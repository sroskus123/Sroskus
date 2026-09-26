// Weapon feel (GUN-03): aim recoil per weapon and stance, first shot vs follow-ups, climb and recovery
// (also partial recovery into the look), frame-rate independence through the real FixedStepLoop, the
// crosshair never lying (every round goes where the rendered camera looked), muzzle flash timing,
// casings and the per-surface impact table. Node only, no DOM.
import test from 'node:test';
import assert from 'node:assert/strict';
import { Vector3 } from 'three';
import weapons from '../../src/data/weapons.json' with { type: 'json' };
import { FixedStepLoop } from '../../src/engine/loop.js';
import { EventBus } from '../../src/engine/events.js';
import { Recoil } from '../../src/weapons/recoil.js';
import { WeaponSystem, lookQuaternion } from '../../src/weapons/weaponSystem.js';
import { CasingPool, FlashTimer, MuzzleEffects, resolveFeel } from '../../src/weapons/muzzleEffects.js';
import { IMPACT_SURFACES, impactSurface } from '../../src/weapons/impactEffects.js';
import { buildLevelSolids } from '../../src/level/levelGeometry.js';
import { CollisionWorld } from '../../src/physics/collisionWorld.js';
import { createRng } from '../../src/util/rng.js';

const R = weapons.iv7_carbine;
const P = weapons.ivp9_pistol;
const DT = 1 / 60;
const RAD = 180 / Math.PI;
// 750 rpm cadence of the core: rounds at t = k * 0.08 s, fired on the first tick at or after that time
const SHOT_TICKS_750 = Array.from({ length: 60 }, (_, k) => Math.ceil((k * 0.08) / DT - 1e-9));

function fwd(yaw, pitch) {
  return new Vector3(0, 0, -1).applyQuaternion(lookQuaternion(yaw, pitch));
}

/** Angle between two directions in degrees (atan2 form: accurate for tiny angles, unlike acos). */
function angleDeg(a, b) {
  return Math.atan2(new Vector3().crossVectors(a, b).length(), a.dot(b)) * RAD;
}

test('recoil: stance multipliers (hip / ADS / crouch) scale the kick exactly as the data says', () => {
  for (const W of [R, P]) {
    const kickAt = (o) => {
      const r = new Recoil(W.recoil, createRng(5));
      r.kick(o);
      return r.lastKick;
    };
    const hip = kickAt({ ads: 0 });
    const ads = kickAt({ ads: 1 });
    const cr = kickAt({ ads: 0, crouch: true });
    const both = kickAt({ ads: 1, crouch: true });
    const half = kickAt({ ads: 0.5 });
    const s = W.recoil.stance;
    assert.ok(hip.pitchDeg > 0.5, `${W.id}: hip kick ${hip.pitchDeg} deg`);
    assert.ok(Math.abs(ads.pitchDeg / hip.pitchDeg - s.ads) < 1e-12, `${W.id} ADS`);
    assert.ok(Math.abs(cr.pitchDeg / hip.pitchDeg - s.crouch) < 1e-12, `${W.id} crouch`);
    assert.ok(Math.abs(both.pitchDeg / hip.pitchDeg - s.ads * s.crouch) < 1e-12, `${W.id} ADS + crouch`);
    assert.ok(Math.abs(half.pitchDeg / hip.pitchDeg - (1 + (s.ads - 1) * 0.5)) < 1e-12, `${W.id} ADS blend`);
    assert.ok(Math.abs(ads.yawDeg / hip.yawDeg - s.ads) < 1e-12, `${W.id} ADS yaw`);
    assert.ok(s.ads < 1 && s.crouch < 1, 'ADS and crouch steady the weapon');
  }
  // legacy call with a number (ADS amount) still works
  const r = new Recoil(R.recoil, createRng(5));
  r.kick(1);
  assert.ok(Math.abs(r.lastKick.stance - R.recoil.stance.ads) < 1e-12);
});

