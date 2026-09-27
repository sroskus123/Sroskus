"""
soldier_pose.py -- test poses of the soldier (extreme deformation poses and rifle stances).

Rifle stances: the IV-7 is placed from the view (bore along the camera direction), the butt pad
centre in the right shoulder pocket (a point carried rigidly by spine_03, on the plate carrier's
shoulder strap), both arms solved by analytic two-bone IK (ivhands.arm_ik) to the hand transforms
of the grip poses in Hand_Poses.json (`hand_attach` in the IV-7 socket frames) and the fingers set
from the same poses.  For ADS the neck posture is solved so that the eye lies on the optic's axis
(socket_ads line) while the head looks along the bore (cheek on the stock).
"""

import json
import math

import bpy
import numpy as np
from mathutils import Vector, Matrix

import ivchar as C
import ivhands as HN
import ivsoldier as S

X = Vector((1, 0, 0))
Y = Vector((0, 1, 0))
Z = Vector((0, 0, 1))

EYE_REST = np.array([0.0, -0.131, 1.687])            # between the MakeHuman eye joints (HUMAN_BASE_spec 12.3)
BUTT_LOCAL = np.array([-0.2840, 0.0, 0.0800])         # IV-7 butt pad centre in the rifle frame (m)
POCKET_REST = np.array([-0.135, -0.150, 1.480])       # right shoulder pocket (rest), carried by clavicle_r, on the strap


# =============================================================================
# extreme deformation poses
# =============================================================================

def p_arms_raised(arm):
    for side, sg in (("l", -1), ("r", 1)):
        C.rotate_bone_world(arm, f"clavicle_{side}", Y * sg, 22)
        C.rotate_bone_world(arm, f"upperarm_{side}", Y * sg, 105)


def p_squat(arm, hip=100.0, knee=130.0, ankle=30.0, spine=(15.0, 10.0), neck=(15.0, 8.0)):
    rest_ank = (C.bone_world(arm, "foot_l") + C.bone_world(arm, "foot_r")) * 0.5
    for side in ("l", "r"):
        C.pose_joint_to(arm, "hip", side, hip, reset=False)
        C.pose_joint_to(arm, "knee", side, knee, reset=False)
        C.rotate_bone_rest_axis(arm, f"foot_{side}", -X, ankle)
    C.rotate_bone_rest_axis(arm, "spine_01", X, spine[0])
    C.rotate_bone_rest_axis(arm, "spine_02", X, spine[1])
    C.rotate_bone_rest_axis(arm, "neck_01", -X, neck[0])
    C.rotate_bone_rest_axis(arm, "head", -X, neck[1])
    now = (C.bone_world(arm, "foot_l") + C.bone_world(arm, "foot_r")) * 0.5
    pb = arm.pose.bones["pelvis"]
    Mw = arm.matrix_world @ pb.matrix
    pb.matrix = arm.matrix_world.inverted() @ (Matrix.Translation(rest_ank - now) @ Mw)
    bpy.context.view_layer.update()


def p_squat_deep(arm):
    """Deep squat as a soldier in a plate carrier does it: knees apart (the thighs pass beside the
    placard), trunk only slightly forward, arms forward for balance."""
    rest_ank = (C.bone_world(arm, "foot_l") + C.bone_world(arm, "foot_r")) * 0.5
    for side, sg in (("l", -1.0), ("r", 1.0)):
        C.rotate_bone_rest_axis(arm, f"thigh_{side}", Y * sg, 22.0)          # abduction (knees apart)
        C.pose_joint_to(arm, "hip", side, 100.0, reset=False)
        C.pose_joint_to(arm, "knee", side, 130.0, reset=False)
        C.rotate_bone_rest_axis(arm, f"foot_{side}", -X, 30.0)
    C.rotate_bone_rest_axis(arm, "spine_01", X, 8.0)
    C.rotate_bone_rest_axis(arm, "spine_02", X, 4.0)
    C.rotate_bone_rest_axis(arm, "neck_01", -X, 10.0)
    C.rotate_bone_rest_axis(arm, "head", -X, 4.0)
    now = (C.bone_world(arm, "foot_l") + C.bone_world(arm, "foot_r")) * 0.5
    pb = arm.pose.bones["pelvis"]
    Mw = arm.matrix_world @ pb.matrix
    pb.matrix = arm.matrix_world.inverted() @ (Matrix.Translation(rest_ank - now) @ Mw)
    bpy.context.view_layer.update()
    for s, sx in (("l", 1), ("r", -1)):
        C.aim_bone(arm, f"upperarm_{s}", (0.25 * sx, -0.85, -0.45))
        C.aim_bone(arm, f"lowerarm_{s}", (0.05 * sx, -0.9, -0.2))


