// First-person camera feel (src/player/cameraEffects.js): head bob synced to the controller's real foot
// contacts, stair step impulse, landing dip scaled by fall speed, strafe roll, traversal arc and weapon
// lowering, the camera motion setting (0 = all off) and tick interpolation. Visual only: the simulation
// eye used for hitscan never moves.
import test from 'node:test';
import assert from 'node:assert/strict';
import { Quaternion, Vector3 } from 'three';
import level from '../../src/data/test_range.json' with { type: 'json' };
import movement from '../../src/data/movement.json' with { type: 'json' };
import bindings from '../../src/data/input_bindings.json' with { type: 'json' };
import { buildLevelSolids } from '../../src/level/levelGeometry.js';
import { CollisionWorld } from '../../src/physics/collisionWorld.js';
import { CharacterController } from '../../src/physics/characterController.js';
import { CameraEffects } from '../../src/player/cameraEffects.js';
import { Player } from '../../src/player/player.js';
import { InputManager } from '../../src/player/input.js';
import { Settings } from '../../src/player/settings.js';
import { EventBus } from '../../src/engine/events.js';

const DT = 1 / 60;
const DEG = Math.PI / 180;
const world = new CollisionWorld(buildLevelSolids(level));
const cmdOf = (o) => ({ moveX: 0, moveZ: 0, yaw: 0, sprint: false, walk: false, crouch: false, jump: false, ads: false, fire: false, ...o });

function rig(pos, motion = 1) {
  const settings = { v: { cameraMotion: motion }, get(k) { return this.v[k]; } };
  const c = new CharacterController(world, movement);
  c.teleport(new Vector3(pos[0], pos[1], pos[2]));
  const fx = new CameraEffects({ settings });
  fx.attach(c);
  const rec = [];
  const events = [];
  c.addListener((n, p) => events.push({ n, p, tick: c.tickCount }));
  const step = (cmd, n = 1) => {
    for (let i = 0; i < n; i++) {
      fx.snapshot();
      c.update(DT, cmd);
      fx.tick(DT, c, cmd.yaw || 0);
      const s = fx.sample(1);
      rec.push({ tick: c.tickCount, y: s.offsetY, side: s.side, roll: s.roll, pitch: s.pitch, lower: s.lower, step: fx.cur.step, landing: fx.cur.landing, amp: fx.cur.bobAmp });
    }
  };
  return { c, fx, rec, events, step, settings };
}

test('head bob is synced to foot contacts: the eye is lowest at each footstep, bob frequency = real cadence', () => {
  const cad = {};
  for (const [name, mode] of [['walk', { walk: true }], ['run', {}], ['sprint', { sprint: true }]]) {
    const r = rig([-30, 0, 28]);
    const cmd = cmdOf({ moveZ: 1, yaw: -90 * DEG, ...mode });
    r.step(cmd, 90);
    const from = r.c.tickCount;
    r.events.length = 0;
    r.step(cmd, 180);
    const steps = r.events.filter((e) => e.n === 'footstep').map((e) => e.tick);
    const rec = r.rec.filter((q) => q.tick > from);
    // local minima of the vertical bob
    const minima = [];
    for (let i = 1; i < rec.length - 1; i++) if (rec[i].y < rec[i - 1].y && rec[i].y <= rec[i + 1].y) minima.push(rec[i].tick);
    assert.ok(Math.abs(minima.length - steps.length) <= 1, `${name}: ${minima.length} bob minima vs ${steps.length} footsteps`);
    // every footstep coincides with a bob minimum (within one tick; minima need a neighbour on both sides)
    const lastTick = rec[rec.length - 1].tick;
    for (const t of steps.filter((x) => x > from + 1 && x < lastTick - 1)) {
      assert.ok(minima.some((m) => Math.abs(m - t) <= 1), `${name}: footstep at ${t} not at a bob minimum`);
    }
    cad[name] = steps.length / 3;
    const amp = Math.max(...rec.map((q) => Math.abs(q.y)));
    assert.ok(amp > 0.004 && amp <= 0.02 + 1e-9, `${name}: bob amplitude ${amp}`);
  }
  assert.ok(cad.walk < cad.run && cad.run < cad.sprint, JSON.stringify(cad));
  console.log(`bob / footstep cadence (steps/s): ${JSON.stringify(cad)}`);
});

