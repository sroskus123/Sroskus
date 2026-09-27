// Movement of one bot (AI-02): path following on the navmesh (string-pulled corners), local avoidance
// between combatants (separation + consistent right-hand sidestep for agents ahead), stuck detection
// (low progress while wanting to move within `stuck.window`) and recovery WITHOUT teleporting:
//   1. another combatant blocks the way -> sidestep and wait briefly, then repath;
//   2. otherwise the navmesh ahead is marked blocked (shared, temporary) and a new route is searched;
//   3. no route -> alternative goal near the original one; repeated failure -> short back-off.
// The output is a desired horizontal direction + speed mode, turned into moveX / moveZ relative to the
// command yaw by the bot.

import { Vector3 } from 'three';

const _dir = new Vector3();
const _sep = new Vector3();
const _tmp = new Vector3();
const _ahead = new Vector3();

export class PathFollower {
  constructor(bot) {
    this.bot = bot;
    this.goal = null; // Vector3
    this.goalTolerance = 0.5;
    this.path = []; // Vector3 waypoints (after the start)
    this.index = 0;
    this.pathTime = -1;
    this.pathFailed = false;
    this.arrived = false;
    this.wantMove = false;
    this.samples = []; // { t, x, z } position history for stuck detection
    this.stuckEvents = [];
    this.recoveries = 0;
    this.backoffUntil = -1;
    this.backoffDir = new Vector3();
    this.waitUntil = -1;
    this.sidestep = 0;
    this.lastStuck = null;
    this.desired = new Vector3();
    this.moveSpeed = 'run';
    this.avoidSide = bot.index % 2 === 0 ? 1 : -1;
    this.stats = { repaths: 0, pathFailures: 0, stuckEvents: 0, blocksAdded: 0, altGoals: 0, backoffs: 0, teammateWaits: 0 };
  }

  reset() {
    this.goal = null;
    this.path = [];
    this.index = 0;
    this.arrived = false;
    this.wantMove = false;
    this.samples.length = 0;
    this.backoffUntil = -1;
    this.waitUntil = -1;
    this.recoveries = 0;
  }

  get hasPath() {
    return this.path.length > 0 && this.index < this.path.length;
  }

  /** Sets (or keeps) the movement goal. Repaths when the goal moved more than goalMoveRepath. */
  setGoal(p, { tolerance = null, force = false } = {}) {
    const M = this.bot.sys.cfg.movement;
    const tol = tolerance ?? M.arriveRadius;
    if (!force && this.goal && this.goal.distanceTo(p) < M.goalMoveRepath && !this.pathFailed) {
      this.goalTolerance = tol;
      return true;
    }
    if (!this.goal) this.goal = new Vector3();
    this.goal.copy(p);
    this.goalTolerance = tol;
    this.arrived = false;
    this.recoveries = 0;
    return this.repath();
  }

  clearGoal() {
    this.goal = null;
    this.path = [];
    this.index = 0;
    this.arrived = false;
    this.wantMove = false;
  }

  repath() {
    const bot = this.bot;
    const nav = bot.sys.nav;
    this.pathTime = bot.sys.time;
    if (!nav || !this.goal) {
      this.path = [];
      this.pathFailed = !nav ? false : true;
      return false;
    }
    this.stats.repaths++;
    const r = nav.findPath(bot.c.position, this.goal, { allowPartial: true, cost: bot.sys.dangerCost(bot.c.team) });
    if (!r.ok) {
      this.path = [];
      this.index = 0;
      this.pathFailed = true;
      this.stats.pathFailures++;
      return false;
    }
    // a partial path that ends where the bot already stands leads nowhere (e.g. every way on is blocked):
    // report the move as failed so the decision layer chooses another goal instead of pushing in place
    const end = r.points.length ? r.points[r.points.length - 1] : null;
    if (r.partial && (!end || Math.hypot(end.x - bot.c.position.x, end.z - bot.c.position.z) < 1.5)) {
      this.path = [];
      this.index = 0;
      this.pathFailed = true;
      this.stats.pathFailures++;
      this.stats.partialToSelf = (this.stats.partialToSelf || 0) + 1;
      if (bot.onMoveFailed && !this._inMoveFailed) {
        this._inMoveFailed = true;
        try {
          bot.onMoveFailed('no_route');
        } finally {
          this._inMoveFailed = false;
        }
      }
      return false;
    }
    // stuck detection measures progress as the drop of the remaining path length: a new path (detour,
    // periodic refresh) changes that length without any movement, so the samples are rebased on it
    const before = this.samples.length ? this.remainingLength() : 0;
    this.path = r.points;
    this.index = 0;
    this.pathFailed = false;
    this.partial = r.partial;
    if (this.samples.length) {
      const delta = this.remainingLength() - before;
      for (const sm of this.samples) sm.rem += delta;
    }
    return true;
  }

