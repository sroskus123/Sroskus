"""
ivbuildings -- authoring source for Shared/level/buildings.json (IRON VALLEY, map "Kalné Hamry").

Building-local frame: metres, Z up.  Origin = centre of the external footprint (outer faces of the
external walls) at finished ground-floor level (top of the L0 floor finish = 0.00).  Local +Y = FRONT
facade (rotation_deg 0 in layout.json means local +Y points north).  Local +X = to the right of an
observer standing inside looking out of the front.  World = rotate local by layout rotation_deg
(counter-clockwise about +Z) and translate by layout position [x, y, z_floor].
Axis conversions (same as layout.json): three.js (x, y, z)_three = (x, z, -y)_blender; Unreal (cm) =
(100 x, -100 y, 100 z) with FBX 'Y forward, Z up' export (UE import NOT TESTED).

Walls (exact, no implicit extension):
  * a wall is a box: centre line from `start` to `end` (exact box ends), `thickness` centred on the line,
    from z = level.floor_z + base_z to + height.
  * walls running along X run through the corners; walls along Y stop at the inner faces of the X-walls;
    internal walls stop at the faces of the walls they meet.  Boxes never overlap.
  * external walls are listed counter-clockwise (seen from above), so their LEFT normal (-dy, dx) points
    INTO the building.  `finish_left` / `finish_right` = finish on the left / right face.
  * `gable_above: true` -> the generator adds the gable prism above `height` up to roof `gable_roof`.
  * `construction_boxes` (derived, authoritative for the generator, no booleans): the wall split into
    full-height piers, sill blocks and lintel blocks; each box = {part, u:[u0,u1] along the wall from
    `start`, z:[z0,z1] above the level floor}.  Union of boxes = wall box minus openings.
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
  * roller doors: guide rails 0.05 m each side -> clear_width = width - 0.10; clear_height =
    state.open_height - 0.05 (bottom rail).  open_height < 2.10 is never used on a walkable opening.
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
Rooms have polygon, ceiling_height (clear), floor_material.  `sealed_voids` = closed, unreachable spaces
(under-stair stores) that are neither rooms nor walkable.  Furniture: box {center, size [x, y, z],
rotation_deg}, cover low/high/none, blocks bullets/vision (soft furniture = concealment only).
"""
import math

T_EXT_MASONRY = 0.45
T_INT = 0.15
FRAME_JAMB = 0.05
FRAME_HEAD = 0.05
DOOR_W = 1.25          # structural width of every single-leaf door -> 1.10 clear
DOOR_HEAD = 2.30       # structural head -> 2.25 clear
LEAF_T = 0.05


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

    def opening(self, oid, wall_id, typ, center, width, sill, head, has_leaf, hinge=None, swing=None,
                open_deg=None, leaf=None, glazing=None, state=None, note=None, passes=None):
        """`center` = local coordinate of the opening centre along the wall axis (x for walls
        along X, y for walls along Y)."""
        w = self._w[wall_id]
        (sx, sy), (ex, ey) = w["start"], w["end"]
        if abs(ey - sy) < 1e-9:  # along X
            d = 1.0 if ex > sx else -1.0
            near = center - d * width / 2.0
            off = (near - sx) * d
        else:
            d = 1.0 if ey > sy else -1.0
            near = center - d * width / 2.0
            off = (near - sy) * d
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
        elif typ == "vent":
            o["passes"] = {"movement": False, "bullets": False, "vision": False}
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
                 under_stair=None, from_landing=None, note=None):
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
    # openings entirely above the wall top sit in the gable prism (louvred inserts, not holes)
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
        below = None
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


def finalize(bd):
    for w in bd["walls"]:
        w["length"] = r3(math.hypot(w["end"][0] - w["start"][0], w["end"][1] - w["start"][1]))
        w["construction_boxes"] = construction_boxes(w, bd["openings"])
    return bd


