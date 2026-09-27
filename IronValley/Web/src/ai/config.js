// AI tunables: Shared/config/ai.json (data-driven, Docs/AI.md) + optional overrides (tests, debug).
// Overrides are a deep merge (objects merge, arrays and scalars replace).

import baseConfig from '../../../Shared/config/ai.json' with { type: 'json' };

export const AI_CONFIG = baseConfig;

function isObj(v) {
  return v && typeof v === 'object' && !Array.isArray(v);
}

export function deepMerge(base, patch) {
  if (!isObj(patch)) return patch === undefined ? base : patch;
  const out = isObj(base) ? { ...base } : {};
  for (const [k, v] of Object.entries(patch)) out[k] = isObj(v) && isObj(out[k]) ? deepMerge(out[k], v) : v;
  return out;
}

const REQUIRED = [
  'turnRateDegPerSec',
  'tick.perceptionHz',
  'tick.decisionHz',
  'vision.range',
  'vision.fovDeg',
  'vision.detectTimeNear',
  'vision.detectTimeFar',
  'hearing.gunshotRange',
  'hearing.footstepRange',
  'memory.decayTimeSeen',
  'aim.baseErrorDeg',
  'combat.reactionDelayMin',
  'combat.reactionDelayMax',
  'combat.bursts',
  'movement.arriveRadius',
  'stuck.window',
  'stuck.minProgress',
];

function get(o, path) {
  return path.split('.').reduce((a, k) => (a == null ? undefined : a[k]), o);
}

/** Merged and validated config (throws on missing / invalid required values). */
export function resolveAIConfig(overrides = null) {
  const cfg = overrides ? deepMerge(baseConfig, overrides) : deepMerge(baseConfig, {});
  const missing = REQUIRED.filter((p) => get(cfg, p) === undefined);
  if (missing.length) throw new Error(`ai.json: missing ${missing.join(', ')}`);
  if (!(cfg.combat.reactionDelayMin > 0) || cfg.combat.reactionDelayMax < cfg.combat.reactionDelayMin) {
    throw new Error('ai.json: combat.reactionDelayMin must be > 0 and <= reactionDelayMax (nonzero reaction time, AI-03)');
  }
  if (!(cfg.vision.detectTimeNear > 0)) throw new Error('ai.json: vision.detectTimeNear must be > 0');
  if (!Array.isArray(cfg.combat.bursts) || cfg.combat.bursts.length === 0) throw new Error('ai.json: combat.bursts must be a non-empty array');
  for (const b of cfg.combat.bursts) {
    if (!(b.shotsMin >= 1 && b.shotsMax >= b.shotsMin && b.pauseMax >= b.pauseMin && b.pauseMin >= 0)) throw new Error('ai.json: invalid burst band');
  }
  return cfg;
}
