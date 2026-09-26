"""R1 review: hand curl tests on the re-imported FBX with own hinge axes (d x palmar), counting
finger faces that cross the DORSAL (back-of-hand) surface, palm thickness, and renders.
curls (MCP, PIP, DIP) for index..pinky; thumb left neutral except where noted."""
import sys, json, math
import numpy as np
import bpy
from mathutils import Vector, Matrix
from mathutils.bvhtree import BVHTree

IV = "/home/user/Sroskus/IronValley"
R1 = IV + "/Art/Previews/_review/base/r1"
NORENDER = "--norender" in sys.argv
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.fbx(filepath=IV + "/Art/Export/FBX/SK_Human_Base.fbx")
arm = [o for o in bpy.data.objects if o.type == 'ARMATURE'][0]
me = [o for o in bpy.data.objects if o.type == 'MESH'][0]
MW = arm.matrix_world


def upd():
    bpy.context.view_layer.update()


def reset():
    for pb in arm.pose.bones:
        pb.rotation_mode = 'QUATERNION'; pb.rotation_quaternion = (1, 0, 0, 0); pb.location = (0, 0, 0)
    upd()


def head(n):
    return (MW @ arm.pose.bones[n].matrix).to_translation()


def rest_head(n):
    return MW @ arm.data.bones[n].head_local


def rot(n, axis, deg):
    upd()
    pb = arm.pose.bones[n]
    Mw = MW @ pb.matrix
    h = Mw.to_translation()
    R = Matrix.Rotation(math.radians(deg), 4, Vector(axis).normalized())
    pb.matrix = MW.inverted() @ (Matrix.Translation(h) @ R @ Matrix.Translation(-h) @ Mw)
    upd()


def delta(n):
    upd()
    Mp = (MW @ arm.pose.bones[n].matrix).to_3x3().normalized()
    Mr = (MW @ arm.data.bones[n].matrix_local).to_3x3().normalized()
    return Mp @ Mr.inverted()


FING = ("index", "middle", "ring", "pinky")


def frame(s):
    w = rest_head(f"hand_{s}"); m = rest_head(f"middle_01_{s}")
    d = (m - w).normalized()
    r = rest_head(f"index_01_{s}") - rest_head(f"pinky_01_{s}")
    r = (r - d * r.dot(d)).normalized()
    p = d.cross(r) if s == "l" else r.cross(d)
    return w, d, r, p.normalized()


# rest segment directions: each finger bone head -> next head (tip: bone tail from the FBX import
# is unreliable, use direction of the previous segment for _03)
def seg_dir(f, i, s):
    if i < 3:
        return (rest_head(f"{f}_{i + 1:02d}_{s}") - rest_head(f"{f}_{i:02d}_{s}")).normalized()
    return seg_dir(f, 2, s)


def curl(s, mcp, pip, dip):
    w, d, r, p = frame(s)
    for f in FING:
        for i, a in ((1, mcp), (2, pip), (3, dip)):
            dd = seg_dir(f, i, s)
            pp = (p - dd * p.dot(dd)).normalized()
            ax_rest = dd.cross(pp)
            n = f"{f}_{i:02d}_{s}"
            par = arm.pose.bones[n].parent.name
            rot(n, delta(par) @ ax_rest, a)


names = [g.name for g in me.vertex_groups]
Wd = np.zeros((len(me.data.vertices), len(names)))
for v in me.data.vertices:
    for g in v.groups:
        Wd[v.index, g.group] = g.weight
dom = np.array(names)[Wd.argmax(1)]
me.data.calc_loop_triangles()
tris = np.array([lt.vertices[:] for lt in me.data.loop_triangles])
tdom = dom[tris[:, 0]].tolist()


def eval_co():
    upd()
    dg = bpy.context.evaluated_depsgraph_get()
    ev = me.evaluated_get(dg); m = ev.to_mesh()
    c = np.array([me.matrix_world @ v.co for v in m.vertices]); ev.to_mesh_clear()
    return c


