// Movement and collision checks through the real build: input goes through the game's input
// handlers (__IV.keyDown -> InputManager), time is advanced in fixed ticks.
import test, { after, before } from 'node:test';
import assert from 'node:assert/strict';
import { enterTestMode, launchGame, screenshot } from './helpers.mjs';

let g;
let cfg;
let markers;

before(async () => {
  g = await launchGame({ width: 960, height: 540 });
  await enterTestMode(g.page);
  cfg = await g.page.evaluate(() => window.__IV.getConfig());
  markers = (await g.page.evaluate(() => window.__IV.getLevelInfo())).markers;
});

after(async () => {
  if (g) {
    assert.deepEqual(g.errors, [], `console errors: ${g.errors.join(' | ')}`);
    await g.close();
  }
});

/** Runs a scenario inside the page: keys held, ticks stepped, returns player states. */
async function scenario({ marker, keys = [], ticks = 60, until = null, maxTicks = 900 }) {
  return g.page.evaluate(
    ({ marker, keys, ticks, until, maxTicks }) => {
      const iv = window.__IV;
      iv.releaseAll();
      iv.teleportToMarker(marker);
      iv.step(2);
      for (const k of keys) iv.keyDown(k);
      let n = 0;
      let maxY = -Infinity;
      if (until) {
        // until = { axis: 'x'|'y'|'z', lt?: number, gt?: number } on the player position
        const pred = (s) => {
          const v = s.position[until.axis];
          return (until.lt !== undefined && v < until.lt) || (until.gt !== undefined && v > until.gt);
        };
        while (n < maxTicks && !pred(iv.getState().player)) {
          iv.step(1);
          n++;
          maxY = Math.max(maxY, iv.getState().player.position.y);
        }
      } else {
        for (let i = 0; i < ticks; i++) {
          iv.step(1);
          maxY = Math.max(maxY, iv.getState().player.position.y);
        }
        n = ticks;
      }
      const s = iv.getState().player;
      for (const k of keys) iv.keyUp(k);
      return { ...s, ticksRun: n, maxY };
    },
    { marker, keys, ticks, until, maxTicks },
  );
}

async function measureSpeed(keys) {
  return g.page.evaluate((keys) => {
    const iv = window.__IV;
    iv.releaseAll();
    iv.teleportToMarker('speed_start');
    iv.step(2);
    for (const k of keys) iv.keyDown(k);
    iv.step(90); // accelerate
    const a = iv.getState().player.position;
    iv.step(60); // exactly 1.0 s of simulation
    const b = iv.getState().player.position;
    for (const k of keys) iv.keyUp(k);
    iv.step(30);
    return Math.hypot(b.x - a.x, b.z - a.z);
  }, keys);
}

test('measured walk / run / sprint speeds are within 5% of config', async () => {
  const run = await measureSpeed(['KeyW']);
  const walk = await measureSpeed(['KeyW', 'AltLeft']);
  const sprint = await measureSpeed(['KeyW', 'ShiftLeft']);
  const S = cfg.movement.speeds;
  const rel = (v, e) => Math.abs(v - e) / e;
  assert.ok(rel(run, S.run) < 0.05, `run ${run} vs ${S.run}`);
  assert.ok(rel(walk, S.walk) < 0.05, `walk ${walk} vs ${S.walk}`);
  assert.ok(rel(sprint, S.sprint) < 0.05, `sprint ${sprint} vs ${S.sprint}`);
  console.log(`# speeds m/s: walk ${walk.toFixed(3)}, run ${run.toFixed(3)}, sprint ${sprint.toFixed(3)}`);
});

test('diagonal movement is not faster than forward movement', async () => {
  const fwd = await measureSpeed(['KeyW']);
  const diag = await measureSpeed(['KeyW', 'KeyD']);
  const sfwd = await measureSpeed(['KeyW', 'ShiftLeft']);
  const sdiag = await measureSpeed(['KeyW', 'KeyA', 'ShiftLeft']);
  assert.ok(diag <= fwd * 1.001, `diag ${diag} > fwd ${fwd}`);
  assert.ok(sdiag <= sfwd * 1.001, `sprint diag ${sdiag} > ${sfwd}`);
});

