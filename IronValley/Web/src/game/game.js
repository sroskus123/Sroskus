// Game orchestrator for the test-range build: wires renderer, environment, level, physics,
// player, weapon, effects, HUD and the fixed-step loop. Systems talk through the event bus.

import { PerspectiveCamera, Scene, Vector3, Box3, Object3D } from 'three';
import bindings from '../data/input_bindings.json' with { type: 'json' };
import movement from '../data/movement.json' with { type: 'json' };
import weapons from '../data/weapons.json' with { type: 'json' };
import envCfg from '../data/environment.json' with { type: 'json' };
import level from '../data/test_range.json' with { type: 'json' };
import { EventBus } from '../engine/events.js';
import { FixedStepLoop } from '../engine/loop.js';
import { Renderer } from '../engine/renderer.js';
import { Environment } from '../engine/environment.js';
import { AdaptiveResolution } from '../engine/adaptiveResolution.js';
import { assetStats, hasAsset, listAssets, loadGLTF } from '../engine/assets.js';
import { buildLevelSolids, listLevelBoxes } from '../level/levelGeometry.js';
import { buildTestRangeView } from '../level/testRangeView.js';
import { probeSkyVisibility } from '../engine/indirectBake.js';
import { updateBakedSun } from '../engine/bakedLightingMaterial.js';
import { CollisionWorld } from '../physics/collisionWorld.js';
import { CharacterController } from '../physics/characterController.js';
import { DynamicsWorld } from '../physics/dynamicsWorld.js';
import { InputManager } from '../player/input.js';
import { Settings } from '../player/settings.js';
import { Player } from '../player/player.js';
import { WeaponSystem, lookQuaternion } from '../weapons/weaponSystem.js';
import { ViewModel } from '../weapons/viewModel.js';
import { ImpactEffects } from '../weapons/impactEffects.js';
import { TargetDummies } from './targetDummies.js';
import { DummyView } from './dummyView.js';
import { Hud } from './hud.js';
import { createRng } from '../util/rng.js';
import { horizontalToVerticalFov, wrapAngle } from '../util/math.js';

function safeStorage() {
  try {
    const s = window.localStorage;
    const k = '__iv_probe__';
    s.setItem(k, '1');
    s.removeItem(k);
    return s;
  } catch {
    return null;
  }
}

const smooth = (t) => t * t * (3 - 2 * t);

export class Game {
  constructor(root) {
    this.root = root;
    this.events = new EventBus();
    this.state = 'loading';
    this.frameCount = 0;
    this.simTicks = 0;
    // debug/test switch: run the whole frame update but skip the WebGL draw calls (software
    // rendering in headless tests takes over a second per frame)
    this.drawEnabled = true;
    // menus (start / pause): the simulation is held, so an unchanged frame is not redrawn
    this.drawCount = 0;
    this._drawDirty = true;
    this._lastDrawSig = '';
    this.eventLog = [];
    this.data = { bindings, movement, weapons, environment: envCfg, level };
    this._eye = new Vector3();
    this._simEye = new Vector3();
    this._sunVis = 1;
    this._sunCheckTimer = 0;
    this._eyeSky = 1; // sky visibility at the eye (target), smoothed into _ambient
    this._ambient = 1;
    this._adapt = 1; // eye adaptation exposure multiplier (smoothed)
    this.eyeAdaptationEnabled = true; // test hook can freeze it (exposure-independent measurements)
    this.bounceSunOverride = null; // debug: baked bounce lit by this sun intensity instead of the light's
    this._lastYaw = 0;
    this._lastPitch = 0;
    this._lookSnaps = 0;
    this.weaponAsset = { path: null, loaded: false, placeholder: true, error: null, size: null };
  }

