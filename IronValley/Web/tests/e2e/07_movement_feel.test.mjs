// Movement feel through the real build (user playtest feedback): vault over the 1.0 m wall with Space, the
// sprint -> jump -> Ctrl bug with REAL keyboard events, jump buffering / coyote time at the 1.0 m drop, the
// weapon lowered while vaulting (real render path, WebGL draw skipped) and the Czech station signs.
import test, { after, before } from 'node:test';
import assert from 'node:assert/strict';
import { enterTestMode, launchGame, screenshot } from './helpers.mjs';

let g;
let cfg;

before(async () => {
  g = await launchGame({ width: 960, height: 540 });
  await enterTestMode(g.page);
  cfg = await g.page.evaluate(() => window.__IV.getConfig());
});

after(async () => {
  if (g) {
    assert.deepEqual(g.errors, [], `console errors: ${g.errors.join(' | ')}`);
    await g.close();
  }
});

test('Space at the 1.0 m wall vaults over it: bus events with the contract payload, feet above the wall top, lands behind', async () => {
  const r = await g.page.evaluate(() => {
    const iv = window.__IV;
    iv.releaseAll();
    iv.teleportToMarker('wall1m_start');
    iv.step(2);
    iv.watchEvents(['traverse:start', 'traverse:end', 'footstep']);
    iv.keyDown('KeyW');
    let n = 0;
    while (iv.getState().player.position.z > -2.9 && n++ < 300) iv.step(1);
    iv.keyDown('Space');
    iv.step(1);
    iv.keyUp('Space');
    const path = [];
    for (let i = 0; i < 70; i++) {
      iv.step(1);
      const p = iv.getState().player;
      path.push({ x: p.position.x, y: p.position.y, z: p.position.z, trav: p.traversing, h: p.height });
    }
    iv.keyUp('KeyW');
    iv.step(20);
    return { path, events: iv.takeEvents(), final: iv.getState().player };
  });
  const st = r.events.find((e) => e.name === 'traverse:start');
  const en = r.events.find((e) => e.name === 'traverse:end');
  assert.ok(st, `no traverse:start (${JSON.stringify(r.final.lastTraversalFail)})`);
  assert.equal(st.id, 'player');
  assert.equal(st.type, 'vault');
  assert.ok(Math.abs(st.obstacleHeight - 1.0) < 0.01, `height ${st.obstacleHeight}`);
  assert.ok(st.duration >= 0.5 && st.duration <= 0.9, `duration ${st.duration}`);
  assert.ok(Array.isArray(st.ledgePoint) && Math.abs(st.ledgePoint[2] - -3.85) < 0.02, JSON.stringify(st.ledgePoint));
  assert.ok(en && en.aborted === false, JSON.stringify(en));
  // over the wall footprint (z -3.85 .. -4.15, capsule radius 0.35) the feet are above the top
  const over = r.path.filter((p) => p.z < -3.85 + 0.35 && p.z > -4.15 - 0.35);
  assert.ok(over.length > 0 && over.every((p) => p.y >= 1.0), `feet in the wall: ${JSON.stringify(over.slice(0, 3))}`);
  assert.ok(r.final.position.z < -4.5 && r.final.grounded && !r.final.crouched, JSON.stringify(r.final.position));
  // a landing footstep after the vault
  assert.ok(r.events.some((e) => e.name === 'footstep' && e.kind === 'land' && e.tick > st.tick), 'landing footstep');
});

test('weapon is lowered while vaulting and raised afterwards (real frame path); screenshot mid-vault', async () => {
  const r = await g.page.evaluate(() => {
    const iv = window.__IV;
    iv.setDrawEnabled(false);
    iv.releaseAll();
    iv.teleport(15, 0, -3.3, 0, 0);
    iv.frames(1 / 60, 30, { render: true });
    const rest = iv.getState().viewModel.holderPosition[1];
    iv.keyDown('Space');
    iv.frames(1 / 60, 1, { render: true });
    iv.keyUp('Space');
    iv.frames(1 / 60, 14, { render: true });
    const s = iv.getState();
    const mid = s.viewModel.holderPosition[1];
    const midCam = s.camera.position;
    const midTrav = s.player.traversing;
    iv.setDrawEnabled(true);
    return { rest, mid, midCam, midTrav };
  });
  assert.ok(r.midTrav, 'still vaulting at the sample');
  assert.ok(r.rest - r.mid > 0.15, `weapon lowered by ${(r.rest - r.mid).toFixed(3)} m`);
  assert.ok(r.midCam[1] > 1.65 + 0.1, `camera rides over the wall (eye ${r.midCam[1]})`);
  await g.page.evaluate(() => window.__IV.renderNow());
  await screenshot(g.page, 'vault_mid.png');
  const after = await g.page.evaluate(() => {
    const iv = window.__IV;
    iv.setDrawEnabled(false);
    iv.frames(1 / 60, 90, { render: true });
    const y = iv.getState().viewModel.holderPosition[1];
    iv.setDrawEnabled(true);
    return y;
  });
  assert.ok(Math.abs(after - r.rest) < 0.01, `weapon back up: ${after} vs ${r.rest}`);
});

