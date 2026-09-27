"""
ivglb.py -- minimal, deterministic glTF 2.0 binary (GLB) writer and mesh buffers for the web export of the level
(Tools/level/export_web_level.py).  numpy only, no Blender.

Geometry is authored in the level frame (Blender: metres, +X east, +Y north, +Z up) and converted to the glTF /
three.js frame on write: (x, y, z)_gltf = (x, z, -y)_level.  That map is a proper rotation, so the winding
(counter-clockwise seen from outside) is kept.

MeshBuf   indexed triangles with position, normal, uv (metres / tile), colour (RGBA u8) and a packed light attribute
          (_IVLIGHT: sky visibility + one-bounce sunlight, u8 normalised) filled later by the bake.
ColBuf    positions + indices only (collision).
GLB       buffer views / accessors / meshes / nodes / materials / textures, EXT_mesh_gpu_instancing, extras.
"""
import json
import math
import struct

import numpy as np

ARRAY_BUFFER = 34962
ELEMENT_ARRAY_BUFFER = 34963
FLOAT = 5126
BYTE = 5120
UBYTE = 5121
USHORT = 5123
UINT = 5125

_TYPE_N = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def to_gltf(p):
    """level frame (x, y, z_up) -> glTF (x, z, -y); works on (..., 3) arrays."""
    p = np.asarray(p, np.float64)
    return np.stack([p[..., 0], p[..., 2], -p[..., 1]], axis=-1)


def face_uv(P, n, tile=1.0):
    """UVs (metres / tile) for points P (k, 3) on a planar face with normal n: horizontal faces map (x, y), others the
    horizontal tangent and the in-plane up direction (walls: along the wall / height; roofs: along the eave / slope)."""
    n = np.asarray(n, float)
    if abs(n[2]) > 0.9:
        u = P[:, 0]
        v = P[:, 1]
    else:
        t = np.array([-n[1], n[0], 0.0])
        tl = np.linalg.norm(t)
        t = t / tl if tl > 1e-9 else np.array([1.0, 0.0, 0.0])
        b = np.cross(n, t)
        if b[2] < 0:
            b = -b
        u = P @ t
        v = P @ b
    return np.stack([u, v], axis=1) / tile


class MeshBuf:
    """Indexed triangle soup with per-vertex attributes (level frame)."""

    def __init__(self, name, tile=1.0):
        self.name = name
        self.tile = tile
        self.P = []
        self.N = []
        self.UV = []
        self.C = []
        self.I = []
        self.n = 0

    def add(self, P, N, UV, C, I):
        P = np.asarray(P, np.float64).reshape(-1, 3)
        k = len(P)
        if k == 0:
            return
        self.P.append(P)
        self.N.append(np.broadcast_to(np.asarray(N, np.float64), (k, 3)).copy())
        self.UV.append(np.asarray(UV, np.float64).reshape(k, 2))
        C = np.asarray(C, np.float64)
        self.C.append(np.broadcast_to(C, (k, 4)).copy())
        self.I.append(np.asarray(I, np.int64).reshape(-1, 3) + self.n)
        self.n += k

    def poly(self, pts, color=(1, 1, 1, 1), tile=None, n=None):
        """planar convex polygon (CCW seen from the side the normal points to), fan triangulated, flat normal."""
        P = np.asarray(pts, np.float64)
        if len(P) < 3:
            return
        if n is None:
            n = np.zeros(3)
            for i in range(1, len(P) - 1):
                n += np.cross(P[i] - P[0], P[i + 1] - P[0])
            ln = np.linalg.norm(n)
            if ln < 1e-12:
                return
            n = n / ln
        I = [(0, i, i + 1) for i in range(1, len(P) - 1)]
        self.add(P, n, face_uv(P, n, tile or self.tile), color, I)

    def quad_grid(self, a, b, c, d, max_edge, color=(1, 1, 1, 1), tile=None):
        """planar quad a-b-c-d (CCW) subdivided into a grid with edges <= max_edge (vertex lighting resolution)."""
        a, b, c, d = (np.asarray(v, np.float64) for v in (a, b, c, d))
        nu = max(1, int(math.ceil(max(np.linalg.norm(b - a), np.linalg.norm(c - d)) / max_edge - 1e-9)))
        nv = max(1, int(math.ceil(max(np.linalg.norm(d - a), np.linalg.norm(c - b)) / max_edge - 1e-9)))
        if nu == 1 and nv == 1:
            self.poly([a, b, c, d], color, tile)
            return
        n = np.cross(b - a, d - a) + np.cross(d - c, b - c)
        ln = np.linalg.norm(n)
        if ln < 1e-12:
            return
        n = n / ln
        s = np.linspace(0, 1, nu + 1)
        t = np.linspace(0, 1, nv + 1)
        S, Tt = np.meshgrid(s, t)
        S = S.ravel()[:, None]
        Tt = Tt.ravel()[:, None]
        P = (1 - S) * (1 - Tt) * a + S * (1 - Tt) * b + S * Tt * c + (1 - S) * Tt * d
        I = []
        for j in range(nv):
            for i in range(nu):
                v0 = j * (nu + 1) + i
                v1 = v0 + 1
                v3 = v0 + nu + 1
                v2 = v3 + 1
                I.append((v0, v1, v2))
                I.append((v0, v2, v3))
        self.add(P, n, face_uv(P, n, tile or self.tile), color, I)

    def arrays(self):
        if not self.P:
            return None
        return (np.concatenate(self.P), np.concatenate(self.N), np.concatenate(self.UV), np.concatenate(self.C),
                np.concatenate(self.I))


