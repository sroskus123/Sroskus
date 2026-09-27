// Clearly marked PLACEHOLDER carbine built from primitives, used until the real IV-7 GLB
// exists. Same conventions as the art pipeline: metres, origin at the pistol grip,
// muzzle along +X, top +Y, right side +Z (glTF axes of a Blender export with muzzle +X).
// Orange buttpad and handguard band mark it as a placeholder in first person.

import { BoxGeometry, Color, CylinderGeometry, Group, Mesh, MeshStandardMaterial, Object3D } from 'three';

// Socket layout identical to the IV-7 GLB (socket_muzzle / socket_ads), so gameplay offsets
// do not change when the real model replaces the placeholder.
export const PLACEHOLDER_MUZZLE = [0.5759, 0.0917, 0];
export const PLACEHOLDER_ADS_EYE = [0.0179, 0.1617, 0];
const BODY_OFFSET = [0.0409, 0.0257, 0]; // primitive body was modelled with the muzzle at (0.535, 0.066)

export function createPlaceholderRifle() {
  const root = new Group();
  root.name = 'IV7_placeholder';
  const g = new Group();
  g.position.fromArray(BODY_OFFSET);
  root.add(g);
  const metal = new MeshStandardMaterial({ color: new Color('#2c2e30'), metalness: 0.55, roughness: 0.5 });
  const polymer = new MeshStandardMaterial({ color: new Color('#3a3934'), metalness: 0.0, roughness: 0.72 });
  const rubber = new MeshStandardMaterial({ color: new Color('#262522'), metalness: 0.0, roughness: 0.9 });
  const marker = new MeshStandardMaterial({ color: new Color('#e07b1f'), metalness: 0.0, roughness: 0.6 });

  const box = (name, x0, x1, y0, y1, hz, mat, rotZ = 0) => {
    const geo = new BoxGeometry(x1 - x0, y1 - y0, hz * 2);
    const m = new Mesh(geo, mat);
    m.name = name;
    m.position.set((x0 + x1) / 2, (y0 + y1) / 2, 0);
    m.rotation.z = rotZ;
    g.add(m);
    return m;
  };
  const cyl = (name, x0, x1, y, r, mat) => {
    const geo = new CylinderGeometry(r, r, x1 - x0, 16);
    geo.rotateZ(Math.PI / 2);
    const m = new Mesh(geo, mat);
    m.name = name;
    m.position.set((x0 + x1) / 2, y, 0);
    g.add(m);
    return m;
  };

  box('upper_receiver', -0.1, 0.17, 0.035, 0.095, 0.026, metal);
  box('lower_receiver', -0.035, 0.1, 0.0, 0.04, 0.024, metal);
  box('handguard', 0.17, 0.4, 0.036, 0.096, 0.03, polymer);
  box('placeholder_band', 0.255, 0.285, 0.035, 0.097, 0.031, marker);
  box('top_rail', -0.085, 0.385, 0.095, 0.104, 0.011, metal);
  cyl('barrel', 0.4, 0.49, 0.066, 0.0095, metal);
  cyl('muzzle_device', 0.49, 0.535, 0.066, 0.013, metal);
  box('front_sight', 0.358, 0.372, 0.104, 0.132, 0.0035, metal);
  box('front_sight_ears_l', 0.355, 0.375, 0.104, 0.134, 0.002, metal).position.z = 0.011;
  box('front_sight_ears_r', 0.355, 0.375, 0.104, 0.134, 0.002, metal).position.z = -0.011;
  box('rear_sight', -0.072, -0.052, 0.104, 0.118, 0.012, metal);
  box('rear_aperture_l', -0.068, -0.056, 0.118, 0.134, 0.0035, metal).position.z = 0.008;
  box('rear_aperture_r', -0.068, -0.056, 0.118, 0.134, 0.0035, metal).position.z = -0.008;
  const mag = box('magazine', 0.025, 0.088, -0.15, 0.0, 0.0125, polymer, 0.2);
  mag.position.x += 0.012;
  const grip = box('pistol_grip', -0.035, 0.005, -0.11, 0.0, 0.015, rubber, -0.3);
  grip.position.x -= 0.012;
  box('trigger_guard', -0.005, 0.07, -0.024, -0.017, 0.009, metal);
  box('trigger', 0.02, 0.028, -0.02, 0.0, 0.003, metal);
  cyl('buffer_tube', -0.23, -0.1, 0.064, 0.0155, metal);
  box('stock', -0.335, -0.2, 0.0, 0.088, 0.022, polymer);
  box('buttpad', -0.35, -0.335, -0.004, 0.092, 0.024, marker);
  box('charging_handle', -0.105, -0.085, 0.08, 0.1, 0.03, metal);

  // simple tube optic on the rail (open aperture on the sight axis so ADS looks through it)
  const axisY = PLACEHOLDER_ADS_EYE[1] - BODY_OFFSET[1];
  const ox0 = 0.098 - BODY_OFFSET[0];
  const ox1 = 0.158 - BODY_OFFSET[0];
  const wall = (y0, y1, hz, z) => {
    const m = box('optic_wall', ox0, ox1, y0, y1, hz, metal);
    m.position.z = z;
    return m;
  };
  wall(axisY + 0.013, axisY + 0.022, 0.022, 0); // top
  wall(axisY - 0.022, axisY - 0.013, 0.022, 0); // bottom
  wall(axisY - 0.013, axisY + 0.013, 0.0045, 0.0175); // right
  wall(axisY - 0.013, axisY + 0.013, 0.0045, -0.0175); // left
  box('optic_mount', ox0 + 0.01, ox1 - 0.01, 0.104, axisY - 0.022, 0.012, metal);
  const dot = new Mesh(new CylinderGeometry(0.0009, 0.0009, 0.0005, 12), new MeshStandardMaterial({ color: new Color('#ff2a1a'), emissive: new Color('#ff2a1a'), emissiveIntensity: 4 }));
  dot.name = 'optic_reticle';
  dot.rotation.z = Math.PI / 2;
  dot.position.set(ox1 - 0.004, axisY, 0);
  g.add(dot);

  root.traverse((o) => {
    if (o.isMesh) {
      o.castShadow = false;
      o.receiveShadow = false;
    }
  });

  const muzzle = new Object3D();
  muzzle.name = 'socket_muzzle';
  muzzle.position.fromArray(PLACEHOLDER_MUZZLE);
  root.add(muzzle);
  const adsEye = new Object3D();
  adsEye.name = 'socket_ads';
  adsEye.position.fromArray(PLACEHOLDER_ADS_EYE);
  root.add(adsEye);
  return { object: root, muzzle, adsEye, isPlaceholder: true };
}
