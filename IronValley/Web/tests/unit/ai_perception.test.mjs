// AI-01 — vision, hearing and memory on the real game integration (MatchSession + Combatant + WorldQuery)
// in the AI arena. The player is scripted (teleports = no footsteps); the bot is driven by the real AI.
import test from 'node:test';
import assert from 'node:assert/strict';
import { Vector3 } from 'three';
import { createArenaSession, place, run, idleCmd, arenaLevel, DT, DEG } from './support/aiSim.mjs';
import { detectTimeAt } from '../../src/ai/perception.js';

const T = arenaLevel().aiTest;

function duel({ seed = 11, tuning = null } = {}) {
  // player (team 0) vs one bot (team 1); guard mode = no zone objective, the bot holds its spot
  const ctx = createArenaSession({ bots: [0, 1, 0], seed, zone: 'arena_yard', tuning });
  run(ctx, 2, { playerCmd: idleCmd() });
  ctx.ai.setGuardMode(true);
  const bot = ctx.ai.bot('bot_1_0');
  return { ctx, bot, c: bot.c, player: ctx.session.player };
}

const chestOf = (c) => {
  const s = c.hitShapes();
  return s[1].a.clone().lerp(s[1].b, 0.75);
};

test('AI-01a: visible player is detected after the configured detection time (nonzero, grows with distance)', () => {
  const results = [];
  for (const target of T.vision.targets.slice(0, 4)) {
    const { ctx, bot, c, player } = duel();
    // player out of view first (behind the bot), bot facing east along the free lane
    place(ctx.session, 'bot_1_0', T.vision.bot, T.vision.botYawDeg);
    ctx.ai.setLookHint('bot_1_0', T.vision.botYawDeg, 60); // the guard watches the lane
    place(ctx.session, 'player', [T.vision.bot[0] - 6, 0, T.vision.bot[2]], 0);
    run(ctx, 30, { playerCmd: idleCmd(0) });
    assert.equal(bot.memory.get('player'), null, 'player behind the bot must not be known');
    place(ctx.session, 'bot_1_0', T.vision.bot, T.vision.botYawDeg);
    place(ctx.session, 'player', target, 90);
    const t0 = ctx.session.simTime;
    let tDetect = null;
    run(ctx, 240, {
      playerCmd: idleCmd(90),
      onTick: () => {
        const e = bot.memory.get('player');
        if (e && e.seen) {
          tDetect = ctx.session.simTime - t0;
          return false;
        }
        return true;
      },
    });
    const eye = c.getEye(new Vector3());
    const d = eye.distanceTo(chestOf(player));
    const expected = detectTimeAt(ctx.ai.cfg, d);
    results.push({ d: +d.toFixed(2), expected: +expected.toFixed(3), measured: tDetect === null ? null : +tDetect.toFixed(3) });
    assert.ok(tDetect !== null, `not detected at ${d.toFixed(1)} m`);
    assert.ok(tDetect > 0.1, `detection must take time (got ${tDetect})`);
    // perception runs at 10 Hz: the detection lands on the first perception tick after the configured time
    assert.ok(tDetect >= expected - 0.1 - 1e-6 && tDetect <= expected + 0.25, `d=${d.toFixed(1)} expected ${expected.toFixed(3)} measured ${tDetect.toFixed(3)}`);
  }
  for (let i = 1; i < results.length; i++) assert.ok(results[i].measured >= results[i - 1].measured - 0.1, 'detection time must not shrink with distance');
  console.log('AI-01a detection', JSON.stringify(results));
});

test('AI-01b: silent player behind an opaque wall is NOT detected for 20 s; memory never holds its position', () => {
  const { ctx, bot, c, player } = duel({ seed: 12 });
  place(ctx.session, 'bot_1_0', T.wall.bot, T.wall.botYawDeg);
  ctx.ai.setLookHint('bot_1_0', T.wall.botYawDeg, 60); // looks straight at the wall behind which the player stands
  place(ctx.session, 'player', T.wall.target, 0);
  // sanity: the wall is between them (no line of sight), and they are close (6 m)
  const eye = c.getEye(new Vector3());
  assert.equal(ctx.session.worldQuery.lineOfSight(eye, player.getEye(new Vector3()), { ignoreId: c.id }), false);
  const raysBefore = bot.perception.stats.raysCast;
  let maxDetect = 0;
  let everKnown = false;
  run(ctx, Math.round(20 / DT), {
    playerCmd: idleCmd(0),
    onTick: () => {
      maxDetect = Math.max(maxDetect, bot.perception.detect.get('player') || 0);
      if (bot.memory.get('player')) everKnown = true;
      for (const e of bot.memory.entries.values()) {
        assert.ok(e.pos.distanceTo(player.position) > 0.01, 'memory holds the true player position');
      }
    },
  });
  assert.equal(everKnown, false, 'bot must not know about the hidden silent player');
  assert.equal(maxDetect, 0, 'no detection progress through the wall');
  assert.ok(bot.perception.stats.raysCast > raysBefore + 100, 'the bot kept casting line-of-sight rays towards the player (it looks at the wall)');
  assert.ok(ctx.ai.getDebug().metrics.perceptionUpdates >= 190, 'perception updated ~10 Hz for 20 s');
  console.log('AI-01b perception updates', ctx.ai.getDebug().metrics.perceptionUpdates, 'rays', bot.perception.stats.raysCast);
});

