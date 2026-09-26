// One AI bot: perception + memory + a utility-based decision layer (~4.5 Hz) + per-tick execution that
// produces the SAME command format as the player (Docs/GAMEPLAY_CONTRACTS.md) for Combatant.applyCommand.
//
// Decision (utility, highest score wins, the current task gets a small hysteresis bonus):
//   engage     an enemy is visible now                                  -> stop / strafe, aim, bursts
//   cover      visible enemy or under fire and not protected, or reloading with enemies around
//                                                                        -> reserve a cover point that
//              protects from the threat (and allows firing), move there, hide / peek cycle, reposition
//              after some time or when flanked
//   search     remembered (not visible) enemy with enough confidence     -> go to the last known /
//              predicted position, look around, give up (forget) when nothing is found
//   objective  default: move to a spaced position in the active zone and hold it (scan the approaches),
//              reposition now and then; re-evaluated on zone control change, death, respawn, round reset
// Combat overlay (every tick, any task): a visible target is tracked with the aim model; after the
// reaction delay the bot fires data-driven bursts when the aim is on target and the MUZZLE (not only the
// eye) has a clear line to the target; it reloads when empty or when safe, and never fires while
// reloading, while the weapon is locked (switch / sprint / death) or while sprinting.

import { Vector3 } from 'three';
import { createRng } from '../util/rng.js';
import { EnemyMemory } from './memory.js';
import { Perception, forwardFromYawPitch } from './perception.js';
import { AimController, yawPitchTo } from './aim.js';
import { PathFollower } from './steering.js';
import { coverProtects } from './tactics.js';

const DEG = Math.PI / 180;
const _eye = new Vector3();
const _aim = new Vector3();
const _v = new Vector3();
const _w = new Vector3();
const _muzzle = new Vector3();
const _mEye = new Vector3();
const _mEye2 = new Vector3();
const _mM1 = new Vector3();
const _mM2 = new Vector3();
const _mD = new Vector3();
const _fDir1 = new Vector3();
const _fDir2 = new Vector3();

function hashId(s) {
  let h = 2166136261 >>> 0;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619) >>> 0;
  }
  return h >>> 0;
}

export function makeCommand() {
  return { moveX: 0, moveZ: 0, yaw: null, pitch: null, sprint: false, walk: false, crouch: false, jump: false, ads: false, fire: false, reload: false, switchTo: null, interact: false };
}

export class Bot {
  constructor(sys, combatant, index) {
    this.sys = sys;
    this.c = combatant;
    this.index = index;
    this.rng = createRng((sys.seed ^ hashId(String(combatant.id))) >>> 0);
    this.memory = new EnemyMemory(sys.cfg);
    this.perception = new Perception(this);
    this.aim = new AimController(this);
    this.move = new PathFollower(this);
    this.cmd = makeCommand();
    this.wasAlive = false;
    this.lives = 0;
    this.metrics = { shots: 0, bursts: 0, reactions: [], shotsDuringReload: 0, blockedMuzzleHolds: 0, reloads: 0, targetsEngaged: 0 };
    this.resetBrain(0);
  }

  resetBrain(t) {
    this.task = 'idle';
    this.taskReason = 'start';
    this.taskSince = t;
    this.targetId = null;
    this.releaseCover();
    this.cover = null;
    this.coverPhase = 'hide';
    this.coverPhaseUntil = 0;
    this.coverSince = 0;
    this.coverExclude = new Set();
    this.post = null;
    this.postSince = 0;
    this.advancing = false;
    this.search = null;
    this.reactionFor = null;
    this.reactionUntil = -1;
    this.reactionStart = -1;
    this.lastTargetSeenAt = -1;
    this.lastEnemySeenAt = -Infinity;
    this.burstLeft = 0;
    this.pauseUntil = 0;
    this.lastShotsFired = this._weapon() ? this._weapon().state.shotsFired : 0;
    this.lastShotsWeapon = this._weapon();
    this.semiRelease = false;
    this.reloadPulse = false;
    this.strafeDir = 1;
    this.strafeUntil = 0;
    this.scanYaw = this.c.yaw;
    this.scanUntil = 0;
    this.decisionDirty = true;
    this.fireBlockedReason = null;
    this.lastLook = null;
    this.muzzleBlockedSince = -1;
    this.lookHint = null;
    this.stepOutUntil = -1;
    this.stepOutDir = new Vector3();
    this.firstShotPending = null;
    this.memory.clear();
    this.perception.reset();
    this.aim.reset();
    this.move.reset();
    this.sys.tactics && this.sys.tactics.board.release(this.c.id);
    if (this.scripted) this.scripted.arrivedAt = -1;
  }

  _weapon() {
    return this.c.weapons ? this.c.weapons[this.c.activeWeapon] : null;
  }

  releaseCover() {
    if (this.sys.cover) this.sys.cover.release(this.c.id);
    this.cover = null;
  }

  onSpawn(t) {
    this.lives++;
    this.resetBrain(t);
    this.wasAlive = true;
    // decide right away, perceive in this bot's slot
    this.nextDecision = t;
  }

