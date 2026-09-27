// Movement feel of the shared capsule controller (player AND bots): turning without "ice", stopping,
// no speed gain, jump buffering / coyote time / jumping at every gait, the sprint-jump-crouch bug, the 50°
// slope, gait-synced footsteps and stair step events. Node, real test-range geometry, fixed 60 Hz tick.
//
// Measured before the rework (old isotropic model, acceleration 10 / deceleration 12 m/s^2):
//   90° turn: sideways drift 0.83 m at run, 1.68 m at sprint (2.31 m turning the view), new heading after
//   0.43 / 0.57 s; stop from sprint 0.48 s; jump pressed 100 ms before landing and 67 ms after walking off
//   an edge: ignored; sprint-jump-crouch: 5.8 -> 5.2 m/s bled in the air, then 12 m/s^2 to crouch speed.
import test from 'node:test';
import assert from 'node:assert/strict';
import { Vector3 } from 'three';
import level from '../../src/data/test_range.json' with { type: 'json' };
import movement from '../../src/data/movement.json' with { type: 'json' };
import weaponsData from '../../src/data/weapons.json' with { type: 'json' };
import combat from '../../src/data/combat.json' with { type: 'json' };
import teams from '../../src/data/teams.json' with { type: 'json' };
import { buildLevelSolids } from '../../src/level/levelGeometry.js';
import { CollisionWorld } from '../../src/physics/collisionWorld.js';
import { CharacterController } from '../../src/physics/characterController.js';
import { updateHorizontalVelocity, locomotionParams } from '../../src/physics/locomotion.js';
import { EventBus } from '../../src/engine/events.js';
import { MatchSession } from '../../src/game/session.js';
import { IDLE_COMMAND } from '../../src/game/combatant.js';

const DT = 1 / 60;
const DEG = Math.PI / 180;
const world = new CollisionWorld(buildLevelSolids(level));
const M = level.markers;
const S = movement.speeds;
const hs = (c) => Math.hypot(c.velocity.x, c.velocity.z);
const cmdOf = (o) => ({ moveX: 0, moveZ: 0, yaw: 0, sprint: false, walk: false, crouch: false, jump: false, ads: false, fire: false, ...o });

function mk(p, w = world) {
  const c = new CharacterController(w, movement);
  c.teleport(new Vector3(p[0], p[1], p[2]));
  return c;
}
const run = (c, n, cmd) => {
  for (let i = 0; i < n; i++) c.update(DT, cmd);
};
/** Wish direction (unit) of a command, as the controller computes it. */
function wishDir(cmd) {
  const sy = Math.sin(cmd.yaw);
  const cy = Math.cos(cmd.yaw);
  const v = new Vector3(cy * cmd.moveX - sy * cmd.moveZ, 0, -sy * cmd.moveX - cy * cmd.moveZ);
  return v.normalize();
}

/**
 * Accelerates with `first` for 1.5 s on open ground, then switches to `second`. Returns the sideways drift
 * (final offset perpendicular to the new wish direction), the time until the velocity points within 10° of
 * the new wish, and the largest speed after the switch.
 */
function turn(first, second, start = [-20, 0, 26]) {
  const c = mk(start);
  run(c, 90, cmdOf(first));
  const v0 = hs(c);
  const p0 = c.position.clone();
  const c2 = cmdOf(second);
  const wd = wishDir(c2);
  const perp = new Vector3(-wd.z, 0, wd.x);
  let tHeading = null;
  let maxSpeed = 0;
  for (let i = 1; i <= 90; i++) {
    c.update(DT, c2);
    maxSpeed = Math.max(maxSpeed, hs(c));
    const v = new Vector3(c.velocity.x, 0, c.velocity.z);
    if (tHeading === null && v.length() > 0.2 && v.normalize().dot(wd) > Math.cos(10 * DEG)) tHeading = i * DT;
  }
  return { v0, drift: Math.abs(c.position.clone().sub(p0).dot(perp)), tHeading, maxSpeed };
}

// ---------------------------------------------------------------- turning / stopping (feedback 1)

