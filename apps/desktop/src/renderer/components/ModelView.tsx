import { Component, Suspense, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode, type RefObject } from 'react'
import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { OrbitControls, TransformControls, GizmoHelper, GizmoViewcube, useGLTF } from '@react-three/drei'
import * as THREE from 'three'
import { Footprints, Orbit, RotateCw, Maximize, LoaderCircle, X, Sparkles } from 'lucide-react'
import type { Building } from '../types'
import { assetMime, floorBounds, furniture, interiorPoint, materials, placementCommand, pointInPolygon, projectPoint, wallExterior, type Asset, type EditorProps, type Point } from './editor-geometry'
import './editor-view.css'
import { SurfaceMaterial } from './scene-materials'
import { Daylight, Landscape, FloorSlab } from './scene-landscape'
import { ExteriorSplat } from './scene-splat'
import { api, base, waitJob } from '../api'
import { captureGuide } from './appearance-capture'
import { AppearanceContext, useAppearance, type AppearancePalette } from './appearance-context'

type Wall = Building['walls'][number]
type CameraAction = { kind: 'fit' | 'rotate' | 'teleport'; point?: Point; nonce: number }
type Hit = { id: string; point: Point; kind: string } | null
const colors = Object.fromEntries(materials.map(m => [m.id, m.color]))

function noticeText(error: unknown) {
  if (error instanceof Error && error.message) return error.message
  return 'Photoreal materials could not be applied.'
}

function paletteFrom(meta: unknown) {
  const palette = meta && typeof meta === 'object' ? (meta as { palette?: AppearancePalette }).palette : null
  return palette && typeof palette.primary === 'string' ? palette : null
}

