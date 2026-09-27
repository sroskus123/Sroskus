// Optic rendering (browser, three.js). Implements the runtime contract of Art/Reference/OPTICS_spec.md section 5:
//
//   glass        thin coated sheets, NO transmission / refraction pass (a transmission pass renders the scene again
//                at lower resolution through roughness mips: blur, and it changes frame to frame when the weapon
//                kicks). Dark tint, low opacity, reduced environment reflection so the view is not washed out.
//   1x reticle   collimated: the reticle sheet of IV-H1 / IV-R1 is drawn with a shader that ignores the sheet UVs
//                and looks the reticle up by the view-ray DIRECTION in the optic frame (projection from infinity
//                along the sight axis). The ray is built with the WORLD camera's projection (the view model is
//                drawn with its own fixed FOV), so the reticle lies on the world point it aims at, whatever the
//                eye / weapon offset (parallax-free) - and in full ADS the sight axis IS the camera axis = the
//                hitscan direction incl. recoil. Crisp at any scale: signed distance field + the documented minimum
//                on-screen size (dot >= 2.5 px, strokes >= 1.25 px), unlit and not tone mapped (stays red).
//   2x / 3x      picture-in-picture: a second camera at the eye looks along the optic's sight axis with the TRUE
//                field of view into a square half-float MSAA render target at least as large as the ocular disc on
//                screen (never upscaled); the ocular glass shows it through its UVs with the reticle composited at
//                object-space scale, the eyepiece vignette and the eyebox (exit pupil) fade.
//   6x           full screen: the main camera narrows to the overlay's documented vertical FOV and the IV-S6 overlay
//                (field stop, vignette) plus the SDF reticle are drawn over the whole screen; the view model is hidden.
//                While raising, the ocular shows the PiP image like the 2x / 3x.
//
// Mounting (section 5.6 / 8): the chosen optic's LOD0 is attached at mount_on_iv7.socket_rail_rifle_m, the IV-7's
// built-in optic nodes (^Optic) are hidden, and the flip-up irons fold (-90 deg about the bone-local Y: top towards
// the stock) whenever an optic is mounted; they stand up only for 'irons'.

import {
  Color,
  DoubleSide,
  FrontSide,
  Group,
  HalfFloatType,
  LinearFilter,
  Matrix3,
  Matrix4,
  Mesh,
  NormalBlending,
  OrthographicCamera,
  PerspectiveCamera,
  PlaneGeometry,
  Quaternion,
  Scene,
  ShaderMaterial,
  SRGBColorSpace,
  Vector2,
  Vector3,
  Vector4,
  WebGLRenderTarget,
} from 'three';
import { loadGLTF, loadTextureAsset, hasAsset } from '../engine/assets.js';
import { ATTACHMENTS, IRONS, OPTIC_IDS, eyeboxFactor, getOpticDef } from './optics.js';

const V = ATTACHMENTS.view;
const _q = new Quaternion();
const _q2 = new Quaternion();
const _v = new Vector3();
const _v2 = new Vector3();
const _v3 = new Vector3();
const _m3 = new Matrix3();
const _Y = new Vector3(0, 1, 0);

/** sRGB 0..255 -> linear 0..1 */
function srgbToLinear(c) {
  const s = c / 255;
  return s <= 0.04045 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
}

// ------------------------------------------------------------------ shaders

