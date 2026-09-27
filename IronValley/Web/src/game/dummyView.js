// Visuals for target dummies. Meshes match the analytic hitboxes in targetDummies.js exactly
// (what you see is what you hit). Hit flash, knock-back wobble and knock-down are visual
// responses to the simulation state. They advance on the fixed simulation tick (tick / hold)
// and are interpolated when drawn (update), so they stop behind the pause menu, follow the
// time scale and do not step at 60 Hz on faster displays.

import { CapsuleGeometry, Color, CylinderGeometry, Group, Mesh, MeshStandardMaterial, SphereGeometry } from 'three';
import { DUMMY_PARTS } from './targetDummies.js';

export class DummyView {
  constructor(dummies) {
    this.dummies = dummies;
    this.group = new Group();
    this.group.name = 'dummies';
    this.items = [];
    const baseMat = new MeshStandardMaterial({ color: new Color('#34383d'), roughness: 0.6, metalness: 0.5 });
    const standGeo = new CylinderGeometry(0.035, 0.035, 0.2, 10);
    standGeo.translate(0, 0.1, 0);
    const plateGeo = new CylinderGeometry(0.3, 0.34, 0.05, 20);
    plateGeo.translate(0, 0.025, 0);
    for (const d of dummies.dummies) {
      const root = new Group();
      root.position.copy(d.base);
      const pivot = new Group(); // tilts around the base when hit / knocked down
      root.add(pivot);
      const mat = new MeshStandardMaterial({ color: new Color('#c9b48a'), roughness: 0.85, metalness: 0, emissive: new Color('#ff2a10'), emissiveIntensity: 0 });
      for (const part of DUMMY_PARTS) {
        let mesh;
        if (part.type === 'sphere') {
          mesh = new Mesh(new SphereGeometry(part.radius, 20, 14), mat);
          mesh.position.fromArray(part.center);
        } else {
          const len = part.b[1] - part.a[1];
          mesh = new Mesh(new CapsuleGeometry(part.radius, len, 6, 16), mat);
          mesh.position.set(part.a[0], (part.a[1] + part.b[1]) / 2, part.a[2]);
        }
        mesh.castShadow = true;
        mesh.receiveShadow = true;
        pivot.add(mesh);
      }
      const plate = new Mesh(plateGeo, baseMat);
      plate.receiveShadow = true;
      plate.castShadow = true;
      root.add(plate);
      const stand = new Mesh(standGeo, baseMat);
      stand.castShadow = true;
      root.add(stand);
      this.group.add(root);
      // visual state after the last tick (curr) and the one before (prev)
      this.items.push({ d, root, pivot, mat, down: 0, prevDown: 0, knock: 0, prevKnock: 0, flash: 0, prevFlash: 0 });
    }
    this.time = dummies.time;
    this.prevTime = dummies.time;
  }

  /** One fixed simulation tick, after TargetDummies.tick. */
  tick(dt) {
    this.prevTime = this.time;
    this.time = this.dummies.time;
    for (const it of this.items) {
      it.prevDown = it.down;
      it.prevKnock = it.knock;
      it.prevFlash = it.flash;
      const target = it.d.down ? 1 : 0;
      it.down += (target - it.down) * (1 - Math.exp(-(target ? 9 : 4) * dt));
      it.knock = it.d.knock;
      it.flash = it.d.hitFlash;
    }
  }

  /** Simulation not advancing (paused / menu): keep the drawn pose still. */
  hold() {
    this.prevTime = this.time;
    for (const it of this.items) {
      it.prevDown = it.down;
      it.prevKnock = it.knock;
      it.prevFlash = it.flash;
    }
  }

  /** Pose for drawing, interpolated between the last two ticks (alpha in [0, 1]). */
  update(alpha = 1) {
    const a = Math.min(Math.max(alpha, 0), 1);
    const t = this.prevTime + (this.time - this.prevTime) * a;
    for (const it of this.items) {
      const down = it.prevDown + (it.down - it.prevDown) * a;
      const knock = it.prevKnock + (it.knock - it.prevKnock) * a;
      const wobble = Math.sin(t * 30) * 0.06 * knock;
      it.pivot.rotation.x = -(down * 1.35) - knock * 0.12 + wobble;
      it.mat.emissiveIntensity = (it.prevFlash + (it.flash - it.prevFlash) * a) * 1.8;
    }
  }
}
