"""
build_level.py -- authoring script for the IRON VALLEY map "Kalné Hamry" (final design, lead-designer merge).
Writes Shared/level/layout.json and Shared/level/buildings.json.  Deterministic (seeded, no wall-clock input).

Run from anywhere:   python3 IronValley/Tools/level/build_level.py
Then:                python3 IronValley/Tools/level/check_layout.py      (must exit 0)
                     python3 IronValley/Tools/level/draw_plans.py
Optional nav bake:   see Tools/level/nav/ (Recast, Node) -- results are merged into layout.json by nav/merge_nav.py
"""
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "lib"))
import ivterrain as T          # noqa: E402
import ivbuildings as IB       # noqa: E402

ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))          # IronValley/
OUT = os.path.join(ROOT, "Shared", "level")
WORK = os.path.join(HERE, "_out")
os.makedirs(OUT, exist_ok=True)
os.makedirs(WORK, exist_ok=True)


def r2(v):
    return round(float(v), 2)


def r3(v):
    return round(float(v), 3)


def xf(c, rot_deg, p):
    """building/prop local -> world XY"""
    a = math.radians(rot_deg)
    return [c[0] + p[0] * math.cos(a) - p[1] * math.sin(a), c[1] + p[0] * math.sin(a) + p[1] * math.cos(a)]


def xf_poly(c, rot, pts):
    return [[r2(q[0]), r2(q[1])] for q in (xf(c, rot, p) for p in pts)]


