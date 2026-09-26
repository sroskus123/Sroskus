"""
human_base.py -- Iron Valley rigged human base  (SK_Human_Base)

The one human every Iron Valley character, the first-person arms and the hands derive from.
Deterministic; re-running it rebuilds everything from the vendored CC0 data.

    python3 human_base.py                       # build + validate + render + export
    python3 human_base.py --stages build,validate,export
    python3 human_base.py --stages render        # renders only (reuses human_base.blend)

Inputs (all CC0 1.0, MakeHuman / MPFB2, vendored from the PyPI wheel anny 0.6.0, see
Art/ThirdParty/mpfb2/SOURCE.md):  3dobjs/base.obj (hm08), targets (macro + 2 measure targets),
rigs/standard/rig.game_engine.json + weights.game_engine.json, mesh_metadata.

Pipeline
  1. load hm08 (19 158 verts incl. helper geometry + joint cubes), convert to Blender frame
  2. apply MakeHuman macro targets (male, 28 y, muscle 0.70, weight 0.50, height 0.50,
     proportions 0.50, race 1/3 each) + measure targets (upper arm longer, forearm shorter)
     to ALL vertices (joint cubes move with the body)
  3. uniform scale to exactly 1.80 m (sole -> vertex), feet on Z = 0, origin on MakeHuman's
     ground joint, facing -Y
  4. joints from rig.game_engine.json exactly as MPFB/anny read them (CUBE = mean of the joint
     cube vertices, MEAN = mean of listed vertices), bone roll from the file; the zero-weight
     'Root' bone is renamed 'root' and placed at the origin with identity orientation
  5. keep only the 'body' group (13 380 verts, closed 2-manifold, quads, hm08 UVs); remove all
     helper geometry (eyes, eyelashes, teeth, tongue, tights, skirt, hair, genital helpers, joint
     cubes)
  6. skin with weights.game_engine.json (vertex indices are unchanged by targets, body indices
     0..13379 are kept 1:1): symmetrised across the mirror plane (hm08.mirror), 4 UE4-mannequin
     twist bones added (upperarm/lowerarm_twist_01_l/r) with ramped weights, limited to 4
     influences per vertex (mirror-exact), renormalised to 1
  7. rest pose: A-pose -- upper arms as modelled by hm08 (~50 deg below horizontal), elbows
     straightened from the modelled ~47 deg to 15 deg flexion, pose applied as the new rest
  8. validate (geometry, stature, facing, skeleton names/hierarchy, skin, joints vs mesh,
     proportions, 12 deformation test poses + 2 with driven twist bones), save .blend, render
     evidence, export FBX (Unreal) + GLB, re-import both
Spec: Art/Reference/HUMAN_BASE_spec.md
"""

import argparse
import json
import math
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))

import bpy                      # noqa: E402
import numpy as np              # noqa: E402
from mathutils import Vector, Matrix   # noqa: E402

import ivlib                    # noqa: E402
import ivchar as C              # noqa: E402

IV = C.IV_ROOT
MP = C.MPFB_DIR
BLEND = os.path.join(HERE, "human_base.blend")
PREV = os.path.join(IV, "Art", "Previews", "HumanBase")
FBX_PATH = os.path.join(IV, "Art", "Export", "FBX", "SK_Human_Base.fbx")
GLB_PATH = os.path.join(IV, "Art", "Export", "GLB", "Human_Base.glb")
REPORT = os.path.join(PREV, "HumanBase_validation.json")

# ---------------------------------------------------------------- design inputs
STATURE = 1.80                      # m, sole to vertex
AGE_YEARS = 28.0
MACRO = dict(gender=1.0, age=C.years_to_age_value(AGE_YEARS), muscle=0.70, weight=0.50,
             height=0.50, proportions=0.50,
             race={"african": 1 / 3, "asian": 1 / 3, "caucasian": 1 / 3})
# MakeHuman 'measure' modifiers (targets/arms).  hm08's joint layout gives a 26 cm upper arm
# and a 28 cm forearm at 1.80 m (ratio 0.95; anatomical ~1.2-1.3).  These two targets move the
# elbow (mesh + joint cube) ~3.6 cm distally and shorten the forearm ~2.4 cm (shoulder->wrist
# +1.3 cm, arm span ~1.91 m = 1.06 x stature).
LOCAL_TARGETS = {"arms/measure-upperarm-length-incr": 0.50,
                 "arms/measure-lowerarm-length-decr": 0.50}
MAX_INFLUENCES = 4
REST_ELBOW_FLEX = 15.0              # deg, A-pose elbow flexion
ROOT_TAIL = (0.0, 0.20, 0.0)        # root bone points +Y, roll 0 -> identity orientation
ARMATURE_NAME = "Armature"          # see spec 'Export': Unreal FBX import of Blender armatures
SKELETON_DATA_NAME = "SKEL_Human_Base"
MESH_NAME = "SK_Human_Base"
BODY_VERTS = 13380
RENDER_SAMPLES = 24
# UE4-mannequin twist bones added on top of the MPFB rig (see spec 'Twist bones'):
# (name, parent, head fraction, tail fraction along the parent)
TWIST_SPECS = [(f"{b}_twist_01_{s}", f"{b}_{s}", fh, ft) for s in ("l", "r")
               for b, fh, ft in (("upperarm", 0.10, 0.60), ("lowerarm", 0.50, 1.00))]
# weight ramps: share of the parent's weight moved to the twist bone
TWIST_RAMPS = {"lowerarm": (0.30, 0.70, True),     # 0 -> 1 from 30 % to 70 % of the forearm
               "upperarm": (0.20, 0.55, False)}    # 1 -> 0 from 20 % to 55 % of the upper arm
TWIST_DRIVE = {"lower": 0.5, "upper": 0.5}


def log(*a):
    print("[human_base]", *a, flush=True)


# =============================================================================
# build
# =============================================================================

