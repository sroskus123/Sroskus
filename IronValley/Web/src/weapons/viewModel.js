// First-person view model: rendered in its own pass (depth cleared) with a fixed vertical
// FOV so it never clips into walls and keeps its proportions when the player changes FOV.
// Lighting uses the same sun direction and environment map as the world; the direct sun is
// dimmed when the eye is in shadow. Pose = hip/ADS blend + sway + bob + recoil + sprint.
// Recoil springs advance on the fixed simulation tick (ViewModelMotion.tick via tickSim) and
// are interpolated here, so the weapon motion is the same at every frame rate. The recoil rotation
// pivots about the sight line (socket_ads), so in ADS (no pitch / yaw kick by data) the sight stays on
// the camera axis - the aim kick comes from the camera recoil, which moves weapon and view together.
// The muzzle flash lives a fixed simulated time (FlashTimer); the pistol slide / bolt cycles per shot.

import {
  AdditiveBlending,
  CanvasTexture,
  Color,
  DirectionalLight,
  Euler,
  Group,
  HemisphereLight,
  PerspectiveCamera,
  PointLight,
  Quaternion,
  Scene,
  SRGBColorSpace,
  Sprite,
  SpriteMaterial,
  Vector3,
} from 'three';
import { createPlaceholderRifle } from './placeholderRifle.js';
import { adsBlend, viewModelPointInCamera, ViewModelMotion } from './viewModelMotion.js';
import { FlashTimer, resolveFeel } from './muzzleEffects.js';
import { createRng } from '../util/rng.js';
import attachments from '../data/attachments.json' with { type: 'json' };