export function ModelView(props: EditorProps) {
  const { building, floorId, onCommand, onSelect, selectedId, busy, projectId } = props
  const host = useRef<HTMLDivElement>(null)
  const [walking, setWalking] = useState(false)
  const [exterior, setExterior] = useState(true)
  const [currentRoom, setCurrentRoom] = useState<string | null>(null)
  const [cameraPoint, setCameraPoint] = useState<Point | null>(null)
  const [action, setAction] = useState<CameraAction>({ kind: 'fit', nonce: 0 })
  const [dragAsset, setDragAsset] = useState<Asset | null>(null)
  const [dragTarget, setDragTarget] = useState<string | null>(null)
  const [notice, setNotice] = useState('')
  const [objectTool, setObjectTool] = useState<'translate' | 'rotate'>('translate')
  const [spacePanning, setSpacePanning] = useState(false)
  const [painting, setPainting] = useState(false)
  const [look, setLook] = useState<{ map: THREE.Texture | null; matrix: THREE.Matrix4 | null; palette: AppearancePalette | null; splatUrl: string | null }>({ map: null, matrix: null, palette: null, splatUrl: null })
  const grab = useRef<(() => ReturnType<typeof captureGuide>) | null>(null)
  const raycast = useRef<(x: number, y: number) => Hit>(() => null)
  const rooms = building.rooms.filter(r => r.floor_id === floorId)
  const bounds = useMemo(() => floorBounds(building, floorId), [building, floorId])
  useEffect(() => { setAction({ kind: 'fit', nonce: Date.now() }); setWalking(false); setCurrentRoom(null) }, [floorId])
  useEffect(() => {
    const listener = (event: Event) => { setDragAsset((event as CustomEvent<Asset | null>).detail); setDragTarget(null) }
    window.addEventListener('archetype:asset-drag', listener)
    return () => window.removeEventListener('archetype:asset-drag', listener)
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
      const splatName = typeof meta.splat === 'string' && meta.splat.endsWith('.splat') ? meta.splat : null
      setLook(current => {
        current.map?.dispose()
        return { map: null, matrix: null, palette: paletteFrom(meta), splatUrl: splatName ? `${base}/projects/${projectId}/files/${splatName}?t=${Date.now()}` : null }
      })
    }).catch(() => undefined)
    return () => { cancelled = true }
  }, [projectId])
  async function paint() {
    if (!projectId || painting) return
    if (!grab.current) { setNotice('The 3D view is still starting.'); return }
    setPainting(true); setNotice('Capturing an isometric guide…')
    try {
      const guide = grab.current()
      const { job_id } = await api(`/projects/${projectId}/appearance`, { image: guide.image, projector: guide.projector })
      await waitJob(job_id, job => { if (job.message) setNotice(job.message) })
      const meta = await fetch(`${base}/projects/${projectId}/files/appearance.json`).then(r => r.ok ? r.json() : null).catch(() => null)
      const splatName = typeof meta?.splat === 'string' ? meta.splat : null
      const splatUrl = splatName ? `${base}/projects/${projectId}/files/${splatName}?t=${Date.now()}` : null
      setLook(current => { current.map?.dispose(); return { map: null, matrix: null, palette: paletteFrom(meta), splatUrl } })
      setNotice(splatUrl ? 'Exterior cladding and Gaussian splat applied.' : 'Photoreal cladding applied to the exterior.')
    } catch (error) {
      setNotice(noticeText(error))
    } finally { setPainting(false) }
  }
  return <div ref={host} tabIndex={0} className={`editor-modelview ${dragAsset ? 'asset-dragging' : ''}${spacePanning ? ' space-panning' : ''}`} aria-label="3D model editor" onPointerDown={() => host.current?.focus()} onDragOver={event => { event.preventDefault(); const hit = raycast.current(event.clientX, event.clientY); setDragTarget(hit?.id || null) }} onDragLeave={event => { if (!host.current?.contains(event.relatedTarget as Node)) setDragTarget(null) }} onDrop={event => {
    event.preventDefault()
    try {
      const data = event.dataTransfer.getData(assetMime)
      if (!data) return
      const asset = JSON.parse(data) as Asset, hit = raycast.current(event.clientX, event.clientY)
      if (!hit) { setNotice('Drop onto the floor or a wall.'); return }
      if (asset.kind === 'material') {
        if (hit.kind === 'wall' || hit.kind === 'room') onCommand([{ kind: 'set_material', target_id: hit.id, params: { material: asset.id } }])
        else setNotice('A finish can be applied to a wall or room floor.')
      } else { const command = placementCommand(asset, hit.point, building, floorId); if (command) onCommand([command]) }
    } catch { setNotice('This asset could not be placed.') }
    finally { setDragAsset(null); setDragTarget(null); window.dispatchEvent(new CustomEvent('archetype:asset-drag', { detail: null })) }
  }}>
    <SceneBoundary><AppearanceContext.Provider value={{ ...look, apply: exterior && !walking }}><Canvas shadows dpr={[1, 1.5]} camera={{ position: [bounds.cx + 30, 38, bounds.cy + 40], fov: 42, near: .2, far: 8000 }} gl={{ antialias: true, toneMapping: THREE.ACESFilmicToneMapping, toneMappingExposure: .85, preserveDrawingBuffer: true }} onCreated={({ gl }) => { gl.shadowMap.type = THREE.PCFShadowMap }} onPointerMissed={() => onSelect(null)}>
      <color attach="background" args={['#b9d2e4']} />
      <Scene {...props} exterior={exterior && !walking} walking={walking} spacePanning={spacePanning} objectTool={objectTool} action={action} dragTarget={dragTarget} raycast={raycast} grab={grab} setRoom={(id, point) => { setCurrentRoom(id); setCameraPoint(point) }} />
    </Canvas></AppearanceContext.Provider></SceneBoundary>
    <div className="editor-floating-tools editor-model-tools" role="toolbar" aria-label="3D navigation">
      <button className={!walking ? 'active' : ''} aria-label="Orbit view" title="Orbit view" onClick={() => setWalking(false)}><Orbit size={17} /></button>
      <button className={walking ? 'active' : ''} aria-label="Walk through the building" title="Walk through" onClick={() => { setWalking(true); const room = rooms.find(r => r.id === currentRoom) || rooms[0]; if (room) setAction({ kind: 'teleport', point: interiorPoint(room.polygon), nonce: Date.now() }) }}><Footprints size={17} /></button>
      <span className="editor-tool-divider" /><button title="Rotate view 45°" aria-label="Rotate view 45 degrees" onClick={() => setAction({ kind: 'rotate', nonce: Date.now() })}><RotateCw size={17} /></button><button title="Fit model" aria-label="Fit model" onClick={() => { setWalking(false); setAction({ kind: 'fit', nonce: Date.now() }) }}><Maximize size={16} /></button>
      <span className="editor-tool-divider" /><button className={look.palette ? 'active' : ''} title="Paint photoreal materials with Flux" aria-label="Paint photoreal materials" disabled={painting || !projectId} onClick={() => { void paint() }}>{painting ? <LoaderCircle size={17} className="editor-spin" /> : <Sparkles size={17} />}</button>
    </div>
    <div className="editor-scene-modes" role="group" aria-label="Building presentation"><button aria-pressed={exterior && !walking} onClick={() => { setExterior(true); setWalking(false); setAction({ kind: 'fit', nonce: Date.now() }) }}>Exterior</button><button aria-pressed={!exterior || walking} onClick={() => { setExterior(false); setWalking(false); setAction({ kind: 'fit', nonce: Date.now() }) }}>Floor cutaway</button></div>
    <div className="editor-model-label"><span className="editor-live-dot" />{exterior && !walking ? 'Whole building · Concept roof & landscape' : `${building.floors.find(f => f.id === floorId)?.name} · ${walking ? 'Walkthrough' : 'Floor cutaway'}`}</div>
    {selectedId && !walking && <div className="editor-model-selection">{building.walls.some(w => w.id === selectedId) ? 'Wall selected' : building.rooms.find(r => r.id === selectedId)?.name || 'Object selected'}{building.objects.some(o => o.id === selectedId) && <><button className={objectTool === 'translate' ? 'active' : ''} onClick={() => setObjectTool('translate')}>Move</button><button className={objectTool === 'rotate' ? 'active' : ''} onClick={() => setObjectTool('rotate')}>Rotate</button></>}<button aria-label="Clear selection" onClick={() => onSelect(null)}><X size={12} /></button></div>}
    {painting && <div className="editor-updating" role="status"><LoaderCircle size={13} className="editor-spin" />Painting photoreal materials with Flux</div>}
    {busy && !painting && <div className="editor-updating" role="status"><LoaderCircle size={13} className="editor-spin" />Updating design · showing saved model</div>}
    {notice && <div className="editor-notice" role="status">{notice}</div>}
    <div className="editor-canvas-hint">{walking ? 'Click the model to look around · W A S D to walk · Esc releases the pointer' : spacePanning ? 'Drag to pan · Release Space to orbit' : 'Drag to orbit · Hold Space to pan · Scroll to zoom'}</div>
    {rooms.length > 0 && (!exterior || walking) && <div className="editor-minimap"><div>{currentRoom ? rooms.find(r => r.id === currentRoom)?.name : 'Floor overview'}<span>Click a room to enter</span></div><svg viewBox={`${bounds.minX - 1} ${bounds.minY - 1} ${bounds.width + 2} ${bounds.height + 2}`} role="group" aria-label="Floor minimap">
      {rooms.map(room => <polygon key={room.id} tabIndex={0} role="button" aria-label={`Enter ${room.name}`} points={room.polygon.map(p => p.join(',')).join(' ')} fill={room.id === currentRoom ? '#7d939f' : '#b9bdbe'} fillOpacity={room.id === currentRoom ? .75 : .4} stroke="#657077" strokeWidth={.12} onClick={() => { setWalking(true); setAction({ kind: 'teleport', point: interiorPoint(room.polygon), nonce: Date.now() }) }} onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { setWalking(true); setAction({ kind: 'teleport', point: interiorPoint(room.polygon), nonce: Date.now() }) } }} />)}
      {building.walls.filter(w => w.floor_id === floorId).map(w => { const a = building.vertices.find(v => v.id === w.start_id), b = building.vertices.find(v => v.id === w.end_id); return a && b ? <line key={w.id} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="#4b5459" strokeWidth={Math.max(w.thickness_ft, .12)} pointerEvents="none" /> : null })}
      {cameraPoint && <circle cx={cameraPoint.x} cy={cameraPoint.y} r={Math.max(.25, bounds.width / 75)} fill="#2e647d" stroke="white" strokeWidth={.16} pointerEvents="none" />}
    </svg></div>}
  </div>
}

