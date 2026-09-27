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

Status: built and validated in Blender (bpy 4.5.14, headless); revised after the first independent
review (fix round 1, see §10). **Not imported into Unreal** (Unreal is unavailable in this
environment), so nothing in this document is an in-engine result.

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
  the bolt carrier visible through it (smooth side with a short band of forward-assist notches
  near the rear of the port, bolt head and extractor at the front), the hinged dust cover hanging
  open below it, a sculpted brass deflector, a forward-assist-style boss, and the T-shaped
  charging handle at the rear. Its left wing carries the latch (a lever in a pocket of the wing,
  pivoting on a vertical roll pin, thumb grooves at the rear, a hook tooth that engages a notch in
  the upper's rear face). The handle's 14 cm shaft runs forward in a channel under the rail.
- **Lower receiver.** A billet-style lower with a magazine well that flares at the mouth
  (6 mm front wall below the pivot-pin lug) and has shallow machined flank panels. The trigger
  guard is integral and open. Takedown pins, bolt catch, selector with pictograms and a fenced
  magazine release (on the right magwell wall, over the magazine catch notch) complete it. The
  lower's rear tang covers the pistol grip's top, so the grip tucks under it.
- **Grip and stock.** A raked, stippled flat-dark-earth (FDE) pistol grip. A skeletal FDE
  carbine stock with a triangular lightening window, a sling slot and a black rubber butt pad,
  riding on a ribbed buffer tube with castle nut and a QD end plate.
- **Magazine.** A curved dark-grey polymer 30-round magazine, textured on its lower flanks, with
  the top cartridges visible between the feed lips.
- **Sights.** A compact enclosed red-dot optic on a riser, plus flip-up front and rear iron
  sights, deployed and absolutely co-witnessed. Both leaves pivot on a pin between two hinge lugs
  and fold rearward.

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
| Gas block | under the handguard | yes, x = 18.6–21.7 cm from the bolt face | Low-profile block; the straight gas tube runs back to x = 3.05 cm, inside the barrel-nut slot (it no longer passes through the barrel extension) |
| Muzzle device length | ~5.5 cm | **5.50 cm** | Three open prong slots, 4.4 mm wide, 120° apart |
| Muzzle device OD | ~2.2 cm | **2.20 cm** | Wrench flats on the sides |
| Handguard length | ~33 cm | **33.00 cm** | Free float; 2 mm gap to the upper receiver |
| Handguard width | ~5 cm | **5.00 cm** | Octagonal section, 3.2 mm wall |
| Top rail width | ~21 mm | **20.5 mm** (max dovetail width, measured over the bevelled tips; 21.2 mm to the sharp profile corners) | Continuous from the upper onto the handguard at the same height. The dovetail tips now carry a real 0.5 mm bevel, which is why the measured width dropped from 21.2 mm |
| Rail cross-slot pitch / width | 10 mm | **10 mm / 5.3 mm**, floor 3.8 mm below the rail top | Design input |
| Rail top above bore | — | **3.00 cm** | |
| Accessory slots | real cut-through | 7 per side, 6 on the bottom, 12 vents | All are real holes; barrel and gas system are visible through them |
| Pistol grip rake | 20–25° | **22°** from vertical | Design input |
| Pistol grip length | ~11 cm | **11.0 cm** along the raked axis | Max width 3.24 cm; stippled (round dimples ≈ 2.6 mm apart) 0.9 cm below the top down to 0.8 cm above the base. The grip top stays inside the lower's bottom face (half width 1.22 cm, rear edge 1.5 mm inside the lower's tang) |
| Trigger reach | ≈ 7.4 cm (typical carbine) | **7.36 cm** | Grip back strap (web of the hand) to the trigger face, measured horizontally 3.5 cm above the grip hold point. The trigger, its pin and the hammer pin sit 1.2 cm further back than in the first build (8.6 cm) |
| Length of pull | – | **34.65 cm** (13.6") | Trigger face to the butt-pad face. See §9.1: this is at or beyond a typical carbine stock's fully extended position |
| Bolt face to butt | – | **45.1 cm** | M4-type carbine at full extension ≈ 42.7 cm (§9.1) |
| Magazine length along the curve | ~19 cm | **19.0 cm** | Centreline from feed-lip top to baseplate bottom |
| Magazine width | ~2.4 cm | **2.40 cm** | Baseplate 2.76 cm |
| Magazine depth (front–back) | ~6.5 cm | **6.50 cm** | |
| Magazine well | – | outside **7.5 cm** front–back (8.0 cm at the flared mouth); front wall **6 mm** below the pivot-pin lug (was 14 mm); rear wall 3 mm | Magazine clearance 0.5 mm; flared mouth kept (design inputs) |
| Charging handle | real AR-type length | **14.1 cm** long (T-handle 1.9 cm + 12.2 cm shaft), latch lever on the left wing | Shaft 8.8 × 4.8 mm in a 9.2 × 5.2 mm channel under the rail (0.2 mm sliding clearance). Latch: lever 1.6 × 1.7 cm in a 1.4 mm deep wing pocket (0.3 mm gap, raised 0.6 mm), Ø 1.4 mm roll pin, hook tooth 2.0 × 2.8 mm in a notch of the upper (0.4 mm clearance) |
| Charging-handle stroke | ≈ 6.5–7 cm | **7.0 cm** | Checked automatically at every 0.5 cm (`IV7_validation.json → pose_checks.charging_handle_stroke`): no penetration, the shaft stays in the channel (≥ **5.2 cm** engaged at full stroke, 0.2 mm from the channel walls = guided, never floating), the body clears the castle nut by 0.2 mm, the buffer tower and end plate by 0.9 mm |
| Optic axis above bore | ~7 cm | **7.00 cm** | |
| Iron sight line above bore | co-witnessed | front post tip **7.00 cm**, rear aperture centre **6.99 cm** | Absolute co-witness: optic axis, rear aperture and front post tip on one line parallel to the bore |
| socket_ads behind the optic's rear lens | 5–8 cm | **8.00 cm** | |
| Height with magazine, incl. optic | — | **30.9 cm** | Top of elevation turret to baseplate corner |
| Height with magazine, without optic | — | **28.9 cm** | Iron sights deployed |
| Max width | — | **5.43 cm** | End-plate sling ear (left) to optic windage turret (right) |

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
| BufferTube (hollow front: the bolt carrier recoils into it) | black anodised aluminium | Body | root | – |
| EndPlate (QD sling ear, flat top level with the buffer tower) / CastleNut (OD 3.24 cm) | phosphated steel | Body | root | – |
| ForwardAssist (plunger; its pawl face follows the carrier with 0.2 mm clearance) | phosphated steel | Body | root | – |
| Pins (front/rear takedown, trigger, hammer) | phosphated steel | Body | root | – |
| DustCoverRod | nitrided steel | Body | root | – |
| RearSightBase / FrontSightBase (+ cross bolts) | black anodised aluminium / steel | Body | root | – |
| Optic (housing 48 segments round, riser mount, turrets and brightness knob with V-groove knurling, clamp knob) + OpticBolt | black anodised aluminium / steel | Body | root | – |
| OpticLensFront / OpticLensRear | thin coated alpha glass (no transmission / refraction) | – (constant `M_IV7_Glass`) | root | – |
| OpticReticle | 0.3 mm emissive red dot on the inner face of the front lens; its muzzle-side cap and rim are black (`M_IV7_ReticleMask`), so the dot cannot be seen from the front | – (constants `M_IV7_Reticle`, `M_IV7_ReticleMask`) | root | – |
| PistolGrip | FDE polymer, stippled | Furniture | root | – |
| Stock | FDE polymer | Furniture | root | (slides later) |
| ButtPad | black rubber | Furniture | root | – |
| **Magazine** (with the catch notch on the left flank) | dark-grey polymer (matte), textured lower flanks | Furniture | magazine | yes |
| **MagRounds** (two visible cartridges) | brass case, copper jacket | Furniture | magazine | yes |
| **ChargingHandle** (T-handle with latch lever, roll pin and hook tooth + 12 cm shaft) | black anodised aluminium | Body | charging_handle | yes |
| **BoltCarrier** (smooth flat, 9 forward-assist notches near the rear of the port, bolt head and extractor) | nitrided steel | Body | bolt_carrier | yes |
| **DustCover** | nitrided steel | Body | dust_cover | yes |
| **Trigger** | nitrided steel | Body | trigger | yes |
| **Selector** (with white index line) | phosphated steel | Body | selector | yes |
| **BoltCatch** | phosphated steel | Body | bolt_catch | yes |
| **MagRelease** (button on the right magwell wall, on the catch axis) | phosphated steel | Body | mag_release | yes |
| **RearSightLeaf** (ghost-ring aperture on the centre post, ears, knuckle bored for the hinge pin) | black anodised aluminium | Body | rear_sight | yes |
| **FrontSightLeaf** (post, ears, knuckle bored for the hinge pin) | black anodised aluminium | Body | front_sight | yes |

Separate `SM_IV7_Magazine` (collection `IV7_Static`) is the magazine body plus rounds joined
into one static mesh, built from copies of the LOD0 meshes: same topology, UVs and baked custom
normals, no vertex groups and no deform weights. It uses the same Furniture texture set, has its
pivot at the magazine catch (same point as the `magazine` bone), and sits at the world origin.

Every part except `Pins` (4), `HandguardScrews` (2), `MagRounds` (2) and `SM_IV7_Magazine` (3)
is one connected shell; the validation report fails otherwise.

**Single mesh or multiple meshes?** The source keeps one object per part: readable, per-part
validation, and easy editing. Each object carries exactly one vertex group at weight 1.0.
Unreal's FBX importer merges all skinned meshes under one armature into a single skeletal mesh
with one section per material, so the in-engine result is effectively one mesh with 5 material
slots (Body, Furniture, Glass, Reticle, ReticleMask; the last is 12 triangles) and no draw-call
penalty for the split.

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
| magazine | 10.386, 0, 4.912 | on the magazine-catch axis (the `mag_release` button axis) at the magazine centreline; the catch notch on the magazine's left flank sits on this axis | translate −Z to drop; small rotation about Y to rock out |
| charging_handle | 1.236, 0, 11.122 | centre of the T-handle | translate −X, **7.0 cm** stroke (5.2 cm of shaft stays in the receiver) |
| bolt_carrier | 8.686, 0, 9.172 | on the bore axis, carrier centre | translate −X (≈ 7.5 cm stroke) |
| dust_cover | 11.536, −1.80, 7.822 | hinge-rod axis (parallel to X) | rotate about X: bind pose = **open (176°)**; −176° closes it |
| trigger | 5.486, 0, 5.072 | trigger pin | rotate about Y, about +12° when pulled |
| selector | 4.086, 0, 5.872 | selector axis | rotate about Y: 0° SAFE (lever forward, bind pose), +90° SEMI (lever down), +180° AUTO (lever back) |
| bolt_catch | 7.186, 1.3, 6.722 | roll pin | rotate about Y (±9°) |
| mag_release | 10.386, −1.65, 4.912 | button axis (right magwell wall, over the rear of the magazine) | translate +Y (press, ≈ 1.5 mm; the button stays 1 mm clear of the magazine) |
| rear_sight | 8.386, 0, 13.692 | leaf hinge (pin between two base lugs) | rotate about the bone's local Y: bind pose deployed; **−90° folds rearward**. Invariant: the leaf top moves towards the stock (−X). +90° (the r1 review's sign) drives the leaf 6 mm into the optic riser |
| front_sight | 50.086, 0, 13.692 | leaf hinge (pin between two base lugs) | rotate about the bone's local Y: bind pose deployed; **−90° folds rearward** (same invariant) |
| socket_muzzle | 57.586, 0, 9.172 | bore axis at the muzzle face | non-deforming |
| socket_ads | 1.786, 0, 16.172 | eye point on the optic axis, 8.0 cm behind the rear lens | non-deforming |
| socket_support_hand | 33.686, 0, 6.472 | handguard bottom, 17 cm ahead of the bolt face | non-deforming |
| socket_firing_hand | 0, 0, 0 | grip hold point | non-deforming |
| socket_eject | 11.536, −1.5, 9.172 | centre of the ejection port, on the receiver's right face | non-deforming |
| socket_mag | 12.536, 0, 0.372 | centre of the magwell mouth | non-deforming |

