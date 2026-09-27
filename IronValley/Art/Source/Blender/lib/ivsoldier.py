"""
ivsoldier.py -- Iron Valley soldier helpers (garments derived from SK_Human_Base, rigid gear
binding, atlas texel synthesis, pose intersection checks).  Used by
Art/Source/Blender/characters/soldier.py.  Deterministic: no unseeded randomness.

Conventions (same as ivchar / ivhands): metres, Z up, the character faces -Y, its left side is +X,
rest pose = the A-pose of SK_Human_Base.  All positions handled here are WORLD rest positions
(the armature object has an identity matrix).
"""

import math
import os
import sys

import bpy
import bmesh
import numpy as np
from mathutils import Vector, Matrix
from mathutils.bvhtree import BVHTree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ivchar as C          # noqa: E402
import ivhands as HN        # noqa: E402

IVSOLDIER_VERSION = "1.0.0"


def log(*a):
    print("[ivsoldier]", *a, flush=True)


# =============================================================================
# 1. Mesh arrays
# =============================================================================

def co_of(ob):
    me = ob.data
    a = np.empty(len(me.vertices) * 3)
    me.vertices.foreach_get("co", a)
    return a.reshape(-1, 3)


def tris_of(me):
    me.calc_loop_triangles()
    t = np.empty(len(me.loop_triangles) * 3, np.int64)
    me.loop_triangles.foreach_get("vertices", t)
    return t.reshape(-1, 3)


def vnormals(co, tris):
    return HN.vertex_normals(co, tris)


def bvh(co, tris):
    return BVHTree.FromPolygons([tuple(map(float, p)) for p in co], [tuple(map(int, t)) for t in tris],
                                all_triangles=True)


def eval_co(ob):
    """Evaluated (posed) world coordinates of a mesh object."""
    return C.mesh_arrays(ob, evaluated=True)


def make_mesh(name, V, F, col, smooth=True):
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(map(float, p)) for p in V], [], [list(map(int, f)) for f in F])
    me.polygons.foreach_set("use_smooth", [smooth] * len(me.polygons))
    me.validate(clean_customdata=False)
    me.update()
    ob = bpy.data.objects.new(name, me)
    col.objects.link(ob)
    return ob


def bm_object(bm, name, col, smooth=True):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    me.polygons.foreach_set("use_smooth", [smooth] * len(me.polygons))
    me.update()
    ob = bpy.data.objects.new(name, me)
    col.objects.link(ob)
    return ob


def set_co(ob, co):
    """Set rest positions; shape keys keep their deltas relative to the basis."""
    me = ob.data
    co = np.asarray(co, np.float64)
    if me.shape_keys is not None:
        kb = me.shape_keys.key_blocks
        base = np.empty(len(me.vertices) * 3)
        kb[0].data.foreach_get("co", base)
        base = base.reshape(-1, 3)
        for k in kb[1:]:
            c = np.empty(len(me.vertices) * 3)
            k.data.foreach_get("co", c)
            k.data.foreach_set("co", (co + (c.reshape(-1, 3) - base)).ravel())
        kb[0].data.foreach_set("co", co.ravel())
    me.vertices.foreach_set("co", co.ravel())
    me.update()


def join_objects(objs, name):
    ctx = bpy.context
    for o in ctx.selected_objects:
        o.select_set(False)
    for o in objs:
        o.select_set(True)
    ctx.view_layer.objects.active = objs[0]
    bpy.ops.object.join()
    ob = ctx.view_layer.objects.active
    ob.name = name
    ob.data.name = name
    return ob


def transform_verts(ob, M):
    co = co_of(ob)
    M = np.asarray(M)
    set_co(ob, co @ M[:3, :3].T + M[:3, 3])


def apply_modifier(ob, mod):
    ctx = bpy.context
    for o in ctx.selected_objects:
        o.select_set(False)
    ob.select_set(True)
    ctx.view_layer.objects.active = ob
    bpy.ops.object.modifier_apply(modifier=mod.name)


