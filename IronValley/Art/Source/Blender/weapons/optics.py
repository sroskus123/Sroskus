#!/usr/bin/env python3
"""
IRON VALLEY optics set -- generator (original designs, no real brands).

    python3 /home/user/Sroskus/IronValley/Art/Source/Blender/weapons/optics.py

  IV-H1  holographic sight 1x   (65 MOA ring + 1 MOA dot)
  IV-R1  compact red dot 1x     (2 MOA dot; the IV-7's optic as a stand-alone asset)
  IV-P2  compact prism 2x       (etched, illuminated chevron + BDC)
  IV-S3  compact scope 3x       (illuminated dot + mil hash marks, capped turrets)
  IV-S6  long-range scope 6x40  (mil-dot / duplex, holdover ladder, exposed turrets, cantilever mount)

Every optic is a separate static asset that mounts on the IV-7 upper rail (generic 21 mm dovetail,
10 mm slot pitch).  Lenses are thin coated glass sheets (alpha blend + reflection, no transmission /
refraction); reticles are high-resolution vector-rasterised textures on a dedicated reticle plane
(Art/Textures/Optics/<ID>/).  Reference and all numbers: Art/Reference/OPTICS_spec.md.

Deterministic; saves optics.blend next to this script.  The IV-7 is imported READ-ONLY for renders.

Environment switches:
    IV_QUICK=1          1024 textures, low samples, half-size renders (iteration only)
    IV_OPTICS=IVH1,...  subset of optics (default: all)
    IV_STAGES=a,b,...   reticles,bake,save,validate,export,reimport,render,config (default: all);
                        'review' = quick procedural-material renders of the bare optics only
    IV_RENDERS=a,b,...  subset of render names (see render_stage)

Authoring frame (per optic, centimetres): origin = socket_rail = rail top centre line at the front
edge of the (front) rail clamp; X forward (muzzle), Y left, Z up, rail top at z = 0.  finalize()
converts to metres.  Weapon convention: muzzle +X, top +Z, right side -Y.
"""

import os
import sys
import math
import json
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "lib")))

import bpy            # noqa: E402
import bmesh          # noqa: E402
from mathutils import Vector, Matrix   # noqa: E402
import ivlib as L     # noqa: E402
import ivoptics as O  # noqa: E402

# ----------------------------------------------------------------------------- paths
PROJECT = os.path.normpath(os.path.join(HERE, "..", "..", "..", ".."))       # IronValley/
ART = os.path.join(PROJECT, "Art")
TEX_ROOT = os.path.join(ART, "Textures", "Optics")
FBX_DIR = os.path.join(ART, "Export", "FBX")
GLB_DIR = os.path.join(ART, "Export", "GLB")
PREV_DIR = os.path.join(ART, "Previews", "Optics")
BLEND = os.path.join(HERE, "optics.blend")
RIFLE_BLEND = os.path.join(HERE, "iv7_carbine.blend")
RIFLE_TEX = os.path.join(ART, "Textures", "Weapons", "IV7")
CONFIG = os.path.join(PROJECT, "Shared", "config", "optics.json")

QUICK = os.environ.get("IV_QUICK") == "1"
ALL_STAGES = ["reticles", "bake", "save", "validate", "export", "reimport", "render", "config"]
STAGES = [s for s in os.environ.get("IV_STAGES", ",".join(ALL_STAGES)).split(",") if s]
TEX_SIZE = 1024 if QUICK else 2048
ALL_IDS = ["IVH1", "IVR1", "IVP2", "IVS3", "IVS6"]
IDS = [s for s in os.environ.get("IV_OPTICS", ",".join(ALL_IDS)).split(",") if s]

# ----------------------------------------------------------------------------- design data
# x_mount: bore-frame x (cm) of socket_rail on the IV-7 (front edge of the clamp); lugs: recoil-lug
# (cross-bolt) x in the optic frame -- each must land on a rail cross-slot centre.
SPEC = {
    "IVH1": dict(model="IV-H1", file="IVH1_Holo", kind="holographic", mag=1.0,
                 name_cs="Holografický zaměřovač IV-H1", short_cs="Holo 1×",
                 axis_h=4.0, x_mount=1.7, lugs=[-2.3], eye_relief=9.0),
    "IVR1": dict(model="IV-R1", file="IVR1_RedDot", kind="red_dot", mag=1.0,
                 name_cs="Kolimátor IV-R1", short_cs="Kolimátor 1×",
                 axis_h=4.0, x_mount=-1.8, lugs=[-1.8], eye_relief=8.0),
}

