// Vault / mantle (src/physics/traversal.js) on the real test range and on custom geometry: which obstacles
// can be crossed, which must be refused (too high, ceiling above the ledge, narrow landing, small window,
// crouched under a roof), that the capsule never overlaps geometry on any tick, input lock, events, bots.
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
import { planTraversal, traversalParams } from '../../src/physics/traversal.js';
import { EventBus } from '../../src/engine/events.js';
import { MatchSession } from '../../src/game/session.js';
import { IDLE_COMMAND } from '../../src/game/combatant.js';

const DT = 1 / 60;
const DEG = Math.PI / 180;
const range = new CollisionWorld(buildLevelSolids(level));
const TP = traversalParams(movement);
const cmdOf = (o) => ({ moveX: 0, moveZ: 0, yaw: 0, sprint: false, walk: false, crouch: false, jump: false, ads: false, fire: false, ...o });
const flat = { type: 'box', id: 'g', min: [-30, -0.5, -30], max: [30, 0, 30], mat: 'floor' };
const custom = (solids) => new CollisionWorld(buildLevelSolids({ solids: [flat, ...solids] }));
const MODE = { stand: {}, walk: { walk: true }, run: {}, sprint: { sprint: true } };

/**
 * Approaches along the view direction (yaw) from `start` and presses jump once when the capsule has moved
 * `pressAfter` metres (0 = immediately, standing). Records every tick: overlap with the world, events.
 */
function attempt(world, start, { yaw = 0, mode = 'run', pressAfter = null, ticks = 150, duringCmd = null, crouch = false, setup = null, stopAfterTraversal = false } = {}) {
  const c = new CharacterController(world, movement);
  c.teleport(new Vector3(start[0], start[1], start[2]));
  if (setup) setup(c);
  const ev = [];
  c.addListener((n, p) => {
    if (n.startsWith('traverse')) ev.push({ n, p, tick: c.tickCount, pos: c.position.clone() });
  });
  const moving = mode !== 'stand';
  const base = cmdOf({ moveZ: moving ? 1 : 0, yaw, crouch, ...MODE[mode] });
  const fwd = new Vector3(-Math.sin(yaw), 0, -Math.cos(yaw));
  const s0 = new Vector3(start[0], 0, start[2]);
  let pressed = false;
  let done = false;
  let overlapTicks = 0;
  let maxY = -Infinity;
  const path = [];
  for (let i = 0; i < ticks; i++) {
    const along = c.position.clone().sub(s0).dot(fwd);
    const press = !pressed && along >= (pressAfter ?? 0);
    if (press) pressed = true;
    const inTrav = c.traversing;
    let cmd = inTrav && duringCmd ? { ...base, ...duringCmd } : { ...base, jump: press };
    if (done && stopAfterTraversal) cmd = cmdOf({ yaw });
    c.update(DT, cmd);
    if (c.overlaps(c.position, c.height, 0.002)) overlapTicks++;
    maxY = Math.max(maxY, c.position.y);
    if (c.traversing) path.push(c.position.clone());
    if (c.stats.traversals > 0 && !c.traversing) done = true;
  }
  const start_ = ev.find((e) => e.n === 'traverse:start');
  const end_ = ev.find((e) => e.n === 'traverse:end');
  return { c, ev, start: start_ ? start_.p : null, end: end_ ? end_.p : null, overlapTicks, maxY, path, fail: c.lastTraversalFail };
}

function assertClean(r, label) {
  assert.equal(r.overlapTicks, 0, `${label}: capsule overlapped geometry on ${r.overlapTicks} ticks`);
}

// ---------------------------------------------------------------- test range stations

