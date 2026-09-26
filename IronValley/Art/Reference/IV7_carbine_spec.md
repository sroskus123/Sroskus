# IV-7 carbine — asset reference and specification

Project: IRON VALLEY (original realistic military FPS prototype).
Asset: **IV-7**, the project's hero weapon. An original 5.56 mm-class gas-operated carbine with
generic modern-carbine ergonomics and Iron Valley's own styling. It carries no real brand names,
trademarks or markings. The only markings are "IV-7" and "5.56 mm" roll marks and generic
selector pictograms.

No reference images exist, so **this document is the reference**. Reviewers measure against the
tables below. Every number here is either a design input to
`Art/Source/Blender/weapons/iv7_carbine.py` or a value measured from the built mesh. The
validation report `Art/Previews/IV7/IV7_validation.json` → `measurements` is regenerated on every
build.

Status: built and validated in Blender (bpy 4.5.14, headless). **Not imported into Unreal**
(Unreal is unavailable in this environment), so nothing in this document is an in-engine result.

---

## 1. Coordinate frame and conventions

| Item | Value |
| --- | --- |
| Units | metric, unit scale 1.0, 1 BU = 1 m, Z up, real-world scale |
| Orientation | muzzle **+X**, top **+Z**, weapon's right side (ejection port) **−Y**, left side (selector, bolt catch) **+Y** |
| Object origin / root bone | firing-hand **grip hold point**: on the pistol-grip centreline (Y = 0), 4.5 cm down the raked grip axis from the grip's top plane. This is where the centre of the firing-hand palm wraps. |
| Bore axis in the final frame | X runs along the bore; the bore sits at **Y = 0, Z = +9.17 cm**; the bolt face is at **X = +16.69 cm** |
| Authoring frame (script only) | centimetres, "bore frame": X = 0 at the bolt face, Z = 0 on the bore axis. `finalize()` converts to metres and moves the origin to the hold point. |

The script is the editable source. It is deterministic and uses no unseeded randomness, and it
also saves `iv7_carbine.blend` next to itself.

## 2. Silhouette description

The IV-7 has a straight-line layout: the buffer tube and stock sit on the bore axis. From the
right side, reading front to back:

- **Muzzle.** A short three-prong flash hider with open-ended slots.
- **Handguard.** A long, slim, free-float octagonal handguard with a continuous top accessory
  rail. Rounded accessory slots run along both sides and the bottom, and small vents sit on the
  upper chamfers.
- **Upper receiver.** A flat-top upper with the same rail. On the right: the ejection port with
  the bolt carrier visible through it, the hinged dust cover hanging open below it, a sculpted
  brass deflector, a forward-assist-style boss, and the T-shaped charging handle at the rear.
- **Lower receiver.** A billet-style lower with a wide magazine well that flares at the mouth
  and has shallow machined flank panels. The trigger guard is integral and open. Takedown pins,
  bolt catch, selector with pictograms and a fenced magazine release complete it.
- **Grip and stock.** A raked, stippled flat-dark-earth (FDE) pistol grip. A skeletal FDE
  carbine stock with a triangular lightening window, a sling slot and a black rubber butt pad,
  riding on a ribbed buffer tube with castle nut and a QD end plate.
- **Magazine.** A curved dark-grey polymer 30-round magazine, textured on its lower flanks, with
  the top cartridges visible between the feed lips.
- **Sights.** A compact enclosed red-dot optic on a riser, plus flip-up front and rear iron
  sights, deployed and absolutely co-witnessed.

Proportions: the handguard is about 38 % of the overall length. The magazine hangs about 12 cm
below the magwell mouth and curves forward about 2.2 cm. The optic sits over the
receiver/handguard joint.

## 3. Dimension table (targets vs. measured)

Measured values come from the built LOD0 meshes (validation report → `measurements`).
Tolerance for major proportions is ±5 %.

