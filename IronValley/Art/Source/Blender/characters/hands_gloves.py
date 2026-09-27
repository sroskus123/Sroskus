"""
hands_gloves.py -- Iron Valley production hands: tactical gloves on SK_Human_Base, the hand pose
library (Blender actions + exported clips) fitted to the real IV-7 geometry, HAND-01 / HAND-02
evidence renders and validation.  Deterministic; re-running rebuilds everything.

    python3 hands_gloves.py                                   # all stages
    python3 hands_gloves.py --stages build,textures           # glove mesh + textures only
    python3 hands_gloves.py --stages poses,validate,render,export
    python3 hands_gloves.py --stages render --only grips      # render subset (hand01, closeups, grips, black, sections)

Inputs (read only): Art/Source/Blender/characters/human_base.blend (run human_base.py first),
Art/Source/Blender/weapons/iv7_carbine.blend (the rifle and its sockets).
Outputs: hands_gloves.blend (next to this script), Art/Textures/Characters/Gloves/*,
Art/Export/FBX/SK_Hands_Gloved.fbx, SK_Human_Base_Gloved.fbx, A_Hand_Poses.fbx,
Art/Export/GLB/Hands_Gloved_Coyote.glb, Hands_Gloved_Black.glb, Hand_Poses.json (both folders),
Art/Previews/Hands/*.png + Hands_validation.json.
Spec: Art/Reference/HANDS_spec.md
"""

import argparse
import glob
import json
import math
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))

import bpy                              # noqa: E402
import numpy as np                      # noqa: E402
from mathutils import Vector, Matrix    # noqa: E402

import ivlib                            # noqa: E402
import ivchar as C                      # noqa: E402
import ivhands as HN                    # noqa: E402

IV = C.IV_ROOT
BASE_BLEND = os.path.join(HERE, "human_base.blend")
BLEND = os.path.join(HERE, "hands_gloves.blend")
RIFLE_BLEND = os.path.join(IV, "Art", "Source", "Blender", "weapons", "iv7_carbine.blend")
PREV = os.path.join(IV, "Art", "Previews", "Hands")
TEX_DIR = os.path.join(IV, "Art", "Textures", "Characters", "Gloves")
TEX_PREFIX = "T_Glove_"
FBX_DIR = os.path.join(IV, "Art", "Export", "FBX")
GLB_DIR = os.path.join(IV, "Art", "Export", "GLB")
REPORT = os.path.join(PREV, "Hands_validation.json")
POSES_JSON = "Hand_Poses.json"
ARM = "Armature"
BODY = "SK_Human_Base"
GL = {"l": "SK_Glove_L", "r": "SK_Glove_R"}
TEX_RES = 2048
RENDER_SAMPLES = 20


def log(*a):
    print("[hands]", *a, flush=True)


def rel(p):
    return os.path.relpath(p, IV)


# =============================================================================
# pose library (anatomical angles, ivchar.hand_pose_quats conventions)
# =============================================================================

def F(mcp, pip, dip, abd=0.0):
    return {"mcp": float(mcp), "pip": float(pip), "dip": float(dip), "abd": float(abd)}


def T(cmc_flex=0.0, cmc_abd=0.0, cmc_rot=0.0, mcp=0.0, ip=0.0):
    return {"cmc_flex": float(cmc_flex), "cmc_abd": float(cmc_abd), "cmc_rot": float(cmc_rot),
            "mcp": float(mcp), "ip": float(ip)}


BASE_POSES = {
    # natural resting hand (arms hanging): cascade of increasing flexion from index to little finger
    "relaxed": dict(index=F(18, 28, 10, 2), middle=F(24, 34, 12, 0), ring=F(28, 38, 14, -2),
                    pinky=F(33, 40, 14, -5), thumb=T(5, 10, 5, 12, 15)),
    # fingers straight, thumb extended beside the index (palm-flat, e.g. pushing a door)
    "open_flat": dict(index=F(0, 0, 0, 0), middle=F(0, 0, 0, 0), ring=F(0, 0, 0, 0), pinky=F(0, 0, 0, 0),
                      thumb=T(-15, 0, 0, 0, 0)),
    # maximal spread: slight MCP hyperextension, fingers abducted, thumb in radial abduction
    "spread": dict(index=F(-5, 0, 0, 12), middle=F(-5, 0, 0, 2), ring=F(-5, 0, 0, -10), pinky=F(-5, 0, 0, -22),
                   thumb=T(-35, -5, 0, 0, -5)),
}
# slight fan (index radial, ring / little ulnar) so neighbouring fingers press together instead of
# overlapping (bare-skin finger-finger overlap 5.0 -> 3.2 mm, measured with ivchar.hand_contact_metrics)
FIST_START = dict(index=F(90, 100, 70, 4), middle=F(90, 100, 70, 0), ring=F(90, 100, 70, -3), pinky=F(90, 100, 70, -6))
TIP_PALM_MAX = 0.0010          # m: fingertip-to-palm penetration allowed in the full fist (skin contact)


# =============================================================================
# build: gloves
# =============================================================================

def open_base():
    bpy.ops.wm.open_mainfile(filepath=BASE_BLEND)
    return bpy.data.objects[ARM], bpy.data.objects[BODY]


def build():
    t0 = time.time()
    arm, body = open_base()
    C.reset_pose(arm)
    C.clear_correctives(body)
    col = ivlib.collection("Gloves")
    rep = {}
    gl, rep["glove_l"] = HN.build_glove(arm, body, "l", col, GL["l"])
    fr = HN.load_fields(gl)
    rep["uv"] = HN.glove_uv(gl, fr)
    rep["uv"].update(HN.uv_stats(gl, TEX_RES))
    gr = HN.mirror_object(gl, GL["r"], col)
    for g in (gl, gr):
        g.parent = arm
        m = g.modifiers.new("Armature", 'ARMATURE')
        m.object = arm
        g.data.materials.clear()
        g.data.materials.append(C.clay_material("M_Glove_Clay", color=(0.25, 0.17, 0.10), rough=0.8))
    rep["glove_r"] = {"mirrored_from": GL["l"], "vertices": len(gr.data.vertices)}
    # gloved body variant: skin hidden under the glove (more than 2.5 cm inside the cuff) removed
    rep["gloved_body"] = make_gloved_body(arm, body, col)
    rep["build_seconds"] = round(time.time() - t0, 1)
    ivlib.deselect_all()
    bpy.ops.wm.save_as_mainfile(filepath=BLEND, compress=True)
    log("built", json.dumps(rep))
    return rep


def make_gloved_body(arm, body, col):
    """SK_Human_Base_Gloved: a copy of the body without the skin that the gloves cover (faces
    whose vertices all lie inside the glove region and more than 2.5 cm distal of the cuff
    opening), so nothing can poke through the gloves in the engine.  Shape keys are kept."""
    ob = body.copy()
    ob.data = body.data.copy()
    ob.name = BODY + "_Gloved"
    ob.data.name = ob.name
    col.objects.link(ob)
    kill = set()
    for s in ("l", "r"):
        vids, faces, _, _ = HN.glove_region(arm, body, s, HN.GLOVE_DESIGN["cuff_len"] - 0.025)
        vs = set(vids.tolist())
        for p in body.data.polygons:
            if all(v in vs for v in p.vertices):
                kill.add(p.index)
    import bmesh
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bm.faces.ensure_lookup_table()
    bmesh.ops.delete(bm, geom=[bm.faces[i] for i in sorted(kill)], context='FACES')
    bm.to_mesh(ob.data)
    bm.free()
    ob.data.update()
    return {"faces_removed": len(kill), "vertices": len(ob.data.vertices), "faces": len(ob.data.polygons)}


# =============================================================================
# textures
# =============================================================================

def textures():
    bpy.ops.wm.open_mainfile(filepath=BLEND)
    arm = bpy.data.objects[ARM]
    C.reset_pose(arm)
    gl = bpy.data.objects[GL["l"]]
    paths, st = HN.glove_textures(gl, arm, "l", TEX_RES, TEX_DIR, TEX_PREFIX)
    mats = {}
    for pal in ("Coyote", "Black"):
        mats[pal] = ivlib.export_material(f"M_Glove_{pal}", paths[f"{pal}_BaseColor"], paths[f"{pal}_ORM"], paths["Normal"])
    for s in ("l", "r"):
        g = bpy.data.objects[GL[s]]
        g.data.materials.clear()
        g.data.materials.append(mats["Coyote"])
    bpy.ops.wm.save_as_mainfile(filepath=BLEND, compress=True, relative_remap=True)
    st["files"] = {k: rel(v) for k, v in paths.items()}
    log("textures", json.dumps(st))
    return st


# =============================================================================
# props: IV-7 (appended read-only) and a PROXY pistol (fitting / evidence only)
# =============================================================================

PISTOL = dict(rake_deg=18.0, grip_len=0.108, grip_depth=0.050, grip_width=0.030, grip_top=0.040,
              slide_len=0.185, slide_h=0.030, slide_w=0.026, bore_z=0.066, trigger_x=0.052, trigger_z=0.028,
              guard_depth=0.034)        # trigger guard bottom below the grip top (inner opening 2.6 cm)


def load_props(with_rifle=True, with_pistol=True):
    props = {}
    if with_rifle:
        col = ivlib.collection("Props_IV7")
        rig, parts = HN.append_weapon(RIFLE_BLEND, into=col)
        props["rifle"] = dict(rig=rig, parts=parts)
    if with_pistol:
        props["pistol"] = dict(parts=build_proxy_pistol(), rig=None)
    return props


def build_proxy_pistol():
    """Generic compact 9 mm-class pistol PROXY (Iron Valley has no pistol asset yet): raked grip
    (5.0 x 3.0 cm section, 18 deg), frame, slide, trigger guard, trigger.  Origin = grip hold
    point, muzzle +X, top +Z, right side -Y (weapon convention).  Only used to fit and show the
    two-handed pistol grip; it is not exported."""
    P = PISTOL
    col = ivlib.collection("Props_PistolProxy")
    r = math.radians(P["rake_deg"])
    up = np.array([math.sin(r), 0.0, math.cos(r)])
    fw = np.array([math.cos(r), 0.0, -math.sin(r)])
    parts = []
    # grip: superellipse sections along the raked axis
    secs = []
    for t in np.linspace(-P["grip_top"], P["grip_len"] - P["grip_top"], 9):
        k = 1.0 - 0.06 * max(0.0, t) / P["grip_len"]
        pts = ivlib.superellipse(0.5 * P["grip_depth"] * k, 0.5 * P["grip_width"] * k, 3.2, 28)
        c = -up * t
        secs.append([tuple(c + fw * a + np.array([0, 1.0, 0]) * b) for a, b in pts])
    g = ivlib.loft("PX_Grip", secs, cap=True, col=col)
    parts.append(g)
    top = up * P["grip_top"]
    fr = ivlib.box("PX_Frame", -0.030, 0.080, -0.0135, 0.0135, top[2] - 0.004, P["bore_z"] - 0.012, col=col)
    parts.append(fr)
    sl = ivlib.box("PX_Slide", -0.040, P["slide_len"] - 0.040, -0.5 * P["slide_w"], 0.5 * P["slide_w"],
                   P["bore_z"] - 0.013, P["bore_z"] + P["slide_h"] - 0.013, col=col)
    parts.append(sl)
    # trigger guard: a swept square tube, U-shaped under the frame
    gd = P["guard_depth"]
    path = [(0.022, 0, top[2] - 0.002), (0.030, 0, top[2] - gd), (0.078, 0, top[2] - gd),
            (0.082, 0, top[2] - 0.012), (0.080, 0, top[2] + 0.002)]
    sec = [(-0.003, -0.004), (0.003, -0.004), (0.003, 0.004), (-0.003, 0.004)]
    tg = ivlib.sweep("PX_TriggerGuard", sec, path, side=(0.0, 1.0, 0.0), cap=True, col=col)
    parts.append(tg)
    trg = ivlib.box("PX_Trigger", P["trigger_x"] - 0.003, P["trigger_x"] + 0.003, -0.004, 0.004,
                    P["trigger_z"] - 0.012, top[2] + 0.004, col=col)
    parts.append(trg)
    mat = C.clay_material("M_PistolProxy", color=(0.035, 0.035, 0.038), rough=0.5)
    for o in parts:
        o.data.materials.append(mat)
        for p in o.data.polygons:
            p.use_smooth = False
    return parts


def collider_of(objs, extra=()):
    return HN.Collider([(o.name,) + HN.eval_world_mesh(o) for o in objs] + list(extra))


# =============================================================================
# fitting
# =============================================================================

def open_pose():
    p = {f: F(0, 5, 3, 0) for f in C.FINGERS4}
    p["thumb"] = T(-45, 10, 0, 5, 5)
    return p


def place_diagonal(model, k, pose, coll, axis_up, cdir, axis_origin, height_anchor, height, yaw=0.0,
                   half=0.018, sel=None, tilt=0.0):
    """Power-grasp placement: the object axis (axis_up, through axis_origin) runs diagonally
    across the palm from the hypothenar heel to the thumb-index web (web towards +axis_up); the
    palm faces the object from direction `cdir` (object axis -> palm), rotated by `yaw` about the
    axis; the rest-space anchor `height_anchor` ends at `height` along the axis; finally the hand
    moves along -cdir until the palm / heel / thenar touch (0.5 mm gap).  Returns H."""
    arm, s = model.arm, model.s
    w, d, r, p = HN.hand_frame(arm, s)
    web = HN.hand_anchor(model, k, "web")
    heel = HN.hand_anchor(model, k, "heel")
    anc = HN.hand_anchor(model, k, height_anchor)
    ug = (web - heel); ug /= np.linalg.norm(ug)
    axis_pt = 0.5 * (web + heel) + p * half
    up = np.asarray(axis_up, float); up /= np.linalg.norm(up)
    from scipy.spatial.transform import Rotation as Rot
    cd = Rot.from_rotvec(up * math.radians(yaw)).as_matrix() @ np.asarray(cdir, float)
    cd -= up * (cd @ up); cd /= np.linalg.norm(cd)
    mp = -p - ug * (-p @ ug); mp /= np.linalg.norm(mp)
    A = np.stack([ug, mp, np.cross(ug, mp)], 1)
    B = np.stack([up, cd, np.cross(up, cd)], 1)
    R = B @ A.T
    if np.linalg.det(R) < 0:           # the right hand's frame is mirrored: keep a proper rotation
        A = np.stack([ug, mp, -np.cross(ug, mp)], 1)
        R = B @ A.T
    if tilt:
        R = Rot.from_rotvec(cd * math.radians(tilt)).as_matrix() @ R
    Hr = model.R[model.hand]
    tp = (R @ (anc - axis_pt)) @ up
    H = np.eye(4)
    H[:3, :3] = R @ Hr[:3, :3]
    H[:3, 3] = R @ (Hr[:3, 3] - axis_pt) + np.asarray(axis_origin, float) + up * (height - tp)
    if sel is None:
        sel = model.verts_of(k, [f"hand_{s}", f"thumb_01_{s}", f"lowerarm_{s}", f"lowerarm_twist_01_{s}"], 0.5)
    return HN.translate_to_contact(model, k, pose, H, coll, -cd, sel, gap=0.0005, max_dist=0.06)


