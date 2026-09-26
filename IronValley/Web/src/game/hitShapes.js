// Hit zones of a combatant (head sphere, torso capsule, two arm and two leg capsules) computed from
// the capsule controller state and the look direction. The placeholder mannequin (characterView.js)
// is built from the same numbers, so what you see is what you hit. Pure math (no DOM), Node-testable.

import { Vector3 } from 'three';
import { capsuleNormal, rayCapsuleT, raySphereT } from '../util/rayShapes.js';

const _c = new Vector3();
const _a = new Vector3();
const _b = new Vector3();

function makeShape(part, type) {
  return { part, type, a: new Vector3(), b: new Vector3(), center: new Vector3(), radius: 0 };
}

/** Reusable set of shapes for one combatant. */
export function createHitShapeSet() {
  return [
    makeShape('head', 'sphere'),
    makeShape('torso', 'capsule'),
    makeShape('arm', 'capsule'),
    makeShape('arm', 'capsule'),
    makeShape('leg', 'capsule'),
    makeShape('leg', 'capsule'),
  ];
}

/**
 * Updates `shapes` in place.
 * @param shapes  from createHitShapeSet()
 * @param cfg     combat.json hitShapes
 * @param s       { feet: Vector3, height, standHeight, eyeHeight, yaw, pitch, gripHip: Vector3|null, gripSupport: Vector3|null }
 *                grip points are world positions of the firing / support hand (the arms end there)
 */
export function updateHitShapes(shapes, cfg, s) {
  const k = s.height / s.standHeight; // crouch squashes torso and legs
  const f = s.feet;
  const cy = Math.cos(s.yaw);
  const sy = Math.sin(s.yaw);
  // right = (cos, 0, -sin), forward = (-sin, 0, -cos)
  const rx = cy;
  const rz = -sy;
  const [head, torso, armR, armL, legR, legL] = shapes;
  head.radius = cfg.headRadius;
  head.center.set(f.x, f.y + s.eyeHeight + cfg.headAboveEye, f.z);
  head.a.copy(head.center);
  head.b.copy(head.center);

  torso.radius = cfg.torso.radius;
  torso.a.set(f.x, f.y + cfg.torso.from * k, f.z);
  torso.b.set(f.x, f.y + Math.min(cfg.torso.to * k, s.eyeHeight - cfg.headRadius * 0.6), f.z);

  const L = cfg.leg;
  legR.radius = legL.radius = L.radius;
  legR.a.set(f.x + rx * L.side, f.y + L.to * k, f.z + rz * L.side);
  legR.b.set(f.x + rx * L.side, f.y + L.from, f.z + rz * L.side);
  legL.a.set(f.x - rx * L.side, f.y + L.to * k, f.z - rz * L.side);
  legL.b.set(f.x - rx * L.side, f.y + L.from, f.z - rz * L.side);

  const A = cfg.arm;
  armR.radius = armL.radius = A.radius;
  const shY = f.y + Math.min(A.shoulderHeight * k, s.eyeHeight - 0.2);
  armR.a.set(f.x + rx * A.shoulderSide, shY, f.z + rz * A.shoulderSide);
  armL.a.set(f.x - rx * A.shoulderSide, shY, f.z - rz * A.shoulderSide);
  if (s.gripHip && s.gripSupport) {
    armR.b.copy(s.gripHip);
    armL.b.copy(s.gripSupport);
  } else {
    // arms hanging down (no weapon pose available)
    armR.b.set(armR.a.x, shY - 0.55 * k, armR.a.z);
    armL.b.set(armL.a.x, shY - 0.55 * k, armL.a.z);
  }
  for (const sh of shapes) {
    if (sh.type === 'capsule') sh.center.addVectors(sh.a, sh.b).multiplyScalar(0.5);
  }
  return shapes;
}

/**
 * Nearest intersection of a unit ray with the shapes. Returns { part, distance, point, normal } or
 * null. Rays starting inside a shape ignore that shape (raySphereT / rayCapsuleT semantics).
 */
export function raycastShapes(shapes, origin, dir, far) {
  let best = null;
  for (const sh of shapes) {
    let t;
    if (sh.type === 'sphere') t = raySphereT(origin, dir, sh.center, sh.radius);
    else t = rayCapsuleT(origin, dir, sh.a, sh.b, sh.radius);
    if (t <= far && (!best || t < best.distance)) best = { shape: sh, distance: t };
  }
  if (!best) return null;
  const point = origin.clone().addScaledVector(dir, best.distance);
  let normal;
  if (best.shape.type === 'sphere') normal = point.clone().sub(best.shape.center).normalize();
  else normal = capsuleNormal(point, best.shape.a, best.shape.b, new Vector3());
  return { part: best.shape.part, distance: best.distance, point, normal };
}

/** Is the point inside any shape (with a small margin)? Used to skip the target body in line-of-sight tests. */
export function pointInShapes(shapes, p, margin = 0.02) {
  for (const sh of shapes) {
    if (sh.type === 'sphere') {
      if (_c.subVectors(p, sh.center).length() <= sh.radius + margin) return true;
    } else {
      _a.copy(sh.a);
      _b.subVectors(sh.b, sh.a);
      const ll = _b.lengthSq();
      const t = ll > 1e-12 ? Math.min(Math.max(_c.subVectors(p, _a).dot(_b) / ll, 0), 1) : 0;
      _c.copy(_a).addScaledVector(_b, t);
      if (_c.distanceTo(p) <= sh.radius + margin) return true;
    }
  }
  return false;
}

/** Axis-aligned bounds of a shape set (for cheap ray rejection). */
export function shapeBounds(shapes, outMin, outMax) {
  outMin.set(Infinity, Infinity, Infinity);
  outMax.set(-Infinity, -Infinity, -Infinity);
  for (const sh of shapes) {
    const r = sh.radius;
    for (const p of sh.type === 'sphere' ? [sh.center] : [sh.a, sh.b]) {
      outMin.x = Math.min(outMin.x, p.x - r);
      outMin.y = Math.min(outMin.y, p.y - r);
      outMin.z = Math.min(outMin.z, p.z - r);
      outMax.x = Math.max(outMax.x, p.x + r);
      outMax.y = Math.max(outMax.y, p.y + r);
      outMax.z = Math.max(outMax.z, p.z + r);
    }
  }
}
