import { describe, expect, it } from 'vitest'
import type { Building } from '../types'
import { formatPlanSvg, schematicExportFilename } from './plan-export'

const source = { document_id: '', sheet_id: '', page: null, method: 'user', assumed: false as const }
const model: Building = {
  schema_version: 2,
  units: 'feet',
  floors: [{ id: 'f1', name: 'Ground', elevation_ft: 0, height_ft: 9 }],
  vertices: [
    { id: 'a', floor_id: 'f1', x: 0, y: 0 },
    { id: 'b', floor_id: 'f1', x: 10, y: 0 },
    { id: 'c', floor_id: 'f1', x: 10, y: 8 },
    { id: 'd', floor_id: 'f1', x: 0, y: 8 },
  ],
  walls: [
    { id: 'ab', floor_id: 'f1', start_id: 'a', end_id: 'b', thickness_ft: 0.5, height_ft: 9, locked: false, structural: 'loadbearing', material: 'plaster', confidence: 1, source },
    { id: 'bc', floor_id: 'f1', start_id: 'b', end_id: 'c', thickness_ft: 0.5, height_ft: 9, locked: false, structural: 'loadbearing', material: 'plaster', confidence: 1, source },
    { id: 'cd', floor_id: 'f1', start_id: 'c', end_id: 'd', thickness_ft: 0.5, height_ft: 9, locked: false, structural: 'loadbearing', material: 'plaster', confidence: 1, source },
    { id: 'da', floor_id: 'f1', start_id: 'd', end_id: 'a', thickness_ft: 0.5, height_ft: 9, locked: false, structural: 'loadbearing', material: 'plaster', confidence: 1, source },
  ],
  openings: [
    { id: 'door', wall_id: 'ab', kind: 'door', offset_ft: 3.5, width_ft: 3, height_ft: 7, sill_ft: 0, hinge: 'left', swing: 'in', clear_width_ft: 2.8, reliability: 'ok', reliability_reason: '', source },
    { id: 'window', wall_id: 'cd', kind: 'window', offset_ft: 3, width_ft: 4, height_ft: 4, sill_ft: 3, hinge: 'left', swing: 'in', clear_width_ft: null, reliability: 'ok', reliability_reason: '', source },
  ],
  rooms: [{
    id: 'kitchen', floor_id: 'f1', name: 'Kitchen', category: 'kitchen', type_ref: 'kitchen',
    polygon: [[0, 0], [10, 0], [10, 8], [0, 8]], wall_ids: ['ab', 'bc', 'cd', 'da'],
    floor_material: 'tile', confidence: 1, needs_review: false, instance_count: 1, parent_room_id: '',
    reliability: 'ok', reliability_reason: '', source,
  }],
  objects: [{ id: 'sofa', floor_id: 'f1', asset_id: 'sofa_02', kind: 'furniture', x: 5, y: 4, rotation_deg: 90, width_ft: 7, depth_ft: 3.2, height_ft: 2.7, splat: '' }],
  type_catalogue: [],
  environment: { time: 14, sun_azimuth: 135, season: 'summer' },
  site: { lat: null, lon: null, rotation_deg: 0, ground_offset_ft: 0, address: '' },
  review: [],
}

describe('plan schematic export', () => {
  it('names the file from the project, floor, and date', () => {
    expect(schematicExportFilename('Willow House', 'Ground floor', new Date('2026-09-20T12:00:00Z'))).toBe('archetype-plan-willow-house-ground-floor-2026-09-20.svg')
  })

  it('writes an SVG schematic with rooms, walls, openings, and objects', () => {
    const svg = formatPlanSvg({
      building: model,
      floorId: 'f1',
      units: 'imperial',
      projectName: 'Willow House',
      exportedAt: new Date('2026-09-20T12:00:00Z'),
    })
    expect(svg).toContain('<svg xmlns="http://www.w3.org/2000/svg"')
    expect(svg).toContain('viewBox="-2 -2 14 15.6"')
    expect(svg).toContain('KITCHEN')
    expect(svg).toContain('80.0 sq ft')
    expect(svg).toContain('id="walls"')
    expect(svg).toContain('id="openings"')
    expect(svg).toContain('id="objects"')
    expect(svg).toContain('A 3 3 0 0 1 0 3')
    expect(svg).toContain('rotate(90')
    expect(svg).toContain('Willow House · Ground')
    expect(svg).toContain('1 drawing unit = 1 ft')
  })

  it('omits other floors and uses metric room labels', () => {
    const svg = formatPlanSvg({ building: model, floorId: 'missing', units: 'metric', projectName: 'A & B' })
    expect(svg).toContain('A &amp; B')
    expect(svg).not.toContain('KITCHEN')
    expect(svg).toContain('labels in metres')
  })
})
