// Character controller tests on the real test-range geometry (Node, no browser).
import test from 'node:test';
import assert from 'node:assert/strict';
import { Vector3 } from 'three';
import level from '../../src/data/test_range.json' with { type: 'json' };
import movement from '../../src/data/movement.json' with { type: 'json' };
import { buildLevelSolids } from '../../src/level/levelGeometry.js';
import { CollisionWorld } from '../../src/physics/collisionWorld.js';
import { CharacterController } from '../../src/physics/characterController.js';

const DT = 1 / 60;
const world = new CollisionWorld(buildLevelSolids(level));
const M = level.markers;
const DEG = Math.PI / 180;

function spawn(marker, overrides = {}) {
  const c = new CharacterController(world, movement);
  const p = overrides.pos || marker.pos;
  c.teleport(new Vector3(p[0], p[1], p[2]));
  return c;
}

function run(c, ticks, cmd) {
  for (let i = 0; i < ticks; i++) c.update(DT, cmd);
}

/** Runs until pred(c) is true or maxTicks elapse; returns ticks used. */
function runUntil(c, cmd, pred, maxTicks = 1200) {
  let i = 0;
  while (!pred(c) && i < maxTicks) {
    c.update(DT, cmd);
    i++;
  }
  return i;
}

function cmdOf(o) {
  return { moveX: 0, moveZ: 0, yaw: 0, sprint: false, walk: false, crouch: false, jump: false, ads: false, fire: false, ...o };
}

function measureSpeed(extra) {
  const m = M.speed_start;
  const c = spawn(m);
  const cmd = cmdOf({ moveZ: 1, yaw: m.yaw * DEG, ...extra });
  run(c, 90, cmd); // accelerate
  const p0 = c.position.clone();
  run(c, 60, cmd); // 1 s
  const d = c.position.clone().sub(p0);
  return Math.hypot(d.x, d.z);
}

test('spawn rests grounded on flat ground', () => {
  const c = spawn(M.spawn);
  run(c, 30, cmdOf({}));
  assert.ok(c.grounded);
  assert.ok(Math.abs(c.position.y) < 1e-3, `y=${c.position.y}`);
});

test('run / walk / sprint / crouch / ads speeds match config within 5%', () => {
  const cases = [
    ['run', {}, movement.speeds.run],
    ['walk', { walk: true }, movement.speeds.walk],
    ['sprint', { sprint: true }, movement.speeds.sprint],
    ['crouch', { crouch: true }, movement.speeds.crouch],
    ['ads', { ads: true }, movement.speeds.ads],
  ];
  for (const [name, extra, expected] of cases) {
    const v = measureSpeed(extra);
    assert.ok(Math.abs(v - expected) / expected < 0.05, `${name}: measured ${v.toFixed(3)} expected ${expected}`);
  }
});

test('diagonal input is not faster than forward', () => {
  const fwd = measureSpeed({});
  const diag = measureSpeed({ moveX: 1 });
  assert.ok(diag <= fwd * 1.001, `diag ${diag} fwd ${fwd}`);
  const sfwd = measureSpeed({ sprint: true });
  const sdiag = measureSpeed({ sprint: true, moveX: 1 });
  assert.ok(sdiag <= sfwd * 1.001, `sprint diag ${sdiag} fwd ${sfwd}`);
});

test('sprint is forward only (backwards falls back to run speed)', () => {
  const back = measureSpeed({ moveZ: -1, sprint: true });
  assert.ok(Math.abs(back - movement.speeds.run) / movement.speeds.run < 0.05, `back sprint ${back}`);
  const strafe = measureSpeed({ moveZ: 0, moveX: 1, sprint: true });
  assert.ok(Math.abs(strafe - movement.speeds.run) / movement.speeds.run < 0.05, `strafe sprint ${strafe}`);
});

test('climbs 0.18 m stairs to the landing', () => {
  const m = M.stairs_start;
  const c = spawn(m);
  const midLanding = (m.landingZ[0] + m.landingZ[1]) / 2;
  runUntil(c, cmdOf({ moveZ: 1 }), (cc) => cc.position.z < midLanding, 600);
  run(c, 10, cmdOf({}));
  assert.ok(c.position.z < midLanding + 0.2, `z=${c.position.z}`);
  assert.ok(Math.abs(c.position.y - m.landingY) < 0.02, `y=${c.position.y}`);
  assert.ok(c.grounded);
});

