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
    bottom_z=0.985,            # shirt tail (inside the trousers, which start at ~1.03-1.05)
    cuff_from_wrist=0.052,     # sleeve end, proximal of the wrist joint along the forearm axis (glove cuff reaches 0.080)
    collar_z0=1.556, collar_tilt=0.26, collar_h=0.030,   # neck line z = z0 + tilt * (y + 0.05); stand-up collar height
    off_torso=0.0045, off_shoulder=0.0065, off_upper=0.0115, off_fore=0.0100, off_cuff=0.0088, off_collar=0.0085,
)
TROUSERS = dict(
    waist_z0=1.043, waist_tilt=0.12,   # waistband top z = z0 + tilt * y  (lower at the front)
    hem_z=0.152,                       # hem over the boot shaft
    off_waist=0.0065, off_seat=0.0095, off_thigh=0.0150, off_knee=0.0120, off_calf=0.0150, off_hem=0.0185,
)
BALACLAVA = dict(off=0.0026, below_collar=0.045, gaiter_off=0.0125, gaiter_top=1.657,
                 eye_c=(0.0, -0.128, 1.6875), eye_a=0.058, eye_b=0.019)   # eye window ellipse (x half, z half)
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

def build_shirt(arm, body, bf, col, body_bvh):
    co, dom = bf["co"], bf["dom"]
    u_fore = forearm_u(arm, co)
    y = co[:, 1]
    collar = SHIRT["collar_z0"] + SHIRT["collar_tilt"] * (y + 0.05)
    bones = {"spine_01", "spine_02", "spine_03", "clavicle_l", "clavicle_r", "neck_01", "pelvis"}
    arm_b = {f"{b}_{s}" for b in ("upperarm", "upperarm_twist_01", "lowerarm", "lowerarm_twist_01") for s in "lr"}
    ok = np.isin(dom, list(bones | arm_b))
    ok &= co[:, 2] >= SHIRT["bottom_z"] - 0.02
    ok &= ~(np.isin(dom, ["neck_01"]) & (co[:, 2] > collar + SHIRT["collar_h"] + 0.02))
    fore = np.isin(dom, [f"lowerarm_{s}" for s in "lr"] + [f"lowerarm_twist_01_{s}" for s in "lr"])

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
    keep = face_keep(body.data, ok, centre_ok)
    ob, src = S.copy_faces(body, keep, "Soldier_Shirt", col)
    c0 = co[src]
    t_up = limb_param(arm, c0, "upperarm_{s}")
    uf = u_fore[src]
    dm = dom[src]
    isarm = np.isin(dm, list(arm_b))
    d = np.full(len(src), SHIRT["off_torso"])
    up = np.isin(dm, [f"upperarm_{s}" for s in "lr"] + [f"upperarm_twist_01_{s}" for s in "lr"])
    d[up] = SHIRT["off_shoulder"] + (SHIRT["off_upper"] - SHIRT["off_shoulder"]) * np.clip(t_up[up] / 0.35, 0, 1)
    fa = np.isin(dm, [f"lowerarm_{s}" for s in "lr"] + [f"lowerarm_twist_01_{s}" for s in "lr"])
    ramp = np.clip((uf[fa] + 0.12) / (0.12 - SHIRT["cuff_from_wrist"]), 0, 1)      # 0 at 12 cm, 1 at the cuff
    d[fa] = SHIRT["off_fore"] + (SHIRT["off_cuff"] - SHIRT["off_fore"]) * ramp
    cl = np.isin(dm, ["clavicle_l", "clavicle_r"])
    d[cl] = SHIRT["off_shoulder"]
    nk = dm == "neck_01"
    d[nk] = SHIRT["off_collar"]
    offset_garment(ob, body_bvh, d)
    ob["iv_src"] = "body"
    return ob, src


