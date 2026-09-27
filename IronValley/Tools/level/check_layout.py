#!/usr/bin/env python3
"""
check_layout.py -- automated consistency checker for Shared/level/layout.json + buildings.json (IRON VALLEY,
map "Kalné Hamry").  Exits with status 1 on any FAIL, 0 when everything passes (WARN lines do not fail).

Independent of the generator: it re-derives geometry from the JSON (only the terrain reference implementation
Tools/level/lib/ivterrain.py is shared, because the terrain formula IS the data contract).

Limits (brief + project rules): capsule r 0.35 / h 1.80 (crouch 1.20), eye 1.65, max step 0.40, max slope 45 deg;
doors >= 0.90 x 2.05 clear (brief) and >= 1.10 clear width (project rule for a 0.30 m Recast corridor);
headroom >= 2.10 wherever a character walks; stairs riser 0.16-0.19, tread 0.26-0.30, 2R+T 0.60-0.65,
width >= 0.90 (brief) / >= 1.10 (project), headroom >= 2.10 above every step.

Usage:  python3 Tools/level/check_layout.py [--fast] [--verbose]
        --fast skips the expensive raster/FMM/LOS sections (never use --fast for acceptance).
"""
import argparse
import json
import re
import math
import os
import sys
import time
from collections import defaultdict, deque

import numpy as np
from matplotlib.path import Path
from scipy import ndimage
from shapely.geometry import Polygon, Point, LineString, box as sbox
from shapely.ops import unary_union

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(HERE, "lib"))
import ivterrain as T  # noqa: E402  (terrain contract: reference implementation)

LAYOUT = os.path.join(ROOT, "Shared", "level", "layout.json")
BUILDINGS = os.path.join(ROOT, "Shared", "level", "buildings.json")
RULES = os.path.join(ROOT, "Shared", "config", "rules.json")
MOVEMENT = os.path.join(ROOT, "Web", "src", "data", "movement.json")

CAPSULE_R = 0.35
EYE = 1.65
MAX_STEP = 0.40
MAX_SLOPE = 45.0
DOOR_W_BRIEF, DOOR_W_PROJECT, DOOR_H = 0.90, 1.10, 2.05
HEADROOM = 2.10
RISER = (0.16, 0.19)
TREAD = (0.26, 0.30)
TWO_R_T = (0.60, 0.65)
STAIR_W_BRIEF, STAIR_W_PROJECT = 0.90, 1.10
EPS = 1e-6


class Report:
    def __init__(self, verbose=False):
        self.fails = []
        self.warns = []
        self.passes = []
        self.verbose = verbose
        self.section = ""

    def sec(self, name):
        self.section = name
        print(f"\n== {name}")

    def ok(self, cid, msg):
        self.passes.append((cid, msg))
        print(f"  PASS {cid}: {msg}")

    def fail(self, cid, msg):
        self.fails.append((cid, msg))
        print(f"  FAIL {cid}: {msg}")

    def warn(self, cid, msg):
        self.warns.append((cid, msg))
        print(f"  WARN {cid}: {msg}")

    def check(self, cid, errors, ok_msg, limit=25):
        if errors:
            for e in errors[:limit]:
                self.fail(cid, e)
            if len(errors) > limit:
                self.fail(cid, f"... and {len(errors) - limit} more")
        else:
            self.ok(cid, ok_msg)

    def info(self, msg):
        print(f"       {msg}")


# ================================================================================================
# geometry helpers
# ================================================================================================
def xf(c, rot, p):
    a = math.radians(rot)
    return (c[0] + p[0] * math.cos(a) - p[1] * math.sin(a), c[1] + p[0] * math.sin(a) + p[1] * math.cos(a))


def inv_xf(c, rot, p):
    a = math.radians(rot)
    dx, dy = p[0] - c[0], p[1] - c[1]
    return (dx * math.cos(a) + dy * math.sin(a), -dx * math.sin(a) + dy * math.cos(a))


def dirv(deg):
    a = math.radians(deg)
    return (-math.sin(a), math.cos(a))


def wall_frame(w):
    (sx, sy), (ex, ey) = w["start"], w["end"]
    L = math.hypot(ex - sx, ey - sy)
    ux, uy = (ex - sx) / L, (ey - sy) / L
    return sx, sy, ux, uy, -uy, ux, L


def wall_poly(w, extra_t=0.0):
    sx, sy, ux, uy, nx, ny, L = wall_frame(w)
    t = w["thickness"] / 2.0 + extra_t
    return Polygon([(sx + nx * t, sy + ny * t), (sx + ux * L + nx * t, sy + uy * L + ny * t),
                    (sx + ux * L - nx * t, sy + uy * L - ny * t), (sx - nx * t, sy - ny * t)])


def opening_span(w, o):
    sx, sy, ux, uy, nx, ny, L = wall_frame(w)
    a = o["offset_from_start"]
    b = a + o["width"]
    return a, b, L, (sx + ux * (a + b) / 2, sy + uy * (a + b) / 2), (nx, ny), (ux, uy)


def opening_poly(w, o, extra=0.02):
    sx, sy, ux, uy, nx, ny, L = wall_frame(w)
    a = o["offset_from_start"]
    b = a + o["width"]
    t = w["thickness"] / 2 + extra
    return Polygon([(sx + ux * a + nx * t, sy + uy * a + ny * t), (sx + ux * b + nx * t, sy + uy * b + ny * t),
                    (sx + ux * b - nx * t, sy + uy * b - ny * t), (sx + ux * a - nx * t, sy + uy * a - ny * t)])


def box_poly(center, size, rot):
    L, W = size[0], size[1]
    return Polygon([xf(center, rot, p) for p in ((-L / 2, -W / 2), (L / 2, -W / 2), (L / 2, W / 2), (-L / 2, W / 2))])


def stair_poly(sd):
    ux, uy = sd["direction_vector"]
    nx, ny = -uy, ux
    x0, y0 = sd["start"]
    run = sd["run"]
    hw = sd["width"] / 2.0
    return Polygon([(x0 + nx * hw, y0 + ny * hw), (x0 + ux * run + nx * hw, y0 + uy * run + ny * hw),
                    (x0 + ux * run - nx * hw, y0 + uy * run - ny * hw), (x0 - nx * hw, y0 - ny * hw)])


def leaf_rest_poly(w, o):
    """door leaf at its rest angle, hinged on the frame at the hinge jamb, on the swing side."""
    sx, sy, ux, uy, nx, ny, L = wall_frame(w)
    a = o["offset_from_start"] + o.get("frame_jamb", 0.05)
    b = o["offset_from_start"] + o["width"] - o.get("frame_jamb", 0.05)
    lt = o.get("leaf", {}).get("thickness", 0.05)
    side = 1.0 if o["swing"] == "left" else -1.0
    face = w["thickness"] / 2.0
    ang = math.radians(o.get("open_deg", 90) or 0)
    polys = []
    hinges = []
    if o["type"] == "double_door":
        half = (b - a) / 2
        hinges = [(a, +1, half), (b, -1, half)]
    else:
        if o["hinge"] == "start":
            hinges = [(a, +1, b - a)]
        else:
            hinges = [(b, -1, b - a)]
    for u0, sgn, length in hinges:
        hx = sx + ux * u0 + nx * side * face
        hy = sy + uy * u0 + ny * side * face
        # closed leaf direction = sgn * u; rotate towards the swing side normal by ang
        cx, cy = sgn * ux, sgn * uy
        px, py = nx * side, ny * side
        dx = cx * math.cos(ang) + px * math.sin(ang)
        dy = cy * math.cos(ang) + py * math.sin(ang)
        # thickness offset towards the closed direction side
        ox, oy = cx * lt, cy * lt
        tip = (hx + dx * length, hy + dy * length)
        polys.append(Polygon([(hx, hy), tip, (tip[0] + ox, tip[1] + oy), (hx + ox, hy + oy)]))
    return unary_union(polys)


def is_walk_opening(o):
    """door-like opening a character can pass (open doors, open roller / sliding doors)."""
    if o["type"] in ("door", "double_door"):
        return True
    if o["type"] in ("roller_door", "sliding_door"):
        return bool(o.get("passes", {}).get("movement"))
    return False


def door_sector_poly(w, o, n_arc=12):
    """area swept by every leaf from closed to its rest angle (for swing-vs-stair checks)."""
    sx, sy, ux, uy, nx, ny, L = wall_frame(w)
    a = o["offset_from_start"] + o.get("frame_jamb", 0.05)
    b = o["offset_from_start"] + o["width"] - o.get("frame_jamb", 0.05)
    side = 1.0 if o["swing"] == "left" else -1.0
    face = w["thickness"] / 2.0
    ang = math.radians(o.get("open_deg", 90) or 0)
    hinges = [(a, +1, (b - a) / 2), (b, -1, (b - a) / 2)] if o["type"] == "double_door" else \
        ([(a, +1, b - a)] if o["hinge"] == "start" else [(b, -1, b - a)])
    polys = []
    for u0, sgn, length in hinges:
        hx, hy = sx + ux * u0 + nx * side * face, sy + uy * u0 + ny * side * face
        cx, cy = sgn * ux, sgn * uy
        px, py = nx * side, ny * side
        pts = [(hx, hy)]
        for k in range(n_arc + 1):
            t = ang * k / n_arc
            pts.append((hx + (cx * math.cos(t) + px * math.sin(t)) * length, hy + (cy * math.cos(t) + py * math.sin(t)) * length))
        polys.append(Polygon(pts).buffer(0))
    return unary_union(polys)


def roof_plane_at(rf, x, y):
    """roof plane height at local (x, y), extrapolated beyond the wall rectangle (for drip edges / gutters)."""
    P = rf.get("wall_rect") or rf.get("rect")
    x0, y0 = min(p[0] for p in P), min(p[1] for p in P)
    x1, y1 = max(p[0] for p in P), max(p[1] for p in P)
    tp = math.tan(math.radians(rf["pitch_deg"]))
    if rf["type"] == "gable":
        if rf.get("ridge_axis", "X") == "X":
            return rf["eave_z"] + ((y1 - y0) / 2 - abs(y - (y0 + y1) / 2)) * tp
        return rf["eave_z"] + ((x1 - x0) / 2 - abs(x - (x0 + x1) / 2)) * tp
    if rf["type"] == "hip":
        dy = (y1 - y0) / 2 - abs(y - (y0 + y1) / 2)
        dx = (x1 - x0) / 2 - abs(x - (x0 + x1) / 2)
        ab = rf.get("abuts") or {}
        if ("+X" in ab and x > (x0 + x1) / 2) or ("-X" in ab and x < (x0 + x1) / 2):
            dx = 1e9
        return rf["eave_z"] + min(dy, dx) * tp
    if rf["type"] == "mono":
        d = rf["slope_direction"]
        return {"-X": rf["high_z"] - (x1 - x) * tp, "+X": rf["high_z"] - (x - x0) * tp,
                "-Y": rf["high_z"] - (y1 - y) * tp, "+Y": rf["high_z"] - (y - y0) * tp}[d]
    return None


def sliding_leaf_polys(bd, open_only=True):
    """local polygons of parked sliding-door leaves (outside face, beside the opening)."""
    out = []
    wm = {w["id"]: w for w in bd["walls"]}
    for o in bd["openings"]:
        if o["type"] != "sliding_door" or not o.get("leaf_rest") or (open_only and not o.get("state", {}).get("open")):
            continue
        w = wm[o["wall_id"]]
        lr = o["leaf_rest"]
        sx, sy, ux, uy, nx, ny, Lw = wall_frame(w)
        side = -1.0 if lr["side"] == "right" else 1.0
        off0 = w["thickness"] / 2 + lr["offset_from_face"]
        off1 = off0 + lr["thickness"]
        u0, u1 = lr["u"]
        out.append(Polygon([(sx + ux * u0 + nx * side * off0, sy + uy * u0 + ny * side * off0),
                            (sx + ux * u1 + nx * side * off0, sy + uy * u1 + ny * side * off0),
                            (sx + ux * u1 + nx * side * off1, sy + uy * u1 + ny * side * off1),
                            (sx + ux * u0 + nx * side * off1, sy + uy * u0 + ny * side * off1)]))
    return out


def ramp_param(st, lx, ly):
    """0 at the ramp top edge, 1 at its foot (local coords).  Uses rise_direction_deg when given (the ramp rises towards it),
    else the long axis with the top at the end nearer to the building origin."""
    P = np.array(st["polygon"], float)
    if "rise_direction_deg" in st:
        d = dirv(st["rise_direction_deg"])
        proj = P[:, 0] * d[0] + P[:, 1] * d[1]
        top, foot = proj.max(), proj.min()
        return np.clip((top - (lx * d[0] + ly * d[1])) / (top - foot), 0, 1)
    lx0, lx1 = P[:, 0].min(), P[:, 0].max()
    ly0, ly1 = P[:, 1].min(), P[:, 1].max()
    if (lx1 - lx0) > (ly1 - ly0):
        near = lx0 if abs(lx0) < abs(lx1) else lx1
        far = lx1 if near == lx0 else lx0
        return np.clip((lx - near) / (far - near), 0, 1)
    near = ly0 if abs(ly0) < abs(ly1) else ly1
    far = ly1 if near == ly0 else ly0
    return np.clip((ly - near) / (far - near), 0, 1)


def shoelace(poly):
    return Polygon(poly).area


def poly_mask(poly, X, Y):
    P = np.asarray(poly, float)
    pts = np.column_stack([X.ravel(), Y.ravel()])
    return Path(P).contains_points(pts, radius=1e-9).reshape(X.shape)


def seg_dist(X, Y, a, b):
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    if L2 < 1e-12:
        return np.hypot(X - ax, Y - ay)
    t = np.clip(((X - ax) * dx + (Y - ay) * dy) / L2, 0, 1)
    return np.hypot(X - ax - t * dx, Y - ay - t * dy)


