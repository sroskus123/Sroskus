// Optic definitions, ADS alignment math, reticle minimum-size / SDF coverage, sensitivity scaling, eyebox,
// loadout validation, bot roles and the armory crate placement in the level data (Node, no browser).
import test from 'node:test';
import assert from 'node:assert/strict';
import { Vector3 } from 'three';
import opticsData from '../../../Shared/config/optics.json' with { type: 'json' };
import weaponsData from '../../src/data/weapons.json' with { type: 'json' };
import attachments from '../../src/data/attachments.json' with { type: 'json' };
import opticsWeb from '../../src/data/optics_web.json' with { type: 'json' };
import {
  IRONS,
  OPTIC_IDS,
  adsPoseFor,
  botKit,
  eyeboxFactor,
  getOpticDef,
  opticChoices,
  opticName,
  opticViewModel,
  pxPerRad,
  resolveOpticId,
  resolveSpareId,
  sensitivityFactor,
  strokeDilation,
  validateOpticLoadout,
} from '../../src/weapons/optics.js';
import { viewModelPointInCamera } from '../../src/weapons/viewModelMotion.js';
import { WeaponSystem, lookQuaternion } from '../../src/weapons/weaponSystem.js';
import { createRng } from '../../src/util/rng.js';
import { armoryBoxes } from '../../src/level/levelGeometry.js';
import { loadLevelData } from '../../src/game/levels.js';
import { horizontalToVerticalFov } from '../../src/util/math.js';

const DEG = Math.PI / 180;
const rifleVm = weaponsData.iv7_carbine.viewModel;

test('choices: five optics + iron sights with the Czech names the user asked for; ids resolve, aliases work', () => {
  const c = opticChoices();
  assert.deepEqual(c.map((x) => x.id), ['IVH1', 'IVR1', 'IVP2', 'IVS3', 'IVS6', 'irons']);
  assert.deepEqual(c.map((x) => x.name), ['Holografický zaměřovač 1×', 'Kolimátor 1×', 'Hranolový 2×', 'Puškohled 3×', 'Puškohled 6×', 'Mechanická mířidla']);
  assert.equal(resolveOpticId('collimator'), 'IVR1');
  assert.equal(resolveOpticId('irons'), IRONS);
  assert.equal(resolveOpticId('nope'), null);
  assert.equal(resolveSpareId('none'), null);
  assert.equal(resolveSpareId(null), null);
  assert.equal(resolveSpareId('irons'), null);
  assert.equal(resolveSpareId('bad'), undefined);
  assert.equal(opticName(null), 'Žádná');
  assert.deepEqual(OPTIC_IDS, opticsData.optics.map((o) => o.id));
});

test('optic definitions follow Shared/config/optics.json: mode, magnification, ADS time, eye = rail + socket_eye', () => {
  const modes = { IVH1: 'collimated', IVR1: 'collimated', IVP2: 'pip', IVS3: 'pip', IVS6: 'fullscreen' };
  for (const o of opticsData.optics) {
    const d = getOpticDef(o.id);
    assert.equal(d.mode, modes[o.id], o.id);
    assert.equal(d.magnification, o.magnification);
    assert.equal(d.adsTime, o.ads_time_s);
    const eye = o.mount_on_iv7.socket_eye_rifle_m.gltf_yup;
    const rail = o.mount_on_iv7.socket_rail_rifle_m.gltf_yup;
    const se = o.sockets_optic_frame_m.gltf_yup.socket_eye;
    for (let k = 0; k < 3; k++) {
      assert.ok(Math.abs(d.eyeRifle[k] - eye[k]) < 1e-9);
      assert.ok(Math.abs(rail[k] + se[k] - eye[k]) < 1e-6, `${o.id} eye = rail + socket_eye`);
    }
    // 1x sights: no zoom (user requirement); magnified: the main camera does not zoom either (PiP / overlay do)
    assert.equal(d.worldFovMultiplier, 1);
    assert.ok(d.assets && d.assets.glb.endsWith('.glb') && d.assets.lod1.endsWith('_LOD1.glb'), `${o.id} web assets`);
    assert.ok(d.reticle.sdf && d.reticle.sdf.size > 0, `${o.id} SDF`);
  }
  const irons = getOpticDef(IRONS);
  assert.deepEqual(irons.eyeRifle, rifleVm.adsEyeLocal);
  assert.equal(irons.adsTime, weaponsData.iv7_carbine.adsTime);
  assert.equal(getOpticDef('IVS6').overlay.vfovDeg, opticsData.optics.find((o) => o.id === 'IVS6').ads_overlay.vertical_fov_deg_when_drawn_full_height);
});