def build_trousers(arm, body, bf, col, body_bvh):
    co, dom = bf["co"], bf["dom"]
    waist = TROUSERS["waist_z0"] + TROUSERS["waist_tilt"] * co[:, 1]
    legs = {f"{b}_{s}" for b in ("thigh", "calf") for s in "lr"}
    ok = np.isin(dom, list(legs | {"pelvis", "spine_01", "spine_02"}))
    ok &= co[:, 2] <= waist + 0.02
    ok &= co[:, 2] >= TROUSERS["hem_z"] - 0.02

    def centre_ok(c):
        return (c[2] <= TROUSERS["waist_z0"] + TROUSERS["waist_tilt"] * c[1]) and c[2] >= TROUSERS["hem_z"]
    keep = face_keep(body.data, ok, centre_ok)
    ob, src = S.copy_faces(body, keep, "Soldier_Trousers", col)
    c0 = co[src]
    dm = dom[src]
    t_th = limb_param(arm, c0, "thigh_{s}")
    t_cf = limb_param(arm, c0, "calf_{s}")
    d = np.full(len(src), TROUSERS["off_seat"])
    wz = TROUSERS["waist_z0"] + TROUSERS["waist_tilt"] * c0[:, 1]
    band = c0[:, 2] > wz - 0.05
    d[band] = TROUSERS["off_waist"]
    th = np.isin(dm, ["thigh_l", "thigh_r"])
    d[th] = TROUSERS["off_seat"] + (TROUSERS["off_thigh"] - TROUSERS["off_seat"]) * np.clip(t_th[th] / 0.25, 0, 1)
    # the knee: slightly closer, calf loose, hem wide (worn over the boot shaft)
    cf = np.isin(dm, ["calf_l", "calf_r"])
    kn = cf & (t_cf < 0.18)
    d[kn] = TROUSERS["off_knee"]
    lw = cf & (t_cf >= 0.18)
    d[lw] = TROUSERS["off_calf"] + (TROUSERS["off_hem"] - TROUSERS["off_calf"]) * np.clip((t_cf[lw] - 0.6) / 0.35, 0, 1)
    d[th & (t_th > 0.85)] = TROUSERS["off_knee"] + 0.002
    offset_garment(ob, body_bvh, d, iters=14)
    return ob, src


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
    offset_garment(ob, body_bvh, d, iters=70, alpha=0.5, clear_frac=0.55)
    # store the gaiter mask for the textures (per vertex attribute)
    at = ob.data.attributes.new("iv_gaiter", 'FLOAT', 'POINT')
    at.data.foreach_set("value", g.astype(np.float32))
    return ob, src, skin, ssrc


def build_garments():
    t0 = time.time()
    arm, body = open_src()
    col = ivlib.collection("Soldier_Clothing")
    bf = S.body_fields(arm, body)
    body_bvh = S.bvh(bf["co"], bf["tris"])
    rep = {}
    shirt, ssrc = build_shirt(arm, body, bf, col, body_bvh)
    trousers, tsrc = build_trousers(arm, body, bf, col, body_bvh)
    bala, bsrc, skin, ksrc = build_balaclava(arm, body, bf, col, body_bvh)
    rep["shirt_inside_trousers"] = enforce_inside(shirt, trousers, lambda c: c[:, 2] < TROUSERS["waist_z0"] + TROUSERS["waist_tilt"] * c[:, 1] - 0.004, 0.003)
    for ob in (shirt, trousers):
        rep[ob.name] = {"shape_keys": prune_shape_keys(ob)}
    for ob in (shirt, trousers, bala, skin):
        ob.parent = arm
        m = ob.modifiers.new("Armature", 'ARMATURE')
        m.object = arm
        rep.setdefault(ob.name, {})
        rep[ob.name].update(vertices=len(ob.data.vertices), tris=len(S.tris_of(ob.data)))
    rep["seconds"] = round(time.time() - t0, 1)
    log(json.dumps(rep))
    return arm, body, col, rep


# =============================================================================
# stage: build -- boots, gloves, gear
# =============================================================================

import soldier_gear as G     # noqa: E402

CARRIER = dict(front_w=0.268, front_h=0.340, front_top=1.458, back_w=0.268, back_h=0.355, back_top=1.488,
               bag_t=0.034, R=0.46, cut=0.040, cut_depth=0.075, tilt_front=2.0, tilt_back=3.0, clear=0.004,
               cb_z=(1.135, 1.300), cb_clear=0.0015, cb_thick=0.009,
               strap_x=0.100, strap_w=0.062, strap_clear=0.002, strap_thick=0.011)
