// Boot, rendering and page-variant checks on the real build (dist/ served locally).
import test, { after, before } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { DIST, decodePng, imageStats, launchGame, loadPlaywright, CHROMIUM_ARGS, screenshot, SCREENS } from './helpers.mjs';
import { startServer } from '../../tools/serve.mjs';

let g;

before(async () => {
  g = await launchGame({ width: 960, height: 540 });
});

after(async () => {
  if (g) await g.close();
});

test('page loads with zero console errors and zero failed requests', async () => {
  // real user flow: click the start button (requests pointer lock; headless may refuse -> drag fallback)
  await g.page.click('.iv-btn-primary');
  await g.page.waitForFunction(() => window.__IV.getState().state === 'playing', null, { timeout: 20_000 });
  // let the real-time loop run a few frames
  await g.page.waitForFunction(() => window.__IV.getState().frame > 5, null, { timeout: 120_000 });
  const s = await g.page.evaluate(() => {
    const st = window.__IV.getState();
    window.__IV.pause(); // stop real-time frames so SwiftShader does not queue up work
    return st;
  });
  assert.equal(s.render.webgl2, true, 'WebGL2 context');
  assert.deepEqual(g.errors, [], `console errors: ${g.errors.join(' | ')}`);
  assert.deepEqual(g.failed, [], `failed requests: ${g.failed.join(' | ')}`);
  assert.ok(g.requests.some((u) => u.endsWith('/game.js')), 'game.js requested');
  assert.ok(['lock', 'drag'].includes(s.input.lookMode), `look mode ${s.input.lookMode}`);
});

test('canvas shows a non-black, non-uniform image (first-person view in the test range)', async () => {
  await g.page.evaluate(() => {
    const iv = window.__IV;
    iv.pause();
    iv.setSetting('adaptiveResolution', false);
    iv.setSetting('renderScale', 1);
    iv.teleportToMarker('overview');
    iv.step(2, { render: true });
  });
  const { buf } = await screenshot(g.page, 'first_person_overview.png');
  const img = decodePng(buf);
  assert.equal(img.width, 960);
  assert.equal(img.height, 540);
  const all = imageStats(img);
  const center = imageStats(img, { x: 240, y: 135, w: 480, h: 270 });
  assert.ok(all.nonBlackRatio > 0.95, `non-black ratio ${all.nonBlackRatio}`);
  assert.ok(all.std > 20, `luminance std ${all.std}`);
  assert.ok(all.usedBins >= 10, `histogram bins ${all.usedBins}`);
  assert.ok(all.distinctColors > 300, `distinct colours ${all.distinctColors}`);
  assert.ok(center.std > 10, `centre std ${center.std}`);
  assert.ok(all.mean > 40 && all.mean < 230, `mean ${all.mean}`);
});

test('sky sun direction exactly matches the directional light', async () => {
  const sun = await g.page.evaluate(() => window.__IV.getState().sun);
  assert.ok(sun.dot > 0.999999, `dot ${sun.dot}`);
  assert.ok(sun.lightDirection[1] > 0.5, 'sun above horizon');
});

