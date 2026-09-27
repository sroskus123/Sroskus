"""
soldier_tex.py -- per-texel materials of the soldier (clothing camo + fabric, gear nylon / hard
parts, team bands).  Everything is evaluated in numpy on the REST positions of the texels
(ivsoldier.atlas_texels), so patterns are continuous across UV seams and identical at any texture
resolution (the first-person arms re-evaluate the same functions at a higher density).

Height maps are metres (converted to OpenGL tangent-space normals by ivhands.height_to_normal);
colours are linear; the gear fabric is authored NEUTRAL (tinted by the material's base colour
factor per team).
"""

import math

import numpy as np

import ivhands as HN

wave_noise = HN.wave_noise


def srgb(h):
    h = h.lstrip("#")
    c = np.array([int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)])
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def sm(a, b, x):
    t = np.clip((x - a) / (b - a), 0.0, 1.0)
    return (t * t * (3 - 2 * t)).astype(np.float32)


def line(d, half, texel):
    """Anti-aliased line profile (1 on the line, 0 beyond half); fades out when the line is
    thinner than ~0.7 texel instead of aliasing."""
    h = np.maximum(half, 0.35 * texel)
    amp = np.clip(half / (0.35 * texel), 0.0, 1.0)
    return (sm(h, 0.0, np.abs(d)) * amp).astype(np.float32)


def stitches(d, along, half, pitch, texel, duty=0.55):
    ph = (along / pitch) % 1.0
    dash = sm(0.0, 0.12, ph) * sm(duty + 0.12, duty, ph)
    fade = np.clip(pitch / (3.0 * texel) - 0.5, 0.0, 1.0)      # dashes disappear when unresolvable
    return line(d, half, texel) * (dash * fade + (1 - fade) * duty * 0.6)


def fold_wave(x, sharp=1.6):
    """Cloth fold profile over a unit period: broad valleys, sharper crests, in [-0.5, 0.5]."""
    s = np.sin(2 * np.pi * x)
    return (np.sign(s) * np.abs(s) ** (1.0 / sharp) * 0.5).astype(np.float32)


# =============================================================================
# palettes
# =============================================================================

CAMO = {
    # base, c1 (mid dark), c2 (darkest), c3 (light), torso jersey, gear tint
    "Alfa": dict(base="#4d5337", c1="#3a3627", c2="#23271c", c3="#6a6a49", torso="#474c37", gear="#4b503c",
                 name="woodland-olive"),
    "Bravo": dict(base="#a28d69", c1="#7f684a", c2="#5e4b35", c3="#bcae8a", torso="#978462", gear="#86704f",
                  name="coyote / tan"),
    "Charlie": dict(base="#737870", c1="#555b52", c2="#3d423b", c3="#9c9f96", torso="#6c7067", gear="#666862",
                    name="grey-green"),
}
NEUTRAL = dict(balaclava="#2c2d27", gaiter="#57544a", skin="#8d6650", boot="#5a4430", boot_toe="#33291f",
               sole="#1d1d1d", lace="#2e2a24")
GEAR_WHITE = 0.62          # linear value of the neutral gear fabric (tint = colour / GEAR_WHITE)


def camo_layers(P, seed=3):
    """Printed camo: three soft-edged layers (c1, c2, c3) over the base, from warped 3D noise.
    Returns weights (m, 4) for base, c1, c2, c3 summing to 1."""
    w = wave_noise(P, 0.30, 2, seed + 11, 6)[:, None] * 0.035
    Q = P + w * np.array([1.0, -0.7, 0.4])[None, :]
    n1 = wave_noise(Q, 0.13, 3, seed + 1, 7)
    n2 = wave_noise(Q + 1.7, 0.09, 3, seed + 2, 7)
    n3 = wave_noise(Q - 2.3, 0.11, 3, seed + 3, 7)
    e = 0.018
    a1 = sm(0.12 - e, 0.12 + e, n1)
    a2 = sm(0.30 - e, 0.30 + e, n2) * sm(-0.1, 0.1, n1)          # darkest blobs inside / next to c1
    a3 = sm(0.20 - e, 0.20 + e, n3) * (1 - a1)
    wb = np.clip(1 - a1 - a3, 0, 1)
    w1 = a1 * (1 - a2)
    w2 = a1 * a2
    W = np.stack([wb, w1, w2, a3], 1)
    return W / np.maximum(W.sum(1, keepdims=True), 1e-6)


def camo_color(W, team):
    c = CAMO[team]
    cols = np.stack([srgb(c["base"]), srgb(c["c1"]), srgb(c["c2"]), srgb(c["c3"])])
    return W @ cols


# =============================================================================
# geometry frames (rest pose) from the armature
# =============================================================================

class Frames:
    def __init__(self, arm):
        self.b = {}
        for bn in arm.data.bones:
            self.b[bn.name] = (np.array(bn.head_local), np.array(bn.tail_local))

    def seg(self, P, bone_fmt, side_mask_pos):
        """t along the bone (0 head, 1 tail), radial distance, unit radial vector, side sign
        chosen by x (left = +x)."""
        t = np.zeros(len(P), np.float32)
        rv = np.zeros_like(P)
        for s, sg in (("l", 1), ("r", -1)):
            h, tl = self.b[bone_fmt.format(s=s)]
            ax = tl - h
            L2 = ax @ ax
            m = (P[:, 0] * sg > 0) if side_mask_pos else np.ones(len(P), bool)
            d = P[m] - h
            tt = d @ ax / L2
            t[m] = tt
            rv[m] = d - np.outer(tt, ax)
        r = np.linalg.norm(rv, axis=1)
        return t, r, rv / np.maximum(r[:, None], 1e-9)

    def axis(self, bone):
        h, t = self.b[bone]
        a = t - h
        return a / np.linalg.norm(a)