def build():
    t0 = time.time()
    ivlib.reset_scene(samples=RENDER_SAMPLES)
    col = ivlib.collection("HumanBase")
    info = {"design_inputs": {"stature_m": STATURE, "age_years": AGE_YEARS,
                              "macro": {k: (round(v, 6) if isinstance(v, float) else v)
                                        for k, v in MACRO.items()},
                              "local_targets": LOCAL_TARGETS, "max_influences": MAX_INFLUENCES,
                              "rest_elbow_flexion_deg": REST_ELBOW_FLEX}}

    obj = C.load_obj(os.path.join(MP, "3dobjs", "base.obj"))
    meta = C.load_json(os.path.join(MP, "mesh_metadata", "basemesh_vertex_groups.json"))
    assert meta["body"] == [[0, BODY_VERTS - 1]], meta["body"]
    bf = obj.groups["body"]["f"]
    assert max(max(f) for f in bf) == BODY_VERTS - 1 and min(min(f) for f in bf) == 0
    helper_ranges = meta["HelperGeometry"] + meta["JointCubes"]
    info["source_mesh"] = {"vertices": int(len(obj.V)), "uvs": int(len(obj.VT)),
                           "groups": len(obj.groups), "body_faces": len(bf),
                           "body_vertices": BODY_VERTS,
                           "removed_vertex_ranges (helpers + joint cubes)": helper_ranges}

    Vb = C.mh_to_blender(obj.V)
    mt = C.macro_target_weights(**MACRO)
    V1, st_macro = C.apply_targets(Vb, mt, os.path.join(MP, "targets", "macrodetails"))
    V2, st_local = C.apply_targets(V1, LOCAL_TARGETS, os.path.join(MP, "targets"))
    info["targets"] = {"macrodetails": st_macro, "local": st_local}

    raw_h = float(np.ptp(V2[:BODY_VERTS, 2]))
    s = STATURE / raw_h
    V3 = V2 * s
    ground = V3[obj.group_vertices("joint-ground")].mean(0)
    off = np.array([0.0, ground[1], V3[:BODY_VERTS, 2].min()])
    V3 = V3 - off
    body_x_asym = float(abs(V3[:BODY_VERTS, 0].max() + V3[:BODY_VERTS, 0].min()))
    info["scale"] = {"height_before_scale_m": round(raw_h, 5), "uniform_scale": round(s, 6),
                     "translation_m": [round(float(v), 5) for v in -off],
                     "ground_joint_after_m": [round(float(v), 5) for v in (ground - off)],
                     "body_x_asymmetry_m": round(body_x_asym, 6)}

    rig = C.load_json(os.path.join(MP, "rigs", "standard", "rig.game_engine.json"))
    bones = C.compute_bones(rig, V3, obj, rename={"Root": "root"})
    mpfb_root = {k: [round(float(x), 5) for x in bones["root"][k]] for k in ("head", "tail")}
    mpfb_root["roll"] = bones["root"]["roll"]
    bones["root"].update(head=np.zeros(3), tail=np.array(ROOT_TAIL), roll=0.0)
    info["root_override"] = {"mpfb_computed": mpfb_root, "used": {"head": [0, 0, 0],
                             "tail": list(ROOT_TAIL), "roll": 0.0},
                             "reason": "Root carries zero skin weight in weights.game_engine.json; "
                                       "placed at the origin with world-aligned axes like the "
                                       "Unreal mannequin root. No deformation change."}
    bones = C.add_twist_bones(bones, TWIST_SPECS)
    bone_names = list(bones.keys())

    # ---- mesh: body group only
    me_ob = C.mesh_from_arrays(MESH_NAME, V3[:BODY_VERTS], bf, obj.groups["body"]["t"], obj.VT, col)
    mat = C.clay_material("M_Human_Base", color=(0.60, 0.58, 0.55), rough=0.55)
    me_ob.data.materials.append(mat)

    # ---- armature
    arm = C.build_armature(ARMATURE_NAME, bones, col)
    arm.data.name = SKELETON_DATA_NAME
    arm.data.display_type = 'OCTAHEDRAL'
    arm.show_in_front = True

    # ---- weights
    wj = C.load_json(os.path.join(MP, "rigs", "standard", "weights.game_engine.json"))
    vf = np.full(len(obj.V), -1, dtype=np.int64)
    vf[:BODY_VERTS] = np.arange(BODY_VERTS)
    D = C.dense_weights_from_json(wj, bone_names, BODY_VERTS, rename={"Root": "root"},
                                  vertex_filter=vf)
    mirror, mflags = C.load_mirror(os.path.join(MP, "mesh_metadata", "hm08.mirror"), BODY_VERTS,
                                   with_flags=True)
    asym_src = C.weight_asymmetry(D / np.maximum(D.sum(1, keepdims=True), 1e-12), bone_names, mirror)
    Ds = C.symmetrize_weights(D, bone_names, mirror)
    for side in ("l", "r"):
        for seg, (s0, s1, tt) in TWIST_RAMPS.items():
            b = bones[f"{seg}_{side}"]
            Ds = C.split_weights_along_bone(Ds, bone_names, V3[:BODY_VERTS], b["head"], b["tail"],
                                            f"{seg}_{side}", f"{seg}_twist_01_{side}", s0, s1, tt)
    _, lst = C.limit_and_normalize(Ds, MAX_INFLUENCES)        # stats only
    D4 = C.limit_symmetric(Ds, bone_names, mirror, mflags, MAX_INFLUENCES)
    chg = np.abs(D4 - Ds).sum(1)
    info["weights"] = dict(lst, source_bones=len(wj["weights"]),
                           source_lr_asymmetry=asym_src,
                           symmetrized=True, twist_ramps=TWIST_RAMPS,
                           after_symmetrize_and_limit_lr_asymmetry=C.weight_asymmetry(D4, bone_names, mirror),
                           limit_change_L1_mean=round(float(chg.mean()), 6),
                           limit_change_L1_max=round(float(chg.max()), 5))
    C.bind_mesh(me_ob, arm, D4, bone_names)

    # ---- rest pose: straighten elbows to REST_ELBOW_FLEX, keep everything else as modelled
    C.reset_pose(arm)
    rp = {}
    for side in ("l", "r"):
        u = C.bone_dir(arm, f"upperarm_{side}")
        f = C.bone_dir(arm, f"lowerarm_{side}")
        flex = C.angle_between(u, f)
        axis = u.cross(f).normalized()
        C.rotate_bone_world(arm, f"lowerarm_{side}", axis, -(flex - REST_ELBOW_FLEX))
        rp[side] = {"modelled_elbow_flexion_deg": round(flex, 2),
                    "upperarm_below_horizontal_deg": round(math.degrees(math.asin(-u.z)), 2)}
    C.apply_pose_as_rest(arm, [me_ob])
    for side in ("l", "r"):
        u = C.bone_dir(arm, f"upperarm_{side}")
        f = C.bone_dir(arm, f"lowerarm_{side}")
        rp[side]["rest_elbow_flexion_deg"] = round(C.angle_between(u, f), 2)
    info["rest_pose"] = rp

    # feet on the ground after re-posing (legs unchanged, but check)
    co = C.mesh_arrays(me_ob)
    info["rest_bbox_m"] = {"min": [round(float(v), 5) for v in co.min(0)],
                           "max": [round(float(v), 5) for v in co.max(0)]}
    bpy.context.view_layer.objects.active = arm
    ivlib.deselect_all()
    os.makedirs(os.path.dirname(BLEND), exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=BLEND, compress=True)
    info["build_seconds"] = round(time.time() - t0, 1)
    log(f"built in {info['build_seconds']} s -> {BLEND}")
    return arm, me_ob, info


def load_scene():
    bpy.ops.wm.open_mainfile(filepath=BLEND)
    return bpy.data.objects[ARMATURE_NAME], bpy.data.objects[MESH_NAME]


# =============================================================================
# measurements
# =============================================================================