def rect_local(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def offset_polyline(pl, off):
    """offset a polyline to the LEFT by `off` (negative = right); miter at vertices."""
    pts = np.array(pl, dtype=float)
    out = []
    n = len(pts)
    for i in range(n):
        if i == 0:
            d = pts[1] - pts[0]
        elif i == n - 1:
            d = pts[-1] - pts[-2]
        else:
            d1 = pts[i] - pts[i - 1]
            d2 = pts[i + 1] - pts[i]
            d = d1 / np.linalg.norm(d1) + d2 / np.linalg.norm(d2)
        d = d / np.linalg.norm(d)
        nrm = np.array([-d[1], d[0]])
        out.append(pts[i] + nrm * off)
    return [[r2(p[0]), r2(p[1])] for p in out]


def resample(pl, s0, s1, step=None):
    """sub-polyline between arc lengths s0..s1 (keeps interior vertices)"""
    pts = np.array(pl, dtype=float)
    seg = np.hypot(*np.diff(pts, axis=0).T)
    cs = np.concatenate([[0], np.cumsum(seg)])

    def at(s):
        k = np.searchsorted(cs, s) - 1
        k = int(np.clip(k, 0, len(seg) - 1))
        t = (s - cs[k]) / seg[k]
        return pts[k] + t * (pts[k + 1] - pts[k])
    res = [at(s0)]
    for k in range(1, len(pts) - 1):
        if s0 < cs[k] < s1:
            res.append(pts[k])
    res.append(at(s1))
    return [[r2(p[0]), r2(p[1])] for p in res]


def polyline_len(pl):
    pts = np.array(pl, dtype=float)
    return float(np.hypot(*np.diff(pts, axis=0).T).sum())


GRID = T.make_base_grid()


def base_h(x, y):
    return T.sample_grid(GRID, np.atleast_1d(np.asarray(x, float)), np.atleast_1d(np.asarray(y, float)))


def profile_z(pl, dz=0.0, smooth=15.0, monotonic=None, fixed=None, step=1.0):
    """z per vertex = moving average (window `smooth` m) of the base terrain along the polyline + dz.
    monotonic: 'dec'/'inc' along the polyline.  fixed: {vertex_index: z}"""
    pts = np.array(pl, dtype=float)
    seg = np.hypot(*np.diff(pts, axis=0).T)
    cs = np.concatenate([[0], np.cumsum(seg)])
    ss = np.arange(0, cs[-1] + 1e-9, step)
    xs = np.interp(ss, cs, pts[:, 0])
    ys = np.interp(ss, cs, pts[:, 1])
    hs = base_h(xs, ys)
    k = max(1, int(smooth / step))
    ker = np.ones(2 * k + 1) / (2 * k + 1)
    hp = np.pad(hs, k, mode="edge")
    hsm = np.convolve(hp, ker, mode="valid")
    zv = np.interp(cs, ss, hsm) + dz
    if fixed:
        for i, z in fixed.items():
            zv[i] = z
    if monotonic == "dec":
        for i in range(1, len(zv)):
            zv[i] = min(zv[i], zv[i - 1] - 0.02)
    elif monotonic == "inc":
        for i in range(1, len(zv)):
            zv[i] = max(zv[i], zv[i - 1])
    return [r2(z) for z in zv]


# =================================================================================================
# 0.  Key design constants
# =================================================================================================
Z_HUB = 0.30
DILNA = {"c": [-32.0, 24.0], "rot": 240.0, "floor": 1.30}
SKLAD = {"c": [42.0, 16.0], "rot": 90.0, "floor": 2.40}
DUM = {"c": [-8.0, -40.0], "rot": 350.0, "floor": 2.94}
Z_DILNA_PAD = DILNA["floor"] - 0.17          # 1.13 (one 0.17 riser at every door)
Z_TERRACE_DILNA = Z_DILNA_PAD + 2.00          # 3.13  (mill-race terrace behind the retaining wall)
Z_SKLAD_YARD = SKLAD["floor"] - 1.10          # 1.30
Z_SKLAD_REAR = SKLAD["floor"] - 0.05          # 2.35
Z_TERRACE_DUM = DUM["floor"] - 0.54           # 2.40


def DLw(p):
    return xf(DILNA["c"], DILNA["rot"], p)


def SKw(p):
    return xf(SKLAD["c"], SKLAD["rot"], p)


def DMw(p):
    return xf(DUM["c"], DUM["rot"], p)


# =================================================================================================
# 1.  Roads, tracks, paths, brook, ditches
# =================================================================================================
RA_XY = [[0, 0], [-22, -9], [-44, -18], [-62, -22], [-80, -22], [-100, -32], [-120, -44], [-148, -56], [-180, -68]]
RB_XY = [[0, 0], [5, 20], [10, 42], [14, 58], [8, 74], [0, 90], [4, 108], [14, 128], [22, 150], [30, 178]]
TC_XY = [[3, -3], [18, -14], [32, -26], [44, -40], [52, -58], [66, -70], [84, -80], [104, -91], [126, -106], [152, -128], [178, -150]]

RA_Z = profile_z(RA_XY, fixed={0: Z_HUB, 1: 0.10})
RA_Z = [RA_Z[0], RA_Z[1]] + [min(z, RA_Z[i]) for i, z in enumerate(RA_Z) if i >= 2]
RB_Z = profile_z(RB_XY, fixed={0: Z_HUB}, monotonic="inc")
TC_Z = profile_z(TC_XY, fixed={0: Z_HUB}, monotonic="inc")
RA_Z = [r2(z) for z in RA_Z]


def with_z(xy, zs):
    return [[p[0], p[1], z] for p, z in zip(xy, zs)]



# the brook: Kalný potok (flows N -> WSW)
BROOK_XY = [[-14, 178], [-16, 150], [-22, 125], [-18, 100], [-16, 78], [-15, 58], [-14, 40], [-13, 24], [-16, 11],
            [-26, 3], [-42, -3], [-62, -6], [-86, -10], [-110, -20], [-140, -34], [-180, -50]]
BROOK_BED = profile_z(BROOK_XY, dz=-1.65, smooth=12, monotonic="dec")
# keep the bed at the village 1.5-2.4 m below the banks
BROOK = with_z(BROOK_XY, BROOK_BED)

# bridge geometry (main bridge at the square)
def perp_bridge(center, brook_dir, length, width):
    d = np.array(brook_dir, float)
    d /= np.linalg.norm(d)
    ax = np.array([-d[1], d[0]])       # left of flow
    a = np.array(center) + ax * length / 2
    b = np.array(center) - ax * length / 2
    return [[r2(a[0]), r2(a[1])], [r2(b[0]), r2(b[1])]]


BR_MAIN = perp_bridge([-14.5, 17.5], [-3, -13], 11.0, 4.5)        # [hub-side?, ...] computed below
BR_FOOT_A = perp_bridge([-58.0, -5.4], [-20, -3], 9.0, 1.5)
BR_FOOT_B = perp_bridge([-14.8, 58.0], [1, -18], 9.0, 1.5)

# ditch along the SW side of track C (drains to a culvert at the square)
TC_LEN = polyline_len(TC_XY)
DITCH_C_XY = offset_polyline(resample(TC_XY, 14.0, 98.0), -3.9)
DITCH_C_Z = [r2(z) for z in (np.array(profile_z(resample(TC_XY, 14.0, 98.0), smooth=6)) - 0.85)]
# ditch along the S side of road A
DITCH_A_XY = offset_polyline(resample(RA_XY, 30.0, 104.0), -5.3)
DITCH_A_Z = [r2(z) for z in (np.array(profile_z(resample(RA_XY, 30.0, 104.0), smooth=6)) - 0.80)]

# dry mill race (náhon) along the NW slope, ends on the terrace behind the workshop
MILL_XY = [DLw((13.0, -15.0)), DLw((-17.0, -15.0)), [-30.0, 52.0], [-29.0, 70.0], [-27.5, 92.0], [-25.5, 112.0], [-22.6, 116.3]]
MILL_XY = [[r2(p[0]), r2(p[1])] for p in MILL_XY]
MILL_DEPTH = 1.00
# bed = 1.00 m below the smoothed ground (terrace pad on the terrace part), rising upstream (list order = upstream)
_mz = profile_z(MILL_XY, dz=-MILL_DEPTH, smooth=10.0)
_mz[0] = r2(Z_TERRACE_DILNA - MILL_DEPTH)
_mz[1] = r2(Z_TERRACE_DILNA - MILL_DEPTH + 0.03)
for _i in range(2, len(_mz)):
    _mz[_i] = r2(max(_mz[_i], _mz[_i - 1] + 0.05))
MILL_Z = _mz

# footpaths (surface + light flattening only)
PATHS = {
    "P_MILLRACE": {"xy": [DLw((12.0, -12.4)), DLw((-17.5, -12.4)), [-27.0, 51.0], [-26.0, 70.0], [-24.5, 88.0]],
                   "width": 1.4, "surface": "dirt", "role": "NW ring/flank: arm B <-> rear of the workshop (terrace behind the retaining wall)"},
    "P_BANK_A": {"xy": [[-58.8, -0.8], [-52.0, 4.0], DLw((14.5, 6.0)), DLw((13.0, 9.0))], "width": 1.4, "surface": "dirt",
                 "role": "footbridge A -> brook north bank -> workshop yard (SW)"},
    "P_BANK_TERRACE": {"xy": [[-52.0, 4.0], DLw((15.0, -6.8)), DLw((15.0, -12.4)), DLw((12.0, -12.4))], "width": 1.2, "surface": "dirt",
                       "role": "brook bank -> ramp up to the SW end of the mill-race terrace"},
    "P_FOOT_A_ROAD": {"xy": [[-57.3, -9.9], [-56.5, -20.2]], "width": 1.4, "surface": "gravel", "role": "road A -> footbridge A"},
    "P_FOOT_B": {"xy": [[13.2, 58.0], [0.0, 58.4], [-10.3, 58.25]], "width": 1.4, "surface": "dirt", "role": "road B -> footbridge B"},
    "P_FOOT_B_W": {"xy": [[-19.3, 57.75], [-27.0, 57.0]], "width": 1.2, "surface": "dirt", "role": "footbridge B -> mill-race path"},
    "P_BANK_B": {"xy": [[-19.3, 57.75], [-19.5, 45.0], DLw((-14.5, 4.0)), DLw((-12.2, 0.7))], "width": 1.2, "surface": "dirt",
                 "role": "footbridge B -> brook west bank -> workshop gable door DL_D3 (NNE)"},
    "P_E_RING": {"xy": [[14.5, 60.0], [30.0, 52.0], [47.0, 42.0], [61.0, 33.0], [61.3, 16.0], [61.0, 0.0], [56.0, -17.0], [47.0, -30.0], [44.5, -39.0]],
                 "width": 1.6, "surface": "dirt", "role": "E ring/flank: arm B <-> arm C behind the warehouse (hedgerow side)"},
    "P_S_RING": {"xy": [[46.0, -42.0], [40.0, -57.0], [16.0, -61.5], [-8.0, -60.0], [-26.0, -56.5], [-44.0, -47.0], [-54.0, -36.0], [-59.0, -24.0]],
                 "width": 1.6, "surface": "dirt", "role": "S ring/flank: arm C <-> arm A behind the house (field / wood edge)"},
    "P_DUM_W": {"xy": [[-40.0, -21.0], [-30.0, -24.5], DMw((-16.5, 3.0)), DMw((-13.0, 3.0))], "width": 1.2, "surface": "gravel",
                "role": "road A -> garden gate on the terrace west edge"},
    "P_DUM_S": {"xy": [DMw((-1.0, -16.5)), DMw((-1.0, -13.5))], "width": 1.2, "surface": "gravel", "role": "S ring -> rear yard gate"},
    "P_SKLAD_S": {"xy": [[37.5, -32.0], [34.5, -14.0], [29.5, 0.5]], "width": 1.4, "surface": "gravel", "role": "track C -> warehouse yard (S)"},
}
for p in PATHS.values():
    p["xy"] = [[r2(q[0]), r2(q[1])] for q in p["xy"]]

# =================================================================================================
# 2.  Terrain stamps
# =================================================================================================
pads = []


def pad(pid, poly, z, blend, surface=None):
    pads.append({"kind": "pad", "id": pid, "polygon": [[r2(p[0]), r2(p[1])] for p in poly], "z": r2(z), "blend": blend,
                 **({"surface": surface} if surface else {})})


# village square (paved junction); its south edge follows the house terrace retaining wall
RW_DUM_XY = [DMw((-15.0, 22.5)), DMw((-1.75, 22.5)), DMw((-0.25, 22.5)), DMw((13.0, 22.5))]
pad("PAD_NAVES", [[-21, -13.2], [-21, 2], [-12, 12.5], [-6.5, 16.5], [4, 16.5], [13, 8], [15.5, -5], [11, -18.2], [5.0, -19.3], [-10, -16.6]],
    Z_HUB, 7.0, "paving_granite_setts")
# workshop: building + yard + rear pad
pad("PAD_DILNA_TERRACE", xf_poly(DILNA["c"], DILNA["rot"], rect_local(-17.5, -16.5, 13.5, -9.25)), Z_TERRACE_DILNA, 5.0, "grass")
pad("PAD_DILNA", xf_poly(DILNA["c"], DILNA["rot"], rect_local(-14.0, -9.25, 15.5, 12.0)), Z_DILNA_PAD, 4.0, "gravel")
# warehouse: front yard (low), building + rear yard (high)
pad("PAD_SKLAD_YARD", [[13.0, -1.0], [31.25, -1.0], [31.25, 36.0], [13.0, 36.0]], Z_SKLAD_YARD, 4.0, "concrete")
pad("PAD_SKLAD", xf_poly(SKLAD["c"], SKLAD["rot"], rect_local(-15.25, -14.0, 15.25, 7.75)), Z_SKLAD_REAR, 3.0, "gravel")
# house terrace (front garden + house + rear yard)
pad("PAD_DUM_TERRACE", xf_poly(DUM["c"], DUM["rot"], rect_local(-15.0, -13.5, 17.0, 22.5)), Z_TERRACE_DUM, 5.0, "grass")
# bridge abutment aprons
pad("PAD_BR_MAIN_W", xf_poly([BR_MAIN[1][0], BR_MAIN[1][1]], 0, rect_local(-2.5, -2.5, 2.5, 2.5)), Z_DILNA_PAD, 2.0)

stamps = list(pads)
# ditches first (so roads crossing them keep their bed = culverts)
stamps.append({"kind": "ditch", "id": "DITCH_C", "polyline": with_z(DITCH_C_XY, DITCH_C_Z), "bed_width": 0.5,
               "bank_slope_h_per_v": 1.2})
stamps.append({"kind": "ditch", "id": "DITCH_A", "polyline": with_z(DITCH_A_XY, DITCH_A_Z), "bed_width": 0.5,
               "bank_slope_h_per_v": 1.2})
# sunken lane (úvoz) on the central part of the S ring path behind the house: covered flank lane, exits every <= 20 m
UVOZ_XY = [[40.0, -57.0], [16.0, -61.5], [-8.0, -60.0], [-26.0, -56.5]]
UVOZ_DEPTH = 1.80
UVOZ_LEN = polyline_len(UVOZ_XY)


def _uvoz_bed():
    pts = np.array(UVOZ_XY, float)
    seg = np.hypot(*np.diff(pts, axis=0).T)
    cs = np.concatenate([[0], np.cumsum(seg)])
    ss = np.arange(0.0, cs[-1] + 1e-9, 2.0)
    if ss[-1] < cs[-1]:
        ss = np.append(ss, cs[-1])
    xs = np.interp(ss, cs, pts[:, 0])
    ys = np.interp(ss, cs, pts[:, 1])
    g = base_h(xs, ys)
    k = 5
    gp = np.pad(g, k, mode="edge")
    gs = np.convolve(gp, np.ones(2 * k + 1) / (2 * k + 1), mode="valid")
    depth = UVOZ_DEPTH * np.minimum(1.0, np.minimum(ss, cs[-1] - ss) / 12.0)
    return [[r2(x), r2(y), r2(z - d)] for x, y, z, d in zip(xs, ys, gs, depth)]


UVOZ_POLY = _uvoz_bed()
UVOZ_EXITS = [{"s0": 14.5, "s1": 18.0, "side": "left", "bank_slope_h_per_v": 1.6, "taper": 1.5, "to": "S spur field"},
              {"s0": 31.5, "s1": 35.0, "side": "right", "bank_slope_h_per_v": 1.6, "taper": 1.5, "to": "hedge gap S of the house rear yard"},
              {"s0": 50.5, "s1": 54.5, "side": "right", "bank_slope_h_per_v": 1.6, "taper": 1.5, "to": "rear yard gate path P_DUM_S"}]
stamps.append({"kind": "sunken_lane", "id": "UVOZ_S", "polyline": UVOZ_POLY, "bed_width": 2.6, "bank_slope_h_per_v": 0.7,
               "exits": UVOZ_EXITS,
               "note": "úvoz: old cart lane worn 1.8 m into the loess of the S spur; steep rooty banks (55 deg, not walkable), "
                       "walkable ends (depth tapers to 0 over 12 m) and 3 side exits (32 deg ramps) -> an exit at most every 19 m"})
# roads / tracks / driveway
DRIVE = [[20.5, -15.2, r2(float(np.interp(polyline_len([TC_XY[0], TC_XY[1]]) + 3.7, [0, polyline_len([TC_XY[0], TC_XY[1]])], [TC_Z[0], TC_Z[1]])))],
         [12.0, -24.5, Z_TERRACE_DUM]]
stamps.append({"kind": "road", "id": "ROAD_A", "polyline": with_z(RA_XY, RA_Z), "width": 6.0, "shoulder": 0.75, "blend": 4.0})
stamps.append({"kind": "road", "id": "ROAD_B", "polyline": with_z(RB_XY, RB_Z), "width": 6.0, "shoulder": 0.75, "blend": 4.0})
stamps.append({"kind": "road", "id": "TRACK_C", "polyline": with_z(TC_XY, TC_Z), "width": 3.6, "shoulder": 0.5, "blend": 3.0})
stamps.append({"kind": "road", "id": "DRIVE_DUM", "polyline": DRIVE, "width": 3.2, "shoulder": 0.3, "blend": 3.0})
RAMP_TERRACE_SW = [[r2(DLw((15.0, -7.0))[0]), r2(DLw((15.0, -7.0))[1]), Z_DILNA_PAD],
                   [r2(DLw((15.0, -12.2))[0]), r2(DLw((15.0, -12.2))[1]), Z_TERRACE_DILNA]]
stamps.append({"kind": "road", "id": "RAMP_TERRACE_SW", "polyline": RAMP_TERRACE_SW, "width": 2.0, "shoulder": 0.2, "blend": 2.5,
               "note": "grassed ramp beside the SW end of RW_DILNA: rear pad <-> mill-race terrace (2.0 m over 5.2 m = 21 deg)"})
RAMP_SKLAD_E = [[54.5, 17.0, Z_SKLAD_REAR], [67.5, 17.0, 7.60]]
stamps.append({"kind": "road", "id": "RAMP_SKLAD_E", "polyline": RAMP_SKLAD_E, "width": 5.0, "shoulder": 0.3, "blend": 4.0,
               "note": "field access ramp from the warehouse rear yard up to the E ring path (22 deg), through the hedge gaps"})
# retaining walls (exact step)
RW_DILNA_XY = [[r2(p[0]), r2(p[1])] for p in (DLw((13.5, -9.25)), DLw((-17.5, -9.25)))]
stamps.append({"kind": "wall", "id": "RW_DILNA", "polyline": RW_DILNA_XY, "top_z": [Z_TERRACE_DILNA, Z_TERRACE_DILNA],
               "bottom_z": [Z_DILNA_PAD, Z_DILNA_PAD], "high_side": "left", "set_high": 3.0, "blend_high": 3.0,
               "set_low": 4.3, "blend_low": 0.5})
RW_DUM_STAMP_XY = [[r2(p[0]), r2(p[1])] for p in (DMw((-15.0, 22.5)), DMw((13.0, 22.5)))]
stamps.append({"kind": "wall", "id": "RW_DUM", "polyline": RW_DUM_STAMP_XY, "top_z": [Z_TERRACE_DUM, Z_TERRACE_DUM],
               "bottom_z": [Z_HUB, Z_HUB], "high_side": "right", "set_high": 3.0, "blend_high": 2.0,
               "set_low": 2.0, "blend_low": 3.0})
# stair ramps AFTER the wall stamps (terrain under each stair mesh follows its pitch line)
WST_B = DMw((-1.0, 22.75))
WST_T = DMw((-1.0, 22.75 - 11 * 0.28))
stamps.append({"kind": "road", "id": "RAMP_UNDER_ST_RW_DUM", "polyline": [[r2(WST_B[0]), r2(WST_B[1]), Z_HUB],
                                                                          [r2(WST_T[0]), r2(WST_T[1]), Z_TERRACE_DUM]],
               "width": 1.5, "shoulder": 0.0, "blend": 0.01, "note": "terrain under stair ST_RW_DUM follows the pitch line"})
DST_B = DLw((-13.0, -8.95))
DST_T = DLw((-13.0, -8.95 - 10 * 0.28))
stamps.append({"kind": "road", "id": "RAMP_UNDER_ST_RW_DILNA", "polyline": [[r2(DST_B[0]), r2(DST_B[1]), Z_DILNA_PAD],
                                                                            [r2(DST_T[0]), r2(DST_T[1]), Z_TERRACE_DILNA]],
               "width": 1.4, "shoulder": 0.0, "blend": 0.01, "note": "terrain under stair ST_RW_DILNA follows the pitch line"})
# brook channel last
stamps.append({"kind": "channel", "id": "BROOK", "polyline": BROOK, "bed_width": 1.6, "bank_slope_h_per_v": 1.5,
               "vertical_sections": []})
stamps.append({"kind": "ditch", "id": "MILLRACE", "polyline": with_z(MILL_XY, MILL_Z), "bed_width": 0.8,
               "bank_slope_h_per_v": 1.2, "note": "dry, overgrown mill race (náhon), ~1.0 m deep, grassed banks 1:1.2 (39.8 deg, walkable "
                                                "along its whole length) = crouch flank lane from footbridge B to the terrace behind the workshop"})


def brook_s_at(pt):
    d, _, s, _ = T.polyline_query(np.array([pt[0]]), np.array([pt[1]]), BROOK_XY)
    return float(s[0])


s_main = brook_s_at([-14.5, 17.5])
stamps[-2]["vertical_sections"] = [{"s0": r2(s_main - 4.0), "s1": r2(s_main + 4.0), "half_width": 2.4,
                                    "note": "masonry abutments at the main bridge"}]

# =================================================================================================
# 3.  Terrain bake helpers (need a provisional layout to sample heights for props/buildings)
# =================================================================================================
LAYOUT = {"terrain": {"base_grid": {"heights": GRID.tolist()}, "stamps": stamps}}


def gz(x, y):
    return float(T.height_at(LAYOUT, x, y)[0])


# =================================================================================================
# 4.  Buildings (main + secondary)
# =================================================================================================
main_buildings = [
    {"id": "B_DILNA", "type": "dilna", "position": [DILNA["c"][0], DILNA["c"][1], DILNA["floor"]], "rotation_deg": DILNA["rot"],
     "footprint": [23.0, 10.0], "enterable": True, "levels": 2, "zone": "zone_dilna", "pad": "PAD_DILNA",
     "front_faces_compass_deg": r2((90 - (DILNA["rot"] + 90)) % 360)},
    {"id": "B_SKLAD", "type": "mensi_sklad", "position": [SKLAD["c"][0], SKLAD["c"][1], SKLAD["floor"]], "rotation_deg": SKLAD["rot"],
     "footprint": [24.5, 15.5], "enterable": True, "levels": 1, "zone": "zone_sklad", "pad": "PAD_SKLAD"},
    {"id": "B_DUM", "type": "obytny_dum", "position": [DUM["c"][0], DUM["c"][1], DUM["floor"]], "rotation_deg": DUM["rot"],
     "footprint": [11.0, 9.5], "enterable": True, "levels": 2, "zone": "zone_dvur", "pad": "PAD_DUM_TERRACE"},
]
for b in main_buildings:
    a = math.radians(b["rotation_deg"])
    fx, fy = -math.sin(a), math.cos(a)
    b["front_faces_compass_deg"] = r2(math.degrees(math.atan2(fx, fy)) % 360)
    b["footprint_world"] = xf_poly(b["position"][:2], b["rotation_deg"], rect_local(-b["footprint"][0] / 2, -b["footprint"][1] / 2,
                                                                                   b["footprint"][0] / 2, b["footprint"][1] / 2))

SEC = []


def sec(sid, typ, name, c, rot, fp, h_eave, roof, ridge, enterable=False, note=None, surface_z=None, extra=None):
    z = None if surface_z is None else r2(surface_z)
    d = {"id": sid, "type": typ, "name": name, "position": [r2(c[0]), r2(c[1]), z], "rotation_deg": rot, "footprint": fp,
         "eave_height": h_eave, "roof": roof, "ridge_height": ridge, "enterable": enterable,
         "reads_closed_by": note or "",
         "footprint_world": xf_poly(c, rot, rect_local(-fp[0] / 2, -fp[1] / 2, fp[0] / 2, fp[1] / 2))}
    if extra:
        d.update(extra)
    SEC.append(d)


sec("S_TRAFO", "transformer_tower", "Trafostanice (zděná věž)", [-6.0, 9.5], 20, [3.2, 3.2], 8.6, "pyramid", 10.2,
    note="steel doors with high-voltage signs, padlocked; no windows below 6 m")
sec("S_KAPLE", "chapel", "Kaplička sv. Floriána (fiktivní)", [21.5, -7.5], 55, [4.2, 5.6], 4.2, "gable_with_bell_turret", 7.6,
    note="locked wooden door with iron grille; tiny grilled windows")
sec("S_ZASTAVKA", "bus_shelter", "Autobusová zastávka", [-13.0, -11.4], 22.3, [4.2, 1.8], 2.5, "flat", 2.6, enterable=True,
    note="open-front concrete shelter (walk-in, 3 walls); back wall 1.8 m = high cover")
sec("S_GARAZE", "garage_row", "Řadové garáže (3 boxy)", [-44.0, -30.0], 12, [9.6, 6.2], 2.7, "flat", 2.8,
    note="closed up-and-over steel doors, rusted, padlocked")
sec("S_HOSPODA", "pub_boarded", "Hostinec U Hamru (zavřený)", [-82.0, -35.6], 0, [14.0, 9.0], 6.4, "gable", 10.4,
    note="windows boarded with weathered OSB, door chained, 'ZAVŘENO' sign; beer-garden fence to the east")
sec("S_KULNA", "shed", "Kůlna u hostince", [-95.0, -44.0], 20, [7.0, 4.5], 3.0, "mono", 3.6, note="closed timber doors")
sec("S_HASICI", "fire_station", "Hasičská zbrojnice", [19.0, 80.0], 90, [10.0, 8.0], 5.2, "gable", 8.0,
    note="closed garage doors; hose tower 3x3x12 m at the rear (see extra)",
    extra={"tower": {"offset_local": [3.5, -2.5], "size": [3.0, 3.0], "height": 12.0, "enterable": False}})
sec("S_KULNA_DUM", "shed", "Kůlna na nářadí u domu", DMw((14.5, 10.0)), DUM["rot"], [3.4, 6.2], 2.6, "mono", 2.9,
    surface_z=Z_TERRACE_DUM, note="closed plank shed (nářaďovna) with a padlocked double door facing the driveway")
sec("S_DREVNIK", "woodshed", "Dřevník", DMw((-9.5, -9.6)), DUM["rot"], [5.0, 2.2], 2.1, "mono", 2.5, surface_z=Z_TERRACE_DUM,
    note="open front but filled with stacked logs to 1.9 m: solid block, not enterable")
sec("S_SENIK", "hay_barn", "Seník (kryté stohování balíků)", [61.2, -46.8], 40, [12.0, 8.0], 5.0, "gable", 6.8,
    note="open-sided roof on posts, packed with square bales to 4.5 m (solid block)")
sec("S_STODOLA", "barn", "Stodola statku", [146.0, -100.0], 40, [22.0, 12.0], 6.0, "gable", 11.0,
    note="big closed timber doors; outside the playable boundary behind spawn C")
sec("S_KOLNA_STROJE", "machinery_shed", "Kolna na stroje (otevřená)", [118.0, -125.0], 40, [15.0, 6.0], 4.2, "mono", 4.8,
    note="open front with a tractor and a trailer inside; 5 m behind spawn C back row, soft boundary crosses it")
sec("S_STERKOVNA", "gravel_works_office", "Kancelář štěrkovny (kontejner)", [44.0, 150.0], 15, [6.0, 2.5], 2.6, "flat", 2.7,
    note="office container, door locked, barred windows")
sec("S_DOMEK_1", "house_closed", "Uzavřený domek (čp. fiktivní 12)", [30.0, 66.0], 90, [9.0, 8.0], 3.2, "gable", 7.4,
    note="single-storey + attic cottage, shutters closed, door locked; front garden picket fence; variant A (ochre render)")
sec("S_DOMEK_2", "house_closed", "Uzavřený domek u potoka", [-2.5, 34.0], 10, [8.0, 7.0], 3.0, "gable", 6.8,
    note="cottage between road B and the brook, shutters closed; variant B (grey render, eternit roof)")
sec("S_DOMEK_3", "house_closed", "Uzavřený domek u silnice A", [-62.0, -45.0], 0, [9.0, 8.0], 3.2, "gable", 7.6,
    note="cottage south of road A, boarded ground-floor windows; variant C (white render, red tiles)")
sec("S_DOMEK_4", "house_closed", "Uzavřený domek u polní cesty", [27.0, -46.0], 40, [9.0, 8.0], 3.2, "gable", 7.4,
    note="cottage SW of track C, shutters closed; variant A mirrored")
sec("S_KULNA_C", "field_shed", "Polní kůlna (ovčín, zavřená)", [46.0, -74.0], 63, [12.0, 6.0], 3.6, "gable", 5.2,
    note="timber field shed on a stone plinth, doors nailed shut")
sec("S_KIOSK", "kiosk_closed", "Stánek (zavřený, rolety)", [-14.5, 2.5], 25, [4.0, 3.0], 2.8, "flat", 3.0,
    note="closed kiosk with steel roller shutters on the NW corner of the square: breaks the brook-corridor sightline")
sec("S_GARAZ_ZED", "garage_built_into_wall", "Garáž zapuštěná v opěrné zdi domu", DMw((6.5, 19.75)), DUM["rot"], [3.0, 6.0], 2.32,
    "flat_under_garden_deck", 2.32, surface_z=Z_HUB,
    note="only the front in the RW_DUM face is modelled: steel up-and-over door 2.40 x 2.00, closed and padlocked, stone surround",
    extra={"embedded_in": "RW_DUM", "roof_deck_top_z": r2(Z_TERRACE_DUM + 0.22)})
sec("S_PILA_BUDKA", "timber_yard_hut", "Bouda skládky dřeva", [-142.0, -72.0], 25, [4.0, 3.0], 2.4, "mono", 2.8,
    note="closed plank hut behind spawn A")

# =================================================================================================
# 5.  Bridges, retaining walls, fences, hedges, low walls
# =================================================================================================
bridges = [
    {"id": "BR_MAIN", "type": "concrete_road_bridge", "ends": BR_MAIN, "width": 4.5,
     "deck_z": [r2(Z_HUB), r2(Z_DILNA_PAD)], "approach": "flush at both ends (no step), deck ramps 0.83 m over 11 m (4.3 deg)", "railing": {"height": 1.10, "type": "steel_tube_3_rail",
                                                                "blocks_movement": True, "blocks_bullets": False, "blocks_vision": False},
     "role": "square -> workshop yard; the direct lane for the team arriving through the square"},
    {"id": "BR_FOOT_A", "type": "timber_footbridge", "ends": BR_FOOT_A, "width": 1.5,
     "deck_z": None, "railing": {"height": 1.00, "type": "timber_handrail", "blocks_movement": True, "blocks_bullets": False,
                                 "blocks_vision": False}, "role": "arm A crossing to the brook north bank"},
    {"id": "BR_FOOT_B", "type": "timber_footbridge", "ends": BR_FOOT_B, "width": 1.5,
     "deck_z": None, "railing": {"height": 1.00, "type": "timber_handrail", "blocks_movement": True, "blocks_bullets": False,
                                 "blocks_vision": False}, "role": "arm B crossing to the mill-race path / west bank"},
]
for br in bridges:
    if br["deck_z"] is None:
        br["approach"] = "flush: the abutment top and the deck end are level with the bank path (no step)"

# main bridge: which end is on the square side?
e0, e1 = BR_MAIN
if math.hypot(*e0) > math.hypot(*e1):
    bridges[0]["ends"] = [e1, e0]

retaining_walls = [
    {"id": "RW_DILNA", "polyline": RW_DILNA_XY, "thickness": 0.60, "top_z": r2(Z_TERRACE_DILNA + 0.10),
     "bottom_z": Z_DILNA_PAD, "low_side": "SE (workshop rear pad)", "material": "stone_rubble_greywacke_with_concrete_cap",
     "cap": {"height": 0.10, "overhang": 0.05}, "parapet": None,
     "stairs": [{"id": "ST_RW_DILNA", "at_local_of": "B_DILNA", "bottom_center_local": [-13.0, -8.95], "direction": "local -Y (up to NW)",
                 "width": 1.40, "risers": 11, "riser": r3(2.0 / 11), "tread": 0.28, "run": r3(10 * 0.28),
                 "construction": "concrete steps cut into the terrace, side walls follow the pitch",
                 "bottom_center_world": [r2(v) for v in DLw((-13.0, -8.95))],
                 "top_center_world": [r2(v) for v in DLw((-13.0, -8.95 - 10 * 0.28))]}],
     "note": "supports the dry mill-race terrace behind the workshop; its SW end dies out into a 1:3 grassed ramp (path P_BANK_TERRACE)"},
    {"id": "RW_DUM", "polyline": [[r2(p[0]), r2(p[1])] for p in RW_DUM_XY], "segments": [[0, 1], [2, 3]], "thickness": 0.50,
     "top_z": r2(Z_TERRACE_DUM + 0.60), "bottom_z": Z_HUB, "low_side": "N (village square)",
     "material": "stone_rubble_sandstone_with_concrete_cap", "cap": {"height": 0.12, "overhang": 0.05},
     "parapet": {"height_above_terrace": 0.60, "note": "0.60 m garden parapet = crouch cover for defenders; from the square the wall is 2.70 m"},
     "stairs": [{"id": "ST_RW_DUM", "type": "stair_cut_into_terrace", "gap_between_segments": [1, 2], "width": 1.50,
                 "bottom_center_world": [r2(WST_B[0]), r2(WST_B[1])], "top_center_world": [r2(WST_T[0]), r2(WST_T[1])],
                 "risers": 12, "riser": r3((Z_TERRACE_DUM - Z_HUB) / 12), "tread": 0.28, "run": r3(11 * 0.28),
                 "direction": "house-local -Y (up, south into the garden)", "side_walls": "0.30 concrete, top follows pitch + 0.9 m rail",
                 "gate": {"width": 1.2, "state": "open", "type": "steel_garden_gate"}}],
     "embedded_structures": [
         {"id": "S_GARAZ_ZED", "type": "garage_built_into_wall", "local_frame": "B_DUM", "along_local_x": [5.0, 8.0],
          "front_face_local_y": 22.75, "depth": 6.0, "floor_z": Z_HUB, "roof_top_z": r2(Z_TERRACE_DUM + 0.22),
          "door": {"width": 2.40, "height": 2.00, "type": "steel_up_and_over", "state": "closed_padlocked", "enterable": False},
          "note": "1934 garage vaulted into the terrace; only the front (door, stone surround, lintel) is modelled; the roof is a "
                  "0.22 m raised concrete deck in the front garden (walkable, step < 0.40) carrying a hedge planter"}],
     "outlets": [{"local_x": -8.0, "z": r2(Z_HUB + 0.40), "type": "stone_spout_pvc110", "serves": "DM_DP3"},
                 {"local_x": 10.5, "z": r2(Z_HUB + 0.40), "type": "stone_spout_pvc110", "serves": "DM_DP4"}],
     "weep_holes": "PVC 50 every 2.0 m, 0.30 m above the square",
     "note": "terrace wall of the house garden facing the village square"},
]

# fences (see-through, movement-blocking), hedges (vision-blocking only), low walls (cover)
FENCES = []


def fence(fid, typ, pl, h, blocks_bullets=False, blocks_vision=False, note=None):
    FENCES.append({"id": fid, "type": typ, "polyline": [[r2(p[0]), r2(p[1])] for p in pl], "height": h,
                   "blocks_movement": True, "blocks_bullets": blocks_bullets, "blocks_vision": blocks_vision,
                   "cover": "low" if (blocks_bullets and 0.8 <= h < 1.6) else ("high" if blocks_bullets and h >= 1.6 else "none"),
                   **({"note": note} if note else {})})


fence("F_SKLAD_ROAD_S", "chain_link_2m", [[12.5, -1.0], [12.5, 13.5]], 2.0, note="yard fence, road side (S part)")
fence("F_SKLAD_ROAD_N", "chain_link_2m", [[12.5, 20.5], [12.5, 36.0]], 2.0, note="yard fence, road side (N part); gate gap y 13.5-20.5 open")
fence("LW_SKLAD_S", "concrete_low_wall", [[12.5, -1.0], [24.0, -1.0]], 0.90, True, True, note="yard south edge, low wall")
fence("LW_DILNA_BANK_1", "concrete_low_wall", [DLw((-14.0, 11.6)), DLw((-5.6, 12.2))], 0.85, True, True, note="yard edge above the brook (NE part)")
fence("LW_DILNA_BANK_2", "concrete_low_wall", [DLw((-0.5, 12.4)), DLw((6.0, 14.0)), DLw((13.5, 12.4))], 0.85, True, True,
      note="yard edge above the brook (SW part); gap for the bridge landing")
fence("HEDGE_DUM_W1", "hedge_hornbeam", [DMw((-15.3, -12.5)), DMw((-15.3, 1.8))], 1.8, False, True, note="terrace west hedge (S of gate)")
fence("HEDGE_DUM_W2", "hedge_hornbeam", [DMw((-15.3, 4.2)), DMw((-15.3, 20.5))], 1.8, False, True, note="terrace west hedge (N of gate)")
fence("F_DUM_REAR_1", "timber_picket_1m", [DMw((-15.3, -13.2)), DMw((-2.1, -13.2))], 1.1, note="rear yard picket fence")
fence("F_DUM_REAR_2", "hedge_privet", [DMw((0.1, -13.2)), DMw((16.5, -13.2))], 1.8, False, True, note="rear yard hedge (SE side, blocks the long view from arm C); gate gap local x -2.1..0.1")
fence("HEDGE_DUM_E", "hedge_privet", [DMw((16.6, -12.2)), DMw((16.6, 6.0))], 1.8, False, True, note="terrace east edge hedge (S of the driveway)")
fence("HEDGE_DUM_N1", "hedge_hornbeam", [DMw((-14.4, 21.3)), DMw((-2.1, 21.3))], 1.8, False, True, note="front-garden hedge behind the parapet (W of the stair gate)")
fence("HEDGE_DUM_N2", "hedge_hornbeam", [DMw((0.1, 21.3)), DMw((12.6, 21.3))], 1.8, False, True, note="front-garden hedge behind the parapet (E of the stair gate)")
fence("LW_DUM_GARDEN", "concrete_low_wall", [DMw((9.8, 5.0)), DMw((9.8, 14.0))], 1.0, True, True,
      note="garden | side yard divider (cover line facing the driveway)")
fence("HEDGE_E_RING_1", "hedgerow_mixed", [[62.5, 40.0], [63.5, 22.0]], 2.4, False, True, note="field hedgerow E of the warehouse")
fence("HEDGE_E_RING_2", "hedgerow_mixed", [[63.8, 16.0], [63.0, -2.0], [58.5, -18.0]], 2.4, False, True)
fence("HEDGE_SKLAD_REAR", "hedge_privet", [[57.0, 30.0], [57.0, 20.0]], 1.8, False, True, note="rear-yard hedge (gap y 12-20)")
fence("HEDGE_SKLAD_REAR2", "hedge_privet", [[57.0, 12.0], [57.0, 3.0]], 1.8, False, True)
fence("HEDGE_TC_NE", "hedgerow_mixed", offset_polyline(resample(TC_XY, 44.0, 76.0), 4.6), 2.2, False, True, note="hedgerow NE of track C (gap 76-86)")
fence("HEDGE_TC_NE2", "hedgerow_mixed", offset_polyline(resample(TC_XY, 86.0, 118.0), 4.6), 2.2, False, True)
fence("F_DOMEK1_FRONT", "timber_picket_1m", [[21.5, 57.0], [21.5, 71.0]], 1.1, note="front garden fence S_DOMEK_1")
fence("HEDGE_DOMEK3", "hedge_privet", [[-68.6, -40.0], [-68.6, -48.6]], 1.8, False, True, note="garden hedge S_DOMEK_3 (west, N of the gate)")
fence("HEDGE_DOMEK3B", "hedge_privet", [[-68.6, -51.4], [-68.6, -52.6], [-55.0, -52.6]], 1.8, False, True,
      note="garden hedge S_DOMEK_3 (SW corner + south); 2.8 m garden gate gap at y -48.6..-51.4 (open wooden gate)")
fence("HEDGE_DOMEK4", "hedge_privet", [[22.0, -58.0], [34.5, -55.5]], 1.8, False, True, note="garden hedge S_DOMEK_4")
fence("HEDGE_TC_SW1", "hedgerow_mixed", offset_polyline(resample(TC_XY, 40.0, 56.0), -7.6), 2.2, False, True, note="hedgerow SW of track C beyond the ditch")
fence("HEDGE_TC_SW2", "hedgerow_mixed", offset_polyline(resample(TC_XY, 61.0, 80.0), -7.6), 2.2, False, True)
fence("F_BEERGARDEN", "timber_picket_1m", [[-75.0, -29.0], [-68.0, -29.0], [-68.0, -38.0], [-75.0, -38.0]], 1.1, note="pub beer garden")

# vegetation blocks: dense shrubs -- block movement and vision, NOT bullets (concealment, not cover)
VEG = []


def veg_belt(vid, pl, width, h, note=None):
    VEG.append({"id": vid, "type": "shrub_belt" if h < 5 else "windbreak_belt", "polyline": [[r2(p[0]), r2(p[1])] for p in pl], "width": width, "height": h,
                "species_mix": "hazel 40 %, elder 25 %, blackthorn 20 %, young alder/willow 15 %",
                "blocks_movement": True, "blocks_vision": True, "blocks_bullets": False,
                "density": "dense to the ground: instanced shrub cards + a continuous core collision box 0.8 x width; leaf gap <= 10 %",
                **({"note": note} if note else {})})


def veg_copse(vid, c, size, rot, h, note=None):
    VEG.append({"id": vid, "type": "shrub_copse", "polygon": xf_poly(c, rot, rect_local(-size[0] / 2, -size[1] / 2, size[0] / 2, size[1] / 2)),
                "height": h, "species_mix": "field copse (remízek): blackthorn, hawthorn, dog rose, 1-3 trees",
                "blocks_movement": True, "blocks_vision": True, "blocks_bullets": False,
                "density": "dense to the ground: instanced shrub cards around a continuous core collision hull; leaf gap <= 10 %",
                **({"note": note} if note else {})})


def brook_bank(s0, s1, off):
    """bank line between arc lengths (any order); offset + = left of the FLOW direction (downstream)."""
    a, b = min(s0, s1), max(s0, s1)
    return offset_polyline(resample(BROOK_XY, a, b), off)


def brook_s(pt):
    d, _, sv, _ = T.polyline_query(np.array([pt[0]]), np.array([pt[1]]), BROOK_XY)
    return float(sv[0])


# arm A: north bank belt (flow is westward there, north = right = negative offset), 3 m gaps every ~24 m
_s_a0, _s_a1 = sorted([brook_s([-150.0, -38.0]), brook_s([-66.0, -7.0])])
_k = 0
_sa = _s_a0
while _sa < _s_a1 - 4:
    _sb = min(_sa + 21.0, _s_a1)
    veg_belt(f"VB_BROOK_A{_k}", brook_bank(_sa, _sb, -5.2), 2.2, 3.0, "north bank of the brook in arm A")
    _sa = _sb + 3.0
    _k += 1
# arm A: south bank near the square (between the footbridge A and the bridge)
veg_belt("VB_BROOK_S1", brook_bank(brook_s([-50.0, -4.5]), brook_s([-31.0, 1.5]), 5.0), 2.0, 2.8, "south bank W of the square")
# east bank north of the square (flow southward: east = left = positive offset): gap at S_DOMEK_2
veg_belt("VB_BROOK_E1", brook_bank(brook_s([-13.2, 40.0]), brook_s([-14.9, 55.0]), 5.0), 2.0, 2.8, "east bank N of S_DOMEK_2")
veg_copse("VK_1", [-82.0, 4.0], [16.0, 9.0], 20, 3.5, "copse in the NW meadow")
veg_copse("VK_2", [-96.0, -76.0], [12.0, 7.0], 0, 3.5, "copse on the S spur foot (arm A)")
veg_copse("VK_3", [-30.0, -70.0], [14.0, 7.0], 5, 3.5, "copse behind the house (S spur)")
veg_copse("VK_4", [68.0, 36.0], [10.0, 7.0], 80, 3.5, "copse outside the E hedgerow")
veg_copse("VK_5", [46.0, 100.0], [14.0, 8.0], 60, 3.5, "copse in arm B east meadow")
veg_copse("VK_6", [-36.0, 90.0], [10.0, 7.0], 85, 3.5, "copse in arm B west (NW spur foot)")
veg_copse("VK_7", [-118.0, -14.0], [10.0, 6.0], 15, 3.5, "copse in arm A north meadow")
veg_copse("VK_8", [74.5, -50.5], [12.0, 7.0], 30, 3.5, "copse on the E spur foot above track C")
veg_copse("VK_9", [46.0, -12.0], [8.0, 14.0], 0, 3.5, "copse S of the warehouse: breaks E-ring -> square -> workshop yard lines")
veg_belt("VB_SKLAD_N", [[52.4, 31.0], [37.3, 31.4], [37.6, 44.8]], 2.6, 5.5,
         "L-shaped windbreak (hornbeam/field maple row, dense to the ground, 5.5 m) round the warehouse north end: "
         "no overwatch from the steep E spur slope / E ring path into the square and the workshop yard")
veg_belt("VB_BROOK_W1", brook_bank(brook_s([-15.3, 62.0]), brook_s([-18.0, 96.0]), -5.2), 2.2, 3.0,
         "west bank N of footbridge B: breaks the long view down the brook corridor")
# úvoz south crest: hedgerow with young field maples (a typical mez along a sunken lane), 4.5 m, 4.2 m S of the lane axis
# (bank top is 2.6 m off the axis). It removes the elevated overwatch from the S spur meadow (4-7 m above the zone floor,
# 32-44 m away) into the house yard/garden. Starts 2 m W of the south exit ramp (s 14.5-18 + taper) and stops 4 m before the
# lane's west end ramp, so the exit and the ring path stay open.
veg_belt("VB_UVOZ_S", offset_polyline(resample(UVOZ_XY, 21.5, UVOZ_LEN - 4.0), 4.2), 3.0, 4.5,
         "hedgerow with field maples on the south crest of the úvoz: no overwatch from the S spur meadow into zone_dvur")
VEG[-1]["species_mix"] = "hazel 35 %, hornbeam 25 %, field maple (young trees to 6 m) 20 %, blackthorn/hawthorn 20 %"
veg_belt("VB_SPUR_S1", [[-142.0, -77.0], [-124.0, -78.5], [-106.0, -79.0]], 2.4, 3.5, "shrub belt along the S spur foot (arm A), gap at VK_2")
veg_belt("VB_SPUR_S2", [[-88.0, -79.0], [-72.0, -78.0], [-58.0, -75.5]], 2.4, 3.5, "shrub belt along the S spur foot (arm A)")

# =================================================================================================
# 6.  Props (catalog + instances)
# =================================================================================================
CATALOG = {
    # type: [L (local X), W (local Y), H], cover, blocks_bullets, blocks_vision, note
    "car_hatchback": {"size": [4.0, 1.75, 1.45], "cover": "low", "note": "generic 2000s hatchback, no brand; wheels/tyres block"},
    "van_rusty": {"size": [5.0, 2.0, 2.2], "cover": "high"},
    "pickup_truck": {"size": [5.3, 1.9, 1.85], "cover": "high"},
    "semi_trailer_box": {"size": [13.6, 2.55, 4.0], "cover": "high", "note": "side skirts to the ground: nobody shoots/crawls underneath"},
    "tipper_truck": {"size": [8.2, 2.5, 3.2], "cover": "high"},
    "tractor_with_trailer": {"size": [9.0, 2.3, 2.8], "cover": "high"},
    "farm_trailer_old": {"size": [5.5, 2.2, 1.6], "cover": "low"},
    "flatbed_trailer": {"size": [6.0, 2.2, 1.1], "cover": "low"},
    "military_truck_wreck": {"size": [7.5, 2.5, 2.9], "cover": "high", "note": "burned-out generic 6x6, no insignia"},
    "bus_wreck": {"size": [12.0, 2.55, 3.0], "cover": "high", "note": "burned-out regional bus (generic, no livery), windows empty: "
                  "collision + vision blocking up to 3.0 m (window band treated as opaque by soot/frames in v1)"},
    "lorry_wreck": {"size": [9.5, 2.5, 3.4], "cover": "high", "note": "burned-out box lorry, generic"},
    "car_wreck": {"size": [4.0, 1.75, 1.35], "cover": "low"},
    "military_truck": {"size": [7.5, 2.5, 3.1], "cover": "high", "note": "team staging vehicle (team colour tarpaulin, fictional markings)"},
    "military_4x4": {"size": [4.8, 2.1, 2.0], "cover": "high"},
    "shipping_container_20": {"size": [6.06, 2.44, 2.59], "cover": "high"},
    "skip_container": {"size": [4.0, 1.8, 1.5], "cover": "low"},
    "pallet_stack": {"size": [1.2, 1.0, 1.1], "cover": "low"},
    "pallets_bagged_cement": {"size": [1.2, 1.0, 1.2], "cover": "low"},
    "pallets_bricks_2high": {"size": [1.2, 1.0, 2.3], "cover": "high", "note": "two pallets of bricks stacked, strapped"},
    "ibc_tanks_x2": {"size": [2.4, 1.2, 1.15], "cover": "low"},
    "big_bags_x2": {"size": [2.0, 1.0, 1.4], "cover": "low"},
    "oil_drums_cluster": {"size": [1.8, 1.2, 0.9], "cover": "low"},
    "steel_profile_stack": {"size": [4.0, 1.2, 0.9], "cover": "low"},
    "concrete_pipes_stack": {"size": [6.0, 3.2, 2.9], "cover": "high", "note": "4 x DN1500 pipes, ends closed by mesh (no crawl-through)"},
    "log_pile": {"size": [6.0, 2.2, 1.6], "cover": "low"},
    "log_pile_high": {"size": [6.0, 2.4, 2.2], "cover": "high"},
    "round_bales_stack": {"size": [4.6, 1.6, 2.6], "cover": "high"},
    "round_bale_single": {"size": [1.5, 1.2, 1.5], "cover": "low"},
    "water_wheel_ruin": {"size": [1.2, 4.0, 4.0], "cover": "high"},
    "harrow_rusty": {"size": [3.0, 1.6, 0.6], "cover": "none"},
    "gas_bottle_cage": {"size": [1.6, 0.8, 1.8], "cover": "high", "note": "mesh cage: blocks movement, not bullets", "blocks_bullets": False},
    "greenhouse_glass": {"size": [3.0, 5.0, 2.4], "cover": "none", "blocks_bullets": False, "blocks_vision": False,
                         "note": "glass: blocks movement only (v1, no breakage)"},
    "raised_bed": {"size": [4.0, 1.2, 0.35], "cover": "none"},
    "garden_table_set": {"size": [1.8, 1.8, 0.75], "cover": "none"},
    "paving_slab_stack": {"size": [1.2, 1.0, 0.9], "cover": "low"},
    "compost_bins": {"size": [2.4, 1.0, 1.0], "cover": "low"},
    "stone_cross": {"size": [0.8, 0.5, 2.6], "cover": "none"},
    "field_shrine": {"size": [0.7, 0.7, 3.2], "cover": "none"},
    "bench": {"size": [1.8, 0.6, 0.85], "cover": "none"},
    "noticeboard": {"size": [1.6, 0.3, 2.0], "cover": "none"},
    "street_lamp": {"size": [0.25, 0.25, 7.0], "cover": "none"},
    "hydrant": {"size": [0.35, 0.35, 0.9], "cover": "none"},
    "beehives_row": {"size": [4.0, 0.8, 0.9], "cover": "low"},
    "sandbag_wall": {"size": [3.0, 0.8, 1.1], "cover": "low"},
    "concrete_barrier_row": {"size": [6.0, 0.6, 0.9], "cover": "low", "note": "3 jersey barriers"},
    "ammo_crates_stack": {"size": [2.0, 1.2, 1.2], "cover": "low"},
    "gravel_heap": {"size": [14.0, 12.0, 5.5], "cover": "high", "note": "OUTSIDE playable boundary; collision is a steep hull (not climbable)"},
    "conveyor_frame": {"size": [18.0, 1.6, 7.0], "cover": "none", "note": "outside playable boundary"},
    "weir_stone_low": {"size": [3.4, 1.0, 0.35], "cover": "none", "blocks_vision": False,
                       "note": "low stone weir (jez) across the brook, 0.35 m sill (walkable step), mill-race intake beside it"},
    "sluice_gate_frame": {"size": [1.4, 0.4, 1.6], "cover": "low", "note": "timber sluice gate (stavidlo) with a rusty rack at the race intake"},
    "hesco_line": {"size": [6.42, 1.1, 2.74], "cover": "high", "module_length": 1.07,
                   "note": "two-tier wall of wire-mesh gabion bastions (generic, no brand) filled with gravel, 2.74 m: hard spawn "
                           "screen; built from 1.07 m cells, every placed length is a whole number of cells (1-6)"},
    "container_stack_2": {"size": [6.06, 2.44, 5.18], "cover": "high",
                          "note": "two stacked 20 ft containers (weathered olive/rust, fictional markings): hard spawn screen where a "
                                  "row looks up at its zone; always the full 6.06 m (never cut)"},
    "container_stack_2_10ft": {"size": [2.99, 2.44, 5.18], "cover": "high",
                               "note": "two stacked 10 ft containers (same finish): used where a 20 ft stack would touch a "
                                       "building; never cut"},
}

PROPS = []


def prop(pid, typ, pos, rot, cluster, note=None, z=None):
    c = CATALOG[typ]
    zz = None if z is None else r2(z)
    PROPS.append({"id": pid, "type": typ, "position": [r2(pos[0]), r2(pos[1]), zz], "rotation_deg": r2(rot % 360),
                  "size": c["size"], "cover": c["cover"], "blocks_bullets": c.get("blocks_bullets", True),
                  "blocks_vision": c.get("blocks_vision", True), "cluster": cluster, **({"note": note} if note else {})})


def lprop(pid, typ, frame, lp, lrot, cluster, note=None, z=None):
    c = frame["c"]
    w = xf(c, frame["rot"], lp)
    prop(pid, typ, w, frame["rot"] + lrot, cluster, note, z)


# --- Z1 workshop yard / rear
lprop("P_DL_1", "steel_profile_stack", DILNA, (-5.8, 9.9), 0, "Z1_yard", "breaks the bridge -> gate dash", Z_DILNA_PAD)
lprop("P_DL_2", "van_rusty", DILNA, (4.6, 9.4), 10, "Z1_yard", z=Z_DILNA_PAD)
lprop("P_DL_3", "flatbed_trailer", DILNA, (-11.2, 8.4), 20, "Z1_yard", z=Z_DILNA_PAD)
lprop("P_DL_4", "skip_container", DILNA, (10.4, 10.0), 70, "Z1_yard", z=Z_DILNA_PAD)
lprop("P_DL_5", "oil_drums_cluster", DILNA, (0.8, 6.5), 0, "Z1_yard", z=Z_DILNA_PAD)
lprop("P_DL_6", "pallet_stack", DILNA, (-1.6, 6.3), 0, "Z1_yard", z=Z_DILNA_PAD)
lprop("P_DL_7", "pallet_stack", DILNA, (9.6, 6.2), 0, "Z1_yard", z=Z_DILNA_PAD)
lprop("P_DL_8", "water_wheel_ruin", DILNA, (12.9, -2.2), 0, "Z1_yard", "rusted wheel on the old tailrace at the annex gable", Z_DILNA_PAD)
lprop("P_DL_9", "harrow_rusty", DILNA, (-6.5, -7.4), 0, "Z1_rear", z=Z_DILNA_PAD)
lprop("P_DL_10", "gas_bottle_cage", DILNA, (-9.6, -5.8), 0, "Z1_rear", z=Z_DILNA_PAD)
lprop("P_DL_11", "pallet_stack", DILNA, (6.0, -10.35), 0, "Z1_terrace", "pallets between the terrace path and the race", Z_TERRACE_DILNA)
lprop("P_DL_12", "bench", DILNA, (7.8, 6.1), 0, "Z1_yard", z=Z_DILNA_PAD)
# --- Z2 warehouse yard / dock / rear
prop("P_SK_1", "semi_trailer_box", [22.3, 15.2], 90, "Z2_yard", "splits the yard into the dock aisle and the outer yard", Z_SKLAD_YARD)
prop("P_SK_2", "shipping_container_20", [17.2, 30.6], 0, "Z2_yard", z=Z_SKLAD_YARD)
prop("P_SK_3", "pallets_bagged_cement", [27.6, 25.6], 0, "Z2_yard", z=Z_SKLAD_YARD)
prop("P_SK_4", "pallets_bagged_cement", [17.8, 6.2], 15, "Z2_yard", z=Z_SKLAD_YARD)
prop("P_SK_5", "pallets_bagged_cement", [28.2, 4.6], 0, "Z2_yard", z=Z_SKLAD_YARD)
prop("P_SK_6", "ibc_tanks_x2", [15.6, 21.2], 90, "Z2_yard", z=Z_SKLAD_YARD)
prop("P_SK_7", "pickup_truck", [24.8, 31.4], 20, "Z2_yard", z=Z_SKLAD_YARD)
prop("P_SK_8", "skip_container", [53.2, 7.8], 90, "Z2_rear", z=Z_SKLAD_REAR)
prop("P_SK_9", "big_bags_x2", [53.4, 22.4], 90, "Z2_rear", z=Z_SKLAD_REAR)
prop("P_SK_10", "pallet_stack", [52.6, 24.5], 0, "Z2_rear", z=Z_SKLAD_REAR)
prop("P_SK_11", "round_bale_single", [67.0, 8.0], 30, "Z2_field")
prop("P_SK_12", "round_bale_single", [66.8, 27.0], 75, "Z2_field")
# --- Z3 house garden / rear yard
lprop("P_DM_1", "greenhouse_glass", DUM, (-10.5, 13.5), 0, "Z3_garden", z=Z_TERRACE_DUM)
lprop("P_DM_2", "raised_bed", DUM, (0.5, 10.0), 0, "Z3_garden", z=Z_TERRACE_DUM)
lprop("P_DM_3", "raised_bed", DUM, (0.5, 13.0), 0, "Z3_garden", z=Z_TERRACE_DUM)
lprop("P_DM_4", "raised_bed", DUM, (-5.0, 11.5), 90, "Z3_garden", z=Z_TERRACE_DUM)
lprop("P_DM_5", "garden_table_set", DUM, (6.5, 8.5), 0, "Z3_garden", z=Z_TERRACE_DUM)
lprop("P_DM_6", "paving_slab_stack", DUM, (-7.2, 8.0), 0, "Z3_garden", z=Z_TERRACE_DUM)
lprop("P_DM_7", "paving_slab_stack", DUM, (3.8, 18.6), 0, "Z3_garden", "behind the parapet near the stairs", Z_TERRACE_DUM)
lprop("P_DM_8", "car_hatchback", DUM, (14.5, 16.3), 90, "Z3_drive", z=Z_TERRACE_DUM)
lprop("P_DM_9", "compost_bins", DUM, (6.5, -10.5), 0, "Z3_rear", z=Z_TERRACE_DUM)
lprop("P_DM_10", "log_pile", DUM, (3.5, -8.8), 0, "Z3_rear", "firewood in the rear yard (keeps 1.2 m in front of the entrance steps)", Z_TERRACE_DUM)
prop("P_DM_11", "log_pile", [-31.0, -40.5], 80, "Z3_west_approach", "stacked firewood below the terrace west hedge (attacker cover)")
prop("P_DM_12", "farm_trailer_old", [-37.5, -35.5], 20, "Z3_west_approach", "old trailer by the garden path (attacker cover)")
# --- square
prop("P_NV_1", "car_hatchback", [-9.5, 4.0], 80, "HUB", z=Z_HUB)
prop("P_NV_2", "noticeboard", [16.3, -5.2], 55, "HUB", z=Z_HUB)
prop("P_NV_3", "bench", [8.5, -1.2], 0, "HUB", z=Z_HUB)
prop("P_NV_4", "hydrant", [-15.5, 6.0], 0, "HUB", z=Z_HUB)
for i, p in enumerate([[-10.0, -8.4], [8.0, 12.0], [10.0, -4.0], [-24.0, -3.5], [11.8, 29.5], [-30.0, -17.0]]):
    prop(f"P_LAMP_{i + 1}", "street_lamp", p, 0, "street")
prop("P_NV_5", "stone_cross", [6.2, 0.8], 0, "HUB", "wayside cross under the linden", z=Z_HUB)
# --- village barricades (sightline breakers on the two long road corridors)
prop("P_BAR_B1", "bus_wreck", [7.0, 37.5], 37, "barricade_B", "burnt bus across road B at 40 deg: chicane, gaps at both ends")
prop("P_BAR_B2", "concrete_barrier_row", [11.5, 44.5], 350, "barricade_B")
prop("P_BAR_C1", "tractor_with_trailer", [28.5, -21.0], 0, "barricade_C", "tractor + trailer stuck across track C at 36 deg: chicane")
prop("P_SK_13", "pallets_bricks_2high", [29.3, 1.8], 0, "Z2_yard", "closes the long N-S view along the dock aisle (S end)", Z_SKLAD_YARD)
prop("P_SK_14", "pallets_bricks_2high", [29.3, 33.3], 0, "Z2_yard", "closes the long N-S view along the dock aisle (N end)", Z_SKLAD_YARD)
prop("P_SK_15", "pallets_bricks_2high", [27.9, 33.3], 0, "Z2_yard", z=Z_SKLAD_YARD)
prop("P_BAR_A1", "lorry_wreck", [-50.0, -18.0], 162.5, "barricade_A", "lorry wreck at 30 deg to road A")
prop("P_BAR_A2", "concrete_barrier_row", [-41.5, -15.8], 100, "barricade_A")
prop("P_BAR_A3", "car_wreck", [-43.0, -12.3], 30, "barricade_A")
# --- arm A
prop("P_A_1", "stone_cross", [-64.0, -15.8], 0, "armA")
prop("P_A_2", "tractor_with_trailer", [-73.5, -16.6], 180, "armA", "parked on the north verge")
prop("P_A_3", "military_truck_wreck", [-108.0, -31.5], 212, "armA")
prop("P_A_4", "log_pile", [-106.0, -48.0], 30, "spawnA")
prop("P_A_5", "log_pile_high", [-131.0, -71.5], 25, "spawnA")
prop("P_A_6", "log_pile", [-131.0, -56.0], 20, "spawnA")
prop("P_A_7", "military_truck", [-139.0, -66.0], 25, "spawnA")
prop("P_A_8", "military_4x4", [-114.0, -50.5], 30, "spawnA")
prop("P_A_9", "concrete_barrier_row", [-151.0, -58.5], 110, "boundaryA", "roadblock across road A (rear of spawn A)")
prop("P_A_10", "concrete_barrier_row", [-148.0, -52.5], 110, "boundaryA")
prop("P_A_11", "car_hatchback", [-40.5, -24.0], 102, "armA", "parked in front of the garages")
# --- arm B
prop("P_B_1", "tipper_truck", [18.8, 46.0], 76, "armB")
prop("P_B_2", "concrete_pipes_stack", [-7.0, 68.0], 10, "armB")
prop("P_B_3", "farm_trailer_old", [-5.5, 99.0], 80, "armB")
prop("P_B_4", "beehives_row", [-12.0, 88.0], 95, "armB")
prop("P_B_5", "military_truck", [38.5, 124.0], 170, "spawnB")
prop("P_B_6", "military_4x4", [31.0, 108.0], 175, "spawnB")
prop("P_B_7", "ammo_crates_stack", [40.0, 138.0], 170, "spawnB")
prop("P_B_8", "gravel_heap", [60.0, 152.0], 20, "boundaryB")
prop("P_B_9", "gravel_heap", [4.0, 171.0], 80, "boundaryB")
prop("P_B_10", "conveyor_frame", [46.0, 170.0], 60, "boundaryB")
prop("P_B_11", "concrete_barrier_row", [25.0, 164.5], 110, "boundaryB", "roadblock across road B (rear of spawn B)")
prop("P_B_12", "weir_stone_low", [-20.6, 116.5], 9, "armB", "stone weir of the old mill race (jez)")
prop("P_B_13", "sluice_gate_frame", [-22.9, 115.4], 60, "armB", "race intake sluice (stavidlo)")
# --- arm C
prop("P_C_1", "round_bales_stack", [38.5, -47.0], 40, "armC")
prop("P_C_2", "field_shrine", [72.0, -65.5], 0, "armC")
prop("P_C_3", "farm_trailer_old", [88.0, -72.5], 30, "armC")
prop("P_C_4", "round_bales_stack", [70.0, -88.0], 30, "armC")
prop("P_C_5", "military_truck", [116.0, -94.0], 326, "spawnC")
prop("P_C_6", "military_4x4", [96.0, -110.0], 45, "spawnC")
prop("P_C_7", "ammo_crates_stack", [106.0, -88.0], 40, "spawnC")
prop("P_C_8", "concrete_barrier_row", [140.0, -118.0], 130, "boundaryC", "roadblock across track C (rear of spawn C)")

# =================================================================================================
# 7.  Capture zones (polygons in world XY; counted by the capsule base / feet position)
# =================================================================================================
def zone_poly(frame, pts):
    return xf_poly(frame["c"], frame["rot"], pts)


def shoelace(poly):
    a = 0.0
    for i in range(len(poly)):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % len(poly)]
        a += x1 * y2 - x2 * y1
    return abs(a) / 2