The rig is checked on every build by `pose_checks()` in the generator; the results are in
`Art/Previews/IV7/IV7_validation.json → pose_checks` and every failure is a validation problem.
Method: the posed (evaluated) meshes, BVH triangle-pair overlap, then the penetration depth (the
largest distance to the other surface of any vertex that lies inside the other closed mesh, ray
parity in two directions). A contact of ≤ 0.1 mm is a seating face (coplanar or a few µm), not a
failure.

| Check | Result |
| --- | --- |
| Bind pose, all part pairs | {{BIND_RESULT}} |
| Documented poses: dust cover closed / half, carrier 3 and 7.5 cm, trigger +12°, selector SEMI / AUTO, bolt catch ±9°, magazine release pressed 1.5 mm, magazine dropping 1 cm and 7 cm rocked −6°, both sights at −30 / −60 / −90°, the combined rig test pose | {{POSE_RESULT}} |
| Charging handle every 0.5 cm of its 7 cm stroke | {{CH_RESULT}} |
| Every optic of `Shared/config/optics.json` mounted on the rail (its LOD0 GLB at `mount_on_iv7.socket_rail_rifle_m`), irons folded −90 / −90, charging handle at full stroke | {{OPTICS_RESULT}} |
| Folded leaves (−90°) | {{FOLD_RESULT}} |
| Negative control: rear leaf folded the wrong way (+90°) | {{NEG_RESULT}} (the check must catch it, and does) |

