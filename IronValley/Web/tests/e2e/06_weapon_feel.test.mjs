// Weapon feel on the real build (GUN-03, playtest "no recoil"): visible camera + view-model kick through
// the real FixedStepLoop.frame -> Game.render path, the crosshair / sight never lying (hip and ADS),
// identical bursts at 30 / 60 / 144 FPS pacing, muzzle flash frames, casings, and screenshots mid-burst
// (the WebGL draw is only enabled for the screenshots; SwiftShader frames are slow).
import test, { after, before } from 'node:test';
import assert from 'node:assert/strict';
import { decodePng, enterTestMode, launchGame, screenshot } from './helpers.mjs';

let g;

before(async () => {
  g = await launchGame({ width: 960, height: 540 });
  await enterTestMode(g.page);
  await g.page.evaluate(() => {
    const iv = window.__IV;
    iv.setDrawEnabled(false);
    iv.setInfiniteAmmo(true);
  });
});

after(async () => {
  if (g) {
    assert.deepEqual(g.errors, [], `console errors: ${g.errors.join(' | ')}`);
    assert.deepEqual(g.failed, [], `failed requests: ${g.failed.join(' | ')}`);
    await g.close();
  }
});

/** In-page helpers (serialised into each evaluate). */
const PAGE_HELPERS = `
  const iv = window.__IV;
  const R2D = 180 / Math.PI;
  function selectWeapon(slot) {
    const st = iv.getState();
    if (st.player.activeWeapon !== slot) {
      iv.keyDown(slot === 0 ? 'Digit1' : 'Digit2');
      iv.step(1);
      iv.keyUp(slot === 0 ? 'Digit1' : 'Digit2');
      iv.step(50);
    }
  }
  function setup({ ads = false, crouch = false, slot = 0, seed = 1234, pitch = 4 } = {}) {
    iv.releaseAll();
    iv.step(2);
    selectWeapon(slot);
    iv.teleportToMarker('impact_view');
    iv.setLook(0, pitch);
    iv.refillAmmo();
    iv.resetRecoil();
    iv.setRecoilSeed(seed);
    if (ads) iv.mouseButton(2, true);
    if (crouch) iv.keyDown('KeyC');
    iv.step(120);
    iv.resetAccumulator();
    iv.frames(1 / 60, 1, { render: true });
  }
  function teardown() {
    iv.mouseButton(0, false);
    iv.mouseButton(2, false);
    iv.keyUp('KeyC');
    iv.step(2);
  }
  function angle(a, b) {
    const cx = a[1] * b[2] - a[2] * b[1];
    const cy = a[2] * b[0] - a[0] * b[2];
    const cz = a[0] * b[1] - a[1] * b[0];
    return Math.atan2(Math.hypot(cx, cy, cz), a[0] * b[0] + a[1] * b[1] + a[2] * b[2]) * R2D;
  }
  function norm(v) {
    const l = Math.hypot(v[0], v[1], v[2]);
    return [v[0] / l, v[1] / l, v[2] / l];
  }
`;