test('walks back down the stairs grounded (ground snapping)', () => {
  const m = M.stairs_start;
  const c = spawn(m, { pos: [m.pos[0], m.landingY, -5.5] });
  assert.ok(c.grounded);
  let airborneTicks = 0;
  for (let i = 0; i < 600 && c.position.z < 0; i++) {
    c.update(DT, cmdOf({ moveZ: -1 }));
    if (!c.grounded) airborneTicks++;
  }
  assert.ok(c.position.z >= 0 && Math.abs(c.position.y) < 0.01, `pos=${c.position.toArray()}`);
  assert.ok(airborneTicks <= 2, `airborne ticks while descending: ${airborneTicks}`);
});

test('cannot pass the 1.0 m wall (walking, sprinting, jumping)', () => {
  const m = M.wall1m_start;
  for (const extra of [{}, { sprint: true }, { sprint: true, jump: true }]) {
    const c = spawn(m);
    run(c, 240, cmdOf({ moveZ: 1, ...extra }));
    assert.ok(c.position.z > m.wallFrontZ, `${JSON.stringify(extra)} z=${c.position.z}`);
    assert.ok(c.position.y < 0.5 || !c.grounded, `stood on wall y=${c.position.y}`);
  }
});

test('cannot walk up the 50° slope, can walk up the 30° slope', () => {
  const c50 = spawn(M.slope50_start);
  let max50 = 0;
  for (let i = 0; i < 300; i++) {
    c50.update(DT, cmdOf({ moveZ: 1, sprint: true }));
    max50 = Math.max(max50, c50.position.y);
  }
  assert.ok(max50 < 0.3, `50deg max y=${max50}`);
  const c30 = spawn(M.slope30_start);
  runUntil(c30, cmdOf({ moveZ: 1 }), (cc) => cc.position.z < -6.5, 600);
  assert.ok(Math.abs(c30.position.y - M.slope30_start.topY) < 0.02, `30deg y=${c30.position.y}`);
});

test('crosses the 0.03 m threshold', () => {
  const m = M.threshold_start;
  const c = spawn(m);
  run(c, 150, cmdOf({ moveZ: 1 }));
  assert.ok(c.position.z < m.passZ, `z=${c.position.z}`);
});

test('passes the 0.90 m doorway', () => {
  const m = M.door_start;
  const c = spawn(m);
  run(c, 150, cmdOf({ moveZ: 1 }));
  assert.ok(c.position.z < m.passZ, `z=${c.position.z}`);
});

test('standing cannot enter the 1.40 m tunnel', () => {
  const m = M.tunnel_start;
  const c = spawn(m);
  run(c, 180, cmdOf({ moveZ: 1 }));
  assert.ok(c.position.z > m.entryZ, `z=${c.position.z}`);
});

test('crouches through the tunnel, cannot stand inside, stands after leaving', () => {
  const m = M.tunnel_start;
  const c = spawn(m);
  run(c, 10, cmdOf({ crouch: true }));
  // crouch-walk to the middle
  let ticks = 0;
  while (c.position.z > m.midZ && ticks < 600) {
    c.update(DT, cmdOf({ moveZ: 1, crouch: true }));
    ticks++;
  }
  assert.ok(c.position.z <= m.midZ, `reached z=${c.position.z}`);
  // release crouch inside: must stay crouched
  run(c, 60, cmdOf({ crouch: false }));
  assert.equal(c.crouched, true);
  assert.equal(c.height, movement.capsule.crouchHeight);
  // leave the tunnel with crouch released: stands up once outside
  ticks = 0;
  while (c.position.z > m.exitZ - 1.0 && ticks < 900) {
    c.update(DT, cmdOf({ moveZ: 1, crouch: false }));
    ticks++;
  }
  run(c, 30, cmdOf({}));
  assert.equal(c.crouched, false, `z=${c.position.z}`);
  assert.equal(c.height, movement.capsule.standHeight);
});

test('falls off the 1.0 m drop, lands and regains control', () => {
  const m = M.drop_start;
  const c = spawn(m);
  let wasOnPlatform = false;
  let ticks = 0;
  while (c.position.z > m.edgeZ - 0.6 && ticks < 900) {
    c.update(DT, cmdOf({ moveZ: 1 }));
    if (Math.abs(c.position.y - m.platformY) < 0.01 && c.grounded) wasOnPlatform = true;
    ticks++;
  }
  assert.ok(wasOnPlatform, 'walked up the ramp onto the platform');
  const landings0 = c.stats.landings;
  run(c, 90, cmdOf({ moveZ: 1 }));
  assert.ok(c.grounded && Math.abs(c.position.y) < 0.01, `y=${c.position.y}`);
  assert.ok(c.stats.landings > landings0, 'landing detected');
  assert.ok(c.stats.lastLandingSpeed > 3.5, `impact speed ${c.stats.lastLandingSpeed}`);
  // regain control: strafe right changes x
  const x0 = c.position.x;
  run(c, 60, cmdOf({ moveX: 1 }));
  assert.ok(c.position.x - x0 > 1.5, `dx=${c.position.x - x0}`);
});

