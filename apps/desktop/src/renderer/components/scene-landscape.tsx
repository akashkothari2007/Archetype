import { useEffect, useMemo, Suspense } from 'react'
import { Cloud, Clouds, Environment, Sky, Stars, useGLTF, useTexture } from '@react-three/drei'
import * as THREE from 'three'
import type { Building } from '../types'
import { floorBounds } from './editor-geometry'
import { SurfaceMaterial } from './scene-materials'

type Bounds = ReturnType<typeof floorBounds>

export function Daylight({ bounds, environment }: { bounds: Bounds; environment: Building['environment'] }) {
  const day = Math.max(0, Math.sin((environment.time - 6) / 12 * Math.PI))
  const elevation = Math.max(.05, day * (environment.season === 'winter' ? .4 : environment.season === 'summer' ? .98 : .66))
  const angle = environment.sun_azimuth * Math.PI / 180
  const span = Math.max(bounds.width, bounds.height, 35)
  const sun: [number, number, number] = [Math.cos(angle), elevation, Math.sin(angle)]
  const target = useMemo(() => { const node = new THREE.Object3D(); node.position.set(bounds.cx, 4, bounds.cy); return node }, [bounds.cx, bounds.cy])
  const look = useMemo(() => {
    const t = Math.pow(day, 0.72)
    return {
      sun: new THREE.Color().lerpColors(new THREE.Color('#ff6a28'), new THREE.Color('#ffd0a0'), t),
      fill: new THREE.Color().lerpColors(new THREE.Color('#ffb07a'), new THREE.Color('#ffd8bc'), t),
      fog: new THREE.Color().lerpColors(new THREE.Color('#e8b48a'), new THREE.Color('#edd9c2'), t),
      hemiSky: new THREE.Color().lerpColors(new THREE.Color('#f2be9c'), new THREE.Color('#f3deca'), t),
      hemiGround: new THREE.Color('#8a705c'),
      turbidity: THREE.MathUtils.lerp(9.4, 4.6, t),
      rayleigh: THREE.MathUtils.lerp(0.42, 0.82, t),
      mieCoefficient: THREE.MathUtils.lerp(0.016, 0.006, t),
      mieDirectionalG: THREE.MathUtils.lerp(0.94, 0.8, t),
      cloud: new THREE.Color().lerpColors(new THREE.Color('#ffd2b0'), new THREE.Color('#fff4e8'), t),
    }
  }, [day])
  const sky = <Sky distance={450000} sunPosition={sun} turbidity={look.turbidity} rayleigh={look.rayleigh} mieCoefficient={look.mieCoefficient} mieDirectionalG={look.mieDirectionalG} />
  return <>
    <color attach="background" args={[look.fog]} />
    <fog attach="fog" args={[look.fog, Math.max(span * 3.5, 140), Math.max(span * 14, 980)]} />
    <group userData={{ captureHide: true }}>
      {sky}
      {day < 0.14 && <Stars radius={280} depth={50} count={1200} factor={2.4} saturation={0.2} fade speed={0} />}
      {day > 0.08 && <Suspense fallback={null}><Clouds texture="assets/landscape/cloud.png" material={THREE.MeshBasicMaterial} frustumCulled={false}>
        <Cloud seed={2} color={look.cloud} opacity={0.38} speed={0} segments={22} volume={28} bounds={[span * 1.4, 10, span * 0.7]} position={[bounds.cx + span * 0.9, 62, bounds.cy - span * 0.4]} fade={40} />
        <Cloud seed={7} color={look.cloud} opacity={0.3} speed={0} segments={20} volume={22} bounds={[span, 8, span * 0.55]} position={[bounds.cx - span * 1.1, 54, bounds.cy + span * 0.7]} fade={40} />
        <Cloud seed={11} color={look.cloud} opacity={0.26} speed={0} segments={18} volume={18} bounds={[span * 0.8, 7, span * 0.45]} position={[bounds.cx + span * 0.2, 70, bounds.cy + span * 1.2]} fade={50} />
      </Clouds></Suspense>}
    </group>
    <Environment key={`${environment.time}-${environment.season}-${environment.sun_azimuth}`} frames={1} resolution={256} environmentIntensity={0.42 + day * 0.28}>
      {sky}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -12, 0]}><planeGeometry args={[8000, 8000]} /><meshBasicMaterial color="#7a6a58" /></mesh>
    </Environment>
    <hemisphereLight args={[look.hemiSky, look.hemiGround, 0.38 + day * 0.22]} />
    <primitive object={target} />
    <directionalLight target={target} position={[bounds.cx + sun[0] * span * 1.8, sun[1] * span * 1.8 + 18, bounds.cy + sun[2] * span * 1.8]} intensity={0.55 + day * 2.15} color={look.sun} castShadow shadow-mapSize={[2048, 2048]} shadow-camera-left={-span * 1.5} shadow-camera-right={span * 1.5} shadow-camera-top={span * 1.5} shadow-camera-bottom={-span * 1.5} shadow-camera-near={1} shadow-camera-far={span * 10} shadow-bias={-.00004} shadow-normalBias={.035} shadow-radius={2} />
    <directionalLight position={[bounds.cx - sun[0] * span, 18, bounds.cy - sun[2] * span]} intensity={0.18 + day * 0.12} color={look.fill} />
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
