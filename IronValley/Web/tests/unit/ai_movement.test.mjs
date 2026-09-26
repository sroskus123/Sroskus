// AI-02 — paths and mutual avoidance on the real game integration: 17 bots cross the arena at the same
// time through the house doorways, up the stair, through the narrow alley and the open gap; a path
// through a barricade the navmesh does not know is detected and recovered; nobody teleports.
import test from 'node:test';
import assert from 'node:assert/strict';
import { createArenaSession, place, run, arenaLevel, DT } from './support/aiSim.mjs';

const L = arenaLevel();
const T = L.aiTest;
// perception off: the bots only walk (combat would interfere with the navigation measurement)
const WALK_ONLY = { vision: { range: 0.5 }, hearing: { gunshotRange: 0, footstepRange: 0 } };

function sprintSpeed() {
  return 5.8;
}

test('AI-02: 17 bots cross the arena (doorways, stair, alley, gap) and reach their goals; no permanent stuck, no teleports', () => {
  const ctx = createArenaSession({ bots: [5, 6, 6], withPlayer: false, seed: 21, zone: 'arena_center', tuning: WALK_ONLY });
  run(ctx, 2);
  const bots = ctx.session.combatants.bots();
  assert.equal(bots.length, 17);
  const routes = T.crossing.routes;
  bots.forEach((c, i) => {
    const r = routes[i % routes.length];
    place(ctx.session, c.id, r.from, 0);
    ctx.ai.commandMove(c.id, r.to, { tolerance: 0.6 });
  });
  const prev = new Map(bots.map((c) => [c.id, c.position.clone()]));
  const arrived = new Map();
  const lastProgress = new Map(bots.map((c) => [c.id, { t: 0, d: Infinity }]));
  let maxH = 0;
  let maxV = 0;
  let maxNoProgress = 0;
  let overlapTicks = 0;
  const overlapRun = new Map();
  let maxOverlapRun = 0;
  const limitH = sprintSpeed() * DT + 0.02;
  run(ctx, Math.round(75 / DT), {
    onTick: () => {
      const t = ctx.session.simTime;
      for (const [i, c] of bots.entries()) {
        const p = c.position;
        const q = prev.get(c.id);
        const h = Math.hypot(p.x - q.x, p.z - q.z);
        const dv = Math.abs(p.y - q.y);
        maxH = Math.max(maxH, h);
        maxV = Math.max(maxV, dv);
        q.copy(p);
        const r = routes[i % routes.length];
        const d = Math.hypot(p.x - r.to[0], p.z - r.to[2]) + Math.abs(p.y - r.to[1]);
        const lp = lastProgress.get(c.id);
        if (d < lp.d - 0.5) {
          lp.d = d;
          lp.t = t;
        }
        if (!arrived.has(c.id)) {
          maxNoProgress = Math.max(maxNoProgress, t - lp.t);
          if (Math.hypot(p.x - r.to[0], p.z - r.to[2]) < 0.8 && Math.abs(p.y - r.to[1]) < 0.5) arrived.set(c.id, +t.toFixed(2));
        }
      }
      // bodies occupying the same spot (capsules do not collide with each other: avoidance must separate)
      for (let a = 0; a < bots.length; a++) {
        for (let b = a + 1; b < bots.length; b++) {
          const pa = bots[a].position;
          const pb = bots[b].position;
          const key = `${a}_${b}`;
          if (Math.hypot(pa.x - pb.x, pa.z - pb.z) < 0.45 && Math.abs(pa.y - pb.y) < 1) {
            overlapTicks++;
            const n = (overlapRun.get(key) || 0) + 1;
            overlapRun.set(key, n);
            maxOverlapRun = Math.max(maxOverlapRun, n);
          } else overlapRun.set(key, 0);
        }
      }
      return arrived.size < bots.length;
    },
  });
  const dbg = ctx.ai.getDebug();
  const stuck = dbg.metrics.stuck;
  const unrecovered = stuck.filter((s) => s.recoveredAt === null);
  const times = [...arrived.values()].sort((a, b) => a - b);
  const summary = {
    arrived: arrived.size,
    arrivalTimesS: { min: times[0], median: times[Math.floor(times.length / 2)], max: times[times.length - 1] },
    stuckEvents: stuck.length,
    stuckActions: stuck.map((s) => s.action),
    recoveryTimesS: stuck.map((s) => s.recoveryTime),
    unrecovered: unrecovered.length,
    maxHorizontalStepPerTick: +maxH.toFixed(4),
    limit: +limitH.toFixed(4),
    maxVerticalStepPerTick: +maxV.toFixed(4),
    maxNoProgressS: +maxNoProgress.toFixed(2),
    overlapTicks,
    maxOverlapRunS: +(maxOverlapRun * DT).toFixed(2),
  };
  console.log('AI-02 crossing', JSON.stringify(summary));
  assert.equal(arrived.size, 17, `all bots must arrive (${arrived.size}/17); not arrived: ${bots.filter((c) => !arrived.has(c.id)).map((c) => c.id)}`);
  assert.ok(maxH <= limitH, `no teleport: max horizontal step ${maxH} > ${limitH}`);
  assert.ok(maxV <= 0.45, `no vertical jump > step height: ${maxV}`);
  assert.ok(maxNoProgress < 10, `no permanent stuck: longest time without progress ${maxNoProgress.toFixed(1)} s`);
  assert.equal(unrecovered.length, 0, 'every stuck event recovered');
  assert.ok(maxOverlapRun * DT < 2.0, `two bots must not share a spot for long (${(maxOverlapRun * DT).toFixed(2)} s)`);
});

