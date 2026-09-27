// Map art pass phase 1 (terrain splat, grass, trees and shrubs) of Kalné Hamry: the generated data the browser
// systems read (src/level/terrainMaterial.js, grass.js, vegetation.js) -- layers bound, weights complete, grass never
// on hard surfaces or tall in capture zones, every species has a model with three LODs inside the budget, file sizes.
import test from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync, statSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseGlb, readAccessor, surfaceRasterFromGlb } from '../../src/level/levelAssets.js';
import { loadLevelData } from '../../src/game/levels.js';
import { pointInPolygonXZ } from '../../src/game/zoneShape.js';
import { decodePng } from '../e2e/helpers.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.resolve(here, '..', '..');
const PUB = path.join(WEB, 'public');
const level = await loadLevelData('kalne_hamry');
const ter = parseGlb(readFileSync(path.join(PUB, level.geometry.terrain)));
const worldPath = level.geometry.render.find((p) => p.endsWith('kh_world.glb'));
const world = parseGlb(readFileSync(path.join(PUB, worldPath)));
const env = level.geometry.environment;
const veg = parseGlb(readFileSync(path.join(PUB, env.vegetation)));
const manifest = JSON.parse(readFileSync(path.join(PUB, env.terrainLayers), 'utf8'));
const splat = ter.json.asset.extras.iv.splat;

function glbImage(glb, index) {
  const im = glb.json.images[index];
  const v = glb.json.bufferViews[im.bufferView];
  return { bytes: Buffer.from(glb.bin.buffer, glb.bin.byteOffset + (v.byteOffset || 0), v.byteLength), mime: im.mimeType };
}

test('terrain splat: the layer manifest matches the level, 3 weight images cover the data square, every layer is used', () => {
  assert.equal(manifest.count, 10);
  assert.deepEqual(splat.layers, manifest.layers.map((l) => l.name));
  assert.deepEqual(splat.layers, ['GrassGround', 'MeadowLitter', 'ForestFloor', 'Dirt', 'Mud', 'Gravel', 'Asphalt', 'Concrete', 'PavingSetts', 'RiverStones']);
  for (const l of manifest.layers) assert.ok(l.tile_m >= 1 && l.tile_m <= 5, `${l.name} tile ${l.tile_m} m`);
  for (const f of Object.values(manifest.files)) assert.ok(existsSync(path.join(PUB, f.path)), f.path);
  assert.equal(splat.weightImages.length, 3);
  assert.equal(splat.res, 0.25);
  const imgs = splat.weightImages.map((i) => decodePng(glbImage(ter, i).bytes));
  for (const im of imgs) assert.deepEqual([im.width, im.height], [splat.size, splat.size]);
  const n = splat.size * splat.size;
  const used = new Array(10).fill(0);
  let bad = 0;
  for (let p = 0; p < n; p += 7) {
    let sum = 0;
    for (let l = 0; l < 10; l++) {
      const im = imgs[l >> 2];
      const v = im.data[p * im.channels + (l & 3)];
      sum += v;
      if (v > 128) used[l]++;
    }
    if (Math.abs(sum - 248) > 40) bad++; // 10 channels quantised to 32 levels (x8)
  }
  assert.ok(bad / (n / 7) < 0.001, `layer weights do not sum to 1 at ${bad} samples`);
  used.forEach((u, l) => assert.ok(u > 50, `layer ${splat.layers[l]} is used (${u} samples)`));
});

test('grass density: none on asphalt / water / brook stones, practically none on tracks and yards, no tall grass in capture zones', () => {
  const g = decodePng(glbImage(ter, splat.grassImage).bytes);
  const raster = { ...surfaceRasterFromGlb(ter), x0: ter.json.asset.extras.iv.surfaceRaster.x0, y0: ter.json.asset.extras.iv.surfaceRaster.y0 };
  const [x0, , , y1] = splat.rect;
  const res = splat.grassRes;
  const at = (x, z, ch) => {
    const i = Math.floor((x - x0) / res);
    const j = Math.floor((z + y1) / res);
    return g.data[(j * g.width + i) * g.channels + ch];
  };
  const counts = {};
  const hits = {};
  const yardViolations = [];
  for (let j = 0; j < raster.height; j += 1) {
    for (let i = 0; i < raster.width; i += 1) {
      const surf = raster.surfaces[raster.data[j * raster.width + i]];
      const cx = rasterX(raster, i);
      const cz = rasterZ(raster, j);
      counts[surf] = (counts[surf] || 0) + 1;
      const low = at(cx, cz, 0);
      const tall = at(cx, cz, 1);
      if (low > 0 || tall > 0) hits[surf] = (hits[surf] || 0) + 1;
      // yards / shoulders: at most the thin strip value along walls and fence plinths, never tall grass
      if (['gravel', 'concrete', 'paving'].includes(surf) && (tall > 0 || low > 0.36 * 255)) yardViolations.push([cx, cz, low, tall]);
    }
  }
  for (const s of ['asphalt', 'water', 'stone']) assert.equal(hits[s] || 0, 0, `grass on ${s}: ${hits[s]} of ${counts[s]} cells`);
  for (const s of ['dirt', 'mud']) assert.equal(hits[s] || 0, 0, `grass on ${s} (tracks, paths, ditches): ${hits[s]} of ${counts[s]} cells`);
  assert.deepEqual(yardViolations.slice(0, 5), [], `grass on yards / shoulders beyond the wall strips: ${yardViolations.length} cells`);
  for (const s of ['gravel', 'concrete', 'paving']) {
    const frac = (hits[s] || 0) / Math.max(counts[s] || 1, 1);
    // the small fenced yards have long 0.7 m wall strips (the rule itself is the value check above)
    assert.ok(frac < 0.2, `grass strips on ${s}: ${(frac * 100).toFixed(1)} % of cells`);
  }
  assert.ok((hits.grass || 0) / counts.grass > 0.6, `meadows have grass (${hits.grass} / ${counts.grass})`);
  // tall grass: never inside a capture zone (visual only, but no unfair hiding place)
  let tallInZone = 0;
  for (const z of level.match.zones) {
    const xs = z.polygon.map((p) => p[0]);
    const zs = z.polygon.map((p) => p[1]);
    for (let x = Math.min(...xs); x <= Math.max(...xs); x += res) {
      for (let zz = Math.min(...zs); zz <= Math.max(...zs); zz += res) {
        if (pointInPolygonXZ(z.polygon, x, zz) && at(x, zz, 1) > 0) tallInZone++;
      }
    }
  }
  assert.equal(tallInZone, 0, 'tall grass inside capture zones');
});