test('sprinting straight at the 0.1 m wall does not tunnel through', () => {
  const m = M.thinwall_start;
  const c = spawn(m);
  run(c, 300, cmdOf({ moveZ: 1, sprint: true }));
  assert.ok(c.position.z > m.wallFrontZ, `z=${c.position.z}`);
  // even with an absurd velocity injected (e.g. explosion) it must not tunnel
  const c2 = spawn(m, { pos: [m.pos[0], 0, -3.0] });
  c2.velocity.set(0, 0, -40);
  c2.grounded = false;
  run(c2, 30, cmdOf({}));
  assert.ok(c2.position.z > m.wallFrontZ, `fast z=${c2.position.z}`);
});

test('jump reaches about 0.45 m apex and lands', () => {
  const c = spawn(M.spawn);
  run(c, 5, cmdOf({}));
  let maxY = 0;
  c.update(DT, cmdOf({ jump: true }));
  for (let i = 0; i < 90; i++) {
    c.update(DT, cmdOf({}));
    maxY = Math.max(maxY, c.position.y);
  }
  assert.ok(Math.abs(maxY - movement.jumpApexHeight) < 0.03, `apex ${maxY}`);
  assert.ok(c.grounded);
});

test('crouch height and eye height', () => {
  const c = spawn(M.spawn);
  run(c, 60, cmdOf({ crouch: true }));
  assert.equal(c.height, 1.2);
  assert.ok(Math.abs(c.eyeHeight - 1.05) < 1e-6);
  run(c, 60, cmdOf({}));
  assert.equal(c.height, 1.8);
  assert.ok(Math.abs(c.eyeHeight - 1.65) < 1e-6);
});

test('diagonal run into the L corner does not get pushed through or launched', () => {
  // corner walls at x=9 (east) and z=-16 (north); approach from south-west
  const c = spawn(M.spawn, { pos: [6.5, 0, -13.5] });
  const yaw = -45 * DEG; // north-east
  let maxY = 0;
  for (let i = 0; i < 240; i++) {
    c.update(DT, cmdOf({ moveZ: 1, yaw, sprint: true }));
    maxY = Math.max(maxY, c.position.y);
  }
  assert.ok(c.position.x < 8.875 - 0.34, `x=${c.position.x}`);
  assert.ok(c.position.z > -15.875 + 0.34, `z=${c.position.z}`);
  assert.ok(maxY < 0.01, `launched y=${maxY}`);
});

test('explicit step height limit: 0.30 m and 0.40 m steps climbed, 0.45 m and 1.0 m blocked', () => {
  const mkWorld = (h) =>
    new CollisionWorld(
      buildLevelSolids({
        solids: [
          { type: 'box', id: 'g', min: [-5, -0.5, -10], max: [5, 0, 5], mat: 'floor' },
          { type: 'box', id: 'step', min: [-2, 0, -6], max: [2, h, -2], mat: 'block' },
        ],
      }),
    );
  for (const [h, expectUp] of [
    [0.3, true],
    [0.4, true],
    [0.45, false],
    [1.0, false],
  ]) {
    for (const extra of [{ walk: true }, {}, { sprint: true }]) {
      const c = new CharacterController(mkWorld(h), movement);
      c.teleport(new Vector3(0, 0, 0));
      runUntil(c, cmdOf({ moveZ: 1, ...extra }), (cc) => cc.position.z < -3.5, 240);
      if (expectUp) {
        assert.ok(Math.abs(c.position.y - h) < 0.01 && c.position.z < -2.5, `h=${h} ${JSON.stringify(extra)} pos=${c.position.toArray()}`);
      } else {
        assert.ok(c.position.y < 0.01 && c.position.z > -2.0, `h=${h} ${JSON.stringify(extra)} pos=${c.position.toArray()}`);
      }
    }
  }
});

// ---------------------------------------------------------------- angled steps, perch, mount
// Custom geometry: a flat ground plus test obstacles. Regression tests for approach-angle
// dependent step failures, zero-rise "steps" along walls, edge perch and jump mounting.