`Art/Previews/IV7/IV7_rig_pose_test.png` shows every moving bone posed (dust cover closed, carrier
7.5 cm and charging handle 7 cm back, trigger pressed, selector on SEMI, bolt catch up, magazine
release pressed, magazine dropping, both sights folded rearward); `IV7_charging_handle.png` and
`IV7_sights_folded.png` show the handle home / pulled and the folded leaves.

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

1. Procedural masks are baked with many samples: edge convexity from an inside-AO over
   **2.2 mm** (Body; 1.6 mm Furniture), cavity (6 mm) and AO (3 cm). **Moving parts are baked
   apart from the weapon**: the magazine with its rounds, the dust cover, charging handle, bolt
   carrier, selector, bolt catch, trigger, magazine release and both sight leaves are each moved
   away during this bake, so they neither receive nor cast inter-part AO or cavity dirt. No pose
   shows an occlusion ghost (closed dust cover, selector on AUTO, folded sights, dropped
   magazine).
2. The materials switch to the baked mask image, and BaseColor, Roughness, Metallic and the
   tangent-space Normal are baked (8 samples per texel).

Edge wear and handling polish are driven by the edge mask and by a per-vertex **contact**
attribute (`iv_contact`, written by `assign_contact()` from bore-frame zones: support-hand area
of the handguard, magwell flare, trigger guard, rail teeth, charging-handle T-bar, controls,
turret caps, end plate, buffer tube underside). The attribute is generator-only: it is removed
after the bake together with every procedural material, node group and generated image
(recursive orphan purge), so the saved `.blend` and the exports contain no procedural data.

