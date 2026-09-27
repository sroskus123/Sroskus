// Gameplay integration logic in Node (no browser): level loading, combatants through Match, hit zones,
// friendly fire, death / life lock (GUN-03), respawn (GAME-02), engine spawn safety, full round with
// results and reset, weapon switching and reload interruptions (GUN-01), AI contract integration.
// Bots are driven by a scripted test AI (same applyCommand path as the real AI), so every case is exact.
import test from 'node:test';
import assert from 'node:assert/strict';
import { Vector3 } from 'three';
import movement from '../../src/data/movement.json' with { type: 'json' };
import weaponsData from '../../src/data/weapons.json' with { type: 'json' };
import combat from '../../src/data/combat.json' with { type: 'json' };
import teams from '../../src/data/teams.json' with { type: 'json' };
import { EventBus } from '../../src/engine/events.js';
import { buildLevelSolids } from '../../src/level/levelGeometry.js';
import { CollisionWorld } from '../../src/physics/collisionWorld.js';
import { MatchSession } from '../../src/game/session.js';
import { IDLE_COMMAND } from '../../src/game/combatant.js';
import { loadLevelData, validateLevel, listAvailableLevels } from '../../src/game/levels.js';
import { weaponInvariantViolations } from '../../src/core/weapon.js';
import { createAISystem as realAI } from '../../src/ai/index.js';
import { BindingsStore, isBindableCode } from '../../src/player/bindingsStore.js';
import { sanitizeSettings } from '../../src/player/settings.js';
import { formatClock } from '../../src/game/hud.js';
import defaultBindings from '../../src/data/input_bindings.json' with { type: 'json' };

const DT = 1 / 60;
const level = await loadLevelData('test_range');
const world = new CollisionWorld(buildLevelSolids(level));

/** Test AI: drives each bot with a scripted command (or idle) through applyCommand, once per tick. */
function scriptedAI() {
  const cmds = new Map();
  let bots = [];
  const factory = () => ({
    addBot: (c) => bots.push(c),
    removeBot: (id) => (bots = bots.filter((b) => b.id !== id)),
    update: (dt) => {
      for (const b of bots) if (b.alive) b.applyCommand(cmds.get(b.id) || { ...IDLE_COMMAND, yaw: b.yaw, pitch: b.pitch }, dt);
    },
    getDebug: () => ({ scripted: true }),
    reset: () => cmds.clear(),
  });
  return { factory, cmds };
}

function makeSession(o = {}) {
  const events = new EventBus();
  const ai = scriptedAI();
  const log = [];
  for (const t of ['combatant:spawned', 'combatant:died', 'combatant:damaged', 'combatant:friendly_fire_blocked', 'round:started', 'round:ended', 'round:reset', 'zone:control_changed', 'weapon:reload_started', 'weapon:reload_interrupted', 'weapon:reload_finished']) {
    events.on(t, (p) => log.push({ t, p }));
  }
  const s = new MatchSession({ level, world, movement, weaponsData, combat, teams, events, createAISystem: o.createAISystem || ai.factory, seed: o.seed ?? 11, bots: o.bots ?? [1, 1, 1], mode: o.mode || 'match', rulesPatch: o.rulesPatch || null });
  s.start({ skipPreRound: o.skipPreRound ?? true });
  return { s, events, cmds: ai.cmds, log };
}

const place = (c, x, y, z, yawDeg = 0) => {
  c.controller.teleport(new Vector3(x, y, z));
  c.yaw = (yawDeg * Math.PI) / 180;
  c.pitch = 0;
};
function aimAngles(c, target) {
  const eye = c.getEye(new Vector3());
  const d = target.clone().sub(eye);
  return { yaw: Math.atan2(-d.x, -d.z), pitch: Math.atan2(d.y, Math.hypot(d.x, d.z)) };
}
const tick = (s, cmd = null, n = 1) => {
  for (let i = 0; i < n; i++) s.tick(DT, { playerCmd: cmd ? { ...cmd } : null });
};
/** Player fires exactly one round at `target` (world point), after the recoil has settled. */
function playerShoot(s, target) {
  const a = aimAngles(s.player, target);
  tick(s, { ...IDLE_COMMAND, ...a }, 45);
  const w = s.player.weapon;
  const before = w.state.shotsFired;
  tick(s, { ...IDLE_COMMAND, ...a, fire: true }, 1);
  tick(s, { ...IDLE_COMMAND, ...a }, 1);
  return { fired: w.state.shotsFired - before, shot: w.lastShot };
}
const assertInvariant = (c) => {
  for (const w of c.weapons) assert.deepEqual(weaponInvariantViolations(w.state.core.snapshot(), w.rulesDef), []);
};

