// Armory crates ("zbrojní bedna") at the team spawns: visuals only (the collision box comes from
// levelGeometry.armoryBoxes, the rules from MatchSession.armoryFor / useArmory). Olive painted wooden crate
// with steel corners, handles, a stencilled label and a team-colour stripe, label side facing the team's spawn.

import { BoxGeometry, CanvasTexture, Color, Group, Mesh, MeshStandardMaterial, SRGBColorSpace } from 'three';

function crateTexture(teamColor, label) {
  const w = 512;
  const h = 256;
  const c = document.createElement('canvas');
  c.width = w;
  c.height = h;
  const g = c.getContext('2d');
  g.fillStyle = '#4f5a3a';
  g.fillRect(0, 0, w, h);
  // planks
  g.strokeStyle = 'rgba(20,24,14,0.55)';
  g.lineWidth = 3;
  for (let i = 1; i < 4; i++) {
    g.beginPath();
    g.moveTo(0, (h / 4) * i);
    g.lineTo(w, (h / 4) * i);
    g.stroke();
  }
  // wear
  for (let i = 0; i < 180; i++) {
    g.fillStyle = `rgba(${i % 2 ? 90 : 30},${i % 2 ? 96 : 34},${i % 2 ? 70 : 22},0.12)`;
    g.fillRect((i * 97) % w, (i * 53) % h, 6 + (i % 7) * 3, 2 + (i % 3));
  }
  // team stripe
  g.fillStyle = teamColor;
  g.fillRect(0, h * 0.08, w, h * 0.07);
  // stencil
  g.fillStyle = 'rgba(232,226,204,0.92)';
  g.textAlign = 'center';
  g.textBaseline = 'middle';
  g.font = '700 58px "DejaVu Sans", "Segoe UI", Arial, sans-serif';
  g.fillText(label, w / 2, h * 0.47);
  g.font = '600 30px "DejaVu Sans", "Segoe UI", Arial, sans-serif';
  g.fillText('OPTIKY IV-7  ·  E', w / 2, h * 0.75);
  const t = new CanvasTexture(c);
  t.colorSpace = SRGBColorSpace;
  t.anisotropy = 4;
  return t;
}

export class ArmoryView {
  /**
   * @param {object} level  level JSON (match.armories, match.teamSpawns)
   * @param {object} teamsData
   */
  constructor(level, teamsData) {
    this.group = new Group();
    this.group.name = 'armories';
    this.items = [];
    const list = (level.match && level.match.armories) || [];
    const steel = new MeshStandardMaterial({ color: new Color('#2b2e30'), roughness: 0.55, metalness: 0.75 });
    const wood = new MeshStandardMaterial({ color: new Color('#56613f'), roughness: 0.82, metalness: 0 });
    for (const a of list) {
      const [sx, sy, sz] = a.size || [1.0, 0.62, 0.62];
      const along = sx >= sz ? 'x' : 'z';
      const L = Math.max(sx, sz);
      const D = Math.min(sx, sz);
      const team = (teamsData && teamsData.teams && teamsData.teams[a.team]) || { color: '#888888' };
      const labelMat = new MeshStandardMaterial({ map: crateTexture(team.color, 'ZBROJNÍ BEDNA'), roughness: 0.85, metalness: 0 });
      const root = new Group();
      root.name = a.id;
      root.position.set(a.center[0], a.center[1], a.center[2]);
      // local frame: long side along local X, label on local +Z
      const body = new Mesh(new BoxGeometry(L - 0.02, sy - 0.04, D - 0.02), [wood, wood, wood, wood, labelMat, labelMat]);
      body.position.y = (sy - 0.04) / 2;
      const lid = new Mesh(new BoxGeometry(L, 0.04, D), wood);
      lid.position.y = sy - 0.02;
      root.add(body, lid);
      // steel corners and handles
      for (const x of [-1, 1]) {
        for (const z of [-1, 1]) {
          const post = new Mesh(new BoxGeometry(0.04, sy, 0.04), steel);
          post.position.set(x * (L / 2 - 0.02), sy / 2, z * (D / 2 - 0.02));
          root.add(post);
        }
        const handle = new Mesh(new BoxGeometry(0.03, 0.04, 0.16), steel);
        handle.position.set(x * (L / 2 + 0.01), sy * 0.62, 0);
        root.add(handle);
      }
      for (const o of root.children) {
        o.castShadow = true;
        o.receiveShadow = true;
      }
      // label side towards the team's spawn points
      const sp = (level.match.teamSpawns && level.match.teamSpawns[a.team]) || [];
      let tx = 0;
      let tz = 0;
      for (const s of sp) {
        tx += s.pos[0] / sp.length;
        tz += s.pos[2] / sp.length;
      }
      const dx = tx - a.center[0];
      const dz = tz - a.center[2];
      if (along === 'x') root.rotation.y = dz >= 0 ? 0 : Math.PI;
      else root.rotation.y = dx >= 0 ? Math.PI / 2 : -Math.PI / 2;
      this.group.add(root);
      this.items.push({ id: a.id, team: a.team, root, materials: [wood, steel, labelMat] });
    }
  }

  /** Ambient (environment) scale from the sky visibility at each crate. */
  setAmbient(fn) {
    for (const it of this.items) {
      const k = fn(it.root.position);
      for (const m of it.materials) m.envMapIntensity = k;
    }
  }

  dispose() {
    this.group.removeFromParent();
    this.group.traverse((o) => {
      if (o.geometry) o.geometry.dispose();
    });
  }
}
