// Vlastnosti automatu zbrane nad ramec rucnich vektoru: nezavislost na delce tiku pro mnoho nahodnych rozdeleni
// a invariant munice pri dlouhych nahodnych posloupnostech. (Rucni vektory GUN-01 jsou ve Shared/testvectors/weapon.json.)
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { compileRules, Rng, WeaponState, weaponInvariantViolations, TickClock } from '../../src/core/index.js';
import { loadBaseRules } from './support/vector_runner.mjs';

const rules = compileRules(loadBaseRules());

/** Rozdeli durationUs na nahodne tiky (vcetne nulovych). */
function randomPartition(rng, durationUs, maxUs) {
  const out = [];
  let t = 0;
  while (t < durationUs) {
    const dt = Math.min(rng.pickIndex(maxUs + 1), durationUs - t);
    out.push(dt);
    t += dt;
  }
  return out;
}

/** Scenar: segmenty [trvani, spoust] a prikazy mezi segmenty. Vraci konecny stav + casy vystrelu. */
function scenarioSegments(def) {
  if (def.fireModes.includes('auto')) {
    return [
      { us: 2500000, trigger: true },
      { us: 500000, trigger: false, after: 'reload' },
      { us: 3500000, trigger: true },
      { us: 100000, trigger: false },
      { us: 1000000, trigger: true, after: 'reload' },
      { us: 700000, trigger: false, after: 'interrupt' },
      { us: 2000000, trigger: true },
    ];
  }
  // Poloautomat: rada stisku a pusteni (kratsi i delsi nez palebny interval), prebiti a preruseni.
  const segs = [];
  for (let i = 0; i < 20; i += 1) segs.push({ us: 90000 + i * 7000, trigger: true }, { us: 40000 + i * 3000, trigger: false });
  segs.push({ us: 500000, trigger: false, after: 'reload' }, { us: 3000000, trigger: true }, { us: 100000, trigger: false });
  for (let i = 0; i < 10; i += 1) segs.push({ us: 150000, trigger: true }, { us: 20000, trigger: false });
  segs.push({ us: 300000, trigger: false, after: 'reload' }, { us: 500000, trigger: false, after: 'interrupt' });
  for (let i = 0; i < 5; i += 1) segs.push({ us: 100000, trigger: true }, { us: 100000, trigger: false });
  return segs;
}

function runScenario(def, partitionFor) {
  const w = new WeaponState(def);
  const shotTimes = [];
  const segments = scenarioSegments(def);
  for (const seg of segments) {
    for (const dt of partitionFor(seg.us)) {
      w.update(dt, seg.trigger);
      for (const e of w.takeEvents()) if (e.type === 'shot') shotTimes.push(e.atUs);
      assert.deepEqual(weaponInvariantViolations(w.snapshot(), def), []);
    }
    if (seg.after === 'reload') w.reload();
    if (seg.after === 'interrupt') w.interrupt('sprint');
    w.takeEvents();
  }
  return { snap: w.snapshot(), shotTimes };
}

test('GUN-01 kadence: stejny vysledek pro 1/30, 1/60, 1/144 a 200 nahodnych rozdeleni tiku', () => {
  for (const wid of ['rifle_iv7', 'pistol_p9']) {
    const def = rules.weapons[wid];
    const fixed = (hz) => (us) => {
      const out = [];
      let prev = 0;
      for (let k = 1; prev < us; k += 1) {
        const t = Math.min(Math.round((k * 1e6) / hz), us);
        out.push(t - prev);
        prev = t;
      }
      return out;
    };
    const reference = runScenario(def, fixed(60));
    assert.ok(reference.shotTimes.length >= 20, `scenar musi vystrelit dost ran (${reference.shotTimes.length})`);
    for (const hz of [30, 144, 240, 7]) assert.deepEqual(runScenario(def, fixed(hz)), reference, `${wid} @${hz} Hz`);
    const rng = new Rng(0xabcdef);
    for (let i = 0; i < 200; i += 1) {
      const maxUs = [1000, 20000, 100000, 1500000][i % 4];
      assert.deepEqual(runScenario(def, (us) => randomPartition(rng, us, maxUs)), reference, `${wid} nahodne rozdeleni #${i}`);
    }
  }
});

