"""IV-7 fix round 1: per-part / per-material statistics of the baked texture sets.

    python3 analyze_tex.py <iv7_carbine.blend> <texture dir> <out.json>

Rasterises every LOD0 part's UV triangles at the texture size (pixel centres, the bake rule),
classifies each face as exterior / interior by ray-cast visibility against the whole rifle
(bind pose) and reports, per part and per material family: linear BaseColor (median RGB,
luminance percentiles), roughness, metallic (share < 0.1 / mid / > 0.9), AO, normal-map tilt,
and the anodised edge-wear share (texels whose linear BaseColor luminance shows bare aluminium).
Also: dust-cover ghost check (AO / BaseColor of the cover's closed-outer face and of the lower
receiver flank under the port against a control patch).
"""
import sys, os, json, math
import numpy as np
import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..", "..", "Source", "Blender", "lib")))
import ivlib as L  # noqa: E402

blend, tex_dir, out_path = sys.argv[1:4]
bpy.ops.wm.open_mainfile(filepath=blend)
HOLD = Vector((-16.685730, 0.0, -9.172327))      # grip hold point in bore-frame cm

FAMILY = {
    "anodised": ["UpperReceiver", "LowerReceiver", "Handguard", "BufferTube", "ChargingHandle", "RearSightBase",
                 "RearSightLeaf", "FrontSightBase", "FrontSightLeaf", "Optic"],
    "nitrided": ["Barrel", "MuzzleDevice", "GasTube", "BoltCarrier", "DustCover", "DustCoverRod", "Trigger"],
    "phosphate": ["HandguardScrews", "BarrelNut", "GasBlock", "EndPlate", "CastleNut", "ForwardAssist", "Pins",
                  "MagRelease", "BoltCatch", "Selector", "RearSightBolt", "FrontSightBolt", "OpticBolt"],
    "polymer_mag": ["Magazine"], "polymer_fde": ["PistolGrip", "Stock"], "rubber": ["ButtPad"],
    "brass": ["MagRounds"],
}
FAM_OF = {p: f for f, ps in FAMILY.items() for p in ps}

parts = [o for o in bpy.data.collections["IV7_Parts"].objects if o.type == 'MESH']
sets = {"Body": [], "Furniture": []}
for o in parts:
    mn = o.data.materials[0].name if o.data.materials else ""
    if mn == "M_IV7_Body":
        sets["Body"].append(o)
    elif mn == "M_IV7_Furniture":
        sets["Furniture"].append(o)

# ---- exterior visibility per triangle (bind pose, whole rifle)
dg = bpy.context.evaluated_depsgraph_get()
allv = []; allt = []; off = 0
tri_world = {}
for o in parts:
    me = o.data
    me.calc_loop_triangles()
    co = np.empty(len(me.vertices) * 3); me.vertices.foreach_get("co", co); co = co.reshape(-1, 3)
    M = np.array(o.matrix_world); co = co @ M[:3, :3].T + M[:3, 3]
    tv = np.empty(len(me.loop_triangles) * 3, np.int64); me.loop_triangles.foreach_get("vertices", tv)
    tv = tv.reshape(-1, 3)
    tri_world[o.name] = (co, tv)
    allv.append(co); allt.append(tv + off); off += len(co)
V = np.concatenate(allv); T = np.concatenate(allt)
bvh = BVHTree.FromPolygons([tuple(v) for v in V], [tuple(t) for t in T], all_triangles=True)
gold = math.pi * (3 - math.sqrt(5))
DIRS = []
for k in range(64):
    z = 1 - 2 * (k + 0.5) / 64; r = math.sqrt(1 - z * z)
    DIRS.append(Vector((math.cos(gold * k) * r, math.sin(gold * k) * r, z)))


def escape_fraction(c, n):
    ok = 0; tot = 0
    for d in DIRS:
        if d.dot(n) < 0.08:
            continue
        tot += 1
        hit = bvh.ray_cast(c + n * 2e-5 + d * 2e-5, d, 1.0)
        if hit[0] is None:
            ok += 1
    return ok / max(tot, 1)


def s2l(x):
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)