class ColBuf:
    """Collision triangles (positions + indices), level frame."""

    def __init__(self, name):
        self.name = name
        self.P = []
        self.I = []
        self.n = 0

    def add(self, P, I):
        P = np.asarray(P, np.float64).reshape(-1, 3)
        if len(P) == 0:
            return
        self.P.append(P)
        self.I.append(np.asarray(I, np.int64).reshape(-1, 3) + self.n)
        self.n += len(P)

    def poly(self, pts):
        P = np.asarray(pts, np.float64)
        if len(P) >= 3:
            self.add(P, [(0, i, i + 1) for i in range(1, len(P) - 1)])

    def arrays(self):
        if not self.P:
            return None
        return np.concatenate(self.P), np.concatenate(self.I)


def srgb_to_linear(c):
    c = np.asarray(c, np.float64)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def hex_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


class GLB:
    def __init__(self, generator="IRON VALLEY Tools/level/export_web_level.py"):
        self.bin = bytearray()
        self.bufferViews = []
        self.accessors = []
        self.meshes = []
        self.nodes = []
        self.materials = []
        self.textures = []
        self.images = []
        self.samplers = []
        self.extensionsUsed = set()
        self.extras = {}
        self.generator = generator

    # ------------------------------------------------------------------ raw data
    def _view(self, data, target=None, stride=None):
        while len(self.bin) % 4:
            self.bin.append(0)
        off = len(self.bin)
        self.bin += data
        v = {"buffer": 0, "byteOffset": off, "byteLength": len(data)}
        if target:
            v["target"] = target
        if stride:
            v["byteStride"] = stride
        self.bufferViews.append(v)
        return len(self.bufferViews) - 1

    def accessor(self, arr, typ, ctype, normalized=False, target=ARRAY_BUFFER, minmax=False):
        arr = np.ascontiguousarray(arr)
        dt = {FLOAT: np.float32, BYTE: np.int8, UBYTE: np.uint8, USHORT: np.uint16, UINT: np.uint32}[ctype]
        a = arr.astype(dt, copy=False)
        n = _TYPE_N[typ]
        count = a.size // n
        stride = None
        if target == ARRAY_BUFFER and a.itemsize * n % 4:
            # vertex attribute elements must be 4-byte aligned: pad each element
            per = a.itemsize * n
            pad = (4 - per % 4) % 4
            rows = a.reshape(count, n)
            buf = np.zeros((count, (per + pad) // a.itemsize), dt)
            buf[:, :n] = rows
            data = buf.tobytes()
            stride = per + pad
        else:
            data = a.tobytes()
        view = self._view(data, target, stride)
        acc = {"bufferView": view, "componentType": ctype, "count": int(count), "type": typ}
        if normalized:
            acc["normalized"] = True
        if minmax:
            r = a.reshape(count, n).astype(np.float64)
            acc["min"] = [float(v) for v in r.min(axis=0)]
            acc["max"] = [float(v) for v in r.max(axis=0)]
        self.accessors.append(acc)
        return len(self.accessors) - 1

    def raw_accessor(self, arr, typ, ctype):
        """non-vertex data (e.g. a raster) referenced from extras: no target."""
        return self.accessor(arr, typ, ctype, target=None)

    # ------------------------------------------------------------------ materials / textures
    def add_image(self, data, mime):
        view = self._view(data)
        self.images.append({"bufferView": view, "mimeType": mime})
        return len(self.images) - 1

    def add_texture(self, image, wrap=10497, mag=9729, minf=9987):
        key = (wrap, mag, minf)
        s = None
        for i, sm in enumerate(self.samplers):
            if (sm["wrapS"], sm["magFilter"], sm["minFilter"]) == key:
                s = i
        if s is None:
            self.samplers.append({"wrapS": wrap, "wrapT": wrap, "magFilter": mag, "minFilter": minf})
            s = len(self.samplers) - 1
        self.textures.append({"source": image, "sampler": s})
        return len(self.textures) - 1

    def add_material(self, m):
        self.materials.append(m)
        return len(self.materials) - 1

    # ------------------------------------------------------------------ meshes / nodes
    def add_mesh(self, name, primitives, extras=None):
        m = {"name": name, "primitives": primitives}
        if extras:
            m["extras"] = extras
        self.meshes.append(m)
        return len(self.meshes) - 1

    def add_node(self, node):
        self.nodes.append(node)
        return len(self.nodes) - 1

    def mesh_from_buf(self, buf, material, light=None, extras=None, index_type=None):
        """MeshBuf -> glTF mesh (attributes converted to the glTF frame). light: (k, 4) u8 packed light or None."""
        a = buf.arrays()
        if a is None:
            return None
        P, N, UV, C, I = a
        attrs = {
            "POSITION": self.accessor(to_gltf(P), "VEC3", FLOAT, minmax=True),
            "NORMAL": self.accessor(to_gltf(N), "VEC3", FLOAT),
            "TEXCOORD_0": self.accessor(UV, "VEC2", FLOAT),
            # vertex tints are authored in sRGB; glTF COLOR_0 is linear
            "COLOR_0": self.accessor(np.clip(np.round(np.column_stack([srgb_to_linear(C[:, :3]), C[:, 3:4]]) * 255), 0, 255), "VEC4", UBYTE,
                                     normalized=True),
        }
        if light is not None:
            attrs["_IVLIGHT"] = self.accessor(light, "VEC4", UBYTE, normalized=True)
        it = index_type or (USHORT if len(P) < 65536 else UINT)
        prim = {"attributes": attrs, "indices": self.accessor(I.ravel(), "SCALAR", it, target=ELEMENT_ARRAY_BUFFER), "mode": 4}
        if material is not None:
            prim["material"] = material
        return self.add_mesh(buf.name, [prim], extras)

    def mesh_positions(self, name, P, I, extras=None, attrs_extra=None, material=None):
        attrs = {"POSITION": self.accessor(to_gltf(P), "VEC3", FLOAT, minmax=True)}
        if attrs_extra:
            attrs.update(attrs_extra)
        it = USHORT if len(P) < 65536 else UINT
        prim = {"attributes": attrs, "indices": self.accessor(np.asarray(I).ravel(), "SCALAR", it, target=ELEMENT_ARRAY_BUFFER), "mode": 4}
        if material is not None:
            prim["material"] = material
        return self.add_mesh(name, [prim], extras)

    # ------------------------------------------------------------------ write
    def write(self, path, scene_nodes):
        gl = {
            "asset": {"version": "2.0", "generator": self.generator},
            "scene": 0,
            "scenes": [{"nodes": list(scene_nodes)}],
            "nodes": self.nodes,
            "meshes": self.meshes,
            "accessors": self.accessors,
            "bufferViews": self.bufferViews,
            "buffers": [{"byteLength": len(self.bin)}],
        }
        if self.materials:
            gl["materials"] = self.materials
        if self.textures:
            gl["textures"] = self.textures
            gl["images"] = self.images
            gl["samplers"] = self.samplers
        if self.extensionsUsed:
            gl["extensionsUsed"] = sorted(self.extensionsUsed)
        if self.extras:
            gl["asset"]["extras"] = self.extras
        js = json.dumps(gl, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        while len(js) % 4:
            js += b" "
        binb = bytes(self.bin)
        while len(binb) % 4:
            binb += b"\0"
        total = 12 + 8 + len(js) + 8 + len(binb)
        with open(path, "wb") as f:
            f.write(struct.pack("<III", 0x46546C67, 2, total))
            f.write(struct.pack("<II", len(js), 0x4E4F534A))
            f.write(js)
            f.write(struct.pack("<II", len(binb), 0x004E4942))
            f.write(binb)
        return total
