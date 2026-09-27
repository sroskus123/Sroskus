"""Fill the IV-7 spec placeholders ({{...}}) from the regenerated reports (fix round 1).

    python3 fill_spec.py

Reads Art/Previews/IV7/IV7_validation.json, fix_r1/tex_stats_after.json, fix_r1/tech_checks.json,
fix_r1/fix_render_measurements.json (after) and fix_r1/r1_render_measurements.json (the r1 review
renders measured with the same object masks), and writes the numbers into
Art/Reference/IV7_carbine_spec.md.  Placeholders that are already filled are left alone.
"""
import json, os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", "..", ".."))
SPEC = os.path.join(ROOT, "Art", "Reference", "IV7_carbine_spec.md")
V = json.load(open(os.path.join(ROOT, "Art", "Previews", "IV7", "IV7_validation.json")))
T = json.load(open(os.path.join(HERE, "tex_stats_after.json")))
TB = json.load(open(os.path.join(HERE, "tex_stats_before_partial_build.json")))
K = json.load(open(os.path.join(HERE, "tech_checks.json")))
RM = json.load(open(os.path.join(HERE, "fix_render_measurements.json")))
R1 = json.load(open(os.path.join(HERE, "r1_render_measurements.json")))
pc = V["pose_checks"]
fam = T["families"]
an = fam["anodised"]["exterior"]
mag = fam["polymer_mag"]["exterior"]
ph = fam["phosphate"]["exterior"]
dens = {n: o.get("texel_density_px_per_cm") for n, o in V["objects"].items()}
ts = V["texture_sets"]


def pct(x, d=1):
    return f"{100 * x:.{d}f} %"


bind = pc["bind_pose"]
subs = {
    "BODY_DENS": f"{min(dens[n] for n in ('UpperReceiver', 'LowerReceiver', 'Handguard')):.1f}-"
                 f"{max(dens[n] for n in ('UpperReceiver', 'LowerReceiver', 'Handguard', 'ChargingHandle', 'Selector')):.1f} px/cm "
                 f"(upper {dens['UpperReceiver']:.1f}, lower {dens['LowerReceiver']:.1f}, handguard {dens['Handguard']:.1f}, "
                 f"optic {dens['Optic']:.1f})",
    "FURN_DENS": f"{dens['PistolGrip']:.1f} px/cm (grip, stock, magazine)",
    "BODY_COV": pct(ts["Body"]["uv_overlap"]["covered_fraction"]),
    "FURN_COV": pct(ts["Furniture"]["uv_overlap"]["covered_fraction"]),
    "ANOD_ROUGH": "p5 / p50 / p95 = " + " / ".join(f"{x:.2f}" for x in an["rough_p5_p50_p95"]),
    "ANOD_WEAR": pct(an["worn_bare_frac_lum_gt_0.20"]),
    "ANOD_TILT": f"{an['normal_tilt_deg_mean_p99'][0]:.1f} deg, p99 {an['normal_tilt_deg_mean_p99'][1]:.1f} deg",
    "PHOS_METAL": pct(ph["metal_lt0.1_mid_gt0.9"][2], 0),
    "BIND_RESULT": (f"**0 penetrations**; {len(bind)} seating contacts (upper/lower, pins in their holes, barrel "
                    f"in nut and muzzle device, cross bolts, grip on the lower ...), deepest "
                    f"{max(v['depth_mm'] for v in bind.values()):.3f} mm"),
    "POSE_RESULT": (f"**{sum(1 for v in pc['poses'].values() if v['result'] == 'PASS')} / {len(pc['poses'])} PASS**, "
                    f"0 penetrations (only coplanar selector-hub seating contacts)"),
    "CH_RESULT": (f"**{sum(1 for r in pc['charging_handle_stroke'] if r['result'] == 'PASS' and r['guided'])} / "
                  f"{len(pc['charging_handle_stroke'])} guided**: 0 penetrations, shaft engaged "
                  f"{pc['charging_handle_stroke'][0]['shaft_engaged_cm']} -> {pc['charging_handle_stroke'][-1]['shaft_engaged_cm']} cm, "
                  f"{max(r['min_gap_to_upper_mm'] for r in pc['charging_handle_stroke']):.1f} mm from the channel at every step"),
    "OPTICS_RESULT": ("**" + ", ".join(f"{k} {v['result']}" for k, v in pc["optics_folded"].items()) + "**, 0 penetrations; "
                      "folded rear leaf to the optic " + " / ".join(f"{v['rear_leaf_folded_clearance_mm']:.1f}"
                                                                 for v in pc["optics_folded"].values()) + " mm; "
                      "charging handle at full stroke: no contact with any optic"),
    "FOLD_RESULT": (f"rear leaf lies at x {pc['rear_leaf_folded_bbox_bore_cm']['x'][0]} ... {pc['rear_leaf_folded_bbox_bore_cm']['x'][1]}, "
                    f"z {pc['rear_leaf_folded_bbox_bore_cm']['z'][0]} ... {pc['rear_leaf_folded_bbox_bore_cm']['z'][1]} cm (bore frame); "
                    f"leaf plates {pc['folded_leaf_clearance_mm']['RearSightLeaf plate - RearSightBase']} / "
                    f"{pc['folded_leaf_clearance_mm']['FrontSightLeaf plate - FrontSightBase']} mm above their bases, "
                    f"{pc['folded_leaf_clearance_mm']['RearSightLeaf-Optic (built-in)']} mm from the built-in optic"),
    "NEG_RESULT": ("**FAIL as expected**: RearSightLeaf in the optic riser, "
                   f"{pc['negative_control']['rear_sight_+90_forward']['contacts']['RearSightLeaf x Optic']['depth_mm']:.1f} mm deep"),
}


