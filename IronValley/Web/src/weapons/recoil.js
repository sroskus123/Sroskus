// Camera recoil with recovery. Offsets are added to the look direction, so the crosshair
// and the aim ray always agree with what the camera shows. Deterministic (seeded RNG).

import { DEG2RAD } from '../util/math.js';

export class Recoil {
  constructor(def, rng) {
    this.def = def;
    this.rng = rng;
    this.pitch = 0; // radians, positive = up
    this.yaw = 0; // radians, positive = left
    this.prevPitch = 0;
    this.prevYaw = 0;
  }

  kick(adsFactor = 0) {
    const mult = 1 - 0.3 * adsFactor; // steadier when aiming
    this.pitch += this.def.pitchDeg * (0.85 + 0.3 * this.rng.next()) * mult * DEG2RAD;
    this.yaw += this.def.yawDeg * this.rng.signed() * mult * DEG2RAD;
    const maxP = this.def.maxPitchDeg * DEG2RAD;
    if (this.pitch > maxP) this.pitch = maxP;
  }

  /** Call at the start of every tick (before kicks) to keep interpolation snapshots. */
  snapshot() {
    this.prevPitch = this.pitch;
    this.prevYaw = this.yaw;
  }

  recover(dt) {
    const f = Math.exp(-this.def.recoveryRate * dt);
    this.pitch *= f;
    this.yaw *= f;
    if (Math.abs(this.pitch) < 1e-6) this.pitch = 0;
    if (Math.abs(this.yaw) < 1e-6) this.yaw = 0;
  }

  reset() {
    this.pitch = this.yaw = this.prevPitch = this.prevYaw = 0;
  }

  interpolated(alpha) {
    return {
      pitch: this.prevPitch + (this.pitch - this.prevPitch) * alpha,
      yaw: this.prevYaw + (this.yaw - this.prevYaw) * alpha,
    };
  }
}