test('clouds looking up (yaw 60, pitch 55) have internal detail, not one flat blob (screenshot)', async () => {
  await g.page.evaluate(() => {
    const iv = window.__IV;
    iv.pause();
    iv.releaseAll();
    iv.teleport(0, 0, 20, 60, 55);
    iv.step(2, { render: true });
  });
  const detailed = await g.page.evaluate(() => window.__IV.getState().sky.detailedClouds);
  assert.equal(detailed, true, 'detailed cloud shader patched into Sky');
  const { buf } = await screenshot(g.page, 'sky_clouds_up.png');
  const img = decodePng(buf);
  // low-saturation bright pixels = cloud; measure luminance spread and local gradient inside them
  const { width, channels, data } = img;
  const lum = (x, y) => {
    const i = (y * width + x) * channels;
    return 0.2126 * data[i] + 0.7152 * data[i + 1] + 0.0722 * data[i + 2];
  };
  const isCloud = (x, y) => {
    const i = (y * width + x) * channels;
    return data[i + 2] - data[i] < 60 && (data[i] + data[i + 1] + data[i + 2]) / 3 > 90;
  };
  let n = 0;
  let sum = 0;
  let sum2 = 0;
  let grad = 0;
  for (let y = 41; y < 339; y++) {
    for (let x = 1; x < 959; x++) {
      if (!isCloud(x, y) || !isCloud(x + 1, y) || !isCloud(x, y + 1)) continue;
      const l = lum(x, y);
      n++;
      sum += l;
      sum2 += l * l;
      grad += Math.abs(lum(x + 1, y) - l) + Math.abs(lum(x, y + 1) - l);
    }
  }
  const mean = sum / n;
  const std = Math.sqrt(sum2 / n - mean * mean);
  const meanGrad = grad / n;
  console.log(`# clouds up: cloud pixels ${n}, luminance std ${std.toFixed(1)}, mean local gradient ${meanGrad.toFixed(2)}`);
  // the old flat blob measured std ~10 and gradient ~0.35 on this view
  assert.ok(n > 5000, `too few cloud pixels (${n})`);
  assert.ok(std > 15, `cloud luminance std ${std}`);
  assert.ok(meanGrad > 1.0, `cloud local gradient ${meanGrad}`);
});

test('renderer uses sRGB output, ACES tone mapping and shadows', async () => {
  const r = await g.page.evaluate(() => {
    const gl = window.__IV._game.renderer.renderer;
    return { cs: gl.outputColorSpace, tm: gl.toneMapping, shadows: gl.shadowMap.enabled, env: !!window.__IV._game.scene.environment };
  });
  assert.equal(r.cs, 'srgb');
  assert.equal(r.tm, 4); // THREE.ACESFilmicToneMapping
  assert.equal(r.shadows, true);
  assert.equal(r.env, true);
});

test('no direct sunlight leaks under the tunnel roof: occluded wall band identical with sun on and off (screenshots)', async () => {
  // Regression: a loose shadow depth range (near 1 / far 220 m) made the normalised depth bias
  // about 9 cm, so the inner wall just under the 1.4 m roof showed dithered sunlit stripes.
  const info = await g.page.evaluate(() => window.__IV.getState().shadow);
  assert.ok(info.far - info.near < 120, `shadow depth range ${info.near}..${info.far} m`);
  assert.ok(info.biasMeters > 0 && info.biasMeters < 0.01, `shadow bias ${info.biasMeters} m`);
  const shoot = async (name, view, sun, crouch) => {
    await g.page.evaluate(
      ({ view, sun, crouch, bounce }) => {
        const iv = window.__IV;
        iv.startGame();
        iv.pause();
        iv.releaseAll();
        // only the direct sunlight is switched; the baked sunlight bounce stays as with the sun on
        iv.setLighting({ sun, bounceSun: bounce });
        iv.teleport(...view);
        if (crouch) iv.keyDown('KeyC');
        iv.step(40, { render: true });
        iv.keyUp('KeyC');
      },
      { view, sun, crouch, bounce: sunOn },
    );
    return decodePng((await screenshot(g.page, name)).buf);
  };
  const sunOn = await g.page.evaluate(() => window.__IV._game.env.sun.intensity);
  const band = { x: 330, y: 0, w: 600, h: 40 }; // inner east wall right under the roof (HUD label is left of x 330)
  const tunnelView = [2.7, 0, -7.0, -90, -10];
  const on = await shoot('tunnel_roof_sun_on.png', tunnelView, sunOn, true);
  const off = await shoot('tunnel_roof_sun_off.png', tunnelView, 0, true);
  // guard: the sun really lights the open range in the same session
  const openOn = imageStats(await shoot('open_sun_on.png', [0, 0, 12, 0, -20], sunOn, false));
  const openOff = imageStats(await shoot('open_sun_off.png', [0, 0, 12, 0, -20], 0, false));
  await g.page.evaluate((s) => window.__IV.setLighting({ sun: s, bounceSun: null }), sunOn);
  assert.ok(openOn.mean > openOff.mean + 15, `sun lights the open floor: ${openOn.mean} vs ${openOff.mean}`);
  const lum = (img, x, y) => {
    const i = (y * img.width + x) * img.channels;
    return 0.2126 * img.data[i] + 0.7152 * img.data[i + 1] + 0.0722 * img.data[i + 2];
  };
  let sumDiff = 0;
  let maxBelow = 0; // below the junction line itself (rows >= 2)
  let brighter = 0;
  let n = 0;
  for (let y = band.y; y < band.y + band.h; y++) {
    for (let x = band.x; x < band.x + band.w; x++) {
      const d = lum(on, x, y) - lum(off, x, y);
      sumDiff += d;
      if (d > 4) brighter++;
      if (y >= band.y + 2) maxBelow = Math.max(maxBelow, d);
      n++;
    }
  }
  console.log(`# tunnel roof band sun on - off: mean ${(sumDiff / n).toFixed(2)}, pixels > +4: ${brighter}/${n}, max below the junction row ${maxBelow.toFixed(1)} (before the fix: mean +10.1, max +29)`);
  assert.ok(sumDiff / n < 1.0, `mean luminance leak ${sumDiff / n}`);
  // single dithered pixels on the junction line itself (PCF kernel) are tolerated, a band is not
  assert.ok(brighter <= n * 0.001, `${brighter} pixels brighter by more than 4 with the sun on`);
  assert.ok(maxBelow < 6, `brightest leaked pixel below the junction line +${maxBelow}`);
});

