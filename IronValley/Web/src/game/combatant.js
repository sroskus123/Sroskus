// One combatant = the player or a bot (Docs/GAMEPLAY_CONTRACTS.md, "Combatant"). Both use the same
// capsule controller, the same core weapon states (owned by Match) with the same hitscan / muzzle
// validation, and the same command format; they differ only in who produces the command.
//
//   cmd = { moveX, moveZ, yaw, pitch, sprint, walk, crouch, jump, ads, fire, reload, switchTo, interact }
//
// alive / health are read from Match (authoritative). Death sets the core life lock on all weapons, so a
// dead combatant cannot fire or reload whatever the command says (GUN-03). No DOM, Node-testable.

import { Quaternion, Vector3 } from 'three';
import { CharacterController } from '../physics/characterController.js';
import { bindMovementEvents } from '../player/movementEvents.js';
import { WeaponSystem, lookQuaternion } from '../weapons/weaponSystem.js';
import { createHitShapeSet, shapeBounds, updateHitShapes } from './hitShapes.js';
import { DEG2RAD, clamp, wrapAngle } from '../util/math.js';

export const IDLE_COMMAND = Object.freeze({
  moveX: 0,
  moveZ: 0,
  yaw: null,
  pitch: null,
  sprint: false,
  walk: false,
  crouch: false,
  jump: false,
  ads: false,
  fire: false,
  reload: false,
  switchTo: null,
  interact: false,
});

const _q = new Quaternion();
const _v = new Vector3();
const _grip = new Vector3();
const _muz = new Vector3();

const RELOAD_EVENT = {
  reload_start: 'weapon:reload_started',
  reload_complete: 'weapon:reload_finished',
  reload_interrupted: 'weapon:reload_interrupted',
};

export class Combatant {
  /**
   * @param {object} o
   * @param {string} o.id
   * @param {number} o.team
   * @param {boolean} o.isPlayer
   * @param {string} o.name
   * @param {object} o.ctx  session context: { world, movement, match, rules, weaponsData, combat, events, worldQuery, dummies, rng(seed), damageSink, now() }
   */
  constructor({ id, team, isPlayer = false, name = id, index = 0, ctx }) {
    this.id = id;
    this.team = team;
    this.isPlayer = isPlayer;
    this.name = name;
    this.index = index;
    this.ctx = ctx;
    this.controller = new CharacterController(ctx.world, ctx.movement);
    // 'footstep' (per foot contact of the controller's gait) and 'traverse:start' / 'traverse:end' on the bus
    bindMovementEvents(this.controller, { owner: this, events: ctx.events, surfaceAt: (p) => ctx.worldQuery.surfaceAt(p), isActive: () => this.alive });
    this.yaw = 0;
    this.pitch = 0;
    this.turnRateDegPerSec = ctx.combat.bots.turnRateDegPerSec;
    this.pitchLimit = (ctx.combat.bots.pitchLimitDeg ?? 85) * DEG2RAD;
    this.lastCmd = IDLE_COMMAND;
    this.lastStepTick = -1;
    this.kills = 0;
    this.deathsSeen = 0;
    this.spawnCountSeen = 0;
    this.spawnPointIndex = -1;
    this.failedSpawnAttemptsBase = 0; // core failedSpawnAttempts when the current wait for a spawn began
    this.lastAttackerId = null;
    this.deathPose = null; // { dir:[x,z], mode:'fall'|'crumple', t, duration, angle }
    this.footDist = 0;
    this.optic = 'collimator';

    // weapons: [primary, secondary] from the core participant (Match owns the WeaponState objects)
    const wd = ctx.weaponsData;
    const defs = [wd[wd.loadout.primary], wd[wd.loadout.secondary]];
    this.weapons = defs.map((def, slot) => {
      const core = ctx.match.respawn.weapon(id, def.rulesId);
      if (!core) throw new Error(`Combatant ${id}: core weapon ${def.rulesId} missing (loadout)`);
      return new WeaponSystem({
        def,
        rng: ctx.rng(index * 7 + slot + 1),
        core,
        rules: ctx.rules,
        raycast: (o, d, far, ignoreId) => ctx.worldQuery.raycastCombat(o, d, far, ignoreId),
        owner: this,
        hitZones: ctx.combat.hitZones,
        dummies: ctx.dummies,
        events: ctx.events,
        damageSink: (hit, amount, shot) => ctx.damageSink(this, hit, amount, shot),
      });
    });
    this.activeWeapon = 0;
    this.switchTimer = 0;
    this.weapons[1].state.core.disable('switch'); // holstered

    this._shapes = createHitShapeSet();
    this._shapeKey = '';
    this.boundsMin = new Vector3();
    this.boundsMax = new Vector3();
    this.gripHip = new Vector3();
    this.gripSupport = new Vector3();
    this._pts = { grip: new Vector3(), support: new Vector3(), muzzle: new Vector3() };
    this._eyeTick = new Vector3();
  }

