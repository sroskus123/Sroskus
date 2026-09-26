// Nacteni a kontrola Shared/config/rules.json. Vystup = "zkompilovana" pravidla s casy v celych mikrosekundach.
// Stejne kontroly (platne/neplatne) provadi C++ (Core/src/rules.cpp + Core/json/rules_json.cpp); shodu overuje
// Shared/testvectors/rules.json.

import { secondsToMicros } from './time.js';

export const FIRE_MODES = Object.freeze(['semi', 'auto']);

export class RulesError extends Error {
  constructor(errors) {
    super(`Neplatna pravidla: ${errors.join('; ')}`);
    this.name = 'RulesError';
    this.errors = errors;
  }
}

/**
 * JSON Merge Patch (RFC 7386): objekty se slucuji rekurzivne, null klic odstrani, vse ostatni nahradi.
 * Pouziva se pro prepisy pravidel v testovacich vektorech i pro ladici nastaveni.
 */
export function mergePatch(target, patch) {
  if (patch === null || typeof patch !== 'object' || Array.isArray(patch)) return clone(patch);
  const base = target !== null && typeof target === 'object' && !Array.isArray(target) ? clone(target) : {};
  for (const [key, value] of Object.entries(patch)) {
    if (value === null) delete base[key];
    else base[key] = mergePatch(base[key], value);
  }
  return base;
}

function clone(v) {
  return v === undefined ? undefined : JSON.parse(JSON.stringify(v));
}

function isObj(v) {
  return v !== null && typeof v === 'object' && !Array.isArray(v);
}

class Checker {
  constructor() {
    this.errors = [];
  }

  fail(path, msg) {
    this.errors.push(`${path}: ${msg}`);
    return undefined;
  }

  obj(parent, key, path) {
    const v = isObj(parent) ? parent[key] : undefined;
    if (!isObj(v)) return this.fail(path, 'ocekavan objekt');
    return v;
  }

  num(parent, key, path, min, max, { minExclusive = false } = {}) {
    const v = isObj(parent) ? parent[key] : undefined;
    if (typeof v !== 'number' || !Number.isFinite(v)) return this.fail(path, 'ocekavano cislo');
    if (minExclusive ? !(v > min) : !(v >= min)) return this.fail(path, `musi byt ${minExclusive ? '>' : '>='} ${min}`);
    if (!(v <= max)) return this.fail(path, `musi byt <= ${max}`);
    return v;
  }

  int(parent, key, path, min, max) {
    const v = isObj(parent) ? parent[key] : undefined;
    if (typeof v !== 'number' || !Number.isInteger(v)) return this.fail(path, 'ocekavano cele cislo');
    if (v < min || v > max) return this.fail(path, `musi byt v rozsahu ${min}..${max}`);
    return v;
  }

  bool(parent, key, path) {
    const v = isObj(parent) ? parent[key] : undefined;
    if (typeof v !== 'boolean') return this.fail(path, 'ocekavana logicka hodnota');
    return v;
  }

  str(parent, key, path, { allowEmpty = false } = {}) {
    const v = isObj(parent) ? parent[key] : undefined;
    if (typeof v !== 'string' || (!allowEmpty && v.length === 0)) return this.fail(path, 'ocekavan neprazdny text');
    return v;
  }

  idList(parent, key, path, minLen, maxLen) {
    const v = isObj(parent) ? parent[key] : undefined;
    if (!Array.isArray(v)) return this.fail(path, 'ocekavano pole');
    if (v.length < minLen || v.length > maxLen) return this.fail(path, `delka musi byt ${minLen}..${maxLen}`);
    const out = [];
    const seen = new Set();
    v.forEach((item, i) => {
      const id = this.str(item, 'id', `${path}[${i}].id`);
      const name = this.str(item, 'name', `${path}[${i}].name`, { allowEmpty: true });
      if (id !== undefined) {
        if (seen.has(id)) this.fail(`${path}[${i}].id`, `duplicitni id "${id}"`);
        seen.add(id);
      }
      out.push({ id, name });
    });
    return out;
  }
}

const LIMIT_SECONDS = 86400;

