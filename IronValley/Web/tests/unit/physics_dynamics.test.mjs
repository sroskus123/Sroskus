// cannon-es stub: static level boxes + a dynamic prop stepped on the fixed tick.
import test from 'node:test';
import assert from 'node:assert/strict';
import level from '../../src/data/test_range.json' with { type: 'json' };
import { listLevelBoxes } from '../../src/level/levelGeometry.js';
import { DynamicsWorld } from '../../src/physics/dynamicsWorld.js';

test('level boxes are mirrored as static bodies', () => {
  const w = new DynamicsWorld();
  const boxes = listLevelBoxes(level);
  w.addLevelBoxes(boxes);
  assert.equal(w.staticBodies.length, boxes.filter((b) => b.collide !== false).length);
  assert.ok(w.staticBodies.length > 20);
});

test('a dropped crate comes to rest on the ground (no fall-through, no jitter)', () => {
  const w = new DynamicsWorld();
  w.addLevelBoxes(listLevelBoxes(level));
  const crate = w.addDynamicBox({ size: [0.5, 0.5, 0.5], position: [0, 2, 20], mass: 12 });
  for (let i = 0; i < 60 * 5; i++) w.step(1 / 60);
  assert.ok(Math.abs(crate.position.y - 0.25) < 0.02, `y=${crate.position.y}`);
  assert.ok(crate.velocity.length() < 0.05, `v=${crate.velocity.length()}`);
  assert.equal(w.steps, 300);
});

test('a crate dropped onto the 1.0 m wall rests on top of it', () => {
  const w = new DynamicsWorld();
  w.addLevelBoxes(listLevelBoxes(level));
  const crate = w.addDynamicBox({ size: [0.2, 0.2, 0.2], position: [15, 2, -4], mass: 3 });
  for (let i = 0; i < 60 * 4; i++) w.step(1 / 60);
  assert.ok(Math.abs(crate.position.y - 1.1) < 0.02, `y=${crate.position.y}`);
});
