// Trees and shrubs of generated levels (map art pass phase 1): Blender-generated models from
// assets/environment/vegetation.glb (Art/Source/Blender/environment/vegetation.py) instanced from the tables that
// Tools/level/export_web_level.py writes into kh_world.glb (asset.extras.iv.vegetation).
//
//  - one InstancedMesh per model x LOD (LOD0 < 35 m, LOD1 < 90 m, LOD2 beyond; shrubs 25 / 60 m) with hysteresis;
//    the LOD buckets are rebuilt every 4th rendered frame or after the camera moved > 2 m, with a coarse per-instance
//    frustum test (instances within 30 m always stay: they may cast shadows into view);
//  - one shared material for bark and foliage (bark = texture array layer + blend from the vertex data, foliage =
//    alpha-tested atlas cards with coverage-preserving mip alpha, crown-spherical normals, baked per-card occlusion,
//    fake translucency against the sun) and gentle wind sway in the vertex shader (trunk bend by height, branch
//    sway by flex, leaf flutter by phase);
//  - the backdrop forest: impostor-LOD trees scattered over the forest part of the backdrop ring at load time.
// Visual only: nothing here is in the collision world, so AI sight / bullets are unaffected (tree trunks and
// shrub blocks keep their collision in kh_collision.glb, see Docs/GAMEPLAY_CONTRACTS.md).
// Browser only.

import {
  BufferAttribute,
  Color,
  DataArrayTexture,
  DoubleSide,
  Float32BufferAttribute,
  Frustum,
  Group,
  InstancedBufferAttribute,
  InstancedMesh,
  LinearFilter,
  LinearMipmapLinearFilter,
  Matrix4,
  MeshDepthMaterial,
  MeshStandardMaterial,
  NoColorSpace,
  Quaternion,
  RepeatWrapping,
  RGBAFormat,
  SRGBColorSpace,
  Sphere,
  Texture,
  UnsignedByteType,
  Vector3,
  ClampToEdgeWrapping,
} from 'three';
import { decodeImage, glbImageBytes } from './terrainMaterial.js';
import { parseGlb, readAccessor } from './levelAssets.js';

const _m = new Matrix4();
const _q = new Quaternion();
const _p = new Vector3();
const _s = new Vector3();
const _y = new Vector3(0, 1, 0);
const _frustum = new Frustum();
const _pm = new Matrix4();
const _sph = new Sphere();

/** Shared uniforms of all vegetation materials (time, wind, sun). */
export function createVegetationUniforms() {
  return {
    ivTime: { value: 0 },
    ivWindDir: { value: new Vector3(0.8, 0, 0.6).normalize() },
    ivWindStrength: { value: 1.0 },
    ivSunDirView: { value: new Vector3(0, 1, 0) },
    ivSunColor: { value: new Color(1, 1, 1) },
  };
}

function imageTexture(bitmap, srgb, repeat = false) {
  const t = new Texture(bitmap);
  t.flipY = false;
  t.colorSpace = srgb ? SRGBColorSpace : NoColorSpace;
  t.wrapS = t.wrapT = repeat ? RepeatWrapping : ClampToEdgeWrapping;
  t.minFilter = LinearMipmapLinearFilter;
  t.magFilter = LinearFilter;
  t.generateMipmaps = true;
  t.needsUpdate = true;
  return t;
}

function arrayTexture(bitmap, layers, srgb) {
  const size = bitmap.width;
  const t = new DataArrayTexture(bitmap, size, size, layers); // strip image -> texSubImage3D (see terrainMaterial.js)
  t.format = RGBAFormat;
  t.type = UnsignedByteType;
  t.colorSpace = srgb ? SRGBColorSpace : NoColorSpace;
  t.wrapS = t.wrapT = RepeatWrapping;
  t.minFilter = LinearMipmapLinearFilter;
  t.magFilter = LinearFilter;
  t.generateMipmaps = true;
  t.needsUpdate = true;
  return t;
}

