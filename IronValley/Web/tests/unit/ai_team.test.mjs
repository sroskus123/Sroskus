// AI-04 — teams and objective on the real game integration: with the player idle (or absent) all three
// bot teams move to the active zone and fight each other, the zone changes hands and ties occur, allies
// never target the player or each other; tasks are re-evaluated on zone control change, death, respawn
// and round reset. Also the whole-match invariants of AI-02/AI-03 (no teleports, no firing while
// reloading, no shot with a blocked muzzle, exclusive cover).
import test from 'node:test';
import assert from 'node:assert/strict';
import { createArenaSession, run, idleCmd, DT } from './support/aiSim.mjs';

function matchRun({ seconds, withPlayer, seed }) {
  const ctx = createArenaSession({ bots: [5, 6, 6], withPlayer, seed, zone: 'arena_center' });
  const { session, ai, log } = ctx;
  const bots = session.combatants.bots();
  const teamOf = new Map(session.combatants.all().map((c) => [c.id, c.team]));
  const inZoneTicks = [0, 0, 0];
  const statuses = new Set();
  const controllers = new Set();
  let targetViolations = 0;
  let playerTargeted = 0;
  let maxH = 0;
  const prev = new Map(bots.map((c) => [c.id, { p: c.position.clone(), spawns: c.participant.spawnCount, alive: c.alive }]));
  let coverShare = 0;
  let muzzleShots = 0;
  let throughWall = 0;
  let botShots = 0;
  const offFired = ctx.events.on('weapon:fired', (p) => {
    if (!teamOf.has(p.shooterId) || p.shooterId === 'player') return;
    botShots++;
    const res = p.result;
    if (res && res.blockedBy === 'eye-to-muzzle') {
      muzzleShots++;
      // D8: a blocked muzzle stops the round at the obstruction; it may only hit the body directly in front
      // of the muzzle (point blank), never the aimed target behind a wall
      if (res.hit && res.hit.kind === 'combatant' && res.hit.distance > 1.0) throughWall++;
      if (res.hit && res.hit.kind === 'combatant' && res.camHit && res.camHit.kind === 'combatant' && res.camHit.combatantId !== res.hit.combatantId && res.hit.kind !== 'world') throughWall += 0;
    }
  });
  let stackSamples = 0;
  let stackHits = 0;
  let tickNo = 0;
  const decisionsAfterZoneChange = [];
  const offZone = ctx.events.on('zone:control_changed', () => {
    decisionsAfterZoneChange.push({ t: session.simTime, pending: true });
  });
  run(ctx, Math.round(seconds / DT), {
    playerCmd: idleCmd(),
    onTick: () => {
      const r = session.roundInfo();
      for (let t = 0; t < 3; t++) if (r.counts[t] > 0) inZoneTicks[t]++;
      statuses.add(r.status);
      if (r.controller >= 0) controllers.add(r.controller);
      for (const c of bots) {
        const b = ai.bot(c.id);
        if (b.targetId) {
          if (teamOf.get(b.targetId) === c.team) targetViolations++;
          if (b.targetId === 'player' && c.team === 0) playerTargeted++;
        }
        const q = prev.get(c.id);
        const spawns = c.participant.spawnCount;
        if (c.alive && q.alive && spawns === q.spawns) maxH = Math.max(maxH, Math.hypot(c.position.x - q.p.x, c.position.z - q.p.z));
        q.p.copy(c.position);
        q.spawns = spawns;
        q.alive = c.alive;
      }
      // teammates spread out: stationary teammates closer than 1 m to each other (sampled every 0.5 s)
      if (++tickNo % 30 === 0) {
        for (let t = 0; t < 3; t++) {
          const still = bots.filter((c) => c.team === t && c.alive && Math.hypot(c.controller.velocity.x, c.controller.velocity.z) < 0.3);
          for (let a = 0; a < still.length; a++) {
            for (let b2 = a + 1; b2 < still.length; b2++) {
              stackSamples++;
              const pa = still[a].position;
              const pb = still[b2].position;
              if (Math.hypot(pa.x - pb.x, pa.z - pb.z) < 1.0 && Math.abs(pa.y - pb.y) < 1) stackHits++;
            }
          }
        }
      }
      // two living bots OCCUPYING the same cover point (both standing on it, not just passing by)
      for (const { coverId } of ai._sys.cover.reservations()) {
        const cp = ai._sys.cover.get(coverId);
        let n = 0;
        for (const c of bots) {
          const still = Math.hypot(c.controller.velocity.x, c.controller.velocity.z) < 0.3;
          if (c.alive && still && Math.hypot(c.position.x - cp.pos.x, c.position.z - cp.pos.z) < 0.4 && Math.abs(c.position.y - cp.pos.y) < 1) n++;
        }
        if (n > 1) coverShare++;
      }
      // after a zone control change every living bot re-decides within the next tick
      for (const z of decisionsAfterZoneChange) {
        if (!z.pending || session.simTime - z.t < DT * 1.5) continue;
        z.pending = false;
        z.late = bots.filter((c) => c.alive && (ai.bot(c.id).lastDecisionAt ?? -1) < z.t - 1e-9).length;
      }
    },
  });
  offFired();
  offZone();
  const dbg = ai.getDebug();
  const kills = [0, 0, 0];
  const deaths = [0, 0, 0];
  const pair = {};
  for (const d of log.died) {
    const vt = teamOf.get(d.victimId);
    deaths[vt]++;
    if (d.attackerId && teamOf.has(d.attackerId)) {
      const at = teamOf.get(d.attackerId);
      kills[at]++;
      pair[`${at}->${vt}`] = (pair[`${at}->${vt}`] || 0) + 1;
    }
  }
  const dmgPairs = {};
  for (const d of log.damaged) {
    const k = `${teamOf.get(d.attackerId)}->${teamOf.get(d.victimId)}`;
    dmgPairs[k] = (dmgPairs[k] || 0) + 1;
  }
  const r = session.roundInfo();
  const reloadViolations = bots.reduce((a, c) => a + ai.bot(c.id).metrics.shotsDuringReload, 0);
  const summary = {
    seconds,
    withPlayer,
    scores: r.scores,
    zoneStatuses: [...statuses],
    controllers: [...controllers],
    zoneChanges: log.zone.length,
    teamInZoneS: inZoneTicks.map((n) => +(n * DT).toFixed(1)),
    kills,
    deaths,
    killPairs: pair,
    damagePairs: dmgPairs,
    shots: log.fired.length,
    friendlyFireBlocked: log.ff,
    targetViolations,
    playerTargetedByAllies: playerTargeted,
    maxStepPerTick: +maxH.toFixed(4),
    stuckEvents: dbg.metrics.stuck.length,
    // an event in the last seconds of the run may still be recovering when the run stops
    unrecoveredStuck: dbg.metrics.stuck.filter((s) => s.recoveredAt === null && s.t < session.simTime - 8).length,
    stuckStillRecoveringAtEnd: dbg.metrics.stuck.filter((s) => s.recoveredAt === null && s.t >= session.simTime - 8).length,
    recoveryMaxS: Math.max(0, ...dbg.metrics.stuck.map((s) => s.recoveryTime || 0)),
    reloadViolations,
    muzzleBlockedShots: muzzleShots,
    muzzleBlockedFraction: +(muzzleShots / Math.max(1, botShots)).toFixed(5),
    hitsThroughWall: throughWall,
    coverShareTicks: coverShare,
    teammateStackFraction: +(stackHits / Math.max(1, stackSamples)).toFixed(4),
    lateDecisionsAfterZoneChange: decisionsAfterZoneChange.reduce((a, z) => a + (z.late || 0), 0),
    reactionSamples: dbg.metrics.reactions.length,
    reactionMedianS: (() => {
      const a = dbg.metrics.reactions.map((x) => x.reaction).sort((u, v) => u - v);
      return a.length ? a[Math.floor(a.length / 2)] : null;
    })(),
    searches: dbg.metrics.searches.length,
    aiUpdateMsAvg: dbg.metrics.updateMsAvg,
    aiUpdateMsMax: dbg.metrics.updateMsMax,
  };
  return { ctx, summary };
}

