#!/usr/bin/env python3
"""
draw_plans.py -- renders the map and building plans of "Kalné Hamry" straight from Shared/level/layout.json and
buildings.json, so the drawings always match the data.

Writes Docs/img/:
  map_plan.png            whole map 350 x 350 m (terrain, roads, water, buildings, props, zones, spawns, boundary)
  map_plan_core.png       village core 150 x 150 m at larger scale (+ cover points and chokepoints)
  map_routes.png          per zone: active spawn rows, primary and flank lanes
  plan_<building>_<level>.png   floor plan of every walkable level (cut plane 1.20 m above the floor)
"""
import json
import math
import os
import sys

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt                                    # noqa: E402
from matplotlib.patches import Polygon as MPoly, Circle, Arc, FancyArrowPatch, Rectangle   # noqa: E402
from matplotlib.collections import PatchCollection                 # noqa: E402
from matplotlib.lines import Line2D                                # noqa: E402
from shapely.geometry import LineString, Polygon                   # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(HERE, "lib"))
import ivterrain as T                                              # noqa: E402

LAYOUT = os.path.join(ROOT, "Shared", "level", "layout.json")
BUILDINGS = os.path.join(ROOT, "Shared", "level", "buildings.json")
IMG = os.path.join(ROOT, "Docs", "img")
TEAM_COL = {"alfa": "#C8A03C", "bravo": "#4E7FB8", "charlie": "#B8574E"}
ZONE_COL = {"zone_dilna": "#7B4FA0", "zone_sklad": "#2E8B7A", "zone_dvur": "#C0607E"}
BNAME = {"B_DILNA": "dilna", "B_SKLAD": "sklad", "B_DUM": "dum"}
BLABEL = {"B_DILNA": "Dílna", "B_SKLAD": "Menší sklad", "B_DUM": "Obytný dům"}
LVLABEL = {"L0": "přízemí", "L1": "patro"}


def cz(v, nd=2):
    return f"{v:.{nd}f}".replace(".", ",")


def xf(c, rot, p):
    a = math.radians(rot)
    return (c[0] + p[0] * math.cos(a) - p[1] * math.sin(a), c[1] + p[0] * math.sin(a) + p[1] * math.cos(a))


def box_poly(center, size, rot):
    L_, W_ = size[0], size[1]
    return [xf(center, rot, p) for p in ((-L_ / 2, -W_ / 2), (L_ / 2, -W_ / 2), (L_ / 2, W_ / 2), (-L_ / 2, W_ / 2))]


def wall_frame(w):
    (sx, sy), (ex, ey) = w["start"], w["end"]
    L_ = math.hypot(ex - sx, ey - sy)
    ux, uy = (ex - sx) / L_, (ey - sy) / L_
    return sx, sy, ux, uy, -uy, ux, L_


def band(ax, pl, width, zorder, cap=2, **kw):
    geom = LineString([p[:2] for p in pl]).buffer(width / 2.0, cap_style=cap, join_style=2, mitre_limit=3.0)
    for gg in getattr(geom, "geoms", [geom]):
        ax.add_patch(MPoly(list(gg.exterior.coords), closed=True, zorder=zorder, **kw))


def stair_poly(sd):
    ux, uy = sd["direction_vector"]
    nx, ny = -uy, ux
    x0, y0 = sd["start"]
    run = sd["run"]
    hw = sd["width"] / 2.0
    return [(x0 + nx * hw, y0 + ny * hw), (x0 + ux * run + nx * hw, y0 + uy * run + ny * hw),
            (x0 + ux * run - nx * hw, y0 + uy * run - ny * hw), (x0 - nx * hw, y0 - ny * hw)]


