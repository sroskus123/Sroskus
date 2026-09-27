"""(Adapted copy for the R1 re-verification: --src=<blend|fbx|glb> --out=<dir> --tag=<t> [--drive --runtime=<json>], extra poses elbow120/squat110/toes40/hipabd45.)
R1 review: extreme-pose deformation tests on the RE-IMPORTED FBX (the delivered file), own
posing code (world-axis rotations about bone heads), own metrics, Cycles CPU renders.

Poses (angles are anatomical joint angles, measured back after posing):
  shoulder150 : L arm abduction 150 deg (frontal plane), R arm flexion 150 deg (sagittal)
  elbow140    : both elbows flexed to 140 deg; L upper arm as rest, R upper arm forward 90 deg
  wrist70     : L wrist flexion 70 deg, R wrist extension 70 deg
  legs        : L hip flexion 100 + knee 130; R hip 0 + knee 130
  squat130    : both hips 100 / knees 130 / ankles 30 dorsiflexion, pelvis lowered (feet planted)
  twist45     : spine axial rotation 45 deg (15/15/15)
  armsdown    : arms hanging at the sides (upper arm 8 deg from vertical) -- idle
usage: python3 r1_poses.py [pose ...] [--norender] [--glbcheck]
"""
import sys, json, math, os
import numpy as np
import bpy, bmesh
from mathutils import Vector, Matrix
from mathutils.bvhtree import BVHTree

IV = "/home/user/Sroskus/IronValley"
sys.path.insert(0, IV + "/Art/Source/Blender/lib")
R1 = IV + "/Art/Previews/_review/base/r1"          # r1_render.py lives here (read only)
opt = {a.split("=")[0]: (a.split("=")[1] if "=" in a else True) for a in sys.argv[1:] if a.startswith("--")}
args = [a for a in sys.argv[1:] if not a.startswith("--")]
NORENDER = "--norender" in sys.argv
SRCPATH = opt.get("--src")
OUT = opt.get("--out", ".")
TAG = opt.get("--tag", "x")
DRIVE = "--drive" in opt
os.makedirs(OUT, exist_ok=True)
if SRCPATH.endswith(".blend"):
    bpy.ops.wm.open_mainfile(filepath=SRCPATH)
    SRC = "blend"
elif SRCPATH.endswith(".fbx"):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=SRCPATH)
    SRC = "fbx"
else:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=SRCPATH)
    SRC = "glb"
arm = [o for o in bpy.data.objects if o.type == 'ARMATURE'][0]
me = sorted([o for o in bpy.data.objects if o.type == 'MESH'], key=lambda o: -len(o.data.vertices))[0]
for o in list(bpy.data.objects):
    if o.type in ('MESH', 'LIGHT', 'CAMERA') and o != me:
        bpy.data.objects.remove(o, do_unlink=True)
MW = arm.matrix_world
X, Y, Z = Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1))


def upd():
    bpy.context.view_layer.update()


def reset():
    for pb in arm.pose.bones:
        pb.rotation_mode = 'QUATERNION'
        pb.rotation_quaternion = (1, 0, 0, 0)
        pb.location = (0, 0, 0)
        pb.scale = (1, 1, 1)
    upd()


def head(n):
    return (MW @ arm.pose.bones[n].matrix).to_translation()


def tail(n):
    return MW @ arm.pose.bones[n].tail


def bdir(n):
    return (tail(n) - head(n)).normalized()


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


def rot_carried(n, axis_rest, deg):
    """rotate about an axis fixed in the PARENT segment (given in rest world coords)"""
    p = arm.pose.bones[n].parent
    ax = (delta(p.name) @ Vector(axis_rest)) if p else Vector(axis_rest)
    rot(n, ax, deg)


def ang(a, b):
    return math.degrees(math.acos(max(-1, min(1, a.normalized().dot(b.normalized())))))


def aim(n, target, frac=1.0):
    cur = bdir(n)
    q = cur.rotation_difference(Vector(target).normalized())
    ax, a = q.to_axis_angle()
    if a > 1e-7:
        rot(n, ax, math.degrees(a) * frac)


DOWN = Vector((0, 0, -1))
achieved = {}


