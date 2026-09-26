// Baked indirect lighting (sky visibility + sunlight bounce), its render geometry, and the fitted
// shadow depth range. Node only (no WebGL): the geometry, the BVH rays and the math are pure.
import test from 'node:test';
import assert from 'node:assert/strict';
import { OrthographicCamera, Vector3 } from 'three';
import level from '../../src/data/test_range.json' with { type: 'json' };
import envCfg from '../../src/data/environment.json' with { type: 'json' };
import { applyWorldUVs, buildLevelSolids } from '../../src/level/levelGeometry.js';
import { CollisionWorld } from '../../src/physics/collisionWorld.js';
import { buildLightingGeometries } from '../../src/level/lightingGeometry.js';
import { bakeVertexLighting, probeSkyVisibility, srgbHexToLinear } from '../../src/engine/indirectBake.js';
import { Environment, sunDirectionFromAngles } from '../../src/engine/environment.js';

const solids = buildLevelSolids(level);
const world = new CollisionWorld(solids);
const sun = sunDirectionFromAngles(envCfg.sun.elevationDeg, envCfg.sun.azimuthDeg);
const geos = buildLightingGeometries(solids);
const albedo = () => [0.25, 0.25, 0.25];
geos.forEach((g) => bakeVertexLighting(g, world, { sunDirection: sun, albedoOf: albedo }));

const insideBox = (p, b, eps = 1e-4) =>
  p.x > b.min[0] + eps && p.x < b.max[0] - eps && p.y > b.min[1] + eps && p.y < b.max[1] - eps && p.z > b.min[2] + eps && p.z < b.max[2] - eps;
const boxes = solids.filter((s) => s.box).map((s) => s.box);

/** Baked values of the vertex of solid `id` nearest to `p` with a normal close to `n`. */
function bakedAt(id, p, n) {
  const i = solids.findIndex((s) => s.id === id);
  const g = geos[i];
  const pos = g.getAttribute('position');
  const nrm = g.getAttribute('normal');
  let best = -1;
  let bestD = Infinity;
  const q = new Vector3();
  for (let k = 0; k < pos.count; k++) {
    if (nrm.getX(k) * n[0] + nrm.getY(k) * n[1] + nrm.getZ(k) * n[2] < 0.9) continue;
    const d = q.fromBufferAttribute(pos, k).distanceTo(new Vector3(...p));
    if (d < bestD) {
      bestD = d;
      best = k;
    }
  }
  return { sky: g.getAttribute('ivSkyVis').getX(best), bounce: g.getAttribute('ivBounce').getX(best), dist: bestD };
}

test('lighting geometry: no triangle reaches from a visible part of a face into another solid', () => {
  // Points strictly inside every triangle (not on its edges, which may lie exactly on a box
  // boundary) must all be on the same side (inside / outside) of every other box; otherwise
  // baked light would be interpolated through a wall.
  const c = new Vector3();
  const a = new Vector3();
  const b = new Vector3();
  const d = new Vector3();
  let bad = 0;
  let tris = 0;
  geos.forEach((g, gi) => {
    const pos = g.getAttribute('position');
    const nrm = g.getAttribute('normal');
    const idx = g.index;
    const own = solids[gi].box;
    for (let t = 0; t < idx.count; t += 3) {
      tris++;
      a.fromBufferAttribute(pos, idx.getX(t));
      b.fromBufferAttribute(pos, idx.getX(t + 1));
      d.fromBufferAttribute(pos, idx.getX(t + 2));
      const off = new Vector3().fromBufferAttribute(nrm, idx.getX(t)).multiplyScalar(0.005);
      c.copy(a).add(b).add(d).divideScalar(3).add(off);
      const bary = (wa, wb, wd) => new Vector3().addScaledVector(a, wa).addScaledVector(b, wb).addScaledVector(d, wd).add(off);
      const samples = [c.clone(), bary(0.8, 0.1, 0.1), bary(0.1, 0.8, 0.1), bary(0.1, 0.1, 0.8)];
      for (const box of boxes) {
        if (box === own) continue;
        const states = samples.map((p) => insideBox(p, box));
        if (states.some((s) => s !== states[0])) {
          bad++;
          break;
        }
      }
    }
  });
  assert.equal(bad, 0, `${bad} of ${tris} triangles straddle another solid's boundary`);
});

test('lighting geometry keeps the metric world UVs of the collision geometry', () => {
  // same projection rule as applyWorldUVs: compare on a box face
  const i = solids.findIndex((s) => s.id === 'tunnel_wall_e');
  const g = geos[i];
  const pos = g.getAttribute('position');
  const nrm = g.getAttribute('normal');
  const uv = g.getAttribute('uv');
  for (let k = 0; k < pos.count; k += 7) {
    const x = pos.getX(k);
    const y = pos.getY(k);
    const z = pos.getZ(k);
    const nx = nrm.getX(k);
    const ny = nrm.getY(k);
    const nz = nrm.getZ(k);
    let u;
    let v;
    if (Math.abs(ny) >= Math.abs(nx) && Math.abs(ny) >= Math.abs(nz)) [u, v] = [x, -z];
    else if (Math.abs(nx) >= Math.abs(nz)) [u, v] = [nx > 0 ? -z : z, y];
    else [u, v] = [nz > 0 ? x : -x, y];
    assert.ok(Math.abs(uv.getX(k) - u) < 1e-5 && Math.abs(uv.getY(k) - v) < 1e-5, `uv at vertex ${k}`);
  }
  assert.ok(typeof applyWorldUVs === 'function');
});