test('test range 1.0 m wall: vault over it standing, walking, running and sprinting (0.5-0.9 s, faster with speed)', () => {
  const back = -4.15;
  let prevDur = Infinity;
  const rows = [];
  for (const mode of ['stand', 'walk', 'run', 'sprint']) {
    const start = mode === 'stand' ? [15, 0, -3.45] : [15, 0, 0];
    const r = attempt(range, start, { mode, pressAfter: mode === 'stand' ? 0 : 2.9, ticks: 240 });
    assert.ok(r.start, `${mode}: no traversal (${JSON.stringify(r.fail)})`);
    assert.equal(r.start.type, 'vault');
    assert.ok(Math.abs(r.start.obstacleHeight - 1.0) < 0.01, `${mode}: height ${r.start.obstacleHeight}`);
    assert.ok(r.start.duration >= 0.5 && r.start.duration <= 0.9, `${mode}: duration ${r.start.duration}`);
    assert.ok(r.start.duration <= prevDur + 1e-9, `${mode}: slower than the slower gait`);
    prevDur = r.start.duration;
    assert.ok(r.end && !r.end.aborted, `${mode}: ended ${JSON.stringify(r.end)}`);
    assert.ok(r.c.position.z < back - movement.capsule.radius, `${mode}: ended at z ${r.c.position.z}`);
    assert.ok(r.c.grounded && Math.abs(r.c.position.y) < 1e-3 && !r.c.crouched, `${mode}: final state ${r.c.position.toArray()}`);
    // over the wall the feet are above its top (lift), never lower
    const over = r.path.filter((p) => p.z < -3.85 + 0.35 && p.z > back - 0.35);
    assert.ok(over.length > 0 && over.every((p) => p.y >= 1.0 + TP.lift - 1e-6), `${mode}: feet dipped into the wall top`);
    assertClean(r, mode);
    rows.push(`${mode} ${r.start.duration.toFixed(2)} s`);
  }
  console.log(`vault durations: ${rows.join(', ')}`);
});

test('test range 1.0 m low cover (0.6 m deep): vault over it; the window (sill 0.9 m, 1.2 x 1.2 m opening) is large enough for the tucked capsule', () => {
  for (const mode of ['stand', 'run', 'sprint']) {
    const r = attempt(range, mode === 'stand' ? [0, 0, -14.3] : [0, 0, -11], { mode, pressAfter: mode === 'stand' ? 0 : 3.0 });
    assert.ok(r.start && r.start.type === 'vault', `cover ${mode}: ${JSON.stringify(r.start || r.fail)}`);
    assert.ok(r.c.position.z < -15.3 - 0.35 && r.c.grounded, `cover ${mode}: ended at ${r.c.position.toArray()}`);
    assertClean(r, `cover ${mode}`);
  }
  // window: centred, and off-centre within the sideways shift the planner tries (lines the capsule up)
  for (const x of [-10, -9.8, -10.25, -9.62]) {
    const r = attempt(range, [x, 0, -13], { mode: 'run', pressAfter: 2.2 });
    assert.ok(r.start && r.start.type === 'vault', `window x=${x}: ${JSON.stringify(r.start || r.fail)}`);
    assert.ok(Math.abs(r.start.obstacleHeight - 0.9) < 0.01);
    assert.ok(r.c.position.z < -16.125 - 0.35, `window x=${x}: ended at ${r.c.position.toArray()}`);
    // inside the opening the capsule stays clear of the jambs (x -10.6 .. -9.4) and the lintel (2.1 m)
    for (const p of r.path.filter((q) => q.z < -15.875 + 0.36 && q.z > -16.125 - 0.36)) {
      assert.ok(p.x - 0.35 >= -10.6 - 1e-6 && p.x + 0.35 <= -9.4 + 1e-6, `window x=${x}: jamb at ${p.toArray()}`);
      assert.ok(p.y >= 0.9 && p.y + TP.tuckHeight <= 2.1 + 1e-6, `window x=${x}: sill / lintel at ${p.toArray()}`);
    }
    assertClean(r, `window x=${x}`);
  }
  // beside the window (solid wall above 0.9 m... up to 3 m): refused
  const beside = attempt(range, [-11.2, 0, -13], { mode: 'run', pressAfter: 2.2 });
  assert.equal(beside.start, null, 'vaulted through a solid wall');
  assert.ok(beside.c.position.z > -15.875, `passed the wall: ${beside.c.position.toArray()}`);
});