/** Decodes the images of vegetation.glb (atlases, bark array, hedge surface). */
export async function loadVegetationTextures(vegGlb, maxAnisotropy = 8) {
  const iv = vegGlb.json.asset.extras.iv;
  const im = iv.images;
  const dec = async (k) => {
    const { bytes, mime } = glbImageBytes(vegGlb, im[k]);
    return decodeImage(bytes, mime);
  };
  const [fol, foln, grass, hedge, hedgen, bark, barkn] = await Promise.all(['foliage', 'foliageNormal', 'grass', 'hedge', 'hedgeNormal', 'bark', 'barkNormal'].map(dec));
  const t = {
    foliage: imageTexture(fol, true),
    foliageNormal: imageTexture(foln, false),
    grass: imageTexture(grass, true),
    hedge: imageTexture(hedge, true, true),
    hedgeNormal: imageTexture(hedgen, false, true),
    bark: arrayTexture(bark, iv.barkLayers.length, true),
    barkNormal: arrayTexture(barkn, iv.barkLayers.length, false),
  };
  for (const k of ['foliage', 'foliageNormal', 'hedge', 'hedgeNormal', 'bark', 'barkNormal']) t[k].anisotropy = Math.min(4, maxAnisotropy);
  return t;
}

const GLSL_TANGENT = `
mat3 ivTangentFrame( vec3 eye_pos, vec3 surf_norm, vec2 uv ) {
	vec3 q0 = dFdx( eye_pos.xyz ); vec3 q1 = dFdy( eye_pos.xyz );
	vec2 st0 = dFdx( uv.st ); vec2 st1 = dFdy( uv.st );
	vec3 N = surf_norm;
	vec3 q1perp = cross( q1, N ); vec3 q0perp = cross( N, q0 );
	vec3 T = q1perp * st0.x + q0perp * st1.x;
	vec3 B = q1perp * st0.y + q0perp * st1.y;
	float det = max( dot( T, T ), dot( B, B ) );
	float scale = ( det == 0.0 ) ? 0.0 : inversesqrt( det );
	return mat3( T * scale, B * scale, N );
}`;

/**
 * The shared bark + foliage material. Vertex data: _ivveg (x material code, y flex, z occlusion, w phase), color
 * (tint / 1.4), instanceColor (per-instance variation).
 */
