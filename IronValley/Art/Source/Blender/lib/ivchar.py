"""
ivchar -- Iron Valley shared CHARACTER helpers (bpy 4.5 LTS, headless).

Companion to ivlib.py (which owns generic materials / baking / export / rendering and must not
be edited from character work).  Everything here is additive and deterministic (no unseeded
randomness).  Used by Art/Source/Blender/characters/*.py.

Sections
--------
  1. Paths and MakeHuman / MPFB2 data (CC0): OBJ loader, frame conversion, targets, macro
     modifier weights (MakeHuman 1.x semantics)
  2. Rig: joint positions from rig.*.json exactly as MPFB interprets them (CUBE = mean of the
     joint cube's vertices, MEAN = mean of listed vertices, VERTEX = one vertex; head / tail /
     roll written to Blender edit bones), weights.*.json loading, influence limiting
  3. Mesh construction from arrays (quads + UVs), hole capping
  4. Posing helpers (world-axis rotations about a bone head, apply pose as rest)
  5. Validation: skin report, hierarchy report, deformation metrics
  6. Clay render helpers for characters
  7. Skinned export re-import check (clean subprocess job, weights included)

Coordinate conventions (project wide, see Docs/ARCHITECTURE.md): metres, Z up, 1 BU = 1 m.
Characters face -Y (Blender "front" view looks along +Y), feet on Z = 0, origin between the feet.
MakeHuman OBJ / target data is Y-up decimetres with the character facing +Z; it is converted
with  p_blender = 0.1 * (x, -z, y)  (a +90 deg rotation about X plus 0.1 scale -- the same
transform anny uses: roma.Linear(0.1 * euler_to_rotmat("X", [90]))).

Run as a script for jobs:  python3 ivchar.py --job /path/job.json
"""

import bpy
import bmesh
import gzip
import itertools
import json
import math
import os
import subprocess
import sys
import tempfile
import time
from mathutils import Vector, Matrix, Quaternion

import numpy as np

IVCHAR_VERSION = "1.0.0"

HERE = os.path.dirname(os.path.abspath(__file__))
IV_ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))        # .../IronValley
MPFB_DIR = os.path.join(IV_ROOT, "Art", "ThirdParty", "mpfb2")


def log(*args):
    print("[ivchar]", *args, flush=True)


# =============================================================================
# 1. MakeHuman / MPFB2 data
# =============================================================================

class ObjMesh:
    """Raw OBJ content: V (N,3) float64 (file frame), VT (M,2), groups {name: {"f": [[vi..]],
    "t": [[ti..]]}} in file order.  Indices are 0-based."""

    def __init__(self, V, VT, groups):
        self.V = V
        self.VT = VT
        self.groups = groups

    def group_vertices(self, name):
        g = self.groups[name]
        return np.unique(np.array([i for f in g["f"] for i in f], dtype=np.int64))


def load_obj(path):
    V, VT, groups = [], [], {}
    g = "noname"
    with open(path) as fh:
        for line in fh:
            s = line.split()
            if not s or s[0].startswith("#"):
                continue
            k = s[0]
            if k == "v":
                V.append((float(s[1]), float(s[2]), float(s[3])))
            elif k == "vt":
                VT.append((float(s[1]), float(s[2])))
            elif k == "g":
                g = s[1]
                groups.setdefault(g, {"f": [], "t": []})
            elif k == "f":
                gg = groups.setdefault(g, {"f": [], "t": []})
                fv, ft = [], []
                for x in s[1:]:
                    p = x.split("/")
                    fv.append(int(p[0]) - 1)
                    ft.append(int(p[1]) - 1 if len(p) > 1 and p[1] else -1)
                gg["f"].append(fv)
                gg["t"].append(ft)
    return ObjMesh(np.array(V, dtype=np.float64), np.array(VT, dtype=np.float64), groups)


def mh_to_blender(a):
    """MakeHuman file frame (Y up, decimetres, facing +Z) -> Blender (Z up, metres, facing -Y)."""
    a = np.asarray(a, dtype=np.float64)
    return 0.1 * np.stack([a[..., 0], -a[..., 2], a[..., 1]], axis=-1)


def load_target(path):
    """MakeHuman .target(.gz): lines 'vertex_index dx dy dz' (file frame).  Returns
    (indices int64 (K,), offsets (K,3) in Blender frame).  Empty files are valid (the
    universal *-averagemuscle-averageweight targets are empty by design)."""
    op = gzip.open if path.endswith(".gz") else open
    idx, d = [], []
    with op(path, "rt") as fh:
        for line in fh:
            s = line.split()
            if len(s) == 4 and not s[0].startswith("#"):
                idx.append(int(s[0]))
                d.append((float(s[1]), float(s[2]), float(s[3])))
    if not idx:
        return np.zeros(0, dtype=np.int64), np.zeros((0, 3))
    return np.array(idx, dtype=np.int64), mh_to_blender(np.array(d))


def years_to_age_value(years):
    """MakeHuman age slider: 1 y -> 0.0, 11 y -> 0.1875, 25 y -> 0.5, 90 y -> 1.0 (piecewise
    linear, see MakeHuman human.py docstring of _setAgeVals)."""
    if years <= 1:
        return 0.0
    if years <= 11:
        return (years - 1) / 10 * 0.1875
    if years <= 25:
        return 0.1875 + (years - 11) / 14 * (0.5 - 0.1875)
    return min(1.0, 0.5 + (years - 25) / 65 * 0.5)