  onDeath(t) {
    this.wasAlive = false;
    this.releaseCover();
    this.sys.tactics.board.release(this.c.id);
    this.memory.clear();
    this.perception.reset();
    this.move.clearGoal();
    this.task = 'dead';
    this.taskSince = t;
    this.targetId = null;
  }

  onMoveFailed(reason) {
    // let the decision layer pick another goal (new cover / post / give up search)
    if (this.task === 'cover' && this.cover) {
      this.coverExclude.add(this.cover.id);
      this.releaseCover();
    } else if (this.task === 'objective') this.post = null;
    else if (this.task === 'search' && this.search) this.search.failed = reason;
    this.decisionDirty = true;
  }

  // ------------------------------------------------------------------ helpers

  get target() {
    return this.targetId ? this.memory.get(this.targetId) : null;
  }

  targetVisible(t) {
    const e = this.target;
    return !!(e && e.seen && t - e.lastSeen < 0.2);
  }

  weaponInfo() {
    const w = this._weapon();
    if (!w) return null;
    const s = w.state;
    const cap = s.rulesDef ? s.rulesDef.magazineCapacity : 30;
    return { w, s, rounds: s.magazine + s.chamber, cap, reserve: s.reserve, ready: s.state === 'ready', enabled: s.enabled, state: s.state };
  }

  _selectTarget(t) {
    let best = null;
    let bestS = -Infinity;
    const p = this.c.position;
    const dmg = this.perception.lastDamage;
    for (const e of this.memory.entries.values()) {
      if (e.conf < 0.05) continue;
      const d = Math.hypot(e.pos.x - p.x, e.pos.z - p.z);
      let s = e.conf * (e.seen ? 2 : 1) - d / 60;
      if (dmg && dmg.attackerId === e.id && t - dmg.t < 3) s += 0.8;
      if (e.id === this.targetId) s += 0.25;
      if (s > bestS) {
        bestS = s;
        best = e;
      }
    }
    const prev = this.targetId;
    this.targetId = best ? best.id : null;
    if (this.targetId !== prev) this.aim.track(this.targetId, 0, false);
  }

  _threatEstimate(t) {
    const e = this.target;
    if (e) return this.memory.predicted(e, t, new Vector3());
    const dmg = this.perception.lastDamage;
    if (dmg && dmg.dir && t - dmg.t < 4) return this.c.position.clone().addScaledVector(dmg.dir, this.sys.cfg.damage.guessDistance);
    return null;
  }

  // ------------------------------------------------------------------ decisions (~4.5 Hz)

  decide(t) {
    const sys = this.sys;
    const cfg = sys.cfg;
    this.decisionDirty = false;
    this.lastDecisionAt = t;
    this.decisions = (this.decisions || 0) + 1;
    const round = sys.roundState();
    if (round === 'ended') {
      this._setTask('idle', 'round_ended', t);
      this.move.clearGoal();
      return;
    }
    if (this.scripted) {
      this._setTask('scripted', 'příkaz', t);
      this.move.setGoal(this.scripted.goal, { tolerance: this.scripted.tolerance });
      return;
    }
    this._selectTarget(t);
    const e = this.target;
    const visible = this.targetVisible(t);
    const underFire = this.perception.underFire;
    const wi = this.weaponInfo();
    const reloading = wi && wi.state !== 'ready';
    const lowAmmo = wi && wi.rounds / wi.cap < cfg.combat.reloadBelowFraction;
    const threat = this._threatEstimate(t);
    const inCover = this.cover && sys.tactics.atCover(this, this.cover);
    const coverGood = inCover && threat && coverProtects(sys.world, this.cover, threat, cfg);
    const zone = sys.activeZone();
    const scores = { objective: zone ? 0.5 : 0.3, engage: 0, cover: 0, search: 0 };
    if (visible) scores.engage = 0.9;
    if ((visible || underFire) && threat && !coverGood) scores.cover = 0.72 + (underFire ? 0.22 : 0) + (reloading || lowAmmo ? 0.08 : 0);
    if ((reloading || (lowAmmo && wi.reserve > 0)) && threat && t - this.lastEnemySeenAt < 6 && !coverGood) scores.cover = Math.max(scores.cover, 0.86);
    if (coverGood && (visible || underFire || t - this.lastEnemySeenAt < 4)) scores.cover = Math.max(scores.cover, 0.92); // stay in good cover while fighting
    // a fresh glimpse is watched (detection may still complete), not walked to
    const freshGlimpse = e && e.source === 'glimpse' && t - e.time < cfg.memory.glimpseWatchTime;
    if (e && !visible && !freshGlimpse && !e.searched && e.conf >= cfg.memory.searchMinConfidence) {
      let s = 0.45 + 0.35 * e.conf;
      if (zone && sys.zoneUrgent(this) && this.c.position.distanceTo(e.pos) > 25) s -= 0.25;
      scores.search = s;
    }
    if (this.task === 'cover' && this.cover && t - this.coverSince > cfg.cover.maxTimeInCover) scores.cover -= 0.3; // time to move on
    if (scores[this.task] !== undefined) scores[this.task] += 0.07;
    let best = 'objective';
    for (const k of Object.keys(scores)) if (scores[k] > scores[best]) best = k;
    this.scores = scores;
    const reason = best === 'engage' ? `vidí ${e.id}` : best === 'cover' ? (underFire ? 'pod palbou' : reloading ? 'přebíjí' : 'kontakt') : best === 'search' ? `pátrá po ${e.id}` : zone ? `oblast ${zone.id}` : 'hlídá';
    this._setTask(best, reason, t);
    this._planTask(t, threat, zone, visible);
  }

