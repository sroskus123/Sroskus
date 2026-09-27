// Generator diferencialnich fuzz vektoru. Nahodne, ale platne posloupnosti akci pro munici, oblast, kolo,
// respawn a zapas; ocekavane vystupy (vysledek, udalosti, stav) dopocita JS jadro. C++ test prehraje stejne
// soubory a musi dat bit po bitu stejny vysledek.
//
// Porovnani stavu: kazdy krok ma "snapshotDigest" (FNV-1a 64 kanonickeho JSON celeho stavu = presna shoda vsech
// poli) a kazdy CHECKPOINT_EVERY-ty a posledni krok navic cely "snapshot" pro citelnou diagnostiku rozdilu.
//
// Pouziti: node tests/unit/support/generate_fuzz_vectors.mjs   (zapise Shared/testvectors/fuzz_*.json)

import { Rng, compileRules, mergePatch } from '../../../src/core/index.js';
import { CaseSession, snapshotDigest } from './vector_runner.mjs';

export const FUZZ_MASTER_SEED = 0x1f0e2d3c;
const CHECKPOINT_EVERY = 10;

const OPENBOLT = {
  name: 'Fuzz: zbran bez komory',
  slot: 'primary',
  magazineCapacity: 20,
  hasChamber: false,
  startReserve: 40,
  maxReserve: 80,
  roundsPerMinute: 600,
  fireModes: ['auto', 'semi'],
  defaultFireMode: 'auto',
  damage: 20,
  reload: { tactical: { duration: 2.0, insertCommit: 1.0 }, empty: { duration: 2.5, insertCommit: 1.2 } },
};

class R {
  constructor(seed) {
    this.rng = new Rng(seed);
  }

  u32() {
    return this.rng.nextU32();
  }

  int(a, b) {
    return a + this.rng.pickIndex(b - a + 1);
  }

  chance(p) {
    return this.rng.nextU32() < p * 4294967296;
  }

  pick(arr) {
    return arr[this.rng.pickIndex(arr.length)];
  }

  subset(arr, p) {
    return arr.filter(() => this.chance(p));
  }
}

function randDt(r, scale = 1) {
  const x = r.int(0, 99);
  if (x < 8) return 0;
  if (x < 45) return r.int(1, 20000) * scale;
  if (x < 70) return r.pick([16667, 16666, 6944, 6945, 33333, 8333, 1000]) * scale;
  if (x < 94) return r.int(20000, 400000) * scale;
  return r.int(400000, 3000000) * scale;
}

function randMode(r) {
  const x = r.int(0, 5);
  if (x === 0) return { hz: 30 };
  if (x === 1) return { hz: 60 };
  if (x === 2) return { hz: 144 };
  if (x === 3) return { hz: r.int(5, 240) };
  if (x === 4) {
    const minUs = r.int(0, 5000);
    return { irregular: { seed: r.u32(), minUs, maxUs: r.int(minUs + 1, 90000) } };
  }
  return { dtUs: r.int(1000, 200000) };
}

function withTrigger(step, trigger) {
  if (trigger) step.trigger = true;
  return step;
}

/** Vytvori pripad: generuje krok, provede ho v zive session a ulozi ocekavany vystup. */
function buildCase(meta, baseRaw, nSteps, nextStep) {
  const testCase = { ...meta, steps: [] };
  const session = new CaseSession(testCase, baseRaw, null);
  for (let i = 0; i < nSteps; i += 1) {
    const step = nextStep(session, i);
    const out = session.step(step);
    if (out.problems.length > 0) throw new Error(`fuzz ${meta.id} krok ${i}: ${out.problems.join('; ')}`);
    const expect = { result: out.result, events: out.events, snapshotDigest: snapshotDigest(out.snapshot) };
    if ((i + 1) % CHECKPOINT_EVERY === 0 || i === nSteps - 1) expect.snapshot = out.snapshot;
    testCase.steps.push({ ...step, expect });
  }
  return testCase;
}

// ------------------------------------------------------------------ zbran

