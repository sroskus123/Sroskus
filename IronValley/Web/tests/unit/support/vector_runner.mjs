// Spoustec sdilenych testovacich vektoru (Shared/testvectors/*.json) nad JS jadrem.
// Presne stejnou semantiku ma C++ spoustec Core/tests/vector_runner.cpp. Format: Shared/testvectors/README.md.

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  compileRules,
  validateRules,
  mergePatch,
  rulesSnapshot,
  Rng,
  WeaponState,
  weaponInvariantViolations,
  ZoneScoring,
  Round,
  RespawnSystem,
  spawnPointSafe,
  Match,
} from '../../../src/core/index.js';
import { intDiv } from '../../../src/core/zone.js';

const here = path.dirname(fileURLToPath(import.meta.url));
export const PROJECT_ROOT = path.resolve(here, '../../../..');
export const RULES_PATH = path.join(PROJECT_ROOT, 'Shared/config/rules.json');
export const VECTORS_DIR = path.join(PROJECT_ROOT, 'Shared/testvectors');

export function loadBaseRules() {
  return JSON.parse(fs.readFileSync(RULES_PATH, 'utf8'));
}

export function listVectorFiles() {
  return fs
    .readdirSync(VECTORS_DIR)
    .filter((f) => f.endsWith('.json'))
    .sort()
    .map((f) => path.join(VECTORS_DIR, f));
}

export function loadVectorFile(file) {
  return JSON.parse(fs.readFileSync(file, 'utf8'));
}

// ---------------------------------------------------------------- tiky

/** Rozlozi durationUs na tiky podle rezimu {hz} | {dtUs} | {irregular:{seed,minUs,maxUs}}. */
export function expandTicks(durationUs, mode, irregularRng) {
  if (!Number.isSafeInteger(durationUs) || durationUs < 0) throw new Error(`run: neplatne durationUs ${durationUs}`);
  const out = [];
  let prev = 0;
  if (mode && mode.hz !== undefined) {
    const hz = mode.hz;
    if (!Number.isInteger(hz) || hz < 1) throw new Error('run: hz musi byt cele >= 1');
    for (let k = 1; prev < durationUs; k += 1) {
      let t = intDiv(2 * k * 1000000 + hz, 2 * hz);
      if (t > durationUs) t = durationUs;
      out.push(t - prev);
      prev = t;
    }
  } else if (mode && mode.dtUs !== undefined) {
    if (!Number.isInteger(mode.dtUs) || mode.dtUs < 1) throw new Error('run: dtUs musi byt cele >= 1');
    while (prev < durationUs) {
      const t = Math.min(prev + mode.dtUs, durationUs);
      out.push(t - prev);
      prev = t;
    }
  } else if (mode && mode.irregular !== undefined) {
    const { minUs, maxUs } = mode.irregular;
    if (!Number.isInteger(minUs) || !Number.isInteger(maxUs) || minUs < 0 || maxUs < 1 || maxUs < minUs) {
      throw new Error('run: neplatne irregular minUs/maxUs');
    }
    while (prev < durationUs) {
      const dt = minUs + irregularRng.pickIndex(maxUs - minUs + 1);
      const t = Math.min(prev + dt, durationUs);
      out.push(t - prev);
      prev = t;
    }
  } else {
    throw new Error(`run: neznamy rezim tiku ${JSON.stringify(mode)}`);
  }
  return out;
}

// ---------------------------------------------------------------- porovnani

export function subsetMismatches(expected, actual, where = '$') {
  if (expected === null || typeof expected !== 'object') {
    return expected === actual ? [] : [`${where}: ocekavano ${JSON.stringify(expected)}, je ${JSON.stringify(actual)}`];
  }
  if (Array.isArray(expected)) {
    if (!Array.isArray(actual)) return [`${where}: ocekavano pole, je ${JSON.stringify(actual)}`];
    if (actual.length !== expected.length) return [`${where}: delka ${expected.length} != ${actual.length} (${JSON.stringify(actual)})`];
    return expected.flatMap((e, i) => subsetMismatches(e, actual[i], `${where}[${i}]`));
  }
  if (actual === null || typeof actual !== 'object' || Array.isArray(actual)) {
    return [`${where}: ocekavan objekt, je ${JSON.stringify(actual)}`];
  }
  return Object.keys(expected).flatMap((k) => subsetMismatches(expected[k], actual[k], `${where}.${k}`));
}

