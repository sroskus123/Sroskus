// CombatantManager (Docs/GAMEPLAY_CONTRACTS.md): owns the list of combatants, creates them through
// Match.addParticipant, places them on the core's 'spawned' events, runs deaths from the core's 'killed'
// events, and provides the engine part of the spawn predicate (geometry, capsule fit, body clearance,
// enemy distance and enemy line of sight). Queries: all(), alive(), byTeam(t), get(id). No DOM.

import { Vector3 } from 'three';
import { Combatant, IDLE_COMMAND } from './combatant.js';
import { CharacterController } from '../physics/characterController.js';
import { spawnPointSafe } from '../core/respawn.js';

const _p = new Vector3();
const _e = new Vector3();
const _t = new Vector3();
const _down = new Vector3(0, -1, 0);

export class CombatantManager {
  /**
   * @param {object} o
   * @param {object} o.ctx       session context (see Combatant)
   * @param {Array<Array<{pos:number[], yaw:number}>>} o.spawns  team spawn points (same order as the core spawnAreas)
   */
  constructor({ ctx, spawns }) {
    this.ctx = ctx;
    this.spawns = spawns;
    this.list = [];
    this.byId = new Map();
    this.player = null;
    this.spawnHistory = [];
    this.deathLog = [];
    this.spawnBlocked = 0;
    this.predicateLog = null; // debug: last rejected reasons
    // probe controller for the capsule-fit test (never moved by the simulation)
    this._probe = null;
    this.predicate = (q) => this.spawnPredicate(q);
  }

  /** Adds a combatant (core participant first; its weapons exist afterwards). */
  add({ id, team, isPlayer = false, name }) {
    const r = this.ctx.match.addParticipant(id, team);
    if (r !== 'ok') throw new Error(`addParticipant(${id}, ${team}) -> ${r}`);
    const c = new Combatant({ id, team, isPlayer, name, index: this.list.length, ctx: this.ctx });
    // park far below the level until the core spawns it (never counts as "in zone" or blocks a spawn)
    c.controller.position.set(0, -1000 - this.list.length * 5, 0);
    this.list.push(c);
    this.byId.set(id, c);
    if (isPlayer) this.player = c;
    return c;
  }

  all() {
    return this.list;
  }

  alive() {
    return this.list.filter((c) => c.alive);
  }

  byTeam(t) {
    return this.list.filter((c) => c.team === t);
  }

  get(id) {
    return this.byId.get(id) ?? null;
  }

  bots() {
    return this.list.filter((c) => !c.isPlayer);
  }

  /**
   * Engine spawn predicate (called by the core RespawnSystem for each candidate point):
   *  - the capsule fits there (not inside geometry, standing height free) and there is ground below;
   *  - no other living body within max(rules.bodyClearance, combat.spawn.bodyClearance);
   *  - no living enemy within max(rules.minEnemyDistance, combat.spawn.minEnemyDistance);
   *  - no living enemy has line of sight to the head or chest of the spawned body.
   * Bodies that the core spawned earlier in the same update are taken at their spawn points.
   */
  spawnPredicate(q) {
    const policy = this.spawnPolicyFor(this.byId.get(q.participantId));
    const res = this.evaluateSpawnPoint(q.point, q.team, q.participantId, policy);
    if (res.safe && policy.fallback) {
      // fallback: only the (near-)safest point of the team is accepted (farthest from the nearest enemy)
      const best = this._bestFallbackDistance(q.team, q.participantId, policy);
      if (res.nearestEnemy < best - policy.bestMargin) {
        res.safe = false;
        res.reasons.push('not_safest');
      }
    }
    if (!res.safe) this.predicateLog = { ...res, participantId: q.participantId, candidateIndex: q.candidateIndex, policy: policy.name };
    return res.safe;
  }

  /**
   * Spawn policy of a waiting combatant. 'strict': enemies >= max(rules.respawn.minEnemyDistance,
   * combat.spawn.minEnemyDistance). After combat.spawn.fallback.afterS of waiting (failed core attempts in
   * this wait x respawn.retryInterval, so it does not depend on the tick length) 'fallback': enemies >=
   * fallback.minEnemyDistance and the safest point of the team. Geometry, body clearance and "no living
   * enemy sees the point" are never relaxed. Without a fallback block the rule stays strict (wait forever).
   */
  spawnPolicyFor(c) {
    const ctx = this.ctx;
    const cfg = ctx.combat.spawn;
    const strict = Math.max(ctx.rules.respawn.minEnemyDistance, cfg.minEnemyDistance);
    const fb = cfg.fallback;
    const part = c ? c.participant : null;
    const failed = part ? part.failedSpawnAttempts - (c.failedSpawnAttemptsBase || 0) : 0;
    const waitedS = (failed * ctx.rules.respawn.retryIntervalUs) / 1e6;
    if (fb && waitedS + 1e-9 >= fb.afterS) return { name: 'fallback', fallback: true, minEnemy: Math.min(strict, fb.minEnemyDistance), bestMargin: fb.bestMarginM ?? 0.5, waitedS };
    return { name: 'strict', fallback: false, minEnemy: strict, bestMargin: 0, waitedS };
  }

