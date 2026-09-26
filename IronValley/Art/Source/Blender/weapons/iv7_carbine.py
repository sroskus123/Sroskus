#!/usr/bin/env python3
"""
IV-7 carbine -- Iron Valley hero weapon generator (original design, 5.56 mm class).

    python3 /home/user/Sroskus/IronValley/Art/Source/Blender/weapons/iv7_carbine.py

Regenerates everything deterministically: geometry, rig, UVs, baked textures, LODs,
validation report, FBX/GLB exports, re-import checks and review renders.  Also saves
iv7_carbine.blend next to this script.  Reference / numbers: Art/Reference/IV7_carbine_spec.md

Environment switches (optional):
    IV_QUICK=1          small textures / low samples / low-res renders (iteration only)
    IV_STAGES=a,b,...   optional stages to run: bake,save,validate,export,reimport,render
                        (default: all).  build, rig, uv and lod always run (fast); without
                        "bake" the existing PNGs in Art/Textures/Weapons/IV7 are reused.
    IV_RENDERS=a,b,...  subset of render names (see RENDER_NAMES below)

Authoring frame
---------------
Geometry is authored in CENTIMETRES in a "bore frame": X along the bore (0 = bolt face,
+X = muzzle), Z up (0 = bore axis), Y = weapon left (+Y) / right (-Y).  finalize() then
converts to metres and moves the origin to the firing-hand grip hold point, giving the
project convention: muzzle +X, top +Z, right side -Y, 1 BU = 1 m, origin = grip hold point.
"""

import os
import sys
import math
import json
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.dont_write_bytecode = True          # keep the source tree free of __pycache__
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "lib")))

import bpy            # noqa: E402
import bmesh          # noqa: E402
from mathutils import Vector, Matrix   # noqa: E402
import ivlib as L     # noqa: E402

# ----------------------------------------------------------------------------- paths
PROJECT = os.path.normpath(os.path.join(HERE, "..", "..", "..", ".."))       # IronValley/
ART = os.path.join(PROJECT, "Art")
TEX_DIR = os.path.join(ART, "Textures", "Weapons", "IV7")
FBX_DIR = os.path.join(ART, "Export", "FBX")
GLB_DIR = os.path.join(ART, "Export", "GLB")
PREV_DIR = os.path.join(ART, "Previews", "IV7")
BLEND = os.path.join(HERE, "iv7_carbine.blend")

QUICK = os.environ.get("IV_QUICK") == "1"
ALL_STAGES = ["bake", "save", "validate", "export", "reimport", "render"]
STAGES = [s for s in os.environ.get("IV_STAGES", ",".join(ALL_STAGES)).split(",") if s]
TEX_SIZE = 1024 if QUICK else 2048
SEED = 7

# ----------------------------------------------------------------------------- design (cm)
BARREL_LEN = 36.8                 # from bolt face (x = 0) to crown
MUZ_X0, MUZ_X1 = 35.4, 40.9       # muzzle device 5.5 cm
MUZ_R = 1.1                       # 2.2 cm OD
OAL = 86.0
BUTT_X = MUZ_X1 - OAL             # -45.1  rear face of the butt pad
UP_X0, UP_X1 = -14.5, 3.0         # upper receiver
RAIL_TOP = 3.0                    # accessory rail top above bore
HG_X0, HG_X1 = 3.2, 36.2          # handguard 33.0 cm
SIGHT_Z = 7.0                     # optic axis == iron sight line above bore (co-witness)
OPT_REAR_LENS_X = -6.9            # rear lens (outer face) of the optic
ADS_EYE_X = OPT_REAR_LENS_X - 8.0 # socket_ads: 8.0 cm behind the rear lens
GRIP_TOP_Z = -5.0
GRIP_RAKE = 22.0                  # degrees from vertical
GRIP_LEN = 11.0                   # along the raked axis
GRIP_TOP_CX = -15.0               # grip axis at the top plane
HOLD_DOWN = 4.5                   # hold point: this far down the grip axis from the top
MAG_PIVOT = (-6.3, 0.0, -4.26)    # magazine catch axis (= MR_C) on the magazine centreline (bore frame)

_ra = math.radians(GRIP_RAKE)
GRIP_DIR = Vector((-math.sin(_ra), 0.0, -math.cos(_ra)))
GRIP_TOP = Vector((GRIP_TOP_CX, 0.0, GRIP_TOP_Z))
HOLD = GRIP_TOP + GRIP_DIR * HOLD_DOWN          # firing-hand hold point (bore frame, cm)

# rail cross-section (generic accessory rail, 21 mm), y >= 0 half, (y, z) in cm
RAIL_NECK_Z = 2.25


def rail_half():
    return [(0.80, RAIL_NECK_Z), (0.80, 2.46), (1.06, 2.72), (0.78, RAIL_TOP)]


RAIL_SLOT_W = 0.53                # cross-slot width (along X)
RAIL_SLOT_Z = 2.62                # cross-slot floor


def W(x, y, z):
    """bore-frame cm -> final metres (origin at the grip hold point)."""
    return Vector(((x - HOLD.x) * 0.01, (y - HOLD.y) * 0.01, (z - HOLD.z) * 0.01))


# part registry: name -> dict(obj, set, bone)
PARTS = {}
COL = {}


def reg(obj, tset, bone, name=None):
    if name:
        obj.name = name
        obj.data.name = name
    PARTS[obj.name] = {"obj": obj, "set": tset, "bone": bone}
    L.link_to(obj, COL["parts"])
    return obj


def mirror_y(half):
    """(y, z) half outline for y >= 0 listed top->bottom -> full CCW outline."""
    right = [(-y, z) for (y, z) in half]
    left = [(y, z) for (y, z) in reversed(half)]
    return right + left


# ============================================================================ helpers
def stadium(length, height, cx, cz, n=4):
    """Rounded slot outline (u along length, v along height), CCW."""
    r = height / 2.0
    hl = length / 2.0 - r
    pts = []
    for k in range(n + 1):
        a = -math.pi / 2 + math.pi * k / n
        pts.append((cx + hl + r * math.cos(a), cz + r * math.sin(a)))
    for k in range(n + 1):
        a = math.pi / 2 + math.pi * k / n
        pts.append((cx - hl + r * math.cos(a), cz + r * math.sin(a)))
    return pts


def rail_slot_cutters(x_centers, half_width=1.4, z_floor=RAIL_SLOT_Z, z_top=4.0):
    return [L.box("rs", x - RAIL_SLOT_W / 2, x + RAIL_SLOT_W / 2, -half_width, half_width,
                  z_floor, z_top) for x in x_centers]


def rotate_obj_data(obj, angle_deg, axis, pivot):
    M = (Matrix.Translation(Vector(pivot)) @ Matrix.Rotation(math.radians(angle_deg), 4, axis)
         @ Matrix.Translation(-Vector(pivot)))
    obj.data.transform(M)
    obj.data.update()


def clamp_section(y_out=1.3, z_top=3.75, gap=0.012):
    """Rail clamp cross-section (y, z) wrapping the dovetail with a small gap."""
    g = gap
    # jaw lip: 45 deg face parallel to the dovetail plus a small chamfer at the tip, so the lip
    # is not an acute knife edge (it could not be bevelled)
    return [(y_out, z_top), (-y_out, z_top), (-y_out, 2.50), (-0.90 - g, 2.50), (-0.87 - g, 2.53),
            (-1.06 - g, 2.72), (-0.78 - g, RAIL_TOP + g), (0.78 + g, RAIL_TOP + g),
            (1.06 + g, 2.72), (0.87 + g, 2.53), (0.90 + g, 2.50), (y_out, 2.50)]


def bezier(p0, p1, p2, n):
    out = []
    for i in range(n + 1):
        t = i / n
        a = (1 - t) ** 2; b = 2 * (1 - t) * t; c = t * t
        out.append((a * p0[0] + b * p1[0] + c * p2[0], a * p0[1] + b * p1[1] + c * p2[1]))
    return out


def text_mesh(name, body, size, depth, x, z, y_face, rot_z=0.0):
    """Engraving cutter from Blender's built-in font, lying on a +Y facing plane."""
    cu = bpy.data.curves.new(name, 'FONT')
    cu.body = body
    cu.size = size
    cu.extrude = depth
    cu.resolution_u = 2
    cu.align_x = 'CENTER'
    cu.align_y = 'CENTER'
    ob = bpy.data.objects.new(name + "_c", cu)
    bpy.context.scene.collection.objects.link(ob)
    dg = bpy.context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(ob.evaluated_get(dg))
    bpy.data.objects.remove(ob)
    bpy.data.curves.remove(cu)
    mo = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(mo)
    # font: reads along +X, up +Y, extruded +-depth along Z.  Target (left side, read from
    # the +Y side): reading direction -X, up +Z, normal +Y.
    R = Matrix(((-1, 0, 0, 0), (0, 0, 1, 0), (0, 1, 0, 0), (0, 0, 0, 1)))
    me.transform(Matrix.Translation((x, y_face, z)) @ Matrix.Rotation(math.radians(rot_z), 4, 'Y') @ R)
    L.weld(mo, 1e-4)
    return mo


def bullet_icon(cx, cz, h=0.58, w=0.22, n=5):
    """Pictogram bullet outline (tip up) in the XZ plane."""
    r = w / 2
    body_top = cz + h / 2 - 0.2
    pts = [(cx - r, cz - h / 2), (cx + r, cz - h / 2), (cx + r, body_top)]
    for k in range(1, n):
        t = k / n
        pts.append((cx + r * (1 - t) ** 0.8, body_top + 0.2 * math.sin(t * math.pi / 2)))
    pts.append((cx, cz + h / 2))
    for k in range(n - 1, 0, -1):
        t = k / n
        pts.append((cx - r * (1 - t) ** 0.8, body_top + 0.2 * math.sin(t * math.pi / 2)))
    pts.append((cx - r, body_top))
    return pts


# ============================================================================ materials
MAT = {}


def build_materials():
    # Body edge mask: 2.2 mm inside-AO convexity (wide enough for visible edge wear; the 1 mm mask
    # hardly ever passed the wear threshold on 0.45 mm bevels)
    mb = L.mask_group("Body", edge_dist=0.0022, cavity_dist=0.006, ao_dist=0.03)
    mf = L.mask_group("Furniture", edge_dist=0.0016, cavity_dist=0.006, ao_dist=0.03)
    MAT["masks_body"], MAT["masks_furn"] = mb, mf
    # black hard-anodised aluminium (metallic, dark base, satin 0.30-0.38 roughness with breakup);
    # separate instances -> slight lot-to-lot differences
    MAT["anod_upper"] = L.mat_anodized("IV7_Anod_Upper", mb, base=(0.040, 0.040, 0.044), rough=0.34, seed=1)
    MAT["anod_lower"] = L.mat_anodized("IV7_Anod_Lower", mb, base=(0.043, 0.042, 0.046), rough=0.35, seed=2)
    MAT["anod_hg"] = L.mat_anodized("IV7_Anod_Handguard", mb, base=(0.038, 0.038, 0.042), rough=0.37, seed=3)
    MAT["anod_opt"] = L.mat_anodized("IV7_Anod_Optic", mb, base=(0.034, 0.034, 0.037), seed=4,
                                     rough=0.32, scratches=0.4)
    MAT["anod_misc"] = L.mat_anodized("IV7_Anod_Misc", mb, base=(0.041, 0.041, 0.044), rough=0.35, seed=5)
    x_soot0 = (MUZ_X0 + 2.0 - HOLD.x) * 0.01
    x_soot1 = (MUZ_X1 - HOLD.x) * 0.01
    MAT["steel_barrel"] = L.mat_steel("IV7_Steel_Barrel", mb, seed=6,
                                      soot={"axis": 'X', "start": (33.0 - HOLD.x) * 0.01,
                                            "end": (37.5 - HOLD.x) * 0.01})
    MAT["steel_muzzle"] = L.mat_steel("IV7_Steel_Muzzle", mb, seed=7, rough=0.4,
                                      soot={"axis": 'X', "start": x_soot0, "end": x_soot1})
    MAT["steel"] = L.mat_steel("IV7_Steel_Nitride", mb, seed=8, grain=0.3)
    MAT["phos"] = L.mat_phosphate("IV7_Steel_Phosphate", mb, seed=9)
    MAT["engrave"] = L.mat_paint("IV7_Engrave_Fill", mb, (0.30, 0.30, 0.31), rough=0.5, seed=10)
    MAT["paint_w"] = L.mat_paint("IV7_Paint_White", mb, (0.72, 0.72, 0.70), seed=11)
    MAT["paint_r"] = L.mat_paint("IV7_Paint_Red", mb, (0.50, 0.035, 0.025), seed=12)
    # furniture
    fde = (0.175, 0.125, 0.072)
    g0 = (GRIP_TOP_Z - 0.9 - HOLD.z) * 0.01
    g1 = (GRIP_TOP_Z - GRIP_LEN * math.cos(_ra) + 0.8 - HOLD.z) * 0.01
    MAT["grip"] = L.mat_polymer("IV7_Polymer_FDE_Grip", mf, base=fde, seed=21,
                                stipple={"zmax": g0, "zmin": g1, "scale": 400.0, "randomness": 0.5})
    MAT["stock"] = L.mat_polymer("IV7_Polymer_FDE_Stock", mf, base=fde, seed=22)
    mz = (MAG_PIVOT[2] - 6.5 - MAG_PIVOT[2]) * 0.01      # object coords of the magazine (origin at pivot)
    # magazine polymer: clearly matte and a lighter, slightly warm grey (reads apart from the
    # dark satin-metal receivers)
    MAT["mag"] = L.mat_polymer("IV7_Polymer_Mag", mf, base=(0.066, 0.063, 0.059), rough=0.76,
                               seed=23, stipple={"zmax": mz, "scale": 380.0, "normal_axis": "Y",
                                                 "randomness": 0.5, "height": 0.8})
    MAT["rubber"] = L.mat_rubber("IV7_Rubber_Pad", mf, seed=24, ribs={"axis": 'Z', "scale": 160.0})
    MAT["brass"] = L.mat_brass("IV7_Brass", mf, seed=25)
    MAT["copper"] = L.mat_copper("IV7_Copper", mf, seed=26)
    MAT["glass_front"] = L.mat_glass("M_IV7_Glass", tint=(0.95, 0.97, 1.0), thin_film_nm=120.0)
    MAT["reticle"] = L.mat_emissive("M_IV7_Reticle", (1.0, 0.02, 0.01), 8.0, illuminate=False)
    MAT["reticle_mask"] = L.mat_constant("M_IV7_ReticleMask", (0.01, 0.01, 0.01), rough=0.5)


def setmat(obj, key):
    obj.data.materials.clear()
    obj.data.materials.append(MAT[key])
    return obj


