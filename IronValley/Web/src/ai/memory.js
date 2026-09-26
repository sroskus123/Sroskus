// Per-bot memory of enemies (AI-01). An entry exists only because of a stimulus: the bot saw the enemy
// (own line-of-sight rays), heard it (gunshot / footstep event, approximate position) or was hit by it
// (approximate direction). The memory is NEVER refreshed from the enemy's true position without such a
// stimulus; between stimuli the entry keeps the last known position / time / velocity and its confidence
// decays until it is forgotten. Dead or respawned enemies are forgotten immediately.
//
// Entry: { id, team, pos (feet, Vector3), vel (Vector3, perceived), time (last update), conf 0..1,
//          source 'vision'|'glimpse'|'hearing'|'damage', seen (visible at the last perception update),
//          firstSeen, lastSeen, aimHeight (visible body point above the feet), searched, updates }

import { Vector3 } from 'three';

export class EnemyMemory {
  constructor(cfg) {
    this.cfg = cfg;
    this.entries = new Map();
    this.log = []; // last updates (debug / tests): { t, id, source, pos }
  }

  get size() {
    return this.entries.size;
  }

  get(id) {
    return this.entries.get(id) || null;
  }

  clear() {
    this.entries.clear();
  }

  forget(id) {
    this.entries.delete(id);
  }

  _entry(id, team, t) {
    let e = this.entries.get(id);
    if (!e) {
      e = { id, team, pos: new Vector3(), vel: new Vector3(), time: t, conf: 0, source: 'none', seen: false, firstSeen: -1, lastSeen: -1, aimHeight: 1.3, searched: false, searching: false, updates: 0, created: t };
      this.entries.set(id, e);
    }
    return e;
  }

  _log(t, id, source, pos) {
    this.log.push({ t: +t.toFixed(3), id, source, pos: [+pos.x.toFixed(2), +pos.y.toFixed(2), +pos.z.toFixed(2)] });
    if (this.log.length > 60) this.log.shift();
  }

  /** Visual confirmation at time t: observed feet position, perceived velocity, visible aim height. */
  see(id, team, t, feet, vel, aimHeight) {
    const e = this._entry(id, team, t);
    const wasSeen = e.seen && t - e.lastSeen < 0.35;
    e.pos.copy(feet);
    if (vel) e.vel.copy(vel);
    else e.vel.set(0, 0, 0);
    if (!wasSeen) e.firstSeen = t;
    e.time = t;
    e.lastSeen = t;
    e.conf = 1;
    e.source = 'vision';
    e.seen = true;
    e.searched = false;
    e.aimHeight = aimHeight;
    e.updates++;
    this._log(t, id, 'vision', feet);
    return e;
  }

  /** Partial detection: approximate position (already with error), low confidence. */
  glimpse(id, team, t, approxFeet, conf) {
    const e = this._entry(id, team, t);
    if (e.seen && t - e.lastSeen < 0.5) return e; // a fresh sighting is better information
    if (e.conf > conf && t - e.time < 1.0) return e;
    e.pos.copy(approxFeet);
    e.vel.set(0, 0, 0);
    e.time = t;
    e.conf = Math.max(e.conf * 0.5, conf);
    e.source = 'glimpse';
    e.searched = false;
    e.updates++;
    this._log(t, id, 'glimpse', approxFeet);
    return e;
  }

  /** Sound: approximate position (already with error). Does not override a recent sighting. */
  hear(id, team, t, approxFeet, conf) {
    const e = this._entry(id, team, t);
    if (e.seen && t - e.lastSeen < 1.0) return e;
    // a closer / more confident recent stimulus is kept; otherwise blend towards the new estimate
    if (e.updates > 0 && t - e.time < 0.6 && e.conf > conf) return e;
    if (e.updates > 0 && e.source === 'hearing' && t - e.time < 3) e.pos.lerp(approxFeet, 0.6);
    else e.pos.copy(approxFeet);
    e.vel.set(0, 0, 0);
    e.time = t;
    e.conf = Math.max(e.conf, conf);
    e.source = 'hearing';
    e.searched = false;
    e.updates++;
    this._log(t, id, 'hearing', e.pos);
    return e;
  }

  /** Being hit: direction known (approximately), distance guessed unless an estimate already exists. */
  damage(id, team, t, approxFeet, conf, { keepPosition = false } = {}) {
    const e = this._entry(id, team, t);
    if (e.seen && t - e.lastSeen < 0.5) return e;
    if (!keepPosition || e.updates === 0) e.pos.copy(approxFeet);
    e.vel.set(0, 0, 0);
    e.time = t;
    e.conf = Math.max(e.conf, conf);
    e.source = 'damage';
    e.searched = false;
    e.updates++;
    this._log(t, id, 'damage', e.pos);
    return e;
  }

  /** Marks entries not seen in this perception pass as not visible. */
  markUnseen(id) {
    const e = this.entries.get(id);
    if (e) e.seen = false;
  }

  /** Confidence decay; entries at 0 are forgotten. */
  decay(dt) {
    for (const [id, e] of this.entries) {
      if (e.seen) continue;
      const T = e.source === 'vision' ? this.cfg.memory.decayTimeSeen : this.cfg.memory.decayTimeHeard;
      // an entry the bot is actively searching decays slower: the search has its own time budget
      e.conf -= (dt / Math.max(T, 0.1)) * (e.searching ? this.cfg.memory.searchingDecayFactor ?? 0.25 : 1);
      if (e.conf <= 0) this.entries.delete(id);
    }
  }

  /** Position estimate: last known + perceived velocity extrapolated for a short time (no new data). */
  predicted(e, t, out = new Vector3()) {
    const dt = Math.min(Math.max(0, t - e.time), this.cfg.memory.velocityExtrapolation);
    return out.copy(e.pos).addScaledVector(e.vel, dt);
  }

  snapshot(t) {
    return [...this.entries.values()].map((e) => ({
      id: e.id,
      team: e.team,
      pos: [+e.pos.x.toFixed(3), +e.pos.y.toFixed(3), +e.pos.z.toFixed(3)],
      vel: [+e.vel.x.toFixed(2), +e.vel.y.toFixed(2), +e.vel.z.toFixed(2)],
      time: +e.time.toFixed(3),
      age: +(t - e.time).toFixed(3),
      conf: +e.conf.toFixed(3),
      source: e.source,
      seen: e.seen,
      lastSeen: +e.lastSeen.toFixed(3),
      searched: e.searched,
      updates: e.updates,
    }));
  }
}
