// Daylight environment: Preetham sky (three's Sky.js, with the detailed cloud layer from
// clouds.js), one directional sun whose direction is
// the single source of truth for both the sky shader and the light, soft shadows that follow
// the player with texel snapping (no shimmering), PMREM image-based lighting generated from
// the same sky, a faint hemisphere fill, and distance + height fog.
//
// Shadow depth range: the orthographic shadow camera's near/far planes are fitted every frame
// to exactly the depth span that geometry inside the shadow footprint can occupy (from the
// scene's height range), and the depth bias is given in metres. A loose range (near 1 / far
// 220 m) turned a small normalised bias into ~9 cm, which let sunlight leak under roofs at
// concave roof/wall junctions and detached shadows from their casters.

import {
  CircleGeometry,
  Color,
  DirectionalLight,
  FogExp2,
  HemisphereLight,
  LinearSRGBColorSpace,
  Mesh,
  MeshStandardMaterial,
  PMREMGenerator,
  Scene,
  Vector3,
} from 'three';
import { Sky } from 'three/examples/jsm/objects/Sky.js';
import { DEG2RAD } from '../util/math.js';
import { installHeightFog } from './heightFog.js';
import { applyDetailedClouds } from './clouds.js';

/** Unit vector pointing from the ground towards the sun. Azimuth: 0 = north (-Z), 90 = east (+X). */
export function sunDirectionFromAngles(elevationDeg, azimuthDeg, out = new Vector3()) {
  const el = elevationDeg * DEG2RAD;
  const az = azimuthDeg * DEG2RAD;
  return out.set(Math.cos(el) * Math.sin(az), Math.sin(el), -Math.cos(el) * Math.cos(az)).normalize();
}

/**
 * Image-based lighting only: scales the chroma of the sky seen by the environment capture.
 * The Preetham sky of Sky.js is far more saturated than real clear-sky light, so without this
 * every shadow is lit by an almost pure blue ambient (navy shadows); real clear-sky diffuse
 * light is only mildly blue (colour temperature around 10 000-15 000 K).
 */
function applyEnvSkySaturation(sky, saturation) {
  const mat = sky.material;
  const marker = 'gl_FragColor = vec4( texColor, 1.0 );';
  if (!mat.fragmentShader.includes(marker)) return false;
  mat.fragmentShader = mat.fragmentShader.replace(
    marker,
    'texColor = mix( vec3( dot( texColor, vec3( 0.2126, 0.7152, 0.0722 ) ) ), texColor, ivEnvSaturation );\n\t\t\t' + marker,
  );
  mat.fragmentShader = mat.fragmentShader.replace('void main() {', 'uniform float ivEnvSaturation;\n\t\tvoid main() {');
  mat.uniforms.ivEnvSaturation = { value: saturation };
  mat.needsUpdate = true;
  return true;
}

function applySkyUniforms(sky, cfg, sunDir) {
  const u = sky.material.uniforms;
  u.turbidity.value = cfg.turbidity;
  u.rayleigh.value = cfg.rayleigh;
  u.mieCoefficient.value = cfg.mieCoefficient;
  u.mieDirectionalG.value = cfg.mieDirectionalG;
  if (u.cloudCoverage) {
    u.cloudCoverage.value = cfg.cloudCoverage;
    u.cloudDensity.value = cfg.cloudDensity;
    u.cloudScale.value = cfg.cloudScale;
    u.cloudElevation.value = cfg.cloudElevation;
    u.cloudSpeed.value = cfg.cloudSpeed;
  }
  u.sunPosition.value.copy(sunDir);
}

