// Kinematic capsule character controller shared by the player and bots (decision D7).
//
// Model: a vertical capsule whose bottom point is `position` (the feet). Movement is
// integrated on the fixed simulation tick and resolved against the static BVH world by
// iterative depenetration in small sub-steps (<= maxSubstepDistance, far below the capsule
// radius, so even sprinting at a 0.1 m wall cannot tunnel through it).
//
// Contact classification (similar to Unreal's CharacterMovement, which judges floors by the
// surface normal rather than the capsule's contact normal):
//   ground   the touched triangle's FACE normal is walkable (<= maxSlope) and the contact lies
//            under the bottom sphere within the perch radius -> resolved vertically, so the
//            capsule never slides on walkable slopes and rolls smoothly over small edges
//            (stair nosings, door thresholds);
//   ceiling  contact normal points down                      -> resolved along the normal;
//   wall     everything else, including steep (> maxSlope) faces -> resolved horizontally
//            only, so steep slopes behave like walls and can never be climbed.
// Ground contacts are resolved before walls in each pass so an edge shared by a tread and a
// riser lifts instead of blocking.
// Two perch radii (both measured horizontally from the capsule axis to the contact point):
//   perchRadius       while grounded, an edge touched within this radius is rolled over as
//                     ground (low edges up to ~0.2 m lift smoothly, like stair nosings);
//   standPerchRadius  what actually supports the capsule. Standing on an edge further out than
//                     this is only allowed if walkable ground lies under the axis within
//                     maxStepHeight (stairs, low ledges); otherwise the capsule falls off
//                     (like Unreal's perch check). While airborne only edges within this radius
//                     can be landed on, so a jump cannot mount ledges much above its apex.
// Steps higher than the automatic roll-over use an explicit lift -> move -> sweep-down step
// (<= maxStepHeight, only with headroom). The forward probe is extended towards the blocking
// face so the step works at any approach angle. A step is accepted only if it really climbed
// onto something past that face; a 1.0 m wall can never become a step.
// Ground snapping (step down): after a grounded move without ground contact, the bottom sphere
// is swept down by groundSnapDistance (stairs / slopes / low ledges downward). The snap is taken
// if walkable ground is hit no more than maxStepHeight below the surface point the capsule was
// last standing on, at any speed; otherwise it falls. So stepping down is limited by
// maxStepHeight exactly like stepping up. If the edge the capsule is rolling off (beyond the
// roll-over perch) is still in the way, the capsule is lowered until the sphere touches that
// edge and keeps rolling down it on the following ticks until it reaches the ground below:
// no hovering, no airborne phase, no sideways pop.
//
// Horizontal velocity: src/physics/locomotion.js (turns redirect quickly instead of sliding, momentum is
// kept in the air, no speed gain). Jump input is buffered (jumpBufferTime) and allowed shortly after
// walking off an edge (coyoteTime), never twice in one air phase. Vault / mantle: src/physics/traversal.js
// (validated scripted move, input locked). Gait phase and foot contacts: src/physics/stride.js.
// Events (onEvent + addListener): 'jump', 'landed', 'footstep', 'step', 'traverse:start', 'traverse:end'.

import { Box3, Line3, Vector3 } from 'three';
import { approach, DEG2RAD } from '../util/math.js';
import { sweepSphereTriangle } from './sweep.js';
import { locomotionParams, updateHorizontalVelocity } from './locomotion.js';
import { StrideTracker } from './stride.js';
import { planTraversal, traversalParams } from './traversal.js';

// Scratch objects. Each one is used by exactly one function so nested calls cannot alias.
const _seg = new Line3();
const _triPoint = new Vector3(); // capsuleTriangleContact
const _segPoint = new Vector3(); // capsuleTriangleContact
const _ctPierce = new Vector3(); // capsuleTriangleContact
const _ctMid = new Vector3(); // capsuleTriangleContact
const _rsNormal = new Vector3(); // _resolve
const _rsFace = new Vector3(); // _resolve
const _rsH = new Vector3(); // _resolve
const _rsKeepN = new Vector3(); // _resolve
const _rsKeepF = new Vector3(); // _resolve
const _alPos = new Vector3(); // _landsOnEdge
const _alNormal = new Vector3(); // _landsOnEdge
const _ovNormal = new Vector3(); // overlaps
const _ovFace = new Vector3(); // overlaps
const _pdCenter = new Vector3(); // _probeDown
const _pdPoint = new Vector3(); // _probeDown
const _pdBest = new Vector3(); // _probeDown
const _pdNormal = new Vector3(); // _probeDown
const _pdFace = new Vector3(); // _probeDown
const _stDir = new Vector3(); // _tryStep
const _stTmp = new Vector3(); // _tryStep
const _stFwd = new Vector3(); // _tryStep
const _upInto = new Vector3(); // update
const _fsCenter = new Vector3(); // _footSupported
const _fsPoint = new Vector3(); // _footSupported
const _box = new Box3();
const DOWN = new Vector3(0, -1, 0);
// A contact whose normal is within ~2.6 deg of the triangle's face normal touches the face
// itself (not an edge or vertex): the surface continues under the capsule.
const FACE_CONTACT_COS = 0.999;
// A step is only tried against a face the character wants to go into (cos of the angle
// between the wish direction and the face normal must exceed this); grazing never steps.
const STEP_MIN_INTO = 0.05;
// Minimum rise and minimum advance past the blocking face for an accepted step.
const STEP_MIN_RISE = 0.005;
const STEP_MIN_PAST = 0.01;
// Ground probe: wall contacts with a normal flatter than this may be skipped if they are only
// grazed (<= PROBE_GLANCE_SKIN overlap) at the ground below.
const PROBE_GLANCE_MAX_NY = 0.5;
const PROBE_GLANCE_SKIN = 0.01;

function makeFlags() {
  return {
    ground: false,
    groundNormal: new Vector3(0, 1, 0),
    // height of the highest supporting contact point (-Infinity: none recorded)
    groundPointY: -Infinity,
    // ground snap only (see _probeDown / _snapDown)
    restOnEdge: false,
    edgePointY: 0,
    supportPointY: 0,
    wall: false,
    ceiling: false,
    wallNormals: [new Vector3(), new Vector3(), new Vector3(), new Vector3()],
    wallCount: 0,
  };
}