# =================================================================================================
# map
# =================================================================================================
def draw_map(L, B, fname, ext, res, figsize, core=False, routes_zone=None):
    x0, x1, y0, y1 = ext
    X, Y, H = T.heightfield(L, res, x0, x1, y0, y1)
    fig = plt.figure(figsize=(figsize * 1.25, figsize))
    ax = fig.add_axes([0.04, 0.04, 0.74, 0.90])
    sun = L["environment"]["sun"]
    ls = matplotlib.colors.LightSource(azdeg=sun["azimuth_compass_deg"], altdeg=sun["elevation_deg"])
    cmap = matplotlib.colors.LinearSegmentedColormap.from_list("iv", ["#93A86C", "#AAB57D", "#C2BD8E", "#C9B79A", "#B7A18A"])
    rgb = ls.shade(H, cmap=cmap, vert_exag=1.6, blend_mode="soft", vmin=-5, vmax=40)
    ax.imshow(rgb, extent=[x0, x1, y0, y1], origin="lower", zorder=0)
    lev = np.arange(-6, 46, 1.0 if core else 2.0)
    cs = ax.contour(X, Y, H, levels=lev, colors="#5b4a3a", linewidths=0.25, alpha=0.5, zorder=1)
    ax.clabel(cs, levels=cs.levels[::(2 if core else 5)], fontsize=6 if core else 5, fmt="%d", inline=True)
    pcol = {"paving_granite_setts": "#B9B3A6", "gravel": "#C9C2AE", "concrete": "#CFCBC2"}
    for st in L["terrain"]["stamps"]:
        if st["kind"] == "pad" and pcol.get(st.get("surface")):
            ax.add_patch(MPoly(st["polygon"], closed=True, fc=pcol[st["surface"]], ec="none", alpha=0.85, zorder=2))
        if st["kind"] == "sunken_lane":
            band(ax, st["polyline"], st["bed_width"] + 2 * 1.8 / st["bank_slope_h_per_v"], 3, cap=1, fc="#6E5B3E", ec="none", alpha=0.55)
            band(ax, st["polyline"], st["bed_width"], 3, cap=1, fc="#9A7B55", ec="none", alpha=0.95)
            P = np.array([[p[0], p[1]] for p in st["polyline"]])
            seg = np.hypot(*np.diff(P, axis=0).T)
            cs_ = np.concatenate([[0], np.cumsum(seg)])
            for exd in st["exits"]:
                sm = (exd["s0"] + exd["s1"]) / 2
                ex_ = np.interp(sm, cs_, P[:, 0])
                ey_ = np.interp(sm, cs_, P[:, 1])
                ax.plot(ex_, ey_, marker="^", color="#3a2c18", ms=5 if core else 3, zorder=4)
    for sa in L["spawn_areas"]:
        ax.add_patch(MPoly(sa["polygon"], closed=True, fc="#CFC6AE", ec="none", alpha=0.6, zorder=2))
    for rd in L["roads"]:
        band(ax, rd["polyline"], rd["width"] + 2 * rd["shoulders"]["width"], 3, fc="#A8A294", ec="none")
        band(ax, rd["polyline"], rd["width"], 3, fc="#55585B", ec="none")
    for tr in L["tracks"]:
        band(ax, tr["polyline"], tr["width"], 3, fc="#A38D6B" if tr["id"] == "TRACK_C" else "#BDB8AE", ec="none")
    for p in L["paths"]:
        band(ax, p["xy"], p["width"], 3, cap=1, fc="#9A7B55", ec="none", alpha=0.85)
    for w in L["water"]:
        band(ax, w["polyline"], 6.5, 3, cap=1, fc="#7F9A8E", ec="none", alpha=0.5)
        band(ax, w["polyline"], w["width_at_surface"], 4, cap=1, fc="#3E6E80", ec="none")
    for d in L["ditches"]:
        mill = d["id"] == "MILLRACE"
        band(ax, d["polyline"], 3.2 if mill else 1.8, 4, cap=1, fc="#7C8F5E" if mill else "#5E7A6E", ec="none", alpha=0.9)
    for br in L["bridges"]:
        band(ax, br["ends"], br["width"], 6, fc="#7A6450" if "timber" in br["type"] else "#9C9A94", ec="#333", lw=0.5)
    sp = L["trees"]["species"]
    crowns, trunks = [], []
    for t in L["trees"]["instances"]:
        x, y, _ = t["pos"]
        if not (x0 - 10 < x < x1 + 10 and y0 - 10 < y < y1 + 10):
            continue
        s = sp[t["species"]]
        crowns.append(Circle((x, y), s["crown_radius"] * t["scale"]))
        trunks.append(Circle((x, y), max(0.25, s["trunk_radius"] * t["scale"])))
    ax.add_collection(PatchCollection(crowns, fc="#3F5E2A", ec="#2C4420", lw=0.2, alpha=0.36, zorder=9))
    ax.add_collection(PatchCollection(trunks, fc="#3B2F22", ec="none", alpha=0.9, zorder=9))
    for f in L["fences_walls_hedges"]:
        xy = np.array(f["polyline"])
        if "hedge" in f["type"]:
            band(ax, f["polyline"], 1.2, 7, cap=1, fc="#44662E", ec="none", alpha=0.95)
        elif "low_wall" in f["type"]:
            band(ax, f["polyline"], 0.35, 7, fc="#6E5A48", ec="none")
        else:
            ax.plot(xy[:, 0], xy[:, 1], color="#555555", lw=0.8, ls=(0, (3, 1.5)), zorder=7)
    for vb in L["vegetation_blocks"]:
        if "polyline" in vb:
            band(ax, vb["polyline"], vb["width"], 7, cap=1, fc="#5C7F3A", ec="#3E5A26", lw=0.3, alpha=0.95)
        else:
            ax.add_patch(MPoly(vb["polygon"], closed=True, fc="#5C7F3A", ec="#3E5A26", lw=0.4, alpha=0.95, zorder=7))
    for rw in L["retaining_walls"]:
        pl = rw["polyline"]
        segs = rw.get("segments") or [[i, i + 1] for i in range(len(pl) - 1)]
        for i0, i1 in segs:
            band(ax, [pl[i0], pl[i1]], rw["thickness"], 8, fc="#3A332C", ec="none")
        for st in rw["stairs"]:
            a_, b_ = np.array(st["bottom_center_world"]), np.array(st["top_center_world"])
            band(ax, [a_, b_], st["width"], 8, fc="#CFCBC2", ec="#333", lw=0.4)
            ax.annotate("", xy=b_, xytext=a_, arrowprops=dict(arrowstyle="-|>", color="#222", lw=0.8), zorder=12)
    for sb in L["secondary_buildings"]:
        emb = sb.get("embedded_in")
        ax.add_patch(MPoly(sb["footprint_world"], closed=True, fc="#8F877D" if not emb else "#B9B3A6",
                           ec="#3C3833", lw=0.6, ls="-" if not emb else "--", zorder=10))
        if "tower" in sb:
            tw = sb["tower"]
            tc = xf(sb["position"][:2], sb["rotation_deg"], tw["offset_local"])
            ax.add_patch(MPoly(box_poly(tc, tw["size"], sb["rotation_deg"]), closed=True, fc="#6E675F", ec="#3C3833", lw=0.6, zorder=10))
        c = np.array(sb["footprint_world"]).mean(axis=0)
        if x0 < c[0] < x1 and y0 < c[1] < y1 and (core or sb["footprint"][0] * sb["footprint"][1] > 60):
            ax.text(c[0], c[1], sb["id"][2:].replace("_", " "), fontsize=6 if core else 4.5, ha="center", va="center",
                    color="white" if not emb else "#333", zorder=11, clip_on=True)
    bdefs = {b["id"]: b for b in B["buildings"]}
    for bp in L["buildings"]:
        bd = bdefs[bp["id"]]
        c, rot = bp["position"][:2], bp["rotation_deg"]
        ax.add_patch(MPoly(bp["footprint_world"], closed=True, fc="#E9E1D2", ec="none", zorder=10))
        wm = {w["id"]: w for w in bd["walls"]}
        for w in bd["walls"]:
            if w["level"] != "L0":
                continue
            sx, sy, ux, uy, nx, ny, Lw = wall_frame(w)
            t = w["thickness"] / 2
            for cb in w["construction_boxes"]:
                if not (cb["z"][0] <= 1.2 <= cb["z"][1]):
                    continue
                u0, u1 = cb["u"]
                q = [(sx + ux * u0 + nx * t, sy + uy * u0 + ny * t), (sx + ux * u1 + nx * t, sy + uy * u1 + ny * t),
                     (sx + ux * u1 - nx * t, sy + uy * u1 - ny * t), (sx + ux * u0 - nx * t, sy + uy * u0 - ny * t)]
                ax.add_patch(MPoly([xf(c, rot, qq) for qq in q], closed=True, fc="#2B2622" if w["kind"] == "external" else "#5A524A",
                                   ec="none", zorder=11))
        for o in bd["openings"]:
            w = wm[o["wall_id"]]
            if w["level"] != "L0" or o["type"] not in ("door", "double_door", "roller_door"):
                continue
            sx, sy, ux, uy, nx, ny, Lw = wall_frame(w)
            a_, b_ = o["offset_from_start"], o["offset_from_start"] + o["width"]
            t = w["thickness"] / 2 + 0.02
            q = [(sx + ux * a_ + nx * t, sy + uy * a_ + ny * t), (sx + ux * b_ + nx * t, sy + uy * b_ + ny * t),
                 (sx + ux * b_ - nx * t, sy + uy * b_ - ny * t), (sx + ux * a_ - nx * t, sy + uy * a_ - ny * t)]
            col = "#F2C14E" if o.get("passes", {}).get("movement", True) else "#888888"
            ax.add_patch(MPoly([xf(c, rot, qq) for qq in q], closed=True, fc=col, ec="none", zorder=12))
        for f_ in bd.get("furniture", []):
            if f_["level"] not in ("L0", "exterior"):
                continue
            poly = [xf(c, rot, q) for q in box_poly(f_["center"], f_["size"], f_.get("rotation_deg", 0))]
            ax.add_patch(MPoly(poly, closed=True, fc={"high": "#9C5B3C", "low": "#D29A5C"}.get(f_["cover"], "#BBBBBB"), ec="none",
                               alpha=0.9, zorder=12))
        if bd.get("loading_dock"):
            ax.add_patch(MPoly([xf(c, rot, q) for q in bd["loading_dock"]["polygon"]], closed=True, fc="#BDB9B0", ec="#555", lw=0.6, zorder=10))
        for s in bd["exterior_stairs"]:
            ax.add_patch(MPoly([xf(c, rot, q) for q in stair_poly(s)], closed=True, fc="#D9D4C8", ec="#333", lw=0.4, zorder=12))
            ld = s.get("landing")
            if ld:
                ax.add_patch(MPoly([xf(c, rot, q) for q in ld["polygon"]], closed=True, fc="#D9D4C8", ec="#333", lw=0.4, zorder=12))
        lc = np.array(bp["footprint_world"]).mean(axis=0)
        ax.text(lc[0], lc[1], {"B_DILNA": "DÍLNA", "B_SKLAD": "SKLAD", "B_DUM": "DŮM"}[bp["id"]], fontsize=11 if core else 7,
                ha="center", va="center", color="#1C1A18", weight="bold", zorder=13, clip_on=True,
                bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.6))
    for p in L["props"]:
        poly = box_poly(p["position"][:2], p["size"], p["rotation_deg"])
        screen = p["id"].startswith("P_SCREEN")
        fc = "#4A5A3A" if screen else {"high": "#7A3E2A", "low": "#D08A3C", "none": "#9C9C9C"}[p["cover"]]
        ax.add_patch(MPoly(poly, closed=True, fc=fc, ec="#1E1E1E", lw=0.4 if screen else 0.3, zorder=12))
    for z in L["capture_zones"]:
        col = ZONE_COL[z["id"]]
        ax.add_patch(MPoly(z["polygon"], closed=True, fc=col, ec=col, lw=2.0, alpha=0.18, zorder=14))
        ax.add_patch(MPoly(z["polygon"], closed=True, fc="none", ec=col, lw=2.0, zorder=14))
        cx, cy = np.array(z["polygon"]).mean(axis=0)
        ax.text(cx, cy + (6 if core else 0), f"{z['name'].upper()}\n{z['area_m2']:.0f} m²", fontsize=9 if core else 7, color=col,
                weight="bold", ha="center", va="center", zorder=20, clip_on=True,
                bbox=dict(boxstyle="round,pad=0.2", fc="white", ec=col, alpha=0.85))
    for sa in L["spawn_areas"]:
        col = TEAM_COL[sa["team"]]
        for rw in sa["rows"]:
            ax.add_patch(MPoly(rw["polygon"], closed=True, fc=col, ec=col, alpha=0.45, lw=1.2, zorder=14))
            c_ = np.array(rw["polygon"]).max(axis=0)
            if x0 < c_[0] < x1 and y0 < c_[1] < y1:
                zl = ",".join({"zone_dilna": "Dílna", "zone_sklad": "Sklad", "zone_dvur": "Dvůr"}[z] for z in rw["zones"])
                ax.text(c_[0] + 1, c_[1], f"{rw['row_id']} ({zl})", fontsize=6 if core else 5, color="k", zorder=16, clip_on=True,
                        bbox=dict(boxstyle="round,pad=0.1", fc="white", ec="none", alpha=0.7))
        for cp in sa["candidate_points"]:
            yaw = math.radians(cp["yaw_deg"])
            x, y = cp["pos"][:2]
            ax.plot(x, y, "o", ms=2.2 if not core else 3, color=col, mec="k", mew=0.3, zorder=15)
    bnd = L["boundary"]
    for key, style in (("soft_polygon", dict(color="#D62728", lw=1.6, ls="--")), ("warning_polygon", dict(color="#E8A33A", lw=0.8, ls=":")),
                       ("hard_polygon", dict(color="#D62728", lw=0.8, ls="-"))):
        P = np.array(bnd[key] + [bnd[key][0]])
        ax.plot(P[:, 0], P[:, 1], zorder=17, **style)
    if core:
        for cp in L["cover_points"]["points"]:
            x, y = cp["pos"][:2]
            if not (x0 < x < x1 and y0 < y < y1):
                continue
            col = {"high": "#1b4f72", "low": "#5dade2", "window": "#8e44ad"}[cp["height"]]
            ax.plot(x, y, marker="s", ms=1.6, color=col, zorder=16, alpha=0.8)
        for ck in L["chokepoints"]:
            if "at" not in ck or ck["type"] in ("door", "double_door", "roller_door", "stair"):
                continue
            pts = ck["at"] if isinstance(ck["at"][0], list) else [ck["at"]]
            m = np.mean(np.array(pts)[:, :2], axis=0)
            ax.plot(m[0], m[1], "X", ms=6, color="#D62728", mec="white", mew=0.5, zorder=18)
    if routes_zone:
        ln = L["lanes"][routes_zone]
        for team, lane in ln["primary"].items():
            P = np.array(lane)
            ax.plot(P[:, 0], P[:, 1], color=TEAM_COL[team], lw=2.2, zorder=19)
        for team, fl in ln["flank"].items():
            P = np.array(fl["waypoints"])
            ax.plot(P[:, 0], P[:, 1], color=TEAM_COL[team], lw=1.4, ls="--", zorder=19)
    # north arrow, sun, scale
    ax.annotate("S", xy=(x1 - 0.06 * (x1 - x0), y1 - 0.04 * (y1 - y0)), xytext=(x1 - 0.06 * (x1 - x0), y1 - 0.11 * (y1 - y0)),
                arrowprops=dict(arrowstyle="-|>", color="k", lw=1.5), ha="center", fontsize=0.1, zorder=30)
    ax.text(x1 - 0.06 * (x1 - x0), y1 - 0.03 * (y1 - y0), "S (sever)", ha="center", va="bottom", fontsize=8, weight="bold", zorder=30)
    az = math.radians(sun["azimuth_compass_deg"])
    sxy = np.array([x1 - 0.15 * (x1 - x0), y1 - 0.08 * (y1 - y0)])
    d = np.array([math.sin(az), math.cos(az)]) * 0.05 * (x1 - x0)
    ax.annotate("", xy=sxy, xytext=sxy + d, arrowprops=dict(arrowstyle="-|>", color="#E0A020", lw=1.4), zorder=30)
    ax.text(*(sxy + d * 1.15), f"slunce\n{sun['azimuth_compass_deg']:.0f}°/{sun['elevation_deg']:.0f}°", fontsize=6, color="#8a6000",
            ha="center", zorder=30)
    sb = 20 if core else 50
    bx, by = x0 + 0.04 * (x1 - x0), y0 + 0.03 * (y1 - y0)
    for k in range(5):
        ax.add_patch(Rectangle((bx + k * sb / 5, by), sb / 5, 0.012 * (y1 - y0), fc="k" if k % 2 == 0 else "white", ec="k", lw=0.5, zorder=30))
    ax.text(bx + sb / 2, by + 0.02 * (y1 - y0), f"{sb} m", ha="center", fontsize=8, zorder=30)
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.set_aspect("equal")
    ax.tick_params(labelsize=7)
    title = "IRON VALLEY – Kalné Hamry (fiktivní) – " + ("jádro obce" if core else "celá mapa 350 × 350 m")
    if routes_zone:
        title = f"Trasy pro zónu {next(z['name'] for z in L['capture_zones'] if z['id'] == routes_zone)}"
    ax.set_title(title + "   |   souřadnice: m, +X východ, +Y sever, počátek = náves", fontsize=10)
    leg = [Line2D([0], [0], color="#55585B", lw=5, label="asfalt (silnice A, B)"),
           Line2D([0], [0], color="#A38D6B", lw=5, label="polní cesta C"),
           Line2D([0], [0], color="#9A7B55", lw=3, label="pěšina / úvoz (▲ výstup)"),
           Line2D([0], [0], color="#3E6E80", lw=4, label="Kalný potok"),
           Line2D([0], [0], color="#7C8F5E", lw=4, label="suchý náhon (krytá dráha)"),
           Line2D([0], [0], color="#5E7A6E", lw=3, label="příkop"),
           Line2D([0], [0], color="#3A332C", lw=4, label="opěrná zeď (šipka = schody nahoru)"),
           Line2D([0], [0], color="#44662E", lw=4, label="živý plot (jen zakrývá)"),
           Line2D([0], [0], color="#5C7F3A", lw=6, label="křoviny / remízek (jen zakrývá)"),
           Line2D([0], [0], color="#6E5A48", lw=3, label="nízká zídka (kryt)"),
           Line2D([0], [0], color="#555555", lw=1, ls="--", label="pletivo / laťkový plot"),
           Line2D([0], [0], marker="s", color="w", markerfacecolor="#7A3E2A", ms=8, label="rekvizita – vysoký kryt"),
           Line2D([0], [0], marker="s", color="w", markerfacecolor="#D08A3C", ms=8, label="rekvizita – nízký kryt"),
           Line2D([0], [0], marker="s", color="w", markerfacecolor="#4A5A3A", ms=8, label="clona spawnu (HESCO / kontejnery)"),
           Line2D([0], [0], marker="s", color="w", markerfacecolor="#8F877D", ms=8, label="uzavřená budova (neprůchozí)"),
           Line2D([0], [0], color="#D62728", lw=1.5, ls="--", label="hranice měkká / tvrdá (plná)"),
           Line2D([0], [0], color="#E8A33A", lw=1, ls=":", label="pás varování 8 m"),
           Line2D([0], [0], marker="o", color="w", markerfacecolor="#999", ms=6, label="spawn řada (8 bodů) + zóny")]
    if core:
        leg += [Line2D([0], [0], marker="s", color="w", markerfacecolor="#1b4f72", ms=5, label="bod krytu vysoký"),
                Line2D([0], [0], marker="s", color="w", markerfacecolor="#5dade2", ms=5, label="bod krytu nízký"),
                Line2D([0], [0], marker="s", color="w", markerfacecolor="#8e44ad", ms=5, label="střelecká pozice u okna"),
                Line2D([0], [0], marker="X", color="w", markerfacecolor="#D62728", ms=8, label="úzké místo")]
    if routes_zone:
        leg += [Line2D([0], [0], color="k", lw=2.2, label="hlavní trasa týmu"), Line2D([0], [0], color="k", lw=1.4, ls="--", label="obchvat")]
    for t, c_ in TEAM_COL.items():
        leg.append(Line2D([0], [0], color=c_, lw=4, label=f"tým {t}"))
    ax.legend(handles=leg, loc="upper left", bbox_to_anchor=(1.01, 1.0), fontsize=7, frameon=True, title="Legenda")
    fig.savefig(fname, dpi=110)
    plt.close(fig)


