# IRON VALLEY optics: asset reference and specification

Project: IRON VALLEY (original realistic military FPS prototype).
Assets: five swappable weapon optics for the IV-7 carbine's upper rail: **IV-H1** holographic
sight 1x, **IV-R1** compact red dot 1x, **IV-P2** compact prism 2x, **IV-S3** compact scope 3x,
**IV-S6** scope 6x40. All are original designs. The only markings are the model names ("IV-H1" and
so on); there are no real brand names, logos or replicas.

No reference images exist, so **this document is the reference**. Every number is a design input
to `Art/Source/Blender/weapons/optics.py` (helpers in `Art/Source/Blender/lib/ivoptics.py`, built
on `ivlib.py`) or a value measured from the built meshes. Measurements are regenerated on every
build into `Art/Previews/Optics/optics_validation.json`. The runtime data file is
`Shared/config/optics.json`, written by the same script.

Status: built, baked, exported and validated in Blender (bpy 4.5.14 LTS, headless, Cycles CPU).
**Nothing was imported into Unreal** (Unreal is not available in this environment) and **nothing
has been integrated into the web runtime yet**. The through-sight images are Blender renders that
*emulate* the runtime rules in section 5. They are not in-game screenshots.

---

## 1. Why: playtest problems and the design rules that answer them

| Playtest report | Likely cause in the current IV-7 optic | Rule applied to every optic here |
| --- | --- | --- |
| The whole sight flickers when firing | `M_IV7_Glass` uses physical **transmission** (IOR 1.52, Transmission 1). In three.js that makes a separate, lower-resolution transmission render of the scene, sampled through roughness mips. When the view model kicks, the sample changes from frame to frame. The 0.3 mm emissive reticle disc also sat 0.02 mm from the lens face, which causes depth fighting and sub-pixel aliasing | Every lens and window is **thin coated glass**: one open sheet, alpha-blended dark tint plus a coated specular reflection. **Transmission 0, no refraction, no glass/refraction BSDF** (audited in the .blend and in the exported glTF, section 9). The reticle is a texture on its own sheet, 5 mm or more from any glass surface |
| The zoomed view is very blurry | Magnification came from a blurred, low-resolution transmission copy of the screen | Magnified optics are drawn by a **second camera at the true field of view** into a render target at display resolution (picture-in-picture), or, for the IV-S6, by narrowing the main camera and drawing the **full-screen overlay**. Nothing is magnified by scaling an image up |
| The red dot moves with the player | The dot was geometry 14 cm in front of the eye. Any offset between the camera and the optic axis (sway, bob, the eye not exactly on the socket) makes it drift against the target (parallax) | The reticle is **collimated**: the runtime draws it at infinity along the sight axis (section 5.2). The reticle sheet covers the whole window or ocular, so the dot stays visible and on target for an off-axis eye. The dot moves only when the weapon's axis moves, and that is also where the shot goes (hitscan from the muzzle, D8) |
| "Why iron sights when I have a scope, make a clean holo" | The IV-7 is modelled with its flip-up irons deployed and co-witnessed | Both leaves **fold** when an optic is mounted (section 8). For the magnified optics this is physically required: the deployed rear leaf intersects their eyepieces |
| A close-range sight, two medium (2x-3x) and a 6x long-range scope, swappable | One fixed optic | Five separate static assets on a common rail interface, with sockets and a data file |

Reticles are **high-resolution textures** (2048 px or 4096 px, analytically antialiased vector
drawing, straight alpha with colour bleeding for mip maps, separate emissive and signed-distance
textures). The reticle is never emissive geometry.

## 2. Frames, sockets and the rail interface

### 2.1 Optic frame

| Item | Value |
| --- | --- |
| Units | metres (authored in centimetres, scaled at the end), Z up |
| Axes | weapon convention: **+X muzzle**, **+Z up**, **-Y weapon right**, +Y left |
| Origin | **socket_rail**: on the rail centreline, on the rail top plane, at the **front edge of the (front) rail clamp** |
| Sight axis | parallel to X at Y = 0, Z = sight height above the rail |

### 2.2 Sockets (empties, identity rotation: local X = sight axis forward, Z = up)

| Socket | Where |
| --- | --- |
| `socket_rail` | the origin (rail centreline, clamp front edge, rail top) |
| `socket_sight_axis_rear` | sight axis at the ocular lens (1x: rear lens / rear window) |
| `socket_sight_axis_front` | sight axis at the objective lens (1x: front lens / front window) |
| `socket_eye` | ideal eye point on the sight axis at the design eye relief. For the 1x optics it is the IV-7's current ADS eye (bore x = -14.9 cm) |
| `socket_reticle` | centre of the reticle sheet |

In the FBX files the empties are called `SOCKET_socket_rail` and so on and are parented to the
body mesh. This is Unreal's static-mesh socket convention: the socket name becomes `socket_rail`.
In the GLB files they are plain nodes named `socket_rail` and so on, children of the body node.
The GLB's coordinates are glTF Y-up: (x, y, z)<sub>Blender</sub> becomes (x, z, -y)<sub>glTF</sub>;
`Shared/config/optics.json` lists both.

### 2.3 IV-7 rail interface (read from `IV7_carbine_spec.md` / `iv7_carbine.py`, not modified)