test('GUN-01 kadence: pocet vystrelu za drzeni odpovida ceil(T / interval) (polootevreny interval)', () => {
  const def = rules.weapons.rifle_iv7; // 80 000 us
  for (const [T, expected] of [[80000, 1], [80001, 2], [160000, 2], [1000000, 13], [2400000, 30], [2400001, 31]]) {
    const w = new WeaponState(def);
    let shots = 0;
    for (const hz of [144]) {
      let prev = 0;
      for (let k = 1; prev < T; k += 1) {
        const t = Math.min(Math.round((k * 1e6) / hz), T);
        shots += w.update(t - prev, true);
        prev = t;
      }
    }
    assert.equal(shots, expected, `T=${T}`);
  }
});

test('GUN-01 invariant munice pri 300 nahodnych posloupnostech (vcetne preruseni a respawnu)', () => {
  const rng = new Rng(20260926);
  const ids = ['rifle_iv7', 'pistol_p9'];
  for (let run = 0; run < 300; run += 1) {
    const def = rules.weapons[ids[run % 2]];
    const w = new WeaponState(def, { magazine: rng.pickIndex(def.magazineCapacity + 1), chamber: rng.pickIndex(2), reserve: rng.pickIndex(60) });
    let trigger = false;
    for (let i = 0; i < 200; i += 1) {
      const x = rng.pickIndex(100);
      if (x < 55) {
        if (rng.pickIndex(4) === 0) trigger = !trigger;
        w.update(rng.pickIndex(400000), trigger);
      } else if (x < 70) w.reload();
      else if (x < 82) w.interrupt(['sprint', 'switch', 'death'][rng.pickIndex(3)]);
      else if (x < 88) w.resupply(rng.pickIndex(40));
      else if (x < 90) w.resetToLoadout();
      else w.setFireMode(def.fireModes[rng.pickIndex(def.fireModes.length)]);
      const v = weaponInvariantViolations(w.snapshot(), def);
      assert.deepEqual(v, [], `beh ${run} krok ${i}`);
    }
  }
});

test('GUN-01 kazdy commit munice probehne presne jednou (i pri nulovych a obrich ticich)', () => {
  const def = rules.weapons.rifle_iv7;
  const rng = new Rng(7);
  for (let run = 0; run < 100; run += 1) {
    const w = new WeaponState(def, { magazine: 0, chamber: 0, reserve: 90 });
    assert.equal(w.reload(), 'started_empty');
    const events = [];
    for (let i = 0; i < 400 && w.state !== 'ready'; i += 1) {
      w.update(rng.pickIndex(3) === 0 ? 0 : rng.pickIndex(300000), false);
      events.push(...w.takeEvents().map((e) => e.type));
    }
    w.update(5000000, false);
    events.push(...w.takeEvents().map((e) => e.type));
    assert.deepEqual(events, ['reload_start', 'mag_insert', 'bolt_release', 'reload_complete'], `beh ${run}`);
    assert.equal(w.magazine, 29);
    assert.equal(w.chamber, 1);
    assert.equal(w.reserve, 60);
  }
});

test('TickClock prevadi plovouci dt na cele mikrosekundy bez driftu', () => {
  const clock = new TickClock();
  let sum = 0;
  for (let i = 0; i < 144 * 600; i += 1) sum += clock.advance(1 / 144);
  assert.ok(Math.abs(sum - 600000000) <= 1, `soucet ${sum}`);
  const c2 = new TickClock();
  let s2 = 0;
  for (let i = 0; i < 60; i += 1) s2 += c2.advance(1 / 60);
  assert.equal(s2, 1000000);
  assert.throws(() => c2.advance(-1));
});

test('jadro odmita neplatne dt', () => {
  const w = new WeaponState(rules.weapons.rifle_iv7);
  assert.throws(() => w.update(0.5, true));
  assert.throws(() => w.update(-1, true));
  assert.throws(() => w.update(Number.NaN, true));
  assert.throws(() => new WeaponState(rules.weapons.rifle_iv7, { magazine: 31 }));
});
