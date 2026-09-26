// Weapon logic: the engine weapon (WeaponHandle / WeaponSystem) runs the AUTHORITATIVE core weapon
// state (src/core/weapon.js, rules from Shared/config/rules.json): cadence from accumulated integer
// microseconds, magazine + separate chamber + reserve, reload commits; plus D8 hitscan on the real
// test-range geometry.
import test from 'node:test';
import assert from 'node:assert/strict';
import { Vector3 } from 'three';
import level from '../../src/data/test_range.json' with { type: 'json' };
import weapons from '../../src/data/weapons.json' with { type: 'json' };
import movement from '../../src/data/movement.json' with { type: 'json' };
import { buildLevelSolids } from '../../src/level/levelGeometry.js';
import { CollisionWorld } from '../../src/physics/collisionWorld.js';
import { WeaponState } from '../../src/weapons/weaponState.js';
import { WeaponSystem } from '../../src/weapons/weaponSystem.js';
import { TargetDummies } from '../../src/game/targetDummies.js';
import { createRng } from '../../src/util/rng.js';
import { baseRulesCompiled } from '../../src/game/gameRules.js';
import { weaponInvariantViolations } from '../../src/core/weapon.js';

const DT = 1 / 60;
const DEF = weapons.iv7_carbine;
const RULES = baseRulesCompiled();
const RDEF = RULES.weapons[DEF.rulesId];
const world = new CollisionWorld(buildLevelSolids(level));
const DEG = Math.PI / 180;

const newHandle = () => new WeaponState({ def: DEF, rulesDef: RDEF });
const tick = (ws, inp = {}) => {
  if (inp.reload) ws.reload();
  const n = ws.tick(DT, { trigger: false, ads: false, ...inp });
  const v = weaponInvariantViolations(ws.core.snapshot(), RDEF);
  assert.deepEqual(v, [], `ammo invariant: ${v.join('; ')}`);
  return n;
};

function holdFire(ws, seconds, extra = {}) {
  const ticks = Math.round(seconds / DT);
  let shots = 0;
  for (let i = 0; i < ticks; i++) shots += tick(ws, { trigger: true, ...extra });
  tick(ws, { trigger: false });
  return shots;
}

test('the engine weapon state is the core state machine (rules.json: rifle 30+1, pistol 15+1)', () => {
  const ws = newHandle();
  assert.equal(ws.core.constructor.name, 'WeaponState');
  assert.equal(ws.magazine, 30);
  assert.equal(ws.chamber, 1);
  assert.equal(ws.reserve, RDEF.startReserve);
  const p = new WeaponState({ def: weapons.ivp9_pistol, rulesDef: RULES.weapons.pistol_p9 });
  assert.equal(p.magazine, 15);
  assert.equal(p.chamber, 1);
  assert.equal(p.core.fireMode, 'semi');
});

test('fire cadence comes from accumulated simulation time (750 rpm -> 38 rounds in 3 s)', () => {
  const ws = newHandle();
  ws.infiniteAmmo = true;
  const shots = holdFire(ws, 3);
  const expected = Math.floor(3 / (60 / 750) - 1e-9) + 1;
  assert.equal(expected, 38);
  assert.equal(shots, expected);
  assert.equal(ws.shotsFired, expected);
});

test('tapping faster than the cadence cannot exceed the rate of fire', () => {
  const ws = newHandle();
  ws.infiniteAmmo = true;
  let shots = 0;
  for (let i = 0; i < 600; i++) {
    // press on even ticks, release on odd ticks (30 presses per second)
    shots += ws.tick(DT, { trigger: i % 2 === 0 });
  }
  const maxAllowed = Math.floor(10 / (60 / 750)) + 1;
  assert.ok(shots <= maxAllowed, `${shots} > ${maxAllowed}`);
  assert.ok(shots > 100, `taps fire at all (${shots})`);
});

test('held fire empties magazine + chamber (31 rounds), the bolt locks, dry fire; an empty reload chambers at bolt release exactly once', () => {
  const ws = newHandle();
  const initial = ws.totalAmmo();
  const shots = holdFire(ws, 5);
  assert.equal(shots, RDEF.magazineCapacity + 1);
  assert.equal(ws.magazine, 0);
  assert.equal(ws.chamber, 0);
  // fresh trigger pull on an empty weapon: dry fire, ammo unchanged
  tick(ws, { trigger: true });
  tick(ws, { trigger: false });
  assert.ok(ws.dryFires >= 1);
  assert.equal(ws.reload(), 'started_empty');
  let t = 0;
  while (ws.state === 'reloading' && t < 1000) {
    tick(ws, { reload: true }); // spamming reload must not add ammo twice
    t++;
  }
  assert.ok(Math.abs(t * DT - RDEF.empty.durationUs / 1e6) < 2 * DT, `empty reload took ${t * DT}`);
  // new magazine (30 from the reserve), then the bolt release moves one round into the chamber: 29 + 1
  assert.equal(ws.magazine, RDEF.magazineCapacity - 1);
  assert.equal(ws.chamber, 1);
  assert.equal(ws.reserve, RDEF.startReserve - RDEF.magazineCapacity);
  assert.equal(ws.totalAmmo() + ws.shotsFired, initial);
});

