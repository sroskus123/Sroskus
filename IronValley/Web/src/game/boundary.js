// Map boundary of generated maps (level.boundary, Docs/MAP_DESIGN.md section 11), DOM-free:
//   inside   within the warning polygon
//   warning  8 m band between the warning polygon and the soft line: HUD text, no timer
//   outside  beyond the soft line: countdown (countdownS, 10 s); at 0 the combatant dies as "Minové pole" (no kill
//            credit, no score change, normal respawn). The hard edge 6 m further out is collision (capsules only).
// Same rule for the player and the bots (bots never plan outside the navmesh, which ends 1 m inside the soft line).

import { pointInPolygonXZ } from './zoneShape.js';

export class BoundarySystem {
  /** @param {object} b level.boundary { soft, warning, hard: [[x, z]...], countdownS, text } */
  constructor(b) {
    this.b = b;
    this.countdownS = b.countdownS ?? 10;
    this.text = b.text || {};
    this.state = new Map(); // id -> { status, outsideS }
    this.deaths = 0;
  }

  classify(p) {
    if (!pointInPolygonXZ(this.b.soft, p.x, p.z)) return 'outside';
    if (this.b.warning && !pointInPolygonXZ(this.b.warning, p.x, p.z)) return 'warning';
    return 'inside';
  }

  /** One tick: updates every living combatant, calls expire(c) when a countdown runs out. */
  update(dt, combatants, expire) {
    for (const c of combatants) {
      if (!c.alive) {
        this.state.delete(c.id);
        continue;
      }
      const status = this.classify(c.position);
      const e = this.state.get(c.id) || { status: 'inside', outsideS: 0 };
      e.status = status;
      e.outsideS = status === 'outside' ? e.outsideS + dt : 0;
      this.state.set(c.id, e);
      if (e.outsideS >= this.countdownS - 1e-9) {
        e.outsideS = 0;
        this.deaths++;
        expire(c);
      }
    }
  }

  /** { status, remainingS, text } for a combatant (HUD). */
  info(id) {
    const e = this.state.get(id);
    if (!e || e.status === 'inside') return { status: 'inside', remainingS: this.countdownS, text: '' };
    if (e.status === 'warning') return { status: 'warning', remainingS: this.countdownS, text: this.text.warning || 'Blížíš se k hranici bojového prostoru.' };
    const rem = Math.max(0, this.countdownS - e.outsideS);
    const t = (this.text.leaving || 'Opouštíš bojový prostor! Vrať se: {s} s').replace('{s}', String(Math.ceil(rem - 1e-6)));
    return { status: 'outside', remainingS: rem, text: t };
  }

  reset() {
    this.state.clear();
  }
}