reset()
c0 = eval_co()
a, b, cc = c0[tris[:, 0]], c0[tris[:, 1]], c0[tris[:, 2]]
N0 = np.cross(b - a, cc - a); N0 /= np.linalg.norm(N0, axis=1)[:, None]
out = {}
for s in ("l", "r"):
    w, d, r, p = frame(s)
    # palm thickness along p through points on the hand axis (between wrist and middle MCP)
    bvh = BVHTree.FromPolygons([Vector(x) for x in c0], tris.tolist(), all_triangles=True)
    th = []
    m1 = rest_head(f"middle_01_{s}")
    for t in (0.35, 0.5, 0.65, 0.8, 0.95):
        q = w + (m1 - w) * t
        hp = bvh.ray_cast(q, p); hd = bvh.ray_cast(q, -p)
        if hp[0] and hd[0]:
            th.append((t, round((hp[0] - hd[0]).length * 100, 2), round(hp[3] * 100, 2), round(hd[3] * 100, 2)))
    out[f"palm_thickness_{s} (t along wrist->middleMCP, total cm, palmar cm, dorsal cm)"] = th
    # finger joint depth: for each finger joint, distance to palmar and dorsal surfaces along p
    jd = {}
    for f in FING:
        for i in (1, 2, 3):
            q = rest_head(f"{f}_{i:02d}_{s}")
            hp = bvh.ray_cast(q, p); hd = bvh.ray_cast(q, -p)
            if hp[0] and hd[0]:
                jd[f"{f}_{i:02d}"] = (round(hp[3] * 100, 2), round(hd[3] * 100, 2), round(hd[3] / (hp[3] + hd[3]), 2))
    out[f"finger_joint_palmar_dorsal_cm_and_dorsal_fraction_{s}"] = jd
    # MCP position relative to the finger web (commissure): web = lowest (most proximal along d)
    # vertex between adjacent fingers
    # distal palm edge: project the MCP heads on d vs the web
    webs = {}
    handv = np.nonzero(np.isin(dom, [f"hand_{s}"] + [f"{f}_01_{s}" for f in FING]))[0]
    for f1, f2 in (("index", "middle"), ("middle", "ring"), ("ring", "pinky")):
        h1 = np.array(rest_head(f"{f1}_02_{s}")); h2 = np.array(rest_head(f"{f2}_02_{s}"))
        mid = (h1 + h2) / 2
        # verts near the plane spanned by d and p through the midpoint between the two fingers
        rr = np.array(r)
        cand = handv[np.abs((c0[handv] - mid) @ rr) < 0.002]
        # web = the most distal vertex on the palm between the fingers: minimal distal extent among
        # those... take the vertex with max projection on d that is still 'hand/01' dominated and
        # lies in the gap: approximate by the min over the gap of the max-d surface
        pr = (c0[cand] - np.array(w)) @ np.array(d)
        webs[f"{f1}-{f2}"] = round(float(pr.max()) * 100, 2)
    mcp = {f: round(float((np.array(rest_head(f"{f}_01_{s}")) - np.array(w)) @ np.array(d)) * 100, 2) for f in FING}
    out[f"along_d_from_wrist_cm_{s}"] = {"MCP": mcp, "web_between_fingers(max distal extent of the gap)": webs}

# curl tests
tests = [("grip60_80_50", (60, 80, 50)), ("builder80_90_45", (80, 90, 45)), ("fist90_100_70", (90, 100, 70)),
         ("fist90_110_80", (90, 110, 80))]
for s in ("l",):
    w, d, r, p = frame(s)
    dors = np.array([i for i, t in enumerate(tris) if tdom[i] == f"hand_{s}" and N0[i] @ np.array(-p) > 0.5])
    palm = np.array([i for i, t in enumerate(tris) if tdom[i] == f"hand_{s}" and N0[i] @ np.array(p) > 0.5])
    fing = np.array([i for i, t in enumerate(tris) if any(tdom[i] == f"{f}_{k:02d}_{s}" for f in FING for k in (2, 3))])
    for name, (m, pi, di) in tests:
        reset(); curl(s, m, pi, di)
        c1 = eval_co()
        def bvh_of(idx):
            return BVHTree.FromPolygons([Vector(x) for x in c1], tris[idx].tolist(), all_triangles=True)
        bf = bvh_of(fing); bd = bvh_of(dors); bp = bvh_of(palm)
        od = bf.overlap(bd); op = bf.overlap(bp)
        # how far do fingertip verts go beyond the dorsal surface: signed distance along -p from the
        # rest dorsal plane is not valid after posing hand? hand is not posed (only fingers) -> ok
        tipv = np.unique(tris[fing].ravel())
        # distance of tip verts from the rest dorsal surface along -p: project on -p relative to the
        # dorsal hand surface point found by ray from the vert towards -p
        bvh_rest = BVHTree.FromPolygons([Vector(x) for x in c0], tris[dors].tolist(), all_triangles=True)
        beyond = 0; maxb = 0.0
        for v in tipv:
            q = Vector(c1[v])
            hit = bvh_rest.ray_cast(q + p * 0.05, -p)      # from palmar side towards dorsal
            if hit[0] is not None:
                dist = (q - hit[0]).dot(-p)                # >0: vertex beyond the dorsal surface
                if dist > 0:
                    beyond += 1; maxb = max(maxb, dist)
        out[f"curl_{name}_{s}"] = {"finger_x_dorsal_face_pairs": len(od), "finger_x_palm_face_pairs": len(op),
                                   "finger_verts_beyond_dorsal_surface": int(beyond), "max_beyond_mm": round(maxb * 1000, 2)}
        print(name, out[f"curl_{name}_{s}"], flush=True)
        if not NORENDER and name in ("grip60_80_50", "fist90_100_70", "builder80_90_45"):
            import importlib.util
            spec = importlib.util.spec_from_file_location("r1_render", R1 + "/r1_render.py")
            rr = importlib.util.module_from_spec(spec); spec.loader.exec_module(rr)
            if not bpy.context.scene.camera:
                rr.setup_scene(me)
            ctr = (np.array(w) + np.array(rest_head(f"middle_01_{s}"))) / 2
            ctr = Vector(ctr) + d * 0.02
            for vn, dirv in (("back", -p), ("side", -r if s == "l" else r), ("palm", p), ("front", d)):
                loc = ctr + Vector(dirv) * 0.45
                rr.render(R1 + f"/r1_hand_{name}_{s}_{vn}.png", loc, ctr, 60)
json.dump(out, open(R1 + "/r1_hands.json", "w"), indent=1)
for k, v in out.items():
    print(k, ":", v)