def p_sprint(arm):
    """Sprint stride: left leg swinging forward (hip 65, knee 95), right leg pushing off behind
    (hip extension 22, knee 35), trunk leaning 12 deg, arms swinging (elbows ~95 deg)."""
    C.rotate_bone_rest_axis(arm, "spine_01", X, 6.0)
    C.rotate_bone_rest_axis(arm, "spine_02", X, 6.0)
    C.rotate_bone_rest_axis(arm, "neck_01", -X, 8.0)
    C.rotate_bone_rest_axis(arm, "head", -X, 4.0)
    C.pose_joint_to(arm, "hip", "l", 65.0, reset=False)
    C.pose_joint_to(arm, "knee", "l", 95.0, reset=False)
    C.rotate_bone_rest_axis(arm, "thigh_r", X, 22.0)       # extension (backwards)
    C.pose_joint_to(arm, "knee", "r", 35.0, reset=False)
    C.rotate_bone_rest_axis(arm, "foot_r", X, 25.0)        # plantar flexion at push-off
    # arms: right forward, left back (opposite to the legs)
    C.aim_bone(arm, "upperarm_r", (-0.18, -0.55, -0.82))
    C.aim_bone(arm, "lowerarm_r", (0.05, -0.85, 0.52))
    C.aim_bone(arm, "upperarm_l", (0.20, 0.50, -0.84))
    C.aim_bone(arm, "lowerarm_l", (0.06, -0.55, -0.83))
    for s in ("l", "r"):
        C.pose_hand_anat(arm, s, FIST_LOOSE)
    bpy.context.view_layer.update()


_F = lambda a, b, c, d=0.0: {"mcp": a, "pip": b, "dip": c, "abd": d}      # noqa: E731
FIST_LOOSE = {"index": _F(45, 55, 30, 2), "middle": _F(50, 60, 32), "ring": _F(52, 60, 32, -2), "pinky": _F(55, 60, 30, -4),
              "thumb": {"cmc_flex": 15, "cmc_abd": 15, "cmc_rot": 5, "mcp": 15, "ip": 20}}


# =============================================================================
# rifle stances
# =============================================================================

def json_to_mat(d):
    return np.array(d, float).reshape(4, 4) if not isinstance(d, dict) else np.array(d["m"], float).reshape(4, 4)


def bone_pose_matrix(arm, name):
    """World pose matrix x inverse world rest matrix (the rigid motion of the bone)."""
    Mp = np.array(arm.matrix_world @ arm.pose.bones[name].matrix)
    Mr = np.array(arm.matrix_world @ arm.data.bones[name].matrix_local)
    return Mp @ np.linalg.inv(Mr)


def eye_world(arm):
    D = bone_pose_matrix(arm, "head")
    return D[:3, :3] @ EYE_REST + D[:3, 3], D[:3, :3]


def rifle_matrix(view_dir, butt_world, cant=0.0):
    """IV-7 root world matrix: +X along view_dir, +Z up (no cant), butt pad centre at butt_world."""
    d = np.asarray(view_dir, float)
    d /= np.linalg.norm(d)
    up = np.array([0, 0, 1.0]) - d * d[2]
    up /= np.linalg.norm(up)
    y = np.cross(up, d)
    R = np.stack([d, y, up], 1)
    if cant:
        c, s = math.cos(math.radians(cant)), math.sin(math.radians(cant))
        R = R @ np.array([[1, 0, 0], [0, c, -s], [0, s, c]])
    M = np.eye(4)
    M[:3, :3] = R
    M[:3, 3] = np.asarray(butt_world) - R @ BUTT_LOCAL
    return M


