// Zivotni cyklus ucastnika: alive -> dead -> respawning -> alive, vyber bezpecneho spawnu, zdravi, vybava.
// Pravidla: Docs/RULES.md, oddil "Respawn". C++: Core/src/respawn.cpp.

import { assertDtMicros } from './time.js';
import { Rng } from './rng.js';
import { WeaponState, DISABLE_REASONS, LIFE_LOCK } from './weapon.js';

/**
 * Referencni cast predikatu spawnu, kterou lze spocitat bez enginu: bod nesmi byt blize nez
 * minEnemyDistance k zivemu nepriteli ani blize nez bodyClearance k jakemukoli zivemu telu.
 * Viditelnost nepritelem a kolize s geometrii kontroluje engine (raycast / overlap) ve svem predikatu.
 * @param point [x, y, z]
 * @param team tym spawnujiciho
 * @param bodies [{team, alive, pos: [x, y, z]}]
 */
export function spawnPointSafe(point, team, bodies, respawnRules) {
  const enemy2 = respawnRules.minEnemyDistance * respawnRules.minEnemyDistance;
  const body2 = respawnRules.bodyClearance * respawnRules.bodyClearance;
  for (const b of bodies) {
    if (!b.alive) continue;
    const dx = b.pos[0] - point[0];
    const dy = b.pos[1] - point[1];
    const dz = b.pos[2] - point[2];
    const d2 = dx * dx + dy * dy + dz * dz;
    if (b.team !== team && d2 < enemy2) return false;
    if (d2 < body2) return false;
  }
  return true;
}

function validPoint(p) {
  return Array.isArray(p) && p.length === 3 && p.every((x) => typeof x === 'number' && Number.isFinite(x));
}

export class RespawnSystem {
  /**
   * @param rules zkompilovana pravidla
   * @param options {seed, spawnAreas}: spawnAreas[team] = pole kandidatnich bodu [x, y, z]
   */
  constructor(rules, { seed = 1, spawnAreas } = {}) {
    this.rules = rules;
    if (!Array.isArray(spawnAreas) || spawnAreas.length !== rules.teamCount) {
      throw new RangeError('RespawnSystem: spawnAreas musi mit jednu oblast pro kazdy tym');
    }
    spawnAreas.forEach((area, t) => {
      if (!Array.isArray(area) || area.length === 0 || !area.every(validPoint)) {
        throw new RangeError(`RespawnSystem: spawnova oblast tymu ${t} musi mit alespon jeden platny bod [x,y,z]`);
      }
    });
    this.spawnAreas = spawnAreas.map((area) => area.map((p) => p.slice()));
    // Rezervace bodu: kolik mikrosekund jeste bod po spawnu nelze nabidnout (casovy rozsah, ne rozsah jednoho update,
    // takze vysledek nezavisi na deleni casu na tiky). Delka rezervace = respawn.retryInterval (Docs/RULES.md, oddil 5).
    this.reservedUs = this.spawnAreas.map((area) => area.map(() => 0));
    this.rng = new Rng(seed >>> 0);
    this.order = [];
    this.byId = new Map();
    this.outbox = [];
  }

  validLoadout(loadout) {
    if (!Array.isArray(loadout) || loadout.length === 0) return false;
    const seen = new Set();
    for (const w of loadout) {
      if (typeof w !== 'string' || !Object.hasOwn(this.rules.weapons, w) || seen.has(w)) return false;
      seen.add(w);
    }
    return true;
  }

  /** Prida ucastnika; ceka na prvni spawn (stav respawning, pokus hned pri dalsim update). */
  addParticipant(id, team, loadout = null) {
    if (typeof id !== 'string' || id.length === 0) return 'invalid_id';
    if (this.byId.has(id)) return 'duplicate_id';
    if (!Number.isInteger(team) || team < 0 || team >= this.rules.teamCount) return 'invalid_team';
    const lo = loadout ?? this.rules.loadout.default;
    if (!this.validLoadout(lo)) return 'invalid_loadout';
    let members = 0;
    for (const p of this.order) if (p.team === team) members += 1;
    if (members >= this.rules.teamSize) return 'team_full';
    // weapons = prave vybavene zbrane (poradi loadoutu); armory = vsechny zbrane, ktere ucastnik kdy dostal.
    // Objekty v armory se nikdy nenahrazuji, takze reference drzena enginem plati po celou dobu zivota systemu.
    // inputLocks = zamky vstupu enginu na urovni ucastnika (menu, vysledky ...); plati pro vsechny jeho zbrane.
    const p = { id, team, loadout: lo.slice(), weapons: new Map(), armory: new Map(), inputLocks: new Set() };
    this.resetParticipant(p);
    this.order.push(p);
    this.byId.set(id, p);
    return 'ok';
  }

  resetParticipant(p) {
    p.state = 'respawning';
    p.health = 0;
    p.respawnInUs = 0;
    p.retryInUs = 0;
    p.spawnPoint = -1;
    p.spawnCount = 0;
    p.deaths = 0;
    p.failedSpawnAttempts = 0;
    this.rebuildWeapons(p);
  }

