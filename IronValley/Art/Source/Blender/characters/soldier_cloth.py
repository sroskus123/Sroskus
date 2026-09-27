"""
soldier_cloth.py -- loose combat clothing for SK_Soldier (Iron Valley).

The garments are still derived from SK_Human_Base faces (so every garment vertex carries the body's
weights and corrective shapes), but their SHAPE is designed, not a skin offset:

* athletic_warp: thicker upper arms / forearms and rounder shoulders on the body proxy (and the
  glove cuffs), radial about the arm bones; hands and finger joints are untouched.
* subdivide: linear midpoint subdivision with a sparse interpolation matrix (weights, shape-key
  deltas follow), so big folds can exist in the silhouette.
* LimbShell: per limb (arm chain / leg chain) the body's cross-sections are replaced by their
  convex hull, then by a parabolic upper envelope along the limb (fabric bridges the biceps /
  forearm / calf bulges instead of following them), plus an ease field that sags towards gravity
  (sleeves) or hangs loose (trouser legs).
* fold functions: compression folds (sharp valleys, round crests) at the elbow, the cuff, the knee,
  above the boots, drape folds on the upper arm and the thigh, gathers at the waist.

Deterministic: no randomness except fixed-seed value noise.
Conventions: metres, Z up, character faces -Y, left = +X, rest = A-pose.
"""

import math

import numpy as np
import bpy
import bmesh
from mathutils import Vector

import ivsoldier as S
import ivchar as C

# =============================================================================
# small math helpers
# =============================================================================


