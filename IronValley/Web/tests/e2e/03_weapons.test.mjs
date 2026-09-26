// Shooting checks on the real build: D8 muzzle obstruction, fire rate independent of frame
// pacing, and input release on Esc / focus loss using real Playwright keyboard and mouse.
import test, { after, before } from 'node:test';
import assert from 'node:assert/strict';
import { enterTestMode, launchGame, screenshot } from './helpers.mjs';

let g;
let markers;

before(async () => {
  g = await launchGame({ width: 960, height: 540 });
  await enterTestMode(g.page);
  markers = (await g.page.evaluate(() => window.__IV.getLevelInfo())).markers;
});

after(async () => {
  if (g) {
    assert.deepEqual(g.errors, [], `console errors: ${g.errors.join(' | ')}`);
    assert.deepEqual(g.failed, [], `failed requests: ${g.failed.join(' | ')}`);
    await g.close();
  }
});

async function fireSingle(page) {
  return page.evaluate(() => {
    const iv = window.__IV;
    iv.step(30); // let cadence / recoil settle
    const before = iv.getState().weapon.shotsFired;
    iv.mouseButton(0, true);
    iv.step(1);
    iv.mouseButton(0, false);
    iv.step(1);
    const s = iv.getState();
    return { fired: s.weapon.shotsFired - before, lastShot: s.weapon.lastShot, dummies: s.dummies };
  });
}

test('camera sees a target past a wall edge, muzzle is blocked: the wall takes the hit', async () => {
  const m = markers.corner_peek;
  const r = await g.page.evaluate((m) => {
    const iv = window.__IV;
    iv.refillAmmo();
    iv.resetRecoil();
    iv.teleportToMarker('corner_peek');
    iv.lookAt(m.pos[0], 1.2, -30);
    const before = iv.getState().dummies.find((d) => d.id === m.targetId).hits;
    return { before };
  }, m);
  const shot = await fireSingle(g.page);
  assert.equal(shot.fired, 1);
  assert.equal(shot.lastShot.cameraTarget, `dummy:${m.targetId}`, 'camera centre ray sees the dummy');
  assert.equal(shot.lastShot.hitTarget, `world:${m.wallId}`, `hit ${shot.lastShot.hitTarget}`);
  assert.equal(shot.lastShot.blocked, true);
  const after = shot.dummies.find((d) => d.id === m.targetId).hits;
  assert.equal(after, r.before, 'dummy must not be hit through the wall');
  // the impact is on the wall face, between the player and the dummy
  assert.ok(shot.lastShot.hitPoint[2] > -16.2 && shot.lastShot.hitPoint[2] < -15.8, `hit z ${shot.lastShot.hitPoint[2]}`);
  await g.page.evaluate(() => window.__IV.step(1, { render: true }));
  await screenshot(g.page, 'muzzle_blocked_corner.png');
});

test('same spot, a clear shot (camera and muzzle both clear) hits the dummy', async () => {
  const r = await g.page.evaluate(() => {
    const iv = window.__IV;
    iv.resetRecoil();
    iv.teleport(3.9, 0, -14.5, 0, 0); // step 1 m left of the corner edge
    iv.lookAt(4.95, 1.2, -30);
  });
  void r;
  const shot = await fireSingle(g.page);
  assert.equal(shot.lastShot.hitTarget, 'dummy:d_corner', `hit ${shot.lastShot.hitTarget}`);
  assert.equal(shot.lastShot.blocked, false);
});

test('crouched behind the 1.0 m cover: camera sees over it, muzzle hits the cover', async () => {
  const m = markers.cover_peek;
  await g.page.evaluate(() => {
    const iv = window.__IV;
    iv.resetRecoil();
    iv.teleportToMarker('cover_peek');
    iv.keyDown('KeyC');
    iv.step(30);
    iv.lookAt(0, 1.3, -30);
  });
  const shot = await fireSingle(g.page);
  await g.page.evaluate(() => {
    window.__IV.keyUp('KeyC');
    window.__IV.step(30);
  });
  assert.equal(shot.lastShot.cameraTarget, `dummy:${m.targetId}`);
  assert.ok(String(shot.lastShot.hitTarget).startsWith(`world:${m.wallId}`), `hit ${shot.lastShot.hitTarget}`);
});