def neighbours(me):
    n = len(me.vertices)
    ev = np.empty(len(me.edges) * 2, np.int64)
    me.edges.foreach_get("vertices", ev)
    ev = ev.reshape(-1, 2)
    nb = [[] for _ in range(n)]
    for a, b in ev:
        nb[a].append(b)
        nb[b].append(a)
    return nb


def boundary_vertices(me):
    from collections import Counter
    c = Counter()
    for p in me.polygons:
        vs = list(p.vertices)
        for i in range(len(vs)):
            c[tuple(sorted((vs[i], vs[(i + 1) % len(vs)])))] += 1
    b = set()
    for e, k in c.items():
        if k == 1:
            b.update(e)
    m = np.zeros(len(me.vertices), bool)
    m[list(b)] = True
    return m


def boundary_loops(me):
    """All boundary loops (ordered vertex lists)."""
    from collections import defaultdict
    ec = defaultdict(int)
    for p in me.polygons:
        vs = list(p.vertices)
        for i in range(len(vs)):
            ec[tuple(sorted((vs[i], vs[(i + 1) % len(vs)])))] += 1
    adj = defaultdict(list)
    for (a, b), k in ec.items():
        if k == 1:
            adj[a].append(b)
            adj[b].append(a)
    loops, seen = [], set()
    for s in sorted(adj):
        if s in seen:
            continue
        loop, prev, cur = [s], None, s
        seen.add(s)
        while True:
            nx = [x for x in adj[cur] if x != prev and (x not in seen or (x == s and len(loop) > 2))]
            if not nx or nx[0] == s:
                break
            prev, cur = cur, nx[0]
            loop.append(cur)
            seen.add(cur)
        loops.append(loop)
    return loops


# =============================================================================
# 2. Weights
# =============================================================================

def bone_names(arm):
    return [b.name for b in arm.data.bones]


def read_W(ob, names):
    return C.read_weights(ob, names)


def write_W(ob, W, names, arm=None, min_w=1e-5):
    """Replace all vertex groups by W (dense, columns = names), ensure an Armature modifier."""
    ob.vertex_groups.clear()
    W = np.asarray(W)
    for j, n in enumerate(names):
        idx = np.nonzero(W[:, j] > min_w)[0]
        if not len(idx):
            continue
        vg = ob.vertex_groups.new(name=n)
        vals = W[idx, j]
        # group identical weights to cut API calls (rigid parts: one call)
        uniq, inv = np.unique(np.round(vals, 6), return_inverse=True)
        for k, u in enumerate(uniq):
            sel = idx[inv == k]
            vg.add([int(i) for i in sel], float(u), 'REPLACE')
    if arm is not None:
        if not any(m.type == 'ARMATURE' for m in ob.modifiers):
            m = ob.modifiers.new("Armature", 'ARMATURE')
            m.object = arm
            m.use_deform_preserve_volume = False
        ob.parent = arm
        ob.matrix_parent_inverse = Matrix.Identity(4)


def limit_normalize(W, k=4, prune=0.004):
    W = np.array(W, float, copy=True)
    W[W < prune] = 0.0
    if W.shape[1] > k:
        idx = np.argsort(-W, axis=1)[:, k:]
        np.put_along_axis(W, idx, 0.0, axis=1)
    s = W.sum(1, keepdims=True)
    return W / np.maximum(s, 1e-12)


def barycentric(p, a, b, c):
    v0, v1, v2 = b - a, c - a, p - a
    d00 = (v0 * v0).sum(1); d01 = (v0 * v1).sum(1); d11 = (v1 * v1).sum(1)
    d20 = (v2 * v0).sum(1); d21 = (v2 * v1).sum(1)
    den = d00 * d11 - d01 * d01
    den = np.where(np.abs(den) < 1e-20, 1e-20, den)
    v = (d11 * d20 - d01 * d21) / den
    w = (d00 * d21 - d01 * d20) / den
    u = 1 - v - w
    B = np.stack([u, v, w], 1)
    B = np.clip(B, 0, None)
    return B / np.maximum(B.sum(1, keepdims=True), 1e-12)