export function createVegetationMaterial(textures, uniforms, { uvScale = 32 } = {}) {
  const mat = new MeshStandardMaterial({ color: 0xffffff, roughness: 0.78, metalness: 0, side: DoubleSide, vertexColors: true, alphaTest: 0.5 });
  mat.alphaToCoverage = true;
  const u = {
    ivFoliage: { value: textures.foliage },
    ivFoliageN: { value: textures.foliageNormal },
    ivBark: { value: textures.bark },
    ivBarkN: { value: textures.barkNormal },
    ivAtlasSize: { value: 1024 },
  };
  mat.onBeforeCompile = (shader) => {
    Object.assign(shader.uniforms, uniforms, u);
    shader.vertexShader = shader.vertexShader
      .replace(
        '#include <common>',
        `#include <common>
attribute vec4 _ivveg;
uniform float ivTime;
uniform vec3 ivWindDir;
uniform float ivWindStrength;
varying vec4 vIvVeg;
varying vec2 vIvUv;
varying float vIvLeaf;`,
      )
      .replace(
        '#include <begin_vertex>',
        `#include <begin_vertex>
vIvVeg = _ivveg;
vIvLeaf = step( 0.99, _ivveg.x );
vIvUv = uv * ${uvScale.toFixed(1)};
{
	#ifdef USE_INSTANCING
	vec3 ivOrigin = ( modelMatrix * instanceMatrix * vec4( 0.0, 0.0, 0.0, 1.0 ) ).xyz;
	mat3 ivInv = inverse( mat3( instanceMatrix ) );
	#else
	vec3 ivOrigin = ( modelMatrix * vec4( 0.0, 0.0, 0.0, 1.0 ) ).xyz;
	mat3 ivInv = mat3( 1.0 );
	#endif
	float flex = _ivveg.y;
	float ph = dot( ivOrigin.xz, vec2( 0.071, 0.053 ) );
	float gust = 0.6 + 0.4 * sin( ivTime * 0.31 + ivOrigin.x * 0.013 + ivOrigin.z * 0.009 );
	float sway = ( sin( ivTime * 0.9 + ph ) + 0.35 * sin( ivTime * 2.3 + ph * 1.7 ) ) * gust * ivWindStrength;
	vec3 wLocal = ivInv * ivWindDir;
	float h = max( transformed.y, 0.0 );
	// trunk / limb bend (grows with height and flex), leaf flutter on the cards
	transformed += wLocal * ( 0.004 * h * h * 0.08 + flex * flex * 0.12 ) * sway;
	float flutter = sin( ivTime * 7.0 + _ivveg.w * 40.0 + transformed.y * 2.0 ) * 0.025 * flex * vIvLeaf * ivWindStrength;
	transformed += normalize( objectNormal + vec3( 0.001 ) ) * flutter;
}`,
      );
    shader.fragmentShader = shader.fragmentShader
      .replace(
        '#include <common>',
        `#include <common>
precision highp sampler2DArray;
uniform sampler2D ivFoliage;
uniform sampler2D ivFoliageN;
uniform sampler2DArray ivBark;
uniform sampler2DArray ivBarkN;
uniform float ivAtlasSize;
uniform vec3 ivSunDirView;
uniform vec3 ivSunColor;
varying vec4 vIvVeg;
varying vec2 vIvUv;
varying float vIvLeaf;
${GLSL_TANGENT}`,
      )
      .replace(
        '#include <map_fragment>',
        `vec3 ivNT = vec3( 0.0, 0.0, 1.0 );
if ( vIvLeaf > 0.5 ) {
	vec4 tx = texture2D( ivFoliage, vIvUv );
	// coverage-preserving alpha in the lower mips (foliage does not thin out with distance)
	vec2 duv = fwidth( vIvUv ) * ivAtlasSize;
	float mip = max( 0.0, log2( max( duv.x, duv.y ) ) );
	tx.a *= 1.0 + mip * 0.45;
	diffuseColor *= tx;
	ivNT = texture2D( ivFoliageN, vIvUv ).xyz * 2.0 - 1.0;
} else {
	float code = vIvVeg.x * 255.0;
	float layer = floor( code / 50.0 + 0.001 );
	float blend = mod( code, 50.0 ) / 49.0;
	vec3 b0 = texture( ivBark, vec3( vIvUv, layer ) ).rgb;
	vec3 n0 = texture( ivBarkN, vec3( vIvUv, layer ) ).xyz;
	if ( blend > 0.01 ) {
		b0 = mix( b0, texture( ivBark, vec3( vIvUv, layer + 1.0 ) ).rgb, blend );
		n0 = mix( n0, texture( ivBarkN, vec3( vIvUv, layer + 1.0 ) ).xyz, blend );
	}
	diffuseColor.rgb *= b0;
	ivNT = n0 * 2.0 - 1.0;
}`,
      )
      .replace('#include <color_fragment>', '#include <color_fragment>\ndiffuseColor.rgb *= 1.4;\ndiffuseColor.rgb *= mix( 1.0, vIvVeg.z, 0.55 );')
      .replace(
        '#include <normal_fragment_begin>',
        `float faceDirection = gl_FrontFacing ? 1.0 : - 1.0;
vec3 normal = normalize( vNormal );
if ( vIvLeaf < 0.5 ) normal *= faceDirection;
vec3 nonPerturbedNormal = normal;`,
      )
      .replace(
        '#include <normal_fragment_maps>',
        `{
	mat3 tbn = ivTangentFrame( - vViewPosition, normal, vIvUv );
	vec3 nt = ivNT;
	nt.xy *= ( vIvLeaf > 0.5 ) ? 0.6 : 1.0;
	normal = normalize( tbn * nt );
}`,
      )
      .replace('#include <roughnessmap_fragment>', 'float roughnessFactor = vIvLeaf > 0.5 ? 0.85 : 0.88;')
      .replace(
        '#include <aomap_fragment>',
        `#include <aomap_fragment>
if ( vIvLeaf > 0.5 ) {
	// foliage: occlusion softened (shaded leaves stay dark green, not black), little specular (no grey sheen)
	reflectedLight.indirectDiffuse *= mix( 0.55, 1.0, vIvVeg.z ) * 1.25;
	reflectedLight.indirectSpecular *= 0.3 * vIvVeg.z;
	reflectedLight.directSpecular *= 0.35;
} else {
	reflectedLight.indirectDiffuse *= vIvVeg.z;
	reflectedLight.indirectSpecular *= vIvVeg.z * vIvVeg.z;
}`,
      )
      .replace(
        '#include <opaque_fragment>',
        `{
	// fake translucency: leaves glow a little when the sun is behind them (thin cards, back-lit)
	vec3 vdir = normalize( vViewPosition );
	float back = pow( clamp( dot( vdir, ivSunDirView ), 0.0, 1.0 ), 3.0 );
	float wrap = clamp( dot( - normal, ivSunDirView ) * 0.5 + 0.5, 0.0, 1.0 );
	outgoingLight += vIvLeaf * diffuseColor.rgb * ivSunColor * ( back * 0.3 + wrap * 0.05 ) * mix( 0.4, 1.0, vIvVeg.z );
}
#include <opaque_fragment>`,
      );
  };
  mat.customProgramCacheKey = () => 'iv-vegetation-1';
  return mat;
}