test('ADS pose per optic: the optic eye point lands on the camera and the sight axis is the camera axis (parallax-free aim)', () => {
  for (const id of [...OPTIC_IDS, IRONS]) {
    const d = getOpticDef(id);
    const vm = opticViewModel(rifleVm, d);
    const eye = viewModelPointInCamera(vm, d.eyeRifle, 1);
    assert.ok(eye.length() < 1e-9, `${id}: eye ${eye.toArray()}`);
    if (id === IRONS) continue;
    const front = viewModelPointInCamera(vm, d.axisFrontRifle, 1);
    const rear = viewModelPointInCamera(vm, d.axisRearRifle, 1);
    const axis = front.clone().sub(rear).normalize();
    assert.ok(axis.distanceTo(new Vector3(0, 0, -1)) < 1e-9, `${id}: axis ${axis.toArray()}`);
    // the axis line passes through the eye: lateral offset of the eye (camera origin) from the axis
    const lateral = rear.clone().negate().projectOnPlane(axis).length();
    assert.ok(lateral < 1e-9, `${id}: lateral ${lateral}`);
    const p = adsPoseFor(d);
    assert.deepEqual(p.adsPosition, [-d.eyeRifle[2], -d.eyeRifle[1], d.eyeRifle[0]]);
  }
  // the IV-R1 twin of the built-in optic keeps the rifle's own ADS pose (weapons.json)
  const a = adsPoseFor(getOpticDef('IVR1')).adsPosition;
  for (let k = 0; k < 3; k++) assert.ok(Math.abs(a[k] - rifleVm.adsPosition[k]) < 1e-4, `IV-R1 eye vs socket_ads ${a} ${rifleVm.adsPosition}`);
});

test('gameplay muzzle and aim per optic: ADS muzzle = drawn pose of that optic; the aim (sight axis) = hitscan direction incl. recoil', () => {
  const def = weaponsData.iv7_carbine;
  for (const id of [...OPTIC_IDS, IRONS]) {
    const d = getOpticDef(id);
    const vm = opticViewModel(def.viewModel, d);
    const ads = viewModelPointInCamera(vm, vm.muzzleLocal, 1).toArray();
    const w = new WeaponSystem({ def, rng: createRng(5) });
    w.setViewModel(vm, def.muzzleOffsetHip, ads);
    const m1 = w.muzzleOffset(1);
    assert.ok(m1.distanceTo(new Vector3().fromArray(ads)) < 1e-9, id);
    // hip muzzle is unchanged by the optic (it is the drawn hip pose)
    assert.ok(w.muzzleOffset(0).distanceTo(new Vector3().fromArray(def.muzzleOffsetHip)) < 1e-9, id);
    // recoil moves aim and camera together: the camera forward (screen centre = collimated reticle in full ADS)
    // equals the hitscan direction
    w.recoil.pitch = 0.021;
    w.recoil.yaw = -0.007;
    const yaw = 0.3;
    const pitch = -0.05;
    const aim = w.aimDirection(yaw, pitch);
    const camFwd = new Vector3(0, 0, -1).applyQuaternion(lookQuaternion(yaw + w.recoil.yaw, pitch + w.recoil.pitch));
    assert.ok(aim.angleTo(camFwd) < 1e-9, id);
  }
});

