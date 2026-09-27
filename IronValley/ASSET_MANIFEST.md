# IRON VALLEY: asset manifest

One row per shippable asset.

| Status value | Meaning |
| --- | --- |
| PASS | Backed by evidence |
| FAIL | Tested and failed |
| NOT TESTED | No test has been run |
| BLOCKED | An external blocker prevents the test |

Unreal Engine is not available in the current environment, so no asset has been imported into
Unreal. Every Unreal path below is a **planned** location. Higgsfield was **not used** for these
assets because it is not available (no connector; network blocked).

| Asset | Author/source | Terms of use | Reference | Editable source | Exports | Unreal path | Fixes applied | QA status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| IV-7 carbine (skeletal): `SK_IV7_Carbine` + LOD1/LOD2 | Procedurally modelled by script in this project (original design). Generated with the Iron Valley Blender pipeline (`ivlib`). No third-party models, textures or scans. Higgsfield not used (not available). | Project-owned original work. Roll-mark letters are cut from Blender's built-in UI font (DejaVu Sans-based, permissive licence). No real brand names or trademarks. | `Art/Reference/IV7_carbine_spec.md` (this document is the reference; no images exist) | `Art/Source/Blender/weapons/iv7_carbine.py` + `Art/Source/Blender/lib/ivlib.py`. Generated `Art/Source/Blender/weapons/iv7_carbine.blend` | FBX: `Art/Export/FBX/SK_IV7_Carbine.fbx`, `SK_IV7_Carbine_LOD1.fbx`, `SK_IV7_Carbine_LOD2.fbx`. GLB: `Art/Export/GLB/IV7_Carbine.glb`, `IV7_Carbine_LOD1.glb`, `IV7_Carbine_LOD2.glb`. Textures: `Art/Textures/Weapons/IV7/T_IV7_{Body,Furniture}_{BaseColor,Normal,Normal_DX,ORM}.png` | `/Game/IronValley/Weapons/IV7/SK_IV7_Carbine` (+ `SKEL_IV7`, `M_IV7_Body`, `M_IV7_Furniture`, `M_IV7_Glass`, `M_IV7_Reticle`, `T_IV7_*`): **NOT IMPORTED (Unreal unavailable)** | Iteration log (build 1 onward): see note (1) below the table | Blender geometry/UV/skin validation: **PASS**, 0 problems across LOD0/1/2 and the magazine (non-manifold, loose, zero-area, duplicate, winding, folded faces, UV bounds/overlap, rigid weights, image paths; `Art/Previews/IV7/IV7_validation.json`). Dimensions vs spec: **PASS** (OAL 86.0 cm, barrel 36.8, handguard 33.0 × 5.0, device 5.5 × 2.2, optic/irons 7.0 cm co-witness). FBX + GLB re-import in Blender's stock importers: **PASS** (dimensions, 38 meshes, 17 bones, materials and images). Rig pivots: **PASS** (pose-test render). Visual review of Cycles renders: done (see `self_assessment`). Unreal import / in-game look / LOD switching in engine: **BLOCKED** (no Unreal). |
| IV-7 magazine (static): `SM_IV7_Magazine` | Same as above (same generator; body + two visible cartridges joined) | Same as above | `Art/Reference/IV7_carbine_spec.md` (magazine rows) | `Art/Source/Blender/weapons/iv7_carbine.py` (`static_magazine()`) | FBX: `Art/Export/FBX/SM_IV7_Magazine.fbx`. GLB: `Art/Export/GLB/IV7_Magazine.glb`. Uses the Furniture texture set | `/Game/IronValley/Weapons/IV7/SM_IV7_Magazine`: **NOT IMPORTED (Unreal unavailable)** | Pivot at the magazine catch (same point as the `magazine` bone), placed at the world origin because Unreal bakes the FBX node transform into static meshes. Magazine is moved away during the AO/mask bake so a dropped magazine carries no weapon occlusion. Custom normals re-weighted after merge. | Validation: **PASS**. FBX/GLB re-import (Blender): **PASS**. Unreal: **BLOCKED**. |
| Human base (skeletal): `SK_Human_Base` (57 bones, 1.80 m adult male, A-pose). The base for every character, the FP arms and the hands. | **Third-party data (CC0 1.0):** MakeHuman hm08 base mesh, macro and measure targets, MPFB2 `game_engine` rig and weights (MakeHuman team; `base.obj` names Data Collection AB, J. Palmius, J. Hauquier). Vendored byte-identical from the PyPI wheel `anny 0.6.0` (NAVER; package code Apache-2.0, no code copied) into `Art/ThirdParty/mpfb2/` (5.9 MB; hashes and list in `SOURCE.md`). Shape choices, weight fixes, twist bones, rest pose and validation are project work by script. Higgsfield not used (not available). | CC0 1.0 for the MakeHuman/MPFB2 data (`Art/ThirdParty/mpfb2/LICENSE.md`): commercial use and modification allowed, no attribution required (credited anyway). No real person, brand or trademark. | `Art/Reference/HUMAN_BASE_spec.md` (proportions, skeleton, rest pose, conventions, derivation rules) | `Art/Source/Blender/characters/human_base.py` + `Art/Source/Blender/lib/ivchar.py` (+ `ivlib.py`). Generated `Art/Source/Blender/characters/human_base.blend` | FBX: `Art/Export/FBX/SK_Human_Base.fbx`. GLB: `Art/Export/GLB/Human_Base.glb`. No textures (one clay material slot `M_Human_Base`) | `/Game/IronValley/Characters/Base/SK_Human_Base` (+ `SKEL_Human_Base`): **NOT IMPORTED (Unreal unavailable)** | See note (2) below the table | Geometry (closed 2-manifold, UVs 0..1, normals, outward volume): **PASS**. Stature 1.800 m, feet on Z = 0, facing −Y: **PASS**. Skeleton with UE-mannequin names and hierarchy (+ 4 UE4 twist bones): **PASS**. Skin (0 unweighted, ≤4 influences, sums 1, L/R exact): **PASS**. Joints inside the mesh / tips on the surface: **PASS**. Proportions within plausibility ranges: **PASS**. FBX + GLB re-import in Blender (1.80 m, 57 bones, heads ±0.07 mm, weights intact): **PASS**. Deformation test poses (12 + 2 driven) rendered and reviewed: done; known P2 items are listed in the spec §13 (elbow tip at 120°, squat gluteal pinch, fist limit 80/90/45). Candy-wrapper on plain LBS at an 80° wrist twist (ring 0.79) is fixed to 0.95 **only if the twist-bone rule is implemented at runtime** (NOT TESTED in engine). Evidence: `Art/Previews/HumanBase/` (65 PNGs + `HumanBase_validation.json`). Unreal import, in-engine skinning and retargeting: **BLOCKED** (no Unreal). |
| Game audio (web): 98 MP3 files, 41 sound keys (`Web/public/assets/audio/`, 624 KiB) | Third-party recordings under CC0 1.0 (The Free Firearm Sound Library: AR-15 5.56 and Walther PPQ 9 mm; Kenney Impact Sounds and RPG Audio; LFA; SpringySpringo; Fantozzi/qubodup; Ali_6868) and CC BY (Eelke CC BY 4.0 + congusbongus CC BY 3.0: metal footsteps; InspectorJ CC BY 4.0: robin). Wind, bullet near-miss, casings and impact layers: procedural synthesis in this project (**provisional**). | CC0 / CC BY only, attribution in `Shared/audio/SOURCES.md` and in the game (Ovládání → Zvuky — autoři a licence). No NC/ND. | `Shared/audio/SOURCES.md` (per-file source URL, author, licence evidence, SHA-256, edits, measured peak/RMS) | `Tools/audio/sources.json` (pinned), `Tools/audio/fetch_sources.py`, `Tools/audio/build_audio.py`, `Tools/audio/write_sources.py` | MP3 44.1 kHz VBR; bank `Web/src/data/audio_bank.json` | not planned yet (UE import BLOCKED) | Loudness plan (rifle close TP −3 dBFS, steps active RMS −24, ambience RMS −36); trimmed lead-ins; aliasing-free modal synthesis; near-identical C-Dogs wood set replaced by CC0 Kenney layers | Spectrogram / waveform review (PNG), unit + e2e tests (decode in Chromium, event mapping, stop on pause/death): **PASS**. Listening test: **NOT TESTED** (no audio output in this environment). |