Bake margins are not Blender's. Every pass bakes with margin 0. A numpy dilation then grows the
baked texels 16 px outward, each new texel taking the mean of its filled neighbours, so ownership
is purely by distance.

UV layout (`ivlib.uv_unwrap`): smart projection (62°), average island scale, a per-island
texture budget (`uv_scale_policy`), flat face groups re-projected as single planar islands and
the selector barrel unwrapped as one cylindrical strip (`uv_planar_policy`; smart projection had
split the hub disc into stretched wedges), then packing (concave shapes, any rotation, 3 px
margin at 2048). Islands that would own fewer than 12 pixel centres are enlarged (up to 6×)
and everything is re-packed twice; islands that still own no pixel centre are nudged by a
fraction of a pixel onto free texels. Only faces smaller than **0.05 mm²** are collapsed onto a
neighbouring UV point (they are below half a texel); visible faces, glyph counters and every
island that touches paint or engraving are never collapsed. After packing, a pixel-centre
rasterisation per island checks that **no pixel is shared by two different islands**; if one
is, the set is re-packed with a safer shape method. The validation report repeats this check
(it fails on any shared pixel) and fails on any zero-UV face larger than 0.05 mm², also on the
LODs (decimated triangles whose UVs collapsed get the affine UV mapping of a neighbour).

