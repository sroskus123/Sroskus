"""
ivveg -- procedural trees and shrubs for IRON VALLEY (bpy 4.5 / mathutils, headless), map art pass phase 1.

A tree is a set of branches (tapered tubes along polylines, grown by species rules: whorls and drooping tips for the
Norway spruce, a bare trunk with an umbrella crown for the Scots pine, ascending limbs with pendulous twigs for the
birches, envelope-limited limbs for the broadleaves, multi-stem clumps for the shrubs) plus alpha cards carrying the
leaf / needle clusters of the foliage atlas (Tools/environment/vegetation_textures.py).

Every model has three LODs built from the same skeleton:
  LOD0  full branch hierarchy (8 / 5 / 3 sided tubes), all cluster cards               (< 35 m)
  LOD1  trunk + limbs only (5 / 3 sides), ~1/3 of the cards at 1.6x size, crossed      (35 - 90 m)
  LOD2  3-sided trunk + a cloud of far-crown clump cards (broadleaves / shrubs) or three crossed
        whole-tree silhouettes (conifers)                                              (> 90 m, backdrop)

Vertex data (written by Art/Source/Blender/environment/vegetation.py with Tools/level/lib/ivglb.py):
  POSITION, NORMAL (foliage: blended towards the crown's spherical normal, so crowns shade as volumes),
  TEXCOORD_0 (bark: metres around / along, tiling; cards: atlas uv), COLOR_0 (tint),
  _IVVEG u8 x4: x = material (bark layer * 50 + blend * 49, 255 = foliage), y = wind flex (0 base .. 1 tips),
                z = ambient occlusion (ray-cast against the model's own cards and limbs), w = wind phase.
Deterministic: every random draw comes from numpy Generators seeded per model.
"""
import math

import numpy as np

try:
    import bpy  # noqa: F401  (the bpy module provides mathutils)
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
except ImportError:          # the geometry code also runs without Blender (tests); AO then falls back
    Vector = None
    BVHTree = None

BARK = {"spruce": 0, "pine": 1, "birch": 2, "birch_base": 3, "broadleaf": 4}


# ================================================================================================ containers
class Branch:
    def __init__(self, pts, radii, level, bark, phase, flex0=0.0, flex1=1.0, tint=(1.0, 1.0, 1.0), blend=None):
        self.pts = np.asarray(pts, float)
        self.r = np.asarray(radii, float)
        self.level = level
        self.bark = bark
        self.phase = phase
        L = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(self.pts, axis=0), axis=1))])
        self.s = L
        self.length = float(L[-1])
        t = L / max(self.length, 1e-6)
        self.flex = flex0 + (flex1 - flex0) * t ** 1.5
        self.tint = np.asarray(tint, float)
        self.blend = np.zeros(len(self.pts)) if blend is None else np.asarray(blend, float)

    def at(self, t):
        """point, tangent, radius, flex at relative position t along the branch."""
        s = t * self.length
        i = int(np.clip(np.searchsorted(self.s, s) - 1, 0, len(self.pts) - 2))
        f = (s - self.s[i]) / max(self.s[i + 1] - self.s[i], 1e-9)
        p = self.pts[i] + (self.pts[i + 1] - self.pts[i]) * f
        d = self.pts[i + 1] - self.pts[i]
        d = d / max(np.linalg.norm(d), 1e-9)
        return p, d, self.r[i] + (self.r[i + 1] - self.r[i]) * f, self.flex[i] + (self.flex[i + 1] - self.flex[i]) * f


class Card:
    """a textured quad: origin (attachment), x axis (image +u), y axis (image up), size (m), anchor (u, v of the
    origin in the rect, v downwards), atlas rect name."""

    def __init__(self, origin, xaxis, yaxis, w, h, rect, anchor=(0.5, 0.97), tint=(1, 1, 1), flex=0.5, phase=0.0, cross=False):
        self.o = np.asarray(origin, float)
        x = np.asarray(xaxis, float)
        y = np.asarray(yaxis, float)
        self.x = x / max(np.linalg.norm(x), 1e-9)
        y = y - self.x * float(np.dot(y, self.x))
        self.y = y / max(np.linalg.norm(y), 1e-9)
        self.w, self.h = w, h
        self.rect = rect
        self.anchor = anchor
        self.tint = np.asarray(tint, float)
        self.flex = flex
        self.phase = phase
        self.cross = cross

    def corners(self):
        au, av = self.anchor
        out = []
        for (u, v) in ((0, 1), (1, 1), (1, 0), (0, 0)):
            out.append(self.o + self.x * (u - au) * self.w + self.y * (av - v) * self.h)
        return np.array(out)

    def center(self):
        return self.corners().mean(axis=0)


