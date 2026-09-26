# SK_Human_Base: rigged human base, reference and specification

Project: IRON VALLEY (original realistic military FPS prototype).
Asset: **SK_Human_Base**, the one rigged human that every Iron Valley character, the
first-person arms and the hands derive from. It is an adult male soldier: 28 years old,
athletic, **1.80 m**.

Status: built and validated in Blender (bpy 4.5.14 LTS, headless, Cycles CPU). **Not imported
into Unreal** (Unreal is not available in this environment), so nothing in this document is an
in-engine result. Higgsfield was **not used** (HF-01 BLOCKED).

| Item | Path |
| --- | --- |
| Build script (editable source) | `Art/Source/Blender/characters/human_base.py` |
| Shared character helpers | `Art/Source/Blender/lib/ivchar.py` (plus `ivlib.py` for rendering and export) |
| Generated scene | `Art/Source/Blender/characters/human_base.blend` |
| Third-party data (CC0) | `Art/ThirdParty/mpfb2/` (see `SOURCE.md` there) |
| FBX (Unreal) | `Art/Export/FBX/SK_Human_Base.fbx` |
| GLB (web / three.js) | `Art/Export/GLB/Human_Base.glb` |
| Validation report | `Art/Previews/HumanBase/HumanBase_validation.json` (regenerated on every run) |
| Renders | `Art/Previews/HumanBase/*.png` |

Rebuild everything: `python3 Art/Source/Blender/characters/human_base.py` (about 20 min, almost
all of it rendering). Without renders: `--stages build,validate,export` (about 10–15 s). A render
subset: `--stages render --only hands,pose:wrist_twist` (prefixes: `rest`, `skeleton`,
`pose:<name>`, `hands`).

**Determinism.** The build uses no randomness. Two consecutive runs produced identical
validation reports (every section except timings) and a byte-identical GLB. The FBX differs by a
few bytes between runs; its content re-imports identically, so the difference is most likely
creation-time metadata.

## Validation summary (from `HumanBase_validation.json → checks`)

| Check | Result | Evidence |
| --- | --- | --- |
| Closed 2-manifold, UVs 0..1, consistent normals, outward volume | **PASS** | report `mesh` |
| Stature 1.800 m, feet on Z = 0 | **PASS** | report `dimensions_check`; ruler renders `HumanBase_rest_*.png` |
| Facing −Y | **PASS** | report `facing` |
| UE-mannequin bone names and hierarchy, single root `root` (+ 4 UE4 twist bones) | **PASS** | report `skeleton` |
| Every vertex weighted, ≤ 4 influences, sums 1, exact L/R symmetry | **PASS** | report `skin`, `weights` |
| Joints inside the mesh, tips on the surface (bone lengths match the mesh) | **PASS** | report `joints_vs_mesh`; `HumanBase_skeleton_*.png` |
| Proportions within plausibility ranges | **PASS** | report `measurements` (section 3) |
| FBX re-import (Blender) | **PASS** | report `export.fbx_reimport` |
| GLB re-import (Blender) | **PASS** | report `export.glb_reimport` |
| Deformation poses reviewed (section 10) | done; P2 items in section 13 | `HumanBase_pose_*.png`, `HumanBase_poses_contact_sheet.png` |
| HAND-01 geometry evidence (palm/back/side; open, transition, fist; both hands) | shown, see section 10 | `HumanBase_hand_*.png`, `HumanBase_hands_contact_sheet.png` |
| Unreal import / in-game look / retargeting | **BLOCKED** | no Unreal in this environment |

---

## 1. Source and licence

- **Mesh, targets, rig and weights:** MakeHuman `hm08` base mesh and the MPFB2 "game_engine" rig
  with its weights. All are **CC0 1.0**. They were vendored byte-for-byte from the PyPI wheel
  `anny 0.6.0` (NAVER; the package code is Apache-2.0, and none of it is copied). Details and
  hashes: `Art/ThirdParty/mpfb2/SOURCE.md`.
- **Everything else** (proportion choices, symmetrised weights, twist bones, rest pose,
  validation) is project work, done by script.
