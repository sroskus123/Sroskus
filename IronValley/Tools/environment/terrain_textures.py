#!/usr/bin/env python3
"""
terrain_textures.py -- procedural, seamlessly tiling PBR detail sets for the terrain splat of "Kalné Hamry"
(IRON VALLEY map art pass, phase 1).  numpy + scipy only, deterministic (fixed seeds).

Writes  Art/Textures/Environment/Terrain/<Set>/T_<Set>_{BaseColor,Normal,Normal_DX,ORM,Height}.png + <Set>.json
        Art/Textures/Environment/Terrain/terrain_layers.json   (layer order of the runtime texture array)
        Art/Previews/Environment/terrain_sets_contact.png       (review sheet: albedo 2x2 + lit 2x2 per set)

Height is on a COMMON scale across sets (used for height-based blending at run time): gravel stone tops and grass
blades reach ~1.0, asphalt ~0.5, mud stays low (puddles), so e.g. shoulder gravel pokes over the asphalt edge and
grass grows into the joints of setts.  relief_m = physical relief of the 0..1 range (normal map strength).

Swap-in rule: any set can be replaced by a photo-scanned CC0 set with the same file names (T_<Set>_*.png, height as
16-bit PNG) and an edited <Set>.json (tile_m, relief_m); Tools/environment/pack_web_environment.py and the game
read only these files.

Usage: python3 Tools/environment/terrain_textures.py [--size 1024] [--only Gravel,Asphalt] [--no-preview]
"""
import argparse
import json
import math
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from envlib import (F32, Canvas, ao_from_height, blade_shape, blur, fbm, hexc, leaf_shape, lin_to_srgb, lum,  # noqa: E402
                    normal_from_height, per_label_max, poisson_points, preview_lit, rot, smoothstep, to01, voronoi, warp,
                    write_set)

ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
OUT = os.path.join(ROOT, "Art", "Textures", "Environment", "Terrain")
PREV = os.path.join(ROOT, "Art", "Previews", "Environment")
SEED = 20260927
T0 = time.time()

# runtime layer order (texture array index) and what each layer is used for
LAYERS = [
    ("GrassGround", "grass sward under the instanced grass (meadows, verges, lawns)"),
    ("MeadowLitter", "dry meadow soil with fallen leaves (under broadleaf trees, dry slopes, along walls)"),
    ("ForestFloor", "spruce needle litter, cones, moss (forest outside the soft boundary)"),
    ("Dirt", "compacted field-track / path soil with pebbles"),
    ("Mud", "wet mud (ditches, brook banks, charlie spawn), puddles in the lows"),
    ("Gravel", "crushed greywacke (yards, road shoulders, paths)"),
    ("Asphalt", "worn asphalt with aggregate, cracks, sealed cracks and a patch (wet state in the shader)"),
    ("Concrete", "broom-finished concrete slabs with joints (yard, drive, bridge approaches)"),
    ("PavingSetts", "granite setts of the village square"),
    ("RiverStones", "rounded brook-bed / bank stones with silt"),
]


def log(*a):
    print(f"[{time.time() - T0:6.1f} s]", *a, flush=True)


def rng(k):
    return np.random.default_rng(SEED + k)


def palette_pick(r, cols, weights=None, var=0.08, size=None):
    cols = np.array([hexc(c) for c in cols])
    idx = r.choice(len(cols), size=size, p=None if weights is None else np.asarray(weights) / np.sum(weights))
    base = cols[idx]
    k = 1.0 + var * r.standard_normal(np.shape(idx) + (1,) if size is not None else (1,))
    return np.clip(base * k, 0, 1)


def finish(name, cv, tile_m, relief_m, family, ao_strength=1.0, rough_noise=0.03, extra=None, normal_strength=1.0, ao_radii=None):
    n = cv.n
    h = np.clip(cv.h, 0, 1)
    nrm = normal_from_height(h, relief_m, tile_m, normal_strength)
    ao = ao_from_height(h, relief_m, tile_m, radii_m=ao_radii or (0.004, 0.015, 0.05), strength=ao_strength)
    rough = np.clip(cv.rough + rough_noise * fbm(n, SEED + 999, lo=4, hi=200), 0.02, 1.0)
    meta = {"tile_m": tile_m, "relief_m": relief_m, "family": family, "author": "generated in this project (IRON VALLEY)",
            "license": "project-owned", "generator": "Tools/environment/terrain_textures.py", "seed": SEED}
    if extra:
        meta.update(extra)
    m = write_set(OUT, name, cv.rgb, h, rough, nrm, ao, meta)
    log(f"{name}: mean {m['mean_base_color_srgb']}, rough {m['mean_roughness']}, tile {tile_m} m")
    return cv.rgb, nrm, ao, h, rough


