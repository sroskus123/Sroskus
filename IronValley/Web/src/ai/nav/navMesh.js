// Runtime navmesh (pure JS, no WebAssembly). The mesh is baked at build time by tools/bake_navmesh.mjs
// (Recast in Node) and shipped as JSON in the three-pathfinding zone format ({ vertices, groups }).
// This module restores the zone (Vector3 vertices / centroids) for three-pathfinding and adds what a
// crowd of bots needs on top of it:
//   - a uniform XZ grid of triangles for fast point location / closest point queries,
//   - metric A* (edge cost = distance between portal midpoints, heuristic = straight distance,
//     optional per-node cost multipliers and blocked nodes),
//   - string pulling (simple stupid funnel) with explicit left/right portal orientation, so the result
//     does not depend on the triangle winding of the baked mesh.
// three-pathfinding 1.3.0 is used for the zone format and as a reference (see NavService), but its A*
// counts polygons (cost 1 per node) with a squared-distance heuristic, which is not a shortest path and
// cannot exclude blocked areas; that is why the search here is our own.

import { Vector3 } from 'three';

const EPS = 1e-9;

/** Signed doubled area of (a, b, c) in XZ (same convention as three-pathfinding / Mononen). */
export function triarea2(a, b, c) {
  const ax = b.x - a.x;
  const az = b.z - a.z;
  const bx = c.x - a.x;
  const bz = c.z - a.z;
  return bx * az - ax * bz;
}

function vequal(a, b) {
  const dx = a.x - b.x;
  const dz = a.z - b.z;
  return dx * dx + dz * dz < 1e-8;
}

/** Barycentric point-in-triangle test in XZ (inclusive, with tolerance in metres). */
export function pointInTriXZ(px, pz, a, b, c, tol = 1e-4) {
  const v0x = c.x - a.x;
  const v0z = c.z - a.z;
  const v1x = b.x - a.x;
  const v1z = b.z - a.z;
  const v2x = px - a.x;
  const v2z = pz - a.z;
  const d00 = v0x * v0x + v0z * v0z;
  const d01 = v0x * v1x + v0z * v1z;
  const d02 = v0x * v2x + v0z * v2z;
  const d11 = v1x * v1x + v1z * v1z;
  const d12 = v1x * v2x + v1z * v2z;
  const den = d00 * d11 - d01 * d01;
  if (Math.abs(den) < EPS) return false;
  const u = (d11 * d02 - d01 * d12) / den;
  const v = (d00 * d12 - d01 * d02) / den;
  // tolerance converted roughly to barycentric units using the triangle size
  const size = Math.sqrt(Math.max(d00, d11));
  const t = tol / Math.max(size, 1e-6);
  return u >= -t && v >= -t && u + v <= 1 + t;
}

/** Height of the triangle plane at (x, z). */
function heightOnTri(x, z, a, b, c) {
  const abx = b.x - a.x;
  const aby = b.y - a.y;
  const abz = b.z - a.z;
  const acx = c.x - a.x;
  const acy = c.y - a.y;
  const acz = c.z - a.z;
  const nx = aby * acz - abz * acy;
  const ny = abz * acx - abx * acz;
  const nz = abx * acy - aby * acx;
  if (Math.abs(ny) < EPS) return (a.y + b.y + c.y) / 3;
  return a.y - (nx * (x - a.x) + nz * (z - a.z)) / ny;
}

/** Closest point on segment ab to p in XZ; writes into out (y interpolated). Returns squared XZ distance. */
function closestOnSegXZ(px, pz, a, b, out) {
  const dx = b.x - a.x;
  const dz = b.z - a.z;
  const L = dx * dx + dz * dz;
  let t = L > EPS ? ((px - a.x) * dx + (pz - a.z) * dz) / L : 0;
  t = t < 0 ? 0 : t > 1 ? 1 : t;
  out.set(a.x + dx * t, a.y + (b.y - a.y) * t, a.z + dz * t);
  const ex = out.x - px;
  const ez = out.z - pz;
  return ex * ex + ez * ez;
}