test('test range: mantle onto the deep 1.0 m platform (ends standing on top); the 3 m thin wall and the 2 m slope top are refused', () => {
  for (const mode of ['stand', 'run']) {
    // standing still after the mantle (input released once it has ended)
    const r = attempt(range, mode === 'stand' ? [9, 0, -8.45] : [9, 0, -11], { yaw: Math.PI, mode, pressAfter: mode === 'stand' ? 0 : 2.3, ticks: 150, stopAfterTraversal: true });
    assert.ok(r.start && r.start.type === 'mantle', `platform ${mode}: ${JSON.stringify(r.start || r.fail)}`);
    assert.equal(r.start.endStance, 'stand');
    assert.ok(Math.abs(r.c.position.y - 1.0) < 1e-3 && r.c.grounded && !r.c.crouched, `platform ${mode}: ${r.c.position.toArray()}`);
    assertClean(r, `platform ${mode}`);
  }
  const thin = attempt(range, [21, 0, 0], { mode: 'sprint', pressAfter: 3.2 });
  assert.equal(thin.start, null);
  assert.equal(thin.fail.reason, 'too_high');
  assert.ok(thin.c.position.z > -3.95);
  const slope = attempt(range, [-15, 0, -7.2], { yaw: Math.PI, mode: 'run', pressAfter: 0.1 });
  assert.equal(slope.start, null);
});

// ---------------------------------------------------------------- custom geometry (negative cases)

const wall = (h, thick = 0.3, extra = []) => custom([{ type: 'box', id: 'w', min: [-3, 0, -2 - thick], max: [3, h, -2] }, ...extra]);

test('height limits: 0.5-1.3 m obstacles are crossed; 0.45 m (a jump), 1.4 m, 1.5 m and 2.0 m are not traversals', () => {
  for (const h of [0.55, 0.8, 1.0, 1.2, 1.3]) {
    const r = attempt(wall(h), [0, 0, 0], { mode: 'run', pressAfter: 1.2 });
    assert.ok(r.start, `h=${h}: refused (${JSON.stringify(r.fail)})`);
    assert.ok(r.c.position.z < -2.3 - 0.35, `h=${h}: ended at ${r.c.position.toArray()}`);
    assertClean(r, `h=${h}`);
  }
  for (const h of [0.45, 1.4, 1.5, 2.0]) {
    const r = attempt(wall(h), [0, 0, 0], { mode: 'sprint', pressAfter: 1.0 });
    assert.equal(r.start, null, `h=${h}: traversal started`);
    assert.ok(r.c.position.z > -2 + 0.34, `h=${h}: got past the wall`);
    if (h > 1.3) assert.equal(r.fail.reason, 'too_high', `h=${h}: ${JSON.stringify(r.fail)}`);
  }
});

test('ceiling above the ledge: refused when the tucked capsule does not fit over it, allowed with enough room', () => {
  const slab = (y0) => ({ type: 'box', id: 'slab', min: [-3, y0, -3.5], max: [3, y0 + 0.2, -1.0] });
  for (const y0 of [1.6, 1.9, 2.0]) {
    const r = attempt(wall(1.0, 0.3, [slab(y0)]), [0, 0, 0], { mode: 'run', pressAfter: 1.2 });
    assert.equal(r.start, null, `slab at ${y0}: vaulted (${JSON.stringify(r.start)})`);
    assertClean(r, `slab ${y0}`);
  }
  const ok = attempt(wall(1.0, 0.3, [slab(2.3)]), [0, 0, 0], { mode: 'run', pressAfter: 1.2 });
  assert.ok(ok.start, `slab at 2.3 m: refused (${JSON.stringify(ok.fail)})`);
  assertClean(ok, 'slab 2.3');
});