export function exactMismatches(expected, actual, where = '$') {
  if (expected === null || typeof expected !== 'object' || actual === null || typeof actual !== 'object') {
    return expected === actual ? [] : [`${where}: ocekavano ${JSON.stringify(expected)}, je ${JSON.stringify(actual)}`];
  }
  if (Array.isArray(expected) !== Array.isArray(actual)) return [`${where}: typ se lisi`];
  const ek = Object.keys(expected).sort();
  const ak = Object.keys(actual).sort();
  if (JSON.stringify(ek) !== JSON.stringify(ak)) return [`${where}: klice ${JSON.stringify(ek)} != ${JSON.stringify(ak)}`];
  return ek.flatMap((k) => exactMismatches(expected[k], actual[k], `${where}.${k}`));
}

/** Kanonicky JSON: klice serazene, bez mezer. C++ ma shodnou serializaci (nlohmann::json s std::map, dump()). */
export function canonicalJson(v) {
  if (v === null || typeof v !== 'object') return JSON.stringify(v);
  if (Array.isArray(v)) return `[${v.map(canonicalJson).join(',')}]`;
  return `{${Object.keys(v)
    .sort()
    .map((k) => `${JSON.stringify(k)}:${canonicalJson(v[k])}`)
    .join(',')}}`;
}

/** FNV-1a 64bit nad UTF-8 bajty kanonickeho JSON, jako 16 hex znaku. */
export function snapshotDigest(v) {
  const bytes = new TextEncoder().encode(canonicalJson(v));
  let h = 0xcbf29ce484222325n;
  for (const b of bytes) {
    h ^= BigInt(b);
    h = (h * 0x100000001b3n) & 0xffffffffffffffffn;
  }
  return h.toString(16).padStart(16, '0');
}

const RESERVED_EXPECT_KEYS = new Set(['result', 'events', 'eventCounts', 'snapshot', 'snapshotDigest']);

export function checkExpect(expect, out) {
  const problems = [];
  if (!expect) return problems;
  if ('result' in expect) problems.push(...exactMismatches(expect.result, out.result, 'result'));
  if ('events' in expect) problems.push(...exactMismatches(expect.events, out.events, 'events'));
  if ('eventCounts' in expect) {
    const counts = {};
    for (const e of out.events) counts[e.type] = (counts[e.type] ?? 0) + 1;
    for (const [type, n] of Object.entries(expect.eventCounts)) {
      if ((counts[type] ?? 0) !== n) problems.push(`eventCounts.${type}: ocekavano ${n}, je ${counts[type] ?? 0}`);
    }
  }
  if ('snapshot' in expect) problems.push(...exactMismatches(expect.snapshot, out.snapshot, 'snapshot'));
  if ('snapshotDigest' in expect) {
    const d = snapshotDigest(out.snapshot);
    if (d !== expect.snapshotDigest) problems.push(`snapshotDigest: ocekavano ${expect.snapshotDigest}, je ${d} (${canonicalJson(out.snapshot)})`);
  }
  const subset = {};
  for (const [k, v] of Object.entries(expect)) if (!RESERVED_EXPECT_KEYS.has(k)) subset[k] = v;
  problems.push(...subsetMismatches(subset, out.snapshot, 'snapshot'));
  return problems;
}

