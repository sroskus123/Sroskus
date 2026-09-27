import numpy as np, bpy, json
IV="/home/user/Sroskus/IronValley"; R1=IV+"/Art/Previews/_review/base/r1"
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.fbx(filepath=IV+"/Art/Export/FBX/SK_Human_Base.fbx")
me=[o for o in bpy.data.objects if o.type=='MESH'][0]
co=np.array([me.matrix_world @ v.co for v in me.data.vertices])
names=[g.name for g in me.vertex_groups]; W=np.zeros((len(co),len(names)))
for v in me.data.vertices:
    for g in v.groups: W[v.index,g.group]=g.weight
edges=np.array([e.vertices[:] for e in me.data.edges]); nb=[[] for _ in co]
for a,b in edges: nb[a].append(b); nb[b].append(a)
for bn in ("pelvis","spine_01"):
    j=names.index(bn); s=set(np.nonzero(W[:,j]>0.5)[0].tolist()); seen=set()
    for v in sorted(s):
        if v in seen: continue
        st=[v]; seen.add(v); comp=[]
        while st:
            x=st.pop(); comp.append(x)
            for y in nb[x]:
                if y in s and y not in seen: seen.add(y); st.append(y)
        c=co[comp].mean(0)
        # what dominates the ring around this island
        ring=set(y for x in comp for y in nb[x])-set(comp)
        rd={}
        for y in ring:
            k=names[int(W[y].argmax())]; rd[k]=rd.get(k,0)+1
        wv=[(names[k],round(float(W[comp[0],k]),3)) for k in np.argsort(W[comp[0]])[::-1][:4] if W[comp[0],k]>0]
        print(bn, "island size",len(comp),"centre",c.round(3).tolist(),"surrounding dominant:",rd,"weights of first vert:",wv)