# ============================================================================ parts
def part_upper():
    prof = mirror_y([(0.78, RAIL_TOP), (1.06, 2.72), (0.80, 2.46), (0.80, 2.08),
                     (1.10, 1.86), (1.50, 1.05), (1.50, -1.90)])
    up = L.poly_extrude("UpperReceiver", prof, 'X', UP_X0, UP_X1)
    # 1) main body: bore, charging-handle channel (floor above the lower's buffer tower, end plate
    #    and castle nut so the handle can slide back its full stroke), ejection port, feed opening;
    #    bevelled with a 22 deg limit so the 26 deg side/chamfer creases get a soft bevel too (the
    #    weighted normals then keep the large flat faces flat)
    cut = [L.cyl("bore", 1.30, UP_X0 - 0.2, UP_X1 + 0.2, 'X', segs=40),
           L.box("ch_chan", UP_X0 - 0.2, CH_CHAN_X1, -CH_CHAN_HW, CH_CHAN_HW, CH_Z0 - 0.02, CH_Z1 + 0.02),
           L.poly_extrude("port", L.rounded_rect(6.5, 1.9, 0.28, 4, cx=-5.15, cy=0.0), 'Y', -2.6, -0.4),
           L.box("feed", -7.5, -0.9, -1.22, 1.22, -2.1, -1.0)]
    L.boolean(up, cut)
    L.bevel(up, 0.045, 2, 22)
    # 2) forward-assist boss, brass deflector and dust-cover hinge knuckles, bevelled on their own
    fa = L.lathe("fa", [(-9.5, 0.0), (-9.5, 0.25), (-10.6, 0.72), (-13.9, 0.72), (-13.9, 0.0)], 28,
                 'X', center=(-1.22, 0.32))
    defl = L.poly_extrude("defl", L.fillet_polygon(
        [(-8.55, -1.40), (-10.7, -1.40), (-10.45, -2.02), (-9.6, -2.24), (-8.85, -1.95)],
        [0, 0, 0.25, 0.4, 0.3], 3), 'Z', 0.05, 1.45)
    knuckles = []
    for x0, x1 in ((-8.95, -8.45), (-1.85, -1.35)):
        kn = L.cyl("kn", 0.22, x0, x1, 'X', center=DUST_HINGE, segs=16)
        L.union(kn, [L.box("web", x0, x1, -1.85, -1.3, -1.52, -1.18)])
        knuckles.append(kn)
    # the boss must not fill the receiver bore (the bore was cut before this union)
    L.boolean(fa, [L.cyl("bore_fa", 1.31, -15.0, -9.0, 'X', segs=40)])
    for o in [fa, defl] + knuckles:
        L.bevel(o, 0.03, 2, 30)
    L.union(up, [fa, defl] + knuckles)
    # 3) forward-assist bore, hinge-pin hole and rail cross-slots with their own narrow bevel
    L.boolean_bevelled(up, [L.cyl("fa_bore", 0.52, -14.6, -13.7, 'X', center=(-1.22, 0.32), segs=20),
                            L.cyl("hinge_hole", 0.095, -9.2, -1.1, 'X', center=DUST_HINGE, segs=12)]
                       + rail_slot_cutters([UP_X0 + 0.9 + k for k in range(17)]), 0.02, 1)
    return reg(setmat(up, "anod_upper"), "Body", "root")


TRIG_DX = -1.2                    # trigger group moved 1.2 cm rearward (trigger reach ~7.4 cm)
TRIG_PIVOT = (-10.0 + TRIG_DX, -4.1)
HAMMER_PIN = (-12.15, -4.72)           # clear of the trigger slot and the SEMI pictogram
MR_C = (-6.3, -4.26)              # magazine catch / release button axis (x, z), over the rear of the magwell
TOWER_FLAT_Z = 1.55               # flattened top of the lower's buffer tower (below the charging handle)


def part_lower():
    body = L.fillet_polygon([
        (2.30, -1.90), (-14.50, -1.90), (-14.50, -1.15), (-16.50, -1.15), (-16.50, -2.30),
        (-17.30, -3.10), (-17.40, -4.25), (-18.15, -5.00),
        (-7.60, -5.00), (-7.60, -3.80), (1.20, -3.80), (2.30, -2.80)],
        [0, 0, 0, 0, 0.3, 0.5, 0.45, 0.3, 0, 0, 0.5, 0.25], 3)
    low = L.poly_extrude("LowerReceiver", body, 'Y', -1.3, 1.3)
    setmat(low, "anod_lower")
    # magwell (loft of rounded rectangles, flared mouth); front wall ~6 mm below the pivot lug
    secs = []
    for z, x0, x1, hw in ((-1.9, -7.75, -0.25, 1.65), (-8.15, -7.75, -0.25, 1.65),
                          (-8.55, -7.9, -0.08, 1.78), (-8.8, -8.0, 0.02, 1.86)):
        rr = L.rounded_rect(x1 - x0, hw * 2, 0.4, 4, cx=(x0 + x1) / 2, cy=0.0)
        secs.append([(u, v, z) for u, v in rr])
    mw = L.loft("magwell", secs)
    # magazine well opening (through the top into the upper's feed opening)
    msecs = []
    for z, x0, x1, hw in ((-1.7, -7.45, -0.85, 1.26), (-8.2, -7.45, -0.85, 1.26),
                          (-8.82, -7.72, -0.55, 1.52), (-9.2, -7.9, -0.35, 1.7)):
        rr = L.rounded_rect(x1 - x0, hw * 2, 0.25, 3, cx=(x0 + x1) / 2, cy=0.0)
        msecs.append([(u, v, z) for u, v in rr])
    # the magwell shell (with its flared mouth) is hollowed and bevelled on its own, then unioned
    L.boolean(mw, [L.loft("mw_in", msecs[::-1])])
    L.bevel(mw, 0.045, 2, 30)
    # buffer tower (flattened top, 0.9 mm above the tube bore)
    tower = L.cyl("tower", 1.62, -16.5, -14.5, 'X', segs=40)
    L.boolean(tower, L.box("tt", -17, -14, -3, 3, TOWER_FLAT_Z, 3))
    # trigger guard
    g_out = L.fillet_polygon([(-7.45, -4.80), (-7.45, -7.25), (-8.25, -7.90), (-12.1, -7.90),
                              (-12.75, -7.45), (-12.7, -6.4), (-12.5, -4.80)],
                             [0, 0.35, 0.4, 0.45, 0.4, 0.4, 0], 3)
    g_in = L.fillet_polygon([(-7.95, -4.6), (-7.95, -6.95), (-8.45, -7.35), (-11.9, -7.35),
                             (-12.2, -6.95), (-12.05, -4.6)], [0, 0.3, 0.3, 0.3, 0.3, 0], 3)
    guard = L.poly_extrude("guard", g_out, 'Y', -0.62, 0.62)
    L.boolean(guard, L.poly_extrude("gin", g_in, 'Y', -1, 1))
    # magazine-release fence (right side, around the button)
    fence = [L.poly_extrude("fence", L.rounded_rect(1.3, 0.24, 0.1, 3, cx=MR_C[0], cy=cz), 'Y', -1.98, -1.62)
             for cz in (MR_C[1] + 0.60, MR_C[1] - 0.60)]
    L.union(low, [tower, guard] + fence)
    cut = []
    cut.append(L.loft("mw_in", msecs[::-1]))
    cut.append(L.cyl("tube_hole", 1.46, -16.7, -15.7, 'X', segs=40))
    cut.append(L.cyl("bore_rel", 1.30, -16.0, -14.4, 'X', segs=40))
    L.boolean(low, cut)
    L.bevel(low, 0.045, 2, 30)
    L.union(low, [mw])
    # small holes, pockets and panels: cut after the body bevel, with their own narrow bevel
    cut = []
    cut.append(L.box("trig_slot", -11.85, -9.6, -0.42, 0.42, -5.4, -3.0))
    cut.append(L.cyl("sel_hole", 0.3, -2, 2, 'Y', center=(-12.6, -3.3), segs=16))
    # catch hole: through the right magwell wall into the magwell (button travel 1.5 mm stays clear)
    cut.append(L.cyl("mr_hole", 0.40, -2.1, -1.1, 'Y', center=MR_C, segs=20))
    cut.append(L.poly_extrude("bc_pocket", L.rounded_rect(2.3, 1.94, 0.3, 3, cx=-8.95, cy=-2.95),
                              'Y', 1.17, 1.5))
    for (px, pz, r) in ((1.2, -2.9, 0.325), (-15.5, -2.6, 0.325), (TRIG_PIVOT[0], TRIG_PIVOT[1], 0.13),
                        (HAMMER_PIN[0], HAMMER_PIN[1], 0.13)):
        cut.append(L.cyl("pinhole", r, -1.8, 1.8, 'Y', center=(px, pz), segs=16))
    # shallow machined panels on both magwell flanks (right panel stops ahead of the catch)
    for sd in (1, -1):
        y0, y1 = (1.59, 1.9) if sd > 0 else (-1.9, -1.59)
        rr = (L.rounded_rect(6.2, 5.2, 0.5, 4, cx=-3.95, cy=-5.25) if sd > 0 else
              L.rounded_rect(4.5, 5.2, 0.5, 4, cx=-3.1, cy=-5.25))
        cut.append(L.poly_extrude("mwpanel", rr, 'Y', y0, y1))
    L.boolean_bevelled(low, cut, 0.02, 1)
    # pictograms (selector, left side) and roll marks: engraved + paint filled.
    # SAFE = white bullet with a diagonal gap, crossed by a thinner white slash that runs past the
    # outline; bullet and slash cutters never overlap (no coplanar boolean slivers)
    sx, sz = -10.85, -3.3
    ang = math.atan2(0.72, 0.60)                       # slash direction (lower rear -> upper front)
    def band(w, half_len):
        dx, dz = math.cos(ang), math.sin(ang)
        nx, nz = -dz, dx
        return [(sx - dx * half_len - nx * w / 2, sz - dz * half_len - nz * w / 2),
                (sx + dx * half_len - nx * w / 2, sz + dz * half_len - nz * w / 2),
                (sx + dx * half_len + nx * w / 2, sz + dz * half_len + nz * w / 2),
                (sx - dx * half_len + nx * w / 2, sz - dz * half_len + nz * w / 2)]
    bullet = L.poly_extrude("ic", bullet_icon(sx, sz, h=0.66, w=0.26), 'Y', 1.19, 1.6)
    L.boolean(bullet, [L.poly_extrude("gap", band(0.15, 1.0), 'Y', 1.0, 1.8)])
    slash = L.poly_extrude("sl", band(0.065, 0.50), 'Y', 1.19, 1.6)
    for c in (bullet, slash):
        setmat(c, "paint_w")
    L.boolean(low, [bullet, slash], material_mode='TRANSFER')
    semi = [L.poly_extrude("ic", bullet_icon(-12.6, -4.6, h=0.5), 'Y', 1.19, 1.6)]
    auto = [L.poly_extrude("ic", bullet_icon(-14.05 + dx, -3.3), 'Y', 1.19, 1.6) for dx in (-0.32, 0.0, 0.32)]
    for c in semi + auto:
        setmat(c, "paint_r")
    L.boolean(low, semi + auto, material_mode='TRANSFER')
    t1 = text_mesh("t_iv7", "IV-7", 0.9, 0.1, -3.95, -5.2, 1.59 - 0.05 + 0.1)
    t2 = text_mesh("t_cal", "5.56 mm", 0.48, 0.1, -3.95, -6.35, 1.59 - 0.05 + 0.1)
    setmat(t1, "engrave"); setmat(t2, "engrave")
    L.boolean(low, [t1, t2], material_mode='TRANSFER')
    # ensure the anodised material is slot 0
    return reg(low, "Body", "root")


def part_handguard():
    half = [(0.78, RAIL_TOP), (1.06, 2.72), (0.80, 2.46), (0.80, RAIL_NECK_Z), (1.25, RAIL_NECK_Z),
            (2.50, 1.10), (2.50, -1.20), (1.35, -2.70)]
    outer = mirror_y(half)
    radii = [0, 0, 0, 0, 0.25, 0.35, 0.35, 0.35, 0.35, 0.35, 0.35, 0.25, 0, 0, 0, 0]
    outer = L.fillet_polygon(outer, radii, 3)
    hg = L.poly_extrude("Handguard", outer, 'X', HG_X0, HG_X1)
    ih = [(0.9, 1.90), (2.18, 0.98), (2.18, -1.08), (1.20, -2.38)]
    inner = L.fillet_polygon(mirror_y(ih), 0.3, 3)
    # base tube first, bevelled on its own (long clean edges); the slots, vents and rail slots are
    # cut afterwards and get their own narrow bevel
    L.boolean(hg, [L.poly_extrude("hg_in", inner, 'X', HG_X0 - 1, HG_X1 + 1)])
    L.bevel(hg, 0.05, 1, 30)
    cut = []
    # side slots (M-LOK style) on both sides, bottom slots, upper-chamfer vents
    xs = [9.0 + 4.0 * k for k in range(7)]
    for x in xs:
        cut.append(L.poly_extrude("s", stadium(3.2, 0.72, x, -0.05), 'Y', -3.0, 3.0))
    for x in xs[:-1]:
        cut.append(L.poly_extrude("b", stadium(3.2, 0.72, x + 2.0, 0.0), 'Z', -3.2, -1.8))
    for side in (1, -1):
        for x in xs[:-1]:
            v = L.poly_extrude("v", stadium(1.9, 0.46, x + 2.0, 0.0), 'Z', -0.6, 0.6)
            # orient onto the upper chamfer face
            ang = math.degrees(math.atan2(2.50 - 1.25, 2.25 - 1.10))   # face normal tilt from +Z
            M = Matrix.Translation((0, side * 1.875, 1.675)) @ Matrix.Rotation(math.radians(-side * ang), 4, 'X')
            v.data.transform(M)
            cut.append(v)
    # clamp slit at the rear bottom + rail cross-slots
    cut.append(L.box("slit", HG_X0 - 0.5, HG_X0 + 2.6, -0.08, 0.08, -3.5, -1.5))
    n = int((HG_X1 - HG_X0 - 1.0) / 1.0) + 1
    cut += rail_slot_cutters([HG_X0 + 0.7 + k for k in range(n) if HG_X0 + 0.7 + k < HG_X1 - 0.4])
    # clamp screw counterbores (right side, rear)
    for x in (HG_X0 + 0.8, HG_X0 + 1.9):
        cut.append(L.cyl("cb", 0.28, -3.0, -2.55, 'Z', center=(x, -0.75), segs=16))
        cut.append(L.cyl("cb2", 0.13, -2.6, -2.1, 'Z', center=(x, -0.75), segs=12))
    L.boolean_bevelled(hg, cut, 0.02, 1)
    return reg(setmat(hg, "anod_hg"), "Body", "root")


def part_handguard_screws():
    objs = []
    for x in (HG_X0 + 0.8, HG_X0 + 1.9):
        s = L.lathe("scr", [(-2.68, 0.0), (-2.68, 0.22), (-2.64, 0.25), (-2.555, 0.25), (-2.555, 0.12),
                            (-2.28, 0.12), (-2.28, 0.0)], 12, 'Z', center=(x, -0.75))
        L.boolean(s, L.poly_extrude("hex", L.circle_pts(0.1, 6, x, -0.75), 'Z', -2.8, -2.52))
        objs.append(s)
    s = L.join(objs, "HandguardScrews")
    L.bevel(s, 0.012, 1, 30)
    return reg(setmat(s, "phos"), "Body", "root")