def nearest_on(bv, P, maxd=1.0):
    """BVH nearest for many points: (loc (n,3), normal (n,3), face (n,), dist (n,)); face -1 = none."""
    n = len(P)
    loc = np.zeros((n, 3)); nor = np.zeros((n, 3)); fi = -np.ones(n, np.int64); d = np.full(n, np.inf)
    for i, p in enumerate(P):
        r = bv.find_nearest(Vector((float(p[0]), float(p[1]), float(p[2]))), maxd)
        if r[0] is not None:
            loc[i] = r[0]; nor[i] = r[1]; fi[i] = r[2]; d[i] = r[3]
    return loc, nor, fi, d


def transfer_weights(src_co, src_tris, src_W, dst_co, k=4, maxd=1.0):
    """Nearest-surface interpolation of src weights onto dst points (Data Transfer 'nearest face
    interpolated' equivalent), limited to k influences and normalised."""
    bv = bvh(src_co, src_tris)
    loc, _, fi, _ = nearest_on(bv, dst_co, maxd)
    fi = np.maximum(fi, 0)
    t = src_tris[fi]
    B = barycentric(loc, src_co[t[:, 0]], src_co[t[:, 1]], src_co[t[:, 2]])
    W = (src_W[t[:, 0]] * B[:, 0:1] + src_W[t[:, 1]] * B[:, 1:2] + src_W[t[:, 2]] * B[:, 2:3])
    return limit_normalize(W, k)


def smooth_weights(W, nb, iters=4, alpha=0.5, mask=None):
    W = np.array(W, float, copy=True)
    for _ in range(iters):
        avg = np.array([W[n].mean(0) if n else W[i] for i, n in enumerate(nb)])
        upd = (1 - alpha) * W + alpha * avg
        if mask is not None:
            W[mask] = upd[mask]
        else:
            W = upd
    return W


def restrict_weights(W, names, allowed):
    """Zero every column not in `allowed` and renormalise (rows with nothing left take the
    first allowed bone)."""
    W = np.array(W, float, copy=True)
    keep = np.array([n in allowed for n in names])
    W[:, ~keep] = 0.0
    s = W.sum(1)
    zero = s < 1e-9
    if zero.any():
        W[zero, names.index(allowed[0])] = 1.0
    return W / np.maximum(W.sum(1, keepdims=True), 1e-12)


def rigid_W(n, names, bone):
    W = np.zeros((n, len(names)))
    W[:, names.index(bone)] = 1.0
    return W


# =============================================================================
# 3. Garments derived from the body
# =============================================================================

def body_fields(arm, body):
    """Per body vertex: rest co, normals, dense weights, dominant bone name."""
    names = bone_names(arm)
    co = co_of(body)
    tris = tris_of(body.data)
    W = read_W(body, names)
    dom = np.array(names)[W.argmax(1)]
    return dict(co=co, tris=tris, N=vnormals(co, tris), W=W, dom=dom, names=names)


def copy_faces(src, keep_face, name, col):
    """Copy of `src` (mesh data incl. vertex groups and shape keys) keeping only the faces with
    keep_face[i]; loose vertices are removed.  Returns (object, original vertex index per new
    vertex)."""
    me = src.data.copy()
    me.name = name
    ob = bpy.data.objects.new(name, me)
    col.objects.link(ob)
    idx_layer = me.attributes.new("iv_src", 'INT', 'POINT')
    idx_layer.data.foreach_set("value", np.arange(len(me.vertices), dtype=np.int32))
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.faces.ensure_lookup_table()
    kill = [f for f in bm.faces if not keep_face[f.index]]
    bmesh.ops.delete(bm, geom=kill, context='FACES')
    loose = [v for v in bm.verts if not v.link_faces]
    bmesh.ops.delete(bm, geom=loose, context='VERTS')
    bm.to_mesh(me)
    bm.free()
    me.update()
    src_idx = np.empty(len(me.vertices), np.int32)
    me.attributes["iv_src"].data.foreach_get("value", src_idx)
    for m in list(ob.modifiers):
        ob.modifiers.remove(m)
    return ob, src_idx.astype(np.int64)


