#!/usr/bin/env python3
"""
export_web_level.py -- generates the playable web version of the map "Kalné Hamry" (IRON VALLEY) from the level
design data, reproducibly (no hand editing):

  inputs   Shared/level/layout.json, Shared/level/buildings.json (the binding level data, decision D10)
  outputs  Web/public/assets/levels/kalne_hamry/kh_terrain.glb    terrain (render + collision), albedo map, surface raster
           Web/public/assets/levels/kalne_hamry/kh_world.glb      buildings, props, fences, walls, bridges, vegetation,
                                                                trees (EXT_mesh_gpu_instancing), backdrop hills, signs
           Web/public/assets/levels/kalne_hamry/kh_collision.glb  collision meshes by class (main / move / movevis)
           Web/src/data/kalne_hamry.json                         level data for the game (spawns, zones, armories, cover,
                                                                boundary, QA points, surfaces, environment)

Placeholder art ("provizorní grafika"): simple PBR materials from Docs/ART_DIRECTION.md, props as correctly sized blocks,
trees as low-poly shapes by species.  Lighting: sky visibility + one bounce of sunlight baked per vertex at build time
(mathutils BVH from the bpy module when available, else a sky-visibility-only 2.5D fallback).

Usage:  python3 Tools/level/export_web_level.py [--no-bake] [--quick]
Requires Python 3.11 + numpy, scipy, shapely, matplotlib, pillow (+ optional bpy 4.5 for the 3D light bake).
"""
import argparse
import hashlib
import io
import json
import math
import os
import sys
import time

import numpy as np
from matplotlib.path import Path as MPath
from PIL import Image, ImageDraw, ImageFile, ImageFont
from scipy import ndimage
from shapely.geometry import LineString, Point, Polygon, box as sbox
from shapely.ops import unary_union

ImageFile.MAXBLOCK = 1 << 25   # optimised JPEG of large images needs one big buffer (PIL "Suspension not allowed")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(HERE, "lib"))
sys.path.insert(0, HERE)
import ivterrain as T  # noqa: E402
import check_layout as C  # noqa: E402
from ivglb import FLOAT, UBYTE, GLB, hex_rgb, srgb_to_linear, to_gltf  # noqa: E402
from ivwebgeo import Scene, xf  # noqa: E402

LEVEL_ID = "kalne_hamry"
ASSET_DIR_REL = "assets/levels/kalne_hamry"
OUT_ASSETS = os.path.join(ROOT, "Web", "public", ASSET_DIR_REL)
OUT_LEVEL = os.path.join(ROOT, "Web", "src", "data", f"{LEVEL_ID}.json")
SEED = 20260927

RES = 0.5            # terrain grid (render + collision), same as the design-time nav input
OUTER_RES = 2.0      # outer terrain ring (render only)
FINE_MARGIN = 6.0    # fine terrain covers the hard boundary + this margin

T0 = time.time()


def log(*a):
    print(f"[{time.time() - T0:6.1f} s]", *a, flush=True)


# ================================================================================================
# materials (ART_DIRECTION.md palette; sRGB hex; roughness / metalness from its PBR table)
# ================================================================================================
MATS = {
    # terrain
    "terrain": {"color": "#8e9a55", "rough": 0.93, "tile": 1.0},   # replaced at run time by the splat material (D13)
    "terrain_outer": {"color": "#ffffff", "rough": 0.95, "tile": 4.0},
    "backdrop": {"color": "#ffffff", "rough": 1.0, "tile": 50.0},
    "water": {"color": "#3f4a3c", "rough": 0.06, "alpha": 0.72, "tile": 4.0},
    # walls
    "plaster_lime": {"color": "#d9cbb3", "rough": 0.9, "tex": "plaster", "tile": 2.0},
    "plaster_cream": {"color": "#d6c8a8", "rough": 0.88, "tex": "plaster", "tile": 2.0},
    "plaster_white": {"color": "#e4e0d4", "rough": 0.9, "tex": "plaster_fine", "tile": 2.0},
    "oil_dado": {"color": "#5e7358", "rough": 0.55, "tex": "plaster_fine", "tile": 2.0},
    "tiles_white": {"color": "#dcdcd6", "rough": 0.25, "tex": "tiles_small", "tile": 0.6},
    "render_grey": {"color": "#9a968d", "rough": 0.9, "tex": "plaster", "tile": 2.0},
    "brick": {"color": "#a0573d", "rough": 0.85, "tex": "brick", "tile": 1.0},
    "brick_sooty": {"color": "#7a4e3c", "rough": 0.85, "tex": "brick", "tile": 1.0},
    "brick_limewash": {"color": "#d8d2c4", "rough": 0.9, "tex": "brick", "tile": 1.0},
    "stone": {"color": "#6f6d63", "rough": 0.9, "tex": "stone", "tile": 2.0},
    "concrete": {"color": "#a5a19a", "rough": 0.85, "tex": "concrete", "tile": 3.0},
    "concrete_dark": {"color": "#8c877e", "rough": 0.88, "tex": "concrete", "tile": 3.0},
    # roofs
    "roof_corr_dark": {"color": "#55524f", "rough": 0.62, "metal": 0.25, "tex": "corrugated", "normal": "corrugated_n", "tile": 1.0},
    "roof_corr_green": {"color": "#687468", "rough": 0.58, "metal": 0.25, "tex": "corrugated", "normal": "corrugated_n", "tile": 1.0},
    "roof_corr_rust": {"color": "#7a5a45", "rough": 0.75, "metal": 0.15, "tex": "corrugated", "normal": "corrugated_n", "tile": 1.0},
    "roof_tile_red": {"color": "#a5553a", "rough": 0.78, "tex": "rooftiles", "normal": "rooftiles_n", "tile": 1.0},
    "roof_slate": {"color": "#4b4f55", "rough": 0.7, "tex": "rooftiles", "tile": 0.8},
    "roof_eternit": {"color": "#8b8a84", "rough": 0.85, "tex": "rooftiles", "tile": 1.2},
    "roof_felt": {"color": "#3d3d3f", "rough": 0.9, "tex": "concrete", "tile": 2.0},
    "soffit": {"color": "#5a4231", "rough": 0.85, "tex": "planks", "tile": 1.0},
    # metals
    "steel_rust": {"color": "#8e5038", "rough": 0.8, "metal": 0.2, "tex": "rust", "tile": 1.5},
    "steel_grey": {"color": "#56616a", "rough": 0.6, "metal": 0.35, "tex": "rust_light", "tile": 1.5},
    "steel_blue": {"color": "#5d6b77", "rough": 0.55, "metal": 0.4, "tile": 1.0},
    "galvanized": {"color": "#a7abaa", "rough": 0.45, "metal": 0.8, "tile": 1.0},
    "frame_dark": {"color": "#3a3a3c", "rough": 0.5, "metal": 0.4, "tile": 1.0},
    "chainlink": {"color": "#8f9392", "rough": 0.5, "metal": 0.6, "tex": "chainlink", "alpha_test": 0.45, "double": True, "tile": 1.0},
    "mesh_deer": {"color": "#6f6a60", "rough": 0.7, "metal": 0.2, "tex": "deermesh", "alpha_test": 0.45, "double": True, "tile": 1.0},
    # timber
    "wood_cream": {"color": "#d6ccae", "rough": 0.6, "tex": "planks_fine", "tile": 1.0},
    "wood_grey": {"color": "#8c8579", "rough": 0.85, "tex": "planks", "tile": 1.0},
    "wood_dark": {"color": "#5a4231", "rough": 0.8, "tex": "planks", "tile": 1.0},
    "osb": {"color": "#b39468", "rough": 0.85, "tex": "osb", "tile": 1.2},
    # glass
    "glass": {"color": "#9aa7a6", "rough": 0.06, "alpha": 0.22, "double": True, "tile": 1.0},
    "glass_dark": {"color": "#1d2226", "rough": 0.12, "tile": 1.0},
    # floors / interiors
    "floor_concrete": {"color": "#8f8b83", "rough": 0.8, "tex": "concrete", "tile": 3.0},
    "floor_terrazzo": {"color": "#b3ada2", "rough": 0.5, "tex": "terrazzo", "tile": 2.0},
    "floor_parquet": {"color": "#946f4c", "rough": 0.55, "tex": "parquet", "tile": 1.0},
    "floor_boards": {"color": "#8a6a48", "rough": 0.65, "tex": "planks", "tile": 1.0},
    "floor_tiles": {"color": "#9a8a7a", "rough": 0.35, "tex": "tiles_floor", "tile": 1.0},
    "furn_wood": {"color": "#7a5a3a", "rough": 0.7, "tex": "planks_fine", "tile": 1.0},
    "furn_steel": {"color": "#4c5357", "rough": 0.55, "metal": 0.5, "tile": 1.0},
    "furn_green": {"color": "#56695a", "rough": 0.55, "metal": 0.3, "tile": 1.0},
    "furn_soft": {"color": "#6b6358", "rough": 0.95, "tile": 1.0},
    "furn_white": {"color": "#d8d6d0", "rough": 0.4, "tile": 1.0},
    # props (vertex-tinted)
    "prop": {"color": "#ffffff", "rough": 0.8, "tile": 1.0},
    "prop_paint": {"color": "#ffffff", "rough": 0.55, "metal": 0.25, "tex": "rust_light", "tile": 2.0},
    "prop_container": {"color": "#ffffff", "rough": 0.65, "metal": 0.3, "tex": "corrugated", "normal": "corrugated_n", "tile": 1.0},
    "tyre": {"color": "#1e1e1f", "rough": 0.9, "tile": 1.0},
    "hesco": {"color": "#bdb08f", "rough": 0.95, "tex": "hesco", "tile": 1.07},
    "logs": {"color": "#7a5a3c", "rough": 0.9, "tex": "logs", "tile": 0.6},
    "bales": {"color": "#c2aa70", "rough": 0.95, "tex": "straw", "tile": 1.0},
    "gravel_heap": {"color": "#9c978c", "rough": 0.98, "tex": "gravel", "tile": 2.0},
    # vegetation
    "hedge": {"color": "#4c6531", "rough": 0.95, "tex": "leaves", "tile": 1.5},
    "veg_core": {"color": "#2f3b22", "rough": 0.95, "tex": "leaves", "tile": 1.5},
    "shrub": {"color": "#56703a", "rough": 0.95, "tex": "leaves", "tile": 2.0},
    "bark": {"color": "#ffffff", "rough": 0.9, "tex": "bark", "tile": 1.0},
    "crown": {"color": "#ffffff", "rough": 0.92, "tex": "leaves", "tile": 3.0},
    # signs / markers
    "sign_mines": {"color": "#ffffff", "rough": 0.6, "tex": "sign_mines", "tile": 1.0},
    "sign_quarry": {"color": "#ffffff", "rough": 0.6, "tex": "sign_quarry", "tile": 1.0},
    "sign_checkpoint": {"color": "#ffffff", "rough": 0.6, "tex": "sign_checkpoint", "tile": 1.0},
    "sign_hunting": {"color": "#ffffff", "rough": 0.6, "tex": "sign_hunting", "tile": 1.0},
    "sign_road": {"color": "#ffffff", "rough": 0.6, "tex": "sign_road", "tile": 1.0},
    "sign_wall": {"color": "#ffffff", "rough": 0.85, "tex": "sign_wall", "alpha_test": 0.3, "tile": 1.0},
    "lamp_emissive": {"color": "#f3e7c8", "rough": 0.4, "emissive": "#6b5b3b", "tile": 1.0},
    "road_marking": {"color": "#d9d6cc", "rough": 0.45, "tex": "marking", "alpha_test": 0.5, "tile": 2.0},
}

SURFACES = ["grass", "asphalt", "gravel", "dirt", "mud", "forest_floor", "concrete", "paving", "wood", "metal", "water",
            "tiles", "stone"]
SURF_ID = {s: i for i, s in enumerate(SURFACES)}

# surface colours for the albedo map (sRGB)
SURF_COL = {
    "grass": "#8e9a55", "asphalt": "#46494e", "gravel": "#9c978c", "dirt": "#7a6448", "mud": "#4b3f31",
    "forest_floor": "#5a4a36", "concrete": "#a19d95", "paving": "#8a8680", "water": "#3f4a3c", "stone": "#6f6d63",
    "wood": "#7a5a3a", "metal": "#6a6e70", "tiles": "#a39d92",
}


# ================================================================================================
# small helpers
# ================================================================================================
def rng(seed):
    return np.random.default_rng(seed)


def value_noise(shape, cells, seed, octaves=4, persistence=0.5):
    """fBm value noise in [0, 1] on an array `shape`, `cells` = number of noise cells across the first octave."""
    h, w = shape
    out = np.zeros(shape, np.float64)
    amp = 1.0
    tot = 0.0
    r = rng(seed)
    for o in range(octaves):
        n = max(2, int(cells * 2 ** o))
        g = r.random((n + 1, n + 1))
        z = ndimage.zoom(g, ((h - 1) / n + 1e-9, (w - 1) / n + 1e-9), order=3, mode="nearest", grid_mode=False)
        z = z[:h, :w]
        if z.shape != shape:
            z = np.pad(z, ((0, h - z.shape[0]), (0, w - z.shape[1])), mode="edge")
        out += amp * z
        tot += amp
        amp *= persistence
    return np.clip(out / tot, 0, 1)


def tile_noise(n, cells, seed, octaves=4, persistence=0.5):
    """seamlessly tiling fBm value noise (n x n) in [0, 1]."""
    out = np.zeros((n, n))
    amp = 1.0
    tot = 0.0
    r = rng(seed)
    for o in range(octaves):
        c = max(2, int(cells * 2 ** o))
        g = r.random((c, c))
        g = np.pad(g, ((0, 1), (0, 1)), mode="wrap")
        z = ndimage.zoom(g, (n / c, n / c), order=1, grid_mode=False, mode="grid-wrap")[:n, :n]
        out += amp * z
        tot += amp
        amp *= persistence
    return out / tot


def png_bytes(arr, mode=None):
    im = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), mode)
    b = io.BytesIO()
    im.save(b, "PNG", optimize=True)
    return b.getvalue()


def jpg_bytes(arr, q=88):
    im = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    b = io.BytesIO()
    im.save(b, "JPEG", quality=q, subsampling=0, optimize=True)
    return b.getvalue()


def poly_signed_dist(poly, X, Y):
    """signed distance to a polygon (negative inside), vectorised over X, Y."""
    P = np.asarray(poly, float)
    inside = MPath(P).contains_points(np.column_stack([X.ravel(), Y.ravel()])).reshape(X.shape)
    d = np.full(X.shape, np.inf)
    n = len(P)
    for i in range(n):
        ax, ay = P[i]
        bx, by = P[(i + 1) % n]
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        t = np.clip(((X - ax) * dx + (Y - ay) * dy) / max(L2, 1e-12), 0, 1)
        d = np.minimum(d, np.hypot(X - (ax + t * dx), Y - (ay + t * dy)))
    return np.where(inside, -d, d)


def polyline_dist(pl, X, Y):
    """distance to a polyline and the arc length of the closest point (vectorised)."""
    P = np.asarray([p[:2] for p in pl], float)
    d = np.full(X.shape, np.inf)
    s = np.zeros(X.shape)
    acc = 0.0
    for i in range(len(P) - 1):
        ax, ay = P[i]
        bx, by = P[i + 1]
        dx, dy = bx - ax, by - ay
        L = math.hypot(dx, dy)
        if L < 1e-9:
            continue
        t = np.clip(((X - ax) * dx + (Y - ay) * dy) / (L * L), 0, 1)
        dd = np.hypot(X - (ax + t * dx), Y - (ay + t * dy))
        m = dd < d
        d = np.where(m, dd, d)
        s = np.where(m, acc + t * L, s)
        acc += L
    return d, s


# ================================================================================================
# terrain
# ================================================================================================
class Terrain:
    """0.5 m heightfield over the fine region (hard boundary + margin) and a 2 m field over the whole data square."""

    def __init__(self, L):
        self.L = L
        hard = Polygon(L["boundary"]["hard_polygon"])
        self.hard = hard
        self.soft = Polygon(L["boundary"]["soft_polygon"])
        self.region = hard.buffer(FINE_MARGIN, join_style=2)
        bx0, by0, bx1, by1 = self.region.bounds
        self.x0 = max(-175.0, math.floor(bx0 / RES) * RES)
        self.y0 = max(-175.0, math.floor(by0 / RES) * RES)
        self.x1 = min(175.0, math.ceil(bx1 / RES) * RES)
        self.y1 = min(175.0, math.ceil(by1 / RES) * RES)
        log(f"terrain: fine heightfield {self.x0}..{self.x1} x {self.y0}..{self.y1} @ {RES} m")
        self.X, self.Y, self.H = T.heightfield(L, RES, self.x0, self.x1, self.y0, self.y1)
        self.nx = self.X.shape[1]
        self.ny = self.X.shape[0]
        log(f"terrain: fine {self.nx} x {self.ny}; coarse @ {OUTER_RES} m")
        self.cX, self.cY, self.cH = T.heightfield(L, OUTER_RES, -176.0, 176.0, -176.0, 176.0)
        # cell mask: fine cells whose centre lies in the region
        cx = (self.X[:-1, :-1] + self.X[1:, 1:]) / 2
        cy = (self.Y[:-1, :-1] + self.Y[1:, 1:]) / 2
        self.cellX, self.cellY = cx, cy
        self.cell_in = MPath(np.array(self.region.exterior.coords)).contains_points(
            np.column_stack([cx.ravel(), cy.ravel()])).reshape(cx.shape)
        # no terrain under the ground floors of the main buildings (their floor base fills the footprint): no
        # coincident terrain at floor height (z-fighting, wrong footstep surface)
        for bp in L["buildings"]:
            fp = Polygon(bp["footprint_world"]).buffer(-0.3, join_style=2)
            if fp.is_empty:
                continue
            under = MPath(np.array(fp.exterior.coords)).contains_points(np.column_stack([cx.ravel(), cy.ravel()])).reshape(cx.shape)
            self.cell_in &= ~under

    def fine_z(self, x, y):
        """height on the triangulated fine grid (diagonal (i, j) -> (i + 1, j + 1)), vectorised."""
        x = np.asarray(x, float)
        y = np.asarray(y, float)
        fx = (x - self.x0) / RES
        fy = (y - self.y0) / RES
        i = np.clip(np.floor(fx).astype(int), 0, self.nx - 2)
        j = np.clip(np.floor(fy).astype(int), 0, self.ny - 2)
        u = np.clip(fx - i, 0, 1)
        v = np.clip(fy - j, 0, 1)
        H = self.H
        z00 = H[j, i]
        z10 = H[j, i + 1]
        z01 = H[j + 1, i]
        z11 = H[j + 1, i + 1]
        return np.where(u >= v, z00 + u * (z10 - z00) + v * (z11 - z10), z00 + v * (z01 - z00) + u * (z11 - z01))

    def coarse_z(self, x, y):
        x = np.asarray(x, float)
        y = np.asarray(y, float)
        fx = (x + 176.0) / OUTER_RES
        fy = (y + 176.0) / OUTER_RES
        n = self.cH.shape[0]
        i = np.clip(np.floor(fx).astype(int), 0, n - 2)
        j = np.clip(np.floor(fy).astype(int), 0, n - 2)
        u = np.clip(fx - i, 0, 1)
        v = np.clip(fy - j, 0, 1)
        H = self.cH
        return (H[j, i] * (1 - u) * (1 - v) + H[j, i + 1] * u * (1 - v) + H[j + 1, i] * (1 - u) * v + H[j + 1, i + 1] * u * v)

    def z(self, x, y):
        """ground height: fine grid inside the fine region, coarse outside."""
        x = np.atleast_1d(np.asarray(x, float))
        y = np.atleast_1d(np.asarray(y, float))
        inside = (x >= self.x0) & (x <= self.x1) & (y >= self.y0) & (y <= self.y1)
        out = self.coarse_z(x, y)
        if inside.any():
            out = np.where(inside, self.fine_z(x, y), out)
        return out

    def z1(self, x, y):
        return float(self.z(x, y)[0])


def surface_fields(L, X, Y):
    """priority-ordered surface features on points (X, Y): yields (priority, surface, d) with d <= 0 inside
    (signed distance-like fields, so they can be upsampled smoothly for the albedo map)."""
    feats = []
    stamps = {s["id"]: s for s in L["terrain"]["stamps"]}
    soft = L["boundary"]["soft_polygon"]
    # forest floor outside the soft boundary
    feats.append((20, "forest_floor", 2.0 - poly_signed_dist(soft, X, Y)))
    for f in L.get("fields", []):
        crop = (f.get("crop") or "").lower()
        surf = "grass" if ("hay" in crop or "meadow" in crop) else "dirt"
        feats.append((56, surf, poly_signed_dist(f["polygon"], X, Y)))
    for sa in L["spawn_areas"]:
        feats.append((58, "mud" if sa["team"] == "charlie" else "gravel", poly_signed_dist(sa["polygon"], X, Y)))
    pad_surf = {"PAD_NAVES": "paving", "PAD_DILNA": "gravel", "PAD_SKLAD_YARD": "concrete", "PAD_SKLAD": "gravel",
                "PAD_DUM_TERRACE": "grass"}
    for pid, s in stamps.items():
        if s["kind"] != "pad":
            continue
        surf = pad_surf.get(pid)
        if surf is None:
            ss = (s.get("surface") or "")
            surf = "gravel" if "gravel" in ss else ("grass" if "grass" in ss else None)
        if surf:
            pr = 60 if pid in pad_surf else 57
            feats.append((pr, surf, poly_signed_dist(s["polygon"], X, Y) - (0 if pid in pad_surf else 0.4)))
    # garden gravel paths around the house (1.0 m)
    for bp in L["buildings"]:
        if bp["id"] == "B_DUM":
            fp = Polygon(bp["footprint_world"]).buffer(1.0, join_style=2)
            feats.append((59, "gravel", poly_signed_dist(list(fp.exterior.coords), X, Y)))
    for d in L["ditches"]:
        dd, _ = polyline_dist(d["polyline"], X, Y)
        bw = d.get("bed_width", 0.6)
        if d["id"] == "MILLRACE":
            feats.append((71, "grass", dd - (bw / 2 + 1.5)))
        elif d["id"].startswith("DITCH_C"):
            feats.append((70, "mud", dd - (bw / 2 + 1.9)))
            feats.append((71, "stone", dd - bw / 2))
            feats.append((88, "water", dd - 0.12))
        else:
            feats.append((70, "mud", dd - (bw / 2 + 0.6)))
    uv = stamps.get("UVOZ_S")
    if uv:
        dd, _ = polyline_dist(uv["polyline"], X, Y)
        feats.append((72, "dirt", dd - (uv["bed_width"] / 2 + 0.3)))
    for p in L["paths"]:
        dd, _ = polyline_dist(p["xy"], X, Y)
        surf = p.get("surface", "gravel")
        surf = "gravel" if "gravel" in surf else ("dirt" if ("dirt" in surf or "earth" in surf) else ("grass" if "grass" in surf else "gravel"))
        feats.append((78 if surf == "gravel" else 76, surf, dd - p["width"] / 2))
    for t in L["tracks"]:
        dd, _ = polyline_dist(t["polyline"], X, Y)
        sid = t["id"]
        if sid == "DRIVE_DUM":
            feats.append((74, "concrete", dd - t["width"] / 2))
        elif sid in ("TRACK_C", "TRACK_E_RING"):
            feats.append((76, "dirt", dd - t["width"] / 2))
            feats.append((77, "grass", dd - 0.3))
            feats.append((76, "gravel", np.maximum(1.25 - dd, dd - t["width"] / 2)))
        else:
            feats.append((75, "gravel", dd - t["width"] / 2))
    for r in L["roads"]:
        dd, _ = polyline_dist(r["polyline"], X, Y)
        sh = r.get("shoulders", 0.75)
        if isinstance(sh, dict):
            sh = sh.get("width", 0.75)
        feats.append((78, "gravel", dd - (r["width"] / 2 + float(sh))))
        feats.append((80, "asphalt", dd - r["width"] / 2))
    for w in L["water"]:
        dd, _ = polyline_dist(w["polyline"], X, Y)
        feats.append((70, "mud", dd - (w["width_at_surface"] / 2 + 0.9)))
        feats.append((100, "water", dd - w["width_at_surface"] / 2))
    return feats


def surface_raster(L, X, Y, fields=None):
    best = np.full(X.shape, -1, np.int16)
    cls = np.full(X.shape, SURF_ID["grass"], np.uint8)
    for pr, surf, d in (fields if fields is not None else surface_fields(L, X, Y)):
        upd = (d <= 0) & (pr >= best)
        cls[upd] = SURF_ID[surf]
        best[upd] = pr
    return cls


