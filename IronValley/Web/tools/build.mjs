#!/usr/bin/env node
// Build: bundles src/main.js into dist/game.js (single IIFE, no eval / new Function, no
// WebAssembly), copies public/ into dist/, and writes two HTML entry points:
//   dist/index.html     complete document for local serving
//   dist/artifact.html  same page body without <!doctype>/<html>/<head>/<body>, for hosts
//                       that wrap the page in their own skeleton (claude.ai Artifact)
// Both reference game.js and assets with relative URLs.
// It also writes dist-artifact/, a self-contained copy for the claude.ai Artifact host, which
// refuses binary model files: every .glb (and every image and font under assets/, e.g. the optic reticle SDFs, the
// 6x overlay and the title-menu fonts) becomes <name>.b64.txt (base64 text) and the bundle there is built with that asset list
// (src/engine/assets.js decodes it). Publish dist-artifact/iron-valley.html together with every other file in
// dist-artifact/. The web variants of the Blender exports (WebP / JPEG textures) are made by
// ../Tools/web_assets/build_web_assets.py (npm run assets:web); a stale manifest is reported here.

import { build } from 'esbuild';
import { cp, mkdir, readdir, readFile, rm, stat, writeFile } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const webRoot = path.resolve(here, '..');
const dist = path.join(webRoot, 'dist');
const distArtifact = path.join(webRoot, 'dist-artifact');
const publicDir = path.join(webRoot, 'public');
const dev = process.argv.includes('--dev');

async function listFiles(dir, base = dir) {
  if (!existsSync(dir)) return [];
  const out = [];
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...(await listFiles(full, base)));
    else if (!entry.name.startsWith('.')) out.push(path.relative(base, full).split(path.sep).join('/'));
  }
  return out;
}

/**
 * Warns when the web asset variants are older than their sources (Tools/web_assets/build_web_assets.py writes
 * public/assets/web_assets_manifest.json with the size and SHA-256 of every source it read).
 */
async function checkWebAssets() {
  const manifestPath = path.join(publicDir, 'assets', 'web_assets_manifest.json');
  if (!existsSync(manifestPath)) {
    console.warn('warning: public/assets/web_assets_manifest.json missing - run "npm run assets:web"');
    return;
  }
  const { createHash } = await import('node:crypto');
  const m = JSON.parse(await readFile(manifestPath, 'utf8'));
  const repo = path.resolve(webRoot, '..');
  const stale = [];
  for (const s of m.sources || []) {
    const f = path.join(repo, s.path);
    if (!existsSync(f)) continue; // sources are optional in a web-only checkout
    const st = await stat(f);
    if (st.size !== s.bytes) {
      stale.push(s.path);
      continue;
    }
    const h = createHash('sha256').update(await readFile(f)).digest('hex');
    if (h !== s.sha256) stale.push(s.path);
  }
  if (stale.length) console.warn(`warning: web assets are stale (sources changed: ${stale.join(', ')}) - run "npm run assets:web"`);
}