def relax_offset(co, co_body_bvh, nb, fixed, target, iters=12, alpha=0.45, min_clear=None):
    """Laplacian relaxation of a garment surface (bridges concavities like fabric) while keeping
    each vertex at least min_clear (per vertex) outside the body surface.  target: per vertex
    desired clearance (used to push out)."""
    co = np.array(co, float, copy=True)
    min_clear = target * 0.8 if min_clear is None else min_clear
    for it in range(iters):
        avg = np.array([co[n].mean(0) if n else co[i] for i, n in enumerate(nb)])
        new = (1 - alpha) * co + alpha * avg
        new[fixed] = co[fixed]
        co = new
        loc, nor, fi, d = nearest_on(co_body_bvh, co, 0.2)
        s = ((co - loc) * nor).sum(1)
        sd = np.where(s >= 0, d, -d)
        need = sd < min_clear
        co[need] = loc[need] + nor[need] * min_clear[need, None]
    return co


def ring_fold(u, u0, u1, wavelength, phase=0.0):
    """Soft periodic folds along a limb coordinate u (0..1 envelope between u0 and u1)."""
    env = np.clip((u - u0) / max(u1 - u0, 1e-9), 0, 1)
    env = np.sin(env * np.pi)
    return env * np.cos(2 * np.pi * u / wavelength + phase)


def add_lip(ob, loop, inward_dir_fn, edge=0.003, depth=0.015, lining_dir_fn=None):
    """Rolled edge at an open garment boundary: ring 1 = boundary moved `edge` inwards (thickness),
    ring 2 = `depth` further inside along lining_dir_fn (default: -inward direction turned along
    the surface).  New vertices copy the weights and shape-key deltas of their boundary vertex.
    inward_dir_fn(p) -> unit vector pointing from the garment towards the body at boundary point p.
    lining_dir_fn(p) -> unit vector along which the lining continues (into the garment).
    Returns the new vertex indices (ring1 + ring2)."""
    me = ob.data
    co = co_of(ob)
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.verts.ensure_lookup_table()
    dl = bm.verts.layers.deform.verify()
    lip = bm.faces.layers.int.get("iv_lip") or bm.faces.layers.int.new("iv_lip")
    bm.verts.ensure_lookup_table()
    sk = list(bm.verts.layers.shape.values()) if bm.verts.layers.shape else []
    outer = [bm.verts[i] for i in loop]
    r1, r2 = [], []
    for vi, v in zip(loop, outer):
        p = co[vi]
        ind = np.asarray(inward_dir_fn(p), float)
        ld = np.asarray(lining_dir_fn(p), float) if lining_dir_fn else None
        p1 = p + ind * edge
        p2 = p1 + (ld * depth if ld is not None else ind * depth)
        for pp, ring in ((p1, r1), (p2, r2)):
            nv = bm.verts.new(tuple(map(float, pp)))
            for kk, w in v[dl].items():
                nv[dl][kk] = w
            for lay in sk:
                delta = Vector(v[lay]) - v.co
                nv[lay] = Vector(tuple(map(float, pp))) + delta
            ring.append(nv)
    bm.verts.ensure_lookup_table()
    n = len(loop)
    nf = []
    for i in range(n):
        j = (i + 1) % n
        nf.append(bm.faces.new((outer[i], outer[j], r1[j], r1[i])))
        nf.append(bm.faces.new((r1[i], r1[j], r2[j], r2[i])))
    for f in nf:
        f.smooth = True
        f[lip] = 1
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    nv0 = len(co)
    bm.to_mesh(me)
    bm.free()
    me.update()
    return list(range(nv0, nv0 + 2 * n))


def fix_winding_outward(ob, centre_fn=None):
    """Recalculate normals so they point outwards (bmesh consistent + outward heuristic)."""
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    bm.to_mesh(ob.data)
    bm.free()
    ob.data.update()