  distanceToGoal() {
    if (!this.goal) return 0;
    const p = this.bot.c.position;
    return Math.hypot(this.goal.x - p.x, this.goal.z - p.z);
  }

  /** Remaining path length from the current position (approximation for decisions). */
  remainingLength() {
    if (!this.hasPath) return this.distanceToGoal();
    const p = this.bot.c.position;
    let L = Math.hypot(this.path[this.index].x - p.x, this.path[this.index].z - p.z);
    for (let i = this.index + 1; i < this.path.length; i++) L += this.path[i].distanceTo(this.path[i - 1]);
    return L;
  }

  /**
   * One tick: returns the desired world direction (XZ unit or zero) in this.desired and whether the bot
   * wants to move.
   */
  update(dt) {
    const bot = this.bot;
    const sys = bot.sys;
    const M = sys.cfg.movement;
    const t = sys.time;
    const pos = bot.c.position;
    this.desired.set(0, 0, 0);
    this.wantMove = false;
    this._trackRecovery(t, pos);
    if (!this.goal) {
      this._sample(t, pos, false);
      return this.desired;
    }
    // arrival
    const dg = Math.hypot(this.goal.x - pos.x, this.goal.z - pos.z);
    if (dg <= this.goalTolerance && Math.abs(this.goal.y - pos.y) < 1.2) {
      this.arrived = true;
      this.path = [];
      this._sample(t, pos, false);
      this._separationOnly();
      return this.desired;
    }
    this.arrived = false;
    if (!this.hasPath) {
      if (t - this.pathTime > 0.5) this.repath();
      if (!this.hasPath) {
        this._sample(t, pos, false);
        return this.desired;
      }
    } else if (t - this.pathTime > M.repathInterval && !this.partial && !this._halted(t, pos)) {
      // periodic refresh keeps paths valid when blocks expire / appear (not while the bot is pressed in place:
      // then the stuck detector decides and repaths itself; a refreshed path with a slightly different corner
      // would only make the bot shuffle sideways and delay the detection)
      this.repath();
      if (!this.hasPath) return this.desired;
    }
    // advance waypoints
    while (this.index < this.path.length) {
      const w = this.path[this.index];
      const last = this.index === this.path.length - 1;
      const r = last ? this.goalTolerance : M.waypointRadius;
      if (Math.hypot(w.x - pos.x, w.z - pos.z) <= r && Math.abs(w.y - pos.y) < 1.4) this.index++;
      else break;
    }
    if (this.index >= this.path.length) {
      this._sample(t, pos, false);
      return this.desired;
    }
    const w = this.path[this.index];
    _dir.set(w.x - pos.x, 0, w.z - pos.z);
    const L = _dir.length();
    if (L > 1e-4) _dir.divideScalar(L);
    this.wantMove = true;

    // back-off (stuck recovery) overrides the path direction for a moment
    if (t < this.backoffUntil) _dir.copy(this.backoffDir);
    // waiting for a teammate to clear the way: sidestep
    if (t < this.waitUntil) {
      const fx = _dir.x;
      const fz = _dir.z;
      _dir.set(-fz * this.sidestep * 0.8 + fx * 0.2, 0, fx * this.sidestep * 0.8 + fz * 0.2).normalize();
    }

    // local avoidance
    const sep = this._separation(pos, _dir);
    this.desired.copy(_dir).addScaledVector(sep, M.separationWeight);
    const dl = this.desired.length();
    if (dl > 1e-4) this.desired.divideScalar(dl);
    this._sample(t, pos, true);
    this._stuckCheck(t, pos, _dir);
    return this.desired;
  }

