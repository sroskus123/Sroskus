"""
ivterrain -- reference implementation of the IRON VALLEY terrain definition (layout.json -> heightfield).

Coordinate convention: Blender world, metres, Z up, +X east, +Y north, origin = map centre,
extent x,y in [-175, 175].

Terrain = BASE + DETAIL (masked gradient-noise fBm) + STAMPS (applied in the listed order).
  BASE    : 71 x 71 height grid, 5 m spacing, node (i, j) at x = -175 + 5 i, y = -175 + 5 j,
            sampled with Catmull-Rom bicubic interpolation (clamped at the border).
            The grid itself was produced by base_analytic() below (kept for documentation;
            the GRID in layout.json is authoritative).
  DETAIL  : seeded multi-octave Perlin gradient noise (integer hash lowbias32, no tables), multiplied
            by a quiet-zone mask (0 on pads/roads/zones/spawns/buildings, smoothstep to 1 at 8 m) --
            see detail_noise().  Deterministic and portable (JS: Math.imul / >>> 0).
  STAMPS  : pads, roads, channels (brook), ditches, sunken lanes, retaining walls -- see apply_stamps().

Everything is deterministic numpy; the same functions are used by analyze.py and draw.py so the
drawings and analyses match the data exactly.
"""
import math
import numpy as np

EXT = 175.0
GRID_STEP = 5.0
GRID_N = 71


# ----------------------------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------------------------
def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def polyline_query(px, py, verts, zvals=None):
    """Nearest point on a polyline for arrays of points.
    Returns dist, side (+1 = left of travel direction, -1 = right), s (arc length at nearest
    point), z (linear interpolation of per-vertex values, or None)."""
    px = np.asarray(px, dtype=float)
    py = np.asarray(py, dtype=float)
    best = np.full(px.shape, np.inf)
    side = np.zeros(px.shape)
    sarc = np.zeros(px.shape)
    zout = np.zeros(px.shape) if zvals is not None else None
    acc = 0.0
    for k in range(len(verts) - 1):
        ax, ay = verts[k][0], verts[k][1]
        bx, by = verts[k + 1][0], verts[k + 1][1]
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        L = math.sqrt(L2)
        t = np.clip(((px - ax) * dx + (py - ay) * dy) / L2, 0.0, 1.0)
        qx = ax + t * dx
        qy = ay + t * dy
        d = np.hypot(px - qx, py - qy)
        m = d < best
        best = np.where(m, d, best)
        cr = dx * (py - ay) - dy * (px - ax)
        side = np.where(m, np.sign(cr) + (cr == 0), side)
        sarc = np.where(m, acc + t * L, sarc)
        if zvals is not None:
            zz = zvals[k] + t * (zvals[k + 1] - zvals[k])
            zout = np.where(m, zz, zout)
        acc += L
    return best, side, sarc, zout


def point_in_poly(px, py, poly):
    px = np.asarray(px, dtype=float)
    py = np.asarray(py, dtype=float)
    inside = np.zeros(px.shape, dtype=bool)
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        cond = ((yi > py) != (yj > py))
        with np.errstate(divide='ignore', invalid='ignore'):
            xint = (xj - xi) * (py - yi) / (yj - yi + 1e-12) + xi
        inside ^= cond & (px < xint)
        j = i
    return inside


def dist_to_poly_edge(px, py, poly):
    closed = list(poly) + [poly[0]]
    d, _, _, _ = polyline_query(px, py, closed)
    return d