def flip_faces(ob):
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bmesh.ops.reverse_faces(bm, faces=list(bm.faces))
    bm.to_mesh(ob.data)
    bm.free()
    ob.data.update()


def outward_score(ob, ref_point):
    """Mean of (face centre - ref) . face normal: > 0 means normals point away from ref."""
    me = ob.data
    s = 0.0
    for p in me.polygons:
        s += (Vector(p.center) - Vector(ref_point)).dot(p.normal) * p.area
    return s


def copy_shape_keys_from_body(ob, body, src_idx, scale=1.0):
    """Give `ob` the body's shape keys: each new vertex i takes the delta of body vertex
    src_idx[i] (garments built on body vertices)."""
    bk = body.data.shape_keys
    if bk is None:
        return []
    base = np.empty(len(body.data.vertices) * 3)
    bk.key_blocks[0].data.foreach_get("co", base)
    base = base.reshape(-1, 3)
    me = ob.data
    co = co_of(ob)
    if me.shape_keys is None:
        ob.shape_key_add(name="Basis", from_mix=False)
    names = []
    for k in bk.key_blocks[1:]:
        c = np.empty(len(body.data.vertices) * 3)
        k.data.foreach_get("co", c)
        delta = (c.reshape(-1, 3) - base)[src_idx] * scale
        if np.abs(delta).max() < 1e-7:
            continue
        kk = me.shape_keys.key_blocks.get(k.name) or ob.shape_key_add(name=k.name, from_mix=False)
        kk.data.foreach_set("co", (co + delta).ravel())
        kk.value = 0.0
        names.append(k.name)
    return names


def drive_correctives_on(arm, objs, spec):
    """ivchar.drive_correctives for several meshes sharing the body's corrective shape names."""
    out = {}
    for ob in objs:
        if ob.data.shape_keys is None:
            continue
        ob["iv_correctives"] = spec if isinstance(spec, str) else __import__("json").dumps(spec)
        out[ob.name] = C.drive_correctives(arm, ob)
    return out


def clear_shape_values(objs):
    for ob in objs:
        if ob.data.shape_keys is not None:
            for k in ob.data.shape_keys.key_blocks[1:]:
                k.value = 0.0


# =============================================================================
# 4. Procedural solids for gear (closed meshes)
# =============================================================================

def rounded_box_bm(sx, sy, sz, r, segs=2):
    """Closed rounded box centred at the origin (bmesh), size sx x sy x sz, edge radius r."""
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        v.co = Vector((v.co.x * sx, v.co.y * sy, v.co.z * sz))
    if r > 0 and segs > 0:
        bmesh.ops.bevel(bm, geom=list(bm.edges), offset=min(r, 0.49 * min(sx, sy, sz)), segments=segs,
                        profile=0.5, affect='EDGES', clamp_overlap=True)
    return bm


def superellipse_loop(a, b, n=16, p=4.0):
    t = np.linspace(0, 2 * np.pi, n, endpoint=False)
    c, s = np.cos(t), np.sin(t)
    x = a * np.sign(c) * np.abs(c) ** (2 / p)
    y = b * np.sign(s) * np.abs(s) ** (2 / p)
    return np.stack([x, y], 1)


def loft_closed(sections, cap=True):
    """sections: list of (n,3) rings (same n).  Returns (V, F) with quads and fan-free n-gon caps."""
    V = np.concatenate(sections)
    n = len(sections[0])
    F = []
    for k in range(len(sections) - 1):
        a, b = k * n, (k + 1) * n
        for i in range(n):
            j = (i + 1) % n
            F.append([a + i, a + j, b + j, b + i])
    if cap:
        F.append(list(range(n))[::-1])
        F.append([(len(sections) - 1) * n + i for i in range(n)])
    return V, F


