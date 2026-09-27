// Visuals of the other combatants (not the local player): placeholder mannequins interpolated between
// the last two simulation ticks, death poses, and muzzle flashes at the gameplay muzzle of bots' shots.
// Advances on the fixed tick (tick / hold) and draws in update(alpha), like the other views.

import { AdditiveBlending, CanvasTexture, Euler, Group, Quaternion, SRGBColorSpace, Sprite, SpriteMaterial, Vector3 } from 'three';
import { CharacterView } from './characterView.js';
import { createHitShapeSet } from './hitShapes.js';
import { lookQuaternion } from '../weapons/weaponSystem.js';
import { adsBlend } from '../weapons/viewModelMotion.js';
import { getOpticDef, IRONS } from '../weapons/optics.js';

const _lq = new Quaternion();
const _hq = new Quaternion();
const _ry = new Quaternion().setFromAxisAngle(new Vector3(0, 1, 0), Math.PI / 2); // model +X -> camera -Z
const _he = new Euler(0, 0, 0, 'XYZ');
const _eye = new Vector3();
const _ro = new Vector3();

function flashTexture() {
  const s = 64;
  const c = document.createElement('canvas');
  c.width = c.height = s;
  const g = c.getContext('2d');
  const grd = g.createRadialGradient(s / 2, s / 2, 0, s / 2, s / 2, s / 2);
  grd.addColorStop(0, 'rgba(255,245,220,1)');
  grd.addColorStop(0.3, 'rgba(255,190,90,0.8)');
  grd.addColorStop(1, 'rgba(255,120,20,0)');
  g.fillStyle = grd;
  g.fillRect(0, 0, s, s);
  const t = new CanvasTexture(c);
  t.colorSpace = SRGBColorSpace;
  return t;
}

function snap(c) {
  const ctl = c.controller;
  return {
    feet: ctl.position.clone(),
    yaw: c.yaw,
    pitch: c.pitch,
    height: ctl.height,
    eyeHeight: ctl.eyeHeight,
    death: c.deathPose ? { dir: c.deathPose.dir.slice(), mode: c.deathPose.mode, angle: c.deathPose.angle } : null,
  };
}

const lerpAngle = (a, b, t) => {
  let d = b - a;
  while (d > Math.PI) d -= Math.PI * 2;
  while (d < -Math.PI) d += Math.PI * 2;
  return a + d * t;
};

export class CombatantViews {
  constructor(scene, teamsData) {
    this.scene = scene;
    this.teamsData = teamsData;
    this.group = new Group();
    this.group.name = 'combatants';
    scene.add(this.group);
    this.items = new Map();
    this.session = null;
    this._flashTex = null;
    this._tmpFeet = new Vector3();
    this.opticAssets = null; // OpticAssets (LOD1 optics for bots), set by the game once loaded
    this._rifleQuat = new Quaternion();
  }

  /** Third-person optics (LOD1) become available: bots show their mounted optic from now on. */
  setOpticAssets(assets) {
    this.opticAssets = assets;
    for (const it of this.items.values()) it.view.setOptic(null, null);
  }

  /** Rebuilds the views for a new session (all combatants except the local player). */
  setSession(session) {
    for (const it of this.items.values()) it.view.dispose();
    this.items.clear();
    this.session = session;
    if (!session) return;
    if (!this._flashTex) this._flashTex = flashTexture();
    for (const c of session.combatants.all()) {
      if (c.isPlayer) continue;
      const t = this.teamsData.teams[c.team] || { color: '#888888', dark: '#444444' };
      const view = new CharacterView({ team: c.team, color: t.color, dark: t.dark, name: c.id });
      this.group.add(view.root);
      const flash = new Sprite(new SpriteMaterial({ map: this._flashTex, blending: AdditiveBlending, depthWrite: false, transparent: true, toneMapped: false }));
      flash.scale.setScalar(0.35);
      flash.visible = false;
      this.group.add(flash);
      const s = snap(c);
      this.items.set(c.id, { c, view, prev: s, curr: snap(c), spawnSeen: c.spawnCountSeen, shapes: createHitShapeSet(), pts: { grip: new Vector3(), support: new Vector3(), muzzle: new Vector3() }, flash, flashTimer: 0 });
    }
  }

  /** A bot fired: flash at its gameplay muzzle for 50 ms of simulation time. */
  onShot(shooterId, muzzleWorld) {
    const it = this.items.get(shooterId);
    if (!it) return;
    it.flash.position.copy(muzzleWorld);
    it.flashTimer = 0.05;
  }