test('turning 90° while running / sprinting: sideways drift <= 0.3 / 0.5 m, new heading within 0.25 s, no speed gain', () => {
  const rows = [];
  const cases = [
    // [label, first, second, max drift]
    ['run W->D', { moveZ: 1 }, { moveX: 1 }, 0.3],
    ['run W->A', { moveZ: 1 }, { moveX: -1 }, 0.3],
    ['run view +90', { moveZ: 1 }, { moveZ: 1, yaw: 90 * DEG }, 0.3],
    ['run view -90', { moveZ: 1 }, { moveZ: 1, yaw: -90 * DEG }, 0.3],
    ['sprint W->D', { moveZ: 1, sprint: true }, { moveX: 1, sprint: true }, 0.5],
    ['sprint W->A', { moveZ: 1, sprint: true }, { moveX: -1, sprint: true }, 0.5],
    ['sprint view +90', { moveZ: 1, sprint: true }, { moveZ: 1, sprint: true, yaw: 90 * DEG }, 0.5],
    ['sprint view -90', { moveZ: 1, sprint: true }, { moveZ: 1, sprint: true, yaw: -90 * DEG }, 0.5],
    ['sprint W->W+D (45°)', { moveZ: 1, sprint: true }, { moveZ: 1, moveX: 1, sprint: true }, 0.5],
    ['walk W->D', { moveZ: 1, walk: true }, { moveX: 1, walk: true }, 0.3],
  ];
  for (const [label, a, b, maxDrift] of cases) {
    const r = turn(a, b);
    rows.push(`${label}: drift ${r.drift.toFixed(3)} m, heading ${r.tHeading?.toFixed(3)} s`);
    assert.ok(r.drift <= maxDrift, `${label}: sideways drift ${r.drift.toFixed(3)} m > ${maxDrift}`);
    assert.ok(r.tHeading !== null && r.tHeading <= 0.25 + 1e-9, `${label}: new heading after ${r.tHeading} s`);
    assert.ok(r.maxSpeed <= r.v0 + 1e-6, `${label}: speed gain ${r.v0} -> ${r.maxSpeed}`);
  }
  console.log(`turns: ${rows.join('; ')}`);
});

test('stopping: from sprint within 0.25-0.45 s (not instant), from run and walk faster; never coasts on', () => {
  const stop = (mode) => {
    const c = mk([-20, 0, 26]);
    run(c, 90, cmdOf({ moveZ: 1, ...mode }));
    const p0 = c.position.clone();
    for (let i = 1; i <= 90; i++) {
      c.update(DT, cmdOf({}));
      if (hs(c) < 0.01) return { t: i * DT, d: c.position.distanceTo(p0) };
    }
    return { t: Infinity, d: c.position.distanceTo(p0) };
  };
  const sp = stop({ sprint: true });
  const rn = stop({});
  const wk = stop({ walk: true });
  assert.ok(sp.t >= 0.25 && sp.t <= 0.45, `sprint stop ${sp.t} s`);
  assert.ok(sp.d > 0.6 && sp.d < 1.6, `sprint stopping distance ${sp.d} m`);
  assert.ok(rn.t < sp.t && wk.t < rn.t, `run ${rn.t} s, walk ${wk.t} s`);
  console.log(`stop: sprint ${sp.t.toFixed(3)} s / ${sp.d.toFixed(2)} m, run ${rn.t.toFixed(3)} s, walk ${wk.t.toFixed(3)} s`);
});

test('smooth view turns keep sprint speed and the velocity follows the view (no ice), never faster than sprint', () => {
  for (const rate of [90, 180, 360]) {
    const c = mk([-20, 0, 26]);
    let yaw = 0;
    run(c, 90, cmdOf({ moveZ: 1, sprint: true }));
    let minSpeed = Infinity;
    let maxSpeed = 0;
    let maxLag = 0;
    for (let i = 0; i < 120; i++) {
      yaw += rate * DEG * DT;
      const cmd = cmdOf({ moveZ: 1, sprint: true, yaw });
      c.update(DT, cmd);
      minSpeed = Math.min(minSpeed, hs(c));
      maxSpeed = Math.max(maxSpeed, hs(c));
      const v = new Vector3(c.velocity.x, 0, c.velocity.z).normalize();
      maxLag = Math.max(maxLag, Math.acos(Math.min(1, v.dot(wishDir(cmd)))) / DEG);
    }
    assert.ok(maxSpeed <= S.sprint + 1e-6, `${rate}°/s: speed ${maxSpeed}`);
    assert.ok(minSpeed >= 0.9 * S.sprint, `${rate}°/s: speed dropped to ${minSpeed}`);
    assert.ok(maxLag < 12, `${rate}°/s: velocity lags the view by ${maxLag.toFixed(1)}°`);
  }
});