def build_road_markings(sc, L, terr):
    """worn white road markings (edge lines 0.12 m at 0.25 m from the edge, centre dashes 3 m / 6 m gap) as thin
    render-only strips 2 cm above the 0.5 m terrain triangles (they replace the markings painted into the old
    albedo map). Same layout as the old albedo markings (no markings in the end caps on the square)."""
    m = sc.mb("road_marking")
    for r in L["roads"]:
        P = np.array([p[:2] for p in r["polyline"]], float)
        seg = np.linalg.norm(np.diff(P, axis=0), axis=1)
        total = float(seg.sum())
        hw = r["width"] / 2
        s_all = np.arange(0.0, total + 1e-9, 0.5)
        cum = np.concatenate([[0], np.cumsum(seg)])
        idx = np.clip(np.searchsorted(cum, s_all, side="right") - 1, 0, len(seg) - 1)
        t = (s_all - cum[idx]) / np.maximum(seg[idx], 1e-9)
        C = P[idx] + (P[idx + 1] - P[idx]) * t[:, None]
        D = (P[idx + 1] - P[idx]) / np.maximum(seg[idx], 1e-9)[:, None]
        # smooth the direction at the polyline corners
        D = ndimage.uniform_filter1d(D, 5, axis=0, mode="nearest")
        D /= np.maximum(np.linalg.norm(D, axis=1, keepdims=True), 1e-9)
        Nn = np.column_stack([-D[:, 1], D[:, 0]])
        inner = (s_all > hw + 0.5) & (s_all < total - hw - 0.5)

        def strip(off, width, keep):
            a = C + Nn * (off - width / 2)
            b = C + Nn * (off + width / 2)
            for k in range(len(s_all) - 1):
                if not (keep[k] and keep[k + 1]):
                    continue
                q = np.array([a[k], a[k + 1], b[k + 1], b[k]])
                z = terr.z(q[:, 0], q[:, 1]) + 0.02
                V = np.column_stack([q, z])
                m.poly(V, n=np.array([0.0, 0.0, 1.0]))
        dash = (s_all % 9.0) < 3.0
        strip(hw - 0.25, 0.12, inner)
        strip(-(hw - 0.25), 0.12, inner)
        strip(0.0, 0.12, inner & dash)


# ================================================================================================
# procedural placeholder textures (tiling, deterministic)
# ================================================================================================
def _lum(base, var):
    """luminance multiplier map around 1 -> sRGB u8 grey (texture multiplies the material colour)."""
    v = np.clip(base + var, 0, 1.25) / 1.25
    return np.repeat((v * 255)[..., None], 3, axis=2)


def tex_rgb(name, n=256):
    """returns (rgb_or_rgba uint8 array, is_colour) for a named texture."""
    s = SEED + sum(ord(c) for c in name)
    r = rng(s)
    if name == "plaster":
        a = tile_noise(n, 4, s, 5)
        b = tile_noise(n, 24, s + 1, 3)
        speck = (r.random((n, n)) > 0.985) * 0.08
        return _lum(1.0, (a - 0.5) * 0.16 + (b - 0.5) * 0.08 - speck), False
    if name == "plaster_fine":
        a = tile_noise(n, 6, s, 4)
        return _lum(1.0, (a - 0.5) * 0.06), False
    if name == "concrete":
        a = tile_noise(n, 5, s, 5)
        b = tile_noise(n, 40, s + 1, 2)
        return _lum(1.0, (a - 0.5) * 0.14 + (b - 0.5) * 0.08), False
    if name == "terrazzo":
        a = tile_noise(n, 30, s, 2)
        sp = r.random((n, n))
        v = (a - 0.5) * 0.06 + np.where(sp > 0.93, 0.12, 0) - np.where(sp < 0.06, 0.14, 0)
        return _lum(1.0, v), False
    if name == "stone":
        pts = r.random((70, 2)) * n
        yy, xx = np.mgrid[0:n, 0:n]
        best = np.full((n, n), 1e9)
        second = np.full((n, n), 1e9)
        idx = np.zeros((n, n), int)
        for k, (px, py) in enumerate(pts):
            dx = np.minimum(np.abs(xx - px), n - np.abs(xx - px))
            dy = np.minimum(np.abs(yy - py), n - np.abs(yy - py))
            d = np.hypot(dx, dy)
            m = d < best
            second = np.where(m, best, np.minimum(second, d))
            idx = np.where(m, k, idx)
            best = np.where(m, d, best)
        shade = r.random(70)[idx]
        edge = np.clip((second - best) / 3.0, 0, 1)
        v = 0.78 + 0.3 * shade - (1 - edge) * 0.35 + (tile_noise(n, 20, s, 2) - 0.5) * 0.1
        return _lum(v, 0), False
    if name in ("brick",):
        img = np.zeros((n, n, 3))
        rows = 13
        rh = n / rows
        mort = np.array(hex_rgb("#a59c8c"))
        img[:] = mort
        base = np.array(hex_rgb("#a0573d"))
        for j in range(rows):
            y0 = int(j * rh)
            y1 = int((j + 1) * rh - rh * 0.13)
            off = 0.5 if j % 2 else 0.0
            for k in range(-1, 4):
                x0 = int((k + off) * n / 4 + n * 0.012)
                x1 = int((k + 1 + off) * n / 4 - n * 0.012)
                c = base * (0.82 + 0.3 * r.random()) * np.array([1, 0.95 + 0.1 * r.random(), 0.95])
                for xa in range(x0, x1):
                    img[y0:y1, xa % n] = c
        img *= (0.93 + 0.14 * tile_noise(n, 16, s, 3))[..., None]
        return img * 255, True
    if name == "corrugated":
        a = tile_noise(n, 3, s, 4)
        streak = tile_noise(n, 12, s + 2, 2)
        streak = np.repeat(streak[:1], n, axis=0) * 0.6 + streak * 0.4
        return _lum(1.0, (a - 0.5) * 0.1 + (streak - 0.5) * 0.18), False
    if name == "corrugated_n":
        x = np.arange(n) / n
        waves = 13
        dz = np.cos(2 * np.pi * waves * x) * 0.55
        nx_ = -dz
        nrm = np.stack([np.repeat(nx_[None], n, 0), np.zeros((n, n)), np.ones((n, n))], -1)
        nrm /= np.linalg.norm(nrm, axis=-1, keepdims=True)
        return (nrm * 0.5 + 0.5) * 255, True
    if name == "rooftiles":
        yy, xx = np.mgrid[0:n, 0:n] / n
        row = (yy * 3) % 1
        col = (xx * 3.3 + np.floor(yy * 3) * 0.5) % 1
        v = 1.0 - 0.25 * (row < 0.08) - 0.12 * (np.abs(col - 0.5) > 0.46) + 0.12 * row
        v += (tile_noise(n, 10, s, 3) - 0.5) * 0.18
        return _lum(v * 0.9, 0), False
    if name == "rooftiles_n":
        yy = np.mgrid[0:n, 0:n][0] / n
        row = (yy * 3) % 1
        ny_ = np.where(row < 0.1, -0.8, 0.25)
        nrm = np.stack([np.zeros((n, n)), ny_, np.ones((n, n))], -1)
        nrm /= np.linalg.norm(nrm, axis=-1, keepdims=True)
        return (nrm * 0.5 + 0.5) * 255, True
    if name in ("planks", "planks_fine"):
        yy, xx = np.mgrid[0:n, 0:n] / n
        w = 8 if name == "planks" else 6
        bi = np.floor(xx * w).astype(int)
        shade = r.random(w)[bi]
        grain = tile_noise(n, 4, s, 4)
        grain = np.repeat(grain[:, :1], n, axis=1) * 0.3 + grain * 0.7
        gap = np.abs(((xx * w) % 1) - 0.5) > (0.46 if name == "planks" else 0.48)
        v = 0.85 + 0.2 * shade + (grain - 0.5) * 0.2 - 0.35 * gap
        return _lum(v, 0), False
    if name == "parquet":
        yy, xx = np.mgrid[0:n, 0:n] / n
        bx = np.floor(xx * 8)
        by = np.floor(yy * 2 + (bx % 2) * 0.5)
        shade = (np.sin(bx * 12.9898 + by * 78.233) * 43758.5453) % 1
        v = 0.85 + 0.25 * shade + (tile_noise(n, 16, s, 2) - 0.5) * 0.1
        return _lum(v, 0), False
    if name in ("tiles_small", "tiles_floor"):
        yy, xx = np.mgrid[0:n, 0:n] / n
        k = 4 if name == "tiles_small" else 3
        grout = (np.abs((xx * k) % 1 - 0.5) > 0.465) | (np.abs((yy * k) % 1 - 0.5) > 0.465)
        v = 1.0 - 0.25 * grout + (tile_noise(n, 8, s, 2) - 0.5) * 0.06
        return _lum(v, 0), False
    if name == "osb":
        a = tile_noise(n, 30, s, 3)
        b = r.random((n, n))
        return _lum(0.95, (a - 0.5) * 0.35 + (b - 0.5) * 0.08), False
    if name in ("rust", "rust_light"):
        a = tile_noise(n, 5, s, 5)
        b = tile_noise(n, 30, s + 1, 3)
        amt = 0.3 if name == "rust" else 0.12
        return _lum(1.0, (a - 0.5) * amt + (b - 0.5) * amt * 0.5), False
    if name in ("chainlink", "deermesh"):
        yy, xx = np.mgrid[0:n, 0:n] / n
        if name == "chainlink":
            k = 16
            u = (xx + yy) * k
            v = (xx - yy) * k
            wire = (np.abs(u % 1 - 0.5) > 0.42) | (np.abs(v % 1 - 0.5) > 0.42)
        else:
            k = 7
            wire = (np.abs((xx * k) % 1 - 0.5) > 0.44) | (np.abs((yy * k) % 1 - 0.5) > 0.44)
        rgba = np.zeros((n, n, 4))
        rgba[..., :3] = 235
        rgba[..., 3] = np.where(wire, 255, 0)
        return rgba, True
    if name == "hesco":
        yy, xx = np.mgrid[0:n, 0:n] / n
        grid = (np.abs((xx * 10) % 1 - 0.5) > 0.44) | (np.abs((yy * 10) % 1 - 0.5) > 0.44)
        edge = (xx < 0.02) | (xx > 0.98)
        v = 1.0 + (tile_noise(n, 6, s, 3) - 0.5) * 0.25 - 0.3 * grid - 0.4 * edge
        return _lum(v, 0), False
    if name == "logs":
        yy, xx = np.mgrid[0:n, 0:n] / n
        v = 0.9 + 0.2 * np.sin(yy * 2 * np.pi * 3) + (tile_noise(n, 10, s, 3) - 0.5) * 0.3
        return _lum(v, 0), False
    if name in ("straw", "gravel"):
        a = tile_noise(n, 40, s, 2)
        b = r.random((n, n))
        return _lum(0.95, (a - 0.5) * 0.2 + (b - 0.5) * (0.35 if name == "gravel" else 0.15)), False
    if name == "leaves":
        a = tile_noise(n, 10, s, 4)
        b = tile_noise(n, 48, s + 1, 2)
        v = 0.75 + 0.45 * a + (b - 0.5) * 0.35
        return _lum(v, 0), False
    if name == "marking":
        # worn road paint: alpha = paint left (cracks and abrasion), colour = slightly dirty white
        a = tile_noise(n, 6, s, 5)
        b = tile_noise(n, 40, s + 1, 3)
        paint = np.clip((a * 0.6 + b * 0.4 - 0.3) * 4.0, 0, 1)
        rgba = np.zeros((n, n, 4))
        rgba[..., :3] = (230 - 25 * b[..., None]) * np.ones(3)
        rgba[..., 3] = np.where(paint > 0.35, 255, 0)
        return rgba, True
    if name == "bark":
        a = tile_noise(n, 12, s, 3)
        a = np.repeat(a[:1], n, 0) * 0.7 + a * 0.3
        return _lum(0.95, (a - 0.5) * 0.4), False
    raise KeyError(name)


def sign_texture(kind):
    """sign boards with Czech text (fictional names only)."""
    W, H = 512, 256
    font_b = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    font_r = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    fb = ImageFont.truetype(font_b, 44) if os.path.exists(font_b) else ImageFont.load_default()
    fs = ImageFont.truetype(font_b, 30) if os.path.exists(font_b) else ImageFont.load_default()
    fr = ImageFont.truetype(font_r, 26) if os.path.exists(font_r) else ImageFont.load_default()
    img = Image.new("RGB", (W, H), (240, 238, 230))
    d = ImageDraw.Draw(img)
    if kind == "sign_mines":
        d.rectangle([0, 0, W, H], fill=(192, 57, 43))
        d.rectangle([10, 10, W - 10, H - 10], outline=(250, 250, 245), width=6)
        d.text((W / 2, 70), "POZOR! MINY", font=fb, fill=(250, 250, 245), anchor="mm")
        d.text((W / 2, 135), "VOJENSKÝ PROSTOR", font=fs, fill=(250, 250, 245), anchor="mm")
        d.text((W / 2, 190), "VSTUP ZAKÁZÁN", font=fs, fill=(250, 250, 245), anchor="mm")
    elif kind == "sign_quarry":
        d.rectangle([0, 0, W, H], fill=(232, 178, 26))
        d.text((W / 2, 80), "Štěrkovna Kalný Vrch", font=fs, fill=(20, 20, 20), anchor="mm")
        d.text((W / 2, 150), "VSTUP ZAKÁZÁN", font=fb, fill=(20, 20, 20), anchor="mm")
    elif kind == "sign_checkpoint":
        d.rectangle([0, 0, W, H], fill=(245, 245, 240))
        d.rectangle([8, 8, W - 8, H - 8], outline=(192, 57, 43), width=12)
        d.text((W / 2, 95), "KONTROLNÍ", font=fb, fill=(192, 57, 43), anchor="mm")
        d.text((W / 2, 165), "STANOVIŠTĚ - STŮJ!", font=fs, fill=(30, 30, 30), anchor="mm")
    elif kind == "sign_hunting":
        d.rectangle([0, 0, W, H], fill=(46, 85, 50))
        d.text((W / 2, 95), "HONITBA", font=fb, fill=(245, 245, 235), anchor="mm")
        d.text((W / 2, 165), "vstup se psy zakázán", font=fr, fill=(245, 245, 235), anchor="mm")
    elif kind == "sign_road":
        d.rectangle([0, 0, W, H], fill=(245, 245, 240))
        d.rectangle([8, 8, W - 8, H - 8], outline=(20, 20, 20), width=6)
        d.text((W / 2, H / 2), "Nové Kalno 2 km", font=fb, fill=(20, 20, 20), anchor="mm")
    arr = np.array(img)
    return arr


def wall_sign_texture(text, W=1024, H=128):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    fp = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    size = 80
    f = ImageFont.truetype(fp, size) if os.path.exists(fp) else ImageFont.load_default()
    while os.path.exists(fp) and d.textlength(text, font=f) > W - 20 and size > 20:
        size -= 4
        f = ImageFont.truetype(fp, size)
    d.text((W / 2, H / 2), text, font=f, fill=(58, 52, 46, 215), anchor="mm")
    return np.array(img)


class MaterialBank:
    """builds glTF materials (+ embedded textures) on demand for one GLB."""

    def __init__(self, glb, bake=True):
        self.glb = glb
        self.idx = {}
        self.tex = {}
        self.bake = bake

    def texture(self, name, arr=None, colour=False, jpeg=False):
        if name in self.tex:
            return self.tex[name]
        if arr is None:
            arr, colour = tex_rgb(name)
        if arr.shape[-1] == 4:
            data = png_bytes(arr, "RGBA")
            mime = "image/png"
        elif jpeg:
            data = jpg_bytes(arr, 90)
            mime = "image/jpeg"
        else:
            data = png_bytes(arr, "RGB")
            mime = "image/png"
        img = self.glb.add_image(data, mime)
        t = self.glb.add_texture(img)
        self.tex[name] = t
        return t

    def get(self, key, extra_tex=None):
        if key in self.idx:
            return self.idx[key]
        m = MATS[key]
        col = list(srgb_to_linear(np.array(hex_rgb(m["color"])))) + [m.get("alpha", 1.0)]
        mat = {"name": key, "pbrMetallicRoughness": {"baseColorFactor": [round(float(c), 5) for c in col],
                                                      "metallicFactor": m.get("metal", 0.0), "roughnessFactor": m.get("rough", 0.8)}}
        tex = m.get("tex")
        if tex:
            if tex.startswith("sign_"):
                arr = wall_sign_texture(extra_tex) if tex == "sign_wall" else sign_texture(tex)
                t = self.texture(key if tex == "sign_wall" else tex, arr, True)
                mat["pbrMetallicRoughness"]["baseColorFactor"] = [1, 1, 1, 1]
            elif tex == "albedo":
                t = self.texture("albedo", extra_tex, True, jpeg=True)
                mat["pbrMetallicRoughness"]["baseColorFactor"] = [1, 1, 1, 1]
            else:
                arr, colour = tex_rgb(tex)
                t = self.texture(tex, arr, colour)
                if colour and tex not in ("chainlink", "deermesh"):
                    mat["pbrMetallicRoughness"]["baseColorFactor"] = [1, 1, 1, col[3]]
            mat["pbrMetallicRoughness"]["baseColorTexture"] = {"index": t}
        if m.get("normal"):
            arr, _ = tex_rgb(m["normal"])
            mat["normalTexture"] = {"index": self.texture(m["normal"], arr, True), "scale": 0.8}
        if m.get("alpha", 1.0) < 1.0:
            mat["alphaMode"] = "BLEND"
        if m.get("alpha_test"):
            mat["alphaMode"] = "MASK"
            mat["alphaCutoff"] = m["alpha_test"]
        if m.get("double"):
            mat["doubleSided"] = True
        if m.get("emissive"):
            mat["emissiveFactor"] = [round(float(c), 4) for c in srgb_to_linear(np.array(hex_rgb(m["emissive"])))]
        mat["extras"] = {"iv": {"key": key}}
        self.idx[key] = self.glb.add_material(mat)
        return self.idx[key]


# ================================================================================================
# polygon helpers
# ================================================================================================
def dedupe(pts, eps=1e-6):
    out = []
    for p in pts:
        if not out or math.hypot(p[0] - out[-1][0], p[1] - out[-1][1]) > eps:
            out.append(tuple(p))
    if len(out) > 1 and math.hypot(out[0][0] - out[-1][0], out[0][1] - out[-1][1]) <= eps:
        out.pop()
    return out


def earcut(pts):
    """ear clipping of a simple polygon (2D list), returns index triples (CCW)."""
    P = [tuple(p) for p in pts]
    n = len(P)
    if n < 3:
        return []
    area = sum(P[i][0] * P[(i + 1) % n][1] - P[(i + 1) % n][0] * P[i][1] for i in range(n))
    idx = list(range(n)) if area > 0 else list(range(n))[::-1]
    tris = []

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    guard = 0
    while len(idx) > 3 and guard < 10000:
        guard += 1
        ear = False
        for k in range(len(idx)):
            i0, i1, i2 = idx[k - 1], idx[k], idx[(k + 1) % len(idx)]
            a, b, c = P[i0], P[i1], P[i2]
            if cross(a, b, c) <= 1e-12:
                continue
            ok = True
            for j in idx:
                if j in (i0, i1, i2):
                    continue
                p = P[j]
                if cross(a, b, p) >= -1e-12 and cross(b, c, p) >= -1e-12 and cross(c, a, p) >= -1e-12:
                    ok = False
                    break
            if ok:
                tris.append((i0, i1, i2))
                idx.pop(k)
                ear = True
                break
        if not ear:
            break
    if len(idx) == 3:
        tris.append(tuple(idx))
    return tris


def rect_strips(poly):
    """decompose an axis-aligned (possibly holed) shapely polygon into rectangles (x strips)."""
    out = []
    geoms = poly.geoms if poly.geom_type == "MultiPolygon" else [poly]
    for g in geoms:
        if g.is_empty:
            continue
        bx0, by0, bx1, by1 = g.bounds
        xs = sorted(set([round(v[0], 4) for v in g.exterior.coords] + [round(v[0], 4) for r_ in g.interiors for v in r_.coords]))
        for xa, xb in zip(xs[:-1], xs[1:]):
            strip = g.intersection(sbox(xa, by0 - 1, xb, by1 + 1))
            parts = [strip] if strip.geom_type == "Polygon" else [q for q in getattr(strip, "geoms", []) if q.geom_type == "Polygon"]
            for q in parts:
                if q.area < 1e-4:
                    continue
                out.append(q.bounds)
    return out


# ================================================================================================
# main buildings
# ================================================================================================
FLOOR_MAT = [("parquet", "floor_parquet"), ("timber", "floor_boards"), ("terrazzo", "floor_terrazzo"), ("tiles", "floor_tiles"),
             ("vinyl", "floor_tiles"), ("concrete", "floor_concrete")]
FLOOR_SURF = {"floor_parquet": "wood", "floor_boards": "wood", "floor_terrazzo": "tiles", "floor_tiles": "tiles", "floor_concrete": "concrete"}


def floor_mat(fm):
    f = (fm or "").lower()
    for k, v in FLOOR_MAT:
        if k in f:
            return v
    return "floor_concrete"


def finish_layers(fin, building_id):
    """wall finish -> [(z_top_rel_or_None, material)] from the floor up."""
    f = (fin or "").lower()
    import re
    m = re.search(r"_(\d{3,4})$", f)
    split = int(m.group(1)) / 1000.0 if m else None
    if "green_oil" in f:
        return [(split or 1.5, "oil_dado"), (None, "plaster_white")]
    if f.startswith("tiles"):
        return [(split or 1.5, "tiles_white"), (None, "plaster_white")]
    if "render_lime_cream" in f:
        return [(None, "plaster_cream")]
    if "peeling_to_red_brick" in f or "render_lime" in f:
        return [(None, "plaster_lime")]
    if "brick_red" in f:
        return [(None, "brick_sooty")]
    if "brick_limewash" in f:
        return [(None, "brick_limewash")]
    return [(None, "plaster_white")]


class BuildingCtx:
    def __init__(self, sc, bp, bd, terr):
        self.sc = sc
        self.bp = bp
        self.bd = bd
        self.terr = terr
        self.c0 = bp["position"][:2]
        self.rot = bp["rotation_deg"]
        self.zf = bp["position"][2]
        self.lv = {l["id"]: l for l in bd["levels"]}
        self.walls = {w["id"]: w for w in bd["walls"]}

    def W(self, p):
        return xf(self.c0, self.rot, p)

    def Wz(self, p, z):
        x, y = xf(self.c0, self.rot, p)
        return (x, y, self.zf + z)

    def lvz(self, lid):
        if lid in self.lv:
            return self.lv[lid]["floor_z"]
        return 0.0


def layered_face(sc, key_layers, a, b, z0, z1, zbase, sub=1.0):
    """vertical quad a->b (world xy) from z0 to z1 split into finish layers (heights relative to zbase)."""
    zc = z0
    for top_rel, key in key_layers:
        zt = z1 if top_rel is None else min(z1, zbase + top_rel)
        if zt > zc + 1e-4:
            sc.face(key, [(a[0], a[1], zc), (b[0], b[1], zc), (b[0], b[1], zt), (a[0], a[1], zt)], sub=sub)
            zc = zt
        if zc >= z1 - 1e-4:
            break


def brick_patches(sc, A, B, Z0, Z1, zb, key):
    """exposed brick where the lime render has fallen off (refs 02, 04: plinth, corners, under the eaves): a few
    brick quads 4 mm proud of the facade, deterministic per wall piece."""
    L = math.hypot(B[0] - A[0], B[1] - A[1])
    if L < 0.9 or Z1 - Z0 < 0.8:
        return
    h = int(hashlib.sha256(key.encode()).hexdigest()[:8], 16)
    r = rng(h)
    ux, uy = (B[0] - A[0]) / L, (B[1] - A[1]) / L
    nx, ny = uy, -ux  # outward (right side of A->B = exterior)
    n = int(r.integers(0, 3)) if L > 2.0 else int(r.integers(0, 2))
    for k in range(n):
        wdt = float(r.uniform(0.35, min(1.3, L * 0.6)))
        hgt = float(r.uniform(0.25, min(0.9, Z1 - Z0 - 0.1)))
        u = float(r.uniform(0.05, max(0.06, L - wdt - 0.05)))
        where = r.random()
        if where < 0.45:
            z0 = zb + float(r.uniform(0.05, 0.4))           # plinth band
        elif where < 0.75:
            z0 = Z1 - hgt - float(r.uniform(0.05, 0.3))     # under the eaves / lintels
        else:
            z0 = float(r.uniform(Z0 + 0.2, max(Z0 + 0.25, Z1 - hgt - 0.2)))
        z0 = max(Z0 + 0.02, z0)
        z1 = min(Z1 - 0.02, z0 + hgt)
        if z1 - z0 < 0.15:
            continue
        o = 0.004
        p0 = (A[0] + ux * u + nx * o, A[1] + uy * u + ny * o)
        p1 = (A[0] + ux * (u + wdt) + nx * o, A[1] + uy * (u + wdt) + ny * o)
        sc.face("brick", [(p0[0], p0[1], z0), (p1[0], p1[1], z0), (p1[0], p1[1], z1), (p0[0], p0[1], z1)])


