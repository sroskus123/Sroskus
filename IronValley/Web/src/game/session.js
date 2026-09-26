// MatchSession: one match (or free practice) on one level. Owns the authoritative Match (rules core),
// the combatants (player + bots), the world query, the AI system and the test dummies, and advances them
// on the fixed tick. DOM-free and three.js-render-free, so the complete round logic (spawns, damage,
// deaths, respawns, zone scoring, round end, reset) runs identically in Node unit tests and in the game.
//
// Tick order:  zone presence -> Match.update (respawns at their exact instants, zone scoring, round clock)
//              -> player.applyCommand -> ai.update (bots' applyCommand) -> idle step for undriven
//              combatants -> dummies. Damage goes through Match.applyDamage the moment a round hits.

import { Vector3 } from 'three';
import { Match } from '../core/match.js';
import { TickClock } from '../core/time.js';
import { CombatantManager } from './combatants.js';
import { WorldQuery } from './worldQuery.js';
import { TargetDummies } from './targetDummies.js';
import { buildMatchRules } from './gameRules.js';
import { createRng } from '../util/rng.js';

export const PLAYER_ID = 'player';

function mixSeed(seed, k) {
  let h = (seed >>> 0) ^ Math.imul(k + 1, 0x9e3779b1);
  h = Math.imul(h ^ (h >>> 16), 0x85ebca6b);
  h = Math.imul(h ^ (h >>> 13), 0xc2b2ae35);
  return (h ^ (h >>> 16)) >>> 0;
}

export class MatchSession {
  /**
   * @param {object} o
   * @param {object} o.level        level JSON (with a `match` block for mode 'match')
   * @param {object} o.world        CollisionWorld of the level
   * @param {object} o.movement     movement.json
   * @param {object} o.weaponsData  weapons.json
   * @param {object} o.combat       combat.json
   * @param {object} o.teams        teams.json
   * @param {object} o.events       EventBus
   * @param {Function} o.createAISystem  createAISystem from src/ai/index.js
   * @param {'match'|'practice'} [o.mode]
   * @param {number} [o.seed]
   * @param {number[]} [o.bots]     bots per team [t0 (besides the player), t1, t2]
   * @param {boolean} [o.withPlayer]
   * @param {object} [o.rulesPatch] JSON merge patch over rules.json (tests only)
   * @param {object} [o.aiConfig]   extra config handed to the AI system
   * @param {object} [o.loadout]    { optic }
   */
  constructor(o) {
    this.level = o.level;
    this.mode = o.mode || 'match';
    this.seed = (o.seed ?? 1) >>> 0;
    this.events = o.events;
    this.movement = o.movement;
    this.combat = o.combat;
    this.teamsData = o.teams;
    this.weaponsData = o.weaponsData;
    this.withPlayer = o.withPlayer !== false;
    this.loadout = { optic: (o.loadout && o.loadout.optic) || 'collimator' };
    this.rules = buildMatchRules(this.mode === 'match' ? this.level : null, o.rulesPatch || null);
    this.teamCount = this.rules.teamCount;

    // spawn points per team (practice: the player's marker only; other teams get a far point, unused)
    const lm = this.level.match;
    if (this.mode === 'match') {
      if (!lm) throw new Error(`Úroveň ${this.level.id} nemá zápasová data (match)`);
      this.spawns = lm.teamSpawns.map((list) => list.map((s) => ({ pos: s.pos.slice(), yaw: s.yaw ?? 0 })));
      this.zones = lm.zones.map((z) => ({ ...z }));
    } else {
      const mk = this.level.markers[(lm && lm.practiceSpawn) || 'spawn'] || { pos: [0, 0, 0], yaw: 0 };
      this.spawns = [];
      for (let t = 0; t < this.teamCount; t++) this.spawns.push(t === 0 ? [{ pos: mk.pos.slice(), yaw: mk.yaw ?? 0 }] : [{ pos: [0, -500, 0], yaw: 0 }]);
      this.zones = [];
    }
    if (this.spawns.length !== this.teamCount) throw new Error(`teamSpawns: ${this.spawns.length} týmů, pravidla mají ${this.teamCount}`);
    this.match = new Match(this.rules, { seed: this.seed, spawnAreas: this.spawns.map((l) => l.map((s) => s.pos)) });

    this.clock = new TickClock();
    this.tickCount = 0;
    this.simTime = 0;
    this.lastDtUs = 0;
    this.dummies = new TargetDummies(this.level.dummies || []);
    this.pendingKills = new Map();
    this.stats = { ffBlocked: 0, damageEvents: 0, shotsHitCombatants: 0 };
    this.killFeed = [];
    this.aiEnabled = true;

    const session = this;
    this.ctx = {
      world: o.world,
      movement: o.movement,
      match: this.match,
      rules: this.rules,
      weaponsData: o.weaponsData,
      combat: o.combat,
      events: o.events,
      worldQuery: null,
      dummies: this.dummies,
      rng: (k) => createRng(mixSeed(session.seed, k)),
      damageSink: (shooter, hit, amount, shot) => session.applyShotDamage(shooter, hit, amount, shot),
      tick: () => session.tickCount,
      time: () => session.simTime,
      dtUs: () => session.lastDtUs,
    };
    this.combatants = new CombatantManager({ ctx: this.ctx, spawns: this.spawns });
    this.worldQuery = new WorldQuery({ world: o.world, combatants: this.combatants, dummies: this.dummies });
    this.ctx.worldQuery = this.worldQuery;

    // roster: the player (team 0) + bots
    const names = o.teams.botNames || [];
    const bots = (o.bots || o.teams.defaultBots || [0, 0, 0]).slice(0, this.teamCount);
    while (bots.length < this.teamCount) bots.push(0);
    if (this.withPlayer) this.combatants.add({ id: PLAYER_ID, team: o.teams.playerTeam ?? 0, isPlayer: true, name: o.teams.playerName || 'Ty' });
    for (let t = 0; t < this.teamCount; t++) {
      const maxBots = this.rules.teamSize - (this.withPlayer && t === (o.teams.playerTeam ?? 0) ? 1 : 0);
      const n = Math.max(0, Math.min(bots[t] | 0, maxBots));
      for (let i = 0; i < n; i++) {
        const name = (names[t] && names[t][i]) || `Bot ${t + 1}-${i + 1}`;
        this.combatants.add({ id: `bot_${t}_${i}`, team: t, name });
      }
    }
    this.botCounts = [0, 1, 2].slice(0, this.teamCount).map((t) => this.combatants.byTeam(t).filter((c) => !c.isPlayer).length);

    // AI (stub until the AI module replaces src/ai/index.js with the same interface)
    this.ai = o.createAISystem({
      combatants: this.combatants,
      world: this.worldQuery,
      nav: null,
      cover: null,
      events: o.events,
      match: this.match,
      config: { levelId: this.level.id, level: this.level, rules: this.rules, zones: this.zones, session: this, ...(o.aiConfig || {}) },
    });
    for (const c of this.combatants.bots()) this.ai.addBot(c);

    this._roundState = null;
    this._zoneKey = '';
    this.roundEndedAt = null;
    this.started = false;
  }

