// Kalné Hamry (generated map, Tools/level/export_web_level.py) in the real build:
//  - the level loads from its GLB files without console errors or failed requests (load time and the rendered
//    frame's draw calls / triangles are printed; SwiftShader numbers are NOT real GPU performance);
//  - a match puts the player on a safe spawn point of the row that is active for the round's zone;
//  - the player walks into each main building through its doors and up its stairs (scripted keyboard walk along
//    waypoints, the same controller and collision as in the game): the workshop hall through gate G1, the
//    warehouse over the dock stairs and the open sliding door, the house through the entrance steps and door and
//    up the U-stair to the first floor;
//  - a full round with 17 bots (render off, time-scaled through the real loop) ends with a winner or a draw, with
//    no bot stuck for 5 s or longer and no teleport.
import test, { after, before } from 'node:test';
import assert from 'node:assert/strict';
import { launchGame, screenshot } from './helpers.mjs';

const SPRINT_STEP = 5.8 / 60 + 0.02; // m per tick: sprint speed + margin (no teleport)

let g;
let page;
const ev = (fn, arg) => page.evaluate(fn, arg);

before(async () => {
  g = await launchGame({ width: 960, height: 540 });
  page = g.page;
  page.setDefaultTimeout(900_000);
});

after(async () => {
  if (g) {
    assert.deepEqual(g.errors, [], `console errors: ${g.errors.join(' | ')}`);
    assert.deepEqual(g.failed, [], `failed requests: ${g.failed.join(' | ')}`);
    await g.close();
  }
});

test('Kalné Hamry loads from its GLB files without errors; draw calls / triangles of a rendered frame', async () => {
  const r = await ev(async () => {
    const iv = window.__IV;
    const t0 = performance.now();
    const info = await iv.loadLevel('kalne_hamry');
    const ms = performance.now() - t0;
    iv.startGame();
    iv.pause();
    iv.teleportToMarker('spawn');
    iv.step(2);
    const gm = iv._game;
    const ri = gm.renderer.renderer.info;
    // the game draws the world and then the view model: accumulate both (shadow pass included)
    ri.autoReset = false;
    ri.reset();
    iv.renderNow();
    ri.autoReset = true;
    return {
      ms,
      info,
      state: iv.getState(),
      hud: iv.getHud(),
      frame: { calls: ri.render.calls, triangles: ri.render.triangles, geometries: ri.memory.geometries, textures: ri.memory.textures },
      levels: iv.listLevels(),
      tag: document.querySelector('.iv-hud') ? document.querySelector('.iv-hud').textContent.includes('pracovní verze (provizorní grafika)') : false,
    };
  });
  console.log(`# kalne_hamry load ${r.ms.toFixed(0)} ms (fetch ${r.info.load.fetchMs.toFixed(0)}, collision BVH ${r.info.load.collisionMs.toFixed(0)}, render ${r.info.load.renderMs.toFixed(0)}); collision ${r.info.load.triangles} tris; view ${JSON.stringify(r.info.load.view)}; frame at the square: ${r.frame.calls} draw calls, ${r.frame.triangles} triangles`);
  assert.equal(r.state.levelId, 'kalne_hamry');
  assert.equal(r.info.hasMatch, true);
  assert.ok(r.info.load.triangles > 100000, 'terrain + buildings collision');
  assert.ok(r.frame.calls > 10 && r.frame.triangles > 10000, JSON.stringify(r.frame));
  assert.ok(r.levels.some((l) => l.id === 'kalne_hamry' && l.name === 'Kalné Hamry' && l.tag === 'pracovní verze (provizorní grafika)'));
  assert.ok(r.tag, 'HUD shows "pracovní verze (provizorní grafika)"');
  await screenshot(page, 'kh_square.png');
});

