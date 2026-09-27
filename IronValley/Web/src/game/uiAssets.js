// Title-screen fonts and picture (public/assets/ui). Loaded from bytes, never from a URL in CSS: fonts go through
// the FontFace API with an ArrayBuffer source, the picture is decoded with createImageBitmap(Blob) and drawn into a
// canvas. A host page whose Content-Security-Policy has no font-src / img-src for data: (e.g. only
// "default-src 'self'") still shows the menu as designed. On the Artifact host the files come as ".b64.txt"
// twins (fetchAssetBytes). Anything missing just leaves the fallback fonts / dark background; no errors.

import { fetchAssetBytes, hasAsset } from '../engine/assets.js';

const LATIN =
  'U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,U+0308,U+0329,U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD';
const LATIN_EXT =
  'U+0100-02BA,U+02BD-02C5,U+02C7-02CC,U+02CE-02D7,U+02DD-02FF,U+0304,U+0308,U+0329,U+1D00-1DBF,U+1E00-1E9F,U+1EF2-1EFF,U+2020,U+20A0-20AB,U+20AD-20C0,U+2113,U+2C60-2C7F,U+A720-A7FF';

// Barlow Condensed (SIL OFL 1.1, public/assets/ui/fonts/OFL_BarlowCondensed.txt): Black for the logo, SemiBold for the menu
const FONTS = [
  ['IV Display', '900', 'assets/ui/fonts/barlow-condensed-latin-900-normal.woff2', LATIN],
  ['IV Display', '900', 'assets/ui/fonts/barlow-condensed-latin-ext-900-normal.woff2', LATIN_EXT],
  ['IV Menu', '600', 'assets/ui/fonts/barlow-condensed-latin-600-normal.woff2', LATIN],
  ['IV Menu', '600', 'assets/ui/fonts/barlow-condensed-latin-ext-600-normal.woff2', LATIN_EXT],
];
// made by Tools/web_assets/clean_title_art.py from the user's mockup (text removed)
const TITLE_ART = 'assets/ui/title_kalne_hamry.webp';

export const uiAssetState = { fonts: 0, fontErrors: [], titleArt: null };

let fontsPromise = null;
let artPromise = null;

export function loadUiFonts() {
  if (fontsPromise) return fontsPromise;
  if (typeof FontFace !== 'function' || !document.fonts) return (fontsPromise = Promise.resolve(0));
  fontsPromise = Promise.all(
    FONTS.filter(([, , path]) => hasAsset(path)).map(async ([family, weight, path, unicodeRange]) => {
      try {
        const face = new FontFace(family, await fetchAssetBytes(path), { weight, style: 'normal', unicodeRange, display: 'swap' });
        await face.load();
        document.fonts.add(face);
        uiAssetState.fonts++;
      } catch (err) {
        uiAssetState.fontErrors.push(`${path}: ${err && err.message}`);
      }
    }),
  ).then(() => uiAssetState.fonts);
  return fontsPromise;
}

/** Resolves to an ImageBitmap of the title picture, or null when it is missing or cannot be decoded. */
export function loadTitleArt() {
  if (artPromise) return artPromise;
  if (!hasAsset(TITLE_ART) || typeof createImageBitmap !== 'function') return (artPromise = Promise.resolve(null));
  artPromise = fetchAssetBytes(TITLE_ART)
    .then((bytes) => createImageBitmap(new Blob([bytes], { type: 'image/webp' })))
    .then((bitmap) => {
      uiAssetState.titleArt = { width: bitmap.width, height: bitmap.height };
      return bitmap;
    })
    .catch((err) => {
      uiAssetState.titleArt = { error: err && err.message };
      return null;
    });
  return artPromise;
}
