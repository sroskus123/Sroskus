// View-model motion (recoil springs, sway) and static pose: frame-rate independence and
// consistency of the gameplay muzzle offsets with the drawn pose. Node only, no DOM.
import test from 'node:test';
import assert from 'node:assert/strict';
import { Vector3 } from 'three';
import weapons from '../../src/data/weapons.json' with { type: 'json' };
import { FixedStepLoop } from '../../src/engine/loop.js';
import { stepDampedSpring, ViewModelMotion, viewModelPointInCamera, VIEW_MODEL_MOTION_DEFAULTS } from '../../src/weapons/viewModelMotion.js';

const W = weapons.iv7_carbine;

function rk4(x, v, k, d, T, n = 20000) {
  const h = T / n;
  const f = (x1, v1) => [v1, -k * x1 - d * v1];
  for (let i = 0; i < n; i++) {
    const [a1, b1] = f(x, v);
    const [a2, b2] = f(x + (h / 2) * a1, v + (h / 2) * b1);
    const [a3, b3] = f(x + (h / 2) * a2, v + (h / 2) * b2);
    const [a4, b4] = f(x + h * a3, v + h * b3);
    x += (h / 6) * (a1 + 2 * a2 + 2 * a3 + a4);
    v += (h / 6) * (b1 + 2 * b2 + 2 * b3 + b4);
  }
  return [x, v];
}

test('exact damped spring step matches a fine RK4 integration (under-, critically, over-damped)', () => {
  for (const [k, d] of [
    [260, 22],
    [220, 20],
    [100, 20],
    [100, 40],
  ]) {
    for (const [x0, v0] of [
      [0, 0.9],
      [0.3, -1],
      [-0.2, 2],
    ]) {
      for (const T of [1 / 60, 0.1, 0.37]) {
        const e = stepDampedSpring(x0, v0, k, d, T);
        const r = rk4(x0, v0, k, d, T);
        assert.ok(Math.abs(e[0] - r[0]) < 1e-7 && Math.abs(e[1] - r[1]) < 1e-7, `k=${k} d=${d} x0=${x0} v0=${v0} T=${T}: ${e} vs ${r}`);
      }
    }
  }
});

/**
 * Drives ViewModelMotion exactly like the game: springs on the fixed tick of the real
 * FixedStepLoop (shots fired from the tick), kick interpolated and sway smoothed per frame.
 */
function simulate(fps, { seconds = 1, shotTicks = [3], lookRate = 0 } = {}) {
  const m = new ViewModelMotion();
  const shots = new Set(shotTicks);
  const frames = [];
  let lastYaw = 0;
  let yaw = 0;
  const loop = new FixedStepLoop({
    step: (dt, tick) => {
      if (shots.has(tick)) m.onShot();
      m.tick(dt);
    },
    render: (alpha, dt) => {
      yaw += lookRate * dt; // the mouse turns the view at a constant rate
      m.frame(dt, yaw - lastYaw, 0, 0);
      lastYaw = yaw;
      const k = m.kickAt(alpha);
      frames.push({ t: loop.simTime, alpha, ...k, swayX: m.swayX });
    },
  });
  const n = Math.round(seconds * fps);
  for (let i = 0; i < n; i++) loop.frame(1 / fps);
  return { m, frames, loop };
}

test('recoil kick stays bounded and FPS independent at 4-240 FPS (one shot)', () => {
  const peakKick = 0.0174;
  const peakRot = 0.0578;
  const runs = {};
  for (const fps of [4, 10, 15, 20, 30, 60, 144, 240]) {
    const r = simulate(fps);
    runs[fps] = r;
    for (const f of r.frames) {
      assert.ok(Number.isFinite(f.kick) && Number.isFinite(f.kickRot), `${fps} FPS: not finite`);
      assert.ok(Math.abs(f.kick) <= peakKick + 1e-4, `${fps} FPS: kick ${f.kick}`);
      assert.ok(Math.abs(f.kickRot) <= peakRot + 1e-4, `${fps} FPS: kickRot ${f.kickRot}`);
    }
    // after exactly 60 ticks the spring state is bit-identical whatever the frame pacing
    assert.equal(r.loop.ticks, 60, `${fps} FPS ticks`);
    assert.equal(r.m.kick, runs[4].m.kick, `${fps} FPS end state`);
    assert.equal(r.m.kickRot, runs[4].m.kickRot, `${fps} FPS end state`);
  }
  // frames that fall on the same simulated time show the same kick at every frame rate
  for (const t of [0.25, 0.5, 0.75]) {
    const ref = runs[4].frames.find((f) => Math.abs(f.t - t) < 1e-9);
    for (const fps of [20, 60, 144, 240]) {
      const f = runs[fps].frames.find((g) => Math.abs(g.t - t) < 1e-9);
      assert.ok(ref && f, `sample at ${t} s for ${fps} FPS`);
      assert.ok(Math.abs(f.kick - ref.kick) < 1e-12 && Math.abs(f.kickRot - ref.kickRot) < 1e-12, `${fps} FPS at ${t} s`);
    }
  }
  // the displayed peak is the same at 60 and 144 FPS (within sampling), and equals the tuned value
  const peak = (fps, key) => Math.max(...runs[fps].frames.map((f) => Math.abs(f[key])));
  for (const key of ['kick', 'kickRot']) {
    const p60 = peak(60, key);
    const p144 = peak(144, key);
    assert.ok(Math.abs(p60 - p144) / p144 < 0.05, `${key}: 60 FPS ${p60} vs 144 FPS ${p144}`);
  }
  assert.ok(Math.abs(peak(144, 'kick') - peakKick) / peakKick < 0.05, `peak kick ${peak(144, 'kick')}`);
  assert.ok(Math.abs(peak(144, 'kickRot') - peakRot) / peakRot < 0.05, `peak kickRot ${peak(144, 'kickRot')}`);
});