test('enclosed spaces get less ambient light than open ground: tunnel wall vs open wall of the same material and orientation (screenshots)', async () => {
  // Before: the image-based sky light reached every surface fully, so the tunnel's inner walls
  // were exactly as bright as walls in the open. Sun off = ambient light only; eye adaptation
  // frozen so both views use the same exposure.
  const bake = await g.page.evaluate(() => window.__IV.getState().bakedLighting);
  assert.ok(bake && bake.vertices > 5000, `baked level lighting present: ${JSON.stringify(bake)}`);
  const shoot = async (name, view, crouch) => {
    const st = await g.page.evaluate(
      ({ view, crouch }) => {
        const iv = window.__IV;
        iv.startGame();
        iv.pause();
        iv.releaseAll();
        iv.setEyeAdaptation(false);
        iv.setLighting({ sun: 0 });
        iv.teleport(...view);
        if (crouch) iv.keyDown('KeyC');
        iv.step(40, { render: true });
        iv.keyUp('KeyC');
        return iv.getState().bakedLighting;
      },
      { view, crouch },
    );
    return { img: decodePng((await screenshot(g.page, name)).buf), st };
  };
  const sunOn = await g.page.evaluate(() => window.__IV._game.env.sun.intensity);
  // both walls face -x (west) and use the 'wall' material: the tunnel's east inner wall, and
  // the tunnel's west outer wall seen from the open ground in front of it
  const inside = await shoot('ao_tunnel_wall_ambient.png', [2.7, 0, -5.5, -90, 0], true);
  const open = await shoot('ao_open_wall_ambient.png', [0.2, 0, -5.5, -90, 0], true);
  await g.page.evaluate((s) => {
    window.__IV.setLighting({ sun: s });
    window.__IV.setEyeAdaptation(true);
  }, sunOn);
  const region = { x: 380, y: 120, w: 200, h: 120 };
  const lin = (v) => ((v / 255 + 0.055) / 1.055) ** 2.4;
  const a = imageStats(inside.img, region).mean;
  const b = imageStats(open.img, region).mean;
  console.log(`# ambient only: tunnel wall ${a.toFixed(1)}, open wall ${b.toFixed(1)} (linear ratio ${(lin(a) / lin(b)).toFixed(2)}); eye sky visibility inside ${inside.st.eyeSky.toFixed(2)}, view-model ambient ${inside.st.viewModelAmbient.toFixed(2)}`);
  assert.ok(lin(a) < 0.5 * lin(b), `tunnel wall ${a} vs open wall ${b}: interior must get clearly less ambient light`);
  assert.ok(inside.st.eyeSky < 0.2 && open.st.eyeSky > 0.6, `eye sky visibility inside ${inside.st.eyeSky}, open ${open.st.eyeSky}`);
  assert.ok(inside.st.viewModelAmbient < 0.5 && open.st.viewModelAmbient > 0.6, 'the held weapon darkens with the world inside');
});

