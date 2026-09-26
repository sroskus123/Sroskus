// Match telemetry (tests and debugging only; the game never depends on it). Watches one MatchSession
// through its tick observer and the event bus, without changing the simulation, and reports what an
// integration run needs: scores over time, zone control changes / ties / time per state, kills and
// deaths per team, respawns and respawn delays, shots / hits / reloads per team, bots stuck in movement
// and how they recovered, the largest per-tick position jump of every combatant (teleport check), empty
// weapons and the simulation cost per tick. DOM-free: runs in Node (tools/match_report.mjs, unit tests)
// and in the browser (window.__IV.telemetry*).
//
// Stuck (independent of the AI's own detector): a living combatant that WANTS to move (movement command
// |moveX, moveZ| >= 0.3 and, for bots, the AI path follower is following a path — close-range combat
// strafing is intentional and does not count) but stays within `stuckRadius` of an anchor point. The anchor
// moves when the combatant gets farther than stuckRadius from it, after more than `idleResetS` without
// movement intent, on death and on spawn. Episode duration = time since the anchor was set.

const DEFAULTS = {
  sampleEveryS: 10, // score / zone samples
  stuckRadius: 1.0, // m
  stuckReportS: 2.0, // episodes at least this long are listed
  idleResetS: 1.0, // this long without movement intent ends an episode (the bot chose to stay)
  teleportJump: 0.35, // m per tick; sprint 5.8 m/s = 0.097 m/tick, a 4 m fall ends at ~0.15 m/tick
  maxEpisodes: 200,
};

function pct(sorted, p) {
  if (!sorted.length) return 0;
  const i = Math.min(sorted.length - 1, Math.max(0, Math.round((p / 100) * (sorted.length - 1))));
  return sorted[i];
}

function r3(v) {
  return Math.round(v * 1000) / 1000;
}

export class MatchTelemetry {
  /**
   * @param {import('../game/session.js').MatchSession} session
   * @param {import('../engine/events.js').EventBus} events
   * @param {object} [opts] see DEFAULTS
   */
  constructor(session, events, opts = {}) {
    this.session = session;
    this.events = events;
    this.o = { ...DEFAULTS, ...opts };
    this.teamCount = session.teamCount;
    this._unsub = [];
    this._reset();
  }

  _reset() {
    const T = this.teamCount;
    const z = () => new Array(T).fill(0);
    this.startTick = this.session.tickCount;
    this.startTime = this.session.simTime;
    this.ticks = 0;
    this.samples = [];
    this.nextSampleAt = this.session.simTime;
    this.zoneChanges = [];
    this.zoneTime = { controlled: z(), contested: 0, empty: 0, preRound: 0, ended: 0 };
    this.contestedEpisodes = 0;
    this.kills = z();
    this.deaths = z();
    this.forcedDeaths = 0;
    this.teamKills = 0;
    this.spawns = z();
    this.respawns = z();
    this.respawnDelays = [];
    this.shots = z();
    this.shotsBlockedMuzzle = z();
    this.blockedDetail = {}; // '<blockedBy>:<hit kind>[:enemy|friend]' -> count
    this.interruptReasons = {};
    this.hits = z();
    this.headshots = z();
    this.ffBlocked = z();
    this.damage = z();
    this.reloadsStarted = z();
    this.reloadsFinished = z();
    this.reloadsInterrupted = z();
    this.dryFires = z();
    this.switches = z();
    this.rounds = [];
    this.roundResets = 0;
    this.emptyWeaponTicks = 0; // bot ticks with no ammo at all in the active weapon (mag + chamber + reserve 0)
    this.emptyWeaponBots = new Set();
    this.tickMs = [];
    this.aiMs = [];
    this.per = new Map(); // id -> per-combatant tracking
    this.stuckEpisodes = [];
    this.teleports = [];
    this.lastDeathAt = new Map();
    this.errors = [];
  }

