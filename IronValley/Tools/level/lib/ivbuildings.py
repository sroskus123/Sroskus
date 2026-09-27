"""
ivbuildings -- authoring source for Shared/level/buildings.json (IRON VALLEY, map "Kalné Hamry").

Reference-matched revision (2026-09-27): the workshop follows the user's reference Docs/navrhy/04 (L-shaped
single-storey hall + lower gabled annex + small lean-to, two rusty double gates, steel multi-pane windows, two brick
chimneys, roof light, lime plaster peeling off red brick, dark corrugated roof), the warehouse follows 01/03 (long
brick hall with plastered pilasters, green corrugated gable roof, big steel sliding doors) and the house follows 01
(two-storey block with a red clay-tile hip roof, dormers and a lower one-storey wing, walled garden).  Analysis:
Docs/REFERENCE_ANALYSIS.md, decisions: Docs/REFERENCE_DECISIONS.md.

Building-local frame: metres, Z up.  Origin = the point stated in each building's `local_origin` (workshop: centre of
the whole external bounding box; warehouse: centre of the hall; house: centre of the two-storey main block, its wing
extends to -X) at finished ground-floor level (top of the L0 floor finish = 0.00).  Local +Y = FRONT facade
(rotation_deg 0 in layout.json means local +Y points north).  Local +X = to the right of an observer standing inside
looking out of the front.  World = rotate local by layout rotation_deg (counter-clockwise about +Z) and translate by
layout position [x, y, z_floor].  layout.json `footprint_world` is the exact union of the `footprint_parts`
external rectangles (L-shaped plans are not reduced to their bounding box).
Axis conversions (same as layout.json): three.js (x, y, z)_three = (x, z, -y)_blender; Unreal (cm) =
(100 x, -100 y, 100 z) with FBX 'Y forward, Z up' export (UE import NOT TESTED).

Walls (exact, no implicit extension):
  * a wall is a box: centre line from `start` to `end` (exact box ends), `thickness` centred on the line,
    from z = level.floor_z + base_z to + height.
  * walls running along X run through the corners; walls along Y stop at the inner faces of the X-walls;
    internal walls stop at the faces of the walls they meet.  Boxes never overlap.
  * external walls are listed counter-clockwise (seen from above), so their LEFT normal (-dy, dx) points
    INTO the building.  `finish_left` / `finish_right` = finish on the left / right face.
  * `construction_boxes` (derived, authoritative for the generator, no booleans): the wall split into
    full-height piers, sill blocks and lintel blocks; each box = {part, u:[u0,u1] along the wall from
    `start`, z:[z0,z1] above the level floor}.  Union of boxes = wall box minus openings.
  * `gable_above: true` -> the wall carries a gable (or a lean-to rake) above `height` up to roof `gable_roof`.
    The prism is given explicitly in `gable`: `polygon_uz` (u along the wall from `start`, z above the level floor,
    spanning the outer faces of the crossing walls), the ids of the openings inside it and `construction_polygons`
    (= gable polygon minus its openings; the generator extrudes each by the wall thickness -- no booleans).
Openings:
  * `offset_from_start` = distance along the centre line from `start` to the near jamb; `width`,
    `sill_height`, `head_height` = STRUCTURAL (rough) opening, relative to the wall's level floor.
  * doors: frame jamb 0.05 m each side and 0.05 m head; leaf of `leaf.thickness` resting at `open_deg`
    (90 = perpendicular to the wall) on the `swing` side ("left"/"right" of the wall direction), hinged at
    the jamb `hinge` ("start"/"end" = jamb nearer to the wall start/end).
    clear_width = width - 2 * frame_jamb - leaf thickness (single leaf) or - 2 * leaf thickness (pair);
    clear_height = head_height - frame_head.  Project rule: clear_width >= 1.10 m (brief >= 0.90 m) so a
    0.35 m capsule keeps a >= 0.40 m navmesh corridor at Recast cs 0.05 m / radius 7 cells (the binding bake
    setting; cs 0.10 / radius 4 would leave only 0.20-0.30 m and pinched the house U-stair); clear_height >= 2.05 m.
  * sliding doors (`sliding_door`): top-hung steel leaf on an external track; guides 0.05 m each side ->
    clear_width = width - 0.10, clear_height = head_height - 0.05.  `state.open` true = the leaf is parked beside the
    opening over solid wall (`leaf_rest.u` = its span along the wall, `leaf_rest.side` = outside face, 0.25 m off
    it, clear of the 0.15 m pilasters); false = closed and padlocked (solid collision, blocks bullets and vision, baked as wall in the navmesh).
  * roller doors: guide rails 0.05 m each side -> clear_width = width - 0.10; clear_height =
    state.open_height - 0.05 (bottom rail).  open_height < 2.10 is never used on a walkable opening.
  * windows carry `reveal_depth` (frame set back from the outer face, 0.12 m) and `sill_overhang` (external sill
    projection, 0.04 m, with a drip groove).
  * `passes` = {movement, bullets, vision}: windows are capsule-blocking clip planes that pass bullets and
    vision (v1: glass does not stop hits); translucent polycarbonate strips pass bullets, block vision;
    louvred vents block everything.
Stairs (`stairs` = internal flights, `exterior_stairs` = every external flight incl. dock and entrance
steps; one schema for all):
  * `start` = local XY of the centre of the FIRST (bottom) riser line; `direction_deg` = direction of
    ascent, degrees CCW from local +Y (0 = +Y, 90 = -X, 180 = -Y, 270 = +X), i.e. the same convention as
    building rotations; `direction_vector` = (-sin a, cos a).
  * `count` = number of risers, `treads` = count - 1 (the last riser lands on the landing/upper floor),
    `run` = treads * tread, `top_riser_center` = start + direction_vector * run (validated).
  * `width` = clear width between wall faces / balustrade inner faces (project rule >= 1.10 m).
  * `waist` = structural depth below the pitch line (soffit = pitch line - waist).
  * `under_stair` = how the space below the flight is closed: enclosed (walls, listed in `sealed_voids`),
    solid_mass (built solid to the ground), filled (collision furniture up to where headroom >= 2.10).
  * exterior flights and ramps declare `foot_ground` (terrain level in front of the first riser, local z); the terrain
    must meet it within 0.02 m and may never rise above a tread (validated against the terrain contract).
Roofs: `eave_z` = height of the roof plane on the wall line (wall plate); the drip edge is eave_z - overhang *
tan(pitch).  Every gutter carries `drip_edge_z` and its rim `z` hangs 0.03 m below it (validated); downpipes start at
the gutter.  `dormers`, `roof_lights`, `ridge_vent` are listed per roof.  Chimneys have `base_z` (a stack corbelled
on the tie beams starts above the floor space) and `serves` (the stove / forge that justifies it).
Rooms have polygon, ceiling_height (clear), `ceiling` (what closes it: slab id, joists, roof) and floor_material.
`sealed_voids` = closed, unreachable spaces (under-stair stores) that are neither rooms nor walkable.  Furniture: box
{center, size [x, y, z], rotation_deg}, cover low/high/none, blocks bullets/vision (soft furniture = concealment only).
`fixtures` = wall-mounted lamps / signs (visual only, no collision).  `pilasters` = facade piers (0.15 m proud, never
across an opening).
"""
import math

from shapely.geometry import Polygon, box as sbox
from shapely.ops import unary_union

T_EXT_MASONRY = 0.45
T_INT = 0.15
FRAME_JAMB = 0.05
FRAME_HEAD = 0.05
DOOR_W = 1.25          # structural width of every single-leaf door -> 1.10 clear
DOOR_HEAD = 2.30       # structural head -> 2.25 clear
LEAF_T = 0.05
REVEAL = 0.12
SILL_OVER = 0.04
GUTTER_BELOW_DRIP = 0.03


def r3(v):
    return round(float(v), 4)


def dir_vec(direction_deg):
    a = math.radians(direction_deg)
    return (-math.sin(a), math.cos(a))


class B:
    """Small builder that keeps ids unique and computes opening offsets from local coordinates."""

    def __init__(self, bid):
        self.bid = bid
        self.walls = []
        self.openings = []
        self._w = {}

    def wall(self, wid, level, start, end, t, h, kind, material, finish_in=None, finish_out=None,
             base_z=0.0, gable_above=False, gable_roof=None, note=None):
        w = {"id": wid, "level": level, "start": [r3(start[0]), r3(start[1])],
             "end": [r3(end[0]), r3(end[1])], "thickness": t, "base_z": base_z, "height": r3(h),
             "kind": kind, "material": material}
        if finish_in:
            w["finish_left"] = finish_in
        if finish_out:
            w["finish_right"] = finish_out
        if gable_above:
            w["gable_above"] = True
            w["gable_roof"] = gable_roof
        if note:
            w["note"] = note
        self.walls.append(w)
        self._w[wid] = w
        return w

    def ext_rect(self, prefix, level, x0, y0, x1, y1, t, h, material, fin_in, fin_out,
                 gables=(), gable_roof=None, skip=()):
        """4 external walls CCW: S (+X), E (+Y), N (-X), W (-Y). X-walls run through."""
        hw = t / 2.0
        spec = {
            "S": ((x0, y0 + hw), (x1, y0 + hw)),
            "E": ((x1 - hw, y0 + t), (x1 - hw, y1 - t)),
            "N": ((x1, y1 - hw), (x0, y1 - hw)),
            "W": ((x0 + hw, y1 - t), (x0 + hw, y0 + t)),
        }
        out = {}
        for side in ("S", "E", "N", "W"):
            if side in skip:
                continue
            s, e = spec[side]
            out[side] = self.wall(f"{prefix}_{side}", level, s, e, t, h, "external", material,
                                  fin_in, fin_out, gable_above=(side in gables),
                                  gable_roof=gable_roof if side in gables else None)
        return out

    def _offset(self, w, center, width):
        (sx, sy), (ex, ey) = w["start"], w["end"]
        if abs(ey - sy) < 1e-9:  # along X
            d = 1.0 if ex > sx else -1.0
            near = center - d * width / 2.0
            return (near - sx) * d
        d = 1.0 if ey > sy else -1.0
        near = center - d * width / 2.0
        return (near - sy) * d

    def opening(self, oid, wall_id, typ, center, width, sill, head, has_leaf, hinge=None, swing=None,
                open_deg=None, leaf=None, glazing=None, state=None, note=None, passes=None):
        """`center` = local coordinate of the opening centre along the wall axis (x for walls
        along X, y for walls along Y)."""
        w = self._w[wall_id]
        off = self._offset(w, center, width)
        o = {"id": oid, "wall_id": wall_id, "type": typ, "offset_from_start": r3(off), "width": r3(width),
             "sill_height": r3(sill), "head_height": r3(head), "has_leaf": has_leaf}
        if typ in ("door", "double_door"):
            lt = (leaf or {}).get("thickness", LEAF_T)
            n_leaf = 2 if typ == "double_door" else 1
            o["hinge"] = hinge
            o["swing"] = swing
            o["open_deg"] = open_deg
            o["frame_jamb"] = FRAME_JAMB
            o["frame_head"] = FRAME_HEAD
            o["clear_width"] = r3(width - 2 * FRAME_JAMB - n_leaf * lt)
            o["clear_height"] = r3(head - FRAME_HEAD)
            o["clear_rule"] = f"{width:.2f} - 2 x {FRAME_JAMB:.2f} frame - {n_leaf} x {lt:.2f} leaf at {open_deg} deg"
            o["passes"] = {"movement": True, "bullets": True, "vision": True}
        elif typ == "sliding_door":
            st = dict(state or {})
            is_open = bool(st.get("open"))
            o["guides"] = 0.05
            o["clear_width"] = r3(width - 0.10)
            o["clear_height"] = r3(head - 0.05)
            o["passes"] = {"movement": is_open, "bullets": is_open, "vision": is_open,
                           "note": "open: leaf parked over solid wall beside the opening; closed: padlocked steel leaf "
                                   "(solid collision, blocks bullets and vision, baked as wall)"}
            L_ = math.hypot(w["end"][0] - w["start"][0], w["end"][1] - w["start"][1])
            a, b = off, off + width
            leaf_w = width + 0.10
            if is_open:
                if st.get("park", "end") == "end":
                    u = [b - 0.05, b - 0.05 + leaf_w]
                else:
                    u = [a + 0.05 - leaf_w, a + 0.05]
            else:
                u = [a - 0.05, b + 0.05]
            out_side = "right" if w["kind"] == "external" else st.get("side", "right")
            o["leaf_rest"] = {"u": [r3(u[0]), r3(u[1])], "side": out_side, "offset_from_face": 0.25,
                              "thickness": (leaf or {}).get("thickness", 0.08), "height": r3(head + 0.10),
                              "wall_length": r3(L_)}
            st["open"] = is_open
            state = st
        elif typ == "roller_door":
            oh = (state or {}).get("open_height", 0.0)
            o["guide_rails"] = 0.05
            o["clear_width"] = r3(width - 0.10)
            o["clear_height"] = r3(max(0.0, oh - 0.05))
            walk = oh >= 2.10
            o["passes"] = {"movement": walk, "bullets": walk, "vision": walk,
                           "note": "open part passes; closed curtain above/below blocks bullets and vision"}
        elif typ == "window":
            opaque = glazing is not None and "polycarbonate" in glazing
            o["passes"] = passes or {"movement": False, "bullets": True, "vision": not opaque,
                                     "note": "capsule clip plane; v1 glass passes hits" if not opaque else
                                     "translucent strip: blocks vision, passes bullets"}
            o["reveal_depth"] = REVEAL
            o["sill_overhang"] = SILL_OVER
        elif typ == "vent":
            o["passes"] = {"movement": False, "bullets": False, "vision": False}
            o["reveal_depth"] = 0.05
        if leaf:
            o["leaf"] = leaf
        if glazing:
            o["glazing"] = glazing
        if state:
            o["state"] = state
        if note:
            o["note"] = note
        self.openings.append(o)
        return o

    def door(self, oid, wall_id, center, hinge, swing, leaf_type, material, width=DOOR_W, head=DOOR_HEAD,
             deg=90, thickness=LEAF_T, note=None):
        return self.opening(oid, wall_id, "door", center, width, 0.0, head, True, hinge=hinge, swing=swing,
                            open_deg=deg, leaf={"type": leaf_type, "thickness": thickness, "material": material},
                            note=note)


