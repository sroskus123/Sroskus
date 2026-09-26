// PLACEHOLDER third-person soldier: a simple mannequin in team colour built from the combatant's hit
// zones (head sphere, torso / arm / leg capsules), so the drawn body is exactly the hittable body, plus a
// placeholder rifle between the grip and the gameplay muzzle (the muzzle flash comes from where the
// shot starts, GUN-02). It carries empty joint nodes named like the Unreal Mannequin skeleton (pelvis,
// spine_01..03, neck_01, head, clavicle_*, upperarm_*, lowerarm_*, hand_*, thigh_*, calf_*, foot_*), the
// same names as the project's Human_Base rig, so attachments and a real skinned GLB with animations can
// replace the primitives later behind the same interface: pose(state), setDeath(pose), dispose().
// Death: stable procedural fall about the feet (no physics, cannot explode); the physics ragdoll hooks
// onto the combatant:died event later.

import { CapsuleGeometry, Color, Group, Mesh, MeshStandardMaterial, Object3D, Quaternion, SphereGeometry, BoxGeometry, Vector3 } from 'three';

export const MANNEQUIN_BONES = [
  'pelvis', 'spine_01', 'spine_02', 'spine_03', 'neck_01', 'head',
  'clavicle_l', 'upperarm_l', 'lowerarm_l', 'hand_l',
  'clavicle_r', 'upperarm_r', 'lowerarm_r', 'hand_r',
  'thigh_l', 'calf_l', 'foot_l', 'thigh_r', 'calf_r', 'foot_r',
];

const UP = new Vector3(0, 1, 0);
const _d = new Vector3();
const _m = new Vector3();
const _q = new Quaternion();
const _axis = new Vector3();

const materialCache = new Map();
function teamMaterials(color, dark) {
  const key = `${color}|${dark}`;
  if (!materialCache.has(key)) {
    materialCache.set(key, {
      vest: new MeshStandardMaterial({ color: new Color(color), roughness: 0.8, metalness: 0 }),
      limb: new MeshStandardMaterial({ color: new Color(dark), roughness: 0.85, metalness: 0 }),
      head: new MeshStandardMaterial({ color: new Color('#b9b2a6'), roughness: 0.7, metalness: 0 }),
      helmet: new MeshStandardMaterial({ color: new Color(dark), roughness: 0.6, metalness: 0.1 }),
      gun: new MeshStandardMaterial({ color: new Color('#2a2b2c'), roughness: 0.55, metalness: 0.5 }),
      marker: new MeshStandardMaterial({ color: new Color('#e07b1f'), roughness: 0.6, metalness: 0 }),
    });
  }
  return materialCache.get(key);
}

// shared geometries (nominal lengths; capsules are scaled along their axis to the pose length)
const GEO = {
  torso: { len: 0.47, geo: null },
  arm: { len: 0.55, geo: null },
  leg: { len: 0.8, geo: null },
};

function capsuleGeo(kind, radius) {
  const g = GEO[kind];
  if (!g.geo || g.radius !== radius) {
    g.geo = new CapsuleGeometry(radius, g.len, 4, 10);
    g.radius = radius;
  }
  return g.geo;
}

/** Places a +Y-aligned mesh between local points a and b, scaling its length. */
function placeBetween(mesh, a, b, nominalLen) {
  _d.subVectors(b, a);
  const len = _d.length();
  mesh.position.addVectors(a, b).multiplyScalar(0.5);
  if (len > 1e-6) mesh.quaternion.setFromUnitVectors(UP, _d.divideScalar(len));
  mesh.scale.set(1, Math.max(0.05, len / nominalLen), 1);
}

export class CharacterView {
  /**
   * @param {object} o { team, color, dark, name, hitShapeCfg }
   */
  constructor({ team, color, dark, name = '' }) {
    this.team = team;
    this.root = new Group();
    this.root.name = `soldier_placeholder_${name}`;
    this.root.userData.placeholder = true;
    const mats = teamMaterials(color, dark);
    const mk = (geo, mat, nm) => {
      const m = new Mesh(geo, mat);
      m.name = nm;
      m.castShadow = true;
      m.receiveShadow = true;
      this.root.add(m);
      return m;
    };
    this.parts = {
      head: mk(new SphereGeometry(1, 16, 12), mats.head, 'head_mesh'),
      helmet: mk(new SphereGeometry(1, 16, 8, 0, Math.PI * 2, 0, Math.PI / 2), mats.helmet, 'helmet_mesh'),
      torso: mk(capsuleGeo('torso', 0.19), mats.vest, 'torso_mesh'),
      armR: mk(capsuleGeo('arm', 0.055), mats.limb, 'arm_r_mesh'),
      armL: mk(capsuleGeo('arm', 0.055), mats.limb, 'arm_l_mesh'),
      legR: mk(capsuleGeo('leg', 0.085), mats.limb, 'leg_r_mesh'),
      legL: mk(capsuleGeo('leg', 0.085), mats.limb, 'leg_l_mesh'),
      gun: mk(new BoxGeometry(0.05, 1, 0.07), mats.gun, 'rifle_placeholder'),
      gunBand: mk(new BoxGeometry(0.055, 0.04, 0.075), mats.marker, 'rifle_placeholder_band'),
    };
    this.parts.gunBand.castShadow = false;
    // joint nodes (Unreal Mannequin names) for attachments / future skinned model
    this.bones = {};
    for (const b of MANNEQUIN_BONES) {
      const o = new Object3D();
      o.name = b;
      this.root.add(o);
      this.bones[b] = o;
    }
    this._local = {};
    for (const k of ['head', 'ta', 'tb', 'ar', 'arb', 'al', 'alb', 'lr', 'lrb', 'll', 'llb', 'grip', 'muzzle', 'support']) this._local[k] = new Vector3();
    this.visible = true;
  }

