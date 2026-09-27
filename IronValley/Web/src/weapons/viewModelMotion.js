// View-model motion state (no rendering, no DOM, testable in Node).
//
// Recoil kick springs (back, rise, muzzle pitch, roll, yaw) advance on the fixed simulation tick,
// like the camera recoil, and the renderer interpolates between the last two tick states. Each tick
// uses the exact solution of the damped spring, so the result is stable for any step length and
// identical at every frame rate. Peaks per shot come from weapons.json feel.viewModel (metres /
// degrees), per stance (hip / ADS / crouch).
//
// Sway and the sprint pose are per-frame smoothing driven by rates, not by per-frame deltas:
// sway follows the look angular velocity (rad/s) through an exponential filter, so the same
// mouse speed gives the same sway at 30, 60 or 144 FPS.

import { Euler, Vector3 } from 'three';
import { createRng } from '../util/rng.js';

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

/** Peak displacement of a damped spring x'' = -k x - d x' released from rest with unit velocity. */
export function springPeakPerUnitVelocity(k, d) {
  const w0 = Math.sqrt(k);
  const zeta = d / (2 * w0);
  if (zeta < 1 - 1e-6) {
    const wd = w0 * Math.sqrt(1 - zeta * zeta);
    const a = zeta * w0;
    const t = Math.atan2(wd, a) / wd;
    return (Math.exp(-a * t) * Math.sin(wd * t)) / wd;
  }
  if (zeta <= 1 + 1e-6) return 1 / (w0 * Math.E);
  const r = w0 * Math.sqrt(zeta * zeta - 1);
  const r1 = -zeta * w0 + r;
  const r2 = -zeta * w0 - r;
  const t = Math.log(r2 / r1) / (r1 - r2);
  return (Math.exp(r1 * t) - Math.exp(r2 * t)) / (r1 - r2);
}

// Per-shot kick of the drawn weapon, five springs in the weapon holder frame (camera space):
//   back  metres, + = towards the eye        rise  metres, + = up
//   pitch radians, + = muzzle up             roll  radians, + = counter-clockwise   yaw radians, + = muzzle left
// Data (weapons.json <weapon>.feel.viewModel) gives the PEAK of one shot from rest per channel (metres /
// degrees); the velocity impulse is derived from the spring constants. Stance multipliers per channel:
// in ADS pitch / yaw / rise are 0 by default so the sight line stays on the camera axis (the aim itself
// kicks through the camera recoil, which moves weapon and view together - the sight never lies).
export const KICK_CHANNELS = ['back', 'rise', 'pitch', 'roll', 'yaw'];

export const VIEW_MODEL_KICK_DEFAULTS = {
  back: { peak: 0.028, stiffness: 300, damping: 26 },
  rise: { peak: 0.006, stiffness: 240, damping: 22 },
  pitch: { peakDeg: 3.0, stiffness: 220, damping: 20 },
  roll: { peakDeg: 1.5, stiffness: 170, damping: 15 },
  yaw: { peakDeg: 0.6, stiffness: 200, damping: 20 },
  rollBias: 0.4, // > 0: clockwise (to the right) more often
  stance: {
    ads: { back: 0.45, rise: 0, pitch: 0, roll: 0.5, yaw: 0 },
    crouch: { back: 0.85, rise: 0.85, pitch: 0.85, roll: 0.85, yaw: 0.85 },
  },
  seed: 1,
};

export const VIEW_MODEL_MOTION_DEFAULTS = {
  kick: VIEW_MODEL_KICK_DEFAULTS,
  // sway offset (m) per rad/s of look rate, clamped; tuned so 60 FPS matches the old feel
  swayPerRadPerSec: 0.01,
  swayMax: 0.03,
  swayRate: 10,
  sprintRate: 8,
};

