// Optics in the real build (headless Chromium, SwiftShader): mounting and irons, ADS alignment of the drawn reticle
// with the hitscan direction (incl. recoil) for every optic, no reticle swim under bob / sway, no flicker / NaN
// frames around a shot (pixel statistics of consecutive frames), sensitivity scaling, the PiP target size, the
// loadout screen, the armory crate, the timed backpack swap, bots' LOD1 optics. ADS screenshots per optic.
import test, { after, before } from 'node:test';
import assert from 'node:assert/strict';
import { enterTestMode, launchGame, screenshot } from './helpers.mjs';

let g;
const W = 960;
const H = 540;
const OPTICS = ['IVH1', 'IVR1', 'IVP2', 'IVS3', 'IVS6'];

before(async () => {
  g = await launchGame({ width: W, height: H });
  await enterTestMode(g.page);
  // in-page helpers: render one frame through the real loop and read the canvas back
  await g.page.evaluate(() => {
    const game = window.__IV._game;
    const gl = game.renderer.renderer.getContext();
    // dt > 0: one frame through the real loop (interpolated poses); dt = 0: draw the current tick (alpha 1)
    window.__ivFrame = (dt = 1 / 60) => {
      if (dt > 0) game.loop.frame(dt, { render: true });
      else {
        game._drawDirty = true;
        game.render(1, 0);
      }
      const w = gl.drawingBufferWidth;
      const h = gl.drawingBufferHeight;
      const buf = new Uint8Array(w * h * 4);
      gl.readPixels(0, 0, w, h, gl.RGBA, gl.UNSIGNED_BYTE, buf);
      return { w, h, buf };
    };
    // red (illuminated reticle) pixels near a screen point (top-left origin), luminance of regions
    window.__ivStats = (f, cx, cy, { r = 24, ringIn = 70, ringOut = 150, corner = 40 } = {}) => {
      const { w, h, buf } = f;
      let n = 0;
      let sx = 0;
      let sy = 0;
      let ringS = 0;
      let ringN = 0;
      let all = 0;
      let bad = 0;
      let cornerS = 0;
      let cornerN = 0;
      for (let y = 0; y < h; y++) {
        const yy = h - 1 - y;
        for (let x = 0; x < w; x++) {
          const k = (y * w + x) * 4;
          const R = buf[k];
          const G = buf[k + 1];
          const B = buf[k + 2];
          const l = 0.2126 * R + 0.7152 * G + 0.0722 * B;
          all += l;
          if (!(R + G + B >= 0)) bad++;
          const d = Math.hypot(x + 0.5 - cx, yy + 0.5 - cy);
          if (d <= r && R > 150 && R > 2 * G && R > 2 * B) {
            n++;
            sx += x + 0.5;
            sy += yy + 0.5;
          }
          if (d >= ringIn && d < ringOut) {
            ringS += l;
            ringN++;
          }
          if ((x < corner || x >= w - corner) && (yy < corner || yy >= h - corner)) {
            cornerS += l;
            cornerN++;
          }
        }
      }
      return { red: n, cx: n ? sx / n : null, cy: n ? sy / n : null, ring: ringS / ringN, mean: all / (w * h), corners: cornerS / cornerN, bad };
    };
  });
});

after(async () => {
  if (g) await g.close();
});

const ev = (fn, arg) => g.page.evaluate(fn, arg);

/**
 * Largest transient brightness excursion in a frame series: for each frame, how far it stands above (or below)
 * the lowest (highest) value on BOTH sides within `w` frames. A monotonic change (motion) gives 0; the old
 * muzzle-flash light on the optic housing gave ~13 (0..255 luminance) for two frames.
 */
function flashProminence(v, w = 3) {
  let best = 0;
  for (let p = 1; p < v.length - 1; p++) {
    const L = v.slice(Math.max(0, p - w), p);
    const R = v.slice(p + 1, p + 1 + w);
    const up = Math.min(v[p] - Math.min(...L), v[p] - Math.min(...R));
    const down = Math.min(Math.max(...L) - v[p], Math.max(...R) - v[p]);
    best = Math.max(best, up, down);
  }
  return best;
}

