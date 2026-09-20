import { Component, Suspense, useEffect, useMemo, useRef, useState, type ReactNode, type RefObject } from 'react'
import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { OrbitControls, TransformControls, GizmoHelper, GizmoViewcube, useGLTF } from '@react-three/drei'
import * as THREE from 'three'
import { Footprints, Orbit, RotateCw, Maximize, LoaderCircle, X, Sparkles } from 'lucide-react'
import type { Building } from '../types'
import { assetMime, floorBounds, furniture, interiorPoint, placementCommand, pointInPolygon, projectPoint, type Asset, type EditorProps, type Point } from './editor-geometry'
import './editor-view.css'
import { Daylight, Landscape, FloorSlab } from './scene-landscape'
import { BuildingShell, RoomFloor, Walls3D, buildingHeightFt, groundElevationOf, topFloorOf } from './scene-building'
import { ExteriorSplat } from './scene-splat'
import { SiteView } from './SiteView'
import { emptySite, type SiteReport } from './site-geometry'
import { api, base, waitJob } from '../api'
import { captureGuide } from './appearance-capture'
import { AppearanceContext, useAppearance, type AppearancePalette } from './appearance-context'

type CameraAction = { kind: 'fit' | 'rotate' | 'teleport'; point?: Point; nonce: number }
type Hit = { id: string; point: Point; kind: string } | null
type View = 'exterior' | 'cutaway' | 'site'
type CamSnap = { pos: [number, number, number]; target: [number, number, number] } | null
export type PaintFn = (prompt?: string) => Promise<void>

function noticeText(error: unknown) {
  if (error instanceof Error && error.message) return error.message
  return 'Photoreal materials could not be applied.'
}

function paletteFrom(meta: unknown) {
  const palette = meta && typeof meta === 'object' ? (meta as { palette?: AppearancePalette }).palette : null
  return palette && typeof palette.primary === 'string' ? palette : null
}

function emptyLook() {
  return { map: null as THREE.Texture | null, roofMap: null as THREE.Texture | null, matrix: null as THREE.Matrix4 | null, palette: null as AppearancePalette | null, splatUrl: null as string | null }
}

function disposeLook(current: { map: THREE.Texture | null; roofMap: THREE.Texture | null }) {
  current.map?.dispose()
  current.roofMap?.dispose()
}

function splatFrom(meta: unknown, projectId: string) {
  const name = meta && typeof meta === 'object' ? (meta as { splat?: string }).splat : null
  if (typeof name !== 'string' || !/\.(splat|ply|spz)$/i.test(name)) return null
  return `${base}/projects/${projectId}/files/${name}?t=${Date.now()}`
}