// ------------------------------------------------------------------ levels

test('levels load by id from src/data/<id>.json; missing or invalid ids reject', async () => {
  assert.equal(level.id, 'test_range');
  assert.equal(level.match.teamSpawns.length, 3);
  assert.equal(level.match.zones.length, 3);
  await assert.rejects(loadLevelData('does_not_exist'), /není|not/);
  await assert.rejects(loadLevelData('../package'), /Neplatné/);
  await assert.rejects(loadLevelData('weapons'), /neplatná/); // a data file that is not a level
  assert.ok(validateLevel({ id: 'x', solids: [], markers: {} }, 'x').length > 0);
  assert.ok(validateLevel({ id: 'x', solids: [{}], markers: {}, match: { teamSpawns: [[]], zones: [{ id: 'a', center: [0, 0], radius: 0 }] } }, 'x').length >= 3);
  const avail = await listAvailableLevels();
  assert.ok(avail.some((l) => l.id === 'test_range' && l.hasMatch));
});

test('spawn shelters are in their own collision BVH group (base level collision unchanged)', () => {
  // groups: base level, spawn shelters, armory crates at the spawns (added with the optics, own group as well)
  assert.equal(world.parts.length, 3);
  assert.equal(world.parts[1].name, 'spawns');
  assert.equal(world.parts[2].name, 'armory');
  assert.ok(world.parts[1].triangleCount > 0);
  assert.equal(world.parts[2].triangleCount, 3 * 12, 'three crates (12 triangles each)');
  // a ray into a shelter wall is still blocked (queries combine the groups)
  const hit = world.raycast(new Vector3(20, 1.5, 24), new Vector3(1, 0, 0), 20);
  assert.ok(hit && hit.solidId === 'spawn_alfa_w', JSON.stringify(hit && hit.solidId));
});

// ------------------------------------------------------------------ roster

test('roster: player + bots through Match.addParticipant, 3-bot and 17-bot runs, team size cap', () => {
  const a = makeSession({ bots: [0, 1, 2] });
  assert.equal(a.s.combatants.all().length, 4);
  assert.deepEqual(a.s.botCounts, [0, 1, 2]);
  const b = makeSession({ bots: [5, 6, 6] });
  assert.equal(b.s.combatants.all().length, 18);
  assert.equal(b.s.combatants.alive().length, 18, 'everybody spawned at start');
  for (let t = 0; t < 3; t++) assert.equal(b.s.combatants.byTeam(t).length, 6);
  const c = makeSession({ bots: [9, 9, 9] });
  assert.deepEqual(c.s.botCounts, [5, 6, 6], 'capped at teams.size (6) incl. the player');
  for (const x of b.s.combatants.all()) {
    assert.equal(x.health, 100);
    assert.equal(x.weapons.length, 2);
    assert.equal(x.weapons[0].state.core, b.s.match.respawn.weapon(x.id, 'rifle_iv7'), 'weapon state is the Match-owned core object');
  }
});

// ------------------------------------------------------------------ damage