def angle_about(rv, P, ref_l, ref_r):
    """Signed angle (rad) of the radial vector around a limb relative to a reference direction
    (per side, left for x > 0)."""
    ang = np.zeros(len(P), np.float32)
    for sg, ref in ((1, ref_l), (-1, ref_r)):
        m = P[:, 0] * sg > 0
        ang[m] = np.arctan2((np.cross(ref[0], rv[m]) * ref[1]).sum(1), rv[m] @ ref[0])
    return ang


# =============================================================================
# clothing
# =============================================================================

def cloth_maps(td, objnames, fr, shirt_cfg, trouser_cfg, seed=5):
    """Returns dict with 'camoW' (m,4), 'zone' labels, 'base_fn'(team) -> base colour, 'rough',
    'metal', 'height', 'cavity'."""
    P, N = td["P"].astype(np.float64), td["N"]
    m = len(P)
    tex = np.linalg.norm(td["dPdu"], axis=1).astype(np.float32)        # metres per texel
    oid = td["oid"]
    obj = np.array(objnames)[oid]
    is_shirt = obj == "Soldier_Shirt"
    is_tr = obj == "Soldier_Trousers"
    is_bala = obj == "Soldier_Balaclava"
    is_skin = obj == "Soldier_FaceSkin"
    is_helm = obj == "SG_Helmet"
    h = np.zeros(m, np.float32)
    cav = np.ones(m, np.float32)
    rough = np.full(m, 0.86, np.float32)
    seam_dark = np.zeros(m, np.float32)
    thread = np.zeros(m, np.float32)
    solid = np.zeros(m, np.float32)          # 1 = torso jersey (solid colour), 0 = camo print
    reinf = np.zeros(m, np.float32)          # double-layer panels (slightly darker)
    loop_patch = np.zeros(m, np.float32)
    # ---- fabric micro structure: ripstop grid (5 mm) + weave
    g = 0.005
    rip = np.maximum(line((P[:, 0] + P[:, 1] * 0.3) % g - g / 2, 0.00025, tex), line(P[:, 2] % g - g / 2, 0.00025, tex))
    weave = wave_noise(P, 0.0016, 2, seed + 1, 6)
    wr = wave_noise(P, 0.07, 3, seed + 2, 6)            # large soft wrinkles
    # ---------------- shirt
    if is_shirt.any():
        S_ = is_shirt
        t_up, r_up, rv_up = fr.seg(P, "upperarm_{s}", True)
        t_lo, r_lo, rv_lo = fr.seg(P, "lowerarm_{s}", True)
        # sleeve / torso split along a raglan plane from the collar to the armpit
        sgx = np.sign(P[:, 0])
        rag = (np.abs(P[:, 0]) - 0.080) * 0.19 + (1.520 - P[:, 2]) * 0.08
        rag = rag / math.hypot(0.19, 0.08)
        sleeve = S_ & (rag > 0) & (P[:, 2] > 1.10)
        torso = S_ & ~sleeve
        # collar (camo) above the neck line
        neck = shirt_cfg["collar_z0"] + shirt_cfg["collar_tilt"] * (P[:, 1] + 0.05)
        collar = S_ & (P[:, 2] > neck - 0.004) & (np.abs(P[:, 0]) < 0.13)
        solid[torso & ~collar] = 1.0
        # seams: raglan, collar, side seams of the torso, sleeve inseam (underside of the arm)
        d_rag = np.where(S_ & (P[:, 2] > 1.10), rag, 1.0)
        seam = line(d_rag, 0.0008, tex)
        thread = np.maximum(thread, stitches(d_rag - 0.004 * np.sign(d_rag + 1e-9), P[:, 2] + P[:, 1], 0.0003, 0.003, tex))
        d_col = np.where(S_ & (np.abs(P[:, 0]) < 0.11), P[:, 2] - neck + 0.004, 1.0)
        seam = np.maximum(seam, line(d_col, 0.0008, tex))
        side = np.where(torso, np.abs(P[:, 0]) - 0.0, 9.0)
        # sleeve inseam: the arm's underside (towards the body / down in the A-pose)
        down = np.array([0, 0, -1.0])
        ang_u = np.zeros(m, np.float32)
        for bn, (t_, rv_) in (("upperarm", (t_up, rv_up)), ("lowerarm", (t_lo, rv_lo))):
            sel = sleeve & (t_ > -0.1) & (t_ < 1.05)
            if bn == "lowerarm":
                sel = S_ & (t_lo > 0.0)
            for sg in (1, -1):
                ax = fr.axis(f"{bn}_{'l' if sg > 0 else 'r'}")
                ref = down - ax * (down @ ax)
                ref /= np.linalg.norm(ref)
                mm = sel & (sgx == sg)
                ang_u[mm] = np.arccos(np.clip((rv_[mm] @ ref), -1, 1))
        rr = np.where(t_lo > 0.0, r_lo, r_up)
        d_in = np.where(sleeve | (S_ & (t_lo > 0)), ang_u * rr, 9.0)
        seam = np.maximum(seam, line(d_in, 0.0008, tex))
        thread = np.maximum(thread, stitches(np.abs(d_in) - 0.004, np.where(t_lo > 0, t_lo, t_up) * 0.3, 0.0003, 0.003, tex) * (d_in < 1))
        # cuff band (last 5.5 cm) with a hook-and-loop tab
        fore_len = 0.253
        u_cuff = (1.0 - t_lo) * fore_len          # metres from the wrist joint
        cuff = S_ & (t_lo > 0.0) & (u_cuff < shirt_cfg["cuff_from_wrist"] + 0.045)
        d_cuff = np.where(S_ & (t_lo > 0.5), u_cuff - (shirt_cfg["cuff_from_wrist"] + 0.045), 9.0)
        seam = np.maximum(seam, line(d_cuff, 0.0009, tex))
        thread = np.maximum(thread, stitches(d_cuff + 0.003, ang_u * r_lo, 0.0003, 0.003, tex) * (S_ & (t_lo > 0.5)))
        reinf = np.maximum(reinf, cuff * 0.6)
        # elbow patch (posterior elbow, double layer)
        back = np.array([0, 1.0, 0])
        post = np.zeros(m, np.float32)
        for sg in (1, -1):
            s = 'l' if sg > 0 else 'r'
            e0 = fr.b[f"lowerarm_{s}"][0]
            ax = fr.axis(f"lowerarm_{s}") + fr.axis(f"upperarm_{s}")
            ax /= np.linalg.norm(ax)
            ref = back - ax * (back @ ax)
            ref /= np.linalg.norm(ref)
            mm = S_ & (sgx == sg)
            d = P[mm] - e0
            along = d @ ax
            rad = d - np.outer(along, ax)
            rn = np.linalg.norm(rad, axis=1)
            ca = (rad @ ref) / np.maximum(rn, 1e-9)
            ell = (along / 0.085) ** 2 + ((1 - ca) / 0.55) ** 2
            post[mm] = ell
        elbow = S_ & (post < 1.0)
        reinf = np.maximum(reinf, elbow.astype(np.float32))
        seam = np.maximum(seam, line(np.where(S_, post - 1.0, 9.0) * 0.03, 0.0008, tex))
        thread = np.maximum(thread, stitches(np.where(S_, post - 1.0, 9.0) * 0.03 + 0.003, P[:, 2] + P[:, 0], 0.0003, 0.003, tex))
        # upper-arm pocket with a loop patch (lateral side, t 0.10-0.38)
        lat = np.zeros(m, np.float32)
        for sg in (1, -1):
            s = 'l' if sg > 0 else 'r'
            ax = fr.axis(f"upperarm_{s}")
            out = np.array([sg, -0.25, 0.3])
            ref = out - ax * (out @ ax)
            ref /= np.linalg.norm(ref)
            mm = S_ & (sgx == sg)
            lat[mm] = np.arccos(np.clip(rv_up[mm] @ ref, -1, 1)) * r_up[mm]
        pk = S_ & sleeve & (t_up > 0.10) & (t_up < 0.38) & (lat < 0.052)
        d_pk = np.where(S_ & sleeve, np.maximum(np.maximum(0.10 - t_up, t_up - 0.38) * 0.30, lat - 0.052), 9.0)
        seam = np.maximum(seam, line(d_pk, 0.0009, tex))
        thread = np.maximum(thread, stitches(d_pk + 0.003, t_up * 0.3 + lat, 0.0003, 0.003, tex) * (d_pk < 0.02))
        flap = pk & (t_up < 0.17)
        h[flap] += 0.0006
        lpz = pk & (t_up > 0.19) & (t_up < 0.33) & (lat < 0.038)
        loop_patch = np.maximum(loop_patch, lpz.astype(np.float32))
        h[pk] += 0.0010
        # folds: elbow rings (stronger on the inner side), cuff bunching, armpit diagonals, waist
        inner = np.zeros(m, np.float32)
        for sg in (1, -1):
            s = 'l' if sg > 0 else 'r'
            ax = fr.axis(f"lowerarm_{s}")
            ref = -np.array([0, 1.0, 0]) - ax * (-ax[1])
            ref /= np.linalg.norm(ref)
            mm = S_ & (sgx == sg)
            inner[mm] = 0.5 + 0.5 * (np.where((t_lo[mm] > 0)[:, None], rv_lo[mm], rv_up[mm]) @ ref)
        el = np.where(t_lo > 0, t_lo * 0.253, (t_up - 1.0) * 0.298)       # metres from the elbow (+ distal)
        warp = wave_noise(P, 0.05, 2, seed + 7, 6) * 0.35
        ring = fold_wave(el / 0.028 + warp) * sm(0.13, 0.03, np.abs(el)) * (0.35 + 0.65 * inner)
        h[S_ & (sleeve | (t_lo > 0))] += (ring * 0.0026)[S_ & (sleeve | (t_lo > 0))]
        cb = S_ & (t_lo > 0.4)
        bunch = fold_wave(u_cuff / 0.021 + warp * 1.4) * sm(0.19, 0.10, u_cuff) * sm(0.05, 0.10, u_cuff)
        h[cb] += (bunch * 0.0022)[cb]
        pit = S_ & sleeve & (t_up < 0.35)
        diag = fold_wave((P[:, 2] * 0.8 + np.abs(P[:, 0]) * 0.6) / 0.03 + warp) * sm(0.35, 0.05, t_up)
        h[pit] += (diag * 0.0014 * (1 - inner * 0.3))[pit]
        wst = torso & (P[:, 2] < 1.12)
        h[wst] += (fold_wave(P[:, 2] / 0.024 + warp) * sm(1.12, 1.02, P[:, 2]) * 0.0012)[wst]
        # micro: camo sleeves ripstop, torso jersey knit (finer, no grid)
        knit = np.abs(np.sin(P[:, 2] * 2 * np.pi / 0.0011 + np.sin(P[:, 0] * 900) * 0.8)).astype(np.float32)
        h[S_] += np.where(solid[S_] > 0.5, (knit[S_] - 0.5) * 0.00004, rip[S_] * 0.00006 + weave[S_] * 0.00002)
        h[S_] += (wr[S_] * 0.0006)
        rough[S_] = np.where(solid[S_] > 0.5, 0.90, 0.84)
        seam_dark = np.maximum(seam_dark, seam * S_)
        h -= seam * S_ * 0.0004
    # ---------------- trousers
    if is_tr.any():
        T_ = is_tr
        t_th, r_th, rv_th = fr.seg(P, "thigh_{s}", True)
        t_cf, r_cf, rv_cf = fr.seg(P, "calf_{s}", True)
        sgx = np.sign(P[:, 0])
        leg_t = np.where(t_cf > 0.0, 1.0 + t_cf, t_th)      # 0 hip .. 1 knee .. 2 ankle
        rv = np.where((t_cf > 0.0)[:, None], rv_cf, rv_th)
        rr = np.where(t_cf > 0.0, r_cf, r_th)
        # angle round the leg from the lateral side (outseam) and the medial side (inseam)
        latd = np.zeros(m, np.float32)
        frontd = np.zeros(m, np.float32)
        for sg in (1, -1):
            s = 'l' if sg > 0 else 'r'
            for bn, sel in (("thigh", t_cf <= 0.0), ("calf", t_cf > 0.0)):
                ax = fr.axis(f"{bn}_{s}")
                lat = np.array([sg, 0, 0.0]) - ax * (sg * ax[0])
                lat /= np.linalg.norm(lat)
                fw = np.array([0, -1.0, 0]) - ax * (-ax[1])
                fw /= np.linalg.norm(fw)
                mm = T_ & (sgx == sg) & sel
                latd[mm] = np.arctan2(rv[mm] @ fw, rv[mm] @ lat)          # 0 = lateral, +pi/2 = front
        legish = T_ & (P[:, 2] < 0.92)
        d_out = np.where(legish, latd * rr, 9.0)
        d_inn = np.where(legish, (np.pi - np.abs(latd)) * rr, 9.0)
        seam = line(d_out, 0.0009, tex) + line(d_inn, 0.0008, tex)
        thread = np.maximum(thread, stitches(np.abs(d_out) - 0.004, P[:, 2], 0.0003, 0.003, tex) * legish)
        # waistband + belt loops, fly
        wz = trouser_cfg["waist_z0"] + trouser_cfg["waist_tilt"] * P[:, 1]
        wb = T_ & (P[:, 2] > wz - 0.042)
        d_wb = np.where(T_, P[:, 2] - (wz - 0.042), 9.0)
        seam = np.maximum(seam, line(d_wb, 0.0009, tex))
        az = np.arctan2(P[:, 0], -(P[:, 1] + 0.03))
        loops_ = wb & (np.abs(((az / (2 * np.pi) * 0.9) % 0.09) - 0.045) < 0.006)
        h[loops_] += 0.0012
        fly = T_ & (np.abs(P[:, 0] - 0.012) < 0.012) & (P[:, 1] < 0) & (P[:, 2] > wz - 0.22) & ~wb
        d_fly = np.where(T_ & (P[:, 1] < 0) & (P[:, 2] > wz - 0.23), np.abs(P[:, 0] - 0.012) - 0.018, 9.0)
        seam = np.maximum(seam, line(d_fly, 0.0008, tex) * (P[:, 2] > wz - 0.22))
        # knee reinforcement panel (front, around the knee), cargo pockets (lateral thigh)
        kneep = T_ & (leg_t > 0.78) & (leg_t < 1.20) & (np.abs(latd - np.pi / 2) < 1.05)
        d_kp = np.where(T_ & (leg_t > 0.6) & (leg_t < 1.4), np.maximum(np.maximum(0.78 - leg_t, leg_t - 1.20) * 0.45, (np.abs(latd - np.pi / 2) - 1.05) * rr), 9.0)
        seam = np.maximum(seam, line(d_kp, 0.0009, tex))
        thread = np.maximum(thread, stitches(d_kp + 0.003, P[:, 2] + P[:, 0], 0.0003, 0.003, tex) * (np.abs(d_kp) < 0.01))
        reinf = np.maximum(reinf, kneep.astype(np.float32))
        pkt = T_ & (t_th > 0.36) & (t_th < 0.70) & (t_cf <= 0) & (np.abs(latd - 0.25) < 0.62)
        d_pc = np.where(T_ & (t_cf <= 0) & (t_th > 0.2) & (t_th < 0.85), np.maximum(np.maximum(0.36 - t_th, t_th - 0.70) * 0.43, (np.abs(latd - 0.25) - 0.62) * rr), 9.0)
        seam = np.maximum(seam, line(d_pc, 0.0009, tex))
        thread = np.maximum(thread, stitches(d_pc + 0.003, P[:, 2] + P[:, 1], 0.0003, 0.003, tex) * (np.abs(d_pc) < 0.01))
        pflap = pkt & (t_th < 0.45)
        d_fl = np.where(pkt, t_th - 0.45, 9.0) * 0.43
        seam = np.maximum(seam, line(d_fl, 0.0009, tex))
        h[pkt] += 0.0016
        h[pflap] += 0.0010
        cav[pkt & ~pflap] *= (1 - 0.35 * sm(0.012, 0.0, d_fl[pkt & ~pflap]))
        # bellows fold down the pocket middle
        h[pkt] += (np.cos((latd[pkt] - 0.25) / 0.62 * np.pi) * 0.0006)
        # hem band + drawcord
        hem = T_ & (P[:, 2] < trouser_cfg["hem_z"] + 0.030)
        seam = np.maximum(seam, line(np.where(T_, P[:, 2] - (trouser_cfg["hem_z"] + 0.030), 9.0), 0.0009, tex))
        reinf = np.maximum(reinf, hem * 0.4)
        # folds: back of the knee, crotch / hip diagonals, stacked hem, seat
        warp = wave_noise(P, 0.06, 2, seed + 9, 6) * 0.35
        kb = T_ & (np.abs(leg_t - 1.0) < 0.22) & (np.abs(latd + np.pi / 2) < 1.3)
        h[kb] += (fold_wave((leg_t[kb] - 1.0) * 0.45 / 0.03 + warp[kb]) * sm(0.22, 0.05, np.abs(leg_t[kb] - 1.0)) * 0.0028)
        cr = T_ & (t_th < 0.45) & (t_cf <= 0) & (np.abs(latd - np.pi / 2) < 1.4)
        dg = (P[:, 2] * 0.7 - np.abs(P[:, 0]) * 0.7)
        h[cr] += (fold_wave(dg[cr] / 0.035 + warp[cr]) * sm(0.45, 0.05, t_th[cr]) * 0.0020)
        st = T_ & (P[:, 2] < 0.34)
        h[st] += (fold_wave(P[st, 2] / 0.030 + warp[st] * 1.5) * sm(0.34, 0.20, P[st, 2]) * 0.0030)
        h[T_] += rip[T_] * 0.00006 + weave[T_] * 0.00002 + wr[T_] * 0.0007
        seam_dark = np.maximum(seam_dark, seam * T_)
        h -= seam * T_ * 0.00045
    # ---------------- balaclava (knit) + gaiter
    gaiter = np.zeros(m, np.float32)
    if is_bala.any():
        B_ = is_bala
        gaiter[B_] = sm(0.3, 0.7, td["iv_gaiter"][B_])
        rib = np.abs(np.sin(np.arctan2(P[:, 0], -(P[:, 1] + 0.05)) * 170)).astype(np.float32)
        h[B_] += ((rib[B_] - 0.5) * 0.00008) * (1 - gaiter[B_])
        h[B_] += (weave[B_] * 0.00004 + wave_noise(P[B_], 0.05, 2, seed + 12, 6) * 0.0004 * gaiter[B_])
        # gaiter: horizontal soft folds under the nose + a rolled top edge
        gf = fold_wave(P[:, 2] / 0.018 + wave_noise(P, 0.04, 2, seed + 13, 6) * 0.4)
        h[B_] += (gf[B_] * 0.0003 * gaiter[B_])
        edge = np.clip(1 - np.abs(td["iv_gaiter"] - 0.5) / 0.25, 0, 1)
        h[B_] += (edge[B_] * 0.0010)
        rough[B_] = 0.93
    # ---------------- helmet cover (camo, gores, elastic rim)
    if is_helm.any():
        H_ = is_helm
        c = np.array([0.0, -0.051, 1.700])
        d = P - c
        azh = np.arctan2(d[:, 0], -d[:, 1])
        rxy = np.linalg.norm(d[:, :2], axis=1)
        gore = np.abs(((azh / (np.pi / 2)) + 0.5) % 1.0 - 0.5) * (np.pi / 2) * rxy
        seam = line(gore, 0.0008, tex) * sm(1.70, 1.74, P[:, 2]) * sm(1.83, 1.81, P[:, 2])
        thread = np.maximum(thread, stitches(gore - 0.004, P[:, 2], 0.0003, 0.003, tex) * H_ * sm(1.70, 1.74, P[:, 2]))
        wr2 = wave_noise(P, 0.045, 3, seed + 21, 7)
        h[H_] += (wr2[H_] * 0.0011 + rip[H_] * 0.00006)
        rimz = P[:, 2] - (td["P"][:, 2].min() if False else 0)
        seam_dark = np.maximum(seam_dark, seam * H_)
        h -= seam * H_ * 0.0004
        rough[H_] = 0.86
    # ---------------- skin behind the glasses
    if is_skin.any():
        rough[is_skin] = 0.55
        h[is_skin] += wave_noise(P[is_skin], 0.004, 2, seed + 30, 6) * 0.00005
    # loop patches
    h += loop_patch * (wave_noise(P, 0.0009, 2, seed + 40, 7) * 0.00008 + 0.0004)
    rough = np.where(loop_patch > 0.5, 0.97, rough)
    rough = rough + 0.03 * wave_noise(P, 0.09, 2, seed + 41, 5)
    cav *= (1 - 0.30 * seam_dark)
    camoW = camo_layers(P, seed)
    return dict(P=P, camoW=camoW, solid=solid, reinf=reinf, seam=seam_dark, thread=thread, loop=loop_patch,
                gaiter=gaiter, is_bala=is_bala, is_skin=is_skin, is_helm=is_helm, h=h, rough=np.clip(rough, 0.3, 1.0),
                cav=cav, macro=wave_noise(P, 0.25, 2, seed + 50, 5), grime=grime(P, N))


