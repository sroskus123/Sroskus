// Adaptive render scale (Node): recovers on a 60 Hz display after a slow stretch (the old version could only go
// down there: its raise threshold was below the vsync interval), ignores single hitches, holds while aiming, and
// does not pump between two scales.
import test from 'node:test';
import assert from 'node:assert/strict';
import { AdaptiveResolution } from '../../src/engine/adaptiveResolution.js';

function run(a, frames, msAt) {
  const changes = [];
  let t = 0;
  for (let i = 0; i < frames; i++) {
    const ms = msAt(i, a.scale);
    t += ms / 1000;
    const s = a.update(ms, ms / 1000);
    if (s !== null) changes.push({ t, s });
  }
  return changes;
}

test('60 Hz display: a slow stretch lowers the scale, steady vsync frames bring it back to 1', () => {
  const a = new AdaptiveResolution({ min: 0.5, max: 1 });
  const changes = run(a, 60 * 90, (i) => (i > 600 && i < 780 ? 33.3 : 16.67));
  assert.ok(changes.some((c) => c.s < 1), 'lowered during the slow stretch');
  assert.equal(a.scale, 1, `recovered: ${JSON.stringify(changes)}`);
});

test('single hitches (shader compile, tab switch) do not change the scale', () => {
  const a = new AdaptiveResolution({ min: 0.5, max: 1 });
  const changes = run(a, 60 * 30, (i) => (i % 400 === 100 ? 400 : 16.67));
  assert.deepEqual(changes, []);
  assert.equal(a.scale, 1);
});

test('hold (aiming) freezes the scale even when frames are slow', () => {
  const a = new AdaptiveResolution({ min: 0.5, max: 1 });
  let t = 0;
  for (let i = 0; i < 60 * 20; i++) {
    const s = a.update(33.3, 0.0333, { hold: true });
    assert.equal(s, null);
    t += 0.0333;
  }
  assert.equal(a.scale, 1);
});

test('a scale that failed is retried with a growing cooldown (no pumping every few seconds)', () => {
  const a = new AdaptiveResolution({ min: 0.5, max: 1 });
  // too slow above 0.85, fine at or below
  const changes = run(a, 60 * 120, (i, s) => (s > 0.86 ? (i % 2 ? 33.3 : 16.67) : 16.67));
  // retries of the failing scale (0.9)
  const ups = changes.filter((c, k) => k > 0 && c.s > changes[k - 1].s && c.s > 0.86).map((c) => c.t);
  assert.ok(ups.length >= 2);
  const gaps = ups.slice(1).map((t, k) => t - ups[k]);
  for (let k = 1; k < gaps.length; k++) assert.ok(gaps[k] >= gaps[k - 1] - 1, `retry gaps grow: ${gaps.map((g) => g.toFixed(1))}`);
  assert.ok(changes.length < 16, `${changes.length} changes in 2 minutes`);
  assert.ok(a.scale >= 0.8 && a.scale <= 0.9);
});

test('high refresh display: the old 11.5 ms headroom rule still raises the scale', () => {
  const a = new AdaptiveResolution({ min: 0.5, max: 1 });
  a.reset(0.7);
  run(a, 144 * 30, () => 6.9);
  assert.equal(a.scale, 1);
});
