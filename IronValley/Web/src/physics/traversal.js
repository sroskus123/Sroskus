// Vault / mantle traversal for the capsule controller (player and bots).
//
// planTraversal() looks for an obstacle in front of the character whose top is minHeight..maxHeight above
// the ground it stands on (default 0.5..1.3 m) and plans a short scripted kinematic move over it:
//   VAULT   thin obstacle (<= vaultMaxThickness) with walkable landing space behind: up, over, down;
//   MANTLE  deep obstacle: up and onto the top (standing if there is headroom, else crouched).
// The path is a monotone cubic curve in time through keypoints (take-off, in front of the face at
// top + lift, past the back / onto the top, landing). Monotone interpolation never overshoots, so while
// the capsule is horizontally over the obstacle its feet are exactly at top + lift. EVERY sample of the
// path (<= sampleSpacing apart) is validated with a capsule overlap test against the collision world
// (tucked capsule, tuckHeight), and the end point with the crouched capsule; if anything is blocked the
// traversal does not start (or tries a small sideways shift, e.g. to line up with a window). During the
// move the controller re-checks every tick and aborts safely (stays at the last free position, falls).
//
// No geometry is ever entered: the rise happens gap metres in front of the obstacle face, the crossing
// lift metres above its top, and a ceiling / narrow landing / too small opening fails the overlap tests.

export const TRAVERSAL_DEFAULTS = Object.freeze({
  enabled: true,
  minHeight: 0.5,
  maxHeight: 1.3,
  reach: 0.5,
  reachPerSpeed: 0.07,
  maxFacingAngleDeg: 50,
  vaultMaxThickness: 0.7,
  mantleMinDepth: 0.55,
  lift: 0.05,
  gap: 0.03,
  tuckHeight: 1.0,
  tuckEyeHeight: 0.88,
  maxDropBehind: 1.0,
  landingExtra: 0.2,
  landingExtraPerSpeed: 0.05,
  // timing: keypoint times from segment lengths and plausible speeds, total clamped to min..maxDuration
  riseSpeed: 5.0, // average feet speed of the rise to the top (the body tucks: the eye rises only ~0.3 m)
  dropSpeed: 5.0, // average feet speed of the drop behind a vault
  minEntrySpeed: 2.5,
  crossSpeedFactor: 0.75, // horizontal speed over the obstacle = factor x entry speed (a vault costs momentum)
  minCrossSpeed: 2.2,
  maxCrossSpeed: 4.5,
  mantleSpeedFactor: 0.4,
  minMantleSpeed: 1.2,
  maxMantleSpeed: 2.0,
  minMantleCrossTime: 0.25,
  minDuration: 0.5,
  maxDuration: 0.9,
  lateralNudges: [0.1, 0.2, 0.3],
  sampleSpacing: 0.03,
  planShrink: 0.001,
  tickShrink: 0.002,
  airMaxFallSpeed: 4.0,
  exitSpeedVault: 0.8,
  exitSpeedMantle: 0.8,
  // after the move the weapon is raised again for this long (s) and cannot fire until it is up
  weaponRaiseTime: 0.25,
});

export function traversalParams(P) {
  return { ...TRAVERSAL_DEFAULTS, ...((P && P.traversal) || {}) };
}

// ------------------------------------------------------------------ monotone cubic (Fritsch-Carlson)

/** Tangents for a monotone piecewise cubic Hermite through (t[i], v[i]); m0 / mN optional end slopes. */
function monotoneTangents(t, v, m0 = null, mN = null) {
  const n = t.length;
  const d = [];
  for (let i = 0; i < n - 1; i++) d.push((v[i + 1] - v[i]) / (t[i + 1] - t[i]));
  const m = new Array(n);
  m[0] = d[0];
  m[n - 1] = d[n - 2];
  for (let i = 1; i < n - 1; i++) m[i] = d[i - 1] * d[i] <= 0 ? 0 : (d[i - 1] + d[i]) / 2;
  if (m0 !== null) m[0] = m0;
  if (mN !== null) m[n - 1] = mN;
  for (let i = 0; i < n - 1; i++) {
    if (d[i] === 0) {
      m[i] = 0;
      m[i + 1] = 0;
      continue;
    }
    // same sign as the secant, and inside the Fritsch-Carlson circle (no overshoot)
    if (m[i] * d[i] < 0) m[i] = 0;
    if (m[i + 1] * d[i] < 0) m[i + 1] = 0;
    const a = m[i] / d[i];
    const b = m[i + 1] / d[i];
    const h = a * a + b * b;
    if (h > 9) {
      const k = 3 / Math.sqrt(h);
      m[i] = k * a * d[i];
      m[i + 1] = k * b * d[i];
    }
  }
  return m;
}

