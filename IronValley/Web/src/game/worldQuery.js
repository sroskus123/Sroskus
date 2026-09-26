// World queries shared by the game, weapons and AI (Docs/GAMEPLAY_CONTRACTS.md, "Dotazy na svět"):
//   raycastStatic(origin, dir, maxDist)      static geometry (BVH)
//   lineOfSight(from, to, { ignoreId })     static geometry + combatant hit zones; true only if clear
//   surfaceAt(point)                         surface type for footsteps / impacts
// plus raycastCombat(origin, dir, far, ignoreId) used by hitscan: nearest of static world, living
// combatants' hit zones and test dummies, tagged with kind / targetKey. No DOM.

import { Vector3 } from 'three';
import { pointInShapes, raycastShapes } from './hitShapes.js';

const _dir = new Vector3();
const _down = new Vector3(0, -1, 0);
const _o = new Vector3();

// level material -> surface type (footsteps, impacts)
const SURFACE_OF_MAT = {
  floor: 'concrete',
  wall: 'plaster',
  block: 'concrete',
  stair: 'concrete',
  ramp: 'concrete',
  hazard: 'metal',
  accent: 'metal',
  dark: 'metal',
};

/** Ray vs axis-aligned box slab test: does the unit ray reach the box within far? */
function rayHitsBox(o, d, min, max, far) {
  let t0 = 0;
  let t1 = far;
  for (const ax of ['x', 'y', 'z']) {
    const inv = 1 / d[ax];
    let tn = (min[ax] - o[ax]) * inv;
    let tf = (max[ax] - o[ax]) * inv;
    if (tn > tf) [tn, tf] = [tf, tn];
    if (tn > t0) t0 = tn;
    if (tf < t1) t1 = tf;
    if (t0 > t1) return false;
  }
  return true;
}

export class WorldQuery {
  /**
   * @param {object} o
   * @param {import('../physics/collisionWorld.js').CollisionWorld} o.world
   * @param {object} [o.combatants]  CombatantManager (all(); each combatant: id, alive, hitShapes(), boundsMin/Max)
   * @param {import('./targetDummies.js').TargetDummies} [o.dummies]
   */
  constructor({ world, combatants = null, dummies = null }) {
    this.world = world;
    this.combatants = combatants;
    this.dummies = dummies;
    this.stats = { raycasts: 0, losQueries: 0 };
  }

  raycastStatic(origin, dir, maxDist = Infinity) {
    this.stats.raycasts++;
    const h = this.world.raycast(origin, dir, maxDist);
    if (!h) return null;
    return { ...h, kind: 'world', targetKey: `world:${h.solidId}`, surface: SURFACE_OF_MAT[h.mat] || 'concrete' };
  }

  /** Nearest living combatant hit-zone intersection (skipping ignoreId and bodies containing the origin). */
  raycastCombatants(origin, dir, far, ignoreId = null, skipContaining = null) {
    if (!this.combatants) return null;
    let best = null;
    for (const c of this.combatants.all()) {
      if (!c.alive || c.id === ignoreId) continue;
      c.updateHitShapes();
      if (!rayHitsBox(origin, dir, c.boundsMin, c.boundsMax, best ? best.distance : far)) continue;
      const shapes = c.hitShapes();
      if (skipContaining && skipContaining.some((p) => pointInShapes(shapes, p))) continue;
      const h = raycastShapes(shapes, origin, dir, best ? best.distance : far);
      if (h && (!best || h.distance < best.distance)) {
        best = {
          kind: 'combatant',
          targetKey: `combatant:${c.id}`,
          combatantId: c.id,
          team: c.team,
          part: h.part,
          point: h.point,
          normal: h.normal,
          distance: h.distance,
          mat: 'flesh',
        };
      }
    }
    return best;
  }

  /** Hitscan query: nearest of static world, living combatants (except the shooter) and dummies. */
  raycastCombat(origin, dir, far, ignoreId = null) {
    let best = this.raycastStatic(origin, dir, far);
    const limit = best ? best.distance : far;
    const c = this.raycastCombatants(origin, dir, limit, ignoreId);
    if (c && (!best || c.distance < best.distance)) best = c;
    if (this.dummies) {
      const d = this.dummies.raycast(origin, dir, best ? best.distance : far);
      if (d && (!best || d.distance < best.distance)) best = d;
    }
    return best;
  }

  /**
   * True if the segment from -> to is clear of static geometry and of living combatants' hit zones.
   * The body of `ignoreId` and any body containing one of the end points (the observer or the target
   * itself) are skipped, so eye-to-eye checks work without naming the target.
   */
  lineOfSight(fromPoint, toPoint, { ignoreId = null } = {}) {
    this.stats.losQueries++;
    _dir.subVectors(toPoint, fromPoint);
    const dist = _dir.length();
    if (dist < 1e-6) return true;
    _dir.divideScalar(dist);
    if (this.world.raycast(fromPoint, _dir, dist)) return false;
    const blocker = this.raycastCombatants(fromPoint, _dir, dist, ignoreId, [fromPoint, toPoint]);
    return !blocker;
  }

  /** Surface type under / at a point (probe straight down 1.5 m). */
  surfaceAt(point) {
    _o.copy(point);
    _o.y += 0.3;
    const h = this.world.raycast(_o, _down, 1.8);
    if (!h) return 'none';
    return SURFACE_OF_MAT[h.mat] || 'concrete';
  }
}
