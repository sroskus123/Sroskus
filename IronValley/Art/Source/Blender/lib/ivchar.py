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
     roll written to Blender edit bones), weights.*.json loading, mirror symmetrisation,
     twist-bone insertion + weight ramps, (mirror-exact) influence limiting
  3. Mesh construction from arrays (quads + UVs), hole capping
  4. Posing helpers (world / rest-frame / local-axis rotations, aim, hand poses using the
     anatomical MPFB rolls, twist-bone runtime rule drive_twist_bones(), apply pose as rest)
  5. Validation: skin report, hierarchy report, deformation metrics
  6. Clay render helpers for characters
  7. Skinned export re-import check (clean subprocess job, weights included)
  8. Joint and weight refinements (review R1): finger joints re-seated inside the mesh,
     procedural finger weights along the re-seated chains, smoothing of a two-bone weight split
     (toes), joint moves that keep the bone's local X, weight-field diagnostics, hand curl tests
  9. Corrective shapes (review R1): rest-space morph targets solved from Blender's dual-quaternion
     ("Preserve Volume") pose at the elbow / knee / hip, driven by joint angles at runtime
     (drive_correctives; undriven = plain LBS), and the extended deformation metrics
 10. Hand anatomy pass: one flexion axis per finger chain, anatomical joint angles (rest
     offsets, pose_hand_anat), hand contact / penetration metrics

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

IVCHAR_VERSION = "1.2.0"

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


def add_twist_bones(bones, specs):
    """Insert twist bones into a compute_bones() dict.  specs: [(name, parent, f_head, f_tail)]
    -- the twist bone lies on the parent's axis between fractions f_head..f_tail of its length
    and gets the parent's roll, so its local frame equals the parent's (a rotation about local Y
    is a pure twist about the segment axis).  Order is kept parents-first."""
    out = {}
    for n, b in bones.items():
        out[n] = b
        for tn, par, fh, ft in specs:
            if par == n:
                h, t = np.asarray(b["head"]), np.asarray(b["tail"])
                out[tn] = {"head": h + (t - h) * fh, "tail": h + (t - h) * ft, "roll": b["roll"],
                           "parent": par, "use_connect": False, "inherit_scale": "FULL",
                           "use_inherit_rotation": True, "use_local_location": True,
                           "source_name": None, "head_strategy": "TWIST", "tail_strategy": "TWIST"}
    return out


def smoothstep(x):
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3 - 2 * x)


def split_weights_along_bone(D, bone_names, co, head, tail, src, dst, s0, s1, towards_tail=True):
    """Move a share of bone `src`'s weight to `dst` by a smoothstep ramp of the vertex position
    along the src bone axis (s = 0 at head, 1 at tail): share = smoothstep((s-s0)/(s1-s0)) if
    towards_tail else 1 - that.  Row sums are unchanged."""
    D = np.array(D, copy=True)
    h, t = np.asarray(head), np.asarray(tail)
    ax = t - h
    L = np.linalg.norm(ax)
    s = ((co - h) @ ax) / (L * L)
    share = smoothstep((s - s0) / (s1 - s0))
    if not towards_tail:
        share = 1.0 - share
    i, j = bone_names.index(src), bone_names.index(dst)
    moved = D[:, i] * share
    D[:, i] -= moved
    D[:, j] += moved
    return D


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


def twist_angle(q, axis=1):
    """Swing-twist decomposition: signed twist angle (rad) of quaternion q about local axis
    0/1/2 (X/Y/Z)."""
    comp = (q.x, q.y, q.z)[axis]
    return 2.0 * math.atan2(comp, q.w)


def relative_rotation(arm, parent, child):
    """Child's rotation relative to `parent`, in the parent's local frame, with respect to
    the rest relation (identity at rest)."""
    bpy.context.view_layer.update()
    Pp = (arm.matrix_world @ arm.pose.bones[parent].matrix).to_3x3().normalized()
    Cp = (arm.matrix_world @ arm.pose.bones[child].matrix).to_3x3().normalized()
    Pr = rest_world_matrix(arm, parent).to_3x3().normalized()
    Cr = rest_world_matrix(arm, child).to_3x3().normalized()
    rel_pose = Pp.inverted() @ Cp
    rel_rest = Pr.inverted() @ Cr
    # rotation in the parent's frame taking the rest relation to the posed one
    return (rel_pose @ rel_rest.inverted()).to_quaternion()


def drive_twist_bones(arm, sides=("l", "r"), lower=0.5, upper=0.5):
    """Runtime rule for the Iron Valley twist bones (same rule must be used in engine):
      lowerarm_twist_01_s : local Y rotation = lower * twist(hand_s relative to lowerarm_s, Y)
      upperarm_twist_01_s : local Y rotation = -upper * twist(upperarm_s own local rotation, Y)
    (upperarm_twist_01 is a child of upperarm, so it keeps (1 - upper) of the upper-arm roll).
    Returns the applied angles in degrees."""
    out = {}
    for sd in sides:
        la, ha, ua = f"lowerarm_{sd}", f"hand_{sd}", f"upperarm_{sd}"
        lt, ut = f"lowerarm_twist_01_{sd}", f"upperarm_twist_01_{sd}"
        if lt in arm.pose.bones:
            ang = twist_angle(relative_rotation(arm, la, ha), 1) * lower
            pb = arm.pose.bones[lt]
            pb.rotation_mode = 'QUATERNION'
            pb.rotation_quaternion = Quaternion((0, 1, 0), ang)
            out[lt] = round(math.degrees(ang), 2)
        if ut in arm.pose.bones:
            q = arm.pose.bones[ua].matrix_basis.to_quaternion()      # own local rotation
            ang = -twist_angle(q, 1) * upper
            pb = arm.pose.bones[ut]
            pb.rotation_mode = 'QUATERNION'
            pb.rotation_quaternion = Quaternion((0, 1, 0), ang)
            out[ut] = round(math.degrees(ang), 2)
    bpy.context.view_layer.update()
    return out


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


# Twist bones of the UE4 mannequin that the Iron Valley skeleton adds (same names/parents).
UE_MANNEQUIN_TWIST = [f"{b}_twist_01_{s}" for s in ("l", "r") for b in ("upperarm", "lowerarm")]
UE_MANNEQUIN_TWIST_PARENTS = {f"{b}_twist_01_{s}": f"{b}_{s}" for s in ("l", "r")
                              for b in ("upperarm", "lowerarm")}


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
             "armature_modifier": any(md.type == 'ARMATURE' for md in m.modifiers),
             "shape_keys": [k.name for k in me.shape_keys.key_blocks] if me.shape_keys else []}
        if me.shape_keys and len(me.shape_keys.key_blocks) > 1:
            base = np.empty(len(me.vertices) * 3)
            me.shape_keys.key_blocks[0].data.foreach_get("co", base)
            mx = {}
            for k in me.shape_keys.key_blocks[1:]:
                c = np.empty(len(me.vertices) * 3)
                k.data.foreach_get("co", c)
                dd = np.linalg.norm((c - base).reshape(-1, 3), axis=1)
                mx[k.name] = {"moved_vertices": int((dd > 1e-6).sum()), "max_offset": round(float(dd.max()), 5)}
            d["shape_key_offsets_file_units_after_import"] = mx
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



# =============================================================================
# 8. Joint and weight refinements (review R1)
# =============================================================================
#
# Why: in hm08 + MPFB the race 'young' macro targets move the finger surface palmward relative
# to the finger joint cubes, so after the targets every PIP/DIP joint sits 3-5 mm under the
# dorsal skin (dorsal fraction 0.13-0.27), and the MCP cubes sit at the finger webs, 1-1.5 cm
# distal of the knuckles.  A fist then pushes the fingertips through the back of the hand.
# The functions below re-seat the joints from the mesh itself (so they work for any macro
# combination) and rebuild the finger weights around the new joints.

FINGERS4 = ("index", "middle", "ring", "pinky")


def bone_frame(head, tail, roll):
    """Blender rest frame of an edit bone as a 3x3 array (columns x, y = along the bone, z)."""
    y = np.asarray(tail, float) - np.asarray(head, float)
    M = bpy.types.Bone.MatrixFromAxisRoll(Vector(tuple(map(float, y))), float(roll))
    return np.array(M)


def roll_keeping_x(head, tail, x_old):
    """Roll of a bone head->tail whose local X stays as close as possible to x_old (used when a
    joint moves: the anatomical flexion axis of the MPFB roll is kept)."""
    y = np.asarray(tail, float) - np.asarray(head, float)
    y /= np.linalg.norm(y)
    x = np.asarray(x_old, float)
    x = x - y * (x @ y)
    x /= np.linalg.norm(x)
    z = np.cross(x, y)
    M = Matrix([[x[i], y[i], z[i]] for i in range(3)])
    return float(bpy.types.Bone.AxisRollFromMatrix(M, axis=Vector(tuple(map(float, y))))[1])