**Note (1): fixes applied to the IV-7 carbine, in iteration order.**

1. Merged boolean cutters overlapped each other and collapsed parts (0-triangle stock).
   Fixed with exact-solver self-intersection handling.
2. Triangle count was 83k, over budget. Fixed by cutting knurl flutes after bevelling and
   bevelling slots with 1 segment.
3. Dust-cover hinge moved outward so the open cover hangs parallel to the magwell. Added
   webbing so the hinge knuckles are not floating.
4. Degenerate-sliver cleanup after every boolean and bevel. The barrel-nut gas-tube hole was
   near-tangent and became an open slot. The optic bore and lens seats became one stepped
   cutter. Non-manifold / zero-area faces went from 39 problems to 0.
5. UV island budgeting: hidden and interior surfaces get less space. Body exterior went from
   ≈ 20 to ≈ 26 px/cm at 2048².
6. Material rework. The anodising looked like grey primer with speckle, so scratch dots were
   removed, edge wear limited to patchy convex edges, and cavity dirt made subtler.
7. Reticle no longer lights the optic tube. Lens thin-film reduced (the rainbow tint was too
   strong).
8. Studio rig rebuilt for dark finishes.
9. Pin-hole gaps closed. The trigger guard moved clear of the grip. Cartridges and feed lips
   given clearance. Sight leaves hinged in grooves.