def place_anchor(model, k, pose, coll, web_target, mcp_target, fwd_hint, roll, sel=None, mcp_bone="index"):
    """Pistol-grip placement: the thumb-index web crotch sits on `web_target` (the back strap just
    below the tang), the `mcp_bone` MCP joint towards `mcp_target` (the middle MCP on the grip's
    side just under the trigger guard, so the middle finger wraps the front strap below it), the
    fingers (hand d axis) as close to `fwd_hint` as the roll allows (+ `roll` deg about the
    web -> MCP axis); then the hand moves along its palm normal until the palm touches."""
    from scipy.spatial.transform import Rotation as Rot
    arm, s = model.arm, model.s
    w, d, r, p = HN.hand_frame(arm, s)
    web = HN.hand_anchor(model, k, "web")
    imcp = HN.bone_rest_frames(arm)[f"{mcp_bone}_01_{s}"]["H"]
    a_h = (imcp - web) / np.linalg.norm(imcp - web)
    a_w = np.asarray(mcp_target, float) - np.asarray(web_target, float)
    a_w /= np.linalg.norm(a_w)
    R1 = Rot.align_vectors([a_w], [a_h])[0].as_matrix()
    dn = R1 @ d
    tgt = np.asarray(fwd_hint, float); tgt = tgt - a_w * (tgt @ a_w); tgt /= np.linalg.norm(tgt)
    dp = dn - a_w * (dn @ a_w); dp /= np.linalg.norm(dp)
    ang = math.atan2(np.cross(dp, tgt) @ a_w, dp @ tgt) + math.radians(roll)
    R = Rot.from_rotvec(a_w * ang).as_matrix() @ R1
    Hr = model.R[model.hand]
    H = np.eye(4)
    H[:3, :3] = R @ Hr[:3, :3]
    H[:3, 3] = R @ (Hr[:3, 3] - web) + np.asarray(web_target, float)
    if sel is None:
        sel = model.verts_of(k, [f"hand_{s}", f"thumb_01_{s}", f"lowerarm_{s}", f"lowerarm_twist_01_{s}"], 0.5)
    return HN.translate_to_contact(model, k, pose, H, coll, R @ p, sel, gap=0.0005, max_dist=0.04)


def pistol_grip_search(model, coll, web_target, mcp_targets, fwd_hint, grip_parts, trigger_point=None,
                       along_parts=None, rolls=(15.0, 30.0, 45.0, 60.0, 75.0), mcp_bone="middle"):
    """Search roll / MCP target of the anchor placement; per candidate the middle / ring / pinky
    curl to contact and the index is fitted (straight along the frame, or pad onto the trigger);
    a candidate whose middle / ring / pinky touch anything but the grip (e.g. the trigger guard)
    is penalised; the best candidate is wrap-optimised.  Returns (H, pose, report)."""
    k = 0
    best, tried = None, []
    for T2 in mcp_targets:
        for roll in rolls:
            pose = open_pose()
            H = place_anchor(model, k, pose, coll, web_target, T2, fwd_hint, roll, mcp_bone=mcp_bone)
            close_coupled(model, k, pose, H, coll, ["middle", "ring", "pinky"])
            sn = HN.snugness(model, k, pose, H, coll, ["middle", "ring", "pinky"])
            nfor, wfor = foreign_contact(model, k, pose, H, coll, ["middle", "ring", "pinky"], grip_parts)
            if trigger_point is not None:
                ir = fit_index(model, k, pose, H, coll, "trigger", trigger_part=trigger_point)
                ipen = abs(ir["terms"].get("_gap", 0.03) * 1000 - 0.6) * 2 + max(0.0, -ir["terms"]["_min_sd"] * 1000 - 0.3) * 10
            else:
                ir = fit_index(model, k, pose, H, coll, "straight", along_parts=along_parts)
                ipen = ir["terms"].get("_gap", 0.05) * 1000 * 0.5 + ir["terms"]["_dir_deg"] * 0.2
            sc = -sn * 1000 - ipen - 4.0 * nfor - 2.0 * wfor * 1000
            tried.append({"mcp_target_cm": [round(v * 100, 2) for v in T2], "roll_deg": roll,
                          "snugness_mm": round(sn * 1000, 2), "index_penalty": round(ipen, 2),
                          "fingers_touching_other_parts": nfor, "score": round(sc, 2)})
            if best is None or sc > best[0]:
                best = (sc, H, pose, ir, T2, roll)
    sc, H, pose, ir, T2, roll = best
    wr = {f: HN.wrap_finger(model, k, pose, H, coll, f, lim=FIST_LIMITS[f]) for f in ("middle", "ring", "pinky")}
    return H, pose, {"placement": f"web crotch on the back strap below the tang, {mcp_bone} MCP on the grip side, roll searched",
                     "mcp_target_cm": [round(v * 100, 2) for v in T2], "roll_deg": roll,
                     "snugness_mm": round(HN.snugness(model, k, pose, H, coll, ["middle", "ring", "pinky"]) * 1000, 2),
                     "wrap": wr, "index": ir, "candidates": tried}


def place_frame(model, k, pose, coll, d_t, r_t, pivot_name, pivot_target, contact_dir, sel=None):
    """Hand placement from an explicit target frame: the rest hand frame (d = wrist -> middle MCP,
    r = radial) is rotated onto (d_t, r_t) (orthonormalised; the palm normal follows from the
    hand's handedness), the rest anchor `pivot_name` goes to `pivot_target`, then the hand moves
    along `contact_dir` until the palm / thumb base touch (or backs off if penetrating)."""
    arm, s = model.arm, model.s
    w, d, r, p = HN.hand_frame(arm, s)
    def frame(a, b):
        a = np.asarray(a, float) / np.linalg.norm(a)
        b = np.asarray(b, float) - a * (a @ np.asarray(b, float))
        b /= np.linalg.norm(b)
        c = np.cross(a, b) if s == "l" else np.cross(b, a)
        return np.stack([a, b, c], 1)
    A = frame(d, r)
    B = frame(d_t, r_t)
    R = B @ A.T
    piv = HN.hand_anchor(model, k, pivot_name) if isinstance(pivot_name, str) else np.asarray(pivot_name, float)
    Hr = model.R[model.hand]
    H = np.eye(4)
    H[:3, :3] = R @ Hr[:3, :3]
    H[:3, 3] = R @ (Hr[:3, 3] - piv) + np.asarray(pivot_target, float)
    if sel is None:
        sel = model.verts_of(k, [f"hand_{s}", f"thumb_01_{s}", f"lowerarm_{s}", f"lowerarm_twist_01_{s}"], 0.5)
    return HN.translate_to_contact(model, k, pose, H, coll, contact_dir, sel, gap=0.0005, max_dist=0.05), B[:, 2]


def trigger_contact_point(coll, part, above_tip=0.010):
    """Front face of the trigger blade `above_tip` above its tip (where the distal pad presses) and
    the pad target 0.6 mm in front of it."""
    tb = [p_ for p_ in coll.parts if p_["name"] == part][0]
    probe = Vector((float(tb["co"][:, 0].max()) + 0.02, float(tb["co"][:, 1].mean()), float(tb["co"][:, 2].min()) + above_tip))
    loc, nrm, _, _ = tb["bvh"].find_nearest(probe)
    return np.array(loc) + np.array(nrm) * 0.0006


def index_reach(model, k, pose, H, coll, target, max_pen=0.0010):
    """Can the index pad reach `target` from this hand placement with anatomically coupled angles
    (DIP = 0.6 PIP) without the finger sinking > max_pen into the weapon?  Coarse grid; returns
    (pad-to-target distance m, [mcp, abd, pip, dip])."""
    import itertools
    s = model.s
    masks = HN.finger_masks(model, k, s)
    fr = HN.load_fields(model.meshes[k]["ob"])
    pad = masks[("index", 3)] & (fr["z_palm"] > 0.5)
    mv = masks[("index", 1)]
    p2 = json.loads(json.dumps(pose))
    best = (1.0, None)
    for mcp, abd, pip in itertools.product(range(0, 81, 10), (-15.0, -7.5, 0.0, 7.5, 15.0), range(0, 101, 10)):
        p2["index"] = F(mcp, pip, 0.6 * pip, abd)
        Sm = model.pose(p2, H)
        err = float(np.linalg.norm(model.skin(k, Sm, pad) - target, axis=1).min())
        if err < best[0]:
            sd, _ = coll.signed(model.skin(k, Sm, mv), 0.03)
            if -float(sd.min()) <= max_pen:
                best = (err, [mcp, abd, pip, 0.6 * pip])
    return best


def pistol_grip_frame_search(model, coll, ga, fwd, side, mcp_ref, grip_parts, trigger_point=None,
                             along_parts=None, yaws=(-5.0, 0.0, 5.0), tilts=(-16.0, -10.0),
                             fwd_offsets=(-0.005, 0.0, 0.005, 0.010), heights=(-0.004, 0.0, 0.004, 0.008, 0.012),
                             fingers=("middle", "ring", "pinky"), index_mode="auto", reach=None):
    """Pistol-grip placement by the grip's anatomy.  The palm (2nd-5th metacarpals) lies on the
    grip's side, the knuckle row along the grip axis `ga` (hand radial axis r = ga, index on top),
    the straight fingers along `fwd` (perpendicular to ga) yawed by `yaw` about ga (+ = towards
    the grip centre, i.e. the forearm arrives from behind and outside), the knuckle row tilted by
    `tilt` about the palm normal.  The middle MCP joint starts at `mcp_ref` (on the grip's side just
    under the trigger guard) shifted by fwd_offset along fwd and height along ga, well outside the
    grip, and the hand moves towards the grip (palm normal) until the palm touches.  The thumb
    metacarpal then wraps the back strap (fit_thumb), which brings the thumb-index web onto it.
    Per candidate the fingers curl to contact and the index is fitted; fingers touching anything
    but `grip_parts` (e.g. the trigger guard) are penalised.  Returns (H, pose, report)."""
    from scipy.spatial.transform import Rotation as Rot
    k = 0
    s = model.s
    ga = np.asarray(ga, float) / np.linalg.norm(ga)
    f0 = np.asarray(fwd, float) - ga * (ga @ np.asarray(fwd, float))
    f0 /= np.linalg.norm(f0)
    side = np.asarray(side, float) / np.linalg.norm(side)
    sgn = 1.0 if (np.cross(ga, f0) @ side) > 0 else -1.0        # yaw sense that turns the fingers towards the grip
    RF = HN.bone_rest_frames(model.arm)
    mcp_rest = RF[f"middle_01_{s}"]["H"]
    row_rest = RF[f"index_01_{s}"]["H"] - RF[f"pinky_01_{s}"]["H"]
    grip_only = HN.Collider([(p_["name"], p_["co"], p_["tris"]) for p_ in coll.parts if p_["name"] in grip_parts])
    fmask = model.verts_of(k, [f"hand_{s}"] + [f"{f}_0{i}_{s}" for f in fingers for i in (1, 2, 3)], 0.5)
    # high grip: the top finger of the wrap (middle) sits right under the trigger guard
    other = HN.Collider([(p_["name"], p_["co"], p_["tris"]) for p_ in coll.parts if p_["name"] not in grip_parts])
    top_mask = model.verts_of(k, [f"{fingers[0]}_01_{s}", f"{fingers[0]}_02_{s}"], 0.5)
    best, tried = None, []
    for yaw in yaws:
        for tilt in tilts:
            for fo in fwd_offsets:
                for hz in heights:
                    Ry = Rot.from_rotvec(ga * math.radians(yaw) * sgn).as_matrix()
                    d_t = Ry @ f0
                    pn = np.cross(ga, d_t) if (np.cross(ga, d_t) @ side) > 0 else -np.cross(ga, d_t)
                    Rt = Rot.from_rotvec(pn * math.radians(tilt)).as_matrix()
                    d_t, r_t = Rt @ d_t, Rt @ ga
                    start = np.asarray(mcp_ref, float) + f0 * fo + ga * hz - pn * 0.03
                    pose = open_pose()
                    H, _ = place_frame(model, k, pose, coll, d_t, r_t, mcp_rest, start, pn)
                    close_coupled(model, k, pose, H, coll, list(fingers))
                    sn = HN.snugness(model, k, pose, H, grip_only, list(fingers))      # wrap on the GRIP only
                    nfor, wfor = foreign_contact(model, k, pose, H, coll, list(fingers), grip_parts)
                    Rw = H[:3, :3] @ np.linalg.inv(model.R[model.hand][:3, :3])
                    row = Rw @ row_rest
                    row_dev = math.degrees(math.acos(abs(float(row @ ga)) / np.linalg.norm(row)))
                    Sm_ = model.pose(pose, H)
                    fsd, _ = coll.signed(model.skin(k, Sm_, fmask), 0.03)
                    fpen = max(0.0, -float(fsd.min()))                                 # fingers / palm inside the weapon
                    clear = float(other.signed(model.skin(k, Sm_, top_mask), 0.03)[0].min())   # top finger to the guard
                    if "index" in fingers:
                        ir, ipen = None, 0.0                      # the index wraps with the others
                    elif trigger_point is not None:
                        ir = fit_index(model, k, pose, H, coll, "trigger", trigger_part=trigger_point)
                        ipen = abs(ir["terms"].get("_gap", 0.03) * 1000 - 0.6) * 2 + max(0.0, -ir["terms"]["_min_sd"] * 1000 - 0.3) * 10
                    else:
                        ir = fit_index(model, k, pose, H, coll, "straight", along_parts=along_parts)
                        ipen = (abs(ir["terms"].get("_gap", 0.05) * 1000 - 0.8) * 0.5 + ir["terms"]["_dir_deg"] * 0.2
                                + 10.0 * max(-ir["terms"]["_min_sd"] * 1000 - 0.3, 0.0))
                    sc = (-sn * 1000 - ipen - 4.0 * nfor - 2.0 * wfor * 1000 - 0.2 * max(row_dev - 10.0, 0.0)
                          - 5.0 * max(fpen * 1000 - 1.0, 0.0) - 0.5 * max(clear * 1000 - 3.0, 0.0))
                    rerr = None
                    if reach is not None and sc > (best[0] - 12.0 if best else -1e9):
                        # the same placement must also let the index pad reach the trigger face
                        rerr, _ = index_reach(model, k, pose, H, coll, reach)
                        sc -= 1.0 * max(rerr * 1000 - 1.5, 0.0)
                    tried.append({"yaw_deg": yaw, "tilt_deg": tilt, "fwd_offset_mm": round(fo * 1000, 1),
                                  "knuckle_row_vs_grip_axis_deg": round(row_dev, 1),
                                  "penetration_mm": round(fpen * 1000, 2),
                                  "top_finger_to_guard_mm": round(clear * 1000, 2),
                                  "trigger_reach_error_mm": None if rerr is None else round(rerr * 1000, 2),
                                  "height_mm": round(hz * 1000, 1), "snugness_mm": round(sn * 1000, 2),
                                  "index_penalty": round(ipen, 2), "fingers_touching_other_parts": nfor,
                                  "score": round(sc, 2)})
                    if best is None or sc > best[0]:
                        best = (sc, H, pose, ir, tried[-1])
    sc, H, pose, ir, cand = best
    wr = {f: HN.wrap_finger(model, k, pose, H, coll, f, lim=FIST_LIMITS[f]) for f in fingers}
    return H, pose, dict({"placement": "palm on the grip side, knuckle row along the grip axis, middle MCP under the "
                                       "trigger guard; yaw / tilt / forward offset / height searched"}, **cand,
                         snugness_after_wrap_mm=round(HN.snugness(model, k, pose, H, grip_only, list(fingers)) * 1000, 2),
                         wrap=wr, index=ir, candidates=tried)


