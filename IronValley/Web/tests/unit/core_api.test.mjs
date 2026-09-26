// API jadra, ktere vektory nepokryvaji (konstrukce, predikat enginu, vstupy Set/pole).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { compileRules, RespawnSystem, Match, Round, ZoneScoring, spawnPointSafe } from '../../src/core/index.js';
import { loadBaseRules } from './support/vector_runner.mjs';

const rules = compileRules(loadBaseRules());
const areas = [[[0, 0, 0], [4, 0, 0]], [[100, 0, 0]], [[0, 0, 100]]];

test('RespawnSystem odmitne neplatne spawnove oblasti', () => {
  assert.throws(() => new RespawnSystem(rules, { seed: 1, spawnAreas: areas.slice(0, 2) }));
  assert.throws(() => new RespawnSystem(rules, { seed: 1, spawnAreas: [[], [[1, 2, 3]], [[1, 2, 3]]] }));
  assert.throws(() => new RespawnSystem(rules, { seed: 1, spawnAreas: [[[0, 0]], [[1, 2, 3]], [[1, 2, 3]]] }));
});

test('predikat enginu dostane participantId, tym, index a bod; odmitnuty bod se nepouzije', () => {
  const rs = new RespawnSystem(rules, { seed: 1, spawnAreas: areas });
  rs.addParticipant('a1', 0);
  const queries = [];
  rs.update(0, (q) => {
    queries.push({ ...q, point: q.point.slice() });
    return q.candidateIndex === 1;
  });
  assert.equal(rs.participant('a1').spawnPoint, 1);
  assert.ok(queries.every((q) => q.participantId === 'a1' && q.team === 0));
  assert.deepEqual(queries.find((q) => q.candidateIndex === 1).point, [4, 0, 0]);
});

test('respawn zachova objekty zbrani (engine muze drzet referenci)', () => {
  const rs = new RespawnSystem(rules, { seed: 1, spawnAreas: areas });
  rs.addParticipant('a1', 0);
  rs.update(0);
  const w = rs.weapon('a1', 'rifle_iv7');
  w.update(16667, true);
  assert.equal(w.magazine, 29);
  rs.kill('a1');
  rs.update(5000000);
  assert.equal(rs.weapon('a1', 'rifle_iv7'), w);
  assert.equal(w.magazine, 30);
});

test('spawnPointSafe: vzdalenost je 3D a hranice je ostra', () => {
  const r = rules.respawn;
  assert.equal(spawnPointSafe([0, 0, 0], 0, [{ team: 1, alive: true, pos: [0, 25, 0] }], r), true);
  assert.equal(spawnPointSafe([0, 0, 0], 0, [{ team: 1, alive: true, pos: [0, 24.99, 0] }], r), false);
  assert.equal(spawnPointSafe([0, 0, 0], 0, [{ team: 0, alive: true, pos: [0.5, 0, 0] }], r), false);
  assert.equal(spawnPointSafe([0, 0, 0], 0, [{ team: 0, alive: false, pos: [0, 0, 0] }], r), true);
});

test('Match.update prijme Set i pole a ve stavu ended nic nemeni', () => {
  const m = new Match(rules, { seed: 3, spawnAreas: areas });
  m.addParticipant('a1', 0);
  m.addParticipant('b1', 1);
  m.update(0);
  m.start();
  m.update(2000000, { inZone: new Set(['a1']) });
  assert.deepEqual(m.round.scores, [1, 0, 0]);
  m.update(2000000, { inZone: ['a1'] });
  assert.deepEqual(m.round.scores, [2, 0, 0]);
  // t = 199 s: 99 bodu (posledni v 198 s), postup 1 s. b1 zemre tesne pred koncem kola.
  m.update(195000000, { inZone: ['a1'] });
  assert.deepEqual(m.round.scores, [99, 0, 0]);
  assert.equal(m.kill('b1'), 'killed');
  // Cil (100) padne v t = 200 s uprostred tiku: cas kola i odpocet respawnu dobehnou jen do tohoto okamziku.
  assert.equal(m.update(10000000, { inZone: ['a1'] }), 'ok');
  assert.equal(m.state, 'ended');
  assert.equal(m.round.endReason, 'score_target');
  assert.equal(m.round.winner, 0);
  assert.deepEqual(m.round.scores, [100, 0, 0]);
  assert.equal(m.round.elapsedUs, 200000000);
  assert.equal(m.respawn.participant('b1').respawnInUs, 4000000);
  // Ve stavu ended: skore, cas, oblast ani respawny se nehnou; zabiti a poskozeni jsou odmitnuta.
  const before = JSON.stringify(m.snapshot());
  assert.equal(m.update(10000000, { inZone: new Set(['a1', 'b1']) }), 'ok');
  assert.equal(m.update(0, { inZone: ['b1'] }), 'ok');
  assert.equal(JSON.stringify(m.snapshot()), before);
  assert.equal(m.respawn.participant('b1').state, 'dead');
  assert.equal(m.kill('a1'), 'round_ended');
  assert.deepEqual(m.applyDamage('a1', 10, null), { result: 'round_ended', applied: 0 });
});

test('Match.update: zaporne nebo neceleciselne dt je chyba i po konci kola', () => {
  const m = new Match(rules, { seed: 3, spawnAreas: areas });
  m.addParticipant('a1', 0);
  assert.throws(() => m.update(-1), RangeError);
  assert.throws(() => m.update(0.5), RangeError);
  assert.equal(m.respawn.participant('a1').state, 'respawning');
});

test('Match.reset i zmena vybavy zachovaji objekty zbrani; odebrana zbran zustane vypnuta', () => {
  const m = new Match(rules, { seed: 3, spawnAreas: areas });
  m.addParticipant('a1', 0);
  m.update(0);
  const rifle = m.respawn.weapon('a1', 'rifle_iv7');
  const pistol = m.respawn.weapon('a1', 'pistol_p9');
  assert.equal(rifle.update(16667, true), 1);
  m.reset();
  assert.equal(m.respawn.weapon('a1', 'rifle_iv7'), rifle);
  assert.equal(rifle.magazine, 30);
  assert.equal(rifle.enabled, false, 'do spawnu je zbran vypnuta');
  assert.equal(rifle.reload(), 'rejected_disabled');
  m.update(0);
  assert.equal(rifle.enabled, true);
  m.respawn.setLoadout('a1', ['pistol_p9']);
  m.kill('a1');
  m.update(5000000);
  assert.equal(m.respawn.weapon('a1', 'rifle_iv7'), null);
  assert.equal(m.respawn.weapon('a1', 'pistol_p9'), pistol);
  rifle.update(16667, false);
  assert.equal(rifle.update(100000, true), 0, 'stara reference na odebranou zbran nestrili');
  assert.equal(rifle.reload(), 'rejected_disabled');
  m.respawn.setLoadout('a1', ['rifle_iv7', 'pistol_p9']);
  m.kill('a1');
  m.update(5000000);
  assert.equal(m.respawn.weapon('a1', 'rifle_iv7'), rifle, 'znovu vybavena zbran je puvodni objekt');
  assert.equal(rifle.enabled, true);
});

test('Round a ZoneScoring odmitnou neplatne dt', () => {
  const round = new Round(rules, 1);
  assert.throws(() => round.tick(-5, []));
  const zone = new ZoneScoring(rules);
  assert.throws(() => zone.tick(1.5, []));
  assert.throws(() => zone.advance(10, 0));
});
