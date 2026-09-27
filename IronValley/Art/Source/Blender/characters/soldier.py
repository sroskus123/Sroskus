"""
soldier.py -- Iron Valley infantry soldier (SK_Soldier): clothing derived from SK_Human_Base
(deforms with the rig), rigid gear bound to single bones, three team variants, LOD0/1/2, the
first-person arms (FP_Arms), evidence renders, validation and exports.  Deterministic.

    python3 soldier.py                                   # all stages
    python3 soldier.py --stages build                    # geometry + binding + UVs -> soldier.blend
    python3 soldier.py --stages textures,lods,validate
    python3 soldier.py --stages render --only teams,poses
    python3 soldier.py --stages export

Inputs (read only): Art/Source/Blender/characters/hands_gloves.blend (body, gloves, 57-bone rig),
Art/Source/Blender/characters/Hand_Poses.json (grip poses), Art/Source/Blender/weapons/iv7_carbine.blend
(IV-7 rifle, sockets, magazine), Art/Textures/Characters/Gloves/* (glove textures).
Outputs: soldier.blend (next to this script), Art/Textures/Characters/Soldier/*,
Art/Export/FBX/SK_Soldier*.fbx, FP_Arms*.fbx, Art/Export/GLB/Soldier_*.glb, FP_Arms_*.glb,
Art/Previews/Soldier/*.png + Soldier_validation.json.
Spec: Art/Reference/SOLDIER_spec.md
"""

import argparse
import json
import math
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))

import bpy                              # noqa: E402
import bmesh                            # noqa: E402
import numpy as np                      # noqa: E402
from mathutils import Vector, Matrix    # noqa: E402

import ivlib                            # noqa: E402
import ivchar as C                      # noqa: E402
import ivhands as HN                    # noqa: E402
import ivsoldier as S                   # noqa: E402
import soldier_cloth as SC              # noqa: E402

IV = C.IV_ROOT
SRC_BLEND = os.path.join(HERE, "hands_gloves.blend")
BLEND = os.path.join(HERE, "soldier.blend")
RIFLE_BLEND = os.path.join(IV, "Art", "Source", "Blender", "weapons", "iv7_carbine.blend")
POSES_JSON = os.path.join(HERE, "Hand_Poses.json")
PREV = os.path.join(IV, "Art", "Previews", "Soldier")
TEX_DIR = os.path.join(IV, "Art", "Textures", "Characters", "Soldier")
GLOVE_TEX = os.path.join(IV, "Art", "Textures", "Characters", "Gloves")
FBX_DIR = os.path.join(IV, "Art", "Export", "FBX")
GLB_DIR = os.path.join(IV, "Art", "Export", "GLB")
REPORT = os.path.join(PREV, "Soldier_validation.json")
ARM = "Armature"
BODY = "SK_Human_Base"
GLOVES = {"l": "SK_Glove_L", "r": "SK_Glove_R"}


def log(*a):
    print("[soldier]", *a, flush=True)


def rel(p):
    return os.path.relpath(p, IV)


# =============================================================================
# design inputs (metres, rest A-pose, character faces -Y)
# =============================================================================

SHIRT = dict(
    bottom_z=1.030,            # shirt tail (inside the trousers, which start at ~1.06-1.08)
    cuff_from_wrist=0.052,     # sleeve end, proximal of the wrist joint along the forearm axis (glove cuff reaches 0.080)
    collar_z0=1.556, collar_tilt=0.26, collar_h=0.030,   # neck line z = z0 + tilt * (y + 0.05); stand-up collar height
    off_torso=0.0045, off_shoulder=0.0065, off_upper=0.0115, off_fore=0.0100, off_cuff=0.0088, off_collar=0.0085,
)
TROUSERS = dict(
    waist_z0=1.072, waist_tilt=0.12,   # waistband top z = z0 + tilt * y  (lower at the front)
    hem_z=0.152,                       # hem over the boot shaft
    off_waist=0.0065, off_seat=0.0095, off_thigh=0.0150, off_knee=0.0120, off_calf=0.0150, off_hem=0.0185,
)
BALACLAVA = dict(off=0.0026, below_collar=0.045, gaiter_off=0.0190, gaiter_top=1.657,
                 eye_c=(0.0, -0.128, 1.6865), eye_a=0.055, eye_b=0.0155)   # eye window ellipse (x half, z half)
TEAMS = {
    # Web/src/data/teams.json colours; camo colourways per team (linear sRGB -> converted at write)
    "Alfa": dict(color="#3d8bfd", dark="#1f4f99", symbol="circle"),
    "Bravo": dict(color="#e5533d", dark="#8a2a1c", symbol="triangle"),
    "Charlie": dict(color="#f2c230", dark="#8f6f12", symbol="square"),
}


# =============================================================================
# helpers
# =============================================================================

def open_src():
    bpy.ops.wm.open_mainfile(filepath=SRC_BLEND)
    arm = bpy.data.objects[ARM]
    body = bpy.data.objects[BODY]
    C.reset_pose(arm)
    C.clear_correctives(body)
    return arm, body


def forearm_u(arm, co):
    """Signed distance along the forearm axis from the wrist joint (negative = towards the elbow),
    evaluated with the side chosen by x."""
    u = np.zeros(len(co))
    for s, sg in (("l", 1), ("r", -1)):
        wj, ax = HN.forearm_axis(arm, s)
        m = co[:, 0] * sg > 0
        u[m] = (co[m] - wj) @ ax
    return u


def limb_param(arm, co, bone_fmt):
    """Normalised position along a bone (0 head .. 1 tail) for each point, side by x."""
    t = np.zeros(len(co))
    for s, sg in (("l", 1), ("r", -1)):
        b = arm.data.bones[bone_fmt.format(s=s)]
        h, tl = np.array(b.head_local), np.array(b.tail_local)
        ax = tl - h
        m = co[:, 0] * sg > 0
        t[m] = ((co[m] - h) @ ax) / (ax @ ax)
    return t


def smooth_field(f, nb, iters=6, alpha=0.5):
    f = np.array(f, float, copy=True)
    for _ in range(iters):
        f = (1 - alpha) * f + alpha * np.array([f[n].mean() if n else f[i] for i, n in enumerate(nb)])
    return f


def face_keep(me, vert_ok, centre_ok=None):
    keep = np.zeros(len(me.polygons), bool)
    for p in me.polygons:
        vs = list(p.vertices)
        keep[p.index] = all(vert_ok[v] for v in vs) and (centre_ok is None or centre_ok(np.array(p.center)))
    return keep


def prune_shape_keys(ob, eps=1e-4):
    me = ob.data
    if me.shape_keys is None:
        return []
    base = np.empty(len(me.vertices) * 3)
    me.shape_keys.key_blocks[0].data.foreach_get("co", base)
    kept = []
    for k in list(me.shape_keys.key_blocks[1:]):
        c = np.empty(len(me.vertices) * 3)
        k.data.foreach_get("co", c)
        if np.abs(c - base).max() < eps:
            ob.shape_key_remove(k)
        else:
            kept.append(k.name)
    if not kept and me.shape_keys is not None:
        ob.shape_key_clear()
    return kept


def offset_garment(ob, body_bvh, d, fixed=None, iters=10, alpha=0.45, clear_frac=0.8):
    co = S.co_of(ob)
    tris = S.tris_of(ob.data)
    N = S.vnormals(co, tris)
    nb = S.neighbours(ob.data)
    d = smooth_field(d, nb, 8, 0.5)
    new = co + N * d[:, None]
    fx = S.boundary_vertices(ob.data) if fixed is None else fixed
    new = S.relax_offset(new, body_bvh, nb, fx, d, iters=iters, alpha=alpha, min_clear=d * clear_frac)
    S.set_co(ob, new)
    return d


# =============================================================================
# stage: build -- garments
# =============================================================================

def shirt_faces(arm, body, bf):
    co, dom = bf["co"], bf["dom"]
    y = co[:, 1]
    collar = SHIRT["collar_z0"] + SHIRT["collar_tilt"] * (y + 0.05)
    bones = {"spine_01", "spine_02", "spine_03", "clavicle_l", "clavicle_r", "neck_01", "pelvis"}
    arm_b = {f"{b}_{s}" for b in ("upperarm", "upperarm_twist_01", "lowerarm", "lowerarm_twist_01") for s in "lr"}
    ok = np.isin(dom, list(bones | arm_b)) | ((dom == "head") & (co[:, 2] < collar + SHIRT["collar_h"] + 0.02)
                                              & (co[:, 1] > -0.07))          # nape: the collar reaches up the back of the neck
    ok &= co[:, 2] >= SHIRT["bottom_z"] - 0.02
    ok &= ~(np.isin(dom, ["neck_01", "head"]) & (co[:, 2] > collar + SHIRT["collar_h"] + 0.02))

    def centre_ok(c):
        if c[2] < SHIRT["bottom_z"]:
            return False
        uc = forearm_u(arm, c[None])[0]
        if abs(c[0]) > 0.3 and uc > -SHIRT["cuff_from_wrist"]:
            return False
        cz = SHIRT["collar_z0"] + SHIRT["collar_tilt"] * (c[1] + 0.05) + SHIRT["collar_h"]
        if c[2] > cz:
            return False
        return True
    return face_keep(body.data, ok, centre_ok)


def snap_sleeve_ends(G, arm):
    """Sleeve-end boundary vertices moved along the forearm axis onto the cut plane (the face
    selection is jagged)."""
    b = G.boundary()
    u = forearm_u(arm, G.V)
    ends = b & (np.abs(G.V[:, 0]) > 0.30)
    for s, sg in (("l", 1), ("r", -1)):
        wj, ax = HN.forearm_axis(arm, s)
        m = ends & (G.V[:, 0] * sg > 0)
        G.V[m] += ((-SHIRT["cuff_from_wrist"] - u[m])[:, None]) * ax[None, :]
    return int(ends.sum())


GARMENT_TRIS = {"Soldier_Shirt": 10500, "Soldier_Trousers": 7500}
PANEL_IDS = {}


def _pid(name):
    return PANEL_IDS.setdefault(name, len(PANEL_IDS))


def shirt_panels(G):
    """Sewing panels of the combat shirt (per face): front L / R (zip at the centre), back + yoke,
    collar, sleeves with an underside seam, elbow patches, cuffs.  Returns (labels, extra_cut,
    grain per face)."""
    F = G.F
    Fc = SC.face_values(F, G.V)
    Fs = SC.face_values(F, G.src)
    msl = SC.face_values(F, G.attrs["m_sleeve"])
    sel_ = SC.face_values(F, G.attrs["sl_s_el"])
    dend = SC.face_values(F, G.attrs["sl_dend"])
    post = SC.face_values(F, G.attrs["sl_post"])
    ph = np.array([np.arctan2(np.sin(G.attrs["sl_phi"][f]).mean(), np.cos(G.attrs["sl_phi"][f]).mean()) for f in F])
    T = SC.face_values(F, G.attrs["sl_T"])
    neck = SHIRT["collar_z0"] + SHIRT["collar_tilt"] * (Fs[:, 1] + 0.05) - 0.004
    lab = np.zeros(len(F), np.int64)
    grain = np.tile(np.array([0.0, 0.0, 1.0]), (len(F), 1))
    for i in range(len(F)):
        x, y, z = Fc[i]
        sd = "l" if x > 0 else "r"
        if msl[i] > 0.5:
            if dend[i] < SC.SLEEVE["cuff_band"]:
                nm = f"cuff_{sd}"
            elif abs(sel_[i] + 0.005) < 0.070 and post[i] < math.radians(62):
                nm = f"elbow_{sd}"
            else:
                nm = f"sleeve_{sd}"
            grain[i] = T[i]
        elif Fs[i, 2] > neck[i] and abs(x) < 0.12:
            nm = "collar"
        elif Fs[i, 1] < 0.0:
            nm = f"front_{sd}"
        else:
            nm = "yoke" if z > 1.435 else "back"
        lab[i] = _pid("shirt_" + nm)
    names_ = {v: k for k, v in PANEL_IDS.items()}

    def extra(a, b):
        na, nb_ = names_[lab[a]], names_[lab[b]]
        if na != nb_:
            return False
        if na.startswith(("shirt_sleeve", "shirt_cuff")):
            # underside seam at phi = 0 (the hanging side)
            return (np.sign(ph[a]) != np.sign(ph[b])) and abs(ph[a]) < 1.2 and abs(ph[b]) < 1.2
        if na == "shirt_collar":
            return (np.sign(Fc[a, 0]) != np.sign(Fc[b, 0])) and Fc[a, 1] < 0
        return False
    return lab, extra, grain


def trouser_panels(G):
    """Panels of the combat trousers: waistband, front / back per leg (outseam, inseam, centre
    seams), knee patches."""
    F = G.F
    Fc = SC.face_values(F, G.V)
    Fs = SC.face_values(F, G.src)
    ml = SC.face_values(F, G.attrs["m_leg"])
    skn = SC.face_values(F, G.attrs["lg_s_kn"])
    psi = np.degrees(np.array([np.arctan2(G.attrs["lg_sin"][f].mean(), G.attrs["lg_cos"][f].mean()) for f in F])) % 360.0
    waist = TROUSERS["waist_z0"] + TROUSERS["waist_tilt"] * Fs[:, 1]
    lab = np.zeros(len(F), np.int64)
    for i in range(len(F)):
        x, y, z = Fc[i]
        sd = "l" if x > 0 else "r"
        if Fs[i, 2] - waist[i] > -0.036:
            nm = "waistband"
        elif ml[i] > 0.5:
            fr = psi[i] >= 270.0 or psi[i] < 90.0
            ang = min(psi[i], 360.0 - psi[i])
            if abs(skn[i] + 0.012) < 0.085 and ang < 58.0:
                nm = f"knee_{sd}"
            else:
                nm = f"{'front' if fr else 'back'}_{sd}"
        else:
            nm = f"{'front' if Fs[i, 1] < 0.0 else 'back'}_{sd}"
        lab[i] = _pid("trousers_" + nm)
    names_ = {v: k for k, v in PANEL_IDS.items()}

    def extra(a, b):
        if lab[a] != lab[b]:
            return False
        if names_[lab[a]] == "trousers_waistband":
            return (np.sign(Fc[a, 0]) != np.sign(Fc[b, 0])) and Fc[a, 1] < 0
        return False
    grain = np.tile(np.array([0.0, 0.0, 1.0]), (len(F), 1))
    return lab, extra, grain


def finalize_garment(G, name, col, arm, labels, extra, grain, target_tris, info):
    """Panels -> straightened seams -> hi-res object (kept hidden as the normal-map source and the
    first-person source) -> UV unwrap per panel, grain-oriented islands -> game-resolution copy
    (collapse decimation keeps the UV seams), weights and corrective shapes re-transferred."""
    seams, ef = SC.panel_seam_edges(G.F, labels, extra)
    G.V = SC.smooth_seams(G.V, G.F, seams, ef, S.bvh(G.V, G.tris()))
    hi = G.to_object("_HI_" + name, col, arm, keys=True)
    hi.data.attributes.new("iv_panel", 'INT', 'FACE').data.foreach_set("value", labels.astype(np.int32))
    n_seam = SC.unwrap_panels(hi, seams)
    isl = SC.islands_from_seams(G.F, seams, ef)
    SC.orient_islands(hi, isl, grain)
    lo = hi.copy()
    lo.data = hi.data.copy()
    lo.name = name
    lo.data.name = name
    col.objects.link(lo)
    if lo.data.shape_keys is not None:
        lo.shape_key_clear()
    for m_ in list(lo.modifiers):
        lo.modifiers.remove(m_)
    tris = SC.decimate_uv_safe(lo, target_tris)
    hv, ht = G.V, G.tris()
    W = S.transfer_weights(hv, ht, G.W, S.co_of(lo))
    S.write_W(lo, W, G.names, arm)
    SC.transfer_keys_from_arrays(lo, hv, ht, G.keys)
    hi.hide_viewport = True
    hi.hide_render = True
    pn = json.dumps({str(v): k for k, v in PANEL_IDS.items()})
    lo["iv_panels"] = pn
    hi["iv_panels"] = pn
    info[name] = {"hi_tris": int(len(ht)), "game_tris": int(tris), "panels": int(len(np.unique(labels))),
                  "islands": int(isl.max() + 1), "seam_edges": n_seam}
    return lo


def build_shirt(arm, body, bf, col, body_bvh, glove_pts):
    keep = shirt_faces(arm, body, bf)
    names = bf["names"]
    G = SC.Garment.from_body(body, keep, names)
    G.subdivide()
    G.subdivide()
    info = {"snapped_cuff_vertices": snap_sleeve_ends(G, arm)}
    co = G.V
    dom = G.dom()
    TP = SC.TORSO
    d = np.full(len(co), TP["default"])
    front = co[:, 1] < -0.06
    backm = co[:, 1] > 0.03
    d[front] = TP["chest"]
    d[backm] = TP["back"]
    sidem = (np.abs(co[:, 0]) > 0.11) & ~front & ~backm
    d[sidem] = TP["side"]
    d[np.isin(dom, ["clavicle_l", "clavicle_r"])] = TP["shoulder"]
    d[np.isin(dom, ["neck_01", "head"])] = TP["collar"]
    waist = TROUSERS["waist_z0"] + TROUSERS["waist_tilt"] * co[:, 1]
    zrel = co[:, 2] - waist
    d = d + TP["blouse"] * SC.bump(zrel, TP["blouse_c"], TP["blouse_w"])
    d[zrel < -0.004] = TP["tail"]
    V_t, d, L = SC.torso_offset(G, d, body_bvh)
    # trunk: convex sections hanging from the chest / shoulder blades (does not follow the muscles)
    wsp = G.wsum(["spine_01", "spine_02", "spine_03", "pelvis"])
    mt = SC.smoothstep(0.55, 0.90, wsp) * (1.0 - SC.smoothstep(1.40, 1.48, co[:, 2]))
    bmask = np.isin(bf["dom"], ["spine_01", "spine_02", "spine_03", "pelvis"]) & (bf["co"][:, 2] > 0.95) & (bf["co"][:, 2] < 1.52)

    def ease_torso(V, psi):
        a = np.abs(((psi + 180.0) % 360.0) - 180.0)
        e = np.interp(a, [0, 90, 180], [TP["front"], TP["sides"], TP["backe"]])
        w = TROUSERS["waist_z0"] + TROUSERS["waist_tilt"] * V[:, 1]
        zr = V[:, 2] - w
        e = e + TP["blouse"] * SC.bump(zr, TP["blouse_c"], TP["blouse_w"])
        return np.where(zr < -0.004, TP["tail"], e)
    Vh = SC.trunk_design(G, bf["co"], bmask, (0.0, -0.01, 1.52), (0.0, -0.01, 0.95), ease_torso, TP["k_down"], TP["k_up"], mt)
    V_t = V_t * (1 - mt[:, None]) + Vh * mt[:, None]
    send = {}
    for s in ("l", "r"):
        ax = SC.arm_axis(arm, s)
        send[s] = ax.L[2] - SHIRT["cuff_from_wrist"]
    Vt, m, h = SC.sleeve_design(G, arm, bf["co"], bf["W"], names, glove_pts, send, info)
    G.attrs["m_sleeve"] = m.copy()
    # waist gathers above the waistband (the shirt bloused over the trousers)
    th = np.arctan2(co[:, 0], -co[:, 1])
    env = SC.bump(zrel, TP["blouse_c"] - 0.004, TP["blouse_w"] * 0.8) * (1 - m)
    h += TP["gather_amp"] * env * SC.buckle(TP["gather_n"] * th, zrel * 40.0, 5, wander=1.8, fade=0.8)
    G.V = SC.finish(G, V_t, Vt, m, h, body_bvh, L)
    labels, extra, grain = shirt_panels(G)
    ob = finalize_garment(G, "Soldier_Shirt", col, arm, labels, extra, grain, GARMENT_TRIS["Soldier_Shirt"], info)
    ob["iv_src"] = "body"
    ob["iv_info"] = json.dumps(info)
    return ob, G


def trousers_faces(arm, body, bf):
    co, dom = bf["co"], bf["dom"]
    waist = TROUSERS["waist_z0"] + TROUSERS["waist_tilt"] * co[:, 1]
    legs = {f"{b}_{s}" for b in ("thigh", "calf") for s in "lr"}
    ok = np.isin(dom, list(legs | {"pelvis", "spine_01", "spine_02"}))
    ok &= co[:, 2] <= waist + 0.02
    ok &= co[:, 2] >= TROUSERS["hem_z"] - 0.02

    def centre_ok(c):
        return (c[2] <= TROUSERS["waist_z0"] + TROUSERS["waist_tilt"] * c[1]) and c[2] >= TROUSERS["hem_z"]
    return face_keep(body.data, ok, centre_ok)


