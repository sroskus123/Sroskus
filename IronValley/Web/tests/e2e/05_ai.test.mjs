// AI on the real build in headless Chromium (AI arena), simulation with the WebGL draw disabled
// (software rendering is far too slow to render every tick): AI-01 perception and memory, AI-02 17 bots
// crossing the arena + blocked path, AI-03 reaction / hit rate / reload discipline / turn rate, AI-04 a
// match with the idle player. Two screenshots with the AI debug overlay. The player is scripted through
// __IV (teleport = no footsteps; mouse button = real trigger); bots are driven by the real AI.
import test, { after, before } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { launchGame, screenshot, WEB_ROOT } from './helpers.mjs';

const LEVEL = JSON.parse(readFileSync(path.join(WEB_ROOT, 'src/data/ai_arena.json'), 'utf8'));
const T = LEVEL.aiTest;
const AI = JSON.parse(readFileSync(path.join(WEB_ROOT, '..', 'Shared', 'config', 'ai.json'), 'utf8'));
const CENTER = { zone: { locations: [{ id: 'arena_center', name: 'Střed' }] } };

let g;
let page;
const ev = (fn, arg) => page.evaluate(fn, arg);

before(async () => {
  g = await launchGame({ width: 960, height: 540 });
  page = g.page;
});

after(async () => {
  if (g) {
    assert.deepEqual(g.errors, [], `console errors: ${g.errors.join(' | ')}`);
    assert.deepEqual(g.failed, [], `failed requests: ${g.failed.join(' | ')}`);
    await g.close();
  }
});

async function match(o) {
  return ev(async (o) => {
    const iv = window.__IV;
    iv.pause();
    iv.setDrawEnabled(false);
    await iv.startMatch({ level: 'ai_arena', seed: 5, skipPreRound: true, ...o });
    iv.pause();
    iv.releaseAll();
    iv.step(2); // the AI installs __IV.ai on its first update
    return { ai: !!iv.ai, stub: iv.getAIDebug().stub, level: iv.getLevelInfo().id };
  }, o);
}

test('AI system is live in the build: arena level, baked navmesh + cover points bundled, no stub', async () => {
  const r = await match({ bots: [5, 6, 6], rules: CENTER });
  assert.equal(r.level, 'ai_arena');
  assert.equal(r.ai, true);
  assert.equal(r.stub, false);
  const d = await ev(() => {
    const dbg = window.__IV.ai.getDebug();
    return { tri: dbg.nav.triangles, cover: dbg.cover.points, bots: dbg.bots.length, zone: dbg.activeZone };
  });
  assert.ok(d.tri > 300 && d.cover > 100, JSON.stringify(d));
  assert.equal(d.bots, 17);
  assert.equal(d.zone.id, 'arena_center');
});

