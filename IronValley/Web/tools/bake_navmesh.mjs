#!/usr/bin/env node
// Build-time navmesh bake (decision D4). WebAssembly (recast-navigation) is used ONLY here, in Node;
// the game runtime loads the resulting JSON with pure JS (three-pathfinding zone format +
// src/ai/nav/navMesh.js).
//
// For every level in src/data/*.json that has `nav.file`:
//   1. collision geometry of the level (src/level/levelGeometry.js, the same triangles as the BVH
//      collision world), without solids marked `"nav": false` (deliberately unknown obstacles);
//   2. Recast solo navmesh: agent radius 0.35 m, height 1.80 m, max climb 0.40 m, max slope 45 deg
//      (cell 0.05 m, like Shared/level/layout.json ai_navigation);
//   3. detail triangles -> three-pathfinding zone (Pathfinding.createZone), groups = connected parts;
//      the main group must contain every spawn point, zone centre and AI test point (build gate);
//   4. cover points from geometry: along navmesh boundary edges next to obstacles, normal pointing away
//      from the obstacle, low/high by measured obstacle height, peek side for high cover, filtered by
//      reachability (main group) and spacing;
//   5. writes public/<nav.file> (deterministic, no timestamps). A cache key (hash of level, config and
//      this tool's source) skips the bake when nothing changed; --force re-bakes, --check fails if stale.
//
// Usage: node tools/bake_navmesh.mjs [--level <id>] [--force] [--check] [--quiet]

import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { BufferGeometry, Float32BufferAttribute, Vector3 } from 'three';
import { Pathfinding } from 'three-pathfinding/dist/three-pathfinding.modern.mjs';
import { buildLevelSolids } from '../src/level/levelGeometry.js';
import { loadGeometryCollision } from '../src/level/levelAssets.js';
import { CollisionWorld } from '../src/physics/collisionWorld.js';
import { NavMeshData } from '../src/ai/nav/navMesh.js';
import { pointInPolygonXZ, pointInZone } from '../src/game/zoneShape.js';

const here = path.dirname(fileURLToPath(import.meta.url));
const webRoot = path.resolve(here, '..');
const dataDir = path.join(webRoot, 'src', 'data');
const publicDir = path.join(webRoot, 'public');

const args = process.argv.slice(2);
const opt = (name) => args.includes(name);
const optVal = (name) => {
  const i = args.indexOf(name);
  return i >= 0 ? args[i + 1] : null;
};
const FORCE = opt('--force');
const CHECK = opt('--check');
const QUIET = opt('--quiet');
const ONLY = optVal('--level');
const log = (...a) => {
  if (!QUIET) console.log(...a);
};

export const AGENT = { radius: 0.35, height: 1.8, maxClimb: 0.4, maxSlopeDeg: 45 };
const CS = 0.05;
const CH = 0.05;
export const RECAST_CONFIG = {
  cs: CS,
  ch: CH,
  walkableSlopeAngle: AGENT.maxSlopeDeg,
  walkableHeight: Math.ceil(AGENT.height / CH), // 36 cells
  walkableClimb: Math.floor(AGENT.maxClimb / CH), // 8 cells
  walkableRadius: Math.ceil(AGENT.radius / CS), // 7 cells
  maxEdgeLen: 240,
  maxSimplificationError: 1.1,
  minRegionArea: 16,
  mergeRegionArea: 40,
  maxVertsPerPoly: 6,
  detailSampleDist: 6, // world units; coarse on purpose: flat graybox floors + stair ramps need no height detail
  detailSampleMaxError: 1,
  borderSize: 0,
};

export const COVER_CONFIG = {
  sampleStep: 0.5, // spacing of samples along boundary edges (m)
  probeHeight: 0.5, // height of the first obstacle probe above the floor
  probeReach: 0.75, // obstacle must be this close to the navmesh boundary (radius 0.35 + margin)
  heights: [0.3, 0.6, 0.9, 1.1, 1.3, 1.5, 1.7, 1.9, 2.1], // obstacle height probes
  lowMinTop: 0.9, // top of a usable low obstacle (crouched body hidden)
  highMinTop: 1.7, // blocks a standing eye (1.65 m) -> high cover
  peekOffset: 0.8, // lateral step from a high cover point to the peek position
  spacing: 1.1, // minimal distance between cover points with a similar normal
  spacingAny: 0.7, // minimal distance between any two cover points
  maxEdgeSlopeY: 0.3, // boundary samples on stairs/ramps (steep edge) are skipped
};

