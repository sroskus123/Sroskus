// Authoritative match / weapon rules for the browser build: Shared/config/rules.json compiled by the
// rules core (src/core/rules.js). Per-level and test patches are JSON Merge Patches (RFC 7386).

import baseRules from '../../../Shared/config/rules.json' with { type: 'json' };
import { compileRules, mergePatch } from '../core/rules.js';

export const BASE_RULES_RAW = baseRules;

let compiledBase = null;
/** Compiled base rules (cached, frozen). */
export function baseRulesCompiled() {
  if (!compiledBase) compiledBase = compileRules(baseRules);
  return compiledBase;
}

/**
 * Rules for a match on `level`: the level's zones become zone.locations (so the core picks the active
 * zone among the level's three candidates), then an optional extra patch (tests only).
 */
export function buildMatchRules(level, extraPatch = null) {
  let raw = JSON.parse(JSON.stringify(baseRules));
  if (level && level.match && Array.isArray(level.match.zones) && level.match.zones.length > 0) {
    raw = mergePatch(raw, { zone: { locations: level.match.zones.map((z) => ({ id: z.id, name: z.name || z.id })) } });
  }
  if (extraPatch) raw = mergePatch(raw, extraPatch);
  return compileRules(raw);
}
