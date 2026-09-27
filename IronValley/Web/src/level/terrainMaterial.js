// Terrain splat material of generated levels (decision D13): the terrain keeps its MeshStandardMaterial (so the
// lighting model, shadows, fog and the baked sky visibility / bounce of engine/bakedLightingMaterial.js keep working)
// and gets a fragment patch that blends tiling PBR detail layers:
//
//   layers   WebGL2 texture arrays sliced from the strips of assets/environment/terrain/ (albedo sRGB; normal x/y +
//            blend height; roughness + occlusion), made by Tools/environment/pack_web_environment.py from the
//            source sets in Art/Textures/Environment/Terrain (swap-in: replace the sets, re-pack, no code change)
//   weights  3 RGBA images at 0.25 m in kh_terrain.glb (10 layer weights, puddles, spare), bilinear; the three
//            strongest layers of a pixel are sampled and blended by height (gravel pokes over the asphalt edge,
//            grass grows into the joints of the setts)
//   anti-tiling  every layer is sampled twice at cell-hashed offsets and cross-faded by a low-frequency noise
//            (Quilez "texture repetition" #3), plus the 1 m macro tint image of the level
//   wetness  after-shower state (ART_DIRECTION 1, R-11): asphalt / concrete / setts darker and glossier; puddles fill
//            the lows of the layer height where the puddle channel says (ruts, kerbs, yard low spots); damp banks
//
// Browser only (ImageBitmap / canvas decoding).

import { DataArrayTexture, LinearFilter, LinearMipmapLinearFilter, NoColorSpace, RepeatWrapping, ClampToEdgeWrapping, RGBAFormat, SRGBColorSpace, Texture, UnsignedByteType, Vector4 } from 'three';

/** Decodes image bytes without any URL (CSP-safe), straight alpha, no colour management. */
export async function decodeImage(bytes, mime) {
  const blob = new Blob([bytes], { type: mime });
  return createImageBitmap(blob, { premultiplyAlpha: 'none', colorSpaceConversion: 'none' });
}

/** RGBA pixels of a decoded image (canvas readback). */
export function imagePixels(bitmap) {
  const w = bitmap.width;
  const h = bitmap.height;
  const canvas = typeof OffscreenCanvas !== 'undefined' ? new OffscreenCanvas(w, h) : Object.assign(document.createElement('canvas'), { width: w, height: h });
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  ctx.drawImage(bitmap, 0, 0);
  return ctx.getImageData(0, 0, w, h).data;
}

/**
 * WebGL2 texture array straight from a vertical strip image (layers one below the other): texSubImage3D takes the
 * ImageBitmap as its source and slices it by rows (UNPACK_IMAGE_HEIGHT 0 = layer height), so no canvas readback.
 */
export function arrayTexture(bitmap, layers, srgb, maxAnisotropy = 8) {
  const size = bitmap.width;
  const t = new DataArrayTexture(bitmap, size, size, layers);
  t.format = RGBAFormat;
  t.type = UnsignedByteType;
  t.colorSpace = srgb ? SRGBColorSpace : NoColorSpace;
  t.wrapS = t.wrapT = RepeatWrapping;
  t.minFilter = LinearMipmapLinearFilter;
  t.magFilter = LinearFilter;
  t.generateMipmaps = true;
  t.anisotropy = maxAnisotropy;
  t.needsUpdate = true;
  return t;
}

function imageTexture(bitmap, { mipmaps = true, srgb = false } = {}) {
  const t = new Texture(bitmap);
  t.flipY = false;
  t.colorSpace = srgb ? SRGBColorSpace : NoColorSpace;
  t.wrapS = t.wrapT = ClampToEdgeWrapping;
  t.magFilter = LinearFilter;
  t.minFilter = mipmaps ? LinearMipmapLinearFilter : LinearFilter;
  t.generateMipmaps = mipmaps;
  t.needsUpdate = true;
  return t;
}

/** Bytes of image `index` of a parsed GLB ({ json, bin } from levelAssets.parseGlb). */
export function glbImageBytes(glb, index) {
  const im = glb.json.images[index];
  const v = glb.json.bufferViews[im.bufferView];
  return { bytes: new Uint8Array(glb.bin.buffer, glb.bin.byteOffset + (v.byteOffset || 0), v.byteLength), mime: im.mimeType };
}

/**
 * Loads the terrain layer arrays (manifest JSON + 3 strips) and the splat control images of the terrain GLB.
 * @returns {Promise<object>} { layers, albedo, nh, rao, weights[3], macro, splat, grassBitmap }
 */
