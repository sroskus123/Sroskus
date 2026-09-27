// Map art pass phase 1 on Kalné Hamry in the real build (headless Chromium + SwiftShader; timings are relative only):
//  - the terrain splat material binds all 10 detail layers (texture arrays of depth 10) and the weight / macro images;
//  - trees, shrubs and the backdrop forest are instanced; the LOD buckets switch with the camera distance
//    (LOD0 near the square linden, no LOD0 from the high overview, far trees always LOD2);
//  - the grass scatter never puts a clump on asphalt, water or brook stones and is dense on the meadows;
//  - vegetation and grass are not in the collision world (AI sight / bullets unaffected);
//  - budgets of the rendered frame at the square and in the overview: <= 320 draw calls, <= 1.6 M triangles
//    (shadow pass included), load time printed.
import test, { after, before } from 'node:test';
import assert from 'node:assert/strict';
import { launchGame, screenshot } from './helpers.mjs';

let g;
let page;
const ev = (fn, arg) => page.evaluate(fn, arg);

before(async () => {
  g = await launchGame({ width: 960, height: 540 });
  page = g.page;
  page.setDefaultTimeout(900_000);
});

after(async () => {
  if (g) {
    assert.deepEqual(g.errors, [], `console errors: ${g.errors.join(' | ')}`);
    assert.deepEqual(g.failed, [], `failed requests: ${g.failed.join(' | ')}`);
    await g.close();
  }
});

const frameStats = () =>
  ev(() => {
    const iv = window.__IV;
    const ri = iv._game.renderer.renderer.info;
    iv.updateVegetation();
    iv.renderNow();
    ri.autoReset = false;
    ri.reset();
    iv.renderNow();
    ri.autoReset = true;
    return { calls: ri.render.calls, triangles: ri.render.triangles };
  });

test('terrain splat binds all detail layers; vegetation and grass are built', async () => {
  const r = await ev(async () => {
    const iv = window.__IV;
    const t0 = performance.now();
    const info = await iv.loadLevel('kalne_hamry');
    const ms = performance.now() - t0;
    iv.startGame();
    iv.pause();
    iv.setSetting('adaptiveResolution', false);
    iv.teleportToMarker('spawn');
    iv.step(2);
    iv.renderNow();
    return { ms, load: info.load, v: iv.getVegetation() };
  });
  console.log(`# kalne_hamry load ${r.ms.toFixed(0)} ms: ${JSON.stringify(r.load, (k, v) => (k === 'triangles' && typeof v === 'object' ? undefined : v))}`);
  const terrain = r.v.splat;
  assert.ok(terrain.length >= 1, 'terrain meshes carry the splat material');
  for (const t of terrain) {
    assert.equal(t.layers.length, 10, t.mesh);
    assert.deepEqual(t.depth, [10, 10, 10], `${t.mesh}: texture arrays of 10 layers`);
    assert.equal(t.weights, true);
    assert.equal(t.macro, true);
  }
  assert.ok(r.v.veg, 'vegetation built');
  assert.equal(r.v.veg.stats.trees, 1650);
  assert.ok(r.v.veg.stats.shrubs > 1000 && r.v.veg.stats.backdropTrees > 1000, JSON.stringify(r.v.veg.stats));
  assert.equal(r.v.veg.stats.models, 13);
  assert.deepEqual(r.v.grass.types, ['low', 'forb', 'tall', 'chamomile', 'yarrow']);
  assert.ok(r.ms < 8000, `load ${r.ms} ms (SwiftShader; budget on a real machine 2.5 s)`);
});

