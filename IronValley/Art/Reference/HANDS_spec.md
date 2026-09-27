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
~8 min, validate ~6 min, renders ~35 min, export ~3 min). Stages: `--stages
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
| Full fist | capped at 80/90/45 (fingertips through the back beyond that) | MCP 90°, PIP 88–100°, DIP 55–70° per finger (index 90/88/55, middle 90/100/70, ring 90/92/60, little 90/100/70): **0 vertices through the back of the hand**, fingertip-into-palm **0.0 mm** on the bare skin (glove: ≤ 1 mm) |
| Weights | MPFB finger weights centred on the old joints | procedural finger weights around the re-seated joints (R1), web and thumb splits smoothed |
| Thumb | CMC 4.3 cm distal of the wrist joint in the thenar, metacarpal 3.5 cm / proximal 4.0 / distal+tip 3.2 cm | kept (the joints coincide with the thumb's weight splits and creases; see §9 for the proportion caveat); thumb MCP + IP now share one axis; rest thumb: metacarpal 40° radial and 46° palmar of the index metacarpal, flexion plane ~77° to the fingers' (opposition) |

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
5. A rolled hem closes the cuff opening (2 mm edge + 9 mm inner lining).
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

**Textures (`ivhands.glove_textures`, 2048², one UV set, 55 px/cm, 48 % coverage).** The material
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
| `fist_full` (`A_Hand_FistFull`) | both | MCP 90 / PIP 100 / DIP 70 start, PIP and DIP lowered per finger until the fingertip pad sinks ≤ 1 mm into the palm; thumb across the index / middle middle phalanges (bare-skin contact search) |
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
1. Placement: pistol grips — the thumb–index web crotch on the back strap just below the tang, the
   index MCP beside the frame, roll searched; handguard / magazine — a diagonal power grasp (the
   object axis runs from the palm heel to the web), height / yaw / tilt searched. The hand then
   slides along its palm normal to first contact (0.5 mm).
2. Fingers: a tendon-coupled curl (MCP : PIP : DIP = 0.85 : 1 : 0.65) to first contact, then a
   wrap optimisation of all three joints so every segment rests on the object (target 0.8 mm).
3. Index: trigger discipline = straight finger pointing along the receiver axis with its pad side
   touching the receiver; trigger = the distal pad resting on the trigger (≤ 0.6 mm).
4. Thumb: a multi-start optimisation for contact plus a direction (forward along the receiver /
   handguard / frame).
5. Validation measures the result independently (exact ray-parity penetration, weapon vertices
   inside the glove, per-segment gaps).

## 4. Validation results (from `Hands_validation.json`)

RESULTS_TABLE_PLACEHOLDER

## 5. Evidence renders (`Art/Previews/Hands/`)

RENDERS_PLACEHOLDER

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

KNOWN_PLACEHOLDER