def view_dir_from(pitch_deg, yaw_deg=0.0):
    p, y = math.radians(pitch_deg), math.radians(yaw_deg)
    return np.array([math.sin(y) * math.cos(p), -math.cos(y) * math.cos(p), math.sin(p)])


def set_head_orientation(arm, R_world_delta):
    """Pose the head so its rigid rest->pose rotation equals R_world_delta (keeps its joint)."""
    pb = arm.pose.bones["head"]
    Mr = np.array(arm.matrix_world @ arm.data.bones["head"].matrix_local)
    Mcur = np.array(arm.matrix_world @ pb.matrix)
    M = np.eye(4)
    M[:3, :3] = R_world_delta @ Mr[:3, :3]
    M[:3, 3] = Mcur[:3, 3]
    pb.matrix = arm.matrix_world.inverted() @ Matrix(M.tolist())
    bpy.context.view_layer.update()


def look_rotation(d):
    """Rotation taking the rest forward (-Y) / up (+Z) to view direction d with no roll."""
    d = np.asarray(d, float) / np.linalg.norm(d)
    up = np.array([0, 0, 1.0]) - d * d[2]
    up /= np.linalg.norm(up)
    A = np.stack([np.array([1.0, 0, 0]), np.array([0, -1.0, 0]), np.array([0, 0, 1.0])], 1)
    B = np.stack([-np.cross(d, up), d, up], 1)        # rest +X = -(forward x up)
    return B @ np.linalg.inv(A)


def base_upper_body(arm, pitch, bladed=True, ads=False):
    C.reset_pose(arm)
    if bladed:
        # nearly squared stance (the chest faces the target), a slight turn and, for ADS, a
        # forward lean into the rifle
        for n, a in zip(("spine_01", "spine_02", "spine_03"), (2.0, 2.0, 2.0)):
            C.rotate_bone_rest_axis(arm, n, Z, -a)
        if ads:
            C.rotate_bone_rest_axis(arm, "spine_02", X, 3.0)
            C.rotate_bone_rest_axis(arm, "spine_03", X, 3.0)
    # look up / down: shared by the spine and the neck
    for n, f in (("spine_01", 0.10), ("spine_02", 0.22), ("spine_03", 0.23)):
        C.rotate_bone_rest_axis(arm, n, X, -pitch * f)          # +X rotation = flexion (look down) -> -pitch
    C.rotate_bone_world(arm, "clavicle_l", Z, -16.0)            # support shoulder protracted
    C.rotate_bone_world(arm, "clavicle_r", Y, 14.0 if ads else 5.0)  # firing shoulder raised (shrug into the stock)
    C.rotate_bone_world(arm, "clavicle_r", Z, 8.0 if ads else 4.0)   # and brought forward
    bpy.context.view_layer.update()


def pocket_world(arm):
    D = bone_pose_matrix(arm, "clavicle_r")
    return D[:3, :3] @ POCKET_REST + D[:3, 3]


def solve_neck_for_eye(arm, view_dir, line_p, line_d, head_R, q_neck0):
    """Neck flexion / lateral bend / axial turn and a head roll towards the stock so that the eye
    lies on the line (line_p, line_d) while the head looks along the line.  The neck starts from
    q_neck0 on every call.  Returns (residual m, angles, eye relief offset m)."""
    from scipy.optimize import least_squares
    pb = arm.pose.bones["neck_01"]
    d = np.asarray(line_d, float)

    def apply(x):
        pb.rotation_quaternion = q_neck0
        bpy.context.view_layer.update()
        C.rotate_bone_rest_axis(arm, "neck_01", X, x[0])
        C.rotate_bone_rest_axis(arm, "neck_01", Y, x[1])
        C.rotate_bone_rest_axis(arm, "neck_01", Z, x[2])
        roll = np.array(Matrix.Rotation(math.radians(x[3]), 3, Vector(tuple(d))))
        set_head_orientation(arm, roll @ head_R)

    def res(x):
        apply(x)
        e, _ = eye_world(arm)
        v = e - line_p
        perp = v - d * (v @ d)
        along = v @ d                     # red dot: any eye relief between the stock and the optic
        pen = max(0.0, along - 0.03) + max(0.0, -0.20 - along)
        return np.concatenate([perp * 100.0, [pen * 30.0], np.asarray(x) * 0.003])
    r = least_squares(res, np.array([20.0, 0.0, 0.0, 0.0]), bounds=([-10, -30, -45, -25], [50, 30, 45, 25]),
                      diff_step=0.02)
    apply(r.x)
    e, _ = eye_world(arm)
    v = e - line_p
    perp = v - d * (v @ d)
    return float(np.linalg.norm(perp)), [round(float(a), 2) for a in r.x], float(v @ d)