/** Practice, ADS through `optic` at the 30 m target board, settled. */
async function aimWith(optic, { spare = null, look = [0, 1.45, -30], pos = [0, 0, 8] } = {}) {
  return ev(
    ({ optic, spare, look, pos }) => {
      const iv = window.__IV;
      iv.startGame();
      iv.pause();
      iv.setRenderOnStep(false);
      iv.setSetting('adaptiveResolution', false);
      iv.setSetting('renderScale', 1);
      iv.releaseAll();
      iv.setInfiniteAmmo(true);
      const r = iv.setOptic(optic, spare);
      iv.teleport(pos[0], pos[1], pos[2], 0, 0);
      iv.lookAt(look[0], look[1], look[2]);
      iv.resetRecoil();
      iv.mouseButton(2, true);
      iv.step(50);
      return r;
    },
    { optic, spare, look, pos },
  );
}

test('optic assets load; built-in optic hidden; irons fold -90 deg (top towards the stock) with an optic, stand up for irons', async () => {
  const s = await ev(() => window.__IV.getState());
  assert.deepEqual([...s.opticAssets.loaded].sort(), [...OPTICS].sort(), JSON.stringify(s.opticAssets));
  assert.deepEqual(s.opticAssets.errors, []);
  for (const id of ['IVR1', 'irons']) {
    await aimWith(id);
    const d = await ev(() => {
      window.__IV.mouseButton(2, false);
      window.__IV.step(30);
      window.__IV.renderNow();
      return window.__IV.getOpticDebug();
    });
    assert.ok(d.hiddenRifleNodes >= 5, `built-in optic hidden (${d.hiddenRifleNodes})`);
    assert.equal(d.irons.leaf.length, 2, 'rear_sight + front_sight bones');
    for (const l of d.irons.leaf) {
      if (id === 'irons') {
        assert.ok(l.dy > 0.028 && Math.abs(l.dx) < 0.003, `${l.bone} deployed: ${JSON.stringify(l)}`);
      } else {
        // folded: the leaf top moved towards the stock (-X), not forward into the optic (+X), and lies flat
        assert.ok(l.dx < -0.028 && Math.abs(l.dy) < 0.003, `${l.bone} folded: ${JSON.stringify(l)}`);
      }
    }
    assert.equal(d.irons.folded, id !== 'irons');
  }
});

test('ADS per optic: the drawn reticle centre is the hitscan direction (incl. recoil); screenshots', async () => {
  for (const id of OPTICS) {
    await aimWith(id);
    const r = await ev((id) => {
      const iv = window.__IV;
      // a short burst so recoil offsets the aim, then look at a frame on a tick boundary (alpha 1)
      iv.mouseButton(0, true);
      iv.step(12);
      iv.mouseButton(0, false);
      iv.step(2);
      const f = window.__ivFrame(0);
      const d = iv.getOpticDebug();
      const st = window.__ivStats(f, d.aimPx[0], d.aimPx[1], { r: 30 });
      const w = iv.getState().weapon;
      return { d, st, recoil: [w.recoilPitchDeg, w.recoilYawDeg], id };
    }, id);
    const { d, st } = r;
    assert.equal(d.optic, id);
    assert.equal(d.visual, id);
    assert.equal(d.ads, 1);
    assert.ok(Math.abs(r.recoil[0]) > 0.05, `${id}: recoil in effect (${r.recoil})`);
    // the aim (hitscan direction of the next round) is the camera axis: screen centre
    assert.ok(d.aimCamAngleDeg < 1e-4, `${id}: aim vs camera ${d.aimCamAngleDeg}`);
    if (d.mode === 'collimated') {
      // the collimated reticle is looked up along the optic axis; that axis projects onto the aim point
      assert.ok(Math.hypot(d.axisPx[0] - d.aimPx[0], d.axisPx[1] - d.aimPx[1]) < 0.05, `${id} axis ${d.axisPx} aim ${d.aimPx}`);
    } else if (d.mode === 'pip') {
      assert.ok(d.pipAxisAimDeg < 1e-4, `${id}: PiP camera axis vs aim ${d.pipAxisAimDeg} deg`);
      assert.ok(Math.hypot(d.ocularPx[0] - d.aimPx[0], d.ocularPx[1] - d.aimPx[1]) < 0.5, `${id}: ocular centre ${d.ocularPx} vs aim ${d.aimPx}`);
      assert.ok(d.view.pipActive && d.view.eyebox > 0.99, `${id}: eyepiece image on (${JSON.stringify(d.view)})`);
    } else {
      assert.ok(d.view.scoped, `${id}: scoped in`);
      assert.ok(Math.abs(d.cameraFov - 4.1253) < 1e-3, `${id}: 6x camera FOV ${d.cameraFov}`);
      assert.ok(Math.hypot(d.aimPx[0] - W / 2, d.aimPx[1] - H / 2) < 0.05, `${id}: aim ${d.aimPx}`);
    }
    // pixels: the lit reticle (red) is centred on the projected aim point
    assert.ok(st.red >= 3, `${id}: reticle visible (${st.red} red px)`);
    const off = Math.hypot(st.cx - d.aimPx[0], st.cy - d.aimPx[1]);
    const tol = id === 'IVP2' ? 1.5 : 0.75; // the IV-P2 chevron's centroid lies below its apex (the point of aim) by design
    assert.ok(off < tol, `${id}: reticle centroid ${st.cx},${st.cy} vs aim ${d.aimPx} (${off.toFixed(2)} px)`);
    assert.equal(st.bad, 0);
    await screenshot(g.page, `optic_ads_${id}.png`);
  }
  await ev(() => {
    window.__IV.mouseButton(2, false);
    window.__IV.step(30);
  });
});

