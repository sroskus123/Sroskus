// Baked indirect lighting for static level geometry (per vertex) and point probes for dynamic
// objects. Pure three.js + the BVH collision world, no DOM, testable in Node.
//
// Without it the image-based sky light and the hemisphere fill reach every surface fully, so a
// tunnel or a room is exactly as bright as open ground (ENG2-P2-NO-AO). For every vertex, rays
// in a fixed cosine-weighted hemisphere pattern around its normal give:
//   skyVis  fraction of the hemisphere that sees the sky (scales all ambient light, like an
//           ambient-occlusion map: environment, hemisphere fill, specular occlusion);
//   bounce  one bounce of sunlight: surfaces hit by the rays that are sunlit reflect
//           albedo * cos(sun) of the sun's irradiance (plus a small share for their own ambient
//           light), in units of the sun's irradiance at normal incidence (RGB).
// So an interior is dark except where sunlit floor or walls light it, as in reality.
// The fixed ray pattern (not random) keeps neighbouring vertices coherent (no noise).

import { BufferAttribute, DoubleSide, Ray, Vector3 } from 'three';

const GOLDEN = Math.PI * (3 - Math.sqrt(5));

/** Cosine-weighted hemisphere directions around +Z (Malley's method on a Vogel disk). */
export function cosineHemisphere(count) {
  const dirs = [];
  for (let k = 0; k < count; k++) {
    const r = Math.sqrt((k + 0.5) / count);
    const phi = k * GOLDEN;
    dirs.push([r * Math.cos(phi), r * Math.sin(phi), Math.sqrt(Math.max(0, 1 - r * r))]);
  }
  return dirs;
}

const _ray = new Ray();
const _t = new Vector3();
const _bt = new Vector3();
const _dir = new Vector3();
const _hn = new Vector3();
const _va = new Vector3();
const _vb = new Vector3();
const _vc = new Vector3();
const _o = new Vector3();

/** Fallback for world-like objects with a single `bvh` (no groups). */
function rawFromBvh(world, ray, far) {
  const hit = world.bvh.raycastFirst(ray, DoubleSide, 0, far);
  return hit ? { hit, part: world } : null;
}

function tangentFrame(n, t, b) {
  if (Math.abs(n.y) < 0.99) t.set(0, 1, 0).cross(n).normalize();
  else t.set(1, 0, 0).cross(n).normalize();
  b.copy(n).cross(t);
}

/**
 * Samples one point. `out` = { skyVis, bounce: [r, g, b], inside } where inside means most rays
 * started inside a solid (the vertex is hidden, e.g. floor under a wall).
 */
function samplePoint(world, p, n, dirs, opts, out, inward = null) {
  const { sunDirection, maxDistance, albedoOf, ambientShare, originOffset } = opts;
  // all BVH groups of the world (a world without groups behaves exactly like the single main BVH)
  const cast = (ray, far) => (world.raycastFirstRaw ? world.raycastFirstRaw(ray, 0, far) : rawFromBvh(world, ray, far));
  tangentFrame(n, _t, _bt);
  _o.copy(p).addScaledVector(n, originOffset);
  // vertices on a face edge start slightly towards the face centre, so a vertex on a boundary
  // plane (wall base on the floor, wall top under a roof) is judged by the side it belongs to
  if (inward) _o.add(inward);
  let sky = 0;
  let back = 0;
  let br = 0;
  let bg = 0;
  let bb = 0;
  for (let k = 0; k < dirs.length; k++) {
    const d = dirs[k];
    _dir.set(0, 0, 0).addScaledVector(_t, d[0]).addScaledVector(_bt, d[1]).addScaledVector(n, d[2]).normalize();
    _ray.origin.copy(_o);
    _ray.direction.copy(_dir);
    const r = cast(_ray, maxDistance);
    if (!r) {
      sky++;
      continue;
    }
    const hit = r.hit;
    const posAttr = r.part.geometry.getAttribute('position');
    // geometric normal of the triangle as authored (outward): a back face means we are inside
    _va.fromBufferAttribute(posAttr, hit.face.a);
    _vb.fromBufferAttribute(posAttr, hit.face.b);
    _vc.fromBufferAttribute(posAttr, hit.face.c);
    _hn.subVectors(_vb, _va).cross(_vc.sub(_va)).normalize();
    if (_hn.dot(_dir) > 0) {
      back++;
      continue;
    }
    const alb = albedoOf(r.part.solids[r.part.solidOfVertex[hit.face.a]].mat);
    let e = ambientShare;
    const cosSun = _hn.dot(sunDirection);
    if (cosSun > 0) {
      _ray.origin.copy(hit.point).addScaledVector(_hn, 0.01);
      _ray.direction.copy(sunDirection);
      if (!cast(_ray, 400)) e += cosSun;
    }
    br += alb[0] * e;
    bg += alb[1] * e;
    bb += alb[2] * e;
  }
  const inv = 1 / dirs.length;
  out.skyVis = sky * inv;
  out.bounce[0] = br * inv;
  out.bounce[1] = bg * inv;
  out.bounce[2] = bb * inv;
  // From a point outside every solid a ray always enters through a front face first, so back
  // faces mean the vertex is hidden inside (or on the boundary of) another solid.
  out.inside = back >= dirs.length * 0.25;
  return out;
}

const DEFAULTS = {
  rays: 32,
  maxDistance: 60,
  // light an occluding surface reflects from its own ambient light, per unit albedo, relative
  // to the sun's irradiance (ambient ~0.13 of the sun's irradiance, half of it reaching it)
  ambientShare: 0.065,
  originOffset: 0.02,
  albedoOf: () => [0.2, 0.2, 0.2],
};

