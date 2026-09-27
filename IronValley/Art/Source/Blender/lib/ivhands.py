"""
ivhands -- Iron Valley HANDS helpers: tactical glove shell, texel-space glove textures, numpy
skinning of the hand, contact / gap metrics against weapons, grasp fitting (bpy 4.5 LTS,
headless, deterministic).

Used by Art/Source/Blender/characters/hands_gloves.py.  Builds on ivchar (rig, anatomical hand
poses, hand contact metrics) and ivlib (render / export).  Nothing here edits ivlib / ivchar /
ivoptics.

Sections
--------
  1. Glove geometry: hand + wrist region of SK_Human_Base -> (local pre-refine over the
     knuckles) -> Catmull-Clark -> shell at a controlled offset from the ORIGINAL skin plus
     construction reliefs (knuckle guard, finger PIP pads, palm / thumb-saddle patches,
     fingertip caps, cuff, wrist strap) -> rolled hem at the cuff opening -> mirrored right glove
  2. Glove zone fields (per rest vertex): palmar / dorsal field, cap, patch, guard, cuff, strap,
     signed seam distances and seam tangents (for stitching)
  3. Texel-space texture synthesis (numpy): UV raster with barycentrics, attribute
     interpolation, material zones -> BaseColor / roughness / metallic / height -> tangent-space
     normal (OpenGL) + DirectX copy, ORM (AO from a Cycles AO bake x seam cavity)
  4. Numpy skinning of hand meshes (FK from local quaternions; <= 4 influences)
  5. Contact metrics: gap / penetration of a skinned hand against static meshes (BVH)
  6. Grasp fitting: close a finger joint by joint to contact; place the palm on a surface

Conventions: metres, Z up.  Character faces -Y, left side +X.  Weapon: muzzle +X, top +Z,
right side -Y (see Docs/ARCHITECTURE.md).
"""

import math
import os

import bpy
import bmesh
import numpy as np
from mathutils import Vector, Matrix, Quaternion
from mathutils.bvhtree import BVHTree

import ivchar as C

IVHANDS_VERSION = "1.0.0"

FINGERS4 = C.FINGERS4
FINGERS = C.FINGERS



class _Res:
    def __init__(self, x, fun, nfev=0):
        self.x, self.fun, self.nfev = np.asarray(x, float), float(fun), nfev


def powell_min(cost, x0, bounds, options):
    """scipy Powell with bounds, guarded: scipy's bounded Powell can return a point WORSE than x0
    on these non-smooth contact costs (seen: 0.52 -> 6.67), so the start is kept when it is
    better, and one restart from the best point is made."""
    from scipy.optimize import minimize
    x0 = np.clip(np.asarray(x0, float), [b[0] for b in bounds], [b[1] for b in bounds])
    best = _Res(x0, cost(x0))
    for _ in range(2):
        res = minimize(cost, best.x, method="Powell", bounds=bounds, options=options)
        if res.fun < best.fun - 1e-12:
            best = _Res(res.x, res.fun, res.nfev)
        else:
            break
    return best

def log(*a):
    print("[ivhands]", *a, flush=True)


def bvh_arrays(co, tris):
    return BVHTree.FromPolygons([tuple(map(float, x)) for x in co], [tuple(map(int, t)) for t in tris],
                                all_triangles=True)


def mesh_tris(me):
    me.calc_loop_triangles()
    t = np.empty(len(me.loop_triangles) * 3, np.int64)
    me.loop_triangles.foreach_get("vertices", t)
    return t.reshape(-1, 3)


def mesh_co(me):
    co = np.empty(len(me.vertices) * 3)
    me.vertices.foreach_get("co", co)
    return co.reshape(-1, 3)


def vertex_normals(co, tris):
    return C._vertex_normals(co, tris)


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def neighbours_from_tris(tris, n):
    nb = [set() for _ in range(n)]
    for a, b, c in tris:
        nb[a].update((b, c)); nb[b].update((a, c)); nb[c].update((a, b))
    return [np.array(sorted(x), np.int64) for x in nb]


def laplacian_smooth_field(f, nbrs, iters=3, alpha=0.5, mask=None):
    f = np.array(f, float, copy=True)
    for _ in range(iters):
        g = np.array([f[nb].mean(0) if len(nb) else f[i] for i, nb in enumerate(nbrs)])
        new = (1 - alpha) * f + alpha * g
        if mask is not None:
            new[~mask] = f[~mask]
        f = new
    return f


def vertex_gradient(f, co, tris):
    """Per-vertex surface gradient (N,3) of a scalar vertex field (area-weighted face gradients)."""
    a, b, c = co[tris[:, 0]], co[tris[:, 1]], co[tris[:, 2]]
    n = np.cross(b - a, c - a)
    A2 = np.linalg.norm(n, axis=1)
    nn = n / np.maximum(A2[:, None], 1e-20)
    fa, fb, fc = f[tris[:, 0]], f[tris[:, 1]], f[tris[:, 2]]
    g = (np.cross(nn, c - b) * fa[:, None] + np.cross(nn, a - c) * fb[:, None]
         + np.cross(nn, b - a) * fc[:, None]) / np.maximum(A2[:, None], 1e-20)
    out = np.zeros_like(co)
    w = np.zeros(len(co))
    for k in range(3):
        np.add.at(out, tris[:, k], g * A2[:, None])
        np.add.at(w, tris[:, k], A2)
    return out / np.maximum(w[:, None], 1e-20)


# =============================================================================
# 1. Glove geometry
# =============================================================================

GLOVE_BONES = lambda s: ([f"hand_{s}"] + [f"{f}_{i:02d}_{s}" for f in FINGERS for i in (1, 2, 3)])  # noqa: E731


def hand_frame(arm, s):
    """REST hand frame as numpy: wrist joint w, d (wrist -> middle MCP), r (radial), p (palm
    normal, out of the palm)."""
    w, d, r, p = C.hand_frame_rest(arm, s)
    return np.array(w), np.array(d), np.array(r), np.array(p)


def forearm_axis(arm, s):
    """(wrist joint, unit forearm axis elbow -> wrist) in the rest pose."""
    b = arm.data.bones[f"lowerarm_{s}"]
    h, t = np.array(arm.matrix_world @ b.head_local), np.array(arm.matrix_world @ b.tail_local)
    return t, (t - h) / np.linalg.norm(t - h)


def glove_region(arm, body, s, cuff_len):
    """Faces of the body that the glove covers: every face whose vertices are all dominated by the
    hand / finger bones of side s, or by the forearm bones with the face centre no further than
    `cuff_len` proximal of the wrist joint (measured along the forearm axis).
    Returns (vertex indices, faces reindexed, dense weights of those vertices, bone names)."""
    names = [b.name for b in arm.data.bones]
    D = C.read_weights(body, names)
    dom = np.array(names)[D.argmax(1)]
    co = C.mesh_arrays(body)
    wj, ax = forearm_axis(arm, s)
    u = (co - wj) @ ax
    handish = np.isin(dom, GLOVE_BONES(s))
    armish = np.isin(dom, [f"lowerarm_{s}", f"lowerarm_twist_01_{s}"])
    keepf = []
    for poly in body.data.polygons:
        vs = list(poly.vertices)
        if all(handish[v] or armish[v] for v in vs) and u[vs].mean() > -cuff_len:
            keepf.append(vs)
    vids = np.array(sorted({v for f in keepf for v in f}), np.int64)
    remap = -np.ones(len(co), np.int64)
    remap[vids] = np.arange(len(vids))
    faces = [[int(remap[v]) for v in f] for f in keepf]
    return vids, faces, D[vids], names


def object_from_region(name, co, faces, W, names, col, min_w=1e-5):
    ob = C.mesh_from_arrays(name, co, faces, col=col)
    used = np.nonzero(W.max(0) > min_w)[0]
    for j in used:
        vg = ob.vertex_groups.new(name=names[j])
        nz = np.nonzero(W[:, j] > min_w)[0]
        for v in nz:
            vg.add([int(v)], float(W[v, j]), 'REPLACE')
    return ob


def refine_faces(ob, face_mask, smooth=1.0):
    """One linear+smoothed subdivision (bmesh subdivide_edges, cuts=1, grid fill) of the faces in
    face_mask (bool per polygon).  Vertex groups are interpolated."""
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bm.faces.ensure_lookup_table()
    edges = set()
    for i, f in enumerate(bm.faces):
        if face_mask[i]:
            edges.update(f.edges)
    bmesh.ops.subdivide_edges(bm, edges=list(edges), cuts=1, use_grid_fill=True, smooth=smooth,
                              quad_corner_type='INNER_VERT')
    bm.to_mesh(ob.data)
    bm.free()
    ob.data.update()


def apply_subsurf(ob, levels=1):
    m = ob.modifiers.new("IV_Subsurf", 'SUBSURF')
    m.levels = levels
    m.render_levels = levels
    m.quality = 3
    m.use_limit_surface = True
    m.boundary_smooth = 'PRESERVE_CORNERS'
    m.uv_smooth = 'NONE'
    bpy.context.view_layer.objects.active = ob
    for o in bpy.context.selected_objects:
        o.select_set(False)
    ob.select_set(True)
    bpy.ops.object.modifier_apply(modifier=m.name)


def read_groups(ob, names):
    """Dense (V, len(names)) weights of an object's vertex groups (missing = 0)."""
    n = len(ob.data.vertices)
    W = np.zeros((n, len(names)))
    gi = {g.index: g.name for g in ob.vertex_groups}
    col = {nm: j for j, nm in enumerate(names)}
    for v in ob.data.vertices:
        for g in v.groups:
            nm = gi.get(g.group)
            if nm in col:
                W[v.index, col[nm]] = g.weight
    return W


def write_groups(ob, W, names, min_w=1e-6):
    for vg in list(ob.vertex_groups):
        ob.vertex_groups.remove(vg)
    for j, nm in enumerate(names):
        nz = np.nonzero(W[:, j] > min_w)[0]
        if not len(nz):
            continue
        vg = ob.vertex_groups.new(name=nm)
        for v in nz:
            vg.add([int(v)], float(W[v, j]), 'REPLACE')


def limit_weights(W, k=4):
    W = np.array(W, float, copy=True)
    if W.shape[1] > k:
        idx = np.argsort(-W, axis=1)[:, k:]
        np.put_along_axis(W, idx, 0.0, axis=1)
    return W / np.maximum(W.sum(1, keepdims=True), 1e-12)


def boundary_loop(me):
    """Ordered vertex indices of the (single longest) boundary loop of a mesh."""
    from collections import defaultdict
    ec = defaultdict(int)
    for p in me.polygons:
        vs = list(p.vertices)
        for i in range(len(vs)):
            e = tuple(sorted((vs[i], vs[(i + 1) % len(vs)])))
            ec[e] += 1
    be = [e for e, c in ec.items() if c == 1]
    adj = defaultdict(list)
    for a, b in be:
        adj[a].append(b); adj[b].append(a)
    loops, seen = [], set()
    for start in adj:
        if start in seen:
            continue
        loop, prev, cur = [start], None, start
        seen.add(start)
        while True:
            nx = [x for x in adj[cur] if x != prev]
            if not nx or nx[0] == start:
                break
            prev, cur = cur, nx[0]
            if cur in seen:
                break
            loop.append(cur); seen.add(cur)
        loops.append(loop)
    return max(loops, key=len)


def add_hem(ob, inward=0.0022, depth=0.009, arm_axis=None, centre=None):
    """Rolled hem at the cuff opening: the boundary ring is extruded towards the arm axis by
    `inward` (the edge thickness) and then `depth` back inside the glove (distally), so the
    opening shows a thick edge and an inner lining instead of a zero-thickness rim.  New
    vertices copy the weights of their boundary vertex.  Returns the new vertex indices."""
    me = ob.data
    loop = boundary_loop(me)
    co = mesh_co(me)
    ax = np.asarray(arm_axis, float)
    cen = np.asarray(centre, float)
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.verts.ensure_lookup_table()
    dl = bm.verts.layers.deform.verify()
    ring1, ring2 = [], []
    outer = [bm.verts[vi] for vi in loop]
    for vi, v in zip(loop, outer):
        p = co[vi]
        rel = p - cen
        radial = rel - ax * (rel @ ax)
        radial /= max(np.linalg.norm(radial), 1e-9)
        p1 = p - radial * inward
        p2 = p1 + ax * depth
        for pp, ring in ((p1, ring1), (p2, ring2)):
            nv = bm.verts.new(tuple(map(float, pp)))
            nv[dl].clear()
            for k, w in v[dl].items():
                nv[dl][k] = w
            ring.append(nv)
    bm.verts.ensure_lookup_table()
    n = len(loop)
    # orientation: the glove face at the boundary decides the winding of the hem strip
    newf = []
    for i in range(n):
        j = (i + 1) % n
        newf.append(bm.faces.new((outer[i], outer[j], ring1[j], ring1[i])))
        newf.append(bm.faces.new((ring1[i], ring1[j], ring2[j], ring2[i])))
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    for f in newf:
        f.smooth = True
    bm.to_mesh(me)
    bm.free()
    me.update()
    return list(range(len(co), len(co) + 2 * n))