test('recoil: first shot is mostly vertical, follow-ups grow up to followUpMax, a pause starts a new string', () => {
  const cfg = { ...R.recoil, pitchJitter: 0 };
  const r = new Recoil(cfg, createRng(3));
  const pitches = [];
  let tick = 0;
  for (const st of SHOT_TICKS_750.slice(0, 10)) {
    while (tick < st) {
      r.snapshot();
      r.recover(DT);
      tick++;
    }
    r.snapshot();
    r.kick({ ads: 0 });
    r.recover(DT);
    tick++;
    pitches.push({ i: r.shotIndex, p: r.lastKick.pitchDeg });
  }
  pitches.forEach((s, i) => {
    assert.equal(s.i, i, 'shot index within the string');
    const mul = i === 0 ? cfg.firstShotPitch : Math.min(cfg.followUpMax, 1 + cfg.followUpGrowth * i);
    assert.ok(Math.abs(s.p - cfg.pitchDeg * mul) < 1e-12, `shot ${i}: ${s.p}`);
  });
  assert.ok(pitches[9].p > pitches[0].p, 'follow-ups kick harder than the first round');
  // pause longer than stringReset -> new string
  for (let t = 0; t < cfg.stringReset + 0.05; t += DT) r.recover(DT);
  r.kick({});
  assert.equal(r.shotIndex, 0);
  // first-shot horizontal kick limited to firstShotYaw x yawDeg, follow-ups use the full yawDeg
  let firstMax = 0;
  let followMax = 0;
  const rr = new Recoil(R.recoil, createRng(11));
  for (let n = 0; n < 400; n++) {
    rr.kick({});
    if (rr.shotIndex === 0) firstMax = Math.max(firstMax, Math.abs(rr.lastKick.yawDeg));
    else followMax = Math.max(followMax, Math.abs(rr.lastKick.yawDeg));
    const pause = n % 4 === 3 ? 0.4 : 0.08; // strings of 4
    for (let t = 0; t < pause - 1e-9; t += DT) rr.recover(DT);
  }
  assert.ok(firstMax <= R.recoil.yawDeg * R.recoil.firstShotYaw + 1e-12, `first-shot yaw ${firstMax}`);
  assert.ok(followMax > firstMax * 1.5, `follow-up yaw ${followMax} vs first ${firstMax}`);
});

test('recoil: the view kicks without a one-tick jump, then recovers fully when nobody takes the transfer (bots)', () => {
  const r = new Recoil({ ...R.recoil, pitchJitter: 0 }, createRng(1));
  r.snapshot();
  r.kick({});
  r.recover(DT);
  const target = R.recoil.pitchDeg;
  const first = r.pitch * RAD;
  assert.ok(first > 0.3 * target && first < 0.8 * target, `after the shot tick ${first} of ${target} deg (smooth rise, not a teleport)`);
  let peak = first;
  let peakTick = 1;
  const trace = [first];
  for (let i = 2; i <= 150; i++) {
    r.snapshot();
    r.recover(DT);
    trace.push(r.pitch * RAD);
    if (r.pitch * RAD > peak) {
      peak = r.pitch * RAD;
      peakTick = i;
    }
  }
  assert.ok(peak > 0.8 * target, `peak ${peak}`);
  assert.ok(peakTick <= 6, `peak within 0.1 s (tick ${peakTick})`);
  const at = (s) => trace[Math.round(s / DT) - 1];
  assert.ok(at(0.6) < 0.1 * peak, `recovered to ${at(0.6)} deg after 0.6 s`);
  assert.ok(at(2.5) < 1e-4, `fully recovered: ${at(2.5)}`);
  assert.equal(r.lookTransfer, false);
});

function burstThroughLoop(fps, { cfg = R.recoil, rounds = 10, seconds = 2.2, ads = 0, lookTransfer = false } = {}) {
  const r = new Recoil(cfg, createRng(42));
  let look = 0; // pitch of the look owner (player), radians
  if (lookTransfer) r.takeLookTransfer();
  const shots = new Set(SHOT_TICKS_750.slice(0, rounds));
  const frames = [];
  let climbAtLast = 0;
  let transferPerTick = [];
  const loop = new FixedStepLoop({
    step: (dt, tick) => {
      r.snapshot();
      if (shots.has(tick)) r.kick({ ads });
      r.recover(dt);
      if (tick === SHOT_TICKS_750[rounds - 1]) climbAtLast = r.pitch;
      if (lookTransfer) {
        const t = r.takeLookTransfer();
        look += t.pitch;
        transferPerTick.push(t.pitch);
      }
    },
    render: (alpha) => {
      const v = r.interpolated(alpha);
      frames.push({ t: loop.simTime, view: look + v.pitch, recoil: v.pitch });
    },
  });
  const n = Math.round(seconds * fps);
  for (let i = 0; i < n; i++) loop.frame(1 / fps);
  return { r, frames, loop, climbAtLast, look, transferPerTick };
}