AXIS = {k: v["axis_h"] for k, v in SPEC.items()}
PARTS = {}          # oid -> {name: {"obj", "contact"}}
EXTRA = {}          # oid -> {"glass": [objs], "reticle": obj, "sockets": {name: obj}, "points": {...}}
MAT = {}            # oid -> {key: material}
COLS = {}
INFO = {}           # oid -> measured / derived numbers for docs + config


def col(oid):
    if oid not in COLS:
        COLS[oid] = L.collection(oid)
    return COLS[oid]


def reg(oid, obj, key, name=None, contact=0.35):
    """Register a Body-texture-set part of optic `oid` (material key from MAT[oid])."""
    name = name or obj.name
    obj.name = f"{oid}_{name}"
    obj.data.name = obj.name
    if key is not None:
        if len(obj.data.materials) == 0:
            obj.data.materials.append(MAT[oid][key])
        else:
            # keep extra slots from TRANSFER booleans; slot 0 is the base material
            obj.data.materials[0] = MAT[oid][key]
    PARTS.setdefault(oid, {})[obj.name] = {"obj": obj, "contact": contact}
    L.link_to(obj, col(oid))
    return obj


def setmat(obj, mat):
    obj.data.materials.clear()
    obj.data.materials.append(mat)
    return obj


def rot_data(obj, angle_deg, axis, pivot=(0.0, 0.0, 0.0)):
    M = (Matrix.Translation(Vector(pivot)) @ Matrix.Rotation(math.radians(angle_deg), 4, axis)
         @ Matrix.Translation(-Vector(pivot)))
    obj.data.transform(M)
    obj.data.update()
    return obj


def vgroove(axis, apex_r, base_r, hw, a0, a1):
    """90 deg V-groove cutter pointing along +v of the extrusion plane (knurl flute)."""
    return L.poly_extrude("fl", [(0.0, apex_r), (hw, base_r), (-hw, base_r)], axis, a0, a1)


def flutes(axis, center, r, n, a0, a1, depth=0.07, hw=None, phase=0.0):
    """n straight knurl flutes around a cylinder of radius r (axis 'X', 'Y' or 'Z' through
    center = the two remaining coordinates, like ivlib.lathe), spanning a0..a1 along the axis."""
    hw = hw if hw is not None else 0.8 * math.pi * r / n / 2
    out = []
    for k in range(n):
        a = phase + 360.0 * k / n
        if axis == 'Z':
            c = vgroove('Z', r - depth, r + 0.3, hw, a0, a1)          # triangle in XY pointing +Y
            rot_data(c, a, 'Z')
            c.data.transform(Matrix.Translation((center[0], center[1], 0.0)))
        elif axis == 'Y':
            c = vgroove('Y', r - depth, r + 0.3, hw, a0, a1)          # triangle in XZ pointing +Z
            rot_data(c, a, 'Y')
            c.data.transform(Matrix.Translation((center[0], 0.0, center[1])))
        else:
            c = vgroove('X', r - depth, r + 0.3, hw, a0, a1)          # triangle in YZ pointing +Z
            rot_data(c, a, 'X')
            c.data.transform(Matrix.Translation((0.0, center[0], center[1])))
        out.append(c)
    return out


def ticks(axis, center, r, n, a0, a1, major_every=5, a1_major=None, depth=0.03, w=0.035, phase=0.0,
          skip=()):
    """Engraved tick marks (thin radial grooves) around a cylinder; cutters carry no material
    (assign before cutting)."""
    out = []
    for k in range(n):
        if k in skip:
            continue
        a = phase + 360.0 * k / n
        top = a1_major if (a1_major is not None and k % major_every == 0) else a1
        if axis == 'Z':
            c = L.box("tk", -w / 2, w / 2, r - depth, r + 0.2, a0, top)
            rot_data(c, a, 'Z')
            c.data.transform(Matrix.Translation((center[0], center[1], 0.0)))
        elif axis == 'Y':
            c = L.poly_extrude("tk", [(-w / 2, r - depth), (w / 2, r - depth), (w / 2, r + 0.2), (-w / 2, r + 0.2)],
                               'Y', a0, top) if a0 < top else L.poly_extrude(
                "tk", [(-w / 2, r - depth), (w / 2, r - depth), (w / 2, r + 0.2), (-w / 2, r + 0.2)], 'Y', top, a0)
            rot_data(c, a, 'Y')
            c.data.transform(Matrix.Translation((center[0], 0.0, center[1])))
        out.append(c)
    return out