def orient_outward(V, F):
    """Flip all faces if the signed volume is negative (closed meshes)."""
    tris = []
    for f in F:
        for i in range(1, len(f) - 1):
            tris.append((f[0], f[i], f[i + 1]))
    t = np.array(tris)
    vol = np.einsum('ij,ij->i', V[t[:, 0]], np.cross(V[t[:, 1]], V[t[:, 2]])).sum() / 6.0
    if vol < 0:
        F = [list(f)[::-1] for f in F]
    return F


def extrude_profile(pts2d, depth, frame, bevel=0.0):
    """Prism from a closed 2D outline (in frame's x/y) extruded along frame z by depth (centred)."""
    o, ex, ey, ez = frame
    n = len(pts2d)
    rings = []
    zs = [-depth / 2, depth / 2]
    if bevel > 0:
        zs = [-depth / 2, -depth / 2 + bevel, depth / 2 - bevel, depth / 2]
    for k, z in enumerate(zs):
        sh = 0.0
        if bevel > 0 and k in (0, 3):
            sh = bevel
        c = pts2d.mean(0)
        pp = c + (pts2d - c) * (1 - sh / max(np.linalg.norm(pts2d - c, axis=1).mean(), 1e-9))
        rings.append(o + pp[:, 0:1] * ex + pp[:, 1:2] * ey + z * ez)
    V, F = loft_closed(rings)
    return V, orient_outward(V, F)


# =============================================================================
# 5. Intersection metrics
# =============================================================================

def closed_inside(bv, P, dirs=((0.0, 0.0, 1.0), (0.577, -0.577, 0.577), (-0.6, 0.3, -0.74))):
    """Ray-parity inside vote for points P against a closed mesh BVH (majority of 3 rays)."""
    out = np.zeros(len(P), bool)
    for i, p in enumerate(P):
        v = Vector((float(p[0]), float(p[1]), float(p[2])))
        votes = 0
        for d in dirs:
            dv = Vector(d).normalized()
            o = v.copy()
            hits = 0
            for _ in range(64):
                loc, nrm, fi, dist = bv.ray_cast(o, dv, 10.0)
                if loc is None:
                    break
                hits += 1
                o = loc + dv * 1e-6
            votes += hits % 2
        out[i] = votes >= 2
    return out


def penetration(A_co, B_co, B_tris, prefilter=0.03, tol=0.0):
    """Vertices of A inside the CLOSED mesh B: returns dict(count, max_mm, idx).
    Fast prefilter by nearest distance + face-normal sign, confirmed by ray parity."""
    if len(A_co) == 0 or len(B_tris) == 0:
        return {"count": 0, "max_mm": 0.0, "idx": []}
    bmin, bmax = B_co.min(0) - prefilter, B_co.max(0) + prefilter
    cand = np.nonzero(((A_co >= bmin) & (A_co <= bmax)).all(1))[0]
    if not len(cand):
        return {"count": 0, "max_mm": 0.0, "idx": []}
    bv = bvh(B_co, B_tris)
    loc, nor, fi, d = nearest_on(bv, A_co[cand], prefilter + 1.0)
    s = ((A_co[cand] - loc) * nor).sum(1)
    sus = cand[(s < 0) & (d > tol)]
    dd = d[(s < 0) & (d > tol)]
    if not len(sus):
        return {"count": 0, "max_mm": 0.0, "idx": []}
    ins = closed_inside(bv, A_co[sus])
    idx = sus[ins]
    depth = dd[ins]
    return {"count": int(len(idx)), "max_mm": round(float(depth.max()) * 1000, 2) if len(idx) else 0.0,
            "idx": idx.tolist()[:50]}


def signed_bvh(bv, A_co, maxd=0.03):
    loc, nor, fi, d = nearest_on(bv, A_co, maxd)
    s = ((A_co - loc) * nor).sum(1)
    return np.where(fi >= 0, np.where(s >= 0, d, -d), np.nan)


def signed_to_surface(A_co, B_co, B_tris, maxd=0.03):
    """Signed distance of points A to an (open) surface B by the nearest face normal
    (+ = in front of B's faces).  NaN where B is further than maxd."""
    bv = bvh(B_co, B_tris)
    loc, nor, fi, d = nearest_on(bv, A_co, maxd)
    s = ((A_co - loc) * nor).sum(1)
    out = np.where(fi >= 0, np.where(s >= 0, d, -d), np.nan)
    return out