test('AI-02: a path blocked by an obstacle the navmesh does not know is detected within 3 s and recovered via another route', () => {
  const ctx = createArenaSession({ bots: [0, 2, 0], withPlayer: false, seed: 22, zone: 'arena_center', tuning: WALK_ONLY });
  run(ctx, 2);
  const [c, c2] = ctx.session.combatants.bots();
  place(ctx.session, c.id, T.blocked.start, 180);
  place(ctx.session, c2.id, [-30, 0, -20], 0);
  ctx.ai.commandMove(c.id, T.blocked.goal, { tolerance: 0.6 });
  let tAtObstacle = null;
  let tArrive = null;
  let maxH = 0;
  const prev = c.position.clone();
  let viaK2 = false;
  run(ctx, Math.round(40 / DT), {
    onTick: () => {
      const t = ctx.session.simTime;
      const p = c.position;
      maxH = Math.max(maxH, Math.hypot(p.x - prev.x, p.z - prev.z));
      prev.copy(p);
      // barricade face at z = -23.4 (capsule radius 0.35): touching when z < -22.9 near x = 0
      if (tAtObstacle === null && Math.abs(p.x) < 1.2 && p.z < -22.85) tAtObstacle = t;
      if (p.x > 5.5 && p.x < 8.5 && Math.abs(p.z + 24) < 0.6) viaK2 = true;
      if (Math.hypot(p.x - T.blocked.goal[0], p.z - T.blocked.goal[2]) < 0.8) {
        tArrive = t;
        return false;
      }
      return true;
    },
  });
  const stuck = ctx.ai.getDebug().metrics.stuck.filter((s) => s.bot === c.id);
  assert.ok(tAtObstacle !== null, 'bot walked into the barricade (the navmesh route goes through K1)');
  assert.ok(stuck.length >= 1, 'stuck detected');
  const first = stuck[0];
  const detectDelay = first.t - tAtObstacle;
  assert.equal(first.action, 'block_and_repath');
  assert.equal(first.obstacle, 'yard_barricade');
  assert.ok(detectDelay <= 3.0, `detected ${detectDelay.toFixed(2)} s after reaching the obstacle (max 3 s)`);
  assert.ok(tArrive !== null, 'goal reached by another route');
  assert.ok(viaK2, 'recovered through gap K2');
  assert.ok(maxH <= 5.8 * DT + 0.02, 'no teleport');
  // a second bot sent the same way later benefits from the shared block: no stuck, straight via K2
  place(ctx.session, c2.id, T.blocked.start, 180);
  ctx.ai.commandMove(c2.id, T.blocked.goal, { tolerance: 0.6 });
  let t2 = null;
  const t2s = ctx.session.simTime;
  run(ctx, Math.round(25 / DT), {
    onTick: () => {
      const p = c2.position;
      if (Math.hypot(p.x - T.blocked.goal[0], p.z - T.blocked.goal[2]) < 0.8) {
        t2 = ctx.session.simTime - t2s;
        return false;
      }
      return true;
    },
  });
  const stuck2 = ctx.ai.getDebug().metrics.stuck.filter((s) => s.bot === c2.id);
  const res = { reachedObstacleAt: +tAtObstacle.toFixed(2), stuckDetectedAt: +first.t.toFixed(2), detectDelayS: +detectDelay.toFixed(2), recoveryTimeS: first.recoveryTime, arrivedAt: +tArrive.toFixed(2), secondBotS: t2 === null ? null : +t2.toFixed(2), secondBotStuck: stuck2.length };
  console.log('AI-02 blocked path', JSON.stringify(res));
  assert.ok(t2 !== null && stuck2.length === 0, 'second bot uses the known detour');
});