def stair_flight(sid, level_from, level_to, start_center, direction_deg, width, riser, tread, count,
                 z_start, landing=None, construction="concrete", handrail="right", waist=0.18,
                 under_stair=None, from_landing=None, note=None, foot_ground=None):
    """start_center = local XY of the centre of the first riser line (bottom); direction_deg = ascent,
    CCW from local +Y.  count = number of risers; treads = count - 1."""
    run = (count - 1) * tread
    ux, uy = dir_vec(direction_deg)
    top = [start_center[0] + run * ux, start_center[1] + run * uy]
    s = {"id": sid, "level_from": level_from, "level_to": level_to,
         "start": [r3(start_center[0]), r3(start_center[1])], "direction_deg": direction_deg,
         "direction_vector": [r3(ux), r3(uy)],
         "width": width, "riser": r3(riser), "tread": tread, "count": count,
         "treads": count - 1, "run": r3(run), "rise": r3(riser * count),
         "z_start": r3(z_start), "z_end": r3(z_start + riser * count),
         "top_riser_center": [r3(top[0]), r3(top[1])],
         "two_r_plus_t": r3(2 * riser + tread), "construction": construction, "waist": waist,
         "handrail": handrail, "pitch_deg": r3(math.degrees(math.atan2(riser, tread)))}
    if landing:
        s["landing"] = landing
    if from_landing:
        s["from_landing"] = from_landing
    if foot_ground is not None:
        s["foot_ground"] = r3(foot_ground)
    s["under_stair"] = under_stair or {"treatment": "solid_mass"}
    if note:
        s["note"] = note
    return s


def rect(x0, y0, x1, y1):
    return [[r3(x0), r3(y0)], [r3(x1), r3(y0)], [r3(x1), r3(y1)], [r3(x0), r3(y1)]]


def furn(fid, level, typ, center, size, rot=0.0, cover="none", note=None, blocks_bullets=True,
         blocks_vision=True, shape="box"):
    f = {"id": fid, "level": level, "type": typ, "center": [r3(center[0]), r3(center[1])],
         "size": [r3(size[0]), r3(size[1]), r3(size[2])], "rotation_deg": rot, "cover": cover,
         "collision": True, "blocks_bullets": blocks_bullets, "blocks_vision": blocks_vision}
    if shape != "box":
        f["shape"] = shape
    if note:
        f["note"] = note
    return f


def construction_boxes(w, openings):
    """Split a wall into piers / sills / lintels / transoms (no booleans).  u along the wall from start, z above the
    level floor.  The u axis is cut at every opening jamb; in each strip the solid z-intervals (wall height minus the
    openings covering the strip) become boxes; equal neighbouring strips are merged (so a pier is one box)."""
    L = math.hypot(w["end"][0] - w["start"][0], w["end"][1] - w["start"][1])
    z0 = w.get("base_z", 0.0)
    z1 = z0 + w["height"]
    # openings entirely above the wall top sit in the gable prism (see `gable`)
    ops = [o for o in openings if o["wall_id"] == w["id"] and o["sill_height"] < z1 - 1e-6]
    cuts = sorted({0.0, L} | {round(o["offset_from_start"], 6) for o in ops} |
                  {round(o["offset_from_start"] + o["width"], 6) for o in ops})
    strips = []
    for ua, ub in zip(cuts[:-1], cuts[1:]):
        if ub - ua < 1e-6:
            continue
        act = [o for o in ops if o["offset_from_start"] <= ua + 1e-6 and o["offset_from_start"] + o["width"] >= ub - 1e-6]
        holes = sorted((max(z0, o["sill_height"]), min(z1, o["head_height"]), o["id"]) for o in act)
        solid = []
        z = z0
        for (ha, hb, oid) in holes:
            if ha > z + 1e-6:
                part = "pier" if not act else ("sill" if z <= z0 + 1e-6 else "transom")
                solid.append((z, ha, part, oid))
            z = max(z, hb)
        if z < z1 - 1e-6:
            solid.append((z, z1, "pier" if not act else "lintel", holes[-1][2] if holes else None))
        strips.append((ua, ub, solid))
    boxes = []
    open_boxes = {}
    for ua, ub, solid in strips:
        keys = set()
        for (za, zb, part, oid) in solid:
            k = (round(za, 6), round(zb, 6), part, oid)
            keys.add(k)
            if k in open_boxes and abs(open_boxes[k]["u"][1] - ua) < 1e-6:
                open_boxes[k]["u"][1] = ub
            else:
                bx = {"part": part, "u": [ua, ub], "z": [za, zb]}
                if oid and part != "pier":
                    bx["of"] = oid
                boxes.append(bx)
                open_boxes[k] = bx
        for k in list(open_boxes):
            if k not in keys:
                del open_boxes[k]
    for bx in boxes:
        bx["u"] = [r3(bx["u"][0]), r3(bx["u"][1])]
        bx["z"] = [r3(bx["z"][0]), r3(bx["z"][1])]
    return boxes


# ------------------------------------------------------------------------------------------------
# roofs: plane heights, drip edges, gutters, gable prisms
# ------------------------------------------------------------------------------------------------
def _rbounds(r):
    P = r.get("wall_rect") or r.get("rect")
    xs = [p[0] for p in P]
    ys = [p[1] for p in P]
    return min(xs), min(ys), max(xs), max(ys)


def roof_plane_z(rf, x, y):
    """height of the roof plane (top surface on the wall-line convention) at local (x, y); None outside."""
    x0, y0, x1, y1 = _rbounds(rf)
    tp = math.tan(math.radians(rf["pitch_deg"]))
    if rf["type"] == "gable":
        if rf.get("ridge_axis", "X") == "X":
            return rf["eave_z"] + ((y1 - y0) / 2 - abs(y - (y0 + y1) / 2)) * tp
        return rf["eave_z"] + ((x1 - x0) / 2 - abs(x - (x0 + x1) / 2)) * tp
    if rf["type"] == "hip":
        dy = (y1 - y0) / 2 - abs(y - (y0 + y1) / 2)
        dx = (x1 - x0) / 2 - abs(x - (x0 + x1) / 2)
        ab = rf.get("abuts") or {}
        if "+X" in ab and x > (x0 + x1) / 2:
            dx = 1e9
        if "-X" in ab and x < (x0 + x1) / 2:
            dx = 1e9
        return rf["eave_z"] + min(dy, dx) * tp
    if rf["type"] == "mono":
        d = rf["slope_direction"]            # direction the roof falls towards
        if d == "-X":
            return rf["high_z"] - (x1 - x) * tp
        if d == "+X":
            return rf["high_z"] - (x - x0) * tp
        if d == "-Y":
            return rf["high_z"] - (y1 - y) * tp
        return rf["high_z"] - (y - y0) * tp
    return None


def drip_edge_z(rf):
    return r3(rf["eave_z"] - (rf.get("overhang_eave") or 0.0) * math.tan(math.radians(rf["pitch_deg"])))


def gutter(rf, edge, frm, to, profile, note=None):
    d = drip_edge_z(rf)
    g = {"roof": rf["id"], "edge": edge, "from": [r3(frm[0]), r3(frm[1])], "to": [r3(to[0]), r3(to[1])],
         "drip_edge_z": d, "z": r3(d - GUTTER_BELOW_DRIP), "profile": profile,
         "rule": "rim hangs 0.03 m below the drip edge (eave_z - overhang * tan(pitch)) on brackets under the roof edge"}
    if note:
        g["note"] = note
    return g


def gable_prism(w, rf, openings, ext_t=(0.0, 0.0)):
    """gable (or lean-to rake) above the wall top: polygon in (u, z) spanning u = -ext_t[0] .. L + ext_t[1]
    (outer faces of the crossing walls), top = roof plane along the wall centre line."""
    sx, sy = w["start"]
    ex, ey = w["end"]
    L = math.hypot(ex - sx, ey - sy)
    ux, uy = (ex - sx) / L, (ey - sy) / L
    top = w.get("base_z", 0.0) + w["height"]
    us = sorted({-ext_t[0], L + ext_t[1]} | {u for u in [i * 0.05 for i in range(int(-ext_t[0] / 0.05), int((L + ext_t[1]) / 0.05) + 1)]})
    pts = []
    for u in us:
        z = roof_plane_z(rf, sx + ux * u, sy + uy * u)
        pts.append((u, max(top, z)))
    poly = Polygon([(-ext_t[0], top)] + pts + [(L + ext_t[1], top)]).buffer(0).simplify(0.002)
    ops = [o for o in openings if o["wall_id"] == w["id"] and o["sill_height"] >= top - 1e-6]
    holes = [sbox(o["offset_from_start"], o["sill_height"], o["offset_from_start"] + o["width"], o["head_height"]) for o in ops]
    cons = poly.difference(unary_union(holes)) if holes else poly
    # hole-free pieces for extrusion: cut into vertical strips at every opening jamb (like construction_boxes)
    cuts = sorted({-ext_t[0], L + ext_t[1]} | {o["offset_from_start"] for o in ops} | {o["offset_from_start"] + o["width"] for o in ops})
    geoms = []
    for ua, ub in zip(cuts[:-1], cuts[1:]):
        if ub - ua < 1e-6:
            continue
        piece = cons.intersection(sbox(ua, top - 1.0, ub, top + 50.0))
        for g in ([piece] if piece.geom_type == "Polygon" else list(getattr(piece, "geoms", []))):
            if g.geom_type == "Polygon" and g.area > 1e-4:
                geoms.append(g)
    return {"roof": rf["id"], "base_z": r3(top), "apex_z": r3(max(p[1] for p in pts)),
            "polygon_uz": [[r3(u), r3(z)] for u, z in list(poly.exterior.coords)[:-1]],
            "openings": [o["id"] for o in ops],
            "construction_polygons": [[[r3(u), r3(z)] for u, z in list(g.exterior.coords)[:-1]] for g in geoms if g.area > 1e-4],
            "rule": "extrude each construction polygon by the wall thickness along the wall normal; openings are the holes"}


def finalize(bd, gable_ext=None):
    roofs = {r["id"]: r for r in bd["roof"]}
    for w in bd["walls"]:
        w["length"] = r3(math.hypot(w["end"][0] - w["start"][0], w["end"][1] - w["start"][1]))
        w["construction_boxes"] = construction_boxes(w, bd["openings"])
        if w.get("gable_above"):
            w["gable"] = gable_prism(w, roofs[w["gable_roof"]], bd["openings"], (gable_ext or {}).get(w["id"], (0.0, 0.0)))
    return bd