test('reticle: minimum on-screen size rule and SDF spread cover the needed dilation at 960x540 and 1080p', () => {
  assert.equal(strokeDilation(2, 1, 1.25), 0);
  assert.ok(Math.abs(strokeDilation(0.5, 10, 1.25) - (6.25 - 0.5)) < 1e-12);
  const hipV = horizontalToVerticalFov(80, 16 / 9);
  for (const id of OPTIC_IDS) {
    const d = getOpticDef(id);
    const R = d.reticle;
    const texPerRad = R.sdf.size / (R.fieldUnits * R.unitInRad);
    for (const H of [540, 1080]) {
      let pxPerRadShown;
      if (d.mode === 'collimated') pxPerRadShown = pxPerRad(hipV * d.worldFovMultiplier, H);
      else if (d.mode === 'fullscreen') pxPerRadShown = pxPerRad(d.overlay.vfovDeg, H);
      else {
        // PiP: ocular disc on screen (view-model camera 50.5 deg) spans 2 tan(true_fov / 2)
        const depth = Math.abs(d.eyeRifle[0] - d.axisRearRifle[0]);
        const disc = (2 * d.lensRadius * pxPerRad(rifleVm.fovVerticalDeg, H)) / depth;
        pxPerRadShown = disc / (2 * Math.tan((d.trueFovDeg * DEG) / 2));
      }
      const tpp = texPerRad / pxPerRadShown; // SDF texels per screen pixel
      const texPerUnit = R.sdf.size / R.fieldUnits;
      for (const hw of [R.litHalfWidth, R.etchHalfWidth].filter((x) => x > 0)) {
        const k = strokeDilation(hw * texPerUnit, tpp, R.minStrokePx);
        assert.ok(k <= R.sdf.spread - tpp + 1e-9, `${id} @${H}p: dilation ${k.toFixed(2)} texels > spread ${R.sdf.spread} - tpp ${tpp.toFixed(2)}`);
      }
      if (R.dotRadius > 0) {
        // the centre dot is analytic: its radius on screen is at least min_dot_diameter_px / 2
        const rPx = Math.max(R.dotRadius * texPerUnit, 0.5 * R.minDotPx * tpp) / tpp;
        assert.ok(rPx >= R.minDotPx / 2 - 1e-9, `${id} dot`);
      }
    }
  }
  // the documented rule values
  for (const o of opticsData.optics) {
    assert.equal(o.reticle.render_hints.min_dot_diameter_px, 2.5);
    assert.equal(o.reticle.render_hints.min_stroke_px, 1.25);
  }
});

test('mouse sensitivity scales with magnification (setting): 1x no zoom = 1, PiP 1/M, 6x = FOV ratio; off -> only the multiplier', () => {
  const hipV = horizontalToVerticalFov(80, 16 / 9);
  const f = (id, ads, curV, scaling = true, multiplier = 1) => sensitivityFactor({ def: getOpticDef(id), ads, hipVfovDeg: hipV, curVfovDeg: curV, scaling, multiplier });
  assert.equal(f('IVR1', 0, hipV), 1);
  assert.ok(Math.abs(f('IVR1', 1, hipV) - 1) < 1e-12);
  assert.ok(Math.abs(f('IVH1', 1, hipV) - 1) < 1e-12);
  assert.ok(Math.abs(f('IVP2', 1, hipV) - 0.5) < 1e-12);
  assert.ok(Math.abs(f('IVS3', 1, hipV) - 1 / 3) < 1e-12);
  const v6 = getOpticDef('IVS6').overlay.vfovDeg;
  const expect6 = Math.tan((v6 * DEG) / 2) / Math.tan((hipV * DEG) / 2);
  assert.ok(Math.abs(f('IVS6', 1, v6) - expect6) < 1e-12);
  assert.ok(expect6 < 0.1, `6x factor ${expect6}`);
  // irons: the slight ADS zoom (0.82 of the horizontal FOV)
  const vIrons = horizontalToVerticalFov(80 * 0.82, 16 / 9);
  assert.ok(Math.abs(f(IRONS, 1, vIrons) - Math.tan((vIrons * DEG) / 2) / Math.tan((hipV * DEG) / 2)) < 1e-12);
  // setting off: no magnification scaling, the ADS multiplier still applies (blended with ADS)
  assert.equal(f('IVS3', 1, hipV, false, 1), 1);
  assert.ok(Math.abs(f('IVS3', 1, hipV, false, 0.6) - 0.6) < 1e-12);
  assert.ok(Math.abs(f('IVS3', 1, hipV, true, 0.6) - 0.2) < 1e-12);
  // halfway through ADS: in between, monotonic
  const h = f('IVS3', 0.5, hipV);
  assert.ok(h < 1 && h > 1 / 3);
});

test('eyebox: full image on the axis at the design eye relief, fades off-axis / at a wrong eye relief', () => {
  const d = getOpticDef('IVS3');
  assert.equal(eyeboxFactor(d, 0, 0), 1);
  assert.equal(eyeboxFactor(d, d.eyeboxRadius * 0.9, 0.005), 1);
  assert.equal(eyeboxFactor(d, d.eyeboxRadius * 3, 0), 0);
  assert.equal(eyeboxFactor(d, 0, 0.08), 0);
  const mid = eyeboxFactor(d, d.eyeboxRadius * 1.5, 0);
  assert.ok(mid > 0 && mid < 1);
});

