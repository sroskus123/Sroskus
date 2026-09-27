// First-person camera feel. VISUAL ONLY: never changes the simulation, the aim or the hitscan eye.
//
//   head bob       driven by the controller's real gait phase (src/physics/stride.js): the eye is lowest at
//                  each foot contact and highest in mid-stance, sways over the stance foot; the frequency is
//                  the real cadence (faster steps when running / sprinting), the amplitude grows with speed;
//                  on a staircase the contacts land on the treads (stride.js) and the bob is a little
//                  stronger (every step lifts the body by a riser);
//   step impulse   a small eye dip when the controller steps up or down a stair riser ('step' event);
//   landing dip    spring kick of the eye scaled by the fall speed ('landed');
//   strafe roll    slight roll into the sideways velocity;
//   traversal      subtle roll / look-down arc during a vault or mantle, weapon lowered (0..1) and raised
//                  again on the controller's clock (CharacterController.weaponLower / handsBusy).
//
// The screen centre never leaves the aim while the weapon can fire (GUN-03, no lying crosshair / sight):
// dips and bob are eye TRANSLATIONS (parallax of a few cm, the hitscan uses the same direction) and every
// rotation is a roll about the view axis. The only pitch is the traversal look-down, which exists only
// while the hands are off the weapon (the weapon is locked) and is back to 0 when it can fire again.
//
// State advances on the fixed simulation tick (tick / snapshot / hold) and rendering interpolates between
// the last two ticks (sample(alpha)), so nothing moves in 60 Hz steps on faster displays. Everything is
// multiplied by the "camera motion" setting at sample time (0 disables all of it). Comfort first: all
// amplitudes are small (bob <= 2 cm, 2.5 cm on stairs, roll <= 1 deg, step dip <= 3 cm).

export const CAMERA_FX_DEFAULTS = Object.freeze({
  bob: { vertBase: 0.006, vertPerSpeed: 0.0022, vertMax: 0.02, sideRatio: 0.55, crouchScale: 0.6, rate: 8, rollDeg: 0.2, runSpeed: 3.5, stairScale: 1.5, stairVertMax: 0.025 },
  landing: { minSpeed: 1.5, maxSpeed: 8, impulse: 0.35, stiffness: 120, damping: 18, min: -0.12, max: 0.05 },
  step: { impulseUp: 0.25, impulseDown: 0.35, riser: 0.18, maxScale: 2.2, stiffness: 160, damping: 20, min: -0.03, max: 0.015 },
  strafeRoll: { maxDeg: 1.0, runSpeed: 3.5, rate: 6, airScale: 0.5 },
  traverse: { rollDeg: 2.0, pitchDeg: 3.0, lowerRate: 14, raiseRate: 7, landImpulse: 0.5 },
});

const DEG = Math.PI / 180;

function springStep(x, v, k, d, dt) {
  // semi-implicit Euler on the fixed tick (stable for these stiffnesses at 60 Hz)
  v += (-k * x - d * v) * dt;
  x += v * dt;
  return [x, v];
}

export class CameraEffects {
  /**
   * @param {object} [o]
   * @param {{get(key:string):any}} [o.settings]  reads 'cameraMotion' (0..1)
   * @param {object} [o.params]                    overrides of CAMERA_FX_DEFAULTS (per group)
   */
  constructor({ settings = null, params = null } = {}) {
    const D = CAMERA_FX_DEFAULTS;
    const P = params || {};
    this.p = {};
    for (const k of Object.keys(D)) this.p[k] = { ...D[k], ...(P[k] || {}) };
    this.settings = settings;
    this.ctrl = null;
    this._off = null;
    this.cur = this._blank();
    this.prev = this._blank();
    this._out = { phase: 0, amount: 0, landingDip: 0, offsetY: 0, side: 0, roll: 0, pitch: 0, lower: 0, motion: 1 };
    this._lastStride = 0;
    this._tr = null;
    this._trEnd = null; // traversal roll / pitch when the move ended, faded out while the weapon is raised
    this.stats = { steps: 0, landings: 0, traversals: 0, footsteps: 0 };
  }

  _blank() {
    return { phase: 0, amount: 0, bobAmp: 0, landing: 0, landingV: 0, step: 0, stepV: 0, roll: 0, trRoll: 0, trPitch: 0, lower: 0 };
  }