test('no reticle swim in full ADS while walking (head bob) and turning (sway)', async () => {
  for (const id of ['IVR1', 'IVH1', 'IVS3']) {
    await aimWith(id, { pos: [0, 0, 14] });
    const r = await ev(() => {
      const iv = window.__IV;
      iv.keyDown('KeyW');
      const out = [];
      for (let i = 0; i < 24; i++) {
        if (i % 6 === 3) iv.mouseMove(i % 12 === 3 ? 6 : -6, 2); // look sway input
        const f = window.__ivFrame((0.8 / 60) * (1 + (i % 3) * 0.3)); // uneven frames: interpolated poses
        const d = iv.getOpticDebug();
        const st = window.__ivStats(f, d.aimPx[0], d.aimPx[1], { r: 30 });
        out.push({ bob: iv.getState().player.cameraFx.bobAmount ?? null, axisErr: d.mode === 'collimated' ? Math.hypot(d.axisPx[0] - d.aimPx[0], d.axisPx[1] - d.aimPx[1]) : Math.hypot(d.ocularPx[0] - d.aimPx[0], d.ocularPx[1] - d.aimPx[1]), dx: st.cx - d.aimPx[0], dy: st.cy - d.aimPx[1], red: st.red });
      }
      iv.keyUp('KeyW');
      iv.mouseButton(2, false);
      iv.step(20);
      const p = iv.getState().player;
      return { out, moved: p.position };
    });
    const maxAxis = Math.max(...r.out.map((f) => f.axisErr));
    assert.ok(maxAxis < 0.1, `${id}: reticle axis vs aim up to ${maxAxis.toFixed(3)} px while walking`);
    const vis = r.out.filter((f) => f.red > 0);
    assert.equal(vis.length, r.out.length, `${id}: reticle visible in every frame`);
    const rx = Math.max(...vis.map((f) => f.dx)) - Math.min(...vis.map((f) => f.dx));
    const ry = Math.max(...vis.map((f) => f.dy)) - Math.min(...vis.map((f) => f.dy));
    assert.ok(rx < 0.5 && ry < 0.5, `${id}: reticle swims ${rx.toFixed(2)} x ${ry.toFixed(2)} px (walking, looking)`);
  }
});

