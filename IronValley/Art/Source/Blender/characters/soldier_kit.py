"""
soldier_kit.py -- the soldier's add-on kit with real volume (Iron Valley): pockets with flaps on the
garments, team armbands as bands round the sleeve, knee-pad straps, thigh holster, four magazine
pouches, assault pack, glove knuckle guards / wrist straps / finger pads, chunky boot soles.

Every part is a CLOSED mesh.  Parts are collected in a soldier_gear.Built with a binding:
('rigid', bone) or ('fabric', garment_object_name, allowed_bones_or_None) -- fabric parts take the
weights (and corrective shapes) of the surface they are sewn / strapped onto.
Conventions: metres, Z up, character faces -Y, left = +X, rest A-pose.  Deterministic.
"""

import math

import numpy as np
from mathutils import Vector, Matrix

import ivsoldier as S
import ivchar as C
import ivhands as HN
import soldier_gear as G
import soldier_cloth as SC


# =============================================================================
# helpers
# =============================================================================

def limb_grid(bv, ax, s_vals, phi_vals, R=0.25):
    """Rays from outside towards a limb axis (LimbAxis) onto a surface: P, N of shape
    (len(phi_vals), len(s_vals), 3) -- u runs round the limb, v along it."""
    nu, nv = len(phi_vals), len(s_vals)
    O = np.zeros((nu, nv, 3)); D = np.zeros_like(O)
    for j, s in enumerate(s_vals):
        A, T, U, V = ax.frame(s)
        for i, ph in enumerate(phi_vals):
            d = U * math.cos(ph) + V * math.sin(ph)
            O[i, j] = A + d * R
            D[i, j] = -d
    return G.surface_grid(bv, O, D, back=0.0)


def limb_bvh(ob, arm, bones, min_share=0.5):
    """BVH of the faces of a garment that belong to a limb (all vertices with >= min_share weight on
    `bones`): rays for bands round a limb must not hit the torso or the other leg."""
    names = S.bone_names(arm)
    W = S.read_W(ob, names)
    idx = [names.index(b) for b in bones]
    w = W[:, idx].sum(1)
    co = S.co_of(ob)
    tris = S.tris_of(ob.data)
    keep = (w[tris] >= min_share).all(1)
    return S.bvh(co, tris[keep]), co


def lift_outside(V, bv, clear, iters=4):
    """Move vertices that are closer than `clear` to (or inside) a surface out along its normal."""
    V = np.array(V, float)
    for _ in range(iters):
        loc, nor, fi, d = S.nearest_on(bv, V, 0.1)
        ok = fi >= 0
        sd = np.where(((V - loc) * nor).sum(1) >= 0, d, -d)
        bad = ok & (sd < clear)
        if not bad.any():
            break
        V[bad] = loc[bad] + nor[bad] * clear
    return V


def push_out_of(Vp, Fp, gco, direction, margin=0.001, iters=10):
    """Translate a closed part along `direction` until no garment vertex (gco) is inside it."""
    d = np.asarray(direction, float) / np.linalg.norm(direction)
    Vp = np.array(Vp, float)
    tris = np.array([t for f in Fp for t in ([f] if len(f) == 3 else [[f[0], f[i], f[i + 1]] for i in range(1, len(f) - 1)])])
    for _ in range(iters):
        pb = S.bvh(Vp, tris)
        lo, hi = Vp.min(0) - 0.01, Vp.max(0) + 0.01
        g = gco[((gco >= lo) & (gco <= hi)).all(1)]
        if not len(g):
            break
        sg = S.signed_bvh(pb, g, maxd=0.05)
        cand = np.nonzero(np.nan_to_num(sg, nan=1.0) < 0)[0]
        if not len(cand):
            break
        ins = S.closed_inside(pb, g[cand])
        if not ins.any():
            break
        Vp = Vp + d * (float((-sg[cand][ins]).max()) + margin)
    return Vp


def pillow(nu, nv, t_c, t_e, pu=5.0, pv=5.0):
    u = np.linspace(-1, 1, nu)[:, None]
    v = np.linspace(-1, 1, nv)[None, :]
    return t_e + (t_c - t_e) * (1 - np.abs(u) ** pu) * (1 - np.abs(v) ** pv)


