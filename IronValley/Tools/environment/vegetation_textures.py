#!/usr/bin/env python3
"""
vegetation_textures.py -- procedural textures for the vegetation of "Kalné Hamry" (IRON VALLEY map art pass,
phase 1): bark sets, the foliage card atlas (leaf / needle clusters, far-crown clumps, conifer silhouettes), the
grass & flower card atlas (R09, R17) and a tiling clipped-hedge leaf surface.  numpy + PIL, deterministic.

Writes Art/Textures/Environment/Vegetation/
  T_Bark_<Name>_{BaseColor,Normal,ORM}.png         tiling (u = around the trunk, 1 m; v = along it, 1 m)
  T_Foliage_Atlas_BaseColor.png (RGBA) + _Normal.png  2048^2, rects in vegetation_textures.json
  T_Grass_Atlas_BaseColor.png (RGBA)                2048 x 1536
  T_Hedge_{BaseColor,Normal}.png                     tiling 1 m
  vegetation_textures.json                           atlas rects (pixels of the 2048 source), card sizes (m)
  Art/Previews/Environment/vegetation_textures_contact.png

Cards: base colour without baked light (sRGB), alpha = coverage, normal = OpenGL tangent space of the card (x = u,
y = image up); leaf normals come from each leaf's own tilt and cupping (not from a height field: no halo spikes).
Usage: python3 Tools/environment/vegetation_textures.py
"""
import json
import math
import os
import sys
import time

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from envlib import F32, ao_from_height, blur, fbm, hexc, lin_to_srgb, normal_from_height, poisson_points, rot, save_png8, smoothstep, to01, voronoi  # noqa: E402

ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
OUT = os.path.join(ROOT, "Art", "Textures", "Environment", "Vegetation")
PREV = os.path.join(ROOT, "Art", "Previews", "Environment")
SEED = 20260928
T0 = time.time()


def log(*a):
    print(f"[{time.time() - T0:6.1f} s]", *a, flush=True)


def rng(k):
    return np.random.default_rng(SEED + k)


# ================================================================================================ card canvas
class Card:
    """painter's-algorithm canvas for a card: linear colour, alpha, tangent normal."""

    def __init__(self, w, h):
        self.w, self.h = w, h
        self.rgb = np.zeros((h, w, 3), F32)
        self.a = np.zeros((h, w), F32)
        self.n = np.zeros((h, w, 3), F32)
        self.n[..., 2] = 1.0

    def region(self, cx, cy, rad):
        x0 = max(0, int(math.floor(cx - rad)))
        y0 = max(0, int(math.floor(cy - rad)))
        x1 = min(self.w, int(math.ceil(cx + rad)) + 1)
        y1 = min(self.h, int(math.ceil(cy + rad)) + 1)
        if x1 <= x0 or y1 <= y0:
            return None
        xs = np.arange(x0, x1)
        ys = np.arange(y0, y1)
        X, Y = np.meshgrid((xs + 0.5 - cx).astype(F32), (ys + 0.5 - cy).astype(F32))
        return slice(y0, y1), slice(x0, x1), X, Y

    def put(self, sl, alpha, rgb, nrm):
        ys, xs = sl
        a = np.clip(alpha, 0, 1)[..., None]
        self.rgb[ys, xs] = self.rgb[ys, xs] * (1 - a) + np.asarray(rgb, F32) * a
        self.n[ys, xs] = self.n[ys, xs] * (1 - a) + np.asarray(nrm, F32) * a
        self.a[ys, xs] = np.maximum(self.a[ys, xs], alpha)


def _norm(n):
    return n / np.maximum(np.linalg.norm(n, axis=-1, keepdims=True), 1e-6)


def draw_stem(card, p0, p1, w0, w1, col, bend=(0.0, 0.0), steps=None):
    """tapered twig / stem from p0 to p1 (image px), quadratic bend offset at the middle; cylinder normals."""
    p0 = np.asarray(p0, float)
    p1 = np.asarray(p1, float)
    mid = (p0 + p1) / 2 + np.asarray(bend, float)
    L = np.linalg.norm(p1 - p0) + np.linalg.norm(np.asarray(bend))
    steps = steps or max(2, int(L / 2.0))
    ts = np.linspace(0, 1, steps + 1)
    pts = [(1 - t) ** 2 * p0 + 2 * (1 - t) * t * mid + t * t * p1 for t in ts]
    for i in range(steps):
        a, b = pts[i], pts[i + 1]
        w = w0 + (w1 - w0) * (i + 0.5) / steps
        c = (a + b) / 2
        reg = card.region(c[0], c[1], np.linalg.norm(b - a) / 2 + w + 1.5)
        if reg is None:
            continue
        ys, xs, X, Y = reg
        d = b - a
        Ld = max(np.linalg.norm(d), 1e-6)
        dirv = d / Ld
        # distance to the segment
        px = X + c[0] - a[0]
        py = Y + c[1] - a[1]
        t = np.clip((px * dirv[0] + py * dirv[1]) / Ld, 0, 1)
        qx = px - t * d[0]
        qy = py - t * d[1]
        dist = np.sqrt(qx * qx + qy * qy)
        alpha = np.clip(w / 2 + 0.5 - dist, 0, 1)
        if not alpha.any():
            continue
        side = (qx * -dirv[1] + qy * dirv[0]) / max(w / 2, 0.5)
        side = np.clip(side, -1, 1)
        nrm = np.stack([-dirv[1] * side * 0.8, dirv[0] * side * 0.8 * -1, np.sqrt(np.clip(1 - 0.64 * side * side, 0.05, 1))], -1)
        shade = (0.8 + 0.2 * (1 - np.abs(side)))[..., None]
        card.put((ys, xs), alpha, np.asarray(col) * shade, _norm(nrm))
    return pts