AXIS_ABOVE_BUTT = 0.16172 - BUTT_LOCAL[2]      # optic axis above the butt pad centre (IV-7 socket_ads z - butt z)
SUPPORT_REACH = 0.548                           # shoulder joint -> wrist joint with the elbow almost straight


def pose_ads_params(arm, x, view, pitch):
    """x = [spine twist, spine lean, clavicle_r elevation, clavicle_r protraction, clavicle_l
    protraction, neck flexion, neck lateral bend, head roll] (degrees)."""
    C.reset_pose(arm)
    tw, lean, ce, cp, cl, nf, nl, hr = x
    for n in ("spine_01", "spine_02", "spine_03"):
        C.rotate_bone_rest_axis(arm, n, Z, -tw / 3.0)
    for n, f in (("spine_01", 0.10), ("spine_02", 0.22), ("spine_03", 0.23)):
        C.rotate_bone_rest_axis(arm, n, X, -pitch * f)
    C.rotate_bone_rest_axis(arm, "spine_02", X, lean * 0.5)
    C.rotate_bone_rest_axis(arm, "spine_03", X, lean * 0.5)
    C.rotate_bone_world(arm, "clavicle_r", Y, ce)
    C.rotate_bone_world(arm, "clavicle_r", Z, cp)
    C.rotate_bone_world(arm, "clavicle_l", Z, -cl)
    C.rotate_bone_rest_axis(arm, "neck_01", X, nf)
    C.rotate_bone_rest_axis(arm, "neck_01", Y, nl)
    roll = np.array(Matrix.Rotation(math.radians(hr), 3, Vector(tuple(view))))
    set_head_orientation(arm, roll @ look_rotation(view))


def rifle_from_eye(arm, view, relief):
    """Rifle matrix with the optic axis through the eye; the butt pad centre `relief` behind the
    eye along the bore."""
    e, _ = eye_world(arm)
    d = np.asarray(view, float)
    up = np.array([0, 0, 1.0]) - d * d[2]
    up /= np.linalg.norm(up)
    butt = e - d * relief - up * AXIS_ABOVE_BUTT
    return rifle_matrix(d, butt), butt


def solve_ads(arm, rig, lib, view, pitch, left="support_handguard"):
    """Aiming posture: the butt pad centre on the right shoulder pocket (which may slide up the
    shoulder by dz), the eye within 1.5 cm of the optic axis (the first-person camera itself sits at
    socket_ads, the game convention), the support hand within reach; torso / clavicle / neck / head
    angles regularised towards a natural stance."""
    from scipy.optimize import least_squares
    e_sup = lib["poses"][left]
    Hs_rel = np.array(e_sup["hand_attach"]["l"]["matrix"], float)
    S_loc = np.array(rig.data.bones[e_sup["socket"]].matrix_local)
    #              twist lean  ce    cp   cl    nf    nl     hr   relief dz   slide
    x0 = np.array([12.0, 5.0, 10.0, 6.0, 16.0, 22.0, -10.0, 10.0, 0.110, 0.02, 0.04])
    lo = np.array([0.0, 0.0, 0.0, 0.0, 0.0, 0.0, -25.0, 0.0, 0.07, -0.01, 0.0])
    hi = np.array([32.0, 14.0, 20.0, 15.0, 30.0, 40.0, 5.0, 20.0, 0.20, 0.06, 0.075])
    reg = np.array([0.5, 0.6, 0.5, 0.5, 0.3, 0.3, 0.4, 0.4, 0.0, 0.0, 0.0]) * 0.01

    def evaluate(x):
        pose_ads_params(arm, x[:8], view, pitch)
        e, _ = eye_world(arm)
        d = np.asarray(view, float)
        up = np.array([0, 0, 1.0]) - d * d[2]
        up /= np.linalg.norm(up)
        pk = pocket_world(arm) + up * x[9]
        # rifle from the pocket; the eye is then measured against the optic axis
        W = rifle_matrix(d, pk)
        axis_p = (W @ np.array([0.01786, 0.0, 0.16172, 1.0]))[:3]
        v = e - axis_p
        along = v @ d
        perp = v - d * along
        return W, e, perp, along, pk

    def res(x):
        W, e, perp, along, pk = evaluate(x)
        pd = np.linalg.norm(perp)
        sh = np.array(C.bone_world(arm, "upperarm_l"))
        Tsl = np.eye(4); Tsl[0, 3] = -x[10]
        hand = (W @ S_loc @ Tsl @ Hs_rel)[:3, 3]
        reach = max(0.0, np.linalg.norm(hand - sh) - (SUPPORT_REACH - 0.06))
        # eye relief (from the butt pad along the bore) target x[8]
        relief = along + (0.01786 - BUTT_LOCAL[0])
        return np.concatenate([[max(0.0, pd - 0.012) * 90.0, (relief - x[8]) * 15.0, reach * 80.0, x[10] * 2.0], (x - x0) * reg])
    r = least_squares(res, x0, bounds=(lo, hi), diff_step=0.03, max_nfev=300)
    W, e, perp, along, pk = evaluate(r.x)
    return r.x, W, float(np.linalg.norm(perp)), float(along + (0.01786 - BUTT_LOCAL[0]))


