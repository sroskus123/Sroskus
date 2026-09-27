// Full round with 17 bots on the real build (AI arena, active zone "Střed"), WebGL draw off, time-scaled
// through the real loop accumulator (setTimeScale + frames, not only stepTicks): the pre-round countdown,
// the round until it ends by score or time, the results screen, then "Nové kolo" clicked in the UI.
// Checked with the match telemetry (window.__IV.telemetry*, src/debug/matchTelemetry.js):
//  - the round ends with a winner or a draw (score target or time limit) and the results screen says so;
//  - every team scored or took part in a contested zone (AI-04: all three teams go for the zone);
//  - no bot stuck in movement for 5 s or longer (AI-02), no teleport (per-tick jump), no team kill;
//  - no console error, no failed request;
//  - "Nové kolo" resets scores, timers, kill feed, respawns, AI memory, cover reservations and navmesh blocks,
//    the bots wait in their spawns during the countdown and go for the zone at the start, and no timer left
//    over from round 1 scores in round 2 (GAME-01, GAME-02, AI-04).
import test, { after, before } from 'node:test';
import assert from 'node:assert/strict';
import { launchGame } from './helpers.mjs';

const CENTER = { zone: { locations: [{ id: 'arena_center', name: 'Střed' }] } };
const SPRINT_STEP = 5.8 / 60 + 0.02; // m per tick: sprint speed + margin (no teleport)

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

