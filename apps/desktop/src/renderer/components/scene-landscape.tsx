import { useEffect, useLayoutEffect, useMemo, useRef, Suspense } from 'react'
import { ContactShadows, Environment, Sky, Stars, useGLTF, useTexture } from '@react-three/drei'
import * as THREE from 'three'
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js'
import type { Building } from '../types'
import { floorBounds } from './editor-geometry'
import { SurfaceMaterial } from './scene-materials'
import { skyCloudFields, type CloudCopy } from './scene-clouds'
import { landscapeTreePlacements, type LandscapeTree } from './scene-trees'

type Bounds = ReturnType<typeof floorBounds>

export function Daylight({ bounds, environment }: { bounds: Bounds; environment: Building['environment'] }) {
  const day = Math.max(0, Math.sin((environment.time - 6) / 12 * Math.PI))
  const elevation = Math.max(.025, day * (environment.season === 'winter' ? .42 : environment.season === 'summer' ? .92 : .68))
  const angle = environment.sun_azimuth * Math.PI / 180
  const span = Math.max(bounds.width, bounds.height, 35)
  const sun: [number, number, number] = [Math.cos(angle) * 100, elevation * 100, Math.sin(angle) * 100]
  const target = useMemo(() => { const node = new THREE.Object3D(); node.position.set(bounds.cx, 4, bounds.cy); return node }, [bounds.cx, bounds.cy])
  const look = useMemo(() => {
    const t = Math.pow(day, 0.62)
    const golden = 1 - Math.min(1, day * 2.25)
    return {
      sun: new THREE.Color().lerpColors(new THREE.Color('#ff8a4c'), new THREE.Color('#fff3df'), t),
      fill: new THREE.Color().lerpColors(new THREE.Color('#637ea5'), new THREE.Color('#b9d2ea'), t),
      fog: new THREE.Color().lerpColors(new THREE.Color('#9a8491'), new THREE.Color('#cbd9df'), t),
      hemiSky: new THREE.Color().lerpColors(new THREE.Color('#667a9b'), new THREE.Color('#b8d8ed'), t),
      hemiGround: new THREE.Color().lerpColors(new THREE.Color('#51463f'), new THREE.Color('#726e59'), t),
      turbidity: THREE.MathUtils.lerp(9.2, 3.8, t),
      rayleigh: THREE.MathUtils.lerp(0.35, 1.15, t),
      mieCoefficient: THREE.MathUtils.lerp(0.018, 0.0045, t),
      mieDirectionalG: THREE.MathUtils.lerp(0.93, 0.78, t),
      cloud: new THREE.Color().lerpColors(new THREE.Color('#efb08d'), new THREE.Color('#f7f8f4'), t),
      golden,
    }
  }, [day])
  const sky = <Sky distance={450000} sunPosition={sun} turbidity={look.turbidity} rayleigh={look.rayleigh} mieCoefficient={look.mieCoefficient} mieDirectionalG={look.mieDirectionalG} />
  return <>
    <color attach="background" args={[look.fog]} />
    <fog attach="fog" args={[look.fog, Math.max(span * 4.5, 180), Math.max(span * 18, 1200)]} />
    <group userData={{ captureHide: true }}>
      {sky}
      {day < 0.14 && <Stars radius={280} depth={50} count={1200} factor={2.4} saturation={0.2} fade speed={0} />}
      {day > 0.08 && <Suspense fallback={null}><SkyClouds bounds={bounds} color={look.cloud} /></Suspense>}
    </group>
    <Environment key={`${environment.time}-${environment.season}-${environment.sun_azimuth}`} frames={1} resolution={256} environmentIntensity={0.48 + day * 0.36}>
      {sky}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -12, 0]}><planeGeometry args={[8000, 8000]} /><meshBasicMaterial color="#7a6a58" /></mesh>
    </Environment>
    <hemisphereLight args={[look.hemiSky, look.hemiGround, 0.42 + day * 0.26]} />
    <primitive object={target} />
    <directionalLight target={target} position={[bounds.cx + Math.cos(angle) * span * 2.2, elevation * span * 2.2 + 20, bounds.cy + Math.sin(angle) * span * 2.2]} intensity={0.45 + day * 2.35} color={look.sun} castShadow shadow-mapSize={[2048, 2048]} shadow-camera-left={-span * 1.5} shadow-camera-right={span * 1.5} shadow-camera-top={span * 1.5} shadow-camera-bottom={-span * 1.5} shadow-camera-near={1} shadow-camera-far={span * 10} shadow-bias={-.00003} shadow-normalBias={.025} shadow-radius={3} />
    <directionalLight position={[bounds.cx - Math.cos(angle) * span, 22, bounds.cy - Math.sin(angle) * span]} intensity={0.16 + day * 0.17} color={look.fill} />
  </>
}