  _setTask(task, reason, t) {
    if (task !== this.task) {
      // leaving a task: release what belongs to it
      if (this.task === 'cover' && task !== 'engage') this.releaseCover();
      if (task === 'search') this.sys.tactics.board.release(this.c.id); // leaving its spot: free it for teammates
      if (this.task === 'search') {
        if (this.search) {
          const se = this.memory.get(this.search.id);
          if (se) se.searching = false;
          this.sys.recordSearch(this, { id: this.search.id, reason: `interrupted:${task}`, duration: t - this.search.startedAt, pos: this.search.pos });
        }
        this.search = null;
      }
      this.task = task;
      this.taskSince = t;
    }
    this.taskReason = reason;
  }

  _planTask(t, threat, zone, visible) {
    const sys = this.sys;
    const cfg = sys.cfg;
    switch (this.task) {
      case 'engage': {
        // the zone needs us and the enemy is not close / not hitting us: keep advancing while firing
        const e = this.target;
        const d = e ? e.pos.distanceTo(this.c.position) : 0;
        this.advancing = !!(zone && sys.zoneUrgent(this) && !this.perception.underFire && d > 15);
        if (this.advancing) {
          this._planObjective(t, zone);
          break;
        }
        // hold the ground (or the cover we are in); strafe at close range
        if (this.cover && !sys.tactics.atCover(this, this.cover, 1.0)) this.releaseCover();
        if (!this.cover) this.move.clearGoal();
        break;
      }
      case 'cover': {
        let cp = this.cover;
        const flanked = cp && threat && sys.tactics.atCover(this, cp) && !coverProtects(sys.world, cp, threat, cfg);
        const expired = cp && t - this.coverSince > cfg.cover.maxTimeInCover;
        if (cp && (flanked || expired)) {
          this.coverExclude.add(cp.id);
          this.releaseCover();
          cp = null;
          this.coverReason = flanked ? 'obejit' : 'zmena_pozice';
        }
        if (!cp && threat) {
          const found = sys.tactics.findCover(this, threat, { requireFire: visible, zone, urgent: zone && sys.zoneUrgent(this), exclude: this.coverExclude });
          if (found && sys.cover.reserve(this.c.id, found.id)) {
            this.cover = found;
            this.coverSince = t;
            this.coverPhase = 'hide';
            this.coverPhaseUntil = t;
            sys.tactics.board.claim(this.c.id, this.c.team, found.pos, 'cover');
            this.move.setGoal(found.pos, { tolerance: 0.3, force: true });
          } else {
            // no usable cover: fight from here
            this._setTask('engage', 'bez krytu', t);
            this.move.clearGoal();
          }
        } else if (cp) this.move.setGoal(cp.pos, { tolerance: 0.3 });
        if (this.coverExclude.size > 6) this.coverExclude.clear();
        break;
      }
      case 'search': {
        const e = this.target;
        if (!e) break;
        if (!this.search || this.search.id !== e.id || e.time > this.search.infoTime + 1e-6) {
          const guess = this.memory.predicted(e, t, new Vector3());
          const snapped = sys.nav ? sys.nav.closestPoint(guess, 6) : guess;
          this.search = { id: e.id, pos: snapped || guess, startedAt: this.search && this.search.id === e.id ? this.search.startedAt : t, arrivedAt: -1, infoTime: e.time, failed: null };
          if (snapped) this.move.setGoal(this.search.pos, { tolerance: Math.min(1.0, cfg.memory.searchRadius), force: true });
          else this.search.failed = 'no_nav';
        }
        const s = this.search;
        const M = cfg.memory;
        e.searching = true;
        const giveUp = s.failed || t - s.startedAt > M.searchMaxTime || (s.arrivedAt >= 0 && t - s.arrivedAt > M.searchLookTime);
        if (giveUp) {
          e.searched = true;
          sys.recordSearch(this, { id: e.id, reason: s.failed || (s.arrivedAt >= 0 ? 'not_found' : 'timeout'), duration: t - s.startedAt, pos: s.pos });
          if (M.forgetAfterSearch) this.memory.forget(e.id);
          this.search = null;
          this.targetId = null;
          this.decisionDirty = true;
        }
        break;
      }
      case 'objective':
        this._planObjective(t, zone);
        break;
      default:
        this.move.clearGoal();
    }
  }