function resetFlags(f) {
  f.ground = false;
  f.groundNormal.set(0, 1, 0);
  f.groundPointY = -Infinity;
  f.wall = false;
  f.ceiling = false;
  f.wallCount = 0;
  return f;
}

function addWallNormal(f, h) {
  f.wall = true;
  for (let i = 0; i < f.wallCount; i++) {
    if (f.wallNormals[i].dot(h) > 0.999) return;
  }
  if (f.wallCount < f.wallNormals.length) {
    f.wallNormals[f.wallCount++].copy(h);
  }
}

function setGround(f, n) {
  if (!f.ground || n.y > f.groundNormal.y) f.groundNormal.copy(n);
  f.ground = true;
}

function mergeFlags(into, f) {
  if (f.ground) setGround(into, f.groundNormal);
  if (f.groundPointY > into.groundPointY) into.groundPointY = f.groundPointY;
  if (f.ceiling) into.ceiling = true;
  for (let i = 0; i < f.wallCount; i++) addWallNormal(into, f.wallNormals[i]);
}

/**
 * Penetration depth of a capsule (segment + radius) into a triangle. Writes the push-out
 * contact normal and the triangle's face normal (oriented towards the capsule). Returns 0
 * when not touching.
 */
export function capsuleTriangleContact(tri, seg, radius, outNormal, outFace) {
  const plane = tri.plane;
  const ds = plane.distanceToPoint(seg.start);
  const de = plane.distanceToPoint(seg.end);
  if (ds * de < 0) {
    // The capsule axis crosses the triangle plane: check if it pierces the triangle itself.
    const t = ds / (ds - de);
    _ctPierce.copy(seg.end).sub(seg.start).multiplyScalar(t).add(seg.start);
    if (tri.containsPoint(_ctPierce)) {
      outNormal.copy(plane.normal);
      // push towards the side where most of the capsule already is
      if (Math.abs(de) > Math.abs(ds)) {
        if (de < 0) outNormal.negate();
      } else if (ds < 0) {
        outNormal.negate();
      }
      if (outFace) outFace.copy(outNormal);
      return radius + Math.min(Math.abs(ds), Math.abs(de));
    }
  }
  const dist = tri.closestPointToSegment(seg, _triPoint, _segPoint);
  if (dist >= radius) return 0;
  if (dist > 1e-7) {
    outNormal.subVectors(_segPoint, _triPoint).divideScalar(dist);
  } else {
    outNormal.copy(plane.normal);
    _ctMid.addVectors(seg.start, seg.end).multiplyScalar(0.5);
    const side = plane.distanceToPoint(_ctMid);
    if (side < 0 || (side === 0 && outNormal.y < 0)) outNormal.negate();
  }
  if (outFace) {
    outFace.copy(plane.normal);
    if (outFace.dot(outNormal) < 0) outFace.negate();
  }
  return radius - dist;
}

export class CharacterController {
  /**
   * @param {import('./collisionWorld.js').CollisionWorld} world
   * @param {object} params  movement.json
   */
  constructor(world, params) {
    this.world = world;
    this.params = params;
    const c = params.capsule;
    this.radius = c.radius;
    this.standHeight = c.standHeight;
    this.crouchHeight = c.crouchHeight;
    this.standEyeHeight = c.standEyeHeight;
    this.crouchEyeHeight = c.crouchEyeHeight;
    this.walkableCos = Math.cos(params.maxSlopeDeg * DEG2RAD);
    // roll-over perch (grounded contact classification)
    this.perchRadius = Math.min(params.perchRadius ?? this.radius * 0.9, this.radius * 0.99);
    // contact normal y below which an edge contact is too far out to be rolled over
    this.perchMinY = Math.sqrt(1 - (this.perchRadius / this.radius) ** 2);
    // support perch (standing past an edge, landing while airborne)
    this.standPerchRadius = Math.min(params.standPerchRadius ?? this.perchRadius, this.perchRadius);
    this.standPerchMinY = Math.sqrt(1 - (this.standPerchRadius / this.radius) ** 2);
    this._activePerchMinY = this.perchMinY;
    this.jumpSpeed = Math.sqrt(2 * params.gravity * params.jumpApexHeight);

    this.position = new Vector3();
    this.velocity = new Vector3();
    this.grounded = false;
    this.groundNormal = new Vector3(0, 1, 0);
    // height of the surface point the capsule stands on (step-down limit reference)
    this.groundPointY = 0;
    this.crouched = false;
    this.height = this.standHeight;
    this.eyeHeight = this.standEyeHeight;
    this.sprinting = false;
    this.speedTarget = 0;
    this.stepOffset = 0; // visual smoothing for discrete vertical snaps (steps), decays to 0
    this.jumpCooldownTimer = 0;
    this.airTime = 0;

    this.stats = {
      stepUps: 0,
      snaps: 0,
      landings: 0,
      jumps: 0,
      lastLandingSpeed: 0,
      lastLandingTick: -1,
      blockedStandTicks: 0,
      perchDrops: 0,
      bufferedJumps: 0,
      coyoteJumps: 0,
      footsteps: 0,
      stepEvents: 0,
      traversals: 0,
      traversalAborts: 0,
    };
    this.tickCount = 0;
    /** optional callback(eventName, payload) */
    this.onEvent = null;
    this._listeners = [];

    // locomotion / jump buffering / coyote time
    this.loco = locomotionParams(params);
    this.jumpBuffer = 0;
    this.coyoteTimer = 0;
    this._airJumped = false;
    this._wallMem = [new Vector3(), new Vector3(), new Vector3(), new Vector3()];
    this._wallMemCount = 0;
    this._push = { x: 0, z: 0 };
    // gait phase / foot contacts (footstep events, head bob)
    this.stride = new StrideTracker(params.stride || {});
    // vault / mantle
    this.traversalParams = traversalParams(params);
    this.traversalEnabled = this.traversalParams.enabled !== false;
    this.traversal = null;
    // weapon raise after a vault / mantle (s left): the hands come back to the weapon before it can fire
    this.handsRecover = 0;
    this._traversalSeq = 0;
    this._nextAirTraverseTick = 0;
    this.lastTraversalFail = null;
    this._trPos = new Vector3();
    this._trPrev = new Vector3();

    this._tris = [];
    this._probeSkip = [];
    this._flags = makeFlags();
    this._subFlags = makeFlags();
    this._stepFlags = makeFlags();
    this._probeFlags = makeFlags();
    this._snapFlags = makeFlags();
    this._prev = new Vector3();
    this._disp = new Vector3();
    this._sub = new Vector3();
    this._stepPos = new Vector3();
    this._wish = new Vector3();
    this._jumpTest = new Vector3();
    this._saved = new Vector3();
    this._snapStart = new Vector3();
  }

