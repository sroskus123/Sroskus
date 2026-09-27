"""
ivoptics -- Iron Valley optics helpers (bpy 4.5 LTS, headless).  Builds on ivlib.

Imported by Art/Source/Blender/weapons/optics.py.  Everything is deterministic (no unseeded
randomness).  Section 1 and 2 are pure numpy / PIL and can be used without Blender.

Sections
  1. Angular units and the vector reticle rasteriser: reticles are described with vector
     primitives in MOA or mrad and rasterised with analytic signed distances (exact coverage
     antialiasing, no supersampled bitmaps except for numerals).  Outputs per reticle: RGBA base
     texture (straight alpha, colour bled into transparent texels so mip levels keep their
     colour), RGB emissive texture, RGB signed-distance texture and a JSON with the exact
     angular scale.
  2. Exterior ballistics (point mass, G7 drag) for bullet-drop holdover marks.
  3. Rail interface of the IV-7 (21 mm dovetail, 10 mm slot pitch) and rifle-frame conversion.
  4. Materials: thin coated glass (alpha blend + reflection, NO transmission / refraction),
     reticle (emissive, alpha, one-sided), black interior, engraved tick marks.
  5. Mesh helpers: thin lens / window, reticle plane with exact angular UV scale, sockets.
  6. Rifle: read-only import of the IV-7, optic mounting, iron-sight fold pose.
  7. Picture-in-picture composite (preview of the runtime scope rendering).
  8. Measurements / audits (reticle crispness, glTF material audit, transmission audit, sight
     fold), outdoor test-range scene for through-sight renders.
  9. Export jobs (FBX / GLB per optic, SOCKET_ names for Unreal) in a clean subprocess.
"""

import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))

# =============================================================================
# 1. Angular units and vector reticles
# =============================================================================

MOA_PER_MRAD = 10800.0 / (1000.0 * math.pi)        # 3.4377 MOA per milliradian
RAD_PER_UNIT = {"MOA": math.radians(1.0 / 60.0), "mrad": 1e-3}
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_REG = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def srgb_to_linear(c):
    c = np.asarray(c, np.float64)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(c):
    c = np.clip(np.asarray(c, np.float64), 0.0, 1.0)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(c, 1.0 / 2.4) - 0.055)


def _sd_segment(X, Y, ax, ay, bx, by):
    """Distance from points to segment ab (no radius)."""
    ex, ey = bx - ax, by - ay
    wx, wy = X - ax, Y - ay
    ee = ex * ex + ey * ey
    t = np.clip((wx * ex + wy * ey) / ee, 0.0, 1.0) if ee > 0 else np.zeros_like(X)
    dx, dy = wx - ex * t, wy - ey * t
    return np.sqrt(dx * dx + dy * dy)


def _sd_polygon(X, Y, pts):
    """Exact signed distance to a simple polygon (negative inside)."""
    v = [(float(a), float(b)) for a, b in pts]
    n = len(v)
    d = (X - v[0][0]) ** 2 + (Y - v[0][1]) ** 2
    s = np.ones_like(X)
    j = n - 1
    for i in range(n):
        ex, ey = v[j][0] - v[i][0], v[j][1] - v[i][1]
        wx, wy = X - v[i][0], Y - v[i][1]
        ee = ex * ex + ey * ey
        t = np.clip((wx * ex + wy * ey) / ee, 0.0, 1.0)
        bx, by = wx - ex * t, wy - ey * t
        d = np.minimum(d, bx * bx + by * by)
        c1 = Y >= v[i][1]
        c2 = Y < v[j][1]
        c3 = ex * wy > ey * wx
        flip = (c1 & c2 & c3) | (~c1 & ~c2 & ~c3)
        s = np.where(flip, -s, s)
        j = i
    return s * np.sqrt(d)