  // ------------------------------------------------------------------ authoritative state (Match)

  get participant() {
    return this.ctx.match.respawn.participant(this.id);
  }

  get alive() {
    return this.ctx.match.respawn.isAlive(this.id);
  }

  get health() {
    const p = this.participant;
    return p ? p.health : 0;
  }

  get lifeState() {
    const p = this.participant;
    return p ? p.state : 'unknown';
  }

  get position() {
    return this.controller.position;
  }

  get weapon() {
    return this.weapons[this.activeWeapon];
  }

  getEye(out = new Vector3()) {
    const c = this.controller;
    return out.set(c.position.x, c.position.y + c.eyeHeight, c.position.z);
  }

  /** Current hit zones (head, torso, 2 arms, 2 legs), world space. */
  hitShapes() {
    this.updateHitShapes();
    return this._shapes;
  }

  updateHitShapes() {
    const c = this.controller;
    const p = c.position;
    const key = `${p.x},${p.y},${p.z},${this.yaw},${this.pitch},${c.height},${c.eyeHeight},${this.activeWeapon},${this.weapon.state.ads}`;
    if (key === this._shapeKey) return;
    this._shapeKey = key;
    this.poseShapesAt({ feet: p, yaw: this.yaw, pitch: this.pitch, height: c.height, eyeHeight: c.eyeHeight }, this._shapes, this._pts);
    this.gripHip.copy(this._pts.grip);
    this.gripSupport.copy(this._pts.support);
    shapeBounds(this._shapes, this.boundsMin, this.boundsMax);
  }

  /**
   * Hit zones for an arbitrary pose (the interpolated render state uses it too, so the placeholder body
   * is drawn exactly where it can be hit). Writes grip / support hand / muzzle (no recoil) into outPts.
   * @param st { feet, yaw, pitch, height, eyeHeight }
   */
  poseShapesAt(st, outShapes, outPts) {
    const w = this.weapon;
    const vm = w.def.viewModel;
    const ads = w.state.ads;
    const eye = _v.set(st.feet.x, st.feet.y + st.eyeHeight, st.feet.z);
    lookQuaternion(st.yaw, st.pitch, _q);
    _grip.fromArray(vm.hipPosition).lerp(_muz.fromArray(vm.adsPosition), ads);
    w.muzzleOffset(ads, _muz);
    outPts.support.copy(_grip).lerp(_muz, 0.55).applyQuaternion(_q).add(eye);
    outPts.grip.copy(_grip).applyQuaternion(_q).add(eye);
    outPts.muzzle.copy(_muz).applyQuaternion(_q).add(eye);
    updateHitShapes(outShapes, this.ctx.combat.hitShapes, {
      feet: st.feet,
      height: st.height,
      standHeight: this.controller.standHeight,
      eyeHeight: st.eyeHeight,
      yaw: st.yaw,
      pitch: st.pitch,
      gripHip: outPts.grip,
      gripSupport: outPts.support,
    });
    return outShapes;
  }

  /** Muzzle position in world space of the active weapon (for muzzle flashes / debug). */
  muzzleWorld(out = new Vector3()) {
    const w = this.weapon;
    return w.muzzleWorld(this.getEye(new Vector3()), this.yaw, this.pitch, w.state.ads, out);
  }

  // ------------------------------------------------------------------ lifecycle

  /** Places the combatant at a spawn point (called by CombatantManager on the core 'spawned' event). */
  spawnAt(pos, yawDeg = 0) {
    this.controller.crouched = false;
    this.controller.height = this.controller.standHeight;
    this.controller.eyeHeight = this.controller.standEyeHeight;
    this.controller.teleport(pos);
    this.yaw = yawDeg * DEG2RAD;
    this.pitch = 0;
    this.deathPose = null;
    this.lastAttackerId = null;
    this.footDist = 0;
    this.lastCmd = IDLE_COMMAND;
    // loadout was reset by the core (resetToLoadout); engine side: primary drawn, no switch in progress
    this.activeWeapon = 0;
    this.switchTimer = 0;
    this.weapons[0].state.core.enable('switch');
    this.weapons[1].state.core.disable('switch');
    for (const w of this.weapons) {
      w.recoil.reset();
      w.state.ads = 0;
      w.state.releaseInputs();
    }
    this._shapeKey = '';
  }

