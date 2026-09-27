// Instanced grass and meadow flowers around the camera (map art pass phase 1; R09 grass clumps, R17 yarrow /
// chamomile). Visual only: grass is not part of the collision world, so it never blocks AI sight, bullets or
// movement (Docs/GAMEPLAY_CONTRACTS.md, Docs/AI.md) -- tall grass therefore stays sparse and patchy (the density map
// of Tools/level/export_web_level.py keeps it out of capture zones and 3 m around lanes).
//
//  - density map: 0.5 m RGB image in kh_terrain.glb (R low clumps + forbs, G tall grass, B flowers); zero on roads,
//    paths, tracks (+0.3 m), yards (except along walls), water, bridges, props and building footprints;
//  - 8 m cells within 40 m of the camera are scattered deterministically (hash seed per cell), heights from the
//    terrain grid; 5 clump types = 5 draw calls (crossed alpha cards from the grass atlas of vegetation.glb);
//  - distance fade (clumps sink into the ground: low grass 20-30 m, tall grass / flowers up to 40 m), wind sway;
//  - lit like the ground: up-facing normals, the terrain's macro tint and baked sky visibility at the clump base,
//    darker base (occlusion), shadows received (not cast).
// Browser only.

import {
  DataTexture,
  DoubleSide,
  Float32BufferAttribute,
  InstancedBufferAttribute,
  InstancedBufferGeometry,
  LinearFilter,
  Mesh,
  MeshStandardMaterial,
  RedFormat,
  UnsignedByteType,
  Vector4,
} from 'three';
import { imagePixels } from './terrainMaterial.js';
import { readAccessor } from './levelAssets.js';

const CELL = 8;
const RADIUS = 40;

// clump types: atlas rects (variants side by side), card aspect, number of crossed quads, density per m2 at map 1.0
export const GRASS_TYPES = [
  { name: 'low', rects: ['low', 'low_dry'], quads: 3, aspect: 1.35, channel: 0, perM2: 5.0, h: [0.18, 0.55], hPow: 1.6, dryShare: 0.22, radius: 30, fade: [20, 30] },
  { name: 'forb', rects: ['forb', 'forb'], quads: 2, aspect: 1.0, channel: 0, perM2: 0.3, h: [0.25, 0.45], notFlower: true, radius: 34, fade: [24, 34] },
  { name: 'tall', rects: ['tall_a', 'tall_b'], quads: 2, aspect: 0.6, channel: 1, perM2: 0.6, h: [0.75, 1.05], radius: 40, fade: [28, 40] },
  { name: 'chamomile', rects: ['chamomile', 'chamomile'], quads: 2, aspect: 1.0, channel: 2, perM2: 0.35, h: [0.4, 0.58], radius: 36, fade: [26, 36] },
  { name: 'yarrow', rects: ['yarrow', 'yarrow'], quads: 2, aspect: 0.55, channel: 2, perM2: 0.12, h: [0.55, 0.8], radius: 40, fade: [28, 40] },
];