def part_barrel():
    prof = [(33.0, 0.0), (33.0, 0.28), (BARREL_LEN, 0.28), (BARREL_LEN, 0.56), (BARREL_LEN - 0.04, 0.63),
            (MUZ_X0, 0.63), (MUZ_X0, 0.82), (22.1, 0.82), (21.9, 0.84), (18.4, 0.84), (17.8, 0.95),
            (6.0, 0.95), (5.8, 1.0), (3.0, 1.0), (3.0, 1.25), (-1.8, 1.25), (-1.8, 0.0)]
    b = L.lathe("Barrel", prof, 32, 'X')
    L.bevel(b, 0.03, 1, 30)
    return reg(setmat(b, "steel_barrel"), "Body", "root")


def part_barrel_nut():
    n = L.lathe("BarrelNut", [(3.0, 1.02), (3.0, 1.62), (3.08, 1.72), (5.5, 1.72), (5.6, 1.6), (5.6, 1.02)],
                40, 'X', closed=True)
    cut = []
    for k in range(8):
        a = 2 * math.pi * (k + 0.5) / 8
        c = L.box("notch", 4.9, 5.8, -0.22, 0.22, 1.45, 2.2)
        rotate_obj_data(c, math.degrees(a), 'X', (0, 0, 0))
        cut.append(c)
    cut.append(L.box("gt_slot", 2.5, 6.0, -0.28, 0.28, 1.06, 2.3))     # open slot for the gas tube
    L.boolean(n, cut)
    L.bevel(n, 0.03, 1, 30)
    return reg(setmat(n, "phos"), "Body", "root")


def part_muzzle():
    prof = [(MUZ_X0, 0.655), (MUZ_X0, 1.0), (MUZ_X0 + 0.1, MUZ_R), (MUZ_X1 - 0.25, MUZ_R),
            (MUZ_X1, MUZ_R - 0.1), (MUZ_X1, 0.82), (MUZ_X1 - 0.5, 0.62), (37.5, 0.62), (37.35, 0.42),
            (36.95, 0.42), (36.9, 0.655)]
    m = L.lathe("MuzzleDevice", prof, 40, 'X', closed=True)
    cut = []
    for k in range(3):
        a = 90.0 + 120.0 * k
        c = L.poly_extrude("slot", stadium(4.2, 0.44, 39.8, 0.0), 'Z', 0.0, 1.6)
        rotate_obj_data(c, a - 90.0, 'X', (0, 0, 0))
        cut.append(c)
    for s in (1, -1):
        cut.append(L.box("flat", MUZ_X0 + 0.25, 36.9, -2, 2, s * 0.98, s * 2.0) if s > 0 else
                   L.box("flat", MUZ_X0 + 0.25, 36.9, -2, 2, -2.0, -0.98))
    L.boolean(m, cut)
    L.bevel(m, 0.03, 1, 30)
    return reg(setmat(m, "steel_muzzle"), "Body", "root")


def part_gas_block():
    gb = L.poly_extrude("GasBlock", L.rounded_rect(2.2, 1.9, 0.35, 3, cx=0.0, cy=0.85), 'X', 18.6, 21.7)
    L.union(gb, [L.cyl("gbc", 1.15, 18.6, 21.7, 'X', segs=32)])
    cut = [L.cyl("gb_bore", 0.845, 18.0, 22.3, 'X', segs=32),
           L.cyl("gb_tube", 0.265, 18.2, 19.7, 'X', center=(0.0, 1.35), segs=16)]
    for x in (19.3, 21.0):
        cut.append(L.cyl("ss", 0.17, -1.6, -0.95, 'Z', center=(x, 0.0), segs=12))
    L.boolean(gb, cut)
    L.bevel(gb, 0.035, 2, 30)
    return reg(setmat(gb, "phos"), "Body", "root")


def part_gas_tube():
    # starts just ahead of the barrel extension (x 3.0) inside the barrel-nut slot: no overlap with
    # the barrel extension (r 1.25); hidden under the barrel nut / handguard
    t = L.lathe("GasTube", [(3.05, 0.0), (3.05, 0.24), (19.4, 0.24), (19.4, 0.0)], 16, 'X', center=(0.0, 1.35))
    return reg(setmat(t, "steel"), "Body", "root")


def part_buffer_tube():
    # hollow front (bore r 1.25 to x -22.4): the bolt carrier (r 1.15, 7.5 cm stroke) recoils into
    # the tube instead of through solid geometry
    t = L.lathe("BufferTube", [(-16.25, 1.25), (-16.25, 1.45), (-35.7, 1.45), (-36.0, 1.3), (-36.0, 0.0),
                               (-22.4, 0.0), (-22.4, 1.25)], 44, 'X', closed=True)
    rib = L.poly_extrude("rib", L.rounded_rect(0.9, 0.5, 0.12, 3, cx=0.0, cy=-1.5), 'X', -35.6, -18.2)
    L.union(t, [rib])
    cut = [L.cyl("h", 0.17, -2.2, -1.2, 'Z', center=(x, 0.0), segs=12)
           for x in (-33.0, -31.1, -29.2, -27.3, -25.4, -23.5)]
    L.boolean(t, cut)
    L.bevel(t, 0.03, 2, 30)
    return reg(setmat(t, "anod_misc"), "Body", "root")


def part_end_plate():
    p = L.lathe("EndPlate", [(-16.5, 1.46), (-16.5, 1.64), (-16.78, 1.64), (-16.78, 1.46)], 44, 'X', closed=True)
    # sling ear starts outside the tube bore (y >= 1.47 > 1.46), so it never enters the buffer tube
    ear = L.poly_extrude("ear", L.rounded_rect(1.3, 1.25, 0.45, 4, cx=2.12, cy=-0.2), 'X', -16.5, -16.78)
    L.union(p, [ear])
    # QD socket and a flat top level with the lower's tower (the charging handle slides over it)
    L.boolean(p, [L.cyl("qd", 0.3, -17, -16.2, 'X', center=(2.27, -0.2), segs=16),
                  L.box("flat", -17.0, -16.2, -3.0, 3.0, TOWER_FLAT_Z, 3.0)])
    L.bevel(p, 0.025, 1, 30)
    return reg(setmat(p, "phos"), "Body", "root")


def part_castle_nut():
    # OD 3.24 cm: stays below the charging-handle path (CH bottom 1.66 above the bore)
    n = L.lathe("CastleNut", [(-16.78, 1.465), (-16.78, 1.56), (-16.84, 1.62), (-17.49, 1.62), (-17.55, 1.56),
                              (-17.55, 1.465)], 44, 'X', closed=True)
    cut = []
    for k in range(3):
        c = L.box("n", -17.7, -17.25, -0.25, 0.25, 1.35, 2.0)
        rotate_obj_data(c, 30.0 + 120.0 * k, 'X', (0, 0, 0))
        cut.append(c)
    L.boolean(n, cut)
    L.bevel(n, 0.025, 1, 30)
    return reg(setmat(n, "phos"), "Body", "root")


def part_grip():
    ns = 22
    npts = 36
    secs = []
    zlen = GRIP_LEN * math.cos(_ra)
    for i in range(ns + 1):
        u = i / ns
        # denser at the ends, but the first ring stays 2.8 mm below the top: a ring closer than
        # the 1.2 mm bevel made the bevel clamp unevenly (notched top rim)
        s = 0.55 * u + 0.45 * (0.5 - 0.5 * math.cos(math.pi * u))
        z = GRIP_TOP_Z - zlen * s
        cx = GRIP_TOP_CX - (GRIP_TOP_Z - z) * math.tan(_ra)
        # half depths / half width profiles along the grip.  The top section stays inside the
        # lower's bottom face (|y| <= 1.22 < 1.255, rear x -17.85 > -18.0), so the grip tucks
        # under the lower instead of showing a ledge.
        a_f = 2.4 + 0.25 * math.sin(math.pi * min(1, s / 0.4)) * (1 if s < 0.4 else 0) - 0.1 * s
        a_r = 2.4 + 0.45 * max(0.0, 1 - s / 0.14) ** 2 - 0.1 * s + 0.12 * math.sin(math.pi * s)
        b = 1.22 + 0.40 * math.sin(math.pi * min(1.0, s / 0.55) / 2) - 0.12 * max(0, s - 0.8) / 0.2
        if s > 0.93:
            f = (s - 0.93) / 0.07
            a_f += 0.18 * f; a_r += 0.22 * f; b += 0.1 * f
        sec = []
        p = 2.3
        for k in range(npts):
            th = 2 * math.pi * k / npts
            c, sn = math.cos(th), math.sin(th)
            ex = abs(c) ** (2 / p)
            ey = abs(sn) ** (2 / p)
            x = cx + (a_f if c >= 0 else a_r) * math.copysign(ex, c)
            y = b * (1 - 0.16 * max(c, 0) ** 2) * math.copysign(ey, sn)
            sec.append((x, y, z))
        secs.append(sec)
    g = L.loft("PistolGrip", secs)
    L.bevel(g, 0.12, 3, 40)
    return reg(setmat(g, "grip"), "Furniture", "root")


def _stock_section(x, zt, zb, hw, r):
    pts = L.rounded_rect(hw * 2, zt - zb, r, 5, cx=0.0, cy=(zt + zb) / 2)
    return [(x, u, v) for u, v in pts]


def part_stock():
    st = [(-27.45, 1.82, -1.82, 1.8, 1.15), (-27.8, 1.98, -1.98, 1.96, 1.1), (-28.6, 2.08, -2.12, 2.02, 1.05),
          (-31.0, 2.2, -2.45, 2.02, 1.0),
          (-34.0, 2.34, -3.85, 2.04, 0.95), (-37.5, 2.55, -6.2, 2.06, 0.95), (-41.0, 2.85, -8.4, 2.1, 0.9),
          (-43.3, 3.1, -9.3, 2.12, 0.85)]
    s = L.loft("Stock", [_stock_section(*a) for a in st])
    lever = L.poly_extrude("lever", L.fillet_polygon([(-28.4, -1.9), (-31.2, -1.9), (-31.0, -2.75), (-28.9, -2.6)],
                                                     0.2, 3), 'Y', -0.55, 0.55)
    win = L.fillet_polygon([(-34.4, -2.55), (-40.8, -2.55), (-40.8, -6.95), (-37.4, -5.0)], [0.6, 0.6, 0.6, 1.0], 4)
    cut = [L.poly_extrude("win", win, 'Y', -3, 3),
           L.cyl("chan", 1.47, -27.0, -38.6, 'X', segs=44),
           L.box("ribchan", -38.6, -27.0, -0.5, 0.5, -1.85, -1.2),
           L.poly_extrude("sling", stadium(2.4, 0.55, -42.0, -7.6), 'Y', -3, 3)]
    # rotate sling slot to follow the lower edge
    rotate_obj_data(cut[-1], -32.0, 'Y', (-42.0, 0, -7.6))
    L.boolean(s, cut)
    # bevel body and lever separately, then join: bevelling across the lever/stock junction
    # folded two triangles under the stock (found by the opposing-normal check)
    L.bevel(s, 0.08, 2, 30)
    L.bevel(lever, 0.06, 2, 30)
    L.union(s, [lever])
    return reg(setmat(s, "stock"), "Furniture", "root")


def part_butt_pad():
    secs = [_stock_section(-43.3, 3.1, -9.3, 2.12, 0.85), _stock_section(-43.9, 3.22, -9.42, 2.2, 0.9),
            _stock_section(-44.8, 3.18, -9.38, 2.17, 0.9)]
    # slightly convex rear face
    last = _stock_section(BUTT_X, 3.02, -9.22, 2.08, 0.9)
    secs.append(last)
    p = L.loft("ButtPad", secs)
    L.bevel(p, 0.12, 3, 25)
    return reg(setmat(p, "rubber"), "Furniture", "root")


CH_Z0, CH_Z1 = 1.66, 2.14        # charging-handle shaft bottom / top (bore frame)
CH_CHAN_HW = 0.46                 # channel half width (shaft half width 0.44): sliding fit
CH_CHAN_X1 = -1.9                 # front end of the channel in the upper
CH_SHAFT_X1 = -2.3                # front end of the shaft (bind pose)
CH_STROKE = 7.0                   # documented stroke (cm, -X)


def part_charging_handle():
    """T-handle behind the upper plus a long shaft that runs forward in the upper's channel:
    at the full 7 cm stroke 5.2 cm of shaft is still engaged in the receiver."""
    x_face = UP_X0 - 0.02                                        # wings stop 0.2 mm behind the upper
    half = [(x_face, 0.52), (x_face, 1.55), (x_face - 0.28, 2.22), (x_face - 0.88, 2.42),
            (x_face - 1.53, 2.26), (x_face - 1.86, 1.6)]
    pts = half + [(x, -y) for (x, y) in reversed(half)]
    pts = L.fillet_polygon(pts, [0, 0.15, 0.3, 0.3, 0.3, 0.2, 0.2, 0.3, 0.3, 0.3, 0.15, 0], 3)
    ch = L.poly_extrude("ChargingHandle", pts, 'Z', CH_Z0 - 0.04, CH_Z1 + 0.1)
    shaft = L.poly_extrude("shaft", L.rounded_rect(CH_SHAFT_X1 - (x_face - 0.1), 0.88, 0.06, 2,
                                                   cx=(CH_SHAFT_X1 + x_face - 0.1) / 2, cy=0.0),
                           'Z', CH_Z0, CH_Z1)
    L.bevel(ch, 0.03, 2, 30)
    L.bevel(shaft, 0.03, 2, 30)
    L.union(ch, [shaft])
    cut = []
    for side in (1, -1):
        for k in range(3):
            y = side * (1.15 + 0.35 * k)
            # closed-end grooves (grooves running out of the wing edge folded bevel geometry)
            cut.append(L.box("g", x_face - 1.5, x_face - 0.43, y - 0.07, y + 0.07, CH_Z1 + 0.01, CH_Z1 + 0.3))
    L.boolean_bevelled(ch, cut, 0.015, 1)
    return reg(setmat(ch, "anod_misc"), "Body", "charging_handle")


def part_bolt_carrier():
    bc = L.lathe("BoltCarrier", [(-14.3, 0.0), (-14.3, 1.05), (-14.2, 1.15), (-3.05, 1.15), (-2.95, 1.05),
                                 (-2.95, 0.95), (-1.9, 0.95), (-1.85, 0.8), (-1.85, 0.0)], 40, 'X')
    # smooth ejection-side flat with a short band of fine forward-assist notches near the rear
    # of the port (closed-ended, 1.2 mm wide, 2.6 mm pitch); bolt head + extractor at the front
    L.boolean(bc, [L.box("flat", -9.6, -3.1, -1.4, -1.02, -0.9, 0.7)])
    L.bevel(bc, 0.02, 1, 30)
    ex = L.box("extractor", -2.9, -1.95, -0.98, -0.72, -0.25, 0.25)
    L.bevel(ex, 0.015, 1, 30)
    L.union(bc, [ex])
    L.boolean_bevelled(bc, [L.box("serr", -8.15 + 0.26 * k - 0.06, -8.15 + 0.26 * k + 0.06, -1.4, -0.955,
                                  -0.40, 0.40) for k in range(9)], 0.01, 1)
    return reg(setmat(bc, "steel"), "Body", "bolt_carrier")