test('stairs: a small dip + nod per riser; nothing on flat ground', () => {
  const m = level.markers.stairs_start;
  const r = rig(m.pos);
  let n = 0;
  while (r.c.position.z > -5.2 && n++ < 600) r.step(cmdOf({ moveZ: 1 }));
  const stepEvents = r.events.filter((e) => e.n === 'step').length;
  const minStep = Math.min(...r.rec.map((q) => q.step));
  const maxPitch = Math.max(...r.rec.map((q) => -q.pitch));
  assert.ok(stepEvents >= 7, `step events ${stepEvents}`);
  assert.ok(minStep < -0.004 && minStep >= -0.03 - 1e-9, `stair dip ${minStep}`);
  assert.ok(maxPitch > 0.1 * DEG && maxPitch < 1.5 * DEG, `stair nod ${maxPitch / DEG}°`);
  const f = rig([-20, 0, 26]);
  f.step(cmdOf({ moveZ: 1, sprint: true }), 120);
  assert.ok(f.rec.every((q) => q.step === 0), 'step impulse on flat ground');
});

test('landing dip scales with fall speed (none for tiny hops), bounded', () => {
  const dipOf = (start, jump) => {
    const r = rig(start);
    r.step(cmdOf({}), 5);
    if (jump) r.step(cmdOf({ jump: true }));
    let k = 0;
    const cmd = cmdOf({ moveZ: start[1] > 0 ? 1 : 0 });
    while (r.c.stats.landings === 0 && k++ < 300) r.step(cmd);
    r.step(cmdOf({}), 40);
    return Math.min(...r.rec.map((q) => q.landing));
  };
  const hop = dipOf([-20, 0, 26], true); // 0.45 m jump: ~3 m/s impact
  const drop = dipOf([9, 1.0, -7.2], false); // 1.0 m drop: ~4.4 m/s
  assert.ok(hop < -0.005, `jump landing dip ${hop}`);
  assert.ok(drop < hop * 1.2, `1 m drop ${drop} vs jump ${hop}`);
  assert.ok(drop >= -0.12 - 1e-9, `dip bounded: ${drop}`);
});

test('strafe roll leans into the sideways motion, <= 1°, none running straight', () => {
  const right = rig([-20, 0, 26]);
  right.step(cmdOf({ moveX: 1 }), 90);
  const left = rig([-20, 0, 26]);
  left.step(cmdOf({ moveX: -1 }), 90);
  const fwd = rig([-20, 0, 26]);
  fwd.step(cmdOf({ moveZ: 1 }), 90);
  const avgRoll = (r) => r.rec.slice(-30).reduce((a, q) => a + q.roll, 0) / 30;
  const rr = avgRoll(right);
  const lr = avgRoll(left);
  const fr = avgRoll(fwd);
  assert.ok(rr > 0.3 * DEG && rr <= 1.2 * DEG, `strafe right roll ${rr / DEG}°`);
  assert.ok(lr < -0.3 * DEG && lr >= -1.2 * DEG, `strafe left roll ${lr / DEG}°`);
  assert.ok(Math.abs(fr) < 0.1 * DEG, `running straight roll ${fr / DEG}°`);
});

