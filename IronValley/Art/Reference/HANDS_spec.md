# Hands, tactical gloves and hand poses: reference and specification

Project: IRON VALLEY (original realistic military FPS prototype).
Assets: the **hands of `SK_Human_Base`** (anatomy pass), the **tactical gloves** `SK_Glove_L` /
`SK_Glove_R` (coyote and black texture variants), the **hand pose library** (Blender actions and
exported clips) fitted to the real IV-7, and the HAND-01 / HAND-02 evidence.

Status: built and validated in Blender only (bpy 4.5.14 LTS, headless, Cycles CPU). **Nothing
here was imported into or tested in Unreal** (Unreal is not available in this environment), and
the web game does not use the hands yet. Higgsfield was not used (HF-01 BLOCKED).

| Item | Path |
| --- | --- |
| Base rig (hand anatomy pass lives here) | `Art/Source/Blender/characters/human_base.py`, `Art/Source/Blender/lib/ivchar.py` §8–10 |
| Gloves, poses, fitting, evidence, export | `Art/Source/Blender/characters/hands_gloves.py`, `Art/Source/Blender/lib/ivhands.py` |
| Generated scene (gloves, gloved body, 13 pose actions) | `Art/Source/Blender/characters/hands_gloves.blend` |
| Pose library data (anatomical angles, hand-to-socket transforms, fit reports) | `Art/Source/Blender/characters/Hand_Poses.json` (copies in `Art/Export/FBX/` and `Art/Export/GLB/`) |
| Textures | `Art/Textures/Characters/Gloves/T_Glove_Normal.png` (OpenGL), `T_Glove_Normal_DX.png`, `T_Glove_{Coyote,Black}_BaseColor.png` (sRGB), `T_Glove_{Coyote,Black}_ORM.png` (linear: R AO, G roughness, B metallic) |
| FBX (Unreal, cm, no node scale) | `Art/Export/FBX/SK_Hands_Gloved.fbx` (skeleton + 2 gloves), `SK_Human_Base_Gloved.fbx` (skeleton + body without the covered skin + gloves), `A_Hand_Poses.fbx` (skeleton + 14 takes) |
| GLB (web) | `Art/Export/GLB/Hands_Gloved_Coyote.glb`, `Hands_Gloved_Black.glb`, `Human_Base_Gloved_Coyote.glb` (all with the 14 animations) |
| Evidence | `Art/Previews/Hands/*.png`, `Art/Previews/Hands/Hands_validation.json` |

Rebuild: `python3 Art/Source/Blender/characters/human_base.py` (base, ~20 min with renders) then
`python3 Art/Source/Blender/characters/hands_gloves.py` (build 15 s, textures ~2 min, poses
~19 min, validate ~5 min, renders ~40 min, export ~3 min; 4 CPU cores). Stages: `--stages
build,textures,poses,validate,render,export`; render subsets `--only
hand01,black,closeups,grips,sections`. Everything is deterministic (no unseeded randomness; the
fitting uses fixed grids and deterministic Powell searches).

---

## 1. Hand anatomy pass on `SK_Human_Base` (fixes before → after)

The independent review (R1) found the finger joints near the **back** of the fingers, so a fist
pushed the fingertips through the back of the hand and the tested fist had to be capped at
80/90/45°. The fixes live in `human_base.py` / `ivchar.py` (R1 section 8 and the new section 10).