function compileWeapon(c, id, raw, path) {
  if (!isObj(raw)) return c.fail(path, 'ocekavan objekt');
  const w = { id };
  w.name = c.str(raw, 'name', `${path}.name`, { allowEmpty: true });
  w.slot = c.str(raw, 'slot', `${path}.slot`);
  w.magazineCapacity = c.int(raw, 'magazineCapacity', `${path}.magazineCapacity`, 1, 1000);
  w.hasChamber = c.bool(raw, 'hasChamber', `${path}.hasChamber`);
  w.startReserve = c.int(raw, 'startReserve', `${path}.startReserve`, 0, 1000000);
  w.maxReserve = c.int(raw, 'maxReserve', `${path}.maxReserve`, 0, 1000000);
  if (w.startReserve !== undefined && w.maxReserve !== undefined && w.startReserve > w.maxReserve) {
    c.fail(`${path}.startReserve`, 'nesmi byt vetsi nez maxReserve');
  }
  const rpm = c.num(raw, 'roundsPerMinute', `${path}.roundsPerMinute`, 0, 100000, { minExclusive: true });
  if (rpm !== undefined) {
    w.fireIntervalUs = secondsToMicros(60 / rpm);
    if (w.fireIntervalUs < 1) c.fail(`${path}.roundsPerMinute`, 'palebny interval je kratsi nez 1 us');
  }
  const modes = raw.fireModes;
  if (!Array.isArray(modes) || modes.length === 0) {
    c.fail(`${path}.fireModes`, 'ocekavano neprazdne pole');
  } else {
    const seen = new Set();
    for (const m of modes) {
      if (!FIRE_MODES.includes(m)) c.fail(`${path}.fireModes`, `neznamy rezim "${m}"`);
      else if (seen.has(m)) c.fail(`${path}.fireModes`, `duplicitni rezim "${m}"`);
      seen.add(m);
    }
    w.fireModes = modes.slice();
  }
  w.defaultFireMode = c.str(raw, 'defaultFireMode', `${path}.defaultFireMode`);
  if (w.defaultFireMode !== undefined && Array.isArray(modes) && !modes.includes(w.defaultFireMode)) {
    c.fail(`${path}.defaultFireMode`, 'musi byt jednim z fireModes');
  }
  w.damage = c.int(raw, 'damage', `${path}.damage`, 0, 1000000);

  const reload = c.obj(raw, 'reload', `${path}.reload`);
  const tac = c.obj(reload, 'tactical', `${path}.reload.tactical`);
  const emp = c.obj(reload, 'empty', `${path}.reload.empty`);
  w.tactical = { durationUs: 0, insertUs: 0 };
  w.empty = { durationUs: 0, insertUs: 0, boltUs: 0 };
  w.chamber = { durationUs: 0, commitUs: 0 };
  if (tac) {
    const d = c.num(tac, 'duration', `${path}.reload.tactical.duration`, 0, 60, { minExclusive: true });
    const ins = c.num(tac, 'insertCommit', `${path}.reload.tactical.insertCommit`, 0, 60);
    if (d !== undefined && ins !== undefined) {
      w.tactical = { durationUs: secondsToMicros(d), insertUs: secondsToMicros(ins) };
      if (w.tactical.insertUs > w.tactical.durationUs) c.fail(`${path}.reload.tactical.insertCommit`, 'musi byt <= duration');
    }
  }
  if (emp) {
    const d = c.num(emp, 'duration', `${path}.reload.empty.duration`, 0, 60, { minExclusive: true });
    const ins = c.num(emp, 'insertCommit', `${path}.reload.empty.insertCommit`, 0, 60);
    let bolt = 0;
    if (w.hasChamber === true) bolt = c.num(emp, 'boltRelease', `${path}.reload.empty.boltRelease`, 0, 60);
    if (d !== undefined && ins !== undefined && bolt !== undefined) {
      w.empty = {
        durationUs: secondsToMicros(d),
        insertUs: secondsToMicros(ins),
        boltUs: w.hasChamber === true ? secondsToMicros(bolt) : 0,
      };
      if (w.empty.insertUs > w.empty.durationUs) c.fail(`${path}.reload.empty.insertCommit`, 'musi byt <= duration');
      if (w.hasChamber === true) {
        if (w.empty.boltUs < w.empty.insertUs) c.fail(`${path}.reload.empty.boltRelease`, 'musi byt >= insertCommit');
        if (w.empty.boltUs > w.empty.durationUs) c.fail(`${path}.reload.empty.boltRelease`, 'musi byt <= duration');
      }
    }
  }
  if (w.hasChamber === true) {
    const ch = c.obj(reload, 'chamber', `${path}.reload.chamber`);
    if (ch) {
      const d = c.num(ch, 'duration', `${path}.reload.chamber.duration`, 0, 60, { minExclusive: true });
      const cm = c.num(ch, 'commit', `${path}.reload.chamber.commit`, 0, 60);
      if (d !== undefined && cm !== undefined) {
        w.chamber = { durationUs: secondsToMicros(d), commitUs: secondsToMicros(cm) };
        if (w.chamber.commitUs > w.chamber.durationUs) c.fail(`${path}.reload.chamber.commit`, 'musi byt <= duration');
      }
    }
  }
  return w;
}

/** Vrati seznam chyb (prazdny = platna pravidla). */
export function validateRules(raw) {
  return compileInternal(raw).errors;
}

/** Zkontroluje a zkompiluje pravidla; pri chybe vyhodi RulesError. Vysledek je zmrazeny. */
export function compileRules(raw) {
  const { errors, rules } = compileInternal(raw);
  if (errors.length > 0) throw new RulesError(errors);
  return deepFreeze(rules);
}

