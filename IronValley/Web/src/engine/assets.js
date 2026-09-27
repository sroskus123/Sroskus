// Runtime asset access. The build embeds the list of files present in public/assets as
// __IV_ASSETS__, so the game only requests assets that exist (no 404s) and can fall back to
// placeholders otherwise. GLB files must not require Draco / meshopt / KTX2 decoders
// (those need WebAssembly, which this runtime avoids).

import { LinearFilter, LinearMipmapLinearFilter, ClampToEdgeWrapping, Texture } from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';

/* global __IV_ASSETS__ */
const AVAILABLE = new Set(typeof __IV_ASSETS__ !== 'undefined' ? __IV_ASSETS__ : []);

// Hosts that do not serve binary model files (the claude.ai Artifact host refuses .glb) get each
// GLB as "<path>.b64.txt": the same bytes, base64-encoded as plain text (see tools/build.mjs,
// dist-artifact/). The game decodes it itself and hands the ArrayBuffer to GLTFLoader.parse, so no
// blob:/data: URL is ever fetched and a strict connect-src CSP still works.
const B64_SUFFIX = '.b64.txt';

export function hasAsset(path) {
  return AVAILABLE.has(path) || AVAILABLE.has(path + B64_SUFFIX);
}

function base64ToArrayBuffer(text) {
  const clean = text.replace(/\s+/g, '');
  if (typeof Uint8Array.fromBase64 === 'function') return Uint8Array.fromBase64(clean).buffer;
  const bin = atob(clean);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out.buffer;
}

export function listAssets() {
  return [...AVAILABLE];
}

/**
 * GLTFLoader plugin: decodes images embedded in the GLB binary chunk straight from their bytes
 * with createImageBitmap(Blob), without creating blob: URLs.
 *
 * Upstream GLTFLoader turns each embedded image into a blob: URL and loads it with fetch()
 * (ImageBitmapLoader). A host page whose Content-Security-Policy does not list blob: in
 * connect-src (e.g. "connect-src 'self'") refuses those requests and the weapon renders without
 * textures. Decoding the Blob directly needs no URL, so no CSP directive applies. The decode
 * options match ImageBitmapLoader's (premultiplyAlpha 'none', colorSpaceConversion 'none') and
 * the texture is set up exactly like upstream (flipY etc. are applied later by the parser).
 * Images referenced by URI, and browsers where the parser does not use ImageBitmap, keep the
 * upstream path.
 */
export class GLTFEmbeddedImagePlugin {
  constructor(parser) {
    this.name = 'IV_embedded_image_bitmap';
    this.decoded = 0;
    const upstream = parser.loadImageSource.bind(parser);
    parser.loadImageSource = (sourceIndex, loader) => {
      const def = parser.json.images && parser.json.images[sourceIndex];
      if (!def || def.bufferView === undefined || !loader || loader.isImageBitmapLoader !== true || typeof createImageBitmap !== 'function') {
        return upstream(sourceIndex, loader);
      }
      if (parser.sourceCache[sourceIndex] !== undefined) {
        return parser.sourceCache[sourceIndex].then((texture) => texture.clone());
      }
      const options = { ...(loader.options || { premultiplyAlpha: 'none' }), colorSpaceConversion: 'none' };
      const promise = parser
        .getDependency('bufferView', def.bufferView)
        .then((bufferView) => createImageBitmap(new Blob([bufferView], { type: def.mimeType }), options))
        .then((bitmap) => {
          const texture = new Texture(bitmap);
          texture.needsUpdate = true;
          if (def.extras && typeof def.extras === 'object') Object.assign(texture.userData, def.extras);
          texture.userData.mimeType = def.mimeType;
          this.decoded++;
          return texture;
        })
        .catch((error) => {
          console.error('[assets] could not decode embedded GLB image', sourceIndex, error && error.message);
          throw error;
        });
      parser.sourceCache[sourceIndex] = promise;
      return promise;
    };
  }
}

