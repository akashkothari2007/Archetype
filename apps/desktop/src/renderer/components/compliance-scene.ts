import type { Building, Check } from '../types'
import { interiorPoint, pointInPolygon, polygonArea, type Point } from './editor-geometry'

export type CheckHit = Check & {
  type_ref?: string
  instances_affected?: number
  affected_space_ids?: string[]
  contributing_room_ids?: string[]
  pinch_polygon?: number[][] | null
}

export type FailRoom = {
  id: string
  floor_id: string
  polygon: number[][]
  height_ft: number
  area: number
}

export type FailBox = {
  id: string
  kind: 'opening' | 'wall' | 'object'
  floor_id: string
  x: number
  z: number
  localY: number
  rotation: number
  size: [number, number, number]
}

export type FailVolume = {
  id: string
  kind: 'room' | 'pinch'
  floor_id: string
  polygon: number[][]
  height_ft: number
}

export type FailHighlights = {
  rooms: FailRoom[]
  boxes: FailBox[]
  volumes: FailVolume[]
}

const MAX_LIGHTS = 8

function listedIds(check: CheckHit) {
  return [...(check.entity_ids || []), check.entity_id].filter(Boolean)
}

function spaceIds(check: CheckHit) {
  return [...(check.affected_space_ids || []), ...(check.contributing_room_ids || [])].filter(Boolean)
}

function floorHeight(building: Building, floorId: string) {
  return building.floors.find(floor => floor.id === floorId)?.height_ft || 9
}

function roomsForOpening(building: Building, wallId: string) {
  return building.rooms.filter(room => room.wall_ids?.includes(wallId))
}

function roomAtPoint(building: Building, floorId: string, point: Point) {
  return building.rooms.find(room => room.floor_id === floorId && pointInPolygon(point, room.polygon))
}

function failChecks(checks: CheckHit[] | undefined) {
  return (checks || []).filter(check => check.status === 'fail')
}

function collectFailRooms(building: Building, checks: CheckHit[]) {
  const rooms = new Map<string, FailRoom>()
  const add = (id: string | undefined) => {
    const room = id ? building.rooms.find(item => item.id === id) : undefined
    if (!room?.polygon || room.polygon.length < 3 || rooms.has(room.id)) return
    rooms.set(room.id, {
      id: room.id,
      floor_id: room.floor_id,
      polygon: room.polygon,
      height_ft: floorHeight(building, room.floor_id),
      area: polygonArea(room.polygon),
    })
  }
  for (const check of checks) {
    for (const id of spaceIds(check)) add(id)
    if (check.type_ref) for (const room of building.rooms) if (room.type_ref === check.type_ref) add(room.id)
    for (const id of listedIds(check)) {
      add(id)
      const opening = building.openings.find(item => item.id === id)
      if (opening) for (const room of roomsForOpening(building, opening.wall_id)) add(room.id)
      const wall = building.walls.find(item => item.id === id)
      if (wall) for (const room of roomsForOpening(building, wall.id)) add(room.id)
      const object = building.objects.find(item => item.id === id)
      if (object) add(roomAtPoint(building, object.floor_id, { x: object.x, y: object.y })?.id)
    }
  }
  return [...rooms.values()]
}

function openingBox(building: Building, opening: Building['openings'][number]): FailBox | null {
  const wall = building.walls.find(item => item.id === opening.wall_id)
  const a = wall && building.vertices.find(item => item.id === wall.start_id)
  const b = wall && building.vertices.find(item => item.id === wall.end_id)
  if (!wall || !a || !b) return null
  const angle = Math.atan2(b.y - a.y, b.x - a.x)
  const mid = opening.offset_ft + opening.width_ft / 2
  return {
    id: opening.id,
    kind: 'opening',
    floor_id: wall.floor_id,
    x: a.x + Math.cos(angle) * mid,
    z: a.y + Math.sin(angle) * mid,
    localY: opening.sill_ft + opening.height_ft / 2,
    rotation: -angle,
    size: [Math.max(.3, opening.width_ft + .16), Math.max(.3, opening.height_ft + .16), Math.max(.22, wall.thickness_ft + .22)],
  }
}

function wallBox(building: Building, wall: Building['walls'][number]): FailBox | null {
  const a = building.vertices.find(item => item.id === wall.start_id)
  const b = building.vertices.find(item => item.id === wall.end_id)
  if (!a || !b) return null
  const length = Math.hypot(b.x - a.x, b.y - a.y)
  if (length < .05) return null
  return {
    id: wall.id,
    kind: 'wall',
    floor_id: wall.floor_id,
    x: (a.x + b.x) / 2,
    z: (a.y + b.y) / 2,
    localY: wall.height_ft / 2,
    rotation: -Math.atan2(b.y - a.y, b.x - a.x),
    size: [length + .1, wall.height_ft + .1, Math.max(.22, wall.thickness_ft + .18)],
  }
}