  /** Death (core already killed the participant): choose a stable fall direction with free space. */
  beginDeath({ fromDir = null, attackerId = null } = {}) {
    this.lastAttackerId = attackerId;
    const cfg = this.ctx.combat.death;
    const base = fromDir && Math.hypot(fromDir.x, fromDir.z) > 1e-6 ? new Vector3(fromDir.x, 0, fromDir.z).normalize() : new Vector3(-Math.sin(this.yaw), 0, -Math.cos(this.yaw)).negate();
    const candidates = [base, new Vector3(-base.z, 0, base.x), new Vector3(base.z, 0, -base.x), base.clone().negate()];
    let dir = null;
    const p = this.controller.position;
    for (const d of candidates) {
      let free = true;
      for (const h of [0.15, 0.45, 0.9]) {
        const o = new Vector3(p.x, p.y + h, p.z);
        if (this.ctx.worldQuery.raycastStatic(o, d, cfg.fallClearance)) {
          free = false;
          break;
        }
      }
      if (free) {
        dir = d;
        break;
      }
    }
    this.deathPose = {
      dir: dir ? [dir.x, dir.z] : [base.x, base.z],
      mode: dir ? 'fall' : 'crumple',
      t: 0,
      duration: cfg.fallTime,
      angle: 0,
      settled: false,
    };
    for (const w of this.weapons) w.state.releaseInputs();
  }

  // ------------------------------------------------------------------ the single behaviour entry

  /**
   * One fixed tick for this combatant, driven by `cmd` (same format for player and bots).
   * Call exactly once per tick (the CombatantManager steps combatants the AI did not drive).
   */
  applyCommand(cmd, dt) {
    const ctx = this.ctx;
    this.lastStepTick = ctx.tick();
    cmd = cmd || IDLE_COMMAND;
    this.lastCmd = cmd;
    const alive = this.alive;
    const c = this.controller;
    const dtUs = ctx.dtUs();

    if (alive) {
      // --- look (bots: limited turn rate) ---
      if (typeof cmd.yaw === 'number' && Number.isFinite(cmd.yaw)) {
        if (this.isPlayer) this.yaw = cmd.yaw;
        else {
          const maxTurn = this.turnRateDegPerSec * DEG2RAD * dt;
          this.yaw += clamp(wrapAngle(cmd.yaw - this.yaw), -maxTurn, maxTurn);
          this.yaw = wrapAngle(this.yaw);
        }
      }
      if (typeof cmd.pitch === 'number' && Number.isFinite(cmd.pitch)) {
        const target = clamp(cmd.pitch, -this.pitchLimit, this.pitchLimit);
        if (this.isPlayer) this.pitch = target;
        else {
          const maxTurn = this.turnRateDegPerSec * DEG2RAD * dt;
          this.pitch += clamp(target - this.pitch, -maxTurn, maxTurn);
        }
      }
      // --- weapon switch (core 'switch' lock on the holstered / drawing weapon) ---
      if ((cmd.switchTo === 0 || cmd.switchTo === 1) && cmd.switchTo !== this.activeWeapon) this.switchWeapon(cmd.switchTo);
      // --- movement ---
      c.update(dt, {
        moveX: cmd.moveX || 0,
        moveZ: cmd.moveZ || 0,
        yaw: this.yaw,
        sprint: !!cmd.sprint,
        walk: !!cmd.walk,
        crouch: !!cmd.crouch,
        jump: !!cmd.jump,
        ads: !!cmd.ads,
        fire: !!cmd.fire,
      });
    } else {
      // dead: body stays (gravity only), no input
      c.update(dt, { moveX: 0, moveZ: 0, yaw: this.yaw, sprint: false, walk: false, crouch: false, jump: false, ads: false, fire: false });
      this._advanceDeathPose(dt);
    }

    // --- switch timer ---
    if (this.switchTimer > 0) {
      this.switchTimer -= dt;
      if (this.switchTimer <= 0) {
        this.switchTimer = 0;
        this.weapon.state.core.enable('switch');
      }
    }
    // --- sprint lock (sprint interrupts reload, core reason 'sprint'); a vault / mantle needs the hands too,
    // until the weapon is raised again (controller.handsBusy) ---
    for (const w of this.weapons) {
      if ((c.sprinting || c.handsBusy) && alive) w.state.core.disable('sprint');
      else w.state.core.enable('sprint');
    }
    // --- weapons: every weapon is updated every tick with the real trigger state (core contract) ---
    const eye = this.getEye(this._eyeTick);
    // The REAL trigger state goes to the active weapon also while dead / locked: the core needs it to
    // see that a trigger held through death, menu or respawn is not a new press (Docs/RULES.md, R20).
    for (let i = 0; i < this.weapons.length; i++) {
      const w = this.weapons[i];
      const active = i === this.activeWeapon;
      w.tick(dt, { trigger: active && !!cmd.fire, ads: active && alive && !!cmd.ads, reload: active && alive && !!cmd.reload, sprinting: c.sprinting, dtUs }, eye, this.yaw, this.pitch);
      this._forwardWeaponEvents(w, active && alive);
    }
    this._shapeKey = '';
  }