def measurements(arm, body):
    C.reset_pose(arm)
    co = C.mesh_arrays(body)
    names = [b.name for b in arm.data.bones]
    D = C.read_weights(body, names)
    H = lambda n: np.array(arm.data.bones[n].head_local)     # noqa: E731
    T = lambda n: np.array(arm.data.bones[n].tail_local)     # noqa: E731
    Ln = lambda n: float(np.linalg.norm(T(n) - H(n)))        # noqa: E731
    m = {}
    m["stature_m"] = float(co[:, 2].max() - co[:, 2].min())
    # head height: vertex (top) to menton (lowest point of the chin on the front midline)
    hj = H("head")
    mid = np.abs(co[:, 0]) < 0.003
    lower = mid & (co[:, 1] < hj[1] - 0.04) & (co[:, 2] > hj[2] - 0.12) & (co[:, 2] < hj[2])
    ymin = co[lower, 1].min()
    cand = lower & (co[:, 1] < ymin + 0.025)
    i_ch = np.nonzero(cand)[0][np.argmin(co[cand, 2])]
    i_top = int(np.argmax(co[:, 2]))
    m["head_height_menton_to_vertex_m"] = float(co[i_top, 2] - co[i_ch, 2])
    m["_menton_vertex"] = int(i_ch)
    m["_vertex_top"] = i_top
    m["head_bone_m"] = Ln("head")
    m["neck_bone_m"] = Ln("neck_01")
    m["shoulder_joint_breadth_m"] = float(np.linalg.norm(H("upperarm_l") - H("upperarm_r")))
    sj = H("upperarm_l")
    near = np.linalg.norm(co - sj, axis=1) < 0.10
    m["shoulder_breadth_deltoids_m"] = float(2 * co[near, 0].max())
    m["upper_arm_m"] = Ln("upperarm_l")
    m["forearm_m"] = Ln("lowerarm_l")
    # hand: wrist joint to farthest hand/finger-dominated vertex along wrist->middle fingertip
    handbones = ["hand_l"] + [f"{f}_{i:02d}_l" for f in C.FINGERS for i in (1, 2, 3)]
    hm = C.dominant_bone_mask(D, names, handbones)
    w = H("hand_l")
    d = T("middle_03_l") - w
    d /= np.linalg.norm(d)
    m["hand_length_m"] = float(((co[hm] - w) @ d).max())
    m["hand_breadth_m"] = float(np.ptp((co[C.dominant_bone_mask(D, names, ['hand_l'])] - w)
                                       @ np.cross(d, [0, 0, 1]) / np.linalg.norm(np.cross(d, [0, 0, 1]))))
    m["thigh_m"] = Ln("thigh_l")
    m["shin_m"] = float(np.linalg.norm(H("foot_l") - H("calf_l")))
    fm = C.dominant_bone_mask(D, names, ["foot_l", "ball_l"])
    fd = T("ball_l") - H("foot_l")
    fd[2] = 0
    fd /= np.linalg.norm(fd)
    proj = co[fm] @ fd
    m["foot_length_m"] = float(proj.max() - proj.min())
    m["shoulder_joint_height_m"] = float(sj[2])
    m["hip_joint_height_m"] = float(H("thigh_l")[2])
    m["knee_joint_height_m"] = float(H("calf_l")[2])
    m["ankle_joint_height_m"] = float(H("foot_l")[2])
    m["hip_joint_breadth_m"] = float(np.linalg.norm(H("thigh_l") - H("thigh_r")))
    # arm span estimate: 2 * (shoulder joint x + upper arm + forearm + hand)
    m["arm_span_estimate_m"] = float(2 * (sj[0] + m["upper_arm_m"] + m["forearm_m"] + m["hand_length_m"]))
    m["elbow_height_if_arm_hanging_m"] = float(sj[2] - m["upper_arm_m"])
    m["wrist_height_if_arm_hanging_m"] = float(sj[2] - m["upper_arm_m"] - m["forearm_m"])
    m["fingertip_height_if_arm_hanging_m"] = float(sj[2] - m["upper_arm_m"] - m["forearm_m"] - m["hand_length_m"])
    return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in m.items()}


# Plausibility ranges for an adult male of 1.80 m (approximate, from general anthropometric
# literature -- NOT measured data; used only to flag gross errors, cf. GEO-01's ~5 % target).
PLAUSIBLE = {
    "head_height_menton_to_vertex_m": (0.215, 0.245),
    "upper_arm_m": (0.285, 0.335),
    "forearm_m": (0.245, 0.275),
    "hand_length_m": (0.185, 0.215),
    "thigh_m": (0.415, 0.465),
    "shin_m": (0.415, 0.465),
    "foot_length_m": (0.255, 0.290),
    "arm_span_estimate_m": (1.78, 1.92),
    "shoulder_joint_height_m": (1.40, 1.48),
    "hip_joint_height_m": (0.90, 0.98),
    "knee_joint_height_m": (0.48, 0.54),
}


# =============================================================================
# validation
# =============================================================================

