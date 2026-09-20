import type { ModelCommand } from '../types'
import { catalogAsset } from './editor-geometry'

export function placedCommands(commands?: ModelCommand[] | null) {
  return (commands || []).filter(command => command.kind === 'place_object')
}

export function otherCommands(commands?: ModelCommand[] | null) {
  return (commands || []).filter(command => command.kind !== 'place_object')
}

export function placementPreview(command: ModelCommand) {
  const assetId = String(command.params?.asset_id || '')
  const asset = catalogAsset(assetId)
  return {
    id: asset?.id || assetId,
    label: asset?.label || assetId.replaceAll('_', ' ') || 'Object',
    preview: asset?.preview,
    symbol: asset?.id || assetId,
  }
}
