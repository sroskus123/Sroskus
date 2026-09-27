// Shared helpers for the browser end-to-end tests: loads Playwright from a global install
// (no browser download), serves dist/ with tools/serve.mjs, launches headless Chromium with
// WebGL2 via SwiftShader (software rendering: slow, NOT representative of real performance),
// collects console errors / failed requests, and decodes PNG screenshots for pixel checks.

import { createRequire } from 'node:module';
import { existsSync, mkdirSync } from 'node:fs';
import path from 'node:path';
import zlib from 'node:zlib';
import { fileURLToPath } from 'node:url';
import { startServer } from '../../tools/serve.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
export const WEB_ROOT = path.resolve(here, '..', '..');
export const DIST = path.join(WEB_ROOT, 'dist');
export const SCREENS = path.join(here, 'screens');

if (!process.env.PLAYWRIGHT_BROWSERS_PATH && existsSync('/opt/pw-browsers')) {
  process.env.PLAYWRIGHT_BROWSERS_PATH = '/opt/pw-browsers';
}

export function loadPlaywright() {
  const require = createRequire(import.meta.url);
  const nodeDir = path.dirname(process.execPath);
  const candidates = [
    process.env.PLAYWRIGHT_MODULE,
    'playwright',
    path.join(nodeDir, '..', 'lib', 'node_modules', 'playwright'), // global npm prefix (Linux/macOS)
    path.join(nodeDir, 'node_modules', 'playwright'), // global npm prefix (Windows)
    '/opt/node22/lib/node_modules/playwright',
  ].filter(Boolean);
  const errors = [];
  for (const c of candidates) {
    try {
      return require(c);
    } catch (e) {
      errors.push(`${c}: ${e.code || e.message}`);
    }
  }
  throw new Error(`Playwright not found (install it globally or set PLAYWRIGHT_MODULE). Tried:\n${errors.join('\n')}`);
}

export const CHROMIUM_ARGS = ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'];

/**
 * Serves dist/, opens the game and waits until it booted.
 * @returns {Promise<{page, browser, server, errors:string[], warnings:string[], failed:string[], close:()=>Promise<void>}>}
 */
export async function launchGame({ width = 960, height = 540, file = 'index.html', waitReady = true } = {}) {
  if (!existsSync(path.join(DIST, 'index.html'))) throw new Error('dist/ is missing - run "npm run build" first');
  mkdirSync(SCREENS, { recursive: true });
  const server = await startServer({ root: DIST });
  const { chromium } = loadPlaywright();
  const browser = await chromium.launch({ headless: true, args: CHROMIUM_ARGS });
  const context = await browser.newContext({ viewport: { width, height }, deviceScaleFactor: 1 });
  const page = await context.newPage();
  const errors = [];
  const warnings = [];
  const failed = [];
  const requests = [];
  page.on('console', (msg) => {
    if (msg.type() === 'error') errors.push(msg.text());
    else if (msg.type() === 'warning') warnings.push(msg.text());
  });
  page.on('pageerror', (err) => errors.push(`pageerror: ${err && err.message ? err.message : err}`));
  page.on('request', (req) => requests.push(req.url()));
  page.on('requestfailed', (req) => failed.push(`${req.url()} (${req.failure() ? req.failure().errorText : 'failed'})`));
  page.on('response', (res) => {
    if (res.status() >= 400) failed.push(`${res.url()} HTTP ${res.status()}`);
  });
  await page.goto(server.url + file, { waitUntil: 'load' });
  if (waitReady) {
    await page.waitForFunction(() => window.__IV_BOOT && window.__IV_BOOT.status !== 'loading', null, { timeout: 90_000 });
    const boot = await page.evaluate(() => window.__IV_BOOT);
    if (boot.status !== 'ready') throw new Error(`Game failed to boot: ${JSON.stringify(boot)}; errors: ${errors.join(' | ')}`);
  }
  return {
    page,
    browser,
    server,
    errors,
    warnings,
    failed,
    requests,
    close: async () => {
      await browser.close();
      await server.close();
    },
  };
}

/** Puts the game into a deterministic test mode: playing, loop frozen, no auto rendering. */
export async function enterTestMode(page, { render = false } = {}) {
  await page.evaluate((render) => {
    const iv = window.__IV;
    iv.startGame();
    iv.pause();
    iv.setRenderOnStep(render);
    iv.setSetting('adaptiveResolution', false);
    iv.setSetting('renderScale', 1);
  }, render);
}