test('hit zones: head / torso / arm / leg multipliers from data, damage and death through Match', () => {
  const { s, log } = makeSession({ bots: [0, 1, 0] });
  const enemy = s.combatants.get('bot_1_0');
  const zones = combat.hitZones;
  const dmg = (part) => Math.max(1, Math.round(34 * zones[part]));
  const cases = [
    ['head', (sh) => sh[0].center.clone()],
    ['torso', (sh) => sh[1].center.clone().add(new Vector3(0, 0.05, 0))],
    ['arm', (sh) => sh[2].a.clone().lerp(sh[2].b, 0.8)],
    ['leg', (sh) => sh[4].a.clone().lerp(sh[4].b, 0.5)],
  ];
  for (const [part, pick] of cases) {
    s.match.respawn.participant(enemy.id).health = 100; // test reset of the authoritative value
    place(s.player, 0, 0, 6, 0);
    place(enemy, 0, 0, -6, 180);
    tick(s, null, 2);
    const target = pick(enemy.hitShapes());
    const r = playerShoot(s, target);
    assert.equal(r.fired, 1);
    assert.equal(r.shot.hitKind, 'combatant', `${part}: ${JSON.stringify(r.shot)}`);
    assert.equal(r.shot.hitPart, part, `${part}: hit ${r.shot.hitPart}`);
    assert.equal(enemy.health, 100 - dmg(part), `${part} damage`);
  }
  const d = log.filter((e) => e.t === 'combatant:damaged');
  assert.equal(d.length, 4);
  assert.ok(d.every((e) => e.p.attackerId === 'player' && e.p.victimId === 'bot_1_0' && e.p.fromDir));
  // two head shots kill (68 + 68 > 100): death via Match, kill feed, life lock
  s.match.respawn.participant(enemy.id).health = 100;
  playerShoot(s, enemy.hitShapes()[0].center.clone());
  playerShoot(s, enemy.hitShapes()[0].center.clone());
  assert.equal(enemy.alive, false);
  assert.equal(s.match.respawn.participant(enemy.id).state, 'dead');
  assert.ok(log.some((e) => e.t === 'combatant:died' && e.p.victimId === enemy.id && e.p.attackerId === 'player'));
  assert.equal(s.killFeed.at(-1).victimId, enemy.id);
  assert.equal(s.player.kills, 1);
  assert.ok(enemy.weapons.every((w) => w.state.core.disabledBy.includes('life')));
  assert.ok(enemy.deathPose && enemy.deathPose.mode);
  assertInvariant(s.player);
});

test('friendly fire is OFF (rules.json combat.friendlyFire): allies take no damage, enemies do', () => {
  const { s, log } = makeSession({ bots: [1, 1, 0] });
  const ally = s.combatants.get('bot_0_0');
  const enemy = s.combatants.get('bot_1_0');
  assert.equal(s.rules.combat.friendlyFire, false);
  place(s.player, 0, 0, 6, 0);
  place(ally, 0, 0, -4, 180);
  place(enemy, 6, 0, 0, 225);
  tick(s, null, 2);
  const r = playerShoot(s, ally.hitShapes()[1].center.clone());
  assert.equal(r.shot.hitTarget, 'combatant:bot_0_0');
  assert.equal(ally.health, 100);
  assert.equal(s.stats.ffBlocked, 1);
  assert.ok(log.some((e) => e.t === 'combatant:friendly_fire_blocked'));
  assert.equal(log.filter((e) => e.t === 'combatant:damaged').length, 0);
  const r2 = playerShoot(s, enemy.hitShapes()[1].center.clone());
  assert.equal(r2.shot.hitTarget, 'combatant:bot_1_0');
  assert.equal(enemy.health, 66);
});

// ------------------------------------------------------------------ GUN-03

