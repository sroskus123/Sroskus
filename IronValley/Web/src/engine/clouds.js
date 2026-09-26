// Detailed cloud layer for three's Sky shader.
//
// The stock Sky.js clouds project 4 octaves of noise onto a flat plane and shade them only by
// the local density. Looking up, the view covers less than one noise cell, so the sky shows one
// soft, flat blob (ENV-04: clouds must not look like flat blobs). This replaces that block with:
//   - a curved cloud layer (finite distance at the horizon, no infinite stretching),
//   - domain-warped multi-octave density plus billow erosion for cumulus-like structure, with
//     per-octave level of detail from screen-space derivatives so octaves smaller than a pixel
//     fade out (no shimmering or aliasing towards the horizon),
//   - lighting marched towards the sun through the density field (lit sides facing the sun,
//     self-shadowed cores), ambient from the sky itself and a forward-scattering silver lining,
//   - Beer-law opacity and the same aerial-perspective composite as the stock shader.
// The sun direction comes from the same sunPosition uniform as the sky and the light.

const IV_CLOUD_UNIFORMS_GLSL = /* glsl */ `
		uniform float cloudDetail;
		uniform float cloudLayerHeight;
		uniform float cloudSunAbsorption;
`;

const IV_CLOUD_FUNCTIONS_GLSL = /* glsl */ `
		// ---- IRON VALLEY clouds -------------------------------------------------------------
		const float IV_PLANET_R = 6.0e5; // flattened planet radius for the layer curvature (m)
		const mat2 IV_ROT = mat2( 0.8, -0.6, 0.6, 0.8 );
		const mat2 IV_ROT_B = mat2( 0.6, 0.8, -0.8, 0.6 );

		// octave weight: fade octaves whose features are smaller than ~1.5 pixels
		float ivLod( float freq, float fw ) {
			return 1.0 - smoothstep( 0.35, 0.75, fw * freq );
		}

		// Adds up to \`count\` fbm octaves continuing from the state (p, amp, freq); stops at the
		// first octave the level of detail has faded out (all finer ones are faded too).
		float ivFbmPart( inout vec2 p, inout float amp, inout float freq, float fw, int count ) {
			float sum = 0.0;
			for ( int i = 0; i < 8; i ++ ) {
				if ( i >= count ) break;
				float w = ivLod( freq, fw );
				if ( w <= 0.0 ) { amp = 0.0; break; }
				sum += amp * w * noise( p );
				p = IV_ROT * p * 2.03 + vec2( 17.13, 3.71 );
				amp *= 0.5;
				freq *= 2.03;
			}
			return sum;
		}

		// puffy erosion detail: |noise| fbm in [0, 1] (0.5 where faded out)
		float ivBillow( vec2 p, float fw, int count ) {
			float sum = 0.0;
			float amp = 0.5;
			float freq = 1.0;
			float norm = 0.0;
			for ( int i = 0; i < 4; i ++ ) {
				if ( i >= count ) break;
				float w = ivLod( freq, fw );
				if ( w <= 0.0 ) break;
				sum += amp * mix( 0.5, abs( noise( p ) ), w );
				norm += amp;
				p = IV_ROT_B * p * 2.11 + vec2( 5.3, 11.9 );
				amp *= 0.5;
				freq *= 2.11;
			}
			return norm > 0.0 ? sum / norm : 0.5;
		}

		// shape value -> density given the coverage threshold
		float ivCarve( float shape, float cov ) {
			return clamp( ( shape - ( 1.0 - cov ) ) / max( cov * 0.75, 0.05 ), 0.0, 1.0 );
		}

		// cheap density for the light samples (coarse octaves, warp and coverage reused)
		float ivLightDensity( vec2 pw, float fw, float cov ) {
			float amp = 0.5;
			float freq = 1.0;
			float s = ivFbmPart( pw, amp, freq, fw, 4 );
			return ivCarve( s * ( 0.992 / 0.9375 ) + 0.5, cov );
		}
`;