def macro_factors(gender=0.5, age=0.5, muscle=0.5, weight=0.5, height=0.5, proportions=0.5,
                  race=None):
    """Per-component macro weights with MakeHuman 1.x semantics (apps/human.py _set*Vals):
    gender -> male/female, age -> baby/child/young/old, muscle/weight -> min/average/max,
    height -> min/maxheight (none at 0.5), proportions -> uncommon/idealproportions (none at
    0.5), race -> african/asian/caucasian normalised to sum 1."""
    f = {"male": gender, "female": 1.0 - gender}
    if age < 0.5:
        f["old"] = 0.0
        f["baby"] = max(0.0, 1 - age * 5.333)
        f["young"] = max(0.0, (age - 0.1875) * 3.2)
        f["child"] = max(0.0, min(1.0, 5.333 * age) - f["young"])
    else:
        f["baby"] = f["child"] = 0.0
        f["old"] = max(0.0, age * 2 - 1)
        f["young"] = 1.0 - f["old"]
    for n, v in (("muscle", muscle), ("weight", weight)):
        f["max" + n] = max(0.0, v * 2 - 1)
        f["min" + n] = max(0.0, 1 - v * 2)
        f["average" + n] = 1.0 - (f["max" + n] + f["min" + n])
    f["maxheight"] = max(0.0, height * 2 - 1)
    f["minheight"] = max(0.0, 1 - height * 2)
    f["idealproportions"] = max(0.0, proportions * 2 - 1)
    f["uncommonproportions"] = max(0.0, 1 - proportions * 2)
    race = race or {"african": 1 / 3, "asian": 1 / 3, "caucasian": 1 / 3}
    s = sum(race.values())
    for k in ("african", "asian", "caucasian"):
        f[k] = race.get(k, 0.0) / s
    return f


def macro_target_weights(eps=1e-9, **params):
    """{relative target path (under targets/macrodetails, no extension): weight} for the MakeHuman
    macro modifiers: universal-{g}-{a}-{m}-{w}, {race}-{g}-{a}, height/{g}-{a}-{m}-{w}-{h},
    proportions/{g}-{a}-{m}-{w}-{p}.  Each weight is the product of its component factors."""
    f = macro_factors(**params)
    G = ("female", "male")
    A = ("baby", "child", "young", "old")
    M = ("minmuscle", "averagemuscle", "maxmuscle")
    W = ("minweight", "averageweight", "maxweight")
    T = {}
    for g, a, m, w in itertools.product(G, A, M, W):
        base = f[g] * f[a] * f[m] * f[w]
        if base <= eps:
            continue
        T[f"universal-{g}-{a}-{m}-{w}"] = base
        for h in ("minheight", "maxheight"):
            if f[h] > eps:
                T[f"height/{g}-{a}-{m}-{w}-{h}"] = base * f[h]
        if a != "baby":
            for p in ("idealproportions", "uncommonproportions"):
                if f[p] > eps:
                    T[f"proportions/{g}-{a}-{m}-{w}-{p}"] = base * f[p]
    for r in ("african", "asian", "caucasian"):
        for g, a in itertools.product(G, A):
            wt = f[r] * f[g] * f[a]
            if wt > eps:
                T[f"{r}-{g}-{a}"] = wt
    return dict(sorted(T.items()))


def apply_targets(Vb, weights, target_root, suffix=".target.gz"):
    """Vb: (N,3) Blender-frame vertices.  weights: {relpath: w}.  Returns a new array.
    Also returns per-target stats for the record."""
    out = np.array(Vb, dtype=np.float64, copy=True)
    stats = {}
    for rel, w in weights.items():
        i, d = load_target(os.path.join(target_root, rel + suffix))
        if len(i):
            np.add.at(out, i, w * d)
        stats[rel] = {"weight": round(float(w), 6), "vertices": int(len(i))}
    return out, stats


# =============================================================================
# 2. Rig
# =============================================================================

def load_json(path):
    with open(path) as fh:
        return json.load(fh)


def joint_indices(spec, obj):
    s = spec["strategy"]
    if s == "CUBE":
        return obj.group_vertices(spec["cube_name"])
    if s == "MEAN":
        return np.array(spec["vertex_indices"], dtype=np.int64)
    if s == "VERTEX":
        return np.array([spec["vertex_index"]], dtype=np.int64)
    raise NotImplementedError(s)


def compute_bones(rig, Vb, obj, rename=None):
    """rig: parsed rig.*.json (dict bone -> spec, or {"bones": ...}).  Vb: Blender-frame vertices
    AFTER target application (joint cubes move with the targets).  Returns an ordered dict
    name -> {head, tail, roll, parent, use_connect, ...}, parents before children (depth-first
    in file order, as anny's parse_recursively)."""
    rename = rename or {}
    rig = rig.get("bones", rig)
    roots = [n for n, b in rig.items() if not b.get("parent")]
    assert len(roots) == 1, roots
    order = []

    def rec(n):
        order.append(n)
        for c, b in rig.items():
            if b.get("parent") == n and c not in order:
                rec(c)
    rec(roots[0])
    assert len(order) == len(rig)
    out = {}
    for n in order:
        b = rig[n]
        hi = joint_indices(b["head"], obj)
        ti = joint_indices(b["tail"], obj)
        out[rename.get(n, n)] = {
            "head": Vb[hi].mean(0), "tail": Vb[ti].mean(0), "roll": float(b["roll"]),
            "parent": rename.get(b["parent"], b["parent"]) if b.get("parent") else None,
            "use_connect": bool(b.get("use_connect", False)),
            "inherit_scale": b.get("inherit_scale", "FULL"),
            "use_inherit_rotation": bool(b.get("use_inherit_rotation", True)),
            "use_local_location": bool(b.get("use_local_location", True)),
            "source_name": n,
            "head_strategy": b["head"]["strategy"], "tail_strategy": b["tail"]["strategy"],
        }
    return out