// ---------------------------------------------------------------- kontrola tvaru vektoru
// Neznamy nebo spatne umisteny klic (preklep "expcet", "expect" uvnitr "do" nebo "loop", "trigger": "true") by se
// jinak tise ignoroval a pripad by prosel naprazdno. Oba spoustece proto tvar kontroluji stejne a odmitnou ho
// chybou pripadu. C++: Core/tests/vector_runner.cpp (validateCaseShape, validateStep).

export class CaseError extends Error {}

export const FILE_KEYS = new Set(['schema', 'version', 'suite', 'description', 'cases', 'generated', 'generator', 'masterSeed']);
const CASE_KEYS = new Set(['id', 'kind', 'description', 'rules', 'setup', 'tickModes', 'steps']);
const SETUP_KEYS = {
  weapon: ['weapon', 'magazine', 'chamber', 'reserve', 'fireMode'],
  zone: [],
  round: ['seed'],
  respawn: ['seed', 'spawnAreas', 'participants'],
  match: ['seed', 'spawnAreas', 'participants'],
  rng: ['seed'],
  rules: [],
};
const SETUP_PARTICIPANT_KEYS = new Set(['id', 'team', 'loadout']);
const WEAPON_OPS = {
  tick: ['dtUs', 'trigger', 'repeat'],
  run: ['durationUs', 'trigger', 'ticks'],
  reload: [],
  interrupt: ['reason'],
  disable: ['reason'],
  enable: ['reason'],
  setFireMode: ['mode'],
  resupply: ['rounds'],
  resetToLoadout: [],
};
const ZONE_OPS = { tick: ['dtUs', 'participants', 'repeat'], run: ['durationUs', 'ticks', 'participants'], reset: [] };
const LIFE_OPS = {
  add: ['id', 'team', 'loadout'],
  kill: ['id'],
  damage: ['id', 'amount', 'attacker'],
  setLoadout: ['id', 'loadout'],
  weapon: ['id', 'weapon', 'do'],
  weaponEvents: ['id', 'weapon'],
  disableInput: ['id', 'reason'],
  enableInput: ['id', 'reason'],
};
const OPS = {
  weapon: WEAPON_OPS,
  zone: ZONE_OPS,
  round: { ...ZONE_OPS, start: [] },
  respawn: { ...LIFE_OPS, tick: ['dtUs', 'repeat', 'bodies', 'blocked'], run: ['durationUs', 'ticks', 'bodies', 'blocked'], resetRound: [] },
  match: {
    ...LIFE_OPS,
    tick: ['dtUs', 'repeat', 'bodies', 'blocked', 'inZone', 'inactive'],
    run: ['durationUs', 'ticks', 'bodies', 'blocked', 'inZone', 'inactive'],
    reset: [],
    start: [],
  },
  rules: { compile: ['overrides'] },
  rng: { next: ['count'], pick: ['n', 'count'], shuffle: ['n'] },
};

const isPlainObject = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);
const isBool = (v) => typeof v === 'boolean';

// Klic s hodnotou undefined (jen v pripadech sestavenych v JS, JSON ho neumi) se bere jako chybejici.
const has = (obj, k) => obj[k] !== undefined;

function checkKeys(obj, allowed, where) {
  for (const k of Object.keys(obj)) if (has(obj, k) && !allowed.has(k)) throw new CaseError(`${where}: neznamy klic "${k}"`);
}

function checkTickMode(mode, where) {
  if (!isPlainObject(mode)) throw new CaseError(`${where}: rezim tiku musi byt objekt`);
  const keys = Object.keys(mode);
  if (keys.length !== 1 || !['hz', 'dtUs', 'irregular'].includes(keys[0])) {
    throw new CaseError(`${where}: rezim tiku musi mit prave jeden klic hz | dtUs | irregular, ma ${JSON.stringify(keys)}`);
  }
  if (keys[0] === 'irregular') {
    if (!isPlainObject(mode.irregular)) throw new CaseError(`${where}: irregular musi byt objekt`);
    checkKeys(mode.irregular, new Set(['seed', 'minUs', 'maxUs']), `${where}.irregular`);
  }
}