def engrave_text(oid, target, body, size, frame, depth=0.018):
    """Engrave white-filled text into a flat face.  frame = 'left' (face +Y, read from the left
    side), 'right' (face -Y), 'top' (face +Z, read from behind); plus (x, y, z) = centre on the
    face."""
    kind, (x, y, z) = frame
    if kind == 'left':
        R = Matrix(((-1, 0, 0, 0), (0, 0, 1, 0), (0, 1, 0, 0), (0, 0, 0, 1)))    # read along -X, up +Z
    elif kind == 'right':
        R = Matrix(((1, 0, 0, 0), (0, 0, -1, 0), (0, 1, 0, 0), (0, 0, 0, 1)))    # read along +X, up +Z
    else:
        R = Matrix(((0, -1, 0, 0), (1, 0, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1)))    # read along -Y, up +X
    t = O.text_mesh("txt", body, size, depth, Matrix.Translation((x, y, z)) @ R)
    setmat(t, MAT[oid]["paint"])
    L.boolean(target, [t], material_mode='TRANSFER')
    return target


# ----------------------------------------------------------------------------- materials
def build_materials(oid, seed):
    mk = L.mask_group(oid, edge_dist=0.0016, cavity_dist=0.005, ao_dist=0.02)
    M = {"masks": mk}
    # matte hard-anodised housings (optics are usually more matte than the rifle's satin receiver)
    M["body"] = L.mat_anodized(f"{oid}_Anod_Body", mk, base=(0.030, 0.030, 0.033), rough=0.47, wear=0.75,
                               scratches=0.35, seed=seed + 1)
    M["body2"] = L.mat_anodized(f"{oid}_Anod_Mount", mk, base=(0.034, 0.034, 0.036), rough=0.44, wear=0.9,
                                scratches=0.45, seed=seed + 2)
    M["knob"] = L.mat_anodized(f"{oid}_Anod_Knob", mk, base=(0.032, 0.032, 0.035), rough=0.40, wear=1.15,
                               scratches=0.5, seed=seed + 3)
    M["steel"] = L.mat_phosphate(f"{oid}_Steel_Phosphate", mk, seed=seed + 4)
    M["screw"] = L.mat_steel(f"{oid}_Steel_Screw", mk, rough=0.42, seed=seed + 5)
    M["rubber"] = L.mat_rubber(f"{oid}_Rubber", mk, base=(0.020, 0.020, 0.021), rough=0.88, seed=seed + 6)
    M["rubber_rib"] = L.mat_rubber(f"{oid}_Rubber_Ribbed", mk, base=(0.020, 0.020, 0.021), rough=0.86,
                                   seed=seed + 7, ribs={"axis": 'X', "scale": 260.0})
    M["interior"] = O.mat_black_interior(f"{oid}_Interior", mk, seed=seed + 8)
    M["paint"] = L.mat_paint(f"{oid}_Paint_White", mk, (0.62, 0.62, 0.60), rough=0.5, seed=seed + 9)
    M["paint_red"] = L.mat_paint(f"{oid}_Paint_Red", mk, (0.45, 0.03, 0.02), rough=0.5, seed=seed + 10)
    M["polymer"] = L.mat_polymer(f"{oid}_Polymer", mk, base=(0.028, 0.028, 0.029), rough=0.62, seed=seed + 11)
    MAT[oid] = M
    return M


