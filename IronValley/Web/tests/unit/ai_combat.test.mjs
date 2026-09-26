// AI-03 — combat behaviour on the real game integration: reaction time and hit rate vs distance follow
// Shared/config/ai.json, data-driven bursts, no firing while reloading, limited turn rate, and the same
// muzzle rule as the player (no hits through walls when only the eye sees the target).
import test from 'node:test';
import assert from 'node:assert/strict';
import { Vector3 } from 'three';
import { createArenaSession, place, run, idleCmd, arenaLevel, aiJson, DT, DEG } from './support/aiSim.mjs';
import { detectTimeAt } from '../../src/ai/perception.js';
import { aimSigmaDeg, gaussian } from '../../src/ai/aim.js';
import { raycastShapes } from '../../src/game/hitShapes.js';
import { createRng } from '../../src/util/rng.js';

const T = arenaLevel().aiTest;
const TOUGH = { combat: { maxHealth: 1000000 } };

function duel({ seed, tuning = null }) {
  const ctx = createArenaSession({ bots: [0, 1, 0], seed, zone: 'arena_yard', tuning, rulesPatch: TOUGH });
  run(ctx, 2, { playerCmd: idleCmd() });
  ctx.ai.setGuardMode(true);
  const bot = ctx.ai.bot('bot_1_0');
  return { ctx, bot, c: bot.c, player: ctx.session.player };
}

/** Engagement at distance d on the free lane; returns measurements. */
function engage(d, { seed, seconds = 14, tuning = null, checkEachTick = null }) {
  const { ctx, bot, c, player } = duel({ seed, tuning });
  const B = T.vision.bot;
  place(ctx.session, 'bot_1_0', B, T.vision.botYawDeg);
  ctx.ai.setLookHint('bot_1_0', T.vision.botYawDeg, 60); // the guard watches the lane
  place(ctx.session, 'player', [B[0] - 5, 0, B[2]], 90); // behind the bot: unseen
  run(ctx, 20, { playerCmd: idleCmd(90) });
  place(ctx.session, 'bot_1_0', B, T.vision.botYawDeg);
  place(ctx.session, 'player', [B[0] + d, 0, B[2]], 90);
  const t0 = ctx.session.simTime;
  const shots = [];
  const hits = [];
  const blockedByMuzzle = [];
  const perShot = [];
  const cfg = ctx.ai.cfg;
  const offShots = ctx.events.on('weapon:fired', (p) => {
    if (p.shooterId !== c.id) return;
    shots.push(ctx.session.simTime);
    if (p.result && p.result.blockedBy === 'eye-to-muzzle') blockedByMuzzle.push(ctx.session.simTime);
    // the configured error model for exactly this shot (same inputs the AI used) + the weapon's recoil
    const eye = c.getEye(new Vector3());
    const sh = player.hitShapes();
    const aimPoint = sh[1].a.clone().lerp(sh[1].b, 0.75);
    const sigma = aimSigmaDeg(cfg, {
      distance: eye.distanceTo(aimPoint),
      targetLateralSpeed: 0,
      ownSpeed: Math.hypot(c.controller.velocity.x, c.controller.velocity.z),
      runSpeed: 3.5,
      crouched: c.controller.crouched,
      trackTime: bot.aim.trackTime,
    });
    perShot.push({ sigma, eye, aimPoint, recoilPitch: c.weapon.recoil.pitch, recoilYaw: c.weapon.recoil.yaw, shapes: sh.map((x) => ({ ...x, a: x.a.clone(), b: x.b.clone(), center: x.center.clone() })) });
  });
  const offHits = ctx.events.on('combatant:damaged', (p) => {
    if (p.attackerId === c.id && p.victimId === 'player') hits.push(ctx.session.simTime);
  });
  let reloadViolations = 0;
  let reloads = 0;
  let maxTurn = 0;
  let prevYaw = c.yaw;
  run(ctx, Math.round(seconds / DT), {
    playerCmd: idleCmd(90),
    onTick: () => {
      maxTurn = Math.max(maxTurn, Math.abs(Math.atan2(Math.sin(c.yaw - prevYaw), Math.cos(c.yaw - prevYaw))));
      prevYaw = c.yaw;
      if (checkEachTick) checkEachTick(ctx, bot);
    },
  });
  offShots();
  offHits();
  // reload discipline is checked through the AI's own counter (cmd.fire while the weapon was not ready)
  reloadViolations = bot.metrics.shotsDuringReload;
  reloads = c.weapon.state.reloadsCompleted;
  const eye = c.getEye(new Vector3());
  const chest = (() => {
    const s = player.hitShapes();
    return s[1].a.clone().lerp(s[1].b, 0.75);
  })();
  return { ctx, bot, c, player, t0, shots, hits, blockedByMuzzle, reloadViolations, reloads, maxTurn, distance: eye.distanceTo(chest), eye, chest, perShot };
}