export function ModelView(props: EditorProps & { registerPaint?: (fn: PaintFn | null) => void; visible?: boolean }) {
  const { building, floorId, onCommand, onSelect, selectedId, busy, projectId, registerPaint } = props
  const host = useRef<HTMLDivElement>(null)
  const cameraStore = useRef<CamSnap>(null)
  const [walking, setWalking] = useState(false)
  const [view, setView] = useState<View>('exterior')
  const [currentRoom, setCurrentRoom] = useState<string | null>(null)
  const [cameraPoint, setCameraPoint] = useState<Point | null>(null)
  const [action, setAction] = useState<CameraAction>({ kind: 'fit', nonce: 0 })
  const [dragAsset, setDragAsset] = useState<Asset | null>(null)
  const [dragTarget, setDragTarget] = useState<string | null>(null)
  const [notice, setNotice] = useState('')
  const [objectTool, setObjectTool] = useState<'translate' | 'rotate'>('translate')
  const [spacePanning, setSpacePanning] = useState(false)
  const [painting, setPainting] = useState(false)
  const [report, setReport] = useState<SiteReport | null>(null)
  const [look, setLook] = useState(emptyLook)
  const grab = useRef<(() => ReturnType<typeof captureGuide>) | null>(null)
  const raycast = useRef<(x: number, y: number) => Hit>(() => null)
  const rooms = building.rooms.filter(r => r.floor_id === floorId)
  const bounds = useMemo(() => floorBounds(building, floorId), [building, floorId])
  const site = building.site ?? emptySite
  const sited = site.lat != null && site.lon != null
  const onSite = view === 'site'
  const exterior = view === 'exterior'
  useEffect(() => { setAction({ kind: 'fit', nonce: Date.now() }); setWalking(false); setCurrentRoom(null) }, [floorId])
  useEffect(() => { if (!sited && onSite) setView('exterior') }, [sited, onSite])
  // The Site tab in the library panel shows the buildability readout measured here.
  useEffect(() => { window.dispatchEvent(new CustomEvent('archetype:site-report', { detail: onSite ? report : null })) }, [report, onSite])
  useEffect(() => {
    const listener = (event: Event) => { setDragAsset((event as CustomEvent<Asset | null>).detail); setDragTarget(null) }
    const show = () => setView(current => (current === 'site' ? current : 'site'))
    window.addEventListener('archetype:asset-drag', listener)
    window.addEventListener('archetype:show-site', show)
    return () => { window.removeEventListener('archetype:asset-drag', listener); window.removeEventListener('archetype:show-site', show) }
  }, [])
  useEffect(() => { if (!notice || painting) return; const t = setTimeout(() => setNotice(''), 4000); return () => clearTimeout(t) }, [notice, painting])
  useEffect(() => {
    const isActive = () => !!host.current?.contains(document.activeElement)
    const down = (event: KeyboardEvent) => { if (event.code === 'Space' && isActive() && !walking) { event.preventDefault(); setSpacePanning(true) } }
    const up = (event: KeyboardEvent) => { if (event.code === 'Space') setSpacePanning(false) }
    const release = () => setSpacePanning(false)
    window.addEventListener('keydown', down); window.addEventListener('keyup', up); window.addEventListener('blur', release)
    return () => { window.removeEventListener('keydown', down); window.removeEventListener('keyup', up); window.removeEventListener('blur', release) }
  }, [walking])
  useEffect(() => {
    if (!projectId) return
    let cancelled = false
    fetch(`${base}/projects/${projectId}/files/appearance.json`).then(r => r.ok ? r.json() : null).then(meta => {
      if (cancelled || !meta) return
      setLook(current => {
        disposeLook(current)
        return { map: null, roofMap: null, matrix: null, palette: paletteFrom(meta), splatUrl: splatFrom(meta, projectId) }
      })
    }).catch(() => undefined)
    return () => { cancelled = true }
  }, [projectId])
  async function paint(prompt?: string) {
    if (!projectId || painting) return
    for (let i = 0; i < 40 && !grab.current; i++) await new Promise(r => setTimeout(r, 50))
    if (!grab.current) { setNotice('The 3D view is still starting.'); return }
    setPainting(true); setNotice('Capturing an isometric guide…')
    try {
      const guide = grab.current()
      const { job_id } = await api(`/projects/${projectId}/appearance`, prompt ? { image: guide.image, projector: guide.projector, prompt } : { image: guide.image, projector: guide.projector })
      await waitJob(job_id, job => { if (job.message) setNotice(job.message) })
      const meta = await fetch(`${base}/projects/${projectId}/files/appearance.json`).then(r => r.ok ? r.json() : null).catch(() => null)
      const splatUrl = splatFrom(meta, projectId)
      if (!splatUrl) throw new Error('TripoSplat did not return a Gaussian splat. Check the splat endpoint in .env.')
      setLook(current => { disposeLook(current); return { map: null, roofMap: null, matrix: null, palette: paletteFrom(meta), splatUrl } })
      setNotice('TripoSplat Gaussian applied to the exterior.')
    } catch (error) {
      setNotice(noticeText(error))
    } finally { setPainting(false) }
  }
  const latestPaint = useRef<PaintFn>(paint)
  latestPaint.current = paint
  useEffect(() => { registerPaint?.(prompt => latestPaint.current(prompt)); return () => registerPaint?.(null) }, [registerPaint])
  return <div ref={host} tabIndex={0} className={`editor-modelview ${dragAsset ? 'asset-dragging' : ''}${spacePanning ? ' space-panning' : ''}`} aria-label="3D model editor" onPointerDown={() => host.current?.focus()} onDragOver={event => { event.preventDefault(); const hit = raycast.current(event.clientX, event.clientY); setDragTarget(hit?.id || null) }} onDragLeave={event => { if (!host.current?.contains(event.relatedTarget as Node)) setDragTarget(null) }} onDrop={event => {
    event.preventDefault()
    try {
      const data = event.dataTransfer.getData(assetMime)
      if (!data) return
      const asset = JSON.parse(data) as Asset, hit = raycast.current(event.clientX, event.clientY)
      if (!hit) { setNotice(onSite ? 'Switch to Exterior or Floor cutaway to place assets.' : 'Drop onto the floor or a wall.'); return }
      if (asset.kind === 'material') {
        if (hit.kind === 'wall' || hit.kind === 'room') onCommand([{ kind: 'set_material', target_id: hit.id, params: { material: asset.id } }])
        else setNotice('A finish can be applied to a wall or room floor.')
      } else { const command = placementCommand(asset, hit.point, building, floorId); if (command) onCommand([command]) }
    } catch { setNotice('This asset could not be placed.') }
    finally { setDragAsset(null); setDragTarget(null); window.dispatchEvent(new CustomEvent('archetype:asset-drag', { detail: null })) }
  }}>
    <SceneBoundary>{props.visible === false ? null : onSite
      ? <SiteView building={building} report={report} onReport={setReport} />
      : <AppearanceContext.Provider value={{ ...look, apply: exterior && !walking }}><Canvas frameloop="demand" shadows dpr={[1, 1.5]} camera={{ position: [bounds.cx + 30, 38, bounds.cy + 40], fov: 42, near: .2, far: 8000 }} gl={{ antialias: true, toneMapping: THREE.ACESFilmicToneMapping, toneMappingExposure: 1.05, preserveDrawingBuffer: true }} onCreated={({ gl }) => { gl.shadowMap.type = THREE.PCFShadowMap }} onPointerMissed={() => onSelect(null)}>
        <Scene {...props} exterior={exterior && !walking} walking={walking} spacePanning={spacePanning} objectTool={objectTool} action={action} dragTarget={dragTarget} raycast={raycast} grab={grab} setRoom={(id, point) => { setCurrentRoom(id); setCameraPoint(point) }} cameraStore={cameraStore} />
      </Canvas></AppearanceContext.Provider>}</SceneBoundary>
    {!onSite && <div className="editor-floating-tools editor-model-tools" role="toolbar" aria-label="3D navigation">
      <button className={!walking ? 'active' : ''} aria-label="Orbit view" title="Orbit view" onClick={() => setWalking(false)}><Orbit size={17} /></button>
      <button className={walking ? 'active' : ''} aria-label="Walk through the building" title="Walk through" onClick={() => { setWalking(true); const room = rooms.find(r => r.id === currentRoom) || rooms[0]; if (room) setAction({ kind: 'teleport', point: interiorPoint(room.polygon), nonce: Date.now() }) }}><Footprints size={17} /></button>
      <span className="editor-tool-divider" /><button title="Rotate view 45°" aria-label="Rotate view 45 degrees" onClick={() => setAction({ kind: 'rotate', nonce: Date.now() })}><RotateCw size={17} /></button><button title="Fit model" aria-label="Fit model" onClick={() => { setWalking(false); setAction({ kind: 'fit', nonce: Date.now() }) }}><Maximize size={16} /></button>
      <span className="editor-tool-divider" /><button className={look.splatUrl ? 'active' : ''} title="Build a TripoSplat Gaussian of the exterior" aria-label="Build a TripoSplat Gaussian of the exterior" disabled={painting || !projectId} onClick={() => { void paint() }}>{painting ? <LoaderCircle size={17} className="editor-spin" /> : <Sparkles size={17} />}</button>
    </div>}
    <div className="editor-scene-modes" role="group" aria-label="Building presentation">
      <button aria-pressed={exterior && !walking} onClick={() => { setView('exterior'); setWalking(false); setAction({ kind: 'fit', nonce: Date.now() }) }}>Exterior</button>
      <button aria-pressed={view === 'cutaway' || walking} onClick={() => { setView('cutaway'); setWalking(false); setAction({ kind: 'fit', nonce: Date.now() }) }}>Floor cutaway</button>
      <button aria-pressed={onSite} disabled={!sited} title={sited ? 'Stand the building on Google’s 3D map' : 'Choose a location in the Site tab of the Library panel first'} onClick={() => { setView('site'); setWalking(false) }}>On site</button>
    </div>
    <div className="editor-model-label"><span className="editor-live-dot" />{onSite ? `${site.address || 'Chosen site'} · Google Photorealistic 3D Tiles` : exterior && !walking ? 'Whole building · Concept roof & landscape' : `${building.floors.find(f => f.id === floorId)?.name} · ${walking ? 'Walkthrough' : 'Floor cutaway'}`}</div>
    {selectedId && !walking && !onSite && <div className="editor-model-selection">{building.walls.some(w => w.id === selectedId) ? 'Wall selected' : building.rooms.find(r => r.id === selectedId)?.name || 'Object selected'}{building.objects.some(o => o.id === selectedId) && <><button className={objectTool === 'translate' ? 'active' : ''} onClick={() => setObjectTool('translate')}>Move</button><button className={objectTool === 'rotate' ? 'active' : ''} onClick={() => setObjectTool('rotate')}>Rotate</button></>}<button aria-label="Clear selection" onClick={() => onSelect(null)}><X size={12} /></button></div>}
    {onSite && <SiteBadge report={report} building={building} />}
    {painting && <div className="editor-updating" role="status"><LoaderCircle size={13} className="editor-spin" />Building a TripoSplat Gaussian of the exterior</div>}
    {busy && !painting && <div className="editor-updating" role="status"><LoaderCircle size={13} className="editor-spin" />Updating design · showing saved model</div>}
    {notice && <div className="editor-notice" role="status">{notice}</div>}
    <div className="editor-canvas-hint">{onSite ? 'Drag to orbit the site · Scroll to zoom · Imagery © Google' : walking ? 'Click the model to look around · W A S D to walk · Esc releases the pointer' : spacePanning ? 'Drag to pan · Release Space to orbit' : 'Drag to orbit · Hold Space to pan · Scroll to zoom'}</div>
    {rooms.length > 0 && !onSite && (!exterior || walking) && <div className="editor-minimap"><div>{currentRoom ? rooms.find(r => r.id === currentRoom)?.name : 'Floor overview'}<span>Click a room to enter</span></div><svg viewBox={`${bounds.minX - 1} ${bounds.minY - 1} ${bounds.width + 2} ${bounds.height + 2}`} role="group" aria-label="Floor minimap">
      {rooms.map(room => <polygon key={room.id} tabIndex={0} role="button" aria-label={`Enter ${room.name}`} points={room.polygon.map(p => p.join(',')).join(' ')} fill={room.id === currentRoom ? '#7d939f' : '#b9bdbe'} fillOpacity={room.id === currentRoom ? .75 : .4} stroke="#657077" strokeWidth={.12} onClick={() => { setWalking(true); setAction({ kind: 'teleport', point: interiorPoint(room.polygon), nonce: Date.now() }) }} onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { setWalking(true); setAction({ kind: 'teleport', point: interiorPoint(room.polygon), nonce: Date.now() }) } }} />)}
      {building.walls.filter(w => w.floor_id === floorId).map(w => { const a = building.vertices.find(v => v.id === w.start_id), b = building.vertices.find(v => v.id === w.end_id); return a && b ? <line key={w.id} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="#4b5459" strokeWidth={Math.max(w.thickness_ft, .12)} pointerEvents="none" /> : null })}
      {cameraPoint && <circle cx={cameraPoint.x} cy={cameraPoint.y} r={Math.max(.25, bounds.width / 75)} fill="#2e647d" stroke="white" strokeWidth={.16} pointerEvents="none" />}
    </svg></div>}
  </div>
}

