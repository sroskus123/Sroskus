// Headless AI simulation on the REAL game integration (src/game/session.js MatchSession: core Match,
// CombatantManager, Combatant.applyCommand, WorldQuery, hitscan with muzzle validation) and the real AI
// (src/ai/index.js) on the AI arena. Used by the AI unit tests and as a CLI for measurements:
//   node tests/unit/support/aiSim.mjs --seconds 120 --seed 3
// Test-only manipulation helpers (teleport, look, player commands) live here, never in src/game.

import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { Vector3 } from 'three';
import { EventBus } from '../../../src/engine/events.js';
import { buildLevelSolids } from '../../../src/level/levelGeometry.js';
import { CollisionWorld } from '../../../src/physics/collisionWorld.js';
import { MatchSession } from '../../../src/game/session.js';
import { createAISystem } from '../../../src/ai/index.js';

const here = path.dirname(fileURLToPath(import.meta.url));
export const WEB = path.resolve(here, '..', '..', '..');
const readJson = (p) => JSON.parse(readFileSync(path.join(WEB, p), 'utf8'));

export const DT = 1 / 60;
export const DEG = Math.PI / 180;

let cache = null;
function data() {
  if (!cache) {
    const level = readJson('src/data/ai_arena.json');
    cache = {
      level,
      world: new CollisionWorld(buildLevelSolids(level)),
      movement: readJson('src/data/movement.json'),
      weaponsData: readJson('src/data/weapons.json'),
      combat: readJson('src/data/combat.json'),
      teams: readJson('src/data/teams.json'),
      aiJson: JSON.parse(readFileSync(path.join(WEB, '..', 'Shared', 'config', 'ai.json'), 'utf8')),
    };
  }
  return cache;
}

export function arenaLevel() {
  return data().level;
}

export function aiJson() {
  return data().aiJson;
}

/**
 * @param {object} o { mode 'match'|'practice', bots [t0,t1,t2], withPlayer, seed, tuning (ai.json overrides),
 *                     zone (force a zone id), rulesPatch, skipPreRound }
 */
export function createArenaSession(o = {}) {
  const d = data();
  const events = new EventBus();
  const rulesPatch = { ...(o.rulesPatch || {}) };
  if (o.zone) rulesPatch.zone = { ...(rulesPatch.zone || {}), locations: [{ id: o.zone, name: o.zone }] };
  const session = new MatchSession({
    level: d.level,
    world: d.world,
    movement: d.movement,
    weaponsData: d.weaponsData,
    combat: d.combat,
    teams: d.teams,
    events,
    createAISystem,
    mode: o.mode || 'match',
    seed: o.seed ?? 1,
    bots: o.bots || [5, 6, 6],
    withPlayer: o.withPlayer !== false,
    rulesPatch: Object.keys(rulesPatch).length ? rulesPatch : null,
    aiConfig: o.tuning ? { tuning: o.tuning } : {},
  });
  session.start({ skipPreRound: o.skipPreRound !== false });
  const log = { fired: [], hits: [], damaged: [], died: [], ff: 0, zone: [] };
  events.on('weapon:fired', (p) => log.fired.push({ t: session.simTime, shooterId: p.shooterId, team: p.team, blocked: p.result ? p.result.blocked : null, hitKind: p.result && p.result.hit ? p.result.hit.kind : null, victim: p.result && p.result.hit ? p.result.hit.combatantId : null }));
  events.on('combatant:damaged', (p) => log.damaged.push({ t: session.simTime, victimId: p.victimId, attackerId: p.attackerId, amount: p.amount, part: p.part }));
  events.on('combatant:died', (p) => log.died.push({ t: session.simTime, victimId: p.victimId, attackerId: p.attackerId }));
  events.on('combatant:friendly_fire_blocked', () => log.ff++);
  events.on('zone:control_changed', (p) => log.zone.push({ t: session.simTime, controller: p.controller, status: p.status }));
  return { session, events, ai: session.ai, log, world: d.world };
}

/** Test-only: put a combatant somewhere (feet position) and set its view (degrees). */
export function place(session, id, pos, yawDeg = null, pitchDeg = 0) {
  const c = session.combatants.get(id);
  c.controller.teleport(new Vector3(pos[0], pos[1], pos[2]));
  c.controller.velocity.set(0, 0, 0);
  if (yawDeg !== null) c.yaw = yawDeg * DEG;
  c.pitch = pitchDeg * DEG;
  return c;
}

export function idleCmd(yawDeg = null, extra = {}) {
  return { moveX: 0, moveZ: 0, yaw: yawDeg === null ? null : yawDeg * DEG, pitch: 0, sprint: false, walk: false, crouch: false, jump: false, ads: false, fire: false, reload: false, switchTo: null, interact: false, ...extra };
}

/** Runs n ticks; playerCmd = object or function(tick) -> cmd; onTick(i) optional. */
export function run(ctx, n, { playerCmd = null, onTick = null } = {}) {
  const { session } = ctx;
  for (let i = 0; i < n; i++) {
    const cmd = typeof playerCmd === 'function' ? playerCmd(i) : playerCmd;
    session.tick(DT, { playerCmd: cmd });
    if (onTick && onTick(i) === false) return i + 1;
  }
  return n;
}

export function botOf(ctx, id) {
  return ctx.ai.bot(id);
}

/** Moves every bot except `keep` far away and freezes them (no AI, no bodies in the way). */
export function isolate(ctx, keep = []) {
  const { session } = ctx;
  let k = 0;
  for (const c of session.combatants.all()) {
    if (keep.includes(c.id)) continue;
    session.forceKill(c.id);
    k++;
  }
  // dead bots respawn after the delay: make respawns impossible for the test duration
  return k;
}

// ------------------------------------------------------------------ CLI (measurements)
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const arg = (n, d) => {
    const i = process.argv.indexOf(n);
    return i >= 0 ? Number(process.argv[i + 1]) : d;
  };
  const seconds = arg('--seconds', 60);
  const seed = arg('--seed', 1);
  const ctx = createArenaSession({ seed, zone: 'arena_center', withPlayer: process.argv.includes('--player') });
  const t0 = Date.now();
  const n = Math.round(seconds / DT);
  const every = Math.round(10 / DT);
  run(ctx, n, {
    playerCmd: idleCmd(),
    onTick: (i) => {
      if ((i + 1) % every === 0) {
        const r = ctx.session.roundInfo();
        const tasks = {};
        for (const b of ctx.ai.getDebug().bots) tasks[b.task] = (tasks[b.task] || 0) + 1;
        console.log(`t=${ctx.session.simTime.toFixed(0)}s scores=${r.scores.join('/')} zone=${r.status}:${r.controller} counts=${r.counts.join('/')} shots=${ctx.log.fired.length} dmg=${ctx.log.damaged.length} deaths=${ctx.log.died.length} ff=${ctx.log.ff} tasks=${JSON.stringify(tasks)}`);
      }
    },
  });
  const dbg = ctx.ai.getDebug();
  console.log(`sim ${seconds}s in ${((Date.now() - t0) / 1000).toFixed(1)} s wall; ai update avg ${dbg.metrics.updateMsAvg} ms max ${dbg.metrics.updateMsMax} ms`);
  console.log('stuck events', dbg.metrics.stuck.length, JSON.stringify(dbg.metrics.stuck.slice(-5)));
  console.log('reactions', dbg.metrics.reactions.length, JSON.stringify(dbg.metrics.reactions.slice(0, 5)));
  console.log('searches', dbg.metrics.searches.length);
  console.log('zone changes', JSON.stringify(ctx.log.zone.slice(0, 20)));
}
