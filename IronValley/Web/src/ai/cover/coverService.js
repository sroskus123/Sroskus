// CoverService (Docs/GAMEPLAY_CONTRACTS.md): cover points generated from level geometry at bake time
// (tools/bake_navmesh.mjs) and exclusive reservation, so no two bots ever hold the same point (AI-02).
//   points: [{ id, pos: Vector3, normal: Vector3 (away from the obstacle), height: 'low'|'high',
//              top, window, peek, peekPos: Vector3|null }]
//   reserve(botId, coverId) -> bool (false if another bot holds it); a bot holds at most one point
//   release(botId), holderOf(coverId), reservedBy(botId), query(center, radius)

import { Vector3 } from 'three';

export class CoverService {
  /** @param {object[]} points baked cover points (arrays) or already converted objects */
  constructor(points = []) {
    this.points = points.map((p) => ({
      id: p.id,
      pos: toVec(p.pos),
      normal: toVec(p.normal).setY(0).normalize(),
      height: p.height === 'high' ? 'high' : 'low',
      top: p.top ?? (p.height === 'high' ? 2.0 : 1.0),
      window: !!p.window,
      peek: p.peek || 'none',
      peekPos: p.peekPos ? toVec(p.peekPos) : null,
      solid: p.solid || null,
    }));
    this.byId = new Map(this.points.map((p) => [p.id, p]));
    this.holder = new Map(); // coverId -> botId
    this.byBot = new Map(); // botId -> coverId
    this.cell = 4;
    this.grid = new Map();
    for (const p of this.points) {
      const k = this._key(Math.floor(p.pos.x / this.cell), Math.floor(p.pos.z / this.cell));
      if (!this.grid.has(k)) this.grid.set(k, []);
      this.grid.get(k).push(p);
    }
    this.stats = { reservations: 0, conflictsRejected: 0 };
  }

  _key(cx, cz) {
    return `${cx},${cz}`;
  }

  get(id) {
    return this.byId.get(id) || null;
  }

  /** Cover points within `radius` (XZ) of center and within dy vertically. */
  query(center, radius, { dy = 2.0 } = {}) {
    const out = [];
    const c0x = Math.floor((center.x - radius) / this.cell);
    const c1x = Math.floor((center.x + radius) / this.cell);
    const c0z = Math.floor((center.z - radius) / this.cell);
    const c1z = Math.floor((center.z + radius) / this.cell);
    const r2 = radius * radius;
    for (let cz = c0z; cz <= c1z; cz++) {
      for (let cx = c0x; cx <= c1x; cx++) {
        const list = this.grid.get(this._key(cx, cz));
        if (!list) continue;
        for (const p of list) {
          const dx = p.pos.x - center.x;
          const dz = p.pos.z - center.z;
          if (dx * dx + dz * dz <= r2 && Math.abs(p.pos.y - center.y) <= dy) out.push(p);
        }
      }
    }
    return out;
  }

  holderOf(coverId) {
    return this.holder.get(coverId) ?? null;
  }

  reservedBy(botId) {
    const id = this.byBot.get(botId);
    return id ? this.byId.get(id) : null;
  }

  isFree(coverId, botId = null) {
    const h = this.holder.get(coverId);
    return h === undefined || h === botId;
  }

  /** Exclusive reservation. A bot's previous reservation is released first. */
  reserve(botId, coverId) {
    if (!this.byId.has(coverId)) return false;
    const h = this.holder.get(coverId);
    if (h !== undefined && h !== botId) {
      this.stats.conflictsRejected++;
      return false;
    }
    if (h === botId) return true;
    this.release(botId);
    this.holder.set(coverId, botId);
    this.byBot.set(botId, coverId);
    this.stats.reservations++;
    return true;
  }

  release(botId) {
    const id = this.byBot.get(botId);
    if (id === undefined) return;
    this.byBot.delete(botId);
    if (this.holder.get(id) === botId) this.holder.delete(id);
  }

  releaseAll() {
    this.holder.clear();
    this.byBot.clear();
  }

  /** Current reservations as [{ coverId, botId }] (debug / tests). */
  reservations() {
    return [...this.holder.entries()].map(([coverId, botId]) => ({ coverId, botId }));
  }
}

function toVec(a) {
  if (!a) return new Vector3();
  if (Array.isArray(a)) return new Vector3(a[0], a[1], a[2]);
  return new Vector3(a.x, a.y, a.z);
}

/** Convenience: CoverService from baked nav JSON (uses data.cover) or pass-through. */
export function createCoverService(coverOrData) {
  if (!coverOrData) return new CoverService([]);
  if (typeof coverOrData.reserve === 'function') return coverOrData;
  if (Array.isArray(coverOrData)) return new CoverService(coverOrData);
  if (Array.isArray(coverOrData.cover)) return new CoverService(coverOrData.cover);
  return new CoverService([]);
}