function sha(s) {
  return createHash('sha256').update(s).digest('hex').slice(0, 16);
}

function round(v, d = 3) {
  const f = 10 ** d;
  return Math.round(v * f) / f;
}

/** Geometry solids of a generated level (GLB files under public/), read from disk. */
export async function levelGeometrySolids(level) {
  if (!level.geometry) return { solids: [], surfaceRaster: null };
  return loadGeometryCollision(level, (p) => readFileSync(path.join(publicDir, p)));
}

/**
 * Triangle soup of the level collision geometry, without solids marked nav: false. Generated levels add their GLB
 * geometry (`extraSolids`); terrain triangles outside `geometry.navClip` (the soft boundary 1 m inwards) are left out,
 * so bots never plan a path out of bounds.
 */
export function levelNavInput(level, extraSolids = []) {
  const skip = new Set(level.solids.filter((s) => s.nav === false).map((s) => s.id));
  const solids = [...buildLevelSolids(level), ...extraSolids];
  const navSolids = solids.filter((s) => s.collide !== false && s.nav !== false && !skip.has(s.parent) && !skip.has(s.id));
  const clip = level.geometry && Array.isArray(level.geometry.navClip) ? level.geometry.navClip : null;
  let count = 0;
  const keep = new Map();
  for (const s of navSolids) {
    const p = s.geometry.getAttribute('position');
    if (clip && s.terrain) {
      const arr = p.array;
      const mask = new Uint8Array(p.count / 3);
      let n = 0;
      for (let t = 0; t < p.count / 3; t++) {
        const cx = (arr[t * 9] + arr[t * 9 + 3] + arr[t * 9 + 6]) / 3;
        const cz = (arr[t * 9 + 2] + arr[t * 9 + 5] + arr[t * 9 + 8]) / 3;
        if (pointInPolygonXZ(clip, cx, cz)) {
          mask[t] = 1;
          n++;
        }
      }
      keep.set(s, mask);
      count += n * 3;
    } else count += p.count;
  }
  const positions = new Float32Array(count * 3);
  let o = 0;
  for (const s of navSolids) {
    const p = s.geometry.getAttribute('position');
    const mask = keep.get(s);
    if (mask) {
      for (let t = 0; t < mask.length; t++) {
        if (!mask[t]) continue;
        positions.set(p.array.subarray(t * 9, t * 9 + 9), o * 3);
        o += 3;
      }
      continue;
    }
    positions.set(p.array.subarray(0, p.count * 3), o * 3);
    o += p.count;
  }
  // BoxGeometry winding is outward (CCW seen from outside): Recast rasterizes both windings the same
  // for walkability by slope, so indices are straight.
  const indices = new Uint32Array(count);
  for (let i = 0; i < count; i++) indices[i] = i;
  return { positions, indices, solids, skipped: [...skip] };
}

function zoneToJson(zone) {
  const vertices = [];
  for (const v of zone.vertices) vertices.push(round(v.x, 3), round(v.y, 3), round(v.z, 3));
  const groups = zone.groups.map((g) =>
    g.map((n) => ({
      id: n.id,
      neighbours: n.neighbours,
      vertexIds: n.vertexIds,
      centroid: [round(n.centroid.x, 3), round(n.centroid.y, 3), round(n.centroid.z, 3)],
      portals: n.portals,
    })),
  );
  return { vertices, groups };
}

/** Required reachable points (spawns, zone centres, AI test points) as Vector3 with labels. */
function requiredPoints(level) {
  const out = [];
  const m = level.match || {};
  (m.teamSpawns || []).forEach((list, t) => list.forEach((s, i) => out.push({ label: `spawn team ${t} #${i}`, p: new Vector3().fromArray(s.pos) })));
  // a zone centre may be occupied by cover (the arena's centre pillar): accept navmesh within 2 m
  for (const z of m.zones || []) {
    // polygon zones: the zone QA centre point (on the floor / ground) when the level lists one
    const qa = (level.qaPoints || []).find((q) => q.id === `QA_${z.id}_center`);
    out.push({ label: `zone ${z.id}`, p: new Vector3().fromArray(qa ? qa.pos : z.center), maxDist: 2.0 });
  }
  const t = level.aiTest || {};
  const add = (label, arr) => {
    if (Array.isArray(arr) && arr.length === 3 && arr.every(Number.isFinite)) out.push({ label, p: new Vector3().fromArray(arr) });
  };
  if (t.blocked) {
    add('aiTest.blocked.start', t.blocked.start);
    add('aiTest.blocked.goal', t.blocked.goal);
  }
  (t.upstairs || []).forEach((p, i) => add(`aiTest.upstairs[${i}]`, p));
  for (const r of (t.crossing && t.crossing.routes) || []) {
    add(`route ${r.name} from`, r.from);
    add(`route ${r.name} to`, r.to);
  }
  return out;
}

