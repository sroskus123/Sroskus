"""R1 review: independent proportion measurements on the re-imported FBX (world metres, Z up,
facing -Y).  Own landmark definitions; compared with approximate adult-male references
(ANSUR II male means scaled 180/175.6 for lengths; Drillis&Contini segment ratios)."""
import json, math
import numpy as np
import bpy

IV = "/home/user/Sroskus/IronValley"
R1 = IV + "/Art/Previews/_review/base/r1"
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.fbx(filepath=IV + "/Art/Export/FBX/SK_Human_Base.fbx")
arm = [o for o in bpy.data.objects if o.type == 'ARMATURE'][0]
me = [o for o in bpy.data.objects if o.type == 'MESH'][0]
MW = arm.matrix_world
H = {b.name: np.array(MW @ b.head_local) for b in arm.data.bones}
T = {b.name: np.array(MW @ b.tail_local) for b in arm.data.bones}
co = np.array([me.matrix_world @ v.co for v in me.data.vertices])
names = [g.name for g in me.vertex_groups]
W = np.zeros((len(co), len(names)))
for v in me.data.vertices:
    for g in v.groups:
        W[v.index, g.group] = g.weight
dom = np.array(names)[W.argmax(1)]
m = {}
zmax = co[:, 2].max()
m["stature"] = float(zmax - co[:, 2].min())
# ---- head: menton = lowest point of the chin on the midline.  Midline profile: for 2 mm
# z-bins, the most forward (min y) midline vertex; menton = lowest bin before the profile
# jumps back to the neck (throat) -- detect the largest backward jump of forward-most y
mid = np.abs(co[:, 0]) < 0.004
prof = []
for z in np.arange(H["neck_01"][2], zmax, 0.002):
    sel = mid & (co[:, 2] >= z) & (co[:, 2] < z + 0.002)
    if sel.any():
        prof.append((z, co[sel, 1].min()))
prof = np.array(prof)
# the chin region is below the mouth: search 8..16 cm below eye level
eye_z = 1.687
reg = (prof[:, 0] > eye_z - 0.17) & (prof[:, 0] < eye_z - 0.06)
pz, py = prof[reg, 0], prof[reg, 1]
jump = np.diff(py)            # going up in z: at the menton, y jumps forward (more negative)
k = int(np.argmin(jump))
menton_z = float(pz[k + 1])
m["menton_z"] = menton_z
m["head_height_vertex_menton"] = float(zmax - menton_z)
m["heads_tall"] = m["stature"] / m["head_height_vertex_menton"]
head_sel = (co[:, 2] > menton_z + 0.10) & (dom == "head")
m["head_breadth_max_x"] = float(np.ptp(co[head_sel & (co[:, 2] > H["head"][2] + 0.02), 0]))
# head length: glabella (forward-most midline point above the eyes, below the forehead) to back
hl_sel = (co[:, 2] > eye_z) & (co[:, 2] < eye_z + 0.06) & (dom == "head")
m["head_length_y"] = float(np.ptp(co[(co[:, 2] > eye_z - 0.01) & (co[:, 2] < eye_z + 0.08) & (dom == "head"), 1]))
# ---- torso breadths (exclude arm/hand/finger dominated verts)
armish = np.array([any(s in d for s in ("upperarm", "lowerarm", "hand", "thumb", "index", "middle", "ring", "pinky")) for d in dom])
def breadth(z0, z1, excl_arm=True):
    s = (co[:, 2] > z0) & (co[:, 2] < z1)
    if excl_arm:
        s &= ~armish
    return float(np.ptp(co[s, 0])), float(np.ptp(co[s, 1]))