test('no speed gain from strafing, zig-zag, air strafing or repeated (buffered) jumps', () => {
  // zig-zag on the ground at sprint
  const c = mk([-20, 0, 26]);
  let maxSpeed = 0;
  for (let i = 0; i < 360; i++) {
    const side = Math.floor(i / 20) % 2 === 0 ? 1 : -1;
    c.update(DT, cmdOf({ moveZ: 1, moveX: side, sprint: true }));
    maxSpeed = Math.max(maxSpeed, hs(c));
  }
  assert.ok(maxSpeed <= S.sprint + 1e-6, `zig-zag ${maxSpeed}`);
  // bunny hop: jump on every landing (buffer), strafing and turning the view in the air
  const b = mk([-20, 0, 26]);
  run(b, 90, cmdOf({ moveZ: 1, sprint: true }));
  let yaw = 0;
  let bMax = 0;
  for (let i = 0; i < 600; i++) {
    yaw += (Math.floor(i / 25) % 2 === 0 ? 1 : -1) * 150 * DEG * DT;
    const side = Math.floor(i / 25) % 2 === 0 ? 1 : -1;
    b.update(DT, cmdOf({ moveZ: 1, moveX: side, sprint: true, yaw, jump: i % 6 === 0 }));
    bMax = Math.max(bMax, hs(b));
  }
  assert.ok(b.stats.jumps >= 10, `jumps ${b.stats.jumps}`);
  assert.ok(bMax <= S.sprint + 1e-6, `bunny hop / air strafe speed ${bMax}`);
});

test('walls: sliding speed is the tangential part of the wish (projection), pressing straight into a wall stops the slide', () => {
  const L = locomotionParams(movement);
  const walls = [new Vector3(0, 0, 1)]; // wall normal +z (wall on the -z side)
  const v = { x: 0, z: 0 };
  const push = { x: 0, z: 0 };
  const ang = 45 * DEG; // wish 45° into the wall
  for (let i = 0; i < 120; i++) {
    updateHorizontalVelocity(v, Math.sin(ang), -Math.cos(ang), S.run, true, L, DT, walls, 1, push);
    if (v.z < 0) v.z = 0; // the wall removes the into-wall part (as the controller does)
  }
  assert.ok(Math.abs(v.x - S.run * Math.sin(ang)) < 1e-6, `slide ${v.x}`);
  assert.ok(push.z < 0, 'the removed into-wall part keeps pressing against the wall');
  for (let i = 0; i < 30; i++) updateHorizontalVelocity(v, 0, -1, S.run, true, L, DT, walls, 1, push);
  assert.ok(Math.hypot(v.x, v.z) < 1e-6, `pressing straight into the wall: ${v.x}, ${v.z}`);
});

// ---------------------------------------------------------------- jumping (feedback 6)

test('jumps while walking, running and sprinting: ~0.45 m apex, forward speed kept in the air', () => {
  for (const [name, mode, speed] of [['walk', { walk: true }, S.walk], ['run', {}, S.run], ['sprint', { sprint: true }, S.sprint]]) {
    const c = mk([-20, 0, 26]);
    const cmd = cmdOf({ moveZ: 1, ...mode });
    run(c, 60, cmd);
    c.update(DT, { ...cmd, jump: true });
    let apex = 0;
    let minAirSpeed = Infinity;
    for (let i = 0; i < 80; i++) {
      c.update(DT, cmd);
      apex = Math.max(apex, c.position.y);
      if (!c.grounded) minAirSpeed = Math.min(minAirSpeed, hs(c));
    }
    assert.equal(c.stats.jumps, 1, `${name}: jumps`);
    assert.ok(Math.abs(apex - movement.jumpApexHeight) < 0.03, `${name}: apex ${apex}`);
    assert.ok(minAirSpeed >= speed * 0.98, `${name}: air speed ${minAirSpeed} vs ${speed}`);
    assert.ok(c.grounded, `${name}: landed`);
  }
});