def triangulate(faces):
    return np.array([(f[0], f[k], f[k + 1]) for f in faces for k in range(1, len(f) - 1)],
                    dtype=np.int64)


def bvh_from_arrays(V, tris):
    from mathutils.bvhtree import BVHTree
    return BVHTree.FromPolygons([tuple(map(float, p)) for p in V],
                                [tuple(map(int, t)) for t in tris], all_triangles=True)


def _ray_dist(bvh, p, d):
    hit = bvh.ray_cast(Vector(tuple(map(float, p))), Vector(tuple(map(float, d))))
    if hit[0] is None:
        raise RuntimeError(f"ray from {tuple(np.round(p, 4))} along {tuple(np.round(d, 3))} hit nothing")
    return float(hit[3])


def palm_length(bones, s):
    """Wrist joint -> middle-finger MCP (as computed by MPFB, before re-seating)."""
    return float(np.linalg.norm(np.asarray(bones[f"middle_01_{s}"]["head"], float)
                                - np.asarray(bones[f"hand_{s}"]["head"], float)))


# Lengths are metres at the reference build (palm length 0.1164 m) and scale with the palm.
FINGER_RESEAT_DEFAULTS = dict(ref_palm=0.1164, mcp_shift=-0.012, pip_shift=0.003, dip_shift=0.005,
                              mcp_dorsal_frac=0.35, ip_dorsal_frac=0.45, lateral_centre=True)


def reseat_finger_joints(bones, V, tris, sides=("l", "r"), palm=None, **params):
    """Re-seat finger / thumb joints of a compute_bones() dict inside the mesh V (in place).

    For every head of index/middle/ring/pinky _01.._03 and thumb _02/_03 (thumb_01 = CMC, deep in
    the thenar, is kept):
      1. move along the bone's own axis (fingers only): MCP by mcp_shift (negative = proximal,
         into the palm, to the knuckle), PIP by pip_shift, DIP by dip_shift (scaled by the palm
         length / ref_palm);
      2. move along the bone's local Z (MPFB rolls: local X = flexion axis, +Z = palmar side) to
         the given fraction of the mesh thickness measured from the dorsal surface (rays +-Z);
      3. PIP/DIP/thumb IP: centre between the side surfaces along local X (rays +-X, only when
         both hits are within 2 cm).
    The parent's tail in the same chain follows its child's head; rolls are recomputed so each
    bone keeps its local X (the anatomical flexion axis).  The _03 tail (fingertip marker) is
    kept.  All positions are measured on the ORIGINAL joints, then applied.  Returns a report."""
    P = dict(FINGER_RESEAT_DEFAULTS, **params)
    bvh = bvh_from_arrays(V, tris)
    frames = {n: bone_frame(b["head"], b["tail"], b["roll"]) for n, b in bones.items()}
    new, rep = {}, {"params": {k: (list(v) if isinstance(v, tuple) else v) for k, v in P.items()},
                    "joints": {}}
    for s in sides:
        pl = palm_length(bones, s) if palm is None else palm[s]
        k = pl / P["ref_palm"]
        rep[f"palm_length_{s}_m"] = round(pl, 5)
        for f in ("thumb",) + FINGERS4:
            for i in (1, 2, 3):
                if f == "thumb" and i == 1:
                    continue
                n = f"{f}_{i:02d}_{s}"
                F = frames[n]
                x, y, z = F[:, 0], F[:, 1], F[:, 2]
                j0 = np.asarray(bones[n]["head"], float)
                a0, d0 = _ray_dist(bvh, j0, z), _ray_dist(bvh, j0, -z)
                sh = 0.0 if f == "thumb" else k * {1: P["mcp_shift"], 2: P["pip_shift"], 3: P["dip_shift"]}[i]
                j = j0 + y * sh
                a, d = _ray_dist(bvh, j, z), _ray_dist(bvh, j, -z)
                fr = P["mcp_dorsal_frac"] if i == 1 else P["ip_dorsal_frac"]
                dz = fr * (a + d) - d
                j = j + z * dz
                lat = 0.0
                if P["lateral_centre"] and i > 1:
                    try:
                        l1, l2 = _ray_dist(bvh, j, x), _ray_dist(bvh, j, -x)
                        if l1 < 0.02 and l2 < 0.02:
                            lat = 0.5 * (l1 - l2)
                            j = j + x * lat
                    except RuntimeError:
                        pass
                new[n] = j
                rep["joints"][n] = {"along_m": round(float(sh), 5), "palmar_m": round(float(dz), 5),
                                    "lateral_m": round(float(lat), 5),
                                    "thickness_m": round(a + d, 5),
                                    "dorsal_frac_before": round(d0 / (a0 + d0), 3),
                                    "dorsal_frac_after": round(fr, 3),
                                    "moved_m": round(float(np.linalg.norm(j - j0)), 5)}
    seg_before = {}
    for s in sides:
        for f in ("thumb",) + FINGERS4:
            ch = [f"{f}_{i:02d}_{s}" for i in (1, 2, 3)]
            seg_before[f"{f}_{s}"] = [float(np.linalg.norm(np.asarray(bones[c]["tail"]) - np.asarray(bones[c]["head"]))) for c in ch]
    touched = set()
    for n, j in new.items():
        bones[n]["head"] = j
        bones[n]["head_strategy"] = "RESEAT"
        par = bones[n]["parent"]
        if par and par.split("_")[0] == n.split("_")[0]:
            bones[par]["tail"] = j
            bones[par]["tail_strategy"] = "RESEAT"
            touched.add(par)
        touched.add(n)
    for n in sorted(touched):
        b = bones[n]
        b["roll"] = roll_keeping_x(b["head"], b["tail"], frames[n][:, 0])
    rep["segments_cm"] = {}
    for key, before in seg_before.items():
        f, s = key.rsplit("_", 1)
        ch = [f"{f}_{i:02d}_{s}" for i in (1, 2, 3)]
        after = [float(np.linalg.norm(np.asarray(bones[c]["tail"]) - np.asarray(bones[c]["head"]))) for c in ch]
        rep["segments_cm"][key] = {"before": [round(v * 100, 2) for v in before],
                                   "after": [round(v * 100, 2) for v in after],
                                   "proximal_over_middle_after": round(after[0] / after[1], 3)}
    return rep


def move_joint(bones, name, delta):
    """Move the head of `name` by delta (world, m) keeping its tail and local X; a connected
    parent's tail follows."""
    b = bones[name]
    x_old = bone_frame(b["head"], b["tail"], b["roll"])[:, 0]
    old = np.asarray(b["head"], float)
    b["head"] = old + np.asarray(delta, float)
    b["roll"] = roll_keeping_x(b["head"], b["tail"], x_old)
    par = b["parent"]
    if par and np.linalg.norm(np.asarray(bones[par]["tail"], float) - old) < 1e-6:
        pb = bones[par]
        px = bone_frame(pb["head"], pb["tail"], pb["roll"])[:, 0]
        pb["tail"] = np.array(b["head"])
        pb["roll"] = roll_keeping_x(pb["head"], pb["tail"], px)


def finger_chain(bones, f, s):
    """(bone names, 4 chain points head01, head02, head03, tail03, frames of the 3 bones)."""
    names = [f"{f}_{i:02d}_{s}" for i in (1, 2, 3)]
    P = [np.asarray(bones[n]["head"], float) for n in names] + [np.asarray(bones[names[-1]]["tail"], float)]
    F = [bone_frame(bones[n]["head"], bones[n]["tail"], bones[n]["roll"]) for n in names]
    return names, P, F


def chain_coords(co, P, F):
    """Nearest-point coordinates of points co (N,3) on the chain polyline P0..P3 (segment 0 is
    extended proximally, segment 2 distally): arc position (m, 0 at P0, negative proximal),
    lateral offset (along the segment's local X) and palmar offset (along local Z)."""
    n = len(co)
    best = np.full(n, np.inf)
    arc, lat, pal = np.zeros(n), np.zeros(n), np.zeros(n)
    cum = 0.0
    for k in range(3):
        a, b = P[k], P[k + 1]
        L = float(np.linalg.norm(b - a))
        u = (b - a) / L
        t = (co - a) @ u
        tc = np.clip(t, -np.inf if k == 0 else 0.0, np.inf if k == 2 else L)
        rel = co - (a + np.outer(tc, u))
        dd = np.linalg.norm(rel, axis=1)
        m = dd < best - 1e-12
        best[m] = dd[m]
        arc[m] = cum + tc[m]
        lat[m] = rel[m] @ F[k][:, 0]
        pal[m] = rel[m] @ F[k][:, 2]
        cum += L
    return arc, lat, pal