  get eyePosition() {
    return new Vector3(this.position.x, this.position.y + this.eyeHeight, this.position.z);
  }

  /** Additional event listener (name, payload); returns a function that removes it. */
  addListener(fn) {
    this._listeners.push(fn);
    return () => {
      const i = this._listeners.indexOf(fn);
      if (i >= 0) this._listeners.splice(i, 1);
    };
  }

  /** True during a vault / mantle (input locked, weapon lowered). */
  get traversing() {
    return this.traversal !== null;
  }

  /**
   * Hands off the weapon: during a vault / mantle and while the weapon is raised again afterwards
   * (traversal.weaponRaiseTime). The combatant locks the weapon for exactly this time and the first-person
   * view model is lowered / raised on the same clock, so a round never leaves a weapon drawn lowered.
   */
  get handsBusy() {
    return this.traversal !== null || this.handsRecover > 0;
  }

  /** 0..1 how far the weapon is lowered by a traversal (1 during the move, raised to 0 over weaponRaiseTime). */
  get weaponLower() {
    if (this.traversal) return 1;
    const T = this.traversalParams.weaponRaiseTime;
    if (!(this.handsRecover > 0) || !(T > 0)) return 0;
    const u = Math.min(1, this.handsRecover / T);
    return u * u * (3 - 2 * u);
  }

  teleport(pos) {
    if (this.traversal) {
      // a teleport (respawn, script) ends a traversal without moving along it
      const tr = this.traversal;
      this.traversal = null;
      if (this.height < this.crouchHeight) this.height = this.crouched ? this.crouchHeight : this.standHeight;
      this._emit('traverse:end', { id: tr.id, type: tr.plan.type, aborted: true, reason: 'teleport', tick: this.tickCount });
    }
    this.position.copy(pos);
    this.velocity.set(0, 0, 0);
    this.stepOffset = 0;
    this.handsRecover = 0;
    this.grounded = false;
    this.airTime = 0;
    this.jumpBuffer = 0;
    this.coyoteTimer = 0;
    this._airJumped = false;
    this._wallMemCount = 0;
    this.stride.reset();
    this._activePerchMinY = this.perchMinY;
    const f = resetFlags(this._probeFlags);
    this._gather(this.position, this.height, 0.3);
    this._resolve(this.position, this.height, f);
    if (f.ground || this._probeDown(this.position, this.height, 0.5, f)) {
      this.grounded = true;
      this.groundNormal.copy(f.groundNormal);
      if (!this._supported(this.position, this.groundNormal)) this.grounded = false;
    }
    this.groundPointY = Number.isFinite(f.groundPointY) ? f.groundPointY : this.position.y;
  }

  // ---------------------------------------------------------------- collision helpers

  _segment(pos, height, radius) {
    _seg.start.set(pos.x, pos.y + radius, pos.z);
    _seg.end.set(pos.x, pos.y + Math.max(height - radius, radius), pos.z);
    return _seg;
  }

  _gather(pos, height, margin, extraDown = 0) {
    const r = this.radius;
    _box.min.set(pos.x - r - margin, pos.y - margin - extraDown, pos.z - r - margin);
    _box.max.set(pos.x + r + margin, pos.y + height + margin, pos.z + r + margin);
    return this.world.gatherTriangles(_box, this._tris);
  }

  /**
   * Walkable face, and the contact is either on the face itself or an edge/vertex close enough
   * to the axis (active perch: roll-over radius while grounded, support radius in the air).
   */
  _isGroundContact(n, face) {
    if (face.y < this.walkableCos - 1e-4) return false;
    return n.y >= this._activePerchMinY - 1e-4 || n.dot(face) >= FACE_CONTACT_COS;
  }

  /**
   * True if walkable ground lies under the capsule axis within the support perch radius, at
   * most maxStepHeight below the feet (small sphere swept down from the feet).
   */
  _footSupported(pos) {
    const rp = this.standPerchRadius;
    const maxDist = this.params.maxStepHeight + 0.02;
    this._gather(pos, rp * 2, 0.05, maxDist + 0.05);
    const center = _fsCenter.set(pos.x, pos.y + rp, pos.z);
    let best = Infinity;
    for (let i = 0; i < this._tris.length; i++) {
      const t = sweepSphereTriangle(center, DOWN, rp, this._tris[i], maxDist, _fsPoint);
      if (t < best) best = t;
    }
    if (!(best <= maxDist)) return false;
    const tol = 1e-4;
    for (let i = 0; i < this._tris.length; i++) {
      const tri = this._tris[i];
      const t = sweepSphereTriangle(center, DOWN, rp, tri, best + tol, _fsPoint);
      if (t > best + tol) continue;
      // face normal oriented towards the sphere; an edge shared by a walkable top and a
      // vertical side counts as support
      const side = tri.plane.distanceToPoint(center) < 0 ? -1 : 1;
      if (tri.plane.normal.y * side >= this.walkableCos - 1e-4) return true;
    }
    return false;
  }

  /** Grounded on `normal`: is the capsule really supported there (see standPerchRadius)? */
  _supported(pos, normal) {
    if (normal.y >= this.standPerchMinY - 1e-4) return true;
    return this._footSupported(pos);
  }

  /**
   * Airborne landing check for an edge/vertex contact that looks standable at the penetrated
   * position: a fast sideways sub-step can carry an edge from "touching the side of the
   * sphere" to "under the sphere" in one go. Judge the contact by its normal at first touch
   * along the sub-step from `from` to `pos` instead (bisection), so the landing / ledge-mount
   * limit does not depend on speed.
   */
  _landsOnEdge(tri, pos, from, height) {
    const r = this.radius;
    _alPos.copy(from);
    if (capsuleTriangleContact(tri, this._segment(_alPos, height, r), r, _alNormal, null) > 1e-4) return true; // already resting on it
    let lo = 0;
    let hi = 1;
    for (let k = 0; k < 14; k++) {
      const mid = (lo + hi) / 2;
      _alPos.lerpVectors(from, pos, mid);
      if (capsuleTriangleContact(tri, this._segment(_alPos, height, r), r, _alNormal, null) > 1e-6) hi = mid;
      else lo = mid;
    }
    _alPos.lerpVectors(from, pos, hi);
    if (capsuleTriangleContact(tri, this._segment(_alPos, height, r), r, _alNormal, null) <= 0) return true;
    return _alNormal.y >= this.standPerchMinY - 1e-4;
  }

