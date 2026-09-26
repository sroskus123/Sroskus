"""
ivraster -- rasterises layout.json + buildings.json for analysis (walkability, path cost, line of sight).

Grids are row = y index (south -> north), col = x index (west -> east), cell centres at
x = x0 + (i + 0.5) * res ... we use node-centred grids: x = x0 + i * res (i = 0..N-1).
"""
import math
import numpy as np
from matplotlib.path import Path

import ivterrain as T
import ivcheck as C


class Grid:
    def __init__(self, res, x0=-T.EXT, x1=T.EXT, y0=-T.EXT, y1=T.EXT):
        self.res = res
        self.xs = np.arange(x0, x1 + 1e-9, res)
        self.ys = np.arange(y0, y1 + 1e-9, res)
        self.X, self.Y = np.meshgrid(self.xs, self.ys, indexing="xy")
        self.shape = self.X.shape

    def ij(self, x, y):
        i = int(round((x - self.xs[0]) / self.res))
        j = int(round((y - self.ys[0]) / self.res))
        return j, i

    def poly_mask(self, poly, pad=0.0):
        P = np.array(poly, float)
        xmin, ymin = P.min(axis=0) - pad - self.res
        xmax, ymax = P.max(axis=0) + pad + self.res
        i0 = max(0, int((xmin - self.xs[0]) / self.res))
        i1 = min(self.shape[1], int((xmax - self.xs[0]) / self.res) + 2)
        j0 = max(0, int((ymin - self.ys[0]) / self.res))
        j1 = min(self.shape[0], int((ymax - self.ys[0]) / self.res) + 2)
        m = np.zeros(self.shape, bool)
        if i1 <= i0 or j1 <= j0:
            return m
        sx = self.X[j0:j1, i0:i1]
        sy = self.Y[j0:j1, i0:i1]
        pts = np.column_stack([sx.ravel(), sy.ravel()])
        inside = Path(P).contains_points(pts, radius=1e-9).reshape(sx.shape)
        if pad > 0:
            d = T.dist_to_poly_edge(sx, sy, poly)
            inside |= d <= pad
        m[j0:j1, i0:i1] = inside
        return m

    def seg_mask(self, a, b, half_w):
        xmin = min(a[0], b[0]) - half_w - self.res
        xmax = max(a[0], b[0]) + half_w + self.res
        ymin = min(a[1], b[1]) - half_w - self.res
        ymax = max(a[1], b[1]) + half_w + self.res
        i0 = max(0, int((xmin - self.xs[0]) / self.res))
        i1 = min(self.shape[1], int((xmax - self.xs[0]) / self.res) + 2)
        j0 = max(0, int((ymin - self.ys[0]) / self.res))
        j1 = min(self.shape[0], int((ymax - self.ys[0]) / self.res) + 2)
        m = np.zeros(self.shape, bool)
        if i1 <= i0 or j1 <= j0:
            return m
        sx = self.X[j0:j1, i0:i1]
        sy = self.Y[j0:j1, i0:i1]
        d, _, _, _ = T.polyline_query(sx, sy, [a, b])
        m[j0:j1, i0:i1] = d <= half_w
        return m

    def disk_mask(self, c, r):
        return self.seg_mask(c, [c[0] + 1e-6, c[1]], r)


def xf(c, rot, p):
    a = math.radians(rot)
    return [c[0] + p[0] * math.cos(a) - p[1] * math.sin(a), c[1] + p[0] * math.sin(a) + p[1] * math.cos(a)]


def box_poly(center, size, rot):
    L, W = size[0], size[1]
    return [xf(center, rot, p) for p in ((-L / 2, -W / 2), (L / 2, -W / 2), (L / 2, W / 2), (-L / 2, W / 2))]


def stair_poly_local(sd):
    ux, uy = sd["direction_vector"]
    nx, ny = -uy, ux
    x0, y0 = sd["start"]
    run = sd["run"]
    hw = sd["width"] / 2.0
    return [(x0 + nx * hw, y0 + ny * hw), (x0 + ux * run + nx * hw, y0 + uy * run + ny * hw),
            (x0 + ux * run - nx * hw, y0 + uy * run - ny * hw), (x0 - nx * hw, y0 - ny * hw)]