FINGER_WEIGHT_DEFAULTS = dict(ref_palm=0.1164, mcp_dorsal=(-0.002, 0.014), mcp_palmar=(-0.008, 0.008),
                              side_blend=0.004, ip_window=0.30, lateral_rho=0.005,
                              lateral_cut=(0.012, 0.020), keep_source_ownership=True)


def procedural_finger_weights(D, bone_names, co, bones, s, palm=None, **params):
    """Rebuild the weights of hand_s and the four finger chains around the (re-seated) joints.

    Only the weight mass the vertex already gives to hand + index/middle/ring/pinky chains is
    redistributed; every other bone (thumb, forearm, twist) keeps its weight, so the thumb and
    the wrist are unchanged.  Per vertex and finger:
      lateral share  = where the source weights already give the vertex to finger chains (the
                       fingers and webs), the source's split among the fingers is kept; in the
                       palm (source: pure hand) a Gaussian of the lateral distance to each finger
                       axis (rho), normalised over the four fingers; faded out beyond lateral_cut
                       of the nearest axis (thumb web, palm edges stay on hand);
      hand -> finger = smoothstep ramp of the arc position around the new MCP, window
                       mcp_dorsal on the back, mcp_palmar on the palm side (blended over
                       side_blend): the knuckles stay mostly with the hand, the palmar pad at
                       the finger base goes with the finger;
      01 / 02 / 03   = smoothstep ramps centred on the PIP / DIP, half-width ip_window x the
                       shorter adjacent segment.
    Lengths are metres at the reference palm (ref_palm) and scale with the palm length."""
    P_ = dict(FINGER_WEIGHT_DEFAULTS, **params)
    pl = palm_length_from(bones, s) if palm is None else palm
    k = pl / P_["ref_palm"]
    D = np.array(D, dtype=np.float64, copy=True)
    col = {n: i for i, n in enumerate(bone_names)}
    ih = col[f"hand_{s}"]
    ich = [col[f"{f}_{i:02d}_{s}"] for f in FINGERS4 for i in (1, 2, 3)]
    R = D[:, [ih] + ich].sum(1)
    vm = np.nonzero(R > 1e-9)[0]
    c = co[vm]
    lam = np.zeros((len(vm), 4))
    Ff = np.zeros((len(vm), 4))
    S3 = np.zeros((len(vm), 4, 3))
    absl = np.zeros((len(vm), 4))
    rho = P_["lateral_rho"] * k
    for q, f in enumerate(FINGERS4):
        _, P, F = finger_chain(bones, f, s)
        arc, lat, pal = chain_coords(c, P, F)
        absl[:, q] = np.abs(lat)
        lam[:, q] = np.exp(-(lat ** 2) / (2 * rho ** 2))
        wp = smoothstep(pal / (P_["side_blend"] * k) * 0.5 + 0.5)            # 0 dorsal .. 1 palmar
        t0 = k * (P_["mcp_dorsal"][0] * (1 - wp) + P_["mcp_palmar"][0] * wp)
        t1 = k * (P_["mcp_dorsal"][1] * (1 - wp) + P_["mcp_palmar"][1] * wp)
        Ff[:, q] = smoothstep((arc - t0) / (t1 - t0))
        L = [float(np.linalg.norm(P[i + 1] - P[i])) for i in range(3)]
        s1, s2 = L[0], L[0] + L[1]
        w1 = P_["ip_window"] * min(L[0], L[1])
        w2 = P_["ip_window"] * min(L[1], L[2])
        b1 = smoothstep((arc - (s1 - w1)) / (2 * w1))
        b2 = smoothstep((arc - (s2 - w2)) / (2 * w2))
        S3[:, q, 0] = 1 - b1
        S3[:, q, 1] = b1 * (1 - b2)
        S3[:, q, 2] = b1 * b2
    ls = lam.sum(1, keepdims=True)
    lam = np.where(ls > 1e-300, lam / np.maximum(ls, 1e-300), 0.0)
    # where the SOURCE weights already assign the vertex to finger chains (the fingers and the
    # webs, distal of MPFB's MCP), keep the source's lateral ownership; the geometric split is
    # only used where the source had pure hand weight (the palm / knuckles the new MCP reaches)
    Csrc = np.stack([D[vm][:, [col[f"{f}_{i:02d}_{s}"] for i in (1, 2, 3)]].sum(1) for f in FINGERS4], 1)
    csum = Csrc.sum(1)
    own = np.where(csum[:, None] > 1e-12, Csrc / np.maximum(csum, 1e-12)[:, None], 0.0)
    alpha = np.clip(csum / np.maximum(R[vm], 1e-12), 0.0, 1.0)
    if P_.get("keep_source_ownership", True):
        lam = alpha[:, None] * own + (1.0 - alpha[:, None]) * lam
    lc0, lc1 = P_["lateral_cut"][0] * k, P_["lateral_cut"][1] * k
    g = 1.0 - smoothstep((absl.min(1) - lc0) / (lc1 - lc0))
    share = lam * Ff * g[:, None]
    before = D[vm][:, [ih] + ich].copy()
    D[vm[:, None], np.array([ih] + ich)[None, :]] = 0.0
    D[vm, ih] = R[vm] * (1.0 - share.sum(1))
    for q, f in enumerate(FINGERS4):
        for i in range(3):
            D[vm, col[f"{f}_{i + 1:02d}_{s}"]] += R[vm] * share[:, q] * S3[:, q, i]
    after = D[vm][:, [ih] + ich]
    rep = {"vertices_rebuilt": int(len(vm)), "palm_length_m": round(pl, 5),
           "mean_abs_change": round(float(np.abs(after - before).sum(1).mean()), 5),
           "max_abs_change": round(float(np.abs(after - before).sum(1).max()), 5),
           "params": {kk: (list(v) if isinstance(v, tuple) else v) for kk, v in P_.items()}}
    return D, rep


def palm_length_from(bones, s):
    return palm_length(bones, s)


def mesh_neighbours(faces, n):
    """Vertex adjacency (polygon edges) as a list of int arrays."""
    nb = [set() for _ in range(n)]
    for f in faces:
        m = len(f)
        for i in range(m):
            a, b = int(f[i]), int(f[(i + 1) % m])
            nb[a].add(b)
            nb[b].add(a)
    return [np.array(sorted(x), dtype=np.int64) for x in nb]


def smooth_weight_pair(D, bone_names, nbrs, a, b, rings=3, iters=10, alpha=0.5, protect=None):
    """Smooth the split between bones a and b (share q = w_b / (w_a + w_b)) with Laplacian
    iterations over their blend zone grown by `rings` edge rings.  The per-vertex sum w_a + w_b
    and every other bone are unchanged (so row sums stay 1).  Vertices outside the zone act as
    fixed boundary values.  protect: optional bool mask of vertices never changed."""
    D = np.array(D, dtype=np.float64, copy=True)
    ia, ib = bone_names.index(a), bone_names.index(b)
    m = D[:, ia] + D[:, ib]
    has = m > 1e-9
    q = np.where(has, D[:, ib] / np.maximum(m, 1e-12), 0.0)
    zone = has & (D[:, ia] > 1e-6) & (D[:, ib] > 1e-6)
    for _ in range(rings):
        g = zone.copy()
        for v in np.nonzero(zone)[0]:
            g[nbrs[v]] = True
        zone = g & has
    if protect is not None:
        zone &= ~protect
    idx = np.nonzero(zone)[0]
    nl = [nbrs[v][has[nbrs[v]]] for v in idx]
    for _ in range(iters):
        qn = q.copy()
        for v, nv in zip(idx, nl):
            if len(nv):
                qn[v] = (1 - alpha) * q[v] + alpha * q[nv].mean()
        q = qn
    D[idx, ib] = m[idx] * q[idx]
    D[idx, ia] = m[idx] * (1.0 - q[idx])
    return D, {"pair": [a, b], "zone_vertices": int(len(idx)), "rings": rings, "iterations": iters,
               "alpha": alpha}