def build_armature(name, bones, col=None, display='OCTAHEDRAL'):
    """Create an armature object from compute_bones() output (head/tail/roll in world space,
    armature object at the identity transform)."""
    arm = bpy.data.armatures.new(name)
    arm.display_type = display
    ob = bpy.data.objects.new(name, arm)
    (col or bpy.context.scene.collection).objects.link(ob)
    bpy.context.view_layer.objects.active = ob
    for o in bpy.context.selected_objects:
        o.select_set(False)
    ob.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    ebs = {}
    for n, b in bones.items():
        eb = arm.edit_bones.new(n)
        eb.head = Vector(b["head"])
        eb.tail = Vector(b["tail"])
        eb.roll = b["roll"]
        ebs[n] = eb
    for n, b in bones.items():
        eb = ebs[n]
        if b["parent"]:
            eb.parent = ebs[b["parent"]]
            # connect only when the MPFB flag says so AND the heads coincide
            if b["use_connect"] and (eb.parent.tail - eb.head).length < 1e-6:
                eb.use_connect = True
        eb.inherit_scale = b.get("inherit_scale", "FULL")
        eb.use_inherit_rotation = b.get("use_inherit_rotation", True)
        eb.use_local_location = b.get("use_local_location", True)
    bpy.ops.object.mode_set(mode='OBJECT')
    return ob


def dense_weights_from_json(wjson, bone_names, n_verts, rename=None, vertex_filter=None):
    """weights.*.json -> dense (n_verts, n_bones) float64 array.  vertex_filter: optional
    int array mapping source vertex index -> new index (or -1 to drop)."""
    rename = rename or {}
    W = wjson.get("weights", wjson)
    col = {n: i for i, n in enumerate(bone_names)}
    D = np.zeros((n_verts, len(bone_names)), dtype=np.float64)
    for src_bone, lst in W.items():
        b = rename.get(src_bone, src_bone)
        if b not in col or not lst:
            continue
        arr = np.array(lst, dtype=np.float64)
        vi = arr[:, 0].astype(np.int64)
        wt = arr[:, 1]
        if vertex_filter is not None:
            vi = vertex_filter[vi]
            keep = vi >= 0
            vi, wt = vi[keep], wt[keep]
        np.add.at(D[:, col[b]], vi, wt)
    return D


def limit_and_normalize(D, max_influences=4, prune_below=0.0):
    """Keep the max_influences largest weights per row, drop weights < prune_below, and
    renormalise rows to sum 1.  Returns (new array, stats)."""
    D = np.array(D, dtype=np.float64, copy=True)
    before = (D > 0).sum(1)
    if D.shape[1] > max_influences:
        part = np.argpartition(-D, max_influences, axis=1)[:, max_influences:]
        np.put_along_axis(D, part, 0.0, axis=1)
    if prune_below > 0:
        D[D < prune_below] = 0.0
    s = D.sum(1, keepdims=True)
    zero = (s[:, 0] <= 0)
    s[s <= 0] = 1.0
    D /= s
    return D, {"max_influences_before": int(before.max()) if len(before) else 0,
               "vertices_over_limit_before": int((before > max_influences).sum()),
               "rows_without_weight": int(zero.sum())}


def load_mirror(path, n_verts=None, with_flags=False):
    """hm08.mirror -> int array m with m[v] = mirror partner of v (self for midline verts).
    Lines are 'v partner flag' (flag r / l / m).  with_flags=True also returns the flag array."""
    pairs = []
    with open(path) as fh:
        for line in fh:
            p = line.split()
            if len(p) >= 2:
                pairs.append((int(p[0]), int(p[1]), p[2] if len(p) > 2 else "m"))
    n = n_verts or (max(max(a, b) for a, b, _ in pairs) + 1)
    m = np.arange(n, dtype=np.int64)
    fl = np.array(["m"] * n)
    for a, b, f in pairs:
        if a < n and b < n:
            m[a] = b
            fl[a] = f
    return (m, fl) if with_flags else m


def limit_symmetric(D, bone_names, mirror, flags, max_influences=4):
    """Mirror-exact influence limiting: limit the 'l' and midline vertices, then copy the
    mirrored result to their 'r' partners.  On a midline vertex, a mirror pair of bones that
    would be split by the cut is dropped as a pair.  D should already be symmetric."""
    perm = np.array([bone_names.index(mirror_bone_name(n)) for n in bone_names])
    out = np.zeros_like(D)
    for v in range(len(D)):
        if flags[v] == "r" and mirror[v] != v:
            continue
        row = D[v]
        order = sorted(range(len(row)), key=lambda j: (-round(row[j], 12), bone_names[j]))
        keep = [j for j in order if row[j] > 0][:max_influences]
        if flags[v] != "l" or mirror[v] == v:
            ks = set(keep)
            keep = [j for j in keep if perm[j] in ks]         # midline: pairs only
        r = np.zeros_like(row)
        r[keep] = row[keep]
        if r.sum() <= 0:
            r = row.copy()
        out[v] = r / r.sum()
    for v in range(len(D)):
        if flags[v] == "r" and mirror[v] != v:
            out[v] = out[mirror[v]][perm]
    return out


def mirror_bone_name(n):
    if n.endswith("_l"):
        return n[:-2] + "_r"
    if n.endswith("_r"):
        return n[:-2] + "_l"
    return n


def symmetrize_weights(D, bone_names, mirror):
    """Average each vertex's weights with its mirror vertex's weights (bones mirrored
    _l <-> _r), like anny.models.model_transforms.symmetrize_skinning_weights."""
    perm = [bone_names.index(mirror_bone_name(n)) for n in bone_names]
    Dn = D / np.maximum(D.sum(1, keepdims=True), 1e-12)
    return 0.5 * (Dn + Dn[mirror][:, perm])