function CloudBank({ url, color, copies }: { url: string; color: THREE.Color; copies: CloudCopy[] }) {
  const { scene } = useGLTF(url, false, false)
  const { geometry, material } = useMemo(() => {
    const cloned = scene.clone(true)
    cloned.updateMatrixWorld(true)
    const pieces: THREE.BufferGeometry[] = []
    cloned.traverse(node => {
      if (!(node instanceof THREE.Mesh)) return
      const piece = node.geometry.clone()
      piece.applyMatrix4(node.matrixWorld)
      pieces.push(piece)
    })
    const geometry = mergeGeometries(pieces, false)
    pieces.forEach(piece => piece.dispose())
    if (!geometry) throw new Error(`Cloud mesh failed to merge: ${url}`)
    geometry.computeBoundingSphere()
    const material = new THREE.MeshLambertMaterial({ color: '#f4f6f3', emissive: '#4a4e4c', fog: false, side: THREE.DoubleSide })
    return { geometry, material }
  }, [scene])
  useLayoutEffect(() => {
    material.color.copy(color)
    material.emissive.copy(color).multiplyScalar(0.28)
  }, [color, material])
  useEffect(() => () => { geometry.dispose(); material.dispose() }, [geometry, material])
  return <>{copies.map((copy, i) => <mesh key={i} geometry={geometry} material={material} position={[copy.x, copy.y, copy.z]} rotation={[0, copy.yaw, 0]} scale={copy.scale} />)}</>
}

function SkyClouds({ bounds, color }: { bounds: Bounds; color: THREE.Color }) {
  const fields = useMemo(() => skyCloudFields(bounds), [bounds])
  return <>
    <CloudBank url="assets/landscape/clouds/cumulus-2.glb" color={color} copies={fields.main} />
    <CloudBank url="assets/landscape/clouds/cumulus-5.glb" color={color} copies={fields.cluster} />
  </>
}

function seeded(index: number, salt = 0) {
  const value = Math.sin(index * 127.1 + salt * 311.7) * 43758.5453
  return value - Math.floor(value)
}

function terrainHeight(x: number, z: number, bounds: Bounds) {
  const dx = Math.max(0, Math.abs(x - bounds.cx) - bounds.width * .65)
  const dz = Math.max(0, Math.abs(z - bounds.cy) - bounds.height * .65)
  const fade = THREE.MathUtils.smoothstep(Math.hypot(dx, dz), 4, 80)
  return fade * (Math.sin(x * .025) * 1.25 + Math.cos(z * .021) * 1.05 + Math.sin((x + z) * .011) * .7)
}

function TerrainGround({ bounds, size }: { bounds: Bounds; size: number }) {
  const geometry = useMemo(() => {
    const geometry = new THREE.PlaneGeometry(size, size, 72, 72)
    const position = geometry.attributes.position
    for (let i = 0; i < position.count; i++) {
      const x = position.getX(i) + bounds.cx
      const z = -position.getY(i) + bounds.cy
      position.setZ(i, terrainHeight(x, z, bounds))
    }
    geometry.computeVertexNormals()
    return geometry
  }, [bounds, size])
  useEffect(() => () => geometry.dispose(), [geometry])
  return <mesh geometry={geometry} rotation={[-Math.PI / 2, 0, 0]} position={[bounds.cx, -.68, bounds.cy]} receiveShadow><SurfaceMaterial finish="grass" color="#aebc91" matchStyle={false} /></mesh>
}