test('GUN-03: dead combatants cannot fire or reload; a trigger held through death / respawn needs a new press; menu lock', () => {
  const { s } = makeSession({ bots: [0, 0, 0] });
  const p = s.player;
  const w = p.weapon;
  const hold = { ...IDLE_COMMAND, yaw: p.yaw, pitch: 0.3, fire: true };
  tick(s, hold, 20);
  assert.ok(w.state.shotsFired > 0, 'fires while alive');
  assert.equal(s.forceKill('player'), 'killed');
  const shots = w.state.shotsFired;
  tick(s, { ...hold, reload: true }, 120);
  assert.equal(w.state.shotsFired, shots, 'no shots while dead');
  assert.equal(w.state.core.reload(), 'rejected_disabled');
  assert.ok(w.state.core.disabledBy.includes('life'));
  // respawn after rules.respawn.delay (5 s) with the trigger still held -> no shot
  tick(s, hold, 300);
  assert.equal(p.alive, true);
  assert.equal(p.participant.spawnCount, 2);
  tick(s, hold, 30);
  assert.equal(w.state.shotsFired, shots, 'held trigger through respawn must not fire');
  tick(s, { ...hold, fire: false }, 1);
  tick(s, hold, 1);
  assert.equal(w.state.shotsFired, shots + 1, 'a new press fires after respawn');
  // menu lock: nothing fires while the menu is open; after closing a new press is needed
  s.setMenuLock(true);
  assert.ok(w.state.core.disabledBy.includes('menu'));
  const s2 = w.state.shotsFired;
  tick(s, hold, 30);
  assert.equal(w.state.shotsFired, s2, 'no shots with the menu lock');
  s.setMenuLock(false);
  tick(s, hold, 10);
  assert.equal(w.state.shotsFired, s2, 'trigger held through the menu does not fire');
  tick(s, { ...hold, fire: false }, 1);
  tick(s, hold, 1);
  assert.equal(w.state.shotsFired, s2 + 1);
  assertInvariant(p);
});

test('GUN-03: menu opened mid-burst (simulation frozen behind it): a quick 3-tick click after "Pokračovat" fires at once', () => {
  // The game does not tick behind the pause menu. Before the fix the fire interval of the last round stayed
  // frozen mid-way, so a click shorter than the leftover (up to 80 ms) was swallowed - the e2e Esc test failed
  // whenever the burst was stopped right after a round (leftover 66.7 ms > 50 ms click).
  for (const burstTicks of [5, 6, 7, 8, 9, 10, 20, 21]) {
    const { s } = makeSession({ bots: [0, 0, 0] });
    const p = s.player;
    const w = p.weapon;
    const hold = { ...IDLE_COMMAND, yaw: p.yaw, pitch: 0.3, fire: true };
    tick(s, hold, burstTicks);
    const cooldownAtPause = w.state.core.cooldownUs;
    s.setMenuLock(true); // Esc: no simulation ticks while the menu is open
    s.setMenuLock(false); // "Pokračovat"
    const before = w.state.shotsFired;
    tick(s, hold, 3);
    tick(s, { ...hold, fire: false }, 1);
    assert.equal(w.state.shotsFired - before, 1, `burst ${burstTicks} ticks (fire interval left ${cooldownAtPause} us): a new click after the menu fires`);
    // (a button kept down through the menu is forgotten by the InputManager - e2e 04 checks it with real input)
    assertInvariant(p);
  }
});

// ------------------------------------------------------------------ GAME-02