  /**
   * Depenetrates `pos` against the gathered triangles; accumulates contact info in flags.
   * `from` (airborne sub-steps only): start of the sub-step, see _landsOnEdge.
   */
  _resolve(pos, height, flags, from = null) {
    const r = this.radius;
    const tris = this._tris;
    const n = _rsNormal;
    const face = _rsFace;
    for (let iter = 0; iter < 8; iter++) {
      let maxDepth = 0;
      // pass 0: ground contacts only; pass 1: everything that still penetrates
      for (let pass = 0; pass < 2; pass++) {
        for (let i = 0; i < tris.length; i++) {
          const seg = this._segment(pos, height, r);
          const depth = capsuleTriangleContact(tris[i], seg, r, n, face);
          if (depth <= 1e-6) continue;
          let isGround = this._isGroundContact(n, face);
          if (isGround && from !== null && n.dot(face) < FACE_CONTACT_COS) {
            // n / face live in shared scratch vectors: keep them across the check
            _rsKeepN.copy(n);
            _rsKeepF.copy(face);
            isGround = this._landsOnEdge(tris[i], pos, from, height);
            n.copy(_rsKeepN);
            face.copy(_rsKeepF);
          }
          if (pass === 0 && !isGround) continue;
          if (depth > maxDepth) maxDepth = depth;
          if (isGround) {
            pos.y += depth / n.y;
            setGround(flags, n);
            // supporting point on the bottom sphere (edge height when perched on an edge)
            const py = pos.y + r * (1 - n.y);
            if (py > flags.groundPointY) flags.groundPointY = py;
          } else if (n.y < -0.3) {
            pos.addScaledVector(n, depth);
            flags.ceiling = true;
          } else {
            _rsH.set(n.x, 0, n.z);
            let len = _rsH.length();
            if (len < 0.2) {
              // contact normal nearly vertical but surface too steep to stand on:
              // slide off along the surface's horizontal direction
              _rsH.set(face.x, 0, face.z);
              len = _rsH.length();
              if (len < 1e-5) {
                pos.addScaledVector(n, depth);
                continue;
              }
              _rsH.divideScalar(len);
              const along = _rsH.dot(n);
              pos.addScaledVector(_rsH, depth / Math.max(along, 0.2));
            } else {
              _rsH.divideScalar(len);
              pos.addScaledVector(_rsH, depth / len);
            }
            addWallNormal(flags, _rsH);
          }
        }
      }
      if (maxDepth < 1e-5) break;
    }
  }

  /** True if the capsule at pos (with radius shrunk by `shrink`) overlaps static geometry. */
  overlaps(pos, height, shrink = 0.01) {
    this._gather(pos, height, 0.05);
    const r = this.radius - shrink;
    for (let i = 0; i < this._tris.length; i++) {
      const seg = this._segment(pos, height, r);
      if (capsuleTriangleContact(this._tris[i], seg, r, _ovNormal, _ovFace) > 1e-4) return true;
    }
    return false;
  }

  canStand() {
    return !this.overlaps(this.position, this.standHeight, 0.01);
  }

  /**
   * Sweeps the bottom sphere straight down by up to maxDist. If the first surface hit is
   * standable ground, moves pos onto it and returns true; otherwise leaves pos unchanged.
   * flags.groundPointY is the height of the ground contact found.
   * `restOnEdge` (ground snap only): if a skipped edge would overlap the sphere at that ground,
   * lower pos only until the sphere touches the edge instead of failing (flags.restOnEdge =
   * true, flags.edgePointY = height of that edge contact); the capsule then rolls down the edge
   * on the next ticks exactly like a rounded foot.
   */
  _probeDown(pos, height, maxDist, flags, restOnEdge = false) {
    resetFlags(flags);
    flags.restOnEdge = false;
    const r = this.radius;
    const n = this._gather(pos, height, 0.05, maxDist + 0.05);
    const tris = this._tris;
    const center = _pdCenter.set(pos.x, pos.y + r, pos.z);
    const skipped = this._probeSkip;
    skipped.length = 0;
    const tol = 1e-4;
    // A glancing touch of a wall edge on the way down (e.g. the next stair riser's top edge
    // right in front of the capsule on a tread narrower than the capsule) must not hide the
    // ground just below it. Such contacts (nearly horizontal normal) are skipped as long as the
    // bottom sphere would overlap them by no more than PROBE_GLANCE_SKIN at the ground found
    // further down; the next depenetration pass pushes that sliver out sideways.
    // ground snap: exact contact (roll down the edge instead of pushing a sliver out sideways)
    const skin = restOnEdge ? 1e-4 : PROBE_GLANCE_SKIN;
    let firstT = Infinity; // first time of impact overall (always a skipped edge after round 0)
    let firstPointY = 0;
    for (let round = 0; round < 3; round++) {
      // first time of impact among the remaining triangles
      let best = Infinity;
      for (let i = 0; i < n; i++) {
        if (skipped.includes(i)) continue;
        const t = sweepSphereTriangle(center, DOWN, r, tris[i], maxDist, _pdPoint);
        if (t < best) best = t;
      }
      if (!(best <= maxDist)) return false;
      if (round === 0) firstT = best;
      // Several triangles can be hit at the same time (an edge shared by a tread and a riser):
      // the contact counts as ground if any of them is a standable surface.
      let groundFound = false;
      let blocking = false;
      const skippedBefore = skipped.length;
      for (let i = 0; i < n && !groundFound; i++) {
        if (skipped.includes(i)) continue;
        const tri = tris[i];
        const t = sweepSphereTriangle(center, DOWN, r, tri, best + tol, _pdPoint);
        if (t > best + tol) continue;
        _pdBest.set(center.x, center.y - t, center.z);
        _pdNormal.subVectors(_pdBest, _pdPoint);
        const len = _pdNormal.length();
        if (len < 1e-7) continue;
        _pdNormal.divideScalar(len);
        _pdFace.copy(tri.plane.normal);
        if (_pdFace.dot(_pdNormal) < 0) _pdFace.negate();
        if (this._isGroundContact(_pdNormal, _pdFace)) {
          groundFound = true;
          flags.groundPointY = _pdPoint.y;
        } else if (_pdNormal.y < PROBE_GLANCE_MAX_NY) {
          if (round === 0 && skipped.length === 0) firstPointY = _pdPoint.y;
          skipped.push(i);
        } else {
          blocking = true; // e.g. a steep face under the capsule: it must slide / fall
        }
      }
      if (groundFound) {
        let drop = Math.max(best - 1e-5, 0);
        // the skipped wall contacts may only be grazed at the new position
        _pdBest.set(center.x, center.y - drop, center.z);
        for (let k = 0; k < skipped.length; k++) {
          tris[skipped[k]].closestPointToPoint(_pdBest, _pdPoint);
          if (r - _pdPoint.distanceTo(_pdBest) <= skin) continue;
          if (!restOnEdge) return false;
          // rest on the first edge instead (touching it); the ground below is within reach
          drop = Math.max(firstT - 1e-5, 0);
          flags.restOnEdge = true;
          flags.edgePointY = firstPointY;
          break;
        }
        pos.y -= drop;
        setGround(flags, _pdNormal);
        return true;
      }
      if (blocking || skipped.length === skippedBefore) return false;
    }
    return false;
  }

