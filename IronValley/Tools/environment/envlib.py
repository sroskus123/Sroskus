"""
envlib.py -- shared numpy helpers for the procedural environment textures of IRON VALLEY (terrain detail sets,
bark, leaf / needle cards, grass cards).  Everything is deterministic (explicit seeds) and seamlessly tiling
(periodic FFT noise, Voronoi on a torus, sprites stamped with wrap-around).

Conventions (Docs/ART_DIRECTION.md 3):
  - base colour is sRGB without baked light; ORM = R occlusion, G roughness, B metallic (linear);
  - normal maps are OpenGL convention (+Y = image up); the _DX variant flips green;
  - height is 0..1 over the set's relief (`relief_m` in the set JSON), saved as 16-bit PNG.
Image rows run top -> bottom; x = column.
"""
import json
import math
import os

import numpy as np
from PIL import Image
from scipy import ndimage
from scipy.spatial import cKDTree

F32 = np.float32


# ------------------------------------------------------------------------------------------------ colour
def srgb_to_lin(c):
    c = np.asarray(c, np.float64)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def lin_to_srgb(c):
    c = np.clip(np.asarray(c, np.float64), 0, 1)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(c, 1 / 2.4) - 0.055)


def hexc(h):
    """sRGB hex -> linear rgb (3,)"""
    h = h.lstrip("#")
    return srgb_to_lin(np.array([int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]))


def lum(rgb):
    return rgb[..., 0] * 0.2126 + rgb[..., 1] * 0.7152 + rgb[..., 2] * 0.0722


# ------------------------------------------------------------------------------------------------ noise
def fbm(n, seed, lo=1.0, hi=None, beta=2.0, aniso=(1.0, 1.0)):
    """periodic fractal noise (n x n), zero mean / unit std. Power spectrum ~ f^-beta between lo and hi cycles per
    tile (soft band edges). aniso = frequency scale (x, y): (1, 4) stretches features along x."""
    r = np.random.default_rng(seed)
    w = r.standard_normal((n, n))
    F = np.fft.rfft2(w)
    fy = np.fft.fftfreq(n)[:, None] * n * aniso[1]
    fx = np.fft.rfftfreq(n)[None, :] * n * aniso[0]
    f = np.hypot(fx, fy)
    amp = np.zeros_like(f)
    nz = f > 0
    amp[nz] = f[nz] ** (-beta / 2)
    if lo:
        amp *= 1.0 - np.exp(-((f / lo) ** 4))
    if hi:
        amp *= np.exp(-((f / hi) ** 2))
    out = np.fft.irfft2(F * amp, s=(n, n))
    out -= out.mean()
    out /= out.std() + 1e-12
    return out.astype(F32)


def to01(a, lo_pct=0.5, hi_pct=99.5):
    lo, hi = np.percentile(a, [lo_pct, hi_pct])
    return np.clip((a - lo) / max(hi - lo, 1e-9), 0, 1).astype(F32)


def blur(a, sigma):
    return ndimage.gaussian_filter(a, sigma, mode="wrap")


def warp(a, dx, dy):
    """sample periodic array a at (y + dy, x + dx) (pixels)."""
    n0, n1 = a.shape[:2]
    yy, xx = np.mgrid[0:n0, 0:n1].astype(F32)
    coords = [yy + dy, xx + dx]
    if a.ndim == 2:
        return ndimage.map_coordinates(a, coords, order=1, mode="grid-wrap").astype(F32)
    return np.stack([ndimage.map_coordinates(a[..., k], coords, order=1, mode="grid-wrap") for k in range(a.shape[2])], -1).astype(F32)


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0, 1)
    return t * t * (3 - 2 * t)


# ------------------------------------------------------------------------------------------------ voronoi
def poisson_points(n, count, seed, min_dist=None):
    """roughly uniform points on the torus [0, n)^2 (jittered grid, optionally thinned to min_dist)."""
    r = np.random.default_rng(seed)
    g = int(math.ceil(math.sqrt(count)))
    cell = n / g
    ij = np.stack(np.meshgrid(np.arange(g), np.arange(g)), -1).reshape(-1, 2)
    pts = (ij + 0.15 + 0.7 * r.random((len(ij), 2))) * cell
    pts = pts[r.permutation(len(pts))[:count]]
    return pts % n


def voronoi(n, pts, metric_warp=None):
    """periodic Voronoi on the pixel grid: (d1, d2, idx, edge) where edge = distance to the nearest cell border
    (exact bisector distance between the two nearest seeds). pts in pixel units (x, y)."""
    tree = cKDTree(pts, boxsize=n)
    yy, xx = np.mgrid[0:n, 0:n].astype(np.float64) + 0.5
    if metric_warp is not None:
        xx = xx + metric_warp[0]
        yy = yy + metric_warp[1]
    q = np.column_stack([xx.ravel() % n, yy.ravel() % n])
    d, i = tree.query(q, k=2)
    p1 = pts[i[:, 0]]
    p2 = pts[i[:, 1]]
    dv = p2 - p1
    dv -= n * np.round(dv / n)
    sep = np.maximum(np.linalg.norm(dv, axis=1), 1e-6)
    edge = (d[:, 1] ** 2 - d[:, 0] ** 2) / (2 * sep)
    sh = (n, n)
    return d[:, 0].reshape(sh).astype(F32), d[:, 1].reshape(sh).astype(F32), i[:, 0].reshape(sh), edge.reshape(sh).astype(F32)