  /** Listens to a controller's events (landing, stair steps, traversal); detaches from the previous one. */
  attach(controller) {
    if (this._off) this._off();
    this._off = null;
    this.ctrl = controller;
    if (controller && typeof controller.addListener === 'function') {
      this._off = controller.addListener((name, payload) => this.onEvent(name, payload));
    }
    this._lastStride = controller && controller.stride ? controller.stride.phase : 0;
    this.reset();
  }

  detach() {
    if (this._off) this._off();
    this._off = null;
    this.ctrl = null;
  }

  reset() {
    this.cur = this._blank();
    this.prev = this._blank();
    this._tr = null;
    this._trEnd = null;
    this._lastStride = this.ctrl && this.ctrl.stride ? this.ctrl.stride.phase : 0;
  }

  get motion() {
    const m = this.settings ? Number(this.settings.get('cameraMotion')) : 1;
    return Number.isFinite(m) ? Math.min(1, Math.max(0, m)) : 1;
  }

  onEvent(name, p) {
    const c = this.cur;
    if (name === 'landed') {
      const L = this.p.landing;
      const s = Math.min(p.speed || 0, L.maxSpeed);
      if (s > L.minSpeed) c.landingV -= s * L.impulse;
      this.stats.landings++;
    } else if (name === 'step') {
      const S = this.p.step;
      const dy = p.dy || 0;
      const scale = Math.min(Math.abs(dy) / S.riser, S.maxScale);
      c.stepV -= (dy > 0 ? S.impulseUp : S.impulseDown) * scale;
      this.stats.steps++;
    } else if (name === 'footstep') {
      this.stats.footsteps++;
    } else if (name === 'traverse:start') {
      this._tr = { t: 0, duration: Math.max(0.1, p.duration || 0.7), type: p.type, side: p.type === 'mantle' ? -1 : 1 };
      this._trEnd = null;
      this.stats.traversals++;
    } else if (name === 'traverse:end') {
      if (this._tr && this._tr.type === 'vault' && !p.aborted) c.landingV -= this.p.traverse.landImpulse;
      this._tr = null;
      this._trEnd = { roll: c.trRoll, pitch: c.trPitch };
    }
  }

  /** Start of a simulation tick: previous-tick snapshot for interpolation. */
  snapshot() {
    Object.assign(this.prev, this.cur);
  }

  /** Simulation not advancing (pause / menu): the interpolated camera stands still. */
  hold() {
    Object.assign(this.prev, this.cur);
  }

  /**
   * One fixed tick (after the controller moved).
   * @param {number} dt
   * @param {import('../physics/characterController.js').CharacterController} ctrl
   * @param {number} yaw  view yaw (rad)
   */
  tick(dt, ctrl, yaw) {
    const c = this.cur;
    const B = this.p.bob;
    const speed = Math.hypot(ctrl.velocity.x, ctrl.velocity.z);
    const grounded = ctrl.grounded && !ctrl.traversing;

    // gait phase (unwrapped, radians: one cycle of two steps = 2 pi)
    const sp = ctrl.stride ? ctrl.stride.phase : 0;
    let d = sp - this._lastStride;
    if (d < -1e-9) d += 2;
    this._lastStride = sp;
    c.phase += d * Math.PI;
    if (c.phase > 1e4) {
      c.phase -= 2 * Math.PI * Math.floor(c.phase / (2 * Math.PI));
      this.prev.phase = c.phase - d * Math.PI;
    }

    // bob amount (view model convention: 1 ~ run speed) and eye amplitude (m), both smoothed
    const k = 1 - Math.exp(-B.rate * dt);
    const moving = grounded && ctrl.stride && ctrl.stride.moving;
    const amountTarget = grounded ? Math.min(speed / B.runSpeed, 1.6) : 0;
    c.amount += (amountTarget - c.amount) * k;
    const stairs = !!(moving && ctrl.stride.onStairs);
    let ampTarget = moving ? B.vertBase + B.vertPerSpeed * speed : 0;
    if (stairs) ampTarget = Math.min(B.stairVertMax, ampTarget * B.stairScale);
    else ampTarget = Math.min(B.vertMax, ampTarget);
    if (ctrl.crouched) ampTarget *= B.crouchScale;
    c.bobAmp += (ampTarget - c.bobAmp) * k;

    // landing dip spring
    const L = this.p.landing;
    [c.landing, c.landingV] = springStep(c.landing, c.landingV, L.stiffness, L.damping, dt);
    c.landing = Math.min(L.max, Math.max(L.min, c.landing));

    // stair step spring
    const S = this.p.step;
    [c.step, c.stepV] = springStep(c.step, c.stepV, S.stiffness, S.damping, dt);
    c.step = Math.min(S.max, Math.max(S.min, c.step));

    // strafe roll: into the sideways velocity (right of the view = +)
    const R = this.p.strafeRoll;
    const side = ctrl.velocity.x * Math.cos(yaw) - ctrl.velocity.z * Math.sin(yaw);
    let rollTarget = Math.max(-1.2, Math.min(1.2, side / R.runSpeed)) * R.maxDeg * DEG;
    if (!grounded) rollTarget *= R.airScale;
    if (ctrl.traversing) rollTarget = 0;
    c.roll += (rollTarget - c.roll) * (1 - Math.exp(-R.rate * dt));

    // traversal arc: roll / look-down peak mid-move, weapon lowered
    const T = this.p.traverse;
    const tr = this._tr;
    if (tr) {
      tr.t = Math.min(1, tr.t + dt / tr.duration);
      const s = Math.sin(Math.PI * tr.t);
      c.trRoll = tr.side * T.rollDeg * DEG * s;
      c.trPitch = -T.pitchDeg * DEG * s * s;
      c.lower += (1 - c.lower) * (1 - Math.exp(-T.lowerRate * dt));
    } else if (typeof ctrl.weaponLower === 'number') {
      // weapon raised on the controller's clock: fully up (and no look-down pitch left) exactly when the
      // weapon may fire again (CharacterController.handsBusy ends)
      const g = ctrl.weaponLower;
      c.lower = Math.min(c.lower, g);
      if (this._trEnd) {
        c.trRoll = this._trEnd.roll * g;
        c.trPitch = this._trEnd.pitch * g;
        if (g === 0) this._trEnd = null;
      } else {
        c.trRoll = 0;
        c.trPitch = 0;
      }
    } else {
      const kr = 1 - Math.exp(-T.raiseRate * dt);
      c.trRoll += (0 - c.trRoll) * kr;
      c.trPitch += (0 - c.trPitch) * kr;
      c.lower += (0 - c.lower) * kr;
      if (Math.abs(c.lower) < 1e-4) c.lower = 0;
    }
  }