def smooth_weight_group(D, bone_names, nbrs, group, rings=1, iters=6, alpha=0.5, mixed=1e-3):
    """Laplacian smoothing of the split among the bones in `group` (shares q_k = w_k / sum) over
    the vertices where at least two of them carry weight > `mixed`, grown by `rings` edge
    rings.  The group's per-vertex mass and all other bones are unchanged."""
    D = np.array(D, dtype=np.float64, copy=True)
    cols = [bone_names.index(b) for b in group]
    G = D[:, cols]
    m = G.sum(1)
    has = m > 1e-9
    Q = np.where(has[:, None], G / np.maximum(m, 1e-12)[:, None], 0.0)
    zone = has & ((G > mixed).sum(1) >= 2)
    for _ in range(rings):
        g = zone.copy()
        for v in np.nonzero(zone)[0]:
            g[nbrs[v]] = True
        zone = g & has
    idx = np.nonzero(zone)[0]
    nl = [nbrs[v][has[nbrs[v]]] for v in idx]
    for _ in range(iters):
        Qn = Q.copy()
        for v, nv in zip(idx, nl):
            if len(nv):
                Qn[v] = (1 - alpha) * Q[v] + alpha * Q[nv].mean(0)
        Q = Qn
    Q[idx] /= np.maximum(Q[idx].sum(1, keepdims=True), 1e-12)
    D[np.ix_(idx, cols)] = m[idx, None] * Q[idx]
    return D, {"group": list(group), "zone_vertices": int(len(idx)), "rings": rings,
               "iterations": iters, "alpha": alpha}


def weight_spikes(D, bone_names, nbrs, thr=0.3):
    """Vertices whose weight for some bone differs from the mean of its neighbours by > thr
    (the R1 review metric), and the largest weight gradient per cm along edges per bone."""
    Wn = np.zeros_like(D)
    deg = np.array([len(x) for x in nbrs], dtype=np.float64)
    for v, nv in enumerate(nbrs):
        if len(nv):
            Wn[v] = D[nv].mean(0)
    sp = np.abs(D - Wn)
    bad = np.nonzero(sp.max(1) > thr)[0]
    by = {}
    for v in bad:
        n = bone_names[int(sp[v].argmax())]
        by[n] = by.get(n, 0) + 1
    return {"threshold": thr, "count": int(len(bad)), "by_bone": dict(sorted(by.items())),
            "count_over_0.2": int((sp.max(1) > 0.2).sum()), "_deg_min": int(deg.min())}


def weight_gradient_max(D, bone_names, co, faces, bones=None):
    """Largest |dw| per cm along mesh edges, per bone (or the listed bones)."""
    e = set()
    for f in faces:
        m = len(f)
        for i in range(m):
            a, b = int(f[i]), int(f[(i + 1) % m])
            e.add((min(a, b), max(a, b)))
    e = np.array(sorted(e), dtype=np.int64)
    L = np.linalg.norm(co[e[:, 0]] - co[e[:, 1]], axis=1) * 100.0
    cols = range(len(bone_names)) if bones is None else [bone_names.index(b) for b in bones]
    out = {}
    for j in cols:
        g = np.abs(D[e[:, 0], j] - D[e[:, 1], j]) / np.maximum(L, 1e-9)
        out[bone_names[j]] = round(float(g.max()), 3)
    return out



def finger_joint_depths(arm, body, co=None, sides=("l", "r")):
    """Independent check of joint placement on the REST mesh: for every finger joint (heads of
    index..pinky _01.._03, thumb _02/_03) the distances to the palmar / dorsal surface along the
    bone's local +Z / -Z and to the side surfaces along +-X; dorsal_frac = dorsal / (palmar +
    dorsal) (0 = on the back of the finger, 0.5 = centred)."""
    reset_pose(arm)
    co = mesh_arrays(body, evaluated=True) if co is None else co
    me = body.data
    me.calc_loop_triangles()
    tris = np.empty(len(me.loop_triangles) * 3, dtype=np.int64)
    me.loop_triangles.foreach_get("vertices", tris)
    bvh = bvh_from_arrays(co, tris.reshape(-1, 3))
    out = {}
    for s in sides:
        for f in ("thumb",) + FINGERS4:
            for i in (1, 2, 3):
                if f == "thumb" and i == 1:
                    continue
                n = f"{f}_{i:02d}_{s}"
                M = np.array((arm.matrix_world @ arm.data.bones[n].matrix_local).to_3x3())
                x, z = M[:, 0] / np.linalg.norm(M[:, 0]), M[:, 2] / np.linalg.norm(M[:, 2])
                j = np.array(arm.matrix_world @ arm.data.bones[n].head_local)
                a, d = _ray_dist(bvh, j, z), _ray_dist(bvh, j, -z)
                r = {"palmar_mm": round(a * 1000, 2), "dorsal_mm": round(d * 1000, 2),
                     "dorsal_frac": round(d / (a + d), 3)}
                if i > 1:
                    try:
                        r["side_mm"] = [round(_ray_dist(bvh, j, x) * 1000, 2), round(_ray_dist(bvh, j, -x) * 1000, 2)]
                    except RuntimeError:
                        pass
                out[n] = r
    return out

# ---- hand curl tests (validation) -----------------------------------------------------------

def hand_frame_rest(arm, s):
    """REST hand frame: wrist, d = wrist->middle MCP, r = radial, p = palm normal OUT of the palm."""
    H = lambda n: arm.matrix_world @ arm.data.bones[n].head_local       # noqa: E731
    w, m = H(f"hand_{s}"), H(f"middle_01_{s}")
    d = (m - w).normalized()
    r = H(f"index_01_{s}") - H(f"pinky_01_{s}")
    r = (r - d * r.dot(d)).normalized()
    p = d.cross(r) if s == "l" else r.cross(d)
    return w, d, r, p.normalized()


def curl_fingers(arm, s, mcp, pip, dip, hinge="anatomical"):
    """Curl index..pinky (MCP, PIP, DIP deg) on top of the current pose.
    hinge='anatomical': axis = rest segment direction x palm normal (independent of the bone
    rolls; the R1 reviewer's method); hinge='local': the bones' local +X (ivchar.pose_hand)."""
    if hinge == "local":
        for f in FINGERS4:
            for i, a in ((1, mcp), (2, pip), (3, dip)):
                if a:
                    rotate_local(arm, f"{f}_{i:02d}_{s}", (1, 0, 0), a)
        return
    _, _, _, p = hand_frame_rest(arm, s)
    H = lambda n: arm.matrix_world @ arm.data.bones[n].head_local       # noqa: E731
    T = lambda n: arm.matrix_world @ arm.data.bones[n].tail_local       # noqa: E731
    for f in FINGERS4:
        for i, a in ((1, mcp), (2, pip), (3, dip)):
            n = f"{f}_{i:02d}_{s}"
            dd = ((H(f"{f}_{i + 1:02d}_{s}") if i < 3 else T(n)) - H(n)).normalized()
            pp = (p - dd * p.dot(dd)).normalized()
            ax = dd.cross(pp)
            par = arm.pose.bones[n].parent.name
            rotate_bone_world(arm, n, pose_delta_rotation(arm, par) @ ax, a)


def hand_curl_metrics(arm, body, s, curl, hinge="anatomical", rest=None, tris=None, dom=None):
    """R1 HAND-01 metrics for a finger curl (hand bone not posed):
      verts_beyond_dorsal : finger (_02/_03-dominated) vertices beyond the REST dorsal hand
                            surface along -palm normal (fingertips through the back of the hand)
      finger_x_dorsal_pairs / finger_x_palm_pairs / tip_x_palm_pairs : overlapping face pairs
      tip_gap_to_palm_m   : smallest distance of a distal-segment vertex to the palm faces."""
    from mathutils.bvhtree import BVHTree
    names = [b.name for b in arm.data.bones]
    if dom is None:
        dom = np.array(names)[read_weights(body, names).argmax(1)]
    reset_pose(arm)
    if rest is None:
        rest = mesh_arrays(body, evaluated=True)
    if tris is None:
        me = body.data
        me.calc_loop_triangles()
        tris = np.empty(len(me.loop_triangles) * 3, dtype=np.int64)
        me.loop_triangles.foreach_get("vertices", tris)
        tris = tris.reshape(-1, 3)
    w, d, r, p = hand_frame_rest(arm, s)
    pn = np.array(p)
    a, b, c = rest[tris[:, 0]], rest[tris[:, 1]], rest[tris[:, 2]]
    N0 = np.cross(b - a, c - a)
    N0 /= np.maximum(np.linalg.norm(N0, axis=1)[:, None], 1e-20)
    tdom = dom[tris[:, 0]]
    isH = tdom == f"hand_{s}"
    dors = np.nonzero(isH & (N0 @ -pn > 0.5))[0]
    palm = np.nonzero(isH & (N0 @ pn > 0.5))[0]
    fing = np.nonzero(np.isin(tdom, [f"{f}_{k:02d}_{s}" for f in FINGERS4 for k in (2, 3)]))[0]
    tipf = np.nonzero(np.isin(tdom, [f"{f}_03_{s}" for f in FINGERS4]))[0]
    curl_fingers(arm, s, *curl, hinge=hinge)
    co = mesh_arrays(body, evaluated=True)
    bv = lambda idx, cc: BVHTree.FromPolygons([tuple(map(float, x)) for x in cc],   # noqa: E731
                                              [tuple(map(int, t)) for t in tris[idx]], all_triangles=True)
    bf, bd, bp, bt = bv(fing, co), bv(dors, co), bv(palm, co), bv(tipf, co)
    res = {"curl_mcp_pip_dip_deg": list(curl), "hinge": hinge,
           "finger_x_dorsal_pairs": len(bf.overlap(bd)), "finger_x_palm_pairs": len(bf.overlap(bp)),
           "tip_x_palm_pairs": len(bt.overlap(bp))}
    brest = bv(dors, rest)
    beyond, maxb = 0, 0.0
    for v in np.unique(tris[fing].ravel()):
        q = Vector(tuple(map(float, co[v])))
        hit = brest.ray_cast(q + p * 0.05, -p)
        if hit[0] is not None:
            dist = (q - hit[0]).dot(-p)
            if dist > 0:
                beyond += 1
                maxb = max(maxb, dist)
    res["verts_beyond_dorsal"] = int(beyond)
    res["max_beyond_dorsal_m"] = round(float(maxb), 5)
    gap = min(bp.find_nearest(Vector(tuple(map(float, co[v]))))[3] for v in np.unique(tris[tipf].ravel()))
    res["tip_gap_to_palm_m"] = round(float(gap), 5)
    reset_pose(arm)
    return res