- **Formats as interpreted here:**
  - Targets are `vertex dx dy dz` in decimetres, Y up. The macro-target weights follow MakeHuman
    1.x semantics.
  - Joints in `rig.game_engine.json`:
    - `CUBE` = mean of the vertices of the named joint cube;
    - `MEAN` = mean of the listed vertices;
    - roll = the Blender edit-bone roll.
  - Weights are `[vertex, weight]` lists per bone.
- **Check of the interpretation:** applying MakeHuman's default macros (all 0.5) reproduces
  every `default_position` in `rig.game_engine.json` to within 0.3 µm. The only exception is
  the tail of the unweighted `Root` bone, at 1.8 mm.

## 2. Body design inputs

| Input | Value | Why |
| --- | --- | --- |
| Gender | 1.0 (male) | – |
| Age | 28 years → MakeHuman age value 0.5231 (young 0.954, old 0.046) | Brief |
| Muscle | 0.70 (average 0.6, max 0.4) | "athletic, muscle high-average" |
| Weight | 0.50 (average) | Brief |
| Height macro | 0.50 (no height target); stature set by uniform scaling | Keeps MakeHuman's average-male proportions; the height targets distort limb ratios at the extremes |
| Proportions | 0.50 ("regular": neither `idealproportions` nor `uncommonproportions`) | "realistic proportions" (the ideal target is a heroic stylisation) |
| Race mix | african / asian / caucasian 1/3 each (MakeHuman default) | Neutral base; faces are covered by balaclava or shemagh and eye protection |
| Measure targets | `measure-upperarm-length-incr` 0.50, `measure-lowerarm-length-decr` 0.50 | See the next paragraph |
| Stature | exactly 1.800 m, sole to vertex (uniform scale 1.041092 on the 1.72895 m model) | Brief |

**Why the arm measure targets.** hm08's joint layout gives, at 1.80 m, a 26.1 cm upper arm and
a 27.7 cm forearm, measured between joint centres. That is a ratio of 0.95; adults are about
1.2–1.3. With the arm hanging, the elbow would sit about 4.5 cm too high. MakeHuman's own measure
targets move the mesh and the elbow joint cube together, so the elbow bends where the mesh
bends. Result: upper arm 29.8 cm, forearm 25.3 cm (ratio 1.18), with the elbow at 1.138 m
when the arm hangs. Shoulder-to-wrist length grows by 1.3 cm, and the estimated arm span is
1.91 m (1.06 × stature).

## 3. Proportions (measured on the built rest mesh, from the validation report)

The plausibility ranges are **approximate values for an adult male of 1.80 m from general
anthropometric literature**. They are not measurements of a real person and are used only to
catch gross errors. GEO-01's ±5 % target applies where a real reference exists; this base
has no single reference person.

| Measure | Definition | Value | Plausible range |
| --- | --- | --- | --- |
| Stature | sole → vertex | **180.0 cm** | exact |
| Head | menton (chin, front midline, lowest point) → vertex | **22.8 cm** (7.9 heads tall) | 21.5–24.5 |
| Shoulder width, joints | `upperarm_l` head ↔ `upperarm_r` head | **38.7 cm** | – |
| Shoulder width, deltoids | 2 × max \|x\| of mesh within 10 cm of the shoulder joint (A-pose) | **56.6 cm** | inflated by the A-pose; bideltoid breadth in a neutral stance is smaller |
| Arm (upper arm) | shoulder joint → elbow joint | **29.8 cm** | 28.5–33.5 |
| Forearm | elbow joint → wrist joint | **25.3 cm** | 24.5–27.5 |
| Hand | wrist joint → tip of middle finger (mesh) | **21.0 cm** | 18.5–21.5 |
| Hand breadth | across the palm (mesh, hand-dominated vertices) | 9.3 cm | – |
| Thigh | hip joint → knee joint | **43.3 cm** | 41.5–46.5 |
| Shin | knee joint → ankle joint | **45.5 cm** | 41.5–46.5 |
| Foot | heel → toe tip along the foot axis (mesh) | **26.9 cm** | 25.5–29.0 |
| Shoulder joint height | – | 143.5 cm | 140–148 |
| Hip joint height | – | 95.6 cm | 90–98 |
| Knee joint height | – | 52.7 cm | 48–54 |
| Ankle joint height | – | 7.4 cm | – |
| Hip joint separation | – | 22.7 cm | – |
| Arm span (estimate) | 2 × (shoulder joint x + arm + forearm + hand) | 190.9 cm | 178–192 |
| Elbow / wrist / fingertip height, arm hanging | shoulder joint height minus the segments | 113.8 / 88.4 / 67.4 cm | – |