test('recoil: a 10-round burst climbs visibly, recovers after release, and is identical at 30 / 60 / 144 FPS', () => {
  const runs = {};
  for (const fps of [30, 60, 144]) runs[fps] = burstThroughLoop(fps);
  const climb = runs[60].climbAtLast * RAD;
  assert.ok(climb > 3 && climb < 6.5, `hip climb after 10 rounds ${climb.toFixed(2)} deg (visible, controllable)`);
  // identical simulation
  assert.equal(runs[30].climbAtLast, runs[144].climbAtLast);
  assert.equal(runs[30].r.pitch, runs[144].r.pitch);
  // rendered peak within 5 % at every frame rate
  const peak = (fps) => Math.max(...runs[fps].frames.map((f) => f.view));
  for (const fps of [30, 144]) assert.ok(Math.abs(peak(fps) - peak(60)) / peak(60) < 0.05, `${fps} FPS peak ${peak(fps)} vs 60 FPS ${peak(60)}`);
  // frames on the same simulated time show the same view
  for (const t of [1 / 6, 0.5, 2 / 3, 1.0, 1.5]) {
    const vals = [30, 60, 144].map((fps) => runs[fps].frames.find((f) => Math.abs(f.t - t) < 1e-9));
    assert.ok(vals.every(Boolean), `sample at ${t}`);
    for (const v of vals) assert.ok(Math.abs(v.view - vals[0].view) < 1e-12, `view at ${t} s differs`);
  }
  // recovery: back within 10 % of the climb 0.6 s after the last round, fully after 2 s (no transfer)
  const tLast = (SHOT_TICKS_750[9] + 1) * DT;
  const after = (s) => runs[60].frames.find((f) => f.t >= tLast + s - 1e-9).view * RAD;
  assert.ok(after(0.6) < 0.1 * climb, `0.6 s after release ${after(0.6)} deg`);
  assert.ok(Math.abs(runs[60].r.pitch) * RAD < 0.01, 'fully recovered');
  // ADS climbs less by the stance factor
  const adsRun = burstThroughLoop(60, { ads: 1 });
  assert.ok(Math.abs(adsRun.climbAtLast / runs[60].climbAtLast - R.recoil.stance.ads) < 0.02, 'ADS climb scaled');
  // sustained fire (60 rounds, no magazine limit here) never exceeds the cap
  const long = burstThroughLoop(60, { rounds: 60, seconds: 5 });
  assert.ok(Math.max(...long.frames.map((f) => f.recoil)) <= (R.recoil.maxPitchDeg * Math.PI) / 180 + 1e-12);
});

test('recoil: partial automatic recovery leaves (1 - recoverFraction) of the climb in the look without any visible jump', () => {
  for (const fps of [30, 60, 144]) {
    const run = burstThroughLoop(fps, { lookTransfer: true, seconds: 3 });
    const climb = run.climbAtLast;
    // settled: recoil offset gone, the rest is in the look
    assert.ok(Math.abs(run.r.pitch) < 1e-5, `offset ${run.r.pitch}`);
    const share = run.look / climb;
    const f = R.recoil.recoverFraction;
    assert.ok(share > (1 - f) * 0.8 && share < (1 - f) * 1.3, `${fps} FPS: ${(share * 100).toFixed(1)} % of the climb stays in the look`);
    // the rendered view (look + interpolated offset) never jumps: frame-to-frame change stays small
    let maxStep = 0;
    for (let i = 1; i < run.frames.length; i++) maxStep = Math.max(maxStep, Math.abs(run.frames[i].view - run.frames[i - 1].view));
    const perShot = (R.recoil.pitchDeg * R.recoil.followUpMax * (1 + R.recoil.pitchJitter)) / RAD;
    assert.ok(maxStep < perShot * (60 / fps) * 0.8 + 1e-9, `${fps} FPS: largest frame step ${maxStep * RAD} deg`);
  }
  // exact continuity at every tick boundary: the view drawn at alpha = 0 of tick N equals the view drawn at
  // alpha = 1 of tick N - 1, although the look jumps by the transferred amount at that boundary
  {
    const r = new Recoil(R.recoil, createRng(42));
    r.takeLookTransfer();
    let look = 0;
    let prevEnd = null;
    let transferred = 0;
    const shots = new Set(SHOT_TICKS_750.slice(0, 10));
    for (let tick = 0; tick < 200; tick++) {
      r.snapshot();
      if (shots.has(tick)) r.kick({});
      r.recover(DT);
      const t = r.takeLookTransfer();
      look += t.pitch;
      transferred += Math.abs(t.pitch);
      const start = look + r.interpolated(0).pitch;
      if (prevEnd !== null) assert.ok(Math.abs(start - prevEnd) < 1e-12, `tick ${tick}: view jumps by ${(start - prevEnd) * RAD} deg`);
      prevEnd = look + r.interpolated(1).pitch;
    }
    assert.ok(transferred > 0.001, 'something was transferred');
  }
  // the same view as without transfer until the string ends (transfer only in the post-string return)
  const a = burstThroughLoop(60, { lookTransfer: true });
  const b = burstThroughLoop(60, { lookTransfer: false });
  const tLast = (SHOT_TICKS_750[9] + 1) * DT;
  for (let i = 0; i < a.frames.length && a.frames[i].t <= tLast; i++) assert.ok(Math.abs(a.frames[i].view - b.frames[i].view) < 1e-12);
});

