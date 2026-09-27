// Muzzle effects: flash timing (first-person sprite + light), smoke puffs and spent casings.
//
// Everything advances on the fixed simulation tick (pauses with the game, identical at every frame rate):
//   - FlashTimer: the flash lives a fixed simulated time (feel.muzzle.flash.duration, ~2 ticks), is
//     sampled per rendered frame with the interpolation alpha and is guaranteed to be drawn in at least
//     one frame even at very low FPS - so ~2 frames at 60 FPS, ~4-5 at 144 FPS, 1 at 30 FPS, and the same
//     visible time everywhere.
//   - CasingPool: pooled, capped casings with gravity, air drag, bounce / friction against the static
//     world (raycast per tick), tumble; they lie still after landing, then shrink away (restTime +
//     fadeTime). The oldest casing is recycled when the pool is full.
//   - MuzzleEffects: renders casings (one InstancedMesh) and smoke puffs (pooled sprites) in the world
//     scene. Visual only; no gameplay reads any of this.
// Pure logic (FlashTimer, CasingPool) needs no DOM; MuzzleEffects builds canvas textures only when a
// document exists, so the whole module can be exercised in Node tests.

import {
  Color,
  CylinderGeometry,
  DynamicDrawUsage,
  InstancedMesh,
  Matrix4,
  MeshStandardMaterial,
  NormalBlending,
  Quaternion,
  Sprite,
  SpriteMaterial,
  CanvasTexture,
  SRGBColorSpace,
  Vector3,
} from 'three';
import { createRng } from '../util/rng.js';

export const FLASH_DEFAULTS = { duration: 0.03, size: [0.085, 0.125], adsScale: 0.6, light: 1.6, worldLight: 5, worldLightTime: 0.04, minVisible: 0.55 };
export const SMOKE_DEFAULTS = { opacity: 0.14, life: 0.9, size: [0.05, 0.32], speed: 1.3, drag: 3.5, rise: 0.28, forward: 0.05, color: '#c9c6bf', maxDistance: 45 };
export const CASING_DEFAULTS = {
  length: 0.045,
  radius: 0.0048,
  color: '#b98d3e',
  ejectLocal: null,
  velocity: [0.6, 1.0, 2.8], // model space of the weapon: +X forward (muzzle), +Y up, +Z right
  spread: 0.25,
  spin: 28,
  drag: 0.3,
  restitution: 0.3,
  friction: 0.55,
  restTime: 0.7,
  fadeTime: 0.35,
  maxLife: 4,
  maxDistance: 20,
};

export function resolveFeel(feel = {}) {
  const m = feel.muzzle || {};
  return {
    flash: { ...FLASH_DEFAULTS, ...(m.flash || {}) },
    smoke: { ...SMOKE_DEFAULTS, ...(m.smoke || {}) },
    casing: { ...CASING_DEFAULTS, ...(feel.casing || {}) },
  };
}

// ------------------------------------------------------------------ flash timing

export class FlashTimer {
  constructor(duration = FLASH_DEFAULTS.duration, minVisible = FLASH_DEFAULTS.minVisible) {
    this.duration = duration;
    this.minVisible = minVisible;
    this.reset();
  }

  reset() {
    this.age = Infinity; // simulated seconds since the shot (0 in the shot's tick, before it advances)
    this.pending = false; // not drawn yet
    this.seq = 0;
    this.framesShown = 0;
  }

  /** A shot was fired in the current simulation tick (before this tick's tick() call). */
  trigger() {
    this.age = 0;
    this.pending = true;
    this.seq++;
    this.framesShown = 0;
  }

  /** One fixed simulation tick. */
  tick(dt) {
    if (Number.isFinite(this.age)) {
      this.age += dt;
      if (this.age > 1) this.age = Infinity;
    }
  }

  /** Simulated age of the flash at a rendered frame (the render lags the last tick by (1 - alpha) ticks). */
  renderAge(alpha, dt) {
    if (!Number.isFinite(this.age)) return Infinity;
    const a = Math.min(Math.max(alpha, 0), 1);
    return Math.max(0, this.age - (1 - a) * dt);
  }

  /**
   * Intensity 0..1 for a rendered frame; marks the flash as drawn. A flash that was never drawn is shown
   * once with at least `minVisible`, so every shot flashes on screen whatever the frame pacing.
   */
  sample(alpha, dt) {
    const age = this.renderAge(alpha, dt);
    let I = age < this.duration ? 1 - 0.6 * (age / this.duration) ** 2 : 0;
    if (this.pending) {
      I = Math.max(I, this.minVisible);
      this.pending = false;
    }
    if (I > 0) this.framesShown++;
    return I;
  }
}