DUST_ANGLE = 176.0
DUST_HINGE = (-1.80, -1.35)       # (y, z) hinge axis (parallel to X)


def part_dust_cover():
    x0, x1 = -8.40, -1.90
    # plate: thin shell in YZ section extruded along X (closed position)
    sec = [(-1.53, -1.28), (-1.53, 1.10), (-1.67, 1.10), (-1.72, -1.24)]
    plate = L.poly_extrude("DustCover", sec, 'X', x0, x1)
    rib = L.poly_extrude("rib", [(-1.66, -0.35), (-1.66, 0.55), (-1.74, 0.5), (-1.74, -0.3)], 'X', x0 + 0.6, x1 - 0.6)
    # hinge barrel: union a SOLID cylinder, then drill the rod bore (a pre-carved plate unioned
    # with a hollow tube left coincident surfaces -> zero-thickness folded edges)
    barrel = L.cyl("barrel", 0.2, x0, x1, 'X', center=DUST_HINGE, segs=24)
    L.union(plate, [rib, barrel])
    L.boolean(plate, [L.cyl("bore", 0.105, x0 - 0.1, x1 + 0.1, 'X', center=DUST_HINGE, segs=16)])
    L.bevel(plate, 0.02, 1, 30)
    rotate_obj_data(plate, DUST_ANGLE, 'X', (0.0, DUST_HINGE[0], DUST_HINGE[1]))
    return reg(setmat(plate, "steel"), "Body", "dust_cover")


def part_dust_rod():
    r = L.lathe("DustCoverRod", [(-9.05, 0.0), (-9.05, 0.09), (-1.25, 0.09), (-1.25, 0.0)], 12, 'X', center=DUST_HINGE)
    return reg(setmat(r, "steel"), "Body", "root")


def part_forward_assist():
    f = L.lathe("ForwardAssist", [(-13.7, 0.0), (-13.7, 0.47), (-14.3, 0.47), (-14.42, 0.4), (-14.45, 0.0)], 24, 'X',
                center=(-1.22, 0.32))
    cut = []
    for k in range(6):
        c = L.box("fl", -14.6, -14.25, -0.05, 0.05, 0.2, 0.7)
        rotate_obj_data(c, 30 * k, 'X', (0, 0, 0))
        c.data.transform(Matrix.Translation((0, -1.22, 0.32)))
        cut.append(c)
    # pawl face follows the carrier (r 1.15) with 0.2 mm clearance, so the plunger never enters
    # the carrier in any carrier position
    cut.append(L.cyl("carrier_clear", 1.17, -15.0, -13.0, 'X', segs=64))
    L.boolean(f, cut)
    L.bevel(f, 0.012, 1, 30)
    return reg(setmat(f, "phos"), "Body", "root")


def part_pins():
    objs = []
    for (px, pz, r, head) in ((1.2, -2.9, 0.42, True), (-15.5, -2.6, 0.42, True),
                              (TRIG_PIVOT[0], TRIG_PIVOT[1], 0.125, False), (HAMMER_PIN[0], HAMMER_PIN[1], 0.125, False)):
        if head:
            rs = 0.32
            p = L.lathe("pin", [(-1.31, 0.0), (-1.31, rs - 0.05), (-1.28, rs), (1.30, rs), (1.30, r),
                                (1.42, r - 0.02), (1.47, r - 0.15), (1.48, 0.0)], 24, 'Y', center=(px, pz))
        else:
            p = L.lathe("pin", [(-1.31, 0.0), (-1.31, r - 0.02), (-1.29, r), (1.29, r), (1.31, r - 0.02),
                                (1.31, 0.0)], 12, 'Y', center=(px, pz))
        objs.append(p)
    pins = L.join(objs, "Pins")
    return reg(setmat(pins, "phos"), "Body", "root")


def part_mag_release():
    # button in the right magwell wall: inner end 2 mm outside the magazine, 1.5 mm press stays clear
    m = L.lathe("MagRelease", [(-1.46, 0.0), (-1.46, 0.36), (-1.88, 0.36), (-1.94, 0.31), (-1.96, 0.0)], 24, 'Y',
                center=MR_C)
    return reg(setmat(m, "phos"), "Body", "mag_release")


def part_bolt_catch():
    # top edge kept low (and the front corner chamfered) so the catch clears the lower's pocket
    # and the upper at +-9 deg
    body = L.fillet_polygon([(-9.9, -2.3), (-8.2, -2.25), (-8.0, -2.45), (-8.0, -2.6), (-8.8, -2.8), (-8.6, -3.7),
                             (-9.55, -3.7), (-9.9, -2.85)], [0.2, 0.1, 0.1, 0.1, 0.2, 0.15, 0.15, 0.2], 3)
    bc = L.poly_extrude("BoltCatch", body, 'Y', 1.21, 1.42)
    pad = L.poly_extrude("pad", L.rounded_rect(1.0, 0.72, 0.15, 3, cx=-9.05, cy=-3.25), 'Y', 1.3, 1.62)
    pin = L.cyl("rp", 0.14, 1.2, 1.47, 'Y', center=(-9.5, -2.45), segs=12)
    for o in (bc, pad, pin):
        L.bevel(o, 0.02, 1, 30)
    L.union(bc, [pad, pin])
    L.boolean_bevelled(bc, [L.box("r", -9.6 + 0.2 * k, -9.52 + 0.2 * k, 1.55, 1.8, -3.6, -2.9) for k in range(5)],
                       0.01, 1)
    return reg(setmat(bc, "phos"), "Body", "bolt_catch")


SEL_C = (-12.6, -3.3)


def part_selector():
    hub = L.lathe("Selector", [(-1.38, 0.0), (-1.38, 0.28), (1.30, 0.28), (1.30, 0.55), (1.56, 0.52),
                               (1.60, 0.0)], 28, 'Y', center=SEL_C)
    arm = L.poly_extrude("arm", L.fillet_polygon([(SEL_C[0], SEL_C[1] + 0.26), (SEL_C[0] + 1.3, SEL_C[1] + 0.17),
                                                  (SEL_C[0] + 1.3, SEL_C[1] - 0.17), (SEL_C[0], SEL_C[1] - 0.26)],
                                                 [0, 0.15, 0.15, 0], 3), 'Y', 1.32, 1.66)
    L.union(hub, [arm])
    ridge = L.box("ridge", SEL_C[0] + 0.85, SEL_C[0] + 0.97, 1.55, 1.75, SEL_C[1] - 0.12, SEL_C[1] + 0.12)
    L.union(hub, [ridge])
    L.bevel(hub, 0.02, 1, 30)
    idx = L.poly_extrude("idx", [(SEL_C[0] + 0.2, SEL_C[1] - 0.03), (SEL_C[0] + 0.75, SEL_C[1] - 0.03),
                                 (SEL_C[0] + 0.75, SEL_C[1] + 0.03), (SEL_C[0] + 0.2, SEL_C[1] + 0.03)], 'Y', 1.6, 1.8)
    setmat(idx, "paint_w")
    setmat(hub, "phos")
    L.boolean(hub, [idx], material_mode='TRANSFER')
    return reg(hub, "Body", "selector")


def part_trigger():
    d = TRIG_DX
    cl = bezier((-9.95 + d, -4.35), (-9.05 + d, -5.55), (-9.62 + d, -6.62), 14)
    pts_f, pts_b = [], []
    for i, (x, z) in enumerate(cl):
        if i == 0:
            dx, dz = cl[1][0] - x, cl[1][1] - z
        elif i == len(cl) - 1:
            dx, dz = x - cl[i - 1][0], z - cl[i - 1][1]
        else:
            dx, dz = cl[i + 1][0] - cl[i - 1][0], cl[i + 1][1] - cl[i - 1][1]
        ln = math.hypot(dx, dz); nx, nz = -dz / ln, dx / ln
        t = 0.36 - 0.1 * (i / (len(cl) - 1))
        pts_f.append((x + nx * t / 2, z + nz * t / 2)); pts_b.append((x - nx * t / 2, z - nz * t / 2))
    outline = pts_b + [(cl[-1][0] - 0.02, cl[-1][1] - 0.12)] + list(reversed(pts_f))
    tr = L.poly_extrude("Trigger", outline, 'Y', -0.35, 0.35)
    hub = L.cyl("hub", 0.42, -0.35, 0.35, 'Y', center=TRIG_PIVOT, segs=24)
    L.union(tr, [hub])
    L.boolean(tr, [L.cyl("tp", 0.135, -0.5, 0.5, 'Y', center=TRIG_PIVOT, segs=16)])
    L.bevel(tr, 0.04, 2, 30)
    return reg(setmat(tr, "steel"), "Body", "trigger")


HINGE_Z = 4.52
TOWER_TOP = 4.28                  # sight-base tower top: 0.9 mm below a leaf folded rearward
LUG_R = 0.30                      # hinge lug radius around the pin axis
LUG_Y0, LUG_Y1 = 0.78, 0.95       # hinge lugs (|y|); the leaf knuckle is |y| <= 0.72
PIN_R = 0.075                     # hinge pin (part of the base); knuckle bore 0.085


def _sight_base(name, x0, x1, bolt_x, tower_pts, hinge_x):
    """Rail clamp + tower + cross bolt (sits in a rail cross-slot) + two hinge lugs with a pin.
    The leaf knuckle sits between the lugs on the pin, so it can fold 90 deg rearward without
    touching the tower (tower top 0.9 mm below the folded leaf)."""
    b = L.poly_extrude(name, clamp_section(1.3, 3.75), 'X', x0, x1)
    tower = L.poly_extrude("tw", tower_pts, 'Y', -0.95, 0.95)
    lug_pts = [(hinge_x - LUG_R, TOWER_TOP - 0.3), (hinge_x + LUG_R, TOWER_TOP - 0.3)]
    for k in range(13):
        a = math.pi * k / 12
        lug_pts.append((hinge_x + LUG_R * math.cos(a), HINGE_Z + LUG_R * math.sin(a)))
    lugs = [L.poly_extrude("lug", lug_pts, 'Y', LUG_Y0 * sd, LUG_Y1 * sd) if sd > 0 else
            L.poly_extrude("lug", lug_pts, 'Y', -LUG_Y1, -LUG_Y0) for sd in (1, -1)]
    pin = L.cyl("pin", PIN_R, -LUG_Y1 - 0.04, LUG_Y1 + 0.04, 'Y', center=(hinge_x, HINGE_Z), segs=16)
    L.union(b, [tower] + lugs + [pin])
    L.boolean(b, [L.cyl("bolt", 0.19, -2, 2, 'Y', center=(bolt_x, 2.8), segs=16)])
    return b


def _cross_bolt(name, bolt_x, y_right=-1.31):
    b = L.lathe(name, [(y_right, 0.0), (y_right, 0.18), (1.3, 0.18), (1.3, 0.3), (1.36, 0.3), (1.38, 0.0)], 16, 'Y',
                center=(bolt_x, 2.8))
    return L.bevel(b, 0.012, 1, 30)


def _leaf(name, frame_pts, hx, extra=None, thick=0.15, bev=0.025):
    """Leaf plate (profile in YZ, extruded along X) + knuckle between the base lugs, bored for the
    pin.  Plate, knuckle and extras (ring / post) are bevelled separately and then unioned, so
    every visible edge keeps a real bevel (bevelling the unioned leaf clamped them to ~0)."""
    lf = L.poly_extrude(name, frame_pts, 'X', hx - thick, hx + thick)
    kn = L.cyl("kn", 0.13, -0.72, 0.72, 'Y', center=(hx, HINGE_Z), segs=20)
    for o in [lf, kn] + (extra or []):
        L.bevel(o, bev, 2, 30)
    L.union(lf, [kn] + (extra or []))
    L.boolean(lf, [L.cyl("kb", PIN_R + 0.01, -0.9, 0.9, 'Y', center=(hx, HINGE_Z), segs=16)])
    return lf


def part_rear_sight():
    x0, x1, hx = -9.6, -7.3, -8.3
    tw = L.fillet_polygon([(x0, 3.7), (x1, 3.7), (x1, 4.05), (-7.75, TOWER_TOP), (x0, TOWER_TOP)],
                          [0, 0, 0.2, 0.3, 0.2], 3)
    b = _sight_base("RearSightBase", x0, x1, -8.6, tw, hx)
    knob = L.lathe("knob", [(-1.28, 0.42), (-1.72, 0.42), (-1.76, 0.36), (-1.76, 0.0), (-1.28, 0.0)], 24, 'Y',
                   center=(-8.95, 3.25))
    L.union(b, [knob])
    L.bevel(b, 0.03, 2, 30)
    reg(setmat(b, "anod_misc"), "Body", "root")
    reg(setmat(_cross_bolt("RearSightBolt", -8.6, y_right=-1.27), "phos"), "Body", "root")   # ends inside the knob
    # leaf (deployed): frame with protective ears + ghost-ring aperture on the sight line.  The
    # bottom corners are notched (|y| 0.72) to clear the hinge lugs; the centre post runs up into
    # the ring so the ring is one piece with the leaf.
    z0 = HINGE_Z
    frame = L.fillet_polygon([(-0.72, z0), (0.72, z0), (0.72, z0 + 0.42), (1.12, z0 + 0.62), (1.12, 7.45),
                              (0.86, 7.62), (0.74, 5.2), (0.36, 5.2), (0.36, 6.62), (-0.36, 6.62), (-0.36, 5.2),
                              (-0.74, 5.2), (-0.86, 7.62), (-1.12, 7.45), (-1.12, z0 + 0.62), (-0.72, z0 + 0.42)],
                             [0.05, 0.05, 0.1, 0.1, 0.12, 0.12, 0.12, 0.1, 0.05, 0.05, 0.1, 0.12, 0.12, 0.12,
                              0.1, 0.1], 4)
    ring = L.lathe("ring", [(hx - 0.15, 0.45), (hx - 0.15, 0.62), (hx + 0.15, 0.62), (hx + 0.15, 0.45)], 32, 'X',
                   center=(0.0, SIGHT_Z), closed=True)
    # the post (frame) reaches z 6.62 and must not fill the aperture: trim it with the aperture
    # cylinder before the union
    frame_obj_trim = L.cyl("ap", 0.45, hx - 0.3, hx + 0.3, 'X', center=(0.0, SIGHT_Z), segs=32)
    lf = _leaf("RearSightLeaf", frame, hx, [ring])
    L.boolean(lf, [frame_obj_trim])
    return reg(setmat(lf, "anod_misc"), "Body", "rear_sight")


