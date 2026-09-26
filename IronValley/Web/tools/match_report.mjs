// Headless match run with telemetry (Node, no rendering): the real MatchSession (core Match, combatants,
// hitscan, spawn predicate) + the real AI on a level, the player idle at its spawn (or absent), and the
// telemetry of src/debug/matchTelemetry.js. Prints a JSON report (or a short summary).
//
//   node tools/match_report.mjs --level ai_arena --bots 5,6,6 --seconds 180 --seed 7
//   node tools/match_report.mjs --level ai_arena --bots 5,6,6 --full        # until the round ends (max 700 s)
//   options: --no-player, --pre-round (keep the 5 s countdown), --json (full JSON), --zone <id>

import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { EventBus } from '../src/engine/events.js';
import { buildLevelSolids } from '../src/level/levelGeometry.js';
import { CollisionWorld } from '../src/physics/collisionWorld.js';
import { MatchSession } from '../src/game/session.js';
import { createAISystem } from '../src/ai/index.js';
import { MatchTelemetry } from '../src/debug/matchTelemetry.js';

const here = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.resolve(here, '..');
const readJson = (p) => JSON.parse(readFileSync(path.join(WEB, p), 'utf8'));

export function runMatch({ level = 'ai_arena', bots = [5, 6, 6], seconds = 180, full = false, seed = 1, withPlayer = true, skipPreRound = true, zone = null, onSample = null } = {}) {
  const lvl = readJson(`src/data/${level}.json`);
  const events = new EventBus();
  const errors = [];
  const origError = console.error;
  console.error = (...a) => {
    errors.push(a.map(String).join(' '));
    origError(...a);
  };
  try {
    const session = new MatchSession({
      level: lvl,
      world: new CollisionWorld(buildLevelSolids(lvl)),
      movement: readJson('src/data/movement.json'),
      weaponsData: readJson('src/data/weapons.json'),
      combat: readJson('src/data/combat.json'),
      teams: readJson('src/data/teams.json'),
      events,
      createAISystem,
      mode: 'match',
      seed,
      bots,
      withPlayer,
      rulesPatch: zone ? { zone: { locations: [{ id: zone, name: zone }] } } : null,
    });
    session.start({ skipPreRound });
    const tel = new MatchTelemetry(session, events).attach();
    const dt = 1 / 60;
    const idle = { moveX: 0, moveZ: 0, yaw: null, pitch: null, fire: false };
    const maxTicks = Math.round((full ? 700 : seconds) * 60);
    const t0 = performance.now();
    const cpu0 = process.cpuUsage();
    let n = 0;
    let lastSample = 0;
    for (; n < maxTicks; n++) {
      session.tick(dt, { playerCmd: idle });
      if (onSample && tel.samples.length !== lastSample) {
        lastSample = tel.samples.length;
        onSample(tel.samples[lastSample - 1], tel);
      }
      if (full && session.match.round.state === 'ended' && session.simTime - session.roundEndedAt > 2.5) break;
    }
    const wallMs = performance.now() - t0;
    const cpu = process.cpuUsage(cpu0);
    const rep = tel.report();
    rep.level = level;
    rep.seed = seed;
    rep.bots = bots;
    rep.withPlayer = withPlayer;
    rep.wall = { ms: Math.round(wallMs), msPerTick: +(wallMs / n).toFixed(3), cpuMsPerTick: +((cpu.user + cpu.system) / 1000 / n).toFixed(3) };
    rep.consoleErrors = errors;
    tel.detach();
    session.dispose();
    return rep;
  } finally {
    console.error = origError;
  }
}