def mirror_object(src, name, col):
    """Mirror a mesh object across X = 0 (flip winding), renaming _l <-> _r vertex groups."""
    me = src.data.copy()
    me.name = name
    ob = bpy.data.objects.new(name, me)
    col.objects.link(ob)
    co = mesh_co(me)
    co[:, 0] *= -1
    me.vertices.foreach_set("co", co.ravel())
    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.reverse_faces(bm, faces=list(bm.faces), flip_multires=False)
    bm.to_mesh(me)
    bm.free()
    # vertex-group names live on the mesh (copied with it): rename them in place
    for vg in list(ob.vertex_groups):
        vg.name = "__m__" + C.mirror_bone_name(vg.name)
    for vg in list(ob.vertex_groups):
        vg.name = vg.name[5:]
    me.update()
    return ob


# =============================================================================
# 2. Glove zone fields (per REST vertex of the glove shell)
# =============================================================================
#
# Every field is a smooth vertex scalar; the texture synthesis interpolates them per texel, so
# zone borders (= seams) are smooth iso-lines, independent of the mesh edges.  Signed distance
# families (metres, negative / positive side documented per family) drive seams and stitching.

GLOVE_DESIGN = dict(
    cuff_len=0.080,          # glove reaches 8 cm proximal of the wrist joint (along the forearm axis)
    cuff_seam_u=0.010,       # cuff / glove-body seam 1 cm distal of the wrist joint
    strap_u=-0.031, strap_w=0.026, strap_end_deg=-58.0, strap_overlap_deg=62.0,
    tab_len=0.016, tab_half_w=0.0085,
    t_fabric=0.0010, t_leather=0.00125, t_cuff=0.0013,
    h_cap=0.00035, h_patch=0.00055, h_strap=0.0016, h_strap_top=0.0012, h_tab=0.0010,
    h_plate=0.0014, h_pad=0.0030, h_pip=0.0019,
    leather_z=0.12,          # palmar field iso-value of the leather / stretch-fabric seam
    cap_len=0.012, cap_len_thumb=0.014, cap_palm_extra=0.005,
    saddle_r=0.021, heel_c=(0.040, -0.026), heel_r=(0.026, 0.016),
    pad_back=0.0035, pad_half_d=0.0095, pad_groove=0.0012, plate_margin=0.0025,
    pip_back=0.0055, pip_half_len=0.0080, pip_half_w=0.0056,
)


def bone_rest_frames(arm):
    out = {}
    for b in arm.data.bones:
        M = arm.matrix_world @ b.matrix_local
        R = np.array(M.to_3x3().normalized())
        out[b.name] = dict(H=np.array(M.translation), X=R[:, 0], Y=R[:, 1], Z=R[:, 2], L=b.length)
    return out


def _rrect_sdf(a, b, ca, cb, ha, hb, r):
    """Rounded-rectangle signed distance in 2D (a, b) (negative inside)."""
    qa = np.abs(a - ca) - (ha - r)
    qb = np.abs(b - cb) - (hb - r)
    out = np.sqrt(np.maximum(qa, 0) ** 2 + np.maximum(qb, 0) ** 2) + np.minimum(np.maximum(qa, qb), 0)
    return out - r


def glove_fields(co, nrm, W, names, arm, s, design=None):
    """Zone fields of a LEFT/RIGHT glove shell in the rest pose (co / nrm: skin-level surface
    positions and normals of the shell; W: dense weights over `names`).  Returns a dict of
    per-vertex arrays (metres for distances) and the geometric relief height `h_geo`."""
    P = dict(GLOVE_DESIGN, **(design or {}))
    F = bone_rest_frames(arm)
    w, d, r, p = hand_frame(arm, s)
    wj, ax = forearm_axis(arm, s)
    col = {n: j for j, n in enumerate(names)}
    V = len(co)
    # ---- palmar field: weight-blended palmar axis (finger / thumb bones: local +Z = flexion side)
    zp = np.zeros(V)
    for n, j in col.items():
        if not n.endswith(f"_{s}"):
            continue
        axis = F[n]["Z"] if n.split("_")[0] in FINGERS else p
        zp += W[:, j] * (nrm @ axis)
    fr = {"z_palm": zp}
    rel = co - w
    a_, b_ = rel @ d, rel @ r
    fr["hand_a"], fr["hand_b"] = a_, b_
    u = (co - wj) @ ax
    fr["u_arm"] = u
    # ---- fingertip caps: signed distance along the distal bone (+ = inside the cap)
    cap = np.full(V, -0.05)
    for f in FINGERS:
        fw = sum(W[:, col[f"{f}_{i:02d}_{s}"]] for i in (1, 2, 3) if f"{f}_{i:02d}_{s}" in col)
        b3 = F[f"{f}_03_{s}"]
        sv = (co - b3["H"]) @ b3["Y"]
        L = P["cap_len_thumb"] if f == "thumb" else P["cap_len"]
        val = sv - (b3["L"] - L - P["cap_palm_extra"] * np.clip(zp, 0, 1))
        m = fw > 0.5
        cap[m] = val[m]
    fr["cap"] = cap
    # ---- palm patches: thumb saddle (3D disc around the thumb-index web) + hypothenar heel pad
    web = 0.5 * (F[f"thumb_02_{s}"]["H"] + F[f"index_01_{s}"]["H"])
    web = web + d * 0.002 + p * 0.004            # centred slightly to the palm side of the web
    sad = np.linalg.norm(co - web, axis=1) - P["saddle_r"]
    hc, hr = P["heel_c"], P["heel_r"]
    heel = np.sqrt(((a_ - hc[0]) / hr[0]) ** 2 + ((b_ - hc[1]) / hr[1]) ** 2) - 1.0
    heel = heel * min(hr) + np.clip(0.3 - zp, 0, None) * 0.03          # palmar side only
    fr["patch"] = np.minimum(sad, heel)
    # ---- knuckle guard: segmented pads over the MCP heads on a common plate (dorsal only)
    mcp = {f: F[f"{f}_01_{s}"]["H"] - w for f in FINGERS4}
    ab = {f: (mcp[f] @ d, mcp[f] @ r) for f in FINGERS4}
    order = list(FINGERS4)
    pads = []
    for k, f in enumerate(order):
        nb = [ab[order[j]][1] for j in (k - 1, k + 1) if 0 <= j < len(order)]
        sp = min(abs(ab[f][1] - x) for x in nb)
        hb = 0.5 * sp - P["pad_groove"]
        pads.append(_rrect_sdf(a_, b_, ab[f][0] - P["pad_back"], ab[f][1], P["pad_half_d"], hb, 0.0035))
    pad = np.min(pads, axis=0)
    plate = np.min([x - P["plate_margin"] for x in pads], axis=0)
    dors = smoothstep(-0.30, -0.50, zp)          # 1 on the back of the hand
    far = 0.02
    pad = np.where(dors > 0.5, pad, far)
    plate = np.where(dors > 0.5, plate, far)
    # ---- PIP pads (dorsal proximal phalanx near the PIP) and a thumb IP pad
    pips = []
    for f in FINGERS4 + ("thumb",):
        bn = f"{f}_01_{s}" if f != "thumb" else f"thumb_02_{s}"
        b1 = F[bn]
        sv = (co - b1["H"]) @ b1["Y"]
        xv = (co - b1["H"]) @ b1["X"]
        fw = sum(W[:, col[f"{f}_{i:02d}_{s}"]] for i in (1, 2, 3) if f"{f}_{i:02d}_{s}" in col)
        e = _rrect_sdf(sv, xv, b1["L"] - P["pip_back"], 0.0, P["pip_half_len"], P["pip_half_w"], 0.0035)
        e = np.where((fw > 0.5) & (zp < -0.35), e, far)
        pips.append(e)
    pip = np.min(pips, axis=0)
    fr["guard_pad"], fr["guard_plate"], fr["pip_pad"] = pad, plate, pip
    fr["guard"] = np.minimum(plate, pip)
    # ---- cuff and strap (cylindrical coordinates about the forearm axis)
    fr["cuff"] = u - P["cuff_seam_u"]                       # < 0 = cuff
    radial = (co - wj) - np.outer(u, ax)
    e1 = -p - ax * (-p @ ax); e1 /= np.linalg.norm(e1)       # dorsal
    e2 = np.cross(ax, e1)
    if s == "r":
        e2 = -e2                                             # mirror: same anatomical side
    phi = np.degrees(np.arctan2(radial @ e2, radial @ e1))
    R = np.linalg.norm(radial, axis=1)
    band = np.abs(u - P["strap_u"]) - 0.5 * P["strap_w"]
    pe, po = P["strap_end_deg"], P["strap_overlap_deg"]
    dphi = (phi - pe + 540.0) % 360.0 - 180.0               # angle past the strap end
    top_sector = np.maximum(dphi, -po - dphi) * np.radians(1) * R     # <0 inside the overlap sector
    top = np.maximum(band, top_sector)
    sig = dphi * np.radians(1) * R                           # arc length past the end
    tab = _rrect_sdf(sig, u, 0.5 * P["tab_len"] - 0.002, P["strap_u"], 0.5 * P["tab_len"] + 0.002,
                     P["tab_half_w"], 0.005)
    tab = np.maximum(tab, -sig)                              # tab only beyond the end
    fr["strap"] = band
    fr["strap_top"] = np.minimum(top, tab)
    fr["phi"] = phi
    # ---- geometric relief height (metres, along the normal, on top of the base thickness)
    lea = smoothstep(P["leather_z"] - 0.06, P["leather_z"] + 0.06, zp)
    cuffm = smoothstep(0.002, -0.002, fr["cuff"])
    t = P["t_fabric"] + (P["t_leather"] - P["t_fabric"]) * lea
    t = t * (1 - cuffm) + P["t_cuff"] * cuffm
    h = np.zeros(V)
    h += P["h_cap"] * smoothstep(-0.0008, 0.0008, cap) * (1 - cuffm)
    h += P["h_patch"] * smoothstep(0.0008, -0.0008, fr["patch"]) * (1 - cuffm)
    h += P["h_plate"] * smoothstep(0.0008, -0.0008, plate)
    h += P["h_pad"] * smoothstep(0.0, -0.0035, pad) * (0.85 + 0.15 * smoothstep(0.0, -0.008, pad))
    h += P["h_pip"] * smoothstep(0.0, -0.0028, pip)
    strapm = smoothstep(0.0008, -0.0008, band)
    h += P["h_strap"] * strapm
    h += P["h_strap_top"] * smoothstep(0.0008, -0.0008, top) + P["h_tab"] * smoothstep(0.0008, -0.0008, tab)
    fr["t_base"] = t
    fr["h_geo"] = h
    return fr


FIELD_ATTRS = ("z_palm", "cap", "patch", "guard", "guard_pad", "guard_plate", "pip_pad", "cuff", "strap",
               "strap_top", "phi", "u_arm", "hand_a", "hand_b", "t_base", "h_geo", "hem", "skin_gap")


def store_fields(ob, fr):
    me = ob.data
    for k in FIELD_ATTRS:
        if k not in fr:
            continue
        a = me.attributes.get(k) or me.attributes.new(k, 'FLOAT', 'POINT')
        a.data.foreach_set("value", np.asarray(fr[k], np.float32))


def load_fields(ob):
    me = ob.data
    out = {}
    for k in FIELD_ATTRS:
        a = me.attributes.get(k)
        if a is None:
            continue
        v = np.empty(len(me.vertices), np.float32)
        a.data.foreach_get("value", v)
        out[k] = v.astype(np.float64)
    return out