def tri_list(F):
    return np.array([t for f in F for t in ([f] if len(f) == 3 else [[f[0], f[i], f[i + 1]] for i in range(1, len(f) - 1)])])


# =============================================================================
# pockets with flaps, armbands, straps on the garments
# =============================================================================

def pocket(B, name, bv, gco, ax, s0, s1, ph0, ph1, garment, t_c=0.016, t_e=0.004, clear=0.0012,
           flap=0.045, nu=11, nv=11, bones=None):
    """Bellows pocket (pillow slab) on a limb region + a flap over its top (a separate thin slab
    draped over the pocket top and past its sides).  s runs along the limb (s1 = pocket top side
    towards the joint above: s0 < s1 means the pocket top is at the SMALLER s)."""
    s_vals = np.linspace(s0, s1, nv)
    phis = np.linspace(ph0, ph1, nu)
    P, N = limb_grid(bv, ax, s_vals, phis)
    P = G.smooth_grid(P, 2)
    N = G.smooth_grid(N, 3)
    N /= np.linalg.norm(N, axis=-1, keepdims=True)
    T = pillow(nu, nv, t_c, t_e)
    V, F, Wl = G.slab_from_grid(P, N, clear, T, round_edge=0.25, return_walls=True)
    V = push_out_of(V, F, gco, N.reshape(-1, 3).mean(0))
    B.add(name, V, F, ("fabric", garment, bones), atlas="cloth", zone="pocket")
    # flap: rays onto the pocket (falls back to the garment beyond the pocket's sides)
    pb = S.bvh(V, tri_list(F))
    top = s0                           # pocket top = the s0 edge
    fs = np.linspace(top - 0.006, top + flap, 5)
    dph = (ph1 - ph0) * 0.07
    fph = np.linspace(ph0 - dph, ph1 + dph, nu + 2)
    Pf, Nf = limb_grid(pb, ax, fs, fph)
    Pg, Ng = limb_grid(bv, ax, fs, fph)
    # use whichever surface is further out along the normal (pocket where it exists)
    dp = ((Pf - Pg) * Ng).sum(-1)
    use_p = dp > 0.0005
    Pc = np.where(use_p[..., None], Pf, Pg + Ng * 0.0012)
    Nc = np.where(use_p[..., None], Nf, Ng)
    Pc = G.smooth_grid(Pc, 1)
    Nc = G.smooth_grid(Nc, 2)
    Nc /= np.linalg.norm(Nc, axis=-1, keepdims=True)
    Vf, Ff, Wf = G.slab_from_grid(Pc, Nc, 0.0009, 0.0030, round_edge=0.3, return_walls=True)
    Vf = lift_outside(Vf, pb, 0.0006)
    B.add(name + "Flap", Vf, Ff, ("fabric", garment, bones), atlas="cloth", zone="pocket")
    return {"s": [round(float(s0), 3), round(float(s1), 3)], "phi_deg": [round(math.degrees(ph0)), round(math.degrees(ph1))]}


def band_round_limb(B, name, bv, ax, s0, s1, ph0, ph1, garment, thick, clear, nu=40, nv=3, atlas="gear",
                    zone="strap", closed=False, bones=None, round_edge=0.25):
    s_vals = np.linspace(s0, s1, nv)
    phis = np.linspace(ph0, ph1, nu, endpoint=not closed)
    P, N = limb_grid(bv, ax, s_vals, phis)
    P = G.smooth_grid(P, 1, closed_u=closed)
    N = G.smooth_grid(N, 2, closed_u=closed)
    N /= np.linalg.norm(N, axis=-1, keepdims=True)
    V, F, Wl = G.slab_from_grid(P, N, clear, thick, closed_u=closed, round_edge=round_edge, return_walls=True)
    V = lift_outside(V, bv, clear * 0.8)
    B.add(name, V, F, ("fabric", garment, bones), atlas=atlas, zone=zone, flat=Wl)
    return V, F


def angle_of(ax, s, direction):
    A, T, U, V = ax.frame(s)
    d = np.asarray(direction, float)
    return math.atan2(d @ V, d @ U)