def weight_asymmetry(D, bone_names, mirror):
    perm = [bone_names.index(mirror_bone_name(n)) for n in bone_names]
    diff = np.abs(D - D[mirror][:, perm]).max(1)
    return {"max_abs_diff": round(float(diff.max()), 5), "vertices_over_0.01": int((diff > 0.01).sum())}


def bind_mesh(mesh_obj, arm_obj, D, bone_names, threshold=1e-6):
    """Create one vertex group per bone (every bone, so the FBX/glTF skin carries the full
    skeleton), write weights (> threshold) and add an Armature modifier; parent to armature."""
    mesh_obj.vertex_groups.clear()
    for j, n in enumerate(bone_names):
        vg = mesh_obj.vertex_groups.new(name=n)
        col = D[:, j]
        idx = np.nonzero(col > threshold)[0]
        # group by identical weight is slow; add per vertex
        for i in idx.tolist():
            vg.add([i], float(col[i]), 'REPLACE')
    mod = mesh_obj.modifiers.new("Armature", 'ARMATURE')
    mod.object = arm_obj
    mod.use_deform_preserve_volume = False    # plain LBS, same as game engines
    mesh_obj.parent = arm_obj
    mesh_obj.matrix_parent_inverse = Matrix.Identity(4)
    return mod


def read_weights(mesh_obj, bone_names):
    """Dense (n_verts, n_bones) array from vertex groups (by name)."""
    me = mesh_obj.data
    col = {n: i for i, n in enumerate(bone_names)}
    gi2c = {vg.index: col.get(vg.name, -1) for vg in mesh_obj.vertex_groups}
    D = np.zeros((len(me.vertices), len(bone_names)))
    for v in me.vertices:
        for g in v.groups:
            c = gi2c.get(g.group, -1)
            if c >= 0:
                D[v.index, c] += g.weight
    return D


# =============================================================================
# 3. Mesh construction
# =============================================================================

def mesh_from_arrays(name, V, faces, uv_faces=None, VT=None, col=None, smooth=True):
    """V (N,3); faces: list of index lists; uv_faces: parallel list of VT index lists."""
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(map(float, p)) for p in V], [], [list(map(int, f)) for f in faces])
    if uv_faces is not None and VT is not None:
        uvl = me.uv_layers.new(name="UVMap")
        flat = np.array([t for f in uv_faces for t in f], dtype=np.int64)
        # from_pydata keeps polygon/loop order
        uvl.data.foreach_set("uv", VT[flat].astype(np.float32).ravel())
    me.polygons.foreach_set("use_smooth", [smooth] * len(me.polygons))
    me.validate(clean_customdata=False)
    me.update()
    ob = bpy.data.objects.new(name, me)
    (col or bpy.context.scene.collection).objects.link(ob)
    return ob


def mesh_arrays(obj, evaluated=False):
    """World-space vertex coordinates (N,3) of a mesh object (optionally evaluated)."""
    if evaluated:
        dg = bpy.context.evaluated_depsgraph_get()
        ev = obj.evaluated_get(dg)
        me = ev.to_mesh()
        co = np.empty(len(me.vertices) * 3)
        me.vertices.foreach_get("co", co)
        ev.to_mesh_clear()
    else:
        me = obj.data
        co = np.empty(len(me.vertices) * 3)
        me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    M = np.array(obj.matrix_world)
    return co @ M[:3, :3].T + M[:3, 3]


def boundary_loops(obj):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    edges = [e for e in bm.edges if e.is_boundary]
    loops = []
    seen = set()
    for e in edges:
        if e.index in seen:
            continue
        # walk
        loop = [e.verts[0].index]
        cur = e.verts[1]
        prev_e = e
        seen.add(e.index)
        while cur.index != loop[0]:
            loop.append(cur.index)
            nxt = [x for x in cur.link_edges if x.is_boundary and x.index not in seen]
            if not nxt:
                break
            prev_e = nxt[0]
            seen.add(prev_e.index)
            cur = prev_e.other_vert(cur)
        loops.append(loop)
    bm.free()
    return loops


# =============================================================================
# 4. Posing
# =============================================================================

def reset_pose(arm):
    for pb in arm.pose.bones:
        pb.rotation_mode = 'QUATERNION'
        pb.rotation_quaternion = (1, 0, 0, 0)
        pb.location = (0, 0, 0)
        pb.scale = (1, 1, 1)
    bpy.context.view_layer.update()


def rotate_bone_world(arm, bone_name, axis_world, angle_deg):
    """Rotate a pose bone about a WORLD-space axis through its head, on top of its current pose.
    Children follow (FK).  Works in any hierarchy state; call in parent->child order."""
    bpy.context.view_layer.update()
    pb = arm.pose.bones[bone_name]
    pb.rotation_mode = 'QUATERNION'
    Mw = arm.matrix_world @ pb.matrix                     # current world matrix of the bone
    R = Matrix.Rotation(math.radians(angle_deg), 4, Vector(axis_world).normalized())
    head = Mw.to_translation()
    Mnew = Matrix.Translation(head) @ R @ Matrix.Translation(-head) @ Mw
    pb.matrix = arm.matrix_world.inverted() @ Mnew
    bpy.context.view_layer.update()


def rotate_bone_local(arm, bone_name, axis_local, angle_deg):
    """Rotate about an axis expressed in the bone's CURRENT local frame (x, y=along bone, z)."""
    bpy.context.view_layer.update()
    pb = arm.pose.bones[bone_name]
    Mw = arm.matrix_world @ pb.matrix
    ax = (Mw.to_3x3() @ Vector(axis_local)).normalized()
    rotate_bone_world(arm, bone_name, ax, angle_deg)


