// Static collision world: collidable level triangles merged into BVH acceleration structures
// (three-mesh-bvh). Provides ray casts (hitscan, camera probes) and triangle gathering for the capsule
// character controller.
//
// Solids can be put into separate BVH groups (`bvhGroup` on the level solid, default "main"). Each group
// gets its own merged geometry and BVH; queries combine them (nearest hit / main group's triangles
// first). This keeps collision results of the base level bit-identical when optional geometry (e.g. the
// match spawn shelters) is added: the contact resolution order of the character controller follows the
// BVH layout, which would otherwise change with any triangle added anywhere in the level.

import { Box3, BufferGeometry, DoubleSide, Float32BufferAttribute, Ray, Vector3 } from 'three';
import { ExtendedTriangle, MeshBVH, SAH } from 'three-mesh-bvh';

const _ray = new Ray();
const _va = new Vector3();
const _vb = new Vector3();
const _vc = new Vector3();

/** One merged geometry + BVH for a group of solids. */
class CollisionPart {
  constructor(name, collidable) {
    this.name = name;
    let vertexCount = 0;
    for (const s of collidable) {
      if (s.geometry.index) throw new Error('CollisionWorld expects non-indexed geometry');
      vertexCount += s.geometry.getAttribute('position').count;
    }
    const positions = new Float32Array(vertexCount * 3);
    const solidOfVertex = new Uint16Array(vertexCount);
    let offset = 0;
    this.solids = [];
    collidable.forEach((s, idx) => {
      const p = s.geometry.getAttribute('position');
      positions.set(p.array.subarray(0, p.count * 3), offset * 3);
      solidOfVertex.fill(idx, offset, offset + p.count);
      offset += p.count;
      this.solids.push({ id: s.id, parent: s.parent || s.id, mat: s.mat });
    });
    this.solidOfVertex = solidOfVertex;
    const geometry = new BufferGeometry();
    geometry.setAttribute('position', new Float32BufferAttribute(positions, 3));
    this.geometry = geometry;
    this.bvh = new MeshBVH(geometry, { strategy: SAH, targetLeafSize: 6 });
    geometry.boundsTree = this.bvh;
    this.triangleCount = vertexCount / 3;
    this.bounds = new Box3().setFromBufferAttribute(geometry.getAttribute('position'));
  }
}

export class CollisionWorld {
  /**
   * @param {Array<{id:string,parent:string,mat:string,collide:boolean,geometry:BufferGeometry,bvhGroup?:string}>} solids
   */
  constructor(solids) {
    const collidable = solids.filter((s) => s.collide !== false);
    const groups = new Map([['main', []]]);
    for (const s of collidable) {
      const g = s.bvhGroup || 'main';
      if (!groups.has(g)) groups.set(g, []);
      groups.get(g).push(s);
    }
    this.parts = [];
    for (const [name, list] of groups) if (list.length > 0 || name === 'main') this.parts.push(new CollisionPart(name, list));
    const main = this.parts[0];
    // the main group keeps the historic single-BVH fields (lighting bake, tests)
    this.geometry = main.geometry;
    this.bvh = main.bvh;
    this.solids = main.solids;
    this.solidOfVertex = main.solidOfVertex;
    this.triangleCount = this.parts.reduce((n, p) => n + p.triangleCount, 0);
    this.bounds = new Box3();
    for (const p of this.parts) if (p.triangleCount > 0) this.bounds.union(p.bounds);

    // pool of triangles used by gatherTriangles
    this._triPool = [];
  }

  /**
   * Nearest raw BVH hit over all groups: { hit (three-mesh-bvh intersection with face / point /
   * distance), part (geometry, solids, solidOfVertex) } or null. `ray` is used as given.
   */
  raycastFirstRaw(ray, near = 0, far = Infinity) {
    let best = null;
    for (const part of this.parts) {
      if (part.triangleCount === 0) continue;
      const hit = part.bvh.raycastFirst(ray, DoubleSide, near, best ? Math.min(far, best.hit.distance) : far);
      if (hit && (!best || hit.distance < best.hit.distance)) best = { hit, part };
    }
    return best;
  }

  /**
   * Nearest ray hit against static geometry (both faces), or null.
   * @returns {{point:Vector3, normal:Vector3, distance:number, solidId:string, parent:string, mat:string}|null}
   */
  raycast(origin, direction, far = Infinity, near = 0) {
    _ray.origin.copy(origin);
    _ray.direction.copy(direction).normalize();
    const r = this.raycastFirstRaw(_ray, near, far);
    if (!r) return null;
    const { hit, part } = r;
    const pos = part.geometry.getAttribute('position');
    _va.fromBufferAttribute(pos, hit.face.a);
    _vb.fromBufferAttribute(pos, hit.face.b);
    _vc.fromBufferAttribute(pos, hit.face.c);
    const normal = new Vector3().subVectors(_vc, _vb).cross(new Vector3().subVectors(_va, _vb)).normalize();
    if (normal.dot(_ray.direction) > 0) normal.negate();
    const solid = part.solids[part.solidOfVertex[hit.face.a]];
    return {
      point: hit.point.clone(),
      normal,
      distance: hit.distance,
      solidId: solid.id,
      parent: solid.parent,
      mat: solid.mat,
    };
  }

  /**
   * Collects copies of all triangles whose bounds intersect `box` into `out` (array of
   * ExtendedTriangle). Returns the number of triangles written. Triangles are pooled.
   * Order: main group first (in its BVH traversal order), then the other groups.
   */
  gatherTriangles(box, out) {
    let n = 0;
    const pool = this._triPool;
    for (const part of this.parts) {
      if (part.triangleCount === 0 || !part.bounds.intersectsBox(box)) continue;
      part.bvh.shapecast({
        intersectsBounds: (b) => b.intersectsBox(box),
        intersectsTriangle: (tri) => {
          // quick reject on triangle bounds
          const minX = Math.min(tri.a.x, tri.b.x, tri.c.x);
          const maxX = Math.max(tri.a.x, tri.b.x, tri.c.x);
          if (maxX < box.min.x || minX > box.max.x) return false;
          const minY = Math.min(tri.a.y, tri.b.y, tri.c.y);
          const maxY = Math.max(tri.a.y, tri.b.y, tri.c.y);
          if (maxY < box.min.y || minY > box.max.y) return false;
          const minZ = Math.min(tri.a.z, tri.b.z, tri.c.z);
          const maxZ = Math.max(tri.a.z, tri.b.z, tri.c.z);
          if (maxZ < box.min.z || minZ > box.max.z) return false;
          let t = pool[n];
          if (!t) {
            t = new ExtendedTriangle();
            pool[n] = t;
          }
          t.a.copy(tri.a);
          t.b.copy(tri.b);
          t.c.copy(tri.c);
          t.needsUpdate = true;
          t.update();
          out[n] = t;
          n++;
          return false; // keep traversing
        },
      });
    }
    out.length = n;
    return n;
  }
}
