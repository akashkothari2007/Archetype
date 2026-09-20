import { useEffect, useMemo } from 'react'
import * as THREE from 'three'
import type { Building } from '../types'
import { floorWorldY } from './scene-building'
import { failHighlights, failPartFocused, rankFailRooms, roomLightPlacement, type CheckHit, type FailRoom, type FailBox, type FailVolume } from './compliance-scene'

const WASH = '#c91812'
const PART = '#b01410'

function overlayMaterial(opacity: number, emissive = 0.42) {
  return <meshStandardMaterial color={PART} transparent opacity={opacity} emissive={WASH} emissiveIntensity={emissive} roughness={.92} metalness={0} depthWrite={false} side={THREE.DoubleSide} polygonOffset polygonOffsetFactor={-2} />
}

function PolygonVolume({ polygon, y, height, opacity }: { polygon: number[][]; y: number; height: number; opacity: number }) {
  const geometry = useMemo(() => {
    if (polygon.length < 3) return null
    const shape = new THREE.Shape(polygon.map(([x, z]) => new THREE.Vector2(x, -z)))
    const extruded = new THREE.ExtrudeGeometry(shape, { depth: Math.max(.08, height), bevelEnabled: false, curveSegments: 1 })
    extruded.rotateX(-Math.PI / 2)
    return extruded
  }, [polygon, height])
  useEffect(() => () => { geometry?.dispose() }, [geometry])
  if (!geometry) return null
  return <mesh geometry={geometry} position={[0, y, 0]} renderOrder={8} raycast={() => {}}>{overlayMaterial(opacity)}</mesh>
}

function FailRoomLight({ room, elevation, focused }: { room: FailRoom; elevation: number; focused: boolean }) {
  const look = useMemo(() => roomLightPlacement(room), [room])
  const boost = focused ? 1.35 : 1
  return <group>
    <pointLight position={[look.x, elevation + look.ceiling, look.z]} color="#ff3328" intensity={look.intensity * 1.45 * boost} distance={look.distance} decay={2} />
    <pointLight position={[look.x, elevation + Math.min(5.2, room.height_ft * .55), look.z]} color="#ff5a48" intensity={look.intensity * .55 * boost} distance={look.distance * .85} decay={2} />
    <PolygonVolume polygon={room.polygon} y={elevation + .03} height={.14} opacity={focused ? .14 : .1} />
  </group>
}

function FailBoxMesh({ box, elevation, focused }: { box: FailBox; elevation: number; focused: boolean }) {
  return <mesh position={[box.x, elevation + box.localY, box.z]} rotation={[0, box.rotation, 0]} renderOrder={10} raycast={() => {}}>
    <boxGeometry args={box.size} />
    {overlayMaterial(focused ? .5 : .38, focused ? .62 : .48)}
  </mesh>
}

function FailVolumeMesh({ volume, elevation, focused }: { volume: FailVolume; elevation: number; focused: boolean }) {
  return <PolygonVolume polygon={volume.polygon} y={elevation + .03} height={volume.height_ft - .06} opacity={volume.kind === 'pinch' ? (focused ? .48 : .4) : (focused ? .34 : .26)} />
}

export function ComplianceFailFx({ building, checks = [], selectedId = null, floorIds }: { building: Building; checks?: CheckHit[]; selectedId?: string | null; floorIds: string[] }) {
  const hits = useMemo(() => failHighlights(building, checks), [building, checks])
  const lights = useMemo(() => rankFailRooms(hits.rooms, floorIds, selectedId), [hits.rooms, floorIds, selectedId])
  const visible = useMemo(() => new Set(floorIds), [floorIds])
  if (!hits.rooms.length && !hits.boxes.length && !hits.volumes.length) return null
  return <group userData={{ captureHide: true }}>
    {lights.map(room => <FailRoomLight key={room.id} room={room} elevation={floorWorldY(building, room.floor_id)} focused={room.id === selectedId} />)}
    {hits.boxes.filter(box => visible.has(box.floor_id)).map(box => (
      <FailBoxMesh key={box.id} box={box} elevation={floorWorldY(building, box.floor_id)} focused={failPartFocused(box.id, selectedId, checks)} />
    ))}
    {hits.volumes.filter(volume => visible.has(volume.floor_id)).map(volume => (
      <FailVolumeMesh key={volume.id} volume={volume} elevation={floorWorldY(building, volume.floor_id)} focused={failPartFocused(volume.id, selectedId, checks)} />
    ))}
  </group>
}