  /**
   * Pose from world-space hit shapes and weapon points (interpolated render state).
   * @param {object} st { feet: Vector3, shapes (6, see hitShapes.js), grip, support, muzzle, death: {dir:[x,z], mode, angle}|null }
   */
  pose(st) {
    const r = this.root;
    const f = st.feet;
    r.position.copy(f);
    const L = this._local;
    const toLocal = (out, p) => out.subVectors(p, f);
    const [head, torso, armR, armL, legR, legL] = st.shapes;
    toLocal(L.head, head.center);
    const P = this.parts;
    P.head.position.copy(L.head);
    P.head.scale.setScalar(head.radius);
    P.helmet.position.copy(L.head).y += head.radius * 0.18;
    P.helmet.scale.set(head.radius * 1.12, head.radius * 0.95, head.radius * 1.12);
    placeBetween(P.torso, toLocal(L.ta, torso.a), toLocal(L.tb, torso.b), GEO.torso.len);
    placeBetween(P.armR, toLocal(L.ar, armR.a), toLocal(L.arb, armR.b), GEO.arm.len);
    placeBetween(P.armL, toLocal(L.al, armL.a), toLocal(L.alb, armL.b), GEO.arm.len);
    placeBetween(P.legR, toLocal(L.lr, legR.a), toLocal(L.lrb, legR.b), GEO.leg.len);
    placeBetween(P.legL, toLocal(L.ll, legL.a), toLocal(L.llb, legL.b), GEO.leg.len);
    // placeholder rifle: from 0.25 m behind the grip to the gameplay muzzle
    toLocal(L.grip, st.grip);
    toLocal(L.muzzle, st.muzzle);
    _d.subVectors(L.muzzle, L.grip).normalize();
    _m.copy(L.grip).addScaledVector(_d, -0.25);
    placeBetween(P.gun, _m, L.muzzle, 1);
    P.gunBand.position.copy(L.grip).addScaledVector(_d, 0.22);
    P.gunBand.quaternion.copy(P.gun.quaternion);
    // joints
    const B = this.bones;
    B.pelvis.position.copy(L.ta);
    B.spine_01.position.lerpVectors(L.ta, L.tb, 0.33);
    B.spine_02.position.lerpVectors(L.ta, L.tb, 0.66);
    B.spine_03.position.copy(L.tb);
    B.neck_01.position.lerpVectors(L.tb, L.head, 0.5);
    B.head.position.copy(L.head);
    B.clavicle_r.position.lerpVectors(L.tb, L.ar, 0.5);
    B.clavicle_l.position.lerpVectors(L.tb, L.al, 0.5);
    B.upperarm_r.position.copy(L.ar);
    B.upperarm_l.position.copy(L.al);
    B.lowerarm_r.position.lerpVectors(L.ar, L.arb, 0.5);
    B.lowerarm_l.position.lerpVectors(L.al, L.alb, 0.5);
    B.hand_r.position.copy(L.arb);
    B.hand_l.position.copy(L.alb);
    B.thigh_r.position.copy(L.lr);
    B.thigh_l.position.copy(L.ll);
    B.calf_r.position.lerpVectors(L.lr, L.lrb, 0.5);
    B.calf_l.position.lerpVectors(L.ll, L.llb, 0.5);
    B.foot_r.position.copy(L.lrb);
    B.foot_l.position.copy(L.llb);

    // death: rotate the whole body about the feet toward the free fall direction
    const d = st.death;
    if (d && d.angle > 0) {
      _axis.set(d.dir[1], 0, -d.dir[0]).normalize();
      if (d.mode === 'crumple') {
        _q.setFromAxisAngle(_axis, Math.min(d.angle, 0.35));
        r.quaternion.copy(_q);
        const k = 1 - 0.62 * (d.angle / (Math.PI / 2.6));
        r.scale.set(1, Math.max(0.35, k), 1);
      } else {
        r.quaternion.setFromAxisAngle(_axis, d.angle);
        r.scale.set(1, 1, 1);
        // lift slightly while lying so the body rests on the floor instead of sinking into it
        r.position.y += Math.sin(d.angle) * 0.19;
      }
    } else {
      r.quaternion.identity();
      r.scale.set(1, 1, 1);
    }
  }

  setVisible(v) {
    this.visible = v;
    this.root.visible = v;
  }

  dispose() {
    this.root.removeFromParent();
    for (const m of Object.values(this.parts)) {
      if (m.geometry !== GEO.torso.geo && m.geometry !== GEO.arm.geo && m.geometry !== GEO.leg.geo) m.geometry.dispose();
    }
  }
}
