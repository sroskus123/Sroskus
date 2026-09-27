// Perception of one bot (AI-01): vision, hearing and damage feed the bot's EnemyMemory.
//
// Vision (every perception tick, ~10 Hz, staggered across bots):
//   range + field-of-view cone (reduced detection in the periphery), line-of-sight rays from the bot's eye
//   to several body points of the enemy (worldQuery.lineOfSight: static geometry + other bodies), and a
//   detection level that grows with a rate depending on distance, visible fraction of the body, periphery,
//   stance and movement. Only a level >= 1 counts as "seen" (nonzero reaction time); a partial level gives
//   a glimpse with an approximate position. Nothing is learned about enemies whose rays are blocked.
// Hearing (events): gunshots and footsteps within a loudness-scaled range, weaker through walls, give an
//   APPROXIMATE position (error grows with distance and occlusion), never the exact one.
// Damage (events): the incoming shot direction with an angular error; the distance is guessed unless the
//   bot already has an estimate (usually from hearing the same shot).

import { Vector3 } from 'three';

const _eye = new Vector3();
const _fwd = new Vector3();
const _to = new Vector3();
const _p = new Vector3();
const _feet = new Vector3();
const _q = new Vector3();
const _chest = new Vector3();
const _pts = [
  { w: 0, p: null, h: 0 },
  { w: 0, p: null, h: 0 },
  { w: 0, p: null, h: 0 },
];

function lerp(a, b, t) {
  return a + (b - a) * t;
}

/** Forward vector of a yaw/pitch pair (yaw 0 = -Z, positive yaw turns left). */
export function forwardFromYawPitch(yaw, pitch, out = new Vector3()) {
  const cp = Math.cos(pitch);
  return out.set(-Math.sin(yaw) * cp, Math.sin(pitch), -Math.cos(yaw) * cp);
}

/** Configured time (s) to detect a fully visible, still, standing enemy in central vision at distance d. */
export function detectTimeAt(cfg, d) {
  const v = cfg.vision;
  if (d <= v.nearRange) return v.detectTimeNear;
  if (d <= v.fullDetectionRange) return lerp(v.detectTimeNear, v.detectTimeFar, (d - v.nearRange) / Math.max(1e-6, v.fullDetectionRange - v.nearRange));
  if (d >= v.range) return Infinity;
  const k = 1 - (d - v.fullDetectionRange) / Math.max(1e-6, v.range - v.fullDetectionRange);
  return v.detectTimeFar / Math.max(k, 1e-6);
}

export class Perception {
  /**
   * @param {object} bot  AI bot (has .c combatant, .memory, .rng, .sys)
   */
  constructor(bot) {
    this.bot = bot;
    this.detect = new Map(); // enemy id -> detection level 0..1.5
    this.lastObs = new Map(); // enemy id -> { t, pos } last visual observation (velocity estimate)
    this.visibleNow = new Set();
    this.lastUpdate = -1;
    this.heard = []; // recent sound stimuli (debug): { t, id, kind, pos (approx), err, occluded }
    this.alert = null; // { pos: Vector3, until, reason } something to look at
    this.underFireUntil = -1;
    this.lastDamage = null; // { t, attackerId, dir: Vector3 }
    this.stats = { raysCast: 0, detections: 0, soundsHeard: 0, soundsIgnored: 0, damageEvents: 0, whiz: 0 };
    this.firstDetect = new Map(); // enemy id -> { visibleSince, detectedAt } (measurements)
  }

  reset() {
    this.detect.clear();
    this.lastObs.clear();
    this.visibleNow.clear();
    this.heard.length = 0;
    this.alert = null;
    this.underFireUntil = -1;
    this.lastDamage = null;
    this.firstDetect.clear();
  }

  forget(id) {
    this.detect.delete(id);
    this.lastObs.delete(id);
    this.visibleNow.delete(id);
    this.firstDetect.delete(id);
  }

