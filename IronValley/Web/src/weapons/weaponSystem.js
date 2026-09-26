// Weapon system for ONE weapon of ONE combatant (player or bot - same code path, decision D8 / §7):
// runs the authoritative core weapon state (through WeaponHandle) on the fixed tick, computes the camera
// ray and the muzzle position, resolves each round with traceShot (camera ray picks the aim point, the
// segment muzzle -> aim point decides the hit) against a raycast function supplied by the game (static
// world + combatant hit zones + test dummies), applies dummy damage and hands combatant hits to the
// game's damage sink (which goes through Match). Publishes weapon:fired / weapon:hit. No rendering, so
// it is testable in Node.

import { Euler, Quaternion, Vector3 } from 'three';
import { traceShot } from './hitscan.js';
import { Recoil } from './recoil.js';
import { WeaponHandle } from './weaponState.js';
import { adsBlend, viewModelPointInCamera } from './viewModelMotion.js';
import { baseRulesCompiled } from '../game/gameRules.js';

const _euler = new Euler(0, 0, 0, 'YXZ');
const _q = new Quaternion();
const FORWARD = new Vector3(0, 0, -1);

/** Orientation of a first-person camera from yaw (about +Y) and pitch (about +X). */
export function lookQuaternion(yaw, pitch, out = new Quaternion()) {
  _euler.set(pitch, yaw, 0, 'YXZ');
  return out.setFromEuler(_euler);
}

/** Damage of one round: rules damage x hit-zone multiplier, integer >= 1 (the core takes integers). */
export function roundDamage(baseDamage, multiplier) {
  return Math.max(1, Math.round(baseDamage * (multiplier ?? 1)));
}

export class WeaponSystem {
  /**
   * @param {object} o
   * @param {object} o.def                weapons.json entry (rulesId links it to rules.json)
   * @param {import('../physics/collisionWorld.js').CollisionWorld} [o.world]
   * @param {import('../game/targetDummies.js').TargetDummies} [o.dummies]
   * @param {import('../engine/events.js').EventBus} [o.events]
   * @param {object} o.rng
   * @param {object} [o.core]     core WeaponState owned by Match (else a standalone one from rules.json)
   * @param {object} [o.rules]    compiled rules (default: Shared/config/rules.json)
   * @param {Function} [o.raycast] (origin, dir, far, ignoreId) -> nearest hit {kind, targetKey, point, normal, distance, ...}
   * @param {object} [o.owner]    { id, team } of the combatant holding the weapon
   * @param {object} [o.hitZones] multipliers per part for combatant hits
   * @param {Function} [o.damageSink] (hit, amount, shotRecord) -> damage result for combatant hits
   */
  constructor({ def, world = null, dummies = null, events = null, rng, core = null, rules = null, raycast = null, owner = null, hitZones = null, damageSink = null }) {
    this.def = def;
    this.world = world;
    this.dummies = dummies;
    this.events = events;
    this.owner = owner || { id: 'standalone', team: 0 };
    this.hitZones = hitZones || { head: 2, torso: 1, arm: 0.7, leg: 0.75 };
    this.damageSink = damageSink;
    const R = rules || baseRulesCompiled();
    const rulesDef = R.weapons[def.rulesId];
    if (!rulesDef) throw new Error(`WeaponSystem: rules.json has no weapon "${def.rulesId}" for ${def.id}`);
    this.rulesDef = rulesDef;
    this.damage = rulesDef.damage;
    this.state = new WeaponHandle({ def, core, rulesDef });
    this.recoil = new Recoil(def.recoil, rng);
    this.lastShot = null;
    this.hitsOnDummies = 0;
    this.hitsOnCombatants = 0;
    this.hitsOnWorld = 0;
    this.misses = 0;
    this.blockedShots = 0;
    this._eye = new Vector3();
    this._yaw = 0;
    this._pitch = 0;
    this.setViewModel(def.viewModel, def.muzzleOffsetHip, def.muzzleOffsetAds);
    this.raycast = raycast
      ? (origin, dir, far) => raycast(origin, dir, far, this.owner.id)
      : (origin, dir, far) => this._raycast(origin, dir, far);
  }

  /**
   * Muzzle offsets follow the drawn view-model path between hip and ADS (eased blend plus hip cant),
   * not a straight line between the two data offsets, so shots leave from the drawn muzzle during the
   * whole transition (GUN-02). The data offsets stay exact at the end poses.
   */
  setViewModel(vm, hipOffset, adsOffset) {
    this._hipOffset = new Vector3().fromArray(hipOffset);
    this._adsOffset = new Vector3().fromArray(adsOffset);
    this._vm = vm && vm.muzzleLocal && vm.hipPosition && vm.adsPosition ? vm : null;
    if (this._vm) {
      this._hipCorr = this._hipOffset.clone().sub(viewModelPointInCamera(vm, vm.muzzleLocal, 0));
      this._adsCorr = this._adsOffset.clone().sub(viewModelPointInCamera(vm, vm.muzzleLocal, 1));
    }
  }