# ================================================================================================ grass sward
def grass_ground(n):
    tile = 2.0
    px = tile / n
    r = rng(1)
    cv = Canvas(n, base_rgb=hexc("#4f4330"), base_h=0.12, base_rough=0.92)
    soil = fbm(n, SEED + 11, lo=3, hi=300)
    cv.rgb *= (0.85 + 0.15 * soil[..., None])
    # dark moss / low litter mat between the tufts
    moss = smoothstep(0.1, 0.9, fbm(n, SEED + 12, lo=6, hi=180))
    cv.rgb = cv.rgb * (1 - 0.6 * moss[..., None]) + hexc("#3b4524") * 0.6 * moss[..., None]
    cv.h += 0.12 * moss
    # tuft density field: grass grows in overlapping tufts, a few bare / mossy gaps
    dens = to01(fbm(n, SEED + 13, lo=3, hi=40)) * 0.6 + 0.55
    greens = ["#5f6d2e", "#6e7c37", "#7c8b40", "#88944a", "#687532", "#566429"]
    drys = ["#a39461", "#b1a26c", "#958a58", "#bfae78", "#8b7d4c"]
    count = int(130000 * (n / 1024) ** 2)
    xs = r.random(count) * n
    ys = r.random(count) * n
    keep = r.random(count) < dens[ys.astype(int) % n, xs.astype(int) % n] / 1.15
    xs, ys = xs[keep], ys[keep]
    order = r.permutation(len(xs))
    for k in order:
        cx, cy = xs[k], ys[k]
        L = (0.018 + 0.05 * r.random() ** 1.5) / px          # 1.8 - 6.8 cm (foreshortened, seen from above)
        W = (0.0022 + 0.0022 * r.random()) / px
        ang = r.random() * 2 * math.pi
        ys_, xs_, X, Y = cv.region(cx, cy, L + 2)
        U, V = rot(X, Y, ang)
        a, prof = blade_shape(U, V, L, max(W, 1.1), bend=(r.random() - 0.5) * 0.5)
        if not a.any():
            continue
        dry = r.random() < 0.26
        col = palette_pick(r, drys if dry else greens, var=0.1)
        # blades are lighter at the tip (sun) and darker at the base
        t = np.clip(U / max(L, 1e-6), 0, 1)[..., None]
        colmap = col * (0.72 + 0.4 * t)
        cv.stamp(ys_, xs_, a, prof * 0.18, colmap, rough=0.86 if not dry else 0.93, sit=0.05, bury=False)
    # clover / small forb leaves
    for _ in range(int(900 * (n / 1024) ** 2)):
        cx, cy = r.random(2) * n
        R = (0.006 + 0.006 * r.random()) / px
        ang0 = r.random() * 2 * math.pi
        col = hexc("#4f6a2c") * (0.85 + 0.3 * r.random())
        for j in range(3):
            ang = ang0 + j * 2 * math.pi / 3
            ys_, xs_, X, Y = cv.region(cx, cy, 2 * R + 2)
            U, V = rot(X, Y, ang)
            a, prof, vein = leaf_shape(U, V, R * 1.6, R * 1.5, tip=0.8)
            cv.stamp(ys_, xs_, a, prof * 0.1, col * (1 - 0.25 * vein[..., None]), rough=0.8, sit=0.06, bury=False)
    cv.h = np.clip(cv.h / max(float(np.percentile(cv.h, 99.7)), 1e-3), 0, 1) * 0.95
    return finish("GrassGround", cv, tile, 0.035, "grass (ART_DIRECTION 3.1)", ao_strength=1.1, extra={"blend_note": "blades reach ~0.95"})


# ================================================================================================ meadow litter
def meadow_litter(n):
    tile = 2.5
    px = tile / n
    r = rng(2)
    cv = Canvas(n, base_rgb=hexc("#5d4c35"), base_h=0.1, base_rough=0.93)
    soil = fbm(n, SEED + 21, lo=3, hi=300)
    cv.rgb *= (0.82 + 0.18 * soil[..., None])
    crumbs = fbm(n, SEED + 22, lo=150, hi=500)
    cv.h += 0.04 * crumbs
    # sparse, partly dry grass
    dens = to01(fbm(n, SEED + 23, lo=3, hi=30))
    greens = ["#6a7534", "#7b8440", "#5e6a2e"]
    drys = ["#a89868", "#b9a673", "#94865a", "#c2b183", "#7f7250"]
    count = int(45000 * (n / 1024) ** 2)
    for _ in range(count):
        cx, cy = r.random(2) * n
        if r.random() > 0.25 + 0.75 * dens[int(cy) % n, int(cx) % n]:
            continue
        L = (0.02 + 0.06 * r.random() ** 1.3) / px
        W = (0.002 + 0.002 * r.random()) / px
        ang = r.random() * 2 * math.pi
        ys_, xs_, X, Y = cv.region(cx, cy, L + 2)
        U, V = rot(X, Y, ang)
        a, prof = blade_shape(U, V, L, max(W, 1.0), bend=(r.random() - 0.5) * 0.6)
        dry = r.random() < 0.6
        col = palette_pick(r, drys if dry else greens, var=0.1)
        cv.stamp(ys_, xs_, a, prof * 0.12, col, rough=0.93, sit=0.03, bury=False)
    # fallen leaves (lime, birch, maple): yellow, ochre, brown
    leaf_cols = ["#9a7d3a", "#8a6a33", "#7a552e", "#a88c45", "#634a2c", "#857a3e", "#6e6035", "#5a4a30", "#94703a"]
    for _ in range(int(1500 * (n / 1024) ** 2)):
        cx, cy = r.random(2) * n
        L = (0.025 + 0.07 * r.random() ** 1.5) / px
        W = L * (0.55 + 0.35 * r.random())
        ang = r.random() * 2 * math.pi
        ys_, xs_, X, Y = cv.region(cx, cy, L + 3)
        U, V = rot(X + L * 0.5 * math.cos(ang), Y + L * 0.5 * math.sin(ang), ang)
        a, prof, vein = leaf_shape(U, V, L, W, tip=1.2 + r.random(), serrate=0.08 * r.random(), lobes=3 if r.random() < 0.2 else 0)
        col = palette_pick(r, leaf_cols, var=0.12)
        curl = (0.8 + 0.3 * np.clip(V / max(W * 0.5, 1e-3), -1, 1))[..., None]
        colmap = col * (1 - 0.18 * vein[..., None]) * curl
        cv.stamp(ys_, xs_, a, prof * 0.08, colmap, rough=0.9, sit=0.08, bury=False)
    # twigs
    for _ in range(int(160 * (n / 1024) ** 2)):
        cx, cy = r.random(2) * n
        L = (0.06 + 0.15 * r.random()) / px
        W = (0.004 + 0.004 * r.random()) / px
        ang = r.random() * 2 * math.pi
        ys_, xs_, X, Y = cv.region(cx, cy, L + 3)
        U, V = rot(X, Y, ang)
        a, prof = blade_shape(U, V, L, W, bend=(r.random() - 0.5) * 0.3)
        cv.stamp(ys_, xs_, a, prof * 0.1, hexc("#4a3a2a") * (0.8 + 0.4 * r.random()), rough=0.9, sit=0.1, bury=False)
    cv.h = np.clip(cv.h / max(float(np.percentile(cv.h, 99.7)), 1e-3), 0, 1) * 0.72
    return finish("MeadowLitter", cv, tile, 0.03, "grass / forest floor transition (ART_DIRECTION 3.1)")