  async init() {
    const events = this.events;
    this.settings = new Settings({ storage: safeStorage() });
    this.rng = createRng(1337);

    // --- rendering ---
    this.renderer = new Renderer(this.root, { exposure: envCfg.exposure });
    this.baseExposure = envCfg.exposure;
    this.scene = new Scene();
    this.camera = new PerspectiveCamera(50, this.renderer.aspect, 0.05, 2500);
    this.scene.add(this.camera);
    this.env = new Environment(this.renderer.renderer, this.scene, envCfg);
    this.adaptive = new AdaptiveResolution({
      min: this.settings.limits.renderScaleMin,
      max: this.settings.limits.renderScaleMax,
    });
    this._applyRenderScale();

    // --- level ---
    this.levelSolids = buildLevelSolids(level);
    this.world = new CollisionWorld(this.levelSolids);
    const maxAniso = this.renderer.renderer.capabilities.getMaxAnisotropy();
    // baked indirect light: sky visibility + one sunlight bounce per vertex (ENV: interiors
    // must not be lit like open ground)
    const bl = envCfg.bakedLighting || {};
    this.bakedLighting =
      bl.enabled === false ? null : { rays: bl.rays ?? 32, ambientFloor: bl.ambientFloor ?? 0.12, cell: bl.cell ?? 0.5, largeCell: bl.largeCell ?? 1.0 };
    this.levelView = buildTestRangeView(level, this.levelSolids, {
      maxAnisotropy: Math.min(8, maxAniso),
      lighting: this.bakedLighting ? { world: this.world, sunDirection: this.env.sunDirection, ...this.bakedLighting } : null,
    });
    this.scene.add(this.levelView.group);
    // shadow depth range is fitted to the height span of the level (see Environment)
    const levelBounds = new Box3().setFromObject(this.levelView.group);
    this.env.setShadowCasterHeights(levelBounds.min.y, levelBounds.max.y);

    // --- physics ---
    this.dynamics = new DynamicsWorld({ gravity: movement.gravity });
    this.dynamics.addLevelBoxes(listLevelBoxes(level));

    // --- targets ---
    this.dummies = new TargetDummies(level.dummies);
    this.dummyView = new DummyView(this.dummies);
    this.scene.add(this.dummyView.group);
    if (this.bakedLighting) {
      // static targets: one sky-visibility probe at chest height scales their ambient light
      for (const it of this.dummyView.items) {
        const p = it.d.base.clone();
        p.y += 1.1;
        const sky = probeSkyVisibility(this.world, p, { sunDirection: this.env.sunDirection, rays: this.bakedLighting.rays }).skyVis;
        it.mat.envMapIntensity = this.bakedLighting.ambientFloor + (1 - this.bakedLighting.ambientFloor) * sky;
      }
    }

    // --- input + player ---
    this.input = new InputManager(bindings, events);
    this.input.attach(this.renderer.canvas);
    this.controller = new CharacterController(this.world, movement);
    this.player = new Player({ controller: this.controller, input: this.input, settings: this.settings, events, mouse: bindings.mouse });
    this.spawn();

    // --- weapon ---
    this.weaponDef = weapons.iv7_carbine;
    this.weapon = new WeaponSystem({ def: this.weaponDef, world: this.world, dummies: this.dummies, events, rng: createRng(4242) });
    this.viewModel = new ViewModel({
      def: this.weaponDef,
      envTexture: this.scene.environment,
      envIntensity: envCfg.environmentIntensity,
      sunDirection: this.env.sunDirection,
      sunColor: this.env.sun.color,
      sunIntensity: envCfg.sun.intensity,
    });
    this.effects = new ImpactEffects(this.scene, { rng: createRng(99).next });

    // --- HUD ---
    this.hud = new Hud(this.root, {
      bindings,
      settings: this.settings,
      events,
      levelName: level.displayName,
      onStart: () => this.startPlaying(true),
      onResume: () => this.startPlaying(true),
    });
    this.hud.setMode('loading');
    this.hud.weaponName.textContent = this.weaponDef.displayName;

    this._wireEvents();

    this.loop = new FixedStepLoop({
      step: (dt) => this.tick(dt),
      render: (alpha, dt) => this.render(alpha, dt),
    });

    await this.loadWeaponAsset();
    // compile all programs up front so the first frames do not hitch
    try {
      this.renderer.renderer.compile(this.scene, this.camera);
      this.renderer.renderer.compile(this.viewModel.scene, this.viewModel.camera);
    } catch {
      /* compile is an optimisation only */
    }
    this.setState('start');
    this.loop.start();
    return this;
  }

