import type { Building, ModelCommand } from '../types'
import furnitureCatalog from '../furniture-catalog.json'
import { surfacePreview, surfaces } from './material-catalog'

export type Point = { x: number; y: number }
export type EditorProps = {
  building: Building
  floorId: string
  onCommand: (commands: ModelCommand[]) => void
  selectedId: string | null
  onSelect: (id: string | null) => void
  units: 'metric' | 'imperial'
  busy?: boolean
  projectId?: string
  onFloor?: (id: string) => void
}
export const assetMime = 'application/archetype-asset'
export type Asset = { id: string; label: string; kind: 'fixture' | 'furniture' | 'door' | 'window' | 'material'; width: number; depth: number; height: number; preview?: string; model?: string; color?: string }
export const fixtures: Asset[] = [
  { id: 'door', label: 'Swing door', kind: 'door', width: 3, depth: .25, height: 7 },
  { id: 'window', label: 'Window', kind: 'window', width: 4, depth: .25, height: 4 },
  { id: 'toilet', label: 'Toilet', kind: 'fixture', width: 1.7, depth: 2.5, height: 2.5 },
  { id: 'sink', label: 'Basin', kind: 'fixture', width: 2, depth: 1.6, height: 2.8 },
  { id: 'bath', label: 'Bathtub', kind: 'fixture', width: 2.5, depth: 5.5, height: 1.8 },
  { id: 'closet', label: 'Closet', kind: 'fixture', width: 5, depth: 2, height: 8 },
  { id: 'counter', label: 'Counter', kind: 'fixture', width: 5, depth: 2, height: 3 },
  { id: 'shower', label: 'Shower', kind: 'fixture', width: 3, depth: 3, height: .3 },
]
export const furniture: Asset[] = furnitureCatalog.map(a => ({
  id: a.id,
  label: a.label,
  kind: 'furniture' as const,
  width: a.width,
  depth: a.depth,
  height: a.height,
  preview: `assets/${a.id}/preview.png`,
  model: `assets/${a.id}/${a.id}.gltf`,
}))
export function catalogAsset(id?: string | null): Asset | undefined {
  if (!id) return undefined
  return furniture.find(item => item.id === id) || fixtures.find(item => item.id === id)
}

export const materials: Asset[] = surfaces.map(surface => ({
  id: surface.id,
  label: surface.label,
  kind: 'material' as const,
  width: 0,
  depth: 0,
  height: 0,
  color: surface.color,
  preview: surface.tint ? undefined : surfacePreview(surface),
}))
export const distance = (a: Point, b: Point) => Math.hypot(a.x - b.x, a.y - b.y)
export function projectPoint(p: Point, a: Point, b: Point) {
  const length = distance(a, b)
  const t = length ? Math.max(0, Math.min(1, ((p.x - a.x) * (b.x - a.x) + (p.y - a.y) * (b.y - a.y)) / length ** 2)) : 0
  const point = { x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t }
  return { ...point, t, distance: distance(p, point), offset: t * length, length }
}
export function pointInPolygon(p: Point, polygon: number[][]) {
  let inside = false
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const [xi, yi] = polygon[i], [xj, yj] = polygon[j]
    if ((yi > p.y) !== (yj > p.y) && p.x < (xj - xi) * (p.y - yi) / (yj - yi) + xi) inside = !inside
  }
  return inside
}
export function polygonArea(polygon: number[][]) {
  return Math.abs(polygon.reduce((s, a, i) => { const b = polygon[(i + 1) % polygon.length]; return s + a[0] * b[1] - b[0] * a[1] }, 0)) / 2
}
export function interiorPoint(polygon: number[][]): Point {
  if (!polygon.length) return { x: 0, y: 0 }
  const average = { x: polygon.reduce((s, p) => s + p[0], 0) / polygon.length, y: polygon.reduce((s, p) => s + p[1], 0) / polygon.length }
  if (pointInPolygon(average, polygon)) return average
  const minX = Math.min(...polygon.map(p => p[0])), maxX = Math.max(...polygon.map(p => p[0]))
  const minY = Math.min(...polygon.map(p => p[1])), maxY = Math.max(...polygon.map(p => p[1]))
  let best = average, clearance = -1
  for (let x = 1; x < 20; x++) for (let y = 1; y < 20; y++) {
    const p = { x: minX + (maxX - minX) * x / 20, y: minY + (maxY - minY) * y / 20 }
    if (!pointInPolygon(p, polygon)) continue
    const edge = Math.min(...polygon.map((a, i) => { const b = polygon[(i + 1) % polygon.length]; return projectPoint(p, { x: a[0], y: a[1] }, { x: b[0], y: b[1] }).distance }))
    if (edge > clearance) { best = p; clearance = edge }
  }
  return best
}