/** Terrain height grid (0.5 m) and baked sky visibility from the terrain tiles of kh_terrain.glb. */
export function terrainGrid(terGlb) {
  const tiles = [];
  let x0 = Infinity;
  let z0 = Infinity;
  let x1 = -Infinity;
  let z1 = -Infinity;
  for (const node of terGlb.json.nodes || []) {
    const iv = node.extras && node.extras.iv;
    if (!iv || iv.collision !== 'terrain' || node.mesh === undefined) continue;
    const prim = terGlb.json.meshes[node.mesh].primitives[0];
    const pos = readAccessor(terGlb, prim.attributes.POSITION);
    const light = prim.attributes._IVLIGHT !== undefined ? readAccessor(terGlb, prim.attributes._IVLIGHT) : null;
    tiles.push({ pos, light });
    for (let i = 0; i < pos.length; i += 3) {
      x0 = Math.min(x0, pos[i]);
      x1 = Math.max(x1, pos[i]);
      z0 = Math.min(z0, pos[i + 2]);
      z1 = Math.max(z1, pos[i + 2]);
    }
  }
  const res = 0.5;
  const nx = Math.round((x1 - x0) / res) + 1;
  const nz = Math.round((z1 - z0) / res) + 1;
  const h = new Float32Array(nx * nz).fill(NaN);
  const sky = new Uint8Array(nx * nz).fill(255);
  for (const t of tiles) {
    for (let i = 0, v = 0; i < t.pos.length; i += 3, v++) {
      const ix = Math.round((t.pos[i] - x0) / res);
      const iz = Math.round((t.pos[i + 2] - z0) / res);
      h[iz * nx + ix] = t.pos[i + 1];
      if (t.light) sky[iz * nx + ix] = t.light[v * 4 + 3];
    }
  }
  return {
    x0,
    z0,
    res,
    nx,
    nz,
    h,
    sky,
    heightAt(x, z) {
      const fx = (x - x0) / res;
      const fz = (z - z0) / res;
      const i = Math.floor(fx);
      const j = Math.floor(fz);
      if (i < 0 || j < 0 || i >= nx - 1 || j >= nz - 1) return NaN;
      const u = fx - i;
      const w = fz - j;
      const a = h[j * nx + i];
      const b = h[j * nx + i + 1];
      const c = h[(j + 1) * nx + i];
      const d = h[(j + 1) * nx + i + 1];
      return (a * (1 - u) + b * u) * (1 - w) + (c * (1 - u) + d * u) * w;
    },
  };
}

function clumpGeometry(type, rects, atlasSize) {
  const P = [];
  const UV = [];
  const B = [];
  const I = [];
  const [W, H] = atlasSize;
  const [x, y, w, h] = rects[type.rects[0]];
  const u0 = x / W;
  const u1 = (x + w) / W;
  const v0 = y / H;
  const v1 = (y + h) / H;
  const hw = type.aspect * 0.5;
  for (let q = 0; q < type.quads; q++) {
    const a = (q / type.quads) * Math.PI;
    const cx = Math.cos(a) * hw;
    const cz = Math.sin(a) * hw;
    const base = P.length / 3;
    P.push(-cx, 0, -cz, cx, 0, cz, cx, 1, cz, -cx, 1, -cz);
    UV.push(u0, v1, u1, v1, u1, v0, u0, v0);
    B.push(0, 0, 1, 1);
    I.push(base, base + 1, base + 2, base, base + 2, base + 3);
  }
  const g = new InstancedBufferGeometry();
  g.setAttribute('position', new Float32BufferAttribute(P, 3));
  g.setAttribute('uv', new Float32BufferAttribute(UV, 2));
  g.setAttribute('ivBend', new Float32BufferAttribute(B, 1));
  g.setIndex(I);
  // uv offset of the second variant (same row of the atlas)
  const [x2] = rects[type.rects[1]];
  g.userData.uvStep = (x2 - x) / W;
  g.userData.tris = I.length / 3;
  return g;
}