const RETICLE_PARS = /* glsl */ `
uniform sampler2D uSdf;
uniform float uSdfSize;
uniform float uSdfSpread;
uniform float uLitHW;
uniform float uEtchHW;
uniform float uDotR;
uniform float uMinStrokePx;
uniform float uMinDotPx;
uniform vec3 uLitColor;
uniform float uEtchOpacity;
uniform float uHalfField;

// Reticle at texture uv (row 0 = up). Returns straight colour + coverage. Coverage from the signed distance field
// with a per-fragment dilation that keeps strokes >= uMinStrokePx and the centre dot >= uMinDotPx on screen.
vec4 reticleSample(vec2 uv) {
  vec3 s = texture2D(uSdf, uv).rgb;
  vec2 fw = fwidth(uv) * uSdfSize;
  float tpp = max(max(fw.x, fw.y), 1e-4); // SDF texels per screen pixel
  float maxK = max(uSdfSpread - tpp, 0.0); // never dilate past the encoded range
  float dLit = (s.g - 0.5) * 2.0 * uSdfSpread;
  float dEtch = (s.b - 0.5) * 2.0 * uSdfSpread;
  float kLit = min(max(0.0, 0.5 * uMinStrokePx * tpp - uLitHW), maxK);
  float kEtch = min(max(0.0, 0.5 * uMinStrokePx * tpp - uEtchHW), maxK);
  float cLit = clamp((dLit + kLit) / tpp + 0.5, 0.0, 1.0);
  float cEtch = clamp((dEtch + kEtch) / tpp + 0.5, 0.0, 1.0) * uEtchOpacity;
  if (uDotR > 0.0) {
    float r = length((uv - 0.5) * uSdfSize);
    float R = max(uDotR, 0.5 * uMinDotPx * tpp);
    cLit = max(cLit, clamp((R - r) / tpp + 0.5, 0.0, 1.0));
  }
  float a = max(cLit, cEtch);
  vec3 col = uLitColor * (cLit / max(a, 1e-5));
  return vec4(col, a);
}

// tan-space direction (x right, y up) -> reticle texture uv
vec2 reticleUv(vec2 t) {
  return vec2(0.5 + 0.5 * t.x / uHalfField, 0.5 - 0.5 * t.y / uHalfField);
}
`;

const COLLIMATED_VERT = /* glsl */ `
void main() {
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`;

const COLLIMATED_FRAG = /* glsl */ `
${RETICLE_PARS}
uniform mat3 uCamToOptic;
uniform vec2 uTanHalf;
uniform vec4 uViewport;
uniform float uOpacity;
void main() {
  vec2 ndc = ((gl_FragCoord.xy - uViewport.xy) / uViewport.zw) * 2.0 - 1.0;
  vec3 dcam = vec3(ndc.x * uTanHalf.x, ndc.y * uTanHalf.y, -1.0);
  vec3 v = uCamToOptic * dcam; // optic frame: x forward, y up, z right
  if (v.x <= 1e-6) discard;
  vec4 r = reticleSample(reticleUv(vec2(v.z, v.y) / v.x));
  if (r.a * uOpacity < 0.003) discard;
  gl_FragColor = vec4(r.rgb, r.a * uOpacity);
  #include <colorspace_fragment>
}
`;

const EYEPIECE_VERT = /* glsl */ `
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`;

const EYEPIECE_FRAG = /* glsl */ `
${RETICLE_PARS}
uniform sampler2D uPip;
uniform float uPipTan;
uniform float uEyebox;
uniform float uVigStart;
uniform float uHasPip;
varying vec2 vUv;
void main() {
  // lens disc: u to the viewer's right; glTF v runs down the image, so p.y (up) = 1 - 2 v
  vec2 p = vec2(vUv.x * 2.0 - 1.0, 1.0 - vUv.y * 2.0);
  float r = length(p);
  vec3 scene = uHasPip > 0.5 ? texture2D(uPip, vec2(vUv.x, 1.0 - vUv.y)).rgb : vec3(0.0);
  float vig = 1.0 - smoothstep(uVigStart, 1.0, r);
  vec3 lin = scene * vig * uEyebox;
  #ifdef TONE_MAPPING
  vec3 col = toneMapping(lin);
  #else
  vec3 col = lin;
  #endif
  vec4 ret = reticleSample(reticleUv(p * uPipTan));
  col = mix(col, ret.rgb, ret.a * uEyebox);
  gl_FragColor = vec4(col, 1.0);
  #include <colorspace_fragment>
}
`;

const OVERLAY_VERT = /* glsl */ `
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = vec4(position.xy, 0.0, 1.0);
}
`;

const OVERLAY_FRAG = /* glsl */ `
${RETICLE_PARS}
uniform sampler2D uOverlay;
uniform vec2 uScreen;
uniform float uTanHalfV;
uniform float uFade;
uniform float uHasOverlay;
varying vec2 vUv;
void main() {
  vec2 px = vUv * uScreen;
  vec2 q = (px - 0.5 * uScreen) / uScreen.y; // units of screen height, x right, y up
  vec4 ov = vec4(0.0, 0.0, 0.0, 1.0);
  if (abs(q.x) <= 0.5 && abs(q.y) <= 0.5) {
    ov = uHasOverlay > 0.5 ? texture2D(uOverlay, vec2(0.5 + q.x, 0.5 - q.y)) : vec4(0.0);
  }
  vec4 ret = reticleSample(reticleUv(q * 2.0 * uTanHalfV));
  vec3 pc = ov.rgb * ov.a;
  float pa = ov.a;
  pc = ret.rgb * ret.a + pc * (1.0 - ret.a);
  pa = ret.a + pa * (1.0 - ret.a);
  pc *= (1.0 - uFade);
  pa = pa + (1.0 - pa) * uFade;
  gl_FragColor = vec4(pc, pa);
  #include <colorspace_fragment>
}
`;