# ================================================================================================
# 1) DÍLNA -- workshop on the old hammer-mill site (1920s masonry hall + 2-storey annex)
# ================================================================================================
def dilna():
    b = B("B_DILNA")
    T = T_EXT_MASONRY
    # footprint: X[-11.5, 11.5] x Y[-5.0, 5.0]; hall X[-11.5, 4.05], annex X[4.05, 11.5]
    HALL_TOP = 4.60      # wall plate of the hall (above L0 floor)
    FF = 3.00            # annex L0 -> L1 floor-to-floor
    ANX_L1_H = 3.15      # annex L1 walls: 3.00 -> wall plate 6.15
    SOFFIT = FF - 0.25   # underside of the L1 slab
    mat_ext = "brick_masonry_450"
    fin_in_hall = "plaster_lime_white_over_green_oil_dado_1500"
    fin_out = "render_lime_offwhite_weathered"
    # --- hall (L0), no east wall (the annex fire wall is shared)
    b.wall("DL_H_S", "L0", (-11.5, -4.775), (4.05, -4.775), T, HALL_TOP, "external", mat_ext, fin_in_hall, fin_out)
    b.wall("DL_H_N", "L0", (4.05, 4.775), (-11.5, 4.775), T, HALL_TOP, "external", mat_ext, fin_in_hall, fin_out)
    b.wall("DL_H_W", "L0", (-11.275, 4.55), (-11.275, -4.55), T, HALL_TOP, "external", mat_ext, fin_in_hall, fin_out,
           gable_above=True, gable_roof="RF_HALA")
    fin_in_anx = "plaster_lime_white"
    for lv, h in (("L0", FF), ("L1", ANX_L1_H)):
        b.wall(f"DL_A{lv[1]}_S", lv, (4.05, -4.775), (11.5, -4.775), T, h, "external", mat_ext, fin_in_anx, fin_out)
        b.wall(f"DL_A{lv[1]}_E", lv, (11.275, -4.55), (11.275, 4.55), T, h, "external", mat_ext, fin_in_anx, fin_out,
               gable_above=(lv == "L1"), gable_roof="RF_PRISTAVEK" if lv == "L1" else None)
        b.wall(f"DL_A{lv[1]}_N", lv, (11.5, 4.775), (4.05, 4.775), T, h, "external", mat_ext, fin_in_anx, fin_out)
        b.wall(f"DL_A{lv[1]}_W", lv, (4.275, 4.55), (4.275, -4.55), T, h, "internal", mat_ext,
               fin_in_anx, fin_in_hall if lv == "L0" else "render_lime_offwhite_weathered",
               gable_above=(lv == "L1"), gable_roof="RF_PRISTAVEK" if lv == "L1" else None,
               note="former gable of the hammer mill, 0.45 masonry fire wall; above the hall roof it is an exterior face")
    # partitions in the annex
    b.wall("DL_P0_1", "L0", (4.50, -2.10), (11.05, -2.10), T_INT, SOFFIT, "internal", "brick_partition_150",
           "plaster_lime_white", "plaster_lime_white", note="corridor | tool room")
    b.wall("DL_P0_2", "L0", (5.70, -3.40), (11.05, -3.40), 0.10, SOFFIT, "internal", "timber_stud_board_100",
           "painted_board_grey", "painted_board_grey",
           note="closed spandrel along the stair flight (under-stair store DL_V0_PODSCHODI, no door, not walkable)")
    b.wall("DL_P1_1", "L1", (4.50, -2.10), (11.05, -2.10), T_INT, 2.80, "internal", "brick_partition_150",
           "plaster_lime_white", "plaster_lime_white", note="corridor | foreman office")

    # --- openings, hall (L0)
    b.opening("DL_G1", "DL_H_N", "double_door", -5.5, 3.40, 0.0, 3.60, True, hinge="both", swing="right",
              open_deg=100, leaf={"type": "timber_ledged_braced_pair", "thickness": 0.06, "material": "timber_green_paint_worn"},
              note="main gate; both leaves open outward to 100 deg against facade stops")
    b.opening("DL_W1", "DL_H_N", "window", 1.0, 1.80, 1.20, 3.00, False, glazing="steel_industrial_small_panes")
    b.opening("DL_W2", "DL_H_N", "window", -9.4, 1.80, 1.20, 3.00, False, glazing="steel_industrial_small_panes")
    b.door("DL_D2", "DL_H_S", -2.05, "start", "right", "steel_sheet", "steel_grey_paint_worn",
           note="rear door to the rear pad, opens outward")
    for i, x in enumerate((-8.0, -5.0, 1.5)):
        b.opening(f"DL_W{3 + i}", "DL_H_S", "window", x, 1.80, 1.40, 3.00, False, glazing="steel_industrial_small_panes")
    b.door("DL_D3", "DL_H_W", 0.70, "end", "left", "timber_ledged", "timber_green_paint_worn",
           note="gable side door (brook-side path), opens inward")
    b.opening("DL_W6", "DL_H_W", "window", -2.4, 1.60, 1.20, 2.80, False, glazing="steel_industrial_small_panes")
    b.opening("DL_V1", "DL_H_W", "vent", 0.0, 0.80, 5.20, 5.80, False, note="louvred gable vent (not passable)")
    # fire wall L0
    b.door("DL_D4", "DL_A0_W", -3.825, "end", "left", "timber_flush", "timber_cream_paint",
           note="hall -> stair bay, straight onto the flight; leaf rests along the rear wall in the bay")
    b.door("DL_D5", "DL_A0_W", 0.625, "start", "left", "timber_flush", "timber_cream_paint", note="hall -> tool room")
    # annex L0 external
    b.door("DL_D6", "DL_A0_E", 3.225, "end", "right", "steel_sheet", "steel_grey_paint_worn",
           note="annex gable door into the tool room, opens outward")
    b.opening("DL_W7", "DL_A0_E", "window", 0.5, 1.20, 0.90, 2.30, False, glazing="timber_double_casement")
    b.door("DL_D7", "DL_A0_N", 7.80, "end", "left", "timber_half_glazed", "timber_green_paint_worn",
           note="tool room / issue office entrance from the yard")
    b.opening("DL_W8", "DL_A0_N", "window", 6.0, 1.20, 0.90, 2.30, False, glazing="timber_double_casement")
    b.opening("DL_W9", "DL_A0_N", "window", 9.6, 1.20, 0.90, 2.30, False, glazing="timber_double_casement")
    b.door("DL_D8", "DL_P0_1", 10.225, "start", "left", "timber_flush", "timber_cream_paint", note="corridor -> tool room")
    # annex L1
    b.opening("DL_W10", "DL_A1_N", "window", 6.0, 1.20, 0.90, 2.35, False, glazing="timber_double_casement")
    b.opening("DL_W11", "DL_A1_N", "window", 9.6, 1.20, 0.90, 2.35, False, glazing="timber_double_casement")
    b.opening("DL_W12", "DL_A1_E", "window", 1.5, 1.20, 0.90, 2.35, False, glazing="timber_double_casement")
    b.opening("DL_W13", "DL_A1_S", "window", 7.6, 1.00, 1.20, 2.35, False, glazing="timber_double_casement",
              note="stair window above the flight (not reachable, over the void)")
    b.door("DL_D9", "DL_A1_S", 10.375, "end", "right", "steel_sheet", "steel_grey_paint_worn",
           note="upper landing -> external steel stair platform (second way out of the upper floor)")
    b.door("DL_D10", "DL_P1_1", 5.325, "start", "left", "timber_flush", "timber_cream_paint", note="corridor -> foreman office (west)")
    b.door("DL_D11", "DL_P1_1", 10.225, "end", "left", "timber_flush", "timber_cream_paint",
           note="second office door at the landing end: the office is never a single-door trap")
    b.opening("DL_WI1", "DL_A1_W", "window", 2.6, 1.20, 0.95, 2.10, False, glazing="internal_single_glazed_steel_frame",
              note="internal window: foreman office overlooks the hall (office floor +3.00 above the hall floor)")
    b.opening("DL_WI2", "DL_A1_W", "window", 0.2, 1.20, 0.95, 2.10, False, glazing="internal_single_glazed_steel_frame",
              note="internal window: foreman office overlooks the hall")

    riser = FF / 16.0
    stairs = [
        stair_flight("DL_S1", "L0", "L1", (5.70, -4.00), 270.0, 1.10, riser, 0.27, 16, 0.0,
                     landing={"id": "DL_LAND_L1", "level": "L1", "polygon": rect(9.75, -4.55, 11.05, -3.45), "z": FF},
                     construction="reinforced_concrete_slab_stair_terrazzo_treads", handrail="left", waist=0.18,
                     under_stair={"treatment": "enclosed", "void": "DL_V0_PODSCHODI",
                                  "by": ["DL_P0_2", "DL_A0_S", "DL_A0_E", "flight soffit meets the floor at the first riser"]},
                     note="straight flight along the rear wall, bottom approach bay 1.20 m (x 4.50..5.70) reached straight "
                          "through DL_D4 from the hall or from the corridor; rear wall on the right, spandrel + handrail on the left"),
    ]
    ext_rise = FF + 0.17
    ext_riser = ext_rise / 17.0
    ext_stairs = [
        dict(stair_flight("DL_ES1", "ground", "L1", (5.28, -5.65), 270.0, 1.10, ext_riser, 0.27, 17, -0.17,
                          landing={"id": "DL_PLATFORM", "level": "L1", "polygon": rect(9.60, -6.25, 11.50, -5.00), "z": FF,
                                   "thickness": 0.10, "surface": "galvanised_grating"},
                          construction="galvanised_steel_grating_on_steel_stringers", handrail="both", waist=0.25,
                          under_stair={"treatment": "filled", "by": ["DL_F17"],
                                       "note": "firewood stack below the flight up to x 8.45 where the soffit reaches 2.10 m "
                                               "above the rear pad; beyond it and under the platform headroom >= 2.10"},
                          note="external steel stair along the rear facade rising towards +X to the platform at door DL_D9"),
             side="rear_exterior"),
    ]
    levels = [
        {"id": "L0", "name": "Přízemí (dílna + přístavek)", "floor_z": 0.0, "ceiling_height": SOFFIT,
         "floor_thickness": 0.15, "note": "hall has no ceiling: tie beams at z 4.20 (clear), roof above; annex slab soffit 2.75; "
                                          "slab-on-grade 0.15 + stone plinth"},
        {"id": "L1", "name": "Patro přístavku", "floor_z": FF, "ceiling_height": 2.80, "floor_thickness": 0.25,
         "extent": rect(4.50, -4.55, 11.05, 4.55)},
    ]
    rooms = [
        {"id": "DL_R_HALA", "level": "L0", "name": "Dílna (hala)", "polygon": rect(-11.05, -4.55, 4.05, 4.55),
         "ceiling_height": 4.20, "floor_material": "concrete_oil_stained", "in_zone": True},
        {"id": "DL_R_CHODBA0", "level": "L0", "name": "Schodišťový kout a chodba",
         "polygon": [[4.50, -4.55], [5.70, -4.55], [5.70, -3.35], [11.05, -3.35], [11.05, -2.175], [4.50, -2.175]],
         "ceiling_height": SOFFIT, "floor_material": "terrazzo_grey", "in_zone": False,
         "note": "bottom approach bay 1.20 x 1.10 m in front of the first riser + corridor 1.175 m to the tool room"},
        {"id": "DL_R_VYDEJNA", "level": "L0", "name": "Výdejna nářadí", "polygon": rect(4.50, -2.025, 11.05, 4.55),
         "ceiling_height": SOFFIT, "floor_material": "vinyl_tiles_beige", "in_zone": True},
        {"id": "DL_R_CHODBA1", "level": "L1", "name": "Chodba patra s podestou",
         "polygon": [[4.50, -4.55], [5.70, -4.55], [5.70, -3.45], [9.75, -3.45], [9.75, -4.55], [11.05, -4.55],
                     [11.05, -2.175], [4.50, -2.175]], "ceiling_height": 2.80, "floor_material": "timber_boards", "in_zone": False},
        {"id": "DL_R_KANCELAR", "level": "L1", "name": "Kancelář mistra", "polygon": rect(4.50, -2.025, 11.05, 4.55),
         "ceiling_height": 2.80, "floor_material": "vinyl_tiles_beige", "in_zone": False,
         "note": "two doors to the corridor, two internal windows over the hall; outside zone_dilna (z_max)"},
    ]
    sealed_voids = [
        {"id": "DL_V0_PODSCHODI", "level": "L0", "polygon": rect(5.70, -4.55, 11.05, -3.45),
         "reason": "space below flight DL_S1 and its top landing, closed by spandrel DL_P0_2; no door, not walkable, not in navmesh"},
    ]
    slabs = [
        {"level": "L1", "polygon": rect(4.50, -4.55, 11.05, 4.55), "thickness": 0.25, "top_z": FF,
         "openings": [{"id": "DL_SO1", "polygon": rect(5.70, -4.55, 9.75, -3.45), "reason": "stair DL_S1 void"}]},
    ]
    balustrades = [
        {"id": "DL_BAL1", "level": "L1", "polyline": [[5.70, -3.45], [9.75, -3.45]], "height": 1.00, "type": "steel_flat_bar_infill"},
        {"id": "DL_BAL2", "level": "L1", "polyline": [[5.70, -4.55], [5.70, -3.45]], "height": 1.00, "type": "steel_flat_bar_infill"},
        {"id": "DL_BAL3", "level": "exterior", "polyline": [[9.60, -6.25], [11.50, -6.25], [11.50, -5.00]], "height": 1.10,
         "z": FF, "type": "galvanised_steel_rail", "note": "platform guard; flight side guards follow DL_ES1"},
    ]
    roof = [
        {"id": "RF_HALA", "type": "gable", "pitch_deg": 30.0, "ridge_axis": "X", "wall_rect": rect(-11.5, -5.0, 4.05, 5.0),
         "eave_z": HALL_TOP, "ridge_z": r3(HALL_TOP + 5.0 * math.tan(math.radians(30))), "overhang_eave": 0.50,
         "overhang_verge": {"-X": 0.30, "+X": 0.0}, "abuts": {"+X": "DL_A1_W (annex fire wall rises above, lead flashing)"},
         "material": "fibre_cement_corrugated_grey", "structure": "timber king-post trusses at 3.0 m, tie beams underside z 4.20",
         "fascia": "timber_board_0.20_brown", "soffit": "open rafters"},
        {"id": "RF_PRISTAVEK", "type": "gable", "pitch_deg": 35.0, "ridge_axis": "X", "wall_rect": rect(4.05, -5.0, 11.5, 5.0),
         "eave_z": FF + ANX_L1_H, "ridge_z": r3(FF + ANX_L1_H + 5.0 * math.tan(math.radians(35))), "overhang_eave": 0.50,
         "overhang_verge": {"-X": 0.20, "+X": 0.30}, "material": "clay_tile_beaver_tail_red_weathered",
         "structure": "timber purlin roof, ceiling joists over L1 at z 5.80-6.15 (attic not accessible)",
         "fascia": "timber_board_0.20_brown", "soffit": "boarded"},
    ]
    gutters = [
        {"roof": "RF_HALA", "edge": "+Y", "from": [-11.8, 5.5], "to": [4.05, 5.5], "z": HALL_TOP - 0.05, "profile": "half_round_125_galv"},
        {"roof": "RF_HALA", "edge": "-Y", "from": [-11.8, -5.5], "to": [4.05, -5.5], "z": HALL_TOP - 0.05, "profile": "half_round_125_galv"},
        {"roof": "RF_PRISTAVEK", "edge": "+Y", "from": [4.05, 5.5], "to": [11.8, 5.5], "z": FF + ANX_L1_H - 0.05, "profile": "half_round_125_zinc"},
        {"roof": "RF_PRISTAVEK", "edge": "-Y", "from": [4.05, -5.5], "to": [11.8, -5.5], "z": FF + ANX_L1_H - 0.05, "profile": "half_round_125_zinc"},
    ]
    downpipes = [
        {"id": "DL_DP1", "pos": [-11.2, 5.12], "top_z": HALL_TOP - 0.05, "dia": 0.10, "outlet": "splash_block_to_yard_channel"},
        {"id": "DL_DP2", "pos": [3.75, 5.12], "top_z": HALL_TOP - 0.05, "dia": 0.10, "outlet": "splash_block_to_yard_channel"},
        {"id": "DL_DP3", "pos": [-11.2, -5.12], "top_z": HALL_TOP - 0.05, "dia": 0.10, "outlet": "rear_pad_channel"},
        {"id": "DL_DP4", "pos": [3.75, -5.12], "top_z": HALL_TOP - 0.05, "dia": 0.10, "outlet": "rear_pad_channel"},
        {"id": "DL_DP5", "pos": [11.2, 5.12], "top_z": FF + ANX_L1_H - 0.05, "dia": 0.10, "outlet": "gully_G_DL1"},
        {"id": "DL_DP6", "pos": [11.62, -4.60], "top_z": FF + ANX_L1_H - 0.05, "dia": 0.10, "outlet": "old_tailrace_to_brook",
         "note": "on the east gable face, clear of the stair platform"},
    ]
    drainage = {"yard": "gravel yard falls 1 % towards the brook; a concrete dish channel along the gate side collects DL_DP1/DP2 "
                        "and the hall gate apron and discharges through the yard low wall into the brook",
                "rear_pad": "stone-lined drain channel at the foot of RW_DILNA collects the weep holes (every 2.0 m, 0.30 m above the "
                            "pad) and DL_DP3/DP4, runs NE to the old tailrace beside the annex and into the brook",
                "gullies": [{"id": "G_DL1", "pos": [11.9, 5.6], "type": "cast_iron_gully_300"}]}
    foundation = {"plinth_height_above_floor": 0.45, "plinth_material": "stone_greywacke_rubble_plinth",
                  "ground_levels": {"front_yard": -0.17, "rear_pad": -0.17, "gable_-X": -0.17, "gable_+X": -0.17},
                  "footing": "stone strip footing 0.60 wide, 0.80 deep (hidden)",
                  "floor_to_terrain_rule": "terrain pad around the building is flat at floor - 0.17 on all sides (one riser)"}
    exterior_steps = [
        {"id": "DL_X1", "at": "DL_G1", "type": "ramp", "polygon": rect(-7.2, 5.0, -3.8, 6.5), "z_top": 0.0, "z_bottom": -0.17,
         "slope_pct": r3(17.0 / 1.5), "material": "concrete_broom"},
        {"id": "DL_X2", "at": "DL_D7", "type": "step", "polygon": rect(7.10, 5.0, 8.50, 5.35), "risers": 1, "riser": 0.17,
         "material": "concrete"},
        {"id": "DL_X3", "at": "DL_D3", "type": "step", "polygon": rect(-11.85, 0.0, -11.5, 1.40), "risers": 1, "riser": 0.17,
         "material": "stone_slab"},
        {"id": "DL_X4", "at": "DL_D6", "type": "step", "polygon": rect(11.5, 2.55, 11.85, 3.90), "risers": 1, "riser": 0.17,
         "material": "concrete"},
        {"id": "DL_X5", "at": "DL_D2", "type": "step", "polygon": rect(-2.75, -5.35, -1.35, -5.0), "risers": 1, "riser": 0.17,
         "material": "concrete"},
    ]
    furniture = [
        furn("DL_F1", "L0", "tractor_dismantled", (-5.5, 0.6), (3.8, 1.9, 2.4), 0, "high",
             note="old tractor on blocks, wheels off -- the hall's central hard cover"),
        furn("DL_F2", "L0", "lathe", (1.3, -3.35), (2.6, 1.0, 1.40), 0, "low"),
        furn("DL_F3", "L0", "lathe", (-8.4, -3.35), (2.6, 1.0, 1.40), 0, "low"),
        furn("DL_F4", "L0", "milling_machine", (2.4, 2.9), (1.6, 1.4, 2.10), 0, "high"),
        furn("DL_F5", "L0", "workbench", (-10.45, -1.6), (0.8, 2.6, 0.95), 0, "low"),
        furn("DL_F6", "L0", "profile_rack_steel", (-2.3, 1.6), (0.8, 4.0, 2.40), 0, "high",
             note="steel profile rack as a room divider: splits the hall into two lanes"),
        furn("DL_F7", "L0", "oil_drums_x4", (-3.6, -3.9), (1.2, 1.2, 0.90), 0, "low"),
        furn("DL_F8", "L0", "pallet_stack", (-10.35, -4.0), (1.2, 1.0, 1.10), 0, "low"),
        furn("DL_F9", "L0", "welding_cart", (0.6, -0.9), (0.8, 0.6, 1.00), 0, "low"),
        furn("DL_F10", "L0", "compressor", (-10.25, 3.85), (1.4, 0.7, 1.10), 0, "low"),
        furn("DL_F11", "L0", "lockers_row", (6.3, -1.70), (2.6, 0.5, 1.90), 0, "high"),
        furn("DL_F12", "L0", "desk_steel", (8.2, 0.6), (1.6, 0.8, 0.75), 0, "low"),
        furn("DL_F13", "L0", "tool_shelving", (10.8, -0.20), (0.5, 1.6, 2.00), 0, "high"),
        furn("DL_F14", "L1", "desk_timber", (7.6, 1.8), (1.6, 0.8, 0.75), 0, "low"),
        furn("DL_F15", "L1", "filing_cabinets", (4.8, 1.0), (0.5, 2.0, 1.40), 0, "low"),
        furn("DL_F16", "L1", "sofa_old", (9.6, 4.05), (2.0, 0.9, 0.85), 0, "none", blocks_bullets=False,
             note="soft furniture: concealment only"),
        furn("DL_F17", "exterior", "firewood_under_stair", (6.865, -5.65), (3.17, 1.10, 1.95), 0, "high",
             shape="wedge_under_soffit",
             note="fills the space below DL_ES1 from its foot to x 8.45 (collision); top follows the stair soffit - 0.02"),
    ]
    return finalize({
        "id": "B_DILNA", "type": "dilna", "name": "Dílna (bývalý hamr)", "enterable": True,
        "story": "Hamr na Kalném potoce stál na tomto místě od 18. století; náhon od jezu pod štěrkovnou přiváděl vodu na kolo "
                 "u štítu přístavku. Kolem roku 1924 rodina Kalinů přestavěla hamr na cihlovou zámečnickou dílnu, v 60. letech "
                 "se z ní stala opravna zemědělských strojů. Hala bez stropu s krovem, dvoupodlažní přístavek s výdejnou "
                 "nářadí a kanceláří mistra, který vnitřními okny dohlíží do haly.",
        "local_origin": "centre of the external footprint X[-11.5,11.5] x Y[-5.0,5.0] at finished L0 floor (z 0.00); +Y = front (yard)",
        "footprint_external": [23.0, 10.0],
        "footprint_parts": [
            {"part": "hall", "external_rect": rect(-11.5, -5.0, 4.05, 5.0), "interior_rect": rect(-11.05, -4.55, 4.05, 4.55),
             "walls": {"x": [0.45, 0.0], "y": [0.45, 0.45]},
             "check": "15.55 = 0.45 + 15.10 (the 0.45 fire wall is counted in the annex); 10.00 = 0.45 + 9.10 + 0.45"},
            {"part": "annex", "external_rect": rect(4.05, -5.0, 11.5, 5.0), "interior_rect": rect(4.50, -4.55, 11.05, 4.55),
             "walls": {"x": [0.45, 0.45], "y": [0.45, 0.45]},
             "check": "7.45 = 0.45 (fire wall) + 6.55 + 0.45; 10.00 = 0.45 + 9.10 + 0.45"},
        ],
        "structure": "load-bearing brick masonry 450 (external + former gable = fire wall), 150 brick partitions; timber roofs",
        "levels": levels, "rooms": rooms, "sealed_voids": sealed_voids, "walls": b.walls, "openings": b.openings,
        "slabs": slabs, "stairs": stairs, "exterior_stairs": ext_stairs, "balustrades": balustrades, "balconies": [],
        "roof": roof, "gutters": gutters, "downpipes": downpipes, "drainage": drainage, "foundation": foundation,
        "exterior_steps": exterior_steps,
        "chimneys": [{"id": "DL_CH1", "type": "steel_flue", "pos": [-9.5, -5.25], "size": [0.20, 0.20], "top_z": 8.0,
                      "note": "stove flue on the rear facade of the hall, 0.25 m off the wall"}],
        "furniture": furniture,
        "zone_notes": "zone_dilna counts the hall floor, the tool room and the yard; the stair bay/corridor strip and the whole "
                      "upper floor (z >= +3.00, 0.50 m above z_max) are outside the capture polygon",
    })