| Item | Before | After |
| --- | --- | --- |
| Finger joint depth (dorsal fraction = dorsal / (dorsal + palmar) thickness through the joint) | MPFB cubes: PIP/DIP 0.13–0.27 (3–5 mm under the dorsal skin), MCP at the finger webs | PIP / DIP **0.44–0.47** (centred), MCP **0.35** (knuckle depth, i.e. slightly palmar of the metacarpal-head top: 10–11 mm under the dorsal skin, 17–21 mm above the palmar skin); MCP moved 1.2 cm proximally from the web to the knuckle; PIP/DIP centred sideways |
| Bone axes | per-bone MPFB rolls, X axes of one finger up to 3.1° apart (thumb IP/MCP 4.9°) | every finger chain (and thumb MCP + IP) **shares one flexion axis exactly** (0.000°); the chain was made planar first (joint shifts ≤ 1 mm, reported per finger in `HumanBase_validation.json → finger_axes`) |
| Pose angles | curls were added on top of the relaxed rest pose (already MCP 11–14°, PIP 8–14° flexed), so "90/100/70" was really ~104/110/73 and drove the fingertips ~15 mm into the palm | poses are **anatomical** (0 = straight finger); the measured rest offsets are stored on the armature (`iv_hand_rest_angles`) and in the data (`Hand_Poses.json → conventions.rest_offsets_deg`) |
| MCP abduction | (new) | joint-coordinate-system order `q = Rx(flexion) · Rz(abduction)`: abduction turns the finger about its own floating axis, so a flexed finger still moves **sideways**. (The first implementation used `Rz · Rx`; at 90° MCP that turned "abduction" into a twist of the finger about its long axis, which swung the curled fingertips into the neighbour.) Read back exactly (Euler `ZXY`) |
| Full fist | capped at 80/90/45 (fingertips through the back beyond that) | MCP 90°, PIP 88–100°, DIP 55–70° per finger (index 90/88/55, middle 90/100/70, ring 90/90/57.5, little 90/100/70) with a slight fan (abduction +4 / 0 / −3 / −6°): **0 vertices through the back of the hand**, fingertip-into-palm **0.0 mm** on the bare skin (glove 0.6 mm), neighbouring fingers press ≤ 2.9 mm into each other (without the fan 5.0 mm) |
| Weights | MPFB finger weights centred on the old joints | procedural finger weights around the re-seated joints (R1), web and thumb splits smoothed |
| Thumb | CMC 4.3 cm distal of the wrist joint in the thenar, metacarpal 3.5 cm / proximal 4.0 / distal+tip 3.2 cm | kept (the joints coincide with the thumb's weight splits and creases; see §7 for the proportion caveat); thumb MCP + IP now share one axis; rest thumb: metacarpal 40° radial and 46° palmar of the index metacarpal, flexion plane ~77° to the fingers' (opposition) |

Phalanx lengths (joint to joint, tip marker for the distal; cm): index 4.33 / 2.79 / 2.54,
middle 5.28 / 3.27 / 2.57, ring 4.82 / 2.97 / 2.54, little 3.89 / 1.97 / 1.76 (proximal /
middle 1.55–1.97, anatomical 1.6–1.8); thumb 3.47 / 4.01 / 3.17. Hand length 21.0 cm, breadth 9.3
cm.

## 2. Tactical gloves

Soldiers always wear gloves, so the glove is the in-game hand surface.

**Construction of the shell (`ivhands.build_glove`).**
1. Region: the body faces dominated by the hand / finger bones, plus the forearm up to **8.0 cm
   proximal of the wrist joint** (the cuff).
2. The back of the hand over the knuckles is pre-refined once (158 faces), then the region gets
   one Catmull-Clark level (limit surface): 8,963 vertices / 17,884 triangles per glove.
3. The smooth surface is offset along its normals by the material thickness **plus how far the
   original low-poly skin lies outside the smooth surface** (up to 2.1 mm at convex fingertips),
   so the skin can never be outside the glove at rest: fabric 1.0 mm, synthetic leather 1.25 mm,
   neoprene cuff 1.3 mm, + 0.15 mm margin.
4. Construction reliefs are part of the same shell (it cannot float or detach): knuckle guard
   (1.4 mm plate + 3.0 mm segmented pads over the four MCPs), PIP pads on the four fingers and an IP
   pad on the thumb (1.9 mm), fingertip caps (0.35 mm), palm / thumb-saddle patches (0.55 mm),
   wrist strap (1.6 mm, overlapping end 1.2 mm more, pull tab).
5. A rolled hem closes the cuff opening (2.2 mm edge + 9 mm inner lining). The lining follows the
   shell's taper 3 mm under it and takes the weights of the shell above it, so it stays inside the
   cuff at every wrist extreme (a first version at a constant radius touched the shell where the
   forearm narrows and showed through at 60° extension).
6. The right glove is the exact mirror of the left one (same UVs, one texture set).

Weights: the body's weights, interpolated by the subdivision, limited to **4 influences** and
normalised (every vertex weighted). The glove therefore bends exactly like the skin under it.

**Zones (all from smooth rest-pose fields, see `GLOVE_DESIGN` in `ivhands.py`):**

| Zone | Material | Where |
| --- | --- | --- |
| Palm, finger fronts | synthetic leather, fine pebble grain | palmar field > 0.12 (finger local +Z / palm normal, weight blended) |
| Fingertip caps | synthetic leather, reinforced (wraps 5 mm further on the pad side) | distal 12 mm (thumb 14 mm) of each finger |
| Thumb saddle + palm heel patches | double-layer leather, double stitched | disc around the thumb–index web (both sides), hypothenar ellipse |
| Back, finger backs, side gussets | stretch knit fabric | everything else on the hand |
| Knuckle guard + PIP / IP pads | moulded TPR, stitched flange | over the metacarpal heads (segmented, grooves between fingers) and the dorsal proximal phalanges |
| Cuff | neoprene | from 1 cm distal of the wrist joint to the opening |
| Wrist strap | hook-and-loop webbing with overlapping end and pull tab | 2.6 cm band 3.1 cm proximal of the wrist joint |
| Hem / lining | dark lining fabric | the cuff opening |

**Textures (`ivhands.glove_textures`, 2048², one UV set, 55 px/cm, 49 % coverage).** The material
is evaluated **per texel** in numpy from the interpolated zone fields: seams are smooth curves (not
mesh edges), every seam has a groove, and stitch rows are dashed with a true 3.1 mm pitch along
the seam (55 % thread). Height detail (knit, grain, stipple, loop fabric, relief edges, grooves,
threads) is converted to a tangent-space normal with each texel's UV Jacobian (MikkTSpace-style
frame, correct for rotated / mirrored islands). AO = Cycles AO bake (8 mm) × seam cavity. The
coyote and black variants share the normal map; each has its own BaseColor and ORM.

