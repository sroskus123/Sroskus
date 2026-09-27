#!/usr/bin/env python3
"""IRON VALLEY: web variants of the Blender exports (reproducible, no network, no Blender needed).

Reads the canonical exports in Art/Export/GLB and Art/Textures/Optics and writes what the browser build
ships in Web/public/assets:

  weapons/IV7_Carbine.glb            rifle (textures <= 2048)
  optics/<file>.glb                  optic LOD0, first person (body textures <= 1024, reticles lossless)
  optics/<file>_LOD1.glb             optic LOD1, third person (textures <= 512)
  optics/<ID>_reticle_sdf.png        reticle signed-distance field for the runtime shader (R all, G lit, B etched)
  optics/IVS6_ads_overlay.webp       IV-S6 full-screen overlay (lossless, same px/mrad as the reticle)
  web_assets_manifest.json           sources (size + sha256) and outputs, used by Web/tools/build.mjs to warn when stale

and Web/src/data/optics_web.json (file names, SDF size / spread) for the runtime.

Texture encoding per material slot (measured on the IV-7 2048 set, see Web/README.md):
  base colour           WebP lossy q90 (EXT_texture_webp, no PNG fallback; three.js GLTFLoader supports it)
  normal, ORM           JPEG 4:4:4 q92 (core glTF). WebP lossy is always 4:2:0: on the packed ORM it mixes
                        AO / roughness / metal across texels (PSNR 25-30 dB), JPEG 4:4:4 keeps 39-44 dB.
  reticle (any slot)    WebP lossless at the source resolution (never resized)
Geometry is copied unchanged except WEIGHTS_0: float -> normalized unsigned byte (core glTF; the IV-7 is rigid
skinned, weights are exactly 0 or 1). The rifle's built-in optic glass loses KHR_materials_transmission (the web
runtime hides that optic and must never create a transmission pass).

Usage:  python3 Tools/web_assets/build_web_assets.py            (from the IronValley root or anywhere)
        cd Web && npm run assets:web                            (same)
Needs Python 3.10+, Pillow (WebP) and numpy + scipy (the same environment as the Blender pipeline).
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import struct
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

ROOT = Path(__file__).resolve().parents[2]
EXPORT = ROOT / 'Art' / 'Export' / 'GLB'
TEX = ROOT / 'Art' / 'Textures' / 'Optics'
PUBLIC = ROOT / 'Web' / 'public' / 'assets'
DATA_OUT = ROOT / 'Web' / 'src' / 'data' / 'optics_web.json'
OPTICS_JSON = ROOT / 'Shared' / 'config' / 'optics.json'

ARTIFACT_LIMIT = 15 * 1024 * 1024  # claude.ai Artifact host: per file, after base64 (x 4/3)

# texture size caps per asset class
RIFLE_MAX = 2048
OPTIC_BODY_MAX = 1024
OPTIC_LOD1_MAX = 512

# runtime reticle SDF: size (px) and spread (+- texels at that size) per optic. The spread must cover the
# dilation the shader needs to keep strokes >= min_stroke_px / the dot >= min_dot_diameter_px at the smallest
# on-screen scale (960 x 540, 1x ADS view for the 1x sights, the PiP disc / 6x overlay for the others).
SDF_PARAMS = {
    'IVH1': {'size': 512, 'spread': 64},
    'IVR1': {'size': 512, 'spread': 128},
    'IVP2': {'size': 512, 'spread': 48},
    'IVS3': {'size': 1024, 'spread': 16},
    'IVS6': {'size': 1024, 'spread': 12},
}

WEBP_BASE = dict(quality=90, method=6)
JPEG_DATA = dict(quality=92, subsampling=0, optimize=True)
WEBP_LOSSLESS = dict(lossless=True, quality=100, method=6)


# ------------------------------------------------------------------ GLB io

def read_glb(path: Path):
    b = path.read_bytes()
    magic, version, length = struct.unpack_from('<III', b, 0)
    if magic != 0x46546C67 or version != 2:
        raise ValueError(f'{path}: not a glTF 2.0 binary')
    off = 12
    js = None
    binchunk = b''
    while off < length:
        clen, ctype = struct.unpack_from('<II', b, off)
        data = b[off + 8: off + 8 + clen]
        if ctype == 0x4E4F534A:
            js = json.loads(data.decode('utf-8'))
        elif ctype == 0x004E4942:
            binchunk = bytes(data)
        off += 8 + clen
    return js, binchunk


def write_glb(path: Path, js: dict, blob: bytes):
    jbytes = json.dumps(js, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
    jbytes += b' ' * ((4 - len(jbytes) % 4) % 4)
    blob += b'\0' * ((4 - len(blob) % 4) % 4)
    total = 12 + 8 + len(jbytes) + 8 + len(blob)
    out = struct.pack('<III', 0x46546C67, 2, total)
    out += struct.pack('<II', len(jbytes), 0x4E4F534A) + jbytes
    out += struct.pack('<II', len(blob), 0x004E4942) + blob
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(out)
    return len(out)


def view_bytes(js, blob, index):
    bv = js['bufferViews'][index]
    o = bv.get('byteOffset', 0)
    return blob[o: o + bv['byteLength']]


# ------------------------------------------------------------------ textures

def image_roles(js):
    """Role of each image from the material slots that use it (reticle > normal > orm > emissive > base)."""
    prio = {'reticle': 5, 'normal': 4, 'orm': 3, 'emissive': 2, 'base': 1}
    roles = {}

    def tex_image(ti):
        t = js['textures'][ti]
        if 'source' in t:
            return t['source']
        ext = t.get('extensions', {})
        for k in ('EXT_texture_webp', 'EXT_texture_avif', 'KHR_texture_basisu'):
            if k in ext:
                return ext[k]['source']
        return None

    def mark(ti, role):
        if ti is None:
            return
        img = tex_image(ti)
        if img is None:
            return
        if img not in roles or prio[role] > prio[roles[img]]:
            roles[img] = role

    for m in js.get('materials', []):
        reticle = 'reticle' in (m.get('name') or '').lower()
        pbr = m.get('pbrMetallicRoughness', {})
        slots = [
            (pbr.get('baseColorTexture'), 'base'),
            (pbr.get('metallicRoughnessTexture'), 'orm'),
            (m.get('normalTexture'), 'normal'),
            (m.get('occlusionTexture'), 'orm'),
            (m.get('emissiveTexture'), 'emissive'),
        ]
        for ref, role in slots:
            if ref is not None:
                mark(ref['index'], 'reticle' if reticle else role)
    return roles


def encode_image(img: Image.Image, role: str, max_size: int):
    """Returns (bytes, mime, info). Reticles keep their resolution and are lossless."""
    src_size = img.size
    if role != 'reticle' and max(img.size) > max_size:
        img = img.resize((max_size, max_size), Image.LANCZOS)
    has_alpha = img.mode in ('RGBA', 'LA') and np.asarray(img.convert('RGBA'))[..., 3].min() < 255
    if role in ('reticle', 'emissive'):
        buf = io.BytesIO()
        img.convert('RGBA' if has_alpha else 'RGB').save(buf, 'WEBP', **WEBP_LOSSLESS)
        return buf.getvalue(), 'image/webp', {'format': 'webp-lossless', 'from': list(src_size), 'size': list(img.size)}
    if role == 'base':
        buf = io.BytesIO()
        img.convert('RGBA' if has_alpha else 'RGB').save(buf, 'WEBP', **WEBP_BASE)
        return buf.getvalue(), 'image/webp', {'format': 'webp-q90', 'from': list(src_size), 'size': list(img.size)}
    buf = io.BytesIO()
    img.convert('RGB').save(buf, 'JPEG', **JPEG_DATA)
    return buf.getvalue(), 'image/jpeg', {'format': 'jpeg444-q92', 'from': list(src_size), 'size': list(img.size)}


# ------------------------------------------------------------------ GLB conversion

def convert_glb(src: Path, dst: Path, max_size: int, strip_transmission: bool = False):
    js, blob = read_glb(src)
    roles = image_roles(js)
    new_views = {}  # bufferView index -> new bytes
    tex_info = []
    webp_images = set()
    for i, im in enumerate(js.get('images', [])):
        if 'bufferView' not in im:
            raise ValueError(f'{src}: image {i} is not embedded')
        pil = Image.open(io.BytesIO(view_bytes(js, blob, im['bufferView'])))
        pil.load()
        role = roles.get(i, 'base')
        data, mime, info = encode_image(pil, role, max_size)
        new_views[im['bufferView']] = data
        im['mimeType'] = mime
        if mime == 'image/webp':
            webp_images.add(i)
        tex_info.append({'image': im.get('name', str(i)), 'role': role, **info, 'bytes': len(data)})

    # WEIGHTS_0: float -> normalized unsigned byte when every weight is (numerically) a byte step
    weights_converted = 0
    for mesh in js.get('meshes', []):
        for prim in mesh['primitives']:
            ai = prim['attributes'].get('WEIGHTS_0')
            if ai is None:
                continue
            acc = js['accessors'][ai]
            if acc['componentType'] != 5126 or acc.get('sparse'):
                continue
            bvi = acc['bufferView']
            users = [a for a in js['accessors'] if a.get('bufferView') == bvi]
            bv = js['bufferViews'][bvi]
            if len(users) != 1 or bv.get('byteStride') not in (None, 16):
                continue
            raw = view_bytes(js, blob, bvi)
            o = acc.get('byteOffset', 0)
            w = np.frombuffer(raw[o: o + acc['count'] * 16], dtype='<f4').reshape(-1, 4)
            q = np.round(w * 255.0)
            if np.abs(q / 255.0 - w).max() > 1.5e-3:
                continue
            q = q.astype(np.uint8)
            # keep each vertex's weights summing to exactly 255 (rounding): fix on the largest weight
            s = q.astype(np.int32).sum(axis=1)
            big = q.argmax(axis=1)
            q[np.arange(len(q)), big] = (q[np.arange(len(q)), big].astype(np.int32) + (255 - s)).clip(0, 255).astype(np.uint8)
            new_views[bvi] = q.tobytes()
            bv.pop('byteStride', None)
            acc['componentType'] = 5121
            acc['normalized'] = True
            acc['byteOffset'] = 0
            weights_converted += 1

    # rebuild the binary chunk (bufferViews in their original order, 4-byte aligned)
    out = bytearray()
    for i, bv in enumerate(js['bufferViews']):
        data = new_views[i] if i in new_views else view_bytes(js, blob, i)
        out += b'\0' * ((4 - len(out) % 4) % 4)
        bv['byteOffset'] = len(out)
        bv['byteLength'] = len(data)
        bv['buffer'] = 0
        out += data
    js['buffers'] = [{'byteLength': len(out)}]

    # textures that use WebP images go through EXT_texture_webp (no fallback source)
    for t in js.get('textures', []):
        src_i = t.get('source')
        if src_i is not None and src_i in webp_images:
            t.pop('source')
            t.setdefault('extensions', {})['EXT_texture_webp'] = {'source': src_i}
    if webp_images:
        for key in ('extensionsUsed', 'extensionsRequired'):
            lst = js.setdefault(key, [])
            if 'EXT_texture_webp' not in lst:
                lst.append('EXT_texture_webp')

    stripped = 0
    if strip_transmission:
        for m in js.get('materials', []):
            ext = m.get('extensions', {})
            if 'KHR_materials_transmission' in ext:
                ext.pop('KHR_materials_transmission', None)
                ext.pop('KHR_materials_volume', None)
                pbr = m.setdefault('pbrMetallicRoughness', {})
                pbr['baseColorFactor'] = [0.03, 0.035, 0.035, 0.1]
                m['alphaMode'] = 'BLEND'
                stripped += 1
            if not ext:
                m.pop('extensions', None)
        used = {k for m in js.get('materials', []) for k in m.get('extensions', {})}
        for key in ('extensionsUsed', 'extensionsRequired'):
            if key in js:
                js[key] = [e for e in js[key] if e in used or not e.startswith('KHR_materials_')]
                if not js[key]:
                    js.pop(key)

    js.setdefault('asset', {})['extras'] = {
        'iv_web_variant': True,
        'source': str(src.relative_to(ROOT)),
        'tool': 'Tools/web_assets/build_web_assets.py',
    }
    size = write_glb(dst, js, bytes(out))
    return {
        'source': str(src.relative_to(ROOT)),
        'output': str(dst.relative_to(ROOT)),
        'bytes': size,
        'sourceBytes': src.stat().st_size,
        'textures': tex_info,
        'weightsConverted': weights_converted,
        'transmissionStripped': stripped,
    }


# ------------------------------------------------------------------ reticle SDF

def signed_distance(cov: np.ndarray) -> np.ndarray:
    """Signed distance in texels (+ inside) from an antialiased coverage map (0..1)."""
    inside = cov >= 0.5
    if not inside.any():
        return np.full(cov.shape, -1e3, dtype=np.float32)
    d_out = ndimage.distance_transform_edt(~inside)  # outside texels: distance to the nearest inside texel
    d_in = ndimage.distance_transform_edt(inside)  # inside texels: distance to the nearest outside texel
    d = np.where(inside, d_in - 0.5, -(d_out - 0.5)).astype(np.float32)
    # sub-texel edge from the analytic coverage (box-filter AA: coverage - 0.5 ~ signed distance near the edge)
    edge = (cov > 0.0) & (cov < 1.0)
    d[edge] = (cov[edge] - 0.5).astype(np.float32)
    return d


def reticle_sdf(opt_id: str, size: int, spread: int):
    base = Image.open(TEX / opt_id / f'T_{opt_id}_Reticle.png').convert('RGBA')
    emi = Image.open(TEX / opt_id / f'T_{opt_id}_Reticle_Emissive.png').convert('RGB')
    a = np.asarray(base, dtype=np.float32)[..., 3] / 255.0
    e = np.asarray(emi, dtype=np.float32)
    lit = e.max(axis=2) / 255.0
    etched = np.clip(a - lit, 0.0, 1.0)
    src = a.shape[0]
    f = src // size
    if f * size != src:
        raise ValueError(f'{opt_id}: SDF size {size} does not divide {src}')
    chans = []
    for cov in (a, lit, etched):
        d = signed_distance(cov)
        d = d.reshape(size, f, size, f).mean(axis=(1, 3)) / f  # distances in output texels
        chans.append(np.clip(np.round((0.5 + d / (2.0 * spread)) * 255.0), 0, 255).astype(np.uint8))
    img = Image.fromarray(np.stack(chans, axis=-1), 'RGB')
    out = PUBLIC / 'optics' / f'{opt_id}_reticle_sdf.png'
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, 'PNG', optimize=True)
    return {'file': f'assets/optics/{opt_id}_reticle_sdf.png', 'size': size, 'spread': spread, 'sourceSize': src, 'bytes': out.stat().st_size,
            'channels': 'R all features, G illuminated, B etched; value = 0.5 + d / (2 spread), d = signed distance in texels of this texture (+ inside)'}


# ------------------------------------------------------------------ main

def sha256(p: Path):
    h = hashlib.sha256()
    with p.open('rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def main():
    t0 = time.time()
    optics = json.loads(OPTICS_JSON.read_text())
    results = []
    sources = [OPTICS_JSON]

    rifle_src = EXPORT / 'IV7_Carbine.glb'
    results.append(convert_glb(rifle_src, PUBLIC / 'weapons' / 'IV7_Carbine.glb', RIFLE_MAX, strip_transmission=True))
    sources.append(rifle_src)

    web = {'_comment': 'GENERATED by Tools/web_assets/build_web_assets.py - do not edit. Runtime file names of the web optic assets and the reticle SDF parameters.',
           'rifle': {'glb': 'assets/weapons/IV7_Carbine.glb'}, 'optics': {}}
    for o in optics['optics']:
        oid = o['id']
        a = o['assets']
        lod0 = ROOT / a['glb']
        lod1 = ROOT / a['glb_lod1']
        name0 = lod0.name
        name1 = lod1.name
        results.append(convert_glb(lod0, PUBLIC / 'optics' / name0, OPTIC_BODY_MAX))
        results.append(convert_glb(lod1, PUBLIC / 'optics' / name1, OPTIC_LOD1_MAX))
        sources += [lod0, lod1, TEX / oid / f'T_{oid}_Reticle.png', TEX / oid / f'T_{oid}_Reticle_Emissive.png']
        p = SDF_PARAMS[oid]
        entry = {'glb': f'assets/optics/{name0}', 'lod1': f'assets/optics/{name1}', 'sdf': reticle_sdf(oid, p['size'], p['spread'])}
        if 'ads_overlay' in o:
            ov_src = ROOT / o['ads_overlay']['texture']
            ov = Image.open(ov_src)
            ov.load()
            out = PUBLIC / 'optics' / f'{oid}_ads_overlay.webp'
            ov.save(out, 'WEBP', **WEBP_LOSSLESS)
            entry['overlay'] = {'file': f'assets/optics/{oid}_ads_overlay.webp', 'size': ov.size[0], 'bytes': out.stat().st_size, 'format': 'webp-lossless'}
            sources.append(ov_src)
        web['optics'][oid] = entry

    DATA_OUT.write_text(json.dumps(web, indent=2, ensure_ascii=False) + '\n')

    outputs = []
    too_big = []
    for f in sorted((PUBLIC / 'weapons').glob('*.glb')) + sorted((PUBLIC / 'optics').glob('*')):
        n = f.stat().st_size
        b64 = 4 * math.ceil(n / 3)
        outputs.append({'path': str(f.relative_to(ROOT)), 'bytes': n, 'base64Bytes': b64})
        if b64 > ARTIFACT_LIMIT:
            too_big.append(f.name)
    manifest = {
        'tool': 'Tools/web_assets/build_web_assets.py',
        'generatedAt': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'sources': [{'path': str(s.relative_to(ROOT)), 'bytes': s.stat().st_size, 'sha256': sha256(s)} for s in sources],
        'outputs': outputs,
        'glb': results,
    }
    (PUBLIC / 'web_assets_manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')

    tot_src = sum(r['sourceBytes'] for r in results)
    tot_out = sum(r['bytes'] for r in results)
    for r in results:
        print(f"{r['output']:<52} {r['sourceBytes'] / 1048576:6.2f} MiB -> {r['bytes'] / 1048576:6.2f} MiB"
              f"  (weights u8: {r['weightsConverted']}, transmission stripped: {r['transmissionStripped']})")
    for oid, e in web['optics'].items():
        print(f"{e['sdf']['file']:<52} {e['sdf']['bytes'] / 1024:7.1f} KiB  ({e['sdf']['size']} px, spread {e['sdf']['spread']})")
        if 'overlay' in e:
            print(f"{e['overlay']['file']:<52} {e['overlay']['bytes'] / 1024:7.1f} KiB")
    print(f'GLB total {tot_src / 1048576:.2f} MiB -> {tot_out / 1048576:.2f} MiB in {time.time() - t0:.1f} s')
    if too_big:
        print('ERROR: over the artifact host limit after base64:', ', '.join(too_big))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