# =============================================================================
# 9. Corrective shapes (review R1)
# =============================================================================
#
# Linear blend skinning collapses a hinge joint at large flexion: a vertex blended 50/50 between
# two bones rotated by theta lands on the chord, at cos(theta/2) of its distance to the axis
# (elbow at 140 deg: 0.34), which cuts the olecranon / knee front into a wedge and folds the
# crease.  Dual-quaternion skinning rotates such a vertex by the blended angle instead.  Game
# engines skin with LBS, so the DQS shape is stored as a rest-space morph target:
#     LBS(v + d) = LBS(v) + M_v d   with  M_v = sum_i w_i R_i   ->   d = M_v^-1 (x_dqs - x_lbs)
# which reproduces the DQS pose exactly at the solved angle.  Two shapes per joint (a mid and a
# high angle) are blended piecewise-linearly by the joint angle (drive_correctives).  Without a
# driver the weights stay 0 and the mesh deforms exactly as plain LBS.

def skinning_rotations(arm):
    """Per-bone 3x3 deformation rotation (pose @ rest^-1, world) for the current pose."""
    MW = arm.matrix_world
    MWi = MW.inverted()
    return {pb.name: np.array((MW @ pb.matrix @ pb.bone.matrix_local.inverted() @ MWi).to_3x3())
            for pb in arm.pose.bones}


def dqs_offsets(arm, body, D, bone_names):
    """Rest-space offsets that turn the current plain-LBS pose of `body` into Blender's DQS
    ('Preserve Volume') pose.  D: dense (V, B) weights in bone_names order.
    Returns (delta (V,3), x_lbs, x_dqs)."""
    mods = [m for m in body.modifiers if m.type == 'ARMATURE']
    for m in mods:
        m.use_deform_preserve_volume = False
    bpy.context.view_layer.update()
    x_lbs = mesh_arrays(body, evaluated=True)
    for m in mods:
        m.use_deform_preserve_volume = True
    bpy.context.view_layer.update()
    x_dqs = mesh_arrays(body, evaluated=True)
    for m in mods:
        m.use_deform_preserve_volume = False
    bpy.context.view_layer.update()
    R = skinning_rotations(arm)
    Rs = np.stack([R[n] for n in bone_names])
    diff = x_dqs - x_lbs
    idx = np.nonzero(np.linalg.norm(diff, axis=1) > 1e-7)[0]
    delta = np.zeros_like(diff)
    if len(idx):
        M = np.einsum('vb,bij->vij', D[idx], Rs)
        delta[idx] = np.linalg.solve(M, diff[idx][..., None])[..., 0]
    return delta, x_lbs, x_dqs


def ensure_basis(body):
    if body.data.shape_keys is None:
        body.shape_key_add(name="Basis", from_mix=False)
    return body.data.shape_keys.key_blocks[0]


def add_offset_shape(body, name, delta, eps=1e-6):
    """Relative shape key = Basis + delta (offsets below eps are dropped so exporters can
    write sparse data).  Returns (key, number of moved vertices)."""
    basis = ensure_basis(body)
    n = len(body.data.vertices)
    co = np.empty(n * 3)
    basis.data.foreach_get("co", co)
    d = np.array(delta, dtype=np.float64, copy=True)
    d[np.linalg.norm(d, axis=1) < eps] = 0.0
    key = body.data.shape_keys.key_blocks.get(name) or body.shape_key_add(name=name, from_mix=False)
    key.relative_key = basis
    key.data.foreach_set("co", (co.reshape(-1, 3) + d).ravel())
    key.value = 0.0
    key.slider_min, key.slider_max = 0.0, 1.0
    return key, int((np.linalg.norm(d, axis=1) > 0).sum())


def _bone_dir_posed(arm, n):
    return bone_dir(arm, n)


def hinge_angle(arm, parent, child):
    """Angle (deg) between two bones' posed directions (elbow: upperarm/lowerarm, knee:
    thigh/calf).  Includes the rest-pose bend."""
    return angle_between(_bone_dir_posed(arm, parent), _bone_dir_posed(arm, child))


def hip_flexion_angle(arm, s):
    """Signed hip flexion (deg) of thigh_s relative to its rest orientation in the pelvis frame:
    rotation of the thigh direction about the pelvis' lateral axis (rest world X carried by
    the pelvis), positive = thigh forward / up.  Abduction and axial rotation are ignored."""
    Dp = pose_delta_rotation(arm, "pelvis")
    Lat = (Dp @ Vector((1.0, 0.0, 0.0))).normalized()
    d_rest = (Dp @ (rest_world_matrix(arm, f"thigh_{s}").to_3x3() @ Vector((0, 1, 0)))).normalized()
    d_now = bone_dir(arm, f"thigh_{s}")
    a = (d_rest - Lat * d_rest.dot(Lat)).normalized()
    b = (d_now - Lat * d_now.dot(Lat)).normalized()
    ang = math.degrees(math.atan2(a.cross(b).dot(Lat), max(-1.0, min(1.0, a.dot(b)))))
    return -ang       # thigh forward (-Y at rest) = negative rotation about +X -> flexion > 0


def corrective_weights(angle, rest, samples):
    """Piecewise-linear in-between weights for shapes solved at `samples` (ascending, deg):
    angle <= rest -> all 0; between two neighbouring samples the two shapes cross-fade; between
    rest and the first sample the first shape fades in; >= the last sample -> last shape = 1."""
    pts = [float(rest)] + [float(x) for x in samples]
    w = [0.0] * len(samples)
    if angle <= pts[0]:
        return w
    if angle >= pts[-1]:
        w[-1] = 1.0
        return w
    for k in range(1, len(pts)):
        if angle <= pts[k]:
            t = (angle - pts[k - 1]) / (pts[k] - pts[k - 1])
            w[k - 1] = t
            if k >= 2:
                w[k - 2] = 1.0 - t
            return w
    return w


def corrective_name(joint, s, angle):
    return f"CS_{joint}_{int(round(angle)):03d}_{s}"


def joint_angle(arm, joint, s):
    """The driver angle of a corrective joint (deg): elbow = angle(upperarm, lowerarm), knee =
    angle(thigh, calf), hip = hip_flexion_angle."""
    if joint == "elbow":
        return hinge_angle(arm, f"upperarm_{s}", f"lowerarm_{s}")
    if joint == "knee":
        return hinge_angle(arm, f"thigh_{s}", f"calf_{s}")
    if joint == "hip":
        return hip_flexion_angle(arm, s)
    raise ValueError(joint)


def drive_correctives(arm, body, spec=None, sides=("l", "r")):
    """Runtime rule for the corrective shapes (the same rule must run in the engine): for each
    joint in spec ({joint: {"rest": deg, "samples": [deg, ...]}}, stored on the mesh as the
    custom property 'iv_correctives' by the build) and side s, angle = joint_angle(joint, s)
    and the shapes CS_<joint>_<sample>_<s> get corrective_weights(angle, rest, samples).
    Returns {shape: weight, '_<joint>_<s>_angle_deg': angle}."""
    if body.data.shape_keys is None:
        return {}
    spec = spec or json.loads(body.get("iv_correctives", "{}"))
    kb = body.data.shape_keys.key_blocks
    out = {}
    for joint, js in spec.items():
        for s in sides:
            a = joint_angle(arm, joint, s)
            for ang, w in zip(js["samples"], corrective_weights(a, js["rest"], js["samples"])):
                n = corrective_name(joint, s, ang)
                if n in kb:
                    kb[n].value = w
                    out[n] = round(w, 4)
            out[f"_{joint}_{s}_angle_deg"] = round(a, 2)
    bpy.context.view_layer.update()
    return out