  _separationOnly() {
    const M = this.bot.sys.cfg.movement;
    const sep = this._separation(this.bot.c.position, null);
    if (sep.lengthSq() > 0.04) {
      this.desired.copy(sep).multiplyScalar(M.separationWeight);
      if (this.desired.length() > 1) this.desired.normalize();
      this.wantMove = false;
      this.nudging = true;
    } else this.nudging = false;
  }

  /** Separation from nearby bodies + sidestep for bodies ahead in the movement direction. */
  _separation(pos, dir) {
    const sys = this.bot.sys;
    const M = sys.cfg.movement;
    _sep.set(0, 0, 0);
    const R = M.separationRadius;
    this.blockedBy = null;
    const reach = Math.max(R, dir ? M.avoidLookAhead : 0);
    for (const o of sys.combatants.all()) {
      if (o === this.bot.c) continue;
      const op = o.controller.position;
      if (Math.abs(op.x - pos.x) > reach || Math.abs(op.z - pos.z) > reach || Math.abs(op.y - pos.y) > 1.5 || !o.alive) continue;
      _tmp.set(pos.x - op.x, 0, pos.z - op.z);
      const d = _tmp.length();
      if (d < R) {
        if (d < 1e-3) _tmp.set(this.avoidSide, 0, 0);
        else _tmp.divideScalar(d);
        _sep.addScaledVector(_tmp, (R - d) / R);
      }
      if (dir) {
        // agent ahead within the look-ahead corridor -> step to our side
        _ahead.set(op.x - pos.x, 0, op.z - pos.z);
        const along = _ahead.dot(dir);
        if (along > 0 && along < M.avoidLookAhead) {
          // right of dir = (-dir.z, dir.x) (three.js XZ, same as the controller); lateral > 0: other is left
          const lateral = _ahead.x * dir.z - _ahead.z * dir.x;
          if (Math.abs(lateral) < M.avoidRadius) {
            const side = Math.abs(lateral) < 0.1 ? this.avoidSide : lateral > 0 ? 1 : -1; // +1 = step right
            const w = (1 - along / M.avoidLookAhead) * 0.8;
            _sep.x += -dir.z * side * w;
            _sep.z += dir.x * side * w;
            if (along < 1.0) this.blockedBy = o;
          }
        }
      }
    }
    return _sep;
  }

  /** Wanted to move for the last 0.6 s but moved less than 0.1 m. */
  _halted(t, pos) {
    const s = this.samples;
    if (!s.length || t - s[0].t < 0.6) return false;
    let ref = null;
    for (let i = s.length - 1; i >= 0; i--) {
      if (t - s[i].t >= 0.6) {
        ref = s[i];
        break;
      }
    }
    return !!ref && Math.hypot(pos.x - ref.x, pos.z - ref.z) < 0.1;
  }

  _sample(t, pos, moving) {
    const s = this.samples;
    if (!moving) {
      s.length = 0;
      return;
    }
    // a jump no walking body can make (placement by a test / debugging): the history no longer applies
    if (s.length && Math.hypot(pos.x - s[s.length - 1].x, pos.z - s[s.length - 1].z) > 1.0 + 8 * (t - s[s.length - 1].t)) s.length = 0;
    if (s.length === 0 || t - s[s.length - 1].t >= 0.1) s.push({ t, x: pos.x, z: pos.z, rem: this.remainingLength() });
    const W = this.bot.sys.cfg.stuck.window;
    while (s.length > 2 && t - s[1].t >= W) s.shift();
  }

  /** Side (+1 right / -1 left of dir) with more free space for a sidestep. */
  _freeSide(pos, dir) {
    const w = this.bot.sys.world;
    if (!w || typeof w.raycastStatic !== 'function') return this.avoidSide;
    _tmp.set(pos.x, pos.y + 0.5, pos.z);
    const r = w.raycastStatic(_tmp, _ahead.set(-dir.z, 0, dir.x), 1.2);
    const l = w.raycastStatic(_tmp, _dir.set(dir.z, 0, -dir.x), 1.2);
    const dr = r ? r.distance : 1.2;
    const dl = l ? l.distance : 1.2;
    if (Math.abs(dr - dl) < 0.05) return this.avoidSide;
    return dr > dl ? 1 : -1;
  }