Z1_POLY = zone_poly(DILNA, [[-12.5, -6.5], [4.05, -6.5], [4.05, -2.0], [13.0, -2.0], [13.0, 9.5], [10.0, 11.2], [4.0, 12.3],
                           [-5.5, 12.0], [-11.0, 11.0], [-13.0, 9.0], [-13.0, -6.5]])
Z2_POLY = zone_poly(SKLAD, [[-13.0, 0.0], [13.0, 0.0], [13.0, 18.5], [-13.0, 18.5]])
Z3_POLY = zone_poly(DUM, [[-10.5, -6.0], [10.5, -6.0], [10.5, 17.5], [-10.5, 17.5]])


def centroid(poly):
    P = np.array(poly)
    return [r2(P[:, 0].mean()), r2(P[:, 1].mean())]


zones = [
    {"id": "zone_dilna", "name": "Dílna", "desc": "workshop hall ground floor + yard between the hall and the brook",
     "polygon": Z1_POLY, "center": [r2(v) for v in DLw((0.0, 6.0))], "z_min": r2(DILNA["floor"] - 0.60), "z_max": r2(DILNA["floor"] + 2.50),
     "hud_marker": [r2(v) for v in DLw((0.0, 6.0))] + [r2(DILNA["floor"] + 3.0)],
     "excluded": "annex upper floor (L1) and the mill-race terrace; the bridge deck"},
    {"id": "zone_sklad", "name": "Sklad", "desc": "loading dock, front aisle and first rack row of the warehouse + dock apron of the yard",
     "polygon": Z2_POLY, "center": [r2(v) for v in SKw((0.0, 8.5))], "z_min": r2(Z_SKLAD_YARD - 0.50), "z_max": r2(SKLAD["floor"] + 2.60),
     "hud_marker": [r2(v) for v in SKw((0.0, 8.5))] + [r2(SKLAD["floor"] + 3.5)],
     "excluded": "rear aisle, rear yard"},
    {"id": "zone_dvur", "name": "Dvůr", "desc": "house terrace garden, ground floor of the house and the rear yard",
     "polygon": Z3_POLY, "center": [r2(v) for v in DMw((0.0, 8.5))], "z_min": r2(Z_TERRACE_DUM - 0.50), "z_max": r2(DUM["floor"] + 2.60),
     "hud_marker": [r2(v) for v in DMw((0.0, 8.5))] + [r2(DUM["floor"] + 3.5)],
     "excluded": "the square below the retaining wall, the upper floor of the house"},
]
for zn in zones:
    zn["area_m2"] = r2(shoelace(zn["polygon"]))
    zn["inclusion_test"] = ("capsule foot point (x, y, z_foot) counts when inside `polygon` AND z_min <= z_foot <= z_max; every walkable "
                            "surface inside the polygon lies >= 0.30 m inside or >= 0.30 m outside [z_min, z_max] (validated)")
    zn["marker"] = {"in_world": "violet smoke marker (fialový signální kouř) + olive radio-relay crate (bedna s převaděčem) at "
                                "`hud_marker`, white painted boundary line on the ground along the polygon (decal, 0.12 m wide, like a "
                                "road marking); enabled only for the active zone. Violet/white because blue, red and yellow are the team "
                                "colours of Web/src/data/teams.json and stay reserved for ownership",
                    "hud": "zone outline + zone name and distance in metres; tinted with the controlling team's colour (teams.json), "
                           "white when contested, neutral grey when empty (as Web/src/game/zoneView.js)"}