const flatGround = { type: 'box', id: 'g', min: [-30, -0.5, -30], max: [30, 0, 30], mat: 'floor' };
const mkCustomWorld = (solids) => new CollisionWorld(buildLevelSolids({ solids: [flatGround, ...solids] }));
const MODES = [{ walk: true }, {}, { sprint: true }];
const modeName = (m) => (m.walk ? 'walk' : m.sprint ? 'sprint' : 'run');

/** Approaches a step face at z = -2 (step on the -z side) at `angDeg` from its normal. */
function approachStep(w, h, angDeg, mode, phase) {
  const c = new CharacterController(w, movement);
  const d0 = 1.2 + phase;
  c.teleport(new Vector3(-Math.sin(angDeg * DEG) * d0, 0, -2 + 0.35 + Math.cos(angDeg * DEG) * d0));
  const cmd = cmdOf({ moveZ: 1, yaw: -angDeg * DEG, ...mode });
  for (let t = 0; t < 240; t++) {
    c.update(DT, cmd);
    if (c.grounded && Math.abs(c.position.y - h) < 0.01) return { climbed: true, tick: t };
  }
  return { climbed: false, pos: c.position.toArray().map((v) => +v.toFixed(3)) };
}

test('steps up to maxStepHeight are climbed at any approach angle, speed and start phase', () => {
  for (const h of [0.25, 0.3, 0.4]) {
    const w = mkCustomWorld([{ type: 'box', id: 'step', min: [-12, 0, -8], max: [12, h, -2], mat: 'block' }]);
    const fails = [];
    for (const ang of [0, 15, 30, 45, 60, 75]) {
      for (const mode of MODES) {
        for (const phase of [0, 0.013, 0.029, 0.047]) {
          const r = approachStep(w, h, ang, mode, phase);
          if (!r.climbed) fails.push({ ang, mode: modeName(mode), phase, pos: r.pos });
        }
      }
    }
    assert.deepEqual(fails, [], `h=${h}: ${JSON.stringify(fails)}`);
  }
});

test('obstacles above maxStepHeight are never stepped onto, at any approach angle', () => {
  for (const h of [0.41, 0.45, 1.0]) {
    const w = mkCustomWorld([{ type: 'box', id: 'step', min: [-12, 0, -8], max: [12, h, -2], mat: 'block' }]);
    for (const ang of [0, 30, 60, 75]) {
      for (const mode of MODES) {
        const r = approachStep(w, h, ang, mode, 0.02);
        assert.equal(r.climbed, false, `h=${h} ang=${ang} ${modeName(mode)}`);
      }
    }
  }
});

test('diagonal climb of a 0.25 m riser / 0.30 m tread staircase: reaches the top, never airborne', () => {
  const solids = [];
  const n = 6;
  for (let i = 0; i < n; i++) {
    solids.push({ type: 'box', id: `s${i}`, min: [-6, 0, -2 - 0.3 * i - 0.3 * (i === n - 1 ? 6 : 1)], max: [6, 0.25 * (i + 1), -2 - 0.3 * i], mat: 'block' });
  }
  const w = mkCustomWorld(solids);
  for (const ang of [0, 20, 40, 50, 60]) {
    for (const mode of MODES) {
      const c = new CharacterController(w, movement);
      c.teleport(new Vector3(-Math.sin(ang * DEG) * 2, 0, -2 + 0.35 + Math.cos(ang * DEG) * 2));
      const cmd = cmdOf({ moveZ: 1, yaw: -ang * DEG, ...mode });
      let airborne = 0;
      let top = false;
      for (let t = 0; t < 600 && !top; t++) {
        c.update(DT, cmd);
        if (!c.grounded) airborne++;
        top = c.grounded && Math.abs(c.position.y - 0.25 * n) < 0.01;
      }
      assert.ok(top, `ang=${ang} ${modeName(mode)} stuck at ${c.position.toArray()}`);
      assert.equal(airborne, 0, `ang=${ang} ${modeName(mode)} airborne ticks`);
    }
  }
});

