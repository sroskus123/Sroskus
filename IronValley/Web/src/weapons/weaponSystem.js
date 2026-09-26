// Weapon system: runs the weapon state machine on the fixed tick, computes the camera ray
// and the muzzle position, resolves hits (D8) against the static world and the target
// dummies, and publishes events for visuals (view model, muzzle flash, impacts, HUD).
// No rendering here, so it is testable in Node.

import { Euler, Quaternion, Vector3 } from 'three';
import { traceShot } from './hitscan.js';
import { Recoil } from './recoil.js';
import { WeaponState } from './weaponState.js';

const _euler = new Euler(0, 0, 0, 'YXZ');
const _q = new Quaternion();
const FORWARD = new Vector3(0, 0, -1);

/** Orientation of a first-person camera from yaw (about +Y) and pitch (about +X). */
export function lookQuaternion(yaw, pitch, out = new Quaternion()) {
  _euler.set(pitch, yaw, 0, 'YXZ');
  return out.setFromEuler(_euler);
}

export class WeaponSystem {
  /**
   * @param {object} o
   * @param {object} o.def                weapon definition (weapons.json entry)
   * @param {import('../physics/collisionWorld.js').CollisionWorld} o.world
   * @param {import('../game/targetDummies.js').TargetDummies} [o.dummies]
   * @param {import('../engine/events.js').EventBus} [o.events]
   * @param {object} o.rng
   */
  constructor({ def, world, dummies = null, events = null, rng }) {
    this.def = def;
    this.world = world;
    this.dummies = dummies;
    this.events = events;
    this.state = new WeaponState(def);
    this.recoil = new Recoil(def.recoil, rng);
    this.lastShot = null;
    this.hitsOnDummies = 0;
    this.hitsOnWorld = 0;
    this.misses = 0;
    this.blockedShots = 0;
    this._eye = new Vector3();
    this._yaw = 0;
    this._pitch = 0;
    this._hipOffset = new Vector3().fromArray(def.muzzleOffsetHip);
    this._adsOffset = new Vector3().fromArray(def.muzzleOffsetAds);
    this.raycast = (origin, dir, far) => this._raycast(origin, dir, far);
  }

  /** Nearest hit among static world and dummies, tagged with kind / targetKey. */
  _raycast(origin, dir, far) {
    let best = null;
    const w = this.world.raycast(origin, dir, far);
    if (w) {
      best = { ...w, kind: 'world', targetKey: `world:${w.solidId}` };
    }
    if (this.dummies) {
      const d = this.dummies.raycast(origin, dir, best ? Math.min(far, best.distance) : far);
      if (d && (!best || d.distance < best.distance)) best = d;
    }
    return best;
  }

  /** Muzzle position in world space for the given eye/look (recoil included). */
  muzzleWorld(eye, yaw, pitch, ads, out = new Vector3()) {
    lookQuaternion(yaw + this.recoil.yaw, pitch + this.recoil.pitch, _q);
    out.lerpVectors(this._hipOffset, this._adsOffset, ads).applyQuaternion(_q);
    return out.add(eye);
  }

  aimDirection(yaw, pitch, out = new Vector3()) {
    lookQuaternion(yaw + this.recoil.yaw, pitch + this.recoil.pitch, _q);
    return out.copy(FORWARD).applyQuaternion(_q);
  }

  /**
   * One fixed tick.
   * @param {number} dt
   * @param {object} inp { trigger, ads, reload, canFire, sprinting }
   * @param {Vector3} eye  simulation eye position
   * @param {number} yaw
   * @param {number} pitch
   */
  tick(dt, inp, eye, yaw, pitch) {
    this._eye.copy(eye);
    this._yaw = yaw;
    this._pitch = pitch;
    this.recoil.snapshot();
    const fired = this.state.tick(dt, inp, () => this._fireOne());
    this.recoil.recover(dt);
    return fired;
  }

  _fireOne() {
    const eye = this._eye;
    const dir = this.aimDirection(this._yaw, this._pitch, new Vector3());
    const muzzle = this.muzzleWorld(eye, this._yaw, this._pitch, this.state.ads, new Vector3());
    const result = traceShot({ eye, dir, muzzle, range: this.def.range, raycast: this.raycast });
    let damageResult = null;
    if (result.hit) {
      if (result.hit.kind === 'dummy' && this.dummies) {
        damageResult = this.dummies.applyHit(result.hit, this.def.damage);
        this.hitsOnDummies++;
      } else {
        this.hitsOnWorld++;
      }
    } else {
      this.misses++;
    }
    if (result.blocked) this.blockedShots++;
    this.lastShot = {
      index: this.state.shotsFired,
      eye: eye.toArray(),
      muzzle: muzzle.toArray(),
      aimPoint: result.aimPoint.toArray(),
      cameraTarget: result.camHit ? result.camHit.targetKey : null,
      hitTarget: result.hit ? result.hit.targetKey : null,
      hitKind: result.hit ? result.hit.kind : null,
      hitPart: result.hit && result.hit.part ? result.hit.part : null,
      hitPoint: result.hit ? result.hit.point.toArray() : null,
      blocked: result.blocked,
      blockedBy: result.blockedBy,
    };
    if (this.events) {
      this.events.emit('weapon:fired', { muzzle, dir, result, ads: this.state.ads, shot: this.lastShot });
      if (result.hit) this.events.emit('weapon:hit', { hit: result.hit, damage: damageResult, blocked: result.blocked });
    }
    this.recoil.kick(this.state.ads);
  }

  getState() {
    return {
      ...this.state.getState(),
      recoilPitchDeg: (this.recoil.pitch * 180) / Math.PI,
      recoilYawDeg: (this.recoil.yaw * 180) / Math.PI,
      hitsOnDummies: this.hitsOnDummies,
      hitsOnWorld: this.hitsOnWorld,
      misses: this.misses,
      blockedShots: this.blockedShots,
      lastShot: this.lastShot,
    };
  }
}