/** Bursts = groups of shots less than 0.12 s apart (cadence 0.08 s). */
function bursts(times) {
  const out = [];
  let cur = [];
  for (const t of times) {
    if (cur.length && t - cur[cur.length - 1] > 0.12) {
      out.push(cur);
      cur = [];
    }
    cur.push(t);
  }
  if (cur.length) out.push(cur);
  return out;
}

/**
 * Hit probability predicted by the configured aim model for each recorded shot: angular error
 * N(0, sigma^2) per axis with sigma from ai.json (aimSigmaDeg, the same formula and inputs the AI used),
 * plus the weapon's recoil offset at that shot, against the target's real hit shapes (Monte-Carlo).
 */
function predictedHitRate(perShot, samples = 1500) {
  const rng = createRng(99);
  const dir = new Vector3();
  let sum = 0;
  for (const s of perShot) {
    const base = new Vector3().subVectors(s.aimPoint, s.eye);
    const d = base.length();
    base.divideScalar(d);
    const yaw0 = Math.atan2(-base.x, -base.z) + s.recoilYaw;
    const pitch0 = Math.asin(base.y) + s.recoilPitch;
    let hit = 0;
    for (let i = 0; i < samples; i++) {
      const yaw = yaw0 + gaussian(rng) * s.sigma * DEG;
      const pitch = pitch0 + gaussian(rng) * s.sigma * DEG;
      dir.set(-Math.sin(yaw) * Math.cos(pitch), Math.sin(pitch), -Math.cos(yaw) * Math.cos(pitch));
      if (raycastShapes(s.shapes, s.eye, dir, d + 2)) hit++;
    }
    sum += hit / samples;
  }
  return perShot.length ? sum / perShot.length : 0;
}

test('AI-03: reaction time before the first shot is nonzero and follows the configured detection + reaction delay', () => {
  const cfg = aiJson();
  const rows = [];
  for (const d of [10, 20, 40]) {
    for (let trial = 0; trial < 4; trial++) {
      const r = engage(d, { seed: 100 + trial * 7 + d, seconds: 3 });
      assert.ok(r.shots.length > 0, `no shot at ${d} m`);
      const reaction = r.shots[0] - r.t0;
      const det = detectTimeAt(cfg, r.distance);
      const lo = det + cfg.combat.reactionDelayMin - 0.1;
      const hi = det + cfg.combat.reactionDelayMax + 0.45; // + perception tick, turn / aim settle into the fire cone
      rows.push({ d, trial, reaction: +reaction.toFixed(3), expectedMin: +lo.toFixed(3), expectedMax: +hi.toFixed(3) });
      assert.ok(reaction >= lo && reaction <= hi, `d=${d} reaction ${reaction.toFixed(3)} outside [${lo.toFixed(3)}, ${hi.toFixed(3)}]`);
      assert.ok(reaction >= 0.3, 'no instant aimbot');
    }
  }
  const byD = (d) => rows.filter((r) => r.d === d).map((r) => r.reaction);
  const mean = (a) => a.reduce((s, x) => s + x, 0) / a.length;
  console.log('AI-03 reaction', JSON.stringify({ mean10: +mean(byD(10)).toFixed(3), mean20: +mean(byD(20)).toFixed(3), mean40: +mean(byD(40)).toFixed(3), rows }));
  assert.ok(mean(byD(40)) > mean(byD(10)), 'reaction grows with distance');
});