  /** Objective: a spaced post inside the active zone (cover preferred), held and changed now and then. */
  _planObjective(t, zone) {
    const sys = this.sys;
    const cfg = sys.cfg;
    if (!zone) {
      // no objective (practice / tests): hold the current spot
      if (!this.post) this.post = { pos: this.c.position.clone(), cover: null, guard: true };
      this.move.clearGoal();
      return;
    }
    const inZone = sys.isInZone(this.c.position, zone);
    const postInZone = this.post && !this.post.guard && sys.isInZone(this.post.pos, zone);
    const reposition = this.post && inZone && t - this.postSince > this.postHold;
    if (!postInZone || reposition || this.post.zoneId !== zone.id) {
      const prev = this.post && this.post.cover;
      const np = sys.tactics.zonePost(this, zone);
      if (np.cover && !sys.cover.reserve(this.c.id, np.cover.id)) np.cover = null;
      else if (!np.cover && prev) this.releaseCover();
      if (np.cover) this.cover = np.cover;
      this.post = { ...np, zoneId: zone.id };
      this.postSince = t;
      this.postHold = cfg.objective.holdRepositionMin + this.rng.next() * (cfg.objective.holdRepositionMax - cfg.objective.holdRepositionMin);
      sys.tactics.board.claim(this.c.id, this.c.team, np.pos, 'post');
    }
    this.move.setGoal(this.post.pos, { tolerance: this.post.cover ? 0.3 : 0.6 });
  }

  // ------------------------------------------------------------------ per tick

  act(dt) {
    const sys = this.sys;
    const cfg = sys.cfg;
    const t = sys.time;
    const c = this.c;
    const cmd = this.cmd;
    cmd.moveX = 0;
    cmd.moveZ = 0;
    cmd.sprint = false;
    cmd.walk = false;
    cmd.crouch = false;
    cmd.jump = false;
    cmd.ads = false;
    cmd.fire = false;
    cmd.reload = false;
    cmd.switchTo = null;
    if (this.task === 'idle' && sys.roundState() === 'ended') {
      cmd.yaw = c.yaw;
      cmd.pitch = c.pitch;
      return cmd;
    }
    c.getEye(_eye);
    if (this.scripted) return this._actScripted(t, dt);
    const e = this.target;
    const visible = this.targetVisible(t);
    if (visible) {
      this.lastEnemySeenAt = t;
      this.lastTargetSeenAt = t;
    }
    const wi = this.weaponInfo();

    // ---- reaction timer (nonzero, data-driven) ----
    if (visible) {
      if (this.reactionFor !== e.id || e.firstSeen > this.reactionStart + 1e-6) {
        const R = cfg.combat;
        const reacq = this.reactionFor === e.id && e.firstSeen - this.reactionStart < 1.5;
        const delay = (R.reactionDelayMin + this.rng.next() * (R.reactionDelayMax - R.reactionDelayMin)) * (reacq ? 0.5 : 1);
        this.reactionFor = e.id;
        this.reactionStart = e.firstSeen;
        this.reactionUntil = t + delay;
        this.firstShotPending = { targetId: e.id, detectedAt: e.firstSeen, delay, distance: e.pos.distanceTo(c.position) };
        this.metrics.targetsEngaged++;
      }
    }

    // ---- movement ----
    const desired = this.move.update(dt);
    let moving = this.move.wantMove || this.move.nudging;
    let crouch = false;
    let walk = false;
    const inCover = this.cover && sys.tactics.atCover(this, this.cover);
    if (this.task === 'engage' && visible && !inCover && !this.advancing) {
      const d = e.pos.distanceTo(c.position);
      if (d < 12) {
        // strafe at close range
        if (t > this.strafeUntil) {
          this.strafeDir = this.rng.next() < 0.5 ? -1 : 1;
          this.strafeUntil = t + 0.5 + this.rng.next() * 0.7;
        }
        const [fx, fz] = [e.pos.x - c.position.x, e.pos.z - c.position.z];
        const L = Math.hypot(fx, fz) || 1;
        desired.set((-fz / L) * this.strafeDir, 0, (fx / L) * this.strafeDir);
        moving = true;
      } else if (d > 15) crouch = true;
    }
    if (inCover && this.cover) {
      // hide / peek cycle
      if (t >= this.coverPhaseUntil) {
        const C = cfg.cover;
        const hide = this.coverPhase === 'peek';
        this.coverPhase = hide ? 'hide' : 'peek';
        this.coverPhaseUntil = t + (hide ? C.hideTimeMin + this.rng.next() * (C.hideTimeMax - C.hideTimeMin) : C.peekTimeMin + this.rng.next() * (C.peekTimeMax - C.peekTimeMin));
      }
      const reloadingNow = wi && wi.state !== 'ready';
      let phase = reloadingNow ? 'hide' : this.coverPhase;
      if (visible && this.coverPhase === 'peek') phase = 'peek';
      if (this.task !== 'cover' && this.task !== 'engage' && !this.perception.underFire) phase = 'peek'; // holding a post: watch over the cover
      if (this.cover.height === 'low') crouch = phase === 'hide';
      else if (this.cover.peekPos && phase === 'peek' && (this.task === 'cover' || this.task === 'engage')) {
        this.move.setGoal(this.cover.peekPos, { tolerance: 0.25 });
      }
    } else if (this.cover && this.cover.peekPos && this.task === 'cover' && this.move.goal && this.move.goal.distanceTo(this.cover.peekPos) < 0.05 && this.coverPhase === 'hide') {
      this.move.setGoal(this.cover.pos, { tolerance: 0.3 });
    }
    if (t < this.stepOutUntil) {
      desired.copy(this.stepOutDir);
      moving = true;
      crouch = false;
    }
    if (this.task === 'search' && this.search) {
      const d = this.move.distanceToGoal();
      if (d < 8) walk = true;
      // arrived near the last known position (within memory.searchRadius): look around there
      if ((this.move.arrived || d < cfg.memory.searchRadius * 0.4) && this.search.arrivedAt < 0) this.search.arrivedAt = t;
    }

    // ---- look / aim ----
    let look = null;
    let aimRes = null;
    const recentTarget = e && e.lastSeen >= 0 && t - e.lastSeen <= cfg.combat.continueFireAfterLostSight + 0.1;
    if (e && (visible || recentTarget)) {
      this.memory.predicted(e, t, _aim);
      _aim.y += e.aimHeight + cfg.aim.aimHeightOffset;
      this.aim.track(e.id, dt, visible);
      const tv = e.vel;
      _v.subVectors(_aim, _eye).setY(0).normalize();
      const lateral = Math.abs(tv.x * _v.z - tv.z * _v.x);
      aimRes = this.aim.aimAt(_eye, _aim, dt, { targetLateralSpeed: lateral });
      look = aimRes;
    } else {
      this.aim.track(null, dt, false);
      const alert = this.perception.alert;
      if (alert && alert.until > t) {
        _w.copy(alert.pos);
        _w.y += 1.4;
        look = this.aim.lookAtPoint(_eye, _w, dt);
      } else if (this.task === 'search' && this.search) {
        if (this.search.arrivedAt >= 0) look = this._scan(t, dt, true);
        else look = this._lookAlongPath(dt) || this.aim.lookAtPoint(_eye, _w.copy(this.search.pos).setY(this.search.pos.y + 1.4), dt);
      } else if (moving && this.move.hasPath) look = this._lookAlongPath(dt);
      else look = this._scan(t, dt, false);
    }
    cmd.yaw = look.yaw;
    cmd.pitch = look.pitch;
    this.lastLook = look;

    // ---- speed mode ----
    const knownThreat = t - this.lastEnemySeenAt < 5 || this.perception.underFire;
    const reloadingNow = wi && wi.state !== 'ready';
    let sprint = false;
    if (moving && !visible && !knownThreat && !reloadingNow && !crouch && this.task !== 'search' && this.move.remainingLength() > cfg.movement.sprintMinDistance) {
      // sprinting requires moving within ~50 deg of the view: look along the path
      sprint = true;
    }
    if (sprint) {
      const pl = this._lookAlongPath(dt);
      if (pl) {
        cmd.yaw = pl.yaw;
        cmd.pitch = pl.pitch;
      }
    }

    // ---- movement -> local command (relative to the commanded yaw) ----
    if (moving || desired.lengthSq() > 1e-6) {
      const y = cmd.yaw;
      const fx = -Math.sin(y);
      const fz = -Math.cos(y);
      const rx = Math.cos(y);
      const rz = -Math.sin(y);
      cmd.moveZ = desired.x * fx + desired.z * fz;
      cmd.moveX = desired.x * rx + desired.z * rz;
    }
    cmd.crouch = crouch && !sprint;
    cmd.walk = walk && !sprint;

    // ---- weapon: reload / fire ----
    this._weaponControl(t, dt, e, visible, recentTarget, aimRes, wi, sprint);
    cmd.sprint = sprint && !cmd.fire;
    cmd.ads = !!(visible && aimRes && aimRes.distance > cfg.combat.adsRange && !moving && !sprint);
    return cmd;
  }