/**
 * Shadow-pass material of the vegetation: cards cut out by the foliage atlas alpha (not solid quads), same wind as
 * the visible material (so shadows sway with the leaves).
 */
export function createVegetationDepthMaterial(textures, uniforms, { uvScale = 32 } = {}) {
  const m = new MeshDepthMaterial({ side: DoubleSide });
  m.onBeforeCompile = (shader) => {
    Object.assign(shader.uniforms, uniforms, { ivFoliage: { value: textures.foliage }, ivAtlasSize: { value: 1024 } });
    shader.vertexShader = shader.vertexShader
      .replace(
        '#include <common>',
        `#include <common>
attribute vec4 _ivveg;
uniform float ivTime;
uniform vec3 ivWindDir;
uniform float ivWindStrength;
varying vec2 vIvUv;
varying float vIvLeaf;`,
      )
      .replace(
        '#include <begin_vertex>',
        `#include <begin_vertex>
vIvLeaf = step( 0.99, _ivveg.x );
vIvUv = uv * ${uvScale.toFixed(1)};
{
	#ifdef USE_INSTANCING
	vec3 ivOrigin = ( modelMatrix * instanceMatrix * vec4( 0.0, 0.0, 0.0, 1.0 ) ).xyz;
	mat3 ivInv = inverse( mat3( instanceMatrix ) );
	#else
	vec3 ivOrigin = ( modelMatrix * vec4( 0.0, 0.0, 0.0, 1.0 ) ).xyz;
	mat3 ivInv = mat3( 1.0 );
	#endif
	float flex = _ivveg.y;
	float ph = dot( ivOrigin.xz, vec2( 0.071, 0.053 ) );
	float gust = 0.6 + 0.4 * sin( ivTime * 0.31 + ivOrigin.x * 0.013 + ivOrigin.z * 0.009 );
	float sway = ( sin( ivTime * 0.9 + ph ) + 0.35 * sin( ivTime * 2.3 + ph * 1.7 ) ) * gust * ivWindStrength;
	float h = max( transformed.y, 0.0 );
	transformed += ( ivInv * ivWindDir ) * ( 0.004 * h * h * 0.08 + flex * flex * 0.12 ) * sway;
}`,
      );
    shader.fragmentShader = shader.fragmentShader
      .replace(
        '#include <common>',
        `#include <common>
uniform sampler2D ivFoliage;
uniform float ivAtlasSize;
varying vec2 vIvUv;
varying float vIvLeaf;`,
      )
      .replace(
        '#include <alphatest_fragment>',
        `if ( vIvLeaf > 0.5 ) {
	float a = texture2D( ivFoliage, vIvUv ).a;
	vec2 duv = fwidth( vIvUv ) * ivAtlasSize;
	a *= 1.0 + max( 0.0, log2( max( duv.x, duv.y ) ) ) * 0.45;
	if ( a < 0.5 ) discard;
}`,
      );
  };
  m.customProgramCacheKey = () => 'iv-vegetation-depth-1';
  return m;
}