test('partial reload uses the tactical time, keeps the chambered round and conserves ammo', () => {
  const ws = newHandle();
  const initial = ws.totalAmmo();
  for (let i = 0; i < 20; i++) tick(ws, { trigger: i < 18 });
  const fired = ws.shotsFired;
  assert.ok(fired > 0 && fired < RDEF.magazineCapacity);
  assert.equal(ws.reload(), 'started_tactical');
  let t = 0;
  while (ws.state === 'reloading' && t < 1000) {
    tick(ws, {});
    t++;
  }
  assert.ok(Math.abs(t * DT - RDEF.tactical.durationUs / 1e6) < 2 * DT, `reload took ${t * DT}`);
  assert.equal(ws.magazine, RDEF.magazineCapacity);
  assert.equal(ws.chamber, 1);
  assert.equal(ws.totalAmmo() + ws.shotsFired, initial);
});

test('cannot fire while reloading; reload with a full magazine and chamber is refused', () => {
  const ws = newHandle();
  assert.equal(ws.reload(), 'rejected_full');
  holdFire(ws, 0.5);
  assert.equal(ws.reload(), 'started_tactical');
  const before = ws.shotsFired;
  for (let i = 0; i < 30; i++) tick(ws, { trigger: true });
  assert.equal(ws.shotsFired, before);
});

test('reload progress for the HUD comes from the core action time', () => {
  const ws = newHandle();
  holdFire(ws, 0.3);
  ws.reload();
  const half = Math.round(RDEF.tactical.durationUs / 1e6 / 2 / DT);
  for (let i = 0; i < half; i++) tick(ws, {});
  assert.ok(Math.abs(ws.reloadProgress - 0.5) < 0.02, `progress ${ws.reloadProgress}`);
});

function makeSystem() {
  const dummies = new TargetDummies(level.dummies);
  const ws = new WeaponSystem({ def: DEF, world, dummies, rng: createRng(7) });
  return { ws, dummies };
}

function eyeAt(marker, crouched = false) {
  const p = marker.pos;
  return new Vector3(p[0], p[1] + (crouched ? movement.capsule.crouchEyeHeight : movement.capsule.standEyeHeight), p[2]);
}

function aimAt(eye, target) {
  const d = target.clone().sub(eye);
  const yaw = Math.atan2(-d.x, -d.z);
  const pitch = Math.atan2(d.y, Math.hypot(d.x, d.z));
  return { yaw, pitch };
}

function fireOnce(ws, eye, yaw, pitch) {
  // let cadence and recoil settle so every call is an independent first shot
  for (let i = 0; i < 60; i++) ws.tick(DT, { trigger: false }, eye, yaw, pitch);
  const before = ws.state.shotsFired;
  ws.tick(DT, { trigger: true, canFire: true }, eye, yaw, pitch);
  ws.tick(DT, { trigger: false }, eye, yaw, pitch);
  assert.equal(ws.state.shotsFired, before + 1, 'exactly one round fired');
  return ws.lastShot;
}

test('clear line of fire hits the dummy torso', () => {
  const { ws, dummies } = makeSystem();
  const eye = new Vector3(0, 1.65, -12);
  const target = new Vector3(-5, 1.2, -30);
  const { yaw, pitch } = aimAt(eye, target);
  const shot = fireOnce(ws, eye, yaw, pitch);
  assert.equal(shot.cameraTarget, 'dummy:d_left');
  assert.equal(shot.hitTarget, 'dummy:d_left');
  assert.equal(shot.blocked, false);
  assert.equal(dummies.byId.get('d_left').hits, 1);
});

test('D8: camera sees the dummy past the corner edge, but the blocked muzzle hits the wall', () => {
  const { ws, dummies } = makeSystem();
  const m = level.markers.corner_peek;
  const eye = eyeAt(m);
  const target = new Vector3(m.pos[0], 1.2, -30);
  const { yaw, pitch } = aimAt(eye, target);
  const shot = fireOnce(ws, eye, yaw, pitch);
  assert.equal(shot.cameraTarget, `dummy:${m.targetId}`, 'camera ray must see the dummy');
  assert.equal(shot.hitTarget, `world:${m.wallId}`, `shot must hit the wall, got ${shot.hitTarget}`);
  assert.equal(shot.blocked, true);
  assert.equal(dummies.byId.get(m.targetId).hits, 0);
});