// ------------------------------------------------------------------ casings (pure logic)

const _X = new Vector3(1, 0, 0);
const _mv = new Vector3();
const _n = new Vector3();
const _vt = new Vector3();
const _ax = new Vector3();
const _dq = new Quaternion();

export class CasingPool {
  constructor(max = 40) {
    this.max = max;
    this.items = [];
    for (let i = 0; i < max; i++) {
      this.items.push({ active: false, p: new Vector3(), v: new Vector3(), q: new Quaternion(), w: new Vector3(), age: 0, rest: 0, resting: false, bounces: 0, scale: 1, landed: false, def: CASING_DEFAULTS, meta: null, id: 0 });
    }
    this.cursor = 0;
    this.spawned = 0;
    this.recycled = 0;
    this.landedCount = 0;
    this.expired = 0;
  }

  /** Activates a casing (recycles the oldest when the pool is full). Returns it. */
  spawn(pos, vel, axis, angVel, def = CASING_DEFAULTS, meta = null) {
    let c = null;
    for (let i = 0; i < this.max && !c; i++) {
      const k = (this.cursor + i) % this.max;
      if (!this.items[k].active) {
        c = this.items[k];
        this.cursor = (k + 1) % this.max;
      }
    }
    if (!c) {
      // pool full: recycle the oldest (largest age / resting longest)
      let best = 0;
      let bestAge = -1;
      for (let i = 0; i < this.max; i++) {
        const it = this.items[i];
        const a = it.age + it.rest;
        if (a > bestAge) {
          bestAge = a;
          best = i;
        }
      }
      c = this.items[best];
      this.recycled++;
    }
    c.active = true;
    c.p.copy(pos);
    c.v.copy(vel);
    c.q.setFromUnitVectors(_X, _ax.copy(axis).normalize());
    c.w.copy(angVel);
    c.age = 0;
    c.rest = 0;
    c.resting = false;
    c.bounces = 0;
    c.scale = 1;
    c.landed = false;
    c.def = def;
    c.meta = meta;
    c.id = ++this.spawned;
    return c;
  }

  activeCount() {
    let n = 0;
    for (const c of this.items) if (c.active) n++;
    return n;
  }

  clear() {
    for (const c of this.items) c.active = false;
  }

  /**
   * One fixed tick.
   * @param {number} dt
   * @param {(origin:Vector3, dir:Vector3, far:number)=>({point:Vector3, normal:Vector3, mat?:string}|null)} raycast
   * @param {(casing:object, hit:object)=>void} [onLand] first ground contact of each casing
   */
  step(dt, raycast, onLand = null) {
    for (const c of this.items) {
      if (!c.active) continue;
      const d = c.def;
      if (c.resting) {
        c.rest += dt;
        if (c.rest > d.restTime) {
          c.scale = 1 - (c.rest - d.restTime) / Math.max(1e-3, d.fadeTime);
          if (c.scale <= 0) {
            c.active = false;
            this.expired++;
          }
        }
        continue;
      }
      c.age += dt;
      if (c.age > d.maxLife) {
        c.active = false;
        this.expired++;
        continue;
      }
      c.v.y -= 9.81 * dt;
      c.v.multiplyScalar(Math.exp(-d.drag * dt));
      _mv.copy(c.v).multiplyScalar(dt);
      const dist = _mv.length();
      const hit = dist > 1e-6 && raycast ? raycast(c.p, _mv.clone().divideScalar(dist), dist + d.radius) : null;
      if (hit) {
        _n.copy(hit.normal);
        if (_n.dot(c.v) > 0) _n.negate();
        c.p.copy(hit.point).addScaledVector(_n, d.radius * 1.05);
        const vn = c.v.dot(_n);
        _vt.copy(c.v).addScaledVector(_n, -vn).multiplyScalar(d.friction);
        c.v.copy(_vt).addScaledVector(_n, -vn * d.restitution);
        c.w.multiplyScalar(0.45);
        c.bounces++;
        if (!c.landed) {
          c.landed = true;
          this.landedCount++;
          if (onLand) onLand(c, hit);
        }
        if ((c.v.length() < 0.45 && _n.y > 0.5) || c.bounces >= 5) {
          c.resting = true;
          c.v.set(0, 0, 0);
          c.w.set(0, 0, 0);
          // lie flat: case axis in the ground plane, keeping its heading
          _ax.copy(_X).applyQuaternion(c.q);
          _ax.addScaledVector(_n, -_ax.dot(_n));
          if (_ax.lengthSq() < 1e-6) _ax.set(1, 0, 0).addScaledVector(_n, -_n.x);
          c.q.setFromUnitVectors(_X, _ax.normalize());
          c.p.copy(hit.point).addScaledVector(_n, d.radius);
        }
      } else {
        c.p.add(_mv);
      }
      const wl = c.w.length();
      if (wl > 1e-6) {
        _dq.setFromAxisAngle(_ax.copy(c.w).divideScalar(wl), wl * dt);
        c.q.premultiply(_dq);
      }
    }
  }
}

