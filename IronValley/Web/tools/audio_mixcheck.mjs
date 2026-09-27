// Mix level check (measurement, not a test): renders scenes (own full-auto burst, steps, reload, wind, a busy
// fire fight) through the real AudioSystem master chain in an OfflineAudioContext of headless Chromium and
// prints peak / RMS / max 10 ms RMS in dBFS and the number of full-scale samples. Needs a build (dist/).
//   node tools/audio_mixcheck.mjs
import { launchGame } from '../tests/e2e/helpers.mjs';
const g = await launchGame({ width: 640, height: 360 });
const page = g.page;
await page.click('button[data-action="practice"]');
await page.waitForFunction(() => { const a = window.__IV.getAudio(); return a.unlocked && a.decoded === a.files; }, null, { timeout: 60000 });
const res = await page.evaluate(async () => {
  const live = window.__IV._game.audio;
  const Cls = live.constructor;
  const scenes = {
    own_rifle_burst: (s) => { for (let i = 0; i < 12; i++) { s._play('rifle_close', { category: 'weapon', owner: 'me', delay: 0.2 + i * 0.08 }); s._play('rifle_tail', { category: 'tail', owner: 'me', delay: 0.3 + i * 0.08 }); } },
    own_rifle_single: (s) => { s._play('rifle_close', { category: 'weapon', owner: 'me', delay: 0.2 }); s._play('rifle_tail', { category: 'tail', owner: 'me', delay: 0.3 }); },
    own_pistol_single: (s) => { s._play('pistol_close', { category: 'weapon', owner: 'me', delay: 0.2 }); s._play('pistol_tail', { category: 'tail', owner: 'me', delay: 0.29 }); },
    own_steps_run: (s) => { for (let i = 0; i < 9; i++) s._play('step_concrete', { category: 'step', owner: 'me', gain: 0.35 + 0.65 * 0.55, delay: 0.2 + i * 0.33 }); },
    own_steps_walk: (s) => { for (let i = 0; i < 7; i++) s._play('step_concrete', { category: 'step', owner: 'me', gain: 0.35 + 0.65 * 0.25, delay: 0.2 + i * 0.43 }); },
    own_reload: (s) => { s._play('rifle_mag_out', { category: 'mech', owner: 'me', delay: 0.3 }); s._play('rifle_mag_in', { category: 'mech', owner: 'me', delay: 1.3 }); s._play('rifle_bolt_release', { category: 'mech', owner: 'me', delay: 2.3 }); },
    wind_only: (s) => { s._startAmbience(); },
    chaos: (s) => { s._startAmbience(); for (let i = 0; i < 12; i++) { s._play('rifle_close', { category: 'weapon', owner: 'me', delay: 0.2 + i * 0.08 }); s._play('rifle_tail', { category: 'tail', owner: 'me', delay: 0.3 + i * 0.08 }); }
      for (let b = 0; b < 6; b++) for (let i = 0; i < 8; i++) s._play('rifle_close', { category: 'weapon', owner: 'b' + b, pos: { x: 3 + b, y: 1.5, z: -8 }, ref: 10, delay: 0.25 + i * 0.08 + b * 0.013 });
      for (let i = 0; i < 10; i++) s._play('impact_concrete', { category: 'impact', owner: 'b', pos: { x: 1, y: 1, z: -2 }, ref: 3, delay: 0.3 + i * 0.07 });
      for (let i = 0; i < 4; i++) s._play('nearmiss_crack', { category: 'nearmiss', owner: 'b', pos: { x: 0.5, y: 1.6, z: 0 }, ref: 1.5, delay: 0.4 + i * 0.1 }); },
  };
  const out = {};
  for (const [name, fn] of Object.entries(scenes)) {
    const dur = 4;
    const oc = new OfflineAudioContext(2, 44100 * dur, 44100);
    const s = new Cls({ events: null, settings: { get: () => 0.7, onChange: () => () => {} }, isPlayer: () => false, createContext: () => oc, fetchBuffer: () => Promise.reject(new Error('x')), random: Math.random });
    s.ctx = oc; s._buildMaster(); s.playing = true;
    for (const [f, b] of live.buffers) s.buffers.set(f, b);
    s.setListener({ x: 0, y: 1.6, z: 0 }, { x: 0, y: 0, z: -1 }, { x: 0, y: 1, z: 0 });
    fn(s);
    const buf = await oc.startRendering();
    let peak = 0, sum = 0, n = 0, over = 0;
    const win = 441; let maxWinRms = 0;
    for (let c = 0; c < 2; c++) { const d = buf.getChannelData(c); for (let i = 0; i < d.length; i++) { const v = Math.abs(d[i]); if (v > peak) peak = v; if (v >= 0.999) over++; sum += d[i] * d[i]; n++; }
      for (let i = 0; i + win < d.length; i += win) { let q = 0; for (let j = 0; j < win; j++) q += d[i + j] * d[i + j]; maxWinRms = Math.max(maxWinRms, Math.sqrt(q / win)); } }
    const db = (x) => Math.round(20 * Math.log10(Math.max(x, 1e-9)) * 10) / 10;
    out[name] = { peakDb: db(peak), rmsDb: db(Math.sqrt(sum / n)), max10msRmsDb: db(maxWinRms), samplesAtFullScale: over };
  }
  return out;
});
console.log(JSON.stringify(res, null, 1));
await g.close();