| Item | Value |
| --- | --- |
| Rail | generic 21 mm dovetail (top half width 7.8 mm, flank to 10.6 mm at 2.8 mm below the top, neck 8.0 mm) |
| Rail top above bore | **3.00 cm**, continuous over the upper receiver (bore x -14.5 ... +3.0 cm) and the handguard (+3.2 ... +36.2 cm) |
| Cross slots | 10 mm pitch, 5.3 mm wide, floor 3.8 mm below the top; upper receiver slots at bore x = -13.6 + k cm (k = 0 ... 16) |
| Occupied | rear sight base bore x -9.6 ... -7.3 cm; front sight base +32.2 ... +34.4 cm |
| Bore frame | cm, X = 0 at the bolt face, Z = 0 on the bore. Rifle object frame = bore frame minus the grip hold point (-16.686, 0, -9.172) cm, in metres |

Clamps wrap the dovetail with **0.12 mm** running clearance on the flanks and top (no coincident
faces) and end 2.5 mm above the rail's neck. Each recoil lug (cross bolt, r 1.75 mm in a 1.9 mm
hole) sits in the centre of a cross slot, 0.25 mm above the slot floor. All clamps sit on the
**upper receiver rail**. Nothing bridges the gap to the free-float handguard. The IV-S6's front
ring overhangs the handguard on a cantilever arm, 1.5 cm clear of its rail.

Mounting positions on the IV-7 (measured in the mounted scene; the lug x values are checked
against the slot list):

