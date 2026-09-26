"""
ivlib -- Iron Valley shared Blender asset pipeline (bpy 4.5 LTS, headless).

One module, imported by every generator script under Art/Source/Blender/<category>/.
Everything here is deterministic: no function uses unseeded randomness.

Sections
--------
  1. Scene / units / render engine setup
  2. Geometry primitives (profile extrude, tube extrude, lathe, loft, sweep, 2D outlines)
  3. Mesh operations (boolean, bevel, weighted normals, triangulate, join, origin)
  4. Procedural PBR material presets (anodised aluminium, nitrided / phosphated steel,
     polymer, rubber, brass / copper, paint, glass, emissive) driven by a per-texture-set
     "mask" node group (edge / cavity / AO)
  5. UV helpers (multi-object smart project + pack, texel density)
  6. Baking (two-stage: masks first, then BaseColor / Roughness / Metallic / Normal) with
     ORM packing and DirectX normal generation (numpy), export-material swap
  7. LOD generation
  8. Validation report (JSON)
  9. Render helpers (studio + Nishita sky lighting, ortho / perspective cameras, clay
     override, contact sheet)
 10. Export (FBX tuned for Unreal, GLB) and re-import checks, executed in a clean
     subprocess ("jobs") so the calling scene is never mutated.

Conventions (project wide): metric, unit scale 1.0, 1 BU = 1 m, Z up.  Weapons: muzzle +X,
top +Z, weapon's right side -Y.  Textures: PBR metal/rough, BaseColor sRGB, Normal OpenGL
(+Y up; a DirectX variant is written next to it), ORM = R ambient occlusion, G roughness,
B metallic (linear).

Run as a script for jobs:  python3 ivlib.py --job /path/job.json
"""

import bpy
import bmesh
import json
import math
import os
import subprocess
import sys
import tempfile
import time
from mathutils import Vector, Matrix

import numpy as np

LIB_VERSION = "1.0.0"


def log(*args):
    print("[ivlib]", *args, flush=True)


# =============================================================================
# 1. Scene / units / engine
# =============================================================================

def reset_scene(threads=4, samples=64):
    """Empty factory scene, metric units (1 BU = 1 m), Cycles CPU."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    us = sc.unit_settings
    us.system = 'METRIC'
    us.scale_length = 1.0
    us.length_unit = 'CENTIMETERS'   # display only
    setup_cycles(sc, samples=samples, threads=threads)
    return sc


def setup_cycles(scene=None, samples=64, threads=4, denoise=True, seed=0):
    sc = scene or bpy.context.scene
    sc.render.engine = 'CYCLES'
    sc.cycles.device = 'CPU'
    sc.cycles.samples = samples
    sc.cycles.use_adaptive_sampling = True
    sc.cycles.adaptive_threshold = 0.02
    sc.cycles.use_denoising = denoise
    sc.cycles.denoiser = 'OPENIMAGEDENOISE'
    sc.cycles.seed = seed
    sc.cycles.max_bounces = 8
    sc.cycles.glossy_bounces = 4
    sc.cycles.transmission_bounces = 8
    sc.cycles.transparent_max_bounces = 8
    sc.render.threads_mode = 'FIXED'
    sc.render.threads = threads
    sc.view_settings.view_transform = 'AgX'
    sc.view_settings.look = 'AgX - Medium High Contrast'
    sc.view_settings.exposure = 0.0
    sc.render.film_transparent = False
    return sc


def collection(name, parent=None):
    """Get or create a collection linked under parent (default: scene root)."""
    col = bpy.data.collections.get(name)
    if col is None:
        col = bpy.data.collections.new(name)
    parent = parent or bpy.context.scene.collection
    if col.name not in [c.name for c in parent.children]:
        parent.children.link(col)
    return col


def link_to(obj, col):
    for c in list(obj.users_collection):
        c.objects.unlink(obj)
    col.objects.link(obj)
    return obj


def deselect_all():
    for o in bpy.context.view_layer.objects:
        o.select_set(False)


def select(objs, active=None):
    deselect_all()
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = active or (objs[0] if objs else None)


# =============================================================================
# 2. Geometry primitives
#    All functions create a new mesh object at identity transform with vertices in
#    world coordinates, linked to `col` (default: scene collection).  Units are whatever
#    the caller uses (the IV-7 script authors in centimetres and rescales at the end).
# =============================================================================

def _plane3(axis, u, v, d):
    """Map 2D profile coords (u, v) + depth d onto 3D for an extrusion axis."""
    if axis == 'Y':
        return Vector((u, d, v))      # profile in XZ
    if axis == 'X':
        return Vector((d, u, v))      # profile in YZ
    return Vector((u, v, d))          # 'Z': profile in XY


def bm_to_object(bm, name, col=None, recalc=True):
    if recalc:
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    (col or bpy.context.scene.collection).objects.link(ob)
    return ob


def _signed_area(pts):
    a = 0.0
    for i in range(len(pts)):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % len(pts)]
        a += x0 * y1 - x1 * y0
    return 0.5 * a


def poly_extrude(name, pts, axis='Y', d0=-0.5, d1=0.5, col=None):
    """Extrude a closed 2D outline (list of (u, v)) between depths d0..d1 along `axis`.
    axis 'Y': pts are (x, z) side profile; 'X': (y, z) section; 'Z': (x, y) plan."""
    bm = bmesh.new()
    r0 = [bm.verts.new(_plane3(axis, u, v, d0)) for u, v in pts]
    r1 = [bm.verts.new(_plane3(axis, u, v, d1)) for u, v in pts]
    n = len(pts)
    bm.faces.new(r0)
    bm.faces.new(list(reversed(r1)))
    for i in range(n):
        j = (i + 1) % n
        bm.faces.new((r0[i], r0[j], r1[j], r1[i]))
    return bm_to_object(bm, name, col)


def tube_extrude(name, outer, inner, axis='X', d0=0.0, d1=1.0, col=None):
    """Hollow prism: outer and inner closed outlines (same vertex count, same winding)."""
    assert len(outer) == len(inner)
    bm = bmesh.new()
    o0 = [bm.verts.new(_plane3(axis, u, v, d0)) for u, v in outer]
    o1 = [bm.verts.new(_plane3(axis, u, v, d1)) for u, v in outer]
    i0 = [bm.verts.new(_plane3(axis, u, v, d0)) for u, v in inner]
    i1 = [bm.verts.new(_plane3(axis, u, v, d1)) for u, v in inner]
    n = len(outer)
    for k in range(n):
        j = (k + 1) % n
        bm.faces.new((o0[k], o0[j], o1[j], o1[k]))
        bm.faces.new((i0[k], i1[k], i1[j], i0[j]))
        bm.faces.new((o0[k], i0[k], i0[j], o0[j]))
        bm.faces.new((o1[k], o1[j], i1[j], i1[k]))
    return bm_to_object(bm, name, col)


def _axis_point(axis, a, c0, c1, r, th):
    ct, st = math.cos(th), math.sin(th)
    if axis == 'X':
        return Vector((a, c0 + r * ct, c1 + r * st))
    if axis == 'Y':
        return Vector((c0 + r * ct, a, c1 + r * st))
    return Vector((c0 + r * ct, c1 + r * st, a))


def lathe(name, prof, segments=32, axis='X', center=(0.0, 0.0), phase=0.0,
          closed=False, cap=True, col=None):
    """Surface of revolution.  prof = [(a, r), ...] where a runs along `axis` and r is the
    radius.  r == 0 creates a pole.  closed=True treats the profile as a closed loop
    (e.g. out along the outside, back along the bore) and adds no caps."""
    bm = bmesh.new()
    rings = []
    for a, r in prof:
        if r <= 1e-9:
            rings.append([bm.verts.new(_axis_point(axis, a, center[0], center[1], 0.0, 0.0))])
        else:
            rings.append([bm.verts.new(_axis_point(axis, a, center[0], center[1], r,
                                                   phase + 2 * math.pi * s / segments))
                          for s in range(segments)])
    npr = len(rings)
    pairs = [(i, i + 1) for i in range(npr - 1)]
    if closed:
        pairs.append((npr - 1, 0))
    for i, j in pairs:
        A, B = rings[i], rings[j]
        if len(A) == 1 and len(B) == 1:
            continue
        if len(A) == 1:
            for s in range(segments):
                bm.faces.new((A[0], B[(s + 1) % segments], B[s]))
        elif len(B) == 1:
            for s in range(segments):
                bm.faces.new((A[s], A[(s + 1) % segments], B[0]))
        else:
            for s in range(segments):
                t = (s + 1) % segments
                bm.faces.new((A[s], A[t], B[t], B[s]))
    if cap and not closed:
        if len(rings[0]) > 1:
            bm.faces.new(list(reversed(rings[0])))
        if len(rings[-1]) > 1:
            bm.faces.new(rings[-1])
    return bm_to_object(bm, name, col)


def loft(name, sections, cap=True, col=None):
    """Skin a list of closed 3D loops (equal vertex count) with quads; optional end caps."""
    bm = bmesh.new()
    rings = [[bm.verts.new(Vector(p)) for p in sec] for sec in sections]
    n = len(sections[0])
    for a, b in zip(rings[:-1], rings[1:]):
        for s in range(n):
            t = (s + 1) % n
            bm.faces.new((a[s], a[t], b[t], b[s]))
    if cap:
        bm.faces.new(list(reversed(rings[0])))
        bm.faces.new(rings[-1])
    return bm_to_object(bm, name, col)


def path_frames(path, side=(0.0, 1.0, 0.0)):
    """Frames along a polyline lying in the plane perpendicular to `side`.
    Returns list of (point, tangent, normal) with normal = tangent x side."""
    side = Vector(side).normalized()
    pts = [Vector(p) for p in path]
    out = []
    for i, p in enumerate(pts):
        if i == 0:
            t = pts[1] - pts[0]
        elif i == len(pts) - 1:
            t = pts[-1] - pts[-2]
        else:
            t = pts[i + 1] - pts[i - 1]
        t.normalize()
        n = t.cross(side).normalized()
        out.append((p, t, n))
    return out


def sweep(name, section, path, side=(0.0, 1.0, 0.0), scales=None, cap=True, col=None):
    """Sweep a 2D section (u along the frame normal, v along `side`) along a planar path.
    `scales` optional list of (su, sv) per path point."""
    side_v = Vector(side).normalized()
    secs = []
    for i, (p, t, n) in enumerate(path_frames(path, side)):
        su, sv = scales[i] if scales else (1.0, 1.0)
        secs.append([p + n * (u * su) + side_v * (v * sv) for u, v in section])
    return loft(name, secs, cap=cap, col=col)


def circle_pts(r, n=24, cx=0.0, cy=0.0, phase=0.0):
    return [(cx + r * math.cos(phase + 2 * math.pi * i / n),
             cy + r * math.sin(phase + 2 * math.pi * i / n)) for i in range(n)]


def rounded_rect(w, h, r, seg=4, cx=0.0, cy=0.0):
    """CCW outline of a w x h rectangle with corner radius r (seg segments per corner)."""
    r = min(r, w / 2 - 1e-6, h / 2 - 1e-6)
    hw, hh = w / 2 - r, h / 2 - r
    pts = []
    corners = [(hw, -hh, -90), (hw, hh, 0), (-hw, hh, 90), (-hw, -hh, 180)]
    for ccx, ccy, a0 in corners:
        for k in range(seg + 1):
            a = math.radians(a0 + 90.0 * k / seg)
            pts.append((cx + ccx + r * math.cos(a), cy + ccy + r * math.sin(a)))
    return pts


def superellipse(a, b, p=4.0, n=32, cx=0.0, cy=0.0, phase=0.0):
    """|x/a|^p + |y/b|^p = 1 outline (p=2 ellipse, larger p boxier)."""
    pts = []
    for i in range(n):
        t = phase + 2 * math.pi * i / n
        c, s = math.cos(t), math.sin(t)
        x = a * math.copysign(abs(c) ** (2.0 / p), c)
        y = b * math.copysign(abs(s) ** (2.0 / p), s)
        pts.append((cx + x, cy + y))
    return pts


def fillet_polygon(pts, radius, seg=3):
    """Round every corner of a closed 2D polygon.  radius may be a float or a per-vertex
    list (0 = keep sharp)."""
    n = len(pts)
    rads = radius if isinstance(radius, (list, tuple)) else [radius] * n
    out = []
    for i in range(n):
        p0 = Vector(pts[i - 1]); p1 = Vector(pts[i]); p2 = Vector(pts[(i + 1) % n])
        r = rads[i]
        d1 = (p0 - p1); d2 = (p2 - p1)
        l1, l2 = d1.length, d2.length
        if r <= 0 or l1 < 1e-9 or l2 < 1e-9:
            out.append(tuple(p1)); continue
        d1.normalize(); d2.normalize()
        ang = math.acos(max(-1.0, min(1.0, d1.dot(d2))))
        if ang < 1e-3 or abs(ang - math.pi) < 1e-3:
            out.append(tuple(p1)); continue
        t = r / math.tan(ang / 2)
        t = min(t, 0.45 * l1, 0.45 * l2)
        r_eff = t * math.tan(ang / 2)
        a = p1 + d1 * t
        b = p1 + d2 * t
        bis = (d1 + d2).normalized()
        c = p1 + bis * (r_eff / math.sin(ang / 2))
        va = (a - c); vb = (b - c)
        a0 = math.atan2(va.y, va.x); a1 = math.atan2(vb.y, vb.x)
        da = a1 - a0
        while da > math.pi: da -= 2 * math.pi
        while da < -math.pi: da += 2 * math.pi
        for k in range(seg + 1):
            aa = a0 + da * k / seg
            out.append((c.x + r_eff * math.cos(aa), c.y + r_eff * math.sin(aa)))
    return out


def box(name, x0, x1, y0, y1, z0, z1, col=None):
    return poly_extrude(name, [(x0, z0), (x1, z0), (x1, z1), (x0, z1)], 'Y', y0, y1, col)


def cyl(name, r, a0, a1, axis='X', center=(0.0, 0.0), segs=24, phase=0.0, col=None):
    return lathe(name, [(a0, r), (a1, r)], segs, axis, center, phase, col=col)


# =============================================================================
# 3. Mesh operations
# =============================================================================

CLEAN_DIST = 1e-4   # degenerate-geometry tolerance in authoring units (set per asset)


def apply_modifiers(obj):
    """Bake the evaluated modifier stack into the object's mesh (keeps custom normals)."""
    dg = bpy.context.evaluated_depsgraph_get()
    old = obj.data
    new = bpy.data.meshes.new_from_object(obj.evaluated_get(dg), preserve_all_data_layers=True,
                                          depsgraph=dg)
    new.name = old.name
    obj.modifiers.clear()
    obj.data = new
    if old.users == 0:
        bpy.data.meshes.remove(old)
    return obj


def merged_copy(objs, name="__merged", col=None):
    """Single object containing copies of all given objects' geometry (world space)."""
    bm = bmesh.new()
    mats = []
    for o in objs:
        me = o.data
        tmp = bmesh.new()
        tmp.from_mesh(me)
        tmp.transform(o.matrix_world)
        # remap material indices
        remap = {}
        for i, m in enumerate(me.materials):
            if m not in mats:
                mats.append(m)
            remap[i] = mats.index(m)
        for f in tmp.faces:
            f.material_index = remap.get(f.material_index, 0)
        me2 = bpy.data.meshes.new("__tmp")
        tmp.to_mesh(me2); tmp.free()
        bm.from_mesh(me2)
        bpy.data.meshes.remove(me2)
    ob = bm_to_object(bm, name, col, recalc=False)
    for m in mats:
        ob.data.materials.append(m)
    return ob


def clean_mesh(obj, dist=1e-4):
    """Collapse zero-length edges / zero-area slivers, merge doubles, drop loose geometry.
    `dist` is in the object's current units (1e-4 = 1 micron when authoring in cm)."""
    bm = bmesh.new(); bm.from_mesh(obj.data)
    bmesh.ops.dissolve_degenerate(bm, dist=dist, edges=bm.edges[:])
    bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=dist)
    loose_e = [e for e in bm.edges if not e.link_faces]
    if loose_e:
        bmesh.ops.delete(bm, geom=loose_e, context='EDGES')
    loose_v = [v for v in bm.verts if not v.link_edges]
    if loose_v:
        bmesh.ops.delete(bm, geom=loose_v, context='VERTS')
    bm.to_mesh(obj.data); bm.free()
    obj.data.update()
    return obj


def delete(objs):
    for o in (objs if isinstance(objs, (list, tuple)) else [objs]):
        me = o.data if o.type == 'MESH' else None
        bpy.data.objects.remove(o, do_unlink=True)
        if me is not None and me.users == 0:
            bpy.data.meshes.remove(me)


def boolean(target, cutters, op='DIFFERENCE', solver='EXACT', material_mode='INDEX',
            use_self=False, keep_cutters=False):
    """Apply a boolean between target and one or more cutter objects (merged first)."""
    cutters = cutters if isinstance(cutters, (list, tuple)) else [cutters]
    if not cutters:
        return target
    cut = merged_copy(cutters, "__cutter") if len(cutters) > 1 else cutters[0]
    m = target.modifiers.new("bool", 'BOOLEAN')
    m.operation = op
    m.solver = solver
    m.object = cut
    if solver == 'EXACT':
        # merged cutters may overlap each other -> self-intersection handling required
        m.use_self = use_self or len(cutters) > 1
        m.material_mode = material_mode
    apply_modifiers(target)
    clean_mesh(target, CLEAN_DIST)
    if len(cutters) > 1:
        delete(cut)
    if not keep_cutters:
        delete(list(cutters))
    return target