function hermite(t, T, V, M) {
  const n = T.length;
  if (t <= T[0]) return V[0];
  if (t >= T[n - 1]) return V[n - 1];
  let i = 0;
  while (i < n - 2 && t > T[i + 1]) i++;
  const h = T[i + 1] - T[i];
  const u = (t - T[i]) / h;
  const u2 = u * u;
  const u3 = u2 * u;
  return (2 * u3 - 3 * u2 + 1) * V[i] + (u3 - 2 * u2 + u) * h * M[i] + (-2 * u3 + 3 * u2) * V[i + 1] + (u3 - u2) * h * M[i + 1];
}

function smooth01(x) {
  const u = Math.min(1, Math.max(0, x));
  return u * u * (3 - 2 * u);
}

// ------------------------------------------------------------------ plan (curve)

/** A validated traversal path. positionAt(t, out) gives the feet position for t in [0, 1]. */
export class TraversalPlan {
  constructor(o) {
    Object.assign(this, o);
    const { T, S, L, Y } = this;
    this.MS = monotoneTangents(T, S, o.ms0 ?? null, null);
    this.ML = monotoneTangents(T, L, 0, 0);
    this.MY = monotoneTangents(T, Y, o.my0 ?? null, o.myN ?? null);
  }

  positionAt(t, out) {
    const s = hermite(t, this.T, this.S, this.MS);
    const l = hermite(t, this.T, this.L, this.ML);
    out.x = this.x0 + this.mx * s + this.lx * l;
    out.z = this.z0 + this.mz * s + this.lz * l;
    out.y = hermite(t, this.T, this.Y, this.MY);
    return out;
  }

  /** Eye height (relative to the feet) along the move: tuck while crossing, then the end stance. */
  eyeHeightAt(t) {
    const t1 = this.T[1];
    const t2 = this.T[this.T.length - 2];
    if (t <= t1) return this.eye0 + (this.tuckEye - this.eye0) * smooth01(t / t1);
    if (t <= t2) return this.tuckEye;
    return this.tuckEye + (this.eyeEnd - this.tuckEye) * smooth01((t - t2) / (1 - t2));
  }
}

// ------------------------------------------------------------------ planning

/**
 * @param {import('./characterController.js').CharacterController} ctrl
 * @param {object} o
 * @param {number} o.dirX, o.dirZ   horizontal unit direction of the traversal (facing)
 * @param {number} o.speed          horizontal speed towards dir (m/s, >= 0)
 * @param {number} o.baseY          height of the ground the character stands on / left (obstacle height ref)
 * @param {boolean} [o.airborne]
 * @param {boolean} [o.nudge]       try small sideways shifts if the straight path is blocked (default true)
 * @param {object} [o.params]       traversalParams()
 * @returns {{ok:true, plan:TraversalPlan} | {ok:false, reason:string, detail?:object}}
 */