Every value is inside its plausibility range (check `proportions_within_plausible_ranges` =
PASS). The hand is at the upper end of the range, as the wrist joint sits slightly proximal to
the wrist crease. Renders with a 1.80 m ruler in 10 cm bands: `HumanBase_rest_front.png`,
`_side.png`, `_back.png`.

## 4. Mesh

| Item | Value |
| --- | --- |
| Topology | hm08 `body` group: 13 380 vertices, 13 378 quads (26 756 triangles on export). The source quads are kept in the .blend; exporters triangulate. |
| Closed surface | 0 boundary edges, 0 non-manifold edges, 0 loose / zero-area / duplicate faces, consistent winding, positive signed volume (outward normals). Eye sockets and mouth are closed pockets inside the body surface. |
| UVs | original hm08 body UVs (`UVMap`), one set, all inside 0..1 (0.009–0.994) |
| Normals | smooth shading, no custom normals; 0 faces opposing their vertex normals |
| Material | one slot, `M_Human_Base` (neutral clay, no textures yet). Skin textures are **not part of this asset**. |
| Removed | every helper and joint cube: eyeballs, eyelashes, upper/lower teeth, tongue, tights, skirt, hair and genital helpers, joint cubes (vertex ranges 13380–19157) |
| Eyes, brows, lashes, teeth, tongue | **Removed.** Soldiers wear a helmet, balaclava or shemagh, and eye protection, and a clean closed body is the goal. hm08 has no eyebrow geometry (MakeHuman brows are proxies). The eyelid openings show the dark, closed socket pocket. A character with an uncovered face can add eyeballs back from `base.obj` groups `helper-l-eye` / `helper-r-eye`, rigidly bound to `head`. |
| Known native contact | 8 face pairs at the two mouth corners touch or overlap slightly in the rest pose (hm08 closed lips). Hidden under face covering; P2. |

## 5. Coordinate conventions

- Metres, Z up, 1 BU = 1 m. The character **faces −Y** (the Blender front view looks along +Y).
  Its left side (`_l` bones) is at +X. Feet are on **Z = 0**, and the origin is on MakeHuman's
  ground joint between the feet (x = 0, y within 0.5 mm of the ground cube centre).
- **FBX → Unreal** (settings in `ivlib.FBX_UNREAL_OPTS`, centimetre bake, no node scale):
  Blender (x, y, z) arrives as UE (x, −y, z), so the character faces **UE +Y**. That is the
  UE mannequin convention (Character blueprints rotate the mesh −90° in yaw). **Unverified in
  Unreal.**
- **GLB**: metres, Y up (converted by the exporter). The character faces **+Z** (the glTF front),
  and its left is +X.
- Bone axes follow Blender: local **Y runs along the bone**. The MPFB rolls are anatomical, which
  was checked (section 7). In the FBX the bones keep the Blender orientation (primary Y), unlike
  the UE mannequin (X along the bone). Unreal's IK Retargeter works per chain and does not need
  matching bone axes, but hand-made additive animations would.

## 6. Rest pose: A-pose

| Joint | Rest | Source |
| --- | --- | --- |
| Upper arms | 48.3° below horizontal, slightly forward | as modelled by hm08 |
| Elbows | **15° flexion** | straightened from the modelled 45.9° (rotation about the elbow hinge, then applied as rest) |
| Forearms / hands | neutral, palms facing the thighs and slightly down; fingers relaxed and slightly curved | as modelled |
| Spine, neck, head | upright, looking forward | as modelled |
| Legs | feet about 41 cm apart at the ankles, soles flat on Z = 0 | as modelled |