def union(target, others, **kw):
    return boolean(target, others, op='UNION', **kw)


def mesh_health(obj, locations=False):
    """(non-manifold edges, zero-area faces, self-intersecting face pairs) of a mesh.  Self
    intersections ignore pairs of faces that share a vertex.  locations=True also returns the
    centres of the intersecting faces."""
    from mathutils.bvhtree import BVHTree
    bm = bmesh.new(); bm.from_mesh(obj.data)
    bm.faces.ensure_lookup_table()
    nonman = sum(1 for e in bm.edges if len(e.link_faces) != 2)
    zero = sum(1 for f in bm.faces if f.calc_area() < (CLEAN_DIST * 0.1) ** 2)
    tree = BVHTree.FromBMesh(bm)
    inter = 0
    locs = []
    for i, j in tree.overlap(tree):
        if i >= j:
            continue
        vi = {v.index for v in bm.faces[i].verts}
        if any(v.index in vi for v in bm.faces[j].verts):
            continue
        inter += 1
        if locations:
            locs.append(bm.faces[i].calc_center_median().copy())
            locs.append(bm.faces[j].calc_center_median().copy())
    bm.free()
    return ((nonman, zero, inter), locs) if locations else (nonman, zero, inter)


def _bevel_once(obj, width, segments, angle, profile, limit, clamp, harden, miter_outer):
    m = obj.modifiers.new("bevel", 'BEVEL')
    m.width = width
    m.segments = segments
    m.limit_method = limit
    m.angle_limit = math.radians(angle)
    m.profile = profile
    m.use_clamp_overlap = clamp
    m.harden_normals = harden
    m.miter_outer = miter_outer
    apply_modifiers(obj)
    clean_mesh(obj, CLEAN_DIST)
    return obj


def _local_bevel_limits(me, width, angle):
    """Per-edge bevel width fraction (edge index -> 0..1) limited only by the geometry around
    each edge: the offset may use at most half of the distance to the opposite side of each
    adjacent face, and half of each adjacent non-bevelled face edge it slides along.  Also
    returns the edge segments (for mapping problems back to edges)."""
    bm = bmesh.new(); bm.from_mesh(me)
    lim = math.radians(angle)
    cand = {}
    for e in bm.edges:
        if len(e.link_faces) != 2:
            continue
        f1, f2 = e.link_faces
        if f1.normal.length < 0.5 or f2.normal.length < 0.5:
            continue
        if f1.normal.angle(f2.normal, 0.0) > lim:
            cand[e.index] = e
    wts = {}; segs = {}
    for idx, e in cand.items():
        a, b = e.verts[0].co, e.verts[1].co
        segs[idx] = (a.copy(), b.copy())
        d = b - a
        ln = d.length
        if ln < 1e-12:
            continue
        d = d / ln
        w = width
        for f in e.link_faces:
            dmin = 1e9
            for v in f.verts:
                if v is e.verts[0] or v is e.verts[1]:
                    continue
                r = v.co - a
                dmin = min(dmin, (r - d * r.dot(d)).length)
            if dmin < 1e8:
                w = min(w, 0.5 * dmin)
            for v in e.verts:
                for e2 in v.link_edges:
                    if e2 is e or e2.index in cand or f not in e2.link_faces:
                        continue
                    o = e2.other_vert(v).co - v.co
                    l2 = o.length
                    if l2 < 1e-12:
                        continue
                    sin_t = (o / l2).cross(d).length
                    # nearly in-line neighbours: the offset vertex moves perpendicular to the
                    # edge rather than far along the neighbour
                    w = min(w, 0.5 * l2 * (sin_t if sin_t > 0.26 else 1.0))
        wts[idx] = min(1.0, w / width)
    bm.free()
    return wts, segs


def _set_bevel_weights(me, wts, min_frac=0.04):
    bm = bmesh.new(); bm.from_mesh(me)
    layer = bm.edges.layers.float.get("bevel_weight_edge") or bm.edges.layers.float.new("bevel_weight_edge")
    for e in bm.edges:
        f = wts.get(e.index, 0.0)
        e[layer] = f if f >= min_frac else 0.0
    bm.to_mesh(me); bm.free()


def _clear_bevel_weights(obj):
    a = obj.data.attributes.get("bevel_weight_edge")
    if a:
        obj.data.attributes.remove(a)


BEVEL_RETRIES = 5


def _narrow_near(wts, segs, locs, width, attempt):
    """After a failed local bevel: narrow the edges within 2 bevel widths of any problem spot
    (x0.4 per retry; the last retry removes their bevel)."""
    r = 2.0 * width
    f = 0.4 if attempt < BEVEL_RETRIES - 1 else 0.0
    for idx, (a, b) in segs.items():
        if idx in wts and wts[idx] > 0 and any(_seg_dist(p, a, b) < r for p in locs):
            wts[idx] *= f


def _seg_dist(p, a, b):
    ab = b - a
    t = 0.0 if ab.length_squared < 1e-20 else max(0.0, min(1.0, (p - a).dot(ab) / ab.length_squared))
    return (p - (a + ab * t)).length


def razor_length(obj, angle=70.0, ignore_below=0.0):
    """Total length of manifold edges whose faces meet at more than `angle` degrees (object
    units): unbevelled hard edges.  ignore_below > 0 first collapses geometry smaller than that
    (a bevel a few microns wide is still a razor edge to the eye)."""
    bm = bmesh.new(); bm.from_mesh(obj.data)
    if ignore_below > 0:
        bmesh.ops.dissolve_degenerate(bm, dist=ignore_below, edges=bm.edges[:])
    lim = math.radians(angle)
    tot = 0.0
    for e in bm.edges:
        if len(e.link_faces) != 2:
            continue
        f1, f2 = e.link_faces
        if f1.calc_area() < 1e-12 or f2.calc_area() < 1e-12:
            continue
        if f1.normal.angle(f2.normal, 0.0) > lim:
            tot += e.calc_length()
    bm.free()
    return tot


def bevel(obj, width, segments=1, angle=30.0, profile=0.5, limit='ANGLE', clamp='auto',
          harden=False, miter_outer='MITER_SHARP'):
    """Bevel modifier, applied.

    clamp='auto' (default): Blender's "clamp overlap" is global -- one tiny edge anywhere (a
    boolean sliver, a fine fillet facet) limits the width of EVERY bevel on the object, and the
    near-zero bevels are then dissolved by clean_mesh, leaving razor edges.  'auto' also builds
    a bevel where every edge gets its own width, limited only by the geometry around it
    (_local_bevel_limits, applied through the bevel-weight limit method, unclamped; edges near
    any self-intersection are narrowed and it retries), and keeps whichever of the two valid
    results leaves less unbevelled (> 70 deg) edge length.  clamp=True / False forces one mode
    with the angle limit."""
    if clamp != 'auto' or limit != 'ANGLE':
        return _bevel_once(obj, width, segments, angle, profile, limit, bool(clamp), harden, miter_outer)
    before = mesh_health(obj)
    src = obj.data.copy()
    # candidate A: Blender's clamped bevel
    _bevel_once(obj, width, segments, angle, profile, 'ANGLE', True, harden, miter_outer)
    res_clamped = obj.data
    ign = min(0.2 * width, 10.0 * CLEAN_DIST)       # bevels narrower than this still read as razor edges
    razor_c = razor_length(obj, ignore_below=ign)
    # candidate B: local per-edge widths
    wts, segs = _local_bevel_limits(src, width, angle)
    res_local = None
    for attempt in range(BEVEL_RETRIES + 1):
        work = src.copy()
        obj.data = work
        _set_bevel_weights(work, wts)
        _bevel_once(obj, width, segments, angle, profile, 'WEIGHT', False, harden, miter_outer)
        _clear_bevel_weights(obj)
        after, locs = mesh_health(obj, locations=True)
        if all(x <= y for x, y in zip(after, before)):
            res_local = obj.data
            break
        bad = obj.data
        obj.data = src                     # never remove an object's current data (kills the object)
        bpy.data.meshes.remove(bad)
        _narrow_near(wts, segs, locs, width, attempt)
    razor_l = None
    if res_local is not None:
        obj.data = res_local
        razor_l = razor_length(obj, ignore_below=ign)
    if res_local is not None and razor_l < razor_c - 1e-9:
        keep, drop, mode = res_local, res_clamped, "local"
    else:
        keep, drop, mode = res_clamped, res_local, "clamped"
    obj.data = keep
    keep.name = src.name
    for m in (drop, src):
        if m is not None:
            bpy.data.meshes.remove(m)
    obj["iv_bevel_mode"] = mode
    if os.environ.get("IV_BEVEL_DEBUG"):
        log(f"  bevel {obj.name}: clamped razor {razor_c:.3f}, local razor "
            f"{'failed' if razor_l is None else round(razor_l, 3)} -> {mode}")
    return obj


def boolean_bevelled(target, cutters, width, segments=1, angle=30.0, profile=0.5, op='DIFFERENCE'):
    """Boolean difference, then bevel ONLY the edges the cut created (edges touching a face that
    came from a cutter), with per-edge local widths.  For small details cut into an already
    bevelled part (knurl flutes, grooves): they get their own narrow, low-segment bevel instead
    of razor edges, and the part's existing bevels are left alone."""
    me = target.data
    a = me.attributes.get("iv_pre") or me.attributes.new("iv_pre", 'INT', 'FACE')
    a.data.foreach_set("value", [1] * len(me.polygons))
    boolean(target, cutters, op=op)
    me = target.data
    bm = bmesh.new(); bm.from_mesh(me)
    pre = bm.faces.layers.int.get("iv_pre")
    new_edges = set()
    for e in bm.edges:
        if any(f[pre] == 0 for f in e.link_faces):
            new_edges.add(e.index)
    bm.free()
    before = mesh_health(target)
    src = me.copy()
    # uniform (narrow) width on every new hard edge; only spots that self-intersect get
    # narrowed.  (Neighbourhood limits are too pessimistic here: the cut's rim crosses the
    # part's existing bevel strips and is split into many short segments.)
    wts, segs = _local_bevel_limits(src, width, angle)
    wts = {k: 1.0 for k in wts if k in new_edges}
    ok = False
    for attempt in range(BEVEL_RETRIES + 1):
        work = src.copy()
        target.data = work
        _set_bevel_weights(work, wts)
        _bevel_once(target, width, segments, angle, profile, 'WEIGHT', False, False, 'MITER_SHARP')
        _clear_bevel_weights(target)
        after, locs = mesh_health(target, locations=True)
        if all(x <= y for x, y in zip(after, before)):
            ok = True
            break
        bad = target.data
        target.data = src
        bpy.data.meshes.remove(bad)
        _narrow_near(wts, segs, locs, width, attempt)
    if ok:
        target.data.name = src.name
        bpy.data.meshes.remove(src)
    else:
        log(f"  boolean_bevelled {target.name}: new-edge bevel failed; cut left unbevelled")
    at = target.data.attributes.get("iv_pre")
    if at:
        target.data.attributes.remove(at)
    return target


def weld(obj, dist):
    bm = bmesh.new(); bm.from_mesh(obj.data)
    bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=dist)
    bm.to_mesh(obj.data); bm.free()
    return obj


def transform_mesh(obj, matrix):
    obj.data.transform(matrix)
    obj.data.update()
    return obj


def mark_sharp_between_flats(obj, min_angle, max_angle, min_area):
    """Mark edges sharp where two LARGE faces (area >= min_area, object units^2) meet at an angle
    between min_angle and max_angle degrees: a shallow design crease (e.g. a 26 deg chamfer)
    that is below the bevel limit.  Left smooth, face-area weighting bends the normals of the big
    flat faces towards each other (visible as a bent reflection on glossy finishes).  Thin bevel
    or fillet strips never qualify, so rounded edges stay smooth."""
    me = obj.data
    bm = bmesh.new(); bm.from_mesh(me)
    lo, hi = math.radians(min_angle), math.radians(max_angle)
    sharp = []
    for e in bm.edges:
        if len(e.link_faces) != 2:
            continue
        f1, f2 = e.link_faces
        if f1.calc_area() < min_area or f2.calc_area() < min_area:
            continue
        a = f1.normal.angle(f2.normal, 0.0)
        if lo <= a <= hi:
            sharp.append(e.index)
    bm.free()
    attr = me.attributes.get("sharp_edge") or me.attributes.new("sharp_edge", 'BOOLEAN', 'EDGE')
    vals = [False] * len(me.edges)
    attr.data.foreach_get("value", vals)
    for i in sharp:
        vals[i] = True
    attr.data.foreach_set("value", vals)
    return len(sharp)


def finish_shading(obj, sharp_angle=50.0, weighted=True, weight=50, triangulate=True, clean_dist=None,
                   sharp_flats=None):
    """Smooth shading + sharp edges above `sharp_angle` + face-area weighted normals (on the
    n-gon mesh, so large flat faces shade flat) + triangulation that keeps custom normals.
    Triangulating before UV/bake guarantees bake and export share the same tangent basis.
    sharp_flats=(min_angle, max_angle, min_area) additionally marks shallow creases between
    large flat faces sharp (see mark_sharp_between_flats)."""
    if clean_dist:
        clean_mesh(obj, clean_dist)
    me = obj.data
    me.shade_smooth()
    if sharp_angle is not None:
        me.set_sharp_from_angle(angle=math.radians(sharp_angle))
    if sharp_flats:
        mark_sharp_between_flats(obj, *sharp_flats)
    if weighted:
        w = obj.modifiers.new("wn", 'WEIGHTED_NORMAL')
        w.mode = 'FACE_AREA'
        w.weight = weight
        w.keep_sharp = True
        w.thresh = 0.01
        apply_modifiers(obj)
    if triangulate:
        t = obj.modifiers.new("tri", 'TRIANGULATE')
        t.quad_method = 'BEAUTY'
        t.ngon_method = 'BEAUTY'
        t.keep_custom_normals = True
        t.min_vertices = 4
        apply_modifiers(obj)
    return obj


def join(objs, name):
    """Join objects into objs[0] (renamed).  Materials are merged by the operator."""
    if len(objs) == 1:
        objs[0].name = name
        return objs[0]
    with bpy.context.temp_override(active_object=objs[0], object=objs[0],
                                   selected_objects=objs, selected_editable_objects=objs):
        bpy.ops.object.join()
    objs[0].name = name
    objs[0].data.name = name
    return objs[0]


def set_origin(obj, point):
    """Move the object origin to world `point` without moving geometry."""
    p = Vector(point)
    mw = obj.matrix_world.copy()
    local = mw.inverted() @ p
    obj.data.transform(Matrix.Translation(-local))
    obj.matrix_world = mw @ Matrix.Translation(local)
    return obj


def assign_material(obj, mat, faces=None):
    me = obj.data
    if mat.name not in [m.name for m in me.materials if m]:
        me.materials.append(mat)
    idx = [m.name if m else None for m in me.materials].index(mat.name)
    for p in me.polygons:
        if faces is None or p.index in faces:
            p.material_index = idx
    return idx


def tri_count(obj):
    me = obj.data
    me.calc_loop_triangles()
    return len(me.loop_triangles)


def world_bbox(objs):
    mn = Vector((1e9, 1e9, 1e9)); mx = Vector((-1e9, -1e9, -1e9))
    for o in objs:
        if o.type != 'MESH':
            continue
        mw = o.matrix_world
        for v in o.data.vertices:
            w = mw @ v.co
            mn = Vector((min(mn.x, w.x), min(mn.y, w.y), min(mn.z, w.z)))
            mx = Vector((max(mx.x, w.x), max(mx.y, w.y), max(mx.z, w.z)))
    return mn, mx


def world_bbox_fast(objs):
    mn = np.array([1e9] * 3); mx = np.array([-1e9] * 3)
    for o in objs:
        if o.type != 'MESH' or len(o.data.vertices) == 0:
            continue
        co = np.empty(len(o.data.vertices) * 3, np.float64)
        o.data.vertices.foreach_get("co", co)
        co = co.reshape(-1, 3)
        M = np.array(o.matrix_world)
        w = co @ M[:3, :3].T + M[:3, 3]
        mn = np.minimum(mn, w.min(0)); mx = np.maximum(mx, w.max(0))
    return Vector(mn), Vector(mx)


# =============================================================================
# 4. Procedural PBR materials
# =============================================================================

def _is_socket(x):
    return isinstance(x, bpy.types.NodeSocket)


