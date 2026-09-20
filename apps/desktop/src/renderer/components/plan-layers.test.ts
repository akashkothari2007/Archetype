import { describe, expect, it } from 'vitest'
import { computeLayerCounts } from './plan-layers'

describe('plan layer counts', () => {
  it('uses extracted sheet geometry when present', () => {
    expect(computeLayerCounts({
      sheetWalls: [{ cls: 'loadbearing' }, { cls: 'partition' }, { cls: 'partition' }],
      sheetDoors: 4,
      sheetWindows: 2,
      sheetFixtures: 3,
      sheetFurniture: 12,
      floorWalls: [{ structural: 'loadbearing' }],
      floorOpenings: 1,
      floorFixtures: 1,
      floorFurniture: 1,
    })).toEqual([1, 2, 6, 4, 12, 25])
  })

  it('falls back to the live floor model when the sheet is empty', () => {
    expect(computeLayerCounts({
      floorWalls: [{ structural: 'loadbearing' }, { structural: 'nonstructural' }, { structural: 'nonstructural' }],
      floorOpenings: 3,
      floorFixtures: 2,
      floorFurniture: 5,
    })).toEqual([1, 2, 3, 2, 5, 13])
  })
})