def part_front_sight():
    x0, x1, hx = 32.2, 34.4, 33.4
    tw = L.fillet_polygon([(x0, 3.7), (x1, 3.7), (x1, TOWER_TOP), (32.9, TOWER_TOP), (x0, 3.98)],
                          [0, 0, 0.2, 0.3, 0.2], 3)
    b = _sight_base("FrontSightBase", x0, x1, 33.9, tw, hx)
    L.bevel(b, 0.03, 2, 30)
    reg(setmat(b, "anod_misc"), "Body", "root")
    reg(setmat(_cross_bolt("FrontSightBolt", 33.9), "phos"), "Body", "root")
    z0 = HINGE_Z
    frame = L.fillet_polygon([(-0.72, z0), (0.72, z0), (0.72, z0 + 0.42), (1.05, z0 + 0.62), (1.05, 7.2),
                              (0.85, 7.42), (0.68, 7.2), (0.68, 5.0), (-0.68, 5.0), (-0.68, 7.2), (-0.85, 7.42),
                              (-1.05, 7.2), (-1.05, z0 + 0.62), (-0.72, z0 + 0.42)],
                             [0.05, 0.05, 0.1, 0.1, 0.1, 0.1, 0.1, 0.12, 0.12, 0.1, 0.1, 0.1, 0.1, 0.1], 4)
    post = L.poly_extrude("post", [(-0.3, 4.9), (0.3, 4.9), (0.3, 5.3), (0.1, 5.6), (0.1, SIGHT_Z), (-0.1, SIGHT_Z),
                                   (-0.1, 5.6), (-0.3, 5.3)], 'X', hx - 0.11, hx + 0.11)
    lf = _leaf("FrontSightLeaf", frame, hx, [post], bev=0.02)
    return reg(setmat(lf, "anod_misc"), "Body", "front_sight")


OPT_X0, OPT_X1 = -7.3, -0.4
RETICLE_R = 0.015                 # 0.3 mm dot


def part_optic():
    secs = []
    # 48 points around (12 per quarter): the housing and hood silhouette is the closest surface
    # to the eye in the ADS view
    for x, s in ((OPT_X0, 0.95), (OPT_X0 + 0.25, 1.0), (-1.4, 1.0), (-1.05, 1.06), (OPT_X1, 1.06)):
        sec = L.superellipse(1.8 * s, 1.8 * s, 3.0, 48, 0.0, SIGHT_Z, phase=math.pi / 48)
        secs.append([(x, u, v) for u, v in sec])
    body = L.loft("Optic", secs)
    # riser / mount
    riser = L.poly_extrude("riser", L.fillet_polygon([(-5.9, 3.6), (-1.8, 3.6), (-1.8, 4.2), (-2.4, 5.9),
                                                      (-5.3, 5.9), (-5.9, 4.2)], [0, 0, 0.3, 0.5, 0.5, 0.3], 6),
                           'Y', -1.05, 1.05)
    clamp = L.poly_extrude("clamp", clamp_section(1.3, 3.8), 'X', -5.9, -1.8)
    turret_e = L.lathe("te", [(8.55, 0.0), (8.55, 0.88), (9.05, 0.88), (9.1, 0.76), (9.62, 0.76), (9.66, 0.7),
                              (9.66, 0.0)], 24, 'Z', center=(-3.75, 0.0))
    turret_w = L.lathe("tw", [(-1.55, 0.0), (-1.55, 0.88), (-2.05, 0.88), (-2.1, 0.76), (-2.62, 0.76), (-2.66, 0.7),
                              (-2.66, 0.0)], 24, 'Y', center=(-3.75, SIGHT_Z))
    knob_b = L.lathe("kb", [(1.55, 0.0), (1.55, 0.95), (2.1, 0.95), (2.16, 0.86), (2.16, 0.0)], 32, 'Y',
                     center=(-4.9, SIGHT_Z))
    cknob = L.lathe("ck", [(-1.28, 0.55), (-1.9, 0.55), (-1.95, 0.48), (-1.95, 0.0), (-1.28, 0.0)], 28, 'Y',
                    center=(-3.6, 2.85))
    L.union(body, [riser, clamp, turret_e, turret_w, knob_b, cknob])
    # bore with integral lens-seat rings (x -6.65..-6.5 behind the rear lens, -1.3..-1.15 in
    # front of... behind the front lens): one stepped lathe cutter keeps the mesh manifold
    bore_prof = [(OPT_X0 - 0.5, 0.0), (OPT_X0 - 0.5, 1.3), (-6.65, 1.3), (-6.65, 1.12), (-6.5, 1.12), (-6.5, 1.3),
                 (-1.3, 1.3), (-1.3, 1.12), (-1.15, 1.12), (-1.15, 1.3), (OPT_X1 + 0.5, 1.3), (OPT_X1 + 0.5, 0.0)]
    cut = [L.lathe("bore", bore_prof, 48, 'X', center=(0.0, SIGHT_Z)),
           L.cyl("rbolt", 0.19, -1.28, 2, 'Y', center=(-3.6, 2.8), segs=16)]
    # knurl flutes on turret caps and brightness knob: cut after the body bevel and given their
    # own narrow single-segment bevel (no razor edges, few extra triangles)
    fl = []
    for k in range(12):
        a = 360.0 * k / 12
        c = L.box("fl", -0.055, 0.055, 0.68, 0.9, 9.2, 9.7)
        rotate_obj_data(c, a, 'Z', (0, 0, 0)); c.data.transform(Matrix.Translation((-3.75, 0, 0)))
        fl.append(c)
        c = L.box("fl", -0.055, 0.055, -2.7, -2.16, 0.68, 0.9)
        rotate_obj_data(c, a, 'Y', (0, 0, 0)); c.data.transform(Matrix.Translation((-3.75, 0, SIGHT_Z)))
        fl.append(c)
    for k in range(16):
        c = L.box("fl", -0.07, 0.07, 1.6, 2.25, 0.86, 1.1)
        rotate_obj_data(c, 360.0 * k / 16, 'Y', (0, 0, 0)); c.data.transform(Matrix.Translation((-4.9, 0, SIGHT_Z)))
        fl.append(c)
    fl.append(L.box("cs", -3.75 - 0.5, -3.75 + 0.5, -0.07, 0.07, 9.58, 9.8))
    fl.append(L.box("cs", -3.75 - 0.07, -3.75 + 0.07, -2.8, -2.58, SIGHT_Z - 0.5, SIGHT_Z + 0.5))
    L.boolean(body, cut)
    L.bevel(body, 0.035, 2, 30)
    L.boolean_bevelled(body, fl, 0.012, 1)
    reg(setmat(body, "anod_opt"), "Body", "root")
    # cross bolt through the clamp (sits in a rail slot)
    bolt = _cross_bolt("OpticBolt", -3.6, y_right=-1.27)       # right end inside the clamp knob
    reg(setmat(bolt, "phos"), "Body", "root")
    # lenses (constant glass material) and reticle (emissive)
    lr = L.cyl("OpticLensRear", 1.29, -6.9, -6.68, 'X', center=(0.0, SIGHT_Z), segs=48)
    lf = L.cyl("OpticLensFront", 1.29, -1.13, -0.93, 'X', center=(0.0, SIGHT_Z), segs=48)
    for o in (lr, lf):
        L.bevel(o, 0.02, 1, 30)
        reg(setmat(o, "glass_front"), None, "root")
    # reticle: 0.3 mm emissive dot bonded to the inner face of the front lens (x = -1.13), about
    # 4.5 px wide in the 1600 px ADS render.  Only the eye-side cap (-X) is emissive; the cap facing
    # the muzzle and the rim use a black mask material, so the dot is not seen from the front
    # (a real sight's emitter is hidden behind the reflective front lens).
    dot = L.cyl("OpticReticle", RETICLE_R, -1.1352, -1.1302, 'X', center=(0.0, SIGHT_Z), segs=12)
    dot.data.materials.append(MAT["reticle"])
    dot.data.materials.append(MAT["reticle_mask"])
    for pl in dot.data.polygons:
        pl.material_index = 0 if pl.normal.x < -0.9 else 1
    # glows but does not light the optic tube (render-only setting; Unreal: unlit emissive)
    dot.visible_diffuse = False
    dot.visible_glossy = False
    dot.visible_shadow = False
    return reg(dot, None, "root")


# ---- magazine ---------------------------------------------------------------
MAG_TOP_BODY = -2.4
MAG_STRAIGHT = 5.8
MAG_R = 30.0
MAG_BODY_LEN = 17.4
MAG_CX = -4.15
MAG_DEPTH, MAG_WIDTH = 6.5, 2.4


def mag_path(n_arc=16, extra=0.0):
    pts = []
    for k in range(4):
        pts.append((MAG_CX, 0.0, MAG_TOP_BODY - MAG_STRAIGHT * k / 3))
    arc = MAG_BODY_LEN - MAG_STRAIGHT + extra
    phi = arc / MAG_R
    z0 = MAG_TOP_BODY - MAG_STRAIGHT
    for k in range(1, n_arc + 1):
        a = phi * k / n_arc
        pts.append((MAG_CX + MAG_R * (1 - math.cos(a)), 0.0, z0 - MAG_R * math.sin(a)))
    return pts


def mag_path_from(z_start, extra=0.0, n_arc=16):
    """Magazine centreline from z_start (on the straight part) to the end of the arc."""
    full = mag_path(n_arc, extra)
    out = [(MAG_CX, 0.0, z_start)]
    out += [p for p in full if p[2] < z_start - 0.2]
    return out


def part_magazine():
    sec = L.rounded_rect(MAG_DEPTH, MAG_WIDTH, 0.42, 4)
    path = mag_path()
    body = L.sweep("Magazine", sec, path)
    # front / rear spine ribs (start below the magwell mouth)
    ribs = []
    for u in (MAG_DEPTH / 2, -MAG_DEPTH / 2):
        rs = L.rounded_rect(0.5, 0.9, 0.2, 3, cx=u, cy=0.0)
        ribs.append(L.sweep("spine", rs, mag_path_from(-9.4, extra=-0.7)))
    # baseplate: short sweep continuing the path
    fr = L.path_frames(path)
    p_end, t_end, n_end = fr[-1]
    bp_sec = L.rounded_rect(MAG_DEPTH + 0.45, MAG_WIDTH + 0.36, 0.5, 4)
    bp_path = [tuple(p_end - t_end * 0.35), tuple(p_end + t_end * 0.25), tuple(p_end + t_end * 0.55)]
    bp = L.sweep("baseplate", bp_sec, bp_path, scales=[(1, 1), (1, 1), (0.97, 0.93)])
    # feed lips (hollow top) + rear wall
    lips = []
    for sd in (1, -1):
        lip = [(1.2, -2.5), (1.2, -1.6), (0.95, -1.34), (0.46, -1.33), (0.42, -1.40), (0.66, -1.60),
               (0.99, -1.72), (0.99, -2.5)]
        lip = [(sd * y, z) for y, z in lip]
        lips.append(L.poly_extrude("lip", L.fillet_polygon(lip, [0, 0.12, 0.12, 0.04, 0.04, 0.1, 0.1, 0], 2),
                                   'X', -7.40, -2.45))
    rear = L.box("rearwall", -7.40, -7.18, -1.2, 1.2, -2.5, -1.6)
    # trim lips and rear wall to the body's rounded footprint (their square corners poked 0.3 mm
    # into the magwell's rounded inner corners)
    for o in lips + [rear]:
        foot = L.poly_extrude("foot", L.rounded_rect(MAG_DEPTH, MAG_WIDTH, 0.42, 4, cx=MAG_CX, cy=0.0), 'Z', -3.0, -1.0)
        L.boolean(o, [foot], op='INTERSECT')
    # staged bevels: body + spines + baseplate first, lips / rear wall on their own, then the round
    # pocket and catch notch with a narrow bevel of their own
    L.union(body, ribs + [bp])
    L.bevel(body, 0.05, 2, 30)
    for o in lips + [rear]:
        L.bevel(o, 0.03, 1, 30)
    L.union(body, lips + [rear])
    # pocket for the rounds under the lips + the catch notch on the left flank (engages the
    # magazine catch on the MR_C axis; hidden when inserted, visible on a dropped magazine)
    L.boolean_bevelled(body, [L.box("pocket", -7.18, -1.3, -0.99, 0.99, -3.15, -2.0),
                              L.box("catch", MR_C[0] - 0.32, MR_C[0] + 0.32, 1.08, 1.5, MR_C[1] - 0.26,
                                    MR_C[1] + 0.26)], 0.02, 1)
    reg(setmat(body, "mag"), "Furniture", "magazine")
    # two visible rounds (brass case + copper jacket); top round held by both lips
    rounds = [cartridge("round", -7.15, 0.0, -1.70), cartridge("round", -7.15, -0.49, -2.54)]
    r = L.join(rounds, "MagRounds")
    return reg(r, "Furniture", "magazine")


def cartridge(name, x0, y, z):
    prof = [(0.0, 0.0), (0.0, 0.455), (0.03, 0.478), (0.10, 0.478), (0.13, 0.40), (0.22, 0.40), (0.30, 0.472),
            (3.60, 0.452), (3.88, 0.316), (4.50, 0.316), (4.50, 0.286), (4.95, 0.286), (5.25, 0.235),
            (5.50, 0.14), (5.66, 0.05), (5.70, 0.0)]
    prof = [(x0 + a, r) for a, r in prof]
    c = L.lathe(name, prof, 20, 'X', center=(y, z))
    c.data.materials.append(MAT["brass"]); c.data.materials.append(MAT["copper"])
    mouth = x0 + 4.5
    for p in c.data.polygons:
        p.material_index = 1 if p.center.x > mouth + 1e-3 else 0
    return c


# ============================================================================ build
def build():
    t0 = time.time()
    L.CLEAN_DIST = 5e-4      # 5 micron in authoring units (cm)
    COL["parts"] = L.collection("IV7_Parts")
    build_materials()
    builders = [part_upper, part_lower, part_handguard, part_handguard_screws, part_barrel, part_barrel_nut,
                part_muzzle, part_gas_block, part_gas_tube, part_buffer_tube, part_end_plate, part_castle_nut,
                part_grip, part_stock, part_butt_pad, part_charging_handle, part_bolt_carrier, part_dust_cover,
                part_dust_rod, part_forward_assist, part_pins, part_mag_release, part_bolt_catch, part_selector,
                part_trigger, part_rear_sight, part_front_sight, part_optic, part_magazine]
    for b in builders:
        tb = time.time()
        b()
        L.log(f"  {b.__name__} {time.time() - tb:.1f}s")
    finalize()
    assign_contact()
    L.log(f"build done {time.time() - t0:.1f}s, parts={len(PARTS)}")