def draw_routes(L, B, fname):
    fig, axs = plt.subplots(1, 3, figsize=(24, 8.6))
    X, Y, H = T.heightfield(L, 1.0, -175, 175, -175, 175)
    for ax, z in zip(axs, L["capture_zones"]):
        ax.imshow(H, extent=[-175, 175, -175, 175], origin="lower", cmap="Greys", alpha=0.35)
        ax.contour(X, Y, H, levels=np.arange(-6, 46, 2.0), colors="#7a6a5a", linewidths=0.2)
        for rd in L["roads"] + L["tracks"]:
            band(ax, rd["polyline"], rd["width"], 2, fc="#8a8a8a", ec="none")
        for w in L["water"]:
            band(ax, w["polyline"], w["width_at_surface"], 2, cap=1, fc="#3E6E80", ec="none")
        for b in L["buildings"] + L["secondary_buildings"]:
            ax.add_patch(MPoly(b["footprint_world"], closed=True, fc="#555", ec="none", zorder=3))
        for p in L["props"]:
            if p["id"].startswith("P_SCREEN"):
                ax.add_patch(MPoly(box_poly(p["position"][:2], p["size"], p["rotation_deg"]), closed=True, fc="#4A5A3A", ec="k", lw=0.3, zorder=4))
        for zz in L["capture_zones"]:
            ax.add_patch(MPoly(zz["polygon"], closed=True, fc=ZONE_COL[zz["id"]], alpha=0.25 if zz["id"] != z["id"] else 0.6,
                               ec=ZONE_COL[zz["id"]], lw=1.5, zorder=5))
        ln = L["lanes"][z["id"]]
        for team, lane in ln["primary"].items():
            P = np.array(lane)
            ax.plot(P[:, 0], P[:, 1], color=TEAM_COL[team], lw=2.4, zorder=6)
        for team, fl in ln["flank"].items():
            P = np.array(fl["waypoints"])
            ax.plot(P[:, 0], P[:, 1], color=TEAM_COL[team], lw=1.3, ls="--", zorder=6)
        bal = L["balance"]["zones"][z["id"]]
        nav = L.get("navmesh_validation", {}).get("balance", {}).get(z["id"], {})
        for sa in L["spawn_areas"]:
            for rw in sa["rows"]:
                act = z["id"] in rw["zones"]
                ax.add_patch(MPoly(rw["polygon"], closed=True, fc=TEAM_COL[sa["team"]], alpha=0.9 if act else 0.15, ec="k", lw=0.5, zorder=7))
                if act:
                    c = np.array(rw["polygon"]).mean(axis=0)
                    nm = nav.get("teams", {}).get(sa["team"], {}).get("mean_m")
                    ax.text(c[0] + 4, c[1] + 4, f"{rw['row_id']}\nFMM {bal['distances_edge_m'][sa['team']]:.0f} m" +
                            (f"\nRecast {nm:.0f} m" if nm else ""), fontsize=7, zorder=8,
                            bbox=dict(boxstyle="round,pad=0.2", fc="white", ec=TEAM_COL[sa["team"]], alpha=0.85))
        sb = L["boundary"]["soft_polygon"]
        P = np.array(sb + [sb[0]])
        ax.plot(P[:, 0], P[:, 1], "r--", lw=1, zorder=5)
        ax.set_xlim(-175, 175)
        ax.set_ylim(-175, 175)
        ax.set_aspect("equal")
        ax.tick_params(labelsize=6)
        mm = nav.get("max_over_min")
        ax.set_title(f"Zóna {z['name']}: aktivní spawn řady, hlavní trasy (plné) a obchvaty (čárkované)\n"
                     f"max/min vzdálenost FMM {max(bal['distances_edge_m'].values()) / min(bal['distances_edge_m'].values()):.3f}"
                     + (f", Recast navmesh {mm:.3f}" if mm else ""), fontsize=9)
    fig.tight_layout()
    fig.savefig(fname, dpi=100)
    plt.close(fig)