test('climbs the 0.18 m stairs to the landing', async () => {
  const m = markers.stairs_start;
  const mid = (m.landingZ[0] + m.landingZ[1]) / 2;
  const s = await scenario({ marker: 'stairs_start', keys: ['KeyW'], until: { axis: 'z', lt: mid }, maxTicks: 600 });
  assert.ok(s.position.z < mid + 0.1, `z ${s.position.z}`);
  assert.ok(Math.abs(s.position.y - m.landingY) < 0.02, `y ${s.position.y}`);
  assert.equal(s.grounded, true);
  // screenshot of the stairs from the side
  await g.page.evaluate(() => {
    const iv = window.__IV;
    iv.teleportToMarker('stairs_view');
    iv.step(1, { render: true });
  });
  await screenshot(g.page, 'stairs_view.png');
  // and from the middle of the flight, looking up
  await g.page.evaluate(() => {
    const iv = window.__IV;
    iv.teleportToMarker('stairs_start');
    iv.keyDown('KeyW');
    iv.step(40);
    iv.keyUp('KeyW');
    iv.step(20, { render: true });
  });
  await screenshot(g.page, 'stairs_climbing.png');
});

test('cannot pass the 1.0 m wall (sprinting and jumping at it)', async () => {
  const m = markers.wall1m_start;
  const s = await scenario({ marker: 'wall1m_start', keys: ['KeyW', 'ShiftLeft'], ticks: 180 });
  assert.ok(s.position.z > m.wallFrontZ, `z ${s.position.z}`);
  assert.ok(s.maxY < 0.05, `was lifted to ${s.maxY}`);
  // jumping repeatedly against it: pure jump physics never mounts it (the deliberate vault that the jump key
  // starts at the wall is switched off here and tested in 07_movement_feel.test.mjs)
  const j = await g.page.evaluate(() => {
    const iv = window.__IV;
    iv.teleportToMarker('wall1m_start');
    iv.setTraversalEnabled(false);
    iv.step(2);
    iv.keyDown('KeyW');
    let maxY = -Infinity;
    let minZ = Infinity;
    for (let i = 0; i < 8; i++) {
      iv.step(20);
      iv.keyDown('Space');
      iv.step(1);
      iv.keyUp('Space');
      for (let k = 0; k < 40; k++) {
        iv.step(1);
        const p = iv.getState().player.position;
        minZ = Math.min(minZ, p.z);
        maxY = Math.max(maxY, p.y);
      }
    }
    iv.keyUp('KeyW');
    iv.step(30);
    iv.setTraversalEnabled(true);
    return { minZ, maxY, final: iv.getState().player };
  });
  assert.ok(j.minZ > m.wallFrontZ, `jumped through: min z ${j.minZ}`);
  assert.ok(j.final.position.y < 0.01 && j.final.position.z > m.wallFrontZ, JSON.stringify(j.final.position));
  assert.ok(j.maxY > 0.3 && j.maxY < 0.5, `jump apex ${j.maxY}`);
});

test('cannot walk up the 50° slope but can walk up the 30° slope', async () => {
  const s50 = await scenario({ marker: 'slope50_start', keys: ['KeyW', 'ShiftLeft'], ticks: 240 });
  assert.ok(s50.maxY < 0.3, `50deg reached y ${s50.maxY}`);
  const s30 = await scenario({ marker: 'slope30_start', keys: ['KeyW'], until: { axis: 'z', lt: -6.5 }, maxTicks: 600 });
  assert.ok(Math.abs(s30.position.y - markers.slope30_start.topY) < 0.02, `30deg y ${s30.position.y}`);
});

test('crosses the 0.03 m threshold', async () => {
  const m = markers.threshold_start;
  const s = await scenario({ marker: 'threshold_start', keys: ['KeyW'], until: { axis: 'z', lt: m.passZ }, maxTicks: 300 });
  assert.ok(s.position.z < m.passZ, `z ${s.position.z}`);
  assert.ok(s.ticksRun < 150, `took ${s.ticksRun} ticks`);
});

test('passes the 0.90 m doorway', async () => {
  const m = markers.door_start;
  const s = await scenario({ marker: 'door_start', keys: ['KeyW'], until: { axis: 'z', lt: m.passZ }, maxTicks: 300 });
  assert.ok(s.position.z < m.passZ, `z ${s.position.z}`);
  assert.ok(s.ticksRun < 150, `took ${s.ticksRun} ticks`);
});