test('LOD switching: LOD0 near the square linden, none from the high overview; backdrop trees stay LOD2', async () => {
  const near = await ev(() => {
    const iv = window.__IV;
    iv.setCameraOverride({ pos: [12.0, 3.0, -2.0], target: [8.5, 4.0, -2.5], fovDeg: 80 });
    iv.renderNow();
    iv.updateVegetation();
    return iv.getVegetation();
  });
  assert.ok(near.veg.counts[0] > 0, `LOD0 instances near the square: ${near.veg.counts}`);
  assert.ok(near.veg.meshes.some((m) => m.name === 'veg_wide_LOD0'), `the square linden at LOD0 (${near.veg.meshes.map((m) => m.name).join(', ')})`);
  assert.ok(near.veg.meshes.filter((m) => m.lod === 2).every((m) => !m.castShadow), 'LOD2 casts no shadow');
  const far = await ev(() => {
    const iv = window.__IV;
    iv.setCameraOverride({ pos: [70.0, 75.0, 75.0], target: [-5.0, 0.0, -5.0], fovDeg: 70 });
    iv.renderNow();
    iv.updateVegetation();
    return iv.getVegetation();
  });
  assert.equal(far.veg.counts[0], 0, `no LOD0 from 75 m up: ${far.veg.counts}`);
  assert.ok(far.veg.counts[2] > far.veg.counts[1] && far.veg.counts[1] > 0, `mostly LOD2 far away: ${far.veg.counts}`);
  await screenshot(page, 'kh_art_overview.png');
});

test('grass: dense on the meadow, never on asphalt, water or brook stones; not in the collision world', async () => {
  const r = await ev(() => {
    const iv = window.__IV;
    const gm = iv._game;
    iv.setCameraOverride({ pos: [36.0, 4.0, -52.0], target: [8.0, 2.0, -46.0], fovDeg: 80 });
    iv.renderNow();
    iv.updateVegetation();
    const v = iv.getVegetation({ instances: true });
    const raster = gm.world.surfaceRaster;
    const bad = {};
    let checked = 0;
    for (const it of v.grass.instances) {
      const s = raster.surfaceAt(it.x, it.z);
      checked++;
      if (s === 'asphalt' || s === 'water' || s === 'stone') bad[s] = (bad[s] || 0) + 1;
    }
    // the collision world has no grass / foliage: a ray low over a meadow patch full of clumps hits only terrain
    const inst = v.grass.instances.filter((i) => i.type === 'tall' || i.type === 'low').slice(0, 40);
    let blocked = 0;
    for (const it of inst) {
      const o = gm.camera.position.clone().set(it.x - 3, it.y + 0.3, it.z);
      const d = gm.camera.position.clone().set(1, 0, 0);
      const hit = gm.world.raycast(o, d, 3, 0, 'vision');
      if (hit && !String(hit.solidId).startsWith('geo:')) blocked++;
    }
    return { counts: v.grass.counts, cells: v.grass.cells, triangles: v.grass.triangles, bad, checked, blocked, solids: gm.world.solids ? gm.world.solids.filter((s) => /grass|veg|tree_card/.test(s.id)).length : 0 };
  });
  console.log(`# grass at the meadow: ${JSON.stringify(r.counts)} in ${r.cells} cells, ${r.triangles} triangles`);
  assert.deepEqual(r.bad, {}, 'grass clumps on asphalt / water / stones');
  assert.ok(r.counts[0] > 2000, `low grass clumps: ${r.counts[0]}`);
  assert.ok(r.counts[3] + r.counts[4] > 20, `meadow flowers: ${r.counts}`);
  assert.equal(r.blocked, 0, 'grass does not block rays');
  assert.equal(r.solids, 0, 'no vegetation solids in the collision world');
  await screenshot(page, 'kh_art_meadow.png');
});

test('frame budget at the square and in the overview: <= 320 draw calls, <= 1.6 M triangles (shadow pass included)', async () => {
  await ev(() => {
    const iv = window.__IV;
    iv.setCameraOverride(null);
    iv.teleportToMarker('spawn');
    iv.step(2);
  });
  const square = await frameStats();
  await ev(() => window.__IV.setCameraOverride({ pos: [70.0, 75.0, 75.0], target: [-5.0, 0.0, -5.0], fovDeg: 70 }));
  const overview = await frameStats();
  await ev(() => window.__IV.setCameraOverride(null));
  console.log(`# frame budget: square ${square.calls} calls / ${square.triangles} tris; overview ${overview.calls} calls / ${overview.triangles} tris`);
  for (const [name, f] of Object.entries({ square, overview })) {
    assert.ok(f.calls <= 320, `${name}: ${f.calls} draw calls`);
    assert.ok(f.triangles <= 1600000, `${name}: ${f.triangles} triangles`);
  }
});