# ================================================================================================ forest floor
def forest_floor(n):
    tile = 3.0
    px = tile / n
    r = rng(3)
    cv = Canvas(n, base_rgb=hexc("#3e3024"), base_h=0.1, base_rough=0.95)
    cv.rgb *= (0.85 + 0.15 * fbm(n, SEED + 31, lo=3, hi=300)[..., None])
    # moss cushions
    mfuzz = fbm(n, SEED + 34, lo=80, hi=500, beta=0.5)
    moss = smoothstep(0.7, 1.6, fbm(n, SEED + 32, lo=3, hi=40) + 0.35 * mfuzz)
    mossd = to01(fbm(n, SEED + 33, lo=60, hi=500))
    cv.rgb = cv.rgb * (1 - 0.85 * moss[..., None]) + (hexc("#3e4726") * (0.7 + 0.5 * mossd[..., None])) * 0.85 * moss[..., None]
    cv.h += moss * (0.35 + 0.15 * mossd)
    cv.mask = moss
    # needle litter (dense): short thin strokes
    ncol = ["#6b4a30", "#7a5636", "#5a4232", "#8a6440", "#4d3b2c", "#6e5a44"]
    count = int(110000 * (n / 1024) ** 2)
    for _ in range(count):
        cx, cy = r.random(2) * n
        if moss[int(cy) % n, int(cx) % n] > 0.5 and r.random() < 0.55:
            continue
        L = (0.012 + 0.012 * r.random()) / px
        W = max(0.0012 / px, 0.9)
        ang = r.random() * 2 * math.pi
        ys_, xs_, X, Y = cv.region(cx, cy, L + 2)
        U, V = rot(X + 0.5 * L * math.cos(ang), Y + 0.5 * L * math.sin(ang), ang)
        a, prof = blade_shape(U, V, L, W, bend=(r.random() - 0.5) * 0.2)
        cv.stamp(ys_, xs_, a, prof * 0.05, palette_pick(r, ncol, var=0.12), rough=0.93, sit=0.02, bury=False)
    # spruce cones
    for _ in range(int(55 * (n / 1024) ** 2)):
        cx, cy = r.random(2) * n
        L = (0.08 + 0.05 * r.random()) / px
        W = L * 0.36
        ang = r.random() * 2 * math.pi
        ys_, xs_, X, Y = cv.region(cx, cy, L)
        U, V = rot(X, Y, ang)
        e = (U / (L / 2)) ** 2 + (V / (W / 2)) ** 2
        a = np.clip((1 - e) * 6, 0, 1)
        scales = 0.5 + 0.5 * np.sin(U * 1.2 / max(px * 400, 1e-3)) * np.sin(V * 1.6)
        prof = np.sqrt(np.clip(1 - e, 0, 1)) * (0.85 + 0.15 * scales)
        col = hexc("#6a4a2e") * (0.8 + 0.3 * r.random()) * (0.75 + 0.35 * scales[..., None])
        cv.stamp(ys_, xs_, a, prof * 0.4, col, rough=0.85, sit=0.05, bury=False)
    # twigs and a few beech leaves
    for _ in range(int(260 * (n / 1024) ** 2)):
        cx, cy = r.random(2) * n
        L = (0.05 + 0.2 * r.random()) / px
        W = (0.003 + 0.005 * r.random()) / px
        ang = r.random() * 2 * math.pi
        ys_, xs_, X, Y = cv.region(cx, cy, L + 3)
        U, V = rot(X, Y, ang)
        a, prof = blade_shape(U, V, L, W, bend=(r.random() - 0.5) * 0.3)
        cv.stamp(ys_, xs_, a, prof * 0.12, hexc("#3f3226") * (0.8 + 0.4 * r.random()), rough=0.9, sit=0.08, bury=False)
    for _ in range(int(500 * (n / 1024) ** 2)):
        cx, cy = r.random(2) * n
        L = (0.04 + 0.03 * r.random()) / px
        ang = r.random() * 2 * math.pi
        ys_, xs_, X, Y = cv.region(cx, cy, L + 3)
        U, V = rot(X, Y, ang)
        a, prof, vein = leaf_shape(U, V, L, L * 0.6, tip=1.3)
        col = palette_pick(r, ["#7a4f2a", "#8c6030", "#5e4028"], var=0.1)
        cv.stamp(ys_, xs_, a, prof * 0.06, col * (1 - 0.2 * vein[..., None]), rough=0.9, sit=0.06, bury=False)
    cv.h = np.clip(cv.h / max(float(np.percentile(cv.h, 99.7)), 1e-3), 0, 1) * 0.8
    cv.rough = np.where(moss > 0.5, 0.97, cv.rough)
    return finish("ForestFloor", cv, tile, 0.04, "forest_floor (ART_DIRECTION 3.1)")


# ================================================================================================ dirt
def pebbles(cv, r, count, rmin_m, rmax_m, px, cols, height, rough=0.8, bury_depth=0.4, speck=None, rough_hi=None, base=None):
    """rounded stones (ellipses with a wobbly outline, domed); stacked over whatever is lower (bury)."""
    for _ in range(count):
        cx, cy = r.random(2) * cv.n
        R = (rmin_m + (rmax_m - rmin_m) * r.random() ** 2) / px
        el = 0.55 + 0.4 * r.random()
        ang = r.random() * math.pi
        ys_, xs_, X, Y = cv.region(cx, cy, R + 1.5)
        U, V = rot(X, Y, ang)
        k = 2 + int(r.random() * 3)
        wob = 1.0 + 0.08 * np.sin(np.arctan2(V, U) * k + r.random() * 6) + 0.04 * np.sin(np.arctan2(V, U) * (k + 3) + r.random() * 6)
        e = np.sqrt((U / R) ** 2 + (V / (R * el)) ** 2) / wob
        a = np.clip((1 - e) * R * 0.9, 0, 1)
        prof = np.sqrt(np.clip(1 - e * e, 0, 1))
        col = palette_pick(r, cols, var=0.1)
        cmap = col * (0.8 + 0.22 * prof)[..., None]
        if speck is not None:
            cmap = cmap * (1 + 0.08 * speck[np.ix_(ys_, xs_)])[..., None]
        rr = rough if rough_hi is None else rough + (rough_hi - rough) * r.random()
        hh = height * min(1.0, R * px / 0.01)
        if base is None:
            cv.stamp(ys_, xs_, a, prof * hh, cmap, rough=rr, sit=-bury_depth * hh * 0.5, bury=True)
        else:   # absolute bed level: smaller stones fill the gaps around the bigger ones instead of lying on them
            cv.stamp(ys_, xs_, a, base + prof * hh, cmap, rough=rr, sit=None, bury=True)


