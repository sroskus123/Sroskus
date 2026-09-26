"""R1 review render helpers (own minimal clay setup, Cycles CPU)."""
import math
import bpy
from mathutils import Vector

W, H = 1280, 720


def setup_scene(me, samples=20):
    sc = bpy.context.scene
    sc.render.engine = 'CYCLES'
    sc.cycles.device = 'CPU'
    sc.cycles.samples = samples
    sc.cycles.use_denoising = True
    try:
        sc.cycles.denoiser = 'OPENIMAGEDENOISE'
    except Exception:
        pass
    sc.render.threads_mode = 'FIXED'
    sc.render.threads = 3
    sc.render.resolution_x, sc.render.resolution_y = W, H
    sc.render.resolution_percentage = 100
    sc.view_settings.view_transform = 'Standard'
    sc.render.film_transparent = False
    world = bpy.data.worlds.new("R1World")
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs[0].default_value = (0.30, 0.31, 0.33, 1)
    bg.inputs[1].default_value = 0.8
    sc.world = world
    mat = bpy.data.materials.new("R1Clay")
    mat.use_nodes = True
    b = mat.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (0.62, 0.60, 0.57, 1)
    b.inputs["Roughness"].default_value = 0.5
    me.data.materials.clear()
    me.data.materials.append(mat)
    for p in me.data.polygons:
        p.use_smooth = True
    # key + rim lights
    for name, rot, e in (("Key", (math.radians(50), 0, math.radians(-35)), 3.0), ("Fill", (math.radians(65), 0, math.radians(140)), 1.2),
                         ("Top", (0, 0, 0), 0.8)):
        ld = bpy.data.lights.new(name, 'SUN')
        ld.energy = e
        ld.angle = math.radians(8)
        lo = bpy.data.objects.new(name, ld)
        lo.rotation_euler = rot
        sc.collection.objects.link(lo)
    # ground
    bpy.ops.mesh.primitive_plane_add(size=12, location=(0, 0, -0.0005))
    g = bpy.context.active_object
    gm = bpy.data.materials.new("R1Ground")
    gm.use_nodes = True
    gm.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.25, 0.25, 0.26, 1)
    g.data.materials.append(gm)
    cam = bpy.data.cameras.new("R1Cam")
    co = bpy.data.objects.new("R1Cam", cam)
    sc.collection.objects.link(co)
    sc.camera = co


def render(path, loc, tgt, lens=45, ortho=None):
    sc = bpy.context.scene
    co = sc.camera
    co.location = Vector(loc)
    d = Vector(tgt) - Vector(loc)
    co.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()
    if ortho:
        co.data.type = 'ORTHO'
        co.data.ortho_scale = ortho
    else:
        co.data.type = 'PERSP'
        co.data.lens = lens
    co.data.clip_start = 0.01
    sc.render.filepath = path
    bpy.ops.render.render(write_still=True)
    print("rendered", path, flush=True)