function SiteBadge({ report, building }: { report: SiteReport | null; building: Building }) {
  const height = buildingHeightFt(building)
  if (!report) return <div className="editor-updating" role="status"><LoaderCircle size={13} className="editor-spin" />Streaming the site and measuring the ground</div>
  return <div className={`editor-site-badge ${report.verdict}`} role="status">
    <strong>{report.verdict === 'buildable' ? 'Buildable' : report.verdict === 'caution' ? 'Check this site' : report.verdict === 'blocked' ? 'Not buildable' : 'Not measured'}</strong>
    <span>{report.tiltDeg.toFixed(1)}° tilt · {report.roughnessM.toFixed(2)} m rough · {report.spreadM.toFixed(1)} m range</span>
    <small>{Math.round(height)} ft tall on this pad</small>
  </div>
}

function Scene({ building, floorId, onSelect, onCommand, selectedId, exterior, walking, spacePanning, objectTool, action, dragTarget, raycast, grab, setRoom, cameraStore }: EditorProps & { exterior: boolean; walking: boolean; spacePanning: boolean; objectTool: 'translate' | 'rotate'; action: CameraAction; dragTarget: string | null; raycast: RefObject<(x: number, y: number) => Hit>; grab: RefObject<(() => ReturnType<typeof captureGuide>) | null>; setRoom: (id: string | null, p: Point) => void; cameraStore: RefObject<CamSnap> }) {
  const look = useAppearance()
  const bounds = useMemo(() => floorBounds(exterior ? { ...building, vertices: building.vertices.map(v => ({ ...v, floor_id: floorId })) } : building, floorId), [building, floorId, exterior])
  const walls = building.walls.filter(w => w.floor_id === floorId), rooms = building.rooms.filter(r => r.floor_id === floorId)
  const objects = building.objects.filter(o => o.floor_id === floorId)
  const vertices = useMemo(() => new Map(building.vertices.map(v => [v.id, v])), [building.vertices])
  const controls = useRef<any>(null)
  const { camera, gl, scene, invalidate } = useThree()
  const keys = useRef(new Set<string>())
  const lastRoom = useRef(0)
  const groundElevation = groundElevationOf(building)
  const topFloor = topFloorOf(building)
  // Save camera state into the parent ref when this Canvas unmounts so it
  // can be restored when the 3D panel becomes visible again.
  useEffect(() => () => {
    const tgt = controls.current?.target
    cameraStore.current = { pos: [camera.position.x, camera.position.y, camera.position.z], target: tgt ? [tgt.x, tgt.y, tgt.z] : [bounds.cx, 0, bounds.cy] }
  }, [camera, bounds.cx, bounds.cy, cameraStore])
  useEffect(() => {
    grab.current = () => {
      const height = (topFloor?.elevation_ft || 0) + (topFloor?.height_ft || 9) - groundElevation
      return captureGuide(gl, scene, bounds, height)
    }
    return () => { grab.current = null }
  }, [gl, scene, bounds, topFloor?.elevation_ft, topFloor?.height_ft, groundElevation, grab])
  useEffect(() => {
    const orbit = controls.current
    if (!orbit) return
    orbit.mouseButtons.LEFT = spacePanning ? THREE.MOUSE.PAN : THREE.MOUSE.ROTATE
    return () => { orbit.mouseButtons.LEFT = THREE.MOUSE.ROTATE }
  }, [spacePanning])
  useEffect(() => {
    raycast.current = (clientX, clientY) => {
      if (exterior) return null
      const rect = gl.domElement.getBoundingClientRect(), pointer = new THREE.Vector2((clientX - rect.left) / rect.width * 2 - 1, -(clientY - rect.top) / rect.height * 2 + 1)
      const ray = new THREE.Raycaster(); ray.setFromCamera(pointer, camera)
      const hits = ray.intersectObjects(scene.children, true)
      for (const hit of hits) {
        if (hit.object.userData.kind === 'wall-instances' && hit.instanceId != null) {
          const id = (hit.object.userData.instanceIds as string[] | undefined)?.[hit.instanceId]
          if (id) return { id, kind: 'wall', point: { x: hit.point.x, y: hit.point.z } }
        }
        let object: THREE.Object3D | null = hit.object; while (object && !object.userData.entityId) object = object.parent; if (object?.userData.entityId) return { id: object.userData.entityId, kind: object.userData.kind, point: { x: hit.point.x, y: hit.point.z } }
      }
      const point = ray.ray.intersectPlane(new THREE.Plane(new THREE.Vector3(0, 1, 0), 0), new THREE.Vector3())
      return point && point.x >= bounds.minX - 2 && point.x <= bounds.maxX + 2 && point.z >= bounds.minY - 2 && point.z <= bounds.maxY + 2 ? { id: '', kind: 'ground', point: { x: point.x, y: point.z } } : null
    }
  }, [camera, gl, scene, raycast, bounds, exterior])
  useEffect(() => {
    // On remount after a tab switch, restore the camera the user had.
    const saved = cameraStore.current
    if (saved) {
      camera.position.set(saved.pos[0], saved.pos[1], saved.pos[2])
      controls.current?.target.set(saved.target[0], saved.target[1], saved.target[2])
      cameraStore.current = null
    } else if (action.kind === 'fit') {
      const height = exterior ? (topFloor?.elevation_ft || 0) + (topFloor?.height_ft || 9) - groundElevation : 9
      const distance = Math.max(bounds.width, bounds.height, height * 2, 20) * (exterior ? 1.55 : 1)
      const targetY = exterior ? height * .35 : 1
      camera.position.set(bounds.cx + distance * .85, targetY + distance * .65, bounds.cy - distance * 1.25)
      controls.current?.target.set(bounds.cx, targetY, bounds.cy)
      camera.lookAt(bounds.cx, targetY, bounds.cy)
    } else if (action.kind === 'rotate') {
      if (walking) { camera.rotation.order = 'YXZ'; camera.rotation.y -= Math.PI / 4 }
      else { const center = controls.current?.target || new THREE.Vector3(bounds.cx, 0, bounds.cy); const delta = camera.position.clone().sub(center).applyAxisAngle(new THREE.Vector3(0, 1, 0), Math.PI / 4); camera.position.copy(center).add(delta); camera.lookAt(center) }
    } else if (action.point) {
      camera.position.set(action.point.x, 5.3, action.point.y)
      camera.rotation.order = 'YXZ'; camera.rotation.set(0, Math.PI, 0)
      controls.current?.target.set(action.point.x, 5.3, action.point.y + 4)
    }
    controls.current?.update()
    invalidate()
  }, [action, bounds, camera, exterior, topFloor?.elevation_ft, topFloor?.height_ft, groundElevation, invalidate, cameraStore])
  useEffect(() => {
    if (!walking && document.pointerLockElement === gl.domElement) document.exitPointerLock()
    keys.current.clear()
    const down = (e: KeyboardEvent) => { if (!walking || ['INPUT', 'TEXTAREA', 'SELECT'].includes((e.target as HTMLElement)?.tagName)) return; if (['w', 'a', 's', 'd', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].includes(e.key)) { keys.current.add(e.key.toLowerCase()); e.preventDefault() } }
    const up = (e: KeyboardEvent) => keys.current.delete(e.key.toLowerCase())
    const blur = () => keys.current.clear()
    const look = (e: MouseEvent) => { if (walking && document.pointerLockElement === gl.domElement) { camera.rotation.order = 'YXZ'; camera.rotation.y -= e.movementX * .002; camera.rotation.x = THREE.MathUtils.clamp(camera.rotation.x - e.movementY * .002, -Math.PI * .46, Math.PI * .46); invalidate() } }
    const capture = () => { if (walking) gl.domElement.requestPointerLock()?.catch(() => undefined) }
    window.addEventListener('keydown', down); window.addEventListener('keyup', up); window.addEventListener('blur', blur); document.addEventListener('mousemove', look); gl.domElement.addEventListener('click', capture)
    return () => { window.removeEventListener('keydown', down); window.removeEventListener('keyup', up); window.removeEventListener('blur', blur); document.removeEventListener('mousemove', look); gl.domElement.removeEventListener('click', capture) }
  }, [walking, camera, gl])
  function collides(p: Point) {
    if (p.x < bounds.minX || p.x > bounds.maxX || p.y < bounds.minY || p.y > bounds.maxY) return true
    for (const wall of walls) {
      const a = vertices.get(wall.start_id), b = vertices.get(wall.end_id)
      if (!a || !b) continue
      const hit = projectPoint(p, a, b)
      if (hit.distance > wall.thickness_ft / 2 + .65) continue
      const portal = building.openings.some(o => o.wall_id === wall.id && o.kind === 'door' && o.height_ft >= 5.5 && hit.offset >= o.offset_ft + .55 && hit.offset <= o.offset_ft + o.width_ft - .55)
      if (!portal) return true
    }
    for (const o of objects) {
      if (o.height_ft < .5) continue
      const angle = -o.rotation_deg * Math.PI / 180, dx = p.x - o.x, dy = p.y - o.y
      const x = dx * Math.cos(angle) - dy * Math.sin(angle), y = dx * Math.sin(angle) + dy * Math.cos(angle)
      if (Math.abs(x) < o.width_ft / 2 + .35 && Math.abs(y) < o.depth_ft / 2 + .35) return true
    }
    return false
  }
  useFrame(({ clock }, delta) => {
    if (walking) {
      const k = keys.current, forward = Number(k.has('w') || k.has('arrowup')) - Number(k.has('s') || k.has('arrowdown')), lateral = Number(k.has('d') || k.has('arrowright')) - Number(k.has('a') || k.has('arrowleft'))
      if (forward || lateral) {
        const direction = new THREE.Vector3(); camera.getWorldDirection(direction); direction.y = 0; direction.normalize()
        const right = new THREE.Vector3(-direction.z, 0, direction.x), move = direction.multiplyScalar(forward).addScaledVector(right, lateral).normalize().multiplyScalar(Math.min(delta, .06) * 8)
        // Substeps prevent crossing a thin partition during a slow frame.
        const steps = Math.max(1, Math.ceil(move.length() / .15))
        for (let i = 0; i < steps; i++) {
          if (!collides({ x: camera.position.x + move.x / steps, y: camera.position.z })) camera.position.x += move.x / steps
          if (!collides({ x: camera.position.x, y: camera.position.z + move.z / steps })) camera.position.z += move.z / steps
        }
        camera.position.y = 5.3
        invalidate() // keep the WASD movement loop alive under frameloop="demand"
      }
    }
    if (clock.elapsedTime - lastRoom.current > .3) {
      const target = walking ? camera.position : controls.current?.target || camera.position
      const point = { x: target.x, y: target.z }, room = rooms.find(r => pointInPolygon(point, r.polygon))
      setRoom(room?.id || null, point); lastRoom.current = clock.elapsedTime
    }
  })
  const hideShell = exterior && !!look.splatUrl
  const roofHeight = buildingHeightFt(building)
  return <>
    <Daylight bounds={bounds} environment={building.environment} />
    <Suspense fallback={null}>
      <Landscape bounds={bounds} />
      {hideShell && look.splatUrl && <ExteriorSplat url={look.splatUrl} bounds={bounds} height={roofHeight} />}
      {exterior
        ? <BuildingShell building={building} hideShell={hideShell} selectedId={selectedId} dragTarget={dragTarget} onSelect={onSelect} />
        : <group>
          {rooms.map(room => <group key={room.id}><FloorSlab polygon={room.polygon} y={-.32} thickness={.32} /><RoomFloor room={room} faded={dragTarget === room.id} selected={selectedId === room.id} onSelect={onSelect} /></group>)}
          <Walls3D walls={walls} vertices={vertices} openings={building.openings} selectedId={selectedId} dragTarget={dragTarget} onSelect={onSelect} photoreal={false} />
          {objects.map(object => <PlacedEntity key={object.id} object={object} selected={selectedId === object.id} walking={walking} tool={objectTool} onSelect={onSelect} onCommand={onCommand} />)}
        </group>}
    </Suspense>
    {!walking && <OrbitControls ref={controls} makeDefault minDistance={3} maxDistance={Math.max(bounds.width, bounds.height) * 8} maxPolarAngle={Math.PI * .485} enablePan enableDamping dampingFactor={.09} />}
    {!walking && <group userData={{ captureHide: true }}><GizmoHelper alignment="top-right" margin={[58, 65]}><GizmoViewcube color="#eeefef" hoverColor="#c8d6df" textColor="#64727b" strokeColor="#e0e1e1" opacity={.8} /></GizmoHelper></group>}
  </>
}