def dirt(n):
    tile = 2.5
    px = tile / n
    r = rng(4)
    cv = Canvas(n, base_rgb=hexc("#6f5a40"), base_h=0.3, base_rough=0.92)
    b = fbm(n, SEED + 41, lo=2, hi=120, beta=2.2)
    fine = fbm(n, SEED + 42, lo=120, hi=512, beta=0.8)
    cv.rgb *= (0.93 + 0.05 * b[..., None] + 0.07 * fine[..., None])
    # damp darker blotches, lighter dry dusty areas
    damp = smoothstep(0.5, 1.8, fbm(n, SEED + 43, lo=3, hi=30))
    cv.rgb *= (1 - 0.14 * damp[..., None])
    dry = smoothstep(0.6, 1.8, fbm(n, SEED + 44, lo=3, hi=30))
    cv.rgb = cv.rgb * (1 - 0.2 * dry[..., None]) + hexc("#93806a") * 0.2 * dry[..., None]
    # crumbly clods (small soil aggregates)
    cpts = poisson_points(n, int(9000 * (n / 1024) ** 2), SEED + 48)
    cw = 0.2 * (n / math.sqrt(len(cpts)))
    _, _, cidx, cedge = voronoi(n, cpts, (cw * fbm(n, SEED + 49, lo=1, hi=80), cw * fbm(n, SEED + 50, lo=1, hi=80)))
    cmax = per_label_max(cedge, cidx, len(cpts))
    clod = np.sqrt(np.clip(cedge / np.maximum(cmax, 1e-3), 0, 1))
    cshade = (0.9 + 0.2 * np.random.default_rng(SEED + 51).random(len(cpts)))[cidx]
    cv.h += 0.12 * clod
    cv.rgb *= (0.8 + 0.2 * clod)[..., None] * cshade[..., None]
    cv.h += 0.08 * b + 0.03 * fine
    cv.rough -= 0.1 * damp
    # shallow compaction cracks in the dry parts
    pts = poisson_points(n, 260, SEED + 45)
    wx = 6 * fbm(n, SEED + 46, lo=4, hi=60)
    wy = 6 * fbm(n, SEED + 47, lo=4, hi=60)
    _, _, _, edge = voronoi(n, pts, (wx, wy))
    crack = np.clip(1 - edge / 1.3, 0, 1) * dry
    cv.h -= 0.1 * crack
    cv.rgb *= (1 - 0.35 * crack[..., None])
    stones = ["#6c675d", "#7a7468", "#5b564e", "#827a6c", "#6a5e4e", "#57524a"]
    pebbles(cv, r, int(7000 * (n / 1024) ** 2), 0.0015, 0.006, px, stones, 0.4)
    pebbles(cv, r, int(320 * (n / 1024) ** 2), 0.008, 0.022, px, stones, 0.6)
    # straw / grass bits
    for _ in range(int(900 * (n / 1024) ** 2)):
        cx, cy = r.random(2) * n
        L = (0.015 + 0.04 * r.random()) / px
        ang = r.random() * 2 * math.pi
        ys_, xs_, X, Y = cv.region(cx, cy, L + 2)
        U, V = rot(X, Y, ang)
        a, prof = blade_shape(U, V, L, 1.2, bend=0.2 * (r.random() - 0.5))
        cv.stamp(ys_, xs_, a, prof * 0.05, palette_pick(r, ["#a89868", "#8c7a50", "#6c7a38"], var=0.1), rough=0.9, sit=0.01, bury=False)
    cv.h = np.clip(cv.h, 0, 1) * 0.75
    return finish("Dirt", cv, tile, 0.03, "dirt (ART_DIRECTION 3.1)", ao_strength=0.9)


# ================================================================================================ mud
def mud(n):
    tile = 3.0
    px = tile / n
    r = rng(5)
    cv = Canvas(n, base_rgb=hexc("#4a3d2f"), base_h=0.2, base_rough=0.55)
    b = fbm(n, SEED + 51, lo=2, hi=90, beta=2.4)
    fine = fbm(n, SEED + 52, lo=90, hi=500, beta=1.0)
    cv.h += 0.12 * b + 0.02 * fine
    # boot and tyre impressions: smeared ellipses pressed into the mud with raised rims
    for _ in range(int(70 * (n / 1024) ** 2)):
        cx, cy = r.random(2) * n
        L = (0.12 + 0.2 * r.random()) / px
        W = L * (0.35 + 0.2 * r.random())
        ang = r.random() * math.pi
        ys_, xs_, X, Y = cv.region(cx, cy, L)
        U, V = rot(X, Y, ang)
        e = np.sqrt((U / (L / 2)) ** 2 + (V / (W / 2)) ** 2)
        dent = np.clip(1 - e, 0, 1) ** 0.6
        rim = np.exp(-((e - 1.05) / 0.12) ** 2)
        treads = 0.5 + 0.5 * np.sign(np.sin(U * 2 * math.pi / max(0.025 / px, 2)))
        cv.h[np.ix_(ys_, xs_)] += (-0.14 * dent * (0.8 + 0.2 * treads) + 0.05 * rim).astype(F32)
    cv.h = blur(cv.h, 0.8)
    rip = fbm(n, SEED + 53, lo=40, hi=250, beta=1.2)
    cv.h += 0.03 * rip
    # puddles in the lows: flat, dark, glossy (the shader adds more water with the wetness mask)
    lowlvl = np.percentile(cv.h, 18)
    wet = smoothstep(lowlvl + 0.03, lowlvl - 0.01, cv.h)
    cv.h = np.maximum(cv.h, lowlvl - 0.005)
    col = cv.rgb * (0.85 + 0.2 * to01(b)[..., None] + 0.05 * fine[..., None])
    col *= (1 - 0.25 * wet[..., None]) * (1 + 0.06 * rip[..., None])
    cv.rgb = col.astype(F32)
    cv.rough = (0.5 - 0.12 * to01(fine) - 0.35 * wet).astype(F32)
    stones = ["#6f6d63", "#7a7468", "#5c5850"]
    pebbles(cv, r, int(700 * (n / 1024) ** 2), 0.002, 0.01, px, stones, 0.3, rough=0.6)
    for _ in range(int(500 * (n / 1024) ** 2)):
        cx, cy = r.random(2) * n
        L = (0.02 + 0.06 * r.random()) / px
        ang = r.random() * 2 * math.pi
        ys_, xs_, X, Y = cv.region(cx, cy, L + 2)
        U, V = rot(X, Y, ang)
        a, prof = blade_shape(U, V, L, 1.3, bend=0.3 * (r.random() - 0.5))
        cv.stamp(ys_, xs_, a, prof * 0.04, palette_pick(r, ["#8c7a50", "#6a5a3a", "#5a6a30"], var=0.1), rough=0.7, sit=0.005, bury=True)
    cv.h = np.clip(cv.h, 0, 1) * 0.5
    return finish("Mud", cv, tile, 0.05, "mud (ART_DIRECTION 3.1)", rough_noise=0.02, ao_strength=0.7)


