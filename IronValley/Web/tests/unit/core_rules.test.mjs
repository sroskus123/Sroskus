// Shared/config/rules.json obsahuje hodnoty ze zadani (§2.1, GAME-01/02, GUN-01) a jadro je spravne nacte.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { compileRules, validateRules, mergePatch, RulesError } from '../../src/core/index.js';
import { loadBaseRules } from './support/vector_runner.mjs';

const raw = loadBaseRules();

test('rules.json je platny a obsahuje hodnoty ze zadani', () => {
  assert.deepEqual(validateRules(raw), []);
  const r = compileRules(raw);
  assert.equal(r.teamCount, 3);
  assert.equal(r.teamSize, 6);
  assert.equal(r.round.timeLimitUs, 600 * 1e6);
  assert.equal(r.round.scoreTarget, 100);
  assert.equal(r.zone.pointIntervalUs, 2 * 1e6);
  assert.equal(r.zone.pointsPerAward, 1);
  assert.equal(r.zone.locations.length, 3, 'tri umisteni oblasti');
  assert.equal(r.respawn.delayUs, 5 * 1e6);
  assert.equal(r.combat.friendlyFire, false);
  const rifle = r.weapons.rifle_iv7;
  assert.equal(rifle.magazineCapacity, 30);
  assert.equal(rifle.hasChamber, true, 'puska 30+1');
  const pistol = r.weapons.pistol_p9;
  assert.equal(pistol.magazineCapacity, 15);
  assert.equal(pistol.hasChamber, true, 'pistole 15+1');
  assert.deepEqual(r.loadout.default, ['rifle_iv7', 'pistol_p9']);
});

test('zkompilovana pravidla jsou zmrazena', () => {
  const r = compileRules(raw);
  assert.throws(() => {
    r.round.scoreTarget = 5;
  });
});

test('neplatna pravidla vyhodi RulesError se seznamem chyb', () => {
  const bad = mergePatch(raw, { round: { scoreTarget: 0 }, weapons: { rifle_iv7: { magazineCapacity: -1 } } });
  assert.throws(() => compileRules(bad), (e) => e instanceof RulesError && e.errors.length === 2);
});

test('roundsPerMinute pod 1 rana/min je odmitnuto pred prevodem na us (hlaseni shodne s C++ unit_tests.cpp)', () => {
  for (const rpm of [1e-300, 0.9999999999999999]) {
    const errors = validateRules(mergePatch(raw, { weapons: { rifle_iv7: { roundsPerMinute: rpm } } }));
    assert.deepEqual(errors, ['weapons.rifle_iv7.roundsPerMinute: musi byt alespon 1 rana/min (palebny interval nejvyse 60 s)']);
  }
  const r = compileRules(mergePatch(raw, { weapons: { rifle_iv7: { roundsPerMinute: 1 } } }));
  assert.equal(r.weapons.rifle_iv7.fireIntervalUs, 60 * 1e6);
});

test('mergePatch: objekty se slucuji, null maze, pole se nahrazuji, vstup se nemeni', () => {
  const base = { a: { b: 1, c: [1, 2] }, d: 1 };
  const out = mergePatch(base, { a: { c: [3] }, d: null, e: 2 });
  assert.deepEqual(out, { a: { b: 1, c: [3] }, e: 2 });
  assert.deepEqual(base, { a: { b: 1, c: [1, 2] }, d: 1 });
});
