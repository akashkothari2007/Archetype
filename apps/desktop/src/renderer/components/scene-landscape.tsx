import { useEffect, useMemo } from 'react'
import { Environment, Sky, useGLTF, useTexture } from '@react-three/drei'
import * as THREE from 'three'
import type { Building } from '../types'
import { floorBounds } from './editor-geometry'
import { SurfaceMaterial } from './scene-materials'

type Bounds = ReturnType<typeof floorBounds>

export function Daylight({ bounds, environment }: { bounds: Bounds; environment: Building['environment'] }) {
  const day = Math.max(0, Math.sin((environment.time - 6) / 12 * Math.PI))
  const elevation = Math.max(.025, day * (environment.season === 'winter' ? .45 : environment.season === 'summer' ? 1.05 : .7))
  const angle = environment.sun_azimuth * Math.PI / 180
  const span = Math.max(bounds.width, bounds.height, 35)
  const direction: [number, number, number] = [Math.cos(angle) * 100, elevation * 100, Math.sin(angle) * 100]
  const target = useMemo(() => { const node = new THREE.Object3D(); node.position.set(bounds.cx, 4, bounds.cy); return node }, [bounds.cx, bounds.cy])
  const sky = <Sky distance={2000} sunPosition={direction} turbidity={2.8} rayleigh={1.6} mieCoefficient={.005} mieDirectionalG={.82} />
  return <>
    <fog attach="fog" args={['#c4d2db', Math.max(span * 5, 240), Math.max(span * 18, 1300)]} />
    <group userData={{ captureHide: true }} position={[bounds.cx, 0, bounds.cy]}>{sky}</group>
    <Environment key={`${environment.time}-${environment.season}-${environment.sun_azimuth}`} frames={1} resolution={128} environmentIntensity={.45 + day * .2}>
      {sky}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -10, 0]}><planeGeometry args={[4000, 4000]} /><meshBasicMaterial color="#717763" /></mesh>
    </Environment>
    <hemisphereLight args={['#d5e5f2', '#8b8375', .85]} />
    <primitive object={target} />
    <directionalLight target={target} position={[bounds.cx + direction[0] * span / 45, direction[1] * span / 45 + 15, bounds.cy + direction[2] * span / 45]} intensity={.15 + day * 3.1} color={day < .3 ? '#ffd2a0' : '#fff2de'} castShadow shadow-mapSize={[2048, 2048]} shadow-camera-left={-span * 1.5} shadow-camera-right={span * 1.5} shadow-camera-top={span * 1.5} shadow-camera-bottom={-span * 1.5} shadow-camera-near={1} shadow-camera-far={span * 10} shadow-bias={-.00004} shadow-normalBias={.035} shadow-radius={3} />
  </>
}

// Actual textured 3D mesh, simplified offline; no billboards or camera-facing cards.
function LandscapeTrees({ bounds }: { bounds: Bounds }) {
  const { scene } = useGLTF('assets/landscape/tree/tree.gltf', false, false)
  const alpha = useTexture('assets/landscape/tree-leaves-alpha.png')
  const { model, materials, height } = useMemo(() => {
    const model = scene.clone(true), materials: THREE.Material[] = []
    const box = new THREE.Box3().setFromObject(model)
    const center = box.getCenter(new THREE.Vector3()), height = box.max.y - box.min.y
    model.position.set(-center.x, -box.min.y, -center.z)
    model.traverse(node => {
      if (!(node instanceof THREE.Mesh)) return
      const original = node.material as THREE.MeshStandardMaterial
      const material = original.clone()
      material.envMapIntensity = .7
      if (/leaves/.test(material.name)) { alpha.flipY = false; material.alphaMap = alpha; material.alphaTest = .28; material.transparent = false; material.depthWrite = true; material.side = THREE.DoubleSide; material.roughness = 1; material.metalness = 0 }
      node.material = material; node.castShadow = node.receiveShadow = true
      materials.push(material)
    })
    return { model, materials, height }
  }, [scene, alpha])
  useEffect(() => () => materials.forEach(material => material.dispose()), [materials])
  const placements = useMemo(() => {
    const w = bounds.width / 2, h = bounds.height / 2
    return [[-w-22, -h-4, 25], [w+27, -h-7, 29], [-w-25, h+20, 30], [w+30, h+23, 26], [-w-12,h+46,24], [w+10,h+58,31], [-w-65,h+75,32], [w+72,h+80,29]].map(([x,z,size], i) => { const clone = model.clone(true); if (i > 3) clone.traverse(node => { node.castShadow = false }); return { x, z, size: size / height, rotation: i * 2.399, clone } })
  }, [bounds.width, bounds.height, model, height])
  return <group position={[bounds.cx, -.6, bounds.cy]} dispose={null}>{placements.map((p, i) => <group key={i} position={[p.x, 0, p.z]} rotation={[0, p.rotation, 0]} scale={p.size}><primitive object={p.clone} /></group>)}</group>
}

export function Landscape({ bounds }: { bounds: Bounds }) {
  const size = Math.max(2000, Math.max(bounds.width, bounds.height) * 30)
  const roadZ = bounds.minY - 34
  return <group userData={{ captureHide: true }}>
    <mesh rotation={[-Math.PI / 2, 0, 0]} position={[bounds.cx, -.65, bounds.cy]} receiveShadow><planeGeometry args={[size, size]} /><SurfaceMaterial finish="grass" color="#d6dcc7" matchStyle={false} /></mesh>
    {/* A modest access street and paving give the aerial camera familiar scale. */}
    <mesh position={[bounds.cx, -.6, roadZ]} receiveShadow><boxGeometry args={[size, .08, 19]} /><SurfaceMaterial finish="stone" color="#535758" matchStyle={false} /></mesh>
    {[-12.5, 12.5].map(offset => <mesh key={offset} position={[bounds.cx, -.43, roadZ + offset]} receiveShadow><boxGeometry args={[size, .3, 5]} /><SurfaceMaterial finish="stone" color="#c4c0b5" matchStyle={false} /></mesh>)}
    <mesh position={[bounds.minX + 5, -.38, bounds.minY - 10]} receiveShadow><boxGeometry args={[10, .38, 20]} /><SurfaceMaterial finish="stone" color="#bdb9aa" matchStyle={false} /></mesh>
    <LandscapeTrees bounds={bounds} />
  </group>
}

export function FloorSlab({ polygon, y = -.32, roof = false, thickness = .32, photoreal = false }: { polygon: number[][]; y?: number; roof?: boolean; thickness?: number; photoreal?: boolean }) {
  const geometry = useMemo(() => {
    const shape = new THREE.Shape(polygon.map(([x,z]) => new THREE.Vector2(x, -z)))
    const geometry = new THREE.ExtrudeGeometry(shape, { depth: roof ? .38 : thickness, bevelEnabled: false })
    geometry.rotateX(-Math.PI / 2)
    return geometry
  }, [polygon, roof, thickness])
  useEffect(() => () => geometry.dispose(), [geometry])
  return <mesh geometry={geometry} position={[0,y,0]} receiveShadow castShadow><SurfaceMaterial finish="stone" color={roof ? '#616568' : '#b6b2a8'} photoreal={photoreal} /></mesh>
}