def level_hash(L, B):
    """content hash of the level data (layout without navmesh_validation + buildings), used to detect stale nav bakes."""
    import hashlib
    Lc = {k: v for k, v in L.items() if k != "navmesh_validation"}
    s = json.dumps([Lc, B], sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def bearing(frm, to):
    return math.degrees(math.atan2(to[0] - frm[0], to[1] - frm[1])) % 360


def ang_sep(a, b):
    d = abs(a - b) % 360
    return min(d, 360 - d)


# ================================================================================================
# 0. schema / ids
# ================================================================================================
def check_schema(L, B, rules, rep):
    rep.sec("0. Schema, ids and references")
    errs = []
    for k in ("schema", "meta", "terrain", "water", "roads", "tracks", "paths", "ditches", "bridges", "retaining_walls",
              "fences_walls_hedges", "vegetation_blocks", "buildings", "secondary_buildings", "prop_catalog", "props", "trees",
              "capture_zones", "spawn_areas", "boundary", "environment", "surfaces", "balance", "lanes", "cover_points",
              "chokepoints", "ai_navigation", "performance_budget_browser", "qa_points"):
        if k not in L:
            errs.append(f"layout.json missing top-level key '{k}'")
    if L.get("schema") != "ironvalley.layout/1":
        errs.append(f"layout schema {L.get('schema')}")
    if B.get("schema") != "ironvalley.buildings/1":
        errs.append(f"buildings schema {B.get('schema')}")
    conv = L["meta"].get("axis_conversions", {})
    for k in ("threejs", "unreal"):
        if k not in conv:
            errs.append(f"meta.axis_conversions.{k} missing")
    if "three" not in B.get("conventions", "") or "Unreal" not in B.get("conventions", ""):
        errs.append("buildings.json conventions do not document the three.js / Unreal axis conversions")
    if "0 = +Y" not in B.get("conventions", ""):
        errs.append("buildings.json conventions do not state the stair direction convention (0 = local +Y, CCW)")
    zone_ids = [z["id"] for z in L["capture_zones"]]
    rz = [z["id"] for z in rules["zone"]["locations"]]
    if sorted(zone_ids) != sorted(rz):
        errs.append(f"zone ids {zone_ids} != rules.json {rz}")
    for z in L["capture_zones"]:
        rn = next((r["name"] for r in rules["zone"]["locations"] if r["id"] == z["id"]), None)
        if rn and rn != z["name"]:
            errs.append(f"zone {z['id']} name '{z['name']}' != rules.json '{rn}'")
    teams = [t["id"] for t in rules["teams"]["list"]]
    st = [sa["team"] for sa in L["spawn_areas"]]
    if sorted(st) != sorted(teams):
        errs.append(f"spawn teams {st} != rules.json {teams}")
    ids = defaultdict(int)
    for coll in ("roads", "tracks", "paths", "ditches", "bridges", "retaining_walls", "fences_walls_hedges", "vegetation_blocks",
                 "buildings", "secondary_buildings", "props", "capture_zones", "chokepoints"):
        for e in L[coll]:
            ids[e["id"]] += 1
    for k, n in ids.items():
        if n > 1:
            errs.append(f"duplicate id {k} ({n}x)")
    for p in L["props"]:
        if p["type"] not in L["prop_catalog"]:
            errs.append(f"prop {p['id']} type {p['type']} not in prop_catalog")
    bids = {b["id"] for b in B["buildings"]}
    for b in L["buildings"]:
        if b["id"] not in bids:
            errs.append(f"layout building {b['id']} missing in buildings.json")
    rep.check("C00", errs, f"schema ok; zones {zone_ids} and teams {teams} match rules.json; ids unique; {len(L['props'])} props typed")


# ================================================================================================
# 1. terrain
# ================================================================================================
def check_terrain(L, rep, fast):
    rep.sec("1. Terrain")
    errs = []
    bg = L["terrain"]["base_grid"]
    H = np.asarray(bg["heights"], float)
    ox, oy = bg["origin"]
    n = H.shape
    x1 = ox + bg["spacing"] * (n[1] - 1)
    y1 = oy + bg["spacing"] * (n[0] - 1)
    ext = L["meta"]["extent"]
    if not (ox <= ext[0][0] and oy <= ext[0][1] and x1 >= ext[1][0] and y1 >= ext[1][1]):
        errs.append(f"base grid covers x[{ox},{x1}] y[{oy},{y1}] but map extent is {ext}")
    if not np.all(np.isfinite(H)):
        errs.append("base grid has non-finite heights")
    if list(n) != list(bg["size"])[::-1] and list(n) != list(bg["size"]):
        errs.append(f"base grid size {bg['size']} != heights shape {n}")
    kinds = {"pad", "road", "channel", "ditch", "sunken_lane", "wall"}
    for st in L["terrain"]["stamps"]:
        if st["kind"] not in kinds:
            errs.append(f"stamp {st.get('id')} unknown kind {st['kind']}")
    dn = L["terrain"].get("detail_noise")
    if not dn or not dn.get("octaves"):
        errs.append("terrain.detail_noise missing (terrain would be blob-smooth)")
    rep.check("T01", errs, f"base grid {n[1]}x{n[0]} @ {bg['spacing']} m covers x[{ox},{x1}] y[{oy},{y1}] >= map extent; "
                           f"{len(L['terrain']['stamps'])} stamps of known kinds; detail noise with {len(dn['octaves'])} octaves")
    # vertical steps: every wall stamp and masonry section must carry both face polylines for constrained triangulation
    errs = []
    vs = {v["stamp"]: v for v in L["terrain"].get("vertical_steps", [])}
    for st in L["terrain"]["stamps"]:
        if st["kind"] == "wall":
            v = vs.get(st["id"])
            if not v:
                errs.append(f"wall stamp {st['id']} has no vertical_steps entry (faces for constrained triangulation)")
                continue
            rw = next((r for r in L["retaining_walls"] if r["id"] == st["id"]), None)
            if rw:
                for fk in ("high_face", "low_face"):
                    for p in v[fk]:
                        d = LineString(rw["polyline"]).distance(Point(p[0], p[1]))
                        if abs(d - rw["thickness"] / 2) > 0.02:
                            errs.append(f"{st['id']} {fk} vertex {p[:2]} is {d:.3f} from the wall axis, expected {rw['thickness'] / 2}")
        if st["kind"] in ("channel", "ditch") and st.get("vertical_sections"):
            if not any(k.startswith(st["id"]) for k in vs):
                errs.append(f"{st['id']} has vertical (masonry) sections but no vertical_steps faces")
    rep.check("T02", errs, f"{len(vs)} vertical terrain steps carry both face polylines (generator must insert them as "
                           "constraint edges -- no sawtooth)")
    # micro relief: not blob-smooth
    X, Y = np.meshgrid(np.arange(-170, 170, 1.0), np.arange(-170, 170, 1.0))
    D = T.detail_noise(X, Y, dn)
    open_m = T.detail_mask(X, Y, dn["mask"]) > 0.99
    rms = float(D[open_m].std()) if open_m.any() else 0.0
    if rms < 0.2:
        rep.fail("T03", f"detail relief RMS in open terrain {rms:.2f} m < 0.20 m (blob-smooth)")
    else:
        rep.ok("T03", f"detail relief RMS in open terrain {rms:.2f} m (masked to 0 on pads/roads/zones/spawns/buildings)")
    # reference bake
    rb = L["terrain"].get("reference_bake", {})
    fpath = os.path.join(ROOT, rb.get("file", ""))
    if not rb or not os.path.exists(fpath):
        rep.fail("T04", f"reference bake {rb.get('file')} missing")
    else:
        from PIL import Image
        img = np.asarray(Image.open(fpath)).astype(np.float64)
        z0, z1 = rb["z_min"], rb["z_max"]
        rng = np.random.default_rng(7)
        ny, nx = img.shape
        jj = rng.integers(0, ny, 3000)
        ii = rng.integers(0, nx, 3000)
        xs = -175.0 + ii * rb["resolution"]
        ys = 175.0 - jj * rb["resolution"]      # row 0 = north
        zb = z0 + img[jj, ii] / 65535.0 * (z1 - z0)
        zr = T.height_at(L, xs, ys)
        err = np.abs(zb - zr)
        q = (z1 - z0) / 65535.0
        if err.max() > 0.02:
            rep.fail("T04", f"reference bake differs from the reference implementation by {err.max():.4f} m (> 0.02)")
        else:
            rep.ok("T04", f"reference bake {rb['file']} ({nx}x{ny} @ {rb['resolution']} m) matches the reference implementation "
                          f"within {err.max() * 1000:.1f} mm (16-bit step {q * 1000:.2f} mm) on 3000 samples")


# ================================================================================================
# 2. buildings (local frame)
# ================================================================================================
def level_floor(bd, lid):
    for l in bd["levels"]:
        if l["id"] == lid:
            return l["floor_z"]
    for s in bd["stairs"] + bd["exterior_stairs"]:
        ld = s.get("landing")
        if ld and ld.get("id") == lid:
            return ld["z"]
        if ld and ld.get("level") == lid:
            return ld["z"]
    return None


def check_building(bd, rep):
    bid = bd["id"]
    walls = bd["walls"]
    wmap = {w["id"]: w for w in walls}
    lv = {l["id"]: l for l in bd["levels"]}
    errs = []
    # ---- B01 wall thickness
    for w in walls:
        t = w["thickness"]
        mat = w["material"]
        if w["kind"] == "external":
            lo, hi = (0.20, 0.30) if "sandwich" in mat or "steel" in mat else (0.30, 0.50)
        else:
            if "450" in mat or "loadbearing" in mat:
                lo, hi = 0.25, 0.50
            elif "stud" in mat:
                lo, hi = 0.08, 0.12
            else:
                lo, hi = 0.10, 0.15
        if not (lo - EPS <= t <= hi + EPS):
            errs.append(f"{w['id']} ({w['kind']}, {mat}) thickness {t} outside [{lo}, {hi}]")
    rep.check(f"B01[{bid}]", errs, f"{len(walls)} wall thicknesses realistic (masonry 0.30-0.45 ext, cladding 0.25, partitions "
                                   "0.10-0.15, spine/fire walls 0.30-0.45)")
    # ---- B02 wall boxes do not overlap per level
    errs = []
    for L_ in lv:
        ws = [w for w in walls if w["level"] == L_]
        for i in range(len(ws)):
            for j in range(i + 1, len(ws)):
                a = wall_poly(ws[i]).intersection(wall_poly(ws[j])).area
                if a > 1e-5:
                    errs.append(f"wall overlap {ws[i]['id']} x {ws[j]['id']} = {a:.4f} m2")
    rep.check(f"B02[{bid}]", errs, "wall boxes do not overlap")
    # ---- B03 external = internal + walls, ring filled
    errs = []
    for part in bd["footprint_parts"]:
        er = Polygon(part["external_rect"])
        ir = Polygon(part["interior_rect"])
        ex0, ey0, ex1, ey1 = er.bounds
        ix0, iy0, ix1, iy1 = ir.bounds
        wx, wy = part["walls"]["x"], part["walls"]["y"]
        if abs((ex1 - ex0) - ((ix1 - ix0) + wx[0] + wx[1])) > 0.002:
            errs.append(f"{part['part']}: external width {ex1 - ex0:.3f} != interior {ix1 - ix0:.3f} + walls {wx}")
        if abs((ey1 - ey0) - ((iy1 - iy0) + wy[0] + wy[1])) > 0.002:
            errs.append(f"{part['part']}: external depth {ey1 - ey0:.3f} != interior {iy1 - iy0:.3f} + walls {wy}")
        if abs(ix0 - ex0 - wx[0]) > 0.002 or abs(ex1 - ix1 - wx[1]) > 0.002 or abs(iy0 - ey0 - wy[0]) > 0.002 or abs(ey1 - iy1 - wy[1]) > 0.002:
            errs.append(f"{part['part']}: interior rect not inset by the declared wall thicknesses")
        ws0 = [w for w in walls if w["level"] == "L0" and (w["kind"] == "external" or "fire wall" in w.get("note", ""))]
        ue = unary_union([wall_poly(w) for w in ws0])
        ring = er.difference(ir)
        if ring.area > 0:
            cov = ring.intersection(ue).area / ring.area
            if cov < 0.999:
                errs.append(f"{part['part']}: external walls fill only {cov:.4f} of the ring between external and interior rect")
    ext = unary_union([Polygon(p["external_rect"]) for p in bd["footprint_parts"]])
    fx, fy = bd["footprint_external"]
    bx0, by0, bx1, by1 = ext.bounds
    if abs((bx1 - bx0) - fx) > 0.002 or abs((by1 - by0) - fy) > 0.002:
        errs.append(f"footprint_external {fx} x {fy} != union of parts {bx1 - bx0:.3f} x {by1 - by0:.3f}")
    rep.check(f"B03[{bid}]", errs, f"external {fx} x {fy} m = interior + wall thicknesses for every part; ring fully walled")
    # ---- B04 openings geometry
    errs = []
    for o in bd["openings"]:
        w = wmap[o["wall_id"]]
        a, b, Lw, mid, nrm, u = opening_span(w, o)
        if a < 0.10 - EPS or b > Lw - 0.10 + EPS:
            errs.append(f"{o['id']}: opening [{a:.3f},{b:.3f}] leaves a pier < 0.10 in wall {w['id']} (L {Lw:.3f})")
        top = w.get("base_z", 0) + w["height"]
        if o["head_height"] > top + EPS and not w.get("gable_above"):
            errs.append(f"{o['id']}: head {o['head_height']} above wall top {top}")
        if o["type"] != "vent" and not w.get("gable_above") and o["head_height"] > top - 0.10 + EPS:
            errs.append(f"{o['id']}: lintel < 0.10 m (head {o['head_height']}, wall top {top})")
        for w2 in walls:
            if w2 is w or w2["level"] != w["level"]:
                continue
            sx, sy, ux, uy, nx, ny, L2 = wall_frame(w)
            for end in (w2["start"], w2["end"]):
                px, py = end[0] - sx, end[1] - sy
                along = px * ux + py * uy
                perp = abs(px * nx + py * ny)
                if perp <= w["thickness"] / 2 + 0.002 and a - w2["thickness"] / 2 < along < b + w2["thickness"] / 2:
                    if o["sill_height"] < 2.5:
                        errs.append(f"{o['id']}: wall {w2['id']} abuts inside the opening span")
        for col in bd.get("columns", []):
            sx, sy, ux, uy, nx, ny, L2 = wall_frame(w)
            px, py = col["center"][0] - sx, col["center"][1] - sy
            along = px * ux + py * uy
            perp = abs(px * nx + py * ny)
            half = max(col["size"]) / 2
            if perp <= w["thickness"] / 2 + 0.40 and a - half < along < b + half and o["type"] in ("door", "double_door", "roller_door", "sliding_door"):
                errs.append(f"{o['id']}: column {col['center']} stands in the opening")
    # piers measured to the FACE of every abutting / crossing wall (review P2-PIERS), not only to the end of the wall box
    for o in bd["openings"]:
        w = wmap[o["wall_id"]]
        a, b = o["offset_from_start"], o["offset_from_start"] + o["width"]
        sx, sy, ux, uy, nx, ny, Lw = wall_frame(w)
        wp = wall_poly(w, extra_t=0.003)
        for w2 in walls:
            if w2 is w or w2["level"] != w["level"]:
                continue
            p2 = wall_poly(w2)
            if p2.distance(wp) > 0.003:
                continue
            ux2, uy2 = wall_frame(w2)[2:4]
            if abs(ux * ux2 + uy * uy2) > 0.2:
                continue            # collinear continuation, not an abutting wall
            us = [(q[0] - sx) * ux + (q[1] - sy) * uy for q in list(p2.exterior.coords)[:-1]]
            f0, f1 = min(us), max(us)
            if f1 <= a + EPS:
                pier = a - f1
            elif f0 >= b - EPS:
                pier = f0 - b
            else:
                continue            # wall inside the span: reported above
            if pier < 0.10 - 1e-3 and (o["sill_height"] < 2.5 or o["type"] != "window"):
                errs.append(f"{o['id']}: only {pier:.3f} m of masonry between the opening and the face of abutting wall {w2['id']} (< 0.10)")
    byw = defaultdict(list)
    for o in bd["openings"]:
        byw[o["wall_id"]].append(o)
    for wid, os_ in byw.items():
        for i in range(len(os_)):
            for j in range(i + 1, len(os_)):
                p, q = os_[i], os_[j]
                h = min(p["offset_from_start"] + p["width"], q["offset_from_start"] + q["width"]) - max(p["offset_from_start"], q["offset_from_start"])
                v = min(p["head_height"], q["head_height"]) - max(p["sill_height"], q["sill_height"])
                if h > -0.20 and v > -0.20:
                    errs.append(f"openings {p['id']} / {q['id']} on {wid} overlap or leave < 0.20 m between them")
    rep.check(f"B04[{bid}]", errs, f"{len(bd['openings'])} openings sit in their walls with piers >= 0.10 (to wall ends AND to the faces "
                                   "of abutting walls), lintels >= 0.10, no wall or column inside a door span, >= 0.20 m between openings")
    # ---- B05 doors clear sizes
    errs = []
    nd = 0
    for o in bd["openings"]:
        if o["type"] in ("door", "double_door"):
            nd += 1
            nl = 2 if o["type"] == "double_door" else 1
            lt = o.get("leaf", {}).get("thickness", 0.05)
            cw = o["width"] - 2 * o["frame_jamb"] - nl * lt
            ch = o["head_height"] - o["frame_head"]
            if abs(cw - o["clear_width"]) > 0.006:
                errs.append(f"{o['id']}: clear_width {o['clear_width']} != {o['width']} - 2x{o['frame_jamb']} - {nl}x{lt} = {cw:.3f}")
            if abs(ch - o["clear_height"]) > 0.006:
                errs.append(f"{o['id']}: clear_height {o['clear_height']} != head - frame = {ch:.3f}")
            if o["clear_width"] < DOOR_W_BRIEF - EPS or o["clear_height"] < DOOR_H - EPS:
                errs.append(f"{o['id']}: clear {o['clear_width']} x {o['clear_height']} below the brief minimum 0.90 x 2.05")
            elif o["clear_width"] < DOOR_W_PROJECT - EPS:
                errs.append(f"{o['id']}: clear width {o['clear_width']} < 1.10 (project rule: >= 0.40 m Recast corridor at cs 0.05 / radius 7 cells)")
            if o.get("open_deg") is None or o.get("hinge") is None or o.get("swing") not in ("left", "right"):
                errs.append(f"{o['id']}: hinge/swing/open_deg not fully specified")
        elif o["type"] == "sliding_door":
            nd += 1
            g = o.get("guides", 0.05)
            if abs(o["clear_width"] - (o["width"] - 2 * g)) > 0.006 or abs(o["clear_height"] - (o["head_height"] - 0.05)) > 0.006:
                errs.append(f"{o['id']}: sliding door clear {o['clear_width']} x {o['clear_height']} != width - 2 x guides / head - 0.05")
            op = bool(o.get("state", {}).get("open"))
            if op != bool(o["passes"]["movement"]) or op != bool(o["passes"]["vision"]):
                errs.append(f"{o['id']}: sliding door state.open {op} disagrees with passes {o['passes']}")
            if op and (o["clear_width"] < DOOR_W_PROJECT - EPS or o["clear_height"] < DOOR_H - EPS):
                errs.append(f"{o['id']}: open sliding door clear {o['clear_width']} x {o['clear_height']} below 1.10 x 2.05")
            if not o.get("leaf_rest"):
                errs.append(f"{o['id']}: sliding door without leaf_rest (parked / closed leaf pose)")
        elif o["type"] == "roller_door":
            nd += 1
            oh = o["state"]["open_height"]
            if 0 < oh < HEADROOM:
                errs.append(f"{o['id']}: roller door partly open below 2.10 ({oh}) -- crouch passage")
            if oh >= HEADROOM and (o["clear_width"] < DOOR_W_PROJECT or o["clear_height"] < DOOR_H):
                errs.append(f"{o['id']}: open roller door clear {o['clear_width']} x {o['clear_height']}")
    rep.check(f"B05[{bid}]", errs, f"{nd} doors: clear width/height = structural - frame - leaf, all >= 1.10 x 2.05 m "
                                   "(brief >= 0.90 x 2.05)")
    # ---- B06 leaf rest pose clear
    errs = []
    furn_polys = {f["id"]: (f["level"], box_poly(f["center"], f["size"], f.get("rotation_deg", 0))) for f in bd.get("furniture", [])}
    st_polys = [(s, stair_poly(s)) for s in bd["stairs"] + bd["exterior_stairs"]]
    for o in bd["openings"]:
        if o["type"] not in ("door", "double_door"):
            continue
        w = wmap[o["wall_id"]]
        lp = leaf_rest_poly(w, o)
        for w2 in walls:
            if w2["level"] == w["level"] and w2["id"] != w["id"] and lp.intersection(wall_poly(w2)).area > 1e-4:
                errs.append(f"{o['id']}: leaf rest pose intersects wall {w2['id']}")
        for fid, (fl, fp) in furn_polys.items():
            same = fl == w["level"] or (fl == "exterior" and w["kind"] == "external")
            if same and lp.intersection(fp).area > 1e-4:
                errs.append(f"{o['id']}: leaf rest pose intersects furniture {fid}")
        for s, sp in st_polys:
            lvl_s = s["level_from"] if s["level_from"] != "ground" else "L0"
            if lvl_s == w["level"] and lp.intersection(sp).area > 1e-4:
                errs.append(f"{o['id']}: leaf rest pose intersects stair {s['id']}")
        for ba in bd.get("balustrades", []):
            if ba["level"] == w["level"] and lp.intersection(LineString(ba["polyline"]).buffer(0.03)).area > 1e-5:
                errs.append(f"{o['id']}: leaf rest pose intersects balustrade {ba['id']}")
    # swing sector (closed -> rest) vs stair approach / arrival zones (review P2-DOOR-SWING-STAIRS)
    zones_st = []
    for s in bd["stairs"] + bd["exterior_stairs"]:
        dv = s["direction_vector"]
        nx_, ny_ = -dv[1], dv[0]
        hw = s["width"] / 2
        x0, y0 = s["start"]
        xt, yt = s["top_riser_center"]
        appr = Polygon([(x0 - dv[0] * 1.0 + nx_ * hw, y0 - dv[1] * 1.0 + ny_ * hw), (x0 + nx_ * hw, y0 + ny_ * hw),
                        (x0 - nx_ * hw, y0 - ny_ * hw), (x0 - dv[0] * 1.0 - nx_ * hw, y0 - dv[1] * 1.0 - ny_ * hw)])
        arr = Polygon([(xt + nx_ * hw, yt + ny_ * hw), (xt + dv[0] * 1.0 + nx_ * hw, yt + dv[1] * 1.0 + ny_ * hw),
                       (xt + dv[0] * 1.0 - nx_ * hw, yt + dv[1] * 1.0 - ny_ * hw), (xt - nx_ * hw, yt - ny_ * hw)])
        lf = "L0" if s["level_from"] in ("ground", "Lmid") else s["level_from"]
        if s["level_from"] != "ground":
            zones_st.append((s["id"], "approach", lf, appr))
        zones_st.append((s["id"], "arrival", s["level_to"], arr))
    nsec = 0
    for o in bd["openings"]:
        if o["type"] not in ("door", "double_door"):
            continue
        w = wmap[o["wall_id"]]
        sec_ = door_sector_poly(w, o)
        nsec += 1
        for sid, kind, lvl_, zp in zones_st:
            if lvl_ == w["level"]:
                a_ = sec_.intersection(zp).area
                if a_ > 0.02:
                    errs.append(f"{o['id']}: leaf swing sweeps {a_:.2f} m2 of the 1.0 m {kind} zone of stair {sid}")
        # a leaf at rest must not stand in front of a usable window
        lp = leaf_rest_poly(w, o)
        for o2 in bd["openings"]:
            if o2["type"] != "window" or o2["sill_height"] > 1.5:
                continue
            w2 = wmap[o2["wall_id"]]
            if w2["level"] != w["level"]:
                continue
            fz = opening_poly(w2, o2, extra=0.5)
            if lp.intersection(fz).area > 0.02:
                errs.append(f"{o['id']}: leaf at rest stands in front of window {o2['id']}")
    # parked sliding-door leaves: over solid wall, clear of pilasters, stairs, supports and exterior furniture
    for o in bd["openings"]:
        if o["type"] != "sliding_door" or not o.get("leaf_rest"):
            continue
        w = wmap[o["wall_id"]]
        lr = o["leaf_rest"]
        sx, sy, ux, uy, nx, ny, Lw = wall_frame(w)
        u0, u1 = lr["u"]
        if u0 < -EPS or u1 > Lw + EPS:
            errs.append(f"{o['id']}: parked leaf u {lr['u']} runs past the wall ends (L {Lw:.2f})")
        if o.get("state", {}).get("open"):
            for o2 in bd["openings"]:
                if o2 is o or o2["wall_id"] != w["id"] or o2["sill_height"] >= lr["height"]:
                    continue
                if min(u1, o2["offset_from_start"] + o2["width"]) - max(u0, o2["offset_from_start"]) > 0.02:
                    errs.append(f"{o['id']}: parked leaf covers opening {o2['id']}")
        pil = [pp for pp in bd.get("pilasters", []) if pp["wall"] == w["id"]]
        for pp in pil:
            pu = (pp["x"] - sx) * ux if abs(ux) > 0.5 else (pp["x"] - sy) * uy
            if u0 - pp["width"] / 2 < pu < u1 + pp["width"] / 2 and lr["offset_from_face"] < pp["proud"] + 0.05 - EPS:
                errs.append(f"{o['id']}: parked leaf {lr['offset_from_face']} m off the face hits pilaster at {pp['x']} (proud {pp['proud']})")
        side = -1.0 if lr["side"] == "right" else 1.0
        off = w["thickness"] / 2 + lr["offset_from_face"]
        lpoly = Polygon([(sx + ux * u0 + nx * side * off, sy + uy * u0 + ny * side * off),
                         (sx + ux * u1 + nx * side * off, sy + uy * u1 + ny * side * off),
                         (sx + ux * u1 + nx * side * (off + lr["thickness"]), sy + uy * u1 + ny * side * (off + lr["thickness"])),
                         (sx + ux * u0 + nx * side * (off + lr["thickness"]), sy + uy * u0 + ny * side * (off + lr["thickness"]))])
        for s, sp in st_polys:
            if lpoly.intersection(sp).area > 1e-4:
                errs.append(f"{o['id']}: parked leaf intersects stair {s['id']}")
        for rf in bd["roof"]:
            for su in rf.get("supports", []):
                if lpoly.intersection(box_poly(su["pos"], su["size"], 0)).area > 1e-5:
                    errs.append(f"{o['id']}: parked leaf intersects roof support {su['pos']}")
        for fid, (fl_, fp) in furn_polys.items():
            if fl_ == "exterior" and lpoly.intersection(fp).area > 1e-4:
                errs.append(f"{o['id']}: parked leaf intersects exterior furniture {fid}")
    rep.check(f"B06[{bid}]", errs, f"every door leaf rest pose is clear of walls, furniture, stairs, balustrades and windows; {nsec} swing "
                                   "sectors clear of the 1.0 m stair approach/arrival zones; parked sliding leaves over solid wall, clear "
                                   "of pilasters, stairs, supports and exterior furniture")
    # ---- B07 furniture
    errs = []
    fl = [f for f in bd.get("furniture", []) if f["level"] in lv]
    for f in fl:
        fp = box_poly(f["center"], f["size"], f.get("rotation_deg", 0))
        for w in walls:
            if w["level"] == f["level"] and fp.intersection(wall_poly(w)).area > 1e-4:
                errs.append(f"furniture {f['id']} intersects wall {w['id']}")
        if not any(Polygon(r["polygon"]).buffer(0.01).contains(fp) for r in bd["rooms"] if r["level"] == f["level"]):
            errs.append(f"furniture {f['id']} not inside a room of {f['level']}")
        for o in bd["openings"]:
            if not is_walk_opening(o):
                continue
            w = wmap[o["wall_id"]]
            if w["level"] != f["level"]:
                continue
            a, b, Lw, mid, (nx, ny), (ux, uy) = opening_span(w, o)
            sx, sy = w["start"]
            D = 1.0 + w["thickness"] / 2
            p0 = (sx + ux * a, sy + uy * a)
            p1 = (sx + ux * b, sy + uy * b)
            zone = Polygon([(p0[0] + nx * D, p0[1] + ny * D), (p1[0] + nx * D, p1[1] + ny * D), (p1[0] - nx * D, p1[1] - ny * D),
                            (p0[0] - nx * D, p0[1] - ny * D)])
            if fp.intersection(zone).area > 1e-3:
                errs.append(f"furniture {f['id']} blocks the 1.0 m clear zone of {o['id']}")
    for i in range(len(fl)):
        for j in range(i + 1, len(fl)):
            if fl[i]["level"] == fl[j]["level"]:
                a = box_poly(fl[i]["center"], fl[i]["size"], fl[i].get("rotation_deg", 0))
                b = box_poly(fl[j]["center"], fl[j]["size"], fl[j].get("rotation_deg", 0))
                if a.intersection(b).area > 1e-4:
                    errs.append(f"furniture overlap {fl[i]['id']} x {fl[j]['id']}")
    for ch in bd.get("chimneys", []):
        cp = box_poly(ch["pos"], ch.get("size", [0.3, 0.3]), 0)
        for o in bd["openings"]:
            if cp.intersection(opening_poly(wmap[o["wall_id"]], o, 0.0)).area > 1e-4:
                errs.append(f"chimney {ch['id']} cuts opening {o['id']}")
        # every flue serves a real heat source (review P2-CONSTRUCTION-DATA: a flue without a stove)
        srv = ch.get("serves")
        fsrv = next((f for f in bd.get("furniture", []) if f["id"] == srv), None)
        if ch.get("base_z", 0.0) > 0.3:
            if fsrv is None:
                errs.append(f"chimney {ch['id']} starts at z {ch['base_z']} but serves no furniture (stove/forge) -- flue without a heat source")
            elif box_poly(fsrv["center"], fsrv["size"], fsrv.get("rotation_deg", 0)).distance(cp) > 1.5:
                errs.append(f"chimney {ch['id']} is {box_poly(fsrv['center'], fsrv['size'], 0).distance(cp):.2f} m from the stove {srv} it serves")
        elif srv and fsrv is None:
            errs.append(f"chimney {ch['id']} serves unknown furniture {srv}")
    # tall furniture in front of windows (review P2-WINDOW-FURNITURE): taller than sill + 0.10 within 0.7 m of the window
    for o in bd["openings"]:
        if o["type"] != "window":
            continue
        w = wmap[o["wall_id"]]
        zone = opening_poly(w, o, extra=0.7)
        for f in fl:
            if f["level"] != w["level"] or f["size"][2] <= o["sill_height"] + 0.10:
                continue
            fp = box_poly(f["center"], f["size"], f.get("rotation_deg", 0))
            a_ = fp.intersection(zone).area
            if a_ > 0.01:
                errs.append(f"furniture {f['id']} ({f['size'][2]} m tall) stands within 0.7 m in front of window {o['id']} (sill "
                            f"{o['sill_height']})")
    rep.check(f"B07[{bid}]", errs, f"{len(fl)} furniture boxes inside rooms, clear of walls, of 1.0 m door zones, of each other and of "
                                   "the 0.7 m zone in front of windows (when taller than the sill); chimneys clear of openings, every "
                                   "raised flue serves a stove/forge")
    # ---- B08 construction boxes (piers / sills / lintels)
    errs = []
    for w in walls:
        cbs = w.get("construction_boxes")
        if not cbs:
            errs.append(f"{w['id']}: construction_boxes missing")
            continue
        Lw = math.hypot(w["end"][0] - w["start"][0], w["end"][1] - w["start"][1])
        z0 = w.get("base_z", 0.0)
        z1 = z0 + w["height"]
        area = sum((c["u"][1] - c["u"][0]) * (c["z"][1] - c["z"][0]) for c in cbs)
        holes = sum(o["width"] * (min(o["head_height"], z1) - max(o["sill_height"], z0)) for o in bd["openings"]
                    if o["wall_id"] == w["id"] and o["sill_height"] < z1 - EPS)
        if abs(area - (Lw * (z1 - z0) - holes)) > 1e-3:
            errs.append(f"{w['id']}: construction boxes area {area:.3f} != wall {Lw * (z1 - z0):.3f} - openings {holes:.3f}")
        rects = [sbox(c["u"][0], c["z"][0], c["u"][1], c["z"][1]) for c in cbs]
        for i in range(len(rects)):
            if rects[i].bounds[0] < -EPS or rects[i].bounds[2] > Lw + EPS or rects[i].bounds[1] < z0 - EPS or rects[i].bounds[3] > z1 + EPS:
                errs.append(f"{w['id']}: construction box {cbs[i]} outside the wall")
            for j in range(i + 1, len(rects)):
                if rects[i].intersection(rects[j]).area > 1e-6:
                    errs.append(f"{w['id']}: construction boxes {i} and {j} overlap")
    # gables: openings above the wall box need a gable prism with hole-free construction polygons (review P2-CONSTRUCTION-DATA)
    ngab = 0
    for w in walls:
        top = w.get("base_z", 0.0) + w["height"]
        above = [o for o in bd["openings"] if o["wall_id"] == w["id"] and o["head_height"] > top + EPS]
        g = w.get("gable")
        if above and not g:
            errs.append(f"{w['id']}: openings {[o['id'] for o in above]} rise above the wall box (z {top}) but the wall has no gable prism")
            continue
        if not g:
            continue
        ngab += 1
        gp = Polygon(g["polygon_uz"]).buffer(0)
        gops = [o for o in bd["openings"] if o["id"] in g.get("openings", [])]
        for o in above:
            if o["id"] not in g.get("openings", []):
                errs.append(f"{w['id']}: opening {o['id']} above the wall box is not listed in the gable openings")
        holes = unary_union([sbox(o["offset_from_start"], max(o["sill_height"], top), o["offset_from_start"] + o["width"],
                                  o["head_height"]) for o in gops]) if gops else Polygon()
        pieces = [Polygon(pc).buffer(0) for pc in g["construction_polygons"]]
        area = sum(pc.area for pc in pieces)
        exp = gp.difference(holes).area
        if abs(area - exp) > 2e-3:
            errs.append(f"{w['id']}: gable construction polygons {area:.3f} m2 != gable {gp.area:.3f} - openings = {exp:.3f}")
        for k, pc in enumerate(pieces):
            if list(Polygon(g["construction_polygons"][k]).interiors):
                errs.append(f"{w['id']}: gable construction polygon {k} has holes (no booleans allowed)")
            if pc.difference(gp.buffer(1e-3)).area > 1e-4 or pc.intersection(holes).area > 1e-4:
                errs.append(f"{w['id']}: gable construction polygon {k} leaves the gable or covers an opening")
        for i_ in range(len(pieces)):
            for j_ in range(i_ + 1, len(pieces)):
                if pieces[i_].intersection(pieces[j_]).area > 1e-4:
                    errs.append(f"{w['id']}: gable construction polygons {i_} and {j_} overlap")
        rf = next((r for r in bd["roof"] if r["id"] == g.get("roof")), None)
        if rf is None or abs(g["apex_z"] - rf.get("ridge_z", g["apex_z"])) > 0.01:
            errs.append(f"{w['id']}: gable apex {g['apex_z']} != ridge of roof {g.get('roof')}")
    rep.check(f"B08[{bid}]", errs, f"construction boxes (piers/sills/lintels) exactly tile every wall minus its openings; {ngab} gable "
                                   "prisms tile gable minus gable openings with hole-free polygons up to the ridge")
    # ---- B09 stairs
    errs = []
    info = []
    ceilings = []
    for sl in bd.get("slabs", []):
        ceilings.append((sl["top_z"] - sl["thickness"], Polygon(sl["polygon"]), [Polygon(h["polygon"]) for h in sl.get("openings", [])]))
    tops = [l for l in bd["levels"] if l.get("ceiling_height", 0) > 0]
    top = max(tops, key=lambda l: l["floor_z"])
    top_ext = Polygon(top.get("extent") or unary_union([Polygon(p["interior_rect"]) for p in bd["footprint_parts"]]).envelope.exterior.coords)
    ceilings.append((top["floor_z"] + top["ceiling_height"], top_ext, []))
    for ld in [s.get("landing") for s in bd["stairs"]]:
        if ld and ld.get("level") == "Lmid":
            ceilings.append((ld["z"] - 0.20, Polygon(ld["polygon"]), []))
    for s in bd["stairs"] + bd["exterior_stairs"]:
        R_, T_ = s["riser"], s["tread"]
        if not (RISER[0] - EPS <= R_ <= RISER[1] + EPS):
            errs.append(f"{s['id']}: riser {R_:.4f} outside {RISER}")
        if not (TREAD[0] - EPS <= T_ <= TREAD[1] + EPS):
            errs.append(f"{s['id']}: tread {T_} outside {TREAD}")
        if not (TWO_R_T[0] - EPS <= 2 * R_ + T_ <= TWO_R_T[1] + EPS):
            errs.append(f"{s['id']}: 2R+T {2 * R_ + T_:.4f} outside {TWO_R_T}")
        if s["width"] < STAIR_W_BRIEF - EPS:
            errs.append(f"{s['id']}: width {s['width']} < 0.90 (brief)")
        elif s["width"] < STAIR_W_PROJECT - EPS:
            errs.append(f"{s['id']}: width {s['width']} < 1.10 (project rule)")
        dv = dirv(s["direction_deg"])
        if abs(dv[0] - s["direction_vector"][0]) > 1e-3 or abs(dv[1] - s["direction_vector"][1]) > 1e-3:
            errs.append(f"{s['id']}: direction_vector {s['direction_vector']} != (-sin, cos)({s['direction_deg']}) = {dv}")
        tr = (s["start"][0] + dv[0] * s["run"], s["start"][1] + dv[1] * s["run"])
        if math.hypot(tr[0] - s["top_riser_center"][0], tr[1] - s["top_riser_center"][1]) > 0.01:
            errs.append(f"{s['id']}: top_riser_center {s['top_riser_center']} != start + dir x run {tr}")
        if abs(s["run"] - (s["count"] - 1) * T_) > 0.005 or abs(s["rise"] - s["count"] * R_) > 0.005:
            errs.append(f"{s['id']}: run/rise inconsistent with count")
        if abs(s["z_end"] - s["z_start"] - s["rise"]) > 0.005:
            errs.append(f"{s['id']}: z_end - z_start != rise")
        zt = level_floor(bd, s["level_to"])
        if zt is not None and abs(zt - s["z_end"]) > 0.005:
            errs.append(f"{s['id']}: arrives at z {s['z_end']} but level {s['level_to']} floor is {zt}")
        if s["level_from"] == "ground":
            gl = s["z_start"]
            if gl > -0.05 + EPS:
                errs.append(f"{s['id']}: ground start z {gl} not below the floor")
        else:
            zf = level_floor(bd, s["level_from"])
            if zf is not None and abs(zf - s["z_start"]) > 0.005:
                errs.append(f"{s['id']}: starts at z {s['z_start']} but {s['level_from']} is at {zf}")
        sp = stair_poly(s)
        lvl = s["level_from"] if s["level_from"] in lv else ("L0" if s["level_from"] in ("ground", "Lmid") else None)
        for w in walls:
            if lvl and w["level"] == lvl and sp.intersection(wall_poly(w)).area > 1e-4:
                errs.append(f"{s['id']}: flight footprint intersects wall {w['id']}")
        # headroom above every step (3D): lowest ceiling surface above the nosing across the width
        min_head = 99.0
        if s.get("side") != "rear_exterior" and s["level_from"] != "ground":
            nx, ny = -dv[1], dv[0]
            for k in range(1, s["count"] + 1):
                d = (k - 1) * T_
                z = s["z_start"] + k * R_
                for side in (-0.45, 0.0, 0.45):
                    px = s["start"][0] + dv[0] * (d + 0.02) + nx * side * s["width"]
                    py = s["start"][1] + dv[1] * (d + 0.02) + ny * side * s["width"]
                    pt = Point(px, py)
                    c = 99.0
                    for bottom, P, holes in ceilings:
                        if bottom <= z + 0.01:
                            continue
                        if P.buffer(1e-6).contains(pt) and not any(h.contains(pt) for h in holes):
                            c = min(c, bottom)
                    min_head = min(min_head, c - z)
            if min_head < HEADROOM - EPS:
                errs.append(f"{s['id']}: headroom {min_head:.3f} < 2.10 above a step")
        info.append(f"{s['id']}: {s['count']} x {R_:.4f} / {T_} (2R+T {2 * R_ + T_:.3f}), width {s['width']}, "
                    f"min headroom {'open sky' if min_head > 50 else f'{min_head:.2f}'}")
        if "under_stair" not in s or s["under_stair"].get("treatment") not in ("enclosed", "solid_mass", "filled"):
            errs.append(f"{s['id']}: under_stair treatment missing")
        # exterior flights: headroom under roofs / canopies above them (B09 used to skip exterior stairs)
        if s in bd["exterior_stairs"]:
            nx, ny = -dv[1], dv[0]
            for k in range(1, s["count"] + 1):
                d = (k - 1) * T_
                z = s["z_start"] + k * R_
                for side in (-0.45, 0.0, 0.45):
                    px = s["start"][0] + dv[0] * (d + 0.02) + nx * side * s["width"]
                    py = s["start"][1] + dv[1] * (d + 0.02) + ny * side * s["width"]
                    for rf in bd["roof"]:
                        P = rf.get("rect") or rf["wall_rect"]
                        oh = 0.0 if rf.get("rect") else rf.get("overhang_eave", 0.0)
                        if Polygon(P).buffer(oh, join_style=2).contains(Point(px, py)):
                            zr = roof_plane_at(rf, px, py) - 0.25
                            if zr - z < HEADROOM - EPS:
                                errs.append(f"{s['id']}: headroom {zr - z:.2f} under roof {rf['id']} above step {k} (< 2.10)")
        # nothing structural stands in the flight or in its 1.0 m approach / arrival (review P2-ACCESS-CLUTTER: canopy post)
        hw = s["width"] / 2
        x0_, y0_ = s["start"]
        nx, ny = -dv[1], dv[0]
        L0_, L1_ = -1.0, s["run"] + s["tread"] + 1.0
        clear_zone = Polygon([(x0_ + dv[0] * L0_ + nx * hw, y0_ + dv[1] * L0_ + ny * hw), (x0_ + dv[0] * L1_ + nx * hw, y0_ + dv[1] * L1_ + ny * hw),
                              (x0_ + dv[0] * L1_ - nx * hw, y0_ + dv[1] * L1_ - ny * hw), (x0_ + dv[0] * L0_ - nx * hw, y0_ + dv[1] * L0_ - ny * hw)])
        for rf in bd["roof"]:
            for su in rf.get("supports", []):
                if box_poly(su["pos"], su["size"], 0).intersects(clear_zone):
                    errs.append(f"{s['id']}: roof support {su['pos']} of {rf['id']} stands in the flight or its 1.0 m approach/arrival")
        for col in bd.get("columns", []):
            if box_poly(col["center"], col["size"], 0).intersects(clear_zone):
                errs.append(f"{s['id']}: column {col['center']} stands in the flight or its 1.0 m approach/arrival")
    rep.check(f"B09[{bid}]", errs, f"{len(bd['stairs']) + len(bd['exterior_stairs'])} stairs within riser/tread/2R+T/width/headroom "
                                   "limits; direction_deg (0 = +Y) consistent with top_riser_center; arrive at their levels")
    for i in info:
        rep.info(i)
    # ---- B10 exterior single steps / thresholds
    errs = []
    for st in bd.get("exterior_steps", []):
        if st["type"] == "step" and not (RISER[0] - EPS <= st["riser"] <= RISER[1] + EPS):
            errs.append(f"{st['id']}: single step riser {st['riser']} outside {RISER}")
        if st["type"] == "threshold" and st["riser"] > 0.05 + EPS:
            errs.append(f"{st['id']}: threshold {st['riser']} > 0.05")
        if st["type"] == "ramp" and st.get("slope_pct", 0) > 100 * math.tan(math.radians(MAX_SLOPE)):
            errs.append(f"{st['id']}: ramp {st['slope_pct']} % steeper than 45 deg")
    rep.check(f"B10[{bid}]", errs, "single steps 0.16-0.19, thresholds <= 0.05, ramps < 45 deg")
    # ---- B11 rooms
    errs = []
    for r in bd["rooms"]:
        if r["ceiling_height"] < HEADROOM:
            errs.append(f"{r['id']}: ceiling {r['ceiling_height']} < 2.10")
        rp = Polygon(r["polygon"])
        if not rp.is_valid:
            errs.append(f"{r['id']}: invalid polygon")
        for w in walls:
            if w["level"] == r["level"] and rp.intersection(wall_poly(w)).area > 1e-4:
                errs.append(f"room {r['id']} overlaps wall {w['id']}")
        if r["level"] in lv and lv[r["level"]].get("ceiling_height", 3) + (lv[r['level']]['floor_z']) < 0:
            errs.append(f"{r['id']}: bad level")
        # ceiling derived from geometry (review P2-SKLAD-OFFICE): a slab above the room, or the roof structure directly over it
        fz = lv[r["level"]]["floor_z"] if r["level"] in lv else 0.0
        zc = fz + r["ceiling_height"]
        cover = None
        for sl in bd.get("slabs", []):
            bot = sl["top_z"] - sl["thickness"]
            if bot <= fz + 0.5:
                continue
            if Polygon(sl["polygon"]).intersection(rp).area >= 0.90 * rp.area and (cover is None or bot < cover[1]):
                cover = (sl["id"], bot)
        decl = r.get("ceiling") or {}
        if cover:
            if abs(cover[1] - zc) > 0.05:
                errs.append(f"{r['id']}: declared ceiling z {zc:.2f} but slab {cover[0]} soffit is at {cover[1]:.2f}")
            if decl.get("type") == "slab" and decl.get("slab") != cover[0]:
                errs.append(f"{r['id']}: ceiling references slab {decl.get('slab')} but {cover[0]} covers the room")
        else:
            if decl.get("type") == "slab":
                errs.append(f"{r['id']}: ceiling type slab {decl.get('slab')} but no slab covers the room")
            x0_, y0_, x1_, y1_ = rp.bounds
            zr = []
            for xx in np.arange(x0_ + 0.25, x1_, 0.5):
                for yy in np.arange(y0_ + 0.25, y1_, 0.5):
                    if not rp.contains(Point(xx, yy)):
                        continue
                    zs = [roof_plane_at(rf, xx, yy) for rf in bd["roof"] if Polygon(rf["wall_rect"]).buffer(0.01).contains(Point(xx, yy))]
                    zr.append(min(zs) if zs else None)
            if not zr or any(z_ is None for z_ in zr):
                errs.append(f"{r['id']}: part of the room is covered by neither a slab nor a roof")
            else:
                rmin = min(zr)
                if rmin - zc < -EPS:
                    errs.append(f"{r['id']}: declared ceiling z {zc:.2f} above the roof plane ({rmin:.2f})")
                elif rmin - zc > 1.0:
                    errs.append(f"{r['id']}: declared ceiling z {zc:.2f} but nothing covers it: the roof is {rmin - zc:.2f} m higher and "
                                "there is no slab (open-topped box)")
    rep.check(f"B11[{bid}]", errs, f"{len(bd['rooms'])} rooms: clear height >= 2.10, polygons clear of walls; every declared ceiling is "
                                   "a real slab soffit or the roof structure directly over the room (<= 1.0 m below the roof plane)")
    # ---- B16 gutters hang just below the roof drip edge; downpipes meet them (review P1-GUTTERS)
    errs = []
    rfs = {rf["id"]: rf for rf in bd["roof"]}
    for g in bd.get("gutters", []):
        rf = rfs.get(g["roof"])
        if rf is None:
            errs.append(f"gutter on unknown roof {g['roof']}")
            continue
        for end in (g["from"], g["to"], [(g["from"][0] + g["to"][0]) / 2, (g["from"][1] + g["to"][1]) / 2]):
            drip = roof_plane_at(rf, end[0], end[1])
            if not (drip - 0.10 - EPS <= g["z"] <= drip - 0.0 + EPS):
                errs.append(f"gutter {g['roof']} {g['edge']}: z {g['z']} at {end} is {g['z'] - drip:+.3f} m from the roof plane "
                            f"({drip:.3f}); must hang 0.00-0.10 m below the drip edge")
                break
        dz = g.get("drip_edge_z")
        if dz is not None and abs(dz - roof_plane_at(rf, *g["from"])) > 0.01:
            errs.append(f"gutter {g['roof']} {g['edge']}: drip_edge_z {dz} != roof plane at the edge {roof_plane_at(rf, *g['from']):.3f}")
        P = Polygon(rf.get("rect") or rf["wall_rect"]).buffer(0.0 if rf.get("rect") else rf.get("overhang_eave", 0.0), join_style=2)
        if max(P.exterior.distance(Point(*g["from"])), P.exterior.distance(Point(*g["to"]))) > 0.05:
            errs.append(f"gutter {g['roof']} {g['edge']}: not on the roof's overhang line")
    gl = [(LineString([g["from"], g["to"]]), g) for g in bd.get("gutters", [])]
    for dp in bd.get("downpipes", []):
        cands = [(ln.distance(Point(*dp["pos"])), g) for ln, g in gl]
        cands = [c for c in cands if c[0] <= 0.75]
        if not cands:
            errs.append(f"downpipe {dp['id']} at {dp['pos']} is not under any gutter (> 0.75 m)")
            continue
        if not any(abs(dp["top_z"] - g["z"]) <= 0.05 for _, g in cands):
            errs.append(f"downpipe {dp['id']} top {dp['top_z']} does not meet the gutter it serves ({[g['z'] for _, g in cands]})")
    rep.check(f"B16[{bid}]", errs, f"{len(bd.get('gutters', []))} gutters hang 0-0.10 m below the roof plane at the drip edge (eave_z - "
                                   f"overhang x tan pitch), on the overhang line; {len(bd.get('downpipes', []))} downpipes meet a gutter")
    return {"walls": walls, "wmap": wmap}


GRID_OFF = 0.0137   # raster cell centres never coincide with the (0.025 m-rounded) wall faces


def building_level_raster(bd, level, res=0.05, close_doors=True, pad=1.5):
    """local raster of one level: 0 free, 1 wall/solid.  Doors closed (close_doors) or open."""
    walls = [w for w in bd["walls"] if w["level"] == level]
    ext = unary_union([Polygon(p["external_rect"]) for p in bd["footprint_parts"]])
    x0, y0, x1, y1 = ext.bounds
    xs = np.arange(x0 - pad + GRID_OFF, x1 + pad + 1e-9, res)
    ys = np.arange(y0 - pad + GRID_OFF, y1 + pad + 1e-9, res)
    X, Y = np.meshgrid(xs, ys)
    solid = np.zeros(X.shape, bool)
    for w in walls:
        solid |= poly_mask(list(wall_poly(w, extra_t=0.004).exterior.coords)[:-1], X, Y)
        if not close_doors:
            for o in bd["openings"]:
                if o["wall_id"] != w["id"]:
                    continue
                walk = is_walk_opening(o)
                if walk:
                    solid &= ~poly_mask(list(opening_poly(w, o, 0.03).exterior.coords)[:-1], X, Y)
    return xs, ys, X, Y, solid, ext


def check_rooms_closed_and_reachable(bd, rep):
    bid = bd["id"]
    errs = []
    warns = []
    lvls = [l["id"] for l in bd["levels"] if l.get("ceiling_height", 0) > 0]
    lv_floor = {l["id"]: l["floor_z"] for l in bd["levels"]}
    interior = unary_union([Polygon(p["interior_rect"]) for p in bd["footprint_parts"]])
    for lvl in lvls:
        xs, ys, X, Y, solid, ext = building_level_raster(bd, lvl, close_doors=True)
        res = xs[1] - xs[0]
        inside = np.zeros(X.shape, bool)
        lext = next(l for l in bd["levels"] if l["id"] == lvl).get("extent")
        intr = Polygon(lext) if lext else interior
        for g in (intr.geoms if intr.geom_type == "MultiPolygon" else [intr]):
            inside |= poly_mask(list(g.buffer(-0.001).exterior.coords)[:-1], X, Y)
        blocked = solid.copy()
        # stairs rising from this level block the floor below them (the flight / its enclosed space)
        for s in bd["stairs"]:
            lf = s["level_from"] if s["level_from"] != "Lmid" else "L0"
            if lf == lvl:
                blocked |= poly_mask(list(stair_poly(s).exterior.coords)[:-1], X, Y)
        for ch in bd.get("chimneys", []):
            if ch.get("base_z", 0.0) <= lv_floor.get(lvl, 0.0) + 2.10:      # stacks corbelled out above head height do not block
                blocked |= poly_mask(list(box_poly(ch["pos"], ch.get("size", [0.3, 0.3]), 0).exterior.coords)[:-1], X, Y)
        # slab openings on upper levels are not floor
        for sl in bd.get("slabs", []):
            if sl["level"] == lvl:
                for h in sl.get("openings", []):
                    blocked |= poly_mask(h["polygon"], X, Y)
        for ba in bd.get("balustrades", []):
            if ba["level"] == lvl:
                pl = ba["polyline"]
                for a, b in zip(pl[:-1], pl[1:]):
                    blocked |= seg_dist(X, Y, a, b) <= 0.04
        free = inside & ~blocked
        lab, n = ndimage.label(free)
        rooms = [r for r in bd["rooms"] if r["level"] == lvl]
        voids = [v for v in bd.get("sealed_voids", []) if v["level"] == lvl]
        masks = {r["id"]: poly_mask(r["polygon"], X, Y) for r in rooms}
        vmasks = {v["id"]: poly_mask(v["polygon"], X, Y) for v in voids}
        matched_room = defaultdict(list)
        for k in range(1, n + 1):
            comp = lab == k
            cnt = comp.sum()
            if cnt * res * res < 0.05:
                continue
            best = None
            for rid, m in list(masks.items()) + list(vmasks.items()):
                ov = (comp & m).sum() / cnt
                if ov >= 0.98:
                    best = rid
            if best is None:
                cx, cy = X[comp].mean(), Y[comp].mean()
                errs.append(f"{lvl}: enclosed free region of {cnt * res * res:.2f} m2 around ({cx:.2f},{cy:.2f}) is not inside a single "
                            "room / sealed void (walls do not close the rooms)")
                continue
            matched_room[best].append(cnt * res * res)
        for rid, m in list(masks.items()) + list(vmasks.items()):
            comps = matched_room.get(rid, [])
            if not comps and rid in masks:
                errs.append(f"{lvl}: room {rid} has no enclosed free region (overlapping another room?)")
            if len(comps) > 1 and rid in masks:
                errs.append(f"{lvl}: room {rid} is split into {len(comps)} separate regions by walls")
            if comps and rid in masks:
                rpoly = Polygon(next(r for r in rooms if r["id"] == rid)["polygon"])
                occ = [stair_poly(s) for s in bd["stairs"] if (s["level_from"] if s["level_from"] != "Lmid" else "L0") == lvl]
                occ += [box_poly(ch["pos"], ch.get("size", [0.3, 0.3]), 0) for ch in bd.get("chimneys", [])
                        if ch.get("base_z", 0.0) <= lv_floor.get(lvl, 0.0) + 2.10]
                occ += [Polygon(h["polygon"]) for sl in bd.get("slabs", []) if sl["level"] == lvl for h in sl.get("openings", [])]
                occ += [LineString(ba["polyline"]).buffer(0.04) for ba in bd.get("balustrades", []) if ba["level"] == lvl]
                area = rpoly.difference(unary_union(occ)).area if occ else rpoly.area
                if abs(sum(comps) - area) / area > 0.03:
                    errs.append(f"{lvl}: room {rid} free region {sum(comps):.2f} m2 vs polygon minus stairs/voids {area:.2f} m2")
    rep.check(f"B12[{bid}]", errs, f"walls close into rooms on {lvls}: every enclosed region (doors closed) is exactly one room or "
                                   "a declared sealed void")
    # ---- graph reachability through doors + stairs; capsule raster through open doors
    errs = []
    graph = defaultdict(set)
    rooms = bd["rooms"]
    wmap = {w["id"]: w for w in bd["walls"]}

    def room_at(level, x, y):
        for r in rooms:
            if r["level"] == level and Polygon(r["polygon"]).buffer(0.02).contains(Point(x, y)):
                return r["id"]
        return None
    platforms = {}
    for s in bd["exterior_stairs"]:
        ld = s.get("landing")
        if ld and s["level_to"] != "L0":
            platforms[ld["id"]] = (ld, s)
    for o in bd["openings"]:
        walk = is_walk_opening(o)
        if not walk:
            continue
        w = wmap[o["wall_id"]]
        a, b, Lw, mid, (nx, ny), u = opening_span(w, o)
        d = w["thickness"] / 2 + 0.3
        pa = (mid[0] + nx * d, mid[1] + ny * d)
        pb = (mid[0] - nx * d, mid[1] - ny * d)
        ra = room_at(w["level"], *pa)
        rb = room_at(w["level"], *pb)
        for side, rr, pp in (("a", ra, pa), ("b", rb, pb)):
            pass
        if w["kind"] == "external":
            outside_pt = pb if ra else pa
            node = "EXTERIOR"
            if w["level"] != "L0":
                node = None
                for pid, (ld, s) in platforms.items():
                    if Polygon(ld["polygon"]).buffer(0.05).contains(Point(*outside_pt)):
                        node = "PLATFORM:" + pid
                if node is None:
                    errs.append(f"{o['id']}: upper-floor external door opens onto nothing (no platform/balcony in front)")
                    continue
            ra = ra or node
            rb = rb or node
        if ra is None or rb is None:
            errs.append(f"{o['id']}: door does not connect two spaces ({ra}, {rb})")
            continue
        graph[ra].add((rb, o["id"]))
        graph[rb].add((ra, o["id"]))
    for pid, (ld, s) in platforms.items():
        graph["PLATFORM:" + pid].add(("EXTERIOR", s["id"]))
        graph["EXTERIOR"].add(("PLATFORM:" + pid, s["id"]))
    for s in bd["stairs"]:
        dv = s["direction_vector"]
        bx, by = s["start"][0] - dv[0] * 0.4, s["start"][1] - dv[1] * 0.4
        tx, ty = s["top_riser_center"][0] + dv[0] * 0.4, s["top_riser_center"][1] + dv[1] * 0.4
        lf, lt = s["level_from"], s["level_to"]
        nb = ("LANDING:" + s["from_landing"]) if s.get("from_landing") else room_at(lf, bx, by)
        nt = room_at(lt, tx, ty) if lt in {l["id"] for l in bd["levels"]} else ("LANDING:" + s["landing"]["id"])
        if nb is None or nt is None:
            errs.append(f"{s['id']}: stair ends not in rooms (bottom {nb}, top {nt})")
            continue
        graph[nb].add((nt, s["id"]))
        graph[nt].add((nb, s["id"]))
    seen = {"EXTERIOR"}
    todo = ["EXTERIOR"]
    while todo:
        c = todo.pop()
        for nb_, _ in graph.get(c, ()):
            if nb_ not in seen:
                seen.add(nb_)
                todo.append(nb_)
    for r in rooms:
        if r["id"] not in seen:
            errs.append(f"room {r['id']} unreachable from outside through doors/stairs")
    rep.check(f"B13a[{bid}]", errs, f"all {len(rooms)} rooms reachable from outside (door/stair graph search)")
    # exits of elevated rooms
    errs = []
    upper = [r for r in rooms if r["level"] not in ("L0",)]
    for r in upper:
        ex = {v for _, v in graph[r["id"]]}
        if len(ex) < 2:
            ok_dead = r.get("dead_end_ok")
            wins = [o for o in bd["openings"] if o["type"] == "window" and wmap[o["wall_id"]]["level"] == r["level"] and
                    Polygon(r["polygon"]).buffer(0.6).intersects(wall_poly(wmap[o["wall_id"]])) and
                    Polygon(r["polygon"]).buffer(0.5).intersects(opening_poly(wmap[o["wall_id"]], o))]
            low = [o["id"] for o in wins if o["sill_height"] <= 1.25]
            if not ok_dead or low:
                errs.append(f"elevated room {r['id']} has a single exit {sorted(ex)} (firing windows {low}); needs 2 or dead_end_ok + no low windows")
            else:
                warns.append(f"{r['id']} dead end accepted: {ok_dead}")
    # two independent ways down from every upper level
    for l in bd["levels"]:
        if l["floor_z"] <= 0 or l.get("ceiling_height", 0) <= 0:
            continue
        ways = [s["id"] for s in bd["stairs"] if s["level_to"] == l["id"]] + [s["id"] for s in bd["exterior_stairs"] if s["level_to"] == l["id"]]
        if len(ways) < 2:
            errs.append(f"level {l['id']} has only {len(ways)} way(s) down: {ways}")
    rep.check(f"B13b[{bid}]", errs, "every upper level has >= 2 independent ways down; elevated rooms have >= 2 exits (except declared "
                                    "dead ends without firing windows)")
    for w_ in warns:
        rep.warn(f"B13b[{bid}]", w_)
    # capsule raster connectivity per level with doors open
    errs = []
    for lvl in lvls:
        xs, ys, X, Y, solid, ext = building_level_raster(bd, lvl, close_doors=False, pad=6.0)
        res = xs[1] - xs[0]
        blocked = solid.copy()
        for s in bd["stairs"]:
            lf = s["level_from"] if s["level_from"] != "Lmid" else "L0"
            if lf == lvl:
                blocked |= poly_mask(list(stair_poly(s).exterior.coords)[:-1], X, Y)
        for s in bd["exterior_stairs"]:
            if s["level_to"] != "L0" and lvl == "L0":
                blocked |= poly_mask(list(stair_poly(s).exterior.coords)[:-1], X, Y)
        if lvl == "L0" and bd.get("loading_dock"):
            # dock edge (1.10 m) is not walkable from the yard: model the dock as a separate raised area joined by its stairs
            pass
        for f in bd.get("furniture", []):
            if f["level"] == lvl or (f["level"] == "exterior" and lvl == "L0"):
                blocked |= poly_mask(list(box_poly(f["center"], f["size"], f.get("rotation_deg", 0)).exterior.coords)[:-1], X, Y)
        if lvl == "L0":
            for pl_ in sliding_leaf_polys(bd):
                blocked |= poly_mask(list(pl_.exterior.coords)[:-1], X, Y)
            for rf in bd["roof"]:
                for su in rf.get("supports", []):
                    blocked |= poly_mask(list(box_poly(su["pos"], su["size"], 0).exterior.coords)[:-1], X, Y)
        for ch in bd.get("chimneys", []):
            if ch.get("base_z", 0.0) <= lv_floor.get(lvl, 0.0) + 2.10:
                blocked |= poly_mask(list(box_poly(ch["pos"], ch.get("size", [0.3, 0.3]), 0).exterior.coords)[:-1], X, Y)
        for col in bd.get("columns", []):
            blocked |= poly_mask(list(box_poly(col["center"], col["size"], 0).exterior.coords)[:-1], X, Y)
        for sl in bd.get("slabs", []):
            if sl["level"] == lvl:
                for h in sl.get("openings", []):
                    blocked |= poly_mask(h["polygon"], X, Y)
        for ba in bd.get("balustrades", []):
            if ba["level"] == lvl:
                for a, b in zip(ba["polyline"][:-1], ba["polyline"][1:]):
                    blocked |= seg_dist(X, Y, a, b) <= 0.04
        for v in bd.get("sealed_voids", []):
            if v["level"] == lvl:
                blocked |= poly_mask(v["polygon"], X, Y)
        extp = poly_mask(list(ext.exterior.coords)[:-1], X, Y)
        if lvl != "L0":
            # upper level: outside the footprint is air except platforms / balconies
            air = ~extp
            for s in bd["exterior_stairs"]:
                ld = s.get("landing")
                if ld and ld["level"] == lvl:
                    air &= ~poly_mask(ld["polygon"], X, Y)
            blocked |= air
        free = ~blocked
        dist = ndimage.distance_transform_edt(free) * res
        walk = dist > CAPSULE_R
        lab, n = ndimage.label(walk)
        # seeds: outside ring (L0) or platforms (upper)
        seeds = set()
        if lvl == "L0":
            ring = ~extp & walk
            seeds |= set(np.unique(lab[ring])) - {0}
        comp_ok = set(seeds)
        # stair connections: top/bottom approach points link components across levels -> handled per level by requiring each
        # room to touch a component that contains a door to the exterior or a stair end
        stair_pts = []
        for s in bd["stairs"] + bd["exterior_stairs"]:
            dv = s["direction_vector"]
            if s["level_to"] == lvl:
                stair_pts.append((s["top_riser_center"][0] + dv[0] * 0.5, s["top_riser_center"][1] + dv[1] * 0.5))
            lf = s["level_from"] if s["level_from"] not in ("ground",) else "L0"
            if lf == lvl or (s["level_from"] == "Lmid" and False):
                stair_pts.append((s["start"][0] - dv[0] * 0.5, s["start"][1] - dv[1] * 0.5))
        for (px, py) in stair_pts:
            i = int(round((px - xs[0]) / res))
            j = int(round((py - ys[0]) / res))
            sub = lab[max(0, j - 3):j + 4, max(0, i - 3):i + 4]
            vals = set(np.unique(sub)) - {0}
            if not vals:
                errs.append(f"{lvl}: stair end at ({px:.2f},{py:.2f}) is not reachable by a 0.35 m capsule (approach sealed)")
            if lvl != "L0" or True:
                comp_ok |= vals
        for r in bd["rooms"]:
            if r["level"] != lvl:
                continue
            m = poly_mask(r["polygon"], X, Y) & walk
            vals = set(np.unique(lab[m])) - {0}
            if not vals:
                errs.append(f"{lvl}: room {r['id']} has no floor area wide enough for a 0.35 m capsule")
            elif not (vals & comp_ok):
                errs.append(f"{lvl}: room {r['id']} not connected (capsule r 0.35, doors open) to the exterior or a stair")
    rep.check(f"B13c[{bid}]", errs, "capsule (r 0.35) raster connectivity per level: every room and every stair approach reachable "
                                    "with doors open, furniture placed")
    # ---- B14 under-stair headroom in 3D
    errs = []
    for s in bd["stairs"] + bd["exterior_stairs"]:
        us = s.get("under_stair", {})
        lf = s["level_from"]
        floor_below = s["z_start"] if lf == "ground" else (level_floor(bd, "L0") if lf == "Lmid" else level_floor(bd, lf))
        if lf == "Lmid":
            floor_below = 0.0
        if lf == "ground":
            floor_below = s["z_start"]
        dv = s["direction_vector"]
        nx, ny = -dv[1], dv[0]
        waist = s.get("waist", 0.18)
        low_pts = []
        for d in np.arange(0.05, s["run"] + s["tread"], 0.10):
            zn = s["z_start"] + s["riser"] + d * s["riser"] / s["tread"]
            soffit = zn - waist / math.cos(math.atan2(s["riser"], s["tread"]))
            clear = soffit - floor_below
            if 0.05 < clear < HEADROOM:
                for side in np.linspace(-0.45, 0.45, 5):
                    low_pts.append((s["start"][0] + dv[0] * d + nx * side * s["width"], s["start"][1] + dv[1] * d + ny * side * s["width"]))
        ld = s.get("landing")
        if ld and ld.get("level") == "Lmid":
            clear = ld["z"] - 0.20 - floor_below
            if clear < HEADROOM:
                P = Polygon(ld["polygon"])
                x0_, y0_, x1_, y1_ = P.bounds
                for x in np.linspace(x0_ + 0.05, x1_ - 0.05, 6):
                    for y in np.linspace(y0_ + 0.05, y1_ - 0.05, 6):
                        low_pts.append((x, y))
        if not low_pts:
            continue
        t = us.get("treatment")
        if t == "solid_mass":
            continue
        if t == "filled":
            fills = [f for f in bd.get("furniture", []) if f["id"] in us.get("by", [])]
            fp = unary_union([box_poly(f["center"], f["size"], f.get("rotation_deg", 0)) for f in fills]) if fills else Polygon()
            bad = [p for p in low_pts if not fp.buffer(0.01).contains(Point(*p))]
            if bad:
                errs.append(f"{s['id']}: {len(bad)} low-headroom points under the flight not covered by its fill {us.get('by')}")
            continue
        if t == "enclosed":
            lvl = "L0"
            xs, ys, X, Y, solid, ext = building_level_raster(bd, lvl, close_doors=False, pad=2.0)
            res = xs[1] - xs[0]
            blocked = solid.copy()
            for ss in bd["stairs"]:
                lf2 = ss["level_from"] if ss["level_from"] != "Lmid" else "L0"
                if lf2 == lvl:
                    # the flight itself only blocks where its soffit is below knee height (it meets the floor)
                    pass
            for ba in bd.get("balustrades", []):
                if ba["level"] == lvl:
                    for a, b in zip(ba["polyline"][:-1], ba["polyline"][1:]):
                        blocked |= seg_dist(X, Y, a, b) <= 0.04
            # cells where any flight's soffit is < 0.30 above the floor are solid (flight meets the floor)
            for ss in bd["stairs"]:
                if ss["level_from"] not in ("L0", "Lmid"):
                    continue
                dv2 = ss["direction_vector"]
                sp = stair_poly(ss)
                m = poly_mask(list(sp.exterior.coords)[:-1], X, Y)
                dd = (X - ss["start"][0]) * dv2[0] + (Y - ss["start"][1]) * dv2[1]
                zn = ss["z_start"] + ss["riser"] + dd * ss["riser"] / ss["tread"]
                soffit = zn - ss.get("waist", 0.18) / math.cos(math.atan2(ss["riser"], ss["tread"]))
                blocked |= m & (soffit < 0.30)
            free = ~blocked
            dist = ndimage.distance_transform_edt(free) * res
            reach = dist > 0.20        # even a crouching/sliding capsule narrower than the real one
            lab, n = ndimage.label(reach)
            extp = poly_mask(list(ext.exterior.coords)[:-1], X, Y)
            outside = set(np.unique(lab[~extp & reach])) - {0}
            for p in low_pts:
                i = int(round((p[0] - xs[0]) / res))
                j = int(round((p[1] - ys[0]) / res))
                if 0 <= j < lab.shape[0] and 0 <= i < lab.shape[1] and lab[j, i] in outside:
                    errs.append(f"{s['id']}: low-headroom space under the flight at ({p[0]:.2f},{p[1]:.2f}) is reachable from the rooms "
                                "(crouch nook) -- must be enclosed")
                    break
            continue
        errs.append(f"{s['id']}: low headroom below the flight but no valid under_stair treatment")
    rep.check(f"B14[{bid}]", errs, "every space below stairs/landings with headroom < 2.10 is enclosed, solid or filled (3D check, "
                                   "no crouch-only nooks)")


# ================================================================================================
# 3. layout: placement, overlaps, terrain contact
# ================================================================================================
def check_placement(L, B, H_at, rep):
    rep.sec("3. Placement, overlaps, terrain contact")
    bdefs = {b["id"]: b for b in B["buildings"]}
    errs = []
    fps = []
    for b in L["buildings"]:
        bd = bdefs[b["id"]]
        c, rot = b["position"][:2], b["rotation_deg"]
        ext = unary_union([Polygon(p["external_rect"]) for p in bd["footprint_parts"]])
        wp = Polygon([xf(c, rot, p) for p in list(ext.exterior.coords)[:-1]])
        lp = Polygon(b["footprint_world"])
        dmax = max(max(lp.exterior.distance(Point(p)) for p in list(wp.exterior.coords)),
                   max(wp.exterior.distance(Point(p)) for p in list(lp.exterior.coords)))
        if dmax > 0.011:
            errs.append(f"{b['id']}: footprint_world differs from buildings.json footprint placed at {c} rot {rot}")
        if abs(b["footprint"][0] - bd["footprint_external"][0]) > 0.001 or abs(b["footprint"][1] - bd["footprint_external"][1]) > 0.001:
            errs.append(f"{b['id']}: layout footprint {b['footprint']} != buildings.json {bd['footprint_external']}")
        fps.append((b["id"], wp, None))
    for sb in L["secondary_buildings"]:
        fps.append((sb["id"], Polygon(sb["footprint_world"]), sb.get("embedded_in")))
    for i in range(len(fps)):
        for j in range(i + 1, len(fps)):
            a = fps[i][1].intersection(fps[j][1]).area
            if a > 0.01:
                errs.append(f"buildings overlap: {fps[i][0]} x {fps[j][0]} ({a:.2f} m2)")
    roads = []
    for rd in L["roads"] + L["tracks"]:
        w = rd["width"] + 2 * rd.get("shoulders", {}).get("width", 0.0)
        roads.append((rd["id"], LineString([p[:2] for p in rd["polyline"]]).buffer(w / 2, cap_style=2)))
    for bid_, fp, emb in fps:
        for rid, rp in roads:
            a = fp.intersection(rp).area
            if a > 0.01:
                errs.append(f"building {bid_} overlaps road/track {rid} ({a:.2f} m2)")
    for rw in L["retaining_walls"]:
        segs = rw.get("segments") or [[k, k + 1] for k in range(len(rw["polyline"]) - 1)]
        rwp = unary_union([LineString([rw["polyline"][a], rw["polyline"][b]]).buffer(rw["thickness"] / 2, cap_style=2) for a, b in segs])
        for bid_, fp, emb in fps:
            if emb == rw["id"]:
                continue
            if fp.intersection(rwp).area > 0.01:
                errs.append(f"building {bid_} overlaps retaining wall {rw['id']}")
    for p in L["props"]:
        pp = box_poly(p["position"][:2], p["size"], p["rotation_deg"])
        for bid_, fp, emb in fps:
            if pp.intersection(fp).area > 0.01:
                errs.append(f"prop {p['id']} ({p['type']}) intersects building {bid_}")
    rep.check("L01", errs, f"{len(fps)} buildings (3 main + {len(L['secondary_buildings'])} secondary) do not overlap each other, "
                           "roads/tracks, retaining walls or props")
    # secondary buildings are non-enterable and flagged, no fake doors
    errs = []
    for sb in L["secondary_buildings"]:
        if sb.get("enterable") and not sb["type"].startswith("bus_shelter"):
            errs.append(f"{sb['id']} flagged enterable but has no interior data")
        if not sb.get("enterable") and not sb.get("reads_closed_by"):
            errs.append(f"{sb['id']}: non-enterable building without 'reads_closed_by' (must read closed: no fake open doors)")
    for b in L["buildings"]:
        if not b.get("enterable"):
            errs.append(f"main building {b['id']} not enterable")
    types = {b["type"] for b in L["buildings"]}
    if not {"dilna", "mensi_sklad", "obytny_dum"} <= types:
        errs.append(f"main building types {types} do not cover dílna / menší sklad / obytný dům")
    rep.check("L02", errs, "3 distinct main types (dílna, menší sklad, obytný dům) all fully enterable; every secondary building "
                           "is flagged enterable:false and reads closed (no fake doors), except the open bus shelter")
    # terrain contact at doors and building aprons
    errs = []
    for b in L["buildings"]:
        bd = bdefs[b["id"]]
        c, rot, zf = b["position"][:2], b["rotation_deg"], b["position"][2]
        wmap = {w["id"]: w for w in bd["walls"]}
        surfaces = []
        for s in bd["exterior_stairs"]:
            if s.get("landing") and s["level_to"] == "L0":
                surfaces.append((Polygon(s["landing"]["polygon"]), s["landing"]["z"], s["id"]))
        if bd.get("loading_dock"):
            surfaces.append((Polygon(bd["loading_dock"]["polygon"]), bd["loading_dock"]["top_z"], "dock"))
        steps = []
        for st in bd.get("exterior_steps", []):
            if st["type"] == "step":
                surfaces.append((Polygon(st["polygon"]), 0.0, st["id"]))
                steps.append(st)
            if st.get("apron"):
                surfaces.append((Polygon(st["apron"]["polygon"]), st["apron"]["z"], st["id"] + "_apron"))
        for o in bd["openings"]:
            walk = is_walk_opening(o)
            w = wmap[o["wall_id"]]
            if not walk or w["kind"] != "external" or w["level"] != "L0":
                continue
            a, bb, Lw, mid, (nx, ny), u = opening_span(w, o)
            pl = (mid[0] - nx * (w["thickness"] / 2 + 0.25), mid[1] - ny * (w["thickness"] / 2 + 0.25))
            pf = (mid[0] - nx * (w["thickness"] / 2 + 1.2), mid[1] - ny * (w["thickness"] / 2 + 1.2))
            pin = (mid[0] + nx * (w["thickness"] / 2 + 0.25), mid[1] + ny * (w["thickness"] / 2 + 0.25))
            rin = [r for r in bd["rooms"] if r["level"] == "L0" and Polygon(r["polygon"]).buffer(0.02).contains(Point(*pin))]
            if not rin:
                pl, pf, pin = pin, (mid[0] + nx * (w["thickness"] / 2 + 1.2), mid[1] + ny * (w["thickness"] / 2 + 1.2)), pl
            if any(Polygon(r["polygon"]).buffer(0.02).contains(Point(*pl)) for r in bd["rooms"] if r["level"] == "L0"):
                continue            # the "external" wall separates two rooms here (house -> wing): an internal doorway
            zs = None
            for P, z, sid in surfaces:
                if P.buffer(0.02).contains(Point(*pl)):
                    zs = z
            if zs is None:
                pw = xf(c, rot, pl)
                zs = float(H_at(pw[0], pw[1])) - zf
                pw2 = xf(c, rot, pf)
                zs2 = float(H_at(pw2[0], pw2[1])) - zf
                if abs(zs2 - zs) > 0.12:
                    errs.append(f"{b['id']}.{o['id']}: terrain not flat in front of the door ({zs:.2f} -> {zs2:.2f} over 1 m)")
            if zs > 0.02:
                errs.append(f"{b['id']}.{o['id']}: ground outside is {zs:.3f} above the floor (water would run in)")
            if -zs > RISER[1] + 0.02:
                errs.append(f"{b['id']}.{o['id']}: ground outside is {-zs:.3f} below the floor with no declared step/stair/landing")
            if 0.05 < -zs < RISER[0] - 0.02:
                errs.append(f"{b['id']}.{o['id']}: {-zs:.3f} step at the door is below the 0.16 riser minimum")
        # entrance step slabs: top flush with the floor, exactly one declared riser down to the ground beyond them
        for st in steps:
            P = Polygon(st["polygon"])
            cx, cy = P.centroid.x, P.centroid.y
            best = None
            for w in bd["walls"]:
                if w["kind"] != "external" or w["level"] != "L0":
                    continue
                d = wall_poly(w).distance(P)
                if best is None or d < best[0]:
                    best = (d, w)
            w = best[1]
            sx, sy, ux, uy, nx, ny, Lw = wall_frame(w)
            px, py = cx - nx * 0.6, cy - ny * 0.6       # 0.6 m further out (away from the building)
            pw = xf(c, rot, (px, py))
            zg = float(H_at(pw[0], pw[1])) - zf
            if abs(-zg - st["riser"]) > 0.03:
                errs.append(f"{b['id']}.{st['id']}: ground beyond the entrance step is {-zg:.3f} below the floor, declared riser {st['riser']}")
    rep.check("L03", errs, "every external ground-floor door meets flat ground, a landing, a step or the dock at <= one riser "
                           "(0.16-0.19) below the floor, never above it")
    errs = []
    for sb in L["secondary_buildings"]:
        if sb.get("embedded_in"):
            continue
        zc = float(H_at(*sb["position"][:2]))
        if abs(zc - sb["position"][2]) > 0.15:
            errs.append(f"{sb['id']}: z {sb['position'][2]} vs terrain {zc:.2f}")
    for p in L["props"]:
        zc = float(H_at(*p["position"][:2]))
        if abs(zc - p["position"][2]) > 0.15 and p["position"][2] < zc:
            errs.append(f"prop {p['id']}: z {p['position'][2]} is {zc - p['position'][2]:.2f} below the terrain (sunk)")
        if p["position"][2] - zc > 0.25:
            errs.append(f"prop {p['id']}: z {p['position'][2]} floats {p['position'][2] - zc:.2f} above the terrain")
    rep.check("L04", errs, f"{len(L['secondary_buildings'])} secondary buildings and {len(L['props'])} props sit on the terrain "
                           "(|dz| <= 0.15 m at their centre; yard props on their pads)")


# ================================================================================================
# 4. walk raster (independent) + zones + spawns + balance + routes
# ================================================================================================
class Walk:
    def __init__(self, L, B, res=0.25):
        t0 = time.time()
        self.res = res
        xs = np.arange(-175.0, 175.0 + 1e-9, res)
        self.xs = xs
        self.X, self.Y = np.meshgrid(xs, xs)
        X, Y = self.X, self.Y
        H = T.heightfield(L, res)[2]
        self.H = H
        F = H.copy()
        blocked = np.zeros(X.shape, bool)
        solid = H.copy()            # hard occluder top (no vegetation)
        bdefs = {b["id"]: b for b in B["buildings"]}

        def pm(poly):
            P = np.asarray(poly, float)
            x0, y0 = P.min(axis=0) - 1
            x1, y1 = P.max(axis=0) + 1
            i0 = max(0, int((x0 + 175) / res)); i1 = min(len(xs), int((x1 + 175) / res) + 2)
            j0 = max(0, int((y0 + 175) / res)); j1 = min(len(xs), int((y1 + 175) / res) + 2)
            m = np.zeros(X.shape, bool)
            if i1 > i0 and j1 > j0:
                m[j0:j1, i0:i1] = poly_mask(P, X[j0:j1, i0:i1], Y[j0:j1, i0:i1])
            return m

        def sm(a, b, hw):
            x0, x1 = min(a[0], b[0]) - hw - 1, max(a[0], b[0]) + hw + 1
            y0, y1 = min(a[1], b[1]) - hw - 1, max(a[1], b[1]) + hw + 1
            i0 = max(0, int((x0 + 175) / res)); i1 = min(len(xs), int((x1 + 175) / res) + 2)
            j0 = max(0, int((y0 + 175) / res)); j1 = min(len(xs), int((y1 + 175) / res) + 2)
            m = np.zeros(X.shape, bool)
            if i1 > i0 and j1 > j0:
                m[j0:j1, i0:i1] = seg_dist(X[j0:j1, i0:i1], Y[j0:j1, i0:i1], a, b) <= hw
            return m
        self.pm, self.sm = pm, sm
        self.inside_bld = np.zeros(X.shape, bool)
        for bp in L["buildings"]:
            bd = bdefs[bp["id"]]
            c, rot, zf = bp["position"][:2], bp["rotation_deg"], bp["position"][2]
            fp = pm(bp["footprint_world"])
            F[fp] = zf
            self.inside_bld |= fp
            for w in bd["walls"]:
                if w["level"] != "L0":
                    continue
                wp = wall_poly(w, extra_t=res / 2)
                m = pm([xf(c, rot, q) for q in list(wp.exterior.coords)[:-1]])
                for o in bd["openings"]:
                    if o["wall_id"] != w["id"]:
                        continue
                    walk = is_walk_opening(o)
                    if walk:
                        op = opening_poly(w, o, res)
                        m &= ~pm([xf(c, rot, q) for q in list(op.exterior.coords)[:-1]])
                blocked |= m
            for col in bd.get("columns", []):
                blocked |= pm([xf(c, rot, q) for q in list(box_poly(col["center"], col["size"], 0).exterior.coords)[:-1]])
            for f in bd.get("furniture", []):
                if f["level"] in ("L0", "exterior"):
                    blocked |= pm([xf(c, rot, q) for q in list(box_poly(f["center"], f["size"], f.get("rotation_deg", 0)).exterior.coords)[:-1]])
            for s in bd["stairs"]:
                blocked |= pm([xf(c, rot, q) for q in list(stair_poly(s).exterior.coords)[:-1]])
            for v in bd.get("sealed_voids", []):
                blocked |= pm([xf(c, rot, q) for q in v["polygon"]])
            for ch in bd.get("chimneys", []):
                if ch.get("base_z", 0.0) > 2.10:
                    continue            # stack corbelled out on the roof structure: no floor footprint
                if Polygon(unary_union([Polygon(p["external_rect"]) for p in bd["footprint_parts"]])).contains(Point(*ch["pos"])):
                    blocked |= pm([xf(c, rot, q) for q in list(box_poly(ch["pos"], ch.get("size", [0.3, 0.3]), 0).exterior.coords)[:-1]])
            for pl_ in sliding_leaf_polys(bd):
                blocked |= pm([xf(c, rot, q) for q in list(pl_.exterior.coords)[:-1]])
            for rf in bd["roof"]:
                for su in rf.get("supports", []):
                    blocked |= pm([xf(c, rot, q) for q in list(box_poly(su["pos"], su["size"], 0).exterior.coords)[:-1]])
            if bd.get("loading_dock"):
                F[pm([xf(c, rot, q) for q in bd["loading_dock"]["polygon"]])] = zf + bd["loading_dock"]["top_z"]
            for st in bd.get("exterior_steps", []):
                if st.get("apron"):
                    F[pm([xf(c, rot, q) for q in st["apron"]["polygon"]])] = zf + st["apron"]["z"]
                if st["type"] == "ramp":
                    m = pm([xf(c, rot, q) for q in st["polygon"]])
                    a = math.radians(rot)
                    lx = (X - c[0]) * math.cos(a) + (Y - c[1]) * math.sin(a)
                    ly = -(X - c[0]) * math.sin(a) + (Y - c[1]) * math.cos(a)
                    tt = ramp_param(st, lx, ly)
                    F = np.where(m, zf + st["z_top"] + tt * (st["z_bottom"] - st["z_top"]), F)
                if st["type"] == "step":
                    F[pm([xf(c, rot, q) for q in st["polygon"]])] = zf - st["riser"] / 2
            for s in bd["exterior_stairs"]:
                m = pm([xf(c, rot, q) for q in list(stair_poly(s).exterior.coords)[:-1]])
                if s["level_to"] != "L0":
                    blocked |= m
                    continue
                ld = s.get("landing")
                if ld:
                    F[pm([xf(c, rot, q) for q in ld["polygon"]])] = zf + ld["z"]
                dv = s["direction_vector"]
                p0 = xf(c, rot, s["start"])
                p1 = xf(c, rot, (s["start"][0] + dv[0], s["start"][1] + dv[1]))
                dd = (X - p0[0]) * (p1[0] - p0[0]) + (Y - p0[1]) * (p1[1] - p0[1])
                F = np.where(m, zf + s["z_start"] + np.clip(dd / max(s["run"], 0.01), 0, 1) * s["rise"], F)
            # LOS solid: building volume to eave (walls handled exactly by the 3D LOS model, this raster is for walk only)
        for sb in L["secondary_buildings"]:
            m = pm(sb["footprint_world"])
            if sb.get("embedded_in"):
                F = np.where(m, sb["roof_deck_top_z"], F)
                continue
            blocked |= m
        for p in L["props"]:
            if p["type"] in ("weir_stone_low",):
                continue
            blocked |= pm(list(box_poly(p["position"][:2], p["size"], p["rotation_deg"]).exterior.coords)[:-1])
        for fz in L["fences_walls_hedges"]:
            if not fz.get("blocks_movement", True):
                continue
            hw = 0.6 if "hedge" in fz["type"] else 0.12
            for a, b in zip(fz["polyline"][:-1], fz["polyline"][1:]):
                blocked |= sm(a, b, hw)
        for vb in L["vegetation_blocks"]:
            if not vb.get("blocks_movement", True):
                continue
            if "polyline" in vb:
                for a, b in zip(vb["polyline"][:-1], vb["polyline"][1:]):
                    blocked |= sm(a, b, vb["width"] / 2)
            else:
                blocked |= pm(vb["polygon"])
        for rw in L["retaining_walls"]:
            segs = rw.get("segments") or [[k, k + 1] for k in range(len(rw["polyline"]) - 1)]
            for i0, i1 in segs:
                blocked |= sm(rw["polyline"][i0], rw["polyline"][i1], rw["thickness"] / 2 + res / 2)
            for st in rw.get("stairs", []):
                blocked &= ~sm(st["bottom_center_world"], st["top_center_world"], st["width"] / 2 - 0.02)
        for br in L["bridges"]:
            a, b = br["ends"]
            m = sm(a, b, br["width"] / 2)
            ss = ((X - a[0]) * (b[0] - a[0]) + (Y - a[1]) * (b[1] - a[1])) / ((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2)
            F = np.where(m, br["deck_z"][0] + np.clip(ss, 0, 1) * (br["deck_z"][1] - br["deck_z"][0]), F)
            d = np.array(b, float) - np.array(a, float)
            d /= np.linalg.norm(d)
            nrm = np.array([-d[1], d[0]])
            for sg in (-1, 1):
                off = nrm * sg * (br["width"] / 2 + 0.05)
                blocked |= sm((np.array(a) + off).tolist(), (np.array(b) + off).tolist(), 0.06)
            blocked &= ~sm(a, b, br["width"] / 2 - 0.05)
        for po in L.get("utility_lines", {}).get("poles", []):
            x, y = po["pos"][:2]
            r = po.get("collision_radius", 0.14)
            i = int(round((x + 175) / res)); j = int(round((y + 175) / res))
            k = int(math.ceil(r / res)) + 1
            sub = (slice(max(0, j - k), j + k + 1), slice(max(0, i - k), i + k + 1))
            blocked[sub] |= np.hypot(X[sub] - x, Y[sub] - y) <= max(r, res / 2)
        for t in L["trees"]["instances"]:
            sp = L["trees"]["species"][t["species"]]
            r = sp["trunk_radius"] * t.get("scale", 1.0)
            x, y = t["pos"][:2]
            i = int(round((x + 175) / res)); j = int(round((y + 175) / res))
            k = int(math.ceil(r / res))
            if 0 <= j < len(xs) and 0 <= i < len(xs):
                sub = (slice(max(0, j - k), j + k + 1), slice(max(0, i - k), i + k + 1))
                blocked[sub] |= np.hypot(X[sub] - x, Y[sub] - y) <= r
        # steps / slopes
        dzx = np.abs(np.diff(F, axis=1))
        dzy = np.abs(np.diff(F, axis=0))
        step = np.zeros(X.shape, bool)
        lim = max(MAX_STEP, math.tan(math.radians(MAX_SLOPE)) * res + 1e-6)
        sx_ = dzx > lim
        sy_ = dzy > lim
        step[:, :-1] |= sx_; step[:, 1:] |= sx_; step[:-1, :] |= sy_; step[1:, :] |= sy_
        gy, gx = np.gradient(F, res)
        self.slope = np.degrees(np.arctan(np.hypot(gx, gy)))
        self.steep = self.slope > MAX_SLOPE
        self.soft = pm(L["boundary"]["soft_polygon"])
        self.blocked_obj = blocked
        self.F = F
        allb = blocked | step | self.steep | ~self.soft
        self.free = ~allb
        dist = ndimage.distance_transform_edt(self.free) * res
        self.walk = dist > CAPSULE_R
        self.water = np.zeros(X.shape, bool)
        for wtr in L.get("water", []):
            pl = wtr["polyline"]
            d, _, _, zs = T.polyline_query(X, Y, [[p[0], p[1]] for p in pl], [p[2] for p in pl])
            self.water |= (d <= wtr["width_at_surface"] / 2) & (F < zs + 0.02)
        lab, n = ndimage.label(self.walk)
        self.lab = lab
        sizes = ndimage.sum(np.ones_like(lab), lab, index=np.arange(1, n + 1)) if n else []
        self.main_comp = int(np.argmax(sizes)) + 1 if n else 0
        self.t = time.time() - t0

    def ij(self, x, y):
        n = len(self.xs) - 1
        return min(n, max(0, int(round((y + 175) / self.res)))), min(n, max(0, int(round((x + 175) / self.res))))

    def snap(self, x, y, rmax=1.0):
        j, i = self.ij(x, y)
        r = int(rmax / self.res)
        sub = self.walk[max(0, j - r):j + r + 1, max(0, i - r):i + r + 1]
        jj, ii = np.nonzero(sub)
        if len(jj) == 0:
            return None
        jj = jj + max(0, j - r)
        ii = ii + max(0, i - r)
        k = np.argmin((jj - j) ** 2 + (ii - i) ** 2)
        return int(jj[k]), int(ii[k])


def zone_cells(W, z):
    m = W.pm(z["polygon"]) & W.walk & (W.F >= z["z_min"]) & (W.F <= z["z_max"])
    return m


def fmm_from(W, mask):
    import skfmm
    phi = np.where(mask, -1.0, 1.0)
    phi = np.ma.MaskedArray(phi, ~(W.walk | mask))
    speed = np.where(W.water, 0.75, 1.0)
    t = skfmm.travel_time(phi, speed, dx=W.res)
    return np.ma.filled(t, np.inf)


def spawn_sets(L):
    """{zone_id: {team: [points]}}, {team: area}"""
    out = defaultdict(lambda: defaultdict(list))
    for sa in L["spawn_areas"]:
        for p in sa["candidate_points"]:
            for z in p["zones"]:
                out[z][sa["team"]].append(p)
    return out


def check_zones_spawns(L, B, W, rep, rules):
    rep.sec("4. Zones, spawns, balance, boundary, routes")
    soft = Polygon(L["boundary"]["soft_polygon"])
    bdefs = {b["id"]: b for b in B["buildings"]}
    # ---- Z01 zones on walkable ground, z-bands unambiguous, upper floors excluded
    errs = []
    info = []
    for z in L["capture_zones"]:
        P = Polygon(z["polygon"])
        if not P.is_valid:
            errs.append(f"{z['id']}: invalid polygon")
        if not (400 <= P.area <= 600):
            errs.append(f"{z['id']}: area {P.area:.0f} m2 outside 400-600")
        if abs(P.area - z["area_m2"]) > 0.5:
            errs.append(f"{z['id']}: area_m2 {z['area_m2']} != polygon {P.area:.1f}")
        if not soft.contains(P):
            errs.append(f"{z['id']}: polygon not inside the soft boundary")
        zm = W.pm(z["polygon"])
        inside_walk = zm & W.walk
        band = inside_walk & (W.F >= z["z_min"]) & (W.F <= z["z_max"])
        frac = band.sum() / max(1, zm.sum())
        if frac < 0.45:
            errs.append(f"{z['id']}: only {100 * frac:.0f} % of the polygon is walkable ground inside the z band")
        amb = inside_walk & (((W.F > z["z_min"] - 0.30) & (W.F < z["z_min"] + 0.30)) | ((W.F > z["z_max"] - 0.30) & (W.F < z["z_max"] + 0.30)))
        if amb.sum() * W.res ** 2 > 0.3:
            jj, ii = np.nonzero(amb)
            errs.append(f"{z['id']}: {amb.sum() * W.res ** 2:.1f} m2 of walkable surface lies within 0.30 m of z_min/z_max, e.g. "
                        f"({W.xs[ii[0]]:.1f},{W.xs[jj[0]]:.1f}) z {W.F[jj[0], ii[0]]:.2f} -- capsule-foot inclusion ambiguous")
        comp = set(np.unique(W.lab[band])) - {0}
        if W.main_comp not in comp:
            errs.append(f"{z['id']}: zone cells not on the main walk component")
        # upper floors / balconies / platforms of buildings whose footprint intersects the polygon
        for bp in L["buildings"]:
            bd = bdefs[bp["id"]]
            c, rot, zf = bp["position"][:2], bp["rotation_deg"], bp["position"][2]
            for l in bd["levels"]:
                if l["floor_z"] <= 0 or l.get("ceiling_height", 0) <= 0:
                    continue
                for r in bd["rooms"]:
                    if r["level"] != l["id"]:
                        continue
                    rp = Polygon([xf(c, rot, q) for q in r["polygon"]])
                    if rp.intersection(P).area > 0.01 and zf + l["floor_z"] < z["z_max"] + 0.30:
                        errs.append(f"{z['id']}: upper-floor room {r['id']} at z {zf + l['floor_z']:.2f} is inside the zone band")
            for s in bd["exterior_stairs"]:
                ld = s.get("landing")
                if ld and s["level_to"] not in ("L0",):
                    lp = Polygon([xf(c, rot, q) for q in ld["polygon"]])
                    if lp.intersection(P).area > 0.01 and zf + ld["z"] < z["z_max"] + 0.30:
                        errs.append(f"{z['id']}: elevated platform {ld['id']} inside the zone band")
        for st in L["terrain"]["stamps"]:
            if st["kind"] in ("channel", "ditch", "sunken_lane"):
                pl = LineString([p[:2] for p in st["polyline"]])
                if pl.intersects(P):
                    zs = [p[2] for p in st["polyline"]]
                    if max(zs) >= z["z_min"] - 0.30:
                        errs.append(f"{z['id']}: trench/bed {st['id']} crosses the polygon with bed z up to {max(zs):.2f} >= z_min - 0.30")
        info.append(f"{z['id']}: {P.area:.0f} m2, z {z['z_min']}..{z['z_max']}, walkable in band {100 * frac:.0f} %")
    rep.check("Z01", errs, "zones on walkable ground, fully inside the boundary, unambiguous z bands (>= 0.30 m margin), upper floors, "
                           "platforms and trench beds excluded")
    for i in info:
        rep.info(i)
    # ---- S01 spawn points
    errs = []
    sets = spawn_sets(L)
    areas = {sa["team"]: sa for sa in L["spawn_areas"]}
    for team, sa in areas.items():
        pts = sa["candidate_points"]
        poly = Polygon(sa["polygon"])
        if len(pts) < 8:
            errs.append(f"{team}: only {len(pts)} spawn points")
        for p in pts:
            x, y, zp = p["pos"]
            if not poly.buffer(0.01).contains(Point(x, y)):
                errs.append(f"{team}: {p['id']} outside its spawn area polygon")
            j, i = W.ij(x, y)
            if not W.walk[j, i]:
                errs.append(f"{team}: {p['id']} ({x},{y}) not on walkable capsule-clear ground")
            if W.slope[j, i] > 15.0:
                errs.append(f"{team}: {p['id']} on a {W.slope[j, i]:.1f} deg slope (> 15)")
            if abs(W.F[j, i] - zp) > 0.12:
                errs.append(f"{team}: {p['id']} z {zp} vs ground {W.F[j, i]:.2f}")
            if W.inside_bld[j, i]:
                errs.append(f"{team}: {p['id']} inside a building")
            # clearance to objects (props, buildings, fences, vegetation)
            r = int(0.85 / W.res)
            sub = W.blocked_obj[max(0, j - r):j + r + 1, max(0, i - r):i + r + 1]
            if sub.any():
                errs.append(f"{team}: {p['id']} closer than 0.85 m to an object")
            if soft.exterior.distance(Point(x, y)) < 10.0:
                errs.append(f"{team}: {p['id']} only {soft.exterior.distance(Point(x, y)):.1f} m from the soft boundary (< 10 m, warning band)")
        for a in range(len(pts)):
            for b in range(a + 1, len(pts)):
                d = math.dist(pts[a]["pos"][:2], pts[b]["pos"][:2])
                if d < 1.5:
                    errs.append(f"{team}: {pts[a]['id']} / {pts[b]['id']} only {d:.2f} m apart")
    for zid, tm in sets.items():
        for team, pts in tm.items():
            if len(pts) < 8:
                errs.append(f"{zid}/{team}: only {len(pts)} points for this zone")
            spread = max(math.dist(p["pos"][:2], q["pos"][:2]) for p in pts for q in pts)
            if spread > 25.0:
                errs.append(f"{zid}/{team}: active spawn set spread {spread:.1f} m > 25 m")
    rep.check("S01", errs, "each team >= 8 points (16 per team: 2 rows x 8) inside its area; each zone has 8 per team; walkable, "
                           "slope <= 15 deg, >= 0.85 m from objects, not in buildings, >= 1.5 m apart, >= 10 m inside the soft boundary, "
                           "active set spread <= 25 m")
    # ---- S02 separation / bearings / straight-line balance
    errs = []
    info = []
    for z in L["capture_zones"]:
        zid = z["id"]
        tm = sets[zid]
        teams = sorted(tm)
        P = Polygon(z["polygon"])
        cen = {t: np.mean([p["pos"][:2] for p in tm[t]], axis=0) for t in teams}
        for a in range(len(teams)):
            for b in range(a + 1, len(teams)):
                d = min(math.dist(p["pos"][:2], q["pos"][:2]) for p in tm[teams[a]] for q in tm[teams[b]])
                if d < 150.0:
                    errs.append(f"{zid}: active spawns {teams[a]} / {teams[b]} only {d:.0f} m apart (< 150)")
        brg = {t: bearing(z["center"], cen[t]) for t in teams}
        seps = [ang_sep(brg[teams[a]], brg[teams[b]]) for a in range(len(teams)) for b in range(a + 1, len(teams))]
        if min(seps) < 80.0:
            errs.append(f"{zid}: approach bearings {({t: round(v) for t, v in brg.items()})} min separation {min(seps):.0f} deg < 80")
        dc = {t: float(np.mean([math.dist(p["pos"][:2], z["center"]) for p in tm[t]])) for t in teams}
        de = {t: float(np.mean([P.exterior.distance(Point(p["pos"][:2])) for p in tm[t]])) for t in teams}
        for name, dd in (("centre", dc), ("edge", de)):
            m = np.mean(list(dd.values()))
            dev = max(abs(v / m - 1) for v in dd.values())
            if dev > 0.10:
                errs.append(f"{zid}: straight-line spawn->zone {name} distances {({t: round(v, 1) for t, v in dd.items()})} deviate "
                            f"{100 * dev:.1f} % from the mean (> 10 %)")
        info.append(f"{zid}: straight-line centre {({t: round(v, 1) for t, v in dc.items()})}, edge {({t: round(v, 1) for t, v in de.items()})}, "
                    f"bearings {({t: round(v) for t, v in brg.items()})} (min sep {min(seps):.0f} deg)")
    rep.check("S02", errs, "per zone: active spawns of different teams >= 150 m apart, approach bearings >= 80 deg apart, "
                           "straight-line centre and edge distances within +-10 % of the mean")
    for i in info:
        rep.info(i)
    # ---- S03 grid-path (FMM) balance
    errs = []
    info = []
    fields = {}
    for z in L["capture_zones"]:
        zid = z["id"]
        zm = zone_cells(W, z)
        D = fmm_from(W, zm)
        fields[zid] = D
        tm = sets[zid]
        means = {}
        for team, pts in tm.items():
            vals = []
            for p in pts:
                j, i = W.ij(*p["pos"][:2])
                sub = D[max(0, j - 2):j + 3, max(0, i - 2):i + 3]
                sub = sub[np.isfinite(sub)]
                vals.append(float(sub.min()) if sub.size else float("inf"))
            if not all(math.isfinite(v) for v in vals):
                errs.append(f"{zid}/{team}: {sum(1 for v in vals if not math.isfinite(v))} spawn points cannot reach the zone")
                continue
            means[team] = float(np.mean(vals))
        if len(means) == 3:
            m = np.mean(list(means.values()))
            dev = max(abs(v / m - 1) for v in means.values())
            ratio = max(means.values()) / min(means.values())
            if dev > 0.10:
                errs.append(f"{zid}: grid-path distances {({t: round(v, 1) for t, v in means.items()})} deviate {100 * dev:.1f} % (> 10 %)")
            if ratio > 1.06:
                errs.append(f"{zid}: grid-path max/min {ratio:.3f} > 1.06 (project target)")
            info.append(f"{zid}: FMM walk to zone edge {({t: round(v, 1) for t, v in means.items()})} m, max dev {100 * dev:.1f} %, "
                        f"max/min {ratio:.3f}, run 3.5 m/s {min(means.values()) / 3.5:.0f}-{max(means.values()) / 3.5:.0f} s")
    rep.check("S03", errs, "grid-path (fast marching, 0.25 m, capsule-eroded) spawn -> zone distances within +-10 % and max/min <= 1.06")
    for i in info:
        rep.info(i)
    # ---- B00 boundary encloses all gameplay content
    errs = []
    hard = Polygon(L["boundary"]["hard_polygon"])
    if not hard.buffer(0.5).contains(soft):
        errs.append("hard polygon does not enclose the soft polygon")
    for b in L["buildings"]:
        if not soft.contains(Polygon(b["footprint_world"]).buffer(3.0)):
            errs.append(f"main building {b['id']} (+3 m) not inside the soft boundary")
    for sa in L["spawn_areas"]:
        for p in sa["candidate_points"]:
            if not soft.contains(Point(p["pos"][:2])):
                errs.append(f"spawn {p['id']} outside the soft boundary")
    for cp in L["cover_points"]["points"]:
        if not soft.contains(Point(cp["pos"][:2])):
            errs.append(f"cover point {cp['id']} outside the soft boundary")
    for zid, ln in L["lanes"].items():
        for kind in ("primary", "flank"):
            for team, lane in ln[kind].items():
                pts = lane if kind == "primary" else lane["waypoints"]
                for p in pts:
                    if not soft.buffer(0.5).contains(Point(p[:2])):
                        errs.append(f"lane {zid}/{kind}/{team} point {p[:2]} outside the soft boundary")
                        break
    for ck in L["chokepoints"]:
        if "at" in ck:
            pts = ck["at"] if isinstance(ck["at"][0], list) else [ck["at"]]
            for p in pts:
                if not soft.contains(Point(p[:2])):
                    errs.append(f"chokepoint {ck['id']} outside the soft boundary")
    for p in L["qa_points"]:
        if p["kind"] != "boundary" and not soft.buffer(0.5).contains(Point(p["pos"][:2])):
            errs.append(f"QA point {p['id']} outside the soft boundary")
    for tr in L["boundary"]["treatment"]:
        if not tr.get("physical") or not tr.get("explanation"):
            errs.append(f"boundary section {tr.get('section')} lacks physical treatment or player explanation")
    if "warning_polygon" not in L["boundary"]:
        errs.append("boundary.warning_polygon (8 m warning band) missing")
    rep.check("BND", errs, f"soft boundary ({soft.area:.0f} m2) encloses all buildings, zones, spawns, cover points, lanes, chokepoints "
                           "and QA points; hard polygon encloses it; every boundary section has a physical treatment and a player explanation")
    # ---- R01 routes: walkable, slope/step limits, flank lengths
    errs = []
    info = []
    maxs = 0.0
    for zid, ln in L["lanes"].items():
        prim = {t: lane for t, lane in ln["primary"].items()}
        for kind in ("primary", "flank"):
            for team, lane in ln[kind].items():
                pts = np.array((lane if kind == "primary" else lane["waypoints"]), float)
                for a, b in zip(pts[:-1], pts[1:]):
                    Lg = math.dist(a[:2], b[:2])
                    n = max(2, int(Lg / 0.25))
                    for k in range(n + 1):
                        x = a[0] + (b[0] - a[0]) * k / n
                        y = a[1] + (b[1] - a[1]) * k / n
                        j, i = W.ij(x, y)
                        s_ = W.slope[j, i]
                        if W.steep[j, i]:
                            # tolerate single-cell stair/door edges (<= 0.40 step) handled by the step test
                            nb = W.F[max(0, j - 1):j + 2, max(0, i - 1):i + 2]
                            if nb.max() - nb.min() > 2 * MAX_STEP:
                                errs.append(f"lane {zid}/{kind}/{team} crosses a {s_:.0f} deg slope / {nb.max() - nb.min():.2f} m step at ({x:.1f},{y:.1f})")
                                break
                        elif s_ > maxs and not W.inside_bld[j, i]:
                            maxs = s_
                    else:
                        continue
                    break
            if kind == "flank":
                for team, fl in ln["flank"].items():
                    ex = fl["extra_vs_primary_pct"]
                    if ex > 10.0 + EPS and not fl.get("deep_flank"):
                        errs.append(f"flank {zid}/{team} is {ex:.1f} % longer than the primary lane (> 10 %, not declared deep_flank)")
                    if fl.get("deep_flank"):
                        info.append(f"deep flank accepted: {zid}/{team} +{ex:.1f} % ({fl.get('deep_flank')})")
    rep.check("R01", errs, f"all primary and flank lanes stay on walkable ground with slopes <= 45 deg (max open-ground slope "
                           f"{maxs:.1f} deg); flanks within +10 % of the primary lane unless declared deep flanks")
    for i in info:
        rep.info(i)
    # ---- R02 slopes on roads, tracks and paths
    errs = []
    worst = {}
    for coll in ("roads", "tracks", "paths"):
        for rd in L[coll]:
            pl = rd.get("polyline") or rd.get("xy")
            pts = np.array([p[:2] for p in pl], float)
            mx = 0.0
            for a, b in zip(pts[:-1], pts[1:]):
                n = max(2, int(math.dist(a, b) / 0.5))
                for k in range(n + 1):
                    x = a[0] + (b[0] - a[0]) * k / n
                    y = a[1] + (b[1] - a[1]) * k / n
                    j, i = W.ij(x, y)
                    if not W.soft[j, i]:
                        continue
                    mx = max(mx, W.slope[j, i])
            worst[rd["id"]] = mx
            lim = 20.0 if coll in ("roads", "tracks") and rd["id"] not in ("RAMP_SKLAD_E",) else MAX_SLOPE
            if mx > lim:
                errs.append(f"{rd['id']}: slope {mx:.1f} deg > {lim}")
    rep.check("R02", errs, f"roads/tracks <= 20 deg (ramp <= 45), paths <= 45 deg inside the boundary (worst: "
                           f"{max(worst.items(), key=lambda kv: kv[1])[0]} {max(worst.values()):.1f} deg)")
    # ---- R03 documented entrances connected (retaining-wall stairs, dock stairs/ramp, bridges, lane exits, doors)
    errs = []
    n_ok = 0
    for ck in L["chokepoints"]:
        pts = []
        if "at" in ck:
            pts = ck["at"] if isinstance(ck["at"][0], list) else [ck["at"]]
        elif "at_s" in ck:
            continue
        if ck.get("level") not in (None, "L0"):
            continue
        for p in pts:
            c = W.snap(p[0], p[1], 1.2)
            if c is None or W.lab[c] != W.main_comp:
                errs.append(f"entrance {ck['id']} at {p[:2]} not connected to the main walk component")
            else:
                n_ok += 1
    rep.check("R03", errs, f"{n_ok} documented entrance points (doors, stairs, bridges, gates, ramps) lie on the main walk component")
    # ---- R04 approach space in front of every ground-level stair (0.8 m before the first riser, full capsule clearance)
    errs = []
    n = 0
    for bp in L["buildings"]:
        bd = bdefs[bp["id"]]
        c, rot = bp["position"][:2], bp["rotation_deg"]
        for s in bd["exterior_stairs"]:
            dv = s["direction_vector"]
            p = xf(c, rot, (s["start"][0] - dv[0] * 0.8, s["start"][1] - dv[1] * 0.8))
            j, i = W.ij(*p)
            n += 1
            if not (W.walk[j, i] and W.lab[j, i] == W.main_comp):
                errs.append(f"{bp['id']}.{s['id']}: the 0.8 m approach before the first riser at ({p[0]:.2f},{p[1]:.2f}) is blocked or "
                            "not capsule-clear")
    for rw in L["retaining_walls"]:
        for st in rw.get("stairs", []):
            a_ = np.array(st["bottom_center_world"])
            b_ = np.array(st["top_center_world"])
            d_ = (b_ - a_) / np.linalg.norm(b_ - a_)
            for tag, p in (("bottom", a_ - d_ * 0.8), ("top", b_ + d_ * 0.8)):
                j, i = W.ij(*p)
                n += 1
                if not (W.walk[j, i] and W.lab[j, i] == W.main_comp):
                    errs.append(f"{st['id']}: {tag} approach at ({p[0]:.2f},{p[1]:.2f}) blocked or not capsule-clear")
    rep.check("R04", errs, f"{n} stair approaches (exterior building stairs, retaining-wall stairs) are free and capsule-clear")
    return fields


# ================================================================================================
# 5. line of sight (hard geometry only: terrain, buildings with real window openings, closed buildings, hard props,
#    walls, retaining walls, HESCO) -- vegetation deliberately ignored for spawn safety
# ================================================================================================
class LOS:
    def __init__(self, L, B, W):
        self.W = W
        self.H = W.H
        self.res = W.res
        bdefs = {b["id"]: b for b in B["buildings"]}
        boxes = []   # cx, cy, hx, hy, rot_rad, z0, z1
        roofs = []   # (poly world, fn(x,y) -> z top, z bottom)

        def addbox(cx, cy, lx, ly, rot, z0, z1):
            if lx <= 0 or ly <= 0 or z1 <= z0:
                return
            boxes.append((cx, cy, lx / 2, ly / 2, math.radians(rot), z0, z1))
        for bp in L["buildings"]:
            bd = bdefs[bp["id"]]
            c, rot, zf = bp["position"][:2], bp["rotation_deg"], bp["position"][2]
            lvl = {l["id"]: l for l in bd["levels"]}
            ops = {o["id"]: o for o in bd["openings"]}
            for w in bd["walls"]:
                sx, sy, ux, uy, nx, ny, Lw = wall_frame(w)
                ang = math.degrees(math.atan2(uy, ux))
                zl = zf + lvl[w["level"]]["floor_z"]
                for cb in w["construction_boxes"]:
                    part_see_through = False
                    u0, u1 = cb["u"]
                    mx_, my_ = sx + ux * (u0 + u1) / 2, sy + uy * (u0 + u1) / 2
                    wc = xf(c, rot, (mx_, my_))
                    addbox(wc[0], wc[1], u1 - u0, w["thickness"], ang + rot, zl + cb["z"][0], zl + cb["z"][1])
                for o in bd["openings"]:
                    if o["wall_id"] == w["id"] and not o.get("passes", {}).get("vision", True):
                        a, b = o["offset_from_start"], o["offset_from_start"] + o["width"]
                        mx_, my_ = sx + ux * (a + b) / 2, sy + uy * (a + b) / 2
                        wc = xf(c, rot, (mx_, my_))
                        z0 = o["sill_height"]
                        z1 = o["head_height"]
                        if o["type"] == "roller_door":
                            z0 = o["state"]["open_height"]
                        addbox(wc[0], wc[1], b - a, w["thickness"], ang + rot, zl + z0, zl + z1)
            for sl in bd.get("slabs", []):
                P = Polygon(sl["polygon"])
                for h in sl.get("openings", []):
                    P = P.difference(Polygon(h["polygon"]))
                geoms = [P] if P.geom_type == "Polygon" else list(P.geoms)
                for g in geoms:
                    x0, y0, x1, y1 = g.bounds
                    # decompose into up to a few axis-aligned rectangles by x-strips
                    xs_ = sorted(set([round(v[0], 4) for v in g.exterior.coords] + [round(v[0], 4) for r_ in g.interiors for v in r_.coords]))
                    for xa, xb in zip(xs_[:-1], xs_[1:]):
                        strip = g.intersection(sbox(xa, y0 - 1, xb, y1 + 1))
                        for gg in ([strip] if strip.geom_type == "Polygon" else getattr(strip, "geoms", [])):
                            if gg.area < 1e-4:
                                continue
                            bx0, by0, bx1, by1 = gg.bounds
                            cc = xf(c, rot, ((bx0 + bx1) / 2, (by0 + by1) / 2))
                            addbox(cc[0], cc[1], bx1 - bx0, by1 - by0, rot, zf + sl["top_z"] - sl["thickness"], zf + sl["top_z"])
            for rf in bd["roof"]:
                if rf["type"] == "mono":
                    Rr = np.array(rf["rect"])
                    x0, y0 = Rr.min(axis=0); x1, y1 = Rr.max(axis=0)
                    cc = xf(c, rot, ((x0 + x1) / 2, (y0 + y1) / 2))
                    addbox(cc[0], cc[1], x1 - x0, y1 - y0, rot, zf + rf["eave_z"] - 0.15, zf + rf["high_z"])
                    continue
                Rr = np.array(rf["wall_rect"])
                x0, y0 = Rr.min(axis=0); x1, y1 = Rr.max(axis=0)
                roofs.append((c, rot, zf, rf, x0, y0, x1, y1))
            for f in bd.get("furniture", []):
                if f.get("blocks_vision") and f["level"] in lvl:
                    fc = xf(c, rot, f["center"])
                    z0 = zf + lvl[f["level"]]["floor_z"]
                    addbox(fc[0], fc[1], f["size"][0], f["size"][1], rot + f.get("rotation_deg", 0), z0, z0 + f["size"][2])
            if bd.get("loading_dock"):
                Rr = np.array(bd["loading_dock"]["polygon"])
                x0, y0 = Rr.min(axis=0); x1, y1 = Rr.max(axis=0)
                cc = xf(c, rot, ((x0 + x1) / 2, (y0 + y1) / 2))
                addbox(cc[0], cc[1], x1 - x0, y1 - y0, rot, zf - 1.10, zf)
            for ba in bd.get("balconies", []):
                Rr = np.array(ba["polygon"])
                x0, y0 = Rr.min(axis=0); x1, y1 = Rr.max(axis=0)
                cc = xf(c, rot, ((x0 + x1) / 2, (y0 + y1) / 2))
                addbox(cc[0], cc[1], x1 - x0, y1 - y0, rot, zf + ba["top_z"] - ba["slab_thickness"], zf + ba["top_z"])
                pp = ba["parapet"]
                for (a_, b_) in pp["segments"]:
                    mx_, my_ = (a_[0] + b_[0]) / 2, (a_[1] + b_[1]) / 2
                    cc = xf(c, rot, (mx_, my_))
                    ang = math.degrees(math.atan2(b_[1] - a_[1], b_[0] - a_[0]))
                    addbox(cc[0], cc[1], math.dist(a_, b_), pp["thickness"], rot + ang, zf + ba["top_z"], zf + ba["top_z"] + pp["height"])
        for sb in L["secondary_buildings"]:
            if sb.get("embedded_in"):
                continue
            if sb["type"].startswith("bus_shelter") or sb["type"].startswith("transformer_pole"):
                continue          # open timber shelter (back wall is slatted) / pole-mounted transformer: no solid volume
            c, rot, z = sb["position"][:2], sb["rotation_deg"], sb["position"][2]
            addbox(c[0], c[1], sb["footprint"][0], sb["footprint"][1], rot, z - 0.5, z + sb["eave_height"])
            roofs.append(("SEC", sb))
            if "tower" in sb:
                tw = sb["tower"]
                tc = xf(c, rot, tw["offset_local"])
                addbox(tc[0], tc[1], tw["size"][0], tw["size"][1], rot, z, z + tw["height"])
        for p in L["props"]:
            if not p.get("blocks_vision", True):
                continue
            addbox(p["position"][0], p["position"][1], p["size"][0], p["size"][1], p["rotation_deg"], p["position"][2] - 0.3,
                   p["position"][2] + p["size"][2])
        for fz in L["fences_walls_hedges"]:
            if not fz["blocks_vision"] or "hedge" in fz["type"]:
                continue
            for a, b in zip(fz["polyline"][:-1], fz["polyline"][1:]):
                mx_, my_ = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
                z = float(T.height_at(L, mx_, my_)[0])
                addbox(mx_, my_, math.dist(a, b), 0.25, math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])), z - 0.3, z + fz["height"])
        for rw in L["retaining_walls"]:
            segs = rw.get("segments") or [[k, k + 1] for k in range(len(rw["polyline"]) - 1)]
            for i0, i1 in segs:
                a, b = rw["polyline"][i0], rw["polyline"][i1]
                mx_, my_ = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
                addbox(mx_, my_, math.dist(a, b), rw["thickness"], math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])), rw["bottom_z"] - 0.3, rw["top_z"])
        self.boxes = np.array(boxes, float)
        self.roofs = roofs

    def roof_top(self, x, y):
        """max roof-volume top at points (x, y) (nan outside); roof volume = [eave, roof surface]."""
        top = np.full(np.shape(x), np.nan)
        bot = np.full(np.shape(x), np.nan)
        for r in self.roofs:
            if r[0] == "SEC":
                sb = r[1]
                c, rot, z = sb["position"][:2], sb["rotation_deg"], sb["position"][2]
                a = math.radians(rot)
                lx = (x - c[0]) * math.cos(a) + (y - c[1]) * math.sin(a)
                ly = -(x - c[0]) * math.sin(a) + (y - c[1]) * math.cos(a)
                fx, fy = sb["footprint"]
                inside = (np.abs(lx) <= fx / 2) & (np.abs(ly) <= fy / 2)
                if sb["ridge_height"] <= sb["eave_height"] + 0.05:
                    continue
                if fx >= fy:
                    zt = z + sb["eave_height"] + (sb["ridge_height"] - sb["eave_height"]) * (1 - np.abs(ly) / (fy / 2))
                else:
                    zt = z + sb["eave_height"] + (sb["ridge_height"] - sb["eave_height"]) * (1 - np.abs(lx) / (fx / 2))
                top = np.where(inside, np.fmax(top, zt), top)
                bot = np.where(inside, np.fmin(bot, z + sb["eave_height"]) if np.isnan(bot).all() else z + sb["eave_height"], bot)
                continue
            c, rot, zf, rf, x0, y0, x1, y1 = r
            a = math.radians(rot)
            lx = (x - c[0]) * math.cos(a) + (y - c[1]) * math.sin(a)
            ly = -(x - c[0]) * math.sin(a) + (y - c[1]) * math.cos(a)
            inside = (lx >= x0) & (lx <= x1) & (ly >= y0) & (ly <= y1)
            tp = math.tan(math.radians(rf["pitch_deg"]))
            if rf["type"] == "gable":
                zt = rf["eave_z"] + ((y1 - y0) / 2 - np.abs(ly - (y0 + y1) / 2)) * tp
            else:
                zt = rf["eave_z"] + np.minimum((y1 - y0) / 2 - np.abs(ly - (y0 + y1) / 2), (x1 - x0) / 2 - np.abs(lx - (x0 + x1) / 2)) * tp
            top = np.where(inside, np.fmax(top, zf + zt), top)
            bot = np.where(inside, zf + rf["eave_z"] - 0.30, bot)
        return top, bot

    def visible(self, A, Bs, step=0.4):
        """A: (3,), Bs: (n,3) -> bool array visible (no hard occluder between)."""
        A = np.asarray(A, float)
        Bs = np.asarray(Bs, float)
        n = len(Bs)
        vis = np.ones(n, bool)
        D = Bs - A
        Lh = np.hypot(D[:, 0], D[:, 1])
        # terrain samples
        for k in range(n):
            m = max(2, int(Lh[k] / step))
            t = np.linspace(0.0, 1.0, m + 1)[1:-1]
            if len(t) == 0:
                continue
            px = A[0] + D[k, 0] * t
            py = A[1] + D[k, 1] * t
            pz = A[2] + D[k, 2] * t
            fi = (px + 175) / self.res
            fj = (py + 175) / self.res
            i0 = np.clip(np.floor(fi).astype(int), 0, self.H.shape[1] - 2)
            j0 = np.clip(np.floor(fj).astype(int), 0, self.H.shape[0] - 2)
            tx = fi - i0
            ty = fj - j0
            h = (self.H[j0, i0] * (1 - tx) * (1 - ty) + self.H[j0, i0 + 1] * tx * (1 - ty) + self.H[j0 + 1, i0] * (1 - tx) * ty
                 + self.H[j0 + 1, i0 + 1] * tx * ty)
            # ignore samples within 0.6 m of the ends (standing on the ground)
            keep = (t * Lh[k] > 0.6) & ((1 - t) * Lh[k] > 0.6)
            if np.any((pz <= h + 0.05) & keep):
                vis[k] = False
                continue
            rt, rb = self.roof_top(px, py)
            if np.any((pz <= rt) & (pz >= rb) & keep):
                vis[k] = False
        idx = np.nonzero(vis)[0]
        if len(idx) == 0 or len(self.boxes) == 0:
            return vis
        bx = self.boxes
        for k in idx:
            a = A
            b = Bs[k]
            x0, x1 = min(a[0], b[0]), max(a[0], b[0])
            y0, y1 = min(a[1], b[1]), max(a[1], b[1])
            rr = np.hypot(bx[:, 2], bx[:, 3])
            sel = (bx[:, 0] + rr >= x0) & (bx[:, 0] - rr <= x1) & (bx[:, 1] + rr >= y0) & (bx[:, 1] - rr <= y1)
            if not sel.any():
                continue
            bb = bx[sel]
            ca, sa = np.cos(bb[:, 4]), np.sin(bb[:, 4])
            # transform segment into box frames
            ax = (a[0] - bb[:, 0]) * ca + (a[1] - bb[:, 1]) * sa
            ay = -(a[0] - bb[:, 0]) * sa + (a[1] - bb[:, 1]) * ca
            dx = (b[0] - a[0]) * ca + (b[1] - a[1]) * sa
            dy = -(b[0] - a[0]) * sa + (b[1] - a[1]) * ca
            az = np.full(len(bb), a[2])
            dz = np.full(len(bb), b[2] - a[2])
            tmin = np.zeros(len(bb))
            tmax = np.ones(len(bb))
            for (o, d, lo, hi) in ((ax, dx, -bb[:, 2], bb[:, 2]), (ay, dy, -bb[:, 3], bb[:, 3]), (az, dz, bb[:, 5], bb[:, 6])):
                with np.errstate(divide="ignore", invalid="ignore"):
                    t1 = (lo - o) / d
                    t2 = (hi - o) / d
                par = np.abs(d) < 1e-12
                tl = np.where(par, np.where((o >= lo) & (o <= hi), -np.inf, np.inf), np.minimum(t1, t2))
                th = np.where(par, np.where((o >= lo) & (o <= hi), np.inf, -np.inf), np.maximum(t1, t2))
                tmin = np.maximum(tmin, tl)
                tmax = np.minimum(tmax, th)
            L3 = np.linalg.norm(b - a)
            hit = (tmax >= tmin) & (tmax > 0.3 / L3) & (tmin < 1 - 0.3 / L3)
            if hit.any():
                vis[k] = False
        return vis