export async function loadTerrainSplat(terGlb, fetchBytes, { maxAnisotropy = 8 } = {}) {
  const iv = terGlb.json.asset && terGlb.json.asset.extras && terGlb.json.asset.extras.iv;
  const splat = iv && iv.splat;
  if (!splat) return null;
  const man = JSON.parse(new TextDecoder('utf-8').decode(await fetchBytes(splat.layerManifest)));
  const [a, n, r] = await Promise.all(
    ['albedo', 'nh', 'rao'].map(async (k) => decodeImage(await fetchBytes(man.files[k].path), 'image/jpeg')),
  );
  const imgs = await Promise.all([...splat.weightImages, splat.macroImage, splat.grassImage].map((i) => {
    const { bytes, mime } = glbImageBytes(terGlb, i);
    return decodeImage(bytes, mime);
  }));
  const count = man.count;
  const out = {
    manifest: man,
    splat,
    layers: man.layers,
    albedo: arrayTexture(a, count, true, maxAnisotropy),
    nh: arrayTexture(n, count, false, maxAnisotropy),
    rao: arrayTexture(r, count, false, maxAnisotropy),
    weights: imgs.slice(0, 3).map((b) => imageTexture(b)),
    macro: imageTexture(imgs[3]),
    grassBitmap: imgs[4],
  };
  return out;
}

const MAX_LAYERS = 12;

/**
 * Chains the splat patch after the material's existing onBeforeCompile (baked lighting).
 * @param {import('three').MeshStandardMaterial} material
 * @param {object} ts result of loadTerrainSplat
 * @param {object} o { wet: 0..1 (after-shower state of the hard surfaces), baked: whether ivSkyVis exists }
 */