function Scene({ building, floorId, onSelect, onCommand, selectedId, exterior, walking, spacePanning, objectTool, action, dragTarget, raycast, grab, setRoom }: EditorProps & { exterior: boolean; walking: boolean; spacePanning: boolean; objectTool: 'translate' | 'rotate'; action: CameraAction; dragTarget: string | null; raycast: RefObject<(x: number, y: number) => Hit>; grab: RefObject<(() => ReturnType<typeof captureGuide>) | null>; setRoom: (id: string | null, p: Point) => void }) {
  const look = useAppearance()
  const bounds = useMemo(() => floorBounds(exterior ? { ...building, vertices: building.vertices.map(v => ({ ...v, floor_id: floorId })) } : building, floorId), [building, floorId, exterior])
  const walls = building.walls.filter(w => w.floor_id === floorId), rooms = building.rooms.filter(r => r.floor_id === floorId)
  const objects = building.objects.filter(o => o.floor_id === floorId)
  const vertices = useMemo(() => new Map(building.vertices.map(v => [v.id, v])), [building.vertices])
  const controls = useRef<any>(null)
  const { camera, gl, scene } = useThree()
  const keys = useRef(new Set<string>())
  const lastRoom = useRef(0)
  const groundElevation = Math.min(...building.floors.map(f => f.elevation_ft), 0)
  const topFloor = [...building.floors].sort((a,b) => (b.elevation_ft + b.height_ft) - (a.elevation_ft + a.height_ft))[0]
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
    if (action.kind === 'fit') {
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
  }, [action, bounds, camera, exterior, topFloor?.elevation_ft, topFloor?.height_ft, groundElevation])
  useEffect(() => {
    if (!walking && document.pointerLockElement === gl.domElement) document.exitPointerLock()
    keys.current.clear()
    const down = (e: KeyboardEvent) => { if (!walking || ['INPUT', 'TEXTAREA', 'SELECT'].includes((e.target as HTMLElement)?.tagName)) return; if (['w', 'a', 's', 'd', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].includes(e.key)) { keys.current.add(e.key.toLowerCase()); e.preventDefault() } }
    const up = (e: KeyboardEvent) => keys.current.delete(e.key.toLowerCase())
    const blur = () => keys.current.clear()
    const look = (e: MouseEvent) => { if (walking && document.pointerLockElement === gl.domElement) { camera.rotation.order = 'YXZ'; camera.rotation.y -= e.movementX * .002; camera.rotation.x = THREE.MathUtils.clamp(camera.rotation.x - e.movementY * .002, -Math.PI * .46, Math.PI * .46) } }
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
      }
    }
    if (clock.elapsedTime - lastRoom.current > .3) {
      const target = walking ? camera.position : controls.current?.target || camera.position
      const point = { x: target.x, y: target.z }, room = rooms.find(r => pointInPolygon(point, r.polygon))
      setRoom(room?.id || null, point); lastRoom.current = clock.elapsedTime
    }
  })
  const hideShell = exterior && !!look.splatUrl
  const roofHeight = (topFloor?.elevation_ft || 0) + (topFloor?.height_ft || 9) - groundElevation
  return <>
    <Daylight bounds={bounds} environment={building.environment} />
    <Suspense fallback={null}>
      <Landscape bounds={bounds} />
      {hideShell && look.splatUrl && <ExteriorSplat url={look.splatUrl} bounds={bounds} height={roofHeight} />}
      {(exterior ? building.floors : building.floors.filter(f => f.id === floorId)).map(floor => {
        const floorRooms = exterior ? building.rooms.filter(r => r.floor_id === floor.id) : rooms
        const floorWalls = exterior ? building.walls.filter(w => w.floor_id === floor.id) : walls
        const below = building.floors.filter(f => f.elevation_ft < floor.elevation_ft).sort((a,b) => b.elevation_ft-a.elevation_ft)[0]
        const slabThickness = exterior && below ? Math.max(.32, floor.elevation_ft-below.elevation_ft-below.height_ft) : .32
        return <group key={floor.id} position={[0, exterior ? floor.elevation_ft - groundElevation : 0, 0]}>
          {floorRooms.map(room => <group key={room.id}><FloorSlab polygon={room.polygon} y={-slabThickness} thickness={slabThickness} /><RoomFloor room={room} faded={dragTarget === room.id} selected={selectedId === room.id} onSelect={onSelect} /></group>)}
          {!hideShell && <Walls3D walls={floorWalls} vertices={vertices} openings={building.openings} selectedId={selectedId} dragTarget={dragTarget} onSelect={onSelect} photoreal={exterior} />}
          {exterior && !hideShell && <FloorDressing walls={floorWalls} rooms={floorRooms} vertices={vertices} height={floor.height_ft} foundation={floor.elevation_ft === groundElevation} />}
          {exterior && !hideShell && floor.id === topFloor?.id && <ConceptRoof walls={floorWalls} rooms={floorRooms} vertices={vertices} height={floor.height_ft} />}
          {!exterior && objects.map(object => <PlacedEntity key={object.id} object={object} selected={selectedId === object.id} walking={walking} tool={objectTool} onSelect={onSelect} onCommand={onCommand} />)}
        </group>
      })}
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