/** Cover points from geometry along the main group's boundary edges. */
export function generateCover(nav, world, cfg = COVER_CONFIG, { excludeSolids = [] } = {}) {
  const exclude = new Set(excludeSolids);
  const edges = nav.boundaryEdges(nav.mainGroup);
  const V = nav.vertices;
  const candidates = [];
  const origin = new Vector3();
  const dir = new Vector3();
  const p = new Vector3();
  for (const e of edges) {
    const a = V[e.a];
    const b = V[e.b];
    const c = V[e.c];
    const ex = b.x - a.x;
    const ez = b.z - a.z;
    const len = Math.hypot(ex, ez);
    if (len < 0.2) continue;
    if (Math.abs(b.y - a.y) / len > cfg.maxEdgeSlopeY) continue;
    // outward normal in XZ: perpendicular pointing away from the triangle's third vertex
    let nx = ez / len;
    let nz = -ex / len;
    const mx = (a.x + b.x) / 2;
    const mz = (a.z + b.z) / 2;
    if (nx * (c.x - mx) + nz * (c.z - mz) > 0) {
      nx = -nx;
      nz = -nz;
    }
    const n = Math.max(1, Math.round(len / cfg.sampleStep));
    for (let k = 0; k < n; k++) {
      const t = (k + 0.5) / n;
      p.set(a.x + ex * t, a.y + (b.y - a.y) * t, a.z + ez * t);
      // obstacle directly outside the boundary?
      origin.set(p.x, p.y + cfg.probeHeight, p.z);
      dir.set(nx, 0, nz);
      const hit = world.raycast(origin, dir, cfg.probeReach);
      if (!hit || Math.abs(hit.normal.y) > 0.3) continue;
      if (exclude.has(hit.parent) || exclude.has(hit.solidId)) continue;
      // cover normal = obstacle face normal (horizontal), pointing away from the obstacle
      const hn = new Vector3(hit.normal.x, 0, hit.normal.z).normalize();
      const toward = hn.clone().negate();
      const reach = hit.distance + 0.25;
      let top = 0;
      for (const h of cfg.heights) {
        origin.set(p.x, p.y + h, p.z);
        if (world.raycast(origin, toward, reach)) top = h;
        else break;
      }
      if (top < cfg.lowMinTop) continue;
      // window: blocked below the sill, open above it, blocked again above the opening
      let window = false;
      if (top < cfg.highMinTop) {
        origin.set(p.x, p.y + 2.3, p.z);
        window = !!world.raycast(origin, toward, reach);
      }
      const height = top >= cfg.highMinTop ? 'high' : 'low';
      candidates.push({ pos: p.clone(), normal: hn, height, top, window, node: e.node, solid: hit.parent });
    }
  }
  // peek sides for high cover: is the obstacle still there 0.6 m to the left/right?
  const right = new Vector3();
  const q = new Vector3();
  for (const cp of candidates) {
    cp.peek = 'none';
    cp.peekPos = null;
    if (cp.height !== 'high') continue;
    // facing = normal (away from cover); right = (-fz, fx)
    right.set(-cp.normal.z, 0, cp.normal.x);
    const toward = cp.normal.clone().negate();
    const openSide = (sign) => {
      q.copy(cp.pos).addScaledVector(right, sign * 0.6);
      origin.set(q.x, q.y + 1.5, q.z);
      return !world.raycast(origin, toward, 0.9);
    };
    const r = openSide(1);
    const l = openSide(-1);
    cp.peek = r && l ? 'both' : r ? 'right' : l ? 'left' : 'none';
    if (cp.peek !== 'none') {
      const s = cp.peek === 'left' ? -1 : 1;
      const pp = cp.pos.clone().addScaledVector(right, s * COVER_CONFIG.peekOffset).addScaledVector(cp.normal, 0.1);
      const cl = nav.closestPoint(pp, { maxDist: 0.6, group: nav.mainGroup });
      if (cl && nav.segmentOnMesh(cp.pos, cl.point, { group: nav.mainGroup })) cp.peekPos = cl.point.clone();
    }
  }
  // spacing: deterministic order (x, z), keep a point if no kept point is too close
  candidates.sort((u, v) => u.pos.x - v.pos.x || u.pos.z - v.pos.z || u.pos.y - v.pos.y);
  const kept = [];
  // prefer points with a peek position / window (more useful), then low cover
  const rank = (cp) => (cp.peekPos ? 0 : cp.window ? 1 : cp.height === 'low' ? 2 : 3);
  const ordered = [...candidates].sort((u, v) => rank(u) - rank(v));
  for (const cp of ordered) {
    let ok = true;
    for (const k of kept) {
      const d = Math.hypot(k.pos.x - cp.pos.x, k.pos.z - cp.pos.z);
      if (Math.abs(k.pos.y - cp.pos.y) > 1.5) continue;
      if (d < cfg.spacingAny || (d < cfg.spacing && k.normal.dot(cp.normal) > 0.5)) {
        ok = false;
        break;
      }
    }
    if (!ok) continue;
    // the capsule must stand here: point on the main group
    if (nav.nodeAt(cp.pos, { group: nav.mainGroup }) < 0) continue;
    kept.push(cp);
  }
  kept.sort((u, v) => u.pos.x - v.pos.x || u.pos.z - v.pos.z || u.pos.y - v.pos.y);
  // points lie on the navmesh border: move them 2 cm inwards (along the normal) and keep only those that
  // are still inside the main group after rounding to millimetres (what the runtime loads)
  const inside = [];
  for (const cp of kept) {
    cp.pos.addScaledVector(cp.normal, 0.02);
    const r = new Vector3(round(cp.pos.x), round(cp.pos.y), round(cp.pos.z));
    if (nav.nodeAt(r, { group: nav.mainGroup }) >= 0) inside.push(cp);
  }
  return inside.map((cp, i) => ({
    id: `cv${String(i).padStart(3, '0')}`,
    pos: [round(cp.pos.x), round(cp.pos.y), round(cp.pos.z)],
    normal: [round(cp.normal.x, 4), 0, round(cp.normal.z, 4)],
    height: cp.height,
    top: cp.top,
    window: cp.window,
    peek: cp.peek,
    peekPos: cp.peekPos ? [round(cp.peekPos.x), round(cp.peekPos.y), round(cp.peekPos.z)] : null,
    solid: cp.solid,
  }));
}

