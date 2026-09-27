"""
soldier_gear.py -- geometry of the soldier's gear, conformed to the garments built by soldier.py.
Every piece is a CLOSED mesh.  Rigid pieces are later bound 100 % to one bone; fabric bands
(cummerbund, shoulder straps, belt, knee straps) take the weights of the garment under them,
restricted to the bones listed in soldier.py (smooth blend only where fabric meets the body).

All coordinates: metres, rest A-pose, the character faces -Y, left = +X.
"""

import math

import bmesh
import bpy
import numpy as np
from mathutils import Vector, Matrix

import ivsoldier as S


# =============================================================================
# generic builders
# =============================================================================

def ray_hit(bv, origin, direction, maxd=2.0):
    d = Vector(tuple(map(float, direction))).normalized()
    loc, nor, fi, dist = bv.ray_cast(Vector(tuple(map(float, origin))), d, maxd)
    if loc is None:
        return None, None
    return np.array(loc), np.array(nor)


def surface_grid(bv, origins, dirs, back=0.25):
    """Cast rays towards a garment from OUTSIDE (origin - dir * back, along +dir) and return the
    first hits: P (nu, nv, 3), N (outward normals)."""
    nu, nv = origins.shape[:2]
    P = np.zeros((nu, nv, 3)); N = np.zeros((nu, nv, 3))
    for i in range(nu):
        for j in range(nv):
            o = origins[i, j] - dirs[i, j] * back
            loc, nor = ray_hit(bv, o, dirs[i, j], max(back * 2.5, 1.0))
            if loc is None:
                # missed (edge of the garment): nearest surface point to the ray's closest approach
                r = bv.find_nearest(Vector(tuple(map(float, origins[i, j] + dirs[i, j] * 0.3))), 1.0)
                loc, nor = np.array(r[0]), np.array(r[1])
            if np.dot(nor, dirs[i, j]) > 0:
                nor = -nor
            P[i, j] = loc; N[i, j] = nor
    return P, N


def smooth_grid(A, iters=2, closed_u=False):
    A = A.copy()
    for _ in range(iters):
        B = A.copy()
        if closed_u:
            B = 0.5 * A + 0.25 * (np.roll(A, 1, 0) + np.roll(A, -1, 0))
        else:
            B[1:-1] = 0.5 * A[1:-1] + 0.25 * (A[:-2] + A[2:])
        C_ = B.copy()
        C_[:, 1:-1] = 0.5 * B[:, 1:-1] + 0.25 * (B[:, :-2] + B[:, 2:])
        A = C_
    return A


def slab_from_grid(P, N, clear, thick, closed_u=False, round_edge=0.35):
    """Closed solid on a surface grid: inner sheet at `clear`, outer at clear + thick (thick may
    be an (nu, nv) array).  The outer sheet's two long edges are pulled in by round_edge * thick
    so the band has a rounded (not boxy) edge.  Returns (V, F)."""
    nu, nv = P.shape[:2]
    T = np.broadcast_to(np.asarray(thick, float), (nu, nv))
    inner = P + N * clear
    outer = P + N * (clear + T)[..., None]
    if round_edge > 0 and nv >= 3:
        # pull the outer edge rows towards the band centre across v
        for j in (0, nv - 1):
            jn = 1 if j == 0 else nv - 2
            outer[:, j] = outer[:, j] + (outer[:, jn] - outer[:, j]) * 0.0 - N[:, j] * (T[:, j] * round_edge)[:, None]
    V = np.concatenate([outer.reshape(-1, 3), inner.reshape(-1, 3)])
    off = nu * nv

    def o(i, j):
        return (i % nu) * nv + j

    F = []
    iu = range(nu) if closed_u else range(nu - 1)
    for i in iu:
        for j in range(nv - 1):
            F.append([o(i, j), o(i + 1, j), o(i + 1, j + 1), o(i, j + 1)])
            F.append([off + o(i, j + 1), off + o(i + 1, j + 1), off + o(i + 1, j), off + o(i, j)])
        # long side walls (v = 0 and v = nv-1)
        F.append([off + o(i, 0), off + o(i + 1, 0), o(i + 1, 0), o(i, 0)])
        F.append([o(i, nv - 1), o(i + 1, nv - 1), off + o(i + 1, nv - 1), off + o(i, nv - 1)])
    if not closed_u:
        for i in (0, nu - 1):
            ring = [o(i, j) for j in range(nv)] + [off + o(i, j) for j in range(nv)][::-1]
            F.append(ring if i == nu - 1 else ring[::-1])
    return V, S.orient_outward(V, F)