def wall_box(ctx, w, u0, u1, z0, z1, ext_layers, int_layers, end_key, top_key, zbase, bottom=False, cls="main", surface="concrete"):
    """one construction box of a wall with per-face finishes (local wall frame -> world)."""
    sc = ctx.sc
    sx, sy, ux, uy, nx, ny, Lw = C.wall_frame(w)
    t = w["thickness"] / 2
    A = ctx.W((sx + ux * u0 - nx * t, sy + uy * u0 - ny * t))
    B = ctx.W((sx + ux * u1 - nx * t, sy + uy * u1 - ny * t))
    Cc = ctx.W((sx + ux * u1 + nx * t, sy + uy * u1 + ny * t))
    D = ctx.W((sx + ux * u0 + nx * t, sy + uy * u0 + ny * t))
    Z0 = ctx.zf + z0
    Z1 = ctx.zf + z1
    zb = ctx.zf + zbase
    layered_face(sc, ext_layers, A, B, Z0, Z1, zb)
    layered_face(sc, int_layers, Cc, D, Z0, Z1, zb)
    if ext_layers and ext_layers[-1][1] == "plaster_lime" and w.get("kind") == "external":
        brick_patches(sc, A, B, Z0, Z1, zb, f"{w['id']}:{u0:.2f}")
    sc.face(end_key, [(B[0], B[1], Z0), (Cc[0], Cc[1], Z0), (Cc[0], Cc[1], Z1), (B[0], B[1], Z1)])
    sc.face(end_key, [(D[0], D[1], Z0), (A[0], A[1], Z0), (A[0], A[1], Z1), (D[0], D[1], Z1)])
    sc.face(top_key, [(A[0], A[1], Z1), (B[0], B[1], Z1), (Cc[0], Cc[1], Z1), (D[0], D[1], Z1)])
    if bottom:
        sc.face(top_key, [(D[0], D[1], Z0), (Cc[0], Cc[1], Z0), (B[0], B[1], Z0), (A[0], A[1], Z0)])
    sc.prism([A, B, Cc, D], Z0, Z1, mat=False, cls=cls, surface=surface, render=False)


def local_box(ctx, cx, cy, lx, ly, rot_local, z0, z1, **kw):
    """oriented box given in building-local coordinates (rot relative to the building)."""
    wx, wy = ctx.W((cx, cy))
    ctx.sc.obox(wx, wy, lx, ly, ctx.rot + rot_local, ctx.zf + z0, ctx.zf + z1, **kw)


def wall_uv_box(ctx, w, u0, u1, n0, n1, z0, z1, **kw):
    """box in the wall frame: u along the wall, n across it (left normal), z relative to the building floor."""
    sx, sy, ux, uy, nx, ny, Lw = C.wall_frame(w)
    pts = [ctx.W((sx + ux * u + nx * n, sy + uy * u + ny * n)) for u, n in ((u0, n0), (u1, n0), (u1, n1), (u0, n1))]
    ctx.sc.prism(pts, ctx.zf + z0, ctx.zf + z1, **kw)


def build_openings(ctx, w, zl, external):
    sc = ctx.sc
    bd = ctx.bd
    t = w["thickness"] / 2
    ext_sign = -1.0 if external else 0.0
    for o in bd["openings"]:
        if o["wall_id"] != w["id"]:
            continue
        a = o["offset_from_start"]
        b = a + o["width"]
        typ = o["type"]
        zs = zl + o.get("sill_height", 0.0)
        zh = zl + o.get("head_height", 2.1)
        if typ in ("window", "interior_window"):
            rd = o.get("reveal_depth", 0.12)
            d = (-t + rd + 0.03) if external else 0.0
            fw = 0.06
            dark = "wood_cream" if "timber" in (o.get("glazing") or "") else "frame_dark"
            # frame
            for (u0, u1, z0, z1) in ((a, a + fw, zs, zh), (b - fw, b, zs, zh), (a, b, zs, zs + fw), (a, b, zh - fw, zh)):
                wall_uv_box(ctx, w, u0, u1, d - 0.03, d + 0.03, z0 - ctx.zf, z1 - ctx.zf, mat=dark, collide=False)
            # glazing bars
            g = o.get("glazing") or ""
            import re
            mm = re.search(r"(\d+)x(\d+)", g)
            if mm and "multipane" in g:
                cols, rows = int(mm.group(1)), int(mm.group(2))
                for k in range(1, cols):
                    u = a + (b - a) * k / cols
                    wall_uv_box(ctx, w, u - 0.012, u + 0.012, d - 0.015, d + 0.015, zs - ctx.zf, zh - ctx.zf, mat="frame_dark", collide=False)
                for k in range(1, rows):
                    z = zs + (zh - zs) * k / rows
                    wall_uv_box(ctx, w, a, b, d - 0.015, d + 0.015, z - 0.012 - ctx.zf, z + 0.012 - ctx.zf, mat="frame_dark", collide=False)
            elif "casement" in g:
                u = (a + b) / 2
                wall_uv_box(ctx, w, u - 0.03, u + 0.03, d - 0.03, d + 0.03, zs - ctx.zf, zh - ctx.zf, mat=dark, collide=False)
                z = zs + (zh - zs) * 0.72
                wall_uv_box(ctx, w, a, b, d - 0.03, d + 0.03, z - 0.03 - ctx.zf, z + 0.03 - ctx.zf, mat=dark, collide=False)
            # glass (render) + capsule plane (collision 'move': bullets and sight pass)
            sx, sy, ux, uy, nx, ny, Lw = C.wall_frame(w)
            p0 = ctx.W((sx + ux * a + nx * d, sy + uy * a + ny * d))
            p1 = ctx.W((sx + ux * b + nx * d, sy + uy * b + ny * d))
            sc.face("glass", [(p0[0], p0[1], zs), (p1[0], p1[1], zs), (p1[0], p1[1], zh), (p0[0], p0[1], zh)])
            wall_uv_box(ctx, w, a, b, d - 0.02, d + 0.02, zs - ctx.zf, zh - ctx.zf, mat=False, cls="move", surface="glass", render=False)
            if external:
                so = o.get("sill_overhang", 0.04)
                wall_uv_box(ctx, w, a - 0.04, b + 0.04, -t - so, -t + rd, zs - 0.05 - ctx.zf, zs - ctx.zf, mat="concrete", collide=False)
        elif typ in ("door", "double_door"):
            jb = o.get("frame_jamb", 0.05)
            fh = o.get("frame_head", 0.05)
            fk = "steel_blue"
            for (u0, u1, z0, z1) in ((a, a + jb, zl, zh), (b - jb, b, zl, zh), (a, b, zh - fh, zh)):
                wall_uv_box(ctx, w, u0, u1, -t - 0.01, t + 0.01, z0 - ctx.zf, z1 - ctx.zf, mat=fk, collide=False)
            wall_uv_box(ctx, w, a, b, -t, t, zl - ctx.zf, zl + 0.015 - ctx.zf, mat="concrete_dark", collide=False)
            lp = C.leaf_rest_poly(w, o)
            leaf = o.get("leaf", {})
            lm = (leaf.get("material") or "").lower()
            key = "steel_rust" if ("rust" in lm or "red_oxide" in lm) else ("steel_grey" if "steel" in lm else ("wood_cream" if ("white" in lm or "cream" in lm) else "wood_dark"))
            for gpoly in (lp.geoms if lp.geom_type == "MultiPolygon" else [lp]):
                pts = [ctx.W(p) for p in list(gpoly.exterior.coords)[:-1]]
                sc.prism(pts, zl + 0.01, zl + o.get("clear_height", 2.1), mat=key, cls="main", surface="metal" if "steel" in key else "wood")
        elif typ == "sliding_door":
            st = o.get("state", {})
            if not o["passes"]["movement"]:
                wall_uv_box(ctx, w, a, b, -t * 0.4, t * 0.4, zl - ctx.zf, zh - ctx.zf, mat="steel_grey", cls="main", surface="metal")
            lr = o.get("leaf_rest")
            if lr and st.get("open"):
                side = -1.0 if lr["side"] == "right" else 1.0
                off0 = t + lr["offset_from_face"]
                off1 = off0 + lr["thickness"]
                u0, u1 = lr["u"]
                n0, n1 = sorted((side * off0, side * off1))
                wall_uv_box(ctx, w, u0, u1, n0, n1, 0.0 + (zl - ctx.zf), lr["height"] + (zl - ctx.zf), mat="steel_grey", cls="main", surface="metal")
            # guide rail above the opening (outside face)
            wall_uv_box(ctx, w, a - 0.3, b + 3.9 if lr else b + 0.3, -t - 0.12, -t, zh + 0.05 - ctx.zf, zh + 0.15 - ctx.zf, mat="galvanized", collide=False)
        elif typ == "vent":
            wall_uv_box(ctx, w, a, b, -t + 0.05, t - 0.05, zs - ctx.zf, zh - ctx.zf, mat="frame_dark", cls="main", surface="metal")


def gable_wall(ctx, w, zl, ext_layers, int_layers):
    """gable (walls[].gable.construction_polygons in (u, z) of the wall plane) extruded by the wall thickness."""
    sc = ctx.sc
    g = w["gable"]
    sx, sy, ux, uy, nx, ny, Lw = C.wall_frame(w)
    t = w["thickness"] / 2
    ek = ext_layers[-1][1]
    ik = int_layers[-1][1]
    for poly in g["construction_polygons"]:
        P = dedupe([tuple(p) for p in poly])
        if len(P) < 3:
            continue
        area = sum(P[i][0] * P[(i + 1) % len(P)][1] - P[(i + 1) % len(P)][0] * P[i][1] for i in range(len(P)))
        if abs(area) < 1e-6:
            continue
        if area < 0:
            P = P[::-1]

        def wp(u, z, s):
            x, y = ctx.W((sx + ux * u + nx * s * t, sy + uy * u + ny * s * t))
            return (x, y, zl + z)
        tris = earcut(P)
        # (u, z) is CCW seen from the exterior (-n side, u to the right); the interior face (+n) uses the reverse order
        m_i = sc.mb(ik)
        m_e = sc.mb(ek)
        for (i0, i1, i2) in tris:
            m_i.poly([wp(*P[i0], 1), wp(*P[i2], 1), wp(*P[i1], 1)])
            m_e.poly([wp(*P[i0], -1), wp(*P[i1], -1), wp(*P[i2], -1)])
        n = len(P)
        for k in range(n):
            a_, b_ = P[k], P[(k + 1) % n]
            sc.face(ek, [wp(*a_, -1), wp(*a_, 1), wp(*b_, 1), wp(*b_, -1)])
        # collision: convex hull pieces as prisms along the normal (triangles extruded)
        col = sc.cb("main", "concrete", True)
        for (i0, i1, i2) in tris:
            A = [wp(*P[i], -1) for i in (i0, i1, i2)]
            B = [wp(*P[i], 1) for i in (i0, i1, i2)]
            col.add(A + B, [(0, 2, 1), (3, 4, 5), (0, 1, 4), (0, 4, 3), (1, 2, 5), (1, 5, 4), (2, 0, 3), (2, 3, 5)])


def roof_geometry(ctx, rf, mat_key):
    """roof slab (0.15 m build-up over the roof plane) with overhangs; render + collision."""
    sc = ctx.sc
    P = rf.get("wall_rect") or rf.get("rect")
    x0, y0 = min(p[0] for p in P), min(p[1] for p in P)
    x1, y1 = max(p[0] for p in P), max(p[1] for p in P)
    oe = rf.get("overhang_eave", 0.3) or 0.0
    ov = rf.get("overhang_verge") or {}
    ab = rf.get("abuts") or {}
    tp = math.tan(math.radians(rf["pitch_deg"]))
    TH = 0.14
    soffit = "soffit"

    def zp(x, y):
        return float(C.roof_plane_at(rf, x, y))

    def emit(pts_local):
        corners = [ctx.Wz((x, y), zp(x, y) + TH) for x, y in pts_local]
        return corners

    faces = []
    if rf["type"] == "gable":
        if rf.get("ridge_axis", "X") == "X":
            ym = (y0 + y1) / 2
            xa = x0 - (0.0 if "-X" in ab else ov.get("-X", 0.3))
            xb = x1 + (0.0 if "+X" in ab else ov.get("+X", 0.3))
            faces.append([(xa, y0 - oe), (xb, y0 - oe), (xb, ym), (xa, ym)])
            faces.append([(xb, y1 + oe), (xa, y1 + oe), (xa, ym), (xb, ym)])
        else:
            xm = (x0 + x1) / 2
            ya = y0 - (0.0 if "-Y" in ab else ov.get("-Y", 0.3))
            yb = y1 + (0.0 if "+Y" in ab else ov.get("+Y", 0.3))
            faces.append([(x0 - oe, yb), (x0 - oe, ya), (xm, ya), (xm, yb)])
            faces.append([(x1 + oe, ya), (x1 + oe, yb), (xm, yb), (xm, ya)])
    elif rf["type"] == "hip":
        X0, X1, Y0, Y1 = x0 - oe, x1 + oe, y0 - oe, y1 + oe
        if "+X" in ab:
            X1 = x1
        if "-X" in ab:
            X0 = x0
        ym = (y0 + y1) / 2
        # ridge ends: where the hip planes meet the ridge (dx = dy)
        hw = (y1 - y0) / 2
        rx0 = X0 + (hw + oe) if "-X" not in ab else X0
        rx1 = X1 - (hw + oe) if "+X" not in ab else X1
        if rx1 < rx0:
            rx0 = rx1 = (X0 + X1) / 2
        faces.append([(X0, Y0), (X1, Y0), (rx1, ym), (rx0, ym)])
        faces.append([(X1, Y1), (X0, Y1), (rx0, ym), (rx1, ym)])
        if "-X" not in ab:
            faces.append([(X0, Y1), (X0, Y0), (rx0, ym)])
        if "+X" not in ab:
            faces.append([(X1, Y0), (X1, Y1), (rx1, ym)])
    elif rf["type"] == "mono":
        R = rf.get("rect") or [[x0 - oe, y0 - oe], [x1 + oe, y0 - oe], [x1 + oe, y1 + oe], [x0 - oe, y1 + oe]]
        rx0, ry0 = min(p[0] for p in R), min(p[1] for p in R)
        rx1, ry1 = max(p[0] for p in R), max(p[1] for p in R)
        faces.append([(rx0, ry0), (rx1, ry0), (rx1, ry1), (rx0, ry1)])
    for fpts in faces:
        top = [ctx.Wz((x, y), zp(x, y) + TH) for x, y in fpts]
        bot = [ctx.Wz((x, y), zp(x, y)) for x, y in fpts]
        # orient CCW from above
        area = sum(top[i][0] * top[(i + 1) % len(top)][1] - top[(i + 1) % len(top)][0] * top[i][1] for i in range(len(top)))
        if area < 0:
            top = top[::-1]
            bot = bot[::-1]
        sc.face(mat_key, top, sub=1.5 if len(top) == 4 else None)
        sc.face(soffit, bot[::-1])
        n = len(top)
        for i in range(n):
            j = (i + 1) % n
            sc.face("frame_dark", [bot[i], bot[j], top[j], top[i]])
        col = sc.cb("main", "metal" if "corr" in mat_key else "stone", True)
        V = bot + top
        I = [(n, n + k, n + k + 1) for k in range(1, n - 1)] + [(0, k + 1, k) for k in range(1, n - 1)]
        for k in range(n):
            k2 = (k + 1) % n
            I += [(k, k2, n + k2), (k, n + k2, n + k)]
        col.add(V, I)


def build_dormers(ctx, rf, mat_key):
    """small gabled dormers on a hip roof slope (render only; the attic is closed)."""
    sc = ctx.sc
    P = rf.get("wall_rect")
    if not P or not rf.get("dormers"):
        return
    y0 = min(p[1] for p in P)
    y1 = max(p[1] for p in P)
    tp = math.tan(math.radians(rf["pitch_deg"]))
    for d in rf["dormers"]:
        sgn = 1 if d.get("slope", "+Y") == "+Y" else -1
        cx = d["center_x"]
        w = d["width"]
        fh = d.get("front_height", 1.2)
        yf = (y1 - 0.6) if sgn > 0 else (y0 + 0.6)          # front face just behind the eave line
        zf_ = float(C.roof_plane_at(rf, cx, yf)) + 0.14
        depth = fh / tp + 0.3
        yb = yf - sgn * depth
        # cheeks + front (box up to front height), gable roof along the dormer axis
        a = (cx - w / 2, min(yf, yb))
        b = (cx + w / 2, max(yf, yb))
        pts = [ctx.W(p) for p in ((a[0], a[1]), (b[0], a[1]), (b[0], b[1]), (a[0], b[1]))]
        sc.prism(pts, ctx.zf + zf_ - 0.4, ctx.zf + zf_ + fh, mat="plaster_cream", collide=False)
        ww = d.get("window", {}).get("width", 0.7)
        wh = d.get("window", {}).get("height", 0.8)
        fy = yf + sgn * 0.01
        q0 = ctx.W((cx - ww / 2, fy))
        q1 = ctx.W((cx + ww / 2, fy))
        z0 = ctx.zf + zf_ + 0.2
        quad = [(q0[0], q0[1], z0), (q1[0], q1[1], z0), (q1[0], q1[1], z0 + wh), (q0[0], q0[1], z0 + wh)]
        if sgn < 0:
            quad = quad[::-1]
        sc.face("glass_dark", quad if sgn > 0 else quad)
        ridge_h = w / 2
        zt = ctx.zf + zf_ + fh
        for s_ in (-1, 1):
            e0 = ctx.W((cx + s_ * (w / 2 + 0.15), yf + sgn * 0.2))
            e1 = ctx.W((cx + s_ * (w / 2 + 0.15), yb))
            r0 = ctx.W((cx, yf + sgn * 0.2))
            r1 = ctx.W((cx, yb))
            quad = [(e0[0], e0[1], zt), (e1[0], e1[1], zt), (r1[0], r1[1], zt + ridge_h), (r0[0], r0[1], zt + ridge_h)]
            n = np.cross(np.array(quad[1]) - quad[0], np.array(quad[3]) - quad[0])
            if n[2] < 0:
                quad = quad[::-1]
            sc.face(mat_key, quad)
        g0 = ctx.W((cx - w / 2, yf))
        g1 = ctx.W((cx + w / 2, yf))
        gm = ctx.W((cx, yf))
        tri = [(g0[0], g0[1], zt), (g1[0], g1[1], zt), (gm[0], gm[1], zt + ridge_h)]
        n = np.cross(np.array(tri[1]) - tri[0], np.array(tri[2]) - tri[0])
        outward = np.array([ctx.W((cx, yf + sgn))[0] - gm[0], ctx.W((cx, yf + sgn))[1] - gm[1], 0])
        if np.dot(n, outward) < 0:
            tri = tri[::-1]
        sc.face("plaster_cream", tri)


def roof_mat(m):
    m = (m or "").lower()
    if "green" in m:
        return "roof_corr_green"
    if "clay" in m or "tile" in m:
        return "roof_tile_red"
    if "corrugated" in m and "grey" in m and "dark" not in m:
        return "roof_corr_rust"
    return "roof_corr_dark"


FURN = {
    "lathe": ("furn_green", "main"), "milling_machine": ("furn_green", "main"), "compressor": ("furn_green", "main"),
    "shelving_steel_loaded": ("furn_steel", "main"), "profile_rack_steel": ("furn_steel", "main"), "pallet_racking_full": ("steel_blue", "main"),
    "workbench": ("furn_wood", "main"), "tool_counter": ("furn_wood", "main"), "desk_steel": ("furn_steel", "main"),
    "forge_hearth_brick": ("brick", "main"), "stove_cast_iron": ("frame_dark", "main"), "kitchen_stove_solid_fuel": ("frame_dark", "main"),
    "lockers_row": ("furn_green", "main"), "wash_trough": ("concrete", "main"), "air_tank_vertical": ("furn_green", "main"),
    "oil_drums_x4": ("steel_blue", "main"), "welding_cart": ("furn_steel", "main"), "tractor_dismantled": ("steel_rust", "main"),
    "forklift": ("prop_paint", "main"), "pallet_jack": ("steel_rust", "main"), "filing_cabinets": ("furn_steel", "main"),
    "desk_office": ("furn_wood", "main"), "bathtub": ("furn_white", "main"), "boiler_washing_machine": ("furn_white", "main"),
    "kitchen_units": ("furn_white", "main"), "sofa": ("furn_soft", "movevis"), "bed_single": ("furn_soft", "movevis"),
    "bed_double": ("furn_soft", "movevis"),
}


