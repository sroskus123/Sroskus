// Bullet impact effects: pooled decals (one instanced draw call), spark particles and small
// dust puffs, plus a world-space muzzle light. Visual only; driven by weapon events.

import {
  AdditiveBlending,
  BufferAttribute,
  BufferGeometry,
  CanvasTexture,
  Color,
  DynamicDrawUsage,
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

export class ImpactEffects {
  constructor(scene, { maxDecals = 200, maxSparks = 384, maxPuffs = 16, rng = Math.random } = {}) {
    this.scene = scene;
    this.rng = rng;
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
    this.impacts = 0;
  }

  onShot(muzzleWorld) {
    this.muzzleLight.position.copy(muzzleWorld);
    this.muzzleLightTimer = 0.06;
  }

  /** hit: {point, normal, kind} */
  onHit(hit) {
    this.impacts++;
    const n = hit.normal;
    if (hit.kind === 'world') {
      const size = 0.07 + this.rng() * 0.03;
      _q.setFromUnitVectors(Z, n);
      const spin = new Quaternion().setFromAxisAngle(Z, this.rng() * Math.PI * 2);
      _q.multiply(spin);
      _p.copy(hit.point).addScaledVector(n, 0.002);
      _s.set(size, size, size);
      _m.compose(_p, _q, _s);
      this.decals.setMatrixAt(this.decalCursor, _m);
      this.decalCursor = (this.decalCursor + 1) % this.decals.instanceMatrix.count;
      this.decalCount = Math.min(this.decalCount + 1, this.decals.instanceMatrix.count);
      this.decals.count = this.decalCount;
      this.decals.instanceMatrix.needsUpdate = true;
    }
    const nSparks = hit.kind === 'world' ? 10 : 5;
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
      this.sparkLife[k] = 0.12 + this.rng() * 0.18;
      if (hit.kind === 'world') col.setXYZ(k, 1.6, 0.78, 0.28);
      else col.setXYZ(k, 0.9, 0.55, 0.35);
    }
    pos.needsUpdate = true;
    col.needsUpdate = true;
    // puff
    const sp = this.puffs[this.puffCursor];
    this.puffCursor = (this.puffCursor + 1) % this.puffs.length;
    sp.visible = true;
    sp.position.copy(hit.point).addScaledVector(n, 0.05);
    sp.userData.life = 0.6;
    sp.userData.vel.copy(n).multiplyScalar(0.4);
    sp.scale.setScalar(0.12);
    sp.material.opacity = 0.8;
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
      sp.scale.multiplyScalar(1 + dt * 2.2);
      sp.material.opacity = Math.max(0, sp.userData.life / 0.6) * 0.8;
    }
    this.muzzleLightTimer -= dt;
    this.muzzleLight.intensity = this.muzzleLightTimer > 0 ? 6 : 0;
  }
}
