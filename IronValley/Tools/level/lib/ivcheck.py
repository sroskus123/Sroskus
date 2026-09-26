"""
ivcheck -- validation of buildings.json against the IRON VALLEY architectural/gameplay limits.

Limits (brief): capsule r 0.35 / h 1.80 (crouch 1.20), max step 0.40, max slope 45 deg,
doors >= 0.90 clear width and >= 2.05 clear height, headroom >= 2.10 wherever a character walks,
stairs riser 0.16-0.19, tread 0.26-0.30, 2R+T 0.60-0.65, width >= 0.90, headroom >= 2.10 above
every step.  Realistic wall thickness: external masonry 0.30-0.45, partitions 0.10-0.15.
"""
import math
from shapely.geometry import Polygon, Point, LineString, box
from shapely.ops import unary_union

LIM = dict(door_w=0.90, door_h=2.05, headroom=2.10, riser=(0.16, 0.19), tread=(0.26, 0.30),
           two_r_t=(0.60, 0.65), stair_w=0.90, pier=0.10, door_front_clear=1.0)


def wall_poly(w):
    (sx, sy), (ex, ey) = w["start"], w["end"]
    t = w["thickness"] / 2.0
    L = math.hypot(ex - sx, ey - sy)
    ux, uy = (ex - sx) / L, (ey - sy) / L
    nx, ny = -uy, ux
    return Polygon([(sx + nx * t, sy + ny * t), (ex + nx * t, ey + ny * t), (ex - nx * t, ey - ny * t), (sx - nx * t, sy - ny * t)])


def wall_frame(w):
    (sx, sy), (ex, ey) = w["start"], w["end"]
    L = math.hypot(ex - sx, ey - sy)
    ux, uy = (ex - sx) / L, (ey - sy) / L
    return sx, sy, ux, uy, -uy, ux, L


def opening_geom(w, o):
    sx, sy, ux, uy, nx, ny, L = wall_frame(w)
    a = o["offset_from_start"]
    b = a + o["width"]
    mid = (a + b) / 2.0
    return {"p0": (sx + ux * a, sy + uy * a), "p1": (sx + ux * b, sy + uy * b), "mid": (sx + ux * mid, sy + uy * mid),
            "u": (ux, uy), "n": (nx, ny), "a": a, "b": b, "L": L}


def furn_poly(f):
    cx, cy = f["center"]
    w, d = f["size"][0], f["size"][1]
    a = math.radians(f.get("rotation_deg", 0.0))
    ca, sa = math.cos(a), math.sin(a)
    pts = []
    for px, py in ((-w / 2, -d / 2), (w / 2, -d / 2), (w / 2, d / 2), (-w / 2, d / 2)):
        pts.append((cx + px * ca - py * sa, cy + px * sa + py * ca))
    return Polygon(pts)


def stair_poly(s):
    a = math.radians(s["direction_deg"])
    ux, uy = math.cos(a), math.sin(a)
    nx, ny = -uy, ux
    x0, y0 = s["start"]
    run = s["run"]
    hw = s["width"] / 2.0
    return Polygon([(x0 + nx * hw, y0 + ny * hw), (x0 + ux * run + nx * hw, y0 + uy * run + ny * hw),
                    (x0 + ux * run - nx * hw, y0 + uy * run - ny * hw), (x0 - nx * hw, y0 - ny * hw)])