def palm(side):
    w = head(f"hand_{side}")
    mid = head(f"middle_01_{side}")
    d = (mid - w).normalized()
    r = head(f"index_01_{side}") - head(f"pinky_01_{side}")
    r = (r - d * r.dot(d)).normalized()
    # palmar direction from the relaxed finger curl (fingertips curve towards the palm)
    tip = tail(f"middle_03_{side}")
    c = tip - mid
    p = (c - d * c.dot(d))
    p = (p - r * p.dot(r)).normalized()
    return w, d, r, p


# ---------------------------------------------------------------- poses
def pose_shoulder150():
    # left: abduction in the frontal plane about -Y (left arm goes up)
    a0 = ang(bdir("upperarm_l"), DOWN)
    rot("clavicle_l", -Y, 20)
    a1 = ang(bdir("upperarm_l"), DOWN)
    rot("upperarm_l", -Y, 150 - a1)
    # straighten elbow to 5 deg for a clean overhead reach
    u, f = bdir("upperarm_l"), bdir("lowerarm_l")
    rot("lowerarm_l", u.cross(f), -(ang(u, f) - 5))
    achieved["L_abduction_from_down_deg"] = round(ang(bdir("upperarm_l"), DOWN), 1)
    achieved["L_abduction_projected_frontal_deg"] = round(math.degrees(math.atan2(bdir("upperarm_l").x, -bdir("upperarm_l").z)), 1)
    # right: flexion (sagittal) to 150 deg: clavicle elevation 15, then aim forward-up
    rot("clavicle_r", Y, 15)
    a = math.radians(150)
    aim("upperarm_r", (-0.12, -math.sin(a), -math.cos(a)))
    u, f = bdir("upperarm_r"), bdir("lowerarm_r")
    rot("lowerarm_r", u.cross(f), -(ang(u, f) - 5))
    achieved["R_flexion_from_down_deg"] = round(ang(bdir("upperarm_r"), DOWN), 1)
    achieved["R_flexion_projected_sagittal_deg"] = round(math.degrees(math.atan2(-bdir("upperarm_r").y, -bdir("upperarm_r").z)), 1)


def elbow_to(side, target):
    u, f = bdir(f"upperarm_{side}"), bdir(f"lowerarm_{side}")
    n = u.cross(f).normalized()
    cur = ang(u, f)
    rot(f"lowerarm_{side}", n, target - cur)
    achieved[f"{side}_elbow_flexion_deg"] = round(ang(bdir(f"upperarm_{side}"), bdir(f"lowerarm_{side}")), 1)


def pose_elbow140():
    elbow_to("l", 140)
    # right upper arm forward horizontal (flexion 90), then elbow 140 in the same hinge plane
    u0, f0 = bdir("upperarm_r"), bdir("lowerarm_r")
    aim("upperarm_r", (-0.35, -0.8, -0.5))
    elbow_to("r", 140)


def wrist(side, deg):
    w, d, r, p = palm(side)
    # flexion: middle knuckle moves towards the palmar side p
    rot(f"hand_{side}", r, deg)
    d2 = (head(f"middle_01_{side}") - head(f"hand_{side}")).normalized()
    if (d2.dot(p) > 0) != (deg > 0):
        rot(f"hand_{side}", r, -2 * deg)
    d2 = (head(f"middle_01_{side}") - head(f"hand_{side}")).normalized()
    achieved[f"{side}_wrist_{'flexion' if deg > 0 else 'extension'}_deg"] = round(math.degrees(math.atan2(d2.dot(p), d2.dot(d))), 1)


def pose_wrist70():
    wrist("l", 70)
    wrist("r", -70)


def hip_flex(side, deg):
    t0 = bdir(f"thigh_{side}")
    cur = math.degrees(math.atan2(-t0.y, -t0.z))
    rot_carried(f"thigh_{side}", -X, deg - cur)
    t = bdir(f"thigh_{side}")
    achieved[f"{side}_hip_flexion_deg(sagittal)"] = round(math.degrees(math.atan2(-t.y, -t.z)), 1)


def knee_flex(side, deg):
    for _ in range(4):
        cur = ang(bdir(f"thigh_{side}"), head(f"foot_{side}") - head(f"calf_{side}"))
        rot_carried(f"calf_{side}", X, deg - cur)
    achieved[f"{side}_knee_flexion_deg"] = round(ang(bdir(f"thigh_{side}"), head(f"foot_{side}") - head(f"calf_{side}")), 1)


