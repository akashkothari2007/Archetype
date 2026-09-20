import { describe, expect, it } from 'vitest'
import type { Building } from '../types'
import { fixtures, floorBounds, interiorPoint, lengthLabel, placementCommand, pointInPolygon, polygonArea, projectPoint, roomLookYaw } from './editor-geometry'

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
})
