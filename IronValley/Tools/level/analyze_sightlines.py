#!/usr/bin/env python3
"""
analyze_sightlines.py -- zone exposure metrics for "Kalné Hamry" (IRON VALLEY), to be re-run after every layout edit.

Observers: every walkable ground cell of the main walk component on a 4 m grid inside the soft boundary, eye 1.65 m.
Targets:   walkable zone cells on a 4 m grid, torso height 1.2 m above the floor.
Occluders: the 3D LOS model of check_layout.py (terrain, construction boxes with window openings, roofs, closed buildings,
           hard props, walls, HESCO/containers); with --vegetation also the vision proxies of hedges, shrub belts, copses
           and windbreaks (dense to the ground, collision_semantics); tree crowns are never used.

Metrics per zone:
  area_seeing_any_m2                observer area that sees at least one zone target
  max_dist_seeing_any_m             farthest observer that sees a zone target
  area_gt100m_seeing_ge25pct_m2     long-range exposure: observers > 100 m away that see >= 25 % of the zone
  attack_sectors_20_80m_ge10pct     number of 45 deg sectors (of 8) from which the zone is seen (>= 10 %) at 20-80 m
  elevated_overwatch_cells          observers <= 80 m away, eye >= 4 m above the zone floor, seeing >= 40 % of the zone
  upper_window_fraction_seen        share of the zone seen from each upper-floor window firing position next to it

Output: Tools/level/_out/sightlines.json or sightlines_veg.json (read by draw_plans.py for Docs/MAP_DESIGN.md).
Usage:  python3 Tools/level/analyze_sightlines.py [--vegetation]
"""
import argparse
import json
import math
import os
import sys
import time

import numpy as np
from shapely.geometry import Polygon

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "lib"))
import check_layout as C          # noqa: E402
import ivterrain as T             # noqa: E402

STEP = 4.0


def vegetation_boxes(L):
    """oriented vision boxes (cx, cy, hx, hy, rot, z0, z1) of every vision-blocking vegetation proxy."""
    out = []

    def gz(x, y):
        return float(T.height_at(L, x, y)[0])

    def seg(a, b, w, h):
        cx, cy = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
        ln = math.hypot(b[0] - a[0], b[1] - a[1])
        if ln < 0.05:
            return
        z = min(gz(a[0], a[1]), gz(b[0], b[1]), gz(cx, cy))
        out.append((cx, cy, ln / 2, w / 2, math.atan2(b[1] - a[1], b[0] - a[0]), z - 0.5, z + h))
    for v in L["vegetation_blocks"]:
        if not v.get("blocks_vision", True):
            continue
        if "polyline" in v:
            for a, b in zip(v["polyline"][:-1], v["polyline"][1:]):
                seg(a, b, v["width"], v["height"])
        else:
            r = Polygon(v["polygon"]).minimum_rotated_rectangle
            c = list(r.exterior.coords)[:4]
            e1 = (c[1][0] - c[0][0], c[1][1] - c[0][1])
            e2 = (c[2][0] - c[1][0], c[2][1] - c[1][1])
            cc = r.centroid
            z = min(gz(p[0], p[1]) for p in c)
            out.append((cc.x, cc.y, math.hypot(*e1) / 2, math.hypot(*e2) / 2, math.atan2(e1[1], e1[0]), z - 0.5, z + v["height"]))
    for f in L["fences_walls_hedges"]:
        if "hedge" in f["type"] and f.get("blocks_vision"):
            for a, b in zip(f["polyline"][:-1], f["polyline"][1:]):
                seg(a, b, 0.8, f["height"])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vegetation", action="store_true")
    a = ap.parse_args()
    t0 = time.time()
    L = json.load(open(C.LAYOUT))
    B = json.load(open(C.BUILDINGS))
    W = C.Walk(L, B)
    los = C.LOS(L, B, W)
    nveg = 0
    if a.vegetation:
        vb = vegetation_boxes(L)
        nveg = len(vb)
        los.boxes = np.vstack([los.boxes, np.array(vb, float)])
    xs = np.arange(-172.0, 173.0, STEP)
    obs = []
    for x in xs:
        for y in xs:
            j, i = W.ij(x, y)
            if W.walk[j, i] and W.lab[j, i] == W.main_comp:
                obs.append((x, y, W.F[j, i]))
    obs = np.array(obs)
    res = {"method": __doc__.split("Output:")[0].strip(), "vegetation": a.vegetation, "vegetation_boxes": nveg,
           "observers": int(len(obs)), "grid_m": STEP, "zones": {}}
    for z in L["capture_zones"]:
        samp = C.zone_samples(L, B, W, z, spacing=STEP)
        tg = np.array([(x, y, f + 1.2) for x, y, f in samp])
        cx, cy = z["center"]
        zf = float(np.mean([s_[2] for s_ in samp]))
        d = np.hypot(obs[:, 0] - cx, obs[:, 1] - cy)
        frac = np.zeros(len(obs))
        for k in np.nonzero(d <= 260)[0]:
            o = obs[k]
            frac[k] = los.visible((o[0], o[1], o[2] + C.EYE), tg).mean()
        seen = frac > 0
        far25 = (d > 100) & (frac >= 0.25)
        sectors = sorted({int((math.degrees(math.atan2(obs[k, 0] - cx, obs[k, 1] - cy)) % 360) // 45)
                          for k in np.nonzero((d >= 20) & (d <= 80) & (frac >= 0.10))[0]})
        elev = (d <= 80) & (obs[:, 2] >= zf + 4.0) & (frac >= 0.40)
        win = [cp for cp in L["cover_points"]["points"]
               if cp.get("kind") == "window" and cp.get("level") not in (None, "L0") and z["id"] in cp["zones"]]
        wf = {cp["object"]: round(float(los.visible((cp["pos"][0], cp["pos"][1], cp["pos"][2] + C.EYE), tg).mean()), 2) for cp in win}
        res["zones"][z["id"]] = {
            "zone_targets": int(len(tg)),
            "area_seeing_any_m2": int(seen.sum() * STEP * STEP),
            "max_dist_seeing_any_m": round(float(d[seen].max()), 1) if seen.any() else 0.0,
            "area_gt100m_seeing_ge25pct_m2": int(far25.sum() * STEP * STEP),
            "attack_sectors_20_80m_ge10pct": len(sectors), "sectors": sectors,
            "elevated_overwatch_cells": int(elev.sum()),
            "elevated_overwatch_xyz": [[round(float(v), 1) for v in obs[k]] for k in np.nonzero(elev)[0]],
            "upper_window_fraction_seen": wf,
            "area_seeing_any_by_distance_m2": {f"{lo}-{lo + 50}": int(((d >= lo) & (d < lo + 50) & seen).sum() * STEP * STEP)
                                               for lo in range(0, 250, 50)}}
        print(z["id"], json.dumps({k: v for k, v in res["zones"][z["id"]].items() if k != "elevated_overwatch_xyz"}), flush=True)
    out = os.path.join(HERE, "_out", "sightlines_veg.json" if a.vegetation else "sightlines.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump(res, open(out, "w"), indent=1)
    print(f"written {out} ({time.time() - t0:.0f} s)")


if __name__ == "__main__":
    main()
