import { Component, Suspense, useEffect, useMemo, useRef, useState, type ReactNode, type RefObject } from 'react'
import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { OrbitControls, TransformControls, GizmoHelper, GizmoViewcube, useGLTF } from '@react-three/drei'
import * as THREE from 'three'
import { Footprints, Orbit, RotateCw, Maximize, LoaderCircle, X } from 'lucide-react'
import type { Building } from '../types'
import { assetMime, floorBounds, furniture, interiorPoint, materials, placementCommand, pointInPolygon, projectPoint, type Asset, type EditorProps, type Point } from './editor-geometry'
import './editor-view.css'

type Wall = Building['walls'][number]
type CameraAction = { kind: 'fit' | 'rotate' | 'teleport'; point?: Point; nonce: number }
type Hit = { id: string; point: Point; kind: string } | null
const colors = Object.fromEntries(materials.map(m => [m.id, m.color]))

export function ModelView(props: EditorProps) {
  const { building, floorId, onCommand, onSelect, selectedId, busy } = props
  const host = useRef<HTMLDivElement>(null)
  const [walking, setWalking] = useState(false)
  const [currentRoom, setCurrentRoom] = useState<string | null>(null)
  const [cameraPoint, setCameraPoint] = useState<Point | null>(null)
  const [action, setAction] = useState<CameraAction>({ kind: 'fit', nonce: 0 })
  const [dragAsset, setDragAsset] = useState<Asset | null>(null)
  const [dragTarget, setDragTarget] = useState<string | null>(null)
  const [notice, setNotice] = useState('')
  const [objectTool, setObjectTool] = useState<'translate' | 'rotate'>('translate')
  const raycast = useRef<(x: number, y: number) => Hit>(() => null)
  const rooms = building.rooms.filter(r => r.floor_id === floorId)
  const bounds = useMemo(() => floorBounds(building, floorId), [building, floorId])
  useEffect(() => { setAction({ kind: 'fit', nonce: Date.now() }); setWalking(false); setCurrentRoom(null) }, [floorId])
  useEffect(() => {
    const listener = (event: Event) => { setDragAsset((event as CustomEvent<Asset | null>).detail); setDragTarget(null) }
    window.addEventListener('archetype:asset-drag', listener)
    return () => window.removeEventListener('archetype:asset-drag', listener)
  }, [])
  useEffect(() => { if (!notice) return; const t = setTimeout(() => setNotice(''), 4000); return () => clearTimeout(t) }, [notice])
  return <div ref={host} className={`editor-modelview ${dragAsset ? 'asset-dragging' : ''}`} aria-label="3D model editor" onDragOver={event => { event.preventDefault(); const hit = raycast.current(event.clientX, event.clientY); setDragTarget(hit?.id || null) }} onDragLeave={event => { if (!host.current?.contains(event.relatedTarget as Node)) setDragTarget(null) }} onDrop={event => {
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
    <SceneBoundary><Canvas shadows dpr={[1, 1.75]} camera={{ position: [bounds.cx + 30, 38, bounds.cy + 40], fov: 44, near: .1, far: 10000 }} gl={{ antialias: true, toneMapping: THREE.ACESFilmicToneMapping, toneMappingExposure: 1.05 }} onPointerMissed={() => onSelect(null)}>
      <color attach="background" args={['#e9e8e4']} />
      <Scene {...props} walking={walking} objectTool={objectTool} action={action} dragTarget={dragTarget} raycast={raycast} setRoom={(id, point) => { setCurrentRoom(id); setCameraPoint(point) }} />
    </Canvas></SceneBoundary>
    <div className="editor-floating-tools editor-model-tools" role="toolbar" aria-label="3D navigation">
      <button className={!walking ? 'active' : ''} aria-label="Orbit view" title="Orbit view" onClick={() => setWalking(false)}><Orbit size={17} /></button>
      <button className={walking ? 'active' : ''} aria-label="Walk through the building" title="Walk through" onClick={() => { setWalking(true); const room = rooms.find(r => r.id === currentRoom) || rooms[0]; if (room) setAction({ kind: 'teleport', point: interiorPoint(room.polygon), nonce: Date.now() }) }}><Footprints size={17} /></button>
      <span className="editor-tool-divider" /><button title="Rotate view 45°" aria-label="Rotate view 45 degrees" onClick={() => setAction({ kind: 'rotate', nonce: Date.now() })}><RotateCw size={17} /></button><button title="Fit model" aria-label="Fit model" onClick={() => { setWalking(false); setAction({ kind: 'fit', nonce: Date.now() }) }}><Maximize size={16} /></button>
    </div>
    <div className="editor-model-label"><span className="editor-live-dot" />{building.floors.find(f => f.id === floorId)?.name} <span>·</span> {walking ? 'Walkthrough' : 'Perspective'}</div>
    {selectedId && !walking && <div className="editor-model-selection">{building.walls.some(w => w.id === selectedId) ? 'Wall selected' : building.rooms.find(r => r.id === selectedId)?.name || 'Object selected'}{building.objects.some(o => o.id === selectedId) && <><button className={objectTool === 'translate' ? 'active' : ''} onClick={() => setObjectTool('translate')}>Move</button><button className={objectTool === 'rotate' ? 'active' : ''} onClick={() => setObjectTool('rotate')}>Rotate</button></>}<button aria-label="Clear selection" onClick={() => onSelect(null)}><X size={12} /></button></div>}
    {busy && <div className="editor-updating" role="status"><LoaderCircle size={13} className="editor-spin" />Updating design · showing saved model</div>}
    {notice && <div className="editor-notice" role="status">{notice}</div>}
    <div className="editor-canvas-hint">{walking ? 'Click the model to look around · W A S D to walk · Esc releases the pointer' : 'Drag to orbit · Right-drag to pan · Scroll to zoom'}</div>
    {rooms.length > 0 && <div className="editor-minimap"><div>{currentRoom ? rooms.find(r => r.id === currentRoom)?.name : 'Floor overview'}<span>Click a room to enter</span></div><svg viewBox={`${bounds.minX - 1} ${bounds.minY - 1} ${bounds.width + 2} ${bounds.height + 2}`} role="group" aria-label="Floor minimap">
      {rooms.map(room => <polygon key={room.id} tabIndex={0} role="button" aria-label={`Enter ${room.name}`} points={room.polygon.map(p => p.join(',')).join(' ')} fill={room.id === currentRoom ? '#7d939f' : '#b9bdbe'} fillOpacity={room.id === currentRoom ? .75 : .4} stroke="#657077" strokeWidth={.12} onClick={() => { setWalking(true); setAction({ kind: 'teleport', point: interiorPoint(room.polygon), nonce: Date.now() }) }} onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { setWalking(true); setAction({ kind: 'teleport', point: interiorPoint(room.polygon), nonce: Date.now() }) } }} />)}
      {building.walls.filter(w => w.floor_id === floorId).map(w => { const a = building.vertices.find(v => v.id === w.start_id), b = building.vertices.find(v => v.id === w.end_id); return a && b ? <line key={w.id} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="#4b5459" strokeWidth={Math.max(w.thickness_ft, .12)} pointerEvents="none" /> : null })}
      {cameraPoint && <circle cx={cameraPoint.x} cy={cameraPoint.y} r={Math.max(.25, bounds.width / 75)} fill="#2e647d" stroke="white" strokeWidth={.16} pointerEvents="none" />}
    </svg></div>}
  </div>
}

