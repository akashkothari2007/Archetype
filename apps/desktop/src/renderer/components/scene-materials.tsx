import { useMemo } from 'react'
import { useTexture } from '@react-three/drei'
import { useThree } from '@react-three/fiber'
import * as THREE from 'three'
import { useAppearance } from './appearance-context'
import { surfaceOf, type SurfaceKind } from './material-catalog'

type SurfaceProps = { finish: string; color?: string; selected?: boolean; faded?: boolean; photoreal?: boolean; matchStyle?: boolean }

function parseHex(value: string | undefined, fallback: string) {
  if (!value) return fallback
  return /^#[0-9a-fA-F]{6}$/.test(value) ? value : fallback
}

function glslColor(hex: string) {
  const color = new THREE.Color(hex)
  return `vec3(${color.r.toFixed(4)}, ${color.g.toFixed(4)}, ${color.b.toFixed(4)})`
}

function sample(kind: SurfaceKind, sampler: string) {
  return kind === 'wood' || kind === 'metal' ? `texture2D(${sampler}, surfaceUV)` : `naturalSample(${sampler}, surfaceUV)`
}

// World-space mapping keeps texture scale constant on long walls, instanced walls,
// thin reveals and floor polygons. Albedo, normals and roughness share coordinates.
export function SurfaceMaterial(props: SurfaceProps) {
  return <MappedSurface key={surfaceOf(props.finish).folder} {...props} />
}

function MappedSurface({ finish, color = '#ffffff', selected = false, faded = false, photoreal = false, matchStyle = true }: SurfaceProps) {
  const gl = useThree(state => state.gl)
  const look = useAppearance()
  const surface = surfaceOf(finish)
  const maps = useTexture(['Diffuse', 'nor_gl', 'Rough'].map(kind => `assets/${surface.folder}/${kind}.jpg`))
  const textures = useMemo(() => {
    maps.forEach((map, i) => { map.wrapS = map.wrapT = THREE.RepeatWrapping; map.anisotropy = Math.min(8, gl.capabilities.getMaxAnisotropy()); map.colorSpace = i === 0 ? THREE.SRGBColorSpace : THREE.NoColorSpace; map.needsUpdate = true })
    return { map: maps[0], normalMap: maps[1], roughnessMap: maps[2] }
  }, [maps[0], maps[1], maps[2], gl])
  const clad = photoreal && look.apply && !!look.palette && !look.splatUrl
  const brick = parseHex(look.palette?.primary, '#8a5a3a')
  const grout = parseHex(look.palette?.secondary, '#d8d0c4')
  const roof = parseHex(look.palette?.floor, '#6a6560')
  const painted = !!surface.tint
  const tint = clad ? '#ffffff' : !matchStyle || !look.apply || !look.palette || surface.kind === 'grass'
    ? (painted ? color : '#ffffff')
    : painted ? parseHex(surface.kind === 'wood' || surface.kind === 'stone' ? look.palette.floor : look.palette.secondary, color) : '#ffffff'
  const compile = useMemo(() => (shader: THREE.WebGLProgramParametersWithUniforms) => {
    const { kind, scale, stylize, planks } = surface
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
        ${planks ? `
          float row = floor(surfaceUV.y * 8.0);
          surfaceUV.x += surfaceHash(vec2(row, 9.0)).x;
        ` : ''}
        vec4 surfaceColor = ${sample(kind, 'map')};
        ${kind === 'grass' ? 'surfaceColor.rgb *= vec3(.84, 1.12, .72) * (0.93 + 0.07 * sin(vSurfacePosition.x * .035 + sin(vSurfacePosition.z * .05)));' : ''}
        ${clad && kind === 'plaster' ? `
          vec2 masonry = sn.y > max(sn.x, sn.z) ? vSurfacePosition.xz : (sn.x > sn.z ? vec2(vSurfacePosition.z, vSurfacePosition.y) : vec2(vSurfacePosition.x, vSurfacePosition.y));
          float courses = 4.55;
          float ratio = 2.55;
          float course = floor(masonry.y * courses);
          vec2 brickUV = vec2(masonry.x * courses / ratio + mod(course, 2.0) * 0.5, masonry.y * courses);
          vec2 brickId = floor(brickUV);
          vec2 brickFract = fract(brickUV);
          float groutMask = 1.0 - step(0.07, brickFract.x) * step(0.11, brickFract.y);
          float speck = surfaceHash(brickId).x;
          vec3 brickCol = ${glslColor(brick)} * mix(vec3(0.78, 0.74, 0.7), surfaceColor.rgb, 0.32) * (0.84 + 0.24 * speck);
          vec3 groutCol = ${glslColor(grout)} * mix(vec3(1.0), surfaceColor.rgb, 0.18);
          surfaceColor.rgb = mix(brickCol, groutCol, groutMask);
        ` : kind === 'plaster' ? 'surfaceColor.rgb = mix(vec3(.83, .80, .76), surfaceColor.rgb, .82);' : ''}
        ${clad && kind === 'stone' && stylize ? `
          vec2 shingle = sn.y > 0.55 ? vSurfacePosition.xz : (sn.x > sn.z ? vSurfacePosition.zy : vSurfacePosition.xy);
          vec2 tileId = floor(shingle * vec2(1.15, 2.4));
          vec2 tileUv = fract(shingle * vec2(1.15, 2.4) + vec2(mod(tileId.y, 2.0) * 0.5, 0.0));
          float gap = 1.0 - step(0.06, tileUv.x) * step(0.08, tileUv.y);
          float wear = surfaceHash(tileId).x;
          surfaceColor.rgb = mix(${glslColor(roof)} * (0.72 + 0.3 * wear), ${glslColor(grout)} * 0.55, gap);
          surfaceColor.rgb *= mix(vec3(1.0), naturalSample(map, surfaceUV).rgb, 0.28);
        ` : stylize && kind === 'stone' ? 'surfaceColor.rgb = mix(vec3(.62, .60, .57), surfaceColor.rgb, .74);' : ''}
        diffuseColor *= surfaceColor;`)
      .replace('#include <normal_fragment_begin>', THREE.ShaderChunk.normal_fragment_begin.replaceAll('vNormalMapUv', 'surfaceUV'))
      .replace('#include <normal_fragment_maps>', THREE.ShaderChunk.normal_fragment_maps.replaceAll('vNormalMapUv', 'surfaceUV').replaceAll('texture2D( normalMap, surfaceUV )', sample(kind, 'normalMap')))
      .replace('#include <roughnessmap_fragment>', THREE.ShaderChunk.roughnessmap_fragment.replaceAll('vRoughnessMapUv', 'surfaceUV').replaceAll('texture2D( roughnessMap, surfaceUV )', sample(kind, 'roughnessMap')))
  }, [surface, clad, brick, grout, roof])
  const normal = clad && surface.kind === 'plaster' ? .7 : surface.normalScale
  return <meshStandardMaterial key={clad ? `clad-${surface.id}-${brick}` : `pbr-${surface.id}-${tint}`} {...textures} color={tint} normalScale={[normal, normal]} roughness={clad && surface.kind === 'stone' && surface.stylize ? .95 : surface.roughness} metalness={surface.metalness || 0} envMapIntensity={clad ? .48 : surface.kind === 'metal' ? 1.2 : .85} onBeforeCompile={compile} customProgramCacheKey={() => `surface-v10-${surface.id}-${clad ? `clad-${brick}-${grout}-${roof}` : `pbr-${tint}`}`} transparent={faded} opacity={faded ? .4 : 1} emissive={selected ? '#31495d' : '#000000'} emissiveIntensity={selected ? .16 : 0} />
}