/** Geometry of one model LOD from the parsed glTF: dequantised (node scale), float uv, attributes kept. */
function modelGeometry(gltf, nodeName) {
  let mesh = null;
  gltf.scene.traverse((o) => {
    if (o.isMesh && o.name === nodeName && !mesh) mesh = o;
  });
  if (!mesh) {
    // GLTFLoader names the Mesh after the glTF mesh and the node group after the node
    gltf.scene.traverse((o) => {
      if (!mesh && o.name === nodeName) o.traverse((c) => { if (c.isMesh && !mesh) mesh = c; });
    });
  }
  if (!mesh) throw new Error(`vegetation model ${nodeName} missing`);
  mesh.updateMatrixWorld(true);
  const g = mesh.geometry.clone();
  const pos = g.getAttribute('position');
  const s = mesh.matrixWorld;
  const out = new Float32Array(pos.count * 3);
  for (let i = 0; i < pos.count; i++) {
    _p.set(pos.getX(i), pos.getY(i), pos.getZ(i)).applyMatrix4(s);
    out[i * 3] = _p.x;
    out[i * 3 + 1] = _p.y;
    out[i * 3 + 2] = _p.z;
  }
  g.setAttribute('position', new Float32BufferAttribute(out, 3));
  g.computeBoundingSphere();
  g.computeBoundingBox();
  return g;
}

/**
 * Builds the vegetation of a level.
 * @param {object} o { vegGltf (GLTFLoader result), vegGlb (parseGlb), worldGlb (parseGlb of kh_world.glb), textures,
 *                     uniforms, backdrop (Mesh of the backdrop ring, optional) }
 */