def bent_box(w, h, t, R, bevel=0.006, nx=10, nz=6, cut_top=0.0, cut_depth=0.0, taper=0.0):
    """Curved slab (plate / plate bag), in a local frame: x across, z up, y = thickness towards the
    body (outer face at y = 0, inner at y = t), bent about a vertical axis at y = +R (concave
    towards the body).  cut_top: shooter's-cut width removed at the top corners (per side) over the
    top cut_depth.  taper: inner face narrower by this fraction (pillow edge).  Returns (V, F)."""
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        v.co = Vector((v.co.x * w, v.co.y * t + t / 2, v.co.z * h))
    if bevel > 0:
        bmesh.ops.bevel(bm, geom=list(bm.edges), offset=min(bevel, 0.45 * t), segments=2, profile=0.6,
                        affect='EDGES', clamp_overlap=True)
    # subdivide for bending
    for _ in range(3):
        long_e = [e for e in bm.edges if abs(e.verts[0].co.x - e.verts[1].co.x) > w / nx * 1.2]
        if not long_e:
            break
        bmesh.ops.subdivide_edges(bm, edges=long_e, cuts=1, use_grid_fill=True)
    for _ in range(2):
        long_e = [e for e in bm.edges if abs(e.verts[0].co.z - e.verts[1].co.z) > h / nz * 1.2]
        if not long_e:
            break
        bmesh.ops.subdivide_edges(bm, edges=long_e, cuts=1, use_grid_fill=True)
    bmesh.ops.triangulate(bm, faces=[f for f in bm.faces if len(f.verts) > 4])
    for v in bm.verts:
        x, y, z = v.co
        if cut_top > 0 and cut_depth > 0:
            zz = (z - (h / 2 - cut_depth)) / cut_depth
            if zz > 0:
                k = 1.0 - cut_top / (w / 2) * min(zz, 1.0)
                x = x * k
        if taper > 0:
            f = 1.0 - taper * (y / t)
            x *= f
            z *= (1.0 - taper * 0.5 * (y / t))
        if R > 0:
            phi = x / R
            r = R - y
            x, y = r * math.sin(phi), R - r * math.cos(phi)
        v.co = Vector((x, y, z))
    V = np.array([v.co[:] for v in bm.verts])
    F = [[v.index for v in f.verts] for f in bm.faces]
    bm.free()
    return V, F


def frame_matrix(origin, ex, ey, ez):
    M = np.eye(4)
    M[:3, 0], M[:3, 1], M[:3, 2], M[:3, 3] = ex, ey, ez, origin
    return M


def xf(V, M):
    return V @ M[:3, :3].T + M[:3, 3]


def rbox(sx, sy, sz, r, segs=2):
    bm = S.rounded_box_bm(sx, sy, sz, r, segs)
    V = np.array([v.co[:] for v in bm.verts])
    F = [[v.index for v in f.verts] for f in bm.faces]
    bm.free()
    return V, F


def lathe_closed(profile, n=16, axis_frame=None):
    """Closed solid of revolution: profile = [(r, z), ...] from bottom to top (r > 0 except the
    poles may be 0).  Local axis = +Z.  Returns (V, F)."""
    rings, poles = [], []
    t = np.linspace(0, 2 * np.pi, n, endpoint=False)
    for r, z in profile:
        rings.append(np.stack([r * np.cos(t), r * np.sin(t), np.full(n, z)], 1))
    V, F = S.loft_closed(rings, cap=True)
    return V, S.orient_outward(V, F)


