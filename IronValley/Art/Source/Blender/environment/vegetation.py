#!/usr/bin/env python3
"""
vegetation.py -- builds the trees and shrubs of "Kalné Hamry" in Blender (bpy 4.5, headless) from the procedural
rules of Art/Source/Blender/lib/ivveg.py and the textures of Tools/environment/vegetation_textures.py, and writes

  Web/public/assets/environment/vegetation.glb   every model x LOD0/1/2 (custom vertex data, see ivveg), the
                                                  foliage atlas (WebP with alpha) + normal atlas, the bark array
                                                  strips, the grass & flower atlas, the clipped-hedge surface and
                                                  asset extras: models, species -> model map, LOD distances,
                                                  grass card definitions (read by Web/src/level/vegetation.js)
  Art/Export/GLB/Environment/Vegetation.glb       the same file (source of the web copy)
  Art/Source/Blender/environment/vegetation.blend one object per model and LOD (for inspection / UE export later)
  Art/Previews/Environment/vegetation_models.png  Cycles preview of all LOD0 models (with --preview)
  Art/Previews/Environment/vegetation_stats.json  triangles / vertices / cards per model and LOD

Usage: python3 Art/Source/Blender/environment/vegetation.py [--preview] [--no-blend]
Deterministic (fixed seeds per model).
"""
import argparse
import io
import json
import math
import os
import sys
import time

import numpy as np
from PIL import Image, ImageFile, ImageFilter

ImageFile.MAXBLOCK = 1 << 25   # optimised JPEG of large images needs one big buffer (PIL "Suspension not allowed")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))
sys.path.insert(0, os.path.join(ROOT, "Tools", "level", "lib"))
import ivveg as V  # noqa: E402
from ivglb import FLOAT, UBYTE, BYTE, USHORT, UINT, ELEMENT_ARRAY_BUFFER, GLB, to_gltf  # noqa: E402

TEX = os.path.join(ROOT, "Art", "Textures", "Environment", "Vegetation")
OUT_WEB = os.path.join(ROOT, "Web", "public", "assets", "environment", "vegetation.glb")
OUT_ART = os.path.join(ROOT, "Art", "Export", "GLB", "Environment", "Vegetation.glb")
PREV = os.path.join(ROOT, "Art", "Previews", "Environment")
SEED = 20260929
T0 = time.time()


def log(*a):
    print(f"[{time.time() - T0:6.1f} s]", *a, flush=True)


def rng(k):
    return np.random.default_rng(SEED + k)


