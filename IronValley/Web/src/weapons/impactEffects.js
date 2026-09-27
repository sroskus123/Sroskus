// Bullet impact effects: pooled decals (one instanced draw call), spark particles and small
// dust puffs, per surface (IMPACT_SURFACES: concrete / plaster / metal / wood / dirt / flesh / target,
// kept subtle: sparks only on metal and a couple on concrete), plus the world-space muzzle light and the
// muzzle effects (smoke puffs, spent casings: MuzzleEffects). Visual only; driven by weapon events and
// advanced on the fixed simulation tick.

import {
  AdditiveBlending,
  BufferAttribute,
  BufferGeometry,
  CanvasTexture,
  Color,
  DynamicDrawUsage,
  Euler,
  InstancedMesh,
  Matrix4,
  MeshStandardMaterial,
  NormalBlending,
  PlaneGeometry,
  PointLight,
  Points,
  PointsMaterial,
  Quaternion,
  SRGBColorSpace,
  Sprite,
  SpriteMaterial,
  Vector3,
} from 'three';
import weaponsData from '../data/weapons.json' with { type: 'json' };
import attachments from '../data/attachments.json' with { type: 'json' };
import { MuzzleEffects, resolveFeel } from './muzzleEffects.js';
import { adsBlend, viewModelPointInCamera } from './viewModelMotion.js';

// first-person muzzle light / smoke in ADS (attachments.json view.flashAds): the world light lit everything in
// front for 0.04 s at every shot, the smoke puff drifted across the sight picture
const FLASH_ADS = { worldLight: 1, smoke: 1, ...((attachments.view && attachments.view.flashAds) || {}) };

// level material -> surface (mirrors SURFACE_OF_MAT in src/game/worldQuery.js, used for footsteps)
const SURFACE_OF_MAT = {
  floor: 'concrete',
  wall: 'plaster',
  block: 'concrete',
  stair: 'concrete',
  ramp: 'concrete',
  hazard: 'metal',
  accent: 'metal',
  dark: 'metal',
  // generated level geometry / terrain surfaces (layout.json surfaces)
  grass: 'dirt',
  mud: 'dirt',
  gravel: 'dirt',
  forest_floor: 'dirt',
  water: 'dirt',
  asphalt: 'concrete',
  paving: 'concrete',
  stone: 'concrete',
  tiles: 'concrete',
  tile: 'concrete',
  glass: 'metal',
};

/**
 * Impact look per surface. decal = hole size (m, 0 = none) tinted by decalColor; sparks = count (additive,
 * short); dust = puff { color, opacity, size (m), grow (per s), life (s), speed (m/s along the normal) }.
 */
export const IMPACT_SURFACES = {
  concrete: { decal: 0.08, decalColor: '#ffffff', sparks: 2, sparkColor: [0.95, 0.6, 0.3], dust: { color: '#b9b2a4', opacity: 0.5, size: 0.1, grow: 2.0, life: 0.7, speed: 0.45 } },
  plaster: { decal: 0.085, decalColor: '#efe9df', sparks: 0, sparkColor: [0, 0, 0], dust: { color: '#d8d2c6', opacity: 0.55, size: 0.11, grow: 2.2, life: 0.8, speed: 0.5 } },
  metal: { decal: 0.05, decalColor: '#7a7a78', sparks: 7, sparkColor: [1.45, 0.78, 0.3], dust: { color: '#8c8a86', opacity: 0.2, size: 0.05, grow: 1.6, life: 0.35, speed: 0.3 } },
  wood: { decal: 0.07, decalColor: '#a07f5a', sparks: 0, sparkColor: [0, 0, 0], dust: { color: '#8b6a45', opacity: 0.45, size: 0.08, grow: 1.8, life: 0.6, speed: 0.4 } },
  dirt: { decal: 0.08, decalColor: '#5d4e3c', sparks: 0, sparkColor: [0, 0, 0], dust: { color: '#7a6a55', opacity: 0.55, size: 0.13, grow: 2.4, life: 0.9, speed: 0.6 } },
  flesh: { decal: 0, decalColor: '#ffffff', sparks: 0, sparkColor: [0, 0, 0], dust: { color: '#6e2a24', opacity: 0.28, size: 0.05, grow: 1.5, life: 0.25, speed: 0.2 } },
  target: { decal: 0, decalColor: '#ffffff', sparks: 1, sparkColor: [0.9, 0.55, 0.3], dust: { color: '#a89f8c', opacity: 0.3, size: 0.06, grow: 1.6, life: 0.4, speed: 0.3 } },
};