  /** Largest nearest-enemy distance among the team's points that pass the fallback checks (cached per update). */
  _bestFallbackDistance(team, participantId, policy) {
    // bodies the core spawned earlier in this update but the engine has not placed yet change the answer
    let pending = 0;
    for (const c of this.list) {
      const p = c.participant;
      if (p && p.state === 'alive' && p.spawnCount !== c.spawnCountSeen) pending++;
    }
    const key = `${this.ctx.tick()}|${team}|${participantId}|${pending}`;
    if (this._bestCache && this._bestCache.key === key) return this._bestCache.best;
    let best = -Infinity;
    for (const s of this.spawns[team]) {
      const r = this.evaluateSpawnPoint(s.pos, team, participantId, policy);
      if (r.safe && r.nearestEnemy > best) best = r.nearestEnemy;
    }
    this._bestCache = { key, best };
    return best;
  }

  /**
   * Full evaluation of a spawn point (also used for the spawn history and tests).
   * @param {object} [policy] from spawnPolicyFor (default: strict)
   */
  evaluateSpawnPoint(point, team, participantId = null, policy = null) {
    const ctx = this.ctx;
    const cfg = ctx.combat.spawn;
    const rr = ctx.rules.respawn;
    const minEnemy = policy ? policy.minEnemy : Math.max(rr.minEnemyDistance, cfg.minEnemyDistance);
    const clearance = Math.max(rr.bodyClearance, cfg.bodyClearance);
    const out = { safe: true, reasons: [], nearestEnemy: Infinity, nearestBody: Infinity, visibleTo: null, minEnemyDistance: minEnemy };
    _p.set(point[0], point[1], point[2]);

    // geometry: capsule fits and ground is below
    if (!this._probe) this._probe = new CharacterController(ctx.world, ctx.movement);
    const probe = this._probe;
    probe.world = ctx.world;
    _t.copy(_p);
    _t.y += 0.03;
    if (probe.overlaps(_t, probe.standHeight, 0.01)) {
      out.safe = false;
      out.reasons.push('inside_geometry');
    }
    _t.copy(_p);
    _t.y += 0.3;
    const ground = ctx.worldQuery.raycastStatic(_t, _down, cfg.groundProbe + 0.3);
    if (!ground) {
      out.safe = false;
      out.reasons.push('no_ground');
    }

    // bodies (core reference distance part + engine thresholds)
    const bodies = [];
    for (const c of this.list) {
      if (c.id === participantId) continue;
      const pos = this.effectivePosition(c);
      if (!pos) continue;
      bodies.push({ c, team: c.team, alive: true, pos: [pos.x, pos.y, pos.z] });
    }
    for (const b of bodies) {
      const d = Math.hypot(b.pos[0] - _p.x, b.pos[1] - _p.y, b.pos[2] - _p.z);
      out.nearestBody = Math.min(out.nearestBody, d);
      if (b.team !== team) out.nearestEnemy = Math.min(out.nearestEnemy, d);
    }
    if (!spawnPointSafe(point, team, bodies, { minEnemyDistance: minEnemy, bodyClearance: clearance })) {
      out.safe = false;
      if (out.nearestBody < clearance) out.reasons.push('body_too_close');
      if (out.nearestEnemy < minEnemy) out.reasons.push('enemy_too_close');
    }

    // enemy line of sight (eye of each living enemy -> head / chest of the spawned body)
    for (const b of bodies) {
      if (b.team === team) continue;
      const c = b.c;
      _e.set(b.pos[0], b.pos[1] + c.controller.eyeHeight, b.pos[2]);
      let seen = false;
      for (const h of cfg.losHeights) {
        _t.set(_p.x, _p.y + h, _p.z);
        if (ctx.worldQuery.lineOfSight(_e, _t, { ignoreId: c.id })) {
          seen = true;
          break;
        }
      }
      if (seen) {
        out.safe = false;
        out.visibleTo = c.id;
        out.reasons.push('visible_to_enemy');
        break;
      }
    }
    return out;
  }

  /**
   * Position of a living body for spawn checks: its controller position, or its spawn point when the
   * core spawned it earlier in the current update and the engine has not placed it yet. null = not alive.
   */
  effectivePosition(c) {
    const part = c.participant;
    if (!part || part.state !== 'alive') return null;
    if (part.spawnCount !== c.spawnCountSeen) {
      const s = this.spawns[c.team][part.spawnPoint];
      return s ? new Vector3(s.pos[0], s.pos[1], s.pos[2]) : null;
    }
    return c.controller.position.clone();
  }