HELMET = dict(c=(0.0, -0.051, 1.700), ax=0.1175, ay_f=0.1400, ay_b=0.1335, az=0.1330, p=2.3, shell=0.009,
              rim=((0, 1.738), (35, 1.733), (62, 1.716), (90, 1.711), (118, 1.712), (145, 1.692), (180, 1.680)))
BOOT = dict(top_z=0.205, off=0.0058, sole_z=0.030, sole_margin=0.006)
BELT = dict(z=(0.998, 1.046), clear=0.0015, thick=0.010)
KNEE = dict(clear=0.003, thick=0.013, z=(-0.075, 0.065), az=65.0)


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
        V, F = G.slab_from_grid(Pp, Nn, P["cb_clear"], P["cb_thick"])
        B.add(f"PC_Cummerbund_{s.upper()}", V, F, ("fabric", "Soldier_Shirt", ["spine_01", "spine_02", "spine_03"]),
              zone="carrier", rigid_ends=("spine_03", 0.035, "u"), grid=(len(az), len(zc)))
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
        V, F = G.slab_from_grid(Pp, Nn, P["strap_clear"], P["strap_thick"])
        B.add(f"PC_Strap_{s.upper()}", V, F, ("fabric", "Soldier_Shirt", ["spine_03", f"clavicle_{s}", "neck_01"]),
              zone="carrier", rigid_ends=("spine_03", 0.05, "u"), grid=(len(phis), 3))
    # --- placard (triple magazine pouch) on the lower front bag + three IV-7 magazines
    o, ex, ey, ez = fr_f
    ymin = Vf[:, 1].min()
    pw, ph_, pd = 0.236, 0.130, 0.068
    Vp, Fp = G.bent_box(pw, ph_, pd, P["R"] + 0.04, bevel=0.010, nx=5, nz=3)
    zb = P["front_top"] - P["front_h"] + 0.012
    Mp = G.frame_matrix(np.array([0.0, 0, zb + ph_ / 2]), ex, ey, ez)
    Vp = G.xf(Vp, Mp)
    # rest it on the bag's outer face (0.5 mm overlap)
    Vp[:, 1] += (ymin + 0.0005) - Vp[:, 1].max() + (Vp[:, 1].max() - Vp[:, 1].max())
    front_face_y = ymin
    shift = front_face_y + 0.001 - Vp[:, 1].max()
    Vp[:, 1] += shift
    B.add("PC_Placard", Vp, Fp, ("rigid", "spine_03"), zone="pouch")
    info["placard_front_y"] = float(Vp[:, 1].min())
    info["placard_top_z"] = float(Vp[:, 2].max())
    # admin pouch (upper front, flat)
    Va, Fa = G.bent_box(0.150, 0.095, 0.026, P["R"], bevel=0.008, nx=4, nz=2)
    Ma = G.frame_matrix(np.array([0.018, 0, P["front_top"] - 0.075]), ex, ey, ez)
    Va = G.xf(Va, Ma)
    Va[:, 1] += (ymin + 0.001) - Va[:, 1].max() + 0.0
    # the bag's outer face is tilted: fit per vertex height by moving until it touches
    B.add("PC_AdminPouch", Va, Fa, ("rigid", "spine_03"), zone="pouch")
    # --- back: zip-on panel + horizontal pouch; radio pouch (left rear) + GP pouch (right rear)
    ob_, bx, by, bz = fr_b
    ymax = Vb[:, 1].max()
    Vz, Fz = G.bent_box(0.230, 0.285, 0.040, P["R"], bevel=0.009, nx=5, nz=4)
    Mz = G.frame_matrix(np.array([0.0, 0, P["back_top"] - 0.035 - 0.285 / 2]), bx, by, bz)
    Vz = G.xf(Vz, Mz)
    Vz[:, 1] += (ymax - 0.001) - Vz[:, 1].min()
    B.add("PC_BackPanel", Vz, Fz, ("rigid", "spine_03"), zone="pouch")
    Vh, Fh = G.rbox(0.200, 0.050, 0.085, 0.012)
    Vh = Vh + np.array([0.0, Vz[:, 1].max() + 0.025 - 0.004, P["back_top"] - 0.035 - 0.285 + 0.055])
    B.add("PC_BackPouch", Vh, Fh, ("rigid", "spine_03"), zone="pouch")
    info["back_panel_outer_y"] = float(Vz[:, 1].max())
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
        B.add(f"PC_{kind.capitalize()}Pouch", V, F, ("rigid", "spine_03"), zone="pouch")
        if kind == "radio":
            # radio body top (knobs) above the pouch + antenna
            Vr, Fr = G.rbox(0.036, 0.060, 0.030, 0.006)
            Vr = Vr @ R.T + c + np.array([0, 0, h / 2 + 0.010])
            B.add("PC_Radio", Vr, Fr, ("rigid", "spine_03"), zone="hard")
            top = c + np.array([0, 0.012, h / 2 + 0.025])
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