class Model:
    def __init__(self, name, height, crown_radius, crown_center, trunk_radius, kind):
        self.name = name
        self.height = height
        self.crown_radius = crown_radius
        self.crown_center = np.asarray(crown_center, float)
        self.trunk_radius = trunk_radius
        self.kind = kind
        self.branches = []
        self.cards = []


# ================================================================================================ helpers
def unit(v):
    v = np.asarray(v, float)
    return v / max(np.linalg.norm(v), 1e-9)


def perp(d):
    a = np.array([0.0, 0.0, 1.0]) if abs(d[2]) < 0.9 else np.array([1.0, 0.0, 0.0])
    return unit(np.cross(d, a))


def rotate(v, axis, ang):
    axis = unit(axis)
    return v * math.cos(ang) + np.cross(axis, v) * math.sin(ang) + axis * np.dot(axis, v) * (1 - math.cos(ang))


def grow(p0, d0, length, steps, r, gravity=0.0, wander=0.1, up_bend=0.0, droop_end=0.0):
    """polyline from p0 along d0; gravity < 0 bends down, up_bend > 0 bends up; droop_end bends the last third down."""
    pts = [np.asarray(p0, float)]
    d = unit(d0)
    seg = length / steps
    for i in range(steps):
        t = i / steps
        d = d + np.array([0, 0, gravity * seg]) + np.array([0, 0, up_bend * seg]) + r.normal(0, wander * seg, 3)
        if droop_end and t > 0.6:
            d = d + np.array([0, 0, -droop_end * seg])
        d = unit(d)
        pts.append(pts[-1] + d * seg)
    return np.array(pts)


def taper(n, r0, r1, power=1.0):
    t = np.linspace(0, 1, n)
    return r0 + (r1 - r0) * t ** power


def ellipsoid_limit(c, rx, rz, p0, d, maxlen):
    """distance from p0 along d to the surface of the crown ellipsoid (centre c, radii rx, rx, rz)."""
    q = (np.asarray(p0) - c) / np.array([rx, rx, rz])
    v = np.asarray(d) / np.array([rx, rx, rz])
    a = float(np.dot(v, v))
    b = 2 * float(np.dot(q, v))
    cc = float(np.dot(q, q)) - 1
    disc = b * b - 4 * a * cc
    if disc < 0:
        return maxlen * 0.3
    t = (-b + math.sqrt(disc)) / (2 * a)
    return float(np.clip(t, maxlen * 0.15, maxlen))


