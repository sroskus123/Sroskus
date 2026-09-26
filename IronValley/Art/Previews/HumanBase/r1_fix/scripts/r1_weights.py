# Copy of the R1 reviewer's script (Art/Previews/_review/base/r1/r1_weights.py) with the output folder
# redirected to Art/Previews/HumanBase/r1_fix (re-verification of the R1 fixes). Measurement code unchanged.
"""R1 review: weight-field quality on the re-imported FBX.
- dominant-region islands per bone (stray vertices assigned to a far bone)
- spikes: |w_v - mean(w_neighbours)| per bone
- influence of anatomically distant bones (e.g. head weights on the hand)
- L/R symmetry via mirrored positions (own mirror by KD-tree, not hm08.mirror)
- max weight-gradient per bone (weight change per cm along edges)"""
import json
import numpy as np
import bpy
from mathutils.kdtree import KDTree

IV = "/home/user/Sroskus/IronValley"
R1 = "/home/user/Sroskus/IronValley/Art/Previews/HumanBase/r1_fix"
REV = "/home/user/Sroskus/IronValley/Art/Previews/_review/base/r1"
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.fbx(filepath=IV + "/Art/Export/FBX/SK_Human_Base.fbx")
arm = [o for o in bpy.data.objects if o.type == 'ARMATURE'][0]
me = [o for o in bpy.data.objects if o.type == 'MESH'][0]
co = np.array([me.matrix_world @ v.co for v in me.data.vertices])
names = [g.name for g in me.vertex_groups]
nv, nb = len(co), len(names)
W = np.zeros((nv, nb))
for v in me.data.vertices:
    for g in v.groups:
        W[v.index, g.group] = g.weight
edges = np.array([e.vertices[:] for e in me.data.edges])
nbrs = [[] for _ in range(nv)]
for a, b in edges:
    nbrs[a].append(b); nbrs[b].append(a)
out = {}
# islands of the dominant region (w > 0.5)
isl = {}
for j, n in enumerate(names):
    s = np.nonzero(W[:, j] > 0.5)[0]
    if len(s) == 0:
        continue
    S = set(s.tolist()); seen = set(); comps = []
    for v in s:
        if v in seen:
            continue
        st = [v]; seen.add(v); c = 0
        while st:
            x = st.pop(); c += 1
            for y in nbrs[x]:
                if y in S and y not in seen:
                    seen.add(y); st.append(y)
        comps.append(c)
    if len(comps) > 1:
        isl[n] = sorted(comps, reverse=True)
out["bones_with_multiple_dominant_islands(w>0.5)"] = isl
# spikes
Wn = np.zeros_like(W)
deg = np.array([len(x) for x in nbrs])
for a, b in edges:
    Wn[a] += W[b]; Wn[b] += W[a]
Wn /= deg[:, None]
sp = np.abs(W - Wn)
top = np.argsort(sp.max(1))[::-1][:15]
out["spike_count(|w-mean_nbr|>0.3)"] = int((sp.max(1) > 0.3).sum())
out["spike_count(|w-mean_nbr|>0.2)"] = int((sp.max(1) > 0.2).sum())
out["top_spikes"] = [{"v": int(v), "pos": co[v].round(3).tolist(), "bone": names[int(sp[v].argmax())],
                      "w": round(float(W[v, sp[v].argmax()]), 3), "nbr_mean": round(float(Wn[v, sp[v].argmax()]), 3)} for v in top]
# spike by bone
sb = {}
for v in np.nonzero(sp.max(1) > 0.2)[0]:
    b = names[int(sp[v].argmax())]
    sb[b] = sb.get(b, 0) + 1
out["spikes>0.2_by_bone"] = sb
# gradient: max |dw| / edge length per bone (1/cm)
L = np.linalg.norm(co[edges[:, 0]] - co[edges[:, 1]], axis=1) * 100
G = np.abs(W[edges[:, 0]] - W[edges[:, 1]]) / np.maximum(L, 1e-6)[:, None]
gmax = G.max(0)
out["max_weight_gradient_per_cm_top"] = sorted([(names[j], round(float(gmax[j]), 3)) for j in range(nb)], key=lambda t: -t[1])[:12]
# distant influences: a vertex influenced by a bone whose head/tail segment is > 25 cm away
Hh = {b.name: np.array(arm.matrix_world @ b.head_local) for b in arm.data.bones}
Tt = {b.name: np.array(arm.matrix_world @ b.tail_local) for b in arm.data.bones}
far = []
for j, n in enumerate(names):
    s = np.nonzero(W[:, j] > 0.01)[0]
    h, t = Hh[n], Tt[n]
    d = t - h; l2 = d @ d
    tt = np.clip(((co[s] - h) @ d) / l2, 0, 1)
    dist = np.linalg.norm(co[s] - (h + tt[:, None] * d), axis=1)
    k = np.argmax(dist)
    far.append((n, round(float(dist[k] * 100), 1), round(float(W[s[k], j]), 3), co[s[k]].round(3).tolist()))
out["max_distance_vertex_to_influencing_bone_segment_cm_top"] = sorted(far, key=lambda t: -t[1])[:12]
# own mirror symmetry check
kd = KDTree(nv)
for i, c in enumerate(co):
    kd.insert(c, i)
kd.balance()
mirror = np.array([kd.find((-c[0], c[1], c[2]))[1] for c in co])
mdist = np.array([kd.find((-c[0], c[1], c[2]))[2] for c in co])
perm = [names.index(n[:-2] + ("_r" if n.endswith("_l") else "_l")) if n.endswith(("_l", "_r")) else j for j, n in enumerate(names)]
Wm = W[mirror][:, perm]
ok = mdist < 1e-4
out["geometry_mirror_max_dist_m"] = float(mdist.max())
out["weights_mirror_max_abs_diff(verts with exact mirror)"] = float(np.abs(W[ok] - Wm[ok]).max())
json.dump(out, open(R1 + "/r1_weights.json", "w"), indent=1)
for k, v in out.items():
    print(k, ":", v)