  get player() {
    return this.combatants.player;
  }

  /** Detaches the AI from the shared event bus (call before dropping the session). */
  dispose() {
    if (this.ai && typeof this.ai.dispose === 'function') this.ai.dispose();
    this.disposed = true;
  }

  /** Spawns everybody right away (dt 0 update) so the first frame already shows the level populated. */
  start({ skipPreRound = false } = {}) {
    if (skipPreRound && this.mode === 'match') this.match.start();
    this._advanceMatch(0);
    this.started = true;
    this._emitRoundTransitions(true);
    return this;
  }

  /** Participants inside the active zone (alive, feet inside the cylinder). */
  zoneOccupants() {
    const z = this.activeZone();
    const out = [];
    if (!z) return out;
    for (const c of this.combatants.all()) {
      if (!c.alive) continue;
      if (this.isInZone(c.position, z)) out.push(c.id);
    }
    return out;
  }

  isInZone(p, z = this.activeZone()) {
    if (!z) return false;
    const dx = p.x - z.center[0];
    const dz = p.z - z.center[2];
    const h = z.height ?? 4;
    return dx * dx + dz * dz <= z.radius * z.radius && p.y >= z.center[1] - 0.5 && p.y <= z.center[1] + h;
  }

  activeZone() {
    if (this.mode !== 'match') return null;
    const id = this.match.round.zoneId;
    return this.zones.find((z) => z.id === id) || null;
  }