def build_main_building(sc, bp, bd, terr):
    ctx = BuildingCtx(sc, bp, bd, terr)
    zf = ctx.zf
    bid = bd["id"]
    # ground-floor base (floor slab + footing), plinth render on the sides
    for part in bd["footprint_parts"]:
        pts = [ctx.W(p) for p in part["external_rect"]]
        sc.prism(pts, zf - 0.8, zf, mat="render_grey", top=False, bottom=False, cls="main", surface="concrete")
    # walls
    for w in bd["walls"]:
        zl = zf + ctx.lvz(w["level"])
        external = w.get("kind") == "external"
        ext_layers = finish_layers(w.get("finish_right"), bid) if external else finish_layers(w.get("finish_right") or w.get("finish_left"), bid)
        int_layers = finish_layers(w.get("finish_left"), bid)
        end_key = ext_layers[-1][1] if external else int_layers[-1][1]
        top_key = ext_layers[-1][1]
        mat = (w.get("material") or "").lower()
        surf = "wood" if "timber" in mat else "concrete"
        for cb in w["construction_boxes"]:
            u0, u1 = cb["u"]
            z0, z1 = cb["z"]
            wall_box(ctx, w, u0, u1, ctx.lvz(w["level"]) + z0, ctx.lvz(w["level"]) + z1, ext_layers, int_layers, end_key, top_key,
                     ctx.lvz(w["level"]), bottom=z0 > 0.05, surface=surf)
        if w.get("gable"):
            gable_wall(ctx, w, ctx.lvz(w["level"]) + 0.0, ext_layers, int_layers)
        build_openings(ctx, w, zl, external)
    # pilasters (plastered brick piers proud of the facade)
    for pl in bd.get("pilasters", []):
        w = ctx.walls[pl["wall"]]
        sx, sy, ux, uy, nx, ny, Lw = C.wall_frame(w)
        if "x" in pl:
            u = (pl["x"] - sx) / ux if abs(ux) > 0.5 else 0.0
        else:
            u = (pl["y"] - sy) / uy if abs(uy) > 0.5 else 0.0
        t = w["thickness"] / 2
        hw = pl["width"] / 2
        wall_uv_box(ctx, w, u - hw, u + hw, -t - pl["proud"], -t, pl["z"][0], pl["z"][1], mat="plaster_lime", cls="main", surface="concrete")
    # slabs (upper floors): ceiling below, floors rendered per room
    for sl in bd.get("slabs", []):
        P = Polygon(sl["polygon"])
        for h in sl.get("openings", []):
            P = P.difference(Polygon(h["polygon"]))
        for (q0, q1, q2, q3) in rect_strips(P):
            pts = [ctx.W(p) for p in ((q0, q1), (q2, q1), (q2, q3), (q0, q3))]
            sc.prism(pts, zf + sl["top_z"] - sl["thickness"], zf + sl["top_z"], mat="plaster_white", top=False, sub=1.0, cls="main", surface="wood")
    slab_levels = {sl["level"] for sl in bd.get("slabs", [])}
    # room floors (render) and missing ceilings (render + collision)
    eave = max((r["eave_z"] for r in bd["roof"]), default=4.0)
    for rm in bd["rooms"]:
        z = zf + ctx.lvz(rm["level"])
        poly = dedupe(rm["polygon"])
        key = floor_mat(rm.get("floor_material"))
        tris = earcut(poly)
        mbuf = sc.mb(key)
        Pw = [ctx.W(p) for p in poly]
        for (i0, i1, i2) in tris:
            mbuf.poly([(Pw[i][0], Pw[i][1], z + 0.004) for i in (i0, i1, i2)])
        ch = rm.get("ceiling_height") or 2.6
        lvl_ids = [l["id"] for l in bd["levels"]]
        li = lvl_ids.index(rm["level"]) if rm["level"] in lvl_ids else 0
        above = lvl_ids[li + 1] if li + 1 < len(lvl_ids) else None
        covered = above in slab_levels
        if not covered and ch < 4.0:
            cz = z + ch
            ceil = [(x, y) for (x, y) in Pw]
            for (i0, i1, i2) in tris:
                sc.mb("plaster_white").poly([(ceil[i][0], ceil[i][1], cz) for i in (i0, i2, i1)])
            for (q0, q1, q2, q3) in rect_strips(Polygon(poly)):
                pts = [ctx.W(p) for p in ((q0, q1), (q2, q1), (q2, q3), (q0, q3))]
                sc.prism(pts, cz, cz + 0.06, mat="plaster_white", bottom=False, cls="main", surface="wood")
    # stairs (interior flights + exterior steps): step boxes, landings
    for s in bd["stairs"] + bd["exterior_stairs"]:
        dv = s["direction_vector"]
        pn = (-dv[1], dv[0])
        hw = s["width"] / 2
        sx_, sy_ = s["start"]
        solid = s.get("under_stair", {}).get("treatment") == "solid_mass"
        foot = s.get("foot_ground", s["z_start"])
        mat_s = "concrete" if "concrete" in (s.get("construction") or "") or solid else "floor_terrazzo"
        if "grating" in (s.get("construction") or "") or "steel" in (s.get("construction") or ""):
            mat_s = "galvanized"
        surf = "metal" if mat_s == "galvanized" else "concrete"
        for i in range(s["treads"]):
            d0, d1 = i * s["tread"], (i + 1) * s["tread"]
            top = s["z_start"] + s["riser"] * (i + 1)
            bot = (foot - 0.3) if solid else max(s["z_start"] - 0.05, top - s["riser"] - max(s.get("waist", 0.16), 0.12))
            q = [ctx.W((sx_ + pn[0] * hw + dv[0] * d0, sy_ + pn[1] * hw + dv[1] * d0)),
                 ctx.W((sx_ - pn[0] * hw + dv[0] * d0, sy_ - pn[1] * hw + dv[1] * d0)),
                 ctx.W((sx_ - pn[0] * hw + dv[0] * d1, sy_ - pn[1] * hw + dv[1] * d1)),
                 ctx.W((sx_ + pn[0] * hw + dv[0] * d1, sy_ + pn[1] * hw + dv[1] * d1))]
            sc.prism(q, zf + bot, zf + top, mat=mat_s, side="plaster_white" if not solid else mat_s, cls="main", surface=surf)
        ld = s.get("landing")
        if ld:
            lz = ld["z"]
            bot = (foot - 0.3) if solid else lz - ld.get("thickness", 0.2)
            sc.prism([ctx.W(p) for p in ld["polygon"]], zf + bot, zf + lz, mat=mat_s if solid else "floor_terrazzo",
                     side="plaster_white" if not solid else mat_s, cls="main", surface=surf)
    # balustrades
    for ba in bd.get("balustrades", []):
        zb_ = ba.get("z")
        if zb_ is None:
            zb_ = ctx.lvz(ba["level"]) if ba["level"] in ctx.lv else next(
                (st["landing"]["z"] for st in bd["stairs"] if st.get("landing") and st["landing"]["level"] == ba["level"]), 0.0)
        for p, q in zip(ba["polyline"][:-1], ba["polyline"][1:]):
            a = ctx.W(p)
            b = ctx.W(q)
            sc.seg_box(a, b, 0.07, zf + zb_ + ba["height"] - 0.06, zf + zb_ + ba["height"], mat="wood_dark", collide=False)
            L_ = math.dist(p, q)
            nb = max(2, int(L_ / 0.14))
            for k in range(nb + 1):
                t_ = k / nb
                x = a[0] + (b[0] - a[0]) * t_
                y = a[1] + (b[1] - a[1]) * t_
                sc.obox(x, y, 0.025, 0.025, 0, zf + zb_, zf + zb_ + ba["height"] - 0.06, mat="frame_dark", collide=False)
            sc.seg_box(a, b, 0.06, zf + zb_, zf + zb_ + ba["height"], mat=False, cls="move", surface="wood", render=False)
    # balconies
    for ba in bd.get("balconies", []):
        sc.prism([ctx.W(p) for p in ba["polygon"]], zf + ba["top_z"] - ba["slab_thickness"], zf + ba["top_z"], mat="concrete",
                 top="floor_terrazzo", cls="main", surface="tiles")
        pp = ba["parapet"]
        for p, q in pp["segments"]:
            sc.seg_box(ctx.W(p), ctx.W(q), pp["thickness"], zf + ba["top_z"], zf + ba["top_z"] + pp["height"], mat="plaster_cream",
                       cls="main", surface="concrete")
    # furniture
    for f in bd.get("furniture", []):
        zl = ctx.lvz(f["level"]) if f["level"] in ctx.lv else -0.17
        key, cls = FURN.get(f["type"], ("furn_wood", "main"))
        if f.get("blocks_bullets") is False:
            cls = "movevis" if f.get("blocks_vision", True) else "move"
        if f.get("shape") == "wedge_under_soffit":
            st = next(s_ for s_ in bd["stairs"] + bd["exterior_stairs"] if f["id"] in s_.get("under_stair", {}).get("by", []))
            dv = st["direction_vector"]
            n_ = 5
            for k in range(n_):
                u0 = -f["size"][0] / 2 + f["size"][0] * k / n_
                u1 = -f["size"][0] / 2 + f["size"][0] * (k + 1) / n_
                cxl = f["center"][0] + dv[0] * (u0 + u1) / 2
                cyl = f["center"][1] + dv[1] * (u0 + u1) / 2
                dd = (cxl - st["start"][0]) * dv[0] + (cyl - st["start"][1]) * dv[1] - (u1 - u0) / 2
                zs = st["z_start"] + st["riser"] + dd * st["riser"] / st["tread"] - st.get("waist", 0.2) - 0.05
                top = min(zs, zl + f["size"][2])
                if top > zl + 0.1:
                    local_box(ctx, cxl, cyl, u1 - u0, f["size"][1], math.degrees(math.atan2(dv[1], dv[0])), zl - 0.1, top,
                              mat="wood_dark", cls="main", surface="wood")
            continue
        lx, ly, lz = f["size"]
        rotl = f.get("rotation_deg", 0)
        surf = "metal" if key in ("furn_steel", "furn_green", "steel_blue", "steel_rust", "frame_dark", "prop_paint") else "wood"
        if f["type"] in ("pallet_racking_full", "shelving_steel_loaded", "profile_rack_steel"):
            # frame + shelves + load (reads as racking)
            local_box(ctx, f["center"][0], f["center"][1], lx, ly, rotl, zl, zl + lz, mat=False, cls=cls, surface="metal", render=False)
            for k in range(4):
                zz = zl + 0.1 + (lz - 0.2) * k / 3
                local_box(ctx, f["center"][0], f["center"][1], lx, ly, rotl, zz, zz + 0.06, mat="steel_blue", collide=False)
            ca, sa_ = math.cos(math.radians(rotl)), math.sin(math.radians(rotl))
            for ex in (-lx / 2 + 0.05, lx / 2 - 0.05):
                for ey in (-ly / 2 + 0.05, ly / 2 - 0.05):
                    local_box(ctx, f["center"][0] + ex * ca - ey * sa_, f["center"][1] + ex * sa_ + ey * ca, 0.08, 0.08, rotl, zl, zl + lz,
                              mat="steel_blue", collide=False)
            for k in range(3):
                zz = zl + 0.16 + (lz - 0.2) * k / 3
                local_box(ctx, f["center"][0], f["center"][1], lx * 0.94, ly * 0.8, rotl, zz, zz + (lz - 0.2) / 3 * 0.75,
                          mat="prop", color=(0.72, 0.62, 0.45, 1) if k % 2 else (0.6, 0.6, 0.58, 1), collide=False)
            continue
        local_box(ctx, f["center"][0], f["center"][1], lx, ly, rotl, zl, zl + lz, mat=key, cls=cls, surface=surf)
    # columns, chimneys
    for col in bd.get("columns", []):
        local_box(ctx, col["center"][0], col["center"][1], col["size"][0], col["size"][1], 0, 0, col["height"], mat="steel_blue", cls="main", surface="metal")
    for ch in bd.get("chimneys", []):
        sz = ch.get("size", [0.4, 0.4])
        zb = ch.get("base_z", 0.0)
        local_box(ctx, ch["pos"][0], ch["pos"][1], sz[0], sz[1], 0, zb - (0.2 if zb <= 0 else 0.0), ch["top_z"], mat="brick", cls="main", surface="concrete")
        local_box(ctx, ch["pos"][0], ch["pos"][1], sz[0] + 0.12, sz[1] + 0.12, 0, ch["top_z"], ch["top_z"] + 0.08, mat="concrete", collide=False)
    # loading dock + exterior steps / ramps / thresholds / canopies
    if bd.get("loading_dock"):
        dk = bd["loading_dock"]
        sc.prism([ctx.W(p) for p in dk["polygon"]], zf + dk.get("bottom_z", -1.1) - 0.15, zf + dk.get("top_z", 0.0), mat="concrete",
                 cls="main", surface="concrete")
    for st in bd.get("exterior_steps", []):
        if st["type"] == "step":
            zt = st.get("z", 0.0)
            sc.prism([ctx.W(p) for p in st["polygon"]], zf + zt - 0.6, zf + zt, mat="concrete", cls="main", surface="concrete")
        elif st["type"] == "ramp":
            P = st["polygon"]
            PL = np.array(P, float)
            prm = C.ramp_param(st, PL[:, 0], PL[:, 1])
            ztop = [st["z_top"] + (st["z_bottom"] - st["z_top"]) * float(v) for v in prm]
            Pw = [ctx.W(p) for p in P]
            sc.prism(Pw, zf + min(ztop) - 0.5, zf + max(ztop), top_z=[zf + z for z in ztop], mat="concrete", cls="main", surface="concrete")
        elif st["type"] == "threshold":
            ap = st.get("apron")
            if ap:
                sc.prism([ctx.W(p) for p in ap["polygon"]], zf + ap["z"] - 0.3, zf + ap["z"], mat="concrete", cls="main", surface="concrete")
        elif st["type"] == "canopy":
            if st.get("polygon"):
                z = st.get("z", 2.5)
                sc.prism([ctx.W(p) for p in st["polygon"]], zf + z, zf + z + 0.1, mat="roof_tile_red", bottom="soffit", cls="main", surface="stone")
    # roofs
    for rf in bd["roof"]:
        roof_geometry(ctx, rf, roof_mat(rf.get("material")))
        build_dormers(ctx, rf, roof_mat(rf.get("material")))
        if rf["type"] == "mono" and rf.get("supports"):
            for sp in rf["supports"]:
                c = sp.get("pos") or sp.get("center")
                if c:
                    local_box(ctx, c[0], c[1], 0.15, 0.15, 0, sp.get("z0", -1.1), sp.get("z1", rf["eave_z"]), mat="steel_blue", cls="main", surface="metal")
    # gutters and downpipes (render only)
    for gu in bd.get("gutters", []):
        a = ctx.W(gu["from"])
        b = ctx.W(gu["to"])
        sc.seg_box(a, b, 0.13, zf + gu["z"] - 0.1, zf + gu["z"], mat="galvanized", collide=False)
    for dp in bd.get("downpipes", []):
        x, y = ctx.W(dp["pos"])
        zg = terr.z1(x, y)
        sc.obox(x, y, 0.1, 0.1, ctx.rot, min(zg, zf) - 0.1, zf + dp["top_z"], mat="galvanized", collide=False)
    # fixtures: lamps, lintel beams, painted signs
    for fx in bd.get("fixtures", []):
        w = ctx.walls.get(fx.get("wall"))
        p = fx["pos"]
        if w is None:
            continue
        sx, sy, ux, uy, nx, ny, Lw = C.wall_frame(w)
        t = w["thickness"] / 2
        u = (p[0] - sx) * ux + (p[1] - sy) * uy
        if "lamp" in fx["type"]:
            wall_uv_box(ctx, w, u - 0.05, u + 0.05, -t - 0.5, -t, fx["z"] + 0.05, fx["z"] + 0.1, mat="frame_dark", collide=False)
            wall_uv_box(ctx, w, u - 0.18, u + 0.18, -t - 0.62, -t - 0.26, fx["z"] - 0.08, fx["z"] + 0.02, mat="furn_white", collide=False)
            wall_uv_box(ctx, w, u - 0.1, u + 0.1, -t - 0.54, -t - 0.34, fx["z"] - 0.1, fx["z"] - 0.07, mat="lamp_emissive", collide=False)
        elif fx["type"] == "steel_lintel_beam_exposed":
            hl = fx.get("length", 3.0) / 2
            wall_uv_box(ctx, w, u - hl, u + hl, -t - 0.02, -t + 0.06, fx["z"], fx["z"] + 0.22, mat="steel_rust", collide=False)
        elif "sign" in fx["type"] and fx.get("text_cs"):
            key = f"sign_{fx['id']}"
            if key not in MATS:
                MATS[key] = {"color": "#ffffff", "rough": 0.85, "tex": "sign_wall", "alpha_test": 0.3, "tile": 1.0, "text": fx["text_cs"]}
            wlen = 0.24 * len(fx["text_cs"]) * (0.5 if fx["type"] == "house_number_plate" else 1.0)
            wlen = min(wlen, 9.0)
            hgt = wlen / 8.0
            a = ctx.W((sx + ux * (u - wlen / 2) - nx * (t + 0.012), sy + uy * (u - wlen / 2) - ny * (t + 0.012)))
            b = ctx.W((sx + ux * (u + wlen / 2) - nx * (t + 0.012), sy + uy * (u + wlen / 2) - ny * (t + 0.012)))
            z = zf + fx["z"]
            m = sc.mb(key)
            # quad facing outwards (-n): seen from outside u runs to the right
            P4 = np.array([(a[0], a[1], z), (b[0], b[1], z), (b[0], b[1], z + hgt), (a[0], a[1], z + hgt)])
            nrm = np.cross(P4[1] - P4[0], P4[3] - P4[0])
            m.add(P4, nrm / np.linalg.norm(nrm), [(0, 1), (1, 1), (1, 0), (0, 0)], (1, 1, 1, 1), [(0, 1, 2), (0, 2, 3)])
    return ctx


# ================================================================================================
# secondary buildings (closed, readable volumes; no fake doors)
# ================================================================================================
SEC_STYLE = {
    "S_DOMEK_1": ("plaster_ochre", "roof_tile_red"), "S_DOMEK_2": ("plaster_greyish", "roof_eternit"),
    "S_DOMEK_3": ("plaster_white", "roof_tile_red"), "S_DOMEK_4": ("stone", "roof_slate"),
    "S_HOSPODA": ("plaster_cream", "roof_tile_red"), "S_HASICI": ("plaster_lime", "roof_corr_dark"),
    "S_KAPLE": ("plaster_cream", "roof_slate"), "S_GARAZE": ("plaster_greyish", "roof_felt"),
    "S_KIOSK": ("plaster_white", "roof_felt"), "S_STODOLA": ("wood_grey", "roof_corr_dark"),
    "S_SENIK": ("wood_grey", "roof_corr_rust"), "S_KOLNA_STROJE": ("wood_grey", "roof_corr_rust"),
    "S_STERKOVNA": ("steel_grey", "roof_felt"), "S_KULNA_C": ("wood_grey", "roof_corr_dark"),
    "S_DREVNIK": ("wood_grey", "roof_corr_dark"), "S_ZASTAVKA": ("wood_grey", "roof_corr_dark"),
}
MATS["plaster_ochre"] = {"color": "#c9a86a", "rough": 0.9, "tex": "plaster", "tile": 2.0}
MATS["plaster_greyish"] = {"color": "#a9a59b", "rough": 0.9, "tex": "plaster", "tile": 2.0}


def facade_panel(sc, c0, rot, lx, ly, zb, face, u, w, z0, z1, key, proud=0.03):
    """flat panel (door, shutter, boarded window) proud of a facade of a local box (face: '+Y', '-Y', '+X', '-X')."""
    if face in ("+Y", "-Y"):
        s = 1 if face == "+Y" else -1
        cy = s * (ly / 2 + proud / 2)
        p = xf(c0, rot, (u, cy))
        sc.obox(p[0], p[1], w, proud, rot, zb + z0, zb + z1, mat=key, collide=False)
    else:
        s = 1 if face == "+X" else -1
        cx = s * (lx / 2 + proud / 2)
        p = xf(c0, rot, (cx, u))
        sc.obox(p[0], p[1], proud, w, rot, zb + z0, zb + z1, mat=key, collide=False)


def gable_roof_local(sc, c0, rot, lx, ly, ze, zr, key, oh=0.35, axis="X", solid_gables=None, collide=True):
    """gable roof over a local lx x ly rectangle, eave ze, ridge zr (absolute); gable triangles filled with solid_gables."""
    if axis == "X":
        hw = ly / 2
        tp = (zr - ze) / hw
        zo = ze - oh * tp
        pts_s = [(-lx / 2 - oh, -hw - oh, zo), (lx / 2 + oh, -hw - oh, zo), (lx / 2 + oh, 0, zr), (-lx / 2 - oh, 0, zr)]
        pts_n = [(lx / 2 + oh, hw + oh, zo), (-lx / 2 - oh, hw + oh, zo), (-lx / 2 - oh, 0, zr), (lx / 2 + oh, 0, zr)]
        tri = [((-lx / 2, -hw, ze), (-lx / 2, hw, ze), (-lx / 2, 0, zr)), ((lx / 2, hw, ze), (lx / 2, -hw, ze), (lx / 2, 0, zr))]
    else:
        hw = lx / 2
        tp = (zr - ze) / hw
        zo = ze - oh * tp
        pts_s = [(-hw - oh, ly / 2 + oh, zo), (-hw - oh, -ly / 2 - oh, zo), (0, -ly / 2 - oh, zr), (0, ly / 2 + oh, zr)]
        pts_n = [(hw + oh, -ly / 2 - oh, zo), (hw + oh, ly / 2 + oh, zo), (0, ly / 2 + oh, zr), (0, -ly / 2 - oh, zr)]
        tri = [((-hw, -ly / 2, ze), (hw, -ly / 2, ze), (0, -ly / 2, zr)), ((hw, ly / 2, ze), (-hw, ly / 2, ze), (0, ly / 2, zr))]
    for pts in (pts_s, pts_n):
        W4 = [(*xf(c0, rot, p[:2]), p[2] + 0.12) for p in pts]
        sc.sloped_slab(W4, 0.12, mat=key, bottom="soffit", side="frame_dark", cls="main" if collide else None, surface="metal", sub=2.0)
    if solid_gables:
        for t in tri:
            P = [(*xf(c0, rot, p[:2]), p[2]) for p in t]
            sc.mb(solid_gables).poly(P)
            if collide:
                # thin prism for collision
                pass


def build_secondary(sc, sb, terr):
    sid = sb["id"]
    typ = sb["type"]
    c0 = sb["position"][:2]
    rot = sb["rotation_deg"]
    z = sb["position"][2]
    lx, ly = sb["footprint"]
    eave = sb["eave_height"]
    ridge = sb.get("ridge_height", eave)
    wall_key, roof_key = SEC_STYLE.get(sid, ("plaster_lime", "roof_corr_rust" if typ.startswith("shed") else "roof_corr_dark"))
    plinth = sb.get("plinth") or {}
    pb = plinth.get("bottom_z", z - 0.15)
    pt = plinth.get("top_z", z + 0.3) if isinstance(plinth.get("top_z"), (int, float)) else z + 0.3
    fw = sb["footprint_world"]
    # --- special types
    if sb.get("embedded_in"):
        # garage in the retaining wall: only the front (door) face is modelled; the volume is terrain / wall
        sc.prism(fw, z - 0.2, sb["roof_deck_top_z"], mat="stone", top="concrete", cls="main", surface="concrete")
        facade_panel(sc, c0, rot, lx, ly, z, "+Y", 0.0, 2.4, 0.0, 2.0, "steel_rust")
        return
    if typ == "transformer_pole_h":
        pl = sb.get("poles", {})
        for (px, py) in pl.get("local", [[-1.1, 0], [1.1, 0]]):
            q = xf(c0, rot, (px, py))
            sc.obox(q[0], q[1], 0.3, 0.3, rot, z - 0.3, z + pl.get("height", 9.0), mat="concrete", cls="main", surface="concrete")
        tr = sb.get("transformer", {})
        sc.obox(*xf(c0, rot, (0, 0)), 2.6, 0.9, rot, z + tr.get("platform_z", 4.4) - 0.1, z + tr.get("platform_z", 4.4), mat="steel_grey", cls="main", surface="metal")
        s3 = tr.get("size", [1.5, 1.0, 1.6])
        sc.obox(*xf(c0, rot, (0, 0)), s3[0], s3[1], rot, z + tr.get("z0", 4.6), z + tr.get("z0", 4.6) + s3[2], mat="furn_green", cls="main", surface="metal")
        sc.obox(*xf(c0, rot, (0, 0.2)), 1.0, 0.5, rot, z - 0.2, z + 1.6, mat="steel_grey", cls="main", surface="metal")
        return
    if typ.startswith("bus_shelter"):
        # open-front timber shelter: back + side plank walls on a concrete footing wall, bench, gable roof
        t = 0.08
        sc.prism(fw, z - 0.3, z + 0.02, mat="concrete", cls="main", surface="concrete")
        for (a, b) in (((-lx / 2, -ly / 2), (lx / 2, -ly / 2)), ((-lx / 2, -ly / 2), (-lx / 2, ly / 2)), ((lx / 2, -ly / 2), (lx / 2, ly / 2))):
            A = xf(c0, rot, a)
            B = xf(c0, rot, b)
            sc.seg_box(A, B, t, z, z + 0.9, mat="concrete", cls="main", surface="concrete")
            sc.seg_box(A, B, t, z + 0.9, z + eave, mat="wood_grey", cls="movevis", surface="wood")
        q = xf(c0, rot, (0, -ly / 2 + 0.35))
        sc.obox(q[0], q[1], lx - 0.3, 0.4, rot, z + 0.4, z + 0.47, mat="wood_dark", collide=False)
        for (px, py) in ((-lx / 2, ly / 2), (lx / 2, ly / 2)):
            q = xf(c0, rot, (px, py))
            sc.obox(q[0], q[1], 0.12, 0.12, rot, z, z + eave, mat="wood_grey", cls="main", surface="wood")
        gable_roof_local(sc, c0, rot, lx, ly, z + eave, z + ridge, roof_key, oh=0.25, axis="X", solid_gables="wood_grey")
        return
    # plinth
    sc.prism(fw, pb, pt, mat="render_grey" if "stone" not in plinth.get("material", "") else "stone", cls="main", surface="concrete")
    zb = pt
    ze = z + eave
    zr = z + ridge
    solid_key = wall_key
    if typ in ("hay_barn", "machinery_shed", "woodshed"):
        # open structure filled with bales / logs: solid block + posts + roof
        fill = "bales" if typ != "woodshed" else "logs"
        inset = 0.25
        P = [xf(c0, rot, p) for p in ((-lx / 2 + inset, -ly / 2 + inset), (lx / 2 - inset, -ly / 2 + inset), (lx / 2 - inset, ly / 2 - inset), (-lx / 2 + inset, ly / 2 - inset))]
        sc.prism(P, zb, z + min(eave, 4.5) - 0.1, mat=fill, cls="main", surface="wood")
        # the collision covers the whole footprint to the eave (as data: collision proxy = full footprint)
        sc.prism(fw, zb, ze, mat=False, cls="main", surface="wood", render=False)
        for px in np.linspace(-lx / 2, lx / 2, max(2, int(lx / 3) + 1)):
            for py in (-ly / 2, ly / 2):
                q = xf(c0, rot, (px, py))
                sc.obox(q[0], q[1], 0.18, 0.18, rot, zb, ze, mat="wood_dark", collide=False)
        if sb.get("roof") == "mono":
            hi = z + ridge
            W4 = [(*xf(c0, rot, (-lx / 2 - 0.3, -ly / 2 - 0.3)), hi), (*xf(c0, rot, (lx / 2 + 0.3, -ly / 2 - 0.3)), hi),
                  (*xf(c0, rot, (lx / 2 + 0.3, ly / 2 + 0.3)), ze), (*xf(c0, rot, (-lx / 2 - 0.3, ly / 2 + 0.3)), ze)]
            sc.sloped_slab(W4, 0.1, mat=roof_key, bottom="soffit", side="frame_dark", cls="main", surface="metal")
        else:
            gable_roof_local(sc, c0, rot, lx, ly, ze, zr, roof_key, oh=0.4, axis="X" if lx >= ly else "Y")
        return
    # closed walls to the eave
    sc.prism(fw, zb, ze, mat=solid_key, top=False, bottom=False, sub=2.0, cls="main", surface="wood" if "wood" in solid_key else "concrete")
    roof = sb.get("roof", "gable")
    if roof in ("gable", "gable_with_bell_turret"):
        axis = "X" if lx >= ly else "Y"
        if sid == "S_KAPLE":
            axis = "Y"
        gable_roof_local(sc, c0, rot, lx, ly, ze, zr, roof_key, oh=0.4 if typ != "chapel" else 0.25, axis=axis, solid_gables=solid_key)
        # gable collision (triangles as thin prisms)
        if axis == "X":
            for s in (-1, 1):
                A = xf(c0, rot, (s * lx / 2, -ly / 2))
                B = xf(c0, rot, (s * lx / 2, ly / 2))
                M = xf(c0, rot, (s * lx / 2, 0))
                sc.col_poly("main", "concrete", [(A[0], A[1], ze), (B[0], B[1], ze), (M[0], M[1], zr)])
        # solid attic volume for collision: a wedge
        hw = (ly if axis == "X" else lx) / 2
        for k in range(4):
            f0 = k / 4
            f1 = (k + 1) / 4
            hz = ze + (zr - ze) * f0
            wdt = hw * (1 - f0)
            if axis == "X":
                P = [xf(c0, rot, p) for p in ((-lx / 2, -wdt), (lx / 2, -wdt), (lx / 2, wdt), (-lx / 2, wdt))]
            else:
                P = [xf(c0, rot, p) for p in ((-wdt, -ly / 2), (wdt, -ly / 2), (wdt, ly / 2), (-wdt, ly / 2))]
            sc.prism(P, hz, ze + (zr - ze) * f1, mat=False, cls="main", surface="concrete", render=False)
    elif roof == "mono":
        lo = z + eave
        hi = z + ridge
        W4 = [(*xf(c0, rot, (-lx / 2 - 0.3, -ly / 2 - 0.3)), hi), (*xf(c0, rot, (lx / 2 + 0.3, -ly / 2 - 0.3)), hi),
              (*xf(c0, rot, (lx / 2 + 0.3, ly / 2 + 0.3)), lo), (*xf(c0, rot, (-lx / 2 - 0.3, ly / 2 + 0.3)), lo)]
        sc.sloped_slab(W4, 0.1, mat=roof_key, bottom="soffit", side="frame_dark", cls="main", surface="metal")
        # walls up to the roof plane (rear higher)
        P = [xf(c0, rot, p) for p in ((-lx / 2, -ly / 2), (lx / 2, -ly / 2), (lx / 2, ly / 2), (-lx / 2, ly / 2))]
        sc.prism(P, ze, hi, top_z=[hi, hi, lo, lo], mat=solid_key, top=False, bottom=False, cls="main", surface="concrete")
    else:  # flat
        sc.prism(fw, ze, ze + 0.25, mat="concrete_dark", top="roof_felt", cls="main", surface="concrete")
    # towers
    tw = sb.get("tower")
    if tw:
        tc = xf(c0, rot, tw["offset_local"])
        th = z + tw["height"]
        sc.obox(tc[0], tc[1], tw["size"][0], tw["size"][1], rot, zb, th, mat=solid_key, cls="main", surface="concrete")
        # spire / cap
        s0 = max(tw["size"]) / 2 + 0.1
        top = th + (2.4 if typ == "chapel" else 1.2)
        P = [xf(tc, rot, p) for p in ((-s0, -s0), (s0, -s0), (s0, s0), (-s0, s0))]
        apex = (tc[0], tc[1], top)
        m = sc.mb("roof_slate" if typ == "chapel" else "roof_corr_dark")
        for i in range(4):
            a = P[i]
            b = P[(i + 1) % 4]
            m.poly([(a[0], a[1], th), (b[0], b[1], th), apex])
        sc.col_poly("main", "metal", [(P[0][0], P[0][1], th), (P[1][0], P[1][1], th), apex])
        if typ == "chapel":
            sc.obox(tc[0], tc[1], 0.08, 0.08, rot, top, top + 0.7, mat="frame_dark", collide=False)
            q = xf(tc, rot, (0, 0))
            sc.obox(q[0], q[1], 0.45, 0.08, rot, top + 0.45, top + 0.53, mat="frame_dark", collide=False)
    # closed-looking details: door (locked), windows (shutters / boards / dark glass)
    front = "+Y"
    if typ.startswith("shed"):
        facade_panel(sc, c0, rot, lx, ly, zb, "+Y", -0.6, 0.95, 0.0, 2.0, "steel_grey")
        facade_panel(sc, c0, rot, lx, ly, zb, "+Y", 0.9, 0.6, 1.2, 1.7, "glass_dark")
        facade_panel(sc, c0, rot, lx, ly, zb, "+Y", -0.6, 0.3, 2.07, 2.2, "lamp_emissive", proud=0.12)
        return
    door_key = {"S_KAPLE": "wood_dark", "S_GARAZE": "steel_rust", "S_HASICI": "steel_rust", "S_KIOSK": "steel_grey",
                "S_STODOLA": "wood_dark", "S_STERKOVNA": "steel_grey"}.get(sid, "wood_dark")
    win_key = {"S_DOMEK_3": "osb", "S_HOSPODA": "osb", "S_DOMEK_1": "wood_dark", "S_DOMEK_2": "wood_dark", "S_DOMEK_4": "wood_dark",
               "S_KULNA_C": "wood_dark", "S_KAPLE": "glass_dark", "S_KIOSK": "steel_grey", "S_STERKOVNA": "glass_dark"}.get(sid, "glass_dark")
    if typ == "garage_row":
        for k in range(3):
            facade_panel(sc, c0, rot, lx, ly, zb, "+Y", -lx / 2 + lx * (k + 0.5) / 3, 2.4, 0.0, 2.1, "steel_rust")
        return
    if typ == "kiosk_closed":
        facade_panel(sc, c0, rot, lx, ly, zb, "+Y", 0.0, lx * 0.8, 0.8, 2.2, "steel_grey")
        facade_panel(sc, c0, rot, lx, ly, zb, "-X", 0.3, 0.9, 0.0, 2.0, "steel_grey")
        return
    dw = 2.2 if typ in ("barn", "fire_station") else (1.4 if typ == "chapel" else 1.0)
    dh = 3.0 if typ in ("barn", "fire_station") else (2.4 if typ == "chapel" else 2.05)
    L_front = lx
    facade_panel(sc, c0, rot, lx, ly, zb, front, 0.0 if typ in ("chapel", "barn") else -L_front * 0.18, dw, 0.0, min(dh, eave - 0.3), door_key)
    if typ == "fire_station":
        facade_panel(sc, c0, rot, lx, ly, zb, front, L_front * 0.25, 2.8, 0.0, 3.2, "steel_rust")
    nwin = max(1, int(L_front / 3.2))
    for face in ("+Y", "-Y"):
        for k in range(nwin):
            u = -L_front / 2 + L_front * (k + 0.5) / nwin
            if face == front and abs(u - (-L_front * 0.18)) < 1.2 and typ not in ("chapel", "barn"):
                continue
            if eave >= 2.6 and typ not in ("barn",):
                facade_panel(sc, c0, rot, lx, ly, zb, face, u, 1.0, 0.9, min(2.1, eave - 0.4), win_key)
    for face in ("+X", "-X"):
        if eave > 2.6 and typ not in ("barn", "garage_row"):
            facade_panel(sc, c0, rot, lx, ly, zb, face, 0.0, 0.9, 0.9, min(2.1, eave - 0.4), win_key)