  /**
   * Attempts to climb a step after the plain move from `prev` by `move` was blocked.
   * `resolved` is where the plain move ended (touching the obstacle), `wallFlags` holds the
   * wall normals it touched, `intoDir` (horizontal unit vector or null) is the direction the
   * character wants to go. On success moves this.position and fills outFlags.
   */
  _tryStep(prev, move, height, resolved, wallFlags, outFlags, intoDir = null) {
    const P = this.params;
    const hlen = Math.hypot(move.x, move.z);
    if (hlen < 1e-7) return false;
    _stDir.set(move.x / hlen, 0, move.z / hlen);
    // The face to climb: the touched wall normal most opposed to where the character wants to
    // go. The wish is used rather than the velocity because velocity into a wall is removed at
    // the end of every tick, so after any blocked tick the move itself only grazes the face.
    const want = intoDir || _stDir;
    let block = null;
    let blockDot = -STEP_MIN_INTO;
    for (let i = 0; i < wallFlags.wallCount; i++) {
      const d = wallFlags.wallNormals[i].dot(want);
      if (d < blockDot) {
        blockDot = d;
        block = wallFlags.wallNormals[i];
      }
    }
    if (!block) return false;
    const maxLift = P.maxStepHeight;
    // lift in increments, stopping below any ceiling
    let lift = 0;
    const p = this._stepPos;
    for (let k = 1; k <= 4; k++) {
      const l = (maxLift * k) / 4;
      p.copy(prev);
      p.y += l;
      if (this.overlaps(p, height, 0.005)) break;
      lift = l;
    }
    if (lift < 0.05) return false;
    // Forward probe: the move itself, extended towards the blocking face far enough that the
    // step edge ends up under the bottom sphere inside the roll-over perch radius. Probing only
    // along the (possibly oblique) move direction fails at steep approach angles, and probing
    // further along the slide direction would let the "step" add speed along walls.
    const gap = Math.max(0, _stTmp.subVectors(prev, resolved).dot(block));
    const need = gap + (this.radius - this.perchRadius) + (P.stepEdgeMargin ?? 0.02);
    _stFwd.copy(_stDir).multiplyScalar(hlen);
    const into = -_stFwd.dot(block);
    if (into < need) _stFwd.addScaledVector(block, into - need);
    p.copy(prev);
    p.y += lift;
    p.add(_stFwd);
    const f = resetFlags(this._stepFlags);
    this._gather(p, height, 0.25);
    this._resolve(p, height, f);
    const pf = this._probeFlags;
    if (!this._probeDown(p, height, lift + 0.05, pf)) return false;
    const rise = p.y - prev.y;
    // nothing was climbed (e.g. a tall wall pushed the lifted probe back to the floor)
    if (rise < STEP_MIN_RISE) return false;
    // Judge the step by the height of the supporting surface point, not by the capsule
    // bottom: perched on an edge, the rounded bottom sits lower than the edge itself.
    if (pf.groundPointY - prev.y > maxLift + 1e-3 || rise > maxLift + 1e-3) return false;
    // the capsule must have got past the face that stopped the plain move, and not backwards
    if (_stTmp.subVectors(p, resolved).dot(block) > -STEP_MIN_PAST) return false;
    if (_stTmp.subVectors(p, prev).dot(_stDir) <= 1e-4) return false;
    // final safety: stepped position must be free
    if (this.overlaps(p, height, 0.01)) return false;
    // accept
    resetFlags(outFlags);
    outFlags.ground = true;
    outFlags.groundNormal.copy(pf.groundNormal);
    outFlags.groundPointY = pf.groundPointY;
    for (let i = 0; i < f.wallCount; i++) addWallNormal(outFlags, f.wallNormals[i]);
    if (f.ceiling) outFlags.ceiling = true;
    this.position.copy(p);
    if (rise > 0.02) this.stepOffset -= rise;
    this.stats.stepUps++;
    return true;
  }

  /**
   * Ground snap / step down after a grounded move ended without ground contact. On success pos
   * stands on walkable ground at most maxStepHeight below the previous support point (or rests
   * on the edge it is rolling off, with that ground right below; see _probeDown restOnEdge),
   * `flags` holds the ground and flags.supportPointY the actual support height, `wallFlags` the
   * walls touched by the final depenetration (only float noise normally). On failure pos is
   * unchanged (the capsule falls).
   */
  _snapDown(pos, flags, wallFlags) {
    const P = this.params;
    const start = this._snapStart.copy(pos);
    resetFlags(wallFlags);
    if (!this._probeDown(pos, this.height, P.groundSnapDistance, flags, true)) return false;
    // stepping down is limited like stepping up (measured between the support points)
    if (this.groundPointY - flags.groundPointY > P.maxStepHeight + 1e-3) {
      pos.copy(start);
      return false;
    }
    flags.supportPointY = flags.restOnEdge ? flags.edgePointY : flags.groundPointY;
    this._gather(pos, this.height, 0.25);
    this._resolve(pos, this.height, wallFlags);
    if (this.overlaps(pos, this.height, 0.01)) {
      pos.copy(start);
      return false;
    }
    return true;
  }