def build_magazines(rifle_rig, rifle_parts, B, placard_top, placard_front_y, back_y):
    """Three IV-7 magazines standing in the placard (tops above it).  Mesh: the IV-7 LOD2
    magazine + rounds, cut 1.5 cm below the placard top (the hidden part is removed)."""
    mag = next(o for o in rifle_parts if o.name.startswith("Magazine_LOD2"))
    rnd = next(o for o in rifle_parts if o.name.startswith("MagRounds_LOD2"))
    parts = []
    for o in (mag, rnd):
        co = S.co_of(o)
        M = np.array(o.matrix_world)
        co = co @ M[:3, :3].T + M[:3, 3]
        parts.append((co, [list(p.vertices) for p in o.data.polygons]))
    V, F = G.merge_parts(parts)
    # rifle frame -> world: X_r -> -Y (bullets forward), Y_r -> +X, Z_r -> +Z
    R = np.array([[0, 1, 0], [-1, 0, 0], [0, 0, 1.0]])
    V = V @ R.T
    top = V[:, 2].max()
    cx = 0.5 * (V[:, 0].min() + V[:, 0].max())
    # centre each magazine in a cell of the placard
    out = []
    for i, x in enumerate((-0.068, 0.0, 0.068)):
        W = V + np.array([x - cx, 0, placard_top + 0.040 - top])
        # depth: rear face 1.2 cm in front of the bag
        W[:, 1] += (back_y - 0.013) - W[:, 1].max()
        # cut away everything more than 1.5 cm below the placard top
        bm = bmesh.new()
        for p in W:
            bm.verts.new(tuple(map(float, p)))
        bm.verts.ensure_lookup_table()
        for f in F:
            try:
                bm.faces.new([bm.verts[k] for k in f])
            except ValueError:
                pass
        cut = placard_top - 0.015
        geom = list(bm.verts) + list(bm.edges) + list(bm.faces)
        res = bmesh.ops.bisect_plane(bm, geom=geom, plane_co=(0, 0, cut), plane_no=(0, 0, 1), clear_inner=True)
        edges = [e for e in res["geom_cut"] if isinstance(e, bmesh.types.BMEdge)]
        if edges:
            bmesh.ops.holes_fill(bm, edges=edges, sides=0)
        bmesh.ops.triangulate(bm, faces=list(bm.faces))
        bmesh.ops.dissolve_limit(bm, angle_limit=math.radians(8), verts=list(bm.verts), edges=list(bm.edges))
        bmesh.ops.triangulate(bm, faces=list(bm.faces))
        Vm = np.array([v.co[:] for v in bm.verts])
        Fm = [[v.index for v in f.verts] for f in bm.faces]
        bm.free()
        B.add(f"PC_Mag_{i + 1}", Vm, Fm, ("rigid", "spine_03"), zone="mag")
        # bungee retention cord over the top (thin rounded bar)
        Vb_, Fb_ = G.rbox(0.004, 0.058, 0.004, 0.0018, 1)
        Vb_ = Vb_ + np.array([x, 0.5 * (W[:, 1].min() + W[:, 1].max()), W[:, 2].max() + 0.0022])
        B.add(f"PC_Bungee_{i + 1}", Vb_, Fb_, ("rigid", "spine_03"), zone="hard")
        out.append({"x": x, "top_z": float(W[:, 2].max())})
    return out