/** Walks (running) off the 1.0 m drop edge; returns the controller right after it left the ground. */
function offTheEdge(extra = {}) {
  const c = mk([9, 1.0, -7.2]);
  const cmd = cmdOf({ moveZ: 1, ...extra });
  let n = 0;
  while (c.grounded && n++ < 300) c.update(DT, cmd);
  assert.ok(!c.grounded, 'left the platform');
  return { c, cmd };
}

test('jump input is buffered: pressed up to 150 ms before landing it fires on landing, earlier presses do not', () => {
  // landing tick of the fall from the 1.0 m platform
  const probe = offTheEdge();
  let landTick = 0;
  while (!probe.c.grounded && landTick < 200) {
    probe.c.update(DT, probe.cmd);
    landTick++;
  }
  for (const [msBefore, expect] of [[17, 1], [50, 1], [100, 1], [150, 1], [217, 0], [300, 0]]) {
    const { c, cmd } = offTheEdge();
    const pressAt = landTick - Math.round(msBefore / (1000 * DT));
    let jumpTick = null;
    let landedAt = null;
    for (let i = 0; i < landTick + 30; i++) {
      c.update(DT, { ...cmd, jump: i === pressAt });
      if (landedAt === null && c.stats.landings > 0) landedAt = i;
      if (jumpTick === null && c.stats.jumps > 0) jumpTick = i;
    }
    assert.equal(c.stats.jumps, expect, `pressed ${msBefore} ms before landing: jumps ${c.stats.jumps}`);
    if (expect) assert.ok(jumpTick - landedAt <= 1, `buffered jump ${jumpTick - landedAt} ticks after landing`);
  }
});

test('coyote time: a jump up to ~120 ms after walking off an edge still works, later it does not; never a double jump', () => {
  for (const [ticksAfter, expect] of [[0, 1], [3, 1], [6, 1], [9, 0], [15, 0]]) {
    for (const mode of [{}, { sprint: true }]) {
      const { c, cmd } = offTheEdge(mode);
      run(c, ticksAfter, cmd);
      const vyBefore = c.velocity.y;
      c.update(DT, { ...cmd, jump: true });
      assert.equal(c.stats.jumps, expect, `${ticksAfter} ticks after leaving (${JSON.stringify(mode)}): jumps ${c.stats.jumps}`);
      if (expect) {
        assert.equal(c.stats.coyoteJumps, 1);
        assert.ok(c.velocity.y > vyBefore + 2, 'full jump impulse');
      }
      // a second press in the air never jumps again, even held every tick (until the landing)
      for (let i = 0; i < 60 && !c.grounded; i++) c.update(DT, { ...cmd, jump: true });
      assert.equal(c.stats.jumps, expect, 'no double jump in the air');
    }
  }
  // standing jump: pressing at the apex does nothing, holding jump every tick (bot style) gives one jump per landing
  const c = mk([-20, 0, 26]);
  run(c, 5, cmdOf({}));
  c.update(DT, cmdOf({ jump: true }));
  run(c, 18, cmdOf({}));
  c.update(DT, cmdOf({ jump: true }));
  run(c, 60, cmdOf({}));
  assert.equal(c.stats.jumps, 1, 'apex press ignored');
  const h = mk([-20, 0, 26]);
  run(h, 5, cmdOf({}));
  let airJumps = 0;
  for (let i = 0; i < 240; i++) {
    const wasAir = !h.grounded;
    const j0 = h.stats.jumps;
    h.update(DT, cmdOf({ jump: true }));
    if (wasAir && h.stats.jumps > j0 && h.stats.coyoteJumps > 0) airJumps++;
  }
  assert.equal(airJumps, 0, 'no jump from mid-air while holding jump');
  assert.ok(h.stats.jumps >= 3 && h.stats.jumps <= h.stats.landings + 1, `jumps ${h.stats.jumps}, landings ${h.stats.landings}`);
});

