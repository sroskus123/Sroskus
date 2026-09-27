// Distance + exponential height fog, installed by patching three's fog shader chunks
// (before any material compiles). Distance fog comes from scene.fog (FogExp2); the height
// term integrates an exponential density along the view ray analytically, so low areas get
// a little more haze than the sky-facing parts of the scene.

import { ShaderChunk } from 'three';

let installed = false;

export function installHeightFog({ heightFalloff = 0.1, heightDensity = 0.005, baseHeight = 0, density = 0.0045 } = {}) {
  if (installed) return false;
  installed = true;
  const k = Math.max(heightFalloff, 1e-4).toFixed(6);
  // the height term scales with the distance density (fogDensity uniform), so a level that changes scene.fog.density
  // (level JSON environment.fog, e.g. Kalné Hamry D9) scales both terms; with environment.json values the result is
  // unchanged (heightDensity = density * ratio)
  const ratio = (density > 0 ? Math.max(heightDensity, 0) / density : 0).toFixed(6);
  const base = Number(baseHeight).toFixed(4);

  ShaderChunk.fog_pars_vertex = /* glsl */ `
#ifdef USE_FOG
	varying float vFogDepth;
	varying float vFogWorldY;
#endif
`;
  ShaderChunk.fog_vertex = /* glsl */ `
#ifdef USE_FOG
	vFogDepth = - mvPosition.z;
	vFogWorldY = cameraPosition.y + ( transpose( mat3( viewMatrix ) ) * mvPosition.xyz ).y;
#endif
`;
  ShaderChunk.fog_pars_fragment = /* glsl */ `
#ifdef USE_FOG
	uniform vec3 fogColor;
	varying float vFogDepth;
	varying float vFogWorldY;
	#ifdef FOG_EXP2
		uniform float fogDensity;
	#else
		uniform float fogNear;
		uniform float fogFar;
	#endif
#endif
`;
  ShaderChunk.fog_fragment = /* glsl */ `
#ifdef USE_FOG
	#ifdef FOG_EXP2
		float fogFactor = 1.0 - exp( - fogDensity * fogDensity * vFogDepth * vFogDepth );
	#else
		float fogFactor = smoothstep( fogNear, fogFar, vFogDepth );
	#endif
	{
		float ivK = ${k};
		float ivH0 = cameraPosition.y - ${base};
		float ivH1 = vFogWorldY - ${base};
		float ivDh = ivH1 - ivH0;
		float ivE0 = exp( - ivK * ivH0 );
		float ivLine = abs( ivDh ) > 1e-3 ? ( ivE0 - exp( - ivK * ivH1 ) ) / ( ivK * ivDh ) : ivE0;
		float ivHeight = 1.0 - exp( - fogDensity * ${ratio} * ivLine * vFogDepth );
		fogFactor = 1.0 - ( 1.0 - fogFactor ) * ( 1.0 - clamp( ivHeight, 0.0, 1.0 ) );
	}
	gl_FragColor.rgb = mix( gl_FragColor.rgb, fogColor, fogFactor );
#endif
`;
  return true;
}