  _wireEvents() {
    const ev = this.events;
    const log = (type, payload) => {
      this.eventLog.push({ type, tick: this.simTicks, ...payload });
      if (this.eventLog.length > 200) this.eventLog.shift();
    };
    ev.on('input:menu', (p) => {
      log('menu', { reason: p.reason });
      if (this.state === 'playing') this.pause(p.reason);
    });
    ev.on('input:fallback', (p) => {
      log('pointer-fallback', { reason: p.reason });
      if (this.state === 'playing') this.hud.showNotice('Ukazatel myši nelze uzamknout — rozhlížej se tažením myši se stisknutým tlačítkem.', 6);
    });
    ev.on('input:released', (p) => {
      if (this.weapon) this.weapon.state.releaseInputs();
      log('input-released', { reason: p.reason });
    });
    ev.on('input:toggleFps', () => this.settings.set('showFps', !this.settings.get('showFps')));
    ev.on('weapon:fired', (p) => {
      this.viewModel.onShot();
      this.effects.onShot(p.muzzle);
    });
    ev.on('weapon:hit', (p) => {
      this.effects.onHit(p.hit);
      if (p.hit.kind === 'dummy') this.hud.showHitmarker(!!(p.damage && p.damage.killed));
      log('hit', { target: p.hit.targetKey, blocked: p.blocked });
    });
    ev.on('player:landed', (p) => log('landed', { speed: Number(p.speed.toFixed(3)) }));
    this.settings.onChange((key) => {
      this._drawDirty = true;
      if (key === 'renderScale' || key === 'adaptiveResolution' || key === '*') this._applyRenderScale();
    });
  }

  _applyRenderScale() {
    if (!this.renderer) return;
    if (this.settings.get('adaptiveResolution')) {
      this.renderer.setScale(this.adaptive.scale);
    } else {
      this.renderer.setScale(this.settings.get('renderScale'));
    }
  }

  spawn() {
    const m = level.markers.spawn;
    this.player.teleport(new Vector3().fromArray(m.pos), m.yaw, 0);
  }

  setState(s) {
    this.state = s;
    this.hud.setMode(s);
    this.input.setEnabled(s === 'playing');
    this.events.emit('game:state', { state: s });
  }

  /** Enter gameplay. fromGesture: request pointer lock (must be inside a user gesture). */
  startPlaying(fromGesture) {
    if (this.state === 'loading') return;
    this.setState('playing');
    this.hud.setStatus('');
    if (fromGesture) this.input.requestPointerLock();
    try {
      this.renderer.canvas.focus({ preventScroll: true });
    } catch {
      /* ignore */
    }
  }

  pause(reason = 'menu') {
    if (this.state !== 'playing') return;
    this.weapon.state.releaseInputs();
    this.setState('paused');
    this.input.exitPointerLock();
    this.hud.setStatus(reason === 'pointerlock-lost' ? 'Kurzor uvolněn.' : '');
  }

  // ------------------------------------------------------------------ simulation

  tick(dt) {
    if (this.state !== 'playing') {
      // simulation stands still: keep interpolated visuals still too (otherwise the view
      // behind the menu would jump between the last two tick states as alpha cycles)
      this.player.holdInterpolation();
      this.weapon.recoil.snapshot();
      this.viewModel.holdSim();
      this.dummyView.hold();
      this.input.consumeTick();
      return;
    }
    const inp = this.input;
    const fire = inp.isActive('fire');
    const aim = inp.isActive('aim');
    const reload = inp.wasPressed('reload');
    if (inp.wasPressed('weapon2')) this.hud.showNotice('Pistole zatím není k dispozici.', 2);
    if (inp.wasPressed('interact')) this.hud.showNotice('Tady není nic k použití.', 1.5);

    const reloading = this.weapon.state.state === 'reloading';
    this.player.tick(dt, { triggerHeld: fire, adsHeld: aim && !reloading });
    const eye = this.player.getSimEye(this._simEye);
    this.weapon.tick(
      dt,
      { trigger: fire, ads: aim, reload, canFire: true, sprinting: this.controller.sprinting },
      eye,
      this.player.yaw,
      this.player.pitch,
    );
    this.dummies.tick(dt);
    this.dummyView.tick(dt);
    this.dynamics.step(dt);
    this.effects.tick(dt);
    this.viewModel.tickSim(dt);
    this.hud.tick(dt);
    inp.consumeTick();
    this.simTicks++;
  }

  // ------------------------------------------------------------------ rendering