function rangeWorld() {
  return new CollisionWorld(
    buildLevelSolids({
      solids: [
        { type: 'box', id: 'ground', min: [-50, -0.5, -80], max: [50, 0, 20] },
        { type: 'box', id: 'wall', min: [-50, 0, -60.5], max: [50, 30, -60] },
      ],
    }),
  );
}

test('WeaponSystem (GUN-03): every round goes exactly where the rendered camera looked, hip / ADS, standing / crouched', () => {
  for (const W of [R, P]) {
    for (const stance of [{ ads: false, crouch: false }, { ads: true, crouch: false }, { ads: false, crouch: true }]) {
      const events = new EventBus();
      const owner = { id: 'p', team: 0, controller: { crouched: stance.crouch } };
      const ws = new WeaponSystem({ def: W, world: rangeWorld(), rng: createRng(9), events, owner });
      ws.state.infiniteAmmo = true;
      const eye = new Vector3(0, 1.65, 0);
      const yaw = 0.1;
      const pitch = 0.02;
      let camPrev = fwd(yaw, pitch); // camera the renderer shows at alpha = 1 after the previous tick (no recoil yet)
      const fired = [];
      let checked = 0;
      events.on('weapon:fired', (p) => fired.push(p));
      for (let tick = 0; tick < 180; tick++) {
        const before = fired.length;
        const trigger = W.id === 'ivp9_pistol' ? tick % 10 < 2 : true; // pistol: taps
        ws.tick(DT, { trigger, ads: stance.ads, reload: false, sprinting: false }, eye, yaw, pitch);
        for (let k = before; k < fired.length; k++) {
          const p = fired[k];
          assert.ok(camPrev, 'camera known');
          const ang = angleDeg(p.dir, camPrev);
          assert.ok(ang < 1e-6, `${W.id} ${JSON.stringify(stance)} shot ${k}: ${ang} deg off the rendered camera`);
          // the recorded aim point lies on that ray from the eye
          const toAim = new Vector3().fromArray(p.shot.aimPoint).sub(eye).normalize();
          assert.ok(angleDeg(toAim, camPrev) < 1e-4, 'aim point on the camera ray');
          assert.equal(p.crouch, stance.crouch);
          checked++;
        }
        const rec = ws.recoil.interpolated(1);
        camPrev = fwd(yaw + rec.yaw, pitch + rec.pitch);
      }
      assert.ok(checked >= 10, `${W.id}: ${checked} rounds checked`);
      if (stance.crouch) assert.ok(Math.abs(ws.recoil.lastKick.stance - W.recoil.stance.crouch) < 1e-12, 'crouch stance used for the kick');
      if (stance.ads) assert.ok(ws.recoil.lastKick.stance < 1, 'ADS stance used for the kick');
    }
  }
});