# ================================================================================================ species
def spruce(name, r, H=22.0, R=3.4, cb=1.2, trunk_r=0.32, card_rects=("spruce_a", "spruce_a")):
    """Norway spruce (R11): straight trunk, whorls every ~0.5 m, conical crown to near the ground, lower limbs
    droop and turn up at the tips, hanging branchlet curtains (sprays + tassels on the cards)."""
    m = Model(name, H, R, (0, 0, cb + (H - cb) * 0.35), trunk_r, "conifer")
    tr = grow((0, 0, -0.1), (0, 0, 1), H, 24, r, wander=0.015)
    m.branches.append(Branch(tr, taper(len(tr), trunk_r, 0.02, 0.9), 0, BARK["spruce"], r.random(), 0.0, 0.25))
    z = cb
    whorl = 0
    while z < H - 0.4:
        f = (z - cb) / (H - cb)                      # 0 at the crown base .. 1 at the top
        Rz = R * (1 - f) ** 0.95 * (0.9 + 0.2 * r.random()) + 0.25
        nb = int(r.integers(4, 6)) if f < 0.9 else 3
        a0 = r.random() * 2 * math.pi
        p_tr = tr[min(len(tr) - 1, int(z / H * (len(tr) - 1)))]
        for k in range(nb):
            az = a0 + k * 2 * math.pi / nb + r.normal(0, 0.25)
            dirh = np.array([math.cos(az), math.sin(az), 0])
            elev = math.radians(35 - 70 * (1 - f) ** 0.8 + r.normal(0, 6))     # top ascending, bottom drooping
            d = unit(dirh * math.cos(elev) + np.array([0, 0, math.sin(elev)]))
            L = Rz * (0.85 + 0.25 * r.random()) / max(math.cos(elev), 0.35)
            steps = max(3, int(L / 0.7))
            pts = grow(p_tr, d, L, steps, r, gravity=-0.08 * (1 - f), up_bend=0.18 * (1 - f) if f < 0.85 else 0, wander=0.06)
            br = Branch(pts, taper(len(pts), trunk_r * 0.22 * (1 - f * 0.7) + 0.02, 0.008), 1, BARK["spruce"], r.random(), 0.15 + 0.2 * f, 0.9)
            m.branches.append(br)
            # the limb in side view (drooping curtains) + a crossed, tilted copy, then flat sprays along it
            dh = unit(np.array([d[0], d[1], 0.0]))
            for tilt in (0.0, 0.9):
                ya = rotate(np.array([0, 0, 1.0]), dh, tilt + r.normal(0, 0.15))
                m.cards.append(Card(p_tr + dh * trunk_r * 0.5, dh, ya, br.length * 1.08, br.length * (0.75 if tilt == 0 else 0.55), "spruce_b",
                                    anchor=(0.02, 0.25), tint=(0.85 + 0.25 * r.random(),) * 3, flex=0.35 + 0.3 * f, phase=br.phase))
            n_cards = max(1, int(br.length / 0.8))
            for j in range(n_cards):
                t = 0.1 + 0.9 * (j + r.random() * 0.6) / n_cards
                p, tg, rad, fl = br.at(t)
                side = perp(tg)
                if side[2] < 0:
                    side = -side
                for s_ in ((-1, 1) if j == n_cards - 1 else ((-1,) if j % 2 else (1,))):
                    xa = unit(tg * 0.6 + side * s_ * 0.8 + np.array([0, 0, -0.15]))
                    side_h = unit(np.cross(np.array([0, 0, 1.0]), xa))
                    up = rotate(side_h, xa, r.normal(0, 0.55))      # sprays lie roughly flat, tilted +-30 deg
                    size = (0.95 + 0.4 * r.random()) * (0.8 + 0.35 * (1 - f))
                    m.cards.append(Card(p, xa, up, size, size, card_rects[int(r.integers(0, 2))], anchor=(0.03, 0.42),
                                        tint=(0.9 + 0.2 * r.random(),) * 3, flex=fl + 0.1, phase=br.phase))
                if f < 0.8 and r.random() < 0.3:
                    # hanging curtain: a spray turned down
                    xa = unit(np.array([0, 0, -1.0]) + tg * 0.25)
                    up = unit(np.cross(tg, xa))
                    size = 0.65 + 0.3 * r.random()
                    m.cards.append(Card(p, xa, up, size, size * 0.8, card_rects[int(r.integers(0, 2))], anchor=(0.03, 0.42),
                                        tint=(0.8 + 0.15 * r.random(),) * 3, flex=fl + 0.2, phase=br.phase))
        z += 0.6 + 0.25 * r.random()
        whorl += 1
    # leader: a few small sprays at the top
    for k in range(4):
        p = tr[-1] - np.array([0, 0, 0.3 * k])
        az = r.random() * 2 * math.pi
        xa = unit(np.array([math.cos(az), math.sin(az), 0.6]))
        m.cards.append(Card(p, xa, np.array([0, 0, 1.0]), 0.6, 0.6, card_rects[0], anchor=(0.03, 0.42), flex=0.3, phase=0.2))
    return m