def roof_height_fn(bd_place, bdef):
    """returns f(X, Y) -> world roof/top z (nan outside) for LOS (building = opaque volume)."""
    c = bd_place["position"][:2]
    rot = bd_place["rotation_deg"]
    zf = bd_place["position"][2]
    parts = []
    for r in bdef["roof"]:
        if "wall_rect" in r:
            R = np.array(r["wall_rect"])
            x0, y0 = R.min(axis=0)
            x1, y1 = R.max(axis=0)
            parts.append((r, x0, y0, x1, y1))
        elif "rect" in r:
            R = np.array(r["rect"])
            x0, y0 = R.min(axis=0)
            x1, y1 = R.max(axis=0)
            parts.append((r, x0, y0, x1, y1))

    def f(X, Y):
        a = math.radians(rot)
        dx = X - c[0]
        dy = Y - c[1]
        lx = dx * math.cos(a) + dy * math.sin(a)
        ly = -dx * math.sin(a) + dy * math.cos(a)
        out = np.full(X.shape, np.nan)
        for r, x0, y0, x1, y1 in parts:
            ov = r.get("overhang_eave", 0.0) or 0.0
            inside = (lx >= x0 - 0.05) & (lx <= x1 + 0.05) & (ly >= y0 - ov) & (ly <= y1 + ov)
            tp = math.tan(math.radians(r["pitch_deg"]))
            if r["type"] == "gable":
                hd = (y1 - y0) / 2
                yc = (y0 + y1) / 2
                z = r["eave_z"] + (hd - np.abs(ly - yc)) * tp
            elif r["type"] == "hip":
                hd = (y1 - y0) / 2
                hl = (x1 - x0) / 2
                yc = (y0 + y1) / 2
                xc = (x0 + x1) / 2
                z = r["eave_z"] + np.minimum(hd - np.abs(ly - yc), hl - np.abs(lx - xc)) * tp
            elif r["type"] == "mono":
                z = np.full(X.shape, r["high_z"])
                # canopy: thin plate -- treat as non-blocking volume below (handled: skip)
                continue
            else:
                z = np.full(X.shape, r["eave_z"])
            z = z + zf
            out = np.where(inside, np.fmax(out, z), out)
        return out
    return f


def sec_height(sb):
    return sb["position"][2] + (sb["ridge_height"] + sb["eave_height"]) / 2.0