test('shots in 3 s of held fire are identical at 30, 60 and 144 FPS frame pacing', async () => {
  const results = await g.page.evaluate(() => {
    const iv = window.__IV;
    const out = {};
    iv.teleportToMarker('impact_view');
    iv.setLook(0, 35); // into the sky: counting shots only, keep walls clean for the impact screenshot
    iv.setInfiniteAmmo(true);
    for (const fps of [30, 60, 144]) {
      iv.refillAmmo();
      iv.resetRecoil();
      iv.step(30); // trigger released, cadence reset
      iv.resetAccumulator();
      const before = iv.getState().weapon.shotsFired;
      const ticksBefore = iv.getState().ticks;
      iv.mouseButton(0, true);
      const frames = Math.round(3 * fps);
      iv.frames(1 / fps, frames, { render: false });
      iv.mouseButton(0, false);
      const s = iv.getState();
      out[fps] = { shots: s.weapon.shotsFired - before, ticks: s.ticks - ticksBefore, frames };
      iv.frames(1 / fps, fps, { render: false });
    }
    iv.setInfiniteAmmo(false);
    iv.refillAmmo();
    return out;
  });
  const interval = 60 / 750;
  const expected = Math.floor(3 / interval - 1e-9) + 1;
  console.log(`# held fire 3 s: ${JSON.stringify(results)} expected ${expected}`);
  assert.equal(results[30].ticks, 180);
  assert.equal(results[60].ticks, 180);
  assert.equal(results[144].ticks, 180);
  assert.equal(results[30].shots, results[60].shots);
  assert.equal(results[60].shots, results[144].shots);
  assert.equal(results[60].shots, expected);
});

test('held fire with the real magazine stops at 30 + 1 rounds (magazine + chamber, rules core)', async () => {
  const r = await g.page.evaluate(() => {
    const iv = window.__IV;
    iv.refillAmmo();
    iv.setLook(0, 35);
    iv.step(10);
    const before = iv.getState().weapon.shotsFired;
    iv.mouseButton(0, true);
    iv.step(240);
    iv.mouseButton(0, false);
    iv.step(1);
    const s = iv.getState().weapon;
    return { shots: s.shotsFired - before, magazine: s.magazine, chamber: s.chamber, capacity: s.capacity };
  });
  assert.equal(r.capacity, 30);
  assert.equal(r.shots, 31);
  assert.equal(r.magazine, 0);
  assert.equal(r.chamber, 0);
});

test('view model recoil stays bounded and frame-rate independent through the real loop (4-144 FPS)', async () => {
  // Real FixedStepLoop.frame -> Game.render path; only the WebGL draw calls are skipped (a
  // SwiftShader frame takes over a second). Before the fix the springs were integrated per
  // frame and diverged below ~15 FPS (the weapon flew off screen after one shot).
  const r = await g.page.evaluate(() => {
    const iv = window.__IV;
    iv.setDrawEnabled(false);
    iv.releaseAll();
    iv.teleportToMarker('impact_view');
    iv.setLook(0, 35);
    iv.refillAmmo();
    const hip = iv.getConfig().weapon.viewModel.hipPosition;
    const out = {};
    for (const fps of [4, 10, 20, 30, 60, 144]) {
      iv.resetRecoil();
      iv.step(120); // springs at rest
      iv.mouseButton(0, true);
      iv.step(1); // exactly one shot on a tick boundary
      iv.mouseButton(0, false);
      iv.resetAccumulator(); // frames start on that tick boundary at every frame rate
      const shots0 = iv.getState().weapon.shotsFired;
      let maxKick = 0;
      let maxRot = 0;
      let maxDev = 0;
      let finite = true;
      const at = {};
      const n = Math.round(fps * 1.0);
      for (let i = 1; i <= n; i++) {
        iv.frames(1 / fps, 1, { render: true });
        const v = iv.getState().viewModel;
        finite = finite && v.finite && Number.isFinite(v.kick) && Number.isFinite(v.kickRot);
        maxKick = Math.max(maxKick, Math.abs(v.kick));
        maxRot = Math.max(maxRot, Math.abs(v.kickRot));
        const h = v.holderPosition;
        maxDev = Math.max(maxDev, Math.hypot(h[0] - hip[0], h[1] - hip[1], h[2] - hip[2]));
        const t = i / fps;
        if (Math.abs(t - 0.5) < 1e-9 || Math.abs(t - 1) < 1e-9) at[t] = { kick: v.kick, kickRot: v.kickRot };
      }
      out[fps] = { maxKick, maxRot, maxDev, finite, at, extraShots: iv.getState().weapon.shotsFired - shots0 };
    }
    iv.setDrawEnabled(true);
    return out;
  });
  console.log(`# view model after one shot: ${JSON.stringify(Object.fromEntries(Object.entries(r).map(([k, v]) => [k, { kick: +v.maxKick.toFixed(4), rot: +v.maxRot.toFixed(4), dev: +v.maxDev.toFixed(4) }])))}`);
  for (const [fps, v] of Object.entries(r)) {
    assert.equal(v.finite, true, `${fps} FPS: non-finite pose`);
    assert.equal(v.extraShots, 0);
    assert.ok(v.maxKick < 0.02, `${fps} FPS: kick ${v.maxKick}`);
    assert.ok(v.maxRot < 0.06, `${fps} FPS: kickRot ${v.maxRot}`);
    assert.ok(v.maxDev < 0.01, `${fps} FPS: weapon moved ${v.maxDev} m from the hip pose`);
    for (const t of ['0.5', '1']) {
      assert.ok(Math.abs(v.at[t].kick - r[144].at[t].kick) < 1e-9 && Math.abs(v.at[t].kickRot - r[144].at[t].kickRot) < 1e-9, `${fps} FPS differs from 144 FPS at ${t} s`);
    }
  }
  // displayed peak at 60 and 144 FPS within 5 %
  assert.ok(Math.abs(r[60].maxRot - r[144].maxRot) / r[144].maxRot < 0.05, `peak kickRot 60 ${r[60].maxRot} vs 144 ${r[144].maxRot}`);
});