class NB:
    """Tiny node-tree builder.  Every helper accepts sockets or plain numbers."""

    def __init__(self, mat_or_tree):
        self.nt = mat_or_tree.node_tree if hasattr(mat_or_tree, "node_tree") else mat_or_tree
        self.nodes = self.nt.nodes
        self.links = self.nt.links
        self._x = -1600

    def node(self, typ, **props):
        n = self.nodes.new(typ)
        n.location = (self._x, 0)
        self._x += 40
        for k, v in props.items():
            setattr(n, k, v)
        return n

    def set(self, inp, v):
        if _is_socket(v):
            self.links.new(v, inp)
        elif v is not None:
            if hasattr(inp, "default_value"):
                dv = inp.default_value
                if hasattr(dv, "__len__") and not isinstance(v, (list, tuple)):
                    v = [v] * len(dv)
                    if len(dv) == 4:
                        v[3] = 1.0
                elif hasattr(dv, "__len__") and len(v) == 3 and len(dv) == 4:
                    v = list(v) + [1.0]
                inp.default_value = v

    # -- inputs
    def coords(self, kind='Object'):
        return self.node('ShaderNodeTexCoord').outputs[kind]

    def value(self, v):
        n = self.node('ShaderNodeValue'); n.outputs[0].default_value = v
        return n.outputs[0]

    def rgb(self, c):
        n = self.node('ShaderNodeRGB'); n.outputs[0].default_value = (c[0], c[1], c[2], 1.0)
        return n.outputs[0]

    def mapping(self, vec, loc=(0, 0, 0), rot=(0, 0, 0), scale=(1, 1, 1)):
        n = self.node('ShaderNodeMapping')
        self.set(n.inputs['Vector'], vec)
        n.inputs['Location'].default_value = loc
        n.inputs['Rotation'].default_value = rot
        n.inputs['Scale'].default_value = scale
        return n.outputs[0]

    # -- math
    def math(self, op, a, b=0.0, c=0.0, clamp=False):
        n = self.node('ShaderNodeMath', operation=op, use_clamp=clamp)
        self.set(n.inputs[0], a); self.set(n.inputs[1], b); self.set(n.inputs[2], c)
        return n.outputs[0]

    def add(self, a, b, clamp=False): return self.math('ADD', a, b, clamp=clamp)
    def mul(self, a, b, clamp=False): return self.math('MULTIPLY', a, b, clamp=clamp)
    def sub(self, a, b, clamp=False): return self.math('SUBTRACT', a, b, clamp=clamp)
    def maxf(self, a, b): return self.math('MAXIMUM', a, b)
    def minf(self, a, b): return self.math('MINIMUM', a, b)
    def inv(self, a): return self.math('SUBTRACT', 1.0, a, clamp=True)

    def remap(self, x, lo, hi, to_lo=0.0, to_hi=1.0, smooth=False, clamp=True):
        n = self.node('ShaderNodeMapRange', data_type='FLOAT',
                      interpolation_type='SMOOTHSTEP' if smooth else 'LINEAR', clamp=clamp)
        self.set(n.inputs[0], x); self.set(n.inputs[1], lo); self.set(n.inputs[2], hi)
        self.set(n.inputs[3], to_lo); self.set(n.inputs[4], to_hi)
        return n.outputs[0]

    def lerp(self, fac, a, b):
        return self.remap(fac, 0.0, 1.0, a, b)

    def mix_col(self, fac, a, b, blend='MIX'):
        n = self.node('ShaderNodeMix', data_type='RGBA', blend_type=blend, clamp_result=True)
        self.set(n.inputs[0], fac); self.set(n.inputs[6], a); self.set(n.inputs[7], b)
        return n.outputs[2]

    def ramp(self, fac, stops, interp='LINEAR'):
        n = self.node('ShaderNodeValToRGB')
        cr = n.color_ramp
        cr.interpolation = interp
        while len(cr.elements) > 1:
            cr.elements.remove(cr.elements[-1])
        for i, (pos, col) in enumerate(stops):
            e = cr.elements[0] if i == 0 else cr.elements.new(pos)
            e.position = pos
            e.color = (col[0], col[1], col[2], 1.0) if len(col) == 3 else col
        self.set(n.inputs[0], fac)
        return n.outputs[0]

    def sep(self, col):
        n = self.node('ShaderNodeSeparateColor')
        self.set(n.inputs[0], col)
        return n.outputs[0], n.outputs[1], n.outputs[2]

    def comb(self, r, g, b):
        n = self.node('ShaderNodeCombineColor')
        self.set(n.inputs[0], r); self.set(n.inputs[1], g); self.set(n.inputs[2], b)
        return n.outputs[0]

    # -- textures (object-space coordinates in metres after final scaling)
    def noise(self, vec, scale, detail=2.0, rough=0.5, w=0.0, distortion=0.0, lac=2.0):
        n = self.node('ShaderNodeTexNoise', noise_dimensions='4D')
        self.set(n.inputs['Vector'], vec)
        self.set(n.inputs['W'], w)
        self.set(n.inputs['Scale'], scale)
        self.set(n.inputs['Detail'], detail)
        self.set(n.inputs['Roughness'], rough)
        self.set(n.inputs['Lacunarity'], lac)
        self.set(n.inputs['Distortion'], distortion)
        return n.outputs['Fac']

    def voronoi(self, vec, scale, w=0.0, randomness=1.0, feature='F1', out='Distance'):
        n = self.node('ShaderNodeTexVoronoi', voronoi_dimensions='4D', feature=feature)
        self.set(n.inputs['Vector'], vec)
        self.set(n.inputs['W'], w)
        self.set(n.inputs['Scale'], scale)
        self.set(n.inputs['Randomness'], randomness)
        return n.outputs[out]

    def wave(self, vec, scale, direction='Z', distortion=0.0, detail=0.0, profile='SIN',
             phase=0.0):
        n = self.node('ShaderNodeTexWave', wave_type='BANDS', bands_direction=direction,
                      wave_profile=profile)
        self.set(n.inputs['Vector'], vec)
        self.set(n.inputs['Scale'], scale)
        self.set(n.inputs['Distortion'], distortion)
        self.set(n.inputs['Detail'], detail)
        self.set(n.inputs['Phase Offset'], phase)
        return n.outputs['Fac']

    def bump(self, height, strength, distance, normal=None):
        n = self.node('ShaderNodeBump')
        self.set(n.inputs['Height'], height)
        self.set(n.inputs['Strength'], strength)
        self.set(n.inputs['Distance'], distance)
        if normal is not None:
            self.set(n.inputs['Normal'], normal)
        return n.outputs['Normal']

    def geometry(self, out='Position'):
        return self.node('ShaderNodeNewGeometry').outputs[out]

    def xyz(self, vec):
        n = self.node('ShaderNodeSeparateXYZ')
        self.set(n.inputs[0], vec)
        return n.outputs[0], n.outputs[1], n.outputs[2]


def _new_material(name):
    m = bpy.data.materials.get(name)
    if m is not None:
        bpy.data.materials.remove(m)
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new('ShaderNodeOutputMaterial'); out.name = "OUT"; out.location = (600, 0)
    bsdf = nt.nodes.new('ShaderNodeBsdfPrincipled'); bsdf.name = "BSDF"; bsdf.location = (300, 0)
    nt.links.new(bsdf.outputs[0], out.inputs['Surface'])
    return m, NB(m), bsdf


# ---- mask group: per texture set, "Edge", "Cavity", "AO" in 0..1 ----------------

MASK_GROUP_PREFIX = "IV_Masks_"


def mask_group(set_name, edge_dist=0.0012, cavity_dist=0.006, ao_dist=0.03, samples=16):
    """Create (or rebuild procedurally) the mask node group for a texture set.
    Edge   = convexity (1 - inside-AO over a very short distance, only this object)
    Cavity = short-range AO (1 open .. 0 crevice)
    AO     = medium-range ambient occlusion used for the ORM red channel."""
    name = MASK_GROUP_PREFIX + set_name
    g = bpy.data.node_groups.get(name)
    if g is None:
        g = bpy.data.node_groups.new(name, 'ShaderNodeTree')
        for s in ("Edge", "Cavity", "AO"):
            g.interface.new_socket(s, in_out='OUTPUT', socket_type='NodeSocketFloat')
    g["edge_dist"] = edge_dist; g["cavity_dist"] = cavity_dist
    g["ao_dist"] = ao_dist; g["samples"] = samples
    _mask_group_procedural(g)
    return g


def _clear_tree(tree):
    for n in list(tree.nodes):
        tree.nodes.remove(n)


def _mask_group_procedural(g):
    _clear_tree(g)
    nb = NB(g)
    out = nb.node('NodeGroupOutput')
    samples = int(g.get("samples", 16))
    ao_in = nb.node('ShaderNodeAmbientOcclusion', inside=True, only_local=True, samples=samples)
    ao_in.inputs['Distance'].default_value = g["edge_dist"]
    edge = nb.math('SUBTRACT', 1.0, ao_in.outputs['AO'], clamp=True)
    ao_c = nb.node('ShaderNodeAmbientOcclusion', inside=False, only_local=False, samples=samples)
    ao_c.inputs['Distance'].default_value = g["cavity_dist"]
    ao_f = nb.node('ShaderNodeAmbientOcclusion', inside=False, only_local=False, samples=samples)
    ao_f.inputs['Distance'].default_value = g["ao_dist"]
    nb.links.new(edge, out.inputs['Edge'])
    nb.links.new(ao_c.outputs['AO'], out.inputs['Cavity'])
    nb.links.new(ao_f.outputs['AO'], out.inputs['AO'])
    g["mode"] = "procedural"


def mask_group_use_image(g, image, uv_map="UVMap"):
    """Switch a mask group to read a previously baked mask image (R edge, G cavity, B AO)."""
    _clear_tree(g)
    nb = NB(g)
    out = nb.node('NodeGroupOutput')
    uv = nb.node('ShaderNodeUVMap'); uv.uv_map = uv_map
    tex = nb.node('ShaderNodeTexImage', interpolation='Linear', extension='EXTEND')
    tex.image = image
    nb.links.new(uv.outputs[0], tex.inputs[0])
    r, gg, b = nb.sep(tex.outputs['Color'])
    nb.links.new(r, out.inputs['Edge'])
    nb.links.new(gg, out.inputs['Cavity'])
    nb.links.new(b, out.inputs['AO'])
    g["mode"] = "image"


def _masks(nb, group):
    n = nb.node('ShaderNodeGroup')
    n.node_tree = group
    n.name = "IV_MASKS"
    return n.outputs['Edge'], n.outputs['Cavity'], n.outputs['AO']


def _seed_w(seed):
    return (seed * 7.123) % 97.0


def _contact(nb, attr, default=0.35):
    """Per-vertex 'handling contact' attribute (0..1, written by the generator: where hands, gear
    and slings touch the part).  Falls back to `default` when the attribute is absent."""
    if not attr:
        return default
    n = nb.node('ShaderNodeAttribute', attribute_type='GEOMETRY', attribute_name=attr)
    fac = n.outputs['Fac']
    # attribute missing -> Fac 0 -> use the default (generators write values >= 0.02)
    return nb.lerp(nb.math('GREATER_THAN', fac, 0.0005), default, fac)


def _micro_normal(nb, co, w, h_extra=None, strength=1.0, milling=0.0, scuff=None):
    """Normal detail that survives an 8-bit normal map (2-6 deg tilt) at ~25-45 px/cm:
    orange-peel (~2 mm features), optional milling lines along X (~1.3 mm pitch) and optional
    handling scuffs (short streaks) where scuff (0..1 socket) is high."""
    peel = nb.noise(co, 420.0, 3.0, 0.55, w + 21.0)
    h = nb.mul(peel, 0.55)
    if milling:
        mill = nb.wave(nb.mapping(co, scale=(1.0, 1.0, 1.0)), 780.0, 'X', distortion=1.5, detail=1.0)
        h = nb.add(h, nb.mul(mill, 0.18 * milling))
    if scuff is not None:
        sco = nb.mapping(co, scale=(1.0, 9.0, 9.0))
        st = nb.remap(nb.noise(sco, 160.0, 2.0, 0.5, w + 31.0), 0.62, 0.72, smooth=True)
        h = nb.sub(h, nb.mul(nb.mul(st, scuff), 0.8))
    if h_extra is not None:
        h = nb.add(h, h_extra)
    return nb.bump(h, strength, 0.00022)


def mat_anodized(name, masks, base=(0.042, 0.042, 0.046), rough=0.34, wear=1.0,
                 scratches=0.6, seed=0, contact_attr="iv_contact", contact_default=0.35,
                 bare=(0.62, 0.63, 0.65)):
    """Black hard-anodised aluminium, metallic workflow: the dyed oxide over aluminium reads as a
    dark metal (metallic 1, base ~0.04 linear) with a satin, slightly broken-up roughness
    (~0.30-0.38), crisper and slightly lighter on bevel highlights.  Wear-through to bright bare
    aluminium (base ~0.6, roughness ~0.27) sits on convex edges, driven by a wide convexity mask
    and the per-vertex contact attribute (hands, sling, magazine changes).  Handling polish
    lowers roughness in contact areas.  Micro normal: orange-peel, milling marks, scuffs."""
    m, nb, bsdf = _new_material(name)
    co = nb.coords('Object')
    w = _seed_w(seed)
    edge, cav, ao = _masks(nb, masks)
    contact = _contact(nb, contact_attr, contact_default)
    n_big = nb.noise(co, 9.0, 3.0, 0.5, w)
    n_mid = nb.noise(co, 60.0, 4.0, 0.55, w + 3.1)
    n_fine = nb.noise(co, 700.0, 2.0, 0.5, w + 5.7)
    patch = nb.remap(nb.noise(co, 22.0, 3.0, 0.6, w + 8.0), 0.38, 0.62)          # where wear happens
    gain = nb.lerp(contact, 0.45, 1.55)
    e = nb.mul(edge, nb.lerp(patch, 0.55, 1.2))
    e = nb.mul(e, nb.remap(n_mid, 0.3, 0.7, 0.8, 1.15))
    e = nb.mul(e, gain)
    worn = nb.remap(e, 0.50 / max(wear, 1e-3), 0.66 / max(wear, 1e-3), smooth=True)
    hl = nb.remap(edge, 0.25, 0.55, smooth=True)                                   # bevel highlight
    # handling polish: streaks along X, low frequency, stronger where handled
    sco = nb.mapping(co, scale=(6.0, 160.0, 160.0))
    polish = nb.mul(nb.remap(nb.noise(sco, 1.0, 3.0, 0.6, w + 11.0), 0.45, 0.75, smooth=True),
                    nb.mul(scratches, nb.lerp(contact, 0.4, 1.0)))
    dirt = nb.mul(nb.remap(cav, 0.55, 0.15, smooth=True), 0.55)
    coat = nb.ramp(nb.add(nb.mul(n_big, 0.7), nb.mul(n_mid, 0.3)),
                   [(0.3, [c * 0.85 for c in base]), (0.7, [c * 1.15 for c in base])])
    coat = nb.mix_col(nb.add(nb.mul(hl, 0.35), nb.mul(polish, 0.25)), coat, [c * 1.6 for c in base])
    bare_c = nb.ramp(n_fine, [(0.3, [c * 0.88 for c in bare]), (0.7, [min(1.0, c * 1.08) for c in bare])])
    col = nb.mix_col(worn, coat, bare_c)
    col = nb.mix_col(dirt, col, (0.050, 0.046, 0.040))
    r = nb.add(rough, nb.remap(n_big, 0.3, 0.7, -0.045, 0.045))
    r = nb.add(r, nb.remap(n_mid, 0.3, 0.7, -0.025, 0.025))
    r = nb.sub(r, nb.mul(polish, 0.09))
    r = nb.sub(r, nb.mul(hl, 0.05))
    r = nb.lerp(worn, r, 0.27)
    r = nb.lerp(dirt, r, 0.72)
    # metallic: binary per material; only heavy grime in crevices turns dielectric (narrow step)
    grime = nb.remap(dirt, 0.42, 0.5)
    metal = nb.inv(grime)
    nrm = _micro_normal(nb, co, w, nb.mul(worn, -0.35), strength=1.0, milling=1.0,
                        scuff=nb.mul(contact, 1.0))
    nb.set(bsdf.inputs['Base Color'], col)
    nb.set(bsdf.inputs['Roughness'], r)
    nb.set(bsdf.inputs['Metallic'], metal)
    nb.set(bsdf.inputs['Normal'], nrm)
    m["iv_preset"] = "anodized"
    return m