function Scene({ building, floorId, onSelect, onCommand, selectedId, walking, objectTool, action, dragTarget, raycast, setRoom }: EditorProps & { walking: boolean; objectTool: 'translate' | 'rotate'; action: CameraAction; dragTarget: string | null; raycast: RefObject<(x: number, y: number) => Hit>; setRoom: (id: string | null, p: Point) => void }) {
  const bounds = useMemo(() => floorBounds(building, floorId), [building, floorId])
  const walls = building.walls.filter(w => w.floor_id === floorId), rooms = building.rooms.filter(r => r.floor_id === floorId)
  const objects = building.objects.filter(o => o.floor_id === floorId)
  const vertices = useMemo(() => new Map(building.vertices.map(v => [v.id, v])), [building.vertices])
  const controls = useRef<any>(null)
  const { camera, gl, scene } = useThree()
  const keys = useRef(new Set<string>())
  const lastRoom = useRef(0)
  const sun = building.environment
  const daylight = Math.max(.08, Math.sin((sun.time - 6) / 12 * Math.PI))
  const elevation = (sun.season === 'winter' ? .42 : sun.season === 'summer' ? 1 : .7) * Math.max(.1, daylight)
  const azimuth = sun.sun_azimuth * Math.PI / 180
  const dayColor = daylight < .25 ? '#e8b195' : '#fff4db'
  useEffect(() => {
    raycast.current = (clientX, clientY) => {
      const rect = gl.domElement.getBoundingClientRect(), pointer = new THREE.Vector2((clientX - rect.left) / rect.width * 2 - 1, -(clientY - rect.top) / rect.height * 2 + 1)
      const ray = new THREE.Raycaster(); ray.setFromCamera(pointer, camera)
      const hits = ray.intersectObjects(scene.children, true)
      for (const hit of hits) { let object: THREE.Object3D | null = hit.object; while (object && !object.userData.entityId) object = object.parent; if (object?.userData.entityId) return { id: object.userData.entityId, kind: object.userData.kind, point: { x: hit.point.x, y: hit.point.z } } }
      const point = ray.ray.intersectPlane(new THREE.Plane(new THREE.Vector3(0, 1, 0), 0), new THREE.Vector3())
      return point && point.x >= bounds.minX - 2 && point.x <= bounds.maxX + 2 && point.z >= bounds.minY - 2 && point.z <= bounds.maxY + 2 ? { id: '', kind: 'ground', point: { x: point.x, y: point.z } } : null
    }
  }, [camera, gl, scene, raycast, bounds])
  useEffect(() => {
    if (action.kind === 'fit') {
      const distance = Math.max(bounds.width, bounds.height, 15)
      camera.position.set(bounds.cx + distance * .85, distance * .85, bounds.cy + distance * .9)
      controls.current?.target.set(bounds.cx, 0, bounds.cy)
      camera.lookAt(bounds.cx, 0, bounds.cy)
    } else if (action.kind === 'rotate') {
      if (walking) { camera.rotation.order = 'YXZ'; camera.rotation.y -= Math.PI / 4 }
      else { const center = controls.current?.target || new THREE.Vector3(bounds.cx, 0, bounds.cy); const delta = camera.position.clone().sub(center).applyAxisAngle(new THREE.Vector3(0, 1, 0), Math.PI / 4); camera.position.copy(center).add(delta); camera.lookAt(center) }
    } else if (action.point) {
      camera.position.set(action.point.x, 5.3, action.point.y)
      camera.rotation.order = 'YXZ'; camera.rotation.set(0, Math.PI, 0)
      controls.current?.target.set(action.point.x, 5.3, action.point.y + 4)
    }
    controls.current?.update()
  }, [action, bounds, camera])
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
  return <>
    <ambientLight intensity={.35 + daylight * .35} />
    <hemisphereLight args={['#dce8f7', '#bdb5a4', .8]} />
    <directionalLight position={[bounds.cx + Math.cos(azimuth) * 80, 15 + elevation * 100, bounds.cy + Math.sin(azimuth) * 80]} intensity={.4 + daylight * 2.5} color={dayColor} castShadow shadow-mapSize={[2048, 2048]} shadow-camera-left={-Math.max(bounds.width, bounds.height)} shadow-camera-right={Math.max(bounds.width, bounds.height)} shadow-camera-top={Math.max(bounds.width, bounds.height)} shadow-camera-bottom={-Math.max(bounds.width, bounds.height)} shadow-camera-far={350} shadow-bias={-.0002} />
    <mesh rotation={[-Math.PI / 2, 0, 0]} position={[bounds.cx, -.15, bounds.cy]} receiveShadow><planeGeometry args={[Math.max(bounds.width * 4, 150), Math.max(bounds.height * 4, 150)]} /><meshStandardMaterial color="#e9e6df" roughness={1} /></mesh>
    {rooms.map(room => <RoomFloor key={room.id} room={room} faded={dragTarget === room.id} selected={selectedId === room.id} onSelect={onSelect} />)}
    {walls.map(wall => { const a = vertices.get(wall.start_id), b = vertices.get(wall.end_id); return a && b ? <WallMesh key={wall.id} wall={wall} a={a} b={b} openings={building.openings.filter(o => o.wall_id === wall.id)} faded={dragTarget === wall.id} selected={selectedId === wall.id} onSelect={onSelect} /> : null })}
    {objects.map(object => <PlacedEntity key={object.id} object={object} selected={selectedId === object.id} walking={walking} tool={objectTool} onSelect={onSelect} onCommand={onCommand} />)}
    {!walking && <OrbitControls ref={controls} makeDefault minDistance={3} maxDistance={Math.max(bounds.width, bounds.height) * 6} maxPolarAngle={Math.PI * .49} enableDamping dampingFactor={.09} />}
    {!walking && <GizmoHelper alignment="top-right" margin={[58, 65]}><GizmoViewcube color="#eeefef" hoverColor="#c8d6df" textColor="#64727b" strokeColor="#e0e1e1" opacity={.8} /></GizmoHelper>}
  </>
}

