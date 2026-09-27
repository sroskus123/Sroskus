// Tenka fasada zapasu: kolo (oblast, skore, cas) + respawn system (zivoty, spawny, vybava).
// Tik se deli v okamzicich pokusu o spawn: pro kazdy usek se oblast vyhodnoti se stavem zivota na jeho zacatku,
// respawny probehnou na jeho konci. Ucastnik se tak v oblasti pocita presne od okamziku spawnu a body nezavisi
// na delce tiku (Docs/RULES.md, oddil 7 a R13). C++: Core/src/match.cpp.

import { assertDtMicros } from './time.js';
import { Round } from './round.js';
import { RespawnSystem } from './respawn.js';
import { deriveSeed, SPAWN_SEED_SALT } from './rng.js';

export class Match {
  /**
   * @param rules zkompilovana pravidla
   * @param options {seed, spawnAreas}; semeno spawnu = seed XOR 0x9E3779B9
   */
  constructor(rules, { seed = 1, spawnAreas } = {}) {
    this.rules = rules;
    this.round = new Round(rules, seed);
    this.respawn = new RespawnSystem(rules, { seed: deriveSeed(seed, SPAWN_SEED_SALT), spawnAreas });
  }

  get state() {
    return this.round.state;
  }

  addParticipant(id, team, loadout = null) {
    return this.respawn.addParticipant(id, team, loadout);
  }

  start() {
    return this.round.start();
  }

  kill(id) {
    if (this.round.state === 'ended') return 'round_ended';
    return this.respawn.kill(id);
  }

  applyDamage(victimId, amount, attackerId = null) {
    if (this.round.state === 'ended') return { result: 'round_ended', applied: 0 };
    return this.respawn.applyDamage(victimId, amount, attackerId);
  }

  /** Zamek vstupu enginu (menu, vysledkova obrazovka ...) pro vsechny zbrane ucastnika; plati i ve stavu ended. */
  disableInput(id, reason) {
    return this.respawn.disableInput(id, reason);
  }

  enableInput(id, reason) {
    return this.respawn.enableInput(id, reason);
  }

  /**
   * @param world {inZone: Set|Array id, inactive: Set|Array id, predicate(query) -> bool}
   * Vstupy sveta plati po cely tik. Vraci 'ok' (ve stavu ended se nic nedeje; respawny i skore stoji).
   */
  update(dtUs, world = {}) {
    assertDtMicros(dtUs);
    if (this.round.state === 'ended') return 'ok';
    const inZone = toSet(world.inZone);
    const inactive = toSet(world.inactive);
    const predicate = world.predicate ?? null;
    this.respawn.advance(0, predicate); // kdo ma spawn ted (novy ucastnik, po resetu), pocita se od zacatku
    let remaining = dtUs;
    do {
      const step = Math.min(remaining, this.respawn.nextAttemptInUs());
      const pre0 = this.round.preRoundRemainingUs;
      const elapsed0 = this.round.elapsedUs;
      const r = this.round.tick(step, this.zoneParticipants(inZone, inactive));
      if (r !== 'ok') return r;
      // Kolo mohlo skoncit uprostred useku (cil nebo casovy limit): odpocty respawnu i rezervace bodu dobehnou jen
      // do okamziku konce, pak stoji.
      const used = pre0 - this.round.preRoundRemainingUs + (this.round.elapsedUs - elapsed0);
      this.respawn.advance(used, predicate);
      remaining -= step;
    } while (remaining > 0 && this.round.state !== 'ended');
    return 'ok';
  }

  zoneParticipants(inZone, inactive) {
    return this.respawn.order.map((p) => ({
      id: p.id,
      team: p.team,
      alive: p.state === 'alive',
      active: !inactive.has(p.id),
      inZone: inZone.has(p.id),
    }));
  }

  /** Nove kolo: skore, oblast, casovace, odpocty respawnu i stav zbrani se vynuluji. */
  reset() {
    this.round.reset();
    this.respawn.resetRound();
    return 'ok';
  }

  snapshot() {
    return { round: this.round.snapshot(), respawn: this.respawn.snapshot() };
  }
}

function toSet(v) {
  if (v instanceof Set) return v;
  return new Set(Array.isArray(v) ? v : []);
}