test('baked sky visibility: open ground sees the whole sky, the tunnel interior almost none, wall bases about half', () => {
  const open = bakedAt('ground', [0, 0, 20], [0, 1, 0]);
  assert.ok(open.sky > 0.99, `open ground ${open.sky}`);
  const tunnelFloor = bakedAt('ground', [3, 0, -5.5], [0, 1, 0]);
  assert.ok(tunnelFloor.sky < 0.1, `tunnel floor ${tunnelFloor.sky}`);
  const tunnelWall = bakedAt('tunnel_wall_e', [3.8, 0.9, -5.5], [-1, 0, 0]);
  assert.ok(tunnelWall.sky < 0.1, `tunnel inner wall ${tunnelWall.sky}`);
  // floor right at the outside base of the tunnel's west wall: the wall hides about half the sky
  const base = bakedAt('ground', [1.9, 0, -5.5], [0, 1, 0]);
  assert.ok(base.sky > 0.3 && base.sky < 0.7, `wall base ${base.sky}`);
  // 6.5 m from the 2.5 m high south boundary wall a little sky is hidden near the horizon
  const far = bakedAt('ground', [0, 0, 25], [0, 1, 0]);
  assert.ok(far.sky > 0.85 && far.sky < 0.99, `ground 6.5 m from the boundary wall ${far.sky}`);
});

test('baked bounce: sunlit surfaces light nearby geometry, the dark tunnel still gets some through its openings', () => {
  const inTunnel = bakedAt('tunnel_wall_e', [3.8, 0.9, -5.5], [-1, 0, 0]);
  assert.ok(inTunnel.bounce > 0.005, `tunnel wall bounce ${inTunnel.bounce}`);
  const open = bakedAt('ground', [0, 0, 20], [0, 1, 0]);
  assert.equal(open.bounce, 0, 'nothing to bounce from on open ground');
  // bounce never exceeds what a white sunlit hemisphere could give
  for (const g of geos) {
    const b = g.getAttribute('ivBounce');
    for (let k = 0; k < b.count * 3; k++) assert.ok(b.array[k] >= 0 && b.array[k] <= 1, 'bounce in [0, 1]');
  }
});

test('sky-visibility probe (view model / targets) and deterministic bake', () => {
  const eyeOpen = probeSkyVisibility(world, new Vector3(0, 1.65, 12), { sunDirection: sun });
  const eyeTunnel = probeSkyVisibility(world, new Vector3(3, 1.05, -5.5), { sunDirection: sun });
  assert.ok(eyeOpen.skyVis > 0.99 && eyeTunnel.skyVis < 0.1, `open ${eyeOpen.skyVis} tunnel ${eyeTunnel.skyVis}`);
  const again = buildLightingGeometries(solids);
  bakeVertexLighting(again[0], world, { sunDirection: sun, albedoOf: albedo });
  assert.deepEqual(Array.from(again[0].getAttribute('ivSkyVis').array), Array.from(geos[0].getAttribute('ivSkyVis').array));
  assert.deepEqual(srgbHexToLinear('#ffffff'), [1, 1, 1]);
});

test('fitted shadow depth range contains every level caster wherever the player is (no clipped shadows)', () => {
  // Environment._fitShadowDepth without WebGL: a minimal stand-in with the fields it uses
  const cam = new OrthographicCamera();
  const env = {
    cfg: envCfg,
    sunDirection: sun,
    casterMinY: world.bounds.min.y,
    casterMaxY: world.bounds.max.y,
    sun: { shadow: { camera: cam, bias: 0 } },
    lightDistance: 0,
  };
  const x = new Vector3(0, 1, 0).cross(sun).normalize();
  const y = sun.clone().cross(x).normalize();
  const E = envCfg.sun.shadowExtent;
  const pos = world.geometry.getAttribute('position');
  const p = new Vector3();
  let worst = Infinity;
  for (const f of [new Vector3(0, 1.65, 12), new Vector3(-30, 1.65, 20), new Vector3(3, 1.05, -5.5), new Vector3(35, 0.5, -38), new Vector3(-27, 3.1, -6)]) {
    Environment.prototype._fitShadowDepth.call(env, f, y);
    const light = f.clone().addScaledVector(sun, env.lightDistance);
    for (let k = 0; k < pos.count; k++) {
      p.fromBufferAttribute(pos, k);
      const r = p.clone().sub(f);
      if (Math.abs(r.dot(x)) > E || Math.abs(r.dot(y)) > E) continue; // outside the footprint
      const depth = light.clone().sub(p).dot(sun); // distance from the light along its direction
      worst = Math.min(worst, depth - cam.near, cam.far - depth);
    }
    assert.ok(cam.far - cam.near < 120, `depth range ${cam.far - cam.near} m`);
    assert.ok(Math.abs(-env.sun.shadow.bias * (cam.far - cam.near) - envCfg.sun.shadowBiasMeters) < 1e-9, 'bias in metres');
  }
  assert.ok(worst > 0.4, `a caster came within ${worst} m of the near/far planes`);
});