function reticleUniforms(def, sdfTex) {
  const R = def.reticle;
  const sdf = R.sdf || { size: 512, spread: 16 };
  const texPerUnit = sdf.size / R.fieldUnits; // SDF texels per reticle unit (MOA / mrad)
  const col = R.colourSrgb.map(srgbToLinear);
  const b = V.reticleBrightness ?? 1;
  return {
    uSdf: { value: sdfTex },
    uSdfSize: { value: sdf.size },
    uSdfSpread: { value: sdf.spread },
    uLitHW: { value: R.litHalfWidth * texPerUnit },
    uEtchHW: { value: R.etchHalfWidth * texPerUnit },
    uDotR: { value: R.dotRadius * texPerUnit },
    uMinStrokePx: { value: R.minStrokePx },
    uMinDotPx: { value: R.minDotPx },
    uLitColor: { value: new Color(col[0] * b, col[1] * b, col[2] * b) },
    uEtchOpacity: { value: V.reticleEtchOpacity ?? 0.92 },
    uHalfField: { value: Math.tan((0.5 * R.fieldUnits * R.unitInRad)) },
  };
}

export function makeCollimatedReticleMaterial(def, sdfTex) {
  const m = new ShaderMaterial({
    name: `IV_${def.id}_CollimatedReticle`,
    uniforms: {
      ...reticleUniforms(def, sdfTex),
      uCamToOptic: { value: new Matrix3() },
      uTanHalf: { value: new Vector2(1, 1) },
      uViewport: { value: new Vector4(0, 0, 1, 1) },
      uOpacity: { value: 1 },
    },
    vertexShader: COLLIMATED_VERT,
    fragmentShader: COLLIMATED_FRAG,
    transparent: true,
    depthWrite: false,
    depthTest: true,
    side: FrontSide,
    blending: NormalBlending,
    toneMapped: false,
  });
  return m;
}

export function makeEyepieceMaterial(def, sdfTex) {
  return new ShaderMaterial({
    name: `IV_${def.id}_Eyepiece`,
    uniforms: {
      ...reticleUniforms(def, sdfTex),
      uPip: { value: null },
      uPipTan: { value: Math.tan(((def.trueFovDeg || 5) * Math.PI) / 360) },
      uEyebox: { value: 0 },
      uVigStart: { value: V.pip.vignetteStart ?? 0.8 },
      uHasPip: { value: 0 },
    },
    vertexShader: EYEPIECE_VERT,
    fragmentShader: EYEPIECE_FRAG,
    side: DoubleSide,
    toneMapped: true,
  });
}

export function makeScopeOverlayMaterial(def, sdfTex, overlayTex) {
  return new ShaderMaterial({
    name: `IV_${def.id}_ScopeOverlay`,
    uniforms: {
      ...reticleUniforms(def, sdfTex),
      uOverlay: { value: overlayTex },
      uScreen: { value: new Vector2(1, 1) },
      uTanHalfV: { value: Math.tan((def.overlay.vfovDeg * Math.PI) / 360) },
      uFade: { value: 0 },
      uHasOverlay: { value: overlayTex ? 1 : 0 },
    },
    vertexShader: OVERLAY_VERT,
    fragmentShader: OVERLAY_FRAG,
    transparent: true,
    premultipliedAlpha: true,
    depthTest: false,
    depthWrite: false,
    toneMapped: false,
  });
}

// ------------------------------------------------------------------ assets

