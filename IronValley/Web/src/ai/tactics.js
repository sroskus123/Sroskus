// Tactical queries shared by the bots: cover choice against a threat, positions inside the objective zone,
// and team spacing (teammates claim positions on a per-team board so they spread out instead of stacking).
// Cover points come from the bake (CoverService) and are reserved exclusively.

import { Vector3 } from 'three';

const DEG = Math.PI / 180;
const _a = new Vector3();
const _b = new Vector3();
const _dir = new Vector3();

export class TeamBoard {
  constructor() {
    this.claims = new Map(); // botId -> { team, pos: Vector3, kind }
  }
  claim(botId, team, pos, kind) {
    let c = this.claims.get(botId);
    if (!c) {
      c = { team, pos: new Vector3(), kind };
      this.claims.set(botId, c);
    }
    c.team = team;
    c.pos.copy(pos);
    c.kind = kind;
  }
  release(botId) {
    this.claims.delete(botId);
  }
  clear() {
    this.claims.clear();
  }
  /** Distance from p to the nearest claim of a teammate (excluding botId). */
  nearestTeammateClaim(botId, team, p) {
    let best = Infinity;
    for (const [id, c] of this.claims) {
      if (id === botId || c.team !== team) continue;
      const d = Math.hypot(c.pos.x - p.x, c.pos.z - p.z) + Math.abs(c.pos.y - p.y) * 2;
      if (d < best) best = d;
    }
    return best;
  }
}

/** Does cover point cp hide a body from a threat at `threat` (feet)? */
export function coverProtects(world, cp, threat, cfg, { crouched = cp.height === 'low' } = {}) {
  _dir.set(threat.x - cp.pos.x, 0, threat.z - cp.pos.z);
  const L = _dir.length();
  if (L < 1e-3) return false;
  _dir.divideScalar(L);
  // the obstacle lies in direction -normal: the threat must be beyond it
  const cosCone = Math.cos(cfg.cover.threatConeDeg * DEG);
  if (-(_dir.x * cp.normal.x + _dir.z * cp.normal.z) < cosCone) return false;
  // ray from the threat's eye to the exposed head of the bot at the cover point
  _a.set(threat.x, threat.y + 1.6, threat.z);
  _b.set(cp.pos.x, cp.pos.y + (crouched ? 1.05 : 1.62), cp.pos.z);
  _dir.subVectors(_b, _a);
  const d = _dir.length();
  _dir.divideScalar(d);
  return !!world.raycastStatic(_a, _dir, d - 0.05);
}

/** Can a bot fire at the threat from this cover (standing over low cover / from the peek position)? */
export function coverFirePosition(world, cp, threat) {
  const from = cp.height === 'low' || cp.window ? cp.pos : cp.peekPos;
  if (!from) return null;
  _a.set(from.x, from.y + 1.62, from.z);
  _b.set(threat.x, threat.y + 1.3, threat.z);
  _dir.subVectors(_b, _a);
  const d = _dir.length();
  _dir.divideScalar(d);
  return world.raycastStatic(_a, _dir, d - 0.3) ? null : from;
}

export class Tactics {
  constructor(sys) {
    this.sys = sys;
    this.board = new TeamBoard();
    this.stats = { coverSearches: 0, coverFound: 0, coverNone: 0 };
  }

  reset() {
    this.board.clear();
  }

  /**
   * Best free cover point for `bot` against `threat` (feet position estimate).
   * @param {object} o { center (search centre, default bot position), radius, requireFire, zone (prefer inside), exclude:Set }
   * @returns cover point or null (not reserved yet)
   */
  findCover(bot, threat, o = {}) {
    const sys = this.sys;
    const cfg = sys.cfg;
    const cover = sys.cover;
    const nav = sys.nav;
    this.stats.coverSearches++;
    if (!cover || !cover.points.length || !nav) return null;
    const pos = bot.c.position;
    const center = o.center || pos;
    const radius = o.radius ?? cfg.cover.searchRadius;
    const list = cover.query(center, radius, { dy: 3.5 });
    const scored = [];
    for (const cp of list) {
      if (!cover.isFree(cp.id, bot.c.id)) continue;
      if (o.exclude && o.exclude.has(cp.id)) continue;
      if (cp.solid && sys.shelterSolids.has(cp.solid)) continue; // never hide in a spawn shelter
      if (nav.isBlocked(cp.pos)) continue;
      const dThreat = Math.hypot(cp.pos.x - threat.x, cp.pos.z - threat.z);
      if (dThreat < cfg.cover.minThreatDistance) continue;
      // cheap direction pre-check (the LOS test follows for the best few)
      _dir.set(threat.x - cp.pos.x, 0, threat.z - cp.pos.z).normalize();
      if (-(_dir.x * cp.normal.x + _dir.z * cp.normal.z) < Math.cos(cfg.cover.threatConeDeg * DEG)) continue;
      const d = Math.hypot(cp.pos.x - pos.x, cp.pos.z - pos.z) + Math.abs(cp.pos.y - pos.y) * 2;
      let score = -d;
      if (cp.height === 'low' || cp.window || cp.peekPos) score += 3;
      if (o.zone) {
        const dz = Math.hypot(cp.pos.x - o.zone.center[0], cp.pos.z - o.zone.center[2]);
        score -= Math.max(0, dz - o.zone.radius + 0.5) * 0.8;
        if (o.urgent) {
          // the zone needs us: do not fall back away from it; under zone pressure prefer the cover that brings
          // the bot closer (bounding from cover to cover towards the zone)
          const dzBot = Math.hypot(pos.x - o.zone.center[0], pos.z - o.zone.center[2]);
          score -= Math.max(0, dz - dzBot) * 1.2;
          if (o.press > 0) score += Math.max(0, dzBot - dz) * 1.5 * o.press;
        }
      }
      const crowd = this.board.nearestTeammateClaim(bot.c.id, bot.c.team, cp.pos);
      if (crowd < cfg.cover.teammateSpacing) score -= (cfg.cover.teammateSpacing - crowd) * 4;
      // do not run past the threat to reach a cover
      if (dThreat > Math.hypot(pos.x - threat.x, pos.z - threat.z) + 6) score -= 4;
      scored.push({ cp, score });
    }
    scored.sort((u, v) => v.score - u.score);
    let checked = 0;
    for (const { cp } of scored) {
      if (checked++ >= 10) break;
      if (!coverProtects(sys.world, cp, threat, cfg)) continue;
      if (o.requireFire && !coverFirePosition(sys.world, cp, threat)) continue;
      const r = nav.findPath(pos, cp.pos);
      if (!r.ok) continue;
      const straight = Math.hypot(cp.pos.x - pos.x, cp.pos.z - pos.z);
      if (r.length > straight * 1.8 + 5) continue;
      this.stats.coverFound++;
      return cp;
    }
    this.stats.coverNone++;
    return null;
  }

