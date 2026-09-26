// View-model motion state (no rendering, no DOM, testable in Node).
//
// Recoil kick springs advance on the fixed simulation tick, like the camera recoil, and the
// renderer interpolates between the last two tick states. Each tick uses the exact solution of
// the damped spring, so the result is stable for any step length and identical at every frame
// rate (the old per-frame explicit integration blew up below ~15 FPS and changed the kick
// strength with FPS).
//
// Sway and the sprint pose are per-frame smoothing driven by rates, not by per-frame deltas:
// sway follows the look angular velocity (rad/s) through an exponential filter, so the same
// mouse speed gives the same sway at 30, 60 or 144 FPS.

import { Euler, Vector3 } from 'three';

/**
 * Advances a damped spring x'' = -k x - d x' exactly by dt. Returns [x, v].
 * Handles under-, critically and over-damped springs.
 */
export function stepDampedSpring(x0, v0, k, d, dt) {
  if (dt <= 0) return [x0, v0];
  const w0 = Math.sqrt(k);
  const zeta = d / (2 * w0);
  if (zeta < 1 - 1e-6) {
    const wd = w0 * Math.sqrt(1 - zeta * zeta);
    const a = zeta * w0;
    const e = Math.exp(-a * dt);
    const c = Math.cos(wd * dt);
    const s = Math.sin(wd * dt);
    const B = (v0 + a * x0) / wd;
    const x = e * (x0 * c + B * s);
    const v = e * (v0 * c - (wd * x0 + (a * v0 + a * a * x0) / wd) * s);
    return [x, v];
  }
  if (zeta <= 1 + 1e-6) {
    // critically damped
    const e = Math.exp(-w0 * dt);
    const B = v0 + w0 * x0;
    const x = e * (x0 + B * dt);
    const v = e * (B - w0 * (x0 + B * dt));
    return [x, v];
  }
  // over-damped
  const r = w0 * Math.sqrt(zeta * zeta - 1);
  const r1 = -zeta * w0 + r;
  const r2 = -zeta * w0 - r;
  const c2 = (v0 - r1 * x0) / (r2 - r1);
  const c1 = x0 - c2;
  const e1 = Math.exp(r1 * dt);
  const e2 = Math.exp(r2 * dt);
  return [c1 * e1 + c2 * e2, c1 * r1 * e1 + c2 * r2 * e2];
}

// Impulses are chosen so the peak of one shot equals what the old per-frame integration gave
// at 60 FPS (kick 0.0174, kickRot 0.0577), i.e. the look tuned at the target frame rate.
export const VIEW_MODEL_MOTION_DEFAULTS = {
  kick: { stiffness: 260, damping: 22, impulse: 0.602 },
  kickRot: { stiffness: 220, damping: 20, impulse: 1.839 },
  // sway offset (m) per rad/s of look rate, clamped; tuned so 60 FPS matches the old feel
  swayPerRadPerSec: 0.01,
  swayMax: 0.03,
  swayRate: 10,
  sprintRate: 8,
};

export class ViewModelMotion {
  constructor(cfg = {}) {
    this.cfg = { ...VIEW_MODEL_MOTION_DEFAULTS, ...cfg };
    this.reset();
  }

  reset() {
    this.kick = 0;
    this.kickVel = 0;
    this.kickRot = 0;
    this.kickRotVel = 0;
    this.prevKick = 0;
    this.prevKickRot = 0;
    this.swayX = 0;
    this.swayY = 0;
    this.sprint = 0;
  }

  /** A shot was fired (called from the simulation tick, before tick()). */
  onShot() {
    this.kickVel += this.cfg.kick.impulse;
    this.kickRotVel += this.cfg.kickRot.impulse;
  }

  /** One fixed simulation tick. */
  tick(dt) {
    this.prevKick = this.kick;
    this.prevKickRot = this.kickRot;
    const K = this.cfg.kick;
    const R = this.cfg.kickRot;
    [this.kick, this.kickVel] = stepDampedSpring(this.kick, this.kickVel, K.stiffness, K.damping, dt);
    [this.kickRot, this.kickRotVel] = stepDampedSpring(this.kickRot, this.kickRotVel, R.stiffness, R.damping, dt);
  }

  /** Simulation not advancing (paused): keep the interpolated pose still. */
  hold() {
    this.prevKick = this.kick;
    this.prevKickRot = this.kickRot;
  }

  /** Interpolated kick values for rendering (alpha in [0, 1] between the last two ticks). */
  kickAt(alpha) {
    const a = Math.min(Math.max(alpha, 0), 1);
    return {
      kick: this.prevKick + (this.kick - this.prevKick) * a,
      kickRot: this.prevKickRot + (this.kickRot - this.prevKickRot) * a,
    };
  }

  /**
   * Per rendered frame: sway from the look angular velocity and the sprint pose blend.
   * @param {number} dt      real frame time (s); 0 = redraw without time passing
   * @param {number} lookDX  yaw change since the last frame (rad)
   * @param {number} lookDY  pitch change since the last frame (rad)
   * @param {number} sprintTarget 0..1
   */
  frame(dt, lookDX, lookDY, sprintTarget) {
    if (!(dt > 1e-6)) return;
    const c = this.cfg;
    const clamp = (v) => Math.max(-c.swayMax, Math.min(c.swayMax, v));
    const targetX = clamp((-lookDX / dt) * c.swayPerRadPerSec);
    const targetY = clamp((lookDY / dt) * c.swayPerRadPerSec);
    const ks = 1 - Math.exp(-c.swayRate * dt);
    this.swayX += (targetX - this.swayX) * ks;
    this.swayY += (targetY - this.swayY) * ks;
    this.sprint += (sprintTarget - this.sprint) * (1 - Math.exp(-c.sprintRate * dt));
  }
}

// ---------------------------------------------------------------- static pose

const _poseEuler = new Euler(0, 0, 0, 'XYZ');
const _poseV = new Vector3();
const easeInOut = (t) => t * t * (3 - 2 * t);

/** Hip/ADS blend weight used by the view model (smoothstep of the ADS amount). */
export function adsBlend(ads) {
  return easeInOut(Math.min(Math.max(ads, 0), 1));
}

/**
 * Camera-space position of a model-space point (glTF: muzzle +X, up +Y) for the static view
 * model pose at the given ADS amount: hip/ADS position blend plus the hip cant (yaw / roll),
 * without animation offsets (recoil, sway, bob, sprint, reload). This is exactly the pose the
 * renderer draws when those offsets are zero, so gameplay muzzle offsets are derived from it.
 * @param {object} vm  weapon.viewModel definition (hipPosition, adsPosition, hipRotation)
 */
export function viewModelPointInCamera(vm, local, ads, out = new Vector3()) {
  const w = adsBlend(ads);
  const hipW = 1 - w;
  const rot = vm.hipRotation || [0, 0, 0];
  // model root is turned +90 deg about Y: (x, y, z) -> (z, y, -x)
  _poseV.set(local.z ?? local[2], local.y ?? local[1], -(local.x ?? local[0]));
  _poseEuler.set(rot[0] * hipW, rot[1] * hipW, rot[2] * hipW, 'XYZ');
  _poseV.applyEuler(_poseEuler);
  const hp = vm.hipPosition;
  const ap = vm.adsPosition;
  return out.set(hp[0] + (ap[0] - hp[0]) * w, hp[1] + (ap[1] - hp[1]) * w, hp[2] + (ap[2] - hp[2]) * w).add(_poseV);
}
