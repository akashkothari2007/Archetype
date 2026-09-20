import { useEffect, useLayoutEffect, useMemo, useRef } from 'react'
import * as THREE from 'three'
import type { Building } from '../types'
import { materials, wallExterior, type Point } from './editor-geometry'
import { surfaceOf } from './material-catalog'
import { SurfaceMaterial } from './scene-materials'
import { FloorSlab } from './scene-landscape'

type Wall = Building['walls'][number]
type Vertices = Map<string, { id: string; x: number; y: number }>
export const colors = Object.fromEntries(materials.map(m => [m.id, m.color]))
function finishColor(id: string) {
  const surface = surfaceOf(id)
  return surface.tint ? (colors[id] || surface.color) : '#ffffff'
}

export function groundElevationOf(building: Building) {
  return Math.min(...building.floors.map(f => f.elevation_ft), 0)
}
export function topFloorOf(building: Building) {
  return [...building.floors].sort((a, b) => (b.elevation_ft + b.height_ft) - (a.elevation_ft + a.height_ft))[0]
}
export function buildingHeightFt(building: Building) {
  const top = topFloorOf(building)
  return (top?.elevation_ft || 0) + (top?.height_ft || 9) - groundElevationOf(building)
}
export function floorsThrough(building: Building, floorId?: string | null) {
  const ordered = [...building.floors].sort((a, b) => a.elevation_ft - b.elevation_ft)
  if (!floorId) return ordered
  const selected = building.floors.find(floor => floor.id === floorId)
  if (!selected) return []
  return ordered.filter(floor => floor.elevation_ft <= selected.elevation_ft)
}
export function floorWorldY(building: Building, floorId: string) {
  const floor = building.floors.find(item => item.id === floorId)
  return (floor?.elevation_ft || 0) - groundElevationOf(building)
}
export function cutawayHeightFt(building: Building, floorId: string) {
  const floor = building.floors.find(item => item.id === floorId)
  return (floor?.elevation_ft || 0) + (floor?.height_ft || 9) - groundElevationOf(building)
}
export function storeySlabThickness(building: Building, floor: Building['floors'][number]) {
  const below = building.floors.filter(item => item.elevation_ft < floor.elevation_ft).sort((a, b) => b.elevation_ft - a.elevation_ft)[0]
  return below ? Math.max(.32, floor.elevation_ft - below.elevation_ft - below.height_ft) : .32
}

/** Exterior massing stacked from grade. Pass throughFloorId to hide the roof and every storey above that cut. */
export function BuildingShell({ building, hideShell = false, selectedId = null, dragTarget = null, onSelect, throughFloorId, photoreal = true }: { building: Building; hideShell?: boolean; selectedId?: string | null; dragTarget?: string | null; onSelect: (id: string) => void; throughFloorId?: string | null; photoreal?: boolean }) {
  const ground = groundElevationOf(building)
  const topFloor = topFloorOf(building)
  const floors = floorsThrough(building, throughFloorId)
  const showRoof = !throughFloorId
  const vertices = useMemo(() => new Map(building.vertices.map(v => [v.id, v])), [building.vertices])
  return <>{floors.map(floor => {
    const floorRooms = building.rooms.filter(r => r.floor_id === floor.id)
    const floorWalls = building.walls.filter(w => w.floor_id === floor.id)
    const slabThickness = storeySlabThickness(building, floor)
    return <group key={floor.id} position={[0, floor.elevation_ft - ground, 0]}>
      {!hideShell && floorRooms.map(room => <group key={room.id}><FloorSlab polygon={room.polygon} y={-slabThickness} thickness={slabThickness} /><RoomFloor room={room} faded={dragTarget === room.id} selected={selectedId === room.id} onSelect={onSelect} /></group>)}
      {!hideShell && <Walls3D walls={floorWalls} vertices={vertices} openings={building.openings} selectedId={selectedId} dragTarget={dragTarget} onSelect={onSelect} photoreal={photoreal} />}
      {!hideShell && <FloorDressing walls={floorWalls} rooms={floorRooms} vertices={vertices} height={floor.height_ft} foundation={floor.elevation_ft === ground} />}
      {!hideShell && showRoof && floor.id === topFloor?.id && <ConceptRoof walls={floorWalls} rooms={floorRooms} vertices={vertices} height={floor.height_ft} />}
    </group>
  })}</>
}