# ================================================================================================ gravel
def stone_layer(cv, n, count, seed, cols, h_top, gap_px, sit_level, angular=True, round_=False, rough=(0.88, 0.97), cover=1.0, elong=0.0):
    """Voronoi stone layer (angular crushed stone or rounded pebbles) composited over the canvas where higher."""
    r = np.random.default_rng(seed)
    pts = poisson_points(n, count, seed)
    cellpx = n / math.sqrt(count)
    wx = 0.22 * cellpx * fbm(n, seed + 1, lo=1, hi=math.sqrt(count) * 1.2)
    wy = 0.22 * cellpx * fbm(n, seed + 2, lo=1, hi=math.sqrt(count) * 1.2)
    d1, d2, idx, edge = voronoi(n, pts, (wx, wy))
    emax = per_label_max(edge, idx, len(pts))
    e = np.clip((edge - gap_px) / np.maximum(emax - gap_px, 1e-3), 0, 1)
    present = r.random(len(pts)) < cover
    if round_:
        prof = np.sqrt(np.clip(1 - (1 - e) ** 2, 0, 1))
    else:
        # angular: facetted pyramid with per-stone tilt planes
        tx = r.standard_normal(len(pts)) * 0.35
        ty = r.standard_normal(len(pts)) * 0.35
        yy, xx = np.mgrid[0:n, 0:n] + 0.5
        dx = xx - pts[idx, 0]
        dy = yy - pts[idx, 1]
        dx -= n * np.round(dx / n)
        dy -= n * np.round(dy / n)
        tilt = (tx[idx] * dx + ty[idx] * dy) / np.maximum(emax, 1)
        prof = np.clip(np.minimum(e * 1.6, 1.0) + 0.25 * tilt * e, 0, 1.2)
    top = h_top * (0.75 + 0.35 * r.random(len(pts)))[idx]
    z = sit_level + prof * top
    a = (e > 0).astype(F32) * present[idx]
    a *= np.clip(e * 8, 0, 1)
    above = z > cv.h
    a = a * above
    col = palette_pick(r, cols, var=0.09, size=len(pts))[idx]
    # facet lighting-free variation: slight darkening towards the stone edge (dirt film), speckle
    speck = fbm(n, seed + 3, lo=n / 8, hi=n / 1.5, beta=0.5)
    col = col * (0.8 + 0.2 * np.clip(e * 2, 0, 1))[..., None] * (1 + 0.05 * speck[..., None])
    cv.rgb = cv.rgb * (1 - a[..., None]) + col * a[..., None]
    cv.h = np.where(a > 0, cv.h * (1 - a) + z * a, cv.h).astype(F32)
    rr = rough[0] + (rough[1] - rough[0]) * r.random(len(pts))[idx]
    cv.rough = cv.rough * (1 - a) + rr * a
    return a


def gravel(n):
    tile = 2.0
    px = tile / n
    cv = Canvas(n, base_rgb=hexc("#4e4a42"), base_h=0.15, base_rough=0.97)
    cv.rgb *= (0.85 + 0.15 * fbm(n, SEED + 61, lo=4, hi=400)[..., None])
    cols = ["#9c978c", "#a39d91", "#8d897f", "#aaa497", "#858178", "#978d80", "#9f9687", "#8a8c84", "#b0aa9c", "#7a766e"]
    # fines (3-6 mm), medium (10-20 mm), large (20-40 mm) on top
    stone_layer(cv, n, int(26000 * (n / 1024) ** 2), SEED + 62, cols, 0.25, 0.9, 0.2)
    stone_layer(cv, n, int(5200 * (n / 1024) ** 2), SEED + 63, cols, 0.45, 1.4, 0.35, cover=0.92)
    stone_layer(cv, n, int(1300 * (n / 1024) ** 2), SEED + 64, cols, 0.5, 2.2, 0.45, cover=0.8)
    # dust in the lows, darker fines film
    low = smoothstep(0.45, 0.2, cv.h)
    cv.rgb = cv.rgb * (1 - 0.55 * low[..., None]) + hexc("#4a453c") * 0.55 * low[..., None]
    dust = smoothstep(0.2, 1.5, fbm(n, SEED + 65, lo=2, hi=10))
    cv.rgb = cv.rgb * (1 - 0.2 * dust[..., None]) + hexc("#8a8272") * 0.2 * dust[..., None]
    cv.h = np.clip(cv.h, 0, 1)
    cv.h = cv.h / max(float(cv.h.max()), 1e-3) * 1.0
    return finish("Gravel", cv, tile, 0.045, "gravel (ART_DIRECTION 3.1)", ao_strength=1.3, ao_radii=(0.003, 0.01, 0.03))