function genWeaponCase(r, baseRaw, index) {
  const rulesOverride = { weapons: { fuzz_openbolt: OPENBOLT } };
  const rules = compileRules(mergePatch(baseRaw, rulesOverride));
  const wid = r.pick(['rifle_iv7', 'pistol_p9', 'fuzz_openbolt']);
  const def = rules.weapons[wid];
  const lowAmmo = r.chance(0.5);
  const setup = {
    weapon: wid,
    magazine: lowAmmo ? r.int(0, 4) : r.int(0, def.magazineCapacity),
    chamber: def.hasChamber ? r.int(0, 1) : 0,
    reserve: lowAmmo ? r.int(0, 45) : r.int(0, Math.min(def.maxReserve, 120)),
    fireMode: r.pick(def.fireModes),
  };
  let trigger = false;
  const flip = (p) => {
    if (r.chance(p)) trigger = !trigger;
    return trigger;
  };
  const meta = { id: `FUZZ/weapon-${index}-${wid}`, kind: 'weapon', rules: rulesOverride, setup };
  return buildCase(meta, baseRaw, 110, (session) => {
    const w = session.sys;
    // Rizeni podle ziveho stavu (porad nahodne a platne): behem akce casteji preruseni v nahodnem okamziku,
    // pri prazdne komore a plnem zasobniku casteji stisk spouste (nabiti), pri malo munici casteji doplneni.
    if (w.state === 'reloading' && w.reloadKind === 'empty' && w.insertCommitted && !w.boltReleased && r.chance(0.5)) {
      return { op: 'interrupt', reason: r.pick(['sprint', 'switch', 'death']) };
    }
    if (w.state !== 'ready' && r.chance(0.6)) {
      if (r.chance(0.25)) return { op: 'interrupt', reason: r.pick(['sprint', 'switch', 'death']) };
      return withTrigger({ op: 'tick', dtUs: r.int(0, 700000) }, flip(0.5));
    }
    if (w.needsChamberAction && r.chance(0.6)) {
      if (r.chance(0.2)) return { op: 'reload' };
      trigger = !w.triggerPrev;
      return withTrigger({ op: 'tick', dtUs: r.int(1, 700000) }, trigger);
    }
    if (w.state === 'ready' && w.chamber === 0 && w.magazine === 0 && w.reserve > 0 && r.chance(0.5)) return { op: 'reload' };
    if (w.totalAmmo < 3 && r.chance(0.3)) return { op: 'resupply', rounds: r.int(1, 40) };
    // Vypnuti (smrt, menu) a zapnuti: vypnuta zbran casto dostava spoust i prebiti, ktere musi ignorovat.
    if (!w.enabled && r.chance(0.3)) return { op: 'enable' };
    if (r.chance(0.04)) return { op: 'disable', reason: r.pick(['death', 'other', 'sprint', 'switch', 'jump']) };
    const x = r.int(0, 99);
    if (x < 48) return withTrigger({ op: 'tick', dtUs: randDt(r) }, flip(0.3));
    if (x < 58) return { op: 'reload' };
    if (x < 65) return { op: 'interrupt', reason: r.pick(['sprint', 'switch', 'death', 'other', 'sprint', 'jump']) };
    if (x < 69) return { op: 'setFireMode', mode: r.pick(['semi', 'auto', 'burst']) };
    if (x < 73) return { op: 'resupply', rounds: r.int(-2, 50) };
    if (x < 75) return { op: 'resetToLoadout' };
    if (x < 89) return withTrigger({ op: 'run', durationUs: r.int(0, 3000000), ticks: randMode(r) }, flip(0.4));
    return withTrigger({ op: 'tick', dtUs: r.pick([16667, 16666, 6944, 6945, 33333]), repeat: r.int(1, 30) }, flip(0.3));
  });
}

// ------------------------------------------------------------------ oblast a kolo

function makeRoster(r, perTeamMin, perTeamMax) {
  const roster = [];
  ['a', 'b', 'c'].forEach((prefix, team) => {
    const n = r.int(perTeamMin, perTeamMax);
    for (let k = 1; k <= n; k += 1) roster.push([`${prefix}${k}`, team, true, true, false]);
  });
  return roster;
}

function mutateRoster(r, roster) {
  for (const p of roster) {
    if (r.chance(0.15)) p[4] = !p[4];
    if (r.chance(0.05)) p[2] = !p[2];
    if (r.chance(0.04)) p[3] = !p[3];
  }
  return roster.map((p) => p.slice());
}