| Optic | socket_rail on the IV-7 (bore x, cm) | Clamp on the rail (bore x, cm) | Recoil lug slot(s) (bore x, cm) | socket_rail, rifle frame (m, Blender) | socket_eye, bore frame (cm) | socket_eye, rifle frame (m, Blender) |
| --- | --- | --- | --- | --- | --- | --- |
| IV-H1 | +1.7 | -3.3 ... +1.7 | -0.6 | (0.18386, 0, 0.12172) | (-14.90, 0, 7.40) | (0.01786, 0, 0.16572) |
| IV-R1 | -1.8 | -5.9 ... -1.8 (the rifle's optic clamp) | -3.6 | (0.14886, 0, 0.12172) | (-14.90, 0, 7.00) | (0.01786, 0, 0.16172), identical to `socket_ads` |
| IV-P2 | -0.4 | -5.8 ... -0.4 | -3.6 | (0.16286, 0, 0.12172) | (-15.02, 0, 7.10) | (0.01666, 0, 0.16272) |
| IV-S3 | +2.4 | -4.6 ... +2.4 | +1.4, -2.6 | (0.19086, 0, 0.12172) | (-15.80, 0, 7.00) | (0.00886, 0, 0.16172) |
| IV-S6 | +2.4 | -5.1 ... +2.4 | +1.4, -2.6 | (0.19086, 0, 0.12172) | (-16.95, 0, 7.60) | (-0.00264, 0, 0.16772) |

glTF (Y-up) coordinates are (x, z, -y) of the Blender values; `optics.json` lists both.

The eye points are realistic:
- The 1x sights keep the IV-7's current ADS eye.
- The magnified optics put the eye at their design eye relief, 0.1 to 2.05 cm further back. With
  the IV-7's forward "game" cheek weld, a scope needs a cantilever mount to reach it, which is why
  the IV-S6 has one.
- The runtime must use each optic's `socket_eye` (section 5.6).

## 3. The five optics

| | IV-H1 | IV-R1 | IV-P2 | IV-S3 | IV-S6 |
| --- | --- | --- | --- | --- | --- |
| Czech name (`name_cs`) | Holografický zaměřovač IV-H1 | Kolimátor IV-R1 | Hranolový zaměřovač IV-P2 (2×) | Kompaktní puškohled IV-S3 (3×) | Puškohled IV-S6 (6×40) |
| Type, magnification | holographic, 1x | enclosed red dot, 1x | prism, 2x | scope 3x24, 30 mm tube | scope 6x40, 30 mm tube |
| Size L x W x H (cm), H including the clamp below the rail top | 9.80 x 4.62 x 6.69 | 6.90 x 4.82 x 7.39 | 9.25 x 5.41 x 7.22 | 17.00 x 6.14 x 7.76 | 27.00 x 6.80 x 8.95 |
| Top above the rail top (cm) | 6.12 | 6.66 | 6.65 | 7.19 | 8.38 |
| **Sight axis over the rail / over the IV-7 bore (cm)** | **4.40 / 7.40** | **4.00 / 7.00** | **4.10 / 7.10** | **4.00 / 7.00** | **4.60 / 7.60** |
| Eye relief (cm), from the rear window / ocular lens to socket_eye | 8.86 (1x: any) | 8.11 (1x: any) | 7.00 | 8.50 | 9.00 |
| Eyebox radius (mm), `eyebox_radius_m` | 11.7 (window half height) | 12.9 (lens radius) | 5.0 (exit pupil 10 mm) | 4.0 (exit pupil 8 mm) | 3.33 (exit pupil 6.7 mm) |
| Clear aperture, `lens_radius_m` | window 32.4 x 23.4 mm (r 11.7 mm) | r 12.9 mm | ocular r 12.0 mm, objective 20 mm | ocular r 14.2 mm, objective 24 mm | ocular r 18.0 mm, objective 40 mm |
| True / apparent field of view | 1x | 1x | 9.7 / 19.3 deg (17.0 m at 100 m) | 6.3 / 18.8 deg (11.0 m at 100 m) | 3.77 / 22.3 deg (6.6 m at 100 m) |
| Reticle | 65 MOA ring + 1 MOA dot | 2 MOA dot | chevron + BDC 300-600 m | 0.6 mrad dot + 1 mrad hashes | duplex mil-dot + holdover 300-600 m |
| Zero (m) | 50 | 50 | 100 | 100 | 100 |
| ADS time (s), `ads_time_s` | 0.22 | 0.21 | 0.25 | 0.27 | 0.32 |
| Recommended range (m) | 0-150 | 0-150 | 15-400 | 25-450 | 75-600 |
| Mass (kg, estimate) | 0.31 | 0.17 | 0.30 | 0.43 | 0.68 |
| Triangles LOD0 (body + glass + reticle) / LOD1 | 7,344 / 3,654 | 10,814 / 4,604 | 17,028 / 7,710 | 22,174 / 10,283 | 25,792 / 12,094 |
| Body texture set, UV coverage, texel density | 2048², 58 %, 90.7 px/cm | 1024², 46 %, 46.6 px/cm | 1024², 38 %, 35.1 px/cm | 1024², 37 %, 24.2 px/cm | 2048², 50 %, 46.0 px/cm |
| Export: static mesh / file | `SM_IVH1_Holo` / `IVH1_Holo` | `SM_IVR1_RedDot` / `IVR1_RedDot` | `SM_IVP2_Prism` / `IVP2_Prism` | `SM_IVS3_Scope` / `IVS3_Scope` | `SM_IVS6_Scope` / `IVS6_Scope` |

For comparison, the IV-7 body texture density is about 26 px/cm.

Masses are plausible design estimates for handling (`mass_kg` in the data file), not measured.

### IV-H1 holographic sight 1x

- **Body:** a base holding the electronics and laser module, with a rounded nose around a
  transverse CR123-size battery tube. The battery cap is on the left: knurled, with a coin slot.
  A protective **hood** (tunnel) carries a large rounded-rectangle **window**, 32.4 x 23.4 mm
  clear. The rear and front windows are 51.8 mm apart.
- **Controls:** two rubber brightness **buttons** on the left side in a raised guard pad. Recessed,
  slotted windage and elevation adjusters on the right.
- **Mount:** integral 50 mm **rail clamp** with one recoil lug and a **QD throw lever** on the right.
  "IV-H1" is engraved and paint-filled on the hood.
- **Sight axis:** 4.40 cm above the rail (7.40 cm over the bore). With the IV-7 irons (line 4.00 cm
  above the rail) this is the usual lower-1/3 co-witness height of holographic sights.
- **Reticle:** 65 MOA ring + 1 MOA dot, red, on a one-sided sheet between the windows. It is a
  hologram, so it has no ink and is invisible when switched off, and invisible from the front.

### IV-R1 compact red dot 1x

- **Body:** the IV-7's current optic as a stand-alone asset, same housing and same position. That is
  the 6.9 cm, 48-segment superelliptic tube (36 mm across), riser, 4.1 cm clamp, capped turrets
  and brightness knob. socket_rail sits at bore x -1.8 cm, the lug in the slot at -3.6. The axis is
  4.00 cm above the rail (7.00 over the bore, absolute co-witness).
- **Changes from the rifle's optic:**
  - Thin glass sheets instead of glass cylinders.
  - A 2 MOA texture dot on a sheet 5.7 mm behind the front lens. It was a 0.3 mm emissive disc
    0.2 mm from the lens face.
  - A **closed emitter**: an LED housing on the tube floor near the rear lens, a one-sided
    reticle sheet facing the eye, and a red-reflecting front coating. The dot cannot be seen from
    the front (section 9).
- **Eye point:** its `socket_eye` coincides with the IV-7's `socket_ads` (difference 0.000 mm).

### IV-P2 compact prism 2x

- **Body:** a boxy prism housing (32 x 45.5 mm section). A 20 mm objective in a tube with a
  sunshade lip. A 28 mm eyepiece with a knurled diopter ring and a ribbed rubber eyecup.
- **Controls:** capped elevation (top) and windage (right) turrets with white index marks. On the
  left, an illumination rheostat that is also the battery compartment (coin slot).
- **Mount:** integrated rail clamp (54 mm) with a cross bolt and hex nut, and a web under the
  objective tube. "IV-P2 2x" is engraved.
- **Optics:** eye relief 7.0 cm, exit pupil 10 mm, 9.7 deg true field (17.0 m at 100 m).
- **Reticle:** etched chevron (illuminated) with a vertical stadia and BDC holdover bars for
  300 / 400 / 500 / 600 m (100 m zero), each 0.5 m wide at its range, with etched numerals.

### IV-S3 compact scope 3x24

- **Body:** 30 mm tube, 17.0 cm long. Objective bell 36 mm across (24 mm clear aperture). Eyepiece
  38.6 mm across with a knurled fast-focus ring and a ribbed rubber eyecup.
- **Turrets:** a saddle with **capped** elevation and windage turrets (knurled covers) and an
  illumination knob on the left (battery cap, coin slot, position marks).
- **Mount:** one-piece 30 mm mount: two split rings, each with two cap screws, and a short forward
  cantilever. Two recoil lugs with nuts. "IV-S3" is engraved on the mount.
- **Optics:** eye relief 8.5 cm, exit pupil 8 mm, 6.3 deg true field (11.0 m at 100 m).
- **Reticle:** an illuminated 0.6 mrad centre dot floating in a 0.09 mrad etched crosshair. The
  crosshair has 1 mrad hash marks (0.35 mrad long, 0.7 mrad every 5th) out to 10 mrad. Thick
  0.45 mrad posts run from 10 mrad to beyond the field stop.

### IV-S6 scope 6x40

- **Body:** 30 mm tube, 27.0 cm long, 40 mm objective (bell 48.4 mm across). Eyepiece 44 mm across
  with a knurled fast-focus ring and a ribbed rubber eyecup.
- **Turrets:** a saddle with **exposed** knurled elevation and windage turrets, each with 40
  engraved, white-filled marks per turn (long every 5th) and index lines. An **illumination knob**
  on the left: 9 marked positions, battery cap with coin slot.
- **Mount:** a **cantilever mount**. The 7.5 cm clamp sits on the upper receiver rail only (two
  recoil lugs with nuts). The rear ring stands on an upright over the clamp. An arm with a
  lightening slot carries the front ring forward over the handguard.
- **Sight axis:** 4.60 cm above the rail (7.60 over the bore).
- **Optics:** eye relief 9.0 cm, exit pupil 6.7 mm, 3.77 deg true field (6.6 m at 100 m),
  22.3 deg apparent field.
- **Reticle:** a duplex mil-dot. A 0.06 mrad thin wire carries 0.22 mrad dots every mrad out to
  9 mrad left, right and up, and 0.16 mrad marks every mrad out to 11 below. Holdover bars for
  300 / 400 / 500 / 600 m (100 m zero) carry numerals. Thick 0.45 mrad posts run from 10 mrad
  (12 below) to 34 mrad. There is an illuminated 0.24 mrad centre dot.
- **ADS overlay:** plus a **full-screen ADS overlay** (section 5.4).

## 4. Reticles

Files per optic in `Art/Textures/Optics/<ID>/`:

| File | Content |
| --- | --- |
| `T_<ID>_Reticle.png` | sRGB colour + **straight alpha** (coverage of all features). RGB is the illumination colour where the nearest feature is illuminated and black ink where it is etched. Fully transparent texels carry the nearest feature's colour (colour bleeding), so mip maps and bilinear filtering never pull black fringes into a red stroke. The border texels are transparent |
| `T_<ID>_Reticle_Emissive.png` | sRGB, illumination colour x coverage of the illuminated features only. Multiply by the brightness setting |
| `T_<ID>_Reticle_SDF.png` | signed distance in texels, 0.5 = feature edge, spread +-16 texels. R = all features, G = illuminated, B = etched. It lets the runtime keep strokes at least N screen pixels wide and draw crisp edges at any scale |
| `T_<ID>_Reticle.json` | exact angular scale, projection, feature list with sizes, holdover table, encoding, sampling |
| `T_IVS6_ADS_Overlay.png` + `.json` | IV-S6 full-screen overlay (section 5.4) |

- **Drawing.** Every feature is a vector primitive (circle, ring, arc, segment, polygon) given in
  MOA or mrad. It is rasterised with an **exact analytic signed distance** and coverage
  `clamp(0.5 - d_px, 0, 1)`, which is box-filter antialiasing with no supersampled bitmap.
  Numerals are the one exception: they are DejaVu Sans Bold, 4x supersampled, with the distance
  from a Euclidean distance transform.
- **Angular frame.** The texture centre (between the four centre texels) is the point of aim.
  Row 0 is up; u runs to the shooter's right. Angles are **object space**, the angle at the target.
  Behind the eyepiece of a magnified optic they appear x magnification.
- **Projection.** The mapping is gnomonic: pixel offset = px_per_unit x tan(angle) / unit_in_rad.
  Reticle marks are linear at the target, and a rectilinear camera projects the same way.
  px_per_unit is exact at the axis. At the texture edge, a mapping linear in angle would differ by
  less than 0.13 %.
- **Sampling.** The textures are power of two. Generate mips with premultiplied-alpha filtering,
  use trilinear plus anisotropic filtering and **clamp-to-edge** addressing. The glTF samplers are
  CLAMP_TO_EDGE; this is checked.

| Optic | Units | Texture | Field, edge to edge | px per unit | px/MOA | px/mrad | Features (object space) | Illumination |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| IV-H1 | MOA | 2048² | 80 MOA | 25.600 | 25.600 | 88.006 | ring 65 MOA (centreline diameter), 2 MOA stroke; 1 MOA dot | all lit, projected (no ink) |
| IV-R1 | MOA | 2048² | 32 MOA | 64.000 | 64.000 | 220.016 | 2 MOA dot | lit, projected (no ink) |
| IV-P2 | MOA | 2048² | 64 MOA | 32.000 | 32.000 | 110.008 | chevron 6.0 x 3.3 MOA, 0.67 MOA stroke, apex = point of aim; stadia 0.3 MOA; BDC bars 0.45 MOA stroke, 0.5 m wide at range; numerals 1.7 MOA | chevron lit; BDC etched |
| IV-S3 | mrad | 4096² | 120 mrad | 34.133 | 9.929 | 34.133 | dot 0.6 mrad; crosshair 0.09 mrad from 0.9 to 10 mrad; hashes every 1 mrad (0.35 / 0.7 mrad); posts 0.45 mrad, 10-57 mrad | dot lit; rest etched |
| IV-S6 | mrad | 4096² | 72 mrad | 56.889 | 16.548 | 56.889 | dot 0.24 mrad; wire 0.06 mrad; mil dots 0.22 mrad at 1-9 mrad left, right and up; 0.16 mrad marks at 1-11 mrad down; holdover bars 0.06 mrad, 0.5 m wide at range; numerals 0.42 mrad; posts 0.45 mrad from 10 (12 down) to 34 mrad | dot lit; rest etched |

Measured on the rasterised textures (`reticle_metrics`):
- Every probed edge crossing has exactly **1 partially covered texel**: IV-H1 52 crossings,
  IV-P2 16, IV-S3 40, IV-S6 24. The IV-R1 dot's edges fall exactly on texel boundaries on the probe
  lines, so there it is a clean 1-to-0 step.
- Border alpha is **0** in all textures.
- The illuminated-coverage centroid is within 0.0002 px of the texture centre. The IV-P2 chevron's
  centroid lies 1.88 MOA below its apex by design; the apex is the point of aim.

| Range | Drop below the line of sight, IV-P2 / IV-S6 (cm) | IV-P2 BDC hold (MOA) | IV-S6 hold (mrad) | Bar width (IV-P2 MOA / IV-S6 mrad) |
| --- | --- | --- | --- | --- |
| 300 m | 37.8 / 36.8 | 4.33 | 1.226 | 5.73 / 1.667 |
| 400 m | 93.9 / 92.4 | 8.07 | 2.309 | 4.30 / 1.250 |
| 500 m | 186.3 / 184.3 | 12.81 | 3.685 | 3.44 / 1.000 |
| 600 m | 328.9 / 326.4 | 18.84 | 5.440 | 2.86 / 0.833 |

The holdover marks use real 5.56 mm exterior ballistics: a point-mass G7 model with MV 895 m/s,
G7 BC 0.151, sea-level ICAO air, and each optic's own sight height. **The game itself is hitscan
(D8), so there is no bullet drop at runtime yet.** The BDC and holdover marks are correct for the
real load but decorative until ballistics exist.

**On-screen size at true scale.** In the default ADS view (vertical FOV 50.5 x 0.82 = 41.4 deg),
1 MOA is 0.43 px at 1080 lines. The IV-H1 ring is then about 28 px across at 1080p, but its 1 MOA
dot and 2 MOA stroke are sub-pixel. The data file therefore carries `render_hints`: keep the dot at
least 2.5 px and strokes at least 1.25 px by thresholding the SDF lower. The textures themselves
stay at true scale.

## 5. Runtime rendering contract (web and Unreal integration, not implemented here)

### 5.1 Glass

- **three.js:** use `MeshStandardMaterial` or Physical **without transmission**: `transparent: true`,
  `opacity` = the material's alpha (0.08-0.16), `depthWrite: false`, `side: DoubleSide`,
  roughness 0.03, metalness 0, environment reflections on. Draw after the opaque view model and
  before the reticle.
- **Unreal:** Translucent, Surface TranslucencyVolume (or Forward Shading). Opacity = alpha. The
  Refraction input must be left unconnected.
- **Never** use a transmission, refraction or screen-space-refraction pass on optic glass.
- The ocular sheet's UVs map the lens disc to 0..1 (u to the viewer's right), ready for a render
  target.

