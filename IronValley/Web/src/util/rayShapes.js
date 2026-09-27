// Ray intersection against analytic shapes (spheres, capsules). Pure math, no allocations
// in the hot path except for results.

import { Vector3 } from 'three';

const _m = new Vector3();
const _e = new Vector3();
const _p = new Vector3();

/** Distance t along a unit ray to a sphere, or Infinity. Rays starting inside return Infinity. */
export function raySphereT(o, d, center, r) {
  _m.subVectors(o, center);
  const b = _m.dot(d);
  const c = _m.lengthSq() - r * r;
  if (c > 0 && b > 0) return Infinity;
  const disc = b * b - c;
  if (disc < 0) return Infinity;
  const t = -b - Math.sqrt(disc);
  return t >= 0 ? t : Infinity;
}

/** Distance t along a unit ray to a capsule (segment a-b, radius r), or Infinity. */
export function rayCapsuleT(o, d, a, b, r) {
  let best = Infinity;
  _e.subVectors(b, a);
  const ee = _e.lengthSq();
  if (ee > 1e-12) {
    _m.subVectors(o, a);
    const md = _m.dot(_e);
    const nd = d.dot(_e);
    const A = ee - nd * nd;
    const k = _m.lengthSq() - r * r;
    const B = ee * _m.dot(d) - nd * md;
    const C = ee * k - md * md;
    if (Math.abs(A) > 1e-12) {
      const disc = B * B - A * C;
      if (disc >= 0) {
        const t = (-B - Math.sqrt(disc)) / A;
        if (t >= 0) {
          const s = md + t * nd;
          if (s >= 0 && s <= ee) best = t;
        }
      }
    }
  }
  best = Math.min(best, raySphereT(o, d, a, r), raySphereT(o, d, b, r));
  return best;
}

/** Outward normal of a capsule at a surface point. */
export function capsuleNormal(point, a, b, out = new Vector3()) {
  _e.subVectors(b, a);
  const ee = _e.lengthSq();
  const s = ee > 1e-12 ? Math.min(Math.max(_p.subVectors(point, a).dot(_e) / ee, 0), 1) : 0;
  _p.copy(a).addScaledVector(_e, s);
  return out.subVectors(point, _p).normalize();
}