test('no jump while crouched under the tunnel roof (crouch released, no headroom)', () => {
  const m = M.tunnel_start;
  const c = mk(m.pos);
  run(c, 10, cmdOf({ crouch: true }));
  let n = 0;
  while (c.position.z > m.midZ && n++ < 600) c.update(DT, cmdOf({ moveZ: 1, crouch: true }));
  const y0 = c.position.y;
  let maxY = y0;
  for (let i = 0; i < 60; i++) {
    c.update(DT, cmdOf({ jump: i % 10 === 0 }));
    maxY = Math.max(maxY, c.position.y);
  }
  assert.equal(c.crouched, true);
  assert.equal(c.stats.jumps, 0, 'jumped under the roof');
  assert.ok(maxY - y0 < 1e-6, `lifted ${maxY - y0}`);
});

test('standing under a low ceiling: no jump when the head has no room (also buffered / coyote), a higher ceiling stops the jump without penetration', () => {
  const flat = { type: 'box', id: 'g', min: [-10, -0.5, -10], max: [10, 0, 10], mat: 'floor' };
  const ceilingAt = (y) => new CollisionWorld(buildLevelSolids({ solids: [flat, { type: 'box', id: 'c', min: [-2, y, -2], max: [2, y + 0.3, 2] }] }));
  // 1.83 m: 3 cm above the standing head -> refused (stand, walk, run, sprint, and a buffered press)
  for (const mode of [{}, { moveZ: 1, walk: true }, { moveZ: 1 }, { moveZ: 1, sprint: true }]) {
    const c = mk([0, 0, 1.2], ceilingAt(1.83));
    run(c, 2, cmdOf({}));
    const cmd = cmdOf({ yaw: 0, ...mode }); // stays under the slab for the 8 ticks (Space pressed on every one)
    let maxY = 0;
    for (let i = 0; i < 8; i++) {
      c.update(DT, { ...cmd, jump: true });
      maxY = Math.max(maxY, c.position.y);
      assert.ok(!c.overlaps(c.position, c.height, 0.002), `${JSON.stringify(mode)}: overlap under the slab`);
    }
    assert.equal(c.stats.jumps, 0, `${JSON.stringify(mode)}: jumped with 3 cm of headroom`);
    assert.ok(maxY < 1e-6, `${JSON.stringify(mode)}: lifted ${maxY}`);
  }
  // 2.05 m: the jump starts, the head stops at the slab (never inside it), then it falls back
  const c = mk([0, 0, 0], ceilingAt(2.05));
  run(c, 2, cmdOf({}));
  c.update(DT, cmdOf({ jump: true }));
  assert.equal(c.stats.jumps, 1);
  let maxTop = 0;
  for (let i = 0; i < 90; i++) {
    c.update(DT, cmdOf({}));
    maxTop = Math.max(maxTop, c.position.y + c.height);
    assert.ok(!c.overlaps(c.position, c.height, 0.002), `head in the slab at tick ${i}: ${c.position.y}`);
  }
  assert.ok(maxTop <= 2.05 + 1e-3 && maxTop > 1.95, `head top ${maxTop}`);
  assert.ok(c.grounded && Math.abs(c.position.y) < 1e-6, 'back on the floor');
});

// ---------------------------------------------------------------- sprint -> jump -> crouch (feedback 11)

test('sprint, jump, crouch within 1 s: momentum is kept in the air, landing crouched slows smoothly to crouch speed (no dead stop)', () => {
  for (const delayTicks of [3, 10, 20, 30, 45, 60]) {
    const c = mk([-20, 0, 26]);
    const sp = cmdOf({ moveZ: 1, sprint: true });
    run(c, 90, sp);
    c.update(DT, { ...sp, jump: true });
    run(c, delayTicks, sp);
    const crouchCmd = { ...sp, crouch: true };
    let landSpeed = null;
    let prevSpeed = hs(c);
    let maxDecel = 0;
    let airMin = Infinity;
    const p0 = c.position.clone();
    let tReach = null;
    for (let i = 1; i <= 90; i++) {
      const wasAir = !c.grounded;
      c.update(DT, crouchCmd);
      const v = hs(c);
      if (!c.grounded) airMin = Math.min(airMin, v);
      if (wasAir && c.grounded && landSpeed === null) landSpeed = v;
      maxDecel = Math.max(maxDecel, (prevSpeed - v) / DT);
      if (tReach === null && v <= S.crouch + 1e-6) tReach = i * DT;
      prevSpeed = v;
      assert.ok(v >= S.crouch - 1e-6, `delay ${delayTicks}: dropped below crouch speed (${v})`);
    }
    assert.equal(c.crouched, true);
    if (Number.isFinite(airMin)) assert.ok(airMin >= S.sprint - 1e-6, `delay ${delayTicks}: air speed bled to ${airMin}`);
    if (landSpeed !== null) assert.ok(landSpeed >= S.sprint - 0.2, `delay ${delayTicks}: landing speed ${landSpeed}`);
    assert.ok(maxDecel <= movement.speedChangeDeceleration + 1e-6, `delay ${delayTicks}: deceleration ${maxDecel} m/s^2`);
    assert.ok(tReach !== null && tReach > 0.4 && tReach < 1.4, `delay ${delayTicks}: crouch speed after ${tReach} s`);
    assert.ok(c.position.distanceTo(p0) > 2.0, `delay ${delayTicks}: travelled only ${c.position.distanceTo(p0)} m`);
  }
});