def draw_leaf(card, base, ang, L, W, col, r, tip=1.5, serrate=0.0, cup=0.5, tilt=None, heart=0.0, vein_dark=0.2, petiole=0.15, spots=0.0):
    """ovate leaf with petiole starting at base (px), direction ang (rad, image frame: +x right, +y down)."""
    cx = base[0] + math.cos(ang) * L * (0.5 + petiole)
    cy = base[1] + math.sin(ang) * L * (0.5 + petiole)
    reg = card.region(cx, cy, L * 0.6 + W + 2)
    if reg is None:
        return
    ys, xs, X, Y = reg
    U, V = rot(X, Y, ang)
    u = U / L + 0.5            # 0 at the base, 1 at the tip
    uu = np.clip(u, 0, 1)
    half = W * 0.5 * np.maximum(np.sin(np.pi * uu ** (1 / tip)), 0.0) ** 0.9
    if heart:
        half = half * (1 + heart * np.clip(1 - uu * 4, 0, 1))
    if serrate:
        half = half * (1 - serrate * (0.5 + 0.5 * np.sin(uu * 55 + r.random() * 6)))
    d = np.abs(V) - half
    inside = (u >= 0) & (u <= 1)
    alpha = np.clip(0.6 - d, 0, 1) * inside
    if not alpha.any():
        return
    rel = np.clip(V / np.maximum(half, 0.5), -1, 1)
    tx, ty = tilt if tilt is not None else (r.normal(0, 0.35), r.normal(0, 0.35))
    # cupping (edges up) + midrib crease, in leaf coords -> image
    nv = rel * cup
    nu = (uu - 0.5) * 0.3
    nx = nu * math.cos(ang) - nv * math.sin(ang) + tx
    ny = nu * math.sin(ang) + nv * math.cos(ang) + ty
    nrm = _norm(np.stack([nx, -ny, np.ones_like(nx)], -1))
    vein = np.clip(1 - np.abs(V) / 0.9, 0, 1) * inside
    side_v = np.clip(1 - np.abs(np.abs(V) - (U + L * 0.5) * 0.55 % (L * 0.14)) / 0.8, 0, 1) * (np.abs(rel) < 0.85) * inside
    c = np.asarray(col, F32)[None, None, :] * (0.88 + 0.16 * (1 - np.abs(rel)))[..., None]
    c = c * (1 - vein_dark * np.maximum(vein, side_v * 0.5))[..., None]
    c = c * (1 + 0.15 * (uu - 0.5))[..., None]
    if spots:
        sp = (np.sin(U * 0.9 + r.random() * 9) * np.sin(V * 1.3 + r.random() * 9)) > (1 - spots)
        c = c * np.where(sp, 0.75, 1.0)[..., None]
    card.put((ys, xs), alpha, c, nrm)
    # petiole
    if petiole > 0:
        draw_stem(card, base, (base[0] + math.cos(ang) * L * petiole * 1.1, base[1] + math.sin(ang) * L * petiole * 1.1), 1.2, 1.0, np.asarray(col) * 0.6)


def draw_needle(card, p, ang, L, W, col):
    reg = card.region(p[0] + math.cos(ang) * L / 2, p[1] + math.sin(ang) * L / 2, L / 2 + W + 1)
    if reg is None:
        return
    ys, xs, X, Y = reg
    U, V = rot(X, Y, ang)
    t = U / L + 0.5
    w = W * 0.5 * np.clip(1 - np.abs(t - 0.45) * 1.6, 0.2, 1)
    alpha = np.clip(w + 0.5 - np.abs(V), 0, 1) * ((t >= 0) & (t <= 1))
    if not alpha.any():
        return
    side = np.clip(V / np.maximum(w, 0.4), -1, 1)
    nx = -side * math.sin(ang) * 0.7
    ny = side * math.cos(ang) * 0.7
    nrm = _norm(np.stack([nx, -ny, np.ones_like(nx)], -1))
    c = np.asarray(col, F32)[None, None, :] * (0.75 + 0.3 * (1 - np.abs(side)))[..., None]
    card.put((ys, xs), alpha, c, nrm)


def pick(r, cols, var=0.08):
    c = hexc(cols[r.integers(len(cols))])
    return np.clip(c * (1 + var * r.standard_normal()), 0, 1)


# ================================================================================================ foliage cards
SPRUCE = ["#2c3a22", "#34432a", "#28361f", "#3a4a2c", "#2f3d25"]
PINE = ["#3a4a2c", "#46573a", "#3f5230", "#4c5c38"]
BIRCH = ["#7d8f3e", "#8a9a44", "#6f8238", "#7a8c3a", "#869640", "#94984a", "#6a7c36", "#b8923a"]
LIME = ["#566f30", "#5e7a36", "#4f6a2c", "#65803a", "#6a7f34"]
MAPLE = ["#4e652e", "#566c32", "#465c29", "#5c7036", "#40562a"]
ASPEN = ["#4e6a30", "#56703a", "#48612c", "#5c7436"]
HAZEL = ["#526630", "#5a6c36", "#4a5e2c", "#606e3a", "#6a6c3a", "#44582a"]
FRUIT = ["#56703a", "#5e7640", "#4e6834"]
TWIG = ["#4a3a2c", "#5a4634", "#3e3228"]
TWIG_BIRCH = ["#3a2e28", "#4a3c34"]