/** Surface of a hit: combatant -> flesh, dummy -> target, world -> level material mapping. */
export function impactSurface(hit) {
  if (!hit) return 'concrete';
  if (hit.kind === 'combatant') return 'flesh';
  if (hit.kind === 'dummy') return 'target';
  const m = hit.mat === 'terrain' && hit.surface ? hit.surface : hit.mat;
  if (m && IMPACT_SURFACES[m]) return m;
  return (m && SURFACE_OF_MAT[m]) || 'concrete';
}

function holeTexture() {
  const s = 128;
  const c = document.createElement('canvas');
  c.width = c.height = s;
  const g = c.getContext('2d');
  g.clearRect(0, 0, s, s);
  // scorched ring
  const grd = g.createRadialGradient(s / 2, s / 2, 2, s / 2, s / 2, s / 2);
  grd.addColorStop(0, 'rgba(8,7,6,1)');
  grd.addColorStop(0.24, 'rgba(14,12,11,1)');
  grd.addColorStop(0.36, 'rgba(45,41,37,0.85)');
  grd.addColorStop(0.62, 'rgba(80,75,68,0.35)');
  grd.addColorStop(1, 'rgba(90,84,76,0)');
  g.fillStyle = grd;
  g.beginPath();
  g.arc(s / 2, s / 2, s / 2, 0, Math.PI * 2);
  g.fill();
  // chipped edge flecks
  g.fillStyle = 'rgba(200,196,188,0.35)';
  for (let i = 0; i < 14; i++) {
    const a = (i / 14) * Math.PI * 2 + (i % 3) * 0.2;
    const r = s * (0.2 + (i % 4) * 0.04);
    g.beginPath();
    g.arc(s / 2 + Math.cos(a) * r, s / 2 + Math.sin(a) * r, 2 + (i % 3), 0, Math.PI * 2);
    g.fill();
  }
  const t = new CanvasTexture(c);
  t.colorSpace = SRGBColorSpace;
  return t;
}

function sparkTexture() {
  const s = 32;
  const c = document.createElement('canvas');
  c.width = c.height = s;
  const g = c.getContext('2d');
  const grd = g.createRadialGradient(s / 2, s / 2, 0, s / 2, s / 2, s / 2);
  grd.addColorStop(0, 'rgba(255,255,255,1)');
  grd.addColorStop(0.35, 'rgba(255,255,255,0.6)');
  grd.addColorStop(1, 'rgba(255,255,255,0)');
  g.fillStyle = grd;
  g.fillRect(0, 0, s, s);
  const t = new CanvasTexture(c);
  t.colorSpace = SRGBColorSpace;
  return t;
}

function puffTexture() {
  const s = 64;
  const c = document.createElement('canvas');
  c.width = c.height = s;
  const g = c.getContext('2d');
  const grd = g.createRadialGradient(s / 2, s / 2, 0, s / 2, s / 2, s / 2);
  grd.addColorStop(0, 'rgba(190,184,172,0.8)');
  grd.addColorStop(1, 'rgba(190,184,172,0)');
  g.fillStyle = grd;
  g.fillRect(0, 0, s, s);
  const t = new CanvasTexture(c);
  t.colorSpace = SRGBColorSpace;
  return t;
}