  attach() {
    const s = this.session;
    const on = (type, fn) => this._unsub.push(this.events.on(type, fn));
    const teamOf = (id) => {
      const c = id != null ? s.combatants.get(id) : null;
      return c ? c.team : -1;
    };
    on('weapon:fired', (p) => {
      if (p.team >= 0 && p.team < this.teamCount) {
        this.shots[p.team]++;
        if (p.result && p.result.blocked) {
          this.shotsBlockedMuzzle[p.team]++;
          const h = p.result.hit;
          let k = `${p.result.blockedBy}:${h ? h.kind : 'none'}`;
          if (h && h.kind === 'combatant') k += h.team === p.team ? ':friend' : ':enemy';
          this.blockedDetail[k] = (this.blockedDetail[k] || 0) + 1;
        }
      }
    });
    on('weapon:hit', (p) => {
      const t = teamOf(p.shooterId);
      if (t < 0 || !p.hit || p.hit.kind !== 'combatant') return;
      const d = p.damage;
      if (d && (d.result === 'applied' || d.result === 'killed')) {
        this.hits[t]++;
        if (p.part === 'head') this.headshots[t]++;
      }
    });
    on('combatant:damaged', (p) => {
      const t = teamOf(p.attackerId);
      if (t >= 0) this.damage[t] += p.amount || 0;
    });
    on('combatant:friendly_fire_blocked', (p) => {
      const t = teamOf(p.attackerId);
      if (t >= 0) this.ffBlocked[t]++;
    });
    on('combatant:died', (p) => {
      const vt = teamOf(p.victimId);
      if (vt >= 0) this.deaths[vt]++;
      const at = teamOf(p.attackerId);
      if (p.attackerId == null) this.forcedDeaths++;
      else if (at === vt) this.teamKills++;
      else if (at >= 0) this.kills[at]++;
      this.lastDeathAt.set(p.victimId, s.simTime);
      const tr = this.per.get(p.victimId);
      if (tr) this._endStuck(tr, 'died');
    });
    on('combatant:spawned', (p) => {
      if (p.team >= 0 && p.team < this.teamCount) this.spawns[p.team]++;
      const died = this.lastDeathAt.get(p.id);
      if (died !== undefined) {
        this.respawns[p.team]++;
        this.respawnDelays.push(s.simTime - died);
        this.lastDeathAt.delete(p.id);
      }
      const tr = this.per.get(p.id);
      if (tr) {
        this._endStuck(tr, 'respawned');
        tr.spawnedThisTick = true;
      }
    });
    const reload = (arr) => (p) => {
      const t = teamOf(p.id);
      if (t >= 0) arr[t]++;
    };
    on('weapon:reload_started', reload(this.reloadsStarted));
    on('weapon:reload_finished', reload(this.reloadsFinished));
    on('weapon:reload_interrupted', (p) => {
      reload(this.reloadsInterrupted)(p);
      this.interruptReasons[p.kind] = (this.interruptReasons[p.kind] || 0) + 1;
    });
    on('weapon:dry_fire', reload(this.dryFires));
    on('weapon:switched', reload(this.switches));
    on('zone:control_changed', (p) => {
      this.zoneChanges.push({ t: r3(s.simTime - this.startTime), roundT: r3(s.match.round.elapsedUs / 1e6), status: p.status, controller: p.controller });
      if (p.status === 'contested') this.contestedEpisodes++;
    });
    on('round:ended', (p) => {
      this.rounds.push({ t: r3(s.simTime - this.startTime), roundT: r3(s.match.round.elapsedUs / 1e6), winner: p.winner, draw: !!p.draw, reason: p.reason, scores: p.scores.slice() });
    });
    on('round:reset', () => {
      this.roundResets++;
      this.lastDeathAt.clear();
      for (const tr of this.per.values()) {
        this._endStuck(tr, 'round_reset');
        tr.prevPos = null;
      }
    });
    this._unsub.push(s.addTickObserver(() => this._onTick()));
    return this;
  }

  detach() {
    for (const u of this._unsub) u();
    this._unsub.length = 0;
  }

