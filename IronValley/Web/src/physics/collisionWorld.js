// Static collision world: all collidable level triangles merged into one geometry with a
// three-mesh-bvh acceleration structure. Provides ray casts (hitscan, camera probes) and
// triangle gathering for the capsule character controller.

import { Box3, BufferGeometry, DoubleSide, Float32BufferAttribute, Ray, Vector3 } from 'three';
import { ExtendedTriangle, MeshBVH, SAH } from 'three-mesh-bvh';

const _ray = new Ray();
const _va = new Vector3();
const _vb = new Vector3();
const _vc = new Vector3();

export class CollisionWorld {
  /**
   * @param {Array<{id:string,parent:string,mat:string,collide:boolean,geometry:BufferGeometry}>} solids
   */
  constructor(solids) {
    const collidable = solids.filter((s) => s.collide !== false);
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

    // pool of triangles used by gatherTriangles
    this._triPool = [];
  }

  /**
   * Nearest ray hit against static geometry (both faces), or null.
   * @returns {{point:Vector3, normal:Vector3, distance:number, solidId:string, parent:string, mat:string}|null}
   */
  raycast(origin, direction, far = Infinity, near = 0) {
    _ray.origin.copy(origin);
    _ray.direction.copy(direction).normalize();
    const hit = this.bvh.raycastFirst(_ray, DoubleSide, near, far);
    if (!hit) return null;
    const pos = this.geometry.getAttribute('position');
    _va.fromBufferAttribute(pos, hit.face.a);
    _vb.fromBufferAttribute(pos, hit.face.b);
    _vc.fromBufferAttribute(pos, hit.face.c);
    const normal = new Vector3().subVectors(_vc, _vb).cross(new Vector3().subVectors(_va, _vb)).normalize();
    if (normal.dot(_ray.direction) > 0) normal.negate();
    const solid = this.solids[this.solidOfVertex[hit.face.a]];
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
   */
  gatherTriangles(box, out) {
    let n = 0;
    const pool = this._triPool;
    this.bvh.shapecast({
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
    out.length = n;
    return n;
  }
}