test('full-auto recoil (750 rpm) stays bounded at 4, 10 and 144 FPS', () => {
  const shotTicks = [];
  for (let i = 0; i < 13; i++) shotTicks.push(Math.round(i * 4.8));
  for (const fps of [4, 10, 144]) {
    const r = simulate(fps, { seconds: 1.5, shotTicks });
    const maxKick = Math.max(...r.frames.map((f) => Math.abs(f.kick)));
    const maxRot = Math.max(...r.frames.map((f) => Math.abs(f.kickRot)));
    assert.ok(maxKick < 0.05 && maxRot < 0.15, `${fps} FPS: kick ${maxKick} rot ${maxRot}`);
  }
});

test('sway depends on the look speed, not on the frame rate', () => {
  const vals = {};
  for (const fps of [30, 60, 144]) {
    const r = simulate(fps, { seconds: 0.5, shotTicks: [], lookRate: 2 }); // 2 rad/s to the left
    vals[fps] = r.m.swayX;
  }
  // 2 rad/s -> target -0.02 m; after 0.5 s of exponential approach at rate 10: -0.02 * (1 - e^-5)
  const expected = -2 * VIEW_MODEL_MOTION_DEFAULTS.swayPerRadPerSec * (1 - Math.exp(-VIEW_MODEL_MOTION_DEFAULTS.swayRate * 0.5));
  for (const fps of [30, 60, 144]) {
    assert.ok(Math.abs(vals[fps] - expected) < 1e-9, `${fps} FPS sway ${vals[fps]} expected ${expected}`);
  }
  // a redraw without time passing does not move the sway
  const m = new ViewModelMotion();
  m.frame(0, 0.1, 0.1, 1);
  assert.equal(m.swayX, 0);
  assert.equal(m.sprint, 0);
});

test('gameplay muzzle offsets equal the drawn static pose (hip cant included); ADS eye on the camera', () => {
  const vm = W.viewModel;
  const hip = viewModelPointInCamera(vm, vm.muzzleLocal, 0);
  const ads = viewModelPointInCamera(vm, vm.muzzleLocal, 1);
  const eye = viewModelPointInCamera(vm, vm.adsEyeLocal, 1);
  const dHip = hip.distanceTo(new Vector3().fromArray(W.muzzleOffsetHip));
  const dAds = ads.distanceTo(new Vector3().fromArray(W.muzzleOffsetAds));
  assert.ok(dHip < 5e-4, `hip muzzle ${hip.toArray()} vs data ${W.muzzleOffsetHip} (${dHip} m)`);
  assert.ok(dAds < 5e-4, `ADS muzzle ${ads.toArray()} vs data ${W.muzzleOffsetAds} (${dAds} m)`);
  assert.ok(eye.length() < 5e-4, `ADS eye ${eye.toArray()}`);
  // the hip cant is really part of the pose (guards against the old translation-only formula)
  const noCant = viewModelPointInCamera({ ...vm, hipRotation: [0, 0, 0] }, vm.muzzleLocal, 0);
  assert.ok(noCant.distanceTo(hip) > 0.01, 'hip rotation must move the muzzle');
});

test('gameplay muzzle follows the drawn view-model pose through the whole hip <-> ADS transition', async () => {
  const { WeaponSystem } = await import('../../src/weapons/weaponSystem.js');
  const { buildLevelSolids } = await import('../../src/level/levelGeometry.js');
  const { CollisionWorld } = await import('../../src/physics/collisionWorld.js');
  const { createRng } = await import('../../src/util/rng.js');
  const world = new CollisionWorld(buildLevelSolids({ solids: [{ type: 'box', id: 'g', min: [-5, -0.5, -5], max: [5, 0, 5] }] }));
  const ws = new WeaponSystem({ def: W, world, rng: createRng(1) });
  const vm = W.viewModel;
  // end poses are exactly the data offsets
  assert.deepEqual(ws.muzzleOffset(0).toArray(), W.muzzleOffsetHip);
  assert.deepEqual(ws.muzzleOffset(1).toArray(), W.muzzleOffsetAds);
  let worst = 0;
  let worstLinear = 0;
  for (let i = 0; i <= 40; i++) {
    const ads = i / 40;
    const drawn = viewModelPointInCamera(vm, vm.muzzleLocal, ads);
    worst = Math.max(worst, ws.muzzleOffset(ads).distanceTo(drawn));
    const linear = new Vector3().fromArray(W.muzzleOffsetHip).lerp(new Vector3().fromArray(W.muzzleOffsetAds), ads);
    worstLinear = Math.max(worstLinear, linear.distanceTo(drawn));
  }
  assert.ok(worst < 5e-4, `gameplay vs drawn muzzle during ADS transition: ${(worst * 1000).toFixed(3)} mm`);
  // guard: the drawn path really differs from a straight line (so this test can fail)
  assert.ok(worstLinear > 0.01, `linear blend deviates only ${worstLinear} m`);
  // and the world-space muzzle uses it (eye at origin, looking down -z, no recoil)
  const eye = new Vector3(0, 1.65, 0);
  const mw = ws.muzzleWorld(eye, 0, 0, 0.25, new Vector3());
  assert.ok(mw.clone().sub(eye).distanceTo(viewModelPointInCamera(vm, vm.muzzleLocal, 0.25)) < 5e-4);
});