class Reticle:
    """A reticle described with vector primitives in angular units.

    Frame: origin = point of aim (the optical / sight axis), +x = right, +y = up, units 'MOA' or
    'mrad'.  The texture is square, `size_px` wide, and covers `field` units edge to edge, so the
    angular scale is exactly px_per_unit = size_px / field and the axis is the texture centre.
    Layers: 'lit' = illuminated (drawn in `color`, also written to the emissive texture),
    'etch' = etched / wire reticle (black, not illuminated)."""

    def __init__(self, rid, units, size_px, field, color_srgb=(255, 38, 24), title=""):
        assert units in RAD_PER_UNIT
        self.id = rid
        self.units = units
        self.N = int(size_px)
        self.field = float(field)
        self.ppu = self.N / self.field
        self.color = tuple(int(c) for c in color_srgb)
        self.title = title
        self.prims = []
        self.elements = []

    # -- primitives (all sizes in angular units) --------------------------------------------
    def _add(self, layer, fn, bbox, desc=None):
        assert layer in ("lit", "etch")
        self.prims.append({"layer": layer, "fn": fn, "bbox": bbox})
        if desc:
            self.elements.append({"layer": layer, **desc})

    def circle(self, c, r, layer="lit", desc=None):
        cx, cy = c
        self._add(layer, lambda X, Y: np.hypot(X - cx, Y - cy) - r, (cx - r, cy - r, cx + r, cy + r), desc)

    def ring(self, c, r, w, layer="lit", desc=None):
        """r = centre-line radius, w = stroke width."""
        cx, cy = c
        ro = r + w / 2
        self._add(layer, lambda X, Y: np.abs(np.hypot(X - cx, Y - cy) - r) - w / 2,
                  (cx - ro, cy - ro, cx + ro, cy + ro), desc)

    def arc(self, c, r, w, a0, a1, layer="lit", desc=None):
        """Circular arc (degrees, CCW from +x, a0 < a1) with round caps."""
        cx, cy = c
        t0, t1 = math.radians(a0), math.radians(a1)
        p0 = (cx + r * math.cos(t0), cy + r * math.sin(t0))
        p1 = (cx + r * math.cos(t1), cy + r * math.sin(t1))
        mid = 0.5 * (t0 + t1)
        half = 0.5 * (t1 - t0)

        def fn(X, Y):
            ang = np.arctan2(Y - cy, X - cx)
            rel = np.mod(ang - mid + math.pi, 2 * math.pi) - math.pi
            inside = np.abs(rel) <= half
            d_arc = np.abs(np.hypot(X - cx, Y - cy) - r)
            d_end = np.minimum(np.hypot(X - p0[0], Y - p0[1]), np.hypot(X - p1[0], Y - p1[1]))
            return np.where(inside, d_arc, d_end) - w / 2
        ro = r + w / 2
        self._add(layer, fn, (cx - ro, cy - ro, cx + ro, cy + ro), desc)

    def seg(self, a, b, w, layer="etch", cap="butt", desc=None):
        """Straight line of width w from a to b; cap 'butt' (square ends at a and b) or 'round'."""
        ax, ay = a
        bx, by = b
        if cap == "round":
            fn = lambda X, Y: _sd_segment(X, Y, ax, ay, bx, by) - w / 2
        else:
            L = math.hypot(bx - ax, by - ay)
            ux, uy = (bx - ax) / L, (by - ay) / L
            nx, ny = -uy * w / 2, ux * w / 2
            pts = [(ax + nx, ay + ny), (ax - nx, ay - ny), (bx - nx, by - ny), (bx + nx, by + ny)]
            fn = lambda X, Y, pts=pts: _sd_polygon(X, Y, pts)
        m = w / 2
        self._add(layer, fn, (min(ax, bx) - m, min(ay, by) - m, max(ax, bx) + m, max(ay, by) + m), desc)

    def poly(self, pts, layer="etch", desc=None):
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        self._add(layer, lambda X, Y: _sd_polygon(X, Y, pts), (min(xs), min(ys), max(xs), max(ys)), desc)

    def text(self, s, pos, height, layer="etch", anchor="lm", desc=None):
        """Numerals / letters (DejaVu Sans Bold), cap height = `height` units, anchored at pos.
        Rasterised 4x supersampled; the signed distance comes from a Euclidean distance
        transform of the supersampled mask."""
        self.prims.append({"layer": layer, "text": s, "pos": pos, "height": height, "anchor": anchor})
        if desc:
            self.elements.append({"layer": layer, **desc})

    # -- rasterisation ---------------------------------------------------------------------
    def _px(self, x, y):
        """Angular coordinates -> continuous pixel coordinates (col, row), row 0 at the top."""
        return (x + self.field / 2) * self.ppu, (self.field / 2 - y) * self.ppu

    def _text_sdf(self, p, spread_px):
        from PIL import Image, ImageDraw, ImageFont
        from scipy.ndimage import distance_transform_edt
        S = 4
        cap_px = p["height"] * self.ppu * S
        # DejaVu Sans Bold: cap height ~ 0.73 em
        font = ImageFont.truetype(FONT_BOLD, max(4, int(round(cap_px / 0.729))))
        cx, cy = self._px(*p["pos"])
        l, t, r, b = font.getbbox(p["text"], anchor=p["anchor"])
        pad = int(spread_px * S + 8)
        x0 = int(math.floor(cx + (l - pad) / S)); x1 = int(math.ceil(cx + (r + pad) / S))
        y0 = int(math.floor(cy + (t - pad) / S)); y1 = int(math.ceil(cy + (b + pad) / S))
        W, H = (x1 - x0) * S, (y1 - y0) * S
        img = Image.new("L", (W, H), 0)
        ImageDraw.Draw(img).text(((cx - x0) * S, (cy - y0) * S), p["text"], fill=255, font=font,
                                 anchor=p["anchor"])
        m = np.asarray(img) > 127
        sd = (distance_transform_edt(~m) - distance_transform_edt(m)) / S      # texture px
        sd = sd.reshape(H // S, S, W // S, S).mean(axis=(1, 3))
        return sd / self.ppu, (y0, y1, x0, x1)                                 # units

    def render(self, spread_px=16.0):
        """Rasterise.  Returns dict of float arrays (row 0 = top): cov_lit, cov_etch, alpha,
        sd_lit, sd_etch (units), plus the colour field t (1 = nearest feature is lit)."""
        N, ppu, F = self.N, self.ppu, self.field
        far = np.float32(4.0 * spread_px / ppu)
        sd = {"lit": np.full((N, N), far, np.float32), "etch": np.full((N, N), far, np.float32)}
        m = (spread_px + 3) / ppu
        for p in self.prims:
            tgt = sd[p["layer"]]
            if "text" in p:
                d, (i0, i1, j0, j1) = self._text_sdf(p, spread_px)
                a0, a1, b0, b1 = max(i0, 0), min(i1, N), max(j0, 0), min(j1, N)
                if a1 > a0 and b1 > b0:
                    sub = d[a0 - i0:a1 - i0, b0 - j0:b1 - j0].astype(np.float32)
                    np.minimum(tgt[a0:a1, b0:b1], sub, out=tgt[a0:a1, b0:b1])
                continue
            x0, y0, x1, y1 = p["bbox"]
            j0 = max(0, int(math.floor((x0 - m + F / 2) * ppu)))
            j1 = min(N, int(math.ceil((x1 + m + F / 2) * ppu)))
            i0 = max(0, int(math.floor((F / 2 - y1 - m) * ppu)))
            i1 = min(N, int(math.ceil((F / 2 - y0 + m) * ppu)))
            if j1 <= j0 or i1 <= i0:
                continue
            # evaluate in horizontal bands to bound memory on long primitives
            xs = (np.arange(j0, j1) + 0.5) / ppu - F / 2
            for r0 in range(i0, i1, 512):
                r1 = min(i1, r0 + 512)
                ys = F / 2 - (np.arange(r0, r1) + 0.5) / ppu
                X, Y = np.meshgrid(xs, ys)
                d = p["fn"](X, Y).astype(np.float32)
                np.minimum(tgt[r0:r1, j0:j1], d, out=tgt[r0:r1, j0:j1])
        cov_l = np.clip(0.5 - sd["lit"] * ppu, 0.0, 1.0)
        cov_e = np.clip(0.5 - sd["etch"] * ppu, 0.0, 1.0)
        alpha = cov_l + cov_e * (1.0 - cov_l)
        t = np.clip(0.5 + (sd["etch"] - sd["lit"]) * ppu * 0.5, 0.0, 1.0)
        return {"cov_lit": cov_l, "cov_etch": cov_e, "alpha": alpha, "sd_lit": sd["lit"],
                "sd_etch": sd["etch"], "t": t, "spread_px": spread_px}

    def save(self, out_dir, prefix=None, spread_px=16.0, extra=None):
        """Write T_<id>_Reticle.png (RGBA), _Emissive.png (RGB), _SDF.png (RGB) and
        T_<id>_Reticle.json.  Returns the metadata dict."""
        from PIL import Image
        os.makedirs(out_dir, exist_ok=True)
        prefix = prefix or f"T_{self.id}_Reticle"
        r = self.render(spread_px)
        col_srgb = np.array(self.color, np.float64) / 255.0
        col_lin = srgb_to_linear(col_srgb)
        t = r["t"][..., None]
        # base: colour field (lit colour where the nearest feature is lit, black where etched),
        # straight alpha; transparent texels carry the nearest feature's colour (mip safe)
        rgb = linear_to_srgb(col_lin[None, None, :] * t)
        base = np.dstack([rgb, r["alpha"][..., None]])
        base8 = np.clip(np.round(base * 255.0), 0, 255).astype(np.uint8)
        em = linear_to_srgb(col_lin[None, None, :] * r["cov_lit"][..., None])
        em8 = np.clip(np.round(em * 255.0), 0, 255).astype(np.uint8)

        def enc(sd):
            return np.clip(0.5 - sd * self.ppu / (2.0 * spread_px), 0.0, 1.0)
        sdf = np.dstack([enc(np.minimum(r["sd_lit"], r["sd_etch"])), enc(r["sd_lit"]), enc(r["sd_etch"])])
        sdf8 = np.clip(np.round(sdf * 255.0), 0, 255).astype(np.uint8)
        paths = {
            "base_rgba": os.path.join(out_dir, prefix + ".png"),
            "emissive_rgb": os.path.join(out_dir, prefix + "_Emissive.png"),
            "sdf_rgb": os.path.join(out_dir, prefix + "_SDF.png"),
        }
        Image.fromarray(base8, "RGBA").save(paths["base_rgba"], optimize=False, compress_level=9)
        Image.fromarray(em8, "RGB").save(paths["emissive_rgb"], optimize=False, compress_level=9)
        Image.fromarray(sdf8, "RGB").save(paths["sdf_rgb"], optimize=False, compress_level=9)
        # measured extents of the drawn reticle (alpha > 0.5), in units from the axis
        ys, xs = np.nonzero(r["alpha"] > 0.5)
        ext = None
        if len(xs):
            ext = {"x_min": round((xs.min() + 0.5) / self.ppu - self.field / 2, 4),
                   "x_max": round((xs.max() + 0.5) / self.ppu - self.field / 2, 4),
                   "y_min": round(self.field / 2 - (ys.max() + 0.5) / self.ppu, 4),
                   "y_max": round(self.field / 2 - (ys.min() + 0.5) / self.ppu, 4)}
        rad = RAD_PER_UNIT[self.units]
        meta = {
            "id": self.id, "title": self.title, "units": self.units,
            "size_px": [self.N, self.N], "field_units": self.field,
            "px_per_unit": self.ppu, "unit_in_rad": rad,
            "field_deg": math.degrees(self.field * rad),
            "px_per_moa": self.ppu if self.units == "MOA" else self.ppu / MOA_PER_MRAD,
            "px_per_mrad": self.ppu if self.units == "mrad" else self.ppu * MOA_PER_MRAD,
            "axis_px": [self.N / 2.0, self.N / 2.0],
            "axis_note": "the point of aim is the exact texture centre (between the four centre texels)",
            "orientation": "row 0 = top (up); +x = right as seen by the shooter",
            "colour_srgb": list(self.color),
            "drawn_extent_units": ext,
            "elements": self.elements,
            "textures": {k: os.path.basename(v) for k, v in paths.items()},
            "encoding": {
                "base_rgba": "sRGB colour + straight alpha. RGB = illumination colour where the nearest reticle "
                             "feature is illuminated, black where it is etched; transparent texels carry the "
                             "nearest feature colour so mip levels do not darken or fringe.",
                "emissive_rgb": "sRGB, illumination colour x coverage of the illuminated features only "
                                "(black = not illuminated). Multiply by the brightness setting.",
                "sdf_rgb": f"signed distance, 0.5 = feature edge, 1 = inside, 0 = outside; value = 0.5 - "
                           f"d_px / {2 * spread_px:g} (d_px = distance in texels at this resolution, "
                           f"clamped at +-{spread_px:g} px). R = all features, G = illuminated, B = etched.",
            },
            "sampling": "power-of-two, generate mips (box / Kaiser), trilinear + anisotropic filtering, "
                        "clamp-to-edge addressing (the border texels are transparent)",
        }
        if extra:
            meta.update(extra)
        with open(os.path.join(out_dir, prefix + ".json"), "w") as f:
            json.dump(meta, f, indent=2)
        meta["paths"] = paths
        meta["_render"] = r
        return meta


def reticle_preview(meta, out_path, bg="sky", size=1024, title=None, scale_units=None):
    """Composite a reticle texture over a background for review; draws the axis cross-hair
    guides in the margin and a scale bar of `scale_units`."""
    from PIL import Image, ImageDraw, ImageFont
    r = meta["_render"]
    N = meta["size_px"][0]
    col_lin = srgb_to_linear(np.array(meta["colour_srgb"]) / 255.0)
    yy = np.linspace(0, 1, N)[:, None]
    if bg == "sky":
        bgc = srgb_to_linear(np.array([0.72, 0.80, 0.88]))[None, None, :] * (1 - 0.25 * yy[..., None]) + \
              np.zeros((N, N, 3))
    else:
        bgc = np.full((N, N, 3), srgb_to_linear(0.5))
    # illuminated parts glow (display: emissive over the background), etched parts black
    t = r["t"][..., None]
    a = r["alpha"][..., None]
    fg = col_lin[None, None, :] * t * 1.0
    out = bgc * (1 - a) + fg * a
    img = Image.fromarray(np.clip(np.round(linear_to_srgb(out) * 255), 0, 255).astype(np.uint8), "RGB")
    img = img.resize((size, size), Image.LANCZOS)
    dr = ImageDraw.Draw(img)
    c = size / 2
    for d in (-1, 1):   # margin guides pointing at the axis
        dr.line([(c, 0 if d < 0 else size), (c, 12 if d < 0 else size - 12)], fill=(0, 90, 255), width=2)
        dr.line([(0 if d < 0 else size, c), (12 if d < 0 else size - 12, c)], fill=(0, 90, 255), width=2)
    font = ImageFont.truetype(FONT_REG, 18)
    if scale_units:
        px = scale_units * meta["px_per_unit"] * size / N
        dr.rectangle([20, size - 40, 20 + px, size - 34], fill=(20, 20, 20))
        dr.text((20, size - 30), f"{scale_units:g} {meta['units']}", fill=(20, 20, 20), font=font)
    dr.text((20, 16), title or meta["id"], fill=(20, 20, 20), font=font)
    img.save(out_path)
    return out_path


def eyebox_overlay(reticle_meta, radius_units, out_path, edge_soft_frac=0.006, vignette_start=0.86,
                   vignette_strength=0.55, rim_dark=0.18):
    """Full-screen scope ADS overlay (straight-alpha RGBA, same size and angular scale as the
    reticle texture, so px_per_unit is identical and the texture centre is the point of aim).

    Inside the eyebox (the field stop as seen at the design eye relief, radius `radius_units`):
    fully transparent except for the reticle and a soft darkening towards the field stop
    (vignette from `vignette_start` of the radius, smoothstep^1.5 to `vignette_strength`, plus a
    slight overall `rim_dark` fall-off that real eyepieces show).  The field stop itself is a
    crisp, antialiased edge (width edge_soft_frac x radius).  Outside the eyebox: opaque black
    (the eyepiece housing / tube shadow).  RGB is black everywhere except the illuminated
    reticle features (their colour); etched features are black ink."""
    from PIL import Image
    r = reticle_meta["_render"]
    N = reticle_meta["size_px"][0]
    ppu = reticle_meta["px_per_unit"]
    F = reticle_meta["field_units"]
    assert radius_units < F / 2, "eyebox must fit inside the texture"
    xs = (np.arange(N) + 0.5) / ppu - F / 2
    X, Y = np.meshgrid(xs, -xs)
    R = np.hypot(X, Y) / radius_units                       # 1 = field stop
    soft = max(edge_soft_frac, 1.0 / (radius_units * ppu))
    inside = np.clip((1.0 - R) / soft + 0.5, 0.0, 1.0)       # 1 inside, 0 outside (antialiased)
    u = np.clip((R - vignette_start) / (1.0 - vignette_start), 0.0, 1.0)
    vig = vignette_strength * (u * u * (3 - 2 * u)) ** 1.5 + rim_dark * np.clip(R, 0, 1) ** 4
    vig = np.clip(vig, 0.0, 1.0)
    a_ret = r["alpha"]
    t = r["t"]
    # layers (top to bottom): reticle, vignette (black), outside-mask (black, opaque)
    a_in = a_ret + vig * (1.0 - a_ret)
    alpha = a_in * inside + (1.0 - inside)
    col_lin = srgb_to_linear(np.array(reticle_meta["colour_srgb"]) / 255.0)
    # premultiplied colour: only the illuminated reticle has colour, the rest is black
    pre = col_lin[None, None, :] * (t * a_ret * inside)[..., None]
    rgb_lin = pre / np.maximum(alpha, 1e-6)[..., None]
    # colour-bleed: fully transparent texels inside the eyebox take the reticle colour field so
    # that mip levels / bilinear filtering never pull black into the illuminated strokes
    bleed = col_lin[None, None, :] * t[..., None]
    rgb_lin = np.where((alpha < 1e-4)[..., None], bleed, rgb_lin)
    out = np.dstack([linear_to_srgb(rgb_lin), alpha])
    Image.fromarray(np.clip(np.round(out * 255), 0, 255).astype(np.uint8), "RGBA").save(
        out_path, optimize=False, compress_level=9)
    c = N // 2
    return {"path": out_path, "size_px": [N, N], "px_per_unit": ppu, "units": reticle_meta["units"],
            "field_units": F, "eyebox_radius_units": radius_units, "eyebox_radius_px": radius_units * ppu,
            "eyebox_radius_fraction_of_size": radius_units * ppu / N,
            "field_stop_edge_width_fraction": soft, "vignette_start_fraction": vignette_start,
            "vignette_max_opacity": vignette_strength, "rim_darkening": rim_dark,
            "alpha_at_centre_offset_2units": float(alpha[c, c + int(2 * ppu)]),
            "alpha_outside": float(alpha[2, 2])}


# =============================================================================
# 2. Exterior ballistics (bullet-drop holdover marks)
# =============================================================================
# Standard G7 drag function (Mach, Cd), abridged.
G7 = [(0.00, 0.1198), (0.20, 0.1193), (0.40, 0.1193), (0.50, 0.1194), (0.60, 0.1194), (0.70, 0.1202),
      (0.75, 0.1215), (0.80, 0.1242), (0.85, 0.1306), (0.875, 0.1368), (0.90, 0.1464), (0.925, 0.1660),
      (0.95, 0.2054), (0.975, 0.2993), (1.00, 0.3803), (1.025, 0.4015), (1.05, 0.4043), (1.075, 0.4034),
      (1.10, 0.4014), (1.15, 0.3955), (1.20, 0.3884), (1.30, 0.3732), (1.40, 0.3580), (1.50, 0.3440),
      (1.60, 0.3315), (1.70, 0.3209), (1.80, 0.3117), (1.90, 0.3042), (2.00, 0.2980), (2.20, 0.2864),
      (2.40, 0.2752), (2.60, 0.2643), (2.80, 0.2533), (3.00, 0.2424), (3.50, 0.2150), (4.00, 0.1950)]
LB_PER_IN2 = 0.45359237 / 0.0254 ** 2           # 703.07 kg/m^2


def _g7_cd(mach):
    return float(np.interp(mach, [m for m, _ in G7], [c for _, c in G7]))


def trajectory(mv, bc_g7, launch_rad, x_max, rho=1.225, sound=340.3, g=9.80665, dt=2e-5):
    """Point-mass trajectory from the muzzle (0, 0).  Returns arrays x, y (m)."""
    k = rho * math.pi / (8.0 * LB_PER_IN2 * bc_g7)
    vx, vy = mv * math.cos(launch_rad), mv * math.sin(launch_rad)
    x = y = 0.0
    xs, ys = [0.0], [0.0]
    while x < x_max:
        v = math.hypot(vx, vy)
        a = k * _g7_cd(v / sound) * v
        # semi-implicit Euler at 20 us: well below 1 mm error at 600 m
        vx -= a * vx * dt
        vy -= (a * vy + g) * dt
        x += vx * dt
        y += vy * dt
        xs.append(x)
        ys.append(y)
    return np.array(xs), np.array(ys)


def holdovers(mv, bc_g7, sight_height_m, zero_m, ranges_m):
    """Drop below the line of sight (m) and holdover angle (rad) at each range for a rifle zeroed
    at zero_m with the sight axis sight_height_m above the bore."""
    lo, hi = -0.01, 0.02
    for _ in range(40):
        th = 0.5 * (lo + hi)
        xs, ys = trajectory(mv, bc_g7, th, zero_m + 1.0)
        y_z = float(np.interp(zero_m, xs, ys))
        if y_z > sight_height_m:
            hi = th
        else:
            lo = th
    th = 0.5 * (lo + hi)
    xs, ys = trajectory(mv, bc_g7, th, max(ranges_m) + 1.0)
    out = []
    for R in ranges_m:
        drop = sight_height_m - float(np.interp(R, xs, ys))
        out.append({"range_m": R, "drop_m": drop, "hold_rad": math.atan2(drop, R)})
    return {"launch_rad": th, "rows": out}


# =============================================================================
# 3. IV-7 rail interface and frames
# =============================================================================
# Bore frame (cm): X along the bore (0 = bolt face, +X muzzle), Z up (0 = bore axis), Y = weapon
# left.  Values from Art/Reference/IV7_carbine_spec.md / iv7_carbine.py (read here as data; that
# script is not imported).  Optic frame (cm while authoring, m after finalize): origin =
# socket_rail = rail top centre line at the front edge of the optic's (front) clamp; X forward,
# Y left, Z up; the rail top is z = 0.
IV7 = {
    "hold_bore_cm": (-16.685730, 0.0, -9.172327),     # grip hold point = rifle object origin
    "rail_top_cm": 3.0,
    "upper_rail_x_cm": (-14.5, 3.0),
    "handguard_rail_x_cm": (3.2, 36.2),
    "slot_pitch_cm": 1.0, "slot_width_cm": 0.53, "slot_floor_cm": 2.62,
    "upper_slots_x_cm": [round(-13.6 + k, 3) for k in range(17)],
    "handguard_slots_x_cm": [round(3.9 + k, 3) for k in range(32) if 3.9 + k < 35.8],
    "rear_sight_base_x_cm": (-9.6, -7.3), "front_sight_base_x_cm": (32.2, 34.4),
    "rear_sight_hinge_cm": (-8.3, 0.0, 4.52), "front_sight_hinge_cm": (33.4, 0.0, 4.52),
    "rear_sight_lug_top_cm": 4.82, "folded_leaf_z_cm": (4.37, 4.67),
    "irons_line_cm": 7.0, "ads_eye_x_cm": -14.9,
    "texture_dir": None,       # set by the caller (Art/Textures/Weapons/IV7)
}
RIFLE_OPTIC_OBJECTS = ("Optic", "OpticBolt", "OpticLensFront", "OpticLensRear", "OpticReticle")


def bore_to_rifle_m(x, y, z):
    """Bore-frame cm -> rifle object frame (m, origin at the grip hold point)."""
    from mathutils import Vector
    hx, hy, hz = IV7["hold_bore_cm"]
    return Vector(((x - hx) * 0.01, (y - hy) * 0.01, (z - hz) * 0.01))


def mount_offset_m(x_mount_cm):
    """Rifle-frame position (m) of an optic origin whose clamp front edge sits at bore-frame x on
    the rail top centre line."""
    return bore_to_rifle_m(x_mount_cm, 0.0, IV7["rail_top_cm"])


def on_slot(x_bore_cm, tol=1e-6):
    """True if a recoil lug at this bore-frame x sits on the centre of an IV-7 rail cross-slot."""
    slots = IV7["upper_slots_x_cm"] + IV7["handguard_slots_x_cm"]
    return any(abs(x_bore_cm - s) < tol for s in slots)


def clamp_section(y_out=1.3, z_top=0.75, gap=0.012, z_bot=-0.50):
    """Rail clamp cross-section (y, z) in the rail-top frame (cm), wrapping the IV-7 21 mm
    dovetail (half widths: 0.78 at the top, 1.06 at z -0.28, neck 0.80) with a small gap.  The jaw
    lips end 0.1 above the neck so the clamp never bottoms on the rail."""
    g = gap
    return [(y_out, z_top), (-y_out, z_top), (-y_out, z_bot), (-0.90 - g, z_bot), (-0.87 - g, z_bot + 0.03),
            (-1.06 - g, -0.28), (-0.78 - g, g), (0.78 + g, g), (1.06 + g, -0.28), (0.87 + g, z_bot + 0.03),
            (0.90 + g, z_bot), (y_out, z_bot)]


# =============================================================================
# 4. Materials
# =============================================================================

def _L():
    import ivlib
    return ivlib


def mat_glass_thin(name, tint=(0.030, 0.034, 0.040), alpha=0.12, coat=(0.55, 0.75, 1.0), spec=0.8,
                   rough=0.03, thin_film_nm=0.0):
    """Thin coated glass for a single-sheet lens / window: ALPHA BLENDED tint + specular reflection,
    NO transmission and NO refraction (a refraction pass renders a blurred, low-resolution copy of
    the scene and flickers when the view model moves).  Double sided (the sheet has no back
    face).  tint = dark base colour (the veil it adds is a slight neutral-density darkening),
    coat = colour of the reflection (anti-reflection / dichroic coating)."""
    L = _L()
    m, nb, bsdf = L._new_material(name)
    bsdf.inputs['Base Color'].default_value = (*tint, 1.0)
    bsdf.inputs['Alpha'].default_value = alpha
    bsdf.inputs['Roughness'].default_value = rough
    bsdf.inputs['Metallic'].default_value = 0.0
    bsdf.inputs['IOR'].default_value = 1.52
    bsdf.inputs['Specular IOR Level'].default_value = spec
    bsdf.inputs['Specular Tint'].default_value = (*coat, 1.0)
    bsdf.inputs['Transmission Weight'].default_value = 0.0
    if thin_film_nm > 0:
        bsdf.inputs['Thin Film Thickness'].default_value = thin_film_nm
        bsdf.inputs['Thin Film IOR'].default_value = 1.38
    m.surface_render_method = 'BLENDED'
    m.use_backface_culling = False
    m.diffuse_color = (*coat, alpha)
    m["iv_preset"] = "glass_thin"
    m["iv_alpha"] = alpha
    return m


def mat_reticle(name, base_png, emissive_png, strength=5.0):
    """Reticle plane: base RGBA (colour + straight alpha), emissive RGB, unlit look (no specular),
    alpha blended, ONE SIDED (back-face culled: invisible from the muzzle side = closed emitter).
    The runtime is expected to replace it with a parallax-free reticle shader (see OPTICS_spec)."""
    L = _L()
    m, nb, bsdf = L._new_material(name)
    uv = nb.node('ShaderNodeUVMap')
    uv.uv_map = "UVMap"
    tb = nb.node('ShaderNodeTexImage', interpolation='Linear', extension='EXTEND')
    tb.image = L.load_image(base_png, 'sRGB')
    tb.image.alpha_mode = 'STRAIGHT'
    tb.name = "T_Reticle"
    te = nb.node('ShaderNodeTexImage', interpolation='Linear', extension='EXTEND')
    te.image = L.load_image(emissive_png, 'sRGB')
    te.name = "T_ReticleEmissive"
    nb.links.new(uv.outputs[0], tb.inputs[0])
    nb.links.new(uv.outputs[0], te.inputs[0])
    nb.links.new(tb.outputs['Color'], bsdf.inputs['Base Color'])
    nb.links.new(tb.outputs['Alpha'], bsdf.inputs['Alpha'])
    nb.links.new(te.outputs['Color'], bsdf.inputs['Emission Color'])
    bsdf.inputs['Emission Strength'].default_value = strength
    bsdf.inputs['Roughness'].default_value = 1.0
    bsdf.inputs['Specular IOR Level'].default_value = 0.0
    bsdf.inputs['Metallic'].default_value = 0.0
    m.surface_render_method = 'BLENDED'
    m.use_backface_culling = True
    m["iv_preset"] = "reticle"
    return m


def cycles_one_sided(mat):
    """Render-time patch (never saved / exported): Cycles has no back-face culling, so mix the
    surface with a Transparent BSDF on back faces (matches the one-sided real-time material)."""
    nt = mat.node_tree
    if nt.nodes.get("IV_ONE_SIDED"):
        return mat
    out = nt.nodes["OUT"]
    src = out.inputs['Surface'].links[0].from_socket
    geo = nt.nodes.new('ShaderNodeNewGeometry')
    tr = nt.nodes.new('ShaderNodeBsdfTransparent')
    mix = nt.nodes.new('ShaderNodeMixShader')
    mix.name = "IV_ONE_SIDED"
    nt.links.new(geo.outputs['Backfacing'], mix.inputs[0])
    nt.links.new(src, mix.inputs[1])
    nt.links.new(tr.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], out.inputs['Surface'])
    return mat