/**
 * Bakes ivSkyVis (float) and ivBounce (vec3) vertex attributes into an indexed geometry from
 * lightingGeometry.js (vertices hidden inside solids take the values of their grid neighbours).
 * @param {import('three').BufferGeometry} geometry
 * @param {import('../physics/collisionWorld.js').CollisionWorld} world
 * @param {object} opts { sunDirection (unit, towards the sun), rays, maxDistance, albedoOf(mat) -> [r,g,b] linear }
 * @returns {{vertices:number, inside:number, rays:number}}
 */
export function bakeVertexLighting(geometry, world, opts) {
  const o = { ...DEFAULTS, ...opts };
  const dirs = cosineHemisphere(o.rays);
  const pos = geometry.getAttribute('position');
  const nrm = geometry.getAttribute('normal');
  const count = pos.count;
  const sky = new Float32Array(count);
  const bounce = new Float32Array(count * 3);
  const inside = new Uint8Array(count);
  const p = new Vector3();
  const n = new Vector3();
  const s = { skyVis: 0, bounce: [0, 0, 0], inside: false };
  const inward = inwardOffsets(geometry, 0.01);
  const iw = new Vector3();
  let nInside = 0;
  for (let i = 0; i < count; i++) {
    p.fromBufferAttribute(pos, i);
    n.fromBufferAttribute(nrm, i).normalize();
    iw.set(inward[i * 3], inward[i * 3 + 1], inward[i * 3 + 2]);
    samplePoint(world, p, n, dirs, o, s, iw);
    sky[i] = s.skyVis;
    bounce[i * 3] = s.bounce[0];
    bounce[i * 3 + 1] = s.bounce[1];
    bounce[i * 3 + 2] = s.bounce[2];
    if (s.inside) {
      inside[i] = 1;
      nInside++;
    }
  }
  fillInside(geometry.userData.grids || [], inside, sky, bounce);
  geometry.setAttribute('ivSkyVis', new BufferAttribute(sky, 1));
  geometry.setAttribute('ivBounce', new BufferAttribute(bounce, 3));
  return { vertices: count, inside: nInside, rays: o.rays };
}

/** Per-vertex offset (length <= dist) towards the centre of the vertex's grid face. */
function inwardOffsets(geometry, dist) {
  const pos = geometry.getAttribute('position');
  const out = new Float32Array(pos.count * 3);
  const c = new Vector3();
  const p = new Vector3();
  for (const g of geometry.userData.grids || []) {
    const last = g.start + g.rows * g.cols - 1;
    c.fromBufferAttribute(pos, g.start).add(p.fromBufferAttribute(pos, last)).multiplyScalar(0.5);
    for (let i = g.start; i <= last; i++) {
      p.fromBufferAttribute(pos, i);
      const dx = c.x - p.x;
      const dy = c.y - p.y;
      const dz = c.z - p.z;
      const len = Math.hypot(dx, dy, dz);
      if (len < 1e-6) continue;
      const k = Math.min(dist, len) / len;
      out[i * 3] = dx * k;
      out[i * 3 + 1] = dy * k;
      out[i * 3 + 2] = dz * k;
    }
  }
  return out;
}

/** Hidden grid vertices take the average of their visible 4-neighbours (repeated outwards). */
function fillInside(grids, inside, sky, bounce) {
  for (const g of grids) {
    for (let pass = 0; pass < 64; pass++) {
      let changed = 0;
      let remaining = 0;
      const filled = [];
      for (let r = 0; r < g.rows; r++) {
        for (let c = 0; c < g.cols; c++) {
          const i = g.start + r * g.cols + c;
          if (!inside[i]) continue;
          let n = 0;
          let s = 0;
          let b0 = 0;
          let b1 = 0;
          let b2 = 0;
          for (const [dr, dc] of [[-1, 0], [1, 0], [0, -1], [0, 1]]) {
            const rr = r + dr;
            const cc = c + dc;
            if (rr < 0 || cc < 0 || rr >= g.rows || cc >= g.cols) continue;
            const j = g.start + rr * g.cols + cc;
            if (inside[j]) continue;
            n++;
            s += sky[j];
            b0 += bounce[j * 3];
            b1 += bounce[j * 3 + 1];
            b2 += bounce[j * 3 + 2];
          }
          if (n === 0) {
            remaining++;
            continue;
          }
          filled.push([i, s / n, b0 / n, b1 / n, b2 / n]);
        }
      }
      for (const [i, s, b0, b1, b2] of filled) {
        sky[i] = s;
        bounce[i * 3] = b0;
        bounce[i * 3 + 1] = b1;
        bounce[i * 3 + 2] = b2;
        inside[i] = 0;
        changed++;
      }
      if (!changed || !remaining) break;
    }
  }
}

/**
 * Sky visibility of the upper hemisphere at a point (dynamic objects: view model, targets).
 * @returns {{skyVis:number, bounce:number[]}}
 */
export function probeSkyVisibility(world, point, opts = {}) {
  const o = { ...DEFAULTS, ...opts };
  const dirs = o._dirs || cosineHemisphere(o.rays);
  return samplePoint(world, point, new Vector3(0, 1, 0), dirs, { ...o, originOffset: 0 }, { skyVis: 0, bounce: [0, 0, 0], inside: false });
}

/** Linear-light RGB of an sRGB hex colour (albedo from a display colour). */
export function srgbHexToLinear(hex) {
  const v = parseInt(hex.replace('#', ''), 16);
  const ch = (x) => {
    const c = x / 255;
    return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  return [ch((v >> 16) & 255), ch((v >> 8) & 255), ch(v & 255)];
}
