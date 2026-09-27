// Game orchestrator: renderer, environment, level (loaded by id), input, the player camera, the match
// session (authoritative rules through the core Match, combatants, AI), weapons' view models, effects,
// third-person placeholder soldiers, HUD, menus and audio, on the fixed-step loop. Systems talk
// through the event bus. The round logic itself lives in MatchSession (DOM-free).

import { PerspectiveCamera, Quaternion, Scene, Vector3, Box3, Object3D } from 'three';
import defaultBindings from '../data/input_bindings.json' with { type: 'json' };
import movement from '../data/movement.json' with { type: 'json' };
import weaponsData from '../data/weapons.json' with { type: 'json' };
import combat from '../data/combat.json' with { type: 'json' };
import teamsData from '../data/teams.json' with { type: 'json' };
import envCfg from '../data/environment.json' with { type: 'json' };
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
import { DynamicsWorld } from '../physics/dynamicsWorld.js';
import { InputManager } from '../player/input.js';
import { Settings } from '../player/settings.js';
import { BindingsStore } from '../player/bindingsStore.js';
import { Player } from '../player/player.js';
import { lookQuaternion } from '../weapons/weaponSystem.js';
import { ViewModel } from '../weapons/viewModel.js';
import { createPlaceholderPistol } from '../weapons/placeholderPistol.js';
import { ImpactEffects } from '../weapons/impactEffects.js';
import { viewModelPointInCamera } from '../weapons/viewModelMotion.js';
import { DummyView } from './dummyView.js';
import { Hud } from './hud.js';
import { Menus } from './menus.js';
import { AudioSystem } from '../audio/audioSystem.js';
import { MatchSession } from './session.js';
import { CombatantViews } from './combatantViews.js';
import { ZoneView } from './zoneView.js';
import { DEFAULT_LEVEL_ID, listAvailableLevels, loadLevelData } from './levels.js';
import { baseRulesCompiled } from './gameRules.js';
import { createAISystem } from '../ai/index.js';
import { horizontalToVerticalFov, wrapAngle, DEG2RAD } from '../util/math.js';
import { OpticAssets, FirstPersonOptics } from '../weapons/opticView.js';
import { ATTACHMENTS, IRONS, getOpticDef, opticName, resolveOpticId, sensitivityFactor, validateOpticLoadout } from '../weapons/optics.js';
import { ArmoryView } from './armoryView.js';

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
const OPTIC_SIG = { irons: 1, IVH1: 2, IVR1: 3, IVP2: 4, IVS3: 5, IVS6: 6, null: 7 };
const _v = new Vector3();
const _qRecoilRoll = new Quaternion();
const RECOIL_PITCH_LIMIT = 88 * DEG2RAD; // same as Player
const _fwd = new Vector3();
const _up = new Vector3();

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
    this.drawCount = 0;
    this._drawDirty = true;
    this._lastDrawSig = '';
    this.eventLog = [];
    this.data = { bindings: defaultBindings, movement, weapons: weaponsData, combat, teams: teamsData, environment: envCfg, level: null };
    this._eye = new Vector3();
    this._sunVis = 1;
    this._sunCheckTimer = 0;
    this._eyeSky = 1;
    this._ambient = 1;
    this._adapt = 1;
    this.eyeAdaptationEnabled = true;
    this.bounceSunOverride = null;
    this._lastYaw = 0;
    this._lastPitch = 0;
    this._lookSnaps = 0;
    this.weaponAsset = { path: null, loaded: false, placeholder: true, error: null, size: null };
    this.pistolAsset = { path: weaponsData.ivp9_pistol.viewModel.asset, loaded: false, placeholder: true, error: null };
    this.session = null;
    this.player = null;
    this.botCounts = teamsData.defaultBots.slice();
    this.seedOverride = null;
    this.aiEnabled = true;
    this.infiniteAmmo = false;
    // the player's optic kit (loadout screen / armory crate): primary optic + spare optic in the backpack
    this.kit = { ...ATTACHMENTS.loadoutDefault };
    this.opticAssets = null;
    this.fpOptics = null;
    this.armoryView = null;
    this._lastOpticPose = null;
    this.resultsAt = null;
    this.deathCam = null;
    this.levels = [];
    this.levelId = null;
    this.matchCount = 0;
  }

  async init() {
    const events = this.events;
    const storage = safeStorage();
    this.settings = new Settings({ storage });
    this.bindingsStore = new BindingsStore(defaultBindings, storage);
    this.rules = baseRulesCompiled();

    // --- rendering ---
    this.renderer = new Renderer(this.root, { exposure: envCfg.exposure });
    this.baseExposure = envCfg.exposure;
    this.scene = new Scene();
    this.camera = new PerspectiveCamera(50, this.renderer.aspect, 0.05, 2500);
    this.scene.add(this.camera);
    this.env = new Environment(this.renderer.renderer, this.scene, envCfg);
    this.adaptive = new AdaptiveResolution({ min: this.settings.limits.renderScaleMin, max: this.settings.limits.renderScaleMax });
    this._applyRenderScale();
    const bl = envCfg.bakedLighting || {};
    this.bakedLighting = bl.enabled === false ? null : { rays: bl.rays ?? 32, ambientFloor: bl.ambientFloor ?? 0.12, cell: bl.cell ?? 0.5, largeCell: bl.largeCell ?? 1.0 };

    // --- input ---
    this.input = new InputManager(this.bindingsStore.get(), events);
    this.input.attach(this.renderer.canvas);
    this.bindingsStore.onChange((b) => {
      this.input.setBindings(b);
      this.data.bindings = b;
    });
    this.data.bindings = this.bindingsStore.get();

    // --- weapons (view models) ---
    const vmOpts = {
      envTexture: this.scene.environment,
      envIntensity: envCfg.environmentIntensity,
      sunDirection: this.env.sunDirection,
      sunColor: this.env.sun.color,
      sunIntensity: envCfg.sun.intensity,
    };
    this.viewModels = [new ViewModel({ def: weaponsData.iv7_carbine, ...vmOpts }), new ViewModel({ def: weaponsData.ivp9_pistol, ...vmOpts, createPlaceholder: createPlaceholderPistol })];
    this.effects = new ImpactEffects(this.scene, { rng: Math.random, camera: this.camera, world: () => this.world, events, lookupCombatant: (id) => (this.session ? this.session.combatants.get(id) : null) });
    this.combatantViews = new CombatantViews(this.scene, teamsData);
    this.zoneView = new ZoneView(this.scene, teamsData);

    // --- HUD, menus, audio ---
    this.hud = new Hud(this.root, { levelName: '', teamsData });
    this.menus = new Menus(this.root, {
      settings: this.settings,
      bindingsStore: this.bindingsStore,
      levels: () => this.levels,
      currentLevel: () => this.levelId,
      weaponsData,
      teamsData,
      rulesInfo: () => this.rulesInfo(),
      // "Zpět" / Esc from the loadout returns to the title: keep the game state in sync
      onScreen: (screen) => {
        if (screen === 'title' && this.state === 'loadout') this.state = 'start';
      },
      actions: {
        armoryChoose: (k) => this.armoryChoose(k),
        armoryState: () => {
          const pc = this.playerCombatant;
          return pc ? { mounted: pc.optic, spare: pc.spareOptic, kit: { ...pc.opticLoadout.kit } } : null;
        },
        gesture: () => this.audio.unlock(),
        start: () => this.openLoadout(),
        practice: () => this.startPractice(true),
        deploy: (lo) => this.deploy(lo, true),
        resume: () => this.startPlaying(true),
        leave: () => this.toTitle(),
        newRound: () => this.newRound(true),
        changeLoadout: () => this.openLoadout(),
        mainMenu: () => this.toTitle(),
        selectLevel: (id) => this.selectLevel(id),
        quit: () => this.quit(),
      },
    });
    this.menus.show('loading');
    // event-driven sound (src/audio): subscribes to the bus itself; hooks below are unlock / listener / tick / reset
    this.audio = new AudioSystem({
      events: this.events,
      settings: this.settings,
      isPlayer: (id) => !!this.playerCombatant && id === this.playerCombatant.id,
      raycast: (origin, dir, far) => (this.world ? this.world.raycast(origin, dir, far) : null),
      createVector: () => new Vector3(),
      combatantPosition: (id) => {
        const c = this.session ? this.session.combatants.get(id) : null;
        return c ? c.getEye(new Vector3()) : null;
      },
      hasAsset,
    });

    this._wireEvents();
    this.loop = new FixedStepLoop({ step: (dt) => this.tick(dt), render: (alpha, dt) => this.render(alpha, dt) });

    this.levels = await listAvailableLevels();
    await this.loadLevel(DEFAULT_LEVEL_ID);
    await this.loadWeaponAssets();
    await this.loadOpticAssets();
    this._compileAll();
    this.setState('start');
    this.loop.start();
    this.audio.prefetch(); // encoded files only; decoded after the first user gesture
    return this;
  }

  // ------------------------------------------------------------------ accessors (legacy names kept)

  get controller() {
    return this.session && this.session.player ? this.session.player.controller : null;
  }

  get playerCombatant() {
    return this.session ? this.session.player : null;
  }

  /** The player's active weapon system (legacy name `weapon`). */
  get weapon() {
    const p = this.playerCombatant;
    return p ? p.weapon : null;
  }

  get weaponDef() {
    const w = this.weapon;
    return w ? w.def : weaponsData.iv7_carbine;
  }

  get viewModel() {
    const p = this.playerCombatant;
    return this.viewModels[p ? p.activeWeapon : 0];
  }

  get dummies() {
    return this.session ? this.session.dummies : null;
  }

  // ------------------------------------------------------------------ level

  async loadLevel(id) {
    const level = await loadLevelData(id);
    if (this.levelView) {
      this.scene.remove(this.levelView.group);
      this.levelView.group.traverse((o) => {
        if (o.geometry) o.geometry.dispose();
      });
    }
    this.levelId = id;
    this.level = level;
    this.data.level = level;
    this.levelSolids = buildLevelSolids(level);
    this.world = new CollisionWorld(this.levelSolids);
    const maxAniso = this.renderer.renderer.capabilities.getMaxAnisotropy();
    this.levelView = buildTestRangeView(level, this.levelSolids, {
      maxAnisotropy: Math.min(8, maxAniso),
      lighting: this.bakedLighting ? { world: this.world, sunDirection: this.env.sunDirection, ...this.bakedLighting } : null,
    });
    this.scene.add(this.levelView.group);
    if (this.armoryView) this.armoryView.dispose();
    this.armoryView = new ArmoryView(level, teamsData);
    this.scene.add(this.armoryView.group);
    if (this.bakedLighting) {
      const bl = this.bakedLighting;
      this.armoryView.setAmbient((p) => {
        const q = p.clone();
        q.y += 0.5;
        return bl.ambientFloor + (1 - bl.ambientFloor) * probeSkyVisibility(this.world, q, { sunDirection: this.env.sunDirection, rays: bl.rays }).skyVis;
      });
    }
    const levelBounds = new Box3().setFromObject(this.levelView.group);
    this.env.setShadowCasterHeights(levelBounds.min.y, levelBounds.max.y);
    this.dynamics = new DynamicsWorld({ gravity: movement.gravity });
    this.dynamics.addLevelBoxes(listLevelBoxes(level));
    this.hud.setLevelName(level.displayName || id);
    this.hud.setLevelTag(id === 'test_range' ? 'vývojová mapa' : level.tag || 'mapa');
    this.newSession({ mode: 'practice' });
    return { id, displayName: level.displayName, hasMatch: !!level.match };
  }

  async selectLevel(id) {
    if (id === this.levelId) return;
    this.menus.setStatus('Načítám mapu…');
    try {
      await this.loadLevel(id);
      this.menus.setStatus('');
    } catch (err) {
      this.menus.setStatus(`Mapu nelze načíst: ${err.message}`);
    }
    if (this.state === 'start') this.menus.show('title');
  }

  // ------------------------------------------------------------------ session

  nextSeed() {
    if (this.seedOverride !== null) return this.seedOverride >>> 0;
    return (Date.now() ^ Math.floor(Math.random() * 0x7fffffff)) >>> 0;
  }

  /**
   * Creates a new match / practice session on the current level and hooks views to it.
   * @param {object} o { mode, bots, seed, optic, rulesPatch, skipPreRound }
   */
  newSession(o = {}) {
    const mode = o.mode || 'match';
    if (mode === 'match' && !this.level.match) throw new Error(`Mapa ${this.levelId} nemá zápasová data`);
    const seed = o.seed !== undefined ? o.seed >>> 0 : this.nextSeed();
    if (o.optic || o.spare !== undefined) {
      const v = validateOpticLoadout({ optic: o.optic || this.kit.optic, spare: o.spare !== undefined ? o.spare : this.kit.spare === o.optic ? null : this.kit.spare });
      if (v.ok) this.kit = { optic: v.optic, spare: v.spare };
    }
    const s = new MatchSession({
      level: this.level,
      world: this.world,
      movement,
      weaponsData,
      combat,
      teams: teamsData,
      events: this.events,
      createAISystem,
      mode,
      seed,
      bots: mode === 'match' ? (o.bots || this.botCounts) : [0, 0, 0],
      rulesPatch: o.rulesPatch || null,
      loadout: { optic: this.kit.optic, spare: this.kit.spare },
    });
    s.aiEnabled = this.aiEnabled;
    if (this.session) this.session.dispose();
    this.session = s;
    this.matchCount += mode === 'match' ? 1 : 0;
    const pc = s.player;
    if (!this.player) {
      this.player = new Player({ controller: pc.controller, input: this.input, settings: this.settings, events: this.events, mouse: this.data.bindings.mouse });
      this.player.lookScaleFn = () => this._lookScale();
    } else {
      this.player.attachController(pc.controller);
    }
    s.start({ skipPreRound: !!o.skipPreRound });
    if (this.infiniteAmmo) for (const w of pc.weapons) w.state.infiniteAmmo = true;
    // views
    if (this.dummyView) {
      this.scene.remove(this.dummyView.group);
      this.dummyView.group.traverse((o) => {
        if (o.geometry) o.geometry.dispose();
      });
    }
    this.dummyView = new DummyView(s.dummies);
    this.scene.add(this.dummyView.group);
    if (this.bakedLighting) {
      for (const it of this.dummyView.items) {
        const p = it.d.base.clone();
        p.y += 1.1;
        const sky = probeSkyVisibility(this.world, p, { sunDirection: this.env.sunDirection, rays: this.bakedLighting.rays }).skyVis;
        it.mat.envMapIntensity = this.bakedLighting.ambientFloor + (1 - this.bakedLighting.ambientFloor) * sky;
      }
    }
    this.combatantViews.setSession(s);
    this._syncOpticView(true);
    this.effects.clear();
    this.hud.clearTransient();
    this.audio.reset();
    this.resultsAt = null;
    this.deathCam = null;
    this._drawDirty = true;
    this._updatePlaceholderNote();
    return s;
  }

  /** Optic mounted on the player's rifle now ('irons' = none). */
  get optic() {
    const pc = this.playerCombatant;
    return pc ? pc.optic : this.kit.optic;
  }

  /**
   * The player's optic kit (loadout / armory / tests): applied at once to the current combatant and kept for the
   * next sessions. Returns { ok, reason }.
   */
  setPlayerKit({ optic, spare = null }, source = 'loadout') {
    const v = validateOpticLoadout({ optic, spare });
    if (!v.ok) return { ok: false, reason: v.reason };
    this.kit = { optic: v.optic, spare: v.spare };
    const pc = this.playerCombatant;
    const r = pc ? pc.setOpticKit(this.kit, source) : { ok: true };
    this._syncOpticView(true);
    return r;
  }

  /** Legacy name: set the primary optic (spare kept when valid). */
  applyOptic(optic) {
    const o = resolveOpticId(optic) || this.kit.optic;
    return this.setPlayerKit({ optic: o, spare: this.kit.spare === o ? null : this.kit.spare });
  }

  /** First-person rifle shows the optic of the player's loadout (visual optic mid-swap) and aims through it. */
  _syncOpticView(force = false) {
    const pc = this.playerCombatant;
    const vm0 = this.viewModels[0];
    if (!pc) return;
    const L = pc.opticLoadout;
    if (force || this._lastOpticPose !== L.mounted) {
      vm0.setOpticPose(getOpticDef(L.mounted).eyeRifle);
      this._lastOpticPose = L.mounted;
      this._drawDirty = true;
    }
    if (this.fpOptics && (force || this.fpOptics.id !== L.visualOptic)) {
      this.fpOptics.setOptic(L.visualOptic);
      this._drawDirty = true;
    }
  }

  /** Mouse look factor while aiming (magnification scaling + ADS sensitivity setting). */
  _lookScale() {
    const pc = this.playerCombatant;
    if (!pc || !this.renderer) return 1;
    const w = pc.weapon;
    const hipV = horizontalToVerticalFov(this.settings.get('fovDeg'), this.renderer.aspect);
    return sensitivityFactor({
      def: pc.activeWeapon === 0 ? pc.opticDef : null,
      ads: w.state.ads,
      hipVfovDeg: hipV,
      curVfovDeg: this.camera.fov,
      scaling: this.settings.get('adsSensitivityScaling'),
      multiplier: this.settings.get('adsSensitivity'),
    });
  }

  // ------------------------------------------------------------------ armory crate

  /** Opens the armory crate screen (the simulation stops behind it like the pause menu). */
  openArmory(armory) {
    if (this.state !== 'playing') return false;
    const pc = this.playerCombatant;
    if (!pc || !this.session.armoryFor(pc)) return false;
    for (const w of pc.weapons) w.state.releaseInputs();
    this.session.setMenuLock(true);
    this.armoryOpen = armory || this.session.armoryFor(pc);
    this.setState('paused');
    this.menus.setStatus('');
    this.menus.show('armory', { mounted: pc.optic, spare: pc.spareOptic, kit: { ...pc.opticLoadout.kit } });
    this.input.exitPointerLock();
    this.events.emit('armory:opened', { id: pc.id, armoryId: this.armoryOpen.id });
    return true;
  }

  /** Armory screen choice: changes the kit at once (only at the crate). Returns { ok, reason }. */
  armoryChoose({ optic, spare }) {
    const pc = this.playerCombatant;
    if (!pc) return { ok: false, reason: 'no_player' };
    const r = this.session.useArmory(pc, { optic, spare });
    if (r.ok) {
      this.kit = { ...pc.opticLoadout.kit };
      this._syncOpticView(true);
    }
    return r;
  }

  rulesInfo() {
    const r = this.session ? this.session.rules : this.rules;
    const rw = r.weapons;
    const zones = (this.level && this.level.match ? this.level.match.zones : []).map((z) => z.name || z.id);
    return {
      playerTeamName: r.teams[teamsData.playerTeam].name,
      levelName: this.level ? this.level.displayName : '',
      rifleAmmo: `${rw.rifle_iv7.magazineCapacity}+1 nábojů · rezerva ${rw.rifle_iv7.startReserve}`,
      pistolAmmo: `${rw.pistol_p9.magazineCapacity}+1 nábojů · rezerva ${rw.pistol_p9.startReserve}`,
      scoreTarget: r.round.scoreTarget,
      timeLimitS: r.round.timeLimitUs / 1e6,
      pointInterval: String(r.zone.pointIntervalUs / 1e6).replace('.', ','),
      pointsPerAward: r.zone.pointsPerAward,
      respawnDelay: String(r.respawn.delayUs / 1e6).replace('.', ','),
      zoneNames: zones.join(', ') || '—',
    };
  }

  // ------------------------------------------------------------------ flow

  setState(s) {
    this.state = s;
    this.hud.setMode(s);
    this.input.setEnabled(s === 'playing');
    if (s === 'start') this.menus.show('title');
    this.events.emit('game:state', { state: s });
  }

  openLoadout() {
    this.setState('loadout');
    // the loadout screen starts from the current kit (it may have changed at an armory crate)
    this.menus.optic = this.kit.optic;
    this.menus.spare = this.kit.spare;
    this.menus.show('loadout');
  }

  /** Start a match from the loadout screen. */
  deploy(lo = {}, fromGesture = false) {
    this.newSession({ mode: 'match', optic: lo.optic || this.kit.optic, spare: lo.spare !== undefined ? lo.spare : this.kit.spare });
    this.startPlaying(fromGesture);
  }

  startPractice(fromGesture = false) {
    this.newSession({ mode: 'practice' });
    this.startPlaying(fromGesture);
  }

  /** Enter gameplay (resume). fromGesture: request pointer lock (must be inside a user gesture). */
  startPlaying(fromGesture) {
    if (this.state === 'loading' || !this.session) return;
    this.armoryOpen = null;
    this.session.setMenuLock(false);
    this.menus.hide();
    this.setState('playing');
    if (fromGesture) {
      this.input.requestPointerLock();
      this.audio.unlock(); // "Začít" / "Pokračovat" click: create / resume the AudioContext
    }
    try {
      this.renderer.canvas.focus({ preventScroll: true });
    } catch {
      /* ignore */
    }
  }

  pause(reason = 'menu') {
    if (this.state !== 'playing') return;
    for (const w of this.playerCombatant.weapons) w.state.releaseInputs();
    this.session.setMenuLock(true);
    this.setState('paused');
    this.menus.setStatus(reason === 'pointerlock-lost' ? 'Kurzor uvolněn.' : '');
    this.menus.show('paused');
    this.input.exitPointerLock();
  }

  toTitle() {
    this.newSession({ mode: 'practice' });
    this.setState('start');
    this.input.exitPointerLock();
  }

  newRound(fromGesture = false) {
    if (!this.session || this.session.mode !== 'match') return;
    this.session.resetRound();
    this.effects.clear();
    this.hud.clearTransient();
    this.resultsAt = null;
    this.deathCam = null;
    this.startPlaying(fromGesture);
  }

  showResults() {
    const s = this.session;
    const r = s.roundInfo();
    const kills = [0, 0, 0];
    for (const c of s.combatants.all()) kills[c.team] += c.kills;
    const pc = s.player;
    const data = {
      draw: r.draw,
      winnerName: r.winner >= 0 ? r.teams[r.winner].name : '',
      winnerColor: r.winner >= 0 ? r.teams[r.winner].color : '',
      reason: r.endReason,
      scoreTarget: r.scoreTarget,
      teams: r.teams.map((t, i) => ({ name: t.name, color: t.color, score: r.scores[i], kills: kills[i], own: i === teamsData.playerTeam })),
      player: pc ? { kills: pc.kills, deaths: pc.participant.deaths } : null,
    };
    this.resultsAt = null;
    this.lastResults = data;
    this.setState('results');
    this.menus.show('results', data);
    this.input.exitPointerLock();
  }

  /** "Ukončit": a web page cannot close the user's tab reliably, so the cursor is freed and the player told how to quit. */
  quit() {
    this.input.exitPointerLock();
    this.menus.show('quit');
  }

  // ------------------------------------------------------------------ events

  _wireEvents() {
    const ev = this.events;
    const log = (type, payload) => {
      this.eventLog.push({ type, tick: this.simTicks, ...payload });
      if (this.eventLog.length > 300) this.eventLog.shift();
    };
    const isPlayer = (id) => this.playerCombatant && id === this.playerCombatant.id;
    ev.on('input:menu', (p) => {
      log('menu', { reason: p.reason });
      if (this.state === 'playing') this.pause(p.reason);
      else if (this.menus.open && p.reason === 'key') this.menus.back();
    });
    ev.on('input:fallback', (p) => {
      log('pointer-fallback', { reason: p.reason });
      if (this.state === 'playing') this.hud.showNotice('Ukazatel myši nelze uzamknout — rozhlížej se tažením myši se stisknutým tlačítkem.', 6);
    });
    ev.on('input:released', (p) => {
      if (this.playerCombatant) for (const w of this.playerCombatant.weapons) w.state.releaseInputs();
      log('input-released', { reason: p.reason });
    });
    ev.on('input:toggleFps', () => this.settings.set('showFps', !this.settings.get('showFps')));
    ev.on('weapon:fired', (p) => {
      if (isPlayer(p.shooterId)) {
        this.viewModel.onShot(p);
        this.effects.onShot(p.muzzle, p, this.viewModel);
      } else {
        this.combatantViews.onShot(p.shooterId, p.muzzle);
        this.effects.onShot(p.muzzle, p, null);
      }
    });
    ev.on('weapon:hit', (p) => {
      this.effects.onHit(p.hit);
      const byPlayer = isPlayer(p.shooterId);
      if (byPlayer) {
        const d = p.damage;
        if (p.hit.kind === 'dummy') this.hud.showHitmarker(!!(d && d.killed), combat.hud.hitmarkerSeconds);
        else if (p.hit.kind === 'combatant' && d && (d.result === 'applied' || d.result === 'killed')) {
          this.hud.showHitmarker(d.result === 'killed', combat.hud.hitmarkerSeconds);
        }
      }
      log('hit', { shooter: p.shooterId, target: p.hit.targetKey, part: p.part || null, blocked: p.blocked, result: p.damage ? p.damage.result || null : null });
    });
    ev.on('combatant:damaged', (p) => {
      if (isPlayer(p.victimId) && p.attackerPosition) {
        const pc = this.playerCombatant;
        const dx = p.attackerPosition.x - pc.position.x;
        const dz = p.attackerPosition.z - pc.position.z;
        this.hud.showDamage(this._relativeAngle(dx, dz, this.player.yaw), combat.hud.damageIndicatorSeconds);
      }
      log('damaged', { victim: p.victimId, attacker: p.attackerId, amount: p.amount, part: p.part });
    });
    ev.on('combatant:friendly_fire_blocked', (p) => log('ff-blocked', { victim: p.victimId, attacker: p.attackerId }));
    ev.on('combatant:died', (p) => {
      if (isPlayer(p.victimId)) {
        const s = this.session;
        const k = p.attackerId ? s.combatants.get(p.attackerId) : null;
        this.deathCam = { t: 0, killerId: p.attackerId, killerName: k ? k.name : null, killerTeam: k ? k.team : -1, weapon: p.weaponId ? weaponsData[p.weaponId].shortName : null, forced: !p.attackerId, from: this.camera.position.clone() };
        for (const w of this.playerCombatant.weapons) w.state.releaseInputs();
      }
      log('died', { victim: p.victimId, attacker: p.attackerId });
    });
    ev.on('combatant:spawned', (p) => {
      if (isPlayer(p.id)) {
        this.player.teleport(p.position, p.yaw / DEG2RAD, 0);
        this.deathCam = null;
        this._drawDirty = true;
      }
      log('spawned', { id: p.id, pos: p.position.toArray().map((v) => Math.round(v * 100) / 100) });
    });
    ev.on('round:started', (p) => {
      const z = this.session.activeZone();
      this.hud.showBanner(`Kolo začalo — obsaď oblast ${z ? z.name : ''}`, 3);
      log('round-started', { zone: p.zoneId });
    });
    ev.on('round:ended', (p) => {
      const r = this.session.roundInfo();
      this.hud.showBanner(p.draw ? 'Konec kola — remíza' : `Konec kola — vítězí ${r.teams[p.winner].name}`, combat.hud.roundEndBannerSeconds);
      this.resultsAt = this.session.simTime + combat.hud.roundEndBannerSeconds;
      log('round-ended', { winner: p.winner, draw: p.draw, reason: p.reason, scores: p.scores });
    });
    ev.on('round:reset', (p) => log('round-reset', { zone: p.zoneId }));
    ev.on('zone:control_changed', (p) => log('zone', { controller: p.controller, status: p.status }));
    ev.on('weapon:reload_started', (p) => log('reload-start', { id: p.id, kind: p.kind }));
    ev.on('weapon:reload_finished', (p) => log('reload-done', { id: p.id, kind: p.kind }));
    ev.on('weapon:reload_interrupted', (p) => log('reload-interrupted', { id: p.id, kind: p.kind }));
    ev.on('player:landed', (p) => log('landed', { speed: Number(p.speed.toFixed(3)) }));
    // optics: the first-person view follows the player's loadout; swap feedback in the HUD
    ev.on('optic:changed', (p) => {
      if (isPlayer(p.id)) this._syncOpticView(true);
      log('optic', { id: p.id, mounted: p.mounted, spare: p.spare, source: p.source });
    });
    ev.on('optic:swap_started', (p) => log('optic-swap', { id: p.id, from: p.from, to: p.to }));
    ev.on('optic:swap_interrupted', (p) => {
      if (isPlayer(p.id)) this.hud.showNotice('Výměna optiky přerušena', 1.6);
      log('optic-swap-interrupted', { id: p.id, reason: p.reason });
    });
    ev.on('optic:swap_rejected', (p) => {
      if (!isPlayer(p.id)) return;
      const txt = { nothing_to_swap: 'V batohu není náhradní optika', primary_not_active: 'Optiku lze měnit jen na pušce', reloading: 'Nejdřív dokonči přebíjení', sprinting: 'Za sprintu optiku nevyměníš' }[p.reason];
      if (txt) this.hud.showNotice(txt, 1.6);
    });
    ev.on('optic:swap_finished', (p) => {
      if (isPlayer(p.id)) this.hud.showNotice(`Nasazeno: ${opticName(p.mounted)}`, 1.6);
    });
    this.settings.onChange((key) => {
      this._drawDirty = true;
      if (key === 'renderScale' || key === 'adaptiveResolution' || key === '*') this._applyRenderScale();
    });
  }

  /** Angle of the horizontal vector (dx, dz) relative to the view yaw: 0 = ahead, + = left. */
  _relativeAngle(dx, dz, yaw) {
    const len = Math.hypot(dx, dz) || 1;
    const vx = dx / len;
    const vz = dz / len;
    const fx = -Math.sin(yaw);
    const fz = -Math.cos(yaw);
    const lx = -Math.cos(yaw);
    const lz = Math.sin(yaw);
    return Math.atan2(vx * lx + vz * lz, vx * fx + vz * fz);
  }

  _applyRenderScale() {
    if (!this.renderer) return;
    if (this.settings.get('adaptiveResolution')) this.renderer.setScale(this.adaptive.scale);
    else this.renderer.setScale(this.settings.get('renderScale'));
  }

  _updatePlaceholderNote() {
    const notes = [];
    if (this.viewModels[0].isPlaceholder) notes.push('puška: provizorní model');
    if (this.viewModels[1].isPlaceholder) notes.push('pistole: provizorní model');
    if (this.session && this.session.mode === 'match') notes.push('postavy: provizorní figuríny');
    this.hud.setPlaceholderNote(notes.length ? notes.join(' · ') : '');
  }

  // ------------------------------------------------------------------ simulation

  tick(dt) {
    if (this.state !== 'playing' || !this.session) {
      if (this.player) this.player.holdInterpolation();
      if (this.weapon) this.weapon.recoil.snapshot();
      for (const vm of this.viewModels) vm.holdSim();
      if (this.dummyView) this.dummyView.hold();
      this.combatantViews.hold();
      this.input.consumeTick();
      return;
    }
    const s = this.session;
    const pc = s.player;
    this.player.beginTick();
    // always the real input: a dead combatant ignores movement, and its weapons still need the real
    // trigger state (core contract), so a trigger held through death does not fire after the respawn
    const cmd = this.player.buildCommand();
    s.tick(dt, { playerCmd: cmd });
    // E at the own team's armory crate: optic kit screen
    if (cmd.interact && this.state === 'playing') {
      const a = s.armoryFor(pc);
      if (a) {
        this.openArmory(a);
        this.input.consumeTick();
        return;
      }
    }
    this.audio.tick(dt);
    // partial recoil recovery (weapons/recoil.js): what the automatic return leaves goes into the look
    for (const w of pc.weapons) {
      const rt = w.recoil.takeLookTransfer();
      if (rt.pitch || rt.yaw) {
        this.player.yaw += rt.yaw;
        this.player.pitch = Math.max(-RECOIL_PITCH_LIMIT, Math.min(RECOIL_PITCH_LIMIT, this.player.pitch + rt.pitch));
      }
    }
    this.player.endTick(dt);
    this.combatantViews.tick(dt);
    this.dummyView.tick(dt);
    this.dynamics.step(dt);
    this.effects.tick(dt);
    this.viewModels.forEach((vm, i) => (i === pc.activeWeapon ? vm.tickSim(dt) : vm.holdSim()));
    this.hud.tick(dt);
    if (this.deathCam) this.deathCam.t += dt;
    this.input.consumeTick();
    this.simTicks++;
    if (this.resultsAt !== null && s.simTime >= this.resultsAt - 1e-9) this.showResults();
  }

  // ------------------------------------------------------------------ rendering

  render(alpha, frameDt) {
    const r = this.renderer;
    if (r.contextLost || !this.session) return;
    r.resize();
    const s = this.session;
    const pc = s.player;
    const alive = pc.alive;
    if (this.state === 'playing') this.player.applyLookInput();
    let lookDX = wrapAngle(this.player.yaw - this._lastYaw);
    let lookDY = this.player.pitch - this._lastPitch;
    this._lastYaw = this.player.yaw;
    this._lastPitch = this.player.pitch;
    let snapped = false;
    if (this.player.lookSnaps !== this._lookSnaps) {
      this._lookSnaps = this.player.lookSnaps;
      lookDX = 0;
      lookDY = 0;
      snapped = true;
    }
    const w = pc.weapon;
    const eye = this.player.getRenderEye(alpha, this._eye);
    const bob = this.player.getRenderBob(alpha);
    const rec = w.recoil.interpolated(alpha);
    let camYaw = this.player.yaw + rec.yaw;
    let camPitch = this.player.pitch + rec.pitch;
    const q = lookQuaternion(camYaw, camPitch, this.camera.quaternion);
    // visual camera roll from recoil: about the view axis, so the crosshair keeps pointing at the aim
    if (rec.roll) q.multiply(_qRecoilRoll.setFromAxisAngle(_v.set(0, 0, 1), rec.roll * this.settings.get('cameraMotion')));
    // camera feel (strafe roll, traversal arc, landing / stair nod; visual only, src/player/cameraEffects.js)
    if (alive) this.player.applyCameraEffects(q, alpha);
    if (!alive && this.deathCam) {
      // short death view: the camera sinks to the ground and tilts
      const dc = this.deathCam;
      const u = Math.min(1, (dc.t + alpha / 60) / combat.death.deathCamTime);
      const e = smooth(u);
      const feet = pc.position;
      eye.set(feet.x, feet.y + combat.death.deathCamHeight + (1 - e) * (pc.controller.standEyeHeight - combat.death.deathCamHeight), feet.z);
      camPitch = this.player.pitch * (1 - e) - 0.25 * e;
      lookQuaternion(camYaw, camPitch, q);
      _v.set(0, 0, 1);
      this.camera.quaternion.multiply(this.camera.quaternion.clone().setFromAxisAngle(_v, 0.35 * e));
    }
    this.camera.position.copy(eye);
    const ws = w.state;
    const adsEase = smooth(ws.ads);
    // ADS field of view: per optic on the rifle (1x sights: no zoom; 6x: the overlay's documented vertical FOV
    // once scoped in), the weapon's own value otherwise (pistol)
    this._syncOpticView();
    const primary = pc.activeWeapon === 0;
    const odef = primary ? pc.opticDef : null;
    const fovMult = odef ? odef.worldFovMultiplier : w.def.adsFovMultiplier || 1;
    const hfov = this.settings.get('fovDeg') * (1 + (fovMult - 1) * adsEase);
    const scopedFov = !!(odef && odef.mode === 'fullscreen' && odef.overlay && this.fpOptics && this.fpOptics.id === odef.id && ws.ads >= odef.scopeIn && alive);
    this.camera.fov = scopedFov ? odef.overlay.vfovDeg : horizontalToVerticalFov(hfov, r.aspect);
    this.camera.aspect = r.aspect;
    this.camera.updateProjectionMatrix();
    this.camera.updateMatrixWorld();
    this.env.follow(eye, eye);

    this._sunCheckTimer -= frameDt;
    if (this._sunCheckTimer <= 0 || snapped) {
      this._sunCheckTimer = 0.1;
      this._sunVis = this.world.raycast(eye, this.env.sunDirection, 400) ? 0 : 1;
      if (this.bakedLighting) this._eyeSky = probeSkyVisibility(this.world, eye, { sunDirection: this.env.sunDirection, rays: 16 }).skyVis;
    }
    const vm = this.viewModel;
    if (this.bakedLighting) {
      this._ambient = snapped ? this._eyeSky : this._ambient + (this._eyeSky - this._ambient) * (1 - Math.exp(-6 * frameDt));
      const f = this.bakedLighting.ambientFloor;
      vm.setAmbientScale(f + (1 - f) * this._ambient);
      updateBakedSun(this.levelView.lighting.uniforms, this.env.sun.color, this.bounceSunOverride ?? this.env.sun.intensity);
    }
    this._updateEyeAdaptation(frameDt, snapped);

    const sw = pc.switchTimer > 0 ? pc.switchTimer / Math.max(1e-3, w.def.switchTime || 0.4) : 0;
    const swapLower = this._opticSwapLower(pc);
    vm.update({
      dt: frameDt,
      alpha,
      orientation: q,
      aspect: r.aspect,
      ads: ws.ads,
      sprint: pc.controller.sprinting ? 1 : 0,
      bobPhase: bob.phase,
      bobAmount: bob.amount,
      lookDX,
      lookDY,
      reload: ws.state === 'reloading' || ws.state === 'chambering' ? ws.reloadProgress : 0,
      lower: Math.max(sw, this.player.getWeaponLower(alpha), swapLower), // weapon switch, vault / mantle, optic swap
      motion: this.settings.get('cameraMotion'),
      sunVisibility: this._sunVis,
    });
    const showVm = alive && (this.state === 'playing' || this.state === 'paused');
    if (this.fpOptics) this.fpOptics.update({ worldCamera: this.camera, ads: ws.ads, primary, renderer: r.renderer, vmVisible: showVm });
    this.dummyView.update(alpha);
    this.combatantViews.update(alpha);
    const ri = s.roundInfo();
    this.zoneView.update(ri.zone, ri.status, ri.controller, s.simTime);

    if (this.drawEnabled) {
      const sig = this._drawSignature();
      const idle = this.state !== 'playing' && !this._drawDirty && sig === this._lastDrawSig;
      if (!idle) {
        const gl = r.renderer;
        gl.clear();
        gl.render(this.scene, this.camera);
        const fo = this.fpOptics;
        if (showVm && primary && fo && fo.scoped) {
          // 6x scoped: overlay + reticle over the zoomed world, no view model
          fo.renderScope(gl);
        } else if (showVm) {
          if (primary && fo && fo.pipActive) fo.renderPip(gl, this.scene); // eyepiece image (2x / 3x / 6x raising)
          gl.clearDepth();
          gl.render(vm.scene, vm.camera);
        }
        this._lastDrawSig = sig;
        this._drawDirty = false;
        this.drawCount++;
      }
    }

    // HUD from real state
    const part = pc.participant;
    let zoneVec = null;
    if (ri.zone) {
      const dx = ri.zone.center[0] - pc.position.x;
      const dz = ri.zone.center[2] - pc.position.z;
      zoneVec = { distance: Math.hypot(dx, dz), angle: this._relativeAngle(dx, dz, this.player.yaw), inside: s.isInZone(pc.position) };
    }
    let death = null;
    if (!alive && part) {
      const dc = this.deathCam || {};
      death = {
        killerName: dc.killerName || null,
        killerColor: dc.killerTeam >= 0 ? teamsData.teams[dc.killerTeam].color : null,
        weapon: dc.weapon || null,
        forced: !!dc.forced,
        respawnIn: part.respawnInUs / 1e6,
        waiting: part.state === 'respawning',
      };
    }
    const L = pc.opticLoadout;
    const weaponLabel = pc.activeWeapon === 0 ? `${w.def.displayName} · ${opticName(pc.optic).toLowerCase()}` : w.def.displayName;
    const armory = alive && this.state === 'playing' ? s.armoryFor(pc) : null;
    const opticHud = {
      spare: opticName(pc.spareOptic),
      hasSpare: pc.spareOptic !== null,
      swapping: L.swapping,
      progress: L.progress,
      swapKey: this._keyLabel('swapOptic'),
      armoryPrompt: armory ? `${this._keyLabel('interact')} — zbrojní bedna (změna optiky)` : '',
    };
    this.hud.update(frameDt, {
      weapon: ws.getState(),
      weaponLabel,
      player: pc.controller,
      alive,
      health: pc.health,
      maxHealth: s.rules.combat.maxHealth,
      fps: this.loop.fps,
      showFps: this.settings.get('showFps'),
      sprinting: pc.controller.sprinting,
      round: ri,
      zoneVec,
      ownTeam: pc.team,
      killFeed: s.killFeed,
      death,
      allies: this._allyMarkers(pc),
      optic: opticHud,
    });

    // audio listener on the camera
    _fwd.set(0, 0, -1).applyQuaternion(this.camera.quaternion);
    _up.set(0, 1, 0).applyQuaternion(this.camera.quaternion);
    this.audio.setListener(this.camera.position, _fwd, _up);

    if (this.settings.get('adaptiveResolution') && !this.loop.frozen && this.state === 'playing') {
      // no resolution change while aiming (a scale step would be visible in the sight picture)
      const sc = this.adaptive.update(this.loop.lastFrameMs, frameDt, { hold: alive && ws.ads > 0.01 });
      if (sc !== null) r.setScale(sc);
    }
    this.frameCount++;
  }

  /** Screen positions of living allies (through walls; allies only). */
  _allyMarkers(pc) {
    const out = [];
    const canvas = this.renderer.canvas;
    const wpx = canvas.clientWidth || 960;
    const hpx = canvas.clientHeight || 540;
    for (const c of this.session.combatants.byTeam(pc.team)) {
      if (c === pc || !c.alive) continue;
      const p = c.controller.position;
      _v.set(p.x, p.y + c.controller.height + 0.3, p.z);
      const dist = _v.distanceTo(this.camera.position);
      _v.project(this.camera);
      const onScreen = _v.z > -1 && _v.z < 1 && Math.abs(_v.x) <= 1.05 && Math.abs(_v.y) <= 1.05;
      out.push({
        id: c.id,
        name: c.name,
        color: teamsData.teams[c.team].color,
        distance: dist,
        onScreen,
        x: ((_v.x + 1) / 2) * wpx,
        y: ((1 - _v.y) / 2) * hpx,
      });
    }
    return out;
  }

  _drawSignature() {
    const r = this.renderer.renderer;
    const vm = this.viewModel;
    const parts = [
      ...this.camera.matrixWorld.elements,
      ...this.camera.projectionMatrix.elements,
      ...vm.holder.position.toArray(),
      vm.holder.rotation.x,
      vm.holder.rotation.y,
      vm.holder.rotation.z,
      r.toneMappingExposure,
      vm.ambientScale,
      vm.sun.intensity,
      vm.flash.visible ? 1 : 0,
      this.fpOptics ? (this.fpOptics.scoped ? 2 : 0) + (this.fpOptics.pipActive ? 4 : 0) + this.fpOptics.rtSize : 0,
      this.fpOptics ? OPTIC_SIG[this.fpOptics.id] ?? 9 : 0,
      r.domElement.width,
      r.domElement.height,
      this.env.sun.intensity,
    ];
    let s = '';
    for (const v of parts) s += `${Math.round(v * 1e5)},`;
    return s;
  }

  /** Weapon lowering 0..1 of the player's optic swap (hook for the arms animation: lower -> swap -> raise). */
  _opticSwapLower(pc) {
    const L = pc.opticLoadout;
    const P = L.rules.phases;
    if (L.swap) {
      const u = L.progress;
      if (u < P.detach) return smooth(Math.min(1, u / Math.max(1e-3, P.detach)));
      if (u < P.raise) return 1;
      return 1 - smooth(Math.min(1, (u - P.raise) / Math.max(1e-3, 1 - P.raise)));
    }
    if (L.raise > 0) return smooth(Math.min(1, L.raise / Math.max(1e-3, L.rules.interruptRaiseS || 0.3)));
    return 0;
  }

  _keyLabel(action) {
    const codes = (this.data.bindings.actions && this.data.bindings.actions[action]) || [];
    const c = codes[0];
    if (!c) return '?';
    if (c.startsWith('Key')) return c.slice(3);
    if (c.startsWith('Digit')) return c.slice(5);
    return c;
  }

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

  async loadWeaponAssets() {
    await this.loadWeaponAsset();
    await this.loadPistolAsset();
    this._updatePlaceholderNote();
  }

  /** Optic set (LOD0 first person, LOD1 third person, reticle SDFs, 6x overlay), then the first-person mount. */
  async loadOpticAssets() {
    const maxAniso = Math.min(8, this.renderer.renderer.capabilities.getMaxAnisotropy());
    this.opticAssets = new OpticAssets({ maxAnisotropy: maxAniso });
    try {
      await this.opticAssets.loadAll();
    } catch (err) {
      console.warn('[optics] loading failed:', err && err.message);
    }
    this.fpOptics = new FirstPersonOptics({ viewModel: this.viewModels[0], assets: this.opticAssets });
    this.fpOptics.onRifleModel();
    this.combatantViews.setOpticAssets(this.opticAssets);
    this._syncOpticView(true);
  }

  /** Precompiles every shader the game can need (world, view models, each optic, the 6x overlay): no first-ADS hitch. */
  _compileAll() {
    const gl = this.renderer.renderer;
    try {
      gl.compile(this.scene, this.camera);
      for (const vm of this.viewModels) gl.compile(vm.scene, vm.camera);
      if (this.fpOptics) {
        const keep = this.fpOptics.id;
        for (const id of ['IVH1', 'IVR1', 'IVP2', 'IVS3', 'IVS6']) {
          if (!this.opticAssets.has(id)) continue;
          this.fpOptics.setOptic(id);
          gl.compile(this.viewModels[0].scene, this.viewModels[0].camera);
        }
        for (const m of this.fpOptics.compileTargets()) {
          this.fpOptics.overlayQuad.material = m;
          gl.compile(this.fpOptics.overlayScene, this.fpOptics.overlayCamera);
        }
        this.fpOptics.setOptic(keep);
      }
    } catch {
      /* compile is an optimisation only */
    }
  }

  /** Loads a GLB and prepares it for the view-model pass (glass fix, sockets). */
  async _loadViewModelGlb(path, sockets) {
    const gltf = await loadGLTF(path);
    const obj = gltf.scene;
    obj.updateMatrixWorld(true);
    let muzzle = obj.getObjectByName(sockets.muzzle || 'socket_muzzle') || null;
    const adsEye = obj.getObjectByName(sockets.adsEye || 'socket_ads') || null;
    let glassFixed = 0;
    obj.traverse((o) => {
      if (!muzzle && !o.isMesh && /muzzle/i.test(o.name)) muzzle = o;
      if (o.isMesh) {
        o.castShadow = false;
        o.receiveShadow = false;
        o.frustumCulled = false;
        // KHR_materials_transmission needs a transmission pass that samples the same scene; the view
        // model pass contains only the weapon, so the lens would render black -> thin transparent glass
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
    return { obj, muzzle, adsEye, box, size, glassFixed };
  }

  async loadWeaponAsset() {
    const def = weaponsData.iv7_carbine;
    const path = def.viewModel.asset;
    this.weaponAsset.path = path;
    if (!hasAsset(path)) return;
    try {
      const { obj, muzzle, adsEye, box, size, glassFixed } = await this._loadViewModelGlb(path, def.viewModel.sockets || {});
      const vm0 = this.viewModels[0];
      vm0.setModel(obj, muzzle, { placeholder: false, name: path.split('/').pop(), adsEye });
      const maxAniso = Math.min(8, this.renderer.renderer.capabilities.getMaxAnisotropy());
      obj.traverse((o) => {
        if (!o.isMesh) return;
        for (const m of Array.isArray(o.material) ? o.material : [o.material]) {
          for (const k of ['map', 'normalMap', 'roughnessMap', 'metalnessMap', 'aoMap']) if (m && m[k]) m[k].anisotropy = maxAniso;
        }
      });
      if (this.fpOptics) this.fpOptics.onRifleModel();
      this._syncOpticView(true);
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
        muzzleLocal: vm0.muzzleLocal.toArray(),
        adsEyeLocal: vm0.adsEyeLocal.toArray(),
        glassMaterialsAdjusted: glassFixed,
        textures: (() => {
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
    } catch (err) {
      console.warn('[assets] weapon GLB failed to load, using placeholder:', err && err.message);
      this.weaponAsset.error = String(err && err.message);
    }
  }

  /**
   * IV-P9 pistol GLB (if present in the build): replaces the placeholder. ADS position and the gameplay
   * muzzle are derived from its sockets, so shots leave from the drawn muzzle.
   */
  async loadPistolAsset() {
    const def = weaponsData.ivp9_pistol;
    const path = def.viewModel.asset;
    if (!hasAsset(path)) return;
    try {
      const { obj, muzzle, adsEye } = await this._loadViewModelGlb(path, def.viewModel.sockets || {});
      const vm1 = this.viewModels[1];
      vm1.setModel(obj, muzzle, { placeholder: false, name: path.split('/').pop(), adsEye });
      const m = vm1.muzzleLocal;
      def.viewModel.muzzleLocal = [m.x, m.y, m.z];
      if (adsEye) {
        const a = vm1.adsEyeLocal;
        def.viewModel.adsEyeLocal = [a.x, a.y, a.z];
        def.viewModel.adsPosition = [-a.z, -a.y, a.x];
        vm1.adsPos.fromArray(def.viewModel.adsPosition);
      }
      def.muzzleOffsetHip = viewModelPointInCamera(def.viewModel, def.viewModel.muzzleLocal, 0).toArray();
      def.muzzleOffsetAds = viewModelPointInCamera(def.viewModel, def.viewModel.muzzleLocal, 1).toArray();
      if (this.session) for (const c of this.session.combatants.all()) c.weapons[1].setViewModel(def.viewModel, def.muzzleOffsetHip, def.muzzleOffsetAds);
      this.pistolAsset = { path, loaded: true, placeholder: false, error: null, muzzleLocal: def.viewModel.muzzleLocal, adsEyeLocal: def.viewModel.adsEyeLocal };
      this._drawDirty = true;
    } catch (err) {
      console.warn('[assets] pistol GLB failed to load, using placeholder:', err && err.message);
      this.pistolAsset.error = String(err && err.message);
    }
  }

  // ------------------------------------------------------------------ state for tests / debug

  getState() {
    const s = this.session;
    const p = this.player ? this.player.getState() : null;
    const pc = this.playerCombatant;
    return {
      state: this.state,
      menuScreen: this.menus.screen,
      frame: this.frameCount,
      draws: this.drawCount,
      ticks: this.loop.ticks,
      simTicks: this.simTicks,
      simTime: this.loop.simTime,
      fps: this.loop.fps,
      frozen: this.loop.frozen,
      timeScale: this.loop.timeScale,
      alpha: this.loop.alpha,
      levelId: this.levelId,
      mode: s ? s.mode : null,
      player: p ? { ...p, alive: pc.alive, health: pc.health, lifeState: pc.lifeState, activeWeapon: pc.activeWeapon, id: pc.id, team: pc.team } : null,
      weapon: this.weapon ? this.weapon.getState() : null,
      weapons: pc ? pc.weapons.map((w) => w.getState()) : [],
      optic: this.optic,
      opticSpare: pc ? pc.spareOptic : this.kit.spare,
      opticKit: { ...this.kit },
      opticLoadout: pc ? pc.opticLoadout.getState() : null,
      opticView: this.fpOptics ? this.fpOptics.getDebug() : null,
      opticAssets: this.opticAssets ? { loaded: [...this.opticAssets.items.keys()], errors: this.opticAssets.errors.slice() } : null,
      armory: pc && this.session ? (this.session.armoryFor(pc) || {}).id || null : null,
      lookScale: this.player ? this.player.lastLookScale : 1,
      weaponAsset: { ...this.weaponAsset, viewModel: this.viewModels[0].assetName, isPlaceholder: this.viewModels[0].isPlaceholder, hiddenNodes: this.viewModels[0].hiddenCount || 0 },
      pistolAsset: { ...this.pistolAsset, viewModel: this.viewModels[1].assetName, isPlaceholder: this.viewModels[1].isPlaceholder },
      viewModel: {
        kick: this.viewModel.kick,
        kickRot: this.viewModel.kickRot,
        swayX: this.viewModel.motion.swayX,
        swayY: this.viewModel.motion.swayY,
        holderPosition: this.viewModel.holder.position.toArray(),
        holderRotation: [this.viewModel.holder.rotation.x, this.viewModel.holder.rotation.y, this.viewModel.holder.rotation.z],
        finite: [this.viewModel.holder.position.x, this.viewModel.holder.position.y, this.viewModel.holder.position.z].every(Number.isFinite),
        name: this.viewModel.assetName,
      },
      input: this.input.getState(),
      dummies: this.dummies ? this.dummies.getState() : [],
      dynamics: this.dynamics.getState(),
      render: this.renderer.getInfo(),
      camera: {
        position: this.camera.position.toArray(),
        fovVertical: this.camera.fov,
        fovHorizontalSetting: this.settings.get('fovDeg'),
      },
      settings: { ...this.settings.values },
      bindings: this.bindingsStore.get().actions,
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
      round: s ? s.roundInfo() : null,
      audio: this.audio.getState(),
      events: this.eventLog.slice(-50),
    };
  }
}