test('AI-01 in the browser: detection after the configured time; silent player behind a wall never known; gunshot -> approximate position + search; last known position not updated without a stimulus', async () => {
  await match({ bots: [0, 1, 0], rules: { combat: { maxHealth: 1000000 } } });
  const r = await ev(
    ({ T, AI }) => {
      const iv = window.__IV;
      const ai = iv.ai;
      const bot = 'bot_1_0';
      const now = () => iv.getMatchState().simTime;
      const known = () => (ai.memory(bot) || []).find((e) => e.id === 'player') || null;
      ai.setGuardMode(true);
      const out = {};
      // (a) visible player at 20 m on the free lane
      iv.placeCombatant(bot, ...T.vision.bot, T.vision.botYawDeg);
      ai.setLookHint(bot, T.vision.botYawDeg, 120);
      iv.placeCombatant('player', T.vision.bot[0] - 6, 0, T.vision.bot[2], 90);
      iv.step(20);
      out.knownBefore = !!known();
      iv.placeCombatant(bot, ...T.vision.bot, T.vision.botYawDeg);
      iv.placeCombatant('player', T.vision.bot[0] + 20, 0, T.vision.bot[2], 90);
      const t0 = now();
      let tDetect = null;
      for (let i = 0; i < 180 && tDetect === null; i++) {
        iv.step(1);
        const e = known();
        if (e && e.seen) tDetect = now() - t0;
      }
      out.detect20 = tDetect;
      // (b) player behind the wall line, silent (teleport, no footsteps), 20 s
      iv.forceKill('player');
      iv.step(1);
      out.forgottenAfterDeath = !known();
      iv.simulate(6);
      iv.placeCombatant(bot, ...T.wall.bot, T.wall.botYawDeg);
      ai.setLookHint(bot, T.wall.botYawDeg, 120);
      iv.placeCombatant('player', ...T.wall.target, 0);
      iv.step(2);
      let everKnown = false;
      for (let i = 0; i < 1200; i++) {
        iv.step(1);
        if (known()) everKnown = true;
      }
      out.wallEverKnown = everKnown;
      // (c) one gunshot behind the wall (into the ground): approximate position, then a search
      iv.placeCombatant(bot, ...T.gunshot.bot, T.gunshot.botYawDeg);
      ai.setLookHint(bot, T.gunshot.botYawDeg, 120);
      iv.placeCombatant('player', ...T.gunshot.shooter, 0, -60);
      iv.setLook(0, -60);
      iv.step(5);
      const truePos = iv.listCombatants().find((c) => c.id === 'player').position;
      iv.mouseButton(0, true);
      iv.step(1);
      iv.mouseButton(0, false);
      iv.step(2);
      const heard = known();
      out.heard = heard ? { source: heard.source, err: Math.hypot(heard.pos[0] - truePos[0], heard.pos[2] - truePos[2]), seen: heard.seen } : null;
      // the player leaves silently to the north-west yard (hidden behind the wall line)
      iv.placeCombatant('player', -30, 0, -32, 0);
      let searched = false;
      let minDist = 1e9;
      for (let i = 0; i < 40 * 60; i++) {
        iv.step(1);
        const b = ai.brief(bot);
        if (b.task === 'search') searched = true;
        if (heard) minDist = Math.min(minDist, Math.hypot(b.pos[0] - heard.pos[0], b.pos[2] - heard.pos[2]));
        if (searched && b.task !== 'search' && !known()) break;
      }
      out.searched = searched;
      out.searchClosest = minDist;
      out.forgottenAfterSearch = !known();
      // (d) seen in the open, then hidden and moved silently: the last known position stays
      iv.placeCombatant(bot, ...T.loseSight.bot, T.loseSight.botYawDeg);
      ai.setLookHint(bot, T.loseSight.botYawDeg, 120);
      iv.placeCombatant('player', ...T.loseSight.target, 180);
      iv.step(60);
      const seen = known();
      out.seenOpen = !!(seen && seen.seen);
      iv.placeCombatant('player', ...T.loseSight.hideAt, 180);
      iv.step(12);
      const lk = known();
      iv.placeCombatant('player', ...T.loseSight.moveTo, 180);
      let changed = 0;
      for (let i = 0; i < 240; i++) {
        iv.step(1);
        const e = known();
        if (!e || e.seen) break;
        if (Math.hypot(e.pos[0] - lk.pos[0], e.pos[2] - lk.pos[2]) > 1e-6) changed++;
      }
      out.lastKnown = lk ? lk.pos : null;
      out.lastKnownChanged = changed;
      return out;
    },
    { T, AI },
  );
  console.log('e2e AI-01', JSON.stringify(r));
  assert.equal(r.knownBefore, false);
  assert.ok(r.detect20 !== null && r.detect20 > 0.3 && r.detect20 < 0.8, `detection at 20 m after ${r.detect20} s (config ~0.46 s)`);
  assert.equal(r.forgottenAfterDeath, true, 'dead target forgotten');
  assert.equal(r.wallEverKnown, false, 'silent player behind a wall never known');
  assert.ok(r.heard && r.heard.source === 'hearing' && !r.heard.seen, 'gunshot heard');
  assert.ok(r.heard.err > 0.02 && r.heard.err < 4, `approximate position (error ${r.heard.err} m)`);
  assert.ok(r.searched && r.searchClosest < 6, `search walked to the heard position (closest ${r.searchClosest})`);
  assert.equal(r.forgottenAfterSearch, true, 'gave up after the search');
  assert.equal(r.seenOpen, true);
  assert.equal(r.lastKnownChanged, 0, 'last known position unchanged without a stimulus');
});

