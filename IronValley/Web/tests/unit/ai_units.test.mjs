// Pure AI building blocks: memory (only stimuli write it, decay, forgetting), perception timing model,
// aim noise statistics, config validation, funnel string pulling on a synthetic L-corridor.
import test from 'node:test';
import assert from 'node:assert/strict';
import { Vector3 } from 'three';
import { EnemyMemory } from '../../src/ai/memory.js';
import { detectTimeAt } from '../../src/ai/perception.js';
import { aimSigmaDeg, gaussian } from '../../src/ai/aim.js';
import { resolveAIConfig } from '../../src/ai/config.js';
import { NavMeshData } from '../../src/ai/nav/navMesh.js';
import { createRng } from '../../src/util/rng.js';

const cfg = resolveAIConfig();

test('memory: entries change only through stimuli; hearing does not override a fresh sighting; confidence decays to forgetting', () => {
  const m = new EnemyMemory(cfg);
  assert.equal(m.size, 0);
  m.see('e1', 1, 1.0, new Vector3(1, 0, 1), new Vector3(1, 0, 0), 1.3);
  const e = m.get('e1');
  assert.equal(e.conf, 1);
  assert.equal(e.source, 'vision');
  // a sound right after the sighting keeps the visual information
  m.hear('e1', 1, 1.2, new Vector3(9, 0, 9), 0.6);
  assert.deepEqual(e.pos.toArray(), [1, 0, 1]);
  // not seen any more: position frozen, confidence decays, predicted = short extrapolation only
  m.markUnseen('e1');
  for (let i = 0; i < 60; i++) m.decay(1 / 60);
  assert.deepEqual(e.pos.toArray(), [1, 0, 1], 'decay never moves the last known position');
  assert.ok(e.conf < 1);
  const p = m.predicted(e, 100, new Vector3());
  assert.ok(Math.abs(p.x - (1 + cfg.memory.velocityExtrapolation)) < 1e-9, 'extrapolation is capped');
  for (let i = 0; i < 60 * 30; i++) m.decay(1 / 60);
  assert.equal(m.get('e1'), null, 'forgotten after the decay time');
  // explicit forget (death / respawn)
  m.hear('e2', 2, 5, new Vector3(3, 0, 3), 0.5);
  m.forget('e2');
  assert.equal(m.size, 0);
});

test('perception model: detection time is nonzero, grows with distance, infinite beyond range', () => {
  const t8 = detectTimeAt(cfg, 5);
  const t20 = detectTimeAt(cfg, 20);
  const t40 = detectTimeAt(cfg, 40);
  const t80 = detectTimeAt(cfg, 80);
  assert.ok(t8 > 0.1 && t8 < t20 && t20 < t40 && t40 < t80);
  assert.equal(detectTimeAt(cfg, cfg.vision.range + 1), Infinity);
});

test('aim model: sigma grows with distance, target speed and own movement, shrinks with tracking; noise has unit variance', () => {
  const base = aimSigmaDeg(cfg, { distance: 10, trackTime: Infinity });
  assert.ok(aimSigmaDeg(cfg, { distance: 40, trackTime: Infinity }) > base);
  assert.ok(aimSigmaDeg(cfg, { distance: 10, targetLateralSpeed: 3, trackTime: Infinity }) > base);
  assert.ok(aimSigmaDeg(cfg, { distance: 10, ownSpeed: 3.5, trackTime: Infinity }) > base);
  assert.ok(Math.abs(aimSigmaDeg(cfg, { distance: 10, trackTime: 0 }) - base * cfg.aim.initialErrorMult) < 1e-9);
  assert.ok(aimSigmaDeg(cfg, { distance: 10, crouched: true, trackTime: Infinity }) < base);
  // OU process as in AimController: stationary unit variance
  const rng = createRng(7);
  const tau = cfg.aim.noiseCorrelation;
  const k = Math.exp(-1 / 60 / tau);
  const s = Math.sqrt(1 - k * k);
  let x = gaussian(rng);
  let sum2 = 0;
  const N = 200000;
  for (let i = 0; i < N; i++) {
    x = x * k + s * gaussian(rng);
    sum2 += x * x;
  }
  assert.ok(Math.abs(sum2 / N - 1) < 0.08, `variance ${sum2 / N}`);
});

test('config: a zero reaction time or empty bursts are rejected (AI-03: nonzero, data-driven)', () => {
  assert.throws(() => resolveAIConfig({ combat: { reactionDelayMin: 0 } }), /reaction/);
  assert.throws(() => resolveAIConfig({ combat: { bursts: [] } }), /bursts/);
  assert.equal(resolveAIConfig({ aim: { baseErrorDeg: 2 } }).aim.baseErrorDeg, 2);
});

test('funnel: path around the inner corner of an L-shaped corridor stays inside and is shortest', () => {
  // L corridor: x 0..10, z 0..2 (east leg) + x 8..10, z 2..10 (north leg... +z here), triangulated
  const V = [
    [0, 0, 0], [10, 0, 0], [10, 0, 10], [8, 0, 10], [8, 0, 2], [0, 0, 2],
  ];
  const tris = [
    [0, 5, 4], [0, 4, 1], [1, 4, 2], [4, 3, 2],
  ];
  // three-pathfinding-like zone: neighbours share two vertex ids
  const nodes = tris.map((t, i) => ({ id: i, vertexIds: t, neighbours: [], portals: [], centroid: [0, 0, 0] }));
  for (const a of nodes) {
    const c = a.vertexIds.reduce((acc, v) => acc.map((x, k) => x + V[v][k] / 3), [0, 0, 0]);
    a.centroid = c;
    for (const b of nodes) {
      if (a === b) continue;
      const sh = a.vertexIds.filter((v) => b.vertexIds.includes(v));
      if (sh.length === 2) {
        a.neighbours.push(b.id);
        a.portals.push(sh);
      }
    }
  }
  const nav = new NavMeshData({ zone: { vertices: V.flat(), groups: [nodes] }, mainGroup: 0 });
  const start = new Vector3(1, 0, 1);
  const end = new Vector3(9, 0, 9);
  const s = nav.nodeAt(start);
  const t = nav.nodeAt(end);
  const corridor = nav.searchNodes(s, start, t, end);
  assert.ok(corridor && corridor.length >= 2);
  const pts = nav.stringPull(corridor, start, end);
  // the only corner needed is the inner corner (8, 2)
  assert.equal(pts.length, 3, JSON.stringify(pts));
  assert.ok(pts[1].distanceTo(new Vector3(8, 0, 2)) < 1e-6);
  for (let i = 1; i < pts.length; i++) assert.ok(nav.segmentOnMesh(pts[i - 1], pts[i], { step: 0.05 }));
});