test('crouching in the air tucks the capsule (feet stay, head lowers); standing up in the air needs headroom', () => {
  const c = mk([-20, 0, 26]);
  run(c, 5, cmdOf({}));
  c.update(DT, cmdOf({ jump: true }));
  run(c, 5, cmdOf({}));
  const y = c.position.y;
  c.update(DT, cmdOf({ crouch: true }));
  assert.equal(c.height, movement.capsule.crouchHeight);
  assert.ok(c.position.y > y, 'still rising (velocity unchanged)');
  // under the tunnel roof: jump in, crouch in the air -> cannot stand while under the roof
  const t = mk([3, 0, -5.5]);
  run(t, 10, cmdOf({ crouch: true }));
  assert.equal(t.crouched, true);
  run(t, 30, cmdOf({ crouch: false }));
  assert.equal(t.crouched, true, 'no headroom in the tunnel');
});

// ---------------------------------------------------------------- 50° slope (feedback 4)

test('50° slope: jumping against it never climbs it and never jitters; at rest the capsule is perfectly still', () => {
  for (const mode of [{}, { sprint: true }]) {
    const c = mk(M.slope50_start.pos);
    c.traversalEnabled = false;
    const cmd = cmdOf({ moveZ: 1, ...mode });
    run(c, 120, cmd);
    let maxY = 0;
    let groundFlipsInFlight = 0;
    for (let k = 0; k < 8; k++) {
      c.update(DT, { ...cmd, jump: true });
      let g = c.grounded;
      for (let i = 0; i < 50; i++) {
        c.update(DT, cmd);
        maxY = Math.max(maxY, c.position.y);
        if (c.grounded !== g && c.grounded === false) groundFlipsInFlight++;
        g = c.grounded;
      }
    }
    assert.equal(c.stats.jumps, 8);
    assert.ok(maxY < movement.jumpApexHeight + 0.01, `climbed to ${maxY}`);
    assert.equal(groundFlipsInFlight, 0, 'grounded -> airborne flicker after landing');
    run(c, 30, cmd);
    const p = c.position.clone();
    let maxMove = 0;
    for (let i = 0; i < 120; i++) {
      const q = c.position.clone();
      c.update(DT, cmd);
      maxMove = Math.max(maxMove, c.position.distanceTo(q));
    }
    assert.ok(c.grounded && maxMove < 1e-9 && c.position.distanceTo(p) < 1e-9, `${JSON.stringify(mode)}: rest jitter ${maxMove}`);
  }
});

// ---------------------------------------------------------------- gait, footsteps, stair steps (feedback 2, SND-01)