function checkZoneParticipant(p, where) {
  if (Array.isArray(p)) {
    if (p.length !== 5 || typeof p[0] !== 'string' || !Number.isInteger(p[1]) || !isBool(p[2]) || !isBool(p[3]) || !isBool(p[4])) {
      throw new CaseError(`${where}: ucastnik musi byt [id, tym, alive, active, inZone] (text, cele cislo, 3x bool), je ${JSON.stringify(p)}`);
    }
    return;
  }
  if (!isPlainObject(p)) throw new CaseError(`${where}: ucastnik musi byt pole nebo objekt`);
  checkKeys(p, new Set(['id', 'team', 'alive', 'active', 'inZone']), where);
  if (typeof p.id !== 'string' || !Number.isInteger(p.team) || !isBool(p.alive) || !isBool(p.active) || !isBool(p.inZone)) {
    throw new CaseError(`${where}: ucastnik ma spatne typy ${JSON.stringify(p)}`);
  }
}

/** Kontrola tvaru pripadu (klice pripadu, setup, tickModes). Kroky kontroluje validateStep pri provadeni. */
export function validateCaseShape(testCase) {
  if (!isPlainObject(testCase)) throw new CaseError('pripad musi byt objekt');
  const where = `pripad ${testCase.id ?? '?'}`;
  checkKeys(testCase, CASE_KEYS, where);
  if (typeof testCase.id !== 'string' || testCase.id.length === 0) throw new CaseError(`${where}: chybi id`);
  if (!Object.hasOwn(SETUP_KEYS, testCase.kind)) throw new CaseError(`${where}: neznamy druh "${testCase.kind}"`);
  if (!Array.isArray(testCase.steps)) throw new CaseError(`${where}: steps musi byt pole`);
  if (has(testCase, 'rules') && !isPlainObject(testCase.rules)) throw new CaseError(`${where}: rules musi byt objekt`);
  if (has(testCase, 'setup')) {
    if (!isPlainObject(testCase.setup)) throw new CaseError(`${where}: setup musi byt objekt`);
    checkKeys(testCase.setup, new Set(SETUP_KEYS[testCase.kind]), `${where}.setup`);
    for (const [i, p] of (testCase.setup.participants ?? []).entries()) {
      if (!isPlainObject(p)) throw new CaseError(`${where}.setup.participants[${i}]: ocekavan objekt`);
      checkKeys(p, SETUP_PARTICIPANT_KEYS, `${where}.setup.participants[${i}]`);
    }
  }
  if (has(testCase, 'tickModes')) {
    if (!Array.isArray(testCase.tickModes) || testCase.tickModes.length === 0) throw new CaseError(`${where}: tickModes musi byt neprazdne pole`);
    testCase.tickModes.forEach((m, i) => checkTickMode(m, `${where}.tickModes[${i}]`));
  }
}

/**
 * Kontrola tvaru kroku pro dany druh. nested = krok uvnitr "loop" nebo "do" (tam se ocekavani nekontroluje,
 * proto je "expect" zakazane).
 */