  // ---------------------------------------------------------------- simulation

  /**
   * One fixed simulation tick.
   * @param {number} dt
   * @param {object} cmd { moveX, moveZ (forward +), yaw, sprint, walk, crouch, jump, ads, fire }
   */
  update(dt, cmd) {
    const P = this.params;
    this.tickCount++;
    if (this.handsRecover > 0) this.handsRecover = this.handsRecover - dt > 1e-6 ? this.handsRecover - dt : 0;
    // vault / mantle in progress: scripted kinematic move, input locked
    if (this.traversal) {
      this._stepTraversal(dt);
      return;
    }
    const wasGrounded = this.grounded;
    const pos = this.position;
    const vel = this.velocity;
    const gy0 = this.groundPointY;
    const px0 = pos.x;
    const pz0 = pos.z;

    // --- stance (stand up only with headroom) ---
    if (cmd.crouch && !this.crouched) {
      this.crouched = true;
      this.height = this.crouchHeight;
    } else if (!cmd.crouch && this.crouched) {
      if (this.canStand()) {
        this.crouched = false;
        this.height = this.standHeight;
      } else {
        this.stats.blockedStandTicks++;
      }
    }
    const eyeTarget = this.crouched ? this.crouchEyeHeight : this.standEyeHeight;
    this.eyeHeight = approach(this.eyeHeight, eyeTarget, P.eyeHeightRate * dt);

    // --- wish direction (diagonal input normalised) ---
    let ix = cmd.moveX || 0;
    let iz = cmd.moveZ || 0;
    const ilen = Math.hypot(ix, iz);
    if (ilen > 1) {
      ix /= ilen;
      iz /= ilen;
    }
    const yaw = cmd.yaw || 0;
    const sy = Math.sin(yaw);
    const cy = Math.cos(yaw);
    // forward = (-sin, 0, -cos), right = (cos, 0, -sin)
    const wish = this._wish.set(cy * ix - sy * iz, 0, -sy * ix - cy * iz);
    const wishLen = wish.length();

    let angleOk = false;
    if (wishLen > 0.1 && iz > 0) {
      const cosA = iz / Math.hypot(ix, iz);
      angleOk = cosA >= Math.cos(P.sprintMaxAngleDeg * DEG2RAD) - 1e-6;
    }
    const sprint = !!cmd.sprint && !this.crouched && !cmd.ads && !cmd.fire && angleOk;
    let speed;
    if (this.crouched) speed = P.speeds.crouch;
    else if (cmd.ads) speed = P.speeds.ads;
    else if (cmd.walk) speed = P.speeds.walk;
    else if (sprint) speed = P.speeds.sprint;
    else speed = P.speeds.run;
    this.sprinting = sprint && wishLen > 0.1;
    this.speedTarget = speed * wishLen;

    // --- horizontal velocity (src/physics/locomotion.js) ---
    const push = this._push;
    if (wishLen > 1e-3) {
      updateHorizontalVelocity(vel, wish.x / wishLen, wish.z / wishLen, speed * wishLen, this.grounded, this.loco, dt, this._wallMem, this._wallMemCount, push);
    } else {
      updateHorizontalVelocity(vel, 0, 0, 0, this.grounded, this.loco, dt, null, 0, push);
    }

    // --- jump / vault (buffered press, coyote time after walking off an edge) ---
    let jumped = false;
    this.jumpCooldownTimer = Math.max(0, this.jumpCooldownTimer - dt);
    this.jumpBuffer = Math.max(0, this.jumpBuffer - dt);
    if (cmd.jump) this.jumpBuffer = P.jumpBufferTime ?? 0.15;
    if (this.traversalEnabled && iz >= 0 && this._traversalWanted(cmd, iz)) {
      if (this._tryStartTraversal(yaw, !(this.jumpBuffer > 0))) {
        this._stepTraversal(dt);
        return;
      }
    }
    const canJumpNow = this.grounded || (this.coyoteTimer > 0 && !this._airJumped);
    if (this.jumpBuffer > 0 && canJumpNow && !this.crouched && this.jumpCooldownTimer <= 0) {
      const test = this._jumpTest.copy(pos);
      test.y += 0.05;
      if (!this.overlaps(test, this.height, 0.01)) {
        vel.y = this.jumpSpeed;
        if (!this.grounded) this.stats.coyoteJumps++;
        if (!cmd.jump) this.stats.bufferedJumps++;
        this.grounded = false;
        jumped = true;
        this.jumpBuffer = 0;
        this.coyoteTimer = 0;
        this._airJumped = true;
        this.jumpCooldownTimer = P.jumpCooldown;
        this.stats.jumps++;
        this._emit('jump', { tick: this.tickCount });
      }
    }

    // --- displacement for this tick ---
    const disp = this._disp;
    if (this.grounded) {
      vel.y = 0;
      disp.set(vel.x * dt, 0, vel.z * dt);
      // keep pressing against walls the wish goes into (contact -> step attempts, see locomotion.js)
      const pl = Math.hypot(push.x, push.z);
      if (pl > 1e-6) {
        const k = Math.min(pl, P.wallPushSpeed ?? 0.5) / pl;
        disp.x += push.x * k * dt;
        disp.z += push.z * k * dt;
      }
      const n = this.groundNormal;
      if (n.y > 0.1) disp.y = -(disp.x * n.x + disp.z * n.z) / n.y;
    } else {
      const vy0 = vel.y;
      const vy1 = Math.max(vy0 - P.gravity * dt, -P.maxFallSpeed);
      disp.set(vel.x * dt, ((vy0 + vy1) / 2) * dt, vel.z * dt);
      vel.y = vy1;
    }

    // --- move in sub-steps ---
    const flags = resetFlags(this._flags);
    const dist = disp.length();
    const nSub = Math.max(1, Math.ceil(dist / P.maxSubstepDistance));
    const sub = this._sub.copy(disp).divideScalar(nSub);
    const canStep = wasGrounded && !jumped;
    // grounded: roll over low edges; airborne: only edges near the axis can be landed on
    this._activePerchMinY = canStep ? this.perchMinY : this.standPerchMinY;
    const intoDir = wishLen > 0.1 ? _upInto.set(wish.x / wishLen, 0, wish.z / wishLen) : null;
    for (let i = 0; i < nSub; i++) {
      const prev = this._prev.copy(pos);
      pos.add(sub);
      const f = resetFlags(this._subFlags);
      this._gather(pos, this.height, 0.25);
      this._resolve(pos, this.height, f, canStep ? null : prev);
      if (f.wall && canStep && (sub.x !== 0 || sub.z !== 0)) {
        const saved = this._saved.copy(pos);
        if (!this._tryStep(prev, sub, this.height, saved, f, f, intoDir)) {
          pos.copy(saved);
        }
      }
      mergeFlags(flags, f);
    }

    // --- ground state ---
    const vyBefore = vel.y;
    if (jumped) {
      this.grounded = false;
    } else if (flags.ground && (wasGrounded || vel.y <= 0)) {
      this.grounded = true;
      this.groundNormal.copy(flags.groundNormal);
      if (Number.isFinite(flags.groundPointY)) this.groundPointY = flags.groundPointY;
    } else if (wasGrounded) {
      const y0 = pos.y;
      const pf = this._probeFlags;
      const sf = this._snapFlags;
      if (this._snapDown(pos, pf, sf)) {
        this.grounded = true;
        this.groundNormal.copy(pf.groundNormal);
        this.groundPointY = pf.supportPointY;
        for (let i = 0; i < sf.wallCount; i++) addWallNormal(flags, sf.wallNormals[i]);
        const dy = pos.y - y0;
        if (Math.abs(dy) > 0.03) {
          this.stepOffset -= dy;
          this.stats.snaps++;
        }
      } else {
        this.grounded = false;
      }
    } else {
      this.grounded = false;
    }
    // perched on an edge beyond the support radius over a drop: not supported, fall off
    if (this.grounded && !this._supported(pos, this.groundNormal)) {
      this.grounded = false;
      this.stats.perchDrops++;
    }

    const hSpeed = Math.hypot(vel.x, vel.z);
    if (this.grounded) {
      if (!wasGrounded) {
        const impact = -Math.min(vyBefore, 0);
        this.stats.landings++;
        this.stats.lastLandingSpeed = impact;
        this.stats.lastLandingTick = this.tickCount;
        this._emit('landed', { speed: impact, airTime: this.airTime, tick: this.tickCount });
        this._footstep(this.stride.land(hSpeed), impact);
      }
      vel.y = 0;
      this.airTime = 0;
      this.coyoteTimer = P.coyoteTime ?? 0.12;
      this._airJumped = false;
    } else {
      this.airTime += dt;
      this.coyoteTimer = Math.max(0, this.coyoteTimer - dt);
    }
    if (flags.ceiling && vel.y > 0) vel.y = 0;
    // remove velocity pointing into walls we touched (prevents speed build-up against walls)
    this._wallMemCount = 0;
    for (let i = 0; i < flags.wallCount; i++) {
      const h = flags.wallNormals[i];
      const d = vel.x * h.x + vel.z * h.z;
      if (d < 0) {
        vel.x -= h.x * d;
        vel.z -= h.z * d;
      }
      if (this._wallMemCount < this._wallMem.length) this._wallMem[this._wallMemCount++].copy(h);
    }

    // --- gait: foot contacts, stair steps (camera / audio / AI hearing) ---
    if (this.grounded && wasGrounded) {
      const contact = this.stride.update(dt, true, Math.hypot(vel.x, vel.z), this.crouched);
      if (contact) this._footstep(contact, 0);
      // a stair riser: the support height jumps faster than any walkable slope could raise it
      const dy = this.groundPointY - gy0;
      const hMove = Math.hypot(pos.x - px0, pos.z - pz0);
      const slopeRise = hMove * Math.tan(P.maxSlopeDeg * DEG2RAD) * 1.2;
      if (Math.abs(dy) > Math.max(P.stepEventMinRise ?? 0.05, slopeRise)) {
        this.stats.stepEvents++;
        this.stride.riser(Math.hypot(vel.x, vel.z)); // foot contacts follow the treads of a staircase
        this._emit('step', { dy, tick: this.tickCount });
      }
    } else if (!this.grounded) {
      this.stride.update(dt, false, 0, this.crouched);
    }

    // decay visual step smoothing
    this.stepOffset *= Math.exp(-14 * dt);
    if (Math.abs(this.stepOffset) < 1e-4) this.stepOffset = 0;
  }

