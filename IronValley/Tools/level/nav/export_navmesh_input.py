#!/usr/bin/env python3
"""
export_navmesh_input.py -- builds the Recast input triangle soup for the design-time navmesh validation bake of
"Kalné Hamry" straight from Shared/level/layout.json + buildings.json (no hand-made geometry).

Output (Tools/level/_out/nav/):
  nav_input.bin   little-endian: uint32 nverts, uint32 ntris, float32 xyz * nverts (RECAST frame: x, z_blender, -y_blender),
                  uint32 i0 i1 i2 * ntris
  nav_queries.json  spawn points, zone target points, documented entrances, reference point (all in the Blender frame)

Collision content (same rules as layout.meta.collision_semantics): terrain (0.5 m cells, clipped 1 m inside the soft
boundary), building construction boxes of every level, floor and upper slabs (minus stair voids), stair ramps (pitch
plane), landings, balconies + parapets, balustrades, door leaves in their rest pose, furniture, columns, chimneys, the dock,
secondary buildings, props, fences / hedge cores / shrub cores, retaining walls (stair gaps open), bridge decks + railings,
tree trunks.  Windows are closed by their construction boxes' absence only above sills -> the sill boxes stop the capsule.
"""
import json
import math
import os
import struct
import sys

import numpy as np
from shapely.geometry import Polygon, Point, box as sbox

HERE = os.path.dirname(os.path.abspath(__file__))
LEVEL = os.path.abspath(os.path.join(HERE, ".."))
ROOT = os.path.abspath(os.path.join(LEVEL, "..", ".."))
sys.path.insert(0, os.path.join(LEVEL, "lib"))
sys.path.insert(0, LEVEL)
import ivterrain as T          # noqa: E402
import check_layout as C       # noqa: E402

OUT = os.path.join(LEVEL, "_out", "nav")


class Soup:
    def __init__(self):
        self.v = []
        self.t = []

    def add_tri(self, a, b, c):
        n = len(self.v)
        self.v += [a, b, c]
        self.t.append((n, n + 1, n + 2))

    def add_quad(self, a, b, c, d):
        self.add_tri(a, b, c)
        self.add_tri(a, c, d)

    def add_prism(self, poly_xy, z0, z1):
        """closed prism over a convex/simple polygon (world XY), CCW order normalised."""
        P = list(poly_xy)
        if Polygon(P).exterior.is_ccw is False:
            P = P[::-1]
        n = len(P)
        top = [(p[0], p[1], z1) for p in P]
        bot = [(p[0], p[1], z0) for p in P]
        for k in range(1, n - 1):
            self.add_tri(top[0], top[k], top[k + 1])
            self.add_tri(bot[0], bot[k + 1], bot[k])
        for k in range(n):
            a, b = P[k], P[(k + 1) % n]
            self.add_quad((a[0], a[1], z0), (b[0], b[1], z0), (b[0], b[1], z1), (a[0], a[1], z1))

    def add_obox(self, cx, cy, lx, ly, rot_deg, z0, z1):
        a = math.radians(rot_deg)
        ca, sa = math.cos(a), math.sin(a)
        pts = [(cx + px * ca - py * sa, cy + px * sa + py * ca) for px, py in ((-lx / 2, -ly / 2), (lx / 2, -ly / 2), (lx / 2, ly / 2), (-lx / 2, ly / 2))]
        self.add_prism(pts, z0, z1)

    def add_ramp(self, corners_xyz, thickness=0.25):
        """walkable inclined quad (a, b, c, d CCW seen from above) + a skirt below it."""
        a, b, c, d = corners_xyz
        self.add_quad(a, b, c, d)
        for p, q in ((a, b), (b, c), (c, d), (d, a)):
            self.add_quad((q[0], q[1], q[2] - thickness), (p[0], p[1], p[2] - thickness), p, q)

    def write(self, path):
        V = np.array(self.v, np.float64)
        R = np.column_stack([V[:, 0], V[:, 2], -V[:, 1]]).astype(np.float32)   # recast frame (Y up)
        Tt = np.array(self.t, np.uint32)
        with open(path, "wb") as f:
            f.write(struct.pack("<II", len(R), len(Tt)))
            f.write(R.tobytes())
            f.write(Tt.tobytes())
        return len(R), len(Tt)