function invalidRoster(r, roster) {
  const copy = roster.map((p) => p.slice());
  if (copy.length === 0 || r.chance(0.5)) copy.push([copy.length ? copy[0][0] : 'dup', 0, true, true, true], ['dup', 0, true, true, true]);
  else copy[r.int(0, copy.length - 1)][1] = r.pick([3, -1, 7]);
  return copy;
}

function genZoneCase(r, baseRaw, index) {
  const roster = makeRoster(r, 1, 4);
  const rulesOverride = { zone: { pointInterval: r.pick([2.0, 2.0, 1.0, 0.7, 2.5]), pointsPerAward: r.pick([1, 1, 2]) } };
  const meta = { id: `FUZZ/zone-${index}`, kind: 'zone', rules: rulesOverride };
  return buildCase(meta, baseRaw, 100, () => {
    const x = r.int(0, 99);
    if (x < 80) return { op: 'tick', dtUs: randDt(r, r.pick([1, 1, 5])), participants: mutateRoster(r, roster) };
    if (x < 88) return { op: 'run', durationUs: r.int(0, 8000000), ticks: randMode(r), participants: mutateRoster(r, roster) };
    if (x < 91) return { op: 'reset' };
    if (x < 96) return { op: 'tick', dtUs: randDt(r), participants: invalidRoster(r, roster) };
    return { op: 'tick', dtUs: 0, participants: mutateRoster(r, roster) };
  });
}

function genRoundCase(r, baseRaw, index) {
  const roster = makeRoster(r, 1, 3);
  const rulesOverride = {
    round: { preRoundDuration: r.pick([0, 1.0, 5.0]), timeLimit: r.pick([20.0, 45.0, 90.0]), scoreTarget: r.int(3, 30) },
    zone: { pointInterval: r.pick([2.0, 1.0, 0.7, 1.5]), pointsPerAward: r.pick([1, 1, 2, 3]) },
  };
  const meta = { id: `FUZZ/round-${index}`, kind: 'round', rules: rulesOverride, setup: { seed: r.u32() } };
  return buildCase(meta, baseRaw, 110, () => {
    const x = r.int(0, 99);
    if (x < 70) return { op: 'tick', dtUs: randDt(r, r.pick([1, 5, 10])), participants: mutateRoster(r, roster) };
    if (x < 82) return { op: 'run', durationUs: r.int(0, 20000000), ticks: randMode(r), participants: mutateRoster(r, roster) };
    if (x < 88) return { op: 'start' };
    if (x < 93) return { op: 'reset' };
    return { op: 'tick', dtUs: randDt(r), participants: invalidRoster(r, roster) };
  });
}

// ------------------------------------------------------------------ respawn a zapas

const TEAM_BASE = [
  [0, 0, 0],
  [100, 0, 0],
  [0, 0, 100],
];

function randSpawnAreas(r) {
  return TEAM_BASE.map((base) => {
    const n = r.int(1, 5);
    const pts = [];
    for (let i = 0; i < n; i += 1) pts.push([base[0] + r.int(0, 40) / 2, base[1] + r.int(0, 4) / 4, base[2] + r.int(0, 40) / 2]);
    return pts;
  });
}

function randBodies(r) {
  const n = r.int(0, 4);
  const out = [];
  for (let i = 0; i < n; i += 1) {
    const base = r.pick(TEAM_BASE);
    out.push({ team: r.int(0, 2), alive: r.chance(0.75), pos: [base[0] + r.int(-60, 80) / 2, 0, base[2] + r.int(-60, 80) / 2] });
  }
  return out;
}

function randBlocked(r, areas) {
  const out = {};
  areas.forEach((area, team) => {
    if (r.chance(0.4)) out[String(team)] = area.map((_, i) => i).filter(() => r.chance(0.5));
  });
  return out;
}

function randWeaponStep(r) {
  const x = r.int(0, 10);
  if (x < 5) return withTrigger({ op: 'tick', dtUs: randDt(r) }, r.chance(0.5));
  if (x < 7) return { op: 'reload' };
  if (x < 8) return { op: 'interrupt', reason: r.pick(['sprint', 'switch', 'death']) };
  if (x < 10) return withTrigger({ op: 'run', durationUs: r.int(0, 1500000), ticks: randMode(r) }, r.chance(0.5));
  return r.chance(0.5) ? { op: 'disable', reason: 'other' } : { op: 'enable' };
}