const SIM_DT = 1 / 60;
const _qR = new Quaternion();
const _eR = new Euler(0, 0, 0, 'XYZ');
const _pv = new Vector3();
const _pv2 = new Vector3();
const _q2 = new Quaternion();
const _Z = new Vector3(0, 0, 1);

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
    // attachments (optics) in the rifle model frame; not touched by setHiddenNodes
    this.attachRoot = new Group();
    this.attachRoot.name = 'attachments';
    this.model = null;
    // ADS: share of the walk bob / look sway left on the weapon in full ADS (0 = the sight stays put) and the muzzle
    // flash sprite / light in ADS (attachments.json view)
    const view = attachments.view || {};
    this.adsBob = view.adsBob ?? 0.25;
    this.adsSway = view.adsSway ?? 0;
    this.flashAds = { sprite: 1, viewLight: 1, ...(view.flashAds || {}) };

    this.flashLight = new PointLight(new Color('#ffb56b'), 0, 0.35, 2);
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
    this.vmDef = vm; // view-model definition of the current ADS pose (per optic, setOpticPose)
    const ph = createPlaceholder();
    this.setModel(ph.object, ph.muzzle, { placeholder: true, name: 'placeholder', adsEye: ph.adsEye });
    this.hiddenPatterns = [];

    // animation state (springs on the simulation tick, sway / sprint per frame); kick peaks from
    // weapons.json feel.viewModel
    this.motion = new ViewModelMotion({ ...(vm.motion || {}), kick: (def.feel && def.feel.viewModel) || (vm.motion && vm.motion.kick) || {} });
    this.hipRotation = vm.hipRotation || [0, 0, 0];
    this.kick = 0; // last rendered (interpolated) values, for inspection
    this.kickRot = 0;
    this.recoilPose = { back: 0, rise: 0, pitch: 0, roll: 0, yaw: 0 };
    this.feel = resolveFeel(def.feel || {});
    this.flashTimer = new FlashTimer(this.feel.flash.duration, this.feel.flash.minVisible);
    this.flashIntensity = 0;
    this._flashRng = createRng(97);
    this._flashAds = 0;
    this.cycleAge = Infinity; // simulated seconds since the last shot (slide / bolt cycle)
    this._simDt = SIM_DT;
    this.updated = false;
    this.sunVisibility = 1;
    this._tmpV = new Vector3();
  }

  setModel(object, muzzleNode, { placeholder = false, name = 'model', adsEye = null } = {}) {
    while (this.modelRoot.children.length) this.modelRoot.remove(this.modelRoot.children[0]);
    this.modelRoot.add(object);
    this.modelRoot.add(this.attachRoot);
    this.model = object;
    this.muzzleNode = muzzleNode;
    this.adsEyeNode = adsEye;
    this.isPlaceholder = placeholder;
    this.assetName = name;
    // socket positions in model space (sockets may be nested under rotated bones)
    this.camera.updateMatrixWorld(true);
    const tmp = new Vector3();
    if (muzzleNode) this.muzzleLocal.copy(this.modelRoot.worldToLocal(muzzleNode.getWorldPosition(tmp)));
    if (adsEye) this.adsEyeLocal.copy(this.modelRoot.worldToLocal(adsEye.getWorldPosition(tmp)));
    this.modelAdsEyeLocal = this.adsEyeLocal.clone(); // the model's own sight line (irons)
    this._setupFeelNodes(object);
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
    if (!this.model) return 0;
    this.model.traverse((o) => {
      if (o === this.model || o === this.flash) return;
      const hide = this.hiddenPatterns.some((re) => re.test(o.name || ''));
      if (o.isMesh || o.isGroup || o.isObject3D) {
        if (hide) hidden++;
        o.visible = !hide;
      }
    });
    this.hiddenCount = hidden;
    return hidden;
  }

  /**
   * ADS pose for a mounted attachment: the eye point `adsEyeLocal` (model space, e.g. the optic's socket_eye)
   * lands on the camera in full ADS. Also the pivot of the ADS recoil roll.
   */
  setOpticPose(adsEyeLocal) {
    const e = adsEyeLocal;
    this.adsEyeLocal.set(e[0], e[1], e[2]);
    this.adsPos.set(-e[2], -e[1], e[0]);
    this.vmDef = { ...this.def.viewModel, adsEyeLocal: [e[0], e[1], e[2]], adsPosition: [-e[2], -e[1], e[0]] };
  }

  /** Ambient light scale 0..1 (sky visibility at the eye, already smoothed by the caller). */
  setAmbientScale(s) {
    this.ambientScale = s;
    this.scene.environmentIntensity = this.baseEnvIntensity * s;
    this.hemi.intensity = this.baseHemiIntensity * s;
  }

  /** Eject socket, recoil pivot and the nodes that cycle per shot (slide / bolt), from the model + data. */
  _setupFeelNodes(object) {
    const sockets = this.def.viewModel.sockets || {};
    const tmp = new Vector3();
    const ej = object.getObjectByName(sockets.eject || 'socket_eject');
    const data = this.def.feel && this.def.feel.casing && this.def.feel.casing.ejectLocal;
    this.ejectLocal = ej ? this.modelRoot.worldToLocal(ej.getWorldPosition(tmp)).clone() : new Vector3().fromArray(data || [this.muzzleLocal.x * 0.2, this.muzzleLocal.y, 0.015]);
    this.ejectFromSocket = !!ej;
    // cycle: model -X (towards the shooter) expressed in each node's parent space
    const cyc = this.def.feel && this.def.feel.cycle;
    this.cycleNodes = [];
    if (cyc && cyc.nodes) {
      const re = new RegExp(cyc.nodes, 'i');
      const a = this.modelRoot.localToWorld(new Vector3(0, 0, 0));
      const b = this.modelRoot.localToWorld(new Vector3(-1, 0, 0));
      object.traverse((o) => {
        if (o === object || !o.parent || !re.test(o.name || '')) return;
        const pa = o.parent.worldToLocal(a.clone());
        const pb = o.parent.worldToLocal(b.clone());
        this.cycleNodes.push({ node: o, base: o.position.clone(), dir: pb.sub(pa) });
      });
    }
    this.cycleOffset = 0;
    const pv = this.def.feel && this.def.feel.viewModel && this.def.feel.viewModel.pivot;
    this.kickPivot = pv ? new Vector3().fromArray(pv) : this.adsEyeLocal;
  }

  /** Slide / bolt travel (m) at a simulated time since the shot. */
  _cycleTravel(t) {
    const c = this.def.feel && this.def.feel.cycle;
    if (!c || !Number.isFinite(t)) return 0;
    if (t < c.backTime) return c.travel * (t / c.backTime);
    const u = (t - c.backTime) / c.returnTime;
    if (u >= 1) return 0;
    return c.travel * (1 - u * u * (3 - 2 * u));
  }

  /** One fixed simulation tick: recoil springs, the muzzle flash timer and the slide / bolt cycle. */
  tickSim(dt) {
    this._simDt = dt;
    this.motion.tick(dt);
    this.flashTimer.tick(dt);
    if (Number.isFinite(this.cycleAge)) this.cycleAge = this.cycleAge + dt > 1 ? Infinity : this.cycleAge + dt;
  }

  /** Simulation not advancing (paused / menu): keep the interpolated pose still. */
  holdSim() {
    this.motion.hold();
  }

  /**
   * Called from the simulation tick when a shot is fired.
   * @param {object} [shot] weapon:fired payload ({ ads, crouch }) - stance of the kick
   */
  onShot(shot = {}) {
    const ads = (shot && shot.ads) || 0;
    this.motion.onShot({ ads, crouch: !!(shot && shot.crouch) });
    this.flashTimer.trigger();
    this.cycleAge = 0;
    // deterministic per-shot variation (never Math.random: identical at every frame rate / replay)
    const f = this.feel.flash;
    this.flash.material.rotation = this._flashRng.next() * Math.PI * 2;
    const s = (f.size[0] + (f.size[1] - f.size[0]) * this._flashRng.next()) * (1 + (f.adsScale - 1) * adsBlend(ads));
    this.flash.scale.set(s, s, s);
    this._flashAds = ads;
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
    const k = m.kickAt(p.alpha ?? 1);
    this.kick = k.back;
    this.kickRot = k.pitch;
    const rp = this.recoilPose;
    rp.back = k.back;
    rp.rise = k.rise;
    rp.pitch = k.pitch;
    rp.roll = k.roll;
    rp.yaw = k.yaw;
    this.updated = true;
    const swayX = m.swayX;
    const swayY = m.swayY;
    const sprint = m.sprint;

    const ads = adsBlend(p.ads);
    const hipW = 1 - ads;
    const motion = p.motion;
    const pos = this._tmpV.lerpVectors(this.hip, this.adsPos, ads);
    // bob and sway on the weapon fade out in ADS (attachments.json view.adsBob / adsSway): in full ADS the
    // sight stays on the camera axis, so the reticle does not swim (the eye itself still bobs with the camera)
    const bob = p.bobAmount * motion * (this.adsBob + (1 - this.adsBob) * hipW);
    const swayW = this.adsSway + (1 - this.adsSway) * hipW;
    pos.x += Math.cos(p.bobPhase) * 0.006 * bob + swayX * swayW;
    pos.y += Math.abs(Math.sin(p.bobPhase)) * -0.006 * bob + swayY * swayW;
    // recoil pushes the weapon back (along the view axis) and up (rise is 0 in ADS by data)
    pos.z += k.back;
    pos.y += k.rise;
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
      hr[0] * hipW + r * -0.5 - sprint * 0.25 - lower * 0.7,
      hr[1] * hipW + sprint * 0.55 + swayX * 2 * swayW,
      hr[2] * hipW + sprint * 0.3 + r * 0.35 + swayX * 1.5 * swayW,
    );
    // recoil rotations about fixed holder-local pivots p (position += q * (p - q_kick * p)):
    // muzzle rise / yaw about feel.viewModel.pivot (shoulder pocket / wrist), roll about the sight line
    // point socket_ads, so a roll never moves the sight off the camera axis in ADS
    if (k.pitch !== 0 || k.yaw !== 0) this._rotateAbout(this.kickPivot, _qR.setFromEuler(_eR.set(k.pitch, k.yaw, 0, 'XYZ')));
    if (k.roll !== 0) this._rotateAbout(this.adsEyeLocal, _qR.setFromAxisAngle(_Z, k.roll));
    // slide / bolt cycle (simulated time since the shot, interpolated like the springs)
    if (this.cycleNodes && this.cycleNodes.length) {
      const age = Number.isFinite(this.cycleAge) ? Math.max(0, this.cycleAge - (1 - Math.min(Math.max(p.alpha ?? 1, 0), 1)) * this._simDt) : Infinity;
      const tr = this._cycleTravel(age);
      this.cycleOffset = tr;
      for (const c of this.cycleNodes) c.node.position.copy(c.base).addScaledVector(c.dir, tr);
    }

    // lighting: world sun direction is fixed; dim direct light when the eye is in shadow
    this.sunVisibility += (p.sunVisibility - this.sunVisibility) * (1 - Math.exp(-6 * dt));
    this.sun.intensity = this.sunIntensity * (0.12 + 0.88 * this.sunVisibility);

    // muzzle flash: fixed simulated lifetime (FlashTimer), drawn at least once per shot
    // In ADS the sprite and the light fade by attachments.json view.flashAds: the flash is hidden by the flash hider
    // from the shooter's eye, and a light on the weapon lit the optic's housing for two frames ("the whole scope
    // flickers"); the flash light also only reaches the front of the handguard (distance), never the optic.
    const fI = this.flashTimer.sample(p.alpha ?? 1, this._simDt);
    this.flashIntensity = fI;
    const fa = adsBlend(this._flashAds);
    const spriteK = 1 + ((this.flashAds.sprite ?? 1) - 1) * fa;
    const lightK = 1 + ((this.flashAds.viewLight ?? 1) - 1) * fa;
    const flashOn = fI * spriteK > 0.02;
    this.flash.visible = flashOn;
    this.flash.material.opacity = Math.min(1, fI * spriteK);
    this.flash.getWorldPosition(this.flashLight.position);
    this.flashLight.intensity = fI > 1e-6 ? this.feel.flash.light * fI * lightK : 0;
  }

  /** Rotates the holder by q (holder-local) about the model-space point `local`, which stays fixed. */
  _rotateAbout(local, q) {
    _pv.set(local.z, local.y, -local.x); // model -> holder (model root turned +90 deg about Y)
    _pv2.copy(_pv).applyQuaternion(q);
    _pv.sub(_pv2).applyQuaternion(this.holder.quaternion);
    this.holder.position.add(_pv);
    this.holder.quaternion.multiply(q);
  }

  /**
   * Camera-space position of a model-space point for the static hip/ADS pose (hip cant
   * included, animation offsets excluded) - the same pose update() draws at rest.
   */
  _poseToCamera(local, ads, out) {
    return viewModelPointInCamera(this.vmDef, local, ads, out);
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

  /** Camera-space position of the eject socket as currently drawn (null before the first update()). */
  ejectInCameraSpace(out = new Vector3()) {
    if (!this.updated) return null;
    this.holder.updateMatrix();
    return out.copy(this.ejectLocal).applyQuaternion(this.modelRoot.quaternion).applyQuaternion(this.holder.quaternion).add(this.holder.position);
  }

  /** Camera-space direction of a model-space vector (+X muzzle, +Y up, +Z right) in the drawn pose. */
  modelDirInCameraSpace(v, out = new Vector3()) {
    _q2.copy(this.holder.quaternion).multiply(this.modelRoot.quaternion);
    return out.copy(v).applyQuaternion(_q2);
  }
}