def mat_black_interior(name, masks, base=(0.011, 0.011, 0.012), rough=0.8, seed=0):
    """Flocked / blackened interior of optic tubes and housings (dielectric, matte)."""
    L = _L()
    m, nb, bsdf = L._new_material(name)
    co = nb.coords('Object')
    edge, cav, ao = L._masks(nb, masks)
    n = nb.noise(co, 240.0, 2.0, 0.5, L._seed_w(seed))
    nb.set(bsdf.inputs['Base Color'], nb.ramp(n, [(0.3, base), (0.7, [c * 1.35 for c in base])]))
    nb.set(bsdf.inputs['Roughness'], nb.add(rough, nb.remap(n, 0.3, 0.7, -0.05, 0.05)))
    nb.set(bsdf.inputs['Metallic'], 0.0)
    m["iv_preset"] = "black_interior"
    return m


# =============================================================================
# 5. Mesh helpers
# =============================================================================

def _sheet_object(name, verts, faces, uvs, facing, col=None):
    """Open single-surface mesh; faces are wound so the normals point along +X*facing."""
    import bmesh
    from mathutils import Vector
    L = _L()
    bm = bmesh.new()
    bv = [bm.verts.new(v) for v in verts]
    bf = [bm.faces.new([bv[i] for i in f]) for f in faces]
    bm.normal_update()
    avg = Vector()
    for f in bf:
        avg += f.normal * f.calc_area()
    if avg.x * facing < 0:
        bmesh.ops.reverse_faces(bm, faces=bf)
    uvl = bm.loops.layers.uv.new("UVMap")
    for f in bm.faces:
        for lp in f.loops:
            lp[uvl].uv = uvs[lp.vert.index]
    ob = L.bm_to_object(bm, name, col, recalc=False)
    ob.data.shade_smooth()
    return ob