def build(layout, bjson, res=0.25, with_trees=True, playable_only=True):
    g = Grid(res)
    X, Y = g.X, g.Y
    H = T.apply_stamps(T.base_plus_detail(layout, X, Y), X, Y, layout["terrain"]["stamps"])
    F = H.copy()                         # walk surface (L0 floors, dock, stairs as ramps)
    blocked = np.zeros(g.shape, bool)
    water = np.zeros(g.shape, bool)
    solid = H.copy()                     # LOS: opaque from -inf up to solid
    c0 = np.full(g.shape, np.inf)        # LOS canopy band [c0, c1]
    c1 = np.full(g.shape, -np.inf)
    bdefs = {b["id"]: b for b in bjson["buildings"]}

    # ---- main buildings
    for bp in layout["buildings"]:
        bd = bdefs[bp["id"]]
        c = bp["position"][:2]
        rot = bp["rotation_deg"]
        zf = bp["position"][2]
        fp = [xf(c, rot, p) for p in (np.array(bd["footprint_parts"][0]["external_rect"]).tolist())]
        # full footprint
        ext = np.array([p for part in bd["footprint_parts"] for p in part["external_rect"]])
        x0, y0 = ext.min(axis=0)
        x1, y1 = ext.max(axis=0)
        fpm = g.poly_mask([xf(c, rot, p) for p in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))])
        F[fpm] = zf
        rf = roof_height_fn(bp, bd)(X, Y)
        solid = np.where(~np.isnan(rf), np.fmax(solid, rf), solid)
        # walls L0 minus door openings
        wmap = {w["id"]: w for w in bd["walls"]}
        for w in bd["walls"]:
            if w["level"] != "L0":
                continue
            # rasterise one cell thicker than the wall (perpendicular only) so thin, grid-aligned walls
            # can never slip between grid nodes; door spans stay exact
            wfat = dict(w, thickness=w["thickness"] + g.res)
            wp = C.wall_poly(wfat)
            poly = [xf(c, rot, p) for p in list(wp.exterior.coords)[:-1]]
            m = g.poly_mask(poly)
            # carve doors
            for o in bd["openings"]:
                if o["wall_id"] != w["id"]:
                    continue
                passable = o["type"] in ("door", "double_door", "opening") or (
                    o["type"] == "roller_door" and o.get("state", {}).get("open_height", 0) >= 2.05)
                if not passable:
                    continue
                gg = C.opening_geom(w, o)
                p0, p1 = gg["p0"], gg["p1"]
                nx, ny = gg["n"]
                t = w["thickness"] / 2 + g.res
                op = [(p0[0] + nx * t, p0[1] + ny * t), (p1[0] + nx * t, p1[1] + ny * t), (p1[0] - nx * t, p1[1] - ny * t),
                      (p0[0] - nx * t, p0[1] - ny * t)]
                m &= ~g.poly_mask([xf(c, rot, q) for q in op])
            blocked |= m
        for col in bd.get("columns", []):
            blocked |= g.poly_mask([xf(c, rot, q) for q in box_poly(col["center"], col["size"], 0)])
        for f_ in bd.get("furniture", []):
            if f_["level"] in ("L0", "exterior"):
                blocked |= g.poly_mask([xf(c, rot, q) for q in box_poly(f_["center"], f_["size"], f_.get("rotation_deg", 0))])
        # dock + exterior steps / ramps (as ramps for walkability)
        dock = bd.get("loading_dock")
        if dock:
            F[g.poly_mask([xf(c, rot, p) for p in dock["polygon"]])] = zf + dock["top_z"]
        # interior flights and sealed voids are not part of the ground walk surface
        for sd in bd.get("stairs", []):
            blocked |= g.poly_mask([xf(c, rot, q) for q in stair_poly_local(sd)])
        for sv in bd.get("sealed_voids", []):
            blocked |= g.poly_mask([xf(c, rot, q) for q in sv["polygon"]])
        for sd in bd.get("exterior_stairs", []):
            poly = stair_poly_local(sd)
            m = g.poly_mask([xf(c, rot, q) for q in poly])
            if sd["level_to"] != "L0":
                blocked |= m          # rises to an upper floor: not part of the ground walk surface
                continue
            lnd = sd.get("landing")
            if lnd:
                F[g.poly_mask([xf(c, rot, p) for p in lnd["polygon"]])] = zf + lnd["z"]
            ux, uy = sd["direction_vector"]
            sx, sy = sd["start"]
            wx = [xf(c, rot, (sx, sy)), xf(c, rot, (sx + ux, sy + uy))]
            ux_w, uy_w = wx[1][0] - wx[0][0], wx[1][1] - wx[0][1]
            s = (X - wx[0][0]) * ux_w + (Y - wx[0][1]) * uy_w
            zbot = zf + sd["z_start"]
            ztop = zf + sd["z_end"]
            F = np.where(m, zbot + np.clip(s / max(sd["run"], 0.01), 0, 1) * (ztop - zbot), F)
        for st in bd.get("exterior_steps", []):
            if st.get("apron"):
                F[g.poly_mask([xf(c, rot, p) for p in st["apron"]["polygon"]])] = zf + st["apron"]["z"]
            if st["type"] in ("ramp",) and "polygon" in st:
                P = np.array(st["polygon"])
                m = g.poly_mask([xf(c, rot, q) for q in st["polygon"]])
                # ramp along its local X from z_top (at the building side) to z_bottom
                lx0, lx1 = P[:, 0].min(), P[:, 0].max()
                ly0, ly1 = P[:, 1].min(), P[:, 1].max()
                a = math.radians(rot)
                dx = X - c[0]
                dy = Y - c[1]
                lx = dx * math.cos(a) + dy * math.sin(a)
                ly = -dx * math.sin(a) + dy * math.cos(a)
                if (lx1 - lx0) > (ly1 - ly0):   # slopes along X, away from the building
                    near = lx0 if abs(lx0) < abs(lx1) else lx1
                    far = lx1 if near == lx0 else lx0
                    t = np.clip((lx - near) / (far - near), 0, 1)
                else:
                    near = ly0 if abs(ly0) < abs(ly1) else ly1
                    far = ly1 if near == ly0 else ly0
                    t = np.clip((ly - near) / (far - near), 0, 1)
                F = np.where(m, zf + st["z_top"] + t * (st["z_bottom"] - st["z_top"]), F)
            if st["type"] in ("step", "threshold_ramp") and "polygon" in st:
                m = g.poly_mask([xf(c, rot, q) for q in st["polygon"]])
                F = np.where(m, zf - 0.5 * st.get("riser", 0.1), F)
    # ---- secondary buildings
    for sb in layout["secondary_buildings"]:
        m = g.poly_mask(sb["footprint_world"])
        if sb.get("embedded_in"):
            F = np.where(m, sb["roof_deck_top_z"], F)
            solid = np.where(m, np.fmax(solid, sb["roof_deck_top_z"]), solid)
            continue
        blocked |= m
        solid = np.where(m, np.fmax(solid, sec_height(sb)), solid)
        if "tower" in sb:
            tw = sb["tower"]
            tc = xf(sb["position"][:2], sb["rotation_deg"], tw["offset_local"])
            mt = g.poly_mask(box_poly(tc, tw["size"], sb["rotation_deg"]))
            blocked |= mt
            solid = np.where(mt, np.fmax(solid, sb["position"][2] + tw["height"]), solid)
    # ---- props
    for p in layout["props"]:
        poly = box_poly(p["position"][:2], p["size"], p["rotation_deg"])
        m = g.poly_mask(poly)
        blocked |= m
        if p.get("blocks_vision", True):
            solid = np.where(m, np.fmax(solid, p["position"][2] + p["size"][2]), solid)
    # ---- fences / hedges / low walls
    for fz in layout["fences_walls_hedges"]:
        pl = fz["polyline"]
        for a, b in zip(pl[:-1], pl[1:]):
            m = g.seg_mask(a, b, 0.2 if "hedge" not in fz["type"] else 0.6)
            blocked |= m
            if fz["blocks_vision"]:
                solid = np.where(m, np.fmax(solid, H + fz["height"]), solid)
    # ---- vegetation blocks (shrub belts / copses): block movement + vision
    for vb in layout.get("vegetation_blocks", []):
        if vb["type"] in ("shrub_belt", "windbreak_belt"):
            m = np.zeros(g.shape, bool)
            pl = vb["polyline"]
            for a, b in zip(pl[:-1], pl[1:]):
                m |= g.seg_mask(a, b, vb["width"] / 2)
        else:
            m = g.poly_mask(vb["polygon"])
        blocked |= m
        solid = np.where(m, np.fmax(solid, H + vb["height"]), solid)
    # ---- retaining walls (+ parapet) with stair gaps
    for rw in layout["retaining_walls"]:
        pl = rw["polyline"]
        segs = rw.get("segments") or [[i, i + 1] for i in range(len(pl) - 1)]
        for i0, i1 in segs:
            m = g.seg_mask(pl[i0], pl[i1], rw["thickness"] / 2)
            blocked |= m
            solid = np.where(m, np.fmax(solid, rw["top_z"]), solid)
        for st in rw.get("stairs", []):
            b0 = st["bottom_center_world"]
            b1 = st["top_center_world"]
            m = g.seg_mask(b0, b1, st["width"] / 2)
            blocked &= ~m
    # ---- bridges: deck is walkable (override brook), railings block
    for br in layout["bridges"]:
        a, b = br["ends"]
        m = g.seg_mask(a, b, br["width"] / 2)
        s = ((X - a[0]) * (b[0] - a[0]) + (Y - a[1]) * (b[1] - a[1])) / ((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2)
        F = np.where(m, br["deck_z"][0] + np.clip(s, 0, 1) * (br["deck_z"][1] - br["deck_z"][0]), F)
        d = np.array(b, float) - np.array(a, float)
        d /= np.linalg.norm(d)
        nrm = np.array([-d[1], d[0]])
        for sgn in (-1, 1):
            off = nrm * sgn * (br["width"] / 2 + 0.05)
            blocked |= g.seg_mask((np.array(a) + off).tolist(), (np.array(b) + off).tolist(), 0.06)
        blocked &= ~g.seg_mask(a, b, br["width"] / 2 - 0.05)
    # ---- water (brook bed) -- slower
    for wtr in layout.get("water", []):
        pl = wtr["polyline"]
        d, _, _, zs = T.polyline_query(X, Y, [[p[0], p[1]] for p in pl], [p[2] for p in pl])
        water |= (d <= wtr["width_at_surface"] / 2) & (F < zs + 0.02)
    # ---- trees
    if with_trees and "trees" in layout:
        sp = layout["trees"]["species"]
        for t in layout["trees"]["instances"]:
            s = sp[t["species"]]
            x, y, z = t["pos"]
            sc = t.get("scale", 1.0)
            tr = s["trunk_radius"] * sc
            blocked |= g.disk_mask([x, y], tr + 0.0)
            m = g.disk_mask([x, y], max(tr, g.res * 0.6))
            solid = np.where(m, np.fmax(solid, z + s["crown_base"] * sc), solid)
            cr = s["crown_radius"] * sc * 0.85
            mc = g.disk_mask([x, y], cr)
            c0 = np.where(mc, np.fmin(c0, z + s["crown_base"] * sc), c0)
            c1 = np.where(mc, np.fmax(c1, z + s["height"] * sc), c1)
    # ---- steepness / steps on the walk surface
    dzx = np.abs(np.diff(F, axis=1))
    dzy = np.abs(np.diff(F, axis=0))
    step = np.zeros(g.shape, bool)
    lim = max(0.40, math.tan(math.radians(45)) * res + 1e-6)
    sx_ = dzx > lim
    sy_ = dzy > lim
    step[:, :-1] |= sx_
    step[:, 1:] |= sx_
    step[:-1, :] |= sy_
    step[1:, :] |= sy_
    gy, gx = np.gradient(F, res)
    slope = np.degrees(np.arctan(np.hypot(gx, gy)))
    steep = slope > 45.0
    # a step edge between two walkable flat surfaces (<=0.40) is fine; edges > 0.40 block
    blocked_all = blocked | step | steep
    play = g.poly_mask(layout["boundary"]["soft_polygon"])
    if playable_only:
        blocked_all |= ~play
    return {"grid": g, "H": H, "F": F, "blocked": blocked_all, "blocked_objects": blocked, "water": water, "solid": solid,
            "c0": c0, "c1": c1, "play": play, "slope": slope}
