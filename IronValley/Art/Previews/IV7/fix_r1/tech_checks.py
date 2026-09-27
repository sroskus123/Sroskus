"""IV-7 fix round 1: technical spot checks on the saved .blend and the exports.

    python3 tech_checks.py <iv7_carbine.blend> <project root> <out.json>

TECH-12 UV stretch per part (share of 3D area whose UV Jacobian has singular-value ratio > 1.5),
TECH-11 data hygiene (orphan / procedural data left in the .blend, deform weights on the static
magazine), TECH-8 FBX texture references (normal map and absolute paths, raw byte scan),
TECH-5 razor edges (convex / concave split, > 70 deg), glass: GLB material extensions.
"""
import sys, os, json, math, struct
import numpy as np
import bpy, bmesh

blend, root, out = sys.argv[1:4]
bpy.ops.wm.open_mainfile(filepath=blend)
rep = {}
# ---- TECH-12 stretch
st = {}
for o in bpy.data.collections["IV7_Parts"].objects:
    if o.type != 'MESH' or not o.data.uv_layers:
        continue
    me = o.data; me.calc_loop_triangles()
    uv = me.uv_layers.active.data
    tot = 0.0; bad = 0.0
    for t in me.loop_triangles:
        p = [me.vertices[v].co for v in t.vertices]
        q = [uv[l].uv for l in t.loops]
        e1 = p[1] - p[0]; e2 = p[2] - p[0]
        a3 = e1.cross(e2).length * 0.5
        if a3 < 1e-12:
            continue
        ax = e1.normalized(); ay = e1.cross(e2).cross(e1).normalized()
        P = np.array([[e1.dot(ax), e2.dot(ax)], [e1.dot(ay), e2.dot(ay)]])
        U = np.array([[q[1].x - q[0].x, q[2].x - q[0].x], [q[1].y - q[0].y, q[2].y - q[0].y]])
        try:
            J = U @ np.linalg.inv(P)
        except np.linalg.LinAlgError:
            continue
        s = np.linalg.svd(J, compute_uv=False)
        tot += a3
        if s[1] <= 1e-12 or s[0] / s[1] > 1.5:
            bad += a3
    st[o.name] = round(bad / tot, 4) if tot else None
rep["uv_stretch_share_ratio_gt_1.5"] = st
# ---- TECH-11 hygiene
rep["blend_data"] = {
    "materials": sorted(m.name for m in bpy.data.materials),
    "node_groups": sorted(g.name for g in bpy.data.node_groups),
    "images": sorted(f"{i.name} ({i.source})" for i in bpy.data.images),
    "orphan_materials": sorted(m.name for m in bpy.data.materials if m.users == 0),
    "orphan_meshes": sorted(m.name for m in bpy.data.meshes if m.users == 0),
    "generated_images": sorted(i.name for i in bpy.data.images if i.source == 'GENERATED'),
}
sm = bpy.data.objects.get("SM_IV7_Magazine")
if sm:
    rep["SM_IV7_Magazine"] = {"vertex_groups": len(sm.vertex_groups),
                              "verts_with_deform_weights": sum(1 for v in sm.data.vertices if len(v.groups)),
                              "has_custom_normals": sm.data.has_custom_normals}
# ---- TECH-5 razor edges
rz = {}
for n in ("UpperReceiver", "LowerReceiver", "Handguard", "Optic", "MuzzleDevice", "RearSightBase", "FrontSightBase",
          "BoltCarrier", "DustCover", "ChargingHandle", "RearSightLeaf", "FrontSightLeaf"):
    o = bpy.data.objects[n]
    bm = bmesh.new(); bm.from_mesh(o.data)
    cvx = ccv = 0.0
    for e in bm.edges:
        if len(e.link_faces) != 2:
            continue
        f1, f2 = e.link_faces
        if f1.calc_area() < 1e-12 or f2.calc_area() < 1e-12:
            continue
        if f1.normal.angle(f2.normal, 0.0) > math.radians(70):
            if (f2.calc_center_median() - f1.calc_center_median()).dot(f1.normal) < 0:
                cvx += e.calc_length()
            else:
                ccv += e.calc_length()
    bm.free()
    rz[n] = {"convex_cm": round(cvx * 100, 1), "concave_cm": round(ccv * 100, 1)}
rep["razor_edges_gt_70deg"] = rz
# ---- TECH-8 FBX references (raw scan)
fbx = {}
for f in ("SK_IV7_Carbine.fbx", "SK_IV7_Carbine_LOD1.fbx", "SK_IV7_Carbine_LOD2.fbx", "SM_IV7_Magazine.fbx"):
    p = os.path.join(root, "Art", "Export", "FBX", f)
    if not os.path.exists(p):
        continue
    b = open(p, "rb").read()
    fbx[f] = {"mentions_Normal_DX": b.count(b"_Normal_DX.png"), "mentions_OpenGL_Normal": b.count(b"_Normal.png"),
              "absolute_home_paths": b.count(b"/home/"), "bytes": len(b)}
rep["fbx_texture_refs"] = fbx
# ---- glass in the GLB
p = os.path.join(root, "Art", "Export", "GLB", "IV7_Carbine.glb")
if os.path.exists(p):
    b = open(p, "rb").read()
    L = struct.unpack_from("<I", b, 12)[0]
    js = json.loads(b[20:20 + L])
    mats = {m["name"]: {k: m.get(k) for k in ("alphaMode", "doubleSided")} | {"extensions": sorted((m.get("extensions") or {}).keys())}
            for m in js.get("materials", [])}
    rep["glb"] = {"extensionsUsed": js.get("extensionsUsed", []), "materials": mats,
                  "nodes_named_Optic*": sorted(n["name"] for n in js.get("nodes", []) if n.get("name", "").startswith("Optic")),
                  "sockets_and_sight_bones": sorted(n["name"] for n in js.get("nodes", []) if n.get("name", "").startswith(("socket_", "rear_sight", "front_sight")))}
json.dump(rep, open(out, "w"), indent=1)
print(json.dumps({k: v for k, v in rep.items() if k != "blend_data"}, indent=1)[:6000])
print("blend orphans:", rep["blend_data"]["orphan_materials"], rep["blend_data"]["orphan_meshes"], rep["blend_data"]["generated_images"])
print("node groups:", rep["blend_data"]["node_groups"])