test('AI-02 in the browser: 17 bots cross the arena (doorways, stair, alley, gap) without teleports or permanent stuck; blocked path recovered', async () => {
  await match({ bots: [5, 6, 6], rules: CENTER });
  const r = await ev(
    ({ routes, blocked }) => {
      const iv = window.__IV;
      const ai = iv.ai;
      const ids = ai.positions().map((p) => p[0]);
      // (1) blocked path on a fresh navmesh: one bot through the barricade gap K1 (the others are parked
      //     with scripted moves, so nobody fights)
      ids.forEach((id, i) => {
        iv.placeCombatant(id, -30 + (i % 6) * 2.5, 0, 26 + Math.floor(i / 6) * 2.5, 0);
        ai.commandMove(id, [-30 + (i % 6) * 2.5, 0, 26 + Math.floor(i / 6) * 2.5], { tolerance: 0.6 });
      });
      const b0 = ids[0];
      iv.placeCombatant(b0, ...blocked.start, 180);
      ai.commandMove(b0, blocked.goal, { tolerance: 0.6 });
      let tAt = null;
      let tArr = null;
      let tt = 0;
      for (let i = 0; i < 40 * 60; i++) {
        iv.step(1);
        tt += 1 / 60;
        const p = ai.brief(b0).pos;
        if (tAt === null && Math.abs(p[0]) < 1.2 && p[2] < -22.85 && p[2] > -23.6) tAt = tt;
        if (Math.hypot(p[0] - blocked.goal[0], p[2] - blocked.goal[2]) < 0.8) {
          tArr = tt;
          break;
        }
      }
      const tNow = ai.time();
      const evs = ai.getDebug().metrics.stuck.filter((s) => s.bot === b0).map((s) => ({ dt: s.t - (tNow - tt), action: s.action, obstacle: s.obstacle }));
      // (2) 17 bots cross the arena at once
      ids.forEach((id, i) => {
        const rt = routes[i % routes.length];
        iv.placeCombatant(id, ...rt.from, 0);
        ai.commandMove(id, rt.to, { tolerance: 0.6 });
      });
      const prev = new Map(ai.positions().map((p) => [p[0], [p[3], p[4], p[5]]]));
      const arrived = new Map();
      let maxH = 0;
      let t = 0;
      const stuck0 = ai.getDebug().metrics.stuck.length;
      for (let i = 0; i < 75 * 60 && arrived.size < ids.length; i++) {
        iv.step(1);
        t += 1 / 60;
        for (const p of ai.positions()) {
          const q = prev.get(p[0]);
          if (p[2]) maxH = Math.max(maxH, Math.hypot(p[3] - q[0], p[5] - q[2]));
          prev.set(p[0], [p[3], p[4], p[5]]);
          const k = ids.indexOf(p[0]);
          const rt = routes[k % routes.length];
          if (!arrived.has(p[0]) && Math.hypot(p[3] - rt.to[0], p[5] - rt.to[2]) < 0.8 && Math.abs(p[4] - rt.to[1]) < 0.5) arrived.set(p[0], +t.toFixed(2));
        }
      }
      const stuck = ai.getDebug().metrics.stuck.slice(stuck0);
      return {
        arrived: arrived.size,
        total: ids.length,
        maxArrival: Math.max(...arrived.values()),
        maxH,
        stuck: stuck.length,
        unrecovered: stuck.filter((s) => s.recoveredAt === null).length,
        blocked: { reachedAt: tAt, arrivedAt: tArr, events: evs },
      };
    },
    { routes: T.crossing.routes, blocked: T.blocked },
  );
  console.log('e2e AI-02', JSON.stringify(r));
  assert.equal(r.arrived, r.total, `all 17 bots arrived (${r.arrived}/${r.total})`);
  assert.ok(r.maxH <= 5.8 / 60 + 0.02, `no teleport (max step ${r.maxH})`);
  assert.equal(r.unrecovered, 0, 'every stuck event recovered');
  assert.ok(r.blocked.reachedAt !== null && r.blocked.arrivedAt !== null, 'blocked path: reached the barricade and then the goal');
  const ev0 = r.blocked.events.find((e) => e.action === 'block_and_repath' && e.obstacle === 'yard_barricade');
  assert.ok(ev0, 'barricade detected as an unknown obstacle');
  assert.ok(ev0.dt - r.blocked.reachedAt <= 3.0, `detected ${(ev0.dt - r.blocked.reachedAt).toFixed(2)} s after reaching the barricade`);
});