test('recoil is clearly visible at 60 FPS (camera + view model), scales with stance and recovers', async () => {
  const r = await g.page.evaluate(`(() => {${PAGE_HELPERS}
    function single(o) {
      setup(o);
      const f0 = iv.getWeaponFeel();
      const h0 = f0.viewModel.holderPosition;
      const s0 = iv.getState().weapon.shotsFired;
      iv.mouseButton(0, true);
      iv.frames(1 / 60, 1, { render: true });
      iv.mouseButton(0, false);
      let cam = 0, back = 0, pitch = 0, roll = 0, camRoll = 0, dev = 0;
      const trace = [];
      for (let i = 0; i < 90; i++) {
        iv.frames(1 / 60, 1, { render: true });
        const f = iv.getWeaponFeel();
        const dp = f.camera.pitchDeg - f0.camera.pitchDeg;
        trace.push(dp);
        cam = Math.max(cam, dp);
        back = Math.max(back, f.viewModel.pose.back);
        pitch = Math.max(pitch, Math.abs(f.viewModel.pose.pitch) * R2D);
        roll = Math.max(roll, Math.abs(f.viewModel.pose.roll) * R2D);
        camRoll = Math.max(camRoll, Math.abs(f.camera.rollDeg));
        const h = f.viewModel.holderPosition;
        dev = Math.max(dev, Math.hypot(h[0] - h0[0], h[1] - h0[1], h[2] - h0[2]));
      }
      const settled = trace[trace.length - 1];
      const iPeak = trace.indexOf(cam);
      let rec = null;
      for (let i = iPeak; i < trace.length; i++) if (Math.abs(trace[i] - settled) <= 0.1 * (cam - settled)) { rec = (i + 1) / 60; break; }
      const shots = iv.getState().weapon.shotsFired - s0;
      teardown();
      return { shots, cam, back, pitch, roll, camRoll, dev, rec, settled };
    }
    return {
      hip: single({}),
      ads: single({ ads: true }),
      crouch: single({ crouch: true }),
      pistolHip: single({ slot: 1 }),
      pistolAds: single({ slot: 1, ads: true }),
      cfg: iv.getConfig().weapon.feel,
    };
  })()`);
  await g.page.evaluate(`(() => {${PAGE_HELPERS} selectWeapon(0); })()`);
  const fmt = (o) => Object.fromEntries(Object.entries(o).map(([k, v]) => [k, typeof v === 'number' ? +v.toFixed(4) : v]));
  console.log(`# single shot: ${JSON.stringify({ hip: fmt(r.hip), ads: fmt(r.ads), crouch: fmt(r.crouch), pistolHip: fmt(r.pistolHip), pistolAds: fmt(r.pistolAds) })}`);
  for (const k of ['hip', 'ads', 'crouch', 'pistolHip', 'pistolAds']) assert.equal(r[k].shots, 1, k);
  // rifle, hip: camera kick >= 0.4 deg, weapon >= 1.5 cm back, >= 2 deg muzzle rise, visible roll (was 0.6 mm / 0.17 deg)
  assert.ok(r.hip.cam >= 0.4, `hip camera kick ${r.hip.cam}`);
  assert.ok(r.hip.back >= 0.015 && r.hip.pitch >= 2 && r.hip.roll >= 0.5, `hip view model ${JSON.stringify(r.hip)}`);
  assert.ok(r.hip.camRoll >= 0.2, `visual camera roll ${r.hip.camRoll}`);
  assert.ok(r.hip.dev < 0.06, `weapon stays in view (${r.hip.dev} m)`);
  // stance: ADS and crouch kick less; ADS does not rotate the weapon (sight stays on the aim)
  assert.ok(r.ads.cam < r.hip.cam && r.ads.cam >= 0.25, `ADS camera ${r.ads.cam}`);
  assert.ok(r.crouch.cam < r.hip.cam, `crouch camera ${r.crouch.cam}`);
  assert.ok(r.ads.pitch < 1e-6, `ADS muzzle rotation ${r.ads.pitch}`);
  // recovery: within 10 % of the settled view in 0.6 s
  for (const k of ['hip', 'ads', 'pistolHip']) assert.ok(r[k].rec !== null && r[k].rec <= 0.6, `${k} recovery ${r[k].rec} s`);
  // pistol flips harder than the rifle per round
  assert.ok(r.pistolHip.cam > r.hip.cam && r.pistolHip.pitch >= 4, `pistol ${JSON.stringify(r.pistolHip)}`);
});

