// Aim (gameplay) recoil + a small visual camera roll. Pure logic on the fixed simulation tick, no DOM,
// deterministic (seeded RNG). Used identically by the player and the bots (same WeaponSystem).
//
// `pitch` / `yaw` are the recoil offsets that WeaponSystem adds to the look for BOTH the hitscan aim
// direction and the rendered camera, so the crosshair / sight always shows where the next round goes
// (GUN-03). `roll` is visual only: a rotation about the view axis never moves the screen centre, so it
// adds punch without making the crosshair lie ("camera recoil" vs "gameplay recoil", zadani §6).
//
// Model (all values from weapons.json `<weapon>.recoil`):
//   - every shot pushes a TARGET climb up by pitchDeg (random jitter, stance multiplier: hip / ADS /
//     crouch) and sideways by a random yaw with a bias (right-handed drift);
//   - first shot of a string: full vertical, reduced horizontal; follow-up shots grow a little
//     (followUpGrowth per shot, up to followUpMax), so taps are precise and long strings climb;
//   - the offset follows the target with a short rise time (no one-tick teleport of the view);
//   - recovery pulls the target back exponentially: slowly while the string continues
//     (firingRecovery x recoveryRate), at the full rate once no shot came for recoveryDelay;
//   - partial automatic recovery: when a look owner consumes the transfer (the player, see
//     takeLookTransfer), only recoverFraction of the post-string return is automatic; the rest is
//     moved into the look without any visible jump (the player pulls it down with the mouse). Without a
//     consumer (bots: their aim controller re-aims every tick anyway) recovery is complete.
// The tick length is fixed (1/60 s) and every step is an exact exponential / exact spring solution, so
// the result is identical at every rendering frame rate; the renderer interpolates prev -> current.

import { DEG2RAD, RAD2DEG } from '../util/math.js';
import { springPeakPerUnitVelocity, stepDampedSpring } from './viewModelMotion.js';

export const RECOIL_DEFAULTS = {
  pitchDeg: 0.6,
  pitchJitter: 0.15,
  yawDeg: 0.2,
  yawBias: 0,
  firstShotPitch: 1,
  firstShotYaw: 0.4,
  followUpGrowth: 0.05,
  followUpMax: 1.2,
  stringReset: 0.3,
  riseTime: 0.02,
  recoveryRate: 7,
  recoveryDelay: 0.09,
  firingRecovery: 0.3,
  recoverFraction: 1,
  maxPitchDeg: 6,
  maxYawDeg: 2,
  stance: { ads: 0.75, crouch: 0.85 },
};

export const CAMERA_ROLL_DEFAULTS = { rollDeg: 0, rollBias: 0.3, stiffness: 260, damping: 22, stance: { ads: 0.6, crouch: 0.85 } };

function stanceMul(stance, ads, crouch) {
  const a = Math.min(Math.max(ads || 0, 0), 1);
  const adsM = stance && stance.ads !== undefined ? stance.ads : 1;
  const crM = stance && stance.crouch !== undefined ? stance.crouch : 1;
  return (1 + (adsM - 1) * a) * (crouch ? crM : 1);
}

export class Recoil {
  /**
   * @param {object} def   weapons.json `recoil` block (legacy blocks with only pitchDeg / yawDeg /
   *                       recoveryRate / maxPitchDeg work too, missing keys use RECOIL_DEFAULTS)
   * @param {object} rng   seeded RNG ({ next(), signed() })
   * @param {object} [camera] weapons.json `feel.camera` (visual roll), optional
   */
  constructor(def, rng, camera = null) {
    this.def = def || {};
    this.cfg = { ...RECOIL_DEFAULTS, ...this.def, stance: { ...RECOIL_DEFAULTS.stance, ...(this.def.stance || {}) } };
    this.cam = { ...CAMERA_ROLL_DEFAULTS, ...(camera || {}), stance: { ...CAMERA_ROLL_DEFAULTS.stance, ...((camera && camera.stance) || {}) } };
    this.rollImpulse = this.cam.rollDeg > 0 ? (this.cam.rollDeg * DEG2RAD) / springPeakPerUnitVelocity(this.cam.stiffness, this.cam.damping) : 0;
    this.rng = rng;
    this.lookTransfer = false; // set by the owner of the look (player) that calls takeLookTransfer()
    this.reset();
  }

  reset() {
    this.pitch = 0; // radians, positive = up (aim + camera)
    this.yaw = 0; // radians, positive = left (aim + camera)
    this.targetPitch = 0;
    this.targetYaw = 0;
    this.prevPitch = 0;
    this.prevYaw = 0;
    this.roll = 0; // radians, visual camera roll (positive = counter-clockwise)
    this.rollVel = 0;
    this.prevRoll = 0;
    this.sinceShot = Infinity;
    this.shotIndex = -1;
    this.shots = 0;
    this.pendingPitch = 0;
    this.pendingYaw = 0;
    this.lastKick = { pitchDeg: 0, yawDeg: 0, index: -1, stance: 1 };
  }

