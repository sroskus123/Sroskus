"""Which build stage moves the finger surface away from the finger joint cubes? Dorsal fraction
(dorsal distance / (palmar+dorsal)) of each left finger joint-cube centre, per target stage.
Also: do the targets move the joint-cube vertices at all?"""
import sys, os, numpy as np, json
sys.path.insert(0, "/home/user/Sroskus/IronValley/Art/Source/Blender/lib")
import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree
import ivchar as C
MP = C.MPFB_DIR
obj = C.load_obj(MP + "/3dobjs/base.obj")
V0 = C.mh_to_blender(obj.V)
bf = obj.groups["body"]["f"]
tris = [(f[0], f[k], f[k + 1]) for f in bf for k in range(1, len(f) - 1)]
MACRO = dict(gender=1.0, age=C.years_to_age_value(28.0), muscle=0.70, weight=0.50, height=0.50, proportions=0.50,
             race={"african": 1 / 3, "asian": 1 / 3, "caucasian": 1 / 3})
mt = C.macro_target_weights(**MACRO)
cube_groups = [g for g in obj.groups if g.startswith("joint-l-finger")]
cube_idx = np.unique(np.concatenate([obj.group_vertices(g) for g in cube_groups]))
def depth(V, tag):
    bvh = BVHTree.FromPolygons([Vector(x) for x in V], tris, all_triangles=True)
    cen = lambda g: V[obj.group_vertices(g)].mean(0)
    w = cen("joint-l-hand"); m = cen("joint-l-finger-3-1")
    d = m - w; d /= np.linalg.norm(d)
    r = cen("joint-l-finger-2-1") - cen("joint-l-finger-5-1"); r -= d * (r @ d); r /= np.linalg.norm(r)
    p = np.cross(d, r); p /= np.linalg.norm(p)
    row = {}
    for fi, fn in ((2, "index"), (3, "middle"), (4, "ring"), (5, "pinky")):
        for j in (1, 2, 3):
            q = Vector(cen(f"joint-l-finger-{fi}-{j}"))
            hp = bvh.ray_cast(q, Vector(p)); hd = bvh.ray_cast(q, Vector(-p))
            row[f"{fn}_{j}"] = round(hd[3] / (hp[3] + hd[3]), 2) if (hp[0] and hd[0]) else None
    print(f"{tag:55s}", " ".join(f"{k}:{v}" for k, v in row.items()))
    return row
res = {}
res["raw"] = depth(V0, "raw hm08")
V = V0.copy()
for rel, wgt in mt.items():
    i, dd = C.load_target(os.path.join(MP, "targets", "macrodetails", rel + ".target.gz"))
    moved_cubes = np.isin(i, cube_idx).sum()
    moved_hand_surface = 0
    V1 = V.copy()
    if len(i):
        np.add.at(V1, i, wgt * dd)
    print(f"  target {rel} w={wgt:.3f}: verts {len(i)}, finger-cube verts moved {moved_cubes}/{len(cube_idx)}")
    V = V1
    res[rel] = depth(V, "after " + rel)
for rel, wgt in {"arms/measure-upperarm-length-incr": 0.5, "arms/measure-lowerarm-length-decr": 0.5}.items():
    i, dd = C.load_target(os.path.join(MP, "targets", rel + ".target.gz"))
    print(f"  target {rel}: verts {len(i)}, finger-cube verts moved {np.isin(i, cube_idx).sum()}/{len(cube_idx)}")
    np.add.at(V, i, wgt * dd)
    res[rel] = depth(V, "after " + rel)
json.dump(res, open("/home/user/Sroskus/IronValley/Art/Previews/_review/base/r1/r1_hm08_stages.json", "w"), indent=1)