function PlacedEntity({ object, selected, walking, tool, onSelect, onCommand }: { object: Building['objects'][number]; selected: boolean; walking: boolean; tool: 'translate' | 'rotate'; onSelect: EditorProps['onSelect']; onCommand: EditorProps['onCommand'] }) {
  const ref = useRef<THREE.Group>(null)
  const node = <group ref={ref} position={[object.x, .02, object.y]} rotation={[0, -object.rotation_deg * Math.PI / 180, 0]} userData={{ entityId: object.id, kind: 'object' }} onClick={e => { e.stopPropagation(); onSelect(object.id) }}>
    {object.kind === 'furniture' && furniture.some(a => a.id === object.asset_id) ? <Suspense fallback={<LoadingObject object={object} />}><FurnitureModel object={object} selected={selected} /></Suspense> : <FixtureModel object={object} selected={selected} />}
  </group>
  return selected && !walking ? <TransformControls mode={tool} showX={tool === 'translate'} showY={tool === 'rotate'} showZ={tool === 'translate'} size={.7} translationSnap={.25} rotationSnap={Math.PI / 12} onMouseUp={() => { const node = ref.current; if (!node) return; const rotation = -node.rotation.y * 180 / Math.PI; if (Math.abs(node.position.x - object.x) + Math.abs(node.position.z - object.y) + Math.abs(rotation - object.rotation_deg) < .001) return; onCommand([{ kind: 'update_object', target_id: object.id, params: { x: node.position.x, y: node.position.z, rotation_deg: rotation } }]) }}>{node}</TransformControls> : node
}