export function validateStep(kind, step, where, nested = false) {
  if (!isPlainObject(step)) throw new CaseError(`${where}: krok musi byt objekt`);
  if (typeof step.op !== 'string') throw new CaseError(`${where}: chybi op`);
  const table = OPS[kind];
  let allowed;
  if (step.op === 'loop') allowed = ['count', 'steps'];
  else if (Object.hasOwn(table, step.op)) allowed = table[step.op];
  else throw new CaseError(`${where}: neznama operace "${step.op}" pro ${kind}`);
  const keys = new Set(['op', ...allowed]);
  if (!nested) keys.add('expect');
  for (const k of Object.keys(step)) {
    if (keys.has(k) || !has(step, k)) continue;
    if (k === 'expect') throw new CaseError(`${where}: "expect" uvnitr vnoreneho kroku (loop/do) se nekontroluje - patri do vnejsiho kroku`);
    throw new CaseError(`${where}: neznamy klic "${k}" v operaci ${step.op}`);
  }
  if (has(step, 'expect') && !isPlainObject(step.expect)) throw new CaseError(`${where}: expect musi byt objekt`);
  if (has(step, 'trigger') && !isBool(step.trigger)) throw new CaseError(`${where}: trigger musi byt true/false, je ${JSON.stringify(step.trigger)}`);
  if (has(step, 'repeat') && !(Number.isInteger(step.repeat) && step.repeat >= 0)) throw new CaseError(`${where}: repeat musi byt cele >= 0`);
  if (has(step, 'ticks') && step.ticks !== 'case') checkTickMode(step.ticks, `${where}.ticks`);
  if (has(step, 'participants')) {
    if (!Array.isArray(step.participants)) throw new CaseError(`${where}: participants musi byt pole`);
    step.participants.forEach((p, i) => checkZoneParticipant(p, `${where}.participants[${i}]`));
  }
  if (has(step, 'bodies')) {
    if (!Array.isArray(step.bodies)) throw new CaseError(`${where}: bodies musi byt pole`);
    step.bodies.forEach((b, i) => {
      const w = `${where}.bodies[${i}]`;
      if (!isPlainObject(b)) throw new CaseError(`${w}: ocekavan objekt`);
      checkKeys(b, new Set(['team', 'alive', 'pos']), w);
      const posOk = Array.isArray(b.pos) && b.pos.length === 3 && b.pos.every((x) => typeof x === 'number');
      if (!Number.isInteger(b.team) || !isBool(b.alive) || !posOk) throw new CaseError(`${w}: {team: cele, alive: bool, pos: [x,y,z]}, je ${JSON.stringify(b)}`);
    });
  }
  if (has(step, 'blocked')) {
    if (!isPlainObject(step.blocked)) throw new CaseError(`${where}: blocked musi byt objekt {tym: [indexy]}`);
    for (const [t, list] of Object.entries(step.blocked)) {
      if (!Array.isArray(list) || !list.every(Number.isInteger)) throw new CaseError(`${where}: blocked.${t} musi byt pole celych cisel`);
    }
  }
  for (const key of ['inZone', 'inactive']) {
    if (has(step, key) && !(Array.isArray(step[key]) && step[key].every((x) => typeof x === 'string'))) {
      throw new CaseError(`${where}: ${key} musi byt pole id`);
    }
  }
  if (step.op === 'loop') {
    if (!Number.isInteger(step.count) || step.count < 0 || !Array.isArray(step.steps)) throw new CaseError(`${where}: loop {count: cele >= 0, steps: []}`);
    step.steps.forEach((inner, i) => validateStep(kind, inner, `${where}.steps[${i}]`, true));
  }
  if (step.op === 'weapon' && (kind === 'respawn' || kind === 'match')) {
    if (!isPlainObject(step.do) || step.do.op === 'loop') throw new CaseError(`${where}: do musi byt jeden krok zbrane`);
    validateStep('weapon', step.do, `${where}.do`, true);
  }
}

// ---------------------------------------------------------------- spousteni

function participantsList(v) {
  return v ?? [];
}

function makePredicate(world, rules) {
  const blocked = world.blocked ?? {};
  const bodies = world.bodies ?? [];
  return (q) => {
    const list = blocked[String(q.team)] ?? [];
    if (list.includes(q.candidateIndex)) return false;
    return spawnPointSafe(q.point, q.team, bodies, rules.respawn);
  };
}

function invariantCheck(problems, label, w) {
  for (const v of weaponInvariantViolations(w.snapshot(), w.def)) problems.push(`${label}: invariant: ${v}`);
}

function allWeaponsInvariant(problems, label, respawn) {
  // Vsechny zbrane, ktere ucastnik kdy dostal (i ty mimo aktualni vybavu).
  for (const p of respawn.order) for (const [wid, w] of p.armory) invariantCheck(problems, `${label} ${p.id}/${wid}`, w);
}

