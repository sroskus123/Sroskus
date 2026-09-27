# Third-party data: MakeHuman / MPFB2 (CC0 1.0)

This folder holds the few MakeHuman / MPFB2 data files that the Iron Valley character scripts
load (`Art/Source/Blender/characters/human_base.py` together with `Art/Source/Blender/lib/ivchar.py`).
Nothing else is vendored.

## Origin

| Item | Value |
| --- | --- |
| Data | MakeHuman `hm08` base mesh, targets, and the MPFB2 "game_engine" rig with its weights and mesh metadata |
| Authors | MakeHuman team. The `base.obj` header names Data Collection AB, Joel Palmius and Jonas Hauquier as the copyright holders at the time of the CC0 release (September 2020). The MPFB2 rig and weights come from the same project. |
| License | **CC0 1.0 Universal** (full text in `LICENSE.md`). `weights.game_engine.json` also declares `"license": "CC0"` in its header. |
| Obtained from | PyPI package **anny 0.6.0** (NAVER Corp.), file `anny-0.6.0-py3-none-any.whl`, path inside the wheel `anny/data/mpfb2/` |
| Wheel SHA-256 | `050a0b24a3e7fdb89b46dc3581947ea84225305425ac9a1a97b65ea997fb2ad6` |
| anny code | Apache-2.0. **No anny code is vendored or copied.** Its model code was only read to understand how it interprets the rig, target and weight formats. |
| Date vendored | 2026-09-26 |
| Re-create | `python3 vendor_from_wheel.py [wheel]`. It checks the wheel hash and extracts exactly the files below. |

## Files (byte-identical to the wheel, not modified)

| File | Bytes | SHA-256 (first 16 hex) | Used for |
| --- | --- | --- | --- |
| `LICENSE.md` | 6962 | `f6089cba01cb570a` | CC0 1.0 legal text |
| `3dobjs/base.obj` | 1749303 | `8e761e6624b8f545` | hm08 base mesh: 19 158 vertices, 21 334 UVs, groups (`body` plus helper geometry and joint cubes) |
| `rigs/standard/rig.game_engine.json` | 41038 | `a7785470d1c71316` | 53-bone game-engine skeleton: joint definitions (CUBE/MEAN), roll, parents |
| `rigs/standard/weights.game_engine.json` | 3026778 | `9f4a773e74ce5ba0` | skin weights per bone (vertex index, weight) |
| `mesh_metadata/basemesh_vertex_groups.json` | 81984 | `8cb1417bc55ae5ec` | index ranges: `body` = 0..13379, helper geometry, joint cubes (checked by the build) |
| `mesh_metadata/hm08.mirror` | 245992 | `679f80f101d89b3d` | left/right vertex pairs, used to symmetrise the weights |
| `targets/macrodetails/universal-male-young-averagemuscle-averageweight.target.gz` | 76 | `e814651195c53971` | macro target (empty by design) |
| `targets/macrodetails/universal-male-young-maxmuscle-averageweight.target.gz` | 45597 | `833caafc302bd930` | macro target |
| `targets/macrodetails/universal-male-old-averagemuscle-averageweight.target.gz` | 74 | `3721ecc3f7a6af1d` | macro target (empty by design) |
| `targets/macrodetails/universal-male-old-maxmuscle-averageweight.target.gz` | 46209 | `d2443e0ce0b3acc6` | macro target |
| `targets/macrodetails/{african,asian,caucasian}-male-{young,old}.target.gz` | 112944–132860 | see `vendor_from_wheel.py` output | macro race/gender/age targets |
| `targets/arms/measure-upperarm-length-incr.target.gz` | 14066 | `72890d3448778f6d` | measure (proportion) target |
| `targets/arms/measure-lowerarm-length-decr.target.gz` | 13026 | `c2ebdaf38b9fedc6` | measure (proportion) target |

Total size: about 5.9 MB.

## What the Iron Valley build changes (at runtime, in the script; the files stay untouched)

1. It applies the macro targets (male, 28 years, muscle 0.70, weight 0.50, height 0.50,
   proportions 0.50, race 1/3 each) and the two measure targets (upper arm +0.50, forearm
   −0.50). It then scales the model uniformly to 1.80 m.
2. It deletes all helper geometry and joint cubes (eyes, eyelashes, teeth, tongue, tights,
   skirt, hair and genital helpers). Only the closed `body` group is kept, with its original
   UVs.
3. It renames the `Root` bone to `root` and places it at the origin with identity orientation.
   Root has no skin weights, so this does not change any deformation.
4. It adds four twist bones (`upperarm_twist_01_l/r`, `lowerarm_twist_01_l/r`, Unreal-mannequin
   names) and ramps part of the parent bones' weights onto them.
5. Weights: they are symmetrised across the mirror plane (the source differs by up to 0.26
   between sides, mostly on the calves and feet), limited to 4 influences, and renormalised to
   sum to 1.
6. The elbows are straightened from the modelled ~46° to 15° flexion, and that pose is applied
   as the rest pose (A-pose).

## Adding more targets later

If a derived character needs other macro values (for example a heavier build or a female
body), add the matching `targets/macrodetails/...` files to `FILES` in `vendor_from_wheel.py`
and re-run it. The weight formula is in `ivchar.macro_target_weights()`, which lists exactly
which files a given parameter set needs.