def grime(P, N):
    """Wear: dust on the lower legs / knees / seat, darker creases -- a gentle multiplier (0..1)."""
    low = np.clip((0.55 - P[:, 2]) / 0.45, 0, 1)
    n = wave_noise(P, 0.08, 3, 77, 6)
    return (low * (0.6 + 0.4 * n)).astype(np.float32)


def cloth_base(cm, team):
    c = CAMO[team]
    base = camo_color(cm["camoW"], team)
    tor = srgb(c["torso"])[None, :] * (1 + 0.04 * cm["macro"][:, None])
    base = base * (1 - cm["solid"][:, None]) + tor * cm["solid"][:, None]
    base *= (1 - 0.10 * cm["reinf"])[:, None]
    base *= (1 - 0.18 * cm["seam"])[:, None]
    thr = srgb(c["c1"])[None, :]
    base = base * (1 - cm["thread"][:, None] * 0.6) + thr * cm["thread"][:, None] * 0.6
    base *= (1 + 0.10 * cm["loop"])[:, None]
    # dust on the lower legs / boots side (lighter, desaturated)
    dust = srgb("#8f8570")[None, :]
    gw = (cm["grime"] * 0.22)[:, None]
    base = base * (1 - gw) + dust * gw
    b = cm["is_bala"]
    if b.any():
        bal = srgb(NEUTRAL["balaclava"])[None, :] * (1 + 0.05 * cm["macro"][b, None])
        gai = srgb(NEUTRAL["gaiter"])[None, :] * (1 + 0.06 * cm["macro"][b, None])
        # neck gaiter / shemagh: low-contrast woven check (sand / olive drab) with darker lines
        Pb = cm["P"][b]
        u = np.arctan2(Pb[:, 0], -(Pb[:, 1] + 0.05)) * 0.085
        v = Pb[:, 2]
        cell = 0.011
        chk = ((np.floor(u / cell) + np.floor(v / cell)) % 2).astype(np.float32)
        ln = np.maximum(np.abs(((u / cell) % 1) - 0.5), np.abs(((v / cell) % 1) - 0.5))
        lines = np.clip((ln - 0.40) / 0.08, 0, 1)
        sand = srgb("#7d765f")[None, :]
        gai = gai * (1 - 0.35 * chk[:, None]) + sand * (0.35 * chk[:, None])
        gai = gai * (1 - 0.30 * lines[:, None])
        g = cm["gaiter"][b, None]
        base[b] = bal * (1 - g) + gai * g
    k = cm["is_skin"]
    if k.any():
        base[k] = srgb(NEUTRAL["skin"])[None, :] * (1 + 0.05 * cm["macro"][k, None])
    return np.clip(base, 0, 1)