test('crouches into the 1.40 m tunnel, cannot stand inside, can stand after leaving', async () => {
  const m = markers.tunnel_start;
  const r = await g.page.evaluate((m) => {
    const iv = window.__IV;
    iv.releaseAll();
    // standing: blocked at the entrance
    iv.teleportToMarker('tunnel_start');
    iv.step(2);
    iv.keyDown('KeyW');
    iv.step(150);
    iv.keyUp('KeyW');
    const standingZ = iv.getState().player.position.z;
    // crouched: walk in
    iv.teleportToMarker('tunnel_start');
    iv.step(2);
    iv.keyDown('KeyC');
    iv.step(15);
    iv.keyDown('KeyW');
    let n = 0;
    while (iv.getState().player.position.z > m.midZ && n < 600) {
      iv.step(1);
      n++;
    }
    iv.keyUp('KeyW');
    iv.keyUp('KeyC'); // try to stand up inside
    iv.step(60, { render: true });
    const inside = iv.getState().player;
    // walk out with crouch released
    iv.keyDown('KeyW');
    n = 0;
    while (iv.getState().player.position.z > m.exitZ - 1.0 && n < 900) {
      iv.step(1);
      n++;
    }
    iv.keyUp('KeyW');
    iv.step(40);
    const outside = iv.getState().player;
    return { standingZ, inside, outside };
  }, m);
  await screenshot(g.page, 'tunnel_crouched.png');
  assert.ok(r.standingZ > m.entryZ, `standing entered the tunnel: z ${r.standingZ}`);
  assert.ok(r.inside.position.z <= m.midZ + 0.05, `reached z ${r.inside.position.z}`);
  assert.equal(r.inside.crouched, true, 'must stay crouched under the 1.40 m ceiling');
  assert.equal(r.inside.height, cfg.movement.capsule.crouchHeight);
  assert.ok(Math.abs(r.inside.eyeHeight - cfg.movement.capsule.crouchEyeHeight) < 1e-6);
  assert.equal(r.outside.crouched, false, 'stands up after leaving');
  assert.equal(r.outside.height, cfg.movement.capsule.standHeight);
});

test('falls off the 1.0 m drop, lands and regains control', async () => {
  const m = markers.drop_start;
  const r = await g.page.evaluate((m) => {
    const iv = window.__IV;
    iv.releaseAll();
    iv.teleportToMarker('drop_start');
    iv.step(2);
    iv.keyDown('KeyW');
    let onPlatform = false;
    let n = 0;
    let airborne = 0;
    while (n < 900) {
      iv.step(1);
      n++;
      const p = iv.getState().player;
      if (p.grounded && Math.abs(p.position.y - m.platformY) < 0.01) onPlatform = true;
      if (!p.grounded) airborne++;
      if (p.position.z < m.edgeZ - 1.5 && p.grounded) break;
    }
    const landed = iv.getState().player;
    iv.keyUp('KeyW');
    // regain control: strafe right
    const x0 = landed.position.x;
    iv.keyDown('KeyD');
    iv.step(60);
    iv.keyUp('KeyD');
    iv.step(30);
    const after = iv.getState().player;
    const landings = iv.getState().events.filter((e) => e.type === 'landed');
    return { onPlatform, landed, dx: after.position.x - x0, airborne, landings };
  }, m);
  assert.ok(r.onPlatform, 'walked up the ramp onto the 1.0 m platform');
  assert.ok(r.landed.grounded && Math.abs(r.landed.position.y) < 0.01, `y ${r.landed.position.y}`);
  assert.ok(r.airborne >= 15 && r.airborne <= 40, `airborne ticks ${r.airborne}`);
  const last = r.landings[r.landings.length - 1];
  assert.ok(last && last.speed > 3.5 && last.speed < 5.5, `landing event ${JSON.stringify(last)}`);
  assert.ok(r.dx > 1.5, `strafe after landing moved ${r.dx}`);
});

test('sprinting straight at the thin 0.1 m wall does not tunnel through', async () => {
  const m = markers.thinwall_start;
  const s = await scenario({ marker: 'thinwall_start', keys: ['KeyW', 'ShiftLeft'], ticks: 240 });
  assert.ok(s.position.z > m.wallFrontZ, `z ${s.position.z}`);
  // at a 4x time scale on 30 FPS frame pacing the per-tick motion is unchanged (fixed step)
  const r = await g.page.evaluate(() => {
    const iv = window.__IV;
    iv.teleportToMarker('thinwall_start');
    iv.step(2);
    iv.setTimeScale(4);
    iv.keyDown('KeyW');
    iv.keyDown('ShiftLeft');
    iv.frames(1 / 30, 60, { render: false });
    iv.keyUp('ShiftLeft');
    iv.keyUp('KeyW');
    iv.setTimeScale(1);
    return iv.getState().player.position;
  });
  assert.ok(r.z > m.wallFrontZ, `time-scaled z ${r.z}`);
});

