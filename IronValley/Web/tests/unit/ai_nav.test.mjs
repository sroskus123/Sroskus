// Navmesh bake output, NavService (paths, blocked areas) and CoverService (bake-time cover points,
// exclusive reservation). Pure Node, no rendering.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import path from 'node:path';
import { Vector3 } from 'three';
import { NavService } from '../../src/ai/nav/navService.js';
import { CoverService } from '../../src/ai/cover/coverService.js';
import { NAV_DATA } from '../../src/ai/nav/navRegistry.generated.js';
import { buildLevelSolids } from '../../src/level/levelGeometry.js';
import { CollisionWorld } from '../../src/physics/collisionWorld.js';
import { WEB } from './support/aiSim.mjs';

const level = JSON.parse(readFileSync(path.join(WEB, 'src/data/ai_arena.json'), 'utf8'));
const data = JSON.parse(readFileSync(path.join(WEB, 'public/assets/nav/ai_arena.json'), 'utf8'));
const v = (a) => new Vector3(a[0], a[1], a[2]);

test('bake: navmesh JSON is up to date with the level and the bake settings (npm run bake:nav --check)', () => {
  const out = execFileSync(process.execPath, [path.join(WEB, 'tools/bake_navmesh.mjs'), '--check', '--level', 'ai_arena'], { cwd: WEB, encoding: 'utf8' });
  assert.match(out, /ai_arena up to date/);
  assert.deepEqual(NAV_DATA.ai_arena.cacheKey, data.cacheKey, 'bundled registry = public file');
});

test('bake: agent settings, three-pathfinding zone format, main group gate', () => {
  assert.equal(data.schema, 'ironvalley.nav/1');
  assert.deepEqual(data.warnings, [], 'reachability gate passed');
  assert.equal(data.tiled, false, 'the arena fits a solo navmesh');
  assert.deepEqual(data.agent, { radius: 0.35, height: 1.8, maxClimb: 0.4, maxSlopeDeg: 45 });
  assert.equal(data.recast.walkableRadius, 7);
  assert.equal(data.recast.walkableHeight, 36);
  assert.equal(data.recast.walkableClimb, 8);
  assert.equal(data.recast.walkableSlopeAngle, 45);
  assert.ok(data.zone.vertices.length % 3 === 0);
  for (const g of data.zone.groups) for (const n of g) assert.ok(n.vertexIds.length === 3 && n.portals.length === n.neighbours.length);
  assert.ok(data.stats.mainGroupTriangles > 300);
  assert.deepEqual(data.skippedSolids, ['yard_barricade'], 'the barricade (nav: false) is not baked');
  const nav = new NavService(data);
  // every spawn point and zone centre is on the main group (reachable)
  for (const list of level.match.teamSpawns) for (const s of list) assert.ok(nav.locate(v(s.pos), 0.8), `spawn ${s.pos}`);
  // roof of the house / tops of containers are separate groups (unreachable), not the main group
  assert.equal(nav.locate(new Vector3(0, 6.0, 17), 0.5), null, 'roof is not on the main group');
});

test('NavService: every AI test route has a path that stays on the navmesh; not longer than the three-pathfinding reference', () => {
  const nav = new NavService(data);
  const rows = [];
  for (const r of level.aiTest.crossing.routes) {
    const p = nav.findPath(v(r.from), v(r.to));
    assert.ok(p.ok, `route ${r.name}: ${p.reason}`);
    let prev = nav.closestPoint(v(r.from));
    for (const q of p.points) {
      assert.ok(nav.mesh.segmentOnMesh(prev, q, { step: 0.1 }), `route ${r.name}: segment leaves the navmesh`);
      prev = q;
    }
    const end = p.points[p.points.length - 1];
    assert.ok(Math.hypot(end.x - r.to[0], end.z - r.to[2]) < 0.3 && Math.abs(end.y - r.to[1]) < 0.5, `route ${r.name} ends at the goal`);
    const ref = nav.referencePath(v(r.from), v(r.to));
    let refLen = 0;
    let pr = v(r.from);
    for (const q of ref || []) {
      refLen += pr.distanceTo(q);
      pr = q;
    }
    assert.ok(p.length <= refLen * 1.03 + 0.6, `route ${r.name}: ${p.length.toFixed(2)} vs reference ${refLen.toFixed(2)}`);
    rows.push(`${r.name}:${p.length.toFixed(1)}/${refLen.toFixed(1)}`);
  }
  // upstairs goals really go up the stair (y 3.0)
  const up = nav.findPath(v([0, 0, 27]), v(level.aiTest.upstairs[0]));
  assert.ok(up.ok && Math.abs(up.points[up.points.length - 1].y - 3.0) < 0.2);
  console.log('route lengths ours/reference', rows.join(' '));
});