export class Environment {
  /**
   * @param {import('three').WebGLRenderer} renderer
   * @param {Scene} scene
   * @param {object} cfg environment.json
   */
  constructor(renderer, scene, cfg) {
    this.cfg = cfg;
    this.scene = scene;
    // must run before any material is compiled
    installHeightFog(cfg.fog);

    this.sunDirection = sunDirectionFromAngles(cfg.sun.elevationDeg, cfg.sun.azimuthDeg);

    // --- sky ---
    this.sky = new Sky();
    this.sky.scale.setScalar(1800);
    this.sky.frustumCulled = false;
    this.sky.renderOrder = -1;
    applyDetailedClouds(this.sky, cfg.clouds);
    applySkyUniforms(this.sky, cfg.sky, this.sunDirection);
    scene.add(this.sky);

    // --- sun ---
    const s = cfg.sun;
    this.sun = new DirectionalLight(new Color(s.color), s.intensity);
    this.sun.castShadow = true;
    this.sun.shadow.mapSize.set(s.shadowMapSize, s.shadowMapSize);
    const cam = this.sun.shadow.camera;
    cam.left = -s.shadowExtent;
    cam.right = s.shadowExtent;
    cam.top = s.shadowExtent;
    cam.bottom = -s.shadowExtent;
    cam.near = 1;
    cam.far = 220;
    cam.updateProjectionMatrix();
    this.sun.shadow.bias = s.shadowBias ?? 0;
    this.sun.shadow.normalBias = s.shadowNormalBias;
    this.sun.shadow.radius = s.shadowRadius;
    this.sun.shadow.blurSamples = 8;
    this.lightDistance = 100;
    // world-space height range of everything that casts shadows (setShadowCasterHeights)
    this.casterMinY = -1;
    this.casterMaxY = 10;
    scene.add(this.sun);
    scene.add(this.sun.target);

    // --- ambient fill ---
    const h = cfg.hemisphere;
    this.hemi = new HemisphereLight(new Color(h.skyColor), new Color(h.groundColor), h.intensity);
    scene.add(this.hemi);

    // --- fog (color given in display space; three applies fog after tone mapping) ---
    const fogColor = new Color().setHex(parseInt(cfg.fog.color.slice(1), 16), LinearSRGBColorSpace);
    scene.fog = new FogExp2(fogColor, cfg.fog.density);

    // --- image based lighting from the same sky (sun disc hidden to avoid fireflies) ---
    // Pass 1 captures the sky alone. Pass 2 adds the sunlit ground below the horizon (lit by the
    // same sun and by pass 1's sky light, in the capture's units: the capture is scaled by
    // environmentIntensity when used), so walls and undersides get neutral bounce light from
    // the ground instead of the blue horizon haze the sky shader returns below the horizon.
    this.pmrem = new PMREMGenerator(renderer);
    const envScene = new Scene();
    const envSky = new Sky();
    envSky.scale.setScalar(1800);
    applyDetailedClouds(envSky, cfg.clouds);
    applyEnvSkySaturation(envSky, cfg.environmentSkySaturation ?? 1);
    applySkyUniforms(envSky, cfg.sky, this.sunDirection);
    envSky.material.uniforms.showSunDisc.value = 0;
    envScene.add(envSky);
    let envTarget = this.pmrem.fromScene(envScene, 0, 0.1, 5000);
    const gcfg = cfg.environmentGround;
    this.envGround = null;
    if (gcfg) {
      const envI = Math.max(cfg.environmentIntensity, 1e-3);
      const groundMat = new MeshStandardMaterial({
        color: new Color(gcfg.color),
        roughness: 1,
        metalness: 0,
        envMap: envTarget.texture,
        envMapIntensity: 1,
      });
      const ground = new Mesh(new CircleGeometry(gcfg.radius ?? 3000, 48), groundMat);
      ground.rotation.x = -Math.PI / 2;
      ground.position.y = gcfg.offsetY ?? -1.65;
      envScene.add(ground);
      const envSun = new DirectionalLight(new Color(s.color), s.intensity / envI);
      envSun.position.copy(this.sunDirection);
      envScene.add(envSun);
      envScene.add(envSun.target);
      const pass2 = this.pmrem.fromScene(envScene, 0, 0.1, 5000);
      envTarget.dispose();
      envTarget = pass2;
      ground.geometry.dispose();
      groundMat.dispose();
      this.envGround = { color: gcfg.color, offsetY: ground.position.y };
    }
    this.envTarget = envTarget;
    scene.environment = this.envTarget.texture;
    scene.environmentIntensity = cfg.environmentIntensity;
    envSky.geometry.dispose();
    envSky.material.dispose();
    this.pmrem.dispose();

    this._focus = new Vector3();
    this._x = new Vector3();
    this._y = new Vector3();
    this.follow(new Vector3());
  }

