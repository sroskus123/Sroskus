// Visual representation of the graybox test range ("Zkušební prostor"): neutral metric grid
// materials (1 texture repeat = 1 metre, like an editor dev grid), merged per material for
// few draw calls, plus labelled signs and a banner. Browser only (uses canvas textures).
// With `lighting` options the level is drawn from subdivided geometry with baked indirect
// light (sky visibility + one sunlight bounce per vertex, see engine/indirectBake.js), so
// enclosed spaces get less ambient light than open ground.

import {
  BoxGeometry,
  CanvasTexture,
  Color,
  Group,
  LinearMipmapLinearFilter,
  Mesh,
  MeshBasicMaterial,
  MeshStandardMaterial,
  PlaneGeometry,
  RepeatWrapping,
  SRGBColorSpace,
} from 'three';
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js';
import { buildLightingGeometries } from './lightingGeometry.js';
import { bakeVertexLighting, srgbHexToLinear } from '../engine/indirectBake.js';
import { applyBakedLighting, createBakedLightingUniforms } from '../engine/bakedLightingMaterial.js';

export const PALETTE = {
  floor: { base: '#7a7d80', line: '#55595e', roughness: 0.92 },
  wall: { base: '#9c9993', line: '#75726c', roughness: 0.88 },
  block: { base: '#6c7782', line: '#4d565f', roughness: 0.85 },
  stair: { base: '#8f8b82', line: '#67635b', roughness: 0.9 },
  ramp: { base: '#7f8a82', line: '#5b665e', roughness: 0.9 },
  hazard: { base: '#9a6452', line: '#6f4536', roughness: 0.9 },
  accent: { base: '#c98128', line: '#8f5a1b', roughness: 0.7 },
  dark: { base: '#3b3f45', line: '#2a2d31', roughness: 0.6 },
};

function makeGridTexture(base, line, maxAnisotropy) {
  const size = 256;
  const c = document.createElement('canvas');
  c.width = c.height = size;
  const g = c.getContext('2d');
  g.fillStyle = base;
  g.fillRect(0, 0, size, size);
  // subtle large-scale variation so big planes do not look like flat plastic
  const grad = g.createLinearGradient(0, 0, size, size);
  grad.addColorStop(0, 'rgba(255,255,255,0.025)');
  grad.addColorStop(1, 'rgba(0,0,0,0.035)');
  g.fillStyle = grad;
  g.fillRect(0, 0, size, size);
  g.strokeStyle = line;
  // 0.25 m lines
  g.globalAlpha = 0.28;
  g.lineWidth = 1;
  for (let i = 1; i < 4; i++) {
    if (i === 2) continue;
    const p = (i * size) / 4 + 0.5;
    g.beginPath();
    g.moveTo(p, 0);
    g.lineTo(p, size);
    g.moveTo(0, p);
    g.lineTo(size, p);
    g.stroke();
  }
  // 0.5 m line
  g.globalAlpha = 0.45;
  g.lineWidth = 1.5;
  const h = size / 2;
  g.beginPath();
  g.moveTo(h, 0);
  g.lineTo(h, size);
  g.moveTo(0, h);
  g.lineTo(size, h);
  g.stroke();
  // 1 m border
  g.globalAlpha = 0.85;
  g.lineWidth = 3;
  g.strokeRect(1.5, 1.5, size - 3, size - 3);
  g.globalAlpha = 1;
  const tex = new CanvasTexture(c);
  tex.wrapS = tex.wrapT = RepeatWrapping;
  tex.colorSpace = SRGBColorSpace;
  tex.anisotropy = maxAnisotropy;
  tex.minFilter = LinearMipmapLinearFilter;
  tex.generateMipmaps = true;
  return tex;
}

export function createGridMaterials(maxAnisotropy = 8) {
  const mats = {};
  for (const [key, p] of Object.entries(PALETTE)) {
    mats[key] = new MeshStandardMaterial({
      name: `grid_${key}`,
      map: makeGridTexture(p.base, p.line, maxAnisotropy),
      roughness: p.roughness,
      metalness: 0,
    });
  }
  return mats;
}

function drawSign(text, sub, w = 512, h = 192) {
  const c = document.createElement('canvas');
  c.width = w;
  c.height = h;
  const g = c.getContext('2d');
  g.fillStyle = '#23272c';
  g.fillRect(0, 0, w, h);
  g.fillStyle = '#e39a35';
  g.fillRect(0, 0, w, 10);
  g.fillStyle = '#f2efe8';
  g.textBaseline = 'middle';
  let size = Math.round(h * 0.34);
  g.font = `700 ${size}px "DejaVu Sans", "Segoe UI", Arial, sans-serif`;
  while (g.measureText(text).width > w - 40 && size > 12) {
    size -= 2;
    g.font = `700 ${size}px "DejaVu Sans", "Segoe UI", Arial, sans-serif`;
  }
  g.fillText(text, 22, h * 0.42);
  if (sub) {
    let s2 = Math.round(h * 0.16);
    g.font = `400 ${s2}px "DejaVu Sans", "Segoe UI", Arial, sans-serif`;
    while (g.measureText(sub).width > w - 40 && s2 > 10) {
      s2 -= 1;
      g.font = `400 ${s2}px "DejaVu Sans", "Segoe UI", Arial, sans-serif`;
    }
    g.fillStyle = '#b9c0c7';
    g.fillText(sub, 22, h * 0.76);
  }
  const tex = new CanvasTexture(c);
  tex.colorSpace = SRGBColorSpace;
  tex.anisotropy = 4;
  return tex;
}