  /** Scripted move: follow the path (sprint on long straight parts), look along it, never fire. */
  _actScripted(t, dt) {
    const cmd = this.cmd;
    const s = this.scripted;
    const desired = this.move.update(dt);
    const look = this._lookAlongPath(dt) || this.aim.turnTowards(this.c.yaw, 0, dt);
    cmd.yaw = look.yaw;
    cmd.pitch = look.pitch;
    const y = cmd.yaw;
    cmd.moveZ = desired.x * -Math.sin(y) + desired.z * -Math.cos(y);
    cmd.moveX = desired.x * Math.cos(y) + desired.z * -Math.sin(y);
    cmd.sprint = !!(s.run && this.move.wantMove && this.move.remainingLength() > this.sys.cfg.movement.sprintMinDistance);
    if (this.move.arrived && s.arrivedAt < 0) s.arrivedAt = t;
    this.lastShotsFired = this._weapon() ? this._weapon().state.shotsFired : this.lastShotsFired;
    this.lastShotsWeapon = this._weapon();
    return cmd;
  }

  _lookAlongPath(dt) {
    const m = this.move;
    if (!m.hasPath) return null;
    const p = this.c.position;
    // look at a point ~3 m ahead along the path at eye height
    let wp = m.path[m.index];
    for (let i = m.index; i < m.path.length; i++) {
      wp = m.path[i];
      if (Math.hypot(wp.x - p.x, wp.z - p.z) > 3) break;
    }
    _w.set(wp.x, wp.y + this.c.controller.eyeHeight, wp.z);
    const { yaw } = yawPitchTo(_eye, _w);
    return this.aim.turnTowards(yaw, 0, dt);
  }