# ---- handling-contact attribute (drives edge wear / polish in the Body materials) ----------
# part: (base value, [(lo (x, y, z), hi (x, y, z), add), ...]) in bore-frame cm; None = unbounded
CONTACT = {
    "UpperReceiver": (0.30, [((None, None, 2.3), (None, None, None), 0.35),           # rail teeth
                             ((None, None, None), (-11.0, None, None), 0.2)]),        # rear (charging)
    "LowerReceiver": (0.35, [((None, None, None), (None, None, -7.6), 0.55),         # magwell flare
                             ((-12.8, None, None), (-7.4, None, -4.8), 0.45),         # trigger guard
                             ((-13.5, 0.9, -4.2), (-7.8, None, -1.9), 0.2),           # selector / catch
                             ((None, None, None), (-16.4, None, -3.4), 0.3),          # rear tang
                             ((-1.2, None, None), (None, None, -5.0), 0.25)]),        # magwell front
    "Handguard": (0.22, [((10.0, None, None), (27.0, None, -1.0), 0.6),              # support hand
                         ((None, None, 2.3), (None, None, None), 0.3),                # rail
                         ((34.5, None, None), (None, None, None), 0.35)]),            # front edge
    "BufferTube": (0.35, [((None, None, None), (None, None, -0.9), 0.35)]),
    "EndPlate": (0.7, []), "CastleNut": (0.5, []),
    "ChargingHandle": (0.55, [((None, 0.9, None), (-14.5, None, None), 0.45),
                              ((None, None, None), (-14.5, -0.9, None), 0.45)]),
    "Optic": (0.28, [((None, None, 8.5), (None, None, None), 0.5),                   # elevation turret
                     ((None, None, None), (None, -1.85, None), 0.5),                  # windage turret
                     ((None, 1.85, None), (None, None, None), 0.45),                  # brightness knob
                     ((None, None, None), (-6.9, None, None), 0.2),                   # rear hood rim
                     ((-0.8, None, None), (None, None, None), 0.2)]),                 # front rim
    "RearSightBase": (0.4, []), "FrontSightBase": (0.4, []),
    "RearSightLeaf": (0.45, [((None, None, 7.2), (None, None, None), 0.3)]),
    "FrontSightLeaf": (0.45, [((None, None, 7.0), (None, None, None), 0.3)]),
    "BoltCatch": (0.8, []), "Selector": (0.8, []), "MagRelease": (0.75, []), "Trigger": (0.55, []),
    "MuzzleDevice": (0.35, [((40.0, None, None), (None, None, None), 0.3)]),
    "Barrel": (0.15, []), "GasBlock": (0.15, []), "GasTube": (0.15, []), "BarrelNut": (0.2, []),
    "HandguardScrews": (0.3, []), "Pins": (0.5, []), "ForwardAssist": (0.7, []),
    "DustCover": (0.06, []), "DustCoverRod": (0.2, []), "BoltCarrier": (0.4, []),
    "RearSightBolt": (0.4, []), "FrontSightBolt": (0.4, []), "OpticBolt": (0.4, []),
}


def assign_contact():
    """Write the per-vertex float attribute 'iv_contact' (0.02..1) used by the anodised / steel
    materials: where hands, gear and slings touch the rifle, edge wear and polish are stronger."""
    import numpy as np
    soft = 0.5

    def sstep(a, b, x):
        t = np.clip((x - a) / (b - a), 0.0, 1.0)
        return t * t * (3 - 2 * t)
    for name, p in PARTS.items():
        base, zones = CONTACT.get(name, (0.3, []))
        me = p["obj"].data
        co = np.empty(len(me.vertices) * 3); me.vertices.foreach_get("co", co)
        co = co.reshape(-1, 3) * 100.0 + np.array(HOLD)
        val = np.full(len(co), base)
        for lo, hi, add in zones:
            m = np.ones(len(co))
            for k in range(3):
                if lo[k] is not None:
                    m *= sstep(lo[k] - soft, lo[k] + soft, co[:, k])
                if hi[k] is not None:
                    m *= 1.0 - sstep(hi[k] - soft, hi[k] + soft, co[:, k])
            val += add * m
        a = me.attributes.get("iv_contact") or me.attributes.new("iv_contact", 'FLOAT', 'POINT')
        a.data.foreach_set("value", np.clip(val, 0.02, 1.0).astype(np.float32))


def remove_contact():
    for p in PARTS.values():
        a = p["obj"].data.attributes.get("iv_contact")
        if a:
            p["obj"].data.attributes.remove(a)


def finalize():
    """cm bore frame -> metres, origin at the grip hold point; shading, weighted normals."""
    M = Matrix.Scale(0.01, 4) @ Matrix.Translation(-HOLD)
    for name, p in PARTS.items():
        o = p["obj"]
        o.data.transform(M)
        o.data.update()
        L.finish_shading(o, sharp_angle=50.0, weighted=True, triangulate=True, clean_dist=1e-6)


# ============================================================================ rig
ARM_NAME = "SK_IV7"
BONE_LEN = 0.02   # m; every bone points along +Y (world) with roll 0 -> world-aligned axes

# name: (head in bore-frame cm, deform)
BONES = {
    "root": (tuple(HOLD), True),
    "magazine": (MAG_PIVOT, True),
    "charging_handle": ((UP_X0 - 0.02 - 0.93, 0.0, (CH_Z0 + CH_Z1 + 0.1) / 2), True),   # T-handle centre
    "bolt_carrier": ((-8.0, 0.0, 0.0), True),
    "dust_cover": ((-5.15, DUST_HINGE[0], DUST_HINGE[1]), True),
    "trigger": ((TRIG_PIVOT[0], 0.0, TRIG_PIVOT[1]), True),
    "selector": ((SEL_C[0], 0.0, SEL_C[1]), True),
    "bolt_catch": ((-9.5, 1.3, -2.45), True),
    "mag_release": ((MR_C[0], -1.65, MR_C[1]), True),
    "rear_sight": ((-8.3, 0.0, HINGE_Z), True),
    "front_sight": ((33.4, 0.0, HINGE_Z), True),
    "socket_muzzle": ((MUZ_X1, 0.0, 0.0), False),
    "socket_ads": ((ADS_EYE_X, 0.0, SIGHT_Z), False),
    "socket_support_hand": ((17.0, 0.0, -2.7), False),
    "socket_firing_hand": (tuple(HOLD), False),
    "socket_eject": ((-5.15, -1.5, 0.0), False),
    "socket_mag": ((MAG_CX, 0.0, -8.8), False),
}


def rig():
    col = L.collection("IV7_Rig")
    ad = bpy.data.armatures.new(ARM_NAME)
    arm = bpy.data.objects.new(ARM_NAME, ad)
    col.objects.link(arm)
    ad.display_type = 'STICK'
    L.select([arm], arm)
    bpy.ops.object.mode_set(mode='EDIT')
    ebs = {}
    for name, (head, deform) in BONES.items():
        eb = ad.edit_bones.new(name)
        h = W(*head)
        eb.head = h
        eb.tail = h + Vector((0.0, BONE_LEN, 0.0))
        eb.roll = 0.0
        eb.use_deform = deform
        ebs[name] = eb
    for name, eb in ebs.items():
        if name != "root":
            eb.parent = ebs["root"]
    bpy.ops.object.mode_set(mode='OBJECT')
    # rigid skinning: every part object 100% weighted to exactly one bone
    for name, p in PARTS.items():
        o = p["obj"]
        bone = p["bone"]
        if bone != "root":
            L.set_origin(o, W(*BONES[bone][0]))
        o.vertex_groups.clear()
        vg = o.vertex_groups.new(name=bone)
        vg.add(list(range(len(o.data.vertices))), 1.0, 'REPLACE')
        o.parent = arm
        o.matrix_parent_inverse = arm.matrix_world.inverted()
        m = o.modifiers.new("Armature", 'ARMATURE')
        m.object = arm
    L.log(f"rig: {len(BONES)} bones, {len(PARTS)} skinned parts")
    return arm


# ============================================================================ uv / bake
def set_objects(tset):
    return [p["obj"] for p in PARTS.values() if p["set"] == tset]


HIDDEN_PARTS = {"Barrel": 0.35, "GasTube": 0.35, "GasBlock": 0.45, "BarrelNut": 0.4, "BoltCarrier": 0.7,
                "HandguardScrews": 0.6, "DustCoverRod": 0.5, "Pins": 0.8, "RearSightBolt": 0.7,
                "FrontSightBolt": 0.7, "OpticBolt": 0.7, "MagRounds": 0.8}


def uv_scale_policy(obj, info):
    """Texture-space budget per UV island: hidden / tiny / interior surfaces get less."""
    base = obj.name.split("_LOD")[0]
    if any(m.startswith(("IV7_Paint", "IV7_Engrave")) for m in info["materials"]):
        return 1.6                                       # markings: extra resolution for legibility
    f = HIDDEN_PARTS.get(base, 1.0)
    a_cm2 = info["area3d"] * 1e4
    if a_cm2 < 0.01:
        f *= 0.45
    elif a_cm2 < 0.06:
        f *= 0.7
    c = info["center"]; n = info["normal"]
    bore = Vector((c.x, 0.0, -HOLD.z * 0.01))            # point on the bore axis at this x
    radial = Vector((0.0, c.y - bore.y, c.z - bore.z))
    if base in ("Handguard", "UpperReceiver", "BufferTube") and radial.length > 1e-6:
        if n.dot(radial.normalized()) < -0.3:            # faces looking at the bore = interior
            f *= 0.4
    if base == "Optic":
        axis = Vector((0.0, 0.0, (SIGHT_Z - HOLD.z) * 0.01))
        r = Vector((0.0, c.y, c.z - axis.z))
        if r.length > 1e-6 and n.dot(r.normalized()) < -0.3 and r.length < 0.0135:
            f *= 0.6                                     # inside of the optic tube
    return f


UV_ANGLE = 62.0
UV_PACK_MARGIN = 0.0015           # 3 px at 2048 (+ 16 px distance-based dilation)
UV_REPORT = {}


def uv_planar_policy(obj):
    """Flat faces that smart projection splits into wedges (the selector hub disc and lever) and
    the selector barrel, which it cuts into stretched quadrant islands."""
    if obj.name.split("_LOD")[0] == "Selector":
        c = obj.matrix_world.inverted() @ W(SEL_C[0], 0.0, SEL_C[1])
        return [('CYL', (0.0, 1.0, 0.0), tuple(c), 12.0), ((0.0, 1.0, 0.0), 12.0)]
    return []


def uv_stage():
    for tset in ("Body", "Furniture"):
        objs = set_objects(tset)
        t0 = time.time()
        UV_REPORT[tset] = {}
        L.uv_unwrap(objs, angle=UV_ANGLE, island_margin=0.002, pack_margin=UV_PACK_MARGIN,
                    scale_fn=uv_scale_policy, tex_size=TEX_SIZE, protect_materials=("IV7_Paint", "IV7_Engrave"),
                    planar_fn=uv_planar_policy, report=UV_REPORT[tset])
        L.log(f"uv {tset}: {len(objs)} objects {time.time() - t0:.1f}s")
    for p in PARTS.values():
        if p["set"] is None:
            L.uv_simple(p["obj"])


ISOLATED_PARTS = ["DustCover", "ChargingHandle", "BoltCarrier", "Selector", "BoltCatch", "Trigger",
                  "MagRelease", "RearSightLeaf", "FrontSightLeaf"]


def bake_stage():
    # moving parts are baked apart from the weapon: they neither receive nor cast inter-part AO /
    # cavity dirt, so no pose shows an occlusion "ghost" (e.g. the dust cover closed, the selector
    # on AUTO, a dropped magazine)
    iso = [[PARTS["Magazine"]["obj"], PARTS["MagRounds"]["obj"]]] + \
          [[PARTS[n]["obj"]] for n in ISOLATED_PARTS]
    samp_mask = 12 if QUICK else 24
    samp_final = 4 if QUICK else 8
    res = {}
    res["Body"] = L.bake_texture_set("Body", set_objects("Body"), MAT["masks_body"], TEX_DIR, "T_IV7_",
                                     size=TEX_SIZE, mask_samples=samp_mask, final_samples=samp_final,
                                     margin=8 if QUICK else 16, isolate=iso)
    res["Furniture"] = L.bake_texture_set("Furniture", set_objects("Furniture"), MAT["masks_furn"], TEX_DIR,
                                          "T_IV7_", size=TEX_SIZE, mask_samples=samp_mask,
                                          final_samples=samp_final, margin=8 if QUICK else 16, isolate=iso)
    # swap procedural materials for export materials that reference the baked images only
    for tset, paths in res.items():
        em = L.export_material(f"M_IV7_{tset}", paths["BaseColor"], paths["ORM"], paths["Normal"])
        MAT["export_" + tset] = em
        L.swap_to_export_material(set_objects(tset), em)
    with open(os.path.join(TEX_DIR, "bake_manifest.json"), "w") as f:
        json.dump({k: {kk: os.path.relpath(vv, PROJECT) for kk, vv in v.items()} for k, v in res.items()}, f,
                  indent=2)
    return res


def purge_procedural():
    """Remove everything procedural that the export materials no longer use (clean .blend):
    procedural materials, mask node groups, generated mask / bake images, orphan cutter meshes,
    and the generator-only 'iv_contact' attribute.  Purged recursively until nothing is left
    (a single pass left IV7_Brass / IV7_Copper alive through an orphan mesh)."""
    remove_contact()
    for _ in range(4):
        n = bpy.data.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)
        if not n:
            break


# ============================================================================ LODs / static magazine
LOD_RATIOS = {1: 0.5, 2: 0.2}
LOD_OBJS = {1: [], 2: []}


def lod_stage(arm):
    for lvl, ratio in LOD_RATIOS.items():
        col = L.collection(f"IV7_LOD{lvl}")
        for name, p in PARTS.items():
            src = p["obj"]
            nt = L.tri_count(src)
            # tiny parts keep a floor so they do not collapse into slivers
            floor = 12 if lvl == 2 else 24
            o = L.make_lod(src, ratio, f"{name}_LOD{lvl}", col, sharp_angle=50.0, min_faces=min(nt, floor))
            o.parent = arm
            o.matrix_parent_inverse = arm.matrix_world.inverted()
            if not any(m.type == 'ARMATURE' for m in o.modifiers):
                m = o.modifiers.new("Armature", 'ARMATURE'); m.object = arm
            LOD_OBJS[lvl].append(o)
        col.hide_render = True
        L.log(f"LOD{lvl}: {sum(L.tri_count(o) for o in LOD_OBJS[lvl])} tris")


SM_MAG = "SM_IV7_Magazine"


def static_magazine():
    """Stand-alone magazine static mesh (same Furniture texture set), pivot = magazine catch,
    placed at the world origin (Unreal bakes the FBX node transform into static meshes).
    Built from copies of the skinned Magazine + MagRounds meshes, so topology, UVs and the baked
    custom normals are identical to LOD0; no vertex groups or deform weights are left on it."""
    col = L.collection("IV7_Static")
    copies = []
    for src in (PARTS["Magazine"]["obj"], PARTS["MagRounds"]["obj"]):
        ob = bpy.data.objects.new(src.name + "_sm", src.data.copy())
        col.objects.link(ob)
        ob.data.transform(src.matrix_world)           # translation only (origin at the pivot)
        copies.append(ob)
    ob = L.join(copies, SM_MAG)
    ob.data.name = SM_MAG
    ob.data.transform(Matrix.Translation(-W(*MAG_PIVOT)))
    # drop the deform weights that came with the copied mesh data (the object has no groups, so
    # they would dangle): re-create the group, then remove it together with its weights
    vg = ob.vertex_groups.new(name="magazine")
    ob.vertex_groups.remove(vg)
    ob.data.materials.clear()
    ob.data.materials.append(MAT["export_Furniture"])
    for pl in ob.data.polygons:
        pl.material_index = 0
    col.hide_render = True
    return ob


