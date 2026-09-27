// Level registry: loads level data by id from src/data/<id>.json (schema: Docs/GAMEPLAY_CONTRACTS.md,
// section "Úroveň"). The dynamic import with a template literal is bundled by esbuild as a glob over
// src/data/*.json, so every level file present at build time is in the bundle; a missing id rejects.
// Works the same in Node (unit tests) and in the browser build. No DOM, no three.js.

import index from '../data/levels.json' with { type: 'json' };

const ID_RE = /^[a-z0-9_]+$/;

/** Validates the level schema and returns a list of problems (empty = usable). */
export function validateLevel(level, id = null) {
  const errs = [];
  if (!level || typeof level !== 'object') return ['level is not an object'];
  if (id !== null && level.id !== id) errs.push(`id "${level.id}" does not match file "${id}"`);
  // generated levels (Tools/level/export_web_level.py) carry their geometry in GLB files: `geometry` replaces solids
  const geo = level.geometry;
  if (geo !== undefined) {
    if (!geo || typeof geo.collision !== 'string' || typeof geo.terrain !== 'string' || !Array.isArray(geo.render) || geo.render.length === 0) {
      errs.push('geometry: { collision, terrain, render: [..] } asset paths required');
    }
    if (!Array.isArray(level.solids)) errs.push('solids: array required');
  } else if (!Array.isArray(level.solids) || level.solids.length === 0) errs.push('solids: non-empty array required');
  if (!level.markers || typeof level.markers !== 'object') errs.push('markers: object required');
  const m = level.match;
  if (m !== undefined) {
    if (!Array.isArray(m.teamSpawns) || m.teamSpawns.length === 0) errs.push('match.teamSpawns: array of team spawn lists required');
    else {
      m.teamSpawns.forEach((list, t) => {
        if (!Array.isArray(list) || list.length === 0) errs.push(`match.teamSpawns[${t}]: at least one point`);
        else list.forEach((s, i) => {
          if (!s || !Array.isArray(s.pos) || s.pos.length !== 3 || !s.pos.every(Number.isFinite)) errs.push(`match.teamSpawns[${t}][${i}].pos: [x, y, z] required`);
        });
      });
    }
    if (!Array.isArray(m.zones) || m.zones.length === 0) errs.push('match.zones: at least one zone');
    else {
      const seen = new Set();
      m.zones.forEach((z, i) => {
        if (!z || typeof z.id !== 'string' || !z.id) errs.push(`match.zones[${i}].id required`);
        else if (seen.has(z.id)) errs.push(`match.zones[${i}].id duplicate`);
        else seen.add(z.id);
        if (!z || !Array.isArray(z.center) || z.center.length !== 3 || !z.center.every(Number.isFinite)) errs.push(`match.zones[${i}].center: [x, y, z] required`);
        if (!z || !(z.radius > 0)) errs.push(`match.zones[${i}].radius > 0 required`);
        if (z && z.polygon !== undefined && (!Array.isArray(z.polygon) || z.polygon.length < 3 || !Number.isFinite(z.yMin) || !Number.isFinite(z.yMax) || z.yMax <= z.yMin)) {
          errs.push(`match.zones[${i}].polygon: >= 3 points [x, z] with yMin < yMax required`);
        }
      });
    }
  }
  return errs;
}

/**
 * Loads a level by id. Resolves to the parsed JSON (validated), rejects if it does not exist in the
 * build or is invalid.
 */
export async function loadLevelData(id) {
  if (typeof id !== 'string' || !ID_RE.test(id)) throw new Error(`Neplatné id úrovně: ${id}`);
  let mod;
  try {
    mod = await import(`../data/${id}.json`, { with: { type: 'json' } });
  } catch (err) {
    throw new Error(`Úroveň "${id}" v buildu není (src/data/${id}.json): ${err && err.message}`);
  }
  const level = mod.default ?? mod;
  const errs = validateLevel(level, id);
  if (errs.length) throw new Error(`Úroveň "${id}" je neplatná: ${errs.join('; ')}`);
  return level;
}

/** Levels from the index that actually exist in this build: [{id, name, hasMatch}]. */
export async function listAvailableLevels() {
  const out = [];
  for (const entry of index.list) {
    try {
      const lvl = await loadLevelData(entry.id);
      out.push({ id: entry.id, name: lvl.displayName || entry.name, hasMatch: !!lvl.match, tag: lvl.tag || null });
    } catch {
      /* not in this build */
    }
  }
  return out;
}

export const DEFAULT_LEVEL_ID = index.default;