def per_label_max(a, labels, count):
    m = ndimage.maximum(a, labels=labels, index=np.arange(count))
    return np.asarray(m, F32)[labels]


# ------------------------------------------------------------------------------------------------ canvas + sprites
class Canvas:
    """layered material canvas (linear colour, height 0..1+, roughness, ao-free) with wrap-around sprite stamping."""

    def __init__(self, n, base_rgb=(0.1, 0.1, 0.1), base_h=0.0, base_rough=0.9):
        self.n = n
        self.rgb = np.empty((n, n, 3), F32)
        self.rgb[:] = np.asarray(base_rgb, F32)
        self.h = np.full((n, n), base_h, F32)
        self.rough = np.full((n, n), base_rough, F32)
        self.mask = np.zeros((n, n), F32)   # free channel (e.g. moss, wet)

    def region(self, cx, cy, rad):
        n = self.n
        x0 = int(math.floor(cx - rad))
        y0 = int(math.floor(cy - rad))
        x1 = int(math.ceil(cx + rad)) + 1
        y1 = int(math.ceil(cy + rad)) + 1
        xs = np.arange(x0, x1)
        ys = np.arange(y0, y1)
        X = xs[None, :] + 0.5 - cx
        Y = ys[:, None] + 0.5 - cy
        return ys % n, xs % n, X.astype(F32), Y.astype(F32)

    def stamp(self, ys, xs, alpha, height, rgb, rough=None, sit=0.0, bury=True, mask=None):
        """composite a sprite: alpha (a), height profile (absolute, or relative to the ground under it if sit is not
        None: z = median(ground) + sit + height), colour (3,) or (h, w, 3), roughness scalar / array."""
        ix = np.ix_(ys, xs)
        H = self.h[ix]
        a = alpha
        if sit is not None:
            under = H[a > 0.5]
            base = float(np.median(under)) if under.size else float(H.mean())
            z = base + sit + height
        else:
            z = height
        if bury:
            a = a * np.clip((z - H) * 40.0 + 1.0, 0, 1)
        a = np.clip(a, 0, 1).astype(F32)
        if not a.any():
            return
        self.h[ix] = H * (1 - a) + np.maximum(H, z) * a
        C = self.rgb[ix]
        rgb = np.asarray(rgb, F32)
        if rgb.ndim == 1:
            rgb = rgb[None, None, :]
        self.rgb[ix] = C * (1 - a[..., None]) + rgb * a[..., None]
        if rough is not None:
            R = self.rough[ix]
            self.rough[ix] = R * (1 - a) + np.asarray(rough, F32) * a
        if mask is not None:
            M = self.mask[ix]
            self.mask[ix] = M * (1 - a) + np.asarray(mask, F32) * a


def rot(X, Y, ang):
    c, s = math.cos(ang), math.sin(ang)
    return X * c + Y * s, -X * s + Y * c


def blade_shape(X, Y, length, width, bend=0.0):
    """grass blade / needle along +u from the origin: alpha (antialiased) and height profile (0 at the base, 1 at the
    ridge). bend curves the blade (fraction of its length)."""
    u = X
    v = Y - bend * (u / max(length, 1e-6)) ** 2 * length
    t = u / max(length, 1e-6)
    w = width * 0.5 * np.clip(1.0 - t, 0, 1) ** 0.7 * np.clip(t * 6, 0, 1) ** 0.3
    inside_len = (t >= 0) & (t <= 1)
    d = np.abs(v) - w
    a = np.clip(0.5 - d, 0, 1) * inside_len
    prof = np.clip(1 - np.abs(v) / np.maximum(w, 1e-3), 0, 1) ** 0.5 * (0.35 + 0.65 * np.clip(t, 0, 1))
    return a.astype(F32), prof.astype(F32)


def leaf_shape(X, Y, length, width, tip=1.6, serrate=0.0, lobes=0):
    """ovate leaf along +u from the petiole at the origin: alpha, height profile (midrib ridge + cupping), vein mask."""
    t = X / max(length, 1e-6)
    tt = np.clip(t, 0, 1)
    # outline: ovate with a pointed tip
    half = width * 0.5 * np.sin(np.pi * np.clip(tt, 0, 1) ** (1 / tip)) * (tt <= 1) * (tt >= 0)
    if serrate:
        half = half * (1.0 - serrate * (0.5 + 0.5 * np.sin(tt * 40.0)))
    if lobes:
        half = half * (0.78 + 0.22 * np.cos(tt * lobes * 2 * np.pi))
    d = np.abs(Y) - half
    a = np.clip(0.6 - d, 0, 1) * ((t >= 0) & (t <= 1))
    rel = np.clip(np.abs(Y) / np.maximum(half, 1e-3), 0, 1)
    prof = (0.55 + 0.45 * (1 - rel) ** 2) * (0.6 + 0.4 * np.sin(np.pi * tt))
    vein = np.clip(1.0 - np.abs(Y) / 0.8, 0, 1)
    side = np.clip(1.0 - np.abs(np.abs(Y) - (X - length * 0.1) * 0.45 % (length * 0.16)) / 0.7, 0, 1) * (rel < 0.9)
    return a.astype(F32), prof.astype(F32), np.maximum(vein, side * 0.5).astype(F32)