def pose_legs():
    hip_flex("l", 100)
    knee_flex("l", 130)
    knee_flex("r", 130)


def pose_squat130():
    ank0 = (head("foot_l") + head("foot_r")) * 0.5
    for s in ("l", "r"):
        hip_flex(s, 100)
        knee_flex(s, 130)
        rot_carried(f"foot_{s}", -X, 30)
    rot_carried("spine_01", X, 15)
    rot_carried("spine_02", X, 10)
    rot_carried("neck_01", -X, 15)
    rot_carried("head", -X, 8)
    now = (head("foot_l") + head("foot_r")) * 0.5
    pb = arm.pose.bones["pelvis"]
    pb.matrix = MW.inverted() @ (Matrix.Translation(ank0 - now) @ (MW @ pb.matrix))
    upd()


def pose_twist45():
    for n in ("spine_01", "spine_02", "spine_03"):
        rot_carried(n, Z, 15)
    achieved["spine_twist_total_deg"] = 45


def pose_armsdown():
    for s, sg in (("l", 1), ("r", -1)):
        a = ang(bdir(f"upperarm_{s}"), DOWN)
        rot(f"upperarm_{s}", Y * sg, a - 8)      # left arm down = rotate about +Y
        achieved[f"{s}_upperarm_from_vertical_deg"] = round(ang(bdir(f"upperarm_{s}"), DOWN), 1)


def pose_elbow120():
    elbow_to("l", 120)
    aim("upperarm_r", (-0.35, -0.8, -0.5))
    elbow_to("r", 120)


def pose_squat110():
    ank0 = (head("foot_l") + head("foot_r")) * 0.5
    for s in ("l", "r"):
        hip_flex(s, 95)
        knee_flex(s, 110)
        rot_carried(f"foot_{s}", -X, 25)
    rot_carried("spine_01", X, 12)
    now = (head("foot_l") + head("foot_r")) * 0.5
    pb = arm.pose.bones["pelvis"]
    pb.matrix = MW.inverted() @ (Matrix.Translation(ank0 - now) @ (MW @ pb.matrix))
    upd()


def pose_toes40():
    # both toe chains: left dorsiflexion 40 (toes up), right plantarflexion 40
    for s, sgn in (("l", 1), ("r", -1)):
        b = arm.data.bones[f"ball_{s}"]
        x = (MW.to_3x3() @ b.matrix_local.to_3x3()).col[0]
        t0 = tail(f"ball_{s}").z
        rot(f"ball_{s}", x, 40)
        up = tail(f"ball_{s}").z > t0
        if up != (sgn > 0):
            rot(f"ball_{s}", x, -80)
        achieved[f"{s}_toes_{'up' if sgn > 0 else 'down'}_deg"] = 40


def pose_hipabd45():
    for s, sg in (("l", -1), ("r", 1)):
        rot_carried(f"thigh_{s}", Y * sg, 45)
    achieved["hip_abduction_deg"] = 45


POSES = {"elbow120": pose_elbow120, "squat110": pose_squat110, "toes40": pose_toes40, "hipabd45": pose_hipabd45,
         "shoulder150": pose_shoulder150, "elbow140": pose_elbow140, "wrist70": pose_wrist70,
         "legs": pose_legs, "squat130": pose_squat130, "twist45": pose_twist45, "armsdown": pose_armsdown}

# ---------------------------------------------------------------- metrics
names = [g.name for g in me.vertex_groups]
Wd = np.zeros((len(me.data.vertices), len(names)))
for v in me.data.vertices:
    for g in v.groups:
        Wd[v.index, g.group] = g.weight
dom = np.array(names)[Wd.argmax(1)]
tris = np.array([[me.data.loops[i].vertex_index for i in lt.loops] for lt in me.data.loop_triangles]) if me.data.loop_triangles else None
if tris is None or len(tris) == 0:
    me.data.calc_loop_triangles()
    tris = np.array([lt.vertices[:] for lt in me.data.loop_triangles])
else:
    tris = np.array([lt.vertices[:] for lt in me.data.loop_triangles])