def garment_kit(B, arm, shirt, trousers, info):
    """Sleeve pockets, team armbands, left cargo pocket, knee-pad straps."""
    from soldier import garment_bvh          # noqa: late import (same process)
    sbv, sco = garment_bvh(shirt)
    tbv, tco = garment_bvh(trousers)
    out = {}
    for s, sg in (("l", 1.0), ("r", -1.0)):
        ax = SC.arm_axis(arm, s)
        abv, _ = limb_bvh(shirt, arm, [f"upperarm_{s}", f"upperarm_twist_01_{s}", f"lowerarm_{s}", f"lowerarm_twist_01_{s}"])
        lat = np.array([sg, 0.0, 0.0])
        fwd = np.array([0.0, -1.0, 0.0])
        c = angle_of(ax, 0.09, lat * math.cos(math.radians(18)) + fwd * math.sin(math.radians(18)))
        out[f"sleeve_pocket_{s}"] = pocket(B, f"SleevePocket_{s.upper()}", abv, sco, ax, 0.030, 0.138,
                                           c - math.radians(46), c + math.radians(46), "Soldier_Shirt",
                                           t_c=0.011, t_e=0.0035, flap=0.040)
        # team armband: a band round the sleeve below the pocket
        band_round_limb(B, f"Armband_{s.upper()}", abv, ax, 0.158, 0.214, -math.pi, math.pi, "Soldier_Shirt",
                        thick=0.0026, clear=0.0016, nu=36, nv=3, atlas="team", zone="team", closed=True)
    # cargo pocket on the left thigh (the right thigh carries the holster)
    ax = SC.leg_axis(arm, "l")
    lbv, _ = limb_bvh(trousers, arm, ["thigh_l", "calf_l"])
    c = angle_of(ax, 0.30, np.array([1.0, 0.18, 0.0]))
    out["cargo_l"] = pocket(B, "CargoPocket_L", lbv, tco, ax, 0.205, 0.405, c - math.radians(50), c + math.radians(50),
                            "Soldier_Trousers", t_c=0.021, t_e=0.005, flap=0.055, nu=12, nv=12)
    # knee-pad straps: round the back of the leg from one edge of the pad to the other
    for s in ("l", "r"):
        ax = SC.leg_axis(arm, s)
        lbv, _ = limb_bvh(trousers, arm, [f"thigh_{s}", f"calf_{s}"])
        kn = ax.L[1]
        for k, (a0, a1) in enumerate(((kn - 0.088, kn - 0.061), (kn + 0.058, kn + 0.085))):
            band_round_limb(B, f"KneeStrap_{s.upper()}{k + 1}", lbv, ax, a0, a1, math.radians(52), math.radians(308),
                            "Soldier_Trousers", thick=0.0036, clear=0.0016, nu=26, nv=3, zone="strap",
                            bones=[f"thigh_{s}", f"calf_{s}"])
    info["garment_kit"] = out
    return out


# =============================================================================
# carrier: magazine pouches + magazines, assault pack
# =============================================================================

def surface_point(bv, origin, direction):
    loc, nor = G.ray_hit(bv, origin, direction, 1.0)
    if loc is None:
        return None, None
    if nor @ np.asarray(direction) > 0:
        nor = -nor
    return loc, nor


def mag_mesh_from_rifle(rifle_parts):
    mag = next(o for o in rifle_parts if o.name.startswith("Magazine_LOD2"))
    rnd = next(o for o in rifle_parts if o.name.startswith("MagRounds_LOD2"))
    parts = []
    for o in (mag, rnd):
        co = S.co_of(o)
        M = np.array(o.matrix_world)
        parts.append((co @ M[:3, :3].T + M[:3, 3], [list(p.vertices) for p in o.data.polygons]))
    return G.merge_parts(parts)