def validate(arm, body, info):
    t0 = time.time()
    rep = {"generated_by": f"human_base.py (ivchar {C.IVCHAR_VERSION}, ivlib {ivlib.LIB_VERSION})",
           "blender": bpy.app.version_string, "time": time.strftime("%Y-%m-%d %H:%M:%S")}
    rep.update(info)
    checks = {}
    C.reset_pose(arm)
    # geometry (ivlib.mesh_checks); its 'skin.non_rigid_verts' is a weapon (rigid) criterion
    mc = ivlib.mesh_checks(body)
    mc.pop("skin", None)
    rep["mesh"] = mc
    co = C.mesh_arrays(body)
    tris, area, nn = C.face_metrics(body, co)
    vol = float(np.sum(np.einsum("ij,ij->i", co[tris[:, 0]], np.cross(co[tris[:, 1]], co[tris[:, 2]]))) / 6.0)
    rep["mesh"]["signed_volume_m3"] = round(vol, 5)
    geo_ok = (mc["non_manifold_edges"] == 0 and mc["boundary_edges"] == 0 and mc["loose_verts"] == 0
              and mc["zero_area_faces"] == 0 and mc["duplicate_faces"] == 0
              and mc["inconsistent_normal_edges"] == 0 and mc["faces_opposing_vertex_normals"] == 0
              and not mc["missing_uvs"] and mc.get("uv_out_of_bounds_loops", 0) == 0 and vol > 0)
    checks["geometry_closed_manifold_uv_normals"] = "PASS" if geo_ok else "FAIL"

    # dimensions
    dims = mc["dimensions_cm"]
    bb_min = mc["bbox_min_m"]
    rep["dimensions_check"] = {"height_cm": dims[2], "feet_min_z_m": bb_min[2]}
    checks["stature_1.80_m_feet_on_z0"] = "PASS" if (abs(dims[2] - 180.0) < 0.05 and abs(bb_min[2]) < 1e-4) else "FAIL"
    # facing -Y: nose tip is the most forward head vertex -> must have negative y and x ~ 0
    head_mask = co[:, 2] > arm.data.bones["head"].head_local.z
    inose = np.nonzero(head_mask)[0][np.argmin(co[head_mask, 1])]
    rep["facing"] = {"most_forward_head_vertex": int(inose), "position_m": [round(float(v), 4) for v in co[inose]]}
    checks["facing_minus_Y"] = "PASS" if (co[inose, 1] < -0.05 and abs(co[inose, 0]) < 0.01) else "FAIL"

    # skeleton
    parents = dict(C.UE_MANNEQUIN_PARENTS)
    parents.update(C.UE_MANNEQUIN_TWIST_PARENTS)
    hr = C.hierarchy_report(arm, expected=list(C.UE_MANNEQUIN_CORE) + C.UE_MANNEQUIN_TWIST,
                            parents=parents)
    rep["skeleton"] = hr
    rep["skeleton"]["bones"] = {b.name: {"parent": b.parent.name if b.parent else None,
                                         "head_m": [round(v, 4) for v in b.head_local],
                                         "tail_m": [round(v, 4) for v in b.tail_local],
                                         "length_m": round(b.length, 4),
                                         "roll_deg": None,
                                         "deform": b.use_deform}
                                for b in arm.data.bones}
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode='EDIT')
    for eb in arm.data.edit_bones:
        rep["skeleton"]["bones"][eb.name]["roll_deg"] = round(math.degrees(eb.roll), 3)
    bpy.ops.object.mode_set(mode='OBJECT')
    checks["skeleton_ue_mannequin_names_hierarchy"] = "PASS" if hr["ok"] else "FAIL"
    # L/R symmetry of joints
    asym = 0.0
    for b in arm.data.bones:
        if b.name.endswith("_l"):
            o = arm.data.bones[b.name[:-2] + "_r"]
            p = Vector(b.head_local)
            q = Vector(o.head_local)
            asym = max(asym, (Vector((-p.x, p.y, p.z)) - q).length)
    rep["skeleton"]["max_lr_joint_asymmetry_m"] = round(asym, 6)

    # skin
    sk = C.skin_report(body, arm, MAX_INFLUENCES)
    rep["skin"] = sk
    checks["skin_all_weighted_max4_sum1"] = "PASS" if sk["ok"] else "FAIL"

    # bone placement vs mesh: every joint (bone head) must lie INSIDE the closed body; the tail
    # of an MPFB leaf bone (fingertips, toe tip, top of head) is MPFB's tip marker and must lie
    # within 1 cm of the surface (inside or outside); twist-bone tails must be inside.
    bvh = C.mesh_bvh(body, co)
    jin = {}
    bad = []
    for b in arm.data.bones:
        if b.name == "root":
            continue
        inside, dist = C.inside_mesh(bvh, b.head_local)
        jin[f"{b.name}.head"] = {"inside": inside, "dist_to_surface_m": round(dist, 4)}
        if not inside:
            bad.append(f"{b.name}.head outside")
        if not b.children:
            inside, dist = C.inside_mesh(bvh, b.tail_local)
            jin[f"{b.name}.tail"] = {"inside": inside, "dist_to_surface_m": round(dist, 4)}
            if "_twist_" in b.name:
                if not inside:          # twist bones lie on the limb axis: tail must be inside
                    bad.append(f"{b.name}.tail outside")
            elif dist > 0.01:           # MPFB terminal bones: tail = tip marker on the surface
                bad.append(f"{b.name}.tail {dist * 100:.1f} cm from surface")
    rep["joints_vs_mesh"] = {"problems": bad, "detail": jin}
    checks["joints_inside_mesh_tips_on_surface"] = "PASS" if not bad else "FAIL"

    # proportions
    ms = measurements(arm, body)
    rep["measurements"] = ms
    flags = {k: {"value": ms[k], "range": v, "ok": v[0] <= ms[k] <= v[1]} for k, v in PLAUSIBLE.items()}
    rep["measurement_plausibility"] = flags
    checks["proportions_within_plausible_ranges"] = "PASS" if all(f["ok"] for f in flags.values()) else "FAIL"

    rep["checks"] = checks
    rep["validation_seconds"] = round(time.time() - t0, 1)
    return rep


# =============================================================================
# deformation test poses
# =============================================================================

X = Vector((1, 0, 0))
Y = Vector((0, 1, 0))
Z = Vector((0, 0, 1))


def p_arms_raised(arm):
    for side, sg in (("l", -1), ("r", 1)):
        ax = Y * sg
        C.rotate_bone_world(arm, f"clavicle_{side}", ax, 22)
        C.rotate_bone_world(arm, f"upperarm_{side}", ax, 105)


def p_arms_forward(arm):
    for side, sx in (("l", 1), ("r", -1)):
        C.aim_bone(arm, f"upperarm_{side}", (0.15 * sx, -1.0, 0.0))
        C.aim_bone(arm, f"lowerarm_{side}", (0.05 * sx, -1.0, 0.03))


def p_arms_crossed(arm):
    C.aim_bone(arm, "upperarm_l", (0.22, -0.55, -0.80))
    C.aim_bone(arm, "lowerarm_l", (-0.96, -0.12, 0.25))
    C.aim_bone(arm, "upperarm_r", (-0.22, -0.60, -0.77))
    C.aim_bone(arm, "lowerarm_r", (0.96, -0.22, 0.14))


def p_elbows_120(arm):
    for side in ("l", "r"):
        u = C.bone_dir(arm, f"upperarm_{side}")
        C.aim_bone(arm, f"lowerarm_{side}", u)
        fwd = Vector((0, -1, 0))
        fwd_p = (fwd - u * fwd.dot(u)).normalized()
        C.rotate_bone_world(arm, f"lowerarm_{side}", u.cross(fwd_p), 120.0)


def p_squat(arm, hip=100.0, knee=120.0):
    rest_ank = (C.bone_world(arm, "foot_l") + C.bone_world(arm, "foot_r")) * 0.5
    for side in ("l", "r"):
        C.rotate_bone_rest_axis(arm, f"thigh_{side}", -X, hip)
        C.rotate_bone_rest_axis(arm, f"calf_{side}", X, knee)
        C.rotate_bone_rest_axis(arm, f"foot_{side}", -X, knee - hip)
    C.rotate_bone_rest_axis(arm, "spine_01", X, 14)
    C.rotate_bone_rest_axis(arm, "spine_02", X, 10)
    C.rotate_bone_rest_axis(arm, "neck_01", -X, 12)
    C.rotate_bone_rest_axis(arm, "head", -X, 8)
    now = (C.bone_world(arm, "foot_l") + C.bone_world(arm, "foot_r")) * 0.5
    pb = arm.pose.bones["pelvis"]
    Mw = arm.matrix_world @ pb.matrix
    pb.matrix = arm.matrix_world.inverted() @ (Matrix.Translation(rest_ank - now) @ Mw)
    bpy.context.view_layer.update()