# model name: (builder, LOD2 clump / silhouette rect, is conifer)
MODELS = {
    "spruce": (lambda r: V.spruce("spruce", r, H=22.0, R=3.4, cb=1.2), "spruce_sil", True),
    "spruce_b": (lambda r: V.spruce("spruce_b", r, H=22.0, R=3.1, cb=4.5), "spruce_sil", True),
    "pine": (lambda r: V.pine("pine", r, H=20.0, R=3.6, cb=11.0), "pine_sil", True),
    "birch": (lambda r: V.broadleaf("birch", r, 16.0, 3.5, 4.0, 0.22, "birch", limbs=12, elev=(55, 72), sub=7, pendulous=0.75, bark="birch",
                                    card_size=0.85, density=1.7, autumn=0.05), "clump_birch", False),
    "birch_young": (lambda r: V.broadleaf("birch_young", r, 13.0, 2.5, 3.0, 0.13, "birch", limbs=9, elev=(58, 76), sub=6, pendulous=0.6,
                                          bark="birch", card_size=0.7, density=1.2, autumn=0.05), "clump_birch", False),
    "slender": (lambda r: V.broadleaf("slender", r, 14.0, 3.3, 3.0, 0.2, "aspen", limbs=11, elev=(45, 70), sub=7, card_size=0.9, density=1.3), "clump_dark", False),
    "wide": (lambda r: V.broadleaf("wide", r, 16.0, 6.0, 2.5, 0.36, "lime", stems=3, limbs=12, elev=(22, 58), sub=5, card_size=1.3, density=0.75,
                                   autumn=0.03), "clump_green", False),
    "round": (lambda r: V.broadleaf("round", r, 18.0, 5.5, 3.5, 0.34, "maple", limbs=13, elev=(28, 60), sub=8, card_size=1.2, density=1.0), "clump_green", False),
    "fruit": (lambda r: V.broadleaf("fruit", r, 6.5, 3.0, 1.6, 0.15, "fruit", limbs=9, elev=(18, 50), sub=7, card_size=0.8, density=1.4, lean=0.12), "clump_green", False),
    "shrub_low": (lambda r: V.shrub("shrub_low", r, 0.8, 1.4, "hazel", stems=6, card_size=0.45), "clump_green", False),
    "shrub_mid": (lambda r: V.shrub("shrub_mid", r, 1.3, 1.8, "hazel", stems=8, card_size=0.55), "clump_green", False),
    "shrub_tall": (lambda r: V.shrub("shrub_tall", r, 2.0, 2.2, "hazel", stems=10, card_size=0.65), "clump_green", False),
    "hedge_wild": (lambda r: V.shrub("hedge_wild", r, 2.2, 1.8, "maple", stems=10, card_size=0.6, density=1.2), "clump_dark", False),
}
# layout species / kinds -> models (variants chosen per instance by its seed)
SPECIES_MODELS = {
    "smrk": ["spruce", "spruce_b"], "borovice": ["pine"], "briza": ["birch"], "briza_mlada": ["birch_young"],
    "olse": ["slender"], "jasan": ["slender", "round"], "vrba": ["wide"], "lipa": ["wide", "round"], "lipa_stara": ["wide"],
    "habr": ["wide", "round"], "orech": ["wide"], "javor": ["round"], "buk": ["round", "slender"], "dub": ["round", "wide"],
    "jablon": ["fruit"], "hruska": ["fruit"], "svestka": ["fruit"],
    "shrub_low": ["shrub_low"], "shrub_mid": ["shrub_mid"], "shrub_tall": ["shrub_tall"], "hedge_wild": ["hedge_wild"],
    "far_conifer": ["spruce"], "far_broadleaf": ["round"],
}
# LOD switch distances (m, from layout.json trees.species[*].lods / performance_budget_browser.trees)
LOD_DIST = {"lod1": 35.0, "lod2": 90.0, "shrub_lod1": 25.0, "shrub_lod2": 60.0, "hysteresis": 4.0}


def load_meta():
    return json.load(open(os.path.join(TEX, "vegetation_textures.json")))


def build_all(meta):
    rects = {k: tuple(v) for k, v in meta["foliage"]["rects"].items()}
    size = tuple(meta["foliage"]["size"])
    out = {}
    for i, (name, (fn, far_rect, conifer)) in enumerate(MODELS.items()):
        r = rng(i * 17)
        m0 = fn(r)
        m1 = V.lod1(m0, rng(i * 17 + 1), keep=0.3 if not name.startswith(("shrub", "hedge")) else 0.4, scale=1.6)
        m2 = V.lod2(m0, rng(i * 17 + 2), far_rect, silhouette_rect=far_rect if conifer else None,
                    n_clumps=12 if not name.startswith(("shrub", "hedge")) else 5)
        lods = []
        for k, m in enumerate((m0, m1, m2)):
            sides = ((8, 3, 3, 3) if conifer else (8, 5, 3, 3)) if k == 0 else (5, 3, 3)
            arr = V.build_mesh(m, rects, size, sides=sides, ao=(k < 2), r=rng(i * 17 + 5 + k))
            lods.append(arr)
        P = lods[0][0]
        height = float(P[:, 2].max())
        crown = float(np.percentile(np.hypot(P[:, 0], P[:, 1]), 98))
        out[name] = {"lods": lods, "height": height, "crown": crown, "trunk": m0.trunk_radius, "conifer": conifer,
                     "cards": [len(m0.cards), len(m1.cards), len(m2.cards)]}
        tris = [len(a[5]) for a in lods]
        log(f"{name}: H {height:.1f} m, crown r {crown:.1f} m, tris LOD0/1/2 {tris}, cards {out[name]['cards']}")
    return out