/** Provede jeden krok nad zbrani (sdileno druhem weapon a operaci "weapon" v respawn/match). */
function weaponStep(w, step, ctx, problems, label) {
  switch (step.op) {
    case 'tick': {
      const reps = step.repeat ?? 1;
      let shots = 0;
      for (let i = 0; i < reps; i += 1) {
        shots += w.update(step.dtUs, step.trigger === true);
        invariantCheck(problems, label, w);
      }
      return shots;
    }
    case 'run': {
      const mode = step.ticks === 'case' ? ctx.mode : step.ticks;
      if (!mode) throw new CaseError('run: "ticks":"case" bez tickModes');
      let shots = 0;
      for (const dt of expandTicks(step.durationUs, mode, ctx.irregularRng(mode))) {
        shots += w.update(dt, step.trigger === true);
        invariantCheck(problems, label, w);
      }
      return shots;
    }
    case 'reload':
      return w.reload();
    case 'interrupt':
      return w.interrupt(step.reason);
    case 'disable':
      return w.disable(step.reason);
    case 'enable':
      return w.enable(step.reason);
    case 'setFireMode':
      return w.setFireMode(step.mode);
    case 'resupply':
      return w.resupply(step.rounds);
    case 'resetToLoadout':
      w.resetToLoadout();
      return 'ok';
    default:
      throw new CaseError(`neznama operace zbrane "${step.op}"`);
  }
}

function runTicks(step, ctx, fn) {
  // Spolecna obsluha tick(repeat) / run pro druhy zone, round, respawn, match. Vraci prvni chybu nebo 'ok'.
  let result = 'ok';
  const dts = [];
  if (step.op === 'tick') {
    const reps = step.repeat ?? 1;
    for (let i = 0; i < reps; i += 1) dts.push(step.dtUs);
  } else {
    const mode = step.ticks === 'case' ? ctx.mode : step.ticks;
    if (!mode) throw new CaseError('run: "ticks":"case" bez tickModes');
    dts.push(...expandTicks(step.durationUs, mode, ctx.irregularRng(mode)));
  }
  for (const dt of dts) {
    const r = fn(dt);
    if (r !== 'ok' && result === 'ok') result = r;
  }
  return result;
}

function makeSystem(kind, rules, setup) {
  switch (kind) {
    case 'weapon': {
      const def = rules.weapons[setup.weapon];
      if (!def) throw new CaseError(`neznama zbran ${setup.weapon}`);
      const w = new WeaponState(def);
      if (setup.magazine !== undefined || setup.chamber !== undefined || setup.reserve !== undefined) {
        if (w.setAmmo({ magazine: setup.magazine, chamber: setup.chamber, reserve: setup.reserve }) !== 'ok') {
          throw new CaseError('setup: neplatny stav munice');
        }
      }
      if (setup.fireMode !== undefined && w.setFireMode(setup.fireMode) !== 'ok') throw new CaseError('setup: neplatny fireMode');
      return w;
    }
    case 'zone':
      return new ZoneScoring(rules);
    case 'round':
      return new Round(rules, setup.seed ?? 1);
    case 'respawn':
    case 'match': {
      const sys =
        kind === 'respawn'
          ? new RespawnSystem(rules, { seed: setup.seed ?? 1, spawnAreas: setup.spawnAreas })
          : new Match(rules, { seed: setup.seed ?? 1, spawnAreas: setup.spawnAreas });
      for (const p of setup.participants ?? []) {
        const r = sys.addParticipant(p.id, p.team, p.loadout ?? null);
        if (r !== 'ok') throw new CaseError(`setup: pridani ${p.id} selhalo: ${r}`);
      }
      return sys;
    }
    case 'rng':
      return new Rng(setup.seed ?? 0);
    case 'rules':
      return null;
    default:
      throw new CaseError(`neznamy druh "${kind}"`);
  }
}