export function buildVegetation({ vegGltf, vegGlb, worldGlb, textures, uniforms, backdrop = null }) {
  const iv = vegGlb.json.asset.extras.iv;
  const w = worldGlb.json.asset.extras && worldGlb.json.asset.extras.iv && worldGlb.json.asset.extras.iv.vegetation;
  const group = new Group();
  group.name = 'vegetation';
  const material = createVegetationMaterial(textures, uniforms, { uvScale: iv.uvScale || 32 });
  const depthMaterial = createVegetationDepthMaterial(textures, uniforms, { uvScale: iv.uvScale || 32 });
  const models = {};
  for (const [name, info] of Object.entries(iv.models)) {
    models[name] = { name, info, geos: info.lods.map((l) => modelGeometry(vegGltf, l.node)) };
  }
  // ---- instance list: tables of the level (trees, shrubs) + backdrop forest
  const inst = []; // { model, pos, yaw, sy, sxz, tint, shrub, far }
  const addTable = (tab, isShrub) => {
    if (!tab || !tab.count) return;
    const rows = readAccessor(worldGlb, tab.rows);
    const kinds = readAccessor(worldGlb, tab.kinds);
    for (let i = 0; i < tab.count; i++) {
      const o = i * 8;
      const kind = tab.kindNames[kinds[i]];
      const list = iv.speciesModels[kind] || ['round'];
      const seed = rows[o + 7];
      const mname = list[Math.min(list.length - 1, Math.floor(seed * list.length))];
      const m = models[mname];
      if (!m) continue;
      const sy = rows[o + 4] / m.info.height;
      let sxz = rows[o + 5] / Math.max(m.info.crownRadius, 0.1);
      sxz = Math.min(Math.max(sxz, sy * 0.72), sy * 1.35);
      const k = 0.9 + 0.2 * ((seed * 7.31) % 1);
      const tint = [k * (0.97 + 0.06 * ((seed * 3.7) % 1)), k, k * (0.95 + 0.08 * ((seed * 5.3) % 1))];
      inst.push({ model: mname, x: rows[o], y: rows[o + 1], z: rows[o + 2], yaw: rows[o + 3], sy, sxz, tint, shrub: isShrub, far: false });
    }
  };
  if (w) {
    addTable(w.trees, false);
    addTable(w.shrubs, true);
  }
  const nearCount = inst.length;
  let farCount = 0;
  if (backdrop) farCount = scatterBackdropForest(backdrop, inst, models, iv);
  // ---- InstancedMesh per model x LOD (capacity = instances of that model)
  const byModel = {};
  for (const it of inst) (byModel[it.model] = byModel[it.model] || []).push(it);
  const meshes = [];
  for (const [name, list] of Object.entries(byModel)) {
    const m = models[name];
    m.meshes = m.geos.map((geo, lod) => {
      const im = new InstancedMesh(geo, material, list.length);
      im.name = `veg_${name}_LOD${lod}`;
      im.count = 0;
      im.frustumCulled = true;
      im.castShadow = lod < 2;
      im.customDepthMaterial = depthMaterial;
      im.receiveShadow = true;
      im.instanceColor = new InstancedBufferAttribute(new Float32Array(list.length * 3), 3);
      im.userData.lod = lod;
      im.userData.model = name;
      group.add(im);
      meshes.push(im);
      return im;
    });
  }
  // per-instance static matrices
  for (const it of inst) {
    _q.setFromAxisAngle(_y, it.yaw);
    _p.set(it.x, it.y, it.z);
    _s.set(it.sxz, it.sy, it.sxz);
    it.matrix = new Matrix4().compose(_p, _q, _s);
    it.lod = -1;
    it.radius = models[it.model].info.height * it.sy * 0.6;
  }
  const d = iv.lodDistances;
  const state = { lastPos: new Vector3(1e9, 0, 0), frame: 0, counts: [0, 0, 0], visible: 0 };
  function update(camera, force = false) {
    state.frame++;
    const cp = camera.position;
    if (!force && state.frame % 4 !== 0 && cp.distanceToSquared(state.lastPos) < 4) return false;
    state.lastPos.copy(cp);
    _pm.multiplyMatrices(camera.projectionMatrix, camera.matrixWorldInverse);
    _frustum.setFromProjectionMatrix(_pm);
    for (const name in byModel) for (const im of models[name].meshes) im.count = 0;
    state.counts = [0, 0, 0];
    state.visible = 0;
    const h = d.hysteresis;
    for (const it of inst) {
      const dx = it.x - cp.x;
      const dy = it.y + it.radius * 0.5 - cp.y;
      const dz = it.z - cp.z;
      const dist = Math.sqrt(dx * dx + dy * dy + dz * dz);
      let lod;
      if (it.far) lod = 2;
      else {
        const l1 = it.shrub ? d.shrub_lod1 : d.lod1;
        const l2 = it.shrub ? d.shrub_lod2 : d.lod2;
        const prev = it.lod;
        lod = dist < l1 ? 0 : dist < l2 ? 1 : 2;
        // hysteresis: keep the previous LOD inside the band around a threshold
        if (prev === 0 && lod === 1 && dist < l1 + h) lod = 0;
        if (prev === 1 && lod === 0 && dist > l1 - h) lod = 1;
        if (prev === 1 && lod === 2 && dist < l2 + h) lod = 1;
        if (prev === 2 && lod === 1 && dist > l2 - h) lod = 2;
      }
      it.lod = lod;
      if (dist > 30) {
        _sph.center.set(it.x, it.y + it.radius * 0.8, it.z);
        _sph.radius = it.radius * 1.2;
        if (!_frustum.intersectsSphere(_sph)) continue;
      }
      const im = models[it.model].meshes[lod];
      const k = im.count++;
      im.setMatrixAt(k, it.matrix);
      im.instanceColor.setXYZ(k, it.tint[0], it.tint[1], it.tint[2]);
      state.counts[lod]++;
      state.visible++;
    }
    for (const name in byModel) {
      for (const im of models[name].meshes) {
        im.visible = im.count > 0;
        if (im.count > 0) {
          im.instanceMatrix.needsUpdate = true;
          im.instanceColor.needsUpdate = true;
          im.computeBoundingSphere();
        }
      }
    }
    return true;
  }
  const stats = {
    models: Object.keys(models).length,
    instances: inst.length,
    trees: w && w.trees ? w.trees.count : 0,
    shrubs: w && w.shrubs ? w.shrubs.count : 0,
    backdropTrees: farCount,
    meshes: meshes.length,
    triangles: Object.fromEntries(Object.entries(iv.models).map(([k, v]) => [k, v.lods.map((l) => l.triangles)])),
  };
  void nearCount;
  return { group, update, state, stats, material, models, instances: inst };
}