def spruce_spray(w, h, r, droop=0.25):
    """Norway spruce branchlet spray: main axis from the base (left) with alternating side twigs angled forward
    (comb form), every twig needled on both sides; hanging tassels under the side twigs; open gaps between twigs."""
    c = Card(w, h)
    base = (w * 0.03, h * 0.42)
    tip = (w * 0.97, h * (0.42 + droop))
    main = draw_stem(c, base, tip, 3.2, 1.2, pick(r, TWIG), bend=(0, -h * 0.06), steps=60)
    nd = w * 0.028          # needle length (~2.5 cm on a 0.9 m card)

    def needled(pts, scale=1.0):
        for i in range(1, len(pts)):
            a, b = np.array(pts[i - 1]), np.array(pts[i])
            ang = math.atan2(b[1] - a[1], b[0] - a[0])
            for side in (-1, 1):
                for _ in range(2):
                    draw_needle(c, b, ang + side * (0.7 + 0.6 * r.random()), nd * scale * (0.8 + 0.4 * r.random()), 2.3, pick(r, SPRUCE, 0.14))
            draw_needle(c, b, ang + r.normal(0, 0.5), nd * scale * 0.8, 2.3, pick(r, SPRUCE, 0.14))
    k = 0
    for i in range(4, len(main) - 3, 3):
        p = main[i]
        t = i / len(main)
        side = 1 if k % 2 else -1
        k += 1
        a_main = math.atan2(main[i + 1][1] - main[i - 1][1], main[i + 1][0] - main[i - 1][0])
        ang = a_main + side * (0.75 + 0.2 * r.random())
        Ls = w * (0.30 * (1 - t) ** 0.6 + 0.07) * (0.75 + 0.4 * r.random())
        q = (p[0] + math.cos(ang) * Ls, p[1] + math.sin(ang) * Ls + droop * Ls * 0.5)
        sub = draw_stem(c, p, q, 1.8, 0.9, pick(r, TWIG), bend=(0, Ls * 0.08), steps=max(4, int(Ls / 5)))
        needled(sub, 0.9)
        # hanging tassels (secondary twigs droop below the side twig)
        for tpt in sub[2::4]:
            if r.random() < 0.5:
                hang = (tpt[0] + r.normal(0, 4), tpt[1] + Ls * (0.25 + 0.2 * r.random()))
                hs = draw_stem(c, tpt, hang, 1.1, 0.7, pick(r, TWIG), steps=5)
                needled(hs, 0.75)
    needled(main, 1.1)
    return c


def spruce_limb(w, h, r):
    """side view of a whole Norway-spruce limb: the limb sweeps out from the trunk (left, 25 % down), sags and turns
    up at the tip; dense curtains of branchlets hang from it (the characteristic 'comb' spruce of R11)."""
    c = Card(w, h)
    base = (w * 0.02, h * 0.25)
    tip = (w * 0.98, h * 0.3)
    main = draw_stem(c, base, tip, 5.0, 1.6, pick(r, TWIG), bend=(0, h * 0.14), steps=70)
    nd = w * 0.03

    def needled(pts, scale=1.0, dens=2):
        for i in range(1, len(pts)):
            a, b = np.array(pts[i - 1]), np.array(pts[i])
            ang = math.atan2(b[1] - a[1], b[0] - a[0])
            for side in (-1, 1):
                for _ in range(dens):
                    draw_needle(c, b, ang + side * (0.6 + 0.8 * r.random()), nd * scale * (0.75 + 0.45 * r.random()), 3.3, pick(r, SPRUCE, 0.15))
    for i in range(3, len(main) - 1, 2):
        p = main[i]
        t = i / len(main)
        L = h * (0.5 * (1 - t) ** 0.7 + 0.12) * (0.7 + 0.5 * r.random())
        end = (p[0] + w * (0.02 + 0.06 * r.random()), p[1] + L)
        hang = draw_stem(c, p, end, 1.8, 0.9, pick(r, TWIG), bend=(w * 0.03, 0), steps=max(4, int(L / 6)))
        needled(hang, 0.9, 2)
        if r.random() < 0.5:     # short spray up/out from the limb
            q = (p[0] + w * 0.05, p[1] - h * (0.04 + 0.05 * r.random()))
            needled(draw_stem(c, p, q, 1.4, 0.8, pick(r, TWIG), steps=5), 0.8, 2)
    needled(main, 1.1, 3)
    return c