Meshes are triangulated *before* UV and bake, so the exported mesh and the normal map share the
same MikkTSpace basis.

Texel density at 2048² (object averages from the validation report; exterior surfaces are
somewhat higher, interior/hidden surfaces lower by design):

| Surface | Density |
| --- | --- |
| Body, receivers and controls | {{BODY_DENS}} |
| Body hidden or interior surfaces (receiver bore, handguard and buffer-tube insides, barrel under the handguard, gas system, bolt carrier) | 35–70 % of the exterior density, by design (`uv_scale_policy`) |
| Engraved and painted markings (pictograms, roll marks) | 1.6× the exterior density, for legibility |
| Furniture | {{FURN_DENS}} |

UV coverage of the 2048² sheets: Body **{{BODY_COV}}** (was 41 %), Furniture **{{FURN_COV}}**. The
Body sheet stays below the 65–70 % a hand-packed sheet reaches because the bevelled hard-surface
parts break into ≈ 2 000 smart-projection islands, each with a 3 px margin (§10, MAT-6).

Material identity, as baked values (linear):

| Material | BaseColor | Metallic | Roughness | Notes |
| --- | --- | --- | --- | --- |
| Black hard-anodised aluminium | ≈ (0.040, 0.041, 0.047): dark, slightly cool (B/R ≈ 1.15), so the specular reflection is faintly coloured | **1** | ≈ 0.29–0.32 on the flats (measured {{ANOD_ROUGH}}), low-frequency breakup ±0.05 plus machining streaks (1.6 mm pitch, ±0.02), ≈ 0.05 lower on bevel highlights and where handled | Metal-like satin: sharper, structured highlights. Wear-through to bare aluminium (base ≈ 0.6, roughness ≈ 0.27) only where an edge is convex AND exposed (baked AO) and weighted by the contact attribute, broken into chips (not a line along every bevel): {{ANOD_WEAR}} of the exterior anodised texels. Micro normal: orange-peel + tool-path lines (mean tilt {{ANOD_TILT}}). Light dust in cavities (≈ 0.08 linear, rough ≈ 0.6); heavy grime in closed cavities is a dielectric layer |
| Nitrided steel | ≈ 0.05 | **1** | ≈ 0.37 | Carbon fouling at the muzzle and heavy cavity grime are dielectric layers with a narrow transition (metallic stays binary) |
| Phosphated steel | ≈ 0.06 | **1** ({{PHOS_METAL}} of the texels > 0.9) | ≈ 0.6 | |
| FDE polymer | ≈ (0.175, 0.125, 0.072) | 0 | ≈ 0.66 | Stippled areas ≈ 0.8 |
| Magazine polymer | ≈ (0.066, 0.063, 0.057): slightly lighter and warm | 0 | **≈ 0.80** (matte, diffuse), ≈ 0.9 on the stippled lower flanks | Reads clearly apart from the cool, reflective satin metal receivers in sun and in shade (`IV7_sun_vs_shade.png`) |
| Rubber | ≈ 0.017 | 0 | ≈ 0.9 | |
| Brass / copper | – | 1 | ≈ 0.28–0.3 | |
| Glass | (0.024, 0.030, 0.036) tint | 0 | 0.03 | Thin coated **alpha** glass like the optics set (`ivoptics.mat_glass_thin`): alpha 0.05 per surface (each lens is a closed disc, 4 surfaces in view), blended, double sided, specular 0.7 with a cool coating tint. **No transmission, no refraction** (checked: `IV7_validation.json → glass_audit`; the GLB carries no `KHR_materials_transmission`) |
| Reticle | saturated red (1, 0.02, 0.01) | – | – | Emission **8** (was 150, which clipped to pink-white); 0.3 mm dot; in Cycles it does not illuminate its surroundings |
| Reticle mask | 0.01 | 0 | 0.5 | Black back of the reticle dot |

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
- `GLB/IV7/IV7_Carbine_LOD1.gltf` / `_LOD2.gltf` (shared-texture glTF set, §8).

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
  - Textures: the FBX materials reference **`T_IV7_*_Normal_DX.png`** (Unreal's normal
    convention) and BaseColor, with **relative paths only** (`../../Textures/Weapons/IV7/…` in
    both `FileName` and `RelativeFilename`); `use_metadata=False`, so no absolute path of the
    source `.blend` is embedded either. Checked by scanning the written files: 0 occurrences of
    `/home/`.
  - Verified by parsing the written file: `GlobalSettings.UnitScaleFactor = 1.0`, no
    `Lcl Scaling` on any node, bone translations in cm (e.g. `socket_muzzle` at
    57.59 / 0 / 9.17). The armature and mesh root nodes carry only the −90° X
    axis-conversion rotation, which Unreal's "Convert Scene" removes.