function snapshotOf(kind, sys, ctx) {
  switch (kind) {
    case 'rng':
      return { state: sys.state };
    case 'rules':
      return ctx.lastCompiled ?? {};
    default:
      return sys.snapshot();
  }
}

function doStep(kind, sys, step, ctx, rules, problems, nested = false) {
  const world = ctx.world;
  if (!nested) validateStep(kind, step, `krok ${step?.op ?? '?'}`);
  if (step.op === 'loop') {
    // Genericke opakovani vnorenych kroku (bez kontrol uvnitr). Udalosti se spojuji, vysledek je "ok".
    const events = [];
    for (let i = 0; i < step.count; i += 1) {
      for (const inner of step.steps) events.push(...doStep(kind, sys, inner, ctx, rules, problems, true).events);
    }
    return { result: 'ok', events };
  }
  switch (kind) {
    case 'weapon': {
      const result = weaponStep(sys, step, ctx, problems, 'weapon');
      return { result, events: sys.takeEvents() };
    }
    case 'zone':
    case 'round': {
      if (step.op === 'tick' || step.op === 'run') {
        if ('participants' in step) world.participants = participantsList(step.participants);
        const result = runTicks(step, ctx, (dt) => sys.tick(dt, world.participants));
        return { result, events: [] };
      }
      if (step.op === 'reset') return { result: sys.reset() ?? 'ok', events: [] };
      if (kind === 'round' && step.op === 'start') return { result: sys.start(), events: [] };
      throw new CaseError(`neznama operace "${step.op}" pro ${kind}`);
    }
    case 'respawn':
    case 'match': {
      const respawn = kind === 'respawn' ? sys : sys.respawn;
      let result;
      let events = null;
      switch (step.op) {
        case 'add':
          result = sys.addParticipant(step.id, step.team, step.loadout ?? null);
          break;
        case 'kill':
          result = sys.kill(step.id);
          break;
        case 'damage': {
          const r = sys.applyDamage(step.id, step.amount, step.attacker ?? null);
          result = { result: r.result, applied: r.applied };
          break;
        }
        case 'setLoadout':
          result = respawn.setLoadout(step.id, step.loadout);
          break;
        case 'tick':
        case 'run': {
          for (const key of ['bodies', 'blocked', 'inZone', 'inactive']) if (key in step) world[key] = step[key];
          const predicate = makePredicate(world, rules);
          result = runTicks(step, ctx, (dt) => {
            if (kind === 'respawn') {
              sys.update(dt, predicate);
              return 'ok';
            }
            return sys.update(dt, { inZone: world.inZone ?? [], inactive: world.inactive ?? [], predicate });
          });
          break;
        }
        case 'resetRound':
          if (kind !== 'respawn') throw new CaseError('resetRound jen pro respawn');
          result = sys.resetRound();
          break;
        case 'reset':
          if (kind !== 'match') throw new CaseError('reset jen pro match');
          result = sys.reset();
          break;
        case 'start':
          if (kind !== 'match') throw new CaseError('start jen pro match');
          result = sys.start();
          break;
        case 'weapon': {
          const w = respawn.weapon(step.id, step.weapon);
          if (!w) throw new CaseError(`zbran ${step.id}/${step.weapon} neexistuje`);
          w.takeEvents();
          result = weaponStep(w, step.do, ctx, problems, `${step.id}/${step.weapon}`);
          events = w.takeEvents();
          break;
        }
        case 'weaponEvents': {
          // Udalosti, ktere zbran nashromazdila od posledniho kroku "weapon" (napr. preruseni pri resetu nebo smrti).
          const w = respawn.weapon(step.id, step.weapon);
          if (!w) throw new CaseError(`zbran ${step.id}/${step.weapon} neexistuje`);
          result = 'ok';
          events = w.takeEvents();
          break;
        }
        case 'disableInput':
          result = sys.disableInput(step.id, step.reason);
          break;
        case 'enableInput':
          result = sys.enableInput(step.id, step.reason);
          break;
        default:
          throw new CaseError(`neznama operace "${step.op}" pro ${kind}`);
      }
      const sysEvents = respawn.takeEvents();
      allWeaponsInvariant(problems, 'po kroku', respawn);
      return { result, events: events ?? sysEvents };
    }
    case 'rng': {
      if (step.op === 'next') return { result: Array.from({ length: step.count }, () => sys.nextU32()), events: [] };
      if (step.op === 'pick') return { result: Array.from({ length: step.count }, () => sys.pickIndex(step.n)), events: [] };
      if (step.op === 'shuffle') return { result: sys.shuffledIndices(step.n), events: [] };
      throw new CaseError(`neznama operace "${step.op}" pro rng`);
    }
    case 'rules': {
      if (step.op !== 'compile') throw new CaseError(`neznama operace "${step.op}" pro rules`);
      const raw = mergePatch(ctx.caseRaw, step.overrides ?? {});
      const errors = validateRules(raw);
      if (errors.length === 0) {
        ctx.lastCompiled = rulesSnapshot(compileRules(raw));
        return { result: 'valid', events: [] };
      }
      ctx.lastCompiled = {};
      return { result: 'invalid', events: [] };
    }
    default:
      throw new CaseError(`neznamy druh "${kind}"`);
  }
}