# ============================================================================ measurements
def _verts_bore(obj):
    """World vertices of obj converted back to bore-frame cm."""
    mw = obj.matrix_world
    out = []
    for v in obj.data.vertices:
        w = mw @ v.co
        out.append(Vector((w.x * 100 + HOLD.x, w.y * 100 + HOLD.y, w.z * 100 + HOLD.z)))
    return out


def measure():
    P = {k: v["obj"] for k, v in PARTS.items()}
    lod0 = list(P.values())
    mn, mx = L.world_bbox_fast(lod0)
    no_optic = [o for n, o in P.items() if not n.startswith("Optic")]
    mn2, mx2 = L.world_bbox_fast(no_optic)
    bv = _verts_bore(P["Barrel"])
    b_max = max(v.x for v in bv)

    def radius_at(obj, x):
        """Outer radius of a mesh at station x: max distance from the bore axis of all
        edge / plane(x) intersection points (exact for any mesh)."""
        vs = _verts_bore(obj)
        best = 0.0
        for e in obj.data.edges:
            a_, b_ = vs[e.vertices[0]], vs[e.vertices[1]]
            if (a_.x - x) * (b_.x - x) > 0 or abs(b_.x - a_.x) < 1e-9:
                continue
            t = (x - a_.x) / (b_.x - a_.x)
            pnt = a_.lerp(b_, t)
            best = max(best, math.hypot(pnt.y, pnt.z))
        return best
    mv = _verts_bore(P["MuzzleDevice"])
    hv = _verts_bore(P["Handguard"])
    rail_w = max(abs(v.y) for v in hv if v.z > 2.5) * 2
    fs = _verts_bore(P["FrontSightLeaf"])
    post_tip = max(v.z for v in fs if abs(v.y) < 0.15)
    lr = _verts_bore(P["OpticLensRear"])
    lens_c = sum((v for v in lr), Vector()) / len(lr)
    lens_rear_face = min(v.x for v in lr)
    rs = _verts_bore(P["RearSightLeaf"])
    # aperture bore: vertices 0.45 cm (+-0.03) from the sight line (the post below is excluded)
    ring = [v for v in rs if abs(math.hypot(v.y, v.z - SIGHT_Z) - 0.45) < 0.03]
    # trigger reach: web of the hand (grip back strap) to the trigger face at finger height
    zf = -5.67
    tv = _verts_bore(P["Trigger"])
    trig_face = max(v.x for v in tv if abs(v.z - zf) < 0.15)
    back = min(v.x for v in _verts_bore(P["PistolGrip"]) if abs(v.z - zf) < 0.15)
    butt = min(v.x for v in _verts_bore(P["ButtPad"]))
    mg = _verts_bore(P["Magazine"])
    top = [v for v in mg if -7.0 < v.z < -3.0]
    arc = MAG_BODY_LEN - MAG_STRAIGHT
    mag_centerline = (MAG_TOP_BODY - (-1.33)) * -1 + MAG_STRAIGHT + arc + 0.55
    gv = _verts_bore(P["PistolGrip"])
    d = {
        "overall_length_cm": round((mx.x - mn.x) * 100, 2),
        "height_with_magazine_and_optic_cm": round((mx.z - mn.z) * 100, 2),
        "height_with_magazine_without_optic_cm": round((mx2.z - mn2.z) * 100, 2),
        "width_max_cm": round((mx.y - mn.y) * 100, 2),
        "barrel_length_from_bolt_face_cm": round(b_max - 0.0, 2),
        "barrel_od_cm": {"x=8": round(2 * radius_at(P["Barrel"], 8.0), 3),
                         "x=20 (gas block journal, hidden)": round(2 * radius_at(P["Barrel"], 20.0), 3),
                         "x=30": round(2 * radius_at(P["Barrel"], 30.0), 3)},
        "muzzle_device_length_cm": round(max(v.x for v in mv) - min(v.x for v in mv), 2),
        "muzzle_device_od_cm": round(2 * max(math.hypot(v.y, v.z) for v in mv), 3),
        "handguard_length_cm": round(max(v.x for v in hv) - min(v.x for v in hv), 2),
        "handguard_width_cm": round(max(v.y for v in hv) - min(v.y for v in hv), 2),
        "rail_max_width_mm": round(rail_w * 10, 2),
        "rail_slot_pitch_mm": 10.0,
        "rail_top_above_bore_cm": round(max(v.z for v in hv), 3),
        "optic_axis_above_bore_cm": round(lens_c.z, 3),
        "front_post_tip_above_bore_cm": round(post_tip, 3),
        "rear_aperture_centre_above_bore_cm": round(sum(v.z for v in ring) / len(ring), 3) if ring else None,
        "socket_ads_behind_rear_lens_cm": round(lens_rear_face - ADS_EYE_X, 3),
        "grip_rake_deg": GRIP_RAKE,
        "grip_length_along_axis_cm": GRIP_LEN,
        "grip_hold_point_below_bore_cm": round(-HOLD.z, 3),
        "trigger_reach_cm": round(trig_face - back, 2),
        "length_of_pull_cm": round(trig_face - butt, 2),
        "bolt_face_to_butt_cm": round(0.0 - butt, 2),
        "charging_handle": {"length_cm": round(max(v.x for v in _verts_bore(P["ChargingHandle"])) -
                                               min(v.x for v in _verts_bore(P["ChargingHandle"])), 2),
                            "stroke_cm": CH_STROKE,
                            "engaged_in_receiver_at_full_stroke_cm": round((CH_SHAFT_X1 - CH_STROKE) - UP_X0, 2)},
        "magwell_front_wall_mm": round((-0.25 - (-0.85)) * 10, 1),
        "magazine_pivot_on_catch_axis": [MAG_PIVOT[0] == MR_C[0], MAG_PIVOT[2] == MR_C[1]],
        "magazine_centerline_length_cm": round(mag_centerline, 2),
        "magazine_body_width_cm": round(max(v.y for v in top) - min(v.y for v in top), 3),
        "magazine_body_depth_cm": round(max(v.x for v in top) - min(v.x for v in top), 3),
        "grip_width_max_cm": round(max(v.y for v in gv) - min(v.y for v in gv), 3),
        "bore_axis_in_final_frame_cm": [round(-HOLD.x, 3), 0.0, round(-HOLD.z, 3)],
        "note": ("all values measured from the built meshes except rake / grip length / rail pitch / "
                 "magwell front wall / charging-handle stroke (design inputs)"),
    }
    return d


# ============================================================================ validation
# parts that are legitimately several separate shells; every other part must be ONE shell
MULTI_SHELL = {"Pins": 4, "HandguardScrews": 2, "MagRounds": 2, "SM_IV7_Magazine": 3}


def validate_stage(arm, sm):
    lod0 = [p["obj"] for p in PARTS.values()]
    sets = {"Body": {"objects": set_objects("Body"), "size": TEX_SIZE},
            "Furniture": {"objects": set_objects("Furniture"), "size": TEX_SIZE}}
    extra = {
        "asset": "IV-7 carbine",
        "measurements": measure(),
        "triangles": {
            "LOD0": sum(L.tri_count(o) for o in lod0),
            "LOD1": sum(L.tri_count(o) for o in LOD_OBJS[1]),
            "LOD2": sum(L.tri_count(o) for o in LOD_OBJS[2]),
            "SM_IV7_Magazine": L.tri_count(sm),
            "per_part_LOD0": {o.name: L.tri_count(o) for o in sorted(lod0, key=lambda o: -L.tri_count(o))},
        },
        "parts": {n: {"texture_set": p["set"], "bone": p["bone"]} for n, p in PARTS.items()},
    }
    extra["uv_unwrap"] = UV_REPORT
    rep = L.validate(os.path.join(PREV_DIR, "IV7_validation.json"), lod0 + LOD_OBJS[1] + LOD_OBJS[2] + [sm],
                     arm, sets, extra, shells=MULTI_SHELL, max_zero_uv_face_mm2=0.05)
    return rep


# ============================================================================ export / reimport
EXPORTS = {}


GLTF_DIR = os.path.join(GLB_DIR, "IV7")      # shared-texture glTF set


def export_stage():
    """FBX for Unreal (LOD0 / LOD1 / LOD2 skeletal + magazine static), one self-contained GLB of
    LOD0 (the browser build loads this single file) and a glTF set (LOD0/1/2 + magazine) whose
    .gltf files all reference ONE shared copy of the textures in GLB/IV7/textures/."""
    names0 = [ARM_NAME] + list(PARTS.keys())
    n1 = [ARM_NAME] + [o.name for o in LOD_OBJS[1]]
    n2 = [ARM_NAME] + [o.name for o in LOD_OBJS[2]]
    jobs = [
        ("FBX", os.path.join(FBX_DIR, "SK_IV7_Carbine.fbx"), names0, ["ARMATURE", "MESH"]),
        ("FBX", os.path.join(FBX_DIR, "SK_IV7_Carbine_LOD1.fbx"), n1, ["ARMATURE", "MESH"]),
        ("FBX", os.path.join(FBX_DIR, "SK_IV7_Carbine_LOD2.fbx"), n2, ["ARMATURE", "MESH"]),
        ("FBX", os.path.join(FBX_DIR, "SM_IV7_Magazine.fbx"), [SM_MAG], ["MESH"]),
        ("GLB", os.path.join(GLB_DIR, "IV7_Carbine.glb"), names0, None),
        ("GLB", os.path.join(GLTF_DIR, "IV7_Carbine.gltf"), names0, None),
        ("GLB", os.path.join(GLTF_DIR, "IV7_Carbine_LOD1.gltf"), n1, None),
        ("GLB", os.path.join(GLTF_DIR, "IV7_Carbine_LOD2.gltf"), n2, None),
        ("GLB", os.path.join(GLTF_DIR, "IV7_Magazine.gltf"), [SM_MAG], None),
    ]
    # the per-LOD GLBs of earlier builds each embedded the same 12 MB of textures: replaced by
    # the shared-texture glTF set
    for old in ("IV7_Carbine_LOD1.glb", "IV7_Carbine_LOD2.glb", "IV7_Magazine.glb"):
        if os.path.exists(os.path.join(GLB_DIR, old)):
            os.remove(os.path.join(GLB_DIR, old))
    os.makedirs(GLTF_DIR, exist_ok=True)
    for fmt, path, names, types in jobs:
        t0 = time.time()
        if fmt == "FBX":
            r = L.export_fbx(BLEND, names, path, object_types=types)
        else:
            r = L.export_glb(BLEND, names, path, texture_dir="textures")
        nbytes = r["bytes"]
        if path.endswith(".gltf"):
            b = os.path.splitext(path)[0] + ".bin"
            nbytes += os.path.getsize(b) if os.path.exists(b) else 0
        EXPORTS[path] = {"format": "glTF (separate, shared textures)" if path.endswith(".gltf") else fmt,
                         "objects": len(names), "bytes": nbytes}
        L.log(f"export {os.path.basename(path)} {nbytes / 1e6:.2f} MB {time.time() - t0:.1f}s")
    tex = os.path.join(GLTF_DIR, "textures")
    if os.path.isdir(tex):
        EXPORTS[os.path.join(tex, "")] = {"format": "shared PNG textures of the glTF set",
                                          "files": sorted(os.listdir(tex)),
                                          "bytes": sum(os.path.getsize(os.path.join(tex, f)) for f in os.listdir(tex))}


def reimport_stage(arm, sm):
    results = {}
    lod0 = [p["obj"] for p in PARTS.values()]
    ref = {
        "SK_IV7_Carbine": (lod0, len(lod0)),
        "SK_IV7_Carbine_LOD1": (LOD_OBJS[1], len(LOD_OBJS[1])),
        "SK_IV7_Carbine_LOD2": (LOD_OBJS[2], len(LOD_OBJS[2])),
        "IV7_Carbine": (lod0, len(lod0)),
        "IV7_Carbine_LOD1": (LOD_OBJS[1], len(LOD_OBJS[1])),
        "IV7_Carbine_LOD2": (LOD_OBJS[2], len(LOD_OBJS[2])),
        "SM_IV7_Magazine": ([sm], 1),
        "IV7_Magazine": ([sm], 1),
    }
    paths = [p for p in EXPORTS if not p.endswith(os.sep)] if EXPORTS else \
        [os.path.join(FBX_DIR, f) for f in sorted(os.listdir(FBX_DIR)) if f.startswith(("SK_IV7", "SM_IV7"))] + \
        [os.path.join(GLB_DIR, f) for f in sorted(os.listdir(GLB_DIR)) if f.startswith("IV7") and f.endswith(".glb")] + \
        ([os.path.join(GLTF_DIR, f) for f in sorted(os.listdir(GLTF_DIR)) if f.endswith(".gltf")]
         if os.path.isdir(GLTF_DIR) else [])
    for path in paths:
        base = os.path.splitext(os.path.basename(path))[0]
        objs, n_expected = ref[base]
        mn, mx = L.world_bbox_fast(objs)
        src_dims = [round((mx[i] - mn[i]) * 100, 2) for i in range(3)]
        r = L.reimport_check(path)
        dims_ok = all(abs(a - b) <= max(0.05, 0.005 * b) for a, b in zip(r["dimensions_cm"], src_dims))
        skinned = not base.endswith("Magazine")
        bones_ok = (r["bone_count"] == len(BONES)) if skinned else (r["bone_count"] == 0)
        mats = r["materials"]
        images_ok = all(im["exists_or_packed"] for ims in mats.values() for im in ims)
        tex_mats = [m for m in mats if m.startswith(("M_IV7_Body", "M_IV7_Furniture"))]
        tex_ok = all(len(mats[m]) >= 2 for m in tex_mats) and len(tex_mats) >= 1
        mesh_ok = r["mesh_objects"] == n_expected
        key = os.path.relpath(path, PROJECT)
        results[key] = {
            "result": "PASS" if (dims_ok and bones_ok and images_ok and tex_ok and mesh_ok and r["vertex_groups_match_bones"]) else "FAIL",
            "source_dimensions_cm": src_dims, "reimport_dimensions_cm": r["dimensions_cm"], "dims_ok": dims_ok,
            "mesh_objects": r["mesh_objects"], "mesh_objects_expected": n_expected, "bone_count": r["bone_count"],
            "bones_ok": bones_ok, "armature_object_scale_after_import": r["armature_object_scale"],
            "tris": r["tris"], "materials": {m: [os.path.basename(i["path"]) or i["name"] for i in ims] for m, ims in mats.items()},
            "images_resolved": images_ok, "textured_materials_ok": tex_ok,
            "vertex_groups_match_bones": r["vertex_groups_match_bones"],
            "importer": "Blender stock io_scene_fbx / io_scene_gltf2 (not Unreal)",
        }
        results[key]["file"] = os.path.basename(path)
        L.log(f"reimport {os.path.basename(path)}: {results[key]['result']}")
    vp = os.path.join(PREV_DIR, "IV7_validation.json")
    rep = json.load(open(vp)) if os.path.exists(vp) else {}
    rep["reimport_checks"] = results
    rep["exports"] = {os.path.relpath(k, PROJECT): v for k, v in EXPORTS.items()}
    json.dump(rep, open(vp, "w"), indent=2)
    return results