  /** Vision pass. `dt` = time since the previous pass of this bot. */
  updateVision(t, dt) {
    const bot = this.bot;
    const sys = bot.sys;
    const cfg = sys.cfg;
    const V = cfg.vision;
    const c = bot.c;
    const world = sys.world;
    c.getEye(_eye);
    forwardFromYawPitch(c.yaw, c.pitch, _fwd);
    const cosHalfFov = Math.cos(((V.fovDeg / 2) * Math.PI) / 180);
    const cosCentral = Math.cos(((V.centralFovDeg / 2) * Math.PI) / 180);
    this.visibleNow.clear();
    for (const e of sys.combatants.all()) {
      if (e === c || e.team === c.team) continue;
      if (!e.alive) {
        this.detect.delete(e.id);
        continue;
      }
      // cheap range / cone rejection on the feet position before touching the hit shapes
      const ep = e.controller.position;
      const rx = ep.x - _eye.x;
      const rz = ep.z - _eye.z;
      if (rx * rx + rz * rz > (V.range + 1) * (V.range + 1)) {
        this._noSight(e, t, dt);
        continue;
      }
      const shapes = e.hitShapes();
      const head = shapes[0];
      const torso = shapes[1];
      // body points inside the hit shapes (lineOfSight skips a body that contains the end point)
      const pts = _pts;
      pts[0].w = V.bodyPoints[0].weight;
      pts[0].p = head.center;
      pts[0].h = head.center.y;
      pts[1].w = V.bodyPoints[1].weight;
      pts[1].p = _chest.copy(torso.a).lerp(torso.b, 0.75);
      pts[1].h = _chest.y;
      pts[2].w = V.bodyPoints[2].weight;
      pts[2].p = torso.a;
      pts[2].h = torso.a.y;
      _to.subVectors(pts[1].p, _eye);
      const d = _to.length();
      let level = this.detect.get(e.id) || 0;
      let rate = 0;
      let vis = 0;
      let aimH = 0;
      let bestW = -1;
      if (d <= V.range && d > 1e-3) {
        _to.divideScalar(d);
        const cosA = _to.dot(_fwd);
        if (cosA >= cosHalfFov) {
          for (const bp of pts) {
            this.stats.raysCast++;
            if (world.lineOfSight(_eye, bp.p, { ignoreId: c.id })) {
              vis += bp.w;
              // aim at the visible point with the largest weight (chest first)
              if (bp.w > bestW) {
                bestW = bp.w;
                aimH = bp.h - e.controller.position.y;
              }
            }
          }
          if (vis >= V.minVisibility) {
            const T = detectTimeAt(cfg, d);
            rate = (1 / T) * vis * (cosA >= cosCentral ? 1 : V.peripheralFactor);
            if (e.controller.crouched) rate *= V.crouchFactor;
            const sp = Math.hypot(e.controller.velocity.x, e.controller.velocity.z);
            if (sp >= V.movingSpeed) rate *= V.movingFactor;
          }
        }
      }
      let fd = this.firstDetect.get(e.id);
      if (!fd) {
        fd = { visibleSince: -1, detectedAt: -1 };
        this.firstDetect.set(e.id, fd);
      }
      if (rate > 0) {
        // became visible somewhere in the last interval: count half of it (not the whole interval, which would
        // let a target that appeared just before this pass be detected up to one interval early)
        const newly = fd.visibleSince < 0;
        if (newly) fd.visibleSince = t - dt * 0.5;
        level = Math.min(1.5, level + rate * (newly ? dt * 0.5 : dt));
      } else {
        level = Math.max(0, level - V.detectDecayPerSec * dt);
        if (level === 0) fd.visibleSince = -1;
      }
      this.detect.set(e.id, level);
      const feet = e.controller.position;
      if (rate > 0 && level >= 1) {
        // SEEN: position observed now (the only way the true position enters the memory)
        let vel = null;
        const prev = this.lastObs.get(e.id);
        if (prev && prev.t >= 0 && t - prev.t > 1e-3 && t - prev.t < 0.35) vel = _p.subVectors(feet, prev.pos).divideScalar(t - prev.t).setY(0);
        const entry = bot.memory.get(e.id);
        const wasSeen = entry && entry.seen;
        bot.memory.see(e.id, e.team, t, feet, vel, aimH);
        if (!wasSeen) this.stats.detections++;
        const lo = this.lastObs.get(e.id);
        if (lo) {
          lo.t = t;
          lo.pos.copy(feet);
        } else this.lastObs.set(e.id, { t, pos: feet.clone() });
        this.visibleNow.add(e.id);
        if (fd.detectedAt < 0) fd.detectedAt = t;
      } else {
        bot.memory.markUnseen(e.id);
        const lo = this.lastObs.get(e.id);
        if (lo) lo.t = -1;
        if (rate > 0 && level >= V.glimpseLevel) {
          // partial detection: something moved there -> approximate position, look at it
          const err = 1.0 + 0.05 * d;
          const a = bot.rng.next() * Math.PI * 2;
          const r = err * Math.sqrt(bot.rng.next());
          _feet.set(feet.x + Math.cos(a) * r, feet.y, feet.z + Math.sin(a) * r);
          bot.memory.glimpse(e.id, e.team, t, _feet, 0.3);
          this.setAlert(_feet, t, 'glimpse');
        }
      }
    }
    this.lastUpdate = t;
  }

