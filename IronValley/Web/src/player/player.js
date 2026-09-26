// Player: turns input into movement commands for the shared capsule controller, owns the
// look angles and produces the interpolated first-person eye transform for rendering.

import { Vector3 } from 'three';
import { clamp, DEG2RAD } from '../util/math.js';

const PITCH_LIMIT = 88 * DEG2RAD;

export class Player {
  /**
   * @param {object} opts
   * @param {import('../physics/characterController.js').CharacterController} opts.controller
   * @param {import('./input.js').InputManager} opts.input
   * @param {import('./settings.js').Settings} opts.settings
   * @param {import('../engine/events.js').EventBus} opts.events
   * @param {object} opts.mouse  bindings.mouse
   */
  constructor({ controller, input, settings, events, mouse }) {
    this.ctrl = controller;
    this.input = input;
    this.settings = settings;
    this.events = events;
    this.mouse = mouse || { baseRadiansPerPixel: 0.0022, invertY: false };
    this.yaw = 0;
    this.pitch = 0;
    // incremented whenever the look direction is set directly (teleport / respawn / script)
    // instead of turned by the mouse, so view-model sway can ignore that jump
    this.lookSnaps = 0;

    // interpolation snapshots (feet position, eye height, step smoothing)
    this.prevFeet = new Vector3();
    this.currFeet = new Vector3();
    this.prevEyeH = controller.eyeHeight;
    this.currEyeH = controller.eyeHeight;
    this.prevStep = 0;
    this.currStep = 0;

    // camera vertical filter: follows the eye with velocity prediction so that uniform
    // slopes do not lag, while stair bumps are smoothed out
    this.viewY = 0;
    this.viewVy = 0;
    this.prevViewY = 0;

    // head bob / landing dip (visual only, scaled by camera motion setting). They advance on
    // the simulation tick, so rendering interpolates them between the last two ticks like the
    // eye position (otherwise they would move in 60 Hz steps on faster displays).
    this.bobPhase = 0;
    this.bobAmount = 0;
    this.landingDip = 0;
    this.landingDipVel = 0;
    this.prevBobPhase = 0;
    this.prevBobAmount = 0;
    this.prevLandingDip = 0;
    this._bob = { phase: 0, amount: 0, landingDip: 0 };
    this.lastCmd = null;

    controller.onEvent = (name, payload) => {
      if (name === 'landed') {
        const s = Math.min(payload.speed, 8);
        if (s > 1.5) this.landingDipVel -= s * 0.35;
      }
      events.emit(`player:${name}`, payload);
    };
  }

  teleport(pos, yawDeg = null, pitchDeg = null) {
    this.ctrl.teleport(pos);
    this.lookSnaps++;
    if (yawDeg !== null) this.yaw = yawDeg * DEG2RAD;
    if (pitchDeg !== null) this.pitch = clamp(pitchDeg * DEG2RAD, -PITCH_LIMIT, PITCH_LIMIT);
    this.prevFeet.copy(this.ctrl.position);
    this.currFeet.copy(this.ctrl.position);
    this.prevEyeH = this.currEyeH = this.ctrl.eyeHeight;
    this.prevStep = this.currStep = 0;
    this.viewY = this.prevViewY = this.ctrl.position.y + this.ctrl.eyeHeight;
    this.viewVy = 0;
    this.landingDip = this.landingDipVel = 0;
    this._holdVisuals();
  }

  setLook(yawDeg, pitchDeg) {
    this.lookSnaps++;
    this.yaw = yawDeg * DEG2RAD;
    this.pitch = clamp(pitchDeg * DEG2RAD, -PITCH_LIMIT, PITCH_LIMIT);
  }

  /** Applies accumulated mouse deltas (called every rendered frame for low latency). */
  applyLookInput() {
    const { dx, dy } = this.input.consumeLook();
    if (dx === 0 && dy === 0) return;
    const k = this.mouse.baseRadiansPerPixel * this.settings.get('mouseSensitivity');
    this.yaw -= dx * k;
    this.pitch -= (this.mouse.invertY ? -dy : dy) * k;
    this.pitch = clamp(this.pitch, -PITCH_LIMIT, PITCH_LIMIT);
    // keep yaw bounded
    if (this.yaw > Math.PI * 4 || this.yaw < -Math.PI * 4) this.yaw %= Math.PI * 2;
  }

  /** Builds the movement command from current input. */
  buildCommand(weapon) {
    const inp = this.input;
    return {
      moveX: inp.axis('moveRight', 'moveLeft'),
      moveZ: inp.axis('moveForward', 'moveBackward'),
      yaw: this.yaw,
      sprint: inp.isActive('sprint'),
      walk: inp.isActive('walk'),
      crouch: inp.isActive('crouch'),
      jump: inp.wasPressed('jump'),
      ads: weapon ? weapon.adsHeld : false,
      fire: weapon ? weapon.triggerHeld : false,
    };
  }