test('no flicker or NaN frames around a shot in ADS (consecutive-frame pixel statistics)', async () => {
  for (const id of OPTICS) {
    await aimWith(id);
    const frames = await ev(() => {
      const iv = window.__IV;
      const out = [];
      for (let i = 0; i < 9; i++) {
        if (i === 3) iv.mouseButton(0, true);
        const f = window.__ivFrame(1 / 60);
        if (i === 3) iv.mouseButton(0, false);
        const d = iv.getOpticDebug();
        // reference: the drawn camera axis (screen centre) = the aim at this frame's interpolated recoil; the next
        // round's hitscan direction is up to one tick of recoil motion ahead of an interpolated frame
        const c = [d.canvas[0] / 2, d.canvas[1] / 2];
        const st = window.__ivStats(f, c[0], c[1], { r: 30, ringIn: 80, ringOut: 150 });
        const feel = iv.getWeaponFeel();
        out.push({ ...st, aim: c, aimTick: d.aimCamAngleDeg, flash: feel.viewModel.flashVisible, finite: iv.getState().viewModel.finite, shots: iv.getState().weapon.shotsFired });
      }
      iv.mouseButton(2, false);
      iv.step(20);
      return out;
    });
    assert.ok(frames[8].shots > frames[0].shots, `${id}: a round was fired`);
    for (const [i, f] of frames.entries()) {
      assert.equal(f.bad, 0, `${id} frame ${i}: NaN pixels`);
      assert.ok(f.finite, `${id} frame ${i}: view model pose finite`);
      assert.ok(f.mean > 8, `${id} frame ${i}: not a black frame (${f.mean.toFixed(1)})`);
      assert.ok(f.red >= 3, `${id} frame ${i}: reticle visible (${f.red})`);
      const off = Math.hypot(f.cx - f.aim[0], f.cy - f.aim[1]);
      assert.ok(off < (id === 'IVP2' ? 1.5 : 0.75), `${id} frame ${i}: reticle ${off.toFixed(2)} px off the aim`);
      assert.equal(f.flash, false, `${id} frame ${i}: no muzzle-flash sprite in full ADS`);
      assert.ok(f.aimTick < 0.6, `${id} frame ${i}: drawn aim within one tick of recoil of the hitscan direction (${f.aimTick})`);
    }
    // brightness flashes of the optic housing / eyepiece surroundings: the prominence of any transient peak or dip
    // (up and back within 3 frames). The image may move with the recoil kick (a step), it must not flash.
    const ring = frames.map((f) => f.ring);
    const maxFlash = flashProminence(ring);
    assert.ok(maxFlash < 3, `${id}: housing brightness flash ${maxFlash.toFixed(2)} (${ring.map((v) => v.toFixed(1)).join(' ')})`);
    if (id === 'IVS6') for (const f of frames) assert.ok(f.corners < 1, `6x: outside the field stop stays black (${f.corners})`);
  }
});

test('mouse sensitivity scales with the magnification (setting), PiP target never smaller than the ocular disc', async () => {
  const base = await ev(() => window.__IV.getConfig().bindings.mouse.baseRadiansPerPixel * window.__IV.getState().settings.mouseSensitivity);
  const res = {};
  for (const id of [...OPTICS, 'irons']) {
    await aimWith(id);
    res[id] = await ev(() => {
      const iv = window.__IV;
      iv.renderNow();
      const game = iv._game;
      const y0 = game.player.yaw;
      iv.mouseMove(100, 0);
      const d = iv.getOpticDebug();
      return { dyaw: y0 - game.player.yaw, scale: game.player.lastLookScale, view: d.view, fov: d.cameraFov };
    });
    assert.ok(Math.abs(res[id].dyaw - 100 * base * res[id].scale) < 1e-9, `${id}: yaw per 100 px ${res[id].dyaw}`);
  }
  assert.ok(Math.abs(res.IVR1.scale - 1) < 1e-9 && Math.abs(res.IVH1.scale - 1) < 1e-9, '1x: no zoom, no change');
  assert.ok(Math.abs(res.IVP2.scale - 0.5) < 1e-6);
  assert.ok(Math.abs(res.IVS3.scale - 1 / 3) < 1e-6);
  assert.ok(res.IVS6.scale < 0.1 && res.IVS6.scale > 0.05, `6x ${res.IVS6.scale}`);
  for (const id of ['IVP2', 'IVS3']) {
    const v = res[id].view;
    assert.ok(v.rtSize >= v.discPx - 1e-6, `${id}: render target ${v.rtSize} px < disc ${v.discPx.toFixed(1)} px`);
    assert.ok(v.discPx > 100, `${id}: disc ${v.discPx}`);
  }
  // setting off: no magnification scaling in the PiP
  await ev(() => window.__IV.setSetting('adsSensitivityScaling', false));
  await aimWith('IVS3');
  const off = await ev(() => {
    window.__IV.renderNow();
    const game = window.__IV._game;
    const y0 = game.player.yaw;
    window.__IV.mouseMove(100, 0);
    return y0 - game.player.yaw;
  });
  assert.ok(Math.abs(off - 100 * base) < 1e-9, `scaling off: ${off}`);
  await ev(() => {
    window.__IV.setSetting('adsSensitivityScaling', true);
    window.__IV.mouseButton(2, false);
    window.__IV.step(30);
  });
});