test('gameplay muzzle matches the drawn muzzle socket (hip incl. cant, ADS, and during the ADS transition) within 2 mm', async (t) => {
  const m = await g.page.evaluate(() => window.__IV.muzzleConsistency());
  if (m.model === 'placeholder') {
    t.skip('IV-7 GLB not in this build (placeholder has no socket to compare)');
    return;
  }
  // rendered = socket_muzzle node position in camera space after the real viewModel.update() at rest
  assert.ok(m.hip.rendered && m.hip.renderedDistance < 0.002, JSON.stringify(m.hip));
  assert.ok(m.ads.rendered && m.ads.renderedDistance < 0.002, JSON.stringify(m.ads));
  // the analytic pose used by tools agrees with the drawn one
  assert.ok(m.hip.distance < 0.002 && m.ads.distance < 0.002, JSON.stringify(m));
  // mid-transition (the drawn weapon eases and un-cants; shots must leave from the drawn muzzle)
  assert.equal(m.transition.length, 5);
  for (const tr of m.transition) assert.ok(tr.renderedDistance !== null && tr.renderedDistance < 0.002, JSON.stringify(m.transition));
  const worst = Math.max(...m.transition.map((tr) => tr.renderedDistance));
  console.log(`# muzzle: hip rendered-vs-logic ${(m.hip.renderedDistance * 1000).toFixed(3)} mm, ADS ${(m.ads.renderedDistance * 1000).toFixed(3)} mm, transition worst ${(worst * 1000).toFixed(3)} mm`);
});

test('artifact.html has no document skeleton and boots when wrapped by a host page', async () => {
  const html = await readFile(path.join(DIST, 'artifact.html'), 'utf8');
  assert.ok(html.startsWith('<title>Iron Valley</title>'), 'starts with <title>');
  assert.ok(/<style>/.test(html), 'has a <style> block');
  assert.ok(!/<!doctype/i.test(html) && !/<html[\s>]/i.test(html) && !/<head[\s>]/i.test(html) && !/<body[\s>]/i.test(html), 'no skeleton tags');
  assert.ok(html.includes('src="game.js"'), 'relative game.js reference');
  const index = await readFile(path.join(DIST, 'index.html'), 'utf8');
  assert.ok(/^<!doctype html>/i.test(index) && index.includes('src="game.js"'));

  // simulate a host that wraps the fragment in its own skeleton
  const server = await startServer({ root: DIST });
  const { chromium } = loadPlaywright();
  const browser = await chromium.launch({ headless: true, args: CHROMIUM_ARGS });
  try {
    const page = await browser.newPage({ viewport: { width: 960, height: 540 } });
    const errors = [];
    const failed = [];
    page.on('console', (m) => m.type() === 'error' && errors.push(m.text()));
    page.on('pageerror', (e) => errors.push(String(e)));
    page.on('requestfailed', (r) => failed.push(r.url()));
    page.on('response', (r) => r.status() >= 400 && failed.push(`${r.url()} ${r.status()}`));
    // the host page itself lives at the server origin; the fragment is injected as its body
    await page.goto(server.url + 'build-info.json');
    await page.setContent(`<!doctype html><html><head><meta charset="utf-8"><base href="${server.url}"></head><body>${html}</body></html>`);
    await page.waitForFunction(() => window.__IV_BOOT && window.__IV_BOOT.status !== 'loading', null, { timeout: 90_000 });
    const boot = await page.evaluate(() => window.__IV_BOOT);
    assert.equal(boot.status, 'ready', JSON.stringify(boot));
    assert.equal(await page.title(), 'Iron Valley');
    assert.deepEqual(errors, []);
    assert.deepEqual(failed, []);
  } finally {
    await browser.close();
    await server.close();
  }
});