  // ---------------------------------------------------------------- foot contacts

  _footstep(contact, impact) {
    if (!contact) return;
    this.stats.footsteps++;
    const s = contact.speed;
    let loudness;
    if (contact.kind === 'land') loudness = Math.min(1, 0.35 + impact / 8);
    else loudness = this.crouched ? 0.15 : this.sprinting ? 1.0 : s < 2 ? 0.25 : 0.55;
    this._emit('footstep', {
      foot: contact.foot,
      kind: contact.kind,
      speed: s,
      loudness,
      crouched: this.crouched,
      position: { x: this.position.x, y: this.position.y, z: this.position.z },
      tick: this.tickCount,
    });
  }

  // ---------------------------------------------------------------- vault / mantle

  /** Should a traversal be attempted this tick? (jump pressed / buffered, or jumped into a wall holding forward) */
  _traversalWanted(cmd, iz) {
    const TP = this.traversalParams;
    if (this.grounded || (this.coyoteTimer > 0 && !this._airJumped)) return this.jumpBuffer > 0;
    // airborne: only early in the air phase, not falling fast, throttled
    if (this.airTime > 1.2 || this.velocity.y < -TP.airMaxFallSpeed) return false;
    if (this.tickCount < this._nextAirTraverseTick) return false;
    if (this.jumpBuffer > 0) return true;
    // jumped at an obstacle holding forward: grab it on contact (no second press needed)
    if (!this._airJumped || iz < 0.5) return false;
    const fx = -Math.sin(cmd.yaw || 0);
    const fz = -Math.cos(cmd.yaw || 0);
    for (let i = 0; i < this._wallMemCount; i++) {
      const n = this._wallMem[i];
      if (n.x * fx + n.z * fz < -0.7) return true;
    }
    return false;
  }

