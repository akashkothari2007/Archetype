import { describe, expect, it } from 'vitest'
import type { Building } from '../types'
import { catalogAsset, fixtures, floorBounds, floorsBounds, furniture, interiorPoint, lengthLabel, materials, placementCommand, pointInPolygon, polygonArea, projectPoint, roomLookYaw } from './editor-geometry'

const model: Building = {
  schema_version: 2, units: 'feet',
  floors: [{ id: 'f1', name: 'Ground', elevation_ft: 0, height_ft: 9 }],
  vertices: [{ id: 'a', floor_id: 'f1', x: 0, y: 0 }, { id: 'b', floor_id: 'f1', x: 10, y: 0 }],
  walls: [{ id: 'w', floor_id: 'f1', start_id: 'a', end_id: 'b', thickness_ft: .5, height_ft: 9, locked: false, structural: 'nonstructural', material: 'plaster', confidence: 1, source: { document_id: '', sheet_id: '', page: null, method: 'user', assumed: false } }],
  openings: [], rooms: [], objects: [], type_catalogue: [], environment: { time: 14, sun_azimuth: 135, season: 'summer' },
  site: { lat: null, lon: null, rotation_deg: 0, ground_offset_ft: 0, address: '' }, review: [],
}

describe('floor geometry and asset placement', () => {
  it('places openings by their start offset and clamps them to the host wall', () => {
    const door = fixtures.find(a => a.id === 'door')!
    expect(placementCommand(door, { x: 5, y: .3 }, model, 'f1')?.params).toMatchObject({ wall_id: 'w', offset_ft: 3.5, width_ft: 3 })
    expect(placementCommand(door, { x: 9.9, y: 0 }, model, 'f1')?.params?.offset_ft).toBe(7)
    expect(placementCommand(door, { x: -.2, y: 0 }, model, 'f1')?.params?.offset_ft).toBe(0)
  })
  it('does not attach an opening to a remote wall or another floor', () => {
    const door = fixtures[0]
    expect(placementCommand(door, { x: 4, y: 7 }, model, 'f1')).toBeNull()
    expect(placementCommand(door, { x: 4, y: 0 }, model, 'f2')).toBeNull()
  })
  it('keeps object dimensions and positions in canonical feet', () => {
    const bath = fixtures.find(a => a.id === 'bath')!
    expect(placementCommand(bath, { x: 4.5, y: 2 }, model, 'f1')).toMatchObject({ kind: 'place_object', params: { asset_id: 'bath', floor_id: 'f1', x: 4.5, y: 2, width_ft: 2.5, depth_ft: 5.5 } })
  })
  it('exposes a full default furniture catalog with 3D models', () => {
    expect(furniture.length).toBeGreaterThan(20)
    expect(furniture.some(item => item.id === 'sofa_02' && item.model?.endsWith('.gltf'))).toBe(true)
    expect(furniture.some(item => item.id === 'GothicBed_01')).toBe(true)
    expect(furniture.some(item => item.id === 'dining_table')).toBe(true)
    expect(catalogAsset('sofa_02')).toMatchObject({label: 'Leather sofa', preview: 'assets/sofa_02/preview.png'})
    expect(catalogAsset('bath')?.label).toBe('Bathtub')
  })
  it('lists painted and textured finishes in the materials library', () => {
    expect(materials.some(item => item.id === 'plaster' && item.color === '#f3efe7')).toBe(true)
    expect(materials.some(item => item.id === 'brick' && item.preview?.includes('brick_wall_001'))).toBe(true)
    expect(materials.some(item => item.id === 'marble' && item.preview?.includes('marble_01'))).toBe(true)
    expect(materials.some(item => item.id === 'herringbone' && item.preview?.includes('herringbone_parquet'))).toBe(true)
    expect(materials.length).toBeGreaterThan(12)
  })
  it('finds an interior teleport point even for a deeply concave room', () => {
    const polygon = [[0, 0], [10, 0], [10, 2], [2, 2], [2, 10], [0, 10]]
    const point = interiorPoint(polygon)
    expect(pointInPolygon(point, polygon)).toBe(true)
    expect(polygonArea(polygon)).toBe(36)
  })
  it('aims the walk camera down the long axis of a room', () => {
    const wide = roomLookYaw([[0, 0], [20, 0], [20, 6], [0, 6]], { x: 10, y: 3 })
    expect(Math.abs(Math.cos(wide))).toBeLessThan(.2)
    expect(Math.abs(Math.sin(wide))).toBeGreaterThan(.9)
    const deep = roomLookYaw([[0, 0], [6, 0], [6, 20], [0, 20]], { x: 3, y: 10 })
    expect(Math.abs(Math.sin(deep))).toBeLessThan(.2)
    expect(Math.abs(Math.cos(deep))).toBeGreaterThan(.9)
  })
  it('projects onto a rotated wall and gives the same distance from either endpoint order', () => {
    const p = { x: 4, y: 0 }, a = { x: 0, y: 0 }, b = { x: 6, y: 6 }
    const projected = projectPoint(p, a, b)
    expect(projected.x).toBeCloseTo(2)
    expect(projected.y).toBeCloseTo(2)
    expect(projected.offset).toBeCloseTo(Math.sqrt(8))
    expect(projectPoint(p, b, a).distance).toBeCloseTo(projected.distance)
  })
  it('handles empty floors and imperial rounding without 12-inch overflow', () => {
    expect(floorBounds(model, 'missing').width).toBe(40)
    expect(lengthLabel(2.9999, 'imperial')).toBe('3′ 0″')
    expect(lengthLabel(10, 'metric')).toBe('3.05 m')
  })
  it('frames every stacked storey, not only the active floor', () => {
    const stacked = {
      ...model,
      floors: [...model.floors, { id: 'f2', name: 'Upper', elevation_ft: 10, height_ft: 9 }],
      vertices: [...model.vertices, { id: 'c', floor_id: 'f2', x: 40, y: 30 }],
    }
    expect(floorsBounds(stacked, ['f1', 'f2'])).toMatchObject({ minX: 0, maxX: 40, minY: 0, maxY: 30, width: 40, height: 30 })
  })
})
