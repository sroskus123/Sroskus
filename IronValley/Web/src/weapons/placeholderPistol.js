// Clearly marked PLACEHOLDER pistol (IV-P9) built from primitives, used until the real GLB exists at
// public/assets/weapons/IVP9_Pistol.glb. Same conventions as the art pipeline: metres, origin at the
// firing-hand grip, muzzle along +X, top +Y, right side +Z (glTF axes). Orange magazine base and slide
// band mark it as a placeholder in first person. Sockets match weapons.json (ivp9_pistol.viewModel).

import { BoxGeometry, Color, CylinderGeometry, Group, Mesh, MeshStandardMaterial, Object3D } from 'three';

export const PISTOL_MUZZLE = [0.157, 0.068, 0];
export const PISTOL_ADS_EYE = [-0.42, 0.094, 0]; // sight line: top of the front post, seen through the rear notch

export function createPlaceholderPistol() {
  const root = new Group();
  root.name = 'IVP9_placeholder';
  const metal = new MeshStandardMaterial({ color: new Color('#2b2d2f'), metalness: 0.6, roughness: 0.45 });
  const polymer = new MeshStandardMaterial({ color: new Color('#2f2e2b'), metalness: 0.0, roughness: 0.75 });
  const marker = new MeshStandardMaterial({ color: new Color('#e07b1f'), metalness: 0.0, roughness: 0.6 });
  const dot = new MeshStandardMaterial({ color: new Color('#d9d4c4'), metalness: 0, roughness: 0.4, emissive: new Color('#4a4a3a'), emissiveIntensity: 0.4 });
  const box = (name, x0, x1, y0, y1, hz, mat, rotZ = 0) => {
    const m = new Mesh(new BoxGeometry(x1 - x0, y1 - y0, hz * 2), mat);
    m.name = name;
    m.position.set((x0 + x1) / 2, (y0 + y1) / 2, 0);
    m.rotation.z = rotZ;
    root.add(m);
    return m;
  };
  box('slide', -0.035, 0.155, 0.047, 0.085, 0.0135, metal);
  box('slide_band_placeholder', 0.02, 0.035, 0.047, 0.0855, 0.0138, marker);
  box('frame', -0.03, 0.14, 0.022, 0.05, 0.012, polymer);
  const barrel = new Mesh(new CylinderGeometry(0.0055, 0.0055, 0.01, 12), metal);
  barrel.name = 'barrel_tip';
  barrel.rotation.z = Math.PI / 2;
  barrel.position.set(0.152, 0.068, 0);
  root.add(barrel);
  box('grip', -0.038, 0.012, -0.095, 0.03, 0.0145, polymer, -0.22);
  box('mag_base_placeholder', -0.045, 0.0, -0.106, -0.094, 0.016, marker, -0.22);
  box('trigger_guard', 0.0, 0.06, 0.012, 0.019, 0.008, polymer);
  box('trigger', 0.018, 0.024, 0.0, 0.022, 0.003, metal);
  // rear sight: base + two ears with a 6 mm notch; front post 4.4 mm wide, its top on the sight line
  box('rear_sight_base', -0.032, -0.018, 0.085, 0.0885, 0.011, metal);
  box('rear_sight_ear_l', -0.032, -0.018, 0.0885, 0.097, 0.0035, metal).position.z = -0.0065;
  box('rear_sight_ear_r', -0.032, -0.018, 0.0885, 0.097, 0.0035, metal).position.z = 0.0065;
  box('front_sight', 0.142, 0.150, 0.085, 0.094, 0.0022, metal);
  const fdot = box('front_dot', 0.1495, 0.1505, 0.0905, 0.0925, 0.0012, dot);
  fdot.name = 'front_sight_dot';
  root.traverse((o) => {
    if (o.isMesh) {
      o.castShadow = false;
      o.receiveShadow = false;
    }
  });
  const muzzle = new Object3D();
  muzzle.name = 'socket_muzzle';
  muzzle.position.fromArray(PISTOL_MUZZLE);
  root.add(muzzle);
  const adsEye = new Object3D();
  adsEye.name = 'socket_ads';
  adsEye.position.fromArray(PISTOL_ADS_EYE);
  root.add(adsEye);
  return { object: root, muzzle, adsEye, isPlaceholder: true };
}