  switchWeapon(slot) {
    if (slot === this.activeWeapon || !this.weapons[slot]) return false;
    const old = this.weapon;
    old.state.core.disable('switch'); // interrupts a reload with reason 'switch'
    old.state.ads = 0;
    this.activeWeapon = slot;
    const w = this.weapon;
    w.state.core.disable('switch'); // stays locked while drawing
    this.switchTimer = Math.max(1e-3, w.def.switchTime ?? 0.4);
    this.ctx.events.emit('weapon:switched', { id: this.id, weaponId: w.def.id, slot });
    return true;
  }

  _forwardWeaponEvents(w, active) {
    const ev = w.state.lastEvents;
    if (!ev || ev.length === 0) return;
    for (const e of ev) {
      const name = RELOAD_EVENT[e.type];
      if (name) this.ctx.events.emit(name, { id: this.id, weaponId: w.def.id, kind: e.detail || w.state.core.reloadKind });
      else if (e.type === 'dry_fire') {
        this.ctx.events.emit('weapon:dry_fire', { id: this.id, weaponId: w.def.id });
        // engine policy: a trigger pull on an empty weapon starts a reload when there is reserve
        if (active && w.state.reserve > 0) w.state.reload();
      } else if (e.type === 'mag_insert' || e.type === 'bolt_release' || e.type === 'chamber_start' || e.type === 'chamber_commit') {
        // core stage / commit moments (charging handle or slide pulled, magazine seated, bolt / slide forward)
        this.ctx.events.emit('weapon:action', { id: this.id, weaponId: w.def.id, type: e.type });
      }
    }
  }

  _advanceDeathPose(dt) {
    const d = this.deathPose;
    if (!d || d.settled) return;
    d.t = Math.min(d.duration, d.t + dt);
    const u = d.t / d.duration;
    const ease = 1 - (1 - u) * (1 - u); // ease-out, no overshoot (never "explodes")
    d.angle = (d.mode === 'fall' ? Math.PI / 2 : Math.PI / 2.6) * ease;
    if (d.t >= d.duration) d.settled = true;
  }

  getState() {
    const p = this.controller.position;
    const part = this.participant;
    return {
      id: this.id,
      name: this.name,
      team: this.team,
      isPlayer: this.isPlayer,
      alive: this.alive,
      state: part ? part.state : 'unknown',
      health: this.health,
      position: [p.x, p.y, p.z],
      yawDeg: this.yaw / DEG2RAD,
      pitchDeg: this.pitch / DEG2RAD,
      crouched: this.controller.crouched,
      activeWeapon: this.activeWeapon,
      switching: this.switchTimer > 0,
      weapon: this.weapon.state.getState(),
      weapons: this.weapons.map((w) => w.state.getState()),
      spawnCount: part ? part.spawnCount : 0,
      deaths: part ? part.deaths : 0,
      kills: this.kills,
      respawnInS: part ? part.respawnInUs / 1e6 : 0,
      spawnPoint: this.spawnPointIndex,
      deathPose: this.deathPose ? { ...this.deathPose } : null,
      lastStepTick: this.lastStepTick,
    };
  }
}