def fit_thumb(model, k, pose, H, coll, direction, parts=None, starts=None, bounds=None):
    s = model.s
    fr = HN.load_fields(model.meshes[k]["ob"])
    masks = HN.finger_masks(model, k, s)
    palmar = fr["z_palm"] > 0.2
    moving = masks[("thumb", 1)] & ~masks[("index", 1)]
    # the thumb must not pass through the (already posed) fingers either: they join the collider
    # (contact is still only sought on the weapon parts)
    own = HN.self_collider(model, k, pose, H, "thumb", ("index", "middle", "ring", "pinky"),
                           exclude_near=np.nonzero(masks[("thumb", 1)])[0], near_dist=0.010)
    best = None
    for x0 in (starts or ([20, 0, 0, 10, 10], [40, 10, 10, 20, 20], [10, 20, 20, 10, 30], [50, -10, 0, 20, 10])):
        p2 = json.loads(json.dumps(pose))
        rep = HN.fit_digit(model, k, p2, H, coll, "thumb", ["cmc_flex", "cmc_abd", "cmc_rot", "mcp", "ip"],
                           bounds or [(-45, 70), (-25, 50), (-25, 35), (0, 55), (0, 70)], moving,
                           contact=masks[("thumb", 3)] & palmar, contact_gap=0.0008, contact_parts=parts,
                           direction=(np.asarray(direction) / np.linalg.norm(direction), f"thumb_02_{s}", f"thumb_03_{s}"),
                           w_dir=20.0, x0=x0, self_coll=own)
        c = sum(v for kk, v in rep["terms"].items() if not kk.startswith("_"))
        if best is None or c < best[0]:
            best = (c, p2, rep)
    pose.clear()
    pose.update(best[1])
    return best[2]


# trigger discipline: the straight index lies along the receiver side ABOVE the trigger guard,
# rising ~17 deg from its MCP (which sits at the guard's height) -- world direction (weapon axes
# coincide with world axes for the IV-7 at rest and for the proxy pistol)
STRAIGHT_INDEX_DIR = np.array([1.0, 0.0, 0.30])


def fit_index(model, k, pose, H, coll, mode, trigger_point=None, trigger_part="Trigger", along_parts=None, target=None):
    """mode 'straight': index along the frame (trigger discipline); 'trigger': pad on the trigger."""
    s = model.s
    masks = HN.finger_masks(model, k, s)
    if mode == "straight":
        return HN.fit_digit(model, k, pose, H, coll, "index", ["mcp", "abd", "pip", "dip"],
                            [(-10, 60), (-25, 20), (0, 20), (0, 15)], masks[("index", 1)],
                            contact=masks[("index", 2)], contact_gap=0.0008, contact_parts=along_parts,
                            direction=(STRAIGHT_INDEX_DIR / np.linalg.norm(STRAIGHT_INDEX_DIR), f"index_01_{s}", f"index_03_{s}"),
                            w_dir=40.0)
    # trigger: the distal phalanx pad resting on the trigger (contact <= 0.6 mm), finger clear of
    # the trigger guard / receiver.  Coarse grid (pad-to-trigger distance, no penetration) + Powell.
    import itertools
    fr = HN.load_fields(model.meshes[k]["ob"])
    pad = masks[("index", 3)] & (fr["z_palm"] > 0.5)
    tpart = [p_ for p_ in coll.parts if p_["name"] == trigger_part][0]
    tb = tpart["bvh"]
    mv = masks[("index", 1)]
    g = None
    if target is not None:
        # start from the coupled-angle grid that brings the pad onto the trigger contact point
        err, ang = index_reach(model, k, pose, H, coll, target)
        if ang is not None:
            g = (err, ang)
    for mcp, abd, pip, dip in (itertools.product(range(10, 91, 10), (-15, -5, 5, 15), range(0, 101, 15), range(0, 71, 15))
                               if g is None else ()):
        if HN.coupling_penalty(pip, dip, mcp) > 0:          # anatomically coupled candidates only
            continue
        pose["index"] = F(mcp, pip, dip, abd)
        Sm = model.pose(pose, H)
        P = model.skin(k, Sm, pad)
        dmin = min(tb.find_nearest(Vector(tuple(map(float, q))))[3] for q in P[::3])
        if dmin < 0.012:
            sd, _ = coll.signed(model.skin(k, Sm, mv), 0.03)
            sc = dmin + max(0.0, -float(sd.min()) - 0.0003) * 5
            if g is None or sc < g[0]:
                g = (sc, [mcp, abd, pip, dip])
    if g is None:
        g = (1.0, [40, 0, 40, 20])
    rep = HN.fit_digit(model, k, pose, H, coll, "index", ["mcp", "abd", "pip", "dip"],
                       [(-5, 90), (-20, 20), (0, 105), (0, 75)], mv, contact=pad, contact_gap=0.0006,
                       contact_parts=[trigger_part], x0=g[1], w_contact=6e4)
    rep["grid_start"] = {"score_m": round(g[0], 5), "angles": g[1]}
    return rep


# closing limits per finger: at most the tuned full fist (set by poses_stage from tune_fist), so
# a finger that misses the object stops where the fist stops instead of curling into the palm
FIST_LIMITS = {f: {"mcp": (-5.0, 92.0), "pip": (0.0, 100.0), "dip": (0.0, 70.0)} for f in C.FINGERS4}


def set_fist_limits(fist):
    for f in C.FINGERS4:
        FIST_LIMITS[f] = {"mcp": (-5.0, 92.0), "pip": (0.0, float(fist[f]["pip"])), "dip": (0.0, float(fist[f]["dip"]))}


def close_coupled(model, k, pose, H, coll, fingers):
    masks = HN.finger_masks(model, k, model.s)
    return {f: HN.close_finger_coupled(model, k, pose, H, coll, f, masks=masks,
                                       limits={kk: v[1] for kk, v in FIST_LIMITS[f].items()}) for f in fingers}


def foreign_contact(model, k, pose, H, coll, fingers, allowed, thr=0.001):
    """How many of `fingers` touch (sd < thr) a collider part NOT in `allowed`, and the deepest
    such penetration (m)."""
    names = [p_["name"] for p_ in coll.parts]
    bad_ids = [i for i, nm in enumerate(names) if nm not in allowed]
    S = model.pose(pose, H)
    masks = HN.finger_masks(model, k, model.s)
    n, worst = 0, 0.0
    for f in fingers:
        sd, pi = coll.signed(model.skin(k, S, masks[(f, 1)]), 0.03)
        bad = (sd < thr) & np.isin(pi, bad_ids)
        if bad.any():
            n += 1
            worst = max(worst, float(-sd[bad].min()))
    return n, worst


def rifle_frames(rig):
    up = np.array([math.sin(math.radians(22)), 0, math.cos(math.radians(22))])
    return up


def grip_score(model, k, pose, H, coll, grip_part, fingers=("middle", "ring", "pinky")):
    """Quality of a closed power grasp: every finger's segments touch only `grip_part` (1 point),
    fingers wrap (sum of flexion), no finger at the MCP limit without a contact."""
    names = [p["name"] for p in coll.parts]
    S = model.pose(pose, H)
    masks = HN.finger_masks(model, k, model.s)
    sc = 0.0
    for f in fingers:
        P = model.skin(k, S, masks[(f, 1)])
        sd, pi = coll.signed(P, 0.03)
        touch = {names[i] for i in np.unique(pi[sd < 0.0015]) if i >= 0}
        sc += 1.0 if (touch and touch <= set(grip_part)) else -1.0
        sc += min(pose[f]["mcp"] + pose[f]["pip"] + pose[f]["dip"], 220.0) / 200.0
    return sc


def power_grasp(model, coll, up, cdir, origin, anchor, heights, yaws, tilts, fingers, grip_parts,
                half=0.018, index_fit=None, top=3, allowed=None):
    """Search palm height / yaw / tilt of a diagonal power grasp: each candidate is placed and the
    fingers curl (coupled) to contact; the `top` snuggest candidates get the full wrap
    optimisation (all segments on the object) and the optional index fit; best total wins."""
    k = 0
    cands = []
    for h in heights:
        for yaw in yaws:
            for tilt in tilts:
                pose = open_pose()
                H = place_diagonal(model, k, pose, coll, up, cdir, origin, anchor, h, yaw=yaw, half=half, tilt=tilt)
                close_coupled(model, k, pose, H, coll, fingers)
                sn = HN.snugness(model, k, pose, H, coll, fingers)
                if allowed is not None:
                    nf, wf = foreign_contact(model, k, pose, H, coll, fingers, allowed)
                    sn += 0.004 * nf + 2.0 * wf
                cands.append((sn, h, yaw, tilt, H, pose))
    cands.sort(key=lambda c: c[0])
    best = None
    for sn, h, yaw, tilt, H, pose in cands[:top]:
        wr = {f: HN.wrap_finger(model, k, pose, H, coll, f, lim=FIST_LIMITS[f]) for f in fingers}
        sn2 = HN.snugness(model, k, pose, H, coll, fingers)
        sc = -sn2 * 1000.0
        if allowed is not None:
            nf, wf = foreign_contact(model, k, pose, H, coll, fingers, allowed)
            sc -= 4.0 * nf + 2000.0 * wf
        ir = None
        if index_fit is not None:
            ir, ipen = index_fit(model, k, pose, H, coll)
            sc -= ipen
        if best is None or sc > best[0]:
            best = (sc, H, pose, {"height_mm": round(h * 1000, 1), "yaw_deg": yaw, "tilt_deg": tilt,
                                  "snugness_mm": round(sn2 * 1000, 2), "wrap": wr, "index": ir})
    rep = best[3]
    rep["candidates"] = [{"height_mm": round(c[1] * 1000, 1), "yaw_deg": c[2], "tilt_deg": c[3],
                          "snugness_mm": round(c[0] * 1000, 2)} for c in cands]
    return best[1], best[2], rep


def trigger_press(model, k, pose, H, coll, trigger_point, re_wrap=("middle", "ring", "pinky"), wrap_parts=None,
                  thumb_dir=None, thumb_parts=None, max_rot=0.26, max_move=0.025):
    """Index pad onto the trigger face: coarse grid of the index angles, then a joint refinement of
    the hand placement (<= 25 mm, 15 deg; palm pads may compress <= 1.8 mm on the grip) and the
    index angles; then the other fingers re-wrap and the thumb is re-fitted."""
    s = model.s
    fr = HN.load_fields(model.meshes[k]["ob"])
    masks = HN.finger_masks(model, k, s)
    co = model.meshes[k]["co"]
    b3 = HN.bone_rest_frames(model.arm)[f"index_03_{s}"]
    pad_pt = b3["H"] + b3["Y"] * b3["L"] * 0.45
    cand = np.nonzero(masks[("index", 3)] & (fr["z_palm"] > 0.5))[0]
    vi = int(cand[np.argmin(np.linalg.norm(co[cand] - pad_pt, axis=1))])
    palm = model.verts_of(k, [f"hand_{s}", f"thumb_01_{s}"], 0.5)
    sel = palm | masks[("index", 1)]
    # coarse grid of the index angles for the current hand placement
    import itertools
    best = None
    for mcp, abd, pip, dip in itertools.product(range(0, 91, 10), (-20, -10, 0, 10, 20), range(0, 101, 20), range(0, 71, 20)):
        if HN.coupling_penalty(pip, dip, mcp) > 0:
            continue
        pose["index"] = F(mcp, pip, dip, abd)
        q = model.skin(k, model.pose(pose, H))[vi]
        err = float(np.linalg.norm(q - trigger_point))
        if best is None or err < best[0]:
            best = (err, mcp, abd, pip, dip)
    pose["index"] = F(best[1], best[3], best[4], best[2])
    H2, rr = HN.refine_hand_and_digit(model, k, pose, H, coll, "index", ["mcp", "abd", "pip", "dip"],
                                      [(-5, 80), (-20, 20), (0, 100), (0, 75)], trigger_point, vi, sel,
                                      max_rot=max_rot, max_move=max_move, soft=palm)
    rr["grid_start"] = {"error_mm": round(best[0] * 1000, 1), "mcp": best[1], "abd": best[2], "pip": best[3], "dip": best[4]}
    rr["pad_vertex"] = vi
    rep = {"index_trigger": rr}
    rep["wrap"] = {f: HN.wrap_finger(model, k, pose, H2, coll, f, lim=FIST_LIMITS[f]) for f in re_wrap}
    if thumb_dir is not None:
        rep["thumb"] = fit_thumb(model, k, pose, H2, coll, thumb_dir, parts=thumb_parts)
    return H2, rep