zones[0]["excluded"] = ("annex stair bay/corridor strip and the whole upper floor (office z +4.30 world, 0.50 above z_max); the "
                        "external steel stair; the mill-race terrace; the brook bed and banks beyond the yard low walls")
zones[2]["excluded"] = "the square below the retaining wall; the upper floor and the balcony of the house (z 5.94, 0.40 above z_max)"

# =================================================================================================
# 8.  Spawn spines (the per-zone spawn rows are solved in ivlayout_post from real path distances)
# =================================================================================================
SPINES = {
    # team: road polyline it follows, lateral offset (+ = left of the road direction away from the square), s range (m along the road)
    "alfa": {"road": "ROAD_A", "xy": RA_XY, "offset": 22.0, "s_range": [80.0, 146.0], "side": "S of road A behind the pub (timber yard)"},
    "bravo": {"road": "ROAD_B", "xy": RB_XY, "offset": -10.0, "s_range": [80.0, 160.0], "side": "E of road B (gravel works yard)"},
    "charlie": {"road": "TRACK_C", "xy": TC_XY, "offset": -9.0, "s_range": [80.0, 140.0], "side": "SW of track C (farm meadow)"},
}
SPINE_XY = {t: offset_polyline(v["xy"], v["offset"]) for t, v in SPINES.items()}
# Design-fixed spawn rows (s = metres along the team's road from the square).  They come from the exhaustive geodesic solver
# (ivpost.solve_spawns without fixed rows); the hard HESCO screens are built around them and the balance is re-measured
# with the screens present (Tools/level/check_layout.py S03 enforces max/min <= 1.06).
FIXED_ROWS = {"alfa": {"zone_dilna": 142.0, "zone_dvur": 142.0, "zone_sklad": 84.0},
              "bravo": {"zone_dilna": 157.0, "zone_sklad": 157.0, "zone_dvur": 92.0},
              "charlie": {"zone_dilna": 89.0, "zone_sklad": 132.0, "zone_dvur": 132.0}}