def build_belt(arm, trousers, B):
    bv, tco = garment_bvh(trousers)
    az = np.radians(np.linspace(0, 360, 28, endpoint=False))
    cen = np.array([0.0, -0.030])
    O = np.zeros((len(az), 3, 3)); D = np.zeros_like(O)
    for i, a in enumerate(az):
        dxy = np.array([math.sin(a), -math.cos(a)])
        # belt top 6 mm under the waistband top (the waist line is lower at the front)
        yw = cen[1] + dxy[1] * 0.12
        ztop = TROUSERS["waist_z0"] + TROUSERS["waist_tilt"] * yw - 0.006
        for j, z in enumerate(np.linspace(ztop - (BELT["z"][1] - BELT["z"][0]), ztop, 3)):
            O[i, j] = [cen[0] + dxy[0] * 0.45, cen[1] + dxy[1] * 0.45, z]
            D[i, j] = [-dxy[0], -dxy[1], 0]
    Pp, Nn = G.surface_grid(bv, O, D, back=0.0)
    Pp = G.smooth_grid(Pp, 1, closed_u=True)
    Nn = G.smooth_grid(Nn, 2, closed_u=True)
    Nn[..., 2] *= 0.3
    Nn /= np.linalg.norm(Nn, axis=-1, keepdims=True)
    V, F = G.slab_from_grid(Pp, Nn, BELT["clear"], BELT["thick"], closed_u=True, round_edge=0.25)
    B.add("Belt", V, F, ("fabric", "Soldier_Trousers", ["pelvis", "spine_01"]), zone="belt")
    ring_out = Pp + Nn * (BELT["clear"] + BELT["thick"])
    front = ring_out[0, 1]
    # buckle
    Vk, Fk = G.rbox(0.058, 0.014, 0.040, 0.004)
    Vk = Vk + front + np.array([0, -0.006, 0])
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
        B.add(name, Vp, Fp, ("rigid", "pelvis"), zone="pouch")
        pouch.append(name)
    return {"pouches": pouch}


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
        B.add(f"KneePad_{s.upper()}", V, F, ("rigid", f"calf_{s}"), zone="kneepad")
        # strap below the pad around the back of the leg
        azb = np.radians(np.linspace(58, 302, 13))
        hb = np.array([-0.062, -0.050, -0.038])
        O = np.zeros((len(azb), len(hb), 3)); D = np.zeros_like(O)
        for i, a in enumerate(azb):
            dirv = fwd * math.cos(a) + side * math.sin(a)
            for j, hh in enumerate(hb):
                c = k0 - ax * hh
                O[i, j] = c + dirv * 0.13
                D[i, j] = -dirv
        Pp, Nn = G.surface_grid(bv, O, D, back=0.0)
        Nn = G.smooth_grid(Nn, 2)
        Nn /= np.linalg.norm(Nn, axis=-1, keepdims=True)
        V, F = G.slab_from_grid(Pp, Nn, 0.001, 0.0032, round_edge=0.2)
        B.add(f"KneeStrap_{s.upper()}", V, F, ("rigid", f"calf_{s}"), zone="strap")
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
    azs = np.linspace(0, 360, 32, endpoint=False)
    Pp = np.zeros((32, 2, 3)); Nn = np.zeros_like(Pp)
    for i, a in enumerate(azs):
        for j, z in enumerate((1.776, 1.812)):
            p, n = on_shell(a, z)
            Pp[i, j], Nn[i, j] = p, n
    V_, F_ = G.slab_from_grid(Pp, Nn, 0.0016, 0.0028, closed_u=True, round_edge=0.2)
    B.add("Helmet_Band", V_, F_, ("rigid", "head"), zone="team", atlas="team")
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
    start = np.array([cupL[:, 0].min() + 0.012, cupL[:, 1].min() + 0.012, 1.640])
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


def build_armbands(arm, shirt, col):
    """Team armbands: the sleeve faces between 42 and 66 % down each upper arm, raised 2.2 mm with a
    rolled edge, weighted exactly like the sleeve under them."""
    co = S.co_of(shirt)
    names = S.bone_names(arm)
    W = S.read_W(shirt, names)
    t = limb_param(arm, co, "upperarm_{s}")
    dom = np.array(names)[W.argmax(1)]
    up = np.isin(dom, [f"upperarm_{s}" for s in "lr"] + [f"upperarm_twist_01_{s}" for s in "lr"])
    ok = up & (t > 0.36) & (t < 0.74)
    keep = face_keep(shirt.data, ok, lambda c: 0.42 < limb_param(arm, c[None], "upperarm_{s}")[0] < 0.66)
    ob, src = S.copy_faces(shirt, keep, "Soldier_Armbands", col)
    if ob.data.shape_keys is not None:
        ob.shape_key_clear()
    c = S.co_of(ob)
    N = S.vnormals(c, S.tris_of(ob.data))
    S.set_co(ob, c + N * 0.0022)
    # rolled edges (thickness) at both boundary rings of each band
    for loop in S.boundary_loops(ob.data):
        add_lip_normal(ob, loop, edge=0.0022, depth=0.003)
    return ob