/** Minimal binary heap keyed by a Float64Array of scores. */
class NodeHeap {
  constructor() {
    this.items = [];
  }
  clear() {
    this.items.length = 0;
  }
  get size() {
    return this.items.length;
  }
  push(id, f) {
    const it = this.items;
    it.push([id, f]);
    let i = it.length - 1;
    while (i > 0) {
      const p = (i - 1) >> 1;
      if (it[p][1] <= it[i][1]) break;
      [it[p], it[i]] = [it[i], it[p]];
      i = p;
    }
  }
  pop() {
    const it = this.items;
    const top = it[0];
    const last = it.pop();
    if (it.length > 0) {
      it[0] = last;
      let i = 0;
      for (;;) {
        const l = 2 * i + 1;
        const r = l + 1;
        let m = i;
        if (l < it.length && it[l][1] < it[m][1]) m = l;
        if (r < it.length && it[r][1] < it[m][1]) m = r;
        if (m === i) break;
        [it[m], it[i]] = [it[i], it[m]];
        i = m;
      }
    }
    return top;
  }
}

export class NavMeshData {
  /**
   * @param {object} data baked JSON (tools/bake_navmesh.mjs): { zone: { vertices: number[], groups: Node[][] }, ... }
   */
  constructor(data) {
    if (!data || !data.zone || !Array.isArray(data.zone.vertices) || !Array.isArray(data.zone.groups)) {
      throw new Error('NavMeshData: invalid navmesh data (missing zone)');
    }
    this.data = data;
    const flat = data.zone.vertices;
    this.vertices = new Array(flat.length / 3);
    for (let i = 0; i < this.vertices.length; i++) this.vertices[i] = new Vector3(flat[i * 3], flat[i * 3 + 1], flat[i * 3 + 2]);
    // global node list: node index = running index over all groups
    this.nodes = [];
    this.groups = data.zone.groups.map((g, gi) => {
      const base = this.nodes.length;
      const out = g.map((n) => {
        const c = n.centroid;
        const node = {
          id: n.id,
          index: base + n.id,
          group: gi,
          neighbours: n.neighbours,
          vertexIds: n.vertexIds,
          portals: n.portals,
          centroid: Array.isArray(c) ? new Vector3(c[0], c[1], c[2]) : new Vector3(c.x, c.y, c.z),
        };
        return node;
      });
      for (const n of out) this.nodes.push(n);
      return out;
    });
    this.mainGroup = Number.isInteger(data.mainGroup) ? data.mainGroup : this._largestGroup();
    // per-node triangle bounds and grid
    const N = this.nodes.length;
    this.minX = new Float64Array(N);
    this.maxX = new Float64Array(N);
    this.minZ = new Float64Array(N);
    this.maxZ = new Float64Array(N);
    this.minY = new Float64Array(N);
    this.maxY = new Float64Array(N);
    let bx0 = Infinity;
    let bz0 = Infinity;
    let bx1 = -Infinity;
    let bz1 = -Infinity;
    for (const n of this.nodes) {
      const [a, b, c] = n.vertexIds.map((i) => this.vertices[i]);
      const i = n.index;
      this.minX[i] = Math.min(a.x, b.x, c.x);
      this.maxX[i] = Math.max(a.x, b.x, c.x);
      this.minZ[i] = Math.min(a.z, b.z, c.z);
      this.maxZ[i] = Math.max(a.z, b.z, c.z);
      this.minY[i] = Math.min(a.y, b.y, c.y);
      this.maxY[i] = Math.max(a.y, b.y, c.y);
      bx0 = Math.min(bx0, this.minX[i]);
      bz0 = Math.min(bz0, this.minZ[i]);
      bx1 = Math.max(bx1, this.maxX[i]);
      bz1 = Math.max(bz1, this.maxZ[i]);
    }
    this.cell = 2.0;
    this.gx0 = Math.floor(bx0) - 1;
    this.gz0 = Math.floor(bz0) - 1;
    this.gw = Math.max(1, Math.ceil((bx1 - this.gx0 + 1) / this.cell));
    this.gh = Math.max(1, Math.ceil((bz1 - this.gz0 + 1) / this.cell));
    this.grid = new Array(this.gw * this.gh);
    for (let k = 0; k < this.grid.length; k++) this.grid[k] = [];
    for (const n of this.nodes) {
      const i = n.index;
      const cx0 = this._cx(this.minX[i]);
      const cx1 = this._cx(this.maxX[i]);
      const cz0 = this._cz(this.minZ[i]);
      const cz1 = this._cz(this.maxZ[i]);
      for (let cz = cz0; cz <= cz1; cz++) for (let cx = cx0; cx <= cx1; cx++) this.grid[cz * this.gw + cx].push(i);
    }
    // A* scratch
    this._g = new Float64Array(N);
    this._stamp = new Uint32Array(N);
    this._closed = new Uint32Array(N);
    this._parent = new Int32Array(N);
    this._entry = new Array(N); // entry point (portal midpoint) per node
    for (let k = 0; k < N; k++) this._entry[k] = new Vector3();
    this._search = 0;
    this._visited = new Uint32Array(N);
    this._visitStamp = 0;
    this._heap = new NodeHeap();
    this._tmp = new Vector3();
    this._tmp2 = new Vector3();
    this.stats = { searches: 0, expanded: 0 };
  }