def zone_samples(L, B, W, z, spacing=2.0):
    P = Polygon(z["polygon"])
    x0, y0, x1, y1 = P.bounds
    out = []
    for x in np.arange(x0 + spacing / 2, x1, spacing):
        for y in np.arange(y0 + spacing / 2, y1, spacing):
            if not P.contains(Point(x, y)):
                continue
            j, i = W.ij(x, y)
            f = W.F[j, i]
            if W.walk[j, i] and z["z_min"] <= f <= z["z_max"]:
                out.append((x, y, f))
    return out


def upper_window_points(L, B, zone_id):
    """observer points at upper-floor window firing positions and balconies next to a zone."""
    out = []
    bdefs = {b["id"]: b for b in B["buildings"]}
    for cp in L["cover_points"]["points"]:
        if cp.get("kind") == "window" and cp.get("level") not in (None, "L0") and zone_id in cp["zones"]:
            out.append((cp["pos"][0], cp["pos"][1], cp["pos"][2], cp["id"]))
    for bp in L["buildings"]:
        bd = bdefs[bp["id"]]
        for ba in bd.get("balconies", []):
            P = Polygon(ba["polygon"]).centroid
            q = xf(bp["position"][:2], bp["rotation_deg"], (P.x, P.y))
            if bp.get("zone") == zone_id:
                out.append((q[0], q[1], bp["position"][2] + ba["top_z"], ba["id"]))
    return out