# ----------------------------------------------------------------------------------------------
# BASE terrain (documentation of how GRID was produced)
# ----------------------------------------------------------------------------------------------
# Valley axes: three arms from the village square (0,0).  z = valley-floor height at vertex.
VALLEY_AXES = {
    "A": {"verts": [[0, 0], [-60, -18], [-120, -40], [-200, -70]], "z": [0.0, -1.0, -2.2, -4.2]},
    "B": {"verts": [[0, 0], [4, 60], [14, 120], [30, 200]], "z": [0.0, 1.8, 4.0, 7.0]},
    "C": {"verts": [[0, 0], [45, -40], [95, -80], [160, -135]], "z": [0.0, 1.2, 3.2, 6.0]},
}
BASE_PARAMS = {
    "distance": "d_i = distance to axis i; d = dmin - K ln(sum exp(-(d_i - dmin)/K)), K = 6 m (soft union); "
                "weights w_i = exp(-(d_i-dmin)/K)/sum -> floor = sum w_i z_i(s_i), s = sum w_i s_i",
    "floor_half_width": "w(s) = 12 + 0.08 * s   (s = blended arc length along the axes)",
    "rise": "e0 = max(0, d - w); e = e0^2/12 if e0 < 6 else e0 - 3; R = 0.0022 e^2 + 0.090 e; Rc = 42 tanh(R/42)",
    "noise": "N = m(r) * (0.8 sin(0.021x+0.9) sin(0.017y+2.1) + 0.5 sin(0.043x-0.031y+0.4) + "
             "0.3 sin(0.071x+0.052y+1.7) + 0.25 sin(-0.09x+0.11y+3.1)), m(r) = 0.25 + smoothstep(40,110,r)",
    "height": "h = floor(s) + Rc + N",
}


def base_analytic(x, y):
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    K = 6.0  # soft-min length scale (m): rounds the spur crests between the arms
    ds, fs, ss = [], [], []
    for ax in VALLEY_AXES.values():
        d, _, s, z = polyline_query(x, y, ax["verts"], ax["z"])
        ds.append(d); fs.append(z); ss.append(s)
    ds = np.array(ds); fs = np.array(fs); ss = np.array(ss)
    dmin = ds.min(axis=0)
    ex = np.exp(-(ds - dmin) / K)
    wsum = ex.sum(axis=0)
    d_soft = dmin - K * np.log(wsum)          # smooth union of the three distance fields
    wts = ex / wsum
    floor = (wts * fs).sum(axis=0)
    s = (wts * ss).sum(axis=0)
    w = 12.0 + 0.08 * s
    e = np.maximum(0.0, d_soft - w)
    e = np.where(e < 6.0, e * e / 12.0, e - 3.0)  # C1-smooth start of the valley side
    R = 0.0022 * e * e + 0.090 * e
    Rc = 42.0 * np.tanh(R / 42.0)
    r = np.hypot(x, y)
    m = 0.25 + smoothstep(40.0, 110.0, r)
    N = (0.8 * np.sin(0.021 * x + 0.9) * np.sin(0.017 * y + 2.1)
         + 0.5 * np.sin(0.043 * x - 0.031 * y + 0.4)
         + 0.3 * np.sin(0.071 * x + 0.052 * y + 1.7)
         + 0.25 * np.sin(-0.09 * x + 0.11 * y + 3.1))
    return floor + Rc + m * N


def make_base_grid():
    g = np.arange(GRID_N) * GRID_STEP - EXT
    X, Y = np.meshgrid(g, g, indexing="xy")  # rows = y (j), cols = x (i)
    H = base_analytic(X, Y)
    return np.round(H, 2)


# ----------------------------------------------------------------------------------------------
# Catmull-Rom bicubic sampling of GRID  (grid[j][i] -> row j = y index, col i = x index)
# ----------------------------------------------------------------------------------------------
def _cr(p0, p1, p2, p3, t):
    return 0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t
                  + (-p0 + 3 * p1 - 3 * p2 + p3) * t * t * t)


def sample_grid(grid, x, y):
    grid = np.asarray(grid, dtype=float)
    n = grid.shape[0]
    fx = (np.asarray(x, dtype=float) + EXT) / GRID_STEP
    fy = (np.asarray(y, dtype=float) + EXT) / GRID_STEP
    fx = np.clip(fx, 0, n - 1 - 1e-9)
    fy = np.clip(fy, 0, n - 1 - 1e-9)
    i1 = np.floor(fx).astype(int)
    j1 = np.floor(fy).astype(int)
    tx = fx - i1
    ty = fy - j1
    rows = []
    for dj in (-1, 0, 1, 2):
        jj = np.clip(j1 + dj, 0, n - 1)
        vals = [grid[jj, np.clip(i1 + di, 0, n - 1)] for di in (-1, 0, 1, 2)]
        rows.append(_cr(vals[0], vals[1], vals[2], vals[3], tx))
    return _cr(rows[0], rows[1], rows[2], rows[3], ty)