# ================================================================================================
# props (clearly placeholder blocks, correct size), fences / walls / hedges, vegetation blocks
# ================================================================================================
PROP_COL = {
    "car_hatchback": "#5d6f82", "van_rusty": "#7a6a55", "pickup_truck": "#6b7355", "semi_trailer_box": "#b8b4aa",
    "tipper_truck": "#c28a2c", "tractor_with_trailer": "#3f6b3a", "farm_trailer_old": "#6f5a45", "flatbed_trailer": "#5a5f63",
    "military_truck_wreck": "#4b4e3a", "bus_wreck": "#7a5a45", "lorry_wreck": "#6a4a3a", "car_wreck": "#6a5040",
    "military_truck": "#4f5a3a", "military_4x4": "#55603f", "shipping_container_20": "#5c5f3e", "skip_container": "#c2932c",
    "pallet_stack": "#a88a60", "pallets_bagged_cement": "#b9b4a8", "pallets_bricks_2high": "#a0573d", "ibc_tanks_x2": "#d8d8d0",
    "big_bags_x2": "#e0ddd0", "oil_drums_cluster": "#3d5a78", "steel_profile_stack": "#6a5a50", "concrete_pipes_stack": "#a5a19a",
    "log_pile": "#7a5a3c", "log_pile_high": "#7a5a3c", "round_bales_stack": "#c2aa70", "round_bale_single": "#c2aa70",
    "water_wheel_ruin": "#5a4231", "harrow_rusty": "#7a4b2e", "gas_bottle_cage": "#5d6b77", "greenhouse_glass": "#bfc8c8",
    "raised_bed": "#6f5a45", "garden_table_set": "#8a7a60", "paving_slab_stack": "#9a968e", "compost_bins": "#4f5f3a",
    "stone_cross": "#8a8680", "field_shrine": "#b8b0a0", "bench": "#6f5a45", "noticeboard": "#5a4231", "street_lamp": "#4a4f52",
    "hydrant": "#b0302a", "beehives_row": "#c8a040", "sandbag_wall": "#a89a70", "concrete_barrier_row": "#b3aea3",
    "ammo_crates_stack": "#4f5a3a", "gravel_heap": "#9c978c", "conveyor_frame": "#6a5a4a", "weir_stone_low": "#6f6d63",
    "sluice_gate_frame": "#5a4a3a", "hesco_line": "#bdb08f", "container_stack_2": "#5c5f3e", "forklift_parked": "#d0a020",
    "euro_pallet_stack_4": "#b89a6a", "crate_stack_mixed": "#8a7050", "barrels_plastic_blue_x3": "#2f5e9a",
    "timber_stack_on_pallets": "#9a7a50", "military_truck_parked": "#4f5a3a", "container_stack_2_10ft": "#7b4c31",
}
VEHICLES = {"car_hatchback", "van_rusty", "pickup_truck", "tipper_truck", "military_truck_wreck", "lorry_wreck", "car_wreck",
            "military_truck", "military_4x4", "military_truck_parked", "bus_wreck", "tractor_with_trailer", "forklift_parked"}


def tint(hexc, k=1.0):
    c = np.array(hex_rgb(hexc)) * k
    return (float(c[0]), float(c[1]), float(c[2]), 1.0)


def prop_class(p):
    bb = p.get("blocks_bullets", True)
    bv = p.get("blocks_vision", True)
    if bb:
        return "main"
    return "movevis" if bv else "move"


def build_prop(sc, p, terr):
    typ = p["type"]
    x, y, z = p["position"]
    rot = p["rotation_deg"]
    lx, ly, lz = p["size"]
    col = tint(PROP_COL.get(typ, "#8a8a80"))
    cls = prop_class(p)
    gf = p.get("ground_fit") or {}
    surf = "metal" if (typ in VEHICLES or "container" in typ or "steel" in typ or "drum" in typ) else (
        "wood" if ("pallet" in typ or "log" in typ or "crate" in typ or "timber" in typ or "bench" in typ) else "concrete")
    zb = z
    if gf.get("mode") == "tilt" or gf.get("mode") == "conform":
        cz = gf.get("corner_z")
        if cz:
            zb = min(cz)
    # collision: the size box (from below the ground)
    sc.obox(x, y, lx, ly, rot, zb - 0.4, z + lz, mat=False, cls=cls, surface=surf, render=False)
    if typ == "gravel_heap":
        top = [(-lx * 0.22, -ly * 0.2), (lx * 0.22, -ly * 0.2), (lx * 0.22, ly * 0.2), (-lx * 0.22, ly * 0.2)]
        bot = [(-lx / 2, -ly / 2), (lx / 2, -ly / 2), (lx / 2, ly / 2), (-lx / 2, ly / 2)]
        T_ = [(*xf((x, y), rot, q), z + lz) for q in top]
        B_ = [(*xf((x, y), rot, q), zb - 0.2) for q in bot]
        m = sc.mb("gravel_heap")
        m.poly(T_)
        for i in range(4):
            j = (i + 1) % 4
            m.poly([B_[i], B_[j], T_[j], T_[i]])
        return
    if typ == "hesco_line":
        n = max(1, int(round(lx / 1.07)))
        for k in range(n):
            u = -lx / 2 + (k + 0.5) * lx / n
            q = xf((x, y), rot, (u, 0))
            sc.obox(q[0], q[1], lx / n - 0.02, ly, rot, zb - 0.1, z + lz / 2 - 0.01, mat="hesco", collide=False)
            sc.obox(q[0], q[1], lx / n - 0.02, ly, rot, z + lz / 2, z + lz, mat="hesco", collide=False)
        return
    if typ in ("container_stack_2", "container_stack_2_10ft", "shipping_container_20"):
        n = 2 if "stack" in typ else 1
        hh = lz / n
        for k in range(n):
            c = tint(PROP_COL[typ], 1.0 if k == 0 else 0.85)
            sc.obox(x, y, lx, ly, rot, zb - 0.1 + k * hh, z + (k + 1) * hh - 0.02, mat="prop_container", color=c, collide=False)
        return
    if typ in ("semi_trailer_box", "flatbed_trailer", "farm_trailer_old"):
        deck = zb + (1.1 if typ == "semi_trailer_box" else 0.75)
        sc.obox(x, y, lx, ly * 0.9, rot, deck - 0.25, deck, mat="steel_grey", collide=False)
        top = z + lz if typ == "semi_trailer_box" else deck + (0.45 if typ == "farm_trailer_old" else 0.08)
        if top > deck + 0.01:
            key = "prop_container" if typ == "semi_trailer_box" else "furn_wood"
            sc.obox(x, y, lx, ly, rot, deck, top, mat=key, color=col, collide=False)
        wr = 0.45
        for fx_ in ((-lx / 2 + 1.2, -lx / 2 + 2.3) if typ == "semi_trailer_box" else (-lx / 4, lx / 4)):
            for fy_ in (-ly / 2 + 0.2, ly / 2 - 0.2):
                q = xf((x, y), rot, (fx_, fy_))
                sc.obox(q[0], q[1], wr * 2, 0.35, rot, zb, zb + wr * 2, mat="tyre", collide=False)
        if typ == "semi_trailer_box":
            q = xf((x, y), rot, (lx / 2 - 1.5, 0))
            sc.obox(q[0], q[1], 0.15, 0.15, rot, zb, deck - 0.25, mat="steel_grey", collide=False)
        return
    if typ in VEHICLES:
        clear = 0.35 if typ not in ("bus_wreck", "car_wreck", "lorry_wreck", "military_truck_wreck") else 0.15
        cab_frac = 0.3 if typ not in ("car_hatchback", "car_wreck", "military_4x4", "bus_wreck", "van_rusty") else 1.0
        body_top = z + lz * (0.55 if cab_frac < 1 else 0.6)
        sc.obox(x, y, lx, ly * 0.96, rot, zb + clear, body_top, mat="prop_paint", color=col, collide=False)
        if cab_frac < 1:
            q = xf((x, y), rot, (lx / 2 - lx * cab_frac / 2, 0))
            sc.obox(q[0], q[1], lx * cab_frac, ly * 0.94, rot, body_top, z + lz, mat="prop_paint", color=col, collide=False)
            # cargo / trailer load
            q = xf((x, y), rot, (-lx * cab_frac / 2, 0))
            sc.obox(q[0], q[1], lx * (1 - cab_frac) - 0.2, ly * 0.96, rot, body_top, body_top + 0.25, mat="prop_paint",
                    color=tint(PROP_COL[typ], 0.8), collide=False)
        else:
            sc.obox(x, y, lx * 0.62, ly * 0.9, rot, body_top, z + lz, mat="prop_paint", color=tint(PROP_COL[typ], 0.95), collide=False)
            q = xf((x, y), rot, (lx * 0.05, 0))
            sc.obox(q[0], q[1], lx * 0.55, ly * 0.92, rot, body_top + 0.12, z + lz - 0.15, mat="glass_dark", collide=False)
        wr = min(0.55, lz * 0.22)
        for fx_ in (-lx / 2 + wr + 0.3, lx / 2 - wr - 0.3):
            for fy_ in (-ly / 2 + 0.12, ly / 2 - 0.12):
                q = xf((x, y), rot, (fx_, fy_))
                sc.obox(q[0], q[1], wr * 2, 0.28, rot, zb, zb + wr * 2, mat="tyre", collide=False)
        return
    if typ == "conveyor_frame":
        # sloped belt on legs
        a = xf((x, y), rot, (-lx / 2, 0))
        b = xf((x, y), rot, (lx / 2, 0))
        sc.seg_wall(a, b, ly, zb + 0.8, zb + lz - 0.6, zb + 1.2, zb + lz, mat="steel_rust", collide=False)
        for k in range(4):
            q = xf((x, y), rot, (-lx / 2 + lx * (k + 0.5) / 4, 0))
            sc.obox(q[0], q[1], 0.2, ly * 0.8, rot, zb, zb + 0.8 + (lz - 1.4) * (k + 0.5) / 4, mat="steel_rust", collide=False)
        return
    if typ == "street_lamp":
        sc.obox(x, y, 0.16, 0.16, rot, zb - 0.1, z + lz, mat="steel_grey", collide=False)
        q = xf((x, y), rot, (0.5, 0))
        sc.obox(q[0], q[1], 1.1, 0.12, rot, z + lz - 0.15, z + lz, mat="steel_grey", collide=False)
        q = xf((x, y), rot, (0.9, 0))
        sc.obox(q[0], q[1], 0.4, 0.25, rot, z + lz - 0.25, z + lz - 0.12, mat="lamp_emissive", collide=False)
        return
    key = {"log_pile": "logs", "log_pile_high": "logs", "round_bales_stack": "bales", "round_bale_single": "bales"}.get(typ, "prop")
    if typ == "concrete_barrier_row":
        n = max(1, int(round(lx / 2.0)))
        for k in range(n):
            q = xf((x, y), rot, (-lx / 2 + (k + 0.5) * lx / n, 0))
            sc.obox(q[0], q[1], lx / n - 0.05, ly, rot, zb - 0.1, z + lz * 0.35, mat="concrete", collide=False)
            sc.obox(q[0], q[1], lx / n - 0.05, ly * 0.35, rot, z + lz * 0.35, z + lz, mat="concrete", collide=False)
        return
    if typ in ("pallet_stack", "euro_pallet_stack_4", "timber_stack_on_pallets", "crate_stack_mixed", "ammo_crates_stack"):
        sc.obox(x, y, lx, ly, rot, zb - 0.05, z + lz, mat="furn_wood" if "ammo" not in typ else "prop", color=col, collide=False)
        return
    sc.obox(x, y, lx, ly, rot, zb - 0.1, z + lz, mat=key, color=col if key == "prop" else None, collide=False)


def ground_pieces(terr, pl, step=2.5):
    """splits a polyline into pieces <= step with ground heights at both ends."""
    out = []
    for a, b in zip(pl[:-1], pl[1:]):
        L = math.dist(a[:2], b[:2])
        n = max(1, int(math.ceil(L / step)))
        for k in range(n):
            p = (a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n)
            q = (a[0] + (b[0] - a[0]) * (k + 1) / n, a[1] + (b[1] - a[1]) * (k + 1) / n)
            out.append((p, q, terr.z1(*p), terr.z1(*q)))
    return out


def build_fence(sc, f, terr):
    typ = f["type"]
    h = f["height"]
    sh = f.get("solid_height", 0.0) or 0.0
    pl = f["polyline"]
    pieces = ground_pieces(terr, pl, 2.5)
    if "hedge" in typ:
        wd = 1.2 if typ != "hedgerow_mixed" else 1.6
        key = "hedge"
        for (p, q, za, zb) in pieces:
            jitter = 0.15 * math.sin(p[0] * 1.7 + p[1] * 0.9)
            if typ == "hedgerow_mixed":
                sc.seg_wall(p, q, wd, za - 0.3, zb - 0.3, za + h + jitter, zb + h + jitter, mat=False, cls="movevis", surface="grass", render=False)
                sc.seg_wall(p, q, wd - 0.6, za - 0.3, zb - 0.3, za + h * 0.8 + jitter, zb + h * 0.8 + jitter, mat="veg_core", collide=False)
            else:
                sc.seg_wall(p, q, wd, za - 0.3, zb - 0.3, za + h + jitter, zb + h + jitter, mat=key, cls="movevis", surface="grass")
        return
    if typ in ("garden_wall_rendered_1p8", "concrete_low_wall", "concrete_low_wall_rendered"):
        th = 0.3 if "garden" in typ else 0.25
        key = "plaster_cream" if ("rendered" in typ) else "concrete"
        for (p, q, za, zb) in pieces:
            sc.seg_wall(p, q, th, za - 0.3, zb - 0.3, za + h, zb + h, mat=key, cls="main", surface="concrete", sub=1.5)
            sc.seg_wall(p, q, th + 0.08, za + h, zb + h, za + h + 0.06, zb + h + 0.06, mat="concrete", collide=False)
        return
    if typ == "post_and_pipe_rail_1m":
        for (p, q, za, zb) in pieces:
            sc.obox(p[0], p[1], 0.25, 0.25, 0, za - 0.2, za + h, mat="concrete", collide=False)
            for zz in (0.45, 0.9):
                sc.seg_wall(p, q, 0.06, za + zz - 0.03, zb + zz - 0.03, za + zz + 0.03, zb + zz + 0.03, mat="steel_rust", collide=False)
            sc.seg_wall(p, q, 0.25, za - 0.2, zb - 0.2, za + h, zb + h, mat=False, cls="move", surface="metal", render=False)
        q = pieces[-1][1]
        sc.obox(q[0], q[1], 0.25, 0.25, 0, pieces[-1][3] - 0.2, pieces[-1][3] + h, mat="concrete", collide=False)
        return
    if typ == "timber_picket_1m":
        for (p, q, za, zb) in pieces:
            sc.obox(p[0], p[1], 0.1, 0.1, 0, za - 0.2, za + h, mat="wood_grey", collide=False)
            for zz in (0.25, 0.8):
                sc.seg_wall(p, q, 0.04, za + zz, zb + zz, za + zz + 0.08, zb + zz + 0.08, mat="wood_grey", collide=False)
            L = math.dist(p, q)
            n = max(1, int(L / 0.14))
            for k in range(n):
                t_ = (k + 0.5) / n
                xx, yy = p[0] + (q[0] - p[0]) * t_, p[1] + (q[1] - p[1]) * t_
                zg = za + (zb - za) * t_
                sc.obox(xx, yy, 0.07, 0.03, math.degrees(math.atan2(q[1] - p[1], q[0] - p[0])), zg + 0.05, zg + h - 0.05, mat="wood_grey", collide=False)
            sc.seg_wall(p, q, 0.12, za - 0.2, zb - 0.2, za + h, zb + h, mat=False, cls="move", surface="wood", render=False)
        return
    # chain-link (on a plinth / on a low concrete wall)
    for (p, q, za, zb) in pieces:
        if sh > 0.01:
            sc.seg_wall(p, q, 0.25 if sh > 0.5 else 0.2, za - 0.3, zb - 0.3, za + sh, zb + sh, mat="concrete", cls="main", surface="concrete")
        sc.obox(p[0], p[1], 0.07, 0.07, 0, za - 0.2, za + h, mat="steel_blue", collide=False)
        # mesh panel (double sided, alpha tested): see-through for sight and bullets
        zl0a, zl0b = za + max(sh, 0.05), zb + max(sh, 0.05)
        m = sc.mb("chainlink")
        P4 = np.array([(p[0], p[1], zl0a), (q[0], q[1], zl0b), (q[0], q[1], za + h), (p[0], p[1], za + h)])
        L = math.dist(p, q)
        nrm = np.cross(P4[1] - P4[0], P4[3] - P4[0])
        nrm = nrm / max(np.linalg.norm(nrm), 1e-9)
        m.add(P4, nrm, [(0, zl0a - za), (L, zl0b - zb), (L, h), (0, h)], (1, 1, 1, 1), [(0, 1, 2), (0, 2, 3)])
        sc.seg_wall(p, q, 0.1, za + sh if sh > 0.01 else za - 0.2, zb + sh if sh > 0.01 else zb - 0.2, za + h, zb + h,
                    mat=False, cls="move", surface="metal", render=False)
    q = pieces[-1][1]
    sc.obox(q[0], q[1], 0.07, 0.07, 0, pieces[-1][3] - 0.2, pieces[-1][3] + h, mat="steel_blue", collide=False)


def build_vegetation_block(sc, vb, terr):
    """collision: the block volume (class movevis, exactly as before); render: a dark leafy core inset 0.35 m and
    lowered 0.6 m. The visible shrubs are instances (shrub_instances, assets/environment/vegetation.glb)."""
    h = vb["height"]
    if "polyline" in vb:
        wd = vb["width"]
        for (p, q, za, zb) in ground_pieces(terr, vb["polyline"], 3.0):
            j = 0.35 * math.sin(p[0] * 0.8 + p[1] * 1.3)
            sc.seg_wall(p, q, wd, za - 0.4, zb - 0.4, za + h + j, zb + h + j, mat=False, cls="movevis", surface="grass", render=False)
            sc.seg_wall(p, q, max(0.4, wd - 0.7), za - 0.4, zb - 0.4, za + h * 0.8 + j, zb + h * 0.8 + j, mat="veg_core", collide=False)
    else:
        P = Polygon(vb["polygon"])
        zc = terr.z1(P.centroid.x, P.centroid.y)
        pts = [tuple(c) for c in list(P.exterior.coords)[:-1]]
        zmin = min(terr.z1(*p) for p in pts)
        sc.prism(pts, zmin - 0.5, zc + h, mat=False, cls="movevis", surface="grass", render=False)
        inner = P.buffer(-0.5, join_style=2)
        if not inner.is_empty and inner.geom_type == "Polygon":
            sc.prism([tuple(c) for c in list(inner.exterior.coords)[:-1]], zmin - 0.5, zc + h * 0.8, mat="veg_core", collide=False)