def cut_below(V, F, z_cut):
    import bmesh
    bm = bmesh.new()
    for p in V:
        bm.verts.new(tuple(map(float, p)))
    bm.verts.ensure_lookup_table()
    for f in F:
        try:
            bm.faces.new([bm.verts[k] for k in f])
        except ValueError:
            pass
    geom = list(bm.verts) + list(bm.edges) + list(bm.faces)
    res = bmesh.ops.bisect_plane(bm, geom=geom, plane_co=(0, 0, z_cut), plane_no=(0, 0, 1), clear_inner=True)
    edges = [e for e in res["geom_cut"] if isinstance(e, bmesh.types.BMEdge)]
    if edges:
        bmesh.ops.holes_fill(bm, edges=edges, sides=0)
    bmesh.ops.triangulate(bm, faces=list(bm.faces))
    bmesh.ops.dissolve_limit(bm, angle_limit=math.radians(8), verts=list(bm.verts), edges=list(bm.edges))
    bmesh.ops.triangulate(bm, faces=list(bm.faces))
    Vm = np.array([v.co[:] for v in bm.verts])
    Fm = [[v.index for v in f.verts] for f in bm.faces]
    bm.free()
    return Vm, Fm


def mag_pouches(B, bag_V, bag_F, frame, bag_bottom_z, rifle_parts, snap_to, n=4, w=0.070, d=0.041, h=0.128,
                pitch=0.0715, above=0.036):
    """Four single-magazine pouches side by side on the lower front of the plate bag, each with an
    IV-7 magazine (mesh from the rifle's LOD2, lying flat: its 6.5 cm depth across the pouch) whose
    top stands `above` out of the pouch, and a bungee retention cord."""
    o, ex, ey, ez = frame
    bb = S.bvh(np.asarray(bag_V), tri_list(bag_F))
    Vmag, Fmag = mag_mesh_from_rifle(rifle_parts)
    out = []
    xs = (np.arange(n) - (n - 1) / 2.0) * pitch
    zc = bag_bottom_z + 0.008 + h / 2
    for i, x in enumerate(xs):
        org = o + ex * x + ez * (zc - o[2]) - ey * 0.35
        p, nrm = surface_point(bb, org, ey)
        if p is None:
            # beyond the bag's side: continue the bag's curvature from the last hit
            p, nrm = out[-1]["p"] + ex * pitch, out[-1]["n"]
        t = np.cross(ez, nrm)
        t /= np.linalg.norm(t)
        up = np.cross(nrm, t)
        R = np.column_stack([t, nrm, up])         # local x across, y outwards, z up
        Vp, Fp = G.rbox(w, d, h, 0.007)
        c = p + nrm * (d / 2 + 0.002)
        Vp = Vp @ R.T + c
        Vp = snap_to(Vp, bag_V, bag_F, -nrm)
        B.add(f"PC_MagPouch_{i + 1}", Vp, Fp, ("rigid", "spine_03"), zone="pouch")
        cen = Vp.mean(0)
        top = float(Vp[:, 2].max())
        # magazine: rifle X (depth) -> across the pouch, rifle Y (width) -> outwards, Z up
        Rm = np.column_stack([t, nrm, up])
        Vm = Vmag @ Rm.T
        Vm = Vm - np.array([0.5 * (Vm[:, 0].min() + Vm[:, 0].max()), 0.5 * (Vm[:, 1].min() + Vm[:, 1].max()), Vm[:, 2].max()])
        Vm = Vm + np.array([cen[0], cen[1], top + above])
        Vm2, Fm2 = cut_below(Vm, Fmag, top - 0.015)
        B.add(f"PC_Mag_{i + 1}", Vm2, Fm2, ("rigid", "spine_03"), zone="mag")
        # bungee over the magazine top (across its depth)
        Vb, Fb = G.rbox(0.058, 0.0042, 0.0042, 0.0019, 1)
        Vb = Vb @ R.T + np.array([cen[0], cen[1], top + above + 0.0022])
        B.add(f"PC_Bungee_{i + 1}", Vb, Fb, ("rigid", "spine_03"), zone="hard")
        # pull tab of the bungee hanging down the pouch front
        Vt, Ft = G.rbox(0.016, 0.004, 0.030, 0.0015, 1)
        front = float((Vp @ nrm).max())
        c_t = cen - nrm * float(cen @ nrm) + nrm * (front + 0.0025) + up * (h / 2 - 0.014)
        Vt = Vt @ R.T + c_t
        B.add(f"PC_PullTab_{i + 1}", Vt, Ft, ("rigid", "spine_03"), zone="hard")
        out.append({"p": p, "n": nrm, "x": float(x), "top_z": top, "mag_top_z": top + above})
    return [{"x": round(q["x"], 3), "pouch_top_z": round(q["top_z"], 3), "mag_top_z": round(q["mag_top_z"], 3)} for q in out], \
        float(min(B.parts[f"PC_MagPouch_{i + 1}"]["V"][:, 1].min() for i in range(n)))