  /** Idle look: scan the approaches (enemy spawns, remembered threats), change direction now and then. */
  _scan(t, dt, searching) {
    const cfg = this.sys.cfg;
    if (this.lookHint && t < this.lookHint.until && !searching) return this.aim.turnTowards(this.lookHint.yaw, 0, dt);
    if (t >= this.scanUntil) {
      const O = cfg.objective;
      this.scanUntil = t + O.scanIntervalMin + this.rng.next() * (O.scanIntervalMax - O.scanIntervalMin);
      const pts = [];
      if (searching) {
        for (let k = 0; k < 4; k++) pts.push(this.c.yaw + (this.rng.next() * 2 - 1) * Math.PI);
      } else {
        for (const s of this.sys.enemySpawnCenters(this.c.team)) pts.push(yawPitchTo(this.c.position, s).yaw);
        for (const e of this.memory.entries.values()) pts.push(yawPitchTo(this.c.position, e.pos).yaw);
        const zone = this.sys.activeZone();
        if (zone && !this.sys.isInZone(this.c.position, zone)) pts.push(yawPitchTo(this.c.position, new Vector3(zone.center[0], 0, zone.center[2])).yaw);
      }
      if (pts.length) this.scanYaw = pts[Math.floor(this.rng.next() * pts.length)] + (this.rng.next() * 2 - 1) * 20 * DEG;
    }
    return this.aim.turnTowards(this.scanYaw, 0, dt);
  }

  _weaponControl(t, dt, e, visible, recentTarget, aimRes, wi, sprinting) {
    const sys = this.sys;
    const cfg = sys.cfg;
    const cmd = this.cmd;
    this.fireBlockedReason = null;
    if (!wi) return;
    // out of ammo (magazine, chamber and reserve empty): draw the other weapon if it has any (same
    // switchTo command as the player; the core 'switch' lock keeps it from firing while drawing)
    if (wi.rounds === 0 && wi.reserve === 0 && this.c.switchTimer <= 0) {
      const other = this.c.weapons ? this.c.weapons.findIndex((w, i) => i !== this.c.activeWeapon && w.state.magazine + w.state.chamber + w.state.reserve > 0) : -1;
      if (other >= 0) {
        cmd.switchTo = other;
        this.burstLeft = 0;
        this.fireBlockedReason = 'switching';
        this.metrics.switches = (this.metrics.switches || 0) + 1;
        return;
      }
      this.fireBlockedReason = 'no_ammo';
      this.burstLeft = 0;
      return;
    }
    const reloading = wi.state !== 'ready';
    // reload decision
    if (!reloading && wi.enabled) {
      const empty = wi.rounds === 0 && wi.reserve > 0;
      const safe = t - this.lastEnemySeenAt > cfg.combat.safeReloadNoContactTime && !this.perception.underFire && !visible;
      const low = wi.rounds / wi.cap < cfg.combat.reloadBelowFraction && wi.reserve > 0;
      const needsChamber = wi.s.core && wi.s.core.needsChamberAction;
      if ((empty || (low && safe)) && !needsChamber) {
        cmd.reload = true;
        this.metrics.reloads++;
        this.burstLeft = 0;
        return;
      }
    }
    if (reloading) {
      this.fireBlockedReason = 'reloading';
      this.burstLeft = 0;
      return;
    }
    if (!wi.enabled) {
      this.fireBlockedReason = 'weapon_locked';
      return;
    }
    if (sprinting) {
      this.fireBlockedReason = 'sprinting';
      return;
    }
    if (!e || !(visible || recentTarget) || !aimRes) {
      this.burstLeft = 0;
      return;
    }
    if (t < this.reactionUntil) {
      this.fireBlockedReason = 'reaction';
      return;
    }
    if (aimRes.distance > cfg.combat.maxEngageRange) {
      this.fireBlockedReason = 'range';
      return;
    }
    if (t < this.pauseUntil) {
      this.fireBlockedReason = 'burst_pause';
      return;
    }
    const cone = Math.max(cfg.combat.fireConeDeg, Math.atan2(cfg.combat.fireConeMinMeters, Math.max(aimRes.distance, 0.5)) / DEG);
    if (aimRes.offAimDeg > cone && this.burstLeft === 0) {
      this.fireBlockedReason = 'aiming';
      return;
    }
    // same muzzle rule as the player (D8): do not pull the trigger if the muzzle has no clear line
    if (cfg.combat.muzzleCheck && typeof this.c.muzzleWorld === 'function') {
      this.c.muzzleWorld(_muzzle);
      if (!this._muzzleClear(_muzzle, _aim)) {
        this.fireBlockedReason = 'muzzle_blocked';
        this.metrics.blockedMuzzleHolds++;
        this.burstLeft = 0;
        // held for a moment: step out (away from the obstacle in front of the muzzle) to get a clear line
        if (this.muzzleBlockedSince < 0) this.muzzleBlockedSince = t;
        else if (t - this.muzzleBlockedSince > cfg.combat.muzzleStepOutAfter && t > this.stepOutUntil) {
          // try a sidestep to the left and to the right: which one gives the muzzle a clear line?
          const eyeP = this.c.getEye(_w).clone();
          const fx = -Math.sin(this.c.yaw);
          const fz = -Math.cos(this.c.yaw);
          const clearAt = (side) => {
            const ox = -fz * side * 0.5;
            const oz = fx * side * 0.5;
            const e2 = new Vector3(eyeP.x + ox, eyeP.y, eyeP.z + oz);
            const m2 = new Vector3(_muzzle.x + ox, _muzzle.y, _muzzle.z + oz);
            const d = m2.clone().sub(e2);
            const L = d.length();
            if (sys.world.raycastStatic(eyeP, new Vector3(ox, 0, oz).normalize(), 0.85)) return false; // room to step
            return !sys.world.raycastStatic(e2, d.divideScalar(L), L) && sys.world.lineOfSight(m2, _aim, { ignoreId: this.c.id });
          };
          const r = clearAt(1);
          const l = clearAt(-1);
          const side = r && !l ? 1 : l && !r ? -1 : this.rng.next() < 0.5 ? -1 : 1;
          this.stepOutDir.set(-fz * side, 0, fx * side);
          this.stepOutUntil = t + 0.5;
          this.metrics.stepOuts = (this.metrics.stepOuts || 0) + 1;
        }
        return;
      }
    }
    this.muzzleBlockedSince = -1;
    // never fire with a teammate (bot or player) in or near the line of fire
    if (this._friendlyInLine(aimRes.distance)) {
      this.fireBlockedReason = 'friendly_in_line';
      this.metrics.friendlyHolds = (this.metrics.friendlyHolds || 0) + 1;
      this.burstLeft = 0;
      return;
    }
    if (this.burstLeft === 0) {
      const band = cfg.combat.bursts.find((b) => aimRes.distance <= b.maxDist) || cfg.combat.bursts[cfg.combat.bursts.length - 1];
      this.burstLeft = band.shotsMin + Math.floor(this.rng.next() * (band.shotsMax - band.shotsMin + 1));
      this.burstBand = band;
      this.metrics.bursts++;
    }
    // hold the trigger; afterApply() counts the rounds that left and ends the burst (release + pause).
    // A semi-automatic weapon fires once per press: release for one tick after each round (the core queues
    // the next press until the fire interval has passed).
    if (this.semiRelease) {
      this.semiRelease = false;
      this.fireBlockedReason = 'semi_release';
      return;
    }
    cmd.fire = true;
  }

