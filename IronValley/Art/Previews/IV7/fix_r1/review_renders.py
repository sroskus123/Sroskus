"""IV-7 fix round 1: review renders + per-object render measurements from the BAKED export
materials stored in the .blend (the same data the GLB / FBX carry).

    python3 review_renders.py <iv7_carbine.blend> <out_dir> [quick] [view ...]

Views: sun_vs_shade (inspect view, sun and shade side by side + receiver / magazine luminance and
highlight statistics from an object-ID pass), fp (first-person sun / shade), graze (raking light,
wear), engine_ao (closed / open dust cover with the baked AO multiplied onto indirect light, the
way three.js aoMap / Unreal material AO use it), charging (handle home / pulled 7 cm, top and
right), fold (both leaves folded -90 deg, right and top, built-in optic), ring (rear aperture from
the ADS eye, optic hidden), optic_s3 (IV-S3 mounted, irons folded).
"""
import sys, os, math, json
import numpy as np
import bpy
from mathutils import Vector

blend, OUT = sys.argv[1], sys.argv[2]
args = sys.argv[3:]
QUICK = "quick" in args
views = [a for a in args if a != "quick"] or ["sun_vs_shade", "fp", "graze", "engine_ao", "charging", "fold",
                                              "ring", "optic_s3"]
os.makedirs(OUT, exist_ok=True)
bpy.ops.wm.open_mainfile(filepath=blend)
sc = bpy.context.scene
sc.render.engine = 'CYCLES'; sc.cycles.device = 'CPU'
sc.render.threads_mode = 'FIXED'; sc.render.threads = 4
sc.cycles.use_adaptive_sampling = True; sc.cycles.adaptive_threshold = 0.02
sc.cycles.use_denoising = True; sc.cycles.denoiser = 'OPENIMAGEDENOISE'
sc.cycles.max_bounces = 8; sc.cycles.glossy_bounces = 4; sc.cycles.transparent_max_bounces = 16
sc.view_settings.view_transform = 'AgX'; sc.view_settings.look = 'AgX - Medium High Contrast'
for c in ("IV7_LOD1", "IV7_LOD2", "IV7_Static"):
    if c in bpy.data.collections:
        bpy.data.collections[c].hide_render = True
arm = bpy.data.objects["SK_IV7"]; arm.hide_render = True
PARTS = [o for o in bpy.data.collections["IV7_Parts"].objects if o.type == 'MESH']
env = bpy.data.collections.new("REV_Env"); sc.collection.children.link(env)
RES = (960, 540) if QUICK else (1600, 900)
SPP = 32 if QUICK else 128
HOLD = Vector((-16.685730, 0.0, -9.172327))
MEAS = {}


def W(x, y, z):
    return Vector(((x - HOLD.x) * 0.01, (y - HOLD.y) * 0.01, (z - HOLD.z) * 0.01))


def sun_dir(el, rot):
    el = math.radians(el); rot = math.radians(rot)
    return Vector((math.sin(rot) * math.cos(el), math.cos(rot) * math.cos(el), math.sin(el)))


def clear_env():
    for o in list(env.objects):
        bpy.data.objects.remove(o, do_unlink=True)


def world(sun_el=40, sun_rot=-35, sky=0.3, sun=True, sun_strength=4.5):
    w = bpy.data.worlds.new("REV_World"); w.use_nodes = True; nt = w.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    s = nt.nodes.new('ShaderNodeTexSky'); s.sky_type = 'NISHITA'; s.sun_disc = False
    s.sun_elevation = math.radians(sun_el); s.sun_rotation = math.radians(sun_rot); s.altitude = 300; s.dust_density = 1.5
    bg = nt.nodes.new('ShaderNodeBackground'); bg.inputs[1].default_value = sky
    o = nt.nodes.new('ShaderNodeOutputWorld')
    nt.links.new(s.outputs[0], bg.inputs[0]); nt.links.new(bg.outputs[0], o.inputs[0])
    sc.world = w
    if sun:
        ld = bpy.data.lights.new("REV_Sun", 'SUN'); ld.energy = sun_strength; ld.angle = math.radians(0.55)
        ob = bpy.data.objects.new("REV_Sun", ld); env.objects.link(ob)
        ob.rotation_euler = (-sun_dir(sun_el, sun_rot)).to_track_quat('-Z', 'Y').to_euler()