/**
 * Inkrementalni provadeni pripadu (pouziva ho executeCase i generator fuzz vektoru, ktery potrebuje
 * zivy stav, aby generoval jen platne akce). step(stepObj) vrati {result, events, snapshot, problems}.
 */
export class CaseSession {
  constructor(testCase, baseRaw, mode = null) {
    validateCaseShape(testCase);
    this.kind = testCase.kind;
    const raw = mergePatch(baseRaw, testCase.rules ?? {});
    this.rules = this.kind === 'rules' ? null : compileRules(raw);
    const irregularRngs = new Map();
    this.ctx = {
      mode,
      baseRaw,
      caseRaw: raw,
      lastCompiled: null,
      world: { participants: [] },
      irregularRng(m) {
        if (!m || m.irregular === undefined) return null;
        const key = canonicalJson(m);
        if (!irregularRngs.has(key)) irregularRngs.set(key, new Rng(m.irregular.seed >>> 0));
        return irregularRngs.get(key);
      },
    };
    this.sys = makeSystem(this.kind, this.rules, testCase.setup ?? {});
  }

  step(stepObj) {
    const problems = [];
    const out = doStep(this.kind, this.sys, stepObj, this.ctx, this.rules, problems);
    out.snapshot = snapshotOf(this.kind, this.sys, this.ctx);
    out.problems = problems;
    return out;
  }
}

/**
 * Provede pripad v jednom rezimu tiku. onStep(index, out) dostane {result, events, snapshot}.
 * Vraci seznam problemu (invarianty); vyjimky konfigurace pripadu propadnou.
 */
export function executeCase(testCase, baseRaw, mode, onStep) {
  const problems = [];
  const session = new CaseSession(testCase, baseRaw, mode);
  testCase.steps.forEach((step, i) => {
    const out = session.step(step);
    for (const p of out.problems) problems.push(`krok ${i} (${step.op}): ${p}`);
    onStep(i, out);
  });
  return problems;
}

/** Spusti pripad ve vsech rezimech a porovna s ocekavanim. Vraci seznam selhani (prazdny = PASS). */
export function checkCase(testCase, baseRaw) {
  const modes = testCase.tickModes ?? [null];
  const failures = [];
  for (const mode of modes) {
    const label = mode ? ` [ticks ${JSON.stringify(mode)}]` : '';
    const problems = executeCase(testCase, baseRaw, mode, (i, out) => {
      const step = testCase.steps[i];
      for (const p of checkExpect(step.expect, out)) failures.push(`krok ${i} (${step.op})${label}: ${p}`);
    });
    for (const p of problems) failures.push(`${label} ${p}`);
  }
  return failures;
}