test('artifact.html under a strict host CSP (no blob:, no inline script): boots, weapon textures load, 0 errors', async () => {
  const html = await readFile(path.join(DIST, 'artifact.html'), 'utf8');
  const csp = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'";
  const server = await startServer({ root: DIST });
  const { chromium } = loadPlaywright();
  const browser = await chromium.launch({ headless: true, args: CHROMIUM_ARGS });
  try {
    const page = await browser.newPage({ viewport: { width: 480, height: 270 } });
    const errors = [];
    const failed = [];
    page.on('console', (m) => m.type() === 'error' && errors.push(m.text()));
    page.on('pageerror', (e) => errors.push(String(e)));
    page.on('requestfailed', (r) => failed.push(r.url()));
    page.on('response', (r) => r.status() >= 400 && failed.push(`${r.url()} ${r.status()}`));
    await page.goto(server.url + 'build-info.json');
    await page.setContent(
      `<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="${csp}"><base href="${server.url}"></head><body>${html}</body></html>`,
    );
    await page.waitForFunction(() => window.__IV_BOOT && window.__IV_BOOT.status !== 'loading', null, { timeout: 90_000 });
    const r = await page.evaluate(() => ({ boot: window.__IV_BOOT, asset: window.__IV.getState().weaponAsset }));
    assert.equal(r.boot.status, 'ready', JSON.stringify(r.boot));
    assert.deepEqual(errors, [], `console errors under CSP: ${errors.slice(0, 3).join(' | ')}`);
    assert.deepEqual(failed, []);
    if (r.asset.path && r.asset.loaded) {
      assert.equal(r.asset.isPlaceholder, false);
      const tx = r.asset.textures;
      assert.ok(tx.referenced > 0 && tx.withImage === tx.referenced, `weapon textures ${JSON.stringify(tx)}`);
      assert.ok(tx.embeddedDecodedWithoutUrl >= tx.referenced, `decoded without blob: URLs ${JSON.stringify(tx)}`);
    }
  } finally {
    await browser.close();
    await server.close();
  }
});