10. A back-face diagnostic render found a black notch under the stock: bevelling across the
    adjustment-lever junction had folded two triangles. The stock and lever are now bevelled
    separately, and small features on the charging handle, barrel nut and bolt catch are cut
    after bevelling. A "face opposes its vertex normals" check was added to the validator, and
    the count is now 0 across all LODs.
11. Orange specks on the magazine edges, red specks on rail teeth and a dark hairline on the
    stock all came from foreign bake margins. Blender's multi-object bake margin let one
    object's margin overwrite the unrasterised border texels of another object's island. The
    bake now uses margin 0 plus a distance-based numpy dilation (`ivlib.dilate`). Sub-texel
    islands and slivers are collapsed onto a neighbouring UV point after packing.
12. Pictograms were illegible (SAFE garbled, SEMI red lost) because tiny-island UV shrinking
    had squeezed them. Markings now get 1.6× texel density.

**Note (2): fixes and decisions for `SK_Human_Base`, in build order** (details in
`Art/Reference/HUMAN_BASE_spec.md`).

1. Macro targets applied with MakeHuman 1.x semantics: male, 28 years, muscle 0.70,
   weight 0.50, height 0.50, proportions 0.50, race 1/3 each. Applying the default macros
   reproduces every rig `default_position` to within 0.3 µm, which confirms the interpretation.
2. Upper arm / forearm ratio corrected. hm08 gave a 26.1 cm upper arm and a 27.7 cm forearm
   (ratio 0.95, elbow about 4.5 cm too high). The MakeHuman measure targets `upperarm-length-incr`
   0.5 and `lowerarm-length-decr` 0.5 give 29.8 / 25.3 cm, and the mesh elbow and joint move
   together.
3. Uniform scale to exactly 1.80 m, soles on Z = 0, origin on the MakeHuman ground joint.
4. All helper geometry and joint cubes removed (eyes, lashes, teeth, tongue, tights, skirt,
   hair and genital helpers). Only the closed `body` group is kept, with its original UVs.
5. `Root` renamed `root` and placed at the origin with identity orientation (it has zero skin
   weight, so no deformation change).
6. Source weights symmetrised. They differed by up to 0.26 between left and right (calves,
   feet, pelvis); now 0.000.
7. Four UE4-mannequin twist bones added (`upperarm_twist_01_l/r`, `lowerarm_twist_01_l/r`) with
   ramped weights. The runtime rule (0.5 × twist) is in the spec §9 and in
   `ivchar.drive_twist_bones()`. Measured: wrist ring at an 80° hand twist goes from 0.79 to
   0.95; shoulder ring at a 70° humeral roll goes from 0.88 to 0.97.
8. Influences limited to 4 per vertex, mirror-exact, renormalised.
9. Rest pose: elbows straightened from the modelled 45.9° to 15°, then applied as the rest
   (A-pose; upper arms stay as modelled, 48° below horizontal).
10. Fist limit found by rendering. At 88/100/62° the fingertips pass through the thin hm08 palm
    and appear on the back of the hand; the tested fist uses 80/90/45°.