  /**
   * A stuck event counts as recovered once the bot got more than 1 m away from where it was stuck. A new stuck
   * event before the previous one recovered continues the same episode: the open events form a chain and are
   * all closed by the recovery that finally ends it (their recovery time includes the whole episode).
   */
  _trackRecovery(t, pos) {
    const ev = this.lastStuck;
    if (!ev || ev.recoveredAt !== null) return;
    // recovered: moved more than 1 m away from where it was stuck, or reached / dropped the goal (the
    // decision layer chose to stay, e.g. it arrived at a cover next to the stuck spot)
    const moved = Math.hypot(pos.x - ev.pos[0], pos.z - ev.pos[2]) > 1.0;
    const noLongerMoving = !this.goal || this.arrived;
    if (moved || noLongerMoving) {
      const how = moved ? 'moved_away' : this.arrived ? 'arrived' : 'goal_dropped';
      const chain = this.openStuck && this.openStuck.includes(ev) ? this.openStuck : [ev];
      for (const e of chain) {
        e.recoveredAt = +t.toFixed(3);
        e.recoveryTime = +(t - e.t).toFixed(3);
        e.recoveredBy = e === ev ? how : `chain:${how}`;
      }
      this.openStuck = [];
      this.recoveries = 0;
    }
  }

  _stuckCheck(t, pos, dir) {
    const bot = this.bot;
    const sys = bot.sys;
    const S = sys.cfg.stuck;
    const s = this.samples;
    if (s.length < 2 || t < this.backoffUntil || t < this.waitUntil) return;
    const first = s[0];
    if (t - first.t < S.window) return;
    const moved = Math.hypot(pos.x - first.x, pos.z - first.z);
    // progress = the remaining path got shorter (sliding along the face of an obstacle the navmesh does not
    // know moves the bot but brings it no closer along its path)
    const progressed = first.rem - this.remainingLength();
    if (moved >= S.minProgress) {
      if (progressed >= S.minProgress) return;
      // moving without path progress counts only when pressed against static geometry (sliding along it);
      // bodies pushing each other around in a crowd are not a stuck bot
      _tmp.set(pos.x, pos.y + 0.5, pos.z);
      const face = sys.world && typeof sys.world.raycastStatic === 'function' ? sys.world.raycastStatic(_tmp, dir, 0.6) : null;
      if (!face) return;
    }
    // STUCK: wanted to move for `window` seconds with less than minProgress
    this.stats.stuckEvents++;
    const stuckSince = first.t;
    const ev = { t, since: +stuckSince.toFixed(3), detectDelay: +(t - stuckSince).toFixed(3), pos: [+pos.x.toFixed(2), +pos.y.toFixed(2), +pos.z.toFixed(2)], action: '', recoveredAt: null, recoveryTime: null, goal: this.goal ? this.goal.toArray().map((v) => +v.toFixed(2)) : null };
    this.samples.length = 0;
    this.recoveries++;
    // what is in the way? a static obstacle the navmesh does not know (only if it is BEFORE the next
    // waypoint), or other bodies (congestion)
    const wp = this.path[this.index];
    const toWp = wp ? Math.hypot(wp.x - pos.x, wp.z - pos.z) : 0.9;
    _tmp.set(pos.x, pos.y + 0.5, pos.z);
    const staticAhead = sys.world && typeof sys.world.raycastStatic === 'function' ? sys.world.raycastStatic(_tmp, dir, Math.min(0.9, toWp + 0.05)) : null;
    let bodiesNear = this.blockedBy;
    if (!bodiesNear) {
      for (const o of sys.combatants.all()) {
        if (o === bot.c || !o.alive) continue;
        const op = o.controller.position;
        if (Math.hypot(op.x - pos.x, op.z - pos.z) < 1.3 && Math.abs(op.y - pos.y) < 1.5) {
          bodiesNear = o;
          break;
        }
      }
    }
    const op = bodiesNear ? bodiesNear.controller.position : null;
    const ov = bodiesNear ? bodiesNear.controller.velocity : null;
    // a body that stands still (arrived at its own spot) never runs a stuck check of its own, so it never
    // yields: waiting for it is pointless
    const otherStill = !!ov && Math.hypot(ov.x, ov.z) < 0.3;
    const goalTaken = !!(op && this.goal && otherStill && Math.hypot(this.goal.x - op.x, this.goal.z - op.z) < 1.0);
    if (bodiesNear && !staticAhead && goalTaken) {
      // somebody stands on our goal: step aside and let the decision layer pick another spot
      this.sidestep = this._freeSide(pos, dir);
      this.waitUntil = t + 0.5;
      this.stats.teammateWaits++;
      ev.action = `goal_taken_by:${bodiesNear.id}`;
      bot.onMoveFailed && bot.onMoveFailed('congestion');
    } else if (bodiesNear && !staticAhead && this.recoveries <= 2) {
      // congestion: the bot with lower priority yields (sidestep to the free side + wait); never block the
      // navmesh because of bodies. Priority: the player and lower bot index go first; a body standing still
      // does not move out of the way, so the moving bot steps around it.
      const other = sys.byId ? sys.byId.get(bodiesNear.id) : null;
      const iYield = !other || otherStill || other.index < bot.index || bodiesNear.isPlayer;
      if (iYield) {
        this.sidestep = this._freeSide(pos, dir);
        this.waitUntil = t + S.teammateWaitTime;
      }
      this.stats.teammateWaits++;
      ev.action = iYield ? `yield_to:${bodiesNear.id}` : `priority_over:${bodiesNear.id}`;
    } else if (sys.nav && staticAhead && this.recoveries <= S.maxRecoveries) {
      // unknown static obstacle: block the navmesh just ahead and search another route
      // block the ground the obstacle covers (its footprint); if the navmesh already knows the obstacle
      // (nothing covered), block the navmesh just ahead of the bot instead
      const box = sys.solidBox ? sys.solidBox(staticAhead.solidId) : null;
      const fb = box && typeof sys.nav.blockFootprint === 'function' ? sys.nav.blockFootprint(box, S.blockTtl, { reason: `stuck:${bot.c.id}`, keepFree: [pos] }) : -1;
      if (fb < 0) {
        _tmp.copy(pos).addScaledVector(dir, 1.2);
        sys.nav.blockArea(_tmp, S.blockRadius, S.blockTtl, { reason: `stuck:${bot.c.id}`, keepFree: [pos], ahead: { origin: pos, dir } });
      }
      ev.block = fb >= 0 ? 'footprint' : 'ahead';
      this.stats.blocksAdded++;
      const ok = this.repath();
      ev.action = ok ? 'block_and_repath' : 'block_no_route';
      ev.obstacle = staticAhead.solidId || null;
      if (!ok && this.goal) {
        const alt = sys.nav.randomPointNear(this.goal, 5, () => bot.rng.next());
        if (alt) {
          this.goal.copy(alt);
          this.repath();
          this.stats.altGoals++;
          ev.action = 'alternative_goal';
          bot.onMoveFailed && bot.onMoveFailed('no_route');
        }
      }
    } else {
      // snagged, or congestion that did not clear: back off away from the obstacle / body, repath and let
      // the decision layer choose another goal (new cover / post) instead of pushing forever
      this.backoffDir.copy(dir).negate();
      if (bodiesNear) {
        _tmp.set(pos.x - bodiesNear.controller.position.x, 0, pos.z - bodiesNear.controller.position.z);
        if (_tmp.lengthSq() > 1e-6) this.backoffDir.add(_tmp.normalize()).normalize();
      }
      this.backoffUntil = t + S.backoffTime;
      this.stats.backoffs++;
      ev.action = 'backoff_new_goal';
      this.pathTime = -Infinity; // repath after the back-off
      this.recoveries = 0;
      bot.onMoveFailed && bot.onMoveFailed(bodiesNear ? 'congestion' : 'stuck');
    }
    if (!this.openStuck || !this.lastStuck || this.lastStuck.recoveredAt !== null) this.openStuck = [];
    this.openStuck.push(ev);
    this.lastStuck = ev;
    this.stuckEvents.push(ev);
    if (this.stuckEvents.length > 20) this.stuckEvents.shift();
    sys.recordStuck(bot, ev);
  }

  snapshot() {
    return {
      goal: this.goal ? this.goal.toArray().map((v) => +v.toFixed(2)) : null,
      path: this.path.map((p) => [+p.x.toFixed(2), +p.y.toFixed(2), +p.z.toFixed(2)]),
      index: this.index,
      arrived: this.arrived,
      wantMove: this.wantMove,
      pathFailed: this.pathFailed,
      partial: !!this.partial,
      stuckEvents: this.stuckEvents.slice(-5),
      stats: { ...this.stats },
    };
  }
}