test('GAME-02: the player dies 3 times (2 forced, 1 shot by an enemy) and each respawn restores health, loadout, reload state, safe spawn', () => {
  const { s, cmds } = makeSession({ bots: [0, 1, 0] });
  const p = s.player;
  const enemy = s.combatants.get('bot_1_0');
  const checkRespawn = (n) => {
    tick(s, null, 1);
    let guard = 0;
    while (!p.alive && guard++ < 60 * 30) tick(s, null, 1);
    assert.equal(p.alive, true, `respawn ${n}`);
    assert.equal(p.health, 100);
    assert.equal(p.participant.spawnCount, n + 1);
    const [r, pi] = p.weapons.map((w) => w.state);
    assert.deepEqual([r.magazine, r.chamber, r.reserve, r.state], [30, 1, 90, 'ready']);
    assert.deepEqual([pi.magazine, pi.chamber, pi.reserve, pi.state], [15, 1, 45, 'ready']);
    assert.equal(p.activeWeapon, 0);
    assert.ok(p.weapons[0].state.core.enabled, 'rifle unlocked');
    assert.ok(p.weapons[1].state.core.disabledBy.includes('switch') && !p.weapons[1].state.core.disabledBy.includes('life'));
    const rec = s.combatants.spawnHistory.filter((h) => h.id === 'player').at(-1);
    assert.equal(rec.spawnCount, n + 1);
    assert.ok(rec.safeAtSpawn && !rec.insideGeometry && rec.visibleToEnemy === null && rec.nearestEnemy >= 20, JSON.stringify(rec));
    const sp = level.match.teamSpawns[0][rec.point].pos;
    assert.deepEqual(p.position.toArray().map((v) => Math.round(v * 100) / 100), sp);
    // controls work: moving forward changes the position
    const z0 = p.position.clone();
    tick(s, { ...IDLE_COMMAND, yaw: p.yaw, moveZ: 1 }, 30);
    assert.ok(p.position.distanceTo(z0) > 0.5, 'moves after respawn');
    assertInvariant(p);
  };
  // death 1: forced, in the middle of a reload
  tick(s, { ...IDLE_COMMAND, yaw: 0, pitch: 0.4, fire: true }, 30);
  tick(s, { ...IDLE_COMMAND, yaw: 0, reload: true }, 1);
  assert.equal(p.weapon.state.state, 'reloading');
  s.forceKill('player');
  checkRespawn(1);
  // death 2: shot dead by the enemy bot (scripted fire through the same weapon code path)
  place(p, 0, 0, 6, 0);
  place(enemy, 0, 0, -8, 180);
  tick(s, null, 2);
  let guard = 0;
  while (p.alive && guard++ < 600) {
    const a = aimAngles(enemy, p.hitShapes()[0].center.clone());
    cmds.set(enemy.id, { ...IDLE_COMMAND, ...a, fire: guard % 20 < 10 });
    tick(s, { ...IDLE_COMMAND, yaw: 0 }, 1);
  }
  cmds.clear();
  assert.equal(p.alive, false, 'killed by the enemy');
  const death = s.combatants.deathLog.at(-1);
  assert.equal(death.victimId, 'player');
  assert.equal(death.attackerId, enemy.id);
  place(enemy, 0, 0, -8, 180); // stays far from the shelter
  checkRespawn(2);
  // death 3: forced
  s.forceKill('player');
  checkRespawn(3);
  assert.equal(p.participant.deaths, 3);
});

// ------------------------------------------------------------------ spawn safety

test('spawn safety: scripted enemies block unsafe points (distance, line of sight, geometry, bodies); spawn waits instead', () => {
  const { s } = makeSession({ bots: [1, 2, 0] });
  const e1 = s.combatants.get('bot_1_0');
  const e2 = s.combatants.get('bot_1_1');
  const mate = s.combatants.get('bot_0_0');
  // evaluate single points in the open range
  place(e1, 0, 0, -30, 0);
  place(e2, 0, 0, -39.5, 0); // behind the 4 m backstop
  place(mate, 30, 0, 0, 0);
  tick(s, null, 1);
  const open = s.combatants.evaluateSpawnPoint([0, 0, 0], 0);
  assert.equal(open.safe, false);
  assert.ok(open.reasons.includes('visible_to_enemy'), JSON.stringify(open));
  assert.equal(open.visibleTo, e1.id);
  s.forceKill(e1.id);
  const behind = s.combatants.evaluateSpawnPoint([0, 0, 0], 0);
  assert.equal(behind.safe, true, `enemy behind the backstop sees nothing: ${JSON.stringify(behind)}`);
  assert.ok(s.combatants.evaluateSpawnPoint([0, 0, -20], 0).reasons.includes('enemy_too_close'));
  assert.ok(s.combatants.evaluateSpawnPoint([0, 0, -15], 0).reasons.includes('inside_geometry'), 'inside the 1 m cover block');
  assert.ok(s.combatants.evaluateSpawnPoint([120, 0, 0], 0).reasons.includes('no_ground'));
  assert.ok(s.combatants.evaluateSpawnPoint([30, 0, 1.2], 0).reasons.includes('body_too_close'), 'teammate within 1.5 m');
  // an enemy inside the Alfa shelter blocks every Alfa point: the player waits (no unsafe spawn)
  tick(s, null, 400); // e1 respawns meanwhile (Bravo shelter)
  place(e2, 34.5, 0, 26, 0);
  s.forceKill('player');
  tick(s, null, 60 * 8);
  assert.equal(s.player.alive, false, 'no spawn while every point is unsafe');
  assert.equal(s.player.lifeState, 'respawning');
  assert.ok(s.combatants.spawnBlocked > 0);
  // enemy leaves -> spawn at the next retry, at a safe point
  place(e2, -34.5, 0, -36, 0);
  tick(s, null, 40);
  assert.equal(s.player.alive, true);
  const rec = s.combatants.spawnHistory.filter((h) => h.id === 'player').at(-1);
  assert.ok(rec.safeAtSpawn && rec.nearestEnemy >= 25 && rec.visibleToEnemy === null, JSON.stringify(rec));
  // every spawn so far happened on a safe point
  for (const h of s.combatants.spawnHistory) assert.ok(h.safeAtSpawn && !h.insideGeometry, JSON.stringify(h));
});