def to_blender(models, save_path=None):
    """one Blender object per model and LOD (UV, colour, custom data as attributes) -> .blend for inspection."""
    import bpy
    bpy.ops.wm.read_factory_settings(use_empty=True)
    col = bpy.data.collections.new("Vegetation")
    bpy.context.scene.collection.children.link(col)
    objs = {}
    for name, md in models.items():
        for k, (P, N, UV, C, Vv, I) in enumerate(md["lods"]):
            me = bpy.data.meshes.new(f"SM_Veg_{name}_LOD{k}")
            me.from_pydata([tuple(p) for p in P], [], [tuple(t) for t in I])
            uv = me.uv_layers.new(name="UVMap")
            loops_v = np.zeros(len(me.loops), np.int64)
            me.loops.foreach_get("vertex_index", loops_v)
            uvl = np.column_stack([UV[loops_v, 0], 1 - UV[loops_v, 1]])
            uv.data.foreach_set("uv", uvl.ravel())
            ca = me.color_attributes.new("Tint", "FLOAT_COLOR", "POINT")
            ca.data.foreach_set("color", np.column_stack([C, np.ones(len(C))]).ravel())
            va = me.attributes.new("_IVVEG", "FLOAT_COLOR", "POINT")
            va.data.foreach_set("color", Vv.ravel())
            me.update()
            ob = bpy.data.objects.new(f"SM_Veg_{name}_LOD{k}", me)
            col.objects.link(ob)
            ob.location = (list(models).index(name) * 14.0, k * 14.0, 0)
            objs[(name, k)] = ob
    if save_path:
        bpy.ops.wm.save_as_mainfile(filepath=save_path)
    return objs


def preview(models, path):
    """Cycles preview of every LOD0 (foliage atlas with alpha, bark layers), side view, sun + sky."""
    import bpy
    sys.path.insert(0, os.path.join(HERE, "..", "lib"))
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.device = "CPU"
    sc.cycles.samples = 24
    sc.cycles.use_denoising = False
    sc.cycles.transparent_max_bounces = 24
    sc.render.threads_mode = "FIXED"
    sc.render.threads = 3
    sc.render.film_transparent = False
    world = bpy.data.worlds.new("W")
    sc.world = world
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (0.55, 0.65, 0.8, 1)
    world.node_tree.nodes["Background"].inputs[1].default_value = 0.8
    sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", "SUN"))
    sun.data.energy = 3.5
    sun.rotation_euler = (math.radians(52), 0, math.radians(40))
    sc.collection.objects.link(sun)
    atlas = bpy.data.images.load(os.path.join(TEX, "T_Foliage_Atlas_BaseColor.png"))
    bark_imgs = [bpy.data.images.load(os.path.join(TEX, f"T_Bark_{n}_BaseColor.png")) for n in ("Spruce", "Pine", "Birch", "BirchBase", "Broadleaf")]

    def mat_leaf():
        m = bpy.data.materials.new("Leaf")
        m.use_nodes = True
        nt = m.node_tree
        bs = nt.nodes["Principled BSDF"]
        tx = nt.nodes.new("ShaderNodeTexImage")
        tx.image = atlas
        at = nt.nodes.new("ShaderNodeAttribute")
        at.attribute_name = "Tint"
        mul = nt.nodes.new("ShaderNodeMix")
        mul.data_type = "RGBA"
        mul.blend_type = "MULTIPLY"
        mul.inputs["Factor"].default_value = 1.0
        nt.links.new(tx.outputs["Color"], mul.inputs["A"])
        nt.links.new(at.outputs["Color"], mul.inputs["B"])
        nt.links.new(mul.outputs["Result"], bs.inputs["Base Color"])
        nt.links.new(tx.outputs["Alpha"], bs.inputs["Alpha"])
        bs.inputs["Roughness"].default_value = 0.7
        return m

    def mat_bark(img):
        m = bpy.data.materials.new("Bark")
        m.use_nodes = True
        nt = m.node_tree
        tx = nt.nodes.new("ShaderNodeTexImage")
        tx.image = img
        nt.links.new(tx.outputs["Color"], nt.nodes["Principled BSDF"].inputs["Base Color"])
        return m
    leaf = mat_leaf()
    barks = [mat_bark(i) for i in bark_imgs]
    names = [n for n in models if n not in ("spruce_b",)]
    x = 0.0
    maxh = 0
    for name in names:
        P, N, UV, C, Vv, I = models[name]["lods"][0]
        me = bpy.data.meshes.new(name)
        me.from_pydata([tuple(p) for p in P], [], [tuple(t) for t in I])
        uv = me.uv_layers.new(name="UVMap")
        lv = np.zeros(len(me.loops), np.int64)
        me.loops.foreach_get("vertex_index", lv)
        uv.data.foreach_set("uv", np.column_stack([UV[lv, 0], 1 - UV[lv, 1]]).ravel())
        ca = me.color_attributes.new("Tint", "FLOAT_COLOR", "POINT")
        ca.data.foreach_set("color", np.column_stack([C, np.ones(len(C))]).ravel())
        me.materials.append(leaf)
        for b in barks:
            me.materials.append(b)
        leaf_v = Vv[:, 0] > 0.99
        code = np.round(Vv[:, 0] * 255).astype(int)
        mi = np.zeros(len(I), np.int32)
        tri_leaf = leaf_v[I[:, 0]]
        layer = np.clip(code[I[:, 0]] // 50, 0, 4)
        mi[~tri_leaf] = 1 + layer[~tri_leaf]
        me.polygons.foreach_set("material_index", mi)
        me.update()
        ob = bpy.data.objects.new(name, me)
        sc.collection.objects.link(ob)
        w = models[name]["crown"] * 2 + 1.5
        ob.location = (x + w / 2, 0, 0)
        x += w
        maxh = max(maxh, models[name]["height"])
    ground = bpy.data.meshes.new("g")
    ground.from_pydata([(-5, -30, 0), (x + 5, -30, 0), (x + 5, 30, 0), (-5, 30, 0)], [], [(0, 1, 2, 3)])
    gob = bpy.data.objects.new("g", ground)
    gm = bpy.data.materials.new("G")
    gm.use_nodes = True
    gm.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.2, 0.22, 0.12, 1)
    ground.materials.append(gm)
    sc.collection.objects.link(gob)
    cam = bpy.data.objects.new("Cam", bpy.data.cameras.new("Cam"))
    cam.data.type = "ORTHO"
    cam.data.ortho_scale = max(x, maxh * 2.2) * 1.02
    cam.location = (x / 2, -60, maxh * 0.5)
    cam.rotation_euler = (math.radians(90), 0, 0)
    sc.collection.objects.link(cam)
    sc.camera = cam
    sc.render.resolution_x = 2000
    sc.render.resolution_y = int(2000 * max(maxh * 1.1, 1) / max(x, maxh * 2.2))
    sc.render.resolution_y = max(400, sc.render.resolution_y)
    sc.render.filepath = path
    bpy.ops.render.render(write_still=True)
    log(f"preview -> {path}")


