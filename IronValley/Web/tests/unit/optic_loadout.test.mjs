// Optic loadout rules (Node): kit, backpack swap timing and phases, interruptions, no fire / ADS / reload during a
// swap, the ADS pose following the mounted optic, respawn back to the kit, bots' role kits and the armory crate.
import test from 'node:test';
import assert from 'node:assert/strict';
import { Vector3 } from 'three';
import movement from '../../src/data/movement.json' with { type: 'json' };
import weaponsData from '../../src/data/weapons.json' with { type: 'json' };
import combat from '../../src/data/combat.json' with { type: 'json' };
import teams from '../../src/data/teams.json' with { type: 'json' };
import attachments from '../../src/data/attachments.json' with { type: 'json' };
import { EventBus } from '../../src/engine/events.js';
import { buildLevelSolids } from '../../src/level/levelGeometry.js';
import { CollisionWorld } from '../../src/physics/collisionWorld.js';
import { MatchSession } from '../../src/game/session.js';
import { IDLE_COMMAND } from '../../src/game/combatant.js';
import { OpticLoadout } from '../../src/game/opticLoadout.js';
import { loadLevelData } from '../../src/game/levels.js';
import { getOpticDef, opticViewModel, IRONS } from '../../src/weapons/optics.js';
import { viewModelPointInCamera } from '../../src/weapons/viewModelMotion.js';

const DT = 1 / 60;
const SWAP_TICKS = Math.round(attachments.swap.durationS / DT);

test('OpticLoadout: default kit, setKit validation, the spare never equals the primary', () => {
  const L = new OpticLoadout();
  assert.equal(L.mounted, attachments.loadoutDefault.optic);
  assert.equal(L.spare, attachments.loadoutDefault.spare);
  assert.equal(L.setKit({ optic: 'IVS6', spare: 'IVS6' }).reason, 'spare_equals_primary');
  const r = L.setKit({ optic: 'IVS6', spare: 'IVH1' }, 'armory');
  assert.ok(r.ok);
  assert.deepEqual([L.mounted, L.spare], ['IVS6', 'IVH1']);
  assert.deepEqual(r.events.map((e) => e.type), ['optic:changed']);
  assert.equal(r.events[0].source, 'armory');
});

test('swap: commits exactly after durationS (not a tick earlier), phases in order at the data fractions', () => {
  const L = new OpticLoadout({ kit: { optic: 'IVR1', spare: 'IVS3' } });
  const start = L.startSwap({ alive: true, activeSlot: 0 });
  assert.ok(start.ok);
  assert.ok(L.busy);
  const events = [...start.events];
  for (let i = 0; i < SWAP_TICKS - 1; i++) events.push(...L.tick(DT, { alive: true }));
  assert.equal(L.mounted, 'IVR1', 'still the old optic one tick before the end');
  assert.ok(L.swapping);
  events.push(...L.tick(DT, { alive: true }));
  assert.deepEqual([L.mounted, L.spare, L.busy], ['IVS3', 'IVR1', false]);
  const phases = events.filter((e) => e.type === 'optic:swap_phase').map((e) => e.phase);
  assert.deepEqual(phases, ['lower', 'detach', 'stow', 'attach', 'raise']);
  const P = attachments.swap.phases;
  for (const e of events.filter((x) => x.type === 'optic:swap_phase')) assert.ok(Math.abs(e.t - P[e.phase] * attachments.swap.durationS) < 1e-9);
  assert.deepEqual(events.slice(-2).map((e) => e.type), ['optic:swap_finished', 'optic:changed']);
});

test('swap: visual optic follows the phases (old -> empty rail -> new), for the arms animation hook', () => {
  const L = new OpticLoadout({ kit: { optic: 'IVH1', spare: 'IVS6' } });
  L.startSwap({ alive: true, activeSlot: 0 });
  const seen = [];
  for (let i = 0; i < SWAP_TICKS; i++) {
    const v = L.visualOptic;
    if (seen[seen.length - 1] !== v) seen.push(v);
    L.tick(DT, { alive: true });
  }
  assert.deepEqual(seen, ['IVH1', null, 'IVS6']);
});