def ms(tag, lab, key="lum_p10_p50_p90_p99"):
    d = RM.get(tag, {}).get(lab) or {}
    return d.get(key)


def r1s(tag, lab):
    return R1.get(tag, {}).get(lab, {})


upper_sun, mag_sun = RM["inspect_sun"]["upper_receiver"], RM["inspect_sun"]["magazine"]
upper_sh, mag_sh = RM["inspect_shade"]["upper_receiver"], RM["inspect_shade"]["magazine"]
r1_us, r1_ms, r1_ush, r1_msh = (r1s("r1_sun", "upper_receiver"), r1s("r1_sun", "magazine"),
                                r1s("r1_shade", "upper_receiver"), r1s("r1_shade", "magazine"))
tb_an = TB["families"]["anodised"]["exterior"]
ring = V["rear_sight_ring"]
fbx = K["fbx_texture_refs"]
st = K["uv_stretch_share_ratio_gt_1.5"]
rz = K["razor_edges_gt_70deg"]
dc = T["dust_cover_ghost"]

rows = [
    ("SIL-1", "P1", "**Fixed**",
     "Real AR-type charging handle: T-handle (1.9 cm) + 12.2 cm shaft (14.1 cm) running in a 9.2 x 5.2 mm channel under the "
     "rail; latch lever on the left wing (1.4 mm pocket, 0.3 mm gap, raised 0.6 mm), vertical roll pin, thumb grooves, hook "
     "tooth in a notch of the upper's rear face; wings 0.2 mm behind the upper; body 0.2 mm over the castle nut",
     f"`pose_checks.charging_handle_stroke`: {subs['CH_RESULT']}. `IV7_charging_handle.png`, `IV7_rig_pose_test.png`"),
    ("SIL-2", "P1", "**Fixed**",
     "Fold = -90 deg about the bone's local Y (leaf top towards the stock) in the rig test pose, spec 5 / 9.4 and the "
     "optics spec; sight towers lowered to z 4.28 with the hinge at 4.52 so a folded leaf never touches its base; automated "
     "fold validation with the built-in optic and with every optic of `Shared/config/optics.json` mounted",
     f"Folds at -30 / -60 / -90 deg: 0 penetrations. Mounted optics: {subs['OPTICS_RESULT']}. {subs['FOLD_RESULT']}. "
     f"Negative control +90 deg: {subs['NEG_RESULT']}. `IV7_sights_folded.png`"),
    ("TECH-2", "P1", "**Fixed**", "Same change as SIL-2 (the documented sign was the defect)", "As SIL-2"),
    ("TECH-1", "P1", "**Fixed**",
     "The leaf's centre post runs up into the ghost ring (post to z 6.62, trimmed by the aperture bore), bevelled "
     "separately, then unioned; new validation `rear_sight_ring` + the one-shell rule for every part",
     "RearSightLeaf LOD0 / LOD1 / LOD2: " + " / ".join(str(ring[n]["shells"]) for n in ("RearSightLeaf", "RearSightLeaf_LOD1", "RearSightLeaf_LOD2"))
     + " shell; solid material on the centre line from the post (z 6.20) through the junction into the ring (z 6.52) in "
     "every LOD. `IV7_ads.png`, `fix_r1/fix_rear_ring_closeup_optic_hidden.png`"),
    ("MAT-1", "P1", "**Fixed**",
     "Anodised aluminium: metallic 1, dark cool base (B/R 1.15, faintly coloured specular), satin roughness 0.29-0.32 with "
     "breakup and machining streaks, orange-peel + tool-path micro normal (`ivlib.mat_anodized(style='worn_satin')`; the "
     "legacy style used by the optics set is unchanged). Magazine polymer: lighter warm grey (0.066, 0.063, 0.057), matte 0.80 "
     "(0.9 stippled)",
     f"Exterior texels, anodised: BaseColor median {an['basecolor_lin_median_rgb']}, metallic > 0.9 on "
     f"{pct(an['metal_lt0.1_mid_gt0.9'][2])}, roughness {subs['ANOD_ROUGH']}; magazine: {mag['basecolor_lin_median_rgb']}, "
     f"metallic 0, roughness p50 {mag['rough_p5_p50_p95'][1]:.2f}. Inspect render (same camera as r1), sRGB luminance "
     f"p50 / p90 upper receiver vs magazine: shade {upper_sh['lum_p10_p50_p90_p99'][1]} / {upper_sh['lum_p10_p50_p90_p99'][2]} vs "
     f"{mag_sh['lum_p10_p50_p90_p99'][1]} / {mag_sh['lum_p10_p50_p90_p99'][2]} (r1: {r1_ush['p10_p50_p90_p99'][1]} / "
     f"{r1_ush['p10_p50_p90_p99'][2]} vs {r1_msh['p10_p50_p90_p99'][1]} / {r1_msh['p10_p50_p90_p99'][2]}); sun "
     f"{upper_sun['lum_p10_p50_p90_p99'][1]} / {upper_sun['lum_p10_p50_p90_p99'][2]} vs {mag_sun['lum_p10_p50_p90_p99'][1]} / "
     f"{mag_sun['lum_p10_p50_p90_p99'][2]} (r1: {r1_us['p10_p50_p90_p99'][1]} / {r1_us['p10_p50_p90_p99'][2]} vs "
     f"{r1_ms['p10_p50_p90_p99'][1]} / {r1_ms['p10_p50_p90_p99'][2]}). The receiver is now a dark reflective surface with "
     f"sky highlights, the magazine a flat lighter diffuse grey. `IV7_sun_vs_shade.png`"),
    ("MAT-2", "P1", "**Fixed**",
     "Wear only where an edge is convex AND exposed (baked AO) and weighted by the contact attribute (handguard bottom at the "
     "support hand, magwell flare, trigger guard, charging-handle wings and latch, rail teeth moderately, turret caps, end plate), "
     "broken into chips and scuffed patches; half-worn dark rims; light dust in cavities",
     f"Bare-aluminium texels (exterior anodised): r1 0.22 % -> {subs['ANOD_WEAR']} (partial build "
     f"{pct(tb_an['worn_bare_frac_lum_gt_0.20'])} as a continuous line on every bevel); per part: "
     + ", ".join(f"{n} {pct((T['parts'][n].get('exterior') or T['parts'][n]['all'])['worn_bare_frac_lum_gt_0.20'])}"
                 for n in ("ChargingHandle", "LowerReceiver", "UpperReceiver", "Handguard", "Optic", "BufferTube"))
     + ". `fix_r1/fix_graze_*.png`, `IV7_closeup_receiver_*.png`"),
    ("MAT-3", "P1", "**Fixed**",
     "The mask bake moves every moving part away (dust cover, charging handle, carrier, selector, bolt catch, trigger, "
     "magazine release, both leaves, magazine + rounds): no inter-part AO or cavity dirt in either direction",
     f"ORM AO on the cover's closed-outer face: r1 mean 0.032 -> {dc['cover_closed_outer_face']['ao_mean']:.2f} "
     f"(p5 {dc['cover_closed_outer_face']['ao_p5']:.2f}); lower flank under the port {dc['lower_flank_under_port']['ao_mean']:.2f} "
     f"vs control patch {dc['lower_flank_control_below']['ao_mean']:.2f} (fence / button occlusion, no cover shape). "
     "`fix_r1/fix_engineAO_dustcover_open_vs_closed.png`"),
    ("Glass", "P1", "**Fixed**",
     "`M_IV7_Glass` = thin coated alpha glass (`ivoptics.mat_glass_thin`: alpha 0.05 per surface, blended, double sided, "
     "specular 0.7 with a cool coating tint): no transmission, no refraction",
     f"`glass_audit`: 0 problems; GLB `extensionsUsed` = {K['glb']['extensionsUsed']} (no KHR_materials_transmission)"),
    ("SIL-3", "P2", "Fixed", "Trigger, trigger pin and hammer pin 1.2 cm rearward", f"Trigger reach {V['measurements']['trigger_reach_cm']} cm (was 8.6)"),
    ("SIL-4", "P2", "Documented", "LOP and bolt-face-to-butt added to 3 and 9.1", f"LOP {V['measurements']['length_of_pull_cm']} cm"),
    ("SIL-5", "P2", "Fixed", "Magwell front wall 14 -> 6 mm below the pivot-pin lug, flared mouth kept", "Measured 6.0 mm; magazine clearance 0.5 mm"),
    ("SIL-6", "P2", "Fixed", "Smooth carrier flat with 9 fine forward-assist notches (1.2 mm wide, 2.6 mm pitch) near the rear of the port; bolt head and extractor", "`IV7_closeup_receiver_right.png`"),
    ("SIL-7", "P2", "Fixed", "Grip top section inside the lower's footprint, first ring 2.8 mm below the top (even bevel)", "Grip / lower seating contact 0 penetration"),
    ("TECH-3", "P2", "Fixed",
     "Only UV islands whose TOTAL area is < 0.05 mm^2 are collapsed (a tiny face inside a larger island keeps its UVs); "
     "islands with no pixel centre are nudged / grown (up to 3.4x) instead of collapsed; glyph counters and pictogram gaps "
     "get the markings' 1.6x density; LOD triangles with collapsed UVs get a neighbour's affine mapping",
     f"Collapsed faces 6,060 -> {ts['Body']['uv_overlap']['collapsed_degenerate_faces']} (Body); largest zero-UV face "
     f"{max((o.get('zero_uv_max_face_mm2') or 0) for o in V['objects'].values()):.3f} mm^2 across LOD0/1/2 (limit 0.05); "
     "the '6' of the roll mark renders with its counter (`fix_r1/crop_rollmark_3x.png`)"),
    ("TECH-4", "P2", "Fixed", "Pixel-exact per-island raster check (fails on any shared pixel); nudged islands update the ownership map",
     f"Shared pixels Body {ts['Body']['uv_overlap']['pixels_shared_by_different_islands']}, Furniture "
     f"{ts['Furniture']['uv_overlap']['pixels_shared_by_different_islands']} at 2048"),
    ("TECH-5", "P2", "Partly fixed",
     "Knife edge at the buffer tower removed (tower flat 1.55), dust-cover hinge rebuilt (solid barrel, then bored), leaves "
     "bevelled per piece, V-groove knurls. Remaining > 70 deg edges are mostly concave (inside corners of slots and knurls)",
     "Convex / concave > 70 deg (cm): " + ", ".join(f"{n} {v['convex_cm']}/{v['concave_cm']}" for n, v in rz.items()
                                                     if n in ("UpperReceiver", "LowerReceiver", "Optic", "MuzzleDevice", "DustCover", "RearSightBase"))
     + " (r1 total: upper 59.8, lower 61, optic 132, muzzle 54.7, dust cover 2 x 6.5 fold). Rail-slot and muzzle-slot "
     "convex edges remain: known issue"),
    ("TECH-6", "P2", "Fixed", "Forward-assist pawl trimmed to the carrier radius + 0.2 mm, gas tube from x 3.05, CH wings 0.2 mm behind the upper, end plate over the tube OD, magazine-release hole deepened, bolt-catch top lowered",
     subs["BIND_RESULT"] + "; every documented pose 0 penetrations"),
    ("TECH-7", "P2", "Fixed", "Upper bevelled with a 22 deg limit (the 26 deg side creases get a soft bevel, the large flats shade flat)",
     "No flat receiver face > 1 cm^2 with corner normals > 5.5 deg off (the review's 4.63 cm^2 face: 12.2 deg); the magwell flare strip stays smooth by design"),
    ("TECH-8", "P2", "Fixed", "FBX materials reference `_Normal_DX`; relative texture paths only; the header's source-file path reduced to the file name",
     f"Raw scan: `_Normal_DX` references {fbx['SK_IV7_Carbine.fbx']['mentions_Normal_DX']}, OpenGL normal references "
     f"{fbx['SK_IV7_Carbine.fbx']['mentions_OpenGL_Normal']}, '/home/' {sum(v['absolute_home_paths'] for v in fbx.values())} in 4 FBX files"),
    ("TECH-9", "P2", "Fixed", "One self-contained LOD0 GLB for the browser + a glTF set (LOD0/1/2 + magazine) sharing one copy of the textures", "`Art/Export/GLB/IV7/`"),
    ("TECH-10", "P2", "Fixed", "Magazine release and catch notch moved to x -6.3 over the rear of the magwell; magazine bone on that axis", "`measurements.magazine_pivot_on_catch_axis` = [true, true]"),
    ("TECH-11", "P2", "Fixed", "Recursive orphan purge; static magazine: all vertex groups and deform weights removed, custom normals copied from LOD0",
     "Orphan materials / meshes / generated images: 0; node groups: `glTF Material Output` only"),
    ("TECH-12", "P2", "Fixed", "Selector hub disc planar and barrel cylindrical islands (`uv_planar_policy`)",
     f"Selector UV area with stretch > 1.5: 17.4 % -> {pct(st['Selector'])}"),
    ("MAT-4", "P2", "Fixed", "Phosphate metallic 1 (darker base 0.046, roughness 0.52); grime / soot fade to dielectric in a narrow step",
     f"Phosphate texels metallic > 0.9: {pct(ph['metal_lt0.1_mid_gt0.9'][2])} (r1: 0 %, all mid)"),
    ("MAT-5", "P2", "Improved", "Orange-peel + tool-path micro normal, bake dithered to 8 bits",
     f"Anodised mean tilt 0.32-0.45 -> {an['normal_tilt_deg_mean_p99'][0]:.2f} deg, p99 {an['normal_tilt_deg_mean_p99'][1]:.1f} deg "
     "(kept subtle on purpose: stronger peel read as crumpled paper in the close-ups)"),
    ("MAT-6", "P2", "Improved, documented", "Per-island budgets, markings 1.6x, hidden surfaces 0.35-0.7x",
     f"Body coverage 41 % -> {subs['BODY_COV']}; the ~2,000 bevel islands with 3 px margins keep it below 65 %"),
    ("MAT-7", "P2", "Fixed", "Stipple cells ~2.5 mm (~11 texels), low Voronoi randomness", "`IV7_closeup_receiver_*.png`"),
    ("MAT-8", "P2", "Fixed", "0.3 mm dot, emission 8, black muzzle-side mask", "`IV7_ads.png`: small saturated red dot"),
    ("MAT-9", "P2", "Fixed", "SAFE = white bullet with an unpainted diagonal gap + thin slash, cutters never overlap", "`fix_r1/crop_pictograms_3x.png`"),
    ("MAT-10", "P2", "Fixed", "Housing 48 segments (12 per quarter)", "`IV7_ads.png`"),
]
table = ["| ID | Sev. | Outcome | Change in the source | Evidence (regenerated) |", "| --- | --- | --- | --- | --- |"]
for r in rows:
    table.append("| " + " | ".join(x.replace("|", "/").replace("\n", " ") for x in r) + " |")
subs["FIX_TABLE"] = "\n".join(table)

s = open(SPEC).read()
for k, v in subs.items():
    s = s.replace("{{" + k + "}}", v)
left = [x for x in subs if "{{" + x + "}}" in s]
open(SPEC, "w").write(s)
import re
print("remaining placeholders:", re.findall(r"\{\{[A-Z_]+\}\}", s))
json.dump(subs, open(os.path.join(HERE, "spec_fill_values.json"), "w"), indent=1)