/** Glass: thin sheets, no transmission, dark tint, modest reflections (does not wash the view out). */
function tuneGlass(m) {
  if (!m) return;
  m.transmission = 0;
  m.transparent = true;
  m.depthWrite = false;
  m.side = DoubleSide;
  m.roughness = Math.min(m.roughness ?? 0.03, 0.05);
  m.metalness = 0;
  m.envMapIntensity = 0.35;
  if (m.specularColor && m.specularColor.isColor) {
    // coatings: keep the tint, cap the strength (the red front coating must not tint the whole view)
    const mx = Math.max(m.specularColor.r, m.specularColor.g, m.specularColor.b);
    if (mx > 1) m.specularColor.multiplyScalar(1 / mx);
  }
  m.needsUpdate = true;
}

function setAnisotropy(root, aniso) {
  root.traverse((o) => {
    if (!o.isMesh) return;
    for (const m of Array.isArray(o.material) ? o.material : [o.material]) {
      if (!m) continue;
      for (const k of ['map', 'normalMap', 'roughnessMap', 'metalnessMap', 'aoMap', 'emissiveMap']) {
        if (m[k] && m[k].isTexture && m[k].anisotropy !== aniso) {
          m[k].anisotropy = aniso;
          m[k].needsUpdate = true;
        }
      }
    }
  });
}

/**
 * Loads the optic set: LOD0 (first person), LOD1 (third person), reticle SDFs and the 6x overlay. Missing files
 * leave that optic unavailable (the game falls back to the irons / placeholder) instead of failing.
 */
export class OpticAssets {
  constructor({ maxAnisotropy = 8 } = {}) {
    this.maxAnisotropy = maxAnisotropy;
    this.items = new Map();
    this.errors = [];
    this.loaded = false;
  }

  async loadAll() {
    await Promise.all(OPTIC_IDS.map((id) => this._load(id)));
    this.loaded = true;
    return this;
  }

  async _load(id) {
    const def = getOpticDef(id);
    if (!def.assets || !hasAsset(def.assets.glb)) {
      this.errors.push(`${id}: asset missing`);
      return;
    }
    try {
      const [g0, g1, sdf, overlay] = await Promise.all([
        loadGLTF(def.assets.glb),
        def.assets.lod1 && hasAsset(def.assets.lod1) ? loadGLTF(def.assets.lod1) : Promise.resolve(null),
        def.reticle.sdf && hasAsset(def.reticle.sdf.file) ? loadTextureAsset(def.reticle.sdf.file) : Promise.resolve(null),
        def.overlay && def.overlay.file && hasAsset(def.overlay.file) ? loadTextureAsset(def.overlay.file, { mipmaps: true, colorSpace: SRGBColorSpace }) : Promise.resolve(null),
      ]);
      const lod0 = g0.scene;
      lod0.name = `optic_${id}`;
      lod0.updateMatrixWorld(true);
      setAnisotropy(lod0, this.maxAnisotropy);
      const parts = { glassRear: null, glassFront: null, reticle: null, body: null };
      lod0.traverse((o) => {
        if (!o.isMesh) return;
        o.castShadow = false;
        o.receiveShadow = false;
        o.frustumCulled = false;
        const mn = (o.material && o.material.name) || '';
        if (/_Glass_Rear$/i.test(mn)) parts.glassRear = o;
        else if (/_Glass_Front$/i.test(mn)) parts.glassFront = o;
        else if (/_Reticle$/i.test(mn)) parts.reticle = o;
        else if (/_Body$/i.test(mn)) parts.body = o;
      });
      const sockets = {};
      for (const s of ['socket_rail', 'socket_eye', 'socket_sight_axis_rear', 'socket_sight_axis_front', 'socket_reticle']) sockets[s] = lod0.getObjectByName(s) || null;
      let lod1 = null;
      if (g1) {
        lod1 = g1.scene;
        lod1.name = `optic_${id}_LOD1`;
        setAnisotropy(lod1, Math.min(4, this.maxAnisotropy));
        lod1.traverse((o) => {
          if (!o.isMesh) return;
          o.castShadow = true;
          o.receiveShadow = true;
          if (/_Glass/i.test((o.material && o.material.name) || '')) tuneGlass(o.material);
        });
      }
      if (sdf) sdf.name = `${id}_reticle_sdf`;
      this.items.set(id, { def, lod0, parts, sockets, lod1, sdf, overlay });
    } catch (err) {
      this.errors.push(`${id}: ${err && err.message}`);
      console.warn('[optics] could not load', id, err && err.message);
    }
  }