test('full round with 17 bots (render off, time-scaled): winner or draw, every team contests the zone, nobody stuck >= 5 s, no teleport, "Nové kolo" resets everything', async () => {
  const start = await ev(async (rules) => {
    const iv = window.__IV;
    iv.pause();
    iv.setDrawEnabled(false);
    // with the 5 s pre-round (no skip): the whole round flow as in the game
    await iv.startMatch({ level: 'ai_arena', bots: [5, 6, 6], seed: 9, ai: true, rules });
    iv.pause();
    iv.releaseAll();
    iv.telemetryStart();
    return { m: iv.getMatchState(), n: iv.listCombatants().length };
  }, CENTER);
  assert.equal(start.n, 18, 'player + 17 bots');
  assert.equal(start.m.state, 'pre_round');
  assert.equal(start.m.zoneId, 'arena_center');

  // run the round through the real loop with time scale 10 (frames of 1/60 s real time -> 10 ticks each)
  let chunks = 0;
  let last = null;
  const t0 = Date.now();
  while (chunks < 90) {
    last = await ev(() => {
      const iv = window.__IV;
      iv.setTimeScale(10);
      iv.frames(1 / 60, 60, { render: false }); // 10 s of simulation
      const m = iv.getMatchState();
      return { gameState: m.gameState, state: m.state, elapsed: m.elapsedS, scores: m.scores };
    });
    chunks++;
    if (last.gameState === 'results') break;
  }
  const wallS = (Date.now() - t0) / 1000;
  const r = await ev(() => {
    const iv = window.__IV;
    iv.setTimeScale(1);
    const tel = iv.telemetryReport();
    const m = iv.getMatchState();
    return { tel, m, menu: iv.getMenu(), text: document.querySelector('.iv-menu') ? document.querySelector('.iv-menu').textContent : '', locked: !!document.pointerLockElement };
  });
  const tel = r.tel;
  console.log(
    `# full round: ${tel.round.elapsedS} s, scores ${tel.round.scores.join('/')}, ${tel.round.draw ? 'draw' : `winner ${tel.round.winner}`} (${tel.round.endReason}); zone presence ${tel.zone.presenceS.join('/')} s, contested ${tel.zone.contestedPresenceS.join('/')} s, controllers ${tel.zone.controllersSeen}; kills ${tel.kills.join('/')}, deaths ${tel.deaths.join('/')}; stuck max ${tel.stuck.maxS} s; jump max ${tel.jumps.maxHorizontalM} m/tick (3D ${tel.jumps.maxM}); shots ${tel.shots.join('/')} hits ${tel.hits.join('/')}; ${tel.perf.tickMsMean} ms/tick; wall ${wallS.toFixed(1)} s`,
  );

  // the round ended with a winner or a draw, the results screen shows it
  assert.equal(r.m.gameState, 'results', `results screen after the round (${JSON.stringify(last)})`);
  assert.equal(tel.round.state, 'ended');
  assert.ok(['score_target', 'time_limit'].includes(tel.round.endReason), tel.round.endReason);
  if (tel.round.draw) {
    assert.equal(tel.round.endReason, 'time_limit');
    assert.match(r.text, /Remíza/);
  } else {
    assert.ok([0, 1, 2].includes(tel.round.winner), `winner ${tel.round.winner}`);
    const top = Math.max(...tel.round.scores);
    assert.equal(tel.round.scores[tel.round.winner], top, 'the winner has the top score');
    assert.equal(tel.round.scores.filter((s) => s === top).length, 1, 'a unique top score');
    assert.match(r.text, /Vítězí tým/);
  }
  if (tel.round.endReason === 'time_limit') assert.ok(Math.abs(tel.round.elapsedS - 600) < 0.05, `time limit at 600 s (${tel.round.elapsedS})`);
  else assert.equal(Math.max(...tel.round.scores), 100);
  assert.equal(r.locked, false, 'cursor free on the results screen');

  // AI-04: every team scored or took part in a contested zone
  for (let t = 0; t < 3; t++) {
    assert.ok(tel.round.scores[t] > 0 || tel.zone.contestedPresenceS[t] > 0, `team ${t} scored or contested the zone (score ${tel.round.scores[t]}, contested presence ${tel.zone.contestedPresenceS[t]} s)`);
    assert.ok(tel.zone.presenceS[t] > 0, `team ${t} was in the zone (${tel.zone.presenceS[t]} s)`);
    assert.ok(tel.kills[t] > 0, `team ${t} fought (kills ${tel.kills[t]})`);
  }
  assert.equal(tel.teamKills, 0, 'no team kill');
  // AI-02: nobody stuck for 5 s or longer; no teleport
  assert.ok(tel.stuck.maxS < 5, `longest stuck episode ${tel.stuck.maxS} s (${tel.stuck.maxId}): ${JSON.stringify(tel.stuck.longest.slice(0, 2))}`);
  assert.equal(tel.jumps.teleports, 0, `teleports: ${JSON.stringify(tel.jumps.teleportList)}`);
  assert.ok(tel.jumps.maxHorizontalM <= SPRINT_STEP, `max horizontal step ${tel.jumps.maxHorizontalM} m/tick`);
  assert.ok(tel.respawns.every((n) => n > 0), `respawns ${tel.respawns}`);

  // "Nové kolo" from the results screen (real click)
  assert.deepEqual(
    r.menu.buttons.map((b) => b.text),
    ['Nové kolo', 'Změnit výbavu', 'Hlavní menu'],
  );
  await page.click('.iv-btn-primary');
  await page.waitForFunction(() => window.__IV.getState().state === 'playing');
  const nr = await ev(() => {
    const iv = window.__IV;
    iv.pause();
    const snap = () => {
      const d = iv.getAIDebug();
      return {
        memory: d.bots.reduce((s, b) => s + b.memory.length, 0),
        targets: d.bots.filter((b) => b.target).length,
        paths: d.bots.reduce((s, b) => s + b.move.path.length, 0),
        cover: d.cover.reservations.length,
        blocks: d.nav.blocks.length,
        time: d.time,
        tasks: d.bots.map((b) => ({ task: b.task, reason: b.taskReason, since: b.taskSince, decidedAt: b.lastDecisionAt })),
      };
    };
    const ai0 = snap();
    const m = iv.getMatchState();
    const c = iv.listCombatants();
    const tel = iv.telemetryReport();
    iv.step(1);
    const ai1 = snap();
    iv.renderNow();
    return { ai0, ai1, m, c, hud: iv.getHud(), deaths: iv.getDeathLog().length, spawns: iv.getSpawnHistory().length, resets: tel.roundResets };
  });
  assert.equal(nr.m.roundNumber, 2);
  assert.equal(nr.m.state, 'pre_round');
  assert.deepEqual(nr.m.scores, [0, 0, 0]);
  assert.equal(nr.m.elapsedS, 0);
  assert.equal(nr.m.remainingS, 600);
  assert.equal(nr.m.progress, 0);
  assert.equal(nr.m.killFeed.length, 0);
  assert.equal(nr.m.status, 'empty');
  assert.equal(nr.deaths, 0, 'death log cleared');
  assert.equal(nr.spawns, 18, 'everybody spawned once for round 2');
  assert.equal(nr.resets, 1);
  assert.match(nr.hud.timer, /Start za 5 s/);
  assert.equal(nr.hud.scores.join(','), '0,0,0');
  for (const x of nr.c) {
    assert.equal(x.alive, true, `${x.id} alive`);
    assert.equal(x.health, 100, `${x.id} health`);
    assert.equal(x.spawnCount, 1, `${x.id} spawned once`);
    assert.deepEqual([x.weapon.magazine, x.weapon.chamber, x.weapon.reserve], [30, 1, 90], `${x.id} full rifle`);
  }
  for (const s of [nr.ai0, nr.ai1]) {
    assert.equal(s.memory, 0, 'AI memory cleared');
    assert.equal(s.targets, 0, 'no AI target carried over');
    assert.equal(s.blocks, 0, 'navmesh blocks cleared');
  }
  assert.equal(nr.ai0.cover, 0, 'cover reservations cleared by the reset');
  assert.equal(nr.ai0.paths, 0, 'paths cleared');
  // one tick later every bot has re-planned for round 2: during the countdown it waits in its spawn
  for (const b of nr.ai1.tasks) {
    assert.equal(b.task, 'idle', `round-2 countdown task ${JSON.stringify(b)}`);
    assert.equal(b.reason, 'odpočet', `waits for the start ${JSON.stringify(b)}`);
    assert.ok(b.decidedAt !== null && b.decidedAt >= nr.ai0.time - 1e-6, `decided after the reset ${JSON.stringify(b)}`);
  }
  assert.equal(nr.ai1.cover, 0, 'no cover reserved while waiting for the start');

  // round 2 runs; no timer left over from round 1 scores (nobody reaches the zone in 1 s of play)
  const run = await ev(() => {
    const iv = window.__IV;
    iv.setTimeScale(10);
    iv.frames(1 / 60, 36, { render: false }); // 6 s: pre-round + 1 s of the round
    iv.setTimeScale(1);
    return { ...iv.getMatchState(), tasks: iv.getAIDebug().bots.map((b) => b.task), deaths: iv.getDeathLog().length };
  });
  assert.equal(run.state, 'running');
  assert.ok(run.elapsedS > 0.9, `round 2 clock runs (${run.elapsedS})`);
  assert.deepEqual(run.scores, [0, 0, 0], 'no leftover scoring in round 2');
  assert.equal(run.deaths, 0, 'nobody died during the countdown');
  assert.ok(run.tasks.filter((t) => t === 'objective').length >= 15, `after the start the bots go for the zone: ${run.tasks}`);
  await ev(() => window.__IV.telemetryStop());
});
