import {fixtures, furniture} from './components/editor-geometry'
import type {Building} from './types'

export type ContextChipKind = '2d' | '3d' | 'room' | 'furniture' | 'fixture' | 'wall' | 'opening'
export type ContextChip = {id: string; kind: ContextChipKind; label: string}

const catalog = [...furniture, ...fixtures]

function assetLabel(assetId: string, kind?: string) {
  const named = catalog.find(item => item.id === assetId)?.label
  if (named) return named
  const fallback = assetId.replaceAll('_', ' ').replace(/\s+/g, ' ').trim()
  if (fallback) return fallback
  return kind === 'furniture' ? 'Furniture' : 'Object'
}

export function viewContextChip(mode: '2d' | '3d'): ContextChip {
  return {id: 'view', kind: mode, label: mode === '2d' ? '2D Floor Plan' : '3D Model'}
}

export function selectionContextChip(building: Building | null | undefined, selectedId: string | null | undefined): ContextChip | null {
  if (!building || !selectedId) return null
  const room = building.rooms.find(item => item.id === selectedId)
  if (room) return {id: room.id, kind: 'room', label: room.name || 'Room'}
  const object = building.objects.find(item => item.id === selectedId)
  if (object) {
    const kind = object.kind === 'furniture' ? 'furniture' : 'fixture'
    return {id: object.id, kind, label: assetLabel(object.asset_id, object.kind)}
  }
  const opening = building.openings.find(item => item.id === selectedId)
  if (opening) return {id: opening.id, kind: 'opening', label: opening.kind === 'door' ? 'Door' : 'Window'}
  const wall = building.walls.find(item => item.id === selectedId)
  if (wall) return {id: wall.id, kind: 'wall', label: 'Wall'}
  return {id: selectedId, kind: 'wall', label: 'Selection'}
}

export function composerContextChips(input: {
  mode: '2d' | '3d'
  building?: Building | null
  selectedId?: string | null
  includeView?: boolean
}): ContextChip[] {
  const chips: ContextChip[] = []
  if (input.includeView !== false) chips.push(viewContextChip(input.mode))
  const selected = selectionContextChip(input.building, input.selectedId)
  if (selected) chips.push(selected)
  return chips
}
