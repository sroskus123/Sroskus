#!/usr/bin/env python3
"""merge_nav.py -- inserts Tools/level/_out/nav/nav_results.json into Shared/level/layout.json as `navmesh_validation`.
The results carry the content hash of layout.json (without this key) + buildings.json taken at export time; check_layout.py
fails when the hash no longer matches (stale bake)."""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LEVEL = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, LEVEL)
import check_layout as C  # noqa: E402

res = json.load(open(os.path.join(LEVEL, "_out", "nav", "nav_results.json")))
q = json.load(open(os.path.join(LEVEL, "_out", "nav", "nav_queries.json")))
L = json.load(open(C.LAYOUT))
h = C.level_hash(L, json.load(open(C.BUILDINGS)))
if q.get("level_hash") != h:
    sys.exit(f"nav results were exported from a different level version ({q.get('level_hash')} != {h}); re-run export + bake")
slim = {k: v for k, v in res.items() if k != "entrances"}
slim["entrances_failed"] = [e for e in res["entrances"] if not e["ok"]]
for zid, b in slim["balance"].items():
    for t in b["teams"].values():
        t.pop("points", None)
slim["level_hash"] = h
slim["status"] = ("PASS" if not res["disconnected_entrances"] and all(b["max_over_min"] <= 1.06 and not b["unreachable"]
                                                                        for b in res["balance"].values()) else "FAIL")
slim["note"] = ("design-time validation bake from the level JSON proxy geometry (Tools/level/nav). The shipping navmesh is baked "
                "the same way from the generated collision meshes (ARCHITECTURE D4) and must reproduce these results.")
L["navmesh_validation"] = slim
json.dump(L, open(C.LAYOUT, "w"), ensure_ascii=False, indent=1)
print("merged navmesh_validation:", slim["status"], {k: v["max_over_min"] for k, v in slim["balance"].items()})
