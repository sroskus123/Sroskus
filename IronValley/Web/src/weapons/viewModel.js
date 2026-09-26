// First-person view model: rendered in its own pass (depth cleared) with a fixed vertical
// FOV so it never clips into walls and keeps its proportions when the player changes FOV.
// Lighting uses the same sun direction and environment map as the world; the direct sun is
// dimmed when the eye is in shadow. Pose = hip/ADS blend + sway + bob + recoil + sprint.
// Recoil springs advance on the fixed simulation tick (ViewModelMotion.tick via tickSim) and
// are interpolated here, so the weapon motion is the same at every frame rate.

import {
  AdditiveBlending,
  CanvasTexture,
  Color,
  DirectionalLight,
  Group,
  HemisphereLight,
  PerspectiveCamera,
  PointLight,
  Scene,
  SRGBColorSpace,
  Sprite,
  SpriteMaterial,
  Vector3,
} from 'three';
import { createPlaceholderRifle } from './placeholderRifle.js';
import { adsBlend, viewModelPointInCamera, ViewModelMotion } from './viewModelMotion.js';

function makeFlashTexture() {
  const s = 128;
  const c = document.createElement('canvas');
  c.width = c.height = s;
  const g = c.getContext('2d');
  const grd = g.createRadialGradient(s / 2, s / 2, 0, s / 2, s / 2, s / 2);
  grd.addColorStop(0, 'rgba(255,248,225,1)');
  grd.addColorStop(0.18, 'rgba(255,214,140,0.95)');
  grd.addColorStop(0.45, 'rgba(255,150,50,0.45)');
  grd.addColorStop(1, 'rgba(255,110,20,0)');
  g.fillStyle = grd;
  g.fillRect(0, 0, s, s);
  // a few petals
  g.globalCompositeOperation = 'lighter';
  g.fillStyle = 'rgba(255,200,120,0.55)';
  for (let i = 0; i < 5; i++) {
    g.save();
    g.translate(s / 2, s / 2);
    g.rotate((i / 5) * Math.PI * 2);
    g.beginPath();
    g.moveTo(0, -4);
    g.lineTo(s * 0.48, 0);
    g.lineTo(0, 4);
    g.closePath();
    g.fill();
    g.restore();
  }
  const t = new CanvasTexture(c);
  t.colorSpace = SRGBColorSpace;
  return t;
}

export class ViewModel {
  /**
   * @param {object} o
   * @param {object} o.def            weapon definition
   * @param {import('three').Texture} o.envTexture
   * @param {number} o.envIntensity
   * @param {Vector3} o.sunDirection
   * @param {Color} o.sunColor
   * @param {number} o.sunIntensity
   */
  constructor({ def, envTexture, envIntensity = 1, sunDirection, sunColor, sunIntensity, createPlaceholder = createPlaceholderRifle }) {
    this.def = def;
    const vm = def.viewModel;
    this.scene = new Scene();
    this.scene.environment = envTexture;
    this.scene.environmentIntensity = envIntensity;
    // ambient (environment + hemisphere fill) is scaled by the sky visibility at the eye, so the
    // weapon darkens with the world in tunnels and rooms (see setAmbientScale)
    this.baseEnvIntensity = envIntensity;
    this.baseHemiIntensity = 0.35;
    this.ambientScale = 1;
    this.camera = new PerspectiveCamera(vm.fovVerticalDeg || 50, 16 / 9, 0.01, 10);
    this.scene.add(this.camera);

    this.sunIntensity = sunIntensity;
    this.sun = new DirectionalLight(sunColor, sunIntensity);
    this.sun.position.copy(sunDirection).multiplyScalar(5);
    this.scene.add(this.sun);
    this.scene.add(this.sun.target);
    this.hemi = new HemisphereLight(new Color('#c4d6ea'), new Color('#5d584e'), this.baseHemiIntensity);
    this.scene.add(this.hemi);

    this.holder = new Group(); // camera-space pose of the weapon grip
    this.camera.add(this.holder);
    this.modelRoot = new Group();
    this.modelRoot.rotation.y = Math.PI / 2; // model +X (muzzle) -> camera -Z (forward)
    this.holder.add(this.modelRoot);

    this.flashLight = new PointLight(new Color('#ffb56b'), 0, 1.2, 2);
    this.scene.add(this.flashLight);
    this.flash = new Sprite(
      new SpriteMaterial({ map: makeFlashTexture(), blending: AdditiveBlending, depthWrite: false, transparent: true, toneMapped: false }),
    );
    this.flash.scale.setScalar(0.1);
    this.flash.visible = false;

    this.hip = new Vector3().fromArray(vm.hipPosition);
    this.adsPos = new Vector3().fromArray(vm.adsPosition);
    this.muzzleNode = null;
    this.isPlaceholder = true;
    this.assetName = 'placeholder';
    this.muzzleLocal = new Vector3().fromArray(vm.muzzleLocal);
    this.adsEyeLocal = new Vector3().fromArray(vm.adsEyeLocal || [0, 0, 0]);
    const ph = createPlaceholder();
    this.setModel(ph.object, ph.muzzle, { placeholder: true, name: 'placeholder', adsEye: ph.adsEye });
    this.hiddenPatterns = [];

    // animation state (springs on the simulation tick, sway / sprint per frame)
    this.motion = new ViewModelMotion(vm.motion || {});
    this.hipRotation = vm.hipRotation || [0, 0, 0];
    this.kick = 0; // last rendered (interpolated) values, for inspection
    this.kickRot = 0;
    this.flashTimer = 0;
    this.sunVisibility = 1;
    this._tmpV = new Vector3();
  }