def xf(c, rot, p):
    return C.xf(c, rot, p)


def main():
    os.makedirs(OUT, exist_ok=True)
    L = json.load(open(C.LAYOUT))
    B = json.load(open(C.BUILDINGS))
    S = Soup()
    soft = Polygon(L["boundary"]["soft_polygon"])
    clip = soft.buffer(-1.0)
    # ---------------- terrain
    res = 0.5
    x0, y0, x1, y1 = soft.bounds
    x0, y0 = math.floor(x0) - 1, math.floor(y0) - 1
    x1, y1 = math.ceil(x1) + 1, math.ceil(y1) + 1
    X, Y, H = T.heightfield(L, res, x0, x1, y0, y1)
    xs = X[0]
    ys = Y[:, 0]
    from matplotlib.path import Path
    cx = (X[:-1, :-1] + X[1:, 1:]) / 2
    cy = (Y[:-1, :-1] + Y[1:, 1:]) / 2
    inside = Path(np.array(clip.exterior.coords)).contains_points(np.column_stack([cx.ravel(), cy.ravel()])).reshape(cx.shape)
    nterr = 0
    for j in range(len(ys) - 1):
        for i in np.nonzero(inside[j])[0]:
            a = (xs[i], ys[j], H[j, i])
            b = (xs[i + 1], ys[j], H[j, i + 1])
            c = (xs[i + 1], ys[j + 1], H[j + 1, i + 1])
            d = (xs[i], ys[j + 1], H[j + 1, i])
            S.add_quad(a, b, c, d)
            nterr += 2
    # ---------------- buildings
    bdefs = {b["id"]: b for b in B["buildings"]}
    for bp in L["buildings"]:
        bd = bdefs[bp["id"]]
        c0, rot, zf = bp["position"][:2], bp["rotation_deg"], bp["position"][2]
        lv = {l["id"]: l for l in bd["levels"]}
        W = lambda p: xf(c0, rot, p)  # noqa: E731
        ext = [W(p) for p in bd["footprint_parts"][0]["external_rect"]]
        for part in bd["footprint_parts"]:
            S.add_prism([W(p) for p in part["external_rect"]], zf - 0.6, zf)
        for w in bd["walls"]:
            sx, sy, ux, uy, nx, ny, Lw = C.wall_frame(w)
            ang = math.degrees(math.atan2(uy, ux)) + rot
            zl = zf + lv[w["level"]]["floor_z"]
            for cb in w["construction_boxes"]:
                u0, u1 = cb["u"]
                m = W((sx + ux * (u0 + u1) / 2, sy + uy * (u0 + u1) / 2))
                S.add_obox(m[0], m[1], u1 - u0, w["thickness"], ang, zl + cb["z"][0], zl + cb["z"][1])
            for o in bd["openings"]:
                if o["wall_id"] == w["id"] and o["type"] == "roller_door" and not o["passes"]["movement"]:
                    a_, b_ = o["offset_from_start"], o["offset_from_start"] + o["width"]
                    m = W((sx + ux * (a_ + b_) / 2, sy + uy * (a_ + b_) / 2))
                    S.add_obox(m[0], m[1], b_ - a_, w["thickness"], ang, zl, zl + o["head_height"])
                if o["wall_id"] == w["id"] and o["type"] in ("door", "double_door"):
                    lp = C.leaf_rest_poly(w, o)
                    for g in (lp.geoms if lp.geom_type == "MultiPolygon" else [lp]):
                        S.add_prism([W(p) for p in list(g.exterior.coords)[:-1]], zl + 0.01, zl + o["clear_height"])
        for sl in bd.get("slabs", []):
            P = Polygon(sl["polygon"])
            for h in sl.get("openings", []):
                P = P.difference(Polygon(h["polygon"]))
            for g in (P.geoms if P.geom_type == "MultiPolygon" else [P]):
                bx0, by0, bx1, by1 = g.bounds
                xs_ = sorted(set([round(v[0], 4) for v in g.exterior.coords] + [round(v[0], 4) for r_ in g.interiors for v in r_.coords]))
                for xa, xb in zip(xs_[:-1], xs_[1:]):
                    strip = g.intersection(sbox(xa, by0 - 1, xb, by1 + 1))
                    for gg in ([strip] if strip.geom_type == "Polygon" else getattr(strip, "geoms", [])):
                        if gg.area < 1e-4:
                            continue
                        q0, q1, q2, q3 = gg.bounds
                        S.add_prism([W(p) for p in ((q0, q1), (q2, q1), (q2, q3), (q0, q3))], zf + sl["top_z"] - sl["thickness"], zf + sl["top_z"])
        for s in bd["stairs"] + bd["exterior_stairs"]:
            dv = s["direction_vector"]
            nx, ny = -dv[1], dv[0]
            hw = s["width"] / 2
            ext_run = s["run"] + 0.30          # the top riser lands on the landing: extend onto it
            sx_, sy_ = s["start"]
            a = W((sx_ + nx * hw, sy_ + ny * hw))
            b = W((sx_ - nx * hw, sy_ - ny * hw))
            c = W((sx_ - nx * hw + dv[0] * ext_run, sy_ - ny * hw + dv[1] * ext_run))
            d = W((sx_ + nx * hw + dv[0] * ext_run, sy_ + ny * hw + dv[1] * ext_run))
            za = zf + s["z_start"]
            zb = zf + s["z_start"] + (s["z_end"] - s["z_start"]) * ext_run / s["run"]
            zb = min(zb, zf + s["z_end"])
            S.add_ramp([(a[0], a[1], za), (b[0], b[1], za), (c[0], c[1], zb), (d[0], d[1], zb)])
            ld = s.get("landing")
            if ld:
                S.add_prism([W(p) for p in ld["polygon"]], zf + ld["z"] - ld.get("thickness", 0.20), zf + ld["z"])
            if s.get("under_stair", {}).get("treatment") == "solid_mass":
                # solid base under the flight: stepped boxes up to 5 cm below the pitch plane
                nstep = 6
                for k in range(nstep):
                    d0 = s["run"] * k / nstep
                    d1 = s["run"] * (k + 1) / nstep
                    zt = zf + s["z_start"] + (s["z_end"] - s["z_start"]) * d0 / s["run"] - 0.05
                    q = [W((sx_ + nx * hw * 0.98 + dv[0] * d0, sy_ + ny * hw * 0.98 + dv[1] * d0)),
                         W((sx_ - nx * hw * 0.98 + dv[0] * d0, sy_ - ny * hw * 0.98 + dv[1] * d0)),
                         W((sx_ - nx * hw * 0.98 + dv[0] * d1, sy_ - ny * hw * 0.98 + dv[1] * d1)),
                         W((sx_ + nx * hw * 0.98 + dv[0] * d1, sy_ + ny * hw * 0.98 + dv[1] * d1))]
                    zg = zf + s["z_start"] - 0.6
                    if zt > zg + 0.05:
                        S.add_prism(q, zg, zt)
        for ba in bd.get("balustrades", []):
            zb_ = zf + (ba.get("z") if ba.get("z") is not None else (lv[ba["level"]]["floor_z"] if ba["level"] in lv else
                                                                    next((st["landing"]["z"] for st in bd["stairs"] if st.get("landing") and st["landing"]["level"] == ba["level"]), 0.0)))
            for p, q in zip(ba["polyline"][:-1], ba["polyline"][1:]):
                m = W(((p[0] + q[0]) / 2, (p[1] + q[1]) / 2))
                S.add_obox(m[0], m[1], math.dist(p, q), 0.06, math.degrees(math.atan2(q[1] - p[1], q[0] - p[0])) + rot, zb_, zb_ + ba["height"])
        for ba in bd.get("balconies", []):
            S.add_prism([W(p) for p in ba["polygon"]], zf + ba["top_z"] - ba["slab_thickness"], zf + ba["top_z"])
            pp = ba["parapet"]
            for p, q in pp["segments"]:
                m = W(((p[0] + q[0]) / 2, (p[1] + q[1]) / 2))
                S.add_obox(m[0], m[1], math.dist(p, q), pp["thickness"], math.degrees(math.atan2(q[1] - p[1], q[0] - p[0])) + rot,
                           zf + ba["top_z"], zf + ba["top_z"] + pp["height"])
        for f in bd.get("furniture", []):
            if f["level"] in lv:
                zl = zf + lv[f["level"]]["floor_z"]
            else:
                zl = zf - 0.17
            m = W(f["center"])
            if f.get("shape") == "wedge_under_soffit":
                # stepped boxes under the soffit of the flight above it (the flight id is in the stair's under_stair.by)
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
                    top = min(zf + zs, zl + f["size"][2])
                    if top > zl + 0.1:
                        mm = W((cxl, cyl))
                        S.add_obox(mm[0], mm[1], u1 - u0, f["size"][1], rot + math.degrees(math.atan2(dv[1], dv[0])), zl - 0.1, top)
                continue
            S.add_obox(m[0], m[1], f["size"][0], f["size"][1], rot + f.get("rotation_deg", 0), zl, zl + max(f["size"][2], 0.6))
        for col in bd.get("columns", []):
            m = W(col["center"])
            S.add_obox(m[0], m[1], col["size"][0], col["size"][1], rot, zf, zf + col["height"])
        for ch in bd.get("chimneys", []):
            m = W(ch["pos"])
            S.add_obox(m[0], m[1], ch.get("size", [0.3, 0.3])[0], ch.get("size", [0.3, 0.3])[1], rot, zf - 0.2, zf + 6.0)
        if bd.get("loading_dock"):
            S.add_prism([W(p) for p in bd["loading_dock"]["polygon"]], zf - 1.20, zf)
        for st in bd.get("exterior_steps", []):
            if st["type"] == "step":
                S.add_prism([W(p) for p in st["polygon"]], zf - st["riser"] - 0.1, zf)
            if st["type"] == "ramp":
                P = np.array(st["polygon"])
                lx0, lx1 = P[:, 0].min(), P[:, 0].max()
                ly0, ly1 = P[:, 1].min(), P[:, 1].max()
                if (lx1 - lx0) > (ly1 - ly0):
                    near = lx0 if abs(lx0) < abs(lx1) else lx1
                    far = lx1 if near == lx0 else lx0
                    corners = [(near, ly0, st["z_top"]), (far, ly0, st["z_bottom"]), (far, ly1, st["z_bottom"]), (near, ly1, st["z_top"])]
                else:
                    near = ly0 if abs(ly0) < abs(ly1) else ly1
                    far = ly1 if near == ly0 else ly0
                    corners = [(lx0, near, st["z_top"]), (lx1, near, st["z_top"]), (lx1, far, st["z_bottom"]), (lx0, far, st["z_bottom"])]
                cw = [(*W(p[:2]), zf + p[2]) for p in corners]
                if Polygon([c_[:2] for c_ in cw]).exterior.is_ccw is False:
                    cw = cw[::-1]
                S.add_ramp(cw, thickness=1.3)
    # ---------------- secondary buildings
    for sb in L["secondary_buildings"]:
        z = sb["position"][2]
        if sb.get("embedded_in"):
            S.add_prism(sb["footprint_world"], z - 0.2, sb["roof_deck_top_z"])
            continue
        if sb["type"] == "bus_shelter":
            S.add_prism(sb["footprint_world"], z - 0.3, z + sb["eave_height"])
            continue
        S.add_prism(sb["footprint_world"], z - 0.6, z + sb["eave_height"])
        if "tower" in sb:
            tw = sb["tower"]
            tc = xf(sb["position"][:2], sb["rotation_deg"], tw["offset_local"])
            S.add_obox(tc[0], tc[1], tw["size"][0], tw["size"][1], sb["rotation_deg"], z, z + tw["height"])
    # ---------------- props
    for p in L["props"]:
        z = p["position"][2]
        S.add_obox(p["position"][0], p["position"][1], p["size"][0], p["size"][1], p["rotation_deg"], z - 0.4, z + p["size"][2])
    # ---------------- fences, hedges, shrubs
    for fz in L["fences_walls_hedges"]:
        if not fz.get("blocks_movement", True):
            continue
        wdt = 1.2 if "hedge" in fz["type"] else 0.12
        for a, b in zip(fz["polyline"][:-1], fz["polyline"][1:]):
            m = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            za = float(T.height_at(L, *a)[0]); zb = float(T.height_at(L, *b)[0])
            S.add_obox(m[0], m[1], math.dist(a, b), wdt, math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])), min(za, zb) - 0.5,
                       max(za, zb) + max(fz["height"], 1.0))
    for vb in L["vegetation_blocks"]:
        if "polyline" in vb:
            for a, b in zip(vb["polyline"][:-1], vb["polyline"][1:]):
                m = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
                za = float(T.height_at(L, *a)[0]); zb = float(T.height_at(L, *b)[0])
                S.add_obox(m[0], m[1], math.dist(a, b) + vb["width"], vb["width"], math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])),
                           min(za, zb) - 0.5, max(za, zb) + vb["height"])
        else:
            P = Polygon(vb["polygon"])
            zc = float(T.height_at(L, P.centroid.x, P.centroid.y)[0])
            S.add_prism(vb["polygon"], zc - 2.0, zc + vb["height"] + 2.0)
    # ---------------- retaining walls
    for rw in L["retaining_walls"]:
        segs = rw.get("segments") or [[k, k + 1] for k in range(len(rw["polyline"]) - 1)]
        for i0, i1 in segs:
            a, b = rw["polyline"][i0], rw["polyline"][i1]
            m = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            S.add_obox(m[0], m[1], math.dist(a, b), rw["thickness"], math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])),
                       rw["bottom_z"] - 0.5, rw["top_z"])
    # ---------------- retaining-wall stairs as explicit ramps (the terrain stamp alone is too coarse at 0.5 m)
    for rw in L["retaining_walls"]:
        for st in rw.get("stairs", []):
            a = np.array(st["bottom_center_world"], float)
            b = np.array(st["top_center_world"], float)
            d = (b - a) / np.linalg.norm(b - a)
            n = np.array([-d[1], d[0]])
            hw = st["width"] / 2
            za = rw["bottom_z"]
            zb = rw["top_z"] - (rw["parapet"]["height_above_terrace"] if rw.get("parapet") else 0.10)
            a2 = a - d * 0.3
            b2 = b + d * 0.4
            corners = [(*(a2 + n * hw), za), (*(a2 - n * hw), za), (*(b2 - n * hw), zb), (*(b2 + n * hw), zb)]
            if Polygon([c_[:2] for c_ in corners]).exterior.is_ccw is False:
                corners = corners[::-1]
            S.add_ramp(corners, thickness=0.5)
    # ---------------- bridges
    for br in L["bridges"]:
        a, b = br["ends"]
        d = np.array(b, float) - np.array(a, float)
        Lb = np.linalg.norm(d)
        d /= Lb
        n = np.array([-d[1], d[0]])
        hw = br["width"] / 2
        za, zb = br["deck_z"]
        pa = np.array(a) - d * 0.5
        pb = np.array(b) + d * 0.5
        corners = [(*(pa + n * hw), za), (*(pa - n * hw), za), (*(pb - n * hw), zb), (*(pb + n * hw), zb)]
        if Polygon([c_[:2] for c_ in corners]).exterior.is_ccw is False:
            corners = corners[::-1]
        S.add_ramp(corners, thickness=0.4)
        for sg in (-1, 1):
            off = n * sg * (hw + 0.05)
            m = (np.array(a) + np.array(b)) / 2 + off
            S.add_obox(m[0], m[1], Lb, 0.08, math.degrees(math.atan2(d[1], d[0])), min(za, zb), max(za, zb) + br["railing"]["height"])
    # ---------------- tree trunks
    sp = L["trees"]["species"]
    for t in L["trees"]["instances"]:
        if not soft.buffer(2).contains(Point(t["pos"][:2])):
            continue
        s = sp[t["species"]]
        r = s["trunk_radius"] * t.get("scale", 1.0)
        S.add_obox(t["pos"][0], t["pos"][1], 2 * r, 2 * r, 0, t["pos"][2] - 0.3, t["pos"][2] + s["crown_base"] * t.get("scale", 1.0))
    nv, nt = S.write(os.path.join(OUT, "nav_input.bin"))
    # ---------------- queries
    W_ = C.Walk(L, B)
    zones = {}
    for z in L["capture_zones"]:
        zones[z["id"]] = [(float(x), float(y), float(f)) for (x, y, f) in C.zone_samples(L, B, W_, z, spacing=2.0)]
    spawns = {sa["team"]: [{"id": p["id"], "pos": p["pos"], "zones": p["zones"]} for p in sa["candidate_points"]] for sa in L["spawn_areas"]}
    ents = []
    for ck in L["chokepoints"]:
        if "at" not in ck:
            continue
        pts = ck["at"] if isinstance(ck["at"][0], list) else [ck["at"]]
        for k, p in enumerate(pts):
            if ck.get("type") == "stair" and ck.get("building"):
                bp = next(b for b in L["buildings"] if b["id"] == ck["building"])
                bd = bdefs[ck["building"]]
                sd = next(s_ for s_ in bd["stairs"] + bd["exterior_stairs"] if "CK_" + s_["id"] == ck["id"])
                zz = bp["position"][2] + sd["z_start"]
            elif ck.get("level") not in (None, "L0"):
                bp = next(b for b in L["buildings"] if b["id"] == ck["building"])
                bd = bdefs[ck["building"]]
                zz = bp["position"][2] + next(l["floor_z"] for l in bd["levels"] if l["id"] == ck["level"])
            else:
                j, i = W_.ij(p[0], p[1])
                zz = float(W_.F[j, i])
            ents.append({"id": ck["id"] + (f"#{k}" if len(pts) > 1 else ""), "pos": [p[0], p[1], zz], "type": ck["type"]})
    for rw in L["retaining_walls"]:
        for st in rw.get("stairs", []):
            for tag, p, zz in (("bottom", st["bottom_center_world"], rw["bottom_z"]), ("top", st["top_center_world"], rw["top_z"] - (0.60 if rw.get("parapet") else 0.10))):
                ents.append({"id": f"{st['id']}_{tag}", "pos": [p[0], p[1], zz], "type": "retaining-wall stair"})
    for q in L["qa_points"]:
        if q["kind"] == "stair":
            ents.append({"id": q["id"], "pos": q["pos"], "type": "stair end"})
    ref = {"id": "SQUARE", "pos": [0.0, 0.0, 0.30]}
    json.dump({"level_hash": C.level_hash(L, B), "spawns": spawns, "zones": zones, "entrances": ents, "reference": ref,
               "frame": "blender (x, y, z); convert to recast as (x, z, -y)"}, open(os.path.join(OUT, "nav_queries.json"), "w"))
    print(f"nav input: {nv} verts, {nt} tris (terrain {nterr}); queries: {sum(len(v) for v in zones.values())} zone targets, "
          f"{sum(len(v) for v in spawns.values())} spawns, {len(ents)} entrances")


if __name__ == "__main__":
    main()