def bone_world(arm, name, which="head"):
    pb = arm.pose.bones[name]
    M = arm.matrix_world @ pb.matrix
    if which == "head":
        return M.to_translation()
    return M @ Vector((0, pb.bone.length, 0))


def bone_dir(arm, name):
    return (bone_world(arm, name, "tail") - bone_world(arm, name, "head")).normalized()


def rest_world_matrix(arm, name):
    return arm.matrix_world @ arm.data.bones[name].matrix_local


def pose_delta_rotation(arm, name):
    """Rotation (3x3) that takes the bone's REST world orientation to its current POSED one."""
    bpy.context.view_layer.update()
    Mp = (arm.matrix_world @ arm.pose.bones[name].matrix).to_3x3().normalized()
    Mr = rest_world_matrix(arm, name).to_3x3().normalized()
    return Mp @ Mr.inverted()


def rotate_bone_rest_axis(arm, name, axis_rest_world, angle_deg):
    """Rotate a bone about an axis given in the REST world frame, carried along by the motion
    its parent has already made (i.e. an anatomical axis fixed to the parent segment)."""
    pb = arm.pose.bones[name]
    if pb.parent:
        D = pose_delta_rotation(arm, pb.parent.name)
        axis_now = D @ Vector(axis_rest_world)
    else:
        axis_now = Vector(axis_rest_world)
    rotate_bone_world(arm, name, axis_now, angle_deg)


def aim_bone(arm, name, target_dir_world, fraction=1.0):
    """Swing a bone (about its head) so its direction points along target_dir_world (posed)."""
    cur = bone_dir(arm, name)
    tgt = Vector(target_dir_world).normalized()
    q = cur.rotation_difference(tgt)
    ax, ang = q.to_axis_angle()
    if ang > 1e-7:
        rotate_bone_world(arm, name, ax, math.degrees(ang) * fraction)


def angle_between(a, b):
    a = Vector(a).normalized()
    b = Vector(b).normalized()
    return math.degrees(math.acos(max(-1.0, min(1.0, a.dot(b)))))


FINGERS = ("thumb", "index", "middle", "ring", "pinky")


def palm_frame(arm, side):
    """Posed hand frame for side 'l'/'r': (centre, d = wrist->middle knuckle, r = towards the
    thumb side (radial), n = palm normal pointing OUT of the palm).  For the left hand
    n = d x r, for the right hand n = r x d (mirror)."""
    wrist = bone_world(arm, f"hand_{side}", "head")
    mid = bone_world(arm, f"middle_01_{side}", "head")
    idx = bone_world(arm, f"index_01_{side}", "head")
    pky = bone_world(arm, f"pinky_01_{side}", "head")
    d = (mid - wrist).normalized()
    r = (idx - pky)
    r = (r - d * r.dot(d)).normalized()
    n = d.cross(r) if side == "l" else r.cross(d)
    return (wrist + mid) * 0.5, d, r, n.normalized()


def rotate_local(arm, name, axis_local, angle_deg):
    """Compose a rotation about an axis of the bone's CURRENT local frame (intrinsic)."""
    pb = arm.pose.bones[name]
    pb.rotation_mode = 'QUATERNION'
    q = Quaternion(Vector(axis_local), math.radians(angle_deg))
    pb.rotation_quaternion = pb.rotation_quaternion @ q
    bpy.context.view_layer.update()


def pose_hand(arm, side, curl=(0.0, 0.0, 0.0), spread=0.0, thumb=(0.0, 0.0, 0.0, 0.0),
              curl_scale=None):
    """Finger posing on top of the current pose, in the bones' LOCAL axes.

    The MPFB game_engine bone rolls are anatomical (verified: every finger bone's local X is
    the flexion axis to within ~15 deg, positive rotation = flexion on both sides), so:
      curl   = (MCP, PIP, DIP) flexion in deg for index/middle/ring/pinky (local +X)
      spread = abduction of the 01 joints (local Z) -- index towards the thumb, ring and
               pinky away (x1, x1.6), middle fixed; mirrored sign on the right hand
      thumb  = (thumb_01 about X: + folds across the palm / - radial abduction,
                thumb_01 about Z: + swings out in front of the palm (palmar abduction),
                thumb_02 flexion, thumb_03 flexion)
      curl_scale = optional per-finger multiplier dict (e.g. {"pinky": 1.1})."""
    zs = 1.0 if side == "l" else -1.0
    mult = {"index": -1.0, "middle": 0.0, "ring": 1.0, "pinky": 1.6}
    for f in ("index", "middle", "ring", "pinky"):
        k = (curl_scale or {}).get(f, 1.0)
        if spread and mult[f]:
            rotate_local(arm, f"{f}_01_{side}", (0, 0, 1), -spread * mult[f] * zs)
        for i, ang in enumerate(curl):
            if ang:
                rotate_local(arm, f"{f}_{i + 1:02d}_{side}", (1, 0, 0), ang * k)
    t1x, t1z, t2, t3 = thumb
    if t1x:
        rotate_local(arm, f"thumb_01_{side}", (1, 0, 0), t1x)
    if t1z:
        rotate_local(arm, f"thumb_01_{side}", (0, 0, 1), t1z * zs)
    if t2:
        rotate_local(arm, f"thumb_02_{side}", (1, 0, 0), t2)
    if t3:
        rotate_local(arm, f"thumb_03_{side}", (1, 0, 0), t3)