function grassMaterial(tex, uniforms, splatTex, groundSky, grid, splat, uvStep, fade) {
  const m = new MeshStandardMaterial({ color: 0xffffff, roughness: 0.9, metalness: 0, side: DoubleSide, alphaTest: 0.5 });
  m.alphaToCoverage = true;
  const [rx0, ry0, rx1, ry1] = splat.rect;
  const u = {
    ivGrassTex: { value: tex },
    ivMacro: { value: splatTex },
    ivGroundSky: { value: groundSky },
    ivSplatRect: { value: new Vector4(rx0, ry1, rx1 - rx0, ry1 - ry0) },
    ivGridRect: { value: new Vector4(grid.x0, grid.z0, (grid.nx - 1) * grid.res, (grid.nz - 1) * grid.res) },
    ivUvStep: { value: uvStep },
    ivFade: { value: fade },
  };
  m.onBeforeCompile = (shader) => {
    Object.assign(shader.uniforms, uniforms, u);
    shader.vertexShader = shader.vertexShader
      .replace(
        '#include <common>',
        `#include <common>
attribute vec4 ivPos;
attribute vec4 ivScl;
attribute float ivBend;
uniform float ivTime;
uniform vec3 ivWindDir;
uniform float ivWindStrength;
uniform float ivUvStep;
uniform vec2 ivFade;
varying vec2 vIvUv;
varying float vIvBend;
varying float vIvTint;
varying vec2 vIvXZ;`,
      )
      .replace('#include <beginnormal_vertex>', 'vec3 objectNormal = vec3( 0.0, 1.0, 0.0 );')
      .replace(
        '#include <begin_vertex>',
        `vec3 transformed;
{
	vec3 camW = cameraPosition;
	float d = distance( ivPos.xz, camW.xz );
	float jit = fract( ivScl.w * 13.13 ) * 5.0;   // per-clump offset: no visible ring where the grass sinks in
	float f = 1.0 - smoothstep( ivFade.x - jit, ivFade.y - jit * 0.6, d );
	vec3 p = position;
	p.y *= ivScl.x * f;
	p.xz *= ivScl.y * ( 0.6 + 0.4 * f );
	float c = cos( ivPos.w ), s = sin( ivPos.w );
	p.xz = vec2( c * p.x - s * p.z, s * p.x + c * p.z );
	float ph = dot( ivPos.xz, vec2( 0.37, 0.29 ) );
	float gust = 0.55 + 0.45 * sin( ivTime * 0.45 + ivPos.x * 0.05 + ivPos.z * 0.04 );
	float sway = ( sin( ivTime * 1.9 + ph ) * 0.7 + sin( ivTime * 3.7 + ph * 2.3 ) * 0.3 ) * gust * ivWindStrength;
	p.xz += ivWindDir.xz * ivBend * ivBend * ivScl.x * 0.16 * sway;
	transformed = p + ivPos.xyz;
	vIvUv = uv + vec2( ivScl.z * ivUvStep, 0.0 );
	vIvBend = ivBend;
	vIvTint = ivScl.w;
	vIvXZ = ivPos.xz;
}`,
      );
    shader.fragmentShader = shader.fragmentShader
      .replace(
        '#include <common>',
        `#include <common>
uniform sampler2D ivGrassTex;
uniform sampler2D ivMacro;
uniform sampler2D ivGroundSky;
uniform vec4 ivSplatRect;
uniform vec4 ivGridRect;
varying vec2 vIvUv;
varying float vIvBend;
varying float vIvTint;
varying vec2 vIvXZ;`,
      )
      .replace(
        '#include <map_fragment>',
        `{
	vec4 tx = texture2D( ivGrassTex, vIvUv );
	// coverage-preserving alpha: thin blades must not vanish in the lower mips
	vec2 duv = fwidth( vIvUv ) * vec2( 1024.0, 768.0 );
	tx.a *= 1.0 + max( 0.0, log2( max( duv.x, duv.y ) ) ) * 0.6;
	diffuseColor *= tx;
	vec2 uvW = vec2( ( vIvXZ.x - ivSplatRect.x ) / ivSplatRect.z, ( vIvXZ.y + ivSplatRect.y ) / ivSplatRect.w );
	vec3 macro = texture2D( ivMacro, uvW ).rgb * 2.0;
	vec3 hue = mix( vec3( 0.92, 1.02, 0.9 ), vec3( 1.1, 1.03, 0.82 ), vIvTint );
	diffuseColor.rgb *= macro * hue * ( 0.86 + 0.26 * fract( vIvTint * 7.13 ) ) * mix( 0.72, 1.0, smoothstep( 0.0, 0.6, vIvBend ) );
}`,
      )
      .replace(
        '#include <aomap_fragment>',
        `#include <aomap_fragment>
{
	vec2 g = ( vIvXZ - ivGridRect.xy ) / ivGridRect.zw;
	float sky = texture2D( ivGroundSky, g ).r;
	reflectedLight.indirectDiffuse *= mix( 0.35, 1.0, sky ) * mix( 0.8, 1.0, vIvBend );
	reflectedLight.indirectSpecular *= 0.5;
}`,
      );
  };
  m.customProgramCacheKey = () => 'iv-grass-1';
  return m;
}