/**
 * Fetches an asset file (or its "<path>.b64.txt" twin on the Artifact host) as bytes.
 * No blob: / data: URL is ever created (strict CSP, see GLTFEmbeddedImagePlugin).
 */
export async function fetchAssetBytes(path) {
  if (!AVAILABLE.has(path) && AVAILABLE.has(path + B64_SUFFIX)) {
    const res = await fetch(path + B64_SUFFIX);
    if (!res.ok) throw new Error(`HTTP ${res.status} for ${path + B64_SUFFIX}`);
    return base64ToArrayBuffer(await res.text());
  }
  const res = await fetch(path);
  if (!res.ok) throw new Error(`HTTP ${res.status} for ${path}`);
  return res.arrayBuffer();
}

const MIME_BY_EXT = { png: 'image/png', webp: 'image/webp', jpg: 'image/jpeg', jpeg: 'image/jpeg' };

/**
 * Loads an image asset (PNG / WebP / JPEG) into a Texture: bytes -> createImageBitmap(Blob), no URL, no
 * vertical flip (row 0 = top at v = 0, like glTF textures). Linear data by default (set colorSpace for
 * colour images). mipmaps: false keeps LinearFilter (distance fields), true = trilinear.
 */
export async function loadTextureAsset(path, { mipmaps = false, colorSpace = null } = {}) {
  const bytes = await fetchAssetBytes(path);
  const ext = path.split('.').pop().toLowerCase();
  const bitmap = await createImageBitmap(new Blob([bytes], { type: MIME_BY_EXT[ext] || 'application/octet-stream' }), {
    premultiplyAlpha: 'none',
    colorSpaceConversion: 'none',
    imageOrientation: 'none',
  });
  const t = new Texture(bitmap);
  t.flipY = false;
  t.wrapS = t.wrapT = ClampToEdgeWrapping;
  t.generateMipmaps = mipmaps;
  t.minFilter = mipmaps ? LinearMipmapLinearFilter : LinearFilter;
  t.magFilter = LinearFilter;
  if (colorSpace) t.colorSpace = colorSpace;
  t.needsUpdate = true;
  t.name = path.split('/').pop();
  return t;
}

let loader = null;
/** Number of embedded images decoded without blob: URLs (for tests / diagnostics). */
export const assetStats = { embeddedImagesDecoded: 0 };

/** Parses GLB bytes already in memory (e.g. fetched once for collision and rendering). */
export function parseGLTF(bytes, path = '') {
  getLoader();
  const base = path.slice(0, path.lastIndexOf('/') + 1);
  return new Promise((resolve, reject) => loader.parse(bytes, base, resolve, (err) => reject(err instanceof Error ? err : new Error(String(err)))));
}

function getLoader() {
  if (!loader) {
    loader = new GLTFLoader();
    loader.register((parser) => {
      const plugin = new GLTFEmbeddedImagePlugin(parser);
      const count = () => {
        assetStats.embeddedImagesDecoded += plugin.decoded;
        plugin.decoded = 0;
      };
      // afterRoot runs once the whole asset (including its textures) is parsed
      plugin.afterRoot = () => {
        count();
        return null;
      };
      return plugin;
    });
  }
  return loader;
}

/** Loads a GLB/GLTF relative to the page. Resolves to the parsed glTF. */
export function loadGLTF(path) {
  getLoader();
  const fail = (reject) => (err) => reject(err instanceof Error ? err : new Error(String(err)));
  if (!AVAILABLE.has(path) && AVAILABLE.has(path + B64_SUFFIX)) {
    const base = path.slice(0, path.lastIndexOf('/') + 1);
    return fetch(path + B64_SUFFIX)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status} for ${path + B64_SUFFIX}`);
        return res.text();
      })
      .then((text) => new Promise((resolve, reject) => loader.parse(base64ToArrayBuffer(text), base, resolve, fail(reject))));
  }
  return new Promise((resolve, reject) => {
    loader.load(path, resolve, undefined, fail(reject));
  });
}
