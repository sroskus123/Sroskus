"""Compare posed vertex positions FBX vs GLB (same poses, same posing code). GLB verts are split at
UV seams: map each GLB vert to the FBX vert with the same REST position."""
import numpy as np, json, glob
import bpy
from mathutils.kdtree import KDTree
IV="/home/user/Sroskus/IronValley"; R1=IV+"/Art/Previews/_review/base/r1"
def rest(kind):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    if kind=="fbx": bpy.ops.import_scene.fbx(filepath=IV+"/Art/Export/FBX/SK_Human_Base.fbx")
    else: bpy.ops.import_scene.gltf(filepath=IV+"/Art/Export/GLB/Human_Base.glb")
    me=sorted([o for o in bpy.data.objects if o.type=='MESH'], key=lambda o:-len(o.data.vertices))[0]
    return np.array([me.matrix_world @ v.co for v in me.data.vertices])
F=rest("fbx"); G=rest("glb")
kd=KDTree(len(F))
for i,c in enumerate(F): kd.insert(c,i)
kd.balance()
mp=np.array([kd.find(c)[1] for c in G]); dd=np.array([kd.find(c)[2] for c in G])
out={"rest_map_max_dist_m":float(dd.max())}
for f in sorted(glob.glob(R1+"/r1_pose_*_fbx.npy")):
    p=f.split("r1_pose_")[1].rsplit("_fbx",1)[0]
    a=np.load(f); b=np.load(f.replace("_fbx.npy","_glb.npy"))
    out[p]={"max_abs_diff_m":float(np.abs(b-a[mp]).max()), "mean_diff_m":float(np.linalg.norm(b-a[mp],axis=1).mean())}
json.dump(out,open(R1+"/r1_glb_vs_fbx.json","w"),indent=1); print(json.dumps(out,indent=1))