  /** Handles the core RespawnSystem events ('spawned', 'killed', 'spawn_blocked'). */
  processCoreEvents(pendingKills) {
    const events = this.ctx.match.respawn.takeEvents();
    for (const e of events) {
      const c = this.byId.get(e.id);
      if (!c) continue;
      if (e.type === 'spawned') this._onSpawned(c, e.point);
      else if (e.type === 'killed') this._onKilled(c, pendingKills ? pendingKills.get(e.id) : null);
      else if (e.type === 'spawn_blocked') this.spawnBlocked++;
    }
    if (pendingKills) pendingKills.clear();
  }

  _onSpawned(c, pointIndex) {
    const ctx = this.ctx;
    const part = c.participant;
    const s = this.spawns[c.team][pointIndex];
    // record what the spot looked like, under the policy that accepted it (failed attempts not reset yet)
    const policy = this.spawnPolicyFor(c);
    const check = this.evaluateSpawnPoint(s.pos, c.team, c.id, policy);
    const strictCheck = policy.fallback ? this.evaluateSpawnPoint(s.pos, c.team, c.id) : check;
    c.failedSpawnAttemptsBase = part.failedSpawnAttempts;
    c.spawnCountSeen = part.spawnCount;
    c.spawnPointIndex = pointIndex;
    c.spawnAt(new Vector3(s.pos[0], s.pos[1], s.pos[2]), s.yaw ?? 0);
    const rec = {
      tick: ctx.tick(),
      time: ctx.time(),
      id: c.id,
      team: c.team,
      point: pointIndex,
      position: [s.pos[0], s.pos[1], s.pos[2]],
      spawnCount: part.spawnCount,
      nearestEnemy: check.nearestEnemy,
      nearestBody: check.nearestBody,
      visibleToEnemy: check.visibleTo,
      insideGeometry: check.reasons.includes('inside_geometry'),
      safeAtSpawn: check.safe,
      policy: policy.name,
      waitedS: policy.waitedS,
      minEnemyDistance: policy.minEnemy,
      strictSafe: strictCheck.safe,
    };
    this.spawnHistory.push(rec);
    if (this.spawnHistory.length > 2000) this.spawnHistory.shift();
    ctx.events.emit('combatant:spawned', { id: c.id, team: c.team, position: c.position.clone(), yaw: c.yaw, isPlayer: c.isPlayer });
  }

  _onKilled(c, info) {
    const ctx = this.ctx;
    const attackerId = info ? info.attackerId : null;
    const fromDir = info ? info.fromDir : null;
    c.deathsSeen = c.participant.deaths;
    c.failedSpawnAttemptsBase = c.participant.failedSpawnAttempts; // the wait for the next spawn starts now
    c.beginDeath({ fromDir, attackerId });
    const attacker = attackerId ? this.byId.get(attackerId) : null;
    if (attacker && attacker !== c && attacker.team !== c.team) attacker.kills++;
    const rec = {
      tick: ctx.tick(),
      time: ctx.time(),
      victimId: c.id,
      attackerId,
      weaponId: info ? info.weaponId : null,
      part: info ? info.part : null,
      forced: info ? !!info.forced : true,
      position: c.position.toArray(),
    };
    this.deathLog.push(rec);
    if (this.deathLog.length > 500) this.deathLog.shift();
    ctx.events.emit('combatant:died', { victimId: c.id, attackerId, position: c.position.clone(), weaponId: rec.weaponId, part: rec.part, team: c.team });
  }

  /** Steps every combatant that was not driven this tick (AI stub, dead bots, AI disabled) with an idle command. */
  stepUndriven(dt) {
    const tick = this.ctx.tick();
    for (const c of this.list) {
      if (c.lastStepTick !== tick) c.applyCommand(IDLE_COMMAND, dt);
    }
  }

  /** New round: engine-side state back to the start (core reset is done by the session). */
  resetRound() {
    for (const c of this.list) {
      c.kills = 0;
      c.deathPose = null;
      c.spawnCountSeen = 0;
      c.deathsSeen = 0;
      c.spawnPointIndex = -1;
      c.failedSpawnAttemptsBase = 0; // the core reset its counters
      c.lastAttackerId = null;
      c.controller.position.set(0, -1000 - c.index * 5, 0);
      c.controller.velocity.set(0, 0, 0);
      for (const w of c.weapons) {
        w.recoil.reset();
        w.state.ads = 0;
        w.state.releaseInputs();
        w.lastShot = null;
      }
      c.activeWeapon = 0;
      c.switchTimer = 0;
      c.weapons[0].state.core.enable('switch');
      c.weapons[1].state.core.disable('switch');
    }
    this.spawnHistory.length = 0;
    this.deathLog.length = 0;
    this.spawnBlocked = 0;
  }
}