def lens_sheet(name, x, center_yz, radius, facing=-1, sag=0.0, segs=64, rings=6, col=None):
    """Single-surface lens disc perpendicular to X at x, optionally a spherical cap bulging `sag`
    towards the facing side (facing -1 = towards the eye / -X, +1 = towards the muzzle).
    UVs: the disc's bounding square maps to 0..1 with u to the viewer's right and v up, so a
    picture-in-picture render target can be applied to an ocular lens directly."""
    Rs = (radius ** 2 + sag ** 2) / (2 * sag) if sag > 0 else None

    def xoff(r):
        return 0.0 if Rs is None else facing * (math.sqrt(max(Rs * Rs - r * r, 0.0)) - (Rs - sag))
    cy, cz = center_yz
    verts = [(x + xoff(0.0), cy, cz)]
    for k in range(1, rings + 1):
        r = radius * (k / rings) ** 0.8
        for s in range(segs):
            a = 2 * math.pi * s / segs
            verts.append((x + xoff(r), cy + r * math.cos(a), cz + r * math.sin(a)))
    faces = [(0, 1 + s, 1 + (s + 1) % segs) for s in range(segs)]
    for k in range(rings - 1):
        a0, a1 = 1 + k * segs, 1 + (k + 1) * segs
        for s in range(segs):
            t = (s + 1) % segs
            faces.append((a0 + s, a1 + s, a1 + t, a0 + t))
    sgn = 1.0 if facing > 0 else -1.0          # viewer's right: +Y seen from the front, -Y from the rear
    uvs = [(0.5 + sgn * (v[1] - cy) / (2 * radius), 0.5 + (v[2] - cz) / (2 * radius)) for v in verts]
    return _sheet_object(name, verts, faces, uvs, facing, col)


