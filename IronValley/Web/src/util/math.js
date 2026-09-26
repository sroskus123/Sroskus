export const DEG2RAD = Math.PI / 180;
export const RAD2DEG = 180 / Math.PI;

export function clamp(v, lo, hi) {
  return v < lo ? lo : v > hi ? hi : v;
}

export function lerp(a, b, t) {
  return a + (b - a) * t;
}

/** Frame-rate independent exponential approach: returns factor in [0,1]. */
export function damp(rate, dt) {
  return 1 - Math.exp(-rate * dt);
}

/** Move `current` towards `target` by at most `maxDelta`. */
export function approach(current, target, maxDelta) {
  if (current < target) return Math.min(current + maxDelta, target);
  return Math.max(current - maxDelta, target);
}

/** Wrap an angle in radians to (-PI, PI]. */
export function wrapAngle(a) {
  a = (a + Math.PI) % (Math.PI * 2);
  if (a < 0) a += Math.PI * 2;
  return a - Math.PI;
}

/**
 * Converts a horizontal FOV (degrees) to the vertical FOV (degrees) that
 * three.js PerspectiveCamera expects, for the given aspect ratio.
 */
export function horizontalToVerticalFov(hFovDeg, aspect) {
  const h = hFovDeg * DEG2RAD;
  return 2 * Math.atan(Math.tan(h / 2) / aspect) * RAD2DEG;
}