const _m = new Matrix4();
const _q = new Quaternion();
const _s = new Vector3();
const _p = new Vector3();
const Z = new Vector3(0, 0, 1);
const _X = new Vector3(1, 0, 0);
const _col = new Color();
const _dir = new Vector3();
const _e = new Euler(0, 0, 0, 'YXZ');
const _lq = new Quaternion();
const _pos = new Vector3();
const _vel = new Vector3();
const _axis = new Vector3();
const _vm = new Vector3();
const _tmp = new Vector3();
const _tmp2 = new Vector3();
const _eye = new Vector3();

export class ImpactEffects {
  /**
   * @param {import('three').Scene} scene
   * @param {object} [o]
   * @param {import('three').PerspectiveCamera} [o.camera]  world camera (first-person spawn: FOV match)
   * @param {Function|object} [o.world]   CollisionWorld or () => CollisionWorld (casing bounces)
   * @param {import('../engine/events.js').EventBus} [o.events]  publishes weapon:casing_landed
   * @param {Function} [o.lookupCombatant] (id) -> combatant (velocity added to its casings)
   */
  constructor(scene, { maxDecals = 200, maxSparks = 384, maxPuffs = 16, rng = Math.random, camera = null, world = null, events = null, lookupCombatant = null, weapons = weaponsData } = {}) {
    this.scene = scene;
    this.rng = rng;
    this.camera = camera;
    this.world = world;
    this.events = events;
    this.lookupCombatant = lookupCombatant;
    this.weapons = weapons;
    this._feel = {};
    // decals
    const decalMat = new MeshStandardMaterial({
      map: holeTexture(),
      transparent: true,
      depthWrite: false,
      polygonOffset: true,
      polygonOffsetFactor: -4,
      polygonOffsetUnits: -4,
      roughness: 0.95,
      metalness: 0,
    });
    this.decals = new InstancedMesh(new PlaneGeometry(1, 1), decalMat, maxDecals);
    this.decals.count = 0;
    this.decals.frustumCulled = false;
    this.decals.receiveShadow = true;
    this.decals.instanceMatrix.setUsage(DynamicDrawUsage);
    this.decals.name = 'impact_decals';
    for (let i = 0; i < maxDecals; i++) this.decals.setColorAt(i, new Color('#ffffff'));
    scene.add(this.decals);
    this.decalCursor = 0;
    this.decalCount = 0;

    // sparks
    this.maxSparks = maxSparks;
    const pos = new Float32Array(maxSparks * 3);
    for (let i = 0; i < maxSparks; i++) pos[i * 3 + 1] = -1000;
    const col = new Float32Array(maxSparks * 3);
    const g = new BufferGeometry();
    g.setAttribute('position', new BufferAttribute(pos, 3).setUsage(DynamicDrawUsage));
    g.setAttribute('color', new BufferAttribute(col, 3).setUsage(DynamicDrawUsage));
    this.sparkVel = new Float32Array(maxSparks * 3);
    this.sparkLife = new Float32Array(maxSparks);
    this.sparkCursor = 0;
    this.sparks = new Points(
      g,
      new PointsMaterial({
        size: 0.022,
        map: sparkTexture(),
        vertexColors: true,
        blending: AdditiveBlending,
        depthWrite: false,
        transparent: true,
        toneMapped: false,
      }),
    );
    this.sparks.frustumCulled = false;
    this.sparks.name = 'impact_sparks';
    scene.add(this.sparks);

    // dust puffs
    const puffMat = new SpriteMaterial({ map: puffTexture(), transparent: true, depthWrite: false, blending: NormalBlending });
    this.puffs = [];
    for (let i = 0; i < maxPuffs; i++) {
      const sp = new Sprite(puffMat.clone());
      sp.visible = false;
      sp.userData = { life: 0, vel: new Vector3() };
      scene.add(sp);
      this.puffs.push(sp);
    }
    this.puffCursor = 0;

    // muzzle light in the world (lights nearby walls when firing)
    this.muzzleLight = new PointLight(new Color('#ffb060'), 0, 7, 2);
    this.muzzleLight.castShadow = false;
    scene.add(this.muzzleLight);
    this.muzzleLightTimer = 0;
    this.muzzleLightPower = 5;
    this.impacts = 0;
    this.surfaceCounts = {};

    // smoke puffs + spent casings (pooled, capped)
    this.muzzle = new MuzzleEffects(scene, {
      raycast: (o, d, far) => {
        const w = typeof this.world === 'function' ? this.world() : this.world;
        return w ? w.raycast(o, d, far) : null;
      },
      onCasingLanded: (e) => {
        if (this.events) this.events.emit('weapon:casing_landed', { ...e, surface: impactSurface({ kind: 'world', mat: e.mat }) });
      },
    });
  }

