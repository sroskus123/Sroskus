"""R1 review: x-ray side view of the rest left hand (source .blend, read-only) with finger joint
centres as red spheres, viewed along the radial axis, to show the dorsal placement of the pivots."""
import math, numpy as np
import bpy
from mathutils import Vector

IV = "/home/user/Sroskus/IronValley"
R1 = IV + "/Art/Previews/_review/base/r1"
bpy.ops.wm.open_mainfile(filepath=IV + "/Art/Source/Blender/characters/human_base.blend")
arm = bpy.data.objects["Armature"]; me = bpy.data.objects["SK_Human_Base"]
B = arm.data.bones
H = lambda n: arm.matrix_world @ B[n].head_local
w = H("hand_l"); m = H("middle_01_l")
d = (m - w).normalized()
r = H("index_01_l") - H("pinky_01_l"); r = (r - d * r.dot(d)).normalized()
p = d.cross(r).normalized()          # palmar
sc = bpy.context.scene
for o in list(sc.objects):
    if o not in (me,):
        o.hide_render = True
sc.render.engine = 'CYCLES'; sc.cycles.device = 'CPU'; sc.cycles.samples = 16; sc.cycles.use_denoising = True
sc.render.threads_mode = 'FIXED'; sc.render.threads = 3
sc.render.resolution_x, sc.render.resolution_y = 1280, 720
sc.view_settings.view_transform = 'Standard'
world = bpy.data.worlds.new("W"); world.use_nodes = True
world.node_tree.nodes["Background"].inputs[0].default_value = (0.3, 0.31, 0.33, 1); sc.world = world
mat = bpy.data.materials.new("Xray"); mat.use_nodes = True
nt = mat.node_tree; nt.nodes.clear()
o_ = nt.nodes.new("ShaderNodeOutputMaterial"); tr = nt.nodes.new("ShaderNodeBsdfTransparent")
em = nt.nodes.new("ShaderNodeEmission"); em.inputs[0].default_value = (0.8, 0.8, 0.8, 1); em.inputs[1].default_value = 0.35
mix = nt.nodes.new("ShaderNodeMixShader"); mix.inputs[0].default_value = 0.35
lw = nt.nodes.new("ShaderNodeLayerWeight"); lw.inputs[0].default_value = 0.35
nt.links.new(lw.outputs["Facing"], mix.inputs[0])
nt.links.new(tr.outputs[0], mix.inputs[1]); nt.links.new(em.outputs[0], mix.inputs[2]); nt.links.new(mix.outputs[0], o_.inputs[0])
me.data.materials.clear(); me.data.materials.append(mat)
red = bpy.data.materials.new("Red"); red.use_nodes = True
rn = red.node_tree; rn.nodes.clear(); ro = rn.nodes.new("ShaderNodeOutputMaterial"); re_ = rn.nodes.new("ShaderNodeEmission")
re_.inputs[0].default_value = (1, 0.1, 0.05, 1); re_.inputs[1].default_value = 3; rn.links.new(re_.outputs[0], ro.inputs[0])
for f in ("index", "middle", "ring", "pinky"):
    for i in (1, 2, 3):
        bpy.ops.mesh.primitive_uv_sphere_add(radius=0.0018, location=H(f"{f}_{i:02d}_l"))
        s = bpy.context.active_object; s.data.materials.append(red); s.hide_render = False
# only the middle finger chain line (to show pivots vs finger outline)
cam = bpy.data.cameras.new("C"); co = bpy.data.objects.new("C", cam); sc.collection.objects.link(co); sc.camera = co
ctr = (w + m) * 0.5 + d * 0.05
loc = ctr - r * 0.40          # look from the ulnar (pinky) side along +r
co.location = loc
co.rotation_euler = (ctr - loc).to_track_quat('-Z', 'Y').to_euler()
cam.type = 'ORTHO'; cam.ortho_scale = 0.20
# rotate camera so that the hand axis d is horizontal
up = p
co.rotation_euler = (ctr - loc).to_track_quat('-Z', 'Y').to_euler()
from mathutils import Matrix
zc = (loc - ctr).normalized(); yc = (-p - zc * (-p).dot(zc)).normalized(); xc = yc.cross(zc)
Mrot = Matrix((xc, yc, zc)).transposed()
co.rotation_euler = Mrot.to_euler()
sc.render.filepath = R1 + "/r1_hand_xray_side_joints.png"
bpy.ops.render.render(write_still=True)
print("rendered")