def eval_co():
    upd()
    dg = bpy.context.evaluated_depsgraph_get()
    ev = me.evaluated_get(dg)
    m = ev.to_mesh()
    c = np.array([me.matrix_world @ v.co for v in m.vertices])
    ev.to_mesh_clear()
    return c


def tri_geom(c):
    a, b, cc = c[tris[:, 0]], c[tris[:, 1]], c[tris[:, 2]]
    n = np.cross(b - a, cc - a)
    A = np.linalg.norm(n, axis=1)
    return A, n / np.maximum(A[:, None], 1e-15)


def self_intersections(c):
    bvh = BVHTree.FromPolygons([Vector(x) for x in c], tris.tolist(), all_triangles=True)
    pairs = bvh.overlap(bvh)
    ts = [set(t) for t in tris]
    bad = [(i, j) for i, j in pairs if i < j and not (ts[i] & ts[j])]
    return bad


def ring_ratio(c0, c1, bone, frac, halfw=0.012, R0=None):
    """mean radial distance of verts near a cross-section of `bone` at `frac` of its length,
    posed / rest; verts selected in REST by slab position and dominant-bone family"""
    b = arm.data.bones[bone]
    h0 = np.array(MW @ b.head_local); t0 = np.array(MW @ b.tail_local)
    ax0 = (t0 - h0) / np.linalg.norm(t0 - h0)
    p0 = h0 + frac * (t0 - h0)
    s = (c0 - p0) @ ax0
    rad0 = c0 - p0 - np.outer(s, ax0)
    fam = bone.split("_")[0]
    near = (np.abs(s) < halfw) & (np.linalg.norm(rad0, axis=1) < (R0 or 0.09))
    near &= np.array([(fam in d) or (d.startswith(bone.split("_")[0])) for d in dom]) | True
    if near.sum() < 6:
        return None
    # posed frame of the bone
    h1 = np.array(head(bone)); t1 = np.array(tail(bone))
    ax1 = (t1 - h1) / np.linalg.norm(t1 - h1)
    p1 = h1 + frac * (t1 - h1)
    s1 = (c1[near] - p1) @ ax1
    rad1 = c1[near] - p1 - np.outer(s1, ax1)
    return float(np.linalg.norm(rad1, axis=1).mean() / np.linalg.norm(rad0[near], axis=1).mean())


def clearance(c, pt):
    """distance from a joint centre to the nearest surface point"""
    bvh = BVHTree.FromPolygons([Vector(x) for x in c], tris.tolist(), all_triangles=True)
    loc, n, i, d = bvh.find_nearest(Vector(pt))
    return float(d)


def volume(c):
    a, b, cc = c[tris[:, 0]], c[tris[:, 1]], c[tris[:, 2]]
    return float(np.einsum("ij,ij->i", a, np.cross(b, cc)).sum() / 6)


reset()
c_rest = eval_co()
A0, N0 = tri_geom(c_rest)
V0 = volume(c_rest)
bone_idx = {n: i for i, n in enumerate(names)}
tri_dom = dom[tris[:, 0]]
JOINTS = {"shoulder_l": ("upperarm_l", 0.0), "shoulder_r": ("upperarm_r", 0.0), "elbow_l": ("lowerarm_l", 0.0),
          "elbow_r": ("lowerarm_r", 0.0), "wrist_l": ("hand_l", 0.0), "wrist_r": ("hand_r", 0.0),
          "hip_l": ("thigh_l", 0.0), "hip_r": ("thigh_r", 0.0), "knee_l": ("calf_l", 0.0), "knee_r": ("calf_r", 0.0)}
clear0 = {k: clearance(c_rest, np.array(MW @ arm.data.bones[b].head_local)) for k, (b, _) in JOINTS.items()}
si_rest = self_intersections(c_rest)

import importlib.util
spec = importlib.util.spec_from_file_location("r1_render", R1 + "/r1_render.py")
rr = importlib.util.module_from_spec(spec); spec.loader.exec_module(rr)
if not NORENDER:
    rr.setup_scene(me)