test('too narrow landing behind a thin wall, landing too far down, and no room on top are refused', () => {
  // a tall wall 0.5 m behind the thin 1.0 m wall: the capsule does not fit between them
  const narrow = attempt(wall(1.0, 0.3, [{ type: 'box', id: 'back', min: [-3, 0, -3.3], max: [3, 3, -2.8] }]), [0, 0, 0], { mode: 'run', pressAfter: 1.2 });
  assert.equal(narrow.start, null, `narrow landing: ${JSON.stringify(narrow.start)}`);
  assertClean(narrow, 'narrow');
  // wide enough (1.0 m gap) -> fine
  const wide = attempt(wall(1.0, 0.3, [{ type: 'box', id: 'back', min: [-3, 0, -4.4], max: [3, 3, -3.3] }]), [0, 0, 0], { mode: 'run', pressAfter: 1.2 });
  assert.ok(wide.start, `1.0 m landing gap refused: ${JSON.stringify(wide.fail)}`);
  assertClean(wide, 'wide');
  // landing 2 m below the take-off: refused (a vault is not a way to jump down a cliff)
  const cliff = new CollisionWorld(
    buildLevelSolids({
      solids: [
        { type: 'box', id: 'hi', min: [-5, -0.5, -2.3], max: [5, 0, 5] },
        { type: 'box', id: 'lo', min: [-5, -2.5, -9], max: [5, -2.0, -2.3] },
        { type: 'box', id: 'parapet', min: [-5, 0, -2.3], max: [5, 1.0, -2.0] },
      ],
    }),
  );
  const drop = attempt(cliff, [0, 0, 0], { mode: 'run', pressAfter: 1.2 });
  assert.equal(drop.start, null, `landing 2 m down: ${JSON.stringify(drop.start)}`);
  assert.equal(drop.fail.reason, 'landing_too_low');
  // deep 1.0 m block with a ceiling 0.9 m above its top: not even the crouched capsule fits -> refused
  const lowTop = custom([
    { type: 'box', id: 'blk', min: [-3, 0, -6], max: [3, 1.0, -2] },
    { type: 'box', id: 'ceil', min: [-3, 1.9, -6], max: [3, 2.1, -2.5] },
  ]);
  const lt = attempt(lowTop, [0, 0, 0], { mode: 'run', pressAfter: 1.2 });
  assert.equal(lt.start, null, `mantle under a 0.9 m gap: ${JSON.stringify(lt.start)}`);
  assertClean(lt, 'low top');
});

test('mantle with 1.3 m headroom on top ends crouched (stands up later only with room)', () => {
  const w = custom([
    { type: 'box', id: 'blk', min: [-3, 0, -8], max: [3, 1.0, -2] },
    { type: 'box', id: 'ceil', min: [-3, 2.3, -8], max: [3, 2.5, -2.6] },
  ]);
  const r = attempt(w, [0, 0, -1.5], { mode: 'stand', pressAfter: 0, ticks: 80 });
  assert.ok(r.start && r.start.type === 'mantle', JSON.stringify(r.start || r.fail));
  assert.equal(r.start.endStance, 'crouch');
  assert.ok(r.c.crouched && r.c.grounded && Math.abs(r.c.position.y - 1.0) < 1e-3, `ended ${r.c.position.toArray()} crouched=${r.c.crouched}`);
  assertClean(r, 'crouch mantle');
});

test('a window too small for the tucked capsule (low or narrow opening) is refused', () => {
  const win = (from, to, bottom, top) => custom([{ type: 'wall', id: 'ww', axis: 'x', from: -4, to: 4, center: -2.125, thickness: 0.25, height: 3.0, openings: [{ from, to, bottom, top }] }]);
  const cases = [
    ['1.0 m tall', win(-0.6, 0.6, 0.9, 1.9)],
    ['0.65 m wide', win(-0.325, 0.325, 0.9, 2.1)],
  ];
  for (const [label, w] of cases) {
    const r = attempt(w, [0, 0, 0], { mode: 'run', pressAfter: 1.1 });
    assert.equal(r.start, null, `${label}: vaulted (${JSON.stringify(r.start)})`);
    assert.ok(r.c.position.z > -2.0, `${label}: passed through`);
    assertClean(r, label);
  }
  const big = attempt(win(-0.6, 0.6, 0.9, 2.1), [0, 0, 0], { mode: 'run', pressAfter: 1.1 });
  assert.ok(big.start, `1.2 x 1.2 m window refused: ${JSON.stringify(big.fail)}`);
  assertClean(big, 'big window');
});