def build_trousers(arm, body, bf, col, body_bvh):
    keep = trousers_faces(arm, body, bf)
    names = bf["names"]
    G = SC.Garment.from_body(body, keep, names)
    G.subdivide()
    G.subdivide()
    # clean edges: waistband top on the waist line, hems on the hem height
    b = G.boundary()
    waist = TROUSERS["waist_z0"] + TROUSERS["waist_tilt"] * G.V[:, 1]
    top = b & (G.V[:, 2] > 0.8)
    G.V[top, 2] = waist[top]
    hem = b & (G.V[:, 2] < 0.4)
    G.V[hem, 2] = TROUSERS["hem_z"]
    co = G.V
    PP = SC.PELVIS
    d = np.full(len(co), PP["front"])
    d[co[:, 1] > -0.01] = PP["seat"]
    zrel = co[:, 2] - waist
    d[zrel > -0.045] = PP["waist"]
    cr = (np.abs(co[:, 0]) < 0.06) & (co[:, 2] < 0.90)
    d[cr] = PP["crotch"]
    d[co[:, 2] < 0.85] = np.maximum(d[co[:, 2] < 0.85], 0.016)
    V_t, d, L = SC.torso_offset(G, d, body_bvh)
    # pelvis: convex sections (smooth seat and crotch, no gluteal fold / groin detail)
    wp = G.wsum(["pelvis", "spine_01", "spine_02"])
    mt = SC.smoothstep(0.45, 0.85, wp) * SC.smoothstep(0.86, 0.93, co[:, 2])
    bmask = np.isin(bf["dom"], ["pelvis", "spine_01", "spine_02"]) & (bf["co"][:, 2] > 0.84) & (bf["co"][:, 2] < 1.12)

    def ease_pelvis(V, psi):
        a = np.abs(((psi + 180.0) % 360.0) - 180.0)
        e = np.interp(a, [0, 90, 180], [PP["front"], PP["sides"], PP["back"]])
        w = TROUSERS["waist_z0"] + TROUSERS["waist_tilt"] * V[:, 1]
        k = SC.smoothstep(-0.060, -0.035, V[:, 2] - w)
        return e * (1 - k) + PP["waist"] * k
    Vh = SC.trunk_design(G, bf["co"], bmask, (0.0, 0.0, 1.12), (0.0, 0.0, 0.76), ease_pelvis, PP["k_down"], PP["k_up"], mt)
    V_t = V_t * (1 - mt[:, None]) + Vh * mt[:, None]
    info = {}
    Vt, m, h = SC.leg_design(G, arm, bf["co"], bf["W"], names, info)
    G.attrs["m_leg"] = m.copy()
    crotch = (np.abs(co[:, 0]) < 0.10) & (co[:, 2] > 0.76) & (co[:, 2] < 0.96)
    G.V = SC.finish(G, V_t, Vt, m, h, body_bvh, L, local_relax=crotch)
    labels, extra, grain = trouser_panels(G)
    ob = finalize_garment(G, "Soldier_Trousers", col, arm, labels, extra, grain, GARMENT_TRIS["Soldier_Trousers"], info)
    ob["iv_info"] = json.dumps(info)
    return ob, G


def enforce_inside(inner, outer, mask_fn, margin):
    """Move `inner` vertices (mask) that are not at least `margin` inside the `outer` garment's
    surface inwards along the outer surface normal (layer order at overlaps, rest pose)."""
    co = S.co_of(inner)
    m = mask_fn(co)
    oc, ot = S.co_of(outer), S.tris_of(outer.data)
    bv = S.bvh(oc, ot)
    idx = np.nonzero(m)[0]
    loc, nor, fi, d = S.nearest_on(bv, co[idx], 0.05)
    ok = fi >= 0
    sd = np.where(((co[idx] - loc) * nor).sum(1) >= 0, d, -d)
    bad = ok & (sd > -margin)
    co[idx[bad]] = loc[bad] - nor[bad] * margin
    S.set_co(inner, co)
    return {"moved": int(bad.sum()), "tested": int(len(idx)), "worst_before_mm": round(float(sd[ok].max()) * 1000, 2) if ok.any() else None}


def enforce_outside(outer, inner, mask_fn, margin):
    """Move `outer` garment vertices (mask) that are not at least `margin` outside the `inner`
    closed surface outwards along its normal."""
    co = S.co_of(outer)
    idx = np.nonzero(mask_fn(co))[0]
    ic, it = S.co_of(inner), S.tris_of(inner.data)
    bv = S.bvh(ic, it)
    loc, nor, fi, d = S.nearest_on(bv, co[idx], 0.05)
    ok = fi >= 0
    sd = np.where(((co[idx] - loc) * nor).sum(1) >= 0, d, -d)
    bad = ok & (sd < margin)
    co[idx[bad]] = loc[bad] + nor[bad] * margin
    S.set_co(outer, co)
    return {"moved": int(bad.sum()), "tested": int(len(idx)), "worst_before_mm": round(float(sd[ok].min()) * 1000, 2) if ok.any() else None}


def eye_window(co):
    c = np.array(BALACLAVA["eye_c"])
    e = ((co[:, 0] - c[0]) / BALACLAVA["eye_a"]) ** 2 + ((co[:, 2] - c[2]) / BALACLAVA["eye_b"]) ** 2
    return (e <= 1.0) & (co[:, 1] < -0.09)


def build_balaclava(arm, body, bf, col, body_bvh):
    co, dom = bf["co"], bf["dom"]
    collar = SHIRT["collar_z0"] + SHIRT["collar_tilt"] * (co[:, 1] + 0.05)
    ok = np.isin(dom, ["head", "neck_01"]) & (co[:, 2] >= collar - BALACLAVA["below_collar"] - 0.02)
    win = eye_window(co)

    def centre_ok(c):
        cz = SHIRT["collar_z0"] + SHIRT["collar_tilt"] * (c[1] + 0.05) - BALACLAVA["below_collar"]
        return c[2] >= cz and not eye_window(c[None])[0]
    keep = face_keep(body.data, ok, centre_ok)
    ob, src = S.copy_faces(body, keep, "Soldier_Balaclava", col)
    # skin patch: the eye window (plus 1 cm under the balaclava edge)
    cc = BALACLAVA["eye_c"]

    def skin_ok(c):
        e = ((c[0] - cc[0]) / (BALACLAVA["eye_a"] + 0.012)) ** 2 + ((c[2] - cc[2]) / (BALACLAVA["eye_b"] + 0.010)) ** 2
        return e <= 1.0 and c[1] < -0.09
    keep_s = face_keep(body.data, np.ones(len(co), bool), skin_ok)
    skin, ssrc = S.copy_faces(body, keep_s, "Soldier_FaceSkin", col)
    if skin.data.shape_keys is not None:
        skin.shape_key_clear()
    if ob.data.shape_keys is not None:
        ob.shape_key_clear()
    # neck gaiter pulled up over the nose: the lower face and the chin are covered by a looser,
    # thicker layer (fills the lip / chin detail); its top edge runs just under the glasses
    c0 = co[src]
    gz = BALACLAVA["gaiter_top"] - 0.0 * c0[:, 0]
    front = np.clip((-c0[:, 1] - 0.035) / 0.05, 0, 1)                 # 0 behind the ears .. 1 at the face
    up = np.clip((gz - c0[:, 2]) / 0.006, 0, 1)                       # below the gaiter's top edge
    low = np.clip((c0[:, 2] - 1.552) / 0.018, 0, 1)                   # thin again inside the collar
    g = front * up * low
    d = BALACLAVA["off"] + (BALACLAVA["gaiter_off"] - BALACLAVA["off"]) * g
    ob["iv_gaiter"] = 1
    offset_garment(ob, body_bvh, d, iters=120, alpha=0.5, clear_frac=0.35)
    # store the gaiter mask for the textures (per vertex attribute)
    at = ob.data.attributes.new("iv_gaiter", 'FLOAT', 'POINT')
    at.data.foreach_set("value", g.astype(np.float32))
    return ob, src, skin, ssrc


def build_garments():
    t0 = time.time()
    arm, body = open_src()
    names = S.bone_names(arm)
    rep = {}
    # athletic build: thicker arms / rounder shoulders on the body proxy and the glove cuffs
    rep["girth_before"] = SC.arm_girths(arm, S.co_of(body), S.tris_of(body.data))
    rep["warp_max_mm"] = round(SC.warp_object(body, arm, names) * 1000, 1)
    for s_ in ("l", "r"):
        SC.warp_object(bpy.data.objects[GLOVES[s_]], arm, names)
    rep["girth_body"] = SC.arm_girths(arm, S.co_of(body), S.tris_of(body.data))
    col = ivlib.collection("Soldier_Clothing")
    bf = S.body_fields(arm, body)
    body_bvh = S.bvh(bf["co"], bf["tris"])
    glove_pts = {s_: S.co_of(bpy.data.objects[GLOVES[s_]]) for s_ in ("l", "r")}
    shirt, gs = build_shirt(arm, body, bf, col, body_bvh, glove_pts)
    trousers, gt = build_trousers(arm, body, bf, col, body_bvh)
    bala, bsrc, skin, ksrc = build_balaclava(arm, body, bf, col, body_bvh)
    rep["shirt_inside_trousers"] = enforce_inside(shirt, trousers, lambda c: c[:, 2] < TROUSERS["waist_z0"] + TROUSERS["waist_tilt"] * c[:, 1] - 0.004, 0.008)
    for ob in (shirt, trousers):
        rep[ob.name] = {"shape_keys": prune_shape_keys(ob)}
    for ob in (shirt, trousers, bala, skin):
        ob.parent = arm
        if not any(m.type == 'ARMATURE' for m in ob.modifiers):
            m = ob.modifiers.new("Armature", 'ARMATURE')
            m.object = arm
        rep.setdefault(ob.name, {})
        rep[ob.name].update(vertices=len(ob.data.vertices), tris=len(S.tris_of(ob.data)))
    rep["shirt_info"] = json.loads(shirt["iv_info"])
    rep["girth_sleeve"] = SC.arm_girths(arm, S.co_of(shirt), S.tris_of(shirt.data), W=S.read_W(shirt, names), names=names)
    rep["seconds"] = round(time.time() - t0, 1)
    log(json.dumps(rep))
    return arm, body, col, rep


# =============================================================================
# stage: build -- boots, gloves, gear
# =============================================================================

import soldier_gear as G     # noqa: E402
import soldier_kit as SK     # noqa: E402

CARRIER = dict(front_w=0.272, front_h=0.330, front_top=1.468, back_w=0.272, back_h=0.355, back_top=1.488,
               bag_t=0.040, R=0.46, cut=0.040, cut_depth=0.075, tilt_front=2.0, tilt_back=3.0, clear=0.0060,
               cb_z=(1.148, 1.292), cb_clear=0.0060, cb_thick=0.016,
               strap_x=0.114, strap_w=0.068, strap_clear=0.0055, strap_thick=0.018)
HELMET = dict(c=(0.0, -0.051, 1.700), ax=0.1175, ay_f=0.1400, ay_b=0.1335, az=0.1330, p=2.3, shell=0.009,
              rim=((0, 1.738), (35, 1.733), (62, 1.716), (90, 1.711), (118, 1.712), (145, 1.692), (180, 1.680)))
BOOT = dict(top_z=0.205, off=0.0058, sole_z=0.030, sole_margin=0.006)
BELT = dict(z=(0.996, 1.048), clear=0.0040, thick=0.015)
KNEE = dict(clear=0.005, thick=0.018, z=(-0.100, 0.050), az=62.0)


def rim_z(az):
    a = abs(((az + 180.0) % 360.0) - 180.0)
    pts = HELMET["rim"]
    for (a0, z0), (a1, z1) in zip(pts[:-1], pts[1:]):
        if a <= a1:
            t = (a - a0) / (a1 - a0)
            t = t * t * (3 - 2 * t)
            return z0 + (z1 - z0) * t
    return pts[-1][1]


def garment_bvh(ob, exclude_bones=None, arm=None):
    """BVH of a garment (optionally without the faces dominated by `exclude_bones`, e.g. the sleeves
    when conforming torso gear)."""
    co = S.co_of(ob)
    tris = S.tris_of(ob.data)
    if exclude_bones:
        names = S.bone_names(arm)
        W = S.read_W(ob, names)
        dom = np.array(names)[W.argmax(1)]
        bad = np.isin(dom, list(exclude_bones))
        tris = tris[~bad[tris].any(1)]
    return S.bvh(co, tris), co


def build_gloves(arm, col, target=3200):
    """Game-resolution copies of the tactical gloves (hands_gloves.py): decimated with UVs kept,
    weights re-transferred from the full-resolution glove (<= 4 influences)."""
    names = S.bone_names(arm)
    out = {}
    for s in ("l", "r"):
        src = bpy.data.objects[GLOVES[s]]
        ob = src.copy()
        ob.data = src.data.copy()
        ob.name = f"Soldier_Glove_{s.upper()}"
        ob.data.name = ob.name
        col.objects.link(ob)
        for m in list(ob.modifiers):
            ob.modifiers.remove(m)
        W0 = S.read_W(src, names)
        co0, t0 = S.co_of(src), S.tris_of(src.data)
        dm = ob.modifiers.new("Dec", 'DECIMATE')
        dm.ratio = target / len(t0)
        dm.use_collapse_triangulate = True
        S.apply_modifier(ob, dm)
        W = S.transfer_weights(co0, t0, W0, S.co_of(ob))
        S.write_W(ob, W, names, arm)
        out[s] = ob
    return out


def build_boots(arm, body, bf, col, body_bvh):
    """Boot uppers: the foot + ankle volume of the body is voxelised (3 mm), morphologically closed
    (fills the gaps between the toes and under the arch), offset outwards by the leather + lining
    thickness, clipped to the sole top and the shaft height, and meshed with marching cubes.
    The shaft top is closed (it sits inside the trouser leg)."""
    from scipy import ndimage
    from skimage import measure
    co, dom = bf["co"], bf["dom"]
    names = bf["names"]
    parts = []
    vox = 0.003
    for s, sg in (("l", 1), ("r", -1)):
        m = (co[:, 0] * sg > 0.02) & (co[:, 2] < BOOT["top_z"] + 0.05)
        lo = co[m].min(0) - 0.03
        hi = co[m].max(0) + 0.03
        hi[2] = BOOT["top_z"] + 0.01
        lo[2] = -0.01
        nx, ny, nz = np.ceil((hi - lo) / vox).astype(int) + 1
        gx, gy, gz = (lo[0] + np.arange(nx) * vox, lo[1] + np.arange(ny) * vox, lo[2] + np.arange(nz) * vox)
        P = np.stack(np.meshgrid(gx, gy, gz, indexing="ij"), -1).reshape(-1, 3)
        sd = S.signed_bvh(body_bvh, P, maxd=0.05)
        sd = np.where(np.isnan(sd), 0.05, sd).reshape(nx, ny, nz)
        occ = sd < 0
        # close with a 12 mm ball (toe gaps, arch), keep the foot only below the shaft top
        r = int(round(0.012 / vox))
        ball = np.linalg.norm(np.stack(np.meshgrid(*[np.arange(-r, r + 1)] * 3, indexing="ij"), -1), axis=-1) <= r
        occ = ndimage.binary_closing(np.pad(occ, r + 1), structure=ball)[r + 1:-r - 1, r + 1:-r - 1, r + 1:-r - 1]
        dout = ndimage.distance_transform_edt(~occ) * vox
        din = ndimage.distance_transform_edt(occ) * vox
        f = np.where(occ, -din, dout)
        f = ndimage.gaussian_filter(f, 1.0)
        off = BOOT["off"] + 0.002
        Z = gz[None, None, :]
        f = np.maximum(f - off, (BOOT["sole_z"] - 0.004) - Z)      # nothing below the sole's top
        f = np.maximum(f, Z - BOOT["top_z"])                         # shaft top
        verts, faces, _, _ = measure.marching_cubes(f, 0.0, spacing=(vox, vox, vox))
        verts = verts + lo
        faces = faces[:, ::-1]
        ob = S.make_mesh(f"_boot_{s}", verts, faces.tolist(), col)
        parts.append(ob)
    ob = S.join_objects(parts, "Soldier_Boots")
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=1e-6)
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    bm.to_mesh(ob.data)
    bm.free()
    if S.outward_score(ob, (0, -0.08, 0.06)) < 0:
        S.flip_faces(ob)
    dm = ob.modifiers.new("Dec", 'DECIMATE')
    dm.ratio = 1900 / len(S.tris_of(ob.data))
    dm.use_collapse_triangulate = True
    S.apply_modifier(ob, dm)
    Wb = S.transfer_weights(bf["co"], bf["tris"], bf["W"], S.co_of(ob))
    nb = S.neighbours(ob.data)
    Wb = S.limit_normalize(S.smooth_weights(Wb, nb, 3, 0.5), 4)
    S.write_W(ob, Wb, names, arm)
    # soles: footprint outline of each upper, extruded 0 .. sole_z; weights foot -> ball across the crease
    soles = []
    names = bf["names"]
    c = S.co_of(ob)
    for s, sg in (("l", 1), ("r", -1)):
        m = (c[:, 0] * sg > 0) & (c[:, 2] < BOOT["sole_z"] + 0.012)
        pts = c[m][:, :2]
        from scipy.spatial import ConvexHull
        hull = pts[ConvexHull(pts).vertices]
        cen = hull.mean(0)
        # resample the hull outline uniformly (36 points) and grow it by the sole margin
        seg = np.linalg.norm(np.roll(hull, -1, 0) - hull, axis=1)
        L = np.concatenate([[0], np.cumsum(seg)])
        tt = np.linspace(0, L[-1], 36, endpoint=False)
        ring = np.array([np.interp(tt, L, np.append(hull[:, k], hull[0, k])) for k in (0, 1)]).T
        nrm = ring - cen
        nrm /= np.linalg.norm(nrm, axis=1, keepdims=True)
        ring = ring + nrm * BOOT["sole_margin"]
        foot = arm.data.bones[f"foot_{s}"]
        ball = arm.data.bones[f"ball_{s}"]
        a = np.array(ball.head_local)[:2] - np.array(foot.head_local)[:2]
        a /= np.linalg.norm(a)
        rings = []
        for z, shrink in ((0.0, 0.004), (0.004, 0.0), (BOOT["sole_z"] - 0.004, 0.0), (BOOT["sole_z"], 0.003)):
            rr = ring - nrm * shrink
            # toe spring: the front 4 cm of the sole bottom rises
            sfw = (rr - np.array(ball.head_local)[:2]) @ a
            zz = np.full(len(rr), z)
            if z < 0.005:
                zz = zz + np.clip(sfw - 0.02, 0, None) * 0.25
            rings.append(np.column_stack([rr, zz]))
        V, F = S.loft_closed(rings)
        F = S.orient_outward(V, F)
        so = S.make_mesh(f"Soldier_Sole_{s.upper()}", V, F, col)
        # weights: foot behind the ball joint, ball in front, 3 cm blend
        u = (V[:, :2] - np.array(ball.head_local)[:2]) @ a
        k = np.clip((u + 0.015) / 0.03, 0, 1)
        k = k * k * (3 - 2 * k)
        W = np.zeros((len(V), len(names)))
        W[:, names.index(f"foot_{s}")] = 1 - k
        W[:, names.index(f"ball_{s}")] = k
        S.write_W(so, W, names, arm)
        soles.append(so)
    return ob, soles


ARM_BONES = [f"{b}_{s}" for b in ("upperarm", "upperarm_twist_01", "lowerarm", "lowerarm_twist_01") for s in "lr"]


def build_carrier(arm, shirt, B):
    bv, sco = garment_bvh(shirt, ARM_BONES, arm)
    P = CARRIER
    parts = {}

    def place_bag(w, h, top, tilt, front):
        V, F = G.bent_box(w, h, P["bag_t"], P["R"], bevel=0.007, nx=6, nz=4, cut_top=P["cut"], cut_depth=P["cut_depth"])
        th = math.radians(tilt)
        if front:
            ex, ey, ez = np.array([1, 0, 0.]), np.array([0, math.cos(th), -math.sin(th)]), np.array([0, math.sin(th), math.cos(th)])
            o = np.array([0, -0.30, top - h / 2])
        else:
            ex, ey, ez = np.array([-1, 0, 0.]), np.array([0, -math.cos(th), -math.sin(th)]), np.array([0, -math.sin(th), math.cos(th)])
            o = np.array([0, 0.30, top - h / 2])
        M = G.frame_matrix(o, ex, ey, ez)
        W = G.xf(V, M)
        # slide along ey (towards the body) until the inner side is `clear` off the shirt
        for _ in range(40):
            sd = S.signed_bvh(bv, W, maxd=0.5)
            m = np.nanmin(sd)
            if abs(m - P["clear"]) < 2e-4:
                break
            W = W + ey * (m - P["clear"]) * 0.9
        k = int(np.nanargmin(sd))
        log(f"bag {'front' if front else 'back'}: contact vertex {np.round(W[k], 3).tolist()} clear {m * 1000:.1f} mm")
        return W, F, (o, ex, ey, ez), M
    Vf, Ff, fr_f, _ = place_bag(P["front_w"], P["front_h"], P["front_top"], P["tilt_front"], True)
    Vb, Fb, fr_b, _ = place_bag(P["back_w"], P["back_h"], P["back_top"], P["tilt_back"], False)
    B.add("PC_FrontBag", Vf, Ff, ("rigid", "spine_03"), zone="carrier")
    B.add("PC_BackBag", Vb, Fb, ("rigid", "spine_03"), zone="carrier")
    info = {"front_outer_y": float(Vf[:, 1].min()), "back_outer_y": float(Vb[:, 1].max())}
    # --- cummerbund, both sides
    zc = np.linspace(P["cb_z"][0], P["cb_z"][1], 5)
    for s, sg in (("l", 1), ("r", -1)):
        az = np.radians(np.linspace(30, 150, 15)) * sg
        cen = np.array([0.0, -0.028])
        O = np.zeros((len(az), len(zc), 3)); D = np.zeros_like(O)
        for i, a in enumerate(az):
            dxy = np.array([math.sin(a), -math.cos(a)])
            for j, z in enumerate(zc):
                O[i, j] = [cen[0] + dxy[0] * 0.45, cen[1] + dxy[1] * 0.45, z]
                D[i, j] = [-dxy[0], -dxy[1], 0]
        Pp, Nn = G.surface_grid(bv, O, D, back=0.0)
        Nn = G.smooth_grid(Nn, 2)
        Nn /= np.linalg.norm(Nn, axis=-1, keepdims=True)
        tt = SK.pillow(len(az), len(zc), P["cb_thick"], P["cb_thick"] * 0.6, pu=10, pv=3)
        V, F, Wl = G.slab_from_grid(Pp, Nn, P["cb_clear"], tt, round_edge=0.3, return_walls=True)
        B.add(f"PC_Cummerbund_{s.upper()}", V, F, ("fabric", "Soldier_Shirt", None), flat=Wl,
              zone="carrier", rigid_ends=("spine_03", 0.025, "u"), grid=(len(az), len(zc)))
    # --- shoulder straps
    for s, sg in (("l", 1), ("r", -1)):
        phis = np.radians(np.linspace(86, -70, 15))
        xs = sg * (P["strap_x"] + np.array([-0.5, 0.0, 0.5]) * P["strap_w"])
        O = np.zeros((len(phis), 3, 3)); D = np.zeros_like(O)
        for i, ph in enumerate(phis):
            dd = np.array([0.0, -math.sin(ph), math.cos(ph)])
            for j, x in enumerate(xs):
                c = np.array([x, -0.015, 1.405])
                O[i, j] = c + dd * 0.40
                D[i, j] = -dd
        Pp, Nn = G.surface_grid(bv, O, D, back=0.0)
        Pp = G.smooth_grid(Pp, 1)
        Nn = G.smooth_grid(Nn, 2)
        Nn /= np.linalg.norm(Nn, axis=-1, keepdims=True)
        tt = SK.pillow(len(phis), 3, P["strap_thick"], P["strap_thick"] * 0.55, pu=8, pv=2)
        V, F, Wl = G.slab_from_grid(Pp, Nn, P["strap_clear"], tt, round_edge=0.35, return_walls=True)
        B.add(f"PC_Strap_{s.upper()}", V, F, ("fabric", "Soldier_Shirt", None), flat=Wl,
              zone="carrier", rigid_ends=("spine_03", 0.015, "u"), grid=(len(phis), 3))
    # admin panel (loop field) on the upper front bag, above the magazine pouches
    o, ex, ey, ez = fr_f
    ymin = Vf[:, 1].min()
    Va, Fa = G.bent_box(0.170, 0.082, 0.013, P["R"], bevel=0.005, nx=4, nz=2)
    Ma = G.frame_matrix(np.array([0.0, 0, P["front_top"] - 0.062]), ex, ey, ez)
    Va = G.xf(Va, Ma)
    Va[:, 1] += (ymin + 0.001) - Va[:, 1].max()
    Va = snap_to(Va, Vf, Ff, ey)
    B.add("PC_AdminPouch", Va, Fa, ("rigid", "spine_03"), zone="pouch")
    info["front_frame"] = fr_f
    info["back_frame"] = fr_b
    return info, (Vf, Ff), (Vb, Fb)


