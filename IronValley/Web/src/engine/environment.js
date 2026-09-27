// Daylight environment: Preetham sky (three's Sky.js, with the detailed cloud layer from
// clouds.js), one directional sun whose direction is
// the single source of truth for both the sky shader and the light, soft shadows that follow
// the player with texel snapping (no shimmering), PMREM image-based lighting generated from
// the same sky, a faint hemisphere fill, and distance + height fog.

import {
  Color,
  DirectionalLight,
  FogExp2,
  HemisphereLight,
  LinearSRGBColorSpace,
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
    this.sun.shadow.bias = s.shadowBias;
    this.sun.shadow.normalBias = s.shadowNormalBias;
    this.sun.shadow.radius = s.shadowRadius;
    this.sun.shadow.blurSamples = 8;
    this.lightDistance = 100;
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
    this.pmrem = new PMREMGenerator(renderer);
    const envScene = new Scene();
    const envSky = new Sky();
    envSky.scale.setScalar(1800);
    applyDetailedClouds(envSky, cfg.clouds);
    applySkyUniforms(envSky, cfg.sky, this.sunDirection);
    envSky.material.uniforms.showSunDisc.value = 0;
    envScene.add(envSky);
    this.envTarget = this.pmrem.fromScene(envScene, 0, 0.1, 5000);
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
   * Centres the shadow frustum on `focus`, snapped to whole shadow-map texels in light space
   * so shadows do not shimmer while the player moves.
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
    this.sun.target.position.copy(f);
    this.sun.position.copy(f).addScaledVector(dir, this.lightDistance);
    this.sun.target.updateMatrixWorld();
    this.sun.updateMatrixWorld();
    this.sky.position.copy(cameraPosition);
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