def assault_pack(B, bag_V, bag_F, frame, top_z, snap_to, w=0.272, d=0.108, h=0.350):
    """Small assault pack zipped onto the back plate bag: tapered rounded body, front pocket, grab
    handle, compression straps."""
    o, bx, by, bz = frame                      # by points towards the body
    out_ = -by
    bb = S.bvh(np.asarray(bag_V), tri_list(bag_F))
    zc = top_z - h / 2
    p, nrm = surface_point(bb, o + bz * (zc - o[2]) - by * 0.35, by)
    R = np.column_stack([bx, nrm, np.cross(bx, nrm)])
    V, F = G.rbox(w, d, h, 0.028, 3)
    # taper: the outer face and the top are narrower (a real pack sags into a wedge)
    yl = (V[:, 1] + d / 2) / d                  # 0 at the bag, 1 outside
    zl = (V[:, 2] + h / 2) / h
    V[:, 0] *= 1.0 - 0.10 * yl - 0.05 * zl
    V[:, 1] = -d / 2 + (V[:, 1] + d / 2) * (1.0 - 0.28 * zl ** 1.5)
    V = V @ R.T + p + nrm * (d / 2 + 0.002)
    V = snap_to(V, bag_V, bag_F, -nrm)
    B.add("PC_Pack", V, F, ("rigid", "spine_03"), zone="pouch")
    pk = S.bvh(V, tri_list(F))
    # front pocket (lower half of the outer face)
    c0 = V.mean(0) - R[:, 2] * 0.07
    q, qn = surface_point(pk, c0 + nrm * 0.3, -nrm)
    Vf, Ff = G.rbox(0.215, 0.036, 0.150, 0.014, 2)
    Rq = np.column_stack([bx, qn, np.cross(bx, qn)])
    Vf = Vf @ Rq.T + q + qn * 0.019
    Vf = snap_to(Vf, V, F, -qn)
    B.add("PC_PackPocket", Vf, Ff, ("rigid", "spine_03"), zone="pouch")
    # grab handle on the top
    tp = V[np.argmax(V[:, 2])]
    Vh, Fh = G.rbox(0.085, 0.022, 0.011, 0.004, 1)
    Vh = Vh @ R.T + np.array([V[:, 0].mean(), tp[1], tp[2] + 0.004])
    Vh = snap_to(Vh, V, F, np.array([0, 0, -1.0]))
    B.add("PC_PackHandle", Vh, Fh, ("rigid", "spine_03"), zone="strap")
    # compression straps on both sides (2 each)
    for sd in (-1, 1):
        for k, zz in enumerate((0.25, 0.62)):
            zq = V[:, 2].min() + (V[:, 2].max() - V[:, 2].min()) * zz
            q, qn = surface_point(pk, np.array([V[:, 0].mean() + sd * 0.4, V[:, 1].mean(), zq]), np.array([-sd, 0, 0.0]))
            if q is None:
                continue
            Vs, Fs = G.rbox(0.004, d * 0.8, 0.022, 0.0015, 1)
            Vs = Vs + q + qn * 0.003
            Vs = snap_to(Vs, V, F, -qn)
            B.add(f"PC_PackStrap_{'L' if sd > 0 else 'R'}{k + 1}", Vs, Fs, ("rigid", "spine_03"), zone="strap")
    return {"pack_outer_y": round(float(V[:, 1].max()), 3), "pack_top_z": round(float(V[:, 2].max()), 3),
            "pack_bottom_z": round(float(V[:, 2].min()), 3)}


