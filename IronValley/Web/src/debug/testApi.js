// window.__IV — test and debugging interface. Reads state and drives time/input for automated
// tests. The game never calls into this module; removing it does not change gameplay.

import { Quaternion, Vector3 } from 'three';

export function installTestApi(game, target = window) {
  let renderOnStep = false;
  const api = {
    version: 1,
    ready: true,
    /** Direct access for interactive debugging only (tests must not rely on internals). */
    _game: game,

    getState: () => game.getState(),
    getLevelInfo: () => ({
      id: game.data.level.id,
      displayName: game.data.level.displayName,
      markers: game.data.level.markers,
      dummies: game.data.level.dummies,
    }),
    getConfig: () => ({ movement: game.data.movement, weapon: game.weaponDef, bindings: game.data.bindings }),

    /** Enter the playing state without a user gesture (no pointer lock). */
    startGame: () => {
      game.startPlaying(false);
      return game.state;
    },
    openMenu: () => game.pause('test'),

    // ---- time control ----
    pause: () => {
      game.loop.frozen = true;
      game.loop.resetAccumulator();
      return true;
    },
    resume: () => {
      game.loop.frozen = false;
      game.loop._lastTs = null;
      return true;
    },
    /** Runs exactly n fixed ticks synchronously. Renders once afterwards if renderOnStep. */
    step: (n = 1, opts = {}) => {
      const render = opts.render ?? renderOnStep;
      game.loop.stepTicks(Math.max(0, n | 0), { render });
      return game.loop.ticks;
    },
    /** Simulates `count` frames of `dtSeconds` through the real accumulator (frame pacing tests). */
    frames: (dtSeconds, count = 1, opts = {}) => {
      const render = opts.render ?? renderOnStep;
      let ticks = 0;
      for (let i = 0; i < count; i++) ticks += game.loop.frame(dtSeconds, { render });
      return ticks;
    },
    resetAccumulator: () => game.loop.resetAccumulator(),
    setTimeScale: (s) => {
      game.loop.timeScale = Math.max(0, Number(s) || 0);
      return game.loop.timeScale;
    },
    setRenderOnStep: (on) => {
      renderOnStep = !!on;
      return renderOnStep;
    },
    /** Eye adaptation on/off (off = fixed base exposure, for exposure-independent pixel checks). */
    setEyeAdaptation: (on) => {
      game.eyeAdaptationEnabled = !!on;
      return game.eyeAdaptationEnabled;
    },
    /** Skip the WebGL draw calls while keeping the full frame update (pose, HUD). */
    setDrawEnabled: (on) => {
      game.drawEnabled = !!on;
      return game.drawEnabled;
    },
    renderNow: () => {
      game.render(game.loop.alpha, 0);
      return game.frameCount;
    },

    // ---- input injection (goes through the same handlers as DOM events) ----
    keyDown: (code) => game.input.handleKeyDown(code, false),
    keyUp: (code) => game.input.handleKeyUp(code),
    mouseMove: (dx, dy) => {
      game.input.handleMouseMove(dx, dy);
      game.player.applyLookInput();
    },
    mouseButton: (button, down) => game.input.handleMouseButton(button, !!down),
    releaseAll: () => game.input.releaseAll('test'),

    // ---- test-only placement ----
    teleport: (x, y, z, yawDeg = null, pitchDeg = null) => {
      game.player.teleport(new Vector3(x, y, z), yawDeg, pitchDeg);
      return game.player.getState().position;
    },
    teleportToMarker: (name) => {
      const m = game.data.level.markers[name];
      if (!m) throw new Error(`Unknown marker ${name}`);
      game.player.teleport(new Vector3().fromArray(m.pos), m.yaw ?? 0, m.pitch ?? 0);
      return game.player.getState().position;
    },
    setLook: (yawDeg, pitchDeg) => {
      game.player.setLook(yawDeg, pitchDeg);
      return { yaw: yawDeg, pitch: pitchDeg };
    },
    /** Aim the camera at a world point from the current simulation eye. */
    lookAt: (x, y, z) => {
      const eye = game.player.getSimEye(new Vector3());
      const d = new Vector3(x, y, z).sub(eye);
      const yaw = (Math.atan2(-d.x, -d.z) * 180) / Math.PI;
      const pitch = (Math.atan2(d.y, Math.hypot(d.x, d.z)) * 180) / Math.PI;
      game.player.setLook(yaw, pitch);
      return { yaw, pitch };
    },

    // ---- weapon helpers (test / debug only) ----
    setInfiniteAmmo: (on) => {
      game.weapon.state.infiniteAmmo = !!on;
      return game.weapon.state.infiniteAmmo;
    },
    refillAmmo: () => {
      const s = game.weapon.state;
      s.cancelReload();
      s.magazine = game.weaponDef.magazineSize;
      s.reserve = game.weaponDef.reserveAmmo;
      return s.getState();
    },
    resetRecoil: () => game.weapon.recoil.reset(),

    setSetting: (key, value) => game.settings.set(key, value),
    /** Debug lighting overrides (tuning only; not persisted). */
    setLighting: (o = {}) => {
      const r = game.renderer.renderer;
      if (o.exposure !== undefined) {
        game.baseExposure = o.exposure; // eye adaptation multiplies this every frame
        r.toneMappingExposure = o.exposure * game._adapt;
      }
      if (o.sun !== undefined) {
        game.env.sun.intensity = o.sun;
        game.viewModel.sunIntensity = o.sun;
      }
      if (o.env !== undefined) {
        game.scene.environmentIntensity = o.env;
        game.viewModel.baseEnvIntensity = o.env;
        game.viewModel.setAmbientScale(game.viewModel.ambientScale);
      }
      if (o.hemi !== undefined) game.env.hemi.intensity = o.hemi;
      // baked sunlight bounce: null = follows the sun light, a number = fixed sun intensity (lets
      // a test switch only the direct sunlight)
      if (o.bounceSun !== undefined) game.bounceSunOverride = o.bounceSun;
      if (o.fogDensity !== undefined) game.scene.fog.density = o.fogDensity;
      return {
        exposure: r.toneMappingExposure,
        sun: game.env.sun.intensity,
        env: game.scene.environmentIntensity,
        hemi: game.env.hemi.intensity,
      };
    },
    /**
     * Gameplay muzzle (weapons.json offsets, WeaponSystem.muzzleOffset between them) vs the view
     * model. `visual` is the analytic static pose; `rendered` is the muzzle socket node's
     * camera-space position after the real viewModel.update() at rest (springs settled, camera
     * motion 0), i.e. what is drawn. `transition` samples the hip <-> ADS blend in between.
     */
    muzzleConsistency: () => {
      const vm = game.viewModel;
      const def = game.weaponDef;
      const res = {};
      const saved = { ...vm.motion };
      const q = new Quaternion();
      const drawnAt = (ads) => {
        vm.motion.reset();
        vm.update({
          dt: 0,
          alpha: 1,
          orientation: q,
          aspect: vm.camera.aspect,
          ads,
          sprint: 0,
          bobPhase: 0,
          bobAmount: 0,
          lookDX: 0,
          lookDY: 0,
          reload: 0,
          motion: 0,
          sunVisibility: vm.sunVisibility,
        });
        return vm.renderedMuzzleInCameraSpace(new Vector3());
      };
      for (const ads of [0, 1]) {
        const visual = vm.muzzleInCameraSpace(ads);
        const logic = new Vector3().fromArray(ads ? def.muzzleOffsetAds : def.muzzleOffsetHip);
        const rendered = drawnAt(ads);
        res[ads ? 'ads' : 'hip'] = {
          visual: visual.toArray(),
          rendered: rendered ? rendered.toArray() : null,
          logic: logic.toArray(),
          distance: visual.distanceTo(logic),
          renderedDistance: rendered ? rendered.distanceTo(logic) : null,
        };
      }
      res.transition = [0.1, 0.25, 0.5, 0.75, 0.9].map((ads) => {
        const rendered = drawnAt(ads);
        const logic = game.weapon.muzzleOffset(ads);
        return { ads, renderedDistance: rendered ? rendered.distanceTo(logic) : null };
      });
      Object.assign(vm.motion, saved);
      const eye = vm.adsEyeInCameraSpace(1);
      res.adsEye = { cameraSpace: eye.toArray(), distance: eye.length() };
      res.model = vm.assetName;
      return res;
    },
  };
  target.__IV = api;
  return api;
}