def drive_runtime(arm, body, twist=(0.5, 0.5)):
    """Everything the engine must drive per frame: twist bones + corrective shapes."""
    out = {"twist": drive_twist_bones(arm, lower=twist[0], upper=twist[1])}
    out["correctives"] = drive_correctives(arm, body)
    return out


def clear_correctives(body):
    if body.data.shape_keys is not None:
        for k in body.data.shape_keys.key_blocks[1:]:
            k.value = 0.0
        bpy.context.view_layer.update()


def flex_about_axis(arm, bone, axis_rest_world, angle_deg):
    """Rotate `bone` about an axis given in the REST world frame carried by its parent."""
    rotate_bone_rest_axis(arm, bone, axis_rest_world, angle_deg)


def pose_joint_to(arm, joint, s, angle, reset=True):
    """Pose one joint (others at rest) to an anatomical angle, for corrective solving and tests:
    elbow = angle(upperarm, lowerarm), flexed about the rest hinge axis (upperarm x lowerarm, the
    rest pose has 15 deg of flexion); knee = angle(thigh, calf), flexed about rest world +X
    carried by the thigh (foot moves back); hip = hip_flexion_angle, about rest world -X carried
    by the pelvis (knee moves forward).  reset=False poses on top of the current pose (the
    hinge axes are then carried by the parents)."""
    if reset:
        reset_pose(arm)
    if joint == "elbow":
        par, ch = f"upperarm_{s}", f"lowerarm_{s}"
        u0 = rest_world_matrix(arm, par).to_3x3() @ Vector((0, 1, 0))
        f0 = rest_world_matrix(arm, ch).to_3x3() @ Vector((0, 1, 0))
        ax = (pose_delta_rotation(arm, par) @ u0.cross(f0)).normalized()
        for _ in range(4):
            cur = angle_between(bone_dir(arm, par), bone_dir(arm, ch))
            rotate_bone_world(arm, ch, ax, angle - cur)
    elif joint == "knee":
        for _ in range(4):
            cur = angle_between(bone_dir(arm, f"thigh_{s}"), bone_dir(arm, f"calf_{s}"))
            rotate_bone_rest_axis(arm, f"calf_{s}", Vector((1.0, 0.0, 0.0)), angle - cur)
    elif joint == "hip":
        for _ in range(4):
            cur = hip_flexion_angle(arm, s)
            rotate_bone_rest_axis(arm, f"thigh_{s}", Vector((-1.0, 0.0, 0.0)), angle - cur)
    bpy.context.view_layer.update()


def build_correctives(arm, body, spec, sides=("l", "r")):
    """Solve and add the corrective shapes for spec = {joint: {"rest": deg, "samples": [deg..]}}
    (joint in elbow / knee / hip).  Each shape is solved with only that joint posed (others at
    rest), from the current weights.  Stores the spec on the mesh as the custom property
    'iv_correctives'.  Returns a report (achieved angle, moved vertices, max offsets)."""
    names = [b.name for b in arm.data.bones]
    D = read_weights(body, names)
    clear_correctives(body)
    rep = {}
    for joint, js in spec.items():
        for s in sides:
            for ang in js["samples"]:
                pose_joint_to(arm, joint, s, ang)
                achieved = joint_angle(arm, joint, s)
                delta, xl, xd = dqs_offsets(arm, body, D, names)
                n = corrective_name(joint, s, ang)
                reset_pose(arm)
                key, moved = add_offset_shape(body, n, delta)
                rep[n] = {"joint": joint, "side": s, "solved_at_deg": round(achieved, 3),
                          "moved_vertices": moved,
                          "max_rest_offset_m": round(float(np.linalg.norm(delta, axis=1).max()), 5),
                          "max_posed_correction_m": round(float(np.linalg.norm(xd - xl, axis=1).max()), 5)}
    reset_pose(arm)
    body["iv_correctives"] = json.dumps(spec)
    return rep


def corrective_error(arm, body, joint, s, angles, spec=None):
    """How closely the driven shapes reproduce the true DQS pose at test angles: per angle the
    max / mean distance (m) between the driven LBS mesh and Blender's DQS mesh, and the max
    correction that was needed."""
    names = [b.name for b in arm.data.bones]
    D = read_weights(body, names)
    out = {}
    for a in angles:
        clear_correctives(body)
        pose_joint_to(arm, joint, s, a)
        _, xl, xd = dqs_offsets(arm, body, D, names)
        drive_correctives(arm, body, spec, sides=(s,))
        x = mesh_arrays(body, evaluated=True)
        e = np.linalg.norm(x - xd, axis=1)
        need = np.linalg.norm(xd - xl, axis=1)
        m = need > 1e-5
        out[str(a)] = {"max_err_m": round(float(e.max()), 5),
                       "mean_err_m": round(float(e[m].mean()), 6) if m.any() else 0.0,
                       "max_needed_m": round(float(need.max()), 5)}
    clear_correctives(body)
    reset_pose(arm)
    return out


# ---- extended deformation metrics (the R1 reviewer's definitions) -----------------------------

def signed_volume(co, tris):
    return float(np.einsum("ij,ij->i", co[tris[:, 0]], np.cross(co[tris[:, 1]], co[tris[:, 2]])).sum() / 6.0)


def inverted_triangles(arm, co0, co1, tris, tri_dom):
    """Triangles whose posed normal points against the rest normal carried by the rotation of
    the triangle's dominant bone (R1 metric).  Returns (count, {bone: count})."""
    a, b, c = co0[tris[:, 0]], co0[tris[:, 1]], co0[tris[:, 2]]
    N0 = np.cross(b - a, c - a)
    N0 /= np.maximum(np.linalg.norm(N0, axis=1)[:, None], 1e-20)
    a, b, c = co1[tris[:, 0]], co1[tris[:, 1]], co1[tris[:, 2]]
    N1 = np.cross(b - a, c - a)
    N1 /= np.maximum(np.linalg.norm(N1, axis=1)[:, None], 1e-20)
    Dm = {n: np.array(pose_delta_rotation(arm, n)) for n in set(tri_dom.tolist())}
    Nexp = np.stack([Dm[d] @ N0[i] for i, d in enumerate(tri_dom)])
    inv = np.nonzero(np.einsum("ij,ij->i", Nexp, N1) < 0)[0]
    by = {}
    for i in inv:
        by[tri_dom[i]] = by.get(tri_dom[i], 0) + 1
    return int(len(inv)), dict(sorted(by.items()))


def inverted_triangle_indices(arm, co0, co1, tris, tri_dom):
    a, b, c = co0[tris[:, 0]], co0[tris[:, 1]], co0[tris[:, 2]]
    N0 = np.cross(b - a, c - a)
    N0 /= np.maximum(np.linalg.norm(N0, axis=1)[:, None], 1e-20)
    a, b, c = co1[tris[:, 0]], co1[tris[:, 1]], co1[tris[:, 2]]
    N1 = np.cross(b - a, c - a)
    N1 /= np.maximum(np.linalg.norm(N1, axis=1)[:, None], 1e-20)
    Dm = {n: np.array(pose_delta_rotation(arm, n)) for n in set(tri_dom.tolist())}
    Nexp = np.stack([Dm[d] @ N0[i] for i, d in enumerate(tri_dom)])
    return np.nonzero(np.einsum("ij,ij->i", Nexp, N1) < 0)[0], N1


def buried_triangles(bvh, co1, tris, idx, N1, offset=0.0015):
    """How many of the triangles idx lie buried inside the posed body: the point `offset` in
    front of the triangle (along its posed normal) is inside the closed mesh (ray parity).
    Buried faces are hidden in a fold or inside the flesh; the rest can be seen."""
    n = 0
    for i in idx:
        inside, _ = inside_mesh(bvh, co1[tris[i]].mean(0) + N1[i] * offset)
        n += bool(inside)
    return int(n)