  feelOf(weaponId) {
    if (!this._feel[weaponId]) {
      const def = (this.weapons && this.weapons[weaponId]) || null;
      this._feel[weaponId] = { def, feel: resolveFeel((def && def.feel) || {}) };
    }
    return this._feel[weaponId];
  }

  /**
   * A round was fired.
   * @param {Vector3} muzzleWorld  gameplay muzzle (world)
   * @param {object} [shot]        weapon:fired payload ({ weaponId, shooterId, dir, ads, shot: { eye } })
   * @param {import('./viewModel.js').ViewModel} [viewModel] the player's view model: first-person shot
   *        (world muzzle light; smoke and casing spawn at the DRAWN muzzle / eject port, FOV matched)
   */
  onShot(muzzleWorld, shot = null, viewModel = null) {
    const firstPerson = !!viewModel || !shot;
    const info = shot && shot.weaponId ? this.feelOf(shot.weaponId) : null;
    if (firstPerson) {
      const a = adsBlend((shot && shot.ads) || 0);
      this.muzzleLight.position.copy(muzzleWorld);
      this.muzzleLightTimer = info ? info.feel.flash.worldLightTime : 0.04;
      this.muzzleLightPower = (info ? info.feel.flash.worldLight : 5) * (1 + (FLASH_ADS.worldLight - 1) * a);
    }
    if (!shot || !info || !info.def || !shot.dir) return;
    const f = info.feel;
    const dir = _dir.copy(shot.dir).normalize();
    _e.set(Math.asin(Math.max(-1, Math.min(1, dir.y))), Math.atan2(-dir.x, -dir.z), 0, 'YXZ');
    const q = _lq.setFromEuler(_e);
    const cam = this.camera;
    const camPos = cam ? cam.position : null;
    const dist = camPos ? camPos.distanceTo(muzzleWorld) : 0;
    const vm = viewModel;
    const ads = shot.ads || 0;
    const vmDef = info.def.viewModel;
    // --- smoke puff at the drawn muzzle ---
    if (firstPerson || dist <= f.smoke.maxDistance) {
      const pos = _pos.copy(muzzleWorld);
      if (vm && shot.shot && shot.shot.eye) {
        const m = vm.renderedMuzzleInCameraSpace ? vm.renderedMuzzleInCameraSpace(_tmp) : null;
        if (m && vm.updated) this._fpToWorld(m, shot.shot.eye, q, vm, pos);
      }
      this.muzzle.puff(pos, dir, f.smoke, firstPerson ? 1 + (FLASH_ADS.smoke - 1) * adsBlend(ads) : 1);
    }
    // --- spent casing from the eject port ---
    if (!(firstPerson || dist <= f.casing.maxDistance)) return;
    const c = f.casing;
    const ejectLocal = vm && vm.ejectLocal ? vm.ejectLocal : new Vector3().fromArray(c.ejectLocal || [0.1, vmDef.muzzleLocal[1], 0.015]);
    const vModel = _vm.fromArray(c.velocity);
    vModel.x += (this.rng() - 0.5) * 2 * c.spread;
    vModel.y += (this.rng() - 0.5) * 2 * c.spread;
    vModel.z += (this.rng() - 0.5) * 2 * c.spread;
    const pos = _pos;
    const vel = _vel;
    const axis = _axis;
    let pCam = null;
    if (vm && shot.shot && shot.shot.eye) pCam = vm.ejectInCameraSpace(_tmp);
    if (pCam) {
      this._fpToWorld(pCam, shot.shot.eye, q, vm, pos);
      vm.modelDirInCameraSpace(vModel, vel).applyQuaternion(q);
      vm.modelDirInCameraSpace(_X, axis).applyQuaternion(q);
    } else {
      // static pose relative to the gameplay muzzle (bots, or before the first rendered frame)
      const e = viewModelPointInCamera(vmDef, ejectLocal, ads, _tmp);
      const m = viewModelPointInCamera(vmDef, vmDef.muzzleLocal, ads, _tmp2);
      pos.copy(e.sub(m)).applyQuaternion(q).add(muzzleWorld);
      vel.set(vModel.z, vModel.y, -vModel.x).applyQuaternion(q);
      axis.copy(dir);
    }
    const who = this.lookupCombatant && shot.shooterId ? this.lookupCombatant(shot.shooterId) : null;
    if (who && who.controller && who.controller.velocity) vel.add(who.controller.velocity);
    this.muzzle.ejectCasing(pos, vel, axis, c, { weaponId: shot.weaponId, shooterId: shot.shooterId });
  }