test('AI-01c: a gunshot behind the wall gives an APPROXIMATE position and starts a search that ends', () => {
  const { ctx, bot, c, player } = duel({ seed: 13 });
  place(ctx.session, 'bot_1_0', T.gunshot.bot, T.gunshot.botYawDeg);
  place(ctx.session, 'player', T.gunshot.shooter, 0, -60);
  run(ctx, 20, { playerCmd: idleCmd(0, { pitch: -60 * DEG }) });
  assert.equal(bot.memory.get('player'), null);
  // one shot into the ground
  const trueFeet = player.position.clone();
  run(ctx, 1, { playerCmd: idleCmd(0, { pitch: -60 * DEG, fire: true }) });
  run(ctx, 1, { playerCmd: idleCmd(0, { pitch: -60 * DEG }) });
  const e = bot.memory.get('player');
  assert.ok(e, 'the gunshot must be heard');
  assert.equal(e.source, 'hearing');
  assert.equal(e.seen, false);
  const err = Math.hypot(e.pos.x - trueFeet.x, e.pos.z - trueFeet.z);
  const H = ctx.ai.cfg.hearing;
  const d = c.getEye(new Vector3()).distanceTo(trueFeet);
  const maxErr = (H.errorBase + H.errorPerMeter * d) * H.occludedErrorMult + 1e-6;
  assert.ok(err > 0.02, `hearing must not give the exact position (error ${err})`);
  assert.ok(err <= maxErr, `error ${err.toFixed(2)} within the configured bound ${maxErr.toFixed(2)}`);
  const heardPos = e.pos.clone();
  // the player leaves silently (teleport) to the north-west yard, hidden behind the 3 m wall line, so the
  // search finds nothing
  place(ctx.session, 'player', [-30, 0, -32], 0);
  const start = c.position.clone();
  let searched = false;
  let minDist = Infinity;
  let searchEnded = null;
  run(ctx, Math.round(40 / DT), {
    playerCmd: idleCmd(0),
    onTick: () => {
      if (bot.task === 'search' && bot.search) {
        searched = true;
        assert.ok(bot.search.pos.distanceTo(player.position) > 1, 'search goal must not follow the true position');
      }
      minDist = Math.min(minDist, Math.hypot(c.position.x - heardPos.x, c.position.z - heardPos.z));
      if (searched && bot.task !== 'search' && searchEnded === null) searchEnded = ctx.session.simTime;
    },
  });
  const searches = ctx.ai.getDebug().metrics.searches.filter((s) => s.bot === 'bot_1_0');
  assert.ok(searched, 'bot must start a search');
  assert.ok(minDist < 6, `bot must walk (around the wall) to the heard position (closest ${minDist.toFixed(1)} m, start ${start.distanceTo(heardPos).toFixed(1)} m)`);
  assert.ok(searchEnded !== null && searches.length >= 1, 'search must end (give up)');
  assert.equal(bot.memory.get('player'), null, 'after an unsuccessful search the contact is forgotten');
  console.log('AI-01c hearing error', err.toFixed(2), 'm (bound', maxErr.toFixed(2), ') search', JSON.stringify(searches[0]), 'closest approach', minDist.toFixed(2));
});

test('AI-01d: after losing sight the last known position is NOT updated without a new stimulus; dead / respawned targets are forgotten', () => {
  const { ctx, bot, player } = duel({ seed: 14, tuning: { combat: { reactionDelayMin: 5, reactionDelayMax: 5 } } });
  place(ctx.session, 'bot_1_0', T.loseSight.bot, T.loseSight.botYawDeg);
  ctx.ai.setLookHint('bot_1_0', T.loseSight.botYawDeg, 60);
  place(ctx.session, 'player', T.loseSight.target, 180);
  run(ctx, 60, { playerCmd: idleCmd(180) });
  let e = bot.memory.get('player');
  assert.ok(e && e.seen, 'player in the open must be seen');
  // hide behind the container and then move further away, silently (teleports, no footsteps / shots)
  place(ctx.session, 'player', T.loseSight.hideAt, 180);
  run(ctx, 12, { playerCmd: idleCmd(180) });
  e = bot.memory.get('player');
  assert.ok(e, 'contact remembered after losing sight');
  const lastKnown = e.pos.clone();
  const updates = e.updates;
  assert.ok(lastKnown.distanceTo(new Vector3(...T.loseSight.target)) < 0.3, 'last known = where it was last seen');
  run(ctx, 60, { playerCmd: idleCmd(180) });
  place(ctx.session, 'player', T.loseSight.moveTo, 180);
  let violations = 0;
  let seenAgain = false;
  run(ctx, Math.round(6 / DT), {
    playerCmd: idleCmd(180),
    onTick: () => {
      const m = bot.memory.get('player');
      if (!m) return;
      if (m.seen) {
        seenAgain = true;
        return false;
      }
      if (m.updates !== updates || m.pos.distanceTo(lastKnown) > 1e-6) violations++;
    },
  });
  assert.equal(violations, 0, 'last known position changed without a stimulus');
  const m = bot.memory.get('player');
  if (m && !seenAgain) {
    assert.ok(m.pos.distanceTo(player.position) > 3, 'memory must not track the true position');
    assert.ok(m.conf < 1, 'confidence decays');
  }
  // forgetting a dead target
  place(ctx.session, 'player', T.loseSight.target, 180);
  run(ctx, 60, { playerCmd: idleCmd(180) });
  assert.ok(bot.memory.get('player'), 'seen again in the open');
  ctx.session.forceKill('player');
  run(ctx, 1, { playerCmd: idleCmd(180) });
  assert.equal(bot.memory.get('player'), null, 'dead target forgotten immediately');
  // respawned target stays unknown until perceived again
  run(ctx, Math.round(6 / DT), { playerCmd: idleCmd(180) });
  assert.ok(player.alive, 'player respawned');
  const k = bot.memory.get('player');
  assert.ok(!k || k.firstSeen > 0, 'respawned target is not carried over from before the death');
  console.log('AI-01d last known kept', lastKnown.toArray().map((v) => +v.toFixed(2)), 'updates', updates, 'seenAgain', seenAgain);
});