def pane_sheet(name, x, center_yz, w, h, corner_r, facing=-1, seg=6, col=None):
    """Flat single-surface window pane (rounded rectangle) perpendicular to X at x."""
    L = _L()
    cy, cz = center_yz
    outline = L.rounded_rect(w, h, corner_r, seg, cx=cy, cy=cz)
    verts = [(x, cy, cz)] + [(x, u, v) for u, v in outline]
    n = len(outline)
    faces = [(0, 1 + s, 1 + (s + 1) % n) for s in range(n)]
    sgn = 1.0 if facing > 0 else -1.0
    uvs = [(0.5 + sgn * (v[1] - cy) / w, 0.5 + (v[2] - cz) / h) for v in verts]
    return _sheet_object(name, verts, faces, uvs, facing, col)


def reticle_plane(name, x_plane, center_yz, eye_x, reticle_meta, magnification=1.0, shape=None, col=None):
    """Reticle sheet on the sight axis at x_plane, facing the eye (-X).

    UV scale: seen from the eye point (x = eye_x on the axis) one texture unit subtends exactly one
    angular unit at the axis (x magnification for magnified optics = the apparent size behind the
    eyepiece); the mapping is gnomonic (UV linear in tan(angle)), which a flat sheet gives exactly.
    The sheet itself fills the aperture: shape = ('circle', r) or ('rect', half_y, half_z,
    corner_r).  Its UVs therefore run beyond 0..1 and the texture must be sampled clamp-to-edge
    (the border texels are transparent).  A runtime collimated reticle shader needs the whole
    aperture: with the eye off the axis the dot is drawn where the ray PARALLEL to the sight axis
    through the eye meets the sheet.  u runs to the shooter's right (-Y), v up (texture row 0 =
    top).  Returns (obj, tex_half) with tex_half = half size of the texture's field on the sheet."""
    d = x_plane - eye_x
    assert d > 0
    # gnomonic mapping: texture offset is linear in tan(angle) (reticle marks are linear at the
    # target, and a rectilinear eyepiece / game camera obeys tan(apparent) = M tan(true)); the
    # scale px_per_unit is exact at the axis.
    half_ang = 0.5 * reticle_meta["field_units"] * RAD_PER_UNIT[reticle_meta["units"]] * magnification
    tex_half = d * half_ang
    cy, cz = center_yz
    shape = shape or ('rect', tex_half, tex_half, 0.0)
    if shape[0] == 'circle':
        rr = shape[1]
        segs, rings = 48, 3
        verts = [(x_plane, cy, cz)]
        for k in range(1, rings + 1):
            r = rr * k / rings
            for s in range(segs):
                a = 2 * math.pi * s / segs
                verts.append((x_plane, cy + r * math.cos(a), cz + r * math.sin(a)))
        faces = [(0, 1 + s, 1 + (s + 1) % segs) for s in range(segs)]
        for k in range(rings - 1):
            a0, a1 = 1 + k * segs, 1 + (k + 1) * segs
            for s in range(segs):
                t = (s + 1) % segs
                faces.append((a0 + s, a1 + s, a1 + t, a0 + t))
    else:
        L = _L()
        _, hy, hz, cr = shape
        outline = L.rounded_rect(2 * hy, 2 * hz, cr, 6, cx=cy, cy=cz) if cr > 0 else \
            [(cy + hy, cz - hz), (cy + hy, cz + hz), (cy - hy, cz + hz), (cy - hy, cz - hz)]
        verts = [(x_plane, cy, cz)] + [(x_plane, u, v) for u, v in outline]
        n = len(outline)
        faces = [(0, 1 + s, 1 + (s + 1) % n) for s in range(n)]
    uvs = [(0.5 - (v[1] - cy) / (2 * tex_half), 0.5 + (v[2] - cz) / (2 * tex_half)) for v in verts]
    ob = _sheet_object(name, verts, faces, uvs, -1, col)
    ob["iv_reticle_tex_half"] = tex_half
    ob["iv_reticle_eye_distance"] = d
    return ob, tex_half


def make_socket(name, loc, rot=(0.0, 0.0, 0.0), size=0.01, col=None):
    import bpy
    o = bpy.data.objects.new(name, None)
    o.empty_display_type = 'ARROWS'
    o.empty_display_size = size
    o.location = loc
    o.rotation_euler = rot
    (col or bpy.context.scene.collection).objects.link(o)
    return o


def parent_keep(child, parent):
    child.parent = parent
    child.matrix_parent_inverse = parent.matrix_world.inverted()


def text_mesh(name, body, size, depth, M, col=None, align=('CENTER', 'CENTER')):
    """Mesh from Blender's built-in font (reads along +X, up +Y, extruded +-depth along Z), then
    transformed by the 4x4 matrix M (object data).  For engraving cutters."""
    import bpy
    L = _L()
    cu = bpy.data.curves.new(name, 'FONT')
    cu.body = body
    cu.size = size
    cu.extrude = depth
    cu.resolution_u = 2
    cu.align_x, cu.align_y = align
    ob = bpy.data.objects.new(name + "_c", cu)
    bpy.context.scene.collection.objects.link(ob)
    dg = bpy.context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(ob.evaluated_get(dg))
    bpy.data.objects.remove(ob)
    bpy.data.curves.remove(cu)
    mo = bpy.data.objects.new(name, me)
    (col or bpy.context.scene.collection).objects.link(mo)
    me.transform(M)
    L.weld(mo, 1e-4)
    return mo


# =============================================================================
# 6. Rifle (read-only) and mounting
# =============================================================================

def import_rifle(blend_path, texture_dir, collections=("IV7_Parts", "IV7_Rig")):
    """Append the IV-7 LOD0 parts + armature from its .blend (read-only: a temporary copy is
    loaded, the source is never opened for writing).  Image paths are re-pointed to texture_dir.
    Returns (armature, [mesh objects])."""
    import bpy
    import shutil
    import tempfile
    fd, tmp = tempfile.mkstemp(suffix=".blend", prefix="iv7_ro_")
    os.close(fd)
    shutil.copyfile(blend_path, tmp)
    before = set(bpy.data.objects)
    ims_before = set(bpy.data.images)
    try:
        with bpy.data.libraries.load(tmp, link=False) as (df, dt):
            dt.collections = [c for c in df.collections if c in collections]
        for c in dt.collections:
            if c is not None and c.name not in bpy.context.scene.collection.children:
                bpy.context.scene.collection.children.link(c)
    finally:
        os.remove(tmp)
    for im in set(bpy.data.images) - ims_before:
        if im.source == 'FILE' and im.filepath:
            p = os.path.join(texture_dir, os.path.basename(bpy.path.abspath(im.filepath)))
            if os.path.exists(p):
                im.filepath = p
                im.reload()
    new = [o for o in bpy.data.objects if o not in before]
    arm = next(o for o in new if o.type == 'ARMATURE')
    meshes = [o for o in new if o.type == 'MESH']
    for o in meshes:
        if o.name.split(".")[0] in RIFLE_OPTIC_OBJECTS:
            o.hide_render = True
            o.hide_viewport = True
    arm.hide_render = True
    return arm, meshes