for _t, _r in FIXED_ROWS.items():
    SPINES[_t]["fixed_rows"] = _r


def spine_point(team, s):
    pl = SPINES[team]["xy"]
    P = np.array(pl, float)
    S = np.array(SPINE_XY[team], float)
    seg = np.hypot(*np.diff(P, axis=0).T)
    cs = np.concatenate([[0], np.cumsum(seg)])
    k = int(np.clip(np.searchsorted(cs, s) - 1, 0, len(seg) - 1))
    t = (s - cs[k]) / seg[k]
    q = S[k] + t * (S[k + 1] - S[k])
    d = P[k + 1] - P[k]
    d = d / np.linalg.norm(d)
    return q, d          # position on the spine, road direction (away from the square)


def spine_corridor(team, pad=6.0):
    a, b = SPINES[team]["s_range"]
    pts = [spine_point(team, s)[0].tolist() for s in np.arange(a - 6, b + 6.01, 3.0)]
    return pts


spawn_areas = []   # filled by ivlayout_post.solve_spawns()

# =================================================================================================
# 9.  Boundary
# =================================================================================================
SOFT = [[-152, -20], [-126, -6], [-100, 6], [-80, 16], [-68, 30], [-62, 46], [-56, 62], [-48, 80], [-40, 100], [-34, 122],
        [-31, 150], [-26, 162], [4, 166], [44, 163], [54, 130], [62, 106], [70, 84], [76, 60], [78, 36], [77, 12], [73, -10], [80, -32],
        [98, -52], [122, -70], [140, -94], [134, -124], [112, -132], [92, -122], [72, -104], [48, -88], [24, -78], [0, -76],
        [-24, -77], [-48, -82], [-74, -88], [-100, -88], [-128, -86], [-150, -82], [-158, -56]]

