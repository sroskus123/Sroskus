"""R1 review: parse Human_Base.glb directly (no Blender importer) and check the skin data.
Checks: node hierarchy, skin joints / skeleton root, inverse bind matrices vs node world
matrices, JOINTS_0/WEIGHTS_0 (count, <=4, normalised, unweighted), mesh bbox/height, scale,
index/triangle count, normals/tangents present and unit, UV range."""
import json, struct, sys
import numpy as np

P = "/home/user/Sroskus/IronValley/Art/Export/GLB/Human_Base.glb"
out = {}
with open(P, "rb") as f:
    data = f.read()
magic, ver, length = struct.unpack_from("<III", data, 0)
assert magic == 0x46546C67
off = 12
chunks = []
while off < length:
    clen, ctype = struct.unpack_from("<II", data, off)
    chunks.append((ctype, data[off + 8: off + 8 + clen]))
    off += 8 + clen
gj = json.loads(chunks[0][1])
bin_ = chunks[1][1]
out["asset"] = gj.get("asset")
out["extensionsUsed"] = gj.get("extensionsUsed")
out["n_nodes"] = len(gj["nodes"])
out["n_meshes"] = len(gj["meshes"])
out["n_skins"] = len(gj.get("skins", []))
out["n_materials"] = len(gj.get("materials", []))
out["n_animations"] = len(gj.get("animations", []))
out["scenes"] = gj["scenes"]

CT = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
NC = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def acc(i):
    a = gj["accessors"][i]
    bv = gj["bufferViews"][a["bufferView"]]
    dt = np.dtype(CT[a["componentType"]])
    n = NC[a["type"]]
    start = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
    stride = bv.get("byteStride", dt.itemsize * n)
    if stride == dt.itemsize * n:
        arr = np.frombuffer(bin_, dtype=dt, count=a["count"] * n, offset=start).reshape(a["count"], n)
    else:
        arr = np.stack([np.frombuffer(bin_, dtype=dt, count=n, offset=start + k * stride) for k in range(a["count"])])
    if a.get("normalized"):
        arr = arr.astype(np.float64) / np.iinfo(dt).max
    return arr.astype(np.float64) if dt != np.float32 else arr.astype(np.float64)


nodes = gj["nodes"]
parent = {}
for i, n in enumerate(nodes):
    for c in n.get("children", []):
        parent[c] = i