test('sprint -> Space -> Ctrl within 1 s (REAL keyboard events): momentum kept, smooth slow-down to crouch speed, no dead stop', async () => {
  const S = cfg.movement.speeds;
  for (const delayTicks of [10, 30, 55]) {
    await g.page.evaluate(() => {
      const iv = window.__IV;
      iv.releaseAll();
      iv.teleport(-10, 0, 26, 0, 0);
      iv.step(2);
    });
    await g.page.keyboard.down('ShiftLeft');
    await g.page.keyboard.down('KeyW');
    await g.page.evaluate(() => window.__IV.step(90));
    await g.page.keyboard.down('Space');
    await g.page.evaluate(() => window.__IV.step(1));
    await g.page.keyboard.up('Space');
    await g.page.evaluate((n) => window.__IV.step(n), delayTicks);
    await g.page.keyboard.down('ControlLeft');
    const r = await g.page.evaluate(() => {
      const iv = window.__IV;
      const s0 = iv.getState();
      const out = { held: s0.input.heldCodes, p0: s0.player.position, speeds: [], grounded: [] };
      for (let i = 0; i < 90; i++) {
        iv.step(1);
        const p = iv.getState().player;
        out.speeds.push(p.horizontalSpeed);
        out.grounded.push(p.grounded);
      }
      const p = iv.getState().player;
      out.p1 = p.position;
      out.crouched = p.crouched;
      out.jumps = p.stats.jumps;
      return out;
    });
    await g.page.keyboard.up('ControlLeft');
    await g.page.keyboard.up('KeyW');
    await g.page.keyboard.up('ShiftLeft');
    const tag = `Ctrl ${delayTicks} ticks after the jump`;
    assert.ok(['ShiftLeft', 'KeyW', 'ControlLeft'].every((k) => r.held.includes(k)), `${tag}: keys held ${r.held}`);
    assert.ok(r.jumps >= 1, `${tag}: jumped`);
    assert.equal(r.crouched, true, `${tag}: crouched`);
    const minSpeed = Math.min(...r.speeds);
    let maxDecel = 0;
    for (let i = 1; i < r.speeds.length; i++) maxDecel = Math.max(maxDecel, (r.speeds[i - 1] - r.speeds[i]) * 60);
    const dist = Math.hypot(r.p1.x - r.p0.x, r.p1.z - r.p0.z);
    assert.ok(minSpeed >= S.crouch - 1e-6, `${tag}: speed fell to ${minSpeed}`);
    assert.ok(maxDecel <= cfg.movement.speedChangeDeceleration + 1e-3, `${tag}: deceleration ${maxDecel} m/s^2`);
    assert.ok(dist > 2.5, `${tag}: moved only ${dist.toFixed(2)} m in 1.5 s`);
    const firstGround = r.grounded.indexOf(true);
    if (firstGround > 0) assert.ok(r.speeds[firstGround] > S.sprint - 0.2, `${tag}: landing speed ${r.speeds[firstGround]}`);
  }
});