test('impact decals and sparks on a wall (screenshot)', async () => {
  const r = await g.page.evaluate(() => {
    const iv = window.__IV;
    iv.refillAmmo();
    iv.teleportToMarker('impact_view');
    const before = iv.getState().effects.decals;
    // five single shots in a small pattern on the thin wall
    const pts = [
      [21.35, 1.55],
      [21.55, 1.55],
      [21.45, 1.4],
      [21.35, 1.25],
      [21.55, 1.25],
    ];
    const hits = [];
    for (const [x, y] of pts) {
      iv.resetRecoil();
      iv.lookAt(x, y, -3.95);
      iv.step(20);
      iv.mouseButton(0, true);
      iv.step(1);
      iv.mouseButton(0, false);
      hits.push(iv.getState().weapon.lastShot.hitTarget);
    }
    // look slightly left of the group so the crosshair does not cover it; render right after the
    // last shot so its muzzle flash and sparks are visible
    iv.lookAt(21.1, 1.4, -3.95);
    iv.frames(1 / 60, 1, { render: true });
    return { added: iv.getState().effects.decals - before, hits };
  });
  assert.equal(r.added, 5, JSON.stringify(r));
  assert.ok(r.hits.every((h) => h === 'world:thin_wall'), JSON.stringify(r.hits));
  await screenshot(g.page, 'shot_impact.png');
});