# ============================================================================ IV-R1 red dot
def build_IVR1():
    """The IV-7's enclosed red dot (Art/Reference/IV7_carbine_spec.md, part 'Optic') moved into the
    optic frame (x_opt = x_bore + 1.8, z_opt = z_bore - 3.0).  Look and size are kept; the lenses
    become thin coated sheets, the reticle a 2 MOA texture on a plane 5.7 mm behind the front
    lens (the old 0.3 mm disc sat 0.02 mm from the lens face: z-fighting), plus a closed emitter."""
    oid = "IVR1"
    A = AXIS[oid]
    secs = []
    for x, s in ((-5.5, 0.95), (-5.25, 1.0), (0.4, 1.0), (0.75, 1.06), (1.4, 1.06)):
        sec = L.superellipse(1.8 * s, 1.8 * s, 3.0, 48, 0.0, A, phase=math.pi / 48)
        secs.append([(x, u, v) for u, v in sec])
    body = L.loft("Housing", secs)
    setmat(body, MAT[oid]["body"])
    riser = L.poly_extrude("riser", L.fillet_polygon([(-4.1, 0.6), (0.0, 0.6), (0.0, 1.2), (-0.6, 2.9), (-3.5, 2.9),
                                                      (-4.1, 1.2)], [0, 0, 0.3, 0.5, 0.5, 0.3], 6), 'Y', -1.05, 1.05)
    clamp = L.poly_extrude("clamp", O.clamp_section(1.3, 0.8), 'X', -4.1, 0.0)
    te = L.lathe("te", [(5.55, 0.0), (5.55, 0.88), (6.05, 0.88), (6.1, 0.76), (6.62, 0.76), (6.66, 0.7), (6.66, 0.0)],
                 24, 'Z', center=(-1.95, 0.0))
    tw = L.lathe("tw", [(-1.55, 0.0), (-1.55, 0.88), (-2.05, 0.88), (-2.1, 0.76), (-2.62, 0.76), (-2.66, 0.7),
                        (-2.66, 0.0)], 24, 'Y', center=(-1.95, A))
    kb = L.lathe("kb", [(1.55, 0.0), (1.55, 0.95), (2.1, 0.95), (2.16, 0.86), (2.16, 0.0)], 32, 'Y', center=(-3.1, A))
    ck = L.lathe("ck", [(-1.28, 0.55), (-1.9, 0.55), (-1.95, 0.48), (-1.95, 0.0), (-1.28, 0.0)], 28, 'Y',
                 center=(-1.8, -0.18))
    L.union(body, [riser, clamp, te, tw, kb, ck])
    bore_prof = [(-6.0, 0.0), (-6.0, 1.3), (-4.85, 1.3), (-4.85, 1.12), (-4.7, 1.12), (-4.7, 1.3), (0.5, 1.3),
                 (0.5, 1.12), (0.65, 1.12), (0.65, 1.3), (2.4, 1.3), (2.4, 0.0)]
    bore = setmat(L.lathe("bore", bore_prof, 48, 'X', center=(0.0, A)), MAT[oid]["interior"])
    L.boolean(body, [bore, L.cyl("lug", 0.19, -1.28, 2.0, 'Y', center=(-1.8, -0.18), segs=16)],
              material_mode='TRANSFER')
    L.bevel(body, 0.035, 2, 30)
    fl = []
    fl += flutes('Z', (-1.95, 0.0), 0.76, 12, 6.15, 6.75, depth=0.07, hw=0.26)           # elevation cap
    fl += flutes('Y', (-1.95, A), 0.76, 12, -2.72, -2.14, depth=0.07, hw=0.26)           # windage cap
    fl += flutes('Y', (-3.1, A), 0.95, 16, 1.58, 2.25, depth=0.08, hw=0.26)              # brightness knob
    fl.append(L.poly_extrude("cs", [(0.0, 6.58), (0.2, 6.8), (-0.2, 6.8)], 'X', -2.45, -1.45))
    c = L.poly_extrude("cs", [(0.0, -2.58), (0.2, -2.8), (-0.2, -2.8)], 'Z', A - 0.5, A + 0.5)
    c.data.transform(Matrix.Translation((-1.95, 0, 0)))
    fl.append(c)
    L.boolean(body, fl)
    engrave_text(oid, body, "IV-R1", 0.42, ('left', (-2.05, 1.05, 1.85)))
    reg(oid, body, "body", "Housing", contact=0.3)
    bolt = L.lathe("Lug", [(-1.27, 0.0), (-1.27, 0.18), (1.3, 0.18), (1.3, 0.3), (1.36, 0.3), (1.38, 0.0)], 16, 'Y',
                   center=(-1.8, -0.18))
    L.bevel(bolt, 0.012, 1, 30)
    reg(oid, bolt, "steel", "Lug", contact=0.4)
    # closed emitter: LED housing on the tube floor near the rear lens (visible from the eye side
    # through the rear lens, as in real tube sights), aimed at the front reflector
    em = L.poly_extrude("Emitter", L.fillet_polygon([(-4.45, 2.62), (-3.95, 2.62), (-3.95, 2.93), (-4.05, 3.02),
                                                     (-4.45, 3.02)], [0, 0, 0.05, 0.05, 0.05], 3), 'Y', -0.2, 0.2)
    L.bevel(em, 0.02, 1, 30)
    reg(oid, em, "interior", "Emitter", contact=0.05)
    # optics: rear lens (towards the eye), front reflector lens with a red-reflecting coating
    lens_r = 1.29
    g_rear = O.lens_sheet("LensRear", -4.99, (0.0, A), lens_r, facing=-1, sag=0.03)
    g_front = O.lens_sheet("LensFront", 0.77, (0.0, A), lens_r, facing=+1, sag=0.09)
    return {"glass": [(g_rear, "glass_rear"), (g_front, "glass_front")],
            "reticle_x": 0.20, "ocular_x": -4.99, "objective_x": 0.77,
            "lens_radius": lens_r, "aperture": ("circle", lens_r)}


