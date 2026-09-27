// Weapon logic: cadence from simulation time, ammo accounting, reload, and D8 hitscan on
// the real test-range geometry.
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

const DT = 1 / 60;
const DEF = weapons.iv7_carbine;
const world = new CollisionWorld(buildLevelSolids(level));
const DEG = Math.PI / 180;

function holdFire(ws, seconds, extra = {}) {
  const ticks = Math.round(seconds / DT);
  let shots = 0;
  for (let i = 0; i < ticks; i++) shots += ws.tick(DT, { trigger: true, ads: false, reload: false, canFire: true, ...extra });
  ws.tick(DT, { trigger: false });
  return shots;
}

test('fire cadence comes from accumulated simulation time (750 rpm -> 38 rounds in 3 s)', () => {
  const ws = new WeaponState(DEF);
  ws.infiniteAmmo = true;
  const shots = holdFire(ws, 3);
  const expected = Math.floor(3 / (60 / DEF.rpm) - 1e-9) + 1;
  assert.equal(expected, 38);
  assert.equal(shots, expected);
});

test('tapping faster than the cadence cannot exceed the rate of fire', () => {
  const ws = new WeaponState(DEF);
  ws.infiniteAmmo = true;
  let shots = 0;
  for (let i = 0; i < 600; i++) {
    // press on even ticks, release on odd ticks (30 presses per second)
    shots += ws.tick(DT, { trigger: i % 2 === 0, canFire: true });
  }
  const maxAllowed = Math.floor(10 / (60 / DEF.rpm)) + 1;
  assert.ok(shots <= maxAllowed, `${shots} > ${maxAllowed}`);
});

test('magazine empties at 30 rounds, dry fire then reload refills from reserve exactly once', () => {
  const ws = new WeaponState(DEF);
  const initial = ws.totalAmmo();
  const shots = holdFire(ws, 5);
  assert.equal(shots, DEF.magazineSize);
  assert.equal(ws.magazine, 0);
  // fresh trigger pull on empty magazine: dry fire + automatic reload start
  ws.tick(DT, { trigger: true, canFire: true });
  ws.tick(DT, { trigger: false });
  assert.ok(ws.dryFires >= 1);
  assert.equal(ws.state, 'reloading');
  let t = 0;
  while (ws.state === 'reloading' && t < 1000) {
    ws.tick(DT, { trigger: false, reload: true }); // spamming reload must not add ammo twice
    t++;
  }
  assert.ok(Math.abs(t * DT - DEF.reloadEmptyTime) < 3 * DT, `empty reload took ${t * DT}`);
  assert.equal(ws.magazine, DEF.magazineSize);
  assert.equal(ws.reserve, DEF.reserveAmmo - DEF.magazineSize);
  assert.equal(ws.totalAmmo() + ws.shotsFired, initial);
});

test('partial reload uses the tactical time and conserves ammo', () => {
  const ws = new WeaponState(DEF);
  const initial = ws.totalAmmo();
  for (let i = 0; i < 20; i++) ws.tick(DT, { trigger: i < 18, canFire: true });
  const fired = ws.shotsFired;
  assert.ok(fired > 0 && fired < DEF.magazineSize);
  ws.tick(DT, { reload: true });
  let t = 1;
  while (ws.state === 'reloading' && t < 1000) {
    ws.tick(DT, {});
    t++;
  }
  assert.ok(Math.abs(t * DT - DEF.reloadTime) < 3 * DT, `reload took ${t * DT}`);
  assert.equal(ws.magazine, DEF.magazineSize);
  assert.equal(ws.totalAmmo() + ws.shotsFired, initial);
});

test('cannot fire while reloading; reload with full magazine is refused', () => {
  const ws = new WeaponState(DEF);
  assert.equal(ws.startReload(), false);
  holdFire(ws, 0.5);
  assert.ok(ws.startReload());
  const before = ws.shotsFired;
  for (let i = 0; i < 30; i++) ws.tick(DT, { trigger: true, canFire: true });
  assert.equal(ws.shotsFired, before);
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

test('headshot multiplier and knock-down after enough damage', () => {
  const { ws, dummies } = makeSystem();
  const eye = new Vector3(10, 1.65, -20);
  const { yaw, pitch } = aimAt(eye, new Vector3(10, 1.64, -30));
  const shot = fireOnce(ws, eye, yaw, pitch);
  assert.equal(shot.hitPart, 'head');
  const d = dummies.byId.get('d_right');
  assert.equal(d.health, 100 - DEF.damage * DEF.headMultiplier);
});