def ground(z=-1.45):
    bpy.ops.mesh.primitive_plane_add(size=400, location=(0, 0, z))
    g = bpy.context.active_object; g.name = "REV_Ground"
    for c in g.users_collection:
        c.objects.unlink(g)
    env.objects.link(g)
    m = bpy.data.materials.new("REV_GroundMat"); m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs['Base Color'].default_value = (0.20, 0.18, 0.14, 1); b.inputs['Roughness'].default_value = 0.95
    g.data.materials.append(m)


def occluder(sun_el, sun_rot, center, dist=3.0, size=6.0):
    d = sun_dir(sun_el, sun_rot)
    bpy.ops.mesh.primitive_plane_add(size=size, location=Vector(center) + d * dist)
    p = bpy.context.active_object; p.name = "REV_Occluder"
    for c in p.users_collection:
        c.objects.unlink(p)
    env.objects.link(p)
    p.rotation_euler = d.to_track_quat('Z', 'Y').to_euler()
    p.visible_camera = False; p.visible_glossy = False
    m = bpy.data.materials.new("REV_Occ"); m.use_nodes = True
    m.node_tree.nodes["Principled BSDF"].inputs['Base Color'].default_value = (0.05, 0.05, 0.05, 1)
    p.data.materials.append(m)


def cam(loc, target, fov=40, ortho=None):
    cd = bpy.data.cameras.new("REV_Cam"); cd.sensor_fit = 'HORIZONTAL'
    if ortho:
        cd.type = 'ORTHO'; cd.ortho_scale = ortho
    else:
        cd.angle = math.radians(fov)
    cd.clip_start = 0.003; cd.clip_end = 1000
    ob = bpy.data.objects.new("REV_Cam", cd); env.objects.link(ob)
    ob.location = loc
    ob.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat('-Z', 'Y').to_euler()
    sc.camera = ob
    return ob


def render(name, samples=None, res=None):
    sc.render.resolution_x, sc.render.resolution_y = res or RES; sc.render.resolution_percentage = 100
    sc.cycles.samples = samples or SPP
    sc.render.image_settings.file_format = 'PNG'; sc.render.image_settings.color_mode = 'RGB'
    sc.render.filepath = os.path.join(OUT, name + ".png")
    bpy.ops.render.render(write_still=True)
    print("WROTE", sc.render.filepath)
    return sc.render.filepath


def pose(**bones):
    for pb in arm.pose.bones:
        pb.rotation_mode = 'XYZ'; pb.location = (0, 0, 0); pb.rotation_euler = (0, 0, 0)
    for bn, (loc, rot) in bones.items():
        pb = arm.pose.bones[bn]; pb.location = loc; pb.rotation_euler = [math.radians(a) for a in rot]
    bpy.context.view_layer.update()


MRES = (1280, 720)       # measurement views: same size / camera as the r1 review renders (comparable)