def pine(name, r, H=20.0, R=3.4, cb=12.0, trunk_r=0.3):
    """Scots pine: tall bare trunk (orange upper bark), irregular umbrella crown of a few long limbs with needle
    tufts at the ends."""
    m = Model(name, H, R, (0, 0, cb + (H - cb) * 0.55), trunk_r, "conifer")
    tr = grow((0, 0, -0.1), (r.normal(0, 0.03), r.normal(0, 0.03), 1), H * 0.97, 22, r, wander=0.03)
    t = np.linspace(0, 1, len(tr))
    orange = np.clip((t - 0.45) / 0.25, 0, 1)
    tint = None
    br = Branch(tr, taper(len(tr), trunk_r, 0.04, 0.8), 0, BARK["pine"], r.random(), 0.0, 0.2)
    br.orange = orange
    m.branches.append(br)
    nl = int(r.integers(9, 13))
    for k in range(nl):
        f = (k + r.random()) / nl
        z = cb + (H - cb) * 0.9 * f
        p_tr = tr[min(len(tr) - 1, int(z / H * (len(tr) - 1)))]
        az = k * 2.4 + r.normal(0, 0.3)
        elev = math.radians(25 - 20 * f + r.normal(0, 10))
        d = unit(np.array([math.cos(az) * math.cos(elev), math.sin(az) * math.cos(elev), math.sin(elev)]))
        L = R * (1.1 - 0.5 * f) * (0.7 + 0.5 * r.random())
        pts = grow(p_tr, d, L, max(4, int(L / 0.4)), r, up_bend=0.12, wander=0.12)
        b = Branch(pts, taper(len(pts), trunk_r * 0.35 * (1 - 0.5 * f) + 0.03, 0.02), 1, BARK["pine"], r.random(), 0.2, 0.9)
        b.orange = np.ones(len(pts))
        m.branches.append(b)
        # sub-limbs + tufts
        for j in range(int(r.integers(2, 5))):
            tt = 0.35 + 0.6 * r.random()
            p, tg, rad, fl = b.at(tt)
            d2 = unit(tg + r.normal(0, 0.6, 3) + np.array([0, 0, 0.3]))
            L2 = L * (0.3 + 0.3 * r.random())
            pts2 = grow(p, d2, L2, 3, r, up_bend=0.2, wander=0.15)
            b2 = Branch(pts2, taper(len(pts2), rad * 0.6, 0.01), 2, BARK["pine"], r.random(), fl, 1.0)
            b2.orange = np.ones(len(pts2))
            m.branches.append(b2)
            for q in (b2.pts[-1], b2.pts[-2]):
                for _ in range(3):
                    az2 = r.random() * 2 * math.pi
                    xa = unit(np.array([math.cos(az2), math.sin(az2), r.normal(0, 0.4)]))
                    m.cards.append(Card(q, xa, np.array([0, 0, 1.0]) + r.normal(0, 0.3, 3), 0.75, 0.75, "pine_tuft", anchor=(0.5, 0.97),
                                        tint=(0.85 + 0.25 * r.random(),) * 3, flex=1.0, phase=b2.phase, cross=True))
        for q in b.pts[len(b.pts) // 2:]:
            for _ in range(2):
                az2 = r.random() * 2 * math.pi
                xa = unit(np.array([math.cos(az2), math.sin(az2), r.normal(0, 0.4)]))
                m.cards.append(Card(q, xa, np.array([0, 0, 1.0]) + r.normal(0, 0.3, 3), 0.8, 0.8, "pine_tuft", anchor=(0.5, 0.97),
                                    tint=(0.85 + 0.25 * r.random(),) * 3, flex=0.9, phase=b.phase))
    return m


def broadleaf(name, r, H, R, cb, trunk_r, card, stems=1, limbs=10, elev=(30, 60), sub=6, pendulous=0.0, bark="broadleaf",
              card_size=0.7, density=1.0, crown_shape=1.0, lean=0.03, autumn=0.0, flatten=1.0):
    """generic broadleaf / birch / shrub: stems -> limbs to the crown ellipsoid -> sub-branches -> cluster cards."""
    zc = cb + (H - cb) * 0.5
    rz = (H - cb) * 0.5
    m = Model(name, H, R, (0, 0, zc), trunk_r, "broadleaf")
    c = np.array([0, 0, zc])
    for s in range(stems):
        if stems > 1:
            az = s * 2 * math.pi / stems + r.random()
            d0 = unit(np.array([math.cos(az) * 0.25, math.sin(az) * 0.25, 1.0]))
            base = np.array([math.cos(az) * trunk_r * 0.4, math.sin(az) * trunk_r * 0.4, -0.1])
            tr_r = trunk_r * (0.75 if stems <= 3 else 0.45)
        else:
            d0 = unit(np.array([r.normal(0, lean), r.normal(0, lean), 1.0]))
            base = np.array([0, 0, -0.1])
            tr_r = trunk_r
        top_h = H * (0.8 + 0.1 * r.random())
        tr = grow(base, d0, top_h, 16, r, wander=0.05)
        blend = None
        if bark == "birch":
            zz = tr[:, 2]
            blend = np.clip(1 - (zz - 0.3) / 2.2, 0, 1) ** 1.3        # black fissured base
        m.branches.append(Branch(tr, taper(len(tr), tr_r, 0.03, 0.85), 0, BARK[bark], r.random(), 0.0, 0.3, blend=blend))
        nl = max(3, int(limbs * (1.0 if stems == 1 else 0.7)))
        for k in range(nl):
            f = (k + r.random()) / nl
            z = cb * (0.7 + 0.3 * r.random()) + (top_h - cb) * 0.9 * f
            i = min(len(tr) - 1, int(z / top_h * (len(tr) - 1)))
            p0 = tr[i]
            az = k * 2.39996 + s * 1.3 + r.normal(0, 0.2)
            e = math.radians(elev[0] + (elev[1] - elev[0]) * f + r.normal(0, 8))
            d = unit(np.array([math.cos(az) * math.cos(e), math.sin(az) * math.cos(e), math.sin(e)]))
            L = ellipsoid_limit(c, R, rz * crown_shape, p0, d, R * 1.6) * (0.8 + 0.2 * r.random())
            pts = grow(p0, d, L, max(3, int(L / 0.8)), r, gravity=-0.05 - pendulous * 0.1, wander=0.12, up_bend=0.03)
            rad0 = tr_r * (0.42 - 0.2 * f) * (0.85 + 0.3 * r.random())
            limb = Branch(pts, taper(len(pts), max(rad0, 0.025), 0.012), 1, BARK[bark] if bark != "birch" else BARK["birch"], r.random(), 0.2 + 0.2 * f, 0.85)
            m.branches.append(limb)
            for j in range(sub):
                tt = 0.25 + 0.72 * (j + r.random()) / sub
                p, tg, rad, fl = limb.at(tt)
                d2 = unit(tg + perp(tg) * r.normal(0, 1.0) + rotate(perp(tg), tg, r.random() * 6.28) * 0.6)
                if pendulous:
                    d2 = unit(d2 + np.array([0, 0, -pendulous * 0.9]))
                L2 = ellipsoid_limit(c, R, rz * crown_shape, p, d2, L * 0.7) * (0.6 + 0.35 * r.random())
                pts2 = grow(p, d2, L2, max(2, int(L2 / 0.6)), r, gravity=-0.1 - pendulous * 0.9, wander=0.15)
                twig = Branch(pts2, taper(len(pts2), max(rad * 0.55, 0.012), 0.005), 2, BARK[bark], r.random(), fl, 1.0)
                m.branches.append(twig)
                # cluster cards along the outer part of the twig
                nc = max(2, int(twig.length / 0.28 * density))
                for q in range(nc):
                    t3 = 0.3 + 0.7 * (q + r.random()) / nc
                    pc, tg3, _, fl3 = twig.at(t3)
                    out = unit(pc - c + np.array([0, 0, 0.3]) + r.normal(0, 0.5, 3))
                    if pendulous > 0.4:
                        # hanging clusters: image top at the twig, card hangs down
                        xa = unit(np.cross(np.array([0, 0, 1.0]), out) + r.normal(0, 0.2, 3))
                        up = unit(np.array([0, 0, 1.0]) + out * 0.3)
                        anchor = (0.5, 0.03)
                    else:
                        # the card faces outwards (crown shell); its twig grows along the shell tangent, mostly upwards
                        nrm = unit(out + r.normal(0, 0.35, 3))
                        tang = np.array([0, 0, 1.0]) - nrm * nrm[2]
                        if np.linalg.norm(tang) < 0.2:
                            tang = tg3 - nrm * np.dot(tg3, nrm)
                        up = rotate(unit(tang), nrm, r.normal(0, 0.9))
                        xa = unit(np.cross(up, nrm))
                        anchor = (0.5, 0.97)
                    sz = card_size * (0.75 + 0.5 * r.random())
                    tint = np.array([1.0, 1.0, 1.0]) * (0.88 + 0.22 * r.random())
                    if autumn and r.random() < autumn:
                        tint = np.array([1.18, 1.02, 0.62])
                    m.cards.append(Card(pc, xa, up, sz, sz, card, anchor=anchor, tint=tint, flex=fl3 + 0.1, phase=twig.phase))
    # flatten crown bottoms (broadleaves shade their own undersides; shrubs sit on the ground)
    return m


def shrub(name, r, H, W, card, stems=7, density=1.0, card_size=0.6):
    """multi-stem shrub (R13 hazel / currant / viburnum): stems fanning from the ground, cards over the dome."""
    m = Model(name, H, W / 2, (0, 0, H * 0.55), 0.03, "shrub")
    c = np.array([0, 0, H * 0.5])
    for s in range(stems):
        az = s * 2.39996 + r.random()
        tilt = 0.25 + 0.45 * r.random()
        d = unit(np.array([math.cos(az) * tilt, math.sin(az) * tilt, 1.0]))
        L = H * (0.8 + 0.3 * r.random())
        pts = grow((math.cos(az) * 0.05, math.sin(az) * 0.05, -0.05), d, L, 6, r, gravity=-0.04, wander=0.12)
        stem = Branch(pts, taper(len(pts), 0.012 + 0.01 * H, 0.004), 1, BARK["broadleaf"], r.random(), 0.05, 0.9)
        m.branches.append(stem)
        nc = max(3, int(L / 0.18 * density))
        for q in range(nc):
            t = 0.25 + 0.75 * (q + r.random()) / nc
            pc, tg, _, fl = stem.at(t)
            out = unit(pc - c + r.normal(0, 0.6, 3) + np.array([0, 0, 0.2]))
            pc = pc + out * 0.1
            tang = np.array([0, 0, 1.0]) - out * out[2]
            if np.linalg.norm(tang) < 0.2:
                tang = tg - out * np.dot(tg, out)
            up = rotate(unit(tang), out, r.normal(0, 0.9))
            xa = unit(np.cross(up, out))
            sz = card_size * (0.7 + 0.6 * r.random())
            m.cards.append(Card(pc, xa, up, sz, sz, card, anchor=(0.5, 0.9), tint=(0.85 + 0.3 * r.random(),) * 3, flex=fl, phase=stem.phase))
    # fill the lower dome so the shrub is dense to the ground (vision-blocking belts, ART_DIRECTION 6.2)
    for q in range(int(stems * 3 * density)):
        az = r.random() * 6.28
        rad = W * 0.35 * math.sqrt(r.random())
        pc = np.array([math.cos(az) * rad, math.sin(az) * rad, H * (0.12 + 0.3 * r.random())])
        out = unit(pc - np.array([0, 0, 0]) + np.array([0, 0, 0.3]))
        tang = unit(np.array([0, 0, 1.0]) - out * out[2] + 1e-3)
        xa = unit(np.cross(tang, out))
        sz = card_size * (0.8 + 0.5 * r.random())
        m.cards.append(Card(pc, xa, tang, sz, sz, card, anchor=(0.5, 0.7), tint=(0.8 + 0.2 * r.random(),) * 3, flex=0.3, phase=r.random()))
    return m


# ================================================================================================ LOD derivation
def lod1(m, r, keep=0.33, scale=1.6):
    """limbs only; a third of the cards, 1.6x larger, each crossed with a second quad."""
    out = Model(m.name + "_LOD1", m.height, m.crown_radius, m.crown_center, m.trunk_radius, m.kind)
    out.branches = []
    for b in m.branches:
        if b.level == 0:
            idx = np.linspace(0, len(b.pts) - 1, min(len(b.pts), 9)).astype(int)
        elif b.level == 1 and m.kind != "conifer":
            idx = np.linspace(0, len(b.pts) - 1, min(len(b.pts), 3)).astype(int)
        else:
            continue
        nb = Branch(b.pts[idx], b.r[idx], b.level, b.bark, b.phase, blend=b.blend[idx])
        nb.flex = b.flex[idx]
        if getattr(b, "orange", None) is not None:
            nb.orange = b.orange[idx]
        out.branches.append(nb)
    for cd in m.cards:
        if r.random() < keep:
            c2 = Card(cd.o, cd.x, cd.y, cd.w * scale, cd.h * scale, cd.rect, cd.anchor, cd.tint, cd.flex, cd.phase, cross=True)
            out.cards.append(c2)
    return out


def lod2(m, r, clump_rect, silhouette_rect=None, n_clumps=12):
    """far LOD: 3-sided trunk + clump cloud (broadleaf / shrub) or three crossed silhouettes (conifer)."""
    out = Model(m.name + "_LOD2", m.height, m.crown_radius, m.crown_center, m.trunk_radius, m.kind)
    tr = m.branches[0]
    if silhouette_rect:
        # whole-tree silhouettes (the card contains the trunk too)
        H = m.height
        W = m.crown_radius * 2.3
        for k in range(3):
            az = k * math.pi / 3
            xa = np.array([math.cos(az), math.sin(az), 0.0])
            out.cards.append(Card((0, 0, -0.1), xa, (0, 0, 1), W, H * 1.02, silhouette_rect, anchor=(0.5, 0.99), flex=0.35, phase=0.3))
        return out
    idx = np.linspace(0, len(tr.pts) - 1, 5).astype(int)
    b = Branch(tr.pts[idx], tr.r[idx], 0, tr.bark, tr.phase, 0.0, 0.3, blend=tr.blend[idx])
    out.branches = [b]
    c = m.crown_center
    R = m.crown_radius
    rz = max(m.height - c[2], 1.0)
    for k in range(n_clumps):
        # points on a slightly flattened ellipsoid shell, bottom sparser
        u = r.random() * 2 - 1
        az = r.random() * 2 * math.pi
        u = u * 0.85 + 0.1
        dirv = np.array([math.sqrt(max(0, 1 - u * u)) * math.cos(az), math.sqrt(max(0, 1 - u * u)) * math.sin(az), u])
        p = c + dirv * np.array([R, R, rz * 0.9]) * (0.55 + 0.25 * r.random())
        up = unit(dirv * 0.6 + np.array([0, 0, 0.8]))
        xa = unit(np.cross(up, rotate(np.array([1.0, 0, 0]), up, r.random() * 6.28)))
        sz = R * (0.85 + 0.35 * r.random())
        out.cards.append(Card(p, xa, up, sz, sz, clump_rect, anchor=(0.5, 0.5), tint=(0.9 + 0.2 * r.random(),) * 3, flex=0.6, phase=r.random(), cross=True))
    return out


# ================================================================================================ meshing
class MeshArrays:
    def __init__(self):
        self.P, self.N, self.UV, self.C, self.V, self.I = [], [], [], [], [], []
        self.n = 0

    def add(self, P, N, UV, C, V, I):
        self.P.append(np.asarray(P, float))
        self.N.append(np.asarray(N, float))
        self.UV.append(np.asarray(UV, float))
        self.C.append(np.asarray(C, float))
        self.V.append(np.asarray(V, float))
        self.I.append(np.asarray(I, np.int64) + self.n)
        self.n += len(P)

    def arrays(self):
        return tuple(np.concatenate(a) for a in (self.P, self.N, self.UV, self.C, self.V, self.I))


def tube_mesh(ma, b, sides, bark_tile=1.0, ao=0.8):
    P = b.pts
    n = len(P)
    T = np.gradient(P, axis=0)
    T = T / np.maximum(np.linalg.norm(T, axis=1, keepdims=True), 1e-9)
    nrm = perp(T[0])
    frames = []
    for i in range(n):
        if i > 0:
            # parallel transport
            v = np.cross(T[i - 1], T[i])
            s = np.linalg.norm(v)
            if s > 1e-8:
                ang = math.asin(min(1.0, s))
                nrm = rotate(nrm, v, ang)
        nrm = unit(nrm - T[i] * np.dot(nrm, T[i]))
        frames.append((nrm, np.cross(T[i], nrm)))
    circ = 2 * math.pi * float(b.r[0])
    reps = max(1, int(round(circ / bark_tile)))
    verts, norms, uvs, cols, vegs = [], [], [], [], []
    orange = getattr(b, "orange", None)
    for i in range(n):
        nn, bb = frames[i]
        for k in range(sides + 1):
            a = 2 * math.pi * k / sides
            dirv = nn * math.cos(a) + bb * math.sin(a)
            verts.append(P[i] + dirv * b.r[i])
            norms.append(dirv)
            uvs.append((reps * k / sides, b.s[i] / bark_tile))
            tint = b.tint
            if orange is not None:
                o = float(orange[i])
                tint = tint * (1 - o) + np.array([1.35, 0.95, 0.72]) * o
            cols.append(tint)
            code = b.bark * 50 + int(round(float(b.blend[i]) * 49))
            vegs.append((code / 255.0, b.flex[i], ao, b.phase))
    I = []
    for i in range(n - 1):
        for k in range(sides):
            a = i * (sides + 1) + k
            c = a + sides + 1
            I += [(a, a + 1, c + 1), (a, c + 1, c)]
    ma.add(verts, norms, uvs, cols, vegs, I)


def card_mesh(ma, cd, rects, atlas_size, crown_c, crown_r, sph=0.65, ao=1.0):
    x, y, w, h = rects[cd.rect]
    W, Hh = atlas_size
    u0, u1 = x / W, (x + w) / W
    v0, v1 = y / Hh, (y + h) / Hh           # glTF uv: v = 0 at the top of the image
    quads = [(cd.x, cd.y)]
    if cd.cross:
        quads.append((unit(np.cross(cd.y, cd.x)), cd.y))
    for (xa, ya) in quads:
        c2 = Card(cd.o, xa, ya, cd.w, cd.h, cd.rect, cd.anchor)
        C4 = c2.corners()
        fn = unit(np.cross(xa, ya))
        verts, norms, uvs, cols, vegs = [], [], [], [], []
        for j, (u, v) in enumerate(((0, 1), (1, 1), (1, 0), (0, 0))):
            p = C4[j]
            sp = unit((p - crown_c) / np.array([crown_r, crown_r, max(crown_r, 1.0)]))
            fnn = fn if np.dot(fn, sp) >= 0 else -fn
            nrm = unit(fnn * (1 - sph) + sp * sph)
            verts.append(p)
            norms.append(nrm)
            uvs.append((u0 + (u1 - u0) * u, v0 + (v1 - v0) * v))
            cols.append(cd.tint)
            # the card's outer corners flex more than its attachment
            fl = cd.flex + (0.15 if v < 0.5 else 0.0)
            vegs.append((1.0, min(1.0, fl), ao, cd.phase))
        ma.add(verts, norms, uvs, cols, vegs, [(0, 1, 2), (0, 2, 3)])


def ray_ao(model, cards_tris, rays=14, maxd=None, strength=0.8):
    """per-card ambient occlusion: fraction of hemisphere rays (around the card's outward direction) that hit the
    model's own cards / limbs (alpha cards count half)."""
    if BVHTree is None:
        return [1.0] * len(model.cards)
    V, F = cards_tris
    bvh = BVHTree.FromPolygons([tuple(map(float, v)) for v in V], [tuple(map(int, f)) for f in F], all_triangles=True)
    g = math.pi * (3 - math.sqrt(5))
    dirs = []
    for k in range(rays):
        rr = math.sqrt((k + 0.5) / rays)
        ph = k * g
        dirs.append((rr * math.cos(ph), rr * math.sin(ph), math.sqrt(max(0.0, 1 - rr * rr))))
    dirs = np.array(dirs)
    maxd = maxd or model.crown_radius * 2.5
    out = []
    c = model.crown_center
    for cd in model.cards:
        p = cd.center()
        nrm = unit(p - c + np.array([0, 0, 0.4]))
        t = perp(nrm)
        b = np.cross(nrm, t)
        D = dirs[:, :1] * t + dirs[:, 1:2] * b + dirs[:, 2:3] * nrm
        o = Vector(tuple(map(float, p + nrm * 0.05)))
        hit = 0.0
        for d in D:
            loc, _, _, dist = bvh.ray_cast(o, Vector(tuple(map(float, d))), maxd)
            if loc is not None:
                hit += 0.6 if dist > 0.3 else 0.3
        occ = hit / rays
        out.append(float(np.clip(1.0 - strength * occ, 0.25, 1.0)))
    return out


def build_mesh(model, rects, atlas_size, sides=(8, 5, 3, 3), ao=True, r=None):
    ma = MeshArrays()
    for b in model.branches:
        s = sides[min(b.level, len(sides) - 1)]
        tube_mesh(ma, b, s, ao=0.75 if b.level == 0 else 0.6)
    card_ao = [1.0] * len(model.cards)
    if ao and model.cards and BVHTree is not None:
        # occluders: the cards (as quads) + limbs (coarse)
        V, F = [], []
        for cd in model.cards:
            C4 = cd.corners()
            base = len(V)
            V += list(C4)
            F += [(base, base + 1, base + 2), (base, base + 2, base + 3)]
        card_ao = ray_ao(model, (np.array(V), F))
    for cd, a in zip(model.cards, card_ao):
        card_mesh(ma, cd, rects, atlas_size, model.crown_center, model.crown_radius, ao=a)
    return ma.arrays()
