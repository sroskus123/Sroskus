// bake_navmesh.mjs -- design-time Recast navmesh validation for "Kalné Hamry" (IRON VALLEY).
// Input : Tools/level/_out/nav/nav_input.bin + nav_queries.json (written by export_navmesh_input.py from the level JSON)
// Output: Tools/level/_out/nav/nav_results.json (merged into Shared/level/layout.json by merge_nav.py)
// Settings = layout.ai_navigation.agent.recast: cs 0.05, ch 0.05, radius 7 cells (0.35 m = capsule), height 36 cells
// (1.80 m), climb 8 cells (0.40 m), slope 45 deg, 256-cell tiles (12.8 m).  WASM is used only here, in the build tool (ARCHITECTURE D4).
import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { init, NavMeshQuery } from 'recast-navigation';
import { generateTiledNavMesh } from 'recast-navigation/generators';

const HERE = dirname(fileURLToPath(import.meta.url));
const OUT = join(HERE, '..', '_out', 'nav');

const cfg = {
  cs: 0.05, ch: 0.05, walkableSlopeAngle: 45, walkableHeight: 36, walkableClimb: 8, walkableRadius: 7,
  tileSize: 256, maxEdgeLen: 240, maxSimplificationError: 1.1, minRegionArea: 16, mergeRegionArea: 40,
  maxVertsPerPoly: 6, detailSampleDist: 12, detailSampleMaxError: 1,
};

await init();
const t0 = Date.now();
const buf = readFileSync(join(OUT, 'nav_input.bin'));
const nv = buf.readUInt32LE(0);
const nt = buf.readUInt32LE(4);
const positions = new Float32Array(buf.buffer, buf.byteOffset + 8, nv * 3);
const indices = new Uint32Array(buf.buffer.slice(buf.byteOffset + 8 + nv * 12, buf.byteOffset + 8 + nv * 12 + nt * 12));
const pos = Float32Array.from(positions);
const Q = JSON.parse(readFileSync(join(OUT, 'nav_queries.json'), 'utf8'));

const res = generateTiledNavMesh(pos, indices, cfg);
if (!res.success) {
  console.error('navmesh generation failed', res.error);
  process.exit(2);
}
const navMesh = res.navMesh;
const tBake = (Date.now() - t0) / 1000;
const query = new NavMeshQuery(navMesh, { maxNodes: 65535 });
const toR = (p) => ({ x: p[0], y: p[2], z: -p[1] });
const dist = (a, b) => Math.hypot(a.x - b.x, a.y - b.y, a.z - b.z);
const hdist = (a, b) => Math.hypot(a.x - b.x, a.z - b.z);
const HALF = { x: 0.6, y: 1.2, z: 0.6 };

function pathLen(a, b) {
  const r = query.computePath(a, b, { halfExtents: HALF, maxPathPolys: 4096, maxStraightPathPoints: 4096 });
  if (!r.success || !r.path || r.path.length === 0) return { ok: false, len: Infinity };
  let L = 0;
  for (let i = 1; i < r.path.length; i++) L += dist(r.path[i - 1], r.path[i]);
  const end = r.path[r.path.length - 1];
  const reached = hdist(end, b) < 0.6 && Math.abs(end.y - b.y) < 1.0;
  return { ok: reached, len: reached ? L : Infinity, end, n: r.path.length };
}

function snapped(p) {
  const r = query.findClosestPoint(toR(p), { halfExtents: HALF });
  if (!r.success) return null;
  const d = hdist(r.point, toR(p));
  return d < 0.6 ? r.point : null;
}

// ---- entrances: reachable from the village square along the navmesh
const refP = snapped(Q.reference.pos);
const disconnected = [];
const entranceResults = [];
for (const e of Q.entrances) {
  const p = snapped(e.pos);
  if (!p) { disconnected.push(`${e.id} (no navmesh within 0.6 m)`); entranceResults.push({ id: e.id, ok: false }); continue; }
  const r = pathLen(refP, p);
  if (!r.ok) disconnected.push(`${e.id} (no path from the square)`);
  entranceResults.push({ id: e.id, ok: r.ok, path_m: Number.isFinite(r.len) ? +r.len.toFixed(2) : null });
}

// ---- spawn -> zone balance: per spawn point, shortest navmesh path to any zone target point (= zone edge distance)
const balance = {};
for (const [zid, targets] of Object.entries(Q.zones)) {
  const tg = targets.map((t) => snapped(t)).filter((t) => t);
  const teams = {};
  let unreachable = 0;
  for (const [team, pts] of Object.entries(Q.spawns)) {
    const vals = [];
    for (const sp of pts) {
      if (!sp.zones.includes(zid)) continue;
      const a = snapped(sp.pos);
      if (!a) { unreachable++; vals.push(null); continue; }
      // exact minimum over all targets, pruned by the straight-line lower bound
      const order = tg.map((t) => [dist(t, a), t]).sort((u, v) => u[0] - v[0]);
      let best = Infinity;
      for (const [lb, t] of order) {
        if (lb >= best) break;
        const r = pathLen(a, t);
        if (r.len < best) best = r.len;
      }
      if (!Number.isFinite(best)) unreachable++;
      vals.push(Number.isFinite(best) ? +best.toFixed(2) : null);
    }
    const fin = vals.filter((v) => v !== null);
    teams[team] = { mean_m: fin.length ? +(fin.reduce((s, v) => s + v, 0) / fin.length).toFixed(2) : null, points: vals };
  }
  const means = Object.values(teams).map((t) => t.mean_m).filter((v) => v !== null);
  const mx = Math.max(...means), mn = Math.min(...means);
  balance[zid] = { teams, max_over_min: +(mx / mn).toFixed(4), unreachable, run_time_s_3_5: [+(mn / 3.5).toFixed(1), +(mx / 3.5).toFixed(1)] };
}

// ---- navmesh statistics
let polys = 0, tiles = 0;
for (let i = 0; i < navMesh.getMaxTiles(); i++) {
  const tile = navMesh.getTile(i);
  if (!tile || !tile.header()) continue;
  tiles++;
  polys += tile.header().polyCount();
}
const out = {
  tool: 'recast-navigation 0.43.1 (Node ' + process.version + ')', config: { ...cfg, walkableRadius_cells: cfg.walkableRadius },
  input: { vertices: nv, triangles: nt }, bake_seconds: +tBake.toFixed(1), tiles, polys,
  disconnected_entrances: disconnected, entrances_checked: entranceResults.length, entrances: entranceResults, balance,
  method: 'Detour computePath (straight path length) from each active spawn point to every zone target point (2 m grid of '
    + 'walkable zone cells, exact minimum with straight-line pruning); a target counts as reached only when the path ends within 0.6 m of it; entrances are reached from the '
    + 'village square (0, 0, 0.30).',
};
writeFileSync(join(OUT, 'nav_results.json'), JSON.stringify(out, null, 1));
console.log(`baked ${tiles} tiles / ${polys} polys in ${tBake.toFixed(1)} s; entrances ${entranceResults.length - disconnected.length}/${entranceResults.length} connected`);
for (const [zid, b] of Object.entries(balance)) {
  console.log(zid, Object.fromEntries(Object.entries(b.teams).map(([t, v]) => [t, v.mean_m])), 'max/min', b.max_over_min, 'unreachable', b.unreachable);
}
if (disconnected.length) console.log('DISCONNECTED:', disconnected.join('; '));