res_all = {"blend": os.path.basename(blend), "tex_dir": tex_dir, "sets": {}, "families": {}, "parts": {}}
fam_px = {}
for sname, objs in sets.items():
    bc8 = np.array(Image.open(os.path.join(tex_dir, f"T_IV7_{sname}_BaseColor.png")).convert("RGB"))
    orm8 = np.array(Image.open(os.path.join(tex_dir, f"T_IV7_{sname}_ORM.png")).convert("RGB"))
    nm8 = np.array(Image.open(os.path.join(tex_dir, f"T_IV7_{sname}_Normal.png")).convert("RGB"))
    res = bc8.shape[0]
    # Blender UV rows start at the bottom: flip the PNGs to UV row order
    bc = s2l(np.flipud(bc8).reshape(-1, 3) / 255.0)
    orm = np.flipud(orm8).reshape(-1, 3) / 255.0
    nm = np.flipud(nm8).reshape(-1, 3) / 255.0 * 2 - 1
    tilt = np.degrees(np.arccos(np.clip(nm[:, 2] / np.maximum(np.linalg.norm(nm, axis=1), 1e-6), -1, 1)))
    lum = bc @ np.array([0.2126, 0.7152, 0.0722])
    covered = np.zeros(res * res, bool)
    for o in objs:
        me = o.data
        co, tv = tri_world[o.name]
        tl = np.empty(len(me.loop_triangles) * 3, np.int64); me.loop_triangles.foreach_get("loops", tl)
        tl = tl.reshape(-1, 3)
        uv = np.empty(len(me.loops) * 2); me.uv_layers.active.data.foreach_get("uv", uv); uv = uv.reshape(-1, 2)
        P = uv[tl] * res
        t_idx, pix = L._raster_tris(P, res)
        covered[pix] = True
        # exterior flag per triangle
        a = co[tv[:, 1]] - co[tv[:, 0]]; b = co[tv[:, 2]] - co[tv[:, 0]]
        nrm = np.cross(a, b); ln = np.linalg.norm(nrm, axis=1); nrm = nrm / np.maximum(ln, 1e-18)[:, None]
        cen = co[tv].mean(1)
        ext = np.array([escape_fraction(Vector(cen[i]), Vector(nrm[i])) >= 0.2 if ln[i] > 1e-14 else False
                        for i in range(len(tv))])
        e_px = ext[t_idx]
        rec = {}
        for label, m in (("all", np.ones(len(pix), bool)), ("exterior", e_px)):
            p = pix[m]
            if len(p) == 0:
                continue
            C = bc[p]; Lm = lum[p]; R = orm[p, 1]; Mt = orm[p, 2]; A = orm[p, 0]; Tl = tilt[p]
            rec[label] = {
                "texels": int(len(p)),
                "basecolor_lin_median_rgb": [round(float(np.median(C[:, k])), 4) for k in range(3)],
                "lum_lin_p5_p50_p95": [round(float(np.percentile(Lm, q)), 4) for q in (5, 50, 95)],
                "rough_p5_p50_p95": [round(float(np.percentile(R, q)), 3) for q in (5, 50, 95)],
                "rough_std": round(float(R.std()), 4),
                "metal_lt0.1_mid_gt0.9": [round(float((Mt < 0.1).mean()), 4), round(float(((Mt >= 0.1) & (Mt <= 0.9)).mean()), 4),
                                          round(float((Mt > 0.9).mean()), 4)],
                "ao_p5_p50_p95": [round(float(np.percentile(A, q)), 3) for q in (5, 50, 95)],
                "normal_tilt_deg_mean_p99": [round(float(Tl.mean()), 2), round(float(np.percentile(Tl, 99)), 2)],
                "worn_bare_frac_lum_gt_0.20": round(float(((Lm > 0.20) & (Mt > 0.5)).mean()), 4),
                "worn_any_frac_lum_gt_0.10": round(float(((Lm > 0.10) & (Mt > 0.5)).mean()), 4),
                "grime_dielectric_frac_metal_lt_0.5": round(float((Mt < 0.5).mean()), 4),
            }
        rec["exterior_face_share"] = round(float(ext.mean()), 3)
        rec["family"] = FAM_OF.get(o.name, "?")
        res_all["parts"][o.name] = rec
        f = FAM_OF.get(o.name)
        if f:
            d = fam_px.setdefault(f, {"all": [], "exterior": [], "set": sname})
            d["all"].append(pix); d["exterior"].append(pix[e_px])
    res_all["sets"][sname] = {"size": res, "covered_fraction": round(float(covered.mean()), 4)}
    # family aggregates for this set
    for f, d in fam_px.items():
        if d["set"] != sname or f in res_all["families"]:
            continue
        out = {}
        for label in ("all", "exterior"):
            p = np.unique(np.concatenate(d[label])) if d[label] else np.zeros(0, np.int64)
            if len(p) == 0:
                continue
            C = bc[p]; Lm = lum[p]; R = orm[p, 1]; Mt = orm[p, 2]; A = orm[p, 0]; Tl = tilt[p]
            out[label] = {
                "texels": int(len(p)),
                "basecolor_lin_median_rgb": [round(float(np.median(C[:, k])), 4) for k in range(3)],
                "basecolor_lin_mean_rgb": [round(float(C[:, k].mean()), 4) for k in range(3)],
                "lum_lin_p5_p50_p95": [round(float(np.percentile(Lm, q)), 4) for q in (5, 50, 95)],
                "rough_p5_p50_p95": [round(float(np.percentile(R, q)), 3) for q in (5, 50, 95)],
                "rough_mean_std": [round(float(R.mean()), 3), round(float(R.std()), 4)],
                "metal_lt0.1_mid_gt0.9": [round(float((Mt < 0.1).mean()), 4), round(float(((Mt >= 0.1) & (Mt <= 0.9)).mean()), 4),
                                          round(float((Mt > 0.9).mean()), 4)],
                "metal_mean": round(float(Mt.mean()), 3),
                "ao_p5_p50_p95": [round(float(np.percentile(A, q)), 3) for q in (5, 50, 95)],
                "normal_tilt_deg_mean_p99": [round(float(Tl.mean()), 2), round(float(np.percentile(Tl, 99)), 2)],
                "worn_bare_frac_lum_gt_0.20": round(float(((Lm > 0.20) & (Mt > 0.5)).mean()), 4),
                "worn_any_frac_lum_gt_0.10": round(float(((Lm > 0.10) & (Mt > 0.5)).mean()), 4),
                "grime_dielectric_frac_metal_lt_0.5": round(float((Mt < 0.5).mean()), 4),
            }
        res_all["families"][f] = out
    # ---- dust-cover ghost check (Body set)
    if sname == "Body" and "DustCover" in tri_world:
        def face_pix(oname, sel_fn):
            o = bpy.data.objects[oname]; me = o.data
            co, tv = tri_world[oname]
            tl = np.empty(len(me.loop_triangles) * 3, np.int64); me.loop_triangles.foreach_get("loops", tl)
            tl = tl.reshape(-1, 3)
            uv = np.empty(len(me.loops) * 2); me.uv_layers.active.data.foreach_get("uv", uv); uv = uv.reshape(-1, 2)
            a = co[tv[:, 1]] - co[tv[:, 0]]; b = co[tv[:, 2]] - co[tv[:, 0]]
            nrm = np.cross(a, b); nrm /= np.maximum(np.linalg.norm(nrm, axis=1), 1e-18)[:, None]
            cen = co[tv].mean(1) * 100.0 + np.array(HOLD)          # bore-frame cm
            sel = np.nonzero(sel_fn(cen, nrm))[0]
            t_idx, pix = L._raster_tris(uv[tl[sel]] * res, res)
            return pix

        def stat(pix):
            if len(pix) == 0:
                return None
            return {"texels": int(len(pix)), "ao_mean": round(float(orm[pix, 0].mean()), 3),
                    "ao_p5": round(float(np.percentile(orm[pix, 0], 5)), 3),
                    "basecolor_lum_lin_mean": round(float(lum[pix].mean()), 4)}
        # the cover's face that is the OUTER face when closed: in the bind (open, 176 deg) pose
        # its normal points about +Y
        # plate faces only: > 3.5 mm from the hinge axis (the hinge-barrel bore around the static rod
        # is legitimately occluded in every pose)
        far = lambda c: np.hypot(c[:, 1] + 1.80, c[:, 2] + 1.35) > 0.35
        dc_out = face_pix("DustCover", lambda c, n: (n[:, 1] > 0.8) & far(c))
        dc_in = face_pix("DustCover", lambda c, n: (n[:, 1] < -0.8) & far(c))
        flank_port = face_pix("LowerReceiver", lambda c, n: (n[:, 1] < -0.9) & (c[:, 0] > -8.2) & (c[:, 0] < -2.2) &
                              (c[:, 2] < -2.3) & (c[:, 2] > -4.5))
        flank_ctrl = face_pix("LowerReceiver", lambda c, n: (n[:, 1] < -0.9) & (c[:, 0] > -8.2) & (c[:, 0] < -2.2) &
                              (c[:, 2] < -5.3) & (c[:, 2] > -7.5))
        res_all["dust_cover_ghost"] = {"cover_closed_outer_face": stat(dc_out), "cover_closed_inner_face": stat(dc_in),
                                       "lower_flank_under_port": stat(flank_port),
                                       "lower_flank_control_below": stat(flank_ctrl)}

json.dump(res_all, open(out_path, "w"), indent=1)
print("families:")
for f, d in res_all["families"].items():
    e = d.get("exterior") or d.get("all")
    print(f"  {f:12s} ext tx={e['texels']:8d} bc_med={e['basecolor_lin_median_rgb']} lum={e['lum_lin_p5_p50_p95']} "
          f"rough={e['rough_p5_p50_p95']} std={e['rough_mean_std'][1]} metal(<.1,mid,>.9)={e['metal_lt0.1_mid_gt0.9']} "
          f"tilt={e['normal_tilt_deg_mean_p99']} worn>{e['worn_bare_frac_lum_gt_0.20']} any>{e['worn_any_frac_lum_gt_0.10']} "
          f"grime={e['grime_dielectric_frac_metal_lt_0.5']}")
print("dust cover:", json.dumps(res_all.get("dust_cover_ghost")))
print("sets:", res_all["sets"])