function checkMatch(s) {
  assert.ok(s.teamInZoneS.every((x) => x > 0), `all three teams reached the zone: ${s.teamInZoneS}`);
  assert.ok(s.kills.every((k) => k > 0), `all three teams scored kills: ${s.kills}`);
  const pairs = Object.keys(s.damagePairs).filter((k) => k[0] !== k[3]);
  assert.ok(pairs.length >= 4, `teams fight each other (damage pairs ${pairs})`);
  assert.ok(s.controllers.length >= 2, `zone changed hands: controllers ${s.controllers}`);
  assert.ok(s.zoneStatuses.includes('contested'), 'ties (contested) occur');
  assert.equal(s.targetViolations, 0, 'no bot targets a teammate');
  assert.equal(s.playerTargetedByAllies, 0, 'allies never target the player');
  assert.equal(s.friendlyFireBlocked, 0, 'no friendly round was fired into a teammate');
  assert.ok(s.maxStepPerTick <= 5.8 * DT + 0.02, `no teleport (max step ${s.maxStepPerTick})`);
  assert.equal(s.unrecoveredStuck, 0, 'every stuck event recovered');
  assert.equal(s.reloadViolations, 0, 'no trigger while reloading');
  assert.equal(s.hitsThroughWall, 0, 'no bot round passed a wall because only the eye saw the target');
  assert.ok(s.muzzleBlockedFraction < 0.005, `the AI rarely pulls the trigger with a blocked muzzle (${s.muzzleBlockedShots} rounds)`);
  assert.ok(s.coverShareTicks * DT < 1.0, `no two bots on one cover point (${(s.coverShareTicks * DT).toFixed(2)} s)`);
  assert.equal(s.lateDecisionsAfterZoneChange, 0, 'every bot re-decides after a zone control change');
  assert.ok(s.teammateStackFraction < 0.03, `teammates spread out (stationary pairs < 1 m: ${s.teammateStackFraction})`);
}

