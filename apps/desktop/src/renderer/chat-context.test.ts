import {describe, expect, it} from 'vitest'
import type {Building} from './types'
import {composerContextChips, selectionContextChip, viewContextChip} from './chat-context'

const source = {document_id: '', sheet_id: '', page: null, method: 'user', assumed: false as const}
const building: Building = {
  schema_version: 2,
  units: 'feet',
  floors: [{id: 'f1', name: 'Ground', elevation_ft: 0, height_ft: 9}],
  vertices: [],
  walls: [{id: 'ab', floor_id: 'f1', start_id: 'a', end_id: 'b', thickness_ft: 0.5, height_ft: 9, locked: false, structural: 'loadbearing', material: 'plaster', confidence: 1, source}],
  openings: [{id: 'door', wall_id: 'ab', kind: 'door', offset_ft: 3.5, width_ft: 3, height_ft: 7, sill_ft: 0, hinge: 'left', swing: 'in', clear_width_ft: 2.8, reliability: 'ok', reliability_reason: '', source}],
  rooms: [{
    id: 'kitchen', floor_id: 'f1', name: 'Kitchen', category: 'kitchen', type_ref: 'kitchen',
    polygon: [[0, 0], [10, 0], [10, 8], [0, 8]], wall_ids: ['ab'],
    floor_material: 'tile', confidence: 1, needs_review: false, instance_count: 1, parent_room_id: '',
    reliability: 'ok', reliability_reason: '', source,
  }],
  objects: [
    {id: 'sofa', floor_id: 'f1', asset_id: 'sofa_02', kind: 'furniture', x: 5, y: 4, rotation_deg: 90, width_ft: 7, depth_ft: 3.2, height_ft: 2.7, splat: ''},
    {id: 'imagined', floor_id: 'f1', asset_id: 'walnut_credenza', kind: 'furniture', x: 2, y: 2, rotation_deg: 0, width_ft: 5, depth_ft: 1.5, height_ft: 2.4, splat: 'splat.png'},
  ],
  type_catalogue: [],
  environment: {time: 14, sun_azimuth: 135, season: 'summer'},
  site: {lat: null, lon: null, rotation_deg: 0, ground_offset_ft: 0, address: ''},
  review: [],
}

describe('chat context chips', () => {
  it('labels the active view', () => {
    expect(viewContextChip('2d')).toEqual({id: 'view', kind: '2d', label: '2D Floor Plan'})
    expect(viewContextChip('3d')).toEqual({id: 'view', kind: '3d', label: '3D Model'})
  })

  it('turns a clicked room into a named chip', () => {
    expect(selectionContextChip(building, 'kitchen')).toEqual({id: 'kitchen', kind: 'room', label: 'Kitchen'})
  })

  it('turns clicked furniture into a named chip', () => {
    expect(selectionContextChip(building, 'sofa')).toEqual({id: 'sofa', kind: 'furniture', label: 'Leather sofa'})
    expect(selectionContextChip(building, 'imagined')).toEqual({id: 'imagined', kind: 'furniture', label: 'walnut credenza'})
  })

  it('adds the selection beside the view chip and can omit the view', () => {
    expect(composerContextChips({mode: '2d', building, selectedId: 'kitchen'}).map(chip => chip.label)).toEqual(['2D Floor Plan', 'Kitchen'])
    expect(composerContextChips({mode: '3d', building, selectedId: 'sofa'}).map(chip => chip.label)).toEqual(['3D Model', 'Leather sofa'])
    expect(composerContextChips({mode: '2d', building, selectedId: 'kitchen', includeView: false})).toEqual([{id: 'kitchen', kind: 'room', label: 'Kitchen'}])
    expect(composerContextChips({mode: '2d', selectedId: null})).toEqual([{id: 'view', kind: '2d', label: '2D Floor Plan'}])
  })
})
