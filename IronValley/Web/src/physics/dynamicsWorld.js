// cannon-es rigid-body world (stub for ragdolls, doors and small props).
// Static level boxes are mirrored from the level data; the world is stepped on the same
// fixed simulation tick as the character controller (one internal step of exactly fixedDt,
// no variable sub-stepping). The player/bot capsules are kinematic and do not live here.

import { Body, Box, ContactMaterial, Material, SAPBroadphase, Vec3, World } from 'cannon-es';

export class DynamicsWorld {
  constructor({ gravity = 9.81 } = {}) {
    this.world = new World({ gravity: new Vec3(0, -gravity, 0) });
    this.world.broadphase = new SAPBroadphase(this.world);
    this.world.allowSleep = true;
    this.staticMaterial = new Material('static');
    this.propMaterial = new Material('prop');
    this.world.addContactMaterial(
      new ContactMaterial(this.staticMaterial, this.propMaterial, { friction: 0.6, restitution: 0.05 }),
    );
    this.world.addContactMaterial(new ContactMaterial(this.propMaterial, this.propMaterial, { friction: 0.5, restitution: 0.05 }));
    this.staticBodies = [];
    this.dynamicBodies = [];
    this.steps = 0;
  }

  /** Adds an axis-aligned static box from min/max corners (metres). */
  addStaticBox(min, max, userData = null) {
    const hx = (max[0] - min[0]) / 2;
    const hy = (max[1] - min[1]) / 2;
    const hz = (max[2] - min[2]) / 2;
    const body = new Body({ mass: 0, material: this.staticMaterial, type: Body.STATIC });
    body.addShape(new Box(new Vec3(hx, hy, hz)));
    body.position.set(min[0] + hx, min[1] + hy, min[2] + hz);
    body.userData = userData;
    this.world.addBody(body);
    this.staticBodies.push(body);
    return body;
  }

  /**
   * Mirrors the axis-aligned boxes of a level (boxes, wall pieces, stair steps).
   * Ramps are not mirrored yet (the stub has no convex wedge shape); props are not placed on them.
   * @param {Array<{id:string,min:number[],max:number[],collide?:boolean}>} boxes
   */
  addLevelBoxes(boxes) {
    for (const b of boxes) {
      if (b.collide === false) continue;
      this.addStaticBox(b.min, b.max, { id: b.id });
    }
  }

  /** Adds a dynamic box prop. size = [x, y, z] full extents in metres. */
  addDynamicBox({ size, position, mass = 10, userData = null }) {
    const body = new Body({ mass, material: this.propMaterial });
    body.addShape(new Box(new Vec3(size[0] / 2, size[1] / 2, size[2] / 2)));
    body.position.set(position[0], position[1], position[2]);
    body.linearDamping = 0.05;
    body.angularDamping = 0.1;
    body.sleepSpeedLimit = 0.15;
    body.sleepTimeLimit = 0.5;
    body.userData = userData;
    this.world.addBody(body);
    this.dynamicBodies.push(body);
    return body;
  }

  /** One fixed tick. */
  step(dt) {
    this.world.step(dt);
    this.steps++;
  }

  getState() {
    return {
      steps: this.steps,
      staticBodies: this.staticBodies.length,
      dynamicBodies: this.dynamicBodies.length,
      sleeping: this.dynamicBodies.filter((b) => b.sleepState === Body.SLEEPING).length,
    };
  }
}