  _track(c) {
    let tr = this.per.get(c.id);
    if (!tr) {
      tr = {
        id: c.id,
        team: c.team,
        isPlayer: c.isPlayer,
        prevPos: null,
        prevAlive: false,
        prevSpawnCount: -1,
        maxJump: 0,
        maxJumpH: 0,
        maxJumpAt: null,
        anchor: null,
        anchorT: 0,
        idleT: 0,
        stuckMax: 0,
        stuckEpisode: null,
        stuckEpisodes: 0,
        spawnedThisTick: false,
        aliveTicks: 0,
        distance: 0,
      };
      this.per.set(c.id, tr);
    }
    return tr;
  }

  _endStuck(tr, how) {
    const ep = tr.stuckEpisode;
    tr.anchor = null;
    tr.idleT = 0;
    if (!ep) return;
    tr.stuckEpisode = null;
    ep.duration = r3(ep.duration);
    ep.endedBy = how;
    if (ep.duration >= this.o.stuckReportS) {
      tr.stuckEpisodes++;
      if (this.stuckEpisodes.length < this.o.maxEpisodes) this.stuckEpisodes.push(ep);
    }
  }

  _onTick() {
    const s = this.session;
    const o = this.o;
    const dt = s.lastDtUs / 1e6;
    const t = s.simTime - this.startTime;
    this.ticks++;
    this.tickMs.push(s.perf.tickMs);
    this.aiMs.push(s.perf.aiMs);
    const r = s.match.round;
    if (s.mode === 'match') {
      if (r.state === 'pre_round') this.zoneTime.preRound += dt;
      else if (r.state === 'ended') this.zoneTime.ended += dt;
      else if (r.zone.status === 'controlled' && r.zone.controller >= 0) this.zoneTime.controlled[r.zone.controller] += dt;
      else if (r.zone.status === 'contested') this.zoneTime.contested += dt;
      else this.zoneTime.empty += dt;
    }
    if (s.simTime + 1e-9 >= this.nextSampleAt) {
      this.nextSampleAt += o.sampleEveryS;
      const alive = new Array(this.teamCount).fill(0);
      for (const c of s.combatants.all()) if (c.alive) alive[c.team]++;
      this.samples.push({ t: Math.round(t), roundT: r3(r.elapsedUs / 1e6), state: r.state, scores: r.scores.slice(), status: r.zone.status, controller: r.zone.controller, counts: r.zone.counts.slice(), alive, kills: this.kills.slice() });
    }
    const ai = s.ai;
    const botOf = ai && typeof ai.bot === 'function' ? (id) => ai.bot(id) : () => null;
    for (const c of s.combatants.all()) {
      const tr = this._track(c);
      const alive = c.alive;
      const p = c.controller.position;
      const part = c.participant;
      const sc = part ? part.spawnCount : 0;
      if (alive) {
        tr.aliveTicks++;
        // per-tick jump (a spawn is a legitimate placement, everything else must be continuous motion)
        if (tr.prevPos && tr.prevAlive && sc === tr.prevSpawnCount && !tr.spawnedThisTick) {
          const dx = p.x - tr.prevPos.x;
          const dy = p.y - tr.prevPos.y;
          const dz = p.z - tr.prevPos.z;
          const dH = Math.hypot(dx, dz);
          const d3 = Math.hypot(dH, dy);
          tr.distance += dH;
          if (d3 > tr.maxJump) {
            tr.maxJump = d3;
            tr.maxJumpAt = { t: r3(t), pos: [r3(p.x), r3(p.y), r3(p.z)] };
          }
          if (dH > tr.maxJumpH) tr.maxJumpH = dH;
          if (d3 > o.teleportJump && this.teleports.length < o.maxEpisodes) this.teleports.push({ id: c.id, t: r3(t), jump: r3(d3), from: [r3(tr.prevPos.x), r3(tr.prevPos.y), r3(tr.prevPos.z)], to: [r3(p.x), r3(p.y), r3(p.z)] });
        }
        // movement intent: the command applied this tick (+ the AI path follower for bots)
        const cmd = c.lastCmd || {};
        const mv = Math.hypot(cmd.moveX || 0, cmd.moveZ || 0);
        let intent = mv >= 0.3;
        let task = null;
        if (intent && !c.isPlayer) {
          const b = botOf(c.id);
          if (b && b.move) {
            intent = !!b.move.wantMove;
            task = b.task;
          }
        }
        if (!tr.anchor) {
          tr.anchor = { x: p.x, z: p.z };
          tr.anchorT = t;
        }
        const away = Math.hypot(p.x - tr.anchor.x, p.z - tr.anchor.z);
        if (away > o.stuckRadius) {
          this._endStuck(tr, 'moved_away');
          tr.anchor = { x: p.x, z: p.z };
          tr.anchorT = t;
        } else if (!intent) {
          tr.idleT += dt;
          if (tr.idleT > o.idleResetS) {
            this._endStuck(tr, 'stopped_moving');
            tr.anchor = { x: p.x, z: p.z };
            tr.anchorT = t;
          }
        } else {
          tr.idleT = 0;
          const dur = t - tr.anchorT;
          if (dur > tr.stuckMax) tr.stuckMax = dur;
          if (dur >= 0.5) {
            if (!tr.stuckEpisode) tr.stuckEpisode = { id: c.id, team: c.team, start: r3(tr.anchorT), duration: dur, pos: [r3(p.x), r3(p.y), r3(p.z)], task };
            tr.stuckEpisode.duration = dur;
            if (task) tr.stuckEpisode.task = task;
          }
        }
        // bots out of ammo in the active weapon
        if (!c.isPlayer) {
          const ws = c.weapon.state;
          if (ws.magazine + ws.chamber + ws.reserve === 0) {
            this.emptyWeaponTicks++;
            this.emptyWeaponBots.add(c.id);
          }
        }
      } else if (tr.prevAlive) {
        this._endStuck(tr, 'died');
      }
      tr.prevPos = tr.prevPos || { x: 0, y: 0, z: 0 };
      tr.prevPos.x = p.x;
      tr.prevPos.y = p.y;
      tr.prevPos.z = p.z;
      tr.prevAlive = alive;
      tr.prevSpawnCount = sc;
      tr.spawnedThisTick = false;
    }
  }