test('footsteps follow the real gait: cadence and step length grow with speed, feet alternate, landings count, silent when still', () => {
  const rows = [];
  let prevCadence = 0;
  for (const [name, mode, speed, lenRange] of [
    ['crouch', { crouch: true }, S.crouch, [0.5, 0.8]],
    ['walk', { walk: true }, S.walk, [0.6, 0.85]],
    ['run', {}, S.run, [0.95, 1.3]],
    ['sprint', { sprint: true }, S.sprint, [1.35, 1.8]],
  ]) {
    const c = mk([-30, 0, 28]);
    const steps = [];
    c.addListener((n, p) => n === 'footstep' && steps.push(p));
    const cmd = cmdOf({ moveZ: 1, yaw: -90 * DEG, ...mode });
    run(c, 60, cmd);
    steps.length = 0;
    run(c, 180, cmd); // 3 s at full speed
    const cadence = steps.length / 3;
    const stepLen = speed / cadence;
    rows.push(`${name} ${cadence.toFixed(2)} steps/s, ${stepLen.toFixed(2)} m`);
    assert.ok(stepLen >= lenRange[0] && stepLen <= lenRange[1], `${name}: step length ${stepLen}`);
    // walk < run < sprint (crouch-walking uses short, quick steps and is not part of the ordering)
    if (name !== 'crouch') {
      assert.ok(cadence > prevCadence, `${name}: cadence ${cadence} after ${prevCadence}`);
      prevCadence = cadence;
    }
    for (let i = 1; i < steps.length; i++) assert.notEqual(steps[i].foot, steps[i - 1].foot, 'feet alternate');
    assert.ok(steps.every((s) => s.kind === 'step' && s.loudness > 0 && Math.abs(s.speed - speed) < 0.05), JSON.stringify(steps[0]));
    // stop: at most one settling step event, then silence
    steps.length = 0;
    run(c, 120, cmdOf({ yaw: -90 * DEG }));
    const afterStop = steps.length;
    steps.length = 0;
    run(c, 120, cmdOf({ yaw: -90 * DEG }));
    assert.ok(afterStop <= 1, `${name}: ${afterStop} steps while stopping`);
    assert.equal(steps.length, 0, `${name}: steps while standing still`);
  }
  console.log(`gait: ${rows.join('; ')}`);
  // landing is a (louder) contact; nothing in the air
  const c = mk([-20, 0, 26]);
  const ev = [];
  c.addListener((n, p) => n === 'footstep' && ev.push({ ...p, air: !c.grounded }));
  run(c, 5, cmdOf({}));
  c.update(DT, cmdOf({ jump: true }));
  run(c, 60, cmdOf({}));
  assert.equal(ev.length, 1, `events around a standing jump: ${ev.length}`);
  assert.equal(ev[0].kind, 'land');
});

test('stairs emit a step event per riser (up and down); slopes and flat ground do not', () => {
  const m = M.stairs_start;
  const up = mk(m.pos);
  const upEv = [];
  up.addListener((n, p) => n === 'step' && upEv.push(p.dy));
  let n = 0;
  while (up.position.z > -5.2 && n++ < 600) up.update(DT, cmdOf({ moveZ: 1 }));
  assert.ok(upEv.filter((d) => d > 0.1 && d < 0.3).length >= 7, `up steps ${JSON.stringify(upEv.map((d) => +d.toFixed(3)))}`);
  const down = mk([m.pos[0], m.landingY, -5.5]);
  const downEv = [];
  down.addListener((nm, p) => nm === 'step' && downEv.push(p.dy));
  n = 0;
  while (down.position.z < 0.5 && n++ < 600) down.update(DT, cmdOf({ moveZ: -1 }));
  assert.ok(downEv.filter((d) => d < -0.1 && d > -0.3).length >= 7, `down steps ${JSON.stringify(downEv.map((d) => +d.toFixed(3)))}`);
  for (const [label, start, cmd] of [
    ['30° slope', M.slope30_start.pos, cmdOf({ moveZ: 1, sprint: true })],
    ['15° ramp', [9, 0, 1.5], cmdOf({ moveZ: 1, sprint: true })],
    ['flat', [-20, 0, 26], cmdOf({ moveZ: 1, sprint: true })],
  ]) {
    const c = mk(start);
    const ev = [];
    c.addListener((nm) => nm === 'step' && ev.push(1));
    run(c, 90, cmd);
    assert.equal(ev.length, 0, `${label}: ${ev.length} step events`);
  }
});