def pine_tuft(w, h, r):
    """pine twig ends with long paired needles in brushy tufts."""
    c = Card(w, h)
    for k in range(5):
        base = (w * (0.3 + 0.4 * r.random()), h * 0.98)
        tipp = (w * (0.15 + 0.7 * r.random()), h * (0.3 + 0.3 * r.random()))
        pts = draw_stem(c, base, tipp, 3.0, 1.6, hexc("#6a4a32"))
        for p in pts[len(pts) // 3:]:
            for _ in range(5):
                ang = -math.pi / 2 + r.normal(0, 0.9)
                draw_needle(c, p, ang, h * (0.16 + 0.06 * r.random()), 1.5, pick(r, PINE, 0.1))
    return c


def leaf_cluster(w, h, r, cols, leaf_len, aspect, count, tip=1.5, serrate=0.0, heart=0.0, hanging=False, twig=TWIG, fruit=None, spots=0.0):
    """branch tip with leaves: 3-5 twigs from the base, leaves along them."""
    c = Card(w, h)
    nt = 4 + int(r.integers(0, 3))
    base = (w * 0.5, h * 0.97) if not hanging else (w * 0.5, h * 0.03)
    tips = []
    for k in range(nt):
        if hanging:
            tp = (w * (0.1 + 0.8 * r.random()), h * (0.7 + 0.28 * r.random()))
        else:
            ang = -math.pi / 2 + (k / max(nt - 1, 1) - 0.5) * 2.0 + r.normal(0, 0.15)
            Lt = h * (0.55 + 0.35 * r.random())
            tp = (base[0] + math.cos(ang) * Lt, base[1] + math.sin(ang) * Lt)
        pts = draw_stem(c, base, tp, 2.6, 1.0, pick(r, twig), bend=(r.normal(0, w * 0.06), r.normal(0, h * 0.04)))
        tips.append(pts)
    per = count // nt
    for j in range(per):
        depth = j / max(per - 1, 1)             # early leaves are behind: darker (self-occlusion inside the cluster)
        for pts in tips:
            p = pts[int(len(pts) * (0.12 + 0.88 * r.random()))]
            if hanging:
                ang = math.pi / 2 + r.normal(0, 0.8)
            else:
                ang = r.random() * 2 * math.pi
            L = leaf_len * (0.7 + 0.5 * r.random())
            col = pick(r, cols, 0.1) * (0.62 + 0.38 * depth)
            draw_leaf(c, p, ang, L, L * aspect, col, r, tip=tip, serrate=serrate, heart=heart, spots=spots)
        if fruit and r.random() < 0.6:
            p = pts[-1]
            rr = leaf_len * 0.28
            reg = c.region(p[0], p[1] + rr, rr + 2)
            if reg is not None:
                ys, xs, X, Y = reg
                e = np.sqrt(X * X + Y * Y) / rr
                al = np.clip((1 - e) * rr, 0, 1)
                nrm = _norm(np.stack([X / rr, -Y / rr, np.sqrt(np.clip(1 - e * e, 0.05, 1))], -1))
                col = hexc(fruit) * (0.85 + 0.25 * np.clip(-(X + Y) / rr, -1, 1))[..., None]
                c.put((ys, xs), al, col, nrm)
    return c


def clump(w, h, r, cols, leaf_len, aspect, count, tip=1.5, dark_core=0.55):
    """far-crown clump: an irregular blob densely filled with small leaves, darker towards the middle (self-shadow
    inside the crown is part of the look at 90+ m), ragged edge."""
    c = Card(w, h)
    yy, xx = np.mgrid[0:h, 0:w]
    cx, cy = w / 2, h / 2
    shape_n = fbm(max(w, h), int(r.integers(0, 10000)), lo=2, hi=12)[:h, :w]
    rr = np.hypot((xx - cx) / (w * 0.46), (yy - cy) / (h * 0.46)) + 0.18 * shape_n
    for k in range(count):
        ang = r.random() * 2 * math.pi
        rad = math.sqrt(r.random()) * 0.95
        px = cx + math.cos(ang) * rad * w * 0.44
        py = cy + math.sin(ang) * rad * h * 0.44
        if rr[min(h - 1, int(py)), min(w - 1, int(px))] > 1.0:
            continue
        L = leaf_len * (0.7 + 0.5 * r.random())
        col = pick(r, cols, 0.1) * (dark_core + (1 - dark_core) * rad)
        draw_leaf(c, (px, py), r.random() * 2 * math.pi, L, L * aspect, col, r, tip=tip, petiole=0.0, vein_dark=0.1)
    return c


def conifer_silhouette(w, h, r, cols, pine=False):
    """whole conifer (LOD2 crossed cards): irregular tiers of drooping branches (spruce) or an umbrella crown of
    needle clumps on a tall bare orange-topped trunk (pine)."""
    c = Card(w, h)
    cx = w / 2
    if pine:
        draw_stem(c, (cx, h * 0.99), (cx + w * 0.02, h * 0.12), w * 0.06, w * 0.025, hexc("#8a5a3c"))
        for k in range(9):
            ang = -math.pi / 2 + r.normal(0, 0.9)
            L = w * (0.2 + 0.25 * r.random())
            y0 = h * (0.18 + 0.2 * r.random())
            draw_stem(c, (cx, y0), (cx + math.cos(ang) * L * 1.2 + r.normal(0, 8), y0 - abs(math.sin(ang)) * L * 0.4), 3.0, 1.5, hexc("#7a5238"))
        for k in range(260):
            ang = r.random() * 2 * math.pi
            rad = math.sqrt(r.random())
            px = cx + math.cos(ang) * rad * w * 0.45
            py = h * 0.22 + math.sin(ang) * rad * h * 0.13 + r.normal(0, 6)
            shade = 0.55 + 0.45 * (1 - rad * 0.5) * (0.6 + 0.4 * r.random())
            for _ in range(14):
                draw_needle(c, (px, py), -math.pi / 2 + r.normal(0, 1.2), h * 0.022, 2.2, pick(r, PINE, 0.12) * shade)
        return c
    draw_stem(c, (cx, h * 0.99), (cx, h * 0.01), w * 0.045, w * 0.01, hexc("#5e5448"))
    y = h * 0.02
    while y < h * 0.95:
        f = y / h                         # 0 top .. 1 bottom
        half = w * (0.04 + 0.46 * f ** 0.85) * (0.8 + 0.35 * r.random())
        for side in (-1, 1):
            if r.random() < 0.12 and f > 0.3:
                continue                  # gaps: a missing branch here and there
            L = half * (0.75 + 0.3 * r.random())
            end = (cx + side * L, y + L * (0.18 + 0.25 * f) + r.normal(0, 3))
            pts = draw_stem(c, (cx, y), end, 2.4, 1.0, pick(r, TWIG), bend=(0, -L * (0.12 + 0.1 * r.random())))
            for p in pts[1:]:
                hang = 1 + 3 * abs(p[0] - cx) / max(half, 1)
                for _ in range(7):
                    draw_needle(c, (p[0] + r.normal(0, 2), p[1] + abs(r.normal(0, 3.5 * hang))), math.pi / 2 + r.normal(0, 0.9), h * 0.013, 1.7,
                                pick(r, cols, 0.14) * (0.6 + 0.4 * abs(p[0] - cx) / max(half, 1)))
        y += h * (0.018 + 0.02 * r.random())
    return c


# ================================================================================================ grass cards
GRASS_G = ["#5f6d2e", "#6e7c37", "#7c8b40", "#88944a", "#687532", "#566429"]
GRASS_D = ["#a39461", "#b1a26c", "#958a58", "#bfae78", "#8b7d4c"]


def grass_blade_card(c, base, height, lean, width, col, dry_tip=0.3, r=None):
    """a curved grass blade from the base up: tapered strip with a green -> dry tip gradient; normal ~ up."""
    steps = max(4, int(height / 3))
    x, y = base
    ang = -math.pi / 2 + lean
    curv = r.normal(0, 0.012)
    pts = []
    for i in range(steps + 1):
        pts.append((x, y))
        x += math.cos(ang) * height / steps
        y += math.sin(ang) * height / steps
        ang += curv + (lean * 0.03)
    for i in range(steps):
        t = (i + 0.5) / steps
        a, b = np.array(pts[i]), np.array(pts[i + 1])
        w = width * (1 - t) ** 0.8 + 0.6
        cc = (a + b) / 2
        reg = c.region(cc[0], cc[1], np.linalg.norm(b - a) / 2 + w + 1)
        if reg is None:
            continue
        ys, xs, X, Y = reg
        d = b - a
        Ld = max(np.linalg.norm(d), 1e-6)
        dv = d / Ld
        px = X + cc[0] - a[0]
        py = Y + cc[1] - a[1]
        tt = np.clip((px * dv[0] + py * dv[1]) / Ld, 0, 1)
        qx, qy = px - tt * d[0], py - tt * d[1]
        dist = np.sqrt(qx * qx + qy * qy)
        al = np.clip(w / 2 + 0.5 - dist, 0, 1)
        if not al.any():
            continue
        dry = smoothstep(1 - dry_tip, 1.0, t)
        colt = np.asarray(col) * (1 - dry) + hexc("#b3a16a") * dry
        colt = colt * (0.7 + 0.35 * t)
        c.put((ys, xs), al, colt, np.array([0, 0, 1.0]))


def grass_card(w, h, r, count, height_frac, dry=0.25, width=6.5, spread=0.35):
    c = Card(w, h)
    for _ in range(count):
        bx = w * (0.5 + r.normal(0, 0.16))
        H = h * height_frac * (0.45 + 0.55 * r.random())
        lean = r.normal(0, spread)
        cols = GRASS_D if r.random() < dry else GRASS_G
        grass_blade_card(c, (bx, h - 1), H, lean, width * (0.7 + 0.6 * r.random()), pick(r, cols, 0.1), dry_tip=0.25 + 0.3 * r.random(), r=r)
    return c


def seed_head(c, p, r, length, col):
    """panicle of reed / hair grass: a thin stem tip with many small spikelets."""
    for i in range(26):
        t = i / 26
        q = (p[0] + r.normal(0, 4) * t, p[1] + length * t)
        for _ in range(4):
            ang = math.pi / 2 + r.normal(0, 0.6)
            draw_needle(c, q, ang, length * 0.16 * (1 - 0.5 * t), 2.2, col * (0.85 + 0.3 * r.random()))


def tall_grass_card(w, h, r):
    c = grass_card(w, h, r, 70, 0.62, dry=0.35, width=6.5, spread=0.25)
    for _ in range(9):
        bx = w * (0.5 + r.normal(0, 0.14))
        top = (bx + r.normal(0, w * 0.06), h * (0.04 + 0.12 * r.random()))
        draw_stem(c, (bx, h - 1), top, 1.8, 1.2, hexc("#8e8a55"), bend=(r.normal(0, 6), 0))
        seed_head(c, top, r, h * 0.2, hexc("#a8956a"))
    return c


def forb_card(w, h, r):
    """cinquefoil / wild strawberry leaves among short grass (R09 c)."""
    c = grass_card(w, h, r, 40, 0.55, dry=0.2)
    for _ in range(9):
        bx = w * (0.5 + r.normal(0, 0.18))
        top = (bx + r.normal(0, w * 0.1), h * (0.35 + 0.35 * r.random()))
        draw_stem(c, (bx, h - 1), top, 1.6, 1.2, hexc("#55682c"))
        n = 3 if r.random() < 0.5 else 5
        a0 = -math.pi / 2
        for k in range(n):
            ang = a0 + (k - (n - 1) / 2) * (1.1 if n == 3 else 0.62)
            draw_leaf(c, top, ang, w * 0.09, w * 0.05, pick(r, ["#4d6a2c", "#557232", "#466228"], 0.1), r, tip=1.2, serrate=0.25, petiole=0.0)
    return c


def flower_card(w, h, r, kind):
    c = grass_card(w, h, r, 35, 0.6 if kind == "chamomile" else 0.45, dry=0.3)
    if kind == "yarrow":
        for _ in range(6):
            bx = w * (0.5 + r.normal(0, 0.14))
            top = (bx + r.normal(0, w * 0.05), h * (0.06 + 0.12 * r.random()))
            draw_stem(c, (bx, h - 1), top, 2.0, 1.4, hexc("#6f7a4a"))
            # feathery leaves along the stem
            for t in np.linspace(0.4, 0.9, 4):
                p = (bx + (top[0] - bx) * (1 - t), top[1] + (h - top[1]) * t)
                for s in (-1, 1):
                    for k in range(6):
                        draw_needle(c, (p[0] + s * k * 2.2, p[1] - k * 1.2), -math.pi / 2 + s * 1.2, w * 0.03, 1.5, hexc("#6d7d48") * (0.9 + 0.2 * r.random()))
            # flat umbel of tiny white flowers
            for _ in range(60):
                q = (top[0] + r.normal(0, w * 0.045), top[1] + abs(r.normal(0, h * 0.008)))
                reg = c.region(q[0], q[1], 3)
                if reg is None:
                    continue
                ys, xs, X, Y = reg
                e = np.sqrt(X * X + Y * Y) / 1.8
                c.put((ys, xs), np.clip((1 - e) * 2, 0, 1), hexc("#e8e4d6") * (0.85 + 0.2 * r.random()), np.array([0, 0.2, 1.0]))
    else:
        for _ in range(9):
            bx = w * (0.5 + r.normal(0, 0.16))
            top = (bx + r.normal(0, w * 0.1), h * (0.08 + 0.3 * r.random()))
            draw_stem(c, (bx, h - 1), top, 1.4, 1.0, hexc("#667a3c"), bend=(r.normal(0, 5), 0))
            rad = w * (0.022 + 0.01 * r.random())
            for k in range(14):
                ang = k / 14 * 2 * math.pi + r.random() * 0.2
                draw_leaf(c, top, ang, rad * 1.6, rad * 0.6, hexc("#f2efe6") * (0.9 + 0.1 * r.random()), r, tip=1.0, petiole=0.0, vein_dark=0.05, cup=0.2, tilt=(0, 0.3))
            reg = c.region(top[0], top[1], rad * 0.55 + 2)
            if reg is not None:
                ys, xs, X, Y = reg
                e = np.sqrt(X * X + Y * Y) / (rad * 0.5)
                nrm = _norm(np.stack([X / (rad * 0.5), -Y / (rad * 0.5), np.ones_like(X) * 1.5], -1))
                c.put((ys, xs), np.clip((1 - e) * 3, 0, 1), hexc("#e2c43a") * (0.9 + 0.2 * r.random()), nrm)
    return c


def nettle_card(w, h, r):
    """ruderal edge along walls: nettle / dock stems with opposite serrated leaves."""
    c = grass_card(w, h, r, 25, 0.5, dry=0.4)
    for _ in range(5):
        bx = w * (0.5 + r.normal(0, 0.15))
        top = (bx + r.normal(0, w * 0.04), h * (0.08 + 0.25 * r.random()))
        pts = draw_stem(c, (bx, h - 1), top, 2.4, 1.2, hexc("#4f6030"))
        nodes = pts[3::max(2, len(pts) // 6)]
        for i, p in enumerate(nodes):
            t = 1 - i / max(len(nodes), 1)        # larger leaves low on the stem
            for side in (-1, 1):
                ang = (0.35 if side > 0 else math.pi - 0.35) + r.normal(0, 0.15)
                L = w * (0.05 + 0.07 * t)
                draw_leaf(c, p, ang, L, L * 0.65, pick(r, ["#3f5a26", "#476330", "#3a5222"], 0.1), r, tip=1.4, serrate=0.3, heart=0.25, petiole=0.12)
    return c


# ================================================================================================ bark
def bark_set(name, n, r, kind):
    tile_u, tile_v = 1.0, 1.0
    px = tile_u / n
    if kind == "spruce":
        pts = poisson_points(n, 420, SEED + 11)
        pts[:, 1] *= 1.0
        d1, d2, idx, edge = voronoi(n, pts, (3 * fbm(n, SEED + 12, lo=2, hi=40), 8 * fbm(n, SEED + 13, lo=2, hi=20)))
        plate = np.clip(edge / 4.0, 0, 1) ** 0.5
        h = 0.3 + 0.6 * plate + 0.1 * fbm(n, SEED + 14, lo=30, hi=300)
        base = hexc("#5e5448")
        var = np.random.default_rng(SEED + 15).random(len(pts))[idx]
        col = base * (0.8 + 0.35 * var)[..., None] * (0.7 + 0.3 * plate)[..., None]
        lich = smoothstep(0.8, 1.8, fbm(n, SEED + 16, lo=3, hi=30))
        col = col * (1 - 0.4 * lich[..., None]) + hexc("#7a8068") * 0.4 * lich[..., None]
        rough = 0.85 + 0.1 * (1 - plate)
    elif kind == "pine":
        pts = poisson_points(n, 90, SEED + 21)
        d1, d2, idx, edge = voronoi(n, pts, (4 * fbm(n, SEED + 22, lo=2, hi=20), 14 * fbm(n, SEED + 23, lo=2, hi=12)))
        plate = np.clip(edge / 7.0, 0, 1) ** 0.4
        h = 0.2 + 0.7 * plate + 0.1 * fbm(n, SEED + 24, lo=40, hi=300)
        var = np.random.default_rng(SEED + 25).random(len(pts))[idx]
        col = hexc("#6e4e3a") * (0.8 + 0.35 * var)[..., None] * (0.55 + 0.45 * plate)[..., None]
        flakes = smoothstep(0.5, 1.5, fbm(n, SEED + 26, lo=20, hi=200))
        col = col * (1 - 0.5 * flakes[..., None] * plate[..., None]) + hexc("#a8663e") * 0.5 * flakes[..., None] * plate[..., None]
        rough = 0.82 + 0.12 * (1 - plate)
    elif kind in ("birch", "birch_base"):
        yy, xx = np.mgrid[0:n, 0:n]
        base_n = fbm(n, SEED + 31, lo=2, hi=60, aniso=(1.0, 0.3))
        white = hexc("#d8d4c8") * (0.92 + 0.08 * base_n[..., None])
        # horizontal lenticels (dark dashes)
        lent = fbm(n, SEED + 32, lo=20, hi=200, aniso=(0.12, 1.0))
        dashes = smoothstep(1.6, 2.4, lent)
        # dark diamond cracks / patches
        cr = smoothstep(1.2, 2.2, fbm(n, SEED + 33, lo=3, hi=30, aniso=(0.6, 1.0)))
        peel = smoothstep(1.0, 1.8, fbm(n, SEED + 34, lo=4, hi=40, aniso=(0.3, 1.0)))
        col = white * (1 - 0.8 * dashes[..., None]) + hexc("#2e2b28") * 0.8 * dashes[..., None]
        col = col * (1 - 0.85 * cr[..., None]) + hexc("#2e2b28") * 0.85 * cr[..., None]
        col = col * (1 - 0.4 * peel[..., None]) + hexc("#c7a58a") * 0.4 * peel[..., None]
        h = 0.6 - 0.35 * dashes - 0.5 * cr + 0.05 * base_n
        rough = 0.6 + 0.3 * cr + 0.1 * dashes
        if kind == "birch_base":
            fiss = fbm(n, SEED + 35, lo=3, hi=80, aniso=(1.0, 0.15))
            f = smoothstep(-0.6, 0.6, fiss)
            col = hexc("#2e2b28") * (0.9 + 0.3 * f[..., None])
            wp = smoothstep(0.9, 1.6, fbm(n, SEED + 36, lo=3, hi=20, aniso=(1.0, 0.4)))
            col = col * (1 - wp[..., None]) + hexc("#bdb7aa") * wp[..., None]
            h = 0.2 + 0.7 * f
            rough = np.full((n, n), 0.9, F32)
    else:   # broadleaf: grey with vertical fissures (lime / maple / oak-ish)
        fiss = fbm(n, SEED + 41, lo=4, hi=80, aniso=(1.0, 0.12))
        ridge = 1 - np.abs(fiss) / 2.5
        ridge = np.clip(ridge, 0, 1) ** 2
        h = 0.2 + 0.7 * ridge + 0.1 * fbm(n, SEED + 42, lo=40, hi=300)
        col = hexc("#6b665c") * (0.65 + 0.45 * ridge[..., None]) * (0.95 + 0.1 * fbm(n, SEED + 43, lo=2, hi=20)[..., None])
        moss = smoothstep(0.9, 1.8, fbm(n, SEED + 44, lo=2, hi=20)) * (1 - ridge)
        col = col * (1 - 0.5 * moss[..., None]) + hexc("#4f5a30") * 0.5 * moss[..., None]
        rough = 0.85 + 0.1 * (1 - ridge)
    h = np.clip(h, 0, 1).astype(F32)
    nrm = normal_from_height(h, 0.02, tile_u, 1.0)
    ao = ao_from_height(h, 0.02, tile_u, radii_m=(0.004, 0.012, 0.03))
    return col.astype(F32), nrm, ao, np.clip(rough, 0, 1).astype(F32)


def hedge_tile(n, r):
    """clipped hedge / shrub core surface: dense small leaves over dark depth."""
    tile = 1.0
    c = Card(n, n)
    c.rgb[:] = hexc("#1c2414")
    c.a[:] = 1
    leaf_px = n * 0.045
    pts = poisson_points(n, int(n * n / (leaf_px * leaf_px) * 1.6), SEED + 51)
    cols = ["#4c6531", "#56703a", "#445c2c", "#5f7a3c", "#3e5428"]
    for (px_, py_) in pts:
        for dx in (0, -n, n):
            for dy in (0, -n, n):
                qx, qy = px_ + dx, py_ + dy
                if -leaf_px * 2 < qx < n + leaf_px * 2 and -leaf_px * 2 < qy < n + leaf_px * 2:
                    col = pick(r, cols, 0.12) * (0.6 + 0.5 * r.random())
                    draw_leaf(c, (qx, qy), r.random() * 2 * math.pi, leaf_px * (0.8 + 0.5 * r.random()), leaf_px * 0.6, col, r, tip=1.3, petiole=0.0, vein_dark=0.12)
    return c


# ================================================================================================ atlases
FOLIAGE_RECTS = {
    # name: (x, y, w, h) in the 2048 source; card sizes in metres
    "spruce_a": (0, 0, 512, 512), "spruce_b": (512, 0, 512, 512), "pine_tuft": (1024, 0, 512, 512), "spruce_sil": (1536, 0, 512, 1024),
    "birch": (0, 512, 512, 512), "lime": (512, 512, 512, 512), "maple": (1024, 512, 512, 512),
    "aspen": (0, 1024, 512, 512), "hazel": (512, 1024, 512, 512), "fruit": (1024, 1024, 512, 512), "pine_sil": (1536, 1024, 512, 1024),
    "clump_green": (0, 1536, 512, 512), "clump_birch": (512, 1536, 512, 512), "clump_dark": (1024, 1536, 512, 512),
}
FOLIAGE_SIZE_M = {"spruce_a": 0.9, "spruce_b": 0.9, "pine_tuft": 0.7, "spruce_sil": 22.0, "birch": 0.55, "lime": 0.7, "maple": 0.7,
                  "aspen": 0.6, "hazel": 0.7, "fruit": 0.6, "pine_sil": 20.0, "clump_green": 2.6, "clump_birch": 2.4, "clump_dark": 2.6}
GRASS_RECTS = {
    "low": (0, 0, 512, 512), "low_dry": (512, 0, 512, 512), "forb": (1024, 0, 512, 512), "chamomile": (1536, 0, 512, 512),
    "tall_a": (0, 512, 512, 1024), "tall_b": (512, 512, 512, 1024), "yarrow": (1024, 512, 512, 1024), "nettle": (1536, 512, 512, 1024),
}
GRASS_HEIGHT_M = {"low": 0.4, "low_dry": 0.4, "forb": 0.5, "chamomile": 0.5, "tall_a": 1.0, "tall_b": 0.9, "yarrow": 0.7, "nettle": 0.8}


def foliage_atlas():
    r = rng(1)
    A = np.zeros((2048, 2048, 4), F32)
    N = np.zeros((2048, 2048, 3), F32)
    N[..., 2] = 1
    makers = {
        "spruce_a": lambda w, h: spruce_spray(w, h, rng(10), 0.22),
        "spruce_b": lambda w, h: spruce_limb(w, h, rng(11)),
        "pine_tuft": lambda w, h: pine_tuft(w, h, rng(12)),
        "spruce_sil": lambda w, h: conifer_silhouette(w, h, rng(13), SPRUCE),
        "birch": lambda w, h: leaf_cluster(w, h, rng(14), BIRCH, w * 0.085, 0.72, 280, tip=1.2, serrate=0.12, hanging=True, twig=TWIG_BIRCH),
        "lime": lambda w, h: leaf_cluster(w, h, rng(15), LIME, w * 0.12, 0.9, 160, tip=1.6, serrate=0.08, heart=0.35),
        "maple": lambda w, h: leaf_cluster(w, h, rng(16), MAPLE, w * 0.12, 0.95, 150, tip=1.1, serrate=0.1),
        "aspen": lambda w, h: leaf_cluster(w, h, rng(17), ASPEN, w * 0.095, 0.95, 200, tip=0.9, serrate=0.1),
        "hazel": lambda w, h: leaf_cluster(w, h, rng(18), HAZEL, w * 0.13, 0.9, 140, tip=1.1, serrate=0.18, heart=0.2),
        "fruit": lambda w, h: leaf_cluster(w, h, rng(19), FRUIT, w * 0.1, 0.55, 180, tip=1.6, serrate=0.1, fruit="#b04a2a"),
        "pine_sil": lambda w, h: conifer_silhouette(w, h, rng(20), PINE, pine=True),
        "clump_green": lambda w, h: clump(w, h, rng(21), LIME + MAPLE, w * 0.07, 0.85, 1700),
        "clump_birch": lambda w, h: clump(w, h, rng(22), BIRCH, w * 0.055, 0.75, 2000),
        "clump_dark": lambda w, h: clump(w, h, rng(23), ASPEN + ["#3f5528"], w * 0.07, 0.9, 1700),
    }
    for name, (x, y, w, h) in FOLIAGE_RECTS.items():
        c = makers[name](w, h)
        A[y:y + h, x:x + w, :3] = c.rgb
        A[y:y + h, x:x + w, 3] = c.a
        N[y:y + h, x:x + w] = c.n
        log(f"foliage card {name}: coverage {c.a.mean() * 100:.0f} %")
    return A, N


def grass_atlas():
    A = np.zeros((1536, 2048, 4), F32)
    makers = {
        "low": lambda w, h: grass_card(w, h, rng(30), 230, 0.9, dry=0.22, spread=0.42),
        "low_dry": lambda w, h: grass_card(w, h, rng(31), 210, 0.85, dry=0.6, spread=0.42),
        "forb": lambda w, h: forb_card(w, h, rng(32)),
        "chamomile": lambda w, h: flower_card(w, h, rng(33), "chamomile"),
        "tall_a": lambda w, h: tall_grass_card(w, h, rng(34)),
        "tall_b": lambda w, h: tall_grass_card(w, h, rng(35)),
        "yarrow": lambda w, h: flower_card(w, h, rng(36), "yarrow"),
        "nettle": lambda w, h: nettle_card(w, h, rng(37)),
    }
    for name, (x, y, w, h) in GRASS_RECTS.items():
        c = makers[name](w, h)
        A[y:y + h, x:x + w, :3] = c.rgb
        A[y:y + h, x:x + w, 3] = c.a
        log(f"grass card {name}: coverage {c.a.mean() * 100:.0f} %")
    return A


def dilate_rgb(A, iters=8):
    """bleed colour into transparent texels (no dark fringes when alpha-tested / mip-mapped)."""
    rgb = A[..., :3].copy()
    a = (A[..., 3] > 0.02).astype(F32)
    for _ in range(iters):
        m = ndi_max(a)
        s = np.zeros_like(rgb)
        cnt = np.zeros(a.shape, F32)
        for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, 1), (-1, 1), (1, -1)):
            ar = np.roll(np.roll(a, dy, 0), dx, 1)
            s += np.roll(np.roll(rgb, dy, 0), dx, 1) * ar[..., None]
            cnt += ar
        fill = (a == 0) & (cnt > 0)
        rgb[fill] = s[fill] / cnt[fill][..., None]
        a = np.maximum(a, (cnt > 0).astype(F32))
    out = A.copy()
    out[..., :3] = rgb
    return out


def ndi_max(a):
    from scipy import ndimage
    return ndimage.maximum_filter(a, 3)


def main():
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(PREV, exist_ok=True)
    meta = {"_comment": "GENERATED by Tools/environment/vegetation_textures.py", "author": "generated in this project (IRON VALLEY)",
            "license": "project-owned", "seed": SEED, "bark": {}, "foliage": {}, "grass": {}}
    # bark
    for name, kind in (("Spruce", "spruce"), ("Pine", "pine"), ("Birch", "birch"), ("BirchBase", "birch_base"), ("Broadleaf", "broadleaf")):
        col, nrm, ao, rough = bark_set(name, 512, rng(2), kind)
        save_png8(os.path.join(OUT, f"T_Bark_{name}_BaseColor.png"), lin_to_srgb(col))
        save_png8(os.path.join(OUT, f"T_Bark_{name}_Normal.png"), nrm * 0.5 + 0.5)
        save_png8(os.path.join(OUT, f"T_Bark_{name}_ORM.png"), np.stack([ao, rough, np.zeros_like(ao)], -1))
        meta["bark"][name] = {"tile_m": [1.0, 1.0], "maps": [f"T_Bark_{name}_BaseColor.png", f"T_Bark_{name}_Normal.png", f"T_Bark_{name}_ORM.png"]}
        log(f"bark {name}")
    # hedge surface
    hc = hedge_tile(512, rng(3))
    save_png8(os.path.join(OUT, "T_Hedge_BaseColor.png"), lin_to_srgb(hc.rgb))
    save_png8(os.path.join(OUT, "T_Hedge_Normal.png"), hc.n * 0.5 + 0.5)
    meta["hedge"] = {"tile_m": 1.0, "maps": ["T_Hedge_BaseColor.png", "T_Hedge_Normal.png"]}
    log("hedge")
    # foliage atlas
    A, N = foliage_atlas()
    A = dilate_rgb(A)
    rgba = np.concatenate([lin_to_srgb(A[..., :3]), A[..., 3:4]], -1)
    save_png8(os.path.join(OUT, "T_Foliage_Atlas_BaseColor.png"), rgba, "RGBA")
    save_png8(os.path.join(OUT, "T_Foliage_Atlas_Normal.png"), N * 0.5 + 0.5)
    meta["foliage"] = {"size": [2048, 2048], "rects": FOLIAGE_RECTS, "card_m": FOLIAGE_SIZE_M,
                       "maps": ["T_Foliage_Atlas_BaseColor.png", "T_Foliage_Atlas_Normal.png"]}
    # grass atlas
    G = dilate_rgb(grass_atlas(), iters=3)
    rgba = np.concatenate([lin_to_srgb(G[..., :3]), G[..., 3:4]], -1)
    save_png8(os.path.join(OUT, "T_Grass_Atlas_BaseColor.png"), rgba, "RGBA")
    meta["grass"] = {"size": [2048, 1536], "rects": GRASS_RECTS, "height_m": GRASS_HEIGHT_M, "maps": ["T_Grass_Atlas_BaseColor.png"]}
    with open(os.path.join(OUT, "vegetation_textures.json"), "w") as f:
        json.dump(meta, f, indent=1)
        f.write("\n")
    # contact sheet: foliage atlas over grey + grass atlas over grey
    def over(rgba_path, size):
        im = Image.open(rgba_path).convert("RGBA").resize(size, Image.LANCZOS)
        bg = Image.new("RGBA", size, (128, 128, 128, 255))
        bg.alpha_composite(im)
        return bg.convert("RGB")
    f1 = over(os.path.join(OUT, "T_Foliage_Atlas_BaseColor.png"), (1024, 1024))
    g1 = over(os.path.join(OUT, "T_Grass_Atlas_BaseColor.png"), (1024, 768))
    sheet = Image.new("RGB", (2048, 1024), (40, 40, 40))
    sheet.paste(f1, (0, 0))
    sheet.paste(g1, (1024, 0))
    sheet.save(os.path.join(PREV, "vegetation_textures_contact.png"))
    log("done")


if __name__ == "__main__":
    main()
