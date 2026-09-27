"""Skeleton axes from the source .blend (authoritative tails/rolls): L/R mirror consistency of the
full bone frames, bone Y along the bone to child, finger flexion axes, root orientation, twist
bone alignment with the parent; plus UE4/UE5 mannequin name coverage."""
import numpy as np, bpy, json, math
IV="/home/user/Sroskus/IronValley"; R1=IV+"/Art/Previews/_review/base/r1"
bpy.ops.wm.open_mainfile(filepath=IV+"/Art/Source/Blender/characters/human_base.blend")
arm=bpy.data.objects["Armature"]; B=arm.data.bones
out={}
M=np.diag([-1,1,1])
pat=[]; worst=[]
for b in B:
    if not b.name.endswith("_l"): continue
    r=B[b.name[:-2]+"_r"]
    Rl=np.array(b.matrix_local.to_3x3()); Rr=np.array(r.matrix_local.to_3x3())
    # Blender symmetric convention: Rr = M Rl diag(1,1,-1)?? determine per-bone sign pattern
    Rm=M@Rl
    s=np.sign(np.einsum("ij,ij->j",Rm,Rr)).astype(int).tolist()
    err=float(np.abs(np.abs(np.einsum("ij,ij->j",Rm,Rr))-1).max())
    pat.append(tuple(s)); worst.append((b.name,round(err,5)))
out["mirror_axis_sign_patterns (x,y,z) counts"]={str(k):pat.count(k) for k in set(pat)}
out["mirror_frame_max_err_top"]=sorted(worst,key=lambda t:-t[1])[:5]
out["root_matrix_local"]=[[round(x,4) for x in row] for row in B["root"].matrix_local]
# twist bone axes vs parent
for s in "lr":
    for seg in ("upperarm","lowerarm"):
        t=B[f"{seg}_twist_01_{s}"]; p=B[f"{seg}_{s}"]
        out[f"{seg}_twist_01_{s}_vs_parent_axis_dot(x,y,z)"]=[round(float(np.dot(np.array(t.matrix_local.to_3x3())[:,k],np.array(p.matrix_local.to_3x3())[:,k])),4) for k in range(3)]
# elbow/knee hinge: is local X of lowerarm/calf the flexion axis (perp to plane of upper&lower)?
for s in "lr":
    for up,lo in (("upperarm","lowerarm"),("thigh","calf")):
        u=np.array(B[f"{up}_{s}"].tail_local-B[f"{up}_{s}"].head_local); f=np.array(B[f"{lo}_{s}"].tail_local-B[f"{lo}_{s}"].head_local)
        n=np.cross(u,f); n/=np.linalg.norm(n)
        X=np.array(B[f"{lo}_{s}"].matrix_local.to_3x3())[:,0]; Zz=np.array(B[f"{lo}_{s}"].matrix_local.to_3x3())[:,2]
        out[f"{lo}_{s}: |dot(localX, hinge_normal)| / |dot(localZ, hinge)|"]=[round(abs(float(X@n)),3),round(abs(float(Zz@n)),3)]
        out[f"{lo}_{s}: rest flexion deg"]=round(math.degrees(math.acos(np.dot(u,f)/np.linalg.norm(u)/np.linalg.norm(f))),2)
# knee: world X alignment of calf local X (hinge approx lateral)
for s in "lr":
    for n in ("thigh","calf","foot"):
        R=np.array(B[f"{n}_{s}"].matrix_local.to_3x3())
        out[f"{n}_{s} localX_world"]=R[:,0].round(3).tolist()
ue4=["root","pelvis","spine_01","spine_02","spine_03","clavicle_l","upperarm_l","lowerarm_l","hand_l","index_01_l","index_02_l","index_03_l","middle_01_l","middle_02_l","middle_03_l","pinky_01_l","pinky_02_l","pinky_03_l","ring_01_l","ring_02_l","ring_03_l","thumb_01_l","thumb_02_l","thumb_03_l","lowerarm_twist_01_l","upperarm_twist_01_l","clavicle_r","upperarm_r","lowerarm_r","hand_r","index_01_r","index_02_r","index_03_r","middle_01_r","middle_02_r","middle_03_r","pinky_01_r","pinky_02_r","pinky_03_r","ring_01_r","ring_02_r","ring_03_r","thumb_01_r","thumb_02_r","thumb_03_r","lowerarm_twist_01_r","upperarm_twist_01_r","neck_01","head","thigh_l","calf_l","calf_twist_01_l","foot_l","ball_l","thigh_twist_01_l","thigh_r","calf_r","calf_twist_01_r","foot_r","ball_r","thigh_twist_01_r","ik_foot_root","ik_foot_l","ik_foot_r","ik_hand_root","ik_hand_gun","ik_hand_l","ik_hand_r"]
names=[b.name for b in B]
out["UE4_mannequin_bones_missing"]=[n for n in ue4 if n not in names]
out["extra_bones_not_in_UE4"]=[n for n in names if n not in ue4]
json.dump(out,open(R1+"/r1_skeleton.json","w"),indent=1)
for k,v in out.items(): print(k,":",v)