**Why an A-pose (not a T-pose).**

1. The weights were authored for hm08's own pose. Raising the arms 48° into a T-pose would bake
   linear-blend-skinning shoulder deformation into the rest mesh that all clothing is modelled
   on. Unbending the elbows is the only pose change, and unbending is benign under LBS.
2. The Unreal mannequins use an A-pose reference pose. The IK Retargeter's retarget pose can
   still be edited on either side.
3. glTF and three.js do not care about the rest pose.
4. CMU mocap BVH files use a T-pose rest. Retargeting them (in Blender) compensates for the
   rest difference per bone, so the A-pose costs nothing there.

## 7. Skeleton: 57 bones, Unreal-mannequin names

- **53 bones from MPFB2 `rig.game_engine.json`.** Joint positions are computed exactly as MPFB
  and anny do: the mean of the joint-cube vertices after the targets are applied. The roll comes
  from the file, and the parents are as listed there.
- **Changed:** `Root` → **`root`**, moved to the origin with identity orientation (it points
  +Y, roll 0). MPFB derives Root from the ground cube and tights-helper vertices, which gives
  head (0, 2.8, 0.05) cm with roll −90°. Root carries **zero** skin weight, so no deformation
  changes.
- **Added:** four UE4-mannequin twist bones: `upperarm_twist_01_l/r` (child of `upperarm`,
  10–60 % along it) and `lowerarm_twist_01_l/r` (child of `lowerarm`, 50–100 %). Each has its
  parent's roll, so its local Y is the segment axis (section 9).
- Not present, compared with the UE mannequins:
  - IK bones (`ik_foot_*`, `ik_hand_*`);
  - `thigh_twist` / `calf_twist`;
  - UE5's `spine_04/05` and `neck_02`;
  - metacarpal bones.

  The core chain names match UE4 and UE5 exactly: root, pelvis, spine_01–03, neck_01, head,
  clavicle, upperarm, lowerarm, hand, the finger chains, thigh, calf, foot, ball.

Hierarchy (validation `skeleton_ue_mannequin_names_hierarchy` = PASS: no missing bones, no
wrong parents, single root `root`):

```
root
└─ pelvis
   ├─ spine_01 ─ spine_02 ─ spine_03
   │                         ├─ neck_01 ─ head
   │                         ├─ clavicle_l ─ upperarm_l ─┬─ upperarm_twist_01_l
   │                         │                           └─ lowerarm_l ─┬─ lowerarm_twist_01_l
   │                         │                                          └─ hand_l ─ thumb/index/middle/ring/pinky _01─_02─_03 _l
   │                         └─ clavicle_r ─ ... (mirror)
   ├─ thigh_l ─ calf_l ─ foot_l ─ ball_l
   └─ thigh_r ─ calf_r ─ foot_r ─ ball_r
```

Rest joint positions (cm; the right side mirrors the left with x → −x; the validation report
lists all 57 bones with head, tail, length and roll):

| Bone | Head (x, y, z) | Length | Bone | Head (x, y, z) | Length |
| --- | --- | --- | --- | --- | --- |
| root | 0, 0, 0 | 20.0 | clavicle_l | 2.4, −2.3, 146.6 | 17.3 |
| pelvis | 0, −0.3, 96.2 | 9.7 | upperarm_l | 19.4, −1.8, 143.5 | 29.8 |
| spine_01 | 0, 3.0, 105.3 | 7.3 | lowerarm_l | 39.2, −1.6, 121.3 | 25.3 |
| spine_02 | 0, 2.1, 112.5 | 6.3 | hand_l | 55.8, −8.0, 103.3 | 3.7 |
| spine_03 | 0, 3.1, 118.7 | 14.3 | thumb_01_l | 57.5, −12.0, 100.7 | 3.5 |
| neck_01 | 0, −1.1, 154.4 | 10.7 | index_01_l | 61.9, −14.7, 95.3 | 2.9 |
| head | 0, −4.9, 164.4 | 16.2 | middle_01_l | 62.8, −11.9, 94.9 | 3.8 |
| thigh_l | 11.3, 0.8, 95.6 | 43.3 | ring_01_l | 62.9, −9.6, 94.8 | 3.4 |
| calf_l | 15.7, −2.8, 52.7 | 45.5 | pinky_01_l | 62.2, −7.3, 94.7 | 2.4 |
| foot_l | 20.5, −1.5, 7.4 | 14.6 | ball_l | 20.9, −14.5, 0.9 | 7.4 |