def merge_parts(parts):
    V, F, off = [], [], 0
    for v, f in parts:
        V.append(v)
        F += [[i + off for i in ff] for ff in f]
        off += len(v)
    return np.concatenate(V), F


def superellipsoid_dome(c, ax, ay_f, ay_b, az, rim_fn, n_az=40, n_el=11, p=2.25, el_top=88.0):
    """Upper superellipsoid surface sampled on (azimuth, elevation) down to the rim elevation
    rim_fn(az_deg) (world z).  az = 0 at the front (-Y), 90 = left (+X).  Returns rows of points
    (n_el, n_az, 3) from the rim (row 0) to near the top, plus the pole point."""
    azs = np.linspace(0, 360, n_az, endpoint=False)
    rows = []
    for k in range(n_el):
        row = []
        for a in azs:
            ar = math.radians(a)
            ca, sa = math.cos(ar), math.sin(ar)
            ay = ay_f if ca > 0 else ay_b
            zr = rim_fn(a)
            q = max(-0.99, min(0.99, (zr - c[2]) / az))
            e0 = math.asin(math.copysign(abs(q) ** (p / 2.0), q))       # z(e0) == rim exactly
            e1 = math.radians(el_top)
            e = e0 + (e1 - e0) * (k / (n_el - 1)) ** 1.15
            ce, se = math.cos(e), math.sin(e)
            fx = np.sign(sa) * abs(sa) ** (2 / p)
            fy = np.sign(ca) * abs(ca) ** (2 / p)
            fe = abs(ce) ** (2 / p)
            x = c[0] + ax * fe * fx
            y = c[1] - ay * fe * fy
            z = c[2] + az * np.sign(se) * abs(se) ** (2 / p)
            row.append((x, y, z))
        rows.append(np.array(row))
    pole = np.array([c[0], c[1] + (ay_b - ay_f) * 0.0, c[2] + az])
    return np.array(rows), pole


def dome_shell(rows, pole, thick, inner_scale_fn=None):
    """Closed helmet-like shell from dome rows: outer surface, a rolled rim, inner surface offset
    by `thick` towards the centre.  Returns (V, F, info) with vertex range tags."""
    n_el, n_az = rows.shape[:2]
    cen = rows.reshape(-1, 3).mean(0)
    cen[2] = rows[0, :, 2].mean()
    outer = rows

    def inward(P):
        d = cen - P
        return d / np.linalg.norm(d, axis=-1, keepdims=True)
    inner = rows + inward(rows) * thick
    pole_in = pole + (cen - pole) / np.linalg.norm(cen - pole) * thick
    V = np.concatenate([outer.reshape(-1, 3), [pole], inner.reshape(-1, 3), [pole_in]])
    no = n_el * n_az
    ip = no
    ib = no + 1
    ipi = ib + no
    F = []

    def O(k, i):
        return k * n_az + (i % n_az)

    def I(k, i):
        return ib + k * n_az + (i % n_az)
    for k in range(n_el - 1):
        for i in range(n_az):
            F.append([O(k, i), O(k, i + 1), O(k + 1, i + 1), O(k + 1, i)])
            F.append([I(k + 1, i), I(k + 1, i + 1), I(k, i + 1), I(k, i)])
    for i in range(n_az):
        F.append([O(n_el - 1, i), O(n_el - 1, i + 1), ip])
        F.append([ipi, I(n_el - 1, i + 1), I(n_el - 1, i)])
        # rim
        F.append([I(0, i), I(0, i + 1), O(0, i + 1), O(0, i)])
    F = S.orient_outward(V, F)
    return V, F, {"outer": (0, no + 1), "inner": (ib, ipi + 1)}


# =============================================================================
# the parts
# =============================================================================

class Built:
    """Collects the parts: name -> dict(V, F, bind=('rigid', bone) | ('fabric', garment, bones),
    atlas='gear'|'cloth'|'team', mat zone tag)."""

    def __init__(self):
        self.parts = {}

    def add(self, name, V, F, bind, atlas="gear", zone="fabric", **kw):
        self.parts[name] = dict(V=np.asarray(V, float), F=F, bind=bind, atlas=atlas, zone=zone, **kw)