nip_z = float(co[(co[:, 1] == co[(co[:, 2] > 1.2) & (co[:, 2] < 1.4) & (np.abs(co[:, 0]) > 0.05) & ~armish, 1].min()), 2][0])
m["nipple_z (forward-most chest point off-midline)"] = nip_z
m["chest_breadth_at_nipple(excl arm verts)"], m["chest_depth_at_nipple"] = breadth(nip_z - 0.01, nip_z + 0.01)
# waist: minimum torso breadth between 0.98 and 1.15
wb = [(z, breadth(z, z + 0.01)[0]) for z in np.arange(0.98, 1.15, 0.01)]
zw, bw = min(wb, key=lambda t: t[1])
m["waist_z"], m["waist_breadth_min"] = float(zw), float(bw)
m["waist_depth"] = breadth(zw, zw + 0.01)[1]
hb = [(z, breadth(z, z + 0.01)[0]) for z in np.arange(0.78, 1.00, 0.01)]
zh, bh = max(hb, key=lambda t: t[1])
m["hip_z"], m["hip_breadth_max"] = float(zh), float(bh)
# crotch height: lowest midline vertex above 0.5 m
cr = mid & (co[:, 2] > 0.5) & (co[:, 2] < 1.0)
m["crotch_height"] = float(co[cr, 2].min())
# ---- joint based segments
L = lambda a, b: float(np.linalg.norm(H[a] - H[b]))
m["gh_joint_breadth (upperarm heads)"] = L("upperarm_l", "upperarm_r")
m["upper_arm (shoulder->elbow joint)"] = L("upperarm_l", "lowerarm_l")
m["forearm (elbow->wrist joint)"] = L("lowerarm_l", "hand_l")
m["upper/fore ratio"] = m["upper_arm (shoulder->elbow joint)"] / m["forearm (elbow->wrist joint)"]
m["thigh (hip->knee joint)"] = L("thigh_l", "calf_l")
m["shank (knee->ankle joint)"] = L("calf_l", "foot_l")
m["thigh/shank ratio"] = m["thigh (hip->knee joint)"] / m["shank (knee->ankle joint)"]
m["hip_joint_separation"] = L("thigh_l", "thigh_r")
m["shoulder_joint_z"] = float(H["upperarm_l"][2])
m["hip_joint_z"] = float(H["thigh_l"][2])
m["knee_joint_z"] = float(H["calf_l"][2])
m["ankle_joint_z"] = float(H["foot_l"][2])
m["neck_joint_z"], m["head_joint_z"] = float(H["neck_01"][2]), float(H["head"][2])
m["spine_03_tail_z"] = float(T["spine_03"][2])
m["spine_03_tail_to_neck_gap"] = float(np.linalg.norm(T["spine_03"] - H["neck_01"]))
m["clavicle_head"] = H["clavicle_l"].round(4).tolist()
# hand: along wrist -> middle fingertip; hand-dominated + finger verts of the left hand
hb_ = ["hand_l"] + [f"{f}_{i:02d}_l" for f in ("thumb", "index", "middle", "ring", "pinky") for i in (1, 2, 3)] + ["lowerarm_twist_01_l"]
hsel = np.isin(dom, hb_[:-1])
d = T["middle_03_l"] - H["hand_l"]; d /= np.linalg.norm(d)
proj = (co[hsel] - H["hand_l"]) @ d
m["hand_len_from_wrist_joint"] = float(proj.max())
# wrist crease estimate: narrowest cross-section of the arm near the wrist joint
fsel = np.isin(dom, ["lowerarm_l", "lowerarm_twist_01_l", "hand_l"])
t = (co - H["hand_l"]) @ d
widths = []
for s in np.arange(-0.04, 0.03, 0.004):
    sl = fsel & (t > s) & (t < s + 0.004)
    if sl.sum() > 8:
        P = co[sl] - H["hand_l"]
        P = P - np.outer(P @ d, d)
        widths.append((s, float(np.linalg.norm(P, axis=1).mean())))
