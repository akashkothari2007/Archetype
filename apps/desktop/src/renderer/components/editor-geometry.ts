import type { Building, ModelCommand } from '../types'

export type Point = { x: number; y: number }
export type EditorProps = {
  building: Building
  floorId: string
  onCommand: (commands: ModelCommand[]) => void
  selectedId: string | null
  onSelect: (id: string | null) => void
  units: 'metric' | 'imperial'
  busy?: boolean
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
export const furniture: Asset[] = [
  { id: 'sofa_02', label: 'Leather sofa', kind: 'furniture', width: 7, depth: 3.2, height: 2.7 },
  { id: 'modern_arm_chair_01', label: 'Lounge chair', kind: 'furniture', width: 2.8, depth: 3, height: 2.9 },
  { id: 'modern_coffee_table_01', label: 'Coffee table', kind: 'furniture', width: 3.8, depth: 2, height: 1.5 },
].map(a => ({ ...a, kind: 'furniture' as const, preview: `assets/${a.id}/preview.png`, model: `assets/${a.id}/${a.id}.gltf` }))
export const materials: Asset[] = [
  { id: 'plaster', label: 'Chalk white', color: '#f3efe7' }, { id: 'sage', label: 'Soft sage', color: '#a7b09d' },
  { id: 'clay', label: 'Warm clay', color: '#c7a28f' }, { id: 'slate', label: 'Slate', color: '#535d63' },
  { id: 'oak', label: 'Natural oak', color: '#c7aa7f' }, { id: 'walnut', label: 'Walnut', color: '#7f593e' },
  { id: 'tile', label: 'Limestone', color: '#d5d0c3' }, { id: 'concrete', label: 'Concrete', color: '#a8a8a2' },
].map(a => ({ ...a, kind: 'material' as const, width: 0, depth: 0, height: 0 }))
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
export function floorBounds(building: Building, floorId: string) {
  const points = building.vertices.filter(v => v.floor_id === floorId)
  if (!points.length) return { minX: 0, maxX: 40, minY: 0, maxY: 30, width: 40, height: 30, cx: 20, cy: 15 }
  const minX = Math.min(...points.map(p => p.x)), maxX = Math.max(...points.map(p => p.x))
  const minY = Math.min(...points.map(p => p.y)), maxY = Math.max(...points.map(p => p.y))
  return { minX, maxX, minY, maxY, width: Math.max(1, maxX - minX), height: Math.max(1, maxY - minY), cx: (minX + maxX) / 2, cy: (minY + maxY) / 2 }
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
