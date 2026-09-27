// Visual of a generated level (level.geometry, e.g. "Kalné Hamry"): the GLB scenes written by
// Tools/level/export_web_level.py, with the lighting baked at build time.
//
//  - _IVLIGHT (u8 RGBA per vertex: one-bounce sunlight * 2 in RGB, sky visibility in A) becomes the ivSkyVis /
//    ivBounce attributes of engine/bakedLightingMaterial.js, so interiors get less sky light than open ground
//    exactly like the test range, without baking at load time.
//  - Terrain tiles get UVs from the albedo rectangle (asset extras) and a world-space detail layer in the shader.
//  - Shadows: world meshes cast and receive, the terrain receives; glass, water, trees' crowns (cheap) as data says.
// Browser only (textures come decoded from GLTFLoader).

import { BufferAttribute, DataTexture, Group, LinearMipmapLinearFilter, RepeatWrapping, RGBAFormat, UnsignedByteType } from 'three';
import { applyBakedLighting, createBakedLightingUniforms } from '../engine/bakedLightingMaterial.js';

function detailTexture(size = 256) {
  // tiling value noise (two octaves) around 1.0, stored in [0, 255]
  let seed = 12345;
  const rnd = () => {
    seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
    return seed / 4294967296;
  };
  const layer = (cells) => {
    const g = new Float32Array(cells * cells);
    for (let i = 0; i < g.length; i++) g[i] = rnd();
    const out = new Float32Array(size * size);
    for (let y = 0; y < size; y++) {
      for (let x = 0; x < size; x++) {
        const fx = (x / size) * cells;
        const fy = (y / size) * cells;
        const x0 = Math.floor(fx);
        const y0 = Math.floor(fy);
        const tx = fx - x0;
        const ty = fy - y0;
        const sx = tx * tx * (3 - 2 * tx);
        const sy = ty * ty * (3 - 2 * ty);
        const a = g[(y0 % cells) * cells + (x0 % cells)];
        const b = g[(y0 % cells) * cells + ((x0 + 1) % cells)];
        const c = g[((y0 + 1) % cells) * cells + (x0 % cells)];
        const d = g[((y0 + 1) % cells) * cells + ((x0 + 1) % cells)];
        out[y * size + x] = a + (b - a) * sx + (c - a) * sy + (a - b - c + d) * sx * sy;
      }
    }
    return out;
  };
  const l1 = layer(8);
  const l2 = layer(32);
  const l3 = layer(64);
  const data = new Uint8Array(size * size * 4);
  for (let i = 0; i < size * size; i++) {
    const v = 0.5 * l1[i] + 0.3 * l2[i] + 0.2 * l3[i];
    const b = Math.max(0, Math.min(255, Math.round(v * 255)));
    data[i * 4] = b;
    data[i * 4 + 1] = Math.max(0, Math.min(255, Math.round(l3[i] * 255)));
    data[i * 4 + 2] = b;
    data[i * 4 + 3] = 255;
  }
  const t = new DataTexture(data, size, size, RGBAFormat, UnsignedByteType);
  t.wrapS = t.wrapT = RepeatWrapping;
  t.minFilter = LinearMipmapLinearFilter;
  t.generateMipmaps = true;
  t.needsUpdate = true;
  return t;
}

/** Adds a world-space detail modulation to a (baked-lighting) terrain material, chained after its own patch. */
function addTerrainDetail(material, detail) {
  const prev = material.onBeforeCompile;
  material.onBeforeCompile = (shader, renderer) => {
    if (prev) prev(shader, renderer);
    shader.uniforms.ivDetail = { value: detail };
    shader.vertexShader = shader.vertexShader
      .replace('#include <common>', '#include <common>\nvarying vec3 vIvWorld;')
      .replace('#include <worldpos_vertex>', '#include <worldpos_vertex>\nvIvWorld = ( modelMatrix * vec4( transformed, 1.0 ) ).xyz;');
    shader.fragmentShader = shader.fragmentShader
      .replace('#include <common>', '#include <common>\nuniform sampler2D ivDetail;\nvarying vec3 vIvWorld;')
      .replace(
        '#include <map_fragment>',
        `#include <map_fragment>
{
	float d1 = texture2D( ivDetail, vIvWorld.xz * 0.9 ).r;
	float d2 = texture2D( ivDetail, vIvWorld.xz * 0.11 ).r;
	float d3 = texture2D( ivDetail, vIvWorld.xz * 3.1 ).g;
	diffuseColor.rgb *= ( 0.8 + 0.4 * d1 ) * ( 0.88 + 0.24 * d2 ) * ( 0.9 + 0.2 * d3 );
}`,
      );
  };
  material.customProgramCacheKey = () => 'iv-baked-lighting-1-terrain-detail';
  material.needsUpdate = true;
}

