// window.__IV — test and debugging interface. Reads state and drives time/input for automated
// tests. The game never calls into this module; removing it does not change gameplay.
// Functions marked "test only" change the simulation in ways a player cannot (force kill, placement,
// seeds, bot counts); they exist so tests can build exact situations.

import { Quaternion, Vector3 } from 'three';
import { DEG2RAD } from '../util/math.js';
import { MatchTelemetry } from './matchTelemetry.js';

export function installTestApi(game, target = window) {
  let renderOnStep = false;
  const S = () => game.session;
  const api = {
    version: 2,
    ready: true,
    /** Direct access for interactive debugging only (tests must not rely on internals). */
    _game: game,

    getState: () => game.getState(),
    /** Audio counters (sounds started per key / category, active voices, context state, decode status). */
    getAudio: () => game.audio.getState(),
    getLevelInfo: () => ({
      id: game.data.level.id,
      displayName: game.data.level.displayName,
      markers: game.data.level.markers,
      dummies: game.data.level.dummies || [],
      signs: game.data.level.signs || [],
      match: game.data.level.match || null,
    }),
    getConfig: () => ({ movement: game.data.movement, weapon: game.weaponDef, bindings: game.data.bindings, rules: S() ? S().rules : game.rules, combat: game.data.combat }),

    /**
     * Enter the playing state without a user gesture (no pointer lock) in FREE PRACTICE on the current
     * level (no bots, no round clock). Resumes a paused practice session; any other session is replaced.
     */
    startGame: () => {
      if (!S() || S().mode !== 'practice') game.newSession({ mode: 'practice' });
      game.startPlaying(false);
      return game.state;
    },
    openMenu: () => game.pause('test'),

    // ---- match flow (test only shortcuts; the UI path is title -> loadout -> "Do boje") ----
    /**
     * Starts a full match without menus. opts: { level, bots:[t0,t1,t2], seed, optic, skipPreRound,
     * rules (JSON merge patch over rules.json, test only), ai (bool) }
     */
    startMatch: async (opts = {}) => {
      if (opts.level && opts.level !== game.levelId) await game.loadLevel(opts.level);
      if (opts.ai !== undefined) game.aiEnabled = !!opts.ai;
      if (opts.bots) game.botCounts = opts.bots.slice();
      game.newSession({ mode: 'match', bots: opts.bots, seed: opts.seed, optic: opts.optic, spare: opts.spare, rulesPatch: opts.rules || null, skipPreRound: !!opts.skipPreRound });
      game.startPlaying(false);
      return api.getMatchState();
    },
    /** Loads a level by id (src/data/<id>.json) and puts a practice session on it. */
    loadLevel: async (id) => game.loadLevel(id),
    listLevels: () => game.levels.slice(),
    /** Bots per team [t0 (besides the player), t1, t2]; restarts the match with the new roster. */
    setBotCount: (counts) => {
      game.botCounts = counts.slice();
      if (S() && S().mode === 'match') {
        game.newSession({ mode: 'match', bots: game.botCounts, seed: S().seed });
        if (game.state === 'playing' || game.state === 'paused') game.startPlaying(false);
      }
      return api.listCombatants().map((c) => ({ id: c.id, team: c.team }));
    },
    /** Deterministic seed for the next sessions (null = random per match). */
    setSeed: (seed) => {
      game.seedOverride = seed === null ? null : seed >>> 0;
      return game.seedOverride;
    },
    setAIEnabled: (on) => {
      game.aiEnabled = !!on;
      if (S()) S().aiEnabled = game.aiEnabled;
      return game.aiEnabled;
    },
    getAIDebug: () => (S() ? S().ai.getDebug() : null),
    /**
     * Match telemetry (src/debug/matchTelemetry.js) on the current session: scores over time, zone control,
     * kills / deaths / respawns, shots / hits / reloads, stuck episodes, per-tick jumps (teleport check), cost.
     * telemetryStart(opts) replaces a running one; telemetryReport() returns the report; telemetryStop().
     */
    telemetryStart: (opts = {}) => {
      if (api._telemetry) api._telemetry.detach();
      api._telemetry = S() ? new MatchTelemetry(S(), game.events, opts).attach() : null;
      return !!api._telemetry;
    },
    telemetryReport: () => (api._telemetry ? api._telemetry.report() : null),
    telemetryStop: () => {
      if (api._telemetry) api._telemetry.detach();
      api._telemetry = null;
      return true;
    },
    newRound: () => {
      game.newRound(false);
      return api.getMatchState();
    },
    toTitle: () => game.toTitle(),
    openLoadout: () => game.openLoadout(),
    deploy: (optic, spare) => {
      game.deploy({ optic, spare }, false);
      return game.state;
    },

    // ---- optics (test / debug) ----
    /** Test only: the player's optic kit without menus ({ optic, spare }); returns { ok, reason }. */
    setOptic: (optic, spare = undefined) => {
      const pc = game.playerCombatant;
      const sp = spare === undefined ? (pc ? pc.spareOptic : game.kit.spare) : spare;
      const r = game.setPlayerKit({ optic, spare: sp === optic ? null : sp });
      game._drawDirty = true;
      return r;
    },
    /** Opens the armory screen if the player stands at the own team's crate (as E would). */
    openArmory: () => game.openArmory(),
    /** Armory screen choice (only valid at the crate): returns { ok, reason }. */
    armoryChoose: (optic, spare = null) => game.armoryChoose({ optic, spare }),
    /**
     * Optic state for tests: where the drawn reticle's centre is on screen (the optic's sight axis projected with
     * the world camera; 6x: the screen centre; PiP: the ocular disc centre and the PiP camera axis) vs the hitscan
     * direction of the next round (aim incl. recoil), plus the view state (eyebox, render target, scope).
     */
    getOpticDebug: () => {
      const vm = game.viewModels[0];
      const fo = game.fpOptics;
      const cam = game.camera;
      const cv = game.renderer.renderer.domElement;
      const W = cv.width;
      const H = cv.height;
      cam.updateMatrixWorld(true);
      const proj = (dirWorld) => {
        const p = cam.position.clone().addScaledVector(dirWorld, 1000).project(cam);
        return [((p.x + 1) / 2) * W, ((1 - p.y) / 2) * H];
      };
      const q = vm.holder.quaternion.clone().multiply(vm.modelRoot.quaternion);
      const axisCam = new Vector3(1, 0, 0).applyQuaternion(q);
      const axisWorld = axisCam.clone().applyQuaternion(cam.quaternion);
      const aim = game.weapon.aimDirection(game.player.yaw, game.player.pitch, new Vector3());
      const pc = game.playerCombatant;
      const out = {
        canvas: [W, H],
        optic: pc ? pc.optic : null,
        visual: fo ? fo.id : null,
        mode: fo ? fo.mode : null,
        ads: game.weapon.state.ads,
        cameraFov: cam.fov,
        aimPx: proj(aim),
        axisPx: proj(axisWorld),
        axisCam: axisCam.toArray(),
        aimCamAngleDeg: (aim.angleTo(new Vector3(0, 0, -1).applyQuaternion(cam.quaternion)) * 180) / Math.PI,
        view: fo ? fo.getDebug() : null,
        lookScale: game.player.lastLookScale,
      };
      if (fo && (fo.mode === 'pip' || fo.mode === 'fullscreen')) {
        const f = new Vector3(0, 0, -1).applyQuaternion(fo.pipCamera.quaternion);
        out.pipAxisAimDeg = (f.angleTo(aim) * 180) / Math.PI;
        out.pipAxisPx = proj(f);
        const rec = fo.mounts.get(fo.id);
        if (rec) {
          vm.holder.updateMatrixWorld(true);
          const r = rec.item.sockets.socket_sight_axis_rear.getWorldPosition(new Vector3());
          const p = r.project(vm.camera);
          out.ocularPx = [((p.x + 1) / 2) * W, ((1 - p.y) / 2) * H];
        }
      }
      if (fo && fo.scoped) out.scopeCentrePx = [W / 2, H / 2];
      // irons fold: leaf tip (bone-local +Z, 3 cm) in the rifle model frame vs the hinge
      const leaf = [];
      for (const { bone } of fo ? fo.bindQuat.values() : []) {
        bone.updateMatrixWorld(true);
        const hinge = vm.modelRoot.worldToLocal(bone.getWorldPosition(new Vector3()));
        const tip = vm.modelRoot.worldToLocal(bone.localToWorld(new Vector3(0, 0, 0.03)));
        leaf.push({ bone: bone.name, dx: tip.x - hinge.x, dy: tip.y - hinge.y, dz: tip.z - hinge.z });
      }
      out.irons = { folded: fo ? fo.ironsFolded : null, leaf };
      out.hiddenRifleNodes = vm.hiddenCount || 0;
      return out;
    },

    getMatchState: () => {
      const s = S();
      if (!s) return null;
      return {
        gameState: game.state,
        menuScreen: game.menus.screen,
        ...s.roundInfo(),
        tick: s.tickCount,
        simTime: s.simTime,
        occupants: s.zoneOccupants(),
        candidates: s.zoneCandidates(),
        stats: { ...s.stats },
        spawnBlocked: s.combatants.spawnBlocked,
        killFeed: s.killFeed.map((k) => ({ ...k })),
        results: game.lastResults || null,
      };
    },
    listCombatants: () => (S() ? S().listCombatants() : []),
    getSpawnHistory: () => (S() ? S().combatants.spawnHistory.map((r) => ({ ...r })) : []),
    getDeathLog: () => (S() ? S().combatants.deathLog.map((r) => ({ ...r })) : []),
    /** Engine spawn predicate for a point (test / debug). */
    evaluateSpawnPoint: (x, y, z, team) => {
      const r = S().combatants.evaluateSpawnPoint([x, y, z], team, null);
      return { ...r, nearestEnemy: Number.isFinite(r.nearestEnemy) ? r.nearestEnemy : null, nearestBody: Number.isFinite(r.nearestBody) ? r.nearestBody : null };
    },
    /** Test only: kill a combatant through the core (Match.kill). */
    forceKill: (id = 'player') => S().forceKill(id),
    /** Test only: put a combatant at a position (scripted placements, e.g. enemies near a spawn). */
    placeCombatant: (id, x, y, z, yawDeg = null, pitchDeg = 0) => {
      const c = S().combatants.get(id);
      if (!c) throw new Error(`Unknown combatant ${id}`);
      if (c.isPlayer) {
        game.player.teleport(new Vector3(x, y, z), yawDeg, pitchDeg);
      } else {
        c.controller.teleport(new Vector3(x, y, z));
        if (yawDeg !== null) c.yaw = yawDeg * DEG2RAD;
        c.pitch = (pitchDeg || 0) * DEG2RAD;
      }
      return c.getState().position;
    },
    /** Test only: aim a bot at a world point (its next idle command keeps this look). */
    aimCombatant: (id, x, y, z) => {
      const c = S().combatants.get(id);
      const eye = c.getEye(new Vector3());
      const d = new Vector3(x, y, z).sub(eye);
      c.yaw = Math.atan2(-d.x, -d.z);
      c.pitch = Math.atan2(d.y, Math.hypot(d.x, d.z));
      return { yawDeg: c.yaw / DEG2RAD, pitchDeg: c.pitch / DEG2RAD };
    },
    /** Test only: drive a bot for n ticks with a command (AI off), e.g. make it fire. */
    driveBot: (id, cmd, ticks = 1) => {
      const s = S();
      const c = s.combatants.get(id);
      const prev = s.aiEnabled;
      s.aiEnabled = false;
      const orig = s.combatants.stepUndriven.bind(s.combatants);
      s.combatants.stepUndriven = (dt) => {
        if (c.lastStepTick !== s.tickCount) c.applyCommand({ yaw: c.yaw, pitch: c.pitch, ...cmd }, dt);
        orig(dt);
      };
      try {
        game.loop.stepTicks(Math.max(0, ticks | 0), { render: false });
      } finally {
        s.combatants.stepUndriven = orig;
        s.aiEnabled = prev;
      }
      return c.getState();
    },
    getHud: () => game.hud.getState(),
    getMenu: () => ({ open: game.menus.open, screen: game.menus.screen, buttons: [...game.menus.panel.querySelectorAll('button')].map((b) => ({ text: b.textContent, action: b.dataset.action || null, primary: b.classList.contains('iv-btn-primary'), disabled: b.disabled })) }),
    getCombatantViews: () => game.combatantViews.getState(),
    /** Runs the simulation for `seconds` with the WebGL draw disabled (fast), in chunks. */
    simulate: (seconds, { render = false } = {}) => {
      const n = Math.round(seconds * 60);
      const was = game.drawEnabled;
      game.drawEnabled = false;
      try {
        game.loop.stepTicks(n, { render });
      } finally {
        game.drawEnabled = was;
      }
      return game.loop.ticks;
    },
    /** Steps until the match state / game state matches (or maxSeconds passes). Returns seconds simulated. */
    simulateUntil: (cond, maxSeconds = 700) => {
      const was = game.drawEnabled;
      game.drawEnabled = false;
      let t = 0;
      const check = () => {
        const s = S();
        if (cond.gameState && game.state === cond.gameState) return true;
        if (cond.roundState && s.match.round.state === cond.roundState) return true;
        if (cond.playerAlive !== undefined && s.player.alive === cond.playerAlive) return true;
        return false;
      };
      try {
        while (!check() && t < maxSeconds) {
          game.loop.stepTicks(30, { render: false });
          t += 0.5;
        }
      } finally {
        game.drawEnabled = was;
      }
      return t;
    },

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
    setEyeAdaptation: (on) => {
      game.eyeAdaptationEnabled = !!on;
      return game.eyeAdaptationEnabled;
    },
    setDrawEnabled: (on) => {
      game.drawEnabled = !!on;
      return game.drawEnabled;
    },
    renderNow: () => {
      game._drawDirty = true;
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
    /** Test only: vault / mantle on the player's controller on or off (pure step / jump physics checks). */
    setTraversalEnabled: (on) => {
      game.player.ctrl.traversalEnabled = !!on;
      return game.player.ctrl.traversalEnabled;
    },
    /** Starts collecting game bus events with these names (e.g. ['footstep', 'traverse:start']); takeEvents() returns them. */
    watchEvents: (names) => {
      if (api._evOff) api._evOff.forEach((off) => off());
      api._evLog = [];
      api._evOff = names.map((n) =>
        game.events.on(n, (p) => {
          const o = {};
          for (const [k, v] of Object.entries(p || {})) o[k] = v && typeof v.toArray === 'function' ? v.toArray() : v;
          api._evLog.push({ name: n, tick: game.simTicks, ...o });
        }),
      );
      return names.length;
    },
    takeEvents: () => {
      const out = api._evLog || [];
      api._evLog = [];
      return out;
    },

    // ---- weapon helpers (test / debug only) ----
    setInfiniteAmmo: (on) => {
      game.infiniteAmmo = !!on;
      for (const w of game.playerCombatant.weapons) w.state.infiniteAmmo = game.infiniteAmmo;
      return game.infiniteAmmo;
    },
    /** Full magazine + chamber + start reserve through the core (resetToLoadout); interrupts a reload. */
    refillAmmo: () => {
      game.weapon.state.refill();
      return game.weapon.state.getState();
    },
    resetRecoil: () => game.weapon.recoil.reset(),
    /**
     * Weapon feel of the player's active weapon: aim recoil state (recoil.js), rendered view-model kick
     * pose, flash, camera (world vs view-model FOV, rendered look with recoil) and muzzle / impact effects.
     */
    getWeaponFeel: () => {
      const w = game.weapon;
      const vm = game.viewModel;
      const cam = game.camera;
      const f = new Vector3(0, 0, -1).applyQuaternion(cam.quaternion);
      const up = new Vector3(0, 1, 0).applyQuaternion(cam.quaternion);
      const R = 180 / Math.PI;
      const horizRight = new Vector3(-f.z, 0, f.x).normalize();
      return {
        recoil: w.recoil.debug(),
        camera: {
          pitchDeg: Math.asin(Math.max(-1, Math.min(1, f.y))) * R,
          yawDeg: Math.atan2(-f.x, -f.z) * R,
          rollDeg: Math.asin(Math.max(-1, Math.min(1, -up.dot(horizRight)))) * R,
          fovDeg: cam.fov,
          position: cam.position.toArray(),
          forward: f.toArray(),
        },
        viewModel: {
          pose: { ...vm.recoilPose },
          holderPosition: vm.holder.position.toArray(),
          holderQuaternion: vm.holder.quaternion.toArray(),
          fovDeg: vm.camera.fov,
          flashIntensity: vm.flashIntensity,
          flashVisible: vm.flash.visible,
          flashFramesShown: vm.flashTimer.framesShown,
          flashSeq: vm.flashTimer.seq,
          cycleOffset: vm.cycleOffset || 0,
          ejectFromSocket: !!vm.ejectFromSocket,
          ejectLocal: vm.ejectLocal ? vm.ejectLocal.toArray() : null,
          adsEyeCamera: (() => {
            vm.holder.updateMatrixWorld(true);
            const node = vm.adsEyeNode;
            if (node) return vm.camera.worldToLocal(node.getWorldPosition(new Vector3())).toArray();
            return vm.adsEyeLocal.clone().applyQuaternion(vm.modelRoot.quaternion).applyQuaternion(vm.holder.quaternion).add(vm.holder.position).toArray();
          })(),
          barrelCamera: vm.modelDirInCameraSpace(new Vector3(1, 0, 0)).toArray(),
        },
        effects: game.effects.getState(),
      };
    },
    /** Test only: same random recoil draws for repeated runs (active weapon's recoil + view-model kick). */
    setRecoilSeed: (seed) => {
      game.weapon.recoil.rng.setState(seed >>> 0);
      if (game.viewModel.motion._rng) game.viewModel.motion._rng.setState((seed * 7 + 1) >>> 0);
      return seed >>> 0;
    },
    /** Core weapon snapshot of the player's active (or given slot) weapon: the authoritative ammo state. */
    getCoreWeapon: (slot = null) => {
      const pc = game.playerCombatant;
      const w = pc.weapons[slot === null ? pc.activeWeapon : slot];
      return w.state.core.snapshot();
    },

    setSetting: (key, value) => game.settings.set(key, value),
    setLighting: (o = {}) => {
      const r = game.renderer.renderer;
      if (o.exposure !== undefined) {
        game.baseExposure = o.exposure;
        r.toneMappingExposure = o.exposure * game._adapt;
      }
      if (o.sun !== undefined) {
        game.env.sun.intensity = o.sun;
        for (const vm of game.viewModels) vm.sunIntensity = o.sun;
      }
      if (o.env !== undefined) {
        game.scene.environmentIntensity = o.env;
        for (const vm of game.viewModels) {
          vm.baseEnvIntensity = o.env;
          vm.setAmbientScale(vm.ambientScale);
        }
      }
      if (o.hemi !== undefined) game.env.hemi.intensity = o.hemi;
      if (o.bounceSun !== undefined) game.bounceSunOverride = o.bounceSun;
      if (o.fogDensity !== undefined) game.scene.fog.density = o.fogDensity;
      game._drawDirty = true;
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
        // gameplay muzzle of the weapon system (per mounted optic: its eye point sets the ADS pose)
        const logic = game.weapon.muzzleOffset(ads);
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