  _advanceMatch(dtUs) {
    const predicate = this.combatants.predicate;
    if (this.mode === 'match') {
      const r = this.match.update(dtUs, { inZone: this.zoneOccupants(), predicate });
      if (r !== 'ok') throw new Error(`Match.update: ${r}`);
    } else {
      this.match.respawn.update(dtUs, predicate);
    }
    this.combatants.processCoreEvents(this.pendingKills);
  }

  /**
   * One fixed tick.
   * @param {number} dt seconds (1/60)
   * @param {object} [o] { playerCmd }
   */
  tick(dt, { playerCmd = null } = {}) {
    this.tickCount++;
    this.lastDtUs = this.clock.advance(dt);
    this.simTime += dt;
    this._advanceMatch(this.lastDtUs);
    this._emitRoundTransitions(false);
    if (this.player) this.player.applyCommand(playerCmd, dt);
    if (this.aiEnabled) this.ai.update(dt);
    this.combatants.stepUndriven(dt);
    this.combatants.processCoreEvents(this.pendingKills);
    this.dummies.tick(dt);
    // kill feed ageing
    for (const k of this.killFeed) k.age += dt;
    while (this.killFeed.length && this.killFeed[0].age > this.combat.hud.killFeedSeconds) this.killFeed.shift();
  }

  /** Damage of one round that hit a combatant (called from the shooter's WeaponSystem). */
  applyShotDamage(shooter, hit, amount, shot) {
    const victim = this.combatants.get(hit.combatantId);
    if (!victim) return null;
    this.stats.shotsHitCombatants++;
    const res = this.match.applyDamage(victim.id, amount, shooter.id);
    const fromDir = shot && shot.dir ? shot.dir.clone() : null;
    if (res.result === 'blocked_friendly_fire') {
      this.stats.ffBlocked++;
      this.events.emit('combatant:friendly_fire_blocked', { victimId: victim.id, attackerId: shooter.id, amount });
      return { ...res, victimId: victim.id, friendly: true };
    }
    if (res.result === 'applied' || res.result === 'killed') {
      this.stats.damageEvents++;
      this.events.emit('combatant:damaged', {
        victimId: victim.id,
        attackerId: shooter.id,
        amount: res.applied,
        part: hit.part,
        fromDir,
        attackerPosition: shooter.position.clone(),
        health: victim.health,
      });
      if (res.result === 'killed') {
        this.pendingKills.set(victim.id, { attackerId: shooter.id, fromDir, weaponId: shot ? shot.weaponId : null, part: hit.part });
        this.combatants.processCoreEvents(this.pendingKills);
        this._pushKillFeed(shooter, victim, shot ? shot.weaponId : null, hit.part === 'head');
      }
    }
    return { ...res, victimId: victim.id, killed: res.result === 'killed' };
  }

  _pushKillFeed(attacker, victim, weaponId, headshot) {
    this.killFeed.push({
      attackerId: attacker ? attacker.id : null,
      attackerName: attacker ? attacker.name : null,
      attackerTeam: attacker ? attacker.team : -1,
      victimId: victim.id,
      victimName: victim.name,
      victimTeam: victim.team,
      weapon: weaponId ? (this.weaponsData[weaponId] || {}).shortName || weaponId : null,
      headshot: !!headshot,
      age: 0,
    });
    while (this.killFeed.length > this.combat.hud.killFeedMax) this.killFeed.shift();
  }

  /** Test only: kill a combatant through the core (Match.kill). */
  forceKill(id) {
    const c = this.combatants.get(id);
    if (!c) return 'unknown_id';
    const r = this.match.kill(id);
    if (r === 'killed') {
      this.pendingKills.set(id, { attackerId: null, fromDir: null, weaponId: null, part: null, forced: true });
      this.combatants.processCoreEvents(this.pendingKills);
      this._pushKillFeed(null, c, null, false);
    }
    return r;
  }

  /** Engine input lock (core disableInput) for the player while a menu is open. */
  setMenuLock(on) {
    if (!this.player) return;
    if (on) this.match.disableInput(this.player.id, 'menu');
    else this.match.enableInput(this.player.id, 'menu');
    for (const w of this.player.weapons) {
      w.state.releaseInputs();
      // Opening the menu releases every input (InputManager.releaseAll). The simulation does not tick
      // behind the menu, so the core is shown that release now (zero-length update, no time passes):
      // the first press after "Pokračovat" is a new press, and a button kept down stays ignored until
      // it is pressed again (the input manager forgot it).
      if (on) w.state.core.update(0, false);
    }
  }