test('crosshair and sight never lie: every round goes along the camera rendered from the state it was fired in (hip, ADS, pistol)', async () => {
  const r = await g.page.evaluate(`(() => {${PAGE_HELPERS}
    function burst(o, ticks) {
      setup(o);
      let worst = 0, n = 0, worstSight = 0, worstBarrel = 0, maxClimb = 0;
      const p0 = iv.getWeaponFeel().camera.pitchDeg;
      let last = iv.getState().weapon.shotsFired;
      for (let t = 0; t < ticks; t++) {
        const tap = o.slot === 1 ? t % 10 < 2 : true;
        iv.mouseButton(0, tap);
        // one tick + a frame exactly on the tick boundary: the render shows the state the round used
        iv.frames(1 / 60, 1, { render: true });
        const s = iv.getState().weapon;
        const f = iv.getWeaponFeel();
        maxClimb = Math.max(maxClimb, f.camera.pitchDeg - p0);
        if (s.shotsFired > last) {
          const ls = s.lastShot;
          const dir = norm([ls.aimPoint[0] - ls.eye[0], ls.aimPoint[1] - ls.eye[1], ls.aimPoint[2] - ls.eye[2]]);
          worst = Math.max(worst, angle(dir, f.camera.forward));
          n++;
          last = s.shotsFired;
        }
        if (o.ads && iv.getState().weapon.ads >= 0.999) {
          const e = f.viewModel.adsEyeCamera;
          worstSight = Math.max(worstSight, Math.hypot(e[0], e[1]));
          worstBarrel = Math.max(worstBarrel, angle(f.viewModel.barrelCamera, [0, 0, -1]));
        }
      }
      teardown();
      return { n, worst, worstSight, worstBarrel, maxClimb };
    }
    const out = { hip: burst({}, 50), ads: burst({ ads: true }, 50), crouchAds: burst({ ads: true, crouch: true }, 50), pistolAds: burst({ slot: 1, ads: true }, 60) };
    selectWeapon(0);
    return out;
  })()`);
  console.log(`# aim consistency: ${JSON.stringify(r)}`);
  for (const [k, v] of Object.entries(r)) {
    assert.ok(v.n >= 5, `${k}: ${v.n} rounds`);
    assert.ok(v.worst < 0.01, `${k}: round ${v.worst} deg off the rendered crosshair`);
    assert.ok(v.maxClimb > 0.5, `${k}: the view climbs (${v.maxClimb} deg)`);
  }
  for (const k of ['ads', 'crouchAds', 'pistolAds']) {
    assert.ok(r[k].worstSight < 0.0005, `${k}: sight line off the camera axis by ${r[k].worstSight} m`);
    assert.ok(r[k].worstBarrel < 0.05, `${k}: sight / barrel tilted ${r[k].worstBarrel} deg in ADS`);
  }
});