test('swap: interruptions (key again, sprint, weapon switch, vault, death) keep the old optic; raise lock afterwards', () => {
  for (const [ctx, reason] of [
    [{ swapPressed: true }, 'swapKey'],
    [{ sprinting: true }, 'sprint'],
    [{ switchRequested: true }, 'switch'],
    [{ handsBusy: true }, 'traverse'],
    [{ alive: false }, 'death'],
  ]) {
    const L = new OpticLoadout({ kit: { optic: 'IVR1', spare: 'IVS6' } });
    L.startSwap({ alive: true, activeSlot: 0 });
    for (let i = 0; i < 60; i++) L.tick(DT, { alive: true });
    const ev = L.tick(DT, { alive: true, ...ctx });
    assert.equal(ev[0].type, 'optic:swap_interrupted', reason);
    assert.equal(ev[0].reason, reason);
    assert.deepEqual([L.mounted, L.spare, L.swapping], ['IVR1', 'IVS6', false], reason);
    if (reason === 'death') assert.equal(L.busy, false);
    else {
      assert.ok(L.busy, `${reason}: weapon still raising`);
      const n = Math.ceil(attachments.swap.interruptRaiseS / DT);
      for (let i = 0; i < n + 1; i++) L.tick(DT, { alive: true });
      assert.equal(L.busy, false);
    }
  }
  // damage does not interrupt by default (data), but can
  const L = new OpticLoadout({ kit: { optic: 'IVR1', spare: 'IVS6' } });
  L.startSwap({ alive: true, activeSlot: 0 });
  assert.equal(L.tick(DT, { alive: true, damaged: true }).length, 0);
  const L2 = new OpticLoadout({ kit: { optic: 'IVR1', spare: 'IVS6' }, rules: { interruptOn: { damage: true } } });
  L2.startSwap({ alive: true, activeSlot: 0 });
  assert.equal(L2.tick(DT, { alive: true, damaged: true })[0].reason, 'damage');
});

test('swap: refused while sprinting, reloading, switching, with the pistol drawn, or with nothing to swap; irons <-> optic', () => {
  const L = new OpticLoadout({ kit: { optic: 'irons', spare: 'IVS3' } });
  for (const [ctx, why] of [
    [{ sprinting: true }, 'sprinting'],
    [{ reloading: true }, 'reloading'],
    [{ switching: true }, 'switching'],
    [{ activeSlot: 1 }, 'primary_not_active'],
    [{ handsBusy: true }, 'hands_busy'],
    [{ alive: false }, 'dead'],
  ]) {
    const r = L.startSwap({ alive: true, activeSlot: 0, ...ctx });
    assert.deepEqual([r.ok, r.reason], [false, why]);
  }
  // irons + spare scope -> scope on the rail, empty backpack -> back to irons
  L.startSwap({ alive: true, activeSlot: 0 });
  for (let i = 0; i < SWAP_TICKS; i++) L.tick(DT, { alive: true });
  assert.deepEqual([L.mounted, L.spare], ['IVS3', null]);
  L.startSwap({ alive: true, activeSlot: 0 });
  for (let i = 0; i < SWAP_TICKS; i++) L.tick(DT, { alive: true });
  assert.deepEqual([L.mounted, L.spare], [IRONS, 'IVS3']);
  const empty = new OpticLoadout({ kit: { optic: 'irons', spare: null } });
  assert.equal(empty.startSwap({ alive: true, activeSlot: 0 }).reason, 'nothing_to_swap');
});

// ------------------------------------------------------------------ in a match session (combatant integration)

const level = await loadLevelData('test_range');
const world = new CollisionWorld(buildLevelSolids(level));

function scriptedAI() {
  let bots = [];
  return () => ({
    addBot: (c) => bots.push(c),
    removeBot: (id) => (bots = bots.filter((b) => b.id !== id)),
    update: (dt) => {
      for (const b of bots) if (b.alive) b.applyCommand({ ...IDLE_COMMAND, yaw: b.yaw, pitch: b.pitch }, dt);
    },
    getDebug: () => ({}),
    reset: () => {},
  });
}

function makeSession(loadout = { optic: 'IVR1', spare: 'IVS6' }, bots = [2, 5, 0]) {
  const events = new EventBus();
  const log = [];
  for (const t of ['optic:swap_started', 'optic:swap_phase', 'optic:swap_finished', 'optic:swap_interrupted', 'optic:swap_rejected', 'optic:changed']) events.on(t, (p) => log.push({ t, ...p }));
  const s = new MatchSession({ level, world, movement, weaponsData, combat, teams, events, createAISystem: scriptedAI(), seed: 5, bots, mode: 'match', loadout });
  s.start({ skipPreRound: true });
  return { s, log };
}
const tick = (s, cmd, n = 1) => {
  for (let i = 0; i < n; i++) s.tick(DT, { playerCmd: { ...IDLE_COMMAND, yaw: s.player.yaw, pitch: s.player.pitch, ...cmd } });
};