test('AI-03: hit rate vs distance follows the aim model of ai.json; bursts are data-driven; no firing while reloading; turn rate respected', () => {
  const cfg = aiJson();
  const out = [];
  for (const d of [10, 20, 40]) {
    // three engagements per distance (the aim noise is time-correlated: pool several runs)
    const runs = [0, 1, 2].map((k) => engage(d, { seed: 300 + d + k, seconds: 25 }));
    const shots = runs.reduce((a, r) => a + r.shots.length, 0);
    const hits = runs.reduce((a, r) => a + r.hits.length, 0);
    const rate = hits / Math.max(1, shots);
    const r = runs[0];
    const band = cfg.combat.bursts.find((b) => r.distance <= b.maxDist);
    const bl = runs.flatMap((x) => bursts(x.shots).map((b) => b.length));
    const perShot = runs.flatMap((x) => x.perShot);
    const predicted = predictedHitRate(perShot);
    const meanSigma = perShot.reduce((a, x) => a + x.sigma, 0) / perShot.length;
    // tolerance: 3 standard deviations of a binomial rate inflated x1.6 for the time-correlated noise
    const tol = 3 * 1.6 * Math.sqrt((predicted * (1 - predicted)) / shots) + 0.03;
    const reloads = runs.reduce((a, x) => a + x.reloads, 0);
    const reloadViolations = runs.reduce((a, x) => a + x.reloadViolations, 0);
    const muzzleBlocked = runs.reduce((a, x) => a + x.blockedByMuzzle.length, 0);
    const maxTurn = Math.max(...runs.map((x) => x.maxTurn));
    out.push({ d, distance: +r.distance.toFixed(1), shots, hits, rate: +rate.toFixed(3), predicted: +predicted.toFixed(3), tolerance: +tol.toFixed(3), perRun: runs.map((x) => +(x.hits.length / x.shots.length).toFixed(3)), meanSigmaDeg: +meanSigma.toFixed(2), burstLengths: bl.slice(0, 30), band: [band.shotsMin, band.shotsMax], reloads, reloadViolations, maxTurnDegPerTick: +(maxTurn / DEG).toFixed(2), muzzleBlockedShots: muzzleBlocked });
    assert.ok(shots >= 60, `enough shots at ${d} m`);
    assert.ok(Math.abs(rate - predicted) <= tol, `d=${d}: hit rate ${rate.toFixed(3)} vs model ${predicted.toFixed(3)} (+-${tol.toFixed(3)})`);
    // bursts: never longer than the configured maximum; most bursts within the band
    assert.ok(bl.every((n) => n <= band.shotsMax), `burst longer than ${band.shotsMax}: ${bl}`);
    const inBand = bl.filter((n) => n >= band.shotsMin).length / bl.length;
    assert.ok(inBand >= 0.6, `bursts mostly within [${band.shotsMin}, ${band.shotsMax}]: ${bl}`);
    assert.equal(reloadViolations, 0, 'trigger held while reloading');
    assert.equal(muzzleBlocked, 0, 'no shot with a blocked muzzle');
    assert.ok(maxTurn <= cfg.turnRateDegPerSec * DEG * DT + 1e-6, 'turn rate limit');
  }
  for (let i = 1; i < out.length; i++) assert.ok(out[i].rate <= out[i - 1].rate + 0.05, 'hit rate must not grow with distance');
  assert.ok(out.some((o) => o.reloads > 0), 'reloads happened during the engagements');
  console.log('AI-03 hit rate', JSON.stringify(out));
});

test('AI-03: accuracy is data-driven (3x aim error in ai.json -> clearly lower hit rate at 20 m)', () => {
  const base = engage(20, { seed: 420, seconds: 14 });
  const sloppy = engage(20, { seed: 420, seconds: 14, tuning: { aim: { baseErrorDeg: aiJson().aim.baseErrorDeg * 3 } } });
  const rb = base.hits.length / base.shots.length;
  const rs = sloppy.hits.length / sloppy.shots.length;
  console.log('AI-03 config sensitivity', JSON.stringify({ base: +rb.toFixed(3), tripleError: +rs.toFixed(3) }));
  assert.ok(rs < rb * 0.7, `higher configured error must lower the hit rate (${rb.toFixed(3)} -> ${rs.toFixed(3)})`);
});

test('AI-03: a 180 deg turn takes time (turn rate), the reaction includes it', () => {
  const cfg = aiJson();
  const { ctx, c } = duel({ seed: 510 });
  const B = T.vision.bot;
  // bot looks west, the player appears east behind it (the bot must first notice it: a pistol shot)
  place(ctx.session, 'bot_1_0', B, 90);
  ctx.ai.setLookHint('bot_1_0', 90, 60); // looks west, away from the player
  place(ctx.session, 'player', [B[0] + 15, 0, B[2]], 90, -60);
  run(ctx, 10, { playerCmd: idleCmd(90, { pitch: -60 * DEG }) });
  const yaw0 = c.yaw;
  run(ctx, 1, { playerCmd: idleCmd(90, { pitch: -60 * DEG, fire: true }) });
  let maxStep = 0;
  let prev = c.yaw;
  let turnedAt = null;
  const t0 = ctx.session.simTime;
  run(ctx, 90, {
    playerCmd: idleCmd(90, { pitch: -60 * DEG }),
    onTick: () => {
      const step = Math.abs(Math.atan2(Math.sin(c.yaw - prev), Math.cos(c.yaw - prev)));
      maxStep = Math.max(maxStep, step);
      prev = c.yaw;
      const fromStart = Math.abs(Math.atan2(Math.sin(c.yaw - yaw0), Math.cos(c.yaw - yaw0)));
      if (turnedAt === null && fromStart > 150 * DEG) turnedAt = ctx.session.simTime - t0;
    },
  });
  const minTime = Math.PI / ((cfg.turnRateDegPerSec * Math.PI) / 180);
  console.log('AI-03 turn', JSON.stringify({ maxStepDegPerTick: +(maxStep / DEG).toFixed(2), limitDegPerTick: +(cfg.turnRateDegPerSec * DT).toFixed(2), turnedAfterS: turnedAt === null ? null : +turnedAt.toFixed(3), minPossibleS: +minTime.toFixed(3) }));
  assert.ok(turnedAt !== null, 'bot turned towards the gunshot');
  assert.ok(maxStep <= cfg.turnRateDegPerSec * DEG * DT + 1e-6, 'per-tick turn limited');
  assert.ok(turnedAt >= 150 / cfg.turnRateDegPerSec - DT, 'no big turn in one tick: at least 150/turnRate seconds');
});