  /** Nearest hit among static world and dummies (standalone use / unit tests). */
  _raycast(origin, dir, far) {
    let best = null;
    const w = this.world ? this.world.raycast(origin, dir, far) : null;
    if (w) best = { ...w, kind: 'world', targetKey: `world:${w.solidId}` };
    if (this.dummies) {
      const d = this.dummies.raycast(origin, dir, best ? Math.min(far, best.distance) : far);
      if (d && (!best || d.distance < best.distance)) best = d;
    }
    return best;
  }

  /** Muzzle offset in camera space (x right, y up, -z forward) at the ADS amount 0..1. */
  muzzleOffset(ads, out = new Vector3()) {
    if (!this._vm) return out.lerpVectors(this._hipOffset, this._adsOffset, ads);
    const w = adsBlend(ads);
    viewModelPointInCamera(this._vm, this._vm.muzzleLocal, ads, out);
    return out.addScaledVector(this._hipCorr, 1 - w).addScaledVector(this._adsCorr, w);
  }

  /** Muzzle position in world space for the given eye/look (recoil included). */
  muzzleWorld(eye, yaw, pitch, ads, out = new Vector3()) {
    lookQuaternion(yaw + this.recoil.yaw, pitch + this.recoil.pitch, _q);
    this.muzzleOffset(ads, out).applyQuaternion(_q);
    return out.add(eye);
  }

  aimDirection(yaw, pitch, out = new Vector3()) {
    lookQuaternion(yaw + this.recoil.yaw, pitch + this.recoil.pitch, _q);
    return out.copy(FORWARD).applyQuaternion(_q);
  }

  /**
   * One fixed tick (call every tick, also for a holstered / locked weapon: core contract).
   * @param {number} dt seconds
   * @param {object} inp { trigger, ads, reload, sprinting, dtUs? }
   * @param {Vector3} eye  simulation eye position
   */
  tick(dt, inp, eye, yaw, pitch) {
    this._eye.copy(eye);
    this._yaw = yaw;
    this._pitch = pitch;
    this.recoil.snapshot();
    if (inp.reload) this.state.reload();
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
    const hit = result.hit;
    if (hit) {
      if (hit.kind === 'dummy' && this.dummies) {
        damageResult = this.dummies.applyHit(hit, this.damage);
        this.hitsOnDummies++;
      } else if (hit.kind === 'combatant') {
        this.hitsOnCombatants++;
        const amount = roundDamage(this.damage, this.hitZones[hit.part]);
        damageResult = this.damageSink ? this.damageSink(hit, amount, { dir, muzzle, weaponId: this.def.id }) : null;
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
      hitTarget: hit ? hit.targetKey : null,
      hitKind: hit ? hit.kind : null,
      hitPart: hit && hit.part ? hit.part : null,
      hitPoint: hit ? hit.point.toArray() : null,
      blocked: result.blocked,
      blockedBy: result.blockedBy,
      damage: damageResult,
    };
    if (this.events) {
      this.events.emit('weapon:fired', {
        shooterId: this.owner.id,
        team: this.owner.team,
        weaponId: this.def.id,
        muzzle,
        dir,
        loudness: this.def.loudness ?? 1,
        result,
        ads: this.state.ads,
        shot: this.lastShot,
      });
      if (hit) {
        this.events.emit('weapon:hit', {
          shooterId: this.owner.id,
          victimId: hit.kind === 'combatant' ? hit.combatantId : null,
          point: hit.point,
          normal: hit.normal,
          surface: hit.mat || (hit.kind === 'combatant' ? 'flesh' : hit.kind),
          part: hit.part || null,
          blocked: result.blocked,
          hit,
          damage: damageResult,
        });
      }
    }
    this.recoil.kick(this.state.ads);
  }

  getState() {
    return {
      ...this.state.getState(),
      recoilPitchDeg: (this.recoil.pitch * 180) / Math.PI,
      recoilYawDeg: (this.recoil.yaw * 180) / Math.PI,
      hitsOnDummies: this.hitsOnDummies,
      hitsOnCombatants: this.hitsOnCombatants,
      hitsOnWorld: this.hitsOnWorld,
      misses: this.misses,
      blockedShots: this.blockedShots,
      lastShot: this.lastShot,
    };
  }
}
