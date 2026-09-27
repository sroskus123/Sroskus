// Visual of the active control zone: a ground ring and a faint translucent wall, tinted by the zone
// state (controlling team colour / contested white / empty grey). Only the active zone is shown.
// Polygon zones (generated maps, src/game/zoneShape.js) get a draped ground line and a wall along the outline.

import { BufferGeometry, Color, CylinderGeometry, DoubleSide, Float32BufferAttribute, Group, Mesh, MeshBasicMaterial, RingGeometry } from 'three';

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
    this.polyLine = null;
    this.polyWall = null;
    scene.add(this.group);
    this.zoneId = null;
    this.stateKey = '';
    // groundAt(x, z, yFrom) -> ground height below (x, yFrom, z) or null; set by the game for draped outlines
    this.groundAt = null;
  }

  _clearPoly() {
    for (const m of [this.polyLine, this.polyWall]) {
      if (m) {
        this.group.remove(m);
        m.geometry.dispose();
      }
    }
    this.polyLine = null;
    this.polyWall = null;
  }

  _buildPoly(zone) {
    this._clearPoly();
    const P = zone.polygon;
    const y0 = zone.yMin ?? zone.center[1];
    const y1 = Math.min(zone.yMax ?? y0 + 3, y0 + 3.5);
    const line = [];
    const wall = [];
    const pts = [];
    for (let i = 0; i < P.length; i++) {
      const a = P[i];
      const b = P[(i + 1) % P.length];
      const L = Math.hypot(b[0] - a[0], b[1] - a[1]);
      const n = Math.max(1, Math.ceil(L / 0.75));
      for (let k = 0; k < n; k++) {
        const t = k / n;
        const x = a[0] + (b[0] - a[0]) * t;
        const z = a[1] + (b[1] - a[1]) * t;
        let y = y0;
        if (this.groundAt) {
          const g = this.groundAt(x, z, y1 + 1.0);
          if (g !== null && g >= y0 - 1.5 && g <= y1 + 0.5) y = g;
        }
        pts.push([x, y + 0.04, z]);
      }
    }
    for (let i = 0; i < pts.length; i++) {
      const p = pts[i];
      const q = pts[(i + 1) % pts.length];
      const dx = q[0] - p[0];
      const dz = q[2] - p[2];
      const L = Math.hypot(dx, dz) || 1;
      const nx = (-dz / L) * 0.06;
      const nz = (dx / L) * 0.06;
      line.push(p[0] - nx, p[1], p[2] - nz, q[0] - nx, q[1], q[2] - nz, q[0] + nx, q[1], q[2] + nz);
      line.push(p[0] - nx, p[1], p[2] - nz, q[0] + nx, q[1], q[2] + nz, p[0] + nx, p[1], p[2] + nz);
      wall.push(p[0], p[1], p[2], q[0], q[1], q[2], q[0], q[1] + 2.4, q[2]);
      wall.push(p[0], p[1], p[2], q[0], q[1] + 2.4, q[2], p[0], p[1] + 2.4, p[2]);
    }
    const lg = new BufferGeometry();
    lg.setAttribute('position', new Float32BufferAttribute(line, 3));
    const wg = new BufferGeometry();
    wg.setAttribute('position', new Float32BufferAttribute(wall, 3));
    this.polyLine = new Mesh(lg, this.ringMat);
    this.polyLine.renderOrder = 2;
    this.polyWall = new Mesh(wg, this.wallMat);
    this.polyWall.renderOrder = 3;
    this.group.add(this.polyLine, this.polyWall);
  }

  /** zone: {center, radius, height} or {polygon, yMin, yMax} or null; status / controller from the core. */
  update(zone, status, controller, time = 0) {
    if (!zone) {
      this.group.visible = false;
      this.zoneId = null;
      return;
    }
    this.group.visible = true;
    if (this.zoneId !== zone.id) {
      this.zoneId = zone.id;
      const poly = Array.isArray(zone.polygon) && zone.polygon.length >= 3;
      this.ring.visible = !poly;
      this.wall.visible = !poly;
      if (poly) {
        this.group.position.set(0, 0, 0);
        this._buildPoly(zone);
      } else {
        this._clearPoly();
        const h = zone.height ?? 4;
        this.group.position.set(zone.center[0], zone.center[1] + 0.03, zone.center[2]);
        this.ring.scale.set(zone.radius, zone.radius, 1);
        this.wall.scale.set(zone.radius, h, zone.radius);
        this.wall.position.y = h / 2;
      }
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