function summary(r) {
  const L = [];
  L.push(`level ${r.level} seed ${r.seed} bots ${r.bots.join('/')}${r.withPlayer ? ' + idle player' : ''}: ${r.simulatedS} s simulated, round ${r.round.state} ${r.round.elapsedS} s, scores ${r.round.scores.join('/')}${r.round.state === 'ended' ? ` -> ${r.round.draw ? 'DRAW' : 'winner ' + r.round.winner} (${r.round.endReason})` : ''}`);
  L.push(`zone: ${r.zone.changes} control changes, ${r.zone.contestedEpisodes} contested episodes, controllers seen ${JSON.stringify(r.zone.controllersSeen)}, time controlled ${r.zone.timeS.controlled.join('/')} s, contested ${r.zone.timeS.contested} s, empty ${r.zone.timeS.empty} s`);
  L.push(`kills ${r.kills.join('/')}, deaths ${r.deaths.join('/')}, team kills ${r.teamKills}, respawns ${r.respawns.join('/')} (delay min ${r.respawnDelayS.min} / median ${r.respawnDelayS.median} / max ${r.respawnDelayS.max} s), spawn_blocked events ${r.spawnBlockedEvents}`);
  L.push(`shots ${r.shots.join('/')}, hits ${r.hits.join('/')} (rate ${r.hitRate.join('/')}), headshots ${r.headshots.join('/')}, muzzle-blocked ${r.shotsBlockedAtMuzzle.join('/')}, FF blocked ${r.friendlyFireBlocked.join('/')}`);
  L.push(`reloads started ${r.reloads.started.join('/')}, finished ${r.reloads.finished.join('/')}, interrupted ${r.reloads.interrupted.join('/')}; dry fires ${r.dryFires.join('/')}; switches ${r.weaponSwitches.join('/')}; empty-weapon bot-seconds ${r.emptyWeapon.botSeconds} (${r.emptyWeapon.bots.length} bots)`);
  L.push(`stuck (telemetry, r ${r.stuck.radiusM} m): max ${r.stuck.maxS} s (${r.stuck.maxId}), episodes >=2 s ${r.stuck.episodesOver2s}, >5 s ${r.stuck.episodesOver5s}, ended by ${JSON.stringify(r.stuck.endedBy)}; AI detector: ${r.stuck.ai.events} events, ${r.stuck.ai.recovered} recovered, max recovery ${r.stuck.ai.maxRecoveryS} s, actions ${JSON.stringify(r.stuck.ai.actions)}`);
  L.push(`jumps: max ${r.jumps.maxM} m/tick (${r.jumps.maxId}), max horizontal ${r.jumps.maxHorizontalM} m/tick, teleports (> ${r.jumps.limitM} m) ${r.jumps.teleports}`);
  L.push(`cost: tick mean ${r.perf.tickMsMean} ms (p50 ${r.perf.tickMsP50}, p95 ${r.perf.tickMsP95}, p99 ${r.perf.tickMsP99}, max ${r.perf.tickMsMax}); ai.update mean ${r.perf.aiMsMean} ms (p95 ${r.perf.aiMsP95}); wall ${r.wall.msPerTick} ms/tick, CPU ${r.wall.cpuMsPerTick} ms/tick`);
  L.push(`console errors: ${r.consoleErrors.length}`);
  return L.join('\n');
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const args = process.argv.slice(2);
  const val = (k, d) => {
    const i = args.indexOf(k);
    return i >= 0 ? args[i + 1] : d;
  };
  const opts = {
    level: val('--level', 'ai_arena'),
    bots: val('--bots', '5,6,6').split(',').map(Number),
    seconds: Number(val('--seconds', 180)),
    full: args.includes('--full'),
    seed: Number(val('--seed', 1)),
    withPlayer: !args.includes('--no-player'),
    skipPreRound: !args.includes('--pre-round'),
    zone: val('--zone', null),
  };
  const r = runMatch({
    ...opts,
    onSample: args.includes('--progress') ? (s) => console.log(`  t=${s.t}s round=${s.roundT}s ${s.state} scores ${s.scores.join('/')} zone ${s.status}:${s.controller} counts ${s.counts.join('/')} alive ${s.alive.join('/')} kills ${s.kills.join('/')}`) : null,
  });
  if (args.includes('--json')) console.log(JSON.stringify(r, null, 1));
  else console.log(summary(r));
}

export { summary };