  setModel(object, muzzleNode, { placeholder = false, name = 'model', adsEye = null } = {}) {
    while (this.modelRoot.children.length) this.modelRoot.remove(this.modelRoot.children[0]);
    this.modelRoot.add(object);
    this.muzzleNode = muzzleNode;
    this.adsEyeNode = adsEye;
    this.isPlaceholder = placeholder;
    this.assetName = name;
    // socket positions in model space (sockets may be nested under rotated bones)
    this.camera.updateMatrixWorld(true);
    const tmp = new Vector3();
    if (muzzleNode) this.muzzleLocal.copy(this.modelRoot.worldToLocal(muzzleNode.getWorldPosition(tmp)));
    if (adsEye) this.adsEyeLocal.copy(this.modelRoot.worldToLocal(adsEye.getWorldPosition(tmp)));
    if (this.flash.parent) this.flash.parent.remove(this.flash);
    this.modelRoot.add(this.flash);
    this.flash.position.copy(this.muzzleLocal).add(new Vector3(0.03, 0, 0));
    if (this.hiddenPatterns && this.hiddenPatterns.length) this.setHiddenNodes(this.hiddenPatterns.map((re) => re.source));
  }

  /**
   * Hides model nodes whose name matches one of the patterns (case-insensitive regular expressions),
   * e.g. the optic for the iron-sights loadout. Everything else is shown.
   */
  setHiddenNodes(patterns = []) {
    this.hiddenPatterns = patterns.map((p) => new RegExp(p, 'i'));
    let hidden = 0;
    this.modelRoot.traverse((o) => {
      if (o === this.modelRoot || o === this.flash) return;
      const hide = this.hiddenPatterns.some((re) => re.test(o.name || ''));
      if (o.isMesh || o.isGroup || o.isObject3D) {
        if (hide) hidden++;
        o.visible = !hide;
      }
    });
    this.hiddenCount = hidden;
    return hidden;
  }

  /** Ambient light scale 0..1 (sky visibility at the eye, already smoothed by the caller). */
  setAmbientScale(s) {
    this.ambientScale = s;
    this.scene.environmentIntensity = this.baseEnvIntensity * s;
    this.hemi.intensity = this.baseHemiIntensity * s;
  }

  /** One fixed simulation tick: recoil springs and the muzzle flash timer. */
  tickSim(dt) {
    this.motion.tick(dt);
    if (this.flashTimer > 0) this.flashTimer -= dt;
  }

  /** Simulation not advancing (paused / menu): keep the interpolated pose still. */
  holdSim() {
    this.motion.hold();
  }

  /** Called from the simulation tick when a shot is fired. */
  onShot() {
    this.motion.onShot();
    this.flashTimer = 0.05;
    this.flash.material.rotation = Math.random() * Math.PI * 2;
    const s = 0.085 + Math.random() * 0.04;
    this.flash.scale.set(s, s, s);
  }