def add_lip_normal(ob, loop, edge, depth, lining=None):
    """add_lip with the inward direction = minus the vertex normal at the boundary; the lining
    continues along `lining(p)` (default: also inwards)."""
    cc = S.co_of(ob)
    nn = S.vnormals(cc, S.tris_of(ob.data))
    L = np.array(loop)

    def inward(p):
        return -nn[L[int(np.argmin(np.linalg.norm(cc[L] - p, axis=1)))]]
    return S.add_lip(ob, loop, inward, edge=edge, depth=depth, lining_dir_fn=lining or inward)


def build_gear_objects(arm, B, col, garments):
    """Turn the Built parts into bound objects."""
    names = S.bone_names(arm)
    objs = {}
    for name, p in B.parts.items():
        ob = S.make_mesh("SG_" + name, p["V"], p["F"], col)
        n = len(p["V"])
        kind = p["bind"][0]
        if kind == "rigid":
            W = S.rigid_W(n, names, p["bind"][1])
        else:
            g = garments[p["bind"][1]]
            gco, gtr = S.co_of(g), S.tris_of(g.data)
            Wg = S.read_W(g, names)
            W = S.transfer_weights(gco, gtr, Wg, p["V"], k=4)
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
    gcol = ivlib.collection("Soldier_Gear")
    B = G.Built()
    rep["carrier"], front_bag, back_bag = build_carrier(arm, shirt, B)
    rep["side_pouches"] = build_side_pouches(arm, shirt, B, back_bag)
    rig, rparts = HN.append_weapon(RIFLE_BLEND, col_name="IV7_LOD2", rig_name="SK_IV7")
    bpy.context.view_layer.update()
    rep["magazines"] = build_magazines(rig, rparts, B, rep["carrier"]["placard_top_z"], None,
                                       rep["carrier"]["front_outer_y"])
    wcol = bpy.data.collections["IV7_LOD2"]
    for o in list(wcol.objects):
        bpy.data.objects.remove(o)
    bpy.data.collections.remove(wcol)
    rep["belt"] = build_belt(arm, trousers, B)
    rep["knee"] = build_knee_pads(arm, trousers, B)
    rep["helmet"] = build_helmet(arm, bala, skin, B)
    build_glasses(bala, skin, B)
    garments = {"Soldier_Shirt": shirt, "Soldier_Trousers": trousers}
    gear = build_gear_objects(arm, B, gcol, garments)
    arms_ = build_armbands(arm, shirt, col)
    arms_.parent = arm
    arms_.modifiers.new("Armature", 'ARMATURE').object = arm
    # hidden balaclava under the helmet / cups, then game resolution for head pieces
    rep["balaclava_hidden_faces"] = hide_under_helmet(bala, arm, [B.parts["Headset_Cup_L"]["V"], B.parts["Headset_Cup_R"]["V"]])
    rep["balaclava_tris"] = decimate_to(bala, 1500, names, (bf["co"], bf["tris"], bf["W"]), arm)
    rep["skin_tris"] = decimate_to(skin, 260, names, (bf["co"], bf["tris"], bf["W"]), arm)
    rep["lips"] = garment_lips(arm, shirt, trousers, bala)
    # the source body / gloves are not part of the soldier (the body is kept hidden as the
    # closed volume proxy for the intersection checks)
    body.hide_render = True
    body.hide_viewport = True
    for n in (BODY + "_Gloved", GLOVES["l"], GLOVES["r"]):
        if n in bpy.data.objects:
            bpy.data.objects.remove(bpy.data.objects[n])
    rep["build_seconds"] = round(time.time() - t0, 1)
    log("build", json.dumps(rep))
    ivlib.deselect_all()
    bpy.ops.wm.save_as_mainfile(filepath=BLEND, compress=True)
    return rep