  /**
   * Interpolated effects (alpha in [0,1] between the last two ticks), already scaled by the camera motion
   * setting. Returns a reused object:
   *   phase, amount   bob phase (rad) / amount for the view model (amount NOT scaled: the view model scales)
   *   landingDip      raw landing spring offset (m, not scaled)
   *   offsetY, side   eye offset up / to the right of the view (m)
   *   roll, pitch     extra camera roll (rad, + = right) and pitch (rad, + = up; only the traversal
   *                   look-down, i.e. never while the weapon can fire)
   *   lower           weapon lowering 0..1 (traversal; not scaled: gameplay feedback, not comfort)
   */
  sample(alpha) {
    const a = Math.min(Math.max(alpha, 0), 1);
    const p = this.prev;
    const c = this.cur;
    const lerp = (x, y) => x + (y - x) * a;
    const o = this._out;
    const m = this.motion;
    o.motion = m;
    o.phase = lerp(p.phase, c.phase);
    o.amount = lerp(p.amount, c.amount);
    o.landingDip = lerp(p.landing, c.landing);
    const amp = lerp(p.bobAmp, c.bobAmp);
    const step = lerp(p.step, c.step);
    const B = this.p.bob;
    // lowest at a foot contact (phase = k pi), highest in mid-stance; sway over the stance foot
    const bobY = -amp * Math.cos(2 * o.phase);
    const bobSide = -amp * B.sideRatio * Math.sin(o.phase);
    o.offsetY = (bobY + o.landingDip + step) * m;
    o.side = bobSide * m;
    const bobRoll = amp > 0 ? (-B.rollDeg * DEG * Math.sin(o.phase) * amp) / B.vertMax : 0;
    o.roll = (lerp(p.roll, c.roll) + lerp(p.trRoll, c.trRoll) + bobRoll) * m;
    o.pitch = lerp(p.trPitch, c.trPitch) * m;
    o.lower = lerp(p.lower, c.lower);
    return o;
  }

  getState() {
    const c = this.cur;
    return {
      phase: c.phase,
      amount: c.amount,
      bobAmp: c.bobAmp,
      landingDip: c.landing,
      stepDip: c.step,
      roll: c.roll,
      traversal: this._tr ? { type: this._tr.type, t: this._tr.t } : null,
      lower: c.lower,
      motion: this.motion,
      stats: { ...this.stats },
    };
  }
}