| Dimension | Target | Measured | Notes |
| --- | --- | --- | --- |
| Overall length, stock position 3 | ~86 cm | **86.00 cm** | Only position 3 is modelled; the stock body can later slide on the buffer tube |
| Barrel length from bolt face | 36.8 cm (14.5") | **36.80 cm** | Crown sits inside the muzzle device |
| Visible barrel OD | 1.6–1.9 cm | **1.90 cm** (x = 8 cm), **1.64 cm** (x = 30 cm) | 1.68 cm at the gas-block journal (hidden under the handguard) |
| Gas block | under the handguard | yes, x = 18.6–21.7 cm from the bolt face | Low-profile block; the straight gas tube runs back into the upper |
| Muzzle device length | ~5.5 cm | **5.50 cm** | Three open prong slots, 4.4 mm wide, 120° apart |
| Muzzle device OD | ~2.2 cm | **2.20 cm** | Wrench flats on the sides |
| Handguard length | ~33 cm | **33.00 cm** | Free float; 2 mm gap to the upper receiver |
| Handguard width | ~5 cm | **5.00 cm** | Octagonal section, 3.2 mm wall |
| Top rail width | ~21 mm | **21.2 mm** (max dovetail width) | Continuous from the upper onto the handguard at the same height |
| Rail cross-slot pitch / width | 10 mm | **10 mm / 5.3 mm**, floor 3.8 mm below the rail top | Design input |
| Rail top above bore | — | **3.00 cm** | |
| Accessory slots | real cut-through | 7 per side, 6 on the bottom, 12 vents | All are real holes; barrel and gas system are visible through them |
| Pistol grip rake | 20–25° | **22°** from vertical | Design input |
| Pistol grip length | ~11 cm | **11.0 cm** along the raked axis | Max width 3.24 cm; stippled 0.9 cm below the top down to 0.8 cm above the base |
| Magazine length along the curve | ~19 cm | **19.0 cm** | Centreline from feed-lip top to baseplate bottom |
| Magazine width | ~2.4 cm | **2.40 cm** | Baseplate 2.76 cm |
| Magazine depth (front–back) | ~6.5 cm | **6.50 cm** | |
| Optic axis above bore | ~7 cm | **7.00 cm** | |
| Iron sight line above bore | co-witnessed | front post tip **7.00 cm**, rear aperture centre **6.99 cm** | Absolute co-witness: optic axis, rear aperture and front post tip on one line parallel to the bore |
| socket_ads behind the optic's rear lens | 5–8 cm | **8.00 cm** | |
| Height with magazine, incl. optic | — | **30.9 cm** | Top of elevation turret to baseplate corner |
| Height with magazine, without optic | — | **28.9 cm** | Iron sights deployed |
| Max width | — | **5.4 cm** | End-plate sling ear (left) to optic windage turret (right) |

## 4. Part list

Every part is a separate mesh object in the collection `IV7_Parts`, parented to the armature
`SK_IV7` and rigidly skinned (100 % weight) to one bone.

| Part (object) | Material look | Texture set | Bone | Moves? |
| --- | --- | --- | --- | --- |
| UpperReceiver | black hard-anodised aluminium | Body | root | – |
| LowerReceiver (incl. integral trigger guard, magwell, engraved + paint-filled pictograms and roll marks) | black anodised aluminium; white/red paint; bare-metal roll marks | Body | root | – |
| Handguard | black anodised aluminium | Body | root | – |
| HandguardScrews | phosphated steel | Body | root | – |
| Barrel | nitrided steel, light carbon near the muzzle | Body | root | – |
| BarrelNut | phosphated steel | Body | root | – |
| MuzzleDevice | nitrided steel with carbon fouling towards the front | Body | root | – |
| GasBlock / GasTube | phosphated / nitrided steel | Body | root | – |
| BufferTube | black anodised aluminium | Body | root | – |
| EndPlate (QD sling ear) / CastleNut | phosphated steel | Body | root | – |
| ForwardAssist (plunger) | phosphated steel | Body | root | – |
| Pins (front/rear takedown, trigger, hammer) | phosphated steel | Body | root | – |
| DustCoverRod | nitrided steel | Body | root | – |
| RearSightBase / FrontSightBase (+ cross bolts) | black anodised aluminium / steel | Body | root | – |
| Optic (housing, riser mount, turrets, brightness knob, clamp knob) + OpticBolt | black anodised aluminium / steel | Body | root | – |
| OpticLensFront / OpticLensRear | glass with a thin-film coating | – (constant `M_IV7_Glass`) | root | – |
| OpticReticle | emissive red dot, bonded to the inner face of the front lens | – (constant `M_IV7_Reticle`) | root | – |
| PistolGrip | FDE polymer, stippled | Furniture | root | – |
| Stock | FDE polymer | Furniture | root | (slides later) |
| ButtPad | black rubber | Furniture | root | – |
| **Magazine** | dark-grey polymer, textured lower flanks | Furniture | magazine | yes |
| **MagRounds** (two visible cartridges) | brass case, copper jacket | Furniture | magazine | yes |
| **ChargingHandle** | black anodised aluminium | Body | charging_handle | yes |
| **BoltCarrier** (with bolt head and extractor) | nitrided steel | Body | bolt_carrier | yes |
| **DustCover** | nitrided steel | Body | dust_cover | yes |
| **Trigger** | nitrided steel | Body | trigger | yes |
| **Selector** (with white index line) | phosphated steel | Body | selector | yes |
| **BoltCatch** | phosphated steel | Body | bolt_catch | yes |
| **MagRelease** | phosphated steel | Body | mag_release | yes |
| **RearSightLeaf** (ghost-ring aperture, ears) | black anodised aluminium | Body | rear_sight | yes |
| **FrontSightLeaf** (post, ears) | black anodised aluminium | Body | front_sight | yes |

Separate `SM_IV7_Magazine` (collection `IV7_Static`) is the magazine body plus rounds joined
into one static mesh. It uses the same Furniture texture set, has its pivot at the magazine catch
(same point as the `magazine` bone), and sits at the world origin.

**Single mesh or multiple meshes?** The source keeps one object per part: readable, per-part
validation, and easy editing. Each object carries exactly one vertex group at weight 1.0.
Unreal's FBX importer merges all skinned meshes under one armature into a single skeletal mesh
with one section per material, so the in-engine result is effectively one mesh with 4 material
slots (Body, Furniture, Glass, Reticle) and no draw-call penalty for the split.

## 5. Rig, pivots and sockets

Armature object and data: **`SK_IV7`**. There are 17 bones, all children of `root`.

Every bone points along **+Y (world)** with roll 0, so each bone's local axes are world-aligned:
local **X = weapon forward**, local **Y = weapon left**, local **Z = up**.

With the documented FBX settings, Blender (x, y, z) arrives in Unreal as (x, −y, z). Bone
orientations should therefore be identity (X forward, Y right, Z up) in Unreal. This is
**unverified**: Unreal was not available.

| Bone | Head, final frame (cm: X, Y, Z) | Pivot meaning | Motion (bone-local) |
| --- | --- | --- | --- |
| root | 0, 0, 0 | grip hold point (= object origin) | – |
| magazine | 10.686, 0, 4.872 | magazine catch height, magazine centreline | translate −Z to drop; small rotation about Y to rock out |
| charging_handle | 1.386, 0, 11.022 | rear centre of the T-handle | translate −X (≈ 6.5–7 cm stroke) |
| bolt_carrier | 8.686, 0, 9.172 | on the bore axis, carrier centre | translate −X (≈ 7.5 cm stroke) |
| dust_cover | 11.536, −1.80, 7.822 | hinge-rod axis (parallel to X) | rotate about X: bind pose = **open (176°)**; −176° closes it |
| trigger | 6.686, 0, 5.072 | trigger pin | rotate about Y, about +12° when pulled |
| selector | 4.086, 0, 5.872 | selector axis | rotate about Y: 0° SAFE (lever forward, bind pose), +90° SEMI (lever down), +180° AUTO (lever back) |
| bolt_catch | 7.186, 1.3, 6.722 | roll pin | rotate about Y (±9°) |
| mag_release | 7.736, −1.3, 4.912 | button axis | translate +Y (press, ≈ 1.5 mm) |
| rear_sight | 8.386, 0, 13.692 | leaf hinge | rotate about Y: bind pose deployed; +90° folds forward |
| front_sight | 50.086, 0, 13.692 | leaf hinge | rotate about Y: bind pose deployed; −90° folds rearward |
| socket_muzzle | 57.586, 0, 9.172 | bore axis at the muzzle face | non-deforming |
| socket_ads | 1.786, 0, 16.172 | eye point on the optic axis, 8.0 cm behind the rear lens | non-deforming |
| socket_support_hand | 33.686, 0, 6.472 | handguard bottom, 17 cm ahead of the bolt face | non-deforming |
| socket_firing_hand | 0, 0, 0 | grip hold point | non-deforming |
| socket_eject | 11.536, −1.5, 9.172 | centre of the ejection port, on the receiver's right face | non-deforming |
| socket_mag | 12.536, 0, 0.372 | centre of the magwell mouth | non-deforming |

The rig is verified in Blender by `Art/Previews/IV7/IV7_rig_pose_test.png`. That render poses
every moving bone: dust cover closed, carrier and charging handle back, trigger pressed, selector
on SEMI, bolt catch up, magazine release pressed, magazine dropping, and both sights folded.

## 6. Texture plan

| Set | Size | Contents | Why this split |
| --- | --- | --- | --- |
| **Body** | 2048² | All metal parts: receivers, handguard, barrel, muzzle, gas system, buffer tube, small parts, controls, sights, optic housing | One material family (anodised aluminium plus steels) keeps value ranges coherent. These are the parts closest to the eye in first person. |
| **Furniture** | 2048² | Grip, stock, butt pad, magazine, cartridges | Lets the magazine static mesh share exactly one set. Allows colour variants (FDE / black / OD) by swapping one set without touching the metal. |
| Glass / Reticle | – | Constant materials, no textures | Transparency and emission are engine-material features, not baked data |

Files per set (`Art/Textures/Weapons/IV7/`):

- `T_IV7_<Set>_BaseColor.png`: sRGB.
- `T_IV7_<Set>_Normal.png`: tangent space, **OpenGL (+Y up)**.
- `T_IV7_<Set>_Normal_DX.png`: green channel flipped, for Unreal. **Use this one in Unreal, or
  enable "Flip Green Channel" on the OpenGL map.**
- `T_IV7_<Set>_ORM.png`: linear; R = ambient occlusion, G = roughness, B = metallic. **In Unreal,
  import with sRGB off.**

`Intermediate/T_IV7_<Set>_Masks.png` holds the baked edge, cavity and AO masks. It is a pipeline
intermediate, not for import.

Baking works in two stages (`ivlib.bake_texture_set`):

1. Procedural masks are baked with many samples: edge convexity from a short-range inside-AO,
   cavity, and AO. The magazine is moved away during this bake so it neither receives nor casts
   weapon occlusion. A dropped magazine therefore has clean AO.
2. The materials switch to the baked mask image, and BaseColor, Roughness, Metallic and the
   tangent-space Normal are baked noise-free.

Bake margins are not Blender's. Every pass bakes with margin 0. A numpy dilation then grows the
baked texels 16 px outward, each new texel taking the mean of its filled neighbours, so ownership
is purely by distance. Blender's per-object margin had let one object's margin overwrite another
object's island border. After packing, islands smaller than ~4 texels² or thinner than ~0.8
texel, and zero-area slivers, are collapsed onto a neighbouring face's UV point, so they never
sample foreign texels. Paint and engraving islands are exempt from this.

Meshes are triangulated *before* UV and bake, so the exported mesh and the normal map share the
same MikkTSpace basis.

Texel density at 2048²:

| Surface | Density |
| --- | --- |
| Body exterior | ≈ 26.5 px/cm (object averages including their interiors: lower 26.5, charging handle 26.4, optic 24.0, upper 23.0, handguard 21.9) |
| Body hidden or interior surfaces (receiver bore, handguard inside, barrel under the handguard, gas system, bolt carrier, very small hole walls) | 45–70 % of that, by design (`uv_scale_policy`); the barrel averages 11.9 px/cm |
| Engraved and painted markings (pictograms, roll marks) | 1.6× the exterior density, for legibility |
| Furniture | ≈ 44.5 px/cm |

Exact numbers are in the validation report.

Material identity, as baked values (linear):

| Material | BaseColor | Metallic | Roughness | Notes |
| --- | --- | --- | --- | --- |
| Black hard-anodised aluminium | ≈ 0.02 | 0 | ≈ 0.44 | Patchy wear on the sharpest convex edges goes to bare aluminium: metallic 1, roughness ≈ 0.3 |
| Nitrided steel | ≈ 0.05 | 1 | ≈ 0.36 | |
| Phosphated steel | ≈ 0.07 | ≈ 0.55 | ≈ 0.6 | |
| FDE polymer | ≈ (0.175, 0.125, 0.072) | 0 | ≈ 0.66 | Stippled areas ≈ 0.8 |
| Magazine polymer | ≈ 0.043 | 0 | ≈ 0.6 | |
| Rubber | ≈ 0.017 | 0 | ≈ 0.9 | |
| Brass / copper | – | 1 | ≈ 0.28–0.3 | |
| Glass | – | – | 0.02 | IOR 1.52, 120 nm thin-film coating |
| Reticle | red | – | – | Emissive 150; in Cycles it does not illuminate its surroundings |

## 7. Triangle budget

| Level | Budget | Measured |
| --- | --- | --- |
| LOD0 (incl. optic and magazine) | 30k–70k | **62,628** |
| LOD1 (~50 %) | – | **31,310** (50.0 %) |
| LOD2 (~20 %) | – | **12,504** (20.0 %) |
| SM_IV7_Magazine | – | 5,298 |

Largest LOD0 parts:

| Part | Triangles |
| --- | --- |
| Optic | 8,032 |
| Handguard | 7,398 |
| LowerReceiver | 7,082 |
| UpperReceiver | 6,486 |
| Magazine | 3,954 |
| BufferTube | 2,254 |
| PistolGrip | 2,034 |
| BoltCarrier | 1,940 |
| Stock | 1,930 |
| Barrel | 1,840 |

The full per-part list is in the validation report.

The LODs are collapse-decimated copies with weighted normals re-applied. They keep the same
skeleton, UVs and materials, and are exported as separate files:

- `SK_IV7_Carbine_LOD1.fbx` / `_LOD2.fbx`, to import into LOD slots of the skeletal mesh.
- `IV7_Carbine_LOD1.glb` / `_LOD2.glb`.

The Blender FBX exporter cannot write FBX LOD groups, so the LODs are not embedded.

## 8. Export notes

These are documented choices. The Unreal side is **untested**.

- **FBX (`ivlib.FBX_UNREAL_OPTS`).**
  - Axes and units: `axis_forward='-Z'`, `axis_up='Y'`. The export subprocess scales geometry
    by 100 at scene unit scale 0.01, with `apply_unit_scale=True` and `FBX_SCALE_NONE`. The
    file is therefore in centimetres with no scale on any node: Unreal needs no
    "Convert Scene Unit" and the skeleton root has scale 1.0.
  - Shading and tangents: smoothing groups `FACE`, custom normals written, MikkTSpace tangents,
    meshes pre-triangulated.
  - Bones: no leaf bones, primary/secondary bone axis Y/X (identity correction), all bones
    including non-deforming sockets kept. No animation.
  - Textures: referenced with relative paths.
  - Verified by parsing the written file: `GlobalSettings.UnitScaleFactor = 1.0`, no
    `Lcl Scaling` on any node, bone translations in cm (e.g. `socket_muzzle` at
    57.59 / 0 / 9.17). The armature and mesh root nodes carry only the −90° X
    axis-conversion rotation, which Unreal's "Convert Scene" removes.
- **Recommended Unreal import (unverified).**
  - Skeletal Mesh on, Import Normals and Tangents, Convert Scene on, Force Front X Axis off,
    Convert Scene Unit off, uniform scale 1.0.
  - Normal maps: `_Normal_DX`, or flip green. ORM: sRGB off, then wire R to AO, G to Roughness
    and B to Metallic manually (FBX materials only carry BaseColor and Normal).
  - Glass: needs a translucent material. Reticle: an unlit emissive material.
  - Unreal may add the armature object `SK_IV7` as an extra identity root bone above `root`.
    This is harmless, and it carries no scale because of the centimetre bake.
- **GLB.** Metres, Y-up (converted by the exporter). Skins, all bones, tangents, and embedded
  PNGs. The ORM image feeds glTF occlusion plus metallicRoughness, whose channel layout matches.

Re-import checks: both formats are re-imported with Blender's stock importers into an empty
scene. Dimensions, mesh count, 17 bones, materials and image references are compared; results
are in `IV7_validation.json → reimport_checks`. This proves only that the files are internally
consistent. It is **not** an Unreal import test.

## 9. Interpretations and uncertainties

1. **Overall length.** 86 cm with the stock in position 3 is longer than a typical 14.5"
   carbine, which is around 80–84 cm in that position. The target is kept as specified and met
   with a longer stock body (buttstock 15.8 cm plus a 1.8 cm pad).
2. **Sight height.** Absolute co-witness at 7.0 cm over the bore follows the ~7 cm optic-height
   target. The iron sights are therefore taller than typical absolute co-witness sights
   (≈ 6.6 cm). This is deliberate.
3. **Eye point.** `socket_ads` sits 8.0 cm behind the optic's rear lens, which puts the eye only
   ≈ 6.6 cm behind the deployed rear aperture. That is closer than a real cheek weld and is a
   game-camera convention required by the brief. The rear leaf uses a large, thin ghost ring so
   the ADS view stays usable (see `IV7_ads.png`).
4. **Sights deployed.** Both iron sights are modelled deployed, as instructed.
5. **Dust cover.** The bind pose has the dust cover open, hanging at 176°, so the bolt carrier is
   visible through the port. Closing it is a −176° rotation of `dust_cover`.
6. **Selector layout.** The throw is the project's own: SAFE forward, SEMI down, AUTO rear. The
   pictograms are generic: a crossed-out bullet (white), one bullet (red) and three bullets
   (red).
7. **Top cartridge.** The top round is centred between the feed lips for visibility; real
   double-stack magazines offset it to one side. The second round is offset.
8. **Reticle.** A 1.4 mm emissive disc bonded to the inner face of the front lens. It is also
   visible from the front of the optic, which a real closed-emitter sight hides (P2).
9. **Internal mechanism.** Only visible internals are modelled: bolt carrier and bolt head
   through the port, and cartridges through the feed lips. There is no hammer, buffer or spring.
   The gas tube is straight, with no bend at the gas block.
10. **Hidden surfaces.** The receiver bore, handguard interior and barrel under the handguard get
    reduced texel density on purpose.
11. **Roll marks.** The "IV-7" and "5.56 mm" letter shapes are cut from Blender's built-in UI
    font (DejaVu Sans-based, permissive licence). There are no third-party logos.
12. **Unverified in engine.** Nothing here was verified in Unreal: axis mapping, bone
    orientation, the extra root bone, material hookup and LOD import are documented intentions
    only.
