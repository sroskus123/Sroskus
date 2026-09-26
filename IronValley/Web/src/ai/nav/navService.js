// NavService (Docs/GAMEPLAY_CONTRACTS.md): path queries on the baked navmesh for bots.
//   findPath(from, to)          -> { ok, points: Vector3[], length, partial, reason }
//   closestPoint(p)             -> Vector3 | null
//   randomPointNear(p, r, rng)  -> Vector3 | null   (reachable from p)
//   isReachable(from, to)       -> bool
// plus temporary blocked areas (stuck recovery, AI-02): blockArea(center, radius, ttl) marks navmesh
// triangles as impassable for `ttl` seconds, so a path through an obstacle the navmesh does not know
// (closed door, barricade) is replaced by another route. Blocks are shared by all bots.
//
// The zone data is also registered in a three-pathfinding `Pathfinding` instance (format compatibility
// and reference queries); the searches themselves use NavMeshData (metric A*, funnel), see navMesh.js.

import { Vector3 } from 'three';
import { Pathfinding } from 'three-pathfinding/dist/three-pathfinding.modern.mjs';
import { NavMeshData } from './navMesh.js';

const ZONE_ID = 'level';

export class NavService {
  /**
   * @param {object} data baked navmesh JSON (public/assets/nav/<level>.json)
   * @param {object} [opts] { cornerOffset (m), now: () => seconds }
   */
  constructor(data, opts = {}) {
    this.mesh = new NavMeshData(data);
    this.data = data;
    this.cornerOffset = opts.cornerOffset ?? 0.2;
    this.time = 0;
    this.blocks = []; // { id, center: Vector3, radius, until, reason, nodes: Set }
    this._blockedNodes = new Map(); // node index -> count
    this._nextBlockId = 1;
    this.stats = { paths: 0, failed: 0, partial: 0, blocksAdded: 0 };
    // three-pathfinding zone (reference implementation, tests compare against it)
    this.pathfinding = new Pathfinding();
    this.pathfinding.setZoneData(ZONE_ID, { vertices: this.mesh.vertices, groups: this.mesh.groups });
    this.zoneId = ZONE_ID;
  }

  get mainGroup() {
    return this.mesh.mainGroup;
  }

  /** Advances the clock used for block expiry (call once per fixed tick). */
  update(dt) {
    this.time += dt;
    if (this.blocks.length && this.blocks.some((b) => b.until <= this.time)) {
      for (const b of this.blocks) if (b.until <= this.time) this._unmark(b);
      this.blocks = this.blocks.filter((b) => b.until > this.time);
    }
  }

  reset() {
    for (const b of this.blocks) this._unmark(b);
    this.blocks = [];
  }

  _unmark(b) {
    for (const n of b.nodes) {
      const c = (this._blockedNodes.get(n) || 0) - 1;
      if (c <= 0) this._blockedNodes.delete(n);
      else this._blockedNodes.set(n, c);
    }
  }

  /**
   * Marks the navmesh around `center` as impassable for `ttl` seconds. Returns the block id.
   * Nodes that contain `keepFree` points (e.g. the bot's own position) are not blocked.
   */
  blockArea(center, radius, ttl, { reason = 'stuck', keepFree = [] } = {}) {
    const c = center.clone ? center.clone() : new Vector3(center.x, center.y, center.z);
    const nodes = new Set(this.mesh.nodesInDisc(c, radius, { dy: 1.5 }));
    for (const p of keepFree) {
      const n = this.mesh.nodeAt(p);
      if (n >= 0) nodes.delete(n);
    }
    const b = { id: this._nextBlockId++, center: c, radius, until: this.time + ttl, reason, nodes };
    for (const n of nodes) this._blockedNodes.set(n, (this._blockedNodes.get(n) || 0) + 1);
    this.blocks.push(b);
    this.stats.blocksAdded++;
    return b.id;
  }

  isBlockedNode(n) {
    return this._blockedNodes.has(n);
  }

  /** Is p inside an active blocked area? */
  isBlocked(p) {
    const n = this.mesh.nodeAt(p);
    return n >= 0 && this._blockedNodes.has(n);
  }

  closestPoint(p, maxDist = 4) {
    const r = this.mesh.closestPoint(p, { maxDist, group: this.mesh.mainGroup });
    return r ? r.point : null;
  }

  /** Closest navmesh location as { point, node } in the main group, or null. */
  locate(p, maxDist = 4) {
    return this.mesh.closestPoint(p, { maxDist, group: this.mesh.mainGroup });
  }

