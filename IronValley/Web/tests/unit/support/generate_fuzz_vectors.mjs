// CLI: vygeneruje Shared/testvectors/fuzz_*.json z JS jadra.
//   node tests/unit/support/generate_fuzz_vectors.mjs          zapise soubory
//   node tests/unit/support/generate_fuzz_vectors.mjs --check  jen overi, ze ulozene soubory odpovidaji (exit 1 pri rozdilu)

import fs from 'node:fs';
import path from 'node:path';
import { generateFuzzDocs, serializeFuzzDoc } from './fuzz_generator.mjs';
import { loadBaseRules, VECTORS_DIR } from './vector_runner.mjs';

const check = process.argv.includes('--check');
const docs = generateFuzzDocs(loadBaseRules());
let stale = 0;
for (const [name, d] of Object.entries(docs)) {
  const file = path.join(VECTORS_DIR, name);
  const text = serializeFuzzDoc(d);
  const steps = d.cases.reduce((n, c) => n + c.steps.length, 0);
  if (check) {
    const current = fs.existsSync(file) ? fs.readFileSync(file, 'utf8') : '';
    const same = current === text;
    if (!same) stale += 1;
    console.log(`${same ? 'OK   ' : 'STALE'} ${name} (${d.cases.length} pripadu, ${steps} kroku)`);
  } else {
    fs.writeFileSync(file, text);
    console.log(`zapsano ${name}: ${d.cases.length} pripadu, ${steps} kroku, ${(text.length / 1024).toFixed(0)} KiB`);
  }
}
process.exit(stale > 0 ? 1 : 0);
