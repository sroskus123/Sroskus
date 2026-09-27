#!/usr/bin/env python3
"""
build_environment.py -- regenerates the whole map art of "Kalné Hamry" (phase 1: terrain materials and vegetation)
in the right order, deterministically (fixed seeds, no hand-edited outputs):

  1. Tools/environment/terrain_textures.py       -> Art/Textures/Environment/Terrain/<Set>/T_<Set>_*.png (+ JSON)
  2. Tools/environment/vegetation_textures.py    -> Art/Textures/Environment/Vegetation/* (bark, foliage / grass atlases)
  3. Tools/environment/pack_web_environment.py   -> Web/public/assets/environment/terrain/* (texture-array strips)
  4. Art/Source/Blender/environment/vegetation.py -> Web/public/assets/environment/vegetation.glb (trees, shrubs, LODs)
  5. Tools/level/export_web_level.py              -> kh_terrain.glb (splat weights, macro tint, grass density),
                                                    kh_world.glb (vegetation instance tables), kh_collision.glb
                                                    (unchanged), Web/src/data/kalne_hamry.json
  then: cd Web && npm run build (re-bakes the navmesh only if the collision changed; it does not)

Usage: python3 Tools/environment/build_environment.py [--skip-textures] [--skip-level] [--preview]
Needs Python 3.11 + numpy 1.26 (bpy 4.5 requires it), scipy, shapely, matplotlib, pillow (WebP), bpy 4.5.
"""
import argparse
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))


def run(cmd, cwd=ROOT):
    t0 = time.time()
    print(f"\n>>> {' '.join(cmd)}", flush=True)
    r = subprocess.run(cmd, cwd=cwd)
    print(f"<<< exit {r.returncode} ({time.time() - t0:.0f} s)", flush=True)
    if r.returncode:
        sys.exit(r.returncode)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-textures", action="store_true", help="reuse Art/Textures/Environment (steps 1-2)")
    ap.add_argument("--skip-level", action="store_true", help="do not re-export the level (step 5)")
    ap.add_argument("--preview", action="store_true", help="Cycles preview of the vegetation models")
    a = ap.parse_args()
    py = sys.executable
    if not a.skip_textures:
        run([py, os.path.join("Tools", "environment", "terrain_textures.py")])
        run([py, os.path.join("Tools", "environment", "vegetation_textures.py")])
    run([py, os.path.join("Tools", "environment", "pack_web_environment.py"), "--terrain-only"])
    veg = [py, os.path.join("Art", "Source", "Blender", "environment", "vegetation.py")]
    if a.preview:
        veg.append("--preview")
    run(veg)
    if not a.skip_level:
        run([py, "export_web_level.py"], cwd=os.path.join(ROOT, "Tools", "level"))
    print("\nnext: cd Web && npm run build && npm run test:unit && npm run test:e2e")


if __name__ == "__main__":
    main()