function Walls3D({ walls, vertices, openings, selectedId, dragTarget, onSelect, photoreal }: { walls: Wall[]; vertices: Map<string, { id: string; x: number; y: number }>; openings: Building['openings']; selectedId: string | null; dragTarget: string | null; onSelect: (id: string) => void; photoreal: boolean }) {
  const byWall = useMemo(() => {
    const map = new Map<string, Building['openings']>()
    for (const opening of openings) {
      const list = map.get(opening.wall_id)
      if (list) list.push(opening)
      else map.set(opening.wall_id, [opening])
    }
    return map
  }, [openings])
  const { solid, holed } = useMemo(() => {
    const solidWalls: Wall[] = []
    const holedWalls: Wall[] = []
    for (const wall of walls) {
      if (byWall.get(wall.id)?.length) holedWalls.push(wall)
      else solidWalls.push(wall)
    }
    return { solid: solidWalls, holed: holedWalls }
  }, [walls, byWall])
  return <>
    <InstancedWalls walls={solid} vertices={vertices} selectedId={selectedId} dragTarget={dragTarget} onSelect={onSelect} photoreal={photoreal} />
    {holed.map(wall => { const a = vertices.get(wall.start_id), b = vertices.get(wall.end_id); return a && b ? <WallMesh key={wall.id} wall={wall} a={a} b={b} openings={byWall.get(wall.id) || []} faded={dragTarget === wall.id} selected={selectedId === wall.id} onSelect={onSelect} photoreal={photoreal} /> : null })}
  </>
}

