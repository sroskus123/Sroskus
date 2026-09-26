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