def id_pass(name, groups, res=None):
    """Flat ID render (emission, no AA): groups = {label: [object names]} -> {label: bool mask}."""
    saved = {o.name: list(o.data.materials) for o in PARTS}
    saved_vis = sc.world
    mats = {}
    cols = [(1, 0, 0), (0, 1, 0), (0, 0, 1), (1, 1, 0), (0, 1, 1), (1, 0, 1)]
    for i, lab in enumerate(groups):
        m = bpy.data.materials.new("ID_" + lab); m.use_nodes = True; nt = m.node_tree
        for n in list(nt.nodes):
            nt.nodes.remove(n)
        e = nt.nodes.new('ShaderNodeEmission'); e.inputs[0].default_value = (*cols[i], 1); e.inputs[1].default_value = 1
        o = nt.nodes.new('ShaderNodeOutputMaterial'); nt.links.new(e.outputs[0], o.inputs[0])
        mats[lab] = m
    blackm = bpy.data.materials.new("ID_black"); blackm.use_nodes = True
    nt = blackm.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    e = nt.nodes.new('ShaderNodeEmission'); e.inputs[0].default_value = (0, 0, 0, 1)
    o = nt.nodes.new('ShaderNodeOutputMaterial'); nt.links.new(e.outputs[0], o.inputs[0])
    lab_of = {n: lab for lab, ns in groups.items() for n in ns}
    for ob in PARTS:
        m = mats.get(lab_of.get(ob.name), blackm)
        ob.data.materials.clear(); ob.data.materials.append(m)
    hid = [o for o in env.objects if o.type == 'MESH']
    for o in hid:
        o.hide_render = True
    vt, look = sc.view_settings.view_transform, sc.view_settings.look
    sc.view_settings.view_transform = 'Standard'; sc.view_settings.look = 'None'
    fw = sc.render.filter_size; sc.render.filter_size = 0.01
    den = sc.cycles.use_denoising; sc.cycles.use_denoising = False
    p = render(name + "_id", samples=1, res=res)
    sc.cycles.use_denoising = den; sc.render.filter_size = fw
    sc.view_settings.view_transform = vt; sc.view_settings.look = look
    for o in hid:
        o.hide_render = False
    for ob in PARTS:
        ob.data.materials.clear()
        for m in saved[ob.name]:
            ob.data.materials.append(m)
    from PIL import Image
    a = np.array(Image.open(p).convert("RGB")).astype(np.int32)
    out = {}
    for i, lab in enumerate(groups):
        c = np.array(cols[i]) * 255
        m = np.all(np.abs(a - c) < 40, axis=-1)
        # erode 2 px: silhouette edges mix with the background in the beauty render
        from scipy import ndimage
        out[lab] = ndimage.binary_erosion(m, iterations=2)
    os.remove(p)
    return out


def region_stats(img_path, masks):
    from PIL import Image
    a = np.array(Image.open(img_path).convert("RGB")).astype(np.float64)
    lum = a @ np.array([0.2126, 0.7152, 0.0722])
    out = {}
    for lab, m in masks.items():
        if m.sum() < 50:
            out[lab] = None
            continue
        L_ = lum[m]; C = a[m]
        out[lab] = {"px": int(m.sum()), "lum_mean": round(float(L_.mean()), 1),
                    "lum_p10_p50_p90_p99": [round(float(np.percentile(L_, q)), 1) for q in (10, 50, 90, 99)],
                    "lum_std": round(float(L_.std()), 2),
                    "highlight_share_lum_gt_2x_median": round(float((L_ > 2 * np.median(L_)).mean()), 4),
                    "rgb_mean": [round(float(C[:, k].mean()), 1) for k in range(3)],
                    "blue_minus_red": round(float(C[:, 2].mean() - C[:, 0].mean()), 2)}
    return out


def side_by_side(paths, out, labels):
    from PIL import Image, ImageDraw
    ims = [Image.open(p).convert("RGB") for p in paths]
    w = sum(i.width for i in ims); h = max(i.height for i in ims)
    sheet = Image.new("RGB", (w, h + 34), (30, 30, 32)); x = 0
    d = ImageDraw.Draw(sheet)
    for im, lab in zip(ims, labels):
        sheet.paste(im, (x, 34)); d.text((x + 10, 10), lab, fill=(230, 230, 230)); x += im.width
    sheet.save(out)
    return out


GROUPS = {"upper_receiver": ["UpperReceiver"], "lower_receiver": ["LowerReceiver"], "magazine": ["Magazine"],
          "handguard": ["Handguard"], "grip_fde": ["PistolGrip"]}
FP_EYE = W(-23.0, 9.5, 11.0); FP_TGT = W(250.0, 1.0, -16.0)
INS_EYE = W(-14.0, 26.0, 12.0); INS_TGT = W(-2.0, 0.0, -6.0)

