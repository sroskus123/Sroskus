// Target dummies for the test range: analytic hitboxes (head sphere, torso and leg capsules),
// hit registration, simple health with knock-down and automatic reset. Pure logic (no
// rendering) so it is testable in Node; visuals live in dummyView.js.

import { Vector3 } from 'three';
import { capsuleNormal, rayCapsuleT, raySphereT } from '../util/rayShapes.js';

// Hitbox layout relative to the dummy's base (metres), roughly an adult of 1.78 m.
export const DUMMY_PARTS = [
  { name: 'head', type: 'sphere', center: [0, 1.64, 0], radius: 0.115, multiplier: 2.0 },
  { name: 'torso', type: 'capsule', a: [0, 1.02, 0], b: [0, 1.36, 0], radius: 0.19, multiplier: 1.0 },
  { name: 'legs', type: 'capsule', a: [0, 0.2, 0], b: [0, 0.86, 0], radius: 0.15, multiplier: 0.8 },
];

const _a = new Vector3();
const _b = new Vector3();
const _c = new Vector3();

export class TargetDummies {
  constructor(defs, { maxHealth = 100, resetDelay = 2.5 } = {}) {
    this.maxHealth = maxHealth;
    this.resetDelay = resetDelay;
    this.dummies = defs.map((d) => ({
      id: d.id,
      base: new Vector3(d.pos[0], d.pos[1], d.pos[2]),
      health: maxHealth,
      hits: 0,
      headHits: 0,
      kills: 0,
      down: false,
      downTimer: 0,
      lastHitTime: -1,
      lastHitPart: null,
      hitFlash: 0,
      knock: 0,
    }));
    this.time = 0;
    this.byId = new Map(this.dummies.map((d) => [d.id, d]));
  }

  /** Nearest hit of a unit ray against standing dummies, or null. */
  raycast(origin, dir, far) {
    let best = null;
    for (const d of this.dummies) {
      if (d.down) continue;
      for (const part of DUMMY_PARTS) {
        let t;
        if (part.type === 'sphere') {
          _a.fromArray(part.center).add(d.base);
          t = raySphereT(origin, dir, _a, part.radius);
        } else {
          _a.fromArray(part.a).add(d.base);
          _b.fromArray(part.b).add(d.base);
          t = rayCapsuleT(origin, dir, _a, _b, part.radius);
        }
        if (t <= far && (!best || t < best.distance)) {
          const point = origin.clone().addScaledVector(dir, t);
          let normal;
          if (part.type === 'sphere') {
            _c.fromArray(part.center).add(d.base);
            normal = point.clone().sub(_c).normalize();
          } else {
            normal = capsuleNormal(point, _a, _b);
          }
          best = {
            kind: 'dummy',
            targetKey: `dummy:${d.id}`,
            dummyId: d.id,
            part: part.name,
            multiplier: part.multiplier,
            point,
            normal,
            distance: t,
          };
        }
      }
    }
    return best;
  }

  applyHit(hit, damage) {
    const d = this.byId.get(hit.dummyId);
    if (!d || d.down) return null;
    d.hits++;
    if (hit.part === 'head') d.headHits++;
    d.lastHitPart = hit.part;
    d.lastHitTime = this.time;
    d.hitFlash = 1;
    d.knock = Math.min(d.knock + 0.35, 1);
    d.health -= damage * (hit.multiplier || 1);
    let killed = false;
    if (d.health <= 0) {
      d.health = 0;
      d.down = true;
      d.downTimer = this.resetDelay;
      d.kills++;
      killed = true;
    }
    return { dummyId: d.id, health: d.health, killed, part: hit.part };
  }

  tick(dt) {
    this.time += dt;
    for (const d of this.dummies) {
      d.hitFlash = Math.max(0, d.hitFlash - dt * 6);
      d.knock = Math.max(0, d.knock - dt * 3);
      if (d.down) {
        d.downTimer -= dt;
        if (d.downTimer <= 0) {
          d.down = false;
          d.health = this.maxHealth;
        }
      }
    }
  }

  getState() {
    return this.dummies.map((d) => ({
      id: d.id,
      hits: d.hits,
      headHits: d.headHits,
      kills: d.kills,
      health: d.health,
      down: d.down,
      lastHitPart: d.lastHitPart,
    }));
  }
}