  /**
   * Vybava podle loadoutu v plnem vychozim stavu, vsechny zbrane se zamkem zivota (odemkne je az spawn).
   * Existujici objekty zbrani se resetuji na miste (reference v enginu zustavaji platne); zbran odebrana z vybavy
   * zustava v armory zamcena, takze ani stara reference nemuze strilet. Nova zbran prevezme zamky vstupu ucastnika.
   */
  rebuildWeapons(p) {
    for (const w of p.armory.values()) w[LIFE_LOCK](true, 'other');
    p.weapons = new Map();
    for (const wid of p.loadout) {
      let w = p.armory.get(wid);
      if (!w) {
        w = new WeaponState(this.rules.weapons[wid]);
        w[LIFE_LOCK](true, 'other');
        for (const reason of p.inputLocks) w.disable(reason);
        p.armory.set(wid, w);
      }
      w.resetToLoadout();
      p.weapons.set(wid, w);
    }
  }

  participant(id) {
    return this.byId.get(id) ?? null;
  }

  weapon(id, weaponId) {
    const p = this.byId.get(id);
    return p ? p.weapons.get(weaponId) ?? null : null;
  }

  isAlive(id) {
    const p = this.byId.get(id);
    return !!p && p.state === 'alive';
  }

  /**
   * Zamek vstupu enginu pro vsechny zbrane ucastnika (i ty, ktere dostane pozdeji): menu, vysledkova obrazovka ...
   * Kazdy duvod je samostatny; respawn, reset kola ani zmena vybavy ho nezrusi, odebere ho jen enableInput.
   */
  disableInput(id, reason) {
    const p = this.byId.get(id);
    if (!p) return 'unknown_id';
    if (!DISABLE_REASONS.includes(reason)) return 'invalid_reason';
    p.inputLocks.add(reason);
    for (const w of p.armory.values()) w.disable(reason);
    return 'ok';
  }

  /** Odebere zamek vstupu s timto duvodem; zamek zivota (mrtvy ucastnik) ani jine duvody tim nezmizi. */
  enableInput(id, reason) {
    const p = this.byId.get(id);
    if (!p) return 'unknown_id';
    if (!DISABLE_REASONS.includes(reason)) return 'invalid_reason';
    p.inputLocks.delete(reason);
    for (const w of p.armory.values()) w.enable(reason);
    return 'ok';
  }

  /** Zmena vybavy; projevi se pri pristim spawnu. */
  setLoadout(id, loadout) {
    const p = this.byId.get(id);
    if (!p) return 'unknown_id';
    if (!this.validLoadout(loadout)) return 'invalid_loadout';
    p.loadout = loadout.slice();
    return 'ok';
  }

  /** Smrt: zdravi 0, odpocet respawnu, zamek zivota na vsech zbranich (prerusi prebijeni s duvodem death). */
  kill(id) {
    const p = this.byId.get(id);
    if (!p) return 'unknown_id';
    if (p.state !== 'alive') return 'not_alive';
    p.state = 'dead';
    p.health = 0;
    p.respawnInUs = this.rules.respawn.delayUs;
    p.retryInUs = 0;
    p.deaths += 1;
    for (const w of p.weapons.values()) w[LIFE_LOCK](true, 'death');
    this.outbox.push({ type: 'killed', id, point: -1 });
    return 'killed';
  }

  /**
   * Poskozeni (cele cislo). attackerId = null pro prostredi. Friendly fire podle pravidel.
   * Vraci {result, applied}: result = applied | killed | blocked_friendly_fire | not_alive | invalid_amount | unknown_id.
   */
  applyDamage(victimId, amount, attackerId = null) {
    const v = this.byId.get(victimId);
    if (!v) return { result: 'unknown_id', applied: 0 };
    let attacker = null;
    if (attackerId !== null && attackerId !== undefined) {
      attacker = this.byId.get(attackerId);
      if (!attacker) return { result: 'unknown_id', applied: 0 };
    }
    if (!Number.isSafeInteger(amount) || amount <= 0) return { result: 'invalid_amount', applied: 0 };
    if (v.state !== 'alive') return { result: 'not_alive', applied: 0 };
    if (attacker && attacker !== v && attacker.team === v.team && !this.rules.combat.friendlyFire) {
      return { result: 'blocked_friendly_fire', applied: 0 };
    }
    const applied = Math.min(amount, v.health);
    v.health -= applied;
    if (v.health === 0) {
      this.kill(victimId);
      return { result: 'killed', applied };
    }
    return { result: 'applied', applied };
  }