  /**
   * View-model camera-space point -> world point that appears at the same screen position through the
   * world camera (the view model uses its own fixed FOV), at the same distance from the eye.
   */
  _fpToWorld(pCam, eyeArr, q, vm, out) {
    const cam = this.camera;
    const s = cam && vm && vm.camera ? Math.tan((cam.fov * Math.PI) / 360) / Math.tan((vm.camera.fov * Math.PI) / 360) : 1;
    out.set(pCam.x * s, pCam.y * s, pCam.z).applyQuaternion(q);
    return out.add(_eye.fromArray(eyeArr));
  }

  /** hit: {point, normal, kind} */
  onHit(hit) {
    this.impacts++;
    const n = hit.normal;
    const surf = impactSurface(hit);
    const S = IMPACT_SURFACES[surf] || IMPACT_SURFACES.concrete;
    this.surfaceCounts[surf] = (this.surfaceCounts[surf] || 0) + 1;
    this.lastSurface = surf;
    if (hit.kind === 'world' && S.decal > 0) {
      const size = S.decal * (0.85 + this.rng() * 0.3);
      _q.setFromUnitVectors(Z, n);
      const spin = new Quaternion().setFromAxisAngle(Z, this.rng() * Math.PI * 2);
      _q.multiply(spin);
      _p.copy(hit.point).addScaledVector(n, 0.002);
      _s.set(size, size, size);
      _m.compose(_p, _q, _s);
      this.decals.setMatrixAt(this.decalCursor, _m);
      this.decals.setColorAt(this.decalCursor, _col.set(S.decalColor));
      if (this.decals.instanceColor) this.decals.instanceColor.needsUpdate = true;
      this.decalCursor = (this.decalCursor + 1) % this.decals.instanceMatrix.count;
      this.decalCount = Math.min(this.decalCount + 1, this.decals.instanceMatrix.count);
      this.decals.count = this.decalCount;
      this.decals.instanceMatrix.needsUpdate = true;
    }
    const nSparks = S.sparks;
    const pos = this.sparks.geometry.getAttribute('position');
    const col = this.sparks.geometry.getAttribute('color');
    for (let i = 0; i < nSparks; i++) {
      const k = this.sparkCursor;
      this.sparkCursor = (this.sparkCursor + 1) % this.maxSparks;
      pos.setXYZ(k, hit.point.x + n.x * 0.01, hit.point.y + n.y * 0.01, hit.point.z + n.z * 0.01);
      const speed = 2 + this.rng() * 4;
      const rx = (this.rng() - 0.5) * 1.6;
      const ry = (this.rng() - 0.5) * 1.6 + 0.4;
      const rz = (this.rng() - 0.5) * 1.6;
      this.sparkVel[k * 3] = (n.x + rx) * speed;
      this.sparkVel[k * 3 + 1] = (n.y + ry) * speed;
      this.sparkVel[k * 3 + 2] = (n.z + rz) * speed;
      this.sparkLife[k] = 0.08 + this.rng() * 0.14;
      col.setXYZ(k, S.sparkColor[0], S.sparkColor[1], S.sparkColor[2]);
    }
    pos.needsUpdate = true;
    col.needsUpdate = true;
    // puff
    const sp = this.puffs[this.puffCursor];
    this.puffCursor = (this.puffCursor + 1) % this.puffs.length;
    sp.visible = true;
    const D = S.dust;
    sp.position.copy(hit.point).addScaledVector(n, 0.04);
    sp.userData.life = D.life;
    sp.userData.maxLife = D.life;
    sp.userData.opacity = D.opacity;
    sp.userData.grow = D.grow;
    sp.userData.vel.copy(n).multiplyScalar(D.speed);
    sp.material.color.set(D.color);
    sp.scale.setScalar(D.size);
    sp.material.opacity = D.opacity;
  }

