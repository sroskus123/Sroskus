#!/usr/bin/env python3
"""
run_pipeline.py -- regenerates and verifies the whole level data set of "Kalné Hamry" in the right order:

  1. build_level.py            -> Shared/level/layout.json, buildings.json, terrain_ref_0p5m.png
  2. nav/export_navmesh_input.py -> Tools/level/_out/nav/nav_input.bin + nav_queries.json
  3. node nav/bake_navmesh.mjs   -> Recast bake (cs 0.05, radius 7) + spawn->zone paths + entrance connectivity
  4. nav/merge_nav.py            -> layout.json navmesh_validation
  5. analyze_sightlines.py       -> Tools/level/_out/sightlines*.json (only with --sightlines)
  6. draw_plans.py               -> Docs/img/*.png + generated tables in Docs/MAP_DESIGN.md
  7. check_layout.py             -> exits non-zero on any violation

Usage: python3 Tools/level/run_pipeline.py [--skip-nav] [--skip-draw] [--sightlines]
Requires: Python 3.11 + numpy, scipy, shapely, matplotlib, scikit-fmm, scikit-image, pillow; Node >= 22 with
`npm install` done in Tools/level/nav (recast-navigation 0.43.1).
"""
import argparse
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))


def run(cmd, cwd=HERE):
    t0 = time.time()
    print(f"\n>>> {' '.join(cmd)}", flush=True)
    r = subprocess.run(cmd, cwd=cwd)
    print(f"<<< exit {r.returncode} ({time.time() - t0:.0f} s)", flush=True)
    return r.returncode


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-nav", action="store_true")
    ap.add_argument("--skip-draw", action="store_true")
    ap.add_argument("--sightlines", action="store_true", help="also run analyze_sightlines.py (hard geometry and + vegetation, ~2 min each)")
    a = ap.parse_args()
    py = sys.executable
    if run([py, "build_level.py"]):
        sys.exit("build failed")
    if not a.skip_nav:
        if run([py, os.path.join("nav", "export_navmesh_input.py")]):
            sys.exit("nav export failed")
        if run(["node", "--max-old-space-size=12000", "bake_navmesh.mjs"], cwd=os.path.join(HERE, "nav")):
            sys.exit("nav bake failed")
        if run([py, os.path.join("nav", "merge_nav.py")]):
            sys.exit("nav merge failed")
    if a.sightlines:
        run([py, "analyze_sightlines.py"])
        run([py, "analyze_sightlines.py", "--vegetation"])
    if not a.skip_draw:
        # drawings and the generated tables of Docs/MAP_DESIGN.md (incl. the sightline metrics) before the check:
        # check Q02 compares that document with the data
        run([py, "draw_plans.py"])
    rc = run([py, "check_layout.py"])
    sys.exit(rc)


if __name__ == "__main__":
    main()