def build_side_pouches(arm, shirt, B, back_bag):
    """Radio pouch + radio on the left side of the back bag, GP pouch on the right (rigid spine_03)."""
    Vb, _ = back_bag
    out = {}
    for s, sg, kind in (("l", 1, "radio"), ("r", -1, "gp")):
        # the bag's lateral edge at mid height
        m = (Vb[:, 0] * sg > 0)
        edge = Vb[m][np.argmax(np.abs(Vb[m][:, 0]))]
        h = 0.150 if kind == "radio" else 0.120
        V, F = G.rbox(0.048, 0.078, h, 0.010)
        c = np.array([edge[0] + sg * 0.018, edge[1] - 0.030, 1.305 - h / 2])
        # yaw so the pouch face follows the torso side (~ 20 deg towards the back)
        yaw = math.radians(-18 * sg)
        R = np.array([[math.cos(yaw), -math.sin(yaw), 0], [math.sin(yaw), math.cos(yaw), 0], [0, 0, 1]])
        V = V @ R.T + c
        V = snap_to(V, Vb, back_bag[1], np.array([-sg, 0.35, 0.0]))
        c = V.mean(0) + np.array([0, 0, 0.0])
        B.add(f"PC_{kind.capitalize()}Pouch", V, F, ("rigid", "spine_03"), zone="pouch")
        if kind == "radio":
            # radio body top (knobs) above the pouch + antenna
            Vr, Fr = G.rbox(0.036, 0.060, 0.030, 0.006)
            Vr = Vr @ R.T + np.array([c[0], c[1], V[:, 2].max() - 0.020 + 0.015])
            B.add("PC_Radio", Vr, Fr, ("rigid", "spine_03"), zone="hard")
            top = np.array([c[0], c[1] + 0.012, V[:, 2].max() + 0.020])
            prof = [(0.0, 0.0), (0.0065, 0.0), (0.0065, 0.030), (0.0035, 0.034), (0.0030, 0.150), (0.0, 0.153)]
            Va, Fa = G.lathe_closed(prof, n=8)
            tilt = math.radians(14)
            Rt = np.array([[1, 0, 0], [0, math.cos(tilt), math.sin(tilt)], [0, -math.sin(tilt), math.cos(tilt)]])
            Ry = np.array([[math.cos(math.radians(10 * sg)), 0, math.sin(math.radians(10 * sg))], [0, 1, 0],
                           [-math.sin(math.radians(10 * sg)), 0, math.cos(math.radians(10 * sg))]])
            Va = Va @ (Ry @ Rt).T + top
            B.add("PC_Antenna", Va, Fa, ("rigid", "spine_03"), zone="hard")
            out["antenna_tip"] = Va[np.argmax(Va[:, 2])].tolist()
    return out


def build_belt(arm, trousers, B):
    bv, tco = garment_bvh(trousers)
    az = np.radians(np.linspace(0, 360, 36, endpoint=False))
    cen = np.array([0.0, -0.030])
    O = np.zeros((len(az), 3, 3)); D = np.zeros_like(O)
    for i, a in enumerate(az):
        dxy = np.array([math.sin(a), -math.cos(a)])
        # belt top 6 mm under the waistband top (the waist line is lower at the front)
        yw = cen[1] + dxy[1] * 0.12
        # flatter than the waistband (higher at the front) and narrower at the front (buckle side)
        ztop = TROUSERS["waist_z0"] + 0.06 * yw - 0.014
        hgt = (BELT["z"][1] - BELT["z"][0]) - 0.012 * max(0.0, -dxy[1])
        for j, z in enumerate(np.linspace(ztop - hgt, ztop, 3)):
            O[i, j] = [cen[0] + dxy[0] * 0.45, cen[1] + dxy[1] * 0.45, z]
            D[i, j] = [-dxy[0], -dxy[1], 0]
    Pp, Nn = G.surface_grid(bv, O, D, back=0.0)
    Pp = G.smooth_grid(Pp, 1, closed_u=True)
    Nn = G.smooth_grid(Nn, 2, closed_u=True)
    Nn[..., 2] *= 0.3
    Nn /= np.linalg.norm(Nn, axis=-1, keepdims=True)
    V, F, Wl = G.slab_from_grid(Pp, Nn, BELT["clear"], BELT["thick"], closed_u=True, round_edge=0.25, return_walls=True)
    B.add("Belt", V, F, flat=Wl, bind= ("fabric", "Soldier_Trousers", ["pelvis", "spine_01", "thigh_l", "thigh_r"]), zone="belt")
    ring_out = Pp + Nn * (BELT["clear"] + BELT["thick"])
    front = ring_out[0, 1]
    # buckle
    Vk, Fk = G.rbox(0.066, 0.016, 0.046, 0.005)
    Vk = Vk + front + np.array([0, -0.007, 0])
    B.add("Belt_Buckle", Vk, Fk, ("rigid", "pelvis"), zone="hard")
    # pouches: two utility pouches on the rear hips, a dump pouch on the left hip
    pouch = []
    for name, azd, size in (("Belt_PouchRL", 148, (0.120, 0.058, 0.120)), ("Belt_PouchRR", -148, (0.120, 0.058, 0.120)),
                            ("Belt_Dump", 108, (0.085, 0.050, 0.110))):
        i = int(round((azd % 360) / (360 / len(az)))) % len(az)
        p = ring_out[i, 1]
        n = Nn[i, 1]
        yaw = math.atan2(n[0], -n[1])
        Vp, Fp = G.rbox(*size, 0.012)
        R = np.array([[math.cos(yaw), -math.sin(yaw), 0], [math.sin(yaw), math.cos(yaw), 0], [0, 0, 1]])
        # hang: top at the belt top, back face on the belt
        c = p + n * (size[1] / 2 - 0.001) + np.array([0, 0, ring_out[i, 2, 2] + 0.004 - size[2] / 2 - p[2]])
        Vp = Vp @ R.T + c
        belt_V, belt_F = B.parts["Belt"]["V"], B.parts["Belt"]["F"]
        Vp = snap_to(Vp, belt_V, belt_F, -n)                   # back face on the belt
        top_rear = Vp[np.argsort(Vp[:, 2])[-8:]].mean(0)
        top_rear = top_rear - n * (size[1] / 2)
        Vp, tilt = tilt_clear(Vp, Fp, bv, tco, top_rear, np.cross(n, [0, 0, 1.0]), clear=0.003)
        B.add(name, Vp, Fp, ("rigid", "pelvis"), zone="pouch")
        pouch.append(f"{name} (tilt {tilt} deg)")
    return {"pouches": pouch}


def tris_from(F):
    return np.array([t for f in F for t in ([f] if len(f) == 3 else [[f[0], f[i], f[i + 1]] for i in range(1, len(f) - 1)])])


def snap_to(V, target_V, target_F, direction, gap=0.0006, iters=8):
    """Translate a rigid part along `direction` (pointing from the part towards the target) until
    its closest approach to the target surface is `gap` (attached, not floating, not inside)."""
    d = np.asarray(direction, float) / np.linalg.norm(direction)
    bv = S.bvh(np.asarray(target_V), tris_from(target_F))
    V = np.array(V, float)
    for _ in range(iters):
        sd = S.signed_bvh(bv, V, maxd=0.08)
        if np.all(np.isnan(sd)):
            break
        m = np.nanmin(sd)
        if abs(m - gap) < 1e-4:
            break
        V = V + d * (m - gap)
    return V


def tilt_clear(V, F, bv, garment_co, hinge_p, hinge_axis, clear=0.003, max_deg=24.0):
    """Swing a hanging pouch about its top hinge (on the belt) until it clears the garment below."""
    ax = np.asarray(hinge_axis, float) / np.linalg.norm(hinge_axis)
    base = np.array(V, float)
    tris = tris_from(F)
    for k in range(int(max_deg) + 1):
        R = np.array(Matrix.Rotation(math.radians(k), 3, Vector(tuple(ax))))
        W = (base - hinge_p) @ R.T + hinge_p
        sd = S.signed_bvh(bv, W, maxd=0.2)
        ok = np.nanmin(sd) >= clear - 1e-4
        if ok:
            pb = S.bvh(W, tris)
            lo, hi = W.min(0) - 0.01, W.max(0) + 0.01
            g = garment_co[((garment_co >= lo) & (garment_co <= hi)).all(1)]
            if len(g):
                sg = S.signed_bvh(pb, g, maxd=0.05)
                cand = np.nonzero(np.nan_to_num(sg, nan=1.0) < 0)[0]
                if len(cand) and S.closed_inside(pb, g[cand]).any():
                    ok = False
        if ok:
            return W, k
    return W, max_deg


def push_clear(V, bv, direction, clear, iters=16, F=None, garment_co=None):
    """Translate a rigid part along `direction` until all its vertices are at least `clear` in front
    of the garment surface (bv) and (with F / garment_co) no garment vertex lies inside the part."""
    d = np.asarray(direction, float) / np.linalg.norm(direction)
    V = np.array(V, float)
    for _ in range(iters):
        sd = S.signed_bvh(bv, V, maxd=0.2)
        m = np.nanmin(sd)
        need = clear - m if m < clear - 1e-4 else 0.0
        if F is not None and garment_co is not None:
            tris = np.array([t for f in F for t in ([f] if len(f) == 3 else [[f[0], f[i], f[i + 1]] for i in range(1, len(f) - 1)])])
            pb = S.bvh(V, tris)
            lo, hi = V.min(0) - 0.01, V.max(0) + 0.01
            g = garment_co[((garment_co >= lo) & (garment_co <= hi)).all(1)]
            if len(g):
                sg = S.signed_bvh(pb, g, maxd=0.05)
                cand = np.nonzero(np.nan_to_num(sg, nan=1.0) < 0)[0]
                if len(cand):
                    ins = S.closed_inside(pb, g[cand])        # ray parity: really inside the part
                    if ins.any():
                        need = max(need, float((-sg[cand][ins]).max()) + clear * 0.5)
        if need <= 1e-4:
            break
        V = V + d * (need + 2e-4)
    return V


def build_knee_pads(arm, trousers, B):
    bv, tco = garment_bvh(trousers)
    out = {}
    for s, sg in (("l", 1), ("r", -1)):
        calf = arm.data.bones[f"calf_{s}"]
        k0 = np.array(calf.head_local)
        ax = np.array(calf.tail_local) - k0
        ax /= np.linalg.norm(ax)
        fwd = np.array([0, -1.0, 0]) - ax * (-ax[1])
        fwd /= np.linalg.norm(fwd)
        side = np.cross(ax, fwd)
        hs = np.linspace(KNEE["z"][0], KNEE["z"][1], 6)
        azs = np.radians(np.linspace(-KNEE["az"], KNEE["az"], 9))
        O = np.zeros((len(azs), len(hs), 3)); D = np.zeros_like(O)
        for i, a in enumerate(azs):
            dirv = fwd * math.cos(a) + side * math.sin(a)
            for j, hh in enumerate(hs):
                c = k0 - ax * hh           # ax points down the shin: +hh = above the joint
                O[i, j] = c + dirv * 0.13
                D[i, j] = -dirv
        Pp, Nn = G.surface_grid(bv, O, D, back=0.0)
        Pp = G.smooth_grid(Pp, 2)
        Nn = G.smooth_grid(Nn, 3)
        Nn /= np.linalg.norm(Nn, axis=-1, keepdims=True)
        ui = np.linspace(-1, 1, len(azs))[:, None]
        vj = np.linspace(-1, 1, len(hs))[None, :]
        T = KNEE["thick"] * (1.0 - 0.45 * np.maximum(np.abs(ui) ** 3, np.abs(vj) ** 3))
        V, F = G.slab_from_grid(Pp, Nn, KNEE["clear"], T, round_edge=0.4)
        V = push_clear(V, bv, fwd, 0.004, F=F, garment_co=tco)
        B.add(f"KneePad_{s.upper()}", V, F, ("rigid", f"calf_{s}"), zone="kneepad")
    return out


def build_helmet(arm, bala, skin, B):
    H = HELMET
    rows, pole = G.superellipsoid_dome(H["c"], H["ax"], H["ay_f"], H["ay_b"], H["az"], rim_z, n_az=32, n_el=8, p=H["p"])
    V, F, tags = G.dome_shell(rows, pole, H["shell"])
    n_out = tags["outer"][1]
    # faces touching only outer-surface vertices = cover (camo, clothing atlas); rim + inner = hard shell
    face_atlas = ["cloth" if all(v < n_out for v in f) else "gear" for f in F]
    B.add("Helmet", V, F, ("rigid", "head"), zone="helmet", face_atlas=face_atlas)
    hb = S.bvh(V, [t for f in F for t in ([f] if len(f) == 3 else [[f[0], f[1], f[2]], [f[0], f[2], f[3]]])])
    # helper: point on the outer surface at (azimuth, z)
    cxy = np.array(H["c"][:2])

    def on_shell(a_deg, z, out=0.0):
        a = math.radians(a_deg)
        d = np.array([math.sin(a), -math.cos(a), 0.0])
        o = np.array([cxy[0], cxy[1], z]) + d * 0.4
        loc, nor = G.ray_hit(hb, o, -d, 0.6)
        if loc is None:
            return None, None
        if nor @ d < 0:
            nor = -nor
        return loc + nor * out, nor

    def rim_at(a_deg):
        """Lowest z at geometric azimuth a where the outer shell exists (the superellipsoid's
        parameter angle is not the geometric azimuth, so rim_z(a) is only a first guess)."""
        z = rim_z(a_deg) - 0.02
        while z < rim_z(a_deg) + 0.03:
            if on_shell(a_deg, z)[0] is not None:
                return z
            z += 0.0005
        return rim_z(a_deg)

    def shell_strip(az0, az1, z0f, z1f, nu, nv, clear, thick, name, zone, atlas="gear", rel_rim=True):
        azs = np.linspace(az0, az1, nu)
        Pp = np.zeros((nu, nv, 3)); Nn = np.zeros_like(Pp)
        for i, a in enumerate(azs):
            base = rim_at(a) if rel_rim else 0.0
            for j, t in enumerate(np.linspace(z0f, z1f, nv)):
                p, n = on_shell(a, base + t)
                Pp[i, j], Nn[i, j] = p, n
        Nn = G.smooth_grid(Nn, 1)
        Nn /= np.linalg.norm(Nn, axis=-1, keepdims=True)
        V_, F_ = G.slab_from_grid(Pp, Nn, clear, thick, round_edge=0.3)
        B.add(name, V_, F_, ("rigid", "head"), zone=zone, atlas=atlas)
        return Pp, Nn
    for s, sg in (("l", 1), ("r", -1)):
        shell_strip(sg * 50, sg * 128, 0.004, 0.030, 9, 3, -0.001, 0.0075, f"Helmet_Rail_{s.upper()}", "rail")
    shell_strip(-15, 15, 0.006, 0.044, 5, 3, -0.001, 0.0055, "Helmet_Shroud", "shroud")
    # team band (elastic band round the cover, above the rails and the shroud)
    azs = np.linspace(17, 343, 34)           # the ends tuck under the NVG shroud (+-15 deg)
    zb = (1.752, 1.769, 1.786)
    Pp = np.zeros((len(azs), 3, 3)); Nn = np.zeros_like(Pp)
    for i, a in enumerate(azs):
        for j, z in enumerate(zb):
            p, n = on_shell(a, z)
            Pp[i, j], Nn[i, j] = p, n
    Nn = G.smooth_grid(Nn, 1)
    Nn /= np.linalg.norm(Nn, axis=-1, keepdims=True)
    V_, F_, W_ = G.slab_from_grid(Pp, Nn, 0.0014, 0.0024, closed_u=False, round_edge=0.15, return_walls=True)
    B.add("Helmet_Band", V_, F_, ("rigid", "head"), zone="team", atlas="team", flat=W_)
    # NVG mount knob on the shroud
    p, n = on_shell(0, rim_at(0) + 0.026, 0.004)
    Vk, Fk = G.rbox(0.026, 0.016, 0.022, 0.004)
    Vk = Vk + p + n * 0.008
    B.add("Helmet_Mount", Vk, Fk, ("rigid", "head"), zone="shroud")
    # headset: ear cups over the ears, arms to the rails, boom mic on the left cup
    bb, bco = garment_bvh(bala)
    out = {}
    for s, sg in (("l", 1), ("r", -1)):
        ear = np.array([sg * 0.070, -0.036, 1.662])
        loc, nor = G.ray_hit(bb, ear + np.array([sg * 0.2, 0, 0]), np.array([-sg, 0, 0]), 0.4)
        xin = loc[0] + sg * 0.004
        prof = [(0.0, 0.0), (0.030, 0.0), (0.039, 0.006), (0.041, 0.016), (0.038, 0.027), (0.028, 0.034), (0.0, 0.036)]
        Vc, Fc = G.lathe_closed(prof, n=18)
        Vc[:, 1] *= 1.18        # taller than wide (local y -> world z)
        # local z (cup axis) -> world +-x
        R = np.array([[0, 0, sg], [1, 0, 0], [0, 1, 0.0]]) if sg > 0 else np.array([[0, 0, -1], [-1, 0, 0], [0, 1, 0.0]])
        Vc = Vc @ R.T + np.array([xin, ear[1], ear[2]])
        B.add(f"Headset_Cup_{s.upper()}", Vc, Fc, ("rigid", "head"), zone="headset")
        # arm from the rail down to the cup top
        top = Vc[np.argmax(Vc[:, 2])]
        rp, rn = on_shell(sg * 90, rim_at(sg * 90) + 0.012, 0.006)
        a0, a1 = top + np.array([0, 0, -0.004]), rp
        mid = 0.5 * (a0 + a1)
        L = np.linalg.norm(a1 - a0) + 0.012
        Va, Fa = G.rbox(0.010, 0.016, L, 0.003)
        dz = (a1 - a0) / np.linalg.norm(a1 - a0)
        ax_ = np.cross(np.array([0, 0, 1.0]), dz)
        ang = math.acos(max(-1, min(1, dz[2])))
        if np.linalg.norm(ax_) > 1e-6:
            Rm = np.array(Matrix.Rotation(ang, 3, Vector(ax_ / np.linalg.norm(ax_))))
            Va = Va @ Rm.T
        Va = Va + mid
        B.add(f"Headset_Arm_{s.upper()}", Va, Fa, ("rigid", "head"), zone="headset")
        out[f"cup_{s}_inner_x"] = float(xin)
    # boom mic (left): swept tube from the cup front to the mouth
    cupL = B.parts["Headset_Cup_L"]["V"]
    start = np.array([cupL[:, 0].min() + 0.018, cupL[:, 1].min() + 0.020, 1.642])     # root inside the cup
    mouth_loc, mouth_n = G.ray_hit(bb, np.array([0.02, -0.40, 1.603]), np.array([0, 1.0, 0]), 0.6)
    tip = mouth_loc + np.array([0.012, -0.020, 0.0])
    path = [start + (tip - start) * t + np.array([0.0, 0.0, -0.012 * math.sin(math.pi * t)]) + np.array([0.018 * math.sin(math.pi * t), 0, 0]) for t in np.linspace(0, 1, 7)]
    rings = []
    for k, p in enumerate(path):
        tng = path[min(k + 1, 6)] - path[max(k - 1, 0)]
        tng /= np.linalg.norm(tng)
        a = np.cross(tng, [0, 0, 1.0]); a /= np.linalg.norm(a)
        b = np.cross(tng, a)
        r = 0.0028 if k < 6 else 0.0045
        rings.append(np.array([p + r * (math.cos(t) * a + math.sin(t) * b) for t in np.linspace(0, 2 * np.pi, 6, endpoint=False)]))
    rings[-1] = rings[-1]
    Vm, Fm = S.loft_closed(rings)
    B.add("Headset_Mic", Vm, S.orient_outward(Vm, Fm), ("rigid", "head"), zone="headset")
    # chin strap: Y band on the balaclava from the front of each cup under the chin
    ctrl = [(0.080, -0.072, 1.628), (0.070, -0.097, 1.598), (0.050, -0.119, 1.573), (0.024, -0.134, 1.558), (0.0, -0.139, 1.553)]
    ctrl = [np.array(c) for c in ctrl]
    path = ctrl + [np.array([-c[0], c[1], c[2]]) for c in ctrl[-2::-1]]
    hc = np.array([0.0, -0.045, 1.640])
    Pp = np.zeros((len(path), 3, 3)); Nn = np.zeros_like(Pp)
    for i, p in enumerate(path):
        tng = path[min(i + 1, len(path) - 1)] - path[max(i - 1, 0)]
        tng /= np.linalg.norm(tng)
        inward = (hc - p) / np.linalg.norm(hc - p)
        bn = np.cross(tng, inward); bn /= np.linalg.norm(bn)
        for j, w in enumerate((-0.009, 0.0, 0.009)):
            q = p + bn * w
            loc, nor = G.ray_hit(bb, q - inward * 0.1, inward, 0.3)
            if loc is None:
                loc, nor = q, -inward
            if nor @ inward > 0:
                nor = -nor
            Pp[i, j], Nn[i, j] = loc, nor
    Nn = G.smooth_grid(Nn, 1)
    Nn /= np.linalg.norm(Nn, axis=-1, keepdims=True)
    V_, F_ = G.slab_from_grid(Pp, Nn, 0.0018, 0.0022, round_edge=0.2)
    B.add("Helmet_ChinStrap", V_, F_, ("rigid", "head"), zone="strap")
    return out