// ------------------------------------------------------------------ rendering

function smokeTexture() {
  if (typeof document === 'undefined') return null;
  const s = 64;
  const c = document.createElement('canvas');
  c.width = c.height = s;
  const g = c.getContext('2d');
  const grd = g.createRadialGradient(s / 2, s / 2, 0, s / 2, s / 2, s / 2);
  grd.addColorStop(0, 'rgba(255,255,255,0.75)');
  grd.addColorStop(0.5, 'rgba(255,255,255,0.35)');
  grd.addColorStop(1, 'rgba(255,255,255,0)');
  g.fillStyle = grd;
  g.fillRect(0, 0, s, s);
  // a few soft lumps so the puff is not a perfect disc
  const r = createRng(7);
  g.globalCompositeOperation = 'destination-out';
  for (let i = 0; i < 9; i++) {
    const x = s / 2 + (r.next() - 0.5) * s * 0.7;
    const y = s / 2 + (r.next() - 0.5) * s * 0.7;
    const gg = g.createRadialGradient(x, y, 0, x, y, s * 0.16);
    gg.addColorStop(0, 'rgba(0,0,0,0.35)');
    gg.addColorStop(1, 'rgba(0,0,0,0)');
    g.fillStyle = gg;
    g.fillRect(0, 0, s, s);
  }
  const t = new CanvasTexture(c);
  t.colorSpace = SRGBColorSpace;
  return t;
}

const _m = new Matrix4();
const _s = new Vector3();
const _p = new Vector3();
const _zero = new Matrix4().makeScale(0, 0, 0);

export class MuzzleEffects {
  /**
   * @param {import('three').Scene} scene  world scene
   * @param {object} [o]
   * @param {number} [o.maxCasings]
   * @param {number} [o.maxSmoke]
   * @param {Function} [o.raycast]  (origin, dir, far) -> static world hit or null
   * @param {Function} [o.onCasingLanded] (payload) -> void
   */
  constructor(scene, { maxCasings = 40, maxSmoke = 24, raycast = null, onCasingLanded = null, seed = 11 } = {}) {
    this.scene = scene;
    this.raycast = raycast;
    this.onCasingLanded = onCasingLanded;
    this.rng = createRng(seed);
    this.pool = new CasingPool(maxCasings);
    // casings: one instanced draw call; unit cylinder along +X scaled per instance (length, radius)
    const geo = new CylinderGeometry(1, 1, 1, 8, 1, false);
    geo.rotateZ(Math.PI / 2);
    this.casingMat = new MeshStandardMaterial({ color: new Color('#ffffff'), metalness: 0.85, roughness: 0.32 });
    this.casings = new InstancedMesh(geo, this.casingMat, maxCasings);
    this.casings.name = 'spent_casings';
    this.casings.instanceMatrix.setUsage(DynamicDrawUsage);
    this.casings.frustumCulled = false;
    this.casings.castShadow = false;
    this.casings.receiveShadow = false;
    for (let i = 0; i < maxCasings; i++) {
      this.casings.setMatrixAt(i, _zero);
      this.casings.setColorAt(i, new Color(CASING_DEFAULTS.color));
    }
    this.casings.count = maxCasings;
    if (scene) scene.add(this.casings);
    // smoke puffs
    const tex = smokeTexture();
    this.smoke = [];
    for (let i = 0; i < maxSmoke; i++) {
      const sp = new Sprite(new SpriteMaterial({ map: tex, color: new Color(SMOKE_DEFAULTS.color), transparent: true, depthWrite: false, blending: NormalBlending, opacity: 0 }));
      sp.name = 'muzzle_smoke';
      sp.visible = false;
      sp.userData = { life: 0, maxLife: 1, vel: new Vector3(), def: SMOKE_DEFAULTS, rot: 0, spin: 0 };
      if (scene) scene.add(sp);
      this.smoke.push(sp);
    }
    this.smokeCursor = 0;
    this.smokeSpawned = 0;
  }