function InstancedWalls({ walls, vertices, selectedId, dragTarget, onSelect, photoreal }: { walls: Wall[]; vertices: Map<string, { id: string; x: number; y: number }>; selectedId: string | null; dragTarget: string | null; onSelect: (id: string) => void; photoreal: boolean }) {
  const mesh = useRef<THREE.InstancedMesh>(null)
  const ids = useMemo(() => walls.map(w => w.id), [walls])
  const count = walls.length
  useLayoutEffect(() => {
    const node = mesh.current
    if (!node || !count) return
    const dummy = new THREE.Object3D()
    const color = new THREE.Color()
    const highlight = new THREE.Color('#3d5c78')
    for (let i = 0; i < walls.length; i++) {
      const wall = walls[i]
      const a = vertices.get(wall.start_id), b = vertices.get(wall.end_id)
      if (!a || !b) {
        dummy.scale.set(0, 0, 0)
        dummy.updateMatrix()
        node.setMatrixAt(i, dummy.matrix)
        continue
      }
      const length = Math.hypot(b.x - a.x, b.y - a.y)
      const angle = Math.atan2(b.y - a.y, b.x - a.x)
      dummy.position.set((a.x + b.x) / 2, wall.height_ft / 2, (a.y + b.y) / 2)
      dummy.rotation.set(0, -angle, 0)
      dummy.scale.set(Math.max(length, .01), wall.height_ft, Math.max(wall.thickness_ft, .05))
      dummy.updateMatrix()
      node.setMatrixAt(i, dummy.matrix)
      color.set(photoreal ? '#ffffff' : (colors[wall.material] || '#eeeae2'))
      if (selectedId === wall.id) color.lerp(highlight, .45)
      if (dragTarget === wall.id) color.multiplyScalar(.45)
      node.setColorAt(i, color)
    }
    node.instanceMatrix.needsUpdate = true
    if (node.instanceColor) node.instanceColor.needsUpdate = true
    node.userData = { kind: 'wall-instances', instanceIds: ids }
  }, [walls, vertices, selectedId, dragTarget, count, ids, photoreal])
  if (!count) return null
  return <instancedMesh key={count} ref={mesh} args={[undefined, undefined, count]} castShadow receiveShadow frustumCulled={false} userData={{ kind: 'wall-instances', instanceIds: ids }} onClick={e => { e.stopPropagation(); const id = ids[e.instanceId ?? -1]; if (id) onSelect(id) }}>
    <boxGeometry args={[1, 1, 1]} />
    <SurfaceMaterial finish="plaster" photoreal={photoreal} />
  </instancedMesh>
}