def fit_rifle_grip(model, coll, rig, trigger=False, base=None):
    """Right hand on the IV-7 pistol grip (hold point = socket_firing_hand = weapon origin):
    trigger discipline (index straight along the lower receiver) or index pad on the trigger.
    base = (H, pose) of the trigger-discipline grip: the trigger variant keeps that hand placement,
    the middle / ring / little fingers and the thumb, and only moves the index onto the trigger
    (a shooter does not re-grip to fire)."""
    S = HN.socket_matrix(rig, "socket_firing_hand")
    if trigger and base is not None:
        H = np.array(base[0])
        pose = json.loads(json.dumps(base[1]))
        # contact point: the front face of the trigger blade 1.0 cm above its tip (where the
        # distal pad presses), found on the evaluated Trigger mesh; the pad targets it 0.6 mm out
        target = trigger_contact_point(coll, "Trigger")
        ir = fit_index(model, 0, pose, H, coll, "trigger", trigger_part="Trigger", target=target)
        return H, pose, {"placement": "the trigger-discipline grip (chosen so the index can also reach the trigger); only "
                                      "the index moves: its distal pad onto the trigger's front face",
                         "trigger_contact_point_m": [round(float(v), 5) for v in target], "index": ir}
    X = S[:3, :3] @ np.array([1.0, 0, 0])
    Mw = lambda v: (S @ np.append(np.asarray(v, float) / 100.0, 1.0))[:3]       # noqa: E731 (cm, weapon frame)
    tp = "Trigger" if trigger else None
    ga = S[:3, :3] @ np.array([math.sin(math.radians(22.0)), 0.0, math.cos(math.radians(22.0))])   # grip axis (22 deg rake)
    # middle MCP joint reference: on the grip's right side about a proximal phalanx behind the
    # front strap (the proximal phalanx lies along the side, the PIP turns the front-right corner,
    # the middle phalanx spans the 3.2 cm front strap, the distal phalanx lies on the left side),
    # at the height of the trigger guard's rear foot bottom (z ~1.3 cm) minus a finger radius
    H, pose, rep = pistol_grip_frame_search(model, coll, ga, X, S[:3, :3] @ np.array([0, 1.0, 0]), Mw((-2.5, -3.8, 0.2)),
                                            ["PistolGrip"], trigger_point=tp, along_parts=["LowerReceiver", "UpperReceiver"],
                                            reach=trigger_contact_point(coll, "Trigger"))
    dirv = S[:3, :3] @ np.array([1.0, 0, -0.25])
    # the thumb wraps the grip / lower receiver on the left side (not over the buffer tube)
    rep["thumb"] = fit_thumb(model, 0, pose, H, coll, dirv, parts=["PistolGrip", "LowerReceiver"])
    return H, pose, rep


def fit_support_handguard(model, coll, rig):
    """Left hand under the handguard at socket_support_hand, thumb forward along the left side."""
    S = HN.socket_matrix(rig, "socket_support_hand")
    X = S[:3, :3] @ np.array([1.0, 0, 0]); Y = S[:3, :3] @ np.array([0, 1.0, 0]); Z = S[:3, :3] @ np.array([0, 0, 1.0])
    centre = S[:3, 3] + Z * (0.0917 - 0.0647)            # handguard / bore axis above the socket
    cdir = 0.45 * Y - 0.89 * Z                            # palm below-left of the handguard
    H, pose, rep = power_grasp(model, coll, X, cdir, centre, "palm", (-0.010, 0.0, 0.010), (-25.0, -10.0, 5.0),
                               (-10.0, 0.0, 10.0), ["index", "middle", "ring", "pinky"], ["Handguard"], half=0.026)
    rep["placement"] = "diagonal power grasp around the handguard, palm centre at socket_support_hand"
    rep["thumb"] = fit_thumb(model, 0, pose, H, coll, X, parts=["Handguard", "HandguardScrews"])
    return H, pose, rep


def fit_mag_grasp(model, coll, rig):
    """Left hand grasping the seated magazine below the magwell (reload grasp), held like a grip:
    palm on the magazine's left flank, knuckle row along the (curved) magazine axis with the
    index on top just under the magwell, all four fingers wrapping the front edge onto the right
    flank, thumb on the left flank pointing forward-down."""
    S = HN.socket_matrix(rig, "socket_mag")
    X = S[:3, :3] @ np.array([1.0, 0, 0]); Y = S[:3, :3] @ np.array([0, 1.0, 0]); Z = S[:3, :3] @ np.array([0, 0, 1.0])
    Mw = lambda v: (S @ np.append(np.asarray(v, float) / 100.0, 1.0))[:3]       # noqa: E731 (cm, socket frame)
    # magazine front edge: x 16.2 (z -2) .. 17.6 (z -8) cm in the weapon frame; socket_mag at (12.54, 0, 0.37)
    up = S[:3, :3] @ np.array([-0.22, 0.0, 0.975])
    # middle MCP joint: left flank (half width 1.2 + palm 2.2 cm), a proximal phalanx behind the
    # front edge, ~5.5 cm below the magwell (the index then sits ~3 cm under it)
    ref = Mw((16.9 - 12.54 - 5.3, 1.2 + 2.2, -5.3 - 0.37))
    H, pose, rep = pistol_grip_frame_search(model, coll, up, X, -Y, ref, ["Magazine", "MagRounds"],
                                            fingers=("index", "middle", "ring", "pinky"),
                                            yaws=(-5.0, 0.0, 5.0), tilts=(-16.0, -8.0, 0.0),
                                            fwd_offsets=(-0.005, 0.0, 0.005), heights=(-0.008, 0.0, 0.008))
    rep["placement"] = "grip-style grasp of the magazine body below the magwell (palm on the left flank)"
    rep["thumb"] = fit_thumb(model, 0, pose, H, coll, X - 0.6 * Z, parts=["Magazine", "MagRounds"])
    return H, pose, rep


def fit_pistol_2h(models, pistol_parts):
    """Two-handed pistol grip on the proxy pistol: right hand high on the grip with the index on the
    trigger; the left hand wraps the right hand's fingers, its palm filling the left side of the
    grip, thumb forward along the frame under the right thumb."""
    mr, ml = models["r"], models["l"]
    coll = collider_of(pistol_parts)
    P = PISTOL
    r = math.radians(P["rake_deg"])
    up = np.array([math.sin(r), 0.0, math.cos(r)])
    fw = np.array([math.cos(r), 0.0, -math.sin(r)])
    Y = np.array([0, 1.0, 0])
    top = up * P["grip_top"]
    # same anatomy as the rifle grip: middle MCP joint on the grip's right side about a proximal
    # phalanx behind the front strap, one finger radius under the trigger guard
    gb = top[2] - P["guard_depth"]
    zc = gb - 0.010
    mcp_ref = up * (zc / up[2]) - fw * 0.025 - Y * 0.037
    # like the rifle: the grip with the index along the frame first, then the index pad onto the
    # trigger face (hand shift <= 8 mm / 6 deg)
    # the proxy's guard opening is 2.2 cm high: the pad presses 6 mm above the trigger tip so the
    # finger clears the frame
    tpt = trigger_contact_point(coll, "PX_Trigger", above_tip=0.006)
    Hr0, pose_r, rr0 = pistol_grip_frame_search(mr, coll, up, fw, Y, mcp_ref, ["PX_Grip"],
                                                along_parts=["PX_Frame", "PX_Slide"], reach=tpt)
    rr0["thumb"] = fit_thumb(mr, 0, pose_r, Hr0, coll, np.array([1.0, 0, -0.15]), parts=["PX_Frame", "PX_Slide", "PX_Grip"])
    Hr_ = Hr0
    rr = {"index": fit_index(mr, 0, pose_r, Hr0, coll, "trigger", trigger_part="PX_Trigger", target=tpt),
          "trigger_contact_point_m": [round(float(v), 5) for v in tpt]}
    rr["grip_search"] = {k_: v for k_, v in rr0.items() if k_ != "candidates"}
    # left hand: the posed right glove joins the collider; the support hand holds grip + firing
    # fingers like a grip from the left: palm on the left panel over the firing fingertips,
    # knuckle row along the grip axis, its index just under the trigger guard, all four fingers
    # wrapping the front of the firing hand's fingers; contact with frame / slide / trigger /
    # guard penalised
    rco = mr.skin(0, mr.pose(pose_r, Hr_))
    coll2 = collider_of(pistol_parts, extra=[("SK_Glove_R_posed", rco, mr.meshes[0]["tris"])])
    ref_l = up * ((gb - 0.025) / up[2]) - fw * 0.020 + Y * 0.047
    Hl_, pose_l, lr = pistol_grip_frame_search(ml, coll2, up, fw, -Y, ref_l, ["PX_Grip", "SK_Glove_R_posed"],
                                               fingers=("index", "middle", "ring", "pinky"),
                                               yaws=(-5.0, 0.0, 5.0), tilts=(-16.0, -8.0, 0.0),
                                               fwd_offsets=(-0.010, 0.0, 0.010), heights=(-0.004, 0.0, 0.004, 0.008))
    lr["thumb"] = fit_thumb(ml, 0, pose_l, Hl_, coll2, np.array([1.0, 0, -0.05]),
                            parts=["PX_Frame", "PX_Slide", "PX_Grip", "SK_Glove_R_posed"])
    return (Hr_, pose_r), (Hl_, pose_l), {"right": rr, "left": lr}


# ---- non-weapon poses ---------------------------------------------------------

def tune_fist(model, k, bare=None):
    """Full fist: start at MCP 90 / PIP 100 / DIP 70 (index..pinky, slight adduction) and, per
    finger, lower PIP and DIP together along (100 -> 88, 70 -> 55) until the fingertip pad does
    not sink more than TIP_PALM_MAX into the palm (glove surface, finger-into-own-palm test by
    the HandModel skin and a collider built from the posed palm)."""
    s = model.s
    pose = json.loads(json.dumps(FIST_START))
    pose["thumb"] = T(-45, 10, 0, 5, 5)
    masks = HN.finger_masks(model, k, s)
    m = model.meshes[k]
    hand_faces = np.nonzero(np.isin(np.argmax(m["W"], 1)[m["tris"][:, 0]],
                                    [m["groups"].index(f"hand_{s}")]))[0]
    rep = {}
    for f in C.FINGERS4:
        chosen = None
        for t in np.linspace(0, 1, 7):
            pose[f]["pip"] = 100 - 12 * t
            pose[f]["dip"] = 70 - 15 * t
            Sm = model.pose(pose, None)
            P = model.skin(k, Sm)
            palm = HN.Collider([("palm", P, m["tris"][hand_faces])])
            sd, _ = palm.signed(P[masks[(f, 3)]], 0.03)
            if -sd.min() <= TIP_PALM_MAX or t == 1:
                chosen = (float(pose[f]["pip"]), float(pose[f]["dip"]), float(-sd.min()))
                break
        rep[f] = {"mcp": 90.0, "pip": round(chosen[0], 1), "dip": round(chosen[1], 1),
                  "tip_into_palm_mm": round(max(chosen[2], 0.0) * 1000, 2)}
    return pose, rep


def fit_thumb_over_fingers(model, k, pose, over=("index", "middle")):
    """Thumb laid over the middle phalanges of the curled fingers (fist, point).  Collider = the
    posed glove's own finger / palm faces (thumb and its attachment excluded); a coarse grid over
    the five thumb angles picks the candidate with the thumb pad touching (<= 1.5 mm penetration,
    gap small) and pointing along the row of phalanges, then Powell polishes it."""
    import itertools
    s = model.s
    masks = HN.finger_masks(model, k, s)
    thumb_v = np.nonzero(masks[("thumb", 1)])[0]
    coll = HN.self_collider(model, k, pose, None, "thumb", ("index", "middle", "ring", "pinky", "hand"),
                            exclude_near=thumb_v, near_dist=0.010)
    M = model.world(None, C.hand_pose_quats(pose, s, model.rest_angles))
    a = M[f"{over[0]}_02_{s}"][:3, 3]
    b = M[f"{over[-1]}_02_{s}"][:3, 3] if len(over) > 1 else M[f"ring_02_{s}"][:3, 3]
    target = (b - a) / np.linalg.norm(b - a)
    mv = masks[("thumb", 2)]
    fr = HN.load_fields(model.meshes[k]["ob"])
    pad = (masks[("thumb", 3)] & (fr["z_palm"] > 0.2))[np.nonzero(mv)[0]]
    best = None
    for cf, ca, cr, mc, ip in itertools.product((15, 30, 45, 60), (-10, 5, 20, 35), (0, 15, 30), (10, 30, 50), (20, 45, 70)):
        pose["thumb"] = T(cf, ca, cr, mc, ip)
        Sm = model.pose(pose, None)
        sd, _ = coll.signed(model.skin(k, Sm, mv), 0.03)
        pen = max(0.0, -float(sd.min()))
        gap = float(sd[pad].min()) if pad.any() else 0.03
        Mw = model.world(None, C.hand_pose_quats(pose, s, model.rest_angles))
        u = (Mw[f"thumb_03_{s}"] @ np.array([0, model.arm.data.bones[f"thumb_03_{s}"].length, 0, 1]))[:3] - Mw[f"thumb_02_{s}"][:3, 3]
        u /= np.linalg.norm(u)
        dang = math.degrees(math.acos(np.clip(u @ target, -1, 1)))
        c = (pen * 1000) ** 2 * 4 + abs(gap * 1000 - 0.8) * 2 + dang * 0.3
        if best is None or c < best[0]:
            best = (c, dict(pose["thumb"]), pen, gap, dang)
    pose["thumb"] = best[1]
    rep = HN.fit_digit(model, k, pose, None, coll, "thumb", ["cmc_flex", "cmc_abd", "cmc_rot", "mcp", "ip"],
                       [(-10, 75), (-15, 50), (-25, 40), (0, 60), (0, 80)], mv,
                       contact=masks[("thumb", 3)] & (fr["z_palm"] > 0.2), contact_gap=0.0008,
                       direction=(target, f"thumb_02_{s}", f"thumb_03_{s}"), w_dir=10.0)
    rep["grid_best"] = {"angles": best[1], "penetration_mm": round(best[2] * 1000, 2),
                        "pad_gap_mm": round(best[3] * 1000, 2), "direction_err_deg": round(best[4], 1)}
    return rep