test('crouched under a low roof facing an obstacle: refused (no room to rise); crouched in the open: allowed', () => {
  const w = wall(1.0, 0.3, [{ type: 'box', id: 'roof', min: [-3, 1.4, -1.95], max: [3, 1.6, 2] }]);
  const r = attempt(w, [0, 0, 0], { mode: 'walk', crouch: true, pressAfter: 1.0, setup: (c) => c.update(DT, cmdOf({ crouch: true })) });
  assert.equal(r.start, null, `vaulted from under the roof: ${JSON.stringify(r.start)}`);
  assert.ok(r.c.crouched);
  assertClean(r, 'under roof');
  const open = attempt(wall(1.0), [0, 0, 0], { mode: 'walk', crouch: true, pressAfter: 1.0, setup: (c) => c.update(DT, cmdOf({ crouch: true })) });
  assert.ok(open.start, `crouched vault in the open refused: ${JSON.stringify(open.fail)}`);
  assertClean(open, 'crouched open');
});

test('direction: backing into a wall or facing away / along it never starts a traversal', () => {
  // walking backwards (S) into the wall with jump
  const back = attempt(wall(1.0), [0, 0, -1.0], { yaw: Math.PI, mode: 'stand', pressAfter: 0, setup: null });
  assert.equal(back.start, null, 'vaulted while facing away');
  // facing 70° off the wall normal
  const oblique = attempt(wall(1.0), [0, 0, -1.4], { yaw: 70 * DEG, mode: 'stand', pressAfter: 0 });
  assert.equal(oblique.start, null, 'vaulted along the wall');
  // moving backwards (moveZ < 0) while facing it: no
  const c = new CharacterController(wall(1.0), movement);
  c.teleport(new Vector3(0, 0, -1.5));
  c.update(DT, cmdOf({ moveZ: -1, jump: true }));
  assert.equal(c.stats.traversals, 0);
});

// ---------------------------------------------------------------- behaviour during the move

test('input is locked during the move, events carry the contract payload, jump early -> grab on contact', () => {
  const r = attempt(wall(1.0), [0, 0, 0], { mode: 'run', pressAfter: 1.2, duringCmd: { moveX: 1, moveZ: -1, crouch: true, jump: true, sprint: true } });
  assert.ok(r.start && r.end, 'vault happened');
  const s = r.start;
  for (const k of ['id', 'type', 'ledgePoint', 'ledgeNormal', 'obstacleHeight', 'duration']) assert.ok(s[k] !== undefined, `traverse:start.${k}`);
  assert.ok(Math.abs(s.ledgePoint.z - -2.0) < 0.02 && Math.abs(s.ledgePoint.y - 1.0) < 1e-3, JSON.stringify(s.ledgePoint));
  assert.ok(s.ledgeNormal.z > 0.99, JSON.stringify(s.ledgeNormal));
  assert.equal(r.end.id, s.id);
  // sideways / backwards input during the move had no effect: the path stays on x = 0 and keeps going -z
  for (const p of r.path) assert.ok(Math.abs(p.x) < 1e-9, `drifted sideways during the move: ${p.x}`);
  for (let i = 1; i < r.path.length; i++) assert.ok(r.path[i].z <= r.path[i - 1].z + 1e-9, 'moved backwards during the move');
  const ticksIn = r.path.length;
  assert.ok(Math.abs(ticksIn * DT - s.duration) <= DT + 1e-9, `move lasted ${ticksIn} ticks for ${s.duration} s`);
  // jump pressed 1.2-1.8 m before the wall, forward held: grabs the wall on contact without a second press
  for (const d of [1.2, 1.5, 1.8]) {
    const e = attempt(wall(1.0), [0, 0, 1.5], { mode: 'sprint', pressAfter: 3.5 - 0.35 - d });
    assert.ok(e.start, `early jump ${d} m: ${JSON.stringify(e.fail)}`);
    assert.ok(e.c.position.z < -2.3 - 0.35, `early jump ${d} m: ended at ${e.c.position.toArray()}`);
    assertClean(e, `early ${d}`);
  }
});

