# Copy of the R1 reviewer's script (Art/Previews/_review/base/r1/r1_finger_sections.py) with the output folder
# redirected to Art/Previews/HumanBase/r1_fix (re-verification of the R1 fixes). Measurement code unchanged.
"""Cross-sections of the left middle and index fingers (source .blend) through each joint centre,
plane normal = the segment direction; plotted with dorsal up and the joint marked in red."""
import numpy as np, bpy, bmesh
from mathutils import Vector
from PIL import Image, ImageDraw
IV="/home/user/Sroskus/IronValley"; R1="/home/user/Sroskus/IronValley/Art/Previews/HumanBase/r1_fix"; REV="/home/user/Sroskus/IronValley/Art/Previews/_review/base/r1"
bpy.ops.wm.open_mainfile(filepath=IV+"/Art/Source/Blender/characters/human_base.blend")
arm=bpy.data.objects["Armature"]; me=bpy.data.objects["SK_Human_Base"]; B=arm.data.bones
H=lambda n: arm.matrix_world @ B[n].head_local
T=lambda n: arm.matrix_world @ B[n].tail_local
w=H("hand_l"); m=H("middle_01_l"); d=(m-w).normalized()
r=H("index_01_l")-H("pinky_01_l"); r=(r-d*r.dot(d)).normalized(); p=d.cross(r).normalized()
base=bmesh.new(); base.from_mesh(me.data); base.transform(me.matrix_world)
img=Image.new("RGB",(1500,560),(250,250,250)); dr=ImageDraw.Draw(img)
sc=9000  # px per m
col=0
for f in ("index","middle"):
    for i in (1,2,3):
        n=f"{f}_{i:02d}_l"; j=H(n); ax=(T(n)-H(n)).normalized()
        bm=base.copy()
        res=bmesh.ops.bisect_plane(bm,geom=bm.verts[:]+bm.edges[:]+bm.faces[:],dist=1e-7,plane_co=j,plane_no=ax)
        edges=[e for e in res["geom_cut"] if isinstance(e,bmesh.types.BMEdge)]
        # local 2D frame: x = radial (r orthogonalised to ax), y = dorsal (-p orthogonalised)
        yd=(-p-ax*(-p).dot(ax)).normalized(); xr=yd.cross(ax).normalized()
        cx=130+col*245; cy=300
        # keep only edges of the loop nearest the joint
        segs=[]
        for e in edges:
            a,b=e.verts[0].co,e.verts[1].co
            if (a-j).length<0.02 and (b-j).length<0.02:
                segs.append(((a-j).dot(xr),(a-j).dot(yd),(b-j).dot(xr),(b-j).dot(yd)))
        ys=[s[1] for s in segs]+[s[3] for s in segs]
        for x1,y1,x2,y2 in segs:
            dr.line([(cx+x1*sc,cy-y1*sc),(cx+x2*sc,cy-y2*sc)],fill=(30,30,120),width=2)
        dr.ellipse([cx-5,cy-5,cx+5,cy+5],fill=(220,20,20))
        top=max(ys); bot=min(ys)
        dr.text((cx-60,40),f"{n}",fill=(0,0,0))
        dr.text((cx-80,60),f"dorsal {top*1000:.1f} mm",fill=(0,0,0))
        dr.text((cx-80,78),f"palmar {-bot*1000:.1f} mm",fill=(0,0,0))
        dr.text((cx-80,96),f"dorsal frac {top/(top-bot):.2f}",fill=(0,0,0))
        print(n, "dorsal mm", round(top*1000,1), "palmar mm", round(-bot*1000,1), "frac", round(top/(top-bot),2))
        bm.free(); col+=1
dr.text((20,520),"Sections perpendicular to each finger bone through its head (joint centre, red). Dorsal (back of hand) is UP. 10 mm = 90 px.",fill=(0,0,0))
dr.line([(1350,480),(1440,480)],fill=(0,0,0),width=3); dr.text((1360,490),"10 mm",fill=(0,0,0))
img.save(R1+"/r1_finger_joint_sections.png")
