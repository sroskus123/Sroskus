"""
ivwebgeo.py -- geometry primitives for the web export of the level (Tools/level/export_web_level.py).

A `Scene` collects render triangles per material (MeshBuf) and collision triangles per collision class (ColBuf).
Every primitive is authored once and can emit both: render faces (with per-face material keys, e.g. interior vs
exterior finish of a wall) and the collision solid (class = which rays / capsules it stops, surface = footstep /
impact sound).  Level frame: metres, +X east, +Y north, +Z up.

Collision classes (Web/src/level/levelAssets.js maps them to BVH groups):
  main     stops the capsule, bullets and vision (walls, terrain, floors, roofs, solid props)
  move     stops only the capsule (window glass, chain-link / picket / pipe-rail fences, hard boundary)
  movevis  stops the capsule and vision, bullets pass (hedges, shrubs, soft furniture, timber crates, plank walls)
"""
import math

import numpy as np

from ivglb import ColBuf, MeshBuf


def rot2(deg):
    a = math.radians(deg)
    return math.cos(a), math.sin(a)


def xf(c, rot, p):
    ca, sa = rot2(rot)
    return (c[0] + p[0] * ca - p[1] * sa, c[1] + p[0] * sa + p[1] * ca)


class Scene:
    def __init__(self, mats):
        self.mats = mats            # key -> material dict (tile, ...)
        self.render = {}            # key -> MeshBuf
        self.col = {}               # (cls, surface, nav) -> ColBuf
        self.color = (1, 1, 1, 1)   # current vertex tint
        self.stats = {"boxes": 0, "prisms": 0}

    # ------------------------------------------------------------------ buffers
    def mb(self, key):
        if key not in self.render:
            m = self.mats.get(key)
            if m is None:
                raise KeyError(f"unknown material {key}")
            self.render[key] = MeshBuf(key, tile=m.get("tile", 1.0))
        return self.render[key]

    def cb(self, cls, surface, nav=True):
        k = (cls, surface, bool(nav))
        if k not in self.col:
            self.col[k] = ColBuf(f"{cls}|{surface}|{int(bool(nav))}")
        return self.col[k]

    # ------------------------------------------------------------------ faces
    def face(self, key, pts, color=None, sub=None):
        """render-only planar polygon (CCW seen from outside). sub = max edge for grid subdivision (quads only)."""
        if key is None:
            return
        m = self.mb(key)
        c = color if color is not None else self.color
        if sub and len(pts) == 4:
            m.quad_grid(pts[0], pts[1], pts[2], pts[3], sub, c)
        else:
            m.poly(pts, c)

    # ------------------------------------------------------------------ prisms
    def prism(self, poly, z0, z1, mat=None, cls="main", surface="concrete", nav=True, top=None, bottom=None,
              side=None, sub=None, color=None, render=True, collide=True, top_z=None):
        """vertical prism over a convex (or star-shaped from vertex 0) polygon.  mat: default render material;
        top / bottom / side override it (None = default, False = skip that face).  top_z: optional per-vertex top
        heights (sloped top)."""
        P = [tuple(p[:2]) for p in poly]
        # CCW
        area = 0.0
        for i in range(len(P)):
            x0, y0 = P[i]
            x1, y1 = P[(i + 1) % len(P)]
            area += x0 * y1 - x1 * y0
        if area < 0:
            P = P[::-1]
            if top_z is not None:
                top_z = list(top_z)[::-1]
        n = len(P)
        tz = [z1] * n if top_z is None else list(top_z)
        if z1 - z0 <= 1e-6 and top_z is None:
            return
        self.stats["prisms"] += 1
        if render and mat is not False:
            tk = mat if top is None else top
            bk = mat if bottom is None else bottom
            sk = mat if side is None else side
            if tk:
                self.face(tk, [(x, y, tz[i]) for i, (x, y) in enumerate(P)], color, sub if n == 4 else None)
            if bk:
                self.face(bk, [(x, y, z0) for (x, y) in P[::-1]], color, sub if n == 4 else None)
            if sk:
                for i in range(n):
                    a, b = P[i], P[(i + 1) % n]
                    if math.hypot(b[0] - a[0], b[1] - a[1]) < 1e-6:
                        continue
                    key = sk(i, a, b) if callable(sk) else sk
                    if key:
                        self.face(key, [(a[0], a[1], z0), (b[0], b[1], z0), (b[0], b[1], tz[(i + 1) % n]), (a[0], a[1], tz[i])], color, sub)
        if collide and cls:
            c = self.cb(cls, surface, nav)
            V = [(x, y, z0) for (x, y) in P] + [(x, y, tz[i]) for i, (x, y) in enumerate(P)]
            I = []
            for k in range(1, n - 1):
                I.append((n, n + k, n + k + 1))
                I.append((0, k + 1, k))
            for k in range(n):
                k2 = (k + 1) % n
                I.append((k, k2, n + k2))
                I.append((k, n + k2, n + k))
            c.add(V, I)

    def obox(self, cx, cy, lx, ly, rot, z0, z1, **kw):
        """oriented box: centre (cx, cy), size lx (along rot) x ly, rotation deg CCW."""
        ca, sa = rot2(rot)
        hx, hy = lx / 2, ly / 2
        pts = [(cx + px * ca - py * sa, cy + px * sa + py * ca) for px, py in ((-hx, -hy), (hx, -hy), (hx, hy), (-hx, hy))]
        self.stats["boxes"] += 1
        self.prism(pts, z0, z1, **kw)

    def seg_box(self, a, b, thick, z0, z1, extend=0.0, **kw):
        """box along the segment a->b (centre line), `thick` wide."""
        dx, dy = b[0] - a[0], b[1] - a[1]
        L = math.hypot(dx, dy)
        if L < 1e-6:
            return
        self.obox((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, L + 2 * extend, thick, math.degrees(math.atan2(dy, dx)), z0, z1, **kw)

    def seg_wall(self, a, b, thick, za0, zb0, za1, zb1, **kw):
        """wall piece along a->b with independent bottom / top heights at both ends (follows sloped ground)."""
        dx, dy = b[0] - a[0], b[1] - a[1]
        L = math.hypot(dx, dy)
        if L < 1e-6:
            return
        nx, ny = -dy / L * thick / 2, dx / L * thick / 2
        poly = [(a[0] - nx, a[1] - ny), (b[0] - nx, b[1] - ny), (b[0] + nx, b[1] + ny), (a[0] + nx, a[1] + ny)]
        z0 = min(za0, zb0)
        self.prism(poly, z0, max(za1, zb1), top_z=[za1, zb1, zb1, za1], **kw)

    def cylinder(self, cx, cy, r, z0, z1, mat, segs=8, cls="main", surface="wood", render=True, collide=True, color=None, rtop=None):
        rt = r if rtop is None else rtop
        pts0 = [(cx + r * math.cos(2 * math.pi * k / segs), cy + r * math.sin(2 * math.pi * k / segs)) for k in range(segs)]
        pts1 = [(cx + rt * math.cos(2 * math.pi * k / segs), cy + rt * math.sin(2 * math.pi * k / segs)) for k in range(segs)]
        if render and mat:
            m = self.mb(mat)
            c = color if color is not None else self.color
            for k in range(segs):
                a0, b0 = pts0[k], pts0[(k + 1) % segs]
                a1, b1 = pts1[k], pts1[(k + 1) % segs]
                m.poly([(a0[0], a0[1], z0), (b0[0], b0[1], z0), (b1[0], b1[1], z1), (a1[0], a1[1], z1)], c)
            m.poly([(x, y, z1) for x, y in pts1], c)
        if collide and cls:
            self.prism(pts0, z0, z1, mat=False, cls=cls, surface=surface, render=False)

    def sloped_slab(self, corners, thick, mat=None, bottom=None, side=None, cls="main", surface="concrete", nav=True,
                    sub=None, color=None, render=True, collide=True):
        """slab under a planar (possibly sloped) quad `corners` [(x, y, z) x 4, CCW from above], `thick` below it."""
        A = [np.array(c, float) for c in corners]
        B = [a - np.array([0, 0, thick]) for a in A]
        area = 0.0
        for i in range(4):
            area += A[i][0] * A[(i + 1) % 4][1] - A[(i + 1) % 4][0] * A[i][1]
        if area < 0:
            A = A[::-1]
            B = B[::-1]
        if render and mat is not False:
            if mat:
                self.face(mat, A, color, sub)
            bk = mat if bottom is None else bottom
            if bk:
                self.face(bk, B[::-1], color, sub)
            sk = mat if side is None else side
            if sk:
                for i in range(4):
                    j = (i + 1) % 4
                    self.face(sk, [B[i], B[j], A[j], A[i]], color)
        if collide and cls:
            c = self.cb(cls, surface, nav)
            V = [tuple(b) for b in B] + [tuple(a) for a in A]
            I = [(4, 5, 6), (4, 6, 7), (0, 2, 1), (0, 3, 2)]
            for k in range(4):
                k2 = (k + 1) % 4
                I.append((k, k2, 4 + k2))
                I.append((k, 4 + k2, 4 + k))
            c.add(V, I)

    def col_poly(self, cls, surface, pts, nav=True):
        self.cb(cls, surface, nav).poly(pts)

    def quad_col_wall(self, cls, surface, a, b, z0a, z0b, z1a, z1b, nav=True):
        """one vertical collision quad (both sides are hit by rays; the controller treats it as a thin wall)."""
        c = self.cb(cls, surface, nav)
        c.add([(a[0], a[1], z0a), (b[0], b[1], z0b), (b[0], b[1], z1b), (a[0], a[1], z1a)], [(0, 1, 2), (0, 2, 3)])