# =============================================================================
# belt kit: thigh holster (right)
# =============================================================================

def thigh_holster(B, arm, trousers, belt_bottom_z, snap_to, info):
    """Drop-leg holster on the right thigh: platform (rigid thigh_r), holster body with a generic
    pistol grip / slide back (rigid thigh_r), hanger strap from the belt (trouser weights: pelvis ->
    thigh), two leg straps round the thigh (trouser weights, thigh_r)."""
    from soldier import garment_bvh          # noqa
    tbv, tco = garment_bvh(trousers)
    ax = SC.leg_axis(arm, "r")
    lbv, _ = limb_bvh(trousers, arm, ["thigh_r", "calf_r"], min_share=0.4)
    c = angle_of(ax, 0.22, np.array([-1.0, 0.12, 0.0]))       # lateral, slightly back
    s0, s1 = 0.115, 0.325
    hw = math.radians(30)
    P, N = limb_grid(tbv, ax, np.linspace(s0, s1, 9), np.linspace(c - hw, c + hw, 7))
    P = G.smooth_grid(P, 3)
    N = G.smooth_grid(N, 3)
    N /= np.linalg.norm(N, axis=-1, keepdims=True)
    Vp, Fp, Wp = G.slab_from_grid(P, N, 0.0045, 0.0075, round_edge=0.2, return_walls=True)
    Vp = push_out_of(Vp, Fp, tco, N.reshape(-1, 3).mean(0), margin=0.002)
    B.add("Holster_Platform", Vp, Fp, ("rigid", "thigh_r"), zone="strap", flat=Wp)
    pb = S.bvh(Vp, tri_list(Fp))
    # holster body on the platform: local frame x along the thigh surface (forward), y outwards, z along the leg (up)
    A, T, U, Vv = ax.frame(0.20)
    nout = U * math.cos(c) + Vv * math.sin(c)
    q, qn = surface_point(pb, A + nout * 0.3 - T * 0.0, -nout)
    up = -T                                                   # leg axis points down
    fx = np.cross(qn, up)
    fx /= np.linalg.norm(fx)
    up = np.cross(fx, qn)
    Rh = np.column_stack([fx, qn, up])
    Vh, Fh = G.rbox(0.058, 0.050, 0.180, 0.012, 2)
    # taper to the muzzle end (bottom) and slant the front
    zl = (Vh[:, 2] + 0.09) / 0.18
    Vh[:, 0] *= 0.78 + 0.22 * zl
    Vh = Vh @ Rh.T + q + qn * 0.027
    Vh = snap_to(Vh, Vp, Fp, -qn)
    B.add("Holster_Body", Vh, Fh, ("rigid", "thigh_r"), zone="holster")
    htop = float((Vh @ up).max())
    # pistol: slide back + grip (generic polymer pistol, no brand features), angled back 17 deg
    cen_top = Vh.mean(0) + up * (htop - float(Vh.mean(0) @ up))
    Vs, Fs = G.rbox(0.040, 0.028, 0.030, 0.004, 1)            # rear of the slide above the holster mouth
    Vs = Vs @ Rh.T + cen_top + up * 0.010 + fx * 0.004
    B.add("Holster_Slide", Vs, Fs, ("rigid", "thigh_r"), zone="hard")
    ang = math.radians(17)
    Rg = np.array(Matrix.Rotation(ang, 3, Vector(tuple(qn))))
    Vg, Fg = G.rbox(0.030, 0.026, 0.092, 0.006, 2)
    Vg = Vg @ Rh.T
    Vg = Vg @ Rg.T + cen_top + up * (0.020 + 0.040) - fx * 0.012
    B.add("Holster_Grip", Vg, Fg, ("rigid", "thigh_r"), zone="hard")
    # hanger: belt bottom -> platform top (on the trousers, lateral hip)
    hs0 = -0.075
    Ph, Nh = limb_grid(tbv, ax, np.linspace(hs0, s0 + 0.02, 7), np.linspace(c - 0.20, c + 0.20, 3))
    Ph = G.smooth_grid(Ph, 2)
    Nh = G.smooth_grid(Nh, 2)
    Nh /= np.linalg.norm(Nh, axis=-1, keepdims=True)
    # hanger strap: u along the strap, v across
    Ph = np.transpose(Ph, (1, 0, 2)).copy()
    Nh = np.transpose(Nh, (1, 0, 2)).copy()
    Vg2, Fg2, Wg2 = G.slab_from_grid(Ph, Nh, 0.0035, 0.0038, round_edge=0.2, return_walls=True)
    Vg2 = lift_outside(Vg2, tbv, 0.003)
    B.add("Holster_Hanger", Vg2, Fg2, ("fabric", "Soldier_Trousers", ["pelvis", "thigh_r"]), zone="strap", flat=Wg2)
    # leg straps round the thigh (from the platform's back edge round the inner thigh to its front edge)
    for k, sm in enumerate((0.165, 0.285)):
        band_round_limb(B, f"Holster_LegStrap{k + 1}", lbv, ax, sm - 0.016, sm + 0.016, c + hw - 0.05, c - hw + 0.05 + 2 * math.pi,
                        "Soldier_Trousers", thick=0.0036, clear=0.0018, nu=24, nv=3, zone="strap", bones=["thigh_r"])
    info["holster"] = {"platform_s": [s0, s1], "angle_deg": round(math.degrees(c), 1)}
    return info["holster"]