export function roomLookYaw(polygon: number[][], from: Point) {
  const n = polygon.length
  if (n < 2) return Math.PI
  const cx = polygon.reduce((s, p) => s + p[0], 0) / n, cy = polygon.reduce((s, p) => s + p[1], 0) / n
  let xx = 0, xy = 0, yy = 0
  for (const [x, y] of polygon) { const dx = x - cx, dy = y - cy; xx += dx * dx; xy += dx * dy; yy += dy * dy }
  const axis = .5 * Math.atan2(2 * xy, xx - yy)
  const yawOf = (dir: number) => Math.atan2(-Math.cos(dir), -Math.sin(dir))
  const clearance = (yaw: number) => {
    const dx = -Math.sin(yaw), dy = -Math.cos(yaw)
    let dist = 0
    for (let t = .25; t <= 80; t += .25) {
      if (!pointInPolygon({ x: from.x + dx * t, y: from.y + dy * t }, polygon)) break
      dist = t
    }
    return dist
  }
  const a = yawOf(axis), b = yawOf(axis + Math.PI)
  return clearance(a) >= clearance(b) ? a : b
}
export function wallExterior(a: Point, b: Point, rooms: { polygon: number[][] }[]) {
  const length = Math.hypot(b.x - a.x, b.y - a.y)
  if (length < 0.01 || !rooms.length) return null
  const nx = -(b.y - a.y) / length, ny = (b.x - a.x) / length
  const center = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 }
  const sideOf = (p: Point) => (p.x - center.x) * nx + (p.y - center.y) * ny
  let hasA = false, hasB = false
  for (const room of rooms) {
    const inside = (sign: number, dist: number) => pointInPolygon({ x: center.x + nx * sign * dist, y: center.y + ny * sign * dist }, room.polygon)
    if ([0.35, 1.1, 2.4].some(dist => inside(1, dist))) hasA = true
    if ([0.35, 1.1, 2.4].some(dist => inside(-1, dist))) hasB = true
    if (hasA && hasB) break
    const centroid = interiorPoint(room.polygon)
    const along = projectPoint(centroid, a, b)
    if (along.distance > Math.max(8, length)) continue
    const side = sideOf(centroid)
    if (side > 0.15) hasA = true
    if (side < -0.15) hasB = true
  }
  if (hasA === hasB) return null
  const sign = hasA ? -1 : 1
  return { length, center, angle: Math.atan2(b.y - a.y, b.x - a.x), sign, outward: { x: nx * sign, y: ny * sign } }
}

export function floorsBounds(building: Building, floorIds: string[]) {
  const ids = new Set(floorIds)
  const points = building.vertices.filter(v => ids.has(v.floor_id))
  if (!points.length) return { minX: 0, maxX: 40, minY: 0, maxY: 30, width: 40, height: 30, cx: 20, cy: 15 }
  const minX = Math.min(...points.map(p => p.x)), maxX = Math.max(...points.map(p => p.x))
  const minY = Math.min(...points.map(p => p.y)), maxY = Math.max(...points.map(p => p.y))
  return { minX, maxX, minY, maxY, width: Math.max(1, maxX - minX), height: Math.max(1, maxY - minY), cx: (minX + maxX) / 2, cy: (minY + maxY) / 2 }
}
export function floorBounds(building: Building, floorId: string) {
  return floorsBounds(building, [floorId])
}
export function lengthLabel(ft: number, units: 'metric' | 'imperial') {
  if (units === 'metric') return `${(ft * .3048).toFixed(2)} m`
  const inches = Math.round(ft * 12)
  return `${Math.floor(inches / 12)}′ ${inches % 12}″`
}
export function nearestWall(building: Building, floorId: string, p: Point) {
  const vertices = new Map(building.vertices.map(v => [v.id, v]))
  return building.walls.filter(w => w.floor_id === floorId).flatMap(w => {
    const a = vertices.get(w.start_id), b = vertices.get(w.end_id)
    return a && b ? [{ wall: w, ...projectPoint(p, a, b) }] : []
  }).sort((a, b) => a.distance - b.distance)[0]
}
export function placementCommand(asset: Asset, p: Point, building: Building, floorId: string): ModelCommand | null {
  if (asset.kind === 'material') return null
  if (asset.kind === 'door' || asset.kind === 'window') {
    const nearest = nearestWall(building, floorId, p)
    if (!nearest || nearest.distance > 3 || nearest.length < asset.width) return null
    return { kind: 'place_opening', target_id: '', params: { wall_id: nearest.wall.id, kind: asset.kind, offset_ft: Math.max(0, Math.min(nearest.length - asset.width, nearest.offset - asset.width / 2)), width_ft: asset.width, height_ft: asset.height, sill_ft: asset.kind === 'window' ? 3 : 0 } }
  }
  return { kind: 'place_object', target_id: '', params: { floor_id: floorId, asset_id: asset.id, kind: asset.kind, x: p.x, y: p.y, rotation_deg: 0, width_ft: asset.width, depth_ft: asset.depth, height_ft: asset.height } }
}

export function isTypingTarget(target: EventTarget | null) {
  if (!(target instanceof HTMLElement)) return false
  const tag = target.tagName
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || target.isContentEditable
}