  /**
   * One round was fired (called from the fixed tick, after the round used the current offsets).
   * @param {number|object} [opts] legacy: ADS amount 0..1; or { ads: 0..1, crouch: bool }
   */
  kick(opts = 0) {
    const o = typeof opts === 'number' ? { ads: opts } : opts || {};
    const c = this.cfg;
    const st = stanceMul(c.stance, o.ads, o.crouch);
    const follow = this.shots > 0 && this.sinceShot < c.stringReset;
    this.shotIndex = follow ? this.shotIndex + 1 : 0;
    const first = this.shotIndex === 0;
    const grow = first ? c.firstShotPitch : Math.min(c.followUpMax, 1 + c.followUpGrowth * this.shotIndex);
    const yawMul = first ? c.firstShotYaw : 1;
    const kp = c.pitchDeg * grow * (1 + c.pitchJitter * this.rng.signed()) * st;
    const b = Math.max(-1, Math.min(1, c.yawBias || 0));
    // yawBias > 0 drifts to the right (negative yaw); the random part keeps the total within +-yawDeg
    const ky = c.yawDeg * yawMul * st * (this.rng.signed() * (1 - Math.abs(b)) - b);
    const maxP = c.maxPitchDeg * DEG2RAD;
    const maxY = c.maxYawDeg * DEG2RAD;
    this.targetPitch = Math.min(this.targetPitch + kp * DEG2RAD, maxP);
    this.targetYaw = Math.max(-maxY, Math.min(maxY, this.targetYaw + ky * DEG2RAD));
    if (this.rollImpulse > 0) {
      const rb = Math.max(-1, Math.min(1, this.cam.rollBias || 0));
      const sign = this.rng.signed() * (1 - Math.abs(rb)) - rb < 0 ? -1 : 1;
      this.rollVel += sign * this.rollImpulse * stanceMul(this.cam.stance, o.ads, o.crouch);
    }
    this.sinceShot = 0;
    this.shots++;
    this.lastKick = { pitchDeg: kp, yawDeg: ky, index: this.shotIndex, stance: st };
  }

  /** Call at the start of every tick (before kicks) to keep interpolation snapshots. */
  snapshot() {
    this.prevPitch = this.pitch;
    this.prevYaw = this.yaw;
    this.prevRoll = this.roll;
  }

  /** Advances recovery, the rise of the offset towards the target and the visual roll by one tick. */
  recover(dt) {
    if (!(dt > 0)) return;
    const c = this.cfg;
    this.sinceShot += dt;
    const inString = this.sinceShot < c.recoveryDelay;
    const rate = c.recoveryRate * (inString ? c.firingRecovery : 1);
    const d = 1 - Math.exp(-rate * dt);
    const dP = this.targetPitch * d;
    const dY = this.targetYaw * d;
    const transfer = this.lookTransfer && !inString && c.recoverFraction < 1;
    if (transfer) {
      // the automatic part returns the view; the rest moves into the look. Subtracting it from the
      // target, the offset and the interpolation snapshot keeps look + offset continuous (no jump).
      const f = Math.max(0, c.recoverFraction);
      const xp = dP * (1 - f);
      const xy = dY * (1 - f);
      this.targetPitch -= dP;
      this.targetYaw -= dY;
      this.pitch -= xp;
      this.yaw -= xy;
      this.prevPitch -= xp;
      this.prevYaw -= xy;
      this.pendingPitch += xp;
      this.pendingYaw += xy;
    } else {
      this.targetPitch -= dP;
      this.targetYaw -= dY;
    }
    const g = c.riseTime > 0 ? Math.exp(-dt / c.riseTime) : 0;
    this.pitch = this.targetPitch + (this.pitch - this.targetPitch) * g;
    this.yaw = this.targetYaw + (this.yaw - this.targetYaw) * g;
    if (Math.abs(this.pitch) < 1e-7 && Math.abs(this.targetPitch) < 1e-7) this.pitch = this.targetPitch = 0;
    if (Math.abs(this.yaw) < 1e-7 && Math.abs(this.targetYaw) < 1e-7) this.yaw = this.targetYaw = 0;
    if (this.rollImpulse > 0 || this.roll !== 0 || this.rollVel !== 0) {
      [this.roll, this.rollVel] = stepDampedSpring(this.roll, this.rollVel, this.cam.stiffness, this.cam.damping, dt);
      if (Math.abs(this.roll) < 1e-7 && Math.abs(this.rollVel) < 1e-6) this.roll = this.rollVel = 0;
    }
  }

  /**
   * Look change that the automatic recovery did not take back (radians, positive pitch = up). The
   * look owner adds it to its yaw / pitch; enables the partial recovery for this weapon.
   */
  takeLookTransfer() {
    this.lookTransfer = true;
    const out = { pitch: this.pendingPitch, yaw: this.pendingYaw };
    this.pendingPitch = 0;
    this.pendingYaw = 0;
    return out;
  }

  interpolated(alpha) {
    const a = Math.min(Math.max(alpha, 0), 1);
    return {
      pitch: this.prevPitch + (this.pitch - this.prevPitch) * a,
      yaw: this.prevYaw + (this.yaw - this.prevYaw) * a,
      roll: this.prevRoll + (this.roll - this.prevRoll) * a,
    };
  }

  debug() {
    return {
      pitchDeg: this.pitch * RAD2DEG,
      yawDeg: this.yaw * RAD2DEG,
      targetPitchDeg: this.targetPitch * RAD2DEG,
      targetYawDeg: this.targetYaw * RAD2DEG,
      rollDeg: this.roll * RAD2DEG,
      shotIndex: this.shotIndex,
      sinceShot: Number.isFinite(this.sinceShot) ? this.sinceShot : null,
      lastKick: { ...this.lastKick },
      lookTransfer: this.lookTransfer,
    };
  }
}