// ------------------------------------------------------------------ full round

test('full round: score target ends the round (results lock), resetRound starts a clean new round; time limit gives a draw', () => {
  const { s, log } = makeSession({ bots: [0, 0, 0], seed: 5 });
  const z = s.activeZone();
  assert.ok(z && ['zone_dilna', 'zone_sklad', 'zone_dvur'].includes(z.id));
  place(s.player, z.center[0], 0, z.center[2], 0);
  let guard = 0;
  while (s.match.round.state !== 'ended' && guard++ < 60 * 250) tick(s, null, 1);
  const r = s.roundInfo();
  assert.equal(r.state, 'ended');
  assert.equal(r.endReason, 'score_target');
  assert.equal(r.winner, 0);
  assert.deepEqual(r.scores, [100, 0, 0]);
  assert.equal(r.elapsedS, 200, '100 points x 2 s');
  assert.ok(log.some((e) => e.t === 'round:ended' && e.p.winner === 0));
  assert.ok(s.player.weapon.state.core.disabledBy.includes('results'), 'results lock');
  const shots = s.player.weapon.state.shotsFired;
  tick(s, { ...IDLE_COMMAND, fire: true }, 10);
  assert.equal(s.player.weapon.state.shotsFired, shots, 'nobody fires on the results screen');
  // new round
  const zone1 = z.id;
  s.resetRound();
  const r2 = s.roundInfo();
  assert.equal(r2.state, 'pre_round');
  assert.deepEqual(r2.scores, [0, 0, 0]);
  assert.equal(r2.elapsedS, 0);
  assert.equal(r2.preRoundS, 5);
  assert.equal(r2.roundNumber, 2);
  assert.ok(log.some((e) => e.t === 'round:reset'));
  assert.equal(s.player.alive, true);
  assert.equal(s.player.participant.spawnCount, 1, 'spawn counters reset with the round');
  assert.equal(s.killFeed.length, 0);
  assert.ok(!s.player.weapon.state.core.disabledBy.includes('results'));
  assert.deepEqual([s.player.weapon.state.magazine, s.player.weapon.state.chamber, s.player.weapon.state.reserve], [30, 1, 90]);
  for (const p of Object.values(s.match.snapshot().respawn.participants)) assert.equal(p.respawnInUs, 0);
  assert.ok(typeof zone1 === 'string' && typeof r2.zoneId === 'string');
  // round 2: nobody in the zone -> time limit -> draw 0:0:0
  place(s.player, 0, 0, 12, 0);
  const zz = s.activeZone();
  assert.equal(s.isInZone(s.player.position, zz), false);
  tick(s, null, 60 * 605 + 5);
  const r3 = s.roundInfo();
  assert.equal(r3.state, 'ended');
  assert.equal(r3.endReason, 'time_limit');
  assert.equal(r3.draw, true);
});

// ------------------------------------------------------------------ GUN-01 in the game loop