  /**
   * @param {object} p
   * @param {number} p.dt              frame delta (s), only for per-frame smoothing
   * @param {number} [p.alpha]         interpolation between the last two simulation ticks
   * @param {import('three').Quaternion} p.orientation world camera orientation
   * @param {number} p.aspect
   * @param {number} p.ads             0..1
   * @param {number} p.sprint          0..1 target
   * @param {number} p.bobPhase
   * @param {number} p.bobAmount
   * @param {number} p.lookDX          yaw change this frame (rad)
   * @param {number} p.lookDY          pitch change this frame (rad)
   * @param {number} p.reload          0..1 progress, 0 when not reloading
   * @param {number} p.motion          camera motion setting 0..1
   * @param {number} p.sunVisibility   0..1
   */
  update(p) {
    const dt = Math.max(p.dt || 0, 0);
    this.camera.quaternion.copy(p.orientation);
    this.camera.aspect = p.aspect;
    this.camera.updateProjectionMatrix();

    const m = this.motion;
    m.frame(dt, p.lookDX || 0, p.lookDY || 0, p.sprint);
    const { kick, kickRot } = m.kickAt(p.alpha ?? 1);
    this.kick = kick;
    this.kickRot = kickRot;
    const swayX = m.swayX;
    const swayY = m.swayY;
    const sprint = m.sprint;

    const ads = adsBlend(p.ads);
    const hipW = 1 - ads;
    const motion = p.motion;
    const pos = this._tmpV.lerpVectors(this.hip, this.adsPos, ads);
    // bob (reduced in ADS)
    const bob = p.bobAmount * motion * (0.25 + 0.75 * hipW);
    pos.x += Math.cos(p.bobPhase) * 0.006 * bob + swayX * hipW;
    pos.y += Math.abs(Math.sin(p.bobPhase)) * -0.006 * bob + swayY * hipW;
    // recoil pushes the weapon back
    pos.z += kick * 0.035;
    // sprint pose: lower and inward
    pos.y -= sprint * 0.06;
    pos.x -= sprint * 0.03;
    // reload dip
    const r = p.reload > 0 ? Math.sin(Math.min(p.reload, 1) * Math.PI) : 0;
    pos.y -= r * 0.07;
    // weapon switch: lowered out of view (0 = up, 1 = fully lowered)
    const lower = Math.min(Math.max(p.lower || 0, 0), 1);
    pos.y -= lower * 0.28;
    this.holder.position.copy(pos);
    // static hip cant (data: viewModel.hipRotation) so the side of the weapon reads, none in
    // ADS; plus recoil, reload, sprint and sway rotations
    const hr = this.hipRotation;
    this.holder.rotation.set(
      hr[0] * hipW + kickRot * 0.05 + r * -0.5 - sprint * 0.25 - lower * 0.7,
      hr[1] * hipW + sprint * 0.55 + swayX * 2 * hipW,
      hr[2] * hipW + sprint * 0.3 + r * 0.35 + swayX * 1.5 * hipW,
    );

    // lighting: world sun direction is fixed; dim direct light when the eye is in shadow
    this.sunVisibility += (p.sunVisibility - this.sunVisibility) * (1 - Math.exp(-6 * dt));
    this.sun.intensity = this.sunIntensity * (0.12 + 0.88 * this.sunVisibility);

    // muzzle flash (timer advanced in tickSim)
    const flashOn = this.flashTimer > 1e-6;
    this.flash.visible = flashOn;
    this.flash.getWorldPosition(this.flashLight.position);
    this.flashLight.intensity = flashOn ? 1.6 : 0;
  }

  /**
   * Camera-space position of a model-space point for the static hip/ADS pose (hip cant
   * included, animation offsets excluded) - the same pose update() draws at rest.
   */
  _poseToCamera(local, ads, out) {
    return viewModelPointInCamera(this.def.viewModel, local, ads, out);
  }

  /**
   * Camera-space position of the muzzle socket node as currently posed by update() (i.e. what
   * is actually drawn, including any animation offsets).
   */
  renderedMuzzleInCameraSpace(out = new Vector3()) {
    if (!this.muzzleNode) return null;
    this.camera.updateMatrixWorld(true);
    this.muzzleNode.getWorldPosition(out);
    return this.camera.worldToLocal(out);
  }

  /** Muzzle position in camera space for the current hip/ADS pose without animation offsets. */
  muzzleInCameraSpace(ads = 0, out = new Vector3()) {
    return this._poseToCamera(this.muzzleLocal, ads, out);
  }

  /** ADS eye socket in camera space (should be the camera origin when fully aimed). */
  adsEyeInCameraSpace(ads = 1, out = new Vector3()) {
    return this._poseToCamera(this.adsEyeLocal, ads, out);
  }
}