def build_glasses(bala, skin, B):
    """Wraparound ballistic glasses: smoked shield + frame bar + temple arms (rigid head)."""
    co = np.concatenate([S.co_of(bala), S.co_of(skin)])
    tr = np.concatenate([S.tris_of(bala.data), S.tris_of(skin.data) + len(S.co_of(bala))])
    hb = S.bvh(co, tr)
    axis = np.array([0.0, -0.035])
    azs = np.linspace(-63, 63, 13)
    top, bot0 = 1.7085, 1.6630
    nv = 4
    Pp = np.zeros((len(azs), nv, 3)); Nn = np.zeros_like(Pp)
    for i, a in enumerate(azs):
        ar = math.radians(a)
        d = np.array([math.sin(ar), -math.cos(ar), 0])
        bot = bot0 + 0.015 * math.exp(-(a / 10.0) ** 2) + 0.011 * (abs(a) / 63) ** 2.5
        tp = top - 0.005 * (abs(a) / 63) ** 2
        for j, z in enumerate(np.linspace(bot, tp, nv)):
            o = np.array([axis[0], axis[1], z]) + d * 0.4
            loc, nor = G.ray_hit(hb, o, -d, 0.6)
            Pp[i, j] = loc + d * 0.0125 if loc is not None else o
    # smooth shield: fit a smooth surface (grid smoothing), constant radius outward
    Pp = G.smooth_grid(Pp, 3)
    for i, a in enumerate(azs):
        ar = math.radians(a)
        Nn[i, :] = [math.sin(ar), -math.cos(ar), 0.10]
    Nn /= np.linalg.norm(Nn, axis=-1, keepdims=True)
    V, F = G.slab_from_grid(Pp, Nn, 0.0, 0.0022, round_edge=0.0)
    B.add("Glasses_Lens", V, F, ("rigid", "head"), zone="lens")
    # frame bar along the top edge
    Pt = Pp[:, -2:, :].copy()
    Pt[:, 0] = Pp[:, -1] - np.array([0, 0, 0.0045])
    V, F = G.slab_from_grid(Pt, Nn[:, -2:], -0.0006, 0.0030, round_edge=0.3)
    B.add("Glasses_Frame", V, F, ("rigid", "head"), zone="frame")
    # temple arms from the shield ends back to the ears (on the balaclava)
    for s, sg in (("l", 1), ("r", -1)):
        end = Pp[-1 if sg > 0 else 0, -1] - np.array([0, 0, 0.004])
        ys = np.linspace(end[1] + 0.004, -0.028, 7)
        Pa = np.zeros((7, 2, 3)); Na = np.zeros_like(Pa)
        for i, y in enumerate(ys):
            for j, dz in enumerate((-0.0035, 0.0035)):
                o = np.array([sg * 0.3, y, end[2] + dz - 0.006 * i / 6])
                loc, nor = G.ray_hit(hb, o, np.array([-sg, 0, 0]), 0.5)
                if loc is None:
                    loc, nor = o - np.array([sg * 0.21, 0, 0]), np.array([sg, 0, 0.0])
                if nor[0] * sg < 0:
                    nor = -nor
                Pa[i, j], Na[i, j] = loc, nor
        V, F = G.slab_from_grid(Pa, Na, 0.0012, 0.0030, round_edge=0.2)
        B.add(f"Glasses_Arm_{s.upper()}", V, F, ("rigid", "head"), zone="frame")


def add_lip_normal(ob, loop, edge, depth, lining=None):
    """add_lip with the inward direction = minus the vertex normal at the boundary; the lining
    continues along `lining(p)` (default: also inwards)."""
    cc = S.co_of(ob)
    nn = S.vnormals(cc, S.tris_of(ob.data))
    L = np.array(loop)

    def inward(p):
        return -nn[L[int(np.argmin(np.linalg.norm(cc[L] - p, axis=1)))]]
    return S.add_lip(ob, loop, inward, edge=edge, depth=depth, lining_dir_fn=lining or inward)


def transfer_shape_keys(src, dst, eps=2e-4):
    """Corrective shape keys of a garment interpolated (nearest surface point) onto a fabric gear
    band so the band moves with the garment's corrected surface; keys that barely move the band
    are dropped."""
    sk = src.data.shape_keys
    if sk is None:
        return []
    sco = S.co_of(src)
    tris = S.tris_of(src.data)
    bv = S.bvh(sco, tris)
    dco = S.co_of(dst)
    loc, _, fi, _ = S.nearest_on(bv, dco, 0.2)
    t = tris[np.maximum(fi, 0)]
    Bc = S.barycentric(loc, sco[t[:, 0]], sco[t[:, 1]], sco[t[:, 2]])
    base = np.empty(len(sco) * 3)
    sk.key_blocks[0].data.foreach_get("co", base)
    base = base.reshape(-1, 3)
    made = []
    for k in sk.key_blocks[1:]:
        c = np.empty(len(sco) * 3)
        k.data.foreach_get("co", c)
        dl = c.reshape(-1, 3) - base
        dd = dl[t[:, 0]] * Bc[:, 0:1] + dl[t[:, 1]] * Bc[:, 1:2] + dl[t[:, 2]] * Bc[:, 2:3]
        if np.abs(dd).max() < eps:
            continue
        if dst.data.shape_keys is None:
            dst.shape_key_add(name="Basis", from_mix=False)
        kk = dst.shape_key_add(name=k.name, from_mix=False)
        kk.data.foreach_set("co", (dco + dd).ravel())
        kk.value = 0.0
        made.append(k.name)
    if made:
        dst["iv_correctives"] = src.get("iv_correctives", bpy.data.objects[BODY].get("iv_correctives"))
    return made


def build_gear_objects(arm, B, col, garments):
    """Turn the Built parts into bound objects."""
    names = S.bone_names(arm)
    objs = {}
    for name, p in B.parts.items():
        ob = S.make_mesh("SG_" + name, p["V"], p["F"], col)
        if p.get("flat"):
            sm_ = np.ones(len(ob.data.polygons), bool)
            sm_[np.asarray(p["flat"], int)] = False
            ob.data.polygons.foreach_set("use_smooth", sm_)
        n = len(p["V"])
        kind = p["bind"][0]
        if kind == "rigid":
            W = S.rigid_W(n, names, p["bind"][1])
        else:
            g = garments[p["bind"][1]]
            gco, gtr = S.co_of(g), S.tris_of(g.data)
            Wg = S.read_W(g, names)
            W = S.transfer_weights(gco, gtr, Wg, p["V"], k=4)
            if p["bind"][2]:
                W = S.restrict_weights(W, names, p["bind"][2])
            if p.get("rigid_ends"):
                bone, dist, _ = p["rigid_ends"]
                nu, nv = p["grid"]
                # slab vertex layout: outer grid then inner grid, u-major
                u = np.tile(np.repeat(np.arange(nu), nv), 2)
                # arc length along u (per grid row 0)
                P0 = p["V"][:nu * nv].reshape(nu, nv, 3)[:, nv // 2]
                s_ = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(P0, axis=0), axis=1))])
                L = s_[-1]
                de = np.minimum(s_, L - s_)[u]
                k = np.clip(1.0 - de / dist, 0, 1)
                k = k * k * (3 - 2 * k)
                R = S.rigid_W(n, names, bone)
                W = W * (1 - k[:, None]) + R * k[:, None]
            W = S.limit_normalize(W, 4)
            # the garment's corrective shapes (hip / knee / elbow) carried onto the fabric band
            transfer_shape_keys(g, ob)
        S.write_W(ob, W, names, arm)
        ob["iv_bind"] = json.dumps(p["bind"])
        ob["iv_zone"] = p["zone"]
        ob["iv_atlas"] = p.get("atlas", "gear")
        if p.get("face_atlas"):
            # split: cover faces (camo, clothing atlas) / hard shell faces (rim + liner, gear atlas)
            fa = np.array([x == "cloth" for x in p["face_atlas"]])
            cover, _ = S.copy_faces(ob, fa, "SG_" + name, col)
            shell, _ = S.copy_faces(ob, ~fa, "SG_" + name + "Shell", col)
            for o2, at in ((cover, "cloth"), (shell, "gear")):
                o2.parent = arm
                o2.modifiers.new("Armature", 'ARMATURE').object = arm
                o2["iv_bind"] = ob["iv_bind"]
                o2["iv_zone"] = p["zone"]
                o2["iv_atlas"] = at
            bpy.data.objects.remove(ob)
            cover.name = "SG_" + name
            cover.data.name = cover.name
            objs[name] = cover
            objs[name + "Shell"] = shell
            continue
        objs[name] = ob
    return objs


def hide_under_helmet(bala, arm, cups):
    """Delete balaclava faces the helmet shell and the ear cups hide in every pose (all rigid on
    `head`, like the balaclava's skull region): faces 2 cm or more above the helmet rim, and faces
    well inside an ear cup's footprint."""
    co = S.co_of(bala)
    c = np.array(HELMET["c"])
    az = np.degrees(np.arctan2(co[:, 0] - c[0], -(co[:, 1] - c[1])))
    rim = np.array([rim_z(a) for a in az])
    hid = co[:, 2] > rim + 0.020
    for cup in cups:
        V = cup
        cc = V.mean(0)
        ry, rz = (V[:, 1].max() - V[:, 1].min()) / 2 * 0.72, (V[:, 2].max() - V[:, 2].min()) / 2 * 0.72
        e = ((co[:, 1] - cc[1]) / ry) ** 2 + ((co[:, 2] - cc[2]) / rz) ** 2
        hid |= (e < 1.0) & (np.sign(co[:, 0]) == np.sign(cc[0])) & (np.abs(co[:, 0]) > 0.055)
    keep = np.array([not all(hid[v] for v in p.vertices) for p in bala.data.polygons])
    bm = bmesh.new()
    bm.from_mesh(bala.data)
    bm.faces.ensure_lookup_table()
    bmesh.ops.delete(bm, geom=[f for f in bm.faces if not keep[f.index]], context='FACES')
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context='VERTS')
    bm.to_mesh(bala.data)
    bm.free()
    bala.data.update()
    return int((~keep).sum())


def decimate_to(ob, target_tris, names=None, src=None, arm=None):
    n = len(S.tris_of(ob.data))
    if n > target_tris:
        dm = ob.modifiers.new("Dec", 'DECIMATE')
        dm.ratio = target_tris / n
        dm.use_collapse_triangulate = True
        S.apply_modifier(ob, dm)
    if src is not None:
        W = S.transfer_weights(src[0], src[1], src[2], S.co_of(ob))
        S.write_W(ob, W, names, arm)
    return len(S.tris_of(ob.data))


def garment_lips(arm, shirt, trousers, bala):
    rep = {}
    # sleeve cuffs: edge towards the forearm, lining 1.5 cm up the sleeve
    loops = S.boundary_loops(shirt.data)
    co = S.co_of(shirt)
    cuffs = [lp for lp in loops if np.abs(co[lp, 0]).mean() > 0.40]
    for lp in cuffs:
        s = "l" if co[lp, 0].mean() > 0 else "r"
        wj, ax = HN.forearm_axis(arm, s)
        add_lip_normal(shirt, lp, edge=0.0032, depth=0.016, lining=lambda p, _ax=ax: -_ax)
    co = S.co_of(shirt)
    loops = S.boundary_loops(shirt.data)
    collar = max(loops, key=lambda lp: co[lp, 2].mean())
    # clean collar edge: the boundary ring snapped to the design neck line (face selection is jagged)
    zt = SHIRT["collar_z0"] + SHIRT["collar_tilt"] * (co[collar, 1] + 0.05) + SHIRT["collar_h"]
    co[collar, 2] += np.clip(zt - co[collar, 2], -0.012, 0.012)
    S.set_co(shirt, co)
    add_lip_normal(shirt, collar, edge=0.0035, depth=0.015, lining=lambda p: np.array([0, 0, -1.0]))
    rep["shirt_lips"] = {"cuffs": len(cuffs), "collar": len(collar)}
    co = S.co_of(trousers)
    hems = [lp for lp in S.boundary_loops(trousers.data) if co[lp, 2].mean() < 0.3]
    for lp in hems:
        add_lip_normal(trousers, lp, edge=0.0045, depth=0.020, lining=lambda p: np.array([0, 0, 1.0]))
    rep["trouser_hems"] = len(hems)
    co = S.co_of(bala)
    eye = [lp for lp in S.boundary_loops(bala.data) if co[lp, 1].mean() < -0.1 and co[lp, 2].mean() > 1.64]
    for lp in eye:
        add_lip_normal(bala, lp, edge=0.0024, depth=0.003)
    rep["eye_window"] = len(eye)
    return rep


def stage_build(a=None):
    t0 = time.time()
    arm, body, col, rep = build_garments()
    names = S.bone_names(arm)
    shirt = bpy.data.objects["Soldier_Shirt"]
    trousers = bpy.data.objects["Soldier_Trousers"]
    bala = bpy.data.objects["Soldier_Balaclava"]
    skin = bpy.data.objects["Soldier_FaceSkin"]
    bf = S.body_fields(arm, body)
    body_bvh = S.bvh(bf["co"], bf["tris"])
    gloves = build_gloves(arm, col)
    boots, soles = build_boots(arm, body, bf, col, body_bvh)
    rep["boots_tris"] = len(S.tris_of(boots.data)) + sum(len(S.tris_of(s.data)) for s in soles)
    rep["trousers_outside_boots"] = enforce_outside(trousers, boots, lambda c: c[:, 2] < 0.27, 0.004)
    gcol = ivlib.collection("Soldier_Gear")
    B = G.Built()
    rep["carrier"], front_bag, back_bag = build_carrier(arm, shirt, B)
    rep["side_pouches"] = build_side_pouches(arm, shirt, B, back_bag)
    rig, rparts = HN.append_weapon(RIFLE_BLEND, col_name="IV7_LOD2", rig_name="SK_IV7")
    bpy.context.view_layer.update()
    fr_f = rep["carrier"].pop("front_frame")
    fr_b = rep["carrier"].pop("back_frame")
    rep["magazines"], rep["carrier"]["pouch_front_y"] = SK.mag_pouches(
        B, front_bag[0], front_bag[1], fr_f, CARRIER["front_top"] - CARRIER["front_h"], rparts, snap_to)
    rep["pack"] = SK.assault_pack(B, back_bag[0], back_bag[1], fr_b, CARRIER["back_top"] - 0.010, snap_to)
    wcol = bpy.data.collections["IV7_LOD2"]
    for o in list(wcol.objects):
        bpy.data.objects.remove(o)
    bpy.data.collections.remove(wcol)
    rep["belt"] = build_belt(arm, trousers, B)
    SK.thigh_holster(B, arm, trousers, BELT["z"][0], snap_to, rep)
    rep["knee"] = build_knee_pads(arm, trousers, B)
    SK.garment_kit(B, arm, shirt, trousers, rep)
    SK.glove_kit(B, arm, gloves, rep)
    rep["helmet"] = build_helmet(arm, bala, skin, B)
    build_glasses(bala, skin, B)
    garments = {"Soldier_Shirt": shirt, "Soldier_Trousers": trousers,
                "Soldier_Glove_L": gloves["l"], "Soldier_Glove_R": gloves["r"]}
    gear = build_gear_objects(arm, B, gcol, garments)
    # glove kit parts sample the glove texture where they sit (projected UVs, glove UV space)
    for nm, ob_ in gear.items():
        if B.parts.get(nm, {}).get("atlas") == "glove":
            SK.project_uv(ob_, gloves["l" if nm.endswith("_L") else "r"])
    # hidden balaclava under the helmet / cups, then game resolution for head pieces
    rep["balaclava_hidden_faces"] = hide_under_helmet(bala, arm, [B.parts["Headset_Cup_L"]["V"], B.parts["Headset_Cup_R"]["V"]])
    rep["balaclava_tris"] = decimate_to(bala, 1500, names, (bf["co"], bf["tris"], bf["W"]), arm)
    rep["skin_tris"] = decimate_to(skin, 260, names, (bf["co"], bf["tris"], bf["W"]), arm)
    rep["lips"] = garment_lips(arm, shirt, trousers, bala)
    # the source body / gloves are not part of the soldier (the body is kept hidden as the
    # closed volume proxy for the intersection checks)
    body.hide_render = True
    body.hide_viewport = True
    if BODY + "_Gloved" in bpy.data.objects:
        bpy.data.objects.remove(bpy.data.objects[BODY + "_Gloved"])
    for s_ in ("l", "r"):
        # the full-resolution gloves stay (hidden) as the source of the first-person gloves
        g = bpy.data.objects[GLOVES[s_]]
        g.name = "_SRC_" + GLOVES[s_]
        g.hide_render = True
        g.hide_viewport = True
    rep["build_seconds"] = round(time.time() - t0, 1)
    log("build", json.dumps(rep))
    ivlib.deselect_all()
    bpy.ops.wm.save_as_mainfile(filepath=BLEND, compress=True)
    return rep


# =============================================================================
# UV atlases
# =============================================================================

GLOVE_UV_RECT = (0.75, 0.0, 0.25)          # (u0, v0, size): the glove UV square inside the clothing atlas
CLOTH_DENSITY = {"Soldier_Shirt": 1.0, "Soldier_Trousers": 1.0, "Soldier_Balaclava": 1.2,
                 "Soldier_FaceSkin": 0.6, "SG_Helmet": 1.15}


def atlas_members():
    obs = [o for o in bpy.data.objects if o.type == 'MESH' and o.name != BODY
           and not o.name.startswith(("_SRC_", "_HI_", "FP_", "SK_Soldier", "_L1_", "_L2_", "IVC_", "IV_Grass", "_rc_"))]
    gloves = [o for o in obs if o.name.startswith("Soldier_Glove_") or o.get("iv_atlas") == "glove" or o.get("iv_glove")]
    cloth = [o for o in obs if (o.name in CLOTH_DENSITY or o.get("iv_atlas") == "cloth") and o not in gloves]
    team = [o for o in obs if o.get("iv_atlas") == "team" or o.name == "SG_Helmet_Band"]
    gear = [o for o in obs if o not in cloth and o not in gloves and o not in team]
    return cloth, gloves, team, gear


PANEL_UV = ("Soldier_Shirt", "Soldier_Trousers")      # unwrapped per sewing panel in the build stage


