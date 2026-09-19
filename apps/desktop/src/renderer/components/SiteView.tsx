import { Suspense, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { OrbitControls } from '@react-three/drei'
import { EastNorthUpFrame, TilesAttributionOverlay, TilesPlugin, TilesRenderer, TilesRendererContext } from '3d-tiles-renderer/r3f'
import { CesiumIonAuthPlugin, GLTFExtensionsPlugin, ReorientationPlugin, TileCompressionPlugin, TilesFadePlugin, UnloadTilesPlugin } from '3d-tiles-renderer/plugins'
import { DRACOLoader } from 'three/examples/jsm/loaders/DRACOLoader.js'
import * as THREE from 'three'
import type { Building } from '../types'
import { BuildingShell, buildingHeightFt } from './scene-building'
import { GOOGLE_TILES_ASSET_ID, METERS_PER_FOOT, assessSite, emptySite, ionToken, planToLocal, samplePlan, siteFootprint, type Sample, type SiteReport } from './site-geometry'

// Google's photorealistic tiles arrive Draco compressed; the decoder is served from public/.
const draco = new DRACOLoader().setDecoderPath('draco/')
const verdictColor: Record<string, string> = { buildable: '#4c8b5a', caution: '#b8873a', blocked: '#a9503f', unknown: '#78838b' }

type Props = { building: Building; report: SiteReport | null; onReport: (report: SiteReport | null) => void }

export function SiteView({ building, report, onReport }: Props) {
  const site = building.site ?? emptySite
  const lat = site.lat, lon = site.lon
  if (!ionToken) return <div className="editor-scene-error"><strong>Add a Cesium ion token to see the site.</strong><p>Put a free Community token in <code>VITE_CESIUM_ION_TOKEN</code> in your <code>.env</code> and restart the dev server. It needs the assets:read and geocode scopes.</p></div>
  if (lat === null || lon === null) return <div className="editor-scene-error"><strong>No location chosen yet.</strong><p>Open the Site tab in the Library panel below, then search for an address or click the map to stand this building somewhere real.</p></div>
  return <Canvas
    dpr={[1, 1.5]}
    frameloop="always"
    camera={{ position: [70, 55, 70], fov: 45, near: 1, far: 80000 }}
    gl={{ antialias: true, logarithmicDepthBuffer: true, toneMapping: THREE.ACESFilmicToneMapping, toneMappingExposure: 1 }}
  >
    <color attach="background" args={['#9eb4c4']} />
    <SiteScene building={building} lat={lat} lon={lon} report={report} onReport={onReport} />
  </Canvas>
}

function SiteScene({ building, lat, lon, report, onReport }: Props & { lat: number; lon: number }) {
  const site = building.site ?? emptySite
  const latRad = lat * Math.PI / 180, lonRad = lon * Math.PI / 180
  const azimuth = site.rotation_deg * Math.PI / 180
  const footprint = useMemo(() => siteFootprint(building), [building])
  const [grade, setGrade] = useState(0)
  const span = Math.max(footprint.width, footprint.height, buildingHeightFt(building)) * METERS_PER_FOOT
  const height = grade + site.ground_offset_ft * METERS_PER_FOOT
  return <>
    <hemisphereLight args={['#e8eef4', '#8a8070', .85]} />
    <directionalLight position={[40, 70, 25]} intensity={1.35} castShadow shadow-mapSize={[2048, 2048]} />
    <ambientLight intensity={.28} />
    <TilesRenderer key={`${lat},${lon}`} errorTarget={6}>
      <TilesPlugin plugin={CesiumIonAuthPlugin} args={{ apiToken: ionToken, assetId: String(GOOGLE_TILES_ASSET_ID), autoRefreshToken: true }} />
      <TilesPlugin plugin={GLTFExtensionsPlugin} args={{ dracoLoader: draco }} />
      <TilesPlugin plugin={ReorientationPlugin} args={{ lat: latRad, lon: lonRad, height: 0 }} />
      <TilesPlugin plugin={TileCompressionPlugin} />
      <TilesPlugin plugin={UnloadTilesPlugin} />
      <TilesPlugin plugin={TilesFadePlugin} />
      <GroundProbe building={building} rotation={site.rotation_deg} onGrade={setGrade} onReport={onReport} />
      <EastNorthUpFrame lat={latRad} lon={lonRad} height={height} az={azimuth}>
        {/* +90° about x stands the y-up building upright in the z-up east-north-up frame. */}
        <group userData={{ siteBuilding: true }} rotation={[Math.PI / 2, 0, 0]} scale={METERS_PER_FOOT}>
          <SitePad footprint={footprint} report={report} />
          <group position={[-footprint.cx, 0, -footprint.cy]}>
            <Suspense fallback={null}><BuildingShell building={building} onSelect={() => undefined} /></Suspense>
          </group>
        </group>
      </EastNorthUpFrame>
      <TilesAttributionOverlay />
    </TilesRenderer>
    <FrameCamera span={span} height={height} />
    <OrbitControls makeDefault target={[0, height + 2, 0]} minDistance={span * .45 + 8} maxDistance={6000} maxPolarAngle={Math.PI * .495} enableDamping dampingFactor={.09} />
  </>
}

/**
 * Drops rays through the footprint onto the loaded mesh. Google tiles keep refining, so
 * this measures as soon as any ground is in view and retries if the first pass misses.
 */
function GroundProbe({ building, rotation, onGrade, onReport }: { building: Building; rotation: number; onGrade: (v: number) => void; onReport: Props['onReport'] }) {
  const tiles = useContext(TilesRendererContext)
  const invalidate = useThree(state => state.invalidate)
  const nextTry = useRef(0)
  const attempts = useRef(0)
  const points = useMemo(() => samplePlan(building, 5), [building.vertices, building.floors])
  const centre = useMemo(() => { const box = siteFootprint(building); return { x: box.cx, y: box.cy } }, [building.vertices])
  useEffect(() => {
    nextTry.current = 0
    attempts.current = 0
    onReport(null)
  }, [rotation, points, onReport])
  useFrame(({ clock }) => {
    if (!tiles?.group || attempts.current >= 8 || clock.elapsedTime < nextTry.current) return
    if (!tiles.root) { nextTry.current = clock.elapsedTime + .4; return }
    const raycaster = new THREE.Raycaster()
    raycaster.far = 80000
    const down = new THREE.Vector3(0, -1, 0)
    const samples: Sample[] = []
    for (const point of points) {
      const { east, north } = planToLocal(point, centre, rotation)
      // After ReorientationPlugin the local frame is +x west, +y up, +z north.
      raycaster.set(new THREE.Vector3(-east, 25000, north), down)
      const hit = raycaster.intersectObject(tiles.group, true).find(item => {
        let node: THREE.Object3D | null = item.object
        while (node) { if (node.userData.siteBuilding) return false; node = node.parent }
        return true
      })
      if (hit) samples.push({ east, north, up: hit.point.y })
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

/** Keep the orbit target on the pad. Terrain sits tens of metres above the ellipsoid, so a one-shot camera pose is wrong. */
function FrameCamera({ span, height }: { span: number; height: number }) {
  const camera = useThree(state => state.camera)
  const controls = useThree(state => state.controls) as { target: THREE.Vector3; update: () => void } | null
  const framed = useRef<string | null>(null)
  useEffect(() => {
    const key = `${Math.round(height * 4)}:${Math.round(span)}`
    if (framed.current === key) return
    framed.current = key
    const dist = Math.max(span * 2.6, 32)
    const target = new THREE.Vector3(0, height + Math.min(span * .2, 4), 0)
    camera.position.set(dist * 0.9, height + dist * 0.55, dist)
    camera.lookAt(target)
    if (controls) { controls.target.copy(target); controls.update() }
  }, [camera, controls, span, height])
  return null
}

function SitePad({ footprint, report }: { footprint: ReturnType<typeof siteFootprint>; report: SiteReport | null }) {
  return <mesh position={[0, .35, 0]} rotation={[-Math.PI / 2, 0, 0]}>
    <planeGeometry args={[footprint.width, footprint.height]} />
    <meshBasicMaterial color={verdictColor[report?.verdict || 'unknown']} transparent opacity={.2} depthWrite={false} side={THREE.DoubleSide} />
  </mesh>
}

export default SiteView