# =============================================================================
# gear (neutral fabric + hard parts)
# =============================================================================

HARD = {
    # zone: (colour hex, roughness, metallic)
    "hard": ("#1e1f1d", 0.62, 0.0), "mag": ("#2b2b2a", 0.74, 0.0), "rail": ("#18191a", 0.74, 0.0),
    "shroud": ("#141516", 0.42, 1.0), "headset": ("#2e3129", 0.58, 0.0), "lens": ("#0c0d10", 0.05, 0.0),
    "frame": ("#161616", 0.48, 0.0), "kneepad": ("#1e1e1c", 0.70, 0.0), "strap": ("#1b1b1a", 0.88, 0.0),
    "helmet": ("#1f201d", 0.80, 0.0),
}
FABRIC_ZONES = ("carrier", "pouch", "belt")


def gear_maps(td, objs, fr, conv, seed=9):
    """Per texel base colour (fabric texels neutral grey, hard texels real colour), roughness,
    metallic, height, cavity for the gear atlas.  objs: list of objects (zone in ob['iv_zone']).
    conv: per-object per-texel convexity (interpolated field) array."""
    P, N = td["P"].astype(np.float64), td["N"]
    m = len(P)
    tex = np.linalg.norm(td["dPdu"], axis=1).astype(np.float32)
    oid = td["oid"]
    names = np.array([o.name for o in objs])[oid]
    zones = np.array([o.get("iv_zone", "hard") for o in objs])[oid]
    base = np.zeros((m, 3), np.float32)
    rough = np.full(m, 0.8, np.float32)
    metal = np.zeros(m, np.float32)
    h = np.zeros(m, np.float32)
    cav = np.ones(m, np.float32)
    fab = np.isin(zones, FABRIC_ZONES)
    # ---- nylon fabric (neutral): cordura weave, MOLLE rows, binding tape on convex edges
    if fab.any():
        F_ = fab
        weave = (np.abs(np.sin(P[:, 0] * 2 * np.pi / 0.0012)) * np.abs(np.sin(P[:, 2] * 2 * np.pi / 0.0012))).astype(np.float32)
        wn = wave_noise(P, 0.05, 3, seed + 1, 6)
        outward = np.zeros(m, np.float32)
        # outward facing = away from the torso axis (bags, cummerbund, belt)
        rad = P[:, :2] - np.array([0.0, -0.03])
        rad /= np.maximum(np.linalg.norm(rad, axis=1)[:, None], 1e-9)
        outward = np.clip((N[:, :2] * rad).sum(1), 0, 1)
        molle_z = (P[:, 2] % 0.0381) / 0.0381                       # PALS: 1" webbing on a 1.5" pitch
        web = sm(0.0, 0.03, molle_z) * sm(0.69, 0.66, molle_z)
        bartack = line(((np.arctan2(P[:, 0], -(P[:, 1] + 0.03)) * np.linalg.norm(P[:, :2] - [0, -0.03], axis=1)) % 0.0381) - 0.019, 0.0014, tex)
        molle_zone = F_ & np.isin(zones, ("carrier", "belt")) & (outward > 0.55)
        # admin pouch front: loop patch
        loopp = F_ & (names == "SG_PC_AdminPouch") & (outward > 0.6)
        webh = web * 0.0011 + bartack * web * 0.0004
        h[molle_zone] += webh[molle_zone]
        cav[molle_zone] *= (1 - 0.25 * (1 - web[molle_zone]) * sm(0.66, 0.72, molle_z[molle_zone]))
        edge = np.clip(conv[F_] * 3.0, 0, 1)
        tape = np.zeros(m, np.float32)
        tape[F_] = sm(0.25, 0.6, edge)
        h += tape * 0.0004
        v = 0.94 + 0.05 * wn - 0.10 * (weave - 0.5) * 0.3
        v *= (1 - 0.06 * tape) * (1 + 0.03 * web * molle_zone)
        # pouch flaps: a horizontal flap line 3 cm under each pouch top on outward faces
        pouch = F_ & (zones == "pouch")
        top = np.zeros(m)
        for k, o in enumerate(objs):
            if o.get("iv_zone") == "pouch":
                sel = oid == k
                if sel.any():
                    top[sel] = P[sel, 2].max()
        dfl = np.where(pouch, P[:, 2] - (top - 0.032), 9.0)
        flap_edge = line(dfl, 0.0010, tex) * (outward > 0.3)
        h[pouch] += np.where(dfl[pouch] > 0, 0.0012, 0.0)
        h -= flap_edge * 0.0008
        cav *= (1 - 0.35 * flap_edge)
        cav[pouch] *= (1 - 0.3 * sm(0.0, -0.01, dfl[pouch]) * sm(-0.02, -0.004, dfl[pouch]))
        # stitch rows along flap edges and binding tape
        thr = stitches(dfl + 0.003, P[:, 0] + P[:, 1], 0.0003, 0.0032, tex) * pouch
        v = v * (1 - 0.35 * thr)
        v = v * (1 + 0.10 * loopp)
        h += loopp * (wave_noise(P, 0.0009, 2, seed + 7, 6) * 0.00008 + 0.0003)
        base[F_] = (GEAR_WHITE * v[F_])[:, None]
        rough[F_] = 0.86 + 0.05 * wn[F_] - 0.04 * tape[F_] + 0.08 * loopp[F_]
        h[F_] += (weave[F_] - 0.25) * 0.00003
    # ---- hard parts
    for z, (hx, r, mt) in HARD.items():
        sel = (zones == z)
        if not sel.any():
            continue
        c = srgb(hx)
        n = wave_noise(P[sel], 0.03, 2, seed + 20, 6)
        base[sel] = c[None, :] * (1 + 0.06 * n[:, None])
        rough[sel] = r + 0.04 * n
        metal[sel] = mt
    # rails: slots every 12 mm
    rl = zones == "rail"
    if rl.any():
        c = np.array([0.0, -0.051])
        azr = np.arctan2(P[:, 0] - c[0], -(P[:, 1] - c[1])) * 0.12
        slot = sm(0.35, 0.30, np.abs(((azr / 0.012) % 1.0) - 0.5)) * rl
        h -= slot * 0.0007
        cav *= (1 - 0.4 * slot)
    # magazines: ribs on the flanks, brass cartridges at the top
    mg = zones == "mag"
    if mg.any():
        for k, o in enumerate(objs):
            if o.get("iv_zone") != "mag":
                continue
            sel = oid == k
            topz = P[sel, 2].max()
            cx = 0.5 * (P[sel, 0].max() + P[sel, 0].min())
            br = sel & (P[:, 2] > topz - 0.0105) & (np.abs(P[:, 0] - cx) < 0.0068) & (N[:, 2] > -0.3)
            base[br] = srgb("#b08a45")
            rough[br] = 0.32
            metal[br] = 1.0
            rib = sel & ~br & (P[:, 2] < topz - 0.02)
            h[rib] += (np.abs(np.sin(P[rib, 2] * 2 * np.pi / 0.004)) * 0.00025)
    # knee pads: grip grooves
    kp = zones == "kneepad"
    if kp.any():
        gz = np.minimum(np.abs(((P[:, 2] + P[:, 0]) / 0.012) % 1 - 0.5), np.abs(((P[:, 2] - P[:, 0]) / 0.012) % 1 - 0.5))
        gro = sm(0.08, 0.02, gz) * kp
        h -= gro * 0.0008
        cav *= (1 - 0.35 * gro)
    # straps (webbing weave)
    stp = zones == "strap"
    if stp.any():
        h[stp] += (np.abs(np.sin(P[stp, 0] * 2 * np.pi / 0.0016 + P[stp, 2] * 2 * np.pi / 0.0016)) * 0.00005)
    # headset cups: a parting line
    hs = zones == "headset"
    if hs.any():
        ring = line(np.abs(P[:, 0]) - 0.107, 0.0006, tex) * hs
        h -= ring * 0.0004
    # boots: suede upper, dark toe bumper, laces on the instep, padded collar; soles: lug tread
    bt = names == "Soldier_Boots"
    if bt.any():
        c_b, c_t = srgb(NEUTRAL["boot"]), srgb(NEUTRAL["boot_toe"])
        fwd = np.zeros(m)
        for sg in (1, -1):
            s = 'l' if sg > 0 else 'r'
            a0, a1 = fr.b[f"foot_{s}"]
            sel = bt & (np.sign(P[:, 0]) == sg)
            ax = (a1 - a0)[:2] / np.linalg.norm((a1 - a0)[:2])
            fwd[sel] = (P[sel, :2] - a0[:2]) @ ax
        toe = bt & (fwd > 0.135) & (P[:, 2] < 0.075)
        heel = bt & (fwd < -0.02) & (P[:, 2] < 0.075)
        n = wave_noise(P, 0.02, 3, seed + 31, 6)
        base[bt] = c_b[None, :] * (1 + 0.10 * n[bt, None])
        base[toe | heel] = c_t[None, :] * (1 + 0.06 * n[toe | heel, None])
        rough[bt] = 0.82
        rough[toe | heel] = 0.66
        # lace strip on top of the instep / shaft front
        latw = np.zeros(m)
        for sg in (1, -1):
            s = 'l' if sg > 0 else 'r'
            a0, a1 = fr.b[f"foot_{s}"]
            sel = bt & (np.sign(P[:, 0]) == sg)
            latw[sel] = np.abs(P[sel, 0] - (a0[0] + (a1[0] - a0[0]) * np.clip(fwd[sel] / 0.13, 0, 1)))
        lace_zone = bt & (latw < 0.018) & (N[:, 2] + (-N[:, 1]) > 0.35) & (fwd > -0.01) & (fwd < 0.12) & (P[:, 2] > 0.05)
        zz = np.where(lace_zone, (P[:, 2] + fwd * 0.8) / 0.013, 0)
        lace = sm(0.35, 0.2, np.abs((zz % 1.0) - 0.5 + (latw / 0.018 - 0.5) * 0.4)) * lace_zone
        base[lace_zone] = base[lace_zone] * 0.6
        base = base * (1 - lace[:, None]) + srgb(NEUTRAL["lace"])[None, :] * lace[:, None]
        h += lace * 0.0012
        eyelet = bt & (np.abs(latw - 0.018) < 0.002) & lace_zone
        base[eyelet] = srgb("#3a3a36")
        metal[eyelet] = 0.8
        # stitch line around the toe bumper / heel counter
        seamb = line(np.where(bt, np.minimum(np.abs(fwd - 0.135), np.abs(fwd + 0.02)), 9.0), 0.0008, tex) * (P[:, 2] < 0.075)
        h -= seamb * 0.0005
        cav *= (1 - 0.3 * seamb)
        h[bt] += n[bt] * 0.0002 + wave_noise(P[bt], 0.0012, 2, seed + 32, 6) * 0.00004
    so = np.char.startswith(names.astype(str), "Soldier_Sole")
    if so.any():
        base[so] = srgb(NEUTRAL["sole"])
        rough[so] = 0.86
        bottom = so & (N[:, 2] < -0.7)
        lug = (np.abs(((P[:, 0] / 0.011) % 1) - 0.5) < 0.30) & (np.abs(((P[:, 1] / 0.014 + 0.5 * np.floor(P[:, 0] / 0.011)) % 1) - 0.5) < 0.32)
        h[bottom] += lug[bottom] * 0.0025
        sidez = so & (np.abs(N[:, 2]) < 0.6)
        h[sidez] += (np.abs(np.sin(P[sidez, 2] * 2 * np.pi / 0.006)) * 0.0004)
    # generic wear: lighter scuffs on convex edges of hard parts and fabric
    edge = np.clip(conv * 2.5, 0, 1)
    wear = edge * (0.5 + 0.5 * wave_noise(P, 0.01, 2, seed + 60, 6)) * ~bt * ~fab
    base *= (1 + 0.18 * wear)[:, None]
    rough = np.clip(rough - 0.10 * wear, 0.03, 1.0)
    return dict(base=np.clip(base, 0, 1), rough=rough, metal=metal, h=h, cav=cav, fab=fab)