export function Walls3D({ walls, vertices, openings, selectedId, dragTarget, onSelect, photoreal }: { walls: Wall[]; vertices: Vertices; openings: Building['openings']; selectedId: string | null; dragTarget: string | null; onSelect: (id: string) => void; photoreal: boolean }) {
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

function InstancedWalls({ walls, vertices, selectedId, dragTarget, onSelect, photoreal }: { walls: Wall[]; vertices: Vertices; selectedId: string | null; dragTarget: string | null; onSelect: (id: string) => void; photoreal: boolean }) {
  const groups = useMemo(() => {
    const map = new Map<string, Wall[]>()
    for (const wall of walls) {
      const id = wall.material || 'plaster'
      const list = map.get(id)
      if (list) list.push(wall)
      else map.set(id, [wall])
    }
    return [...map.entries()]
  }, [walls])
  return <>{groups.map(([material, group]) => <InstancedWallGroup key={material} walls={group} material={material} vertices={vertices} selectedId={selectedId} dragTarget={dragTarget} onSelect={onSelect} photoreal={photoreal} />)}</>
}

function InstancedWallGroup({ walls, material, vertices, selectedId, dragTarget, onSelect, photoreal }: { walls: Wall[]; material: string; vertices: Vertices; selectedId: string | null; dragTarget: string | null; onSelect: (id: string) => void; photoreal: boolean }) {
  const mesh = useRef<THREE.InstancedMesh>(null)
  const ids = useMemo(() => walls.map(w => w.id), [walls])
  const count = walls.length
  const baseColor = finishColor(material)
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
      color.set('#ffffff')
      if (selectedId === wall.id) color.lerp(highlight, .45)
      if (dragTarget === wall.id) color.multiplyScalar(.45)
      node.setColorAt(i, color)
    }
    node.instanceMatrix.needsUpdate = true
    if (node.instanceColor) node.instanceColor.needsUpdate = true
    node.userData = { kind: 'wall-instances', instanceIds: ids }
  }, [walls, vertices, selectedId, dragTarget, count, ids])
  if (!count) return null
  return <instancedMesh key={count} ref={mesh} args={[undefined, undefined, count]} castShadow receiveShadow frustumCulled={false} userData={{ kind: 'wall-instances', instanceIds: ids }} onClick={e => { e.stopPropagation(); const id = ids[e.instanceId ?? -1]; if (id) onSelect(id) }}>
    <boxGeometry args={[1, 1, 1]} />
    <SurfaceMaterial finish={material} color={baseColor} photoreal={photoreal} />
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
  const color = finishColor(wall.material)
  return <group position={[a.x, 0, a.y]} rotation={[0, -angle, 0]} userData={{ entityId: wall.id, kind: 'wall' }} onClick={e => { e.stopPropagation(); onSelect(wall.id) }}>
    {pieces.map((piece, i) => <mesh key={i} position={[piece.x, piece.y, 0]} castShadow receiveShadow><boxGeometry args={[piece.width, piece.height, wall.thickness_ft]} /><SurfaceMaterial finish={wall.material} color={color} faded={faded} selected={selected} photoreal={photoreal} /></mesh>)}
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

export function RoomFloor({ room, faded, selected, onSelect }: { room: Building['rooms'][number]; faded: boolean; selected: boolean; onSelect: (id: string) => void }) {
  const geometry = useMemo(() => { const shape = new THREE.Shape(); room.polygon.forEach(([x, y], i) => i === 0 ? shape.moveTo(x, -y) : shape.lineTo(x, -y)); shape.closePath(); return new THREE.ShapeGeometry(shape) }, [room.polygon])
  useEffect(() => () => geometry.dispose(), [geometry])
  return <mesh geometry={geometry} rotation={[-Math.PI / 2, 0, 0]} position={[0, .025, 0]} receiveShadow userData={{ entityId: room.id, kind: 'room' }} onClick={e => { e.stopPropagation(); onSelect(room.id) }}><SurfaceMaterial finish={room.floor_material || 'oak'} color={finishColor(room.floor_material || 'oak')} faded={faded} selected={selected} /></mesh>
}

function edgeCenter(a: Point, b: Point) {
  return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 }
}

export function ConceptRoof({ walls, rooms, vertices, height }: { walls: Wall[]; rooms: Building['rooms']; vertices: Map<string, Point>; height: number }) {
  const overhang = 2.35
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

export function FloorDressing({ walls, rooms, vertices, height, foundation }: { walls: Wall[]; rooms: Building['rooms']; vertices: Map<string, Point>; height: number; foundation: boolean }) {
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
        <boxGeometry args={[edge.length + 0.16, 1.35, wall.thickness_ft + 0.42]} />
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