# ================================================================================================
# retaining walls, bridges, water, utility poles, boundary
# ================================================================================================
def build_retaining_walls(sc, L, terr):
    for rw in L["retaining_walls"]:
        segs = rw.get("segments") or [[k, k + 1] for k in range(len(rw["polyline"]) - 1)]
        prof = rw.get("top_z_profile")
        bprof = rw.get("bottom_z_profile")
        mat_s = "stone" if "stone" in (rw.get("material") or "") else "concrete"
        par = rw.get("parapet")
        for i0, i1 in segs:
            a, b = rw["polyline"][i0], rw["polyline"][i1]
            za_t = prof[i0] if prof else rw["top_z"]
            zb_t = prof[i1] if prof else rw["top_z"]
            za_b = (bprof[i0] if bprof else rw["bottom_z"]) - 0.5
            zb_b = (bprof[i1] if bprof else rw["bottom_z"]) - 0.5
            if par:
                zpa = za_t - par["height_above_terrace"]
                sc.seg_wall(a, b, rw["thickness"], za_b, zb_b, zpa, zb_t - par["height_above_terrace"], mat=mat_s, cls="main", surface="stone", sub=1.5)
                sc.seg_wall(a, b, rw["thickness"] - 0.1, zpa, zb_t - par["height_above_terrace"], za_t, zb_t, mat="plaster_cream", cls="main", surface="concrete", sub=1.5)
            else:
                sc.seg_wall(a, b, rw["thickness"], za_b, zb_b, za_t, zb_t, mat=mat_s, cls="main", surface="stone", sub=1.5)
            cap = rw.get("cap") or {}
            if cap:
                sc.seg_wall(a, b, rw["thickness"] + 2 * cap.get("overhang", 0.05), za_t, zb_t, za_t + cap.get("height", 0.1),
                            zb_t + cap.get("height", 0.1), mat="concrete", cls="main", surface="concrete")
            g = rw.get("guard")
            if g:
                gh = g.get("height", 1.0) if isinstance(g, dict) else 1.0
                za0 = za_t + (cap.get("height", 0.1) if cap else 0)
                zb0 = zb_t + (cap.get("height", 0.1) if cap else 0)
                sc.seg_wall(a, b, 0.05, za0 + gh - 0.05, zb0 + gh - 0.05, za0 + gh, zb0 + gh, mat="steel_blue", collide=False)
                sc.seg_wall(a, b, 0.04, za0 + gh * 0.5 - 0.02, zb0 + gh * 0.5 - 0.02, za0 + gh * 0.5 + 0.02, zb0 + gh * 0.5 + 0.02, mat="steel_blue", collide=False)
                Ls = math.dist(a[:2], b[:2])
                for k in range(int(Ls / 1.5) + 1):
                    t_ = min(1.0, k * 1.5 / max(Ls, 1e-6))
                    x_, y_ = a[0] + (b[0] - a[0]) * t_, a[1] + (b[1] - a[1]) * t_
                    z_ = za0 + (zb0 - za0) * t_
                    sc.obox(x_, y_, 0.05, 0.05, 0, z_, z_ + gh, mat="steel_blue", collide=False)
                sc.seg_wall(a, b, 0.08, za0, zb0, za0 + gh, zb0 + gh, mat=False, cls="move", surface="metal", render=False)
        for wg in rw.get("wing_walls", []):
            pts = wg["polyline"]
            for a, b in zip(pts[:-1], pts[1:]):
                za = terr.z1(*a)
                zb = terr.z1(*b)
                # stepped top: from the wall end (first point: at the retaining wall) down to the ground + 0.3 at the free end
                zt0 = max(za + 0.3, rw["top_z"] - 0.1 if not prof else max(prof) - 0.1)
                zt0 = min(zt0, za + 2.6)
                sc.seg_wall(a, b, wg["thickness"], za - 0.5, zb - 0.5, zt0, zb + 0.3, mat=mat_s, cls="main", surface="stone")
        for st in rw.get("stairs", []):
            A = np.array(st["bottom_center_world"], float)
            Bp = np.array(st["top_center_world"], float)
            d = (Bp - A) / np.linalg.norm(Bp - A)
            n = np.array([-d[1], d[0]])
            hw = st["width"] / 2
            za = rw["bottom_z"]
            zt = rw["top_z"] - (par["height_above_terrace"] if par else 0.10)
            count = st.get("risers", 11)
            riser = (zt - za) / count
            run = np.linalg.norm(Bp - A)
            tread = run / max(count - 1, 1)
            for i in range(count - 1):
                d0, d1 = i * tread, (i + 1) * tread
                top = za + riser * (i + 1)
                q = [A + n * hw + d * d0, A - n * hw + d * d0, A - n * hw + d * d1, A + n * hw + d * d1]
                sc.prism([tuple(v) for v in q], za - 0.3, top, mat="concrete", cls="main", surface="concrete")
            # landing strip at the top
            q = [A + n * hw + d * run, A - n * hw + d * run, A - n * hw + d * (run + 0.4), A + n * hw + d * (run + 0.4)]
            sc.prism([tuple(v) for v in q], za - 0.3, zt, mat="concrete", cls="main", surface="concrete")
            # side walls following the pitch
            for sg in (-1, 1):
                p0 = A + n * sg * (hw + 0.15) - d * 0.1
                p1 = A + n * sg * (hw + 0.15) + d * (run + 0.3)
                sc.seg_wall(tuple(p0), tuple(p1), 0.3, za - 0.3, za - 0.3, za + 0.9, zt + 0.9, mat="concrete", cls="main", surface="concrete")


def build_bridges(sc, L, terr):
    for br in L["bridges"]:
        a, b = np.array(br["ends"][0], float), np.array(br["ends"][1], float)
        d = (b - a) / np.linalg.norm(b - a)
        n = np.array([-d[1], d[0]])
        hw = br["width"] / 2
        za, zb = br["deck_z"]
        th = br.get("deck_thickness", 0.3)
        pa = a - d * 0.5
        pb = b + d * 0.5
        corners = [(*(pa + n * hw), za), (*(pa - n * hw), za), (*(pb - n * hw), zb), (*(pb + n * hw), zb)]
        sc.sloped_slab(corners, th, mat="concrete", cls="main", surface="concrete", sub=1.5)
        rl = br.get("railing", {})
        rh = rl.get("height", 1.1)
        Lb = np.linalg.norm(b - a)
        for sg in (-1, 1):
            off = n * sg * (hw - 0.08)
            p0 = a + off
            p1 = b + off
            sc.seg_wall(tuple(p0), tuple(p1), 0.12, za, zb, za + rh, zb + rh, mat=False, cls="move", surface="metal", render=False)
            npost = max(2, int(Lb / 2.0) + 1)
            for k in range(npost):
                t_ = k / (npost - 1)
                q = p0 + (p1 - p0) * t_
                z_ = za + (zb - za) * t_
                sc.obox(q[0], q[1], 0.25 if "concrete" in rl.get("type", "") else 0.06, 0.25 if "concrete" in rl.get("type", "") else 0.06,
                        math.degrees(math.atan2(d[1], d[0])), z_ - 0.05, z_ + rh, mat="concrete" if "concrete" in rl.get("type", "") else "steel_blue", collide=False)
            for zz in (0.5, rh - 0.05):
                sc.seg_wall(tuple(p0), tuple(p1), 0.06, za + zz - 0.03, zb + zz - 0.03, za + zz + 0.03, zb + zz + 0.03, mat="steel_rust", collide=False)
        if br.get("underpass", {}).get("treatment") == "closed":
            for sg in (-1, 1):
                p0 = a + n * sg * (hw + 0.05)
                p1 = b + n * sg * (hw + 0.05)
                zlo = min(terr.z1(*(p0 + (p1 - p0) * t)) for t in np.linspace(0, 1, 9))
                ztop = min(za, zb) - th
                if ztop > zlo:
                    sc.seg_wall(tuple(p0), tuple(p1), 0.06, zlo - 0.3, zlo - 0.3, ztop, ztop, mat="steel_blue", cls="move", surface="metal")


def build_water(sc, L):
    for w in L["water"]:
        pl = w["polyline"]
        hw = w["width_at_surface"] / 2 + 0.25
        m = sc.mb("water")
        for p, q in zip(pl[:-1], pl[1:]):
            d = np.array(q[:2], float) - np.array(p[:2], float)
            Ls = np.linalg.norm(d)
            if Ls < 1e-6:
                continue
            d /= Ls
            n = np.array([-d[1], d[0]])
            P = [(*(np.array(p[:2]) - n * hw), p[2] + 0.02), (*(np.array(q[:2]) - n * hw), q[2] + 0.02),
                 (*(np.array(q[:2]) + n * hw), q[2] + 0.02), (*(np.array(p[:2]) + n * hw), p[2] + 0.02)]
            m.poly(P)


def build_poles(sc, L, terr):
    ul = L.get("utility_lines", {})
    poles = {po["id"]: po for po in ul.get("poles", [])}
    for po in poles.values():
        x, y, z = po["pos"]
        r = po.get("collision_radius", 0.14)
        sc.cylinder(x, y, r, z - 0.3, z + po["height"], "wood_dark", segs=8, cls="main", surface="wood")
        sc.obox(x, y, 1.6, 0.1, 0, z + po["height"] - 0.6, z + po["height"] - 0.5, mat="wood_dark", collide=False)
        sc.obox(x, y, 0.24, 0.24, 0, z, z + 1.2, mat="prop", color=(0.85, 0.72, 0.1, 1), collide=False)
        if po.get("lamp"):
            sc.obox(x + 0.4, y, 0.7, 0.08, 0, z + po["height"] - 1.5, z + po["height"] - 1.42, mat="steel_grey", collide=False)
            sc.obox(x + 0.75, y, 0.34, 0.34, 0, z + po["height"] - 1.62, z + po["height"] - 1.5, mat="lamp_emissive", collide=False)
    for sp in ul.get("spans", []):
        a = poles.get(sp.get("from"))
        b = poles.get(sp.get("to"))
        if not a or not b:
            continue
        pa = np.array([a["pos"][0], a["pos"][1], a["pos"][2] + a["height"] - 0.55])
        pb = np.array([b["pos"][0], b["pos"][1], b["pos"][2] + b["height"] - 0.55])
        sag = sp.get("sag", 0.6) if isinstance(sp.get("sag"), (int, float)) else 0.6
        pts = [pa + (pb - pa) * t - np.array([0, 0, 4 * sag * t * (1 - t)]) for t in np.linspace(0, 1, 9)]
        for off in (-0.6, 0.6):
            dd = pb[:2] - pa[:2]
            nn = np.array([-dd[1], dd[0]]) / max(np.linalg.norm(dd), 1e-6) * off
            for p, q in zip(pts[:-1], pts[1:]):
                sc.seg_wall((p[0] + nn[0], p[1] + nn[1]), (q[0] + nn[0], q[1] + nn[1]), 0.02, p[2] - 0.012, q[2] - 0.012, p[2] + 0.012, q[2] + 0.012,
                            mat="frame_dark", collide=False)


def build_boundary(sc, L, terr):
    bnd = L["boundary"]
    for ba in bnd["barriers"]:
        typ = ba["type"]
        h = ba.get("height", 1.4)
        pieces = ground_pieces(terr, ba["polyline"], 2.5)
        for (p, q, za, zb) in pieces:
            if typ == "roadblock":
                sc.seg_wall(p, q, 0.6, za - 0.2, zb - 0.2, za + 0.35, zb + 0.35, mat="concrete", cls="main", surface="concrete")
                sc.seg_wall(p, q, 0.22, za + 0.35, zb + 0.35, za + 0.9, zb + 0.9, mat="concrete", cls="main", surface="concrete")
                sc.seg_wall(p, q, 0.3, za + 0.9, zb + 0.9, za + max(h, 1.6), zb + max(h, 1.6), mat=False, cls="move", surface="metal", render=False)
                continue
            post = "wood_dark" if typ in ("pasture_fence_barbed_1p3m", "farm_fence_timber_1p4m", "deer_fence_2m") else "steel_blue"
            sc.obox(p[0], p[1], 0.12, 0.12, 0, za - 0.2, za + h, mat=post, collide=False)
            if typ in ("deer_fence_2m", "quarry_fence_2m"):
                key = "mesh_deer" if typ == "deer_fence_2m" else "chainlink"
                m = sc.mb(key)
                P4 = np.array([(p[0], p[1], za + 0.05), (q[0], q[1], zb + 0.05), (q[0], q[1], zb + h), (p[0], p[1], za + h)])
                Lp = math.dist(p, q)
                nrm = np.cross(P4[1] - P4[0], P4[3] - P4[0])
                m.add(P4, nrm / max(np.linalg.norm(nrm), 1e-9), [(0, 0), (Lp, 0), (Lp, h), (0, h)], (1, 1, 1, 1), [(0, 1, 2), (0, 2, 3)])
            elif typ == "farm_fence_timber_1p4m":
                for zz in (0.35, 0.8, 1.25):
                    sc.seg_wall(p, q, 0.05, za + zz, zb + zz, za + zz + 0.12, zb + zz + 0.12, mat="wood_grey", collide=False)
            else:
                for zz in (0.3, 0.65, 1.0, 1.25):
                    sc.seg_wall(p, q, 0.015, za + zz, zb + zz, za + zz + 0.015, zb + zz + 0.015, mat="frame_dark", collide=False)
            sc.seg_wall(p, q, 0.12, za - 0.2, zb - 0.2, za + max(h, 1.3), zb + max(h, 1.3), mat=False, cls="move", surface="metal", render=False)
        q = pieces[-1][1]
        sc.obox(q[0], q[1], 0.12, 0.12, 0, pieces[-1][3] - 0.2, pieces[-1][3] + h, mat="wood_dark", collide=False)
        for sg in ba.get("signs", []):
            x, y = sg["pos"]
            zg = terr.z1(x, y)
            kind = {"sign_minefield": "sign_mines", "sign_quarry": "sign_quarry", "sign_checkpoint": "sign_checkpoint",
                    "sign_hunting": "sign_hunting", "sign_road_a": "sign_road"}.get(sg.get("text_id"), "sign_mines")
            # face towards the map centre (inwards)
            ang = math.atan2(-y, -x)
            dx, dy = math.cos(ang), math.sin(ang)
            tx, ty = -dy, dx
            w2, h2 = 0.6, 0.3
            zc = zg + 1.45
            c = (x + dx * 0.08, y + dy * 0.08)
            P4 = np.array([(c[0] - tx * w2, c[1] - ty * w2, zc - h2), (c[0] + tx * w2, c[1] + ty * w2, zc - h2),
                           (c[0] + tx * w2, c[1] + ty * w2, zc + h2), (c[0] - tx * w2, c[1] - ty * w2, zc + h2)])
            nrm = np.cross(P4[1] - P4[0], P4[3] - P4[0])
            nrm = nrm / np.linalg.norm(nrm)
            if nrm[0] * dx + nrm[1] * dy < 0:
                P4 = P4[[1, 0, 3, 2]]
                nrm = -nrm
            sc.mb(kind).add(P4, nrm, [(0, 1), (1, 1), (1, 0), (0, 0)], (1, 1, 1, 1), [(0, 1, 2), (0, 2, 3)])
            sc.obox(x, y, 1.25, 0.03, math.degrees(ang) + 90, zc - h2 - 0.02, zc + h2 + 0.02, mat="frame_dark", collide=False)
            sc.obox(x, y, 0.07, 0.07, 0, zg - 0.2, zc, mat="steel_grey", collide=False)
    # invisible hard wall (capsules only; bullets and sight ignore it)
    hard = bnd["hard_polygon"]
    ring = list(hard) + [hard[0]]
    for a, b in zip(ring[:-1], ring[1:]):
        for (p, q, za, zb) in ground_pieces(terr, [a, b], 4.0):
            sc.seg_wall(p, q, 0.3, za - 2.0, zb - 2.0, za + 6.0, zb + 6.0, mat=False, cls="move", surface="metal", render=False, nav=False)


# ================================================================================================
# trees (trunk collision; models are instanced at run time), outer terrain, backdrop hills
# ================================================================================================
def build_trees(L, terr, sc):
    """tree trunk collision (class main, 2 x trunk radius box up to the crown base, min. 1.8 m) for the trees inside
    the hard boundary -- unchanged from the blockout. The visible trees are instances of the Blender-generated
    models (tree_instances -> kh_world.glb extras, models in assets/environment/vegetation.glb)."""
    sp = L["trees"]["species"]
    hard = terr.hard.buffer(1.0)
    n = 0
    for t in L["trees"]["instances"]:
        s = sp[t["species"]]
        k = t.get("scale", 1.0)
        x, y = t["pos"][0], t["pos"][1]
        z = terr.z1(x, y) - 0.1
        cb = s["crown_base"] * k
        tr = s["trunk_radius"] * k
        n += 1
        if hard.contains(Point(x, y)):
            sc.obox(x, y, 2 * tr, 2 * tr, 0, z - 0.2, z + max(cb, 1.8), mat=False, cls="main", surface="wood", render=False)
    return n


def outer_terrain(sc, terr):
    """2 m terrain over the data square outside the fine region (render only, vertex colours), lowered 8 cm."""
    X, Y, H = terr.cX, terr.cY, terr.cH
    inner = terr.region.buffer(-3.0)
    n = X.shape[0]
    cx = (X[:-1, :-1] + X[1:, 1:]) / 2
    cy = (Y[:-1, :-1] + Y[1:, 1:]) / 2
    mask = ~MPath(np.array(inner.exterior.coords)).contains_points(np.column_stack([cx.ravel(), cy.ravel()])).reshape(cx.shape)
    soft = terr.soft
    noise = value_noise((n, n), 10, SEED + 5, 4)
    base_forest = np.array(hex_rgb("#4d5a36"))
    base_meadow = np.array(hex_rgb("#7f8c4c"))
    d = poly_signed_dist(list(soft.exterior.coords), X, Y)
    f = np.clip((d - 10) / 25.0, 0, 1)[..., None]
    col = base_meadow * (1 - f) + base_forest * f
    col = col * (0.85 + 0.3 * noise[..., None])
    m = sc.mb("terrain_outer")
    jj, ii = np.nonzero(mask)
    vid = -np.ones((n, n), np.int64)
    used = np.zeros((n, n), bool)
    for dj in (0, 1):
        for di in (0, 1):
            used[jj + dj, ii + di] = True
    vid[used] = np.arange(used.sum())
    vj, vi = np.nonzero(used)
    P = np.column_stack([X[vj, vi], Y[vj, vi], H[vj, vi] - 0.08])
    gy, gx = np.gradient(H, OUTER_RES)
    N = np.column_stack([-gx[vj, vi], -gy[vj, vi], np.ones(len(vj))])
    N /= np.linalg.norm(N, axis=1, keepdims=True)
    C4 = np.column_stack([col[vj, vi], np.ones(len(vj))])
    a = vid[jj, ii]
    b = vid[jj, ii + 1]
    c = vid[jj + 1, ii + 1]
    dd = vid[jj + 1, ii]
    I = np.concatenate([np.column_stack([a, b, c]), np.column_stack([a, c, dd])])
    m.add(P, N, P[:, :2] / 4.0, C4, I)
    log(f"outer terrain: {len(P)} verts, {len(I)} tris")


def catmull_periodic(vals, t):
    n = len(vals)
    i = int(math.floor(t)) % n
    f = t - math.floor(t)
    p0, p1, p2, p3 = vals[(i - 1) % n], vals[i], vals[(i + 1) % n], vals[(i + 2) % n]
    return 0.5 * ((2 * p1) + (-p0 + p2) * f + (2 * p0 - 5 * p1 + 4 * p2 - p3) * f * f + (-p0 + 3 * p1 - 3 * p2 + p3) * f ** 3)


def backdrop(sc, L, terr):
    bd = L["terrain"]["backdrop"]
    crest = bd["crest"]
    dists = [c[1] for c in crest]
    heights = [c[2] for c in crest]
    outer = bd["outer_radius"]
    naz = 144
    offs = [0, 8, 20, 40, 70, 110, 170, 250, 350, 480, 650, 850, 1100, 1400, 1800, 2300]
    rows = []
    r_ = rng(SEED + 9)
    for k in range(naz):
        az = 360.0 * k / naz
        a = math.radians(az)
        sx, sy = math.sin(a), math.cos(a)
        r0 = 175.5 / max(abs(sx), abs(sy))
        cd = catmull_periodic(dists, az / 10.0)
        chh = catmull_periodic(heights, az / 10.0)
        ex, ey = sx * r0, sy * r0
        z0 = float(terr.coarse_z(np.array([max(-175.9, min(175.9, ex))]), np.array([max(-175.9, min(175.9, ey))]))[0])
        row = []
        for o in offs:
            r = r0 + o
            if r > outer:
                r = outer
            if r <= cd:
                t = (r - r0) / max(cd - r0, 1.0)
                t = t * t * (3 - 2 * t)
                z = z0 + (chh - z0) * t
            else:
                t = (r - cd) / max(outer - cd, 1.0)
                z = chh * (1 - 0.4 * t)
            z += (r_.random() - 0.5) * min(12.0, o * 0.02)
            row.append((sx * r, sy * r, z))
        rows.append(row)
    m = sc.mb("backdrop")
    forest = np.array(hex_rgb("#3e4a30"))
    field = np.array(hex_rgb("#8a9152"))
    for k in range(naz):
        r1 = rows[k]
        r2 = rows[(k + 1) % naz]
        az = 360.0 * k / naz
        for j in range(len(offs) - 1):
            P = [r1[j], r2[j], r2[j + 1], r1[j + 1]]
            zz = sum(p[2] for p in P) / 4
            fld = 110 <= az <= 150 and zz < 70
            c = (field if fld else forest) * (0.82 + 0.3 * r_.random())
            m.poly(P, color=(*c, 1.0))
    log(f"backdrop: {naz} x {len(offs)} ring")


# ================================================================================================
# light bake: sky visibility + one bounce of sunlight per vertex (mathutils BVH)
# ================================================================================================
def cosine_dirs(count):
    g = math.pi * (3 - math.sqrt(5))
    out = []
    for k in range(count):
        rr = math.sqrt((k + 0.5) / count)
        ph = k * g
        out.append((rr * math.cos(ph), rr * math.sin(ph), math.sqrt(max(0.0, 1 - rr * rr))))
    return np.array(out)


def sun_dir(L):
    env = json.load(open(os.path.join(ROOT, "Web", "src", "data", "environment.json")))
    el = math.radians(env["sun"]["elevationDeg"])
    az = math.radians(env["sun"]["azimuthDeg"])
    # compass azimuth from north, clockwise; level frame +Y north, +X east
    return np.array([math.sin(az) * math.cos(el), math.cos(az) * math.cos(el), math.sin(el)])


class Baker:
    def __init__(self, tris, albedo, sun, rays=16, maxd=30.0):
        from mathutils.bvhtree import BVHTree
        V = tris.reshape(-1, 3)
        self.albedo = albedo
        polys = [(3 * i, 3 * i + 1, 3 * i + 2) for i in range(len(tris))]
        self.bvh = BVHTree.FromPolygons([tuple(map(float, v)) for v in V], polys, all_triangles=True, epsilon=0.0)
        self.dirs = cosine_dirs(rays)
        self.sun = sun
        self.maxd = maxd
        from mathutils import Vector
        self.Vector = Vector
        self.sunv = Vector(tuple(map(float, sun)))

    def bake(self, P, N, label=""):
        Vec = self.Vector
        out = np.zeros((len(P), 4))
        dirs = self.dirs
        t0 = time.time()
        sunv = self.sunv
        amb_share = 0.065
        for i in range(len(P)):
            n = N[i]
            if abs(n[2]) < 0.99:
                t = np.cross((0, 0, 1), n)
            else:
                t = np.cross((1, 0, 0), n)
            t /= np.linalg.norm(t)
            b = np.cross(n, t)
            D = dirs[:, :1] * t + dirs[:, 1:2] * b + dirs[:, 2:3] * n
            o = Vec(tuple(map(float, P[i] + n * 0.03)))
            sky = 0
            back = 0
            br = bg = bb = 0.0
            for d in D:
                dv = Vec((float(d[0]), float(d[1]), float(d[2])))
                loc, hn, idx, dist = self.bvh.ray_cast(o, dv, self.maxd)
                if loc is None:
                    sky += 1
                    continue
                if hn.dot(dv) > 0:
                    back += 1
                    continue
                a = self.albedo[idx]
                e = amb_share
                cs = hn.dot(sunv)
                if cs > 0:
                    l2, _, _, _ = self.bvh.ray_cast(loc + hn * 0.02, sunv, 300.0)
                    if l2 is None:
                        e += cs
                br += a[0] * e
                bg += a[1] * e
                bb += a[2] * e
            k = len(D)
            if back >= k * 0.25:
                out[i] = (-1, 0, 0, 0)
                continue
            out[i] = (sky / k, br / k, bg / k, bb / k)
        log(f"bake {label}: {len(P)} vertices, {time.time() - t0:.1f} s")
        return out


def pack_light(L4):
    """(skyvis, bounce rgb) -> u8 RGBA: R G B = bounce * 2 (clamped), A = sky visibility."""
    out = np.zeros((len(L4), 4))
    out[:, 0:3] = np.clip(L4[:, 1:4] * 2.0, 0, 1)
    out[:, 3] = np.clip(L4[:, 0], 0, 1)
    return np.round(out * 255).astype(np.uint8)


# ================================================================================================
# terrain splat control maps + grass density + vegetation instances (map art pass phase 1, decision D13)
#   - weights of the terrain texture-array layers (Art/Textures/Environment/Terrain/terrain_layers.json) at 0.25 m
#     over the whole data square, 3 RGBA PNGs (12 channels: 10 layers, puddle / wetness, spare)
#   - macro tint (1 m, RGB multiplier * 0.5) against visible tiling and for dry / damp / tyre-worn areas
#   - grass density (0.5 m, RGB = low clumps, tall grass, flowers) for the runtime grass scatter
#   - tree / shrub instance tables; the models live in assets/environment/vegetation.glb (the backdrop forest is
#     scattered at run time over the forest part of the backdrop ring, src/level/vegetation.js)
# ================================================================================================
SPLAT_RES = 0.25
SPLAT_HALF = 176.0
GRASS_RES = 0.5
TERRAIN_LAYERS_JSON = os.path.join(ROOT, "Art", "Textures", "Environment", "Terrain", "terrain_layers.json")
SURF_LAYER = {"asphalt": "Asphalt", "gravel": "Gravel", "dirt": "Dirt", "mud": "Mud", "grass": "GrassGround",
              "forest_floor": "ForestFloor", "concrete": "Concrete", "paving": "PavingSetts", "stone": "RiverStones",
              "water": "RiverStones", "wood": "Concrete", "metal": "Concrete", "tiles": "Concrete"}
