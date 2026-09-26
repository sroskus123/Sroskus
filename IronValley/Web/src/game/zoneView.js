// Visual of the active control zone: a ground ring and a faint translucent wall, tinted by the zone
// state (controlling team colour / contested white / empty grey). Only the active zone is shown.

import { Color, CylinderGeometry, DoubleSide, Group, Mesh, MeshBasicMaterial, RingGeometry } from 'three';

const NEUTRAL = new Color('#c8ccd0');
const CONTESTED = new Color('#ffffff');

export class ZoneView {
  constructor(scene, teamsData) {
    this.teamsData = teamsData;
    this.group = new Group();
    this.group.name = 'zone';
    this.group.visible = false;
    this.ringMat = new MeshBasicMaterial({ color: NEUTRAL.clone(), transparent: true, opacity: 0.55, depthWrite: false, side: DoubleSide, toneMapped: false });
    this.wallMat = new MeshBasicMaterial({ color: NEUTRAL.clone(), transparent: true, opacity: 0.08, depthWrite: false, side: DoubleSide, toneMapped: false });
    this.ring = new Mesh(new RingGeometry(0.94, 1, 64), this.ringMat);
    this.ring.rotation.x = -Math.PI / 2;
    this.ring.renderOrder = 2;
    this.wall = new Mesh(new CylinderGeometry(1, 1, 1, 48, 1, true), this.wallMat);
    this.wall.renderOrder = 3;
    this.group.add(this.ring, this.wall);
    scene.add(this.group);
    this.zoneId = null;
    this.stateKey = '';
  }

  /** zone: {center, radius, height} or null; status / controller from the core. */
  update(zone, status, controller, time = 0) {
    if (!zone) {
      this.group.visible = false;
      this.zoneId = null;
      return;
    }
    this.group.visible = true;
    if (this.zoneId !== zone.id) {
      this.zoneId = zone.id;
      const h = zone.height ?? 4;
      this.group.position.set(zone.center[0], zone.center[1] + 0.03, zone.center[2]);
      this.ring.scale.set(zone.radius, zone.radius, 1);
      this.wall.scale.set(zone.radius, h, zone.radius);
      this.wall.position.y = h / 2;
    }
    let col = NEUTRAL;
    if (status === 'controlled' && controller >= 0) col = new Color((this.teamsData.teams[controller] || {}).color || '#ffffff');
    else if (status === 'contested') col = CONTESTED;
    this.ringMat.color.copy(col);
    this.wallMat.color.copy(col);
    // contested: slow pulse so the state reads without the HUD
    this.wallMat.opacity = status === 'contested' ? 0.08 + 0.06 * (0.5 + 0.5 * Math.sin(time * 6)) : 0.08;
    this.stateKey = `${zone.id}:${status}:${controller}`;
  }
}