- **Recommended Unreal import (unverified).**
  - Skeletal Mesh on, Import Normals and Tangents, Convert Scene on, Force Front X Axis off,
    Convert Scene Unit off, uniform scale 1.0.
  - Normal maps: the FBX already points at `_Normal_DX`. ORM: sRGB off, then wire R to AO, G to
    Roughness and B to Metallic manually (FBX materials only carry BaseColor and Normal).
  - Glass: needs a translucent material. Reticle: an unlit emissive material, one-sided (default);
    ReticleMask: plain black opaque.
  - Unreal may add the armature object `SK_IV7` as an extra identity root bone above `root`.
    This is harmless, and it carries no scale because of the centimetre bake.
- **glTF / GLB.** Metres, Y-up (converted by the exporter). Skins, all bones, tangents. The ORM
  image feeds glTF occlusion plus metallicRoughness, whose channel layout matches.
  - `GLB/IV7_Carbine.glb`: LOD0 as one self-contained file with embedded PNGs. The browser build
    loads exactly this file (`Web/src/data/weapons.json`).
  - `GLB/IV7/`: the complete set as separate glTF files, `IV7_Carbine.gltf`,
    `IV7_Carbine_LOD1.gltf`, `IV7_Carbine_LOD2.gltf`, `IV7_Magazine.gltf` (+ `.bin`), which all
    reference **one** shared copy of the six PNGs in `GLB/IV7/textures/`. The earlier per-LOD
    GLBs each embedded the same 12 MB of textures and are no longer written.

Re-import checks: both formats are re-imported with Blender's stock importers into an empty
scene. Dimensions, mesh count, 17 bones, materials and image references are compared; results
are in `IV7_validation.json → reimport_checks`. This proves only that the files are internally
consistent. It is **not** an Unreal import test.

## 9. Interpretations and uncertainties