  _tryStartTraversal(yaw, auto) {
    const dx = -Math.sin(yaw);
    const dz = -Math.cos(yaw);
    const v = this.velocity;
    const airborne = !this.grounded;
    const baseY = airborne ? Math.min(this.groundPointY, this.position.y) : this.groundPointY;
    const res = planTraversal(this, {
      dirX: dx,
      dirZ: dz,
      speed: Math.max(0, v.x * dx + v.z * dz),
      baseY,
      airborne,
      nudge: !auto,
      params: this.traversalParams,
    });
    if (airborne) this._nextAirTraverseTick = this.tickCount + 3;
    if (!res.ok) {
      this.lastTraversalFail = { reason: res.reason, tick: this.tickCount, detail: res.detail || null };
      return false;
    }
    this._startTraversal(res.plan);
    return true;
  }

  _startTraversal(plan) {
    const tr = { plan, t: 0, id: ++this._traversalSeq, startCrouched: this.crouched };
    this.traversal = tr;
    this.height = plan.tuckHeight;
    this.grounded = false;
    this.sprinting = false;
    this.speedTarget = 0;
    this.jumpBuffer = 0;
    this.coyoteTimer = 0;
    this._airJumped = true;
    this._wallMemCount = 0;
    this.stats.traversals++;
    this.lastTraversalFail = null;
    this._emit('traverse:start', {
      id: tr.id,
      type: plan.type,
      ledgePoint: { ...plan.ledgePoint },
      ledgeNormal: { ...plan.ledgeNormal },
      obstacleHeight: plan.obstacleHeight,
      thickness: plan.thickness,
      duration: plan.duration,
      endStance: plan.endStance,
      tick: this.tickCount,
    });
  }

  _stepTraversal(dt) {
    const tr = this.traversal;
    const plan = tr.plan;
    const TP = this.traversalParams;
    const tPrev = tr.t;
    tr.t = Math.min(1, tr.t + dt / plan.duration);
    const p = plan.positionAt(tr.t, this._trPos);
    // re-validated every tick: never move into geometry (static world: only fails if it changed)
    if (this.overlaps(p, plan.tuckHeight, TP.tickShrink)) {
      this._abortTraversal(tPrev);
      return;
    }
    const prev = this._trPrev.copy(this.position);
    this.position.copy(p);
    this.velocity.set((p.x - prev.x) / dt, (p.y - prev.y) / dt, (p.z - prev.z) / dt);
    this.eyeHeight = plan.eyeHeightAt(tr.t);
    this.grounded = false;
    this.airTime = 0;
    this.stepOffset *= Math.exp(-14 * dt);
    if (Math.abs(this.stepOffset) < 1e-4) this.stepOffset = 0;
    if (tr.t >= 1) this._finishTraversal(false);
  }

  _abortTraversal(tPrev) {
    const tr = this.traversal;
    const plan = tr.plan;
    this.stats.traversalAborts++;
    // back along the (validated) path to a point that holds the crouched capsule
    const p = this._trPos;
    for (let t = tPrev; t >= 0; t -= 0.05) {
      plan.positionAt(Math.max(0, t), p);
      if (!this.overlaps(p, this.crouchHeight, 0.001)) {
        this.position.copy(p);
        break;
      }
      if (t - 0.05 < 0 && t > 0) {
        plan.positionAt(0, p);
        this.position.copy(p);
      }
    }
    this._finishTraversal(true);
  }

  _finishTraversal(aborted) {
    const tr = this.traversal;
    const plan = tr.plan;
    this.traversal = null;
    const pos = this.position;
    if (!aborted && plan.endStance === 'stand' && !this.overlaps(pos, this.standHeight, 0.01)) {
      this.crouched = false;
      this.height = this.standHeight;
    } else {
      this.crouched = true;
      this.height = this.crouchHeight;
    }
    const v = aborted ? 0 : plan.exitSpeed;
    this.velocity.set(plan.mx * v, 0, plan.mz * v);
    // settle: ground under the end point?
    const f = resetFlags(this._probeFlags);
    this._gather(pos, this.height, 0.3);
    this._resolve(pos, this.height, f);
    this.grounded = false;
    if (f.ground || this._probeDown(pos, this.height, 0.12, f)) {
      this.grounded = true;
      this.groundNormal.copy(f.groundNormal);
      if (!this._supported(pos, this.groundNormal)) this.grounded = false;
    }
    if (this.grounded && Number.isFinite(f.groundPointY)) this.groundPointY = f.groundPointY;
    this.airTime = 0;
    this.coyoteTimer = 0;
    this._airJumped = !this.grounded;
    this._wallMemCount = 0;
    this.handsRecover = this.traversalParams.weaponRaiseTime || 0;
    this._emit('traverse:end', {
      id: tr.id,
      type: plan.type,
      aborted,
      grounded: this.grounded,
      position: { x: pos.x, y: pos.y, z: pos.z },
      tick: this.tickCount,
    });
    if (this.grounded) this._footstep(this.stride.land(Math.hypot(this.velocity.x, this.velocity.z)), plan.type === 'vault' ? 2.0 : 0.5);
  }

  _emit(name, payload) {
    if (this.onEvent) this.onEvent(name, payload);
    for (let i = 0; i < this._listeners.length; i++) this._listeners[i](name, payload);
  }

  getState() {
    return {
      position: { x: this.position.x, y: this.position.y, z: this.position.z },
      velocity: { x: this.velocity.x, y: this.velocity.y, z: this.velocity.z },
      horizontalSpeed: Math.hypot(this.velocity.x, this.velocity.z),
      grounded: this.grounded,
      groundNormalY: this.groundNormal.y,
      crouched: this.crouched,
      height: this.height,
      eyeHeight: this.eyeHeight,
      sprinting: this.sprinting,
      traversing: this.traversal !== null,
      handsBusy: this.handsBusy,
      weaponLower: this.weaponLower,
      traversal: this.traversal ? { id: this.traversal.id, type: this.traversal.plan.type, t: this.traversal.t, duration: this.traversal.plan.duration } : null,
      lastTraversalFail: this.lastTraversalFail ? { ...this.lastTraversalFail } : null,
      stridePhase: this.stride.phase,
      stats: { ...this.stats },
    };
  }
}