function GrassTufts({ bounds, roadZ }: { bounds: Bounds; roadZ: number }) {
  const mesh = useRef<THREE.InstancedMesh>(null)
  const count = 1150
  const geometry = useMemo(() => {
    const positions: number[] = []
    const makeBlade = (angle: number, lean: number) => {
      const width = .055, height = .72
      const right = new THREE.Vector3(Math.cos(angle) * width, 0, Math.sin(angle) * width)
      const tip = new THREE.Vector3(Math.sin(angle) * lean, height, -Math.cos(angle) * lean)
      positions.push(-right.x, 0, -right.z, right.x, 0, right.z, tip.x, tip.y, tip.z)
    }
    makeBlade(0, .08); makeBlade(Math.PI / 3, -.04); makeBlade(Math.PI * 2 / 3, .05)
    const blade = new THREE.BufferGeometry()
    blade.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3))
    blade.computeVertexNormals()
    return blade
  }, [])
  useEffect(() => () => geometry.dispose(), [geometry])
  useLayoutEffect(() => {
    if (!mesh.current) return
    const dummy = new THREE.Object3D(), color = new THREE.Color()
    const radiusX = Math.max(54, bounds.width * 1.55), radiusZ = Math.max(48, bounds.height * 1.65)
    let written = 0, attempt = 0
    while (written < count && attempt < count * 8) {
      const x = bounds.cx + (seeded(attempt, 1) * 2 - 1) * radiusX
      const z = bounds.cy + (seeded(attempt, 2) * 2 - 1) * radiusZ
      attempt++
      const onBuilding = x > bounds.minX - 4 && x < bounds.maxX + 4 && z > bounds.minY - 4 && z < bounds.maxY + 4
      const onRoad = Math.abs(z - roadZ) < 13.8
      const onWalk = x > bounds.minX && x < bounds.minX + 10.5 && z > bounds.minY - 21 && z < bounds.minY + 1
      if (onBuilding || onRoad || onWalk) continue
      const scale = .55 + seeded(attempt, 3) * .9
      dummy.position.set(x, -.6 + terrainHeight(x, z, bounds), z)
      dummy.rotation.set(0, seeded(attempt, 4) * Math.PI, (seeded(attempt, 5) - .5) * .13)
      dummy.scale.set(scale, scale, scale)
      dummy.updateMatrix()
      mesh.current.setMatrixAt(written, dummy.matrix)
      color.setHSL(.23 + seeded(attempt, 6) * .055, .3 + seeded(attempt, 7) * .2, .27 + seeded(attempt, 8) * .18)
      mesh.current.setColorAt(written, color)
      written++
    }
    mesh.current.instanceMatrix.needsUpdate = true
    if (mesh.current.instanceColor) mesh.current.instanceColor.needsUpdate = true
  }, [bounds, roadZ])
  return <instancedMesh ref={mesh} args={[geometry, undefined, count]} castShadow receiveShadow frustumCulled={false}>
    <meshStandardMaterial color="#78905b" roughness={.96} metalness={0} side={THREE.DoubleSide} vertexColors />
  </instancedMesh>
}

function Shrub({ position, scale = 1, hue = 0 }: { position: [number, number, number]; scale?: number; hue?: number }) {
  const leaves = ['#52683e', '#62784a', '#758958', '#465d39']
  return <group position={position} scale={scale}>
    <mesh position={[0, .14, 0]} castShadow><cylinderGeometry args={[.08, .13, .5, 7]} /><meshStandardMaterial color="#584532" roughness={1} /></mesh>
    {[[0,.65,0, .72],[-.45,.52,.08,.52],[.42,.48,.03,.58],[-.16,.78,-.34,.48],[.2,.82,.3,.5]].map(([x,y,z,s], i) => <mesh key={i} position={[x,y,z]} scale={[s * 1.15,s,s]} castShadow receiveShadow><dodecahedronGeometry args={[1, 1]} /><meshStandardMaterial color={leaves[(i + hue) % leaves.length]} roughness={1} /></mesh>)}
  </group>
}

function Planting({ bounds }: { bounds: Bounds }) {
  const shrubs = useMemo(() => {
    const result: { p: [number, number, number]; scale: number; hue: number }[] = []
    const sides = [bounds.minY - 4.8, bounds.maxY + 4.8]
    for (let side = 0; side < sides.length; side++) for (let i = 0; i < 9; i++) {
      const t = (i + .45 + seeded(i, side + 10) * .2) / 9
      result.push({ p: [THREE.MathUtils.lerp(bounds.minX + 2, bounds.maxX - 2, t), -.52, sides[side] + (seeded(i, side + 20) - .5) * 1.4], scale: .55 + seeded(i, side + 30) * .35, hue: i + side })
    }
    return result
  }, [bounds])
  return <group>{shrubs.map((shrub, i) => <Shrub key={i} position={shrub.p} scale={shrub.scale} hue={shrub.hue} />)}</group>
}