def thumb_over_fingers_bare(arm, pose, over=("index", "middle"), s="l",
                            grid=((36, 40, 44), (26, 30, 34), (0,), (40,), (20, 28))):
    """Thumb laid across the middle phalanges of the curled fingers, chosen on the closed bare
    skin with the robust ray-parity contact metric (ivchar.hand_contact_metrics): minimise the
    thumb penetration and the thumb-pad gap to the `over` fingers.  The grid was centred on the
    best of a 72-candidate scan (cmc_flex 25-55, cmc_abd 0-30, cmc_rot 0-20, mcp 20-40, ip 20-45)."""
    import itertools
    from scipy.spatial import cKDTree
    body = bpy.data.objects[BODY]
    names = [b.name for b in arm.data.bones]
    D = C.read_weights(body, names)
    dom = np.array(names)[D.argmax(1)]
    tris = HN.mesh_tris(body.data)
    C.reset_pose(arm)
    rest = C.mesh_arrays(body, evaluated=True)
    ra = C.hand_rest_angles(arm, s)
    best, tried = None, []
    for cf, ca, cr, mc, ip in itertools.product(*grid):
        p2 = json.loads(json.dumps(pose))
        p2["thumb"] = T(cf, ca, cr, mc, ip)
        C.reset_pose(arm)
        C.pose_hand_anat(arm, s, p2, ra)
        co = C.mesh_arrays(body, evaluated=True)
        m = C.hand_contact_metrics(co, rest, tris, dom, s)
        t3 = co[dom == f"thumb_03_{s}"]
        tgt = co[np.isin(dom, [f"{f}_0{i}_{s}" for f in over for i in (2, 3)])]
        gap = float(cKDTree(tgt).query(t3)[0].min())
        c = max(m["thumb_max_mm"], 1.0) + max(gap * 1000 - 3.0, 0.0)
        tried.append({"thumb": [cf, ca, cr, mc, ip], "thumb_penetration_mm": m["thumb_max_mm"], "pad_gap_mm": round(gap * 1000, 2)})
        if best is None or c < best[0]:
            best = (c, p2["thumb"], m["thumb_max_mm"], gap)
    C.reset_pose(arm)
    pose["thumb"] = best[1]
    return {"angles": best[1], "thumb_penetration_mm_bare": best[2], "pad_gap_mm_bare": round(best[3] * 1000, 2),
            "candidates": tried}


def lerp_pose(a, b, t):
    out = {}
    for f in a:
        out[f] = {kk: round(a[f][kk] + (b[f].get(kk, a[f][kk]) - a[f][kk]) * t, 3) for kk in a[f]}
    return out


# =============================================================================
# stage: poses
# =============================================================================

HAND_BONES = lambda s: [f"{f}_{i:02d}_{s}" for f in C.FINGERS for i in (1, 2, 3)]   # noqa: E731


def mat_to_json(M):
    M = np.asarray(M)
    q = Matrix(M.tolist()).to_quaternion()
    return {"translation_m": [round(float(v), 6) for v in M[:3, 3]],
            "rotation_quat_wxyz": [round(float(v), 7) for v in q],
            "matrix": [[round(float(v), 7) for v in row] for row in M]}


def json_to_mat(d):
    return np.array(d["matrix"], float)


def remove_props():
    for cn in ("Props_IV7", "Props_PistolProxy"):
        c = bpy.data.collections.get(cn)
        if c is None:
            continue
        for o in list(c.all_objects):
            bpy.data.objects.remove(o, do_unlink=True)
        bpy.data.collections.remove(c)
    bpy.ops.outliner.orphans_purge(do_recursive=True)


def make_actions(arm, lib):
    """One Blender action per library pose (static, frame 1) + A_Hand_OpenToFist (frames 1-41:
    open, T1, T2, T3, fist every 10 frames).  Only the finger / thumb bones of the pose's side(s)
    are keyed (rotation_quaternion)."""
    rest = {s: C.hand_rest_angles(arm, s) for s in ("l", "r")}
    arm.animation_data_create()
    made = []

    def key(pose_by_side, frame):
        for s, pose in pose_by_side.items():
            C.pose_hand_anat(arm, s, pose, rest[s])
            for n in HAND_BONES(s):
                arm.pose.bones[n].keyframe_insert("rotation_quaternion", frame=frame, group=n)

    for name, e in lib["poses"].items():
        act = bpy.data.actions.new("A_Hand_" + "".join(w.capitalize() for w in name.split("_")))
        act.use_fake_user = True
        arm.animation_data.action = act
        C.reset_pose(arm)
        key({s: e["angles"][s] for s in e["angles"]}, 1)
        made.append(act.name)
        e["action"] = act.name
    act = bpy.data.actions.new("A_Hand_OpenToFist")
    act.use_fake_user = True
    arm.animation_data.action = act
    C.reset_pose(arm)
    for fi, pn in zip((1, 11, 21, 31, 41), ("open_flat", "fist_25", "fist_50", "fist_75", "fist_full")):
        key({s: lib["poses"][pn]["angles"][s] for s in ("l", "r")}, fi)
    made.append(act.name)
    lib["clips"] = {"A_Hand_OpenToFist": {"frames": [1, 41], "fps": 24,
                                          "keys": {"1": "open_flat", "11": "fist_25", "21": "fist_50",
                                                   "31": "fist_75", "41": "fist_full"}}}
    arm.animation_data.action = None
    C.reset_pose(arm)
    return made


def poses_stage():
    t0 = time.time()
    bpy.ops.wm.open_mainfile(filepath=BLEND)
    arm = bpy.data.objects[ARM]
    C.reset_pose(arm)
    for a in list(bpy.data.actions):
        bpy.data.actions.remove(a)
    gl = {s: bpy.data.objects[GL[s]] for s in ("l", "r")}
    models = {s: HN.HandModel(arm, [gl[s]], s) for s in ("l", "r")}
    lib = {"conventions": {
        "angles": "anatomical degrees (ivchar.hand_pose_quats): finger mcp/pip/dip flexion 0 = straight "
                  "(proximal phalanx in the palm plane, middle/distal in line with the parent), + = flexion; "
                  "abd = MCP abduction relative to rest, + = towards the thumb (both hands); thumb cmc_flex / "
                  "cmc_abd / cmc_rot = thumb_01 rotation relative to rest about its local X (across the palm) / "
                  "Z (palmar abduction) / Y (pronation); thumb mcp / ip anatomical flexion",
        "local_rotation": "finger _01: q = Rx(mcp - rest) * Rz(abd * side) (flexion about the metacarpal-fixed X, abduction about the floating axis); _02/_03: Rx(angle - rest); "
                          "thumb_01: Rx(cmc_flex) * Rz(cmc_abd * side) * Ry(cmc_rot * side); side = +1 left, -1 right; "
                          "rest offsets below",
        "rest_offsets_deg": {s: C.hand_rest_angles(arm, s) for s in ("l", "r")},
        "hand_attach": "hand_<s> bone WORLD matrix expressed in the weapon socket frame (Blender axes, metres): "
                       "hand_world = socket_world * hand_attach"},
        "poses": {}}
    P = lib["poses"]
    for n, pz in BASE_POSES.items():
        P[n] = {"kind": "base", "angles": {"l": pz, "r": pz}}
    # full fist (per finger tuned to palm contact) + thumb over index / middle
    fist, frep = tune_fist(models["l"], 0)
    set_fist_limits(fist)
    trep = thumb_over_fingers_bare(arm, fist, ("index", "middle"))
    P["fist_full"] = {"kind": "base", "angles": {"l": fist, "r": fist},
                      "fit": {"fingers": frep, "thumb": trep}}
    for t, n in ((0.25, "fist_25"), (0.50, "fist_50"), (0.75, "fist_75")):
        pz = lerp_pose(BASE_POSES["open_flat"], fist, t)
        P[n] = {"kind": "transition", "t": t, "angles": {"l": pz, "r": pz}}
    point = json.loads(json.dumps(fist))
    point["index"] = F(5, 5, 3, 0)
    prep = thumb_over_fingers_bare(arm, point, ("middle",))
    P["point"] = {"kind": "base", "angles": {"l": point, "r": point}, "fit": {"thumb": prep}}
    log("base poses done", round(time.time() - t0, 1))
    # weapon grips
    props = load_props()
    rig = props["rifle"]["rig"]
    coll = collider_of(props["rifle"]["parts"])
    base = None
    for n, trig in (("rifle_grip_index_straight", False), ("rifle_grip_trigger", True)):
        H, pz, rep = fit_rifle_grip(models["r"], coll, rig, trigger=trig, base=base)
        base = (H, pz)
        S = HN.socket_matrix(rig, "socket_firing_hand")
        P[n] = {"kind": "grip", "weapon": "IV-7", "socket": "socket_firing_hand", "angles": {"r": pz},
                "hand_attach": {"r": mat_to_json(np.linalg.inv(S) @ H)}, "fit": rep}
        log(n, round(time.time() - t0, 1))
    H, pz, rep = fit_support_handguard(models["l"], coll, rig)
    S = HN.socket_matrix(rig, "socket_support_hand")
    P["support_handguard"] = {"kind": "grip", "weapon": "IV-7", "socket": "socket_support_hand", "angles": {"l": pz},
                              "hand_attach": {"l": mat_to_json(np.linalg.inv(S) @ H)}, "fit": rep}
    log("support", round(time.time() - t0, 1))
    H, pz, rep = fit_mag_grasp(models["l"], coll, rig)
    S = HN.socket_matrix(rig, "socket_mag")
    P["mag_grasp"] = {"kind": "grip", "weapon": "IV-7", "socket": "socket_mag", "angles": {"l": pz},
                      "hand_attach": {"l": mat_to_json(np.linalg.inv(S) @ H)}, "fit": rep}
    log("mag", round(time.time() - t0, 1))
    (Hr_, pr), (Hl_, pl), rep = fit_pistol_2h(models, props["pistol"]["parts"])
    P["pistol_2h"] = {"kind": "grip", "weapon": "PROXY pistol (generic compact 9 mm, not a game asset)",
                      "socket": "pistol hold point (proxy origin)", "angles": {"r": pr, "l": pl},
                      "hand_attach": {"r": mat_to_json(Hr_), "l": mat_to_json(Hl_)}, "fit": rep,
                      "proxy_dimensions_m": PISTOL}
    log("pistol", round(time.time() - t0, 1))
    remove_props()
    lib["actions"] = make_actions(arm, lib)
    lib["seconds"] = round(time.time() - t0, 1)
    with open(os.path.join(HERE, POSES_JSON), "w") as f:
        json.dump(lib, f, indent=1)
    bpy.ops.wm.save_as_mainfile(filepath=BLEND, compress=True)
    log("poses stage", lib["seconds"], "s")
    return lib




# =============================================================================