test('loadout screen: optic + spare (Czech names), deploy, HUD shows the optic and the spare', async () => {
  const { page } = g;
  await ev(() => {
    window.__IV.resume();
    window.__IV.toTitle();
  });
  await page.click('button[data-action="start"]');
  await page.waitForFunction(() => window.__IV.getMenu().screen === 'loadout');
  const text = await ev(() => document.querySelector('.iv-menu').textContent);
  for (const n of ['Holografický zaměřovač 1×', 'Kolimátor 1×', 'Hranolový 2×', 'Puškohled 3×', 'Puškohled 6×', 'Mechanická mířidla', 'Batoh:', 'Žádná']) assert.ok(text.includes(n), `loadout lists ${n}`);
  await page.click('button[data-action="optic-IVS6"]');
  await page.click('button[data-action="spare-IVR1"]');
  // the spare list never offers the primary
  assert.equal(await ev(() => !!document.querySelector('button[data-action="spare-IVS6"]')), false);
  assert.equal(await ev(() => document.querySelector('button[data-action="spare-IVR1"]').getAttribute('aria-pressed')), 'true');
  await screenshot(page, 'menu_loadout_optics.png');
  await page.click('button[data-action="deploy"]');
  await page.waitForFunction(() => window.__IV.getState().state === 'playing');
  const r = await ev(() => {
    const iv = window.__IV;
    iv.pause();
    iv.setAIEnabled(false);
    iv.step(1);
    iv.renderNow();
    return { s: iv.getState(), hud: iv.getHud() };
  });
  assert.equal(r.s.optic, 'IVS6');
  assert.equal(r.s.opticSpare, 'IVR1');
  assert.match(r.hud.weapon, /puškohled 6×/);
  assert.match(r.hud.optic, /batoh: kolimátor 1× \[B\]/);
});

test('armory crate: E at the own spawn crate opens it, the choice applies at once, not at an enemy crate; screenshot', async () => {
  const { page } = g;
  const r = await ev(async () => {
    const iv = window.__IV;
    await iv.startMatch({ level: 'test_range', bots: [0, 1, 1], seed: 9, skipPreRound: true, ai: false, optic: 'IVR1', spare: 'IVS3' });
    iv.pause();
    const lvl = iv.getLevelInfo().match.armories;
    const own = lvl.find((a) => a.team === 0);
    const enemy = lvl.find((a) => a.team === 1);
    // enemy crate: no prompt, E does nothing
    iv.placeCombatant('player', enemy.center[0] + (enemy.center[0] < 0 ? 1.1 : -1.1), 0, enemy.center[2], 0, 0);
    iv.step(2);
    iv.renderNow();
    const promptEnemy = iv.getHud().prompt;
    iv.keyDown('KeyE');
    iv.step(1);
    iv.keyUp('KeyE');
    const stateEnemy = iv.getState().state;
    // own crate
    iv.placeCombatant('player', own.center[0] - 1.1, 0, own.center[2], -90, -10);
    iv.step(2);
    iv.renderNow();
    const prompt = iv.getHud().prompt;
    iv.keyDown('KeyE');
    iv.step(1);
    iv.keyUp('KeyE');
    return { promptEnemy, stateEnemy, prompt, state: iv.getState().state, screen: iv.getMenu().screen };
  });
  assert.equal(r.promptEnemy, '');
  assert.equal(r.stateEnemy, 'playing');
  assert.match(r.prompt, /zbrojní bedna/);
  assert.equal(r.state, 'paused');
  assert.equal(r.screen, 'armory');
  const menuText = await ev(() => document.querySelector('.iv-menu').textContent);
  assert.match(menuText, /Zbrojní bedna/);
  assert.match(menuText, /Na pušce: Kolimátor 1×/);
  await page.click('button[data-action="optic-IVP2"]');
  await page.click('button[data-action="spare-IVS6"]');
  const s1 = await ev(() => window.__IV.getState());
  assert.equal(s1.optic, 'IVP2');
  assert.equal(s1.opticSpare, 'IVS6');
  assert.equal(s1.opticView.id, 'IVP2', 'the rifle shows the new optic at once');
  assert.match(await ev(() => document.querySelector('.iv-menu').textContent), /Na pušce: Hranolový 2×/);
  await screenshot(page, 'armory_menu.png');
  await page.click('button[data-action="resume"]');
  await page.waitForFunction(() => window.__IV.getState().state === 'playing');
  await ev(() => window.__IV.pause());
});