function treeKind(name: string) {
  if (/leaves/.test(name)) return 'leaves'
  if (/branches/.test(name)) return 'branches'
  return 'trunk'
}

function writeTreeField(mesh: THREE.InstancedMesh | null, trees: LandscapeTree[], height: number, part: 'trunk' | 'leaves' | 'branches') {
  if (!mesh) return
  const dummy = new THREE.Object3D(), color = new THREE.Color()
  trees.forEach((tree, i) => {
    const sy = tree.size / height
    const canopy = part === 'trunk' ? 1 : tree.canopy
    const canopyY = part === 'leaves' ? tree.canopyY : part === 'branches' ? (tree.canopyY + 1) / 2 : 1
    dummy.position.set(tree.x, 0, tree.z)
    dummy.rotation.set(tree.pitch, tree.yaw, tree.roll)
    dummy.scale.set(sy * tree.width * canopy, sy * canopyY, sy * tree.width * canopy)
    dummy.updateMatrix()
    mesh.setMatrixAt(i, dummy.matrix)
    if (part === 'leaves') { color.setRGB(tree.leaf[0], tree.leaf[1], tree.leaf[2]); mesh.setColorAt(i, color) }
  })
  mesh.instanceMatrix.needsUpdate = true
  if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true
}

function TreeField({ parts, trees, height, shadow }: { parts: TreeParts; trees: LandscapeTree[]; height: number; shadow: boolean }) {
  const trunk = useRef<THREE.InstancedMesh>(null)
  const leaves = useRef<THREE.InstancedMesh>(null)
  const branches = useRef<THREE.InstancedMesh>(null)
  useLayoutEffect(() => {
    writeTreeField(trunk.current, trees, height, 'trunk')
    writeTreeField(leaves.current, trees, height, 'leaves')
    writeTreeField(branches.current, trees, height, 'branches')
  }, [trees, height])
  if (!trees.length) return null
  return <>
    {parts.trunk && <instancedMesh key={`trunk-${trees.length}`} ref={trunk} args={[parts.trunk.geometry, parts.trunk.material, trees.length]} castShadow={shadow} receiveShadow frustumCulled={false} />}
    {parts.leaves && <instancedMesh key={`leaves-${trees.length}`} ref={leaves} args={[parts.leaves.geometry, parts.leaves.material, trees.length]} castShadow={shadow} receiveShadow frustumCulled={false} />}
    {parts.branches && <instancedMesh key={`branches-${trees.length}`} ref={branches} args={[parts.branches.geometry, parts.branches.material, trees.length]} castShadow={shadow} receiveShadow frustumCulled={false} />}
  </>
}

type TreeParts = Record<'trunk' | 'leaves' | 'branches', { geometry: THREE.BufferGeometry; material: THREE.MeshStandardMaterial }>