async function main() {
  const t0 = Date.now();
  await rm(dist, { recursive: true, force: true });
  await mkdir(dist, { recursive: true });

  await checkWebAssets();
  const publicFiles = await listFiles(publicDir);
  const assets = publicFiles.filter((f) => f.startsWith('assets/') && !f.endsWith('.gitkeep') && !f.endsWith('README.md'));

  const pkg = JSON.parse(await readFile(path.join(webRoot, 'package.json'), 'utf8'));
  const bundleOptions = (outfile, assetList) => ({
    entryPoints: [path.join(webRoot, 'src/main.js')],
    bundle: true,
    format: 'iife',
    platform: 'browser',
    target: ['es2020', 'chrome100', 'firefox100', 'safari15'],
    outfile,
    minify: !dev,
    sourcemap: dev ? 'linked' : false,
    legalComments: 'none',
    metafile: true,
    define: {
      __IV_ASSETS__: JSON.stringify(assetList),
      __IV_VERSION__: JSON.stringify(pkg.version),
    },
    logLevel: 'warning',
  });
  const result = await build(bundleOptions(path.join(dist, 'game.js'), assets));

  // CSP / runtime guards: no dynamic code evaluation and no WebAssembly in the runtime bundle.
  const js = await readFile(path.join(dist, 'game.js'), 'utf8');
  const forbidden = [
    [/\beval\s*\(/, 'eval('],
    [/new\s+Function\s*\(/, 'new Function('],
    [/\bWebAssembly\b/, 'WebAssembly'],
  ];
  for (const [re, name] of forbidden) {
    if (re.test(js)) throw new Error(`Forbidden construct in bundle: ${name}`);
  }

  if (existsSync(publicDir)) await cp(publicDir, dist, { recursive: true });

  const css = (await readFile(path.join(webRoot, 'src/styles.css'), 'utf8')).trim();
  const body = '<div id="iv-root"></div>\n<script src="game.js"></script>';
  const indexHtml = `<!doctype html>
<html lang="cs">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="IRON VALLEY - zkušební prostor, prohlížečová verze (three.js)">
<title>Iron Valley</title>
<link rel="icon" href="data:,">
<style>
${css}
</style>
</head>
<body>
${body}
</body>
</html>
`;
  const artifactHtml = `<title>Iron Valley</title>
<style>
${css}
</style>
${body}
`;
  await writeFile(path.join(dist, 'index.html'), indexHtml);
  await writeFile(path.join(dist, 'artifact.html'), artifactHtml);

  // Artifact-host variant: .glb -> .glb.b64.txt, bundle built with the renamed asset list.
  await rm(distArtifact, { recursive: true, force: true });
  await mkdir(distArtifact, { recursive: true });
  const b64 = (a) => /\.(glb|png|webp|jpe?g|woff2)$/i.test(a);
  const artifactAssets = assets.map((a) => (b64(a) ? a + '.b64.txt' : a));
  await build(bundleOptions(path.join(distArtifact, 'game.js'), artifactAssets));
  const artifactJs = await readFile(path.join(distArtifact, 'game.js'), 'utf8');
  for (const [re, name] of forbidden) {
    if (re.test(artifactJs)) throw new Error(`Forbidden construct in artifact bundle: ${name}`);
  }
  for (const a of assets) {
    const src = path.join(publicDir, a);
    const dst = path.join(distArtifact, a);
    await mkdir(path.dirname(dst), { recursive: true });
    if (b64(a)) {
      await writeFile(dst + '.b64.txt', (await readFile(src)).toString('base64'));
    } else {
      await cp(src, dst);
    }
  }
  await writeFile(path.join(distArtifact, 'iron-valley.html'), artifactHtml);
  const tooBig = [];
  for (const f of await listFiles(distArtifact)) {
    const bytes = (await stat(path.join(distArtifact, f))).size;
    if (bytes > 15 * 1024 * 1024) tooBig.push(`${f} (${(bytes / 1048576).toFixed(1)} MiB)`);
  }
  if (tooBig.length) console.warn(`warning: files over the artifact host's 15 MiB limit: ${tooBig.join(', ')}`);

  const size = (await stat(path.join(dist, 'game.js'))).size;
  const info = {
    name: pkg.name,
    version: pkg.version,
    builtAt: new Date().toISOString(),
    dependencies: pkg.dependencies,
    esbuild: pkg.devDependencies.esbuild,
    bundleBytes: size,
    assets,
    inputs: Object.keys(result.metafile.inputs).length,
  };
  await writeFile(path.join(dist, 'build-info.json'), JSON.stringify(info, null, 2) + '\n');
  console.log(`build ok: dist/game.js ${(size / 1024).toFixed(0)} KiB, ${assets.length} asset(s), ${Date.now() - t0} ms`);
  for (const a of assets) console.log(`  asset: ${a}`);
}

main().catch((err) => {
  console.error(err && err.message ? err.message : err);
  process.exit(1);
});