/**
 * Makro nad jednou zbrani: pusteni, davka, prebiti a dost dlouhy beh, aby prebiti dobehlo pres commit vlozeni
 * s neprazdnym zasobnikem (jinak by respawn/match fuzz munici pri prebiti skoro nikdy neoveril). U mrtveho
 * ucastnika overuje, ze vypnuta zbran nestrili ani neprebiji.
 */
function weaponMacro(r, id, wid) {
  const on = (step) => ({ op: 'weapon', id, weapon: wid, do: step });
  return {
    op: 'loop',
    count: 1,
    steps: [
      on({ op: 'tick', dtUs: r.int(0, 20000) }),
      on({ op: 'tick', dtUs: r.int(1, 900000), trigger: true }),
      on({ op: 'reload' }),
      on(withTrigger({ op: 'run', durationUs: r.int(1000000, 3200000), ticks: randMode(r) }, r.chance(0.3))),
    ],
  };
}

function respawnLikeStep(r, session, areas, respawnSys, extra) {
  const ids = respawnSys.order.map((p) => p.id);
  const anyId = () => (r.chance(0.05) || ids.length === 0 ? 'zz' : r.pick(ids));
  const x = r.int(0, 99);
  if (x < 14) return { op: 'kill', id: anyId() };
  if (x < 30) {
    const step = { op: 'damage', id: anyId(), amount: r.pick([r.int(1, 60), r.int(60, 150), 0, -3]) };
    const a = r.int(0, 9);
    if (a < 6) step.attacker = anyId();
    return step;
  }
  if (x < 62) {
    const step = { op: 'tick', dtUs: randDt(r, r.pick([1, 5])) };
    if (r.chance(0.5)) step.bodies = randBodies(r);
    if (r.chance(0.4)) step.blocked = randBlocked(r, areas);
    Object.assign(step, extra(r));
    return step;
  }
  if (x < 70) {
    const step = { op: 'run', durationUs: r.int(0, 6000000), ticks: randMode(r) };
    if (r.chance(0.3)) step.bodies = randBodies(r);
    if (r.chance(0.3)) step.blocked = randBlocked(r, areas);
    Object.assign(step, extra(r));
    return step;
  }
  if (x < 86 && ids.length > 0) {
    const p = respawnSys.participant(r.pick(ids));
    const wid = r.pick([...p.weapons.keys()]);
    if (r.chance(0.45)) return weaponMacro(r, p.id, wid);
    return { op: 'weapon', id: p.id, weapon: wid, do: randWeaponStep(r) };
  }
  if (x < 90 && ids.length > 0) {
    return { op: 'setLoadout', id: r.pick(ids), loadout: r.pick([['rifle_iv7', 'pistol_p9'], ['pistol_p9'], ['rifle_iv7'], ['pistol_p9', 'rifle_iv7'], ['knife']]) };
  }
  if (x < 94) return { op: 'add', id: r.chance(0.3) && ids.length ? r.pick(ids) : `n${r.int(1, 99)}`, team: r.int(-1, 3) };
  return null;
}

function genRespawnCase(r, baseRaw, index) {
  const areas = randSpawnAreas(r);
  const participants = [];
  ['a', 'b', 'c'].forEach((prefix, team) => {
    const n = r.int(1, 2);
    for (let k = 1; k <= n; k += 1) participants.push({ id: `${prefix}${k}`, team });
  });
  const rulesOverride = {
    respawn: {
      delay: r.pick([0, 0.5, 1.0, 2.5, 5.0]),
      retryInterval: r.pick([0.1, 0.25, 0.5, 1.0]),
      minEnemyDistance: r.pick([5, 10, 25]),
      bodyClearance: r.pick([0.5, 1, 2]),
    },
    combat: { friendlyFire: r.chance(0.3) },
  };
  const meta = { id: `FUZZ/respawn-${index}`, kind: 'respawn', rules: rulesOverride, setup: { seed: r.u32(), spawnAreas: areas, participants } };
  return buildCase(meta, baseRaw, 80, (session) => {
    const s = respawnLikeStep(r, session, areas, session.sys, () => ({}));
    return s ?? { op: 'resetRound' };
  });
}