const IV_CLOUD_BLOCK_GLSL = /* glsl */ `
			// Clouds (IRON VALLEY layer; derivatives taken outside the branch)
			float ivY = max( direction.y, 0.0 );
			float ivB = IV_PLANET_R * ivY;
			float ivT = -ivB + sqrt( ivB * ivB + cloudLayerHeight * cloudLayerHeight + 2.0 * IV_PLANET_R * cloudLayerHeight );
			vec2 ivP = direction.xz * ivT * cloudScale + time * cloudSpeed;
			float ivFw = length( fwidth( ivP ) );

			if ( direction.y > 0.0 && cloudCoverage > 0.0 ) {

				// large-scale coverage (banks and clear gaps) and domain warp: smooth fields,
				// also reused by the light samples
				float region = noise( ivP * 0.11 + vec2( 3.1, 7.7 ) ) * 0.5 + 0.5;
				float cov = clamp( cloudCoverage + ( region - 0.5 ) * 0.55, 0.0, 1.0 );
				vec2 q = vec2( noise( ivP * 0.45 + vec2( 1.7, 9.2 ) ), noise( ivP * 0.45 + vec2( 8.3, 2.8 ) ) ) * 0.75;
				vec2 pw = ivP + q;

				// coarse shape (3 octaves); skip clear sky early: even the largest possible
				// contribution of the 4 finer octaves cannot reach the coverage threshold
				vec2 pp = pw;
				float amp = 0.5;
				float freq = 1.0;
				float s = ivFbmPart( pp, amp, freq, ivFw, 3 );
				// shape = sum / 0.992 (7-octave norm) * 1.6 * 0.62 + 0.5 = sum + 0.5
				float d = 0.0;
				if ( s + amp * 1.875 * 1.4 + 0.5 > 1.0 - cov ) { // 1.4: margin, |noise| can exceed 1
					s += ivFbmPart( pp, amp, freq, ivFw, 4 );
					float base = ivCarve( s + 0.5, cov );
					if ( base > 0.0 ) {
						// erode edges with puffy detail (strongest where the cloud is thin)
						float det = ivBillow( pw * 3.7 + vec2( 2.0, 5.0 ), ivFw * 3.7, 3 );
						d = clamp( base - ( 1.0 - base ) * det * 0.9 * cloudDetail, 0.0, 1.0 );
					}
				}

				if ( d > 0.0 ) {

					float horizonFade = smoothstep( 0.0, 0.05, direction.y );

					// light marched towards the sun through the layer
					vec2 sunXZ = vSunDirection.xz;
					float sunLen = length( sunXZ );
					vec2 sunStep = sunLen > 1e-4 ? sunXZ / sunLen : vec2( 0.0 );
					// low sun: light crosses more cloud horizontally; high sun: mostly the top
					float horiz = clamp( 1.0 - vSunDirection.y, 0.2, 1.0 );
					float tau = d * 0.7;
					tau += ivLightDensity( pw + sunStep * ( 0.08 * horiz ), ivFw, cov ) * 1.1;
					tau += ivLightDensity( pw + sunStep * ( 0.28 * horiz ), ivFw, cov ) * 0.9;
					float sunT = exp( -tau * cloudSunAbsorption );
					float powder = 1.0 - exp( -d * 6.0 );

					float dayFactor = smoothstep( -0.08, 0.3, vSunDirection.y );
					vec3 sunColor = vSunE * Fex * 0.22 * 0.04;
					vec3 skyAmbient = Lin * 0.04 + vec3( 0.0, 0.0003, 0.00075 );
					// Seen from below, a thick cloud's base is in its own shadow (grey) while thin
					// parts transmit light (bright): view-path attenuation through the local density.
					float viewT = exp( -d * cloudSunAbsorption * 1.1 );
					// ambient: sky light, less of it reaches the base of thick cores
					// (partly desaturated: multiple scattering inside the cloud greys the blue sky light)
					vec3 ambGrey = vec3( dot( skyAmbient, vec3( 0.2126, 0.7152, 0.0722 ) ) );
					vec3 ambient = mix( skyAmbient, ambGrey, 0.75 ) * mix( 1.1, 0.45, d ) + sunColor * 0.06;

					// forward scattering towards the sun (silver lining on thin rims)
					float silver = clamp( 0.51 / pow( 1.49 - cosTheta * 1.4, 1.5 ), 0.0, 3.0 );
					float rim = ( 1.0 - d ) * powder;

					float direct = sunT * mix( 0.35, 1.0, viewT ) * mix( 0.6, 1.0, powder );
					vec3 cloudColor = ambient + sunColor * ( direct * 0.95 + silver * rim * 0.3 );
					cloudColor *= max( dayFactor, 0.03 );

					float alpha = ( 1.0 - exp( -d * cloudDensity * 7.0 ) ) * horizonFade;

					// occlude the sun disc / glow behind opaque cloud
					texColor -= L0 * 0.04 * alpha;
					texColor = mix( texColor, texColor * ( 1.0 - alpha ), clamp( sundisc, 0.0, 1.0 ) );

					// composite through the atmosphere so distant clouds dissolve into haze
					vec3 cloudAerial = mix( texColor, cloudColor, Fex );
					texColor = mix( texColor, cloudAerial, alpha );

				}

			}
`;

export const CLOUD_DEFAULTS = {
  cloudDetail: 1.0,
  cloudLayerHeight: 1800,
  cloudSunAbsorption: 1.6,
};

/**
 * Replaces the stock cloud block of a three Sky's fragment shader. Must be called before the
 * material is compiled. Returns true when the shader was patched (sky.userData.detailedClouds).
 * @param {import('three/examples/jsm/objects/Sky.js').Sky} sky
 */
export function applyDetailedClouds(sky, cfg = {}) {
  const mat = sky.material;
  let fs = mat.fragmentShader;
  const start = fs.indexOf('// Clouds');
  const end = fs.indexOf('gl_FragColor', start);
  const mainAt = fs.indexOf('void main()');
  const uniformAt = fs.indexOf('uniform float time;');
  if (start < 0 || end < 0 || mainAt < 0 || uniformAt < 0 || !mat.uniforms.cloudCoverage) {
    sky.userData.detailedClouds = false;
    return false;
  }
  // the stock block is one `if (...) { ... }` right before gl_FragColor
  fs = fs.slice(0, start) + IV_CLOUD_BLOCK_GLSL.trim() + '\n\n\t\t\t' + fs.slice(end);
  const insertAt = fs.indexOf('void main()');
  fs = fs.slice(0, insertAt) + IV_CLOUD_FUNCTIONS_GLSL + '\n\t\t' + fs.slice(insertAt);
  const uAt = fs.indexOf('uniform float time;') + 'uniform float time;'.length;
  fs = fs.slice(0, uAt) + IV_CLOUD_UNIFORMS_GLSL + fs.slice(uAt);
  mat.fragmentShader = fs;
  const c = { ...CLOUD_DEFAULTS, ...cfg };
  mat.uniforms.cloudDetail = { value: c.cloudDetail };
  mat.uniforms.cloudLayerHeight = { value: c.cloudLayerHeight };
  mat.uniforms.cloudSunAbsorption = { value: c.cloudSunAbsorption };
  mat.needsUpdate = true;
  sky.userData.detailedClouds = true;
  return true;
}