# boundary wobble of each surface (m): irregular, natural edges instead of the vector outlines
BOUNDARY_WOBBLE = {"asphalt": 0.05, "gravel": 0.14, "dirt": 0.2, "mud": 0.3, "grass": 0.25, "forest_floor": 1.8,
                   "concrete": 0.03, "paving": 0.04, "stone": 0.15, "water": 0.04}
# transition width of each layer (Gaussian sigma in 0.25 m texels; the shader sharpens it by height)
LAYER_SIGMA = {"Asphalt": 0.55, "Concrete": 0.55, "PavingSetts": 0.55, "Gravel": 0.9, "Dirt": 1.2, "Mud": 1.5,
               "RiverStones": 1.1, "GrassGround": 1.2, "MeadowLitter": 2.5, "ForestFloor": 3.0}
DECIDUOUS_LITTER = {"lipa", "lipa_stara", "javor", "jasan", "dub", "buk", "habr", "olse", "vrba", "briza", "briza_mlada",
                    "jablon", "hruska", "svestka", "orech"}


def splat_layer_names():
    return [l["name"] for l in json.load(open(TERRAIN_LAYERS_JSON))["layers"]]


def _grid(res):
    n = int(round(2 * SPLAT_HALF / res))
    c = -SPLAT_HALF + (np.arange(n) + 0.5) * res
    GX, GY = np.meshgrid(c, c[::-1])          # row 0 = north (max y)
    return n, GX, GY


def _wobble(n, res, feature_m, seed):
    return (value_noise((n, n), max(2, int(2 * SPLAT_HALF / feature_m)), seed, 3) - 0.5) * 2.0


def _raster_polylines(n, res, polylines, width=0.0):
    """boolean raster (row 0 = north) of polylines (level frame), dilated by width/2."""
    img = Image.new("L", (n, n), 0)
    d = ImageDraw.Draw(img)
    to_px = lambda p: ((p[0] + SPLAT_HALF) / res, (SPLAT_HALF - p[1]) / res)  # noqa: E731
    for pl in polylines:
        pts = [to_px(p) for p in pl]
        if len(pts) >= 2:
            d.line(pts, fill=255, width=max(1, int(round(width / res))))
    return np.asarray(img) > 0


def _raster_polygons(n, res, polys):
    img = Image.new("L", (n, n), 0)
    d = ImageDraw.Draw(img)
    for poly in polys:
        pts = [((p[0] + SPLAT_HALF) / res, (SPLAT_HALF - p[1]) / res) for p in poly]
        if len(pts) >= 3:
            d.polygon(pts, fill=255)
    return np.asarray(img) > 0