/**
 * Design cover points of a generated level (level.cover, from layout.json cover_points: objects, furniture inside
 * buildings, window firing positions, stair watch) snapped onto the main navmesh group; points closer than
 * `spacing` to an already kept point are dropped.
 */
export function designCover(level, nav, existing, spacing = 0.7) {
  const out = [];
  const kept = existing.map((c) => ({ x: c.pos[0], y: c.pos[1], z: c.pos[2] }));
  let dropped = 0;
  for (const cp of level.cover || []) {
    const p = new Vector3().fromArray(cp.pos);
    const cl = nav.closestPoint(p, { maxDist: 0.45, group: nav.mainGroup });
    if (!cl || Math.abs(cl.point.y - p.y) > 0.6) {
      dropped++;
      continue;
    }
    const q = cl.point;
    if (kept.some((k) => Math.hypot(k.x - q.x, k.z - q.z) < spacing && Math.abs(k.y - q.y) < 1.5)) {
      dropped++;
      continue;
    }
    kept.push({ x: q.x, y: q.y, z: q.z });
    const high = cp.height === 'high';
    out.push({
      id: `d_${cp.id}`,
      pos: [round(q.x), round(q.y), round(q.z)],
      normal: [round(cp.normal[0], 4), 0, round(cp.normal[2], 4)],
      height: high ? 'high' : 'low',
      top: high ? 2.0 : cp.height === 'window' ? 1.0 : 1.0,
      window: cp.kind === 'window' || cp.height === 'window',
      peek: cp.peek || 'none',
      peekPos: null,
      solid: null,
      kind: cp.kind,
    });
  }
  return { points: out, dropped };
}

