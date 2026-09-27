// Aiming of one bot (AI-03). The bot turns through the command (cmd.yaw / cmd.pitch) with a limited turn
// rate (no 180 deg turn in one tick; the Combatant limits it again with the same value), and aims with an
// angular error that is a smooth random process (Ornstein-Uhlenbeck, no per-frame jitter):
//   sigma = (base + perDistance * d/10 + targetSpeed * lateral speed + ownMove * own speed / run speed)
//           * crouch factor * settle multiplier
// The settle multiplier starts at initialErrorMult when a target is (re)acquired and shrinks to 1 over
// settleTime while the bot keeps tracking it. All values come from Shared/config/ai.json.

import { Vector3 } from 'three';
import { wrapAngle } from '../util/math.js';

const DEG = Math.PI / 180;
const _d = new Vector3();

/** Box-Muller normal from a uniform rng. */
export function gaussian(rng) {
  let u = rng.next();
  if (u < 1e-12) u = 1e-12;
  const v = rng.next();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
}

/** Yaw / pitch (radians) that look from `from` to `to` (yaw 0 = -Z, positive = left). */
export function yawPitchTo(from, to) {
  _d.subVectors(to, from);
  const h = Math.hypot(_d.x, _d.z);
  return { yaw: Math.atan2(-_d.x, -_d.z), pitch: Math.atan2(_d.y, h) };
}

/** Angular aim error sigma (degrees) of the model for the given situation (used by tests too). */
export function aimSigmaDeg(cfg, { distance, targetLateralSpeed = 0, ownSpeed = 0, runSpeed = 3.5, crouched = false, trackTime = Infinity }) {
  const A = cfg.aim;
  let s = A.baseErrorDeg + (A.distanceErrorDegPer10m * distance) / 10 + A.targetSpeedErrorDegPerMps * targetLateralSpeed + A.ownMoveErrorDeg * Math.min(1.5, ownSpeed / Math.max(runSpeed, 1e-3));
  if (crouched) s *= A.crouchErrorFactor;
  const settle = A.initialErrorMult - (A.initialErrorMult - 1) * Math.min(1, trackTime / Math.max(A.settleTime, 1e-3));
  return s * settle;
}

export class AimController {
  constructor(bot) {
    this.bot = bot;
    this.nx = 0; // OU state, unit variance
    this.ny = 0;
    this.trackId = null;
    this.trackTime = 0;
    this.sigmaDeg = 0;
    this.errYaw = 0;
    this.errPitch = 0;
    this.desiredYaw = 0;
    this.desiredPitch = 0;
    this.maxTurnPerTick = 0;
  }

  reset() {
    this.trackId = null;
    this.trackTime = 0;
    this.nx = 0;
    this.ny = 0;
  }

  /** Start / continue tracking target `id` (switching resets the settle time). */
  track(id, dt, tracking) {
    if (id !== this.trackId) {
      this.trackId = id;
      this.trackTime = 0;
      // a new target starts with a full-size error (stationary state of the noise process)
      this.nx = gaussian(this.bot.rng);
      this.ny = gaussian(this.bot.rng);
    } else if (tracking) this.trackTime += dt;
    else this.trackTime = Math.max(0, this.trackTime - dt * 2);
  }

  /**
   * Computes the look command towards `aimPoint` (world) with the error model, limited by the turn rate.
   * @returns {{ yaw, pitch, errorDeg, offTargetDeg }} yaw/pitch = command; offTargetDeg = angle between the
   *          current view and the exact direction to the aim point (fire gate)
   */
  aimAt(eye, aimPoint, dt, ctx) {
    const bot = this.bot;
    const cfg = bot.sys.cfg;
    const c = bot.c;
    const { yaw, pitch } = yawPitchTo(eye, aimPoint);
    const distance = eye.distanceTo(aimPoint);
    this.sigmaDeg = aimSigmaDeg(cfg, {
      distance,
      targetLateralSpeed: ctx.targetLateralSpeed || 0,
      ownSpeed: Math.hypot(c.controller.velocity.x, c.controller.velocity.z),
      runSpeed: bot.sys.runSpeed,
      crouched: c.controller.crouched,
      trackTime: this.trackTime,
    });
    // OU process: correlation time tau, stationary variance 1
    const tau = Math.max(cfg.aim.noiseCorrelation, 1e-3);
    const k = Math.exp(-dt / tau);
    const s = Math.sqrt(1 - k * k);
    this.nx = this.nx * k + s * gaussian(bot.rng);
    this.ny = this.ny * k + s * gaussian(bot.rng);
    this.errYaw = this.nx * this.sigmaDeg * DEG;
    this.errPitch = this.ny * this.sigmaDeg * DEG;
    this.desiredYaw = yaw;
    this.desiredPitch = pitch;
    const cmd = this.turnTowards(yaw + this.errYaw, pitch + this.errPitch, dt);
    // fire gate: has the view caught up with where the bot INTENDS to aim (target + its own error)?
    // (accuracy itself is the error model; the gate only stops firing while still turning / reacting)
    const offYaw = wrapAngle(yaw + this.errYaw - cmd.yaw);
    const offPitch = pitch + this.errPitch - cmd.pitch;
    const offAimDeg = Math.hypot(offYaw * Math.cos(pitch), offPitch) / DEG;
    const offTargetDeg = Math.hypot(wrapAngle(yaw - cmd.yaw) * Math.cos(pitch), pitch - cmd.pitch) / DEG;
    return { ...cmd, errorDeg: this.sigmaDeg, offAimDeg, offTargetDeg, distance };
  }

  /** Rate-limited look command towards yaw/pitch (radians) from the combatant's current view. */
  turnTowards(yaw, pitch, dt) {
    const bot = this.bot;
    const cfg = bot.sys.cfg;
    const c = bot.c;
    const maxYaw = cfg.turnRateDegPerSec * DEG * dt;
    const maxPitch = cfg.pitchRateDegPerSec * DEG * dt;
    this.maxTurnPerTick = maxYaw;
    const dy = wrapAngle(yaw - c.yaw);
    const dp = pitch - c.pitch;
    const outYaw = wrapAngle(c.yaw + Math.max(-maxYaw, Math.min(maxYaw, dy)));
    const outPitch = Math.max(-1.35, Math.min(1.35, c.pitch + Math.max(-maxPitch, Math.min(maxPitch, dp))));
    return { yaw: outYaw, pitch: outPitch };
  }

  lookAtPoint(eye, p, dt) {
    const { yaw, pitch } = yawPitchTo(eye, p);
    return this.turnTowards(yaw, pitch * 0.6, dt);
  }
}
