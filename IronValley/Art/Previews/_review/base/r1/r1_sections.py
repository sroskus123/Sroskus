"""R1 review: true planar cross-sections (bmesh bisect) of the re-imported FBX body for breadth /
depth measurements, and the midline head profile (for menton) written as CSV + a profile plot."""
import json
import numpy as np
import bpy, bmesh
from mathutils import Vector

IV = "/home/user/Sroskus/IronValley"
R1 = IV + "/Art/Previews/_review/base/r1"
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.fbx(filepath=IV + "/Art/Export/FBX/SK_Human_Base.fbx")
me = [o for o in bpy.data.objects if o.type == 'MESH'][0]
arm = [o for o in bpy.data.objects if o.type == 'ARMATURE'][0]
H = {b.name: np.array(arm.matrix_world @ b.head_local) for b in arm.data.bones}
base = bmesh.new()
base.from_mesh(me.data)
base.transform(me.matrix_world)


def section(co, no):
    bm = base.copy()
    geom = bm.verts[:] + bm.edges[:] + bm.faces[:]
    r = bmesh.ops.bisect_plane(bm, geom=geom, dist=1e-7, plane_co=co, plane_no=no)
    cut = [e for e in r["geom_cut"] if isinstance(e, bmesh.types.BMEdge)]
    # connected loops
    adj = {}
    for e in cut:
        a, b = e.verts
        adj.setdefault(a.index, []).append(b.index)
        adj.setdefault(b.index, []).append(a.index)
    bm.verts.ensure_lookup_table()
    pts = {i: np.array(bm.verts[i].co[:]) for i in adj}
    seen = set(); loops = []
    for s in adj:
        if s in seen:
            continue
        comp = []; st = [s]; seen.add(s)
        while st:
            j = st.pop(); comp.append(j)
            for k in adj[j]:
                if k not in seen:
                    seen.add(k); st.append(k)
        loops.append(np.array([pts[i] for i in comp]))
    bm.free()
    return loops


out = {}
Z = (0, 0, 1)
# horizontal sections through the torso: keep the loop that contains the midline (x~0)
rows = []
for z in np.arange(0.80, 1.56, 0.01):
    loops = section((0, 0, z), Z)
    torso = [L for L in loops if L[:, 0].min() < 0 < L[:, 0].max()]
    if not torso:
        continue
    L = max(torso, key=len)
    rows.append((round(float(z), 3), round(float(np.ptp(L[:, 0])), 4), round(float(np.ptp(L[:, 1])), 4), len(loops)))
out["torso_sections(z, breadth, depth, n_loops)"] = rows
rows_a = np.array(rows)
# waist: min breadth between 0.98 and 1.15 (torso loop, single loop there)
sel = (rows_a[:, 0] >= 0.98) & (rows_a[:, 0] <= 1.15)
i = np.argmin(rows_a[sel, 1]); out["waist"] = rows_a[sel][i].tolist()
# hip breadth: max breadth of the pelvis loop between crotch and 1.00 (single loop incl. both thighs
# only above the crotch)
sel = (rows_a[:, 0] >= 0.87) & (rows_a[:, 0] <= 1.00)
i = np.argmax(rows_a[sel, 1]); out["hip_max_above_crotch"] = rows_a[sel][i].tolist()
# chest at nipple level ~1.31 and armpit level
for zz in (1.25, 1.30, 1.31, 1.35):
    r = [x for x in rows if abs(x[0] - zz) < 1e-6]
    out[f"chest_z{zz}"] = r[0] if r else None
# head: breadth above the ears (sections from eye level up), length at glabella level
hrows = []
for z in np.arange(1.60, 1.80, 0.005):
    loops = section((0, 0, z), Z)
    hd = [L for L in loops if L[:, 0].min() < 0 < L[:, 0].max()]
    if not hd:
        continue
    L = max(hd, key=len)
    hrows.append((round(float(z), 3), round(float(np.ptp(L[:, 0])), 4), round(float(np.ptp(L[:, 1])), 4), len(loops)))
out["head_sections(z, breadth, length, n_loops)"] = hrows
# midline profile (sagittal section x=0)
loops = section((0, 0, 0), (1, 0, 0))
L = np.concatenate(loops)
prof = L[(L[:, 2] > 1.50)]
np.savetxt(R1 + "/r1_midline_profile_head.csv", prof[:, 1:], delimiter=",", header="y,z", comments="")
out["vertex_z"] = float(L[:, 2].max())
# frontal plane section through hip joints (y = thigh head y) to see hip joint vs pelvis width
yh = float(H["thigh_l"][1])
loops = section((0, yh, 0), (0, 1, 0))
L = np.concatenate(loops)
band = L[(L[:, 2] > H["thigh_l"][2] - 0.01) & (L[:, 2] < H["thigh_l"][2] + 0.01)]
out["frontal_section_at_hip_joint_level: x_extent"] = [round(float(band[:, 0].min()), 4), round(float(band[:, 0].max()), 4)]
out["hip_joint_x"] = [round(float(H["thigh_l"][0]), 4), round(float(H["thigh_r"][0]), 4)]
json.dump(out, open(R1 + "/r1_sections.json", "w"), indent=1)
for k, v in out.items():
    if isinstance(v, list) and len(v) > 12:
        print(k)
        for r in v:
            print("   ", r)
    else:
        print(k, v)

# profile plot
from PIL import Image, ImageDraw
img = Image.new("RGB", (900, 1100), (250, 250, 250))
dr = ImageDraw.Draw(img)
sc = 3500  # px per m
y0, z0 = -0.20, 1.50
def P(y, z):
    return (80 + (y - y0) * sc, 1050 - (z - z0) * sc)
for zc in np.arange(1.50, 1.81, 0.01):
    col = (200, 200, 200) if round(zc * 100) % 5 else (150, 150, 150)
    dr.line([P(y0, zc), P(0.03, zc)], fill=col)
    if round(zc * 100) % 5 == 0:
        dr.text((10, P(0, zc)[1] - 6), f"{zc*100:.0f} cm", fill=(0, 0, 0))
for p in prof:
    x, yy = P(p[1], p[2])
    dr.ellipse([x - 1.5, yy - 1.5, x + 1.5, yy + 1.5], fill=(20, 20, 160))
for zc, lab, col in ((1.5719, "builder menton 157.2", (200, 0, 0)), (1.5901, "r1 heuristic 159.0", (0, 140, 0)), (1.80, "vertex 180.0", (0, 0, 0))):
    dr.line([P(y0, zc), P(0.03, zc)], fill=col, width=2)
    dr.text((P(0.035, zc)[0], P(0, zc)[1] - 6), lab, fill=col)
dr.text((300, 10), "Midline (x=0) section of the head, facing -Y (left)", fill=(0, 0, 0))
img.save(R1 + "/r1_head_profile.png")