function genMatchCase(r, baseRaw, index) {
  const areas = randSpawnAreas(r);
  const participants = [];
  ['a', 'b', 'c'].forEach((prefix, team) => {
    const n = r.int(1, 2);
    for (let k = 1; k <= n; k += 1) participants.push({ id: `${prefix}${k}`, team });
  });
  const rulesOverride = {
    round: { preRoundDuration: r.pick([0, 2.0]), timeLimit: r.pick([30.0, 60.0]), scoreTarget: r.int(3, 15) },
    respawn: { delay: r.pick([0.5, 2.0, 5.0]), retryInterval: r.pick([0.25, 0.5]) },
  };
  const meta = { id: `FUZZ/match-${index}`, kind: 'match', rules: rulesOverride, setup: { seed: r.u32(), spawnAreas: areas, participants } };
  const ids = participants.map((p) => p.id);
  const extra = (rr) => {
    const o = {};
    if (rr.chance(0.6)) o.inZone = rr.subset(ids, 0.4);
    if (rr.chance(0.2)) o.inactive = rr.subset(ids, 0.2);
    return o;
  };
  return buildCase(meta, baseRaw, 80, (session) => {
    const x = r.int(0, 99);
    if (x < 6) return { op: 'start' };
    if (x < 9) return { op: 'reset' };
    const s = respawnLikeStep(r, session, areas, session.sys.respawn, extra);
    if (s === null || s.op === 'setLoadout' || s.op === 'add') return { op: 'tick', dtUs: randDt(r), ...extra(r) };
    return s;
  });
}

// ------------------------------------------------------------------ soubory

function doc(suite, description, cases) {
  return { schema: 'ironvalley.testvectors', version: 1, suite, generated: true, generator: 'Web/tests/unit/support/fuzz_generator.mjs', masterSeed: FUZZ_MASTER_SEED, description, cases };
}

/** Vygeneruje vsechny fuzz soubory (deterministicky z FUZZ_MASTER_SEED). Vraci {nazevSouboru: dokument}. */
export function generateFuzzDocs(baseRaw) {
  const master = new R(FUZZ_MASTER_SEED);
  const sub = () => new R(master.u32());
  const make = (count, fn) => Array.from({ length: count }, (_, i) => fn(sub(), baseRaw, i));
  const note = 'VYGENEROVANO - needitovat rucne. Ocekavane hodnoty dopocitalo JS jadro; C++ je musi reprodukovat bit po bitu. Kazdy krok: result, events a snapshotDigest (FNV-1a 64 kanonickeho JSON celeho stavu); kazdy 10. a posledni krok i cely snapshot.';
  return {
    'fuzz_weapon.json': doc('fuzz_weapon', note, make(12, genWeaponCase)),
    'fuzz_zone.json': doc('fuzz_zone', note, make(6, genZoneCase)),
    'fuzz_round.json': doc('fuzz_round', note, make(6, genRoundCase)),
    'fuzz_respawn.json': doc('fuzz_respawn', note, make(6, genRespawnCase)),
    'fuzz_match.json': doc('fuzz_match', note, make(4, genMatchCase)),
  };
}

/** Serializace fuzz dokumentu: jeden krok na radek (citelne diffy, rozumna velikost). */
export function serializeFuzzDoc(d) {
  const head = { ...d };
  delete head.cases;
  const lines = [];
  lines.push('{');
  for (const [k, v] of Object.entries(head)) lines.push(`  ${JSON.stringify(k)}: ${JSON.stringify(v)},`);
  lines.push('  "cases": [');
  d.cases.forEach((c, ci) => {
    const { steps, ...rest } = c;
    lines.push('    {');
    for (const [k, v] of Object.entries(rest)) lines.push(`      ${JSON.stringify(k)}: ${JSON.stringify(v)},`);
    lines.push('      "steps": [');
    steps.forEach((s, si) => lines.push(`        ${JSON.stringify(s)}${si < steps.length - 1 ? ',' : ''}`));
    lines.push('      ]');
    lines.push(`    }${ci < d.cases.length - 1 ? ',' : ''}`);
  });
  lines.push('  ]');
  lines.push('}');
  return `${lines.join('\n')}\n`;
}