test('muzzle flash: fixed simulated lifetime, 2 frames at 60 FPS, 4-5 at 144, 1 at 30; drawn at least once at 10-20 FPS', () => {
  const dur = R.feel.muzzle.flash.duration;
  const res = {};
  for (const fps of [10, 20, 30, 60, 144]) {
    const f = new FlashTimer(dur);
    let visible = 0;
    let lastAge = 0;
    const loop = new FixedStepLoop({
      step: (dt, tick) => {
        if (tick === 3) f.trigger();
        f.tick(dt);
      },
      render: (alpha) => {
        const age = f.renderAge(alpha, DT);
        if (f.sample(alpha, DT) > 0) {
          visible++;
          lastAge = age;
        }
      },
    });
    for (let i = 0; i < fps; i++) loop.frame(1 / fps);
    res[fps] = { visible, lastAge };
  }
  assert.equal(res[60].visible, 2, JSON.stringify(res));
  assert.ok(res[144].visible >= 4 && res[144].visible <= 5, JSON.stringify(res));
  for (const fps of [10, 20, 30]) assert.equal(res[fps].visible, 1, `${fps} FPS: ${JSON.stringify(res)}`);
  // at 30 / 60 / 144 FPS the flash ends at the same simulated age (within one frame)
  for (const fps of [60, 144]) assert.ok(res[fps].lastAge < dur + 1e-9, `${fps} FPS last visible age ${res[fps].lastAge}`);
  // 750 rpm at 10 FPS: every rendered frame whose interval contained a round shows the flash
  const f = new FlashTimer(dur);
  const shots = new Set(SHOT_TICKS_750.slice(0, 20));
  let shotSinceFrame = false;
  let missed = 0;
  const loop = new FixedStepLoop({
    step: (dt, tick) => {
      if (shots.has(tick)) {
        f.trigger();
        shotSinceFrame = true;
      }
      f.tick(dt);
    },
    render: (alpha) => {
      const I = f.sample(alpha, DT);
      if (shotSinceFrame && !(I > 0)) missed++;
      shotSinceFrame = false;
    },
  });
  for (let i = 0; i < 20; i++) loop.frame(1 / 10);
  assert.equal(missed, 0);
});

function floorRaycast(y0 = 0) {
  return (o, d, far) => {
    if (d.y >= 0) return null;
    const t = (o.y - y0) / -d.y;
    if (t < 0 || t > far) return null;
    return { point: new Vector3(o.x + d.x * t, y0, o.z + d.z * t), normal: new Vector3(0, 1, 0), mat: 'floor' };
  };
}

test('casings: plausible arc to the side, land once, lie still, then disappear; capped pool recycles; no tunnelling', () => {
  const def = resolveFeel(R.feel).casing;
  const pool = new CasingPool(40);
  const landed = [];
  const c = pool.spawn(new Vector3(0, 1.5, 0), new Vector3(def.velocity[2], def.velocity[1], -def.velocity[0]), new Vector3(0, 0, -1), new Vector3(0, 25, 0), def);
  let minY = Infinity;
  let restAt = null;
  let goneAt = null;
  let maxY = 0;
  for (let i = 0; i < 360; i++) {
    pool.step(DT, floorRaycast(), (cc, hit) => landed.push({ t: i * DT, hit }));
    if (c.active) {
      minY = Math.min(minY, c.p.y);
      maxY = Math.max(maxY, c.p.y);
      assert.ok([c.p.x, c.p.y, c.p.z, c.q.x, c.q.w].every(Number.isFinite));
    }
    if (restAt === null && c.resting) restAt = i * DT;
    if (goneAt === null && !c.active) goneAt = i * DT;
  }
  assert.equal(landed.length, 1, 'one landing event');
  assert.ok(landed[0].t > 0.3 && landed[0].t < 1.0, `lands after ${landed[0].t} s`);
  assert.ok(maxY > 1.5, 'rises first (upward ejection)');
  assert.ok(minY >= def.radius * 0.99, `never below the floor: ${minY}`);
  assert.ok(restAt !== null && restAt < 2.5, `rests at ${restAt}`);
  assert.ok(goneAt !== null && goneAt - restAt <= def.restTime + def.fadeTime + 2 * DT, `disappears ${goneAt - restAt} s after resting`);
  // lateral throw 0.8 .. 3 m
  assert.ok(pool.items[0].p.x > 0.8 && pool.items[0].p.x < 3, `throw ${pool.items[0].p.x}`);
  // fast casing straight down does not tunnel through the floor
  const fast = pool.spawn(new Vector3(5, 0.3, 0), new Vector3(0, -40, 0), new Vector3(1, 0, 0), new Vector3(), def);
  for (let i = 0; i < 30; i++) {
    pool.step(DT, floorRaycast());
    if (fast.active) assert.ok(fast.p.y >= 0, `tunnelled to ${fast.p.y}`);
  }
  // cap
  const p2 = new CasingPool(40);
  for (let i = 0; i < 100; i++) p2.spawn(new Vector3(0, 1, 0), new Vector3(1, 1, 0), new Vector3(1, 0, 0), new Vector3(), def);
  assert.equal(p2.activeCount(), 40);
  assert.equal(p2.recycled, 60);
});