function PlacedEntity({ object, selected, walking, tool, onSelect, onCommand }: { object: Building['objects'][number]; selected: boolean; walking: boolean; tool: 'translate' | 'rotate'; onSelect: EditorProps['onSelect']; onCommand: EditorProps['onCommand'] }) {
  const ref = useRef<THREE.Group>(null)
  const node = <group ref={ref} position={[object.x, .02, object.y]} rotation={[0, -object.rotation_deg * Math.PI / 180, 0]} userData={{ entityId: object.id, kind: 'object' }} onClick={e => { e.stopPropagation(); onSelect(object.id) }}>
    {object.kind === 'furniture' && furniture.some(a => a.id === object.asset_id) ? <Suspense fallback={<LoadingObject object={object} />}><FurnitureModel object={object} selected={selected} /></Suspense> : <FixtureModel object={object} selected={selected} />}
  </group>
  return selected && !walking ? <TransformControls mode={tool} showX={tool === 'translate'} showY={tool === 'rotate'} showZ={tool === 'translate'} size={.7} translationSnap={.25} rotationSnap={Math.PI / 12} onMouseUp={() => { const node = ref.current; if (!node) return; const rotation = -node.rotation.y * 180 / Math.PI; if (Math.abs(node.position.x - object.x) + Math.abs(node.position.z - object.y) + Math.abs(rotation - object.rotation_deg) < .001) return; onCommand([{ kind: 'update_object', target_id: object.id, params: { x: node.position.x, y: node.position.z, rotation_deg: rotation } }]) }}>{node}</TransformControls> : node
}