def p_spine_twist(arm):
    for n, a in (("spine_01", 15), ("spine_02", 20), ("spine_03", 20), ("neck_01", 5)):
        C.rotate_bone_rest_axis(arm, n, Z, a)


def p_wrist_flex(arm):
    # left hand flexion 70 deg (palm towards forearm), right hand extension 60 deg
    for side, ang in (("l", 70.0), ("r", -60.0)):
        _, d, r, n = C.palm_frame(arm, side)
        C.rotate_bone_rest_axis(arm, f"hand_{side}", d.cross(n), ang)


def p_wrist_twist(arm):
    # rotation of the hand about the forearm axis by 80 deg: left = pronation sense,
    # right = supination sense (from the rest orientation).  No twist bones exist, so this is
    # the candy-wrapper stress test for plain LBS.
    for side, sg in (("l", 1.0), ("r", 1.0)):
        fa = C.bone_dir(arm, f"lowerarm_{side}")
        C.rotate_bone_world(arm, f"hand_{side}", fa, 80.0 * sg)


# Fist limit found by test: 88/100/62 pushes the fingertips through the back of the hand
# (hm08 palm is thin and LBS does not compress it); 80/90/45 keeps them inside.
FIST = dict(curl=(80, 90, 45), thumb=(45, 10, 35, 40))
HALF = dict(curl=(42, 48, 30), thumb=(14, 8, 12, 18))
SPREAD = dict(spread=14.0, curl=(-6, 0, 0), thumb=(-18, 0, -5, 0))


def p_upperarm_roll(arm):
    # elbows 90 deg forward, then the upper arm rolled 70 deg about its own axis (internal
    # rotation: forearm swings towards the belly) -- stress test for the shoulder / upper arm
    for side, sg in (("l", 1.0), ("r", -1.0)):
        u = C.bone_dir(arm, f"upperarm_{side}")
        C.aim_bone(arm, f"lowerarm_{side}", u)
        fwd = Vector((0, -1, 0))
        fwd_p = (fwd - u * fwd.dot(u)).normalized()
        C.rotate_bone_world(arm, f"lowerarm_{side}", u.cross(fwd_p), 90.0)
        C.rotate_bone_world(arm, f"upperarm_{side}", u, 70.0 * sg)


def p_fist(arm):
    for side in ("l", "r"):
        C.pose_hand(arm, side, **FIST)


def p_half(arm):
    for side in ("l", "r"):
        C.pose_hand(arm, side, **HALF)


def p_spread(arm):
    for side in ("l", "r"):
        C.pose_hand(arm, side, **SPREAD)


POSES = [
    ("arms_raised", p_arms_raised, "arms overhead: clavicle 22 deg + shoulder abduction 105 deg"),
    ("arms_forward", p_arms_forward, "shoulder flexion to horizontal, elbows straight"),
    ("arms_crossed", p_arms_crossed, "arms crossed in front of the chest (~110-125 deg elbows)"),
    ("elbows_120", p_elbows_120, "elbow flexion 120 deg, upper arms at rest"),
    ("squat_knees_120", p_squat, "hip flexion 100 deg, knee flexion 120 deg, ankle dorsiflexion 20 deg, feet planted"),
    ("spine_twist", p_spine_twist, "spine axial rotation 55 deg (15+20+20) + neck 5 deg, pelvis fixed"),
    ("wrist_flex", p_wrist_flex, "left wrist flexion 70 deg, right wrist extension 60 deg"),
    ("wrist_twist", p_wrist_twist, "hand rotated 80 deg about the forearm axis"),
    ("upperarm_roll", p_upperarm_roll, "elbows 90 deg, upper arm rolled 70 deg about its axis (internal rotation)"),
    ("fist", p_fist, "fist: fingers MCP/PIP/DIP 80/90/45 deg, thumb 01 folded 45 + out 10, 02/03 flex 35/40"),
    ("fingers_half", p_half, "transition: fingers 42/48/30 deg, thumb 14/8/12/18"),
    ("fingers_spread", p_spread, "fingers spread 14 deg (pinky 22), MCP extension 6 deg, thumb radial abduction 18 deg"),
]


DRIVEN = ("wrist_twist", "upperarm_roll")      # also measured / rendered with driven twist bones


def ring_ratio(co_rest, co_pose, head, tail, fracs, mask, radius=0.08):
    """Mean radial distance of limb cross-section rings (posed / rest) around a static axis."""
    h, t = np.asarray(head), np.asarray(tail)
    ax = t - h
    L = np.linalg.norm(ax)
    ax = ax / L
    out = {}
    for f in fracs:
        p = h + ax * L * f
        r = []
        for co in (co_rest, co_pose):
            rel = co - p
            al = rel @ ax
            rad = np.linalg.norm(rel - np.outer(al, ax), axis=1)
            m = mask & (np.abs(al) < 0.006) & (rad < radius)
            r.append(rad[m].mean())
        out[str(f)] = round(float(r[1] / r[0]), 3)
    return out