test('small HUD labels (stance, location) keep >= 4.5:1 contrast even over a white background', async () => {
  const r = await g.page.evaluate(() => {
    const iv = window.__IV;
    iv.pause();
    iv.releaseAll();
    iv.startGame();
    iv.pause();
    iv.setDrawEnabled(false);
    iv.teleportToMarker('spawn');
    iv.keyDown('KeyC');
    iv.step(10, { render: true }); // HUD update runs in render
    const parse = (c) => {
      const m = c.match(/rgba?\(([^)]+)\)/);
      const v = m[1].split(',').map((x) => parseFloat(x));
      return { r: v[0], g: v[1], b: v[2], a: v.length > 3 ? v[3] : 1 };
    };
    const lin = (u) => {
      const x = u / 255;
      return x <= 0.04045 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4;
    };
    const L = (c) => 0.2126 * lin(c.r) + 0.7152 * lin(c.g) + 0.0722 * lin(c.b);
    const worst = (sel, plateSel) => {
      const el = document.querySelector(sel);
      const cs = getComputedStyle(el);
      const fg = parse(cs.color);
      const plate = parse(getComputedStyle(document.querySelector(plateSel)).backgroundColor);
      // plate composited over the brightest possible scene pixel (white)
      const bg = { r: plate.a * plate.r + (1 - plate.a) * 255, g: plate.a * plate.g + (1 - plate.a) * 255, b: plate.a * plate.b + (1 - plate.a) * 255 };
      const l1 = L(fg);
      const l2 = L(bg);
      return {
        text: el.textContent,
        visible: cs.display !== 'none' && el.getBoundingClientRect().width > 0,
        fontPx: parseFloat(cs.fontSize),
        contrast: (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05),
      };
    };
    const out = {
      stance: worst('.iv-stance', '.iv-stance'),
      locationName: worst('.iv-location-name', '.iv-location'),
      locationTag: worst('.iv-location-tag', '.iv-location'),
    };
    iv.keyUp('KeyC');
    iv.step(30);
    iv.setDrawEnabled(true);
    return out;
  });
  console.log(`# HUD worst-case contrast: ${JSON.stringify(r)}`);
  assert.equal(r.stance.text, 'DŘEP');
  for (const [k, v] of Object.entries(r)) {
    assert.ok(v.visible, `${k} not visible`);
    assert.ok(v.contrast >= 4.5, `${k}: contrast ${v.contrast.toFixed(2)} on white`);
    assert.ok(v.fontPx >= 12, `${k}: font ${v.fontPx}px`);
  }
});

test('narrow / touch screens get the Czech keyboard-and-mouse note; 960x540 does not', async () => {
  const wideVisible = await g.page.evaluate(() => getComputedStyle(document.querySelector('.iv-touch-note')).display !== 'none');
  assert.equal(wideVisible, false, 'note hidden at 960x540');
  await g.page.setViewportSize({ width: 390, height: 780 });
  await g.page.waitForTimeout(200);
  const narrow = await g.page.evaluate(() => {
    const el = document.querySelector('.iv-touch-note');
    return { visible: getComputedStyle(el).display !== 'none', text: el.textContent };
  });
  assert.equal(narrow.visible, true);
  assert.match(narrow.text, /klávesnici a myš/);
  await g.page.evaluate(() => window.__IV.renderNow());
  await screenshot(g.page, 'narrow_note.png');
  await g.page.setViewportSize({ width: 960, height: 540 });
  await g.page.waitForTimeout(200);
  const again = await g.page.evaluate(() => getComputedStyle(document.querySelector('.iv-touch-note')).display !== 'none');
  assert.equal(again, false);
  assert.ok(SCREENS);
});

test('pointer lock rejection falls back to click-and-drag look', async () => {
  await g.page.evaluate(() => {
    const iv = window.__IV;
    iv.resume();
    iv.openMenu();
    // simulate a host frame without pointer-lock permission
    HTMLCanvasElement.prototype.requestPointerLock = function () {
      return Promise.reject(new DOMException('Pointer lock denied', 'NotAllowedError'));
    };
  });
  await g.page.click('.iv-btn-primary');
  await g.page.waitForFunction(() => window.__IV.getState().input.lookMode === 'drag', null, { timeout: 5000 });
  const notice = await g.page.evaluate(() => document.querySelector('.iv-notice').textContent);
  assert.match(notice, /tažením myši/);
  const yaw0 = await g.page.evaluate(() => {
    window.__IV.pause();
    return window.__IV.getState().player.yawDeg;
  });
  // drag with the right button (aim) so the test does not fire
  await g.page.mouse.move(480, 270);
  await g.page.mouse.down({ button: 'right' });
  await g.page.mouse.move(580, 270, { steps: 10 });
  await g.page.mouse.up({ button: 'right' });
  const r = await g.page.evaluate(() => {
    window.__IV.renderNow();
    const s = window.__IV.getState();
    return { yaw: s.player.yawDeg, locked: s.input.pointerLocked, mode: s.input.lookMode };
  });
  assert.equal(r.locked, false);
  assert.equal(r.mode, 'drag');
  assert.ok(r.yaw < yaw0 - 3, `dragging right should turn right: ${yaw0} -> ${r.yaw}`);
  // moving the mouse without a button does not turn the view in drag mode
  await g.page.mouse.move(380, 270, { steps: 5 });
  const r2 = await g.page.evaluate(() => {
    window.__IV.renderNow();
    return window.__IV.getState().player.yawDeg;
  });
  assert.ok(Math.abs(r2 - r.yaw) < 1e-6, `hover changed yaw ${r.yaw} -> ${r2}`);
  assert.deepEqual(g.errors, []);
});