def uv_cloth(cloth, gloves, report):
    others = [o for o in cloth if o.name not in PANEL_UV]
    for o in others:
        me = o.data
        while len(me.uv_layers):
            me.uv_layers.remove(me.uv_layers[0])
        me.uv_layers.new(name="UVMap")
    ivlib.select(others, others[0])
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.uv.smart_project(angle_limit=math.radians(62), island_margin=0.003, area_weight=0.0,
                             correct_aspect=True, scale_to_bounds=False)
    bpy.ops.object.mode_set(mode='OBJECT')
    # one texel density over all clothing islands (the panels keep their grain orientation)
    ivlib.select(cloth, cloth[0])
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.uv.select_all(action='SELECT')
    bpy.ops.uv.average_islands_scale()
    bpy.ops.object.mode_set(mode='OBJECT')
    for o in cloth:
        ivlib.uv_scale_islands(o, lambda ob, info: CLOTH_DENSITY.get(ob.name, 1.0))
    # glove group (gloves + glove kit, glove texture space [0,1]) -> the glove square, pinned
    u0, v0, sz = GLOVE_UV_RECT
    for g in gloves:
        me = g.data
        uv = S.uv_array(me)
        gl = me.uv_layers.get("GloveUV") or me.uv_layers.new(name="GloveUV")
        gl.data.foreach_set("uv", uv.ravel())
        me.uv_layers.active = me.uv_layers["UVMap"]
        me.uv_layers["UVMap"].data.foreach_set("uv", (np.column_stack([u0 + uv[:, 0] * sz, v0 + uv[:, 1] * sz])).ravel())
    allo = cloth + gloves
    ivlib.select(allo, cloth[0])
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    for g in gloves:
        bm = bmesh.from_edit_mesh(g.data)
        ul = bm.loops.layers.uv["UVMap"]
        for f in bm.faces:
            for l in f.loops:
                l[ul].pin_uv = True
        bmesh.update_edit_mesh(g.data)
    bpy.ops.uv.select_all(action='SELECT')
    bpy.ops.uv.pack_islands(rotate=True, rotate_method='CARDINAL', margin=0.003, margin_method='FRACTION',
                            shape_method='CONCAVE', scale=True, pin=True, pin_method='LOCKED')
    bpy.ops.object.mode_set(mode='OBJECT')
    r = ivlib.uv_island_raster(cloth, 2048)
    report["cloth"] = {"coverage_without_gloves": round(r["coverage"], 4), "overlap_px": int(r["overlap_px"]),
                       "islands": len(r["islands"]),
                       "px_per_cm": {o.name: round(ivlib.texel_density(o, 2048), 2) for o in cloth if o.name in CLOTH_DENSITY or "Pocket" in o.name}}


def uv_gear(gear, team, report):
    def dens(ob, info):
        z = ob.get("iv_zone", "")
        n = ob.name
        if n.endswith("HelmetShell"):
            return 0.55
        if z in ("lens", "frame", "shroud", "rail", "headset", "mag"):
            return 1.25
        if n.startswith("Soldier_Boots"):
            return 1.1
        if n.startswith("Soldier_Sole"):
            return 0.7
        return 1.0
    st = {}
    ivlib.uv_unwrap(gear, angle=60.0, island_margin=0.003, pack_margin=0.004, scale_fn=dens, tex_size=2048, report=st)
    report["gear"] = {k: st[k] for k in ("coverage", "overlap_px", "islands") if k in st}
    report["gear"]["px_per_cm"] = {o.name: round(ivlib.texel_density(o, 2048), 2) for o in gear[:0]}
    st = {}
    ivlib.uv_unwrap(team, angle=60.0, island_margin=0.01, pack_margin=0.02, tex_size=256, report=st)
    report["team"] = {k: st[k] for k in ("coverage", "overlap_px", "islands") if k in st}


def stage_uv(a=None):
    bpy.ops.wm.open_mainfile(filepath=BLEND)
    cloth, gloves, team, gear = atlas_members()
    rep = {}
    uv_cloth(cloth, gloves, rep)
    uv_gear(gear, team, rep)
    for o in cloth + gloves:
        o["iv_atlas"] = "cloth"
    for o in gloves:
        o["iv_glove"] = 1
    for o in gear:
        o["iv_atlas"] = "gear"
    for o in team:
        o["iv_atlas"] = "team"
    log("uv", json.dumps(rep))
    bpy.ops.wm.save_as_mainfile(filepath=BLEND, compress=True)
    json.dump(rep, open(os.path.join(PREV, "_uv_report.json"), "w"), indent=1)
    return rep


# =============================================================================
# stage: textures + materials
# =============================================================================

import soldier_tex as T      # noqa: E402

CLOTH_RES, CLOTH_BC_RES, GEAR_RES, TEAM_RES = 2048, 2048, 2048, 256


def tex_path(name):
    return os.path.join(TEX_DIR, name)


def glove_mask(glove, res, grow=3):
    """Atlas pixels (PIL row order) covered by the glove UV islands, grown by `grow` px: only these
    receive the glove texture (other clothing islands may be packed into the gaps of the glove
    square)."""
    me = glove.data
    ti, px, ba = HN.raster_uv_bary(S.uv_array(me)[S.loop_tris(me)], res)
    m = np.zeros(res * res, bool)
    m[px] = True
    m = m.reshape(res, res)
    from scipy import ndimage
    m = ndimage.binary_dilation(m, iterations=grow)
    return np.flipud(m)


def paste_glove(path, glove_png, rect_px, mode, mask=None):
    from PIL import Image
    im = Image.open(path).convert("RGB")
    g = Image.open(glove_png).convert("RGB").resize((rect_px[2], rect_px[2]), Image.LANCZOS if mode != "N" else Image.BOX)
    if mode == "N":
        a = np.asarray(g).astype(np.float32) / 127.5 - 1.0
        a /= np.maximum(np.linalg.norm(a, axis=2, keepdims=True), 1e-6)
        g = Image.fromarray(np.clip((a + 1.0) * 127.5 + 0.5, 0, 255).astype(np.uint8), "RGB")
    full = Image.new("RGB", im.size)
    full.paste(g, (rect_px[0], rect_px[1]))
    A = np.asarray(im).copy()
    Gp = np.asarray(full)
    if mask is None:
        mask = np.zeros(A.shape[:2], bool)
        mask[rect_px[1]:rect_px[1] + rect_px[2], rect_px[0]:rect_px[0] + rect_px[2]] = True
    A[mask] = Gp[mask]
    Image.fromarray(A, "RGB").save(path)


def glove_rect(res):
    u0, v0, sz = GLOVE_UV_RECT
    n = int(round(sz * res))
    return (int(round(u0 * res)), res - int(round(v0 * res)) - n, n)


def ao_texels(objs, td, res, dist):
    arr = S.bake_ao_multi(objs, res, dist, samples=24)
    img = ivlib.dilate(arr, 4)
    return img.reshape(-1, 4)[td["px"], 0]


def gear_tint(team):
    return tuple(float(x) for x in np.clip(T.srgb(T.CAMO[team]["gear"]) / T.GEAR_WHITE, 0, 1))


def export_material_reuse(name, bc, orm, n):
    """ivlib.export_material, but an existing material of that name is kept (its images reloaded)
    so the joined export meshes keep their slots when the textures are regenerated."""
    m = bpy.data.materials.get(name)
    if m is not None and m.use_nodes and "T_BaseColor" in m.node_tree.nodes:
        for nd in m.node_tree.nodes:
            if nd.type == 'TEX_IMAGE' and nd.image:
                nd.image.reload()
        return m
    return ivlib.export_material(name, bc, orm, n)