# ============================================================================ IV-H1 holographic
def build_IVH1():
    oid = "IVH1"
    A = AXIS[oid]
    M = MAT[oid]
    # base (electronics + laser module), nose rounded around the transverse battery tube
    bx0, bat_x, bat_z, bat_r = -8.1, 0.35, 1.5, 1.1
    arc = [(bat_x + bat_r * math.cos(math.radians(a)), bat_z + bat_r * math.sin(math.radians(a)))
           for a in range(-90, 91, 10)]
    outline = [(bx0, bat_z - bat_r)] + arc + [(bx0, bat_z + bat_r)]
    rads = [0.3] + [0.0] * len(arc) + [0.3]
    base = L.poly_extrude("Housing", L.fillet_polygon(outline, rads, 4), 'Y', -1.75, 1.75)
    setmat(base, M["body"])
    # protective hood (tunnel) around the two windows
    hood_out = L.fillet_polygon([(2.12, 2.2), (2.12, 5.72), (-2.12, 5.72), (-2.12, 2.2)], [0, 0.85, 0.85, 0], 6)
    hood = L.poly_extrude("hood", hood_out, 'X', -8.0, -2.3)
    # rail clamp (fixed jaw left, moving jaw right) + button guard pad on the left side
    clamp = L.poly_extrude("clamp", O.clamp_section(1.5, 0.6), 'X', -5.0, 0.0)
    pad = L.poly_extrude("pad", L.rounded_rect(2.6, 1.15, 0.3, 4, cx=-5.7, cy=1.5), 'Y', 1.6, 1.84)
    L.union(base, [hood, clamp, pad])
    im = M["interior"]
    tun = setmat(L.poly_extrude("tun", L.rounded_rect(3.40, 2.50, 0.35, 5, cx=0.0, cy=A), 'X', -7.86, -2.44), im)
    lipr = setmat(L.poly_extrude("lipr", L.rounded_rect(3.24, 2.34, 0.30, 5, cx=0.0, cy=A), 'X', -8.3, -7.8), im)
    lipf = setmat(L.poly_extrude("lipf", L.rounded_rect(3.24, 2.34, 0.30, 5, cx=0.0, cy=A), 'X', -2.5, -2.0), im)
    holes = [L.cyl("bh", 0.43, 1.5, 2.0, 'Y', center=(x, 1.5), segs=24) for x in (-6.25, -5.15)]
    lug = L.cyl("lug", 0.19, -1.7, 1.7, 'Y', center=(-2.3, -0.18), segs=16)
    adj = [L.cyl("adj", 0.33, -1.9, -1.66, 'Y', center=(x, 1.55), segs=20) for x in (-7.25, -6.35)]
    L.boolean(base, [tun, lipr, lipf, lug] + holes + adj, material_mode='TRANSFER')
    L.bevel(base, 0.05, 2, 30)
    engrave_text(oid, base, "IV-H1", 0.46, ('left', (-5.15, 2.12, 4.35)))
    reg(oid, base, "body", "Housing", contact=0.3)
    # rubber buttons (brightness up / down)
    for i, x in enumerate((-6.25, -5.15)):
        b = L.lathe(f"Button{i}", [(1.6, 0.0), (1.6, 0.38), (1.9, 0.38), (1.97, 0.33), (2.02, 0.22), (2.04, 0.0)], 24,
                    'Y', center=(x, 1.5))
        L.bevel(b, 0.02, 1, 30)
        reg(oid, b, "rubber", f"Button{i}", contact=0.6)
    # battery cap (left end of the transverse CR123-size tube), fluted grip + coin slot
    cap = L.lathe("BatteryCap", [(1.70, 0.0), (1.70, 1.02), (2.36, 1.02), (2.44, 0.95), (2.5, 0.82), (2.5, 0.0)], 40,
                  'Y', center=(bat_x, bat_z))
    L.bevel(cap, 0.025, 2, 30)
    cf = flutes('Y', (bat_x, bat_z), 1.02, 30, 1.82, 2.34, depth=0.06, hw=0.07)
    cf.append(L.poly_extrude("cs", [(0.0, 2.44), (0.12, 2.6), (-0.12, 2.6)], 'Z', bat_z - 0.7, bat_z + 0.7))
    cf[-1].data.transform(Matrix.Translation((bat_x, 0.0, 0.0)))
    # coin slot: triangle in XY pointing +Y at y 2.44 (depth 0.06 into the end face at 2.5)
    L.boolean(cap, cf)
    reg(oid, cap, "knob", "BatteryCap", contact=0.7)
    # cross bolt (recoil lug) with its head on the left, QD throw lever on the right
    bolt = L.lathe("Lug", [(-1.5, 0.0), (-1.5, 0.18), (1.44, 0.18), (1.44, 0.3), (1.6, 0.3), (1.62, 0.0)], 16, 'Y',
                   center=(-2.3, -0.18))
    L.bevel(bolt, 0.012, 1, 30)
    reg(oid, bolt, "steel", "Lug", contact=0.4)
    hub = L.lathe("hub", [(-1.47, 0.0), (-1.47, 0.52), (-1.84, 0.52), (-1.9, 0.46), (-1.9, 0.0)], 32, 'Y',
                  center=(-2.3, -0.05))
    arm = L.poly_extrude("arm", L.fillet_polygon([(-2.3, 0.40), (-4.8, 0.28), (-5.3, 0.16), (-5.42, -0.03),
                                                  (-5.28, -0.22), (-2.3, -0.48)], [0, 0.3, 0.2, 0.15, 0.2, 0], 4),
                         'Y', -1.84, -1.56)
    tab = L.poly_extrude("tab", L.rounded_rect(0.5, 0.42, 0.12, 3, cx=-5.18, cy=-0.03), 'Y', -2.1, -1.62)
    L.union(hub, [arm, tab])
    L.bevel(hub, 0.03, 2, 30)
    L.boolean(hub, [L.poly_extrude("hx", L.circle_pts(0.2, 6, -2.3, -0.05), 'Y', -2.0, -1.84)])
    reg(oid, hub, "knob", "QDLever", contact=0.8)
    # windage / elevation adjusters (slotted, in recesses on the right side)
    for i, x in enumerate((-7.25, -6.35)):
        s = L.lathe(f"Adj{i}", [(-1.66, 0.0), (-1.66, 0.27), (-1.78, 0.27), (-1.8, 0.24), (-1.8, 0.0)], 20, 'Y',
                    center=(x, 1.55))
        L.boolean(s, [L.box("sl", x - 0.035, x + 0.035, -1.9, -1.74, 1.55 - 0.3, 1.55 + 0.3)])
        rot_data(s, 25.0 + 40.0 * i, 'Y', (x, 0.0, 1.55))
        reg(oid, s, "screw", f"Adjuster{i}", contact=0.2)
    # windows: rear (hologram, faint amber) and front (protective, blue coated) -- thin sheets
    # inside the lips, 20+ mm apart; the reticle plane sits between them
    w_rear = O.pane_sheet("WindowRear", -7.74, (0.0, A), 3.36, 2.46, 0.33, facing=-1)
    w_front = O.pane_sheet("WindowFront", -2.56, (0.0, A), 3.36, 2.46, 0.33, facing=+1)
    return {"glass": [(w_rear, "glass_rear"), (w_front, "glass_front")],
            "reticle_x": -5.15, "ocular_x": -7.74, "objective_x": -2.56,
            "lens_radius": 1.17, "aperture": ("rect", 3.24, 2.34)}