# ------------------------------------------------------------------------------------------------ derived maps
def normal_from_height(h01, relief_m, tile_m, strength=1.0):
    """OpenGL tangent-space normal (x = +column, y = image up) from a periodic height (0..1 over relief_m)."""
    n = h01.shape[0]
    px = tile_m / n
    hm = h01.astype(np.float64) * relief_m
    dx = (np.roll(hm, -1, 1) - np.roll(hm, 1, 1)) / (2 * px)
    drow = (np.roll(hm, -1, 0) - np.roll(hm, 1, 0)) / (2 * px)
    nx = -dx * strength
    ny = drow * strength      # image up = -row
    nz = np.ones_like(nx)
    L = np.sqrt(nx * nx + ny * ny + nz * nz)
    return np.stack([nx / L, ny / L, nz / L], -1).astype(F32)


def ao_from_height(h01, relief_m, tile_m, radii_m=(0.004, 0.015, 0.05), strength=1.0):
    """cavity occlusion from height: how far below its neighbourhood each texel sits (multi-scale), in [0.35, 1]."""
    n = h01.shape[0]
    px = tile_m / n
    hm = h01 * relief_m
    occ = np.zeros_like(hm)
    for r in radii_m:
        s = max(r / px, 0.7)
        d = blur(hm, s) - hm
        occ += np.clip(d / max(r, 1e-4), 0, None)
    ao = 1.0 - strength * np.clip(occ / len(radii_m), 0, 1) * 1.2
    return np.clip(ao, 0.35, 1.0).astype(F32)


# ------------------------------------------------------------------------------------------------ output
def save_png8(path, arr01, mode="RGB"):
    a = np.clip(np.round(np.asarray(arr01) * 255), 0, 255).astype(np.uint8)
    Image.fromarray(a, mode).save(path, optimize=True)


def save_png16(path, arr01):
    a = np.clip(np.round(np.asarray(arr01) * 65535), 0, 65535).astype(np.uint16)
    Image.fromarray(a, "I;16").save(path)


def write_set(out_dir, name, rgb_lin, h01, rough, normal, ao, meta):
    """writes T_<name>_{BaseColor,Normal,Normal_DX,ORM,Height}.png + <name>.json into out_dir/<name>/."""
    d = os.path.join(out_dir, name)
    os.makedirs(d, exist_ok=True)
    base = lin_to_srgb(rgb_lin)
    save_png8(os.path.join(d, f"T_{name}_BaseColor.png"), base)
    nrm = normal * 0.5 + 0.5
    save_png8(os.path.join(d, f"T_{name}_Normal.png"), nrm)
    ndx = nrm.copy()
    ndx[..., 1] = 1 - ndx[..., 1]
    save_png8(os.path.join(d, f"T_{name}_Normal_DX.png"), ndx)
    orm = np.stack([ao, rough, np.zeros_like(ao)], -1)
    save_png8(os.path.join(d, f"T_{name}_ORM.png"), orm)
    save_png16(os.path.join(d, f"T_{name}_Height.png"), h01)
    mean_srgb = lin_to_srgb(rgb_lin.reshape(-1, 3).mean(axis=0))
    meta = dict(meta)
    meta.update({
        "name": name,
        "maps": {"baseColor": f"T_{name}_BaseColor.png", "normal": f"T_{name}_Normal.png", "normalDX": f"T_{name}_Normal_DX.png",
                 "orm": f"T_{name}_ORM.png", "height": f"T_{name}_Height.png"},
        "size_px": int(h01.shape[0]),
        "mean_base_color_srgb": "#" + "".join(f"{int(round(v * 255)):02x}" for v in mean_srgb),
        "mean_roughness": round(float(rough.mean()), 3),
        "conventions": "base colour sRGB without baked light; ORM R=occlusion G=roughness B=metallic (linear); normal OpenGL (+Y up), _DX flips green; height 16-bit 0..1 over relief_m",
    })
    with open(os.path.join(d, f"{name}.json"), "w") as f:
        json.dump(meta, f, indent=1, ensure_ascii=False)
        f.write("\n")
    return meta


def preview_lit(rgb_lin, normal, ao, light=(0.45, 0.35, 0.82), ambient=0.35):
    """quick lambert preview in sRGB (for the contact sheet only)."""
    L = np.asarray(light, np.float64)
    L /= np.linalg.norm(L)
    nd = np.clip((normal * L[None, None, :]).sum(-1), 0, 1)
    shade = (nd * (1 - ambient) + ambient * ao)[..., None]
    return lin_to_srgb(rgb_lin * shade * 1.6)
