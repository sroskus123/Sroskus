// Spoustec vektoru nesmi tise ignorovat preklepy a spatne umistene klice (V2-P2-5). Stejny soubor
// Shared/testvectors/malformed/cases.json kontroluje i C++ (ivcore_vectors --malformed, ctest runner.malformed).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { VECTORS_DIR, loadBaseRules, checkCase, CaseError } from './support/vector_runner.mjs';

const baseRaw = loadBaseRules();
const fixture = JSON.parse(fs.readFileSync(path.join(VECTORS_DIR, 'malformed/cases.json'), 'utf8'));

test('soubor chybnych pripadu je neprazdny', () => {
  assert.equal(fixture.schema, 'ironvalley.testvectors.malformed');
  assert.ok(fixture.cases.length >= 10);
});

for (const pair of fixture.cases) {
  test(`${pair.id}: kontrolni pripad projde, chybny je odmitnut chybou pripadu`, () => {
    assert.deepEqual(checkCase(pair.good, baseRaw), [], 'kontrolni pripad bez chyby musi projit');
    assert.throws(() => checkCase(pair.bad, baseRaw), (e) => e instanceof CaseError, 'chybny pripad musi skoncit CaseError');
  });
}