# =============================================================================
# glove kit: knuckle guards, wrist straps, finger pads
# =============================================================================

FINGERS = ("index", "middle", "ring", "pinky")


def glove_kit(B, arm, gloves, info):
    out = {}
    for s in ("l", "r"):
        g = gloves[s]
        gco = S.co_of(g)
        gbv = S.bvh(gco, S.tris_of(g.data))
        c, d, r, n = C.palm_frame(arm, s)
        d, r, n = np.array(d), np.array(r), np.array(n)
        back = -n
        mcp = {f: np.array(arm.data.bones[f"{f}_01_{s}"].head_local) for f in FINGERS}
        pip = {f: np.array(arm.data.bones[f"{f}_02_{s}"].head_local) for f in FINGERS}
        # knuckle guard: grid across the MCP line (index -> pinky, +-6 mm), from 22 mm proximal to 7 mm distal
        a0 = mcp["index"] + (mcp["index"] - mcp["pinky"]) / np.linalg.norm(mcp["index"] - mcp["pinky"]) * 0.006
        a1 = mcp["pinky"] - (mcp["index"] - mcp["pinky"]) / np.linalg.norm(mcp["index"] - mcp["pinky"]) * 0.006
        nu, nv = 13, 6
        O = np.zeros((nu, nv, 3)); D = np.zeros_like(O)
        for i, t in enumerate(np.linspace(0, 1, nu)):
            base = a0 * (1 - t) + a1 * t
            for j, v in enumerate(np.linspace(-0.022, 0.007, nv)):
                O[i, j] = base + d * v + back * 0.06
                D[i, j] = -back
        P, N = G.surface_grid(gbv, O, D, back=0.0)
        P = G.smooth_grid(P, 1)
        N = G.smooth_grid(N, 2)
        N /= np.linalg.norm(N, axis=-1, keepdims=True)
        T = pillow(nu, nv, 0.0050, 0.0022, pu=4, pv=3)
        # four raised knuckle ridges
        uu = np.linspace(0, 1, nu)[:, None]
        T = T + 0.0014 * (0.5 + 0.5 * np.cos(2 * np.pi * (uu - 0.1) / 0.267)) * np.linspace(0.3, 1.0, nv)[None, :]
        Vk, Fk = G.slab_from_grid(P, N, 0.0011, T, round_edge=0.3)
        Vk = push_out_of(Vk, Fk, gco, back, margin=0.0006)
        B.add(f"Glove_Knuckle_{s.upper()}", Vk, Fk, ("rigid", f"hand_{s}"), atlas="glove", zone="knuckle")
        # finger pads on the proximal phalanges (rigid to the finger's first bone)
        for f in FINGERS:
            m = 0.5 * (mcp[f] + pip[f])
            fd = (pip[f] - mcp[f]) / np.linalg.norm(pip[f] - mcp[f])
            q, qn = surface_point(gbv, m + back * 0.05, -back)
            if q is None:
                continue
            side = np.cross(qn, fd)
            side /= np.linalg.norm(side)
            fd2 = np.cross(side, qn)
            Rp = np.column_stack([side, qn, fd2])
            Vq, Fq = G.rbox(0.0125, 0.0040, 0.0155, 0.0017, 1)
            Vq = Vq @ Rp.T + q + qn * 0.0030
            Vq = push_out_of(Vq, Fq, gco, qn, margin=0.0005)
            B.add(f"Glove_Pad_{f}_{s.upper()}", Vq, Fq, ("rigid", f"{f}_01_{s}"), atlas="glove", zone="knuckle")
        # hook-and-loop wrist strap round the glove cuff + its tab
        ax = SC.arm_axis(arm, s)
        L2 = ax.L[2]
        Vw, Fw = band_round_limb(B, f"Glove_Strap_{s.upper()}", gbv, ax, L2 - 0.0445, L2 - 0.0175, -math.pi, math.pi,
                                 f"Soldier_Glove_{s.upper()}", thick=0.0034, clear=0.0009, nu=28, nv=3,
                                 atlas="glove", zone="gstrap", closed=True)
        B.parts[f"Glove_Strap_{s.upper()}"]["atlas"] = "glove"
        wb = S.bvh(Vw, tri_list(Fw))
        A, T_, U, Vv = ax.frame(L2 - 0.028)
        ph = angle_of(ax, L2 - 0.028, back)
        dirv = U * math.cos(ph - 0.5 * (1 if s == "l" else -1)) + Vv * math.sin(ph - 0.5 * (1 if s == "l" else -1))
        q, qn = surface_point(wb, A + dirv * 0.2, -dirv)
        if q is not None:
            tg = np.cross(qn, T_)
            Rt = np.column_stack([tg, qn, T_])
            Vt, Ft = G.rbox(0.026, 0.0035, 0.024, 0.0015, 1)
            Vt = Vt @ Rt.T + q + qn * 0.0022
            B.add(f"Glove_StrapTab_{s.upper()}", Vt, Ft, ("fabric", f"Soldier_Glove_{s.upper()}", None), atlas="glove", zone="gstrap")
        out[s] = {"knuckle_width_mm": round(float(np.linalg.norm(a1 - a0)) * 1000, 1)}
    info["glove_kit"] = out
    return out