def splat_maps(L, terr):
    """terrain layer weights (n, n, 12) u8, macro tint (m, m, 3) u8, grass density (g, g, 3) u8 and the class raster."""
    names = splat_layer_names()
    LI = {nm: i for i, nm in enumerate(names)}
    n, GX, GY = _grid(SPLAT_RES)
    log(f"splat: surface fields on {n} x {n} @ {SPLAT_RES} m")
    fields = surface_fields(L, GX, GY)
    wob = _wobble(n, SPLAT_RES, 1.4, SEED + 301)
    wob_big = _wobble(n, SPLAT_RES, 7.0, SEED + 302)
    best = np.full(GX.shape, -1, np.int16)
    cls = np.full(GX.shape, SURF_ID["grass"], np.uint8)
    for pr, surf, d in fields:
        amp = BOUNDARY_WOBBLE.get(surf, 0.1)
        dd = d + amp * (wob_big if surf == "forest_floor" else wob)
        upd = (dd <= 0) & (pr >= best)
        cls[upd] = SURF_ID[surf]
        best[upd] = pr
    # ---- trees: distance to the nearest tree (forest floor only where trees stand), deciduous crowns (leaf litter)
    from scipy.spatial import cKDTree
    sp = L["trees"]["species"]
    tx = np.array([t["pos"][0] for t in L["trees"]["instances"]])
    ty = np.array([t["pos"][1] for t in L["trees"]["instances"]])
    tcr = np.array([sp[t["species"]]["crown_radius"] * t.get("scale", 1.0) for t in L["trees"]["instances"]])
    tdec = np.array([t["species"] in DECIDUOUS_LITTER for t in L["trees"]["instances"]])
    q = np.column_stack([GX.ravel(), GY.ravel()])
    dtree, itree = cKDTree(np.column_stack([tx, ty])).query(q, k=1)
    dtree = dtree.reshape(n, n)
    itree = itree.reshape(n, n)
    rel = dtree / np.maximum(tcr[itree], 1.0)
    under_dec = tdec[itree] & (rel < 1.05)
    # ---- per-layer masks
    W = np.zeros((n, n, 12), np.float32)
    for surf, lay in SURF_LAYER.items():
        if surf in SURF_ID:
            W[..., LI[lay]] += (cls == SURF_ID[surf])
    grass = W[..., LI["GrassGround"]].copy()
    forest = W[..., LI["ForestFloor"]].copy()
    n_dry = value_noise((n, n), 60, SEED + 303, 4)
    # leaf litter under deciduous crowns, dry patches on the meadows, litter along building and wall bases
    bmask = _raster_polygons(n, SPLAT_RES, [b["footprint_world"] for b in L["buildings"]] +
                             [s["footprint_world"] for s in L["secondary_buildings"] if s.get("footprint_world")])
    walls = [f["polyline"] for f in L["fences_walls_hedges"] if f["type"] in ("garden_wall_rendered_1p8", "concrete_low_wall", "concrete_low_wall_rendered", "concrete_wall_chain_link", "chain_link_on_plinth_1p5m")]
    wmask = _raster_polylines(n, SPLAT_RES, walls, 0.3) | bmask
    dwall = ndimage.distance_transform_edt(~wmask) * SPLAT_RES
    litter = np.clip(1.25 - rel, 0, 1) * under_dec * (0.55 + 0.6 * n_dry)
    litter = np.maximum(litter, np.clip((1.3 - dwall) / 1.0, 0, 1) * (0.4 + 0.5 * n_dry))
    litter = np.maximum(litter, smoothstep_np(0.62, 0.8, n_dry) * 0.7)
    garden = poly_signed_dist(next(s["polygon"] for s in L["terrain"]["stamps"] if s["id"] == "PAD_DUM_TERRACE"), GX, GY) < 0
    litter[garden] *= 0.3
    litter = np.clip(litter, 0, 0.9) * grass
    W[..., LI["GrassGround"]] = grass - litter
    W[..., LI["MeadowLitter"]] += litter
    # forest floor: needles under conifers, leaf litter under broadleaves, meadow in the gaps between the trees
    no_tree = np.clip((dtree - 4.0) / 5.0, 0, 1)
    dec_share = under_dec * (0.6 + 0.4 * n_dry)
    to_litter = forest * np.clip(np.maximum(no_tree * 0.8, dec_share * 0.7), 0, 1)
    W[..., LI["ForestFloor"]] = forest - to_litter
    W[..., LI["MeadowLitter"]] += to_litter
    # ---- soften by layer, normalise
    for nm, s in LAYER_SIGMA.items():
        W[..., LI[nm]] = ndimage.gaussian_filter(W[..., LI[nm]], s, mode="nearest")
    tot = W[..., :len(names)].sum(-1, keepdims=True)
    W[..., :len(names)] /= np.maximum(tot, 1e-6)
    # ---- puddles / wetness (channel 10): ruts and kerbs of the wet asphalt, low spots of yards, tracks, mud
    wet = np.zeros((n, n), np.float32)
    nsm = value_noise((n, n), 180, SEED + 304, 3)
    nbig = value_noise((n, n), 40, SEED + 305, 3)
    for r in L["roads"]:
        dd, s_ = polyline_dist(r["polyline"], GX, GY)
        hw = r["width"] / 2
        ruts = np.maximum(np.exp(-((dd - 0.75) / 0.35) ** 2), np.exp(-((dd - 2.25) / 0.35) ** 2))
        kerb = np.clip((dd - (hw - 0.55)) / 0.35, 0, 1) * (dd < hw + 0.05)
        pud = smoothstep_np(0.5, 0.72, nsm * 0.6 + nbig * 0.55) * np.maximum(ruts * 0.85, kerb)
        wet = np.maximum(wet, pud * (dd < hw + 0.1))
    for t in L["tracks"]:
        if t["id"] in ("TRACK_C", "TRACK_E_RING"):
            dd, _ = polyline_dist(t["polyline"], GX, GY)
            ruts = np.exp(-((dd - 0.8) / 0.3) ** 2)
            wet = np.maximum(wet, ruts * smoothstep_np(0.55, 0.75, nsm * 0.5 + nbig * 0.6))
    Hg = terr.z(GX.ravel(), GY.ravel()).reshape(n, n)
    low = np.clip((ndimage.gaussian_filter(Hg, 8.0 / SPLAT_RES * 0.5) - Hg) / 0.06, 0, 1)
    yard = (W[..., LI["Concrete"]] + W[..., LI["Gravel"]] + W[..., LI["PavingSetts"]]) > 0.5
    wet = np.maximum(wet, yard * np.clip((low - 0.35) * 1.6, 0, 1) * smoothstep_np(0.6, 0.8, nsm * 0.5 + nbig * 0.6))
    wet = np.maximum(wet, W[..., LI["Mud"]] * smoothstep_np(0.5, 0.7, nsm * 0.4 + nbig * 0.7))
    # damp brook banks (darker, glossier, no standing water)
    dwater = ndimage.distance_transform_edt(cls != SURF_ID["water"]) * SPLAT_RES
    wet = np.maximum(wet, np.clip(1 - dwater / 2.5, 0, 1) * 0.35)
    W[..., 10] = ndimage.gaussian_filter(wet, 0.8)
    # 64 levels are plenty (the shader renormalises and sharpens by height); far smaller PNGs
    w8 = np.clip(np.round(W * 63) * 4, 0, 255).astype(np.uint8)
    # ---- macro tint (1 m): large-scale brightness / hue, dry meadow patches, damp banks, worn road lanes
    m = int(round(2 * SPLAT_HALF / 1.0))
    ds = n // m
    Wm = W.reshape(m, ds, m, ds, 12).mean(axis=(1, 3))
    Gm = GX.reshape(m, ds, m, ds).mean(axis=(1, 3))
    Gym = GY.reshape(m, ds, m, ds).mean(axis=(1, 3))
    lowf = value_noise((m, m), 12, SEED + 306, 4)
    midf = value_noise((m, m), 45, SEED + 307, 3)
    tint = np.ones((m, m, 3), np.float32)
    tint *= (0.93 + 0.14 * lowf[..., None]) * (0.96 + 0.08 * midf[..., None])
    g = Wm[..., LI["GrassGround"]] + Wm[..., LI["MeadowLitter"]]
    dry = smoothstep_np(0.5, 0.8, value_noise((m, m), 20, SEED + 308, 4)) * g
    tint = tint * (1 - dry[..., None]) + tint * np.array([1.12, 1.05, 0.82]) * dry[..., None]
    dwm = dwater.reshape(m, ds, m, ds).min(axis=(1, 3))
    damp = np.clip(1 - (dwm - 1.5) / 7.0, 0, 1) * g
    tint = tint * (1 - damp[..., None]) + tint * np.array([0.82, 0.9, 0.8]) * damp[..., None]
    for r in L["roads"]:
        dd, _ = polyline_dist(r["polyline"], Gm, Gym)
        lanes = np.maximum(np.exp(-((dd - 0.75) / 0.5) ** 2), np.exp(-((dd - 2.25) / 0.5) ** 2)) * (dd < r["width"] / 2)
        tint *= (1 - 0.07 * lanes)[..., None]
    # shade under the tree crowns (the instanced trees are not part of the light bake): darker, a little browner
    q1 = np.column_stack([Gm.ravel(), Gym.ravel()])
    dt1, it1 = cKDTree(np.column_stack([tx, ty])).query(q1, k=3)
    shade = np.zeros(len(q1))
    for kk in range(3):
        rr_ = dt1[:, kk] / np.maximum(tcr[it1[:, kk]] * 0.9, 1.0)
        shade = 1 - (1 - shade) * (1 - np.clip(1 - rr_ ** 2, 0, 1) * 0.55)
    shade = shade.reshape(m, m)
    tint *= (1 - 0.42 * shade)[..., None] * np.array([1.0, 0.97, 0.94])[None, None, :] ** shade[..., None]
    macro = np.clip(np.round(tint * 0.5 * 255), 0, 255).astype(np.uint8)
    # ---- grass density (0.5 m): R low clumps + forbs, G tall grass, B flowers
    gd = int(round(2 * SPLAT_HALF / GRASS_RES))
    k = n // gd
    Wg = W.reshape(gd, k, gd, k, 12).mean(axis=(1, 3))
    Xg = GX.reshape(gd, k, gd, k).mean(axis=(1, 3))
    Yg = GY.reshape(gd, k, gd, k).mean(axis=(1, 3))
    clsg = cls[k // 2::k, k // 2::k]
    meadow = smoothstep_np(0.35, 0.8, Wg[..., LI["GrassGround"]] + 0.5 * Wg[..., LI["MeadowLitter"]] + 0.25 * Wg[..., LI["ForestFloor"]])
    hard = np.isin(clsg, [SURF_ID[s] for s in ("asphalt", "gravel", "concrete", "paving", "water", "stone", "dirt", "mud")])
    dhard = ndimage.distance_transform_edt(~hard) * GRASS_RES
    meadow *= np.clip((dhard - 0.3) / 0.4, 0, 1)
    # masks: building footprints, props, bridges, retaining walls, zones (for tall grass), lanes (for tall grass)
    block = _raster_polygons(gd, GRASS_RES, [b["footprint_world"] for b in L["buildings"]] +
                             [s["footprint_world"] for s in L["secondary_buildings"] if s.get("footprint_world")])
    prop_polys = []
    for p in L["props"]:
        x, y = p["position"][:2]
        sx, sy = p.get("size", [1, 1, 1])[:2]
        a = math.radians(p.get("rotation_deg", 0.0))
        ca, sa = math.cos(a), math.sin(a)
        hx, hy = sx / 2 + 0.25, sy / 2 + 0.25
        prop_polys.append([(x + u * ca - v * sa, y + u * sa + v * ca) for u, v in ((-hx, -hy), (hx, -hy), (hx, hy), (-hx, hy))])
    block |= _raster_polygons(gd, GRASS_RES, prop_polys)
    block |= _raster_polylines(gd, GRASS_RES, [b["ends"] for b in L["bridges"]], 6.0)
    block |= _raster_polylines(gd, GRASS_RES, [rw["polyline"] for rw in L["retaining_walls"]], 0.8)
    block = ndimage.binary_dilation(block, iterations=1)
    meadow[block] = 0
    wmask_g = _raster_polylines(gd, GRASS_RES, [f["polyline"] for f in L["fences_walls_hedges"]], 0.3) | block
    dwall_g = ndimage.distance_transform_edt(~wmask_g) * GRASS_RES
    zones = _raster_polygons(gd, GRASS_RES, [z["polygon"] for z in L["capture_zones"]])
    dzone = ndimage.distance_transform_edt(~zones) * GRASS_RES
    lane_pl = []

    def _collect(o):
        if isinstance(o, list) and len(o) >= 2 and all(isinstance(p, list) and len(p) >= 2 and all(isinstance(v, (int, float)) for v in p[:2]) for p in o):
            lane_pl.append([p[:2] for p in o])
        elif isinstance(o, dict):
            for v in o.values():
                _collect(v)
        elif isinstance(o, list):
            for v in o:
                _collect(v)
    _collect(L["lanes"])
    dlane = ndimage.distance_transform_edt(~_raster_polylines(gd, GRASS_RES, lane_pl, 0.5)) * GRASS_RES
    dwater_g = dwater[k // 2::k, k // 2::k]
    soft_d = poly_signed_dist(L["boundary"]["soft_polygon"], Xg, Yg)
    verge = np.clip(1 - (np.minimum(dhard, dwall_g) - 0.4) / 2.6, 0, 1)
    dampg = np.clip(1 - (dwater_g - 1.0) / 7.0, 0, 1)
    patch = smoothstep_np(0.58, 0.78, value_noise((gd, gd), 90, SEED + 309, 3))
    low_d = meadow * (0.85 + 0.15 * value_noise((gd, gd), 70, SEED + 310, 3))
    low_d *= np.where(dzone < 0.5, 0.55, 1.0)           # zone floors: low clumps only, fewer
    tall = meadow * np.clip(0.12 + 0.6 * patch + 0.5 * verge + 0.6 * dampg, 0, 1)
    tall *= np.clip((dlane - 3.0) / 1.5, 0, 1) * np.clip((dzone - 2.0) / 1.5, 0, 1)
    tall *= np.clip((soft_d + 40) / 10, 0, 1)
    tall = np.where(soft_d > 0, meadow * 0.35 * (soft_d < 14), tall)   # forest edge band outside the soft line
    flw = meadow * smoothstep_np(0.55, 0.75, value_noise((gd, gd), 55, SEED + 311, 3)) * (1 - verge * 0.6) * (dzone > 1.0) * (soft_d < 0)
    flw *= 1.0 - np.clip(Wg[..., LI["MeadowLitter"]] * 1.5, 0, 1) * 0.7
    # yards: a little grass along walls and fence plinths only
    yardg = np.isin(clsg, [SURF_ID["gravel"], SURF_ID["concrete"], SURF_ID["paving"]]) & ~block
    edge = yardg & (dwall_g < 0.7)
    low_d = np.where(edge, np.maximum(low_d, 0.35), low_d)
    grass_rgb = np.clip(np.round(np.stack([low_d, tall, flw], -1) * 15) * 17, 0, 255).astype(np.uint8)
    log(f"splat: layers {names}; puddles {float((W[..., 10] > 0.5).mean() * 100):.2f} %; grass cells {int((low_d > 0.05).sum())}")
    return {"weights": w8, "macro": macro, "grass": grass_rgb, "names": names, "n": n, "res": SPLAT_RES, "cls": cls}


def smoothstep_np(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0, 1)
    return t * t * (3 - 2 * t)


# ---- vegetation instances (render only; tree trunk collision stays in build_trees)
TREE_SPECIES_ORDER = ["smrk", "borovice", "briza", "briza_mlada", "lipa", "lipa_stara", "javor", "jasan", "dub", "buk", "habr",
                      "olse", "vrba", "jablon", "hruska", "svestka", "orech"]
SHRUB_KINDS = ["shrub_low", "shrub_mid", "shrub_tall", "hedge_wild"]


def tree_instances(L, terr):
    """render rows of the trees; forest trees outside the soft boundary get up to 1.3x crown radius so the canopy
    closes (visual only; the layout data and the trunk collision stay as they are)."""
    sp = L["trees"]["species"]
    soft = Polygon(L["boundary"]["soft_polygon"]).buffer(2.0)
    rows = []
    kinds = []
    for t in L["trees"]["instances"]:
        s = sp[t["species"]]
        k = t.get("scale", 1.0)
        x, y = t["pos"][0], t["pos"][1]
        crown_k = 1.0 if soft.contains(Point(x, y)) else 1.3
        z = terr.z1(x, y) - 0.1
        seed = (int(hashlib.md5(t["id"].encode()).hexdigest()[:8], 16) % 100000) / 100000.0
        rows.append((x, z, -y, math.radians(t.get("yaw_deg", 0.0)), s["height"] * k, s["crown_radius"] * k * crown_k, s["trunk_radius"] * k, seed))
        kinds.append(TREE_SPECIES_ORDER.index(t["species"]))
    return np.array(rows, np.float32), np.array(kinds, np.uint8)


def _along(pl, step, r, jitter=0.3):
    """points every ~step m along a polyline with jitter; yields (x, y, dir_x, dir_y)."""
    out = []
    for a, b in zip(pl[:-1], pl[1:]):
        a = np.array(a[:2], float)
        b = np.array(b[:2], float)
        L_ = np.linalg.norm(b - a)
        if L_ < 1e-6:
            continue
        d = (b - a) / L_
        m = max(1, int(round(L_ / step)))
        for i in range(m):
            t = (i + 0.5 + (r.random() - 0.5) * jitter) / m
            p = a + (b - a) * t
            out.append((p[0], p[1], d[0], d[1]))
    return out


def shrub_instances(L, terr, cls_raster):
    """shrubs of the vegetation blocks and wild hedgerows (inside their collision cores) + the forest-edge
    understory outside the soft boundary (visual only there: the soft boundary countdown applies)."""
    r = rng(SEED + 401)
    rows, kinds = [], []

    def add(x, y, yaw, h, w, kind):
        z = terr.z1(x, y) - 0.05
        rows.append((x, z, -y, yaw, h, w, 0.0, r.random()))
        kinds.append(SHRUB_KINDS.index(kind))
    for vb in L["vegetation_blocks"]:
        h = vb["height"]
        if "polyline" in vb:
            wd = vb["width"]
            for (x, y, dx, dy) in _along(vb["polyline"], 1.15, r):
                nx, ny = -dy, dx
                for off in ((-0.26, 0.26) if wd < 2.6 else (-0.3, 0.0, 0.3)):
                    o = off * wd + (r.random() - 0.5) * 0.3
                    kind = "shrub_tall" if h >= 2.6 else "shrub_mid"
                    add(x + nx * o, y + ny * o, r.random() * 6.283, h * (0.8 + 0.25 * r.random()), wd * (0.75 + 0.3 * r.random()), kind)
        else:
            P = Polygon(vb["polygon"])
            x0, y0, x1, y1 = P.bounds
            for gx in np.arange(x0 + 0.7, x1, 1.5):
                for gy in np.arange(y0 + 0.7, y1, 1.5):
                    px_, py_ = gx + (r.random() - 0.5) * 0.8, gy + (r.random() - 0.5) * 0.8
                    if P.buffer(-0.3).contains(Point(px_, py_)):
                        add(px_, py_, r.random() * 6.283, h * (0.75 + 0.3 * r.random()), 2.2 + r.random(), "shrub_tall")
    for f in L["fences_walls_hedges"]:
        if f["type"] == "hedgerow_mixed":
            for (x, y, dx, dy) in _along(f["polyline"], 1.0, r):
                nx, ny = -dy, dx
                o = (r.random() - 0.5) * 0.5
                add(x + nx * o, y + ny * o, r.random() * 6.283, f["height"] * (0.85 + 0.25 * r.random()), 1.7 + 0.5 * r.random(), "hedge_wild")
    # forest-edge understory: 2-14 m outside the soft line, off roads / tracks / fields, clear of the barrier line
    soft = Polygon(L["boundary"]["soft_polygon"])
    hard = Polygon(L["boundary"]["hard_polygon"])
    band = soft.buffer(14.0).difference(soft.buffer(2.0))
    deep = soft.buffer(60.0).difference(soft.buffer(14.0))
    bx0, by0, bx1, by1 = soft.buffer(60.0).bounds
    fields = [Polygon(f["polygon"]) for f in L.get("fields", [])]
    n = cls_raster.shape[0]
    cand = poisson_points_xy(bx0, by0, bx1, by1, 2.6, r)
    hard_ring = hard.exterior
    for (px_, py_) in cand:
        pt = Point(px_, py_)
        in_band = band.contains(pt)
        if not in_band:
            # deeper forest: every ~3rd candidate, only inside the data square
            if not (max(abs(px_), abs(py_)) < 174.0 and r.random() < 0.3 and deep.contains(pt)):
                continue
        if abs(hard_ring.distance(pt) - 0.5) < 1.6:
            continue
        i = int((SPLAT_HALF - py_) / SPLAT_RES)
        j = int((px_ + SPLAT_HALF) / SPLAT_RES)
        if 0 <= i < n and 0 <= j < n:
            c = cls_raster[max(0, i - 8):i + 9, max(0, j - 8):j + 9]
            if np.isin(c, [SURF_ID[s] for s in ("asphalt", "gravel", "dirt", "concrete", "paving", "water")]).any():
                continue
        if any(fp.buffer(1.0).contains(pt) for fp in fields):
            continue
        if not in_band and np.isin(cls_raster[max(0, i - 8):i + 9, max(0, j - 8):j + 9], [SURF_ID["grass"]]).mean() > 0.9 and r.random() < 0.7:
            continue   # open meadow outside: keep it mostly clear
        inside_hard = hard.contains(pt)
        u = r.random()
        if inside_hard:
            kind, h = "shrub_low", 0.6 + 0.3 * r.random()       # <= 0.8 m inside the physical boundary
        elif u < 0.45:
            kind, h = "shrub_tall", 1.8 + 1.2 * r.random()
        elif u < 0.85:
            kind, h = "shrub_mid", 1.1 + 0.6 * r.random()
        else:
            kind, h = "shrub_low", 0.6 + 0.4 * r.random()
        add(px_, py_, r.random() * 6.283, h, h * (0.9 + 0.5 * r.random()), kind)
    return np.array(rows, np.float32), np.array(kinds, np.uint8)


def poisson_points_xy(x0, y0, x1, y1, rmin, r):
    """jittered-grid blue noise over a rectangle (deterministic)."""
    cell = rmin
    xs = np.arange(x0, x1, cell)
    ys = np.arange(y0, y1, cell)
    X, Y = np.meshgrid(xs, ys)
    P = np.column_stack([X.ravel(), Y.ravel()]) + r.random((X.size, 2)) * cell * 0.85
    return P


# ================================================================================================
# assembly
# ================================================================================================
def three_xyz(p):
    return [round(float(p[0]), 3), round(float(p[2]), 3), round(float(-p[1]), 3)]


def three_xz(p):
    return [round(float(p[0]), 3), round(float(-p[1]), 3)]


def wrap180(a):
    a = (a + 180.0) % 360.0 - 180.0
    return round(a, 2)


NO_BAKE = {"glass", "water", "chainlink", "mesh_deer", "lamp_emissive", "backdrop", "terrain_outer"}
NO_OCCLUDE = {"glass", "water", "chainlink", "mesh_deer", "backdrop", "terrain_outer", "lamp_emissive", "road_marking"}


def chunk_split(arrs, size=120.0):
    """split an indexed mesh (P, N, UV, C, I) into spatial chunks by triangle centroid."""
    P, N, UV, Cc, I = arrs
    cen = P[I].mean(axis=1)
    ci = np.floor((cen[:, 0] + 176.0) / size).astype(int)
    cj = np.floor((cen[:, 1] + 176.0) / size).astype(int)
    key = ci * 100 + cj
    out = []
    for k in sorted(set(key.tolist())):
        tri = I[key == k]
        used = np.unique(tri.ravel())
        remap = -np.ones(len(P), np.int64)
        remap[used] = np.arange(len(used))
        out.append((k, used, remap[tri]))
    return out


def build_all(args):
    L = json.load(open(C.LAYOUT))
    B = json.load(open(C.BUILDINGS))
    level_hash = C.level_hash(L, B)
    terr = Terrain(L)
    sc = Scene(MATS)
    # ---- content
    bdefs = {b["id"]: b for b in B["buildings"]}
    for bp in L["buildings"]:
        build_main_building(sc, bp, bdefs[bp["id"]], terr)
    log(f"main buildings: {sc.stats}")
    for sb in L["secondary_buildings"]:
        build_secondary(sc, sb, terr)
    for p in L["props"]:
        build_prop(sc, p, terr)
    for f in L["fences_walls_hedges"]:
        build_fence(sc, f, terr)
    for vb in L["vegetation_blocks"]:
        build_vegetation_block(sc, vb, terr)
    build_retaining_walls(sc, L, terr)
    build_bridges(sc, L, terr)
    build_water(sc, L)
    build_poles(sc, L, terr)
    build_boundary(sc, L, terr)
    build_road_markings(sc, L, terr)
    outer_terrain(sc, terr)
    backdrop(sc, L, terr)
    log(f"content built: {sc.stats}; render materials {len(sc.render)}, collision sets {len(sc.col)}")
    return L, B, level_hash, terr, sc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-bake", action="store_true", help="skip the light bake (sky visibility 1, no bounce)")
    ap.add_argument("--rays", type=int, default=16)
    args = ap.parse_args()
    os.makedirs(OUT_ASSETS, exist_ok=True)
    L, B, level_hash, terr, sc = build_all(args)

    # ---- world GLB (tree trunk collision goes into the collision scene, so before the collision GLB)
    gw = GLB()
    mbw = MaterialBank(gw)
    ntrees = build_trees(L, terr, sc)

    # ---- terrain splat control maps, grass density, vegetation instances
    splat = splat_maps(L, terr)
    veg_trees, veg_tree_kinds = tree_instances(L, terr)
    veg_shrubs, veg_shrub_kinds = shrub_instances(L, terr, splat["cls"])
    log(f"vegetation: {len(veg_trees)} trees, {len(veg_shrubs)} shrubs (the backdrop forest is scattered at run time)")

    # ---- surface raster (gameplay: footsteps / impacts)
    SX = terr.X[:-1, :-1] + RES / 2
    SY = terr.Y[:-1, :-1] + RES / 2
    surf = surface_raster(L, SX, SY)          # rows = south -> north (j), cols = west -> east (i)
    log(f"surface raster {surf.shape[1]} x {surf.shape[0]} @ {RES} m")

    # ---- light bake
    sun = sun_dir(L)
    world_arrays = {k: m.arrays() for k, m in sc.render.items()}
    world_arrays = {k: v for k, v in world_arrays.items() if v is not None}
    H = terr.H
    ny, nx = H.shape
    light_terrain = None
    light_world = {}
    if not args.no_bake:
        try:
            import bpy  # noqa: F401  (mathutils comes with the bpy module)
            occ = []
            alb = []
            for k, (P, N, UV, Cc, I) in world_arrays.items():
                if k in NO_OCCLUDE:
                    continue
                tri = P[I]
                occ.append(tri)
                base = srgb_to_linear(np.array(hex_rgb(MATS[k]["color"])))
                a = base[None, :] * srgb_to_linear(Cc[I].mean(axis=1)[:, :3])
                alb.append(a)
            # terrain triangles (0.5 m, whole fine grid) + albedo from the surface classes
            X, Y = terr.X, terr.Y
            cin = terr.cell_in
            cj, ci = np.nonzero(cin)
            p00 = np.stack([X[cj, ci], Y[cj, ci], H[cj, ci]], -1)
            p10 = np.stack([X[cj, ci + 1], Y[cj, ci + 1], H[cj, ci + 1]], -1)
            p11 = np.stack([X[cj + 1, ci + 1], Y[cj + 1, ci + 1], H[cj + 1, ci + 1]], -1)
            p01 = np.stack([X[cj + 1, ci], Y[cj + 1, ci], H[cj + 1, ci]], -1)
            ttri = np.concatenate([np.stack([p00, p10, p11], 1), np.stack([p00, p11, p01], 1)])
            scol = np.array([srgb_to_linear(np.array(hex_rgb(SURF_COL[s]))) for s in SURFACES])
            talb = scol[surf[cj, ci]]
            talb = np.concatenate([talb, talb])
            occ.append(ttri)
            alb.append(talb)
            tris = np.concatenate(occ)
            albedo_t = np.concatenate(alb)
            log(f"bake: BVH over {len(tris)} triangles")
            bk = Baker(tris, albedo_t, sun, rays=args.rays)
            for k, (P, N, UV, Cc, I) in world_arrays.items():
                if k in NO_BAKE:
                    continue
                L4 = bk.bake(P, N, k)
                # hidden vertices (inside another solid): take the mean of the visible vertices of the same material
                hid = L4[:, 0] < 0
                if hid.any():
                    vis = ~hid
                    fill = L4[vis].mean(axis=0) if vis.any() else np.array([0.5, 0, 0, 0])
                    # prefer the average over the vertex's triangles
                    L4[hid] = fill
                light_world[k] = pack_light(L4)
            # terrain vertices (used ones)
            used = np.zeros(H.shape, bool)
            used[:-1, :-1] |= cin
            used[1:, :-1] |= cin
            used[:-1, 1:] |= cin
            used[1:, 1:] |= cin
            vj, vi = np.nonzero(used)
            gy, gx = np.gradient(H, RES)
            Nn = np.column_stack([-gx[vj, vi], -gy[vj, vi], np.ones(len(vj))])
            Nn /= np.linalg.norm(Nn, axis=1, keepdims=True)
            Pt = np.column_stack([X[vj, vi], Y[vj, vi], H[vj, vi]])
            L4 = bk.bake(Pt, Nn, "terrain")
            L4[L4[:, 0] < 0] = (0.4, 0, 0, 0)
            light_terrain = np.zeros((ny, nx, 4), np.uint8)
            light_terrain[..., 3] = 255
            light_terrain[vj, vi] = pack_light(L4)
        except ImportError:
            log("bake: bpy / mathutils not available -> no light bake")
    if light_terrain is None:
        light_terrain = np.zeros((ny, nx, 4), np.uint8)
        light_terrain[..., 3] = 255

    # ---- terrain GLB: fine tiles (render + collision) + outer ring + backdrop
    gt = GLB()
    mbt = MaterialBank(gt)
    mat_ter = mbt.get("terrain")
    tnodes = []
    # fine tiles with quantised normals (smooth across tiles)
    gy, gx = np.gradient(H, RES)
    NN = np.stack([-gx, -gy, np.ones_like(H)], -1)
    NN /= np.linalg.norm(NN, axis=-1, keepdims=True)
    gt.extensionsUsed.add("KHR_mesh_quantization")
    X, Y = terr.X, terr.Y
    tile = int(64 / RES)
    cin = terr.cell_in
    tstats = {"tris": 0, "verts": 0, "tiles": 0}
    from ivglb import BYTE, USHORT, UINT, ELEMENT_ARRAY_BUFFER
    for tj in range(0, ny - 1, tile):
        for ti in range(0, nx - 1, tile):
            j1 = min(tj + tile, ny - 1)
            i1 = min(ti + tile, nx - 1)
            sub = cin[tj:j1, ti:i1]
            if not sub.any():
                continue
            used = np.zeros((j1 - tj + 1, i1 - ti + 1), bool)
            used[:-1, :-1] |= sub
            used[1:, :-1] |= sub
            used[:-1, 1:] |= sub
            used[1:, 1:] |= sub
            vid = -np.ones(used.shape, np.int64)
            vid[used] = np.arange(used.sum())
            jj, ii = np.nonzero(used)
            P = np.column_stack([X[tj + jj, ti + ii], Y[tj + jj, ti + ii], H[tj + jj, ti + ii]])
            Nt = NN[tj + jj, ti + ii]
            cj, ci = np.nonzero(sub)
            a = vid[cj, ci]
            b = vid[cj, ci + 1]
            c = vid[cj + 1, ci + 1]
            d = vid[cj + 1, ci]
            I = np.concatenate([np.column_stack([a, b, c]), np.column_stack([a, c, d])])
            attrs = {"NORMAL": gt.accessor(np.round(to_gltf(Nt) * 127), "VEC3", BYTE, normalized=True),
                     "_IVLIGHT": gt.accessor(light_terrain[tj + jj, ti + ii], "VEC4", UBYTE, normalized=True)}
            m = gt.mesh_positions(f"terrain_{ti}_{tj}", P, I, attrs_extra=attrs, material=mat_ter)
            tnodes.append(gt.add_node({"name": f"terrain_{ti}_{tj}", "mesh": m, "extras": {"iv": {"collision": "terrain"}}}))
            tstats["tris"] += len(I)
            tstats["verts"] += len(P)
            tstats["tiles"] += 1
    log(f"terrain tiles: {tstats}")
    for key in ("terrain_outer", "backdrop"):
        arr = world_arrays.pop(key, None)
        if arr is None:
            continue
        P, N, UV, Cc, I = arr
        from ivglb import MeshBuf
        mbuf = MeshBuf(key)
        mbuf.add(P, N, UV, Cc, I)
        mi = gt.mesh_from_buf(mbuf, mbt.get(key))
        tnodes.append(gt.add_node({"name": key, "mesh": mi, "extras": {"iv": {"kind": key}}}))
    surf_acc = gt.raw_accessor(np.flipud(surf).ravel(), "SCALAR", UBYTE)
    # splat control images (PNG / JPEG in the binary chunk, not referenced by any glTF texture: the game decodes them)
    w8 = splat["weights"]
    wimg = [gt.add_image(png_bytes(w8[..., 4 * k:4 * k + 4], "RGBA"), "image/png") for k in range(3)]
    mimg = gt.add_image(jpg_bytes(splat["macro"], 92), "image/jpeg")
    gimg = gt.add_image(png_bytes(splat["grass"], "RGB"), "image/png")
    names = splat["names"]
    channels = {nm: [i // 4, i % 4] for i, nm in enumerate(names)}
    channels["_puddle"] = [2, 2]
    gt.extras = {"iv": {"level": LEVEL_ID, "levelHash": level_hash,
                        "splat": {"rect": [-SPLAT_HALF, -SPLAT_HALF, SPLAT_HALF, SPLAT_HALF], "res": SPLAT_RES, "size": int(splat["n"]),
                                  "weightImages": wimg, "layers": names, "channels": channels, "rowOrder": "north_to_south",
                                  "macroImage": mimg, "macroRes": 1.0, "macroEncoding": "rgb multiplier * 0.5",
                                  "grassImage": gimg, "grassRes": GRASS_RES, "grassChannels": ["low", "tall", "flowers"],
                                  "layerManifest": "assets/environment/terrain/terrain_layers.json"},
                        "surfaceRaster": {"accessor": surf_acc, "width": int(surf.shape[1]), "height": int(surf.shape[0]),
                                          "x0": terr.x0, "y0": terr.y0, "res": RES, "rowOrder": "north_to_south",
                                          "surfaces": SURFACES},
                        "frame": "glTF / three.js (x, y_up, z) = level (x, z, -y)"}}
    t_path = os.path.join(OUT_ASSETS, "kh_terrain.glb")
    t_size = gt.write(t_path, tnodes)
    log(f"wrote {t_path} ({t_size / 1048576:.2f} MiB)")

    # ---- facades: darker splash zone near the ground (rain splash, dirt), vertex tint
    for key in ("plaster_lime", "plaster_cream", "plaster_ochre", "plaster_greyish", "render_grey", "brick", "brick_sooty", "stone",
                "concrete", "wood_grey"):
        if key not in world_arrays:
            continue
        P, N, UV, Cc, I = world_arrays[key]
        vert = np.abs(N[:, 2]) < 0.3
        hg = P[:, 2] - terr.z(P[:, 0], P[:, 1])
        f = 0.78 + 0.22 * np.clip(hg / 0.7, 0, 1)
        f = np.where(vert & (hg > -0.5) & (hg < 1.2), f, 1.0)
        Cc = Cc.copy()
        Cc[:, :3] *= f[:, None]
        world_arrays[key] = (P, N, UV, Cc, I)

    # ---- world GLB: render meshes by material x chunk + trees
    wnodes = []
    wstats = {"meshes": 0, "tris": 0, "verts": 0}
    for key in sorted(world_arrays):
        P, N, UV, Cc, I = world_arrays[key]
        lt = light_world.get(key)
        mat = mbw.get(key, extra_tex=MATS[key].get("text"))
        for ck, used, tri in chunk_split((P, N, UV, Cc, I)):
            from ivglb import MeshBuf
            mbuf = MeshBuf(f"{key}_{ck}")
            mbuf.add(P[used], N[used], UV[used], Cc[used], tri)
            mi = gw.mesh_from_buf(mbuf, mat, light=None if lt is None else lt[used])
            wnodes.append(gw.add_node({"name": f"{key}_{ck}", "mesh": mi, "extras": {"iv": {"material": key, "lit": lt is not None}}}))
            wstats["meshes"] += 1
            wstats["tris"] += len(tri)
            wstats["verts"] += len(used)
    gw.extras = {"iv": {"level": LEVEL_ID, "levelHash": level_hash, "trees": ntrees, "vegetation": {
        "_comment": "instance tables (three.js frame): float32 rows [x, y, z, yaw rad, height m, crown / width m, trunk radius m, seed 0..1] + u8 kind index; models: assets/environment/vegetation.glb",
        "models": "assets/environment/vegetation.glb",
        "trees": {"rows": gw.raw_accessor(veg_trees, "SCALAR", FLOAT), "kinds": gw.raw_accessor(veg_tree_kinds, "SCALAR", UBYTE), "count": int(len(veg_trees)), "kindNames": TREE_SPECIES_ORDER},
        "shrubs": {"rows": gw.raw_accessor(veg_shrubs, "SCALAR", FLOAT), "kinds": gw.raw_accessor(veg_shrub_kinds, "SCALAR", UBYTE), "count": int(len(veg_shrubs)), "kindNames": SHRUB_KINDS}}}}
    w_path = os.path.join(OUT_ASSETS, "kh_world.glb")
    w_size = gw.write(w_path, wnodes)
    log(f"wrote {w_path} ({w_size / 1048576:.2f} MiB): {wstats}")

    # ---- collision GLB
    gc = GLB()
    cnodes = []
    cstats = {}
    for k in sorted(sc.col):
        a = sc.col[k].arrays()
        if a is None:
            continue
        P, I = a
        cls, surface, nav = k
        m = gc.mesh_positions(f"{cls}|{surface}|{int(nav)}", P, I)
        cnodes.append(gc.add_node({"name": f"{cls}|{surface}|{int(nav)}", "mesh": m,
                                   "extras": {"iv": {"class": cls, "surface": surface, "nav": bool(nav)}}}))
        cstats[f"{cls}|{surface}|{int(nav)}"] = len(I)
    gc.extras = {"iv": {"level": LEVEL_ID, "levelHash": level_hash, "classes": {
        "main": {"movement": True, "bullets": True, "vision": True},
        "move": {"movement": True, "bullets": False, "vision": False},
        "movevis": {"movement": True, "bullets": False, "vision": True}}}}
    c_path = os.path.join(OUT_ASSETS, "kh_collision.glb")
    c_size = gc.write(c_path, cnodes)
    log(f"wrote {c_path} ({c_size / 1048576:.2f} MiB): {sum(cstats.values())} tris in {len(cstats)} sets")

    # ---- level data
    level = level_json(L, terr, level_hash, {"kh_terrain.glb": t_path, "kh_world.glb": w_path, "kh_collision.glb": c_path},
                       {"terrain": tstats, "world": wstats, "collisionTris": int(sum(cstats.values())), "trees": ntrees})
    with open(OUT_LEVEL, "w") as f:
        json.dump(level, f, ensure_ascii=False, indent=1)
        f.write("\n")
    log(f"wrote {OUT_LEVEL}")
    for pth in (t_path, w_path, c_path):
        sz = os.path.getsize(pth)
        log(f"  {os.path.basename(pth)}: {sz / 1048576:.2f} MiB, base64 {sz * 4 / 3 / 1048576:.2f} MiB (limit 15)")


def file_sha(p, n=16):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()[:n]


def armory_for_row(L, terr, sa, row, occupied):
    pts = [np.array(p["pos"][:2]) for p in sa["candidate_points"] if p["row"] == row["row_id"]]
    yaw = next(p["yaw_deg"] for p in sa["candidate_points"] if p["row"] == row["row_id"])
    a = math.radians(yaw)
    f = np.array([-math.sin(a), math.cos(a)])    # facing (CCW from north)
    side = np.array([f[1], -f[0]])
    c = np.mean(pts, axis=0)
    back = max(float(-(p - c) @ f) for p in pts) + 1.6
    best = None
    for off_s in (0.0, 1.5, -1.5, 3.0, -3.0):
        for extra in (0.0, 0.8, 1.6):
            q = c - f * (back + extra) + side * off_s
            if any(np.linalg.norm(q - o) < 3.0 for o in occupied):
                continue
            zs = [terr.z1(q[0] + dx, q[1] + dy) for dx in (-0.6, 0.6) for dy in (-0.6, 0.6)]
            if max(zs) - min(zs) > 0.25:
                continue
            if min(np.linalg.norm(q - p) for p in pts) < 1.3:
                continue
            best = (q, max(zs))
            break
        if best:
            break
    if best is None:
        best = (c - f * back, terr.z1(*(c - f * back)))
    return best


def level_json(L, terr, level_hash, files, stats):
    rules = json.load(open(C.RULES))
    team_ids = [t["id"] for t in rules["teams"]["list"]]
    zones = []
    for z in L["capture_zones"]:
        poly = [three_xz(p) for p in z["polygon"]]
        cx, cy = z["center"]
        rad = max(math.dist((cx, cy), p) for p in z["polygon"])
        zones.append({"id": z["id"], "name": z["name"], "center": [round(cx, 3), round(z["z_min"], 3), round(-cy, 3)],
                      "radius": round(rad, 2), "height": round(z["z_max"] - z["z_min"], 2), "polygon": poly,
                      "yMin": z["z_min"], "yMax": z["z_max"], "marker": three_xyz(z["hud_marker"]), "areaM2": z.get("area_m2")})
    team_spawns = []
    armories = []
    spawn_ok = []
    by_team = {sa["team"]: sa for sa in L["spawn_areas"]}
    for ti, tid in enumerate(team_ids):
        sa = by_team[tid]
        lst = []
        for p in sorted(sa["candidate_points"], key=lambda q: (q["row"], q["rank"], q["id"])):
            x, y, z = p["pos"]
            zg = max(z, terr.z1(x, y))
            lst.append({"id": p["id"], "pos": [round(x, 3), round(zg + 0.02, 3), round(-y, 3)], "yaw": wrap180(p["yaw_deg"]),
                        "row": p["row"], "rank": p["rank"], "zones": p["zones"]})
        team_spawns.append(lst)
        occupied = [np.array(a_["_xy"]) for a_ in armories]
        for row in sa["rows"]:
            q, zg = armory_for_row(L, terr, sa, row, occupied)
            armories.append({"id": f"armory_{row['row_id'].lower()}", "team": ti, "center": [round(float(q[0]), 3), round(float(zg) + 0.01, 3), round(float(-q[1]), 3)],
                             "size": [1.0, 0.62, 0.62], "row": row["row_id"], "_xy": [float(q[0]), float(q[1])]})
            occupied.append(q)
    for a_ in armories:
        a_.pop("_xy", None)
    fb = L["ai_navigation"]["spawn_selection"]["fallback_rows"]
    # design cover points (three frame). normal points away from the obstacle = opposite of the threat direction
    cover = []
    for cp in L["cover_points"]["points"]:
        fx, fy = cp["facing"]
        cover.append({"id": cp["id"], "pos": three_xyz(cp["pos"]), "normal": [round(-fx, 4), 0, round(fy, 4)], "height": cp["height"],
                      "kind": cp["kind"], "peek": cp.get("peek", "none"), "zones": cp.get("zones", [])})
    qa = [{"id": q["id"], "kind": q["kind"], "pos": three_xyz(q["pos"]), "note": q.get("note", "")} for q in L["qa_points"]]
    markers = {
        "spawn": {"pos": [3.0, round(terr.z1(3.0, 2.0) + 0.02, 3), -2.0], "yaw": 53.0},
        "overview": {"pos": [3.0, round(terr.z1(3.0, 2.0) + 0.02, 3), -2.0], "yaw": 53.0, "pitch": -4},
    }
    for q in qa:
        markers[q["id"]] = {"pos": q["pos"], "yaw": 0}
    soft = Polygon(L["boundary"]["soft_polygon"])
    nav_clip = soft.buffer(-1.0, join_style=2)
    fog = L["environment"]["fog"]["map_override_D9"]
    txt = L["boundary"]["player_text_cs"]
    bx0, by0, bx1, by1 = Polygon(L["boundary"]["hard_polygon"]).bounds
    return {
        "_comment": "GENERATED by Tools/level/export_web_level.py from Shared/level/layout.json + buildings.json - do not edit. Frame: three.js (x, y up, z) = level (x, z, -y); yaw = degrees CCW from north (-Z). Schema: Docs/GAMEPLAY_CONTRACTS.md (Úroveň + geometry / boundary / cover extension).",
        "id": LEVEL_ID,
        "displayName": "Kalné Hamry",
        "tag": "pracovní verze (provizorní grafika)",
        "levelHash": level_hash,
        "sources": {"Shared/level/layout.json": file_sha(C.LAYOUT, 64), "Shared/level/buildings.json": file_sha(C.BUILDINGS, 64),
                    "generator": "Tools/level/export_web_level.py"},
        "size": [round(bx1 - bx0, 1), round(by1 - by0, 1)],
        "solids": [],
        "geometry": {
            "terrain": f"{ASSET_DIR_REL}/kh_terrain.glb",
            "render": [f"{ASSET_DIR_REL}/kh_terrain.glb", f"{ASSET_DIR_REL}/kh_world.glb"],
            "collision": f"{ASSET_DIR_REL}/kh_collision.glb",
            "environment": {"terrainLayers": "assets/environment/terrain/terrain_layers.json", "vegetation": "assets/environment/vegetation.glb"},
            "files": {os.path.basename(k): file_sha(v) for k, v in files.items()},
            "navClip": [three_xz(p) for p in list(nav_clip.exterior.coords)[:-1]],
            "stats": stats,
        },
        "environment": {"fog": {"color": fog["color"], "density": fog["density"], "heightDensity": fog["heightDensity"],
                                "heightFalloff": fog["heightFalloff"], "baseHeight": fog.get("baseHeight", 0.0)},
                        "shadowExtent": 40, "shadowMapSize": 2048, "cameraFar": 3000},
        "boundary": {
            "soft": [three_xz(p) for p in L["boundary"]["soft_polygon"]],
            "warning": [three_xz(p) for p in L["boundary"]["warning_polygon"]],
            "hard": [three_xz(p) for p in L["boundary"]["hard_polygon"]],
            "countdownS": 10,
            "text": {"warning": txt["warning"], "leaving": txt["leaving"], "death": txt["death"], "briefing": txt["briefing"]},
        },
        "match": {
            "_comment": "teamSpawns[t] = candidate points of team t (rules.json teams order) with the zones their row is active for (spawn_areas / zone_spawn_rows); the spawn predicate accepts only rows active for the current zone, else the zone's fallback rows (ai_navigation.spawn_selection.fallback_rows).",
            "practiceSpawn": "spawn",
            "teamSpawns": team_spawns,
            "fallbackRows": fb,
            "zones": zones,
            "armories": armories,
        },
        "nav": {"file": "assets/nav/kalne_hamry.json", "external": True, "coverExcludeSolids": []},
        "cover": cover,
        "markers": markers,
        "qaPoints": qa,
        "signs": [],
        "banners": [],
        "dummies": [],
    }


if __name__ == "__main__":
    main()