  render(alpha, frameDt) {
    const r = this.renderer;
    if (r.contextLost) return;
    r.resize();
    if (this.state === 'playing') this.player.applyLookInput();
    // wrapped: Player keeps yaw bounded by subtracting whole turns, which is not a turn
    let lookDX = wrapAngle(this.player.yaw - this._lastYaw);
    let lookDY = this.player.pitch - this._lastPitch;
    this._lastYaw = this.player.yaw;
    this._lastPitch = this.player.pitch;
    let snapped = false;
    if (this.player.lookSnaps !== this._lookSnaps) {
      // the view was set directly (teleport / respawn), not turned: no weapon sway from it
      this._lookSnaps = this.player.lookSnaps;
      lookDX = 0;
      lookDY = 0;
      snapped = true;
    }

    const eye = this.player.getRenderEye(alpha, this._eye);
    const bob = this.player.getRenderBob(alpha);
    const rec = this.weapon.recoil.interpolated(alpha);
    const q = lookQuaternion(this.player.yaw + rec.yaw, this.player.pitch + rec.pitch, this.camera.quaternion);
    this.camera.position.copy(eye);
    const ws = this.weapon.state;
    const adsEase = smooth(ws.ads);
    const hfov = this.settings.get('fovDeg') * (1 + (this.weaponDef.adsFovMultiplier - 1) * adsEase);
    this.camera.fov = horizontalToVerticalFov(hfov, r.aspect);
    this.camera.aspect = r.aspect;
    this.camera.updateProjectionMatrix();
    this.camera.updateMatrixWorld();

    this.env.follow(eye, eye);

    // is the eye in sun shadow? (dims the view model's direct light) and how much sky does it
    // see (scales the view model's ambient like the baked level lighting)
    this._sunCheckTimer -= frameDt;
    if (this._sunCheckTimer <= 0 || snapped) {
      this._sunCheckTimer = 0.1;
      this._sunVis = this.world.raycast(eye, this.env.sunDirection, 400) ? 0 : 1;
      if (this.bakedLighting) this._eyeSky = probeSkyVisibility(this.world, eye, { sunDirection: this.env.sunDirection, rays: 16 }).skyVis;
    }
    if (this.bakedLighting) {
      // teleports / respawns jump straight to the new state; otherwise smooth
      this._ambient = snapped ? this._eyeSky : this._ambient + (this._eyeSky - this._ambient) * (1 - Math.exp(-6 * frameDt));
      const f = this.bakedLighting.ambientFloor;
      this.viewModel.setAmbientScale(f + (1 - f) * this._ambient);
      updateBakedSun(this.levelView.lighting.uniforms, this.env.sun.color, this.bounceSunOverride ?? this.env.sun.intensity);
    }
    this._updateEyeAdaptation(frameDt, snapped);

    this.viewModel.update({
      dt: frameDt,
      alpha,
      orientation: q,
      aspect: r.aspect,
      ads: ws.ads,
      sprint: this.controller.sprinting ? 1 : 0,
      bobPhase: bob.phase,
      bobAmount: bob.amount,
      lookDX,
      lookDY,
      reload: ws.state === 'reloading' ? ws.reloadTimer / ws.reloadDuration : 0,
      motion: this.settings.get('cameraMotion'),
      sunVisibility: this._sunVis,
    });
    this.dummyView.update(alpha);

    if (this.drawEnabled) {
      // In a menu the scene behind the translucent overlay is static: skip the draw when nothing
      // visible changed (saves the GPU; with software rendering it also keeps the menu responsive).
      const sig = this._drawSignature();
      const idle = this.state !== 'playing' && !this._drawDirty && sig === this._lastDrawSig;
      if (!idle) {
        const gl = r.renderer;
        gl.clear();
        gl.render(this.scene, this.camera);
        gl.clearDepth();
        gl.render(this.viewModel.scene, this.viewModel.camera);
        this._lastDrawSig = sig;
        this._drawDirty = false;
        this.drawCount++;
      }
    }

    this.hud.update(frameDt, {
      weapon: ws.getState(),
      player: this.controller,
      fps: this.loop.fps,
      showFps: this.settings.get('showFps'),
      sprinting: this.controller.sprinting,
    });

    // only frames actually drawn during play tell the adaptive resolution anything (menus skip draws)
    if (this.settings.get('adaptiveResolution') && !this.loop.frozen && this.state === 'playing') {
      const s = this.adaptive.update(this.loop.lastFrameMs, frameDt);
      if (s !== null) r.setScale(s);
    }
    this.frameCount++;
  }