  _largestGroup() {
    let best = 0;
    this.data.zone.groups.forEach((g, i) => {
      if (g.length > this.data.zone.groups[best].length) best = i;
    });
    return best;
  }

  _cx(x) {
    return Math.min(this.gw - 1, Math.max(0, Math.floor((x - this.gx0) / this.cell)));
  }

  _cz(z) {
    return Math.min(this.gh - 1, Math.max(0, Math.floor((z - this.gz0) / this.cell)));
  }

  triangle(nodeIndex) {
    const n = this.nodes[nodeIndex];
    return [this.vertices[n.vertexIds[0]], this.vertices[n.vertexIds[1]], this.vertices[n.vertexIds[2]]];
  }

  /**
   * Node whose triangle contains (x, z) in XZ with the surface closest to y (within [y - below, y + above]
   * of the surface). Returns -1 if none.
   */
  nodeAt(p, { above = 1.2, below = 0.6, group = null } = {}) {
    const cx = this._cx(p.x);
    const cz = this._cz(p.z);
    if (p.x < this.gx0 || p.z < this.gz0) return -1;
    const list = this.grid[cz * this.gw + cx];
    let best = -1;
    let bestDy = Infinity;
    for (const i of list) {
      if (p.x < this.minX[i] - 1e-3 || p.x > this.maxX[i] + 1e-3 || p.z < this.minZ[i] - 1e-3 || p.z > this.maxZ[i] + 1e-3) continue;
      if (group !== null && this.nodes[i].group !== group) continue;
      const [a, b, c] = this.triangle(i);
      if (!pointInTriXZ(p.x, p.z, a, b, c, 1e-3)) continue;
      const h = heightOnTri(p.x, p.z, a, b, c);
      const dy = p.y - h;
      if (dy > above || dy < -below) continue;
      const ady = Math.abs(dy);
      if (ady < bestDy) {
        bestDy = ady;
        best = i;
      }
    }
    return best;
  }

  /**
   * Closest point on the navmesh. Distance metric: horizontal distance plus vertical distance weighted by
   * `yWeight` (a point on the floor below beats a point on the floor above). Returns
   * { point: Vector3, node, distance } or null when nothing is within maxDist.
   */
  closestPoint(p, { maxDist = 4, yWeight = 2, group = null, out = null } = {}) {
    const inside = this.nodeAt(p, { group });
    if (inside >= 0) {
      const [a, b, c] = this.triangle(inside);
      const pt = (out || new Vector3()).set(p.x, heightOnTri(p.x, p.z, a, b, c), p.z);
      return { point: pt, node: inside, distance: Math.abs(p.y - pt.y) };
    }
    const r = Math.ceil(maxDist / this.cell);
    const cx = this._cx(p.x);
    const cz = this._cz(p.z);
    let best = -1;
    let bestD = maxDist * maxDist;
    const bestP = this._tmp2;
    const cand = this._tmp;
    const stamp = ++this._visitStamp;
    const visited = this._visited;
    for (let dz = -r; dz <= r; dz++) {
      for (let dx = -r; dx <= r; dx++) {
        const gx = cx + dx;
        const gz = cz + dz;
        if (gx < 0 || gz < 0 || gx >= this.gw || gz >= this.gh) continue;
        for (const i of this.grid[gz * this.gw + gx]) {
          if (visited[i] === stamp) continue;
          visited[i] = stamp;
          if (group !== null && this.nodes[i].group !== group) continue;
          const [a, b, c] = this.triangle(i);
          // closest point: inside in XZ -> vertical projection, else closest point on the edges
          let d2;
          if (pointInTriXZ(p.x, p.z, a, b, c, 0)) {
            cand.set(p.x, heightOnTri(p.x, p.z, a, b, c), p.z);
            const dy = (p.y - cand.y) * yWeight;
            d2 = dy * dy;
          } else {
            let h = closestOnSegXZ(p.x, p.z, a, b, cand);
            let bx = cand.x;
            let by = cand.y;
            let bz = cand.z;
            const t2 = closestOnSegXZ(p.x, p.z, b, c, cand);
            if (t2 < h) {
              h = t2;
              bx = cand.x;
              by = cand.y;
              bz = cand.z;
            }
            const t3 = closestOnSegXZ(p.x, p.z, c, a, cand);
            if (t3 < h) {
              h = t3;
              bx = cand.x;
              by = cand.y;
              bz = cand.z;
            }
            cand.set(bx, by, bz);
            const dy = (p.y - by) * yWeight;
            d2 = h + dy * dy;
          }
          if (d2 < bestD) {
            bestD = d2;
            best = i;
            bestP.copy(cand);
          }
        }
      }
    }
    if (best < 0) return null;
    const pt = (out || new Vector3()).copy(bestP);
    // nudge a point on the boundary slightly into its triangle so nodeAt() finds it again
    const n = this.nodes[best];
    pt.lerp(n.centroid, 0.002);
    return { point: pt, node: best, distance: Math.sqrt(bestD) };
  }