def pose_metrics(arm, body):
    C.reset_pose(arm)
    rest = C.mesh_arrays(body, evaluated=True)
    out = {}
    names = [b.name for b in arm.data.bones]
    D = C.read_weights(body, names)
    armmask = {sd: C.dominant_bone_mask(D, names, [f"{b}_{sd}" for b in (
        "upperarm", "upperarm_twist_01", "lowerarm", "lowerarm_twist_01", "hand", "clavicle")])
        for sd in ("l", "r")}
    bvh0 = C.mesh_bvh(body, rest)
    runs = [(n, f, d, False) for n, f, d in POSES] + [(n, f, d, True) for n, f, d in POSES if n in DRIVEN]
    for name, fn, desc, drive in runs:
        C.reset_pose(arm)
        fn(arm)
        tw = C.drive_twist_bones(arm, lower=TWIST_DRIVE["lower"], upper=TWIST_DRIVE["upper"]) if drive else None
        bpy.context.view_layer.update()
        co = C.mesh_arrays(body, evaluated=True)
        r = C.deformation_report(body, rest, co)
        n_int, _ = C.self_intersections(body, co)
        r["self_intersecting_face_pairs"] = n_int
        r["description"] = desc + (" -- twist bones driven" if drive else "")
        maxdl = 0.0
        for pb in arm.pose.bones:
            L = (C.bone_world(arm, pb.name, "tail") - C.bone_world(arm, pb.name, "head")).length
            maxdl = max(maxdl, abs(L - pb.bone.length) / max(pb.bone.length, 1e-9))
        r["max_bone_length_change_rel"] = round(maxdl, 8)
        r["min_z_m"] = round(float(co[:, 2].min()), 4)
        if drive:
            r["twist_bones_driven_deg"] = tw
        if name == "wrist_twist":
            for sd in ("l", "r"):
                b = arm.data.bones[f"lowerarm_{sd}"]
                r[f"forearm_ring_ratio_{sd}"] = ring_ratio(rest, co, b.head_local, b.tail_local,
                                                           (0.3, 0.5, 0.7, 0.85, 0.95, 1.0, 1.05), armmask[sd])
        if name == "upperarm_roll":
            for sd in ("l", "r"):
                b = arm.data.bones[f"upperarm_{sd}"]
                r[f"upperarm_ring_ratio_{sd}"] = ring_ratio(rest, co, b.head_local, b.tail_local,
                                                            (0.1, 0.2, 0.35, 0.5, 0.7), armmask[sd], 0.09)
        if name in ("elbows_120", "squat_knees_120", "upperarm_roll"):
            bvh = C.mesh_bvh(body, co)
            jc = {}
            for jn in (("lowerarm_l", "lowerarm_r") if name != "squat_knees_120" else ("calf_l", "calf_r", "thigh_l")):
                p0 = arm.data.bones[jn].head_local
                p1 = C.bone_world(arm, jn)
                d0 = bvh0.find_nearest(p0)[3]
                d1 = bvh.find_nearest(p1)[3]
                jc[jn] = {"rest_clearance_m": round(d0, 4), "posed_clearance_m": round(d1, 4),
                          "ratio": round(d1 / d0, 3)}
            r["joint_clearance"] = jc
        out[name + ("_driven" if drive else "")] = r
        log(f"pose {name}{' (driven)' if drive else ''}: tris<25%={r['tris_below_25pct_area']} int={r['self_intersecting_face_pairs']}")
    C.reset_pose(arm)
    n_int, _ = C.self_intersections(body, rest)
    out["_rest_self_intersecting_face_pairs"] = n_int
    return out


# =============================================================================
# renders
# =============================================================================

def render_setup(body):
    ivlib.clear_lights_cameras()
    sc = bpy.context.scene
    ivlib.setup_cycles(sc, samples=RENDER_SAMPLES, threads=4)
    sc.view_settings.view_transform = 'AgX'
    sc.view_settings.look = 'None'
    C.neutral_lighting((0, 0, 0.95), 1.8, key=0.50, world_strength=0.35)
    if "IVC_Ground" not in bpy.data.objects:
        C.ground_plane(60.0, (0.30, 0.30, 0.31))
    body.data.materials.clear()
    body.data.materials.append(C.clay_material("IV_CharClay", color=(0.55, 0.53, 0.50), rough=0.6))


def ruler(height=1.80, x=0.75, y=0.0, name="IVC_Ruler"):
    """1.80 m measuring stick with 10 cm bands (alternating) -- visual scale check."""
    objs = []
    ma = C.flat_material("IVC_RulerA", (0.85, 0.85, 0.85))
    mb = C.flat_material("IVC_RulerB", (0.08, 0.08, 0.08))
    n = int(round(height / 0.1))
    for i in range(n):
        ob = ivlib.box(f"{name}_{i:02d}", x - 0.015, x + 0.015, y - 0.015, y + 0.015, i * 0.1, (i + 1) * 0.1)
        ob.data.materials.append(ma if i % 2 == 0 else mb)
        objs.append(ob)
    return objs


def cam_persp(name, target, direction, dist, lens=50.0, up=(0, 0, 1)):
    d = Vector(direction).normalized()
    t = Vector(target)
    return ivlib.camera(name, t + d * dist, t, lens=lens, up=up)


def R(path, cam, res=(1280, 720), samples=None):
    return ivlib.render(path, cam, res=res, samples=samples or RENDER_SAMPLES)


def want(only, key):
    return only is None or any(key == o or key.startswith(o) for o in only)


def renders(arm, body, only=None):
    """only: None = everything, else a list of prefixes: rest, skeleton, pose:<name>, hands."""
    os.makedirs(PREV, exist_ok=True)
    render_setup(body)
    made = []
    C.reset_pose(arm)
    # ---- rest pose, orthographic front / side / back with a 1.80 m ruler (10 cm bands)
    rul_fb = ruler(x=0.95, y=0.0, name="IVC_RulerFB")
    rul_s = ruler(x=0.0, y=0.62, name="IVC_RulerS")
    for view, loc in ((("front", (0, -8, 0.95)), ("side", (8, 0, 0.95)), ("back", (0, 8, 0.95)))
                      if want(only, "rest") else ()):
        for o in rul_fb:
            o.hide_render = view == "side"
        for o in rul_s:
            o.hide_render = view != "side"
        cam = ivlib.camera(f"cam_{view}", loc, (0, 0, 0.95), ortho_scale=2.05, up=(0, 0, 1))
        cam.data.sensor_fit = 'VERTICAL'
        made.append(R(os.path.join(PREV, f"HumanBase_rest_{view}.png"), cam, res=(1440, 1080)))
    for o in rul_fb + rul_s:
        o.hide_render = True
    # ---- rest pose perspective 3/4
    if want(only, "rest"):
        cam = cam_persp("cam_q34", (0, 0, 0.93), (-0.55, -1, 0.12), 4.6, lens=50)
        made.append(R(os.path.join(PREV, "HumanBase_rest_persp.png"), cam, res=(1600, 900)))
    # ---- skeleton overlay (x-ray body + joints/bones)
    if want(only, "skeleton"):
        made += skeleton_overlay(arm, body)
    # ---- deformation poses
    runs = [(n, f, False) for n, f, d in POSES] + [(n, f, True) for n, f, d in POSES if n in DRIVEN]
    for name, fn, drive in runs:
        if name in ("fist", "fingers_half", "fingers_spread") or not want(only, "pose:" + name):
            continue
        C.reset_pose(arm)
        fn(arm)
        if drive:
            C.drive_twist_bones(arm, lower=TWIST_DRIVE["lower"], upper=TWIST_DRIVE["upper"])
        bpy.context.view_layer.update()
        tag = name + ("_driven" if drive else "")
        for shot in pose_shots(arm, name):
            sname, tgt, dirv, dist, lens = shot
            if drive and sname == "full":
                continue
            cam = cam_persp(f"cam_{tag}_{sname}", tgt, dirv, dist, lens=lens)
            made.append(R(os.path.join(PREV, f"HumanBase_pose_{tag}_{sname}.png"), cam))
    # ---- hands
    if want(only, "hands"):
        made += hand_renders(arm, body)
    if want(only, "pose:wrist_twist"):
        made += twist_compare()
    C.reset_pose(arm)
    return made


