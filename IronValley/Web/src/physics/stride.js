// Stride tracker: gait phase of a capsule character derived from its REAL horizontal movement on the ground
// (decision D7: locomotion is driven by the capsule, animation follows it). One source of truth for foot
// contacts: the 'footstep' events (audio, AI hearing) and the first-person head bob use the same phase, so
// the camera dips exactly when a foot lands.
//
// Step length grows with speed (walk ~0.7 m, run ~1.1 m, sprint ~1.6 m; shorter when crouched), so the
// cadence is realistic (walk ~2.3, run ~3.1, sprint ~3.6 steps/s) instead of a fixed stride length.
// phase: 0..2 per gait cycle (0 = left foot contact, 1 = right foot contact). When the character stops,
// the phase runs on to the next contact and rests there (both feet planted). A landing is a contact too.
//
// Stairs: the controller reports every riser it climbs or descends (riser()). Two risers a plausible tread apart
// mean a staircase: the step length becomes a whole number of treads (one tread per step when slow, two or more
// when the cadence would exceed stairMaxCadence) and the phase is pulled, by changing its rate only (never a
// jump, never backwards), so that a foot contact coincides with a riser. The head bob and the footstep sounds
// then follow the steps of the staircase instead of the flat-ground rhythm.

export const STRIDE_DEFAULTS = Object.freeze({
  baseLength: 0.35,
  lengthPerSpeed: 0.22,
  minLength: 0.5,
  maxLength: 1.7,
  crouchFactor: 0.8,
  minSpeed: 0.3,
  stairMinTread: 0.15,
  stairMaxTread: 0.6,
  stairMaxCadence: 3.2,
  stairMemory: 0.5,
  stairLock: 0.6,
});

export class StrideTracker {
  constructor(params = {}) {
    this.p = { ...STRIDE_DEFAULTS, ...params };
    this.reset();
  }

  reset() {
    this.phase = 0; // 0..2
    this.stepLength = this.p.minLength;
    this.cadence = 0; // steps per second
    this.moving = false;
    this.contacts = 0;
    this.lastFoot = 'right'; // so the first step is the left foot
    this.tread = 0; // estimated tread depth of the staircase being walked (m), 0 = none
    this.stairTimer = 0; // s left in stairs mode after the last riser
    this.risers = 0;
    this._sinceRiser = Infinity; // ground distance since the last riser (m)
    this._corr = 0; // pending phase correction (steps), spent over the next ticks
  }

  /** True while walking a staircase (a riser less than stairMemory ago, tread known). */
  get onStairs() {
    return this.stairTimer > 0 && this.tread > 0;
  }

  /** Treads per step on the current staircase at this speed. */
  treadsPerStep(speed) {
    if (!(this.tread > 0)) return 1;
    return Math.max(1, Math.ceil(speed / (this.tread * this.p.stairMaxCadence) - 1e-9));
  }

  /** Step length (m) for a horizontal speed (m/s). */
  lengthFor(speed, crouched = false) {
    const p = this.p;
    if (this.onStairs) return Math.min(p.maxLength, this.treadsPerStep(speed) * this.tread);
    let L = p.baseLength + p.lengthPerSpeed * speed;
    L = Math.min(p.maxLength, Math.max(p.minLength, L));
    if (crouched) L = Math.max(p.minLength * p.crouchFactor, L * p.crouchFactor);
    return L;
  }

  /**
   * Advances the phase by the ground distance covered this tick.
   * @returns {null|{foot:'left'|'right', speed:number, kind:'step'}} a foot contact, if one happened
   */
  update(dt, grounded, speed, crouched) {
    const p = this.p;
    if (!grounded) {
      this.moving = false;
      this.cadence = 0;
      this._corr = 0;
      return null;
    }
    this._sinceRiser += speed * dt;
    if (this.stairTimer > 0) this.stairTimer = Math.max(0, this.stairTimer - dt);
    const moving = speed >= p.minSpeed;
    const L = this.lengthFor(Math.max(speed, p.minSpeed), crouched);
    this.stepLength = L;
    let adv;
    if (moving) {
      adv = (speed * dt) / L;
      this.cadence = speed / L;
      if (this._corr !== 0) {
        // phase lock onto the stair risers: at most double / at least 0.4x the natural rate
        const c = Math.max(-0.6 * adv, Math.min(adv, this._corr));
        adv += c;
        this._corr -= c;
      }
    } else {
      // settle onto the next contact at a slow walking cadence, then rest
      const frac = this.phase - Math.floor(this.phase);
      if (frac === 0) {
        this.cadence = 0;
        this.moving = false;
        return null;
      }
      adv = Math.min(1 - frac, dt * 1.5);
      this.cadence = 0;
    }
    if (!this.moving && moving) {
      // starting from rest: first contact after half a step (push-off), not immediately
      const frac = this.phase - Math.floor(this.phase);
      if (frac === 0) this.phase += 0.5;
    }
    this.moving = moving;
    const before = this.phase;
    const after = before + adv;
    let contact = null;
    const crossed = Math.floor(after + 1e-9);
    if (crossed > Math.floor(before + 1e-9) && moving) {
      // crossed an integer: foot contact (only moving steps are events; settling is silent)
      contact = this._contact(speed, 'step', crossed % 2 === 1 ? 'right' : 'left');
    }
    this.phase = after >= 2 - 1e-9 ? Math.max(0, after - 2) : after;
    return contact;
  }

  /**
   * The controller climbed / descended a stair riser this tick.
   * @param {number} speed horizontal speed (m/s)
   */
  riser(speed) {
    const p = this.p;
    const d = this._sinceRiser;
    this._sinceRiser = 0;
    this.risers++;
    if (!(d >= p.stairMinTread && d <= p.stairMaxTread)) return; // a single step / curb: nothing to follow
    this.tread = this.onStairs ? this.tread + (d - this.tread) * 0.5 : d;
    this.stairTimer = p.stairMemory;
    if (!this.moving) return;
    // the riser nearest to a foot contact should coincide with it: signed phase error to the nearest integer
    const n = this.treadsPerStep(speed);
    const f = this.phase - Math.floor(this.phase);
    const err = f < 0.5 ? f : f - 1;
    if (Math.abs(err) <= 0.5 / n + 1e-9) this._corr = -err * p.stairLock;
  }

  /** Landing after a fall / jump: both feet come down, the next step starts from here. */
  land(speed) {
    this.phase = Math.round(this.phase) % 2;
    this._corr = 0;
    return this._contact(speed, 'land');
  }

  _contact(speed, kind, foot = this.lastFoot === 'left' ? 'right' : 'left') {
    this.contacts++;
    this.lastFoot = foot;
    return { foot, speed, kind };
  }
}