test('IV-7 GLB is the held weapon: loads, metric scale, muzzle forward, lower right, ADS eye on the optic axis', async (t) => {
  const exists = await g.page.evaluate(() => window.__IV.getState().assets.includes('assets/weapons/IV7_Carbine.glb'));
  if (!exists) {
    t.skip('public/assets/weapons/IV7_Carbine.glb not present in this build (placeholder in use)');
    return;
  }
  const r = await g.page.evaluate(() => {
    const iv = window.__IV;
    iv.pause();
    iv.releaseAll();
    iv.teleportToMarker('overview');
    iv.setLook(-8, -2);
    iv.step(5, { render: true });
    const s = iv.getState();
    const game = iv._game;
    const vm = game.viewModel;
    // project the hip muzzle socket with the view model camera
    const p = vm.muzzleInCameraSpace(0);
    const cam = vm.camera;
    const v = p.clone().applyMatrix4(cam.projectionMatrix);
    return { asset: s.weaponAsset, muzzleNdc: [v.x, v.y], consistency: iv.muzzleConsistency() };
  });
  const a = r.asset;
  assert.equal(a.loaded, true, JSON.stringify(a));
  assert.equal(a.isPlaceholder, false);
  assert.equal(a.muzzleNode, 'socket_muzzle');
  assert.equal(a.adsEyeNode, 'socket_ads');
  // metric scale: overall length 0.86 m along +X (muzzle), width about 5 cm
  const len = a.boundsMax[0] - a.boundsMin[0];
  assert.ok(Math.abs(len - 0.86) < 0.02, `length ${len} m`);
  assert.ok(a.size[2] < 0.08, `width ${a.size[2]} m`);
  assert.ok(Math.abs(a.muzzleLocal[0] - a.boundsMax[0]) < 0.01, 'muzzle socket at the front (+X) end');
  // held in the lower right, pointing forward
  assert.ok(r.muzzleNdc[0] > 0.05 && r.muzzleNdc[0] < 0.6, `muzzle ndc x ${r.muzzleNdc[0]}`);
  assert.ok(r.muzzleNdc[1] < -0.1 && r.muzzleNdc[1] > -0.9, `muzzle ndc y ${r.muzzleNdc[1]}`);
  assert.ok(r.consistency.hip.renderedDistance < 0.002 && r.consistency.ads.renderedDistance < 0.002, JSON.stringify(r.consistency));
  assert.ok(r.consistency.adsEye.distance < 0.002, `ADS eye ${JSON.stringify(r.consistency.adsEye)}`);
  await screenshot(g.page, 'weapon_hip.png');
  await g.page.evaluate(() => {
    const iv = window.__IV;
    iv.startGame();
    iv.pause();
    iv.mouseButton(2, true);
    iv.step(30, { render: true });
  });
  const ads = await g.page.evaluate(() => window.__IV.getState().weapon.ads);
  assert.equal(ads, 1);
  await screenshot(g.page, 'weapon_ads.png');
  await g.page.evaluate(() => {
    window.__IV.mouseButton(2, false);
    window.__IV.step(30);
  });
  assert.deepEqual(g.errors, []);
  assert.deepEqual(g.failed, []);
});