def apply_pose_as_rest(arm, meshes):
    """Bake the current pose into the meshes (apply Armature modifier on a copy of the
    modifier stack) and make it the armature rest pose.  Vertex groups are kept."""
    bpy.context.view_layer.update()
    for me_ob in meshes:
        bpy.context.view_layer.objects.active = me_ob
        for o in bpy.context.selected_objects:
            o.select_set(False)
        me_ob.select_set(True)
        mods = [m for m in me_ob.modifiers if m.type == 'ARMATURE']
        for m in mods:
            name = m.name
            bpy.ops.object.modifier_apply(modifier=name)
            nm = me_ob.modifiers.new(name, 'ARMATURE')
            nm.object = arm
            nm.use_deform_preserve_volume = False
    bpy.context.view_layer.objects.active = arm
    for o in bpy.context.selected_objects:
        o.select_set(False)
    arm.select_set(True)
    bpy.ops.object.mode_set(mode='POSE')
    bpy.ops.pose.armature_apply(selected=False)
    bpy.ops.object.mode_set(mode='OBJECT')
    reset_pose(arm)


# =============================================================================
# 5. Validation
# =============================================================================

# Unreal Engine mannequin (UE4/UE5 "SK_Mannequin") body bone names that the project skeleton
# must contain.  Twist and IK bones of the mannequin are optional and not required here.
UE_MANNEQUIN_CORE = (
    ["root", "pelvis", "spine_01", "spine_02", "spine_03", "neck_01", "head"]
    + [f"{b}_{s}" for s in ("l", "r") for b in ("clavicle", "upperarm", "lowerarm", "hand",
                                                  "thigh", "calf", "foot", "ball")]
    + [f"{f}_{i:02d}_{s}" for s in ("l", "r") for f in ("thumb", "index", "middle", "ring", "pinky")
       for i in (1, 2, 3)]
)

UE_MANNEQUIN_PARENTS = {
    "pelvis": "root", "spine_01": "pelvis", "spine_02": "spine_01", "spine_03": "spine_02",
    "neck_01": "spine_03", "head": "neck_01",
}
for _s in ("l", "r"):
    UE_MANNEQUIN_PARENTS.update({
        f"clavicle_{_s}": "spine_03", f"upperarm_{_s}": f"clavicle_{_s}",
        f"lowerarm_{_s}": f"upperarm_{_s}", f"hand_{_s}": f"lowerarm_{_s}",
        f"thigh_{_s}": "pelvis", f"calf_{_s}": f"thigh_{_s}", f"foot_{_s}": f"calf_{_s}",
        f"ball_{_s}": f"foot_{_s}"})
    for _f in ("thumb", "index", "middle", "ring", "pinky"):
        UE_MANNEQUIN_PARENTS[f"{_f}_01_{_s}"] = f"hand_{_s}"
        UE_MANNEQUIN_PARENTS[f"{_f}_02_{_s}"] = f"{_f}_01_{_s}"
        UE_MANNEQUIN_PARENTS[f"{_f}_03_{_s}"] = f"{_f}_02_{_s}"


def hierarchy_report(arm, expected=UE_MANNEQUIN_CORE, parents=UE_MANNEQUIN_PARENTS):
    bones = arm.data.bones
    names = [b.name for b in bones]
    missing = [n for n in expected if n not in names]
    extra = [n for n in names if n not in expected]
    wrong_parent = []
    for c, p in parents.items():
        if c in bones:
            got = bones[c].parent.name if bones[c].parent else None
            if got != p:
                wrong_parent.append({"bone": c, "expected": p, "got": got})
    roots = [b.name for b in bones if b.parent is None]
    return {"bone_count": len(names), "roots": roots, "missing": missing, "extra": extra,
            "wrong_parent": wrong_parent,
            "ok": not missing and not wrong_parent and roots == ["root"]}


def skin_report(mesh_obj, arm, max_influences=4, tol=1e-4):
    bone_names = [b.name for b in arm.data.bones]
    deform = [b.name for b in arm.data.bones if b.use_deform]
    D = read_weights(mesh_obj, bone_names)
    nz = (D > 0).sum(1)
    s = D.sum(1)
    groups_without_bone = [vg.name for vg in mesh_obj.vertex_groups if vg.name not in bone_names]
    used = [bone_names[j] for j in range(len(bone_names)) if (D[:, j] > 0).any()]
    unused = [n for n in deform if n not in used]
    mods = [m for m in mesh_obj.modifiers if m.type == 'ARMATURE' and m.object == arm]
    return {
        "vertices": int(len(D)), "unweighted_vertices": int((nz == 0).sum()),
        "max_influences": int(nz.max()), "vertices_over_limit": int((nz > max_influences).sum()),
        "influence_histogram": {int(k): int((nz == k).sum()) for k in range(0, int(nz.max()) + 1)},
        "weight_sum_min": round(float(s.min()), 6), "weight_sum_max": round(float(s.max()), 6),
        "vertices_sum_off_by_more_than_tol": int((np.abs(s - 1) > tol).sum()),
        "groups_without_bone": groups_without_bone, "deform_bones_without_weights": unused,
        "armature_modifier": bool(mods),
        "ok": bool((nz == 0).sum() == 0 and (nz > max_influences).sum() == 0
                   and (np.abs(s - 1) <= tol).all() and not groups_without_bone and mods),
    }


def face_metrics(obj, co):
    """Per-face area and normal for world coords co (N,3) using obj's topology."""
    me = obj.data
    me.calc_loop_triangles()
    tris = np.empty(len(me.loop_triangles) * 3, dtype=np.int64)
    me.loop_triangles.foreach_get("vertices", tris)
    tris = tris.reshape(-1, 3)
    a, b, c = co[tris[:, 0]], co[tris[:, 1]], co[tris[:, 2]]
    n = np.cross(b - a, c - a)
    area = 0.5 * np.linalg.norm(n, axis=1)
    nn = n / np.maximum(2 * area[:, None], 1e-20)
    return tris, area, nn


