// Deterministicky generator (mulberry32, 32bit stav). Identicka implementace je v C++ (Core/include/ironvalley/core/rng.hpp);
// shodu overuji vektory Shared/testvectors/rng.json.

export class Rng {
  constructor(seed) {
    this.state = seed >>> 0;
  }

  /** Dalsi 32bitove cislo bez znamenka. */
  nextU32() {
    this.state = (this.state + 0x6d2b79f5) >>> 0;
    let t = this.state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return (t ^ (t >>> 14)) >>> 0;
  }

  /** Index v rozsahu [0, n) = floor(u32 * n / 2^32) (nasobeni a posun, bez zamitani); n je 1..2^32-1. */
  pickIndex(n) {
    if (!Number.isInteger(n) || n < 1 || n > 4294967295) throw new RangeError('pickIndex: n mimo rozsah');
    const u = this.nextU32();
    // Do 2^21 je soucin presny v double; nad tim presne pres BigInt (stejny vysledek jako 64bit nasobeni v C++).
    if (n <= 2097152) return Math.floor((u * n) / 4294967296);
    return Number((BigInt(u) * BigInt(n)) >> 32n);
  }

  /** Fisher-Yates: vrati permutaci 0..n-1. Pro n <= 1 nespotrebuje zadne cislo. */
  shuffledIndices(n) {
    const out = [];
    for (let i = 0; i < n; i += 1) out.push(i);
    for (let i = n - 1; i >= 1; i -= 1) {
      const j = this.pickIndex(i + 1);
      const tmp = out[i];
      out[i] = out[j];
      out[j] = tmp;
    }
    return out;
  }
}

/** Odvozeni druheho semene (napr. pro spawny) z hlavniho semene zapasu. */
export function deriveSeed(seed, salt) {
  return ((seed >>> 0) ^ (salt >>> 0)) >>> 0;
}

export const SPAWN_SEED_SALT = 0x9e3779b9;