  /** Portal (shared edge) between two adjacent nodes as [Vector3, Vector3], or null. */
  portal(fromIndex, toIndex) {
    const a = this.nodes[fromIndex];
    const b = this.nodes[toIndex];
    if (a.group !== b.group) return null;
    const k = a.neighbours.indexOf(b.id);
    if (k < 0) return null;
    const pr = a.portals[k];
    if (!pr || pr.length < 2) return null;
    return [this.vertices[pr[0]], this.vertices[pr[1]]];
  }

  /**
   * Metric A* from node s (at point sp) to node t (at point tp).
   * @param {object} opts { blocked?: (nodeIndex)=>boolean, cost?: (nodeIndex)=>number multiplier, maxExpand }
   * @returns {number[]|null} node indices from s to t, or null when unreachable
   */
  searchNodes(s, sp, t, tp, opts = {}) {
    const ns = this.nodes[s];
    const nt = this.nodes[t];
    if (!ns || !nt || ns.group !== nt.group) return null;
    if (s === t) return [s];
    const blocked = opts.blocked || null;
    const costMul = opts.cost || null;
    const maxExpand = opts.maxExpand ?? 20000;
    this.stats.searches++;
    const search = ++this._search;
    const g = this._g;
    const stamp = this._stamp;
    const closed = this._closed;
    const parent = this._parent;
    const entry = this._entry;
    const heap = this._heap;
    heap.clear();
    g[s] = 0;
    stamp[s] = search;
    parent[s] = -1;
    entry[s].copy(sp);
    heap.push(s, sp.distanceTo(tp));
    const group = this.groups[ns.group];
    const base = group[0].index;
    let expanded = 0;
    while (heap.size > 0) {
      const [cur, f] = heap.pop();
      if (closed[cur] === search) continue;
      if (f - g[cur] < -1e-6) continue;
      closed[cur] = search;
      if (cur === t) break;
      if (++expanded > maxExpand) return null;
      const node = this.nodes[cur];
      const ep = entry[cur];
      for (let k = 0; k < node.neighbours.length; k++) {
        const nb = base + node.neighbours[k];
        if (closed[nb] === search) continue;
        if (blocked && nb !== t && blocked(nb)) continue;
        const pr = node.portals[k];
        const va = this.vertices[pr[0]];
        const vb = this.vertices[pr[1]];
        // entry point into nb: portal midpoint (target node: the target point itself is used for h)
        const mx = (va.x + vb.x) * 0.5;
        const my = (va.y + vb.y) * 0.5;
        const mz = (va.z + vb.z) * 0.5;
        let step = Math.hypot(mx - ep.x, (my - ep.y) * 1.0, mz - ep.z);
        if (costMul) step *= costMul(nb);
        const ng = g[cur] + step;
        if (stamp[nb] !== search || ng < g[nb] - 1e-9) {
          stamp[nb] = search;
          g[nb] = ng;
          parent[nb] = cur;
          entry[nb].set(mx, my, mz);
          const h = nb === t ? Math.hypot(tp.x - mx, tp.y - my, tp.z - mz) : Math.hypot(tp.x - mx, tp.y - my, tp.z - mz);
          heap.push(nb, ng + h);
        }
      }
    }
    this.stats.expanded += expanded;
    if (closed[t] !== search) return null;
    const out = [];
    for (let c = t; c !== -1; c = parent[c]) out.push(c);
    out.reverse();
    return out;
  }