/** Spawn -> zone reachability on the baked navmesh for every team and zone (generated levels). */
export function spawnZoneReachability(level, nav) {
  const m = level.match || {};
  const out = {};
  const rules = JSON.parse(readFileSync(path.join(webRoot, '..', 'Shared', 'config', 'rules.json'), 'utf8'));
  const teamIds = rules.teams.list.map((t) => t.id);
  for (const z of m.zones || []) {
    const qa = (level.qaPoints || []).find((q) => q.id === `QA_${z.id}_center`);
    const goal = nav.closestPoint(new Vector3().fromArray(qa ? qa.pos : z.center), { maxDist: 2.5, group: nav.mainGroup });
    const res = {};
    (m.teamSpawns || []).forEach((list, t) => {
      const pts = list.filter((s) => !Array.isArray(s.zones) || s.zones.includes(z.id));
      const lens = [];
      let fail = 0;
      for (const sp of pts) {
        const a = nav.closestPoint(new Vector3().fromArray(sp.pos), { maxDist: 0.8, group: nav.mainGroup });
        if (!a || !goal) {
          fail++;
          continue;
        }
        const corridor = nav.searchNodes(a.node, a.point, goal.node, goal.point, { maxExpand: 400000 });
        if (!corridor) {
          fail++;
          continue;
        }
        const pl = nav.stringPull(corridor, a.point, goal.point);
        let L = 0;
        for (let i = 1; i < pl.length; i++) L += pl[i].distanceTo(pl[i - 1]);
        lens.push(L);
      }
      res[teamIds[t] || `team${t}`] = { points: pts.length, reachable: lens.length, unreachable: fail, meanPathM: lens.length ? round(lens.reduce((u, v) => u + v, 0) / lens.length, 1) : null };
    });
    const means = Object.values(res).map((r) => r.meanPathM).filter((v) => v !== null);
    out[z.id] = { goalOnMesh: !!goal, teams: res, maxOverMin: means.length ? round(Math.max(...means) / Math.min(...means), 3) : null, inZoneGoal: goal ? pointInZone(goal.point, z) : false };
  }
  return out;
}

/**
 * Welds the per-tile navmesh triangles into one mesh (tiled bakes of large maps): vertices with the same XZ
 * (2 mm) and a height difference below `dyWeld` become one vertex (neighbouring tiles sample the border height
 * independently), and triangle edges on tile borders are split at the border vertices of the neighbouring tile
 * (T-junctions), so three-pathfinding finds the shared edges (portals) across tile borders.
 * @returns {{ positions: Float32Array, indices: Uint32Array, welded: number, splits: number }}
 */