# ================================================================================================ asphalt
def asphalt(n):
    tile = 3.0
    px = tile / n
    r = rng(7)
    cv = Canvas(n, base_rgb=hexc("#3b3b3c"), base_h=0.3, base_rough=0.9)
    b = fbm(n, SEED + 71, lo=2, hi=60, beta=2.2)
    cv.rgb *= (0.92 + 0.08 * b[..., None])
    # aggregate: dense small stones in the binder, tops worn flat (lighter where exposed)
    agg_cols = ["#5f5e5b", "#67655f", "#56554f", "#6e6a63", "#5d5a55", "#716f6a", "#625d57"]
    wear = to01(fbm(n, SEED + 72, lo=2, hi=12))        # exposed aggregate in the worn areas
    a1 = stone_layer(cv, n, int(52000 * (n / 1024) ** 2), SEED + 73, agg_cols, 0.14, 0.7, 0.28, cover=0.6, rough=(0.72, 0.85))
    # binder film over part of the stones (fresh / less worn areas)
    film = smoothstep(0.35, 0.75, 1 - wear) * a1 * (fbm(n, SEED + 74, lo=40, hi=400) > 0.2)
    cv.rgb = cv.rgb * (1 - 0.6 * film[..., None]) + hexc("#3a3a3b") * 0.6 * film[..., None]
    fine = fbm(n, SEED + 75, lo=200, hi=512, beta=0.3)
    cv.rgb *= (1 + 0.06 * fine[..., None])
    cv.h += 0.02 * fine
    # crack network (large irregular cells), only partly developed
    pts = poisson_points(n, 12, SEED + 76)
    wx = 40 * fbm(n, SEED + 77, lo=2, hi=40)
    wy = 40 * fbm(n, SEED + 78, lo=2, hi=40)
    _, _, _, edge = voronoi(n, pts, (wx, wy))
    jag = 1.2 * fbm(n, SEED + 79, lo=60, hi=400)
    crackw = 1.2 + 0.6 * to01(fbm(n, SEED + 80, lo=4, hi=40))
    crack = np.clip(1 - np.abs(edge + jag) / crackw, 0, 1)
    develop = smoothstep(-0.2, 0.6, fbm(n, SEED + 81, lo=2, hi=10))
    crack *= develop
    # fine hairline cracks
    pts2 = poisson_points(n, 60, SEED + 82)
    _, _, _, edge2 = voronoi(n, pts2, (0.4 * wx, 0.4 * wy))
    hair = np.clip(1 - np.abs(edge2 + jag) / 0.8, 0, 1) * smoothstep(0.3, 1.0, fbm(n, SEED + 83, lo=3, hi=20))
    cr = np.maximum(crack, 0.6 * hair)
    cv.h -= 0.22 * cr
    cv.rgb *= (1 - 0.55 * cr[..., None])
    cv.rough = cv.rough * (1 - cr) + 0.95 * cr
    # bitumen crack sealing along part of the big cracks: glossy black snakes 2-3 cm wide
    seal_band = np.clip(1 - np.abs(edge + jag * 0.3) / (0.028 / px), 0, 1)
    seal = smoothstep(0.15, 0.4, seal_band) * smoothstep(0.3, 0.9, fbm(n, SEED + 84, lo=2, hi=6))
    cv.rgb = cv.rgb * (1 - seal[..., None]) + hexc("#1f1f20") * seal[..., None]
    cv.h = cv.h * (1 - seal) + 0.36 * seal
    cv.rough = cv.rough * (1 - seal) + 0.35 * seal
    # oil / tyre darkening blotches and a few leaves in the cracks
    oil = smoothstep(0.8, 2.2, fbm(n, SEED + 86, lo=2, hi=14))
    cv.rgb *= (1 - 0.3 * oil[..., None])
    cv.rough -= 0.2 * oil
    for _ in range(int(14 * (n / 1024) ** 2)):
        cx_, cy_ = r.random(2) * n
        L = (0.03 + 0.04 * r.random()) / px
        ang_ = r.random() * 2 * math.pi
        ys_, xs_, X, Y = cv.region(cx_, cy_, L + 3)
        Uu, Vv = rot(X, Y, ang_)
        a, prof, vein = leaf_shape(Uu, Vv, L, L * 0.6)
        col = palette_pick(r, ["#8c6a30", "#6f5028", "#a08238"], var=0.1)
        cv.stamp(ys_, xs_, a, prof * 0.05, col * (1 - 0.2 * vein[..., None]), rough=0.85, sit=0.02, bury=False)
    cv.h = np.clip(cv.h, 0, 1) * 0.55 / max(float(np.percentile(cv.h, 99.8)), 1e-3)
    cv.h = np.clip(cv.h, 0, 0.6)
    return finish("Asphalt", cv, tile, 0.008, "asphalt (ART_DIRECTION 3.1; wet state in the shader)", rough_noise=0.03, ao_strength=0.8,
                  ao_radii=(0.004, 0.012, 0.03))