CAMS = {
    "elbow120": [("elbow_l_out", (1.1, 0.5, 1.2), (0.3, 0.0, 1.2), 40), ("elbow_l_in", (0.9, -1.0, 1.2), (0.3, -0.05, 1.22), 40),
                 ("elbow_r_top", (-0.7, -0.4, 2.2), (-0.2, -0.25, 1.4), 40)],
    "squat110": [("side", (2.4, -0.8, 0.7), (0, 0, 0.55), 45), ("knee_l_close", (1.1, -0.2, 0.5), (0.2, -0.1, 0.45), 35),
                 ("back", (0.3, 2.4, 0.8), (0, 0.1, 0.5), 45)],
    "toes40": [("top", (0.35, -0.9, 0.7), (0.0, -0.12, 0.03), 30), ("side_l", (1.0, -0.35, 0.2), (0.2, -0.12, 0.04), 30),
               ("side_r", (-1.0, -0.35, 0.2), (-0.2, -0.12, 0.04), 30)],
    "hipabd45": [("front", (0.3, -2.8, 0.9), (0, 0, 0.85), 45), ("back", (0.3, 2.8, 0.95), (0, 0, 0.9), 45),
                 ("groin_l", (0.9, -1.1, 0.8), (0.12, -0.05, 0.85), 40)],
    "shoulder150": [("front", (0, -3.2, 1.45), (0, 0, 1.45), 45), ("back", (0.4, 3.2, 1.6), (0.1, 0, 1.55), 45),
                    ("armpit_l", (1.25, -0.9, 1.25), (0.2, 0.0, 1.45), 40), ("shoulder_r_side", (-1.4, -0.35, 1.5), (-0.18, -0.05, 1.5), 40)],
    "elbow140": [("front", (0.3, -2.6, 1.3), (0, 0, 1.25), 40), ("elbow_l_out", (1.1, 0.5, 1.2), (0.3, 0.0, 1.2), 40),
                 ("elbow_l_in", (0.9, -1.0, 1.2), (0.3, -0.05, 1.22), 40), ("elbow_r_top", (-0.7, -0.4, 2.2), (-0.2, -0.25, 1.4), 40)],
    "wrist70": [("wrist_l", (1.1, -0.9, 1.05), (0.57, -0.1, 0.97), 30), ("wrist_r", (-1.1, -0.9, 1.05), (-0.57, -0.1, 0.97), 30),
                ("wrist_l_back", (1.0, 0.8, 1.05), (0.57, -0.05, 0.97), 30), ("wrist_r_back", (-1.0, 0.8, 1.05), (-0.57, -0.05, 0.97), 30)],
    "legs": [("side_l", (2.4, -0.6, 0.8), (0.1, -0.1, 0.75), 45), ("front", (0.3, -2.8, 0.8), (0, -0.1, 0.8), 45),
             ("knee_r_back", (-0.5, 1.4, 0.6), (-0.15, 0.1, 0.55), 40), ("groin_l", (0.9, -1.0, 0.75), (0.08, -0.1, 0.9), 40),
             ("glute_back", (0.4, 1.6, 0.95), (0.05, 0.05, 0.9), 40)],
    "squat130": [("side", (2.4, -0.8, 0.7), (0, 0, 0.55), 45), ("front", (0.2, -2.6, 0.7), (0, -0.1, 0.55), 45),
                 ("back", (0.3, 2.4, 0.8), (0, 0.1, 0.5), 45), ("knee_l_close", (1.1, -0.2, 0.5), (0.2, -0.1, 0.45), 35)],
    "twist45": [("front", (0, -3.0, 1.2), (0, 0, 1.15), 45), ("top", (0.01, -0.3, 3.2), (0, 0, 1.3), 40),
                ("back", (0.3, 2.8, 1.25), (0, 0, 1.2), 45)],
    "armsdown": [("front", (0, -3.2, 1.2), (0, 0, 1.15), 45), ("armpit_l", (1.2, -1.0, 1.35), (0.18, 0, 1.3), 35),
                 ("back", (0.2, 3.2, 1.3), (0, 0, 1.25), 45), ("side_l", (2.5, 0, 1.25), (0.2, 0, 1.2), 40)],
}

