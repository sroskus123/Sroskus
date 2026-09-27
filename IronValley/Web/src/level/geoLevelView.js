// Visual of a generated level (level.geometry, e.g. "Kalné Hamry"): the GLB scenes written by
// Tools/level/export_web_level.py, with the lighting baked at build time.
//
//  - _IVLIGHT (u8 RGBA per vertex: one-bounce sunlight * 2 in RGB, sky visibility in A) becomes the ivSkyVis /
//    ivBounce attributes of engine/bakedLightingMaterial.js, so interiors get less sky light than open ground
//    exactly like the test range, without baking at load time.
//  - Terrain tiles and the outer terrain ring get the splat material (level/terrainMaterial.js, decision D13):
//    tiling PBR detail layers blended by the 0.25 m weight images, anti-tiling, macro tint, wet asphalt + puddles.
//  - Road markings are decal strips (polygon offset, no shadow); vegetation lives in level/vegetation.js.
//  - Shadows: world meshes cast and receive, the terrain receives; glass, water, trees' crowns (cheap) as data says.
// Browser only (textures come decoded from GLTFLoader).

import { BufferAttribute, Group } from 'three';
import { applyBakedLighting, createBakedLightingUniforms } from '../engine/bakedLightingMaterial.js';
import { applyTerrainSplat } from './terrainMaterial.js';

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

const NO_SHADOW_CAST = new Set(['glass', 'water', 'backdrop', 'terrain_outer', 'terrain', 'chainlink', 'mesh_deer', 'lamp_emissive', 'road_marking']);

/**
 * @param {object} level level JSON with a geometry block
 * @param {object[]} gltfs parsed GLTFs (GLTFLoader results) in level.geometry.render order
 * @param {object} o { maxAnisotropy, ambientFloor, terrainSplat (level/terrainMaterial.loadTerrainSplat), wet }
 * @returns {{ group: Group, lighting: { uniforms, vertices, ms }, stats }}
 */
export function buildGeoLevelView(level, gltfs, { maxAnisotropy = 8, ambientFloor = 0.2, terrainSplat = null, wet = 1.0 } = {}) {
  const t0 = typeof performance !== 'undefined' ? performance.now() : 0;
  const group = new Group();
  group.name = level.id;
  const uniforms = createBakedLightingUniforms({ ambientFloor });
  const patched = new Set();
  const stats = { meshes: 0, instanced: 0, instances: 0, triangles: 0, litVertices: 0, splatMaterials: 0 };
  const splatted = new Set();
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
      const lit = unpackLight(g);
      if (lit) stats.litVertices += g.getAttribute('position').count;
      const mat = m.material;
      if (mat) {
        if (mat.map) mat.map.anisotropy = maxAnisotropy;
        if (lit && !patched.has(mat)) {
          applyBakedLighting(mat, uniforms);
          patched.add(mat);
        }
        if (terrainSplat && (isTerrain || matKey === 'terrain_outer') && !splatted.has(mat)) {
          applyTerrainSplat(mat, terrainSplat, { wet });
          splatted.add(mat);
          stats.splatMaterials++;
        }
        if (matKey === 'road_marking' && !mat.polygonOffset) {
          mat.polygonOffset = true;
          mat.polygonOffsetFactor = -2;
          mat.polygonOffsetUnits = -4;
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