def project_uv(ob, src, uv_name="UVMap"):
    """UVs of a part lying on `src` (e.g. the glove kit on the glove): every face takes the affine
    UV map of the src triangle nearest to its centre (seams between faces, none inside a face), so
    the part samples src's texture where it sits (knuckle pads, wrist strap)."""
    me = ob.data
    sme = src.data
    sco = S.co_of(src)
    stri = S.tris_of(sme)
    slt = S.loop_tris(sme)
    suv = S.uv_array(sme, uv_name)
    bv = S.bvh(sco, stri)
    while len(me.uv_layers):
        me.uv_layers.remove(me.uv_layers[0])
    me.uv_layers.new(name=uv_name)
    co = S.co_of(ob)
    lv = np.empty(len(me.loops), np.int64)
    me.loops.foreach_get("vertex_index", lv)
    out = np.zeros((len(me.loops), 2))
    for p in me.polygons:
        c = np.array(p.center)
        r = bv.find_nearest(Vector(tuple(map(float, c))), 0.2)
        if r[0] is None:
            continue
        ti = r[2]
        a, b, cc = sco[stri[ti]]
        ua, ub, uc = suv[slt[ti]]
        e1, e2 = b - a, cc - a
        M = np.array([[e1 @ e1, e1 @ e2], [e1 @ e2, e2 @ e2]])
        Mi = np.linalg.pinv(M)
        for li in range(p.loop_start, p.loop_start + p.loop_total):
            q = co[lv[li]] - a
            w = Mi @ np.array([q @ e1, q @ e2])
            out[li] = ua + w[0] * (ub - ua) + w[1] * (uc - ua)
    me.uv_layers[uv_name].data.foreach_set("uv", out.ravel())
    me.update()