**Bones vs mesh** (check `joints_inside_mesh_tips_on_surface` = PASS):
- Every bone head lies inside the closed body (ray-parity vote).
- Every MPFB leaf tail (fingertips, toe tip, top of head) is MPFB's tip marker and lies within
  1 cm of the surface. The largest is the head tail, 0.7 cm above the scalp.
- Twist-bone tails lie inside the arm.
- The largest L/R joint asymmetry is 0.0 mm.

**Anatomical bone axes (measured).** For every finger and thumb bone, local **+X is the
flexion axis**: the dot product with the anatomical axis is 0.96–1.00, and positive rotation
curls towards the palm on **both** hands, because Blender mirrors the rolls. Local Z of the
finger `_01` bones is the abduction axis. +Z moves the index towards the thumb on the left
hand; the sign is mirrored on the right. The thumb:
- `thumb_01` +X folds it across the palm;
- `thumb_01` +Z (left, mirrored on the right) swings it out in front of the palm;
- `thumb_02/03` +X curl it.

Verified with renders during development; `ivchar.pose_hand()` uses these axes.

## 8. Skinning

| Step | Result |
| --- | --- |
| Source | `weights.game_engine.json`, at most 6 influences per vertex on the body, rows summing to 1 ± 1e-4 |
| Vertex mapping | targets move vertices but keep their indices; body vertices 0..13379 map 1:1 (helpers dropped) |
| Symmetrisation | the source L/R mismatch was up to **0.259** (645 vertices over 0.01, mostly calves, feet and pelvis). Each vertex is averaged with its `hm08.mirror` partner, bones mirrored `_l`↔`_r`. After: **0.000**. |
| Twist split | forearm: a smoothstep ramp moves 0 → 100 % of `lowerarm` weight to `lowerarm_twist_01` between 30 % and 70 % of the forearm. Upper arm: 100 → 0 % of `upperarm` weight to `upperarm_twist_01` between 20 % and 55 % (shoulder side). |
| Influence limit | **4 per vertex** (real time), mirror-exact: left and midline vertices are limited, then right vertices copy their mirror partner. Before the limit, after symmetrisation and the twist split, at most 7 influences, with 630 vertices over 4. The mean L1 change is 0.0004, the maximum 0.11. |
| Result | 13 380 vertices, **0 unweighted**, max 4 influences (1: 6 333, 2: 4 314, 3: 1 403, 4: 1 330), sums **1.000000**, every vertex group is a bone, and `root` is the only deform bone without weight (check `skin_all_weighted_max4_sum1` = PASS) |

## 9. Twist bones: runtime rule (must be implemented in the engine)

| Bone | Local rotation, about its own Y (= segment axis) |
| --- | --- |
| `lowerarm_twist_01_s` | **+0.5 ×** the twist of `hand_s` relative to `lowerarm_s` about lowerarm Y (swing-twist decomposition) |
| `upperarm_twist_01_s` | **−0.5 ×** the twist of `upperarm_s`'s own local rotation about its Y (it is a child of upperarm, so it keeps half the roll) |

The reference implementation is `ivchar.drive_twist_bones()`. In Unreal: a post-process
AnimBP / Control Rig twist-corrective node. In three.js: a few lines per frame after the
animation mixer runs. An **undriven** twist bone behaves exactly like its parent, so the result
without the rule is the plain-LBS result. Animation retargeting or baking can bake the rule into
the clips instead.

Measured effect (validation `deformation_tests`, radius ratio posed/rest; 1.0 = no loss):

| Test | Plain LBS (twist bones not driven) | Twist bones driven |
| --- | --- | --- |
| Hand turned 80° about the forearm: wrist ring (100 %) | **0.793** (candy-wrapper) | **0.946** |
| same, forearm 95 % / 85 % / 50 % | 0.866 / 0.931 / 1.000 | 0.964 / 0.981 / 0.940 |
| Upper arm rolled 70° (elbow 90°): 10 % / 20 % ring | **0.881** / 0.917 | **0.969** / 0.978 |