### 5.2 Collimated reticle (1x optics, and the static reticle sheet of the magnified ones)

Draw the reticle sheet (`<ID>_Reticle`, one-sided, facing the eye, alpha blended, unlit) with a
shader that ignores the sheet's UVs and projects the texture **from infinity along the sight
axis**:

```glsl
// uOpticRot: mat3, inverse rotation of the optic node (world -> optic; glTF optic frame: +X forward, +Y up, +Z right)
// uHalfTan:  0.5 * field_units * unit_in_rad * M   (M = 1 for 1x sights; the apparent factor for a sheet behind an eyepiece)
vec3 v = uOpticRot * (vWorldPos - cameraPosition);     // view ray in the optic frame
if (v.x <= 0.0) discard;
vec2 t  = vec2(v.z, v.y) / v.x;                        // tan(right), tan(up)
vec2 uv = 0.5 + 0.5 * t / uHalfTan;                    // u right, v up
uv.y = 1.0 - uv.y;                                     // glTF textures: row 0 at the top (flipY = false)
vec4 ink = texture(uReticle, uv);                      // clamp-to-edge, transparent border
// RGB is the illumination colour on lit features and black on etched ones, so one multiply
// gives glowing lit strokes (HDR, before tone mapping) and black etched strokes
gl_FragColor = vec4(ink.rgb * uBrightness, ink.a);     // straight alpha, normal blending
```