  /** Is `bot` standing at its reserved cover point? */
  atCover(bot, cp, tol = 0.6) {
    if (!cp) return false;
    const p = bot.c.position;
    return Math.hypot(p.x - cp.pos.x, p.z - cp.pos.z) <= tol && Math.abs(p.y - cp.pos.y) < 1.0;
  }

  /**
   * A position to hold inside the active zone: a free cover point inside the zone that protects from
   * the enemy approach directions, else a random navmesh point in the zone; spaced from teammates.
   * @returns {{ pos: Vector3, cover: object|null }}
   */
  zonePost(bot, zone) {
    const sys = this.sys;
    const cfg = sys.cfg;
    const nav = sys.nav;
    const cover = sys.cover;
    const center = new Vector3(zone.center[0], zone.center[1], zone.center[2]);
    // polygon zones (generated maps): search the circumscribed disc, keep only points inside the polygon and z band
    const poly = Array.isArray(zone.polygon) && zone.polygon.length >= 3;
    const r = Math.max(1, zone.radius - (poly ? 0 : cfg.objective.zoneMargin));
    const dyC = poly ? Math.max(1.5, (zone.yMax ?? center.y + 3) - center.y + 0.5) : 1.5;
    if (poly) center.y = ((zone.yMin ?? center.y) + (zone.yMax ?? center.y + 3)) / 2;
    const inZone = (p) => !poly || sys.isInZone(p, zone);
    const threats = sys.enemySpawnCenters(bot.c.team);
    const cands = [];
    if (cover) {
      for (const cp of cover.query(center, r, { dy: dyC })) {
        if (!inZone(cp.pos)) continue;
        if (!cover.isFree(cp.id, bot.c.id) || (nav && nav.isBlocked(cp.pos))) continue;
        if (cp.solid && sys.shelterSolids.has(cp.solid)) continue;
        let prot = 0;
        for (const t of threats) {
          _dir.set(t.x - cp.pos.x, 0, t.z - cp.pos.z).normalize();
          if (-(_dir.x * cp.normal.x + _dir.z * cp.normal.z) > Math.cos(cfg.cover.threatConeDeg * DEG)) prot++;
        }
        cands.push({ pos: cp.pos, cover: cp, base: 2 + prot * 1.5 + (cp.height === 'low' ? 1 : 0) });
      }
    }
    if (nav) {
      for (let i = 0; i < (poly ? 24 : 8); i++) {
        const p = poly ? nav.randomPointNear(center, r, () => bot.rng.next(), { dy: dyC }) : nav.randomPointNear(center, r, () => bot.rng.next());
        if (p && (poly ? inZone(p) : Math.abs(p.y - center.y) < 1.2)) cands.push({ pos: p, cover: null, base: 0 });
      }
    }
    if (!cands.length) return { pos: center, cover: null };
    let best = null;
    let bestS = -Infinity;
    const bp = bot.c.position;
    for (const c of cands) {
      const crowd = this.board.nearestTeammateClaim(bot.c.id, bot.c.team, c.pos);
      let s = c.base - Math.hypot(c.pos.x - bp.x, c.pos.z - bp.z) * 0.08;
      if (crowd < cfg.objective.teamSpacing) s -= (cfg.objective.teamSpacing - crowd) * 5;
      else s += Math.min(crowd, 8) * 0.1;
      if (s > bestS) {
        bestS = s;
        best = c;
      }
    }
    return { pos: best.pos.clone(), cover: best.cover };
  }
}