def twist_compare():
    """Undriven vs driven twist bones, same camera, side by side."""
    out = []
    for sd in ("l", "r"):
        a = os.path.join(PREV, f"HumanBase_pose_wrist_twist_wrist_{sd}.png")
        b = os.path.join(PREV, f"HumanBase_pose_wrist_twist_driven_wrist_{sd}.png")
        if os.path.exists(a) and os.path.exists(b):
            o = os.path.join(PREV, f"HumanBase_compare_wrist_twist_{sd}.png")
            ivlib.side_by_side([a, b], o, labels=[f"hand turned 80 deg, plain LBS (twist bones not driven) - {sd}",
                                                  f"same pose, lowerarm_twist_01_{sd} driven 0.5 x - {sd}"])
            out.append(o)
    return out


def pose_shots(arm, name):
    full_t = (0, 0, 0.95)
    if name == "squat_knees_120":
        full_t = (0, -0.1, 0.62)
    shots = [("full", full_t, (-0.6, -1, 0.15), 4.4, 50)]
    kl = C.bone_world(arm, "calf_l")
    el = C.bone_world(arm, "lowerarm_l")
    er = C.bone_world(arm, "lowerarm_r")
    sl = C.bone_world(arm, "upperarm_l")
    wl = C.bone_world(arm, "hand_l")
    wr = C.bone_world(arm, "hand_r")
    if name == "arms_raised":
        shots.append(("shoulder_back", (sl + C.bone_world(arm, "upperarm_r")) * 0.5 + Vector((0, 0, 0.05)), (0.35, 1, 0.25), 1.6, 50))
        shots.append(("shoulder_front", sl, (0.5, -1, 0.1), 1.1, 50))
    elif name == "arms_forward":
        shots.append(("shoulder_side", sl, (1, 0.2, 0.25), 1.2, 50))
        shots.append(("shoulder_top", (sl + C.bone_world(arm, "upperarm_r")) * 0.5, (0.25, 0.35, 1), 1.5, 50))
    elif name == "arms_crossed":
        shots.append(("front_close", (el + er) * 0.5, (-0.3, -1, 0.15), 1.3, 50))
    elif name == "elbows_120":
        shots.append(("elbow_inner", el, (0.9, -0.8, 0.3), 0.75, 50))
        shots.append(("elbow_outer", el, (0.8, 1.0, -0.1), 0.75, 50))
    elif name == "squat_knees_120":
        shots.append(("side", (0, 0, 0.55), (1, 0, 0.05), 3.2, 50))
        shots.append(("knee_close", kl, (0.9, -0.9, 0.35), 0.9, 50))
        shots.append(("back_hips", (0, 0.1, 0.55), (0.25, 1, 0.3), 1.8, 50))
    elif name == "spine_twist":
        shots.append(("top", (0, 0, 1.2), (0.1, -0.35, 1), 2.4, 50))
    elif name == "wrist_flex":
        shots.append(("wrist_l", wl, (1, -0.25, 0.1), 0.6, 50))
        shots.append(("wrist_r", wr, (-1, -0.25, 0.1), 0.6, 50))
    elif name == "wrist_twist":
        for sd, w, e, sx in (("l", wl, el, 1), ("r", wr, er, -1)):
            fa = (w - e).normalized()
            view = fa.cross(Vector((0, 0, 1))).normalized()
            if view.y > 0:
                view = -view                       # look from the front side
            view = (view + Vector((0.25 * sx, 0, 0.15))).normalized()
            shots.append((f"wrist_{sd}", w + fa * 0.02, view, 0.42, 50))
    elif name == "upperarm_roll":
        shots.append(("shoulder_l", sl * 0.7 + el * 0.3, (0.75, -1, 0.35), 0.8, 50))
        shots.append(("shoulder_back", sl * 0.7 + el * 0.3, (0.5, 1, 0.3), 0.8, 50))
    return shots


def skeleton_overlay(arm, body):
    made = []
    xr = bpy.data.materials.new("IVC_XRay")
    xr.use_nodes = True
    bs = xr.node_tree.nodes["Principled BSDF"]
    bs.inputs["Alpha"].default_value = 0.22
    bs.inputs["Base Color"].default_value = (0.8, 0.8, 0.8, 1)
    bpy.context.scene.cycles.transparent_max_bounces = 24
    old = list(body.data.materials)
    body.data.materials.clear()
    body.data.materials.append(xr)
    jm = C.flat_material("IVC_Joint", (0.95, 0.25, 0.08), emission=1.5)
    bm_ = C.flat_material("IVC_Bone", (0.15, 0.45, 0.95), emission=1.0)
    tmp = []
    for b in arm.data.bones:
        h = Vector(b.head_local)
        t = Vector(b.tail_local)
        r = 0.006 if not any(f in b.name for f in C.FINGERS) else 0.003
        bpy.ops.mesh.primitive_uv_sphere_add(radius=r, location=h, segments=12, ring_count=6)
        o = bpy.context.object
        o.data.materials.append(jm)
        tmp.append(o)
        dv = t - h
        bpy.ops.mesh.primitive_cylinder_add(radius=r * 0.45, depth=dv.length, location=(h + t) / 2, vertices=8)
        o = bpy.context.object
        o.rotation_euler = dv.to_track_quat('Z', 'Y').to_euler()
        o.data.materials.append(bm_)
        tmp.append(o)
    for view, loc in (("front", (0, -8, 0.95)), ("side", (8, 0, 0.95))):
        cam = ivlib.camera(f"cam_sk_{view}", loc, (0, 0, 0.95), ortho_scale=2.05)
        cam.data.sensor_fit = 'VERTICAL'
        made.append(R(os.path.join(PREV, f"HumanBase_skeleton_{view}.png"), cam, res=(1440, 1080)))
    # hand skeleton close-up (left, palm view)
    c, d, r, n = C.palm_frame(arm, "l")
    bpy.data.objects["IVC_Ground"].hide_render = True
    cam = ivlib.camera("cam_sk_hand", c + d * 0.03 + n * 0.36, c + d * 0.03, lens=50, up=tuple(-d))
    made.append(R(os.path.join(PREV, "HumanBase_skeleton_hand_l_palm.png"), cam, res=(1024, 1024)))
    bpy.data.objects["IVC_Ground"].hide_render = False
    for o in tmp:
        bpy.data.objects.remove(o, do_unlink=True)
    body.data.materials.clear()
    for m in old:
        body.data.materials.append(m)
    return made


def hand_cams(arm, side, tag):
    c, d, r, n = C.palm_frame(arm, side)
    tc = c + d * 0.04
    dist = 0.34
    return [(f"{tag}_palm", tc + n * dist, tc, -d), (f"{tag}_back", tc - n * dist, tc, -d),
            (f"{tag}_side", tc + r * dist + n * 0.05, tc, n)]


def arm_mask(body, arm):
    """Temporary Mask modifier: show only forearms and hands (clean hand close-ups)."""
    names = [b.name for b in arm.data.bones]
    D = C.read_weights(body, names)
    keep = [n for n in names if any(k in n for k in ("lowerarm", "hand", "thumb", "index", "middle", "ring", "pinky"))]
    m = C.dominant_bone_mask(D, names, keep)
    vg = body.vertex_groups.new(name="IVC_ArmMask")
    vg.add([int(i) for i in np.nonzero(m)[0]], 1.0, 'REPLACE')
    mod = body.modifiers.new("IVC_Mask", 'MASK')
    mod.vertex_group = "IVC_ArmMask"
    return mod, vg