  /**
   * The same two segments the D8 hitscan validates: eye -> muzzle (the muzzle must not be inside / behind
   * geometry) and muzzle -> aim point (static geometry and other bodies).
   */
  _muzzleClear(muzzle, aimPoint) {
    const w = this.sys.world;
    const eye = this.c.getEye(_mEye);
    const ws = this._weapon();
    // the round leaves after this tick's turn: check the current AND the commanded view, eye -> muzzle
    // extended by a small margin (movement within the tick), and muzzle -> aim point
    const v = this.c.controller.velocity;
    const check = (e, m) => {
      _mD.subVectors(m, e);
      const L = _mD.length();
      if (L > 1e-4 && w.raycastStatic(e, _mD.divideScalar(L), L + 0.15)) return false;
      return w.lineOfSight(m, aimPoint, { ignoreId: this.c.id });
    };
    if (!check(eye, muzzle)) return false;
    if (ws && typeof ws.muzzleWorld === 'function' && this.cmd.yaw != null) {
      if (!check(eye, ws.muzzleWorld(eye, this.cmd.yaw, this.cmd.pitch, ws.state.ads, _mM1))) return false;
      _mEye2.set(eye.x + v.x / 60, eye.y, eye.z + v.z / 60);
      if (!check(_mEye2, ws.muzzleWorld(_mEye2, this.cmd.yaw, this.cmd.pitch, ws.state.ads, _mM2))) return false;
    }
    return true;
  }

  /**
   * Is a teammate near the firing line? Checked along the view this tick will actually shoot with (the
   * commanded yaw / pitch plus the weapon's current recoil), with a margin that grows with the angular
   * uncertainty (recoil kick of the next round, turn still in progress).
   */
  _friendlyInLine(dist) {
    const c = this.c;
    c.getEye(_eye);
    const w = this._weapon();
    const rp = w && w.recoil ? w.recoil.pitch : 0;
    const ry = w && w.recoil ? w.recoil.yaw : 0;
    const dirs = [forwardFromYawPitch(this.cmd.yaw ?? c.yaw, (this.cmd.pitch ?? c.pitch) + rp, _fDir1), forwardFromYawPitch(c.yaw + ry, c.pitch + rp, _fDir2)];
    const kickRad = ((w && w.def && w.def.recoil ? w.def.recoil.pitchDeg : 0.6) * 1.2 * Math.PI) / 180;
    for (const o of this.sys.combatants.all()) {
      if (o === c || o.team !== c.team || !o.alive) continue;
      const op = o.controller.position;
      if ((op.x - _eye.x) ** 2 + (op.z - _eye.z) ** 2 > (dist + 2) * (dist + 2)) continue;
      for (const f of dirs) {
        // closest distance from the teammate's body axis (feet..head) to the ray
        for (const h of [0.3, 0.9, 1.5, 1.75]) {
          _w.set(op.x - _eye.x, op.y + Math.min(h, o.controller.height) - _eye.y, op.z - _eye.z);
          const s = _w.dot(f);
          if (s < 0 || s > dist + 1.5) continue;
          const d2 = _w.lengthSq() - s * s;
          const margin = 0.75 + s * kickRad;
          if (d2 < margin * margin) return true;
        }
      }
    }
    return false;
  }