  /** Removes all decals, sparks and puffs (new round / new session). */
  clear() {
    this.decalCursor = 0;
    this.decalCount = 0;
    this.decals.count = 0;
    this.decals.instanceMatrix.needsUpdate = true;
    const pos = this.sparks.geometry.getAttribute('position');
    const col = this.sparks.geometry.getAttribute('color');
    for (let k = 0; k < this.maxSparks; k++) {
      this.sparkLife[k] = 0;
      pos.setXYZ(k, 0, -1000, 0);
      col.setXYZ(k, 0, 0, 0);
    }
    pos.needsUpdate = true;
    col.needsUpdate = true;
    for (const sp of this.puffs) sp.visible = false;
    this.muzzleLightTimer = 0;
    this.muzzleLight.intensity = 0;
    this.muzzle.clear();
  }

  /** Advances effect lifetimes on the fixed simulation tick (deterministic, pauses with the game). */
  tick(dt) {
    const pos = this.sparks.geometry.getAttribute('position');
    const col = this.sparks.geometry.getAttribute('color');
    let any = false;
    for (let k = 0; k < this.maxSparks; k++) {
      if (this.sparkLife[k] <= 0) continue;
      any = true;
      this.sparkLife[k] -= dt;
      this.sparkVel[k * 3 + 1] -= 9.81 * dt;
      pos.setXYZ(
        k,
        pos.getX(k) + this.sparkVel[k * 3] * dt,
        pos.getY(k) + this.sparkVel[k * 3 + 1] * dt,
        pos.getZ(k) + this.sparkVel[k * 3 + 2] * dt,
      );
      if (this.sparkLife[k] <= 0) {
        col.setXYZ(k, 0, 0, 0);
        pos.setXYZ(k, 0, -1000, 0);
      }
    }
    if (any) {
      pos.needsUpdate = true;
      col.needsUpdate = true;
    }
    for (const sp of this.puffs) {
      if (!sp.visible) continue;
      sp.userData.life -= dt;
      if (sp.userData.life <= 0) {
        sp.visible = false;
        continue;
      }
      sp.position.addScaledVector(sp.userData.vel, dt);
      sp.scale.multiplyScalar(1 + dt * (sp.userData.grow ?? 2.2));
      sp.material.opacity = Math.max(0, sp.userData.life / (sp.userData.maxLife || 0.6)) * (sp.userData.opacity ?? 0.8);
    }
    this.muzzleLightTimer -= dt;
    this.muzzleLight.intensity = this.muzzleLightTimer > 0 ? this.muzzleLightPower : 0;
    this.muzzle.tick(dt);
  }

  getState() {
    return { impacts: this.impacts, decals: this.decalCount, surfaces: { ...this.surfaceCounts }, lastSurface: this.lastSurface || null, muzzleLight: this.muzzleLight.intensity, ...this.muzzle.getState() };
  }
}