test('GUN-01: weapon switch interrupts a reload before the insert (no ammo change); sprint after the insert keeps the new magazine', () => {
  const { s, log } = makeSession({ bots: [0, 0, 0] });
  const p = s.player;
  const rifle = p.weapons[0];
  const look = { ...IDLE_COMMAND, yaw: 0, pitch: 0.4 };
  tick(s, { ...look, fire: true }, 30); // some rounds
  tick(s, look, 1);
  const before = [rifle.state.magazine, rifle.state.chamber, rifle.state.reserve];
  assert.ok(before[0] < 30);
  tick(s, { ...look, reload: true }, 1);
  assert.equal(rifle.state.state, 'reloading');
  tick(s, look, 30); // 0.5 s < insert commit 1.3 s
  tick(s, { ...look, switchTo: 1 }, 1);
  assert.equal(p.activeWeapon, 1);
  assert.equal(rifle.state.state, 'ready');
  assert.deepEqual([rifle.state.magazine, rifle.state.chamber, rifle.state.reserve], before, 'interrupt before insert changes nothing');
  assert.ok(log.some((e) => e.t === 'weapon:reload_interrupted' && e.p.kind === 'switch'));
  // pistol drawn after its switch time, fires semi
  tick(s, look, 30);
  const pistol = p.weapons[1];
  assert.ok(pistol.state.core.enabled);
  tick(s, { ...look, fire: true }, 30);
  assert.equal(pistol.state.shotsFired, 1, 'semi-auto: one shot per press');
  tick(s, look, 1);
  tick(s, { ...look, switchTo: 0 }, 1);
  tick(s, look, 40);
  assert.ok(rifle.state.core.enabled);
  // empty the rifle, then an empty reload interrupted by sprint after the insert, before the bolt release
  rifle.state.infiniteAmmo = false;
  tick(s, { ...look, fire: true }, 240);
  tick(s, look, 1);
  assert.equal(rifle.state.magazine + rifle.state.chamber, 0);
  tick(s, { ...look, reload: true }, 1);
  assert.equal(rifle.state.core.reloadKind, 'empty');
  tick(s, look, Math.round(1.6 * 60)); // past insert (1.3 s), before bolt release (2.3 s)
  assert.equal(rifle.state.magazine, 30);
  tick(s, { ...look, sprint: true, moveZ: 1 }, 5);
  assert.equal(rifle.state.state, 'ready');
  assert.equal(rifle.state.magazine, 30, 'new magazine kept');
  assert.equal(rifle.state.chamber, 0, 'chamber still empty');
  assert.ok(log.some((e) => e.t === 'weapon:reload_interrupted' && e.p.kind === 'sprint'));
  // next press: chamber action (no shot), then the following press fires
  tick(s, look, 10);
  const shots = rifle.state.shotsFired;
  tick(s, { ...look, fire: true }, 1);
  tick(s, look, 60);
  assert.equal(rifle.state.shotsFired, shots, 'the press only chambers');
  assert.equal(rifle.state.chamber, 1);
  tick(s, { ...look, fire: true }, 1);
  assert.equal(rifle.state.shotsFired, shots + 1);
  assertInvariant(p);
});

// ------------------------------------------------------------------ death pose

test('death pose: falls toward free space (never into a wall), settles at 90 deg, finite', () => {
  const { s } = makeSession({ bots: [0, 1, 0] });
  const e = s.combatants.get('bot_1_0');
  // 0.5 m in front of the thin wall (z -4.05..-3.95), shot from behind (fromDir toward the wall)
  place(e, 21, 0, -3.3, 0);
  tick(s, null, 2);
  s.pendingKills.set(e.id, { attackerId: 'player', fromDir: new Vector3(0, 0, -1), weaponId: 'iv7_carbine', part: 'torso' });
  s.match.kill(e.id);
  s.combatants.processCoreEvents(s.pendingKills);
  const d = e.deathPose;
  assert.ok(d, 'death pose started');
  assert.ok(!(Math.abs(d.dir[0]) < 1e-6 && d.dir[1] < -0.99), `must not fall into the wall: ${d.dir}`);
  const feet = e.position.clone();
  tick(s, null, 60);
  assert.equal(e.deathPose.settled, true);
  assert.ok(Math.abs(e.deathPose.angle - Math.PI / 2) < 1e-9 || e.deathPose.mode === 'crumple');
  assert.ok(e.position.distanceTo(feet) < 0.05, 'the body does not slide or fly');
  const hit = world.raycast(new Vector3(feet.x, 0.3, feet.z), new Vector3(d.dir[0], 0, d.dir[1]), combat.death.fallClearance);
  assert.equal(hit, null, 'free space in the fall direction');
});