results = {}
for pname in (args or list(POSES)):
    reset()
    achieved.clear()
    POSES[pname]()
    if DRIVE:
        # runtime rules of SK_Human_Base (twist bones + corrective shapes), spec from the exported
        # runtime JSON (FBX/GLB carry no custom properties) or the .blend's mesh property
        import ivchar as C
        spec = json.load(open(opt["--runtime"]))["correctives"]["spec"] if "--runtime" in opt else None
        C.drive_twist_bones(arm)
        drv = C.drive_correctives(arm, me, spec)
        upd()
    c1 = eval_co()
    A1, N1 = tri_geom(c1)
    ar = A1 / np.maximum(A0, 1e-15)
    # inversion: posed normal vs rest normal carried by the dominant bone's rotation
    inv = 0
    Dm = {n: np.array(delta(n)) for n in set(tri_dom)}
    Nexp = np.stack([Dm[d] @ N0[i] for i, d in enumerate(tri_dom)])
    dots = np.einsum("ij,ij->i", Nexp, N1)
    inv_idx = np.nonzero(dots < 0)[0]
    e = np.r_[tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]]
    L0 = np.linalg.norm(c_rest[e[:, 0]] - c_rest[e[:, 1]], axis=1)
    L1 = np.linalg.norm(c1[e[:, 0]] - c1[e[:, 1]], axis=1)
    er = L1 / np.maximum(L0, 1e-12)
    si = self_intersections(c1)
    si_new = len(si) - len(si_rest)
    rr_ = {}
    for k, (b, fr) in JOINTS.items():
        for f in (-0.0,):
            pass
    rings = {}
    for bone, fr in (("upperarm_l", 0.08), ("upperarm_r", 0.08), ("upperarm_l", 0.95), ("upperarm_r", 0.95),
                     ("lowerarm_l", 0.05), ("lowerarm_r", 0.05), ("lowerarm_l", 0.97), ("lowerarm_r", 0.97),
                     ("thigh_l", 0.95), ("thigh_r", 0.95), ("calf_l", 0.04), ("calf_r", 0.04), ("thigh_l", 0.05), ("thigh_r", 0.05)):
        r_ = ring_ratio(c_rest, c1, bone, fr)
        if r_ is not None:
            rings[f"{bone}@{fr}"] = round(r_, 3)
    clear1 = {k: round(clearance(c1, np.array(head(b))) / max(clear0[k], 1e-9), 3) for k, (b, _) in JOINTS.items()}
    # worst collapsed tris by region (dominant bone)
    worst = {}
    for i in np.argsort(ar)[:40]:
        worst[tri_dom[i]] = worst.get(tri_dom[i], 0) + 1
    res = {"achieved": dict(achieved),
           "tri_area_ratio_min": round(float(ar.min()), 4),
           "tris_area_lt_0.25": int((ar < 0.25).sum()), "tris_area_lt_0.10": int((ar < 0.10).sum()),
           "tris_area_gt_3": int((ar > 3).sum()),
           "worst40_tris_by_dominant_bone": worst,
           "inverted_tris(normal vs bone-carried rest normal)": int(len(inv_idx)),
           "inverted_tris_by_bone": {k: int(v) for k, v in zip(*np.unique(tri_dom[inv_idx], return_counts=True))} if len(inv_idx) else {},
           "edge_ratio_min_max": [round(float(er.min()), 3), round(float(er.max()), 3)],
           "self_intersecting_pairs": len(si), "self_intersecting_pairs_new_vs_rest": si_new,
           "self_int_by_bone_pair_top": {},
           "body_volume_ratio": round(volume(c1) / V0, 4),
           "ring_ratio(posed/rest)": rings,
           "joint_clearance_ratio(posed/rest)": clear1}
    bp = {}
    for i, j in si:
        k = "/".join(sorted((tri_dom[i], tri_dom[j])))
        bp[k] = bp.get(k, 0) + 1
    res["self_int_by_bone_pair_top"] = dict(sorted(bp.items(), key=lambda kv: -kv[1])[:10])
    results[pname] = res
    print(pname, json.dumps(res, indent=1), flush=True)
    if not NORENDER:
        for vname, loc, tgt, lens in CAMS.get(pname, []):
            rr.render(os.path.abspath(os.path.join(OUT, f"{TAG}_{pname}_{vname}.png")), loc, tgt, lens)
reset()
old = {}
fn = os.path.join(OUT, f"{TAG}_pose_metrics_{SRC}{'_driven' if DRIVE else ''}.json")
if os.path.exists(fn):
    old = json.load(open(fn))
old.update(results)
json.dump(old, open(fn, "w"), indent=1)