test('AI-03 in the browser: reaction time and hit rate at 20 m, no trigger while reloading, turn rate limit', async () => {
  await match({ bots: [0, 1, 0], rules: { combat: { maxHealth: 1000000 } } });
  const r = await ev(
    ({ T, AI }) => {
      const iv = window.__IV;
      const ai = iv.ai;
      const bot = 'bot_1_0';
      ai.setGuardMode(true);
      iv.placeCombatant(bot, ...T.vision.bot, T.vision.botYawDeg);
      ai.setLookHint(bot, T.vision.botYawDeg, 120);
      iv.placeCombatant('player', T.vision.bot[0] - 6, 0, T.vision.bot[2], 90);
      iv.step(20);
      iv.placeCombatant(bot, ...T.vision.bot, T.vision.botYawDeg);
      iv.placeCombatant('player', T.vision.bot[0] + 20, 0, T.vision.bot[2], 90);
      const shots0 = ai.brief(bot).shots;
      const hp0 = iv.listCombatants().find((c) => c.id === 'player').health;
      let first = null;
      let maxTurn = 0;
      let prevYaw = ai.brief(bot).yaw;
      let reloadFire = 0;
      let reloadingTicks = 0;
      for (let i = 0; i < 30 * 60; i++) {
        const before = ai.brief(bot);
        iv.step(1);
        const b = ai.brief(bot);
        const d = Math.abs(Math.atan2(Math.sin(b.yaw - prevYaw), Math.cos(b.yaw - prevYaw)));
        maxTurn = Math.max(maxTurn, d);
        prevYaw = b.yaw;
        if (before.weaponState !== 'ready') {
          reloadingTicks++;
          if (b.fireCmd) reloadFire++;
        }
        if (first === null && b.shots > shots0) first = (i + 1) / 60;
      }
      const b = ai.brief(bot);
      const hp1 = iv.listCombatants().find((c) => c.id === 'player').health;
      const dbg = ai.bot(bot);
      return { first, shots: b.shots - shots0, damage: hp0 - hp1, maxTurnDeg: (maxTurn * 180) / Math.PI, reloadFire, reloadingTicks, shotsDuringReload: b.shotsDuringReload, reactions: dbg.metrics.reactions };
    },
    { T, AI },
  );
  // hits from damage: rifle 34 per torso hit (head x2, arm x0.7, leg x0.75): count hits approximately
  const hitsApprox = r.damage / 34;
  const rate = hitsApprox / r.shots;
  console.log('e2e AI-03', JSON.stringify({ ...r, hitRateApprox: +rate.toFixed(3) }));
  assert.ok(r.first !== null && r.first >= 0.46 + AI.combat.reactionDelayMin - 0.1 && r.first <= 0.46 + AI.combat.reactionDelayMax + 0.5, `first shot after ${r.first} s`);
  assert.ok(r.shots >= 30, 'the bot kept engaging');
  assert.ok(rate > 0.1 && rate < 0.7, `hit rate at 20 m ~ model 0.36 (approx ${rate.toFixed(3)})`);
  assert.ok(r.reloadingTicks > 0, 'reloads happened');
  assert.equal(r.reloadFire, 0, 'no trigger while reloading');
  assert.equal(r.shotsDuringReload, 0);
  assert.ok(r.maxTurnDeg <= AI.turnRateDegPerSec / 60 + 1e-6, `turn rate (${r.maxTurnDeg} deg / tick)`);
});