test('AI-04: 3 minutes, player idle — all teams go to the zone and fight, zone changes hands, ties, allies never target the player', () => {
  const { summary } = matchRun({ seconds: 180, withPlayer: true, seed: 41 });
  console.log('AI-04 match (player idle)', JSON.stringify(summary));
  checkMatch(summary);
});

test('AI-04: 2 minutes without the player (17 bots)', () => {
  const { summary } = matchRun({ seconds: 120, withPlayer: false, seed: 42 });
  console.log('AI-04 match (no player)', JSON.stringify(summary));
  checkMatch(summary);
});

test('AI-04: tasks are re-evaluated on death, respawn and round reset (memory, cover, blocks cleared)', () => {
  const ctx = createArenaSession({ bots: [5, 6, 6], withPlayer: true, seed: 43, zone: 'arena_center' });
  const { session, ai } = ctx;
  run(ctx, Math.round(25 / DT), { playerCmd: idleCmd() });
  // death: the bot drops its cover and memory, its task becomes 'dead'
  const victim = session.combatants.bots().find((c) => c.alive && ai.bot(c.id).memory.size > 0) || session.combatants.bots().find((c) => c.alive);
  const b = ai.bot(victim.id);
  session.forceKill(victim.id);
  run(ctx, 1, { playerCmd: idleCmd() });
  assert.equal(b.task, 'dead');
  assert.equal(b.memory.size, 0);
  assert.equal(ai._sys.cover.reservedBy(victim.id), null, 'cover released on death');
  for (const other of session.combatants.bots()) assert.equal(ai.bot(other.id).memory.get(victim.id), null, 'everybody forgot the dead combatant');
  // respawn (after the respawn delay, when a safe spawn point exists): fresh brain, decides immediately
  run(ctx, Math.round(30 / DT), { playerCmd: idleCmd(), onTick: () => !victim.alive });
  run(ctx, 2, { playerCmd: idleCmd() });
  assert.ok(victim.alive, 'respawned');
  assert.ok(['objective', 'engage', 'cover', 'search'].includes(b.task), `task after respawn: ${b.task}`);
  assert.ok(b.lives >= 2);
  // round reset: everything cleared, then all bots head for the zone again
  const beforeBlocks = ai._sys.nav.blocks.length;
  session.resetRound({ skipPreRound: true });
  assert.equal(ai._sys.cover.reservations().length, 0, 'reservations cleared on reset');
  assert.equal(ai._sys.nav.blocks.length, 0, `navmesh blocks cleared on reset (were ${beforeBlocks})`);
  for (const c of session.combatants.bots()) {
    const bb = ai.bot(c.id);
    assert.equal(bb.memory.size, 0, 'memory cleared on reset');
    assert.equal(bb.move.path.length, 0, 'paths cleared on reset');
  }
  run(ctx, Math.round(2 / DT), { playerCmd: idleCmd() });
  const tasks = session.combatants.bots().map((c) => ai.bot(c.id).task);
  assert.ok(tasks.filter((t) => t === 'objective').length >= 12, `after the reset the bots go for the zone: ${tasks}`);
});