test('traversal: roll / look-down arc during the vault, weapon lowered during and raised after', () => {
  const r = rig([15, 0, -3.3]);
  r.step(cmdOf({ jump: true }));
  assert.ok(r.c.traversing, JSON.stringify(r.c.lastTraversalFail));
  const inMove = [];
  let k = 0;
  while (r.c.traversing && k++ < 120) {
    r.step(cmdOf({}));
    inMove.push(r.rec[r.rec.length - 1]);
  }
  const peakRoll = Math.max(...inMove.map((q) => Math.abs(q.roll)));
  const peakPitch = Math.max(...inMove.map((q) => -q.pitch));
  const peakLower = Math.max(...inMove.map((q) => q.lower));
  assert.ok(peakRoll > 1 * DEG && peakRoll <= 2.5 * DEG, `roll ${peakRoll / DEG}°`);
  assert.ok(peakPitch > 1 * DEG && peakPitch <= 4 * DEG, `pitch ${peakPitch / DEG}°`);
  assert.ok(peakLower > 0.9, `weapon lowered ${peakLower}`);
  r.step(cmdOf({}), 60);
  const last = r.rec[r.rec.length - 1];
  assert.ok(last.lower < 0.05 && Math.abs(last.roll) < 0.05 * DEG, `after: lower ${last.lower}, roll ${last.roll}`);
});

test('camera motion 0 disables bob, dips, roll and nod (weapon lowering stays: gameplay feedback)', () => {
  const r = rig([-20, 0, 26], 0);
  r.step(cmdOf({ moveZ: 1, moveX: 1, sprint: true }), 90);
  r.step(cmdOf({ jump: true }));
  r.step(cmdOf({ moveX: 1 }), 80);
  assert.ok(r.rec.every((q) => q.y === 0 && q.side === 0 && q.roll === 0 && q.pitch === 0), 'camera effects with motion 0');
  const s = rig([-27, 0, 1.0], 0);
  let n = 0;
  while (s.c.position.z > -5.2 && n++ < 600) s.step(cmdOf({ moveZ: 1 }));
  assert.ok(s.rec.every((q) => q.y === 0 && q.pitch === 0), 'stair effects with motion 0');
  const v = rig([15, 0, -3.3], 0);
  v.step(cmdOf({ jump: true }));
  v.step(cmdOf({}), 20);
  assert.ok(v.rec.some((q) => q.lower > 0.5) && v.rec.every((q) => q.roll === 0 && q.pitch === 0));
});

test('Player: camera effects are interpolated between ticks, frozen while paused, and never move the simulation eye', () => {
  const bus = new EventBus();
  const input = new InputManager(bindings, bus);
  input.setEnabled(true);
  const settings = new Settings({ storage: null });
  settings.set('cameraMotion', 1);
  const c = new CharacterController(world, movement);
  const player = new Player({ controller: c, input, settings, events: bus, mouse: bindings.mouse });
  player.teleport(new Vector3(-10, 0, 26), -90, 0);
  input.handleKeyDown('KeyD'); // strafe (roll) while running
  input.handleKeyDown('KeyW');
  for (let i = 0; i < 90; i++) {
    player.tick(DT, null);
    input.consumeTick();
  }
  const q0 = new Quaternion();
  const q1 = new Quaternion();
  player.applyCameraEffects(q0.identity(), 0);
  player.applyCameraEffects(q1.identity(), 1);
  const eyes = [0, 0.25, 0.5, 0.75, 1].map((a) => player.getRenderEye(a, new Vector3()).y);
  const d = eyes.slice(1).map((y, i) => y - eyes[i]);
  assert.ok(d.every((x) => Math.sign(x) === Math.sign(d[0]) && Math.abs(x) > 1e-7), `eye not interpolated: ${d}`);
  assert.ok(q0.angleTo(new Quaternion()) > 0, 'camera roll applied');
  // simulation eye: exactly feet + eye height, no bob
  const sim = player.getSimEye(new Vector3());
  assert.ok(Math.abs(sim.y - (c.position.y + c.eyeHeight)) < 1e-12);
  // paused: holdInterpolation -> sample(0) == sample(1)
  player.holdInterpolation();
  const a = player.getRenderEye(0, new Vector3()).y;
  const b = player.getRenderEye(1, new Vector3()).y;
  assert.ok(Math.abs(a - b) < 1e-12, 'moves while paused');
  assert.ok(player.getState().cameraFx.stats.footsteps >= 2, 'footsteps reached the camera');
});