def mat_steel(name, masks, base=(0.048, 0.048, 0.052), rough=0.36, metal=1.0, wear=1.0,
              grain=0.5, soot=None, seed=0, contact_attr="iv_contact", contact_default=0.3,
              bright=(0.30, 0.30, 0.31)):
    """Nitrided / blackened steel (metallic 1).  Wear to brighter steel on edges (contact
    driven).  Cavity grime and carbon fouling are dielectric layers with a NARROW transition, so
    metallic stays essentially binary.  soot = dict(axis='X', start, end) adds carbon fouling
    increasing from start to end along the axis (object coords, metres)."""
    m, nb, bsdf = _new_material(name)
    co = nb.coords('Object')
    w = _seed_w(seed)
    edge, cav, ao = _masks(nb, masks)
    contact = _contact(nb, contact_attr, contact_default)
    n_big = nb.noise(co, 14.0, 3.0, 0.5, w)
    n_mid = nb.noise(co, 80.0, 4.0, 0.55, w + 2.2)
    n_fine = nb.noise(co, 900.0, 2.0, 0.5, w + 4.4)
    patch = nb.remap(nb.noise(co, 30.0, 3.0, 0.6, w + 6.0), 0.4, 0.62)
    e = nb.mul(nb.mul(edge, nb.lerp(patch, 0.55, 1.2)), nb.lerp(contact, 0.5, 1.5))
    worn = nb.remap(e, 0.5 / max(wear, 1e-3), 0.68 / max(wear, 1e-3), smooth=True)
    dirt = nb.mul(nb.remap(cav, 0.55, 0.15, smooth=True), 0.6)
    coat = nb.ramp(nb.add(nb.mul(n_big, 0.7), nb.mul(n_fine, 0.3)),
                   [(0.35, [c * 0.88 for c in base]), (0.65, [c * 1.14 for c in base])])
    col = nb.mix_col(worn, coat, bright)
    col = nb.mix_col(dirt, col, (0.040, 0.037, 0.032))
    r = nb.add(rough, nb.remap(n_big, 0.3, 0.7, -0.04, 0.04))
    r = nb.add(r, nb.remap(n_fine, 0.3, 0.7, -0.03, 0.03))
    r = nb.lerp(worn, r, 0.24)
    r = nb.lerp(dirt, r, 0.65)
    diel = nb.remap(dirt, 0.44, 0.52)                  # heavy grime layer (narrow edge)
    if soot:
        ax = {'X': 0, 'Y': 1, 'Z': 2}[soot.get('axis', 'X')]
        comp = nb.xyz(co)[ax]
        sv = nb.remap(comp, soot['start'], soot['end'], smooth=True)
        sv = nb.mul(sv, nb.remap(n_mid, 0.25, 0.65, 0.5, 1.0))
        col = nb.mix_col(sv, col, (0.016, 0.015, 0.014))
        r = nb.lerp(sv, r, 0.72)
        diel = nb.maxf(diel, nb.remap(sv, 0.62, 0.72))   # thick carbon: dielectric, narrow step
    mt = nb.mul(metal, nb.inv(diel))
    h_extra = nb.add(nb.mul(n_fine, grain * 0.25), nb.mul(worn, -0.25))
    nrm = _micro_normal(nb, co, w + 1.0, h_extra, strength=0.8, milling=0.5)
    nb.set(bsdf.inputs['Base Color'], col)
    nb.set(bsdf.inputs['Roughness'], r)
    nb.set(bsdf.inputs['Metallic'], mt)
    nb.set(bsdf.inputs['Normal'], nrm)
    m["iv_preset"] = "steel"
    return m


def mat_phosphate(name, masks, seed=0):
    """Manganese-phosphate (parkerized) small parts: dark, grainy, rougher metal (metallic 1)."""
    return mat_steel(name, masks, base=(0.060, 0.061, 0.057), rough=0.6, metal=1.0,
                     wear=0.9, grain=0.9, seed=seed, bright=(0.24, 0.24, 0.24))


def mat_polymer(name, masks, base=(0.200, 0.140, 0.080), rough=0.66, seed=0, stipple=None,
                grain_scale=1300.0, grain_strength=0.14, texture=None):
    """Glass-filled polymer.  stipple = dict(zmax=..., [zmin=...], [normal_axis='Y'], scale=900)
    masks a stippled region (object coords, metres; optional restriction to faces facing
    along an axis).  texture='ribs_z' adds horizontal ribs."""
    m, nb, bsdf = _new_material(name)
    co = nb.coords('Object')
    w = _seed_w(seed)
    edge, cav, ao = _masks(nb, masks)
    n_big = nb.noise(co, 12.0, 3.0, 0.55, w)
    n_mid = nb.noise(co, 80.0, 4.0, 0.6, w + 1.3)
    grain = nb.noise(co, grain_scale, 2.0, 0.6, w + 2.6)
    e = nb.mul(edge, nb.remap(n_mid, 0.3, 0.7, 0.5, 1.4))
    worn = nb.mul(nb.remap(e, 0.5, 0.8, smooth=True), 0.6)
    dirt = nb.mul(nb.remap(cav, 0.6, 0.15, smooth=True), 0.6)
    coat = nb.ramp(n_big, [(0.3, [c * 0.93 for c in base]), (0.7, [c * 1.07 for c in base])])
    col = nb.mix_col(worn, coat, [min(1.0, c * 1.25 + 0.01) for c in base])
    col = nb.mix_col(dirt, col, [c * 0.55 for c in base])
    r = nb.add(rough, nb.remap(n_big, 0.3, 0.7, -0.05, 0.05))
    r = nb.lerp(worn, r, rough - 0.16)
    r = nb.lerp(dirt, r, 0.82)
    h = nb.mul(grain, grain_strength)
    if stipple:
        z = nb.xyz(co)[2]
        x = nb.xyz(co)[0]
        smask = nb.remap(z, stipple['zmax'], stipple['zmax'] - 0.004, smooth=True)
        if 'zmin' in stipple:
            smask = nb.mul(smask, nb.remap(z, stipple['zmin'], stipple['zmin'] + 0.004, smooth=True))
        if 'normal_axis' in stipple:
            # restrict to faces whose (object-space) normal is mostly along the given axis
            ax = {'X': 0, 'Y': 1, 'Z': 2}[stipple['normal_axis']]
            ncomp = nb.xyz(nb.node('ShaderNodeTexCoord').outputs['Normal'])[ax]
            smask = nb.mul(smask, nb.remap(nb.math('ABSOLUTE', ncomp), 0.75, 0.9, smooth=True))
        # even field of round dimples ~2.5 mm apart (>= 10 texels at ~45 px/cm, so they survive
        # the bake and the first mips): low Voronoi randomness, spherical dimple profile
        sc = stipple.get('scale', 400.0)
        vd = nb.voronoi(co, sc, w + 7.0, stipple.get('randomness', 0.55))
        dimple = nb.math('POWER', nb.remap(vd, 0.0, 0.42), 2.0)       # 0 at the cell centre -> 1
        rnd = nb.voronoi(co, sc, w + 7.0, stipple.get('randomness', 0.55), out='Color')
        rr = nb.sep(rnd)[0]
        depth = nb.remap(rr, 0.0, 1.0, 0.8, 1.0)
        h = nb.add(h, nb.mul(nb.mul(dimple, depth), nb.mul(smask, stipple.get('height', 1.0))))
        r = nb.lerp(nb.mul(smask, 0.9), r, min(0.92, rough + 0.14))
    if texture == 'ribs_z':
        rib = nb.wave(co, 180.0, 'Z', profile='SIN')
        h = nb.add(h, nb.mul(rib, 0.25))
    nrm = nb.bump(h, 0.35, 0.0006)
    nb.set(bsdf.inputs['Base Color'], col)
    nb.set(bsdf.inputs['Roughness'], r)
    nb.set(bsdf.inputs['Metallic'], 0.0)
    nb.set(bsdf.inputs['Normal'], nrm)
    m["iv_preset"] = "polymer"
    return m


def mat_rubber(name, masks, base=(0.017, 0.017, 0.018), rough=0.9, seed=0, ribs=None):
    """Soft rubber.  ribs = dict(axis='Z', scale=...) adds a wave-bump rib pattern."""
    m, nb, bsdf = _new_material(name)
    co = nb.coords('Object')
    w = _seed_w(seed)
    edge, cav, ao = _masks(nb, masks)
    n_big = nb.noise(co, 25.0, 3.0, 0.55, w)
    grain = nb.noise(co, 3200.0, 2.0, 0.6, w + 1.0)
    dirt = nb.mul(nb.remap(cav, 0.85, 0.3, smooth=True), 0.6)
    col = nb.ramp(n_big, [(0.3, [c * 0.85 for c in base]), (0.7, [c * 1.2 for c in base])])
    col = nb.mix_col(dirt, col, (0.045, 0.040, 0.034))
    wear = nb.mul(nb.remap(edge, 0.4, 0.8, smooth=True), 0.5)
    col = nb.mix_col(wear, col, [c * 1.8 for c in base])
    r = nb.add(rough, nb.remap(n_big, 0.3, 0.7, -0.04, 0.04))
    r = nb.lerp(wear, r, rough - 0.2)
    h = nb.mul(grain, 0.2)
    if ribs:
        rib = nb.wave(co, ribs.get('scale', 120.0), ribs.get('axis', 'Z'), profile='SIN')
        h = nb.add(h, nb.mul(rib, 0.6))
    nrm = nb.bump(h, 0.4, 0.0006)
    nb.set(bsdf.inputs['Base Color'], col)
    nb.set(bsdf.inputs['Roughness'], r)
    nb.set(bsdf.inputs['Metallic'], 0.0)
    nb.set(bsdf.inputs['Normal'], nrm)
    m["iv_preset"] = "rubber"
    return m


def mat_metal_color(name, masks, base, rough=0.3, seed=0, tarnish=0.5):
    """Brass / copper style bare coloured metal with light tarnish."""
    m, nb, bsdf = _new_material(name)
    co = nb.coords('Object')
    w = _seed_w(seed)
    edge, cav, ao = _masks(nb, masks)
    n_big = nb.noise(co, 60.0, 4.0, 0.6, w)
    n_fine = nb.noise(co, 1800.0, 2.0, 0.5, w + 1.0)
    t = nb.mul(nb.remap(n_big, 0.45, 0.72, smooth=True), tarnish)
    dirt = nb.mul(nb.remap(cav, 0.85, 0.35, smooth=True), 0.7)
    t = nb.maxf(t, dirt)
    col = nb.mix_col(t, base, [c * 0.55 for c in base])
    r = nb.lerp(t, rough, rough + 0.25)
    r = nb.add(r, nb.remap(n_fine, 0.3, 0.7, -0.03, 0.03))
    nrm = nb.bump(nb.mul(n_fine, 0.2), 0.05, 0.0002)
    nb.set(bsdf.inputs['Base Color'], col)
    nb.set(bsdf.inputs['Roughness'], r)
    nb.set(bsdf.inputs['Metallic'], 1.0)
    nb.set(bsdf.inputs['Normal'], nrm)
    m["iv_preset"] = "colored_metal"
    return m


def mat_brass(name, masks, seed=0):
    return mat_metal_color(name, masks, (0.74, 0.47, 0.15), 0.28, seed, 0.45)


def mat_copper(name, masks, seed=0):
    return mat_metal_color(name, masks, (0.80, 0.33, 0.17), 0.3, seed, 0.35)


def mat_paint(name, masks, color, rough=0.55, seed=0):
    """Filled engraving / marking paint (dielectric)."""
    m, nb, bsdf = _new_material(name)
    co = nb.coords('Object')
    w = _seed_w(seed)
    edge, cav, ao = _masks(nb, masks)
    n = nb.noise(co, 900.0, 3.0, 0.6, w)
    chip = nb.remap(n, 0.6, 0.66, smooth=True)
    col = nb.mix_col(nb.mul(chip, 0.7), color, (0.03, 0.03, 0.032))
    nb.set(bsdf.inputs['Base Color'], col)
    nb.set(bsdf.inputs['Roughness'], nb.lerp(chip, rough, 0.5))
    nb.set(bsdf.inputs['Metallic'], 0.0)
    m["iv_preset"] = "paint"
    return m


def mat_glass(name, tint=(0.94, 0.97, 1.0), rough=0.02, ior=1.52, thin_film_nm=0.0):
    """Constant (non-procedural) glass; survives export as plain factors."""
    m, nb, bsdf = _new_material(name)
    bsdf.inputs['Base Color'].default_value = (*tint, 1.0)
    bsdf.inputs['Roughness'].default_value = rough
    bsdf.inputs['IOR'].default_value = ior
    bsdf.inputs['Transmission Weight'].default_value = 1.0
    bsdf.inputs['Metallic'].default_value = 0.0
    if thin_film_nm > 0 and 'Thin Film Thickness' in bsdf.inputs:
        bsdf.inputs['Thin Film Thickness'].default_value = thin_film_nm
        bsdf.inputs['Thin Film IOR'].default_value = 1.38
    if hasattr(m, "surface_render_method"):
        m.surface_render_method = 'BLENDED'      # EEVEE / viewport only; Cycles ignores it
    m["iv_preset"] = "glass"
    return m


def mat_emissive(name, color=(1.0, 0.03, 0.02), strength=40.0, illuminate=True):
    """Constant emissive material.  illuminate=False: not sampled as a light (a reticle
    or indicator that should glow without lighting its surroundings)."""
    m, nb, bsdf = _new_material(name)
    if not illuminate and hasattr(m, "cycles"):
        m.cycles.emission_sampling = 'NONE' 
    bsdf.inputs['Base Color'].default_value = (*color, 1.0)
    bsdf.inputs['Emission Color'].default_value = (*color, 1.0)
    bsdf.inputs['Emission Strength'].default_value = strength
    bsdf.inputs['Roughness'].default_value = 0.4
    m["iv_preset"] = "emissive"
    return m


def mat_constant(name, color, rough=0.5, metal=0.0):
    """Constant (untextured) opaque material; survives export as plain factors."""
    m, nb, bsdf = _new_material(name)
    bsdf.inputs['Base Color'].default_value = (*color, 1.0)
    bsdf.inputs['Roughness'].default_value = rough
    bsdf.inputs['Metallic'].default_value = metal
    m["iv_preset"] = "constant"
    return m


def mat_clay(name="IV_Clay"):
    m, nb, bsdf = _new_material(name)
    bsdf.inputs['Base Color'].default_value = (0.18, 0.18, 0.18, 1.0)
    bsdf.inputs['Roughness'].default_value = 0.5
    return m


def _gltf_output_group():
    """Node group recognised by the glTF exporter to export an occlusion texture."""
    name = "glTF Material Output"
    g = bpy.data.node_groups.get(name)
    if g is None:
        g = bpy.data.node_groups.new(name, 'ShaderNodeTree')
        g.interface.new_socket("Occlusion", in_out='INPUT', socket_type='NodeSocketFloat')
        g.interface.new_socket("Thickness", in_out='INPUT', socket_type='NodeSocketFloat')
        g.nodes.new('NodeGroupInput')
    return g


def load_image(path, colorspace='sRGB'):
    path = os.path.abspath(path)
    for im in bpy.data.images:
        if im.filepath and os.path.abspath(bpy.path.abspath(im.filepath)) == path:
            im.reload()
            im.colorspace_settings.name = colorspace
            return im
    im = bpy.data.images.load(path)
    im.colorspace_settings.name = colorspace
    return im


def export_material(name, basecolor, orm, normal, uv_map="UVMap"):
    """Material that references ONLY baked images: BaseColor (sRGB), ORM (linear:
    R=AO -> glTF occlusion, G=roughness, B=metallic), Normal (OpenGL, tangent space)."""
    m, nb, bsdf = _new_material(name)
    uv = nb.node('ShaderNodeUVMap'); uv.uv_map = uv_map
    t_bc = nb.node('ShaderNodeTexImage'); t_bc.image = load_image(basecolor, 'sRGB')
    t_bc.name = "T_BaseColor"
    t_orm = nb.node('ShaderNodeTexImage'); t_orm.image = load_image(orm, 'Non-Color')
    t_orm.name = "T_ORM"
    t_n = nb.node('ShaderNodeTexImage'); t_n.image = load_image(normal, 'Non-Color')
    t_n.name = "T_Normal"
    for t in (t_bc, t_orm, t_n):
        nb.links.new(uv.outputs[0], t.inputs[0])
    nb.links.new(t_bc.outputs['Color'], bsdf.inputs['Base Color'])
    sep = nb.node('ShaderNodeSeparateColor')
    nb.links.new(t_orm.outputs['Color'], sep.inputs[0])
    nb.links.new(sep.outputs['Green'], bsdf.inputs['Roughness'])
    nb.links.new(sep.outputs['Blue'], bsdf.inputs['Metallic'])
    nm = nb.node('ShaderNodeNormalMap', space='TANGENT'); nm.uv_map = uv_map
    nb.links.new(t_n.outputs['Color'], nm.inputs['Color'])
    nb.links.new(nm.outputs['Normal'], bsdf.inputs['Normal'])
    go = nb.node('ShaderNodeGroup'); go.node_tree = _gltf_output_group()
    nb.links.new(sep.outputs['Red'], go.inputs['Occlusion'])
    m["iv_export"] = True
    return m


def swap_to_export_material(objs, mat):
    """Replace every material slot of objs with the single export material."""
    for o in objs:
        me = o.data
        me.materials.clear()
        me.materials.append(mat)
        for p in me.polygons:
            p.material_index = 0


# =============================================================================
# 5. UV helpers
# =============================================================================