  /** Results screen: nobody fires (core 'results' lock on every participant). */
  setResultsLock(on) {
    for (const c of this.combatants.all()) {
      if (on) this.match.disableInput(c.id, 'results');
      else this.match.enableInput(c.id, 'results');
    }
  }

  /** New round without reloading anything: core reset, engine state, AI reset, immediate spawns. */
  resetRound({ skipPreRound = false } = {}) {
    this.match.reset();
    this.combatants.resetRound();
    this.match.respawn.takeEvents(); // interrupt events of the reset (weapons already reset)
    this.setResultsLock(false);
    this.ai.reset();
    for (const d of this.dummies.dummies) {
      d.health = this.dummies.maxHealth;
      d.down = false;
      d.downTimer = 0;
    }
    this.killFeed.length = 0;
    this.pendingKills.clear();
    this.stats = { ffBlocked: 0, damageEvents: 0, shotsHitCombatants: 0 };
    this.roundEndedAt = null;
    this._roundState = null;
    this._zoneKey = '';
    this.events.emit('round:reset', { zoneId: this.match.round.zoneId });
    if (skipPreRound && this.mode === 'match') this.match.start();
    this._advanceMatch(0);
    this._emitRoundTransitions(true);
  }

  _emitRoundTransitions(initial) {
    if (this.mode !== 'match') return;
    const r = this.match.round;
    const st = r.state;
    if (st !== this._roundState) {
      const prev = this._roundState;
      this._roundState = st;
      if (st === 'running' && (prev === 'pre_round' || initial)) this.events.emit('round:started', { zoneId: r.zoneId });
      else if (st === 'pre_round') this.events.emit('round:pre', { zoneId: r.zoneId, preRoundS: r.preRoundRemainingUs / 1e6 });
      if (st === 'ended') {
        this.roundEndedAt = this.simTime;
        this.setResultsLock(true);
        this.events.emit('round:ended', { zoneId: r.zoneId, winner: r.draw ? null : r.winner, draw: r.draw, reason: r.endReason, scores: r.scores });
      }
    }
    const z = r.zone;
    const key = `${z.status}:${z.controller}`;
    if (key !== this._zoneKey) {
      this._zoneKey = key;
      if (!initial) this.events.emit('zone:control_changed', { zoneId: r.zoneId, controller: z.controller >= 0 ? z.controller : null, status: z.status });
    }
  }

  // ------------------------------------------------------------------ queries for HUD / tests

  roundInfo() {
    const r = this.match.round;
    const z = this.activeZone();
    return {
      mode: this.mode,
      state: this.mode === 'match' ? r.state : 'practice',
      roundNumber: r.roundNumber,
      zoneId: this.mode === 'match' ? r.zoneId : null,
      zoneName: z ? z.name || z.id : null,
      zone: z ? { id: z.id, name: z.name || z.id, center: z.center.slice(), radius: z.radius, height: z.height ?? 4 } : null,
      status: r.zone.status,
      controller: r.zone.controller,
      counts: r.zone.counts.slice(),
      progress: this.rules.zone.pointIntervalUs > 0 ? r.zone.progressUs / this.rules.zone.pointIntervalUs : 0,
      scores: r.scores,
      scoreTarget: this.rules.round.scoreTarget,
      preRoundS: r.preRoundRemainingUs / 1e6,
      elapsedS: r.elapsedUs / 1e6,
      remainingS: r.remainingUs / 1e6,
      timeLimitS: this.rules.round.timeLimitUs / 1e6,
      winner: r.winner,
      draw: r.draw,
      endReason: r.endReason,
      teams: this.rules.teams.map((t, i) => ({ id: t.id, name: t.name, color: (this.teamsData.teams[i] || {}).color })),
      botCounts: this.botCounts.slice(),
      seed: this.seed,
    };
  }

  listCombatants() {
    return this.combatants.all().map((c) => c.getState());
  }

  zoneCandidates() {
    return this.zones.map((z) => ({ id: z.id, name: z.name, center: z.center.slice(), radius: z.radius }));
  }

  /** Distance / direction from a point to the active zone centre (HUD marker). */
  zoneVector(from) {
    const z = this.activeZone();
    if (!z) return null;
    const v = new Vector3(z.center[0] - from.x, 0, z.center[2] - from.z);
    return { distance: v.length(), dx: v.x, dz: v.z };
  }
}