## 3. Pose library

Angles are anatomical (§1) and stored exactly in `Hand_Poses.json`; each pose is also a Blender
action and an exported clip.

| Pose (action) | Side | Kind / method |
| --- | --- | --- |
| `relaxed` (`A_Hand_Relaxed`) | both | authored cascade MCP 18–33, PIP 28–40, DIP 10–14 |
| `open_flat` (`A_Hand_OpenFlat`) | both | all finger joints 0, thumb extended in the palm plane |
| `spread` (`A_Hand_Spread`) | both | MCP −5, abduction index +12 / middle +2 / ring −10 / little −22, thumb radial abduction |
| `fist_full` (`A_Hand_FistFull`) | both | MCP 90 / PIP 100 / DIP 70 start with a slight fan (+4 / 0 / −3 / −6°), PIP and DIP lowered per finger until the fingertip pad sinks ≤ 1 mm into the palm; thumb across the index / middle middle phalanges (bare-skin contact search) |
| `fist_25`, `fist_50`, `fist_75` | both | linear transition steps open_flat → fist_full |
| `A_Hand_OpenToFist` | both | clip, frames 1–41: open, 25 %, 50 %, 75 %, fist every 10 frames |
| `point` (`A_Hand_Point`) | both | index 5 / 5 / 3, other fingers as the fist, thumb on the middle finger |
| `rifle_grip_index_straight` | right | IV-7 pistol grip, index straight along the lower receiver (trigger discipline) |
| `rifle_grip_trigger` | right | same grip, index pad on the trigger |
| `support_handguard` | left | IV-7 handguard at `socket_support_hand`, thumb forward along the left side |
| `mag_grasp` | left | seated IV-7 magazine below the magwell (reload grasp) |
| `pistol_2h` | right + left | two-handed thumbs-forward grip on a **proxy** pistol (no pistol asset exists yet) |