The emissive texture is for standard material pipelines (the glTF emissive slot). The custom
shader does not need it.

Because the lookup depends only on the ray **direction**, the dot lies on the sight axis for any
eye position (parallax-free). The sheet covers the whole aperture, so an off-axis eye still sees
the dot. Draw it after the glass with depth test on and depth write off.

A runtime without this shader can use the sheet's own UVs as a fallback. They are exact from
`socket_eye` (checked, section 9) but show parallax off-axis.

### 5.3 Magnified optics: picture-in-picture

1. Render the scene with a second camera at the **eye** (the ADS camera position), looking along
   the optic's sight axis. Use a square target with vertical FOV = `true_fov_deg`
   (`runtime_view.pip_camera_vfov_deg_over_ocular_disc`). Render it at the ocular disc's on-screen
   size or larger, never smaller. The IV-S6 disc is about 470 px across at 1600 x 900.
2. Draw the reticle into that target at object-space scale:
   `uv = 0.5 + (p_rt - 0.5) * 2 tan(true_fov/2) / (field_units * unit_in_rad)`, with the centre of
   the target being the sight axis.
3. Apply the eyepiece vignette. There is a soft edge from about 80 % of the disc radius. If the eye
   is off the axis by more than `eyebox_radius_m` (the exit-pupil radius), or its eye relief is
   wrong, fade the image out.
4. Show the result on the ocular glass sheet through its UVs, or as a screen-space disc at the
   ocular's projected position.

`Art/Previews/Optics/<ID>_through_pip.png` and `_through_eyepiece.png` are exactly this
composite, made from Cycles renders.

### 5.4 IV-S6 full-screen ADS overlay

`T_IVS6_ADS_Overlay.png` (4096 x 4096) has the **same px/mrad as the reticle texture**, with the
point of aim at the centre.

- **Inside the eyebox:** fully transparent except for the reticle and a soft darkening towards the
  field stop.
- **The field stop:** a crisp, antialiased circle of radius 32.9 mrad (the 3.77 deg true field).
- **Outside:** opaque black.