test('match on Kalné Hamry: the player spawns on a safe point of the row active for the zone', async () => {
  const r = await ev(async () => {
    const iv = window.__IV;
    iv.pause();
    iv.setDrawEnabled(false);
    await iv.startMatch({ level: 'kalne_hamry', bots: [5, 6, 6], seed: 11, ai: true, skipPreRound: true });
    iv.pause();
    const m = iv.getMatchState();
    const gm = iv._game;
    const lvl = gm.level;
    const me = iv.listCombatants().find((c) => c.id === 'player');
    const [x, y, z] = me.position;
    const pts = lvl.match.teamSpawns[me.team];
    let best = null;
    for (const p of pts) {
      const d = Math.hypot(p.pos[0] - x, p.pos[2] - z);
      if (!best || d < best.d) best = { d, p };
    }
    // the spawn record: the engine predicate (no enemy within 25 m or in sight, capsule fits, ground below) at spawn time
    const hist = iv.getSpawnHistory();
    const safe = hist.find((h) => h.id === 'player');
    return { m, me, best, safe, spawns: hist.length, allSafe: hist.every((h) => h.safeAtSpawn && !h.insideGeometry) };
  });
  assert.equal(r.me.alive, true);
  assert.ok(r.best.d < 0.6, `player at a spawn candidate (${r.best.d.toFixed(2)} m)`);
  assert.ok(r.best.p.zones.includes(r.m.zoneId), `the row ${r.best.p.row} is active for ${r.m.zoneId}`);
  assert.equal(r.spawns, 18, 'everybody spawned');
  assert.equal(r.safe.safeAtSpawn, true, JSON.stringify(r.safe));
  assert.equal(r.safe.insideGeometry, false);
  assert.ok(r.safe.nearestEnemy >= 25, `nearest enemy ${r.safe.nearestEnemy} m`);
  assert.equal(r.safe.visibleToEnemy, null, 'no enemy sees the point');
  assert.equal(r.allSafe, true, 'every combatant spawned safely');
});

test('the player walks into the workshop, the warehouse and the house through doors and up the stairs', async () => {
  // waypoints = corners of the baked navmesh path (what the bots walk), three.js coordinates
  const routes = {
    // workshop yard -> gate G1 (double door, open) -> hall
    workshop: { start: [-24.5, 1.13, -18.5], pts: [[-28.02, 1.3, -20.83], [-28.3, 1.3, -21.29], [-28.61, 1.3, -21.32], [-30.44, 1.3, -24.83]], room: { y: [1.25, 1.4], near: [-30.44, -24.83, 1.0] } },
    // warehouse yard -> dock stairs SK_X1 -> dock -> open sliding door SK_SD1 -> hall
    warehouse: {
      start: [26.5, 1.3, -7.0],
      pts: [[29.88, 1.35, -7.77], [30.03, 1.75, -6.89], [31.4, 2.4, -7.22], [33.15, 2.4, -8.84], [33.56, 2.4, -8.92], [38.34, 2.4, -20.21], [38.73, 2.4, -20.49], [40.09, 2.4, -20.47], [40.49, 2.4, -20.04], [40.7, 2.4, -16.5]],
      room: { y: [2.35, 2.5], near: [40.7, -16.5, 1.0] },
    },
    // rear yard -> entrance steps DM_X1 -> door DM0_D1 -> hall -> U-stair (flight S1a, landing, flight S1b) -> first floor hall
    house: {
      start: [-9.5, 2.4, 50.33],
      pts: [[-9.8, 2.4, 49.93], [-9.6, 2.4, 49.61], [-9.45, 2.4, 47.72], [-9.2, 2.4, 47.51], [-8.0, 2.8, 46.36], [-7.57, 2.95, 46.15], [-7.2, 2.95, 44.87], [-7.23, 2.95, 44.1], [-7.65, 2.95, 44.01], [-9.27, 2.95, 43.62], [-9.55, 2.95, 43.22], [-9.2, 4.5, 40.7], [-8.36, 4.45, 40.63], [-7.95, 4.45, 41.08], [-8.23, 5.25, 42.29], [-8.33, 5.95, 43.39], [-7.89, 5.95, 43.81], [-7.65, 5.95, 43.61], [-7.23, 5.95, 43.51], [-7.29, 5.95, 42.82]],
      room: { y: [5.9, 6.0], near: [-7.29, 42.82, 1.0] },
    },
  };
  const out = {};
  for (const [name, rt] of Object.entries(routes)) {
    out[name] = await ev((rt) => {
      const iv = window.__IV;
      iv.pause();
      iv.startGame();
      iv.pause();
      iv.teleport(rt.start[0], rt.start[1], rt.start[2], 0, 0);
      iv.step(5);
      // scripted walk: face the next waypoint every tick and hold W (walk speed, no sprint)
      const pts = rt.pts;
      const maxTicks = 60 * 60;
      let i = 0;
      let ticks = 0;
      const trace = [];
      iv.releaseAll();
      while (i < pts.length && ticks < maxTicks) {
        const p = iv.getState().player.position;
        const q = pts[i];
        const dx = q[0] - p.x;
        const dz = q[2] - p.z;
        if (Math.hypot(dx, dz) < 0.3) {
          i++;
          continue;
        }
        iv.setLook((Math.atan2(-dx, -dz) * 180) / Math.PI, 0);
        iv.keyDown('KeyW');
        iv.step(1);
        ticks++;
        if (ticks % 30 === 0) trace.push([+p.x.toFixed(2), +p.y.toFixed(2), +p.z.toFixed(2)]);
      }
      iv.keyUp('KeyW');
      iv.step(10);
      const s = iv.getState().player;
      return { reached: i, of: pts.length, ticks, position: s.position, grounded: s.grounded, trace };
    }, rt);
    const r = out[name];
    const p = r.position;
    console.log(`# walk ${name}: ${r.reached}/${r.of} waypoints in ${r.ticks} ticks, end (${p.x.toFixed(2)}, ${p.y.toFixed(2)}, ${p.z.toFixed(2)})`);
    assert.equal(r.reached, r.of, `${name}: every waypoint reached (trace ${JSON.stringify(r.trace)})`);
    assert.ok(p.y >= rt.room.y[0] && p.y <= rt.room.y[1], `${name}: on the target floor (y ${p.y})`);
    assert.ok(Math.hypot(p.x - rt.room.near[0], p.z - rt.room.near[1]) < rt.room.near[2], `${name}: in the target room`);
    assert.equal(r.grounded, true);
  }
});