function FurnitureModel({ object, selected }: { object: Building['objects'][number]; selected: boolean }) {
  const source = furniture.find(a => a.id === object.asset_id)!
  const { scene } = useGLTF(source.model!, false, false)
  const look = useAppearance()
  const { clone, size, center, minY } = useMemo(() => {
    const clone = scene.clone(true), box = new THREE.Box3().setFromObject(clone), size = box.getSize(new THREE.Vector3()), center = box.getCenter(new THREE.Vector3())
    const accent = look.palette?.accent
    clone.traverse(node => {
      if (!(node instanceof THREE.Mesh)) return
      node.castShadow = node.receiveShadow = true
      const original = node.material
      const material = Array.isArray(original) ? original[0] : original
      if (accent && material && 'color' in material) {
        const next = (material as THREE.MeshStandardMaterial).clone()
        next.color.lerp(new THREE.Color(accent), .28)
        node.material = next
      }
    })
    return { clone, size, center, minY: box.min.y }
  }, [scene, look.palette?.accent])
  return <group scale={[object.width_ft / size.x, object.height_ft / size.y, object.depth_ft / size.z]}><primitive object={clone} position={[-center.x, -minY, -center.z]} />{selected && <mesh position={[0, size.y / 2, 0]}><boxGeometry args={[size.x * 1.02, size.y * 1.02, size.z * 1.02]} /><meshBasicMaterial color="#408cb0" wireframe transparent opacity={.4} /></mesh>}</group>
}

