"""R1 review: import FBX or GLB into an empty scene with Blender's stock importer and check
mesh topology, islands, normals orientation, UVs (range, flipped, overlap), skin, skeleton.
usage: python3 r1_reimport.py fbx|glb|blend"""
import sys, json, math
import numpy as np
import bpy, bmesh
from mathutils.bvhtree import BVHTree
from mathutils import Vector

kind = sys.argv[-1]
IV = "/home/user/Sroskus/IronValley"
R1 = IV + "/Art/Previews/_review/base/r1"
bpy.ops.wm.read_factory_settings(use_empty=True)
if kind == "fbx":
    bpy.ops.import_scene.fbx(filepath=IV + "/Art/Export/FBX/SK_Human_Base.fbx")
elif kind == "glb":
    bpy.ops.import_scene.gltf(filepath=IV + "/Art/Export/GLB/Human_Base.glb")
else:
    bpy.ops.wm.open_mainfile(filepath=IV + "/Art/Source/Blender/characters/human_base.blend")
bpy.context.view_layer.update()
out = {"kind": kind, "objects": [(o.name, o.type, o.parent.name if o.parent else None,
                                   [round(x, 4) for x in o.scale]) for o in bpy.data.objects]}
arms = [o for o in bpy.data.objects if o.type == 'ARMATURE']
meshes = sorted([o for o in bpy.data.objects if o.type == "MESH"], key=lambda o: -len(o.data.vertices))
out["n_armatures"] = len(arms)
out["n_meshes"] = len(meshes)
arm = arms[0]
me = meshes[0]
out["armature_bones"] = len(arm.data.bones)
out["bone_parents"] = {b.name: (b.parent.name if b.parent else None) for b in arm.data.bones}
MW = arm.matrix_world
heads = {b.name: (MW @ b.head_local) for b in arm.data.bones}
out["bone_heads_world_m"] = {k: [round(v.x, 5), round(v.y, 5), round(v.z, 5)] for k, v in heads.items()}

# evaluated (deformed at rest) world-space mesh
dg = bpy.context.evaluated_depsgraph_get()
ev = me.evaluated_get(dg)
m_ev = ev.to_mesh()
co = np.array([me.matrix_world @ v.co for v in m_ev.vertices])
out["world_bbox_min"] = co.min(0).round(4).tolist()
out["world_bbox_max"] = co.max(0).round(4).tolist()
out["stature_m"] = round(float(np.ptp(co[:, 2])), 5)
# rest (undeformed) vs evaluated difference -> bind pose consistency
co0 = np.array([me.matrix_world @ v.co for v in me.data.vertices])
out["rest_vs_armature_evaluated_max_diff_m"] = float(np.abs(co - co0).max())
ev.to_mesh_clear()

bm = bmesh.new()
bm.from_mesh(me.data)
bm.transform(me.matrix_world)
# GLB splits verts at seams: weld for topology checks
n_before = len(bm.verts)
if kind == "glb":
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)
out["verts_before_weld"] = n_before
out["verts"] = len(bm.verts)
out["faces"] = len(bm.faces)
out["face_sizes"] = {int(k): int(v) for k, v in zip(*np.unique([len(f.verts) for f in bm.faces], return_counts=True))}
out["boundary_edges"] = sum(1 for e in bm.edges if e.is_boundary)
out["non_manifold_edges"] = sum(1 for e in bm.edges if not e.is_manifold)
out["wire_edges"] = sum(1 for e in bm.edges if e.is_wire)
out["loose_verts"] = sum(1 for v in bm.verts if not v.link_edges)
out["zero_area_faces"] = sum(1 for f in bm.faces if f.calc_area() < 1e-10)
# non-contiguous normals: edges whose two faces traverse it in the same direction
bad_wind = 0
for e in bm.edges:
    if len(e.link_faces) == 2:
        f1, f2 = e.link_faces
        l1 = [l for l in e.link_loops if l.face == f1][0]
        l2 = [l for l in e.link_loops if l.face == f2][0]
        if l1.vert == l2.vert:
            bad_wind += 1
out["inconsistent_winding_edges"] = bad_wind
# doubles (distinct verts at the same position) after weld
kd_co = np.array([v.co[:] for v in bm.verts])
from mathutils.kdtree import KDTree
kd = KDTree(len(kd_co))
for i, c in enumerate(kd_co):
    kd.insert(c, i)
kd.balance()
dups = 0
for i, c in enumerate(kd_co):
    if len(kd.find_range(c, 1e-5)) > 1:
        dups += 1
out["coincident_verts(<0.01mm)"] = dups
# islands (connected components)
bm.verts.ensure_lookup_table()
seen = np.zeros(len(bm.verts), bool)
islands = []
for i in range(len(bm.verts)):
    if seen[i]:
        continue
    stack = [i]; seen[i] = True; n = 0
    while stack:
        j = stack.pop(); n += 1
        for e in bm.verts[j].link_edges:
            k = e.other_vert(bm.verts[j]).index
            if not seen[k]:
                seen[k] = True; stack.append(k)
    islands.append(n)
out["mesh_islands"] = sorted(islands, reverse=True)
# signed volume
bm.faces.ensure_lookup_table()
tri = bm.calc_loop_triangles()
vol = 0.0
for t in tri:
    a, b, c = (l.vert.co for l in t)
    vol += a.dot(b.cross(c)) / 6.0