class RifleCollider:
    """The IV-7 parts in rifle-local space (static BVHs) for fast clearance tests while posing."""

    def __init__(self, rig, parts):
        self.rig = rig
        Mi = np.linalg.inv(np.array(rig.matrix_world))
        self.parts = []
        for o in parts:
            co = S.co_of(o)
            M = Mi @ np.array(o.matrix_world)
            co = co @ M[:3, :3].T + M[:3, 3]
            tr = S.tris_of(o.data)
            self.parts.append((o.name, co, tr, S.bvh(co, tr), co.min(0) - 0.02, co.max(0) + 0.02))
        self.all = np.concatenate([p[1] for p in self.parts])


def clear_rifle(rc, obstacles, clear=0.0015, iters=8):
    """Translate the rifle out of the posed obstacles (body proxy, head gear, carrier straps ...):
    rifle vertices behind an obstacle surface and obstacle vertices behind a rifle surface (nearest-
    face sign, depth < 3 cm) are pushed apart.  Returns the total shift (m) and the residual depth."""
    rig = rc.rig
    total = np.zeros(3)
    obs = []
    for o in obstacles:
        co = S.eval_co(o)
        tr = S.tris_of(o.data)
        obs.append((o.name, co, S.bvh(co, tr), co.min(0) - 0.03, co.max(0) + 0.03))
    worst = 0.0
    for it in range(iters):
        W = np.array(rig.matrix_world)
        Rw = rc.all @ W[:3, :3].T + W[:3, 3]
        best = (0.0, None, None)
        for name, co, bv, lo, hi in obs:
            m = ((Rw >= lo) & (Rw <= hi)).all(1)
            if not m.any():
                continue
            P = Rw[m]
            loc, nor, fi, d = S.nearest_on(bv, P, 0.03)
            sgn = ((P - loc) * nor).sum(1)
            pen = (fi >= 0) & (sgn < 0)
            if pen.any():
                k = np.argmax(np.where(pen, d, -1))
                if d[k] > best[0]:
                    best = (d[k], nor[k], name)
            # obstacle vertices inside rifle parts (in rifle space)
            Wi = np.linalg.inv(W)
            Q = co @ Wi[:3, :3].T + Wi[:3, 3]
            for pn, pco, ptr, pbv, plo, phi in rc.parts:
                mq = ((Q >= plo) & (Q <= phi)).all(1)
                if not mq.any():
                    continue
                loc, nor, fi, d = S.nearest_on(pbv, Q[mq], 0.03)
                sgn = ((Q[mq] - loc) * nor).sum(1)
                pen = (fi >= 0) & (sgn < 0)
                if pen.any():
                    k = np.argmax(np.where(pen, d, -1))
                    if d[k] > best[0]:
                        best = (d[k], -(W[:3, :3] @ nor[k]), f"{name}->{pn}")
        worst = best[0]
        if best[0] <= clear * 0.5 or best[1] is None:
            break
        mv = np.asarray(best[1]) * (best[0] + clear)
        total += mv
        M = np.array(rig.matrix_world)
        M[:3, 3] += mv
        rig.matrix_world = Matrix(M.tolist())
        bpy.context.view_layer.update()
    return total, worst