test('NavService: blocked area forces another route (barricade gap K1 -> gap K2) and expires', () => {
  const nav = new NavService(data);
  const B = level.aiTest.blocked;
  const direct = nav.findPath(v(B.start), v(B.goal));
  assert.ok(direct.ok && direct.length < 11.5, 'navmesh does not know the barricade: straight through K1');
  nav.blockArea(new Vector3(0, 0, -24.2), 1.1, 5);
  const around = nav.findPath(v(B.start), v(B.goal));
  assert.ok(around.ok && around.length > 15, `detour expected, got ${around.length}`);
  assert.ok(around.points.some((p) => p.x > 5.5 && p.x < 8.5 && Math.abs(p.z + 24) < 1.0), 'detour through K2');
  assert.equal(nav.isBlocked(new Vector3(0, 0.05, -24)), true);
  for (let i = 0; i < 6 * 60; i++) nav.update(1 / 60);
  assert.equal(nav.blocks.length, 0, 'block expired');
  assert.ok(nav.findPath(v(B.start), v(B.goal)).length < 11.5);
});

test('cover points: generated from geometry, on the reachable navmesh, normal away from the obstacle, low/high by obstacle height', () => {
  const world = new CollisionWorld(buildLevelSolids(level));
  const nav = new NavService(data);
  const cover = new CoverService(data.cover);
  assert.ok(cover.points.length > 100);
  const low = cover.points.filter((p) => p.height === 'low');
  const high = cover.points.filter((p) => p.height === 'high');
  assert.ok(low.length > 20 && high.length > 50);
  for (const p of cover.points) {
    assert.ok(nav.mesh.nodeAt(p.pos, { group: nav.mainGroup }) >= 0, `${p.id} reachable`);
    assert.ok(Math.abs(p.normal.y) < 1e-6 && Math.abs(p.normal.length() - 1) < 1e-3);
    assert.ok(!['boundary_n', 'boundary_s', 'boundary_w', 'boundary_e'].includes(p.solid), 'arena boundary excluded');
    // obstacle directly behind the point (against the normal) at knee height, open in front
    const o = new Vector3(p.pos.x, p.pos.y + 0.5, p.pos.z);
    const back = world.raycast(o, p.normal.clone().negate(), 1.0);
    assert.ok(back, `${p.id}: obstacle behind`);
    // low cover: blocked at 0.9 m, open at 1.7 m (a standing bot fires over it); high: blocked at 1.7 m
    const at = (h) => !!world.raycast(new Vector3(p.pos.x, p.pos.y + h, p.pos.z), p.normal.clone().negate(), back.distance + 0.3);
    assert.ok(at(0.9), `${p.id} covers a crouched body`);
    if (p.height === 'high') assert.ok(at(1.7), `${p.id} high covers a standing eye`);
    else assert.ok(!at(1.7), `${p.id} low: open at standing eye height`);
    if (p.peekPos) assert.ok(nav.mesh.nodeAt(p.peekPos, { group: nav.mainGroup }) >= 0, `${p.id} peek position reachable`);
  }
  // spacing: no two points closer than 0.7 m
  for (let i = 0; i < cover.points.length; i++) {
    for (let j = i + 1; j < cover.points.length; j++) {
      const a = cover.points[i].pos;
      const b = cover.points[j].pos;
      if (Math.abs(a.y - b.y) < 1.5) assert.ok(Math.hypot(a.x - b.x, a.z - b.z) >= 0.69, `${cover.points[i].id}/${cover.points[j].id} too close`);
    }
  }
  console.log('cover points', cover.points.length, 'low', low.length, 'high', high.length, 'window', cover.points.filter((p) => p.window).length, 'peek', cover.points.filter((p) => p.peekPos).length);
});

test('CoverService: reservation is exclusive, one point per bot, release frees it', () => {
  const cover = new CoverService(data.cover);
  const [a, b] = cover.points;
  assert.equal(cover.reserve('bot1', a.id), true);
  assert.equal(cover.reserve('bot2', a.id), false, 'second bot cannot take the same point');
  assert.equal(cover.holderOf(a.id), 'bot1');
  assert.equal(cover.reserve('bot1', b.id), true, 'moving to another point');
  assert.equal(cover.holderOf(a.id), null, 'previous point released automatically');
  assert.equal(cover.reserve('bot2', a.id), true);
  cover.release('bot1');
  assert.equal(cover.holderOf(b.id), null);
  assert.equal(cover.reservations().length, 1);
  assert.equal(cover.stats.conflictsRejected, 1);
});
