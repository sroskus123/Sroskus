// Visuals for target dummies. Meshes match the analytic hitboxes in targetDummies.js exactly
// (what you see is what you hit). Hit flash, knock-back wobble and knock-down are visual
// responses to the simulation state.

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
      this.items.push({ d, root, pivot, mat, down: 0 });
    }
  }

  update(dt) {
    for (const it of this.items) {
      const target = it.d.down ? 1 : 0;
      it.down += (target - it.down) * (1 - Math.exp(-(target ? 9 : 4) * dt));
      const wobble = Math.sin(performance.now() * 0.03) * 0.06 * it.d.knock;
      it.pivot.rotation.x = -(it.down * 1.35) - it.d.knock * 0.12 + wobble;
      it.mat.emissiveIntensity = it.d.hitFlash * 1.8;
    }
  }
}