  /**
   * String pulling over a node corridor (simple stupid funnel). Portal endpoints are ordered left/right
   * relative to the travel direction explicitly, so the winding of the baked triangles does not matter.
   * @returns {Vector3[]} points from start to end (both included)
   */
  stringPull(corridor, start, end) {
    const portals = [{ left: start, right: start }];
    for (let i = 0; i + 1 < corridor.length; i++) {
      const pr = this.portal(corridor[i], corridor[i + 1]);
      if (!pr) continue;
      const c0 = this.nodes[corridor[i]].centroid;
      let [l, r] = pr;
      // convention of the funnel below (Mononen): triarea2(from, left, right) > 0
      if (triarea2(c0, l, r) < 0) [l, r] = [r, l];
      portals.push({ left: l, right: r });
    }
    portals.push({ left: end, right: end });

    const pts = [start.clone()];
    const pushCorner = (v) => {
      const last = pts[pts.length - 1];
      if (!vequal(last, v) || Math.abs(last.y - v.y) > 1e-3) pts.push(v.clone());
    };
    let apex = portals[0].left;
    let pl = portals[0].left;
    let pr = portals[0].right;
    let apexIndex = 0;
    let leftIndex = 0;
    let rightIndex = 0;
    for (let i = 1; i < portals.length; i++) {
      const left = portals[i].left;
      const right = portals[i].right;
      // update right vertex
      if (triarea2(apex, pr, right) <= 0) {
        if (vequal(apex, pr) || triarea2(apex, pl, right) > 0) {
          pr = right;
          rightIndex = i;
        } else {
          pushCorner(pl);
          apex = pl;
          apexIndex = leftIndex;
          pl = apex;
          pr = apex;
          leftIndex = apexIndex;
          rightIndex = apexIndex;
          i = apexIndex;
          continue;
        }
      }
      // update left vertex
      if (triarea2(apex, pl, left) >= 0) {
        if (vequal(apex, pl) || triarea2(apex, pr, left) < 0) {
          pl = left;
          leftIndex = i;
        } else {
          pushCorner(pr);
          apex = pr;
          apexIndex = rightIndex;
          pl = apex;
          pr = apex;
          leftIndex = apexIndex;
          rightIndex = apexIndex;
          i = apexIndex;
          continue;
        }
      }
    }
    const last = pts[pts.length - 1];
    if (!vequal(last, end) || Math.abs(last.y - end.y) > 1e-3) pts.push(end.clone());
    return pts;
  }

  /** Is the XZ segment a->b entirely on the navmesh (sampled every `step` metres)? */
  segmentOnMesh(a, b, { step = 0.25, group = null } = {}) {
    const d = Math.hypot(b.x - a.x, b.z - a.z);
    const n = Math.max(1, Math.ceil(d / step));
    const p = this._tmp;
    for (let i = 0; i <= n; i++) {
      const t = i / n;
      p.set(a.x + (b.x - a.x) * t, a.y + (b.y - a.y) * t, a.z + (b.z - a.z) * t);
      if (this.nodeAt(p, { above: 1.0, below: 1.0, group }) < 0) return false;
    }
    return true;
  }

  /** Area-weighted random point on a node (rng() -> [0,1)). */
  randomPointInNode(nodeIndex, rng, out = new Vector3()) {
    const [a, b, c] = this.triangle(nodeIndex);
    let u = rng();
    let v = rng();
    if (u + v > 1) {
      u = 1 - u;
      v = 1 - v;
    }
    return out.set(a.x + (b.x - a.x) * u + (c.x - a.x) * v, a.y + (b.y - a.y) * u + (c.y - a.y) * v, a.z + (b.z - a.z) * u + (c.z - a.z) * v);
  }

