// Builds world-space BufferGeometry for level solids from JSON data.
// Pure three.js (no DOM), so the same geometry feeds the renderer, the BVH collision
// world and the Node unit tests.

import { BoxGeometry, BufferGeometry, Float32BufferAttribute, Vector3 } from 'three';

const _n = new Vector3();
const _a = new Vector3();
const _b = new Vector3();
const _c = new Vector3();
const _ab = new Vector3();
const _ac = new Vector3();

/**
 * Assigns world-space UVs (1 unit = 1 metre) by projecting each triangle on the
 * plane most aligned with its normal, so grid textures show true metric squares.
 * Geometry must be non-indexed.
 */
export function applyWorldUVs(geometry, scale = 1) {
  const pos = geometry.getAttribute('position');
  const uv = new Float32Array(pos.count * 2);
  for (let i = 0; i < pos.count; i += 3) {
    _a.fromBufferAttribute(pos, i);
    _b.fromBufferAttribute(pos, i + 1);
    _c.fromBufferAttribute(pos, i + 2);
    _ab.subVectors(_b, _a);
    _ac.subVectors(_c, _a);
    _n.crossVectors(_ab, _ac).normalize();
    const ax = Math.abs(_n.x);
    const ay = Math.abs(_n.y);
    const az = Math.abs(_n.z);
    for (let k = 0; k < 3; k++) {
      const x = pos.getX(i + k);
      const y = pos.getY(i + k);
      const z = pos.getZ(i + k);
      let u;
      let v;
      if (ay >= ax && ay >= az) {
        u = x;
        v = -z;
      } else if (ax >= az) {
        u = _n.x > 0 ? -z : z;
        v = y;
      } else {
        u = _n.z > 0 ? x : -x;
        v = y;
      }
      uv[(i + k) * 2] = u * scale;
      uv[(i + k) * 2 + 1] = v * scale;
    }
  }
  geometry.setAttribute('uv', new Float32BufferAttribute(uv, 2));
  return geometry;
}

export function boxGeometry(min, max) {
  const sx = max[0] - min[0];
  const sy = max[1] - min[1];
  const sz = max[2] - min[2];
  if (!(sx > 0 && sy > 0 && sz > 0)) throw new Error(`Invalid box extents ${min} ${max}`);
  const g = new BoxGeometry(sx, sy, sz).toNonIndexed();
  g.translate((min[0] + max[0]) / 2, (min[1] + max[1]) / 2, (min[2] + max[2]) / 2);
  return g;
}

/**
 * Wedge ramp spanning x0..x1, rising from height 0 at zToe to `height` at zTop.
 * Faces: sloped top, vertical back at zTop, two vertical side triangles.
 * (The bottom face lies on the ground and is omitted.)
 */
export function rampGeometry(x0, x1, zToe, zTop, height, baseY = 0) {
  const y0 = baseY;
  const y1 = baseY + height;
  // corner points
  const A = [x0, y0, zToe]; // toe left
  const B = [x1, y0, zToe]; // toe right
  const C = [x1, y1, zTop]; // top right
  const D = [x0, y1, zTop]; // top left
  const E = [x1, y0, zTop]; // back bottom right
  const F = [x0, y0, zTop]; // back bottom left
  const tris = [];
  const pushTri = (p, q, r) => tris.push(p, q, r);
  // Ensure outward winding regardless of direction of the ramp.
  const addFace = (pts, outward) => {
    // pts: polygon (3 or 4 points) - triangulate fan, fix winding to match outward
    const tri = (p, q, r) => {
      _a.fromArray(p);
      _b.fromArray(q);
      _c.fromArray(r);
      _ab.subVectors(_b, _a);
      _ac.subVectors(_c, _a);
      _n.crossVectors(_ab, _ac);
      if (_n.dot(outward) < 0) pushTri(p, r, q);
      else pushTri(p, q, r);
    };
    tri(pts[0], pts[1], pts[2]);
    if (pts.length === 4) tri(pts[0], pts[2], pts[3]);
  };
  const dz = Math.sign(zTop - zToe) || 1;
  // slope normal: up and towards the toe
  addFace([A, B, C, D], new Vector3(0, 1, -dz));
  // back face (vertical) facing away from toe
  addFace([F, E, C, D], new Vector3(0, 0, dz));
  // side faces
  addFace([A, F, D], new Vector3(-1, 0, 0));
  addFace([B, E, C], new Vector3(1, 0, 0));
  const pos = new Float32Array(tris.length * 3);
  tris.forEach((p, i) => pos.set(p, i * 3));
  const g = new BufferGeometry();
  g.setAttribute('position', new Float32BufferAttribute(pos, 3));
  g.computeVertexNormals();
  return g;
}