# =================================================================================================
# floor plans
# =================================================================================================
def draw_floorplan(L, bd, level, fname):
    bp = next(b for b in L["buildings"] if b["id"] == bd["id"])
    lv = next(l for l in bd["levels"] if l["id"] == level)
    zf_world = bp["position"][2]
    CUT = 1.20
    pts = [p for part in bd["footprint_parts"] for p in part["external_rect"]]
    for s in bd["stairs"] + bd["exterior_stairs"]:
        pts += stair_poly(s)
        if s.get("landing"):
            pts += s["landing"]["polygon"]
    if bd.get("loading_dock"):
        pts += bd["loading_dock"]["polygon"]
    for st in bd.get("exterior_steps", []):
        for k in ("polygon", "rect"):
            if k in st:
                pts += st[k]
    P = np.array(pts)
    x0, y0 = P.min(axis=0) - 2.0
    x1, y1 = P.max(axis=0) + 2.0
    w_in = 15.0
    h_in = w_in * (y1 - y0) / (x1 - x0)
    fig = plt.figure(figsize=(w_in + 4.2, max(7.5, h_in + 1.6)))
    ax = fig.add_axes([0.04, 0.06, w_in / (w_in + 4.2) * 0.95, 0.86])
    ax.set_facecolor("#FBFAF7")
    wm = {w["id"]: w for w in bd["walls"]}
    # rooms
    for r in bd["rooms"]:
        if r["level"] != level:
            continue
        ax.add_patch(MPoly(r["polygon"], closed=True, fc="#F1EBDD" if not r.get("in_zone") else "#EFE0EF", ec="none", zorder=1))
        rp = Polygon(r["polygon"])
        c = rp.representative_point()
        ax.text(c.x, c.y, f"{r['name']}\n{cz(rp.area, 1)} m²  sv. v. {cz(r['ceiling_height'])}\n{r['id']}", fontsize=7.5, ha="center",
                va="center", color="#3a3226", zorder=20, bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="none", alpha=0.75))
    for v in bd.get("sealed_voids", []):
        if v["level"] != level:
            continue
        ax.add_patch(MPoly(v["polygon"], closed=True, fc="#D8D8D8", ec="#777", lw=0.5, hatch="xxx", zorder=2))
    # slab openings on this level
    for sl in bd.get("slabs", []):
        if sl["level"] != level:
            continue
        for h in sl.get("openings", []):
            ax.add_patch(MPoly(h["polygon"], closed=True, fc="white", ec="#555", lw=0.8, ls="--", zorder=2))
            c = Polygon(h["polygon"]).centroid
            ax.text(c.x, c.y, "průhled\n(bez podlahy)", fontsize=6.5, ha="center", va="center", color="#666", zorder=3)
    # exterior surfaces
    if level == "L0" and bd.get("loading_dock"):
        ax.add_patch(MPoly(bd["loading_dock"]["polygon"], closed=True, fc="#D5D0C5", ec="#444", lw=0.8, hatch="..", zorder=1))
        c = Polygon(bd["loading_dock"]["polygon"]).centroid
        ax.text(c.x, c.y, "nakládací rampa +0,00 (dvůr −1,10)", fontsize=7, ha="center", va="center", zorder=3)
    for st in bd.get("exterior_steps", []):
        if level != "L0":
            continue
        if "polygon" in st:
            ax.add_patch(MPoly(st["polygon"], closed=True, fc="#E3DED3", ec="#444", lw=0.6, zorder=2))
            c = Polygon(st["polygon"]).centroid
            lab = {"ramp": f"rampa {cz(st.get('slope_pct', 0), 1)} %", "step": f"stupeň {cz(st.get('riser', 0))}", "threshold": "práh"}.get(st["type"], "")
            if st.get("apron"):
                ax.add_patch(MPoly(st["apron"]["polygon"], closed=True, fc="none", ec="#999", lw=0.5, ls=":", zorder=2))
            ax.text(c.x, c.y, lab, fontsize=5.5, ha="center", va="center", zorder=3, color="#333")
        if st["type"] == "canopy":
            ax.add_patch(MPoly(st["rect"], closed=True, fc="none", ec="#1F4E79", lw=0.8, ls="-.", zorder=3))
    for ba in bd.get("balconies", []):
        if ba["level"] != level:
            continue
        ax.add_patch(MPoly(ba["polygon"], closed=True, fc="#E6E0D0", ec="#444", lw=0.8, zorder=2))
        for a_, b_ in ba["parapet"]["segments"]:
            band(ax, [a_, b_], ba["parapet"]["thickness"], 11, fc="#6B5A48", ec="none")
        c = Polygon(ba["polygon"]).centroid
        ax.text(c.x, c.y + 0.3, f"balkon +{cz(ba['top_z'])}\nplné zábradlí {cz(ba['parapet']['height'])} m", fontsize=6.5, ha="center",
                va="center", zorder=21, bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="none", alpha=0.7))
    # walls: construction boxes cut at 1.20 m (solid) or below the cut (outline)
    for w in bd["walls"]:
        if w["level"] != level:
            continue
        sx, sy, ux, uy, nx, ny, Lw = wall_frame(w)
        t = w["thickness"] / 2
        for cb in w["construction_boxes"]:
            u0, u1 = cb["u"]
            q = [(sx + ux * u0 + nx * t, sy + uy * u0 + ny * t), (sx + ux * u1 + nx * t, sy + uy * u1 + ny * t),
                 (sx + ux * u1 - nx * t, sy + uy * u1 - ny * t), (sx + ux * u0 - nx * t, sy + uy * u0 - ny * t)]
            if cb["z"][0] <= CUT <= cb["z"][1]:
                col = "#2B2622" if w["kind"] == "external" else ("#6B6258" if w["thickness"] < 0.2 else "#3F3934")
                if "stud" in w["material"]:
                    col = "#8C8276"
                ax.add_patch(MPoly(q, closed=True, fc=col, ec="none", zorder=10))
            elif cb["z"][1] < CUT:
                ax.add_patch(MPoly(q, closed=True, fc="#CFC8BC", ec="#2B2622", lw=0.4, zorder=9))
    for o in bd["openings"]:
        w = wm[o["wall_id"]]
        if w["level"] != level:
            continue
        sx, sy, ux, uy, nx, ny, Lw = wall_frame(w)
        a_, b_ = o["offset_from_start"], o["offset_from_start"] + o["width"]
        t = w["thickness"] / 2
        p0 = np.array([sx + ux * a_, sy + uy * a_])
        p1 = np.array([sx + ux * b_, sy + uy * b_])
        n = np.array([nx, ny])
        mid = (p0 + p1) / 2
        if o["type"] == "window":
            ls_ = "-" if o["sill_height"] < CUT < o["head_height"] else "--"
            for off in (-t * 0.35, t * 0.35):
                ax.plot([p0[0] + n[0] * off, p1[0] + n[0] * off], [p0[1] + n[1] * off, p1[1] + n[1] * off], color="#2E86C1", lw=0.9, ls=ls_, zorder=12)
            ax.text(*(mid + n * (t + 0.35)), f"{o['id'].split('_')[-1]} {cz(o['sill_height'])}", fontsize=5, ha="center", va="center",
                    color="#2E86C1", zorder=13, rotation=0)
        elif o["type"] == "vent":
            continue
        elif o["type"] == "roller_door":
            walk = o["passes"]["movement"]
            ax.plot([p0[0], p1[0]], [p0[1], p1[1]], color="#1F4E79" if walk else "#C0392B", lw=1.2, ls="--" if walk else "-", zorder=12)
            ax.text(*(mid - n * (t + 0.55)), f"{o['id']} rolovací vrata {cz(o['clear_width'])}×{cz(o['clear_height'])}"
                    + ("" if walk else " ZAVŘENO"), fontsize=6, ha="center", va="center", color="#1F4E79", zorder=13,
                    bbox=dict(boxstyle="round,pad=0.1", fc="white", ec="none", alpha=0.8))
        else:
            side = 1 if o["swing"] == "left" else -1
            face = n * side * t
            ang = math.radians(o.get("open_deg") or 90)
            lt = o.get("leaf", {}).get("thickness", 0.05)
            ja, jb = a_ + o["frame_jamb"], b_ - o["frame_jamb"]
            if o["type"] == "double_door":
                hinges = [(ja, 1, (jb - ja) / 2), (jb, -1, (jb - ja) / 2)]
            elif o["hinge"] == "start":
                hinges = [(ja, 1, jb - ja)]
            else:
                hinges = [(jb, -1, jb - ja)]
            for u0, sg, length in hinges:
                hp = np.array([sx + ux * u0, sy + uy * u0]) + face
                cdir = np.array([ux, uy]) * sg
                pdir = n * side
                tip = hp + (cdir * math.cos(ang) + pdir * math.sin(ang)) * length
                ax.plot([hp[0], tip[0]], [hp[1], tip[1]], color="#1F4E79", lw=1.6, zorder=12)
                a0 = math.degrees(math.atan2(cdir[1], cdir[0]))
                a1 = math.degrees(math.atan2(tip[1] - hp[1], tip[0] - hp[0]))
                lo, hi = (a0, a1) if ((a1 - a0) % 360) < 180 else (a1, a0)
                ax.add_patch(Arc(hp, 2 * length, 2 * length, theta1=lo, theta2=hi, color="#1F4E79", lw=0.5, ls="--", zorder=12))
            ax.text(*(mid - n * side * (t + 0.35)), f"{o['id'].split('_')[-1]} {cz(o['clear_width'])}", fontsize=6, ha="center",
                    va="center", color="#1F4E79", zorder=13, bbox=dict(boxstyle="round,pad=0.1", fc="white", ec="none", alpha=0.8))
    # stairs (drawn on the level they start from; flights arriving here drawn dashed)
    for s in bd["stairs"] + bd["exterior_stairs"]:
        lf = s["level_from"]
        on = (lf == level) or (lf == "ground" and level == "L0") or (lf == "Lmid" and level == "L0")
        arr = s["level_to"] == level and not on
        if not (on or arr):
            continue
        dv = np.array(s["direction_vector"])
        nrm = np.array([-dv[1], dv[0]])
        st0 = np.array(s["start"])
        poly = stair_poly(s)
        ax.add_patch(MPoly(poly, closed=True, fc="#ECE6D8" if on else "none", ec="#333", lw=0.7, ls="-" if on else "--", zorder=5))
        for k in range(s["count"]):
            p = st0 + dv * (k * s["tread"])
            ax.plot(*zip(p + nrm * s["width"] / 2, p - nrm * s["width"] / 2), color="#555", lw=0.5, ls="-" if on else "--", zorder=6)
        ax.add_patch(FancyArrowPatch(tuple(st0 - dv * 0.1), tuple(st0 + dv * s["run"]), arrowstyle="-|>", mutation_scale=10, color="#B03A2E",
                                     lw=1.0, zorder=7))
        lab = f"{s['id']}: {s['count']}×{cz(s['riser'] * 1000, 1)}/{int(round(s['tread'] * 1000))} mm, š {cz(s['width'])}"
        c = st0 + dv * s["run"] / 2 + nrm * (s["width"] / 2 + 0.35)
        ax.text(c[0], c[1], lab, fontsize=6, ha="center", va="center", color="#B03A2E", zorder=21,
                bbox=dict(boxstyle="round,pad=0.1", fc="white", ec="none", alpha=0.85))
        ld = s.get("landing")
        if ld and (ld["level"] == level or (ld["level"] == "Lmid" and level == "L0")):
            ax.add_patch(MPoly(ld["polygon"], closed=True, fc="#E6E0D0", ec="#333", lw=0.6, zorder=4))
            c = Polygon(ld["polygon"]).centroid
            ax.text(c.x, c.y, f"podesta +{cz(ld['z'])}", fontsize=5.5, ha="center", va="center", zorder=8)
    for ba in bd.get("balustrades", []):
        if ba["level"] == level or (ba["level"] == "exterior" and level == "L1") or (ba["level"] == "Lmid" and level == "L0"):
            P2 = np.array(ba["polyline"])
            ax.plot(P2[:, 0], P2[:, 1], color="#7D3C98", lw=1.4, zorder=11, marker="|", ms=4)
    for f in bd.get("furniture", []):
        if f["level"] != level and not (f["level"] == "exterior" and level == "L0"):
            continue
        fc = {"high": "#9C5B3C", "low": "#D29A5C"}.get(f["cover"], "#C8C8C8")
        ax.add_patch(MPoly(box_poly(f["center"], f["size"], f.get("rotation_deg", 0)), closed=True, fc=fc, ec="#333", lw=0.4, alpha=0.9, zorder=8))
        ax.text(f["center"][0], f["center"][1], f["type"].replace("_", " ")[:18], fontsize=4.5, ha="center", va="center", zorder=9, color="#222")
    for col in bd.get("columns", []):
        ax.add_patch(MPoly(box_poly(col["center"], col["size"], 0), closed=True, fc="k", ec="none", zorder=11))
    for ch in bd.get("chimneys", []):
        ax.add_patch(MPoly(box_poly(ch["pos"], ch.get("size", [0.3, 0.3]), 0), closed=True, fc="#8B4513", ec="k", lw=0.5, hatch="////", zorder=11))
    # zone outline (local frame) on the ground floor
    for z in L["capture_zones"]:
        if bp.get("zone") != z["id"]:
            continue
        a = math.radians(bp["rotation_deg"])
        c0 = bp["position"][:2]
        loc = [((x - c0[0]) * math.cos(a) + (y - c0[1]) * math.sin(a), -(x - c0[0]) * math.sin(a) + (y - c0[1]) * math.cos(a)) for x, y in z["polygon"]]
        inband = z["z_min"] <= zf_world + lv["floor_z"] <= z["z_max"]
        ax.add_patch(MPoly(loc, closed=True, fc="none", ec=ZONE_COL[z["id"]], lw=2.0, ls="-" if inband else ":", zorder=15))
        note = (f"zóna {z['name']}: počítá se" if inband else f"zóna {z['name']}: toto podlaží se NEPOČÍTÁ") + \
               f" (z {cz(z['z_min'])}–{cz(z['z_max'])} m, podlaha {cz(zf_world + lv['floor_z'])} m)"
        ax.text(0.01, 0.01, note, transform=ax.transAxes, fontsize=8, color=ZONE_COL[z["id"]], weight="bold", zorder=30)
    # dimensions
    ext = np.array([p for part in bd["footprint_parts"] for p in part["external_rect"]])
    ex0, ey0 = ext.min(axis=0)
    ex1, ey1 = ext.max(axis=0)

    def dim(p, q, off, txt, vertical=False):
        p = np.array(p, float)
        q = np.array(q, float)
        o = np.array([off, 0]) if vertical else np.array([0, off])
        ax.annotate("", xy=tuple(q + o), xytext=tuple(p + o), arrowprops=dict(arrowstyle="<->", lw=0.7, color="#333"), zorder=25)
        m = (p + q) / 2 + o * 1.25
        ax.text(m[0], m[1], txt, fontsize=7, ha="center", va="center", rotation=90 if vertical else 0, zorder=25,
                bbox=dict(boxstyle="round,pad=0.1", fc="white", ec="none", alpha=0.85))
    dim((ex0, ey1), (ex1, ey1), 1.0, f"{cz(ex1 - ex0)} m (vnější)")
    dim((ex1, ey0), (ex1, ey1), 1.0, f"{cz(ey1 - ey0)} m", vertical=True)
    for part in bd["footprint_parts"]:
        ir = np.array(part["interior_rect"])
        ix0, iy0 = ir.min(axis=0)
        ix1, iy1 = ir.max(axis=0)
        dim((ix0, ey0), (ix1, ey0), -0.9, f"{cz(ix1 - ix0)} (vnitřní {part['part']})")
    dim((ex0, ey0 + 0), (ex0, ey0 + (ey1 - ey0)), -1.0, "", vertical=True)
    # north arrow in the building frame
    rot = bp["rotation_deg"]
    nloc = np.array([math.sin(math.radians(rot)), math.cos(math.radians(rot))])
    na = np.array([x1 - 1.2, y1 - 1.6])
    ax.annotate("", xy=tuple(na + nloc * 1.0), xytext=tuple(na - nloc * 0.2), arrowprops=dict(arrowstyle="-|>", lw=1.5, color="k"), zorder=30)
    ax.text(*(na + nloc * 1.4), "S", fontsize=10, weight="bold", ha="center", va="center", zorder=30)
    # scale bar
    bx, by = x0 + 0.4, y0 + 0.4
    for k in range(5):
        ax.add_patch(Rectangle((bx + k, by), 1, 0.12, fc="k" if k % 2 == 0 else "white", ec="k", lw=0.5, zorder=30))
    ax.text(bx + 2.5, by + 0.35, "5 m", ha="center", fontsize=7, zorder=30)
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.set_aspect("equal")
    ax.tick_params(labelsize=7)
    ax.grid(alpha=0.15)
    zfl = zf_world + lv["floor_z"]
    ax.set_title(f"{BLABEL[bd['id']]} – {LVLABEL.get(level, level)} ({level}), podlaha +{cz(lv['floor_z'])} = z {cz(zfl)} m; "
                 f"lokální souřadnice budovy (+Y = průčelí), řez 1,20 m nad podlahou", fontsize=10)
    leg = [MPoly([[0, 0]], fc="#2B2622", label="obvodová zeď v řezu"), MPoly([[0, 0]], fc="#3F3934", label="nosná vnitřní zeď"),
           MPoly([[0, 0]], fc="#6B6258", label="příčka 0,15"), MPoly([[0, 0]], fc="#8C8276", label="lehká příčka / podstupňová stěna 0,10"),
           MPoly([[0, 0]], fc="#CFC8BC", ec="#2B2622", label="parapet pod řezem"),
           Line2D([0], [0], color="#2E86C1", lw=1, label="okno (číslo, parapet m)"),
           Line2D([0], [0], color="#1F4E79", lw=1.6, label="dveře: křídlo v klidové poloze, světlá šířka m"),
           MPoly([[0, 0]], fc="#ECE6D8", ec="#333", label="schodiště (šipka = nahoru)"),
           Line2D([0], [0], color="#7D3C98", lw=1.4, label="zábradlí"),
           MPoly([[0, 0]], fc="#D8D8D8", hatch="xxx", ec="#777", label="uzavřený prostor pod schody"),
           MPoly([[0, 0]], fc="#9C5B3C", label="nábytek – vysoký kryt"), MPoly([[0, 0]], fc="#D29A5C", label="nábytek – nízký kryt"),
           MPoly([[0, 0]], fc="#C8C8C8", label="měkký nábytek (jen zakrývá)"),
           MPoly([[0, 0]], fc="#EFE0EF", label="místnost v zóně"), MPoly([[0, 0]], fc="#F1EBDD", label="místnost mimo zónu"),
           Line2D([0], [0], color="#7B4FA0", lw=2, label="obrys zóny (plný = počítá se)")]
    ax.legend(handles=leg, loc="upper left", bbox_to_anchor=(1.01, 1.0), fontsize=7, frameon=True, title="Legenda")
    fig.savefig(fname, dpi=120)
    plt.close(fig)


def main():
    os.makedirs(IMG, exist_ok=True)
    L = json.load(open(LAYOUT))
    B = json.load(open(BUILDINGS))
    out = []
    f = os.path.join(IMG, "map_plan.png")
    draw_map(L, B, f, (-175, 175, -175, 175), 1.0, 15)
    out.append(f)
    f = os.path.join(IMG, "map_plan_core.png")
    draw_map(L, B, f, (-75, 75, -70, 80), 0.5, 15, core=True)
    out.append(f)
    f = os.path.join(IMG, "map_routes.png")
    draw_routes(L, B, f)
    out.append(f)
    for bd in B["buildings"]:
        for lv in bd["levels"]:
            if lv.get("ceiling_height", 0) <= 0:
                continue
            f = os.path.join(IMG, f"plan_{BNAME[bd['id']]}_{lv['id']}.png")
            draw_floorplan(L, bd, lv["id"], f)
            out.append(f)
    for f in out:
        print("written", os.path.relpath(f, ROOT))


if __name__ == "__main__":
    main()
