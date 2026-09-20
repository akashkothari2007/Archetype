import { describe, expect, it } from 'vitest'
import type { Building } from '../types'
import { failHighlights, failPartFocused, rankFailRooms, roomLightPlacement, type CheckHit } from './compliance-scene'

const source = { document_id: '', sheet_id: '', page: null, method: 'user' as const, assumed: false as const }
const building: Building = {
  schema_version: 2, units: 'feet',
  floors: [
    { id: 'f1', name: 'Ground', elevation_ft: 0, height_ft: 9 },
    { id: 'f2', name: 'Upper', elevation_ft: 10, height_ft: 9 },
  ],
  vertices: [
    { id: 'a', floor_id: 'f1', x: 0, y: 0 }, { id: 'b', floor_id: 'f1', x: 12, y: 0 },
    { id: 'c', floor_id: 'f1', x: 12, y: 10 }, { id: 'd', floor_id: 'f1', x: 0, y: 10 },
  ],
  walls: [
    { id: 'ab', floor_id: 'f1', start_id: 'a', end_id: 'b', thickness_ft: .5, height_ft: 9, locked: false, structural: 'nonstructural', material: 'plaster', confidence: 1, source },
    { id: 'bc', floor_id: 'f1', start_id: 'b', end_id: 'c', thickness_ft: .5, height_ft: 9, locked: false, structural: 'nonstructural', material: 'plaster', confidence: 1, source },
  ],
  openings: [{ id: 'door', wall_id: 'ab', kind: 'door', offset_ft: 4, width_ft: 2.4, height_ft: 7, sill_ft: 0, hinge: 'left', swing: 'in', clear_width_ft: 2.2, reliability: 'ok', reliability_reason: '', source }],
  rooms: [
    { id: 'kitchen', floor_id: 'f1', name: 'Kitchen', category: 'kitchen', type_ref: 'kitchen', polygon: [[0, 0], [12, 0], [12, 10], [0, 10]], wall_ids: ['ab', 'bc'], floor_material: 'oak', confidence: 1, needs_review: false, instance_count: 1, parent_room_id: '', reliability: 'ok', reliability_reason: '', source },
    { id: 'kitchen-2', floor_id: 'f2', name: 'Kitchen 2', category: 'kitchen', type_ref: 'kitchen', polygon: [[0, 0], [8, 0], [8, 8], [0, 8]], wall_ids: [], floor_material: 'oak', confidence: 1, needs_review: false, instance_count: 1, parent_room_id: '', reliability: 'ok', reliability_reason: '', source },
  ],
  objects: [{ id: 'sofa', floor_id: 'f1', asset_id: 'sofa_02', kind: 'furniture', x: 6, y: 5, rotation_deg: 90, width_ft: 7, depth_ft: 3, height_ft: 2.7, splat: '' }],
  type_catalogue: [],
  environment: { time: 14, sun_azimuth: 135, season: 'summer' },
  site: { lat: null, lon: null, rotation_deg: 0, ground_offset_ft: 0, address: '' },
  review: [],
}

function check(partial: Partial<CheckHit> & Pick<CheckHit, 'id' | 'entity_id' | 'status'>): CheckHit {
  return {
    rule_id: 'r1', entity_ids: [partial.entity_id], metric: 'area', actual: 1, required: 4, unit: 'm2',
    message: 'too small', source_doc: '', source_text: '', ...partial,
  }
}

describe('compliance fail scene', () => {
  it('ignores passing checks', () => {
    expect(failHighlights(building, [check({ id: 'ok', entity_id: 'kitchen', status: 'pass' })])).toEqual({ rooms: [], boxes: [], volumes: [] })
  })

  it('washes a failed room and overlays the room volume when the room itself failed', () => {
    const hits = failHighlights(building, [check({ id: 'area', entity_id: 'kitchen', status: 'fail', affected_space_ids: ['kitchen'] })])
    expect(hits.rooms.map(room => room.id)).toEqual(['kitchen'])
    expect(hits.volumes).toMatchObject([{ id: 'kitchen', kind: 'room', floor_id: 'f1' }])
    expect(hits.boxes).toEqual([])
    const light = roomLightPlacement(hits.rooms[0])
    expect(light.x).toBeGreaterThan(0)
    expect(light.z).toBeGreaterThan(0)
    expect(light.intensity).toBeGreaterThan(10)
  })

  it('lights the host room and highlights the door when an opening fails', () => {
    const hits = failHighlights(building, [check({ id: 'door-w', entity_id: 'door', status: 'fail', metric: 'aperture_width', affected_space_ids: ['kitchen'] })])
    expect(hits.rooms.map(room => room.id)).toEqual(['kitchen'])
    expect(hits.boxes).toMatchObject([{ id: 'door', kind: 'opening', floor_id: 'f1' }])
    expect(hits.boxes[0].size[0]).toBeGreaterThan(2.4)
    expect(hits.volumes).toEqual([])
  })

  it('highlights the pinch volume instead of the whole room when min-side geometry is present', () => {
    const pinch = [[4, 3], [8, 3], [8, 4], [4, 4]]
    const hits = failHighlights(building, [check({ id: 'pinch', entity_id: 'kitchen', status: 'fail', metric: 'min_side', affected_space_ids: ['kitchen'], pinch_polygon: pinch })])
    expect(hits.rooms.map(room => room.id)).toEqual(['kitchen'])
    expect(hits.volumes).toMatchObject([{ kind: 'pinch', polygon: pinch }])
    expect(hits.volumes[0].height_ft).toBeLessThan(9)
  })

  it('lights every room of a failed type and overlays furniture when that object failed', () => {
    const hits = failHighlights(building, [check({ id: 'obj', entity_id: 'sofa', status: 'fail', type_ref: 'kitchen' })])
    expect(hits.rooms.map(room => room.id).sort()).toEqual(['kitchen', 'kitchen-2'])
    expect(hits.boxes).toMatchObject([{ id: 'sofa', kind: 'object' }])
  })

  it('keeps ceiling lights on the visible floor and focuses the selected part', () => {
    const hits = failHighlights(building, [check({ id: 'area', entity_id: 'kitchen', status: 'fail', type_ref: 'kitchen', affected_space_ids: ['kitchen', 'kitchen-2'] })])
    expect(rankFailRooms(hits.rooms, ['f1'], null).map(room => room.id)).toEqual(['kitchen'])
    expect(rankFailRooms(hits.rooms, ['f1', 'f2'], 'kitchen-2')[0].id).toBe('kitchen-2')
    expect(failPartFocused('door', 'door', [check({ id: 'door-w', entity_id: 'door', status: 'fail' })])).toBe(true)
    expect(failPartFocused('kitchen', 'other', [check({ id: 'area', entity_id: 'kitchen', status: 'fail' })])).toBe(false)
  })
})
