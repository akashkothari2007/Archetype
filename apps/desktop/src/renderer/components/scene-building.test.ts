import { describe, expect, it } from 'vitest'
import type { Building } from '../types'
import { cutawayHeightFt, floorWorldY, floorsThrough, storeySlabThickness } from './scene-building'

const model: Building = {
  schema_version: 2, units: 'feet',
  floors: [
    { id: 'f2', name: 'Second', elevation_ft: 10, height_ft: 9 },
    { id: 'f1', name: 'First', elevation_ft: 0, height_ft: 9 },
    { id: 'f3', name: 'Third', elevation_ft: 20, height_ft: 9 },
  ],
  vertices: [], walls: [], openings: [], rooms: [], objects: [], type_catalogue: [],
  environment: { time: 14, sun_azimuth: 135, season: 'summer' },
  site: { lat: null, lon: null, rotation_deg: 0, ground_offset_ft: 0, address: '' },
  review: [],
}

describe('floor cutaway stacking', () => {
  it('opens the first floor without any storey above it', () => {
    expect(floorsThrough(model, 'f1').map(floor => floor.id)).toEqual(['f1'])
    expect(floorWorldY(model, 'f1')).toBe(0)
    expect(cutawayHeightFt(model, 'f1')).toBe(9)
  })

  it('keeps lower storeys under the open floor so the cutaway does not float', () => {
    expect(floorsThrough(model, 'f2').map(floor => floor.id)).toEqual(['f1', 'f2'])
    expect(floorsThrough(model, 'f3').map(floor => floor.id)).toEqual(['f1', 'f2', 'f3'])
    expect(floorWorldY(model, 'f2')).toBe(10)
    expect(floorWorldY(model, 'f3')).toBe(20)
    expect(cutawayHeightFt(model, 'f2')).toBe(19)
  })

  it('seats each upper slab on the walls of the storey below', () => {
    const second = model.floors.find(floor => floor.id === 'f2')!
    const slab = storeySlabThickness(model, second)
    expect(slab).toBe(1)
    expect(floorWorldY(model, 'f2') - slab).toBe(floorWorldY(model, 'f1') + 9)
  })

  it('does not invent floors for an unknown cut', () => {
    expect(floorsThrough(model, 'missing')).toEqual([])
  })
})