out["signed_volume_m3"] = round(vol, 5)
# outward check: ray from each face centre along its normal; count hits (odd = normal points inward)
bvh = BVHTree.FromBMesh(bm)
inward = 0
sample = list(bm.faces)[::3]
for f in sample:
    c = f.calc_center_median(); n = f.normal
    o = c + n * 1e-4
    hits = 0
    while True:
        loc, nn, idx, d = bvh.ray_cast(o, n)
        if loc is None:
            break
        hits += 1
        o = loc + n * 1e-5
        if hits > 50:
            break
    if hits % 2 == 1:
        inward += 1
        out.setdefault("inward_face_centres", []).append([round(x, 4) for x in c])
out["faces_sampled_for_inward_normal"] = len(sample)
out["faces_with_inward_normal (odd ray parity)"] = inward

# UVs
uvl = bm.loops.layers.uv.active
out["uv_layers"] = [l.name for l in me.data.uv_layers]
if uvl:
    uvs = np.array([[l[uvl].uv.x, l[uvl].uv.y] for f in bm.faces for l in f.loops])
    out["uv_range"] = [uvs.min(0).round(4).tolist(), uvs.max(0).round(4).tolist()]
    # flipped UV triangles (sign of UV area relative to majority) and zero-area UV faces
    sgn = []
    ratio = []
    for t in tri:
        u = [np.array(l[uvl].uv[:]) for l in t]
        a2 = (u[1][0] - u[0][0]) * (u[2][1] - u[0][1]) - (u[2][0] - u[0][0]) * (u[1][1] - u[0][1])
        sgn.append(a2)
        p = [l.vert.co for l in t]
        A3 = (p[1] - p[0]).cross(p[2] - p[0]).length
        ratio.append(abs(a2) / max(A3, 1e-12))
    sgn = np.array(sgn); ratio = np.array(ratio)
    maj = np.sign(np.median(sgn))
    out["uv_flipped_tris"] = int(np.sum(np.sign(sgn) == -maj))
    out["uv_zero_area_tris"] = int(np.sum(np.abs(sgn) < 1e-12))
    # texel density spread (UV area / 3D area), percentiles
    r = ratio[ratio > 0]
    med = np.median(r)
    out["uv_density_ratio_percentiles(p1,p5,p50,p95,p99)/median"] = (np.percentile(r, [1, 5, 50, 95, 99]) / med).round(3).tolist()
    # overlap via rasterisation at 1024
    N = 1024
    cover = np.zeros((N, N), np.int32)
    for t in tri:
        u = np.array([l[uvl].uv[:] for l in t]) * N
        mn = np.floor(u.min(0)).astype(int); mx = np.ceil(u.max(0)).astype(int)
        mn = np.clip(mn, 0, N - 1); mx = np.clip(mx, 0, N - 1)
        xs, ys = np.meshgrid(np.arange(mn[0], mx[0] + 1) + 0.5, np.arange(mn[1], mx[1] + 1) + 0.5)
        P = np.stack([xs.ravel(), ys.ravel()], 1)
        a, b, c = u
        def edge(p0, p1, P):
            return (p1[0] - p0[0]) * (P[:, 1] - p0[1]) - (p1[1] - p0[1]) * (P[:, 0] - p0[0])
        e0, e1, e2 = edge(a, b, P), edge(b, c, P), edge(c, a, P)
        inside = ((e0 >= 0) & (e1 >= 0) & (e2 >= 0)) | ((e0 <= 0) & (e1 <= 0) & (e2 <= 0))
        Pi = P[inside].astype(int)
        np.add.at(cover, (Pi[:, 1], Pi[:, 0]), 1)
    out["uv_texels_covered"] = int((cover > 0).sum())
    out["uv_texels_overlapping(>1 tri, 1024^2)"] = int((cover > 1).sum())
    out["uv_coverage_fraction"] = round(float((cover > 0).mean()), 4)
    np.save(R1 + f"/r1_uvcover_{kind}.npy", cover)

# skin
names = [b.name for b in arm.data.bones]
vg = {g.index: g.name for g in me.vertex_groups}
cnts = []; sums = []; nonbone = set(); unweighted = 0
for v in me.data.vertices:
    ws = [(vg[g.group], g.weight) for g in v.groups if g.weight > 1e-6]
    for n_, w in ws:
        if n_ not in names:
            nonbone.add(n_)
    cnts.append(len(ws)); sums.append(sum(w for _, w in ws))
    if not ws:
        unweighted += 1
out["skin"] = {"unweighted": unweighted, "max_influences": int(max(cnts)), "sum_min": float(min(sums)), "sum_max": float(max(sums)),
               "hist": {int(k): int(v) for k, v in zip(*np.unique(cnts, return_counts=True))},
               "groups_not_bones": sorted(nonbone), "vertex_groups": len(me.vertex_groups)}
out["armature_modifiers"] = [(m.name, m.object.name if m.object else None) for m in me.modifiers if m.type == 'ARMATURE']
json.dump(out, open(R1 + f"/r1_reimport_{kind}.json", "w"), indent=1)
for k, v in out.items():
    if k in ("bone_parents", "bone_heads_world_m"):
        continue
    print(k, ":", v)