test('backpack swap (B): ~3 s timed, no fire or ADS meanwhile, HUD progress, interruptible, phase events', async () => {
  const r = await ev(() => {
    const iv = window.__IV;
    iv.startGame();
    iv.pause();
    iv.releaseAll();
    iv.setInfiniteAmmo(true);
    iv.setOptic('IVR1', 'IVS3');
    iv.teleport(0, 0, 8, 0, 0);
    iv.step(10);
    iv.watchEvents(['optic:swap_started', 'optic:swap_phase', 'optic:swap_finished', 'optic:swap_interrupted', 'optic:changed']);
    const game = iv._game;
    const shots0 = game.weapon.state.shotsFired;
    iv.keyDown('KeyB');
    iv.step(1);
    iv.keyUp('KeyB');
    iv.mouseButton(0, true);
    iv.mouseButton(2, true);
    iv.step(90);
    iv.renderNow();
    const mid = { shots: game.weapon.state.shotsFired - shots0, ads: game.weapon.state.ads, hud: iv.getHud(), st: iv.getState().opticLoadout };
    iv.step(89);
    const before = iv.getState().opticLoadout.mounted;
    iv.step(2);
    iv.mouseButton(0, false);
    iv.mouseButton(2, false);
    iv.step(5);
    iv.renderNow();
    const done = { st: iv.getState().opticLoadout, hud: iv.getHud(), view: iv.getState().opticView.id, events: iv.takeEvents() };
    // interrupt with B again after 1 s
    iv.keyDown('KeyB');
    iv.step(1);
    iv.keyUp('KeyB');
    iv.step(60);
    iv.keyDown('KeyB');
    iv.step(1);
    iv.keyUp('KeyB');
    iv.step(30);
    const intr = { st: iv.getState().opticLoadout, events: iv.takeEvents() };
    return { mid, before, done, intr };
  });
  assert.equal(r.mid.shots, 0, 'no round fired during the swap');
  assert.equal(r.mid.ads, 0, 'no ADS during the swap');
  assert.equal(r.mid.hud.swapVisible, true, 'HUD shows the swap progress');
  assert.ok(Math.abs(r.mid.st.progress - 0.5) < 0.02, `progress ${r.mid.st.progress}`);
  assert.equal(r.before, 'IVR1', 'nothing changes before 3 s');
  assert.equal(r.done.st.mounted, 'IVS3');
  assert.equal(r.done.st.spare, 'IVR1');
  assert.equal(r.done.view, 'IVS3');
  assert.match(r.done.hud.weapon, /puškohled 3×/);
  assert.match(r.done.hud.optic, /batoh: kolimátor 1×/);
  const phases = r.done.events.filter((e) => e.name === 'optic:swap_phase').map((e) => e.phase);
  assert.deepEqual(phases, ['lower', 'detach', 'stow', 'attach', 'raise']);
  const t0 = r.done.events.find((e) => e.name === 'optic:swap_started').tick;
  const t1 = r.done.events.find((e) => e.name === 'optic:swap_finished').tick;
  assert.equal(t1 - t0, 180, 'exactly 3 s at 60 Hz');
  assert.equal(r.intr.st.mounted, 'IVS3', 'interrupted: optic unchanged');
  assert.ok(r.intr.events.some((e) => e.name === 'optic:swap_interrupted' && e.reason === 'swapKey'));
});

test('bots carry optics by role, drawn as the LOD1 models on their rifles', async () => {
  const r = await ev(async () => {
    const iv = window.__IV;
    await iv.startMatch({ level: 'ai_arena', bots: [5, 6, 6], seed: 4, skipPreRound: true, ai: false });
    iv.pause();
    iv.step(2);
    iv.renderNow();
    return { views: iv.getCombatantViews(), list: iv.listCombatants() };
  });
  const bots = r.list.filter((c) => !c.isPlayer);
  assert.equal(bots.length, 17);
  for (const b of bots) assert.ok(b.optic && b.opticRole, b.id);
  const byId = new Map(r.views.map((v) => [v.id, v]));
  for (const b of bots) {
    const v = byId.get(b.id);
    assert.equal(v.optic, b.optic.mounted, b.id);
    if (v.visible && b.optic.mounted !== 'irons') assert.ok(v.opticLod1, `${b.id}: LOD1 optic attached`);
  }
  assert.ok(bots.some((b) => b.optic.mounted === 'IVS6'), 'marksmen with the 6x');
  assert.deepEqual(g.errors, []);
  assert.deepEqual(g.failed, []);
});