Weapon grips store, besides the finger angles, `hand_attach`: the hand bone's world matrix in the
weapon socket's frame (`hand_world = socket_world × hand_attach`). In the engine this is the IK
target of the hand (the fingers come from the clip).

**Fitting (`hands_gloves.py`, `ivhands.py` §4–6).** Everything is measured on the **glove** (the
in-game surface) with a numpy re-implementation of the armature skinning (checked against Blender:
max 0.0003 mm difference) and BVH queries on the evaluated IV-7 meshes (appended read-only from
`iv7_carbine.blend`; nothing is written back):
1. **Pistol grips (IV-7 grip, magazine, proxy pistol): placement by the grip's anatomy**
   (`pistol_grip_frame_search`). The palm (2nd–5th metacarpals) lies on the grip's side, the
   knuckle row along the grip axis (index on top), the straight fingers point forward, and the
   middle MCP joint starts about one proximal phalanx behind the front strap, one finger radius
   under the trigger guard. The hand then moves along its palm normal to first contact (0.5 mm).
   Yaw, knuckle-row tilt, forward offset and height are searched (IV-7: 120 candidates). Each
   candidate is scored on: the finger wrap measured on the **grip only**, no finger touching
   anything else (the trigger guard), no penetration, the knuckle row parallel to the grip axis,
   a high grip (the middle finger right under the guard), the index along the frame, and, for
   the firing hand, that the **same placement lets the index pad reach the trigger face**
   (coupled-angle grid). This is how a shooter holds a pistol grip: the proximal phalanges lie
   along the side, the PIPs turn the front corner, the middle phalanges span the front strap and
   the distal phalanges rest on the far side.
2. **Handguard:** a diagonal power grasp (the object axis runs from the palm heel to the web),
   height / yaw / tilt searched.
3. **Fingers:** a tendon-coupled curl (MCP : PIP : DIP = 0.85 : 1 : 0.65) to first contact, then the
   joints distal of the first touching segment keep closing; then a wrap optimisation of all three
   joints so every segment rests on the object (target 0.8 mm) with a soft anatomical coupling (DIP
   within 0.3–0.9 × PIP, MCP no more than 25° beyond PIP). A finger that misses the object stops at
   the tuned full fist (it never curls into the palm).
4. **Index:** trigger discipline = straight finger along the receiver side above the trigger guard
   (rising 17° from its MCP) with its pad side on the receiver; trigger = the hand of the
   trigger-discipline grip, allowed to shift ≤ 4 mm / 3°, with the distal pad moved onto the
   trigger's front face (0.6 mm) by a joint hand + index refinement; the other fingers re-wrap, the
   thumb stays.
5. **Thumb:** a multi-start optimisation for pad contact plus a direction (forward along the left
   side of the grip / handguard / frame).
6. **Two-handed pistol:** the firing hand as above; the support hand holds grip + firing fingers
   like a grip from the left (palm over the firing fingertips on the left panel, its index right
   under the trigger guard, all four fingers wrapping the firing hand's fingers; contact with frame
   / slide / trigger / guard penalised); the posed right glove is part of its collider.
7. Every bounded Powell search is guarded (scipy's bounded Powell sometimes returned a point worse
   than its start on these contact costs; the start is kept then).
8. Validation measures the result independently (exact ray-parity penetration, weapon vertices
   inside the glove, per-segment gaps).

## 4. Validation results (from `Hands_validation.json`)