def ring_ratio_posed(arm, co0, co1, bone, frac, halfw=0.012, rmax=0.09):
    """Mean radial distance of the vertices in a rest cross-section slab of `bone` at `frac` of
    its length (|axial| < halfw, radius < rmax), measured around the POSED bone axis / rest
    axis (R1 metric).  None if the slab has < 6 vertices."""
    b = arm.data.bones[bone]
    h0 = np.array(arm.matrix_world @ b.head_local)
    t0 = np.array(arm.matrix_world @ b.tail_local)
    ax0 = (t0 - h0) / np.linalg.norm(t0 - h0)
    p0 = h0 + frac * (t0 - h0)
    sax = (co0 - p0) @ ax0
    rad0 = co0 - p0 - np.outer(sax, ax0)
    near = (np.abs(sax) < halfw) & (np.linalg.norm(rad0, axis=1) < rmax)
    if near.sum() < 6:
        return None
    h1 = np.array(bone_world(arm, bone, "head"))
    t1 = np.array(bone_world(arm, bone, "tail"))
    ax1 = (t1 - h1) / np.linalg.norm(t1 - h1)
    p1 = h1 + frac * (t1 - h1)
    s1 = (co1[near] - p1) @ ax1
    rad1 = co1[near] - p1 - np.outer(s1, ax1)
    return float(np.linalg.norm(rad1, axis=1).mean() / np.linalg.norm(rad0[near], axis=1).mean())


# =============================================================================
# 10. Hand anatomy pass (hands task): one flexion axis per finger, anatomical joint angles,
#     contact / penetration metrics
# =============================================================================
#
# Why: (a) curling a finger bone by bone about slightly different local X axes (MPFB rolls,
# up to ~3 deg apart after the R1 re-seat) makes the finger drift sideways and twist; every
# finger chain (and the thumb MCP + IP) now shares ONE flexion axis.  (b) The hm08 hand is
# modelled relaxed (MCP ~11-14 deg, PIP ~8-14 deg flexed), so a curl added on top of the rest
# pose over-flexes: "90/100/70" on top of the rest pose is really ~104/110/73 deg and drives
# the fingertips ~15 mm into the palm.  Poses are therefore specified in ANATOMICAL angles
# (0 = finger straight: proximal phalanx in the palm plane, middle / distal phalanx in line
# with their parent) and converted with the measured rest angles.

HAND_CHAINS = {f: (f"{f}_01", f"{f}_02", f"{f}_03") for f in FINGERS4}
HAND_CHAINS["thumb"] = ("thumb_02", "thumb_03")         # MCP + IP hinge; CMC (thumb_01) keeps its roll


def unify_chain_axes(bones, sides=("l", "r")):
    """Give every bone of a finger chain the same local X (flexion axis): the normalised mean of
    the chain's current X axes.  The distal joints and the tip marker are first moved onto the
    plane through the chain's first joint with that normal (sub-millimetre shifts), so the chain
    is planar and X is exactly shared (curling about X cannot twist or drift sideways).  A
    parent's tail follows its child's head (same point).  Returns a report."""
    rep = {}
    for s in sides:
        for f, chain in HAND_CHAINS.items():
            names = [f"{c}_{s}" for c in chain]
            X = [bone_frame(bones[n]["head"], bones[n]["tail"], bones[n]["roll"])[:, 0] for n in names]
            spread0 = max(math.degrees(math.acos(max(-1.0, min(1.0, float(a @ b))))) for a in X for b in X)
            xm = np.mean(X, axis=0)
            xm /= np.linalg.norm(xm)
            # make the chain planar: move the distal joints (and the tip marker) onto the plane
            # through the first joint with normal xm (sub-millimetre shifts), so one X fits all
            h0 = np.asarray(bones[names[0]]["head"], float)
            moved = 0.0
            for i, n in enumerate(names):
                b = bones[n]
                for key in (("head",) if i else ()) + ("tail",):
                    q = np.asarray(b[key], float)
                    dq = xm * ((q - h0) @ xm)
                    b[key] = q - dq
                    moved = max(moved, float(np.linalg.norm(dq)))
            for n in names:
                b = bones[n]
                b["roll"] = roll_keeping_x(b["head"], b["tail"], xm)
            X2 = [bone_frame(bones[n]["head"], bones[n]["tail"], bones[n]["roll"])[:, 0] for n in names]
            spread1 = max(math.degrees(math.acos(max(-1.0, min(1.0, float(a @ b))))) for a in X2 for b in X2)
            ys = [np.asarray(bones[n]["tail"], float) - np.asarray(bones[n]["head"], float) for n in names]
            offplane = max(abs(math.degrees(math.asin(max(-1.0, min(1.0, float(y @ xm) / np.linalg.norm(y)))))) for y in ys)
            rep[f"{f}_{s}"] = {"x_spread_before_deg": round(spread0, 3), "x_spread_after_deg": round(spread1, 4),
                               "max_bone_tilt_from_flexion_plane_deg": round(offplane, 3),
                               "planarise_max_joint_shift_mm": round(moved * 1000, 3)}
    return rep


def _ang_about(a, b, ax):
    a = a - ax * a.dot(ax)
    b = b - ax * b.dot(ax)
    return math.degrees(math.atan2(a.cross(b).dot(ax), a.dot(b)))


def hand_rest_angles(arm, s):
    """Anatomical flexion (deg) of the REST pose, per bone: finger _01 = angle of the proximal
    phalanx out of the palm plane (hand_frame_rest), about the bone's own X (flexion > 0);
    _02 / _03 and thumb_02 / thumb_03 = angle to the parent bone about the bone's X."""
    w, d, r, p = hand_frame_rest(arm, s)
    B = arm.data.bones
    M = lambda n: (arm.matrix_world @ B[n].matrix_local).to_3x3()       # noqa: E731
    out = {}
    for f in FINGERS4:
        y1 = M(f"{f}_01_{s}").col[1]
        x = M(f"{f}_01_{s}").col[0]
        out[f"{f}_01_{s}"] = round(_ang_about(y1 - p * y1.dot(p), y1, x), 3)
        for i in (2, 3):
            out[f"{f}_0{i}_{s}"] = round(_ang_about(M(f"{f}_0{i - 1}_{s}").col[1], M(f"{f}_0{i}_{s}").col[1],
                                                    M(f"{f}_0{i}_{s}").col[0]), 3)
    for i in (2, 3):
        out[f"thumb_0{i}_{s}"] = round(_ang_about(M(f"thumb_0{i - 1}_{s}").col[1], M(f"thumb_0{i}_{s}").col[1],
                                                  M(f"thumb_0{i}_{s}").col[0]), 3)
    return out


def hand_pose_quats(pose, s, rest):
    """Local rotations (Quaternion per bone) for an anatomical hand pose.
    pose = {"index": {"mcp", "pip", "dip", "abd"}, ... (middle, ring, pinky),
            "thumb": {"cmc_flex", "cmc_abd", "cmc_rot", "mcp", "ip"}}  (deg; missing keys = rest)
      mcp / pip / dip / thumb mcp / ip : anatomical flexion (0 = straight, + = flexion)
      abd      : MCP abduction relative to rest, + = towards the thumb (radial), both hands
      cmc_flex : thumb_01 about its X relative to rest, + = across the palm (flexion / adduction)
      cmc_abd  : thumb_01 about its Z relative to rest, + = out in front of the palm (palmar abduction)
      cmc_rot  : thumb_01 about its own long axis relative to rest, + = pronation (pad turns towards the fingers)
    Finger _01: q = Rz(abd) Rx(mcp - rest); thumb_01: q = Rx(cmc_flex) Rz(cmc_abd) Ry(cmc_rot)."""
    zs = 1.0 if s == "l" else -1.0
    rad = math.radians
    q = {}
    for f in FINGERS4:
        fp = pose.get(f)
        if fp is None:
            continue
        n1, n2, n3 = (f"{f}_0{i}_{s}" for i in (1, 2, 3))
        q1 = Quaternion((0, 0, 1), rad(fp.get("abd", 0.0) * zs))
        if "mcp" in fp:
            q1 = q1 @ Quaternion((1, 0, 0), rad(fp["mcp"] - rest[n1]))
        q[n1] = q1
        if "pip" in fp:
            q[n2] = Quaternion((1, 0, 0), rad(fp["pip"] - rest[n2]))
        if "dip" in fp:
            q[n3] = Quaternion((1, 0, 0), rad(fp["dip"] - rest[n3]))
    tp = pose.get("thumb")
    if tp is not None:
        q[f"thumb_01_{s}"] = (Quaternion((1, 0, 0), rad(tp.get("cmc_flex", 0.0)))
                              @ Quaternion((0, 0, 1), rad(tp.get("cmc_abd", 0.0) * zs))
                              @ Quaternion((0, 1, 0), rad(tp.get("cmc_rot", 0.0) * zs)))
        if "mcp" in tp:
            q[f"thumb_02_{s}"] = Quaternion((1, 0, 0), rad(tp["mcp"] - rest[f"thumb_02_{s}"]))
        if "ip" in tp:
            q[f"thumb_03_{s}"] = Quaternion((1, 0, 0), rad(tp["ip"] - rest[f"thumb_03_{s}"]))
    return q