def uv_islands(obj, uv_name=None):
    """UV islands of a mesh as lists of polygon indices (faces sharing an edge whose UVs
    match on both sides belong to the same island)."""
    me = obj.data
    uvl = me.uv_layers[uv_name] if uv_name else me.uv_layers.active
    bm = bmesh.new(); bm.from_mesh(me)
    uvk = bm.loops.layers.uv[uvl.name]
    parent = list(range(len(bm.faces)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    for e in bm.edges:
        if len(e.link_loops) != 2:
            continue
        l1, l2 = e.link_loops
        # l1 runs v0->v1 in face1, l2 runs v1->v0 in face2 (manifold, consistent winding)
        a1, b1 = l1[uvk].uv, l1.link_loop_next[uvk].uv
        a2, b2 = l2.link_loop_next[uvk].uv, l2[uvk].uv
        if (a1 - a2).length < 1e-6 and (b1 - b2).length < 1e-6:
            fa, fb = find(l1.face.index), find(l2.face.index)
            if fa != fb:
                parent[fa] = fb
    groups = {}
    for f in bm.faces:
        groups.setdefault(find(f.index), []).append(f.index)
    bm.free()
    return list(groups.values())


def uv_scale_islands(obj, factor_fn):
    """Scale each UV island about its UV centre by factor_fn(obj, info) where info has
    area3d (in world units^2), center (world), normal (area-weighted mean, world), faces,
    materials (names used by the island's faces)."""
    me = obj.data
    uv = me.uv_layers.active.data
    mw = obj.matrix_world
    n3 = mw.to_3x3().inverted().transposed()
    changed = 0
    for isl in uv_islands(obj):
        area = 0.0; c = Vector(); nrm = Vector()
        for fi in isl:
            p = me.polygons[fi]
            a = p.area
            area += a; c += (mw @ p.center) * a; nrm += (n3 @ p.normal) * a
        if area <= 0:
            continue
        mats = set()
        for fi in isl:
            mi = me.polygons[fi].material_index
            if mi < len(me.materials) and me.materials[mi]:
                mats.add(me.materials[mi].name)
        info = {"area3d": area * (mw.median_scale ** 2), "center": c / area,
                "normal": nrm.normalized() if nrm.length > 0 else Vector((0, 0, 1)), "faces": isl,
                "materials": mats}
        f = factor_fn(obj, info)
        if abs(f - 1.0) < 1e-6:
            continue
        loops = [li for fi in isl for li in me.polygons[fi].loop_indices]
        uc = Vector((0.0, 0.0))
        for li in loops:
            uc += uv[li].uv
        uc /= len(loops)
        for li in loops:
            uv[li].uv = uc + (uv[li].uv - uc) * f
        changed += 1
    return changed


def uv_snap_degenerate(obj, area_eps=5e-8, tex_size=None, min_island_texels=0.0,
                       min_thickness_texels=0.0, protect_materials=(), island_pixels=None):
    """Collapse faces that cannot carry texture onto a neighbouring UV point.

    Only for geometry that is truly degenerate: faces with 3D area < area_eps (world units^2;
    default 0.05 mm^2), plus -- as a last resort -- islands that still rasterise no pixel centre at
    all after uv_unwrap enlarged the small islands (island_pixels: {frozenset(faces): count}).
    Islands that use (or touch, e.g. the counter of a glyph) a material whose name contains one of
    `protect_materials` are never collapsed."""
    me = obj.data
    uv = me.uv_layers.active.data
    s2 = obj.matrix_world.median_scale ** 2
    bad = set(p.index for p in me.polygons if p.area * s2 < area_eps)
    if island_pixels:
        prot_verts = set()
        if protect_materials:
            for p in me.polygons:
                mi = p.material_index
                if mi < len(me.materials) and me.materials[mi] and \
                        any(pm in me.materials[mi].name for pm in protect_materials):
                    prot_verts.update(p.vertices)
        for isl, px in island_pixels.items():
            if px > 0:
                continue
            if any(v in prot_verts for fi in isl for v in me.polygons[fi].vertices):
                continue
            bad.update(isl)
    if not bad:
        return 0
    good_uv = {}
    for p in me.polygons:
        if p.index in bad:
            continue
        for li in p.loop_indices:
            good_uv.setdefault(me.loops[li].vertex_index, uv[li].uv.copy())
    fixed = 0
    for fi in bad:
        p = me.polygons[fi]
        known = [good_uv.get(me.loops[li].vertex_index) for li in p.loop_indices]
        known = [v for v in known if v is not None]
        if not known:
            continue
        for li in p.loop_indices:
            uv[li].uv = known[0]
        fixed += 1
    return fixed


# ---- UV rasterisation (pixel-centre coverage, the same rule the bake uses) -------------------

def _raster_tris(P, res):
    """P: (n, 3, 2) triangle corners in pixel units.  Returns (tri_index, pixel_index) arrays of
    every pixel centre inside a triangle (edge-inclusive)."""
    out_t = []; out_p = []
    if len(P) == 0:
        return np.zeros(0, np.int64), np.zeros(0, np.int64)
    x0 = np.floor(P[:, :, 0].min(1) - 0.5).astype(np.int64)
    y0 = np.floor(P[:, :, 1].min(1) - 0.5).astype(np.int64)
    x1 = np.ceil(P[:, :, 0].max(1) - 0.5).astype(np.int64)
    y1 = np.ceil(P[:, :, 1].max(1) - 0.5).astype(np.int64)
    w = x1 - x0 + 1; h = y1 - y0 + 1
    size = np.maximum(w, h)
    d = ((P[:, 1, 1] - P[:, 2, 1]) * (P[:, 0, 0] - P[:, 2, 0]) +
         (P[:, 2, 0] - P[:, 1, 0]) * (P[:, 0, 1] - P[:, 2, 1]))
    ok = np.abs(d) > 1e-12
    for K in (2, 4, 8, 16, 32, 64, 128):
        sel = np.nonzero(ok & (size <= K) & (size > K // 2 if K > 2 else True))[0]
        if len(sel) == 0:
            continue
        gx, gy = np.meshgrid(np.arange(K), np.arange(K))
        gx = gx.ravel(); gy = gy.ravel()
        for chunk in range(0, len(sel), max(1, 2000000 // (K * K))):
            t = sel[chunk:chunk + max(1, 2000000 // (K * K))]
            X = x0[t, None] + gx[None, :] + 0.5
            Y = y0[t, None] + gy[None, :] + 0.5
            Q = P[t]
            dd = d[t][:, None]
            l0 = ((Q[:, 1, 1] - Q[:, 2, 1])[:, None] * (X - Q[:, 2, 0][:, None]) +
                  (Q[:, 2, 0] - Q[:, 1, 0])[:, None] * (Y - Q[:, 2, 1][:, None])) / dd
            l1 = ((Q[:, 2, 1] - Q[:, 0, 1])[:, None] * (X - Q[:, 2, 0][:, None]) +
                  (Q[:, 0, 0] - Q[:, 2, 0])[:, None] * (Y - Q[:, 2, 1][:, None])) / dd
            l2 = 1.0 - l0 - l1
            e = -1e-7
            inside = (l0 >= e) & (l1 >= e) & (l2 >= e) & (X >= 0) & (Y >= 0) & (X < res) & (Y < res)
            ti, gi = np.nonzero(inside)
            out_t.append(t[ti])
            out_p.append((Y[ti, gi] - 0.5).astype(np.int64) * res + (X[ti, gi] - 0.5).astype(np.int64))
    big = np.nonzero(ok & (size > 128))[0]
    for t in big:
        xs = np.arange(max(0, x0[t]), min(res - 1, x1[t]) + 1) + 0.5
        ys = np.arange(max(0, y0[t]), min(res - 1, y1[t]) + 1) + 0.5
        if len(xs) == 0 or len(ys) == 0:
            continue
        X, Y = np.meshgrid(xs, ys)
        (ax, ay), (bx, by), (cx, cy) = P[t]
        dd = d[t]
        l0 = ((by - cy) * (X - cx) + (cx - bx) * (Y - cy)) / dd
        l1 = ((cy - ay) * (X - cx) + (ax - cx) * (Y - cy)) / dd
        l2 = 1 - l0 - l1
        inside = (l0 >= -1e-7) & (l1 >= -1e-7) & (l2 >= -1e-7)
        pix = ((Y[inside] - 0.5).astype(np.int64) * res + (X[inside] - 0.5).astype(np.int64))
        out_t.append(np.full(len(pix), t, np.int64)); out_p.append(pix)
    if not out_t:
        return np.zeros(0, np.int64), np.zeros(0, np.int64)
    return np.concatenate(out_t), np.concatenate(out_p)


def uv_island_raster(objs, res):
    """Rasterise every UV island of objs at res x res (pixel centres).  Returns a dict with
    per-island records (object, faces, pixel count, UV area in px^2, mean thickness in px), the
    coverage fraction and the number of pixels claimed by more than one island (overlap)."""
    islands = []           # (obj, faces)
    gid_of = []            # per object: array poly -> global island id
    all_t = []; all_p = []; all_g = []
    for o in objs:
        me = o.data
        if not me.uv_layers:
            continue
        isl = uv_islands(o)
        g = np.full(len(me.polygons), -1, np.int64)
        for fs in isl:
            g[fs] = len(islands)
            islands.append((o, fs))
        me.calc_loop_triangles()
        nt = len(me.loop_triangles)
        tl = np.empty(nt * 3, np.int32); me.loop_triangles.foreach_get("loops", tl)
        tp = np.empty(nt, np.int32); me.loop_triangles.foreach_get("polygon_index", tp)
        uv = np.empty(len(me.loops) * 2, np.float64); me.uv_layers.active.data.foreach_get("uv", uv)
        P = uv.reshape(-1, 2)[tl.reshape(-1, 3)] * res
        t, pix = _raster_tris(P, res)
        all_t.append(t); all_p.append(pix); all_g.append(g[tp[t]])
        gid_of.append((o, g, P, tp))
    n = len(islands)
    if all_p:
        pix = np.concatenate(all_p); gid = np.concatenate(all_g)
    else:
        pix = np.zeros(0, np.int64); gid = np.zeros(0, np.int64)
    pairs = np.unique(pix * (n + 1) + gid)
    upix = pairs // (n + 1); ugid = pairs % (n + 1)
    counts = np.bincount(ugid, minlength=n)
    per_pix = np.bincount(upix, minlength=res * res)
    covered = int((per_pix > 0).sum()); overlap = int((per_pix > 1).sum())
    # UV area and bbox per island (px units)
    area = np.zeros(n); bmin = np.full((n, 2), 1e18); bmax = np.full((n, 2), -1e18)
    for o, g, P, tp in gid_of:
        a = 0.5 * np.abs((P[:, 1, 0] - P[:, 0, 0]) * (P[:, 2, 1] - P[:, 0, 1]) -
                         (P[:, 2, 0] - P[:, 0, 0]) * (P[:, 1, 1] - P[:, 0, 1]))
        gi = g[tp]
        np.add.at(area, gi, a)
        np.minimum.at(bmin, gi, P.min(1)); np.maximum.at(bmax, gi, P.max(1))
    diag = np.hypot(*(bmax - bmin).T)
    thick = np.where(diag > 0, area / np.maximum(diag, 1e-9), 0.0)
    over_pix = np.nonzero(per_pix > 1)[0]
    over_islands = set()
    if len(over_pix):
        m = np.isin(upix, over_pix)
        over_islands = set(int(x) for x in ugid[m])
    return {"islands": islands, "pixels": counts, "area_px": area, "thick_px": thick,
            "coverage": covered / float(res * res), "overlap_px": overlap,
            "overlap_islands": over_islands, "res": res}


def _scale_island_uv(obj, faces, f):
    me = obj.data
    uv = me.uv_layers.active.data
    loops = [li for fi in faces for li in me.polygons[fi].loop_indices]
    c = Vector((0.0, 0.0))
    for li in loops:
        c += uv[li].uv
    c /= len(loops)
    for li in loops:
        uv[li].uv = c + (uv[li].uv - c) * f


def _pack(objs, margin, shape, rotate):
    select(objs, objs[0])
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.uv.select_all(action='SELECT')
    bpy.ops.uv.pack_islands(rotate=rotate, rotate_method='ANY', margin=margin, shape_method=shape,
                            margin_method='FRACTION', scale=True)
    bpy.ops.object.mode_set(mode='OBJECT')


def uv_planar_groups(obj, axis, max_angle=12.0, min_area=0.0):
    """Re-project connected face groups whose normals lie within max_angle of +-axis (object
    space) as single planar islands at the object's current UV density.  Smart projection can
    split a flat round face (a lathe pole fan) into wedge islands with stretch."""
    me = obj.data
    uvl = me.uv_layers.active.data
    ax = Vector(axis).normalized()
    cosl = math.cos(math.radians(max_angle))
    # current density (uv units per object unit)
    a3 = sum(p.area for p in me.polygons)
    auv = 0.0
    for p in me.polygons:
        pts = [uvl[li].uv for li in p.loop_indices]
        for k in range(1, len(pts) - 1):
            d1 = pts[k] - pts[0]; d2 = pts[k + 1] - pts[0]
            auv += abs(d1.x * d2.y - d1.y * d2.x) * 0.5
    if a3 <= 0 or auv <= 0:
        return 0
    s = math.sqrt(auv / a3)
    t1 = ax.orthogonal().normalized(); t2 = ax.cross(t1).normalized()
    cand = set(p.index for p in me.polygons if abs(p.normal.dot(ax)) >= cosl)
    bm = bmesh.new(); bm.from_mesh(me); bm.faces.ensure_lookup_table()
    groups = []; seen = set()
    for fi in cand:
        if fi in seen:
            continue
        st = [fi]; seen.add(fi); grp = []
        while st:
            f = st.pop(); grp.append(f)
            for e in bm.faces[f].edges:
                for g in e.link_faces:
                    if g.index in cand and g.index not in seen and \
                            (g.normal.dot(ax) > 0) == (bm.faces[f].normal.dot(ax) > 0):
                        seen.add(g.index); st.append(g.index)
        groups.append(grp)
    bm.free()
    n = 0
    for k, grp in enumerate(groups):
        if sum(me.polygons[f].area for f in grp) < min_area:
            continue
        off = Vector((5.0 + 0.37 * k, 5.0))        # arbitrary: pack places it
        for f in grp:
            for li in me.polygons[f].loop_indices:
                co = me.vertices[me.loops[li].vertex_index].co
                uvl[li].uv = off + Vector((co.dot(t1), co.dot(t2))) * s
        n += 1
    return n


def uv_cylinder_group(obj, axis, center, max_dev=15.0):
    """Unwrap the faces of a cylindrical surface around `axis` through `center` (object space)
    as one strip: u = radius * angle, v = position along the axis, at the object's current UV
    density.  Faces qualify when their normal is within max_dev degrees of perpendicular to the
    axis and they lie on the side surface (not the end caps).  Smart projection cuts a thin
    cylinder into quadrant islands with up to 2x stretch."""
    me = obj.data
    uvl = me.uv_layers.active.data
    ax = Vector(axis).normalized(); c0 = Vector(center)
    a3 = sum(p.area for p in me.polygons)
    auv = 0.0
    for p in me.polygons:
        pts = [uvl[li].uv for li in p.loop_indices]
        for k in range(1, len(pts) - 1):
            d1 = pts[k] - pts[0]; d2 = pts[k + 1] - pts[0]
            auv += abs(d1.x * d2.y - d1.y * d2.x) * 0.5
    if a3 <= 0 or auv <= 0:
        return 0
    s = math.sqrt(auv / a3)
    t1 = ax.orthogonal().normalized(); t2 = ax.cross(t1).normalized()
    sin_dev = math.sin(math.radians(max_dev))
    faces = [p for p in me.polygons if abs(p.normal.dot(ax)) <= sin_dev]
    if not faces:
        return 0
    off = Vector((7.0, 5.0))
    for p in faces:
        th = []; vs = []
        for li in p.loop_indices:
            co = me.vertices[me.loops[li].vertex_index].co - c0
            th.append(math.atan2(co.dot(t2), co.dot(t1)))
            vs.append(co.dot(ax))
        if max(th) - min(th) > math.pi:
            th = [t + 2 * math.pi if t < 0 else t for t in th]
        r = sum(((me.vertices[me.loops[li].vertex_index].co - c0) - ax * vs[k]).length
                for k, li in enumerate(p.loop_indices)) / len(th)
        for k, li in enumerate(p.loop_indices):
            uvl[li].uv = off + Vector((th[k] * r, vs[k])) * s
    return len(faces)


def uv_unwrap(objs, angle=60.0, island_margin=0.002, pack_margin=0.004, uv_name="UVMap",
              shape='CONCAVE', rotate=True, scale_fn=None, tex_size=None, protect_materials=(),
              planar_fn=None, min_island_px=12.0, min_thick_px=1.6, max_enlarge=6.0, report=None):
    """Multi-object smart UV project + pack into one shared 0..1 space (consistent texel
    density across all objects of a texture set).

    scale_fn(obj, island_info) -> factor gives hidden / interior islands less texture space.
    planar_fn(obj) -> [(axis, max_angle), ...] re-projects flat face groups as single islands;
    an entry ('CYL', axis, centre[, max_dev]) unwraps a cylindrical surface as one strip.
    With tex_size: islands that would rasterise fewer than `min_island_px` pixel centres (or are
    thinner than `min_thick_px`) are enlarged (up to max_enlarge x) and everything is re-packed,
    twice, instead of collapsing them onto a neighbour texel (which left them untextured and with
    undefined tangents).  After packing, islands of different parts must not share a pixel: if
    they do, the set is re-packed with a safer shape method.  Only faces < 0.05 mm^2 (and islands
    that still get no pixel at all) are collapsed.  `report` (dict) receives the statistics."""
    for o in objs:
        me = o.data
        while len(me.uv_layers) > 0:
            me.uv_layers.remove(me.uv_layers[0])
        me.uv_layers.new(name=uv_name)
    select(objs, objs[0])
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.uv.smart_project(angle_limit=math.radians(angle), island_margin=island_margin,
                             area_weight=0.0, correct_aspect=True, scale_to_bounds=False)
    bpy.ops.uv.select_all(action='SELECT')
    bpy.ops.uv.average_islands_scale()
    bpy.ops.object.mode_set(mode='OBJECT')
    if planar_fn is not None:
        for o in objs:
            for spec in (planar_fn(o) or []):
                if spec[0] == 'CYL':
                    uv_cylinder_group(o, spec[1], spec[2], spec[3] if len(spec) > 3 else 15.0)
                else:
                    uv_planar_groups(o, spec[0], spec[1])
    if scale_fn is not None:
        for o in objs:
            uv_scale_islands(o, scale_fn)
    _pack(objs, pack_margin, shape, rotate)
    stats = {"enlarged": [], "shape": shape}
    if tex_size:
        for it in range(2):
            r = uv_island_raster(objs, tex_size)
            n = 0
            for i, (o, fs) in enumerate(r["islands"]):
                px = r["pixels"][i]; ar = r["area_px"][i]
                if px >= min_island_px:
                    continue
                # too few pixel centres: enlarge about the island centre (a long thin strip that
                # already covers enough pixels is left alone -- enlarging it wastes space)
                f = math.sqrt(min_island_px / max(ar, 0.5))
                f = min(max(f, 1.25), max_enlarge)
                if f > 1.001:
                    _scale_island_uv(o, fs, f); n += 1
            stats["enlarged"].append(n)
            _pack(objs, pack_margin, shape, rotate)
        # islands of different parts must never share a pixel
        for sh in ([shape] + [x for x in ('CONVEX', 'AABB') if x != shape]):
            r = uv_island_raster(objs, tex_size)
            if r["overlap_px"] == 0:
                break
            log(f"uv: {r['overlap_px']} px shared by different islands with shape {sh}; re-packing")
            _pack(objs, pack_margin, 'CONVEX' if sh == shape else 'AABB', rotate)
            stats["shape"] = 'CONVEX' if sh == shape else 'AABB'
        r = uv_island_raster(objs, tex_size)
        stats.update({"coverage": round(r["coverage"], 4), "overlap_px": r["overlap_px"],
                      "islands": len(r["islands"]),
                      "islands_without_pixels": int((r["pixels"] == 0).sum())})
        per_obj = {}
        for i, (o, fs) in enumerate(r["islands"]):
            per_obj.setdefault(o.name, {})[frozenset(fs)] = int(r["pixels"][i])
    else:
        per_obj = {}
    deselect_all()
    snapped = sum(uv_snap_degenerate(o, protect_materials=protect_materials,
                                     island_pixels=per_obj.get(o.name)) for o in objs)
    stats["collapsed_faces"] = snapped
    log(f"uv: {len(objs)} objects, stats {stats}")
    if report is not None:
        report.update(stats)
    return stats


def uv_simple(obj, uv_name="UVMap"):
    """Quick smart projection for a single object (constant-material parts)."""
    uv_unwrap([obj], angle=66.0, uv_name=uv_name, shape='AABB')


def _mesh_arrays(obj):
    me = obj.data
    me.calc_loop_triangles()
    nt = len(me.loop_triangles)
    tri_v = np.empty(nt * 3, np.int32); me.loop_triangles.foreach_get("vertices", tri_v)
    tri_l = np.empty(nt * 3, np.int32); me.loop_triangles.foreach_get("loops", tri_l)
    co = np.empty(len(me.vertices) * 3, np.float64); me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    M = np.array(obj.matrix_world)
    co = co @ M[:3, :3].T + M[:3, 3]
    uv = None
    if me.uv_layers.active:
        uv = np.empty(len(me.loops) * 2, np.float64)
        me.uv_layers.active.data.foreach_get("uv", uv)
        uv = uv.reshape(-1, 2)
    return co, tri_v.reshape(-1, 3), tri_l.reshape(-1, 3), uv


def texel_density(obj, tex_size):
    """Average texel density in pixels per centimetre (world scale)."""
    co, tv, tl, uv = _mesh_arrays(obj)
    if uv is None or len(tv) == 0:
        return 0.0
    a = co[tv[:, 1]] - co[tv[:, 0]]; b = co[tv[:, 2]] - co[tv[:, 0]]
    area3 = 0.5 * np.linalg.norm(np.cross(a, b), axis=1).sum() * 1e4  # cm^2
    ua = uv[tl[:, 1]] - uv[tl[:, 0]]; ub = uv[tl[:, 2]] - uv[tl[:, 0]]
    area_uv = 0.5 * np.abs(ua[:, 0] * ub[:, 1] - ua[:, 1] * ub[:, 0]).sum()
    if area3 <= 0:
        return 0.0
    return math.sqrt(area_uv * tex_size * tex_size / area3)


def uv_overlap_estimate(objs, res=1024):
    """Rasterise all UV triangles of objs; fraction of covered texels hit more than once."""
    cnt = np.zeros((res, res), np.uint16)
    for o in objs:
        co, tv, tl, uv = _mesh_arrays(o)
        if uv is None:
            continue
        P = uv[tl] * res  # (n,3,2)
        # drop degenerate
        for tri in P:
            xmin = int(max(0, math.floor(tri[:, 0].min()))); xmax = int(min(res - 1, math.ceil(tri[:, 0].max())))
            ymin = int(max(0, math.floor(tri[:, 1].min()))); ymax = int(min(res - 1, math.ceil(tri[:, 1].max())))
            if xmax < xmin or ymax < ymin:
                continue
            xs = np.arange(xmin, xmax + 1) + 0.5; ys = np.arange(ymin, ymax + 1) + 0.5
            X, Y = np.meshgrid(xs, ys)
            (x0, y0), (x1, y1), (x2, y2) = tri
            d = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
            if abs(d) < 1e-12:
                continue
            l0 = ((y1 - y2) * (X - x2) + (x2 - x1) * (Y - y2)) / d
            l1 = ((y2 - y0) * (X - x2) + (x0 - x2) * (Y - y2)) / d
            l2 = 1 - l0 - l1
            e = -1e-6
            inside = (l0 >= e) & (l1 >= e) & (l2 >= e)
            cnt[ymin:ymax + 1, xmin:xmax + 1] += inside.astype(np.uint16)
    covered = int((cnt > 0).sum())
    over = int((cnt > 1).sum())
    return {"resolution": res, "covered_fraction": covered / float(res * res),
            "overlap_fraction_of_covered": (over / covered) if covered else 0.0}


# =============================================================================
# 6. Baking
# =============================================================================

def _float_image(name, size, fill):
    """Float bake target.  Alpha starts at 0: Cycles writes alpha 1 into every pixel it
    bakes, which gives an exact coverage mask for our own margin dilation."""
    im = bpy.data.images.get(name)
    if im is not None:
        bpy.data.images.remove(im)
    im = bpy.data.images.new(name, size, size, alpha=True, float_buffer=True)
    im.colorspace_settings.name = 'Non-Color'
    px = np.empty((size, size, 4), np.float32); px[:] = (*fill, 0.0)
    im.pixels.foreach_set(px.ravel())
    return im


def dilate(arr, iterations, fill=None):
    """Nearest-texel margin: grow baked pixels (alpha > 0.5) outward `iterations` times,
    each new pixel = mean of its already-filled 8-neighbours.  Unlike a per-object margin,
    ownership is purely by distance, so a thin face at an island border takes its own
    island's colour, never the margin of a neighbouring object's island."""
    rgb = arr[..., :3].astype(np.float32).copy()
    m = arr[..., 3] > 0.5
    H, W = m.shape
    for _ in range(iterations):
        if m.all():
            break
        pm = np.pad(m, 1, mode='constant')
        pr = np.pad(rgb, ((1, 1), (1, 1), (0, 0)), mode='edge')
        acc = np.zeros_like(rgb); cnt = np.zeros((H, W), np.float32)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dy == 0 and dx == 0:
                    continue
                sm = pm[1 + dy:1 + dy + H, 1 + dx:1 + dx + W]
                acc += pr[1 + dy:1 + dy + H, 1 + dx:1 + dx + W] * sm[..., None]
                cnt += sm
        new = (~m) & (cnt > 0)
        if not new.any():
            break
        rgb[new] = acc[new] / cnt[new][:, None]
        m = m | new
    out = np.empty_like(arr)
    out[..., :3] = rgb
    if fill is not None:
        out[~m, 0], out[~m, 1], out[~m, 2] = fill
    out[..., 3] = 1.0
    return out


def image_to_array(im):
    w, h = im.size
    a = np.empty(w * h * 4, np.float32)
    im.pixels.foreach_get(a)
    return a.reshape(h, w, 4)


def linear_to_srgb(x):
    x = np.clip(x, 0.0, 1.0)
    return np.where(x <= 0.0031308, x * 12.92, 1.055 * np.power(x, 1 / 2.4) - 0.055)


def save_png(arr01, path, mode='RGB', dither_seed=None):
    """arr01: HxWxC float 0..1, Blender row order (bottom row first).  dither_seed: add +-0.5 LSB
    of deterministic noise before quantising (subtle normal-map slopes then survive 8 bits as
    an unbanded average instead of snapping to the flat value)."""
    from PIL import Image
    a = np.flipud(arr01)
    if dither_seed is not None:
        rng = np.random.default_rng(dither_seed)
        a = a + (rng.random(a.shape, dtype=np.float32) - 0.5) / 255.0
    a = np.clip(np.round(a * 255.0), 0, 255).astype(np.uint8)
    if mode == 'L':
        img = Image.fromarray(a[..., 0], 'L')
    else:
        img = Image.fromarray(a[..., :3], 'RGB')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.save(path, optimize=False, compress_level=6)
    return path


def normal_gl_to_dx(src, dst):
    """DirectX (Unreal) normal map from an OpenGL one: invert the green channel."""
    from PIL import Image
    a = np.array(Image.open(src).convert('RGB'))
    a[..., 1] = 255 - a[..., 1]
    Image.fromarray(a, 'RGB').save(dst)
    return dst


def _materials_of(objs):
    mats = []
    for o in objs:
        for m in o.data.materials:
            if m and m not in mats:
                mats.append(m)
    return mats


def _bake(objs, btype, samples, margin):
    sc = bpy.context.scene
    sc.cycles.samples = samples
    sc.cycles.use_adaptive_sampling = False
    sc.render.bake.margin = margin
    sc.render.bake.margin_type = 'EXTEND'
    sc.render.bake.use_selected_to_active = False
    sc.render.bake.target = 'IMAGE_TEXTURES'
    if btype == 'NORMAL':
        sc.render.bake.normal_space = 'TANGENT'
        sc.render.bake.normal_r = 'POS_X'
        sc.render.bake.normal_g = 'POS_Y'    # OpenGL (+Y up)
        sc.render.bake.normal_b = 'POS_Z'
    select(objs, objs[0])
    t0 = time.time()
    # margin 0 + our own distance-based dilation (see dilate()); no clearing so the alpha-0
    # initialisation marks unbaked pixels
    bpy.ops.object.bake(type=btype, margin=0, use_clear=False)
    log("  bake", btype, "%.1fs" % (time.time() - t0))


def _set_target(mats, image):
    for m in mats:
        nt = m.node_tree
        tn = nt.nodes.get("IV_BAKE_TARGET")
        if tn is None:
            tn = nt.nodes.new('ShaderNodeTexImage'); tn.name = "IV_BAKE_TARGET"
            tn.location = (300, 400)
        tn.image = image
        for n in nt.nodes:
            n.select = False
        tn.select = True
        nt.nodes.active = tn


def _route_emission(mats, source):
    """Temporarily connect an Emission shader to the output, fed by `source`:
    'Base Color' | 'Roughness' | 'Metallic' (Principled inputs) or 'MASKS'."""
    saved = []
    for m in mats:
        nt = m.node_tree
        out = nt.nodes["OUT"]
        bsdf = nt.nodes["BSDF"]
        em = nt.nodes.new('ShaderNodeEmission'); em.name = "IV_BAKE_EMIT"
        em.inputs['Strength'].default_value = 1.0
        if source == 'MASKS':
            g = nt.nodes.get("IV_MASKS")
            if g is None:     # constant materials: open, unoccluded
                em.inputs['Color'].default_value = (0.0, 1.0, 1.0, 1.0)
            else:
                cc = nt.nodes.new('ShaderNodeCombineColor'); cc.name = "IV_BAKE_CC"
                nt.links.new(g.outputs['Edge'], cc.inputs[0])
                nt.links.new(g.outputs['Cavity'], cc.inputs[1])
                nt.links.new(g.outputs['AO'], cc.inputs[2])
                nt.links.new(cc.outputs[0], em.inputs['Color'])
        else:
            inp = bsdf.inputs[source]
            if inp.is_linked:
                nt.links.new(inp.links[0].from_socket, em.inputs['Color'])
            else:
                v = inp.default_value
                em.inputs['Color'].default_value = (v[0], v[1], v[2], 1.0) if hasattr(v, "__len__") else (v, v, v, 1.0)
        nt.links.new(em.outputs[0], out.inputs['Surface'])
        saved.append(m)
    return saved


def _restore_bsdf(mats):
    for m in mats:
        nt = m.node_tree
        for nm in ("IV_BAKE_EMIT", "IV_BAKE_CC"):
            n = nt.nodes.get(nm)
            if n:
                nt.nodes.remove(n)
        nt.links.new(nt.nodes["BSDF"].outputs[0], nt.nodes["OUT"].inputs['Surface'])


def bake_texture_set(set_name, objs, masks_group, tex_dir, prefix, size=2048,
                     mask_samples=24, final_samples=4, margin=16, isolate=None,
                     intermediate_dir=None):
    """Two-stage bake of one texture set shared by `objs` (one UV map, packed together).

    Stage 1: bake the procedural mask group (R edge, G cavity, B AO) with many samples.
             `isolate` = list of object groups; each group is moved 10 m apart while the
             masks are baked so detachable parts (e.g. a magazine) receive no occlusion
             from the weapon they are removed from.
    Stage 2: switch the mask group to the baked image (noise-free), then bake BaseColor,
             Roughness, Metallic (emission routing) and the tangent-space Normal (OpenGL).
    Every pass bakes with margin 0; `margin` px of padding are then added by dilate()
    (distance-based ownership; Blender's per-object margin lets one object's margin
    overwrite another object's unrasterised island borders).
    Writes <prefix><set>_BaseColor.png (sRGB), _Normal.png (OpenGL), _Normal_DX.png,
    _ORM.png (R AO, G roughness, B metallic).  Returns dict of paths."""
    t_all = time.time()
    os.makedirs(tex_dir, exist_ok=True)
    intermediate_dir = intermediate_dir or os.path.join(tex_dir, "Intermediate")
    os.makedirs(intermediate_dir, exist_ok=True)
    mats = _materials_of(objs)
    base = f"{prefix}{set_name}"
    log(f"bake set {set_name}: {len(objs)} objects, {len(mats)} materials, {size}px")

    # ---- stage 1: masks
    im_mask = _float_image(base + "_Masks", size, (0.0, 1.0, 1.0))
    _set_target(mats, im_mask)
    _mask_group_procedural(masks_group)
    moved = []
    if isolate:
        for gi, grp in enumerate(isolate):
            for o in grp:
                o.location.y += 10.0 * (gi + 1)
                moved.append((o, 10.0 * (gi + 1)))
    bpy.context.view_layer.update()
    _route_emission(mats, 'MASKS')
    _bake(objs, 'EMIT', mask_samples, margin)
    _restore_bsdf(mats)
    for o, dy in moved:
        o.location.y -= dy
    bpy.context.view_layer.update()
    mask_arr = dilate(image_to_array(im_mask), margin, fill=(0.0, 1.0, 1.0))
    im_mask.pixels.foreach_set(mask_arr.ravel())     # stage 2 samples the dilated masks
    mask_path = save_png(mask_arr, os.path.join(intermediate_dir, base + "_Masks.png"))
    mask_group_use_image(masks_group, im_mask)

    # ---- stage 2: channels
    out = {}
    chans = {}
    for chan, fill in (("Base Color", (0.18, 0.18, 0.18)), ("Roughness", (0.6, 0.6, 0.6)),
                       ("Metallic", (0.0, 0.0, 0.0))):
        im = _float_image(f"{base}_{chan.replace(' ', '')}", size, fill)
        _set_target(mats, im)
        _route_emission(mats, chan)
        _bake(objs, 'EMIT', final_samples, margin)
        _restore_bsdf(mats)
        chans[chan] = dilate(image_to_array(im), margin, fill=fill)
    im_n = _float_image(base + "_NormalGL", size, (0.5, 0.5, 1.0))
    _set_target(mats, im_n)
    _bake(objs, 'NORMAL', final_samples, margin)
    n_arr = dilate(image_to_array(im_n), margin, fill=(0.5, 0.5, 1.0))

    bc = chans["Base Color"].copy()
    bc[..., :3] = linear_to_srgb(bc[..., :3])
    out["BaseColor"] = save_png(bc, os.path.join(tex_dir, base + "_BaseColor.png"))
    out["Normal"] = save_png(n_arr, os.path.join(tex_dir, base + "_Normal.png"))
    out["Normal_DX"] = normal_gl_to_dx(out["Normal"], os.path.join(tex_dir, base + "_Normal_DX.png"))
    orm = np.zeros_like(bc)
    orm[..., 0] = np.clip(mask_arr[..., 2], 0, 1)
    orm[..., 1] = np.clip(chans["Roughness"][..., 0], 0, 1)
    orm[..., 2] = np.clip(chans["Metallic"][..., 0], 0, 1)
    orm[..., 3] = 1.0
    out["ORM"] = save_png(orm, os.path.join(tex_dir, base + "_ORM.png"))
    out["Masks_intermediate"] = mask_path
    # remove bake target nodes (keep materials clean)
    for m in mats:
        tn = m.node_tree.nodes.get("IV_BAKE_TARGET")
        if tn:
            m.node_tree.nodes.remove(tn)
    log(f"bake set {set_name} done in {time.time() - t_all:.1f}s")
    return out


# =============================================================================
# 7. LODs
# =============================================================================

def make_lod(src, ratio, name, col=None, sharp_angle=50.0, min_faces=0):
    """Decimated copy (collapse, triangulated) keeping UVs, materials and vertex groups;
    normals re-weighted afterwards.  Parent / armature modifier are copied."""
    me = src.data.copy()
    ob = bpy.data.objects.new(name, me)
    (col or bpy.context.scene.collection).objects.link(ob)
    ob.matrix_world = src.matrix_world.copy()
    nf = len(me.polygons)
    r = ratio
    if min_faces and nf * ratio < min_faces:
        r = min(1.0, min_faces / max(nf, 1))
    if r < 0.999:
        d = ob.modifiers.new("dec", 'DECIMATE')
        d.decimate_type = 'COLLAPSE'
        d.ratio = r
        d.use_collapse_triangulate = True
        apply_modifiers(ob)
        clear_custom_normals(ob)
        finish_shading(ob, sharp_angle=sharp_angle, weighted=True, triangulate=True)
    return ob


def clear_custom_normals(obj):
    me = obj.data
    if me.has_custom_normals:
        attr = me.attributes.get("custom_normal")
        if attr:
            me.attributes.remove(attr)


# =============================================================================
# 8. Validation
# =============================================================================

def mesh_checks(obj, tex_size=None):
    me = obj.data
    bm = bmesh.new(); bm.from_mesh(me)
    bm.edges.ensure_lookup_table()
    nonman = 0; boundary = 0; inconsistent = 0
    for e in bm.edges:
        lf = len(e.link_faces)
        if lf != 2:
            nonman += 1
            if lf == 1:
                boundary += 1
        else:
            l1, l2 = e.link_loops[0], e.link_loops[1]
            if l1.vert == l2.vert:
                inconsistent += 1
    loose_v = sum(1 for v in bm.verts if not v.link_edges)
    loose_e = sum(1 for e in bm.edges if not e.link_faces)
    # folded / flipped faces: geometric normal opposes the (custom) corner normals.  These
    # pass the winding test but render inside-out with back-face culling (holes in engine).
    cn = me.corner_normals
    s2 = obj.matrix_world.median_scale ** 2
    opposing = 0
    for p in me.polygons:
        if p.area * s2 < 1e-10:
            continue
        avg = Vector()
        for li in p.loop_indices:
            avg += cn[li].vector
        if avg.dot(p.normal) < 0:
            opposing += 1
    zero = sum(1 for f in bm.faces if f.calc_area() < 1e-11)
    # connected shells (face-connected components)
    bm.faces.ensure_lookup_table()
    seen = set(); shells = 0
    for f in bm.faces:
        if f.index in seen:
            continue
        shells += 1
        st = [f]; seen.add(f.index)
        while st:
            g = st.pop()
            for e in g.edges:
                for h in e.link_faces:
                    if h.index not in seen:
                        seen.add(h.index); st.append(h)
    keys = {}
    dup = 0
    for f in bm.faces:
        k = tuple(sorted(v.index for v in f.verts))
        if k in keys:
            dup += 1
        keys[k] = 1
    bm.free()
    mn, mx = world_bbox_fast([obj])
    d = {
        "tris": tri_count(obj),
        "verts": len(me.vertices),
        "non_manifold_edges": nonman,
        "boundary_edges": boundary,
        "inconsistent_normal_edges": inconsistent,
        "faces_opposing_vertex_normals": opposing,
        "loose_verts": loose_v,
        "loose_edges": loose_e,
        "zero_area_faces": zero,
        "duplicate_faces": dup,
        "shells": shells,
        "deform_weights_without_groups": (sum(1 for v in me.vertices if len(v.groups))
                                          if len(obj.vertex_groups) == 0 else 0),
        "uv_layers": [u.name for u in me.uv_layers],
        "missing_uvs": len(me.uv_layers) == 0,
        "has_custom_normals": bool(me.has_custom_normals),
        "bbox_min_m": [round(v, 5) for v in mn],
        "bbox_max_m": [round(v, 5) for v in mx],
        "dimensions_cm": [round((mx[i] - mn[i]) * 100, 3) for i in range(3)],
        "materials": [],
    }
    if me.uv_layers:
        uv = np.empty(len(me.loops) * 2, np.float64)
        me.uv_layers.active.data.foreach_get("uv", uv)
        uv = uv.reshape(-1, 2)
        d["uv_min"] = [round(float(x), 5) for x in uv.min(0)] if len(uv) else None
        d["uv_max"] = [round(float(x), 5) for x in uv.max(0)] if len(uv) else None
        d["uv_out_of_bounds_loops"] = int(((uv < -1e-5) | (uv > 1 + 1e-5)).any(1).sum())
        # faces whose UVs have (numerically) zero area: they carry no texels / no tangent basis
        s2 = obj.matrix_world.median_scale ** 2
        zc = 0; za = 0.0; zmax = 0.0
        for p in me.polygons:
            pts = [uv[li] for li in p.loop_indices]
            a_uv = 0.0
            for k in range(1, len(pts) - 1):
                a_uv += abs((pts[k][0] - pts[0][0]) * (pts[k + 1][1] - pts[0][1]) -
                            (pts[k + 1][0] - pts[0][0]) * (pts[k][1] - pts[0][1])) * 0.5
            if a_uv < 1e-12:
                zc += 1; a3 = p.area * s2; za += a3; zmax = max(zmax, a3)
        d["zero_uv_faces"] = zc
        d["zero_uv_area_mm2"] = round(za * 1e6, 3)
        d["zero_uv_max_face_mm2"] = round(zmax * 1e6, 4)
        if tex_size:
            d["texel_density_px_per_cm"] = round(texel_density(obj, tex_size), 2)
    for m in me.materials:
        md = {"name": m.name if m else None, "images": []}
        if m and m.use_nodes:
            for n in m.node_tree.nodes:
                if n.type == 'TEX_IMAGE' and n.image:
                    p = bpy.path.abspath(n.image.filepath)
                    md["images"].append({"node": n.name, "path": os.path.abspath(p) if p else None,
                                         "exists": bool(p) and os.path.exists(p),
                                         "colorspace": n.image.colorspace_settings.name})
                if n.type not in ('TEX_IMAGE', 'BSDF_PRINCIPLED', 'OUTPUT_MATERIAL', 'NORMAL_MAP',
                                  'SEPRGB', 'SEPARATE_COLOR', 'UVMAP', 'GROUP', 'FRAME', 'REROUTE'):
                    md.setdefault("non_image_nodes", []).append(n.type)
        d["materials"].append(md)
    # skinning
    arm_mods = [mo for mo in obj.modifiers if mo.type == 'ARMATURE']
    if arm_mods:
        arm = arm_mods[0].object
        bones = set(b.name for b in arm.data.bones) if arm else set()
        groups = {vg.index: vg.name for vg in obj.vertex_groups}
        bad_group = [n for n in groups.values() if n not in bones]
        nonrigid = 0; unweighted = 0
        for v in me.vertices:
            ws = [g.weight for g in v.groups if g.weight > 1e-6]
            if not ws:
                unweighted += 1
            elif len(ws) != 1 or abs(ws[0] - 1.0) > 1e-4:
                nonrigid += 1
        d["skin"] = {"armature": arm.name if arm else None, "groups": sorted(groups.values()),
                     "groups_without_bone": bad_group, "unweighted_verts": unweighted,
                     "non_rigid_verts": nonrigid}
    return d


def validate(report_path, objs, armature=None, texture_sets=None, extra=None, shells=None,
             max_zero_uv_face_mm2=None):
    """Write a JSON validation report.  texture_sets = {name: {"objects": [...],
    "size": 2048}} enables texel density and UV checks per set: any pixel shared by two
    different UV islands is a problem.  shells = {base object name: expected shell count}
    (every other object must be exactly ONE connected shell; LOD suffixes are ignored).
    max_zero_uv_face_mm2: faces with zero UV area must all be smaller than this."""
    t0 = time.time()
    set_of = {}
    for sname, sd in (texture_sets or {}).items():
        for o in sd["objects"]:
            set_of[o.name] = (sname, sd["size"])
    rep = {"generated_by": f"ivlib {LIB_VERSION}", "blender": bpy.app.version_string,
           "time": time.strftime("%Y-%m-%d %H:%M:%S"), "objects": {}, "summary": {}}
    tot = 0
    problems = []
    for o in objs:
        s = set_of.get(o.name)
        d = mesh_checks(o, s[1] if s else None)
        d["texture_set"] = s[0] if s else None
        rep["objects"][o.name] = d
        tot += d["tris"]
        for k in ("non_manifold_edges", "loose_verts", "loose_edges", "zero_area_faces",
                  "duplicate_faces", "inconsistent_normal_edges", "faces_opposing_vertex_normals"):
            if d[k]:
                problems.append(f"{o.name}: {k}={d[k]}")
        if d["missing_uvs"]:
            problems.append(f"{o.name}: missing UVs")
        if d.get("uv_out_of_bounds_loops"):
            problems.append(f"{o.name}: {d['uv_out_of_bounds_loops']} UV loops outside 0..1")
        for md in d["materials"]:
            for im in md["images"]:
                if not im["exists"]:
                    problems.append(f"{o.name}: missing image {im['path']}")
            if md.get("non_image_nodes"):
                problems.append(f"{o.name}: material {md['name']} has non-exportable nodes {md['non_image_nodes']}")
        sk = d.get("skin")
        if sk and (sk["groups_without_bone"] or sk["unweighted_verts"] or sk["non_rigid_verts"]):
            problems.append(f"{o.name}: skin issues {sk}")
        if d.get("deform_weights_without_groups"):
            problems.append(f"{o.name}: {d['deform_weights_without_groups']} vertices carry deform weights "
                            f"but the object has no vertex groups")
        if shells is not None:
            base = o.name.split("_LOD")[0]
            exp = shells.get(base, 1)
            if d["shells"] != exp:
                problems.append(f"{o.name}: {d['shells']} connected shells, expected {exp}")
        if max_zero_uv_face_mm2 is not None and d.get("zero_uv_max_face_mm2", 0) > max_zero_uv_face_mm2:
            problems.append(f"{o.name}: zero-UV-area face of {d['zero_uv_max_face_mm2']} mm2 "
                            f"(limit {max_zero_uv_face_mm2})")
    rep["summary"]["total_tris"] = tot
    if texture_sets:
        rep["texture_sets"] = {}
        for sname, sd in texture_sets.items():
            r = uv_island_raster(sd["objects"], sd["size"])
            dens = [texel_density(o, sd["size"]) for o in sd["objects"]]
            ov = {"resolution": sd["size"], "covered_fraction": round(r["coverage"], 4),
                  "pixels_shared_by_different_islands": r["overlap_px"],
                  "islands": len(r["islands"]),
                  "islands_without_pixel_centres": int(((r["pixels"] == 0) & (r["area_px"] > 1e-6)).sum()),
                  "collapsed_degenerate_faces": int((r["area_px"] <= 1e-6).sum()),
                  "method": "pixel-centre rasterisation per island at the texture size"}
            rep["texture_sets"][sname] = {"objects": [o.name for o in sd["objects"]],
                                          "size": sd["size"], "uv_overlap": ov,
                                          "texel_density_min": round(min(dens), 2),
                                          "texel_density_max": round(max(dens), 2)}
            if r["overlap_px"] > 0:
                problems.append(f"set {sname}: {r['overlap_px']} px shared by different UV islands")
    if armature:
        bones = armature.data.bones
        rep["armature"] = {"name": armature.name, "bone_count": len(bones),
                           "bones": {b.name: {"head_cm": [round(x * 100, 3) for x in (armature.matrix_world @ b.head_local)],
                                              "parent": b.parent.name if b.parent else None,
                                              "deform": b.use_deform} for b in bones}}
    rep["problems"] = problems
    rep["summary"]["problem_count"] = len(problems)
    if extra:
        rep.update(extra)
    rep["summary"]["validation_seconds"] = round(time.time() - t0, 1)
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w") as f:
        json.dump(rep, f, indent=2)
    log(f"validation: {len(problems)} problems, {tot} tris -> {report_path}")
    return rep


# =============================================================================
# 9. Render helpers
# =============================================================================

def clear_lights_cameras():
    for o in list(bpy.data.objects):
        if o.type in ('LIGHT', 'CAMERA'):
            bpy.data.objects.remove(o, do_unlink=True)


def world_color(color=(0.18, 0.18, 0.19), strength=1.0):
    w = bpy.data.worlds.get("IV_World") or bpy.data.worlds.new("IV_World")
    w.use_nodes = True
    nt = w.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    bg = nt.nodes.new('ShaderNodeBackground')
    bg.inputs['Color'].default_value = (*color, 1.0)
    bg.inputs['Strength'].default_value = strength
    out = nt.nodes.new('ShaderNodeOutputWorld')
    nt.links.new(bg.outputs[0], out.inputs[0])
    bpy.context.scene.world = w
    return w


def world_sky(sun_elevation=35.0, sun_rotation=-60.0, strength=0.25, altitude=300.0,
              air=1.0, dust=1.5, ozone=1.0, sun_disc=False, background_strength=None):
    """Nishita physical sky.  sun_rotation is the sun azimuth in degrees measured from +Y
    towards +X (verified empirically in bpy 4.5: 0 -> sun towards +Y, 90 -> towards +X).
    sun_disc=False keeps the sky dome only; pair with add_sun() for crisp shadows."""
    w = bpy.data.worlds.get("IV_World") or bpy.data.worlds.new("IV_World")
    w.use_nodes = True
    nt = w.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    sky = nt.nodes.new('ShaderNodeTexSky')
    sky.sky_type = 'NISHITA'
    sky.sun_disc = sun_disc
    sky.sun_elevation = math.radians(sun_elevation)
    sky.sun_rotation = math.radians(sun_rotation)
    sky.altitude = altitude
    sky.air_density = air
    sky.dust_density = dust
    sky.ozone_density = ozone
    bg = nt.nodes.new('ShaderNodeBackground')
    bg.inputs['Strength'].default_value = strength
    nt.links.new(sky.outputs[0], bg.inputs[0])
    out = nt.nodes.new('ShaderNodeOutputWorld')
    if background_strength is not None:
        # camera rays see a different strength than lighting rays
        lp = nt.nodes.new('ShaderNodeLightPath')
        bg2 = nt.nodes.new('ShaderNodeBackground')
        bg2.inputs['Strength'].default_value = background_strength
        nt.links.new(sky.outputs[0], bg2.inputs[0])
        mix = nt.nodes.new('ShaderNodeMixShader')
        nt.links.new(lp.outputs['Is Camera Ray'], mix.inputs[0])
        nt.links.new(bg.outputs[0], mix.inputs[1])
        nt.links.new(bg2.outputs[0], mix.inputs[2])
        nt.links.new(mix.outputs[0], out.inputs[0])
    else:
        nt.links.new(bg.outputs[0], out.inputs[0])
    bpy.context.scene.world = w
    return w


def sun_direction(elevation, rotation):
    """Unit vector pointing TO the sun for the Nishita convention used by world_sky."""
    el = math.radians(elevation); rot = math.radians(rotation)
    # Nishita (bpy 4.5, measured): rotation 0 -> +Y, 90 -> +X
    return Vector((math.sin(rot) * math.cos(el), math.cos(rot) * math.cos(el), math.sin(el)))


def add_sun(elevation=35.0, rotation=-60.0, strength=4.0, angle=0.6, name="IV_Sun"):
    d = sun_direction(elevation, rotation)
    ld = bpy.data.lights.new(name, 'SUN')
    ld.energy = strength
    ld.angle = math.radians(angle)
    ob = bpy.data.objects.new(name, ld)
    bpy.context.scene.collection.objects.link(ob)
    # sun light shines along its local -Z; point -Z away from the sun direction
    ob.rotation_euler = (-d).to_track_quat('-Z', 'Y').to_euler()
    return ob


def add_area(name, loc, target, size, energy, color=(1, 1, 1)):
    ld = bpy.data.lights.new(name, 'AREA')
    ld.size = size
    ld.energy = energy
    ld.color = color
    ob = bpy.data.objects.new(name, ld)
    bpy.context.scene.collection.objects.link(ob)
    ob.location = loc
    ob.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat('-Z', 'Y').to_euler()
    return ob


def studio_lighting(center, radius, key_energy=None, world_strength=1.0, world=(0.030, 0.030, 0.032)):
    """Product-style studio rig scaled to the subject radius (metres): dark surround so
    black finishes stay black, large soft key + top box for form, strip rim for edges."""
    c = Vector(center)
    r = max(radius, 0.05)
    e = key_energy or 120.0 * (r / 0.5) ** 2
    world_color(world, world_strength)
    L = []
    L.append(add_area("IV_Key", c + Vector((0.45, -1.3, 1.1)) * r * 2.4, c, r * 2.0, e))
    L.append(add_area("IV_Top", c + Vector((0.05, 0.1, 1.6)) * r * 2.4, c, r * 2.6, e * 0.55))
    L.append(add_area("IV_Fill", c + Vector((-1.1, -1.0, 0.1)) * r * 2.4, c, r * 2.2, e * 0.18))
    rim = add_area("IV_Rim", c + Vector((-0.5, 1.4, 0.8)) * r * 2.4, c, r * 0.5, e * 0.7)
    rim.data.shape = 'RECTANGLE'; rim.data.size = r * 2.5; rim.data.size_y = r * 0.35
    L.append(rim)
    L.append(add_area("IV_Floor", c + Vector((0.2, -0.4, -1.4)) * r * 2.4, c, r * 2.5, e * 0.08))
    return L


def camera(name, loc, target, fov_deg=None, lens=None, ortho_scale=None, up=None,
           clip_start=0.005, clip_end=200.0, sensor=36.0):
    cd = bpy.data.cameras.new(name)
    cd.sensor_fit = 'HORIZONTAL'
    cd.sensor_width = sensor
    cd.clip_start = clip_start
    cd.clip_end = clip_end
    if ortho_scale:
        cd.type = 'ORTHO'
        cd.ortho_scale = ortho_scale
    elif fov_deg:
        cd.angle = math.radians(fov_deg)
    elif lens:
        cd.lens = lens
    ob = bpy.data.objects.new(name, cd)
    bpy.context.scene.collection.objects.link(ob)
    ob.location = loc
    d = Vector(target) - Vector(loc)
    q = d.to_track_quat('-Z', 'Y')
    if up is not None:
        # roll so that camera Y aligns with the requested up
        z = -d.normalized(); upv = Vector(up)
        x = upv.cross(z).normalized(); y = z.cross(x)
        q = Matrix((x, y, z)).transposed().to_quaternion()
    ob.rotation_euler = q.to_euler()
    return ob


VIEW_DIRS = {
    # view name: (direction from subject to camera, up)
    'RIGHT': (Vector((0, -1, 0)), Vector((0, 0, 1))),   # weapon right side faces -Y
    'LEFT': (Vector((0, 1, 0)), Vector((0, 0, 1))),
    'TOP': (Vector((0, 0, 1)), Vector((1, 0, 0))),
    'BOTTOM': (Vector((0, 0, -1)), Vector((1, 0, 0))),
    'FRONT': (Vector((1, 0, 0)), Vector((0, 0, 1))),    # looking into the muzzle
    'BACK': (Vector((-1, 0, 0)), Vector((0, 0, 1))),
}


def camera_ortho(name, view, bmin, bmax, aspect=16 / 9, margin=1.08):
    """Orthographic camera framing the world bbox from a canonical view.
    RIGHT = weapon right side (camera on -Y, muzzle to image right); LEFT = camera on +Y;
    TOP = looking down, muzzle right; FRONT = looking into the muzzle."""
    d, up = VIEW_DIRS[view]
    c = (Vector(bmin) + Vector(bmax)) * 0.5
    ext = Vector(bmax) - Vector(bmin)
    if view in ('RIGHT', 'LEFT'):
        w, h = ext.x, ext.z
    elif view in ('TOP', 'BOTTOM'):
        w, h = ext.x, ext.y
        up = Vector((0, 1, 0)) if view == 'TOP' else Vector((0, -1, 0))
    else:
        w, h = ext.y, ext.z
    scale = max(w, h * aspect) * margin
    dist = ext.length * 2 + 1.0
    return camera(name, c + d * dist, c, ortho_scale=scale, up=up, clip_end=dist * 4)


def render(path, cam, res=(1600, 900), samples=128, transparent=False, exposure=0.0,
           denoise=True):
    sc = bpy.context.scene
    sc.camera = cam
    sc.render.resolution_x, sc.render.resolution_y = res
    sc.render.resolution_percentage = 100
    sc.cycles.samples = samples
    sc.cycles.use_adaptive_sampling = True
    sc.cycles.use_denoising = denoise
    sc.render.film_transparent = transparent
    sc.view_settings.exposure = exposure
    sc.render.image_settings.file_format = 'PNG'
    sc.render.image_settings.color_mode = 'RGBA' if transparent else 'RGB'
    sc.render.filepath = path
    os.makedirs(os.path.dirname(path), exist_ok=True)
    t0 = time.time()
    bpy.ops.render.render(write_still=True)
    log(f"render {os.path.basename(path)} {res[0]}x{res[1]} s{samples} {time.time() - t0:.1f}s")
    return path


def clay_override(enable=True):
    vl = bpy.context.view_layer
    vl.material_override = mat_clay() if enable else None


def contact_sheet(items, out_path, thumb=512, cols=4, title=None):
    """items = [(path, label), ...] -> labelled grid PNG."""
    from PIL import Image, ImageDraw
    rows = (len(items) + cols - 1) // cols
    pad = 8; lab = 22; top = 30 if title else 0
    W = cols * (thumb + pad) + pad
    H = top + rows * (thumb + lab + pad) + pad
    sheet = Image.new('RGB', (W, H), (40, 40, 42))
    dr = ImageDraw.Draw(sheet)
    if title:
        dr.text((pad, 8), title, fill=(230, 230, 230))
    for i, (p, label) in enumerate(items):
        r, c = divmod(i, cols)
        x = pad + c * (thumb + pad); y = top + pad + r * (thumb + lab + pad)
        im = Image.open(p).convert('RGB').resize((thumb, thumb), Image.LANCZOS)
        sheet.paste(im, (x, y + lab))
        dr.text((x + 2, y + 4), label, fill=(235, 235, 235))
    sheet.save(out_path)
    return out_path


def side_by_side(paths, out_path, labels=None, bg=(40, 40, 42)):
    from PIL import Image, ImageDraw
    ims = [Image.open(p).convert('RGB') for p in paths]
    W = sum(i.width for i in ims); H = max(i.height for i in ims) + 26
    sheet = Image.new('RGB', (W, H), bg)
    dr = ImageDraw.Draw(sheet)
    x = 0
    for i, im in enumerate(ims):
        sheet.paste(im, (x, 26))
        if labels:
            dr.text((x + 6, 6), labels[i], fill=(235, 235, 235))
        x += im.width
    sheet.save(out_path)
    return out_path


# =============================================================================
# 10. Export and re-import (clean subprocess jobs)
# =============================================================================
#
# FBX for Unreal -- options and why:
#   axis_forward='-Z', axis_up='Y'   Blender defaults (Maya-style Y-up file).  Unreal's FBX
#                                    importer ("Convert Scene", on by default) converts to
#                                    Z-up and then mirrors Y for its left-handed frame, so
#                                    Blender (x, y, z) arrives as Unreal (x, -y, z).  Weapons
#                                    built muzzle +X / right side -Y therefore arrive muzzle
#                                    +X (UE forward) with the right side on UE +Y (UE right).
#   geometry pre-scaled x100, scene unit scale 0.01, apply_unit_scale=True,
#   apply_scale_options='FBX_SCALE_NONE', global_scale=1.0
#                                    -> file UnitScaleFactor = 1 (centimetres) and NO scale on
#                                    any node.  Unreal needs no "Convert Scene Unit" and the
#                                    skeleton root carries scale 1.0 (the classic Blender
#                                    100x root-bone scale problem is avoided).  The source
#                                    .blend stays in metres; scaling happens only inside the
#                                    export subprocess.
#   mesh_smooth_type='FACE'          writes smoothing groups (UE warns without them); the
#                                    exact custom split normals are written as well -> import
#                                    with "Import Normals" (or Normals and Tangents).
#   use_tspace=True                  MikkTSpace tangents/binormals from the triangulated
#                                    mesh that was baked (same basis as the normal maps).
#   use_triangles=True               meshes are already triangulated; guarantees no re-split.
#   add_leaf_bones=False             no "_end" bones.
#   primary_bone_axis='Y', secondary_bone_axis='X'   identity bone correction: bone matrices
#                                    are written as authored.
#   armature_nodetype='NULL'         standard; the armature object becomes the FBX root node.
#   use_armature_deform_only=False   keep non-deforming socket bones.
#   bake_anim=False                  no animation in the asset file.
#   path_mode='RELATIVE', embed_textures=False  texture paths stay relative to the FBX; the export
#                                    job also writes the RELATIVE path into FileName / Path (the
#                                    stock exporter puts an absolute machine path there) and points
#                                    the normal map at *_Normal_DX.png (Unreal's convention).
#   object_types = {'ARMATURE','MESH'} (skeletal) or {'MESH'} (static).
#
# GLB: glTF is always metres / Y-up; the exporter converts.  export_apply=False (the only
# modifier left is Armature -- applying it would bake the skin), skins on, all bones kept
# (export_def_bones=False), tangents on, images embedded (PNG).

FBX_UNREAL_OPTS = dict(
    axis_forward='-Z', axis_up='Y', apply_unit_scale=True, apply_scale_options='FBX_SCALE_NONE',
    global_scale=1.0, mesh_smooth_type='FACE', use_tspace=True, use_triangles=True,
    add_leaf_bones=False, primary_bone_axis='Y', secondary_bone_axis='X',
    armature_nodetype='NULL', use_armature_deform_only=False, bake_anim=False,
    path_mode='RELATIVE', embed_textures=False, use_mesh_modifiers=True, use_custom_props=False,
    use_metadata=True, colors_type='NONE', use_mesh_edges=False, use_subsurf=False)

GLB_OPTS = dict(
    export_format='GLB', export_yup=True, export_apply=False, export_texcoords=True,
    export_normals=True, export_tangents=True, export_materials='EXPORT',
    export_image_format='AUTO', export_skins=True, export_def_bones=False,
    export_animations=False, export_leaf_bone=False, export_rest_position_armature=True,
    export_cameras=False, export_lights=False, export_extras=False)


def run_job(job, timeout=900):
    """Run a job dict in a fresh python3 + bpy process; returns the job's JSON result."""
    fd, path = tempfile.mkstemp(suffix=".json", prefix="ivjob_")
    with os.fdopen(fd, "w") as f:
        json.dump(job, f)
    cmd = [sys.executable, os.path.abspath(__file__), "--job", path]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    os.remove(path)
    res = None
    for line in p.stdout.splitlines()[::-1]:
        if line.startswith("IVJOB_RESULT "):
            res = json.loads(line[len("IVJOB_RESULT "):])
            break
    if res is None:
        raise RuntimeError(f"job failed ({job.get('type')}):\n{p.stdout[-3000:]}\n{p.stderr[-3000:]}")
    return res


def _job_export(job):
    bpy.ops.wm.open_mainfile(filepath=job["blend"])
    names = job["objects"]
    objs = [bpy.data.objects[n] for n in names]
    # make everything visible / selectable for export
    for o in objs:
        o.hide_set(False); o.hide_viewport = False; o.hide_select = False
        for c in o.users_collection:
            c.hide_viewport = False
    lc = bpy.context.view_layer.layer_collection

    def _unexclude(l):
        l.exclude = False
        l.hide_viewport = False
        for ch in l.children:
            _unexclude(ch)
    _unexclude(lc)
    select(objs, objs[0])
    fmt = job["format"]
    os.makedirs(os.path.dirname(job["path"]), exist_ok=True)
    if fmt == "FBX":
        if job.get("bake_cm", True):
            sc = bpy.context.scene
            sc.unit_settings.scale_length = 0.01
            roots = [o for o in objs if o.parent is None or o.parent not in objs]
            for r in roots:
                r.matrix_world = Matrix.Scale(100.0, 4) @ r.matrix_world
            bpy.context.view_layer.update()
            select(objs, roots[0])
            bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
            # static roots: keep object origin; locations were scaled with the matrix
        if job.get("normal_dx", True):
            # Unreal reads tangent-space normals DirectX-style (-Y): reference the _Normal_DX map
            for m in bpy.data.materials:
                if not (m.get("iv_export") and m.use_nodes):
                    continue
                n = m.node_tree.nodes.get("T_Normal")
                if n and n.image and n.image.filepath:
                    p = bpy.path.abspath(n.image.filepath)
                    dx = p.replace("_Normal.png", "_Normal_DX.png")
                    if dx != p and os.path.exists(dx):
                        im = bpy.data.images.load(dx, check_existing=True)
                        im.colorspace_settings.name = 'Non-Color'
                        n.image = im
        if job.get("relative_paths_only", True):
            # the stock exporter writes an absolute FileName / Path next to RelativeFilename; keep
            # only the path relative to the FBX so no machine path is embedded
            import io_scene_fbx.export_fbx_bin as _efb
            _orig = _efb._gen_vid_path

            def _rel_only(img, scene_data):
                a, r = _orig(img, scene_data)
                return r, r
            _efb._gen_vid_path = _rel_only
        opts = dict(FBX_UNREAL_OPTS)
        opts["object_types"] = set(job.get("object_types", ["ARMATURE", "MESH"]))
        bpy.ops.export_scene.fbx(filepath=job["path"], use_selection=True, **opts)
    else:
        opts = dict(GLB_OPTS)
        if job["path"].lower().endswith(".gltf"):
            # .gltf + .bin with external images in a shared folder (several files reference the
            # same texture files instead of each embedding its own copy)
            opts["export_format"] = 'GLTF_SEPARATE'
            opts["export_texture_dir"] = job.get("texture_dir", "textures")
        bpy.ops.export_scene.gltf(filepath=job["path"], use_selection=True, **opts)
    return {"ok": True, "path": job["path"], "bytes": os.path.getsize(job["path"])}


def _job_reimport(job):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    path = job["path"]
    if path.lower().endswith(".fbx"):
        bpy.ops.import_scene.fbx(filepath=path, use_custom_normals=True, ignore_leaf_bones=False,
                                 automatic_bone_orientation=False)
    else:
        bpy.ops.import_scene.gltf(filepath=path)
    bpy.context.view_layer.update()
    objs = list(bpy.context.scene.objects)
    arms = [o for o in objs if o.type == 'ARMATURE']
    # the glTF importer adds bone display shapes (e.g. "Icosphere"); they are not file content
    shapes = set()
    for a in arms:
        for pb in a.pose.bones:
            if pb.custom_shape:
                shapes.add(pb.custom_shape.name)
    objs = [o for o in objs if o.name not in shapes]
    meshes = [o for o in objs if o.type == 'MESH']
    dg = bpy.context.evaluated_depsgraph_get()
    mn = np.array([1e9] * 3); mx = np.array([-1e9] * 3)
    tris = 0
    for o in meshes:
        ev = o.evaluated_get(dg)
        me = ev.to_mesh()
        me.calc_loop_triangles()
        tris += len(me.loop_triangles)
        co = np.empty(len(me.vertices) * 3); me.vertices.foreach_get("co", co)
        co = co.reshape(-1, 3)
        M = np.array(o.matrix_world)
        w = co @ M[:3, :3].T + M[:3, 3]
        if len(w):
            mn = np.minimum(mn, w.min(0)); mx = np.maximum(mx, w.max(0))
        ev.to_mesh_clear()
    mats = {}
    for o in meshes:
        for m in o.data.materials:
            if not m or m.name in mats:
                continue
            ims = []
            if m.use_nodes:
                for n in m.node_tree.nodes:
                    if n.type == 'TEX_IMAGE' and n.image:
                        im = n.image
                        p = bpy.path.abspath(im.filepath) if im.filepath else ""
                        ims.append({"name": im.name, "path": p,
                                    "packed": bool(im.packed_file),
                                    "size": list(im.size),
                                    "exists_or_packed": bool(im.packed_file) or (bool(p) and os.path.exists(p))})
            mats[m.name] = ims
    bones = []
    root_scale = None
    for a in arms:
        bones += [b.name for b in a.data.bones]
        root_scale = [round(v, 4) for v in a.matrix_world.to_scale()]
    groups_ok = True
    for o in meshes:
        am = [mo for mo in o.modifiers if mo.type == 'ARMATURE']
        if arms and o.vertex_groups:
            bn = set(bones)
            if any(vg.name not in bn for vg in o.vertex_groups):
                groups_ok = False
    return {"ok": True, "path": path, "objects": len(objs), "mesh_objects": len(meshes),
            "mesh_names": sorted(o.name for o in meshes),
            "armatures": [a.name for a in arms], "bone_count": len(bones), "bones": sorted(bones),
            "armature_object_scale": root_scale,
            "tris": tris, "bbox_min_m": [round(float(v), 4) for v in mn],
            "bbox_max_m": [round(float(v), 4) for v in mx],
            "dimensions_cm": [round(float(mx[i] - mn[i]) * 100, 2) for i in range(3)],
            "materials": mats, "vertex_groups_match_bones": groups_ok}


def export_fbx(blend, objects, path, object_types=("ARMATURE", "MESH"), bake_cm=True):
    return run_job({"type": "export", "format": "FBX", "blend": blend, "objects": list(objects),
                    "path": path, "object_types": list(object_types), "bake_cm": bake_cm})


def export_glb(blend, objects, path, texture_dir="textures"):
    """GLB (self-contained) for *.glb paths; for *.gltf paths a .gltf + .bin whose images are
    written to (and shared through) `texture_dir`, relative to the .gltf."""
    return run_job({"type": "export", "format": "GLB", "blend": blend, "objects": list(objects),
                    "path": path, "texture_dir": texture_dir})


def reimport_check(path):
    return run_job({"type": "reimport", "path": path})


def _job_main(path):
    with open(path) as f:
        job = json.load(f)
    t = job["type"]
    if t == "export":
        res = _job_export(job)
    elif t == "reimport":
        res = _job_reimport(job)
    else:
        raise ValueError(t)
    print("IVJOB_RESULT " + json.dumps(res), flush=True)


if __name__ == "__main__":
    if "--job" in sys.argv:
        _job_main(sys.argv[sys.argv.index("--job") + 1])