def deformation_report(obj, rest_co, posed_co, region_mask=None):
    """Compare posed vs rest triangles: area ratio distribution, collapsed (<25 %) and
    flipped (normal turned > 150 deg relative to the rigidly-expected orientation is hard to
    know, so we report triangles whose area ratio < 0.25 and edge-length ratio extremes)."""
    tris, a0, _ = face_metrics(obj, rest_co)
    _, a1, _ = face_metrics(obj, posed_co)
    ratio = a1 / np.maximum(a0, 1e-12)
    me = obj.data
    e = np.empty(len(me.edges) * 2, dtype=np.int64)
    me.edges.foreach_get("vertices", e)
    e = e.reshape(-1, 2)
    l0 = np.linalg.norm(rest_co[e[:, 0]] - rest_co[e[:, 1]], axis=1)
    l1 = np.linalg.norm(posed_co[e[:, 0]] - posed_co[e[:, 1]], axis=1)
    lr = l1 / np.maximum(l0, 1e-12)
    if region_mask is not None:
        tm = region_mask[tris].any(1)
        em = region_mask[e].any(1)
        ratio, lr = ratio[tm], lr[em]
    return {
        "tri_area_ratio_min": round(float(ratio.min()), 3),
        "tri_area_ratio_p01": round(float(np.percentile(ratio, 1)), 3),
        "tri_area_ratio_p99": round(float(np.percentile(ratio, 99)), 3),
        "tri_area_ratio_max": round(float(ratio.max()), 3),
        "tris_below_25pct_area": int((ratio < 0.25).sum()),
        "tris_below_10pct_area": int((ratio < 0.10).sum()),
        "edge_len_ratio_min": round(float(lr.min()), 3),
        "edge_len_ratio_max": round(float(lr.max()), 3),
    }


def self_intersections(obj, co, max_report=50):
    """Count intersecting non-adjacent triangle pairs (BVH overlap) for world coords co."""
    from mathutils.bvhtree import BVHTree
    me = obj.data
    polys = [tuple(p.vertices) for p in me.polygons]
    bvh = BVHTree.FromPolygons([tuple(map(float, p)) for p in co], polys, all_triangles=False,
                               epsilon=0.0)
    pairs = bvh.overlap(bvh)
    pv = [set(p) for p in polys]
    real = [(i, j) for i, j in pairs if i < j and not (pv[i] & pv[j])]
    return len(real), real[:max_report]


def mesh_bvh(obj, co=None):
    from mathutils.bvhtree import BVHTree
    co = mesh_arrays(obj) if co is None else co
    polys = [tuple(p.vertices) for p in obj.data.polygons]
    return BVHTree.FromPolygons([tuple(map(float, p)) for p in co], polys, all_triangles=False)


def inside_mesh(bvh, p, dirs=((0, 0, 1), (1, 0, 0), (0, 1, 0), (0.577, 0.577, 0.577), (-0.6, 0.3, -0.74))):
    """Majority vote of ray-parity tests (closed mesh).  Returns (inside, distance_to_surface)."""
    p = Vector(p)
    votes = 0
    for d in dirs:
        d = Vector(d).normalized()
        o = p.copy()
        hits = 0
        for _ in range(200):
            loc, nrm, idx, dist = bvh.ray_cast(o, d)
            if loc is None:
                break
            hits += 1
            o = loc + d * 1e-6
        votes += hits % 2
    nearest = bvh.find_nearest(p)
    return votes * 2 > len(dirs), (nearest[3] if nearest[0] is not None else float("inf"))


def dominant_bone_mask(D, bone_names, names):
    """Vertices whose largest weight belongs to one of `names`."""
    cols = [bone_names.index(n) for n in names if n in bone_names]
    arg = D.argmax(1)
    return np.isin(arg, cols)


# =============================================================================
# 6. Clay render helpers (characters)
# =============================================================================

def clay_material(name="IV_CharClay", color=(0.62, 0.60, 0.57), rough=0.55):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    bs = nt.nodes.new('ShaderNodeBsdfPrincipled')
    bs.inputs['Base Color'].default_value = (*color, 1.0)
    bs.inputs['Roughness'].default_value = rough
    bs.inputs['Specular IOR Level'].default_value = 0.35
    out = nt.nodes.new('ShaderNodeOutputMaterial')
    nt.links.new(bs.outputs[0], out.inputs[0])
    return m


def flat_material(name, color, emission=0.0):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    bs = nt.nodes.new('ShaderNodeBsdfPrincipled')
    bs.inputs['Base Color'].default_value = (*color, 1.0)
    bs.inputs['Roughness'].default_value = 0.6
    if emission:
        bs.inputs['Emission Color'].default_value = (*color, 1.0)
        bs.inputs['Emission Strength'].default_value = emission
    out = nt.nodes.new('ShaderNodeOutputMaterial')
    nt.links.new(bs.outputs[0], out.inputs[0])
    return m


