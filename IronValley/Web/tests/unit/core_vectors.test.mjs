// Sdilene testovaci vektory Shared/testvectors/*.json nad JS jadrem (stejne soubory prehrava C++ ctest).
import { describe, test } from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { listVectorFiles, loadVectorFile, loadBaseRules, checkCase } from './support/vector_runner.mjs';

const baseRaw = loadBaseRules();
const files = listVectorFiles();

test('existuji vsechny ocekavane soubory vektoru', () => {
  const names = files.map((f) => path.basename(f));
  for (const n of ['weapon.json', 'zone.json', 'round.json', 'respawn.json', 'match.json', 'rules.json', 'rng.json',
    'fuzz_weapon.json', 'fuzz_zone.json', 'fuzz_round.json', 'fuzz_respawn.json', 'fuzz_match.json']) {
    assert.ok(names.includes(n), `chybi ${n}`);
  }
});

for (const file of files) {
  const data = loadVectorFile(file);
  describe(`vektory ${path.basename(file)}`, () => {
    test('hlavicka souboru', () => {
      assert.equal(data.schema, 'ironvalley.testvectors');
      assert.equal(data.version, 1);
      assert.ok(Array.isArray(data.cases) && data.cases.length > 0);
      const ids = data.cases.map((c) => c.id);
      assert.equal(new Set(ids).size, ids.length, 'duplicitni id pripadu');
    });
    for (const testCase of data.cases) {
      test(testCase.id, () => {
        const failures = checkCase(testCase, baseRaw);
        assert.deepEqual(failures, [], failures.slice(0, 20).join('\n'));
      });
    }
  });
}
