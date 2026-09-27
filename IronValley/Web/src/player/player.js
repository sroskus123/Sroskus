// Player: turns input into movement commands for the shared capsule controller, owns the
// look angles and produces the interpolated first-person eye transform for rendering.

import { Quaternion, Vector3 } from 'three';
import { clamp, DEG2RAD } from '../util/math.js';
import { CameraEffects } from './cameraEffects.js';

const _qFx = new Quaternion();
const _axisX = new Vector3(1, 0, 0);
const _axisZ = new Vector3(0, 0, 1);

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
    // look speed factor while aiming (magnification / ADS sensitivity setting), provided by the game; 1 = hip
    this.lookScaleFn = null;
    this.lastLookScale = 1;
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

    // camera feel (visual only, scaled by the camera motion setting): footstep-synced head bob, stair
    // step impulse, landing dip, strafe roll, traversal arc. Advances on the simulation tick and is
    // interpolated between the last two ticks like the eye position (src/player/cameraEffects.js).
    this.cameraFx = new CameraEffects({ settings });
    this._bob = { phase: 0, amount: 0, landingDip: 0 };
    this.lastCmd = null;

    this._y0 = 0;
    this.attachController(controller);
  }

  /**
   * Uses `controller` for the camera (the player's Combatant owns and moves it; a new match creates a
   * new combatant with a new controller). Landing events drive the camera dip and are re-published.
   */
  attachController(controller) {
    if (this.ctrl && this.ctrl !== controller && this.ctrl.onEvent === this._onCtrlEvent) this.ctrl.onEvent = null;
    this.ctrl = controller;
    this._onCtrlEvent = (name, payload) => {
      this.events.emit(`player:${name}`, payload);
    };
    controller.onEvent = this._onCtrlEvent;
    this.cameraFx.attach(controller);
    this.prevFeet.copy(controller.position);
    this.currFeet.copy(controller.position);
    this.prevEyeH = this.currEyeH = controller.eyeHeight;
    this.viewY = this.prevViewY = controller.position.y + controller.eyeHeight;
    this.viewVy = 0;
    this._y0 = controller.position.y;
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
    this.cameraFx.reset();
    this._y0 = this.ctrl.position.y;
    this._holdVisuals();
  }

  /** Landing dip spring offset (m) of the current tick (camera effects). */
  get landingDip() {
    return this.cameraFx.cur.landing;
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
    const scale = this.lookScaleFn ? this.lookScaleFn() : 1;
    this.lastLookScale = Number.isFinite(scale) && scale > 0 ? scale : 1;
    const k = this.mouse.baseRadiansPerPixel * this.settings.get('mouseSensitivity') * this.lastLookScale;
    this.yaw -= dx * k;
    this.pitch -= (this.mouse.invertY ? -dy : dy) * k;
    this.pitch = clamp(this.pitch, -PITCH_LIMIT, PITCH_LIMIT);
    // keep yaw bounded
    if (this.yaw > Math.PI * 4 || this.yaw < -Math.PI * 4) this.yaw %= Math.PI * 2;
  }

  /**
   * Builds the combatant command (Docs/GAMEPLAY_CONTRACTS.md cmd format) from the current input.
   * `weapon` ({ triggerHeld, adsHeld }) overrides fire / ADS (legacy callers); otherwise they come from
   * the bound actions like everything else.
   */
  buildCommand(weapon) {
    const inp = this.input;
    const own = weapon === undefined || weapon === null;
    return {
      moveX: inp.axis('moveRight', 'moveLeft'),
      moveZ: inp.axis('moveForward', 'moveBackward'),
      yaw: this.yaw,
      pitch: this.pitch,
      sprint: inp.isActive('sprint'),
      walk: inp.isActive('walk'),
      crouch: inp.isActive('crouch'),
      jump: inp.wasPressed('jump'),
      ads: own ? inp.isActive('aim') : !!weapon.adsHeld,
      fire: own ? inp.isActive('fire') : !!weapon.triggerHeld,
      reload: inp.wasPressed('reload'),
      switchTo: inp.wasPressed('weapon1') ? 0 : inp.wasPressed('weapon2') ? 1 : null,
      interact: inp.wasPressed('interact'),
      swapOptic: inp.wasPressed('swapOptic'),
    };
  }

  /** Idle command that keeps the current look (dead, menus). */
  idleCommand() {
    return { moveX: 0, moveZ: 0, yaw: this.yaw, pitch: this.pitch, sprint: false, walk: false, crouch: false, jump: false, ads: false, fire: false, reload: false, switchTo: null, interact: false, swapOptic: false };
  }

  /** Makes the previous-tick snapshots of the visual (bob / dip) state equal to the current one. */
  _holdVisuals() {
    this.cameraFx.hold();
  }

  /**
   * One fixed simulation tick that also moves the controller (standalone use and unit tests). In the
   * game the player's Combatant moves the controller: beginTick() -> combatant.applyCommand -> endTick().
   */
  tick(dt, weapon) {
    this.beginTick();
    const cmd = this.buildCommand(weapon);
    this.lastCmd = cmd;
    this.ctrl.update(dt, cmd);
    this.endTick(dt);
  }

  /** Start of a tick: interpolation snapshots of the previous tick. */
  beginTick() {
    this.prevFeet.copy(this.currFeet);
    this.prevEyeH = this.currEyeH;
    this.prevStep = this.currStep;
    this.prevViewY = this.viewY;
    this._holdVisuals();
    this._y0 = this.ctrl.position.y;
  }

  /** End of a tick (after the controller moved): camera filter, then camera effects (bob, dips, roll). */
  endTick(dt) {
    const c = this.ctrl;
    const y0 = this._y0;
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

    // head bob from the real gait phase, stair step impulse, landing dip, strafe roll, traversal arc
    this.cameraFx.tick(dt, c, this.yaw);
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
    const fx = this.cameraFx.sample(alpha);
    const b = this._bob;
    b.phase = fx.phase;
    b.amount = fx.amount;
    b.landingDip = fx.landingDip;
    return b;
  }

  /**
   * Applies the camera effects' roll / pitch (strafe roll, traversal arc, landing / step nod) to a camera
   * orientation built from yaw / pitch (visual only; the aim uses the simulation look). Returns q.
   */
  applyCameraEffects(q, alpha) {
    const fx = this.cameraFx.sample(alpha);
    if (fx.pitch !== 0) q.multiply(_qFx.setFromAxisAngle(_axisX, fx.pitch));
    if (fx.roll !== 0) q.multiply(_qFx.setFromAxisAngle(_axisZ, -fx.roll));
    return q;
  }

  /** Weapon lowering 0..1 while vaulting / mantling (interpolated). */
  getWeaponLower(alpha) {
    return this.cameraFx.sample(alpha).lower;
  }

  /** Interpolated eye position for rendering (alpha in [0,1] between ticks). */
  getRenderEye(alpha, out = new Vector3()) {
    out.lerpVectors(this.prevFeet, this.currFeet, alpha);
    out.y = this.prevViewY + (this.viewY - this.prevViewY) * alpha;
    const fx = this.cameraFx.sample(alpha);
    if (fx.motion > 0) {
      out.y += fx.offsetY;
      out.x += Math.cos(this.yaw) * fx.side;
      out.z -= Math.sin(this.yaw) * fx.side;
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
      cameraFx: this.cameraFx.getState(),
      cmd: this.lastCmd,
    };
  }
}