test('abort safety: geometry appearing on the path mid-move stops the traversal at a free position', () => {
  const w0 = wall(1.0);
  const w1 = wall(1.0, 0.3, [{ type: 'box', id: 'surprise', min: [-3, 0, -3.2], max: [3, 2.5, -2.75] }]);
  const c = new CharacterController(w0, movement);
  c.teleport(new Vector3(0, 0, -1.4));
  c.update(DT, cmdOf({ jump: true }));
  assert.ok(c.traversing, `no vault: ${JSON.stringify(c.lastTraversalFail)}`);
  run(c, 8, cmdOf({}));
  c.world = w1; // the world changes under the move (e.g. a door closed)
  let aborted = null;
  c.addListener((n, p) => n === 'traverse:end' && (aborted = p.aborted));
  for (let i = 0; i < 90; i++) {
    c.update(DT, cmdOf({}));
    assert.ok(!c.overlaps(c.position, c.height, 0.002), `overlap at tick ${i}: ${c.position.toArray()}`);
  }
  assert.equal(aborted, true);
  assert.equal(c.stats.traversalAborts, 1);
  assert.ok(c.position.z > -2.75 + 0.3, `ended inside / past the new block: ${c.position.toArray()}`);
});

function run(c, n, cmd) {
  for (let i = 0; i < n; i++) c.update(DT, cmd);
}

test('planner: every validated path sample is free and the path is continuous (no step larger than the move allows)', () => {
  const w = wall(1.0);
  const c = new CharacterController(w, movement);
  c.teleport(new Vector3(0, 0, -1.2));
  const res = planTraversal(c, { dirX: 0, dirZ: -1, speed: 0, baseY: 0, params: TP });
  assert.ok(res.ok, JSON.stringify(res));
  const plan = res.plan;
  const p = new Vector3();
  const q = new Vector3();
  plan.positionAt(0, q);
  assert.ok(q.distanceTo(c.position) < 1e-9, 'starts at the feet');
  let maxStep = 0;
  for (let i = 1; i <= 400; i++) {
    plan.positionAt(i / 400, p);
    assert.ok(!c.overlaps(p, TP.tuckHeight, 0.002), `sample ${i} overlaps at ${p.toArray()}`);
    maxStep = Math.max(maxStep, p.distanceTo(q));
    q.copy(p);
  }
  assert.ok(maxStep < 0.02, `path jump ${maxStep}`);
});

// ---------------------------------------------------------------- bots (same controller) and weapon lock

test('bots traverse with the same controller; traverse events reach the bus with the combatant id; no firing during the move', () => {
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
  const s = new MatchSession({ level, world: range, movement, weaponsData, combat, teams, events, createAISystem, seed: 3, bots: [0, 1, 0], mode: 'match' });
  s.start({ skipPreRound: true });
  const bot = s.combatants.all().find((c) => !c.isPlayer);
  bot.controller.teleport(new Vector3(15, 0, -3.3));
  bot.yaw = 0;
  bot.pitch = 0;
  const log = [];
  events.on('traverse:start', (p) => log.push(['start', p]));
  events.on('traverse:end', (p) => log.push(['end', p]));
  const shotsBefore = bot.weapon.state.shotsFired;
  cmds.set(bot.id, { ...IDLE_COMMAND, jump: true, yaw: 0, pitch: 0 });
  s.tick(DT, { playerCmd: null });
  assert.ok(bot.controller.traversing, `bot did not vault: ${JSON.stringify(bot.controller.lastTraversalFail)}`);
  let firedDuring = 0;
  for (let i = 0; i < 70; i++) {
    const was = bot.controller.traversing;
    const n0 = bot.weapon.state.shotsFired;
    cmds.set(bot.id, { ...IDLE_COMMAND, fire: true, yaw: 0, pitch: 0 });
    s.tick(DT, { playerCmd: null });
    if (was && bot.controller.traversing && bot.weapon.state.shotsFired > n0) firedDuring++;
    if (!bot.controller.traversing) break;
  }
  assert.equal(firedDuring, 0, 'fired while vaulting');
  assert.ok(bot.weapon.state.shotsFired >= shotsBefore);
  const st = log.find((e) => e[0] === 'start');
  const en = log.find((e) => e[0] === 'end');
  assert.ok(st && en, JSON.stringify(log));
  assert.equal(st[1].id, bot.id);
  assert.equal(st[1].team, bot.team);
  assert.equal(st[1].type, 'vault');
  assert.ok(typeof st[1].ledgePoint.distanceTo === 'function' && st[1].duration > 0);
  assert.equal(en[1].id, bot.id);
  assert.ok(bot.position.z < -4.15 - 0.3, `bot ended at ${bot.position.toArray()}`);
});