test('in a match: during the backpack swap the rifle does not fire, aim or reload; the ADS pose then follows the new optic', () => {
  const { s, log } = makeSession();
  const pc = s.player;
  const w = pc.weapons[0];
  tick(s, {}, 30);
  assert.equal(pc.optic, 'IVR1');
  tick(s, { swapOptic: true });
  assert.ok(pc.opticLoadout.swapping);
  const fired0 = w.state.shotsFired;
  const mag0 = w.state.magazine;
  // hold fire + ADS + press reload through most of the swap
  tick(s, { fire: true, ads: true }, 60);
  tick(s, { fire: true, ads: true, reload: true }, 1);
  tick(s, { fire: true, ads: true }, SWAP_TICKS - 70);
  assert.equal(w.state.shotsFired, fired0, 'no round fired during the swap');
  assert.equal(w.state.magazine, mag0);
  assert.equal(w.state.ads, 0, 'no ADS during the swap');
  assert.equal(w.state.state, 'ready', 'no reload started');
  assert.ok(w.state.core.disabledBy.includes('other'));
  tick(s, { fire: false }, 12);
  assert.equal(pc.optic, 'IVS6');
  assert.equal(pc.spareOptic, 'IVR1');
  assert.ok(!w.state.core.disabledBy.includes('other'));
  // ADS pose, muzzle and ADS time of the 6x
  const d = getOpticDef('IVS6');
  const vm = opticViewModel(weaponsData.iv7_carbine.viewModel, d);
  assert.ok(w.muzzleOffset(1).distanceTo(viewModelPointInCamera(vm, vm.muzzleLocal, 1)) < 1e-9);
  assert.equal(w.state.adsTime, d.adsTime);
  // it fires again (a new press) and aims
  const f1 = w.state.shotsFired;
  tick(s, { fire: true, ads: true }, 3);
  assert.ok(w.state.shotsFired > f1);
  tick(s, { ads: true }, 40);
  assert.equal(w.state.ads, 1);
  const types = log.filter((e) => e.id === 'player').map((e) => e.t);
  assert.ok(types.includes('optic:swap_started') && types.includes('optic:swap_finished'));
});

test('in a match: sprint interrupts the swap (old optic stays), respawn restores the kit, rejected swap is reported', () => {
  const { s, log } = makeSession({ optic: 'IVH1', spare: 'IVP2' });
  const pc = s.player;
  tick(s, {}, 20);
  tick(s, { swapOptic: true });
  tick(s, {}, 40);
  tick(s, { moveZ: 1, sprint: true }, 30);
  assert.equal(pc.optic, 'IVH1');
  assert.ok(log.some((e) => e.t === 'optic:swap_interrupted' && e.reason === 'sprint'));
  // complete a swap, die, respawn: back to the kit (IVH1 on the rail, IVP2 in the backpack)
  tick(s, {}, 30);
  tick(s, { swapOptic: true });
  tick(s, {}, SWAP_TICKS + 2);
  assert.equal(pc.optic, 'IVP2');
  s.forceKill('player');
  tick(s, {}, 60 * 8);
  assert.ok(pc.alive, 'respawned');
  assert.deepEqual([pc.optic, pc.spareOptic], ['IVH1', 'IVP2']);
  // pistol drawn: swap refused
  tick(s, { switchTo: 1 }, 40);
  tick(s, { swapOptic: true });
  assert.ok(log.some((e) => e.t === 'optic:swap_rejected' && e.reason === 'primary_not_active'));
});

test('in a match: bots carry their role kit (ADS pose of their optic), the armory crate works only for its team, in reach, alive', () => {
  const { s } = makeSession({ optic: 'IVR1', spare: null }, [2, 5, 0]);
  const bots = s.combatants.byTeam(1);
  assert.equal(bots.length, 5);
  for (const b of bots) {
    assert.ok(b.opticRole, b.id);
    const d = getOpticDef(b.optic);
    const vm = opticViewModel(weaponsData.iv7_carbine.viewModel, d);
    assert.ok(b.weapons[0].muzzleOffset(1).distanceTo(viewModelPointInCamera(vm, vm.muzzleLocal, 1)) < 1e-9, b.id);
  }
  assert.ok(bots.some((b) => b.optic === 'IVS6'), 'a marksman with the 6x');
  const pc = s.player;
  const own = s.armories.find((a) => a.team === pc.team);
  const enemy = s.armories.find((a) => a.team !== pc.team);
  // at the own crate
  pc.controller.teleport(new Vector3(own.center[0] - 1.1, 0, own.center[2]));
  assert.equal(s.armoryFor(pc).id, own.id);
  assert.deepEqual(s.useArmory(pc, { optic: 'IVS3', spare: 'IVH1' }), { ok: true, reason: null });
  assert.deepEqual([pc.optic, pc.spareOptic], ['IVS3', 'IVH1']);
  assert.equal(s.useArmory(pc, { optic: 'IVS3', spare: 'IVS3' }).reason, 'spare_equals_primary');
  // out of reach
  pc.controller.teleport(new Vector3(own.center[0] - 3.5, 0, own.center[2]));
  assert.equal(s.armoryFor(pc), null);
  assert.equal(s.useArmory(pc, { optic: 'IVP2' }).reason, 'not_at_armory');
  // the enemy crate
  pc.controller.teleport(new Vector3(enemy.center[0] + (enemy.center[0] > 0 ? -1.1 : 1.1), 0, enemy.center[2]));
  assert.equal(s.armoryFor(pc), null);
  // dead
  pc.controller.teleport(new Vector3(own.center[0] - 1.1, 0, own.center[2]));
  s.forceKill('player');
  assert.equal(s.useArmory(pc, { optic: 'IVP2' }).reason, 'dead');
});
