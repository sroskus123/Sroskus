// Deterministic seeded PRNG (mulberry32). Used wherever gameplay needs randomness
// (recoil spread, effect variation) so that simulations are reproducible in tests.

export function createRng(seed = 1) {
  let state = seed >>> 0;
  const rng = {
    /** Uniform float in [0, 1). */
    next() {
      state = (state + 0x6d2b79f5) >>> 0;
      let t = state;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    },
    /** Uniform float in [min, max). */
    range(min, max) {
      return min + (max - min) * rng.next();
    },
    /** Uniform float in [-1, 1). */
    signed() {
      return rng.next() * 2 - 1;
    },
    getState() {
      return state;
    },
    setState(s) {
      state = s >>> 0;
    },
  };
  return rng;
}