How it is measured (`hands_gloves.py --stages validate`, `ivchar.hand_contact_metrics`,
`ivhands.skin_vs_glove`):
- **Penetration inside the hand** (bare skin and glove shell): a vertex is buried when the point
  0.3 mm in front of it lies inside the closed surface (ray-parity vote). For a buried vertex the
  surfaces of other parts are searched: its depth is the distance to the nearest point of the part
  it is inside, and it must lie on the inner side of that surface (otherwise it is skin folding
  into its own joint crease — reported as `crease`, hidden, like real skin). Categories:
  fingertip→palm, finger↔finger, thumb, crease.
- **Glove vs skin:** each skin vertex against its own glove patch (the glove faces that lay within
  8 mm of it at rest), signed by the face normal.
- **Weapon:** glove vertices inside the weapon (parity) and weapon vertices inside the glove
  (nearest-face), per finger segment, plus per-segment gaps; the cuff / forearm is reported
  separately because in the hand-only evaluation it simply follows the hand (its in-game
  position comes from the arm IK).

| Check (all poses + 4 wrist extremes, both hands) | Limit | Worst | Result |
| --- | --- | --- | --- |
| Joint angles read back from the posed rig vs the library | < 0.05° | 0.001° | **PASS** |
| Phalanx (bone) length change | < 0.001 mm | 0.0000 mm | **PASS** |
| Bare skin: vertices through the back of the hand | 0 | 0 | **PASS** |
| Bare skin: fingertip into the palm | ≤ 1.5 mm | 0.00 mm | **PASS** |
| Bare skin: neighbouring fingers pressing into each other | ≤ 4 mm | 2.90 mm | **PASS** |
| Bare skin: thumb into fingers / palm | ≤ 4 mm | 2.90 mm | **PASS** |
| Glove: skin poking through (SK_Human_Base_Gloved, skin left under the cuff; incl. wrist extremes) | ≤ 0.5 mm | 0.27 mm | **PASS** |
| Glove: cuff lining outside the shell (incl. wrist flex 70 / ext 60 / ulnar 30 / twist 80) | ≤ 0.1 mm | 0.00 mm | **PASS** |
| Glove: fingertip into the palm | ≤ 1.5 mm | 1.33 mm | **PASS** |
| Glove: neighbouring finger shells overlapping (bare limit + 2 shells) | ≤ 6.5 mm | 5.51 mm | **PASS** |
| Glove: thumb shell overlapping fingers / palm | ≤ 6.5 mm | 5.83 mm | **PASS** |
| Weapon inside the glove (glove vertices in the weapon, weapon vertices in the glove; hand region) | ≤ 2 mm | 0.14 mm | **PASS** |
| Every holding digit of every grip has a segment within 0–3 mm of the right part | all | all | **PASS** |

Per pose (left hand for two-sided poses; the right hand is the mirror and measures the same within 0.1 mm):

| Pose | Finger angles MCP/PIP/DIP (abd), index · middle · ring · little | Thumb cmc flex/abd/rot, MCP, IP | Bare: tip→palm / finger↔finger / thumb (mm) | Glove: tip→palm / finger↔finger / thumb (mm) |
| --- | --- | --- | --- | --- |
| `relaxed` | 18/28/10 (+2) · 24/34/12 · 28/38/14 (-2) · 33/40/14 (-5) | 5/10/5, 12, 15 | 0.0 / 0.0 / 0.0 | 0.0 / 0.2 / 0.0 |
| `open_flat` | 0/0/0 · 0/0/0 · 0/0/0 · 0/0/0 | -15/0/0, 0, 0 | 0.0 / 0.0 / 0.0 | 0.0 / 0.0 / 0.0 |
| `spread` | -5/0/0 (+12) · -5/0/0 (+2) · -5/0/0 (-10) · -5/0/0 (-22) | -35/-5/0, 0, -5 | 0.0 / 0.0 / 0.0 | 0.0 / 0.0 / 0.0 |
| `fist_full` | 90/88/55 (+4) · 90/100/70 · 90/90/58 (-3) · 90/100/70 (-6) | 36/30/0, 40, 20 | 0.0 / 2.9 / 0.8 | 0.6 / 5.5 / 4.2 |
| `fist_25` | 22/22/14 (+1) · 22/25/18 · 22/22/14 (-1) · 22/25/18 (-2) | -2/8/0, 10, 5 | 0.0 / 0.0 / 0.0 | 0.0 / 0.1 / 0.0 |
| `fist_50` | 45/44/28 (+2) · 45/50/35 · 45/45/29 (-2) · 45/50/35 (-3) | 10/15/0, 20, 10 | 0.0 / 0.0 / 0.0 | 0.0 / 0.6 / 0.0 |
| `fist_75` | 68/66/41 (+3) · 68/75/52 · 68/68/43 (-2) · 68/75/52 (-4) | 23/22/0, 30, 15 | 0.0 / 0.0 / 2.9 | 0.0 / 2.8 / 5.8 |
| `point` | 5/5/3 · 90/100/70 · 90/90/58 (-3) · 90/100/70 (-6) | 36/30/0, 40, 20 | 0.0 / 2.9 / 0.0 | 0.6 / 5.5 / 1.8 |