# ----------------------------------------------------------------------------------------------
# DETAIL: masked Perlin gradient-noise fBm (portable integer hash, no permutation tables)
# ----------------------------------------------------------------------------------------------
_M32 = np.uint64(0xFFFFFFFF)


def hash_u32(ix, iy, seed):
    """lowbias32( (ix*0x8da6b343) ^ (iy*0xd8163841) ^ (seed*0xcb1ab31f) ), all arithmetic mod 2^32.
    ix, iy: integer lattice coordinates (may be negative -> two's complement mod 2^32)."""
    ix = np.asarray(ix, dtype=np.int64).astype(np.uint64) & _M32
    iy = np.asarray(iy, dtype=np.int64).astype(np.uint64) & _M32
    s = np.uint64(seed & 0xFFFFFFFF)
    h = ((ix * np.uint64(0x8da6b343)) & _M32) ^ ((iy * np.uint64(0xd8163841)) & _M32) ^ ((s * np.uint64(0xcb1ab31f)) & _M32)
    h ^= h >> np.uint64(16)
    h = (h * np.uint64(0x7feb352d)) & _M32
    h ^= h >> np.uint64(15)
    h = (h * np.uint64(0x846ca68b)) & _M32
    h ^= h >> np.uint64(16)
    return h


def perlin2(x, y, seed):
    """Classic 2D gradient noise on a unit lattice; gradient angle = hash/2^32 * 2pi; quintic fade.
    Output roughly in [-0.7, 0.7], exactly 0 on lattice points."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    x0 = np.floor(x)
    y0 = np.floor(y)
    fx = x - x0
    fy = y - y0
    ix = x0.astype(np.int64)
    iy = y0.astype(np.int64)

    def grad(cx, cy, dx, dy):
        a = hash_u32(cx, cy, seed).astype(float) * (2.0 * math.pi / 4294967296.0)
        return np.cos(a) * dx + np.sin(a) * dy

    n00 = grad(ix, iy, fx, fy)
    n10 = grad(ix + 1, iy, fx - 1.0, fy)
    n01 = grad(ix, iy + 1, fx, fy - 1.0)
    n11 = grad(ix + 1, iy + 1, fx - 1.0, fy - 1.0)
    u = fx * fx * fx * (fx * (fx * 6.0 - 15.0) + 10.0)
    v = fy * fy * fy * (fy * (fy * 6.0 - 15.0) + 10.0)
    nx0 = n00 + u * (n10 - n00)
    nx1 = n01 + u * (n11 - n01)
    return nx0 + v * (nx1 - nx0)


def fbm(x, y, octaves):
    out = np.zeros(np.shape(x))
    for o in octaves:
        f = 1.0 / o["wavelength"]
        out = out + o["amplitude"] * perlin2(np.asarray(x) * f + o.get("offset", [0.0, 0.0])[0],
                                             np.asarray(y) * f + o.get("offset", [0.0, 0.0])[1], o["seed"])
    return out


def detail_mask(X, Y, mask_def):
    """Amplitude multiplier in [floor, 1]: 0 inside every quiet feature, smoothstep(0, ramp, distance
    outside the feature) -> 1.  Features: polygon (inside = 0) or polyline with half_width."""
    X = np.asarray(X, dtype=float)
    Y = np.asarray(Y, dtype=float)
    ramp = mask_def["ramp_m"]
    m = np.ones(X.shape)
    for f in mask_def["quiet_features"]:
        pts = f["pts"]
        P = np.asarray(pts, dtype=float)
        pad = f.get("half_width", 0.0)
        xmin, ymin = P.min(axis=0) - pad - ramp
        xmax, ymax = P.max(axis=0) + pad + ramp
        sel = (X >= xmin) & (X <= xmax) & (Y >= ymin) & (Y <= ymax)
        if not sel.any():
            continue
        xs = X[sel]
        ys = Y[sel]
        if f["kind"] == "polygon":
            ins = point_in_poly(xs, ys, pts)
            d = dist_to_poly_edge(xs, ys, pts)
            d = np.where(ins, 0.0, d)
        else:
            d, _, _, _ = polyline_query(xs, ys, pts)
            d = np.maximum(0.0, d - pad)
        q = smoothstep(0.0, ramp, d)
        mm = m[sel]
        m[sel] = np.minimum(mm, q)
    return np.maximum(m, mask_def.get("floor", 0.0))


def detail_noise(X, Y, dn):
    if not dn:
        return np.zeros(np.shape(X))
    return fbm(X, Y, dn["octaves"]) * detail_mask(X, Y, dn["mask"])


# ----------------------------------------------------------------------------------------------
# STAMPS
# ----------------------------------------------------------------------------------------------
def apply_stamps(H, X, Y, stamps):
    """Apply stamps in order.  Stamp kinds:
      pad      : {polygon, z, blend}            h = lerp(h, z, wgt); wgt = 1 inside, smoothstep to 0
                                                at `blend` metres outside the polygon edge.
      road     : {polyline [[x,y,z]..], width, shoulder, blend}
                                                h = lerp(h, zline, wgt); wgt = 1 for d <= width/2 +
                                                shoulder, smoothstep to 0 at + blend.
      channel  : {polyline [[x,y,zbed]..], bed_width, bank_slope_h_per_v, [vertical_sections]}
                                                carve: h = min(h, zbed + max(0, d - bed/2) / slope).
                                                vertical_sections: [{s0, s1, half_width}] -> for
                                                d <= half_width inside [s0,s1]: h = min(h, zbed)
                                                (masonry-lined, vertical banks).
      ditch    : same as channel (smaller).
      sunken_lane: {polyline [[x,y,zbed]..], bed_width, bank_slope_h_per_v (steep, not walkable),
                  exits [{s0, s1, side left|right|both, bank_slope_h_per_v (walkable), taper}]}
                                                carve like a channel; inside an exit window the bank
                                                slope blends (smoothstep over `taper` m of arc length)
                                                to the exit slope -> walkable ramps out of the lane.
      wall     : {polyline [[x,y]..], top_z [..], bottom_z [..], high_side: left|right,
                  set_high, blend_high, set_low, blend_low}
                                                exact step at the wall centre line: high side set
                                                to top_z for set_high m then blended over blend_high;
                                                low side likewise with bottom_z.
    """
    H = H.copy()
    for st in stamps:
        k = st["kind"]
        if k == "pad":
            poly = st["polygon"]
            inside = point_in_poly(X, Y, poly)
            d = dist_to_poly_edge(X, Y, poly)
            wgt = np.where(inside, 1.0, 1.0 - smoothstep(0.0, st["blend"], d)) if st["blend"] > 0 \
                else inside.astype(float)
            H = H + wgt * (st["z"] - H)
        elif k == "road":
            pl = st["polyline"]
            d, _, _, z = polyline_query(X, Y, [[p[0], p[1]] for p in pl], [p[2] for p in pl])
            core = st["width"] / 2.0 + st.get("shoulder", 0.0)
            wgt = 1.0 - smoothstep(core, core + st["blend"], d)
            H = H + wgt * (z - H)
        elif k in ("channel", "ditch"):
            pl = st["polyline"]
            d, _, s, z = polyline_query(X, Y, [[p[0], p[1]] for p in pl], [p[2] for p in pl])
            carve = z + np.maximum(0.0, d - st["bed_width"] / 2.0) / st["bank_slope_h_per_v"]
            H = np.minimum(H, carve)
            for vs in st.get("vertical_sections", []):
                m = (s >= vs["s0"]) & (s <= vs["s1"]) & (d <= vs["half_width"])
                H = np.where(m, np.minimum(H, z), H)
        elif k == "sunken_lane":
            pl = st["polyline"]
            d, side, s, z = polyline_query(X, Y, [[p[0], p[1]] for p in pl], [p[2] for p in pl])
            steep = st["bank_slope_h_per_v"]
            slope = np.full(np.shape(X), float(steep))
            for ex in st.get("exits", []):
                w = smoothstep(ex["s0"] - ex.get("taper", 1.5), ex["s0"], s) * (1.0 - smoothstep(ex["s1"], ex["s1"] + ex.get("taper", 1.5), s))
                if ex["side"] == "left":
                    w = w * (side > 0)
                elif ex["side"] == "right":
                    w = w * (side < 0)
                slope = slope + w * (ex["bank_slope_h_per_v"] - slope)
            carve = z + np.maximum(0.0, d - st["bed_width"] / 2.0) / slope
            H = np.minimum(H, carve)
        elif k == "wall":
            pl = st["polyline"]
            d, side, _, ztop = polyline_query(X, Y, pl, st["top_z"])
            _, _, _, zbot = polyline_query(X, Y, pl, st["bottom_z"])
            hs = 1.0 if st["high_side"] == "left" else -1.0
            # restrict to the wall's own extent (perpendicular foot inside the polyline)
            hi = (side == hs)
            lo = ~hi
            w_hi = 1.0 - smoothstep(st["set_high"], st["set_high"] + st["blend_high"], d)
            w_lo = 1.0 - smoothstep(st["set_low"], st["set_low"] + st["blend_low"], d)
            ext = _within_extent(X, Y, pl)
            H = np.where(hi & ext, H + w_hi * (ztop - H), H)
            H = np.where(lo & ext, H + w_lo * (zbot - H), H)
        else:
            raise ValueError(k)
    return H


def _within_extent(X, Y, pl):
    """True where the nearest point of the polyline is not one of its two END points, i.e. the point lies beside the wall
    (perpendicular foot inside a segment) or in the wedge of an interior vertex (outer corner of a bent wall).  (Before
    2026-09-27 points whose foot fell exactly on an interior vertex were excluded, which left a one-cell notch on grid rows
    through the vertices.)"""
    _, _, s, _ = polyline_query(X, Y, [[p[0], p[1]] for p in pl])
    total = sum(math.hypot(pl[k + 1][0] - pl[k][0], pl[k + 1][1] - pl[k][1]) for k in range(len(pl) - 1))
    return (s > 1e-9) & (s < total - 1e-9)


def heightfield(layout, res=1.0, x0=-EXT, x1=EXT, y0=-EXT, y1=EXT):
    xs = np.arange(x0, x1 + 1e-9, res)
    ys = np.arange(y0, y1 + 1e-9, res)
    X, Y = np.meshgrid(xs, ys, indexing="xy")
    grid = np.asarray(layout["terrain"]["base_grid"]["heights"], dtype=float)
    H = sample_grid(grid, X, Y) + detail_noise(X, Y, layout["terrain"].get("detail_noise"))
    H = apply_stamps(H, X, Y, layout["terrain"]["stamps"])
    return X, Y, H


def height_at(layout, x, y):
    grid = np.asarray(layout["terrain"]["base_grid"]["heights"], dtype=float)
    X = np.atleast_1d(np.asarray(x, dtype=float))
    Y = np.atleast_1d(np.asarray(y, dtype=float))
    H = sample_grid(grid, X, Y) + detail_noise(X, Y, layout["terrain"].get("detail_noise"))
    H = apply_stamps(H, X, Y, layout["terrain"]["stamps"])
    return H


def base_plus_detail(layout, X, Y):
    grid = np.asarray(layout["terrain"]["base_grid"]["heights"], dtype=float)
    return sample_grid(grid, X, Y) + detail_noise(X, Y, layout["terrain"].get("detail_noise"))