def fold_iron_sights(arm, rear_deg=-90.0, front_deg=-90.0):
    """Fold the IV-7 flip-up sights: rotate bones rear_sight / front_sight about the weapon's
    lateral axis (world / bone-local +Y) through their hinge (bone head).  -90 deg = folded
    rearward (leaf lies flat towards the stock), matching the rifle's rig pose test."""
    import bpy
    from mathutils import Matrix
    for bn, ang in (("rear_sight", rear_deg), ("front_sight", front_deg)):
        pb = arm.pose.bones[bn]
        pb.rotation_mode = 'XYZ'
        head = pb.bone.head_local
        R = Matrix.Translation(head) @ Matrix.Rotation(math.radians(ang), 4, 'Y') @ Matrix.Translation(-head)
        pb.matrix = R @ pb.bone.matrix_local
    bpy.context.view_layer.update()


def world_tree(objs, depsgraph):
    """BVH tree of evaluated (posed) meshes in world space."""
    from mathutils.bvhtree import BVHTree
    verts, polys = [], []
    for o in objs:
        ev = o.evaluated_get(depsgraph)
        me = ev.to_mesh()
        M = o.matrix_world
        off = len(verts)
        verts.extend([M @ v.co for v in me.vertices])
        polys.extend([tuple(off + i for i in p.vertices) for p in me.polygons])
        ev.to_mesh_clear()
    return BVHTree.FromPolygons(verts, polys, epsilon=0.0), verts


def clearance_report(optic_objs, rifle_objs, depsgraph, probe=0.03):
    """Intersections (face pairs) and minimum distance between an optic and each rifle part."""
    t_opt, v_opt = world_tree(optic_objs, depsgraph)
    rep = {}
    for ro in rifle_objs:
        if ro.hide_render:
            continue
        t_r, _ = world_tree([ro], depsgraph)
        inter = len(t_opt.overlap(t_r))
        dmin = None
        for v in v_opt:
            hit = t_r.find_nearest(v, probe)
            if hit[0] is not None and (dmin is None or hit[3] < dmin):
                dmin = hit[3]
        if inter or dmin is not None:
            rep[ro.name] = {"intersecting_face_pairs": inter,
                            "min_distance_mm": None if dmin is None else round(dmin * 1000, 2)}
    return rep


# =============================================================================
# 7. Picture-in-picture composite (preview of the runtime scope rendering)
# =============================================================================

def pip_composite(main_png, zoom_png, reticle_meta, out_png, disc_center, disc_radius_px, true_fov_units,
                  vignette_start=0.80, vignette_strength=0.85, label=None):
    """Emulates the runtime magnified-optic path: the zoomed render (camera on the sight axis,
    field of view = the optic's true field over the ocular disc) is scaled into the ocular
    disc of the eye-point render, the reticle is drawn over it at its exact angular scale
    (true_fov_units across the disc diameter) and the eyebox vignette is applied."""
    from PIL import Image, ImageDraw, ImageFont
    main = np.asarray(Image.open(main_png).convert("RGB")).astype(np.float64) / 255.0
    H, W = main.shape[:2]
    D = int(math.ceil(2 * disc_radius_px)) + 4
    zoom = Image.open(zoom_png).convert("RGB").resize((D, D), Image.LANCZOS)
    zl = srgb_to_linear(np.asarray(zoom).astype(np.float64) / 255.0)
    # reticle resampled with premultiplied alpha (no fringes)
    r = reticle_meta["_render"]
    ppu = reticle_meta["px_per_unit"]
    col_lin = srgb_to_linear(np.array(reticle_meta["colour_srgb"]) / 255.0)
    pre = np.dstack([col_lin[None, None, :] * (r["t"] * r["alpha"])[..., None], r["alpha"][..., None]])
    scale = (2 * disc_radius_px / true_fov_units) / ppu            # disc px per texture px
    Nt = reticle_meta["size_px"][0]
    Ns = max(8, int(round(Nt * scale)))
    chans = [Image.fromarray(pre[..., k].astype(np.float32), "F").resize((Ns, Ns), Image.LANCZOS) for k in range(4)]
    pre_s = np.dstack([np.asarray(c) for c in chans])
    # place the scaled reticle centred on the disc canvas
    canvas = np.zeros((D, D, 4))
    c0 = D / 2.0 - Ns / 2.0
    ox = int(round(c0))
    sx0, sy0 = max(0, -ox), max(0, -ox)
    dx0, dy0 = max(0, ox), max(0, ox)
    w = min(Ns - sx0, D - dx0)
    canvas[dy0:dy0 + w, dx0:dx0 + w] = pre_s[sy0:sy0 + w, sx0:sx0 + w]
    a = np.clip(canvas[..., 3:4], 0, 1)
    img = zl * (1 - a) + np.clip(canvas[..., :3], 0, None)
    # eyebox vignette + disc mask
    yy, xx = np.mgrid[0:D, 0:D]
    rr = np.hypot(xx + 0.5 - D / 2.0, yy + 0.5 - D / 2.0) / disc_radius_px
    u = np.clip((rr - vignette_start) / (1 - vignette_start), 0, 1)
    img *= (1 - vignette_strength * (u * u * (3 - 2 * u)) ** 1.5)[..., None]
    mask = np.clip((1.0 - rr) * disc_radius_px + 0.5, 0, 1)[..., None]
    out = srgb_to_linear(main)
    cx, cy = disc_center
    x0 = int(round(cx - D / 2.0))
    y0 = int(round(cy - D / 2.0))
    sub = out[y0:y0 + D, x0:x0 + D]
    sub[:] = sub * (1 - mask) + img * mask
    res = Image.fromarray(np.clip(np.round(linear_to_srgb(out) * 255), 0, 255).astype(np.uint8), "RGB")
    if label:
        dr = ImageDraw.Draw(res)
        dr.text((16, 12), label, fill=(245, 245, 245), font=ImageFont.truetype(FONT_REG, 20),
                stroke_width=2, stroke_fill=(20, 20, 20))
    res.save(out_png)
    return out_png


# =============================================================================
# 8. Measurements, audits, render scene
# =============================================================================

def reticle_metrics(meta):
    """Crispness and angular-scale numbers of a rasterised reticle (from Reticle.save's render).
    - edge_10_90_px: width of the alpha ramp across the lit feature nearest the axis, measured on
      the row through the axis (exact-coverage AA gives <= ~1 px; blur would widen it)
    - lit/etch coverage areas converted to angular areas
    - drawn extent in units."""
    r = meta["_render"]
    a = r["alpha"]
    N = a.shape[0]
    ppu = meta["px_per_unit"]
    c = N // 2
    out = {"px_per_unit": ppu, "units": meta["units"], "size_px": N}
    # edge ramp on the centre row, walking right from the centre until the first fall 0.9 -> 0.1
    row = a[c - 1:c + 1].mean(axis=0)            # the axis lies between rows c-1 and c
    ramps = []
    j = c
    while j < N - 2 and len(ramps) < 3:
        if row[j] >= 0.9 and row[j + 1] < 0.9:
            k = j
            while k < N - 1 and row[k] > 0.1:
                k += 1
            # sub-pixel interpolation of the 0.9 and 0.1 crossings
            def cross(i0, lvl):
                i = i0
                while i < N - 1 and not (row[i] >= lvl > row[i + 1]):
                    i += 1
                return i + (row[i] - lvl) / max(row[i] - row[i + 1], 1e-9)
            ramps.append(round(cross(j, 0.1) - cross(j, 0.9), 3))
            j = k
        j += 1
    out["edge_10_90_px_first_edges"] = ramps
    out["lit_area_units2"] = round(float(r["cov_lit"].sum()) / ppu ** 2, 4)
    out["etch_area_units2"] = round(float(r["cov_etch"].sum()) / ppu ** 2, 4)
    out["border_alpha_max"] = float(max(a[0].max(), a[-1].max(), a[:, 0].max(), a[:, -1].max()))
    # symmetry about the axis (centring): alpha centroid of the lit layer
    L_ = r["cov_lit"]
    if L_.sum() > 0:
        ys, xs = np.mgrid[0:N, 0:N]
        cx = float((L_ * (xs + 0.5)).sum() / L_.sum())
        cy = float((L_ * (ys + 0.5)).sum() / L_.sum())
        out["lit_centroid_offset_px"] = [round(cx - N / 2, 4), round(cy - N / 2, 4)]
    return out


def glb_json(path):
    """The JSON chunk of a .glb (or a .gltf file)."""
    import struct
    with open(path, "rb") as f:
        data = f.read()
    if path.lower().endswith(".gltf"):
        return json.loads(data.decode("utf8"))
    magic, ver, length = struct.unpack_from("<III", data, 0)
    assert magic == 0x46546C67, "not a GLB"
    clen, ctype = struct.unpack_from("<II", data, 12)
    return json.loads(data[20:20 + clen].decode("utf8"))