def check_los(L, B, W, rep):
    rep.sec("5. Line of sight with hard geometry only (vegetation ignored), incl. window openings and upper floors")
    t0 = time.time()
    los = LOS(L, B, W)
    sets = spawn_sets(L)
    errs = []
    info = []
    for z in L["capture_zones"]:
        zid = z["id"]
        samp = zone_samples(L, B, W, z)
        tgts = [(x, y, f + h) for (x, y, f) in samp for h in (1.2, 1.6)]
        upw = upper_window_points(L, B, zid)
        tgts_up = [(x, y, zz + EYE) for (x, y, zz, _) in upw]
        tm = sets[zid]
        tot = 0
        for team, pts in tm.items():
            nvis = 0
            for p in pts:
                eye = (p["pos"][0], p["pos"][1], p["pos"][2] + EYE)
                v = los.visible(eye, np.array(tgts + tgts_up))
                nvis += int(v.sum())
                if v.any():
                    k = int(np.nonzero(v)[0][0])
                    tt = (tgts + tgts_up)[k]
                    errs.append(f"{zid}: spawn {p['id']} sees the zone/overwatch point ({tt[0]:.1f},{tt[1]:.1f},{tt[2]:.1f}) "
                                f"[{int(v.sum())} of {len(v)} rays]")
            tot += len(pts) * (len(tgts) + len(tgts_up))
        # spawn <-> enemy spawn (same zone)
        teams = sorted(tm)
        for a in range(len(teams)):
            for b in range(a + 1, len(teams)):
                for p in tm[teams[a]]:
                    eye = (p["pos"][0], p["pos"][1], p["pos"][2] + EYE)
                    tg = np.array([(q["pos"][0], q["pos"][1], q["pos"][2] + h) for q in tm[teams[b]] for h in (1.2, 1.65)])
                    v = los.visible(eye, tg)
                    if v.any():
                        errs.append(f"{zid}: spawn {p['id']} sees enemy spawn row of {teams[b]} ({int(v.sum())} rays)")
        info.append(f"{zid}: {len(samp)} zone samples x 2 heights + {len(upw)} upper-floor window/balcony points vs 8 spawn points "
                    f"per team: {tot} rays tested")
    rep.check("V01", errs, "0 visible rays from every active spawn point to its zone (incl. through windows) and to upper-floor "
                           "windows/balconies next to the zone, and 0 rays between enemy spawn rows -- terrain, buildings, closed "
                           "buildings, hard props, walls and HESCO only (no foliage)")
    for i in info:
        rep.info(i)
    rep.info(f"LOS model: {len(los.boxes)} oriented boxes + {len(los.roofs)} roof volumes, {time.time() - t0:.0f} s")
    return los