def smoothstep(e0, e1, x):
    t = np.clip((np.asarray(x, float) - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def bump(x, c, w):
    """Smooth bump 1 at c, 0 at |x - c| >= w."""
    t = np.clip(1.0 - np.abs((np.asarray(x, float) - c) / w), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def fold_profile(x):
    """Compression fold: round crests (+1) at x = 0 mod 2pi, sharp valleys (-1) at pi."""
    return 2.0 * np.abs(np.cos(0.5 * x)) - 1.0


def buckle(x, phi, seed, wander=2.2, fade=0.75, amp_var=0.45):
    """Irregular compression folds: ring folds (phase x) whose phase wanders round the limb (phi),
    whose amplitude varies from fold to fold and which fade in / out round the limb (partial
    rings, not an accordion)."""
    xw = x + wander * vnoise1(phi * 1.2 + seed * 0.37, seed) + 0.8 * np.sin(2.0 * phi + seed)
    a = (1.0 - 0.5 * amp_var) + 0.5 * amp_var * vnoise1(xw / (2 * np.pi) * 1.3 + 7.1, seed + 101)
    f = np.clip(0.75 + 0.5 * fade * vnoise1(phi * 1.5 + xw / (2 * np.pi) * 0.6, seed + 202), 0.3, 1.0)
    # fabric bunches outwards: crests +1, valleys -0.35
    return a * f * (0.675 * fold_profile(xw) + 0.325)


def vnoise1(x, seed=0):
    """1D value noise, smooth, in [-1, 1]."""
    x = np.asarray(x, float)
    i = np.floor(x).astype(np.int64)
    f = x - i

    def h(k):
        k = (k * 374761393 + seed * 668265263) & 0xFFFFFFFF
        k = ((k ^ (k >> 13)) * 1274126177) & 0xFFFFFFFF
        return ((k & 0xFFFF) / 32767.5) - 1.0
    u = f * f * (3 - 2 * f)
    return h(i) * (1 - u) + h(i + 1) * u


def bone_pts(arm, name):
    b = arm.data.bones[name]
    return np.array(b.head_local, float), np.array(b.tail_local, float)


def sparse_lap(nb):
    """Row-normalised adjacency matrix (Laplacian smoothing operator)."""
    from scipy import sparse
    rows, cols = [], []
    for i, n in enumerate(nb):
        for j in n:
            rows.append(i)
            cols.append(j)
    n = len(nb)
    A = sparse.csr_matrix((np.ones(len(rows)), (rows, cols)), shape=(n, n))
    d = np.asarray(A.sum(1)).ravel()
    d[d == 0] = 1.0
    return sparse.diags(1.0 / d) @ A


def poly_neighbours(nv, faces):
    nb = [set() for _ in range(nv)]
    for f in faces:
        k = len(f)
        for i in range(k):
            a, b = f[i], f[(i + 1) % k]
            nb[a].add(b)
            nb[b].add(a)
    return [sorted(s) for s in nb]


def poly_boundary(nv, faces):
    from collections import Counter
    c = Counter()
    for f in faces:
        k = len(f)
        for i in range(k):
            c[tuple(sorted((f[i], f[(i + 1) % k])))] += 1
    m = np.zeros(nv, bool)
    for e, n in c.items():
        if n == 1:
            m[list(e)] = True
    return m


def poly_normals(V, faces):
    tris = np.array([t for f in faces for t in ([f[0], f[i], f[i + 1]] for i in range(1, len(f) - 1))])
    return S.vnormals(V, tris), tris


# =============================================================================
# 1. athletic build (body proxy + glove cuffs)
# =============================================================================

ATHLETIC = dict(
    # radial growth about the upper arm bone (t = 0 shoulder joint .. 1 elbow)
    upper_t=(-0.30, -0.05, 0.12, 0.30, 0.50, 0.70, 0.88, 1.00, 1.15),
    upper_f=(0.00, 0.052, 0.078, 0.076, 0.070, 0.062, 0.052, 0.046, 0.042),
    # radial growth about the forearm bone (0 elbow .. 1 wrist); 0 at the wrist (hands unchanged)
    fore_t=(-0.10, 0.00, 0.12, 0.28, 0.45, 0.62, 0.78, 0.90, 0.97, 1.00),
    fore_f=(0.042, 0.048, 0.062, 0.066, 0.058, 0.046, 0.032, 0.016, 0.004, 0.0),
    # the shoulder cap (deltoid) also moves out laterally
    deltoid_out=0.009, deltoid_t=(-0.25, 0.55),
)


def athletic_displacement(arm, P, W, names):
    """Displacement field of the athletic build for points P with weights W (columns `names`)."""
    A = ATHLETIC
    D = np.zeros_like(P)
    col = {n: i for i, n in enumerate(names)}
    for s, sg in (("l", 1.0), ("r", -1.0)):
        side = (P[:, 0] * sg) > 0.0
        if not side.any():
            continue
        sh, el = bone_pts(arm, f"upperarm_{s}")
        el2, wr = bone_pts(arm, f"lowerarm_{s}")
        wu = W[:, col[f"upperarm_{s}"]] + W[:, col[f"upperarm_twist_01_{s}"]]
        wl = W[:, col[f"lowerarm_{s}"]] + W[:, col[f"lowerarm_twist_01_{s}"]]
        du = el - sh
        tu = ((P - sh) @ du) / (du @ du)
        Au = sh + np.clip(tu, -0.3, 1.2)[:, None] * du
        fu = np.interp(tu, A["upper_t"], A["upper_f"])
        dl = wr - el2
        tl = ((P - el2) @ dl) / (dl @ dl)
        Al = el2 + np.clip(tl, -0.2, 1.1)[:, None] * dl
        fl = np.interp(tl, A["fore_t"], A["fore_f"])
        d = wu[:, None] * fu[:, None] * (P - Au) + wl[:, None] * fl[:, None] * (P - Al)
        # deltoid: the lateral half of the shoulder cap moves out along the upper arm's lateral axis
        ax = du / np.linalg.norm(du)
        lat = np.array([sg, 0.0, 0.0]) - ax * ax[0] * sg
        lat /= np.linalg.norm(lat)
        r = P - Au
        lateral = np.clip((r @ lat) / 0.05, 0.0, 1.0)
        env = bump(tu, 0.5 * (A["deltoid_t"][0] + A["deltoid_t"][1]), 0.5 * (A["deltoid_t"][1] - A["deltoid_t"][0]))
        wd = np.clip(wu + W[:, col[f"clavicle_{s}"]] * 0.6, 0, 1)
        d += (wd * env * lateral)[:, None] * lat[None, :] * A["deltoid_out"]
        D[side] = d[side]
    return D


def warp_object(ob, arm, names):
    """Apply the athletic build to a mesh object (basis + every shape key, same field)."""
    W = S.read_W(ob, names)
    me = ob.data
    co = S.co_of(ob)
    D = athletic_displacement(arm, co, W, names)
    if me.shape_keys is not None:
        kb = me.shape_keys.key_blocks
        for k in kb[1:]:
            c = np.empty(len(me.vertices) * 3)
            k.data.foreach_get("co", c)
            c = c.reshape(-1, 3)
            k.data.foreach_set("co", (c + athletic_displacement(arm, c, W, names)).ravel())
        kb[0].data.foreach_set("co", (co + D).ravel())
    me.vertices.foreach_set("co", (co + D).ravel())
    me.update()
    return float(np.linalg.norm(D, axis=1).max())


# =============================================================================
# 2. girth measurement (tape measure = convex hull perimeter of a section)
# =============================================================================

def section_girth(V, T, o, n, rad):
    from scipy.spatial import ConvexHull
    n = np.asarray(n, float) / np.linalg.norm(n)
    d = (V - o) @ n
    s = np.sign(d[T])
    m = (s.min(1) < 0) & (s.max(1) > 0)
    pts = []
    for tri in T[m]:
        for a, b in ((0, 1), (1, 2), (2, 0)):
            da, db = d[tri[a]], d[tri[b]]
            if (da < 0) != (db < 0):
                t = da / (da - db)
                pts.append(V[tri[a]] + t * (V[tri[b]] - V[tri[a]]))
    if len(pts) < 3:
        return 0.0
    P = np.array(pts)
    P = P[np.linalg.norm(P - o, axis=1) < rad]
    if len(P) < 3:
        return 0.0
    u = np.cross(n, [0, 0, 1.0])
    if np.linalg.norm(u) < 1e-3:
        u = np.cross(n, [1.0, 0, 0])
    u /= np.linalg.norm(u)
    w = np.cross(n, u)
    P2 = np.c_[(P - o) @ u, (P - o) @ w]
    h = ConvexHull(P2)
    q = P2[h.vertices]
    return float(np.linalg.norm(np.roll(q, -1, 0) - q, axis=1).sum())


def arm_girths(arm, V, T, s="l", W=None, names=None):
    """Tape-measure girths (convex hull of the section), cm: biceps = mid upper arm (mean of 45 /
    50 / 55 % of the bone, the anthropometric site), forearm = max over 10-35 % of the forearm,
    wrist at 93 %.  With W / names only the arm-dominated triangles are cut (a loose sleeve near the
    armpit must not pick up the torso)."""
    if W is not None:
        idx = [names.index(b) for b in (f"upperarm_{s}", f"upperarm_twist_01_{s}", f"lowerarm_{s}", f"lowerarm_twist_01_{s}", f"hand_{s}")]
        wa = W[:, idx].sum(1)
        T = T[(wa[T] > 0.5).all(1)]
    sh, el = bone_pts(arm, f"upperarm_{s}")
    el2, wr = bone_pts(arm, f"lowerarm_{s}")
    n1 = (el - sh)
    n2 = (wr - el2)
    up = [section_girth(V, T, sh + n1 * f, n1, 0.10) for f in (0.45, 0.50, 0.55)]
    fo = [section_girth(V, T, el2 + n2 * f, n2, 0.09) for f in np.linspace(0.10, 0.35, 6)]
    wrst = section_girth(V, T, el2 + n2 * 0.93, n2, 0.07)
    prof = [round(section_girth(V, T, sh + n1 * f, n1, 0.10) * 100, 1) for f in (0.2, 0.35, 0.5, 0.65, 0.8)]
    return {"biceps_cm": round(float(np.mean(up)) * 100, 1), "forearm_cm": round(max(fo) * 100, 1), "wrist_cm": round(wrst * 100, 1),
            "upperarm_profile_cm_20_35_50_65_80pct": prof}


# =============================================================================
# 3. linear subdivision with attribute interpolation
# =============================================================================

def subdivide(V, faces):
    """Midpoint subdivision: every n-gon -> n quads.  Returns (V2, faces2, M) with M a sparse
    (n2 x n) interpolation matrix (apply to weights, shape deltas, any per-vertex data)."""
    from scipy import sparse
    nv = len(V)
    edge_id = {}
    rows, cols, vals = list(range(nv)), list(range(nv)), [1.0] * nv
    nxt = nv
    for f in faces:
        k = len(f)
        for i in range(k):
            e = tuple(sorted((f[i], f[(i + 1) % k])))
            if e not in edge_id:
                edge_id[e] = nxt
                rows += [nxt, nxt]
                cols += [e[0], e[1]]
                vals += [0.5, 0.5]
                nxt += 1
    F2 = []
    for f in faces:
        k = len(f)
        c = nxt
        nxt += 1
        for v in f:
            rows.append(c)
            cols.append(v)
            vals.append(1.0 / k)
        for i in range(k):
            a = f[i]
            e_next = edge_id[tuple(sorted((f[i], f[(i + 1) % k])))]
            e_prev = edge_id[tuple(sorted((f[i - 1], f[i])))]
            F2.append([a, e_next, c, e_prev])
    M = sparse.csr_matrix((vals, (rows, cols)), shape=(nxt, nv))
    return M @ V, F2, M


# =============================================================================
# 4. garment arrays
# =============================================================================

class Garment:
    """Garment as arrays: V (rest), F (polygons), W (dense weights), keys {name: delta}, src (the
    body point each vertex came from, after subdivision)."""

    def __init__(self, V, F, W, keys, names):
        self.V = np.asarray(V, float)
        self.F = [list(map(int, f)) for f in F]
        self.W = np.asarray(W, float)
        self.keys = dict(keys)
        self.names = names
        self.src = self.V.copy()
        self._nb = None
        self.attrs = {}

    @classmethod
    def from_body(cls, body, keep_face, names):
        me = body.data
        V = S.co_of(body)
        W = S.read_W(body, names)
        faces = [list(p.vertices) for p in me.polygons]
        sel = [faces[i] for i in np.nonzero(keep_face)[0]]
        used = np.unique(np.concatenate([np.array(f) for f in sel]))
        remap = -np.ones(len(V), np.int64)
        remap[used] = np.arange(len(used))
        F = [[int(remap[v]) for v in f] for f in sel]
        keys = {}
        if me.shape_keys is not None:
            kb = me.shape_keys.key_blocks
            base = np.empty(len(V) * 3)
            kb[0].data.foreach_get("co", base)
            base = base.reshape(-1, 3)
            for k in kb[1:]:
                c = np.empty(len(V) * 3)
                k.data.foreach_get("co", c)
                dl = c.reshape(-1, 3) - base
                dl = dl[used]
                if np.abs(dl).max() > 1e-5:
                    keys[k.name] = dl
        g = cls(V[used], F, W[used], keys, names)
        g.body_index = used
        return g

    def subdivide(self):
        V2, F2, M = subdivide(self.V, self.F)
        self.V = V2
        self.src = M @ self.src
        self.F = F2
        self.W = S.limit_normalize(M @ self.W, 4)
        self.keys = {k: M @ d for k, d in self.keys.items()}
        self.attrs = {k: M @ a for k, a in self.attrs.items()}
        self._nb = None
        return M

    @property
    def nb(self):
        if self._nb is None:
            self._nb = poly_neighbours(len(self.V), self.F)
        return self._nb

    def normals(self, V=None):
        return poly_normals(self.V if V is None else V, self.F)[0]

    def tris(self):
        return poly_normals(self.V, self.F)[1]

    def boundary(self):
        return poly_boundary(len(self.V), self.F)

    def dom(self):
        return np.array(self.names)[self.W.argmax(1)]

    def wsum(self, bones):
        idx = [self.names.index(b) for b in bones if b in self.names]
        return self.W[:, idx].sum(1)

    def to_object(self, name, col, arm, keys=True):
        ob = S.make_mesh(name, self.V, self.F, col)
        S.write_W(ob, self.W, self.names, arm)
        if keys and self.keys:
            ob.shape_key_add(name="Basis", from_mix=False)
            for k, d in self.keys.items():
                kk = ob.shape_key_add(name=k, from_mix=False)
                kk.data.foreach_set("co", (self.V + d).ravel())
                kk.value = 0.0
        return ob


# =============================================================================
# 5. limb shells
# =============================================================================

class LimbAxis:
    """Polyline axis through joints J (e.g. shoulder, elbow, wrist) with smooth blending at the
    inner joints.  coords(P) -> s (arc length), A (axis point), T (tangent), U, Vv (section basis:
    U = `ref` direction projected perpendicular to T)."""

    def __init__(self, J, ref, blend=0.035):
        self.J = [np.asarray(j, float) for j in J]
        self.L = np.concatenate([[0.0], np.cumsum([np.linalg.norm(self.J[i + 1] - self.J[i]) for i in range(len(self.J) - 1)])])
        self.ref = np.asarray(ref, float)
        self.blend = blend

    def frame(self, s):
        """Axis point, tangent and section basis (U, V) at arc length s (no joint blending)."""
        k = int(np.clip(np.searchsorted(self.L, s) - 1, 0, len(self.J) - 2))
        a, b = self.J[k], self.J[k + 1]
        d = b - a
        L = np.linalg.norm(d)
        T = d / L
        A = a + T * (s - self.L[k])
        U = self.ref - T * (T @ self.ref)
        U /= np.linalg.norm(U)
        return A, T, U, np.cross(T, U)

    def coords(self, P):
        P = np.asarray(P, float)
        n = len(P)
        segs = len(self.J) - 1
        As, Ss, Ts = [], [], []
        for k in range(segs):
            a, b = self.J[k], self.J[k + 1]
            d = b - a
            L = np.linalg.norm(d)
            t = ((P - a) @ d) / (L * L)
            lo = -0.35 if k == 0 else 0.0
            hi = 1.35 if k == segs - 1 else 1.0
            tc = np.clip(t, lo, hi)
            As.append(a + tc[:, None] * d)
            Ss.append(self.L[k] + t * L)
            Ts.append(np.tile(d / L, (n, 1)))
        A, s, T = As[0], Ss[0], Ts[0]
        for k in range(1, segs):
            d0 = (self.J[k] - self.J[k - 1]); d0 /= np.linalg.norm(d0)
            d1 = (self.J[k + 1] - self.J[k]); d1 /= np.linalg.norm(d1)
            bis = d0 + d1
            bis /= np.linalg.norm(bis)
            w = smoothstep(-self.blend, self.blend, (P - self.J[k]) @ bis)[:, None]
            A = A * (1 - w) + As[k] * w
            s = s * (1 - w[:, 0]) + Ss[k] * w[:, 0]
            T = T * (1 - w) + Ts[k] * w
        T /= np.linalg.norm(T, axis=1, keepdims=True)
        U = self.ref[None, :] - T * (T @ self.ref)[:, None]
        U /= np.maximum(np.linalg.norm(U, axis=1, keepdims=True), 1e-9)
        Vv = np.cross(T, U)
        return s, A, T, U, Vv


def hull_radius_table(axis, pts, s_bins, n_phi=48, k_env=1.0, min_pts=8, k_env_up=None):
    """r(s, phi): convex-hull radius of the limb section at each s bin, then a parabolic upper
    envelope along s (fabric bridges bulges: the envelope drops at most k_env * ds^2), then a small
    circular smoothing in phi."""
    from scipy.spatial import ConvexHull
    s, A, T, U, Vv = axis.coords(pts)
    r2 = np.c_[((pts - A) * U).sum(1), ((pts - A) * Vv).sum(1)]
    phis = np.linspace(-np.pi, np.pi, n_phi, endpoint=False)
    dirs = np.c_[np.cos(phis), np.sin(phis)]
    ns = len(s_bins)
    R = np.full((ns, n_phi), np.nan)
    ds = s_bins[1] - s_bins[0]
    for i, sb in enumerate(s_bins):
        m = np.abs(s - sb) <= ds * 0.75
        if m.sum() < min_pts:
            continue
        q = r2[m]
        try:
            h = ConvexHull(q)
        except Exception:
            continue
        hv = q[h.vertices]
        # ray from origin: for each hull edge, intersection parameter
        a = hv
        b = np.roll(hv, -1, 0)
        e = b - a
        rr = np.full(n_phi, np.nan)
        for j, dvec in enumerate(dirs):
            # solve t*d = a + u*e, 0<=u<=1, t>0
            den = dvec[0] * (-e[:, 1]) - dvec[1] * (-e[:, 0])
            ok = np.abs(den) > 1e-12
            t = np.where(ok, (a[:, 0] * (-e[:, 1]) - a[:, 1] * (-e[:, 0])) / np.where(ok, den, 1), np.nan)
            u = np.where(ok, (dvec[0] * a[:, 1] - dvec[1] * a[:, 0]) / np.where(ok, den, 1), np.nan)
            good = ok & (u >= -1e-6) & (u <= 1 + 1e-6) & (t > 0)
            if good.any():
                rr[j] = t[good].max()
        if np.isnan(rr).all():
            continue
        # origin outside the hull: fall back to the max projection
        if np.isnan(rr).any():
            proj = q @ dirs.T
            rr = np.where(np.isnan(rr), np.clip(proj.max(0), 0.005, None), rr)
        R[i] = rr
    # fill empty bins along s
    for j in range(n_phi):
        col = R[:, j]
        good = ~np.isnan(col)
        if good.sum() == 0:
            R[:, j] = 0.05
        else:
            R[:, j] = np.interp(np.arange(ns), np.nonzero(good)[0], col[good])
    # parabolic upper envelope along s
    E = R.copy()
    kk = np.where(s_bins[None, :] <= s_bins[:, None], k_env, k_env if k_env_up is None else k_env_up)   # [i, j]
    for i in range(ns):
        dsq = ((s_bins - s_bins[i]) ** 2)[:, None]
        E[i] = (R - kk[i][:, None] * dsq).max(0)
    # circular smoothing in phi
    for _ in range(2):
        E = 0.25 * np.roll(E, 1, 1) + 0.5 * E + 0.25 * np.roll(E, -1, 1)
    return E, phis


def sample_table(E, s_bins, phis, s, phi):
    ns, nph = E.shape
    fi = np.clip((s - s_bins[0]) / (s_bins[1] - s_bins[0]), 0, ns - 1.0001)
    i0 = np.floor(fi).astype(int)
    a = fi - i0
    fp = ((phi - phis[0]) % (2 * np.pi)) / (2 * np.pi / nph)
    j0 = np.floor(fp).astype(int) % nph
    j1 = (j0 + 1) % nph
    b = fp - np.floor(fp)
    r = (E[i0, j0] * (1 - a) * (1 - b) + E[i0 + 1, j0] * a * (1 - b)
         + E[i0, j1] * (1 - a) * b + E[i0 + 1, j1] * a * b)
    return r


# =============================================================================
# 6. relaxation with body clearance (sparse, fast)
# =============================================================================

def relax_clear(V, L, body_bvh, fixed, min_clear, iters=10, alpha=0.4, nearest_every=1):
    """Laplacian smoothing (operator L) with a per-vertex minimum clearance outside the body."""
    V = np.array(V, float, copy=True)
    for it in range(iters):
        new = (1 - alpha) * V + alpha * (L @ V)
        new[fixed] = V[fixed]
        V = new
        if it % nearest_every == 0 or it == iters - 1:
            loc, nor, fi, d = S.nearest_on(body_bvh, V, 0.3)
            ok = fi >= 0
            sd = np.where(((V - loc) * nor).sum(1) >= 0, d, -d)
            need = ok & (sd < min_clear)
            V[need] = loc[need] + nor[need] * min_clear[need, None]
    return V


def body_clearance(V, body_bvh):
    loc, nor, fi, d = S.nearest_on(body_bvh, V, 0.3)
    sd = np.where(((V - loc) * nor).sum(1) >= 0, d, -d)
    return sd, loc, nor


# =============================================================================
# 7. design: combat shirt (loose sleeves) and combat trousers (loose legs)
# =============================================================================

SLEEVE = dict(
    k_env=1.6,                        # fabric bridging along the arm (parabolic envelope, 1/m)
    top_upper=0.0025, bot_upper=0.0150,   # ease on top / on the hanging underside (m)
    top_elbow=0.0035, bot_elbow=0.0150,
    top_fore=0.0020, bot_fore=0.0095,
    top_bunch=0.0050, bot_bunch=0.0125,   # bunching zone above the cuff
    cuff=0.0028,                      # cuff band over the glove cuff
    cuff_band=0.040, bunch_len=0.105,  # lengths measured from the sleeve end
    sag_power=1.4,
    fold_elbow=0.0120, fold_cuff=0.0105, fold_drape=0.0055,
)
TORSO = dict(default=0.0115, chest=0.0100, back=0.0105, side=0.0150, shoulder=0.0080, collar=0.0130,
             tail=0.0060, blouse=0.0090, blouse_c=0.034, blouse_w=0.050,
             gather_amp=0.0050, gather_n=22, front=0.0100, sides=0.0150, backe=0.0110, k_down=0.6, k_up=3.0)
LEG = dict(
    k_env=0.9,
    # ease by angle around the leg: front, lateral, back, medial (m)
    thigh=(0.020, 0.025, 0.022, 0.009), knee=(0.015, 0.021, 0.024, 0.014), calf=(0.024, 0.025, 0.025, 0.019),
    blouse=0.012, blouse_z=(0.175, 0.345), hem_z=0.152, hem_ease=0.0135,
    fold_knee=0.0125, fold_blouse=0.0135, fold_drape=0.0060, fold_crotch=0.0070,
)
PELVIS = dict(waist=0.0075, seat=0.0165, front=0.0125, crotch=0.0110, back=0.0170, sides=0.0140, k_down=0.5, k_up=3.0)


def _phi(U, Vv, R):
    return np.arctan2((R * Vv).sum(1), (R * U).sum(1))


def arm_axis(arm, s):
    sh, el = bone_pts(arm, f"upperarm_{s}")
    el2, wr = bone_pts(arm, f"lowerarm_{s}")
    return LimbAxis([sh, el2, wr], ref=(0.0, 0.0, -1.0))


def leg_axis(arm, s):
    hip, kn = bone_pts(arm, f"thigh_{s}")
    kn2, an = bone_pts(arm, f"calf_{s}")
    return LimbAxis([hip, kn2, an], ref=(0.0, -1.0, 0.0), blend=0.045)


def torso_offset(G, d, body_bvh, iters=28, alpha=0.42, clear_frac=0.75, smooth_iters=10):
    """Normal offset by the field d (smoothed), relaxed with the clearance >= clear_frac * d."""
    L = sparse_lap(G.nb)
    for _ in range(smooth_iters):
        d = 0.5 * d + 0.5 * (L @ d)
    N = G.normals()
    V = G.V + N * d[:, None]
    fixed = G.boundary()
    V = relax_clear(V, L, body_bvh, fixed, d * clear_frac, iters=iters, alpha=alpha, nearest_every=2)
    return V, d, L


def sleeve_design(G, arm, body_V, body_W, names, glove_pts, sleeve_end_s, info):
    """Target positions of the sleeve vertices (both arms) + fold heights + membership m."""
    P = SLEEVE
    n = len(G.V)
    Vt = G.V.copy()
    m = np.zeros(n)
    h = np.zeros(n)
    col = {k: i for i, k in enumerate(names)}
    for k in ("sl_s_el", "sl_dend", "sl_post", "sl_phi"):
        G.attrs[k] = np.zeros(n)
    G.attrs["sl_T"] = np.tile(np.array([0.0, 0.0, 1.0]), (n, 1))
    for s, sg in (("l", 1.0), ("r", -1.0)):
        ax = arm_axis(arm, s)
        armw_b = sum(body_W[:, col[b]] for b in (f"upperarm_{s}", f"upperarm_twist_01_{s}", f"lowerarm_{s}", f"lowerarm_twist_01_{s}"))
        pts = body_V[(armw_b > 0.5) & (body_V[:, 0] * sg > 0)]
        gp = glove_pts[s]
        sg_, _, _, _, _ = ax.coords(gp)
        gp = gp[(sg_ > ax.L[2] - 0.10) & (sg_ < ax.L[2] + 0.01)]
        pts = np.concatenate([pts, gp])
        s_bins = np.arange(-0.08, ax.L[2] + 0.03, 0.01)
        E, phis = hull_radius_table(ax, pts, s_bins, k_env=P["k_env"])
        side = (G.V[:, 0] * sg) > 0
        wa = G.wsum([f"upperarm_{s}", f"upperarm_twist_01_{s}", f"lowerarm_{s}", f"lowerarm_twist_01_{s}"])
        sel = side & (wa > 1e-3)
        sv, A, T, U, Vv = ax.coords(G.V[sel])
        R = G.V[sel] - A
        phi = _phi(U, Vv, R)
        r_env = sample_table(E, s_bins, phis, sv, phi)
        se = sleeve_end_s[s]
        dend = se - sv                      # distance from the sleeve end (m, >= 0 on the sleeve)
        el = ax.L[1]
        # ease: top / bottom per zone
        w_up = 1.0 - smoothstep(el - 0.07, el - 0.02, sv)
        w_el = bump(sv, el, 0.07)
        w_fo = smoothstep(el + 0.02, el + 0.07, sv)
        tot = w_up + w_el + w_fo + 1e-9
        top = (P["top_upper"] * w_up + P["top_elbow"] * w_el + P["top_fore"] * w_fo) / tot
        bot = (P["bot_upper"] * w_up + P["bot_elbow"] * w_el + P["bot_fore"] * w_fo) / tot
        wb = bump(dend, P["cuff_band"] + 0.5 * P["bunch_len"], 0.5 * P["bunch_len"] + 0.012)
        top = top * (1 - wb) + P["top_bunch"] * wb
        bot = bot * (1 - wb) + P["bot_bunch"] * wb
        wc = 1.0 - smoothstep(P["cuff_band"] - 0.012, P["cuff_band"] + 0.004, dend)
        top = top * (1 - wc) + P["cuff"] * wc
        bot = bot * (1 - wc) + P["cuff"] * 1.4 * wc
        sag = ((1.0 + np.cos(phi)) * 0.5) ** P["sag_power"]
        ease = top + (bot - top) * sag
        rdir = R / np.maximum(np.linalg.norm(R, axis=1, keepdims=True), 1e-9)
        Vt[sel] = A + rdir * (r_env + ease)[:, None]
        # membership: arm weight, faded in over the shoulder (s < 4 cm from the joint)
        m[sel] = np.clip(wa[sel], 0, 1) * smoothstep(-0.03, 0.05, sv)
        # ---- folds
        fwd = np.array([0.0, -1.0, 0.0])
        Uc = U.mean(0); Vc = Vv.mean(0)
        phi_ant = math.atan2(fwd @ Vc, fwd @ Uc)           # anterior (inner elbow) direction
        seed = 3 if s == "l" else 7
        # elbow: compression folds, strongest on the inner side, slightly oblique
        env_e = bump(sv, el - 0.005, 0.075) * (0.35 + 0.65 * ((1 + np.cos(phi - phi_ant)) * 0.5) ** 1.5)
        x = 2 * np.pi * (sv - el) / 0.031 + 1.1 * np.sin(phi - phi_ant)
        h_el = P["fold_elbow"] * env_e * buckle(x, phi, seed, wander=1.6)
        # cuff bunching: stacked rings with phase wander
        env_c = bump(dend, P["cuff_band"] + 0.5 * P["bunch_len"], 0.5 * P["bunch_len"])
        xc = 2 * np.pi * dend / 0.028
        h_cu = P["fold_cuff"] * env_c * buckle(xc, phi, seed + 1, wander=2.6)
        # drape folds hanging along the underside of the upper arm / forearm
        env_d = (bump(sv, 0.5 * el, 0.5 * el) + 0.6 * bump(sv, el + 0.5 * (se - el - P["cuff_band"] - P["bunch_len"]), 0.08)) * sag
        xd = 3.2 * phi + 2 * np.pi * sv / 0.40 + 0.7 * vnoise1(sv * 12.0, seed + 2)
        h_dr = P["fold_drape"] * env_d * fold_profile(xd) * (1 - wb) * (1 - wc)
        h[sel] = h_el * (1 - wc) + h_cu + h_dr
        G.attrs["sl_s_el"][sel] = sv - el
        G.attrs["sl_dend"][sel] = dend
        G.attrs["sl_post"][sel] = np.abs(((phi - phi_ant - np.pi) + np.pi) % (2 * np.pi) - np.pi)
        G.attrs["sl_phi"][sel] = phi
        G.attrs["sl_T"][sel] = T
        info[f"sleeve_{s}"] = {"s_end": round(float(se), 3), "elbow_s": round(float(el), 3),
                               "fold_mm_p5_p95": [round(float(np.percentile(h[sel], 5)) * 1000, 1), round(float(np.percentile(h[sel], 95)) * 1000, 1)],
                               "elbow_env_max": round(float(env_e.max()), 2), "cuff_env_max": round(float(env_c.max()), 2)}
    return Vt, m, h


def leg_design(G, arm, body_V, body_W, names, info):
    P = LEG
    n = len(G.V)
    Vt = G.V.copy()
    m = np.zeros(n)
    h = np.zeros(n)
    col = {k: i for i, k in enumerate(names)}
    for k in ("lg_s_kn", "lg_cos", "lg_sin"):
        G.attrs[k] = np.zeros(n)
    for s, sg in (("l", 1.0), ("r", -1.0)):
        ax = leg_axis(arm, s)
        lw_b = sum(body_W[:, col[b]] for b in (f"thigh_{s}", f"calf_{s}"))
        pts = body_V[(lw_b > 0.5) & (body_V[:, 0] * sg > 0) & (body_V[:, 2] > 0.10)]
        s_bins = np.arange(-0.10, ax.L[2] + 0.02, 0.01)
        E, phis = hull_radius_table(ax, pts, s_bins, k_env=P["k_env"])
        side = (G.V[:, 0] * sg) > 0
        wl = G.wsum([f"thigh_{s}", f"calf_{s}", f"foot_{s}"])
        sel = side & (wl > 1e-3)
        sv, A, T, U, Vv = ax.coords(G.V[sel])
        R = G.V[sel] - A
        phi = _phi(U, Vv, R)
        # angle round the leg measured from the front towards the lateral side
        psi = np.degrees(-phi if s == "l" else phi) % 360.0
        r_env = sample_table(E, s_bins, phis, sv, phi)
        kn = ax.L[1]

        def by_angle(tab):
            xs = [0, 90, 180, 270, 360]
            ys = list(tab) + [tab[0]]
            return np.interp(psi, xs, ys)
        e_th, e_kn, e_cf = by_angle(P["thigh"]), by_angle(P["knee"]), by_angle(P["calf"])
        w_th = 1.0 - smoothstep(kn - 0.10, kn - 0.03, sv)
        w_kn = bump(sv, kn, 0.09)
        w_cf = smoothstep(kn + 0.03, kn + 0.10, sv)
        ease = (e_th * w_th + e_kn * w_kn + e_cf * w_cf) / (w_th + w_kn + w_cf + 1e-9)
        z = G.V[sel][:, 2]
        # crotch: little ease on the inner thigh near the crotch (the legs must not meet)
        med = bump(psi, 270.0, 75.0) * (1.0 - smoothstep(0.08, 0.26, sv))
        ease = ease * (1 - 0.6 * med)
        zb0, zb1 = P["blouse_z"]
        wbz = bump(z, 0.5 * (zb0 + zb1) - 0.02, 0.5 * (zb1 - zb0) + 0.02)
        ease = ease + P["blouse"] * wbz
        wh = 1.0 - smoothstep(P["hem_z"] + 0.004, P["hem_z"] + 0.030, z)
        ease = ease * (1 - wh) + P["hem_ease"] * wh
        rdir = R / np.maximum(np.linalg.norm(R, axis=1, keepdims=True), 1e-9)
        Vt[sel] = A + rdir * (r_env + ease)[:, None]
        m[sel] = smoothstep(0.25, 0.80, wl[sel]) * smoothstep(0.00, 0.09, sv)
        # ---- folds
        seed = 11 if s == "l" else 17
        # knee: compression folds behind the knee (strong) and above / below the knee pad (front)
        back = bump(psi, 180.0, 80.0)
        front = bump(psi, 0.0, 100.0) + bump(psi, 360.0, 100.0)
        xk = 2 * np.pi * (sv - kn) / 0.030
        env_k = bump(sv, kn + 0.01, 0.075) * (0.25 + 0.75 * back)
        env_kf = (bump(sv, kn - 0.085, 0.035) + bump(sv, kn + 0.090, 0.035)) * front
        h_kn = P["fold_knee"] * (env_k + 0.7 * env_kf) * buckle(xk, np.radians(psi), seed, wander=2.0)
        # stacked folds of the bloused hem above the boots
        xb = 2 * np.pi * (z - zb0) / 0.033
        env_b = bump(z, 0.5 * (zb0 + zb1), 0.5 * (zb1 - zb0))
        h_bl = P["fold_blouse"] * env_b * buckle(xb, np.radians(psi), seed + 1, wander=3.0, fade=0.6)
        # long drape folds down the thigh and the shin
        xd = 5.0 * np.radians(psi) + 2 * np.pi * sv / 0.55 + 0.8 * vnoise1(sv * 9.0, seed + 2)
        env_d = bump(sv, 0.45 * kn, 0.40 * kn) * 0.8 + bump(sv, kn + 0.5 * (ax.L[2] - kn), 0.10) * 0.6
        h_dr = P["fold_drape"] * env_d * fold_profile(xd) * (1 - env_b)
        # crotch diagonals (front, upper inner thigh towards the hip)
        env_x = bump(sv, 0.10, 0.09) * bump(psi, 320.0, 55.0)
        xx = 2 * np.pi * (sv * 0.8 + np.radians(psi) * 0.05) / 0.035
        h_cr = P["fold_crotch"] * env_x * fold_profile(xx)
        h[sel] = (h_kn + h_bl + h_dr + h_cr) * (1 - wh)
        G.attrs["lg_s_kn"][sel] = sv - kn
        G.attrs["lg_cos"][sel] = np.cos(np.radians(psi))
        G.attrs["lg_sin"][sel] = np.sin(np.radians(psi))
        info[f"leg_{s}"] = {"knee_s": round(float(kn), 3)}
    return Vt, m, h


def finish(G, V_torso, Vt, m, h, body_bvh, L, min_clear=0.0035, relax_iters=6, local_relax=None):
    """Blend limb targets into the torso result, relax the seams of the blend, add folds along the
    normals, keep min_clear off the body."""
    V = V_torso * (1 - m[:, None]) + Vt * m[:, None]
    fixed = G.boundary()
    mc = np.full(len(V), min_clear)
    V = relax_clear(V, L, body_bvh, fixed, mc, iters=relax_iters, alpha=0.30, nearest_every=2)
    if local_relax is not None:
        # extra smoothing in a region (e.g. the crotch: the fabric bridges, it does not follow the groin)
        fx = fixed | ~local_relax
        V = relax_clear(V, L, body_bvh, fx, mc * 1.2, iters=40, alpha=0.5, nearest_every=4)
    N = G.normals(V)
    V = V + N * h[:, None]
    sd, loc, nor = body_clearance(V, body_bvh)
    bad = sd < min_clear
    V[bad] = loc[bad] + nor[bad] * min_clear
    return V


def trunk_design(G, body_V, body_mask, top, bottom, ease_fn, k_down, k_up, member):
    """Vertical-axis shell: the body's horizontal sections (body_mask vertices) -> convex hull ->
    envelope that hangs from above (k_down: how fast the fabric may come back in below a bulge;
    k_up: above a bulge).  ease_fn(V, psi_deg) -> ease; member: per-vertex membership (0..1)."""
    ax = LimbAxis([np.asarray(top, float), np.asarray(bottom, float)], ref=(0.0, -1.0, 0.0))
    pts = body_V[body_mask]
    s_bins = np.arange(-0.02, ax.L[1] + 0.03, 0.01)
    E, phis = hull_radius_table(ax, pts, s_bins, n_phi=72, k_env=k_down, k_env_up=k_up, min_pts=10)
    sel = member > 1e-3
    sv, A, T, U, Vv = ax.coords(G.V[sel])
    R = G.V[sel] - A
    phi = _phi(U, Vv, R)
    r_env = sample_table(E, s_bins, phis, sv, phi)
    ease = ease_fn(G.V[sel], np.degrees(phi))
    rdir = R / np.maximum(np.linalg.norm(R, axis=1, keepdims=True), 1e-9)
    Vt = G.V.copy()
    Vt[sel] = A + rdir * (r_env + ease)[:, None]
    return Vt


# =============================================================================
# 8. sewing panels -> UV seams, unwrap, grain orientation; game-resolution copy
# =============================================================================

def face_values(F, vals):
    return np.array([vals[f].mean(0) for f in F])


def panel_seam_edges(F, labels, extra_cut=None):
    """Mesh edges between faces of different panel labels (+ extra_cut(fa, fb) -> bool)."""
    from collections import defaultdict
    ef = defaultdict(list)
    for fi, f in enumerate(F):
        k = len(f)
        for i in range(k):
            ef[tuple(sorted((f[i], f[(i + 1) % k])))].append(fi)
    seams = set()
    for e, fs in ef.items():
        if len(fs) != 2:
            continue
        a, b = fs
        if labels[a] != labels[b] or (extra_cut is not None and extra_cut(a, b)):
            seams.add(e)
    return seams, ef


def smooth_seams(V, F, seams, ef, surf_bvh, iters=8, alpha=0.5):
    """Straighten the panel boundaries (face labels give a staircase): seam vertices of degree 2 in
    the seam graph move towards the mean of their two seam neighbours, projected back onto the
    surface; junctions and open-boundary vertices stay."""
    from collections import defaultdict
    adj = defaultdict(set)
    for a, b in seams:
        adj[a].add(b)
        adj[b].add(a)
    openb = set()
    for e, fs in ef.items():
        if len(fs) == 1:
            openb.update(e)
    mov = np.array([v for v, n in adj.items() if len(n) == 2 and v not in openb], np.int64)
    if not len(mov):
        return V
    nbr = np.array([sorted(adj[v]) for v in mov], np.int64)
    V = np.array(V, float, copy=True)
    for _ in range(iters):
        tgt = 0.5 * (V[nbr[:, 0]] + V[nbr[:, 1]])
        P = V[mov] * (1 - alpha) + tgt * alpha
        loc, nor, fi, d = S.nearest_on(surf_bvh, P, 0.05)
        ok = fi >= 0
        P[ok] = loc[ok]
        V[mov] = P
    return V


def islands_from_seams(F, seams, ef):
    """Connected face components across non-seam edges."""
    n = len(F)
    parent = np.arange(n)

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for e, fs in ef.items():
        if len(fs) == 2 and e not in seams:
            a, b = find(fs[0]), find(fs[1])
            if a != b:
                parent[a] = b
    roots = np.array([find(i) for i in range(n)])
    _, isl = np.unique(roots, return_inverse=True)
    return isl


def unwrap_panels(ob, seams, method='ANGLE_BASED'):
    """Mark the seam edges on the object and unwrap it (all faces) in edit mode."""
    me = ob.data
    ev = np.empty(len(me.edges) * 2, np.int64)
    me.edges.foreach_get("vertices", ev)
    ev = np.sort(ev.reshape(-1, 2), axis=1)
    flag = np.array([(int(a), int(b)) in seams for a, b in ev])
    me.edges.foreach_set("use_seam", flag)
    while len(me.uv_layers):
        me.uv_layers.remove(me.uv_layers[0])
    me.uv_layers.new(name="UVMap")
    for o in bpy.context.selected_objects:
        o.select_set(False)
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.uv.unwrap(method=method, margin=0.002)
    bpy.ops.object.mode_set(mode='OBJECT')
    return int(flag.sum())


def orient_islands(ob, island_of_face, grain_face):
    """Rotate each UV island so the 3D grain direction of its faces maps to +V (fabric cut on the
    grain) and scale all islands to the same texel density (UV area / 3D area)."""
    me = ob.data
    nl = len(me.loops)
    uv = np.empty(nl * 2)
    me.uv_layers["UVMap"].data.foreach_get("uv", uv)
    uv = uv.reshape(-1, 2)
    lv = np.empty(nl, np.int64)
    me.loops.foreach_get("vertex_index", lv)
    co = S.co_of(ob)
    lstart = np.empty(len(me.polygons), np.int64)
    ltot = np.empty(len(me.polygons), np.int64)
    me.polygons.foreach_get("loop_start", lstart)
    me.polygons.foreach_get("loop_total", ltot)
    nisl = int(island_of_face.max()) + 1
    acc = np.zeros((nisl, 2))
    a3 = np.zeros(nisl)
    a2 = np.zeros(nisl)
    for fi in range(len(me.polygons)):
        ls = np.arange(lstart[fi], lstart[fi] + ltot[fi])
        p = co[lv[ls]]
        u = uv[ls]
        for k in range(1, len(ls) - 1):
            e1, e2 = p[k] - p[0], p[k + 1] - p[0]
            d1, d2 = u[k] - u[0], u[k + 1] - u[0]
            n = np.cross(e1, e2)
            A3 = 0.5 * np.linalg.norm(n)
            if A3 < 1e-12:
                continue
            A2 = 0.5 * abs(d1[0] * d2[1] - d1[1] * d2[0])
            g = grain_face[fi]
            g = g - n * (g @ n) / (n @ n)
            M = np.array([[e1 @ e1, e1 @ e2], [e1 @ e2, e2 @ e2]])
            try:
                ab = np.linalg.solve(M, np.array([g @ e1, g @ e2]))
            except np.linalg.LinAlgError:
                continue
            w = ab[0] * d1 + ab[1] * d2
            nw = np.linalg.norm(w)
            if nw > 1e-12:
                acc[island_of_face[fi]] += w / nw * A3
            a3[island_of_face[fi]] += A3
            a2[island_of_face[fi]] += A2
    # per loop island
    isl_loop = np.repeat(island_of_face, ltot)
    dens = np.sqrt(a2.sum() / max(a3.sum(), 1e-12))
    for i in range(nisl):
        m = isl_loop == i
        if not m.any():
            continue
        ang = math.atan2(acc[i, 1], acc[i, 0]) if np.linalg.norm(acc[i]) > 1e-12 else math.pi / 2
        rot = math.pi / 2 - ang
        c, s_ = math.cos(rot), math.sin(rot)
        cen = uv[m].mean(0)
        q = uv[m] - cen
        q = np.c_[q[:, 0] * c - q[:, 1] * s_, q[:, 0] * s_ + q[:, 1] * c]
        sc = dens / max(math.sqrt(a2[i] / max(a3[i], 1e-12)), 1e-12)
        uv[m] = q * sc + cen
    me.uv_layers["UVMap"].data.foreach_set("uv", uv.ravel())
    me.update()
    return nisl


def decimate_uv_safe(ob, target_tris):
    """Collapse decimation (keeps UV seams / island borders) to a triangle budget."""
    n = len(S.tris_of(ob.data))
    if n <= target_tris:
        return n
    dm = ob.modifiers.new("Dec", 'DECIMATE')
    dm.ratio = target_tris / n
    dm.use_collapse_triangulate = True
    S.apply_modifier(ob, dm)
    return len(S.tris_of(ob.data))


def transfer_keys_from_arrays(ob, hi_V, hi_tris, keys):
    """Shape keys (deltas on the hi-res garment) interpolated onto ob (nearest surface point)."""
    if not keys:
        return []
    co = S.co_of(ob)
    bv = S.bvh(hi_V, hi_tris)
    loc, _, fi, _ = S.nearest_on(bv, co, 0.2)
    t = hi_tris[np.maximum(fi, 0)]
    Bc = S.barycentric(loc, hi_V[t[:, 0]], hi_V[t[:, 1]], hi_V[t[:, 2]])
    if ob.data.shape_keys is None:
        ob.shape_key_add(name="Basis", from_mix=False)
    made = []
    for k, d in keys.items():
        dd = d[t[:, 0]] * Bc[:, 0:1] + d[t[:, 1]] * Bc[:, 1:2] + d[t[:, 2]] * Bc[:, 2:3]
        if np.abs(dd).max() < 1e-4:
            continue
        kk = ob.shape_key_add(name=k, from_mix=False)
        kk.data.foreach_set("co", (co + dd).ravel())
        kk.value = 0.0
        made.append(k)
    return made