def gltf_material_audit(path):
    """Materials in a glTF/GLB: alpha mode, double sided, factors, textures, extensions, and the
    wrap mode of every sampler.  Flags any transmission / volume / refraction extension."""
    g = glb_json(path)
    samplers = g.get("samplers", [])
    tex = g.get("textures", [])
    imgs = g.get("images", [])

    def tinfo(ti):
        if ti is None:
            return None
        t = tex[ti["index"]]
        s = samplers[t["sampler"]] if "sampler" in t else {}
        im = imgs[t["source"]] if "source" in t else {}
        return {"image": im.get("name") or im.get("uri"), "wrapS": s.get("wrapS", 10497),
                "wrapT": s.get("wrapT", 10497), "minFilter": s.get("minFilter"), "texCoord": ti.get("texCoord", 0)}
    out = {}
    bad = []
    for m in g.get("materials", []):
        pbr = m.get("pbrMetallicRoughness", {})
        ext = m.get("extensions", {})
        d = {"alphaMode": m.get("alphaMode", "OPAQUE"), "doubleSided": m.get("doubleSided", False),
             "baseColorFactor": pbr.get("baseColorFactor"), "roughnessFactor": pbr.get("roughnessFactor"),
             "metallicFactor": pbr.get("metallicFactor"), "emissiveFactor": m.get("emissiveFactor"),
             "baseColorTexture": tinfo(pbr.get("baseColorTexture")),
             "emissiveTexture": tinfo(m.get("emissiveTexture")),
             "normalTexture": tinfo(m.get("normalTexture")),
             "occlusionTexture": tinfo(m.get("occlusionTexture")),
             "metallicRoughnessTexture": tinfo(pbr.get("metallicRoughnessTexture")),
             "extensions": sorted(ext.keys())}
        for k in ext:
            if any(w in k for w in ("transmission", "volume", "refraction", "dispersion", "diffuse_transmission")):
                bad.append(f"{m.get('name')}: {k}")
        out[m.get("name")] = d
    return {"materials": out, "transmission_like_extensions": bad,
            "extensionsUsed": g.get("extensionsUsed", []),
            "nodes": [n.get("name") for n in g.get("nodes", [])]}


def blend_transmission_audit(materials):
    """Principled BSDF transmission / refraction settings of Blender materials."""
    rep = {}
    for m in materials:
        if not (m and m.use_nodes):
            continue
        for n in m.node_tree.nodes:
            if n.type == 'BSDF_PRINCIPLED':
                rep[m.name] = {"transmission_weight": round(n.inputs['Transmission Weight'].default_value, 6),
                               "transmission_linked": n.inputs['Transmission Weight'].is_linked,
                               "alpha": round(n.inputs['Alpha'].default_value, 4),
                               "alpha_linked": n.inputs['Alpha'].is_linked,
                               "render_method": getattr(m, "surface_render_method", None),
                               "backface_culling": m.use_backface_culling}
            if n.type in ('BSDF_GLASS', 'BSDF_REFRACTION', 'BSDF_TRANSLUCENT'):
                rep.setdefault(m.name, {})["forbidden_node"] = n.type
    return rep


def pose_bone_fold(arm, bone, deg_about_local_y):
    """The DOCUMENTED way to fold a sight leaf: pose-bone Euler rotation about the bone's local Y
    (IV-7 bones are world aligned: local X forward, Y left, Z up)."""
    import bpy
    pb = arm.pose.bones[bone]
    pb.rotation_mode = 'XYZ'
    pb.rotation_euler = (0.0, math.radians(deg_about_local_y), 0.0)
    bpy.context.view_layer.update()


def evaluated_bbox(obj, depsgraph):
    ev = obj.evaluated_get(depsgraph)
    me = ev.to_mesh()
    M = obj.matrix_world
    co = np.array([tuple(M @ v.co) for v in me.vertices])
    ev.to_mesh_clear()
    return co.min(0), co.max(0)


def range_scene(eye, axis_dir=(1.0, 0.0, 0.0), ground_drop=1.55, distances=(25, 50, 100, 200, 300, 400),
                sun=(38.0, 222.0), col=None):
    """Outdoor test range for through-sight renders: Nishita sky + sun, a large ground plane
    `ground_drop` below the eye, torso-sized target boards centred ON the sight axis at each
    distance (white board, black rings, a black centre dot), plus a few trees for depth cues.
    Deterministic.  Returns created objects."""
    import bpy
    L = _L()
    from mathutils import Vector
    eye = Vector(eye)
    ax = Vector(axis_dir).normalized()
    col = col or L.collection("IV_Range")
    L.world_sky(sun_elevation=sun[0], sun_rotation=sun[1], strength=0.35, background_strength=0.6)
    L.add_sun(elevation=sun[0], rotation=sun[1], strength=3.2, angle=0.55)
    objs = []
    gz = eye.z - ground_drop
    # ground
    m, nb, bsdf = L._new_material("IV_RangeGround")
    co = nb.coords('Object')
    n1 = nb.noise(co, 0.35, 4.0, 0.6, 3.0)
    n2 = nb.noise(co, 6.0, 3.0, 0.5, 7.0)
    col_g = nb.ramp(nb.add(nb.mul(n1, 0.7), nb.mul(n2, 0.3)),
                    [(0.35, (0.045, 0.075, 0.018)), (0.55, (0.085, 0.100, 0.030)), (0.75, (0.14, 0.12, 0.06))])
    nb.set(bsdf.inputs['Base Color'], col_g)
    bsdf.inputs['Roughness'].default_value = 0.95
    g = L.box("IV_Ground", eye.x - 50, eye.x + 2500, -1200, 1200, gz - 1.0, gz)
    g.data.materials.append(m)
    L.link_to(g, col)
    objs.append(g)
    # target boards
    mw, _, bw = L._new_material("IV_TargetWhite")
    bw.inputs['Base Color'].default_value = (0.8, 0.8, 0.78, 1)
    bw.inputs['Roughness'].default_value = 0.8
    mk, _, bk = L._new_material("IV_TargetBlack")
    bk.inputs['Base Color'].default_value = (0.012, 0.012, 0.012, 1)
    bk.inputs['Roughness'].default_value = 0.7
    mp, _, bp = L._new_material("IV_Post")
    bp.inputs['Base Color'].default_value = (0.20, 0.13, 0.07, 1)
    # only the 100 m board sits ON the sight axis; the others are staggered sideways so the near
    # boards do not hide the far ones
    lateral = {25: 1.4, 50: -2.2, 100: 0.0, 200: 3.5, 300: -6.0, 400: 8.0}
    for D in distances:
        p = eye + ax * D + Vector((0.0, lateral.get(D, 0.0), 0.0))
        w, h = 0.46, 0.70
        b = L.box(f"IV_Target_{D}", p.x, p.x + 0.02, p.y - w / 2, p.y + w / 2, p.z - h / 2, p.z + h / 2)
        b.data.materials.append(mw)
        L.link_to(b, col)
        rings = []
        for k, rr in enumerate((0.20, 0.15, 0.10, 0.05)):
            ring = L.lathe(f"ring{D}_{k}", [(p.x - 0.001 - 0.0002 * k, rr - 0.008), (p.x - 0.001 - 0.0002 * k, rr + 0.008),
                                            (p.x - 0.0005, rr + 0.008), (p.x - 0.0005, rr - 0.008)], 64, 'X',
                           center=(p.y, p.z), closed=True)
            rings.append(ring)
        dot = L.cyl(f"dot{D}", 0.02, p.x - 0.002, p.x - 0.0005, 'X', center=(p.y, p.z), segs=32)
        rings.append(dot)
        for rgo in rings:
            rgo.data.materials.append(mk)
            L.link_to(rgo, col)
        post = L.box(f"IV_Post_{D}", p.x + 0.02, p.x + 0.07, p.y - 0.025, p.y + 0.025, gz, p.z - h / 2)
        post.data.materials.append(mp)
        L.link_to(post, col)
        objs += [b, post] + rings
    # trees (cones + trunks) off the axis, deterministic positions
    mt, _, bt = L._new_material("IV_Tree")
    bt.inputs['Base Color'].default_value = (0.03, 0.06, 0.025, 1)
    bt.inputs['Roughness'].default_value = 0.9
    rng = np.random.default_rng(7)
    for i in range(40):
        D = float(rng.uniform(40, 700))
        side = float(rng.choice([-1, 1])) * float(rng.uniform(6, 0.35 * D + 8))
        p = eye + ax * D + Vector((0, side, 0))
        hgt = float(rng.uniform(6, 14))
        cone = L.lathe(f"IV_Tree_{i}", [(gz + 1.5, 0.0), (gz + 1.5, hgt * 0.22), (gz + hgt, 0.0)], 10, 'Z',
                       center=(p.x, p.y))
        cone.data.materials.append(mt)
        L.link_to(cone, col)
        objs.append(cone)
    return objs