# ================================================================================================ concrete
def concrete(n):
    tile = 3.0
    px = tile / n
    r = rng(8)
    cv = Canvas(n, base_rgb=hexc("#a39f96"), base_h=0.45, base_rough=0.85)
    b = fbm(n, SEED + 91, lo=2, hi=40, beta=2.3)
    cv.rgb *= (0.96 + 0.04 * b[..., None])
    speck = fbm(n, SEED + 90, lo=180, hi=512, beta=0.0)
    cv.rgb *= (1 + 0.07 * speck[..., None])
    mid = fbm(n, SEED + 89, lo=20, hi=120, beta=1.5)
    cv.rgb *= (1 + 0.04 * mid[..., None])
    cv.h += 0.02 * mid
    # broom finish: fine grooves along x
    broom = fbm(n, SEED + 92, lo=30, hi=400, beta=0.8, aniso=(0.08, 1.0))
    cv.h += 0.05 * broom
    cv.rgb *= (1 + 0.04 * broom[..., None])
    # pores and exposed fine aggregate
    pores = fbm(n, SEED + 93, lo=250, hi=512, beta=0.0)
    pm = smoothstep(2.0, 2.8, pores)
    cv.h -= 0.05 * pm
    cv.rgb *= (1 - 0.25 * pm[..., None])
    aggr = smoothstep(1.8, 2.6, fbm(n, SEED + 94, lo=150, hi=512, beta=0.2))
    cv.rgb = cv.rgb * (1 - 0.5 * aggr[..., None]) + hexc("#8c877c") * 0.5 * aggr[..., None]
    # stains: water / dirt blotches, algae along the joints
    st = smoothstep(0.4, 1.8, fbm(n, SEED + 95, lo=3, hi=24))
    cv.rgb *= (1 - 0.1 * st[..., None])
    yy, xx = np.mgrid[0:n, 0:n] + 0.5
    dj = np.minimum(np.minimum(xx, n - xx), np.minimum(yy, n - yy)) * px   # distance to the slab joints (tile edges)
    jw = 0.012
    joint = smoothstep(jw, jw * 0.4, dj)
    chip = smoothstep(0.035, 0.0, dj) * smoothstep(0.6, 1.5, fbm(n, SEED + 96, lo=10, hi=200))
    algae = smoothstep(0.15, 0.0, dj) * to01(fbm(n, SEED + 97, lo=6, hi=100))
    cv.rgb = cv.rgb * (1 - 0.35 * algae[..., None]) + hexc("#5b604a") * 0.35 * algae[..., None]
    cv.h = cv.h * (1 - np.maximum(joint, chip * 0.6)) + 0.12 * np.maximum(joint, chip * 0.6)
    cv.rgb = cv.rgb * (1 - joint[..., None]) + hexc("#3e3a32") * joint[..., None]
    cv.rgb *= (1 - 0.25 * chip[..., None])
    # a corner crack
    pts = poisson_points(n, 6, SEED + 98)
    wx = 30 * fbm(n, SEED + 99, lo=2, hi=30)
    wy = 30 * fbm(n, SEED + 100, lo=2, hi=30)
    _, _, _, edge = voronoi(n, pts, (wx, wy))
    crack = np.clip(1 - np.abs(edge + 1.0 * fbm(n, SEED + 101, lo=60, hi=400)) / 1.1, 0, 1)
    crack *= smoothstep(0.4, 1.2, fbm(n, SEED + 102, lo=2, hi=8))
    cv.h -= 0.2 * crack
    cv.rgb *= (1 - 0.5 * crack[..., None])
    # moss tufts in the joints
    for _ in range(int(120 * (n / 1024) ** 2)):
        side = r.integers(4)
        t = r.random() * n
        cx, cy = [(t, 0), (t, n - 1), (0, t), (n - 1, t)][side]
        R = (0.006 + 0.012 * r.random()) / px
        ys_, xs_, X, Y = cv.region(cx, cy, R + 1)
        e = np.sqrt(X * X + Y * Y) / R * (1 + 0.3 * np.sin(np.arctan2(Y, X) * 5))
        a = np.clip((1 - e) * 3, 0, 1)
        cv.stamp(ys_, xs_, a, np.sqrt(np.clip(1 - e * e, 0, 1)) * 0.2, hexc("#4e5c2c") * (0.8 + 0.4 * r.random()), rough=0.95, sit=0.0, bury=False)
    cv.h = np.clip(cv.h, 0, 1) * 0.6 / max(float(np.percentile(cv.h, 99.8)), 1e-3)
    cv.h = np.clip(cv.h, 0, 0.65)
    return finish("Concrete", cv, tile, 0.01, "concrete (ART_DIRECTION 3.1)", ao_strength=0.8, ao_radii=(0.004, 0.012, 0.03))


# ================================================================================================ granite setts
def paving_setts(n):
    tile = 1.5
    px = tile / n
    r = rng(9)
    cv = Canvas(n, base_rgb=hexc("#4a4438"), base_h=0.1, base_rough=0.95)
    cv.rgb *= (0.85 + 0.2 * fbm(n, SEED + 111, lo=10, hi=400)[..., None])
    rows = 14
    rh = n / rows
    joint = 0.009 / px
    grain = fbm(n, SEED + 112, lo=200, hi=512, beta=0.0)
    grain2 = fbm(n, SEED + 113, lo=8, hi=60, beta=1.5)
    granite = ["#8a8680", "#96908a", "#7d7975", "#a09990", "#8c8378", "#88878a", "#9b9087", "#78736d", "#908984", "#8e8279"]
    yy, xx = np.mgrid[0:n, 0:n] + 0.5
    H = cv.h.copy()
    C = cv.rgb.copy()
    R = cv.rough.copy()
    for j in range(rows):
        count = 13 + int(r.integers(0, 3))
        w = 0.75 + 0.5 * r.random(count)
        w = w / w.sum() * n
        edges = np.concatenate([[0], np.cumsum(w)]) + r.random() * n
        y0 = j * rh
        for k in range(count):
            x0 = edges[k]
            x1 = edges[k + 1]
            cxs = (x0 + x1) / 2
            cys = y0 + rh / 2 + (r.random() - 0.5) * 2
            hwx = (x1 - x0) / 2 - joint / 2 - r.random() * 1.5
            hwy = rh / 2 - joint / 2 - r.random() * 1.5
            ang = (r.random() - 0.5) * 0.08
            rad = int(max(hwx, hwy) + 4)
            ys_ = np.arange(int(cys) - rad, int(cys) + rad + 1)
            xs_ = np.arange(int(cxs) - rad, int(cxs) + rad + 1)
            X = xs_[None, :] + 0.5 - cxs
            Y = ys_[:, None] + 0.5 - cys
            U, V = rot(X, Y, ang)
            # rounded rectangle with chipped corners
            cr = min(hwx, hwy) * (0.25 + 0.2 * r.random())
            qx = np.abs(U) - (hwx - cr)
            qy = np.abs(V) - (hwy - cr)
            sd = np.hypot(np.maximum(qx, 0), np.maximum(qy, 0)) + np.minimum(np.maximum(qx, qy), 0) - cr
            iy, ix = ys_ % n, xs_ % n
            sd = sd + 0.5 * grain2[np.ix_(iy, ix)]
            a = np.clip(0.5 - sd, 0, 1)
            inner = np.clip(-sd / (min(hwx, hwy) * 0.9), 0, 1)
            prof = 0.55 + 0.35 * np.sqrt(inner) + 0.05 * (r.random() - 0.5)
            col = palette_pick(r, granite, var=0.07)
            gcol = col * (1 + 0.12 * grain[np.ix_(iy, ix)][..., None]) * (0.92 + 0.12 * inner[..., None])
            polish = 0.72 + 0.1 * r.random()
            sl = np.ix_(iy, ix)
            H[sl] = H[sl] * (1 - a) + prof * a
            C[sl] = C[sl] * (1 - a[..., None]) + gcol * a[..., None]
            R[sl] = R[sl] * (1 - a) + (polish + 0.1 * (1 - inner)) * a
    cv.h, cv.rgb, cv.rough = H, C, R
    # moss / weeds in the joints
    low = smoothstep(0.35, 0.15, cv.h)
    mossy = low * smoothstep(0.1, 1.2, fbm(n, SEED + 114, lo=4, hi=60))
    cv.rgb = cv.rgb * (1 - 0.7 * mossy[..., None]) + hexc("#45522a") * 0.7 * mossy[..., None]
    cv.h += 0.12 * mossy
    # dirt film and wet dark spots
    film = smoothstep(0.3, 1.5, fbm(n, SEED + 115, lo=2, hi=12))
    cv.rgb *= (1 - 0.15 * film[..., None])
    cv.h = np.clip(cv.h, 0, 1) * 0.85
    return finish("PavingSetts", cv, tile, 0.02, "paving (ART_DIRECTION 3.1)", ao_strength=1.0, ao_radii=(0.003, 0.01, 0.03))