  /** Nodes whose triangle intersects the XZ disc (center, radius) and whose height is near center.y. */
  nodesInDisc(center, radius, { dy = 2.0 } = {}) {
    const out = [];
    const cx0 = this._cx(center.x - radius);
    const cx1 = this._cx(center.x + radius);
    const cz0 = this._cz(center.z - radius);
    const cz1 = this._cz(center.z + radius);
    const seen = new Set();
    const tmp = this._tmp;
    for (let cz = cz0; cz <= cz1; cz++) {
      for (let cx = cx0; cx <= cx1; cx++) {
        for (const i of this.grid[cz * this.gw + cx]) {
          if (seen.has(i)) continue;
          seen.add(i);
          if (this.maxY[i] < center.y - dy || this.minY[i] > center.y + dy) continue;
          const [a, b, c] = this.triangle(i);
          let hit = pointInTriXZ(center.x, center.z, a, b, c, 0);
          if (!hit) {
            const r2 = radius * radius;
            hit = closestOnSegXZ(center.x, center.z, a, b, tmp) <= r2 || closestOnSegXZ(center.x, center.z, b, c, tmp) <= r2 || closestOnSegXZ(center.x, center.z, c, a, tmp) <= r2;
          }
          if (hit) out.push(i);
        }
      }
    }
    return out;
  }

  /**
   * Nodes whose triangle overlaps the XZ rectangle [minX, maxX] x [minZ, maxZ] (separating-axis test,
   * touching counts as no overlap) and whose height range meets [yMin, yMax].
   */
  nodesInRect(minX, minZ, maxX, maxZ, { yMin = -Infinity, yMax = Infinity } = {}) {
    const out = [];
    if (!(maxX > minX) || !(maxZ > minZ)) return out;
    const cx0 = this._cx(minX);
    const cx1 = this._cx(maxX);
    const cz0 = this._cz(minZ);
    const cz1 = this._cz(maxZ);
    const seen = new Set();
    const rect = [
      [minX, minZ],
      [maxX, minZ],
      [maxX, maxZ],
      [minX, maxZ],
    ];
    for (let cz = cz0; cz <= cz1; cz++) {
      for (let cx = cx0; cx <= cx1; cx++) {
        for (const i of this.grid[cz * this.gw + cx]) {
          if (seen.has(i)) continue;
          seen.add(i);
          if (this.maxY[i] < yMin || this.minY[i] > yMax) continue;
          if (this.maxX[i] <= minX || this.minX[i] >= maxX || this.maxZ[i] <= minZ || this.minZ[i] >= maxZ) continue;
          const [a, b, c] = this.triangle(i);
          const tri = [
            [a.x, a.z],
            [b.x, b.z],
            [c.x, c.z],
          ];
          // SAT: the rectangle axes are covered by the bounds test above; test the 3 triangle edge normals
          let separated = false;
          for (let k = 0; k < 3 && !separated; k++) {
            const p0 = tri[k];
            const p1 = tri[(k + 1) % 3];
            const nx = p1[1] - p0[1];
            const nz = -(p1[0] - p0[0]);
            let tMin = Infinity;
            let tMax = -Infinity;
            for (const q of tri) {
              const d = q[0] * nx + q[1] * nz;
              if (d < tMin) tMin = d;
              if (d > tMax) tMax = d;
            }
            let rMin = Infinity;
            let rMax = -Infinity;
            for (const q of rect) {
              const d = q[0] * nx + q[1] * nz;
              if (d < rMin) rMin = d;
              if (d > rMax) rMax = d;
            }
            if (rMax <= tMin + 1e-9 || rMin >= tMax - 1e-9) separated = true;
          }
          if (!separated) out.push(i);
        }
      }
    }
    return out;
  }

  /** Boundary edges (triangle edges without a neighbour) of a group: [{a, b, node}] (a, b vertex ids). */
  boundaryEdges(groupIndex = this.mainGroup) {
    const out = [];
    for (const n of this.groups[groupIndex]) {
      const ids = n.vertexIds;
      const shared = new Set();
      for (const pr of n.portals) {
        if (pr.length >= 2) shared.add(`${Math.min(pr[0], pr[1])}_${Math.max(pr[0], pr[1])}`);
        if (pr.length === 3) {
          shared.add(`${Math.min(pr[1], pr[2])}_${Math.max(pr[1], pr[2])}`);
          shared.add(`${Math.min(pr[0], pr[2])}_${Math.max(pr[0], pr[2])}`);
        }
      }
      for (let k = 0; k < 3; k++) {
        const a = ids[k];
        const b = ids[(k + 1) % 3];
        if (!shared.has(`${Math.min(a, b)}_${Math.max(a, b)}`)) out.push({ a, b, c: ids[(k + 2) % 3], node: n.index });
      }
    }
    return out;
  }

  get triangleCount() {
    return this.nodes.length;
  }
}