# =============================================================================
# 9. Export jobs (clean subprocess)
# =============================================================================
# Static optic exports.  Every optic is exported on its own from optics.blend:
#   FBX (Unreal): file in centimetres with NO node scale (geometry and empty locations are
#     multiplied by 100 at scene unit scale 0.01, like the IV-7 export in ivlib), axes as ivlib's
#     FBX_UNREAL_OPTS, object types MESH + EMPTY.  Sockets are empties named "SOCKET_<socket>"
#     parented to the body mesh (Unreal's static-mesh socket convention; the socket name in
#     Unreal is the part after SOCKET_, e.g. "socket_eye").  Materials reference BaseColor and
#     the *_Normal_DX.png map by relative path only.
#   GLB (web): metres, Y-up (the exporter converts), sockets are plain nodes named
#     "socket_<name>", textures embedded.

def _prep_optic_scene(job):
    import bpy
    bpy.ops.wm.open_mainfile(filepath=job["blend"])
    keep = set(job["objects"])
    for o in list(bpy.data.objects):
        if o.name not in keep:
            bpy.data.objects.remove(o, do_unlink=True)
    objs = [bpy.data.objects[n] for n in job["objects"]]
    lc = bpy.context.view_layer.layer_collection

    def _unexclude(l):
        l.exclude = False
        l.hide_viewport = False
        for ch in l.children:
            _unexclude(ch)
    _unexclude(lc)
    for o in objs:
        o.hide_set(False)
        o.hide_viewport = False
        o.hide_render = False
        o.hide_select = False
    for old, new in job.get("rename", {}).items():
        bpy.data.objects[old].name = new
    for im in bpy.data.images:
        b = os.path.basename(bpy.path.abspath(im.filepath)) if im.filepath else ""
        if b in job.get("image_map", {}):
            im.filepath = job["image_map"][b]
            im.reload()
    bpy.context.view_layer.update()
    return objs


def _job_export_optic(job):
    import bpy
    from mathutils import Matrix
    L = _L()
    objs = _prep_optic_scene(job)
    root = next(o for o in objs if o.parent is None)
    fmt = job["format"]
    os.makedirs(os.path.dirname(job["path"]), exist_ok=True)
    if fmt == "FBX":
        # bake centimetres: unparent (keep world), scale geometry / locations x100, re-parent
        mw = {o.name: o.matrix_world.copy() for o in objs}
        for o in objs:
            o.parent = None
        for o in objs:
            M = mw[o.name]
            loc, rot, sca = M.decompose()
            if o.type == 'MESH':
                o.data.transform(Matrix.Diagonal((*sca, 1.0)) * 1.0)   # bake any object scale
                o.data.transform(Matrix.Scale(100.0, 4))
                o.data.update()
            else:
                o.empty_display_size *= 100.0
            o.matrix_world = Matrix.Translation(loc * 100.0) @ rot.to_matrix().to_4x4()
        bpy.context.view_layer.update()
        for o in objs:
            if o is not root:
                w = o.matrix_world.copy()
                o.parent = root
                o.matrix_parent_inverse = root.matrix_world.inverted()
                o.matrix_world = w
        for o in objs:
            if o.type == 'EMPTY':
                o.name = "SOCKET_" + o.name
        bpy.context.scene.unit_settings.scale_length = 0.01
        bpy.context.view_layer.update()
        # Unreal convention: point the FBX normal-map reference at *_Normal_DX.png
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
        import io_scene_fbx.export_fbx_bin as _efb
        _orig = _efb._gen_vid_path

        def _rel_only(img, scene_data):
            a, r = _orig(img, scene_data)
            return r, r
        _efb._gen_vid_path = _rel_only
        L.select(objs, root)
        opts = dict(L.FBX_UNREAL_OPTS)
        opts["object_types"] = {'MESH', 'EMPTY'}
        bpy.ops.export_scene.fbx(filepath=job["path"], use_selection=True, **opts)
    else:
        L.select(objs, root)
        opts = dict(L.GLB_OPTS)
        opts["export_skins"] = False
        bpy.ops.export_scene.gltf(filepath=job["path"], use_selection=True, **opts)
    return {"ok": True, "path": job["path"], "bytes": os.path.getsize(job["path"])}


def _job_reimport_optic(job):
    """Re-import an exported FBX / GLB into an empty scene; report meshes, empties (world
    positions in metres after the importer's conversion), materials, images and bounds."""
    import bpy
    bpy.ops.wm.read_factory_settings(use_empty=True)
    p = job["path"]
    if p.lower().endswith(".fbx"):
        bpy.ops.import_scene.fbx(filepath=p, use_custom_normals=True)
    else:
        bpy.ops.import_scene.gltf(filepath=p)
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
    empties = [o for o in bpy.context.scene.objects if o.type == 'EMPTY']
    mn = np.array([1e9] * 3)
    mx = np.array([-1e9] * 3)
    tris = 0
    per_mesh = {}
    for o in meshes:
        ev = o.evaluated_get(dg)
        me = ev.to_mesh()
        me.calc_loop_triangles()
        nt = len(me.loop_triangles)
        tris += nt
        co = np.empty(len(me.vertices) * 3)
        me.vertices.foreach_get("co", co)
        co = co.reshape(-1, 3)
        M = np.array(o.matrix_world)
        w = co @ M[:3, :3].T + M[:3, 3]
        if len(w):
            mn = np.minimum(mn, w.min(0))
            mx = np.maximum(mx, w.max(0))
        per_mesh[o.name] = {"tris": nt, "uv_layers": len(me.uv_layers),
                            "materials": [m.name if m else None for m in o.data.materials]}
        ev.to_mesh_clear()
    mats = {}
    for o in meshes:
        for m in o.data.materials:
            if m and m.name not in mats:
                ims = []
                bs = {}
                if m.use_nodes:
                    for n in m.node_tree.nodes:
                        if n.type == 'TEX_IMAGE' and n.image:
                            ip = bpy.path.abspath(n.image.filepath) if n.image.filepath else ""
                            ims.append({"name": n.image.name, "size": list(n.image.size),
                                        "ok": bool(n.image.packed_file) or (bool(ip) and os.path.exists(ip))})
                        if n.type == 'BSDF_PRINCIPLED':
                            bs = {"transmission": round(n.inputs['Transmission Weight'].default_value, 5),
                                  "alpha": round(n.inputs['Alpha'].default_value, 4),
                                  "alpha_linked": n.inputs['Alpha'].is_linked}
                mats[m.name] = {"images": ims, "bsdf": bs}
    return {"ok": True, "path": p, "meshes": sorted(o.name for o in meshes), "per_mesh": per_mesh, "tris": tris,
            "empties": {o.name: [round(v, 5) for v in o.matrix_world.translation] for o in empties},
            "empty_axes_x": {o.name: [round(v, 5) for v in (o.matrix_world.to_3x3() @ __import__('mathutils').Vector((1, 0, 0))).normalized()] for o in empties},
            "empty_parents": {o.name: (o.parent.name if o.parent else None) for o in empties},
            "bbox_min": [round(float(v), 5) for v in mn], "bbox_max": [round(float(v), 5) for v in mx],
            "materials": mats}


def run_job(job, timeout=900):
    import subprocess
    import tempfile
    fd, path = tempfile.mkstemp(suffix=".json", prefix="ivoptjob_")
    with os.fdopen(fd, "w") as f:
        json.dump(job, f)
    p = subprocess.run([sys.executable, os.path.abspath(__file__), "--job", path], capture_output=True,
                       text=True, timeout=timeout)
    os.remove(path)
    for line in p.stdout.splitlines()[::-1]:
        if line.startswith("IVOPT_RESULT "):
            return json.loads(line[len("IVOPT_RESULT "):])
    raise RuntimeError(f"ivoptics job failed ({job.get('type')}):\n{p.stdout[-3000:]}\n{p.stderr[-3000:]}")


def export_optic(blend, objects, path, rename=None, image_map=None):
    fmt = "FBX" if path.lower().endswith(".fbx") else "GLB"
    return run_job({"type": "export_optic", "format": fmt, "blend": blend, "objects": list(objects),
                    "path": path, "rename": rename or {}, "image_map": image_map or {}})


def reimport_optic(path):
    return run_job({"type": "reimport_optic", "path": path})


def _job_main(path):
    with open(path) as f:
        job = json.load(f)
    t = job["type"]
    if t == "export_optic":
        res = _job_export_optic(job)
    elif t == "reimport_optic":
        res = _job_reimport_optic(job)
    else:
        raise ValueError(t)
    print("IVOPT_RESULT " + json.dumps(res), flush=True)


if __name__ == "__main__":
    if "--job" in sys.argv:
        sys.path.insert(0, HERE)
        _job_main(sys.argv[sys.argv.index("--job") + 1])