function WallMesh({ wall, a, b, openings, faded, selected, onSelect }: { wall: Wall; a: Point; b: Point; openings: Building['openings']; faded: boolean; selected: boolean; onSelect: (id: string) => void }) {
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
  const color = colors[wall.material] || '#eeeae2'
  return <group position={[a.x, 0, a.y]} rotation={[0, -angle, 0]} userData={{ entityId: wall.id, kind: 'wall' }} onClick={e => { e.stopPropagation(); onSelect(wall.id) }}>
    {pieces.map((piece, i) => <mesh key={i} position={[piece.x, piece.y, 0]} castShadow receiveShadow><boxGeometry args={[piece.width, piece.height, wall.thickness_ft]} /><meshStandardMaterial color={color} roughness={.8} transparent={faded} opacity={faded ? .35 : 1} emissive={selected ? '#405969' : '#000000'} emissiveIntensity={selected ? .13 : 0} /></mesh>)}
    {openings.map(opening => <group key={opening.id} position={[opening.offset_ft + opening.width_ft / 2, opening.sill_ft + opening.height_ft / 2, 0]}>
      {opening.kind === 'window' ? <mesh><boxGeometry args={[opening.width_ft - .1, opening.height_ft - .1, .035]} /><meshPhysicalMaterial color="#b8d1d9" transparent opacity={.22} roughness={.1} metalness={.1} side={THREE.DoubleSide} /></mesh> : null}
      {[[-opening.width_ft / 2 + .04, 0, .08, opening.height_ft], [opening.width_ft / 2 - .04, 0, .08, opening.height_ft], [0, opening.height_ft / 2 - .04, opening.width_ft, .08], ...(opening.kind === 'window' ? [[0, -opening.height_ft / 2 + .04, opening.width_ft, .08], [0, 0, .06, opening.height_ft]] : [])].map(([x, y, w, h], i) => <mesh key={i} position={[x, y, 0]} castShadow><boxGeometry args={[w, h, wall.thickness_ft + .04]} /><meshStandardMaterial color={opening.kind === 'window' ? '#747871' : '#f4efe4'} roughness={.6} /></mesh>)}
    </group>)}
  </group>
}
function RoomFloor({ room, faded, selected, onSelect }: { room: Building['rooms'][number]; faded: boolean; selected: boolean; onSelect: (id: string) => void }) {
  const geometry = useMemo(() => { const shape = new THREE.Shape(); room.polygon.forEach(([x, y], i) => i === 0 ? shape.moveTo(x, -y) : shape.lineTo(x, -y)); shape.closePath(); return new THREE.ShapeGeometry(shape) }, [room.polygon])
  const texture = useMemo(() => floorTexture(room.floor_material), [room.floor_material])
  useEffect(() => () => geometry.dispose(), [geometry])
  useEffect(() => () => texture?.dispose(), [texture])
  return <mesh geometry={geometry} rotation={[-Math.PI / 2, 0, 0]} position={[0, .005, 0]} receiveShadow userData={{ entityId: room.id, kind: 'room' }} onClick={e => { e.stopPropagation(); onSelect(room.id) }}><meshStandardMaterial color={colors[room.floor_material] || '#c7aa7f'} map={texture} roughness={.85} transparent={faded} opacity={faded ? .4 : 1} side={THREE.DoubleSide} emissive={selected ? '#354c69' : '#000000'} emissiveIntensity={selected ? .16 : 0} /></mesh>
}
function floorTexture(material: string) {
  if (!['oak', 'walnut', 'tile'].includes(material)) return null
  const canvas = document.createElement('canvas'); canvas.width = canvas.height = 256
  const ctx = canvas.getContext('2d')!; ctx.fillStyle = '#ffffff'; ctx.fillRect(0, 0, 256, 256)
  if (material === 'tile') { ctx.strokeStyle = '#b9b6af'; ctx.lineWidth = 2; ctx.strokeRect(0, 0, 256, 256) }
  else {
    for (let i = 0; i < 8; i++) { ctx.fillStyle = i % 3 ? '#f5f0e8' : '#fffdf9'; ctx.fillRect(0, i * 32, 256, 32); ctx.strokeStyle = '#c8bba8'; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(0, i * 32); ctx.lineTo(256, i * 32); ctx.moveTo((i % 3) * 80, i * 32); ctx.lineTo((i % 3) * 80, (i + 1) * 32); ctx.stroke(); for (let n = 0; n < 8; n++) { ctx.strokeStyle = '#cbbda51c'; ctx.beginPath(); ctx.moveTo(0, i * 32 + n * 4 + 2); ctx.bezierCurveTo(90, i * 32 + n * 4, 180, i * 32 + n * 4 + 4, 256, i * 32 + n * 4 + 2); ctx.stroke() } }
  }
  const map = new THREE.CanvasTexture(canvas); map.wrapS = map.wrapT = THREE.RepeatWrapping; map.repeat.set(.2, .2); map.colorSpace = THREE.SRGBColorSpace; return map
}
function FurnitureModel({ object, selected }: { object: Building['objects'][number]; selected: boolean }) {
  const source = furniture.find(a => a.id === object.asset_id)!
  const { scene } = useGLTF(source.model!)
  const { clone, size, center, minY } = useMemo(() => {
    const clone = scene.clone(true), box = new THREE.Box3().setFromObject(clone), size = box.getSize(new THREE.Vector3()), center = box.getCenter(new THREE.Vector3())
    clone.traverse(node => { if (node instanceof THREE.Mesh) { node.castShadow = node.receiveShadow = true } })
    return { clone, size, center, minY: box.min.y }
  }, [scene])
  return <group scale={[object.width_ft / size.x, object.height_ft / size.y, object.depth_ft / size.z]}><primitive object={clone} position={[-center.x, -minY, -center.z]} />{selected && <mesh position={[0, size.y / 2, 0]}><boxGeometry args={[size.x * 1.02, size.y * 1.02, size.z * 1.02]} /><meshBasicMaterial color="#408cb0" wireframe transparent opacity={.4} /></mesh>}</group>
}
function LoadingObject({ object }: { object: Building['objects'][number] }) {
  return <mesh position={[0, object.height_ft / 2, 0]}><boxGeometry args={[object.width_ft, object.height_ft, object.depth_ft]} /><meshBasicMaterial color="#93a3ad" wireframe transparent opacity={.3} /></mesh>
}
function FixtureModel({ object, selected }: { object: Building['objects'][number]; selected: boolean }) {
  const color = selected ? '#c6dce5' : object.asset_id === 'closet' || object.asset_id === 'counter' ? '#d8c5a7' : '#f8f7f1'
  return <group><mesh position={[0, object.height_ft / 2, 0]} castShadow receiveShadow><boxGeometry args={[object.width_ft, object.height_ft, object.depth_ft]} /><meshStandardMaterial color={color} roughness={.4} /></mesh>{['sink', 'bath', 'toilet', 'shower'].includes(object.asset_id) && <mesh position={[0, object.height_ft + .012, 0]} rotation={[-Math.PI / 2, 0, 0]}><circleGeometry args={[Math.min(object.width_ft, object.depth_ft) * .32, 32]} /><meshStandardMaterial color="#c5cdcc" roughness={.25} /></mesh>}</group>
}
class SceneBoundary extends Component<{ children: ReactNode }, { error: string | null }> {
  state = { error: null as string | null }
  static getDerivedStateFromError(error: Error) { return { error: error.message } }
  render() { return this.state.error ? <div className="editor-scene-error"><strong>The 3D preview could not start.</strong><p>{this.state.error}</p><button onClick={() => this.setState({ error: null })}>Retry preview</button></div> : this.props.children }
}
export default ModelView