// Actual textured 3D mesh, simplified offline; no billboards or camera-facing cards.
function LandscapeTrees({ bounds }: { bounds: Bounds }) {
  const { scene } = useGLTF('assets/landscape/tree/tree.gltf', false, false)
  const alpha = useTexture('assets/landscape/tree-leaves-alpha.png')
  const { parts, materials, geometries, height } = useMemo(() => {
    const model = scene.clone(true)
    model.updateMatrixWorld(true)
    const box = new THREE.Box3().setFromObject(model)
    const center = box.getCenter(new THREE.Vector3()), height = box.max.y - box.min.y
    const bake = new THREE.Matrix4().makeTranslation(-center.x, -box.min.y, -center.z)
    const materials: THREE.Material[] = [], geometries: THREE.BufferGeometry[] = []
    const parts = {} as TreeParts
    model.traverse(node => {
      if (!(node instanceof THREE.Mesh)) return
      const original = node.material as THREE.MeshStandardMaterial
      const geometry = node.geometry.clone()
      geometry.applyMatrix4(node.matrixWorld)
      geometry.applyMatrix4(bake)
      const material = original.clone()
      material.envMapIntensity = .7
      const kind = treeKind(original.name)
      if (kind === 'leaves') {
        alpha.flipY = false
        material.alphaMap = alpha
        material.alphaTest = .28
        material.transparent = false
        material.depthWrite = true
        material.side = THREE.DoubleSide
        material.roughness = 1
        material.metalness = 0
        material.vertexColors = true
        material.needsUpdate = true
      }
      materials.push(material)
      geometries.push(geometry)
      parts[kind] = { geometry, material }
    })
    return { parts, materials, geometries, height }
  }, [scene, alpha])
  useEffect(() => () => { materials.forEach(material => material.dispose()); geometries.forEach(geometry => geometry.dispose()) }, [materials, geometries])
  const placements = useMemo(() => landscapeTreePlacements(bounds), [bounds.width, bounds.height])
  const near = useMemo(() => placements.filter(tree => tree.shadow), [placements])
  const far = useMemo(() => placements.filter(tree => !tree.shadow), [placements])
  return <group position={[bounds.cx, -.6, bounds.cy]} dispose={null}>
    <TreeField parts={parts} trees={near} height={height} shadow />
    <TreeField parts={parts} trees={far} height={height} shadow={false} />
  </group>
}

export function Landscape({ bounds }: { bounds: Bounds }) {
  const size = Math.max(2000, Math.max(bounds.width, bounds.height) * 30)
  const roadZ = bounds.minY - 34
  return <group userData={{ captureHide: true }}>
    <TerrainGround bounds={bounds} size={size} />
    <GrassTufts bounds={bounds} roadZ={roadZ} />
    {/* Layered road, curbs, apron and planting give the model a believable scale and threshold. */}
    <mesh position={[bounds.cx, -.54, roadZ]} receiveShadow><boxGeometry args={[size, .16, 19]} /><meshStandardMaterial color="#45494a" roughness={.96} metalness={0} /></mesh>
    {[-9.65, 9.65].map(offset => <group key={offset}>
      <mesh position={[bounds.cx, -.37, roadZ + offset]} receiveShadow castShadow><boxGeometry args={[size, .34, .55]} /><meshStandardMaterial color="#a5a297" roughness={.9} /></mesh>
      <mesh position={[bounds.cx, -.5, roadZ + offset * 1.09]} receiveShadow><boxGeometry args={[size, .1, 1.3]} /><meshStandardMaterial color="#777a73" roughness={.96} /></mesh>
    </group>)}
    <mesh position={[bounds.cx, -.43, roadZ]} receiveShadow><boxGeometry args={[size, .025, .11]} /><meshStandardMaterial color="#d9d0b4" roughness={.78} /></mesh>
    {Array.from({ length: 18 }, (_, i) => <mesh key={`dash-${i}`} position={[bounds.cx - 180 + i * 22, -.4, roadZ]} receiveShadow><boxGeometry args={[10, .03, .22]} /><meshStandardMaterial color="#ddd6bc" roughness={.76} /></mesh>)}
    <mesh position={[bounds.minX + 5, -.34, bounds.minY - 10]} receiveShadow castShadow><boxGeometry args={[10, .42, 20]} /><SurfaceMaterial finish="stone" color="#b5b0a3" matchStyle={false} /></mesh>
    <mesh position={[bounds.minX + 5, -.1, bounds.minY - 4]} receiveShadow><boxGeometry args={[7.2, .08, 8]} /><SurfaceMaterial finish="stone" color="#c7c0ae" matchStyle={false} /></mesh>
    <Planting bounds={bounds} />
    <LandscapeTrees bounds={bounds} />
    <ContactShadows position={[bounds.cx, -.31, bounds.cy]} scale={Math.max(bounds.width, bounds.height) * 2.1} opacity={.32} blur={2.3} far={Math.max(45, Math.max(bounds.width, bounds.height))} resolution={512} frames={1} color="#293028" />
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

useGLTF.preload('assets/landscape/clouds/cumulus-2.glb')
useGLTF.preload('assets/landscape/clouds/cumulus-5.glb')
useGLTF.preload('assets/landscape/tree/tree.gltf')