def webp_rgba(path, size, q=86):
    im = Image.open(path).convert("RGBA")
    if im.size != size:
        im = im.resize(size, Image.LANCZOS)
    b = io.BytesIO()
    im.save(b, "WEBP", quality=q, alpha_quality=100, method=6)
    return b.getvalue()


def jpeg(path_or_arr, size=None, q=86):
    im = Image.open(path_or_arr).convert("RGB") if isinstance(path_or_arr, str) else Image.fromarray(path_or_arr)
    if size and im.size != size:
        im = im.resize(size, Image.LANCZOS)
    b = io.BytesIO()
    im.save(b, "JPEG", quality=q, subsampling=0, optimize=True)
    return b.getvalue()


UV_SCALE = 32.0     # TEXCOORD_0 is stored as unsigned short normalised uv / UV_SCALE (bark uvs tile in metres)


def write_glb(models, meta, paths):
    g = GLB(generator="IRON VALLEY Art/Source/Blender/environment/vegetation.py")
    g.extensionsUsed.add("KHR_mesh_quantization")
    nodes = []
    model_info = {}
    for name, md in models.items():
        lod_meshes = []
        for k, (P, N, UV, C, Vv, I) in enumerate(md["lods"]):
            # positions: normalised int16 + node scale (KHR_mesh_quantization); the node transform dequantises
            Pg = to_gltf(P)
            ext = float(np.abs(Pg).max()) * 1.001
            Pq = np.round(Pg / ext * 32767)
            attrs = {
                "POSITION": g.accessor(Pq, "VEC3", 5122, normalized=True, minmax=True),
                "NORMAL": g.accessor(np.round(to_gltf(N) * 127), "VEC3", BYTE, normalized=True),
                "TEXCOORD_0": g.accessor(np.clip(np.round(UV / UV_SCALE * 65535), 0, 65535), "VEC2", USHORT, normalized=True),
                "COLOR_0": g.accessor(np.clip(np.round(np.column_stack([np.clip(C, 0, 1.4) / 1.4, np.ones(len(C))]) * 255), 0, 255), "VEC4", UBYTE, normalized=True),
                "_IVVEG": g.accessor(np.clip(np.round(Vv * 255), 0, 255), "VEC4", UBYTE, normalized=True),
            }
            it = USHORT if len(P) < 65536 else UINT
            prim = {"attributes": attrs, "indices": g.accessor(I.ravel(), "SCALAR", it, target=ELEMENT_ARRAY_BUFFER), "mode": 4}
            mi = g.add_mesh(f"{name}_LOD{k}", [prim])
            nodes.append(g.add_node({"name": f"{name}_LOD{k}", "mesh": mi, "scale": [ext, ext, ext], "extras": {"iv": {"model": name, "lod": k}}}))
            lod_meshes.append({"node": f"{name}_LOD{k}", "triangles": int(len(I)), "vertices": int(len(P))})
        model_info[name] = {"height": round(md["height"], 3), "crownRadius": round(md["crown"], 3), "trunkRadius": md["trunk"],
                            "conifer": md["conifer"], "lods": lod_meshes, "cards": md["cards"]}
    imgs = {
        "foliage": g.add_image(webp_rgba(os.path.join(TEX, "T_Foliage_Atlas_BaseColor.png"), (1024, 1024)), "image/webp"),
        "foliageNormal": g.add_image(jpeg(os.path.join(TEX, "T_Foliage_Atlas_Normal.png"), (1024, 1024), 84), "image/jpeg"),
        "grass": g.add_image(webp_rgba(os.path.join(TEX, "T_Grass_Atlas_BaseColor.png"), (1024, 768), 80), "image/webp"),
        "hedge": g.add_image(jpeg(os.path.join(TEX, "T_Hedge_BaseColor.png"), (512, 512), 86), "image/jpeg"),
        "hedgeNormal": g.add_image(jpeg(os.path.join(TEX, "T_Hedge_Normal.png"), (512, 512), 86), "image/jpeg"),
    }
    # bark array strips (256 px per layer)
    names = ["Spruce", "Pine", "Birch", "BirchBase", "Broadleaf"]
    bc = np.concatenate([np.asarray(Image.open(os.path.join(TEX, f"T_Bark_{n}_BaseColor.png")).convert("RGB").resize((256, 256), Image.LANCZOS)) for n in names], 0)
    bn = np.concatenate([np.asarray(Image.open(os.path.join(TEX, f"T_Bark_{n}_Normal.png")).convert("RGB").resize((256, 256), Image.LANCZOS).filter(ImageFilter.GaussianBlur(0.7))) for n in names], 0)
    imgs["bark"] = g.add_image(jpeg(bc, None, 86), "image/jpeg")
    imgs["barkNormal"] = g.add_image(jpeg(bn, None, 80), "image/jpeg")
    fr = meta["foliage"]["rects"]
    gr = meta["grass"]["rects"]
    g.extras = {"iv": {
        "_comment": "GENERATED by Art/Source/Blender/environment/vegetation.py (see Art/Source/Blender/lib/ivveg.py) - do not edit",
        "frame": "glTF / three.js (x, y_up, z) = Blender (x, z, -y)",
        "models": model_info, "speciesModels": SPECIES_MODELS, "lodDistances": LOD_DIST,
        "images": imgs, "barkLayers": names, "barkTileM": 1.0, "hedgeTileM": 1.0,
        "foliageAtlas": {"size": meta["foliage"]["size"], "rects": fr},
        "grassAtlas": {"size": meta["grass"]["size"], "rects": gr, "heightM": meta["grass"]["height_m"]},
        "uvScale": UV_SCALE,
        "vertexData": "POSITION int16 normalised * node scale; TEXCOORD_0 u16 normalised * uvScale; _IVVEG u8x4: x = bark layer * 50 + blend * 49 (255 = foliage), y = wind flex, z = occlusion, w = wind phase; COLOR_0 = tint / 1.4",
    }}
    for p in paths:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        sz = g.write(p, nodes)
        log(f"wrote {p} ({sz / 1048576:.2f} MiB)")
    return model_info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", action="store_true")
    ap.add_argument("--no-blend", action="store_true")
    a = ap.parse_args()
    meta = load_meta()
    models = build_all(meta)
    info = write_glb(models, meta, [OUT_WEB, OUT_ART])
    os.makedirs(PREV, exist_ok=True)
    with open(os.path.join(PREV, "vegetation_stats.json"), "w") as f:
        json.dump(info, f, indent=1)
    if not a.no_blend:
        to_blender(models, os.path.join(HERE, "vegetation.blend"))
        log("blend saved")
    if a.preview:
        preview(models, os.path.join(PREV, "vegetation_models.png"))


if __name__ == "__main__":
    main()