test('AI-03: muzzle rule — eye sees the target but the muzzle is inside a wall: the shot is blocked (same D8 validation) and the AI does not pull the trigger', () => {
  const { ctx, bot, c, player } = duel({ seed: 610 });
  // west edge of the high block h_nw (x -9.5, z -6.2..-5.6): eye 6 cm west of the edge, muzzle inside the block
  const spot = [-9.56, 0, -5.24];
  place(ctx.session, 'bot_1_0', spot, 0);
  ctx.ai.setLookHint('bot_1_0', 0, 60);
  place(ctx.session, 'player', [-9.6, 0, -22], 180);
  run(ctx, 1, { playerCmd: idleCmd(180) });
  place(ctx.session, 'bot_1_0', spot, 0);
  const wq = ctx.session.worldQuery;
  const eye = c.getEye(new Vector3());
  const chest = player.hitShapes()[1].center.clone();
  assert.ok(wq.lineOfSight(eye, chest, { ignoreId: c.id }), 'the eye sees the target');
  const muzzle = c.muzzleWorld(new Vector3());
  const toM = muzzle.clone().sub(eye);
  assert.ok(wq.raycastStatic(eye, toM.clone().normalize(), toM.length()), 'eye -> muzzle crosses the wall');
  // (1) authoritative rule: drive the bot's trigger directly (AI bypassed) aiming at the chest
  const yaw = Math.atan2(-(chest.x - eye.x), -(chest.z - eye.z));
  const pitch = Math.atan2(chest.y - eye.y, Math.hypot(chest.x - eye.x, chest.z - eye.z));
  const fired = [];
  const off = ctx.events.on('weapon:fired', (p) => p.shooterId === c.id && fired.push(p));
  const hp0 = player.health;
  c.yaw = yaw;
  c.pitch = pitch;
  c.applyCommand({ ...idleCmd(), yaw, pitch, fire: true }, DT);
  c.applyCommand({ ...idleCmd(), yaw, pitch, fire: false }, DT);
  off();
  assert.equal(fired.length, 1, 'one round fired');
  assert.equal(fired[0].result.blocked, true);
  assert.equal(fired[0].result.blockedBy, 'eye-to-muzzle');
  assert.equal(player.health, hp0, 'no damage through the wall');
  // (2) the AI in the same spot sees the player but does not fire while the muzzle is blocked
  const aiShots = [];
  const off2 = ctx.events.on('weapon:fired', (p) => p.shooterId === c.id && aiShots.push(p));
  let heldForMuzzle = 0;
  let firedWhileBlocked = 0;
  run(ctx, 180, {
    playerCmd: idleCmd(180),
    onTick: () => {
      if (bot.fireBlockedReason === 'muzzle_blocked') heldForMuzzle++;
    },
  });
  off2();
  for (const p of aiShots) if (p.result.blockedBy === 'eye-to-muzzle') firedWhileBlocked++;
  console.log('AI-03 muzzle', JSON.stringify({ authoritativeBlocked: fired[0].result.blockedBy, aiTicksHeldForMuzzle: heldForMuzzle, stepOuts: bot.metrics.stepOuts || 0, aiShots: aiShots.length, aiShotsWithBlockedMuzzle: firedWhileBlocked }));
  assert.equal(firedWhileBlocked, 0, 'AI never fires with a blocked muzzle');
  assert.ok(heldForMuzzle > 0, 'the AI held fire while its muzzle was blocked');
  assert.ok(aiShots.length > 0 && bot.metrics.stepOuts > 0, 'then it stepped out and fired with a clear muzzle');
});