test('staircase: foot contacts land on the treads (1 per 2 treads walking), footsteps sync to the risers up and down, flat cadence unchanged', () => {
  // a long flight (20 risers of 0.17 / 0.28 m) so the phase lock has time to settle
  const flat = { type: 'box', id: 'g', min: [-10, -0.5, -20], max: [10, 0, 10], mat: 'floor' };
  const w = new CollisionWorld(buildLevelSolids({ solids: [flat, { type: 'stairs', id: 's', x: [-1, 1], zStart: 0, dir: -1, riser: 0.17, tread: 0.28, risers: 20, landingDepth: 3, mat: 'stair' }] }));
  const rows = [];
  for (const [name, mode] of [['walk', { walk: true }], ['run', {}], ['crouch', { crouch: true }]]) {
    for (const dir of ['up', 'down']) {
      const c = mk(dir === 'up' ? [0, 0, 2] : [0, 3.4, -7.0], w);
      const risers = [];
      const steps = [];
      c.addListener((n) => {
        if (n === 'step') risers.push(c.tickCount);
        if (n === 'footstep') steps.push(c.tickCount);
      });
      const cmd = cmdOf({ moveZ: dir === 'up' ? 1 : -1, ...mode });
      for (let i = 0; i < 900; i++) {
        c.update(DT, cmd);
        if (dir === 'up' ? c.position.z < -6.2 : c.position.z > 1.5) break;
      }
      assert.ok(risers.length >= 19, `${name} ${dir}: risers ${risers.length}`);
      const half = risers[Math.floor(risers.length / 2)];
      const last = risers[risers.length - 1];
      const late = steps.filter((t) => t >= half && t <= last);
      const off = late.map((t) => Math.min(...risers.map((r) => Math.abs(r - t))));
      const cadence = late.length / ((last - half) * DT);
      rows.push(`${name} ${dir}: ${cadence.toFixed(2)} steps/s, footstep-riser offsets ${JSON.stringify(off)}`);
      assert.ok(late.length >= 2, `${name} ${dir}: footsteps on the second half ${late.length}`);
      assert.ok(off.every((d) => d <= 1), `${name} ${dir}: footsteps off the risers by ${JSON.stringify(off)} ticks`);
      if (name !== 'run') assert.ok(cadence <= 3.2 + 0.35, `${name} ${dir}: stair cadence ${cadence}`);
      assert.ok(c.stride.tread > 0.25 && c.stride.tread < 0.31, `${name} ${dir}: tread estimate ${c.stride.tread}`);
    }
  }
  console.log(`stairs gait: ${rows.join('; ')}`);
});

// ---------------------------------------------------------------- bots use the same controller

test('bots: a Combatant turning at sprint has the same small drift, and its footsteps reach the bus with the contract payload', () => {
  const events = new EventBus();
  let bots = [];
  const cmds = new Map();
  const createAISystem = () => ({
    addBot: (c) => bots.push(c),
    removeBot: (id) => (bots = bots.filter((b) => b.id !== id)),
    update: (dt) => {
      for (const b of bots) if (b.alive) b.applyCommand(cmds.get(b.id) || { ...IDLE_COMMAND, yaw: b.yaw, pitch: b.pitch }, dt);
    },
    getDebug: () => ({}),
    reset: () => {},
  });
  const s = new MatchSession({ level, world, movement, weaponsData, combat, teams, events, createAISystem, seed: 5, bots: [0, 1, 0], mode: 'match' });
  s.start({ skipPreRound: true });
  const bot = s.combatants.all().find((c) => !c.isPlayer);
  assert.ok(bot.controller instanceof CharacterController, 'bots use the shared controller');
  bot.controller.teleport(new Vector3(-20, 0, 26));
  bot.yaw = 0;
  const steps = [];
  events.on('footstep', (p) => p.id === bot.id && steps.push(p));
  const tick = (n) => {
    for (let i = 0; i < n; i++) s.tick(DT, { playerCmd: null });
  };
  cmds.set(bot.id, { ...IDLE_COMMAND, moveZ: 1, sprint: true, yaw: 0, pitch: 0 });
  tick(90);
  const p0 = bot.position.clone();
  cmds.set(bot.id, { ...IDLE_COMMAND, moveX: 1, sprint: true, yaw: 0, pitch: 0 });
  tick(90);
  const drift = Math.abs(bot.position.z - p0.z);
  assert.ok(drift <= 0.5, `bot sideways drift ${drift}`);
  assert.ok(steps.length >= 5, `bot footsteps ${steps.length}`);
  const f = steps[steps.length - 1];
  assert.equal(f.team, bot.team);
  assert.ok(f.position && typeof f.position.distanceTo === 'function', 'position is a Vector3');
  assert.equal(f.surface, 'concrete');
  assert.ok(f.loudness > 0 && f.speed > 1, JSON.stringify(f));
  s.dispose?.();
});