def check_building(bd):
    errs, warns, info = [], [], []
    lv = {l["id"]: l for l in bd["levels"]}
    walls = bd["walls"]
    wmap = {w["id"]: w for w in walls}
    # ---- wall thickness plausibility
    for w in walls:
        t = w["thickness"]
        if w["kind"] == "external" and not (0.24 <= t <= 0.50):
            errs.append(f"{w['id']}: external thickness {t}")
        if w["kind"] == "internal" and not (0.10 <= t <= 0.45):
            errs.append(f"{w['id']}: internal thickness {t}")
    # ---- wall box overlaps per level
    for L in lv:
        ws = [w for w in walls if w["level"] == L]
        for i in range(len(ws)):
            for j in range(i + 1, len(ws)):
                inter = wall_poly(ws[i]).intersection(wall_poly(ws[j])).area
                if inter > 1e-6:
                    errs.append(f"wall overlap {ws[i]['id']} x {ws[j]['id']} = {inter:.4f} m2")
    # ---- external footprint consistency
    for part in bd.get("footprint_parts", []):
        er = Polygon(part["external_rect"])
        ir = Polygon(part["interior_rect"])
        ws0 = [w for w in walls if w["level"] == "L0"]
        u = unary_union([wall_poly(w) for w in ws0])
        # the interior rect must be free of walls except internal ones, and walls must reach the external rect edges
        ext_ws = [w for w in ws0 if w["kind"] == "external" or "former gable" in w.get("note", "")]
        ue = unary_union([wall_poly(w) for w in ext_ws])
        ring = er.difference(ir)
        cov = ring.intersection(ue).area / ring.area if ring.area > 0 else 1
        info.append(f"{bd['id']}/{part['part']}: external {er.bounds}, interior {ir.bounds}, wall ring coverage {cov:.3f}")
        if cov < 0.999:
            errs.append(f"{bd['id']}/{part['part']}: external walls do not fill the ring between external and interior rect ({cov:.3f})")
    # ---- openings
    for o in bd["openings"]:
        w = wmap[o["wall_id"]]
        g = opening_geom(w, o)
        if g["a"] < LIM["pier"] - 1e-6 or g["b"] > g["L"] - LIM["pier"] + 1e-6:
            errs.append(f"{o['id']}: opening [{g['a']:.2f},{g['b']:.2f}] outside wall {w['id']} length {g['L']:.2f} with piers")
        if o["head_height"] > w["height"] + w.get("base_z", 0) + 1e-6 and not w.get("gable_above"):
            errs.append(f"{o['id']}: head {o['head_height']} above wall height {w['height']}")
        if o["head_height"] > w["height"] - 0.15 + 1e-6 and o["type"] not in ("vent",) and not w.get("gable_above"):
            warns.append(f"{o['id']}: lintel zone < 0.15 m (head {o['head_height']}, wall {w['height']})")
        if o["type"] in ("door", "double_door"):
            if o["clear_width"] < LIM["door_w"] - 1e-9:
                errs.append(f"{o['id']}: clear width {o['clear_width']}")
            if o["clear_height"] < LIM["door_h"] - 1e-9:
                errs.append(f"{o['id']}: clear height {o['clear_height']}")
        if o["type"] == "roller_door":
            oh = o.get("state", {}).get("open_height", 0)
            if 0 < oh < LIM["door_h"]:
                errs.append(f"{o['id']}: roller door partly open below walk height ({oh})")
        # other walls abutting within the opening span (T-junction in an opening)
        for w2 in walls:
            if w2 is w or w2["level"] != w["level"]:
                continue
            for end in (w2["start"], w2["end"]):
                # distance of the abutting wall end from wall w's centre line <= (t_w + ...)/2 and projected inside the opening
                sx, sy, ux, uy, nx, ny, L = wall_frame(w)
                px, py = end[0] - sx, end[1] - sy
                along = px * ux + py * uy
                perp = abs(px * nx + py * ny)
                if perp <= w["thickness"] / 2 + 0.001 + 1e-6 and g["a"] - w2["thickness"] / 2 < along < g["b"] + w2["thickness"] / 2:
                    if o["sill_height"] < 2.5:
                        errs.append(f"{o['id']}: wall {w2['id']} abuts inside the opening span")
    # no column inside a passable/glazed opening (columns within 0.40 m of the wall line)
    for o in bd["openings"]:
        w = wmap[o["wall_id"]]
        g = opening_geom(w, o)
        sx, sy, ux, uy, nx, ny, L = wall_frame(w)
        for col in bd.get("columns", []):
            px, py = col["center"][0] - sx, col["center"][1] - sy
            along = px * ux + py * uy
            perp = abs(px * nx + py * ny)
            half = max(col["size"]) / 2
            if perp <= w["thickness"] / 2 + 0.40 and g["a"] - half < along < g["b"] + half and o["sill_height"] < col["height"] - 0.5:
                if o["type"] in ("door", "double_door", "roller_door", "opening"):
                    errs.append(f"{o['id']}: column at {col['center']} stands in the opening")
    # overlapping openings on the same wall
    by_wall = {}
    for o in bd["openings"]:
        by_wall.setdefault(o["wall_id"], []).append(o)
    for wid, os_ in by_wall.items():
        for i in range(len(os_)):
            for j in range(i + 1, len(os_)):
                a, b = os_[i], os_[j]
                h_ov = min(a["offset_from_start"] + a["width"], b["offset_from_start"] + b["width"]) - max(a["offset_from_start"], b["offset_from_start"])
                v_ov = min(a["head_height"], b["head_height"]) - max(a["sill_height"], b["sill_height"])
                if h_ov > -0.20 and v_ov > -0.20:
                    errs.append(f"openings too close/overlapping on {wid}: {a['id']} {b['id']} (h {h_ov:.2f}, v {v_ov:.2f})")
    # ---- rooms: headroom, overlap with walls
    for r in bd["rooms"]:
        if r["ceiling_height"] < LIM["headroom"]:
            errs.append(f"{r['id']}: ceiling {r['ceiling_height']}")
        rp = Polygon(r["polygon"])
        for w in walls:
            if w["level"] != r["level"]:
                continue
            ov = rp.intersection(wall_poly(w)).area
            if ov > 1e-4:
                errs.append(f"room {r['id']} overlaps wall {w['id']} ({ov:.3f} m2)")
    # ---- stairs
    all_st = list(bd.get("stairs", [])) + list(bd.get("exterior_stairs", []))
    for s in all_st:
        R, Tt = s["riser"], s["tread"]
        if not (LIM["riser"][0] <= R <= LIM["riser"][1]):
            errs.append(f"{s['id']}: riser {R}")
        if not (LIM["tread"][0] <= Tt <= LIM["tread"][1]):
            errs.append(f"{s['id']}: tread {Tt}")
        if not (LIM["two_r_t"][0] <= 2 * R + Tt <= LIM["two_r_t"][1] + 1e-9):
            errs.append(f"{s['id']}: 2R+T {2 * R + Tt:.3f}")
        if s["width"] < LIM["stair_w"]:
            errs.append(f"{s['id']}: width {s['width']}")
        # headroom above each nosing: ceilings = slab soffits of upper levels (minus their openings)
        # + the ceiling of the highest level that has one (over its extent or the whole footprint)
        a = math.radians(s["direction_deg"])
        ux, uy = math.cos(a), math.sin(a)
        nx, ny = -uy, ux
        ceil_surfs = []
        for sl in bd.get("slabs", []):
            ceil_surfs.append((sl["top_z"] - sl["thickness"], Polygon(sl["polygon"]),
                               [Polygon(h["polygon"]) for h in sl.get("openings", [])]))
        tops = [l for l in bd["levels"] if l.get("ceiling_height", 0) > 0]
        if tops:
            top = max(tops, key=lambda l: l["floor_z"])
            ext = top.get("extent") or bd["footprint_parts"][0]["interior_rect"]
            ceil_surfs.append((top["floor_z"] + top["ceiling_height"], Polygon(ext), []))
        min_head = 99
        for k in range(1, s["count"] + 1):
            d = (k - 1) * Tt
            z = s["z_start"] + k * R
            for side in (-0.45, 0.0, 0.45):
                px = s["start"][0] + ux * (d + 0.02) + nx * side * s["width"]
                py = s["start"][1] + uy * (d + 0.02) + ny * side * s["width"]
                pt = Point(px, py)
                ceiling = 99
                if s.get("side") != "rear_exterior":
                    for bottom, P, holes in ceil_surfs:
                        if bottom <= z + 0.01:
                            continue
                        if P.buffer(1e-6).contains(pt) and not any(h.contains(pt) for h in holes):
                            ceiling = min(ceiling, bottom)
                min_head = min(min_head, ceiling - z)
        s_head = round(min_head, 3)
        info.append(f"{s['id']}: R {R:.4f} T {Tt} 2R+T {2 * R + Tt:.3f} rise {s['rise']} min headroom {s_head}")
        if min_head < LIM["headroom"] - 1e-6:
            errs.append(f"{s['id']}: headroom {s_head} < 2.10")
    # ---- furniture vs walls / doors
    for f in bd.get("furniture", []):
        if f["level"] not in lv:
            continue
        fp = furn_poly(f)
        for w in walls:
            if w["level"] == f["level"] and fp.intersection(wall_poly(w)).area > 1e-4:
                errs.append(f"furniture {f['id']} intersects wall {w['id']}")
        for o in bd["openings"]:
            if o["type"] not in ("door", "double_door", "roller_door"):
                continue
            w = wmap[o["wall_id"]]
            if w["level"] != f["level"]:
                continue
            g = opening_geom(w, o)
            (x0, y0), (x1, y1) = g["p0"], g["p1"]
            nxx, nyy = g["n"]
            D = LIM["door_front_clear"] + w["thickness"] / 2
            zone = Polygon([(x0 + nxx * D, y0 + nyy * D), (x1 + nxx * D, y1 + nyy * D), (x1 - nxx * D, y1 - nyy * D), (x0 - nxx * D, y0 - nyy * D)])
            if fp.intersection(zone).area > 1e-3:
                errs.append(f"furniture {f['id']} blocks the 1.0 m clear zone of {o['id']}")
    fl = [f for f in bd.get("furniture", []) if f["level"] in lv]
    for i in range(len(fl)):
        for j in range(i + 1, len(fl)):
            if fl[i]["level"] == fl[j]["level"] and furn_poly(fl[i]).intersection(furn_poly(fl[j])).area > 1e-4:
                errs.append(f"furniture overlap {fl[i]['id']} x {fl[j]['id']}")
    # furniture must lie inside a room of its level
    for f in fl:
        fp = furn_poly(f)
        if not any(Polygon(r["polygon"]).buffer(0.01).contains(fp) for r in bd["rooms"] if r["level"] == f["level"]):
            errs.append(f"furniture {f['id']} not inside a room")
    # ---- connectivity graph (rooms <-> doors <-> exterior, stairs between levels)
    rooms = bd["rooms"]
    graph = {r["id"]: set() for r in rooms}
    graph["EXTERIOR"] = set()

    def room_at(level, x, y):
        for r in rooms:
            if r["level"] == level and Polygon(r["polygon"]).buffer(0.02).contains(Point(x, y)):
                return r["id"]
        return None

    for o in bd["openings"]:
        if o["type"] not in ("door", "double_door") and not (o["type"] == "roller_door" and o.get("state", {}).get("open_height", 0) >= LIM["door_h"]):
            continue
        w = wmap[o["wall_id"]]
        g = opening_geom(w, o)
        mx, my = g["mid"]
        nxx, nyy = g["n"]
        d = w["thickness"] / 2 + 0.3
        ra = room_at(w["level"], mx + nxx * d, my + nyy * d)
        rb = room_at(w["level"], mx - nxx * d, my - nyy * d)
        ra = ra or ("EXTERIOR" if w["kind"] == "external" else None)
        rb = rb or ("EXTERIOR" if w["kind"] == "external" else None)
        if ra is None or rb is None:
            errs.append(f"{o['id']}: door does not connect two spaces ({ra}, {rb})")
            continue
        graph[ra].add((rb, o["id"]))
        graph[rb].add((ra, o["id"]))
    # stairs: connect the room at the bottom approach with the room at the top
    for s in all_st:
        a = math.radians(s["direction_deg"])
        ux, uy = math.cos(a), math.sin(a)
        lf = s["level_from"]
        lt = s["level_to"]
        bx, by = s["start"][0] - ux * 0.4, s["start"][1] - uy * 0.4
        tx, ty = s["top_riser_center"][0] + ux * 0.4, s["top_riser_center"][1] + uy * 0.4
        rb_ = room_at(lf, bx, by) if lf in lv else ("EXTERIOR" if lf == "ground" else "MID:" + s["id"])
        rt_ = room_at(lt, tx, ty) if lt in lv else ("MID:" + s["id"])
        if rt_ is None and s.get("landing"):
            rt_ = "EXTERIOR_PLATFORM:" + s["id"]
        graph.setdefault(rb_, set()).add((rt_, s["id"]))
        graph.setdefault(rt_, set()).add((rb_, s["id"]))
    # merge the mid landing nodes of U-stairs
    mids = [k for k in graph if isinstance(k, str) and k.startswith("MID:")]
    if len(mids) == 2:
        a, b = mids
        graph[a].add((b, "landing"))
        graph[b].add((a, "landing"))
    # platform nodes connect through their door to rooms already (door on external wall -> EXTERIOR). Link platform to that door's room:
    for k in list(graph):
        if isinstance(k, str) and k.startswith("EXTERIOR_PLATFORM:"):
            # the platform is the exterior side of the door on that level
            graph[k].add(("EXTERIOR", "platform"))
            graph["EXTERIOR"].add((k, "platform"))
    # BFS from exterior
    seen = {"EXTERIOR"}
    todo = ["EXTERIOR"]
    while todo:
        c = todo.pop()
        for n, _ in graph.get(c, ()):
            if n not in seen and n is not None:
                seen.add(n)
                todo.append(n)
    for r in rooms:
        if r["id"] not in seen:
            errs.append(f"room {r['id']} unreachable from outside")
    exits = {r["id"]: sorted({via for _, via in graph[r["id"]]}) for r in rooms}
    for rid, ex in exits.items():
        if len(ex) < 2:
            warns.append(f"room {rid} is a dead end (single exit {ex})")
    return {"errors": errs, "warnings": warns, "info": info, "exits": exits,
            "graph": {k: sorted([(n, v) for n, v in vals], key=str) for k, vals in graph.items()}}


if __name__ == "__main__":
    import json, sys
    data = json.load(open(sys.argv[1]))
    for bd in data["buildings"]:
        res = check_building(bd)
        print("==", bd["id"])
        for k in ("errors", "warnings", "info"):
            for m in res[k]:
                print(f"  [{k[:-1]}] {m}")
        for rid, ex in res["exits"].items():
            print(f"  exits {rid}: {ex}")