def rifle_stance(arm, rig, lib, mode="ads", pitch=0.0, left="support_handguard", right="rifle_grip_index_straight",
                 hip_drop=2.0, hip_yaw=4.0, collider=None, obstacles=None):
    """Pose the soldier holding the IV-7.  mode 'ads' (cheek on the stock, eye by the optic axis)
    or 'hip' (rifle shouldered, head up, sights below the eye line).  Returns a report dict."""
    view = view_dir_from(pitch)
    rep = {"mode": mode, "pitch_deg": pitch}
    names = ("spine_twist", "spine_lean", "clav_r_elev", "clav_r_prot", "clav_l_prot", "neck_flex", "neck_lat", "head_roll")
    if mode == "ads":
        x, W, pd, relief = solve_ads(arm, rig, lib, view, pitch, left)
        slide = float(x[10])
        rep.update({"params_deg": dict(zip(names, [round(float(v), 2) for v in x[:8]])),
                    "butt_raised_on_shoulder_mm": round(float(x[9]) * 1000, 1),
                    "support_hand_slide_back_mm": round(slide * 1000, 1),
                    "eye_relief_from_butt_m": round(relief, 3), "eye_to_optic_axis_mm": round(pd * 1000, 1)})
    else:
        x = np.array([14.0, 3.0, 12.0, 6.0, 20.0, 14.0, 0.0, 0.0])
        pose_ads_params(arm, x, view, pitch)
        vd = view_dir_from(pitch - hip_drop, hip_yaw)
        up = np.array([0, 0, 1.0])
        W = rifle_matrix(vd, pocket_world(arm) + up * 0.035 + np.array([0.02, 0, 0]))
        slide = 0.06
        rep["params_deg"] = dict(zip(names, x.tolist()))
        rep["support_hand_slide_back_mm"] = slide * 1000
    rig.matrix_world = Matrix(W.tolist())
    bpy.context.view_layer.update()
    if collider is not None and obstacles:
        shift, resid = clear_rifle(collider, obstacles)
        rep["rifle_clearance_shift_mm"] = [round(float(v) * 1000, 1) for v in shift]
        rep["rifle_clearance_residual_mm"] = round(resid * 1000, 2)
    ik = {}
    for s, pn, pole in (("r", right, (-1.0, 0.25, -0.6)), ("l", left, (0.55, 0.15, -1.0))):
        e = lib["poses"][pn]
        Sock = HN.socket_matrix(rig, e["socket"])
        if s == "l":
            Tsl = np.eye(4); Tsl[0, 3] = -slide          # the grip slides back along the handguard
            Sock = Sock @ Tsl
        H = Sock @ np.array(e["hand_attach"][s]["matrix"], float)
        ik[s] = HN.arm_ik(arm, s, H, pole)
        C.pose_hand_anat(arm, s, e["angles"][s], C.hand_rest_angles(arm, s))
    bpy.context.view_layer.update()
    rep["ik"] = ik
    e, R = eye_world(arm)
    rep["eye"] = [round(float(v), 4) for v in e]
    return rep


def fp_camera(arm, rig, mode, pitch):
    """First-person camera (no roll): ADS = socket_ads looking along the bore (game convention,
    D11); hip = the eye looking along the view direction."""
    view = view_dir_from(pitch)
    if mode == "ads":
        p = np.array(rig.matrix_world @ rig.data.bones["socket_ads"].head_local)
    else:
        p, _ = eye_world(arm)
    up = np.array([0, 0, 1.0]) - view * view[2]
    up /= np.linalg.norm(up)
    return p, view, up


def camera_matrix(arm):
    """World matrix for a camera at the eye looking along the head's forward (-Y rest) axis."""
    e, R = eye_world(arm)
    fwd = R @ np.array([0, -1.0, 0])
    up = R @ np.array([0, 0, 1.0])
    return e, fwd, up
