import { useMemo } from 'react'
import { useTexture } from '@react-three/drei'
import { useThree } from '@react-three/fiber'
import * as THREE from 'three'

type Finish = 'plaster' | 'wood' | 'grass' | 'stone'
const names = { plaster: 'plaster_grey_04', wood: 'wood_floor', grass: 'grass_ground', stone: 'plaster_grey_04' }

// World-space mapping keeps texture scale constant on long walls, instanced walls,
// thin reveals and floor polygons. Albedo, normals and roughness share coordinates.
export function SurfaceMaterial({ finish, color = '#ffffff', selected = false, faded = false }: { finish: Finish; color?: string; selected?: boolean; faded?: boolean }) {
  const gl = useThree(state => state.gl)
  const maps = useTexture(['Diffuse', 'nor_gl', 'Rough'].map(kind => `assets/landscape/${names[finish]}/${kind}.jpg`))
  const textures = useMemo(() => {
    maps.forEach((map, i) => { map.wrapS = map.wrapT = THREE.RepeatWrapping; map.anisotropy = Math.min(8, gl.capabilities.getMaxAnisotropy()); map.colorSpace = i === 0 ? THREE.SRGBColorSpace : THREE.NoColorSpace; map.needsUpdate = true })
    return { map: maps[0], normalMap: maps[1], roughnessMap: maps[2] }
  }, [maps[0], maps[1], maps[2], gl])
  const compile = useMemo(() => (shader: THREE.WebGLProgramParametersWithUniforms) => {
    const scale = finish === 'wood' ? .105 : finish === 'grass' ? .19 : .25
    shader.vertexShader = `varying vec3 vSurfacePosition; varying vec3 vSurfaceNormal;\n${shader.vertexShader}`
      .replace('#include <begin_vertex>', `#include <begin_vertex>
        mat4 surfaceMatrix = modelMatrix;
        #ifdef USE_INSTANCING
          surfaceMatrix = modelMatrix * instanceMatrix;
        #endif
        vSurfacePosition = (surfaceMatrix * vec4(transformed, 1.0)).xyz;
        vSurfaceNormal = normalize(mat3(surfaceMatrix) * normal);`)
    shader.fragmentShader = `varying vec3 vSurfacePosition; varying vec3 vSurfaceNormal;
      vec2 surfaceHash(vec2 p) { return fract(sin(vec2(dot(p, vec2(127.1,311.7)),dot(p,vec2(269.5,183.3)))) * 43758.5453); }
      vec4 naturalSample(sampler2D tex, vec2 uv) {
        vec2 tile = floor(uv / 2.0), blend = smoothstep(0.0, 1.0, fract(uv / 2.0));
        vec4 a = texture2D(tex, uv + surfaceHash(tile) * 7.0);
        vec4 b = texture2D(tex, uv + surfaceHash(tile + vec2(1,0)) * 7.0);
        vec4 c = texture2D(tex, uv + surfaceHash(tile + vec2(0,1)) * 7.0);
        vec4 d = texture2D(tex, uv + surfaceHash(tile + vec2(1,1)) * 7.0);
        return mix(mix(a,b,blend.x),mix(c,d,blend.x),blend.y);
      }
      ${shader.fragmentShader}`
      .replace('#include <map_fragment>', `
        vec3 sn = abs(normalize(vSurfaceNormal));
        vec2 surfaceUV = (sn.y > max(sn.x,sn.z) ? vSurfacePosition.xz : (sn.x > sn.z ? vSurfacePosition.zy : vSurfacePosition.xy)) * ${scale};
        ${finish === 'wood' ? `
          // Shift whole rows along the grain without blending away the plank joints.
          float row = floor(surfaceUV.y * 8.0);
          surfaceUV.x += surfaceHash(vec2(row, 9.0)).x;
        ` : ''}
        vec4 surfaceColor = ${finish !== 'wood' ? 'naturalSample(map, surfaceUV)' : 'texture2D(map, surfaceUV)'};
        ${finish === 'plaster' ? 'surfaceColor.rgb = mix(vec3(.88), surfaceColor.rgb, .13);' : finish === 'stone' ? 'surfaceColor.rgb = mix(vec3(.68), surfaceColor.rgb, .16);' : ''}
        ${finish === 'grass' ? 'surfaceColor.rgb *= vec3(.84, 1.12, .72) * (0.93 + 0.07 * sin(vSurfacePosition.x * .035 + sin(vSurfacePosition.z * .05)));' : ''}
        diffuseColor *= surfaceColor;`)
      .replace('#include <normal_fragment_begin>', THREE.ShaderChunk.normal_fragment_begin.replaceAll('vNormalMapUv', 'surfaceUV'))
      .replace('#include <normal_fragment_maps>', THREE.ShaderChunk.normal_fragment_maps.replaceAll('vNormalMapUv', 'surfaceUV').replaceAll('texture2D( normalMap, surfaceUV )', finish === 'wood' ? 'texture2D( normalMap, surfaceUV )' : 'naturalSample(normalMap, surfaceUV)'))
      .replace('#include <roughnessmap_fragment>', THREE.ShaderChunk.roughnessmap_fragment.replaceAll('vRoughnessMapUv', 'surfaceUV').replaceAll('texture2D( roughnessMap, surfaceUV )', finish === 'wood' ? 'texture2D( roughnessMap, surfaceUV )' : 'naturalSample(roughnessMap, surfaceUV)'))
  }, [finish])
  return <meshStandardMaterial {...textures} color={color} normalScale={finish === 'plaster' ? [.12, .12] : finish === 'grass' ? [.3, .3] : [.08, .08]} roughness={finish === 'wood' ? .8 : 1} envMapIntensity={.85} onBeforeCompile={compile} customProgramCacheKey={() => `surface-v3-${finish}`} transparent={faded} opacity={faded ? .4 : 1} emissive={selected ? '#31495d' : '#000000'} emissiveIntensity={selected ? .16 : 0} />
}
