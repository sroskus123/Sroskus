"""Finger joint-cube depth in the RAW hm08 base mesh (no targets) vs the built SK_Human_Base:
distance from each joint cube centre to the palmar and dorsal surfaces of the body mesh."""
import sys, numpy as np, json
sys.path.insert(0, "/home/user/Sroskus/IronValley/Art/Source/Blender/lib")
import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree
import ivchar as C   # read-only use of the loader
MP = C.MPFB_DIR
obj = C.load_obj(MP + "/3dobjs/base.obj")
V = C.mh_to_blender(obj.V)
bf = obj.groups["body"]["f"]
tris = []
for f in bf:
    for k in range(1, len(f) - 1):
        tris.append((f[0], f[k], f[k + 1]))
bvh = BVHTree.FromPolygons([Vector(x) for x in V], tris, all_triangles=True)
cen = lambda g: V[obj.group_vertices(g)].mean(0)
w = cen("joint-l-hand"); m = cen("joint-l-finger-3-1")
d = (m - w); d /= np.linalg.norm(d)
r = cen("joint-l-finger-2-1") - cen("joint-l-finger-5-1"); r -= d * (r @ d); r /= np.linalg.norm(r)
p = np.cross(d, r); p /= np.linalg.norm(p)
out = {}
for fi, fn in ((2, "index"), (3, "middle"), (4, "ring"), (5, "pinky")):
    for j in (1, 2, 3):
        q = Vector(cen(f"joint-l-finger-{fi}-{j}"))
        hp = bvh.ray_cast(q, Vector(p)); hd = bvh.ray_cast(q, Vector(-p))
        if hp[0] and hd[0]:
            out[f"{fn}_{j:02d}"] = (round(hp[3] * 10 * 1.041, 2), round(hd[3] * 10 * 1.041, 2), round(hd[3] / (hp[3] + hd[3]), 2))
print("RAW hm08 (cm at 1.80 m scale, palmar, dorsal, dorsal fraction):")
for k, v in out.items():
    print("  ", k, v)
json.dump(out, open("/home/user/Sroskus/IronValley/Art/Previews/_review/base/r1/r1_hm08_joint_depth_raw.json", "w"), indent=1)