def hand_renders(arm, body):
    made = []
    mod, vg = arm_mask(body, arm)
    bpy.data.objects["IVC_Ground"].hide_render = True
    for pname, fn in (("open", None), ("fist", p_fist), ("half", p_half), ("spread", p_spread)):
        C.reset_pose(arm)
        if fn:
            fn(arm)
        bpy.context.view_layer.update()
        for side in ("l", "r"):
            for vname, loc, tgt, up in hand_cams(arm, side, f"{side}"):
                cam = ivlib.camera(f"cam_h_{pname}_{vname}", loc, tgt, lens=50, up=tuple(up))
                made.append(R(os.path.join(PREV, f"HumanBase_hand_{pname}_{vname}.png"), cam,
                              res=(720, 720)))
    bpy.data.objects["IVC_Ground"].hide_render = False
    body.modifiers.remove(mod)
    body.vertex_groups.remove(vg)
    C.reset_pose(arm)
    return made


def sheets(paths):
    """Contact sheets for quick review."""
    hands = sorted(p for p in paths if os.path.basename(p).startswith("HumanBase_hand_"))
    poses = sorted(p for p in paths if os.path.basename(p).startswith("HumanBase_pose_"))
    out = []
    if hands:
        items = [(p, os.path.basename(p)[len("HumanBase_hand_"):-4]) for p in hands]
        out.append(ivlib.contact_sheet(items, os.path.join(PREV, "HumanBase_hands_contact_sheet.png"),
                                       thumb=320, cols=6, title="SK_Human_Base hands (clay, rest A-pose + finger test poses)"))
    if poses:
        items = [(p, os.path.basename(p)[len("HumanBase_pose_"):-4]) for p in poses]
        out.append(ivlib.contact_sheet(items, os.path.join(PREV, "HumanBase_poses_contact_sheet.png"),
                                       thumb=320, cols=6, title="SK_Human_Base deformation test poses (plain LBS, 4 influences)"))
    return out


# =============================================================================
# export
# =============================================================================

def export_all():
    res = {}
    res["fbx_export"] = ivlib.export_fbx(BLEND, [ARMATURE_NAME, MESH_NAME], FBX_PATH)
    res["glb_export"] = ivlib.export_glb(BLEND, [ARMATURE_NAME, MESH_NAME], GLB_PATH)
    res["fbx_reimport"] = C.reimport_skinned_check(FBX_PATH)
    res["glb_reimport"] = C.reimport_skinned_check(GLB_PATH)
    return res


def reimport_verdict(r, expected_bones, source_heads=None):
    ok = True
    notes = []
    if source_heads:
        dev = max((Vector(r["bone_heads_world_m"][n]) - Vector(h)).length
                  for n, h in source_heads.items() if n in r["bone_heads_world_m"])
        r["max_bone_head_deviation_m"] = round(dev, 5)
        if dev > 0.001:
            ok = False
            notes.append(f"bone heads deviate up to {dev * 1000:.2f} mm")
    dims = r["dimensions_m"]
    if abs(dims[2] - STATURE) > 0.002 and abs(dims[1] - STATURE) > 0.002:
        ok = False
        notes.append(f"height {dims}")
    if sorted(r.get("bones", [])) != sorted(expected_bones):
        ok = False
        notes.append("bone names differ: missing %s extra %s" % (
            sorted(set(expected_bones) - set(r.get("bones", []))),
            sorted(set(r.get("bones", [])) - set(expected_bones))))
    for mname, m in r["meshes"].items():
        if m.get("unweighted_vertices", 1) != 0 or m.get("max_influences", 99) > MAX_INFLUENCES:
            ok = False
            notes.append(f"{mname}: weights {m}")
        if not m.get("armature_modifier"):
            ok = False
            notes.append(f"{mname}: no armature modifier")
        if m.get("vertices") != BODY_VERTS:
            notes.append(f"{mname}: vertex count {m.get('vertices')} (split by UV seams/normals on import is expected for glTF)")
    return ("PASS" if ok else "FAIL"), notes


# =============================================================================

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stages", default="build,validate,render,export")
    ap.add_argument("--only", default=None, help="render subset: comma list of rest,skeleton,pose:<name>,hands")
    a = ap.parse_args([x for x in sys.argv[1:]])
    stages = a.stages.split(",")
    t0 = time.time()
    info = {}
    if "build" in stages:
        arm, body, info = build()
    else:
        arm, body = load_scene()
        if os.path.exists(REPORT):
            with open(REPORT) as f:
                old = json.load(f)
            info = {k: old[k] for k in ("design_inputs", "source_mesh", "targets", "scale",
                                        "root_override", "weights", "rest_pose", "rest_bbox_m",
                                        "build_seconds") if k in old}
    rep = None
    if "validate" in stages:
        rep = validate(arm, body, info)
        rep["deformation_tests"] = pose_metrics(arm, body)
    elif os.path.exists(REPORT):
        with open(REPORT) as f:
            rep = json.load(f)
    if "render" in stages:
        renders(arm, body, a.only.split(",") if a.only else None)
        import glob
        allp = sorted(glob.glob(os.path.join(PREV, "HumanBase_*.png")))
        sheets(allp)
        if rep is not None:
            rep["renders"] = [os.path.relpath(p, IV) for p in sorted(glob.glob(os.path.join(PREV, "HumanBase_*.png")))]
        # renders changed materials / added helpers: reload the clean saved file afterwards
        arm, body = load_scene()
    if "export" in stages:
        ex = export_all()
        names = [b.name for b in arm.data.bones]
        heads = {b.name: list(arm.matrix_world @ b.head_local) for b in arm.data.bones}
        for k in ("fbx_reimport", "glb_reimport"):
            ex[k + "_verdict"], ex[k + "_notes"] = reimport_verdict(ex[k], names, heads)
        if rep is not None:
            rep["export"] = ex
            rep.setdefault("checks", {})["fbx_reimport"] = ex["fbx_reimport_verdict"]
            rep["checks"]["glb_reimport"] = ex["glb_reimport_verdict"]
    if rep is not None:
        import glob
        # renders on disk (from this or an earlier run of the same deterministic build)
        rep["renders"] = [os.path.relpath(p, IV) for p in sorted(glob.glob(os.path.join(PREV, "HumanBase_*.png")))]
        rep["total_seconds_this_run"] = round(time.time() - t0, 1)
        os.makedirs(PREV, exist_ok=True)
        with open(REPORT, "w") as f:
            json.dump(rep, f, indent=2)
        log("checks:", json.dumps(rep.get("checks", {}), indent=1))
        log("report ->", REPORT)


if __name__ == "__main__":
    main()