test('1.0 m drop: Space pressed ~0.1 s before landing jumps on landing; Space just after walking off still jumps (coyote); jumping while sprinting', async () => {
  const r = await g.page.evaluate(() => {
    const iv = window.__IV;
    const out = {};
    const toEdge = () => {
      iv.releaseAll();
      iv.teleport(9, 1.0, -7.2, 0, 0); // on the platform, facing the drop edge (z = -8)
      iv.step(2);
      iv.keyDown('KeyW');
      let n = 0;
      while (iv.getState().player.grounded && n++ < 200) iv.step(1);
      out.leftAtZ = iv.getState().player.position.z;
    };
    // buffered: press while still ~0.3 m above the floor (~0.08 s before landing)
    toEdge();
    let n = 0;
    while (iv.getState().player.position.y > 0.3 && n++ < 120) iv.step(1);
    const s0 = iv.getState().player.stats;
    iv.keyDown('Space');
    iv.step(1);
    iv.keyUp('Space');
    const airAtPress = !iv.getState().player.grounded;
    iv.step(12);
    const s1 = iv.getState().player.stats;
    out.buffer = { airAtPress, jumps: s1.jumps - s0.jumps, buffered: s1.bufferedJumps - s0.bufferedJumps, landed: s1.landings - s0.landings };
    iv.keyUp('KeyW');
    iv.step(60);
    // coyote: 3 ticks after leaving the platform
    toEdge();
    iv.step(3);
    const c0 = iv.getState().player.stats;
    iv.keyDown('Space');
    iv.step(1);
    iv.keyUp('Space');
    const c1 = iv.getState().player.stats;
    out.coyote = { jumps: c1.jumps - c0.jumps, coyote: c1.coyoteJumps - c0.coyoteJumps, vy: iv.getState().player.velocity.y };
    iv.keyUp('KeyW');
    iv.step(90);
    // sprinting jump on open ground
    iv.releaseAll();
    iv.teleport(-10, 0, 26, 0, 0);
    iv.step(2);
    iv.keyDown('KeyW');
    iv.keyDown('ShiftLeft');
    iv.step(60);
    const j0 = iv.getState().player.stats.jumps;
    iv.keyDown('Space');
    iv.step(1);
    iv.keyUp('Space');
    let apex = 0;
    let minAir = Infinity;
    for (let i = 0; i < 40; i++) {
      iv.step(1);
      const p = iv.getState().player;
      apex = Math.max(apex, p.position.y);
      if (!p.grounded) minAir = Math.min(minAir, p.horizontalSpeed);
    }
    out.sprintJump = { jumps: iv.getState().player.stats.jumps - j0, apex, minAir };
    iv.keyUp('KeyW');
    iv.keyUp('ShiftLeft');
    iv.step(30);
    return out;
  });
  assert.ok(r.leftAtZ < -7.9, `walked off the drop edge (z ${r.leftAtZ})`);
  assert.ok(r.buffer.airAtPress, 'Space was pressed in the air');
  assert.equal(r.buffer.jumps, 1, `buffered jump: ${JSON.stringify(r.buffer)}`);
  assert.equal(r.buffer.buffered, 1);
  assert.equal(r.coyote.jumps, 1, `coyote jump: ${JSON.stringify(r.coyote)}`);
  assert.equal(r.coyote.coyote, 1);
  assert.ok(r.coyote.vy > 2.5, `full jump impulse ${r.coyote.vy} (jump speed ${Math.sqrt(2 * 9.81 * cfg.movement.jumpApexHeight).toFixed(2)} m/s minus one tick of gravity)`);
  assert.equal(r.sprintJump.jumps, 1);
  assert.ok(Math.abs(r.sprintJump.apex - cfg.movement.jumpApexHeight) < 0.03, `apex ${r.sprintJump.apex}`);
  assert.ok(r.sprintJump.minAir > cfg.movement.speeds.sprint - 0.1, `air speed ${r.sprintJump.minAir}`);
});

test('turning 90° from a sprint in the browser build: small sideways drift', async () => {
  const r = await g.page.evaluate(() => {
    const iv = window.__IV;
    iv.releaseAll();
    iv.teleport(-10, 0, 26, 0, 0);
    iv.step(2);
    iv.keyDown('KeyW');
    iv.keyDown('ShiftLeft');
    iv.step(90);
    const p0 = iv.getState().player.position;
    iv.keyUp('KeyW');
    iv.keyDown('KeyD');
    iv.step(60);
    const p1 = iv.getState().player.position;
    iv.keyUp('KeyD');
    iv.keyUp('ShiftLeft');
    iv.step(30);
    return { drift: Math.abs(p1.z - p0.z), side: p1.x - p0.x };
  });
  assert.ok(r.drift <= 0.5, `drift along the old direction ${r.drift}`);
  assert.ok(r.side > 2.5, `moved sideways ${r.side}`);
});

test('station signs explain in Czech what each station tests (screenshot of the wall / thin wall signs)', async () => {
  const info = await g.page.evaluate(() => window.__IV.getLevelInfo().signs);
  assert.ok(info.length >= 12 && info.every((s) => typeof s.hint === 'string' && s.hint.length > 5), 'every sign has a hint line');
  const wall = info.find((s) => s.text.startsWith('ZEĎ 1,0'));
  assert.match(wall.hint, /Mezerník/);
  const thin = info.find((s) => s.text.startsWith('TENKÁ ZEĎ'));
  assert.match(thin.sub, /neprojdeš/);
  for (const [s, file] of [[wall, 'sign_wall_1m.png'], [thin, 'sign_thin_wall.png']]) {
    await g.page.evaluate((pos) => {
      const iv = window.__IV;
      iv.releaseAll();
      iv.teleport(pos[0], 0, pos[2] + 1.6, 0, 0);
      iv.lookAt(pos[0], 1.3, pos[2]);
      iv.step(1);
      iv.renderNow();
    }, s.pos);
    await screenshot(g.page, file);
  }
});