# ============================================================================ renders
RENDER_NAMES = ["ortho_right", "ortho_left", "ortho_top", "ortho_front", "persp_front_right", "persp_rear_left",
                "closeup_receiver_right", "closeup_receiver_left", "first_person", "ads", "clay_right",
                "shade_right", "lods", "magazine", "rig_pose_test", "contact_sheet"]

# pose used by the rig test render: bone -> (location m in bone space, rotation deg about bone X/Y/Z)
# bone axes are world aligned: local X = weapon forward, Y = weapon left, Z = up
TEST_POSE = {
    "dust_cover": ((0, 0, 0), (-DUST_ANGLE, 0, 0)),         # closed
    "bolt_carrier": ((-0.075, 0, 0), (0, 0, 0)),             # carrier to the rear
    "charging_handle": ((-CH_STROKE * 0.01, 0, 0), (0, 0, 0)),  # pulled (full 7 cm stroke)
    "trigger": ((0, 0, 0), (0, 12.0, 0)),                    # pressed
    "selector": ((0, 0, 0), (0, 90.0, 0)),                   # SEMI
    "bolt_catch": ((0, 0, 0), (0, -9.0, 0)),                 # engaged (paddle up)
    "mag_release": ((0, 0.0015, 0), (0, 0, 0)),              # pressed in
    "magazine": ((0.004, 0, -0.07), (0, -6.0, 0)),           # dropping out
    "rear_sight": ((0, 0, 0), (0, -90.0, 0)),                # folded rearward
    "front_sight": ((0, 0, 0), (0, -90.0, 0)),               # folded rearward
}
RENDERS = [r for r in os.environ.get("IV_RENDERS", ",".join(RENDER_NAMES)).split(",") if r]
RES = (800, 450) if QUICK else (1600, 900)
SAMPLES = 24 if QUICK else 128


def _col_render(name, visible):
    c = bpy.data.collections.get(name)
    if c:
        c.hide_render = not visible


def _only(collection_name):
    for n in ("IV7_Parts", "IV7_LOD1", "IV7_LOD2", "IV7_Static", "IV7_Env"):
        _col_render(n, n == collection_name or (n == "IV7_Env" and collection_name == "IV7_Parts+Env"))
    if collection_name == "IV7_Parts+Env":
        _col_render("IV7_Parts", True)


def _clear_env():
    L.clear_lights_cameras()
    env = bpy.data.collections.get("IV7_Env")
    if env:
        for o in list(env.objects):
            bpy.data.objects.remove(o, do_unlink=True)


def env_studio():
    _clear_env()
    objs = [p["obj"] for p in PARTS.values()]
    mn, mx = L.world_bbox_fast(objs)
    c = (mn + mx) / 2
    L.studio_lighting(c, (mx - mn).length / 2)
    return mn, mx, c


def _ground_material():
    m, nb, bsdf = L._new_material("IV7_Env_Ground")
    co = nb.coords('Object')
    n1 = nb.noise(co, 0.6, 4.0, 0.6, 1.0)
    n2 = nb.noise(co, 7.0, 6.0, 0.65, 2.0)
    col = nb.ramp(nb.add(nb.mul(n1, 0.6), nb.mul(n2, 0.4)),
                  [(0.35, (0.10, 0.085, 0.06)), (0.5, (0.16, 0.14, 0.10)), (0.62, (0.075, 0.095, 0.045))])
    nb.set(bsdf.inputs['Base Color'], col)
    nb.set(bsdf.inputs['Roughness'], 0.92)
    nb.set(bsdf.inputs['Normal'], nb.bump(nb.noise(co, 40.0, 4.0, 0.6, 3.0), 0.4, 0.02))
    return m


def _target_material():
    m, nb, bsdf = L._new_material("IV7_Env_Target")
    gen = nb.coords('Generated')
    x, y, z = nb.xyz(gen)
    dx = nb.sub(y, 0.5); dz = nb.sub(z, 0.5)
    r = nb.math('SQRT', nb.add(nb.mul(dx, dx), nb.mul(dz, dz)))
    rings = nb.math('MODULO', r, 0.08)
    ringm = nb.remap(rings, 0.0, 0.012)
    bull = nb.remap(r, 0.05, 0.055)
    v = nb.mul(ringm, bull)
    col = nb.ramp(v, [(0.0, (0.02, 0.02, 0.02)), (1.0, (0.75, 0.72, 0.65))])
    nb.set(bsdf.inputs['Base Color'], col)
    nb.set(bsdf.inputs['Roughness'], 0.85)
    return m


def env_outdoor(sun=True, elevation=38.0, rotation=-35.0, ground_z=None, target=False, sky_strength=0.28,
                sun_strength=4.2):
    _clear_env()
    col = L.collection("IV7_Env")
    L.world_sky(sun_elevation=elevation, sun_rotation=rotation, strength=sky_strength, sun_disc=False)
    if sun:
        L.add_sun(elevation, rotation, sun_strength, angle=0.55)
    gz = ground_z if ground_z is not None else W(0, 0, 13.5).z - 1.62
    gm = _ground_material()
    g = L.box("IV7_Ground", -200, 200, -200, 200, gz - 0.2, gz)
    g.data.materials.append(gm)
    L.link_to(g, col)
    if target:
        eye = W(ADS_EYE_X, 0.0, SIGHT_Z)
        tm = _target_material()
        board = L.box("IV7_Target", eye.x + 25.0, eye.x + 25.03, -0.6, 0.6, eye.z - 0.6, eye.z + 0.6)
        board.data.materials.append(tm)
        L.link_to(board, col)
        for yy in (-0.5, 0.5):
            post = L.box("IV7_TargetPost", eye.x + 25.04, eye.x + 25.1, yy - 0.03, yy + 0.03, gz, eye.z - 0.55)
            post.data.materials.append(gm)
            L.link_to(post, col)
    return gz


def _r(name):
    return os.path.join(PREV_DIR, f"IV7_{name}.png")


def render_stage(arm, sm):
    bpy.context.view_layer.material_override = None
    arm.hide_render = True
    done = []
    samples = SAMPLES
    if any(r.startswith(("ortho", "persp", "closeup", "clay")) for r in RENDERS):
        mn, mx, c = env_studio()
        _only("IV7_Parts")
        for v in ("right", "left", "top", "front"):
            if f"ortho_{v}" in RENDERS:
                cam = L.camera_ortho("cam", v.upper(), mn, mx, margin=1.06 if v in ("right", "left", "top") else 1.25)
                done.append(L.render(_r(f"ortho_{v}"), cam, RES, samples))
        if "persp_front_right" in RENDERS:
            cam = L.camera("cam", c + Vector((0.62, -0.78, 0.30)), c + Vector((0.03, 0, -0.03)), fov_deg=36)
            done.append(L.render(_r("persp_front_right"), cam, RES, samples))
        if "persp_rear_left" in RENDERS:
            cam = L.camera("cam", c + Vector((-0.66, 0.74, 0.30)), c + Vector((-0.02, 0, -0.03)), fov_deg=36)
            done.append(L.render(_r("persp_rear_left"), cam, RES, samples))
        if "closeup_receiver_right" in RENDERS:
            t = W(-6.5, 0, -3.2)
            cam = L.camera("cam", t + Vector((0.07, -0.33, 0.07)), t, fov_deg=34)
            done.append(L.render(_r("closeup_receiver_right"), cam, RES, samples))
        if "closeup_receiver_left" in RENDERS:
            t = W(-8.0, 0, -3.4)
            cam = L.camera("cam", t + Vector((0.04, 0.32, 0.06)), t, fov_deg=34)
            done.append(L.render(_r("closeup_receiver_left"), cam, RES, samples))
        if "clay_right" in RENDERS:
            L.clay_override(True)
            cam = L.camera_ortho("cam", "RIGHT", mn, mx, margin=1.06)
            done.append(L.render(_r("clay_right"), cam, RES, samples))
            L.clay_override(False)
    if "first_person" in RENDERS:
        env_outdoor(sun=True, elevation=40.0, rotation=-35.0)
        _only("IV7_Parts+Env")
        eye = W(-23.0, 9.5, 11.0)
        cam = L.camera("cam", eye, W(250.0, 1.0, -16.0), fov_deg=80, clip_start=0.01, clip_end=500)
        done.append(L.render(_r("first_person"), cam, RES, int(samples * 1.5)))
    if "ads" in RENDERS:
        env_outdoor(sun=True, elevation=40.0, rotation=-35.0, target=True)
        _only("IV7_Parts+Env")
        eye = W(ADS_EYE_X, 0.0, SIGHT_Z)
        cam = L.camera("cam", eye, eye + Vector((10.0, 0.0, 0.0)), fov_deg=42, clip_start=0.005, clip_end=500)
        done.append(L.render(_r("ads"), cam, RES, int(samples * 1.5)))
    if "shade_right" in RENDERS:
        objs = [p["obj"] for p in PARTS.values()]
        mn, mx = L.world_bbox_fast(objs)
        env_outdoor(sun=False, ground_z=mn.z - 1.2, sky_strength=0.9)
        _only("IV7_Parts+Env")
        cam = L.camera_ortho("cam", "RIGHT", mn, mx, margin=1.06)
        done.append(L.render(_r("shade_right"), cam, RES, samples))
    if "lods" in RENDERS:
        mn, mx, c = env_studio()
        paths = []
        for lvl, coll in ((0, "IV7_Parts"), (1, "IV7_LOD1"), (2, "IV7_LOD2")):
            _only(coll)
            cam = L.camera("cam", c + Vector((1.1, -2.2, 0.55)), c, fov_deg=20)
            paths.append(L.render(_r(f"lod{lvl}_mid"), cam, (RES[0] // 2, RES[1] // 2), samples))
        tris = [sum(L.tri_count(p["obj"]) for p in PARTS.values()), sum(L.tri_count(o) for o in LOD_OBJS[1]),
                sum(L.tri_count(o) for o in LOD_OBJS[2])]
        L.side_by_side(paths, _r("lods"), [f"LOD{i}  {t} tris  (~2.5 m, 20 deg FOV)" for i, t in enumerate(tris)])
        done.append(_r("lods"))
        _only("IV7_Parts")
    if "magazine" in RENDERS:
        _clear_env()
        _only("IV7_Static")
        mn, mx = L.world_bbox_fast([sm])
        c = (mn + mx) / 2
        L.studio_lighting(c, (mx - mn).length / 2)
        cam = L.camera("cam", c + Vector((0.34, -0.46, 0.2)), c, fov_deg=34)
        done.append(L.render(_r("magazine"), cam, RES, samples))
        cam = L.camera("cam", c + Vector((0.16, -0.1, 0.24)) + Vector((0, 0, 0.06)), c + Vector((0.0, 0.0, 0.06)), fov_deg=30)
        done.append(L.render(_r("magazine_top"), cam, RES, samples))
        _only("IV7_Parts")
    if "rig_pose_test" in RENDERS:
        mn, mx, c = env_studio()
        _only("IV7_Parts")
        arm.hide_render = True
        for bn, (loc, rot) in TEST_POSE.items():
            pb = arm.pose.bones[bn]
            pb.rotation_mode = 'XYZ'
            pb.location = loc
            pb.rotation_euler = [math.radians(a) for a in rot]
        bpy.context.view_layer.update()
        t = W(-6.0, 0, -2.5)
        cam = L.camera("cam", t + Vector((0.10, -0.42, 0.12)), t, fov_deg=40)
        p1 = L.render(_r("rig_pose_test_right"), cam, RES, samples)
        cam = L.camera("cam", t + Vector((0.06, 0.42, 0.12)), t, fov_deg=40)
        p2 = L.render(_r("rig_pose_test_left"), cam, RES, samples)
        for pb in arm.pose.bones:
            pb.location = (0, 0, 0); pb.rotation_euler = (0, 0, 0)
        bpy.context.view_layer.update()
        L.side_by_side([p1, p2], _r("rig_pose_test"), ["pose test (right): dust cover closed, carrier 7.5 + charging handle 7 cm back, trigger pressed, mag dropping, sights folded rearward",
                                                        "pose test (left): selector SEMI, bolt catch up"])
        done.append(_r("rig_pose_test"))
    if "contact_sheet" in RENDERS:
        items = []
        for tset in ("Body", "Furniture"):
            for ch in ("BaseColor", "Normal", "Normal_DX", "ORM"):
                items.append((os.path.join(TEX_DIR, f"T_IV7_{tset}_{ch}.png"), f"T_IV7_{tset}_{ch}"))
        L.contact_sheet(items, _r("texture_contact_sheet"), thumb=512, cols=4,
                        title=f"IV-7 texture sets ({TEX_SIZE}px): BaseColor sRGB | Normal OpenGL | Normal DirectX | ORM (R AO, G rough, B metal)")
        done.append(_r("texture_contact_sheet"))
    return done


# ============================================================================ main
def load_existing_textures():
    for tset in ("Body", "Furniture"):
        base = os.path.join(TEX_DIR, f"T_IV7_{tset}")
        em = L.export_material(f"M_IV7_{tset}", base + "_BaseColor.png", base + "_ORM.png", base + "_Normal.png")
        MAT["export_" + tset] = em
        L.swap_to_export_material(set_objects(tset), em)


def main():
    t0 = time.time()
    for d in (TEX_DIR, FBX_DIR, GLB_DIR, PREV_DIR):
        os.makedirs(d, exist_ok=True)
    L.log(f"IV-7 build  quick={QUICK}  stages={STAGES}  tex={TEX_SIZE}")
    L.reset_scene()
    build()
    arm = rig()
    uv_stage()
    if "bake" in STAGES:
        bake_stage()
    else:
        load_existing_textures()
    purge_procedural()
    lod_stage(arm)
    sm = static_magazine()
    for n in ("IV7_LOD1", "IV7_LOD2", "IV7_Static"):
        bpy.data.collections[n].hide_viewport = True
    bpy.context.scene.frame_set(1)
    if "save" in STAGES:
        bpy.context.preferences.filepaths.save_version = 0     # no .blend1 backups
        bpy.ops.wm.save_as_mainfile(filepath=BLEND)
        try:
            bpy.ops.file.make_paths_relative()
            bpy.ops.wm.save_mainfile()
        except Exception as e:     # noqa: BLE001
            L.log("make_paths_relative failed:", e)
    if "validate" in STAGES:
        validate_stage(arm, sm)
    if "export" in STAGES:
        export_stage()
    if "reimport" in STAGES:
        reimport_stage(arm, sm)
    if "render" in STAGES:
        render_stage(arm, sm)
    L.log(f"IV-7 done in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