# ================================================================================================
# 1) DÍLNA -- workshop on the old hammer-mill site, as reference 04: hall + lower annex + lean-to
# ================================================================================================
def dilna():
    b = B("B_DILNA")
    T = T_EXT_MASONRY
    # footprint (local): lean-to X[-12.25,-8.75] Y[-0.5,4.5] | hall X[-8.75,5.75] Y[-5,5] | annex X[5.75,12.25] Y[-5,2.8]
    HX0, HX1 = -8.75, 5.75
    AX1, AY1 = 12.25, 2.80
    KX0, KY0, KY1 = -12.25, -0.50, 4.50
    HALL_TOP = 4.60      # wall plate of the hall (reference 04: gates 3.3 m high reach ~0.7 of the wall)
    ANX_TOP = 3.00       # annex wall plate (door 2.1 m ~ 0.7 of its wall, ref. 04)
    KL, KH = 2.60, 3.30  # lean-to: low eave (outer end) / high side against the hall gable
    TK = 0.30
    mat_ext = "brick_masonry_450"
    fin_in_hall = "plaster_lime_white_over_green_oil_dado_1500"
    fin_out = "render_lime_offwhite_peeling_to_red_brick"
    fin_in_anx = "plaster_lime_white"
    # --- hall (L0)
    b.wall("DL_H_S", "L0", (HX0, -4.775), (HX1, -4.775), T, HALL_TOP, "external", mat_ext, fin_in_hall, fin_out)
    b.wall("DL_H_E", "L0", (HX1 - 0.225, -4.55), (HX1 - 0.225, 4.55), T, HALL_TOP, "external", mat_ext, fin_in_hall, fin_out,
           gable_above=True, gable_roof="RF_HALA",
           note="hall +X gable: party wall with the annex below y 2.35 (0.45 brick = fire wall), exterior face in front of the "
                "annex (y 2.8..5.0) and above the annex roof (high gable windows)")
    b.wall("DL_H_N", "L0", (HX1, 4.775), (HX0, 4.775), T, HALL_TOP, "external", mat_ext, fin_in_hall, fin_out)
    b.wall("DL_H_W", "L0", (HX0 + 0.225, 4.55), (HX0 + 0.225, -4.55), T, HALL_TOP, "external", mat_ext, fin_in_hall, fin_out,
           gable_above=True, gable_roof="RF_HALA",
           note="hall -X gable: the lean-to leans against it for y -0.5..4.5")
    # --- annex (lower gabled wing, set back 2.2 m from the hall front, flush with the rear)
    b.wall("DL_A_S", "L0", (HX1, -4.775), (AX1, -4.775), T, ANX_TOP, "external", mat_ext, fin_in_anx, fin_out)
    b.wall("DL_A_E", "L0", (AX1 - 0.225, -4.55), (AX1 - 0.225, AY1 - 0.45), T, ANX_TOP, "external", mat_ext, fin_in_anx, fin_out,
           gable_above=True, gable_roof="RF_PRISTAVEK")
    b.wall("DL_A_N", "L0", (AX1, AY1 - 0.225), (HX1, AY1 - 0.225), T, ANX_TOP, "external", mat_ext, fin_in_anx, fin_out)
    b.wall("DL_P1", "L0", (HX1, -0.90), (AX1 - 0.45, -0.90), T_INT, 2.85, "internal", "brick_partition_150",
           "plaster_lime_white", "tiles_white_1500", note="annex: tool issue room (front) | locker room and washroom (rear)")
    # --- lean-to (mono-pitch, falls towards -X)
    b.wall("DL_K_N", "L0", (HX0, KY1 - TK / 2), (KX0, KY1 - TK / 2), TK, KL, "external", "brick_masonry_300", "plaster_lime_white",
           fin_out, gable_above=True, gable_roof="RF_KULNA", note="lean-to front: sloping top (rake) follows the mono roof")
    b.wall("DL_K_W", "L0", (KX0 + TK / 2, KY1 - TK), (KX0 + TK / 2, KY0 + TK), TK, KL, "external", "brick_masonry_300",
           "plaster_lime_white", fin_out)
    b.wall("DL_K_S", "L0", (KX0, KY0 + TK / 2), (HX0, KY0 + TK / 2), TK, KL, "external", "brick_masonry_300", "plaster_lime_white",
           fin_out, gable_above=True, gable_roof="RF_KULNA")

    GLZ = "steel_industrial_multipane_4x6"
    # --- hall front (+Y), seen from the yard left (+X) to right (-X) exactly as reference 04:
    #     window | gate G1 | downpipe + vent slot | gate G2 | window
    b.opening("DL_W1", "DL_H_N", "window", 4.60, 1.00, 1.50, 3.10, False, glazing=GLZ)
    b.opening("DL_G1", "DL_H_N", "double_door", 1.80, 3.40, 0.0, 3.40, True, hinge="both", swing="right",
              open_deg=100, leaf={"type": "steel_framed_timber_pair_rusty_red", "thickness": 0.06, "material": "steel_timber_red_oxide_rusty"},
              note="main gate (ref. 04 left gate): both leaves rest open outward at 100 deg on facade stops; exposed steel "
                   "I-beam lintel with the wall lamp DL_L1 above")
    b.opening("DL_V1", "DL_H_N", "vent", -1.50, 0.25, 3.40, 4.00, False, note="narrow louvred slot (ref. 04, beside the downpipe)")
    b.opening("DL_G2", "DL_H_N", "double_door", -4.50, 2.60, 0.0, 3.40, True, hinge="both", swing="right",
              open_deg=100, leaf={"type": "steel_framed_timber_pair_rusty_red", "thickness": 0.06, "material": "steel_timber_red_oxide_rusty"},
              note="second gate (ref. 04 right gate, shown closed there): v1 rest pose open so the hall has two wide yard entries")
    b.opening("DL_W2", "DL_H_N", "window", -7.30, 1.10, 1.50, 3.10, False, glazing=GLZ)
    # --- hall rear (-Y), not visible in any reference: door + three windows (interpretation)
    b.door("DL_D2", "DL_H_S", -2.00, "start", "right", "steel_sheet", "steel_grey_paint_worn",
           note="rear door to the rear pad, opens outward")
    for i, x in enumerate((-6.0, 1.4, 4.2)):
        b.opening(f"DL_W{3 + i}", "DL_H_S", "window", x, 1.10, 1.50, 3.10, False, glazing=GLZ)
    # --- hall -X gable: exterior side door (bank path) + door into the lean-to
    b.door("DL_D3", "DL_H_W", -2.60, "start", "right", "timber_ledged", "timber_grey_paint_worn",
           note="gable side door to the brook-bank path, opens outward")
    b.door("DL_D9", "DL_H_W", 1.60, "end", "right", "timber_ledged", "timber_grey_paint_worn",
           note="hall -> compressor lean-to (the lean-to has its own yard door DL_D7: never a single-door trap)")
    # --- hall +X gable: two doors into the annex rooms + two high gable windows above the annex roof (ref. 04)
    b.door("DL_D5", "DL_H_E", 0.90, "end", "right", "timber_flush", "timber_cream_paint", note="hall -> tool issue room")
    b.door("DL_D4", "DL_H_E", -2.85, "start", "right", "timber_flush", "timber_cream_paint", note="hall -> locker room")
    b.opening("DL_WG1", "DL_H_E", "window", 0.60, 0.70, 5.40, 6.30, False, glazing="steel_industrial_multipane_2x3",
              note="high gable window above the annex roof (ref. 04), lights the open roof space of the hall; not reachable")
    b.opening("DL_WG2", "DL_H_E", "window", -2.00, 0.45, 5.30, 5.80, False, glazing="steel_industrial_multipane_1x2",
              note="small high gable window (ref. 04); not reachable")
    # --- annex
    b.door("DL_D6", "DL_A_E", 1.20, "end", "left", "timber_ledged_dark", "timber_grey_black_paint_worn",
           note="annex gable door (ref. 04: dark plank door beside two windows), opens inward")
    b.opening("DL_W7", "DL_A_E", "window", -1.60, 0.90, 0.90, 2.30, False, glazing="steel_multipane_3x5")
    b.opening("DL_W8", "DL_A_E", "window", -3.55, 0.60, 0.90, 2.30, False, glazing="steel_multipane_2x5")
    b.opening("DL_W9", "DL_A_N", "window", 10.00, 1.10, 0.90, 2.30, False, glazing="steel_multipane_4x5")
    b.opening("DL_W10", "DL_A_N", "window", 7.40, 0.90, 0.90, 2.30, False, glazing="steel_multipane_3x5")
    b.opening("DL_W11", "DL_A_S", "window", 9.00, 0.90, 1.40, 2.30, False, glazing="steel_multipane_3x3")
    b.door("DL_D8", "DL_P1", 10.40, "start", "right", "timber_flush", "timber_cream_paint", note="tool issue room <-> locker room")
    # --- lean-to
    b.door("DL_D7", "DL_K_N", -10.55, "start", "left", "timber_ledged_grey", "timber_grey_paint_worn",
           note="lean-to door (ref. 04: grey plank door under a bulkhead lamp), opens inward")
    b.opening("DL_W12", "DL_K_W", "window", 1.80, 0.25, 1.40, 2.00, False, glazing="single_pane_slit",
              note="small slit window on the lean-to end wall (ref. 04)")

    levels = [
        {"id": "L0", "name": "Přízemí (hala, přístavek, kůlna)", "floor_z": 0.0, "ceiling_height": 4.20,
         "floor_thickness": 0.15, "note": "single storey (ref. 04): hall open to the roof (tie beams at 4.20 clear), annex ceiling "
                                          "boards at 2.85, lean-to open to its mono roof; slab-on-grade 0.15 + stone plinth"},
    ]
    rooms = [
        {"id": "DL_R_HALA", "level": "L0", "name": "Dílna (hala)", "polygon": rect(HX0 + 0.45, -4.55, HX1 - 0.45, 4.55),
         "ceiling_height": 4.20, "ceiling": {"type": "roof_trusses", "tie_beam_underside": 4.20},
         "floor_material": "concrete_oil_stained", "in_zone": True},
        {"id": "DL_R_VYDEJNA", "level": "L0", "name": "Výdejna nářadí", "polygon": rect(HX1, -0.825, AX1 - 0.45, AY1 - 0.45),
         "ceiling_height": 2.85, "ceiling": {"type": "timber_ceiling_on_joists", "underside": 2.85},
         "floor_material": "vinyl_tiles_beige", "in_zone": True},
        {"id": "DL_R_SATNA", "level": "L0", "name": "Šatna a umývárna", "polygon": rect(HX1, -4.55, AX1 - 0.45, -0.975),
         "ceiling_height": 2.85, "ceiling": {"type": "timber_ceiling_on_joists", "underside": 2.85},
         "floor_material": "ceramic_tiles_grey", "in_zone": True},
        {"id": "DL_R_KOMPRESOR", "level": "L0", "name": "Kompresorovna (kůlna)", "polygon": rect(KX0 + TK, KY0 + TK, HX0, KY1 - TK),
         "ceiling_height": 2.45, "ceiling": {"type": "mono_roof_purlins", "lowest_underside": 2.45},
         "floor_material": "concrete_oil_stained", "in_zone": True},
    ]
    tp30 = math.tan(math.radians(30))
    roof = [
        {"id": "RF_HALA", "type": "gable", "pitch_deg": 30.0, "ridge_axis": "X", "wall_rect": rect(HX0, -5.0, HX1, 5.0),
         "eave_z": HALL_TOP, "ridge_z": r3(HALL_TOP + 5.0 * tp30), "overhang_eave": 0.45,
         "overhang_verge": {"-X": 0.30, "+X": 0.30},
         "material": "corrugated_sheet_dark_grey_weathered", "structure": "timber king-post trusses at 3.0 m, tie beams underside z 4.20",
         "fascia": "steel_verge_flashing_dark", "soffit": "open rafters",
         "roof_lights": [{"id": "DL_RL1", "center": [2.9, 2.6], "size": [0.9, 1.3], "type": "wired_glass_rooflight_in_corrugated_sheet",
                          "walkable": False, "note": "ref. 04: roof light on the front slope above gate G1"}]},
        {"id": "RF_PRISTAVEK", "type": "gable", "pitch_deg": 30.0, "ridge_axis": "X", "wall_rect": rect(HX1, -5.0, AX1, AY1),
         "eave_z": ANX_TOP, "ridge_z": r3(ANX_TOP + 3.9 * tp30), "overhang_eave": 0.35,
         "overhang_verge": {"-X": 0.0, "+X": 0.30}, "abuts": {"-X": "DL_H_E (lead-free flashing into the hall gable)"},
         "material": "corrugated_sheet_dark_grey_weathered", "structure": "timber rafters on purlins, ceiling joists at 2.85-3.00",
         "fascia": "timber_board_0.20_dark", "soffit": "open rafters"},
        {"id": "RF_KULNA", "type": "mono", "pitch_deg": r3(math.degrees(math.atan2(KH - KL, HX0 - KX0))), "slope_direction": "-X",
         "wall_rect": rect(KX0, KY0, HX0, KY1), "rect": rect(KX0 - 0.30, KY0 - 0.20, HX0, KY1 + 0.20),
         "eave_z": KL, "high_z": KH, "overhang_eave": 0.30,
         "material": "corrugated_sheet_dark_grey_weathered", "structure": "timber purlins on the side walls, flashing into the hall gable",
         "note": "lean-to roof falls away from the hall (ref. 04)"},
    ]
    rh, ra, rk = roof
    gutters = [
        gutter(rh, "+Y", (HX0 - 0.30, 5.0 + 0.45), (HX1 + 0.30, 5.0 + 0.45), "half_round_125_galv"),
        gutter(rh, "-Y", (HX0 - 0.30, -5.0 - 0.45), (HX1 + 0.30, -5.0 - 0.45), "half_round_125_galv"),
        gutter(ra, "+Y", (HX1, AY1 + 0.35), (AX1 + 0.30, AY1 + 0.35), "half_round_125_galv"),
        gutter(ra, "-Y", (HX1, -5.0 - 0.35), (AX1 + 0.30, -5.0 - 0.35), "half_round_125_galv"),
        gutter(rk, "-X", (KX0 - 0.30, KY0 - 0.20), (KX0 - 0.30, KY1 + 0.20), "half_round_100_galv"),
    ]
    gz_h, gz_a, gz_k = gutters[0]["z"], gutters[2]["z"], gutters[4]["z"]
    downpipes = [
        {"id": "DL_DP1", "pos": [HX1 - 0.25, 5.12], "top_z": gz_h, "dia": 0.10, "outlet": "splash_block_to_yard_channel"},
        {"id": "DL_DP2", "pos": [-1.05, 5.12], "top_z": gz_h, "dia": 0.10, "outlet": "splash_block_to_yard_channel",
         "note": "between the gates beside the vent slot (ref. 04)"},
        {"id": "DL_DP3", "pos": [HX0 + 0.25, 5.12], "top_z": gz_h, "dia": 0.10, "outlet": "splash_block_to_yard_channel"},
        {"id": "DL_DP4", "pos": [HX0 + 0.25, -5.12], "top_z": gz_h, "dia": 0.10, "outlet": "rear_pad_channel"},
        {"id": "DL_DP5", "pos": [HX1 - 0.25, -5.12], "top_z": gz_h, "dia": 0.10, "outlet": "rear_pad_channel"},
        {"id": "DL_DP6", "pos": [AX1 - 0.25, AY1 + 0.12], "top_z": gz_a, "dia": 0.10, "outlet": "gully_G_DL1"},
        {"id": "DL_DP7", "pos": [HX1 + 0.20, AY1 + 0.12], "top_z": gz_a, "dia": 0.10, "outlet": "splash_block_to_yard_channel",
         "note": "in the corner between the annex front and the hall gable (ref. 04)"},
        {"id": "DL_DP8", "pos": [AX1 - 0.25, -5.12], "top_z": gz_a, "dia": 0.10, "outlet": "old_tailrace_to_brook"},
        {"id": "DL_DP9", "pos": [KX0 - 0.12, KY1 - 0.20], "top_z": gz_k, "dia": 0.08, "outlet": "splash_block"},
    ]
    drainage = {"yard": "gravel yard falls 1 % towards the brook; a concrete dish channel along the gate side collects DL_DP1-3/DP7 "
                        "and the gate aprons and discharges through the yard bank wall into the brook",
                "rear_pad": "stone-lined drain channel at the foot of RW_DILNA collects the weep holes (every 2.0 m, 0.30 m above the "
                            "pad) and DL_DP4/DP5, runs to the old tailrace beside the annex and into the brook",
                "gullies": [{"id": "G_DL1", "pos": [AX1 + 0.40, AY1 + 0.40], "type": "cast_iron_gully_300"}]}
    foundation = {"plinth_height_above_floor": 0.30, "plinth_visible_height": 0.47, "plinth_material": "stone_greywacke_rubble_plinth",
                  "ground_levels": {"front_yard": -0.17, "rear_pad": -0.17, "gable_-X": -0.17, "gable_+X": -0.17},
                  "footing": "stone strip footing 0.60 wide, 0.80 deep (hidden)",
                  "floor_to_terrain_rule": "terrain pad PAD_DILNA around the building is flat at floor - 0.17 on all sides (one riser); "
                                           "every door has a 0.17 step or a gate ramp"}
    exterior_steps = [
        {"id": "DL_X1", "at": "DL_G1", "type": "ramp", "polygon": rect(-0.05, 5.0, 3.65, 6.5), "z_top": 0.0, "z_bottom": -0.17,
         "slope_pct": r3(17.0 / 1.5), "material": "concrete_broom"},
        {"id": "DL_X6", "at": "DL_G2", "type": "ramp", "polygon": rect(-5.95, 5.0, -3.05, 6.5), "z_top": 0.0, "z_bottom": -0.17,
         "slope_pct": r3(17.0 / 1.5), "material": "concrete_broom"},
        {"id": "DL_X2", "at": "DL_D7", "type": "step", "polygon": rect(-11.25, KY1, -9.85, KY1 + 0.35), "risers": 1, "riser": 0.17,
         "material": "concrete"},
        {"id": "DL_X3", "at": "DL_D3", "type": "step", "polygon": rect(HX0 - 0.35, -3.30, HX0, -1.90), "risers": 1, "riser": 0.17,
         "material": "stone_slab"},
        {"id": "DL_X4", "at": "DL_D6", "type": "step", "polygon": rect(AX1, 0.50, AX1 + 0.35, 1.90), "risers": 1, "riser": 0.17,
         "material": "concrete"},
        {"id": "DL_X5", "at": "DL_D2", "type": "step", "polygon": rect(-2.70, -5.35, -1.30, -5.0), "risers": 1, "riser": 0.17,
         "material": "concrete"},
    ]
    furniture = [
        furn("DL_F1", "L0", "tractor_dismantled", (-2.0, -0.4), (3.8, 1.9, 2.4), 0, "high",
             note="old tractor on blocks, wheels off -- the hall's central hard cover"),
        furn("DL_F2", "L0", "lathe", (2.9, -3.75), (2.6, 1.0, 1.40), 0, "low"),
        furn("DL_F3", "L0", "lathe", (-5.6, -3.75), (2.6, 1.0, 1.40), 0, "low"),
        furn("DL_F4", "L0", "milling_machine", (3.9, 2.4), (1.4, 1.6, 2.10), 0, "high"),
        furn("DL_F5", "L0", "workbench", (-7.85, -0.35), (0.8, 2.4, 0.95), 0, "low"),
        furn("DL_F6", "L0", "profile_rack_steel", (-5.3, 1.3), (0.8, 3.6, 2.40), 0, "high",
             note="steel profile rack: splits the west half of the hall into two lanes"),
        furn("DL_F7", "L0", "oil_drums_x4", (0.9, -3.9), (1.2, 1.2, 0.90), 0, "low"),
        furn("DL_F8", "L0", "pallet_stack", (-7.7, -3.9), (1.2, 1.0, 1.10), 0, "low"),
        furn("DL_F9", "L0", "welding_cart", (1.4, 0.9), (0.8, 0.6, 1.00), 0, "low"),
        furn("DL_F10", "L0", "forge_hearth_brick", (1.0, 2.6), (1.4, 1.0, 0.90), 0, "low",
             note="brick forge hearth; its steel hood and flue feed chimney DL_CH1 (ref. 04 chimney 1)"),
        furn("DL_F11", "L0", "stove_cast_iron", (-3.9, 2.9), (0.7, 0.7, 1.10), 0, "low",
             note="workshop stove; flue pipe to chimney DL_CH2 (ref. 04 chimney 2)"),
        furn("DL_F12", "L0", "shelving_steel_loaded", (-8.0, 3.1), (0.6, 1.4, 2.20), 0, "high",
             note="ref. 04: loaded steel shelving visible through gate G1"),
        furn("DL_F13", "L0", "desk_steel", (8.6, 1.9), (1.6, 0.8, 0.75), 0, "low"),
        furn("DL_F14", "L0", "tool_counter", (7.6, -0.5), (3.0, 0.6, 1.00), 0, "low", note="issue counter along the partition"),
        furn("DL_F15", "L0", "shelving_steel_loaded", (11.5, -0.2), (0.6, 1.2, 2.00), 0, "high"),
        furn("DL_F16", "L0", "lockers_row", (7.9, -1.30), (3.4, 0.5, 1.90), 0, "high"),
        furn("DL_F17", "L0", "wash_trough", (11.45, -2.75), (0.6, 1.8, 0.90), 0, "low"),
        furn("DL_F18", "L0", "compressor", (-11.35, 0.90), (0.7, 1.4, 1.10), 0, "low"),
        furn("DL_F19", "L0", "air_tank_vertical", (-9.3, 0.30), (0.7, 0.7, 1.80), 0, "high"),
    ]
    fixtures = [
        {"id": "DL_L1", "type": "wall_lamp_enamel_gooseneck", "wall": "DL_H_N", "pos": [1.80, 5.0], "z": 3.85, "note": "above gate G1 (ref. 04)"},
        {"id": "DL_L2", "type": "wall_lamp_enamel_gooseneck", "wall": "DL_H_N", "pos": [-4.50, 5.0], "z": 3.85, "note": "above gate G2 (ref. 04)"},
        {"id": "DL_L3", "type": "bulkhead_lamp_caged", "wall": "DL_K_N", "pos": [-10.55, KY1], "z": 2.45, "note": "above the lean-to door"},
        {"id": "DL_L4", "type": "steel_lintel_beam_exposed", "wall": "DL_H_N", "pos": [1.80, 5.0], "z": 3.50, "length": 4.20},
        {"id": "DL_L5", "type": "steel_lintel_beam_exposed", "wall": "DL_H_N", "pos": [-4.50, 5.0], "z": 3.50, "length": 3.40},
        {"id": "DL_S1", "type": "faded_painted_sign", "wall": "DL_H_N", "pos": [-1.20, 5.0], "z": 4.10,
         "text_cs": "KALINA A SYN - ZÁMEČNICTVÍ", "note": "fictional firm"},
    ]
    return finalize({
        "id": "B_DILNA", "type": "dilna", "name": "Dílna (bývalý hamr)", "enterable": True,
        "story": "Hamr na Kalném potoce stál na tomto místě od 18. století; náhon od jezu pod štěrkovnou přiváděl vodu na kolo "
                 "u štítu přístavku. Kolem roku 1924 rodina Kalinů přestavěla hamr na cihlovou zámečnickou dílnu, v 60. letech "
                 "se z ní stala opravna zemědělských strojů. Přízemní hala bez stropu (vazníky, dvě dvoukřídlá vrata, výheň "
                 "s komínem), nižší přístavek s výdejnou nářadí a šatnou a malá kůlna s kompresorem (reference 04).",
        "reference": "Docs/navrhy/04_dilna_samostatne.png (primary), 02_dilna_potok_lavka.png, 01_letecky_pohled_vesnice.png",
        "local_origin": "centre of the whole external bounding box X[-12.25,12.25] x Y[-5.0,5.0] at finished L0 floor (z 0.00); "
                        "+Y = front (yard, brook)",
        "footprint_external": [24.5, 10.0],
        "footprint_parts": [
            {"part": "hall", "external_rect": rect(HX0, -5.0, HX1, 5.0), "interior_rect": rect(HX0 + 0.45, -4.55, HX1 - 0.45, 4.55),
             "walls": {"x": [0.45, 0.45], "y": [0.45, 0.45]}, "check": "14.50 = 0.45 + 13.60 + 0.45; 10.00 = 0.45 + 9.10 + 0.45"},
            {"part": "annex", "external_rect": rect(HX1, -5.0, AX1, AY1), "interior_rect": rect(HX1, -4.55, AX1 - 0.45, AY1 - 0.45),
             "walls": {"x": [0.0, 0.45], "y": [0.45, 0.45]},
             "check": "6.50 = 0 (hall gable counted in the hall) + 6.05 + 0.45; 7.80 = 0.45 + 6.90 + 0.45"},
            {"part": "lean_to", "external_rect": rect(KX0, KY0, HX0, KY1), "interior_rect": rect(KX0 + TK, KY0 + TK, HX0, KY1 - TK),
             "walls": {"x": [TK, 0.0], "y": [TK, TK]},
             "check": "3.50 = 0.30 + 3.20 + 0 (hall gable); 5.00 = 0.30 + 4.40 + 0.30"},
        ],
        "structure": "load-bearing brick masonry 450 (hall and annex), 300 (lean-to), 150 brick partition; timber roofs with "
                     "corrugated sheeting; exterior lime render peeling to the red brick (about 30-40 % bare brick, ref. 04)",
        "levels": levels, "rooms": rooms, "sealed_voids": [], "walls": b.walls, "openings": b.openings,
        "slabs": [], "stairs": [], "exterior_stairs": [], "balustrades": [], "balconies": [],
        "roof": roof, "gutters": gutters, "downpipes": downpipes, "drainage": drainage, "foundation": foundation,
        "exterior_steps": exterior_steps,
        "chimneys": [{"id": "DL_CH1", "type": "brick", "pos": [1.0, 1.0], "size": [0.75, 0.75], "base_z": 4.25,
                      "top_z": r3(HALL_TOP + 4.0 * tp30 + 1.20), "serves": "DL_F10",
                      "note": "brick stack with corbelled cap and vent holes (ref. 04), corbelled on the tie beams at 4.25; "
                              "steel hood + flue from the forge DL_F10 below"},
                     {"id": "DL_CH2", "type": "brick", "pos": [-3.9, 1.0], "size": [0.70, 0.70], "base_z": 4.25,
                      "top_z": r3(HALL_TOP + 4.0 * tp30 + 1.00), "serves": "DL_F11",
                      "note": "second brick stack (ref. 04); flue pipe from the stove DL_F11"}],
        "furniture": furniture, "fixtures": fixtures,
        "zone_notes": "zone_dilna counts the whole single-storey building (hall, annex rooms, lean-to) and the yard between the "
                      "hall and the brook; the mill-race terrace behind RW_DILNA is outside the polygon",
    }, gable_ext={"DL_H_E": (0.45, 0.45), "DL_H_W": (0.45, 0.45), "DL_A_E": (0.45, 0.45),
                  "DL_K_N": (0.0, 0.0), "DL_K_S": (0.0, 0.0)})