  has(id) {
    return this.items.has(id);
  }

  get(id) {
    return this.items.get(id) || null;
  }

  /** A third-person copy of an optic's LOD1 (shared geometry and materials). */
  cloneLod1(id) {
    const it = this.items.get(id);
    if (!it || !it.lod1) return null;
    const c = it.lod1.clone(true);
    c.userData.opticId = id;
    return c;
  }
}

// ------------------------------------------------------------------ first person

/**
 * The optic of the first-person IV-7: mounting, irons, reticle / eyepiece / overlay materials, the PiP camera and
 * target, the 6x full-screen pass. One instance per rifle view model.
 */
export class FirstPersonOptics {
  /**
   * @param {object} o
   * @param {import('./viewModel.js').ViewModel} o.viewModel  the rifle's view model
   * @param {OpticAssets} o.assets
   */
  constructor({ viewModel, assets }) {
    this.vm = viewModel;
    this.assets = assets;
    this.id = null; // optic on the rail as drawn ('irons', an optic id, or null = empty rail mid-swap)
    this.mounts = new Map(); // id -> { group, item, reticleMat, eyepieceMat, overlayMat }
    this.pipCamera = new PerspectiveCamera(5, 1, 0.05, 2500);
    this.rt = null;
    this.rtSize = 0;
    this.pipRenders = 0;
    this.pipActive = false;
    this.scoped = false;
    this.scopeFade = 0;
    this.eyebox = 0;
    this.eyeLateral = 0;
    this.eyeRelief = 0;
    this.discPx = 0;
    this.overlayScene = new Scene();
    this.overlayCamera = new OrthographicCamera(-1, 1, 1, -1, 0, 1);
    this.overlayQuad = new Mesh(new PlaneGeometry(2, 2), null);
    this.overlayQuad.frustumCulled = false;
    this.overlayScene.add(this.overlayQuad);
    this.ironsFolded = false;
    this.bindQuat = new Map();
    this._debug = {};
  }

  get def() {
    return this.id && this.id !== IRONS ? getOpticDef(this.id) : getOpticDef(IRONS);
  }

  /** 'irons' | 'collimated' | 'pip' | 'fullscreen' (null rail = 'irons' look without sights). */
  get mode() {
    if (!this.id || this.id === IRONS) return 'irons';
    return this.def.mode;
  }

  /** Called after the rifle model is (re)loaded: rebinds the irons bones and the mounted optic. */
  onRifleModel() {
    this.bindQuat.clear();
    const model = this.vm.model;
    if (model) {
      for (const n of ['rear_sight', 'front_sight']) {
        const b = model.getObjectByName(n);
        if (b) this.bindQuat.set(n, { bone: b, q: b.quaternion.clone() });
      }
    }
    const id = this.id;
    this.id = undefined;
    this.setOptic(id ?? IRONS);
  }

  _mount(id) {
    if (this.mounts.has(id)) return this.mounts.get(id);
    const item = this.assets.get(id);
    if (!item) return null;
    const def = item.def;
    const group = new Group();
    group.name = `mount_${id}`;
    group.position.fromArray(def.railRifle);
    group.add(item.lod0);
    const rec = { group, item, reticleMat: null, eyepieceMat: null, overlayMat: null };
    tuneGlass(item.parts.glassFront && item.parts.glassFront.material);
    if (def.mode === 'collimated') {
      tuneGlass(item.parts.glassRear && item.parts.glassRear.material);
      if (item.parts.reticle && item.sdf) {
        rec.reticleMat = makeCollimatedReticleMaterial(def, item.sdf);
        item.parts.reticle.material = rec.reticleMat;
        item.parts.reticle.renderOrder = 10;
      }
    } else {
      // magnified: the ocular shows the PiP image with the reticle composited; the static reticle sheet is not drawn
      if (item.parts.reticle) item.parts.reticle.visible = false;
      if (item.parts.glassRear && item.sdf) {
        rec.eyepieceMat = makeEyepieceMaterial(def, item.sdf);
        item.parts.glassRear.material = rec.eyepieceMat;
        item.parts.glassRear.renderOrder = 1;
      }
      if (item.parts.glassFront) item.parts.glassFront.renderOrder = 2;
      if (def.mode === 'fullscreen' && item.sdf) rec.overlayMat = makeScopeOverlayMaterial(def, item.sdf, item.overlay);
    }
    group.visible = false;
    this.vm.attachRoot.add(group);
    this.mounts.set(id, rec);
    return rec;
  }