export function stitchTiles(pos, idx, { dyWeld = 0.3, tileWorld = null, origin = null } = {}) {
  const q = 500; // 2 mm
  const verts = [];
  const bucket = new Map();
  const remap = new Int32Array(pos.length / 3);
  let welded = 0;
  for (let i = 0; i < pos.length / 3; i++) {
    const x = pos[i * 3];
    const y = pos[i * 3 + 1];
    const z = pos[i * 3 + 2];
    const k = `${Math.round(x * q)},${Math.round(z * q)}`;
    let list = bucket.get(k);
    if (!list) {
      list = [];
      bucket.set(k, list);
    }
    let found = -1;
    for (const vi of list) {
      if (Math.abs(verts[vi][1] - y) < dyWeld) {
        found = vi;
        break;
      }
    }
    if (found >= 0) {
      if (Math.abs(verts[found][1] - y) > 1e-4) welded++;
      remap[i] = found;
    } else {
      verts.push([x, y, z]);
      list.push(verts.length - 1);
      remap[i] = verts.length - 1;
    }
  }
  let tris = [];
  for (let t = 0; t < idx.length; t += 3) {
    const a = remap[idx[t]];
    const b = remap[idx[t + 1]];
    const c = remap[idx[t + 2]];
    if (a === b || b === c || a === c) continue;
    tris.push([a, b, c]);
  }
  // T-junctions on tile borders: vertices lying inside another triangle's border edge split that triangle
  let splits = 0;
  if (tileWorld && origin) {
    const onLine = (v, ax) => {
      const f = (v - origin[ax]) / tileWorld;
      return Math.abs(f - Math.round(f)) * tileWorld < 2e-3;
    };
    // border vertices indexed by (axis, line index)
    const lines = new Map();
    verts.forEach((v, i) => {
      for (const ax of [0, 2]) {
        if (!onLine(v[ax], ax)) continue;
        const key = `${ax}:${Math.round((v[ax] - origin[ax]) / tileWorld)}`;
        if (!lines.has(key)) lines.set(key, []);
        lines.get(key).push(i);
      }
    });
    for (const list of lines.values()) list.sort((i, j) => verts[i][0] + verts[i][2] - verts[j][0] - verts[j][2]);
    const findSplit = (a, b) => {
      for (const ax of [0, 2]) {
        if (!onLine(verts[a][ax], ax) || !onLine(verts[b][ax], ax)) continue;
        if (Math.abs(verts[a][ax] - verts[b][ax]) > 2e-3) continue;
        const key = `${ax}:${Math.round((verts[a][ax] - origin[ax]) / tileWorld)}`;
        const o = ax === 0 ? 2 : 0;
        const lo = Math.min(verts[a][o], verts[b][o]);
        const hi = Math.max(verts[a][o], verts[b][o]);
        for (const vi of lines.get(key) || []) {
          if (vi === a || vi === b) continue;
          const v = verts[vi];
          if (v[o] <= lo + 2e-3 || v[o] >= hi - 2e-3) continue;
          const t = (v[o] - verts[a][o]) / (verts[b][o] - verts[a][o]);
          const y = verts[a][1] + (verts[b][1] - verts[a][1]) * t;
          if (Math.abs(v[1] - y) > dyWeld) continue;
          return vi;
        }
      }
      return null;
    };
    const out = [];
    const stack = tris.slice().reverse();
    while (stack.length) {
      const tr = stack.pop();
      let done = true;
      for (let e = 0; e < 3; e++) {
        const a = tr[e];
        const b = tr[(e + 1) % 3];
        const c = tr[(e + 2) % 3];
        const sv = findSplit(a, b);
        if (sv !== null) {
          splits++;
          // (a, s, c) and (s, b, c) keep the winding of (a, b, c)
          stack.push([a, sv, c], [sv, b, c]);
          done = false;
          break;
        }
      }
      if (done) out.push(tr);
    }
    tris = out;
  }
  const positions = new Float32Array(verts.length * 3);
  verts.forEach((v, i) => positions.set(v, i * 3));
  const indices = new Uint32Array(tris.length * 3);
  tris.forEach((t, i) => indices.set(t, i * 3));
  return { positions, indices, welded, splits };
}

