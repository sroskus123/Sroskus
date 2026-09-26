// Fixed-step loop, event bus, settings validation and input bindings (no browser needed).
import test from 'node:test';
import assert from 'node:assert/strict';
import { FixedStepLoop } from '../../src/engine/loop.js';
import { EventBus } from '../../src/engine/events.js';
import { Settings, sanitizeSettings } from '../../src/player/settings.js';
import { InputManager, buildBindingMap } from '../../src/player/input.js';
import bindings from '../../src/data/input_bindings.json' with { type: 'json' };
import { horizontalToVerticalFov } from '../../src/util/math.js';

function makeLoop() {
  const log = { ticks: 0, renders: 0, alphas: [] };
  const loop = new FixedStepLoop({
    step: () => log.ticks++,
    render: (a) => {
      log.renders++;
      log.alphas.push(a);
    },
  });
  return { loop, log };
}

test('fixed-step loop runs the same number of ticks at 30, 60, 144 and 240 FPS pacing', () => {
  for (const fps of [30, 60, 144, 240, 59.94]) {
    const { loop, log } = makeLoop();
    const frames = Math.round(10 * fps);
    for (let i = 0; i < frames; i++) loop.frame(1 / fps, { render: true });
    const expected = Math.floor(frames / fps / (1 / 60) + 1e-6);
    assert.equal(log.ticks, expected, `fps ${fps}`);
    assert.ok(log.alphas.every((a) => a >= 0 && a <= 1));
  }
});

test('huge frame gaps are clamped (no spiral of death)', () => {
  const { loop, log } = makeLoop();
  loop.frame(5.0); // e.g. tab was in background
  assert.equal(log.ticks, 15); // 0.25 s max frame
  assert.equal(loop.clampedFrames, 1);
  loop.frame(Number.NaN);
  loop.frame(-1);
  assert.equal(log.ticks, 15);
});

test('time scale and exact stepping', () => {
  const { loop, log } = makeLoop();
  loop.timeScale = 0.5;
  for (let i = 0; i < 60; i++) loop.frame(1 / 60, { render: false });
  assert.equal(log.ticks, 30);
  loop.stepTicks(7);
  assert.equal(log.ticks, 37);
  loop.resetAccumulator();
  assert.equal(loop.alpha, 0);
});

test('event bus: on / once / off and handler isolation', () => {
  const bus = new EventBus();
  const got = [];
  const off = bus.on('a', (p) => got.push(['a', p]));
  bus.once('a', (p) => got.push(['once', p]));
  const origError = console.error;
  console.error = () => {};
  bus.on('a', () => {
    throw new Error('boom');
  });
  bus.emit('a', 1);
  bus.emit('a', 2);
  console.error = origError;
  off();
  bus.emit('a', 3);
  assert.deepEqual(got, [
    ['a', 1],
    ['once', 1],
    ['a', 2],
  ]);
});

test('settings: FOV limited to 70-100 (default 80), sensitivity and camera motion clamped', () => {
  const d = sanitizeSettings({});
  assert.equal(d.fovDeg, 80);
  assert.equal(sanitizeSettings({ fovDeg: 20 }).fovDeg, 70);
  assert.equal(sanitizeSettings({ fovDeg: 150 }).fovDeg, 100);
  assert.equal(sanitizeSettings({ cameraMotion: 3 }).cameraMotion, 1);
  assert.equal(sanitizeSettings({ mouseSensitivity: 'x' }).mouseSensitivity, d.mouseSensitivity);
  const store = new Map();
  const storage = { getItem: (k) => store.get(k) ?? null, setItem: (k, v) => store.set(k, v) };
  const s = new Settings({ storage });
  let changed = null;
  s.onChange((k, v) => (changed = [k, v]));
  s.set('fovDeg', 95);
  assert.deepEqual(changed, ['fovDeg', 95]);
  assert.equal(new Settings({ storage }).get('fovDeg'), 95, 'persisted');
  const broken = { getItem: () => { throw new Error('denied'); }, setItem: () => { throw new Error('denied'); } };
  const s2 = new Settings({ storage: broken });
  assert.equal(s2.get('fovDeg'), 80);
  s2.set('fovDeg', 90); // must not throw
  assert.equal(s2.get('fovDeg'), 90);
});

test('horizontal FOV 80 at 16:9 converts to about 50.5 deg vertical', () => {
  assert.ok(Math.abs(horizontalToVerticalFov(80, 16 / 9) - 50.53) < 0.05);
});

test('bindings JSON covers every required action with valid codes', () => {
  const required = ['moveForward', 'moveBackward', 'moveLeft', 'moveRight', 'fire', 'aim', 'reload', 'sprint', 'crouch', 'jump', 'interact', 'weapon1', 'weapon2', 'menu'];
  for (const a of required) assert.ok(Array.isArray(bindings.actions[a]) && bindings.actions[a].length > 0, a);
  const map = buildBindingMap(bindings);
  assert.deepEqual(map.get('KeyW'), ['moveForward']);
  assert.deepEqual(map.get('Mouse0'), ['fire']);
  assert.deepEqual(map.get('Mouse2'), ['aim']);
  assert.ok(map.get('KeyC').includes('crouch') && map.get('ControlLeft').includes('crouch'));
  assert.throws(() => buildBindingMap({ actions: { x: 'KeyA' } }));
});

test('input: taps shorter than a tick are latched; releaseAll clears everything; Esc opens the menu', () => {
  const bus = new EventBus();
  const menus = [];
  bus.on('input:menu', (p) => menus.push(p.reason));
  const inp = new InputManager(bindings, bus);
  inp.setEnabled(true);
  inp.handleKeyDown('Space');
  inp.handleKeyUp('Space');
  assert.equal(inp.isHeld('jump'), false);
  assert.equal(inp.wasPressed('jump'), true, 'tap latched until the tick consumes it');
  inp.consumeTick();
  assert.equal(inp.wasPressed('jump'), false);
  inp.handleKeyDown('KeyW');
  inp.handleKeyDown('KeyW', true); // auto-repeat
  inp.handleMouseButton(0, true);
  assert.equal(inp.isHeld('moveForward'), true);
  assert.equal(inp.isHeld('fire'), true);
  inp.releaseAll('blur');
  assert.equal(inp.isHeld('moveForward'), false);
  assert.equal(inp.isHeld('fire'), false);
  inp.handleKeyDown('Escape');
  assert.deepEqual(menus, ['key']);
  // disabled (menu open): gameplay keys ignored
  inp.setEnabled(false);
  inp.handleKeyDown('KeyW');
  assert.equal(inp.isHeld('moveForward'), false);
});