  /** Makes the previous-tick snapshots of the visual (bob / dip) state equal to the current one. */
  _holdVisuals() {
    this.prevBobPhase = this.bobPhase;
    this.prevBobAmount = this.bobAmount;
    this.prevLandingDip = this.landingDip;
  }

  /** One fixed simulation tick. */
  tick(dt, weapon) {
    const c = this.ctrl;
    this.prevFeet.copy(this.currFeet);
    this.prevEyeH = this.currEyeH;
    this.prevStep = this.currStep;
    this.prevViewY = this.viewY;
    this._holdVisuals();

    const cmd = this.buildCommand(weapon);
    this.lastCmd = cmd;
    const y0 = c.position.y;
    c.update(dt, cmd);

    this.currFeet.copy(c.position);
    this.currEyeH = c.eyeHeight;
    this.currStep = c.stepOffset;

    // vertical camera filter
    const target = c.position.y + c.eyeHeight + c.stepOffset;
    if (!c.grounded || Math.abs(target - this.viewY) > 0.6) {
      this.viewY = target;
      this.viewVy = (c.position.y - y0) / dt;
    } else {
      const vyNow = (c.position.y - y0) / dt;
      this.viewVy += (vyNow - this.viewVy) * (1 - Math.exp(-10 * dt));
      const predicted = this.viewY + this.viewVy * dt;
      this.viewY = predicted + (target - predicted) * (1 - Math.exp(-25 * dt));
    }

    // head bob driven by actual horizontal speed
    const speed = Math.hypot(c.velocity.x, c.velocity.z);
    const moving = c.grounded ? Math.min(speed / 3.5, 1.6) : 0;
    this.bobAmount += (moving - this.bobAmount) * (1 - Math.exp(-8 * dt));
    // step frequency ~1.8 Hz at run, higher when sprinting
    this.bobPhase += dt * (4 + speed * 1.6);

    // landing dip spring
    const k = 120;
    const d = 18;
    this.landingDipVel += (-k * this.landingDip - d * this.landingDipVel) * dt;
    this.landingDip += this.landingDipVel * dt;
    this.landingDip = clamp(this.landingDip, -0.12, 0.05);
  }

  /** Simulation not advancing (paused / menu): make the interpolated eye stand still. */
  holdInterpolation() {
    this.prevFeet.copy(this.currFeet);
    this.prevEyeH = this.currEyeH;
    this.prevStep = this.currStep;
    this.prevViewY = this.viewY;
    this._holdVisuals();
  }

  /**
   * Head bob phase / amount and landing dip interpolated between the last two ticks (alpha in
   * [0,1]); shared by the camera and the view model. Returns a reused object.
   */
  getRenderBob(alpha) {
    const a = Math.min(Math.max(alpha, 0), 1);
    const b = this._bob;
    b.phase = this.prevBobPhase + (this.bobPhase - this.prevBobPhase) * a;
    b.amount = this.prevBobAmount + (this.bobAmount - this.prevBobAmount) * a;
    b.landingDip = this.prevLandingDip + (this.landingDip - this.prevLandingDip) * a;
    return b;
  }

  /** Interpolated eye position for rendering (alpha in [0,1] between ticks). */
  getRenderEye(alpha, out = new Vector3()) {
    out.lerpVectors(this.prevFeet, this.currFeet, alpha);
    out.y = this.prevViewY + (this.viewY - this.prevViewY) * alpha;
    const motion = this.settings.get('cameraMotion');
    if (motion > 0) {
      const { phase, amount, landingDip } = this.getRenderBob(alpha);
      const bob = amount * motion;
      out.y += Math.sin(phase * 2) * 0.012 * bob + landingDip * motion;
      const side = Math.cos(phase) * 0.008 * bob;
      out.x += Math.cos(this.yaw) * side;
      out.z -= Math.sin(this.yaw) * side;
    }
    return out;
  }

  /** Exact (non-interpolated) simulation eye position, used for hitscan. */
  getSimEye(out = new Vector3()) {
    const c = this.ctrl;
    return out.set(c.position.x, c.position.y + c.eyeHeight, c.position.z);
  }

  getState() {
    const s = this.ctrl.getState();
    return {
      ...s,
      yawDeg: this.yaw / DEG2RAD,
      pitchDeg: this.pitch / DEG2RAD,
      eyeWorldY: s.position.y + s.eyeHeight,
      viewY: this.viewY,
      cmd: this.lastCmd,
    };
  }
}