def build_glove(arm, body, s, col, name, design=None, refine=True):
    """Build the glove shell for side s (see section 1).  Returns (object, report).  The object
    carries vertex groups (<= 4 influences, normalised) and the zone fields as float attributes."""
    P = dict(GLOVE_DESIGN, **(design or {}))
    rep = {}
    vids, faces, Wreg, names = glove_region(arm, body, s, P["cuff_len"])
    skin_all = C.mesh_arrays(body)
    co0 = skin_all[vids]
    ob = object_from_region(name, co0, faces, Wreg, names, col)
    rep["region"] = {"body_vertices": int(len(vids)), "faces": len(faces)}
    w, d, r, p = hand_frame(arm, s)
    wj, ax = forearm_axis(arm, s)
    if refine:
        me = ob.data
        mask = np.zeros(len(me.polygons), bool)
        F = bone_rest_frames(arm)
        am = [((F[f"{f}_01_{s}"]["H"] - w) @ d) for f in FINGERS4]
        for i, poly in enumerate(me.polygons):
            c = np.array(poly.center)
            nn = np.array(poly.normal)
            a_, b_ = (c - w) @ d, (c - w) @ r
            if nn @ -p > 0.25 and min(am) - 0.035 < a_ < max(am) + 0.018 and -0.06 < b_ < 0.055:
                mask[i] = True
        refine_faces(ob, mask)
        rep["refined_faces"] = int(mask.sum())
    apply_subsurf(ob, 1)
    me = ob.data
    names_g = [g.name for g in ob.vertex_groups]
    W = read_groups(ob, names_g)
    S = mesh_co(me)
    tris = mesh_tris(me)
    N = vertex_normals(S, tris)
    # distance of the ORIGINAL (low-res) skin outside the smooth subdivided surface
    btris = C.triangulate([list(p_.vertices) for p_ in body.data.polygons])
    near = np.linalg.norm(skin_all - wj, axis=1) < 0.30
    bt = btris[near[btris].all(1)]
    bvh = bvh_arrays(skin_all, bt)
    delta = np.zeros(len(S))
    for i, (q, n) in enumerate(zip(S, N)):
        loc, fn, fi, dist = bvh.find_nearest(Vector(tuple(map(float, q))), 0.02)
        if loc is not None:
            delta[i] = (np.array(loc) - q) @ n
    nbrs = neighbours_from_tris(tris, len(S))
    dpos = np.maximum(delta, 0.0)
    dpos = np.maximum(laplacian_smooth_field(dpos, nbrs, iters=2, alpha=0.5), dpos * 0.85)
    rep["skin_outside_subdiv_mm"] = {"max": round(float(delta.max()) * 1000, 3),
                                     "min": round(float(delta.min()) * 1000, 3)}
    fr = glove_fields(S, N, W, names_g, arm, s, P)
    hgeo = laplacian_smooth_field(fr["h_geo"], nbrs, iters=2, alpha=0.5)
    H = fr["t_base"] + hgeo + dpos + 0.00015
    G = S + N * H[:, None]
    me.vertices.foreach_set("co", G.ravel())
    me.update()
    fr["h_geo"] = hgeo
    fr["skin_gap"] = H - np.minimum(delta, 0.0) * 0.0     # nominal shell offset above the skin
    fr["hem"] = np.zeros(len(S))
    store_fields(ob, fr)
    # hem at the cuff opening
    loop = boundary_loop(me)
    inward = float(np.median(H[loop])) - 0.0002
    new = add_hem(ob, inward=inward, depth=0.009, arm_axis=ax, centre=wj)
    me = ob.data
    fr2 = load_fields(ob)
    n0 = len(S)
    # attribute values of new hem vertices: copy from their boundary vertex, flag hem = 1
    fr3 = {}
    L = len(loop)
    for k, v in fr2.items():
        vv = np.array(v)
        vv[n0:n0 + L] = vv[loop]
        vv[n0 + L:n0 + 2 * L] = vv[loop]
        fr3[k] = vv
    fr3["hem"][n0:] = 1.0
    store_fields(ob, fr3)
    # weights: <= 4 influences, normalised (hem copies its boundary vertex)
    names_g = [g.name for g in ob.vertex_groups]
    W = read_groups(ob, names_g)
    W[n0:n0 + L] = W[loop]
    W[n0 + L:n0 + 2 * L] = W[loop]
    W4 = limit_weights(W, 4)
    write_groups(ob, W4, names_g)
    rep["vertices"] = len(me.vertices)
    rep["triangles"] = int(sum(len(p_.vertices) - 2 for p_ in me.polygons))
    rep["shell_offset_mm"] = {"min": round(float(H.min()) * 1000, 3), "max": round(float(H.max()) * 1000, 3),
                              "median": round(float(np.median(H)) * 1000, 3)}
    for poly in me.polygons:
        poly.use_smooth = True
    return ob, rep


# =============================================================================
# 3a. Glove UVs
# =============================================================================

def glove_uv(ob, fields, margin=0.006, method='MINIMUM_STRETCH'):
    """UV islands along the construction: seams where the palmar field changes sign (palm side /
    back side halves of hand, fingers, thumb and cuff) and around the hem; unwrapped with SLIM,
    islands scaled to equal texel density and packed.  Returns a stats dict."""
    me = ob.data
    while len(me.uv_layers):
        me.uv_layers.remove(me.uv_layers[0])
    me.uv_layers.new(name="UVMap")
    z = fields["z_palm"]
    hem = fields["hem"] > 0.5
    # finger family per vertex (fingers get their own islands, cut near the finger bases)
    names = [g.name for g in ob.vertex_groups]
    W = read_groups(ob, names)
    fam = np.full(len(me.vertices), -1)
    for k, f in enumerate(FINGERS):
        cols = [j for j, n in enumerate(names) if n.startswith(f + "_")]
        if cols:
            fam[W[:, cols].sum(1) > 0.5] = k
    bm = bmesh.new()
    bm.from_mesh(me)
    cls = {}
    for f in bm.faces:
        vs = [v.index for v in f.verts]
        fm = np.bincount(fam[vs] + 1, minlength=6).argmax() - 1
        cls[f.index] = (99 if hem[vs].any() else (0 if z[vs].mean() > 0.0 else 1)) + 10 * (fm + 1)
    nseam = 0
    for e in bm.edges:
        fs = e.link_faces
        e.seam = len(fs) == 2 and cls[fs[0].index] != cls[fs[1].index]
        nseam += e.seam
    bm.to_mesh(me)
    bm.free()
    me.update()
    C_sel = bpy.context
    bpy.context.view_layer.objects.active = ob
    for o in bpy.context.selected_objects:
        o.select_set(False)
    ob.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.uv.unwrap(method=method, margin=margin)
    bpy.ops.uv.select_all(action='SELECT')
    bpy.ops.uv.average_islands_scale()
    bpy.ops.uv.pack_islands(udim_source='CLOSEST_UDIM', rotate=True, margin_method='FRACTION',
                            margin=margin, shape_method='CONCAVE')
    bpy.ops.object.mode_set(mode='OBJECT')
    return {"seam_edges": int(nseam)}


def uv_stats(ob, res):
    """Texel density (px per cm, per triangle area-weighted) and UV fold / flip count."""
    me = ob.data
    tris = mesh_tris(me)
    uv = np.empty(len(me.loops) * 2)
    me.uv_layers["UVMap"].data.foreach_get("uv", uv)
    uv = uv.reshape(-1, 2)
    lt = np.empty(len(me.loop_triangles) * 3, np.int64)
    me.loop_triangles.foreach_get("loops", lt)
    lt = lt.reshape(-1, 3)
    co = mesh_co(me)
    a3 = 0.5 * np.linalg.norm(np.cross(co[tris[:, 1]] - co[tris[:, 0]], co[tris[:, 2]] - co[tris[:, 0]]), axis=1)
    U = uv[lt] * res
    a2s = 0.5 * ((U[:, 1, 0] - U[:, 0, 0]) * (U[:, 2, 1] - U[:, 0, 1]) - (U[:, 2, 0] - U[:, 0, 0]) * (U[:, 1, 1] - U[:, 0, 1]))
    dens = np.sqrt(np.abs(a2s) / np.maximum(a3 * 1e4, 1e-12))          # px per cm
    wsum = a3.sum()
    flips = int((a2s < 0).sum())
    return {"texel_density_px_per_cm_mean": round(float((dens * a3).sum() / wsum), 1),
            "texel_density_p05_p95": [round(float(np.percentile(dens, 5)), 1), round(float(np.percentile(dens, 95)), 1)],
            "uv_coverage": round(float(np.abs(a2s).sum() / res ** 2), 3),
            "flipped_uv_triangles": flips, "sign_majority": int((a2s > 0).sum())}


# =============================================================================
# 3b. Texel-space glove textures (numpy)
# =============================================================================
#
# The glove material is evaluated per TEXEL from the interpolated rest-pose zone fields, so the
# seams are smooth curves (not mesh edges), stitching has a true dash pitch along each seam, and
# the result is exactly reproducible.  Height -> tangent-space normal uses each triangle's UV
# Jacobian (MikkTSpace-style T = dP/du, B = sign * N x T), so the normal map is correct for
# rotated / mirrored islands.

