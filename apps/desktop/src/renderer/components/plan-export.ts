import type { Building } from '../types'
import { distance, floorBounds, interiorPoint, lengthLabel, polygonArea } from './editor-geometry'

const PAD = 2
const TITLE = 3.6

function slug(value: string) {
  return value.trim().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '')
}

function n(value: number, digits = 3) {
  const rounded = Number(value.toFixed(digits))
  return Object.is(rounded, -0) ? 0 : rounded
}

function xml(value: string) {
  return value.replace(/[&<>"']/g, ch => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&apos;'}[ch]!))
}

function deg(radians: number) {
  return n(radians * 180 / Math.PI, 2)
}

export function schematicExportFilename(projectName?: string, floorName?: string, at = new Date()) {
  const project = slug(projectName || '') || 'project'
  const floor = slug(floorName || '') || 'plan'
  return `archetype-plan-${project}-${floor}-${at.toISOString().slice(0, 10)}.svg`
}

export function formatPlanSvg(input: {
  building: Building
  floorId: string
  units?: 'metric' | 'imperial'
  projectName?: string
  exportedAt?: Date
}) {
  const units = input.units || 'imperial'
  const building = input.building
  const floorId = input.floorId
  const floor = building.floors.find(item => item.id === floorId)
  const vertices = new Map(building.vertices.map(v => [v.id, v]))
  const walls = building.walls.filter(wall => wall.floor_id === floorId)
  const rooms = building.rooms.filter(room => room.floor_id === floorId)
  const objects = building.objects.filter(object => object.floor_id === floorId)
  const bounds = floorBounds(building, floorId)
  const minX = bounds.minX - PAD
  const minY = bounds.minY - PAD
  const width = bounds.width + PAD * 2
  const height = bounds.height + PAD * 2 + TITLE
  const when = (input.exportedAt || new Date()).toISOString().slice(0, 10)
  const title = [input.projectName, floor?.name || 'Floor plan'].filter(Boolean).join(' · ') || 'Floor plan'

  const roomShapes = rooms.map(room => {
    if (!room.polygon.length) return ''
    const area = polygonArea(room.polygon)
    const label = units === 'metric' ? `${(area * 0.092903).toFixed(1)} m²` : `${area.toFixed(1)} sq ft`
    const center = interiorPoint(room.polygon)
    return [
      `<polygon points="${room.polygon.map(p => `${n(p[0])},${n(p[1])}`).join(' ')}" fill="#fff" stroke="#d8dde2" stroke-width="0.04"/>`,
      `<text x="${n(center.x)}" y="${n(center.y - 0.18)}" text-anchor="middle" font-size="0.55" fill="#33383e" font-family="Inter, Arial, sans-serif">${xml(room.name.toUpperCase())}</text>`,
      `<text x="${n(center.x)}" y="${n(center.y + 0.48)}" text-anchor="middle" font-size="0.38" fill="#898e95" font-family="Inter, Arial, sans-serif">${xml(label)}</text>`,
    ].join('')
  })

  const wallShapes = walls.flatMap(wall => {
    const a = vertices.get(wall.start_id), b = vertices.get(wall.end_id)
    if (!a || !b) return []
    const length = distance(a, b)
    const angle = Math.atan2(b.y - a.y, b.x - a.x)
    const nx = -Math.sin(angle), ny = Math.cos(angle)
    const rotate = deg(angle + (angle > Math.PI / 2 || angle < -Math.PI / 2 ? Math.PI : 0))
    const label = length > 5 ? `<text x="${n((a.x + b.x) / 2 - nx * (wall.thickness_ft / 2 + 0.45))}" y="${n((a.y + b.y) / 2 - ny * (wall.thickness_ft / 2 + 0.45))}" text-anchor="middle" font-size="0.32" fill="#72777b" font-family="Inter, Arial, sans-serif" transform="rotate(${rotate} ${n((a.x + b.x) / 2 - nx * (wall.thickness_ft / 2 + 0.45))} ${n((a.y + b.y) / 2 - ny * (wall.thickness_ft / 2 + 0.45))})">${xml(lengthLabel(length, units))}</text>` : ''
    return [`<line x1="${n(a.x)}" y1="${n(a.y)}" x2="${n(b.x)}" y2="${n(b.y)}" stroke="#242628" stroke-width="${n(Math.max(0.08, wall.thickness_ft))}" stroke-linecap="square"/>`, label]
  })

  const openingShapes = building.openings.flatMap(opening => {
    const wall = walls.find(item => item.id === opening.wall_id)
    const a = wall && vertices.get(wall.start_id)
    const b = wall && vertices.get(wall.end_id)
    if (!wall || !a || !b) return []
    const angle = Math.atan2(b.y - a.y, b.x - a.x)
    const px = a.x + Math.cos(angle) * opening.offset_ft
    const py = a.y + Math.sin(angle) * opening.offset_ft
    const thick = Math.max(0.08, wall.thickness_ft)
    const w = opening.width_ft
    const gap = `<rect x="0" y="${n(-thick / 2)}" width="${n(w)}" height="${n(thick)}" fill="#fff"/>`
    const detail = opening.kind === 'window'
      ? `<rect x="0" y="${n(-thick / 2)}" width="${n(w)}" height="${n(thick)}" fill="none" stroke="#282c31" stroke-width="0.06"/><line x1="0" y1="0" x2="${n(w)}" y2="0" stroke="#282c31" stroke-width="0.06"/>`
      : `<g transform="translate(${opening.hinge === 'right' ? n(w) : 0} 0) scale(${opening.hinge === 'right' ? -1 : 1} ${opening.swing === 'out' ? -1 : 1})"><line x1="0" y1="0" x2="0" y2="${n(w)}" stroke="#282c31" stroke-width="0.08"/><path d="M ${n(w)} 0 A ${n(w)} ${n(w)} 0 0 1 0 ${n(w)}" fill="none" stroke="#282c31" stroke-width="0.05"/></g>`
    return [`<g transform="translate(${n(px)} ${n(py)}) rotate(${deg(angle)})">${gap}${detail}</g>`]
  })

  const objectShapes = objects.map(object => {
    const x = -object.width_ft / 2, y = -object.depth_ft / 2
    return `<g transform="translate(${n(object.x)} ${n(object.y)}) rotate(${n(object.rotation_deg, 2)})"><rect x="${n(x)}" y="${n(y)}" width="${n(object.width_ft)}" height="${n(object.depth_ft)}" rx="0.08" fill="#fafafa" stroke="#74787a" stroke-width="0.05"/></g>`
  })

  const scaleX = minX + 0.4
  const scaleY = minY + height - 1.35
  const unitNote = units === 'metric' ? '1 drawing unit = 1 ft · labels in metres' : '1 drawing unit = 1 ft'
  const titleBlock = [
    `<text x="${n(scaleX)}" y="${n(scaleY)}" font-size="0.42" fill="#33383e" font-family="Inter, Arial, sans-serif">${xml(title)}</text>`,
    `<text x="${n(scaleX)}" y="${n(scaleY + 0.55)}" font-size="0.3" fill="#72777b" font-family="Inter, Arial, sans-serif">${xml(`Archetype schematic · ${when} · ${unitNote}`)}</text>`,
  ]

  return [
    `<?xml version="1.0" encoding="UTF-8"?>`,
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${n(minX)} ${n(minY)} ${n(width)} ${n(height)}" width="${n(width * 24)}" height="${n(height * 24)}" fill="none">`,
    `<title>${xml(title)}</title>`,
    `<rect x="${n(minX)}" y="${n(minY)}" width="${n(width)}" height="${n(height)}" fill="#fff"/>`,
    `<g id="rooms">${roomShapes.join('')}</g>`,
    `<g id="walls">${wallShapes.join('')}</g>`,
    `<g id="openings">${openingShapes.join('')}</g>`,
    `<g id="objects">${objectShapes.join('')}</g>`,
    `<g id="title">${titleBlock.join('')}</g>`,
    `</svg>`,
    '',
  ].join('\n')
}