# ================================================================================================ brook stones
def river_stones(n):
    tile = 2.5
    px = tile / n
    r = rng(10)
    cv = Canvas(n, base_rgb=hexc("#6e6858"), base_h=0.1, base_rough=0.9)
    silt = fbm(n, SEED + 121, lo=3, hi=300)
    cv.rgb *= (0.88 + 0.12 * silt[..., None])
    cv.h += 0.05 * silt
    cols = ["#6f6d63", "#7c796e", "#5f5d56", "#857f72", "#6a6358", "#76726a", "#8e8a80", "#5a5c55", "#948e82", "#6b6a60"]
    speck = fbm(n, SEED + 125, lo=150, hi=512, beta=0.2)
    # sand grains / small gravel, then cobbles (large first so the smaller ones fill the gaps around them)
    stone_layer(cv, n, int(14000 * (n / 1024) ** 2), SEED + 122, cols, 0.2, 0.7, 0.1, angular=False, round_=True, rough=(0.78, 0.9))
    pebbles(cv, r, int(210 * (n / 1024) ** 2), 0.045, 0.1, px, cols, 0.85, rough=0.66, rough_hi=0.84, speck=speck, base=0.08)
    pebbles(cv, r, int(1300 * (n / 1024) ** 2), 0.015, 0.045, px, cols, 0.55, rough=0.7, rough_hi=0.86, speck=speck, base=0.08)
    pebbles(cv, r, int(4000 * (n / 1024) ** 2), 0.004, 0.014, px, cols, 0.3, rough=0.75, rough_hi=0.9, speck=speck, base=0.08)
    # algae / dark wet film low down, dry lighter tops
    lowf = smoothstep(0.45, 0.15, cv.h)
    cv.rgb = cv.rgb * (1 - 0.3 * lowf[..., None]) + hexc("#3f4430") * 0.3 * lowf[..., None]
    cv.h = np.clip(cv.h, 0, 1) / max(float(cv.h.max()), 1e-3) * 0.95
    return finish("RiverStones", cv, tile, 0.08, "stone (ART_DIRECTION 3.1)", ao_strength=1.2, ao_radii=(0.005, 0.02, 0.06))


GENERATORS = {
    "GrassGround": grass_ground, "MeadowLitter": meadow_litter, "ForestFloor": forest_floor, "Dirt": dirt, "Mud": mud,
    "Gravel": gravel, "Asphalt": asphalt, "Concrete": concrete, "PavingSetts": paving_setts, "RiverStones": river_stones,
}


def contact_sheet(results, path, cell=256):
    from PIL import Image, ImageDraw
    names = list(results)
    W = cell * 4
    img = Image.new("RGB", (W, cell * 2 * len(names) // 2 + 20 * len(names)), (30, 30, 30))
    y = 0
    d = ImageDraw.Draw(img)
    for i, name in enumerate(names):
        rgb, nrm, ao, h, rough = results[name]
        n = rgb.shape[0]
        step = max(1, n // cell)
        a = lin_to_srgb(rgb[::step, ::step])
        lit = preview_lit(rgb, nrm, ao)[::step, ::step]
        tile_a = np.tile(a, (2, 2, 1))
        tile_l = np.tile(lit, (2, 2, 1))
        both = np.concatenate([tile_a, tile_l], axis=1)
        im = Image.fromarray(np.clip(both * 255, 0, 255).astype(np.uint8))
        im = im.resize((W, cell), Image.LANCZOS) if im.size[0] != W else im
        d.text((6, y + 3), name, fill=(240, 240, 240))
        img.paste(im, (0, y + 18))
        y += cell + 20
    img = img.crop((0, 0, W, y))
    img.save(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, default=1024)
    ap.add_argument("--only", default=None)
    ap.add_argument("--no-preview", action="store_true")
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(PREV, exist_ok=True)
    names = a.only.split(",") if a.only else list(GENERATORS)
    results = {}
    for nm in names:
        results[nm] = GENERATORS[nm](a.size)
    manifest = {"_comment": "GENERATED by Tools/environment/terrain_textures.py - layer order of the runtime terrain texture array. Each set lives in <name>/ (T_<name>_*.png + <name>.json); replace the PNGs and the JSON (tile_m, relief_m) to swap in scanned sets.",
                "layers": [{"index": i, "name": nm, "use": use} for i, (nm, use) in enumerate(LAYERS)]}
    with open(os.path.join(OUT, "terrain_layers.json"), "w") as f:
        json.dump(manifest, f, indent=1, ensure_ascii=False)
        f.write("\n")
    if not a.no_preview:
        contact_sheet(results, os.path.join(PREV, "terrain_sets_contact.png"))
        log("contact sheet written")


if __name__ == "__main__":
    main()
