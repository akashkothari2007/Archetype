export type SurfaceKind = 'plaster' | 'wood' | 'grass' | 'stone' | 'brick' | 'tile' | 'metal'

export type SurfaceDef = {
  id: string
  label: string
  color: string
  folder: string
  kind: SurfaceKind
  scale: number
  roughness: number
  normalScale: number
  metalness?: number
  tint?: boolean
  stylize?: boolean
  planks?: boolean
}

const plaster = (id: string, label: string, color: string): SurfaceDef => ({
  id, label, color, folder: 'landscape/plaster_grey_04', kind: 'plaster', scale: .38, roughness: .88, normalScale: .55, tint: true,
})

export const surfaces: SurfaceDef[] = [
  plaster('plaster', 'Chalk white', '#f3efe7'),
  plaster('sage', 'Soft sage', '#a7b09d'),
  { id: 'clay', label: 'Warm clay', color: '#c7a28f', folder: 'materials/beige_wall_001', kind: 'plaster', scale: .34, roughness: .9, normalScale: .62 },
  { id: 'slate', label: 'Slate', color: '#535d63', folder: 'materials/slate_floor', kind: 'stone', scale: .2, roughness: .92, normalScale: .45 },
  { id: 'oak', label: 'Natural oak', color: '#c7aa7f', folder: 'landscape/wood_floor', kind: 'wood', scale: .105, roughness: .8, normalScale: .22, planks: true },
  { id: 'walnut', label: 'Walnut', color: '#7f593e', folder: 'materials/american_walnut_veneer', kind: 'wood', scale: .12, roughness: .78, normalScale: .28, planks: true },
  { id: 'tile', label: 'Limestone', color: '#d5d0c3', folder: 'materials/stone_tiles', kind: 'tile', scale: .18, roughness: .72, normalScale: .4 },
  { id: 'concrete', label: 'Concrete', color: '#a8a8a2', folder: 'materials/concrete_floor', kind: 'stone', scale: .22, roughness: .95, normalScale: .38 },
  { id: 'brick', label: 'Red brick', color: '#8a5a3a', folder: 'materials/brick_wall_001', kind: 'brick', scale: .26, roughness: .92, normalScale: .7 },
  { id: 'herringbone', label: 'Herringbone oak', color: '#c4a06a', folder: 'materials/herringbone_parquet', kind: 'wood', scale: .14, roughness: .76, normalScale: .3 },
  { id: 'marble', label: 'Carrara marble', color: '#e8e4dc', folder: 'materials/marble_01', kind: 'tile', scale: .16, roughness: .28, normalScale: .22 },
  { id: 'terracotta', label: 'Terracotta', color: '#c4785a', folder: 'materials/terracotta_floor_tiles', kind: 'tile', scale: .2, roughness: .7, normalScale: .42 },
  { id: 'ceramic', label: 'Ceramic tile', color: '#dfe3e6', folder: 'materials/long_white_tiles', kind: 'tile', scale: .22, roughness: .36, normalScale: .25 },
  { id: 'granite', label: 'Polished granite', color: '#6e6a66', folder: 'materials/granite_tile', kind: 'tile', scale: .16, roughness: .42, normalScale: .3 },
  { id: 'cobble', label: 'Cobblestone', color: '#9a9590', folder: 'materials/cobblestone_04', kind: 'stone', scale: .18, roughness: .94, normalScale: .55 },
  { id: 'paintedbrick', label: 'Painted brick', color: '#d8d2c8', folder: 'materials/painted_brick', kind: 'brick', scale: .26, roughness: .88, normalScale: .62 },
  { id: 'darkwood', label: 'Dark walnut', color: '#4a3428', folder: 'materials/dark_wood', kind: 'wood', scale: .1, roughness: .82, normalScale: .24, planks: true },
  { id: 'metal', label: 'Brushed metal', color: '#8d9296', folder: 'materials/metal_plate', kind: 'metal', scale: .22, roughness: .38, normalScale: .45, metalness: .82 },
]

const grass: SurfaceDef = { id: 'grass', label: 'Grass', color: '#aebc91', folder: 'landscape/grass_ground', kind: 'grass', scale: .19, roughness: .95, normalScale: .3, tint: true }
const stone: SurfaceDef = { id: 'stone', label: 'Stone', color: '#b7b1a6', folder: 'landscape/plaster_grey_04', kind: 'stone', scale: .22, roughness: .88, normalScale: .22, tint: true, stylize: true }
const aliases: Record<string, string> = { white: 'plaster', wood: 'oak' }

export const surfaceById = Object.fromEntries(surfaces.map(surface => [surface.id, surface]))
export const materialIds = new Set(surfaces.map(surface => surface.id))

export function surfacePreview(surface: SurfaceDef) {
  return `assets/${surface.folder}/Diffuse.jpg`
}

export function surfaceOf(finish: string): SurfaceDef {
  const id = aliases[finish] || finish
  if (id === 'grass') return grass
  if (id === 'stone') return stone
  return surfaceById[id] || surfaceById.plaster
}
