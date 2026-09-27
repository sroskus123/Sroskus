"""Toe crease test (re-imported FBX): ball_l dorsiflexion 40 deg (toe-off), ball_r plantarflexion 30."""
import math, numpy as np, bpy, importlib.util
from mathutils import Vector, Matrix
IV="/home/user/Sroskus/IronValley"; R1=IV+"/Art/Previews/_review/base/r1"
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.fbx(filepath=IV+"/Art/Export/FBX/SK_Human_Base.fbx")
arm=[o for o in bpy.data.objects if o.type=='ARMATURE'][0]; me=[o for o in bpy.data.objects if o.type=='MESH'][0]; MW=arm.matrix_world
def rot(n,axis,deg):
    bpy.context.view_layer.update(); pb=arm.pose.bones[n]; Mw=MW@pb.matrix; h=Mw.to_translation()
    pb.matrix=MW.inverted()@(Matrix.Translation(h)@Matrix.Rotation(math.radians(deg),4,Vector(axis).normalized())@Matrix.Translation(-h)@Mw)
    bpy.context.view_layer.update()
rot("ball_l",(1,0,0),40)    # toes up (tip moves +Z) for a -Y pointing toe: rotate about +X
rot("ball_r",(1,0,0),-30)
spec=importlib.util.spec_from_file_location("r1_render",R1+"/r1_render.py"); rr=importlib.util.module_from_spec(spec); spec.loader.exec_module(rr)
rr.setup_scene(me, samples=16)
bpy.data.objects["Plane"].hide_render=True
rr.render(R1+"/r1_toes_side_l.png",(0.75,-0.35,0.12),(0.2,-0.1,0.04),50)
rr.render(R1+"/r1_toes_top.png",(0.0,-0.55,0.55),(0.0,-0.12,0.03),40)
rr.render(R1+"/r1_toes_side_r.png",(-0.75,-0.35,0.12),(-0.2,-0.1,0.04),50)
