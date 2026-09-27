// SND-01 on the real build: the AudioContext is created / resumed by the menu click, every sound file is
// fetched and decoded (no failed requests, MP3 lead-in bounded), the ambience runs only while playing, and
// the expected buffers start for real events: shots (one close + one tail per round, nothing after the
// trigger is released), dry fire and the empty-reload stages (magazine out / in, bolt release), footsteps
// on the test-range concrete, then pause and death stop every running sound. Counters: window.__IV.getAudio().
import test, { after, before } from 'node:test';
import assert from 'node:assert/strict';
import { launchGame } from './helpers.mjs';

let g;
let page;

before(async () => {
  g = await launchGame({ width: 960, height: 540 });
  page = g.page;
});

after(async () => {
  if (g) {
    assert.deepEqual(g.errors, [], `console errors: ${g.errors.join(' | ')}`);
    assert.deepEqual(g.failed, [], `failed requests: ${g.failed.join(' | ')}`);
    await g.close();
  }
});

const ev = (fn, arg) => page.evaluate(fn, arg);
const audio = () => ev(() => window.__IV.getAudio());
const count = (a, key) => a.byKey[key] || 0;

test('SND-01: audio starts on the menu click, all files decode, ambience only while playing', async () => {
  const before = await audio();
  assert.equal(before.unlocked, false, 'no AudioContext before a user gesture');
  assert.equal(before.played, 0);
  await page.click('button[data-action="practice"]'); // "Trénink (bez botů)": a real user gesture
  await page.waitForFunction(() => {
    const a = window.__IV.getAudio();
    return a.unlocked && a.decoded === a.files;
  }, null, { timeout: 60_000 });
  const a = await audio();
  assert.equal(a.contextState, 'running');
  assert.equal(a.stats.decodeErrors, 0);
  assert.equal(a.stats.fetchErrors, 0);
  assert.ok(a.files >= 90, `${a.files} files`);
  assert.ok(a.bufferCheck.maxLeadIn < 0.06, `lead-in ${a.bufferCheck.maxLeadIn}`);
  assert.ok(a.bufferCheck.maxDurationError < 0.08, `decoded duration differs by ${a.bufferCheck.maxDurationError} s`);
  assert.ok(Math.abs(a.masterGain - 0.7) < 1e-6, `default master volume 70 % (${a.masterGain})`);
  console.log('audio decode check:', JSON.stringify({ files: a.files, bufferCheck: a.bufferCheck, contextState: a.contextState }));
  await page.waitForFunction(() => window.__IV.getAudio().ambience, null, { timeout: 10_000 });
  // only ambience so far: no event, no sound
  const cats = Object.keys((await audio()).byCategory);
  assert.deepEqual(cats.filter((c) => c !== 'ambience'), [], `sounds without an event: ${cats}`);
});

