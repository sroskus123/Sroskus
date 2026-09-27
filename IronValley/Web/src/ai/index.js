// IRON VALLEY — AI system (Docs/GAMEPLAY_CONTRACTS.md "AI", Docs/AI.md).
//
// createAISystem({ combatants, world, nav, cover, events, match, config }) → {
//   addBot(combatant), removeBot(id),
//   update(dt),     fixed tick: perception ~10 Hz staggered across bots, decisions ~4.5 Hz, steering /
//                   aiming / firing every tick; each living bot is driven with combatant.applyCommand(cmd, dt)
//   getDebug(),     perception, memory, task, target, path, cover, reaction timer ... (window.__IV.ai)
//   reset(),        new round: memory, cover reservations, paths, blocks, team claims cleared
// }
// `world` = WorldQuery (raycastStatic, lineOfSight), `nav` / `cover` = NavService / CoverService or null
// (then loaded from the baked navmesh of config.levelId), `config` = context from the session
// ({ levelId, level, zones, session, rules, tuning? }). AI tunables: Shared/config/ai.json (+ config.tuning).
//
// The AI never reads an enemy's position except through its own line-of-sight rays (vision) and the
// events it may hear/feel (weapon:fired, footstep, combatant:damaged with fromDir only); see memory.js.

import { Vector3 } from 'three';
import { resolveAIConfig } from './config.js';
import { Bot } from './bot.js';
import { Tactics } from './tactics.js';
import { createNavService } from './nav/navService.js';
import { createCoverService } from './cover/coverService.js';
import { NAV_DATA } from './nav/navRegistry.generated.js';
import { installAIDebugApi } from './debug.js';
import { pointInZone } from '../game/zoneShape.js';

export { resolveAIConfig } from './config.js';
export { NavService } from './nav/navService.js';
export { CoverService } from './cover/coverService.js';

// navmeshes of large levels are not bundled (level.nav.external): the game loads public/<nav.file> with the level and
// registers it here before the match session is created (Node tools read it from disk the same way)
const RUNTIME_NAV = new Map();

/** Registers a baked navmesh loaded at runtime (levels with nav.external). */
export function registerNavData(levelId, data) {
  if (levelId && data) RUNTIME_NAV.set(levelId, data);
}

/** Baked navmesh JSON for a level id (bundled at build time or registered at runtime), or null. */
export function navDataForLevel(levelId) {
  if (!levelId) return null;
  return RUNTIME_NAV.get(levelId) || NAV_DATA[levelId] || null;
}