STAGE_FUNCS = {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stages", default="build,textures,poses,validate,render,export")
    ap.add_argument("--only", default=None)
    a = ap.parse_args(sys.argv[1:])
    stages = a.stages.split(",")
    rep = {}
    if os.path.exists(REPORT):
        with open(REPORT) as f:
            rep = json.load(f)
    rep["generated_by"] = f"hands_gloves.py (ivhands {HN.IVHANDS_VERSION}, ivchar {C.IVCHAR_VERSION}, ivlib {ivlib.LIB_VERSION})"
    rep["blender"] = bpy.app.version_string
    os.makedirs(PREV, exist_ok=True)
    t0 = time.time()
    if "build" in stages:
        rep["build"] = build()
    if "textures" in stages:
        rep["textures"] = textures()
    if "poses" in stages:
        lib = poses_stage()
        rep["pose_fit_seconds"] = lib["seconds"]
    for st in ("validate", "render", "export"):
        if st in stages:
            fn = STAGE_FUNCS[st]
            out = fn(a.only.split(",") if a.only else None) if st == "render" else fn()
            if out is not None:
                rep[st] = out
    rep["seconds_this_run"] = round(time.time() - t0, 1)
    rep["time"] = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(REPORT, "w") as f:
        json.dump(rep, f, indent=1)
    log("report ->", REPORT)



# =============================================================================
# stage: validate
# =============================================================================

# bare-skin limits; the glove shells are offset copies of the skin (1.0-1.25 mm each), so where
# two bare surfaces press together their shells overlap by the two thicknesses more
HAND01_LIMITS = dict(tip_palm_mm=1.5, finger_finger_mm=4.0, thumb_mm=4.0, glove_shells_extra_mm=2.5,
                     glove_poke_mm=0.5, weapon_pen_mm=2.0, contact_gap_mm=3.0, glove_float_p95_mm=4.0)
# per grip: the digits that must hold the object (some segment within 0-3 mm of the named parts)
GRIP_HOLD = {
    "rifle_grip_index_straight": {"r": {"middle": ["PistolGrip"], "ring": ["PistolGrip"], "pinky": ["PistolGrip"],
                                        "thumb": None, "index": ["LowerReceiver", "UpperReceiver"]}},
    "rifle_grip_trigger": {"r": {"middle": ["PistolGrip"], "ring": ["PistolGrip"], "pinky": ["PistolGrip"],
                                 "thumb": None, "index_03": ["Trigger"]}},
    "support_handguard": {"l": {"index": ["Handguard"], "middle": ["Handguard"], "ring": ["Handguard"], "thumb": None}},
    "mag_grasp": {"l": {"index": None, "middle": ["Magazine"], "ring": ["Magazine"], "pinky": ["Magazine"], "thumb": None}},
    "pistol_2h": {"r": {"middle": ["PX_Grip"], "ring": ["PX_Grip"], "pinky": ["PX_Grip"], "index_03": ["PX_Trigger"]},
                  "l": {"index": None, "middle": None, "ring": None, "thumb": None}},
}


def load_pose_scene(with_props=True):
    bpy.ops.wm.open_mainfile(filepath=BLEND)
    arm = bpy.data.objects[ARM]
    C.reset_pose(arm)
    lib = json.load(open(os.path.join(HERE, POSES_JSON)))
    props = load_props() if with_props else {}
    return arm, lib, props


def pose_armature(arm, models, e, props):
    """Pose the Blender armature for library entry e (hands placed on the weapon for grips;
    forearms follow the hands rigidly)."""
    C.reset_pose(arm)
    for s, pz in e["angles"].items():
        if "hand_attach" in e:
            Srel = json_to_mat(e["hand_attach"][s])
            if e["weapon"].startswith("PROXY"):
                Sock = np.eye(4)
            else:
                Sock = HN.socket_matrix(props["rifle"]["rig"], e["socket"])
            HN.apply_to_armature(models[s], Sock @ Srel, pz)
        else:
            C.pose_hand_anat(arm, s, pz, models[s].rest_angles)
    bpy.context.view_layer.update()


def glove_arrays(g):
    co = C.mesh_arrays(g, evaluated=True)
    tris = HN.mesh_tris(g.data)
    return co, tris


def validate():
    t0 = time.time()
    arm, lib, props = load_pose_scene()
    body = bpy.data.objects[BODY]
    C.clear_correctives(body)
    gl = {s: bpy.data.objects[GL[s]] for s in ("l", "r")}
    models = {s: HN.HandModel(arm, [gl[s]], s) for s in ("l", "r")}
    names = [b.name for b in arm.data.bones]
    Db = C.read_weights(body, names)
    dom_b = np.array(names)[Db.argmax(1)]
    tris_b = HN.mesh_tris(body.data)
    C.reset_pose(arm)
    rest_b = C.mesh_arrays(body, evaluated=True)
    grest, gdom, gtris_c, hand_skin = {}, {}, {}, {}
    for s, g in gl.items():
        co, tris = glove_arrays(g)
        gn = [vg.name for vg in g.vertex_groups]
        W = HN.read_groups(g, gn)
        gdom[s] = np.append(np.array(gn)[W.argmax(1)], f"lowerarm_{s}")
        loop = HN.boundary_loop(g.data)
        co2, t2 = HN.cap_opening(co, tris, loop)
        grest[s] = co2
        gtris_c[s] = (t2, loop)
        hand_skin[s] = np.isin(dom_b, HN.GLOVE_BONES(s))
    # skin that SK_Human_Base_Gloved still has under the gloves (the cuff overlap band): the
    # vertices of the glove region used by faces that make_gloved_body keeps
    shipped_skin = {}
    for s in ("l", "r"):
        full = set(HN.glove_region(arm, body, s, HN.GLOVE_DESIGN["cuff_len"])[0].tolist())
        cut = set(HN.glove_region(arm, body, s, HN.GLOVE_DESIGN["cuff_len"] - 0.025)[0].tolist())
        keep = np.zeros(len(body.data.vertices), bool)
        for p_ in body.data.polygons:
            if not all(v in cut for v in p_.vertices):
                keep[list(p_.vertices)] = True
        m_ = np.zeros(len(keep), bool)
        m_[list(full)] = True
        # only skin actually inside the cuff: distal of the cuff opening by > 3 mm (skin at the
        # opening itself is outside the glove by definition)
        wj, ax = HN.forearm_axis(arm, s)
        u = (rest_b - wj) @ ax
        shipped_skin[s] = m_ & keep & (u > -HN.GLOVE_DESIGN["cuff_len"] + 0.003)
    coll_r = collider_of(props["rifle"]["parts"])
    coll_p = collider_of(props["pistol"]["parts"])
    out = {"limits": HAND01_LIMITS, "poses": {}}
    for pn, e in lib["poses"].items():
        pose_armature(arm, models, e, props)
        cob = C.mesh_arrays(body, evaluated=True)
        er = {"kind": e["kind"], "sides": {}}
        for s, pz in e["angles"].items():
            r = {}
            meas = C.measured_hand_angles(arm, s, models[s].rest_angles)
            dev = max(abs(meas[f][kk] - pz[f][kk]) for f in pz for kk in pz[f] if kk in meas[f])
            r["joint_angles_deg"] = meas
            r["angle_readback_max_dev_deg"] = round(float(dev), 4)
            dl = 0.0
            for n in HAND_BONES(s):
                L = (C.bone_world(arm, n, "tail") - C.bone_world(arm, n, "head")).length
                dl = max(dl, abs(L - arm.data.bones[n].length))
            r["bone_length_change_mm"] = round(dl * 1000, 6)
            # glove
            gco, _ = glove_arrays(gl[s])
            loop = gtris_c[s][1]
            gco2, gt2 = HN.cap_opening(gco, HN.mesh_tris(gl[s].data), loop)
            # (a) the shipped combination SK_Human_Base_Gloved + glove (skin left under the cuff)
            r["glove_vs_skin"] = HN.skin_vs_glove(cob, shipped_skin[s], gco, HN.mesh_tris(gl[s].data),
                                                 skin_rest=rest_b, glove_rest=grest[s][:-1])
            # (b) informational: the glove worn over the FULL bare hand of SK_Human_Base
            r["glove_vs_full_bare_hand"] = HN.skin_vs_glove(cob, hand_skin[s], gco, HN.mesh_tris(gl[s].data),
                                                           skin_rest=rest_b, glove_rest=grest[s][:-1])
            gm = C.hand_contact_metrics(gco2, grest[s], gt2, gdom[s], s)
            r["glove_self_contact"] = {k: v for k, v in gm.items() if k != "penetration"}
            r["glove_self_contact_pairs"] = gm["penetration"]
            if e["kind"] != "grip":
                bm = C.hand_contact_metrics(cob, rest_b, tris_b, dom_b, s)
                r["bare_contact"] = {k: v for k, v in bm.items() if k != "penetration"}
                r["bare_contact_pairs"] = bm["penetration"]
                nbd, mbd = C.verts_beyond_dorsal(cob, rest_b, tris_b, dom_b, s, arm)
                r["bare_fingertips_through_back"] = {"verts": nbd, "max_mm": round(mbd * 1000, 2)}
            else:
                coll = coll_p if e["weapon"].startswith("PROXY") else coll_r
                if pn == "pistol_2h" and s == "l":
                    rco = C.mesh_arrays(gl["r"], evaluated=True)
                    coll = collider_of(props["pistol"]["parts"], extra=[("SK_Glove_R_posed", rco, HN.mesh_tris(gl["r"].data))])
                m = models[s]
                regions = {f"{f}_{i:02d}": m.verts_of(0, [f"{f}_{i:02d}_{s}"], 0.5) for f in C.FINGERS for i in (1, 2, 3)}
                fr = HN.load_fields(gl[s])
                regions["palm"] = m.verts_of(0, [f"hand_{s}"], 0.5) & (fr["z_palm"] > 0.3)
                regions["back_of_hand"] = m.verts_of(0, [f"hand_{s}"], 0.5) & (fr["z_palm"] < -0.3)
                Sm = m.pose(pz, None)
                # use the Blender-evaluated glove (identical to the numpy skin; checked in build)
                Pw = gco
                sd, pi = coll.signed(Pw, 0.03)
                ins, dep, pid = coll.inside_parity(Pw)
                pnames = [p_["name"] for p_ in coll.parts]
                reg = {}
                for rn, msk in regions.items():
                    if not msk.any():
                        continue
                    touch = sorted({pnames[i] for i in np.unique(pi[msk & (sd < 0.003)]) if i >= 0})
                    reg[rn] = {"min_gap_mm": round(float(sd[msk].min()) * 1000, 2),
                               "penetration_mm": round(float(dep[msk].max()) * 1000, 2) if ins[msk].any() else 0.0,
                               "in_contact_0_3mm": bool(sd[msk].min() <= 0.003), "touches": touch}
                r["weapon_contact"] = reg
                # weapon vertices poking into the glove
                bg = HN.bvh_arrays(Pw, HN.mesh_tris(gl[s].data))
                lo, hi = Pw.min(0) - 0.01, Pw.max(0) + 0.01
                cm = np.all((coll.co > lo) & (coll.co < hi), axis=1)
                nin, worst = 0, 0.0
                gt_ = HN.mesh_tris(gl[s].data)
                fdom = gdom[s][gt_[:, 0]]
                cuff_face = np.array([str(b).startswith("lowerarm") for b in fdom])
                ncuff, wcuff = 0, 0.0
                for q in coll.co[cm]:
                    v = Vector(tuple(map(float, q)))
                    loc, nn, fi, dist = bg.find_nearest(v, 0.006)
                    if loc is not None and (v - loc).dot(nn) < 0:
                        if cuff_face[fi]:
                            # the cuff / forearm: its placement comes from the arm IK in the game,
                            # here the forearm just follows the hand rigidly -> reported apart
                            ncuff += 1
                            wcuff = max(wcuff, dist)
                            continue
                        nin += 1
                        worst = max(worst, dist)
                r["weapon_verts_inside_glove"] = {"n": nin, "max_depth_mm": round(worst * 1000, 2)}
                r["weapon_verts_inside_cuff_forearm_rigid"] = {"n": ncuff, "max_depth_mm": round(wcuff * 1000, 2)}
                r["max_penetration_mm"] = round(max([v["penetration_mm"] for v in reg.values()] + [worst * 1000]), 2)
                cont = [k for k, v in reg.items() if v["in_contact_0_3mm"]]
                r["segments_in_contact"] = cont
                hold = {}
                for dg, parts_ok in GRIP_HOLD.get(pn, {}).get(s, {}).items():
                    segs_ = [k for k in reg if (k == dg or k.startswith(dg + "_"))]
                    okk = [k for k in segs_ if reg[k]["in_contact_0_3mm"]
                           and (parts_ok is None or set(reg[k]["touches"]) & set(parts_ok))]
                    hold[dg] = {"holding_segments": okk, "ok": bool(okk),
                                "min_gap_mm": min(reg[k]["min_gap_mm"] for k in segs_) if segs_ else None}
                r["grip_hold"] = hold
            er["sides"][s] = r
        out["poses"][pn] = er
        log("validated", pn, round(time.time() - t0, 1))
    out["checks"] = hand_checks(out)
    out["seconds"] = round(time.time() - t0, 1)
    return out


def hand_checks(v):
    L = HAND01_LIMITS
    chk = {}
    worst = {"tip_palm": 0.0, "finger_finger": 0.0, "thumb": 0.0, "through_back": 0, "poke": 0.0,
             "angle_dev": 0.0, "bone_len": 0.0, "wpn_pen": 0.0, "bare_tip_palm": 0.0, "bare_finger_finger": 0.0,
             "bare_thumb": 0.0}
    hold_fail = []
    for pn, e in v["poses"].items():
        for s, r in e["sides"].items():
            worst["angle_dev"] = max(worst["angle_dev"], r["angle_readback_max_dev_deg"])
            worst["bone_len"] = max(worst["bone_len"], r["bone_length_change_mm"])
            worst["poke"] = max(worst["poke"], r["glove_vs_skin"]["poke_through_max_mm"])
            gs = r["glove_self_contact"]
            worst["tip_palm"] = max(worst["tip_palm"], gs["tip_palm_max_mm"])
            worst["finger_finger"] = max(worst["finger_finger"], gs["finger_finger_max_mm"])
            worst["thumb"] = max(worst["thumb"], gs["thumb_max_mm"])
            if "bare_fingertips_through_back" in r:
                worst["through_back"] = max(worst["through_back"], r["bare_fingertips_through_back"]["verts"])
            if "bare_contact" in r:
                for c in ("tip_palm", "finger_finger", "thumb"):
                    worst["bare_" + c] = max(worst["bare_" + c], r["bare_contact"][f"{c}_max_mm"])
            for dg, h in r.get("grip_hold", {}).items():
                if not h["ok"]:
                    hold_fail.append(f"{pn}/{s}/{dg}")
            if "max_penetration_mm" in r:
                worst["wpn_pen"] = max(worst["wpn_pen"], r["max_penetration_mm"])
    chk["joint_angles_exact_readback"] = "PASS" if worst["angle_dev"] < 0.05 else "FAIL"
    chk["phalanx_lengths_constant"] = "PASS" if worst["bone_len"] < 1e-3 else "FAIL"
    chk["no_fingertip_through_back_of_hand"] = "PASS" if worst["through_back"] == 0 else "FAIL"
    chk["glove_never_penetrated_by_skin"] = "PASS" if worst["poke"] <= L["glove_poke_mm"] else "FAIL"
    ex = L["glove_shells_extra_mm"]
    chk["bare_fingertip_into_palm_le_1.5mm"] = "PASS" if worst["bare_tip_palm"] <= L["tip_palm_mm"] else "FAIL"
    chk["bare_finger_finger_overlap_le_4mm"] = "PASS" if worst["bare_finger_finger"] <= L["finger_finger_mm"] else "FAIL"
    chk["bare_thumb_overlap_le_4mm"] = "PASS" if worst["bare_thumb"] <= L["thumb_mm"] else "FAIL"
    chk["glove_fingertip_into_palm_le_1.5mm"] = "PASS" if worst["tip_palm"] <= L["tip_palm_mm"] else "FAIL"
    chk[f"glove_finger_finger_overlap_le_{L['finger_finger_mm'] + ex}mm"] = (
        "PASS" if worst["finger_finger"] <= L["finger_finger_mm"] + ex else "FAIL")
    chk[f"glove_thumb_overlap_le_{L['thumb_mm'] + ex}mm"] = "PASS" if worst["thumb"] <= L["thumb_mm"] + ex else "FAIL"
    chk["weapon_penetration_le_2mm"] = "PASS" if worst["wpn_pen"] <= L["weapon_pen_mm"] else "FAIL"
    chk["grip_digits_in_contact_0_3mm"] = "PASS" if not hold_fail else "FAIL"
    chk["_grip_hold_failures"] = hold_fail
    chk["_worst"] = {k: round(float(x), 3) for k, x in worst.items()}
    return chk


STAGE_FUNCS["validate"] = validate


# =============================================================================
# stage: render (HAND-01 / HAND-02 evidence)
# =============================================================================

SHEET_POSES = ("open_flat", "fist_25", "fist_50", "fist_75", "fist_full", "relaxed", "spread", "point")
VIEW_NAMES = ("palm", "back", "side")


def label(path, text, sub=None):
    from PIL import Image, ImageDraw
    im = Image.open(path).convert("RGB")
    dr = ImageDraw.Draw(im)
    dr.rectangle([0, 0, im.width, 20 if sub is None else 36], fill=(28, 28, 30))
    dr.text((6, 4), text, fill=(235, 235, 235))
    if sub:
        dr.text((6, 20), sub, fill=(190, 190, 190))
    im.save(path)
    return path


def grid(paths, out, cols, title=None, cell=None):
    from PIL import Image, ImageDraw
    ims = [Image.open(p).convert("RGB") for p in paths]
    w, h = cell or (ims[0].width, ims[0].height)
    rows = (len(ims) + cols - 1) // cols
    top = 26 if title else 0
    sheet = Image.new("RGB", (cols * w, rows * h + top), (24, 24, 26))
    dr = ImageDraw.Draw(sheet)
    if title:
        dr.text((8, 6), title, fill=(240, 240, 240))
    for i, im in enumerate(ims):
        if im.size != (w, h):
            im = im.resize((w, h))
        sheet.paste(im, ((i % cols) * w, top + (i // cols) * h))
    sheet.save(out)
    return out


def arm_mask(body, arm, keep_skin_under_glove=True):
    names = [b.name for b in arm.data.bones]
    D = C.read_weights(body, names)
    keep = [n for n in names if any(k in n for k in ("lowerarm", "hand", "thumb", "index", "middle", "ring", "pinky"))]
    m = C.dominant_bone_mask(D, names, keep)
    vg = body.vertex_groups.get("IVH_ArmMask") or body.vertex_groups.new(name="IVH_ArmMask")
    vg.add([int(i) for i in np.nonzero(m)[0]], 1.0, 'REPLACE')
    mod = body.modifiers.get("IVH_Mask") or body.modifiers.new("IVH_Mask", 'MASK')
    mod.vertex_group = "IVH_ArmMask"
    return mod


def render_setup(centre=(0.5, -0.1, 1.0), size=0.6):
    ivlib.clear_lights_cameras()
    sc = bpy.context.scene
    ivlib.setup_cycles(sc, samples=RENDER_SAMPLES, threads=4)
    sc.view_settings.view_transform = 'AgX'
    sc.view_settings.look = 'None'
    C.neutral_lighting(centre, size, key=0.55, world_strength=0.45)
    return sc


def set_variant(variant, arm):
    """bare: SK_Human_Base masked to forearms + hands (clay skin); coyote / black: gloves + the
    gloved body masked to the forearms."""
    body = bpy.data.objects[BODY]
    gb = bpy.data.objects[BODY + "_Gloved"]
    gl = [bpy.data.objects[GL[s]] for s in ("l", "r")]
    skin = C.clay_material("IVH_Skin", color=(0.60, 0.50, 0.43), rough=0.55)
    for ob in (body, gb):
        ob.data.materials.clear()
        ob.data.materials.append(skin)
        arm_mask(ob, arm)
    body.hide_render = variant != "bare"
    gb.hide_render = variant == "bare"
    for g in gl:
        g.hide_render = variant == "bare"
        if variant != "bare":
            g.data.materials.clear()
            g.data.materials.append(bpy.data.materials[f"M_Glove_{variant.capitalize()}"])


def hand_views(arm, s, dist=0.40):
    c, d, r, n = C.palm_frame(arm, s)
    tc = c + d * 0.035
    return {"palm": (tc + n * dist, tc, -d), "back": (tc - n * dist, tc, -d),
            "side": (tc + r * dist + n * 0.06, tc, n)}


def render_hand01(arm, lib, variants=("bare", "coyote"), poses=SHEET_POSES, cell=(520, 440)):
    made = []
    for variant in variants:
        set_variant(variant, arm)
        for pn in poses:
            e = lib["poses"][pn]
            C.reset_pose(arm)
            for s in ("l", "r"):
                C.pose_hand_anat(arm, s, e["angles"][s], C.hand_rest_angles(arm, s))
            bpy.context.view_layer.update()
            panels = []
            for s in ("l", "r"):
                for vn, (loc, tgt, up) in hand_views(arm, s).items():
                    cam = ivlib.camera(f"c_{pn}_{s}_{vn}", loc, tgt, lens=50, up=tuple(up))
                    pth = os.path.join(PREV, "_panels", f"{variant}_{pn}_{s}_{vn}.png")
                    ivlib.render(pth, cam, res=cell, samples=RENDER_SAMPLES)
                    label(pth, f"{variant}  {pn}  {'left' if s == 'l' else 'right'} hand  {vn}")
                    panels.append(pth)
            out = os.path.join(PREV, f"Hands_{variant}_{pn}.png")
            grid(panels, out, 3, title=f"SK_Human_Base hands - {variant} - pose '{pn}' (anatomical angles in Hand_Poses.json) - "
                                       f"rows: left hand, right hand; columns: palm, back, side")
            made.append(out)
    return made


def wrist_pose(arm, kind):
    C.reset_pose(arm)
    for s in ("l", "r"):
        C.pose_hand_anat(arm, s, BASE_POSES["relaxed"], C.hand_rest_angles(arm, s))
        _, d, r, n = C.palm_frame(arm, s)
        if kind == "flex70":
            C.rotate_bone_rest_axis(arm, f"hand_{s}", d.cross(n) if s == "l" else -d.cross(n), 70.0)
        elif kind == "ext60":
            C.rotate_bone_rest_axis(arm, f"hand_{s}", d.cross(n) if s == "l" else -d.cross(n), -60.0)
        elif kind == "ulnar30":
            C.rotate_bone_rest_axis(arm, f"hand_{s}", n if s == "l" else -n, -30.0)
        elif kind == "twist80":
            fa = C.bone_dir(arm, f"lowerarm_{s}")
            C.rotate_bone_world(arm, f"hand_{s}", fa, 80.0)
    C.drive_twist_bones(arm)
    bpy.context.view_layer.update()


def render_closeups(arm, lib):
    made = []
    for variant in ("bare", "coyote"):
        set_variant(variant, arm)
        # knuckles at the full fist (both hands), from the back / fingertip side
        e = lib["poses"]["fist_full"]
        C.reset_pose(arm)
        for s in ("l", "r"):
            C.pose_hand_anat(arm, s, e["angles"][s], C.hand_rest_angles(arm, s))
        bpy.context.view_layer.update()
        for s in ("l", "r"):
            c, d, r, n = C.palm_frame(arm, s)
            tc = c + d * 0.05 + n * 0.01
            for vn, v in (("knuckles", (-n * 0.8 + d * 0.6).normalized()), ("thumb", (r * 0.8 + n * 0.5 + d * 0.3).normalized())):
                cam = ivlib.camera(f"ck_{s}_{vn}", tc + v * 0.24, tc, lens=50, up=tuple(-d if vn == "thumb" else -n))
                pth = os.path.join(PREV, f"Hands_closeup_fist_{vn}_{variant}_{s}.png")
                ivlib.render(pth, cam, res=(800, 800), samples=RENDER_SAMPLES + 8)
                made.append(label(pth, f"{variant} full fist {vn} close-up ({'left' if s == 'l' else 'right'} hand)"))
        # wrist extremes (left hand; the rig is mirror-exact)
        for kind in ("flex70", "ext60", "ulnar30", "twist80"):
            wrist_pose(arm, kind)
            s = "l"
            w = C.bone_world(arm, f"hand_{s}")
            e2 = C.bone_world(arm, f"lowerarm_{s}")
            fa = (w - e2).normalized()
            _, d, r, n = C.palm_frame(arm, s)
            side = fa.cross(Vector((0, 0, 1))).normalized()
            if side.y > 0:
                side = -side
            tc = w + d * 0.03
            vdir = (r * 0.9 + Vector((0, -0.3, 0.2))).normalized() if kind != "twist80" else (side + Vector((0.2, 0, 0.2))).normalized()
            cam = ivlib.camera(f"cw_{kind}", tc + vdir * 0.30, tc, lens=50, up=(0, 0, 1))
            pth = os.path.join(PREV, f"Hands_closeup_wrist_{kind}_{variant}.png")
            ivlib.render(pth, cam, res=(800, 800), samples=RENDER_SAMPLES + 8)
            made.append(label(pth, f"{variant} left wrist {kind} (relaxed fingers; twist bones driven)"))
    C.reset_pose(arm)
    return made


# ---- full-body stances for the first-person views --------------------------------

FP = dict(eye=(0.0, -0.131, 1.687), butt_pocket=(-0.150, -0.080, 1.445), butt_local=(-0.2840, 0.0, 0.0800),
          rifle_pitch=4.0, rifle_cant=0.0, spine_twist=(12.0, 14.0, 14.0), neck_counter=-40.0,
          clavicle_l_protraction=18.0, clavicle_r_elevation=6.0, cam_pitch=-31.0, cam_yaw=-10.0, fov=80.0,
          pistol_offset=(0.0, -0.46, -0.02))


def rifle_world(arm):
    """World matrix of the IV-7 root for the first-person ready stance: butt pad centre in the
    right shoulder pocket, muzzle forward (-Y) and pitched up rifle_pitch degrees."""
    Rz = np.array(Matrix.Rotation(math.radians(-90), 4, 'Z'))
    Rp = np.array(Matrix.Rotation(math.radians(FP["rifle_pitch"]), 4, 'X'))
    W = Rp @ Rz
    W[:3, 3] = np.array(FP["butt_pocket"]) - W[:3, :3] @ np.array(FP["butt_local"])
    return W


def stance_rifle(arm, lib, props, left="support_handguard", right="rifle_grip_index_straight"):
    """Full body: torso turned (bladed), left shoulder protracted, head turned back to the front,
    both arms solved (two-bone IK) to the grip poses on the rifle (butt in the shoulder pocket)."""
    C.reset_pose(arm)
    rig = props["rifle"]["rig"]
    W = rifle_world(arm)
    rig.matrix_world = Matrix(W.tolist())
    bpy.context.view_layer.update()
    for n, a in zip(("spine_01", "spine_02", "spine_03"), FP["spine_twist"]):
        C.rotate_bone_rest_axis(arm, n, Vector((0, 0, 1)), -a)
    C.rotate_bone_rest_axis(arm, "neck_01", Vector((0, 0, 1)), -FP["neck_counter"] * 0.5)
    C.rotate_bone_rest_axis(arm, "head", Vector((0, 0, 1)), -FP["neck_counter"] * 0.5)
    C.rotate_bone_world(arm, "clavicle_l", Vector((0, 0, 1)), -FP["clavicle_l_protraction"])
    C.rotate_bone_world(arm, "clavicle_r", Vector((0, 1, 0)), FP["clavicle_r_elevation"])
    ik = {}
    for s, pn, pole in (("r", right, (-0.6, 0.35, -1.0)), ("l", left, (0.35, 0.1, -1.0))):
        e = lib["poses"][pn]
        Sock = HN.socket_matrix(rig, e["socket"])
        H = Sock @ json_to_mat(e["hand_attach"][s])
        ik[s] = HN.arm_ik(arm, s, H, pole)
        C.pose_hand_anat(arm, s, e["angles"][s], C.hand_rest_angles(arm, s))
    bpy.context.view_layer.update()
    return ik


def fp_camera(name):
    eye = Vector(FP["eye"])
    yaw, pitch = math.radians(FP["cam_yaw"]), math.radians(FP["cam_pitch"])
    d = Vector((-math.sin(-yaw) * 0 + math.sin(yaw), -math.cos(yaw), math.tan(pitch)))
    cam = ivlib.camera(name, eye, eye + d, fov_deg=FP["fov"], up=(0, 0, 1), clip_start=0.02)
    return cam


def render_grips(arm, lib, props):
    made = []
    set_variant("coyote", arm)
    rig = props["rifle"]["rig"]
    models = {s: HN.HandModel(arm, [bpy.data.objects[GL[s]]], s) for s in ("l", "r")}
    gb = bpy.data.objects[BODY + "_Gloved"]
    for pn in ("rifle_grip_index_straight", "rifle_grip_trigger", "support_handguard", "mag_grasp", "pistol_2h"):
        e = lib["poses"][pn]
        pistol = pn.startswith("pistol")
        for o in props["rifle"]["parts"]:
            o.hide_render = pistol
        for o in props["pistol"]["parts"]:
            o.hide_render = not pistol
        rig.matrix_world = Matrix.Identity(4)
        reset_pistol(props)
        # ---- two close angles: hand(s) only, weapon at its own origin
        gb.hide_render = True
        pose_armature(arm, models, e, props)
        for s in ("l", "r"):
            bpy.data.objects[GL[s]].hide_render = s not in e["angles"]
        if pistol:
            tgt = Vector((0.03, 0.0, 0.03))
            views = (("right", (0.1, -1, 0.25)), ("left_low", (0.2, 1, -0.35)))
        elif pn.startswith("rifle"):
            tgt = Vector((0.025, 0.0, 0.035))
            views = (("right", (0.1, -1, 0.2)), ("left_low", (0.25, 1, -0.3)))
        else:
            Sock = HN.socket_matrix(rig, e["socket"])
            tgt = Vector(tuple(Sock[:3, 3])) + Vector((0, 0, 0.0 if pn == "mag_grasp" else 0.02))
            views = (("left", (-0.15, 1, 0.1)), ("right_low", (0.25, -1, -0.45)))
        for vn, v in views:
            cam = ivlib.camera(f"cg_{pn}_{vn}", tgt + Vector(v).normalized() * 0.34, tgt, lens=50, up=(0, 0, 1))
            pth = os.path.join(PREV, f"Hands_grip_{pn}_{vn}.png")
            ivlib.render(pth, cam, res=(1280, 720), samples=RENDER_SAMPLES + 8)
            made.append(label(pth, f"{pn}: {vn} view (coyote gloves; weapon {e['weapon']})",
                              "contact gaps / penetration: Hands_validation.json"))
        # ---- first-person camera angle: full body stance, arms solved to the grips
        gb.hide_render = False
        bpy.data.objects[GL["l"]].hide_render = False
        bpy.data.objects[GL["r"]].hide_render = False
        mod = gb.modifiers.get("IVH_Mask")
        if mod:
            mod.show_render = False
        head_hide = hide_head(gb, arm)
        if pistol:
            ik, W = stance_pistol_objects(arm, lib, props)
        elif pn == "mag_grasp":
            ik = stance_rifle(arm, lib, props, left="mag_grasp", right="rifle_grip_index_straight")
        elif pn == "rifle_grip_trigger":
            ik = stance_rifle(arm, lib, props, right="rifle_grip_trigger")
        else:
            ik = stance_rifle(arm, lib, props)
        cam = fp_camera(f"cfp_{pn}")
        pth = os.path.join(PREV, f"Hands_grip_{pn}_fp.png")
        ivlib.render(pth, cam, res=(1600, 900), samples=RENDER_SAMPLES + 8)
        made.append(label(pth, f"{pn}: first-person camera ({FP['fov']:.0f} deg horizontal FOV, eye at the head), full body posed, arms two-bone IK",
                          "IK: " + json.dumps(ik)))
        # external full-body check of the same stance (shoulders -> hands continuity)
        cam = ivlib.camera(f"cfb_{pn}", (0.95, -1.35, 1.75), (0.0, -0.35, 1.35), lens=45, up=(0, 0, 1))
        pth = os.path.join(PREV, f"Hands_grip_{pn}_stance.png")
        ivlib.render(pth, cam, res=(1280, 720), samples=RENDER_SAMPLES)
        made.append(label(pth, f"{pn}: stance used for the first-person view (arms continuous from the shoulders)"))
        head_hide()
        if mod:
            mod.show_render = True
        rig.matrix_world = Matrix.Identity(4)
        reset_pistol(props)
        C.reset_pose(arm)
    return made


def hide_head(ob, arm):
    """Mask the head / neck for the first-person camera (the camera sits inside the head)."""
    names = [b.name for b in arm.data.bones]
    D = C.read_weights(ob, names)
    m = ~C.dominant_bone_mask(D, names, ["head", "neck_01"])
    vg = ob.vertex_groups.get("IVH_NoHead") or ob.vertex_groups.new(name="IVH_NoHead")
    vg.add([int(i) for i in np.nonzero(m)[0]], 1.0, 'REPLACE')
    mod = ob.modifiers.new("IVH_NoHeadMask", 'MASK')
    mod.vertex_group = "IVH_NoHead"

    def undo():
        ob.modifiers.remove(mod)
    return undo


def stance_pistol_objects(arm, lib, props):
    C.reset_pose(arm)
    e = lib["poses"]["pistol_2h"]
    eye = np.array(FP["eye"])
    Rz = np.array(Matrix.Rotation(math.radians(-90), 4, 'Z'))
    W = Rz.copy()
    W[:3, 3] = eye + np.array(FP["pistol_offset"]) - W[:3, :3] @ np.array([0.0, 0.0, PISTOL["bore_z"] + 0.035])
    for o in props["pistol"]["parts"]:
        if "_rest" not in o:
            o["_rest"] = [list(r) for r in o.matrix_world]
        o.matrix_world = Matrix(W.tolist()) @ Matrix(o["_rest"])
    bpy.context.view_layer.update()
    ik = {}
    for s, pole in (("r", (-0.5, 0.3, -1.0)), ("l", (0.5, 0.3, -1.0))):
        H = W @ json_to_mat(e["hand_attach"][s])
        ik[s] = HN.arm_ik(arm, s, H, pole)
        C.pose_hand_anat(arm, s, e["angles"][s], C.hand_rest_angles(arm, s))
    bpy.context.view_layer.update()
    return ik, W


def reset_pistol(props):
    for o in props["pistol"]["parts"]:
        if "_rest" in o:
            o.matrix_world = Matrix(o["_rest"])
    bpy.context.view_layer.update()


def render_sections(arm, lib):
    """2D sections through each finger's curl plane at the full fist (bare hand and glove)."""
    from PIL import Image, ImageDraw
    body = bpy.data.objects[BODY]
    out = []
    for variant, ob in (("bare", body), ("coyote", bpy.data.objects[GL["l"]])):
        C.reset_pose(arm)
        C.pose_hand_anat(arm, "l", lib["poses"]["fist_full"]["angles"]["l"], C.hand_rest_angles(arm, "l"))
        co = C.mesh_arrays(ob, evaluated=True)
        tris = HN.mesh_tris(ob.data)
        names = [g.name for g in ob.vertex_groups]
        W = HN.read_groups(ob, names)
        dom = np.array(names)[W.argmax(1)]
        tdom = dom[tris[:, 0]]
        w, d, r, p = [np.array(v) for v in C.palm_frame(arm, "l")]
        panels = []
        for f in C.FINGERS4:
            P = np.array([C.bone_world(arm, f"{f}_0{k}_l") for k in (1, 2, 3)] + [C.bone_world(arm, f"{f}_03_l", "tail")])
            nrm = np.cross(P[1] - P[0], P[3] - P[0]); nrm /= np.linalg.norm(nrm)
            e1 = d - nrm * (d @ nrm); e1 /= np.linalg.norm(e1); e2 = np.cross(nrm, e1)
            dist = (co - P[0]) @ nrm
            S, Wd = 4000, 460
            im = Image.new("RGB", (Wd, Wd + 30), (250, 250, 250)); dr = ImageDraw.Draw(im)
            cx, cy = Wd * 0.55, Wd * 0.50
            for t in range(len(tris)):
                i = tris[t]; dd = dist[i]
                if (dd > 0).all() or (dd < 0).all():
                    continue
                pts = []
                for a, b in ((0, 1), (1, 2), (2, 0)):
                    if (dd[a] > 0) != (dd[b] > 0):
                        u = dd[a] / (dd[a] - dd[b]); pts.append(co[i[a]] + u * (co[i[b]] - co[i[a]]))
                if len(pts) != 2:
                    continue
                q = [((x - P[0]) @ e1, (x - P[0]) @ e2) for x in pts]
                if max(abs(v) for xy in q for v in xy) > 0.055:
                    continue
                b = tdom[t]
                col = (40, 40, 40) if not b.startswith(C.FINGERS4) else {"01": (30, 90, 220), "02": (20, 160, 60), "03": (220, 40, 30)}[b.split("_")[1]]
                dr.line([(cx + q[0][0] * S, cy - q[0][1] * S), (cx + q[1][0] * S, cy - q[1][1] * S)], fill=col, width=2)
            for k in range(4):
                q = P[k] - P[0]; x, y = q @ e1, q @ e2
                dr.ellipse([cx + x * S - 3, cy - y * S - 3, cx + x * S + 3, cy - y * S + 3], fill=(255, 150, 0))
            dr.line([(10, Wd + 12), (10 + 0.01 * S, Wd + 12)], fill=(0, 0, 0), width=3)
            dr.text((58, Wd + 6), "1 cm", fill=(0, 0, 0))
            dr.text((8, 6), f"{variant} full fist - {f} curl plane", fill=(0, 0, 0))
            dr.text((8, 20), "black = palm / hand, blue / green / red = proximal / middle / distal", fill=(60, 60, 60))
            panels.append(im)
        sheet = Image.new("RGB", (4 * 460, 490), (255, 255, 255))
        for k, im in enumerate(panels):
            sheet.paste(im, (k * 460, 0))
        pth = os.path.join(PREV, f"Hands_sections_fist_{variant}.png")
        sheet.save(pth)
        out.append(pth)
    C.reset_pose(arm)
    return out


def render(only=None):
    t0 = time.time()
    arm, lib, props = load_pose_scene()
    for o in props["rifle"]["parts"] + props["pistol"]["parts"]:
        o.hide_render = True
    render_setup((0.3, -0.2, 1.1), 1.2)
    want = lambda k: only is None or k in only           # noqa: E731
    made = []
    if want("sections"):
        made += render_sections(arm, lib)
    if want("hand01"):
        made += render_hand01(arm, lib)
    if want("black"):
        made += render_hand01(arm, lib, variants=("black",), poses=("open_flat", "fist_50", "fist_full"))
    if want("closeups"):
        made += render_closeups(arm, lib)
    if want("grips"):
        made += render_grips(arm, lib, props)
    log("renders", len(made), round(time.time() - t0, 1), "s")
    allp = sorted(glob.glob(os.path.join(PREV, "Hands_*.png")))
    return {"images": [rel(p) for p in allp], "seconds_this_run": round(time.time() - t0, 1)}


STAGE_FUNCS["render"] = render


# =============================================================================
# stage: export
# =============================================================================

ANIM_FBX = os.path.join(FBX_DIR, "A_Hand_Poses.fbx")


def _export_anim_fbx(path):
    """Skeleton + every hand-pose action as FBX takes (Unreal: import as animations onto the
    SK_Human_Base skeleton).  Same axis / centimetre conventions as ivlib.FBX_UNREAL_OPTS."""
    bpy.ops.wm.open_mainfile(filepath=BLEND)
    arm = bpy.data.objects[ARM]
    for o in list(bpy.context.scene.objects):
        if o is not arm:
            o.hide_set(False)
    sc = bpy.context.scene
    sc.unit_settings.scale_length = 0.01
    arm.matrix_world = Matrix.Scale(100.0, 4) @ arm.matrix_world
    bpy.context.view_layer.update()
    ivlib.select([arm], arm)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    sc.frame_start, sc.frame_end = 1, 41
    opts = dict(ivlib.FBX_UNREAL_OPTS)
    opts.update(bake_anim=True, bake_anim_use_all_actions=True, bake_anim_use_nla_strips=False,
                bake_anim_force_startend_keying=True, bake_anim_simplify_factor=0.0,
                bake_anim_step=1.0, object_types={'ARMATURE'})
    arm.animation_data_create()
    arm.animation_data.action = None
    bpy.ops.export_scene.fbx(filepath=path, use_selection=True, **opts)
    return {"path": rel(path), "bytes": os.path.getsize(path), "actions": sorted(a.name for a in bpy.data.actions)}


def _export_glb(path, objects, material):
    bpy.ops.wm.open_mainfile(filepath=BLEND)
    objs = [bpy.data.objects[n] for n in objects]
    for o in objs:
        if o.type == 'MESH' and o.name.startswith("SK_Glove"):
            o.data.materials.clear()
            o.data.materials.append(bpy.data.materials[material])
    ivlib.select(objs, objs[0])
    opts = dict(ivlib.GLB_OPTS)
    opts.update(export_animations=True, export_animation_mode='ACTIONS', export_frame_range=False,
                export_force_sampling=True, export_anim_single_armature=True)
    bpy.ops.export_scene.gltf(filepath=path, use_selection=True, **opts)
    return {"path": rel(path), "bytes": os.path.getsize(path)}


def _reimport_anim(path, lib):
    """Re-import the animation FBX / GLB in a clean scene and compare every static pose's finger
    rotations (frame 1) with the pose library (quaternion angle, degrees)."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    if path.lower().endswith(".fbx"):
        bpy.ops.import_scene.fbx(filepath=path, ignore_leaf_bones=False, automatic_bone_orientation=False)
    else:
        bpy.ops.import_scene.gltf(filepath=path)
    arms = [o for o in bpy.context.scene.objects if o.type == 'ARMATURE']
    a = arms[0]
    acts = {x.name.split("|")[-1]: x for x in bpy.data.actions}
    res = {"actions_found": len(bpy.data.actions), "compared": {}, "max_err_deg": 0.0, "missing": []}
    rest = {s: C.hand_rest_angles(a, s) for s in ("l", "r")}
    a.animation_data_create()
    for pn, e in lib["poses"].items():
        an = e["action"]
        cand = [x for k, x in acts.items() if k == an or k.endswith(an) or an in k]
        if not cand:
            res["missing"].append(an)
            continue
        act = cand[0]
        a.animation_data.action = act
        if act.slots:
            a.animation_data.action_slot = act.slots[0]
        bpy.context.scene.frame_set(1)
        bpy.context.view_layer.update()
        err = 0.0
        for s, pz in e["angles"].items():
            q = C.hand_pose_quats(pz, s, rest[s])
            for n, qq in q.items():
                pb = a.pose.bones[n]
                qa = pb.matrix_basis.to_quaternion()
                d = qa.rotation_difference(qq).angle
                err = max(err, math.degrees(min(d, 2 * math.pi - d)))
        res["compared"][pn] = round(err, 4)
        res["max_err_deg"] = max(res["max_err_deg"], round(err, 4))
    return res


def export():
    t0 = time.time()
    lib = json.load(open(os.path.join(HERE, POSES_JSON)))
    out = {}
    fbx_hands = os.path.join(FBX_DIR, "SK_Hands_Gloved.fbx")
    fbx_body = os.path.join(FBX_DIR, "SK_Human_Base_Gloved.fbx")
    out["fbx_hands"] = ivlib.export_fbx(BLEND, [ARM, GL["l"], GL["r"]], fbx_hands)
    out["fbx_body_gloved"] = ivlib.export_fbx(BLEND, [ARM, BODY + "_Gloved", GL["l"], GL["r"]], fbx_body)
    out["fbx_anim"] = _export_anim_fbx(ANIM_FBX)
    glbs = {}
    for pal in ("Coyote", "Black"):
        pth = os.path.join(GLB_DIR, f"Hands_Gloved_{pal}.glb")
        glbs[pal] = _export_glb(pth, [ARM, GL["l"], GL["r"]], f"M_Glove_{pal}")
    pth = os.path.join(GLB_DIR, "Human_Base_Gloved_Coyote.glb")
    glbs["BodyCoyote"] = _export_glb(pth, [ARM, BODY + "_Gloved", GL["l"], GL["r"]], "M_Glove_Coyote")
    out["glb"] = glbs
    for d in (FBX_DIR, GLB_DIR):
        with open(os.path.join(d, POSES_JSON), "w") as f:
            json.dump(lib, f, indent=1)
    out["pose_json"] = [rel(os.path.join(FBX_DIR, POSES_JSON)), rel(os.path.join(GLB_DIR, POSES_JSON))]
    # re-import checks (clean subprocesses for the skinned files; in-process for the clips)
    chk = {}
    for k, pth in (("fbx_hands", fbx_hands), ("fbx_body_gloved", fbx_body),
                   ("glb_coyote", os.path.join(GLB_DIR, "Hands_Gloved_Coyote.glb")),
                   ("glb_black", os.path.join(GLB_DIR, "Hands_Gloved_Black.glb"))):
        r = C.reimport_skinned_check(pth)
        chk[k] = {"bones": r.get("bone_count"), "armature_scale": r.get("armature_object_scale"),
                  "dimensions_m": r.get("dimensions_m"),
                  "meshes": {n: {kk: m.get(kk) for kk in ("vertices", "tris", "unweighted_vertices", "max_influences",
                                                           "weight_sum_min", "weight_sum_max", "armature_modifier",
                                                           "groups_not_bones")} for n, m in r.get("meshes", {}).items()}}
        ok = r.get("bone_count") == 57 and all(m.get("unweighted_vertices", 1) == 0 and m.get("max_influences", 9) <= 4
                                               for m in r.get("meshes", {}).values())
        chk[k]["verdict"] = "PASS" if ok else "FAIL"
    chk["fbx_anim"] = _reimport_anim(ANIM_FBX, lib)
    chk["fbx_anim"]["verdict"] = "PASS" if (not chk["fbx_anim"]["missing"] and chk["fbx_anim"]["max_err_deg"] < 0.5) else "FAIL"
    chk["glb_anim"] = _reimport_anim(os.path.join(GLB_DIR, "Hands_Gloved_Coyote.glb"), lib)
    chk["glb_anim"]["verdict"] = "PASS" if (not chk["glb_anim"]["missing"] and chk["glb_anim"]["max_err_deg"] < 0.5) else "FAIL"
    out["reimport"] = chk
    out["seconds"] = round(time.time() - t0, 1)
    log("export", json.dumps({k: v.get("verdict") for k, v in chk.items()}))
    return out


STAGE_FUNCS["export"] = export


if __name__ == "__main__":
    main()