1. **Overall length and length of pull.** 86 cm with the stock in position 3 is longer than a
   typical 14.5" carbine, which is around 80–84 cm in that position. The target is kept as
   specified and met with a longer stock body (buttstock 15.8 cm plus a 1.8 cm pad). The result:
   **length of pull 34.65 cm (13.6")** and **bolt face to butt 45.1 cm**, against ≈ 42.7 cm for
   an M4-type carbine at full extension, so "position 3" here corresponds to *at or beyond* a real
   carbine stock's fully extended position. Animation and third-person shouldering must use
   these numbers. An OAL of ≈ 83 cm at position 3 would give a typical LOP; that needs the brief
   owner's decision and was not changed.
2. **Sight height.** Absolute co-witness at 7.0 cm over the bore follows the ~7 cm optic-height
   target. The iron sights are therefore taller than typical absolute co-witness sights
   (≈ 6.6 cm). This is deliberate.
3. **Eye point.** `socket_ads` sits 8.0 cm behind the optic's rear lens, which puts the eye only
   ≈ 6.6 cm behind the deployed rear aperture. That is closer than a real cheek weld and is a
   game-camera convention required by the brief. The rear leaf uses a large, thin ghost ring so
   the ADS view stays usable (see `IV7_ads.png`).
4. **Sights deployed; folding.** Both iron sights are modelled deployed, as instructed. Both
   fold **rearward** (−90° about bone Y); a forward fold of the rear leaf would pass through the
   optic riser. Each leaf's knuckle turns on a pin between two lugs of its base; the tower tops
   sit 0.9 mm below a folded leaf.
5. **Dust cover.** The bind pose has the dust cover open, hanging at 176°, so the bolt carrier is
   visible through the port. Closing it is a −176° rotation of `dust_cover`.
6. **Selector layout.** The throw is the project's own: SAFE forward, SEMI down, AUTO rear. The
   pictograms are generic: a crossed-out bullet (white bullet with a diagonal unpainted gap, and a
   thinner white slash running past the outline), one bullet (red) and three bullets (red).
7. **Top cartridge.** The top round is centred between the feed lips for visibility; real
   double-stack magazines offset it to one side. The second round is offset.
8. **Reticle.** A 0.3 mm emissive dot (≈ 7 MOA at the 14 cm eye distance; real dots are 2–4 MOA,
   which would be sub-pixel in a render) bonded to the inner face of the front lens. Its
   muzzle-side cap is black, so it cannot be seen from the front. In an engine a collimated
   (far-plane) reticle shader is the better solution.
9. **Trigger reach.** 7.36 cm from the grip back strap to the trigger face, typical for a
   carbine. The FP arms rig can use a standard trigger-finger pose.
10. **Internal mechanism.** Only visible internals are modelled: bolt carrier and bolt head
    through the port, cartridges through the feed lips, the charging-handle shaft in its channel
    and the magazine catch notch. There is no hammer, buffer or spring. The gas tube is straight
    and ends in the barrel-nut slot.
11. **Hidden surfaces.** The receiver bore, handguard and buffer-tube interiors and the barrel
    under the handguard get reduced texel density on purpose.
12. **Roll marks.** The "IV-7" and "5.56 mm" letter shapes are cut from Blender's built-in UI
    font (DejaVu Sans-based, permissive licence). There are no third-party logos.
13. **Anodised aluminium as a metal.** The dyed oxide is authored as a dark metal (metallic 1),
    the common game-art convention, so that it reads as metal next to the polymer parts.
14. **Unverified in engine.** Nothing here was verified in Unreal: axis mapping, bone
    orientation, the extra root bone, material hookup and LOD import are documented intentions
    only.

## 10. Fix round 1 (independent review r1)

Reviewer defect IDs and what changed in the source (`iv7_carbine.py`, `ivlib.py`). Evidence is in
`Art/Previews/IV7/fix_r1/` and the regenerated validation report.

{{FIX_TABLE}}