test('first-person screenshot at the thin wall (sanity: looking at geometry up close)', async () => {
  await g.page.evaluate(() => {
    const iv = window.__IV;
    iv.teleportToMarker('thinwall_start');
    iv.step(1, { render: true });
  });
  await screenshot(g.page, 'thin_wall_view.png');
});

test('the view stands still behind the pause menu after pausing mid-sprint (no interpolation sawtooth)', async () => {
  const r = await g.page.evaluate(() => {
    const iv = window.__IV;
    iv.setDrawEnabled(false); // full frame update, WebGL draw skipped (SwiftShader is slow)
    iv.releaseAll();
    iv.startGame();
    iv.pause();
    iv.teleportToMarker('speed_start');
    iv.step(2);
    iv.keyDown('KeyW');
    iv.keyDown('ShiftLeft');
    iv.step(60);
    iv.openMenu();
    iv.frames(1 / 144, 3, { render: true }); // let the first paused tick pass
    const xs = [];
    for (let i = 0; i < 30; i++) {
      iv.frames(1 / 144, 1, { render: true });
      const s = iv.getState();
      xs.push(s.camera.position);
    }
    iv.keyUp('KeyW');
    iv.keyUp('ShiftLeft');
    iv.startGame();
    iv.pause();
    iv.setDrawEnabled(true);
    return { state: 'paused', xs };
  });
  let maxJump = 0;
  for (let i = 1; i < r.xs.length; i++) {
    const a = r.xs[i - 1];
    const b = r.xs[i];
    maxJump = Math.max(maxJump, Math.hypot(b[0] - a[0], b[1] - a[1], b[2] - a[2]));
  }
  assert.ok(maxJump < 1e-6, `camera moved ${maxJump} m between frames while paused`);
});

test('head bob is interpolated: at 144 FPS with camera motion on, the camera moves every frame while sprinting', async () => {
  // Real FixedStepLoop.frame -> Game.render path, WebGL draw skipped. Bob and landing dip
  // advance on the 60 Hz tick; without interpolation 3 of 5 frames at 144 FPS repeat the
  // previous height and the others jump by a whole tick.
  const r = await g.page.evaluate(() => {
    const iv = window.__IV;
    iv.startGame();
    iv.pause();
    iv.setDrawEnabled(false);
    const out = {};
    for (const motion of [0, 1]) {
      iv.setSetting('cameraMotion', motion);
      iv.releaseAll();
      iv.teleportToMarker('speed_start');
      iv.step(2);
      iv.keyDown('KeyW');
      iv.keyDown('ShiftLeft');
      iv.step(120); // full speed
      iv.resetAccumulator();
      const cam = [];
      for (let i = 0; i < 144; i++) {
        iv.frames(1 / 144, 1, { render: true });
        cam.push(iv.getState().camera.position);
      }
      iv.keyUp('KeyW');
      iv.keyUp('ShiftLeft');
      iv.step(60);
      const d = (k) => cam.slice(1).map((p, i) => p[k] - cam[i][k]);
      out[motion] = { dx: d(0), dy: d(1) };
    }
    iv.setSetting('cameraMotion', 1);
    iv.setDrawEnabled(true);
    return out;
  });
  const zeros = (a) => a.filter((v) => Math.abs(v) < 1e-9).length;
  // camera motion off: horizontal eye interpolation is exact (constant step), no vertical motion
  const dx0 = r[0].dx;
  assert.ok(Math.max(...dx0) - Math.min(...dx0) < 1e-6, `dx spread ${Math.max(...dx0) - Math.min(...dx0)}`);
  // camera motion on: vertical bob changes every frame, in small steps
  const dy1 = r[1].dy;
  assert.equal(zeros(dy1), 0, `frames without vertical camera change: ${zeros(dy1)}/${dy1.length}`);
  const maxDy = Math.max(...dy1.map(Math.abs));
  assert.ok(maxDy < 0.004, `largest vertical camera step between 144 FPS frames ${maxDy} m`);
  console.log(`# bob at 144 FPS: zero-change frames ${zeros(dy1)}/${dy1.length}, max step ${(maxDy * 1000).toFixed(2)} mm`);
});