test('AI-04 in the browser: 2 minutes with the idle player — all teams reach the zone, fight, zone changes hands, ties, allies never target the player', async () => {
  await match({ bots: [5, 6, 6], seed: 41, rules: CENTER });
  const r = await ev(() => {
    const iv = window.__IV;
    const ai = iv.ai;
    const inZone = [0, 0, 0];
    const statuses = new Set();
    const controllers = new Set();
    let allyTargetsPlayer = 0;
    let teamTargets = 0;
    for (let k = 0; k < 240; k++) {
      iv.step(30);
      const m = iv.getMatchState();
      for (let t = 0; t < 3; t++) if (m.counts[t] > 0) inZone[t] += 0.5;
      statuses.add(m.status);
      if (m.controller >= 0) controllers.add(m.controller);
      for (const p of ai.positions()) {
        if (p[7] !== null && p[7] === p[1]) teamTargets++;
      }
      for (const p of ai.positions()) if (p[1] === 0 && ai.brief(p[0]).targetId === 'player') allyTargetsPlayer++;
    }
    const m = iv.getMatchState();
    const deaths = iv.getDeathLog();
    const teamOf = new Map(iv.listCombatants().map((c) => [c.id, c.team]));
    const kills = [0, 0, 0];
    for (const d of deaths) if (d.attackerId && teamOf.get(d.attackerId) !== teamOf.get(d.victimId)) kills[teamOf.get(d.attackerId)]++;
    const reloadViol = ai.positions().reduce((a, p) => a + p[8], 0);
    return { scores: m.scores, inZone, statuses: [...statuses], controllers: [...controllers], kills, ff: m.stats.ffBlocked, teamTargets, allyTargetsPlayer, reloadViol, updMs: ai.getDebug().metrics.updateMsAvg };
  });
  console.log('e2e AI-04', JSON.stringify(r));
  assert.ok(r.inZone.every((s) => s > 0), `all teams reached the zone: ${r.inZone}`);
  assert.ok(r.kills.every((k) => k > 0), `all teams fought: kills ${r.kills}`);
  assert.ok(r.controllers.length >= 2, 'zone changed hands');
  assert.ok(r.statuses.includes('contested'), 'ties occurred');
  assert.equal(r.teamTargets, 0, 'no bot targeted a teammate');
  assert.equal(r.allyTargetsPlayer, 0, 'allies never targeted the player');
  assert.equal(r.ff, 0, 'no friendly round hit');
  assert.equal(r.reloadViol, 0);
});

test('AI debug overlay: screenshot of the arena with paths, last known positions and reserved cover', async () => {
  await match({ bots: [5, 6, 6], seed: 9, rules: CENTER });
  const info = await ev(() => {
    const iv = window.__IV;
    iv.simulate(14);
    // elevated view from the house roof over the zone
    iv.placeCombatant('player', 0, 6.05, 15.2, 0, -22);
    iv.setLook(0, -22);
    const on = iv.ai.setOverlay(true);
    iv.step(6);
    iv.setDrawEnabled(true);
    iv.renderNow();
    return { on, bots: iv.ai.getDebug().bots.filter((b) => b.alive).length };
  });
  assert.equal(info.on, true, 'overlay enabled');
  await screenshot(page, 'ai_overlay_zone.png');
  await ev(() => {
    const iv = window.__IV;
    // on top of the container b_cont_1, looking over the zone towards the house
    iv.placeCombatant('player', -16, 2.65, -10.5, -123, -12);
    iv.setLook(-123, -12);
    iv.step(1);
    iv.renderNow();
  });
  await screenshot(page, 'ai_overlay_west.png');
  await ev(() => {
    const iv = window.__IV;
    iv.ai.setOverlay(false);
    iv.setDrawEnabled(false);
  });
});