test('D8: crouched behind 1.0 m cover the camera sees over it, the muzzle hits the cover', () => {
  const { ws, dummies } = makeSystem();
  const m = level.markers.cover_peek;
  const eye = eyeAt(m, true);
  const target = new Vector3(0, 1.3, -30);
  const { yaw, pitch } = aimAt(eye, target);
  const shot = fireOnce(ws, eye, yaw, pitch);
  assert.equal(shot.cameraTarget, `dummy:${m.targetId}`);
  assert.ok(shot.hitTarget && shot.hitTarget.startsWith(`world:${m.wallId}`), `got ${shot.hitTarget}`);
  assert.equal(dummies.byId.get(m.targetId).hits, 0);
  // standing at the same place the muzzle clears the cover and the dummy is hit
  const eyeStand = eyeAt(m, false);
  const a2 = aimAt(eyeStand, target);
  const shot2 = fireOnce(ws, eyeStand, a2.yaw, a2.pitch);
  assert.equal(shot2.hitTarget, `dummy:${m.targetId}`);
});

test('shooting through the window opening hits the dummy behind it', () => {
  const { ws } = makeSystem();
  const m = level.markers.window_view;
  const eye = eyeAt(m);
  const { yaw, pitch } = aimAt(eye, new Vector3(-10, 1.25, -30));
  const shot = fireOnce(ws, eye, yaw, pitch);
  assert.equal(shot.hitTarget, 'dummy:d_window');
});

test('headshot multiplier on a dummy (rules damage x head multiplier)', () => {
  const { ws, dummies } = makeSystem();
  const eye = new Vector3(10, 1.65, -20);
  const { yaw, pitch } = aimAt(eye, new Vector3(10, 1.64, -30));
  const shot = fireOnce(ws, eye, yaw, pitch);
  assert.equal(shot.hitPart, 'head');
  const d = dummies.byId.get('d_right');
  assert.equal(RDEF.damage, 34);
  assert.equal(d.health, 100 - RDEF.damage * 2.0);
});

test('dummy hit wobble runs on simulation time: frozen while paused, continuous between ticks, same at any frame rate', async () => {
  const { DummyView } = await import('../../src/game/dummyView.js');
  const { FixedStepLoop } = await import('../../src/engine/loop.js');
  const run = (fps, pauseAfterTicks) => {
    const dummies = new TargetDummies(level.dummies);
    const view = new DummyView(dummies);
    const d = dummies.dummies[0];
    let paused = false;
    let ticks = 0;
    let pausedSteps = 0;
    const loop = new FixedStepLoop({
      step: (dt) => {
        if (paused) {
          view.hold();
          pausedSteps++;
          return;
        }
        if (ticks === 3) dummies.applyHit({ dummyId: d.id, part: 'torso', multiplier: 1 }, 10);
        dummies.tick(dt);
        view.tick(dt);
        ticks++;
        if (ticks === pauseAfterTicks) paused = true;
      },
      render: (alpha) => view.update(alpha),
    });
    const samples = [];
    for (let i = 0; i < Math.round(fps * 0.5); i++) {
      loop.frame(1 / fps);
      samples.push({ ticks, pausedSteps, rot: view.items[0].pivot.rotation.x });
    }
    return samples;
  };
  // paused 3 ticks after the hit (knock 0.35 decays at 3/s): from the first paused tick on,
  // the pose stays exactly still however many frames are drawn
  const p = run(144, 6);
  const frozen = p.filter((s) => s.pausedSteps > 0).map((s) => s.rot);
  assert.ok(frozen.length > 20, `frames while paused: ${frozen.length}`);
  assert.ok(Math.abs(frozen[0]) > 0.01, 'dummy is knocked back when paused');
  for (const r of frozen) assert.equal(r, frozen[0], 'dummy moved while the simulation was paused');
  // not paused: the drawn pose changes between ticks (interpolated, no 60 Hz steps) ...
  const a = run(144, Infinity);
  let sameAsPrev = 0;
  for (let i = 1; i < a.length; i++) if (a[i].ticks >= 4 && a[i].ticks <= 9 && a[i].rot === a[i - 1].rot) sameAsPrev++;
  assert.equal(sameAsPrev, 0, 'frames without pose change while the wobble is active');
  // ... and at tick boundaries the pose is the same at 30 and 144 FPS
  const b = run(30, Infinity);
  const at = (arr, k) => arr.find((s) => s.ticks === k);
  const c = run(60, Infinity);
  for (const k of [4, 6, 8, 16]) assert.ok(Math.abs(at(b, k).rot - at(c, k).rot) < 1e-9, `tick ${k}: ${at(b, k).rot} vs ${at(c, k).rot}`);
});
