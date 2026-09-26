// Horizontal velocity model of the capsule controller (ground and air), shared by the player and bots.
//
// The velocity is split relative to the WISH direction w (unit, horizontal):
//   along  a = v . w          accelerates towards the target speed T (acceleration), brakes when above it
//                             (speedChangeDeceleration: sprint -> run / crouch, landing crouched) or when
//                             moving against the wish (reverseDeceleration);
//   perp   p = v - a w        the part of the velocity that does NOT go where the character wants to go.
//                             On the ground it is braked hard (lateralBraking + lateralFriction * |p|), so a
//                             turn redirects the velocity quickly instead of sliding on "ice".
// Without input the whole velocity brakes at `deceleration` (stop from sprint ~0.36 s).
// In the air the momentum is kept: the along part can only be raised towards T (airAcceleration), never
// lowered towards a slower stance target (crouching in the air does not stop the character), and the perp
// part is braked only lightly (airLateralBraking) while there is input.
// Never a speed gain: the result is clamped to max(|v| before, T), so strafing / turning / jumping cannot
// build up speed.
//
// Walls touched on the previous tick: the target velocity is projected onto their plane (sliding along a
// wall at the tangential part of the wish, as before), and the removed into-wall part is returned as a
// displacement push so the capsule keeps pressing against the face (contact, step attempts on risers).
// Without the projection the strong lateral braking would make walls sticky.

export const LOCOMOTION_DEFAULTS = Object.freeze({
  acceleration: 14,
  deceleration: 16,
  speedChangeDeceleration: 8,
  reverseDeceleration: 20,
  lateralBraking: 30,
  lateralFriction: 5,
  airAcceleration: 2,
  airLateralBraking: 2,
});

function num(v, d) {
  return typeof v === 'number' && Number.isFinite(v) ? v : d;
}

/** Locomotion parameters from movement.json (missing keys fall back to LOCOMOTION_DEFAULTS). */
export function locomotionParams(P) {
  const D = LOCOMOTION_DEFAULTS;
  return {
    acceleration: num(P.acceleration, D.acceleration),
    deceleration: num(P.deceleration, D.deceleration),
    speedChangeDeceleration: num(P.speedChangeDeceleration, D.speedChangeDeceleration),
    reverseDeceleration: num(P.reverseDeceleration, D.reverseDeceleration),
    lateralBraking: num(P.lateralBraking, D.lateralBraking),
    lateralFriction: num(P.lateralFriction, D.lateralFriction),
    airAcceleration: num(P.airAcceleration, D.airAcceleration),
    airLateralBraking: num(P.airLateralBraking, D.airLateralBraking),
  };
}

/**
 * One tick of the horizontal velocity.
 * @param {{x:number,z:number}} vel      horizontal velocity, modified in place
 * @param {number} wx, wz                wish direction (unit) or 0,0 for no input
 * @param {number} target                target speed T (m/s) along the wish
 * @param {boolean} grounded
 * @param {object} L                     locomotionParams()
 * @param {number} dt
 * @param {Array<{x:number,z:number}>|null} walls  horizontal wall normals touched last tick (pointing out
 *                                       of the wall), may be null
 * @param {number} wallCount
 * @param {{x:number,z:number}} [push]   out: into-wall displacement velocity (m/s), zeroed if unused
 */
export function updateHorizontalVelocity(vel, wx, wz, target, grounded, L, dt, walls = null, wallCount = 0, push = null) {
  if (push) {
    push.x = 0;
    push.z = 0;
  }
  const vx0 = vel.x;
  const vz0 = vel.z;
  const speed0 = Math.hypot(vx0, vz0);
  const hasInput = (wx !== 0 || wz !== 0) && target > 1e-6;

  if (!hasInput) {
    // no input: on the ground brake to a stop; in the air keep the momentum
    if (grounded && speed0 > 0) {
      const s = Math.max(0, speed0 - L.deceleration * dt) / speed0;
      vel.x = vx0 * s;
      vel.z = vz0 * s;
    }
    return;
  }

  // target velocity, projected onto the walls it pushes into
  let tx = wx * target;
  let tz = wz * target;
  if (walls) {
    for (let i = 0; i < wallCount; i++) {
      const n = walls[i];
      const d = tx * n.x + tz * n.z;
      if (d < 0) {
        tx -= n.x * d;
        tz -= n.z * d;
        if (push) {
          push.x += n.x * d;
          push.z += n.z * d;
        }
      }
    }
  }
  const tLen = Math.hypot(tx, tz);
  // direction the velocity is steered to (wish slid along the walls; the wish itself when pressing straight
  // into a wall, whose along target is then ~0)
  let dx = wx;
  let dz = wz;
  let T = 0;
  if (tLen > 1e-4 * target) {
    dx = tx / tLen;
    dz = tz / tLen;
    T = tLen;
  }

  let a = vx0 * dx + vz0 * dz;
  let px = vx0 - a * dx;
  let pz = vz0 - a * dz;
  const p = Math.hypot(px, pz);

  if (grounded) {
    // perpendicular part: strong braking (turns)
    if (p > 0) {
      const s = Math.max(0, p - (L.lateralBraking + L.lateralFriction * p) * dt) / p;
      px *= s;
      pz *= s;
    }
    // along part
    if (a < 0) a = Math.min(0, a + L.reverseDeceleration * dt);
    else if (a > T) a = Math.max(T, a - L.speedChangeDeceleration * dt);
    else a = Math.min(T, a + L.acceleration * dt);
  } else {
    if (p > 0) {
      const s = Math.max(0, p - L.airLateralBraking * dt) / p;
      px *= s;
      pz *= s;
    }
    if (a < T) a = Math.min(T, a + L.airAcceleration * dt);
    // a >= T: momentum kept (no braking towards a slower stance target in the air)
  }

  let vx = a * dx + px;
  let vz = a * dz + pz;
  // never a speed gain from turning / strafing / walls
  const cap = Math.max(speed0, T);
  const s1 = Math.hypot(vx, vz);
  if (s1 > cap && s1 > 0) {
    vx *= cap / s1;
    vz *= cap / s1;
  }
  vel.x = vx;
  vel.z = vz;
}
