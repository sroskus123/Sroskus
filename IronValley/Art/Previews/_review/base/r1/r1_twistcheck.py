"""Verify the twist-bone claim on the re-imported FBX with own code: hand turned 80 deg about the
forearm axis; wrist-region mean radius (posed/rest) plain LBS vs lowerarm_twist_01 turned 40 deg."""
import math, numpy as np, bpy
from mathutils import Vector, Matrix
IV="/home/user/Sroskus/IronValley"
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.fbx(filepath=IV+"/Art/Export/FBX/SK_Human_Base.fbx")
arm=[o for o in bpy.data.objects if o.type=='ARMATURE'][0]; me=[o for o in bpy.data.objects if o.type=='MESH'][0]; MW=arm.matrix_world
def upd(): bpy.context.view_layer.update()
def reset():
    for pb in arm.pose.bones: pb.rotation_mode='QUATERNION'; pb.rotation_quaternion=(1,0,0,0)
    upd()
def rot(n,axis,deg):
    upd(); pb=arm.pose.bones[n]; Mw=MW@pb.matrix; h=Mw.to_translation()
    pb.matrix=MW.inverted()@(Matrix.Translation(h)@Matrix.Rotation(math.radians(deg),4,Vector(axis).normalized())@Matrix.Translation(-h)@Mw); upd()
def co():
    upd(); dg=bpy.context.evaluated_depsgraph_get(); ev=me.evaluated_get(dg); m=ev.to_mesh()
    c=np.array([me.matrix_world@v.co for v in m.vertices]); ev.to_mesh_clear(); return c
e=MW@arm.data.bones["lowerarm_l"].head_local; w=MW@arm.data.bones["hand_l"].head_local
ax=(w-e).normalized(); L=(w-e).length
reset(); c0=co()
E=np.array(e); A=np.array(ax)
def ring(c, frac):
    s0=(c0-E)@A
    sel=(np.abs(s0-frac*L)<0.008)&(np.linalg.norm(c0-E-np.outer(s0,A),axis=1)<0.06)
    r0=np.linalg.norm(c0[sel]-E-np.outer(s0[sel],A),axis=1).mean()
    s1=(c[sel]-E)@A
    r1=np.linalg.norm(c[sel]-E-np.outer(s1,A),axis=1).mean()
    return round(float(r1/r0),3)
for tw in (60,80):
    reset(); rot("hand_l",ax,tw); c1=co()
    rot("lowerarm_twist_01_l",ax,tw*0.5); c2=co()
    print(f"hand twist {tw}: ring@100% plain {ring(c1,1.0)} driven {ring(c2,1.0)} | @95% plain {ring(c1,0.95)} driven {ring(c2,0.95)} | @85% plain {ring(c1,0.85)} driven {ring(c2,0.85)} | @60% plain {ring(c1,0.6)} driven {ring(c2,0.6)}")