  /** Everything that changes the drawn image while the simulation is held (menu redraw check). */
  _drawSignature() {
    const r = this.renderer.renderer;
    const parts = [
      ...this.camera.matrixWorld.elements,
      ...this.camera.projectionMatrix.elements,
      ...this.viewModel.holder.position.toArray(),
      this.viewModel.holder.rotation.x,
      this.viewModel.holder.rotation.y,
      this.viewModel.holder.rotation.z,
      r.toneMappingExposure,
      this.viewModel.ambientScale,
      this.viewModel.sun.intensity,
      this.viewModel.flash.visible ? 1 : 0,
      r.domElement.width,
      r.domElement.height,
      this.env.sun.intensity,
    ];
    let s = '';
    for (const v of parts) s += `${Math.round(v * 1e5)},`;
    return s;
  }

  /**
   * Eye adaptation: in enclosed spaces (little sky visible from the eye) the exposure rises up
   * to eyeAdaptation.maxBoost, slowly when going in and faster when coming out, like the eye
   * (and camera auto-exposure). Driven by the sky-visibility probe instead of a GPU luminance
   * readback, so it is cheap and deterministic.
   */
  _updateEyeAdaptation(frameDt, snapped) {
    const a = envCfg.eyeAdaptation;
    let target = 1;
    if (a && this.bakedLighting && this.eyeAdaptationEnabled) {
      const [lo, hi] = a.enclosedSky || [0.05, 0.45];
      const t = Math.min(Math.max((this._eyeSky - lo) / (hi - lo), 0), 1);
      const open = t * t * (3 - 2 * t);
      target = 1 + ((a.maxBoost ?? 1) - 1) * (1 - open);
    }
    if (snapped || !a || !this.eyeAdaptationEnabled) this._adapt = target;
    else {
      const rate = target > this._adapt ? a.brightenRate ?? 1 : a.darkenRate ?? 3;
      this._adapt += (target - this._adapt) * (1 - Math.exp(-rate * frameDt));
    }
    this.renderer.renderer.toneMappingExposure = this.baseExposure * this._adapt;
  }

  // ------------------------------------------------------------------ assets

  async loadWeaponAsset() {
    const path = this.weaponDef.viewModel.asset;
    this.weaponAsset.path = path;
    if (!hasAsset(path)) {
      this.hud.setPlaceholderNote('Zbraň: provizorní model (IV-7 zatím není hotová)');
      return;
    }
    try {
      const gltf = await loadGLTF(path);
      const obj = gltf.scene;
      obj.updateMatrixWorld(true);
      const sockets = this.weaponDef.viewModel.sockets || {};
      let muzzle = obj.getObjectByName(sockets.muzzle || 'socket_muzzle') || null;
      const adsEye = obj.getObjectByName(sockets.adsEye || 'socket_ads') || null;
      let glassFixed = 0;
      obj.traverse((o) => {
        if (!muzzle && !o.isMesh && /muzzle/i.test(o.name)) muzzle = o;
        if (o.isMesh) {
          o.castShadow = false;
          o.receiveShadow = false;
          o.frustumCulled = false;
          // KHR_materials_transmission needs a transmission pass that samples the same
          // scene; the view model pass contains only the weapon, so the lens would render
          // black. Use a plain thin transparent coated lens instead.
          const mats = Array.isArray(o.material) ? o.material : [o.material];
          for (const m of mats) {
            if (m && m.transmission > 0) {
              m.transmission = 0;
              m.transparent = true;
              m.opacity = 0.16;
              m.depthWrite = false;
              m.roughness = Math.min(m.roughness ?? 0.05, 0.08);
              m.needsUpdate = true;
              glassFixed++;
            }
          }
        }
      });
      const box = new Box3().setFromObject(obj);
      const size = box.getSize(new Vector3());
      if (!muzzle) {
        muzzle = new Object3D();
        muzzle.name = 'Socket_Muzzle_auto';
        muzzle.position.set(box.max.x, (box.min.y + box.max.y) / 2, (box.min.z + box.max.z) / 2);
        obj.add(muzzle);
      }
      this.viewModel.setModel(obj, muzzle, { placeholder: false, name: path.split('/').pop(), adsEye });
      this._drawDirty = true;
      this.weaponAsset = {
        path,
        loaded: true,
        placeholder: false,
        error: null,
        size: size.toArray(),
        boundsMin: box.min.toArray(),
        boundsMax: box.max.toArray(),
        muzzleNode: muzzle.name,
        adsEyeNode: adsEye ? adsEye.name : null,
        muzzleLocal: this.viewModel.muzzleLocal.toArray(),
        adsEyeLocal: this.viewModel.adsEyeLocal.toArray(),
        glassMaterialsAdjusted: glassFixed,
        textures: (() => {
          // texture maps referenced by the weapon's materials and how many have pixel data
          const seen = new Set();
          let decoded = 0;
          obj.traverse((o) => {
            if (!o.isMesh) return;
            for (const m of Array.isArray(o.material) ? o.material : [o.material]) {
              for (const key of ['map', 'normalMap', 'roughnessMap', 'metalnessMap', 'aoMap', 'emissiveMap']) {
                const t = m && m[key];
                if (!t || seen.has(t)) continue;
                seen.add(t);
                if (t.image && t.image.width > 0 && t.image.height > 0) decoded++;
              }
            }
          });
          return { referenced: seen.size, withImage: decoded, embeddedDecodedWithoutUrl: assetStats.embeddedImagesDecoded };
        })(),
        meshCount: (() => {
          let n = 0;
          obj.traverse((o) => o.isMesh && n++);
          return n;
        })(),
      };
      this.hud.setPlaceholderNote('');
    } catch (err) {
      console.warn('[assets] weapon GLB failed to load, using placeholder:', err && err.message);
      this.weaponAsset.error = String(err && err.message);
      this.hud.setPlaceholderNote('Zbraň: provizorní model (GLB se nepodařilo načíst)');
    }
  }