  /** Enemy out of range: detection decays, memory marked not visible. */
  _noSight(e, t, dt) {
    const V = this.bot.sys.cfg.vision;
    const level = Math.max(0, (this.detect.get(e.id) || 0) - V.detectDecayPerSec * dt);
    this.detect.set(e.id, level);
    this.bot.memory.markUnseen(e.id);
    const lo = this.lastObs.get(e.id);
    if (lo) lo.t = -1;
    const fd = this.firstDetect.get(e.id);
    if (fd && level === 0) fd.visibleSince = -1;
  }

  setAlert(pos, t, reason) {
    const V = this.bot.sys.cfg.vision;
    if (!this.alert) this.alert = { pos: new Vector3(), until: 0, reason };
    this.alert.pos.copy(pos);
    this.alert.until = t + V.alertTurnTime;
    this.alert.reason = reason;
  }

  /**
   * Sound event (gunshot / footstep) from an enemy at `pos` with `loudness`. For a gunshot, `shotDir` and
   * `shotLen` (distance the round flew before it hit something) decide whether it passed close by (near miss).
   * @returns {boolean} heard
   */
  onSound(t, kind, srcId, srcTeam, pos, loudness, shotDir = null, shotLen = Infinity) {
    const bot = this.bot;
    const sys = bot.sys;
    const H = sys.cfg.hearing;
    const c = bot.c;
    c.getEye(_eye);
    const d = _eye.distanceTo(pos);
    let range = (kind === 'gunshot' ? H.gunshotRange : H.footstepRange) * (loudness ?? 1);
    // occlusion: static geometry between the ear and the source
    _to.subVectors(pos, _eye);
    const len = _to.length();
    let occluded = false;
    if (len > 1e-3) {
      _to.divideScalar(len);
      occluded = !!sys.world.raycastStatic(_eye, _to, Math.max(0, len - 0.05));
    }
    if (occluded) range *= H.occlusionFactor;
    // near miss ("whiz"): the enemy's shot passed close to the bot
    let whiz = false;
    if (kind === 'gunshot' && shotDir) {
      _p.subVectors(c.getEye(_q), pos);
      const s = _p.dot(shotDir);
      // the round must have got that far (it stops at the first wall or body it hits)
      if (s > 0 && s < Math.min(150, shotLen + 0.5)) {
        const closest = Math.sqrt(Math.max(0, _p.lengthSq() - s * s));
        if (closest < H.whizRadius) whiz = true;
      }
    }
    if (d > range && !whiz) {
      this.stats.soundsIgnored++;
      return false;
    }
    const err = (H.errorBase + H.errorPerMeter * d) * (occluded ? H.occludedErrorMult : 1);
    const a = bot.rng.next() * Math.PI * 2;
    const r = err * Math.sqrt(bot.rng.next());
    // feet estimate: gunshots come from ~1.5 m above the feet
    const footY = kind === 'gunshot' ? pos.y - 1.45 : pos.y;
    _feet.set(pos.x + Math.cos(a) * r, footY, pos.z + Math.sin(a) * r);
    const base = kind === 'gunshot' ? H.confidenceGunshot : H.confidenceFootstep;
    const conf = Math.max(0.05, base * (1 - 0.5 * Math.min(1, d / Math.max(range, 1e-3))) * (whiz ? 1.3 : 1));
    bot.memory.hear(srcId, srcTeam, t, _feet, Math.min(0.9, conf));
    this.setAlert(_feet, t, kind);
    if (whiz) {
      this.underFireUntil = Math.max(this.underFireUntil, t + sys.cfg.damage.underFireTime);
      this.stats.whiz++;
    }
    this.stats.soundsHeard++;
    this.heard.push({ t: +t.toFixed(3), id: srcId, kind, pos: [+_feet.x.toFixed(2), +_feet.y.toFixed(2), +_feet.z.toFixed(2)], err: +err.toFixed(2), occluded, distance: +d.toFixed(2), whiz });
    if (this.heard.length > 12) this.heard.shift();
    return true;
  }