export function createAISystem({ combatants, world, nav = null, cover = null, events = null, match = null, config = {} } = {}) {
  config = config || {};
  const cfg = resolveAIConfig(config.tuning || config.aiTuning || null);
  const level = config.level || null;
  const levelId = config.levelId || (level && level.id) || null;
  const navData = config.navData || (nav && typeof nav.findPath !== 'function' ? nav : null) || navDataForLevel(levelId);
  const navService = nav && typeof nav.findPath === 'function' ? nav : navData ? createNavService(navData) : null;
  const coverService = cover && typeof cover.reserve === 'function' ? cover : createCoverService(navData ? navData.cover : []);
  const session = config.session || null;

  const sys = {
    cfg,
    time: 0,
    tickCount: 0,
    seed: ((session && session.seed) || config.seed || 1) >>> 0,
    combatants,
    world,
    nav: navService,
    cover: coverService,
    match,
    events,
    level,
    levelId,
    bots: [],
    byId: new Map(),
    runSpeed: 3.5,
    metrics: { stuck: [], reactions: [], searches: [], ticks: 0, perceptionUpdates: 0, decisions: 0, maxBotsPerceivedInTick: 0, updateMs: 0, updateMsMax: 0 },
    overlay: null,
    debugEnabled: true,
  };
  sys.tactics = new Tactics(sys);

  // ------------------------------------------------------------------ level knowledge
  // team spawn centres; points may list the zones their row is active for (generated maps): per zone then
  const spawnLists = level && level.match && Array.isArray(level.match.teamSpawns) ? level.match.teamSpawns : [];
  const centreOf = (list) => {
    const c = new Vector3();
    for (const s of list) c.add(new Vector3(s.pos[0], s.pos[1], s.pos[2]));
    return c.divideScalar(Math.max(1, list.length));
  };
  const spawnCenters = spawnLists.map(centreOf);
  const zoneSpawnCenters = new Map();
  sys.enemySpawnCenters = (team) => {
    const z = sys.activeZone ? sys.activeZone() : null;
    if (z && spawnLists.some((l) => l.some((s) => Array.isArray(s.zones)))) {
      if (!zoneSpawnCenters.has(z.id)) {
        zoneSpawnCenters.set(z.id, spawnLists.map((l) => {
          const act = l.filter((s) => !Array.isArray(s.zones) || s.zones.includes(z.id));
          return centreOf(act.length ? act : l);
        }));
      }
      return zoneSpawnCenters.get(z.id).filter((_, t) => t !== team);
    }
    return spawnCenters.filter((_, t) => t !== team);
  };
  // axis-aligned footprint of a level solid by id (box solids), for navmesh blocks around unknown obstacles
  const solidBoxes = new Map();
  if (level && Array.isArray(level.solids)) for (const s of level.solids) if (s && s.id && Array.isArray(s.min) && Array.isArray(s.max)) solidBoxes.set(s.id, { min: s.min, max: s.max });
  sys.solidBox = (id) => (id != null ? solidBoxes.get(id) || null : null);
  // solids of spawn shelters (level flag spawnShelter): their cover points are never used
  sys.shelterSolids = new Set(level && Array.isArray(level.solids) ? level.solids.filter((s) => s.spawnShelter).map((s) => s.id) : []);
  // Is the static obstacle a stuck bot ran into unknown to the navmesh? True only for level solids flagged
  // "nav": false (the bake leaves them out: barricade, closed door) and for anything that is not a level solid.
  // Every other level solid is already cut out of the navmesh, so pressing against it means congestion or a
  // snag, never a reason to block the navmesh (a block there can cut a whole team off, measured 2026-09-27).
  // Compound solids (walls with openings, stairs) produce collision ids `<id>_seg2`, `<id>_step3`, ...
  const levelSolidIds = level && Array.isArray(level.solids) ? level.solids.filter((s) => s && s.id).map((s) => s.id) : [];
  const navExcludedIds = level && Array.isArray(level.solids) ? level.solids.filter((s) => s && s.id && s.nav === false).map((s) => s.id) : [];
  const idMatch = (solidId, id) => solidId === id || solidId.startsWith(`${id}_`);
  sys.obstacleUnknownToNav = (solidId) => {
    if (solidId == null) return true;
    const sid = String(solidId);
    // generated level geometry (src/level/levelAssets.js, id prefix "geo:") is in the navmesh bake unless flagged nonav
    if (sid.startsWith('geo:')) return sid.endsWith(':nonav');
    if (navExcludedIds.some((id) => idMatch(sid, id))) return true;
    return !levelSolidIds.some((id) => idMatch(sid, id));
  };

  sys.guardMode = false; // tests / debugging: ignore the zone objective (bots hold their spot)
  sys.activeZone = () => {
    if (sys.guardMode) return null;
    if (session && typeof session.activeZone === 'function') return session.activeZone();
    const zones = config.zones || (level && level.match && level.match.zones) || [];
    const id = match && match.round ? match.round.zoneId : null;
    return zones.find((z) => z.id === id) || null;
  };
  sys.isInZone = (p, z = sys.activeZone()) => pointInZone(p, z);
  sys.zoneController = () => {
    const r = match && match.round;
    if (!r || !r.zone) return null;
    return r.zone.controller >= 0 ? r.zone.controller : null;
  };
  /** The zone needs this bot's team (not controlled by it) and the bot is outside. */
  sys.zoneUrgent = (bot) => {
    const z = sys.activeZone();
    if (!z) return false;
    return sys.zoneController() !== bot.c.team && !sys.isInZone(bot.c.position, z);
  };
  // Zone pressure 0..1 of a team (AI-04): grows while none of its members is inside the active zone it does not
  // hold (after objective.pressureGrace s, over pressureRamp s), and is at least pressureEnemyHolds while an
  // enemy team holds the zone. The bots of that team outside the zone push for it harder (Bot.decide).
  // Team presence = public round state (the zone counts the HUD shows), refreshed every tick in update().
  sys.teamZoneSeenAt = [];
  sys.zonePressure = (team) => {
    const z = sys.activeZone();
    if (!z || sys.roundState() !== 'running') return 0;
    const ctrl = sys.zoneController();
    if (ctrl === team) return 0;
    const O = cfg.objective;
    const since = sys.teamZoneSeenAt[team] ?? 0;
    let p = Math.max(0, Math.min(1, (sys.time - since - (O.pressureGrace ?? 4)) / Math.max(1e-3, O.pressureRamp ?? 16)));
    if (ctrl !== null && ctrl !== team) p = Math.max(p, O.pressureEnemyHolds ?? 0.5);
    return p;
  };
  const refreshZonePresence = () => {
    const r = match && match.round;
    const counts = r && r.zone && Array.isArray(r.zone.counts) ? r.zone.counts : null;
    if (!counts || sys.roundState() !== 'running') {
      for (let t = 0; t < 3; t++) sys.teamZoneSeenAt[t] = sys.time;
      return;
    }
    for (let t = 0; t < counts.length; t++) if (counts[t] > 0 || sys.teamZoneSeenAt[t] === undefined) sys.teamZoneSeenAt[t] = sys.time;
  };
  sys.roundState = () => {
    if (session && session.mode === 'practice') return 'practice';
    const r = match && match.round;
    return r ? r.state : 'running';
  };

  // ------------------------------------------------------------------ team danger map
  // Where teammates died recently, paths of that team get more expensive (A* node cost multiplier), so a
  // doorway that became a kill zone is avoided for a while in favour of another route.
  sys.dangers = []; // { team, pos: Vector3, until }
  sys.addDanger = (team, pos) => {
    sys.dangers.push({ team, pos: pos.clone ? pos.clone() : new Vector3(pos.x, pos.y, pos.z), until: sys.time + cfg.danger.duration });
    if (sys.dangers.length > 40) sys.dangers.shift();
  };
  const costFns = new Map();
  sys.dangerCost = (team) => {
    const list = sys.dangers.filter((d) => d.team === team && d.until > sys.time);
    if (!list.length || !sys.nav) return null;
    const key = `${team}:${list.length}:${list[list.length - 1].until}`;
    const cached = costFns.get(team);
    if (cached && cached.key === key) return cached.fn;
    const nodes = sys.nav.mesh.nodes;
    const R = cfg.danger.radius;
    const W = cfg.danger.weight;
    const fn = (n) => {
      const c = nodes[n].centroid;
      let m = 1;
      for (const d of list) {
        const dd = Math.hypot(c.x - d.pos.x, c.z - d.pos.z);
        if (dd < R && Math.abs(c.y - d.pos.y) < 2) m += W * (1 - dd / R);
      }
      return Math.min(m, cfg.danger.maxMultiplier);
    };
    costFns.set(team, { key, fn });
    return fn;
  };

  // ------------------------------------------------------------------ metrics hooks
  sys.recordStuck = (bot, ev) => {
    ev.bot = bot.c.id; // same object: the recovery time is filled in later by the path follower
    sys.metrics.stuck.push(ev);
    if (sys.metrics.stuck.length > 300) sys.metrics.stuck.shift();
  };
  sys.recordReaction = (bot, f, t) => {
    sys.metrics.reactions.push({ bot: bot.c.id, target: f.targetId, detectedAt: +f.detectedAt.toFixed(3), firstShotAt: +t.toFixed(3), reaction: +(t - f.detectedAt).toFixed(3), delay: +f.delay.toFixed(3), distance: +f.distance.toFixed(2) });
    if (sys.metrics.reactions.length > 500) sys.metrics.reactions.shift();
  };
  sys.recordSearch = (bot, info) => {
    sys.metrics.searches.push({ bot: bot.c.id, t: +sys.time.toFixed(2), ...info, duration: +info.duration.toFixed(2), pos: info.pos ? info.pos.toArray().map((v) => +v.toFixed(2)) : null });
    if (sys.metrics.searches.length > 300) sys.metrics.searches.shift();
  };

  // ------------------------------------------------------------------ events (stimuli)
  const unsub = [];
  const on = (type, fn) => {
    if (events && typeof events.on === 'function') unsub.push(events.on(type, fn));
  };
  const livingBots = () => sys.bots.filter((b) => b.c.alive);
  on('weapon:fired', (p) => {
    if (!p || !p.muzzle) return;
    const team = p.team;
    // how far the round really flew (it stops at the first wall / body): a round that hit a wall cannot pass
    // close by a bot behind that wall ("under fire" only from real near misses)
    const res = p.result;
    const end = res && res.hit && res.hit.point ? res.hit.point : res && res.aimPoint ? res.aimPoint : null;
    const shotLen = end ? p.muzzle.distanceTo(end) : Infinity;
    for (const b of livingBots()) {
      if (b.c.id === p.shooterId) continue;
      if (team === b.c.team && cfg.hearing.ignoreFriendly) continue;
      b.perception.onSound(sys.time, 'gunshot', p.shooterId, team, p.muzzle, p.loudness ?? 1, p.dir || null, shotLen);
    }
  });
  on('footstep', (p) => {
    if (!p || !p.position) return;
    for (const b of livingBots()) {
      if (b.c.id === p.id || b.c.team === p.team) continue;
      const d = b.c.position.distanceTo(p.position);
      if (d > cfg.hearing.footstepRange * (p.loudness ?? 1) + 0.5) continue; // cheap reject before the ray
      b.perception.onSound(sys.time, 'footstep', p.id, p.team, p.position, p.loudness ?? 0.5, null);
    }
  });
  on('combatant:damaged', (p) => {
    const b = p && sys.byId.get(p.victimId);
    if (!b || !b.c.alive) return;
    const attacker = p.attackerId != null && combatants ? combatants.get(p.attackerId) : null;
    // only the shot direction is used (attackerPosition in the event is NOT read: no exact position)
    b.perception.onDamaged(sys.time, p.attackerId ?? null, attacker ? attacker.team : null, p.fromDir || null);
    b.decisionDirty = true;
  });
  const forgetEverywhere = (id) => {
    for (const b of sys.bots) {
      b.memory.forget(id);
      b.perception.forget(id);
      if (b.targetId === id) {
        b.targetId = null;
        b.decisionDirty = true;
      }
    }
  };
  on('combatant:died', (p) => {
    if (!p) return;
    forgetEverywhere(p.victimId);
    const victim = combatants ? combatants.get(p.victimId) : null;
    if (victim && p.position) sys.addDanger(victim.team, p.position);
    const b = sys.byId.get(p.victimId);
    if (b) b.onDeath(sys.time);
  });
  on('combatant:spawned', (p) => {
    if (!p) return;
    forgetEverywhere(p.id); // a respawned enemy is a new, unknown contact
  });
  on('zone:control_changed', () => {
    for (const b of sys.bots) b.decisionDirty = true;
  });
  on('round:started', () => {
    for (const b of sys.bots) b.decisionDirty = true;
  });
  // round over: every bot re-decides in the next tick (task 'idle', stops moving) instead of finishing its
  // current move until its next scheduled decision
  on('round:ended', () => {
    for (const b of sys.bots) b.decisionDirty = true;
  });

  // ------------------------------------------------------------------ API
  function addBot(combatant) {
    if (!combatant || combatant.id == null || sys.byId.has(combatant.id)) return;
    const b = new Bot(sys, combatant, sys.bots.length);
    // one source of truth for the bot turn rate: ai.json overrides the Combatant default (combat.json)
    if ('turnRateDegPerSec' in combatant) combatant.turnRateDegPerSec = cfg.turnRateDegPerSec;
    sys.bots.push(b);
    sys.byId.set(combatant.id, b);
    restagger();
    if (combatant.controller && combatant.controller.params && combatant.controller.params.speeds) sys.runSpeed = combatant.controller.params.speeds.run;
  }

  function removeBot(id) {
    const b = sys.byId.get(id);
    if (!b) return;
    b.releaseCover();
    sys.tactics.board.release(id);
    sys.bots = sys.bots.filter((x) => x !== b);
    sys.byId.delete(id);
    restagger();
  }

  function restagger() {
    const n = Math.max(1, sys.bots.length);
    const pp = 1 / cfg.tick.perceptionHz;
    const dp = 1 / cfg.tick.decisionHz;
    sys.bots.forEach((b, i) => {
      b.nextPerception = sys.time + (pp * i) / n;
      b.nextDecision = sys.time + (dp * i) / n;
    });
  }

  function update(dt) {
    if (!(dt > 0)) return;
    const t0 = typeof performance !== 'undefined' ? performance.now() : 0;
    sys.time += dt;
    sys.tickCount++;
    sys.metrics.ticks++;
    if (sys.nav && typeof sys.nav.update === 'function') sys.nav.update(dt);
    refreshZonePresence();
    const pp = 1 / cfg.tick.perceptionHz;
    const dp = 1 / cfg.tick.decisionHz;
    let perceived = 0;
    const t = sys.time;
    for (const b of sys.bots) {
      const c = b.c;
      if (!c.alive) {
        if (b.wasAlive) b.onDeath(t);
        continue; // the CombatantManager steps dead / undriven combatants
      }
      if (!b.wasAlive) {
        b.onSpawn(t);
        b.nextPerception = t + ((b.index % sys.bots.length) * pp) / Math.max(1, sys.bots.length);
      }
      if (t + 1e-9 >= b.nextPerception) {
        const since = b.perception.lastUpdate >= 0 ? Math.min(0.5, t - b.perception.lastUpdate) : pp;
        b.perception.updateVision(t, since);
        b.nextPerception += pp;
        if (b.nextPerception < t) b.nextPerception = t + pp;
        perceived++;
        sys.metrics.perceptionUpdates++;
      }
      b.memory.decay(dt);
      if (t + 1e-9 >= b.nextDecision || b.decisionDirty) {
        b.decide(t);
        const jitter = (b.rng.next() * 2 - 1) * cfg.tick.decisionJitter;
        b.nextDecision = t + dp + jitter;
        sys.metrics.decisions++;
      }
      const cmd = b.act(dt);
      c.applyCommand(cmd, dt);
      b.afterApply(t);
    }
    sys.metrics.maxBotsPerceivedInTick = Math.max(sys.metrics.maxBotsPerceivedInTick, perceived);
    if (sys.overlay && sys.tickCount % 6 === 0) sys.overlay.update(sys);
    if (sys.debugEnabled) installAIDebugApi(api, sys);
    if (t0) {
      const ms = performance.now() - t0;
      sys.metrics.updateMs = sys.metrics.updateMs * 0.95 + ms * 0.05;
      sys.metrics.updateMsMax = Math.max(sys.metrics.updateMsMax, ms);
    }
  }

  function reset() {
    sys.dangers.length = 0;
    sys.teamZoneSeenAt.length = 0;
    if (sys.nav && typeof sys.nav.reset === 'function') sys.nav.reset();
    if (sys.cover) sys.cover.releaseAll();
    sys.tactics.reset();
    for (const b of sys.bots) {
      b.resetBrain(sys.time);
      b.wasAlive = false;
    }
    restagger();
  }

  function getDebug() {
    return {
      stub: false,
      time: +sys.time.toFixed(3),
      ticks: sys.tickCount,
      levelId,
      nav: sys.nav ? sys.nav.getDebug() : null,
      cover: sys.cover ? { points: sys.cover.points.length, reservations: sys.cover.reservations(), stats: { ...sys.cover.stats } } : null,
      activeZone: (() => {
        const z = sys.activeZone();
        return z ? { id: z.id, center: z.center, radius: z.radius, controller: sys.zoneController() } : null;
      })(),
      round: sys.roundState(),
      config: { perceptionHz: cfg.tick.perceptionHz, decisionHz: cfg.tick.decisionHz, turnRateDegPerSec: cfg.turnRateDegPerSec },
      bots: sys.bots.map((b) => b.snapshot(sys.time)),
      metrics: {
        ticks: sys.metrics.ticks,
        perceptionUpdates: sys.metrics.perceptionUpdates,
        decisions: sys.metrics.decisions,
        maxBotsPerceivedInTick: sys.metrics.maxBotsPerceivedInTick,
        updateMsAvg: +sys.metrics.updateMs.toFixed(3),
        updateMsMax: +sys.metrics.updateMsMax.toFixed(3),
        stuck: sys.metrics.stuck.slice(-50),
        reactions: sys.metrics.reactions.slice(-100),
        searches: sys.metrics.searches.slice(-50),
        tactics: { ...sys.tactics.stats },
      },
      overlay: !!sys.overlay,
    };
  }

  function dispose() {
    for (const u of unsub) if (typeof u === 'function') u();
    unsub.length = 0;
    if (sys.overlay) sys.overlay.dispose();
  }

  /** Scripted move (tests / debugging): the bot walks to `pos` and stays there, perceiving but not fighting. */
  function commandMove(id, pos, { tolerance = 0.6, run = true } = {}) {
    const b = sys.byId.get(id);
    if (!b) return false;
    b.scripted = { type: 'move', goal: new Vector3(pos[0] ?? pos.x, pos[1] ?? pos.y, pos[2] ?? pos.z), tolerance, run, startedAt: sys.time, arrivedAt: -1 };
    b.decisionDirty = true;
    return true;
  }
  function clearCommand(id) {
    const b = sys.byId.get(id);
    if (!b) return false;
    b.scripted = null;
    b.move.clearGoal();
    b.decisionDirty = true;
    return true;
  }
  /** Scripted scenarios: a bot with nothing to do looks towards yawDeg for `seconds` (idle look only). */
  function setLookHint(id, yawDeg, seconds = 30) {
    const b = sys.byId.get(id);
    if (!b) return false;
    b.lookHint = { yaw: (yawDeg * Math.PI) / 180, until: sys.time + seconds };
    return true;
  }
  function setGuardMode(on) {
    sys.guardMode = !!on;
    for (const b of sys.bots) b.decisionDirty = true;
    return sys.guardMode;
  }

  const api = {
    isStub: false,
    commandMove,
    clearCommand,
    setGuardMode,
    setLookHint,
    addBot,
    removeBot,
    update,
    getDebug,
    reset,
    dispose,
    /** Direct access for tests / debugging (not part of the contract). */
    _sys: sys,
    get cfg() {
      return cfg;
    },
    bot: (id) => sys.byId.get(id) || null,
  };
  return api;
}
