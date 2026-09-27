// Shader patch for level materials with baked indirect lighting (engine/indirectBake.js):
//   indirect diffuse (environment + hemisphere fill) and indirect specular are occluded by the
//   per-vertex sky visibility, like three's aoMap, but with a floor (ambientFloor) standing in
//   for the multiple bounces the bake does not trace, so interiors stay readable without eye
//   adaptation; then the baked one-bounce sunlight is added as extra indirect irradiance.
// Uses the vertex attributes ivSkyVis (float) and ivBounce (vec3, in units of the sun's
// irradiance); ivSunIrradiance = sun colour * intensity is updated from the light every frame.

import { Color, Vector3 } from 'three';

export function createBakedLightingUniforms({ ambientFloor = 0.12 } = {}) {
  return {
    ivSunIrradiance: { value: new Vector3(1, 1, 1) },
    ivAmbientFloor: { value: ambientFloor },
  };
}

/** Updates the bounce light source from the directional light (colour * intensity). */
export function updateBakedSun(uniforms, color, intensity) {
  const c = color instanceof Color ? color : new Color(color);
  uniforms.ivSunIrradiance.value.set(c.r * intensity, c.g * intensity, c.b * intensity);
}

/**
 * Patches a MeshStandardMaterial (must be used only on geometry with ivSkyVis / ivBounce).
 * @param {import('three').MeshStandardMaterial} material
 * @param {object} uniforms from createBakedLightingUniforms (shared by all level materials)
 */
export function applyBakedLighting(material, uniforms) {
  material.onBeforeCompile = (shader) => {
    Object.assign(shader.uniforms, uniforms);
    shader.vertexShader = shader.vertexShader
      .replace(
        '#include <common>',
        '#include <common>\nattribute float ivSkyVis;\nattribute vec3 ivBounce;\nvarying float vIvSkyVis;\nvarying vec3 vIvBounce;',
      )
      .replace('#include <begin_vertex>', '#include <begin_vertex>\nvIvSkyVis = ivSkyVis;\nvIvBounce = ivBounce;');
    shader.fragmentShader = shader.fragmentShader
      .replace(
        '#include <common>',
        '#include <common>\nuniform vec3 ivSunIrradiance;\nuniform float ivAmbientFloor;\nvarying float vIvSkyVis;\nvarying vec3 vIvBounce;',
      )
      .replace(
        '#include <aomap_fragment>',
        `#include <aomap_fragment>
{
	float ivAO = mix( ivAmbientFloor, 1.0, clamp( vIvSkyVis, 0.0, 1.0 ) );
	reflectedLight.indirectDiffuse *= ivAO;
	#if defined( USE_ENVMAP ) && defined( STANDARD )
		float ivDotNV = saturate( dot( geometryNormal, geometryViewDir ) );
		reflectedLight.indirectSpecular *= computeSpecularOcclusion( ivDotNV, ivAO, material.roughness );
	#endif
	reflectedLight.indirectDiffuse += vIvBounce * ivSunIrradiance * BRDF_Lambert( material.diffuseColor );
}`,
      );
  };
  material.customProgramCacheKey = () => 'iv-baked-lighting-1';
  material.needsUpdate = true;
  material.userData.bakedLighting = true;
  return material;
}