# ================================================================================================
# 2) SKLAD -- warehouse as references 01/03: long brick hall, green corrugated gable roof, sliding doors
# ================================================================================================
def sklad():
    b = B("B_SKLAD")
    T = T_EXT_MASONRY
    X0, X1, Y0, Y1 = -12.5, 12.5, -6.25, 6.25
    H = 5.50
    mat = "brick_masonry_450_with_plastered_pilasters"
    fin_in = "brick_limewash_white"
    fin_out = "brick_red_weathered_with_plastered_pilasters_and_band"
    walls = b.ext_rect("SK", "L0", X0, Y0, X1, Y1, T, H, mat, fin_in, fin_out, gables=("E", "W"), gable_roof="RF_SKLAD")
    b.wall("SK_P1", "L0", (X0 + 0.45, 2.275), (-8.2, 2.275), T_INT, 3.00, "internal", "block_partition_150",
           "plaster_white", "plaster_white", note="office | hall (along X)")
    b.wall("SK_P2", "L0", (-8.275, 2.35), (-8.275, Y1 - 0.45), T_INT, 3.00, "internal", "block_partition_150",
           "plaster_white", "plaster_white", note="office | hall (along Y)")
    # bays of 5.0 m between pilasters at x = -12.5, -7.5, -2.5, 2.5, 7.5, 12.5 (ref. 03: brick panels between plastered piers)
    SD = {"type": "steel_sliding_door_top_hung", "thickness": 0.08, "material": "steel_sheet_grey_weathered"}
    # front (+Y) = dock side (west in the world), seen from the yard left (+X) to right (-X)
    b.opening("SK_W4", "SK_N", "window", 10.0, 2.40, 1.50, 3.70, False, glazing="steel_industrial_multipane_6x5")
    b.opening("SK_SD2", "SK_N", "sliding_door", 5.0, 3.60, 0.0, 4.00, True, leaf=SD, state={"open": False},
              note="bay 2: closed and padlocked (ref. 03 shows closed grey sliding doors); baked as wall in the navmesh")
    b.door("SK_D1", "SK_N", 1.40, "start", "left", "steel_insulated", "steel_grey", thickness=0.06, width=1.26,
           note="personnel door onto the dock (bay 3); the parked leaf of SK_SD1 covers the wall x -3.25..0.45")
    b.opening("SK_SD1", "SK_N", "sliding_door", -5.0, 3.60, 0.0, 4.00, True, leaf=SD, state={"open": True, "park": "start"},
              note="bay 4: open, leaf parked towards +X over the solid bay-3 wall")
    b.opening("SK_W1", "SK_N", "window", -9.2, 1.20, 1.00, 2.40, False, glazing="steel_multipane_3x4", note="office")
    b.door("SK_D2", "SK_N", -11.20, "end", "left", "steel_insulated_glazed", "steel_grey", thickness=0.06, width=1.26,
           note="office door onto the dock")
    # rear (-Y) = rear yard (east): open sliding door + personnel door + high windows
    b.opening("SK_SD3", "SK_S", "sliding_door", -5.0, 3.60, 0.0, 4.00, True, leaf=SD, state={"open": True, "park": "start"},
              note="rear sliding door, open; leaf parked towards -X over the solid bay-5 rear wall")
    for i, x in enumerate((0.0, 5.0)):
        b.opening(f"SK_WH{i + 1}", "SK_S", "window", x, 2.40, 2.40, 4.20, False, glazing="steel_industrial_multipane_6x4",
                  note="high rear window (not a firing position)")
    b.door("SK_D4", "SK_S", 9.0, "start", "right", "steel_insulated", "steel_grey", thickness=0.06, width=1.26)
    # south gable (-X) towards the square and the chapel: window, office window, door, small gable window (ref. 01/03)
    b.door("SK_D5", "SK_W", -3.30, "start", "right", "steel_insulated", "steel_grey", thickness=0.06, width=1.26)
    b.opening("SK_W2", "SK_W", "window", 0.20, 2.40, 1.30, 3.90, False, glazing="steel_industrial_multipane_6x5")
    b.opening("SK_W3", "SK_W", "window", 4.20, 1.20, 1.00, 2.40, False, glazing="steel_multipane_3x4", note="office")
    b.opening("SK_WG1", "SK_W", "window", 0.0, 0.90, 6.00, 6.80, False, glazing="steel_multipane_3x3",
              note="gable window near the apex (ref. 03); not reachable")
    # north gable (+X)
    b.door("SK_D6", "SK_E", 1.20, "end", "left", "steel_insulated", "steel_grey", thickness=0.06, width=1.26)
    b.opening("SK_W5", "SK_E", "window", -3.0, 2.40, 1.30, 3.90, False, glazing="steel_industrial_multipane_6x5")
    b.opening("SK_WG2", "SK_E", "window", 0.0, 0.90, 6.00, 6.80, False, glazing="steel_multipane_3x3")
    # office internals
    b.door("SK_D3", "SK_P2", 3.35, "start", "right", "timber_flush", "hpl_grey", note="office -> hall")
    b.opening("SK_W6", "SK_P1", "window", -10.2, 1.50, 1.00, 2.20, False, glazing="internal_single_glazed",
              note="office window into the hall")
    pilasters = []
    for wid in ("SK_N", "SK_S"):
        for x in (-12.5, -7.5, -2.5, 2.5, 7.5, 12.5):
            pilasters.append({"wall": wid, "x": x, "width": 0.60, "proud": 0.15, "z": [0.0, H],
                              "material": "render_lime_offwhite_weathered", "note": "plastered brick pier (ref. 03)"})
    for wid in ("SK_W", "SK_E"):
        for y in (-6.25, 6.25):
            pilasters.append({"wall": wid, "y": y, "width": 0.60, "proud": 0.15, "z": [0.0, H],
                              "material": "render_lime_offwhite_weathered"})
    levels = [{"id": "L0", "name": "Hala", "floor_z": 0.0, "ceiling_height": 5.20, "floor_thickness": 0.20,
               "note": "clear height to the truss bottom chords 5.20; floor is 1.10 above the front yard (truck-bed height) "
                       "and at grade with the gable aprons and the rear yard"}]
    rooms = [
        {"id": "SK_R_HALA", "level": "L0", "name": "Skladová hala",
         "polygon": [[X0 + 0.45, Y0 + 0.45], [X1 - 0.45, Y0 + 0.45], [X1 - 0.45, Y1 - 0.45], [-8.2, Y1 - 0.45], [-8.2, 2.20],
                     [X0 + 0.45, 2.20]], "ceiling_height": 5.20, "ceiling": {"type": "roof_trusses", "bottom_chord": 5.20},
         "floor_material": "concrete_industrial_sealed", "in_zone": "front half"},
        {"id": "SK_R_KANCELAR", "level": "L0", "name": "Kancelář skladu", "polygon": rect(X0 + 0.45, 2.35, -8.35, Y1 - 0.45),
         "ceiling_height": 2.85, "ceiling": {"type": "slab", "slab": "SK_OFFICE_CEILING"}, "floor_material": "vinyl_tiles_grey",
         "note": "closed box inside the hall: 0.15 concrete ceiling slab on the 3.00 m block partitions (top z 3.00, NOT walkable, "
                 "no ladder); underside 2.85"},
    ]
    slabs = [{"id": "SK_OFFICE_CEILING", "level": "OFFICE_ROOF", "role": "ceiling", "walkable": False,
              "polygon": rect(X0 + 0.45, 2.20, -8.20, Y1 - 0.45), "thickness": 0.15, "top_z": 3.00, "openings": [],
              "note": "rests on SK_P1/SK_P2 and the external walls; top is a dusty storage deck without access"}]
    tp20 = math.tan(math.radians(20))
    roof = [{"id": "RF_SKLAD", "type": "gable", "pitch_deg": 20.0, "ridge_axis": "X", "wall_rect": rect(X0, Y0, X1, Y1),
             "eave_z": H, "ridge_z": r3(H + 6.25 * tp20), "overhang_eave": 0.40,
             "overhang_verge": {"-X": 0.25, "+X": 0.25}, "material": "corrugated_steel_green_weathered",
             "structure": "riveted steel trusses at 5.0 m on the brick piers, timber purlins",
             "fascia": "steel_flashing_green",
             "ridge_vent": {"from": [-9.0, 0.0], "to": [9.0, 0.0], "width": 0.80, "height": 0.55,
                            "note": "raised ridge ventilator with louvres (ref. 01)"}},
            {"id": "RF_RAMPA", "type": "mono", "pitch_deg": 5.0, "slope_direction": "+Y", "rect": rect(X0, Y1, X1, Y1 + 3.35),
             "wall_rect": rect(X0, Y1, X1, Y1 + 3.0), "eave_z": r3(4.60 - 3.0 * math.tan(math.radians(5))), "high_z": 4.60,
             "overhang_eave": 0.35, "material": "corrugated_steel_grey",
             "supports": [{"pos": [x, Y1 + 2.85], "size": [0.16, 0.16]} for x in (-12.3, -5.0, 1.0, 7.0, 12.3)],
             "note": "dock canopy (ref. 01: lower roof strip along the west side) on brackets; posts on the dock edge kept "
                     ">= 0.3 m clear of the stair spans SK_X1/SK_X2 (review P2-ACCESS-CLUTTER)"}]
    rs, rr = roof
    gutters = [
        gutter(rs, "+Y", (X0 - 0.25, Y1 + 0.40), (X1 + 0.25, Y1 + 0.40), "half_round_150_galv",
               note="discharges onto canopy RF_RAMPA via spreaders"),
        gutter(rs, "-Y", (X0 - 0.25, Y0 - 0.40), (X1 + 0.25, Y0 - 0.40), "half_round_150_galv"),
        gutter(rr, "+Y", (X0, Y1 + 3.35), (X1, Y1 + 3.35), "half_round_150_galv"),
    ]
    gz, gzr = gutters[1]["z"], gutters[2]["z"]
    downpipes = [
        {"id": "SK_DP1", "pos": [X0 + 0.35, Y0 - 0.12], "top_z": gz, "dia": 0.12, "outlet": "gully_G_SK1"},
        {"id": "SK_DP2", "pos": [2.9, Y0 - 0.12], "top_z": gz, "dia": 0.12, "outlet": "gully_G_SK2"},
        {"id": "SK_DP3", "pos": [X1 - 0.35, Y0 - 0.12], "top_z": gz, "dia": 0.12, "outlet": "gully_G_SK3"},
        {"id": "SK_DP4", "pos": [-12.3, Y1 + 2.97], "top_z": gzr, "dia": 0.12, "outlet": "dock_foot_channel", "note": "on canopy post"},
        {"id": "SK_DP5", "pos": [12.3, Y1 + 2.97], "top_z": gzr, "dia": 0.12, "outlet": "dock_foot_channel", "note": "on canopy post"},
    ]
    drainage = {"rear": "three cast-iron gullies at the rear downpipes, piped under the rear yard to the ditch south of the platform",
                "dock": "slotted concrete channel along the dock foot (yard side) collects the canopy downpipes and the yard; "
                        "outfall to the road-side ditch of ROAD_B at the yard gate",
                "gullies": [{"id": "G_SK1", "pos": [X0 + 0.35, Y0 - 0.5]}, {"id": "G_SK2", "pos": [2.9, Y0 - 0.5]},
                            {"id": "G_SK3", "pos": [X1 - 0.35, Y0 - 0.5]}]}
    foundation = {"plinth_height_above_floor": 0.40, "plinth_material": "concrete_plinth_rendered_grey",
                  "ground_levels": {"front (+Y)": "loading dock SK_DOCK at 0.00 (the yard beyond the dock face is -1.10)",
                                    "rear (-Y)": -0.05, "gables (+-X, 3 m aprons)": -0.05,
                                    "note": "building, dock, gable aprons and rear yard sit on one platform cut into the slope "
                                            "(retaining wall RW_SKLAD_NE); the front yard is the 1976 flood-protection fill, "
                                            "1.10 lower (truck-bed height)"},
                  "footing": "strip footings under the brick walls and piers (hidden)"}
    dock = {"id": "SK_DOCK", "type": "loading_dock", "polygon": rect(X0 - 3.0, Y1, X1 + 3.0, Y1 + 3.0), "top_z": 0.0, "bottom_z": -1.10,
            "edge": "steel angle nosing + 4 rubber bumpers (0.25 proud) at x = -8, -3, 3, 8", "material": "concrete_broom",
            "face": "RW_SKLAD_DOCK (the dock face and its north return are the terrain step; gaps at SK_X1, SK_X2, SK_X3)",
            "access": ["SK_X1 stair (yard, south part)", "SK_X2 stair (yard, middle)", "SK_X3 ramp (yard, north end)",
                       "gable aprons at grade (platform: rear yard and the north pocket between the warehouse and the windbreak)"],
            "note": "1.10 m face is NOT a step (max step 0.40): from the yard only via SK_X1/SK_X2/SK_X3; one-way drop down "
                    "allowed; players can mantle it (traversal 0.5-1.3 m) and bots get the same mantle off-mesh link"}
    R = 1.10 / 6.0
    ext_stairs = [
        stair_flight("SK_X1", "ground", "L0", (-9.0, Y1 + 3.0 + 5 * 0.28), 180.0, 1.50, R, 0.28, 6, -1.10,
                     construction="precast_concrete_steps_on_solid_base", handrail="both (steel pipe)", waist=0.0,
                     under_stair={"treatment": "solid_mass"}, foot_ground=-1.10,
                     note="perpendicular to the dock face, stands on the flat yard (both sides free), rises towards the dock"),
        stair_flight("SK_X2", "ground", "L0", (3.8, Y1 + 3.0 + 5 * 0.28), 180.0, 2.00, R, 0.28, 6, -1.10,
                     construction="precast_concrete_steps_on_solid_base", handrail="none (2.0 wide, open both sides)", waist=0.0,
                     under_stair={"treatment": "solid_mass"}, foot_ground=-1.10, note="dock middle"),
    ]
    exterior_steps = [
        {"id": "SK_X3", "at": "dock north end", "type": "ramp", "polygon": rect(X1 + 0.1, Y1 + 3.0, X1 + 2.9, Y1 + 3.0 + 6.6),
         "z_top": 0.0, "z_bottom": -1.10, "foot_ground": -1.10, "slope_pct": r3(110 / 6.6), "rise_direction_deg": 180.0,
         "construction": "solid concrete wedge on the flat yard, both side faces free", "material": "concrete_broom",
         "note": "vehicle/pallet ramp 1:6 (9.5 deg) perpendicular to the dock face; walkable"},
        {"id": "SK_X4", "at": "SK_D5", "type": "threshold", "polygon": rect(X0 - 0.30, -3.95, X0, -2.65), "risers": 0, "riser": 0.05,
         "apron": {"polygon": rect(X0 - 3.0, Y0, X0, Y1), "z": -0.05}, "material": "concrete",
         "note": "gable apron 3 m beyond the gable at floor -0.05 (terrain pad PAD_SKLAD): flush threshold, no step"},
        {"id": "SK_X5", "at": "SK_D6", "type": "threshold", "polygon": rect(X1, 0.55, X1 + 0.30, 1.85), "risers": 0, "riser": 0.05,
         "apron": {"polygon": rect(X1, Y0, X1 + 3.0, Y1), "z": -0.05}, "material": "concrete",
         "note": "gable apron 3 m beyond the gable at floor -0.05: flush threshold, no step"},
    ]
    furniture = [
        furn("SK_F1", "L0", "pallet_racking_full", (-1.0, 1.15), (9.8, 1.10, 3.60), 0, "high", note="rack run 1a (x -5.9..3.9), loaded solid"),
        furn("SK_F2", "L0", "pallet_racking_full", (8.55, 1.15), (4.7, 1.10, 3.60), 0, "high", note="rack run 1b; gap x 3.9..6.2 = cross aisle; ends 1.1 m short of the gable door SK_D6"),
        furn("SK_F3", "L0", "pallet_racking_full", (-4.1, -3.55), (9.2, 1.10, 3.60), 0, "high", note="rack run 2a (x -8.7..0.5)"),
        furn("SK_F4", "L0", "pallet_racking_full", (7.1, -3.55), (8.2, 1.10, 3.60), 0, "high", note="rack run 2b; gap x 0.5..3.0 = cross aisle; ends 0.8 m short of the gable window SK_W5"),
        furn("SK_F5", "L0", "forklift", (-9.2, -0.9), (2.3, 1.2, 2.10), 0, "high", note="parked forklift (ref. 02/03), clear of the gable window SK_W2"),
        furn("SK_F6", "L0", "pallets_bagged_cement", (4.2, 4.4), (1.2, 1.0, 1.20), 0, "low"),
        furn("SK_F7", "L0", "pallets_bagged_cement", (9.9, 4.6), (1.2, 2.0, 1.20), 0, "low"),
        furn("SK_F8", "L0", "big_bags_x3", (-10.3, -4.6), (1.0, 2.2, 1.40), 0, "low"),
        furn("SK_F9", "L0", "ibc_tanks_x2", (10.8, -5.05), (2.2, 1.0, 1.15), 0, "low"),
        furn("SK_F10", "L0", "desk_office", (-11.0, 3.6), (1.6, 0.8, 0.75), 90, "low"),
        furn("SK_F11", "L0", "filing_cabinets", (-8.6, 4.55), (0.9, 0.5, 1.40), 90, "low"),
        furn("SK_F12", "exterior", "euro_pallet_stack_4", (-6.2, Y1 + 1.6), (1.2, 0.8, 0.60), 0, "none",
             blocks_bullets=False, note="on the dock; wood: concealment only (ref. R08)"),
        furn("SK_F13", "exterior", "pallets_bagged_cement", (6.8, Y1 + 1.5), (1.2, 1.0, 1.20), 0, "low", note="on the dock"),
        furn("SK_F14", "exterior", "pallet_jack", (-1.4, Y1 + 1.2), (1.6, 0.6, 1.20), 0, "none"),
    ]
    fixtures = [{"id": "SK_S1", "type": "painted_sign", "wall": "SK_N", "pos": [0.0, Y1], "z": 4.60,
                 "text_cs": "STAVEBNINY KALINA", "note": "fictional firm, above the dock canopy"},
                {"id": "SK_S2", "type": "faded_painted_sign", "wall": "SK_W", "pos": [X0, 0.0], "z": 0.25,
                 "text_cs": "JZD KALNÉ HAMRY - SKLAD HNOJIV 1976", "note": "on the rendered plinth of the south gable"}]
    return finalize({
        "id": "B_SKLAD", "type": "mensi_sklad", "name": "Menší sklad (stavebniny a zemědělské potřeby)", "enterable": True,
        "story": "Cihlový sklad hnojiv a osiv postavilo JZD v roce 1976 na plošině zaříznuté do svahu u návsi, s 1 m vysokým "
                 "protipovodňovým násypem dvora. Podlaha je ve výšce ložné plochy nákladního auta nad dvorem, podél průčelí "
                 "vede nakládací rampa pod přístřeškem. Od roku 2004 slouží firmě Stavebniny Kalina (fiktivní). Dlouhá hala "
                 "z režných cihel s omítnutými pilíři, zelená vlnitá střecha a posuvná ocelová vrata (reference 01 a 03).",
        "reference": "Docs/navrhy/03_ulice_kaple_sklad.png, 01_letecky_pohled_vesnice.png",
        "local_origin": "centre of the hall X[-12.5,12.5] x Y[-6.25,6.25] at finished floor (z 0.00); +Y = front (loading dock)",
        "footprint_external": [25.0, 12.5],
        "footprint_parts": [{"part": "hall", "external_rect": rect(X0, Y0, X1, Y1), "interior_rect": rect(X0 + 0.45, Y0 + 0.45, X1 - 0.45, Y1 - 0.45),
                             "walls": {"x": [0.45, 0.45], "y": [0.45, 0.45]},
                             "check": "25.00 = 0.45 + 24.10 + 0.45; 12.50 = 0.45 + 11.60 + 0.45"}],
        "structure": "brick masonry 450 with plastered brick piers every 5.0 m (0.60 wide, 0.15 proud), riveted steel trusses "
                     "on the piers, corrugated steel roof sheeting (green, weathered); concrete plinth 0.40",
        "levels": levels, "rooms": rooms, "sealed_voids": [], "walls": b.walls, "openings": b.openings, "columns": [],
        "pilasters": pilasters, "slabs": slabs, "stairs": [], "exterior_stairs": ext_stairs, "balustrades": [], "balconies": [],
        "roof": roof, "gutters": gutters, "downpipes": downpipes, "drainage": drainage, "foundation": foundation,
        "loading_dock": dock, "exterior_steps": exterior_steps,
        "chimneys": [{"id": "SK_CH1", "type": "brick", "pos": [-10.25, 5.4], "size": [0.50, 0.50], "base_z": 3.00,
                      "top_z": r3(H + 1.35 * tp20 + 1.0), "serves": "SK_F15",
                      "note": "office stove chimney (ref. 03 shows two small stacks on the ridge side), starts on the office ceiling slab"}],
        "furniture": furniture + [furn("SK_F15", "L0", "stove_cast_iron", (-10.25, 5.4), (0.6, 0.6, 0.90), 0, "low", note="office stove")],
        "fixtures": fixtures,
        "zone_notes": "zone_sklad polygon covers the dock, the front aisle, the office and the first rack row; racks are not climbable",
    }, gable_ext={"SK_E": (0.45, 0.45), "SK_W": (0.45, 0.45)})