Draw it centred with height = screen height, and set the zoomed camera's vertical FOV to
**4.1253 deg** (the overlay's 72 mrad field). At any other scale, the overlay's on-screen height =
screen_px_per_mrad x 72. Fill the rest of the screen with black.

### 5.5 On-screen scale at any FOV

`screen_px_per_texture_px = screen_px_per_rad x unit_in_rad / px_per_unit`, where
`screen_px_per_rad = (H/2) / tan(vfov/2)` of the camera that shows the target: the main camera for
1x sights, the PiP / zoom camera for magnified ones.

### 5.6 Rifle integration

- Hide the IV-7's built-in optic (node regex `^Optic`, already used by the "irons" loadout in
  `Web/src/data/weapons.json`).
- Attach the chosen optic's GLB so that its origin (`socket_rail`) lands on
  `mount_on_iv7.socket_rail_rifle_m`.
- Fold both iron-sight leaves (section 8).
- Use the optic's `socket_eye` as the ADS eye instead of the rifle's `socket_ads`.
- The ADS time comes from the optic (`ads_time_s`).

## 6. Materials, textures and LOD

| Material | What | Maps / values |
| --- | --- | --- |
| `M_<ID>_Body` | every opaque part: anodised housing, mount, knobs, steel screws / lugs / nuts, rubber, white paint fill, black interior | `T_<ID>_Body_BaseColor.png` (sRGB), `_Normal.png` (OpenGL), `_Normal_DX.png` (DirectX, used by the FBX), `_ORM.png` (linear: R = AO, G = roughness, B = metallic) |
| `M_<ID>_Glass_Rear` / `_Front` | thin coated lens / window sheets | constant: dark tint, alpha 0.08-0.16, roughness 0.03, specular level 0.6-1.0 with coating tint, **transmission 0**, double sided, blended |
| `M_<ID>_Reticle` | reticle sheet | `T_<ID>_Reticle.png` (base + alpha), `_Emissive.png`, emission strength 2 (it stays saturated red under AgX), roughness 1, specular 0, **one sided**, blended |

- **Baking.** Baked with `ivlib.bake_texture_set`: masks first, then channels, 16 px distance
  dilation. Each optic is baked **alone**. All optics are authored at the same origin, and a first
  build that baked them together showed grey "grime" blotches wherever another optic's geometry
  occluded the AO or cavity bake.
- **Texture sizes.** IV-H1 and IV-S6 use 2048 x 2048; IV-R1, IV-P2 and IV-S3 use 1024 x 1024.
- **UVs.** Smart projection at 45 deg, or 35 / 28 deg if needed. At the default 62 deg the V-groove
  knurl flutes fold onto their neighbours, sharing texels, which the per-island packing check
  cannot see. Each optic's UVs are unwrapped until no texel is shared by two islands at full
  resolution.
- **LOD1 (third person).**
  - `SM_<ID>_LOD1`: the body collapse-decimated to 50 % with weighted normals re-applied, the same
    UVs and material.
  - `<ID>_Glass_LOD1`: planar-dissolved glass.
  - No reticle sheet.
  - The LOD1 GLB embeds quarter-resolution copies of the body textures (`LOD1/*_LOD1.png`). The
    LOD1 FBX shares the LOD0 material, so it goes into an Unreal LOD slot.

## 7. Exports

| File | Content |
| --- | --- |
| `Art/Export/FBX/SM_<file>.fbx` | LOD0 static mesh: body + glass + reticle sheet + 5 `SOCKET_` empties. Centimetres with no node scale (geometry and locations x100 at unit scale 0.01, the IV-7 convention), `ivlib.FBX_UNREAL_OPTS` axes, relative texture paths, DX normal map |
| `Art/Export/FBX/SM_<file>_LOD1.fbx` | LOD1 body + glass |
| `Art/Export/GLB/<file>.glb` | LOD0 with embedded textures and socket nodes, metres, Y-up |
| `Art/Export/GLB/<file>_LOD1.glb` | LOD1 with quarter-resolution textures |

`<file>` is `IVH1_Holo`, `IVR1_RedDot`, `IVP2_Prism`, `IVS3_Scope` or `IVS6_Scope`. Every file is
re-imported with Blender's stock importers and compared (section 9). **That proves only that the
files are internally consistent. It is not an Unreal import test.**

Recommended Unreal import (unverified): Static Mesh, Combine Meshes on, Import Normals and
Tangents, Convert Scene on, Convert Scene Unit off, scale 1.0.
- **Glass:** translucent material (5.1).
- **Reticle:** translucent unlit material with the 5.2 shader, one-sided.
- **ORM:** sRGB off.

## 8. Iron sights when an optic is mounted (documented, not implemented)

The IV-7 rig: bones `rear_sight` (hinge at bore (-8.3, 0, 4.52) cm) and `front_sight` (hinge at
(33.4, 0, 4.52) cm). They are world aligned, with bone-local X = forward, Y = weapon left,
Z = up. The bind pose is deployed.

| When | rear_sight | front_sight |
| --- | --- | --- |
| IV-R1 (absolute co-witness) or IV-H1 (lower 1/3) | may stay deployed (co-witness), or fold | may stay deployed, or fold |
| IV-P2, IV-S3, IV-S6 | **must fold**: the deployed leaf intersects the eyepiece | **fold**: the post would sit in the magnified view |
| Default for any optic (the playtest request) | fold | fold |

- **Fold.** Rotate each bone **-90 deg about its local Y axis** (Euler XYZ, `rotation_euler.y = -pi/2`
  in Blender). The invariant: **the leaf's top must move towards the stock (-X)**. Folded, the
  rear leaf lies flat from x -8.3 back to -11.4 cm at z 4.37-4.67 cm over the bore, 0.9 mm above
  its tower.
