import { Suspense, useContext, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { TransformControls } from '@react-three/drei'
import { EastNorthUpFrame, GlobeControls, TilesAttributionOverlay, TilesPlugin, TilesRenderer, TilesRendererContext } from '3d-tiles-renderer/r3f'
import { CesiumIonAuthPlugin, GLTFExtensionsPlugin, TileCompressionPlugin, TilesFadePlugin, UnloadTilesPlugin } from '3d-tiles-renderer/plugins'
import { DRACOLoader } from 'three/examples/jsm/loaders/DRACOLoader.js'
import * as THREE from 'three'
import type { Building, ModelCommand } from '../types'
import { BuildingShell, buildingHeightFt } from './scene-building'
import { AppearanceContext, type AppearancePalette } from './appearance-context'
import { GOOGLE_TILES_ASSET_ID, METERS_PER_FOOT, assessSite, emptySite, formatLatLon, haversineMeters, ionToken, planToLocal, samplePlan, siteCameraOffset, siteFootprint, siteSun, type Sample, type SiteReport } from './site-geometry'
import { consumeSiteFrame, consumeSitePlace, peekSitePlace } from './site-intent'

// Google's photorealistic tiles arrive Draco compressed; the decoder is served from public/.
const draco = new DRACOLoader().setDecoderPath('draco/')
const verdictColor: Record<string, string> = { buildable: '#4c8b5a', caution: '#b8873a', blocked: '#a9503f', unknown: '#78838b' }
const scratch = {
  inverse: new THREE.Matrix4(),
  east: new THREE.Vector3(),
  north: new THREE.Vector3(),
  up: new THREE.Vector3(),
  origin: new THREE.Vector3(),
  down: new THREE.Vector3(),
  local: new THREE.Vector3(),
  target: new THREE.Vector3(),
  camera: new THREE.Vector3(),
  ndc: new THREE.Vector2(),
  carto: { lat: 0, lon: 0, height: 0 },
}

type Props = { building: Building; report: SiteReport | null; onReport: (report: SiteReport | null) => void; onCommand: (commands: ModelCommand[]) => void; palette?: AppearancePalette | null; enhanced?: boolean }

export function SiteView({ building, report, onReport, onCommand, palette = null, enhanced = false }: Props) {
  const site = building.site ?? emptySite
  const [placing, setPlacing] = useState(site.lat == null || site.lon == null || peekSitePlace())
  const [recenter, setRecenter] = useState(0)
  const [selected, setSelected] = useState(false)
  useEffect(() => { if (site.lat == null || site.lon == null) setPlacing(true) }, [site.lat, site.lon])
  useEffect(() => {
    const apply = () => {
      if (consumeSitePlace()) setPlacing(true)
      const frames = consumeSiteFrame()
      if (frames) setRecenter(value => value + frames)
    }
    window.addEventListener('archetype:show-site', apply)
    apply()
    return () => window.removeEventListener('archetype:show-site', apply)
  }, [])
  useEffect(() => { window.dispatchEvent(new CustomEvent('archetype:site-placing', { detail: placing })) }, [placing])

  if (!ionToken) return <div className="editor-scene-error"><strong>Add a Cesium ion token to see the globe.</strong><p>Put a free Community token in <code>VITE_CESIUM_ION_TOKEN</code> in your <code>.env</code> and restart the dev server. It needs the assets:read and geocode scopes.</p></div>

  const place = (lat: number, lon: number, address = '') => {
    onCommand([{ kind: 'set_site', target_id: '', params: address ? { lat, lon, address } : { lat, lon } }])
    setPlacing(false)
  }

  const rotate = (delta: number) => {
    const rotation_deg = normalizeDegrees(site.rotation_deg + delta)
    onCommand([{ kind: 'set_site', target_id: '', params: { rotation_deg } }])
  }

  // The generated Gaussian is a single-view reconstruction and breaks into
  // translucent layers from overhead. On site, project its generated material
  // direction onto the measured shell so every orbit remains solid and accurate.
  return <AppearanceContext.Provider value={{ map: null, roofMap: null, matrix: null, palette, splatUrl: null, apply: enhanced && !!palette }}><>
    <Canvas
      className={placing ? 'site-placing' : undefined}
      dpr={[1, 1.5]}
      frameloop="always"
      camera={{ position: [1.8e7, -8e6, 8e6], fov: 45, near: 1, far: 1e8 }}
      gl={{ antialias: true, logarithmicDepthBuffer: true, toneMapping: THREE.NoToneMapping }}
      onPointerMissed={() => setSelected(false)}
    >
      <color attach="background" args={['#07090d']} />
      <SiteScene building={building} report={report} onReport={onReport} onCommand={onCommand} placing={placing} recenter={recenter} selected={selected} onSelect={() => setSelected(true)} onPlace={(lat, lon) => place(lat, lon, site.address || formatLatLon({ lat, lon }))} />
    </Canvas>
    {selected && <div className="editor-site-selection" role="toolbar" aria-label="Building rotation">
      <strong>Building selected</strong>
      <span>{Math.round(normalizeDegrees(site.rotation_deg))}°</span>
      <button type="button" aria-label="Rotate building left 5 degrees" onClick={() => rotate(-5)}>−5°</button>
      <button type="button" aria-label="Rotate building right 5 degrees" onClick={() => rotate(5)}>+5°</button>
      <button type="button" aria-label="Clear building selection" onClick={() => setSelected(false)}>×</button>
    </div>}
  </></AppearanceContext.Provider>
}

function SiteScene({ building, report, onReport, onCommand, placing, recenter, selected, onSelect, onPlace }: { building: Building; report: SiteReport | null; onReport: Props['onReport']; onCommand: Props['onCommand']; placing: boolean; recenter: number; selected: boolean; onSelect: () => void; onPlace: (lat: number, lon: number) => void }) {
  const site = building.site ?? emptySite
  const lat = site.lat, lon = site.lon
  const azimuth = site.rotation_deg * Math.PI / 180
  const footprint = useMemo(() => siteFootprint(building), [building])
  const [grade, setGrade] = useState<number | null>(null)
  const span = Math.max(footprint.width, footprint.height, buildingHeightFt(building)) * METERS_PER_FOOT
  const height = (grade ?? 0) + site.ground_offset_ft * METERS_PER_FOOT
  const sited = lat != null && lon != null
  const controls = useRef<any>(null)
  return <>
    <TilesRenderer errorTarget={8} onLoadModel={event => makeTilesPhotoreal(event.scene)}>
      <TilesPlugin plugin={CesiumIonAuthPlugin} args={{ apiToken: ionToken, assetId: String(GOOGLE_TILES_ASSET_ID), autoRefreshToken: true } as never} />
      <TilesPlugin plugin={GLTFExtensionsPlugin} args={{ dracoLoader: draco } as never} />
      <TilesPlugin plugin={TileCompressionPlugin} />
      <TilesPlugin plugin={UnloadTilesPlugin} />
      <TilesPlugin plugin={TilesFadePlugin} />
      <UnlitTiles />
      <GlobeControls ref={controls} enableDamping dampingFactor={0.12} enableFlight />
      <SitePicker placing={placing} onPlace={onPlace} />
      {placing && <HoverPad footprint={footprint} rotation={site.rotation_deg} />}
      {sited && <GroundProbe building={building} lat={lat} lon={lon} rotation={site.rotation_deg} onGrade={setGrade} onReport={onReport} />}
      {sited && <EastNorthUpFrame lat={lat * Math.PI / 180} lon={lon * Math.PI / 180} height={height}>
        <LitSiteModel>
          {sited && <SiteDaylight lat={lat} />}
          <SiteBuilding building={building} footprint={footprint} report={report} azimuth={azimuth} selected={selected} controls={controls} onSelect={onSelect} onCommand={onCommand} />
        </LitSiteModel>
      </EastNorthUpFrame>}
      <FlyTo lat={lat} lon={lon} span={span} ground={grade} recenter={recenter} controls={controls} />
      <TilesAttributionOverlay />
    </TilesRenderer>
  </>
}

/** Google's textures are already lit. Keep scene lights off them so the aerial stays photographic. */
function makeTilesPhotoreal(scene: THREE.Object3D) {
  scene.traverse(node => {
    if (!(node instanceof THREE.Mesh) || node.userData.archetypeUnlit) return
    node.userData.archetypeUnlit = true
    const materials = Array.isArray(node.material) ? node.material : [node.material]
    for (const material of materials) {
      material.toneMapped = false
      if ('fog' in material) material.fog = false
      if ('envMapIntensity' in material) (material as THREE.MeshStandardMaterial).envMapIntensity = 0
      if (material instanceof THREE.MeshStandardMaterial || material instanceof THREE.MeshPhysicalMaterial) {
        if (material.map) {
          material.emissiveMap = material.map
          material.emissive.setRGB(1, 1, 1)
          material.emissiveIntensity = 1
          material.color.setRGB(1, 1, 1)
        }
        material.metalness = 0
        material.roughness = 1
      }
    }
  })
}

function SiteDaylight({ lat }: { lat: number }) {
  const sun = useMemo(() => siteSun(lat), [lat])
  const target = useMemo(() => new THREE.Object3D(), [])
  const key = useRef<THREE.DirectionalLight>(null)
  const fill = useRef<THREE.DirectionalLight>(null)
  const reach = 80
  useLayoutEffect(() => {
    for (const light of [key.current, fill.current]) {
      if (!light) continue
      light.target = target
      light.target.updateMatrixWorld()
    }
  }, [target])
  return <group>
    <primitive object={target} />
    <ambientLight intensity={0.82} color="#f4f1eb" />
    <hemisphereLight args={['#e8f1f7', '#aaa497', 1.65]} rotation={[Math.PI / 2, 0, 0]} />
    <directionalLight ref={key} position={[sun.east * reach, sun.north * reach, sun.up * reach]} intensity={3.45} color="#fff9ef" />
    <directionalLight ref={fill} position={[-sun.east * reach * 0.55, -sun.north * reach * 0.55, sun.up * reach * 0.22]} intensity={1.05} color="#dce8f2" />
  </group>
}

function normalizeDegrees(value: number) {
  return (value % 360 + 360) % 360
}

function SiteBuilding({ building, footprint, report, azimuth, selected, controls, onSelect, onCommand }: { building: Building; footprint: ReturnType<typeof siteFootprint>; report: SiteReport | null; azimuth: number; selected: boolean; controls: React.RefObject<any>; onSelect: () => void; onCommand: Props['onCommand'] }) {
  const ref = useRef<THREE.Group>(null)
  const height = buildingHeightFt(building)
  useLayoutEffect(() => {
    if (ref.current) ref.current.rotation.z = -azimuth
  }, [azimuth])
  const content = <group ref={ref} rotation={[0, 0, -azimuth]} userData={{ siteBuilding: true }}>
    <group rotation={[Math.PI / 2, 0, 0]} scale={METERS_PER_FOOT}>
      <SitePad footprint={footprint} report={report} />
      <group position={[-footprint.cx, 0, -footprint.cy]}>
        <Suspense fallback={null}><BuildingShell building={building} onSelect={onSelect} /></Suspense>
      </group>
      <mesh position={[0, height / 2, 0]} onClick={event => { event.stopPropagation(); onSelect() }} userData={{ siteBuilding: true }}>
        <boxGeometry args={[Math.max(footprint.width, 1), Math.max(height, 1), Math.max(footprint.height, 1)]} />
        <meshBasicMaterial transparent opacity={0} depthWrite={false} colorWrite={false} />
      </mesh>
    </group>
  </group>
  if (!selected) return content
  return <TransformControls mode="rotate" space="local" showX={false} showY={false} showZ size={0.78} rotationSnap={Math.PI / 36} onMouseDown={() => { if (controls.current) controls.current.enabled = false }} onMouseUp={() => {
    if (controls.current) controls.current.enabled = true
    const node = ref.current
    if (!node) return
    const rotation = normalizeDegrees(-node.rotation.z * 180 / Math.PI)
    if (Math.abs(rotation - normalizeDegrees(building.site?.rotation_deg ?? 0)) < .01) return
    onCommand([{ kind: 'set_site', target_id: '', params: { rotation_deg: rotation } }])
  }}>{content}</TransformControls>
}

function LitSiteModel({ children }: { children: ReactNode }) {
  const ref = useRef<THREE.Group>(null)
  const camera = useThree(state => state.camera)
  useEffect(() => {
    camera.layers.enable(1)
    return () => { camera.layers.disable(1) }
  }, [camera])
  useFrame(() => {
    ref.current?.traverse(node => {
      if (node.layers.mask !== 2) node.layers.set(1)
      if (!(node instanceof THREE.Mesh) || node.userData.siteToneMatched) return
      node.userData.siteToneMatched = true
      const materials = Array.isArray(node.material) ? node.material : [node.material]
      for (const material of materials) {
        if (!material) continue
        material.toneMapped = false
        if ('envMapIntensity' in material) material.envMapIntensity = 0.18
        if ('envMap' in material) material.envMap = null
      }
    })
  })
  return <group ref={ref}>{children}</group>
}

function UnlitTiles() {
  const tiles = useContext(TilesRendererContext) as { addEventListener: (name: string, cb: (event: { scene: THREE.Object3D }) => void) => void; removeEventListener: (name: string, cb: (event: { scene: THREE.Object3D }) => void) => void; forEachLoadedModel: (cb: (scene: THREE.Object3D) => void) => void } | null
  useEffect(() => {
    if (!tiles) return
    const paint = (event: { scene: THREE.Object3D }) => makeTilesPhotoreal(event.scene)
    tiles.addEventListener('load-model', paint)
    tiles.forEachLoadedModel(scene => makeTilesPhotoreal(scene))
    return () => tiles.removeEventListener('load-model', paint)
  }, [tiles])
  return null
}

function pickFromTiles(tiles: { group: THREE.Object3D; ellipsoid: { getPositionToCartographic: (pos: THREE.Vector3, target: { lat: number; lon: number; height: number }) => void } }, camera: THREE.Camera, clientX: number, clientY: number, element: HTMLElement) {
  const rect = element.getBoundingClientRect()
  scratch.ndc.set((clientX - rect.left) / rect.width * 2 - 1, -(clientY - rect.top) / rect.height * 2 + 1)
  const raycaster = new THREE.Raycaster()
  raycaster.far = 1e8
  raycaster.setFromCamera(scratch.ndc, camera)
  const hit = raycaster.intersectObject(tiles.group, true).find(item => {
    let node: THREE.Object3D | null = item.object
    while (node) { if (node.userData.siteBuilding) return false; node = node.parent }
    return true
  })
  if (!hit) return null
  scratch.inverse.copy(tiles.group.matrixWorld).invert()
  scratch.local.copy(hit.point).applyMatrix4(scratch.inverse)
  tiles.ellipsoid.getPositionToCartographic(scratch.local, scratch.carto)
  return { lat: scratch.carto.lat * 180 / Math.PI, lon: scratch.carto.lon * 180 / Math.PI, height: scratch.carto.height }
}

function SitePicker({ placing, onPlace }: { placing: boolean; onPlace: (lat: number, lon: number) => void }) {
  const tiles = useContext(TilesRendererContext) as { group: THREE.Object3D; ellipsoid: { getPositionToCartographic: (pos: THREE.Vector3, target: { lat: number; lon: number; height: number }) => void } } | null
  const camera = useThree(state => state.camera)
  const gl = useThree(state => state.gl)
  const drag = useRef({ x: 0, y: 0, moved: false })
  const onPlaceRef = useRef(onPlace)
  onPlaceRef.current = onPlace
  useEffect(() => {
    const element = gl.domElement
    const down = (event: PointerEvent) => { if (event.button !== 0) return; drag.current = { x: event.clientX, y: event.clientY, moved: false } }
    const move = (event: PointerEvent) => { if (Math.hypot(event.clientX - drag.current.x, event.clientY - drag.current.y) > 7) drag.current.moved = true }
    const up = (event: PointerEvent) => {
      if (!placing || !tiles?.group || drag.current.moved || event.button !== 0) return
      const hit = pickFromTiles(tiles, camera, event.clientX, event.clientY, element)
      if (hit) onPlaceRef.current(hit.lat, hit.lon)
    }
    element.addEventListener('pointerdown', down)
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
    return () => {
      element.removeEventListener('pointerdown', down)
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
    }
  }, [placing, tiles, camera, gl])
  return null
}

function HoverPad({ footprint, rotation }: { footprint: ReturnType<typeof siteFootprint>; rotation: number }) {
  const tiles = useContext(TilesRendererContext) as { group: THREE.Object3D; ellipsoid: { getPositionToCartographic: (pos: THREE.Vector3, target: { lat: number; lon: number; height: number }) => void } } | null
  const { camera, gl } = useThree()
  const pointer = useRef({ x: 0, y: 0, inside: false })
  const [pose, setPose] = useState<{ lat: number; lon: number; height: number } | null>(null)
  useEffect(() => {
    const element = gl.domElement
    const move = (event: PointerEvent) => {
      const rect = element.getBoundingClientRect()
      pointer.current = { x: event.clientX, y: event.clientY, inside: event.clientX >= rect.left && event.clientX <= rect.right && event.clientY >= rect.top && event.clientY <= rect.bottom }
    }
    const leave = () => { pointer.current.inside = false }
    window.addEventListener('pointermove', move)
    element.addEventListener('pointerleave', leave)
    return () => { window.removeEventListener('pointermove', move); element.removeEventListener('pointerleave', leave) }
  }, [gl])
  useFrame(() => {
    if (!tiles?.group || !pointer.current.inside) { if (pose) setPose(null); return }
    const hit = pickFromTiles(tiles, camera, pointer.current.x, pointer.current.y, gl.domElement)
    if (!hit) { if (pose) setPose(null); return }
    if (!pose || Math.abs(pose.lat - hit.lat) > 1e-6 || Math.abs(pose.lon - hit.lon) > 1e-6) setPose(hit)
  })
  if (!pose) return null
  return <EastNorthUpFrame lat={pose.lat * Math.PI / 180} lon={pose.lon * Math.PI / 180} height={pose.height} az={rotation * Math.PI / 180}>
    <group rotation={[Math.PI / 2, 0, 0]} scale={METERS_PER_FOOT}>
      <mesh position={[0, .4, 0]} rotation={[-Math.PI / 2, 0, 0]} userData={{ siteBuilding: true }}>
        <planeGeometry args={[footprint.width, footprint.height]} />
        <meshBasicMaterial color="#7d9cb0" transparent opacity={.35} depthWrite={false} side={THREE.DoubleSide} />
      </mesh>
    </group>
  </EastNorthUpFrame>
}

function enuAxes(ellipsoid: { getEastNorthUpAxes?: (lat: number, lon: number, east: THREE.Vector3, north: THREE.Vector3, up: THREE.Vector3, pos?: THREE.Vector3) => void; getCartographicToNormal: (lat: number, lon: number, target: THREE.Vector3) => THREE.Vector3; getCartographicToPosition: (lat: number, lon: number, height: number, target: THREE.Vector3) => THREE.Vector3 }, lat: number, lon: number, height = 0) {
  if (ellipsoid.getEastNorthUpAxes) {
    ellipsoid.getEastNorthUpAxes(lat, lon, scratch.east, scratch.north, scratch.up)
  } else {
    ellipsoid.getCartographicToNormal(lat, lon, scratch.up)
    scratch.east.set(0, 0, 1).cross(scratch.up)
    if (scratch.east.lengthSq() < 1e-8) scratch.east.set(1, 0, 0).cross(scratch.up)
    scratch.east.normalize()
    scratch.north.copy(scratch.up).cross(scratch.east).normalize()
  }
  ellipsoid.getCartographicToPosition(lat, lon, height, scratch.origin)
}

function GroundProbe({ building, lat, lon, rotation, onGrade, onReport }: { building: Building; lat: number; lon: number; rotation: number; onGrade: (v: number | null) => void; onReport: Props['onReport'] }) {
  const tiles = useContext(TilesRendererContext) as { group: THREE.Object3D; ellipsoid: { getEastNorthUpAxes?: (lat: number, lon: number, east: THREE.Vector3, north: THREE.Vector3, up: THREE.Vector3, pos?: THREE.Vector3) => void; getCartographicToNormal: (lat: number, lon: number, target: THREE.Vector3) => THREE.Vector3; getCartographicToPosition: (lat: number, lon: number, height: number, target: THREE.Vector3) => THREE.Vector3; getPositionToCartographic: (pos: THREE.Vector3, target: { lat: number; lon: number; height: number }) => void }; root?: unknown } | null
  const invalidate = useThree(state => state.invalidate)
  const nextTry = useRef(0)
  const attempts = useRef(0)
  const points = useMemo(() => samplePlan(building, 5), [building.vertices, building.floors])
  const centre = useMemo(() => { const box = siteFootprint(building); return { x: box.cx, y: box.cy } }, [building.vertices])
  useEffect(() => {
    nextTry.current = 0
    attempts.current = 0
    onGrade(null)
    onReport(null)
  }, [lat, lon, rotation, points, onGrade, onReport])
  useFrame(({ clock }) => {
    if (!tiles?.group || !tiles.ellipsoid || attempts.current >= 8 || clock.elapsedTime < nextTry.current) return
    if (!tiles.root) { nextTry.current = clock.elapsedTime + .4; return }
    const latRad = lat * Math.PI / 180, lonRad = lon * Math.PI / 180
    enuAxes(tiles.ellipsoid, latRad, lonRad)
    const east = scratch.east.clone(), north = scratch.north.clone(), up = scratch.up.clone(), origin = scratch.origin.clone()
    scratch.inverse.copy(tiles.group.matrixWorld).invert()
    const raycaster = new THREE.Raycaster()
    raycaster.far = 80000
    const samples: Sample[] = []
    for (const point of points) {
      const offset = planToLocal(point, centre, rotation)
      scratch.origin.copy(origin).addScaledVector(east, offset.east).addScaledVector(north, offset.north).addScaledVector(up, 25000).applyMatrix4(tiles.group.matrixWorld)
      scratch.down.copy(up).negate().transformDirection(tiles.group.matrixWorld)
      raycaster.set(scratch.origin, scratch.down)
      const hit = raycaster.intersectObject(tiles.group, true).find(item => {
        let node: THREE.Object3D | null = item.object
        while (node) { if (node.userData.siteBuilding) return false; node = node.parent }
        return true
      })
      if (!hit) continue
      scratch.local.copy(hit.point).applyMatrix4(scratch.inverse)
      tiles.ellipsoid.getPositionToCartographic(scratch.local, scratch.carto)
      samples.push({ east: offset.east, north: offset.north, up: scratch.carto.height })
    }
    attempts.current += 1
    if (!samples.length) {
      nextTry.current = clock.elapsedTime + 1.2
      return
    }
    attempts.current = 8
    const report = assessSite(samples, points.length)
    onGrade(report.meanUp)
    onReport(report)
    invalidate()
  })
  return null
}

function FlyTo({ lat, lon, span, ground, recenter, controls }: { lat: number | null; lon: number | null; span: number; ground: number | null; recenter: number; controls: { current: { resetState: () => void; pivotPoint: THREE.Vector3 } | null } }) {
  const tiles = useContext(TilesRendererContext) as { group: THREE.Object3D; ellipsoid: { getEastNorthUpAxes?: (lat: number, lon: number, east: THREE.Vector3, north: THREE.Vector3, up: THREE.Vector3, pos?: THREE.Vector3) => void; getCartographicToNormal: (lat: number, lon: number, target: THREE.Vector3) => THREE.Vector3; getCartographicToPosition: (lat: number, lon: number, height: number, target: THREE.Vector3) => THREE.Vector3 } } | null
  const camera = useThree(state => state.camera)
  const last = useRef<{ lat: number; lon: number; recenter: number; ground: number | null } | null>(null)
  useFrame(() => {
    if (!tiles?.ellipsoid || lat == null || lon == null) return
    const previous = last.current
    const jumped = !previous || previous.recenter !== recenter || previous.ground !== ground || haversineMeters(previous, { lat, lon }) > 250
    if (!jumped) return
    last.current = { lat, lon, recenter, ground }
    const { terrain, hover, lookUp } = siteCameraOffset(span, ground)
    const latRad = lat * Math.PI / 180, lonRad = lon * Math.PI / 180
    enuAxes(tiles.ellipsoid, latRad, lonRad, terrain)
    scratch.target.copy(scratch.origin).addScaledVector(scratch.up, lookUp).applyMatrix4(tiles.group.matrixWorld)
    scratch.camera.copy(scratch.origin).addScaledVector(scratch.up, lookUp + hover * 0.88).addScaledVector(scratch.north, -hover * 0.82).applyMatrix4(tiles.group.matrixWorld)
    camera.up.copy(scratch.up).transformDirection(tiles.group.matrixWorld)
    camera.position.copy(scratch.camera)
    camera.lookAt(scratch.target)
    camera.updateMatrixWorld()
    controls.current?.resetState()
    controls.current?.pivotPoint.copy(scratch.target)
  })
  return null
}

function SitePad({ footprint, report }: { footprint: ReturnType<typeof siteFootprint>; report: SiteReport | null }) {
  return <mesh position={[0, .35, 0]} rotation={[-Math.PI / 2, 0, 0]} userData={{ siteBuilding: true }}>
    <planeGeometry args={[footprint.width, footprint.height]} />
    <meshBasicMaterial color={verdictColor[report?.verdict || 'unknown']} transparent opacity={.2} depthWrite={false} side={THREE.DoubleSide} />
  </mesh>
}

export default SiteView