# =============================================================================
# 6. Atlas texel synthesis (several objects sharing one UV atlas)
# =============================================================================

def tri_face_attr(me, name):
    """Per loop-triangle value of an INT face attribute (0 where missing)."""
    me.calc_loop_triangles()
    pi = np.empty(len(me.loop_triangles), np.int64)
    me.loop_triangles.foreach_get("polygon_index", pi)
    if name not in me.attributes:
        return np.zeros(len(pi), np.int32)
    a = np.empty(len(me.polygons), np.int32)
    me.attributes[name].data.foreach_get("value", a)
    return a[pi]


def loop_tris(me):
    me.calc_loop_triangles()
    lt = np.empty(len(me.loop_triangles) * 3, np.int64)
    me.loop_triangles.foreach_get("loops", lt)
    return lt.reshape(-1, 3)


def uv_array(me, name="UVMap"):
    uv = np.empty(len(me.loops) * 2)
    me.uv_layers[name].data.foreach_get("uv", uv)
    return uv.reshape(-1, 2)


def atlas_texels(objs, res, uv="UVMap", attrs=(), face_filter=None):
    """Rasterise the UV triangles of several objects into one res x res atlas (first object wins
    on overlaps) and interpolate per texel: object index, rest world position P, normal N, the
    UV Jacobian (dPdu, dPdv: metres per texel) and the named point attributes.
    face_filter(ob) -> bool mask per loop triangle (optional).  Returns a dict of arrays."""
    out = {k: [] for k in ("oid", "px", "P", "N", "dPdu", "dPdv", "ti")}
    for k in attrs:
        out[k] = []
    taken = np.zeros(res * res, bool)
    for oi, ob in enumerate(objs):
        me = ob.data
        tris = tris_of(me)
        lt = loop_tris(me)
        U = uv_array(me, uv)
        co = co_of(ob)
        M = np.array(ob.matrix_world)
        co = co @ M[:3, :3].T + M[:3, 3]
        nrm = vnormals(co, tris)
        sel = np.ones(len(tris), bool) if face_filter is None else face_filter(ob)
        ti, px, ba = HN.raster_uv_bary(U[lt[sel]], res)
        tsel = np.nonzero(sel)[0]
        ti = tsel[ti]
        keep = ~taken[px]
        ti, px, ba = ti[keep], px[keep], ba[keep]
        taken[px] = True
        tv = tris[ti]

        def I(a):
            a = np.asarray(a)
            if a.ndim == 1:
                return (a[tv[:, 0]] * ba[:, 0] + a[tv[:, 1]] * ba[:, 1] + a[tv[:, 2]] * ba[:, 2]).astype(np.float32)
            return (a[tv[:, 0]] * ba[:, 0:1] + a[tv[:, 1]] * ba[:, 1:2] + a[tv[:, 2]] * ba[:, 2:3]).astype(np.float32)
        P = I(co)
        N = I(nrm)
        N /= np.maximum(np.linalg.norm(N, axis=1)[:, None], 1e-9)
        Uu = U[lt] * res
        Pt = co[tris]
        e1, e2 = Pt[:, 1] - Pt[:, 0], Pt[:, 2] - Pt[:, 0]
        du1, du2 = Uu[:, 1] - Uu[:, 0], Uu[:, 2] - Uu[:, 0]
        det = du1[:, 0] * du2[:, 1] - du2[:, 0] * du1[:, 1]
        det = np.where(np.abs(det) < 1e-12, 1e-12, det)
        dPdu = (e1 * du2[:, 1:2] - e2 * du1[:, 1:2]) / det[:, None]
        dPdv = (e2 * du1[:, 0:1] - e1 * du2[:, 0:1]) / det[:, None]
        out["oid"].append(np.full(len(px), oi, np.int32))
        out["px"].append(px)
        out["P"].append(P)
        out["N"].append(N)
        out["dPdu"].append(dPdu[ti].astype(np.float32))
        out["dPdv"].append(dPdv[ti].astype(np.float32))
        out["ti"].append(ti)
        for k in attrs:
            if k in me.attributes:
                a = np.empty(len(me.vertices), np.float32)
                me.attributes[k].data.foreach_get("value", a)
            else:
                a = np.zeros(len(me.vertices), np.float32)
            out[k].append(I(a))
    td = {k: np.concatenate(v) if v else np.zeros(0) for k, v in out.items()}
    td["res"] = res
    td["names"] = [o.name for o in objs]
    return td