test('sliding along a tall wall: speed equals the tangential part of the wish, no fake step-ups', () => {
  const w = mkCustomWorld([{ type: 'box', id: 'wall', min: [-30, 0, -3], max: [30, 3, -2], mat: 'wall' }]);
  for (const [mode, speed] of [[{ walk: true }, movement.speeds.walk], [{}, movement.speeds.run]]) {
    for (const ang of [30, 45, 60, 80]) {
      const c = new CharacterController(w, movement);
      c.teleport(new Vector3(0, 0, -1.2));
      const cmd = cmdOf({ moveZ: 1, yaw: -ang * DEG, ...mode });
      run(c, 60, cmd);
      const x0 = c.position.x;
      const steps0 = c.stats.stepUps;
      run(c, 60, cmd);
      const v = c.position.x - x0;
      const expected = speed * Math.sin(ang * DEG);
      assert.ok(Math.abs(v - expected) < 0.02 * speed, `${modeName(mode)} ang=${ang}: slide ${v.toFixed(3)} m/s, expected ${expected.toFixed(3)}`);
      assert.equal(c.stats.stepUps - steps0, 0, 'no step-ups against a tall wall');
    }
  }
});

test('edge perch: cannot stand further past a 1.0 m drop than standPerchRadius', () => {
  const w = mkCustomWorld([{ type: 'box', id: 'plat', min: [-3, 0, -3], max: [3, 1.0, 0], mat: 'block' }]);
  // walk slowly off the edge (edge at z = 0, walking +z)
  const c = new CharacterController(w, movement);
  c.teleport(new Vector3(0, 1.0, -1));
  let lastPast = -Infinity;
  let lastFeet = 1;
  for (let i = 0; i < 300; i++) {
    c.update(DT, cmdOf({ moveZ: 1, yaw: Math.PI, walk: true }));
    if (c.grounded && c.position.y > 0.5) {
      lastPast = c.position.z;
      lastFeet = c.position.y;
    }
  }
  assert.ok(lastPast <= movement.standPerchRadius + 0.01, `stood ${lastPast} m past the edge`);
  assert.ok(lastFeet > 1.0 - 0.05, `feet sank to ${lastFeet} while perched`);
  assert.ok(c.grounded && c.position.y < 0.01, 'ended on the lower floor');
  // a capsule placed 0.30 m past the edge is not supported and falls
  const c2 = new CharacterController(w, movement);
  c2.teleport(new Vector3(0, 1.2, 0.3));
  run(c2, 120, cmdOf({}));
  assert.ok(c2.grounded && c2.position.y < 0.01, `placed past the edge: ${c2.position.toArray()}`);
  // but resting on a stair edge 0.28 m out, with the lower tread within maxStepHeight, is fine:
  // it stays there, grounded, with the bottom sphere on the edge (feet at 0.18 - (r - sqrt(r^2 - d^2)))
  const w3 = mkCustomWorld([{ type: 'box', id: 'tread', min: [-3, 0, -3], max: [3, 0.18, 0], mat: 'block' }]);
  const c3 = new CharacterController(w3, movement);
  c3.teleport(new Vector3(0, 0.3, 0.28));
  run(c3, 30, cmdOf({}));
  const r = movement.capsule.radius;
  const perchedFeet = 0.18 - (r - Math.sqrt(r * r - 0.28 * 0.28));
  assert.ok(c3.grounded, 'grounded on the stair edge');
  assert.ok(Math.abs(c3.position.z - 0.28) < 1e-3 && Math.abs(c3.position.y - perchedFeet) < 0.005, `stair edge perch: ${c3.position.toArray()}`);
});

test('a running jump (0.45 m apex) mounts a 0.42 m ledge but never a 0.50 m or higher one', () => {
  const mounts = (h) => {
    const w = mkCustomWorld([{ type: 'box', id: 'ledge', min: [-3, 0, -12], max: [3, h, -10], mat: 'block' }]);
    let n = 0;
    for (const mode of [{}, { sprint: true }]) {
      for (let jumpAt = 0; jumpAt <= 3.0; jumpAt += 0.05) {
        const c = new CharacterController(w, movement);
        c.teleport(new Vector3(0, 0, 0));
        const cmd = cmdOf({ moveZ: 1, ...mode });
        let k = 0;
        while (c.position.z - c.radius > -10 + jumpAt && k++ < 600) c.update(DT, cmd);
        c.update(DT, { ...cmd, jump: true });
        let on = false;
        for (let i = 0; i < 90; i++) {
          c.update(DT, cmd);
          if (c.grounded && Math.abs(c.position.y - h) < 0.02 && c.position.z < -10 && c.position.z > -12) on = true;
        }
        if (on) n++;
      }
    }
    return n;
  };
  assert.ok(mounts(0.42) > 0, '0.42 m ledge should be mountable with a well-timed jump');
  for (const h of [0.5, 0.55, 0.65]) assert.equal(mounts(h), 0, `${h} m ledge was mounted`);
});
