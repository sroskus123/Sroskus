// Publishes a capsule controller's movement facts on the game event bus, tagged with the combatant's
// identity (Docs/GAMEPLAY_CONTRACTS.md, "Události"). Used for every combatant (player and bots):
//   'footstep'        one per foot contact (gait phase of src/physics/stride.js) and per landing:
//                     { id, team, position (Vector3), surface, loudness, speed, foot, kind: 'step'|'land' }
//   'traverse:start'  { id, team, traversalId, type: 'vault'|'mantle', ledgePoint, ledgeNormal, obstacleHeight,
//                       thickness, duration, endStance }
//   'traverse:end'    { id, team, traversalId, type, aborted, position }
// surface comes from the level data (WorldQuery.surfaceAt: material under the feet), 'concrete' if unknown.
// isActive(): events are dropped while it returns false (dead combatants make no footsteps).

import { Vector3 } from 'three';

export function bindMovementEvents(controller, { id = null, team = null, owner = null, events, surfaceAt = null, isActive = null }) {
  return controller.addListener((name, p) => {
    if (!events || (isActive && !isActive())) return;
    // identity read at emit time when an owner (Combatant) is given
    if (owner) {
      id = owner.id;
      team = owner.team;
    }
    if (name === 'footstep') {
      const position = new Vector3(p.position.x, p.position.y, p.position.z);
      let surface = 'concrete';
      if (surfaceAt) {
        const s = surfaceAt(position);
        if (typeof s === 'string' && s !== 'none') surface = s;
      }
      events.emit('footstep', { id, team, position, surface, loudness: p.loudness, speed: p.speed, foot: p.foot, kind: p.kind });
    } else if (name === 'traverse:start') {
      events.emit('traverse:start', {
        id,
        team,
        traversalId: p.id,
        type: p.type,
        ledgePoint: new Vector3(p.ledgePoint.x, p.ledgePoint.y, p.ledgePoint.z),
        ledgeNormal: new Vector3(p.ledgeNormal.x, p.ledgeNormal.y, p.ledgeNormal.z),
        obstacleHeight: p.obstacleHeight,
        thickness: p.thickness,
        duration: p.duration,
        endStance: p.endStance,
      });
    } else if (name === 'traverse:end') {
      events.emit('traverse:end', { id, team, traversalId: p.id, type: p.type, aborted: !!p.aborted, position: new Vector3(p.position.x, p.position.y, p.position.z) });
    }
  });
}