/** Impostor-LOD trees on the forest part of the backdrop ring (vertex colour dark = forest), deterministic. */
function scatterBackdropForest(backdrop, inst, models, iv) {
  const g = backdrop.geometry;
  const pos = g.getAttribute('position');
  const col = g.getAttribute('color');
  const idx = g.index;
  const conifer = (iv.speciesModels.far_conifer || ['spruce'])[0];
  const broad = (iv.speciesModels.far_broadleaf || ['round'])[0];
  let seed = 20260930;
  const rnd = () => {
    seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
    return seed / 4294967296;
  };
  const a = new Vector3();
  const b = new Vector3();
  const c = new Vector3();
  let n = 0;
  const tri = idx ? idx.count / 3 : pos.count / 3;
  for (let t = 0; t < tri; t++) {
    const i0 = idx ? idx.getX(t * 3) : t * 3;
    const i1 = idx ? idx.getX(t * 3 + 1) : t * 3 + 1;
    const i2 = idx ? idx.getX(t * 3 + 2) : t * 3 + 2;
    a.fromBufferAttribute(pos, i0);
    b.fromBufferAttribute(pos, i1);
    c.fromBufferAttribute(pos, i2);
    const r0 = Math.hypot(a.x, a.z);
    if (r0 > 560) continue;
    // forest = the darker vertex colours of the ring (fields are light)
    if (col) {
      const lum = col.getX(i0) * 0.3 + col.getY(i0) * 0.6 + col.getZ(i0) * 0.1;
      if (lum > 0.1) continue;
    }
    const area = b.clone().sub(a).cross(c.clone().sub(a)).length() * 0.5;
    const dens = r0 < 260 ? 1 / 55 : 1 / 100;
    const cnt = Math.floor(area * dens + rnd());
    for (let k = 0; k < cnt; k++) {
      let u = rnd();
      let v = rnd();
      if (u + v > 1) {
        u = 1 - u;
        v = 1 - v;
      }
      const x = a.x + (b.x - a.x) * u + (c.x - a.x) * v;
      const y = a.y + (b.y - a.y) * u + (c.y - a.y) * v;
      const z = a.z + (b.z - a.z) * u + (c.z - a.z) * v;
      if (Math.max(Math.abs(x), Math.abs(z)) < 177.5) continue;
      const isCon = rnd() < 0.62;
      const mname = isCon ? conifer : broad;
      const m = models[mname];
      const hgt = isCon ? 18 + 8 * rnd() : 15 + 7 * rnd();
      const sy = hgt / m.info.height;
      const kk = 0.85 + 0.25 * rnd();
      inst.push({ model: mname, x, y: y - 0.5, z, yaw: rnd() * 6.283, sy, sxz: sy * (0.9 + 0.25 * rnd()), tint: [kk, kk, kk * 0.97], shrub: false, far: true });
      n++;
    }
  }
  return n;
}

/** Swaps the hedge / shrub-core materials of the world to the leafy hedge surface of vegetation.glb. */
export function applyHedgeMaterials(root, textures) {
  root.traverse((o) => {
    if (!o.isMesh || !o.material) return;
    const key = o.material.userData && o.material.userData.iv && o.material.userData.iv.key;
    const m = o.material;
    if (key === 'hedge' || key === 'veg_core') {
      if (m.userData.ivHedge) return;
      m.map = textures.hedge;
      m.normalMap = textures.hedgeNormal;
      m.normalScale.set(0.9, 0.9);
      m.color.setScalar(key === 'hedge' ? 1.0 : 0.45);
      m.roughness = 0.85;
      m.userData.ivHedge = true;
      m.needsUpdate = true;
    }
  });
}

export { BufferAttribute };