  // ------------------------------------------------------------------ state for tests / debug

  getState() {
    const p = this.player.getState();
    return {
      state: this.state,
      frame: this.frameCount,
      draws: this.drawCount,
      ticks: this.loop.ticks,
      simTicks: this.simTicks,
      simTime: this.loop.simTime,
      fps: this.loop.fps,
      frozen: this.loop.frozen,
      timeScale: this.loop.timeScale,
      alpha: this.loop.alpha,
      player: p,
      weapon: this.weapon.getState(),
      weaponAsset: { ...this.weaponAsset, viewModel: this.viewModel.assetName, isPlaceholder: this.viewModel.isPlaceholder },
      viewModel: {
        kick: this.viewModel.kick,
        kickRot: this.viewModel.kickRot,
        swayX: this.viewModel.motion.swayX,
        swayY: this.viewModel.motion.swayY,
        holderPosition: this.viewModel.holder.position.toArray(),
        holderRotation: [this.viewModel.holder.rotation.x, this.viewModel.holder.rotation.y, this.viewModel.holder.rotation.z],
        finite: [this.viewModel.holder.position.x, this.viewModel.holder.position.y, this.viewModel.holder.position.z].every(Number.isFinite),
      },
      input: this.input.getState(),
      dummies: this.dummies.getState(),
      dynamics: this.dynamics.getState(),
      render: this.renderer.getInfo(),
      camera: {
        position: this.camera.position.toArray(),
        fovVertical: this.camera.fov,
        fovHorizontalSetting: this.settings.get('fovDeg'),
      },
      settings: { ...this.settings.values },
      sun: this.env.verifySun(),
      shadow: this.env.getShadowInfo(),
      bakedLighting: this.levelView.lighting
        ? {
            vertices: this.levelView.lighting.vertices,
            hiddenVertices: this.levelView.lighting.hiddenVertices,
            ms: this.levelView.lighting.ms,
            eyeSky: this._eyeSky,
            viewModelAmbient: this.viewModel.ambientScale,
            exposure: this.renderer.renderer.toneMappingExposure,
            adaptation: this._adapt,
          }
        : null,
      sky: { detailedClouds: !!this.env.sky.userData.detailedClouds },
      assets: listAssets(),
      effects: { impacts: this.effects.impacts, decals: this.effects.decalCount },
      events: this.eventLog.slice(-50),
    };
  }
}