def neutral_lighting(center, size, world=(0.42, 0.42, 0.43), world_strength=0.55, key=1.0):
    """Neutral clay-review light: grey world + soft key (front-left-high), fill (front-right),
    rim (back).  size = subject height (m).  Returns the light objects."""
    w = bpy.data.worlds.get("IV_CharWorld") or bpy.data.worlds.new("IV_CharWorld")
    w.use_nodes = True
    nt = w.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    bg = nt.nodes.new('ShaderNodeBackground')
    bg.inputs['Color'].default_value = (*world, 1.0)
    bg.inputs['Strength'].default_value = world_strength
    out = nt.nodes.new('ShaderNodeOutputWorld')
    nt.links.new(bg.outputs[0], out.inputs[0])
    bpy.context.scene.world = w
    c = Vector(center)
    s = size
    L = []

    def area(name, off, sz, energy):
        ld = bpy.data.lights.new(name, 'AREA')
        ld.size = sz
        ld.energy = energy
        ob = bpy.data.objects.new(name, ld)
        bpy.context.scene.collection.objects.link(ob)
        ob.location = c + Vector(off) * s
        ob.rotation_euler = (c - ob.location).to_track_quat('-Z', 'Y').to_euler()
        L.append(ob)
    e = 260.0 * key * (s / 1.8) ** 2
    area("IVC_Key", (-0.9, -1.4, 0.9), 1.1 * s, e)
    area("IVC_Fill", (1.2, -1.1, 0.2), 1.2 * s, e * 0.40)
    area("IVC_Rim", (0.4, 1.5, 0.8), 0.7 * s, e * 0.55)
    area("IVC_Top", (0.0, 0.0, 1.6), 0.9 * s, e * 0.25)
    return L


def ground_plane(size=6.0, color=(0.36, 0.36, 0.37), z=0.0, name="IVC_Ground"):
    me = bpy.data.meshes.new(name)
    h = size / 2
    me.from_pydata([(-h, -h, z), (h, -h, z), (h, h, z), (-h, h, z)], [], [(0, 1, 2, 3)])
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    me.materials.append(flat_material(name + "_M", color))
    return ob


# =============================================================================
# 7. Skinned re-import check (clean subprocess)
# =============================================================================

def _job_reimport_skinned(job):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    path = job["path"]
    if path.lower().endswith(".fbx"):
        bpy.ops.import_scene.fbx(filepath=path, use_custom_normals=True, ignore_leaf_bones=False,
                                 automatic_bone_orientation=False)
    else:
        bpy.ops.import_scene.gltf(filepath=path)
    bpy.context.view_layer.update()
    objs = list(bpy.context.scene.objects)
    arms = [o for o in objs if o.type == 'ARMATURE']
    shapes = set()
    for a in arms:
        for pb in a.pose.bones:
            if pb.custom_shape:
                shapes.add(pb.custom_shape.name)
    meshes = [o for o in objs if o.type == 'MESH' and o.name not in shapes]
    res = {"ok": True, "path": path, "bytes": os.path.getsize(path),
           "armatures": [a.name for a in arms], "mesh_objects": [m.name for m in meshes]}
    if arms:
        a = arms[0]
        res["armature_object_scale"] = [round(v, 5) for v in a.matrix_world.to_scale()]
        res["bone_count"] = len(a.data.bones)
        res["bones"] = [b.name for b in a.data.bones]
        res["parents"] = {b.name: (b.parent.name if b.parent else None) for b in a.data.bones}
        heads = {b.name: [round(float(x), 4) for x in (a.matrix_world @ b.head_local)]
                 for b in a.data.bones}
        res["bone_heads_world_m"] = heads
    mn = np.array([1e9] * 3)
    mx = -mn
    for m in meshes:
        co = mesh_arrays(m, evaluated=True)
        if len(co):
            mn = np.minimum(mn, co.min(0))
            mx = np.maximum(mx, co.max(0))
    res["bbox_min_m"] = [round(float(v), 4) for v in mn]
    res["bbox_max_m"] = [round(float(v), 4) for v in mx]
    res["dimensions_m"] = [round(float(mx[i] - mn[i]), 4) for i in range(3)]
    sk = {}
    for m in meshes:
        me = m.data
        me.calc_loop_triangles()
        d = {"vertices": len(me.vertices), "tris": len(me.loop_triangles),
             "uv_layers": [u.name for u in me.uv_layers],
             "vertex_groups": len(m.vertex_groups),
             "armature_modifier": any(md.type == 'ARMATURE' for md in m.modifiers)}
        if arms:
            names = [b.name for b in arms[0].data.bones]
            D = read_weights(m, names)
            nz = (D > 0).sum(1)
            s = D.sum(1)
            d.update({"unweighted_vertices": int((nz == 0).sum()), "max_influences": int(nz.max()),
                      "weight_sum_min": round(float(s.min()), 5),
                      "weight_sum_max": round(float(s.max()), 5),
                      "groups_not_bones": [vg.name for vg in m.vertex_groups if vg.name not in names]})
        sk[m.name] = d
    res["meshes"] = sk
    return res


def run_job(job, timeout=900):
    fd, path = tempfile.mkstemp(suffix=".json", prefix="ivcjob_")
    with os.fdopen(fd, "w") as f:
        json.dump(job, f)
    cmd = [sys.executable, os.path.abspath(__file__), "--job", path]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    os.remove(path)
    for line in p.stdout.splitlines()[::-1]:
        if line.startswith("IVCJOB_RESULT "):
            return json.loads(line[len("IVCJOB_RESULT "):])
    raise RuntimeError(f"job failed ({job.get('type')}):\n{p.stdout[-3000:]}\n{p.stderr[-3000:]}")


def reimport_skinned_check(path):
    return run_job({"type": "reimport_skinned", "path": path})


def _job_main(path):
    with open(path) as f:
        job = json.load(f)
    if job["type"] == "reimport_skinned":
        res = _job_reimport_skinned(job)
    else:
        raise ValueError(job["type"])
    print("IVCJOB_RESULT " + json.dumps(res), flush=True)


if __name__ == "__main__":
    if "--job" in sys.argv:
        _job_main(sys.argv[sys.argv.index("--job") + 1])