BUILDERS = {"IVH1": build_IVH1, "IVR1": build_IVR1}
GLASS_LOOK = {
    # key: (tint, alpha, coat colour, specular level, thin film nm)
    "IVH1": {"glass_rear": ((0.040, 0.032, 0.022), 0.10, (1.0, 0.78, 0.45), 0.7, 0.0),
             "glass_front": ((0.022, 0.030, 0.040), 0.10, (0.45, 0.72, 1.0), 0.8, 0.0)},
    "IVR1": {"glass_rear": ((0.024, 0.032, 0.030), 0.08, (0.55, 1.0, 0.75), 0.6, 0.0),
             "glass_front": ((0.050, 0.020, 0.012), 0.16, (1.0, 0.36, 0.18), 1.0, 0.0)},
}


# ----------------------------------------------------------------------------- build all
def build(oid, seed):
    t0 = time.time()
    build_materials(oid, seed)
    info = BUILDERS[oid]()
    EXTRA[oid] = {"build": info}
    L.log(f"  build {oid} {time.time() - t0:.1f}s, {len(PARTS[oid])} parts")
    return info


def finalize(oid):
    """cm -> m, shading, glass + sockets."""
    S = Matrix.Scale(0.01, 4)
    for p in PARTS[oid].values():
        o = p["obj"]
        o.data.transform(S)
        o.data.update()
        L.finish_shading(o, sharp_angle=50.0, weighted=True, triangulate=True, clean_dist=1e-6)
        a = o.data.attributes.get("iv_contact") or o.data.attributes.new("iv_contact", 'FLOAT', 'POINT')
        a.data.foreach_set("value", [p["contact"]] * len(o.data.vertices))
    info = EXTRA[oid]["build"]
    glass = []
    for g, key in info["glass"]:
        g.data.transform(S)
        g.data.update()
        tint, alpha, coat, spec, film = GLASS_LOOK[oid][key]
        m = O.mat_glass_thin(f"M_{oid}_Glass_{key.split('_')[1].capitalize()}", tint, alpha, coat, spec, 0.03, film)
        setmat(g, m)
        g.name = f"{oid}_{g.name}"
        L.link_to(g, col(oid))
        glass.append(g)
    EXTRA[oid]["glass"] = glass