  /**
   * Shortest path from `from` to `to` avoiding blocked areas. `points` excludes the start and ends at the
   * (navmesh-projected) goal. With { allowPartial: true } an unreachable goal yields the path to the
   * reachable node closest to the goal (partial = true).
   */
  findPath(from, to, { allowPartial = false, ignoreBlocks = false, cost = null } = {}) {
    this.stats.paths++;
    const s = this.locate(from, 3);
    const t = this.locate(to, 3);
    if (!s || !t) {
      this.stats.failed++;
      return { ok: false, points: [], length: 0, partial: false, reason: !s ? 'start_off_mesh' : 'goal_off_mesh' };
    }
    const blocked = ignoreBlocks || this._blockedNodes.size === 0 ? null : (n) => this._blockedNodes.has(n) && n !== s.node;
    let corridor = this.mesh.searchNodes(s.node, s.point, t.node, t.point, { blocked, cost });
    let goal = t.point;
    let partial = false;
    if (!corridor) {
      if (!allowPartial) {
        this.stats.failed++;
        return { ok: false, points: [], length: 0, partial: false, reason: 'unreachable' };
      }
      // partial: nearest reachable node to the goal (flood from start)
      const alt = this._nearestReachable(s.node, t.point, blocked);
      if (alt < 0) {
        this.stats.failed++;
        return { ok: false, points: [], length: 0, partial: false, reason: 'unreachable' };
      }
      goal = this.mesh.nodes[alt].centroid.clone();
      corridor = this.mesh.searchNodes(s.node, s.point, alt, goal, { blocked, cost });
      partial = true;
      this.stats.partial++;
      if (!corridor) return { ok: false, points: [], length: 0, partial: false, reason: 'unreachable' };
    }
    const raw = this.mesh.stringPull(corridor, s.point, goal);
    this._offsetCorners(raw);
    // drop coincident points (degenerate portals, offset corners that met)
    const pts = [raw[0]];
    for (let i = 1; i < raw.length; i++) {
      if (raw[i].distanceTo(pts[pts.length - 1]) > 0.05 || i === raw.length - 1) pts.push(raw[i]);
    }
    if (pts.length > 2 && pts[pts.length - 1].distanceTo(pts[pts.length - 2]) < 0.05) pts.splice(pts.length - 2, 1);
    let length = 0;
    for (let i = 1; i < pts.length; i++) length += pts[i].distanceTo(pts[i - 1]);
    pts.shift();
    return { ok: true, points: pts, length, partial, corridor, reason: null };
  }

  _nearestReachable(startNode, goal, blocked) {
    const mesh = this.mesh;
    const seen = new Set([startNode]);
    const queue = [startNode];
    let best = -1;
    let bestD = Infinity;
    while (queue.length) {
      const n = queue.shift();
      const node = mesh.nodes[n];
      const d = node.centroid.distanceTo(goal);
      if (d < bestD) {
        bestD = d;
        best = n;
      }
      const base = mesh.groups[node.group][0].index;
      for (const nb of node.neighbours) {
        const k = base + nb;
        if (seen.has(k) || (blocked && blocked(k))) continue;
        seen.add(k);
        queue.push(k);
      }
    }
    return best;
  }

  /** Moves interior path corners a little away from the obstacle corner they wrap around. */
  _offsetCorners(pts) {
    const d = this.cornerOffset;
    if (!(d > 0) || pts.length < 3) return;
    const a = new Vector3();
    const b = new Vector3();
    const cand = new Vector3();
    for (let i = 1; i < pts.length - 1; i++) {
      const k = pts[i];
      a.subVectors(pts[i - 1], k).setY(0);
      b.subVectors(pts[i + 1], k).setY(0);
      if (a.lengthSq() < 1e-6 || b.lengthSq() < 1e-6) continue;
      a.normalize();
      b.normalize();
      const sum = a.add(b);
      if (sum.lengthSq() < 1e-6) continue; // straight
      sum.normalize();
      cand.copy(k).addScaledVector(sum, -d);
      const n = this.mesh.nodeAt(cand, { above: 0.6, below: 0.6 });
      if (n >= 0 && this.mesh.segmentOnMesh(pts[i - 1], cand) && this.mesh.segmentOnMesh(cand, pts[i + 1])) k.copy(cand);
    }
  }

  /** Reference path from three-pathfinding (tests only; ignores blocks and uses its own A*). */
  referencePath(from, to) {
    const group = this.pathfinding.getGroup(ZONE_ID, from, true);
    return this.pathfinding.findPath(from, to, ZONE_ID, group);
  }

  isReachable(from, to) {
    const s = this.locate(from, 3);
    const t = this.locate(to, 3);
    if (!s || !t) return false;
    const blocked = this._blockedNodes.size === 0 ? null : (n) => this._blockedNodes.has(n) && n !== s.node;
    return !!this.mesh.searchNodes(s.node, s.point, t.node, t.point, { blocked });
  }

  /** Random reachable navmesh point within radius r of p (rng() in [0,1)). */
  randomPointNear(p, r, rng = Math.random, { tries = 12 } = {}) {
    const nodes = this.mesh.nodesInDisc(p, r, { dy: 1.5 }).filter((n) => this.mesh.nodes[n].group === this.mesh.mainGroup && !this._blockedNodes.has(n));
    if (!nodes.length) return null;
    const out = new Vector3();
    for (let i = 0; i < tries; i++) {
      const n = nodes[Math.floor(rng() * nodes.length)];
      this.mesh.randomPointInNode(n, rng, out);
      const dx = out.x - p.x;
      const dz = out.z - p.z;
      if (dx * dx + dz * dz <= r * r) return out.clone();
    }
    return null;
  }

  getDebug() {
    return {
      triangles: this.mesh.nodes.length,
      mainGroup: this.mesh.mainGroup,
      blocks: this.blocks.map((b) => ({ id: b.id, center: b.center.toArray().map((v) => +v.toFixed(2)), radius: b.radius, ttl: +(b.until - this.time).toFixed(2), reason: b.reason, nodes: b.nodes.size })),
      stats: { ...this.stats, searches: this.mesh.stats.searches, expanded: this.mesh.stats.expanded },
    };
  }
}

/** Convenience: NavService from baked JSON (or pass-through when already a service). */
export function createNavService(navOrData, opts) {
  if (!navOrData) return null;
  if (typeof navOrData.findPath === 'function') return navOrData;
  return new NavService(navOrData, opts);
}
