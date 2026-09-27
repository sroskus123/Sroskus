#!/usr/bin/env python3
"""
IRON VALLEY optics set -- generator (original designs, no real brands).

    python3 /home/user/Sroskus/IronValley/Art/Source/Blender/weapons/optics.py

  IV-H1  holographic sight 1x   (65 MOA ring + 1 MOA dot)
  IV-R1  compact red dot 1x     (2 MOA dot; the IV-7's optic as a stand-alone asset)
  IV-P2  compact prism 2x       (etched chevron / BDC, illuminated chevron)
  IV-S3  compact scope 3x       (illuminated dot + mil hash marks, capped turrets)
  IV-S6  scope 6x40             (mil-dot / duplex with holdover bars, exposed turrets,
                                 illumination knob, cantilever mount) + full-screen ADS overlay

Every optic is a separate static asset that mounts on the IV-7 upper rail (generic 21 mm
dovetail, 10 mm slot pitch).  Lenses are thin coated glass sheets (alpha blend + reflection, NO
transmission / refraction); reticles are high-resolution vector-rasterised textures on a
dedicated reticle sheet (Art/Textures/Optics/<ID>/).  Reference: Art/Reference/OPTICS_spec.md.

Deterministic; saves optics.blend next to this script.  The IV-7 is imported READ-ONLY (from a
temporary copy of iv7_carbine.blend) for the mounting checks and renders.

Environment switches:
    IV_QUICK=1          1024 / 512 textures, low samples, half-size renders (iteration only)
    IV_OPTICS=IVH1,...  subset of optics (default: all)
    IV_STAGES=a,b,...   build,bake,save,validate,export,reimport,mount,render,config
                        (default: all).  'review' = quick procedural renders of the bare optics.
                        Without 'build' the saved optics.blend is opened instead.
    IV_RENDERS=a,b,...  subset of renders: mounted,through,front,lineup,overlay

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
import numpy as np    # noqa: E402
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
REPORT = os.path.join(PREV_DIR, "optics_validation.json")

QUICK = os.environ.get("IV_QUICK") == "1"
ALL_STAGES = ["build", "bake", "save", "validate", "export", "reimport", "mount", "render", "config"]
STAGES = [s for s in os.environ.get("IV_STAGES", ",".join(ALL_STAGES)).split(",") if s]
ALL_IDS = ["IVH1", "IVR1", "IVP2", "IVS3", "IVS6"]
IDS = [s for s in os.environ.get("IV_OPTICS", ",".join(ALL_IDS)).split(",") if s]
RENDERS = [s for s in os.environ.get("IV_RENDERS", "mounted,through,front,lineup,overlay").split(",") if s]
RES_SCALE = 0.5 if QUICK else 1.0

# ----------------------------------------------------------------------------- design data
BORE_TO_RAIL_CM = O.IV7["rail_top_cm"]          # 3.0: IV-7 rail top above the bore axis
IV7_ADS_EYE_BORE_X = -14.9                      # IV-7 socket_ads (bore frame, cm)
# reference load for the holdover marks (the game itself is hitscan: see OPTICS_spec.md)
BALLISTICS = dict(label="5.56 mm, ~4 g (62 gr class) bullet from the IV-7's 36.8 cm barrel",
                  mv_mps=895.0, bc_g7=0.151, air="ICAO standard sea level (1.225 kg/m3)")

# x_mount: bore-frame x (cm) of socket_rail when mounted on the IV-7 (front edge of the clamp);
# lugs: recoil-lug (cross-bolt) x in the optic frame, each must land on a rail cross-slot centre.
# A: sight axis above the rail top (cm).  eye_relief: design eye relief (cm) for magnified optics;
# for 1x optics the eye point is put at the IV-7's current ADS eye (bore x -14.9).
SPEC = {
    "IVH1": dict(model="IV-H1", file="IVH1_Holo", kind="holographic", mag=1.0,
                 name_cs="Holografický zaměřovač IV-H1", short_cs="Holo 1×",
                 A=4.4, x_mount=1.7, lugs=[-2.3], tex=2048, eye_bore_x=IV7_ADS_EYE_BORE_X,
                 ads_time_s=0.22, range_m=[0, 150], mass_kg=0.31, zero_m=50,
                 note="lower-1/3 co-witness height with the IV-7 irons"),
    "IVR1": dict(model="IV-R1", file="IVR1_RedDot", kind="red_dot", mag=1.0,
                 name_cs="Kolimátor IV-R1", short_cs="Kolimátor 1×",
                 A=4.0, x_mount=-1.8, lugs=[-1.8], tex=1024, eye_bore_x=IV7_ADS_EYE_BORE_X,
                 ads_time_s=0.21, range_m=[0, 150], mass_kg=0.17, zero_m=50,
                 note="the IV-7's own optic (absolute co-witness), same position and size"),
    "IVP2": dict(model="IV-P2", file="IVP2_Prism", kind="prism", mag=2.0,
                 name_cs="Hranolový zaměřovač IV-P2 (2×)", short_cs="Hranol 2×",
                 A=4.1, x_mount=-0.4, lugs=[-3.2], tex=1024, eye_relief=7.0,
                 true_fov_deg=9.7, objective_mm=20.0,
                 ads_time_s=0.25, range_m=[15, 400], mass_kg=0.30, zero_m=100,
                 note="compact prism with integrated mount"),
    "IVS3": dict(model="IV-S3", file="IVS3_Scope", kind="scope", mag=3.0,
                 name_cs="Kompaktní puškohled IV-S3 (3×)", short_cs="Puškohled 3×",
                 A=4.0, x_mount=2.4, lugs=[-1.0, -5.0], tex=1024, eye_relief=8.5,
                 true_fov_deg=6.3, objective_mm=24.0,
                 ads_time_s=0.27, range_m=[25, 450], mass_kg=0.43, zero_m=100,
                 note="3x24, 30 mm tube, one-piece mount"),
    "IVS6": dict(model="IV-S6", file="IVS6_Scope", kind="scope", mag=6.0,
                 name_cs="Puškohled IV-S6 (6×40)", short_cs="Puškohled 6×",
                 A=4.6, x_mount=2.4, lugs=[-1.0, -5.0], tex=2048, eye_relief=9.0,
                 true_fov_deg=3.77, objective_mm=40.0,
                 ads_time_s=0.32, range_m=[75, 600], mass_kg=0.68, zero_m=100,
                 note="6x40, 30 mm tube, cantilever mount"),
}
AXIS = {k: v["A"] for k, v in SPEC.items()}
RED = (255, 38, 24)
RETICLE_EMISSION = 2.0      # stays saturated red under AgX in daylight (6+ desaturates towards pink)

PARTS = {}          # oid -> {name: {"obj", "contact"}}
EXTRA = {}          # oid -> {"build": info, "glass": [...], "reticle": obj, "sockets": {...}}
MAT = {}            # oid -> {key: material}
COLS = {}
RET = {}            # oid -> reticle metadata (Reticle.save result)
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


def dup(obj, name):
    o = bpy.data.objects.new(name, obj.data.copy())
    bpy.context.scene.collection.objects.link(o)
    o.matrix_world = obj.matrix_world.copy()
    return o


def vgroove(axis, apex_r, base_r, hw, a0, a1):
    """90 deg V-groove cutter pointing along +v of the extrusion plane (knurl flute)."""
    return L.poly_extrude("fl", [(0.0, apex_r), (hw, base_r), (-hw, base_r)], axis, a0, a1)


def flutes(axis, center, r, n, a0, a1, depth=0.07, hw=None, phase=0.0):
    """n straight knurl flutes around a cylinder of radius r (axis 'X', 'Y' or 'Z' through
    center = the two remaining coordinates, like ivlib.lathe), spanning a0..a1 along the axis."""
    hw = hw if hw is not None else 0.8 * math.pi * r / n / 2
    out = []
    lo, hi = min(a0, a1), max(a0, a1)
    for k in range(n):
        a = phase + 360.0 * k / n
        c = vgroove(axis, r - depth, r + 0.3, hw, lo, hi)
        rot_data(c, a, axis)
        if axis == 'Z':
            c.data.transform(Matrix.Translation((center[0], center[1], 0.0)))
        elif axis == 'Y':
            c.data.transform(Matrix.Translation((center[0], 0.0, center[1])))
        else:
            c.data.transform(Matrix.Translation((0.0, center[0], center[1])))
        out.append(c)
    return out


def ticks(oid, axis, center, r, n, a0, a1, major_every=5, a1_major=None, depth=0.025, w=0.035,
          phase=0.0, skip=()):
    """Engraved, paint-filled tick marks (thin radial grooves) around a cylinder."""
    out = []
    for k in range(n):
        if k in skip:
            continue
        a = phase + 360.0 * k / n
        top = a1_major if (a1_major is not None and k % major_every == 0) else a1
        lo, hi = min(a0, top), max(a0, top)
        prof = [(-w / 2, r - depth), (w / 2, r - depth), (w / 2, r + 0.2), (-w / 2, r + 0.2)]
        if axis == 'Z':
            c = L.box("tk", -w / 2, w / 2, r - depth, r + 0.2, lo, hi)
            rot_data(c, a, 'Z')
            c.data.transform(Matrix.Translation((center[0], center[1], 0.0)))
        elif axis == 'Y':
            c = L.poly_extrude("tk", prof, 'Y', lo, hi)
            rot_data(c, a, 'Y')
            c.data.transform(Matrix.Translation((center[0], 0.0, center[1])))
        else:
            c = L.poly_extrude("tk", prof, 'X', lo, hi)
            rot_data(c, a, 'X')
            c.data.transform(Matrix.Translation((0.0, center[0], center[1])))
        setmat(c, MAT[oid]["paint"])
        out.append(c)
    return out


def engrave_text(oid, target, body, size, frame, depth=0.018):
    """Engrave white-filled text into a flat face.  frame = ('left', (x, y, z)) face +Y read from
    the left side, ('right', ...) face -Y, ('top', ...) face +Z read from behind."""
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


def paint_mark(oid, target, cutters):
    for c in cutters:
        setmat(c, MAT[oid]["paint"])
    L.boolean(target, cutters, material_mode='TRANSFER')
    return target


def cross_bolt(oid, x, y_out, z=-0.18, nut=True, head_r=0.31, name="Lug"):
    """Recoil lug / cross bolt through the rail clamp (sits in a rail cross-slot): domed head with a
    hex socket against the left jaw face (+Y), shank r 0.175 in the r 0.19 clamp hole, hex nut
    (optional) against the right jaw face.  Returns the list of registered parts."""
    y0 = -y_out - (0.43 if nut else 0.0)
    prof = [(y0, 0.0), (y0, 0.14), (y0 + 0.03, 0.175), (y_out + 0.01, 0.175), (y_out + 0.01, head_r),
            (y_out + 0.17, head_r), (y_out + 0.24, head_r * 0.78), (y_out + 0.26, 0.0)]
    b = L.lathe(name, prof, 20, 'Y', center=(x, z))
    L.bevel(b, 0.012, 1, 30)
    L.boolean(b, [L.poly_extrude("hx", L.circle_pts(0.11, 6, x, z), 'Y', y_out + 0.14, y_out + 0.4)])
    parts = [reg(oid, b, "steel", f"{name}_{x:+.1f}".replace(".", "p"), contact=0.4)]
    if nut:
        n = L.poly_extrude("Nut", L.circle_pts(0.40, 6, x, z, phase=math.pi / 6), 'Y', -y_out - 0.37, -y_out - 0.01)
        L.bevel(n, 0.03, 1, 30)
        L.boolean(n, [L.cyl("nh", 0.18, -y_out - 0.5, -y_out + 0.1, 'Y', center=(x, z), segs=20)])
        parts.append(reg(oid, n, "steel", f"Nut_{x:+.1f}".replace(".", "p"), contact=0.5))
    return parts


def clamp_hole(x, y_out, z=-0.18):
    return L.cyl("lughole", 0.19, -y_out - 0.3, y_out + 0.3, 'Y', center=(x, z), segs=20)


def scope_rings(oid, xs, w, A, r_in=1.51, r_out=1.95, ear=0.52, ear_h=0.40, gap=0.05):
    """30 mm ring(s) split horizontally at the axis.  Returns (lower halves to be unioned into the
    mount, registered caps + screws)."""
    lowers, parts = [], []
    for i, xc in enumerate(xs):
        ann = L.lathe("ring", [(xc - w / 2, r_in), (xc - w / 2, r_out), (xc + w / 2, r_out), (xc + w / 2, r_in)],
                      64, 'X', center=(0.0, A), closed=True)
        ears = [L.box("ear", xc - w / 2, xc + w / 2, r_out - 0.3, r_out + ear, A - ear_h, A + ear_h),
                L.box("ear", xc - w / 2, xc + w / 2, -r_out - ear, -r_out + 0.3, A - ear_h, A + ear_h)]
        L.union(ann, ears)
        cap = dup(ann, "cap")
        L.boolean(ann, [L.box("lo", xc - 2, xc + 2, -5, 5, A - gap / 2, A + 5)])
        L.boolean(cap, [L.box("up", xc - 2, xc + 2, -5, 5, A - 5, A + gap / 2)])
        L.bevel(cap, 0.035, 2, 30)
        parts.append(reg(oid, cap, "body2", f"RingCap{i}", contact=0.3))
        lowers.append(ann)
        for sd in (1, -1):
            yc = sd * (r_out + ear / 2 - 0.02)
            s = L.lathe("Screw", [(A + ear_h + 0.004, 0.0), (A + ear_h + 0.004, 0.2), (A + ear_h + 0.14, 0.2),
                                  (A + ear_h + 0.2, 0.15), (A + ear_h + 0.2, 0.0)], 20, 'Z', center=(xc, yc))
            L.bevel(s, 0.01, 1, 30)
            L.boolean(s, [L.poly_extrude("hx", L.circle_pts(0.09, 6, xc, yc), 'Z', A + ear_h + 0.1, A + ear_h + 0.4)])
            parts.append(reg(oid, s, "screw", f"RingScrew{i}{'L' if sd > 0 else 'R'}", contact=0.2))
    return lowers, parts


# ----------------------------------------------------------------------------- materials
def build_materials(oid, seed):
    mk = L.mask_group(oid, edge_dist=0.0014, cavity_dist=0.005, ao_dist=0.02)
    M = {"masks": mk}
    # matte hard-anodised housings (optics are usually more matte than the rifle's satin receiver)
    M["body"] = L.mat_anodized(f"{oid}_Anod_Body", mk, base=(0.030, 0.030, 0.033), rough=0.47, wear=0.75,
                               scratches=0.35, seed=seed + 1)
    M["body2"] = L.mat_anodized(f"{oid}_Anod_Mount", mk, base=(0.034, 0.034, 0.036), rough=0.42, wear=0.9,
                                scratches=0.45, seed=seed + 2)
    M["knob"] = L.mat_anodized(f"{oid}_Anod_Knob", mk, base=(0.032, 0.032, 0.035), rough=0.42, wear=0.45,
                               scratches=0.3, seed=seed + 3)
    M["steel"] = L.mat_phosphate(f"{oid}_Steel_Phosphate", mk, seed=seed + 4)
    M["screw"] = L.mat_steel(f"{oid}_Steel_Screw", mk, rough=0.42, seed=seed + 5)
    M["rubber"] = L.mat_rubber(f"{oid}_Rubber", mk, base=(0.013, 0.013, 0.014), rough=0.78, seed=seed + 6)
    M["rubber_rib"] = L.mat_rubber(f"{oid}_Rubber_Ribbed", mk, base=(0.013, 0.013, 0.014), rough=0.76,
                                   seed=seed + 7, ribs={"axis": 'X', "scale": 260.0})
    M["interior"] = O.mat_black_interior(f"{oid}_Interior", mk, seed=seed + 8)
    M["paint"] = L.mat_paint(f"{oid}_Paint_White", mk, (0.62, 0.62, 0.60), rough=0.5, seed=seed + 9)
    M["paint_red"] = L.mat_paint(f"{oid}_Paint_Red", mk, (0.45, 0.03, 0.02), rough=0.5, seed=seed + 10)
    MAT[oid] = M
    return M


# ============================================================================ IV-R1 red dot
def build_IVR1():
    """The IV-7's enclosed red dot (Art/Reference/IV7_carbine_spec.md, part 'Optic') moved into the
    optic frame (x_opt = x_bore + 1.8, z_opt = z_bore - 3.0).  Look and size are kept; the lenses
    become thin coated sheets, the reticle a 2 MOA texture on a sheet 5.7 mm behind the front
    lens (the old 0.3 mm disc sat 0.02 mm from the lens face), plus a closed emitter."""
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
    lens_r = 1.29
    g_rear = O.lens_sheet("LensRear", -4.99, (0.0, A), lens_r, facing=-1, sag=0.03)
    g_front = O.lens_sheet("LensFront", 0.77, (0.0, A), lens_r, facing=+1, sag=0.09)
    return {"glass": [(g_rear, "glass_rear"), (g_front, "glass_front")],
            "reticle_x": 0.20, "reticle_shape": ('circle', 1.28), "ocular_x": -4.99, "objective_x": 0.77,
            "lens_radius": lens_r, "aperture": {"shape": "circle", "radius_cm": lens_r},
            "emitter": True}


# ============================================================================ IV-H1 holographic
def build_IVH1():
    oid = "IVH1"
    A = AXIS[oid]
    M = MAT[oid]
    # base (electronics + laser module) with a rounded nose around the transverse battery tube
    bx0, bat_x, bat_z, nose_r = -8.1, 0.35, 1.65, 1.35
    arc = [(bat_x + nose_r * math.cos(math.radians(a)), bat_z + nose_r * math.sin(math.radians(a)))
           for a in range(-90, 91, 10)]
    outline = [(bx0, bat_z - nose_r)] + arc + [(bx0, bat_z + nose_r)]
    rads = [0.3] + [0.0] * len(arc) + [0.3]
    base = L.poly_extrude("Housing", L.fillet_polygon(outline, rads, 4), 'Y', -1.75, 1.75)
    setmat(base, M["body"])
    # protective hood (tunnel) around the two windows
    hz0, hz1 = 2.6, A + 1.72
    hood_out = L.fillet_polygon([(2.12, hz0), (2.12, hz1), (-2.12, hz1), (-2.12, hz0)], [0, 0.85, 0.85, 0], 6)
    hood = L.poly_extrude("hood", hood_out, 'X', -8.0, -2.3)
    clamp = L.poly_extrude("clamp", O.clamp_section(1.5, 0.6), 'X', -5.0, 0.0)
    pad = L.poly_extrude("pad", L.rounded_rect(2.6, 1.15, 0.3, 4, cx=-5.7, cy=1.6), 'Y', 1.6, 1.84)
    L.union(base, [hood, clamp, pad])
    im = M["interior"]
    tun = setmat(L.poly_extrude("tun", L.rounded_rect(3.40, 2.50, 0.35, 5, cx=0.0, cy=A), 'X', -7.86, -2.44), im)
    lipr = setmat(L.poly_extrude("lipr", L.rounded_rect(3.24, 2.34, 0.30, 5, cx=0.0, cy=A), 'X', -8.3, -7.8), im)
    lipf = setmat(L.poly_extrude("lipf", L.rounded_rect(3.24, 2.34, 0.30, 5, cx=0.0, cy=A), 'X', -2.5, -2.0), im)
    holes = [L.cyl("bh", 0.43, 1.5, 2.0, 'Y', center=(x, 1.6), segs=24) for x in (-6.25, -5.15)]
    adj = [L.cyl("adj", 0.33, -1.9, -1.66, 'Y', center=(x, 1.6), segs=20) for x in (-7.25, -6.35)]
    L.boolean(base, [tun, lipr, lipf, clamp_hole(-2.3, 1.5)] + holes + adj, material_mode='TRANSFER')
    L.bevel(base, 0.05, 2, 30)
    engrave_text(oid, base, "IV-H1", 0.46, ('left', (-5.15, 2.12, A + 0.45)))
    reg(oid, base, "body", "Housing", contact=0.3)
    # rubber buttons (brightness up / down) on the left side
    for i, x in enumerate((-6.25, -5.15)):
        b = L.lathe(f"Button{i}", [(1.6, 0.0), (1.6, 0.38), (1.9, 0.38), (1.97, 0.33), (2.02, 0.22), (2.04, 0.0)], 24,
                    'Y', center=(x, 1.6))
        L.bevel(b, 0.02, 1, 30)
        reg(oid, b, "rubber", f"Button{i}", contact=0.6)
    # battery cap (left end of the transverse CR123-size tube), fluted grip + coin slot
    cap = L.lathe("BatteryCap", [(1.76, 0.0), (1.76, 1.02), (2.36, 1.02), (2.44, 0.95), (2.5, 0.82), (2.5, 0.0)], 40,
                  'Y', center=(bat_x, bat_z))
    L.bevel(cap, 0.025, 2, 30)
    cf = flutes('Y', (bat_x, bat_z), 1.02, 30, 1.86, 2.34, depth=0.06, hw=0.07)
    cs = L.poly_extrude("cs", [(0.0, 2.44), (0.12, 2.6), (-0.12, 2.6)], 'Z', bat_z - 0.7, bat_z + 0.7)
    cs.data.transform(Matrix.Translation((bat_x, 0.0, 0.0)))
    cf.append(cs)
    L.boolean(cap, cf)
    reg(oid, cap, "knob", "BatteryCap", contact=0.7)
    # cross bolt (recoil lug) head on the left, QD throw lever on the right
    lug = L.lathe("Lug", [(-1.5, 0.0), (-1.5, 0.175), (1.51, 0.175), (1.51, 0.3), (1.66, 0.3), (1.68, 0.0)], 16, 'Y',
                  center=(-2.3, -0.18))
    L.bevel(lug, 0.012, 1, 30)
    reg(oid, lug, "steel", "Lug", contact=0.4)
    hub = L.lathe("hub", [(-1.51, 0.0), (-1.51, 0.52), (-1.84, 0.52), (-1.9, 0.46), (-1.9, 0.0)], 32, 'Y',
                  center=(-2.3, -0.05))
    arm = L.poly_extrude("arm", L.fillet_polygon([(-2.3, 0.30), (-4.8, 0.26), (-5.3, 0.15), (-5.42, -0.03),
                                                  (-5.28, -0.21), (-2.3, -0.40)], [0, 0.3, 0.2, 0.15, 0.2, 0], 4),
                         'Y', -1.83, -1.575)
    tab = L.poly_extrude("tab", L.rounded_rect(0.5, 0.42, 0.12, 3, cx=-5.18, cy=-0.03), 'Y', -2.1, -1.70)
    L.union(hub, [arm, tab])
    L.bevel(hub, 0.03, 2, 30)
    L.boolean(hub, [L.poly_extrude("hx", L.circle_pts(0.2, 6, -2.3, -0.05), 'Y', -2.0, -1.84)])
    reg(oid, hub, "knob", "QDLever", contact=0.8)
    # windage / elevation adjusters (slotted, in recesses on the right side)
    for i, x in enumerate((-7.25, -6.35)):
        s = L.lathe(f"Adj{i}", [(-1.67, 0.0), (-1.67, 0.27), (-1.78, 0.27), (-1.8, 0.24), (-1.8, 0.0)], 20, 'Y',
                    center=(x, 1.6))
        L.boolean(s, [L.box("sl", x - 0.035, x + 0.035, -1.9, -1.74, 1.6 - 0.3, 1.6 + 0.3)])
        rot_data(s, 25.0 + 40.0 * i, 'Y', (x, 0.0, 1.6))
        reg(oid, s, "screw", f"Adjuster{i}", contact=0.2)
    # windows: rear (hologram, faint amber) and front (protective, blue coated) -- thin sheets
    w_rear = O.pane_sheet("WindowRear", -7.74, (0.0, A), 3.36, 2.46, 0.33, facing=-1)
    w_front = O.pane_sheet("WindowFront", -2.56, (0.0, A), 3.36, 2.46, 0.33, facing=+1)
    return {"glass": [(w_rear, "glass_rear"), (w_front, "glass_front")],
            "reticle_x": -5.15, "reticle_shape": ('rect', 1.68, 1.23, 0.33), "ocular_x": -7.74,
            "objective_x": -2.56, "lens_radius": 1.17,
            "aperture": {"shape": "rounded_rect", "width_cm": 3.24, "height_cm": 2.34, "corner_cm": 0.30}}


# ============================================================================ IV-P2 prism 2x
def build_IVP2():
    oid = "IVP2"
    A = AXIS[oid]
    M = MAT[oid]
    zb0, zb1 = 1.0, A + 1.45                      # prism box bottom / top
    box = L.poly_extrude("Housing", L.rounded_rect(3.2, zb1 - zb0, 0.55, 6, cx=0.0, cy=(zb0 + zb1) / 2), 'X',
                         -6.1, -1.3)
    setmat(box, M["body"])
    obj_t = L.lathe("objt", [(-1.6, 0.0), (-1.6, 1.45), (0.3, 1.45), (0.38, 1.53), (0.85, 1.53), (0.9, 1.46),
                             (0.9, 0.0)], 56, 'X', center=(0.0, A))
    eye_t = L.lathe("eyet", [(-7.75, 0.0), (-7.75, 1.36), (-7.71, 1.4), (-5.8, 1.4), (-5.8, 0.0)], 56, 'X',
                    center=(0.0, A))
    clamp = L.poly_extrude("clamp", O.clamp_section(1.35, 1.25), 'X', -5.4, 0.0)
    web = L.poly_extrude("web", L.fillet_polygon([(-1.6, 1.0), (-0.05, 1.0), (-0.05, 1.3), (-0.6, A - 1.25),
                                                  (-1.6, A - 1.25)], [0, 0, 0.1, 0.3, 0], 4), 'Y', -0.9, 0.9)
    xt = -3.7
    boss_e = L.lathe("be", [(zb1 - 0.3, 0.0), (zb1 - 0.3, 1.0), (zb1 + 0.27, 1.0), (zb1 + 0.27, 0.0)], 40, 'Z',
                     center=(xt, 0.0))
    boss_w = L.lathe("bw", [(-1.3, 0.0), (-1.3, 1.0), (-1.88, 1.0), (-1.88, 0.0)], 40, 'Y', center=(xt, A))
    boss_i = L.lathe("bi", [(1.3, 0.0), (1.3, 1.0), (1.88, 1.0), (1.88, 0.0)], 40, 'Y', center=(xt, A))
    L.union(box, [obj_t, eye_t, clamp, web, boss_e, boss_w, boss_i])
    bore = setmat(L.lathe("bore", [(-8.5, 0.0), (-8.5, 1.22), (-7.55, 1.22), (-7.55, 1.1), (0.1, 1.1), (0.1, 1.02),
                                   (0.3, 1.02), (0.3, 1.3), (1.2, 1.3), (1.2, 0.0)], 56, 'X', center=(0.0, A)),
                  M["interior"])
    L.boolean(box, [bore, clamp_hole(-3.2, 1.35)], material_mode='TRANSFER')
    L.bevel(box, 0.04, 2, 30)
    # index marks next to the turret caps + model marking
    paint_mark(oid, box, [L.box("ix", xt - 1.02, xt - 0.96, -0.03, 0.03, zb1 - 0.2, zb1 + 0.3),
                          L.box("ix", xt - 1.02, xt - 0.96, -1.95, -1.4, A - 0.03, A + 0.03)])
    engrave_text(oid, box, "IV-P2  2x", 0.36, ('left', (-3.7, 1.6, 1.95)))
    reg(oid, box, "body", "Housing", contact=0.3)
    # capped turrets (elevation top, windage right)
    ce = L.lathe("CapElev", [(zb1 + 0.28, 0.0), (zb1 + 0.28, 1.05), (zb1 + 1.0, 1.05), (zb1 + 1.07, 0.98),
                             (zb1 + 1.1, 0.85), (zb1 + 1.1, 0.0)], 40, 'Z', center=(xt, 0.0))
    L.bevel(ce, 0.02, 1, 30)
    L.boolean(ce, flutes('Z', (xt, 0.0), 1.05, 28, zb1 + 0.36, zb1 + 0.96, depth=0.06, hw=0.07))
    reg(oid, ce, "knob", "CapElev", contact=0.7)
    cw = L.lathe("CapWind", [(-1.89, 0.0), (-1.89, 1.05), (-2.61, 1.05), (-2.68, 0.98), (-2.71, 0.85), (-2.71, 0.0)],
                 40, 'Y', center=(xt, A))
    L.bevel(cw, 0.02, 1, 30)
    L.boolean(cw, flutes('Y', (xt, A), 1.05, 28, -1.97, -2.57, depth=0.06, hw=0.07))
    reg(oid, cw, "knob", "CapWind", contact=0.7)
    # illumination knob (left) = battery compartment with a coin slot
    ik = L.lathe("IllumKnob", [(1.89, 0.0), (1.89, 1.08), (2.62, 1.08), (2.68, 1.0), (2.7, 0.85), (2.7, 0.0)], 40,
                 'Y', center=(xt, A))
    L.bevel(ik, 0.02, 1, 30)
    cut = flutes('Y', (xt, A), 1.08, 20, 1.96, 2.56, depth=0.08, hw=0.12)
    cs = L.poly_extrude("cs", [(0.0, 2.6), (0.13, 2.76), (-0.13, 2.76)], 'Z', A - 0.6, A + 0.6)
    cs.data.transform(Matrix.Translation((xt, 0.0, 0.0)))
    L.boolean(ik, cut + [cs])
    reg(oid, ik, "knob", "IllumKnob", contact=0.7)
    # diopter ring + ribbed rubber eyecup
    dr = L.lathe("Diopter", [(-7.15, 1.405), (-7.15, 1.56), (-7.1, 1.6), (-6.3, 1.6), (-6.25, 1.56), (-6.25, 1.405)],
                 56, 'X', center=(0.0, A), closed=True)
    L.boolean(dr, flutes('X', (0.0, A), 1.6, 30, -7.05, -6.35, depth=0.05, hw=0.07))
    reg(oid, dr, "knob", "Diopter", contact=0.3)
    ec = L.lathe("Eyecup", [(-8.35, 1.25), (-8.35, 1.55), (-8.29, 1.63), (-7.23, 1.63), (-7.17, 1.58), (-7.17, 1.405),
                            (-7.76, 1.405), (-7.76, 1.25)], 56, 'X', center=(0.0, A), closed=True)
    L.bevel(ec, 0.03, 2, 30)
    reg(oid, ec, "rubber_rib", "Eyecup", contact=0.5)
    cross_bolt(oid, -3.2, 1.35)
    g_oc = O.lens_sheet("LensOcular", -7.62, (0.0, A), 1.2, facing=-1, sag=0.04)
    g_ob = O.lens_sheet("LensObjective", 0.32, (0.0, A), 1.0, facing=+1, sag=0.06)
    return {"glass": [(g_oc, "glass_rear"), (g_ob, "glass_front")],
            "reticle_x": -5.8, "reticle_shape": ('circle', 1.08), "ocular_x": -7.62, "objective_x": 0.32,
            "lens_radius": 1.2, "aperture": {"shape": "circle", "radius_cm": 1.2}, "objective_radius": 1.0}


# ============================================================================ scopes (shared)
def build_scope(oid, X0, prof, bore, saddle, turret_s, rings_s, ring_w, clamp_x0, spine_pts, arm=None,
                front_upright=None, rear_upright=None, knobs="capped", eyecup=None, focus=None,
                lens_oc=None, lens_ob=None, reticle_s=None, mark="", lighten=None, spine_hw=0.85):
    """Generic riflescope on a one-piece / cantilever 30 mm mount.  All positions along the tube
    are given as s (cm from the rear face of the eyecup); x = X0 + s."""
    A = AXIS[oid]
    M = MAT[oid]

    def X(s):
        return X0 + s
    body = L.lathe("Housing", [(X(s), r) for s, r in prof], 64, 'X', center=(0.0, A))
    setmat(body, M["body"])
    sad = L.lathe("saddle", [(X(s), r) for s, r in saddle], 64, 'X', center=(0.0, A))
    xt = X(turret_s)
    r_s = max(r for _, r in saddle)
    kb = dict(capped=(1.05, 0.62), exposed=(1.22, 0.55))[knobs]
    boss_r, boss_h = kb
    boss_e = L.lathe("be", [(A + r_s - 0.35, 0.0), (A + r_s - 0.35, boss_r), (A + r_s + boss_h, boss_r),
                            (A + r_s + boss_h, 0.0)], 48, 'Z', center=(xt, 0.0))
    boss_w = L.lathe("bw", [(-r_s + 0.35, 0.0), (-r_s + 0.35, boss_r), (-r_s - boss_h, boss_r), (-r_s - boss_h, 0.0)],
                     48, 'Y', center=(xt, A))
    ib_r = boss_r * 0.86
    boss_i = L.lathe("bi", [(r_s - 0.35, 0.0), (r_s - 0.35, ib_r), (r_s + boss_h - 0.1, ib_r),
                            (r_s + boss_h - 0.1, 0.0)], 48, 'Y', center=(xt, A))
    L.union(body, [sad, boss_e, boss_w, boss_i])
    bcut = setmat(L.lathe("bore", [(X(s), r) for s, r in bore], 64, 'X', center=(0.0, A)), M["interior"])
    L.boolean(body, [bcut], material_mode='TRANSFER')
    L.bevel(body, 0.04, 2, 30)
    top_e = A + r_s + boss_h
    # index marks (white) next to the turrets and a power band on the eyepiece
    paint_mark(oid, body, [L.box("ix", xt - boss_r - 0.08, xt - boss_r + 0.06, -0.03, 0.03, top_e - 0.45, top_e + 0.2),
                           L.box("ix", xt - boss_r - 0.08, xt - boss_r + 0.06, -(r_s + boss_h) - 0.2,
                                 -(r_s + boss_h) + 0.45, A - 0.03, A + 0.03)])
    reg(oid, body, "body", "Housing", contact=0.3)
    # turret knobs
    if knobs == "capped":
        r_c = boss_r + 0.05
        h0, h1 = top_e + 0.01, top_e + 0.85
        ce = L.lathe("CapElev", [(h0, 0.0), (h0, r_c), (h1 - 0.08, r_c), (h1 - 0.02, r_c - 0.06), (h1, r_c - 0.18),
                                 (h1, 0.0)], 40, 'Z', center=(xt, 0.0))
        L.bevel(ce, 0.02, 1, 30)
        L.boolean(ce, flutes('Z', (xt, 0.0), r_c, 30, h0 + 0.1, h1 - 0.12, depth=0.06, hw=0.07))
        reg(oid, ce, "knob", "CapElev", contact=0.7)
        w0, w1 = -(r_s + boss_h) - 0.01, -(r_s + boss_h) - 0.85
        cw = L.lathe("CapWind", [(w0, 0.0), (w0, r_c), (w1 + 0.08, r_c), (w1 + 0.02, r_c - 0.06), (w1, r_c - 0.18),
                                 (w1, 0.0)], 40, 'Y', center=(xt, A))
        L.bevel(cw, 0.02, 1, 30)
        L.boolean(cw, flutes('Y', (xt, A), r_c, 30, w0 - 0.1, w1 + 0.12, depth=0.06, hw=0.07))
        reg(oid, cw, "knob", "CapWind", contact=0.7)
        knob_top = h1
    else:
        # exposed, knurled, graduated turrets
        r_k = boss_r + 0.24
        h0 = top_e + 0.01
        prof_k = [(h0, 0.0), (h0, r_k), (h0 + 0.55, r_k), (h0 + 0.6, r_k - 0.05), (h0 + 1.25, r_k - 0.05),
                  (h0 + 1.32, r_k - 0.14), (h0 + 1.36, r_k - 0.3), (h0 + 1.36, 0.0)]
        te = L.lathe("TurretElev", prof_k, 48, 'Z', center=(xt, 0.0))
        L.bevel(te, 0.02, 1, 30)
        L.boolean(te, flutes('Z', (xt, 0.0), r_k - 0.05, 40, h0 + 0.66, h0 + 1.2, depth=0.06, hw=0.06))
        paint_mark(oid, te, ticks(oid, 'Z', (xt, 0.0), r_k, 40, h0 + 0.08, h0 + 0.3, 5, h0 + 0.46))
        reg(oid, te, "knob", "TurretElev", contact=0.7)
        prof_w = [(-a, r) for a, r in prof_k]
        prof_w = [(-(r_s + boss_h) - 0.01 - (a - h0), r) for a, r in prof_k]
        tw = L.lathe("TurretWind", prof_w, 48, 'Y', center=(xt, A))
        L.bevel(tw, 0.02, 1, 30)
        w0 = -(r_s + boss_h) - 0.01
        L.boolean(tw, flutes('Y', (xt, A), r_k - 0.05, 40, w0 - 0.66, w0 - 1.2, depth=0.06, hw=0.06))
        paint_mark(oid, tw, ticks(oid, 'Y', (xt, A), r_k, 40, w0 - 0.08, w0 - 0.3, 5, w0 - 0.46))
        reg(oid, tw, "knob", "TurretWind", contact=0.7)
        knob_top = h0 + 1.36
    # illumination knob (left) with battery cap / coin slot and position dots
    i0 = r_s + boss_h - 0.09
    ir = ib_r + 0.08
    ik = L.lathe("IllumKnob", [(i0, 0.0), (i0, ir), (i0 + 0.62, ir), (i0 + 0.68, ir - 0.07), (i0 + 0.7, ir - 0.2),
                               (i0 + 0.7, 0.0)], 40, 'Y', center=(xt, A))
    L.bevel(ik, 0.02, 1, 30)
    cs = L.poly_extrude("cs", [(0.0, i0 + 0.62), (0.13, i0 + 0.78), (-0.13, i0 + 0.78)], 'Z', A - 0.55, A + 0.55)
    cs.data.transform(Matrix.Translation((xt, 0.0, 0.0)))
    L.boolean(ik, flutes('Y', (xt, A), ir, 18, i0 + 0.3, i0 + 0.6, depth=0.07, hw=0.11) + [cs])
    paint_mark(oid, ik, ticks(oid, 'Y', (xt, A), ir, 12, i0 + 0.05, i0 + 0.22, 12, None, skip=(9, 10, 11), phase=90))
    reg(oid, ik, "knob", "IllumKnob", contact=0.7)
    # eyecup (ribbed rubber) and fast-focus ring (knurled)
    if eyecup:
        ec = L.lathe("Eyecup", [(X(s), r) for s, r in eyecup], 64, 'X', center=(0.0, A), closed=True)
        L.bevel(ec, 0.03, 2, 30)
        reg(oid, ec, "rubber_rib", "Eyecup", contact=0.5)
    if focus:
        s0, s1, ri, ro = focus
        fr = L.lathe("FocusRing", [(X(s0), ri), (X(s0), ro - 0.04), (X(s0) + 0.05, ro), (X(s1) - 0.05, ro),
                                   (X(s1), ro - 0.04), (X(s1), ri)], 64, 'X', center=(0.0, A), closed=True)
        L.boolean(fr, flutes('X', (0.0, A), ro, 36, X(s0) + 0.15, X(s1) - 0.15, depth=0.05, hw=0.08))
        reg(oid, fr, "knob", "FocusRing", contact=0.3)
    # mount: clamp + spine + uprights / cantilever arm + lower ring halves, tube clearance cut
    xs = [X(s) for s in rings_s]
    lowers, _ = scope_rings(oid, xs, ring_w, A)
    mount = L.poly_extrude("Mount", O.clamp_section(1.35, 0.9), 'X', clamp_x0, 0.0)
    setmat(mount, M["body2"])
    others = [L.poly_extrude("spine", L.fillet_polygon(spine_pts, 0.25, 4), 'Y', -spine_hw, spine_hw)]
    for up in (rear_upright, front_upright):
        if up:
            others.append(L.poly_extrude("up", L.fillet_polygon(up, [0.15, 0.15, 0.0, 0.0], 3), 'Y', -0.95, 0.95))
    if arm:
        others.append(L.poly_extrude("arm", L.fillet_polygon(arm, 0.3, 4), 'Y', -0.8, 0.8))
    L.union(mount, others + lowers)
    cuts = [L.cyl("clr", 1.51, xs[0] - 4, xs[-1] + 4, 'X', center=(0.0, A), segs=64)]
    cuts += [clamp_hole(x, 1.35) for x in SPEC[oid]["lugs"]]
    if lighten:
        cuts.append(L.poly_extrude("lt", O_stadium(*lighten), 'Y', -2, 2))
    L.boolean(mount, cuts)
    L.bevel(mount, 0.04, 2, 30)
    if mark:
        engrave_text(oid, mount, mark[0], 0.38, ('left', mark[1]))
    reg(oid, mount, "body2", "Mount", contact=0.35)
    for x in SPEC[oid]["lugs"]:
        cross_bolt(oid, x, 1.35)
    g_oc = O.lens_sheet("LensOcular", X(lens_oc[0]), (0.0, A), lens_oc[1], facing=-1, sag=0.05)
    g_ob = O.lens_sheet("LensObjective", X(lens_ob[0]), (0.0, A), lens_ob[1], facing=+1, sag=0.08)
    return {"glass": [(g_oc, "glass_rear"), (g_ob, "glass_front")],
            "reticle_x": X(reticle_s[0]), "reticle_shape": ('circle', reticle_s[1]),
            "ocular_x": X(lens_oc[0]), "objective_x": X(lens_ob[0]), "lens_radius": lens_oc[1],
            "objective_radius": lens_ob[1], "aperture": {"shape": "circle", "radius_cm": lens_oc[1]},
            "turret_x": xt, "knob_top": knob_top, "rings_x": xs}


def O_stadium(x0, x1, z0, z1, n=6):
    """Rounded slot outline (x, z) for a lightening cut."""
    r = (z1 - z0) / 2
    cz = (z0 + z1) / 2
    pts = []
    for k in range(n + 1):
        a = -math.pi / 2 + math.pi * k / n
        pts.append((x1 - r + r * math.cos(a), cz + r * math.sin(a)))
    for k in range(n + 1):
        a = math.pi / 2 + math.pi * k / n
        pts.append((x0 + r + r * math.cos(a), cz + r * math.sin(a)))
    return pts


def build_IVS3():
    oid = "IVS3"
    A = AXIS[oid]
    X0 = -10.7
    prof = [(0.9, 0.0), (0.9, 1.85), (0.95, 1.93), (3.8, 1.93), (3.9, 1.88), (5.2, 1.5), (13.3, 1.5), (14.3, 1.78),
            (14.35, 1.8), (16.95, 1.8), (17.0, 1.74), (17.0, 0.0)]
    bore = [(-0.5, 0.0), (-0.5, 1.45), (1.15, 1.45), (1.15, 1.3), (13.6, 1.3), (14.4, 1.45), (16.35, 1.45),
            (16.35, 1.22), (16.5, 1.22), (16.5, 1.62), (17.5, 1.62), (17.5, 0.0)]
    saddle = [(7.4, 0.0), (7.4, 1.5), (7.8, 1.72), (10.6, 1.72), (11.0, 1.5), (11.0, 0.0)]
    eyecup = [(0.0, 1.6), (0.0, 1.94), (0.07, 2.0), (0.88, 2.0), (0.88, 1.6)]
    rings_s = [6.3, 12.0]
    xr = [X0 + s for s in rings_s]
    spine = [(-6.3, 0.5), (-0.3, 0.5), (0.7, 1.3), (xr[1] + 0.65, 1.3), (xr[1] + 0.65, 2.85), (xr[0] - 0.65, 2.85),
             (xr[0] - 0.65, 2.2), (-6.3, 1.2)]
    return build_scope(oid, X0, prof, bore, saddle, turret_s=9.2, rings_s=rings_s, ring_w=1.3, clamp_x0=-7.0,
                       spine_pts=spine, knobs="capped", eyecup=eyecup, focus=(1.1, 2.8, 1.935, 2.06),
                       lens_oc=(1.0, 1.42), lens_ob=(16.52, 1.2), reticle_s=(1.6, 1.28),
                       mark=("IV-S3", (-2.9, 0.85, 1.75)), spine_hw=0.85)


def build_IVS6():
    oid = "IVS6"
    A = AXIS[oid]
    X0 = -11.4
    prof = [(0.95, 0.0), (0.95, 1.98), (1.0, 2.08), (2.75, 2.08), (2.8, 2.2), (5.35, 2.2), (5.5, 2.14), (7.0, 1.5),
            (19.0, 1.5), (21.9, 2.38), (22.0, 2.42), (26.9, 2.42), (27.0, 2.34), (27.0, 0.0)]
    bore = [(-0.5, 0.0), (-0.5, 1.82), (1.25, 1.82), (1.25, 1.3), (19.3, 1.3), (22.0, 2.05), (26.25, 2.05),
            (26.25, 2.22), (27.5, 2.22), (27.5, 0.0)]
    saddle = [(10.4, 0.0), (10.4, 1.5), (10.9, 1.86), (14.9, 1.86), (15.4, 1.5), (15.4, 0.0)]
    eyecup = [(0.0, 1.9), (0.0, 2.1), (0.07, 2.17), (0.93, 2.17), (0.93, 1.9)]
    rings_s = [8.6, 17.1]
    xr = [X0 + s for s in rings_s]
    # cantilever: clamp on the upper receiver rail only; rear upright on the clamp, arm forward to
    # the front ring, which overhangs the handguard (1.5 cm clear of its rail)
    spine = [(-6.8, 0.5), (-0.3, 0.5), (1.1, 1.5), (xr[1] + 0.75, 1.5), (xr[1] + 0.75, 2.6), (xr[0] - 0.3, 2.6),
             (xr[0] - 0.9, 2.2), (-6.8, 1.3)]
    rear_up = [(xr[0] - 1.05, 0.6), (xr[0] + 1.05, 0.6), (xr[0] + 1.05, A), (xr[0] - 1.05, A)]
    front_up = [(xr[1] - 0.75, 1.5), (xr[1] + 0.75, 1.5), (xr[1] + 0.75, A), (xr[1] - 0.75, A)]
    return build_scope(oid, X0, prof, bore, saddle, turret_s=12.9, rings_s=rings_s, ring_w=1.5, clamp_x0=-7.5,
                       spine_pts=spine, rear_upright=rear_up, front_upright=front_up, knobs="exposed",
                       eyecup=eyecup, focus=(1.0, 2.7, 2.085, 2.26), lens_oc=(1.05, 1.8), lens_ob=(26.3, 2.0),
                       reticle_s=(1.8, 1.28), mark=("IV-S6", (-0.8, 0.8, 1.55)),
                       lighten=(1.9, 4.4, 1.82, 2.3), spine_hw=0.8)


BUILDERS = {"IVH1": build_IVH1, "IVR1": build_IVR1, "IVP2": build_IVP2, "IVS3": build_IVS3, "IVS6": build_IVS6}
GLASS_LOOK = {
    # key: (tint, alpha, coat colour, specular level)
    "IVH1": {"glass_rear": ((0.040, 0.032, 0.022), 0.10, (1.0, 0.78, 0.45), 0.7),
             "glass_front": ((0.022, 0.030, 0.040), 0.10, (0.45, 0.72, 1.0), 0.8)},
    "IVR1": {"glass_rear": ((0.024, 0.032, 0.030), 0.08, (0.55, 1.0, 0.75), 0.6),
             "glass_front": ((0.050, 0.020, 0.012), 0.16, (1.0, 0.36, 0.18), 1.0)},
    "IVP2": {"glass_rear": ((0.024, 0.032, 0.030), 0.10, (0.55, 1.0, 0.70), 0.7),
             "glass_front": ((0.030, 0.030, 0.020), 0.14, (0.9, 0.85, 0.35), 0.9)},
    "IVS3": {"glass_rear": ((0.024, 0.032, 0.030), 0.10, (0.55, 1.0, 0.70), 0.7),
             "glass_front": ((0.028, 0.034, 0.024), 0.14, (0.55, 1.0, 0.55), 0.9)},
    "IVS6": {"glass_rear": ((0.024, 0.032, 0.030), 0.10, (0.55, 1.0, 0.70), 0.7),
             "glass_front": ((0.030, 0.026, 0.036), 0.15, (0.75, 0.55, 1.0), 0.9)},
}


# ============================================================================ reticles
def sight_height_m(oid):
    return (AXIS[oid] + BORE_TO_RAIL_CM) / 100.0


def holds(oid, ranges):
    h = O.holdovers(BALLISTICS["mv_mps"], BALLISTICS["bc_g7"], sight_height_m(oid), SPEC[oid]["zero_m"], ranges)
    return h


def make_reticles():
    """Vector reticle definitions -> textures + JSON in Art/Textures/Optics/<id>/."""
    q = 2 if QUICK else 1
    out = {}
    for oid in IDS:
        d = os.path.join(TEX_ROOT, oid)
        t0 = time.time()
        if oid == "IVH1":
            r = O.Reticle(oid, "MOA", 2048 // q, 80.0, RED, "IV-H1 holographic: 65 MOA ring + 1 MOA dot")
            r.ring((0, 0), 32.5, 2.0, "lit", desc={"type": "ring", "centreline_diameter": 65.0, "stroke": 2.0})
            r.circle((0, 0), 0.5, "lit", desc={"type": "dot", "diameter": 1.0})
            extra = {"reticle_type": "projected (hologram): no ink, invisible when switched off"}
        elif oid == "IVR1":
            r = O.Reticle(oid, "MOA", 2048 // q, 32.0, RED, "IV-R1 red dot: 2 MOA dot")
            r.circle((0, 0), 1.0, "lit", desc={"type": "dot", "diameter": 2.0})
            extra = {"reticle_type": "projected (LED on a reflective front lens): invisible when switched off"}
        elif oid == "IVP2":
            r = O.Reticle(oid, "MOA", 2048 // q, 64.0, RED, "IV-P2 prism 2x: illuminated chevron + etched BDC")
            chev = [(0.0, 0.0), (3.0, -3.3), (2.1, -3.3), (0.0, -1.0), (-2.1, -3.3), (-3.0, -3.3)]
            r.poly(chev, "lit", desc={"type": "chevron", "apex": [0, 0], "width": 6.0, "height": 3.3,
                                      "stroke": 0.67, "note": "apex tip = point of aim (100 m zero)"})
            h = holds(oid, [300, 400, 500, 600])
            last = 0.0
            for row in h["rows"]:
                y = -row["hold_rad"] / O.RAD_PER_UNIT["MOA"]
                w = 0.5 / row["range_m"] / O.RAD_PER_UNIT["MOA"]          # 0.5 m torso width at range
                r.seg((-w / 2, y), (w / 2, y), 0.45, "etch", desc={"type": "bdc_bar", "range_m": row["range_m"],
                                                                     "hold_moa": round(-y, 3), "width_moa": round(w, 3),
                                                                     "stroke": 0.45})
                r.text(str(row["range_m"] // 100), (w / 2 + 0.9, y), 1.7, "etch", "lm")
                last = y
            r.seg((0.0, -4.4), (0.0, last - 1.2), 0.3, "etch", desc={"type": "stadia", "from": -4.4, "to": round(last - 1.2, 3),
                                                                     "stroke": 0.3})
            extra = {"reticle_type": "etched on the prism (black ink visible without illumination); only the "
                                     "chevron is illuminated",
                     "zero_m": SPEC[oid]["zero_m"], "holdover_rows": h["rows"]}
        elif oid == "IVS3":
            r = O.Reticle(oid, "mrad", 4096 // q, 120.0, RED, "IV-S3 3x: illuminated dot + 1 mrad hash reticle")
            r.circle((0, 0), 0.3, "lit", desc={"type": "dot", "diameter": 0.6})
            w = 0.09
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                r.seg((dx * 0.9, dy * 0.9), (dx * 10.0, dy * 10.0), w, "etch")
                for k in range(1, 10):
                    L_ = 0.7 if k % 5 == 0 else 0.35
                    cx, cy = dx * k, dy * k
                    if dx:
                        r.seg((cx, -L_ / 2), (cx, L_ / 2), w, "etch")
                    else:
                        r.seg((-L_ / 2, cy), (L_ / 2, cy), w, "etch")
                r.seg((dx * 10.0, dy * 10.0), (dx * 57.0, dy * 57.0), 0.45, "etch")
            r.elements.append({"layer": "etch", "type": "crosshair", "stroke": w, "from": 0.9, "to": 10.0,
                               "hash_every": 1.0, "hash_length": 0.35, "hash_length_every_5": 0.7})
            r.elements.append({"layer": "etch", "type": "posts", "stroke": 0.45, "from": 10.0, "to": 57.0})
            extra = {"reticle_type": "etched glass (black) with an illuminated centre dot", "zero_m": SPEC[oid]["zero_m"]}
        elif oid == "IVS6":
            r = O.Reticle(oid, "mrad", 4096 // q, 72.0, RED, "IV-S6 6x: duplex mil-dot with holdover bars")
            r.circle((0, 0), 0.12, "lit", desc={"type": "dot", "diameter": 0.24})
            w = 0.06
            r.seg((-10.0, 0.0), (10.0, 0.0), w, "etch")
            r.seg((0.0, 0.0), (0.0, 10.0), w, "etch")
            r.seg((0.0, 0.0), (0.0, -12.0), w, "etch")
            for k in range(1, 10):
                for p in ((k, 0), (-k, 0), (0, k)):
                    r.circle(p, 0.11, "etch")
            for k in range(1, 12):
                r.circle((0, -k), 0.08, "etch")
            h = holds(oid, [300, 400, 500, 600])
            for row in h["rows"]:
                y = -row["hold_rad"] / 1e-3
                wd = 0.5 / row["range_m"] / 1e-3
                r.seg((-wd / 2, y), (wd / 2, y), 0.06, "etch", desc={"type": "holdover_bar", "range_m": row["range_m"],
                                                                     "hold_mrad": round(-y, 4), "width_mrad": round(wd, 4)})
                r.text(str(row["range_m"] // 100), (wd / 2 + 0.25, y), 0.42, "etch", "lm")
            for p0, p1 in (((-10.0, 0), (-34.0, 0)), ((10.0, 0), (34.0, 0)), ((0, 10.0), (0, 34.0)),
                           ((0, -12.0), (0, -34.0))):
                r.seg(p0, p1, 0.45, "etch")
            r.elements.append({"layer": "etch", "type": "crosshair", "stroke": w,
                               "extent": {"left": 10, "right": 10, "up": 10, "down": 12}})
            r.elements.append({"layer": "etch", "type": "mil_dots", "diameter": 0.22, "spacing": 1.0,
                               "positions": "1..9 left/right/up; 0.16 mrad dots 1..11 down"})
            r.elements.append({"layer": "etch", "type": "posts", "stroke": 0.45,
                               "from": {"left": 10, "right": 10, "up": 10, "down": 12}, "to": 34.0})
            extra = {"reticle_type": "etched glass (black) with an illuminated centre dot",
                     "zero_m": SPEC[oid]["zero_m"], "holdover_rows": h["rows"]}
        extra["magnification_note"] = ("angles are OBJECT-space (as subtended at the target); behind the eyepiece "
                                       f"they appear x{SPEC[oid]['mag']:g}")
        extra["projection"] = ("gnomonic: pixel offset from the texture centre = px_per_unit x tan(angle) / unit_in_rad "
                               "(reticle marks are linear at the target; a rectilinear camera projects the same way). "
                               "px_per_unit is exact at the axis; at the texture edge linear-in-angle differs by "
                               "< 0.13 % for the fields used here.")
        meta = r.save(d, spread_px=16.0, extra=extra)
        meta["metrics"] = O.reticle_metrics(meta)
        out[oid] = meta
        L.log(f"  reticle {oid}: {r.N}px, {meta['px_per_unit']:.3f} px/{r.units}  {time.time() - t0:.1f}s")
        prev = os.path.join(PREV_DIR, "reticles")
        os.makedirs(prev, exist_ok=True)
        O.reticle_preview(meta, os.path.join(prev, f"{oid}_reticle.png"), bg="sky", size=1024,
                          title=f"{SPEC[oid]['model']}  {r.title.split(':', 1)[-1].strip()}  "
                                f"({meta['px_per_unit']:.2f} px/{r.units}, texture {r.N}px)",
                          scale_units=10.0 if r.units == "MOA" else (1.0 if oid == "IVS6" else 5.0))
    RET.update(out)
    return out


def make_overlay():
    """IV-S6 full-screen ADS overlay (same px/mrad as the reticle texture)."""
    if "IVS6" not in RET:
        return None
    oid = "IVS6"
    meta = RET[oid]
    true_r = 0.5 * math.radians(SPEC[oid]["true_fov_deg"]) / 1e-3          # field stop radius, mrad
    path = os.path.join(TEX_ROOT, oid, f"T_{oid}_ADS_Overlay.png")
    ov = O.eyebox_overlay(meta, true_r, path)
    ov["vertical_fov_deg_when_drawn_full_height"] = math.degrees(meta["field_units"] * 1e-3)
    ov["usage"] = ("Draw centred, scaled so that its height = screen height; set the zoomed camera's vertical FOV to "
                   "vertical_fov_deg_when_drawn_full_height (or, for any other scale: overlay_px_on_screen = "
                   "screen_px_per_mrad x field_units).  Fill the screen area outside the square with black.")
    with open(os.path.join(TEX_ROOT, oid, f"T_{oid}_ADS_Overlay.json"), "w") as f:
        json.dump({k: v for k, v in ov.items()}, f, indent=2)
    INFO.setdefault(oid, {})["overlay"] = ov
    return ov


# ============================================================================ build / finalize
def build(oid, seed):
    t0 = time.time()
    build_materials(oid, seed)
    info = BUILDERS[oid]()
    EXTRA[oid] = {"build": info}
    L.log(f"  build {oid} {time.time() - t0:.1f}s, {len(PARTS[oid])} parts")
    return info


def eye_x_cm(oid):
    """Design eye point x (optic frame, cm)."""
    sp = SPEC[oid]
    info = EXTRA[oid]["build"]
    if sp["mag"] > 1.0:
        return info["ocular_x"] - sp["eye_relief"]
    return sp["eye_bore_x"] - sp["x_mount"]


def finalize(oid):
    """cm -> m, shading; glass, reticle sheet, sockets."""
    A = AXIS[oid]
    S = Matrix.Scale(0.01, 4)
    for p in PARTS[oid].values():
        o = p["obj"]
        o.data.transform(S)
        o.data.update()
        L.finish_shading(o, sharp_angle=50.0, weighted=True, triangulate=True, clean_dist=1e-6)
        fix_slivers(o)
        a = o.data.attributes.get("iv_contact") or o.data.attributes.new("iv_contact", 'FLOAT', 'POINT')
        a.data.foreach_set("value", [p["contact"]] * len(o.data.vertices))
    info = EXTRA[oid]["build"]
    glass = []
    for g, key in info["glass"]:
        g.data.transform(S)
        g.data.update()
        tint, alpha, coat, spec = GLASS_LOOK[oid][key]
        m = O.mat_glass_thin(f"M_{oid}_Glass_{key.split('_')[1].capitalize()}", tint, alpha, coat, spec, 0.03, 0.0)
        setmat(g, m)
        g.name = f"{oid}_{g.name}"
        g.data.name = g.name
        L.link_to(g, col(oid))
        glass.append(g)
    EXTRA[oid]["glass"] = glass
    # reticle sheet (metres)
    ex = eye_x_cm(oid)
    meta = RET[oid]
    rshape = info["reticle_shape"]
    shp = (rshape[0],) + tuple(v / 100.0 for v in rshape[1:])
    ret, tex_half = O.reticle_plane(f"{oid}_Reticle", info["reticle_x"] / 100.0, (0.0, A / 100.0), ex / 100.0, meta,
                                    magnification=SPEC[oid]["mag"], shape=shp, col=col(oid))
    base_png = meta["paths"]["base_rgba"]
    em_png = meta["paths"]["emissive_rgb"]
    rm = O.mat_reticle(f"M_{oid}_Reticle", base_png, em_png, strength=RETICLE_EMISSION)
    setmat(ret, rm)
    ret.data.name = ret.name
    for o in [ret] + glass:
        o.visible_shadow = False
        o.visible_diffuse = False if o is ret else True
    ret.visible_glossy = False
    EXTRA[oid]["reticle"] = ret
    EXTRA[oid]["reticle_tex_half_m"] = tex_half
    # sockets (optic frame, metres; identity rotation: X = sight axis forward, Z up)
    socks = {
        "socket_rail": (0.0, 0.0, 0.0),
        "socket_sight_axis_rear": (info["ocular_x"] / 100.0, 0.0, A / 100.0),
        "socket_sight_axis_front": (info["objective_x"] / 100.0, 0.0, A / 100.0),
        "socket_eye": (ex / 100.0, 0.0, A / 100.0),
        "socket_reticle": (info["reticle_x"] / 100.0, 0.0, A / 100.0),
    }
    EXTRA[oid]["sockets"] = {}
    for n, p in socks.items():
        s = O.make_socket(f"{oid}_{n}", p, size=0.01, col=col(oid))
        EXTRA[oid]["sockets"][n] = s


def fix_slivers(o, area_eps=1e-11):
    """Collapse the shortest edge of zero-area boolean slivers (collinear triangles), keeping the
    change only if the mesh health does not get worse."""
    me = o.data
    bm = bmesh.new()
    bm.from_mesh(me)
    bad = [f for f in bm.faces if f.calc_area() < area_eps]
    if not bad:
        bm.free()
        return 0
    before = L.mesh_health(o)
    edges = []
    for f in bad:
        e = min(f.edges, key=lambda e: e.calc_length())
        if e not in edges:
            edges.append(e)
    bmesh.ops.collapse(bm, edges=edges, uvs=True)
    backup = me.copy()
    bm.to_mesh(me)
    bm.free()
    me.update()
    after = L.mesh_health(o)
    if any(a > b for a, b in zip(after, before)):
        o.data = backup
        bpy.data.meshes.remove(me)
        backup.name = o.name
        L.log(f"  fix_slivers {o.name}: collapse made health worse {before} -> {after}; reverted")
        return 0
    bpy.data.meshes.remove(backup)
    L.log(f"  fix_slivers {o.name}: collapsed {len(edges)} sliver edge(s)")
    return len(edges)


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
            L.render(os.path.join(PREV_DIR, "_review", f"{oid}_{tag}.png"), cam, res, 24)
    for other in IDS:
        COLS[other].hide_render = False


# ============================================================================ UV / bake / assemble
def tex_size(oid):
    return SPEC[oid]["tex"] // (2 if QUICK else 1)


def uv_policy_for(oid):
    def fn(obj, info):
        mats = info["materials"]
        if any("_Paint" in m for m in mats):
            return 1.6                                   # markings: extra resolution for legibility
        f = 1.0
        if any(m.endswith("_Interior") for m in mats):
            f *= 0.35                                    # bores / tunnels (seen dark through glass)
        if info["area3d"] * 1e4 < 0.01:
            f *= 0.45
        return f
    return fn


def uv_bake(oid):
    objs = [p["obj"] for p in PARTS[oid].values()]
    ts = tex_size(oid)
    rep = {}
    t0 = time.time()
    # smart projection folds the V-groove knurl flutes onto their neighbours at large angle limits
    # (a self-overlap inside one island that the per-island packing check cannot see); unwrap
    # with a smaller limit until no pixel is shared by two faces' islands
    for ang in (45.0, 35.0, 28.0):
        rep = {}
        L.uv_unwrap(objs, angle=ang, island_margin=0.002, pack_margin=3.0 / ts, scale_fn=uv_policy_for(oid),
                    tex_size=ts, protect_materials=(f"{oid}_Paint",), report=rep)
        ov = L.uv_island_raster(objs, ts)["overlap_px"]
        rep["angle"] = ang
        rep["overlap_px_final"] = ov
        L.log(f"  uv {oid}: angle {ang} -> shared px {ov}")
        if ov == 0:
            break
    # islands nudged onto free texels can end a fraction of a pixel outside 0..1: clamp them
    clamped = 0
    for o in objs:
        uvd = o.data.uv_layers[0].data
        arr = np.empty(len(uvd) * 2)
        uvd.foreach_get("uv", arr)
        c = np.clip(arr, 0.0, 1.0)
        clamped += int((np.abs(c - arr) > 0).sum())
        uvd.foreach_set("uv", c)
    rep["clamped_uv_coords"] = clamped
    L.log(f"  uv {oid}: {time.time() - t0:.1f}s {rep}")
    # glass / reticle must not occlude the AO / cavity bake
    hidden = EXTRA[oid]["glass"] + [EXTRA[oid]["reticle"]]
    for o in hidden:
        o.hide_render = True
    # every optic is authored at the same origin: hide the others, or their overlapping geometry
    # occludes this optic's AO / cavity bake (it shows up as grey dielectric grime blotches)
    for other in COLS:
        COLS[other].hide_render = other != oid
    d = os.path.join(TEX_ROOT, oid)
    paths = L.bake_texture_set(f"{oid}_Body", objs, MAT[oid]["masks"], d, "T_", size=ts,
                               mask_samples=12 if QUICK else 24, final_samples=4 if QUICK else 8,
                               margin=8 if QUICK else 16)
    for o in hidden:
        o.hide_render = False
    for other in COLS:
        COLS[other].hide_render = False
    em = L.export_material(f"M_{oid}_Body", paths["BaseColor"], paths["ORM"], paths["Normal"])
    em.use_backface_culling = True          # closed meshes: single sided in glTF / engines
    L.swap_to_export_material(objs, em)
    INFO.setdefault(oid, {})["uv"] = rep
    INFO[oid]["textures"] = {k: os.path.relpath(v, PROJECT) for k, v in paths.items()}
    # quarter-resolution copies for the third-person LOD1 GLB
    from PIL import Image
    lod_dir = os.path.join(d, "LOD1")
    os.makedirs(lod_dir, exist_ok=True)
    lod = {}
    for k in ("BaseColor", "Normal", "ORM"):
        im = Image.open(paths[k])
        q = im.resize((max(256, im.width // 4), max(256, im.height // 4)), Image.LANCZOS)
        out = os.path.join(lod_dir, os.path.basename(paths[k]).replace(".png", "_LOD1.png"))
        q.save(out, optimize=False, compress_level=9)
        lod[os.path.basename(paths[k])] = out
    INFO[oid]["lod1_image_map"] = lod
    return paths


def purge_procedural(remove_attrs=True):
    if remove_attrs:
        for oid in IDS:
            for p in PARTS.get(oid, {}).values():
                a = p["obj"].data.attributes.get("iv_contact")
                if a:
                    p["obj"].data.attributes.remove(a)
    for _ in range(4):
        n = bpy.data.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)
        if not n:
            break


def assemble(oid):
    """Join the body parts into one static mesh SM_<file> (origin = socket_rail), join the glass
    sheets, parent glass / reticle / sockets to it, build LOD1."""
    sp = SPEC[oid]
    parts = [p["obj"] for p in PARTS[oid].values()]
    part_names = [o.name for o in parts]
    part_tris = {o.name: L.tri_count(o) for o in parts}
    sm = L.join(parts, f"SM_{sp['file']}")
    sm.data.name = sm.name
    L.link_to(sm, col(oid))
    glass = L.join(EXTRA[oid]["glass"], f"{oid}_Glass")
    glass.data.name = glass.name
    ret = EXTRA[oid]["reticle"]
    kids = [glass, ret] + list(EXTRA[oid]["sockets"].values())
    for o in kids:
        o.parent = sm
        o.matrix_parent_inverse = Matrix.Identity(4)
    info = dict(EXTRA[oid]["build"])
    info = {k: v for k, v in info.items() if k != "glass"}
    info["reticle_shape"] = list(info["reticle_shape"])
    info["eye_x"] = eye_x_cm(oid)
    info["reticle_tex_half_m"] = EXTRA[oid]["reticle_tex_half_m"]
    info["parts"] = part_names
    info["part_tris"] = part_tris
    sm["iv_info"] = json.dumps(info)
    # LOD1 (third person): collapse-decimated body, planar-dissolved glass, no reticle
    lcol = L.collection(f"{oid}_LOD1")
    sm1 = L.make_lod(sm, 0.5, sm.name + "_LOD1", lcol, sharp_angle=50.0)
    sm1.data.name = sm1.name
    g1 = bpy.data.objects.new(glass.name + "_LOD1", glass.data.copy())
    lcol.objects.link(g1)
    g1.data.name = g1.name
    d = g1.modifiers.new("dis", 'DECIMATE')
    d.decimate_type = 'DISSOLVE'
    d.angle_limit = math.radians(20.0)
    L.apply_modifiers(g1)
    t = g1.modifiers.new("tri", 'TRIANGULATE')
    L.apply_modifiers(g1)
    g1.parent = sm1
    g1.matrix_parent_inverse = Matrix.Identity(4)
    lcol.hide_render = True
    EXTRA[oid].update({"sm": sm, "glass_obj": glass, "sm_lod1": sm1, "glass_lod1": g1, "info": info})
    return sm


def load_saved():
    """Open optics.blend and re-populate EXTRA / RET from it (stages after 'save')."""
    bpy.ops.wm.open_mainfile(filepath=BLEND)
    for oid in IDS:
        sp = SPEC[oid]
        sm = bpy.data.objects[f"SM_{sp['file']}"]
        info = json.loads(sm["iv_info"])
        EXTRA[oid] = {"sm": sm, "glass_obj": bpy.data.objects[f"{oid}_Glass"], "reticle": bpy.data.objects[f"{oid}_Reticle"],
                      "sm_lod1": bpy.data.objects[f"SM_{sp['file']}_LOD1"],
                      "glass_lod1": bpy.data.objects[f"{oid}_Glass_LOD1"], "info": info, "build": info,
                      "sockets": {n.split(f"{oid}_", 1)[1]: bpy.data.objects[n] for n in
                                  [f"{oid}_{k}" for k in ("socket_rail", "socket_sight_axis_rear",
                                                          "socket_sight_axis_front", "socket_eye", "socket_reticle")]}}
        COLS[oid] = bpy.data.collections[oid]
        for m in sm.data.materials:
            if m and m.name.endswith("_Body"):
                m.use_backface_culling = True
    if os.path.exists(REPORT):
        with open(REPORT) as f:
            old = json.load(f)
        for oid, v in old.get("optics", {}).items():
            if oid in IDS:
                INFO.setdefault(oid, {}).update(v)


def optic_objects(oid, lod=0):
    e = EXTRA[oid]
    if lod == 1:
        return [e["sm_lod1"], e["glass_lod1"]]
    return [e["sm"], e["glass_obj"], e["reticle"]] + list(e["sockets"].values())


# ============================================================================ validation
def sheet_check(o, facing):
    """Open single-surface sheet (lens / window / reticle): boundary-only open edges, no zero-area
    faces, UVs, normals facing +X*facing."""
    me = o.data
    bm = bmesh.new()
    bm.from_mesh(me)
    bnd = sum(1 for e in bm.edges if len(e.link_faces) == 1)
    over = sum(1 for e in bm.edges if len(e.link_faces) > 2)
    zero = sum(1 for f in bm.faces if f.calc_area() < 1e-11)
    shells = 0
    seen = set()
    bm.faces.ensure_lookup_table()
    for f in bm.faces:
        if f.index in seen:
            continue
        shells += 1
        st = [f]
        seen.add(f.index)
        while st:
            g = st.pop()
            for e in g.edges:
                for h in e.link_faces:
                    if h.index not in seen:
                        seen.add(h.index)
                        st.append(h)
    bm.free()
    nx = []
    for p in me.polygons:
        nx.append(p.normal.x)
    mats = [m.name for m in me.materials]
    per_mat_facing = {}
    for p in me.polygons:
        per_mat_facing.setdefault(mats[p.material_index], []).append(p.normal.x)
    ok_facing = {}
    for mname, xs in per_mat_facing.items():
        want = facing.get(mname, facing.get("*"))
        ok_facing[mname] = bool(all(x * want > 0.5 for x in xs)) if want else None
    return {"tris": L.tri_count(o), "boundary_edges": bnd, "edges_with_3plus_faces": over, "zero_area_faces": zero,
            "shells": shells, "uv_layers": [u.name for u in me.uv_layers], "facing_ok": ok_facing}


def validate_stage():
    rep = {}
    for oid in IDS:
        e = EXTRA[oid]
        sm, sm1 = e["sm"], e["sm_lod1"]
        ts = tex_size(oid)
        vpath = os.path.join(PREV_DIR, f"{oid}_mesh_validation.json")
        v = L.validate(vpath, [sm], texture_sets={oid: {"objects": [sm], "size": ts}},
                       shells=None, max_zero_uv_face_mm2=0.05)
        v1 = L.validate(vpath.replace(".json", "_LOD1.json"), [sm1], shells=None, max_zero_uv_face_mm2=0.12)
        v["problems"] = v["problems"] + v1["problems"]
        g = e["glass_obj"]
        mats = [m.name for m in g.data.materials]
        facing = {m: (-1 if "Rear" in m else +1) for m in mats}
        sheets = {g.name: sheet_check(g, facing), e["glass_lod1"].name: sheet_check(e["glass_lod1"], facing),
                  e["reticle"].name: sheet_check(e["reticle"], {"*": -1})}
        sheet_problems = [f"{n}: {k}={d[k]}" for n, d in sheets.items() for k in
                          ("edges_with_3plus_faces", "zero_area_faces") if d[k]]
        sheet_problems += [f"{n}: facing wrong for {m}" for n, d in sheets.items() for m, okf in d["facing_ok"].items()
                           if okf is False]
        # materials: no transmission / refraction anywhere
        mats_all = set()
        for o in optic_objects(oid) + optic_objects(oid, 1):
            if o.type == 'MESH':
                mats_all |= set(o.data.materials)
        tr = O.blend_transmission_audit(mats_all)
        tr_bad = [m for m, d in tr.items() if d.get("transmission_weight", 0) > 0 or d.get("transmission_linked")
                  or d.get("forbidden_node")]
        # reticle sheet UV scale: project socket_eye -> centre UV and angular scale
        r = e["reticle"]
        me = r.data
        uvs = me.uv_layers[0].data
        A = AXIS[oid] / 100.0
        eye_x = e["info"]["eye_x"] / 100.0
        dx = e["info"]["reticle_x"] / 100.0 - eye_x
        # fit u = a*y + b, v = c*z + d from the loops
        ys, zs, us, vs = [], [], [], []
        for p in me.polygons:
            for li in p.loop_indices:
                co = me.vertices[me.loops[li].vertex_index].co
                ys.append(co.y); zs.append(co.z - A); us.append(uvs[li].uv.x); vs.append(uvs[li].uv.y)
        a, b = np.polyfit(ys, us, 1)
        c, dd = np.polyfit(zs, vs, 1)
        meta = RET[oid]
        unit_rad = O.RAD_PER_UNIT[meta["units"]]
        # texture units per radian of apparent angle seen from the eye: du/dangle
        units_per_uv = meta["field_units"]
        ang_per_m = 1.0 / dx                       # small angle: tan(theta) = y / dx
        scale_units_per_rad = abs(a) * units_per_uv / ang_per_m / 1.0
        apparent_units_per_rad = 1.0 / unit_rad / SPEC[oid]["mag"]
        uvchk = {"uv_at_axis": [round(float(b), 6), round(float(dd), 6)],
                 "u_runs_to_shooters_right": bool(a < 0), "v_runs_up": bool(c > 0),
                 "eye_to_sheet_m": round(dx, 5),
                 "texture_units_per_radian_seen_from_eye": round(float(scale_units_per_rad), 3),
                 "expected_units_per_radian": round(apparent_units_per_rad, 3),
                 "scale_error_pct": round(100 * (scale_units_per_rad / apparent_units_per_rad - 1), 5)}
        rep[oid] = {"mesh_validation": vpath.replace(PROJECT + "/", ""),
                    "mesh_problems": v["problems"], "tris_lod0": L.tri_count(sm), "tris_lod1": L.tri_count(sm1),
                    "tris_glass": L.tri_count(g), "tris_reticle": L.tri_count(r),
                    "texture_set": v.get("texture_sets", {}).get(oid, {}),
                    "sheets": sheets, "sheet_problems": sheet_problems,
                    "transmission_audit": tr, "transmission_problems": tr_bad,
                    "reticle_uv_check": uvchk, "reticle_metrics": RET[oid].get("metrics")}
        # dimensions
        mn, mx = L.world_bbox_fast([sm])
        ext = [round((mx[i] - mn[i]) * 100, 2) for i in range(3)]
        rep[oid]["dimensions_cm"] = {"length_x": ext[0], "width_y": ext[1], "height_z": ext[2],
                                     "bbox_min_cm": [round(v * 100, 2) for v in mn],
                                     "bbox_max_cm": [round(v * 100, 2) for v in mx],
                                     "height_above_rail_top_cm": round(mx[2] * 100, 2)}
        INFO.setdefault(oid, {}).update(rep[oid])
        L.log(f"  validate {oid}: mesh {len(v['problems'])} problems, sheets {len(sheet_problems)}, "
              f"transmission {len(tr_bad)}, uv scale err {uvchk['scale_error_pct']}%")
    return rep


# ============================================================================ export / reimport
def export_names(oid):
    sp = SPEC[oid]
    return {"fbx": os.path.join(FBX_DIR, f"SM_{sp['file']}.fbx"),
            "fbx_lod1": os.path.join(FBX_DIR, f"SM_{sp['file']}_LOD1.fbx"),
            "glb": os.path.join(GLB_DIR, f"{sp['file']}.glb"),
            "glb_lod1": os.path.join(GLB_DIR, f"{sp['file']}_LOD1.glb")}


def export_stage():
    for oid in IDS:
        e = EXTRA[oid]
        names = export_names(oid)
        lod0 = [o.name for o in optic_objects(oid)]
        lod1 = [o.name for o in optic_objects(oid, 1)]
        rename = {f"{oid}_{k}": k for k in e["sockets"]}
        res = {}
        res["fbx"] = O.export_optic(BLEND, lod0, names["fbx"], rename=rename)
        res["glb"] = O.export_optic(BLEND, lod0, names["glb"], rename=rename)
        res["fbx_lod1"] = O.export_optic(BLEND, lod1, names["fbx_lod1"])
        imap = {k: v for k, v in INFO.get(oid, {}).get("lod1_image_map", {}).items()}
        res["glb_lod1"] = O.export_optic(BLEND, lod1, names["glb_lod1"], image_map=imap)
        INFO.setdefault(oid, {})["exports"] = {k: {"path": os.path.relpath(v["path"], PROJECT), "bytes": v["bytes"]}
                                               for k, v in res.items()}
        L.log(f"  export {oid}: " + ", ".join(f"{k} {v['bytes'] / 1e6:.2f} MB" for k, v in res.items()))


def reimport_stage():
    for oid in IDS:
        e = EXTRA[oid]
        names = export_names(oid)
        exp_socks = {k: tuple(round(x, 5) for x in s.matrix_world.translation) for k, s in e["sockets"].items()}
        exp_tris0 = L.tri_count(e["sm"]) + L.tri_count(e["glass_obj"]) + L.tri_count(e["reticle"])
        exp_tris1 = L.tri_count(e["sm_lod1"]) + L.tri_count(e["glass_lod1"])
        mn, mx = L.world_bbox_fast([e["sm"], e["glass_obj"], e["reticle"]])
        out = {}
        for key, path in names.items():
            r = O.reimport_optic(path)
            probs = []
            lod = 1 if key.endswith("lod1") else 0
            if r["tris"] != (exp_tris1 if lod else exp_tris0):
                probs.append(f"tris {r['tris']} != {exp_tris1 if lod else exp_tris0}")
            if lod == 0:
                if abs(r["bbox_min"][0] - mn[0]) > 1e-4 or abs(r["bbox_max"][2] - mx[2]) > 1e-4:
                    probs.append(f"bbox {r['bbox_min']} {r['bbox_max']} vs {list(mn)} {list(mx)}")
                got = {}
                for n, pos in r["empties"].items():
                    base = n.split(".")[0]
                    if base.startswith("SOCKET_"):
                        base = base[len("SOCKET_"):]
                    got[base] = pos
                for k, pos in exp_socks.items():
                    if k not in got:
                        probs.append(f"socket {k} missing")
                    elif max(abs(a - b) for a, b in zip(got[k], pos)) > 2e-5:
                        probs.append(f"socket {k} at {got[k]} != {pos}")
                for n, ax in r.get("empty_axes_x", {}).items():
                    if abs(ax[0] - 1.0) > 1e-5:
                        probs.append(f"socket {n} X axis {ax} not along +X")
            for m, d in r["materials"].items():
                for im in d["images"]:
                    if not im["ok"]:
                        probs.append(f"material {m}: image {im['name']} missing")
                if d["bsdf"].get("transmission", 0) > 0:
                    probs.append(f"material {m}: transmission {d['bsdf']['transmission']}")
            if key.startswith("glb"):
                aud = O.gltf_material_audit(path)
                r["gltf_material_audit"] = aud
                if aud["transmission_like_extensions"]:
                    probs.append(f"glTF transmission-like extensions {aud['transmission_like_extensions']}")
                for mname, md in aud["materials"].items():
                    if "Glass" in mname and md["alphaMode"] != "BLEND":
                        probs.append(f"{mname}: alphaMode {md['alphaMode']}")
                    if "Reticle" in mname:
                        if md["alphaMode"] != "BLEND":
                            probs.append(f"{mname}: alphaMode {md['alphaMode']}")
                        if md["doubleSided"]:
                            probs.append(f"{mname}: double sided (emitter would show from the front)")
                        bt = md["baseColorTexture"] or {}
                        if bt.get("wrapS") != 33071 or bt.get("wrapT") != 33071:
                            probs.append(f"{mname}: reticle sampler not CLAMP_TO_EDGE ({bt})")
            r["problems"] = probs
            out[key] = r
            L.log(f"  reimport {oid} {key}: {r['tris']} tris, {len(r['meshes'])} meshes, {len(r['empties'])} empties, "
                  f"problems {probs}")
        INFO.setdefault(oid, {})["reimport"] = out


# ============================================================================ mounting on the IV-7
RIFLE = {}


def bore_cm(v):
    """Rifle-frame metres -> IV-7 bore-frame cm."""
    hx, hy, hz = O.IV7["hold_bore_cm"]
    return (v[0] * 100 + hx, v[1] * 100 + hy, v[2] * 100 + hz)


def import_rifle_once():
    if RIFLE:
        return RIFLE
    arm, meshes = O.import_rifle(RIFLE_BLEND, RIFLE_TEX)
    RIFLE["arm"] = arm
    RIFLE["meshes"] = meshes
    RIFLE["visible"] = [o for o in meshes if not o.hide_render]
    RIFLE["by_name"] = {o.name.split(".")[0]: o for o in meshes}
    for c in ("IV7_LOD1", "IV7_LOD2", "IV7_Static"):
        if c in bpy.data.collections:
            bpy.data.collections[c].hide_render = True
    return RIFLE


def place(oid, mounted=True):
    sm = EXTRA[oid]["sm"]
    off = O.mount_offset_m(SPEC[oid]["x_mount"]) if mounted else Vector()
    sm.matrix_world = Matrix.Translation(off)
    bpy.context.view_layer.update()


def show_only(oids):
    for oid in IDS:
        c = COLS[oid]
        c.hide_render = oid not in oids
        c.hide_viewport = oid not in oids
    bpy.context.view_layer.update()


def near_parts(objs, parts, margin=0.03):
    mn, mx = L.world_bbox_fast(objs)
    out = []
    dg = bpy.context.evaluated_depsgraph_get()
    for p in parts:
        a, b = O.evaluated_bbox(p, dg)
        if all(a[i] <= mx[i] + margin and b[i] >= mn[i] - margin for i in range(3)):
            out.append(p)
    return out


def mount_stage():
    R = import_rifle_once()
    arm = R["arm"]
    res = {}
    ro = R["by_name"].get("Optic")
    for oid in IDS:
        show_only([oid])
        place(oid)
        e = EXTRA[oid]
        mesh_objs = [e["sm"], e["glass_obj"], e["reticle"]]
        d = {}
        for pose, (rear, front) in (("irons_folded_documented", (-90.0, -90.0)), ("irons_deployed", (0.0, 0.0)),
                                    ("rear_leaf_plus90_as_in_review_r1", (90.0, -90.0))):
            O.pose_bone_fold(arm, "rear_sight", rear)
            O.pose_bone_fold(arm, "front_sight", front)
            dg = bpy.context.evaluated_depsgraph_get()
            parts = near_parts(mesh_objs, R["visible"])
            cr = O.clearance_report([e["sm"]], parts, dg, probe=0.03)
            leaf = R["by_name"]["RearSightLeaf"]
            a, b = O.evaluated_bbox(leaf, dg)
            d[pose] = {"clearance": cr,
                       "intersecting_parts": sorted(k for k, v in cr.items() if v["intersecting_face_pairs"] > 0),
                       "rear_leaf_bbox_bore_cm": {"x": [round(bore_cm(a)[0], 2), round(bore_cm(b)[0], 2)],
                                                  "z": [round(bore_cm(a)[2], 2), round(bore_cm(b)[2], 2)]}}
        O.pose_bone_fold(arm, "rear_sight", 0.0)
        O.pose_bone_fold(arm, "front_sight", 0.0)
        # sockets in the rifle frame, sight axis vs bore
        S = {k: s.matrix_world.translation.copy() for k, s in e["sockets"].items()}
        ax = (S["socket_sight_axis_front"] - S["socket_sight_axis_rear"]).normalized()
        ang = math.degrees(ax.angle(Vector((1.0, 0.0, 0.0))))
        rn = e["reticle"].matrix_world.to_3x3() @ e["reticle"].data.polygons[0].normal
        ret_ang = math.degrees(rn.normalized().angle(Vector((-1.0, 0.0, 0.0))))
        bore_z = -O.IV7["hold_bore_cm"][2] / 100.0
        up = d["irons_folded_documented"]["clearance"].get("UpperReceiver", {})
        d.update({
            "socket_rail_rifle_m": [round(v, 5) for v in S["socket_rail"]],
            "socket_eye_rifle_m": [round(v, 5) for v in S["socket_eye"]],
            "socket_eye_bore_cm": [round(v, 3) for v in bore_cm(S["socket_eye"])],
            "sight_axis_over_bore_cm_measured": round((S["socket_eye"].z - bore_z) * 100, 4),
            "sight_axis_angle_to_bore_deg": round(ang, 6),
            "reticle_normal_angle_to_axis_deg": round(ret_ang, 6),
            "lug_slots_bore_x_cm": [round(SPEC[oid]["x_mount"] + x, 3) for x in SPEC[oid]["lugs"]],
            "lugs_on_slot_centres": all(O.on_slot(round(SPEC[oid]["x_mount"] + x, 6)) for x in SPEC[oid]["lugs"]),
            "rail_contact_min_gap_mm": up.get("min_distance_mm"),
            "rail_intersections": up.get("intersecting_face_pairs"),
        })
        if oid == "IVR1" and ro is not None:
            dg = bpy.context.evaluated_depsgraph_get()
            a0, b0 = O.evaluated_bbox(ro, dg)
            a1, b1 = L.world_bbox_fast([e["sm"]])
            d["vs_rifle_optic_bbox_delta_mm"] = {"min": [round((a1[i] - a0[i]) * 1000, 2) for i in range(3)],
                                                 "max": [round((b1[i] - b0[i]) * 1000, 2) for i in range(3)]}
            ads = arm.data.bones["socket_ads"].head_local
            d["socket_eye_vs_rifle_socket_ads_mm"] = [round((S["socket_eye"][i] - ads[i]) * 1000, 3) for i in range(3)]
        res[oid] = d
        L.log(f"  mount {oid}: axis {ang:.6f} deg, rail gap {d['rail_contact_min_gap_mm']} mm, intersections folded "
              f"{d['irons_folded_documented']['intersecting_parts']}, deployed {d['irons_deployed']['intersecting_parts']}")
        place(oid, mounted=False)
    show_only(IDS)
    for oid in IDS:
        INFO.setdefault(oid, {})["mount"] = res[oid]
    return res


# ============================================================================ renders
GAME_ADS_VFOV = 50.5 * 0.82          # Web/src/data/weapons.json: viewModel fovVerticalDeg x adsFovMultiplier


def hfov_from_vfov(vfov_deg, aspect):
    return math.degrees(2 * math.atan(math.tan(math.radians(vfov_deg) / 2) * aspect))


def res(w, h):
    return (int(w * RES_SCALE), int(h * RES_SCALE))


def samples(n):
    return max(8, int(n * (0.4 if QUICK else 1.0)))


def studio(center, radius):
    L.clear_lights_cameras()
    L.studio_lighting(center, radius)
    rc = bpy.data.collections.get("IV_Range")
    if rc:
        rc.hide_render = True


def range_on(eye):
    L.clear_lights_cameras()
    rc = bpy.data.collections.get("IV_Range")
    if rc:
        for o in list(rc.objects):
            bpy.data.objects.remove(o, do_unlink=True)
    O.range_scene(eye)
    bpy.data.collections["IV_Range"].hide_render = False


def one_sided_patch():
    for oid in IDS:
        for m in EXTRA[oid]["reticle"].data.materials:
            O.cycles_one_sided(m)


def label(path, text, sub=None):
    from PIL import Image, ImageDraw, ImageFont
    im = Image.open(path).convert("RGB")
    dr = ImageDraw.Draw(im)
    f = ImageFont.truetype(O.FONT_BOLD, max(14, im.width // 70))
    dr.text((16, 12), text, fill=(240, 240, 240), font=f, stroke_width=2, stroke_fill=(15, 15, 15))
    if sub:
        f2 = ImageFont.truetype(O.FONT_REG, max(12, im.width // 95))
        dr.text((16, 16 + f.size + 4), sub, fill=(220, 220, 220), font=f2, stroke_width=2, stroke_fill=(15, 15, 15))
    im.save(path)


def centre_guides(path, color=(0, 120, 255)):
    from PIL import Image, ImageDraw
    im = Image.open(path).convert("RGB")
    dr = ImageDraw.Draw(im)
    W, H = im.size
    for a, b in (((W / 2, 0), (W / 2, 14)), ((W / 2, H - 14), (W / 2, H)), ((0, H / 2), (14, H / 2)),
                 ((W - 14, H / 2), (W, H / 2))):
        dr.line([a, b], fill=color, width=3)
    im.save(path)


def reticle_pixels(path, box=None):
    """Red-dominant (illuminated reticle) pixels: centroid offset from the image centre and radial
    profile.  box = (x0, y0, x1, y1) restricts the search."""
    from PIL import Image
    a = np.asarray(Image.open(path).convert("RGB")).astype(np.float64) / 255.0
    H, W = a.shape[:2]
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    m = (r > 0.35) & (r > 1.8 * g) & (r > 1.8 * b)
    if box:
        mm = np.zeros_like(m)
        x0, y0, x1, y1 = box
        mm[y0:y1, x0:x1] = m[y0:y1, x0:x1]
        m = mm
    ys, xs = np.nonzero(m)
    if len(xs) == 0:
        return {"red_pixels": 0}
    cx, cy = xs.mean() + 0.5, ys.mean() + 0.5
    rr = np.hypot(xs + 0.5 - W / 2, ys + 0.5 - H / 2)
    out = {"red_pixels": int(len(xs)), "centroid_offset_px": [round(cx - W / 2, 2), round(cy - H / 2, 2)],
           "radius_px_p50": round(float(np.median(rr)), 2), "radius_px_max": round(float(rr.max()), 2),
           "radius_px_min": round(float(rr.min()), 2)}
    if len(xs) >= 12:
        # algebraic (Kasa) circle fit: robust centring even if part of a ring washes out
        X = xs + 0.5 - W / 2
        Y = ys + 0.5 - H / 2
        Amat = np.column_stack([X, Y, np.ones_like(X)])
        bvec = X * X + Y * Y
        c, *_ = np.linalg.lstsq(Amat, bvec, rcond=None)
        xc, yc = c[0] / 2, c[1] / 2
        rad = math.sqrt(max(c[2] + xc * xc + yc * yc, 0.0))
        out["circle_fit"] = {"centre_offset_px": [round(float(xc), 3), round(float(yc), 3)], "radius_px": round(rad, 3)}
    return out


def eye_camera(oid, vfov, aspect, name="eye"):
    eye = EXTRA[oid]["sockets"]["socket_eye"].matrix_world.translation.copy()
    hf = hfov_from_vfov(vfov, aspect)
    cam = L.camera(name, eye, eye + Vector((1.0, 0.0, 0.0)), fov_deg=hf, clip_start=0.002, clip_end=4000.0)
    return cam, eye, hf


def render_mounted(oid):
    R = import_rifle_once()
    show_only([oid])
    place(oid)
    O.pose_bone_fold(R["arm"], "rear_sight", -90.0)
    O.pose_bone_fold(R["arm"], "front_sight", -90.0)
    e = EXTRA[oid]
    mn, mx = L.world_bbox_fast([e["sm"]])
    rail_z = O.mount_offset_m(0)[2]
    bmin = Vector((mn.x - 0.07, 0.0, rail_z - 0.075))
    bmax = Vector((mx.x + 0.07, 0.0, mx.z + 0.012))
    c = (bmin + bmax) / 2
    studio(c, (bmax - bmin).length / 2)
    out = {}
    cam = L.camera_ortho("side", 'RIGHT', Vector((bmin.x, -0.03, bmin.z)), Vector((bmax.x, 0.03, bmax.z)),
                         aspect=16 / 9, margin=1.04)
    p = os.path.join(PREV_DIR, f"{oid}_mounted_side.png")
    L.render(p, cam, res(1600, 900), samples(64))
    label(p, f"{SPEC[oid]['model']} on IV-7 (right side)", f"sight axis {AXIS[oid] + 3.0:.2f} cm over the bore; "
          f"irons folded (rear_sight / front_sight -90 deg)")
    out["side"] = p
    oc = (mn + mx) / 2
    size = (mx - mn).length
    d = Vector((-0.78, 0.60, 0.40)).normalized()
    cam = L.camera("q34", oc + d * max(size, 0.13) * 3.6, oc + Vector((0.05, 0, -0.025)), fov_deg=34)
    p = os.path.join(PREV_DIR, f"{oid}_mounted_34.png")
    L.render(p, cam, res(1600, 900), samples(64))
    label(p, f"{SPEC[oid]['model']} on IV-7 (3/4 rear left)")
    out["q34"] = p
    O.pose_bone_fold(R["arm"], "rear_sight", 0.0)
    O.pose_bone_fold(R["arm"], "front_sight", 0.0)
    place(oid, mounted=False)
    return out


def render_through(oid):
    """View through the optic from socket_eye (mounted on the IV-7, outdoor range)."""
    R = import_rifle_once()
    show_only([oid])
    place(oid)
    O.pose_bone_fold(R["arm"], "rear_sight", -90.0)
    O.pose_bone_fold(R["arm"], "front_sight", -90.0)
    e = EXTRA[oid]
    sp = SPEC[oid]
    eye = e["sockets"]["socket_eye"].matrix_world.translation.copy()
    range_on(eye)
    out = {}
    W, H = res(1600, 900)
    cam, eye, hf = eye_camera(oid, GAME_ADS_VFOV, W / H)
    p_game = os.path.join(PREV_DIR, f"{oid}_through_game_fov.png")
    L.render(p_game, cam, (W, H), samples(48))
    out["game_fov"] = p_game
    meta = RET[oid]
    unit_rad = O.RAD_PER_UNIT[meta["units"]]
    if sp["mag"] <= 1.0:
        vz = 4.5
        cam, _, hfz = eye_camera(oid, vz, W / H, "eye_zoom")
        p_zoom = os.path.join(PREV_DIR, f"{oid}_through_zoom.png")
        L.render(p_zoom, cam, (W, H), samples(48))
        px_per_rad = (H / 2) / math.tan(math.radians(vz) / 2)
        m = reticle_pixels(p_zoom)
        if oid == "IVH1":
            m["expected_ring_radius_px"] = round(px_per_rad * math.tan(32.5 * unit_rad), 2)
            m["expected_ring_stroke_px"] = round(px_per_rad * 2.0 * unit_rad, 2)
            m["expected_dot_diameter_px"] = round(px_per_rad * 1.0 * unit_rad, 2)
        else:
            m["expected_dot_radius_px"] = round(px_per_rad * 1.0 * unit_rad, 2)
        m["zoom_vfov_deg"] = vz
        m["px_per_moa_in_zoom_render"] = round(px_per_rad * O.RAD_PER_UNIT["MOA"], 4)
        mg = reticle_pixels(p_game)
        mg["px_per_moa_in_game_fov_render"] = round((H / 2) / math.tan(math.radians(GAME_ADS_VFOV) / 2)
                                                    * O.RAD_PER_UNIT["MOA"], 4)
        out["zoom"] = p_zoom
        out["measure_zoom"] = m
        out["measure_game"] = mg
        for pth in (p_game, p_zoom):
            centre_guides(pth)
        label(p_game, f"{sp['model']}: view from socket_eye, game ADS FOV {GAME_ADS_VFOV:.1f} deg (vertical)",
              f"eye at bore x {sp.get('eye_bore_x', '')} cm (= IV-7 socket_ads x); reticle = texture on the reticle sheet, seen through the thin glass")
        label(p_zoom, f"{sp['model']}: same eye point, {vz} deg vertical FOV (crispness / centring check)",
              f"100 m board on the sight axis (25/50/200/300/400 m boards staggered sideways); blue ticks = image centre")
    else:
        # emulate the runtime picture-in-picture path: zoomed render (world only) composited into
        # the ocular disc with the reticle at its exact angular scale and the eyebox vignette
        true_fov = math.radians(sp["true_fov_deg"])
        app_half = math.atan(sp["mag"] * math.tan(true_fov / 2))
        lens_half = math.atan(e["info"]["lens_radius"] / sp["eye_relief"])
        half = min(app_half, lens_half)
        r_px = (W / 2) * math.tan(half) / math.tan(math.radians(hf) / 2)
        true_used = 2 * math.atan(math.tan(half) / sp["mag"])
        show_only([])
        for o in R["visible"]:
            o.hide_render = True
        D = int(math.ceil(2 * r_px)) + 4
        zoom_h = 2 * math.degrees(math.atan(math.tan(true_used / 2) * D / (2 * r_px)))
        zc = L.camera("zoom", eye, eye + Vector((1, 0, 0)), fov_deg=zoom_h, clip_start=0.05, clip_end=4000.0)
        p_zr = os.path.join(PREV_DIR, f"{oid}_through_zoomsrc.png")
        L.render(p_zr, zc, (D, D), samples(32))
        true_units = 2 * math.tan(true_used / 2) / unit_rad        # gnomonic: linear in tan(angle)
        p_pip = os.path.join(PREV_DIR, f"{oid}_through_pip.png")
        O.pip_composite(p_game, p_zr, meta, p_pip, (W / 2, H / 2), r_px, true_units,
                        label=f"{sp['model']} {sp['mag']:g}x: eye view at game ADS FOV, eyepiece = runtime PiP emulation")
        # detail: eyepiece only, large
        Dd = int(790 * RES_SCALE)
        rd = Dd / 2 - 6
        Dz = int(math.ceil(2 * rd)) + 4
        zoom_h2 = 2 * math.degrees(math.atan(math.tan(true_used / 2) * Dz / (2 * rd)))
        zc2 = L.camera("zoom2", eye, eye + Vector((1, 0, 0)), fov_deg=zoom_h2, clip_start=0.05, clip_end=4000.0)
        p_zr2 = os.path.join(PREV_DIR, f"{oid}_through_zoomsrc_detail.png")
        L.render(p_zr2, zc2, (Dz, Dz), samples(32))
        from PIL import Image
        blank = os.path.join(PREV_DIR, f"_blank_{oid}.png")
        Image.new("RGB", (Dd, Dd), (0, 0, 0)).save(blank)
        p_det = os.path.join(PREV_DIR, f"{oid}_through_eyepiece.png")
        O.pip_composite(blank, p_zr2, meta, p_det, (Dd / 2, Dd / 2), rd, true_units,
                        label=f"{sp['model']} eyepiece ({math.degrees(true_used):.2f} deg true FOV)")
        # centre of the field, 4x enlarged (same composite at 4x px/unit) for reticle crispness
        zoom_h3 = 2 * math.degrees(math.atan(math.tan(true_used / 2) / 4.0 * Dz / (2 * rd)))
        zc3 = L.camera("zoom3", eye, eye + Vector((1, 0, 0)), fov_deg=zoom_h3, clip_start=0.05, clip_end=4000.0)
        p_zr3 = os.path.join(PREV_DIR, f"{oid}_through_zoomsrc_centre.png")
        L.render(p_zr3, zc3, (Dz, Dz), samples(32))
        p_c4 = os.path.join(PREV_DIR, f"_centre4_{oid}.png")
        O.pip_composite(blank, p_zr3, meta, p_c4, (Dd / 2, Dd / 2), rd, true_units / 4.0,
                        vignette_strength=0.0, label="centre of the field, 4x enlarged")
        os.remove(blank)
        mc = reticle_pixels(p_c4)
        ppu_c4 = 2 * rd / (true_units / 4.0)
        tex_c = RET[oid]["metrics"].get("lit_centroid_offset_px", [0.0, 0.0])
        if mc.get("red_pixels"):
            got = [mc["centroid_offset_px"][0] / ppu_c4, mc["centroid_offset_px"][1] / ppu_c4]
            want = [tex_c[0] / RET[oid]["px_per_unit"], tex_c[1] / RET[oid]["px_per_unit"]]
            mc["lit_centroid_offset_units"] = [round(v, 4) for v in got]
            mc["expected_lit_centroid_offset_units"] = [round(v, 4) for v in want]
            mc["centring_error_units"] = round(math.hypot(got[0] - want[0], got[1] - want[1]), 4)
            mc["px_per_unit_centre_panel"] = round(ppu_c4, 3)
        centre_guides(p_det)
        centre_guides(p_c4)
        L.side_by_side([p_det, p_c4], p_det, labels=[
            f"{sp['model']} {sp['mag']:g}x eyepiece: zoomed render + reticle at its angular scale + eyebox vignette",
            f"centre x4 ({2 * rd / true_units * 4:.2f} px per {meta['units']})"])
        os.remove(p_c4)
        for o in R["visible"]:
            o.hide_render = False
        show_only([oid])
        out.update({"pip": p_pip, "eyepiece": p_det, "zoom_src": p_zr, "disc_radius_px": round(r_px, 2),
                    "true_fov_used_deg": round(math.degrees(true_used), 4),
                    "apparent_half_deg": round(math.degrees(app_half), 3),
                    "ocular_half_angle_deg": round(math.degrees(lens_half), 3),
                    "px_per_unit_in_eyepiece_detail": round(2 * rd / true_units, 4)})
        out["measure_eyepiece_centre_x4"] = mc
        centre_guides(p_game)
        label(p_game, f"{sp['model']}: raw mesh view from socket_eye (static reticle sheet fallback, no PiP)")
    O.pose_bone_fold(R["arm"], "rear_sight", 0.0)
    O.pose_bone_fold(R["arm"], "front_sight", 0.0)
    place(oid, mounted=False)
    bpy.data.collections["IV_Range"].hide_render = True
    return out


def render_front(oid):
    """Closed-emitter check: look into the front of the optic along the axis (studio light),
    with the reticle sheet present and hidden; the two renders must match (no dot visible)."""
    show_only([oid])
    place(oid, mounted=False)
    for o in RIFLE.get("visible", []):
        o.hide_render = True
    e = EXTRA[oid]
    f = e["sockets"]["socket_sight_axis_front"].matrix_world.translation.copy()
    mn, mx = L.world_bbox_fast([e["sm"]])
    studio((mn + mx) / 2, (mx - mn).length / 2)
    cam = L.camera("front", f + Vector((0.28, 0.0, 0.0)), f, fov_deg=16)
    p1 = os.path.join(PREV_DIR, f"{oid}_front_emitter_check.png")
    L.render(p1, cam, res(900, 900), samples(64))
    e["reticle"].hide_render = True
    p2 = os.path.join(PREV_DIR, f"_front_noreticle_{oid}.png")
    L.render(p2, cam, res(900, 900), samples(64))
    e["reticle"].hide_render = False
    from PIL import Image
    a = np.asarray(Image.open(p1).convert("RGB")).astype(np.float64)
    b = np.asarray(Image.open(p2).convert("RGB")).astype(np.float64)
    diff = np.abs(a - b)
    os.remove(p2)
    rw = e["reticle"].matrix_world
    cam_p = cam.matrix_world.translation
    front_facing = 0
    for poly in e["reticle"].data.polygons:
        c = rw @ poly.center
        n = (rw.to_3x3() @ poly.normal).normalized()
        if n.dot(cam_p - c) > 0:
            front_facing += 1
    m = {"reticle_faces_facing_front_camera": front_facing, "reticle_faces": len(e["reticle"].data.polygons),
         "max_abs_diff_8bit": float(diff.max()), "mean_abs_diff_8bit": round(float(diff.mean()), 4),
         "pixels_diff_over_8": int((diff.max(axis=2) > 8).sum()), "red_reticle_pixels": reticle_pixels(p1)["red_pixels"]}
    # strong test: drive the reticle emission bright green (x100); from the front nothing may show,
    # from the eye (control) the dot must show.  The material is restored afterwards.
    mat = e["reticle"].data.materials[0]
    bs = mat.node_tree.nodes["BSDF"]
    link = bs.inputs['Emission Color'].links[0]
    src_sock = link.from_socket
    mat.node_tree.links.remove(link)
    old_col = tuple(bs.inputs['Emission Color'].default_value)
    old_str = bs.inputs['Emission Strength'].default_value
    bs.inputs['Emission Color'].default_value = (0.0, 1.0, 0.0, 1.0)
    bs.inputs['Emission Strength'].default_value = RETICLE_EMISSION * 100.0

    def green_px(path):
        g = np.asarray(Image.open(path).convert("RGB")).astype(np.float64) / 255.0
        return int(((g[..., 1] > 0.35) & (g[..., 1] > 1.8 * g[..., 0]) & (g[..., 1] > 1.8 * g[..., 2])).sum())
    p3 = os.path.join(PREV_DIR, f"_front_green_{oid}.png")
    L.render(p3, cam, res(450, 450), samples(24))
    eye = e["sockets"]["socket_eye"].matrix_world.translation.copy()
    cam_e = L.camera("eyechk", eye, eye + Vector((1.0, 0.0, 0.0)), fov_deg=6.0, clip_start=0.002)
    p4 = os.path.join(PREV_DIR, f"_eye_green_{oid}.png")
    L.render(p4, cam_e, res(450, 450), samples(24))
    m["green_x100_test"] = {"front_green_pixels": green_px(p3), "eye_side_control_green_pixels": green_px(p4)}
    os.remove(p3)
    os.remove(p4)
    bs.inputs['Emission Color'].default_value = old_col
    bs.inputs['Emission Strength'].default_value = old_str
    mat.node_tree.links.new(src_sock, bs.inputs['Emission Color'])
    for o in RIFLE.get("visible", []):
        o.hide_render = False
    label(p1, f"{SPEC[oid]['model']} from the front (closed emitter check)",
          f"with vs without reticle sheet: max diff {m['max_abs_diff_8bit']:.0f}/255, "
          f"{m['pixels_diff_over_8']} px > 8")
    return {"path": p1, **m}


def render_overlay():
    """IV-S6 full-screen ADS overlay over a zoomed render (camera vfov = overlay field)."""
    oid = "IVS6"
    if oid not in IDS:
        return None
    R = import_rifle_once()
    e = EXTRA[oid]
    show_only([oid])
    place(oid)
    eye = e["sockets"]["socket_eye"].matrix_world.translation.copy()
    range_on(eye)
    show_only([])
    for o in R["visible"]:
        o.hide_render = True
    W, H = res(1600, 900)
    ov = INFO[oid]["overlay"]
    vf = ov["vertical_fov_deg_when_drawn_full_height"]
    cam = L.camera("ovl", eye, eye + Vector((1, 0, 0)), fov_deg=hfov_from_vfov(vf, W / H), clip_start=0.05,
                   clip_end=4000.0)
    p_src = os.path.join(PREV_DIR, f"{oid}_overlay_src.png")
    L.render(p_src, cam, (W, H), samples(32))
    from PIL import Image
    src = Image.open(p_src).convert("RGBA")
    ovl = Image.open(os.path.join(PROJECT, "Art", "Textures", "Optics", oid, f"T_{oid}_ADS_Overlay.png")).convert("RGBA")
    ovl = ovl.resize((H, H), Image.LANCZOS)
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    layer.paste(ovl, ((W - H) // 2, 0))
    comp = Image.alpha_composite(src, layer)
    # outside the square: black
    mask = Image.new("L", (W, H), 0)
    mask.paste(255, ((W - H) // 2, 0, (W - H) // 2 + H, H))
    canvas.paste(comp, (0, 0), mask)
    p = os.path.join(PREV_DIR, f"{oid}_ads_overlay_fullscreen.png")
    canvas.convert("RGB").save(p)
    label(p, "IV-S6 full-screen ADS overlay (T_IVS6_ADS_Overlay.png) over a zoomed render",
          f"camera vertical FOV {vf:.3f} deg = overlay field {RET[oid]['field_units']:.0f} mrad; eyebox = "
          f"{SPEC[oid]['true_fov_deg']} deg true FOV")
    centre_guides(p)
    for o in R["visible"]:
        o.hide_render = False
    show_only(IDS)
    place(oid, mounted=False)
    bpy.data.collections["IV_Range"].hide_render = True
    m = reticle_pixels(p)
    return {"path": p, "measure": m}


def render_lineup(lod=0):
    """All optics, unmounted, in two rows (studio)."""
    import bpy_extras
    show_only(IDS)
    R = RIFLE
    for o in R.get("visible", []):
        o.hide_render = True
    rows = [["IVH1", "IVR1", "IVP2"], ["IVS3", "IVS6"]]
    placed = {}
    for ri, row in enumerate(rows):
        x = 0.0
        for oid in row:
            if oid not in IDS:
                continue
            e = EXTRA[oid]
            objs = optic_objects(oid, lod)
            root = objs[0]
            mn, mx = L.world_bbox_fast([root])
            off = Vector((x - mn.x, 0.0, (1 - ri) * 0.13))
            root.matrix_world = Matrix.Translation(off)
            placed[oid] = (root, off, mn, mx)
            x += (mx.x - mn.x) + 0.045
    if lod == 1:
        for oid in IDS:
            COLS[oid].hide_render = True
            bpy.data.collections[f"{oid}_LOD1"].hide_render = False
    bpy.context.view_layer.update()
    allo = [v[0] for v in placed.values()]
    mn, mx = L.world_bbox_fast(allo)
    c = (mn + mx) / 2
    studio(c, (mx - mn).length / 2)
    d = Vector((0.16, -1.0, 0.26)).normalized()
    cam = L.camera("lineup", c + d * (mx - mn).length * 1.55, c, fov_deg=36)
    p = os.path.join(PREV_DIR, f"optics_lineup{'_LOD1' if lod else ''}.png")
    L.render(p, cam, res(1600, 900), samples(64))
    from PIL import Image, ImageDraw, ImageFont
    im = Image.open(p).convert("RGB")
    dr = ImageDraw.Draw(im)
    fnt = ImageFont.truetype(O.FONT_BOLD, max(14, im.width // 75))
    sc = bpy.context.scene
    for oid, (root, off, a, b) in placed.items():
        top = Vector(((a.x + b.x) / 2, 0, b.z)) + off
        uv = bpy_extras.object_utils.world_to_camera_view(sc, cam, top)
        px, py = uv.x * im.width, (1 - uv.y) * im.height
        sp = SPEC[oid]
        t = f"{sp['model']} {sp['mag']:g}x"
        dr.text((px - 60, py - 34), t, fill=(235, 235, 235), font=fnt, stroke_width=2, stroke_fill=(20, 20, 20))
    f2 = ImageFont.truetype(O.FONT_REG, max(12, im.width // 90))
    dr.text((16, im.height - 16 - f2.size), "IRON VALLEY optics" + (" - LOD1 (third person)" if lod else " - LOD0") +
            ": IV-H1 holo 1x, IV-R1 red dot 1x, IV-P2 prism 2x, IV-S3 scope 3x, IV-S6 scope 6x40",
            fill=(225, 225, 225), font=f2, stroke_width=2, stroke_fill=(20, 20, 20))
    im.save(p)
    for oid, (root, off, a, b) in placed.items():
        root.matrix_world = Matrix.Identity(4)
    if lod == 1:
        for oid in IDS:
            COLS[oid].hide_render = False
            bpy.data.collections[f"{oid}_LOD1"].hide_render = True
    for o in R.get("visible", []):
        o.hide_render = False
    bpy.context.view_layer.update()
    return p


def render_stage():
    one_sided_patch()
    import_rifle_once()
    out = {}
    for oid in IDS:
        o = {}
        if "mounted" in RENDERS:
            o["mounted"] = render_mounted(oid)
        if "through" in RENDERS:
            o["through"] = render_through(oid)
        if "front" in RENDERS and oid in ("IVR1", "IVH1"):
            o["front"] = render_front(oid)
        out[oid] = o
        INFO.setdefault(oid, {}).setdefault("renders", {}).update(o)     # merge: partial re-renders keep the rest
    if "overlay" in RENDERS:
        ov = render_overlay()
        if ov:
            INFO["IVS6"].setdefault("renders", {})["overlay"] = ov
    if "lineup" in RENDERS:
        out["lineup"] = render_lineup(0)
        out["lineup_lod1"] = render_lineup(1)
    return out


# ============================================================================ config / report
def rifle_m(xyz_bore_cm):
    hx, hy, hz = O.IV7["hold_bore_cm"]
    return [round((xyz_bore_cm[0] - hx) / 100, 5), round((xyz_bore_cm[1] - hy) / 100, 5),
            round((xyz_bore_cm[2] - hz) / 100, 5)]


def gltf_vec(v):
    return [round(v[0], 5) + 0.0, round(v[2], 5) + 0.0, round(-v[1], 5) + 0.0]


def aperture_m(ap):
    return {(k[:-3] + "_m" if k.endswith("_cm") else k): (round(v / 100.0, 5) if k.endswith("_cm") else v)
            for k, v in ap.items()}


def config_stage():
    optics = []
    for oid in IDS:
        sp = SPEC[oid]
        e = EXTRA[oid]
        info = e["info"]
        meta = RET[oid]
        A = AXIS[oid]
        socks = {k: [round(x, 5) for x in s.matrix_world.translation] for k, s in e["sockets"].items()}
        er_cm = info["ocular_x"] - info["eye_x"]
        if sp["mag"] > 1.0:
            eyebox_r = sp["objective_mm"] / sp["mag"] / 2 / 1000.0          # exit-pupil radius
            true_fov = sp["true_fov_deg"]
            app = 2 * math.degrees(math.atan(sp["mag"] * math.tan(math.radians(true_fov) / 2)))
        else:
            eyebox_r = info["lens_radius"] / 100.0
            true_fov = None
            app = None
        tex_rel = lambda p: os.path.relpath(p, PROJECT)
        feats = [el for el in meta["elements"]]
        mount = INFO.get(oid, {}).get("mount", {})
        ex = export_names(oid)
        d = {
            "id": oid,
            "model": sp["model"],
            "name_cs": sp["name_cs"],
            "short_cs": sp["short_cs"],
            "kind": sp["kind"],
            "magnification": sp["mag"],
            "eye_relief_m": round(er_cm / 100.0, 4),
            "eyebox_radius_m": round(eyebox_r, 5),
            "eyebox_note": ("exit-pupil radius (objective / magnification / 2); outside it the image vignettes"
                            if sp["mag"] > 1 else "1x: no exit pupil; the window / lens half height limits the head position"),
            "lens_radius_m": round(info["lens_radius"] / 100.0, 5),
            "aperture": aperture_m(info["aperture"]),
            "objective_clear_aperture_m": round(sp["objective_mm"] / 1000.0, 4) if sp["mag"] > 1 else None,
            "true_fov_deg": true_fov,
            "apparent_fov_deg": round(app, 3) if app else None,
            "sight_height_over_bore_m": round((A + BORE_TO_RAIL_CM) / 100.0, 4),
            "sight_height_over_rail_m": round(A / 100.0, 4),
            "zero_m": sp["zero_m"],
            "ads_time_s": sp["ads_time_s"],
            "recommended_range_m": sp["range_m"],
            "mass_kg": sp["mass_kg"],
            "reticle": {
                "texture": tex_rel(meta["paths"]["base_rgba"]),
                "emissive": tex_rel(meta["paths"]["emissive_rgb"]),
                "sdf": tex_rel(meta["paths"]["sdf_rgb"]),
                "json": tex_rel(os.path.join(TEX_ROOT, oid, f"T_{oid}_Reticle.json")),
                "units": meta["units"],
                "size_px": meta["size_px"][0],
                "field_units": meta["field_units"],
                "px_per_unit": round(meta["px_per_unit"], 6),
                "px_per_moa": round(meta["px_per_moa"], 6),
                "px_per_mrad": round(meta["px_per_mrad"], 6),
                "angular_space": "object space (angle at the target); apparent = x magnification",
                "axis": "texture centre = point of aim; row 0 = up; u = shooter's right",
                "colour_srgb": list(RED),
                "features": feats,
                "type": meta.get("reticle_type"),
                "scale_rule": ("screen_px_per_texture_px = (screen_px_per_rad_of_the_camera_that_shows_the_target) "
                               "x unit_in_rad / px_per_unit; unit_in_rad = " + f"{O.RAD_PER_UNIT[meta['units']]:.9g}"),
                "render_hints": {"collimated": True, "min_dot_diameter_px": 2.5, "min_stroke_px": 1.25,
                                 "note": "use the SDF texture to keep strokes >= min_stroke_px when true scale is sub-pixel"},
            },
            "sockets_optic_frame_m": {"blender_zup": socks, "gltf_yup": {k: gltf_vec(v) for k, v in socks.items()}},
            "mount_on_iv7": {
                "socket_rail_bore_frame_cm": [sp["x_mount"], 0.0, BORE_TO_RAIL_CM],
                "socket_rail_rifle_m": {"blender_zup": rifle_m((sp["x_mount"], 0.0, BORE_TO_RAIL_CM)),
                                        "gltf_yup": gltf_vec(rifle_m((sp["x_mount"], 0.0, BORE_TO_RAIL_CM)))},
                "socket_eye_rifle_m": {"blender_zup": mount.get("socket_eye_rifle_m"),
                                       "gltf_yup": gltf_vec(mount["socket_eye_rifle_m"]) if mount.get("socket_eye_rifle_m") else None},
                "recoil_lug_slots_bore_x_cm": [round(sp["x_mount"] + x, 2) for x in sp["lugs"]],
                "irons": "fold both leaves (rear_sight, front_sight: -90 deg about bone-local Y = top towards the stock); "
                         "see OPTICS_spec.md",
                "hide_rifle_nodes": ["^Optic"],
            },
            "assets": {k: os.path.relpath(v, PROJECT) for k, v in ex.items()},
            "blend": os.path.relpath(BLEND, PROJECT),
            "node_names": {"body": e["sm"].name, "glass": e["glass_obj"].name, "reticle": e["reticle"].name,
                           "lod1_body": e["sm_lod1"].name},
        }
        if oid == "IVS6" and "overlay" in INFO.get(oid, {}):
            ov = INFO[oid]["overlay"]
            d["ads_overlay"] = {"texture": os.path.relpath(ov["path"], PROJECT), "size_px": ov["size_px"][0],
                                "px_per_mrad": round(ov["px_per_unit"], 6), "field_mrad": ov["field_units"],
                                "eyebox_radius_mrad": round(ov["eyebox_radius_units"], 4),
                                "eyebox_radius_fraction_of_height": round(ov["eyebox_radius_fraction_of_size"], 5),
                                "vertical_fov_deg_when_drawn_full_height": round(ov["vertical_fov_deg_when_drawn_full_height"], 5),
                                "usage": ov["usage"]}
        if sp["mag"] > 1:
            d["runtime_view"] = {"pip_camera_vfov_deg_over_ocular_disc": true_fov,
                                 "ocular_uv": "the glass ocular sheet's UVs map the lens disc to 0..1 (render target)"}
        optics.append(d)
    cfg = {
        "_comment": ("Optiky pro IV-7 (generuje Art/Source/Blender/weapons/optics.py; ručně neupravovat). "
                     "Délky v metrech, úhly ve stupních, síťky v MOA / mrad (úhel v prostoru cíle). "
                     "Popis a pravidla vykreslení: Art/Reference/OPTICS_spec.md."),
        "version": 1,
        "default": "IVR1",
        "rifle": "iv7_carbine",
        "frames": {"blender_zup": "X muzzle, Y weapon left, Z up",
                   "gltf_yup": "X muzzle, Y up, Z weapon right (glTF export of the same data)"},
        "ballistics_reference": BALLISTICS,
        "optics": optics,
    }
    os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
    with open(CONFIG, "w") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    L.log(f"config -> {CONFIG}")
    return cfg


def jsonable(x):
    if isinstance(x, dict):
        return {str(k): jsonable(v) for k, v in x.items() if not str(k).startswith("_")}
    if isinstance(x, (list, tuple)):
        return [jsonable(v) for v in x]
    if isinstance(x, (np.floating, np.integer)):
        return x.item()
    if isinstance(x, Vector):
        return [round(v, 6) for v in x]
    if isinstance(x, (str, int, float, bool)) or x is None:
        return x
    return str(x)


def write_report():
    rep = {"generated_by": "Art/Source/Blender/weapons/optics.py", "time": time.strftime("%Y-%m-%d %H:%M:%S"),
           "blender": bpy.app.version_string, "quick": QUICK, "stages": STAGES, "optics": {}}
    if os.path.exists(REPORT):
        try:
            with open(REPORT) as f:
                old = json.load(f)
            rep["optics"] = old.get("optics", {})
        except Exception:
            pass
    for oid in IDS:
        d = dict(INFO.get(oid, {}))
        d["reticle_meta"] = {k: v for k, v in RET[oid].items() if not k.startswith("_") and k != "paths"}
        rep["optics"][oid] = jsonable(d)
    with open(REPORT, "w") as f:
        json.dump(rep, f, indent=2)
    L.log(f"report -> {REPORT}")


# ============================================================================ main
def main():
    t0 = time.time()
    for d in (TEX_ROOT, FBX_DIR, GLB_DIR, PREV_DIR):
        os.makedirs(d, exist_ok=True)
    L.log(f"optics build  quick={QUICK}  stages={STAGES}  optics={IDS}")
    if "build" in STAGES or "review" in STAGES:
        L.reset_scene()
        L.CLEAN_DIST = 5e-4
        make_reticles()
        for oid in IDS:
            build(oid, seed=100 + 20 * ALL_IDS.index(oid))
            finalize(oid)
        if "review" in STAGES:
            review_stage()
            return
        if "bake" in STAGES:
            for oid in IDS:
                uv_bake(oid)
            purge_procedural()
        for oid in IDS:
            assemble(oid)
        make_overlay()
        purge_procedural(remove_attrs=False)
    else:
        load_saved()
        make_reticles()
        make_overlay()
    if "validate" in STAGES:
        validate_stage()
    if "save" in STAGES:
        bpy.context.scene.render.engine = 'CYCLES'
        bpy.ops.wm.save_as_mainfile(filepath=BLEND, relative_remap=True)
        L.log(f"saved {BLEND}")
    write_report()
    if "export" in STAGES:
        export_stage()
        write_report()
    if "reimport" in STAGES:
        reimport_stage()
        write_report()
    if "mount" in STAGES:
        mount_stage()
        write_report()
    if "render" in STAGES:
        render_stage()
        write_report()
    if "config" in STAGES:
        config_stage()
    L.log(f"optics done in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