test('Esc (real keyboard) pauses, releases the cursor and input, and firing stops', async () => {
  // resume through the real menu button, like a player would
  await g.page.evaluate(() => {
    const iv = window.__IV;
    iv.refillAmmo();
    iv.teleportToMarker('impact_view');
    iv.lookAt(21.2, 1.4, -3.95);
    iv.openMenu();
  });
  await g.page.click('.iv-btn-primary');
  await g.page.waitForFunction(() => window.__IV.getState().state === 'playing');
  // real mouse press on the canvas starts firing
  await g.page.mouse.move(480, 270);
  await g.page.mouse.down({ button: 'left' });
  const firing = await g.page.evaluate(() => {
    const iv = window.__IV;
    const before = iv.getState().weapon.shotsFired;
    iv.frames(1 / 60, 30, { render: false });
    const s = iv.getState();
    return { shots: s.weapon.shotsFired - before, trigger: s.weapon.triggerHeld, held: s.input.heldActions, lookMode: s.input.lookMode };
  });
  assert.ok(firing.shots >= 5, `firing before Esc: ${JSON.stringify(firing)}`);
  await g.page.keyboard.press('Escape');
  await g.page.waitForFunction(() => window.__IV.getState().state === 'paused', null, { timeout: 5000 });
  const afterEsc = await g.page.evaluate(() => {
    const iv = window.__IV;
    const before = iv.getState().weapon.shotsFired;
    iv.frames(1 / 60, 60, { render: false });
    const s = iv.getState();
    return {
      shots: s.weapon.shotsFired - before,
      trigger: s.weapon.triggerHeld,
      heldCodes: s.input.heldCodes,
      enabled: s.input.enabled,
      pointerLocked: s.input.pointerLocked,
      menuVisible: getComputedStyle(document.querySelector('.iv-menu')).display !== 'none',
      state: s.state,
    };
  });
  await g.page.mouse.up({ button: 'left' });
  assert.equal(afterEsc.state, 'paused');
  assert.equal(afterEsc.shots, 0, 'no shots after Esc');
  assert.equal(afterEsc.trigger, false);
  assert.deepEqual(afterEsc.heldCodes, []);
  assert.equal(afterEsc.enabled, false);
  assert.equal(afterEsc.pointerLocked, false);
  assert.equal(afterEsc.menuVisible, true);
  await screenshot(g.page, 'pause_menu.png');
});

test('window blur releases held keys and stops firing', async () => {
  await g.page.click('.iv-btn-primary');
  await g.page.waitForFunction(() => window.__IV.getState().state === 'playing');
  await g.page.keyboard.down('KeyW');
  await g.page.mouse.move(480, 270);
  await g.page.mouse.down({ button: 'left' });
  const during = await g.page.evaluate(() => {
    const iv = window.__IV;
    iv.frames(1 / 60, 20, { render: false });
    const s = iv.getState();
    return { held: s.input.heldCodes, speed: s.player.horizontalSpeed, shots: s.weapon.shotsFired };
  });
  assert.ok(during.held.includes('KeyW') && during.held.includes('Mouse0'), JSON.stringify(during));
  const afterBlur = await g.page.evaluate(() => {
    const iv = window.__IV;
    window.dispatchEvent(new Event('blur'));
    const shots0 = iv.getState().weapon.shotsFired;
    iv.frames(1 / 60, 60, { render: false });
    const s = iv.getState();
    return { held: s.input.heldCodes, speed: s.player.horizontalSpeed, shots: s.weapon.shotsFired - shots0, trigger: s.weapon.triggerHeld };
  });
  await g.page.keyboard.up('KeyW');
  await g.page.mouse.up({ button: 'left' });
  assert.deepEqual(afterBlur.held, []);
  assert.equal(afterBlur.shots, 0);
  assert.equal(afterBlur.trigger, false);
  assert.ok(afterBlur.speed < 0.01, `still moving at ${afterBlur.speed}`);
});

test('turning through the yaw wrap (every two full turns) does not twitch the weapon sway', async () => {
  const r = await g.page.evaluate(() => {
    const iv = window.__IV;
    iv.startGame();
    iv.pause();
    iv.setDrawEnabled(false);
    iv.releaseAll();
    iv.teleportToMarker('spawn');
    iv.step(2);
    const k = iv.getConfig().bindings.mouse.baseRadiansPerPixel * iv.getState().settings.mouseSensitivity;
    const perFrame = -3.0 / 60 / k; // steady left turn at 3 rad/s
    const rows = [];
    for (let i = 0; i < 360; i++) {
      iv._game.input.handleMouseMove(perFrame, 0); // goes through the game's input handler
      iv.frames(1 / 60, 1, { render: true });
      const s = iv.getState();
      rows.push({ yaw: s.player.yawDeg, swayX: s.viewModel.swayX, rotY: s.viewModel.holderRotation[1] });
    }
    iv.setDrawEnabled(true);
    return rows;
  });
  let wrapAt = -1;
  for (let i = 1; i < r.length; i++) if (Math.abs(r[i].yaw - r[i - 1].yaw) > 180) wrapAt = i;
  assert.ok(wrapAt > 60, `the turn crossed the yaw wrap (at frame ${wrapAt})`);
  let atWrap = 0;
  let steady = 0;
  let rotAtWrap = 0;
  let rotSteady = 0;
  for (let i = 61; i < r.length; i++) {
    const j = Math.abs(r[i].swayX - r[i - 1].swayX);
    const jr = Math.abs(r[i].rotY - r[i - 1].rotY);
    if (i >= wrapAt && i <= wrapAt + 2) {
      atWrap = Math.max(atWrap, j);
      rotAtWrap = Math.max(rotAtWrap, jr);
    } else {
      steady = Math.max(steady, j);
      rotSteady = Math.max(rotSteady, jr);
    }
  }
  assert.ok(atWrap <= steady + 1e-6, `sway step at the wrap ${atWrap} m vs steady turning ${steady} m`);
  assert.ok(rotAtWrap <= rotSteady + 1e-6, `holder rotation step at the wrap ${rotAtWrap} vs ${rotSteady} rad`);
});

