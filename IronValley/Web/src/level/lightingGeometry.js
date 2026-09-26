// Render-only level geometry subdivided into small grid cells, so per-vertex baked lighting
// (sky visibility / bounce, see engine/indirectBake.js) has enough resolution. Collision keeps
// using the coarse solids from levelGeometry.js. Pure three.js (no DOM), testable in Node.
//
// Each box face becomes an indexed grid (cell <= `cell` metres, `largeCell` for faces larger
// than `largeFaceArea`) whose lines also run exactly along the edges of every other box that
// touches the face (wall bases on the floor, a roof on top of a wall). So no triangle spans
// from a visible part of the face to a part hidden inside another solid, and baked lighting
// cannot bleed through walls by interpolation. Bottom faces resting on the ground are dropped
// (never visible). Ramps and other triangle solids are subdivided per triangle. UVs are the
// same world projection as applyWorldUVs (1 unit = 1 metre), so the grid textures look
// exactly as before.

import { BufferGeometry, Float32BufferAttribute, Uint32BufferAttribute, Vector3 } from 'three';

const _a = new Vector3();
const _b = new Vector3();
const _c = new Vector3();
const _n = new Vector3();
const _p = new Vector3();

// (normal, u, v) with u x v = normal, so the grid triangles wind counter-clockwise outwards.
// origin(min, max) picks the face corner where the grid starts; size(ext) its u / v extents.
const FACES = [
  { n: [1, 0, 0], u: [0, 0, -1], v: [0, 1, 0], origin: (mn, mx) => [mx[0], mn[1], mx[2]], size: (e) => [e[2], e[1]] },
  { n: [-1, 0, 0], u: [0, 0, 1], v: [0, 1, 0], origin: (mn) => [mn[0], mn[1], mn[2]], size: (e) => [e[2], e[1]] },
  { n: [0, 1, 0], u: [1, 0, 0], v: [0, 0, -1], origin: (mn, mx) => [mn[0], mx[1], mx[2]], size: (e) => [e[0], e[2]], top: true },
  { n: [0, -1, 0], u: [1, 0, 0], v: [0, 0, 1], origin: (mn) => [mn[0], mn[1], mn[2]], size: (e) => [e[0], e[2]], bottom: true },
  { n: [0, 0, 1], u: [1, 0, 0], v: [0, 1, 0], origin: (mn, mx) => [mn[0], mn[1], mx[2]], size: (e) => [e[0], e[1]] },
  { n: [0, 0, -1], u: [-1, 0, 0], v: [0, 1, 0], origin: (mn, mx) => [mx[0], mn[1], mn[2]], size: (e) => [e[0], e[1]] },
];

/** World-projected UV of a point on a face with normal n (same rule as applyWorldUVs). */
function worldUV(x, y, z, nx, ny, nz, out) {
  const ax = Math.abs(nx);
  const ay = Math.abs(ny);
  const az = Math.abs(nz);
  if (ay >= ax && ay >= az) {
    out[0] = x;
    out[1] = -z;
  } else if (ax >= az) {
    out[0] = nx > 0 ? -z : z;
    out[1] = y;
  } else {
    out[0] = nz > 0 ? x : -x;
    out[1] = y;
  }
  return out;
}

class Builder {
  constructor() {
    this.pos = [];
    this.nrm = [];
    this.uv = [];
    this.idx = [];
    // grids: { start, cols, rows } so inside-solid vertices can be filled from neighbours
    this.grids = [];
    this._uv = [0, 0];
  }

  get count() {
    return this.pos.length / 3;
  }

  vertex(x, y, z, nx, ny, nz) {
    this.pos.push(x, y, z);
    this.nrm.push(nx, ny, nz);
    worldUV(x, y, z, nx, ny, nz, this._uv);
    this.uv.push(this._uv[0], this._uv[1]);
    return this.count - 1;
  }

  build() {
    const g = new BufferGeometry();
    g.setAttribute('position', new Float32BufferAttribute(this.pos, 3));
    g.setAttribute('normal', new Float32BufferAttribute(this.nrm, 3));
    g.setAttribute('uv', new Float32BufferAttribute(this.uv, 2));
    g.setIndex(new Uint32BufferAttribute(this.idx, 1));
    g.userData.grids = this.grids;
    return g;
  }
}

/** Sorted grid coordinates in [0, size]: uniform steps plus `extra`, merged when < minGap. */
function gridLines(size, step, extra, minGap = 0.005) {
  const n = Math.max(1, Math.ceil(size / step - 1e-6));
  const vals = [];
  for (let i = 0; i <= n; i++) vals.push({ v: (size * i) / n, pinned: i === 0 || i === n });
  for (const e of extra) if (e > minGap && e < size - minGap) vals.push({ v: e, pinned: true });
  vals.sort((a, b) => a.v - b.v);
  const out = [];
  for (const x of vals) {
    const last = out[out.length - 1];
    if (last && x.v - last.v < minGap) {
      if (x.pinned && !last.pinned) out[out.length - 1] = x;
      continue;
    }
    out.push(x);
  }
  return out.map((x) => x.v);
}