def make_materials(texs):
    mats = {}
    for team in TEAMS:
        mats[("cloth", team)] = export_material_reuse(f"M_Soldier_Cloth_{team}", texs[f"cloth_bc_{team}"], texs["cloth_orm"], texs["cloth_n"])
        m = export_material_reuse(f"M_Soldier_GearFabric_{team}", texs["gear_bc"], texs["gear_orm"], texs["gear_n"])
        nt = m.node_tree
        if "iv_team_tint" in m:
            mats[("gearfab", team)] = m
            mats[("team", team)] = export_material_reuse(f"M_Soldier_Team_{team}", texs[f"team_bc_{team}"], texs["team_orm"], texs["team_n"])
            mats[("cloth", team)] = mats[("cloth", team)]
            continue
        bsdf = next(n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED')
        tb = nt.nodes["T_BaseColor"]
        mix = nt.nodes.new('ShaderNodeMix')
        mix.data_type = 'RGBA'
        mix.blend_type = 'MULTIPLY'
        mix.inputs['Factor'].default_value = 1.0
        mix.inputs[7].default_value = (*gear_tint(team), 1.0)
        nt.links.new(tb.outputs['Color'], mix.inputs[6])
        nt.links.new(mix.outputs[2], bsdf.inputs['Base Color'])
        m["iv_team_tint"] = list(gear_tint(team))
        mats[("gearfab", team)] = m
        mats[("team", team)] = export_material_reuse(f"M_Soldier_Team_{team}", texs[f"team_bc_{team}"], texs["team_orm"], texs["team_n"])
    mats[("gearhard", None)] = export_material_reuse("M_Soldier_GearHard", texs["gear_bc"], texs["gear_orm"], texs["gear_n"])
    for m in mats.values():
        m.use_fake_user = True          # the variants not assigned in the saved file must survive the save
    return mats


def material_key(ob):
    at = ob.get("iv_atlas", "gear")
    if at == "cloth":
        return "cloth"
    if at == "team":
        return "team"
    return "gearfab" if ob.get("iv_zone") in T.FABRIC_ZONES else "gearhard"


def apply_team(team):
    for ob in bpy.data.objects:
        if ob.type != 'MESH' or ob.name == BODY or "iv_atlas" not in ob:
            continue
        if ob.name.startswith(("FP_", "SK_Soldier", "_L1_", "_L2_", "_SRC_")):
            continue
        k = material_key(ob)
        m = bpy.data.materials.get("M_Soldier_GearHard" if k == "gearhard" else
                                   {"cloth": f"M_Soldier_Cloth_{team}", "gearfab": f"M_Soldier_GearFabric_{team}",
                                    "team": f"M_Soldier_Team_{team}"}[k])
        ob.data.materials.clear()
        ob.data.materials.append(m)


def glove_group_mask(objs, res, grow=3, uv="UVMap"):
    """Atlas pixels (PIL row order) covered by the UV islands of the glove group."""
    from scipy import ndimage
    m = np.zeros(res * res, bool)
    for o in objs:
        me = o.data
        ti, px, ba = HN.raster_uv_bary(S.uv_array(me, uv)[S.loop_tris(me)], res)
        m[px] = True
    m = ndimage.binary_dilation(m.reshape(res, res), iterations=grow)
    return np.flipud(m)


GLOVE_SRC = ("T_Glove_Coyote_BaseColor.png", "T_Glove_Coyote_ORM.png", "T_Glove_Normal.png")


def soldier_glove_textures(fr):
    """Soldier gloves: the coyote tactical glove textures of hands_gloves.py (leather palm, stretch
    textile back, TPR knuckle guard, hook-and-loop wrist strap) plus dust on the fingertips / palm
    heel.  Written as T_Soldier_Glove_BaseColor / _ORM (2048); the normal map is the glove's own."""
    from PIL import Image
    src = bpy.data.objects["_SRC_" + GLOVES["l"]]
    td = S.atlas_texels([src], 2048)
    a = T.glove_dust(td, fr)
    img = np.zeros((2048, 2048, 4), np.float32)
    flat = img.reshape(-1, 4)
    flat[td["px"], 0] = a
    flat[td["px"], 3] = 1.0
    img = ivlib.dilate(img, 8)
    A = np.flipud(img[..., 0])[..., None]            # PIL row order
    bc = np.asarray(Image.open(os.path.join(GLOVE_TEX, GLOVE_SRC[0])).convert("RGB")).astype(np.float32) / 255.0
    lin = np.where(bc <= 0.04045, bc / 12.92, ((bc + 0.055) / 1.055) ** 2.4)
    # coyote -> olive-grey (the team-neutral glove colour of the soldier kit; reads as a glove, not skin)
    lum = (lin * np.array([0.2126, 0.7152, 0.0722])).sum(-1, keepdims=True)
    lin = lin * 0.22 + lum * np.array([0.93, 0.97, 0.72]) * 0.78 * 0.92
    dust = T.srgb("#8e846d")[None, None, :]
    lin = lin * (1 - 0.45 * A) + dust * 0.45 * A
    out = np.where(lin <= 0.0031308, lin * 12.92, 1.055 * np.power(np.clip(lin, 0, 1), 1 / 2.4) - 0.055)
    pbc = tex_path("T_Soldier_Glove_BaseColor.png")
    Image.fromarray(np.clip(out * 255 + 0.5, 0, 255).astype(np.uint8), "RGB").save(pbc)
    orm = np.asarray(Image.open(os.path.join(GLOVE_TEX, GLOVE_SRC[1])).convert("RGB")).astype(np.float32) / 255.0
    orm[..., 1] = np.clip(orm[..., 1] + 0.10 * A[..., 0], 0, 1)
    porm = tex_path("T_Soldier_Glove_ORM.png")
    Image.fromarray(np.clip(orm * 255 + 0.5, 0, 255).astype(np.uint8), "RGB").save(porm)
    return pbc, porm, os.path.join(GLOVE_TEX, GLOVE_SRC[2])


def stage_textures(a=None):
    t0 = time.time()
    bpy.ops.wm.open_mainfile(filepath=BLEND)
    arm = bpy.data.objects[ARM]
    C.reset_pose(arm)
    cloth, gloves, team, gear = atlas_members()
    fr = T.Frames(arm)
    os.makedirs(TEX_DIR, exist_ok=True)
    rep = {}
    texs = {}
    # ---------------- gloves (FP material + the glove square of the clothing atlas)
    g_bc, g_orm, g_n = soldier_glove_textures(fr)
    texs["glove_bc"], texs["glove_orm"], texs["glove_n"] = g_bc, g_orm, g_n
    # ---------------- clothing atlas
    td = S.atlas_texels(cloth, CLOTH_RES, attrs=("iv_gaiter",))
    panel_names = {}
    for n in PANEL_UV:
        panel_names.update({int(k): v for k, v in json.loads(bpy.data.objects[n].get("iv_panels", "{}")).items()})
    cm = T.cloth_maps2(td, cloth, fr, panel_names, SHIRT, TROUSERS)
    ao = ao_texels(cloth, td, CLOTH_RES, 0.02)
    nd = HN.height_to_normal(td, cm["h"], CLOTH_RES)
    hi = {n: bpy.data.objects["_HI_" + n] for n in PANEL_UV if "_HI_" + n in bpy.data.objects}
    nh = T.hi_normal_ts(td, cloth, hi)
    nrm = T.blend_normals(nh, nd)
    texs["cloth_n"] = S.texels_write(nrm * 0.5 + 0.5, td, tex_path("T_Soldier_Cloth_Normal.png"), fill=(0.5, 0.5, 1.0))
    orm = np.stack([np.clip(ao * cm["cav"], 0, 1), cm["rough"], np.zeros(len(ao))], 1)
    texs["cloth_orm"] = S.texels_write(orm, td, tex_path("T_Soldier_Cloth_ORM.png"), fill=(1.0, 0.85, 0.0))
    gr = glove_rect(CLOTH_RES)
    gm_hi = glove_group_mask(gloves, CLOTH_RES)
    gm_lo = glove_group_mask(gloves, CLOTH_BC_RES, grow=2)
    paste_glove(texs["cloth_n"], g_n, gr, "N", gm_hi)
    paste_glove(texs["cloth_orm"], g_orm, gr, "L", gm_hi)
    texs["cloth_n_dx"] = ivlib.normal_gl_to_dx(texs["cloth_n"], tex_path("T_Soldier_Cloth_Normal_DX.png"))
    for tm in TEAMS:
        bc = T.cloth_base2(cm, tm)
        p = S.texels_write(bc, td, tex_path(f"T_Soldier_Cloth_{tm}_BaseColor.png"), fill=(0.2, 0.2, 0.2), srgb=True,
                           size=CLOTH_BC_RES)
        paste_glove(p, g_bc, glove_rect(CLOTH_BC_RES), "L", gm_lo)
        texs[f"cloth_bc_{tm}"] = p
    rep["cloth"] = {"texels": int(len(td["px"])), "coverage": round(len(td["px"]) / CLOTH_RES ** 2, 4),
                    "height_mm": [round(float(cm["h"].min()) * 1000, 2), round(float(cm["h"].max()) * 1000, 2)],
                    "hi_normal_texels": int((np.abs(nh[:, 2] - 1.0) > 1e-4).sum())}
    # ---------------- gear atlas
    for o in gear:
        cv = S.vertex_convexity(o)
        at = o.data.attributes.get("iv_conv") or o.data.attributes.new("iv_conv", 'FLOAT', 'POINT')
        at.data.foreach_set("value", cv.astype(np.float32))
    td = S.atlas_texels(gear, GEAR_RES, attrs=("iv_conv",))
    gm = T.gear_maps(td, gear, fr, td["iv_conv"])
    ao = ao_texels(gear, td, GEAR_RES, 0.02)
    nrm = HN.height_to_normal(td, gm["h"], GEAR_RES)
    texs["gear_n"] = S.texels_write(nrm * 0.5 + 0.5, td, tex_path("T_Soldier_Gear_Normal.png"), fill=(0.5, 0.5, 1.0))
    texs["gear_n_dx"] = ivlib.normal_gl_to_dx(texs["gear_n"], tex_path("T_Soldier_Gear_Normal_DX.png"))
    orm = np.stack([np.clip(ao * gm["cav"], 0, 1), gm["rough"], gm["metal"]], 1)
    texs["gear_orm"] = S.texels_write(orm, td, tex_path("T_Soldier_Gear_ORM.png"), fill=(1.0, 0.8, 0.0))
    texs["gear_bc"] = S.texels_write(gm["base"], td, tex_path("T_Soldier_Gear_BaseColor.png"), fill=(0.3, 0.3, 0.3), srgb=True)
    rep["gear"] = {"texels": int(len(td["px"])), "coverage": round(len(td["px"]) / GEAR_RES ** 2, 4),
                   "fabric_texel_share": round(float(gm["fab"].mean()), 3)}
    # ---------------- team atlas
    td = S.atlas_texels(team, TEAM_RES)
    for k, (tm, cfg) in enumerate(TEAMS.items()):
        tmp = T.team_maps(td, team, fr, cfg, cfg["symbol"])
        texs[f"team_bc_{tm}"] = S.texels_write(tmp["base"], td, tex_path(f"T_Soldier_Team_{tm}_BaseColor.png"), fill=(0.3, 0.3, 0.3), srgb=True, dilate_px=8)
        if k == 0:
            nrm = HN.height_to_normal(td, tmp["h"], TEAM_RES)
            texs["team_n"] = S.texels_write(nrm * 0.5 + 0.5, td, tex_path("T_Soldier_Team_Normal.png"), fill=(0.5, 0.5, 1.0), dilate_px=8)
            texs["team_n_dx"] = ivlib.normal_gl_to_dx(texs["team_n"], tex_path("T_Soldier_Team_Normal_DX.png"))
            orm = np.stack([np.ones(len(tmp["rough"])), tmp["rough"], tmp["metal"]], 1)
            texs["team_orm"] = S.texels_write(orm, td, tex_path("T_Soldier_Team_ORM.png"), fill=(1.0, 0.8, 0.0), dilate_px=8)
    # ---------------- materials
    for m in list(bpy.data.materials):
        if (m.users == 0 and not m.use_fake_user) or m.name.startswith(("PV", "DV_", "UVG")):
            try:
                bpy.data.materials.remove(m)
            except Exception:
                pass
    make_materials(texs)
    apply_team("Alfa")
    rep["textures"] = {k: rel(v) for k, v in texs.items()}
    rep["seconds"] = round(time.time() - t0, 1)
    log("textures", json.dumps(rep))
    json.dump(rep, open(os.path.join(PREV, "_tex_report.json"), "w"), indent=1)
    bpy.ops.wm.save_as_mainfile(filepath=BLEND, compress=True)
    return rep


# =============================================================================
# poses / rifle
# =============================================================================

import soldier_pose as SP    # noqa: E402


def load_rifle(col_name="IV7_Parts", fold_irons=True):
    """IV-7 LOD0 (appended read-only).  The flip-up iron sights are folded (-90 deg, top towards the
    stock) as in the web game when the optic is used (OPTICS_spec section 11)."""
    rig, parts = HN.append_weapon(RIFLE_BLEND, col_name=col_name, rig_name="SK_IV7")
    _COLLIDER.clear()             # a collider from a previously opened file refers to removed objects
    if fold_irons:
        for b in ("rear_sight", "front_sight"):
            pb = rig.pose.bones[b]
            pb.rotation_mode = 'QUATERNION'
            pb.rotation_quaternion = Matrix.Rotation(math.radians(-90.0), 4, 'Y').to_quaternion()
    bpy.context.view_layer.update()
    return rig, parts


def load_lib():
    return json.load(open(POSES_JSON))


def soldier_meshes(include_fp=False):
    out = []
    for o in bpy.data.objects:
        if o.type != 'MESH' or o.name == BODY or "iv_atlas" not in o:
            continue
        if o.name.startswith("FP_") and not include_fp:
            continue
        if o.name.startswith(("LOD", "SK_Soldier", "_L1_", "_L2_", "_SRC_")):
            continue
        out.append(o)
    return out


def drive_all(arm):
    """Engine runtime rules on every soldier mesh with corrective shapes (+ the body proxy)."""
    C.drive_twist_bones(arm)
    spec = bpy.data.objects[BODY].get("iv_correctives")
    for o in soldier_meshes() + [bpy.data.objects[BODY]]:
        if o.data.shape_keys is not None:
            if spec and "iv_correctives" not in o:
                o["iv_correctives"] = spec
            C.drive_correctives(arm, o)


def dev_stance(a):
    bpy.ops.wm.open_mainfile(filepath=BLEND)
    arm = bpy.data.objects[ARM]
    rig, parts = load_rifle()
    lib = load_lib()
    ivlib.clear_lights_cameras()
    sc = bpy.context.scene
    ivlib.setup_cycles(sc, samples=12, threads=4)
    sc.view_settings.view_transform = 'AgX'
    C.neutral_lighting((0, -0.2, 1.3), 1.2, key=0.9, world_strength=0.6)
    bpy.data.objects[BODY].hide_render = True
    for mode, pitch in (("ads", 0.0), ("hip", 0.0), ("ads", 35.0), ("ads", -35.0)):
        C.reset_pose(arm)
        rep = rifle_pose(arm, rig, lib, mode, pitch, parts)
        drive_all(arm)
        log("stance", mode, pitch, json.dumps(rep))
        cam = ivlib.camera("st", (1.1, -1.5, 1.6), (0.0, -0.3, 1.35), lens=40, up=(0, 0, 1))
        ivlib.render(os.path.join(PREV, f"_dev_stance_{mode}_{int(pitch)}.png"), cam, res=(800, 600), samples=12)
        e, fwd, up = SP.fp_camera(arm, rig, mode, pitch)
        cam = ivlib.camera("fp", tuple(e), tuple(e + fwd), fov_deg=80, up=tuple(up), clip_start=0.03)
        hid = [o for o in soldier_meshes() if o.name in ("Soldier_Balaclava", "SG_Helmet", "SG_HelmetShell", "SG_Helmet_Band", "SG_Glasses_Lens", "SG_Glasses_Frame")
               or o.name.startswith("SG_Headset") or o.name.startswith("SG_Glasses") or o.name.startswith("SG_Helmet")]
        for o in hid:
            o.hide_render = True
        ivlib.render(os.path.join(PREV, f"_dev_fp_{mode}_{int(pitch)}.png"), cam, res=(800, 450), samples=12)
        for o in hid:
            o.hide_render = False


# =============================================================================
# stage: validate
# =============================================================================

POSES = [
    ("rest", None, "A-pose (bind pose)"),
    ("arms_raised", SP.p_arms_raised, "clavicle 22 deg + shoulder abduction 105 deg"),
    ("squat_deep", SP.p_squat_deep, "hip 100 / knee 130 / ankle 30 deg, trunk forward, arms forward"),
    ("sprint", SP.p_sprint, "sprint stride: hip 65 / knee 95 (front), hip -22 / knee 35 (rear), arms swinging"),
    ("aim_ads", ("ads", 0.0), "aiming down the sights, IV-7 (IK to the grip sockets)"),
    ("aim_ads_up35", ("ads", 35.0), "aiming 35 deg up"),
    ("aim_ads_down35", ("ads", -35.0), "aiming 35 deg down"),
    ("hip_ready", ("hip", 0.0), "rifle shouldered, head up (hip / ready)"),
]
GARMENTS = ["Soldier_Shirt", "Soldier_Trousers", "Soldier_Balaclava", "Soldier_Boots", "Soldier_Glove_L", "Soldier_Glove_R",
            "Soldier_Armbands", "Soldier_Sole_L", "Soldier_Sole_R"]
TOL_MM = 1.0


class PoseMeshes:
    """Evaluated (posed) world arrays of the meshes, with cached BVHs."""

    def __init__(self, objs):
        self.co, self.tris, self._bvh = {}, {}, {}
        for o in objs:
            self.co[o.name] = S.eval_co(o)
            self.tris[o.name] = S.tris_of(o.data)

    def merged(self, name, parts):
        cos, trs, off = [], [], 0
        for n in parts:
            cos.append(self.co[n]); trs.append(self.tris[n] + off); off += len(self.co[n])
        self.co[name] = np.concatenate(cos); self.tris[name] = np.concatenate(trs)

    def bvh(self, n):
        if n not in self._bvh:
            self._bvh[n] = S.bvh(self.co[n], self.tris[n])
        return self._bvh[n]


def penetr(pm, a, b, tol=TOL_MM / 1000.0, mask=None):
    A = pm.co[a] if mask is None else pm.co[a][mask]
    B = pm.co[b]
    if not len(A):
        return {"count": 0, "max_mm": 0.0}
    bmin, bmax = B.min(0) - 0.03, B.max(0) + 0.03
    cand = np.nonzero(((A >= bmin) & (A <= bmax)).all(1))[0]
    if not len(cand):
        return {"count": 0, "max_mm": 0.0}
    bv = pm.bvh(b)
    loc, nor, fi, d = S.nearest_on(bv, A[cand], 1.0)
    sgn = ((A[cand] - loc) * nor).sum(1)
    sus = cand[(sgn < 0) & (d > tol)]
    dd = d[(sgn < 0) & (d > tol)]
    if not len(sus):
        return {"count": 0, "max_mm": 0.0}
    ins = S.closed_inside(bv, A[sus])
    return {"count": int(ins.sum()), "max_mm": round(float(dd[ins].max()) * 1000, 2) if ins.any() else 0.0}


def layer_poke(pm, inner, outer, mask, tol=TOL_MM / 1000.0):
    """Inner-layer vertices (mask) in FRONT of the outer garment's outer shell (poke-through).
    The outer garment's rolled edges / linings (faces tagged iv_lip) are not part of the shell."""
    A = pm.co[inner][mask]
    if not len(A):
        return {"tested": 0, "poke": 0, "max_mm": 0.0}
    key = outer + "#shell"
    if key not in pm.co:
        lip = S.tri_face_attr(bpy.data.objects[outer].data, "iv_lip")
        pm.co[key] = pm.co[outer]
        pm.tris[key] = pm.tris[outer][lip == 0]
    loc, nor, fi, d = S.nearest_on(pm.bvh(key), A, 0.03)
    ok = fi >= 0
    sd = np.where(((A - loc) * nor).sum(1) >= 0, d, -d)
    bad = ok & (sd > tol)
    return {"tested": int(ok.sum()), "poke": int(bad.sum()), "max_mm": round(float(sd[bad].max()) * 1000, 2) if bad.any() else 0.0}


def gear_objects():
    return [o for o in soldier_meshes() if o.name.startswith("SG_")]


def weights_report(arm):
    names = S.bone_names(arm)
    out = {}
    for o in soldier_meshes():
        W = S.read_W(o, names)
        nz = (W > 1e-6).sum(1)
        sums = W.sum(1)
        b = json.loads(o.get("iv_bind", '["skin"]'))
        r = {"vertices": len(W), "max_influences": int(nz.max()), "unweighted": int((nz == 0).sum()),
             "sum_min": round(float(sums.min()), 5), "sum_max": round(float(sums.max()), 5), "bind": b[0]}
        if b[0] == "rigid":
            j = names.index(b[1])
            r["rigid_bone"] = b[1]
            r["rigid_ok"] = bool((nz == 1).all() and np.allclose(W[:, j], 1.0, atol=1e-5))
        elif b[0] == "fabric":
            r["bones_used"] = sorted({names[k] for k in np.nonzero(W.max(0) > 1e-4)[0]})
        out[o.name] = r
    return out


RIFLE_OBSTACLES = ["SK_Human_Base", "Soldier_Balaclava", "SG_Headset_Cup_L", "SG_Headset_Cup_R", "SG_Headset_Mic",
                   "SG_Glasses_Lens", "SG_Glasses_Frame", "SG_Helmet", "SG_HelmetShell", "SG_Helmet_Rail_R",
                   "SG_PC_Strap_R", "SG_PC_Strap_L", "SG_PC_FrontBag", "SG_PC_AdminPouch", "SG_Helmet_ChinStrap"]
_COLLIDER = {}


def rifle_pose(arm, rig, lib, mode, pitch, parts=None):
    """rifle_stance with the clearance pass against the head gear / body / carrier."""
    if parts is not None and "rc" not in _COLLIDER:
        rig.matrix_world = Matrix.Identity(4)
        bpy.context.view_layer.update()
        _COLLIDER["rc"] = SP.RifleCollider(rig, parts)
    obs = [bpy.data.objects[n] for n in RIFLE_OBSTACLES if n in bpy.data.objects]
    bpy.data.objects[BODY].hide_viewport = False
    return SP.rifle_stance(arm, rig, lib, mode, pitch, collider=_COLLIDER.get("rc"), obstacles=obs)


def pose_by(arm, rig, lib, spec, parts=None):
    C.reset_pose(arm)
    if rig is not None:
        rig.matrix_world = Matrix.Identity(4)
    if spec is None:
        pass
    elif callable(spec):
        spec(arm)
    else:
        return rifle_pose(arm, rig, lib, spec[0], spec[1], parts)
    return None


def intersection_suite(arm, rig_parts, rifle_on):
    objs = soldier_meshes() + [bpy.data.objects[BODY]] + (rig_parts if rifle_on else [])
    pm = PoseMeshes(objs)
    gear = [o.name for o in gear_objects() if o.name not in ("SG_Helmet", "SG_HelmetShell")]
    pm.merged("SG_Helmet+Shell", ["SG_Helmet", "SG_HelmetShell"])
    gear.append("SG_Helmet+Shell")
    r = {"gear_in_body": {}, "body_in_gear": {}, "garment_in_gear": {}}
    for g in gear:
        a = penetr(pm, g, BODY)
        if a["count"]:
            r["gear_in_body"][g] = a
        b = penetr(pm, BODY, g)
        if b["count"]:
            r["body_in_gear"][g] = b
        for gm in GARMENTS:
            c = penetr(pm, gm, g)
            if c["count"]:
                r["garment_in_gear"][f"{gm} in {g}"] = c
    # layer order at the overlaps
    co0 = {n: S.co_of(bpy.data.objects[n]) for n in ("Soldier_Shirt", "Soldier_Balaclava", "Soldier_Boots", "Soldier_Glove_L", "Soldier_Glove_R")}
    w = TROUSERS["waist_z0"] + TROUSERS["waist_tilt"] * co0["Soldier_Shirt"][:, 1]
    r["layers"] = {
        "shirt_tail_inside_trousers": layer_poke(pm, "Soldier_Shirt", "Soldier_Trousers", co0["Soldier_Shirt"][:, 2] < w - 0.008),
        "balaclava_inside_collar": layer_poke(pm, "Soldier_Balaclava", "Soldier_Shirt", REST_INSIDE["bala"]),
        "boot_shaft_inside_trousers": layer_poke(pm, "Soldier_Boots", "Soldier_Trousers", co0["Soldier_Boots"][:, 2] > TROUSERS["hem_z"] + 0.012),
    }
    for s in ("L", "R"):
        g = co0[f"Soldier_Glove_{s}"]
        u = forearm_u(arm, g)
        r["layers"][f"glove_cuff_{s}_inside_sleeve"] = layer_poke(pm, f"Soldier_Glove_{s}", "Soldier_Shirt",
                                                                 u < -(SHIRT["cuff_from_wrist"] + 0.006))
    if rifle_on:
        rp = [o.name for o in rig_parts]
        pm.merged("IV7", rp)
        rr = {"rifle_in_body": penetr(pm, "IV7", BODY)}
        for g in gear:
            x = penetr(pm, "IV7", g)
            if x["count"]:
                rr[f"rifle_in_{g}"] = x
        for gm in GARMENTS:
            worst = {"count": 0, "max_mm": 0.0}
            for part in rp:
                x = penetr(pm, gm, part)
                worst["count"] += x["count"]
                worst["max_mm"] = max(worst["max_mm"], x["max_mm"])
            rr[f"{gm}_in_rifle"] = worst
        for g in gear:
            worst = {"count": 0, "max_mm": 0.0}
            for part in rp:
                x = penetr(pm, g, part)
                worst["count"] += x["count"]
                worst["max_mm"] = max(worst["max_mm"], x["max_mm"])
            if worst["count"]:
                rr[f"{g}_in_rifle"] = worst
        r["rifle"] = rr
    return r


REST_INSIDE = {}


def rest_inside_masks():
    """Balaclava vertices that are inside the shirt collar in the bind pose (the layer order that
    every pose must keep)."""
    bala, shirt = bpy.data.objects["Soldier_Balaclava"], bpy.data.objects["Soldier_Shirt"]
    lip = S.tri_face_attr(shirt.data, "iv_lip")
    sc = S.co_of(shirt)
    bv = S.bvh(sc, S.tris_of(shirt.data)[lip == 0])
    bc = S.co_of(bala)
    sd = S.signed_bvh(bv, bc, maxd=0.02)
    REST_INSIDE["bala"] = np.nan_to_num(sd, nan=1.0) < -0.0005


def gear_gaps():
    """Bind pose: the smallest distance from each gear piece to any other soldier mesh (a piece that
    is not touching or nearly touching something would be floating)."""
    objs = soldier_meshes()
    cos = {o.name: S.co_of(o) for o in objs}
    trs = {o.name: S.tris_of(o.data) for o in objs}
    out = {}
    for o in objs:
        if not o.name.startswith("SG_"):
            continue
        others = [n for n in cos if n != o.name]
        C_ = np.concatenate([cos[n] for n in others])
        off = np.cumsum([0] + [len(cos[n]) for n in others])
        T_ = np.concatenate([trs[n] + off[k] for k, n in enumerate(others)])
        lo, hi = cos[o.name].min(0) - 0.05, cos[o.name].max(0) + 0.05
        keep = ((C_[T_] >= lo) & (C_[T_] <= hi)).all(2).any(1)
        if not keep.any():
            out[o.name] = None
            continue
        bv = S.bvh(C_, T_[keep])
        _, _, fi, d = S.nearest_on(bv, cos[o.name], 0.05)
        out[o.name] = round(float(d.min()) * 1000, 2) if (fi >= 0).any() else None
    return out


def summarize_pose(r, rifle_on):
    worst = 0.0
    bad = []
    for sec in ("gear_in_body", "body_in_gear", "garment_in_gear"):
        for k, v in r[sec].items():
            worst = max(worst, v["max_mm"])
            bad.append(f"{sec}:{k}:{v['count']}@{v['max_mm']}mm")
    lay = max(v["max_mm"] for v in r["layers"].values())
    riflew = 0.0
    if rifle_on:
        for k, v in r["rifle"].items():
            if k.startswith("Soldier_Glove"):
                continue
            riflew = max(riflew, v["max_mm"])
    return {"worst_gear_body_garment_mm": worst, "worst_layer_poke_mm": lay, "worst_rifle_mm": riflew, "findings": bad[:40]}


def stage_validate(a=None):
    t0 = time.time()
    bpy.ops.wm.open_mainfile(filepath=BLEND)
    arm = bpy.data.objects[ARM]
    bpy.data.objects[BODY].hide_viewport = False        # the closed body proxy must be evaluated
    rig, parts = load_rifle()
    lib = load_lib()
    rep = {"asset": "SK_Soldier", "script": rel(__file__), "blender": bpy.app.version_string,
           "limits": {"penetration_tolerance_mm": TOL_MM, "lod0_tris_max": 35000, "lod1_tris_target": 12000,
                      "lod2_tris_target": 5000, "fp_arms_tris_max": 15000, "texture_max": 2048}}
    # triangles
    tri = {o.name: len(S.tris_of(o.data)) for o in soldier_meshes()}
    rep["triangles_lod0"] = {"total": int(sum(tri.values())), "parts": dict(sorted(tri.items(), key=lambda kv: -kv[1]))}
    lods = {}
    for n in ("SK_Soldier_LOD0", "SK_Soldier_LOD1", "SK_Soldier_LOD2", "FP_Arms"):
        if n in bpy.data.objects:
            lods[n] = len(S.tris_of(bpy.data.objects[n].data))
    rep["triangles_export"] = lods
    # textures
    from PIL import Image
    texs = {}
    for f in sorted(os.listdir(TEX_DIR)) if os.path.isdir(TEX_DIR) else []:
        if f.endswith(".png"):
            texs[f] = list(Image.open(os.path.join(TEX_DIR, f)).size)
    rep["textures"] = texs
    rep["weights"] = weights_report(arm)
    names = S.bone_names(arm)
    exp = {}
    for n in ("SK_Soldier_LOD0", "SK_Soldier_LOD1", "SK_Soldier_LOD2", "FP_Arms"):
        if n not in bpy.data.objects:
            continue
        o = bpy.data.objects[n]
        W = S.read_W(o, names)
        nz = (W > 1e-6).sum(1)
        me = o.data
        exp[n] = {"tris": len(S.tris_of(me)), "vertices": len(me.vertices), "max_influences": int(nz.max()),
                  "unweighted": int((nz == 0).sum()), "sum_min": round(float(W.sum(1).min()), 5),
                  "materials": [m.name for m in me.materials if m],
                  "shape_keys": len(me.shape_keys.key_blocks) - 1 if me.shape_keys else 0,
                  "bones_with_weight": sorted({names[k] for k in np.nonzero(W.max(0) > 1e-4)[0]})}
    rep["export_meshes"] = exp
    rep["budgets"] = {
        "lod0_tris": exp.get("SK_Soldier_LOD0", {}).get("tris"), "lod0_ok": exp.get("SK_Soldier_LOD0", {}).get("tris", 1e9) <= 35000,
        "lod1_tris": exp.get("SK_Soldier_LOD1", {}).get("tris"), "lod2_tris": exp.get("SK_Soldier_LOD2", {}).get("tris"),
        "fp_arms_tris": exp.get("FP_Arms", {}).get("tris"), "fp_ok": exp.get("FP_Arms", {}).get("tris", 1e9) <= 15000,
        "max_texture_px": max([max(v) for v in texs.values()] or [0]), "textures_ok": all(max(v) <= 2048 for v in texs.values())}
    C.reset_pose(arm)
    rest_inside_masks()
    rep["gear_attachment_gap_mm"] = gear_gaps()
    # poses
    rep["poses"] = {}
    rigp = [o for o in parts]
    for name, spec, desc in POSES:
        rifle_on = isinstance(spec, tuple)
        for o in rigp:
            o.hide_viewport = not rifle_on
        info = pose_by(arm, rig if rifle_on else None, lib, spec, rigp)
        drive_all(arm)
        bpy.context.view_layer.update()
        r = intersection_suite(arm, rigp, rifle_on)
        r["description"] = desc
        if info:
            r["stance"] = info
        r["summary"] = summarize_pose(r, rifle_on)
        rep["poses"][name] = r
        log("pose", name, json.dumps(r["summary"])[:600])
    C.reset_pose(arm)
    rep["seconds"] = round(time.time() - t0, 1)
    json.dump(rep, open(REPORT, "w"), indent=1)
    log("validation written", rel(REPORT))
    return rep


# =============================================================================
# stage: lods + first-person arms
# =============================================================================

LOD_RATIO = {
    # (LOD1, LOD2) triangle ratios per part class; None = part dropped at that LOD
    "garment": (0.42, 0.17), "glove": (0.22, 0.055), "boot": (0.40, 0.16), "sole": (0.5, 0.25),
    "bala": (0.40, 0.16), "skin": (0.5, 0.2), "big": (0.45, 0.20), "small": (0.5, 0.25),
    "tiny": (0.6, None), "team": (0.5, 0.25),
}
TINY = ("SG_PC_Bungee", "SG_Glasses_Arm", "SG_Headset_Mic", "SG_Headset_Arm", "SG_Helmet_Mount", "SG_PC_Antenna",
        "SG_Helmet_ChinStrap", "SG_PC_PullTab", "SG_Glove_Pad", "SG_Glove_StrapTab", "SG_PC_PackStrap", "SG_PC_PackHandle",
        "SG_Holster_Slide")
FP_GLOVE_TRIS = 3800
FP_CUT_T = 0.32          # FP sleeves keep the upper arm from 32 % of its length (from the shoulder) down


def part_class(ob):
    n = ob.name
    if n.startswith("Soldier_Glove"):
        return "glove"
    if n in ("Soldier_Shirt", "Soldier_Trousers"):
        return "garment"
    if n == "Soldier_Balaclava":
        return "bala"
    if n == "Soldier_FaceSkin":
        return "skin"
    if n == "Soldier_Boots":
        return "boot"
    if n.startswith("Soldier_Sole"):
        return "sole"
    if n in ("Soldier_Armbands", "SG_Helmet_Band"):
        return "team"
    if n.startswith(TINY):
        return "tiny"
    return "big" if len(ob.data.polygons) > 250 else "small"


def copy_obj(ob, name, col):
    o = ob.copy()
    o.data = ob.data.copy()
    o.name = name
    o.data.name = name
    col.objects.link(o)
    return o


def decimated_copy(ob, ratio, name, col, names, arm):
    o = copy_obj(ob, name, col)
    if o.data.shape_keys is not None:
        o.shape_key_clear()
    for m in list(o.modifiers):
        o.modifiers.remove(m)
    for l in list(o.data.uv_layers):
        if l.name != "UVMap":
            o.data.uv_layers.remove(l)
    n = len(S.tris_of(o.data))
    target = max(12, int(n * ratio))
    if target < n:
        dm = o.modifiers.new("Dec", 'DECIMATE')
        dm.ratio = target / n
        dm.use_collapse_triangulate = True
        S.apply_modifier(o, dm)
    W0 = S.read_W(ob, names)
    W = S.transfer_weights(S.co_of(ob), S.tris_of(ob.data), W0, S.co_of(o))
    b = json.loads(ob.get("iv_bind", '["skin"]'))
    if b[0] == "rigid":
        W = S.rigid_W(len(W), names, b[1])
    S.write_W(o, W, names, arm)
    for k in ("iv_atlas", "iv_zone", "iv_bind"):
        if k in ob:
            o[k] = ob[k]
    o.data.materials.clear()
    for m in ob.data.materials:
        o.data.materials.append(m)
    return o


def join_export(objs, name, col):
    cps = [copy_obj(o, name + "_" + o.name, col) for o in objs]
    for c in cps:
        for l in list(c.data.uv_layers):
            if l.name != "UVMap":
                c.data.uv_layers.remove(l)
    for c in cps:
        c.parent = bpy.data.objects[ARM]
        c.hide_viewport = False
        c.hide_render = False
        c.hide_set(False)
    ob = S.join_objects(cps, name)
    for m in list(ob.modifiers):
        if m.type != 'ARMATURE':
            ob.modifiers.remove(m)
    if not any(m.type == 'ARMATURE' for m in ob.modifiers):
        ob.modifiers.new("Armature", 'ARMATURE').object = bpy.data.objects[ARM]
    return ob


FP_SLEEVE_TRIS = 4600


def build_fp_arms(arm, col, names):
    """FP_Arms: the sleeves cut from the HIGH-resolution shirt (panels / UVs, big folds) from
    FP_CUT_T of the upper arm down to the cuff, decimated for first person, with the rolled cuff
    edge and a closing cap at the cut (inner sleeve, never meant to be seen); the team armbands; the
    gloves from the full-resolution gloves; the glove kit (knuckle guard, finger pads, wrist strap).
    Same 57-bone skeleton; only arm bones carry weight."""
    hi = bpy.data.objects["_HI_Soldier_Shirt"]
    co = S.co_of(hi)
    W = S.read_W(hi, names)
    dom = np.array(names)[W.argmax(1)]
    t_up = limb_param(arm, co, "upperarm_{s}")
    armb = np.isin(dom, ARM_BONES) | (np.abs(co[:, 0]) > 0.30)
    ok = armb & (t_up > FP_CUT_T - 0.08)

    def centre_ok(c):
        return abs(c[0]) > 0.15 and limb_param(arm, c[None], "upperarm_{s}")[0] > FP_CUT_T
    keep = face_keep(hi.data, ok, centre_ok)
    sl, src = S.copy_faces(hi, keep, "FP_Sleeves", col)
    hv, ht, hW = co, S.tris_of(hi.data), W
    if sl.data.shape_keys is not None:
        sl.shape_key_clear()
    SC.decimate_uv_safe(sl, FP_SLEEVE_TRIS)
    S.write_W(sl, S.transfer_weights(hv, ht, hW, S.co_of(sl)), names, arm)
    made = transfer_shape_keys(hi, sl)
    if sl.data.shape_keys is not None:
        for k in list(sl.data.shape_keys.key_blocks[1:]):
            if not k.name.startswith("CS_elbow"):
                sl.shape_key_remove(k)
    # rolled cuff edge (the cuff end is in view all the time)
    co2 = S.co_of(sl)
    cuffs = [lp for lp in S.boundary_loops(sl.data) if np.abs(co2[lp, 0]).mean() > 0.40]
    for lp in cuffs:
        s_ = "l" if co2[lp, 0].mean() > 0 else "r"
        wj, ax = HN.forearm_axis(arm, s_)
        add_lip_normal(sl, lp, edge=0.0034, depth=0.018, lining=lambda p, _ax=ax: -_ax)
    # cap the cut end (inner sleeve, never meant to be seen) with a fan, tagged as lip
    co2 = S.co_of(sl)
    loops = [lp for lp in S.boundary_loops(sl.data) if np.abs(co2[lp, 0]).mean() < 0.40]
    bm = bmesh.new()
    bm.from_mesh(sl.data)
    bm.verts.ensure_lookup_table()
    liplay = bm.faces.layers.int.get("iv_lip") or bm.faces.layers.int.new("iv_lip")
    dl = bm.verts.layers.deform.verify()
    uvl = bm.loops.layers.uv.active
    capped = 0
    ring_refs = [[bm.verts[i] for i in lp] for lp in loops]
    for lp, refs in zip(loops, ring_refs):
        c = co2[lp].mean(0)
        cv = bm.verts.new(tuple(map(float, c)))
        for kk, w in refs[0][dl].items():
            cv[dl][kk] = w
        uv0 = None
        for l in refs[0].link_loops:
            uv0 = tuple(l[uvl].uv)
            break
        for i in range(len(refs)):
            f = bm.faces.new((refs[i], refs[(i + 1) % len(refs)], cv))
            f[liplay] = 1
            if uv0 is not None:
                for l in f.loops:
                    l[uvl].uv = uv0
            capped += 1
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    bm.to_mesh(sl.data)
    bm.free()
    sl.data.update()
    # armbands (whole bands; they sit below the cut)
    abs_ = [copy_obj(bpy.data.objects[f"SG_Armband_{s_}"], f"_fpab_{s_}", col) for s_ in ("L", "R")]
    fab = S.join_objects(abs_, "FP_Armbands")
    gl = []
    for s_ in ("L", "R"):
        g = bpy.data.objects["_SRC_" + GLOVES[s_.lower()]]
        o = copy_obj(g, f"FP_Glove_{s_}", col)
        o.hide_viewport = False
        o.hide_render = False
        o.hide_set(False)
        for m in list(o.modifiers):
            o.modifiers.remove(m)
        n = len(S.tris_of(o.data))
        if n > FP_GLOVE_TRIS:
            dm = o.modifiers.new("Dec", 'DECIMATE')
            dm.ratio = FP_GLOVE_TRIS / n
            dm.use_collapse_triangulate = True
            S.apply_modifier(o, dm)
        Wg = S.transfer_weights(S.co_of(g), S.tris_of(g.data), S.read_W(g, names), S.co_of(o))
        S.write_W(o, Wg, names, arm)
        gl.append(o)
        # glove kit copies in glove texture space
        kit = [ob for ob in bpy.data.objects if ob.name.startswith("SG_Glove_") and ob.name.endswith("_" + s_)]
        for kb in kit:
            kc = copy_obj(kb, "FP_" + kb.name[3:], col)
            me = kc.data
            if "GloveUV" in me.uv_layers:
                uvg = S.uv_array(me, "GloveUV")
                me.uv_layers["UVMap"].data.foreach_set("uv", uvg.ravel())
                me.uv_layers.remove(me.uv_layers["GloveUV"])
            kc["iv_atlas"] = "fpglove"
            gl.append(kc)
    for o in [sl, fab] + gl:
        o.parent = arm
        if not any(m.type == 'ARMATURE' for m in o.modifiers):
            o.modifiers.new("Armature", 'ARMATURE').object = arm
    sl["iv_atlas"] = "fp"
    sl["iv_panels"] = hi.get("iv_panels", "{}")
    fab["iv_atlas"] = "team"
    for g in gl:
        g["iv_atlas"] = "fpglove"
    return sl, fab, gl, {"cap_faces": capped, "cut_loops": len(loops), "cuff_lips": len(cuffs), "elbow_keys": [k for k in made if k.startswith("CS_elbow")]}


def stage_lods(a=None):
    t0 = time.time()
    bpy.ops.wm.open_mainfile(filepath=BLEND)
    arm = bpy.data.objects[ARM]
    C.reset_pose(arm)
    names = S.bone_names(arm)
    for n in list(bpy.data.collections.keys()):
        if n.startswith("Soldier_Export") or n == "Soldier_FP":
            for o in list(bpy.data.collections[n].objects):
                bpy.data.objects.remove(o)
            bpy.data.collections.remove(bpy.data.collections[n])
    ecol = ivlib.collection("Soldier_Export")
    parts = soldier_meshes()
    rep = {}
    lod0 = join_export(parts, "SK_Soldier_LOD0", ecol)
    rep["LOD0"] = len(S.tris_of(lod0.data))
    for li in (1, 2):
        cps = []
        for o in parts:
            r = LOD_RATIO[part_class(o)][li - 1]
            if r is None:
                continue
            cps.append(decimated_copy(o, r, f"_L{li}_{o.name}", ecol, names, arm))
        lo = S.join_objects(cps, f"SK_Soldier_LOD{li}")
        rep[f"LOD{li}"] = len(S.tris_of(lo.data))
    fcol = ivlib.collection("Soldier_FP")
    sl, fab, gl, info = build_fp_arms(arm, fcol, names)
    rep["fp_parts"] = {o.name: len(S.tris_of(o.data)) for o in [sl, fab] + gl}
    rep["fp_info"] = info
    for o in (lod0, bpy.data.objects["SK_Soldier_LOD1"], bpy.data.objects["SK_Soldier_LOD2"]):
        o.hide_render = True
        o["iv_export"] = 1
    rep["seconds"] = round(time.time() - t0, 1)
    log("lods", json.dumps(rep))
    bpy.ops.wm.save_as_mainfile(filepath=BLEND, compress=True)
    return rep


# =============================================================================
# stage: first-person arms textures / materials
# =============================================================================

FP_RES = 2048


def stage_fp_tex(a=None):
    t0 = time.time()
    bpy.ops.wm.open_mainfile(filepath=BLEND)
    arm = bpy.data.objects[ARM]
    C.reset_pose(arm)
    sl = bpy.data.objects["FP_Sleeves"]
    gl = [o for o in bpy.data.objects if o.get("iv_atlas") == "fpglove" and o.name.startswith("FP_")]
    fab = bpy.data.objects["FP_Armbands"]
    rep = {}
    # the sleeve panels keep their grain-oriented islands: one density, packed on 90 deg steps
    ivlib.select([sl], sl)
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.uv.select_all(action='SELECT')
    bpy.ops.uv.average_islands_scale()
    bpy.ops.uv.pack_islands(rotate=True, rotate_method='CARDINAL', margin=0.003, margin_method='FRACTION',
                            shape_method='CONCAVE', scale=True)
    bpy.ops.object.mode_set(mode='OBJECT')
    r = ivlib.uv_island_raster([sl], FP_RES)
    rep["uv"] = {"coverage": round(r["coverage"], 4), "overlap_px": int(r["overlap_px"]), "islands": len(r["islands"])}
    rep["px_per_cm_sleeves"] = round(ivlib.texel_density(sl, FP_RES), 2)
    rep["px_per_cm_gloves"] = round(ivlib.texel_density(gl[0], 2048), 2)
    fr = T.Frames(arm)
    td = S.atlas_texels([sl], FP_RES)
    panel_names = {int(k): v for k, v in json.loads(sl.get("iv_panels", "{}")).items()}
    cm = T.cloth_maps2(td, [sl], fr, panel_names, SHIRT, TROUSERS)
    # the FP sleeve is a "Soldier_Shirt" for the material logic
    ao = ao_texels([sl], td, FP_RES, 0.015)
    nd = HN.height_to_normal(td, cm["h"], FP_RES)
    nh = T.hi_normal_ts(td, [sl], {"FP_Sleeves": bpy.data.objects["_HI_Soldier_Shirt"]})
    nrm = T.blend_normals(nh, nd)
    texs = {}
    texs["n"] = S.texels_write(nrm * 0.5 + 0.5, td, tex_path("T_Soldier_FPArms_Normal.png"), fill=(0.5, 0.5, 1.0))
    texs["n_dx"] = ivlib.normal_gl_to_dx(texs["n"], tex_path("T_Soldier_FPArms_Normal_DX.png"))
    orm = np.stack([np.clip(ao * cm["cav"], 0, 1), cm["rough"], np.zeros(len(ao))], 1)
    texs["orm"] = S.texels_write(orm, td, tex_path("T_Soldier_FPArms_ORM.png"), fill=(1.0, 0.85, 0.0))
    for tm in TEAMS:
        texs[f"bc_{tm}"] = S.texels_write(T.cloth_base2(cm, tm), td, tex_path(f"T_Soldier_FPArms_{tm}_BaseColor.png"),
                                          fill=(0.2, 0.2, 0.2), srgb=True)
        export_material_reuse(f"M_FPArms_Sleeve_{tm}", texs[f"bc_{tm}"], texs["orm"], texs["n"]).use_fake_user = True
    mg = export_material_reuse("M_FPArms_Glove", tex_path("T_Soldier_Glove_BaseColor.png"), tex_path("T_Soldier_Glove_ORM.png"),
                               os.path.join(GLOVE_TEX, "T_Glove_Normal.png"))
    mg.use_fake_user = True
    for g in gl:
        g.data.materials.clear()
        g.data.materials.append(mg)
    apply_fp_team("Alfa")
    for n in ("FP_Arms",):
        if n in bpy.data.objects:
            bpy.data.objects.remove(bpy.data.objects[n])
    fp = join_export([sl, fab] + gl, "FP_Arms", bpy.data.collections["Soldier_FP"])
    fp.hide_render = True
    fp["iv_export"] = 1
    rep["fp_arms_tris"] = len(S.tris_of(fp.data))
    rep["fp_parts"] = {o.name: len(S.tris_of(o.data)) for o in [sl, fab] + gl}
    rep["textures"] = {k: rel(v) for k, v in texs.items()}
    rep["seconds"] = round(time.time() - t0, 1)
    log("fp_tex", json.dumps(rep))
    json.dump(rep, open(os.path.join(PREV, "_fp_report.json"), "w"), indent=1)
    bpy.ops.wm.save_as_mainfile(filepath=BLEND, compress=True)
    return rep


def apply_fp_team(team):
    for n in ("FP_Sleeves",):
        o = bpy.data.objects[n]
        o.data.materials.clear()
        o.data.materials.append(bpy.data.materials[f"M_FPArms_Sleeve_{team}"])
    o = bpy.data.objects["FP_Armbands"]
    o.data.materials.clear()
    o.data.materials.append(bpy.data.materials[f"M_Soldier_Team_{team}"])
    if "FP_Arms" in bpy.data.objects:
        fp = bpy.data.objects["FP_Arms"]
        for i, m in enumerate(fp.data.materials):
            if m and m.name.startswith("M_FPArms_Sleeve_"):
                fp.data.materials[i] = bpy.data.materials[f"M_FPArms_Sleeve_{team}"]
            elif m and m.name.startswith("M_Soldier_Team_"):
                fp.data.materials[i] = bpy.data.materials[f"M_Soldier_Team_{team}"]


def apply_team_export(team):
    """Swap the team materials on the joined export meshes (same geometry, material slots by name)."""
    for n in ("SK_Soldier_LOD0", "SK_Soldier_LOD1", "SK_Soldier_LOD2"):
        if n not in bpy.data.objects:
            continue
        me = bpy.data.objects[n].data
        for i, m in enumerate(me.materials):
            if m is None:
                continue
            for pre in ("M_Soldier_Cloth_", "M_Soldier_GearFabric_", "M_Soldier_Team_"):
                if m.name.startswith(pre):
                    me.materials[i] = bpy.data.materials[pre + team]
    apply_team(team)
    if "FP_Sleeves" in bpy.data.objects:
        apply_fp_team(team)


# =============================================================================
# stage: evidence renders
# =============================================================================

RS = 28          # render samples (denoised)


def label(path, text, sub=None):
    from PIL import Image, ImageDraw
    im = Image.open(path).convert("RGB")
    dr = ImageDraw.Draw(im)
    h = 22 if sub is None else 38
    dr.rectangle([0, 0, im.width, h], fill=(26, 26, 28))
    dr.text((8, 5), text, fill=(236, 236, 236))
    if sub:
        dr.text((8, 21), sub, fill=(185, 185, 185))
    im.save(path)
    return path


def compose(paths, out, cols, size=None, titles=None, title=None):
    from PIL import Image, ImageDraw
    ims = [Image.open(p).convert("RGB") for p in paths]
    w, h = size or ims[0].size
    rows = (len(ims) + cols - 1) // cols
    top = 24 if title else 0
    sheet = Image.new("RGB", (cols * w, rows * h + top), (24, 24, 26))
    dr = ImageDraw.Draw(sheet)
    if title:
        dr.text((8, 6), title, fill=(240, 240, 240))
    for i, im in enumerate(ims):
        if im.size != (w, h):
            im = im.resize((w, h), Image.LANCZOS)
        x, y = (i % cols) * w, top + (i // cols) * h
        sheet.paste(im, (x, y))
        if titles:
            dr.rectangle([x, y, x + w, y + 18], fill=(26, 26, 28))
            dr.text((x + 6, y + 3), titles[i], fill=(230, 230, 230))
    sheet.save(out)
    return out


def studio(center=(0, 0, 0.95), size=1.9, ground=True):
    ivlib.clear_lights_cameras()
    sc = bpy.context.scene
    ivlib.setup_cycles(sc, samples=RS, threads=4)
    sc.view_settings.view_transform = 'AgX'
    sc.view_settings.look = 'None'
    C.neutral_lighting(center, size, key=0.95, world_strength=0.62)
    g = bpy.data.objects.get("IVC_Ground")
    if ground and g is None:
        g = C.ground_plane(size=40.0, color=(0.30, 0.30, 0.31))
    if g:
        g.hide_render = not ground
    return sc


def outdoor(ground_color=(0.16, 0.19, 0.09)):
    ivlib.clear_lights_cameras()
    sc = bpy.context.scene
    ivlib.setup_cycles(sc, samples=RS, threads=4)
    sc.view_settings.view_transform = 'AgX'
    ivlib.world_sky(sun_elevation=38.0, sun_rotation=222.0, strength=0.30)
    ivlib.add_sun(elevation=38.0, rotation=222.0, strength=3.2, angle=0.8)
    g = bpy.data.objects.get("IV_Grass")
    if g is None:
        me = bpy.data.meshes.new("IV_Grass")
        h = 400.0
        me.from_pydata([(-h, -h, 0), (h, -h, 0), (h, h, 0), (-h, h, 0)], [], [(0, 1, 2, 3)])
        g = bpy.data.objects.new("IV_Grass", me)
        sc.collection.objects.link(g)
        m = C.flat_material("IV_GrassMat", ground_color)
        m.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.95
        me.materials.append(m)
    g.hide_render = False
    gg = bpy.data.objects.get("IVC_Ground")
    if gg:
        gg.hide_render = True
    return sc


def show_only(objs):
    keep = set(o.name for o in objs)
    for o in bpy.data.objects:
        if o.type == 'MESH' and o.name not in ("IVC_Ground", "IV_Grass"):
            o.hide_render = o.name not in keep


def body_parts():
    return soldier_meshes()


def cam_look(name, loc, tgt, lens=None, fov=None, clip=0.02):
    return ivlib.camera(name, tuple(loc), tuple(tgt), lens=lens, fov_deg=fov, up=(0, 0, 1), clip_start=clip)


def render_teams(made):
    studio()
    fronts = []
    for team in TEAMS:
        apply_team(team)
        show_only(body_parts())
        views = []
        for vn, loc in (("front", (0.0, -4.6, 1.0)), ("side", (4.6, -0.25, 1.0)), ("back", (0.0, 4.6, 1.0))):
            cam = cam_look("ct_" + vn, loc, (0, 0, 0.93), lens=40)
            cam.data.sensor_fit = 'VERTICAL'
            cam.data.sensor_height = 24.0
            pth = os.path.join(PREV, f"_tmp_team_{team}_{vn}.png")
            ivlib.render(pth, cam, res=(528, 880), samples=RS)
            views.append(pth)
            if vn == "front":
                fronts.append(pth)
        out = compose(views, os.path.join(PREV, f"Soldier_team_{team}.png"), 3, size=(533, 880),
                      titles=["front", "left side", "back"],
                      title=f"SK_Soldier team {team}: camo {T.CAMO[team]['name']}, team colour {TEAMS[team]['color']} (armbands, helmet band, symbol: {TEAMS[team]['symbol']}), gear tint {T.CAMO[team]['gear']}; neutral studio light, A-pose")
        made.append(out)
    made.append(compose(fronts, os.path.join(PREV, "Soldier_teams_front.png"), 3, size=(533, 880), titles=list(TEAMS),
                        title="Team variants side by side (same mesh; clothing BaseColor 1024 + gear tint + team band texture swapped)"))
    apply_team("Alfa")


def render_closeups(made, team="Alfa"):
    studio(center=(0, 0, 1.4), size=0.8)
    apply_team(team)
    show_only(body_parts())
    shots = [("vest_front", (0.75, -1.05, 1.42), (0.0, -0.10, 1.26), 50), ("vest_back", (-0.8, 1.05, 1.42), (0.0, 0.08, 1.24), 50),
             ("helmet_front", (0.42, -0.55, 1.76), (0.0, -0.05, 1.69), 60), ("helmet_back", (-0.45, 0.52, 1.80), (0.0, -0.03, 1.69), 60)]
    paths = []
    for nm, loc, tgt, lens in shots:
        cam = cam_look("cc_" + nm, loc, tgt, lens=lens)
        pth = os.path.join(PREV, f"Soldier_closeup_{nm}.png")
        ivlib.render(pth, cam, res=(800, 800), samples=RS + 8)
        paths.append(pth)
    made.append(compose(paths, os.path.join(PREV, "Soldier_closeups.png"), 2, size=(800, 800),
                        titles=["plate carrier 3/4 front", "plate carrier 3/4 back", "helmet 3/4 front", "helmet 3/4 back"],
                        title=f"Close-ups (team {team}): plate carrier with plates, cummerbund, IV-7 magazines, radio / GP pouches; helmet with cover, rails, NVG shroud, headset, glasses, gaiter"))
    made += paths


def render_poses(made, rig, parts, lib):
    studio()
    apply_team("Alfa")
    arm = bpy.data.objects[ARM]
    for name, spec, desc in POSES[1:]:
        rifle_on = isinstance(spec, tuple)
        info = pose_by(arm, rig if rifle_on else None, lib, spec, parts)
        drive_all(arm)
        show_only(body_parts() + (parts if rifle_on else []))
        for o in parts:
            o.hide_render = not rifle_on
        paths = []
        views = (("3/4 front", (2.2, -3.3, 1.35)), ("side", (3.9, 0.3, 1.2)), ("3/4 back", (-2.4, 3.1, 1.4)))
        for vi, (vn, loc) in enumerate(views):
            tz = 0.62 if name == "squat_deep" else 0.95
            cam = cam_look("cp", loc, (0, -0.1, tz), lens=40)
            cam.data.sensor_fit = 'VERTICAL'
            cam.data.sensor_height = 24.0
            pth = os.path.join(PREV, f"_tmp_pose_{name}_{vi}.png")
            ivlib.render(pth, cam, res=(533, 880), samples=RS)
            paths.append(pth)
        out = compose(paths, os.path.join(PREV, f"Soldier_pose_{name}.png"), 3, size=(533, 880), titles=[v[0] for v in views],
                      title=f"{name}: {desc} (twist bones + corrective shapes driven; intersection results in Soldier_validation.json)")
        made.append(out)
    C.reset_pose(arm)
    rig.matrix_world = Matrix.Identity(4)


def render_stance(made, rig, parts, lib):
    studio(center=(0, -0.3, 1.2), size=1.6)
    arm = bpy.data.objects[ARM]
    for mode, pitch, tag in (("ads", 0.0, "aim"), ("hip", 0.0, "hip")):
        C.reset_pose(arm)
        info = rifle_pose(arm, rig, lib, mode, pitch, parts)
        drive_all(arm)
        show_only(body_parts() + parts)
        cam = cam_look("cs", (1.35, -2.25, 1.62), (0.0, -0.35, 1.30), lens=42)
        pth = os.path.join(PREV, f"Soldier_stance_{tag}.png")
        ivlib.render(pth, cam, res=(1600, 900), samples=RS)
        made.append(label(pth, f"Holding the IV-7 ({'aiming down the sights' if mode == 'ads' else 'shouldered, hip / ready'}): arms two-bone IK to the grip sockets (Hand_Poses.json), fingers from the grip poses",
                          f"butt on the shoulder pocket, rifle cleared of body / head gear / carrier: {json.dumps(info.get('clearance', {}))}"))
    C.reset_pose(arm)
    rig.matrix_world = Matrix.Identity(4)


def lod_copies(team_list, lods, spacing):
    """Duplicates of the joined LOD meshes (same armature), one per (team, lod), placed along X."""
    col = ivlib.collection("_RenderCopies")
    out = []
    k = 0
    for team in team_list:
        for li in lods:
            src = bpy.data.objects[f"SK_Soldier_LOD{li}"]
            o = src.copy()
            o.data = src.data.copy()
            o.name = f"_rc_{team}_{li}"
            col.objects.link(o)
            me = o.data
            for i, m in enumerate(me.materials):
                if m is None:
                    continue
                for pre in ("M_Soldier_Cloth_", "M_Soldier_GearFabric_", "M_Soldier_Team_"):
                    if m.name.startswith(pre):
                        me.materials[i] = bpy.data.materials[pre + team]
            o.location = ((k - (len(team_list) * len(lods) - 1) / 2.0) * spacing, 0, 0)
            o.hide_render = False
            out.append(o)
            k += 1
    return out, col


def render_distance(made):
    outdoor()
    arm = bpy.data.objects[ARM]
    C.reset_pose(arm)
    # LOD0 / LOD1 / LOD2 side by side at 5, 20, 40 m (80 deg horizontal FOV, eye height 1.65 m)
    cps, col = lod_copies(["Alfa"], (0, 1, 2), 1.3)
    show_only(cps)
    tris = {li: len(S.tris_of(bpy.data.objects[f"SK_Soldier_LOD{li}"].data)) for li in (0, 1, 2)}
    for d in (5, 20, 40):
        cam = cam_look("cd", (0.0, -d, 1.65), (0.0, 0.0, 1.0 + 0.6 * (5.0 / d)), fov=80, clip=0.1)
        pth = os.path.join(PREV, f"Soldier_lod_{d}m.png")
        ivlib.render(pth, cam, res=(1600, 900), samples=RS)
        crop = crop_center(pth, os.path.join(PREV, f"Soldier_lod_{d}m_crop.png"), d)
        made.append(label(pth, f"LOD0 / LOD1 / LOD2 (left to right) at {d} m, 80 deg horizontal FOV, 1600x900, eye 1.65 m (sun 38 deg)",
                          f"triangles LOD0 {tris[0]}, LOD1 {tris[1]}, LOD2 {tris[2]}; enlarged crop: {os.path.basename(crop)}"))
        made.append(crop)
    for o in cps:
        bpy.data.objects.remove(o)
    # team readability at 20 / 40 m (the LOD a bot would use at that distance)
    for d, li in ((20, 1), (40, 2)):
        cps, col = lod_copies(list(TEAMS), (li,), 1.6)
        show_only(cps)
        cam = cam_look("cdt", (0.0, -d, 1.65), (0.0, 0.0, 1.0 + 0.6 * (5.0 / d)), fov=80, clip=0.1)
        pth = os.path.join(PREV, f"Soldier_teams_{d}m.png")
        ivlib.render(pth, cam, res=(1600, 900), samples=RS)
        crop = crop_center(pth, os.path.join(PREV, f"Soldier_teams_{d}m_crop.png"), d)
        made.append(label(pth, f"Teams Alfa / Bravo / Charlie (left to right) at {d} m with LOD{li}, 80 deg FOV 1600x900",
                          f"enlarged crop: {os.path.basename(crop)}"))
        made.append(crop)
        for o in cps:
            bpy.data.objects.remove(o)


def crop_center(src, dst, d):
    """Nearest-neighbour enlargement of the image centre (what a player sees, pixel for pixel)."""
    from PIL import Image
    im = Image.open(src).convert("RGB")
    w = {5: 1600, 20: 640, 40: 400}[d]
    h = int(w * 9 / 16)
    x0, y0 = (im.width - w) // 2, int(im.height * 0.5 - h * 0.55)
    c = im.crop((x0, y0, x0 + w, y0 + h)).resize((1600, 900), Image.NEAREST)
    c.save(dst)
    return label(dst, f"centre crop {w}x{h} px of the {d} m frame enlarged {1600 // w}x (nearest neighbour)")


def fp_cut_visibility(cam, arm):
    """Share of the FP sleeve cut-ring vertices inside the camera frustum (should be 0)."""
    from bpy_extras.object_utils import world_to_camera_view
    sl = bpy.data.objects["FP_Sleeves"]
    lip = S.tri_face_attr(sl.data, "iv_lip")
    tris = S.tris_of(sl.data)
    co = S.eval_co(sl)
    capv = np.unique(tris[lip == 1])
    # the cap fans are the lip faces whose vertices lie on the upper arm
    ta = limb_param(arm, S.co_of(sl), "upperarm_{s}")
    capv = capv[ta[capv] < FP_CUT_T + 0.05]
    sc = bpy.context.scene
    inside = 0
    for v in capv:
        p = world_to_camera_view(sc, cam, Vector(tuple(co[v])))
        if 0 <= p.x <= 1 and 0 <= p.y <= 1 and p.z > 0:
            inside += 1
    return {"cut_vertices": int(len(capv)), "inside_frustum": int(inside)}


def render_fp(made, rig, parts, lib):
    outdoor(ground_color=(0.20, 0.21, 0.16))
    arm = bpy.data.objects[ARM]
    apply_fp_team("Alfa")
    fp = [bpy.data.objects[n] for n in ("FP_Sleeves", "FP_Armbands")] + \
        [o for o in bpy.data.objects if o.name.startswith("FP_") and o.get("iv_atlas") == "fpglove"]
    res = {}
    for mode, pitch in (("hip", 0.0), ("hip", 35.0), ("hip", -35.0), ("ads", 0.0), ("ads", 35.0), ("ads", -35.0)):
        C.reset_pose(arm)
        info = rifle_pose(arm, rig, lib, mode, pitch, parts)
        drive_all(arm)
        for o in fp:
            if o.data.shape_keys is not None:
                o["iv_correctives"] = bpy.data.objects[BODY].get("iv_correctives")
                C.drive_correctives(arm, o)
        show_only(fp + parts)
        e, fwd, up = SP.fp_camera(arm, rig, mode, pitch)
        cam = ivlib.camera("cfp", tuple(e), tuple(e + fwd), fov_deg=80, up=tuple(up), clip_start=0.01)
        vis = fp_cut_visibility(cam, arm)
        tag = f"{mode}_{'level' if pitch == 0 else ('up' if pitch > 0 else 'down')}"
        pth = os.path.join(PREV, f"Soldier_fp_{tag}.png")
        ivlib.render(pth, cam, res=(1600, 900), samples=RS)
        cam_desc = "camera on the optic axis at the cheek-weld eye point" if mode == "ads" else "camera at the eye"
        made.append(label(pth, f"FP_Arms + IV-7, {mode.upper()} looking {'level' if pitch == 0 else ('%+.0f deg' % pitch)}; 80 deg horizontal FOV; {cam_desc}",
                          f"sleeve cut-ring vertices inside the view: {vis['inside_frustum']} / {vis['cut_vertices']}; arms two-bone IK to the IV-7 sockets"))
        res[tag] = {"cut_visibility": vis, "stance": {k: info.get(k) for k in ("ik", "clearance", "params_deg")}}
    C.reset_pose(arm)
    rig.matrix_world = Matrix.Identity(4)
    json.dump(res, open(os.path.join(PREV, "_fp_views.json"), "w"), indent=1)
    return res


def stage_render(a=None):
    t0 = time.time()
    only = (a.only.split(",") if a and a.only else None)
    bpy.ops.wm.open_mainfile(filepath=BLEND)
    arm = bpy.data.objects[ARM]
    bpy.data.objects[BODY].hide_viewport = False
    bpy.data.objects[BODY].hide_render = True
    rig, parts = load_rifle()
    lib = load_lib()
    made = []
    jobs = [("teams", lambda: render_teams(made)), ("closeups", lambda: render_closeups(made)),
            ("poses", lambda: render_poses(made, rig, parts, lib)), ("stance", lambda: render_stance(made, rig, parts, lib)),
            ("distance", lambda: render_distance(made)), ("fp", lambda: render_fp(made, rig, parts, lib))]
    for nm, fn in jobs:
        if only and nm not in only:
            continue
        fn()
    import shutil
    for f in os.listdir(PREV):
        if f.startswith("_tmp_"):
            fp_ = os.path.join(PREV, f)
            shutil.rmtree(fp_) if os.path.isdir(fp_) else os.remove(fp_)
    log("render", len(made), "images", round(time.time() - t0, 1), "s")
    return made


# =============================================================================
# stage: export + re-import
# =============================================================================

SCRATCH_EXPORT = os.environ.get("IV_SCRATCH", os.path.join(HERE, "_export_tmp"))


def gltf_factor_check(path):
    """Read the glTF JSON chunk of a .glb and return the materials' baseColorFactor values."""
    import struct
    with open(path, "rb") as f:
        data = f.read()
    ln = struct.unpack("<I", data[12:16])[0]
    js = json.loads(data[20:20 + ln])
    return {m["name"]: m.get("pbrMetallicRoughness", {}).get("baseColorFactor") for m in js.get("materials", [])}


def runtime_json():
    arm = bpy.data.objects[ARM]
    spec = json.loads(bpy.data.objects[BODY].get("iv_correctives", "{}"))
    shapes = {}
    for n in ("SK_Soldier_LOD0", "FP_Arms"):
        if n in bpy.data.objects and bpy.data.objects[n].data.shape_keys:
            shapes[n] = [k.name for k in bpy.data.objects[n].data.shape_keys.key_blocks[1:]]
    return {
        "asset": "SK_Soldier", "version": f"ivsoldier {S.IVSOLDIER_VERSION}",
        "skeleton": "SK_Human_Base 57 bones (unchanged names / hierarchy / rest pose)",
        "twist_bones": "same rule as Human_Base.runtime.json (ivchar.drive_twist_bones)",
        "correctives": {"spec": spec, "rule": "ivchar.drive_correctives (angle-driven cross-fade, same as SK_Human_Base)",
                        "meshes": shapes, "note": "LOD1 / LOD2 carry no shape keys"},
        "teams": {t: {"cloth_basecolor": f"T_Soldier_Cloth_{t}_BaseColor.png (1024)",
                      "team_basecolor": f"T_Soldier_Team_{t}_BaseColor.png (256)",
                      "gear_fabric_tint_linear": list(gear_tint(t)), "fp_sleeve_basecolor": f"T_Soldier_FPArms_{t}_BaseColor.png",
                      "team_color": TEAMS[t]["color"], "symbol": TEAMS[t]["symbol"], "camo": T.CAMO[t]["name"]} for t in TEAMS},
        "materials": {"M_Soldier_Cloth_<Team>": "clothing atlas (shirt, trousers, gaiter / balaclava, helmet cover, gloves)",
                      "M_Soldier_GearFabric_<Team>": "gear atlas x baseColorFactor (team tint) -- nylon carrier, pouches, belt",
                      "M_Soldier_GearHard": "gear atlas, untinted -- helmet shell, rails, shroud, headset, glasses, mags, boots, knee pads",
                      "M_Soldier_Team_<Team>": "armbands + helmet band (256 texture per team)"},
        "first_person": {"mesh": "FP_Arms", "camera_hip": "eye = head bone x (0, -0.131, 1.687) rest", "camera_ads": "IV-7 socket_ads (D11)",
                         "fov_tested_deg": 80},
    }


def stage_export(a=None):
    t0 = time.time()
    bpy.ops.wm.open_mainfile(filepath=BLEND)
    os.makedirs(SCRATCH_EXPORT, exist_ok=True)
    os.makedirs(os.path.join(GLB_DIR, "Soldier"), exist_ok=True)
    rep = {"files": {}, "reimport": {}}
    for team in TEAMS:
        apply_team_export(team)
        tmp = os.path.join(SCRATCH_EXPORT, f"soldier_export_{team}.blend")
        bpy.ops.wm.save_as_mainfile(filepath=tmp, copy=True)
        jobs = [(os.path.join(GLB_DIR, f"Soldier_{team}.glb"), ["SK_Soldier_LOD0"]),
                (os.path.join(GLB_DIR, f"FP_Arms_{team}.glb"), ["FP_Arms"])]
        for li in (0, 1, 2):
            jobs.append((os.path.join(GLB_DIR, "Soldier", f"Soldier_{team}_LOD{li}.gltf"), [f"SK_Soldier_LOD{li}"]))
        if team == "Alfa":
            jobs += [(os.path.join(FBX_DIR, "SK_Soldier.fbx"), ["SK_Soldier_LOD0"]),
                     (os.path.join(FBX_DIR, "SK_Soldier_LOD1.fbx"), ["SK_Soldier_LOD1"]),
                     (os.path.join(FBX_DIR, "SK_Soldier_LOD2.fbx"), ["SK_Soldier_LOD2"]),
                     (os.path.join(FBX_DIR, "FP_Arms.fbx"), ["FP_Arms"])]
        for path, objs in jobs:
            if path.endswith(".fbx"):
                r = ivlib.export_fbx(tmp, [ARM] + objs, path)
            else:
                r = ivlib.export_glb(tmp, [ARM] + objs, path, texture_dir="textures")
            rep["files"][rel(path)] = r.get("bytes")
            log("exported", rel(path), r.get("bytes"))
        os.remove(tmp)
    # re-import checks (clean Blender processes)
    checks = [os.path.join(FBX_DIR, f) for f in ("SK_Soldier.fbx", "SK_Soldier_LOD1.fbx", "SK_Soldier_LOD2.fbx", "FP_Arms.fbx")]
    checks += [os.path.join(GLB_DIR, f"Soldier_{t}.glb") for t in TEAMS] + [os.path.join(GLB_DIR, "FP_Arms_Alfa.glb"),
                                                                             os.path.join(GLB_DIR, "Soldier", "Soldier_Bravo_LOD2.gltf")]
    for pth in checks:
        r = C.reimport_skinned_check(pth)
        m = list(r.get("meshes", {}).values())
        rep["reimport"][rel(pth)] = {
            "bones": r.get("bone_count"), "dimensions_m": r.get("dimensions_m"),
            "meshes": {k: {kk: v[kk] for kk in ("vertices", "tris", "unweighted_vertices", "max_influences", "weight_sum_min",
                                                 "weight_sum_max", "uv_layers") if kk in v} | {"shape_keys": len(v.get("shape_keys", []))}
                       for k, v in r.get("meshes", {}).items()},
            "ok": bool(r.get("bone_count") == 57 and all(x.get("unweighted_vertices", 1) == 0 and x.get("max_influences", 9) <= 4 for x in m))}
    rep["gltf_base_color_factors"] = {t: gltf_factor_check(os.path.join(GLB_DIR, f"Soldier_{t}.glb")) for t in TEAMS}
    rt = runtime_json()
    for d in (FBX_DIR, GLB_DIR):
        json.dump(rt, open(os.path.join(d, "Soldier.runtime.json"), "w"), indent=1)
    rep["seconds"] = round(time.time() - t0, 1)
    json.dump(rep, open(os.path.join(PREV, "Soldier_export_report.json"), "w"), indent=1)
    log("export", json.dumps({k: v["ok"] for k, v in rep["reimport"].items()}))
    return rep


STAGE_FUNCS_BUILD = stage_build


def quick_preview(tag="garments", textured=False, team=None):
    """Clay (or textured) preview of whatever is in the scene (dev aid)."""
    arm = bpy.data.objects[ARM]
    if textured:
        if team:
            apply_team(team)
        ivlib.clear_lights_cameras()
        sc = bpy.context.scene
        ivlib.setup_cycles(sc, samples=16, threads=4)
        sc.view_settings.view_transform = 'AgX'
        C.neutral_lighting((0, 0, 0.95), 1.9, key=0.9, world_strength=0.6)
        bpy.data.objects[BODY].hide_render = True
        return _preview_shots(tag)
    ivlib.clear_lights_cameras()
    sc = bpy.context.scene
    ivlib.setup_cycles(sc, samples=12, threads=4)
    sc.view_settings.view_transform = 'AgX'
    C.neutral_lighting((0, 0, 0.95), 1.9, key=0.6, world_strength=0.5)
    colors = {"Shirt": (0.30, 0.33, 0.22), "Trousers": (0.28, 0.30, 0.20), "Balaclava": (0.12, 0.12, 0.10),
              "FaceSkin": (0.55, 0.42, 0.33), "Glove": (0.33, 0.24, 0.14), "Boots": (0.20, 0.14, 0.09),
              "Sole": (0.05, 0.05, 0.05), "Armband": (0.05, 0.25, 0.8)}
    zc = {"carrier": (0.26, 0.22, 0.14), "pouch": (0.30, 0.25, 0.16), "mag": (0.06, 0.06, 0.06), "hard": (0.04, 0.04, 0.04),
          "belt": (0.22, 0.19, 0.12), "kneepad": (0.10, 0.10, 0.09), "strap": (0.12, 0.11, 0.09), "helmet": (0.25, 0.27, 0.18),
          "rail": (0.05, 0.05, 0.05), "shroud": (0.03, 0.03, 0.03), "team": (0.05, 0.25, 0.8), "headset": (0.08, 0.09, 0.07),
          "lens": (0.01, 0.01, 0.012), "frame": (0.02, 0.02, 0.02)}
    for o in bpy.data.objects:
        if o.type != 'MESH':
            continue
        if o.name in (BODY, BODY + "_Gloved"):
            o.hide_render = True
            continue
        if "iv_zone" in o:
            c = zc.get(o["iv_zone"], (0.5, 0.5, 0.5))
            o.data.materials.clear()
            o.data.materials.append(C.clay_material("PVZ_" + o["iv_zone"], c, 0.6))
            continue
        for k, c in colors.items():
            if k in o.name:
                o.data.materials.clear()
                o.data.materials.append(C.clay_material("PV_" + k, c, 0.7))
    return _preview_shots(tag)


def _preview_shots(tag):
    os.makedirs(PREV, exist_ok=True)
    out = []
    for name, loc in (("front", (0.0, -3.0, 1.0)), ("side", (3.0, -0.2, 1.0)), ("back", (0.0, 3.0, 1.0))):
        cam = ivlib.camera("pv_" + name, loc, (0, 0, 0.92), lens=62, up=(0, 0, 1))
        p = os.path.join(PREV, f"_dev_{tag}_{name}.png")
        ivlib.render(p, cam, res=(600, 900), samples=12)
        out.append(p)
    for name, loc, tgt, lens in (("head", (0.35, -0.55, 1.75), (0, -0.05, 1.68), 70),
                                 ("torso", (0.9, -1.3, 1.45), (0, -0.05, 1.22), 50),
                                 ("feet", (0.5, -0.9, 0.35), (0.0, -0.05, 0.12), 45),
                                 ("back34", (-0.9, 1.3, 1.45), (0, 0.05, 1.2), 50)):
        cam = ivlib.camera("pvc_" + name, loc, tgt, lens=lens, up=(0, 0, 1))
        p = os.path.join(PREV, f"_dev_{tag}_{name}.png")
        ivlib.render(p, cam, res=(600, 600), samples=12)
        out.append(p)
    from PIL import Image
    ims = [Image.open(q) for q in out]
    sheet = Image.new("RGB", (1800 + 1200, 900 + 0), (30, 30, 30))
    x = 0
    for im in ims[:3]:
        sheet.paste(im, (x, 0)); x += 600
    for k, im in enumerate(ims[3:]):
        sheet.paste(im.resize((600, 600)).crop((0, 0, 600, 450)) if False else im.resize((450, 450)), (1800 + (k % 2) * 450, (k // 2) * 450))
    sheet.save(os.path.join(PREV, f"_dev_{tag}_sheet.png"))
    return out


STAGES = ["build", "uv", "textures", "lods", "fp_tex", "validate", "render", "export"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stages", default=",".join(STAGES))
    ap.add_argument("--only", default=None)
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    a = ap.parse_args(argv)
    for st in a.stages.split(","):
        st = st.strip()
        if st == "dev_build":
            stage_build()
            quick_preview("build")
        elif st == "dev_preview":
            bpy.ops.wm.open_mainfile(filepath=BLEND)
            quick_preview(a.only or "pv")
        elif st == "dev_stance":
            dev_stance(a)
        elif st.startswith("dev_tex"):
            bpy.ops.wm.open_mainfile(filepath=BLEND)
            quick_preview("tex_" + (a.only or "Alfa"), textured=True, team=a.only or "Alfa")
        elif st == "dev_garments":
            build_garments()
            quick_preview("garments")
            bpy.ops.wm.save_as_mainfile(filepath=os.path.join(PREV, "_dev.blend"))
        else:
            STAGE_FUNCS[st](a)


STAGE_FUNCS = {"build": stage_build, "uv": stage_uv, "textures": stage_textures, "validate": stage_validate, "lods": stage_lods, "fp_tex": stage_fp_tex, "render": stage_render, "export": stage_export}

if __name__ == "__main__":
    main()