Weapon grips (glove against the evaluated IV-7 / proxy pistol meshes):

| Grip | Side | Finger angles MCP/PIP/DIP (abd) | Thumb | Deepest glove↔weapon (mm) | Holding segments in contact 0–3 mm |
| --- | --- | --- | --- | --- | --- |
| `rifle_grip_index_straight` | r | 0/0/0 (+10) · 8/75/32 · 13/54/53 · 11/23/24 | 22/10/35, 8, 70 | 0.00 | middle: middle_01/middle_02/middle_03, ring: ring_01/ring_02/ring_03, pinky: pinky_01/pinky_02/pinky_03, thumb: thumb_03, index: index_02/index_03 |
| `rifle_grip_trigger` | r | 0/23/19 (-8) · 8/75/32 · 13/54/53 · 11/23/24 | 22/10/35, 8, 70 | 0.08 | middle: middle_01/middle_02/middle_03, ring: ring_01/ring_02/ring_03, pinky: pinky_01/pinky_02/pinky_03, thumb: thumb_03, index_03: index_03 |
| `support_handguard` | l | 64/60/21 · 60/75/49 · 84/50/0 · 92/100/70 | -27/-8/35, 12, 35 | 0.00 | index: index_01/index_02/index_03, middle: middle_03, ring: ring_02/ring_03, thumb: thumb_01/thumb_03 |
| `mag_grasp` | l | -2/17/18 · 7/13/70 · -1/25/25 · 9/16/18 | 27/14/15, 32, 67 | 0.00 | index: index_01/index_02/index_03, middle: middle_01/middle_02, ring: ring_02/ring_03, pinky: pinky_01/pinky_02/pinky_03, thumb: thumb_03 |
| `pistol_2h` | r | 2/24/33 (-8) · 13/42/9 · 16/30/46 · 18/0/4 | 39/5/31, 9, 37 | 0.14 | middle: middle_01/middle_02, ring: ring_02, pinky: pinky_01/pinky_02/pinky_03, index_03: index_03 |
| `pistol_2h` | l | 16/0/0 · 13/19/21 · 27/2/8 · 63/38/32 | -30/15/32, 14, 53 | 0.11 | index: index_01/index_02/index_03, middle: middle_02/middle_03, ring: ring_02/ring_03, thumb: thumb_03 |

Exports re-imported with Blender's stock importers (clean scene): `SK_Hands_Gloved.fbx`, `SK_Human_Base_Gloved.fbx`, both glove GLBs: **PASS** (57 bones, 8,963 vertices / 17,884 triangles per glove, 0 unweighted, ≤ 4 influences, sums 1). `A_Hand_Poses.fbx` and the GLB animations: 14 actions, every static pose's finger rotations reproduced to **0.000°** (FBX) / **0.000°** (GLB), rest offsets measured on the re-imported rig within 0.001° of the data: **PASS**.

## 5. Evidence renders (`Art/Previews/Hands/`)

