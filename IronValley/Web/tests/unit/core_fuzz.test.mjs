// Diferencialni fuzz: ulozene soubory Shared/testvectors/fuzz_*.json musi byt presne to, co dnes vygeneruje
// JS jadro (jinak by C++ porovnaval proti zastaralym ocekavanim). Samotne prehrani souboru dela core_vectors.test.mjs
// (JS) a ctest (C++).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { generateFuzzDocs, serializeFuzzDoc } from './support/fuzz_generator.mjs';
import { loadBaseRules, VECTORS_DIR, checkCase, snapshotDigest, canonicalJson } from './support/vector_runner.mjs';

const docs = generateFuzzDocs(loadBaseRules());

for (const [name, d] of Object.entries(docs)) {
  test(`${name} odpovida aktualnimu generatoru (neni zastaraly)`, () => {
    const file = path.join(VECTORS_DIR, name);
    assert.ok(fs.existsSync(file), `chybi ${name}; spust node tests/unit/support/generate_fuzz_vectors.mjs`);
    const current = fs.readFileSync(file, 'utf8');
    assert.ok(current === serializeFuzzDoc(d), `${name} je zastaraly; spust node tests/unit/support/generate_fuzz_vectors.mjs`);
  });
}

test('generator je deterministicky', () => {
  const again = generateFuzzDocs(loadBaseRules());
  for (const name of Object.keys(docs)) assert.equal(serializeFuzzDoc(again[name]), serializeFuzzDoc(docs[name]));
});

test('fuzz pokryva vsechny druhy udalosti zbrane', () => {
  const seen = new Set();
  for (const c of docs['fuzz_weapon.json'].cases) for (const s of c.steps) for (const e of s.expect.events) seen.add(e.type);
  for (const t of ['shot', 'dry_fire', 'bolt_locked', 'reload_start', 'mag_insert', 'bolt_release', 'reload_complete',
    'reload_interrupted', 'chamber_start', 'chamber_commit', 'chamber_complete']) {
    assert.ok(seen.has(t), `fuzz nepokryl udalost ${t}`);
  }
});

test('digest odhali zmenu libovolneho pole stavu', () => {
  // Kontrola, ze porovnani pres digest neni slepe: zmena jedineho cisla i poradi klicu.
  const c = docs['fuzz_weapon.json'].cases[0];
  const snap = c.steps[c.steps.length - 1].expect.snapshot;
  const d0 = snapshotDigest(snap);
  assert.equal(snapshotDigest(JSON.parse(JSON.stringify(snap))), d0);
  const reordered = Object.fromEntries(Object.entries(snap).reverse());
  assert.equal(snapshotDigest(reordered), d0, 'poradi klicu nesmi hrat roli');
  assert.notEqual(snapshotDigest({ ...snap, reserve: snap.reserve + 1 }), d0);
  assert.equal(canonicalJson({ b: 1, a: [true, 'x'] }), '{"a":[true,"x"],"b":1}');
});

test('pozmenene ocekavani ve fuzz vektoru spoustec odhali', () => {
  const baseRaw = loadBaseRules();
  const c = JSON.parse(JSON.stringify(docs['fuzz_zone.json'].cases[0]));
  c.steps[5].expect.snapshotDigest = '0000000000000000';
  assert.ok(checkCase(c, baseRaw).length > 0);
});