def review_stage():
    """Quick look at the bare optics with procedural materials (no bake)."""
    L.clear_lights_cameras()
    for oid in IDS:
        for other in IDS:
            COLS[other].hide_render = other != oid
        objs = [p["obj"] for p in PARTS[oid].values()] + EXTRA[oid]["glass"]
        mn, mx = L.world_bbox_fast(objs)
        c = (mn + mx) / 2
        L.clear_lights_cameras()
        L.studio_lighting(c, (mx - mn).length / 2)
        rad = (mx - mn).length
        res = (800, 450)
        for tag, d in (("fl", Vector((0.9, 0.75, 0.45))), ("rr", Vector((-0.8, -0.85, 0.4))),
                       ("side", Vector((0.0, -1.0, 0.05)))):
            cam = L.camera("cam", c + d.normalized() * rad * 1.9, c, fov_deg=32)
            L.render(os.path.join(PREV_DIR, "_review", f"{oid}_{tag}.png"), cam, res, 32)


def main():
    t0 = time.time()
    for d in (TEX_ROOT, FBX_DIR, GLB_DIR, PREV_DIR):
        os.makedirs(d, exist_ok=True)
    L.log(f"optics build  quick={QUICK}  stages={STAGES}  optics={IDS}")
    L.reset_scene()
    L.CLEAN_DIST = 5e-4
    for i, oid in enumerate(IDS):
        build(oid, seed=100 + 20 * ALL_IDS.index(oid))
        finalize(oid)
    if "review" in STAGES:
        review_stage()
    L.log(f"optics done in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