## 10. Deformation tests

Plain LBS, 4 influences, rest A-pose, all poses scripted in `human_base.py` (`POSES`). Metrics
per pose are in the report (`deformation_tests`): triangle area ratios, collapsed triangles,
edge stretch, self-intersecting face pairs, bone length change (always < 3e-6, so no pose scales
a bone), joint clearance and limb ring ratios.

| Pose | Setup | Triangles under 25 % area | Min area ratio | Edge length min / max | Self-intersecting pairs* | Visual review (renders `HumanBase_pose_<pose>_*.png`) |
| --- | --- | --- | --- | --- | --- | --- |
| rest | – | – | – | – | 8 | only the native lip contact (section 4) |
| arms_raised | clavicle 22°, shoulder abduction 105° | 16 | 0.12 | 0.27 / 5.74 | 8 | Shoulders and armpits smooth, no collapse. The skin over the upper back and armpit stretches, with tiny edges up to 5.7×; no folds. |
| arms_forward | shoulder flexion to horizontal, elbows straight | 28 | 0.09 | 0.13 / 2.73 | 8 | Shoulder cap smooth from the side and from above |
| arms_crossed | forearms crossed in front of the chest | 13 | 0.08 | 0.15 / 1.70 | 153 | No elbow collapse. The pairs are hands and forearms touching the chest and arms (contact). |
| elbows_120 | elbow flexion 120° | 22 | 0.02 | 0.28 / 1.84 | 64 | The inner crease compresses: joint-to-surface clearance goes from 2.45 to 1.68 cm (0.68). The outer elbow tip turns slightly pointed and faceted, a classic LBS artefact, **P2**. No inversion or candy-wrapper. |
| squat_knees_120 | hip 100°, knee 120°, ankle 20°, feet planted | 35 | 0.06 | 0.23 / 8.18 | 192 | Knees bend the right way with no collapse. Back-of-knee clearance goes from 4.2 to 2.4 cm (0.57); calf and thigh touch (contact pairs). The gluteal skin stretches, with a **small pinch at the bottom of the gluteal cleft** (4 mm edges stretched up to 8×). **P2**, hidden under trousers. |
| spine_twist | 55° axial (15/20/20) + neck 5° | 0 | 0.43 | 0.70 / 1.54 | 8 | Smooth torso twist |
| wrist_flex | left flexion 70°, right extension 60° | 4 | 0.11 | 0.22 / 2.14 | 14 | No collapse on the palm or the back of the wrist |
| wrist_twist | hand turned 80° about the forearm | 0 | 0.30 | 0.36 / 2.11 | 8 | **Candy-wrapper** with plain LBS: the wrist ring shrinks to 0.79 and a notch is visible. |
| wrist_twist_driven | same, twist bones driven | 0 | 0.61 | 0.68 / 1.48 | 8 | Smooth wrist, ring 0.95 (`HumanBase_compare_wrist_twist_l/r.png`) |
| upperarm_roll | elbow 90°, humerus rolled 70° | 32 | 0.01 | 0.07 / 2.13 | 255 | Shoulder ring 0.88; the pairs are forearm and hand touching the belly (contact) |
| upperarm_roll_driven | same, twist bones driven | 28 | 0.01 | 0.07 / 1.66 | 255 | Shoulder ring 0.97, smooth shoulder cap |
| fist | 80/90/45, thumb 45/10/35/40 | 150 | 0.03 | 0.14 / 3.51 | 752 | Reads as a proper fist, with the thumb across the middle phalanges. **No fingertip comes through the back of the hand.** The pairs are finger-to-finger and fingertip-to-palm contact inside the fist. The dorsal skin over the thumb knuckles stretches (1.7 mm edges up to 3.5×) and the palmar creases compress, as knuckles do. |
| fingers_half | 42/48/30 (transition) | 60 | 0.01 | 0.04 / 1.70 | 50 | Natural half-curl. The strongest compression is in the palmar creases. |
| fingers_spread | 14° spread, thumb 18° radial | 0 | 0.43 | 0.73 / 1.97 | 8 | Clean |

