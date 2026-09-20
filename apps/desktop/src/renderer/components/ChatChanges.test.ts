import {describe, expect, it} from 'vitest'
import {otherCommands, placedCommands, placementPreview} from './chat-placements'

const sofa = {kind: 'place_object' as const, target_id: '', params: {asset_id: 'sofa_02', kind: 'furniture'}}
const bath = {kind: 'place_object' as const, target_id: '', params: {asset_id: 'bath'}}
const move = {kind: 'offset_partition' as const, target_id: 'wall-1', params: {dx: 2}}

describe('chat placement previews', () => {
  it('keeps placed objects separate from other edits', () => {
    expect(placedCommands([sofa, move, bath])).toEqual([sofa, bath])
    expect(otherCommands([sofa, move, bath])).toEqual([move])
  })

  it('uses the furniture-tab preview image and label', () => {
    expect(placementPreview(sofa)).toMatchObject({
      id: 'sofa_02',
      label: 'Leather sofa',
      preview: 'assets/sofa_02/preview.png',
    })
    expect(placementPreview(bath)).toMatchObject({
      id: 'bath',
      label: 'Bathtub',
      symbol: 'bath',
    })
    expect(placementPreview(bath).preview).toBeUndefined()
  })
})