  report() {
    const s = this.session;
    const T = this.teamCount;
    const r = s.match.round;
    // flush the open stuck episodes into a copy (the run may continue)
    const open = [];
    let stuckMax = 0;
    let stuckMaxId = null;
    for (const tr of this.per.values()) {
      if (tr.stuckMax > stuckMax) {
        stuckMax = tr.stuckMax;
        stuckMaxId = tr.id;
      }
      if (tr.stuckEpisode && tr.stuckEpisode.duration >= this.o.stuckReportS) open.push({ ...tr.stuckEpisode, duration: r3(tr.stuckEpisode.duration), endedBy: 'open' });
    }
    const episodes = this.stuckEpisodes.concat(open);
    const byEnd = {};
    for (const e of episodes) byEnd[e.endedBy] = (byEnd[e.endedBy] || 0) + 1;
    const tick = this.tickMs.slice().sort((a, b) => a - b);
    const aiT = this.aiMs.slice().sort((a, b) => a - b);
    const mean = (a) => (a.length ? a.reduce((x, y) => x + y, 0) / a.length : 0);
    const delays = this.respawnDelays.slice().sort((a, b) => a - b);
    const combatants = [...this.per.values()].map((tr) => ({
      id: tr.id,
      team: tr.team,
      isPlayer: tr.isPlayer,
      maxJump: r3(tr.maxJump),
      maxJumpH: r3(tr.maxJumpH),
      maxJumpAt: tr.maxJumpAt,
      stuckMaxS: r3(tr.stuckMax),
      stuckEpisodes: tr.stuckEpisodes,
      distance: Math.round(tr.distance),
      aliveS: r3(tr.aliveTicks / 60),
    }));
    let maxJump = 0;
    let maxJumpH = 0;
    let maxJumpId = null;
    for (const c of combatants) {
      if (c.maxJump > maxJump) {
        maxJump = c.maxJump;
        maxJumpId = c.id;
      }
      maxJumpH = Math.max(maxJumpH, c.maxJumpH);
    }
    const aiDbg = s.ai && typeof s.ai.getDebug === 'function' ? s.ai.getDebug() : null;
    const aiStuck = aiDbg && aiDbg.metrics ? aiDbg.metrics.stuck : [];
    const rate = (a, b) => a.map((x, i) => (b[i] > 0 ? r3(x / b[i]) : 0));
    return {
      simulatedS: r3(s.simTime - this.startTime),
      ticks: this.ticks,
      round: { state: r.state, roundNumber: r.roundNumber, elapsedS: r3(r.elapsedUs / 1e6), scores: r.scores.slice(), winner: r.winner, draw: r.draw, endReason: r.endReason, zoneId: r.zoneId },
      roundsEnded: this.rounds,
      roundResets: this.roundResets,
      samples: this.samples,
      zone: {
        changes: this.zoneChanges.length,
        contestedEpisodes: this.contestedEpisodes,
        controllersSeen: [...new Set(this.zoneChanges.filter((z) => z.controller != null).map((z) => z.controller))].sort(),
        timeS: { controlled: this.zoneTime.controlled.map(r3), contested: r3(this.zoneTime.contested), empty: r3(this.zoneTime.empty), preRound: r3(this.zoneTime.preRound), ended: r3(this.zoneTime.ended) },
        firstChanges: this.zoneChanges.slice(0, 12),
      },
      kills: this.kills.slice(),
      deaths: this.deaths.slice(),
      teamKills: this.teamKills,
      forcedDeaths: this.forcedDeaths,
      spawns: this.spawns.slice(),
      respawns: this.respawns.slice(),
      respawnDelayS: { n: delays.length, min: r3(delays[0] || 0), median: r3(pct(delays, 50)), max: r3(delays[delays.length - 1] || 0) },
      spawnBlockedEvents: s.combatants.spawnBlocked,
      shots: this.shots.slice(),
      hits: this.hits.slice(),
      hitRate: rate(this.hits, this.shots),
      headshots: this.headshots.slice(),
      shotsBlockedAtMuzzle: this.shotsBlockedMuzzle.slice(),
      blockedDetail: { ...this.blockedDetail },
      friendlyFireBlocked: this.ffBlocked.slice(),
      damage: this.damage.slice(),
      reloads: { started: this.reloadsStarted.slice(), finished: this.reloadsFinished.slice(), interrupted: this.reloadsInterrupted.slice(), interruptReasons: { ...this.interruptReasons } },
      dryFires: this.dryFires.slice(),
      weaponSwitches: this.switches.slice(),
      emptyWeapon: { botTicks: this.emptyWeaponTicks, botSeconds: r3(this.emptyWeaponTicks / 60), bots: [...this.emptyWeaponBots] },
      stuck: {
        radiusM: this.o.stuckRadius,
        maxS: r3(stuckMax),
        maxId: stuckMaxId,
        episodesOver2s: episodes.filter((e) => e.duration >= 2).length,
        episodesOver5s: episodes.filter((e) => e.duration > 5).length,
        endedBy: byEnd,
        longest: episodes.sort((a, b) => b.duration - a.duration).slice(0, 8),
        ai: {
          events: aiStuck.length,
          recovered: aiStuck.filter((e) => e.recoveredAt !== null).length,
          maxRecoveryS: aiStuck.reduce((m, e) => Math.max(m, e.recoveryTime || 0), 0),
          actions: aiStuck.reduce((m, e) => ((m[e.action.split(':')[0]] = (m[e.action.split(':')[0]] || 0) + 1), m), {}),
        },
      },
      jumps: { maxM: r3(maxJump), maxHorizontalM: r3(maxJumpH), maxId: maxJumpId, teleports: this.teleports.length, teleportList: this.teleports.slice(0, 10), limitM: this.o.teleportJump },
      perf: {
        tickMsMean: r3(mean(this.tickMs)),
        tickMsP50: r3(pct(tick, 50)),
        tickMsP95: r3(pct(tick, 95)),
        tickMsP99: r3(pct(tick, 99)),
        tickMsMax: r3(tick[tick.length - 1] || 0),
        aiMsMean: r3(mean(this.aiMs)),
        aiMsP50: r3(pct(aiT, 50)),
        aiMsP95: r3(pct(aiT, 95)),
        aiMsMax: r3(aiT[aiT.length - 1] || 0),
      },
      combatants,
    };
  }
}