def raster_uv_bary(uv_tris, res):
    """uv_tris (n,3,2) in 0..1.  Returns (tri index, pixel index, barycentrics (m,3)) of every
    texel centre inside a triangle (first triangle wins on shared edges)."""
    P = uv_tris * res
    x0 = np.floor(P[:, :, 0].min(1) - 0.5).astype(np.int64)
    y0 = np.floor(P[:, :, 1].min(1) - 0.5).astype(np.int64)
    x1 = np.ceil(P[:, :, 0].max(1) - 0.5).astype(np.int64)
    y1 = np.ceil(P[:, :, 1].max(1) - 0.5).astype(np.int64)
    size = np.maximum(x1 - x0 + 1, y1 - y0 + 1)
    d = ((P[:, 1, 1] - P[:, 2, 1]) * (P[:, 0, 0] - P[:, 2, 0]) + (P[:, 2, 0] - P[:, 1, 0]) * (P[:, 0, 1] - P[:, 2, 1]))
    ok = np.abs(d) > 1e-12
    T, PX, BA = [], [], []
    lo = 0
    for K in (2, 4, 8, 16, 32, 64, 128, 256, 512):
        sel = np.nonzero(ok & (size <= K) & (size > lo))[0]
        lo = K
        if not len(sel):
            continue
        gx, gy = np.meshgrid(np.arange(K), np.arange(K))
        gx, gy = gx.ravel(), gy.ravel()
        step = max(1, 3000000 // (K * K))
        for c0 in range(0, len(sel), step):
            t = sel[c0:c0 + step]
            X = x0[t, None] + gx[None, :] + 0.5
            Y = y0[t, None] + gy[None, :] + 0.5
            Q = P[t]
            dd = d[t][:, None]
            l0 = ((Q[:, 1, 1] - Q[:, 2, 1])[:, None] * (X - Q[:, 2, 0][:, None]) + (Q[:, 2, 0] - Q[:, 1, 0])[:, None] * (Y - Q[:, 2, 1][:, None])) / dd
            l1 = ((Q[:, 2, 1] - Q[:, 0, 1])[:, None] * (X - Q[:, 2, 0][:, None]) + (Q[:, 0, 0] - Q[:, 2, 0])[:, None] * (Y - Q[:, 2, 1][:, None])) / dd
            l2 = 1.0 - l0 - l1
            e = -1e-6
            ins = (l0 >= e) & (l1 >= e) & (l2 >= e) & (X >= 0) & (Y >= 0) & (X < res) & (Y < res)
            ti, gi = np.nonzero(ins)
            T.append(t[ti])
            PX.append(np.floor(Y[ti, gi]).astype(np.int64) * res + np.floor(X[ti, gi]).astype(np.int64))
            BA.append(np.stack([l0[ti, gi], l1[ti, gi], l2[ti, gi]], 1).astype(np.float32))
    T, PX, BA = np.concatenate(T), np.concatenate(PX), np.concatenate(BA)
    _, first = np.unique(PX, return_index=True)
    return T[first], PX[first], BA[first]


def _hash_dirs(n, seed):
    rng = np.random.default_rng(seed)
    v = rng.normal(size=(n, 3))
    return v / np.linalg.norm(v, axis=1)[:, None], rng.uniform(0, 2 * np.pi, n)


def wave_noise(P, scale, octaves=4, seed=0, n=6):
    """Smooth pseudo-noise in 3D (sum of random-direction cosines, deterministic), ~[-1, 1].
    scale = feature size in metres."""
    out = np.zeros(len(P), np.float32)
    amp, tot = 1.0, 0.0
    for o in range(octaves):
        dirs, ph = _hash_dirs(n, seed * 101 + o)
        k = 2 * np.pi / (scale / (2.0 ** o))
        acc = np.zeros(len(P), np.float32)
        for dv, p0 in zip(dirs, ph):
            acc += np.cos((P @ dv) * k + p0).astype(np.float32)
        out += amp * acc / math.sqrt(n)
        tot += amp
        amp *= 0.5
    return out / tot


def _line(x, half):
    """Soft line profile: 1 at x = 0, 0 beyond `half`."""
    return smoothstep(half, 0.0, np.abs(x))


GLOVE_PALETTES = {
    # linear RGB, roughness; 'coyote' = coyote brown tactical, 'black' = all-black tactical
    "coyote": dict(fabric=(0.200, 0.115, 0.046), gusset=(0.175, 0.101, 0.041), leather=(0.330, 0.200, 0.090),
                   patch=(0.275, 0.165, 0.072), cap=(0.305, 0.185, 0.083), tpr=(0.105, 0.066, 0.032),
                   cuff=(0.140, 0.083, 0.036), strap=(0.185, 0.108, 0.044), lining=(0.020, 0.019, 0.018),
                   thread=(0.300, 0.215, 0.120), tab=(0.022, 0.021, 0.020),
                   r_fabric=0.90, r_leather=0.60, r_tpr=0.68, r_cuff=0.82, r_strap=0.93, r_thread=0.78),
    "black": dict(fabric=(0.022, 0.022, 0.024), gusset=(0.020, 0.020, 0.022), leather=(0.030, 0.029, 0.030),
                  patch=(0.026, 0.025, 0.026), cap=(0.028, 0.027, 0.028), tpr=(0.017, 0.017, 0.018),
                  cuff=(0.016, 0.016, 0.017), strap=(0.020, 0.020, 0.021), lining=(0.014, 0.014, 0.015),
                  thread=(0.055, 0.055, 0.058), tab=(0.014, 0.014, 0.015),
                  r_fabric=0.88, r_leather=0.52, r_tpr=0.66, r_cuff=0.78, r_strap=0.90, r_thread=0.72),
}


def glove_texel_data(ob, arm, s, res):
    """Rasterise the glove's UV layout and interpolate everything the material needs per texel."""
    me = ob.data
    tris = mesh_tris(me)
    lt = np.empty(len(me.loop_triangles) * 3, np.int64)
    me.loop_triangles.foreach_get("loops", lt)
    lt = lt.reshape(-1, 3)
    uv = np.empty(len(me.loops) * 2)
    me.uv_layers["UVMap"].data.foreach_get("uv", uv)
    uv = uv.reshape(-1, 2)
    co = mesh_co(me)
    fr = load_fields(ob)
    nrm = vertex_normals(co, tris)
    # the shell rest position minus its relief = skin-level reference (patterns stay put)
    ti, px, ba = raster_uv_bary(uv[lt], res)
    tv = tris[ti]
    def I(a):
        a = np.asarray(a)
        if a.ndim == 1:
            return (a[tv[:, 0]] * ba[:, 0] + a[tv[:, 1]] * ba[:, 1] + a[tv[:, 2]] * ba[:, 2]).astype(np.float32)
        return (a[tv[:, 0]] * ba[:, 0:1] + a[tv[:, 1]] * ba[:, 1:2] + a[tv[:, 2]] * ba[:, 2:3]).astype(np.float32)
    # signed distance families (metres, negative inside the feature) and their seam tangents
    z = fr["z_palm"]
    gz = vertex_gradient(z, co, tris)
    s_leather = -(z - GLOVE_DESIGN["leather_z"]) / np.maximum(np.linalg.norm(gz, axis=1), 1.0)
    fams = {"leather": s_leather, "cap": -fr["cap"], "patch": fr["patch"], "plate": fr["guard_plate"],
            "pad": fr["guard_pad"], "pip": fr["pip_pad"], "cuff": fr["cuff"], "strap": fr["strap"],
            "top": fr["strap_top"]}
    td = {"ti": ti, "px": px, "res": res}
    td["P"] = I(co)
    td["N"] = I(nrm)
    td["N"] /= np.maximum(np.linalg.norm(td["N"], axis=1)[:, None], 1e-9)
    for k, f in fams.items():
        td["s_" + k] = I(np.clip(f, -0.03, 0.03))
        g = vertex_gradient(f, co, tris)
        t = np.cross(nrm, g)
        t /= np.maximum(np.linalg.norm(t, axis=1)[:, None], 1e-9)
        td["t_" + k] = I(t)
    for k in ("z_palm", "hem", "h_geo", "hand_a", "hand_b", "u_arm"):
        td[k] = I(fr[k])
    # fabric warp direction: weight-blended bone long axes, in the tangent plane
    F = bone_rest_frames(arm)
    names = [g.name for g in ob.vertex_groups]
    W = read_groups(ob, names)
    warp = np.zeros_like(co)
    for j, n in enumerate(names):
        warp += W[:, j:j + 1] * F[n]["Y"][None, :]
    warp -= nrm * (warp * nrm).sum(1)[:, None]
    warp /= np.maximum(np.linalg.norm(warp, axis=1)[:, None], 1e-9)
    td["warp"] = I(warp)
    # per-triangle UV Jacobian -> tangent frame (for the normal map)
    U = uv[lt] * res
    Pt = co[tris]
    e1, e2 = Pt[:, 1] - Pt[:, 0], Pt[:, 2] - Pt[:, 0]
    du1, du2 = U[:, 1] - U[:, 0], U[:, 2] - U[:, 0]
    det = du1[:, 0] * du2[:, 1] - du2[:, 0] * du1[:, 1]
    det = np.where(np.abs(det) < 1e-12, 1e-12, det)
    dPdu = (e1 * du2[:, 1:2] - e2 * du1[:, 1:2]) / det[:, None]       # metres per texel along +u
    dPdv = (e2 * du1[:, 0:1] - e1 * du2[:, 0:1]) / det[:, None]
    td["dPdu"], td["dPdv"] = dPdu[ti].astype(np.float32), dPdv[ti].astype(np.float32)
    return td


def glove_material_maps(td, palette, seed=7):
    """Evaluate the glove material per texel.  Returns dict of per-texel arrays: base (m,3) linear,
    rough (m,), metal (m,), height (m,) metres (normal-map detail only), cavity (m,)."""
    Pl = palette
    Pp = td["P"]
    m = len(Pp)
    D = GLOVE_DESIGN
    sm = lambda a, b, x: smoothstep(a, b, x).astype(np.float32)           # noqa: E731
    hem = td["hem"] > 0.5
    cuff = sm(0.00025, -0.00025, td["s_cuff"])
    strap = sm(0.00025, -0.00025, td["s_strap"]) * cuff
    top = sm(0.00025, -0.00025, td["s_top"]) * strap
    plate = sm(0.00025, -0.00025, td["s_plate"]) * (1 - cuff)
    pad = sm(0.00025, -0.00025, td["s_pad"]) * plate
    pip = sm(0.00025, -0.00025, td["s_pip"]) * (1 - cuff)
    tpr = np.maximum(plate, pip)
    cap = sm(0.00025, -0.00025, td["s_cap"]) * (1 - cuff) * (1 - tpr)
    patch = sm(0.00025, -0.00025, td["s_patch"]) * (1 - cuff) * (1 - tpr) * (1 - cap)
    lea = sm(0.00025, -0.00025, td["s_leather"]) * (1 - cuff) * (1 - tpr) * (1 - cap) * (1 - patch)
    fab = np.clip(1 - cuff - tpr - cap - patch - lea, 0, 1)
    # gussets = fabric on the finger sides (palmar field near 0)
    gus = fab * sm(-0.55, -0.25, td["z_palm"])
    # ---- micro patterns (metres of height)
    warp = td["warp"]
    weft = np.cross(td["N"], warp)
    kn = 2 * np.pi / 0.00085
    a1 = (Pp * warp).sum(1) * kn
    a2 = (Pp * weft).sum(1) * kn * 0.5
    knit = (np.abs(np.sin(a1 * 0.5 + 0.5 * np.sin(a2))) * 0.8 + 0.2 * np.cos(a2 * 2)).astype(np.float32)
    grain = wave_noise(Pp, 0.0009, 3, seed + 1, 7)
    pebble = np.abs(wave_noise(Pp, 0.0014, 2, seed + 2, 8))
    stip = wave_noise(Pp, 0.0006, 2, seed + 3, 6)
    fuzz = wave_noise(Pp, 0.0004, 2, seed + 4, 8)
    macro = wave_noise(Pp, 0.02, 3, seed + 5, 6)
    blot = wave_noise(Pp, 0.006, 3, seed + 6, 6)
    h = np.zeros(m, np.float32)
    h += fab * (knit - 0.5) * 0.00006
    h += (lea + cap + patch) * (0.6 * grain - 0.4 * pebble) * 0.00005
    h += tpr * stip * 0.00003 + cuff * (1 - strap) * stip * 0.00002
    h += strap * fuzz * 0.00006
    # ---- relief edges: crisp version of the geometric relief minus the interpolated geometry
    crisp = np.zeros(m, np.float32)
    crisp += D["h_cap"] * sm(-0.0002, 0.0002, -td["s_cap"]) * (1 - cuff)
    crisp += D["h_patch"] * sm(0.0002, -0.0002, td["s_patch"]) * (1 - cuff)
    crisp += D["h_plate"] * sm(0.0002, -0.0002, td["s_plate"])
    crisp += D["h_pad"] * sm(0.0, -0.0025, td["s_pad"]) * (0.85 + 0.15 * sm(0.0, -0.008, td["s_pad"]))
    crisp += D["h_pip"] * sm(0.0, -0.002, td["s_pip"])
    crisp += D["h_strap"] * sm(0.0002, -0.0002, td["s_strap"])
    crisp += (D["h_strap_top"] + 0.0) * sm(0.0002, -0.0002, td["s_top"])
    lea_g = sm(-0.0004, 0.0004, -td["s_leather"])
    crisp += (D["t_leather"] - D["t_fabric"]) * lea_g * (1 - cuff)
    geo = td["h_geo"] + (D["t_leather"] - D["t_fabric"]) * sm(D["leather_z"] - 0.06, D["leather_z"] + 0.06, td["z_palm"]) * (1 - cuff)
    h += np.clip(crisp - geo, -0.0015, 0.0015) * 0.8
    # ---- seams: groove at each panel join + dashed stitch rows
    rows = {"leather": (-0.0014, 0.0014), "cap": (-0.0013,), "patch": (-0.0015, -0.0040), "plate": (-0.0014,),
            "pip": (-0.0012,), "cuff": (-0.0016, 0.0016), "strap": (-0.0016,), "top": (-0.0015,)}
    active = {"leather": (1 - cuff) * (1 - tpr), "cap": (1 - cuff) * (1 - tpr), "patch": (1 - cuff) * (1 - tpr),
              "plate": (1 - cuff), "pip": (1 - cuff), "cuff": 1 - strap, "strap": cuff, "top": strap, "pad": plate}
    thread = np.zeros(m, np.float32)
    groove = np.zeros(m, np.float32)
    pitch = 0.0031
    for fam in ("leather", "cap", "patch", "plate", "pip", "cuff", "strap", "top", "pad"):
        sv = td["s_" + fam]
        act = active[fam]
        groove = np.maximum(groove, _line(sv, 0.00032 if fam != "pad" else 0.00045).astype(np.float32) * act)
        if fam == "pad":
            continue
        ph = (Pp * td["t_" + fam]).sum(1) / pitch
        fph = ph % 1.0
        dash = sm(0.10, 0.18, fph) * sm(0.78, 0.70, fph)          # ~55 % duty: 1.7 mm thread, 1.4 mm gap
        for off in rows[fam]:
            prof = _line(sv - off, 0.00030).astype(np.float32)
            thread = np.maximum(thread, prof * dash * act)
            # needle holes between dashes
            groove = np.maximum(groove, 0.6 * prof * (1 - dash) * act * sm(0.0, 0.00015, 0.00030 - np.abs(sv - off)))
    h -= groove * 0.00030
    h += thread * 0.00016
    h[hem] = (knit[hem] - 0.5) * 0.00006
    # ---- colour
    def c(nm):
        return np.array(Pl[nm], np.float32)[None, :]
    base = (fab[:, None] * (c("fabric") * (1 - gus[:, None]) + c("gusset") * gus[:, None])
            + lea[:, None] * c("leather") + patch[:, None] * c("patch") + cap[:, None] * c("cap")
            + tpr[:, None] * c("tpr") + cuff[:, None] * (c("cuff") * (1 - strap[:, None]) + c("strap") * strap[:, None]))
    # pull tab of the strap: rubberised (dark)
    var = 1.0 + 0.05 * macro + 0.03 * blot * (1 - fab)
    base = base * var[:, None]
    base *= (1.0 - 0.22 * fab * (knit - 0.5))[:, None]
    base *= (1.0 + 0.10 * (lea + cap + patch) * grain)[:, None]
    # wear: palmar leather / caps a touch lighter and smoother where it rubs (palm heel, finger pads)
    wear = np.clip((lea + cap + patch) * sm(0.3, 0.9, td["z_palm"]) * (0.5 + 0.5 * blot), 0, 1).astype(np.float32)
    base *= (1.0 + 0.12 * wear)[:, None]
    base = base * (1 - thread[:, None]) + c("thread") * thread[:, None] * (0.9 + 0.1 * var[:, None])
    base *= (1.0 - 0.35 * groove)[:, None]
    base[hem] = np.array(Pl["lining"], np.float32)
    rough = (fab * Pl["r_fabric"] + (lea + patch) * Pl["r_leather"] + cap * (Pl["r_leather"] + 0.04)
             + tpr * Pl["r_tpr"] + cuff * (Pl["r_cuff"] * (1 - strap) + Pl["r_strap"] * strap)).astype(np.float32)
    rough = rough * (1 - thread) + Pl["r_thread"] * thread
    rough -= 0.10 * wear
    rough += 0.03 * macro
    rough[hem] = 0.92
    cavity = (1.0 - 0.45 * groove).astype(np.float32)
    return {"base": np.clip(base, 0, 1), "rough": np.clip(rough, 0.2, 1.0), "metal": np.zeros(m, np.float32),
            "height": h, "cavity": cavity,
            "zones": {"fabric": fab, "leather": lea, "patch": patch, "cap": cap, "tpr": tpr, "cuff": cuff,
                      "strap": strap}}


def height_to_normal(td, height, res, dilate_px=4):
    """Tangent-space OpenGL normal per texel from the texel height (metres) and each texel's
    triangle UV Jacobian.  Returns (m,3) in -1..1."""
    import ivlib
    img = np.zeros((res, res, 4), np.float32)
    flat = img.reshape(-1, 4)
    flat[td["px"], 0] = height
    flat[td["px"], 3] = 1.0
    img = ivlib.dilate(img, dilate_px)
    Hh = img[..., 0]
    # central differences in texel units (x = +u, y = +v: row index grows with v)
    hx = np.zeros_like(Hh); hy = np.zeros_like(Hh)
    hx[:, 1:-1] = 0.5 * (Hh[:, 2:] - Hh[:, :-2])
    hy[1:-1, :] = 0.5 * (Hh[2:, :] - Hh[:-2, :])
    hu = hx.reshape(-1)[td["px"]]
    hv = hy.reshape(-1)[td["px"]]
    N = td["N"]
    a, b = td["dPdu"], td["dPdv"]
    T = a - N * (a * N).sum(1)[:, None]
    T /= np.maximum(np.linalg.norm(T, axis=1)[:, None], 1e-12)
    sgn = np.sign((np.cross(N, T) * b).sum(1))
    sgn[sgn == 0] = 1
    B = np.cross(N, T) * sgn[:, None]
    # solve g . a = hu, g . b = hv for the surface gradient g = gT T + gB B
    aT, aB = (a * T).sum(1), (a * B).sum(1)
    bT, bB = (b * T).sum(1), (b * B).sum(1)
    det = aT * bB - aB * bT
    det = np.where(np.abs(det) < 1e-18, 1e-18, det)
    gT = (hu * bB - hv * aB) / det
    gB = (aT * hv - bT * hu) / det
    n = np.stack([-gT, -gB, np.ones_like(gT)], 1)
    n /= np.linalg.norm(n, axis=1)[:, None]
    return n.astype(np.float32)


def write_texture(values, td, res, path, mode, fill, srgb=False, dilate_px=16):
    """Scatter per-texel values into an image, dilate the gutters (distance ownership) and save."""
    import ivlib
    ch = values.shape[1] if values.ndim == 2 else 1
    img = np.zeros((res, res, 4), np.float32)
    img[..., :3] = fill
    flat = img.reshape(-1, 4)
    if ch == 1:
        flat[td["px"], 0] = values
        flat[td["px"], 1] = values
        flat[td["px"], 2] = values
    else:
        flat[td["px"], :3] = values[:, :3]
    flat[td["px"], 3] = 1.0
    img = ivlib.dilate(img, dilate_px, fill=fill)
    if srgb:
        img[..., :3] = ivlib.linear_to_srgb(img[..., :3])
    # our raster rows grow with v (bottom-up) = Blender pixel order -> save_png flips
    return ivlib.save_png(img, path, mode=mode, dither_seed=11 if mode == 'RGB' else None)


def bake_ao(ob, res, distance=0.008, samples=32):
    """Cycles ambient-occlusion bake of one object on its UVMap (rest pose, object alone).
    Returns an HxWx4 float array (Blender row order) with alpha = coverage."""
    import ivlib
    sc = bpy.context.scene
    hidden = []
    for o in sc.objects:
        if o is not ob and o.type == 'MESH' and not o.hide_render:
            o.hide_render = True
            hidden.append(o)
    im = ivlib._float_image(ob.name + "_AO", res, (1.0, 1.0, 1.0))
    mat = bpy.data.materials.new(ob.name + "_AOBake")
    mat.use_nodes = True
    tn = mat.node_tree.nodes.new('ShaderNodeTexImage')
    tn.image = im
    mat.node_tree.nodes.active = tn
    old = list(ob.data.materials)
    ob.data.materials.clear()
    ob.data.materials.append(mat)
    world = sc.world
    sc.render.engine = 'CYCLES'
    sc.cycles.samples = samples
    sc.render.bake.margin = 0
    sc.render.bake.use_selected_to_active = False
    sc.render.bake.target = 'IMAGE_TEXTURES'
    if world is None:
        sc.world = bpy.data.worlds.new("IVH_World")
    sc.world.light_settings.distance = distance
    ivlib.select([ob], ob)
    bpy.ops.object.bake(type='AO', margin=0, use_clear=False)
    arr = ivlib.image_to_array(im)
    ob.data.materials.clear()
    for m_ in old:
        ob.data.materials.append(m_)
    bpy.data.materials.remove(mat)
    for o in hidden:
        o.hide_render = False
    return arr


def glove_textures(ob, arm, s, res, tex_dir, prefix, palettes=("coyote", "black"), ao_distance=0.008):
    """Full texture synthesis for one glove (the mirrored glove shares the maps).
    Writes <prefix>Normal.png (OpenGL), <prefix>Normal_DX.png, and per palette
    <prefix><Palette>_BaseColor.png (sRGB) + <prefix><Palette>_ORM.png (R AO, G roughness,
    B metallic).  Returns (paths, stats)."""
    import ivlib
    import time
    t0 = time.time()
    td = glove_texel_data(ob, arm, s, res)
    ao_img = bake_ao(ob, res, ao_distance)
    ao = ao_img.reshape(-1, 4)[td["px"], 0]
    stats = {"texels": int(len(td["px"])), "coverage": round(len(td["px"]) / res ** 2, 4),
             "ao_bake_distance_m": ao_distance}
    paths = {}
    os.makedirs(tex_dir, exist_ok=True)
    first = None
    for pal in palettes:
        mm = glove_material_maps(td, GLOVE_PALETTES[pal])
        if first is None:
            first = mm
            n = height_to_normal(td, mm["height"], res)
            nimg = n * 0.5 + 0.5
            paths["Normal"] = write_texture(nimg, td, res, os.path.join(tex_dir, prefix + "Normal.png"), 'RGB', (0.5, 0.5, 1.0))
            paths["Normal_DX"] = ivlib.normal_gl_to_dx(paths["Normal"], os.path.join(tex_dir, prefix + "Normal_DX.png"))
            stats["zone_texel_share"] = {k: round(float(v.mean()), 4) for k, v in mm["zones"].items()}
            stats["height_range_mm"] = [round(float(mm["height"].min()) * 1000, 3), round(float(mm["height"].max()) * 1000, 3)]
        tag = pal.capitalize()
        paths[f"{tag}_BaseColor"] = write_texture(mm["base"], td, res, os.path.join(tex_dir, f"{prefix}{tag}_BaseColor.png"),
                                                  'RGB', (0.1, 0.1, 0.1), srgb=True)
        orm = np.stack([np.clip(ao * mm["cavity"], 0, 1), mm["rough"], mm["metal"]], 1)
        paths[f"{tag}_ORM"] = write_texture(orm, td, res, os.path.join(tex_dir, f"{prefix}{tag}_ORM.png"), 'RGB', (1.0, 0.8, 0.0))
    stats["seconds"] = round(time.time() - t0, 1)
    return paths, stats


# =============================================================================
# 4. Numpy skinning of hand meshes (FK from local quaternions)
# =============================================================================

def _m4(M):
    return np.array(M, dtype=np.float64)


def quat_m4(q):
    return _m4(q.to_matrix().to_4x4()) if q is not None else np.eye(4)


class HandModel:
    """Fast LBS of skinned meshes for ONE hand: the hand bone gets an explicit world matrix, the
    finger bones follow by FK from local rotations (anatomical poses -> ivchar.hand_pose_quats);
    the forearm bones follow the hand rigidly (wrist neutral) unless given explicitly."""

    def __init__(self, arm, objs, s):
        self.arm, self.s = arm, s
        self.names = [b.name for b in arm.data.bones]
        self.R = {b.name: _m4(arm.matrix_world @ b.matrix_local) for b in arm.data.bones}
        self.Ri = {n: np.linalg.inv(M) for n, M in self.R.items()}
        self.parent = {b.name: (b.parent.name if b.parent else None) for b in arm.data.bones}
        self.rel = {n: (self.Ri[p] @ self.R[n] if p else self.R[n]) for n, p in self.parent.items()}
        hand = f"hand_{s}"
        self.hand = hand
        self.sub = [b.name for b in arm.data.bones if b.name != hand and self._under(b.name, hand)]
        self.follow = [f"lowerarm_{s}", f"lowerarm_twist_01_{s}", f"upperarm_{s}", f"upperarm_twist_01_{s}"]
        self.rest_angles = C.hand_rest_angles(arm, s)
        self.meshes = []
        for ob in objs:
            me = ob.data
            co = C.mesh_arrays(ob)
            gn = [g.name for g in ob.vertex_groups]
            W = read_groups(ob, gn)
            k = min(4, W.shape[1])
            idx = np.argsort(-W, axis=1)[:, :k]
            ww = np.take_along_axis(W, idx, 1)
            ww /= np.maximum(ww.sum(1, keepdims=True), 1e-12)
            bidx = np.array([[self.names.index(gn[j]) for j in row] for row in idx])
            self.meshes.append(dict(ob=ob, co=co, bidx=bidx, w=ww, tris=mesh_tris(me), groups=gn, W=W))

    def _under(self, n, anc):
        p = self.parent[n]
        while p:
            if p == anc:
                return True
            p = self.parent[p]
        return False

    def world(self, hand_world=None, quats=None, extra=None):
        """Pose-space world matrices of the hand subtree (+ forearm followers)."""
        quats = quats or {}
        H = self.R[self.hand] if hand_world is None else _m4(hand_world)
        M = {self.hand: H}
        for n in self.sub:
            M[n] = M[self.parent[n]] @ self.rel[n] @ quat_m4(quats.get(n))
        for n in self.follow:
            M[n] = H @ self.Ri[self.hand] @ self.R[n]
        if extra:
            M.update({k: _m4(v) for k, v in extra.items()})
        return M

    def skin_mats(self, M):
        S = np.repeat(np.eye(4)[None], len(self.names), 0)
        for n, m in M.items():
            S[self.names.index(n)] = m @ self.Ri[n]
        return S

    def skin(self, k, S, vmask=None):
        m = self.meshes[k]
        co, bidx, w = m["co"], m["bidx"], m["w"]
        if vmask is not None:
            co, bidx, w = co[vmask], bidx[vmask], w[vmask]
        Mv = np.einsum('vk,vkij->vij', w, S[bidx])
        return np.einsum('vij,vj->vi', Mv[:, :3, :3], co) + Mv[:, :3, 3]

    def pose(self, pose, hand_world=None):
        q = C.hand_pose_quats(pose, self.s, self.rest_angles)
        return self.skin_mats(self.world(hand_world, q))

    def verts_of(self, k, bones, thr=0.2):
        m = self.meshes[k]
        cols = [j for j, g in enumerate(m["groups"]) if g in bones]
        return m["W"][:, cols].sum(1) > thr if cols else np.zeros(len(m["co"]), bool)


def frame_rotation(src, dst):
    """Rotation (3x3) taking the orthonormal frame src = (a, b, c) to dst (same handedness)."""
    A = np.stack(src, 1)
    B = np.stack(dst, 1)
    return B @ A.T


def hand_world_matrix(model, d, r, anchor_rest, anchor_world):
    """World matrix of the hand bone that turns the REST hand frame (d0, r0, p0) into the target
    (d, r, p = handedness of the side) and moves the rest-space point anchor_rest to anchor_world."""
    w0, d0, r0, p0 = hand_frame(model.arm, model.s)
    d = np.asarray(d, float); d /= np.linalg.norm(d)
    r = np.asarray(r, float); r = r - d * (r @ d); r /= np.linalg.norm(r)
    p = np.cross(d, r) if model.s == "l" else np.cross(r, d)
    Rt = frame_rotation((d0, r0, p0), (d, r, p))
    Hr = model.R[model.hand]
    H = np.eye(4)
    H[:3, :3] = Rt @ Hr[:3, :3]
    a = np.asarray(anchor_world, float)
    # the rest point maps to Rt (x - h0) + h
    h0 = Hr[:3, 3]
    H[:3, 3] = a - Rt @ (np.asarray(anchor_rest, float) - h0)
    return H


# =============================================================================
# 5. Contact metrics against static meshes (weapons)
# =============================================================================

class Collider:
    """Static world-space meshes (e.g. weapon parts) for gap / penetration queries."""

    def __init__(self, parts):
        """parts: list of (name, co (N,3), tris (M,3))."""
        self.parts = []
        allc, allt, owner = [], [], []
        off = 0
        for name, co, tris in parts:
            self.parts.append(dict(name=name, co=co, tris=tris, bvh=bvh_arrays(co, tris),
                                   lo=co.min(0), hi=co.max(0)))
            allc.append(co); allt.append(tris + off); owner += [len(self.parts) - 1] * len(tris)
            off += len(co)
        self.co = np.concatenate(allc)
        self.tris = np.concatenate(allt)
        self.owner = np.array(owner)
        self.bvh = bvh_arrays(self.co, self.tris)

    def signed(self, P, maxd=0.05):
        """Signed distance per point: + outside, - inside (nearest-face normal test; exact for
        small depths).  Returns (sd (N,), part index (N,))."""
        sd = np.full(len(P), maxd)
        pi = np.full(len(P), -1)
        for i, q in enumerate(P):
            v = Vector((float(q[0]), float(q[1]), float(q[2])))
            loc, n, fi, dist = self.bvh.find_nearest(v, maxd)
            if loc is None:
                continue
            sgn = 1.0 if (v - loc).dot(n) >= 0 else -1.0
            sd[i] = sgn * dist
            pi[i] = self.owner[fi]
        return sd, pi

    def inside_parity(self, P, candidates=None, margin=0.004):
        """Exact inside test (ray parity against each closed part whose bbox contains the point).
        Returns (inside bool (N,), depth (N,) m, part index)."""
        ins = np.zeros(len(P), bool)
        dep = np.zeros(len(P))
        pid = np.full(len(P), -1)
        for k, pt in enumerate(self.parts):
            m = np.all((P > pt["lo"] - margin) & (P < pt["hi"] + margin), axis=1)
            for i in np.nonzero(m)[0]:
                q = Vector(tuple(map(float, P[i])))
                inside, dist = C.inside_mesh(pt["bvh"], q)
                if inside and dist > dep[i]:
                    ins[i], dep[i], pid[i] = True, dist, k
        return ins, dep, pid


def glove_vs_collider(model, k, S, coll, region_masks):
    """Contact report of mesh k of a HandModel posed with skin matrices S against a Collider:
    per region (name -> vertex bool mask): min signed gap (m, negative = penetration), exact
    parity penetration depth, and collider vertices inside the hand surface (depth via the
    nearest hand face normal)."""
    P = model.skin(k, S)
    sd, _ = coll.signed(P, 0.03)
    ins, dep, pid = coll.inside_parity(P)
    rep = {}
    for nm, msk in region_masks.items():
        if not msk.any():
            continue
        g = sd[msk]
        rep[nm] = {"min_gap_mm": round(float(g.min()) * 1000, 2),
                   "penetration_mm": round(float(dep[msk].max()) * 1000, 2) if ins[msk].any() else 0.0,
                   "verts_inside": int(ins[msk].sum())}
    # collider vertices poking into the hand
    tris = model.meshes[k]["tris"]
    bh = bvh_arrays(P, tris)
    lo, hi = P.min(0) - 0.01, P.max(0) + 0.01
    cm = np.all((coll.co > lo) & (coll.co < hi), axis=1)
    worst = 0.0
    nin = 0
    for q in coll.co[cm]:
        v = Vector(tuple(map(float, q)))
        loc, n, fi, dist = bh.find_nearest(v, 0.006)
        if loc is not None and (v - loc).dot(n) < 0:
            nin += 1
            worst = max(worst, dist)
    rep["_collider_verts_inside_hand"] = {"n": nin, "max_depth_mm": round(worst * 1000, 2)}
    rep["_overall"] = {"min_gap_mm": round(float(sd.min()) * 1000, 2),
                       "max_penetration_mm": round(max(float(dep.max()) if ins.any() else 0.0, worst) * 1000, 2)}
    return rep, P


# =============================================================================
# 6. Grasp fitting
# =============================================================================

def _seg_bones(s, f, i):
    """Bones moved by joint i (1..3) of finger f."""
    return [f"{f}_{j:02d}_{s}" for j in range(i, 4)]


def close_joint(model, k, pose, hand_world, coll, finger, key, lo, hi, gap=0.0006, step=3.0, vmask=None):
    """Increase pose[finger][key] from lo towards hi until the moving part of the finger (vmask)
    first comes within `gap` of the collider; bisection refines it.  Returns (angle, min gap)."""
    def gapat(a):
        pose[finger][key] = a
        S = model.pose(pose, hand_world)
        P = model.skin(k, S, vmask)
        sd, _ = coll.signed(P, 0.03)
        return float(sd.min())
    a0 = lo
    g0 = gapat(a0)
    if g0 <= gap:
        return a0, g0
    sgn = 1.0 if hi >= lo else -1.0
    a = lo
    while (a < hi) if sgn > 0 else (a > hi):
        a1 = min(hi, a + step) if sgn > 0 else max(hi, a - step)
        g1 = gapat(a1)
        if g1 <= gap:
            aa, bb = a, a1
            for _ in range(8):
                mid = 0.5 * (aa + bb)
                if gapat(mid) <= gap:
                    bb = mid
                else:
                    aa = mid
            pose[finger][key] = aa
            return aa, gapat(aa)
        a = a1
    return hi, gapat(hi)


def translate_to_contact(model, k, pose, H, coll, direction, vmask, gap=0.0004, max_dist=0.08, step=0.002):
    """Move the hand (world matrix H) along `direction` until vmask vertices first come within
    `gap` of the collider (or back off if already penetrating).  Returns the new H."""
    dvec = np.asarray(direction, float) / np.linalg.norm(direction)
    S0 = model.pose(pose, None)
    def gapat(t):
        Ht = np.array(H); Ht[:3, 3] = H[:3, 3] + dvec * t
        P = model.skin(k, model.pose(pose, Ht), vmask)
        return float(coll.signed(P, 0.05)[0].min())
    g = gapat(0.0)
    if g < gap:                       # penetrating / too close: back off
        t = 0.0
        while g < gap and t > -max_dist:
            t -= step
            g = gapat(t)
        lo, hi = t, t + step
    else:
        t = 0.0
        while g > gap and t < max_dist:
            t += step
            g = gapat(t)
        lo, hi = t - step, t
    for _ in range(10):
        mid = 0.5 * (lo + hi)
        if gapat(mid) > gap:
            lo = mid
        else:
            hi = mid
    Hn = np.array(H); Hn[:3, 3] = H[:3, 3] + dvec * lo
    return Hn


# =============================================================================
# 7. Weapon import (read-only append) and props
# =============================================================================

def append_weapon(blend, col_name="IV7_Parts", rig_name="SK_IV7", into=None):
    """Append the weapon's LOD0 part collection and rig from `blend` into the current file (the
    source .blend is only read).  Returns (armature, [mesh objects])."""
    with bpy.data.libraries.load(blend, link=False) as (src, dst):
        dst.collections = [c for c in src.collections if c == col_name]
        dst.objects = [o for o in src.objects if o == rig_name]
    colw = dst.collections[0]
    target = into or bpy.context.scene.collection
    target.children.link(colw)
    rig = dst.objects[0]
    colw.objects.link(rig) if rig.name not in colw.objects else None
    return rig, [o for o in colw.objects if o.type == 'MESH']


def eval_world_mesh(ob):
    dg = bpy.context.evaluated_depsgraph_get()
    ev = ob.evaluated_get(dg)
    me = ev.to_mesh()
    co = mesh_co(me)
    M = np.array(ob.matrix_world)
    co = co @ M[:3, :3].T + M[:3, 3]
    tris = mesh_tris(me)
    ev.to_mesh_clear()
    return co, tris


def socket_matrix(rig, bone):
    return np.array(rig.matrix_world @ rig.data.bones[bone].matrix_local)


def apply_to_armature(model, H, pose=None, forearm=True):
    """Pose the Blender armature like HandModel.world(H, pose) (forearm bones follow the hand
    rigidly when `forearm`), for rendering / Blender-side checks."""
    arm = model.arm
    Mw = arm.matrix_world
    if forearm:
        for n in (f"lowerarm_{model.s}", f"lowerarm_twist_01_{model.s}"):
            pb = arm.pose.bones[n]
            pb.rotation_mode = 'QUATERNION'
            pb.matrix = Mw.inverted() @ Matrix((H @ model.Ri[model.hand] @ model.R[n]).tolist())
            bpy.context.view_layer.update()
    pb = arm.pose.bones[model.hand]
    pb.rotation_mode = 'QUATERNION'
    pb.matrix = Mw.inverted() @ Matrix(np.asarray(H).tolist())
    bpy.context.view_layer.update()
    if pose is not None:
        C.pose_hand_anat(arm, model.s, pose, model.rest_angles)


def kabsch(A, B, w=None):
    """Rigid transform (R, t) minimising sum w |R a + t - b|^2."""
    A, B = np.asarray(A, float), np.asarray(B, float)
    w = np.ones(len(A)) if w is None else np.asarray(w, float)
    ca = (A * w[:, None]).sum(0) / w.sum()
    cb = (B * w[:, None]).sum(0) / w.sum()
    Hm = ((A - ca) * w[:, None]).T @ (B - cb)
    U, S, Vt = np.linalg.svd(Hm)
    dd = np.sign(np.linalg.det(Vt.T @ U.T))
    R = Vt.T @ np.diag([1, 1, dd]) @ U.T
    return R, cb - R @ ca


def surface_point(model, k, origin, direction):
    """First hit of a ray on mesh k of the model in its REST pose."""
    m = model.meshes[k]
    b = bvh_arrays(m["co"], m["tris"])
    hit = b.ray_cast(Vector(tuple(map(float, origin))), Vector(tuple(map(float, direction))))
    if hit[0] is None:
        raise RuntimeError("surface_point: no hit")
    return np.array(hit[0])


def hand_anchor(model, k, name):
    """Named surface anchors of the rest glove / hand (world, rest pose):
      web      - crotch of the thumb-index web
      heel     - hypothenar pad (palm heel, ulnar side)
      thenar   - thenar pad (palm heel, radial side)
      palm     - palm centre (palmar surface)
      index_base / middle_base / pinky_base - palmar pad below the MCP of that finger
      back     - back of the hand centre (dorsal surface)"""
    arm, s = model.arm, model.s
    F = bone_rest_frames(arm)
    w, d, r, p = hand_frame(arm, s)
    def pal(a, b):
        return surface_point(model, k, w + d * a + r * b - p * 0.004, p)
    if name == "web":
        mid = 0.5 * (F[f"thumb_02_{s}"]["H"] + F[f"index_01_{s}"]["H"])
        return surface_point(model, k, mid, r)
    if name == "heel":
        return pal(0.035, -0.028)
    if name == "thenar":
        return pal(0.040, 0.018)
    if name == "palm":
        return pal(0.060, -0.004)
    if name.endswith("_base"):
        f = name.split("_")[0]
        m = F[f"{f}_01_{s}"]["H"] - w
        return pal(m @ d - 0.006, m @ r)
    if name == "back":
        return surface_point(model, k, w + d * 0.06 + p * 0.004, -p)
    raise ValueError(name)


def finger_masks(model, k, s):
    """Moving-vertex masks per finger joint: (finger, joint 1..3) -> bool mask (weight > 0.3 on
    the bones distal of the joint)."""
    out = {}
    for f in FINGERS:
        for i in (1, 2, 3):
            out[(f, i)] = model.verts_of(k, _seg_bones(s, f, i), 0.3)
    return out


def refine_placement(model, k, pose, H, coll, anchors, sel, palm_sel=None, w_anchor=3e3, w_rot=2.0,
                     palm_gap=0.0006, n_palm=50, rot_centre=None, maxiter=3000, max_rot=0.35, max_move=0.015):
    """Small 6-DOF refinement of a hand world matrix H: no penetration of the `sel` vertices
    (signed gap >= 0.3 mm), anchors [(rest point, world target), ...] as close as possible, and
    the `n_palm` nearest palm vertices (palm_sel) at palm_gap.  Returns (H, report)."""
    from scipy.optimize import minimize
    from scipy.spatial.transform import Rotation as Rot
    idx = np.nonzero(sel)[0]
    pidx = np.nonzero(palm_sel[idx])[0] if palm_sel is not None else None
    Hr = model.R[model.hand]
    A = np.array([a for a, _ in anchors])
    T = np.array([t for _, t in anchors])
    c0 = np.asarray(rot_centre if rot_centre is not None else T.mean(0))
    def Hx(x):
        R = Rot.from_rotvec(x[:3]).as_matrix()
        Hn = np.array(H)
        Hn[:3, :3] = R @ H[:3, :3]
        Hn[:3, 3] = R @ (H[:3, 3] - c0) + c0 + x[3:6]
        return Hn
    def anchors_world(Hn):
        Rt = Hn[:3, :3] @ np.linalg.inv(Hr[:3, :3])
        return (A - Hr[:3, 3]) @ Rt.T + Hn[:3, 3]
    def cost(x, rep=False):
        Hn = Hx(x)
        P = model.skin(k, model.pose(pose, Hn), sel)
        sd, _ = coll.signed(P, 0.04)
        pen = np.sum(np.minimum(sd - 0.0003, 0) ** 2) * 1e7
        an = np.sum((anchors_world(Hn) - T) ** 2) * w_anchor
        pc = 0.0
        if pidx is not None and len(pidx):
            ps = np.sort(sd[pidx])[:n_palm]
            pc = np.sum((ps - palm_gap) ** 2) * 1e4
        c = pen + an + pc + w_rot * np.sum(x[:3] ** 2)
        if rep:
            return {"cost": round(float(c), 4), "min_gap_mm": round(float(sd.min()) * 1000, 2),
                    "anchor_err_mm": [round(float(e) * 1000, 1) for e in np.linalg.norm(anchors_world(Hn) - T, axis=1)],
                    "palm_gap_mm": [round(float(v) * 1000, 2) for v in (np.sort(sd[pidx])[[0, min(n_palm, len(pidx)) - 1]] if pidx is not None and len(pidx) else [])]}
        return c
    b = [(-max_rot, max_rot)] * 3 + [(-max_move, max_move)] * 3
    res = powell_min(cost, np.zeros(6), b, {"maxiter": maxiter, "xtol": 1e-4, "ftol": 1e-8})
    Hn = Hx(res.x)
    rep = cost(res.x, True)
    rep["rotation_deg"] = round(float(np.degrees(np.linalg.norm(res.x[:3]))), 2)
    rep["translation_mm"] = [round(float(v) * 1000, 1) for v in res.x[3:]]
    rep["evaluations"] = int(res.nfev)
    return Hn, rep


def close_fingers(model, k, pose, H, coll, fingers, limits=None, gap=0.0006, masks=None):
    """Proximal-to-distal closing of fingers to contact: for each finger MCP, then PIP, then DIP
    flex from their current value until the distal part reaches `gap`.  Thumb keys: cmc_flex,
    mcp, ip.  Returns a report of the reached angles and gaps."""
    s = model.s
    masks = masks or finger_masks(model, k, s)
    lim = {"mcp": 95.0, "pip": 110.0, "dip": 80.0, "cmc_flex": 70.0, "ip": 80.0}
    lim.update(limits or {})
    rep = {}
    for f in fingers:
        keys = ("mcp", "pip", "dip") if f != "thumb" else ("cmc_flex", "mcp", "ip")
        for i, key in enumerate(keys, 1):
            lo = pose[f].get(key, 0.0)
            hi = lim[key] if f != "thumb" or key != "mcp" else 60.0
            a, g = close_joint(model, k, pose, H, coll, f, key, lo, hi, gap=gap, vmask=masks[(f, i)])
            rep[f"{f}.{key}"] = {"deg": round(a, 2), "gap_mm": round(g * 1000, 2), "at_limit": bool(a >= hi - 1e-6)}
    return rep


def fit_digit(model, k, pose, H, coll, finger, keys, bounds, moving, contact=None, contact_gap=0.0008,
              direction=None, point=None, w_dir=4.0, w_point=2e4, w_contact=3e4, contact_parts=None,
              maxiter=1500, x0=None, self_coll=None):
    """Optimise the joint angles `keys` of one digit (Powell, bounded) for a grip:
      moving   : vertex mask of the digit (no penetration: signed gap >= 0.3 mm)
      contact  : vertex mask whose minimum gap should equal contact_gap (to `contact_parts` if given)
      direction: (world unit vector, bone for the start, bone for the end [head or tail]) the digit
                 should point along
      point    : (rest-space vertex index, world target) a pad vertex that should sit at a point
    Updates pose in place; returns a report."""
    from scipy.optimize import minimize
    names = [p["name"] for p in coll.parts]
    mv = np.nonzero(moving)[0]
    cv = np.nonzero(contact[mv])[0] if contact is not None else None
    allow = None if contact_parts is None else np.array([n in contact_parts for n in names])
    def apply(x):
        for kk, v in zip(keys, x):
            pose[finger][kk] = float(v)
    def terms(x):
        apply(x)
        S = model.pose(pose, H)
        P = model.skin(k, S, moving)
        sd, pi = coll.signed(P, 0.04)
        t = {"pen": float(np.sum(np.minimum(sd - 0.0003, 0) ** 2) * 1e7)}
        if self_coll is not None:
            # the hand's own (open) surfaces: only faces within 5 mm count, so a far face whose
            # back happens to be nearest cannot fake a deep penetration
            sds, _ = self_coll.signed(P, 0.005)
            t["pen_self"] = float(np.sum(np.minimum(sds - 0.0003, 0) ** 2) * 1e7)
            t["_min_sd_self"] = float(sds.min())
        if cv is not None and len(cv):
            g = sd[cv]
            if allow is not None:
                g = np.where((pi[cv] >= 0) & allow[np.maximum(pi[cv], 0)], g, 0.04)
            t["contact"] = float((g.min() - contact_gap) ** 2 * w_contact)
            t["_gap"] = float(g.min())
        if direction is not None:
            dv, b0, b1 = direction
            M = model.world(H, C.hand_pose_quats(pose, model.s, model.rest_angles))
            h0 = M[b0][:3, 3]
            e = M[b1] @ np.array([0, model.arm.data.bones[b1].length, 0, 1.0])
            u = e[:3] - h0
            u /= np.linalg.norm(u)
            t["dir"] = float((1 - u @ np.asarray(dv)) * w_dir)
            t["_dir_deg"] = float(np.degrees(np.arccos(np.clip(u @ np.asarray(dv), -1, 1))))
        if point is not None:
            vi, tgt = point
            q = model.skin(k, S, None)[vi]
            t["point"] = float(np.sum((q - tgt) ** 2) * w_point)
            t["_point_mm"] = float(np.linalg.norm(q - tgt) * 1000)
        if finger != "thumb":
            fp = pose[finger]
            t["coupling"] = coupling_penalty(fp.get("pip", 0.0), fp.get("dip", 0.0), fp.get("mcp", 0.0), w=1e-3)
        t["_min_sd"] = float(sd.min())
        return t
    def cost(x):
        t = terms(x)
        return sum(v for kk, v in t.items() if not kk.startswith("_"))
    x0 = np.array(x0 if x0 is not None else [pose[finger].get(kk, 0.0) for kk in keys], float)
    x0 = np.clip(x0, [b[0] for b in bounds], [b[1] for b in bounds])
    res = powell_min(cost, x0, bounds, {"maxiter": maxiter, "xtol": 0.05, "ftol": 1e-9})
    t = terms(res.x)
    apply(res.x)
    return {"angles": {kk: round(float(v), 2) for kk, v in zip(keys, res.x)},
            "terms": {kk: round(v, 5) for kk, v in t.items()}, "evaluations": int(res.nfev)}


# =============================================================================
# 8. Arm IK (analytic two-bone, for full-body grip renders) and skin-vs-glove metrics
# =============================================================================

def arm_ik(arm, s, H_hand, pole, clavicle_deg=0.0, clavicle_axis=(0, 1, 0)):
    """Pose clavicle (optional elevation about a world axis), upper arm and forearm of side s so
    the wrist reaches the translation of H_hand (4x4 world matrix of the hand bone), elbow
    towards `pole` (world direction); then the hand gets H_hand's rotation.  The elbow keeps
    its rest hinge axis relation.  Twist bones are driven afterwards (ivchar rule).
    Returns {'reach_error_m', 'elbow_deg', 'wrist_rel_deg'}."""
    Mw = arm.matrix_world
    if clavicle_deg:
        C.rotate_bone_world(arm, f"clavicle_{s}", Vector(clavicle_axis), clavicle_deg * (1 if s == "l" else -1))
    ua, la, ha = f"upperarm_{s}", f"lowerarm_{s}", f"hand_{s}"
    Bu, Bl = arm.data.bones[ua], arm.data.bones[la]
    L1, L2 = Bu.length, Bl.length
    S0 = np.array(C.bone_world(arm, ua))
    T = np.asarray(H_hand)[:3, 3]
    dvec = T - S0
    dist = np.linalg.norm(dvec)
    dd = min(dist, (L1 + L2) * 0.999)
    u = dvec / dist
    pl = np.asarray(pole, float)
    pl = pl - u * (pl @ u)
    pl /= np.linalg.norm(pl)
    cosA = (L1 ** 2 + dd ** 2 - L2 ** 2) / (2 * L1 * dd)
    A = math.acos(max(-1, min(1, cosA)))
    E = S0 + L1 * (math.cos(A) * u + math.sin(A) * pl)
    # rest frames
    Ru = np.array((Mw @ Bu.matrix_local).to_3x3())
    Rl = np.array((Mw @ Bl.matrix_local).to_3x3())
    yu0, yl0 = Ru[:, 1], Rl[:, 1]
    hinge0 = np.cross(yu0, yl0); hinge0 /= np.linalg.norm(hinge0)
    yu = (E - S0) / L1
    yl = (T - E) / np.linalg.norm(T - E)
    hinge = np.cross(yu, yl); hinge /= np.linalg.norm(hinge)
    Rf = frame_rotation((yu0, hinge0, np.cross(yu0, hinge0)), (yu, hinge, np.cross(yu, hinge)))
    # upper arm: current pose parent (clavicle) is honoured by setting the world matrix
    pb = arm.pose.bones[ua]
    Mu = np.eye(4); Mu[:3, :3] = Rf @ Ru; Mu[:3, 3] = S0
    pb.matrix = Mw.inverted() @ Matrix(Mu.tolist())
    bpy.context.view_layer.update()
    # forearm: rigid with the upper arm, then about the hinge to the target
    Rl1 = Rf @ Rl
    y1 = Rl1[:, 1]
    ang = math.atan2(np.cross(y1, yl) @ hinge, y1 @ yl)
    from scipy.spatial.transform import Rotation as Rot
    Rl2 = Rot.from_rotvec(hinge * ang).as_matrix() @ Rl1
    Ml = np.eye(4); Ml[:3, :3] = Rl2; Ml[:3, 3] = E
    arm.pose.bones[la].matrix = Mw.inverted() @ Matrix(Ml.tolist())
    bpy.context.view_layer.update()
    Hn = np.array(H_hand, float)
    tail = np.array(C.bone_world(arm, la, "tail"))
    Hn[:3, 3] = tail
    arm.pose.bones[ha].matrix = Mw.inverted() @ Matrix(Hn.tolist())
    bpy.context.view_layer.update()
    C.drive_twist_bones(arm, sides=(s,))
    rel = C.relative_rotation(arm, la, ha)
    return {"reach_error_m": round(float(np.linalg.norm(tail - T)), 5),
            "elbow_deg": round(C.angle_between(Vector(yu), Vector(yl)), 2),
            "wrist_rel_deg": round(math.degrees(2 * math.acos(min(1.0, abs(rel.w)))), 2)}


def closest_on_triangles(p, A, B, Cc):
    """Closest points on triangles (A, B, Cc: (n, 3)) to points p (n, 3) (Ericson, vectorised)."""
    ab, ac, ap = B - A, Cc - A, p - A
    d1, d2 = (ab * ap).sum(1), (ac * ap).sum(1)
    bp = p - B
    d3, d4 = (ab * bp).sum(1), (ac * bp).sum(1)
    cp = p - Cc
    d5, d6 = (ab * cp).sum(1), (ac * cp).sum(1)
    va = d3 * d6 - d5 * d4
    vb = d5 * d2 - d1 * d6
    vc = d1 * d4 - d3 * d2
    den = np.where(np.abs(va + vb + vc) < 1e-30, 1e-30, va + vb + vc)
    v = vb / den
    w = vc / den
    out = A + ab * v[:, None] + ac * w[:, None]
    # edge / vertex regions
    m = (d1 <= 0) & (d2 <= 0)
    out[m] = A[m]
    m2 = (d3 >= 0) & (d4 <= d3)
    out[m2] = B[m2]
    m3 = (d6 >= 0) & (d5 <= d6)
    out[m3] = Cc[m3]
    mab = (vc <= 0) & (d1 >= 0) & (d3 <= 0) & ~m & ~m2 & ~m3
    t_ = d1 / np.where(np.abs(d1 - d3) < 1e-30, 1e-30, d1 - d3)
    out[mab] = (A + ab * t_[:, None])[mab]
    mac = (vb <= 0) & (d2 >= 0) & (d6 <= 0) & ~m & ~m2 & ~m3 & ~mab
    t_ = d2 / np.where(np.abs(d2 - d6) < 1e-30, 1e-30, d2 - d6)
    out[mac] = (A + ac * t_[:, None])[mac]
    mbc = (va <= 0) & ((d4 - d3) >= 0) & ((d5 - d6) >= 0) & ~m & ~m2 & ~m3 & ~mab & ~mac
    t_ = (d4 - d3) / np.where(np.abs((d4 - d3) + (d5 - d6)) < 1e-30, 1e-30, (d4 - d3) + (d5 - d6))
    out[mbc] = (B + (Cc - B) * t_[:, None])[mbc]
    return out


def skin_vs_glove(skin_co, skin_mask, glove_co, glove_tris, maxd=0.015, skin_rest=None,
                  glove_rest=None, corr_r=0.008, per_vertex=None):
    """Skin vertices (skin_mask) relative to the posed glove surface: signed distance (+ = OUTSIDE
    the glove = poke-through).  Returns stats (mm).
    With skin_rest / glove_rest the test uses each skin vertex's OWN glove patch -- the glove faces
    that lay within corr_r of it in the rest pose (the shell was offset from this skin) -- so a
    neighbouring finger's glove pressing against this finger's glove (glove-glove contact, measured
    separately) cannot be mistaken for skin poking out.  Sign: normal of the nearest own face."""
    idx = np.nonzero(skin_mask)[0]
    gt = np.asarray(glove_tris)
    if skin_rest is None or glove_rest is None:
        bg = bvh_arrays(glove_co, glove_tris)
        sd = np.full(len(idx), np.nan)
        for j, i in enumerate(idx):
            v = Vector(tuple(map(float, skin_co[i])))
            loc, n, fi, dist = bg.find_nearest(v, maxd)
            if loc is not None:
                sd[j] = dist if (v - loc).dot(n) > 0 else -dist
    else:
        br = bvh_arrays(glove_rest, glove_tris)
        vi, fi_ = [], []
        for j, i in enumerate(idx):
            for loc, n, fi, dist in br.find_nearest_range(Vector(tuple(map(float, skin_rest[i]))), corr_r):
                if fi is not None:
                    vi.append(j)
                    fi_.append(fi)
        vi, fi_ = np.array(vi), np.array(fi_)
        P = skin_co[idx][vi]
        A, B, Cc = (glove_co[gt[fi_, k]] for k in range(3))
        Q = closest_on_triangles(P, A, B, Cc)
        dist = np.linalg.norm(P - Q, axis=1)
        fn = np.cross(B - A, Cc - A)
        fn /= np.maximum(np.linalg.norm(fn, axis=1)[:, None], 1e-15)
        sgn = np.sign(((P - Q) * fn).sum(1))
        sd = np.full(len(idx), np.nan)
        best = np.full(len(idx), np.inf)
        order = np.lexsort((dist, vi))          # per skin vertex, nearest own face first
        first = np.ones(len(order), bool)
        first[1:] = vi[order][1:] != vi[order][:-1]
        sel = order[first]
        sd[vi[sel]] = dist[sel] * np.where(sgn[sel] > 0, 1.0, -1.0)
    if per_vertex is not None:
        per_vertex.update({int(i): float(x) for i, x in zip(idx, sd) if not np.isnan(x)})
    ok = ~np.isnan(sd)
    out = sd[ok & (sd > 0)]
    g = -sd[ok & (sd <= 0)]
    g = g if len(g) else np.zeros(1)
    return {"skin_verts_tested": int(skin_mask.sum()), "poke_through_verts": int(len(out)),
            "poke_through_max_mm": round(float(out.max()) * 1000, 2) if len(out) else 0.0,
            "glove_offset_median_mm": round(float(np.median(g)) * 1000, 2),
            "glove_offset_p95_mm": round(float(np.percentile(g, 95)) * 1000, 2),
            "glove_offset_max_mm": round(float(g.max()) * 1000, 2)}


def cap_opening(co, tris, loop):
    """Close a boundary loop with a centre-vertex fan (for inside tests of an open shell)."""
    c = co[loop].mean(0)
    co2 = np.vstack([co, c[None]])
    ci = len(co)
    fan = np.array([[loop[i], loop[(i + 1) % len(loop)], ci] for i in range(len(loop))], np.int64)
    return co2, np.vstack([tris, fan])


CURL_RATIO = {"mcp": 0.85, "pip": 1.0, "dip": 0.65}     # anatomical flexion coupling while curling


def close_finger_coupled(model, k, pose, H, coll, f, gap=0.0006, masks=None, limits=None):
    """Natural curl-then-wrap closing of one finger: (1) curl all three joints together
    (MCP:PIP:DIP = 0.85 : 1 : 0.65, the tendon-coupled cascade) until any segment first reaches
    `gap`; (2) the joints DISTAL of the first touching segment keep closing (proximal to distal)
    until their segments touch too.  Returns a report."""
    s = model.s
    masks = masks or finger_masks(model, k, s)
    lim = {"mcp": 95.0, "pip": 110.0, "dip": 80.0}
    lim.update(limits or {})
    base = {kk: pose[f][kk] for kk in ("mcp", "pip", "dip")}
    segs = {1: model.verts_of(k, [f"{f}_01_{s}"], 0.5), 2: model.verts_of(k, [f"{f}_02_{s}"], 0.5),
            3: model.verts_of(k, [f"{f}_03_{s}"], 0.5)}
    allm = masks[(f, 1)]
    def setc(c):
        for kk in ("mcp", "pip", "dip"):
            pose[f][kk] = min(lim[kk], base[kk] + c * CURL_RATIO[kk])
    def seg_gaps():
        S = model.pose(pose, H)
        P = model.skin(k, S, allm)
        sd, _ = coll.signed(P, 0.03)
        idx = np.nonzero(allm)[0]
        out = {}
        for i, m in segs.items():
            mm = m[idx]
            out[i] = float(sd[mm].min()) if mm.any() else 1.0
        return out
    c, step, cmax = 0.0, 3.0, 130.0
    g = seg_gaps()
    first = None
    if min(g.values()) > gap:
        while c < cmax:
            c1 = c + step
            setc(c1)
            g1 = seg_gaps()
            if min(g1.values()) <= gap:
                lo, hi = c, c1
                for _ in range(8):
                    mid = 0.5 * (lo + hi)
                    setc(mid)
                    if min(seg_gaps().values()) <= gap:
                        hi = mid
                    else:
                        lo = mid
                setc(lo)
                g = seg_gaps()
                break
            c, g = c1, g1
    first = min(g, key=lambda i: g[i])
    rep = {"curl": round(c, 2), "first_contact_segment": int(first)}
    keys = {1: "mcp", 2: "pip", 3: "dip"}
    for j in range(first + 1, 4):
        key = keys[j]
        a, gg = close_joint(model, k, pose, H, coll, f, key, pose[f][key], lim[key], gap=gap, vmask=masks[(f, j)])
        rep[key] = {"deg": round(a, 2), "gap_mm": round(gg * 1000, 2)}
    rep["angles"] = {kk: round(pose[f][kk], 2) for kk in ("mcp", "pip", "dip")}
    rep["segment_gap_mm"] = {str(i): round(v * 1000, 2) for i, v in seg_gaps().items()}
    return rep


def self_collider(model, k, pose, H, exclude_prefix, keep_prefixes, exclude_near=None, near_dist=0.010):
    """Collider from the posed mesh itself: faces whose dominant bone starts with one of
    keep_prefixes and not with exclude_prefix; faces within near_dist (rest) of the vertices in
    exclude_near are dropped (the digit's own attachment)."""
    m = model.meshes[k]
    S = model.pose(pose, H)
    P = model.skin(k, S)
    dom = np.array(m["groups"])[np.argmax(m["W"], 1)]
    td = dom[m["tris"][:, 0]].astype(str)
    keep = np.array([any(t.startswith(p) for p in keep_prefixes) and not t.startswith(exclude_prefix) for t in td])
    if exclude_near is not None:
        bv = bvh_arrays(m["co"][exclude_near], np.zeros((0, 3), np.int64)) if False else None
        near = np.zeros(len(m["co"]), bool)
        pts = m["co"][exclude_near]
        from scipy.spatial import cKDTree
        tree = cKDTree(pts)
        dd, _ = tree.query(m["co"], k=1)
        near = dd < near_dist
        keep &= ~near[m["tris"]].any(1)
    return Collider([("self", P, m["tris"][np.nonzero(keep)[0]])])


DIP_PIP_RANGE = (0.30, 0.90)       # natural DIP / PIP flexion ratio band while grasping


def coupling_penalty(pip, dip, mcp=None, w=1e-4):
    """Soft anatomical coupling: DIP flexion stays within DIP_PIP_RANGE x PIP (the flexor
    profundus flexes both; a DIP flexed beyond its PIP or a stiff-straight DIP on a strongly
    flexed PIP reads as a broken finger) and, when mcp is given, the MCP does not flex more than
    25 deg beyond the PIP (a 'hooked' finger, weighted 4x).  ~1e-2 (= a 1 mm gap in wrap_finger's
    cost) per 10 deg of DIP violation at w = 1e-4."""
    lo, hi = DIP_PIP_RANGE
    over = max(0.0, dip - hi * max(pip, 0.0) - 3.0)
    under = max(0.0, lo * pip - dip - 3.0)
    hook = max(0.0, mcp - pip - 25.0) if mcp is not None else 0.0
    return w * (over * over + under * under + 4.0 * hook * hook)


def wrap_finger(model, k, pose, H, coll, f, gap=0.0008, lim=None, maxiter=400):
    """Distribute a finger's flexion so that the segments rest on the object: Powell over
    (mcp, pip, dip) minimising sum_seg w_seg (max(gap_seg, 0) - gap)^2 (w = 0.25 / 1 / 1 for the
    proximal / middle / distal segment) with a no-penetration penalty and the anatomical coupling
    penalty, starting from the current angles.  lim: per-joint (lo, hi)
    bounds, e.g. capped at the tuned full fist so a finger that misses the object cannot curl
    into the palm.  Returns a report with the per-segment gaps."""
    from scipy.optimize import minimize
    s = model.s
    lim = dict({"mcp": (-5.0, 95.0), "pip": (0.0, 110.0), "dip": (0.0, 80.0)}, **(lim or {}))
    allm = model.verts_of(k, [f"{f}_0{i}_{s}" for i in (1, 2, 3)], 0.3)
    idx = np.nonzero(allm)[0]
    segs = [model.verts_of(k, [f"{f}_0{i}_{s}"], 0.5)[idx] for i in (1, 2, 3)]
    keys = ("mcp", "pip", "dip")
    def ev(x):
        for kk, v in zip(keys, x):
            pose[f][kk] = float(v)
        P = model.skin(k, model.pose(pose, H), allm)
        sd, _ = coll.signed(P, 0.03)
        g = [float(sd[m].min()) if m.any() else 0.03 for m in segs]
        return sd, g
    def cost(x):
        sd, g = ev(x)
        pen = float(np.sum(np.minimum(sd - 0.0002, 0) ** 2)) * 1e7
        # the middle / distal segments must rest on the object; the proximal one only preferably
        # (on a large object it stands off, as in a real grasp)
        return (pen + sum(wg * (max(gi, 0.0) - gap) ** 2 for wg, gi in zip((0.25, 1.0, 1.0), g)) * 1e4
                + coupling_penalty(x[1], x[2], x[0], w=3e-4))
    x0 = [min(max(pose[f][kk], lim[kk][0]), lim[kk][1]) for kk in keys]
    res = powell_min(cost, x0, [lim[kk] for kk in keys], {"maxiter": maxiter, "xtol": 0.1, "ftol": 1e-10})
    sd, g = ev(res.x)
    return {"angles": {kk: round(float(v), 2) for kk, v in zip(keys, res.x)},
            "segment_gap_mm": [round(v * 1000, 2) for v in g], "min_signed_mm": round(float(sd.min()) * 1000, 2)}


def snugness(model, k, pose, H, coll, fingers):
    """Mean segment gap (m, capped at 3 cm) of the listed fingers: 0 = every segment touching."""
    s = model.s
    S = model.pose(pose, H)
    vals = []
    for f in fingers:
        for i in (1, 2, 3):
            m = model.verts_of(k, [f"{f}_0{i}_{s}"], 0.5)
            sd, _ = coll.signed(model.skin(k, S, m), 0.03)
            vals.append(max(float(sd.min()), 0.0))
    return float(np.mean(vals))


def refine_hand_and_digit(model, k, pose, H, coll, finger, keys, bounds, target, vi, sel,
                          max_rot=0.20, max_move=0.015, w_point=3e4, w_reg=0.5, maxiter=3000,
                          soft=None, soft_depth=0.0018):
    """Joint refinement of the hand placement (6 DOF, bounded) and one digit's angles so that
    rest-space vertex vi reaches `target` (e.g. the index pad on the trigger face) without
    penetration of the `sel` vertices (palm, thumb base, the digit).  Returns (H, report)."""
    from scipy.optimize import minimize
    from scipy.spatial.transform import Rotation as Rot
    c0 = np.asarray(target, float)
    idx = np.nonzero(sel)[0]
    vloc = int(np.nonzero(idx == vi)[0][0]) if vi in idx else None
    sel2 = sel.copy()
    sel2[vi] = True
    idx = np.nonzero(sel2)[0]
    vloc = int(np.nonzero(idx == vi)[0][0])
    def unpack(x):
        R = Rot.from_rotvec(x[:3]).as_matrix()
        Hn = np.array(H)
        Hn[:3, :3] = R @ H[:3, :3]
        Hn[:3, 3] = R @ (H[:3, 3] - c0) + c0 + x[3:6]
        for kk, v in zip(keys, x[6:]):
            pose[finger][kk] = float(v)
        return Hn
    thr = np.full(len(idx), 0.0003)
    if soft is not None:
        thr[soft[idx]] = -soft_depth          # palm pads / glove may compress this much on the grip
    def terms(x):
        Hn = unpack(x)
        P = model.skin(k, model.pose(pose, Hn), sel2)
        sd, _ = coll.signed(P, 0.04)
        pen = float(np.sum(np.minimum(sd - thr, 0) ** 2)) * 1e7
        pt = float(np.sum((P[vloc] - c0) ** 2)) * w_point
        reg = float(np.sum(x[:3] ** 2) + np.sum((x[3:6] / 0.01) ** 2) * 0.1) * w_reg
        return pen, pt, reg, float(np.linalg.norm(P[vloc] - c0)), float(sd.min())
    def cost(x):
        a, b, c, _, _ = terms(x)
        return a + b + c
    x0 = np.concatenate([np.zeros(6), [pose[finger].get(kk, 0.0) for kk in keys]])
    b = [(-max_rot, max_rot)] * 3 + [(-max_move, max_move)] * 3 + list(bounds)
    x0 = np.clip(x0, [lo for lo, hi in b], [hi for lo, hi in b])
    res = powell_min(cost, x0, b, {"maxiter": maxiter, "xtol": 1e-3, "ftol": 1e-10})
    Hn = unpack(res.x)
    pen, pt, reg, err, msd = terms(res.x)
    return Hn, {"point_error_mm": round(err * 1000, 2), "min_gap_mm": round(msd * 1000, 2),
                "hand_rotation_deg": round(float(np.degrees(np.linalg.norm(res.x[:3]))), 2),
                "hand_translation_mm": [round(float(v) * 1000, 2) for v in res.x[3:6]],
                "angles": {kk: round(float(v), 2) for kk, v in zip(keys, res.x[6:])}, "evaluations": int(res.nfev)}