test('SND-01: shots, dry fire and reload stages start the expected buffers at the real events', async () => {
  await ev(() => {
    const iv = window.__IV;
    iv.pause(); // frozen loop: the test steps the simulation
    iv.setDrawEnabled(false);
    iv.releaseAll();
    iv.teleportToMarker('spawn');
    iv.step(2);
  });
  const a0 = await audio();
  const shots0 = await ev(() => window.__IV.getCoreWeapon().shotsFired);
  await ev(() => {
    const iv = window.__IV;
    iv.mouseButton(0, true);
    iv.step(30); // 0.5 s of automatic fire
    iv.mouseButton(0, false);
    iv.step(2);
  });
  const a1 = await audio();
  const shots = (await ev(() => window.__IV.getCoreWeapon().shotsFired)) - shots0;
  assert.ok(shots >= 5, `${shots} rounds fired`);
  assert.equal(count(a1, 'rifle_close') - count(a0, 'rifle_close'), shots, 'one close report per round');
  assert.equal(count(a1, 'rifle_tail') - count(a0, 'rifle_tail'), shots, 'one outdoor tail per round');
  assert.ok(a1.activeByCategory.weapon <= 4, 'voice limit for own shots');
  // releasing the trigger stops the fire at once: no further report
  await ev(() => window.__IV.step(60));
  assert.equal(count(await audio(), 'rifle_close'), count(a1, 'rifle_close'));

  // empty the magazine, then a trigger pull: dry fire -> empty reload (magazine out, in, bolt release)
  await ev(() => {
    const iv = window.__IV;
    iv.mouseButton(0, true);
    iv.step(200);
    iv.mouseButton(0, false);
    iv.step(2);
  });
  const core = await ev(() => window.__IV.getCoreWeapon());
  assert.equal(core.magazine + core.chamber, 0, 'magazine emptied');
  const a2 = await audio();
  await ev(() => {
    const iv = window.__IV;
    iv.mouseButton(0, true);
    iv.step(2);
    iv.mouseButton(0, false);
    iv.step(200); // 3.3 s: the whole empty reload (2.9 s)
  });
  const a3 = await audio();
  assert.equal(count(a3, 'rifle_dry') - count(a2, 'rifle_dry'), 1, 'dry fire click');
  assert.equal(count(a3, 'rifle_mag_out') - count(a2, 'rifle_mag_out'), 1, 'magazine out');
  assert.equal(count(a3, 'rifle_mag_in') - count(a2, 'rifle_mag_in'), 1, 'magazine in (insert commit)');
  assert.equal(count(a3, 'rifle_bolt_release') - count(a2, 'rifle_bolt_release'), 1, 'bolt release (commit)');
  const c2 = await ev(() => window.__IV.getCoreWeapon());
  assert.equal(c2.state, 'ready');
  assert.equal(c2.chamber, 1);
});

test('SND-01: footsteps on concrete follow the gait; pause and death stop every running sound', async () => {
  const a0 = await audio();
  await ev(() => {
    const iv = window.__IV;
    iv.teleportToMarker('spawn');
    iv.step(2);
    iv.keyDown('KeyW');
    iv.step(120); // 2 s running
  });
  const a1 = await audio();
  const steps = count(a1, 'step_concrete') - count(a0, 'step_concrete');
  assert.ok(steps >= 4 && steps <= 9, `${steps} concrete steps in 2 s`);
  assert.ok(a1.activeByCategory.step >= 1, 'a step is sounding while running');
  // pause: everything stops (footsteps and the wind loop)
  await ev(() => {
    const iv = window.__IV;
    iv.openMenu();
  });
  let a = await audio();
  assert.equal(a.activeVoices, 0, `voices after pause: ${JSON.stringify(a.activeByCategory)}`);
  assert.equal(a.ambience, false);
  const inPause = a.played;
  await ev(() => window.__IV.step(120));
  assert.equal((await audio()).played, inPause, 'nothing starts behind the pause menu');
  // back to play, then death in a match stops the player's footsteps
  await ev(async () => {
    const iv = window.__IV;
    iv.releaseAll();
    await iv.startMatch({ bots: [0, 1, 0], seed: 7, skipPreRound: true, ai: false });
    iv.pause();
    iv.setDrawEnabled(false);
    iv.step(2);
    iv.keyDown('KeyW');
    iv.step(40);
  });
  a = await audio();
  assert.equal(a.ambience, true, 'ambience restarts in play');
  await ev(() => {
    const iv = window.__IV;
    iv.forceKill('player');
    iv.step(1);
  });
  a = await audio();
  assert.ok(!a.activeByCategory.step, `footsteps after death: ${JSON.stringify(a.activeByCategory)}`);
  const afterDeath = count(a, 'step_concrete');
  await ev(() => window.__IV.step(60));
  assert.equal(count(await audio(), 'step_concrete'), afterDeath, 'a dead player makes no footsteps');
  await ev(() => window.__IV.releaseAll());
});