/**
 * @param {object} o { terrainSplat (loadTerrainSplat), terGlb (parseGlb), vegGlb (parseGlb of vegetation.glb),
 *                     textures (loadVegetationTextures), uniforms (createVegetationUniforms) }
 */
export function buildGrass({ terrainSplat, terGlb, vegGlb, textures, uniforms }) {
  const splat = terrainSplat.splat;
  const px = imagePixels(terrainSplat.grassBitmap);
  const gw = terrainSplat.grassBitmap.width;
  const gh = terrainSplat.grassBitmap.height;
  const gres = splat.grassRes;
  const [rx0, , , ry1] = splat.rect;
  const grid = terrainGrid(terGlb);
  const skyTex = new DataTexture(grid.sky, grid.nx, grid.nz, RedFormat, UnsignedByteType);
  skyTex.magFilter = LinearFilter;
  skyTex.minFilter = LinearFilter;
  skyTex.unpackAlignment = 1;
  skyTex.needsUpdate = true;
  const atlas = vegGlb.json.asset.extras.iv.grassAtlas;
  /** density (0..1) of channel ch at world (x, z), bilinear over the 0.5 m map (row 0 = north = most negative z). */
  const density = (x, z, ch) => {
    const fx = (x - rx0) / gres - 0.5;
    const fy = (z + ry1) / gres - 0.5;
    const i = Math.floor(fx);
    const j = Math.floor(fy);
    if (i < 0 || j < 0 || i >= gw - 1 || j >= gh - 1) return 0;
    const u = fx - i;
    const v = fy - j;
    const o = (j * gw + i) * 4 + ch;
    const a = px[o];
    const b = px[o + 4];
    const c = px[o + gw * 4];
    const d = px[o + gw * 4 + 4];
    return ((a * (1 - u) + b * u) * (1 - v) + (c * (1 - u) + d * u) * v) / 255;
  };
  const group = [];
  const types = GRASS_TYPES.map((t) => {
    const geo = clumpGeometry(t, atlas.rects, atlas.size);
    const mat = grassMaterial(textures.grass, uniforms, terrainSplat.macro, skyTex, grid, splat, geo.userData.uvStep, t.fade);
    const mesh = new Mesh(geo, mat);
    mesh.name = `grass_${t.name}`;
    mesh.frustumCulled = false;
    mesh.castShadow = false;
    mesh.receiveShadow = true;
    geo.instanceCount = 0;
    group.push(mesh);
    return { ...t, geo, mesh, mat, cap: 0 };
  });
  const cells = new Map(); // key -> [Float32Array per type (8 floats per instance)]
  function genCell(ci, cj) {
    let s = (Math.imul(ci, 73856093) ^ Math.imul(cj, 19349663) ^ 0x5bd1e995) >>> 0;
    const rnd = () => {
      s = (Math.imul(s, 1664525) + 1013904223) >>> 0;
      return s / 4294967296;
    };
    const out = [];
    for (const t of types) {
      const n = Math.round(CELL * CELL * t.perM2);
      const arr = [];
      for (let k = 0; k < n; k++) {
        const x = ci * CELL + rnd() * CELL;
        const z = cj * CELL + rnd() * CELL;
        const r1 = rnd();
        const r2 = rnd();
        const r3 = rnd();
        const r4 = rnd();
        let dens = density(x, z, t.channel);
        if (t.notFlower) dens *= 1 - density(x, z, 2) * 0.6;
        if (r1 >= dens) continue;
        const y = grid.heightAt(x, z);
        if (!(y === y)) continue; // NaN: no terrain (building floors)
        const hgt = t.h[0] + (t.h[1] - t.h[0]) * Math.pow(r2, t.hPow || 1);
        const variant = t.dryShare !== undefined ? (r3 < t.dryShare ? 1 : 0) : r3 < 0.5 ? 1 : 0;
        arr.push(x, y - 0.03, z, r4 * 6.2832, hgt, hgt * (0.85 + 0.5 * r2), variant, rnd());
      }
      out.push(new Float32Array(arr));
    }
    return out;
  }
  const state = { cx: 1e9, cz: 1e9, counts: types.map(() => 0), cells: 0, triangles: 0 };
  function rebuild(cx, cz) {
    const need = [];
    const r = Math.ceil(RADIUS / CELL);
    const ci0 = Math.floor(cx / CELL);
    const cj0 = Math.floor(cz / CELL);
    for (let dj = -r; dj <= r; dj++) {
      for (let di = -r; di <= r; di++) {
        const ci = ci0 + di;
        const cj = cj0 + dj;
        const mx = Math.max(Math.abs(ci * CELL + CELL / 2 - cx) - CELL / 2, 0);
        const mz = Math.max(Math.abs(cj * CELL + CELL / 2 - cz) - CELL / 2, 0);
        if (mx * mx + mz * mz > RADIUS * RADIUS) continue;
        const key = `${ci},${cj}`;
        if (!cells.has(key)) cells.set(key, genCell(ci, cj));
        need.push({ key, d2: mx * mx + mz * mz });
      }
    }
    // drop far cells from the cache (keep it bounded)
    if (cells.size > need.length * 3) {
      const keep = new Set(need.map((n) => n.key));
      for (const k of cells.keys()) if (!keep.has(k)) cells.delete(k);
    }
    state.triangles = 0;
    types.forEach((t, ti) => {
      const mine = need.filter((n) => n.d2 <= t.radius * t.radius).map((n) => n.key);
      let total = 0;
      for (const k of mine) total += cells.get(k)[ti].length / 8;
      const data = new Float32Array(Math.max(total, 1) * 8);
      let o = 0;
      for (const k of mine) {
        const a = cells.get(k)[ti];
        data.set(a, o);
        o += a.length;
      }
      // fixed-capacity instance buffers updated in place (three caches the maximum instance count of an
      // InstancedBufferGeometry from its first attribute arrays: replacing them with larger ones would truncate)
      if (!t.posAttr || t.posAttr.count < total) {
        const cap = Math.ceil(Math.max(total, 64) * 1.3);
        t.posAttr = new InstancedBufferAttribute(new Float32Array(cap * 4), 4);
        t.sclAttr = new InstancedBufferAttribute(new Float32Array(cap * 4), 4);
        t.posAttr.setUsage(35048); // DynamicDrawUsage
        t.sclAttr.setUsage(35048);
        t.geo.setAttribute('ivPos', t.posAttr);
        t.geo.setAttribute('ivScl', t.sclAttr);
        delete t.geo._maxInstanceCount;
      }
      const posArr = t.posAttr.array;
      const sclArr = t.sclAttr.array;
      for (let i = 0; i < total; i++) {
        posArr.set(data.subarray(i * 8, i * 8 + 4), i * 4);
        sclArr.set(data.subarray(i * 8 + 4, i * 8 + 8), i * 4);
      }
      t.posAttr.needsUpdate = true;
      t.sclAttr.needsUpdate = true;
      t.geo.instanceCount = total;
      t.mesh.visible = total > 0;
      state.counts[ti] = total;
      state.triangles += total * t.geo.userData.tris;
    });
    state.cells = need.length;
  }
  function update(camera, force = false) {
    const cx = camera.position.x;
    const cz = camera.position.z;
    if (!force && Math.hypot(cx - state.cx, cz - state.cz) < CELL * 0.5) return false;
    state.cx = cx;
    state.cz = cz;
    rebuild(cx, cz);
    return true;
  }
  /** instance positions of the current scatter (tests): [{ type, x, y, z, h }] */
  function debugInstances() {
    const out = [];
    types.forEach((t) => {
      const p = t.geo.getAttribute('ivPos');
      const sc = t.geo.getAttribute('ivScl');
      if (!p) return;
      for (let i = 0; i < t.geo.instanceCount; i++) out.push({ type: t.name, x: p.getX(i), y: p.getY(i), z: p.getZ(i), h: sc.getX(i) });
    });
    return out;
  }
  return { meshes: group, update, state, debugInstances, density, grid, types: types.map((t) => t.name), radius: RADIUS };
}