# =================================================================================================
# 9b. Detail terrain layer (gradient noise) + deferred object heights
# =================================================================================================
DETAIL_OCTAVES = [{"wavelength": 64.0, "amplitude": 1.25, "seed": 101}, {"wavelength": 32.0, "amplitude": 0.75, "seed": 102},
                  {"wavelength": 16.0, "amplitude": 0.38, "seed": 103}, {"wavelength": 8.0, "amplitude": 0.15, "seed": 104},
                  {"wavelength": 4.0, "amplitude": 0.06, "seed": 105}, {"wavelength": 2.0, "amplitude": 0.02, "seed": 106}]


def detail_layer():
    feats = []
    for st in stamps:
        if st["kind"] == "pad":
            feats.append({"kind": "polygon", "src": st["id"], "pts": st["polygon"]})
        elif st["kind"] == "road":
            feats.append({"kind": "polyline", "src": st["id"], "pts": [p[:2] for p in st["polyline"]],
                          "half_width": r2(st["width"] / 2 + st.get("shoulder", 0.0) + st["blend"])})
    for zn in zones:
        feats.append({"kind": "polygon", "src": zn["id"], "pts": zn["polygon"]})
    for t, sp in SPINES.items():
        a, b = sp["s_range"]
        pts = [[r2(q) for q in spine_point(t, s_)[0]] for s_ in np.arange(a - 12.0, b + 12.01, 4.0)]
        feats.append({"kind": "polyline", "src": "spawn_spine_" + t, "pts": pts, "half_width": 9.0})
    for b_ in main_buildings:
        feats.append({"kind": "polygon", "src": b_["id"], "pts": b_["footprint_world"]})
    for sb in SEC:
        feats.append({"kind": "polygon", "src": sb["id"], "pts": sb["footprint_world"]})
    for pr in PROPS:
        c = pr["size"]
        feats.append({"kind": "polygon", "src": pr["id"], "pts": xf_poly(pr["position"][:2], pr["rotation_deg"],
                                                                        rect_local(-c[0] / 2, -c[1] / 2, c[0] / 2, c[1] / 2))})
    for br in bridges:
        feats.append({"kind": "polyline", "src": br["id"], "pts": br["ends"], "half_width": r2(br["width"] / 2 + 2.0)})
    for rw in retaining_walls:
        feats.append({"kind": "polyline", "src": rw["id"], "pts": rw["polyline"], "half_width": 1.0})
    return {"type": "perlin_gradient_fbm",
            "definition": "h_detail(x, y) = mask(x, y) * sum_o amplitude_o * perlin2(x / wavelength_o, y / wavelength_o, seed_o); "
                          "perlin2 = classic gradient noise on the unit lattice, gradient angle = hash_u32(ix, iy, seed) / 2^32 * 2 pi, "
                          "quintic fade 6t^5 - 15t^4 + 10t^3; hash_u32 = lowbias32((ix * 0x8da6b343) ^ (iy * 0xd8163841) ^ "
                          "(seed * 0xcb1ab31f)) with all products mod 2^32 (JS: Math.imul, >>> 0). Reference: Tools/level/lib/ivterrain.py",
            "applied": "after base_grid sampling, before stamps (pads/roads/walls override it)",
            "octaves": DETAIL_OCTAVES,
            "mask": {"ramp_m": 8.0, "floor": 0.0,
                     "rule": "mask = min over quiet features of smoothstep(0, ramp_m, distance outside the feature); polygons are 0 inside, "
                             "polylines 0 within half_width",
                     "quiet_features": feats}}