function compileInternal(raw) {
  const c = new Checker();
  const r = {};
  if (!isObj(raw)) {
    c.fail('$', 'ocekavan objekt');
    return { errors: c.errors, rules: r };
  }
  const teams = c.obj(raw, 'teams', 'teams');
  r.teamCount = c.int(teams, 'count', 'teams.count', 2, 8);
  r.teamSize = c.int(teams, 'size', 'teams.size', 1, 64);
  r.teams = teams ? c.idList(teams, 'list', 'teams.list', 1, 8) : undefined;
  if (r.teams && r.teamCount !== undefined && r.teams.length !== r.teamCount) {
    c.fail('teams.list', 'pocet polozek musi odpovidat teams.count');
  }

  const round = c.obj(raw, 'round', 'round');
  const pre = c.num(round, 'preRoundDuration', 'round.preRoundDuration', 0, LIMIT_SECONDS);
  const limit = c.num(round, 'timeLimit', 'round.timeLimit', 0, LIMIT_SECONDS, { minExclusive: true });
  r.round = {
    preRoundUs: pre === undefined ? undefined : secondsToMicros(pre),
    timeLimitUs: limit === undefined ? undefined : secondsToMicros(limit),
    scoreTarget: c.int(round, 'scoreTarget', 'round.scoreTarget', 1, 1000000),
  };
  if (r.round.timeLimitUs !== undefined && r.round.timeLimitUs < 1) c.fail('round.timeLimit', 'musi byt alespon 1 us');

  const zone = c.obj(raw, 'zone', 'zone');
  const interval = c.num(zone, 'pointInterval', 'zone.pointInterval', 0, LIMIT_SECONDS, { minExclusive: true });
  r.zone = {
    pointIntervalUs: interval === undefined ? undefined : secondsToMicros(interval),
    pointsPerAward: c.int(zone, 'pointsPerAward', 'zone.pointsPerAward', 1, 1000000),
    locations: zone ? c.idList(zone, 'locations', 'zone.locations', 1, 16) : undefined,
  };
  if (r.zone.pointIntervalUs !== undefined && r.zone.pointIntervalUs < 1) c.fail('zone.pointInterval', 'musi byt alespon 1 us');

  const resp = c.obj(raw, 'respawn', 'respawn');
  const delay = c.num(resp, 'delay', 'respawn.delay', 0, LIMIT_SECONDS);
  const retry = c.num(resp, 'retryInterval', 'respawn.retryInterval', 0, LIMIT_SECONDS, { minExclusive: true });
  r.respawn = {
    delayUs: delay === undefined ? undefined : secondsToMicros(delay),
    retryIntervalUs: retry === undefined ? undefined : secondsToMicros(retry),
    minEnemyDistance: c.num(resp, 'minEnemyDistance', 'respawn.minEnemyDistance', 0, 10000),
    bodyClearance: c.num(resp, 'bodyClearance', 'respawn.bodyClearance', 0, 100),
  };
  if (r.respawn.retryIntervalUs !== undefined && r.respawn.retryIntervalUs < 1) c.fail('respawn.retryInterval', 'musi byt alespon 1 us');

  const combat = c.obj(raw, 'combat', 'combat');
  r.combat = {
    maxHealth: c.int(combat, 'maxHealth', 'combat.maxHealth', 1, 1000000),
    friendlyFire: c.bool(combat, 'friendlyFire', 'combat.friendlyFire'),
  };

  const weapons = c.obj(raw, 'weapons', 'weapons');
  r.weapons = {};
  if (weapons) {
    const ids = Object.keys(weapons);
    if (ids.length === 0) c.fail('weapons', 'alespon jedna zbran');
    for (const id of ids) {
      if (id.length === 0) {
        c.fail('weapons', 'prazdne id zbrane');
        continue;
      }
      r.weapons[id] = compileWeapon(c, id, weapons[id], `weapons.${id}`);
    }
  }

  const loadout = c.obj(raw, 'loadout', 'loadout');
  r.loadout = { default: [] };
  if (loadout) {
    const list = loadout.default;
    if (!Array.isArray(list) || list.length === 0) {
      c.fail('loadout.default', 'ocekavano neprazdne pole');
    } else {
      const seen = new Set();
      for (const wid of list) {
        if (typeof wid !== 'string' || !Object.hasOwn(r.weapons, wid)) c.fail('loadout.default', `neznama zbran "${wid}"`);
        else if (seen.has(wid)) c.fail('loadout.default', `duplicitni zbran "${wid}"`);
        seen.add(wid);
      }
      r.loadout.default = list.slice();
    }
  }
  return { errors: c.errors, rules: r };
}

function deepFreeze(o) {
  if (o && typeof o === 'object') {
    Object.freeze(o);
    for (const v of Object.values(o)) deepFreeze(v);
  }
  return o;
}

/** Kanonicka podoba zkompilovanych pravidel (pro porovnani JS a C++ ve vektorech). */
export function rulesSnapshot(rules) {
  return JSON.parse(JSON.stringify(rules));
}