  /** Irons: fold (-90 deg about bone-local Y, top towards the stock) or stand them up. */
  setIronsFolded(folded) {
    for (const { bone, q } of this.bindQuat.values()) {
      bone.quaternion.copy(q);
      if (folded) bone.quaternion.multiply(_q.setFromAxisAngle(_Y, -Math.PI / 2));
      bone.updateMatrixWorld(true);
    }
    this.ironsFolded = !!folded;
  }

  /**
   * Optic drawn on the rail: 'irons' (no optic, irons up), an optic id, or null (empty rail while swapping,
   * irons folded). The ADS pose follows the mounted optic (ViewModel.setOpticPose), set by the caller.
   */
  setOptic(id) {
    const want = id === undefined ? IRONS : id;
    if (want === this.id) return;
    for (const m of this.mounts.values()) m.group.visible = false;
    let ok = want === IRONS || want === null;
    if (want && want !== IRONS) {
      const rec = this._mount(want);
      if (rec) {
        rec.group.visible = true;
        ok = true;
      }
    }
    this.id = ok ? want : IRONS;
    // the built-in optic of the IV-7 is always replaced (IV-R1 is its stand-alone twin)
    this.vm.setHiddenNodes(['^Optic']);
    this.setIronsFolded(this.id !== IRONS);
    this.pipActive = false;
    this.scoped = false;
  }

  _current() {
    return this.id && this.id !== IRONS ? this.mounts.get(this.id) || null : null;
  }

  /**
   * Per frame, after viewModel.update(): reticle uniforms, eyebox, PiP camera pose and target size, scope state.
   * @param {object} f { worldCamera, ads (0..1), primary (bool), renderer (WebGLRenderer), vmVisible }
   */
  update(f) {
    const rec = this._current();
    this.pipActive = false;
    this.scoped = false;
    this.scopeFade = 0;
    if (!rec || !f.primary) {
      this.eyebox = 0;
      this.discPx = 0;
      this._debug = { id: this.id, mode: this.mode, eyebox: 0, discPx: 0, rtSize: this.rtSize, pipActive: false, scoped: false, scopeFade: 0 };
      return;
    }
    const def = rec.item.def;
    const vm = this.vm;
    const gl = f.renderer;
    const cam = f.worldCamera;
    // camera space -> optic frame: optic orientation in camera space = holder * modelRoot (rifle, mount: identity)
    _q.copy(vm.holder.quaternion).multiply(vm.modelRoot.quaternion);
    const W = gl.domElement.width;
    const H = gl.domElement.height;
    if (rec.reticleMat) {
      const u = rec.reticleMat.uniforms;
      _q2.copy(_q).invert();
      u.uCamToOptic.value.setFromMatrix4(_m4FromQuat(_q2));
      const tv = Math.tan((cam.fov * Math.PI) / 360);
      u.uTanHalf.value.set(tv * cam.aspect, tv);
      u.uViewport.value.set(0, 0, W, H);
    }
    if (def.mode === 'pip' || def.mode === 'fullscreen') {
      // eyebox: the eye (view-model camera origin) against the sight axis
      vm.holder.updateMatrixWorld(true);
      const sk = rec.item.sockets;
      const rear = sk.socket_sight_axis_rear.getWorldPosition(_v);
      const front = sk.socket_sight_axis_front.getWorldPosition(_v2);
      const eye = sk.socket_eye.getWorldPosition(_v3);
      const eyeCam = vm.camera.position;
      const axis = front.sub(rear).normalize();
      const rel = _vRel.copy(eyeCam).sub(eye);
      this.eyeRelief = rel.dot(axis);
      this.eyeLateral = rel.addScaledVector(axis, -this.eyeRelief).length();
      this.eyebox = eyeboxFactor(def, this.eyeLateral, this.eyeRelief, V.pip.eyeReliefTolerance);
      // ocular disc on screen (device px) -> render target size (never smaller than the disc)
      const rearW = sk.socket_sight_axis_rear.getWorldPosition(_vRear);
      const depth = Math.max(0.01, -vm.camera.worldToLocal(rearW).z);
      const pxPerTan = H / 2 / Math.tan((vm.camera.fov * Math.PI) / 360);
      this.discPx = (2 * def.lensRadius * pxPerTan) / depth;
      const P = V.pip;
      const want = Math.min(P.max, Math.max(P.min, Math.ceil((this.discPx * P.supersample) / P.step) * P.step));
      const scopeIn = def.mode === 'fullscreen' ? def.scopeIn : 2;
      this.scoped = def.mode === 'fullscreen' && f.ads >= scopeIn;
      if (this.scoped) this.scopeFade = 1 - smooth01((f.ads - scopeIn) / Math.max(1e-3, def.scopeFade));
      this.pipActive = !this.scoped && f.vmVisible && f.ads > 0.02 && this.eyebox > 0.001 && !!rec.eyepieceMat;
      if (this.pipActive && want !== this.rtSize) this._allocRt(want);
      if (rec.eyepieceMat) {
        const u = rec.eyepieceMat.uniforms;
        u.uEyebox.value = this.eyebox;
        u.uHasPip.value = this.pipActive && this.rt ? 1 : 0;
        u.uPip.value = this.rt ? this.rt.texture : null;
      }
      // PiP camera at the eye, looking along the sight axis (camera orientation x holder)
      const pc = this.pipCamera;
      pc.position.copy(cam.position);
      pc.quaternion.copy(cam.quaternion).multiply(vm.holder.quaternion);
      pc.fov = def.trueFovDeg;
      pc.aspect = 1;
      pc.near = cam.near;
      pc.far = cam.far;
      pc.updateProjectionMatrix();
      pc.updateMatrixWorld(true);
      if (rec.overlayMat) {
        const u = rec.overlayMat.uniforms;
        u.uScreen.value.set(W, H);
        u.uFade.value = this.scopeFade;
      }
    }
    this._debug = { id: this.id, mode: def.mode, eyebox: this.eyebox, eyeLateral: this.eyeLateral, eyeRelief: this.eyeRelief, discPx: this.discPx, rtSize: this.rtSize, pipActive: this.pipActive, scoped: this.scoped, scopeFade: this.scopeFade };
  }