/** Merges a feel.viewModel block over the defaults (per channel and per stance). */
export function resolveKickConfig(kick = {}) {
  const D = VIEW_MODEL_KICK_DEFAULTS;
  const out = { rollBias: kick.rollBias ?? D.rollBias, seed: kick.seed ?? D.seed, stance: {} };
  for (const ch of KICK_CHANNELS) out[ch] = { ...D[ch], ...(kick[ch] || {}) };
  for (const s of ['ads', 'crouch']) out.stance[s] = { ...D.stance[s], ...((kick.stance && kick.stance[s]) || {}) };
  return out;
}

const DEG = Math.PI / 180;

export class ViewModelMotion {
  constructor(cfg = {}) {
    this.cfg = { ...VIEW_MODEL_MOTION_DEFAULTS, ...cfg };
    this.kickCfg = resolveKickConfig(cfg.kick || {});
    // velocity impulse per channel so one shot from rest peaks at the configured value
    this.impulse = {};
    for (const ch of KICK_CHANNELS) {
      const c = this.kickCfg[ch];
      const peak = c.peakDeg !== undefined ? c.peakDeg * DEG : c.peak || 0;
      this.impulse[ch] = peak > 0 ? peak / springPeakPerUnitVelocity(c.stiffness, c.damping) : 0;
    }
    this._rng = createRng(this.kickCfg.seed);
    this.reset();
  }

  reset() {
    this.ch = {};
    for (const c of KICK_CHANNELS) this.ch[c] = { x: 0, v: 0, prev: 0 };
    this.swayX = 0;
    this.swayY = 0;
    this.sprint = 0;
    this.shots = 0;
  }

  /** Back offset (m) and muzzle pitch (rad) of the last tick (legacy names). */
  get kick() {
    return this.ch.back.x;
  }

  get kickRot() {
    return this.ch.pitch.x;
  }

  /**
   * A shot was fired (called from the simulation tick, before tick()).
   * @param {object} [o] { ads: 0..1, crouch: bool }
   */
  onShot(o = {}) {
    const K = this.kickCfg;
    const ads = Math.min(Math.max(o.ads || 0, 0), 1);
    const rb = Math.max(-1, Math.min(1, K.rollBias || 0));
    for (const c of KICK_CHANNELS) {
      const adsM = K.stance.ads[c] ?? 1;
      const crM = o.crouch ? (K.stance.crouch[c] ?? 1) : 1;
      let s = (1 + (adsM - 1) * ads) * crM;
      if (c === 'roll') s *= this._rng.signed() * (1 - Math.abs(rb)) - rb < 0 ? -1 : 1;
      else if (c === 'yaw') {
        const r = this._rng.signed();
        s *= (r < 0 ? -1 : 1) * (0.4 + 0.6 * Math.abs(r));
      }
      this.ch[c].v += this.impulse[c] * s;
    }
    this.shots++;
  }

  /** One fixed simulation tick (exact spring solution: identical at any frame rate). */
  tick(dt) {
    const K = this.kickCfg;
    for (const c of KICK_CHANNELS) {
      const st = this.ch[c];
      st.prev = st.x;
      if (st.x === 0 && st.v === 0) continue;
      [st.x, st.v] = stepDampedSpring(st.x, st.v, K[c].stiffness, K[c].damping, dt);
      if (Math.abs(st.x) < 1e-8 && Math.abs(st.v) < 1e-7) st.x = st.v = 0;
    }
  }

  /** Simulation not advancing (paused): keep the interpolated pose still. */
  hold() {
    for (const c of KICK_CHANNELS) this.ch[c].prev = this.ch[c].x;
  }

  /** Interpolated kick pose for rendering (alpha in [0, 1] between the last two ticks). */
  kickAt(alpha) {
    const a = Math.min(Math.max(alpha, 0), 1);
    const out = {};
    for (const c of KICK_CHANNELS) {
      const st = this.ch[c];
      out[c] = st.prev + (st.x - st.prev) * a;
    }
    out.kick = out.back;
    out.kickRot = out.pitch;
    return out;
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