/** Linear albedo of a level material (grid texture average ~ base colour, lines darken ~5 %). */
export function paletteAlbedo(mat) {
  const p = PALETTE[mat] || PALETTE.wall;
  return srgbHexToLinear(p.base).map((c) => c * 0.95);
}

/**
 * @param {object} level  test_range.json
 * @param {Array} solids  output of buildLevelSolids
 * @param {object} opts
 * @param {object} [opts.lighting] { world, sunDirection, ambientFloor, rays } bakes indirect light
 * @returns {{group: Group, materials: object, lighting: object|null}}
 */
export function buildTestRangeView(level, solids, { maxAnisotropy = 8, lighting = null } = {}) {
  const group = new Group();
  group.name = 'test_range';
  const mats = createGridMaterials(maxAnisotropy);
  const byMat = new Map();
  let bake = null;
  if (lighting) {
    const t0 = typeof performance !== 'undefined' ? performance.now() : 0;
    const geos = buildLightingGeometries(solids);
    let vertices = 0;
    let hidden = 0;
    geos.forEach((g, i) => {
      const r = bakeVertexLighting(g, lighting.world, { sunDirection: lighting.sunDirection, rays: lighting.rays, albedoOf: paletteAlbedo });
      vertices += r.vertices;
      hidden += r.inside;
      const mat = solids[i].mat;
      if (!byMat.has(mat)) byMat.set(mat, []);
      byMat.get(mat).push(g);
    });
    const uniforms = createBakedLightingUniforms({ ambientFloor: lighting.ambientFloor });
    for (const m of Object.values(mats)) applyBakedLighting(m, uniforms);
    bake = { uniforms, vertices, hiddenVertices: hidden, ms: (typeof performance !== 'undefined' ? performance.now() : 0) - t0 };
  } else {
    for (const s of solids) {
      if (!byMat.has(s.mat)) byMat.set(s.mat, []);
      byMat.get(s.mat).push(s.geometry);
    }
  }
  for (const [mat, geos] of byMat) {
    const merged = mergeGeometries(geos, false);
    const mesh = new Mesh(merged, mats[mat] || mats.wall);
    mesh.name = `range_${mat}`;
    // the finely subdivided lighting geometry only receives shadows; the coarse solids below
    // cast them (same surfaces, a fraction of the triangles in the shadow pass)
    mesh.castShadow = !bake && mat !== 'floor';
    mesh.receiveShadow = true;
    group.add(mesh);
  }
  if (bake) {
    const casters = solids.filter((s) => s.mat !== 'floor').map((s) => s.geometry);
    if (casters.length) {
      const mesh = new Mesh(mergeGeometries(casters, false), new MeshBasicMaterial({ colorWrite: false, depthWrite: false }));
      mesh.name = 'range_shadow_casters';
      mesh.castShadow = true;
      mesh.receiveShadow = false;
      mesh.renderOrder = -2;
      group.add(mesh);
    }
  }

  // outer terrain plane (visual only, below the range floor level so it never z-fights)
  const outer = new Mesh(
    new PlaneGeometry(3000, 3000),
    new MeshStandardMaterial({ color: new Color('#5f6650'), roughness: 1, metalness: 0 }),
  );
  outer.rotation.x = -Math.PI / 2;
  outer.position.y = -0.3; // well below the floor: SwiftShader loses depth precision on huge clipped triangles
  outer.receiveShadow = true;
  outer.name = 'outer_ground';
  group.add(outer);

  // signs on posts (visual only; kept outside walking lanes)
  const postMat = new MeshStandardMaterial({ color: new Color('#2e3237'), roughness: 0.5, metalness: 0.6 });
  const postGeo = new BoxGeometry(0.06, 1.35, 0.06);
  postGeo.translate(0, 0.675, 0);
  for (const s of level.signs || []) {
    const tex = drawSign(s.text, s.sub);
    const board = new Mesh(
      new PlaneGeometry(1.2, 0.45),
      new MeshStandardMaterial({ map: tex, roughness: 0.75, metalness: 0, emissive: new Color('#ffffff'), emissiveMap: tex, emissiveIntensity: 0.08 }),
    );
    board.position.set(s.pos[0], 1.45, s.pos[2]);
    board.rotation.y = ((s.yaw || 0) * Math.PI) / 180;
    board.castShadow = true;
    board.receiveShadow = true;
    group.add(board);
    const back = new Mesh(new BoxGeometry(1.24, 0.49, 0.03), postMat);
    back.position.set(s.pos[0], 1.45, s.pos[2] - 0.02);
    back.rotation.y = board.rotation.y;
    back.castShadow = true;
    group.add(back);
    const post = new Mesh(postGeo, postMat);
    post.position.set(s.pos[0], 0, s.pos[2] - 0.05);
    post.castShadow = true;
    group.add(post);
  }
  for (const b of level.banners || []) {
    const tex = drawSign(b.text, b.sub, 1024, 256);
    const m = new Mesh(new PlaneGeometry(b.size[0], b.size[1]), new MeshStandardMaterial({ map: tex, roughness: 0.8 }));
    m.position.fromArray(b.center);
    m.receiveShadow = true;
    group.add(m);
  }
  return { group, materials: mats, lighting: bake };
}