# ================================================================================================
# 6. vegetation, performance, AI data, QA points, navmesh results
# ================================================================================================
def check_misc(L, B, W, rep):
    rep.sec("6. Vegetation, performance budget, AI data, QA points, navmesh")
    soft = Polygon(L["boundary"]["soft_polygon"])
    errs = []
    sp = L["trees"]["species"]
    for k, s in sp.items():
        if s.get("leaf_type") != "deciduous":
            n_in = sum(1 for t in L["trees"]["instances"] if t["species"] == k and soft.contains(Point(t["pos"][:2])))
            if n_in:
                errs.append(f"species {k} ({s.get('leaf_type')}) used {n_in}x inside the playable area (brief: listnaté stromy)")
    roads = unary_union([LineString([p[:2] for p in rd["polyline"]]).buffer(rd["width"] / 2) for rd in L["roads"] + L["tracks"]])
    blds = unary_union([Polygon(b["footprint_world"]) for b in L["buildings"]] + [Polygon(b["footprint_world"]) for b in L["secondary_buildings"]])
    zones = unary_union([Polygon(z["polygon"]) for z in L["capture_zones"]])
    for t in L["trees"]["instances"]:
        p = Point(t["pos"][:2])
        if roads.contains(p) or blds.contains(p):
            errs.append(f"tree {t['id']} on a road or in a building")
        z = float(T.height_at(L, *t["pos"][:2])[0])
        if not (-0.25 <= t["pos"][2] - z <= 0.0):
            errs.append(f"tree {t['id']} z {t['pos'][2]} vs terrain {z:.2f} (floating or deeply sunk)")
    for vb in L["vegetation_blocks"]:
        if vb.get("blocks_vision") and "dense" not in json.dumps(vb).lower():
            errs.append(f"{vb['id']}: vision-blocking vegetation not specified as dense to the ground")
    rep.check("G01", errs[:30], f"{len(L['trees']['instances'])} trees: deciduous species only inside the playable area, none on roads "
                                "or in buildings, all on the terrain; vision-blocking shrubs specified dense to the ground")
    errs = []
    pb = L["performance_budget_browser"]
    dc = pb["draw_calls_worst_view"]
    if sum(dc["split"].values()) > dc["budget"] or dc["budget"] > 450:
        errs.append(f"draw-call split {sum(dc['split'].values())} vs budget {dc['budget']} (<= 450)")
    tr = pb["triangles_visible"]
    if sum(tr["split"].values()) > tr["budget"] or tr["budget"] > 2_000_000:
        errs.append(f"triangle split {sum(tr['split'].values())} vs budget {tr['budget']} (<= 2 M)")
    if "KTX2" in pb.get("textures", "") and "no KTX2" not in pb["textures"]:
        errs.append("KTX2 textures conflict with decision D3")
    if "NOT TESTED" not in pb["target"]:
        errs.append("performance budget must state that PERF-01 is NOT TESTED until measured")
    ti = pb["trees"]
    if ti["inside_soft_boundary"] + ti["outside_within_25_m"] + ti["outside_beyond_25_m"] != len(L["trees"]["instances"]):
        errs.append("tree counts inconsistent")
    rep.check("P01", errs, f"browser budget: {sum(dc['split'].values())} <= {dc['budget']} draw calls, {sum(tr['split'].values()):,} <= "
                           f"{tr['budget']:,} triangles; {ti['outside_beyond_25_m']} of {len(L['trees']['instances'])} trees impostor-only; "
                           "no KTX2; PERF-01 declared NOT TESTED")
    errs = []
    cps = L["cover_points"]["points"]
    for cp in cps:
        for k in ("facing_deg", "capacity", "peek", "height"):
            if k not in cp:
                errs.append(f"cover point {cp['id']} lacks {k}")
                break
    for z in L["capture_zones"]:
        n = sum(1 for cp in cps if z["id"] in cp["zones"])
        if n < 40:
            errs.append(f"{z['id']}: only {n} cover points within 30 m")
    ai = L["ai_navigation"]
    for k in ("perception", "doors", "stuck_recovery", "spawn_selection", "agent"):
        if k not in ai:
            errs.append(f"ai_navigation.{k} missing")
    if ai.get("perception", {}).get("max_range_m", 999) > 150:
        errs.append("AI perception cap > 150 m")
    rc = ai["agent"].get("recast", {})
    if rc.get("cs", 1) * rc.get("walkableRadius_cells", 0) < CAPSULE_R - EPS:
        errs.append("recast walkable radius smaller than the capsule")
    if rc.get("cs", 1) > 0.05 + EPS:
        errs.append(f"recast cell size {rc.get('cs')} > 0.05 (a 0.10 bake pinches the 1.10 m stair corridors)")
    rep.check("A01", errs, f"{len(cps)} cover points with facing_deg/peek/capacity (>= 40 per zone), AI perception capped at 150 m, "
                           "door reservation/door_link policy, stuck recovery, spawn risk scoring, Recast radius >= capsule")
    errs = []
    qa = L["qa_points"]
    kinds = defaultdict(int)
    for p in qa:
        kinds[p["kind"]] += 1
    ids = {p["id"] for p in qa}
    for z in L["capture_zones"]:
        if f"QA_{z['id']}_center" not in ids:
            errs.append(f"QA point for {z['id']} missing")
    for sa in L["spawn_areas"]:
        for p in sa["candidate_points"]:
            if f"QA_{p['id']}" not in ids:
                errs.append(f"QA point for spawn {p['id']} missing")
    for b in B["buildings"]:
        for o in b["openings"]:
            if o["type"] in ("door", "double_door") and f"QA_{o['id']}_L" not in ids:
                errs.append(f"QA doorway point for {o['id']} missing")
        for s in b["stairs"] + b["exterior_stairs"]:
            if f"QA_{s['id']}_bottom" not in ids or f"QA_{s['id']}_top" not in ids:
                errs.append(f"QA stair points for {s['id']} missing")
    for bp in L["buildings"]:
        bd = next(b for b in B["buildings"] if b["id"] == bp["id"])
        if bp.get("zone") and any(l_["floor_z"] > 0 for l_ in bd["levels"] if any(r_["level"] == l_["id"] for r_ in bd["rooms"])):
            if not any(p["kind"] == "zone_z" and p["id"].startswith(f"QA_{bp['zone']}_above_") for p in qa):
                errs.append(f"QA z-band point (upper floor above {bp['zone']}) missing")
    rep.check("Q01", errs, f"{len(qa)} QA points ({dict(kinds)}) cover every zone (incl. z-band tests above it), spawn point, doorway, "
                           "stair and chokepoint")
    # Q02: the 'testovací body' list in Docs/MAP_DESIGN.md is generated from qa_points (draw_plans.py) and must match them
    errs = []
    doc = os.path.join(ROOT, "Docs", "MAP_DESIGN.md")
    if not os.path.exists(doc):
        errs.append("Docs/MAP_DESIGN.md missing")
    else:
        t = open(doc, encoding="utf-8").read()
        a, b = t.find("<!-- QA_POINTS:BEGIN -->"), t.find("<!-- QA_POINTS:END -->")
        if a < 0 or b < a:
            errs.append("Docs/MAP_DESIGN.md has no generated 'testovací body' section (markers QA_POINTS:BEGIN/END)")
        else:
            doc_ids = set(re.findall(r"`(QA_[A-Za-z0-9_]+)`", t[a:b]))
            if doc_ids != ids:
                errs.append(f"Docs/MAP_DESIGN.md 'testovací body' differ from layout.qa_points: missing {sorted(ids - doc_ids)[:5]}, "
                            f"extra {sorted(doc_ids - ids)[:5]} -- run Tools/level/draw_plans.py")
    rep.check("Q02", errs, "Docs/MAP_DESIGN.md 'testovací body' list matches layout.qa_points one to one")
    nv = L.get("navmesh_validation")
    if not nv:
        rep.warn("N01", "navmesh_validation missing: the Recast bake (Tools/level/nav) has not been merged -- NOT TESTED")
    else:
        errs = []
        if nv.get("level_hash") != level_hash(L, B):
            errs.append("navmesh_validation is stale (level data changed since the bake) -- re-run Tools/level/nav")
        if nv.get("disconnected_entrances"):
            errs.append(f"navmesh: disconnected documented entrances {nv['disconnected_entrances']}")
        for zid, zr in nv.get("balance", {}).items():
            if zr.get("max_over_min", 9) > 1.06:
                errs.append(f"navmesh balance {zid}: max/min {zr['max_over_min']:.3f} > 1.06")
            if zr.get("unreachable", 0):
                errs.append(f"navmesh {zid}: {zr['unreachable']} spawn points without a path")
        rep.check("N01", errs, f"Recast navmesh ({nv.get('config', {}).get('cs')} m cells, radius {nv.get('config', {}).get('walkableRadius_cells')} "
                               f"cells): all documented entrances connected, spawn -> zone path balance max/min <= 1.06 "
                               f"({ {k: v.get('max_over_min') for k, v in nv.get('balance', {}).items()} })")