for view in views:
    clear_env(); pose()
    if view == "sun_vs_shade":
        world(40, -35); ground(); cam(INS_EYE, INS_TGT, 60)
        m = id_pass("inspect", GROUPS, MRES)
        p1 = render("fix_inspect_sun", res=MRES)
        clear_env(); world(40, -35); ground(); occluder(40, -35, W(0, 0, 0)); cam(INS_EYE, INS_TGT, 60)
        p2 = render("fix_inspect_shade", res=MRES)
        MEAS["inspect_sun"] = region_stats(p1, m); MEAS["inspect_shade"] = region_stats(p2, m)
        np.savez_compressed(os.path.join(OUT, "mask_inspect.npz"), **m)
        side_by_side([p1, p2], os.path.join(OUT, "fix_sun_vs_shade.png"), ["sun (40 deg)", "shade (sky only, sun occluded)"])
    elif view == "fp":
        world(40, -35); ground(); cam(FP_EYE, FP_TGT, 80)
        m = id_pass("fp", GROUPS, MRES)
        p1 = render("fix_fp_sun", samples=int(SPP * 1.5), res=MRES)
        clear_env(); world(40, -35); ground(); occluder(40, -35, W(0, 0, 0)); cam(FP_EYE, FP_TGT, 80)
        p2 = render("fix_fp_shade", samples=int(SPP * 1.5), res=MRES)
        MEAS["fp_sun"] = region_stats(p1, m); MEAS["fp_shade"] = region_stats(p2, m)
        np.savez_compressed(os.path.join(OUT, "mask_fp.npz"), **m)
        side_by_side([p1, p2], os.path.join(OUT, "fix_fp_sun_vs_shade.png"), ["first person, sun", "first person, shade"])
    elif view == "graze":
        world(9, 80, sky=0.08, sun_strength=6.0); ground()
        t = W(-9.0, 0.0, -4.0); cam(t + Vector((0.02, 0.26, 0.03)), t, 40); render("fix_graze_left")
        clear_env(); world(9, 100, sky=0.08, sun_strength=6.0); ground()
        t = W(-5.0, 0.0, -2.0); cam(t + Vector((0.02, -0.26, 0.03)), t, 40); render("fix_graze_right")
        clear_env(); world(30, 150, sky=0.15, sun_strength=5.0); ground()
        t = W(12.0, 0.0, -1.5); cam(t + Vector((0.03, -0.30, -0.08)), t, 40); render("fix_handguard_support_hand")
    elif view == "engine_ao":
        saved = {}
        for mname in ("M_IV7_Body", "M_IV7_Furniture"):
            nt = bpy.data.materials[mname].node_tree
            sep = [n for n in nt.nodes if n.type == 'SEPARATE_COLOR'][0]
            bsdf = [n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED'][0]
            out = [n for n in nt.nodes if n.type == 'OUTPUT_MATERIAL'][0]
            black = nt.nodes.new('ShaderNodeEmission'); black.inputs['Strength'].default_value = 0.0
            mix = nt.nodes.new('ShaderNodeMixShader')
            nt.links.new(sep.outputs['Red'], mix.inputs[0]); nt.links.new(black.outputs[0], mix.inputs[1])
            nt.links.new(bsdf.outputs[0], mix.inputs[2]); nt.links.new(mix.outputs[0], out.inputs['Surface'])
            saved[mname] = (nt, bsdf, out, black, mix)
        paths = []
        for state in ("open", "closed"):
            clear_env()
            pose(**({"dust_cover": ((0, 0, 0), (-176.0, 0, 0))} if state == "closed" else {}))
            world(40, -35, sky=0.9, sun=False); ground(z=-0.35)
            tgt = W(-5.0, 0.0, -2.8); cam(tgt + Vector((0.03, -0.30, 0.05)), tgt, 34)
            paths.append(render(f"fix_engineAO_shade_dustcover_{state}"))
        side_by_side(paths, os.path.join(OUT, "fix_engineAO_dustcover_open_vs_closed.png"),
                     ["baked AO x indirect light: dust cover open (bind)", "dust cover closed (-176 deg)"])
        for mname, (nt, bsdf, out, black, mix) in saved.items():
            nt.links.new(bsdf.outputs[0], out.inputs['Surface']); nt.nodes.remove(mix); nt.nodes.remove(black)
    elif view == "charging":
        world(35, -60, sky=0.35); ground()
        t = W(-17.5, 0.0, 1.9)
        cam(t + Vector((0.0, 0.0, 0.22)), t, 34); render("fix_charging_handle_home_top")
        cam(t + Vector((-0.05, 0.14, 0.09)), t, 34); render("fix_charging_handle_home_34_left")
        pose(charging_handle=((-0.07, 0, 0), (0, 0, 0)))
        t2 = W(-20.0, 0.0, 1.9)
        cam(t2 + Vector((0.0, 0.0, 0.26)), t2, 38); render("fix_charging_handle_pulled_top")
        cam(t2 + Vector((0.0, -0.30, 0.02)), t2, 38); render("fix_charging_handle_pulled_right")
    elif view == "fold":
        world(35, -60, sky=0.35); ground()
        pose(rear_sight=((0, 0, 0), (0, -90.0, 0)), front_sight=((0, 0, 0), (0, -90.0, 0)))
        t = W(-6.0, 0.0, 4.0)
        cam(t + Vector((0.0, -0.30, 0.0)), t, 30); render("fix_rear_sight_folded_right")
        cam(t + Vector((0.0, 0.0, 0.30)), t, 30); render("fix_rear_sight_folded_top")
        t = W(33.4, 0.0, 4.0)
        cam(t + Vector((0.0, -0.20, 0.0)), t, 30); render("fix_front_sight_folded_right")
    elif view == "ring":
        world(40, -35); ground()
        hidden = [o for o in PARTS if o.name.startswith("Optic")]
        for o in hidden:
            o.hide_render = True
        eye = W(-14.9, 0.0, 7.0)
        cam(eye + Vector((0.0, -0.02, 0.0)), W(-8.3, 0.0, 6.4), 14); render("fix_rear_ring_closeup_optic_hidden")
        cam(eye, eye + Vector((10.0, 0, 0)), 42); render("fix_ads_irons_optic_hidden")
        for o in hidden:
            o.hide_render = False
    elif view == "optic_s3":
        cfg = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..",
                                          "Shared", "config", "optics.json")))
        od = next(o for o in cfg["optics"] if o["id"] == "IVS3")
        root = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", ".."))
        before = set(bpy.data.objects)
        bpy.ops.import_scene.gltf(filepath=os.path.join(root, od["assets"]["glb"]))
        new = [o for o in bpy.data.objects if o not in before]
        tops = [o for o in new if o.parent is None]
        off = Vector(od["mount_on_iv7"]["socket_rail_rifle_m"]["blender_zup"])
        for o in tops:
            o.location = o.location + off
        for o in PARTS:
            if o.name.startswith("Optic"):
                o.hide_render = True
        world(35, -60, sky=0.35); ground()
        pose(rear_sight=((0, 0, 0), (0, -90.0, 0)), front_sight=((0, 0, 0), (0, -90.0, 0)))
        t = W(-6.0, 0.0, 5.5)
        cam(t + Vector((0.0, -0.40, 0.0)), t, 34); render("fix_ivs3_mounted_irons_folded_right")
        for o in new:
            bpy.data.objects.remove(o, do_unlink=True)
        for o in PARTS:
            o.hide_render = False
    else:
        print("unknown view", view)

if MEAS:
    mp = os.path.join(OUT, "fix_render_measurements.json")
    old = json.load(open(mp)) if os.path.exists(mp) else {}
    old.update(MEAS)
    json.dump(old, open(mp, "w"), indent=1)
    for k, v in MEAS.items():
        print(k)
        for lab, s in v.items():
            print("   ", lab, s)
