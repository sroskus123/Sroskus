// AudioSystem (src/audio/audioSystem.js) with a fake AudioContext: event -> sound mapping, spatial / distance
// variants, near-miss, voice limits, occlusion, stop on death / pause / round reset, nothing plays without an
// event, master chain and volume; plus consistency of the generated bank with the runtime files (SND-01).
import test from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, statSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { EventBus } from '../../src/engine/events.js';
import { AudioSystem, closestApproach, shotLayerWeights, airCutoff, compressorMakeup } from '../../src/audio/audioSystem.js';
import audioConfig from '../../src/data/audio.json' with { type: 'json' };
import bank from '../../src/data/audio_bank.json' with { type: 'json' };
import settingsDefaults from '../../src/data/settings_defaults.json' with { type: 'json' };
import { Settings } from '../../src/player/settings.js';
import { FakeAudioContext, fakeEncoded } from './support/fakeAudioContext.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const publicDir = path.resolve(here, '../../public');

function seeded(seed = 1) {
  let s = seed >>> 0;
  return () => {
    s = (s + 0x6d2b79f5) >>> 0;
    let t = s;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const flush = () => new Promise((r) => setImmediate(r));

/** A ready system: unlocked fake context, every bank file "decoded" with its real duration. */
async function makeSystem({ state = 'playing', raycast = null, positions = {}, leadIn = 0 } = {}) {
  const events = new EventBus();
  const settings = new Settings({ storage: null });
  const ctx = new FakeAudioContext();
  const sys = new AudioSystem({
    events,
    settings,
    isPlayer: (id) => id === 'p',
    raycast,
    createContext: () => ctx,
    fetchBuffer: (url) => {
      const f = url.split('/').pop();
      const meta = bank.files[f];
      return Promise.resolve(fakeEncoded({ duration: meta.duration, channels: meta.channels, leadIn }));
    },
    combatantPosition: (id) => positions[id] || null,
    random: seeded(7),
  });
  await sys.prefetch();
  assert.equal(sys.unlock(), true);
  await flush();
  await flush();
  sys.setListener({ x: 0, y: 1.65, z: 0 }, { x: 0, y: 0, z: -1 }, { x: 0, y: 1, z: 0 });
  if (state) events.emit('game:state', { state });
  return { sys, events, ctx, settings };
}

const keyOf = (file) => bank.files[file].key;
/** Keys of buffer sources started since index `from` (optionally excluding ambience). */
function startedKeys(ctx, from = 0, { ambience = false } = {}) {
  return ctx.started
    .slice(from)
    .filter((s) => s.buffer && s.buffer.sampleRate)
    .map((s) => s.__key)
    .filter((k) => ambience || !k.startsWith('amb_'));
}

// tag every started source with its bank key (the system sets src.buffer from the decoded map)
function tagSources(sys, ctx) {
  const byBuffer = new Map();
  for (const [f, b] of sys.buffers) byBuffer.set(b.buffer, keyOf(f));
  for (const s of ctx.started) if (s.buffer && byBuffer.has(s.buffer)) s.__key = byBuffer.get(s.buffer);
}

function played(sys, ctx, from = 0, opts) {
  tagSources(sys, ctx);
  return startedKeys(ctx, from, opts);
}

const V = (x, y, z) => ({ x, y, z });
const fired = (over = {}) => ({ shooterId: 'p', team: 0, weaponId: 'iv7_carbine', muzzle: V(0.1, 1.5, -0.8), dir: V(0, 0, -1), loudness: 1, shot: { hitPoint: null, hitKind: null }, ...over });

test('SND: bank and config are consistent; every runtime file exists; payload is small', () => {
  const keys = new Set(Object.keys(bank.sounds));
  const referenced = [];
  for (const w of Object.values(audioConfig.weapons)) {
    referenced.push(w.close, w.distant, w.tail, w.dry, w.draw, w.casing, w.nearMiss, w.magOut.key, ...Object.values(w.actions));
  }
  for (const k of ['step', 'impact']) referenced.push(...Object.values(audioConfig.surfaces[k]));
  referenced.push(audioConfig.footsteps.landThump, audioConfig.movement.jump, audioConfig.movement.traverse, audioConfig.switch.cloth, audioConfig.ambience.wind, audioConfig.ambience.birds);
  for (const k of referenced) assert.ok(keys.has(k), `sound key ${k} missing in audio_bank.json`);
  let total = 0;
  for (const [f, meta] of Object.entries(bank.files)) {
    const p = path.join(publicDir, bank.basePath, f);
    assert.ok(existsSync(p), `missing runtime file ${f}`);
    assert.equal(statSync(p).size, meta.bytes, `${f} size differs from the bank (rebuild with Tools/audio/build_audio.py)`);
    assert.ok(meta.truePeakDb <= -0.5, `${f} true peak ${meta.truePeakDb} dBFS`);
    total += meta.bytes;
  }
  assert.ok(total < 4 * 1024 * 1024, `audio payload ${total} bytes`);
  // loudness plan
  for (const f of bank.sounds.rifle_close) assert.ok(Math.abs(bank.files[f].truePeakDb + 3) <= 0.2, `${f} peak`);
  for (const key of Object.keys(bank.sounds).filter((k) => k.startsWith('step_'))) {
    for (const f of bank.sounds[key]) {
      const m = bank.files[f];
      assert.ok(m.activeRmsDb <= -23.5 && m.activeRmsDb >= -28, `${f} active RMS ${m.activeRmsDb}`);
    }
  }
  assert.ok(Math.abs(bank.files[bank.sounds.amb_wind[0]].rmsDb + 36) <= 0.5, 'wind bed RMS -36 dBFS');
  // several variations for the core sets
  for (const k of ['rifle_close', 'pistol_close', 'step_concrete', 'step_gravel', 'step_dirt', 'step_grass', 'step_wood', 'step_metal', 'impact_concrete', 'impact_metal', 'impact_wood', 'impact_dirt']) {
    assert.ok(bank.sounds[k].length >= 2, `${k} needs variations`);
  }
});

test('SND: master volume default 70 % and follows the setting; master bus has compressor, limiter, trim and soft clipper', async () => {
  assert.equal(settingsDefaults.masterVolume, 0.7);
  const { sys, ctx, settings } = await makeSystem();
  assert.equal(sys.master.gain.value, 0.7);
  settings.set('masterVolume', 0.25);
  assert.equal(sys.master.gain.value, 0.25);
  assert.equal(sys.getState().masterGain, 0.25);
  // chain: master -> compressor -> limiter -> trim -> waveshaper -> destination
  assert.equal(sys.master.outputs[0], sys.compressor);
  assert.equal(sys.compressor.outputs[0], sys.limiter);
  assert.equal(sys.limiter.outputs[0], sys.trim);
  assert.equal(sys.trim.outputs[0], sys.clipper);
  assert.equal(sys.clipper.outputs[0], ctx.destination);
  const mc = audioConfig.masterChain;
  assert.ok(Math.abs(sys.trim.gain.value * compressorMakeup(mc.compressor) * compressorMakeup(mc.limiter) - 1) < 1e-9);
  assert.ok(sys.trim.gain.value < 1, 'make-up gain cancelled (never louder than the input below the threshold)');
});

test('SND: nothing plays without an event (outside play: silence; in play: only the ambience)', async () => {
  const { sys, events, ctx } = await makeSystem({ state: 'start' });
  for (let i = 0; i < 600; i++) {
    sys.tick(1 / 60);
    ctx.advance(1 / 60);
  }
  assert.equal(ctx.started.length, 0, 'no source started before play');
  events.emit('game:state', { state: 'playing' });
  for (let i = 0; i < 60 * 30; i++) {
    sys.tick(1 / 60);
    ctx.advance(1 / 60);
  }
  tagSources(sys, ctx);
  const keys = ctx.started.filter((s) => s.__key).map((s) => s.__key);
  assert.ok(keys.includes('amb_wind'), 'wind bed runs while playing');
  assert.ok(keys.every((k) => k.startsWith('amb_')), `only ambience without events, got ${[...new Set(keys)]}`);
  assert.equal(keys.filter((k) => k === 'amb_wind').length, 1, 'one wind loop');
});

test('SND: own shots, reload stages, dry fire, switch map to the right sounds (not spatial)', async () => {
  const { sys, events, ctx } = await makeSystem();
  let n = ctx.started.length;
  events.emit('weapon:fired', fired());
  let keys = played(sys, ctx, n);
  assert.deepEqual(keys, ['rifle_close', 'rifle_tail']);
  const [close, tail] = ctx.started.slice(n);
  assert.equal(close.startedAt, ctx.currentTime);
  assert.ok(Math.abs(tail.startedAt - ctx.currentTime - audioConfig.weapons.iv7_carbine.tailDelay) < 1e-9, 'tail delayed');
  assert.ok(!close.outputs[0].outputs.some((o) => o.kind === 'panner'), 'own shot is not panned');

  n = ctx.started.length;
  events.emit('weapon:fired', fired({ weaponId: 'ivp9_pistol' }));
  assert.deepEqual(played(sys, ctx, n), ['pistol_close', 'pistol_tail']);

  const seq = [
    ['weapon:dry_fire', { id: 'p', weaponId: 'iv7_carbine' }, 'rifle_dry'],
    ['weapon:reload_started', { id: 'p', weaponId: 'iv7_carbine', kind: 'empty' }, 'rifle_mag_out'],
    ['weapon:action', { id: 'p', weaponId: 'iv7_carbine', type: 'mag_insert' }, 'rifle_mag_in'],
    ['weapon:action', { id: 'p', weaponId: 'iv7_carbine', type: 'bolt_release' }, 'rifle_bolt_release'],
    ['weapon:action', { id: 'p', weaponId: 'iv7_carbine', type: 'chamber_start' }, 'rifle_charge_pull'],
    ['weapon:action', { id: 'p', weaponId: 'iv7_carbine', type: 'chamber_commit' }, 'rifle_charge_release'],
    ['weapon:action', { id: 'p', weaponId: 'ivp9_pistol', type: 'chamber_start' }, 'pistol_slide_pull'],
    ['weapon:action', { id: 'p', weaponId: 'ivp9_pistol', type: 'chamber_commit' }, 'pistol_slide_release'],
    ['weapon:action', { id: 'p', weaponId: 'ivp9_pistol', type: 'bolt_release' }, 'pistol_slide_release'],
    ['weapon:dry_fire', { id: 'p', weaponId: 'ivp9_pistol' }, 'pistol_dry'],
  ];
  for (const [name, payload, key] of seq) {
    n = ctx.started.length;
    events.emit(name, payload);
    assert.deepEqual(played(sys, ctx, n), [key], `${name} ${payload.type || ''}`);
    ctx.advance(0.5);
  }
  // magazine out is timed after the reload start
  n = ctx.started.length;
  const t0 = ctx.currentTime;
  events.emit('weapon:reload_started', { id: 'p', weaponId: 'ivp9_pistol', kind: 'tactical' });
  assert.ok(Math.abs(ctx.started[n].startedAt - t0 - audioConfig.weapons.ivp9_pistol.magOut.delay) < 1e-9);
  n = ctx.started.length;
  events.emit('weapon:switched', { id: 'p', weaponId: 'ivp9_pistol', slot: 1 });
  assert.deepEqual(played(sys, ctx, n), ['switch_cloth', 'switch_draw_pistol']);
  assert.ok(ctx.started[n + 1].startedAt > ctx.started[n].startedAt, 'draw after the cloth');
  // unknown weapon / action: nothing
  n = ctx.started.length;
  events.emit('weapon:action', { id: 'p', weaponId: 'iv7_carbine', type: 'reload_complete' });
  events.emit('weapon:fired', fired({ weaponId: 'nope' }));
  assert.equal(ctx.started.length, n);
});

test('SND: other shooters are spatial; close / distant take by distance, propagation delay, air absorption', async () => {
  const { sys, events, ctx } = await makeSystem();
  const at = (z) => fired({ shooterId: 'b1', muzzle: V(0, 1.5, z), dir: V(1, 0, 0) });
  let n = ctx.started.length;
  events.emit('weapon:fired', at(-10));
  assert.deepEqual(played(sys, ctx, n), ['rifle_close', 'rifle_tail']);
  let src = ctx.started[n];
  const chainTypes = (s) => {
    const out = [];
    let node = s;
    while (node && node.outputs && node.outputs.length) {
      node = node.outputs[0];
      out.push(node.kind);
    }
    return out;
  };
  assert.ok(chainTypes(src).includes('panner'), 'panned');
  assert.ok(Math.abs(src.startedAt - ctx.currentTime - Math.hypot(0.15, 10) / 343) < 1e-3, 'delay = distance / c');
  n = ctx.started.length;
  events.emit('weapon:fired', at(-40));
  assert.deepEqual(played(sys, ctx, n).sort(), ['rifle_close', 'rifle_distant', 'rifle_tail']);
  n = ctx.started.length;
  events.emit('weapon:fired', at(-200));
  assert.deepEqual(played(sys, ctx, n), ['rifle_distant', 'rifle_tail']);
  src = ctx.started[n];
  const filt = src.outputs[0].outputs[0];
  assert.equal(filt.kind, 'biquad');
  assert.equal(filt.type, 'lowpass');
  assert.ok(filt.frequency.value < 9000, `air absorption low-pass ${filt.frequency.value}`);
  // pure helpers
  assert.deepEqual(shotLayerWeights(10), { close: 1, distant: 0 });
  assert.deepEqual(shotLayerWeights(100), { close: 0, distant: 1 });
  assert.ok(airCutoff(10) > airCutoff(300));
  const ca = closestApproach(V(0, 0, 0), V(0, 0, -10), V(1, 0, -5));
  assert.ok(Math.abs(ca.distance - 1) < 1e-9 && Math.abs(ca.t - 0.5) < 1e-9 && Math.abs(ca.along - 5) < 1e-9);
});

test('SND: near-miss crack only when an enemy bullet passes close to the listener', async () => {
  const { sys, events, ctx } = await makeSystem();
  // bot 60 m ahead shooting past the listener's head at 1 m
  let n = ctx.started.length;
  events.emit('weapon:fired', fired({ shooterId: 'b1', muzzle: V(1, 1.65, -60), dir: V(0, 0, 1) }));
  let keys = played(sys, ctx, n);
  assert.ok(keys.includes('nearmiss_crack'), `crack expected, got ${keys}`);
  const crack = ctx.started[n + keys.indexOf('nearmiss_crack')];
  const report = ctx.started[n + keys.indexOf('rifle_distant')];
  assert.ok(crack.startedAt < report.startedAt, 'supersonic crack arrives before the muzzle report');
  assert.equal(sys.getState().stats.nearMisses, 1);
  // shooting away from the listener: no crack
  n = ctx.started.length;
  events.emit('weapon:fired', fired({ shooterId: 'b1', muzzle: V(1, 1.65, -60), dir: V(0, 0, -1) }));
  assert.ok(!played(sys, ctx, n).includes('nearmiss_crack'));
  // bullet stopped by a wall before reaching the listener: no crack
  n = ctx.started.length;
  events.emit('weapon:fired', fired({ shooterId: 'b1', muzzle: V(1, 1.65, -60), dir: V(0, 0, 1), shot: { hitPoint: [1, 1.65, -20], hitKind: 'world' } }));
  assert.ok(!played(sys, ctx, n).includes('nearmiss_crack'));
  // pistol: whiz; own shots never
  n = ctx.started.length;
  events.emit('weapon:fired', fired({ shooterId: 'b2', weaponId: 'ivp9_pistol', muzzle: V(-2, 1.65, -30), dir: V(2 / 30.07, 0, 1) }));
  assert.ok(played(sys, ctx, n).includes('nearmiss_whiz'));
  n = ctx.started.length;
  events.emit('weapon:fired', fired({ shooterId: 'p', muzzle: V(0, 1.6, 1), dir: V(0, 0, -1) }));
  assert.ok(!played(sys, ctx, n).includes('nearmiss_crack'));
});

test('SND: footsteps by surface, landing layers, impacts by surface, casings, jump / traverse', async () => {
  const { sys, events, ctx } = await makeSystem();
  const step = (surface, over = {}) => ({ id: 'p', team: 0, position: V(0, 0, 0), surface, loudness: 0.55, speed: 4, foot: 'left', kind: 'step', ...over });
  for (const [surface, key] of [
    ['concrete', 'step_concrete'],
    ['plaster', 'step_concrete'],
    ['metal', 'step_metal'],
    ['wood', 'step_wood'],
    ['gravel', 'step_gravel'],
    ['grass', 'step_grass'],
    ['dirt', 'step_dirt'],
    ['lava', 'step_concrete'],
  ]) {
    const n = ctx.started.length;
    events.emit('footstep', step(surface));
    assert.deepEqual(played(sys, ctx, n), [key], surface);
    ctx.advance(0.4);
  }
  // louder when sprinting than walking
  let n = ctx.started.length;
  events.emit('footstep', step('concrete', { loudness: 0.25 }));
  const walkGain = ctx.started[n].outputs[0].gain.value;
  ctx.advance(0.4);
  n = ctx.started.length;
  events.emit('footstep', step('concrete', { loudness: 1.0 }));
  const sprintGain = ctx.started[n].outputs[0].gain.value;
  assert.ok(sprintGain > walkGain * 1.3, `sprint ${sprintGain} > walk ${walkGain}`);
  ctx.advance(0.4);
  n = ctx.started.length;
  events.emit('footstep', step('gravel', { kind: 'land', loudness: 0.8 }));
  assert.deepEqual(played(sys, ctx, n).sort(), ['land_thump', 'step_gravel', 'step_gravel']);
  // a bot's step is spatial and ignored beyond the audible distance
  n = ctx.started.length;
  events.emit('footstep', step('metal', { id: 'b1', position: V(3, 0, -3) }));
  assert.deepEqual(played(sys, ctx, n), ['step_metal']);
  n = ctx.started.length;
  events.emit('footstep', step('metal', { id: 'b1', position: V(300, 0, -3) }));
  assert.equal(ctx.started.length, n);
  // impacts
  for (const [surface, key] of [
    ['concrete', 'impact_concrete'],
    ['plaster', 'impact_concrete'],
    ['metal', 'impact_metal'],
    ['wood', 'impact_wood'],
    ['dirt', 'impact_dirt'],
    ['glass', 'impact_glass'],
    ['flesh', 'impact_flesh'],
    ['target', 'impact_wood'],
  ]) {
    n = ctx.started.length;
    events.emit('weapon:hit', { shooterId: 'p', victimId: null, point: V(0, 1, -8), normal: V(0, 0, 1), surface, part: null, blocked: false, hit: { kind: 'world' } });
    assert.deepEqual(played(sys, ctx, n), [key], surface);
    ctx.advance(0.2);
  }
  // hit marker (UI) only for the player's damaging hits on combatants
  const hm0 = sys.getState().stats.hitmarkers;
  events.emit('weapon:hit', { shooterId: 'p', victimId: 'b1', point: V(0, 1, -8), surface: 'flesh', hit: { kind: 'combatant' }, damage: { result: 'applied' } });
  events.emit('weapon:hit', { shooterId: 'b1', victimId: 'p', point: V(0, 1, 0), surface: 'flesh', hit: { kind: 'combatant' }, damage: { result: 'applied' } });
  assert.equal(sys.getState().stats.hitmarkers, hm0 + 1);
  n = ctx.started.length;
  events.emit('weapon:casing_landed', { position: V(0.4, 0, -0.5), surface: 'concrete', weaponId: 'iv7_carbine', shooterId: 'p', speed: 2 });
  events.emit('player:jump', { tick: 1 });
  events.emit('traverse:start', { id: 'p', type: 'vault', ledgePoint: V(0, 1, -1) });
  assert.deepEqual(played(sys, ctx, n), ['casing_rifle', 'jump_gear', 'traverse_gear']);
});

test('SND: voice limits per owner and per category (oldest voice stolen)', async () => {
  const { sys, events, ctx } = await makeSystem();
  const cat = audioConfig.categories.weapon;
  for (let i = 0; i < 12; i++) events.emit('weapon:fired', fired());
  const st = sys.getState();
  assert.ok(st.activeByCategory.weapon <= cat.maxPerOwner, `own shots ${st.activeByCategory.weapon}`);
  assert.ok(st.activeByCategory.tail <= audioConfig.categories.tail.maxPerOwner);
  assert.ok(st.stats.stolen >= 12 - cat.maxPerOwner);
  // stolen voices are stopped (with a short fade), not left running
  const stoppedCloses = ctx.started.filter((s) => s.stoppedAt !== null);
  assert.ok(stoppedCloses.length >= 12 - cat.maxPerOwner);
  // many remote shooters: category cap
  for (let i = 0; i < 30; i++) events.emit('weapon:fired', fired({ shooterId: `b${i}`, muzzle: V(i, 1.5, -12), dir: V(1, 0, 0) }));
  assert.ok(sys.getState().activeByCategory.weapon <= cat.maxVoices);
  // steps: at most 2 per owner
  for (let i = 0; i < 6; i++) events.emit('footstep', { id: 'p', surface: 'concrete', loudness: 1, kind: 'step' });
  assert.ok(sys.getState().activeByCategory.step <= audioConfig.categories.step.maxPerOwner);
});

test('SND: death stops the victim\'s footsteps and pending reload sounds; others keep theirs', async () => {
  const { sys, events, ctx } = await makeSystem({ positions: { b1: V(2, 0, -2) } });
  events.emit('footstep', { id: 'p', surface: 'concrete', loudness: 1, kind: 'step' });
  events.emit('weapon:reload_started', { id: 'p', weaponId: 'iv7_carbine', kind: 'empty' }); // mag out pending (+0.28 s)
  events.emit('footstep', { id: 'b1', position: V(2, 0, -2), surface: 'concrete', loudness: 1, kind: 'step' });
  tagSources(sys, ctx);
  const mine = ctx.started.filter((s) => s.__key === 'step_concrete' || s.__key === 'rifle_mag_out').slice(0, 2);
  const botStep = ctx.started.filter((s) => s.__key === 'step_concrete')[1];
  ctx.advance(0.05);
  events.emit('combatant:died', { victimId: 'p', attackerId: 'b1' });
  for (const s of mine) assert.ok(s.stoppedAt !== null && s.stoppedAt <= ctx.currentTime + audioConfig.stopFade + 1e-9, `${s.__key} stopped`);
  const magOut = mine.find((s) => s.__key === 'rifle_mag_out');
  for (let t = 0; t < 1; t += 0.01) assert.ok(!magOut.audibleAt(ctx.currentTime + t), 'pending magazine-out never plays after death');
  assert.equal(botStep.stoppedAt, null, 'the other combatant keeps its step');
  // interrupted reload cancels the pending magazine-out as well
  const n = ctx.started.length;
  events.emit('weapon:reload_started', { id: 'b1', weaponId: 'iv7_carbine', kind: 'tactical' });
  tagSources(sys, ctx);
  const pending = ctx.started[n];
  assert.equal(pending.__key, 'rifle_mag_out');
  events.emit('weapon:reload_interrupted', { id: 'b1', weaponId: 'iv7_carbine', kind: 'tactical' });
  assert.ok(!pending.audibleAt(ctx.currentTime + 0.3), 'interrupted reload: no magazine-out');
});

test('SND: pause and round reset stop every sound incl. the wind loop; resume restarts the ambience', async () => {
  const { sys, events, ctx } = await makeSystem();
  events.emit('weapon:fired', fired());
  events.emit('footstep', { id: 'p', surface: 'concrete', loudness: 1, kind: 'step' });
  assert.ok(sys.getState().ambience);
  ctx.advance(0.02);
  events.emit('game:state', { state: 'paused' });
  assert.equal(sys.getState().activeVoices, 0);
  assert.equal(sys.getState().ambience, false);
  ctx.advance(0.5);
  assert.equal(ctx.audible().length, 0, 'silence in the pause menu');
  // no birds / wind while paused
  const n = ctx.started.length;
  for (let i = 0; i < 60 * 30; i++) sys.tick(1 / 60);
  assert.equal(ctx.started.length, n);
  // no events are turned into sounds while paused
  events.emit('game:state', { state: 'playing' });
  assert.ok(sys.getState().ambience, 'wind back after resume');
  events.emit('weapon:fired', fired({ shooterId: 'b1', muzzle: V(0, 1.5, -5) }));
  events.emit('round:reset', { zoneId: 'z' });
  ctx.advance(0.2);
  assert.ok(ctx.audible().every((s) => s.loop), 'round reset: only the restarted wind bed remains');
  sys.reset();
  ctx.advance(0.5);
  assert.ok(ctx.audible().every((s) => s.loop));
  events.emit('game:state', { state: 'results' });
  ctx.advance(0.5);
  assert.equal(ctx.audible().length, 0);
});

test('SND: occlusion low-pass when the static world blocks the line of sight; raycast budget per tick', async () => {
  let rays = 0;
  const { sys, events, ctx } = await makeSystem({ raycast: () => (rays++, { distance: 1 }) });
  const n = ctx.started.length;
  events.emit('footstep', { id: 'b1', position: V(4, 0, -4), surface: 'concrete', loudness: 1, kind: 'step' });
  const src = ctx.started[n];
  const filt = src.outputs[0].outputs[0];
  assert.equal(filt.kind, 'biquad');
  assert.equal(filt.type, 'lowpass');
  assert.equal(filt.frequency.value, audioConfig.occlusion.cutoffHz);
  // budget
  sys.tick(1 / 60);
  rays = 0;
  for (let i = 0; i < 40; i++) events.emit('footstep', { id: `b${i}`, position: V(i * 0.7, 0, -6), surface: 'concrete', loudness: 1, kind: 'step' });
  assert.ok(rays <= audioConfig.occlusion.raycastsPerTick, `${rays} raycasts in one tick`);
});

test('SND: encoder lead-in is skipped (start offset), silent until unlocked, files fetched before the gesture', async () => {
  const { sys, events, ctx } = await makeSystem({ leadIn: 0.04 });
  const n = ctx.started.length;
  events.emit('weapon:fired', fired());
  assert.ok(Math.abs(ctx.started[n].offset - 0.037) < 0.002, `offset ${ctx.started[n].offset}`);
  // a system without a context plays nothing and does not throw
  const events2 = new EventBus();
  const quiet = new AudioSystem({ events: events2, settings: new Settings({ storage: null }), isPlayer: () => true, createContext: () => null, fetchBuffer: () => Promise.reject(new Error('offline')) });
  events2.emit('game:state', { state: 'playing' });
  events2.emit('weapon:fired', fired());
  assert.equal(quiet.unlock(), false);
  assert.equal(quiet.getState().played, 0);
  await quiet.prefetch();
  assert.ok(quiet.getState().stats.fetchErrors > 0);
});
