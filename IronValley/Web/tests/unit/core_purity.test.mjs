// Jadro pravidel musi byt ciste (D6): bez three.js, bez DOM, bez nedeterministickych zdroju (Math.random, hodiny).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const coreDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../src/core');
const files = fs.readdirSync(coreDir).filter((f) => f.endsWith('.js'));

test('src/core obsahuje ocekavane moduly', () => {
  for (const f of ['index.js', 'time.js', 'rng.js', 'rules.js', 'weapon.js', 'zone.js', 'round.js', 'respawn.js', 'match.js']) {
    assert.ok(files.includes(f), `chybi ${f}`);
  }
});

for (const f of files) {
  test(`${f}: jen relativni importy, zadne DOM/three/nedeterminismus`, () => {
    const src = fs.readFileSync(path.join(coreDir, f), 'utf8');
    const code = src.replace(/\/\/.*$/gm, '').replace(/\/\*[\s\S]*?\*\//g, '');
    for (const m of code.matchAll(/(?:import|export)\s[^'"]*from\s+['"]([^'"]+)['"]/g)) {
      assert.ok(m[1].startsWith('./'), `${f}: nepovoleny import ${m[1]}`);
    }
    assert.ok(!/\bimport\s*\(/.test(code), `${f}: dynamicky import`);
    for (const banned of ['window', 'document', 'navigator', 'requestAnimationFrame', 'localStorage', 'THREE', 'Math.random', 'Date.now', 'performance.now', 'setTimeout', 'setInterval', 'process.']) {
      assert.ok(!code.includes(banned), `${f}: obsahuje zakazane "${banned}"`);
    }
  });
}