test('MuzzleEffects (no DOM): smoke puffs fade out, casings land with a callback, counts are reported', () => {
  const landed = [];
  const fx = new MuzzleEffects(null, { raycast: floorRaycast(), onCasingLanded: (e) => landed.push(e), maxCasings: 8, maxSmoke: 6 });
  const f = resolveFeel(R.feel);
  for (let i = 0; i < 3; i++) {
    fx.puff(new Vector3(0, 1.5, -0.8), new Vector3(0, 0, -1), f.smoke);
    fx.ejectCasing(new Vector3(0.1, 1.45, -0.3), new Vector3(2.8, 1.2, -0.4), new Vector3(0, 0, -1), f.casing, { weaponId: R.id, shooterId: 'p' });
  }
  assert.equal(fx.getState().smokeActive, 3);
  assert.ok(fx.smoke[0].material.opacity >= 0 && fx.smoke[0].material.opacity <= f.smoke.opacity);
  for (let i = 0; i < 60 * 3; i++) fx.tick(DT);
  const s = fx.getState();
  assert.equal(s.smokeActive, 0);
  assert.equal(landed.length, 3);
  assert.equal(landed[0].weaponId, R.id);
  assert.equal(s.casingsActive, 0, 'casings disappear after landing');
  // many shots: never more than the caps
  for (let i = 0; i < 50; i++) {
    fx.puff(new Vector3(), new Vector3(0, 0, -1), f.smoke);
    fx.ejectCasing(new Vector3(0, 1, 0), new Vector3(1, 1, 0), new Vector3(1, 0, 0), f.casing);
  }
  assert.ok(fx.getState().casingsActive <= 8 && fx.getState().smokeActive <= 6);
});

test('impacts: surfaces from level materials; sparks only on metal (a couple on concrete), no decal on bodies', () => {
  assert.equal(impactSurface({ kind: 'world', mat: 'wall' }), 'plaster');
  assert.equal(impactSurface({ kind: 'world', mat: 'block' }), 'concrete');
  assert.equal(impactSurface({ kind: 'world', mat: 'hazard' }), 'metal');
  assert.equal(impactSurface({ kind: 'world', mat: 'unknown_mat' }), 'concrete');
  assert.equal(impactSurface({ kind: 'world', mat: 'wood' }), 'wood');
  assert.equal(impactSurface({ kind: 'combatant', mat: 'flesh' }), 'flesh');
  assert.equal(impactSurface({ kind: 'dummy' }), 'target');
  for (const [name, s] of Object.entries(IMPACT_SURFACES)) {
    assert.ok(s.sparks <= 8, `${name}: ${s.sparks} sparks`);
    assert.ok(s.dust.opacity <= 0.6 && s.dust.life <= 1, `${name}: subtle dust`);
    if (['plaster', 'wood', 'dirt', 'flesh'].includes(name)) assert.equal(s.sparks, 0, `${name} does not spark`);
  }
  assert.ok(IMPACT_SURFACES.metal.sparks > IMPACT_SURFACES.concrete.sparks);
  assert.equal(IMPACT_SURFACES.flesh.decal, 0);
});

test('weapons.json feel data: ADS never rotates the view model, casings eject to the right, flash is short, AI keys kept', () => {
  for (const W of [R, P]) {
    const a = W.feel.viewModel.stance.ads;
    assert.equal(a.pitch, 0, `${W.id}: ADS pitch must be 0 (sight must show the aim)`);
    assert.equal(a.yaw, 0);
    assert.equal(a.rise, 0);
    assert.ok(W.feel.casing.velocity[2] > 0, 'ejects to the right');
    const d = W.feel.muzzle.flash.duration;
    assert.ok(d >= 1 / 60 && d <= 0.05, `flash ${d} s`);
    assert.ok(W.recoil.pitchDeg > 0 && W.recoil.maxPitchDeg > W.recoil.pitchDeg, 'AI reads recoil.pitchDeg');
    assert.ok(W.recoil.recoverFraction > 0.5 && W.recoil.recoverFraction <= 1);
  }
  // rifle vs pistol: the pistol kicks harder per round, the rifle climbs with sustained fire
  assert.ok(P.recoil.pitchDeg > R.recoil.pitchDeg);
});