/** Expands a stairs definition into box definitions (solid steps down to the ground). */
export function expandStairs(def) {
  const boxes = [];
  const [x0, x1] = def.x;
  const dir = def.dir === 1 ? 1 : -1;
  const baseY = def.baseY ?? 0;
  for (let i = 0; i < def.risers - 1; i++) {
    const za = def.zStart + dir * def.tread * i;
    const zb = def.zStart + dir * def.tread * (i + 1);
    boxes.push({
      id: `${def.id}_step${i + 1}`,
      min: [x0, baseY, Math.min(za, zb)],
      max: [x1, baseY + def.riser * (i + 1), Math.max(za, zb)],
      mat: def.mat,
    });
  }
  const zl0 = def.zStart + dir * def.tread * (def.risers - 1);
  const zl1 = zl0 + dir * def.landingDepth;
  boxes.push({
    id: `${def.id}_landing`,
    min: [x0, baseY, Math.min(zl0, zl1)],
    max: [x1, baseY + def.riser * def.risers, Math.max(zl0, zl1)],
    mat: def.mat,
  });
  return boxes;
}

/** Expands a wall with rectangular openings into box pieces. */
export function expandWall(def) {
  const boxes = [];
  const t = def.thickness / 2;
  const openings = [...(def.openings || [])].sort((a, b) => a.from - b.from);
  const mk = (id, a0, a1, y0, y1) => {
    if (a1 - a0 < 1e-6 || y1 - y0 < 1e-6) return;
    if (def.axis === 'x') {
      boxes.push({ id, min: [a0, y0, def.center - t], max: [a1, y1, def.center + t], mat: def.mat, parent: def.id });
    } else {
      boxes.push({ id, min: [def.center - t, y0, a0], max: [def.center + t, y1, a1], mat: def.mat, parent: def.id });
    }
  };
  let cursor = def.from;
  openings.forEach((o, i) => {
    mk(`${def.id}_seg${i}`, cursor, o.from, 0, def.height);
    mk(`${def.id}_below${i}`, o.from, o.to, 0, o.bottom);
    mk(`${def.id}_above${i}`, o.from, o.to, o.top, def.height);
    cursor = o.to;
  });
  mk(`${def.id}_seg${openings.length}`, cursor, def.to, 0, def.height);
  return boxes;
}

/**
 * Returns [{ id, parent, mat, collide, geometry, box? }] with non-indexed world-space geometry
 * including normals and world UVs. `box` ({min, max}) is set for box-shaped solids (used by
 * the render-only lighting geometry, see lightingGeometry.js).
 */
export function buildLevelSolids(level) {
  const out = [];
  const addBox = (b, parent) => {
    const g = boxGeometry(b.min, b.max);
    applyWorldUVs(g);
    out.push({
      id: b.id,
      parent: b.parent || parent || b.id,
      mat: b.mat || 'wall',
      collide: b.collide !== false,
      geometry: g,
      box: { min: [...b.min], max: [...b.max] },
    });
  };
  for (const s of level.solids) {
    switch (s.type) {
      case 'box':
        addBox(s, s.id);
        break;
      case 'stairs':
        for (const b of expandStairs(s)) addBox(b, s.id);
        break;
      case 'wall':
        for (const b of expandWall(s)) addBox(b, s.id);
        break;
      case 'ramp': {
        const g = rampGeometry(s.x[0], s.x[1], s.zToe, s.zTop, s.height, s.baseY ?? 0);
        applyWorldUVs(g);
        out.push({ id: s.id, parent: s.id, mat: s.mat || 'ramp', collide: s.collide !== false, geometry: g });
        break;
      }
      default:
        throw new Error(`Unknown solid type: ${s.type}`);
    }
  }
  return out;
}

/** All axis-aligned boxes of a level (boxes, expanded stairs and wall pieces); ramps excluded. */
export function listLevelBoxes(level) {
  const out = [];
  for (const s of level.solids) {
    if (s.type === 'box') out.push({ id: s.id, min: s.min, max: s.max, collide: s.collide !== false });
    else if (s.type === 'stairs') expandStairs(s).forEach((b) => out.push({ ...b, collide: true }));
    else if (s.type === 'wall') expandWall(s).forEach((b) => out.push({ ...b, collide: true }));
  }
  return out;
}