# ================================================================================================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fast", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--layout", default=LAYOUT)
    ap.add_argument("--buildings", default=BUILDINGS)
    a = ap.parse_args()
    t0 = time.time()
    rep = Report(a.verbose)
    L = json.load(open(a.layout))
    B = json.load(open(a.buildings))
    rules = json.load(open(RULES))
    mv = json.load(open(MOVEMENT))
    if abs(mv["capsule"]["radius"] - CAPSULE_R) > 1e-9 or abs(mv["maxStepHeight"] - MAX_STEP) > 1e-9 or abs(mv["maxSlopeDeg"] - MAX_SLOPE) > 1e-9:
        rep.fail("C00", "checker limits differ from Web/src/data/movement.json")
    check_schema(L, B, rules, rep)
    check_terrain(L, rep, a.fast)
    rep.sec("2. Buildings (buildings.json, local frames)")
    for bd in B["buildings"]:
        check_building(bd, rep)
        check_rooms_closed_and_reachable(bd, rep)

    def H_at(x, y):
        return T.height_at(L, x, y)[0]
    check_placement(L, B, H_at, rep)
    if not a.fast:
        W = Walk(L, B)
        rep.info(f"walk raster 0.25 m built in {W.t:.0f} s")
        check_zones_spawns(L, B, W, rep, rules)
        check_los(L, B, W, rep)
        check_misc(L, B, W, rep)
    else:
        rep.warn("FAST", "--fast: raster, balance, LOS and misc checks skipped (not an acceptance run)")
    print(f"\n== SUMMARY: {len(rep.passes)} PASS, {len(rep.fails)} FAIL, {len(rep.warns)} WARN ({time.time() - t0:.0f} s)")
    sys.exit(1 if rep.fails else 0)


if __name__ == "__main__":
    main()