function LoadingObject({ object }: { object: Building['objects'][number] }) {
  return <mesh position={[0, object.height_ft / 2, 0]}><boxGeometry args={[object.width_ft, object.height_ft, object.depth_ft]} /><meshBasicMaterial color="#93a3ad" wireframe transparent opacity={.3} /></mesh>
}

function FixtureModel({ object, selected }: { object: Building['objects'][number]; selected: boolean }) {
  const look = useAppearance()
  const color = selected ? '#c6dce5' : look.palette?.primary || (object.asset_id === 'closet' || object.asset_id === 'counter' ? '#d8c5a7' : '#f8f7f1')
  return <group><mesh position={[0, object.height_ft / 2, 0]} castShadow receiveShadow><boxGeometry args={[object.width_ft, object.height_ft, object.depth_ft]} /><meshStandardMaterial color={color} roughness={.4} /></mesh>{['sink', 'bath', 'toilet', 'shower'].includes(object.asset_id) && <mesh position={[0, object.height_ft + .012, 0]} rotation={[-Math.PI / 2, 0, 0]}><circleGeometry args={[Math.min(object.width_ft, object.depth_ft) * .32, 32]} /><meshStandardMaterial color="#c5cdcc" roughness={.25} /></mesh>}</group>
}

class SceneBoundary extends Component<{ children: ReactNode }, { error: string | null }> {
  state = { error: null as string | null }
  static getDerivedStateFromError(error: Error) { return { error: error.message } }
  render() { return this.state.error ? <div className="editor-scene-error"><strong>The 3D preview could not start.</strong><p>{this.state.error}</p><button onClick={() => this.setState({ error: null })}>Retry preview</button></div> : this.props.children }
}

export default ModelView