# =============================================================================
# UV atlases
# =============================================================================

GLOVE_UV_RECT = (0.75, 0.0, 0.25)          # (u0, v0, size): the glove UV square inside the clothing atlas
CLOTH_DENSITY = {"Soldier_Shirt": 1.0, "Soldier_Trousers": 1.0, "Soldier_Balaclava": 1.3,
                 "Soldier_FaceSkin": 0.6, "SG_Helmet": 1.25}


def atlas_members():
    obs = [o for o in bpy.data.objects if o.type == 'MESH' and o.name != BODY]
    cloth = [bpy.data.objects[n] for n in CLOTH_DENSITY if n in bpy.data.objects]
    gloves = [o for o in obs if o.name.startswith("Soldier_Glove_")]
    team = [o for o in obs if o.name in ("Soldier_Armbands", "SG_Helmet_Band")]
    gear = [o for o in obs if o not in cloth and o not in gloves and o not in team]
    return cloth, gloves, team, gear


def uv_cloth(cloth, gloves, report):
    for o in cloth:
        me = o.data
        while len(me.uv_layers):
            me.uv_layers.remove(me.uv_layers[0])
        me.uv_layers.new(name="UVMap")
    ivlib.select(cloth, cloth[0])
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.uv.smart_project(angle_limit=math.radians(62), island_margin=0.003, area_weight=0.0,
                             correct_aspect=True, scale_to_bounds=False)
    bpy.ops.uv.select_all(action='SELECT')
    bpy.ops.uv.average_islands_scale()
    bpy.ops.object.mode_set(mode='OBJECT')
    for o in cloth:
        ivlib.uv_scale_islands(o, lambda ob, info: CLOTH_DENSITY.get(ob.name, 1.0))
    u0, v0, sz = GLOVE_UV_RECT
    for g in gloves:
        uv = S.uv_array(g.data)
        g.data.uv_layers["UVMap"].data.foreach_set("uv", (np.column_stack([u0 + uv[:, 0] * sz, v0 + uv[:, 1] * sz])).ravel())
    allo = cloth + gloves
    ivlib.select(allo, cloth[0])
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    for g in gloves:
        bm = bmesh.from_edit_mesh(g.data)
        ul = bm.loops.layers.uv.active
        for f in bm.faces:
            for l in f.loops:
                l[ul].pin_uv = True
        bmesh.update_edit_mesh(g.data)
    bpy.ops.uv.select_all(action='SELECT')
    bpy.ops.uv.pack_islands(rotate=True, rotate_method='ANY', margin=0.004, margin_method='FRACTION',
                            shape_method='CONCAVE', scale=True, pin=True, pin_method='LOCKED')
    bpy.ops.object.mode_set(mode='OBJECT')
    r = ivlib.uv_island_raster(cloth, 2048)
    report["cloth"] = {"coverage_without_gloves": round(r["coverage"], 4), "overlap_px": int(r["overlap_px"]),
                       "islands": len(r["islands"]),
                       "px_per_cm": {o.name: round(ivlib.texel_density(o, 2048), 2) for o in cloth}}


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
    for o in gear:
        o["iv_atlas"] = "gear"
    for o in team:
        o["iv_atlas"] = "team"
    log("uv", json.dumps(rep))
    bpy.ops.wm.save_as_mainfile(filepath=BLEND, compress=True)
    json.dump(rep, open(os.path.join(PREV, "_uv_report.json"), "w"), indent=1)
    return rep


STAGE_FUNCS_BUILD = stage_build


def quick_preview(tag="garments"):
    """Clay preview of whatever is in the scene (dev aid)."""
    arm = bpy.data.objects[ARM]
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


STAGES = ["build", "textures", "lods", "validate", "render", "export"]


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
        elif st == "dev_garments":
            build_garments()
            quick_preview("garments")
            bpy.ops.wm.save_as_mainfile(filepath=os.path.join(PREV, "_dev.blend"))
        else:
            STAGE_FUNCS[st](a)


STAGE_FUNCS = {"build": stage_build, "uv": stage_uv}

if __name__ == "__main__":
    main()