def local(n):
    if "matrix" in n:
        return np.array(n["matrix"]).reshape(4, 4).T
    t = np.array(n.get("translation", [0, 0, 0]))
    q = n.get("rotation", [0, 0, 0, 1])
    s = np.array(n.get("scale", [1, 1, 1]))
    x, y, z, w = q
    R = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                  [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                  [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
    M = np.eye(4)
    M[:3, :3] = R * s
    M[:3, 3] = t
    return M


def world(i):
    M = local(nodes[i])
    while i in parent:
        i = parent[i]
        M = local(nodes[i]) @ M
    return M


roots = [i for i in range(len(nodes)) if i not in parent]
out["root_nodes"] = [(i, nodes[i].get("name"), [nodes[c].get("name") for c in nodes[i].get("children", [])]) for i in roots]
# non-identity scale anywhere?
out["nodes_with_scale"] = [(n.get("name"), n["scale"]) for n in nodes if "scale" in n and np.abs(np.array(n["scale"]) - 1).max() > 1e-6]
skin = gj["skins"][0]
joints = skin["joints"]
jn = [nodes[j].get("name") for j in joints]
out["skin_joint_count"] = len(joints)
out["skin_skeleton"] = nodes[skin["skeleton"]].get("name") if "skeleton" in skin else None
out["joint_names"] = jn
jparents = {nodes[j]["name"]: (nodes[parent[j]]["name"] if j in parent else None) for j in joints}
out["joint_parents"] = jparents
ibm = acc(skin["inverseBindMatrices"]).reshape(-1, 4, 4).transpose(0, 2, 1)
# mesh node
mesh_nodes = [i for i, n in enumerate(nodes) if "mesh" in n]
out["mesh_nodes"] = [(nodes[i].get("name"), nodes[i].get("skin"), (nodes[parent[i]]["name"] if i in parent else None)) for i in mesh_nodes]
# bind check: world(joint) @ ibm should equal identity-ish (mesh world at bind)
Mmesh = world(mesh_nodes[0])
errs = []
for k, j in enumerate(joints):
    W = world(j)
    E = W @ ibm[k]
    errs.append(float(np.abs(E - np.eye(4)).max()))
out["bind_consistency_max_abs_err (world(joint)@IBM - I)"] = max(errs)
# joint world positions (Y-up metres)
jpos = {nodes[j]["name"]: world(j)[:3, 3] for j in joints}
out["joint_pos_yup_m"] = {k: [round(float(x), 4) for x in v] for k, v in jpos.items() if k in (
    "root", "pelvis", "head", "upperarm_l", "upperarm_r", "hand_l", "foot_l", "ball_l", "thigh_l", "calf_l", "lowerarm_l")}
# joint orientation: local +Y along bone? check the direction to first child
ax_dot = {}
for j in joints:
    ch = [c for c in nodes[j].get("children", []) if c in joints]
    if not ch:
        continue
    W = world(j)
    d = world(ch[0])[:3, 3] - W[:3, 3]
    if np.linalg.norm(d) < 1e-6:
        continue
    d /= np.linalg.norm(d)
    ya = W[:3, 1] / np.linalg.norm(W[:3, 1])
    ax_dot[nodes[j]["name"]] = round(float(ya @ d), 4)
out["joint_localY_dot_dir_to_first_child_min"] = min(ax_dot.values())
out["joint_localY_dot_dir_to_first_child_worst"] = sorted(ax_dot.items(), key=lambda kv: kv[1])[:6]

prims = gj["meshes"][nodes[mesh_nodes[0]]["mesh"]]["primitives"]
out["n_primitives"] = len(prims)
pinfo = []
allW = []
allJ = []
allP = []
for p in prims:
    a = p["attributes"]
    pos = acc(a["POSITION"])
    J = acc(a["JOINTS_0"]).astype(int)
    Wt = acc(a["WEIGHTS_0"])
    extra = [k for k in a if k.startswith("JOINTS_") or k.startswith("WEIGHTS_")]
    nrm = acc(a["NORMAL"]) if "NORMAL" in a else None
    tan = acc(a["TANGENT"]) if "TANGENT" in a else None
    uv = acc(a["TEXCOORD_0"]) if "TEXCOORD_0" in a else None
    idx = acc(p["indices"]).astype(int).ravel()
    pinfo.append({"attributes": sorted(a.keys()), "vertices": len(pos), "triangles": len(idx) // 3, "mode": p.get("mode", 4),
                  "material": p.get("material"),
                  "normal_len_range": [float(np.linalg.norm(nrm, axis=1).min()), float(np.linalg.norm(nrm, axis=1).max())] if nrm is not None else None,
                  "tangent_w_values": sorted(set(np.round(tan[:, 3], 3).tolist())) if tan is not None else None,
                  "uv_range": [uv.min(0).tolist(), uv.max(0).tolist()] if uv is not None else None,
                  "unused_verts": int(len(pos) - len(np.unique(idx))),
                  "degenerate_tris": int(np.sum((idx[0::3] == idx[1::3]) | (idx[1::3] == idx[2::3]) | (idx[0::3] == idx[2::3])))})
    allW.append(Wt); allJ.append(J); allP.append(pos)
W = np.concatenate(allW); J = np.concatenate(allJ); Pp = np.concatenate(allP)
out["primitives"] = pinfo
s = W.sum(1)
out["weights"] = {"vertices": int(len(W)), "sum_min": float(s.min()), "sum_max": float(s.max()),
                  "unweighted (sum<1e-6)": int(np.sum(s < 1e-6)),
                  "nonzero_influence_hist": {int(k): int(v) for k, v in zip(*np.unique((W > 1e-6).sum(1), return_counts=True))},
                  "joint_index_max": int(J.max()), "joint_count": len(joints),
                  "min_nonzero_weight": float(W[W > 0].min())}
used = np.unique(J[W > 1e-6])
out["joints_with_weight"] = len(used)
out["joints_without_weight"] = [jn[k] for k in range(len(jn)) if k not in set(used.tolist())]
# mesh in world (bind) space
Pw = (Mmesh @ np.c_[Pp, np.ones(len(Pp))].T).T[:, :3]
out["bbox_yup_min"] = Pw.min(0).round(4).tolist()
out["bbox_yup_max"] = Pw.max(0).round(4).tolist()
out["height_m (Y extent)"] = round(float(np.ptp(Pw[:, 1])), 4)
# facing: nose = max Z among head verts
head_y = jpos["head"][1]
hm = Pw[:, 1] > head_y
inose = np.argmax(np.where(hm, Pw[:, 2], -9))
out["most_forward_head_vertex_yup"] = Pw[inose].round(4).tolist()
json.dump(out, open("/home/user/Sroskus/IronValley/Art/Previews/_review/base/r1/r1_glb_raw.json", "w"), indent=1)
for k, v in out.items():
    if k in ("joint_names", "joint_parents"):
        continue
    print(k, ":", v)
print("joint names:", jn)