# ================================================================================================
# 2) SKLAD -- small co-op warehouse (steel portal frame, sandwich cladding, raised floor + loading dock)
# ================================================================================================
def sklad():
    b = B("B_SKLAD")
    T = 0.25
    H = 6.00
    mat = "steel_frame_sandwich_cladding_250"
    fin_in = "sandwich_panel_liner_white"
    fin_out = "sandwich_panel_ribbed_greygreen_over_concrete_plinth_1000"
    b.ext_rect("SK", "L0", -12.25, -7.75, 12.25, 7.75, T, H, mat, fin_in, fin_out, gables=("E", "W"),
               gable_roof="RF_SKLAD")
    b.wall("SK_P1", "L0", (-12.0, 2.275), (-8.0, 2.275), T_INT, 3.00, "internal", "block_partition_150",
           "plaster_white", "plaster_white", note="office | hall (along X)")
    b.wall("SK_P2", "L0", (-8.075, 2.35), (-8.075, 7.50), T_INT, 3.00, "internal", "block_partition_150",
           "plaster_white", "plaster_white", note="office | hall (along Y)")
    # openings sit inside the 6.0 m column bays (columns at x = -12, -6, 0, +6, +12)
    b.opening("SK_RD1", "SK_N", "roller_door", -3.0, 4.00, 0.0, 4.20, True, state={"open_height": 4.20},
              note="bay -6..0, fully open (curtain rolled up)")
    b.opening("SK_RD2", "SK_N", "roller_door", 9.0, 4.00, 0.0, 4.20, True, state={"open_height": 0.0},
              note="bay +6..+12, closed and padlocked (solid collision, blocks bullets); baked as wall in the navmesh")
    b.door("SK_D1", "SK_N", 1.35, "start", "left", "steel_insulated", "steel_blue_grey", thickness=0.06, width=1.26,
           note="personnel door onto the dock")
    b.door("SK_D2", "SK_N", -10.85, "end", "left", "steel_insulated_glazed", "steel_blue_grey", thickness=0.06, width=1.26,
           note="office door onto the dock")
    b.opening("SK_W1", "SK_N", "window", -9.2, 1.00, 1.00, 2.20, False, glazing="pvc_double_glazed")
    b.opening("SK_RD3", "SK_S", "roller_door", -3.0, 4.00, 0.0, 4.20, True, state={"open_height": 2.60},
              note="partly open: 3.90 x 2.55 clear passage, curtain above blocks vision/bullets")
    b.door("SK_D4", "SK_S", 8.05, "start", "right", "steel_insulated", "steel_blue_grey", thickness=0.06, width=1.26)
    for i, (a, c) in enumerate(((-11.0, -6.6), (0.6, 11.0))):
        b.opening(f"SK_WH{i + 1}", "SK_S", "window", (a + c) / 2, c - a, 4.20, 5.20, False,
                  glazing="polycarbonate_translucent", note="high strip light, opaque for vision")
    b.door("SK_D5", "SK_W", -5.45, "start", "right", "steel_insulated", "steel_blue_grey", thickness=0.06, width=1.26)
    b.opening("SK_W2", "SK_W", "window", 5.1, 1.20, 1.00, 2.20, False, glazing="pvc_double_glazed", note="office")
    b.opening("SK_WH3", "SK_W", "window", -1.5, 8.0, 4.20, 5.20, False, glazing="polycarbonate_translucent")
    b.door("SK_D6", "SK_E", 0.55, "end", "left", "steel_insulated", "steel_blue_grey", thickness=0.06, width=1.26)
    b.opening("SK_WH4", "SK_E", "window", 0.0, 10.0, 4.20, 5.20, False, glazing="polycarbonate_translucent")
    b.door("SK_D3", "SK_P2", 3.55, "start", "right", "timber_flush", "hpl_grey", note="office -> hall")
    b.opening("SK_W3", "SK_P2", "window", 5.9, 1.50, 1.00, 2.20, False, glazing="internal_single_glazed",
              note="office window into the hall")
    columns = []
    for x in (-12.0 + 0.12, -6.0, 0.0, 6.0, 12.0 - 0.12):
        for y in (-7.5 + 0.12, 7.5 - 0.12):
            columns.append({"center": [r3(x), r3(y)], "size": [0.24, 0.24], "height": H, "section": "HEA240",
                            "material": "steel_painted_blue_grey"})
    for y in (-3.0, 3.0):  # gable posts
        for x in (-12.0 + 0.10, 12.0 - 0.10):
            columns.append({"center": [r3(x), r3(y)], "size": [0.20, 0.20], "height": r3(H + 0.5), "section": "HEA200 gable post",
                            "material": "steel_painted_blue_grey"})
    levels = [{"id": "L0", "name": "Hala", "floor_z": 0.0, "ceiling_height": 5.50, "floor_thickness": 0.20,
               "note": "clear height to rafter haunches 5.50; floor is 1.10 above the front yard (truck-bed height) and at grade at the rear"}]
    rooms = [
        {"id": "SK_R_HALA", "level": "L0", "name": "Skladová hala",
         "polygon": [[-12.0, -7.5], [12.0, -7.5], [12.0, 7.5], [-8.0, 7.5], [-8.0, 2.20], [-12.0, 2.20]],
         "ceiling_height": 5.50, "floor_material": "concrete_industrial_sealed", "in_zone": "front half"},
        {"id": "SK_R_KANCELAR", "level": "L0", "name": "Kancelář skladu", "polygon": rect(-12.0, 2.35, -8.15, 7.5),
         "ceiling_height": 3.00, "floor_material": "vinyl_tiles_grey",
         "note": "suspended ceiling 3.00; office roof deck at 3.20 is NOT accessible (no ladder)"},
    ]
    roof = [{"id": "RF_SKLAD", "type": "gable", "pitch_deg": 10.0, "ridge_axis": "X", "wall_rect": rect(-12.25, -7.75, 12.25, 7.75),
             "eave_z": H, "ridge_z": r3(H + 7.75 * math.tan(math.radians(10))), "overhang_eave": 0.30,
             "overhang_verge": {"-X": 0.20, "+X": 0.20}, "material": "trapezoidal_sheet_greygreen",
             "structure": "steel portal frames at 6.0 m (IPE360 rafters), Z-purlins", "fascia": "steel_flashing_greygreen"},
            {"id": "RF_RAMPA", "type": "mono", "pitch_deg": 5.0, "slope_direction": "+Y", "rect": rect(-12.25, 7.75, 12.25, 11.25),
             "eave_z": r3(4.80 - 3.5 * math.tan(math.radians(5))), "high_z": 4.80, "material": "trapezoidal_sheet_greygreen",
             "supports": [{"pos": [-12.0, 10.60], "size": [0.16, 0.16]}, {"pos": [0.0, 10.60], "size": [0.16, 0.16]},
                          {"pos": [12.0, 10.60], "size": [0.16, 0.16]}],
             "note": "dock canopy on cantilever brackets, posts at the dock edge"}]
    gutters = [
        {"roof": "RF_SKLAD", "edge": "+Y", "from": [-12.45, 8.05], "to": [12.45, 8.05], "z": 5.95, "profile": "box_150_galv",
         "note": "discharges onto canopy RF_RAMPA via spreaders"},
        {"roof": "RF_SKLAD", "edge": "-Y", "from": [-12.45, -8.05], "to": [12.45, -8.05], "z": 5.95, "profile": "box_150_galv"},
        {"roof": "RF_RAMPA", "edge": "+Y", "from": [-12.25, 11.30], "to": [12.25, 11.30], "z": 4.45, "profile": "half_round_150_galv"},
    ]
    downpipes = [
        {"id": "SK_DP1", "pos": [-12.1, -7.9], "top_z": 5.95, "dia": 0.12, "outlet": "gully_G_SK1"},
        {"id": "SK_DP2", "pos": [0.35, -7.9], "top_z": 5.95, "dia": 0.12, "outlet": "gully_G_SK2"},
        {"id": "SK_DP3", "pos": [12.1, -7.9], "top_z": 5.95, "dia": 0.12, "outlet": "gully_G_SK3"},
        {"id": "SK_DP4", "pos": [-12.0, 10.75], "top_z": 4.45, "dia": 0.12, "outlet": "dock_foot_channel", "note": "fixed to canopy post"},
        {"id": "SK_DP5", "pos": [12.0, 10.75], "top_z": 4.45, "dia": 0.12, "outlet": "dock_foot_channel", "note": "fixed to canopy post"},
    ]
    drainage = {"rear": "three cast-iron gullies at the rear downpipes, piped to a soakaway under the rear yard",
                "dock": "slotted concrete channel along the dock foot (yard side) collects the canopy downpipes and the yard; "
                        "outfall to the road-side ditch of ROAD_B at the yard gate",
                "gullies": [{"id": "G_SK1", "pos": [-12.1, -8.3]}, {"id": "G_SK2", "pos": [0.35, -8.3]}, {"id": "G_SK3", "pos": [12.1, -8.3]}]}
    foundation = {"plinth_height_above_floor": 1.00, "plinth_material": "precast_concrete_plinth_panel",
                  "ground_levels": {"front_yard (+Y beyond dock)": -1.10, "rear (-Y)": -0.05,
                                    "gables (+-X, 3 m aprons)": -0.05, "note": "building + rear yard + gable aprons sit on one pad cut "
                                    "into the slope; the front yard is the old 1976 flood-protection fill, 1.10 lower (truck-bed height)"},
                  "footing": "pad footings under columns, ground beam (hidden)"}
    dock = {"id": "SK_DOCK", "type": "loading_dock", "polygon": rect(-12.25, 7.75, 12.25, 10.75), "top_z": 0.0, "bottom_z": -1.10,
            "edge": "steel angle nosing + 4 rubber bumpers (0.25 proud) at x = -8, -3, 3, 8", "material": "concrete_broom",
            "note": "1.10 m edge is NOT a step (max step 0.40): access via SK_X1/SK_X2/SK_X3 only; one-way drop down allowed"}
    R = 1.10 / 6.0
    ext_stairs = [
        stair_flight("SK_X1", "ground", "L0", (-13.65, 9.25), 270.0, 1.50, R, 0.28, 6, -1.10,
                     construction="precast_concrete_steps", handrail="outer side", waist=0.0,
                     under_stair={"treatment": "solid_mass"}, note="dock west end, rises +X onto the dock"),
        stair_flight("SK_X2", "ground", "L0", (0.0, 12.15), 180.0, 2.00, R, 0.28, 6, -1.10,
                     construction="precast_concrete_steps", handrail="none (2.0 wide, open both sides)", waist=0.0,
                     under_stair={"treatment": "solid_mass"}, note="dock middle, rises -Y onto the dock"),
    ]
    exterior_steps = [
        {"id": "SK_X3", "at": "dock east end", "type": "ramp", "polygon": rect(12.25, 7.75, 18.85, 10.75), "z_top": 0.0,
         "z_bottom": -1.10, "slope_pct": r3(110 / 6.6), "rise_direction_deg": 90.0, "material": "concrete_broom",
         "note": "vehicle/pallet ramp 1:6 (9.5 deg), walkable, rises towards -X onto the dock"},
        {"id": "SK_X4", "at": "SK_D5", "type": "threshold", "polygon": rect(-12.55, -6.20, -12.25, -4.70), "risers": 0, "riser": 0.05,
         "apron": {"polygon": rect(-15.25, -7.75, -12.25, 7.75), "z": -0.05}, "material": "concrete",
         "note": "gable pad extends 3 m beyond the gable at floor -0.05 (terrain pad PAD_SKLAD): flush threshold, no step"},
        {"id": "SK_X5", "at": "SK_D6", "type": "threshold", "polygon": rect(12.25, -0.20, 12.55, 1.30), "risers": 0, "riser": 0.05,
         "apron": {"polygon": rect(12.25, -7.75, 15.25, 7.75), "z": -0.05}, "material": "concrete",
         "note": "gable pad extends 3 m beyond the gable at floor -0.05: flush threshold, no step"},
    ]
    furniture = [
        furn("SK_F1", "L0", "pallet_racking_full", (-1.6, 1.75), (9.4, 1.10, 3.60), 0, "high", note="rack run 1a (x -6.3..3.1), loaded solid"),
        furn("SK_F2", "L0", "pallet_racking_full", (7.7, 1.75), (5.4, 1.10, 3.60), 0, "high", note="rack run 1b; gap x 3.1..5.0 = cross aisle"),
        furn("SK_F3", "L0", "pallet_racking_full", (-4.45, -3.25), (8.9, 1.10, 3.60), 0, "high", note="rack run 2a (x -8.9..0)"),
        furn("SK_F4", "L0", "pallet_racking_full", (6.2, -3.25), (8.4, 1.10, 3.60), 0, "high", note="rack run 2b; gap x 0..2 = cross aisle"),
        furn("SK_F5", "L0", "forklift", (-10.0, 0.5), (2.3, 1.2, 2.10), 0, "high"),
        furn("SK_F6", "L0", "pallets_bagged_cement", (3.5, 5.6), (1.2, 1.0, 1.20), 0, "low"),
        furn("SK_F7", "L0", "pallets_bagged_cement", (10.3, 5.4), (1.2, 2.2, 1.20), 0, "low"),
        furn("SK_F8", "L0", "big_bags_x3", (-10.2, -5.6), (1.0, 3.2, 1.40), 0, "low", blocks_bullets=True),
        furn("SK_F9", "L0", "ibc_tanks_x2", (10.4, -5.9), (2.2, 1.0, 1.15), 0, "low"),
        furn("SK_F10", "L0", "desk_office", (-11.0, 4.3), (1.6, 0.8, 0.75), 90, "low"),
        furn("SK_F11", "L0", "filing_cabinets", (-9.9, 2.65), (1.8, 0.5, 1.40), 0, "low"),
        furn("SK_F12", "exterior", "pallet_stack", (-6.5, 9.2), (1.2, 1.0, 1.10), 0, "low", note="on the dock"),
        furn("SK_F13", "exterior", "pallet_stack", (5.5, 9.4), (1.2, 2.0, 1.10), 0, "low", note="on the dock"),
        furn("SK_F14", "exterior", "pallet_jack", (-1.8, 9.0), (1.6, 0.6, 1.20), 0, "none"),
    ]
    return finalize({
        "id": "B_SKLAD", "type": "mensi_sklad", "name": "Menší sklad (stavebniny a zemědělské potřeby)", "enterable": True,
        "story": "Sklad hnojiv a osiv postavilo JZD v roce 1976 na 1 m vysokém protipovodňovém násypu u návsi; v roce 2004 "
                 "ho firma Stavebniny Kalina (fiktivní) přestavěla na ocelovou halu. Podlaha je ve výšce ložné plochy "
                 "nákladního auta nad dvorem, zadní strana je zapuštěná do svahu.",
        "local_origin": "centre of the external footprint X[-12.25,12.25] x Y[-7.75,7.75] at finished floor (z 0.00); "
                        "+Y = front (loading dock)",
        "footprint_external": [24.5, 15.5],
        "footprint_parts": [{"part": "hall", "external_rect": rect(-12.25, -7.75, 12.25, 7.75),
                             "interior_rect": rect(-12.0, -7.5, 12.0, 7.5), "walls": {"x": [0.25, 0.25], "y": [0.25, 0.25]},
                             "check": "24.50 = 0.25 + 24.00 + 0.25; 15.50 = 0.25 + 15.00 + 0.25"}],
        "structure": "5 steel portal frames at 6.0 m, HEA240 columns on the inner face of the cladding zone, "
                     "0.25 m external wall zone = 0.12 sandwich panel + girts (0.25 precast concrete plinth panel up to +1.00)",
        "levels": levels, "rooms": rooms, "sealed_voids": [], "walls": b.walls, "openings": b.openings, "columns": columns,
        "slabs": [], "stairs": [], "exterior_stairs": ext_stairs, "balustrades": [], "balconies": [], "roof": roof,
        "gutters": gutters, "downpipes": downpipes, "drainage": drainage, "foundation": foundation, "loading_dock": dock,
        "exterior_steps": exterior_steps, "chimneys": [], "furniture": furniture,
        "zone_notes": "zone_sklad polygon covers the dock, the front aisle and the first rack row; racks are not climbable",
    })