  /**
   * Ejects one casing.
   * @param {Vector3} pos      world position of the ejection port
   * @param {Vector3} vel      world velocity
   * @param {Vector3} axis     world direction of the case axis at ejection (≈ barrel direction)
   * @param {object} def      resolved casing definition
   * @param {object} [meta]   { weaponId, shooterId }
   */
  ejectCasing(pos, vel, axis, def, meta = null) {
    const d = def || CASING_DEFAULTS;
    // tumble mostly about the vertical axis (flat spin) plus a random wobble
    const spin = d.spin * (0.75 + 0.5 * this.rng.next()) * (this.rng.next() < 0.5 ? -1 : 1);
    const w = new Vector3(this.rng.signed() * 0.35, 1, this.rng.signed() * 0.35).normalize().multiplyScalar(spin);
    const c = this.pool.spawn(pos, vel, axis, w, d, meta);
    this.casings.setColorAt(this.pool.items.indexOf(c), _tmpColor.set(d.color));
    if (this.casings.instanceColor) this.casings.instanceColor.needsUpdate = true;
    return c;
  }

  /** Spawns one smoke puff at `pos` drifting along `dir`. */
  puff(pos, dir, def = SMOKE_DEFAULTS, scale = 1) {
    const sp = this.smoke[this.smokeCursor];
    this.smokeCursor = (this.smokeCursor + 1) % this.smoke.length;
    const u = sp.userData;
    u.def = def;
    u.maxLife = def.life * (0.85 + 0.3 * this.rng.next());
    u.life = u.maxLife;
    u.scale = scale;
    u.vel.copy(dir).multiplyScalar(def.speed * (0.8 + 0.4 * this.rng.next()));
    u.vel.x += this.rng.signed() * 0.08;
    u.vel.z += this.rng.signed() * 0.08;
    u.rot = this.rng.next() * Math.PI * 2;
    u.spin = this.rng.signed() * 0.6;
    sp.position.copy(pos).addScaledVector(dir, def.forward);
    sp.material.color.set(def.color);
    sp.material.rotation = u.rot;
    sp.visible = true;
    this._styleSmoke(sp);
    this.smokeSpawned++;
    return sp;
  }

  _styleSmoke(sp) {
    const u = sp.userData;
    const t = 1 - u.life / u.maxLife; // 0 -> 1
    const d = u.def;
    const size = (d.size[0] + (d.size[1] - d.size[0]) * Math.sqrt(t)) * (u.scale || 1);
    sp.scale.set(size, size, size);
    const fadeIn = Math.min(1, t / 0.08);
    sp.material.opacity = d.opacity * fadeIn * (1 - t) * (1 - t);
  }

  activeSmoke() {
    let n = 0;
    for (const sp of this.smoke) if (sp.visible) n++;
    return n;
  }

  clear() {
    this.pool.clear();
    for (let i = 0; i < this.pool.max; i++) this.casings.setMatrixAt(i, _zero);
    this.casings.instanceMatrix.needsUpdate = true;
    for (const sp of this.smoke) {
      sp.visible = false;
      sp.userData.life = 0;
    }
  }

  /** One fixed simulation tick. */
  tick(dt) {
    const onLand = (c, hit) => {
      if (this.onCasingLanded) this.onCasingLanded({ position: c.p.clone(), mat: hit.mat || null, speed: c.v.length(), weaponId: c.meta ? c.meta.weaponId : null, shooterId: c.meta ? c.meta.shooterId : null });
    };
    this.pool.step(dt, this.raycast, onLand);
    const items = this.pool.items;
    for (let i = 0; i < items.length; i++) {
      const c = items[i];
      if (!c.active) {
        this.casings.setMatrixAt(i, _zero);
        continue;
      }
      const d = c.def;
      const k = Math.max(0, c.scale);
      _s.set(d.length * k, d.radius * k, d.radius * k);
      _m.compose(c.p, c.q, _s);
      this.casings.setMatrixAt(i, _m);
    }
    this.casings.instanceMatrix.needsUpdate = true;
    for (const sp of this.smoke) {
      if (!sp.visible) continue;
      const u = sp.userData;
      u.life -= dt;
      if (u.life <= 0) {
        sp.visible = false;
        continue;
      }
      u.vel.multiplyScalar(Math.exp(-u.def.drag * dt));
      _p.copy(u.vel).multiplyScalar(dt);
      _p.y += u.def.rise * dt;
      sp.position.add(_p);
      u.rot += u.spin * dt;
      sp.material.rotation = u.rot;
      this._styleSmoke(sp);
    }
  }

  getState() {
    return {
      casingsActive: this.pool.activeCount(),
      casingsSpawned: this.pool.spawned,
      casingsLanded: this.pool.landedCount,
      casingsRecycled: this.pool.recycled,
      casingsExpired: this.pool.expired,
      casingCap: this.pool.max,
      smokeActive: this.activeSmoke(),
      smokeSpawned: this.smokeSpawned,
      smokeCap: this.smoke.length,
    };
  }
}

const _tmpColor = new Color();