def texels_write(values, td, path, mode='RGB', fill=(0.5, 0.5, 0.5), srgb=False, dilate_px=12, size=None):
    """Scatter per-texel values, dilate the gutters, optionally convert to sRGB, optionally
    downsample (box filter) to `size`, save PNG (Blender row order handled by ivlib.save_png)."""
    import ivlib
    res = td["res"]
    img = np.zeros((res, res, 4), np.float32)
    img[..., :3] = fill
    flat = img.reshape(-1, 4)
    v = np.asarray(values, np.float32)
    if v.ndim == 1:
        v = np.repeat(v[:, None], 3, 1)
    flat[td["px"], :3] = v[:, :3]
    flat[td["px"], 3] = 1.0
    img = ivlib.dilate(img, dilate_px, fill=fill)
    if size and size != res:
        f = res // size
        img = img.reshape(size, f, size, f, 4).mean((1, 3))
    if srgb:
        img[..., :3] = ivlib.linear_to_srgb(img[..., :3])
    return ivlib.save_png(img, path, mode=mode, dither_seed=11 if mode == 'RGB' else None)


def bake_ao_multi(objs, res, distance, samples=32, name="IVS_AO"):
    """Cycles AO bake of several objects into one shared atlas image (all other render-visible
    meshes occlude).  Returns HxWx4 (Blender row order), alpha = coverage."""
    import ivlib
    sc = bpy.context.scene
    im = ivlib._float_image(name, res, (1.0, 1.0, 1.0))
    mat = bpy.data.materials.new(name + "_Mat")
    mat.use_nodes = True
    tn = mat.node_tree.nodes.new('ShaderNodeTexImage')
    tn.image = im
    mat.node_tree.nodes.active = tn
    olds = {}
    for ob in objs:
        olds[ob.name] = list(ob.data.materials)
        ob.data.materials.clear()
        ob.data.materials.append(mat)
    sc.render.engine = 'CYCLES'
    sc.cycles.samples = samples
    sc.cycles.device = 'CPU'
    sc.render.bake.margin = 0
    sc.render.bake.use_selected_to_active = False
    sc.render.bake.target = 'IMAGE_TEXTURES'
    if sc.world is None:
        sc.world = bpy.data.worlds.new("IVS_World")
    sc.world.light_settings.distance = distance
    ivlib.select(objs, objs[0])
    bpy.ops.object.bake(type='AO', margin=0, use_clear=False)
    arr = ivlib.image_to_array(im)
    for ob in objs:
        ob.data.materials.clear()
        for m in olds[ob.name]:
            ob.data.materials.append(m)
    bpy.data.materials.remove(mat)
    return arr


def vertex_convexity(ob):
    """Per-vertex convexity (m^-1 scaled): N . (P - mean(neighbours)) / mean edge length^2 * edge,
    > 0 on convex edges / corners (binding tape, edge wear), < 0 in creases."""
    co = co_of(ob)
    nb = neighbours(ob.data)
    N = vnormals(co, tris_of(ob.data))
    out = np.zeros(len(co), np.float32)
    for i, n in enumerate(nb):
        if not n:
            continue
        d = co[i] - co[n].mean(0)
        L = np.linalg.norm(co[n] - co[i], axis=1).mean()
        out[i] = float(d @ N[i]) / max(L, 1e-6)
    return out