  /**
   * World-space height range of the static shadow casters (level bounds). Dynamic objects are
   * covered by a margin above (characters, jumps, props thrown up).
   */
  setShadowCasterHeights(minY, maxY) {
    this.casterMinY = minY;
    this.casterMaxY = maxY;
  }

  /**
   * Centres the shadow frustum on `focus`, snapped to whole shadow-map texels in light space
   * so shadows do not shimmer while the player moves, and fits near/far to the casters.
   */
  follow(focus, cameraPosition = focus) {
    const s = this.cfg.sun;
    const dir = this.sunDirection;
    const texel = (2 * s.shadowExtent) / s.shadowMapSize;
    // light-space basis identical to Object3D.lookAt for the shadow camera
    const x = this._x.set(0, 1, 0).cross(dir).normalize();
    const y = this._y.copy(dir).cross(x).normalize();
    const fx = Math.round(focus.dot(x) / texel) * texel;
    const fy = Math.round(focus.dot(y) / texel) * texel;
    const fz = focus.dot(dir);
    const f = this._focus.copy(x).multiplyScalar(fx).addScaledVector(y, fy).addScaledVector(dir, fz);
    this._fitShadowDepth(f, y);
    this.sun.target.position.copy(f);
    this.sun.position.copy(f).addScaledVector(dir, this.lightDistance);
    this.sun.target.updateMatrixWorld();
    this.sun.updateMatrixWorld();
    this.sky.position.copy(cameraPosition);
  }

  /**
   * A point p = f + a*X + b*Y + z*dir inside the footprint (|a|, |b| <= extent) has height
   * p.y = f.y + b*Y.y + z*dir.y, so every caster with height in [casterMinY, casterMaxY] lies
   * at z in [zMin, zMax] below. The light sits just above zMax; the depth range is then only a
   * few tens of metres and the bias (in metres) stays exact.
   */
  _fitShadowDepth(f, yAxis) {
    const s = this.cfg.sun;
    const dy = Math.max(this.sunDirection.y, 0.05);
    const spread = s.shadowExtent * Math.abs(yAxis.y);
    const zMax = (this.casterMaxY + 2 - f.y + spread) / dy + 0.5;
    const zMin = (this.casterMinY - 1 - f.y - spread) / dy - 0.5;
    const near = 0.5;
    this.lightDistance = zMax + near;
    const cam = this.sun.shadow.camera;
    const far = near + (zMax - zMin);
    if (cam.near !== near || Math.abs(cam.far - far) > 1e-9) {
      cam.near = near;
      cam.far = far;
      cam.updateProjectionMatrix();
    }
    if (s.shadowBiasMeters !== undefined) this.sun.shadow.bias = -s.shadowBiasMeters / (far - near);
  }

  /** Shadow depth range / bias actually in use (tests, tuning). */
  getShadowInfo() {
    const cam = this.sun.shadow.camera;
    const range = cam.far - cam.near;
    return {
      near: cam.near,
      far: cam.far,
      bias: this.sun.shadow.bias,
      biasMeters: -this.sun.shadow.bias * range,
      normalBias: this.sun.shadow.normalBias,
      radius: this.sun.shadow.radius,
      casterHeights: [this.casterMinY, this.casterMaxY],
    };
  }

  /** Light direction (towards the light) as the renderer uses it. */
  getLightDirection(out = new Vector3()) {
    return out.subVectors(this.sun.position, this.sun.target.position).normalize();
  }

  /** Consistency check used by tests: sky sun vs directional light. */
  verifySun() {
    const skySun = this.sky.material.uniforms.sunPosition.value.clone().normalize();
    const light = this.getLightDirection();
    return {
      skySun: skySun.toArray(),
      lightDirection: light.toArray(),
      dot: skySun.dot(light),
      elevationDeg: this.cfg.sun.elevationDeg,
      azimuthDeg: this.cfg.sun.azimuthDeg,
    };
  }
}
