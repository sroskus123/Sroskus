#!/usr/bin/env node
// Review screenshots of Kalné Hamry from fixed viewpoints (map art passes, Docs/MAP_art_*.json) and the game's own
// render statistics per view (draw calls / triangles incl. the shadow pass, WebGLRenderer.info).
// Headless Chromium + SwiftShader (software WebGL): the pictures are faithful, the timings are NOT real GPU numbers.
//
// Usage: node tools/level_shots.mjs [--prefix after] [--out ../Art/Previews/Environment] [--views square,road,...]
//                                  [--width 1600 --height 900]
// Needs `npm run build` first (serves dist/).

import { mkdirSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { launchGame } from '../tests/e2e/helpers.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const args = process.argv.slice(2);
const opt = (n, d) => {
  const i = args.indexOf(n);
  return i >= 0 ? args[i + 1] : d;
};
const prefix = opt('--prefix', 'shot');
const outDir = path.resolve(opt('--out', path.join(here, '..', '..', 'Art', 'Previews', 'Environment')));
const width = +opt('--width', 1600);
const height = +opt('--height', 900);

// three.js coordinates (x, y up, z = -level y); free camera. With `ground: true` the y of pos / target is the height
// above the terrain / floor below that point (world raycast).
export const VIEWS = {
  // the village square (granite setts), looking NE past the linden towards the chapel and the warehouse yard
  square: { cam: { pos: [-9.0, 1.7, 4.5], target: [12.0, 1.2, -6.0], fovDeg: 80, ground: true } },
  // the main road B with the concrete bridge over the brook, looking N along the road
  road: { cam: { pos: [9.0, 1.7, -32.0], target: [-14.0, 0.5, -16.0], fovDeg: 80, ground: true } },
  // standing in the meadow east of the road, facing the road with a low wooden obstacle in front and trees behind
  // (the user's screenshot)
  meadow: { cam: { pos: [-92.0, 1.7, 60.0], target: [-106.5, 1.4, 35.9], fovDeg: 80, ground: true } },
  // the game's default view: the practice spawn marker (what a player sees first, the user's screenshot)
  spawn: { marker: 'spawn' },
  // the forest edge south of the house garden, looking into the edge band of the forest
  forest: { cam: { pos: [-40.0, 1.7, 64.0], target: [-60.0, 3.0, 88.0], fovDeg: 80, ground: true } },
  // high overview over the village like the aerial reference 01
  overview: { cam: { pos: [70.0, 75.0, 75.0], target: [-5.0, 0.0, -5.0], fovDeg: 70 } },
  // eye-level views for detail (1.7 m): asphalt close-up and grass close-up
  asphalt: { cam: { pos: [2.6, 1.7, -24.0], target: [5.0, 0.0, -30.0], fovDeg: 75, ground: true } },
  grass: { cam: { pos: [34.0, 1.7, -40.0], target: [39.0, 0.0, -46.0], fovDeg: 75, ground: true } },
  // the shrub copse VK_9 east of the warehouse yard from above (render-only core + shrub instances, R3 check)
  copse: { cam: { pos: [40.0, 14.0, 26.0], target: [46.0, 2.0, 12.0], fovDeg: 60, ground: true } },
};

async function main() {
  const only = opt('--views', null);
  const names = only ? only.split(',') : Object.keys(VIEWS);
  mkdirSync(outDir, { recursive: true });
  const g = await launchGame({ width, height });
  const page = g.page;
  page.setDefaultTimeout(900_000);
  const load = await page.evaluate(async () => {
    const iv = window.__IV;
    const t0 = performance.now();
    const info = await iv.loadLevel('kalne_hamry');
    const ms = performance.now() - t0;
    iv.startGame();
    iv.pause();
    iv.setSetting('adaptiveResolution', false);
    iv.setSetting('renderScale', 1);
    iv.teleportToMarker('spawn');
    iv.step(2);
    return { ms, load: info.load };
  });
  console.log(`load ${load.ms.toFixed(0)} ms ${JSON.stringify(load.load)}`);
  await page.addStyleTag({ content: '.iv-hud{display:none!important}' });
  const stats = { load, views: {} };
  for (const name of names) {
    const v = VIEWS[name];
    if (!v) throw new Error(`unknown view ${name}`);
    const r = await page.evaluate(async (v) => {
      const iv = window.__IV;
      const gm = iv._game;
      if (v.marker) {
        iv.setCameraOverride(null);
        iv.teleportToMarker(v.marker);
        iv.step(2);
      }
      const cam = v.cam ? { ...v.cam, pos: v.cam.pos.slice(), target: v.cam.target.slice() } : null;
      if (cam && cam.ground) {
        const ground = (p) => {
          const o = gm.camera.position.clone().set(p[0], 400, p[2]);
          const h = gm.world.raycast(o, gm.camera.up.clone().set(0, -1, 0), 800);
          return h ? h.point.y : 0;
        };
        cam.pos[1] += ground(cam.pos);
        cam.target[1] += ground(cam.target);
      }
      if (cam) iv.setCameraOverride(cam);
      // put the player near the camera (vegetation LOD / grass follow the camera, shadows follow the eye)
      const ri = gm.renderer.renderer.info;
      iv.step(1);
      iv.renderNow(); // warm-up (shader compile, LOD update)
      iv.renderNow();
      ri.autoReset = false;
      ri.reset();
      const t0 = performance.now();
      iv.renderNow();
      const ms = performance.now() - t0;
      ri.autoReset = true;
      return { calls: ri.render.calls, triangles: ri.render.triangles, ms, textures: ri.memory.textures, geometries: ri.memory.geometries };
    }, v);
    await new Promise((res) => setTimeout(res, 300));
    const file = path.join(outDir, `${prefix}_${name}.png`);
    await page.screenshot({ path: file, type: 'png', timeout: 300_000 });
    stats.views[name] = r;
    console.log(`${name}: ${r.calls} draw calls, ${r.triangles} triangles, frame ${r.ms.toFixed(0)} ms (SwiftShader) -> ${path.relative(process.cwd(), file)}`);
  }
  writeFileSync(path.join(outDir, `${prefix}_stats.json`), JSON.stringify(stats, null, 1) + '\n');
  if (g.errors.length) console.log(`console errors: ${g.errors.join(' | ')}`);
  await g.close();
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