# ================================================================================================
# 3) OBYTNÝ DŮM -- residential house (1934 two-storey brick house, hip roof, balcony with garden stair)
# ================================================================================================
def dum():
    b = B("B_DUM")
    T = T_EXT_MASONRY
    FF = 3.00          # floor-to-floor
    CH = 2.75          # clear ceiling height both floors
    TOP = 6.10         # external wall plate
    mat = "brick_masonry_450"
    fin_out = "render_lime_ochre_light"
    for lv, h in (("L0", FF), ("L1", TOP - FF)):
        b.ext_rect(f"DM{lv[1]}", lv, -5.5, -4.75, 5.5, 4.75, T, h, mat, "plaster_white_painted", fin_out)
        b.wall(f"DM{lv[1]}_SP", lv, (-5.05, 0.0), (5.05, 0.0), 0.30, CH, "internal", "brick_loadbearing_300",
               "plaster_white_painted", "plaster_white_painted", note="spine wall (carries floor joists)")
    # L0 partitions
    b.wall("DM0_Pa", "L0", (2.525, 0.15), (2.525, 4.30), T_INT, CH, "internal", "brick_partition_150",
           "plaster_white_painted", "tiles_kitchen_splash_1500", note="living | kitchen")
    b.wall("DM0_Pb", "L0", (-1.575, -4.30), (-1.575, -0.15), T_INT, CH, "internal", "brick_partition_150",
           "plaster_white_painted", "plaster_white_painted", note="rear room | hall")
    b.wall("DM0_Pc", "L0", (2.375, -4.30), (2.375, -0.15), T_INT, CH, "internal", "brick_partition_150",
           "plaster_white_painted", "tiles_utility_1500", note="hall | utility")
    b.wall("DM0_Pd", "L0", (0.85, -3.24), (0.85, -0.15), 0.10, CH, "internal", "timber_stud_board_100",
           "plaster_white_painted", "plaster_white_painted", note="closes the under-stair space (east side)")
    b.wall("DM0_Pe", "L0", (-0.40, -3.19), (0.80, -3.19), 0.10, CH, "internal", "timber_stud_board_100",
           "plaster_white_painted", "plaster_white_painted", note="closes the under-stair space (south face below flight 2 top and the well)")
    # L1 partitions
    b.wall("DM1_Pa", "L1", (0.0, 0.15), (0.0, 4.30), T_INT, CH, "internal", "brick_partition_150",
           "plaster_white_painted", "plaster_white_painted", note="bedroom | bedroom")
    b.wall("DM1_Pb", "L1", (-1.575, -4.30), (-1.575, -0.15), T_INT, CH, "internal", "brick_partition_150",
           "plaster_white_painted", "plaster_white_painted", note="child room | landing")
    b.wall("DM1_Pc", "L1", (2.375, -4.30), (2.375, -0.15), T_INT, CH, "internal", "brick_partition_150",
           "plaster_white_painted", "tiles_bath_1800", note="corridor | bathroom")

    def win(oid, wall, c, w=1.20, sill=0.85, head=2.35, glazing="timber_double_casement_transom", note=None):
        b.opening(oid, wall, "window", c, w, sill, head, False, glazing=glazing, note=note)

    # ---- L0 external (front = N wall, runs -X)
    for i, x in enumerate((-3.6, -1.2, 1.2)):
        win(f"DM0_WN{i + 1}", "DM0_N", x)
    win("DM0_WN4", "DM0_N", 3.8, w=1.00, sill=1.00, note="kitchen window above the worktop")
    b.door("DM0_D1", "DM0_S", 0.80, "end", "right", "timber_panel_glazed_green", "timber_green_paint",
           note="main entrance from the rear yard (3 steps, landing + canopy); opens outward onto the landing")
    win("DM0_WS1", "DM0_S", -3.4)
    win("DM0_WS2", "DM0_S", 3.6, w=0.90, sill=1.20, head=2.20)
    win("DM0_WW1", "DM0_W", 2.2)
    win("DM0_WW2", "DM0_W", -2.2)
    b.door("DM0_D2", "DM0_E", 1.85, "end", "left", "timber_panel_glazed_green", "timber_green_paint",
           note="kitchen side door to the side yard (3 steps)")
    win("DM0_WE1", "DM0_E", -2.2, w=0.90, sill=1.20, head=2.20)
    # ---- L0 internal
    b.door("DM0_D3", "DM0_SP", 1.60, "start", "left", "timber_panel_white", "timber_white_paint", note="hall corridor -> living room")
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
    win("DM1_WW1", "DM1_W", 2.2)
    win("DM1_WW2", "DM1_W", -2.2)
    win("DM1_WE1", "DM1_E", 2.2)
    win("DM1_WE2", "DM1_E", -2.2, w=0.90, sill=1.30, head=2.20)
    b.door("DM1_D6", "DM1_S", -3.475, "start", "right", "timber_balcony_door_glazed", "timber_white_paint",
           note="child room -> balcony DM_BALK (second way out of the upper floor via garden stair DM_S2)")
    # ---- L1 internal
    b.door("DM1_D1", "DM1_SP", 1.60, "start", "left", "timber_panel_white", "timber_white_paint", note="corridor -> east bedroom")
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
        stair_flight("DM_X1", "ground", "L0", (0.80, -6.51), 0.0, 1.50, 0.18, 0.28, 3, -0.54,
                     landing={"id": "DM_X1_LAND", "level": "L0", "polygon": rect(0.05, -5.95, 1.55, -4.75), "z": 0.0},
                     construction="terrazzo_precast_on_solid_base", handrail="left", waist=0.0,
                     under_stair={"treatment": "solid_mass"}, note="entrance steps + landing at DM0_D1"),
        stair_flight("DM_X2", "ground", "L0", (7.06, 1.85), 90.0, 1.40, 0.18, 0.28, 3, -0.54,
                     landing={"id": "DM_X2_LAND", "level": "L0", "polygon": rect(5.50, 1.05, 6.50, 2.65), "z": 0.0},
                     construction="concrete_on_solid_base", handrail="none", waist=0.0,
                     under_stair={"treatment": "solid_mass"}, note="kitchen side door steps"),
        stair_flight("DM_S2", "ground", "L1", (-2.15, -11.21), 0.0, 1.10, RB, 0.27, 19, -0.54,
                     landing={"id": "DM_BALK", "level": "L1", "polygon": rect(-5.40, -6.35, -1.40, -4.75), "z": FF},
                     construction="masonry_steps_on_solid_rubble_base_with_cheek_walls", handrail="both", waist=0.0,
                     under_stair={"treatment": "solid_mass", "note": "solid rubble base with rendered cheek walls: no space below"},
                     note="garden stair from the rear yard up to the balcony (second independent exit of the upper floor)"),
    ]
    balconies = [
        {"id": "DM_BALK", "level": "L1", "polygon": rect(-5.40, -6.35, -1.40, -4.75), "top_z": FF, "slab_thickness": 0.18,
         "access_door": "DM1_D6", "stair": "DM_S2", "material": "reinforced_concrete_cantilever_terrazzo_top",
         "parapet": {"height": 1.00, "thickness": 0.20, "solid": True, "material": "brick_rendered_ochre",
                     "segments": [[[-5.30, -4.75], [-5.30, -6.35]], [[-5.20, -6.25], [-2.70, -6.25]], [[-1.50, -6.35], [-1.50, -4.75]]],
                     "segment_rule": "segments are the parapet centre lines, boxes of `thickness` inside the slab edge",
                     "note": "solid 1.00 m parapet = crouch cover (firing position outside the zone); opening x -2.70..-1.60 for the stair"},
         "drainage": "falls 2 % to a copper spout at the south-west corner",
         "gameplay": "firing position over the rear yard and the S ring approach, outside zone_dvur (z 5.94 > z_max 5.54)"},
    ]
    levels = [
        {"id": "L0", "name": "Přízemí", "floor_z": 0.0, "ceiling_height": CH, "floor_thickness": 0.25,
         "note": "raised ground floor, +0.54 above the terrace (3 steps)"},
        {"id": "L1", "name": "Patro", "floor_z": FF, "ceiling_height": CH, "floor_thickness": 0.25},
        {"id": "ATTIC", "name": "Půda (nepřístupná)", "floor_z": FF + CH + 0.25, "ceiling_height": 0.0, "floor_thickness": 0.0,
         "note": "closed hatch; not walkable, not in navmesh"},
    ]
    rooms = [
        {"id": "DM_R0_OBYVAK", "level": "L0", "name": "Obývací pokoj", "polygon": rect(-5.05, 0.15, 2.45, 4.30),
         "ceiling_height": CH, "floor_material": "timber_parquet", "in_zone": True},
        {"id": "DM_R0_KUCHYNE", "level": "L0", "name": "Kuchyně", "polygon": rect(2.60, 0.15, 5.05, 4.30),
         "ceiling_height": CH, "floor_material": "ceramic_tiles_red_brown", "in_zone": True},
        {"id": "DM_R0_POKOJ", "level": "L0", "name": "Pokoj (zadní)", "polygon": rect(-5.05, -4.30, -1.65, -0.15),
         "ceiling_height": CH, "floor_material": "timber_parquet", "in_zone": True},
        {"id": "DM_R0_CHODBA", "level": "L0", "name": "Zádveří a chodba",
         "polygon": [[-1.50, -4.30], [2.30, -4.30], [2.30, -0.15], [0.90, -0.15], [0.90, -3.24], [-0.40, -3.24],
                     [-0.40, -3.14], [-1.50, -3.14]], "ceiling_height": CH, "floor_material": "terrazzo_grey", "in_zone": True},
        {"id": "DM_R0_TECH", "level": "L0", "name": "Technická místnost", "polygon": rect(2.45, -4.30, 5.05, -0.15),
         "ceiling_height": CH, "floor_material": "ceramic_tiles_grey", "in_zone": True},
        {"id": "DM_R1_LOZ_Z", "level": "L1", "name": "Ložnice západ", "polygon": rect(-5.05, 0.15, -0.075, 4.30),
         "ceiling_height": CH, "floor_material": "timber_boards", "in_zone": False},
        {"id": "DM_R1_LOZ_V", "level": "L1", "name": "Ložnice východ", "polygon": rect(0.075, 0.15, 5.05, 4.30),
         "ceiling_height": CH, "floor_material": "timber_boards", "in_zone": False},
        {"id": "DM_R1_DETSKY", "level": "L1", "name": "Dětský pokoj", "polygon": rect(-5.05, -4.30, -1.65, -0.15),
         "ceiling_height": CH, "floor_material": "timber_boards", "in_zone": False},
        {"id": "DM_R1_CHODBA", "level": "L1", "name": "Podesta a chodba",
         "polygon": [[-1.50, -4.30], [2.30, -4.30], [2.30, -0.15], [0.80, -0.15], [0.80, -3.14], [-1.50, -3.14]],
         "ceiling_height": CH, "floor_material": "terrazzo_grey", "in_zone": False},
        {"id": "DM_R1_KOUPELNA", "level": "L1", "name": "Koupelna", "polygon": rect(2.45, -4.30, 5.05, -0.15),
         "ceiling_height": CH, "floor_material": "ceramic_tiles_white", "in_zone": False,
         "dead_end_ok": "bathroom: single door, only high windows (sill 1.30 m) -- not a firing position, not campable over the zone"},
    ]
    sealed_voids = [
        {"id": "DM_V0_PODSCHODI", "level": "L0",
         "polygon": [[-1.50, -3.14], [-0.40, -3.14], [-0.40, -3.24], [0.80, -3.24], [0.80, -0.15], [-1.50, -0.15]],
         "reason": "space below both U-stair flights and the mid landing, closed by DM0_Pd / DM0_Pe; not walkable, not in navmesh"},
    ]
    slabs = [{"level": "L1", "polygon": rect(-5.05, -4.30, 5.05, 4.30), "thickness": 0.25, "top_z": FF,
              "openings": [{"id": "DM_SO1", "polygon": rect(-1.50, -3.14, 0.80, -0.15), "reason": "U-stair void (both flights + landing)"}]}]
    balustrades = [
        {"id": "DM_BAL1", "level": "L1", "polyline": [[-1.50, -3.14], [-0.30, -3.14]], "height": 1.00, "type": "timber_rail_steel_balusters"},
        {"id": "DM_BAL2", "level": "L1", "polyline": [[0.80, -3.14], [0.80, -0.15]], "height": 1.00, "type": "timber_rail_steel_balusters",
         "note": "on the void edge above partition DM0_Pd"},
        {"id": "DM_BAL3", "level": "Lmid", "polyline": [[-0.35, -3.14], [-0.35, -1.25]], "height": 1.00, "type": "handrail_in_well"},
    ]
    roof = [{"id": "RF_DUM", "type": "hip", "pitch_deg": 40.0, "ridge_axis": "X", "wall_rect": rect(-5.5, -4.75, 5.5, 4.75),
             "eave_z": TOP, "ridge_z": r3(TOP + 4.75 * math.tan(math.radians(40))),
             "ridge_from": [-0.75, 0.0], "ridge_to": [0.75, 0.0], "overhang_eave": 0.60, "overhang_verge": None,
             "material": "clay_tile_interlocking_red_brown_weathered", "structure": "timber purlin roof, hips at 45 deg on plan",
             "fascia": "timber_board_0.18_dark_brown", "soffit": "boarded_painted"}]
    gutters = [{"roof": "RF_DUM", "edge": e, "z": 6.05, "profile": "half_round_125_zinc", "from": f, "to": t}
               for e, f, t in (("+Y", [-6.1, 5.35], [6.1, 5.35]), ("-Y", [-6.1, -5.35], [6.1, -5.35]),
                               ("+X", [6.1, -5.35], [6.1, 5.35]), ("-X", [-6.1, -5.35], [-6.1, 5.35]))]
    downpipes = [{"id": f"DM_DP{i + 1}", "pos": [sx * 5.62, sy * 4.87], "top_z": 6.05, "dia": 0.10,
                  "outlet": "cast_iron_boot_to_drain_to_RW_DUM_outlet" if sy > 0 else "cast_iron_boot_to_drain_to_soakaway"}
                 for i, (sx, sy) in enumerate(((-1, -1), (1, -1), (-1, 1), (1, 1)))]
    drainage = {"front": "DM_DP3/DP4 boots -> PVC 110 drains under the garden -> two stone spouts in RW_DUM (local x -8.0 and +10.5, "
                         "0.40 m above the square) -> granite gutter along the square -> gully G_NV1 -> culvert to the brook",
                "rear": "DM_DP1/DP2 -> soakaway under the rear yard; the rear yard gravel falls 1 % away from the house",
                "balcony": "copper spout at the balcony SW corner onto a splash stone"}
    foundation = {"plinth_height_above_floor": 0.0, "plinth_visible_height": 0.54, "plinth_material": "render_cement_grey_plinth",
                  "ground_levels": {"all sides": -0.54}, "floor_to_terrain_rule": "terrace pad flat at house floor - 0.54",
                  "footing": "concrete strip footing (hidden), cellar NOT modelled"}
    exterior_steps = [
        {"id": "DM_X1_CANOPY", "at": "DM0_D1", "type": "canopy", "rect": rect(-0.15, -5.95, 1.75, -4.75), "z": 2.55,
         "material": "steel_glass"},
    ]
    furniture = [
        furn("DM_F1", "L0", "sofa", (-3.0, 3.75), (2.2, 0.9, 0.85), 0, "none", blocks_bullets=False, note="soft: concealment only"),
        furn("DM_F2", "L0", "table_dining", (-1.2, 1.7), (1.4, 0.9, 0.75), 0, "low"),
        furn("DM_F3", "L0", "wall_unit_cabinet", (-4.8, 1.6), (0.5, 2.6, 2.00), 0, "high"),
        furn("DM_F4", "L0", "kitchen_units", (3.85, 4.0), (2.3, 0.6, 0.90), 0, "low"),
        furn("DM_F5", "L0", "kitchen_table", (3.5, 3.05), (1.0, 0.8, 0.75), 0, "low"),
        furn("DM_F6", "L0", "wardrobe", (-1.95, -2.0), (0.6, 1.6, 2.00), 0, "none", blocks_bullets=False, note="soft: concealment only"),
        furn("DM_F7", "L0", "bed_single", (-3.85, -3.8), (1.0, 2.0, 0.55), 90, "none", blocks_bullets=False),
        furn("DM_F8", "L0", "boiler_washing_machine", (4.65, -3.6), (0.7, 1.3, 1.80), 0, "high"),
        furn("DM_F9", "L1", "bed_double", (-3.0, 3.0), (1.8, 2.0, 0.55), 0, "none", blocks_bullets=False),
        furn("DM_F10", "L1", "wardrobe", (-4.75, 1.3), (0.6, 2.0, 2.10), 0, "none", blocks_bullets=False),
        furn("DM_F11", "L1", "bed_double", (3.0, 3.0), (1.8, 2.0, 0.55), 0, "none", blocks_bullets=False),
        furn("DM_F12", "L1", "chest_of_drawers", (4.75, 1.0), (0.5, 1.2, 1.00), 0, "low"),
        furn("DM_F13", "L1", "bed_single", (-2.25, -2.0), (1.0, 2.0, 0.55), 0, "none", blocks_bullets=False),
        furn("DM_F14", "L1", "bathtub", (4.25, -3.6), (1.6, 0.75, 0.60), 0, "low"),
    ]
    return finalize({
        "id": "B_DUM", "type": "obytny_dum", "name": "Obytný dům (dům mistra)", "enterable": True,
        "story": "Zděný dvoupodlažní dům z roku 1934 s valbovou střechou, postavený pro mistra hamru na terase nad návsí. "
                 "Terasu drží pískovcová opěrná zeď se zapuštěnou garáží a zahradními schody; vstup je ze dvora, kuchyňské "
                 "dveře do bočního dvorku, balkon nad dvorem má schody do zahrady.",
        "local_origin": "centre of the external footprint X[-5.5,5.5] x Y[-4.75,4.75] at finished L0 floor (z 0.00); "
                        "+Y = street facade (towards the village square)",
        "footprint_external": [11.0, 9.5],
        "footprint_parts": [{"part": "house", "external_rect": rect(-5.5, -4.75, 5.5, 4.75), "interior_rect": rect(-5.05, -4.30, 5.05, 4.30),
                             "walls": {"x": [0.45, 0.45], "y": [0.45, 0.45]},
                             "check": "11.00 = 0.45 + 10.10 + 0.45; 9.50 = 0.45 + 8.60 + 0.45"}],
        "structure": "brick masonry 450 external, 300 spine wall, 150 partitions; reinforced concrete slab over L0, timber joists over L1",
        "levels": levels, "rooms": rooms, "sealed_voids": sealed_voids, "walls": b.walls, "openings": b.openings, "slabs": slabs,
        "stairs": stairs, "exterior_stairs": ext_stairs, "balustrades": balustrades, "balconies": balconies, "roof": roof,
        "gutters": gutters, "downpipes": downpipes, "drainage": drainage, "foundation": foundation, "exterior_steps": exterior_steps,
        "chimneys": [{"id": "DM_CH1", "type": "brick", "pos": [3.0, 0.0], "size": [0.60, 0.60], "top_z": 10.30,
                      "note": "kitchen/boiler flue in the spine wall (0.15 proud into kitchen, utility, east bedroom, bathroom), "
                              "0.2 m above the ridge"}],
        "furniture": furniture,
        "zone_notes": "zone_dvur counts the terrace garden, the side and rear yard strips and the ground floor; the upper floor "
                      "and the balcony (z +3.00, 0.40 m above z_max) are outside",
    })


def all_buildings():
    return [dilna(), sklad(), dum()]