export async function bakeLevel(level, { recast } = {}) {
  const { init, getNavMeshPositionsAndIndices } = recast || (await import('recast-navigation'));
  const { generateSoloNavMesh, generateTiledNavMesh } = await import('recast-navigation/generators');
  await init();
  const t0 = Date.now();
  const geo = await levelGeometrySolids(level);
  const input = levelNavInput(level, geo.solids);
  // small levels: one solo navmesh; large maps (e.g. 350 x 350 m) would exceed a single heightfield at
  // cs 0.05 m, so they are baked in 12.8 m tiles (256 cells) like Tools/level/nav
  let minX = Infinity;
  let maxX = -Infinity;
  let minZ = Infinity;
  let maxZ = -Infinity;
  for (let i = 0; i < input.positions.length; i += 3) {
    minX = Math.min(minX, input.positions[i]);
    maxX = Math.max(maxX, input.positions[i]);
    minZ = Math.min(minZ, input.positions[i + 2]);
    maxZ = Math.max(maxZ, input.positions[i + 2]);
  }
  const tiled = Math.max(maxX - minX, maxZ - minZ) > 120;
  const res = tiled ? generateTiledNavMesh(input.positions, input.indices, { ...RECAST_CONFIG, tileSize: 256 }) : generateSoloNavMesh(input.positions, input.indices, RECAST_CONFIG);
  if (!res.success) throw new Error(`Recast failed for ${level.id}: ${res.error}`);
  let [pos, idx] = getNavMeshPositionsAndIndices(res.navMesh);
  res.navMesh.destroy();
  let stitch = null;
  if (tiled) {
    const origin = [minX, 0, minZ];
    stitch = stitchTiles(pos, idx, { tileWorld: 256 * CS, origin });
    pos = stitch.positions;
    idx = stitch.indices;
  }
  const geom = new BufferGeometry();
  geom.setAttribute('position', new Float32BufferAttribute(pos, 3));
  geom.setIndex(Array.from(idx));
  const zone = Pathfinding.createZone(geom, 1e-3);
  const zoneJson = zoneToJson(zone);

  // main group: the group containing every required point
  const tmpNav = new NavMeshData({ zone: zoneJson, mainGroup: 0 });
  const req = requiredPoints(level);
  const counts = new Map();
  const unresolved = [];
  for (const r of req) {
    const md = r.maxDist ?? 0.8;
    const cl = tmpNav.closestPoint(r.p, { maxDist: md });
    if (!cl) {
      unresolved.push(`${r.label} (no navmesh within ${md} m)`);
      continue;
    }
    r.group = tmpNav.nodes[cl.node].group;
    counts.set(r.group, (counts.get(r.group) || 0) + 1);
  }
  let mainGroup = 0;
  let best = -1;
  for (const [g, c] of counts) {
    if (c > best) {
      best = c;
      mainGroup = g;
    }
  }
  for (const r of req) if (r.group !== undefined && r.group !== mainGroup) unresolved.push(`${r.label} (not connected to the main navmesh)`);
  // the gate is strict for levels that declare a nav block (AI test maps); for other levels it warns so a
  // layout change elsewhere never blocks the build (the navmesh is still written, bots may not reach it)
  const warnings = [];
  if (unresolved.length) {
    const msg = `navmesh gate failed for ${level.id}:\n  ${unresolved.join('\n  ')}`;
    if (level.nav) throw new Error(msg);
    warnings.push(...unresolved);
    console.warn(`nav: WARNING ${msg}`);
  }

  const nav = new NavMeshData({ zone: zoneJson, mainGroup });
  const world = new CollisionWorld(input.solids);
  const geoCoverAll = generateCover(nav, world, COVER_CONFIG, { excludeSolids: (level.nav && level.nav.coverExcludeSolids) || [] });
  // design cover points (generated levels) take precedence; geometry points closer than 0.7 m to one are dropped
  const dc = level.cover ? designCover(level, nav, []) : { points: [], dropped: 0 };
  const geoCover = dc.points.length
    ? geoCoverAll.filter((g) => !dc.points.some((d) => Math.hypot(d.pos[0] - g.pos[0], d.pos[2] - g.pos[2]) < 0.7 && Math.abs(d.pos[1] - g.pos[1]) < 1.5))
    : geoCoverAll;
  const cover = [...geoCover, ...dc.points];
  const reach = level.geometry ? spawnZoneReachability(level, nav) : null;
  const tBake = (Date.now() - t0) / 1000;
  const groupSizes = zoneJson.groups.map((g) => g.length);
  let area = 0;
  for (const n of nav.groups[mainGroup]) {
    const [a, b, c] = nav.triangle(n.index);
    area += Math.abs((b.x - a.x) * (c.z - a.z) - (c.x - a.x) * (b.z - a.z)) / 2;
  }
  return {
    schema: 'ironvalley.nav/1',
    level: level.id,
    tool: 'tools/bake_navmesh.mjs (recast-navigation 0.43.1 solo navmesh, three-pathfinding 1.3.0 zone)',
    agent: AGENT,
    recast: RECAST_CONFIG,
    coverConfig: COVER_CONFIG,
    skippedSolids: input.skipped,
    tiled,
    stitch: stitch ? { welded: stitch.welded, splits: stitch.splits } : null,
    warnings,
    stats: {
      inputTriangles: input.indices.length / 3,
      triangles: nav.nodes.length,
      groups: groupSizes.length,
      mainGroupTriangles: groupSizes[mainGroup],
      mainGroupAreaM2: round(area, 1),
      coverPoints: cover.length,
      coverLow: cover.filter((c) => c.height === 'low').length,
      coverHigh: cover.filter((c) => c.height === 'high').length,
      coverWindow: cover.filter((c) => c.window).length,
      coverWithPeek: cover.filter((c) => c.peekPos).length,
      coverDesign: dc.points.length,
      coverDesignDropped: dc.dropped,
      requiredPointsChecked: req.length,
      bakeSeconds: round(tBake, 2),
    },
    mainGroup,
    reachability: reach,
    zone: zoneJson,
    cover,
  };
}

function levelsWithNav() {
  const out = [];
  for (const f of readdirSync(dataDir).sort()) {
    if (!f.endsWith('.json')) continue;
    let j;
    try {
      j = JSON.parse(readFileSync(path.join(dataDir, f), 'utf8'));
    } catch {
      continue;
    }
    if (!j || !Array.isArray(j.solids) || typeof j.id !== 'string') continue;
    // every level with bots (match block) or an explicit nav block gets a navmesh
    const navFile = j.nav && typeof j.nav.file === 'string' ? j.nav.file : j.match ? `assets/nav/${j.id}.json` : null;
    if (navFile) out.push({ file: f, level: j, navFile });
  }
  return out;
}