test('a dummy that was just hit stands still behind the pause menu', async () => {
  const r = await g.page.evaluate(() => {
    const iv = window.__IV;
    const game = iv._game;
    iv.startGame();
    iv.pause();
    iv.setDrawEnabled(false);
    iv.releaseAll();
    iv.refillAmmo();
    iv.resetRecoil();
    iv.teleport(-5, 0, -20, 0, 0);
    iv.lookAt(-5, 1.3, -30);
    iv.step(10);
    const hits0 = iv.getState().weapon.hitsOnDummies;
    iv.mouseButton(0, true);
    iv.step(1);
    iv.mouseButton(0, false);
    const hit = iv.getState().weapon.hitsOnDummies - hits0;
    iv.openMenu();
    iv.frames(1 / 60, 2, { render: true }); // first paused tick
    const rots = [];
    for (let i = 0; i < 20; i++) {
      const until = performance.now() + 15; // real time passes between frames
      while (performance.now() < until) {
        /* busy wait */
      }
      iv.frames(1 / 60, 1, { render: true });
      rots.push(game.dummyView.items.map((it) => it.pivot.rotation.x));
    }
    const state = game.state;
    iv.startGame();
    iv.pause();
    iv.setDrawEnabled(true);
    return { hit, state, rots, lastShot: iv.getState().weapon.lastShot };
  });
  assert.equal(r.hit, 1, `the shot hit a dummy: ${JSON.stringify(r.lastShot)}`);
  assert.equal(r.state, 'paused');
  let maxChange = 0;
  for (let i = 1; i < r.rots.length; i++) for (let k = 0; k < r.rots[i].length; k++) maxChange = Math.max(maxChange, Math.abs(r.rots[i][k] - r.rots[i - 1][k]));
  assert.ok(Math.max(...r.rots[0].map(Math.abs)) > 0.005, 'the hit dummy is knocked back while paused');
  assert.equal(maxChange, 0, `dummy rotation changed by ${maxChange} rad between frames while paused`);
});

test('pause menu: an unchanged frame is not redrawn, a settings change is, play draws every frame', async () => {
  const r = await g.page.evaluate(() => {
    const iv = window.__IV;
    iv.startGame();
    iv.pause();
    iv.releaseAll();
    iv.teleportToMarker('spawn');
    iv.step(2);
    iv.openMenu();
    // let per-frame easing (weapon sway / sprint pose left over from earlier input, eye
    // adaptation) come to rest without the slow software draws, then draw once
    iv.setDrawEnabled(false);
    iv.frames(1 / 60, 180, { render: true });
    iv.setDrawEnabled(true);
    iv.frames(1 / 60, 2, { render: true });
    const d0 = iv.getState().draws;
    iv.frames(1 / 60, 30, { render: true });
    const d1 = iv.getState().draws;
    iv.setSetting('fovDeg', 90); // visible change behind the menu
    iv.frames(1 / 60, 2, { render: true });
    const d2 = iv.getState().draws;
    iv.setSetting('fovDeg', 80);
    iv.startGame();
    iv.pause();
    const d3 = iv.getState().draws;
    iv.frames(1 / 60, 3, { render: true });
    const d4 = iv.getState().draws;
    return { state: iv.getState().state, idle: d1 - d0, afterSetting: d2 - d1, playing: d4 - d3 };
  });
  assert.equal(r.idle, 0, `redraws of an unchanged paused frame: ${r.idle}`);
  assert.ok(r.afterSetting >= 1, 'FOV change behind the menu is drawn');
  assert.equal(r.playing, 3, 'every frame is drawn while playing');
});