/**
 * Screenshot of the page. SwiftShader renders asynchronously and a frame with the full
 * view model can take over a second, so the capture may need to wait for queued GPU work:
 * the tool timeout is generous (this does not relax any pass criterion).
 */
export async function screenshot(page, name) {
  const file = path.join(SCREENS, name);
  const buf = await page.screenshot({ path: file, type: 'png', timeout: 180_000 });
  return { file, buf };
}

// ------------------------------------------------------------------ PNG decoding

function paeth(a, b, c) {
  const p = a + b - c;
  const pa = Math.abs(p - a);
  const pb = Math.abs(p - b);
  const pc = Math.abs(p - c);
  if (pa <= pb && pa <= pc) return a;
  if (pb <= pc) return b;
  return c;
}

/** Minimal PNG decoder (8-bit RGB/RGBA/Gray, non-interlaced) -> {width, height, channels, data}. */
export function decodePng(buf) {
  const sig = [137, 80, 78, 71, 13, 10, 26, 10];
  for (let i = 0; i < 8; i++) if (buf[i] !== sig[i]) throw new Error('not a PNG');
  let off = 8;
  let width = 0;
  let height = 0;
  let bitDepth = 0;
  let colorType = 0;
  let interlace = 0;
  const idat = [];
  while (off < buf.length) {
    const len = buf.readUInt32BE(off);
    const type = buf.toString('ascii', off + 4, off + 8);
    const data = buf.subarray(off + 8, off + 8 + len);
    if (type === 'IHDR') {
      width = data.readUInt32BE(0);
      height = data.readUInt32BE(4);
      bitDepth = data[8];
      colorType = data[9];
      interlace = data[12];
    } else if (type === 'IDAT') idat.push(data);
    else if (type === 'IEND') break;
    off += 12 + len;
  }
  if (bitDepth !== 8 || interlace !== 0) throw new Error(`unsupported PNG (depth ${bitDepth}, interlace ${interlace})`);
  const channels = { 0: 1, 2: 3, 4: 2, 6: 4 }[colorType];
  if (!channels) throw new Error(`unsupported color type ${colorType}`);
  const raw = zlib.inflateSync(Buffer.concat(idat));
  const stride = width * channels;
  const out = Buffer.alloc(height * stride);
  let p = 0;
  for (let y = 0; y < height; y++) {
    const filter = raw[p++];
    for (let x = 0; x < stride; x++) {
      const cur = raw[p++];
      const a = x >= channels ? out[y * stride + x - channels] : 0;
      const b = y > 0 ? out[(y - 1) * stride + x] : 0;
      const c = x >= channels && y > 0 ? out[(y - 1) * stride + x - channels] : 0;
      let v;
      switch (filter) {
        case 0:
          v = cur;
          break;
        case 1:
          v = cur + a;
          break;
        case 2:
          v = cur + b;
          break;
        case 3:
          v = cur + ((a + b) >> 1);
          break;
        case 4:
          v = cur + paeth(a, b, c);
          break;
        default:
          throw new Error(`bad filter ${filter}`);
      }
      out[y * stride + x] = v & 0xff;
    }
  }
  return { width, height, channels, data: out };
}

/** Luminance statistics of an image region (defaults to full image). */
export function imageStats(img, region = null) {
  const { width, height, channels, data } = img;
  const x0 = region ? region.x : 0;
  const y0 = region ? region.y : 0;
  const x1 = region ? region.x + region.w : width;
  const y1 = region ? region.y + region.h : height;
  let sum = 0;
  let sumSq = 0;
  let n = 0;
  let nonBlack = 0;
  const hist = new Uint32Array(32);
  const colors = new Set();
  for (let y = y0; y < y1; y++) {
    for (let x = x0; x < x1; x++) {
      const i = (y * width + x) * channels;
      const r = data[i];
      const g = channels >= 3 ? data[i + 1] : r;
      const b = channels >= 3 ? data[i + 2] : r;
      const l = 0.2126 * r + 0.7152 * g + 0.0722 * b;
      sum += l;
      sumSq += l * l;
      n++;
      if (l > 12) nonBlack++;
      hist[Math.min(31, l >> 3)]++;
      if (colors.size < 5000) colors.add((r >> 3) | ((g >> 3) << 5) | ((b >> 3) << 10));
    }
  }
  const mean = sum / n;
  const std = Math.sqrt(Math.max(0, sumSq / n - mean * mean));
  const usedBins = hist.filter((h) => h > n * 0.002).length;
  return { mean, std, nonBlackRatio: nonBlack / n, usedBins, distinctColors: colors.size, pixels: n };
}