# ================================================================================================
# 3) OBYTNÝ DŮM -- two-storey house with a red clay-tile hip roof, dormers and a one-storey wing (ref. 01)
# ================================================================================================
def dum():
    b = B("B_DUM")
    T = T_EXT_MASONRY
    FF = 3.00          # floor-to-floor
    CH = 2.75          # clear ceiling height both floors
    TOP = 6.10         # external wall plate
    WX0, WY0, WY1 = -10.0, -1.25, 4.75     # wing X[-10,-5.5] x Y[-1.25,4.75]
    WTOP = 2.90
    mat = "brick_masonry_450"
    fin_out = "render_lime_cream_weathered"
    for lv, h in (("L0", FF), ("L1", TOP - FF)):
        b.ext_rect(f"DM{lv[1]}", lv, -5.5, -4.75, 5.5, 4.75, T, h, mat, "plaster_white_painted", fin_out)
        b.wall(f"DM{lv[1]}_SP", lv, (-5.05, 0.0), (5.05, 0.0), 0.30, CH, "internal", "brick_loadbearing_300",
               "plaster_white_painted", "plaster_white_painted", note="spine wall (carries floor joists)")
    # wing (L0): S (+X), W, N (-X); its east side is the house west wall DM0_W
    b.wall("DM0_WG_S", "L0", (WX0, WY0 + 0.225), (-5.5, WY0 + 0.225), T, WTOP, "external", mat, "plaster_white_painted", fin_out)
    b.wall("DM0_WG_N", "L0", (-5.5, WY1 - 0.225), (WX0, WY1 - 0.225), T, WTOP, "external", mat, "plaster_white_painted", fin_out)
    b.wall("DM0_WG_W", "L0", (WX0 + 0.225, WY1 - 0.45), (WX0 + 0.225, WY0 + 0.45), T, WTOP, "external", mat,
           "plaster_white_painted", fin_out, note="hipped end of the wing roof: no gable")
    # L0 partitions
    b.wall("DM0_Pa", "L0", (2.525, 0.15), (2.525, 4.30), T_INT, CH, "internal", "brick_partition_150",
           "plaster_white_painted", "tiles_kitchen_splash_1500", note="living | kitchen")
    b.wall("DM0_Pb", "L0", (-1.575, -4.30), (-1.575, -0.15), T_INT, CH, "internal", "brick_partition_150",
           "plaster_white_painted", "plaster_white_painted", note="rear room | hall")
    b.wall("DM0_Pc", "L0", (2.475, -4.30), (2.475, -0.15), T_INT, CH, "internal", "brick_partition_150",
           "plaster_white_painted", "tiles_utility_1500", note="hall | utility (corridor widened to 1.50 m: door piers >= 0.12)")
    b.wall("DM0_Pd", "L0", (0.85, -3.24), (0.85, -0.15), 0.10, CH, "internal", "timber_stud_board_100",
           "plaster_white_painted", "plaster_white_painted", note="closes the under-stair space (east side)")
    b.wall("DM0_Pe", "L0", (-0.40, -3.19), (0.80, -3.19), 0.10, CH, "internal", "timber_stud_board_100",
           "plaster_white_painted", "plaster_white_painted", note="closes the under-stair space (south face below flight 2 top and the well)")
    # L1 partitions
    b.wall("DM1_Pa", "L1", (0.0, 0.15), (0.0, 4.30), T_INT, CH, "internal", "brick_partition_150",
           "plaster_white_painted", "plaster_white_painted", note="bedroom | bedroom")
    b.wall("DM1_Pb", "L1", (-1.575, -4.30), (-1.575, -0.15), T_INT, CH, "internal", "brick_partition_150",
           "plaster_white_painted", "plaster_white_painted", note="child room | landing")
    b.wall("DM1_Pc", "L1", (2.475, -4.30), (2.475, -0.15), T_INT, CH, "internal", "brick_partition_150",
           "plaster_white_painted", "tiles_bath_1800", note="corridor | bathroom")

    def win(oid, wall, c, w=1.20, sill=0.85, head=2.35, glazing="timber_double_casement_transom_white", note=None):
        b.opening(oid, wall, "window", c, w, sill, head, False, glazing=glazing, note=note)

    # ---- L0 external (front = N wall, garden side; runs -X)
    for i, x in enumerate((-3.6, -1.2, 1.2)):
        win(f"DM0_WN{i + 1}", "DM0_N", x)
    win("DM0_WN4", "DM0_N", 3.8, w=1.00, sill=1.00, note="kitchen window above the worktop")
    b.door("DM0_D1", "DM0_S", 1.65, "end", "left", "timber_panel_glazed_green", "timber_green_paint",
           note="main entrance from the rear yard (3 steps, landing + canopy); opens INWARD, the leaf rests along the corridor "
                "wall (review P2-DOOR-SWING-STAIRS)")
    win("DM0_WS1", "DM0_S", -3.4)
    win("DM0_WS2", "DM0_S", 3.6, w=0.90, sill=1.20, head=2.20)
    b.door("DM0_D9", "DM0_W", 2.20, "end", "left", "timber_panel_white", "timber_white_paint",
           note="living room -> wing (former window opening)")
    win("DM0_WW2", "DM0_W", -2.2)
    b.door("DM0_D2", "DM0_E", 1.85, "end", "left", "timber_panel_glazed_green", "timber_green_paint",
           note="kitchen side door to the side yard (3 steps)")
    win("DM0_WE1", "DM0_E", -2.2, w=0.90, sill=1.20, head=2.20)
    # ---- wing
    b.door("DM0_D10", "DM0_WG_N", -8.40, "start", "left", "timber_panel_glazed_green", "timber_green_paint",
           note="wing door to the garden (3 steps + landing), opens inward")
    win("DM0_WN5", "DM0_WG_N", -6.60, w=1.00)
    win("DM0_WW3", "DM0_WG_W", 1.75, w=1.00)
    win("DM0_WS3", "DM0_WG_S", -7.75, w=0.90, sill=1.00, head=2.20)
    # ---- L0 internal
    b.door("DM0_D3", "DM0_SP", 1.65, "start", "left", "timber_panel_white", "timber_white_paint", note="hall corridor -> living room")
    b.door("DM0_D4", "DM0_SP", 4.325, "end", "left", "timber_panel_white", "timber_white_paint", note="utility -> kitchen")
    b.door("DM0_D5", "DM0_SP", -3.70, "start", "left", "timber_panel_white", "timber_white_paint", note="rear room -> living room")
    b.door("DM0_D6", "DM0_Pb", -3.575, "start", "left", "timber_panel_white", "timber_white_paint",
           note="vestibule -> rear room (opens into the rear room)")
    b.door("DM0_D7", "DM0_Pc", -2.30, "start", "right", "timber_panel_white", "timber_white_paint", note="hall corridor -> utility")
    b.door("DM0_D8", "DM0_Pa", 1.20, "start", "right", "timber_panel_white", "timber_white_paint", note="living -> kitchen")
    # ---- L1 external
    for i, x in enumerate((-3.6, -1.2, 1.2, 3.6)):
        win(f"DM1_WN{i + 1}", "DM1_N", x)
    win("DM1_WS2", "DM1_S", -0.40, w=1.00, sill=0.95, note="landing window")
    win("DM1_WS3", "DM1_S", 3.6, w=0.90, sill=1.30, head=2.20)
    win("DM1_WW2", "DM1_W", -2.2)
    win("DM1_WE1", "DM1_E", 2.2)
    win("DM1_WE2", "DM1_E", -2.2, w=0.90, sill=1.30, head=2.20)
    b.door("DM1_D6", "DM1_S", -3.475, "start", "right", "timber_balcony_door_glazed", "timber_white_paint",
           note="child room -> balcony DM_BALK (second way out of the upper floor via the stair DM_S2 down to the rear yard)")
    # ---- L1 internal
    b.door("DM1_D1", "DM1_SP", 1.65, "start", "left", "timber_panel_white", "timber_white_paint", note="corridor -> east bedroom")
    b.door("DM1_D2", "DM1_SP", -3.70, "start", "left", "timber_panel_white", "timber_white_paint", note="child room -> west bedroom")
    b.door("DM1_D3", "DM1_Pa", 3.30, "start", "left", "timber_panel_white", "timber_white_paint", note="east bedroom <-> west bedroom")
    b.door("DM1_D5", "DM1_Pc", -1.00, "end", "right", "timber_panel_white", "timber_white_paint", note="corridor -> bathroom")

    R = FF / 16.0
    stairs = [
        stair_flight("DM_S1a", "L0", "Lmid", (-0.95, -3.14), 0.0, 1.10, R, 0.27, 8, 0.0,
                     landing={"id": "DM_LMID", "level": "Lmid", "polygon": rect(-1.50, -1.25, 0.80, -0.15), "z": 1.50, "depth": 1.10},
                     construction="reinforced_concrete_terrazzo", handrail="left", waist=0.16,
                     under_stair={"treatment": "enclosed", "void": "DM_V0_PODSCHODI", "by": ["DM0_Pd", "DM0_Pe", "DM0_Pb", "DM0_SP"]},
                     note="U-stair flight 1 (west), ascending +Y towards the spine wall"),
        stair_flight("DM_S1b", "Lmid", "L1", (0.25, -1.25), 180.0, 1.10, R, 0.27, 8, 1.50, from_landing="DM_LMID",
                     construction="reinforced_concrete_terrazzo", handrail="left", waist=0.16,
                     under_stair={"treatment": "enclosed", "void": "DM_V0_PODSCHODI", "by": ["DM0_Pd", "DM0_Pe"]},
                     note="U-stair flight 2 (east), ascending -Y to the L1 landing; 0.10 well between the flights"),
    ]
    RB = (FF + 0.54) / 19.0
    ext_stairs = [
        stair_flight("DM_X1", "ground", "L0", (1.65, -6.51), 0.0, 1.50, 0.18, 0.28, 3, -0.54,
                     landing={"id": "DM_X1_LAND", "level": "L0", "polygon": rect(0.90, -5.95, 2.40, -4.75), "z": 0.0},
                     construction="terrazzo_precast_on_solid_base", handrail="left", waist=0.0, foot_ground=-0.54,
                     under_stair={"treatment": "solid_mass"}, note="entrance steps + landing at DM0_D1"),
        stair_flight("DM_X2", "ground", "L0", (7.06, 1.85), 90.0, 1.40, 0.18, 0.28, 3, -0.54,
                     landing={"id": "DM_X2_LAND", "level": "L0", "polygon": rect(5.50, 1.05, 6.50, 2.65), "z": 0.0},
                     construction="concrete_on_solid_base", handrail="none", waist=0.0, foot_ground=-0.54,
                     under_stair={"treatment": "solid_mass"}, note="kitchen side door steps"),
        stair_flight("DM_X3", "ground", "L0", (-8.40, 6.51), 180.0, 1.40, 0.18, 0.28, 3, -0.54,
                     landing={"id": "DM_X3_LAND", "level": "L0", "polygon": rect(-9.10, WY1, -7.70, WY1 + 1.20), "z": 0.0},
                     construction="concrete_on_solid_base", handrail="none", waist=0.0, foot_ground=-0.54,
                     under_stair={"treatment": "solid_mass"}, note="wing door steps from the garden"),
        stair_flight("DM_S2", "ground", "L1", (-2.15, -11.21), 0.0, 1.10, RB, 0.27, 19, -0.54,
                     landing={"id": "DM_BALK", "level": "L1", "polygon": rect(-5.40, -6.35, -1.40, -4.75), "z": FF},
                     construction="masonry_steps_on_solid_rubble_base_with_cheek_walls", handrail="both", waist=0.0, foot_ground=-0.54,
                     under_stair={"treatment": "solid_mass", "note": "solid rubble base with rendered cheek walls: no space below"},
                     note="stair from the rear yard up to the balcony (second independent exit of the upper floor)"),
    ]
    balconies = [
        {"id": "DM_BALK", "level": "L1", "polygon": rect(-5.40, -6.35, -1.40, -4.75), "top_z": FF, "slab_thickness": 0.18,
         "access_door": "DM1_D6", "stair": "DM_S2", "material": "reinforced_concrete_cantilever_terrazzo_top",
         "parapet": {"height": 1.00, "thickness": 0.20, "solid": True, "material": "brick_rendered_cream",
                     "segments": [[[-5.30, -4.75], [-5.30, -6.35]], [[-5.20, -6.25], [-2.70, -6.25]], [[-1.50, -6.35], [-1.50, -4.75]]],
                     "segment_rule": "segments are the parapet centre lines, boxes of `thickness` inside the slab edge",
                     "note": "solid 1.00 m parapet = crouch cover (firing position outside the zone); opening x -2.70..-1.60 for the stair"},
         "drainage": "falls 2 % to a copper spout at the south-west corner",
         "gameplay": "firing position over the rear yard and the S ring approach, outside zone_dvur (z 5.94 > z_max 5.54)"},
    ]
    levels = [
        {"id": "L0", "name": "Přízemí", "floor_z": 0.0, "ceiling_height": CH, "floor_thickness": 0.25,
         "note": "raised ground floor, +0.54 above the terrace (3 steps); the wing has the same floor level"},
        {"id": "L1", "name": "Patro", "floor_z": FF, "ceiling_height": CH, "floor_thickness": 0.25, "extent": rect(-5.05, -4.30, 5.05, 4.30)},
        {"id": "ATTIC", "name": "Půda (nepřístupná)", "floor_z": FF + CH + 0.25, "ceiling_height": 0.0, "floor_thickness": 0.0,
         "note": "closed hatch; not walkable, not in navmesh; the dormer windows light it (read as attic, never as a room)"},
    ]
    ceil0 = {"type": "slab", "slab": "DM_SLAB_L1"}
    rooms = [
        {"id": "DM_R0_OBYVAK", "level": "L0", "name": "Obývací pokoj", "polygon": rect(-5.05, 0.15, 2.45, 4.30),
         "ceiling_height": CH, "ceiling": ceil0, "floor_material": "timber_parquet", "in_zone": True},
        {"id": "DM_R0_KUCHYNE", "level": "L0", "name": "Kuchyně", "polygon": rect(2.60, 0.15, 5.05, 4.30),
         "ceiling_height": CH, "ceiling": ceil0, "floor_material": "ceramic_tiles_red_brown", "in_zone": True},
        {"id": "DM_R0_POKOJ", "level": "L0", "name": "Pokoj (zadní)", "polygon": rect(-5.05, -4.30, -1.65, -0.15),
         "ceiling_height": CH, "ceiling": ceil0, "floor_material": "timber_parquet", "in_zone": True},
        {"id": "DM_R0_CHODBA", "level": "L0", "name": "Zádveří a chodba",
         "polygon": [[-1.50, -4.30], [2.40, -4.30], [2.40, -0.15], [0.90, -0.15], [0.90, -3.24], [-0.40, -3.24],
                     [-0.40, -3.14], [-1.50, -3.14]], "ceiling_height": CH, "ceiling": ceil0, "floor_material": "terrazzo_grey", "in_zone": True},
        {"id": "DM_R0_TECH", "level": "L0", "name": "Technická místnost", "polygon": rect(2.55, -4.30, 5.05, -0.15),
         "ceiling_height": CH, "ceiling": ceil0, "floor_material": "ceramic_tiles_grey", "in_zone": True},
        {"id": "DM_R0_KRIDLO", "level": "L0", "name": "Letní kuchyně (přízemní křídlo)", "polygon": rect(WX0 + 0.45, WY0 + 0.45, -5.5, WY1 - 0.45),
         "ceiling_height": 2.60, "ceiling": {"type": "timber_ceiling_on_joists", "underside": 2.60},
         "floor_material": "ceramic_tiles_red_brown", "in_zone": True},
        {"id": "DM_R1_LOZ_Z", "level": "L1", "name": "Ložnice západ", "polygon": rect(-5.05, 0.15, -0.075, 4.30),
         "ceiling_height": CH, "ceiling": {"type": "timber_joists_plaster"}, "floor_material": "timber_boards", "in_zone": False},
        {"id": "DM_R1_LOZ_V", "level": "L1", "name": "Ložnice východ", "polygon": rect(0.075, 0.15, 5.05, 4.30),
         "ceiling_height": CH, "ceiling": {"type": "timber_joists_plaster"}, "floor_material": "timber_boards", "in_zone": False},
        {"id": "DM_R1_DETSKY", "level": "L1", "name": "Dětský pokoj", "polygon": rect(-5.05, -4.30, -1.65, -0.15),
         "ceiling_height": CH, "ceiling": {"type": "timber_joists_plaster"}, "floor_material": "timber_boards", "in_zone": False},
        {"id": "DM_R1_CHODBA", "level": "L1", "name": "Podesta a chodba",
         "polygon": [[-1.50, -4.30], [2.40, -4.30], [2.40, -0.15], [0.80, -0.15], [0.80, -3.14], [-1.50, -3.14]],
         "ceiling_height": CH, "ceiling": {"type": "timber_joists_plaster"}, "floor_material": "terrazzo_grey", "in_zone": False},
        {"id": "DM_R1_KOUPELNA", "level": "L1", "name": "Koupelna", "polygon": rect(2.55, -4.30, 5.05, -0.15),
         "ceiling_height": CH, "ceiling": {"type": "timber_joists_plaster"}, "floor_material": "ceramic_tiles_white", "in_zone": False,
         "dead_end_ok": "bathroom: single door, only high windows (sill 1.30 m) -- not a firing position, not campable over the zone"},
    ]
    sealed_voids = [
        {"id": "DM_V0_PODSCHODI", "level": "L0",
         "polygon": [[-1.50, -3.14], [-0.40, -3.14], [-0.40, -3.24], [0.80, -3.24], [0.80, -0.15], [-1.50, -0.15]],
         "reason": "space below both U-stair flights and the mid landing, closed by DM0_Pd / DM0_Pe; not walkable, not in navmesh"},
    ]
    slabs = [{"id": "DM_SLAB_L1", "level": "L1", "polygon": rect(-5.05, -4.30, 5.05, 4.30), "thickness": 0.25, "top_z": FF,
              "openings": [{"id": "DM_SO1", "polygon": rect(-1.50, -3.14, 0.80, -0.15), "reason": "U-stair void (both flights + landing)"}]}]
    balustrades = [
        {"id": "DM_BAL1", "level": "L1", "polyline": [[-1.50, -3.14], [-0.30, -3.14]], "height": 1.00, "type": "timber_rail_steel_balusters"},
        {"id": "DM_BAL2", "level": "L1", "polyline": [[0.80, -3.14], [0.80, -0.15]], "height": 1.00, "type": "timber_rail_steel_balusters",
         "note": "on the void edge above partition DM0_Pd"},
        {"id": "DM_BAL3", "level": "Lmid", "polyline": [[-0.35, -3.14], [-0.35, -1.25]], "height": 1.00, "type": "handrail_in_well"},
    ]
    tp40 = math.tan(math.radians(40))
    tp35 = math.tan(math.radians(35))
    roof = [{"id": "RF_DUM", "type": "hip", "pitch_deg": 40.0, "ridge_axis": "X", "wall_rect": rect(-5.5, -4.75, 5.5, 4.75),
             "eave_z": TOP, "ridge_z": r3(TOP + 4.75 * tp40),
             "ridge_from": [-0.75, 0.0], "ridge_to": [0.75, 0.0], "overhang_eave": 0.60, "overhang_verge": None,
             "material": "clay_tile_interlocking_red_orange_weathered", "structure": "timber purlin roof, hips at 45 deg on plan",
             "fascia": "timber_board_0.18_dark_brown", "soffit": "boarded_painted",
             "dormers": [{"id": "DM_DOR1", "slope": "+Y", "center_x": -2.4, "width": 1.30, "front_height": 1.20, "roof": "gable 45 deg, red tiles",
                          "window": {"width": 0.70, "height": 0.80}, "note": "ref. 01: small gabled dormers on the garden slope"},
                         {"id": "DM_DOR2", "slope": "+Y", "center_x": 2.4, "width": 1.30, "front_height": 1.20, "roof": "gable 45 deg, red tiles",
                          "window": {"width": 0.70, "height": 0.80}}]},
            {"id": "RF_DUM_KRIDLO", "type": "hip", "pitch_deg": 35.0, "ridge_axis": "X", "wall_rect": rect(WX0, WY0, -5.5, WY1),
             "eave_z": WTOP, "ridge_z": r3(WTOP + 3.0 * tp35), "overhang_eave": 0.45, "abuts": {"+X": "DM0_W / DM1_W (flashing into the house wall)"},
             "material": "clay_tile_interlocking_red_orange_weathered", "structure": "timber rafters, hipped west end (ref. 01)",
             "fascia": "timber_board_0.18_dark_brown", "soffit": "boarded_painted",
             "note": "the ridge meets the house wall at z 5.00, below the L1 floor + 2.0; no L1 window above it (the former DM1_WW1 was removed)"}]
    rf, rw = roof
    gutters = [gutter(rf, e, f, t, "half_round_125_zinc")
               for e, f, t in (("+Y", [-6.1, 5.35], [6.1, 5.35]), ("-Y", [-6.1, -5.35], [6.1, -5.35]),
                               ("+X", [6.1, -5.35], [6.1, 5.35]), ("-X", [-6.1, -5.35], [-6.1, 5.35]))]
    gutters += [gutter(rw, "+Y", (WX0 - 0.45, WY1 + 0.45), (-5.5, WY1 + 0.45), "half_round_125_zinc"),
                gutter(rw, "-Y", (WX0 - 0.45, WY0 - 0.45), (-5.5, WY0 - 0.45), "half_round_125_zinc"),
                gutter(rw, "-X", (WX0 - 0.45, WY0 - 0.45), (WX0 - 0.45, WY1 + 0.45), "half_round_125_zinc")]
    gz_m, gz_w = gutters[0]["z"], gutters[4]["z"]
    downpipes = [{"id": f"DM_DP{i + 1}", "pos": [sx * 5.62, sy * 4.87], "top_z": gz_m, "dia": 0.10,
                  "outlet": "cast_iron_boot_to_drain_to_RW_DUM_outlet" if sy > 0 else "cast_iron_boot_to_drain_to_soakaway"}
                 for i, (sx, sy) in enumerate(((-1, -1), (1, -1), (-1, 1), (1, 1)))]
    downpipes[2] = {"id": "DM_DP3", "pos": [WX0 - 0.12, WY1 + 0.12], "top_z": gz_w, "dia": 0.10,
                    "outlet": "cast_iron_boot_to_drain_to_RW_DUM_outlet", "note": "wing NW corner; the house NW gutter drains onto the wing roof via a spreader"}
    downpipes.append({"id": "DM_DP5", "pos": [WX0 - 0.12, WY0 - 0.12], "top_z": gz_w, "dia": 0.10, "outlet": "cast_iron_boot_to_drain_to_soakaway"})
    drainage = {"front": "DM_DP3/DP4 boots -> PVC 110 drains under the garden -> two stone spouts in RW_DUM (local x -8.0 and +10.5, "
                         "0.40 m above the square) -> granite gutter along the square -> gully G_NV1 -> culvert to the brook",
                "rear": "DM_DP1/DP2/DP5 -> soakaway under the rear yard; the rear yard gravel falls 1 % away from the house",
                "balcony": "copper spout at the balcony SW corner onto a splash stone"}
    foundation = {"plinth_height_above_floor": 0.0, "plinth_visible_height": 0.54, "plinth_material": "render_cement_grey_plinth",
                  "ground_levels": {"all sides": -0.54}, "floor_to_terrain_rule": "terrace pad flat at house floor - 0.54",
                  "footing": "concrete strip footing (hidden), cellar NOT modelled"}
    exterior_steps = [
        {"id": "DM_X1_CANOPY", "at": "DM0_D1", "type": "canopy", "rect": rect(0.70, -5.95, 2.60, -4.75), "z": 2.55,
         "material": "steel_glass"},
    ]
    furniture = [
        furn("DM_F1", "L0", "sofa", (-3.0, 3.75), (2.2, 0.9, 0.85), 0, "none", blocks_bullets=False, note="soft: concealment only"),
        furn("DM_F2", "L0", "table_dining", (-1.2, 1.8), (1.4, 0.9, 0.75), 0, "low"),
        furn("DM_F3", "L0", "wall_unit_cabinet", (-0.9, 0.45), (2.4, 0.5, 2.00), 0, "high",
             note="against the spine wall (review P2-WINDOW-FURNITURE: no longer in front of a window)"),
        furn("DM_F4", "L0", "kitchen_units", (3.85, 4.0), (2.3, 0.6, 0.90), 0, "low"),
        furn("DM_F5", "L0", "kitchen_table", (3.3, 2.9), (1.0, 0.8, 0.75), 0, "low"),
        furn("DM_F6", "L0", "wardrobe", (-1.95, -2.0), (0.6, 1.6, 2.00), 0, "none", blocks_bullets=False, note="soft: concealment only"),
        furn("DM_F7", "L0", "bed_single", (-4.0, -3.55), (1.0, 2.0, 0.55), 90, "none", blocks_bullets=False),
        furn("DM_F8", "L0", "boiler_washing_machine", (4.65, -3.6), (0.7, 1.3, 1.80), 0, "high"),
        furn("DM_F9", "L1", "bed_double", (-3.0, 3.0), (1.8, 2.0, 0.55), 0, "none", blocks_bullets=False),
        furn("DM_F10", "L1", "wardrobe", (-4.75, 1.3), (0.6, 2.0, 2.10), 0, "none", blocks_bullets=False,
             note="against the solid west wall (the L1 west window above the wing roof was removed)"),
        furn("DM_F11", "L1", "bed_double", (3.0, 3.0), (1.8, 2.0, 0.55), 0, "none", blocks_bullets=False),
        furn("DM_F12", "L1", "chest_of_drawers", (4.75, 0.9), (0.5, 1.2, 1.00), 0, "low"),
        furn("DM_F13", "L1", "bed_single", (-2.25, -2.0), (1.0, 2.0, 0.55), 0, "none", blocks_bullets=False),
        furn("DM_F14", "L1", "bathtub", (4.25, -3.6), (1.6, 0.75, 0.60), 0, "low"),
        furn("DM_F15", "L0", "kitchen_stove_solid_fuel", (-9.15, 2.75), (0.8, 0.6, 0.90), 0, "low", note="serves chimney DM_CH2"),
        furn("DM_F16", "L0", "table_kitchen", (-7.6, 1.2), (1.2, 0.8, 0.75), 0, "low"),
        furn("DM_F17", "L0", "cupboard_dresser", (-6.3, -0.55), (1.6, 0.5, 1.90), 0, "high"),
    ]
    return finalize({
        "id": "B_DUM", "type": "obytny_dum", "name": "Obytný dům (dům mistra)", "enterable": True,
        "story": "Zděný dvoupodlažní dům z roku 1934 s valbovou střechou z červených pálených tašek, dvěma vikýři a přízemním "
                 "křídlem letní kuchyně (reference 01), postavený pro mistra hamru na terase nad návsí. Zahrada je obehnaná "
                 "omítnutou zdí s pilíři; k návsi ji drží pískovcová opěrná zeď se zapuštěnou garáží a schody. Vstup je ze dvora, "
                 "kuchyňské dveře do bočního dvorku, balkon nad dvorem má schody dolů na dvůr.",
        "reference": "Docs/navrhy/01_letecky_pohled_vesnice.png (house in the walled garden, south part of the image)",
        "local_origin": "centre of the two-storey main block X[-5.5,5.5] x Y[-4.75,4.75] at finished L0 floor (z 0.00); the "
                        "one-storey wing extends to X -10.0; +Y = street / garden facade (towards the village square)",
        "footprint_external": [15.5, 9.5],
        "footprint_parts": [{"part": "house", "external_rect": rect(-5.5, -4.75, 5.5, 4.75), "interior_rect": rect(-5.05, -4.30, 5.05, 4.30),
                             "walls": {"x": [0.45, 0.45], "y": [0.45, 0.45]},
                             "check": "11.00 = 0.45 + 10.10 + 0.45; 9.50 = 0.45 + 8.60 + 0.45"},
                            {"part": "wing", "external_rect": rect(WX0, WY0, -5.5, WY1), "interior_rect": rect(WX0 + 0.45, WY0 + 0.45, -5.5, WY1 - 0.45),
                             "walls": {"x": [0.45, 0.0], "y": [0.45, 0.45]},
                             "check": "4.50 = 0.45 + 4.05 + 0 (house wall counted in the house); 6.00 = 0.45 + 5.10 + 0.45"}],
        "structure": "brick masonry 450 external, 300 spine wall, 150 partitions; reinforced concrete slab over L0, timber joists over "
                     "L1; one-storey wing with timber ceiling joists",
        "levels": levels, "rooms": rooms, "sealed_voids": sealed_voids, "walls": b.walls, "openings": b.openings, "slabs": slabs,
        "stairs": stairs, "exterior_stairs": ext_stairs, "balustrades": balustrades, "balconies": balconies, "roof": roof,
        "gutters": gutters, "downpipes": downpipes, "drainage": drainage, "foundation": foundation, "exterior_steps": exterior_steps,
        "chimneys": [{"id": "DM_CH1", "type": "brick", "pos": [3.0, 0.0], "size": [0.60, 0.60], "base_z": 0.0, "top_z": 10.30,
                      "serves": "DM_F8",
                      "note": "kitchen/boiler flue in the spine wall (0.15 proud into kitchen, utility, east bedroom, bathroom), "
                              "0.2 m above the ridge"},
                     {"id": "DM_CH2", "type": "brick", "pos": [-9.78, 2.75], "size": [0.45, 0.50], "base_z": 0.0,
                      "top_z": r3(WTOP + 1.45 * tp35 + 1.0), "serves": "DM_F15", "note": "summer-kitchen stove chimney in the wing west wall"}],
        "furniture": furniture,
        "fixtures": [{"id": "DM_S1", "type": "house_number_plate", "wall": "DM0_S", "pos": [0.6, -4.75], "z": 2.10, "text_cs": "čp. 3"}],
        "zone_notes": "zone_dvur counts the terrace garden, the side yard strips, the ground floor with the wing and the entrance "
                      "strip behind the house (landing DM_X1); the upper floor and the balcony (z +3.00, 0.40 m above z_max) are "
                      "outside, the rear yard beyond local y -6.0 is outside",
    })


def all_buildings():
    return [dilna(), sklad(), dum()]
