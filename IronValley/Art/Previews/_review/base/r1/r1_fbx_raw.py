"""R1 review: raw FBX structure of SK_Human_Base.fbx (Blender's FBX parser, no importer logic).
Lists GlobalSettings (units/axes), Model nodes (type, Lcl transforms, PreRotation), skin
clusters (count per bone, weights per vertex from the clusters), BindPose presence."""
import sys, json
import numpy as np
import bpy  # noqa: F401  (makes io_scene_fbx importable)
import addon_utils
addon_utils.enable("io_scene_fbx")
from io_scene_fbx import parse_fbx

P = "/home/user/Sroskus/IronValley/Art/Export/FBX/SK_Human_Base.fbx"
root, version = parse_fbx.parse(P)
out = {"fbx_version": version}


def find(elem, name):
    return [e for e in elem.elems if e.id == name]


def props70(elem):
    d = {}
    for p in find(elem, b"Properties70"):
        for pp in p.elems:
            key = pp.props[0].decode()
            d[key] = [x.decode() if isinstance(x, bytes) else x for x in pp.props[1:]]
    return d


gs = find(root, b"GlobalSettings")[0]
g = props70(gs)
out["GlobalSettings"] = {k: g[k][-1] for k in ("UpAxis", "UpAxisSign", "FrontAxis", "FrontAxisSign",
                                                 "CoordAxis", "CoordAxisSign", "UnitScaleFactor",
                                                 "OriginalUnitScaleFactor") if k in g}
objs = find(root, b"Objects")[0]
models = {}
for m in find(objs, b"Model"):
    uid = m.props[0]
    name = m.props[1].split(b"\x00")[0].decode()
    typ = m.props[2].decode()
    p = props70(m)
    models[uid] = {"name": name, "type": typ,
                   "Lcl Translation": p.get("Lcl Translation", [None] * 4)[-3:],
                   "Lcl Rotation": p.get("Lcl Rotation", [None] * 4)[-3:],
                   "Lcl Scaling": p.get("Lcl Scaling", [None] * 4)[-3:],
                   "PreRotation": p.get("PreRotation", [None] * 4)[-3:] if "PreRotation" in p else None}
conns = find(root, b"Connections")[0]
parent = {}
for c in conns.elems:
    if c.props[0] == b"OO":
        parent.setdefault(c.props[1], []).append(c.props[2])
mparent = {}
for ch, ps in parent.items():
    if ch in models:
        for p_ in ps:
            if p_ in models:
                mparent[ch] = p_
            elif p_ == 0:
                mparent[ch] = 0
roots = [u for u in models if mparent.get(u, 0) == 0]
out["top_level_models"] = [(models[u]["name"], models[u]["type"], models[u]["Lcl Scaling"], models[u]["Lcl Rotation"]) for u in roots]
out["model_type_counts"] = {}
for m in models.values():
    out["model_type_counts"][m["type"]] = out["model_type_counts"].get(m["type"], 0) + 1
# children of top-level null
for u in roots:
    out.setdefault("children_of_top", {})[models[u]["name"]] = [models[c]["name"] + ":" + models[c]["type"] for c, p_ in mparent.items() if p_ == u]
lim = {m["name"]: m for m in models.values() if m["type"] == "LimbNode"}
out["limbnode_count"] = len(lim)
out["root_limb"] = lim.get("root")
out["pelvis_limb"] = lim.get("pelvis")
scales = [m["Lcl Scaling"] for m in lim.values() if m["Lcl Scaling"][0] is not None]
out["limb_scale_range"] = [float(np.min(scales)), float(np.max(scales))] if scales else None
# geometry
geoms = find(objs, b"Geometry")
for gm in geoms:
    if gm.props[2] != b"Mesh":
        continue
    verts = np.array(find(gm, b"Vertices")[0].props[0]).reshape(-1, 3)
    out["geometry"] = {"vertices": len(verts), "min": verts.min(0).round(3).tolist(), "max": verts.max(0).round(3).tolist(),
                       "extent": np.ptp(verts, 0).round(3).tolist()}
    pvi = np.array(find(gm, b"PolygonVertexIndex")[0].props[0])
    out["geometry"]["polygons"] = int((pvi < 0).sum())
    out["geometry"]["max_poly_size"] = int(np.diff(np.r_[-1, np.nonzero(pvi < 0)[0]]).max())
    out["geometry"]["layers"] = [e.id.decode() for e in gm.elems if e.id.startswith(b"Layer")]
# deformers
defs = find(objs, b"Deformer")
clusters = [d for d in defs if d.props[2] == b"Cluster"]
skins = [d for d in defs if d.props[2] == b"Skin"]
out["skin_deformers"] = len(skins)
out["clusters"] = len(clusters)
nv = out["geometry"]["vertices"]
Wsum = np.zeros(nv)
Wcnt = np.zeros(nv, int)
cl_bone = []
for c in clusters:
    idx = find(c, b"Indexes")
    w = find(c, b"Weights")
    if not idx:
        continue
    ii = np.array(idx[0].props[0]); ww = np.array(w[0].props[0])
    np.add.at(Wsum, ii, ww)
    np.add.at(Wcnt, ii, (ww > 0).astype(int))
    # linked bone
    for p_ in parent.get(c.props[0], []):
        pass
out["cluster_weights"] = {"sum_min": float(Wsum.min()), "sum_max": float(Wsum.max()), "unweighted": int((Wsum < 1e-6).sum()),
                          "influence_hist": {int(k): int(v) for k, v in zip(*np.unique(Wcnt, return_counts=True))}}
# bone names linked to clusters
link = {}
for c in conns.elems:
    if c.props[0] == b"OO" and c.props[1] in models and models[c.props[1]]["type"] == "LimbNode":
        link.setdefault(c.props[2], []).append(models[c.props[1]]["name"])
cl_names = []
for c in clusters:
    cl_names += link.get(c.props[0], [])
out["cluster_bones_missing_vs_limbs"] = sorted(set(lim) - set(cl_names))
poses = find(objs, b"Pose")
out["bind_poses"] = [(p.props[1].split(b"\x00")[0].decode(), p.props[2].decode(), len(find(p, b"PoseNode"))) for p in poses]
out["materials"] = [m.props[1].split(b"\x00")[0].decode() for m in find(objs, b"Material")]
out["textures"] = len(find(objs, b"Texture"))
json.dump(out, open("/home/user/Sroskus/IronValley/Art/Previews/_review/base/r1/r1_fbx_raw.json", "w"), indent=1, default=str)
for k, v in out.items():
    print(k, ":", v)