export function applyTerrainSplat(material, ts, { wet = 1.0 } = {}) {
  const prev = material.onBeforeCompile;
  const { splat, layers } = ts;
  const [x0, y0, x1, y1] = splat.rect;
  const idx = Object.fromEntries(layers.map((l) => [l.name, l.index]));
  const tileInv = new Array(MAX_LAYERS).fill(1);
  for (const l of layers) tileInv[l.index] = 1 / l.tile_m;
  const uniforms = {
    ivLayAlb: { value: ts.albedo },
    ivLayNH: { value: ts.nh },
    ivLayRAO: { value: ts.rao },
    ivW0: { value: ts.weights[0] },
    ivW1: { value: ts.weights[1] },
    ivW2: { value: ts.weights[2] },
    ivMacro: { value: ts.macro },
    ivSplatRect: { value: new Vector4(x0, y1, x1 - x0, y1 - y0) },
    ivTileInv: { value: tileInv },
    ivWetGlobal: { value: wet },
  };
  material.userData.terrainSplat = { uniforms, layers: layers.map((l) => l.name) };
  // after-shower wetness per hard layer (asphalt drains slowest, setts fastest; ART_DIRECTION 1 / 3.1)
  const hardWet = [['Asphalt', 1.0], ['Concrete', 0.75], ['PavingSetts', 0.5]].filter(([n]) => idx[n] !== undefined);
  const porous = ['Dirt', 'Mud', 'Gravel', 'RiverStones'].map((n) => idx[n]);
  material.onBeforeCompile = (shader, renderer) => {
    if (prev) prev(shader, renderer);
    Object.assign(shader.uniforms, uniforms);
    shader.vertexShader = shader.vertexShader
      .replace('#include <common>', '#include <common>\nvarying vec3 vIvWorld;\nvarying vec3 vIvWN;')
      .replace(
        '#include <worldpos_vertex>',
        '#include <worldpos_vertex>\nvIvWorld = ( modelMatrix * vec4( transformed, 1.0 ) ).xyz;\nvIvWN = normalize( mat3( modelMatrix ) * objectNormal );',
      );
    shader.fragmentShader = shader.fragmentShader
      .replace(
        '#include <common>',
        `#include <common>
precision highp sampler2DArray;
uniform sampler2DArray ivLayAlb;
uniform sampler2DArray ivLayNH;
uniform sampler2DArray ivLayRAO;
uniform sampler2D ivW0;
uniform sampler2D ivW1;
uniform sampler2D ivW2;
uniform sampler2D ivMacro;
uniform vec4 ivSplatRect;
uniform float ivTileInv[${MAX_LAYERS}];
uniform float ivWetGlobal;
varying vec3 vIvWorld;
varying vec3 vIvWN;
float ivHash21( vec2 p ) { p = fract( p * vec2( 123.34, 456.21 ) ); p += dot( p, p + 45.32 ); return fract( p.x * p.y ); }
float ivVNoise( vec2 p ) {
	vec2 i = floor( p ); vec2 f = fract( p ); f = f * f * ( 3.0 - 2.0 * f );
	float a = ivHash21( i ), b = ivHash21( i + vec2( 1.0, 0.0 ) ), c = ivHash21( i + vec2( 0.0, 1.0 ) ), d = ivHash21( i + vec2( 1.0, 1.0 ) );
	return mix( mix( a, b, f.x ), mix( c, d, f.x ), f.y );
}
// one layer, anti-tiled: two samples at cell-hashed offsets, cross-faded by low-frequency noise (same uv for all maps)
void ivLayer( float layer, vec2 uv, float k, out vec4 alb, out vec4 nh, out vec4 rao ) {
	vec2 dx = dFdx( uv ), dy = dFdy( uv );
	float l = k * 8.0; float ia = floor( l ); float f = fract( l );
	vec2 oa = sin( vec2( 3.0, 7.0 ) * ( ia + layer * 1.7 ) ) * 17.0;
	vec2 ob = sin( vec2( 3.0, 7.0 ) * ( ia + 1.0 + layer * 1.7 ) ) * 17.0;
	vec4 a1 = textureGrad( ivLayAlb, vec3( uv + oa, layer ), dx, dy );
	vec4 a2 = textureGrad( ivLayAlb, vec3( uv + ob, layer ), dx, dy );
	vec4 n1 = textureGrad( ivLayNH, vec3( uv + oa, layer ), dx, dy );
	vec4 n2 = textureGrad( ivLayNH, vec3( uv + ob, layer ), dx, dy );
	vec4 r1 = textureGrad( ivLayRAO, vec3( uv + oa, layer ), dx, dy );
	vec4 r2 = textureGrad( ivLayRAO, vec3( uv + ob, layer ), dx, dy );
	float t = smoothstep( 0.2, 0.8, f + ( n1.b - n2.b ) * 0.6 );
	alb = mix( a1, a2, t ); nh = mix( n1, n2, t ); rao = mix( r1, r2, t );
}`,
      )
      .replace(
        '#include <map_fragment>',
        `#include <map_fragment>
vec3 ivN = vec3( 0.0, 1.0, 0.0 );
float ivRough = 0.9;
float ivDetailAO = 1.0;
float ivPud = 0.0;
{
	vec2 uvW = vec2( ( vIvWorld.x - ivSplatRect.x ) / ivSplatRect.z, ( vIvWorld.z + ivSplatRect.y ) / ivSplatRect.w );
	// wobble the weight lookup a little (breaks the 0.25 m texel grid of the transitions)
	vec2 wob = ( vec2( ivVNoise( vIvWorld.xz * 2.3 ), ivVNoise( vIvWorld.xz * 2.3 + 17.0 ) ) - 0.5 ) * ( 0.35 / ( ivSplatRect.z * 4.0 ) );
	vec4 wa = texture2D( ivW0, uvW + wob );
	vec4 wb = texture2D( ivW1, uvW + wob );
	vec4 wc = texture2D( ivW2, uvW + wob );
	float w[${MAX_LAYERS}];
	w[0] = wa.r; w[1] = wa.g; w[2] = wa.b; w[3] = wa.a; w[4] = wb.r; w[5] = wb.g; w[6] = wb.b; w[7] = wb.a; w[8] = wc.r; w[9] = wc.g; w[10] = 0.0; w[11] = 0.0;
	float puddleCh = wc.b;
	int i0 = 0; int i1 = 0; int i2 = 0; float w0 = -1.0; float w1 = -1.0; float w2 = -1.0;
	for ( int i = 0; i < ${layers.length}; i ++ ) {
		float v = w[ i ];
		if ( v > w0 ) { w2 = w1; i2 = i1; w1 = w0; i1 = i0; w0 = v; i0 = i; }
		else if ( v > w1 ) { w2 = w1; i2 = i1; w1 = v; i1 = i; }
		else if ( v > w2 ) { w2 = v; i2 = i; }
	}
	float k = ivVNoise( vIvWorld.xz * 0.11 );
	vec2 xz = vIvWorld.xz;
	vec4 A0, N0, R0, A1, N1, R1, A2, N2, R2;
	ivLayer( float( i0 ), xz * ivTileInv[ i0 ], k, A0, N0, R0 );
	A1 = A0; N1 = N0; R1 = R0; A2 = A0; N2 = N0; R2 = R0;
	if ( w1 > 0.02 ) ivLayer( float( i1 ), xz * ivTileInv[ i1 ], k, A1, N1, R1 ); else w1 = 0.0;
	if ( w2 > 0.02 ) ivLayer( float( i2 ), xz * ivTileInv[ i2 ], k, A2, N2, R2 ); else w2 = 0.0;
	// height blend
	float depth = 0.12;
	float s0 = N0.b + w0 * 1.1; float s1 = N1.b + w1 * 1.1; float s2 = N2.b + w2 * 1.1;
	float ma = max( s0, max( s1 * step( 0.001, w1 ), s2 * step( 0.001, w2 ) ) ) - depth;
	float b0 = max( s0 - ma, 0.0 ); float b1 = max( s1 - ma, 0.0 ) * step( 0.001, w1 ); float b2 = max( s2 - ma, 0.0 ) * step( 0.001, w2 );
	float bs = max( b0 + b1 + b2, 1e-4 ); b0 /= bs; b1 /= bs; b2 /= bs;
	vec3 alb = A0.rgb * b0 + A1.rgb * b1 + A2.rgb * b2;
	vec4 nh = N0 * b0 + N1 * b1 + N2 * b2;
	vec4 rao = R0 * b0 + R1 * b1 + R2 * b2;
	float h = nh.b;
	// macro variation (1 m tint image, multiplier * 0.5)
	alb *= texture2D( ivMacro, uvW ).rgb * 2.0;
	// wetness: hard surfaces wet after the shower; puddles fill the lows; porous layers darken more
	float hardW = ${hardWet.map(([n, k]) => `w[${idx[n]}] * ${k.toFixed(2)}`).join(' + ')};
	float hardAll = ${hardWet.map(([n]) => `w[${idx[n]}]`).join(' + ')};
	float porW = ${porous.map((i) => `w[${i}]`).join(' + ')};
	float level = puddleCh * 0.8;
	float pud = smoothstep( 0.0, 0.05, level - h ) * step( 0.02, puddleCh );
	float damp = clamp( ivWetGlobal * hardW + puddleCh * 0.9 * porW, 0.0, 1.0 );
	float wetD = max( damp, pud );
	alb *= mix( 1.0, 0.72 + 0.1 * hardAll, wetD );
	alb = mix( alb, alb * vec3( 0.55, 0.57, 0.6 ), pud );
	float rough = rao.r;
	float wetRough = ( w[${idx.Asphalt}] * 0.34 + w[${idx.Concrete}] * 0.42 + w[${idx.PavingSetts}] * 0.45 ) / max( hardAll, 1e-3 );
	rough = mix( rough, mix( 0.45, wetRough, step( 0.05, hardAll ) ), damp );
	rough = mix( rough, 0.04, pud );
	vec2 nt = ( nh.rg * 2.0 - 1.0 ) * ( 1.0 - pud * 0.92 );
	float nz = sqrt( max( 1.0 - dot( nt, nt ), 0.0 ) );
	// tangent frame of the world-aligned layers: image x -> +X, image up -> -Z, projected on the terrain normal
	vec3 Ng = normalize( vIvWN );
	vec3 T = normalize( cross( Ng, vec3( 0.0, 0.0, 1.0 ) ) );
	vec3 B = cross( Ng, T );
	ivN = normalize( T * nt.x + B * nt.y + Ng * nz );
	ivRough = clamp( rough, 0.03, 1.0 );
	ivDetailAO = mix( rao.g, 1.0, pud );
	ivPud = pud;
	// cavity: a little of the detail occlusion also darkens the direct light (reads at grazing sun)
	diffuseColor.rgb = alb * mix( 1.0, ivDetailAO, 0.35 );
}`,
      )
      .replace('#include <roughnessmap_fragment>', 'float roughnessFactor = ivRough;')
      .replace('#include <normal_fragment_maps>', 'normal = normalize( ( viewMatrix * vec4( ivN, 0.0 ) ).xyz );')
      .replace(
        '#include <aomap_fragment>',
        '#include <aomap_fragment>\nreflectedLight.indirectDiffuse *= ivDetailAO;\nreflectedLight.indirectSpecular *= mix( 1.0, ivDetailAO, 0.6 ) * mix( 1.0, 3.2, ivPud );',
      );
  };
  const prevKey = material.customProgramCacheKey ? material.customProgramCacheKey() : '';
  material.customProgramCacheKey = () => `${prevKey}|iv-terrain-splat-1`;
  material.map = null;
  material.vertexColors = false;
  material.color.setRGB(1, 1, 1);
  material.metalness = 0;
  material.roughness = 1;
  material.needsUpdate = true;
  return material;
}