function rasterX(r, i) {
  return r.x0 + (i + 0.5) * r.res;
}
function rasterZ(r, j) {
  // rows north -> south; three z = -level y
  return -(r.y0 + r.height * r.res - (j + 0.5) * r.res);
}

test('vegetation: every tree species / shrub kind of the level has a model with LOD0 / LOD1 / LOD2 inside the triangle budget', () => {
  const iv = veg.json.asset.extras.iv;
  const w = world.json.asset.extras.iv.vegetation;
  assert.equal(w.models, env.vegetation);
  assert.equal(w.trees.count, 1650, 'every tree of layout.json is instanced');
  assert.ok(w.shrubs.count > 1000, `shrubs ${w.shrubs.count}`);
  const kinds = [...w.trees.kindNames, ...w.shrubs.kindNames];
  for (const k of kinds) {
    const list = iv.speciesModels[k] || iv.speciesModels[k.replace(/_les$/, '')];
    assert.ok(list && list.length, `species ${k} mapped`);
    for (const m of list) assert.ok(iv.models[m], `model ${m} of ${k}`);
  }
  for (const [name, m] of Object.entries(iv.models)) {
    assert.equal(m.lods.length, 3, name);
    const shrub = name.startsWith('shrub') || name.startsWith('hedge');
    const [t0, t1, t2] = m.lods.map((l) => l.triangles);
    assert.ok(t0 <= (shrub ? 1500 : 6500), `${name} LOD0 ${t0} tris`);
    assert.ok(t1 <= (shrub ? 700 : 1700) && t1 < t0, `${name} LOD1 ${t1} tris`);
    assert.ok(t2 <= 100 && t2 < t1, `${name} LOD2 ${t2} tris`);
    assert.ok(m.height > 0.5 && m.crownRadius > 0.3, name);
  }
  const d = iv.lodDistances;
  assert.ok(d.lod1 < d.lod2 && d.shrub_lod1 < d.shrub_lod2 && d.hysteresis > 0);
  for (const k of ['foliage', 'foliageNormal', 'grass', 'hedge', 'hedgeNormal', 'bark', 'barkNormal']) assert.ok(iv.images[k] !== undefined, `image ${k}`);
  // instance rows: sane transforms
  const rows = readAccessor(world, w.trees.rows);
  for (let i = 0; i < w.trees.count; i++) {
    const h = rows[i * 8 + 4];
    const cr = rows[i * 8 + 5];
    assert.ok(h > 3 && h < 30 && cr > 1 && cr < 12, `tree ${i}: h ${h}, crown ${cr}`);
  }
});

test('size budget: every environment / level file stays under the Artifact host limit (15 MiB as base64)', () => {
  const files = [env.vegetation, ...Object.values(manifest.files).map((f) => f.path), level.geometry.terrain, worldPath, level.geometry.collision];
  let total = 0;
  for (const f of files) {
    const b = statSync(path.join(PUB, f)).size;
    total += b;
    assert.ok((b * 4) / 3 < 15 * 1048576, `${f}: ${(b / 1048576).toFixed(2)} MiB`);
  }
  const envBytes = [env.vegetation, ...Object.values(manifest.files).map((f) => f.path)].reduce((s, f) => s + statSync(path.join(PUB, f)).size, 0);
  assert.ok(envBytes < 6.5 * 1048576, `environment assets ${(envBytes / 1048576).toFixed(2)} MiB`);
  assert.ok(total > 0);
});