  _allocRt(size) {
    if (!this.rt) {
      this.rt = new WebGLRenderTarget(size, size, { type: HalfFloatType, samples: V.pip.samples ?? 4, depthBuffer: true, minFilter: LinearFilter, magFilter: LinearFilter, generateMipmaps: false });
      this.rt.texture.name = 'optic_pip';
    } else this.rt.setSize(size, size);
    this.rtSize = size;
  }

  /** Renders the eyepiece image (call after the world pass, before the view-model pass). Shadows are reused. */
  renderPip(gl, scene) {
    if (!this.pipActive || !this.rt) return false;
    const prevTarget = gl.getRenderTarget();
    const prevAuto = gl.shadowMap.autoUpdate;
    gl.shadowMap.autoUpdate = false;
    gl.setRenderTarget(this.rt);
    gl.clear();
    gl.render(scene, this.pipCamera);
    gl.setRenderTarget(prevTarget);
    gl.shadowMap.autoUpdate = prevAuto;
    this.pipRenders++;
    return true;
  }

  /** Draws the 6x full-screen overlay + reticle over the world pass. */
  renderScope(gl) {
    const rec = this._current();
    if (!this.scoped || !rec || !rec.overlayMat) return false;
    this.overlayQuad.material = rec.overlayMat;
    gl.render(this.overlayScene, this.overlayCamera);
    return true;
  }

  /** Materials to precompile (renderer.compile) so the first ADS / swap never hitches. */
  compileTargets() {
    const out = [];
    for (const id of OPTIC_IDS) {
      const rec = this._mount(id);
      if (rec && rec.overlayMat) out.push(rec.overlayMat);
    }
    return out;
  }

  getDebug() {
    return { ...this._debug, id: this.id, mode: this.mode, ironsFolded: this.ironsFolded, pipRenders: this.pipRenders, rtSize: this.rtSize };
  }
}

const _vRel = new Vector3();
const _vRear = new Vector3();
function smooth01(x) {
  const t = Math.min(Math.max(x, 0), 1);
  return t * t * (3 - 2 * t);
}

const _m4 = new Matrix4();
function _m4FromQuat(q) {
  return _m4.makeRotationFromQuaternion(q);
}