\* Includes the 8 native lip pairs present in the rest pose.

**Hands (HAND-01 evidence, `HumanBase_hand_<pose>_<l|r>_<palm|back|side>.png`, sheet
`HumanBase_hands_contact_sheet.png`).** The open, half-curled (transition), fist and spread poses
are shown for both hands from the palm, back and side. Every view has five fingers, the thumb
opposing the fingers, joints bending the right way, and stable segment lengths (bone length
change < 3e-6 in every pose). No fingers are fused or crossed. The close-ups mask everything
except the forearms and hands to keep the background clean; the mask is removed afterwards and
the saved file is untouched. The skeleton inside the hand: `HumanBase_skeleton_hand_l_palm.png`.

## 11. Export and re-import

| File | Settings | Re-import (Blender stock importers, clean process) |
| --- | --- | --- |
| `Art/Export/FBX/SK_Human_Base.fbx` | `ivlib.FBX_UNREAL_OPTS`: centimetre bake (UnitScaleFactor 1, no node scale), `-Z` forward / `Y` up, no leaf bones, primary/secondary bone axis Y/X, smoothing groups, tangents, triangulated | **PASS**. 2.39 MB. 57 bones with the same names and parents, bone heads within **0.07 mm** of the source. Height **1.800 m** (bbox 131.5 × 31.7 × 180.0 cm). 13 380 vertices / 26 756 triangles, `UVMap`, armature modifier. Weights: 0 unweighted, max 4 influences, sums 1.000. 56 vertex groups: `root` has no weights, so FBX writes no cluster for it, but the bone exists. The importer converts cm to m with an armature object scale of 0.01; the file itself has no node scale. |
| `Art/Export/GLB/Human_Base.glb` | `ivlib.GLB_OPTS`: metres, Y up, skin, all bones, tangents, rest-position armature | **PASS**. 1.17 MB. 57 bones, heads within **0.07 mm**, height **1.800 m**. 14 517 vertices after the usual glTF split at UV seams (13 380 in the source), 26 756 triangles, 57 joints. Weights: 0 unweighted, max 4 influences, sums 1.000. |

- **Armature object name `Armature`.** When Blender writes the armature object as an FBX null
  above `root`, Unreal may add it as an extra bone above `root`. Unreal is widely reported to
  skip a top node named `Armature`, but that is **not verified here**. If an extra bone
  appears, it carries no scale (because of the centimetre bake) and is harmless for retargeting
  (retarget root = pelvis).
- **Recommended Unreal import (unverified):** Skeletal Mesh; Import Normals (or Normals and
  Tangents); Convert Scene on; Force Front X Axis off; Convert Scene Unit off; uniform scale
  1.0; Use T0 As Ref Pose off; no animation.
- Unreal import, in-engine deformation and retargeting to the UE mannequin: **BLOCKED** (no
  Unreal).

## 12. How to derive characters

1. **Body variants** (other builds, heights, ages):
   - Change `MACRO` / `LOCAL_TARGETS` in a copy of `human_base.py`. Vendor the extra target
     files: `ivchar.macro_target_weights(**params)` lists exactly which ones.
   - Joints are recomputed from the moved joint cubes, so the skeleton stays consistent with the
     mesh. Bone names, the hierarchy, the rest-pose rule and the weights recipe do not change,
     so every animation keeps working.
   - Re-run the validation; the plausibility ranges are for a 1.80 m male.
2. **Clothing and gear:**
   - Model on the rest mesh from `human_base.blend` (A-pose).
   - For soft garments (uniform, gloves, balaclava), transfer weights from `SK_Human_Base` with
     the Data Transfer modifier (nearest face interpolated), then limit to 4 influences and
     normalise.
   - Hard gear must **not** deform like skin: the helmet is rigid (100 %) to `head`; the plate
     carrier and vest are mostly rigid to `spine_03`, with `spine_02` near the bottom edge only;
     pouches are rigid to their carrier bone; knee pads to `calf`; the holster to `thigh`.
   - Hidden body parts under closed garments can be deleted per character to save triangles
     and avoid poke-through.