def row_points(team, s_):
    q, d = spine_point(team, s_)
    n = np.array([-d[1], d[0]])
    pts = [q + d * rk + n * cl for rk in (-4.5, -1.5, 1.5, 4.5) for cl in (-1.5, 1.5)]
    return q, d, pts


def zone_targets(zn, step=3.0):
    P = np.array(zn["polygon"])
    from matplotlib.path import Path as _P
    x0, y0 = P.min(axis=0)
    x1, y1 = P.max(axis=0)
    pts = [tuple(v) for v in P]
    for x in np.arange(x0, x1 + 0.01, step):
        for y in np.arange(y0, y1 + 0.01, step):
            if _P(P).contains_point((x, y)):
                pts.append((x, y))
    return np.array(pts)


def upper_targets(zid):
    """eye points at the upper-floor windows / balcony of the zone's building (for the spawn screens)."""
    bp = next(b for b in main_buildings if b["zone"] == zid)
    bd = next(b for b in IB.all_buildings() if b["id"] == bp["id"])
    wm = {w["id"]: w for w in bd["walls"]}
    lv = {l["id"]: l for l in bd["levels"]}
    out = []
    for o in bd["openings"]:
        w = wm[o["wall_id"]]
        if o["type"] != "window" or w["level"] == "L0" or w["kind"] != "external":
            continue
        (sx, sy), (ex, ey) = w["start"], w["end"]
        L_ = math.hypot(ex - sx, ey - sy)
        u = (o["offset_from_start"] + o["width"] / 2) / L_
        p_ = xf(bp["position"][:2], bp["rotation_deg"], (sx + (ex - sx) * u, sy + (ey - sy) * u))
        out.append((p_[0], p_[1], bp["position"][2] + lv[w["level"]]["floor_z"] + 1.65))
    for ba in bd.get("balconies", []):
        P = np.array(ba["polygon"]).mean(axis=0)
        p_ = xf(bp["position"][:2], bp["rotation_deg"], P)
        out.append((p_[0], p_[1], bp["position"][2] + ba["top_z"] + 1.65))
    return out


SCREEN_TYPES = [("hesco_line", 2.74), ("container_stack_2", 5.18)]