test('10-round burst: same climb and recovery at 30, 60 and 144 FPS pacing (within 5 %)', async () => {
  const r = await g.page.evaluate(`(() => {${PAGE_HELPERS}
    const out = {};
    for (const fps of [30, 60, 144]) {
      setup({ seed: 777 });
      const p0 = iv.getWeaponFeel().camera.pitchDeg;
      const look0 = iv.getState().player.pitchDeg;
      const s0 = iv.getState().weapon.shotsFired;
      iv.mouseButton(0, true);
      let t = 0, peak = 0, released = null, simAt10 = null;
      const common = {};
      for (let i = 1; i <= fps * 2.5; i++) {
        iv.frames(1 / fps, 1, { render: true });
        t = i / fps;
        const f = iv.getWeaponFeel();
        const dp = f.camera.pitchDeg - p0;
        peak = Math.max(peak, dp);
        const k6 = Math.round(t * 6);
        if (Math.abs(t * 6 - k6) < 1e-9) common[k6] = dp;
        if (released === null && iv.getState().weapon.shotsFired - s0 >= 10) {
          iv.mouseButton(0, false);
          released = t;
          simAt10 = f.recoil.targetPitchDeg;
        }
      }
      out[fps] = { shots: iv.getState().weapon.shotsFired - s0, peak, simAt10, common, settled: iv.getWeaponFeel().camera.pitchDeg - p0, lookDrift: iv.getState().player.pitchDeg - look0 };
      teardown();
    }
    return out;
  })()`);
  console.log(`# burst 10 rounds: ${JSON.stringify(Object.fromEntries(Object.entries(r).map(([k, v]) => [k, { shots: v.shots, peak: +v.peak.toFixed(4), settled: +v.settled.toFixed(4), lookDrift: +v.lookDrift.toFixed(4) }])))}`);
  for (const fps of [30, 60, 144]) assert.equal(r[fps].shots, 10, `${fps} FPS shots`);
  assert.ok(r[60].peak > 3 && r[60].peak < 7, `climb ${r[60].peak} deg (visible, controllable)`);
  for (const fps of [30, 144]) {
    assert.ok(Math.abs(r[fps].peak - r[60].peak) / r[60].peak < 0.05, `${fps} FPS peak ${r[fps].peak} vs 60 FPS ${r[60].peak}`);
    assert.ok(Math.abs(r[fps].simAt10 - r[60].simAt10) < 1e-9 || Math.abs(r[fps].settled - r[60].settled) < 1e-6, 'same simulation');
    for (const k of Object.keys(r[60].common)) assert.ok(Math.abs(r[fps].common[k] - r[60].common[k]) < 1e-6, `${fps} FPS view at ${k / 6} s: ${r[fps].common[k]} vs ${r[60].common[k]}`);
  }
  // partial automatic recovery: most of the climb returns, the rest stays in the look (player pulls down)
  assert.ok(r[60].settled > 0 && r[60].settled < 0.35 * r[60].peak, `settled ${r[60].settled} of ${r[60].peak}`);
  assert.ok(Math.abs(r[60].lookDrift - r[60].settled) < 0.05, 'the remainder is in the look, not in a hidden offset');
});

test('muzzle flash lasts a fixed time (2 frames at 60 FPS, 1 at 30, 4-5 at 144); casings eject, land and disappear; pools capped', async () => {
  const r = await g.page.evaluate(`(() => {${PAGE_HELPERS}
    const flash = {};
    for (const fps of [30, 60, 144]) {
      setup({});
      const s0 = iv.getState().weapon.shotsFired;
      iv.mouseButton(0, true);
      let frames = 0;
      let released = false;
      for (let i = 0; i < fps / 2; i++) {
        iv.frames(1 / fps, 1, { render: true });
        if (!released && iv.getState().weapon.shotsFired > s0) {
          iv.mouseButton(0, false); // exactly one round
          released = true;
        }
        if (iv.getWeaponFeel().viewModel.flashIntensity > 0) frames++;
      }
      flash[fps] = { frames, shots: iv.getState().weapon.shotsFired - s0 };
    }
    setup({});
    const e0 = iv.getWeaponFeel().effects;
    iv.mouseButton(0, true);
    iv.frames(1 / 60, 1, { render: true });
    iv.mouseButton(0, false);
    const e1 = iv.getWeaponFeel().effects;
    iv.simulate(3);
    const e2 = iv.getWeaponFeel().effects;
    // 90 rounds of sustained fire: caps hold
    iv.mouseButton(0, true);
    let maxCas = 0, maxSmoke = 0;
    for (let i = 0; i < 90 * 5; i++) {
      iv.step(1);
      const e = iv.getWeaponFeel().effects;
      maxCas = Math.max(maxCas, e.casingsActive);
      maxSmoke = Math.max(maxSmoke, e.smokeActive);
    }
    iv.mouseButton(0, false);
    const e3 = iv.getWeaponFeel().effects;
    teardown();
    return { flash, spawned: e1.casingsSpawned - e0.casingsSpawned, smoke: e1.smokeSpawned - e0.smokeSpawned, landed: e2.casingsLanded - e0.casingsLanded, activeAfter: e2.casingsActive, maxCas, maxSmoke, caps: [e3.casingCap, e3.smokeCap], ejectFromSocket: iv.getWeaponFeel().viewModel.ejectFromSocket };
  })()`);
  console.log(`# flash / casings: ${JSON.stringify(r)}`);
  for (const fps of [30, 60, 144]) assert.equal(r.flash[fps].shots, 1, `${fps} FPS: one round`);
  assert.equal(r.flash[60].frames, 2);
  assert.equal(r.flash[30].frames, 1);
  assert.ok(r.flash[144].frames >= 4 && r.flash[144].frames <= 5, `144 FPS: ${r.flash[144].frames} frames`);
  assert.equal(r.spawned, 1, 'one casing per round');
  assert.equal(r.smoke, 1, 'one smoke puff per round');
  assert.equal(r.landed, 1, 'the casing landed');
  assert.equal(r.activeAfter, 0, 'and disappeared');
  assert.ok(r.maxCas <= r.caps[0] && r.maxSmoke <= r.caps[1], `caps ${JSON.stringify(r)}`);
  assert.equal(r.ejectFromSocket, true, 'IV-7 casings come from the GLB socket_eject');
});

