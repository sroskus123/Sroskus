// Analytic swept-sphere vs triangle time of impact.
// Used for precise ground probing (sweeping the capsule's bottom sphere downwards) so that
// the controller finds the exact first contact instead of stepping in coarse increments.

import { Vector3 } from 'three';

const _n = new Vector3();
const _p = new Vector3();
const _e = new Vector3();
const _m = new Vector3();
const _ab = new Vector3();
const _ac = new Vector3();
const _tmp = new Vector3();
// Contacts that start up to SKIN inside a surface count as an immediate hit (t = 0) instead of
// being ignored; resting contacts carry tiny floating point penetration.
const SKIN = 0.01;

/** Smallest t >= 0 with |o + t d - center| = r (d normalised), or Infinity. */
function raySphere(o, d, center, r) {
  _m.subVectors(o, center);
  const b = _m.dot(d);
  const c = _m.lengthSq() - r * r;
  if (b > 0) return Infinity; // moving away
  const disc = b * b - c;
  if (disc < 0) return Infinity;
  const t = -b - Math.sqrt(disc);
  if (t < -SKIN) return Infinity; // deeply inside: overlap is handled by depenetration
  return Math.max(t, 0);
}

/** Smallest t >= 0 where the ray hits the capsule around segment [p, q] with radius r (cylinder part only). */
function rayCylinder(o, d, p, q, r) {
  _e.subVectors(q, p);
  const ee = _e.lengthSq();
  if (ee < 1e-12) return Infinity;
  _m.subVectors(o, p);
  const md = _m.dot(_e);
  const nd = d.dot(_e);
  const a = ee - nd * nd;
  const k = _m.lengthSq() - r * r;
  const b = ee * _m.dot(d) - nd * md;
  const c = ee * k - md * md;
  if (Math.abs(a) < 1e-12) return Infinity; // ray parallel to the cylinder axis
  const disc = b * b - a * c;
  if (disc < 0) return Infinity;
  let t = (-b - Math.sqrt(disc)) / a;
  if (t < -SKIN) return Infinity;
  if (b > 0 && t < 0) return Infinity; // inside the skin but moving away
  t = Math.max(t, 0);
  const s = md + t * nd; // projection on axis (times ee)
  if (s < 0 || s > ee) return Infinity;
  return t;
}

/**
 * Time of impact of a sphere (center o, radius r) moving along unit direction d against the
 * triangle `tri` (ExtendedTriangle / Triangle with a, b, c). Returns t (distance) or Infinity.
 * Writes the contact point on the triangle into outPoint if provided.
 */
export function sweepSphereTriangle(o, d, r, tri, maxDist, outPoint) {
  let best = Infinity;
  // face
  _ab.subVectors(tri.b, tri.a);
  _ac.subVectors(tri.c, tri.a);
  _n.crossVectors(_ab, _ac);
  const nl = _n.length();
  if (nl > 1e-12) {
    _n.divideScalar(nl);
    let h = _n.dot(_tmp.subVectors(o, tri.a));
    if (h < 0) {
      _n.negate();
      h = -h;
    }
    const approach = -_n.dot(d);
    if (approach > 1e-9 && h >= r - SKIN) {
      const t = Math.max((h - r) / approach, 0);
      if (t <= maxDist) {
        _p.copy(o).addScaledVector(d, t).addScaledVector(_n, -r);
        if (tri.containsPoint(_p)) {
          best = t;
          if (outPoint) outPoint.copy(_p);
        }
      }
    }
  }
  // edges
  const verts = [tri.a, tri.b, tri.c];
  for (let i = 0; i < 3; i++) {
    const p = verts[i];
    const q = verts[(i + 1) % 3];
    const t = rayCylinder(o, d, p, q, r);
    if (t < best && t <= maxDist) {
      best = t;
      if (outPoint) {
        // closest point on edge to the sphere center at t
        _p.copy(o).addScaledVector(d, t);
        _e.subVectors(q, p);
        const s = Math.min(Math.max(_tmp.subVectors(_p, p).dot(_e) / _e.lengthSq(), 0), 1);
        outPoint.copy(p).addScaledVector(_e, s);
      }
    }
  }
  // vertices
  for (let i = 0; i < 3; i++) {
    const t = raySphere(o, d, verts[i], r);
    if (t < best && t <= maxDist) {
      best = t;
      if (outPoint) outPoint.copy(verts[i]);
    }
  }
  return best;
}