  /** Called after the command was applied: ends a burst whose rounds are out. */
  afterApply(t) {
    const w = this._weapon();
    if (!w) return;
    const sf = w.state.shotsFired;
    if (w !== this.lastShotsWeapon) {
      // weapon switched: its counter is separate (engine counter per weapon)
      this.lastShotsWeapon = w;
      this.lastShotsFired = sf;
      this.burstLeft = 0;
    }
    const newShots = sf - this.lastShotsFired;
    if (newShots > 0) {
      this.lastShotsFired = sf;
      if (w.state.core && w.state.core.fireMode === 'semi') this.semiRelease = true;
      this.metrics.shots += newShots;
      const before = this.burstLeft;
      this.burstLeft = Math.max(0, this.burstLeft - newShots);
      if (this.firstShotPending) {
        const f = this.firstShotPending;
        this.metrics.reactions.push({ targetId: f.targetId, detectedAt: +f.detectedAt.toFixed(3), firstShotAt: +t.toFixed(3), delay: +f.delay.toFixed(3), distance: +f.distance.toFixed(2) });
        if (this.metrics.reactions.length > 40) this.metrics.reactions.shift();
        this.sys.recordReaction(this, f, t);
        this.firstShotPending = null;
      }
      if (before > 0 && this.burstLeft === 0) {
        const b = this.burstBand || this.sys.cfg.combat.bursts[0];
        this.pauseUntil = t + b.pauseMin + this.rng.next() * (b.pauseMax - b.pauseMin);
      }
    }
    if (this.cmd.fire && w.state.state !== 'ready') this.metrics.shotsDuringReload++;
  }

  snapshot(t) {
    const e = this.target;
    const c = this.c;
    const wi = this.weaponInfo();
    return {
      id: c.id,
      name: c.name,
      team: c.team,
      alive: c.alive,
      position: c.position.toArray().map((v) => +v.toFixed(3)),
      yawDeg: +(c.yaw / DEG).toFixed(2),
      pitchDeg: +(c.pitch / DEG).toFixed(2),
      task: this.task,
      taskReason: this.taskReason,
      taskSince: +this.taskSince.toFixed(2),
      lastDecisionAt: this.lastDecisionAt === undefined ? null : +this.lastDecisionAt.toFixed(3),
      scores: this.scores ? Object.fromEntries(Object.entries(this.scores).map(([k, v]) => [k, +v.toFixed(3)])) : null,
      target: e ? { id: e.id, seen: e.seen, conf: +e.conf.toFixed(3), source: e.source, lastKnown: e.pos.toArray().map((v) => +v.toFixed(2)) } : null,
      perception: this.perception.snapshot(),
      memory: this.memory.snapshot(t),
      memoryLog: this.memory.log.slice(-12),
      reaction: { targetId: this.reactionFor, until: +this.reactionUntil.toFixed(3), remaining: +Math.max(0, this.reactionUntil - t).toFixed(3) },
      aim: { sigmaDeg: +this.aim.sigmaDeg.toFixed(3), trackTime: +this.aim.trackTime.toFixed(2), errYawDeg: +(this.aim.errYaw / DEG).toFixed(3), errPitchDeg: +(this.aim.errPitch / DEG).toFixed(3) },
      fire: { burstLeft: this.burstLeft, pauseRemaining: +Math.max(0, this.pauseUntil - t).toFixed(3), blocked: this.fireBlockedReason, fireCmd: this.cmd.fire, reloadCmd: this.cmd.reload },
      weapon: wi ? { state: wi.state, magazine: wi.s.magazine, chamber: wi.s.chamber, reserve: wi.reserve, enabled: wi.enabled } : null,
      cover: this.cover ? { id: this.cover.id, pos: this.cover.pos.toArray().map((v) => +v.toFixed(2)), height: this.cover.height, phase: this.coverPhase, since: +this.coverSince.toFixed(2) } : null,
      post: this.post ? { pos: this.post.pos.toArray().map((v) => +v.toFixed(2)), cover: this.post.cover ? this.post.cover.id : null } : null,
      search: this.search ? { id: this.search.id, pos: this.search.pos.toArray().map((v) => +v.toFixed(2)), arrivedAt: +this.search.arrivedAt.toFixed(2), startedAt: +this.search.startedAt.toFixed(2) } : null,
      move: this.move.snapshot(),
      cmd: { ...this.cmd, yaw: this.cmd.yaw == null ? null : +this.cmd.yaw.toFixed(4), pitch: this.cmd.pitch == null ? null : +this.cmd.pitch.toFixed(4) },
      metrics: { ...this.metrics, reactions: this.metrics.reactions.slice(-8) },
    };
  }
}

export { forwardFromYawPitch };