test('screenshots mid-burst: the weapon visibly kicks (hip), ADS sight picture stays centred, pistol flips', async () => {
  const shoot = async (name, o, rounds, extraTicks) => {
    await g.page.evaluate(`(() => {${PAGE_HELPERS}
      const o = ${JSON.stringify(o)};
      setup(o);
      if (${rounds} > 0) {
        const s0 = iv.getState().weapon.shotsFired;
        let n = 0;
        while (iv.getState().weapon.shotsFired - s0 < ${rounds} && n++ < 400) {
          iv.mouseButton(0, o.slot === 1 ? n % 8 < 2 : true);
          iv.step(1);
        }
        iv.mouseButton(0, false);
        iv.step(${extraTicks});
      }
      iv.resetAccumulator();
      iv.frames(1 / 60, 1, { render: true });
      iv.setDrawEnabled(true);
      iv.renderNow();
    })()`);
    const { buf } = await screenshot(g.page, name);
    await g.page.evaluate(`(() => {${PAGE_HELPERS} iv.setDrawEnabled(false); teardown(); })()`);
    return decodePng(buf);
  };
  const rest = await shoot('feel_rest_hip.png', {}, 0, 0);
  const hip = await shoot('feel_hip_burst6.png', {}, 6, 2);
  const ads = await shoot('feel_ads_burst6.png', { ads: true }, 6, 2);
  const pistol = await shoot('feel_pistol_hip.png', { slot: 1 }, 1, 3);
  await g.page.evaluate(`(() => {${PAGE_HELPERS} selectWeapon(0); })()`);
  // fraction of changed pixels in the weapon area (lower right) between rest and mid-burst
  const changed = (a, b, x0, y0, x1, y1) => {
    let n = 0;
    let c = 0;
    for (let y = y0; y < y1; y++)
      for (let x = x0; x < x1; x++) {
        const i = (y * a.width + x) * a.channels;
        const d = Math.abs(a.data[i] - b.data[i]) + Math.abs(a.data[i + 1] - b.data[i + 1]) + Math.abs(a.data[i + 2] - b.data[i + 2]);
        if (d > 60) c++;
        n++;
      }
    return c / n;
  };
  const hipChange = changed(rest, hip, 520, 300, 940, 430);
  // ADS: the reticle dot is at the screen centre (bright pixel within 3 px of the centre)
  let bright = 0;
  for (let y = 267; y <= 273; y++)
    for (let x = 477; x <= 483; x++) {
      const i = (y * ads.width + x) * ads.channels;
      if (ads.data[i] + ads.data[i + 1] + ads.data[i + 2] > 600) bright++;
    }
  const pistolChange = changed(rest, pistol, 520, 300, 940, 540);
  console.log(`# screenshots: hip weapon-area change ${(hipChange * 100).toFixed(1)} %, ADS centre bright px ${bright}, pistol vs rifle ${(pistolChange * 100).toFixed(1)} %`);
  assert.ok(hipChange > 0.08, `the weapon must visibly move mid-burst (${hipChange})`);
  assert.ok(bright >= 1, 'ADS reticle dot stays at the screen centre mid-burst');
});