def spawn_screens():
    """Hard spawn screens in front of every spawn row: a two-tier HESCO bastion wall (2.74 m), or two stacked 20 ft containers
    (5.18 m) where the rows look up at the zone.  The screen is perpendicular to the mean direction to the row's zone targets,
    placed as far forward as its height allows, and long enough that every ray from the 8 row points (eye 1.65 m) to those
    targets (zone floor + 1.6 m, upper-floor windows/balcony + 1.65 m) crosses it below its top.  Ends stay open (chicane
    exits).  Spawn safety therefore holds with hard geometry only (no foliage); check_layout.py V01 verifies it in 3D."""
    rows = {}
    for t, fr in FIXED_ROWS.items():
        for zid, s_ in fr.items():
            rows.setdefault((t, s_), []).append(zid)
    zd = {z["id"]: z for z in zones}
    for (t, s_), zids in sorted(rows.items()):
        q, d, pts = row_points(t, s_)
        P = np.array(pts)
        tgt = []
        for z in zids:
            for (x, y) in zone_targets(zd[z]):
                tgt.append((x, y, gz(x, y) + 1.6))
            tgt += upper_targets(z)
        tgt = np.array(tgt)
        m = tgt[:, :2].mean(axis=0) - q
        f = m / np.linalg.norm(m)
        nrm = np.array([-f[1], f[0]])
        front = max(float(np.dot(p - q, f)) for p in P)
        eyes = [(p[0], p[1], gz(p[0], p[1]) + 1.65) for p in P]
        choice = None
        for typ, hgt in SCREEN_TYPES:
            for dist in (4.5, 3.5, 2.8, 2.2):
                c = q + f * (front + dist)
                lat, need = [], []
                for e in eyes:
                    for g in tgt:
                        v = np.array([g[0] - e[0], g[1] - e[1]])
                        tt = np.dot(c - np.array(e[:2]), f) / np.dot(v, f)
                        x = np.array(e[:2]) + v * tt
                        lat.append(float(np.dot(x - c, nrm)))
                        zr = e[2] + (g[2] - e[2]) * tt
                        need.append((x, zr))
                lo, hi = min(lat) - 1.2, max(lat) + 1.2
                base = min(gz(*(c + nrm * u)) for u in np.linspace(lo, hi, 9))
                req = max(zr for _, zr in need) - base + 0.15
                if req <= hgt:
                    choice = (typ, hgt, dist, c, lo, hi, base, req)
                    break
            if choice:
                break
        if not choice:
            raise RuntimeError(f"no screen blocks row {t} s={s_}")
        typ, hgt, dist, c, lo, hi, base, req = choice
        L_ = hi - lo
        HC = 1.07                                        # HESCO cell length
        if typ == "container_stack_2":
            seglens = [6.06] * int(math.ceil(L_ / 6.06))
        else:
            cells = int(math.ceil(L_ / HC))
            nseg = int(math.ceil(cells / 6))
            seglens = [HC * (cells // nseg + (1 if i < cells % nseg else 0)) for i in range(nseg)]
        mid = (lo + hi) / 2
        lo = mid - sum(seglens) / 2
        rot = math.degrees(math.atan2(nrm[1], nrm[0]))
        from shapely.geometry import Polygon as _Pg, LineString as _Ls
        blds = [_Pg(b_["footprint_world"]).buffer(0.3) for b_ in SEC + main_buildings]

        def strip(u0, u1):
            return _Ls([tuple(c + nrm * u0), tuple(c + nrm * u1)]).buffer(1.3, cap_style=2)

        def trim(ua, ub, hit):
            """shorten the module from the end nearer to the building until its whole footprint strip is clear"""
            from shapely.geometry import Point as _Pt
            da = min(h.distance(_Pt(*(c + nrm * ua))) for h in hit)
            db = min(h.distance(_Pt(*(c + nrm * ub))) for h in hit)
            side = "a" if da < db else "b"
            while ub - ua > 0 and any(h.intersects(strip(ua, ub)) for h in hit):
                if side == "a":
                    ua += 0.05
                else:
                    ub -= 0.05
            return ua, ub, side

        def module_up(r):
            if typ == "hesco_line":
                return max(1, math.ceil(r / HC - 1e-6)) * HC
            return 2.99 if r < 2.99 else r

        def module_down(r):
            if typ == "hesco_line":
                return math.floor(r / HC + 1e-6) * HC
            return 2.99 if r >= 2.99 - 1e-6 else 0.0

        def segs(lo_):
            out, u0 = [], lo_
            for sl in seglens:
                out.append((u0, u0 + sl))
                u0 += sl
            return out

        # pass 1: where a building cuts a module, shift the whole screen away from it so that the cut module becomes a whole
        # module (HESCO: whole cells; 20 ft stack -> 10 ft stack) ending where the building begins -- coverage never shrinks
        shifts = []
        for ua, ub in segs(lo):
            hit = [bp_ for bp_ in blds if bp_.intersects(strip(ua, ub))]
            if hit:
                ta, tb, side = trim(ua, ub, hit)
                need = max(0.0, module_up(tb - ta) - (tb - ta))
                need = need + 0.06 if need > 0 else 0.0          # + one trim step (0.05) of margin
                shifts.append(-need if side == "b" else need)
        if shifts and (all(v >= 0 for v in shifts) or all(v <= 0 for v in shifts)):
            lo += max(shifts, key=abs)
        # pass 2: place whole modules only; a module still cut by a building is rounded down (anchored to its neighbour)
        for i, (ua, ub) in enumerate(segs(lo)):
            typ_i = typ
            hit = [bp_ for bp_ in blds if bp_.intersects(strip(ua, ub))]
            if hit:
                ta, tb, side = trim(ua, ub, hit)
                m = module_down(tb - ta + 1e-6)
                if m < 1.0:
                    continue
                if side == "b":
                    ub = ua + m
                else:
                    ua = ub - m
                if any(h.intersects(strip(ua, ub)) for h in hit):
                    continue
                if typ == "container_stack_2":
                    typ_i = "container_stack_2_10ft"
            u = (ua + ub) / 2
            pc = c + nrm * u
            PROPS.append({"id": f"P_SCREEN_{t.upper()}_{int(s_)}_{i + 1}", "type": typ_i, "position": [r2(pc[0]), r2(pc[1]), None],
                          "rotation_deg": r2(rot % 360), "size": [round(ub - ua, 3), 1.1 if typ == "hesco_line" else 2.44, hgt],
                          "cover": "high", "blocks_bullets": True, "blocks_vision": True, "cluster": f"spawn_screen_{t}",
                          "note": f"hard spawn screen of row s={s_:.0f} ({', '.join(zids)}), {dist} m in front of the front rank, "
                                  f"needs {req:.2f} m of {hgt} m; ends open as chicane exits"})


def finalize_heights():
    LAYOUT["terrain"]["detail_noise"] = detail_layer()
    for sb in SEC:
        if sb["position"][2] is None:
            sb["position"][2] = r2(gz(sb["position"][0], sb["position"][1]))
    for pr in PROPS:
        if pr["position"][2] is None:
            pr["position"][2] = r2(gz(pr["position"][0], pr["position"][1]))
    for br in bridges:
        if br["deck_z"] is None:
            br["deck_z"] = [r2(gz(*br["ends"][0])), r2(gz(*br["ends"][1]))]


# =================================================================================================
# 10.  Assemble + write
# =================================================================================================
def vertical_steps():
    """Both faces of every vertical terrain step, for constrained triangulation in the terrain generator."""
    out = []
    rwt = {rw["id"]: rw for rw in retaining_walls}
    for st in stamps:
        if st["kind"] == "wall":
            t = rwt[st["id"]]["thickness"]
            left = offset_polyline(st["polyline"], t / 2)
            right = offset_polyline(st["polyline"], -t / 2)
            hi, lo = (left, right) if st["high_side"] == "left" else (right, left)
            out.append({"stamp": st["id"], "type": "retaining_wall",
                        "high_face": [[p[0], p[1], st["top_z"][min(i, len(st["top_z"]) - 1)]] for i, p in enumerate(hi)],
                        "low_face": [[p[0], p[1], st["bottom_z"][min(i, len(st["bottom_z"]) - 1)]] for i, p in enumerate(lo)],
                        "rule": "insert both face polylines as constraint edges of the terrain triangulation (vertices every <= 1 m "
                                "along them); drop the triangles between the faces (the wall mesh occupies that band); the terrain on "
                                "each side is sampled from the reference implementation on its own side of the wall"})
        if st["kind"] in ("channel", "ditch"):
            for k, vs in enumerate(st.get("vertical_sections", [])):
                sub = resample([[p[0], p[1]] for p in st["polyline"]], vs["s0"], vs["s1"])
                out.append({"stamp": f"{st['id']}_VS{k}", "type": "masonry_abutment", "of": st["id"],
                            "left_face": offset_polyline(sub, vs["half_width"]), "right_face": offset_polyline(sub, -vs["half_width"]),
                            "rule": "vertical masonry faces of the channel between arc lengths s0..s1: constraint edges as for walls"})
    return out


def bake_reference(layout):
    from PIL import Image
    X, Y, Hh = T.heightfield(layout, 0.5)
    z0 = float(np.floor(Hh.min() * 100) / 100)
    z1 = float(np.ceil(Hh.max() * 100) / 100)
    img = np.round((Hh - z0) / (z1 - z0) * 65535).astype(np.uint16)[::-1, :]     # row 0 = north
    Image.fromarray(img).save(os.path.join(OUT, "terrain_ref_0p5m.png"))
    layout["terrain"]["reference_bake"] = {
        "file": "Shared/level/terrain_ref_0p5m.png", "encoding": "16-bit grayscale PNG, z = z_min + v / 65535 * (z_max - z_min); "
        "row 0 = north (y = +175), column 0 = west (x = -175)", "resolution": 0.5, "size": [int(img.shape[1]), int(img.shape[0])],
        "z_min": z0, "z_max": z1, "tolerance": "the terrain generator's output must match this bake within 0.02 m (vertical steps excepted "
                                              "within 0.5 m of a face)"}


DRAINAGE = {
    "principle": "every surface has somewhere to drain (ENV-01): roofs -> gutters -> downpipes -> gullies / splash blocks / wall "
                 "outlets; yards fall 1 % to channels; roads to ditches; everything ends in the Kalný potok",
    "roads": [{"id": "DITCH_A", "serves": "ROAD_A south side", "outfall": "brook west of footbridge A"},
              {"id": "DITCH_C", "serves": "TRACK_C south-west side", "outfall": "culvert under DRIVE_DUM, inlet grate G_NV2 at the square, "
                                                                                 "pipe to the brook"},
              {"id": "ROAD_B_gutter", "serves": "ROAD_B", "detail": "granite kerb gutter on the east side, gullies every 25 m, "
                                                                     "outfall into the brook below the main bridge"}],
    "gullies": [{"id": "G_NV1", "pos": [-4.0, -14.0], "serves": "square south edge gutter + RW_DUM spouts"},
                {"id": "G_NV2", "pos": [6.0, -10.5], "serves": "square east edge + DITCH_C culvert"},
                {"id": "G_NV3", "pos": [-10.5, 10.0], "serves": "square north-west corner"}],
    "culverts": [{"under": "DRIVE_DUM", "pipe": "concrete DN600"}, {"under": "TRACK_C at the square", "pipe": "concrete DN400"}],
    "retaining_walls": {"RW_DILNA": "weep holes every 2.0 m 0.30 m above the rear pad; stone channel at the foot",
                        "RW_DUM": "weep holes every 2.0 m; two stone spouts for the house drains (see retaining_walls.outlets)"},
    "buildings": "per building in buildings.json (downpipes[].outlet, drainage)",
    "mill_race": "dry since 1952; the intake sluice at the weir is closed (a trickle and mud decals in the bed)",
}


def main():
    import ivpost as POST   # trees, surfaces, lanes, cover points, analysis-derived data
    spawn_screens()
    finalize_heights()
    layout = {
        "schema": "ironvalley.layout/1",
        "meta": {"name": "Kalné Hamry (fiktivní obec)", "map_id": "kalne_hamry", "status": "final design (lead-designer merge), binding",
                 "date": "2026-09-26", "extent": [[-175, -175], [175, 175]], "units": "m",
                 "coordinate_system": "Blender world, metres, Z up, +X east, +Y north, origin = map centre (village square); rotations in "
                                      "degrees about +Z, counter-clockwise, 0 = local +Y (front) facing north; character yaw: facing vector "
                                      "(-sin yaw, cos yaw), 0 = looking north, 90 = looking west",
                 "axis_conversions": {
                     "threejs": "three(x, y, z) = blender(x, z, -y); yaw unchanged (CCW seen from above, 0 = -Z_three = north); "
                                "same as Web/src/data/test_range.json",
                     "unreal": "UE(cm) = (100 x, -100 y, 100 z); yaw_UE = -yaw (UE is left-handed, +Y_UE = south here); FBX export "
                               "'Y forward, Z up' from Blender (import NOT TESTED)",
                     "recast": "recast(x, y, z) = blender(x, z, -y) (Y up), identical to three.js"},
                 "z": "all z values are absolute metres in this frame; building-local z is relative to the building floor",
                 "character": {"capsule_radius": 0.35, "height": 1.80, "crouch_height": 1.20, "eye_height": 1.65, "max_step": 0.40,
                               "max_slope_deg": 45.0, "source": "Web/src/data/movement.json"},
                 "rules_ref": "Shared/config/rules.json (zone ids zone_dilna / zone_sklad / zone_dvur, teams alfa/bravo/charlie)",
                 "design_docs": ["Docs/MAP_DESIGN.md", "Docs/ART_DIRECTION.md"],
                 "round_fiction": {
                     "briefing_cs": "Kalné Hamry, údolí Kalného potoka. Obec je evakuovaná a armáda údolí uzavřela kordonem a minovými "
                                    "poli. Každé kolo shodí vrtulník zásobovací bednu s rádiovým převaděčem na jedno ze tří míst v "
                                    "obci. Kdo ji udrží, vyhrává.",
                     "why_zone_moves": "a supply cache with a radio relay is dropped at one of three places each round (violet smoke marks it)",
                     "why_boundary": "the valley is sealed by an army cordon: roadblocks on the three roads, deer fences with minefield "
                                     "signs on the spurs"},
                 "collision_semantics": {
                     "_columns": ["movement (capsule)", "bullets (hitscan)", "player vision", "AI vision", "proxy"],
                     "terrain": [True, True, True, True, "BVH of 0.5 m LOD0 chunks inside the hard boundary + 10 m"],
                     "walls_slabs_roofs": [True, True, True, True, "the construction boxes of buildings.json (identical to render geometry)"],
                     "windows": ["clip plane", False, False, False, "1 quad per opening; glass passes hits and vision in v1"],
                     "translucent_polycarbonate": ["clip plane", False, True, True, "1 quad"],
                     "door_leaves": ["kinematic", True, True, True, "thin box driven by the door state machine, never dynamic"],
                     "stairs": ["inclined plane nosing-to-nosing", "stepped mesh", True, True, "ramp collider + stepped render/bullet mesh"],
                     "balustrades_railings_wire_picket_fences": [True, False, False, False, "boxes"],
                     "low_walls_parapets_retaining_walls_hesco": [True, True, True, True, "boxes / swept boxes"],
                     "hedges_shrub_belts_copses": [True, False, True, True,
                                                   "core box (blocks movement) + vision volume dense to the ground; NOT cover"],
                     "props": [True, "per prop blocks_bullets", "per prop blocks_vision", "per prop blocks_vision", "boxes / hulls"],
                     "soft_furniture": [True, False, True, True, "concealment, not cover"],
                     "tree_trunks": [True, True, True, True, "cylinder to crown base"],
                     "tree_crowns": [False, False, "partial", "partial (probability 0.5 per crown crossing)", "vision only, never used for spawn safety"],
                     "boundary_hard": [True, False, False, False, "extruded clip wall 6 m high"]}},
        "terrain": {
            "base_grid": {"origin": [-175.0, -175.0], "spacing": 5.0, "size": [71, 71], "order": "heights[j][i]: row j -> y = -175 + 5j, "
                          "column i -> x = -175 + 5i", "interpolation": "Catmull-Rom bicubic, clamped at the border", "heights": GRID.tolist()},
            "base_formula_doc": {"valley_axes": T.VALLEY_AXES, **T.BASE_PARAMS,
                                 "note": "documentation of how base_grid was produced (ivterrain.base_analytic); base_grid is authoritative"},
            "detail_noise": LAYOUT["terrain"]["detail_noise"],
            "stamps_order": "applied exactly in list order; see Tools/level/lib/ivterrain.py apply_stamps() for the reference implementation",
            "stamps": stamps,
            "reference_bake": {"file": "analysis/terrain_ref_0p5m.png", "encoding": "16-bit grayscale, z = zmin + v/65535*(zmax-zmin)",
                               "resolution": 0.5, "note": "generator output must match within 0.02 m"},
            "backdrop": {"type": "distant_hills_ring", "inner_radius": 260, "outer_radius": 2400,
                         "profile": "low-poly ring, crest heights 60-180 m above the square, forested (beech/spruce mix, 2 LODs + impostor band)",
                         "gaps": "valley A opens WSW (lower valley, a church spire of the next village 2.1 km away), valley B continues N "
                                 "into a wooded gorge, valley C climbs SE to fields and a ridge line with a wind-bent lime alley"},
        },
        "water": [{"id": "BROOK_WATER", "polyline": [[p[0], p[1], r2(p[2] + 0.25)] for p in BROOK], "width_at_surface": 2.35,
                   "depth": 0.25, "flow": "towards the WSW end", "material": "shallow_brook_water",
                   "gameplay": "walkable (speed x0.75, splash footsteps); banks 1:1.5 walkable except masonry abutments at BR_MAIN"}],
        "roads": [
            {"id": "ROAD_A", "surface": "asphalt", "polyline": with_z(RA_XY, RA_Z), "width": 6.0, "shoulders": {"width": 0.75, "surface": "gravel"},
             "markings": "none (village road), worn edges, patched cracks", "leads_to": "lower valley (WSW), boundary roadblock behind spawn alfa"},
            {"id": "ROAD_B", "surface": "asphalt", "polyline": with_z(RB_XY, RB_Z), "width": 6.0, "shoulders": {"width": 0.75, "surface": "gravel"},
             "markings": "none", "leads_to": "gravel works (N), boundary roadblock behind spawn bravo"},
        ],
        "tracks": [
            {"id": "TRACK_C", "surface": "dirt_track_gravel_centre", "polyline": with_z(TC_XY, TC_Z), "width": 3.6,
             "detail": "two wheel ruts (dirt/mud, 0.5 wide, 0.08 deep) + grassy centre strip", "leads_to": "farm (SE), roadblock behind spawn charlie"},
            {"id": "DRIVE_DUM", "surface": "concrete_slabs", "polyline": DRIVE, "width": 3.2, "role": "driveway up to the house terrace"},
            {"id": "RAMP_SKLAD_E", "surface": "gravel", "polyline": RAMP_SKLAD_E, "width": 5.0,
             "role": "field access ramp: warehouse rear yard <-> E ring path (the only link through the 4 m cut bank)"},
        ],
        "paths": [{"id": k, **v} for k, v in PATHS.items()],
        "ditches": [
            {"id": "DITCH_C", "polyline": with_z(DITCH_C_XY, DITCH_C_Z), "bed_width": 0.5, "depth": 0.85, "bank_slope_h_per_v": 1.2,
             "surface": "mud_grass", "culverts": ["under DRIVE_DUM (concrete pipe 0.6)", "inlet grate at the square (to the brook)"],
             "gameplay": "crouch lane: 0.85 m deep, a crouched player (1.20) is covered from the track"},
            {"id": "DITCH_A", "polyline": with_z(DITCH_A_XY, DITCH_A_Z), "bed_width": 0.5, "depth": 0.80, "bank_slope_h_per_v": 1.2,
             "surface": "mud_grass", "gameplay": "crouch lane along the S side of road A"},
            {"id": "MILLRACE", "polyline": with_z(MILL_XY, MILL_Z), "bed_width": 0.9, "depth": 0.6, "surface": "stone_lined_dry",
             "gameplay": "dry, stone-lined mill race along the path P_MILLRACE: 0.6 m, not a crouch lane (too narrow), visual + footstep surface"},
        ],
        "bridges": bridges,
        "retaining_walls": retaining_walls,
        "fences_walls_hedges": FENCES,
        "vegetation_blocks": VEG,
        "buildings": main_buildings,
        "secondary_buildings": SEC,
        "prop_catalog": CATALOG,
        "props": PROPS,
        "capture_zones": zones,
        "spawn_areas": spawn_areas,
        "spawn_spines": {t: {**{k: v for k, v in sp.items() if k != "xy"}, "spine_polyline": SPINE_XY[t]} for t, sp in SPINES.items()},
        "boundary": {"soft_polygon": SOFT},
    }
    layout["terrain"]["vertical_steps"] = vertical_steps()
    POST.finish(layout)
    layout["drainage"] = DRAINAGE
    bake_reference(layout)
    with open(os.path.join(OUT, "layout.json"), "w") as f:
        json.dump(layout, f, ensure_ascii=False, indent=1)
    bjson = {"schema": "ironvalley.buildings/1",
             "conventions": IB.__doc__.strip(),
             "units": "m", "buildings": IB.all_buildings()}
    with open(os.path.join(OUT, "buildings.json"), "w") as f:
        json.dump(bjson, f, ensure_ascii=False, indent=1)
    print("written", os.path.join(OUT, "layout.json"), os.path.join(OUT, "buildings.json"))


if __name__ == "__main__":
    main()