s_min = min(widths, key=lambda x: x[1])[0]
m["wrist_narrowest_offset_from_joint (along hand axis)"] = float(s_min + 0.002)
m["hand_len_from_narrowest_wrist"] = float(proj.max() - (s_min + 0.002))
# hand breadth across metacarpals (index_01 .. pinky_01 heads level)
hbsel = np.isin(dom, ["hand_l"])
rdir = H["index_01_l"] - H["pinky_01_l"]; rdir -= d * (rdir @ d); rdir /= np.linalg.norm(rdir)
tk = (co - H["hand_l"]) @ d
knuck = (H["index_01_l"] - H["hand_l"]) @ d
ss = hbsel & (np.abs(tk - (knuck - 0.01)) < 0.01)
m["hand_breadth_metacarpal"] = float(np.ptp(co[ss] @ rdir))
# foot length: per left foot verts z < 0.12 and x > 0
fs = (co[:, 2] < 0.12) & (co[:, 0] > 0.05)
fd = T["ball_l"] - H["foot_l"]; fd[2] = 0; fd /= np.linalg.norm(fd)
pj = co[fs] @ fd
m["foot_length"] = float(np.ptp(pj))
m["foot_breadth"] = float(np.ptp(co[fs] @ np.cross(fd, [0, 0, 1])))
# arm span proxy with arms straight: 2 * (gh_x + upper + fore + hand from joint)
m["arm_span_proxy"] = 2 * (float(H["upperarm_l"][0]) + m["upper_arm (shoulder->elbow joint)"] + m["forearm (elbow->wrist joint)"] + m["hand_len_from_wrist_joint"])
m["elbow_height_arm_hanging"] = m["shoulder_joint_z"] - m["upper_arm (shoulder->elbow joint)"]
m["fingertip_height_arm_hanging"] = m["elbow_height_arm_hanging"] - m["forearm (elbow->wrist joint)"] - m["hand_len_from_wrist_joint"]
S = m["stature"]
# approximate references (adult male, 1.80 m): ANSUR II male means x 180/175.6 (lengths),
# Drillis & Contini ratios x H.  These are rough; only >~8-10 % deviations are flagged.
ref = {
    "head_height_vertex_menton": (0.232 * 1.0, "~23.2 cm adult male (vertex-menton), ~0.13H"),
    "head_breadth_max_x": (0.155, "ANSUR II head breadth ~15.5 cm"),
    "head_length_y": (0.199, "ANSUR II head length ~19.9 cm (glabella-opisthocranion)"),
    "chest_breadth_at_nipple(excl arm verts)": (0.33, "ANSUR II chest breadth ~32-33 cm"),
    "waist_breadth_min": (0.31, "ANSUR II waist breadth ~31 cm (varies with weight)"),
    "hip_breadth_max": (0.35, "ANSUR II hip breadth ~34.5-35.5 cm"),
    "crotch_height": (0.47 * S, "~0.47-0.48 H"),
    "shoulder_joint_z": (0.80 * S, "GH centre ~3-4 cm below acromion height 0.818H"),
    "hip_joint_z": (0.530 * S, "Drillis 0.530H (greater trochanter)"),
    "knee_joint_z": (0.285 * S, "Drillis 0.285H"),
    "upper_arm (shoulder->elbow joint)": (0.172 * S, "GH-centre to elbow-centre ~0.17-0.175H (humerus ~0.196H max length)"),
    "forearm (elbow->wrist joint)": (0.146 * S, "Drillis 0.146H"),
    "thigh (hip->knee joint)": (0.245 * S, "Drillis 0.245H"),
    "shank (knee->ankle joint)": (0.246 * S, "Drillis 0.246H"),
    "hand_len_from_narrowest_wrist": (0.199, "ANSUR II hand length ~19.4 cm x1.025"),
    "hand_breadth_metacarpal": (0.091, "ANSUR II hand breadth ~8.9 cm x1.025"),
    "foot_length": (0.277, "ANSUR II foot length ~27.0 cm x1.025"),
    "hip_joint_separation": (0.18, "HJC separation ~17-19 cm (Harrington/Bell regression, male)"),
    "arm_span_proxy": (1.03 * S, "arm span ~1.00-1.06 H"),
}
cmp_ = {}
for k, (rv, src) in ref.items():
    dv = (m[k] - rv) / rv
    cmp_[k] = {"model_cm": round(m[k] * 100, 1), "ref_cm": round(rv * 100, 1), "dev_pct": round(dv * 100, 1), "ref_source": src,
               "flag": abs(dv) > 0.08}
res = {"measurements_m": {k: (round(v, 4) if isinstance(v, float) else v) for k, v in m.items()}, "vs_reference": cmp_}
json.dump(res, open(R1 + "/r1_measure.json", "w"), indent=1)
for k, v in res["measurements_m"].items():
    print(f"{k:55s} {v}")
print()
for k, v in cmp_.items():
    print(f"{k:45s} model {v['model_cm']:7.1f}  ref {v['ref_cm']:7.1f}  dev {v['dev_pct']:6.1f}%  {'FLAG' if v['flag'] else ''}")