async function main() {
  const toolSrc = readFileSync(fileURLToPath(import.meta.url), 'utf8');
  let stale = 0;
  let baked = 0;
  const registry = [];
  for (const { file, level, navFile } of levelsWithNav()) {
    // large generated levels load their navmesh at runtime (level.nav.external) instead of bundling it
    if (!(level.nav && level.nav.external)) registry.push({ id: level.id, navFile });
    if (ONLY && level.id !== ONLY) continue;
    const out = path.join(publicDir, navFile);
    // cache key: the actual collision geometry (all solids, incl. nav: false ones used for cover rays),
    // the level data the bake reads, and this tool's source
    const geo = createHash('sha256');
    for (const sd of buildLevelSolids(level)) {
      geo.update(`${sd.id}|${sd.parent}|${sd.collide}|`);
      geo.update(Buffer.from(sd.geometry.getAttribute('position').array.buffer));
    }
    const key = sha(geo.digest('hex') + JSON.stringify(level.solids.map((x) => [x.id, x.nav])) + JSON.stringify(level.match || null) + JSON.stringify(level.nav || null) + JSON.stringify(level.aiTest || null) + JSON.stringify(level.geometry ? { files: level.geometry.files, navClip: level.geometry.navClip } : null) + JSON.stringify(level.cover || null) + toolSrc);
    if (!FORCE && existsSync(out)) {
      try {
        const prev = JSON.parse(readFileSync(out, 'utf8'));
        if (prev.cacheKey === key) {
          log(`nav: ${level.id} up to date (${path.relative(webRoot, out)})`);
          continue;
        }
      } catch {
        /* re-bake */
      }
    }
    if (CHECK) {
      console.error(`nav: ${level.id} is stale (run npm run bake:nav)`);
      stale++;
      continue;
    }
    const result = await bakeLevel(level);
    result.cacheKey = key;
    result.levelFile = `src/data/${file}`;
    mkdirSync(path.dirname(out), { recursive: true });
    writeFileSync(out, JSON.stringify(result) + '\n');
    baked++;
    const s = result.stats;
    log(
      `nav: baked ${level.id} -> ${path.relative(webRoot, out)}: ${s.triangles} triangles in ${s.groups} group(s), main ${s.mainGroupTriangles} (${s.mainGroupAreaM2} m2), ` +
        `cover ${s.coverPoints} (low ${s.coverLow}, high ${s.coverHigh}, window ${s.coverWindow}, peek ${s.coverWithPeek}, design ${s.coverDesign}), ${s.bakeSeconds} s`,
    );
    if (result.reachability) {
      for (const [zid, r] of Object.entries(result.reachability)) {
        log(`nav:   ${zid}: ${Object.entries(r.teams).map(([t, v]) => `${t} ${v.reachable}/${v.points} (${v.meanPathM} m)`).join(', ')}; max/min ${r.maxOverMin}`);
      }
    }
  }
  // registry module: bundles the baked navmeshes so the runtime gets them synchronously (no fetch)
  const regPath = path.join(webRoot, 'src/ai/nav/navRegistry.generated.js');
  const lines = [
    '// GENERATED by tools/bake_navmesh.mjs - do not edit. Baked navmeshes bundled into the runtime (pure JSON).',
    ...registry.map((r) => `import nav_${r.id} from '../../../public/${r.navFile}' with { type: 'json' };`),
    '',
    `export const NAV_DATA = { ${registry.map((r) => `${r.id}: nav_${r.id}`).join(', ')} };`,
    '',
  ];
  const reg = lines.join('\n');
  const prevReg = existsSync(regPath) ? readFileSync(regPath, 'utf8') : '';
  if (prevReg !== reg) {
    if (CHECK) {
      console.error('nav: src/ai/nav/navRegistry.generated.js is stale (run npm run bake:nav)');
      stale++;
    } else {
      writeFileSync(regPath, reg);
      log(`nav: wrote ${path.relative(webRoot, regPath)} (${registry.length} level(s))`);
    }
  }
  if (stale) process.exit(1);
  return baked;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch((err) => {
    console.error(err && err.stack ? err.stack : err);
    process.exit(1);
  });
}