All renders: Cycles CPU, neutral studio light, ≤ 1600 × 900. Every image was looked at and the
digits counted (five per visible hand, thumb opposed, joints bending the right way).

| File(s) | Content | What the renders show |
| --- | --- | --- |
| `Hands_bare_<pose>.png`, `Hands_coyote_<pose>.png` (8 poses each: `open_flat`, `fist_25`, `fist_50`, `fist_75`, `fist_full`, `relaxed`, `spread`, `point`) | HAND-01 sheets: both hands, rows left / right, columns palm / back / side | Five digits on every hand in every view; the thumb opposes the fingers; the transition steps close smoothly (MCP, PIP and DIP together); the full fist is compact with the thumb across the index / middle middle phalanges and nothing through the back of the hand; `point` has a straight index with the other fingers in the fist; `spread` shows clean webs. The glove follows the hand exactly: knuckle guard and PIP pads stay on the joints, no floating or piercing, seams and stitches continuous across creases. |
| `Hands_black_{open_flat,fist_50,fist_full}.png` | the black glove variant | Same shell and normal map with the black BaseColor / ORM |
| `Hands_closeup_fist_knuckles_{bare,coyote}_{l,r}.png`, `Hands_closeup_fist_thumb_*` | knuckle and thumb close-ups at the full fist | Four knuckles in a row with the segmented guard over them; the fingers press together along clean contact lines; the thumb lies on the index / middle phalanges |
| `Hands_closeup_wrist_{flex70,ext60,ulnar30,twist80}_{bare,coyote}.png` | wrist extremes (twist bones driven) | Smooth hand-to-forearm transition; the palmar crease folds at 70° flexion as skin does; no candy-wrapper at 80° twist; the cuff, strap and hem stay closed (the cuff lining stays inside the shell, validated per pose) |
| `Hands_sections_fist_{bare,coyote}.png` | 2D sections through each finger's curl plane at the full fist | The joint centres (orange) sit inside the phalanx outlines; the curled fingertip stays inside the fist and never reaches the back of the hand; at the palmar PIP / DIP creases the surface folds into small loops (skin compression, hidden inside the fist) |
| `Hands_grip_<grip>_<view>.png` (two close views per grip) | `rifle_grip_index_straight`, `rifle_grip_trigger`, `support_handguard`, `mag_grasp`, `pistol_2h` on the real IV-7 (proxy pistol for `pistol_2h`) | Rifle grip: web high under the tang, middle finger right under the trigger guard, fingers wrapping the grip, index straight along the receiver side above the guard (trigger discipline) or its pad on the trigger face; thumb on the left side of the grip. Handguard: the fingers wrap the handguard from the right, thumb along the left side. Magazine: palm on the left flank, fingers round the front edge onto the right flank. Pistol: firing index on the trigger, support fingers over the firing fingers under the guard, both thumbs forward on the left. |
| `Hands_grip_<grip>_fp.png` | first-person camera (eye at the head, 80° horizontal FOV) with the whole body posed and the arms solved by two-bone IK to the grip transforms | What the player sees: the rifle in the shoulder pocket with the support hand on the handguard (magazine grasp during a reload for `mag_grasp`), the firing hand at the lower right; the pistol held two-handed in front |
| `Hands_grip_<grip>_stance.png` | outside view of the same stance | Arms continuous from the shoulders to the hands; butt stock in the shoulder pocket |



## 6. Engine notes (unverified in Unreal)

- The gloves are skinned to the full 57-bone `SK_Human_Base` skeleton (same bone names, same
  rest pose): import `SK_Hands_Gloved.fbx` onto the existing `SKEL_Human_Base`. For first-person
  arms use `SK_Human_Base_Gloved.fbx` (the body without the covered skin).
- `A_Hand_Poses.fbx` holds 14 takes (13 static poses + `A_Hand_OpenToFist`); only the finger and
  thumb bones are keyed. Use them as additive/override finger poses in a layered blend per bone
  branch (hand_l / hand_r subtrees) on top of the arm animation.