test('full round with 17 bots on Kalné Hamry (render off, time-scaled): winner or draw, nobody stuck >= 5 s, no teleport', async () => {
  const start = await ev(async () => {
    const iv = window.__IV;
    iv.pause();
    iv.setDrawEnabled(false);
    await iv.startMatch({ level: 'kalne_hamry', bots: [5, 6, 6], seed: 5, ai: true, skipPreRound: true });
    iv.pause();
    iv.releaseAll();
    iv.telemetryStart();
    return { m: iv.getMatchState(), n: iv.listCombatants().length };
  });
  assert.equal(start.n, 18, 'player + 17 bots');
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
    return { tel: iv.telemetryReport(), m: iv.getMatchState() };
  });
  const tel = r.tel;
  console.log(
    `# kalne_hamry round (${start.m.zoneId}): ${tel.round.elapsedS} s, scores ${tel.round.scores.join('/')}, ${tel.round.draw ? 'draw' : `winner ${tel.round.winner}`} (${tel.round.endReason}); zone presence ${tel.zone.presenceS.join('/')} s; kills ${tel.kills.join('/')}; stuck max ${tel.stuck.maxS} s; jump max ${tel.jumps.maxHorizontalM} m/tick; ${tel.perf.tickMsMean} ms/tick (p95 ${tel.perf.tickMsP95}); wall ${wallS.toFixed(1)} s`,
  );
  assert.equal(r.m.gameState, 'results', `results screen after the round (${JSON.stringify(last)})`);
  assert.ok(['score_target', 'time_limit'].includes(tel.round.endReason), tel.round.endReason);
  if (tel.round.draw) assert.equal(tel.round.endReason, 'time_limit');
  else assert.ok([0, 1, 2].includes(tel.round.winner), `winner ${tel.round.winner}`);
  assert.ok(tel.stuck.maxS < 5, `longest stuck episode ${tel.stuck.maxS} s (${tel.stuck.maxId}): ${JSON.stringify(tel.stuck.longest.slice(0, 2))}`);
  assert.equal(tel.jumps.teleports, 0, `teleports: ${JSON.stringify(tel.jumps.teleportList)}`);
  assert.ok(tel.jumps.maxHorizontalM <= SPRINT_STEP, `max horizontal step ${tel.jumps.maxHorizontalM} m/tick`);
  assert.equal(tel.teamKills, 0, 'no team kill');
  await ev(() => window.__IV.telemetryStop());
});