function addBoxFaces(b, min, max, { cell, largeCell, largeFaceArea, groundY, others }) {
  const ext = [max[0] - min[0], max[1] - min[1], max[2] - min[2]];
  for (const f of FACES) {
    if (f.bottom && min[1] <= groundY + 1e-4) continue; // rests on the ground: never visible
    const [su, sv] = f.size(ext);
    const c = su * sv > largeFaceArea ? largeCell : cell;
    const o = f.origin(min, max);
    // edges of other boxes touching this face, projected onto the face's u / v axes
    const axis = f.n[0] !== 0 ? 0 : f.n[1] !== 0 ? 1 : 2;
    const plane = o[axis];
    const eu = [];
    const ev = [];
    const ua = f.u[0] !== 0 ? 0 : f.u[1] !== 0 ? 1 : 2;
    const va = f.v[0] !== 0 ? 0 : f.v[1] !== 0 ? 1 : 2;
    const us = f.u[ua];
    const vs = f.v[va];
    const fmin = [Math.min(o[0], o[0] + f.u[0] * su + f.v[0] * sv), Math.min(o[1], o[1] + f.u[1] * su + f.v[1] * sv), Math.min(o[2], o[2] + f.u[2] * su + f.v[2] * sv)];
    const fmax = [Math.max(o[0], o[0] + f.u[0] * su + f.v[0] * sv), Math.max(o[1], o[1] + f.u[1] * su + f.v[1] * sv), Math.max(o[2], o[2] + f.u[2] * su + f.v[2] * sv)];
    for (const ob of others) {
      if (ob.min === min) continue;
      if (ob.min[axis] > plane + 0.01 || ob.max[axis] < plane - 0.01) continue;
      let overlaps = true;
      for (const k of [ua, va]) if (ob.max[k] < fmin[k] - 1e-4 || ob.min[k] > fmax[k] + 1e-4) overlaps = false;
      if (!overlaps) continue;
      for (const bound of [ob.min[ua], ob.max[ua]]) eu.push((bound - o[ua]) * us);
      for (const bound of [ob.min[va], ob.max[va]]) ev.push((bound - o[va]) * vs);
    }
    const lu = gridLines(su, c, eu);
    const lv = gridLines(sv, c, ev);
    const start = b.count;
    for (let j = 0; j < lv.length; j++) {
      for (let i = 0; i < lu.length; i++) {
        const a = lu[i];
        const d = lv[j];
        b.vertex(o[0] + f.u[0] * a + f.v[0] * d, o[1] + f.u[1] * a + f.v[1] * d, o[2] + f.u[2] * a + f.v[2] * d, f.n[0], f.n[1], f.n[2]);
      }
    }
    const cols = lu.length;
    const nu = lu.length - 1;
    const nv = lv.length - 1;
    for (let j = 0; j < nv; j++) {
      for (let i = 0; i < nu; i++) {
        const p00 = start + j * cols + i;
        const p10 = p00 + 1;
        const p01 = p00 + cols;
        const p11 = p01 + 1;
        b.idx.push(p00, p10, p11, p00, p11, p01);
      }
    }
    b.grids.push({ start, cols, rows: nv + 1 });
  }
}

function addTriangles(b, geometry, cell) {
  const pos = geometry.getAttribute('position');
  for (let t = 0; t < pos.count; t += 3) {
    _a.fromBufferAttribute(pos, t);
    _b.fromBufferAttribute(pos, t + 1);
    _c.fromBufferAttribute(pos, t + 2);
    _n.subVectors(_b, _a).cross(_p.subVectors(_c, _a));
    if (_n.lengthSq() < 1e-12) continue;
    _n.normalize();
    const edge = Math.max(_a.distanceTo(_b), _b.distanceTo(_c), _c.distanceTo(_a));
    const n = Math.max(1, Math.ceil(edge / cell - 1e-6));
    // barycentric lattice: row r has n - r + 1 points
    const rowStart = [];
    for (let r = 0; r <= n; r++) {
      rowStart.push(b.count);
      for (let k = 0; k <= n - r; k++) {
        const wb = k / n;
        const wc = r / n;
        const wa = 1 - wb - wc;
        b.vertex(
          _a.x * wa + _b.x * wb + _c.x * wc,
          _a.y * wa + _b.y * wb + _c.y * wc,
          _a.z * wa + _b.z * wb + _c.z * wc,
          _n.x,
          _n.y,
          _n.z,
        );
      }
    }
    for (let r = 0; r < n; r++) {
      for (let k = 0; k < n - r; k++) {
        const p = rowStart[r] + k;
        const q = rowStart[r] + k + 1;
        const s = rowStart[r + 1] + k;
        b.idx.push(p, q, s);
        if (k < n - r - 1) b.idx.push(q, rowStart[r + 1] + k + 1, s);
      }
    }
  }
}

/**
 * Subdivided, indexed render geometry for one level solid (see buildLevelSolids).
 * @param {object} solid  { geometry, box? }
 * @param {object} [opts]
 * @param {number} [opts.cell]          cell size (m) for ordinary faces
 * @param {number} [opts.largeCell]     cell size for faces larger than largeFaceArea (ground)
 * @param {number} [opts.largeFaceArea] m^2
 * @param {number} [opts.groundY]       bottom faces at or below this height are dropped
 * @param {Array<{min:number[],max:number[]}>} [opts.others] all box solids of the level
 * @returns {BufferGeometry} with position, normal, uv, index and userData.grids
 */
export function buildLightingGeometry(solid, { cell = 0.5, largeCell = 1.0, largeFaceArea = 200, groundY = 0, others = [] } = {}) {
  const b = new Builder();
  if (solid.box) addBoxFaces(b, solid.box.min, solid.box.max, { cell, largeCell, largeFaceArea, groundY, others });
  else addTriangles(b, solid.geometry, cell);
  return b.build();
}

/** Lighting geometry for every solid of a level (box edges shared between solids). */
export function buildLightingGeometries(solids, opts = {}) {
  const others = solids.filter((s) => s.box).map((s) => s.box);
  return solids.map((s) => buildLightingGeometry(s, { ...opts, others }));
}