function WallMesh({ wall, a, b, openings, faded, selected, onSelect, photoreal }: { wall: Wall; a: Point; b: Point; openings: Building['openings']; faded: boolean; selected: boolean; onSelect: (id: string) => void; photoreal: boolean }) {
  const length = Math.hypot(b.x - a.x, b.y - a.y), angle = Math.atan2(b.y - a.y, b.x - a.x)
  const pieces = useMemo(() => {
    const result: { x: number; y: number; width: number; height: number }[] = []
    let cursor = 0
    for (const opening of [...openings].sort((a, b) => a.offset_ft - b.offset_ft)) {
      const start = Math.max(cursor, Math.min(length, opening.offset_ft)), end = Math.min(length, opening.offset_ft + opening.width_ft)
      if (start > cursor) result.push({ x: (cursor + start) / 2, y: wall.height_ft / 2, width: start - cursor, height: wall.height_ft })
      if (opening.sill_ft > 0) result.push({ x: (start + end) / 2, y: opening.sill_ft / 2, width: end - start, height: opening.sill_ft })
      const top = Math.min(wall.height_ft, opening.sill_ft + opening.height_ft)
      if (top < wall.height_ft) result.push({ x: (start + end) / 2, y: (top + wall.height_ft) / 2, width: end - start, height: wall.height_ft - top })
      cursor = Math.max(cursor, end)
    }
    if (cursor < length) result.push({ x: (cursor + length) / 2, y: wall.height_ft / 2, width: length - cursor, height: wall.height_ft })
    return result.filter(p => p.width > .001 && p.height > .001)
  }, [openings, length, wall.height_ft])
  const color = photoreal ? '#ffffff' : (colors[wall.material] || '#eeeae2')
  return <group position={[a.x, 0, a.y]} rotation={[0, -angle, 0]} userData={{ entityId: wall.id, kind: 'wall' }} onClick={e => { e.stopPropagation(); onSelect(wall.id) }}>
    {pieces.map((piece, i) => <mesh key={i} position={[piece.x, piece.y, 0]} castShadow receiveShadow><boxGeometry args={[piece.width, piece.height, wall.thickness_ft]} /><SurfaceMaterial finish="plaster" color={color} faded={faded} selected={selected} photoreal={photoreal} /></mesh>)}
    {openings.map(opening => <OpeningDressing key={opening.id} opening={opening} wallThickness={wall.thickness_ft} photoreal={photoreal} />)}
  </group>
}
function OpeningDressing({ opening, wallThickness, photoreal }: { opening: Building['openings'][number]; wallThickness: number; photoreal: boolean }) {
  const width = opening.width_ft, height = opening.height_ft, depth = wallThickness
  const trim = photoreal ? '#3f4548' : opening.kind === 'window' ? '#747871' : '#f4efe4'
  return <group position={[opening.offset_ft + width / 2, opening.sill_ft + height / 2, 0]}>
    {opening.kind === 'window' ? <mesh position={[0, 0, 0]}><boxGeometry args={[Math.max(.2, width - .22), Math.max(.2, height - .22), .04]} /><meshPhysicalMaterial color="#9ec2ce" transparent opacity={.38} roughness={.04} metalness={.22} envMapIntensity={1.45} side={THREE.DoubleSide} /></mesh> : null}
    {opening.kind === 'door' ? <DoorLeaf opening={opening} wallThickness={wallThickness} /> : null}
    <mesh position={[0, -height / 2 - .07, 0]} castShadow receiveShadow><boxGeometry args={[width + .32, .14, depth + .42]} /><SurfaceMaterial finish="stone" color="#c9c2b4" matchStyle={false} /></mesh>
    <mesh position={[0, height / 2 + .07, 0]} castShadow receiveShadow><boxGeometry args={[width + .22, .16, depth + .16]} /><SurfaceMaterial finish="stone" color="#b7b1a6" matchStyle={false} /></mesh>
    {[[-width / 2 + .07, 0, .14, height], [width / 2 - .07, 0, .14, height], [0, height / 2 - .07, width, .14], ...(opening.kind === 'window' ? [[0, -height / 2 + .07, width, .14], [0, 0, .05, height]] : [])].map(([x, y, w, h], i) => <mesh key={i} position={[x, y, 0]} castShadow><boxGeometry args={[w, h, depth + .1]} /><meshStandardMaterial color={trim} roughness={.48} metalness={.08} /></mesh>)}
  </group>
}
function DoorLeaf({ opening, wallThickness }: { opening: Building['openings'][number]; wallThickness: number }) {
  const width = Math.max(.3, opening.width_ft - .16), height = Math.max(.3, opening.height_ft - .16)
  return <group position={[0, 0, wallThickness / 2 + .075]}>
    <mesh castShadow receiveShadow><boxGeometry args={[width, height, .12]} /><meshStandardMaterial color="#5b3925" roughness={.5} metalness={.02} /></mesh>
    <mesh position={[0, 0, .066]}><boxGeometry args={[width * .78, height * .78, .012]} /><meshStandardMaterial color="#755039" roughness={.42} /></mesh>
    <mesh position={[width * .34, 0, .13]} rotation={[Math.PI / 2, 0, 0]} castShadow><cylinderGeometry args={[.045, .045, .11, 12]} /><meshStandardMaterial color="#c5a46a" metalness={.8} roughness={.22} /></mesh>
  </group>
}
function RoomFloor({ room, faded, selected, onSelect }: { room: Building['rooms'][number]; faded: boolean; selected: boolean; onSelect: (id: string) => void }) {
  const geometry = useMemo(() => { const shape = new THREE.Shape(); room.polygon.forEach(([x, y], i) => i === 0 ? shape.moveTo(x, -y) : shape.lineTo(x, -y)); shape.closePath(); return new THREE.ShapeGeometry(shape) }, [room.polygon])
  const usesOak = ['oak', 'walnut'].includes(room.floor_material)
  useEffect(() => () => geometry.dispose(), [geometry])
  return <mesh geometry={geometry} rotation={[-Math.PI / 2, 0, 0]} position={[0, .025, 0]} receiveShadow userData={{ entityId: room.id, kind: 'room' }} onClick={e => { e.stopPropagation(); onSelect(room.id) }}><SurfaceMaterial finish={usesOak ? 'wood' : 'stone'} color={room.floor_material === 'walnut' ? '#ad876a' : usesOak ? '#ffffff' : colors[room.floor_material] || '#d5d0c3'} faded={faded} selected={selected} /></mesh>
}
function ConceptRoof({ walls, rooms, vertices, height }: { walls: Wall[]; rooms: Building['rooms']; vertices: Map<string, Point>; height: number }) {
  const overhang = 1.55
  return <group>
    {rooms.map(room => <FloorSlab key={room.id} polygon={room.polygon} y={height + .08} roof photoreal />)}
    {walls.map(wall => {
      const a = vertices.get(wall.start_id), b = vertices.get(wall.end_id)
      if (!a || !b) return null
      const edge = wallExterior(a, b, rooms)
      if (!edge) {
        const length = Math.hypot(b.x - a.x, b.y - a.y)
        if (length < .01) return null
        return <group key={wall.id} position={[edgeCenter(a, b).x, height, edgeCenter(a, b).y]} rotation={[0, -Math.atan2(b.y - a.y, b.x - a.x), 0]}>
          <mesh position={[0, .16, 0]} castShadow receiveShadow><boxGeometry args={[length + .03, .32, wall.thickness_ft + .03]} /><SurfaceMaterial finish="stone" color="#616568" photoreal /></mesh>
        </group>
      }
      const z = edge.sign * (wall.thickness_ft / 2 + overhang)
      return <group key={wall.id} position={[edge.center.x, height, edge.center.y]} rotation={[0, -edge.angle, 0]}>
        <mesh position={[0, .12, edge.sign * overhang * .35]} castShadow receiveShadow><boxGeometry args={[edge.length + overhang * .2, .28, wall.thickness_ft + overhang * .7]} /><SurfaceMaterial finish="stone" color="#5c5854" photoreal /></mesh>
        <mesh position={[0, -.04, edge.sign * (wall.thickness_ft / 2 + overhang / 2)]} receiveShadow><boxGeometry args={[edge.length + .16, .08, overhang]} /><SurfaceMaterial finish="wood" color="#c4b49a" matchStyle={false} /></mesh>
        <mesh position={[0, .28, z]} castShadow receiveShadow><boxGeometry args={[edge.length + .22, .62, .12]} /><SurfaceMaterial finish="stone" color="#3f4244" matchStyle={false} /></mesh>
        <mesh position={[0, .58, edge.sign * (wall.thickness_ft / 2 + overhang * .2)]} castShadow receiveShadow><boxGeometry args={[edge.length + .08, .12, wall.thickness_ft + .18]} /><meshStandardMaterial color="#8a8d8c" metalness={.35} roughness={.45} /></mesh>
      </group>
    })}
  </group>
}
function edgeCenter(a: Point, b: Point) {
  return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 }
}
function FloorDressing({ walls, rooms, vertices, height, foundation }: { walls: Wall[]; rooms: Building['rooms']; vertices: Map<string, Point>; height: number; foundation: boolean }) {
  const edges = walls.flatMap(wall => {
    const a = vertices.get(wall.start_id), b = vertices.get(wall.end_id)
    if (!a || !b) return []
    const edge = wallExterior(a, b, rooms)
    return edge ? [{ wall, a, b, edge }] : []
  })
  const corners = new Map<string, Point>()
  for (const item of edges) {
    corners.set(item.wall.start_id, item.a)
    corners.set(item.wall.end_id, item.b)
  }
  return <group>
    {foundation && edges.map(({ wall, edge }) => (
      <mesh key={`base-${wall.id}`} position={[edge.center.x + edge.outward.x * 0.08, 0.58, edge.center.y + edge.outward.y * 0.08]} rotation={[0, -edge.angle, 0]} castShadow receiveShadow>
        <boxGeometry args={[edge.length + 0.1, 1.16, wall.thickness_ft + 0.28]} />
        <SurfaceMaterial finish="stone" color="#6c6760" matchStyle={false} />
      </mesh>
    ))}
    {!foundation && edges.map(({ wall, edge }) => (
      <mesh key={`belt-${wall.id}`} position={[edge.center.x + edge.outward.x * 0.06, 0.08, edge.center.y + edge.outward.y * 0.06]} rotation={[0, -edge.angle, 0]} castShadow>
        <boxGeometry args={[edge.length + 0.06, 0.18, wall.thickness_ft + 0.22]} />
        <SurfaceMaterial finish="stone" color="#b7b1a6" matchStyle={false} />
      </mesh>
    ))}
    {[...corners.entries()].map(([id, point]) => (
      <mesh key={`corner-${id}`} position={[point.x, height / 2, point.y]} castShadow receiveShadow>
        <boxGeometry args={[0.42, height, 0.42]} />
        <SurfaceMaterial finish="stone" color="#d5cfc4" matchStyle={false} />
      </mesh>
    ))}
  </group>
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