  /** The bot was hit. fromDir = travel direction of the shot (attacker -> victim), may be null. */
  onDamaged(t, attackerId, attackerTeam, fromDir) {
    const bot = this.bot;
    const sys = bot.sys;
    const D = sys.cfg.damage;
    this.stats.damageEvents++;
    this.underFireUntil = t + D.underFireTime;
    if (attackerId == null || attackerTeam === bot.c.team) return;
    let dir = null;
    if (fromDir && Math.hypot(fromDir.x, fromDir.z) > 1e-6) {
      dir = new Vector3(-fromDir.x, 0, -fromDir.z).normalize();
      const err = ((bot.rng.next() * 2 - 1) * D.directionErrorDeg * Math.PI) / 180;
      const cs = Math.cos(err);
      const sn = Math.sin(err);
      dir.set(dir.x * cs - dir.z * sn, 0, dir.x * sn + dir.z * cs);
    }
    this.lastDamage = { t, attackerId, dir };
    if (!dir) return;
    const e = bot.memory.get(attackerId);
    const recent = e && t - e.time < 2.5;
    // distance unknown: keep an existing estimate if it lies roughly in that direction, else guess
    let keep = false;
    if (recent) {
      _to.subVectors(e.pos, bot.c.position).setY(0);
      const L = _to.length();
      if (L > 1e-3 && _to.divideScalar(L).dot(dir) > Math.cos((35 * Math.PI) / 180)) keep = true;
    }
    const guess = recent ? Math.max(3, bot.c.position.distanceTo(e.pos)) : D.guessDistance;
    _feet.copy(bot.c.position).addScaledVector(dir, guess);
    bot.memory.damage(attackerId, attackerTeam, t, _feet, D.confidence, { keepPosition: keep });
    this.setAlert(keep ? e.pos : _feet, t, 'damage');
  }

  get underFire() {
    return this.bot.sys.time < this.underFireUntil;
  }

  snapshot() {
    const detect = {};
    for (const [id, v] of this.detect) if (v > 0) detect[id] = +v.toFixed(3);
    return {
      seen: [...this.visibleNow],
      detect,
      heard: this.heard.slice(-6),
      alert: this.alert && this.alert.until > this.bot.sys.time ? { pos: this.alert.pos.toArray().map((v) => +v.toFixed(2)), reason: this.alert.reason } : null,
      underFire: this.underFire,
      lastDamage: this.lastDamage ? { t: +this.lastDamage.t.toFixed(3), attackerId: this.lastDamage.attackerId, dir: this.lastDamage.dir ? this.lastDamage.dir.toArray().map((v) => +v.toFixed(3)) : null } : null,
      stats: { ...this.stats },
      firstDetect: Object.fromEntries([...this.firstDetect.entries()].map(([k, v]) => [k, { visibleSince: +v.visibleSince.toFixed(3), detectedAt: +v.detectedAt.toFixed(3) }])),
    };
  }
}