3. **First-person arms:**
   - Keep the **full 57-bone skeleton**, so FP and third-person animations share one skeleton.
   - Keep the arm mesh: vertices whose dominant weight is clavicle, upperarm (+twist),
     lowerarm (+twist), hand or the fingers, cut at the shoulder or upper chest.
   - Add sleeves and gloves. Attach the camera to `head`. In rest, the eyeball centres (MakeHuman
    eye joints) are at (±3.05, −13.1, 168.7) cm; the camera goes between them at
    (0, −13.1, 168.7) cm.
   - Drive the twist bones (section 9). Without them, rifle-hold forearm pronation and
     supination will candy-wrapper the wrist.
4. **Hand poses and grips** (`ivchar.pose_hand`, local +X = flexion):
   - Tested fist: MCP/PIP/DIP **80/90/45°**, thumb `01` +45° X / +10° Z, `02/03` +35/+40°.
   - **Do not exceed about 80/90/45**: at 88/100/62 the fingertips pass through the thin hm08
     palm and appear on the back of the hand (seen in development renders).
   - Grips on the IV-7 should be posed to contact, not by fixed angles; for close-up quality,
     check intersections with the weapon mesh.
5. **Animation:**
   - Retarget onto this skeleton (CMU BVH are T-pose, so compensate for the rest difference).
     Keep locomotion in-place (D7). Bone lengths are constant.

## 13. Known issues and limitations

| # | Severity | Issue | Status / next step |
| --- | --- | --- | --- |
| 1 | P0 (external) | Unreal import, axis mapping, the possible extra `Armature` root bone, in-engine skinning and IK Retargeter setup against the UE mannequin were not tested. | **BLOCKED** (no Unreal) |
| 2 | P1 if ignored | The twist bones only help when something drives them (section 9). Without a driver, hand twist past ~60° candy-wrappers the wrist (ring 0.79 at 80°). | Implement the rule in the three.js runtime and the UE AnimBP, or bake it during retargeting |
| 3 | P2 | Elbow at 120°: pointed outer tip and 32 % inner clearance loss (plain LBS, 4 influences). | Possible later fix: corrective shape or helper bone. Sleeves hide most of it. |
| 4 | P2 | Deep squat: gluteal stretch with a small pinch at the bottom of the cleft; back-of-knee compression. | Hidden by trousers. Revisit if a crouch animation shows it. |
| 5 | P2 | Tightest clean fist is about 80/90/45°; hm08's thin palm lets tighter curls pass through the back of the hand. Fingers touch and intersect inside the fist. | Pose grips to contact; do not exceed these angles |
| 6 | P2 | Eyeballs removed: the eyelid openings show the dark socket pocket (`HumanBase_rest_front.png`). | Eye protection or a balaclava covers it; re-add `helper-*-eye` rigid to `head` for a bare-faced character |
| 7 | P2 | 8 face pairs at the mouth corners intersect in the rest pose (native hm08 lip contact). | Hidden under face covering |
| 8 | info | The proportion plausibility ranges are approximate literature values, not a measured reference person. The deltoid breadth is inflated by the A-pose. | – |
| 9 | info | No skin textures; one clay material slot. No LODs yet (26.8k triangles for the full body). | Later asset tasks |
| 10 | info | No UE IK bones (`ik_foot_*`, `ik_hand_*`), `thigh_twist`/`calf_twist`, or UE5 `spine_04/05`/`neck_02`. Bone axes are Blender-style (Y along the bone), so animation assets cannot be shared directly with a UE mannequin skeleton; they need retargeting. | Add IK bones by script if a UE workflow needs them |
| 11 | info | MPFB spine layout: `spine_03` ends about 21 cm below `neck_01`, so the upper chest follows `spine_03` rigidly. | Acceptable for a soldier under a plate carrier |
| 12 | info | Only the macro targets for this male build are vendored. | Add more targets for variants (section 12) |
| 13 | info | Higgsfield was not used. | HF-01 **BLOCKED** |