- Twist bones and corrective shapes: the runtime rules of `SK_Human_Base`
  (`Art/Export/*/Human_Base.runtime.json`) still apply; the gloves carry no shape keys (the
  elbow / knee / hip correctives do not reach the glove region).
- Normal maps: use `T_Glove_Normal_DX.png` in Unreal (the FBX export already points at it), the
  OpenGL map in three.js. ORM is linear (sRGB off).

## 7. Known issues and limits

| # | Severity | Issue | Status / next step |
| --- | --- | --- | --- |
| 1 | P0 (external) | Unreal import, the layered finger-pose blend, hand IK to `hand_attach` and the in-engine look were not tested. HAND-02 items that need animation (idle, walk, sprint, ADS, recoil, both reloads, IK hand-off during a reload) and HAND-03 (FOV, camera, visibility) cannot be tested without the engine / animation set. | **BLOCKED** (no Unreal, no animation system here). The static grips and their `hand_attach` transforms are the inputs for that work. |
| 2 | P2 | LBS has no soft-tissue contact: in the full fist neighbouring fingers press up to 2.9 mm into each other (bare) and their glove shells up to 5.5 mm; the palmar creases fold into themselves. | Hidden in the contact lines (renders `Hands_bare_fist_full.png`, `Hands_coyote_fist_full.png`, `Hands_sections_fist_*`). A contact corrective shape would be the next step if close-ups demand it. |
| 3 | P2 | The glove worn over the **full bare hand** of `SK_Human_Base` is pierced by the skin in deep flexion (palmar creases up to 1.9 mm in the fist, `glove_vs_full_bare_hand` in the report). | By design the shipped `SK_Human_Base_Gloved` has the covered skin removed (only the cuff band remains, max 0.27 mm under the cuff). Do not layer the gloves over the bare body mesh. |
| 4 | P2 | Some fitted fingers break the soft DIP/PIP coupling where the geometry forces it: support hand ring 84/50/0 (flat distal pad on the handguard side), magazine middle 7/13/70 (fingertip hooked round the front edge), pistol: firing little finger 18/0/4 and support index 16/0/0 (straight, lying along the firing fingers). | Visible only at close range; the renders read naturally. Re-fit with a stronger coupling weight or a hand-tuned pose if an animator wants it. |
| 5 | P2 | `pistol_2h` is fitted to a **proxy** pistol (no pistol asset exists). The support hand holds loosely (mean segment gap 2.8 mm) and its index lies straight under the trigger guard instead of wrapping the firing fingers. | Re-run `--stages poses` once a real pistol exists (only the prop and `fit_pistol_2h` change). |
| 6 | P2 | The grips are fitted to the IV-7 geometry of 2026-09-27 (grip, trigger, handguard, magazine unchanged by the parallel IV-7 fix round). | If the IV-7's grip, trigger, handguard or magazine change, re-run `--stages poses,validate,render`. |
| 7 | P2 | First-person stance: the arms are solved by a simple two-bone IK with fixed poles and no wrist limits; the right wrist deviation follows from the fitted grip. | Shown in `Hands_grip_*_fp.png` / `_stance.png`; the engine's arm IK and FP camera replace it. |
| 8 | info | Thumb proportions: MPFB's CMC joint sits 4.3 cm distal of the wrist inside the thenar and the metacarpal / proximal / distal lengths are 3.5 / 4.0 / 3.2 cm (the proximal phalanx is long relative to the metacarpal). The joints match the mesh's creases and weights, so they were kept. | Revisit with a hand-specific base mesh. |
| 9 | info | Textures are procedural (numpy per texel); there is no hand-painted wear, no dirt layer and no separate detail map. 2048² for both gloves (mirrored UVs, 55 px/cm). | Enough for first-person distance; add wear masks later. |
| 10 | info | Right glove = mirrored left glove (identical UVs and texture). A seam, stitch or logo that should differ left / right cannot. | None needed now (no logos). |