/** Unpacks _IVLIGHT into ivSkyVis / ivBounce (the attribute names engine/bakedLightingMaterial.js reads). */
function unpackLight(geometry) {
  const L = geometry.getAttribute('_ivlight');
  if (!L) return false;
  const n = L.count;
  const sky = new Float32Array(n);
  const bounce = new Float32Array(n * 3);
  const arr = L.array;
  const norm = L.normalized ? 1 / 255 : 1;
  const stride = L.isInterleavedBufferAttribute ? L.data.stride : 4;
  const off = L.isInterleavedBufferAttribute ? L.offset : 0;
  for (let i = 0; i < n; i++) {
    const o = i * stride + off;
    bounce[i * 3] = arr[o] * norm * 0.5;
    bounce[i * 3 + 1] = arr[o + 1] * norm * 0.5;
    bounce[i * 3 + 2] = arr[o + 2] * norm * 0.5;
    sky[i] = arr[o + 3] * norm;
  }
  geometry.setAttribute('ivSkyVis', new BufferAttribute(sky, 1));
  geometry.setAttribute('ivBounce', new BufferAttribute(bounce, 3));
  geometry.deleteAttribute('_ivlight');
  return true;
}

/** UVs of a terrain tile from the albedo rectangle (level frame x0, y0, x1, y1; three z = -y; row 0 = north). */
function terrainUVs(geometry, rect) {
  const pos = geometry.getAttribute('position');
  const [x0, y0, x1, y1] = rect;
  const uv = new Float32Array(pos.count * 2);
  for (let i = 0; i < pos.count; i++) {
    uv[i * 2] = (pos.getX(i) - x0) / (x1 - x0);
    uv[i * 2 + 1] = (y1 + pos.getZ(i)) / (y1 - y0);
  }
  geometry.setAttribute('uv', new BufferAttribute(uv, 2));
}

const NO_SHADOW_CAST = new Set(['glass', 'water', 'backdrop', 'terrain_outer', 'terrain', 'chainlink', 'mesh_deer', 'lamp_emissive']);

/**
 * @param {object} level level JSON with a geometry block
 * @param {object[]} gltfs parsed GLTFs (GLTFLoader results) in level.geometry.render order
 * @param {object} o { maxAnisotropy, ambientFloor, albedoRect }
 * @returns {{ group: Group, lighting: { uniforms, vertices, ms }, stats }}
 */
export function buildGeoLevelView(level, gltfs, { maxAnisotropy = 8, ambientFloor = 0.2, albedoRect = null } = {}) {
  const t0 = typeof performance !== 'undefined' ? performance.now() : 0;
  const group = new Group();
  group.name = level.id;
  const uniforms = createBakedLightingUniforms({ ambientFloor });
  const patched = new Set();
  const detail = detailTexture();
  const stats = { meshes: 0, instanced: 0, instances: 0, triangles: 0, litVertices: 0 };
  for (const gltf of gltfs) {
    const root = gltf.scene;
    root.updateMatrixWorld(true);
    const meshes = [];
    root.traverse((o) => {
      if (o.isMesh) meshes.push(o);
    });
    for (const m of meshes) {
      const g = m.geometry;
      const iv = (m.userData && m.userData.iv) || (m.parent && m.parent.userData && m.parent.userData.iv) || {};
      const matKey = (m.material && m.material.userData && m.material.userData.iv && m.material.userData.iv.key) || iv.material || '';
      const isTerrain = iv.collision === 'terrain';
      if (isTerrain && albedoRect) terrainUVs(g, albedoRect);
      const lit = unpackLight(g);
      if (lit) stats.litVertices += g.getAttribute('position').count;
      const mat = m.material;
      if (mat) {
        if (mat.map) mat.map.anisotropy = maxAnisotropy;
        if (lit && !patched.has(mat)) {
          applyBakedLighting(mat, uniforms);
          if (isTerrain) addTerrainDetail(mat, detail);
          patched.add(mat);
        }
        if (mat.transparent) m.renderOrder = 1;
      }
      const tris = (g.index ? g.index.count : g.getAttribute('position').count) / 3;
      if (m.isInstancedMesh) {
        stats.instanced++;
        stats.instances += m.count;
        stats.triangles += tris * m.count;
        m.castShadow = true;
        m.receiveShadow = true;
        m.frustumCulled = false; // instances spread over the whole map (bounding sphere of the prototype only)
      } else {
        stats.meshes++;
        stats.triangles += tris;
        m.castShadow = !NO_SHADOW_CAST.has(matKey) && !isTerrain;
        m.receiveShadow = matKey !== 'backdrop';
      }
    }
    group.add(root);
  }
  const ms = (typeof performance !== 'undefined' ? performance.now() : 0) - t0;
  return { group, lighting: { uniforms, vertices: stats.litVertices, hiddenVertices: 0, ms, baked: 'build' }, stats };
}
