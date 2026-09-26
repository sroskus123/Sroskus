// Hitscan per decision D8.
//  1. The camera centre ray defines the intended aim point.
//  2. The path eye -> muzzle must be free (a muzzle poking through a wall is blocked there).
//  3. The shot that actually counts goes from the muzzle to the aim point; the first
//     obstacle on that segment takes the hit, even if the camera could see past it.

import { Vector3 } from 'three';

const _toMuzzle = new Vector3();
const _toAim = new Vector3();

/**
 * @param {object} p
 * @param {Vector3} p.eye      camera position
 * @param {Vector3} p.dir      camera forward (unit)
 * @param {Vector3} p.muzzle   muzzle position in world space
 * @param {number}  p.range
 * @param {(origin:Vector3, dir:Vector3, far:number)=>object|null} p.raycast  nearest hit or null
 */
export function traceShot({ eye, dir, muzzle, range, raycast }) {
  const camHit = raycast(eye, dir, range);
  const aimPoint = camHit ? camHit.point.clone() : eye.clone().addScaledVector(dir, range);

  _toMuzzle.subVectors(muzzle, eye);
  const dm = _toMuzzle.length();
  if (dm > 1e-4) {
    const obstruction = raycast(eye, _toMuzzle.divideScalar(dm).clone(), dm);
    if (obstruction) {
      return {
        hit: obstruction,
        camHit,
        aimPoint,
        origin: eye.clone(),
        direction: _toMuzzle.clone(),
        blocked: true,
        blockedBy: 'eye-to-muzzle',
      };
    }
  }

  _toAim.subVectors(aimPoint, muzzle);
  const da = _toAim.length();
  if (da < 1e-4) {
    return { hit: camHit, camHit, aimPoint, origin: muzzle.clone(), direction: dir.clone(), blocked: false, blockedBy: null };
  }
  const shotDir = _toAim.divideScalar(da).clone();
  // extend slightly past the aim point so the aimed surface itself is registered
  const hit = raycast(muzzle, shotDir, da + 0.05);
  let blocked = false;
  if (hit && camHit) {
    blocked = hit.targetKey !== camHit.targetKey || hit.point.distanceTo(camHit.point) > 0.05;
  } else if (hit && !camHit) {
    blocked = true;
  }
  return {
    hit,
    camHit,
    aimPoint,
    origin: muzzle.clone(),
    direction: shotDir,
    blocked,
    blockedBy: blocked ? 'muzzle-to-aim' : null,
  };
}