function objectBox(object: Building['objects'][number]): FailBox {
  return {
    id: object.id,
    kind: 'object',
    floor_id: object.floor_id,
    x: object.x,
    z: object.y,
    localY: object.height_ft / 2,
    rotation: -object.rotation_deg * Math.PI / 180,
    size: [object.width_ft * 1.06, object.height_ft * 1.06, object.depth_ft * 1.06],
  }
}

function collectFailParts(building: Building, checks: CheckHit[], rooms: FailRoom[]) {
  const boxes = new Map<string, FailBox>()
  const volumes = new Map<string, FailVolume>()
  const addBox = (box: FailBox | null) => { if (box && !boxes.has(box.id)) boxes.set(box.id, box) }
  const addVolume = (volume: FailVolume) => { if (volume.polygon.length >= 3 && !volumes.has(volume.id)) volumes.set(volume.id, volume) }
  for (const check of checks) {
    const pinch = check.pinch_polygon
    const roomFromPinch = pinch && rooms.find(room => spaceIds(check).includes(room.id) || listedIds(check).includes(room.id))
    if (pinch && roomFromPinch) {
      addVolume({ id: `${check.id}-pinch`, kind: 'pinch', floor_id: roomFromPinch.floor_id, polygon: pinch, height_ft: Math.min(4.2, roomFromPinch.height_ft * .55) })
      continue
    }
    let specific = false
    for (const id of listedIds(check)) {
      const opening = building.openings.find(item => item.id === id)
      if (opening) { addBox(openingBox(building, opening)); specific = true; continue }
      const wall = building.walls.find(item => item.id === id)
      if (wall) { addBox(wallBox(building, wall)); specific = true; continue }
      const object = building.objects.find(item => item.id === id)
      if (object) { addBox(objectBox(object)); specific = true; continue }
      const room = rooms.find(item => item.id === id)
      if (room) { addVolume({ id: room.id, kind: 'room', floor_id: room.floor_id, polygon: room.polygon, height_ft: room.height_ft }); specific = true }
    }
    if (!specific) for (const room of rooms.filter(item => spaceIds(check).includes(item.id) || (check.type_ref && building.rooms.some(r => r.id === item.id && r.type_ref === check.type_ref)))) {
      addVolume({ id: room.id, kind: 'room', floor_id: room.floor_id, polygon: room.polygon, height_ft: room.height_ft })
    }
  }
  return { boxes: [...boxes.values()], volumes: [...volumes.values()] }
}

export function failHighlights(building: Building, checks?: CheckHit[]): FailHighlights {
  const failed = failChecks(checks)
  if (!failed.length) return { rooms: [], boxes: [], volumes: [] }
  const rooms = collectFailRooms(building, failed)
  const parts = collectFailParts(building, failed, rooms)
  return { rooms, boxes: parts.boxes, volumes: parts.volumes }
}

export function rankFailRooms(rooms: FailRoom[], floorIds: string[], selectedId: string | null) {
  const visible = new Set(floorIds)
  const onFloor = rooms.filter(room => visible.has(room.floor_id))
  const ranked = [...onFloor].sort((a, b) => {
    const selected = Number(a.id === selectedId) - Number(b.id === selectedId)
    if (selected) return -selected
    const floor = floorIds.indexOf(a.floor_id) - floorIds.indexOf(b.floor_id)
    if (floor) return floor
    return b.area - a.area
  })
  return ranked.slice(0, MAX_LIGHTS)
}

export function failPartFocused(partId: string, selectedId: string | null, checks?: CheckHit[]) {
  if (!selectedId) return false
  if (partId === selectedId) return true
  return failChecks(checks).some(check => listedIds(check).includes(selectedId) && (listedIds(check).includes(partId) || spaceIds(check).includes(partId) || partId.startsWith(`${check.id}-`)))
}

export function roomLightPlacement(room: FailRoom) {
  const center = interiorPoint(room.polygon)
  const span = Math.sqrt(Math.max(room.area, 1))
  return {
    x: center.x,
    z: center.y,
    span,
    ceiling: Math.max(room.height_ft * .84, 6.4),
    distance: Math.max(span * 1.7, 9),
    intensity: 12 + Math.min(span, 16) * 1.15,
  }
}
