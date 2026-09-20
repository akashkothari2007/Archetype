import type { Point } from './editor-geometry'

export type InkBounds = { minX: number; minY: number; maxX: number; maxY: number }
export type FurniturePose = {
  x: number
  y: number
  rotation_deg: number
  width_ft: number
  depth_ft: number
  height_ft: number
}

export const FURNITURE_COLORS = [
  '#f4f0e8',
  '#1f1f1f',
  '#8b5a2b',
  '#c45c4a',
  '#3d6172',
  '#4c8b5a',
  '#c7aa7f',
  '#7f593e',
  '#d4a017',
  '#5c6b70',
] as const

export const BRUSH_SIZES = [4, 10, 22] as const

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value))
}

export function inkSize(ink: InkBounds) {
  return { width: Math.max(0, ink.maxX - ink.minX), height: Math.max(0, ink.maxY - ink.minY) }
}

export function hasInk(ink: InkBounds | null) {
  if (!ink) return false
  const size = inkSize(ink)
  return size.width > 4 && size.height > 4
}

export function expandInk(current: InkBounds | null, x: number, y: number, radius: number): InkBounds {
  const pad = Math.max(1, radius)
  if (!current) return { minX: x - pad, minY: y - pad, maxX: x + pad, maxY: y + pad }
  return {
    minX: Math.min(current.minX, x - pad),
    minY: Math.min(current.minY, y - pad),
    maxX: Math.max(current.maxX, x + pad),
    maxY: Math.max(current.maxY, y + pad),
  }
}

export function ndcFromPixel(x: number, y: number, view: { width: number; height: number }) {
  return { nx: (x / Math.max(view.width, 1)) * 2 - 1, ny: -((y / Math.max(view.height, 1)) * 2 - 1) }
}

const IMAGINE_EVENT = 'archetype:imagine-furniture'
let wantImagine = false

export function requestImagineFurniture() {
  wantImagine = true
  if (typeof window !== 'undefined') window.dispatchEvent(new CustomEvent(IMAGINE_EVENT))
}

export function consumeImagineFurniture() {
  if (!wantImagine) return false
  wantImagine = false
  return true
}

export function furnitureFromSketch(
  ink: InkBounds,
  view: { width: number; height: number },
  unproject: (nx: number, ny: number) => Point | null,
  worldPerPixel: (at: Point, canvasHeight: number) => number,
  yawToward: (at: Point) => number,
  fallback: Point,
): FurniturePose {
  const cx = (ink.minX + ink.maxX) / 2
  const cy = (ink.minY + ink.maxY) / 2
  const { nx, ny } = ndcFromPixel(cx, cy, view)
  const at = unproject(nx, ny) || fallback
  const px = Math.max(worldPerPixel(at, view.height), 0.01)
  const width_ft = clamp((ink.maxX - ink.minX) * px, 1.5, 12)
  const height_ft = clamp((ink.maxY - ink.minY) * px, 1.2, 8)
  const depth_ft = clamp(width_ft * 0.72, 1.2, 10)
  return { x: at.x, y: at.y, width_ft, depth_ft, height_ft, rotation_deg: yawToward(at) }
}