def pose_hand_anat(arm, s, pose, rest=None):
    """Set (not compose) the finger / thumb bones of hand s to an anatomical pose (see
    hand_pose_quats).  rest: hand_rest_angles(arm, s) (computed when None)."""
    rest = rest or hand_rest_angles(arm, s)
    for n, q in hand_pose_quats(pose, s, rest).items():
        pb = arm.pose.bones[n]
        pb.rotation_mode = 'QUATERNION'
        pb.rotation_quaternion = q
    bpy.context.view_layer.update()


def measured_hand_angles(arm, s, rest=None):
    """Read back the anatomical angles of the current pose (inverse of pose_hand_anat, for the
    validation JSON): flexion = rotation about local X (+ rest), abduction = about local Z."""
    rest = rest or hand_rest_angles(arm, s)
    zs = 1.0 if s == "l" else -1.0
    out = {}
    for f in FINGERS4 + ("thumb",):
        e = {}
        for i, key in ((1, "mcp"), (2, "pip"), (3, "dip")):
            n = f"{f}_0{i}_{s}"
            q = arm.pose.bones[n].rotation_quaternion
            if f == "thumb":
                if i == 1:
                    eu = q.to_matrix().to_euler('YZX')       # R = Rx Rz Ry
                    e.update(cmc_flex=round(math.degrees(eu.x), 3), cmc_abd=round(math.degrees(eu.z) * zs, 3),
                             cmc_rot=round(math.degrees(eu.y) * zs, 3))
                else:
                    e["mcp" if i == 2 else "ip"] = round(math.degrees(twist_angle(q, 0)) + rest[n], 3)
                continue
            if i == 1:
                eu = q.to_matrix().to_euler('XZY')           # R = Rz Rx
                e["mcp"] = round(math.degrees(eu.x) + rest[n], 3)
                e["abd"] = round(math.degrees(eu.z) * zs, 3)
            else:
                e[key] = round(math.degrees(twist_angle(q, 0)) + rest[n], 3)
        out[f] = e
    return out


def _vertex_normals(co, tris):
    n = np.zeros_like(co)
    a, b, c = co[tris[:, 0]], co[tris[:, 1]], co[tris[:, 2]]
    fn = np.cross(b - a, c - a)
    for k in range(3):
        np.add.at(n, tris[:, k], fn)
    return n / np.maximum(np.linalg.norm(n, axis=1)[:, None], 1e-12)


def region_of(bone):
    """Hand region of a bone name: 'thumb', 'index', ..., 'hand', or None."""
    f = bone.split("_")[0]
    return f if f in FINGERS + ("hand",) else None


def hand_contact_metrics(co, co_rest, tris, dom, s, fold_rest_dist=0.012, search=0.025, eps=0.0003,
                         per_vertex=None):
    """Penetration metrics of a posed hand (arrays only; no bpy state).
    A hand vertex is BURIED when the point eps in front of it (along its posed normal) lies inside
    the closed posed body (ray-parity vote).  For a buried vertex v the posed faces within
    `search` are collected and every face that lay within `fold_rest_dist` of v in the REST mesh
    (v's own neighbourhood, including the far side of its own joint crease) is ignored:
      * no face left -> v is inside a skin FOLD at a crease (hidden, like real skin): 'folds';
      * else PENETRATION into the region B of the nearest remaining face, depth = its distance.
    Reported per pair "A[_seg]->B" (A, B in thumb, index, middle, ring, pinky, hand, arm):
    count and max / 95th percentile depth in mm."""
    from mathutils.bvhtree import BVHTree
    names_dom = np.asarray(dom)
    reg = np.array([(region_of(b) or "arm") if b.endswith(f"_{s}") else "body" for b in names_dom], dtype=object)
    treg = reg[tris[:, 0]]
    bvh = BVHTree.FromPolygons([tuple(map(float, x)) for x in co], [tuple(map(int, t)) for t in tris], all_triangles=True)
    nrm = _vertex_normals(co, tris)
    regions = FINGERS + ("hand",)
    hv = np.nonzero(np.isin(reg, regions))[0]
    pairs, folds = {}, []
    buried_n = 0
    for v in hv:
        pv = Vector(tuple(map(float, co[v])))
        ins, _ = inside_mesh(bvh, pv + Vector(tuple(map(float, nrm[v]))) * eps)
        if not ins:
            continue
        buried_n += 1
        best = None
        for loc, fn, fi, dist in bvh.find_nearest_range(pv, search):
            if fi is None:
                continue
            if float(np.min(np.linalg.norm(co_rest[tris[fi]] - co_rest[v], axis=1))) < fold_rest_dist:
                continue
            if best is None or dist < best[0]:
                best = (dist, fi)
        if best is None:
            folds.append(int(v))
            continue
        A = reg[v]
        seg = names_dom[v].split("_")[1] if A in FINGERS else ""
        key = f"{A}{'_' + seg if seg else ''}->{treg[best[1]]}"
        pairs.setdefault(key, []).append(best[0])
        if per_vertex is not None:
            per_vertex[int(v)] = (key, best[0])
    pen = {k: {"n": len(v), "max_mm": round(max(v) * 1000, 2),
               "p95_mm": round(float(np.percentile(v, 95)) * 1000, 2)} for k, v in sorted(pairs.items())}
    return dict({"buried_vertices": int(buried_n), "fold_vertices": len(folds)},
                **contact_categories(pen), penetration=pen)


def contact_category(a, b):
    """Category of a hand penetration pair key 'A[_seg]' -> 'B' (see hand_contact_metrics):
      crease        : a finger into itself (palmar skin folding over a flexed PIP / DIP), the
                      proximal segment into the palm or the palm into a finger (MCP crease) --
                      skin folds / compression inside a joint crease, hidden
      tip_palm      : a finger's middle or distal segment into the palm / hand
      finger_finger : side contact between two different fingers (index..pinky)
      thumb         : the thumb into a finger / the palm, or a finger into the thumb
      other         : into the forearm / body"""
    fa = a.split("_")[0]
    if fa == "thumb" or b == "thumb":
        return "thumb" if not (fa == "thumb" and b == "hand" and a.endswith("01")) else "crease"
    if b in ("arm", "body"):
        return "other"
    if fa == b or (fa == "hand" and b in FINGERS4) or (fa in FINGERS4 and b == "hand" and a.endswith("01")):
        return "crease"
    if fa in FINGERS4 and b == "hand":
        return "tip_palm"
    if fa in FINGERS4 and b in FINGERS4:
        return "finger_finger"
    return "other"


def contact_categories(pen):
    out = {}
    for c in ("tip_palm", "finger_finger", "thumb", "crease", "other"):
        vals = [v["max_mm"] for k, v in pen.items() if contact_category(*k.split("->")) == c]
        out[f"{c}_max_mm"] = max(vals) if vals else 0.0
    return out


def verts_beyond_dorsal(co, co_rest, tris, dom, s, arm):
    """Finger vertices (index..pinky _02/_03) beyond the REST dorsal hand surface along -palm
    normal (fingertips through the back of the hand).  Returns (count, max m)."""
    from mathutils.bvhtree import BVHTree
    w, d, r, p = hand_frame_rest(arm, s)
    pn = np.array(p)
    a, b, c = co_rest[tris[:, 0]], co_rest[tris[:, 1]], co_rest[tris[:, 2]]
    N0 = np.cross(b - a, c - a)
    N0 /= np.maximum(np.linalg.norm(N0, axis=1)[:, None], 1e-20)
    tdom = np.asarray(dom)[tris[:, 0]]
    dors = np.nonzero((tdom == f"hand_{s}") & (N0 @ -pn > 0.5))[0]
    br = BVHTree.FromPolygons([tuple(map(float, x)) for x in co_rest], [tuple(map(int, t)) for t in tris[dors]], all_triangles=True)
    fing = np.nonzero(np.isin(np.asarray(dom), [f"{f}_0{k}_{s}" for f in FINGERS4 for k in (2, 3)]))[0]
    n, mx = 0, 0.0
    for v in fing:
        q = Vector(tuple(map(float, co[v])))
        hit = br.ray_cast(q + p * 0.05, -p)
        if hit[0] is not None:
            dist = (q - hit[0]).dot(-p)
            if dist > 0:
                n += 1
                mx = max(mx, dist)
    return int(n), float(mx)


if __name__ == "__main__":
    if "--job" in sys.argv:
        _job_main(sys.argv[sys.argv.index("--job") + 1])