- **glTF / three.js.** The exported root bone carries the Z-up to Y-up conversion. The sight bones
  keep their Blender-local axes (glTF node rotation identity under `root`), so the same
  `bone.rotation.y = -Math.PI / 2` folds them rearward.
- **Unreal.** The bone-local axes after the FBX axis conversion are unverified. Check the
  invariant: the leaf top moves towards -X, the stock.

**Known issue (the IV-7's open review item "rear sight folds into the riser").**
- **The sign is the trap.** The r1 review's pose test used **+90 deg**. That folds the leaf
  **forward**, to x -8.4 ... -5.2 cm, and drives it into the IV-7's optic riser. Measured here:
  about 6 mm past the riser's rear face; the review estimated about 2 cm.
- **With the new optics.** +90 deg still collides with IV-H1, IV-R1 and IV-P2 (table below).
- **The required fix.** The rifle's documentation, pose test and any runtime code must use -90 deg
  (top towards the stock) and state the invariant, not a bare "rotate about Y" instruction.
  This is to be done in the rifle's fix pass; `iv7_carbine.py` was not edited.

Measured with each optic mounted: posed rifle, BVH triangle intersections and nearest distances.

| Optic | Documented fold (-90 / -90 deg) | Irons deployed | Rear leaf +90 deg (the r1 review's sign) |
| --- | --- | --- | --- |
| IV-H1 | no contact; leaf 22.2 mm, base 10.1 mm away | no contact (lower-1/3 co-witness possible) | **leaf intersects the IV-H1 body** |
| IV-R1 | no contact; leaf 11.4 mm, base 10.1 mm | no contact (absolute co-witness) | **leaf intersects the riser / clamp** |
| IV-P2 | no contact; leaf 8.0 mm, base 8.1 mm | **leaf intersects the eyepiece** | **intersects** |
| IV-S3 | no contact; leaf 3.5 mm, base 3.4 mm under the eyepiece | **leaf intersects the eyepiece** | no contact (still the wrong direction) |
| IV-S6 | no contact; leaf 7.6 mm, base 7.0 mm under the eyepiece | **leaf intersects the eyepiece** | no contact (still the wrong direction) |

Rear leaf bounding box, bore frame (cm):

| Pose | x | z |
| --- | --- | --- |
| Deployed | -8.45 ... -8.15 | 4.39 ... 7.62 |
| Folded -90 deg | -11.40 ... -8.17 | 4.37 ... 4.67 |
| +90 deg | -8.43 ... -5.20 | 4.37 ... 4.67 |

## 9. Validation (adversarial self-review)

| Check | Method | Result |
| --- | --- | --- |
| Mounting flush: no floating, no intersection | Each optic is placed on the posed IV-7 (irons folded). BVH triangle-pair overlap and vertex-to-surface distance are measured against every IV-7 part within 3 cm | **0 intersecting pairs** with every part, all five optics. Closest part is the rail (UpperReceiver) at **0.08 mm** everywhere: the modelled 0.12 mm running clearance, measured vertex-to-surface. Nothing else closer than 3.4 mm |
| Recoil lugs in slots | Lug x checked against the IV-7 slot list | all on slot centres (bore x -0.6 / -3.6 / -3.6 / +1.4 and -2.6 / +1.4 and -2.6) |
| Sight axis parallel to the bore (limit 0.05 deg) | Angle of `socket_sight_axis_front - socket_sight_axis_rear` to the bore (+X), mounted | **0.000000 deg** for all five. Reticle sheet normal vs axis: 0.000000 deg |
| Sight height | `socket_eye` z minus the bore z, mounted | 7.4000 / 7.0000 / 7.1000 / 7.0000 / 7.6000 cm (design values) |
| No transmission / refraction | Every material in the .blend: Principled Transmission Weight value and links, no Glass / Refraction / Translucent BSDF. Exported GLB material JSON | **0 problems.** GLB `extensionsUsed` = emissive_strength, specular, ior only (no KHR_materials_transmission / volume / dispersion). Re-imported FBX and GLB: transmission 0 |
| Reticle crispness | analytic AA; partial texels per edge crossing; border alpha; texture size | 1 texel per crossing; border alpha 0; 2048² (H1, R1, P2) and 4096² (S3, S6) |
| Reticle angular scale, static sheet | Linear fit of the reticle sheet's UVs vs position, seen from `socket_eye` | texture units per radian = expected (×magnification) with **0.0000 % error** for all five. Axis at UV (0.5, 0.5); u to the shooter's right, v up |
| Reticle through the real mesh (1x) | Cycles render from `socket_eye` through the thin glass, IV-H1 at 4.5 deg vertical FOV (3.33 px/MOA), circle fit to the red pixels | ring radius **108.16 px vs 108.28 expected (-0.11 %)**, centre offset **(0.007, 0.080) px**. Game FOV (0.35 px/MOA): ring 10.9 px radius vs 11.25 (a one-pixel ring, partially detected). IV-R1 dot centre offset (-0.06, 0.10) px |
| Magnified centring (PiP emulation) | illuminated-feature centroid in the 4x centre panel vs the texture's own | IV-P2 0.18 MOA (1.0 px: the chevron's thin arms are partly below the detection threshold), IV-S3 0.025 mrad (0.7 px), IV-S6 0.000 |
| Emitter hidden from the front (IV-R1, IV-H1) | (1) Reticle faces facing a camera in front of the optic. (2) Renders with and without the reticle sheet. (3) Emission forced to green ×100: front view and an eye-side control | (1) **0 of 144 / 0 of 28.** (2) no red pixels; max difference 18/255 and 20/255 in 125 / 59 px, which is sampling noise from the extra transparent surface. (3) **front 0 green pixels** for both; control from the eye 2 px (R1: a 2 MOA dot at 6 deg FOV, 450 px) and 221 px (H1) |
| IV-S6 overlay transparency | alpha probes | 0 at empty interior points ((±2.5, 2.5) mrad); at most 0.074 within 0.8 R (eyepiece fall-off); mean 0.87 on the field stop; **min 1.000 outside**. 4096², 56.89 px/mrad (the same as the reticle), eyebox radius 1871.6 px (0.457 of the size) |
| Re-imports (Blender stock importers) | FBX + GLB, LOD0 + LOD1, all five (20 files). Triangles, bounding box, the 5 sockets (position and +X axis), images, glTF alpha mode / sidedness / samplers | **20 / 20 files, 0 problems.** Triangles equal, bounding boxes equal to 1e-4 m, sockets within 2e-5 m. Glass BLEND double-sided; reticle BLEND single-sided CLAMP_TO_EDGE |
| Mesh validation (`ivlib.validate`) | LOD0: closed 2-manifold, zero-area faces, opposing normals, UV bounds, zero-UV faces < 0.05 mm², texels shared by different islands at full resolution | **LOD0: 0 problems, all five.** LOD1: 0 problems except one IV-H1 LOD1 triangle (below) |
| Glass and reticle sheets | open edges on the boundary only, zero-area faces, facing | 0 problems. Rear sheets face -X, front sheets +X, reticle -X |

### Evidence (all in `Art/Previews/Optics/`, Blender Cycles renders, at most 1600 x 900)

| File | Shows |
| --- | --- |
| `<ID>_mounted_side.png`, `<ID>_mounted_34.png` | each optic on the IV-7 (irons folded -90 deg): right side (orthographic) and 3/4 rear-left |
| `IVH1_through_game_fov.png`, `IVR1_through_game_fov.png` | view from `socket_eye` at the game ADS FOV (41.4 deg vertical) through the thin glass on the outdoor test range |
| `IVH1_through_zoom.png`, `IVR1_through_zoom.png` | the same eye point at 4.5 deg vertical FOV: ring / dot crisp and centred on the 100 m board (blue ticks mark the image centre) |
| `IVP2/IVS3/IVS6_through_pip.png` | eye view at the game ADS FOV with the eyepiece filled by the runtime PiP emulation (zoomed render + reticle at its angular scale + eyebox vignette) |
| `IVP2/IVS3/IVS6_through_eyepiece.png` | the eyepiece large, plus the field centre 4x enlarged (reticle crispness and centring) |
| `IVP2/IVS3/IVS6_through_game_fov.png` | raw mesh view from the eye (static reticle sheet fallback, no PiP) |
| `IVS6_ads_overlay_fullscreen.png` | `T_IVS6_ADS_Overlay.png` over a zoomed render at 4.1253 deg vertical FOV |
| `IVH1_front_emitter_check.png`, `IVR1_front_emitter_check.png` | the optics seen from the front: no reticle visible |
| `optics_lineup.png`, `optics_lineup_LOD1.png` | all five optics, LOD0 and LOD1 |
| `reticles/<ID>_reticle.png` | each reticle texture over a sky gradient, with a scale bar |
| `optics_validation.json`, `<ID>_mesh_validation*.json` | every number in this document |
| `*_zoomsrc*.png` | the zoomed source renders used by the composites |

## 10. Known issues and limits

1. **Not integrated and not tested in any engine.** The web runtime and Unreal are untouched.
   - Not implemented: the collimated reticle shader, the PiP, the overlay and the minimum reticle
     size (section 5).
   - The playtest problems are fixed in the *assets*. They disappear in game only after that
     integration.
   - Unreal import is BLOCKED (not available).
2. **The game is hitscan.** The BDC and holdover marks match real 5.56 mm ballistics but have no
   effect until bullet drop exists.
3. **True-scale small features are sub-pixel** at the default ADS FOV (0.43 px/MOA at 1080p): the
   IV-H1 1 MOA dot and the IV-R1 2 MOA dot. The runtime has to apply the `render_hints` minimum
   (SDF).
4. The **IV-H1 LOD1** has one 0.6 mm² decimated triangle with zero UV area; it samples a single
   texel. Third person only; cosmetic.
5. **The IV-7 itself is unchanged.** It still carries its old optic, with transmission glass and a
   geometry reticle, and the fold-sign documentation issue (section 8). The rifle's fix pass should
   hide `^Optic`, or treat IV-R1 as its replacement, and correct the fold documentation.
6. **Eye points differ per optic** (bore x -14.9 to -16.95 cm; heights 7.0 to 7.6 cm). This is
   realistic, but the ADS camera must follow `socket_eye`.
7. **The magnified through-sight images are composites** that emulate the runtime PiP; they are
   not an optical simulation. The raw eye view of a magnified optic (`<ID>_through_game_fov.png`)
   shows only the static fallback sheet inside the dark tube, which is what a runtime without PiP
   would show.
8. **UV coverage** is 37-38 % on IV-P2 and IV-S3. The 35-45 deg unwrap needed to stop the knurl
   flutes folding creates many small islands. Texel density is still 24-35 px/cm, at or above the
   IV-7's.
9. The ribbed rubber eyecups read somewhat light grey under the studio lights. It is a material
   polish item.
10. Masses, ADS times and recommended ranges are design values, not measurements. The eyepiece
    vignette is a simple model, not derived from the eye's offset from the exit pupil.
11. The test-range ground in the through-sight renders shows stretched noise at grazing angles.
    This belongs to the preview scene only.