export function planTraversal(ctrl, o) {
  const TP = o.params || traversalParams(ctrl.params);
  const world = ctrl.world;
  const V = ctrl.position.constructor; // three.js Vector3 without importing three here
  const pos = ctrl.position;
  const r = ctrl.radius;
  const mx = o.dirX;
  const mz = o.dirZ;
  const lx = -mz; // lateral unit (right of m when m = forward)
  const lz = mx;
  const speed = Math.max(0, o.speed || 0);
  const baseY = o.baseY;
  const cosFacing = Math.cos((TP.maxFacingAngleDeg * Math.PI) / 180);
  const walkableCos = ctrl.walkableCos;
  const origin = new V();
  const dir = new V(mx, 0, mz);
  const down = new V(0, -1, 0);
  const maxReach = r + TP.reach + TP.reachPerSpeed * speed;
  const topProbeY = baseY + TP.maxHeight + 0.3;

  // --- obstacle face in front (horizontal rays from the axis) ---
  const faceAt = (lat) => {
    let best = null;
    const y0 = Math.max(baseY + 0.3, pos.y + 0.05);
    for (let y = y0; y <= baseY + TP.maxHeight + 1e-6; y += 0.15) {
      origin.set(pos.x + lx * lat, y, pos.z + lz * lat);
      const h = world.raycast(origin, dir, maxReach + 0.05);
      if (!h) continue;
      const nh = Math.hypot(h.normal.x, h.normal.z);
      if (Math.abs(h.normal.y) > 0.35 || nh < 1e-6) continue;
      const nx = h.normal.x / nh;
      const nz = h.normal.z / nh;
      if (nx * mx + nz * mz > -cosFacing) continue;
      if (!best || h.distance < best.d) best = { d: h.distance, nx, nz, y, point: h.point };
    }
    return best;
  };

  // --- column probe: first surface going down at horizontal offset s along m (lateral lat) ---
  const column = (s, lat) => {
    // the horizontal path at topProbeY from the axis to the column must be free (else something tall
    // stands there: the down ray would start inside geometry)
    origin.set(pos.x + lx * lat, topProbeY, pos.z + lz * lat);
    if (world.raycast(origin, dir, s)) return { blocked: true };
    origin.set(pos.x + mx * s + lx * lat, topProbeY, pos.z + mz * s + lz * lat);
    // long enough to also see (and reject as too low) a floor far below the landing limit
    const h = world.raycast(origin, down, topProbeY - (baseY - TP.maxDropBehind - 2.5));
    if (!h) return { none: true };
    return { y: h.point.y, walkable: h.normal.y >= walkableCos - 1e-4 };
  };

  const face0 = faceAt(0);
  if (!face0) return { ok: false, reason: 'no_obstacle' };

  const lines = [0];
  if (o.nudge !== false) for (const n of TP.lateralNudges) lines.push(n, -n);
  let firstFail = null;
  for (const lat of lines) {
    const res = planLine(lat);
    if (res.ok) return res;
    if (!firstFail) firstFail = res;
    // sideways shifts only help when the straight path collided with something
    if (lat === 0 && !res.retry) return res;
  }
  return firstFail;

  function planLine(lat) {
    const face = lat === 0 ? face0 : faceAt(lat);
    if (!face) return { ok: false, reason: 'no_obstacle' };
    const D = face.d;
    // --- ledge top just past the face ---
    const c0 = column(D + 0.05, lat);
    if (c0.blocked) return { ok: false, reason: 'too_high' };
    if (c0.none) return { ok: false, reason: 'no_ledge' };
    if (!c0.walkable) return { ok: false, reason: 'ledge_not_walkable' };
    const topY = c0.y;
    const height = topY - baseY;
    if (topY < face.y - 1e-3) return { ok: false, reason: 'no_ledge' };
    if (height < TP.minHeight) return { ok: false, reason: 'too_low', detail: { height } };
    if (height > TP.maxHeight) return { ok: false, reason: 'too_high', detail: { height } };

    // --- depth of the top along m ---
    const same = (c) => !c.blocked && !c.none && c.walkable && Math.abs(c.y - topY) <= 0.08;
    const scanMax = D + Math.max(TP.vaultMaxThickness, TP.mantleMinDepth) + 0.45;
    let lastSame = D + 0.05;
    let back = null;
    let behindBlocked = false;
    for (let s = D + 0.1; s <= scanMax + 1e-9; s += 0.05) {
      const c = column(s, lat);
      if (same(c)) {
        lastSame = s;
        continue;
      }
      if (c.blocked) behindBlocked = true;
      // refine the back edge between lastSame and s
      let lo = lastSame;
      let hi = s;
      for (let k = 0; k < 6; k++) {
        const mid = (lo + hi) / 2;
        if (same(column(mid, lat))) lo = mid;
        else hi = mid;
      }
      back = (lo + hi) / 2;
      break;
    }
    const thickness = back === null ? Infinity : back - D;

    const eye0 = ctrl.eyeHeight;
    const tries = [];
    if (thickness <= TP.vaultMaxThickness && !behindBlocked) tries.push('vault');
    if (thickness >= TP.mantleMinDepth) tries.push('mantle');
    if (tries.length === 0) return { ok: false, reason: behindBlocked ? 'landing_blocked' : 'no_room_on_top', detail: { thickness } };

    let fail = null;
    for (const type of tries) {
      const res = buildAndValidate(type, lat, D, topY, height, thickness, back, face, eye0);
      if (res.ok) return res;
      if (!fail) fail = res;
    }
    return fail;
  }

  function buildAndValidate(type, lat, D, topY, height, thickness, back, face, eye0) {
    const y0 = pos.y;
    const yLift = topY + TP.lift;
    const s1 = Math.max(0, D - r - TP.gap);
    let T;
    let S;
    let Y;
    let endY;
    // keypoint times (seconds) from distances and speeds; normalised below
    const vH = Math.max(TP.minEntrySpeed, speed);
    const tRise = Math.max(s1 / vH, Math.max(0, yLift - y0) / TP.riseSpeed, 0.1);
    if (type === 'vault') {
      const s2 = back + r + TP.gap;
      const s3 = s2 + TP.landingExtra + TP.landingExtraPerSpeed * speed;
      const land = column(s3, lat);
      if (land.blocked) return { ok: false, reason: 'landing_blocked', retry: true };
      if (land.none || !land.walkable) return { ok: false, reason: 'landing_invalid', retry: true };
      if (land.y > topY - 0.3) return { ok: false, reason: 'landing_invalid', retry: true };
      if (land.y < baseY - TP.maxDropBehind) return { ok: false, reason: 'landing_too_low' };
      endY = land.y;
      const vCross = Math.min(TP.maxCrossSpeed, Math.max(TP.minCrossSpeed, TP.crossSpeedFactor * vH));
      const t2 = tRise + (s2 - s1) / vCross;
      const t3 = t2 + Math.max((s3 - s2) / vCross, (yLift - endY) / TP.dropSpeed, 0.1);
      T = [0, tRise, t2, t3];
      S = [0, s1, s2, s3];
      Y = [y0, yLift, yLift, endY];
    } else {
      const s2 = D + r + 0.08;
      endY = topY;
      const vM = Math.min(TP.maxMantleSpeed, Math.max(TP.minMantleSpeed, TP.mantleSpeedFactor * vH));
      T = [0, tRise, tRise + Math.max((s2 - s1) / vM, TP.minMantleCrossTime)];
      S = [0, s1, s2];
      Y = [y0, yLift, endY];
    }
    const natural = T[T.length - 1];
    for (let i = 0; i < T.length; i++) T[i] /= natural;
    const Lp = T.map((_, i) => (i === 0 ? 0 : lat));
    // duration: follows from the distances (faster with speed, longer for higher / deeper obstacles), clamped
    const duration = Math.min(TP.maxDuration, Math.max(TP.minDuration, natural));
    // keep the take-off speed as the initial slope of s (continuity), vertical from the current velocity
    const ms0 = Math.max(0, speed) * duration;
    const my0 = Math.max(0, ctrl.velocity.y) * duration;
    const plan = new TraversalPlan({
      type,
      duration,
      T,
      S,
      L: Lp,
      Y,
      ms0,
      my0,
      myN: type === 'mantle' ? 0 : null,
      x0: pos.x,
      z0: pos.z,
      mx,
      mz,
      lx,
      lz,
      lateral: lat,
      tuckHeight: TP.tuckHeight,
      tuckEye: TP.tuckEyeHeight,
      eye0,
      eyeEnd: ctrl.standEyeHeight,
      obstacleHeight: height,
      thickness,
      topY,
      ledgePoint: { x: pos.x + mx * D + lx * lat, y: topY, z: pos.z + mz * D + lz * lat },
      ledgeNormal: { x: face.nx, y: 0, z: face.nz },
      endStance: 'stand',
      exitSpeed: type === 'vault' ? Math.max(1.0, Math.min(speed, ctrl.params.speeds.run)) * TP.exitSpeedVault : TP.exitSpeedMantle,
    });

    // --- validate every sample of the path with the tucked capsule ---
    const p = new V();
    const q = new V();
    let length = 0;
    plan.positionAt(0, q);
    for (let i = 1; i <= 64; i++) {
      plan.positionAt(i / 64, p);
      length += p.distanceTo(q);
      q.copy(p);
    }
    const n = Math.max(16, Math.ceil(length / TP.sampleSpacing));
    const shrink = TP.planShrink;
    for (let i = 1; i <= n; i++) {
      const t = i / n;
      plan.positionAt(t, p);
      if (ctrl.overlaps(p, TP.tuckHeight, shrink)) {
        const seg = t <= T[1] ? 'rise' : t <= T[T.length - 2] ? 'cross' : 'land';
        return { ok: false, reason: `blocked_${seg}`, retry: true, detail: { t, at: [p.x, p.y, p.z] } };
      }
    }
    // --- end point: must hold the crouched capsule; stand if there is headroom ---
    plan.positionAt(1, p);
    if (ctrl.overlaps(p, ctrl.crouchHeight, shrink)) return { ok: false, reason: 'no_room_at_end', retry: true };
    if (ctrl.overlaps(p, ctrl.standHeight, shrink)) {
      plan.endStance = 'crouch';
      plan.eyeEnd = ctrl.crouchEyeHeight;
    }
    plan.pathLength = length;
    plan.samples = n;
    return { ok: true, plan };
  }
}