test('loadout validation: primary from the choices, spare an optic or none, never the same as the primary', () => {
  assert.deepEqual(validateOpticLoadout({ optic: 'IVS6', spare: 'IVR1' }), { ok: true, optic: 'IVS6', spare: 'IVR1' });
  assert.deepEqual(validateOpticLoadout({ optic: 'irons', spare: 'IVS3' }), { ok: true, optic: 'irons', spare: 'IVS3' });
  assert.deepEqual(validateOpticLoadout({ optic: 'collimator', spare: 'none' }), { ok: true, optic: 'IVR1', spare: null });
  assert.equal(validateOpticLoadout({ optic: 'IVS3', spare: 'IVS3' }).reason, 'spare_equals_primary');
  assert.equal(validateOpticLoadout({ optic: 'X' }).reason, 'unknown_optic');
  assert.equal(validateOpticLoadout({ optic: 'IVS3', spare: 'X' }).reason, 'unknown_spare');
  const d = attachments.loadoutDefault;
  assert.ok(validateOpticLoadout(d).ok);
  assert.equal(d.optic, opticsData.default, 'default optic = optics.json default');
});

test('bots get optics by role (valid kits, marksman with the 6x, the pattern repeats)', () => {
  const kits = [0, 1, 2, 3, 4, 5, 6].map(botKit);
  for (const k of kits) assert.ok(validateOpticLoadout({ optic: k.optic, spare: k.spare }).ok, JSON.stringify(k));
  assert.equal(kits.find((k) => k.role === 'odstrelovac').optic, 'IVS6');
  assert.ok(new Set(kits.slice(0, 5).map((k) => k.optic)).size >= 4, 'varied optics in a team');
  assert.deepEqual(botKit(attachments.bots.pattern.length), botKit(0));
});

test('web asset data: files named by the tool exist in the public set and are under the artifact limit after base64', async () => {
  const fs = await import('node:fs');
  const path = await import('node:path');
  const pub = path.resolve(import.meta.dirname, '../../public');
  for (const [id, e] of Object.entries(opticsWeb.optics)) {
    for (const f of [e.glb, e.lod1, e.sdf.file, ...(e.overlay ? [e.overlay.file] : [])]) {
      const p = path.join(pub, f);
      assert.ok(fs.existsSync(p), `${id}: ${f}`);
      const n = fs.statSync(p).size;
      assert.ok(Math.ceil(n / 3) * 4 < 15 * 1024 * 1024, `${f} too big for the artifact host`);
    }
  }
  const rifle = path.join(pub, opticsWeb.rifle.glb);
  assert.ok(fs.existsSync(rifle));
  assert.ok(Math.ceil(fs.statSync(rifle).size / 3) * 4 < 15 * 1024 * 1024, 'rifle too big after base64');
  // textures: WebP / JPEG only (no PNG in the web GLBs), no transmission extension left
  const b = fs.readFileSync(rifle);
  const json = JSON.parse(b.subarray(20, 20 + b.readUInt32LE(12)).toString());
  assert.ok(json.images.every((im) => im.mimeType === 'image/webp' || im.mimeType === 'image/jpeg'), JSON.stringify(json.images.map((i) => i.mimeType)));
  assert.ok(!(json.extensionsUsed || []).includes('KHR_materials_transmission'));
});

test('armory crates: one per team at the spawn in both levels, clear of every spawn capsule, reachable, solid', async () => {
  for (const id of ['test_range', 'ai_arena']) {
    const level = await loadLevelData(id);
    const list = level.match.armories;
    assert.deepEqual(list.map((a) => a.team).sort(), [0, 1, 2], id);
    const boxes = armoryBoxes(level);
    for (const [i, a] of list.entries()) {
      const b = boxes[i];
      const spawns = level.match.teamSpawns[a.team];
      let nearest = Infinity;
      for (const s of spawns) {
        const dx = Math.max(b.min[0] - s.pos[0], 0, s.pos[0] - b.max[0]);
        const dz = Math.max(b.min[2] - s.pos[2], 0, s.pos[2] - b.max[2]);
        const gap = Math.hypot(dx, dz) - 0.35; // capsule radius
        nearest = Math.min(nearest, Math.hypot(a.center[0] - s.pos[0], a.center[2] - s.pos[2]));
        assert.ok(gap > 0.5, `${id} ${a.id}: ${gap.toFixed(2)} m from a spawn capsule`);
      }
      assert.ok(nearest < 8, `${id} ${a.id}: ${nearest.toFixed(1)} m from its team's spawns`);
      assert.ok(b.max[1] - b.min[1] < 0.9, 'low crate');
    }
  }
});