  /** One fixed tick (after the session tick). */
  tick(dt) {
    for (const it of this.items.values()) {
      const c = it.c;
      if (c.spawnCountSeen !== it.spawnSeen) {
        // (re)spawned: jump, do not slide across the map
        it.spawnSeen = c.spawnCountSeen;
        it.curr = snap(c);
        it.prev = snap(c);
      } else {
        it.prev = it.curr;
        it.curr = snap(c);
      }
      if (it.flashTimer > 0) it.flashTimer -= dt;
    }
  }

  /** Simulation held (menus): keep the drawn poses still. */
  hold() {
    for (const it of this.items.values()) it.prev = it.curr;
  }

  update(alpha) {
    const a = Math.min(Math.max(alpha, 0), 1);
    let visible = 0;
    for (const it of this.items.values()) {
      const p = it.prev;
      const q = it.curr;
      const parked = q.feet.y < -100;
      const show = !parked && (it.c.alive || !!q.death);
      it.view.setVisible(show);
      it.flash.visible = show && it.flashTimer > 0;
      if (!show) continue;
      visible++;
      const feet = this._tmpFeet.lerpVectors(p.feet, q.feet, a);
      const st = {
        feet,
        yaw: lerpAngle(p.yaw, q.yaw, a),
        pitch: p.pitch + (q.pitch - p.pitch) * a,
        height: p.height + (q.height - p.height) * a,
        eyeHeight: p.eyeHeight + (q.eyeHeight - p.eyeHeight) * a,
      };
      it.c.poseShapesAt(st, it.shapes, it.pts);
      // rifle frame of the drawn weapon: eye + look x (ADS / hip pose of the weapon's view-model definition)
      const w = it.c.weapon;
      const vm = w.viewModelDef;
      const ads = w.state.ads;
      const hipW = 1 - adsBlend(ads);
      const hr = vm.hipRotation || [0, 0, 0];
      lookQuaternion(st.yaw, st.pitch, _lq);
      _hq.setFromEuler(_he.set(hr[0] * hipW, hr[1] * hipW, hr[2] * hipW, 'XYZ'));
      this._rifleQuat.copy(_lq).multiply(_hq).multiply(_ry);
      const aw = adsBlend(ads);
      _ro.set(vm.hipPosition[0] + (vm.adsPosition[0] - vm.hipPosition[0]) * aw, vm.hipPosition[1] + (vm.adsPosition[1] - vm.hipPosition[1]) * aw, vm.hipPosition[2] + (vm.adsPosition[2] - vm.hipPosition[2]) * aw);
      _eye.set(feet.x, feet.y + st.eyeHeight, feet.z);
      _ro.applyQuaternion(_lq).add(_eye);
      // optic (LOD1) on the primary only
      if (this.opticAssets) {
        const id = it.c.activeWeapon === 0 ? it.c.optic : null;
        if (id !== it.view.opticId) {
          const obj = id && id !== IRONS ? this.opticAssets.cloneLod1(id) : null;
          it.view.setOptic(id, obj, obj ? getOpticDef(id).railRifle : null);
        }
      }
      let death = null;
      if (q.death) death = { dir: q.death.dir, mode: q.death.mode, angle: (p.death ? p.death.angle : 0) + (q.death.angle - (p.death ? p.death.angle : 0)) * a };
      it.view.pose({ feet, shapes: it.shapes, grip: it.pts.grip, support: it.pts.support, muzzle: it.pts.muzzle, death, rifleOrigin: _ro, rifleQuat: this._rifleQuat });
    }
    this.visibleCount = visible;
  }

  getState() {
    const out = [];
    for (const [id, it] of this.items) {
      const r = it.view.root;
      out.push({
        id,
        visible: r.visible,
        position: r.position.toArray(),
        finite: r.position.toArray().every(Number.isFinite) && [r.quaternion.x, r.quaternion.y, r.quaternion.z, r.quaternion.w].every(Number.isFinite),
        tiltDeg: (2 * Math.acos(Math.min(1, Math.abs(r.quaternion.w))) * 180) / Math.PI,
        bones: Object.keys(it.view.bones).length,
        optic: it.view.opticId,
        opticLod1: it.view.opticSlot.children.length > 0,
        opticRole: it.c.opticRole,
      });
    }
    return out;
  }
}