// ------------------------------------------------------------------ AI contract integration

test('AI contract: with the real AI system every combatant is stepped exactly once per tick; session disposes the AI', () => {
  const events = new EventBus();
  const s = new MatchSession({ level, world, movement, weaponsData, combat, teams, events, createAISystem: realAI, seed: 3, bots: [2, 3, 3] });
  const steps = new Map();
  for (const c of s.combatants.all()) {
    const orig = c.applyCommand.bind(c);
    c.applyCommand = (cmd, dt) => {
      const k = `${c.id}@${s.tickCount}`;
      steps.set(k, (steps.get(k) || 0) + 1);
      return orig(cmd, dt);
    };
  }
  s.start({ skipPreRound: true });
  for (let i = 0; i < 600; i++) {
    s.tick(DT, { playerCmd: null });
    for (const c of s.combatants.all()) assert.equal(steps.get(`${c.id}@${s.tickCount}`), 1, `${c.id} tick ${s.tickCount}`);
  }
  assert.equal(typeof s.ai.getDebug(), 'object');
  const n = events.listenerCount('weapon:fired');
  s.dispose();
  assert.ok(events.listenerCount('weapon:fired') < n || n === 0, 'AI listeners removed on dispose');
});

// ------------------------------------------------------------------ settings / bindings / HUD helpers

test('key rebinding: data driven, conflicts moved, Esc fixed, persisted; broken storage is tolerated', () => {
  const mem = new Map();
  const storage = { getItem: (k) => mem.get(k) ?? null, setItem: (k, v) => mem.set(k, v), removeItem: (k) => mem.delete(k) };
  const b = new BindingsStore(defaultBindings, storage);
  assert.equal(b.bind('jump', 'KeyJ'), true);
  assert.deepEqual(b.get().actions.jump, ['KeyJ']);
  assert.equal(b.bind('reload', 'KeyJ'), true);
  assert.deepEqual(b.get().actions.reload, ['KeyJ']);
  assert.deepEqual(b.get().actions.jump, [], 'the key moved away from jump');
  assert.equal(b.bind('fire', 'Escape'), false);
  assert.equal(b.bind('fire', 'F3'), false, 'F3 belongs to a fixed action');
  assert.equal(b.bind('menu', 'KeyM'), false, 'menu is not rebindable');
  assert.equal(isBindableCode('Mouse1'), true);
  const b2 = new BindingsStore(defaultBindings, storage);
  assert.deepEqual(b2.get().actions.reload, ['KeyJ'], 'persisted');
  b2.reset();
  assert.deepEqual(new BindingsStore(defaultBindings, storage).get().actions.reload, defaultBindings.actions.reload);
  const broken = { getItem: () => { throw new Error('denied'); }, setItem: () => { throw new Error('denied'); } };
  const b3 = new BindingsStore(defaultBindings, broken);
  assert.equal(b3.bind('jump', 'KeyK'), true);
  assert.deepEqual(b3.get().actions.jump, ['KeyK']);
  const bad = new BindingsStore(defaultBindings, { getItem: () => '{"fire":["Escape"],"jump":"x"}', setItem() {} });
  assert.deepEqual(bad.get().actions.fire, defaultBindings.actions.fire, 'invalid stored bindings are ignored');
});

test('settings: master volume and FOV are clamped; HUD clock format', () => {
  assert.equal(sanitizeSettings({ masterVolume: 3 }).masterVolume, 1);
  assert.equal(sanitizeSettings({ masterVolume: -1 }).masterVolume, 0);
  assert.equal(sanitizeSettings({ fovDeg: 200 }).fovDeg, 100);
  assert.equal(sanitizeSettings({ fovDeg: 10 }).fovDeg, 70);
  assert.equal(formatClock(600), '10:00');
  assert.equal(formatClock(59.2), '1:00');
  assert.equal(formatClock(0), '0:00');
});
