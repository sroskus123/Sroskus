#!/usr/bin/env node
// Build: bundles src/main.js into dist/game.js (single IIFE, no eval / new Function, no
// WebAssembly), copies public/ into dist/, and writes two HTML entry points:
//   dist/index.html     complete document for local serving
//   dist/artifact.html  same page body without <!doctype>/<html>/<head>/<body>, for hosts
//                       that wrap the page in their own skeleton (claude.ai Artifact)
// Both reference game.js and assets with relative URLs.

import { build } from 'esbuild';
import { cp, mkdir, readdir, readFile, rm, stat, writeFile } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const webRoot = path.resolve(here, '..');
const dist = path.join(webRoot, 'dist');
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

async function main() {
  const t0 = Date.now();
  await rm(dist, { recursive: true, force: true });
  await mkdir(dist, { recursive: true });

  const publicFiles = await listFiles(publicDir);
  const assets = publicFiles.filter((f) => f.startsWith('assets/') && !f.endsWith('.gitkeep') && !f.endsWith('README.md'));

  const pkg = JSON.parse(await readFile(path.join(webRoot, 'package.json'), 'utf8'));
  const result = await build({
    entryPoints: [path.join(webRoot, 'src/main.js')],
    bundle: true,
    format: 'iife',
    platform: 'browser',
    target: ['es2020', 'chrome100', 'firefox100', 'safari15'],
    outfile: path.join(dist, 'game.js'),
    minify: !dev,
    sourcemap: dev ? 'linked' : false,
    legalComments: 'none',
    metafile: true,
    define: {
      __IV_ASSETS__: JSON.stringify(assets),
      __IV_VERSION__: JSON.stringify(pkg.version),
    },
    logLevel: 'warning',
  });

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