  /**
   * Posun casu. predicate(query) -> bool rozhoduje, zda je kandidatni bod bezpecny
   * (query = {participantId, team, candidateIndex, point}). Bez predikatu jsou vsechny body bezpecne.
   * Pokusy o spawn probehnou v presnych okamzicich uvnitr tiku (konec odpoctu, konec retryInterval), takze vysledek
   * nezavisi na tom, jak je stejny cas rozdelen na tiky. Ucastnici se stejnym okamzikem jdou v poradi pridani.
   * Bod pouzity pro spawn je rezervovany po dobu retryInterval (i pres hranice update), pak rozhoduje predikat.
   */
  update(dtUs, predicate = null) {
    assertDtMicros(dtUs);
    this.advance(0, predicate);
    let remaining = dtUs;
    while (remaining > 0) {
      const step = Math.min(remaining, this.nextAttemptInUs());
      this.advance(step, predicate);
      remaining -= step;
    }
  }

  /**
   * Za kolik mikrosekund probehne nejblizsi pokus o spawn (0 = ted), Infinity = nikdo neceka.
   * Match podle toho deli tik, aby oblast pocitala respawnuteho presne od okamziku spawnu.
   */
  nextAttemptInUs() {
    let best = Number.POSITIVE_INFINITY;
    for (const p of this.order) {
      if (p.state === 'dead') best = Math.min(best, p.respawnInUs);
      else if (p.state === 'respawning') best = Math.min(best, p.retryInUs);
    }
    return best;
  }

  /**
   * Jeden usek casu bez deleni: odpocty i rezervace bodu klesnou o dtUs a kdo dosahne nuly, zkusi se spawnovat
   * na konci useku. Volajici zajisti dtUs <= nextAttemptInUs() (update a Match to delaji), jinak by se pokus opozdil.
   */
  advance(dtUs, predicate = null) {
    assertDtMicros(dtUs);
    if (dtUs > 0) {
      for (const area of this.reservedUs) {
        for (let i = 0; i < area.length; i += 1) area[i] = area[i] > dtUs ? area[i] - dtUs : 0;
      }
    }
    for (const p of this.order) {
      let attempt = false;
      if (p.state === 'dead') {
        p.respawnInUs = p.respawnInUs > dtUs ? p.respawnInUs - dtUs : 0;
        if (p.respawnInUs > 0) continue;
        p.state = 'respawning';
        p.retryInUs = 0;
        attempt = true;
      } else if (p.state === 'respawning') {
        p.retryInUs = p.retryInUs > dtUs ? p.retryInUs - dtUs : 0;
        attempt = p.retryInUs === 0;
      }
      if (attempt) this.trySpawn(p, predicate);
    }
  }

  trySpawn(p, predicate) {
    const area = this.spawnAreas[p.team];
    const reserved = this.reservedUs[p.team];
    const order = this.rng.shuffledIndices(area.length);
    for (const idx of order) {
      if (reserved[idx] > 0) continue;
      const point = area[idx];
      const ok = predicate ? predicate({ participantId: p.id, team: p.team, candidateIndex: idx, point }) === true : true;
      if (!ok) continue;
      reserved[idx] = this.rules.respawn.retryIntervalUs;
      p.state = 'alive';
      p.health = this.rules.combat.maxHealth;
      p.respawnInUs = 0;
      p.retryInUs = 0;
      p.spawnPoint = idx;
      p.spawnCount += 1;
      this.rebuildWeapons(p);
      for (const w of p.weapons.values()) w[LIFE_LOCK](false);
      this.outbox.push({ type: 'spawned', id: p.id, point: idx });
      return true;
    }
    p.failedSpawnAttempts += 1;
    p.retryInUs = this.rules.respawn.retryIntervalUs;
    this.outbox.push({ type: 'spawn_blocked', id: p.id, point: -1 });
    return false;
  }

  /**
   * Nove kolo: vsichni cekaji na okamzity spawn, vsechny odpocty, rezervace bodu a stav zbrani zruseny, citace
   * vynulovany, zbrane se zamkem zivota. Zamky vstupu enginu (menu, vysledky) zustavaji - odebere je jen engine.
   */
  resetRound() {
    for (const area of this.reservedUs) area.fill(0);
    for (const p of this.order) this.resetParticipant(p);
    this.outbox = [];
    return 'ok';
  }

  takeEvents() {
    const out = this.outbox;
    this.outbox = [];
    return out;
  }

  snapshot() {
    const participants = {};
    for (const p of this.order) {
      const weapons = {};
      for (const [wid, w] of p.weapons) weapons[wid] = w.snapshot();
      participants[p.id] = {
        team: p.team,
        state: p.state,
        health: p.health,
        respawnInUs: p.respawnInUs,
        retryInUs: p.retryInUs,
        spawnPoint: p.spawnPoint,
        spawnCount: p.spawnCount,
        deaths: p.deaths,
        failedSpawnAttempts: p.failedSpawnAttempts,
        loadout: p.loadout.slice(),
        equipped: [...p.weapons.keys()],
        inputLocks: DISABLE_REASONS.filter((r) => p.inputLocks.has(r)),
        weapons,
      };
    }
    return { order: this.order.map((p) => p.id), participants, reservedUs: this.reservedUs.map((a) => a.slice()) };
  }
}