# =============================================================================
# team bands
# =============================================================================

def team_maps(td, objs, fr, team, symbol):
    P, N = td["P"].astype(np.float64), td["N"]
    m = len(P)
    tex = np.linalg.norm(td["dPdu"], axis=1).astype(np.float32)
    names = np.array([o.name for o in objs])[td["oid"]]
    col = srgb(team["color"])
    dark = srgb("#141414")
    base = np.tile(col, (m, 1)).astype(np.float32)
    h = np.zeros(m, np.float32)
    rough = np.full(m, 0.80, np.float32)
    n = wave_noise(P, 0.02, 2, 5, 6)
    base *= (1 + 0.05 * n)[:, None]
    # hook-and-loop / webbing texture
    h += (np.abs(np.sin(P[:, 2] * 2 * np.pi / 0.0015)) * 0.00005).astype(np.float32)
    ab = names == "Soldier_Armbands"
    if ab.any():
        t_up, r_up, rv_up = fr.seg(P, "upperarm_{s}", True)
        sym = np.zeros(m, np.float32)
        for sg in (1, -1):
            s = 'l' if sg > 0 else 'r'
            ax = fr.axis(f"upperarm_{s}")
            out = np.array([sg, -0.35, 0.25])
            ref = out - ax * (out @ ax)
            ref /= np.linalg.norm(ref)
            bi = np.cross(ax, ref) * sg
            sel = ab & (np.sign(P[:, 0]) == sg)
            # local 2D coordinates (m) on the outer side: x round the arm, y along it (band centre t=0.54)
            xs = np.arctan2(rv_up[sel] @ bi, rv_up[sel] @ ref) * r_up[sel]
            ys = (t_up[sel] - 0.54) * 0.298
            rr_ = 0.024
            if symbol == "circle":
                d = np.hypot(xs, ys) - rr_
                inside = np.abs(d) < 0.0045                   # ring
            elif symbol == "triangle":
                k = math.sqrt(3)
                qx, qy = np.abs(xs), ys + rr_ * 0.4
                d = np.maximum(qx * k / 2 + qy / 2, -qy) - rr_ * 0.55
                inside = d < 0
            else:
                d = np.maximum(np.abs(xs), np.abs(ys)) - rr_ * 0.80
                inside = d < 0
            aa = np.clip(0.5 - d / np.maximum(tex[sel], 1e-5) * 0.5, 0, 1) if symbol != "circle" else np.clip(0.5 - (np.abs(np.hypot(xs, ys) - rr_) - 0.0045) / np.maximum(tex[sel], 1e-5) * 0.5, 0, 1)
            sym[sel] = aa
        base = base * (1 - sym[:, None]) + dark[None, :] * sym[:, None]
        h += sym * 0.0002
        rough = np.where(sym > 0.5, 0.6, rough)
    return dict(base=np.clip(base, 0, 1), rough=rough, metal=np.zeros(m, np.float32), h=h, cav=np.ones(m, np.float32))
