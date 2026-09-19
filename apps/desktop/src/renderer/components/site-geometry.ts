import type { Building } from '../types'
import { floorBounds, type Point } from './editor-geometry'

export const METERS_PER_FOOT = 0.3048
export const GOOGLE_TILES_ASSET_ID = 2275207
export const ionToken: string = import.meta.env.VITE_CESIUM_ION_TOKEN || ''
export const emptySite = { lat: null as number | null, lon: null as number | null, rotation_deg: 0, ground_offset_ft: 0, address: '' }

export type LatLon = { lat: number; lon: number }

/** Plan extent of the whole building, across every storey, in feet. */
export function siteFootprint(building: Building) {
  const flattened = { ...building, vertices: building.vertices.map(v => ({ ...v, floor_id: 'all' })) }
  return floorBounds(flattened, 'all')
}

/**
 * Sample points covering the footprint, in plan feet, including the corners so a
 * building straddling a break in the terrain is measured at its worst point.
 */
export function samplePlan(building: Building, steps = 5): Point[] {
  const { minX, maxX, minY, maxY } = siteFootprint(building)
  const points: Point[] = []
  const divisions = Math.max(2, steps) - 1
  for (let i = 0; i <= divisions; i++) {
    for (let j = 0; j <= divisions; j++) {
      points.push({ x: minX + (maxX - minX) * i / divisions, y: minY + (maxY - minY) * j / divisions })
    }
  }
  return points
}

/**
 * Rotate a plan point about the footprint centre into metres east/north. Plan +y runs
 * south, matching the 3D view where the plan's y axis maps to world +z under a y-up camera.
 */
export function planToLocal(point: Point, centre: Point, rotationDeg: number) {
  const angle = rotationDeg * Math.PI / 180
  const dx = (point.x - centre.x) * METERS_PER_FOOT
  const dy = -(point.y - centre.y) * METERS_PER_FOOT
  return { east: dx * Math.cos(angle) + dy * Math.sin(angle), north: -dx * Math.sin(angle) + dy * Math.cos(angle) }
}

export type Sample = { east: number; north: number; up: number }
export type PlaneFit = { tiltDeg: number; roughnessM: number; spreadM: number; meanUp: number }

/**
 * Least-squares plane through the sampled ground. Tilt comes from the fitted normal,
 * roughness from the RMS residual, spread from the raw height range.
 */
export function fitPlane(samples: Sample[]): PlaneFit | null {
  if (samples.length < 3) return null
  const n = samples.length
  let sx = 0, sy = 0, sz = 0
  for (const s of samples) { sx += s.east; sy += s.north; sz += s.up }
  const mx = sx / n, my = sy / n, mz = sz / n
  let xx = 0, xy = 0, yy = 0, xz = 0, yz = 0
  for (const s of samples) {
    const dx = s.east - mx, dy = s.north - my, dz = s.up - mz
    xx += dx * dx; xy += dx * dy; yy += dy * dy; xz += dx * dz; yz += dy * dz
  }
  const determinant = xx * yy - xy * xy
  // A degenerate spread (all samples on a line) has no unique plane; treat it as level.
  const gradientEast = Math.abs(determinant) < 1e-9 ? 0 : (yy * xz - xy * yz) / determinant
  const gradientNorth = Math.abs(determinant) < 1e-9 ? 0 : (xx * yz - xy * xz) / determinant
  let residual = 0
  for (const s of samples) {
    const predicted = mz + gradientEast * (s.east - mx) + gradientNorth * (s.north - my)
    residual += (s.up - predicted) ** 2
  }
  const ups = samples.map(s => s.up)
  return {
    tiltDeg: Math.atan(Math.hypot(gradientEast, gradientNorth)) * 180 / Math.PI,
    roughnessM: Math.sqrt(residual / n),
    spreadM: Math.max(...ups) - Math.min(...ups),
    meanUp: mz,
  }
}

export type Verdict = 'buildable' | 'caution' | 'blocked' | 'unknown'
export type SiteReport = PlaneFit & { verdict: Verdict; reasons: string[]; coverage: number }

export const siteLimits = { tiltDeg: 5, roughnessM: 0.6, spreadM: 2.5, coverage: 0.6 }

/** Turn the fitted ground into a verdict. Obstructions dominate slope: a roof reads as both. */
export function assessSite(samples: Sample[], requested: number): SiteReport {
  const coverage = requested > 0 ? samples.length / requested : 0
  const fit = fitPlane(samples)
  if (!fit || coverage < siteLimits.coverage) {
    return { tiltDeg: 0, roughnessM: 0, spreadM: 0, meanUp: fit?.meanUp ?? 0, coverage, verdict: 'unknown', reasons: ['Not enough ground was in view to measure. Let the tiles finish loading, or zoom closer.'] }
  }
  const reasons: string[] = []
  if (fit.spreadM > siteLimits.spreadM) reasons.push(`${fit.spreadM.toFixed(1)} m of height change across the footprint — likely a building or trees in the way.`)
  if (fit.tiltDeg > siteLimits.tiltDeg) reasons.push(`Ground tilts ${fit.tiltDeg.toFixed(1)}°, over the ${siteLimits.tiltDeg}° limit for a flat pad.`)
  if (fit.roughnessM > siteLimits.roughnessM) reasons.push(`Surface is uneven by ${fit.roughnessM.toFixed(2)} m RMS — not a clear, level lot.`)
  const blocked = fit.spreadM > siteLimits.spreadM || fit.tiltDeg > siteLimits.tiltDeg * 2
  const verdict: Verdict = blocked ? 'blocked' : reasons.length ? 'caution' : 'buildable'
  if (!reasons.length) reasons.push(`Level to within ${fit.tiltDeg.toFixed(1)}° and clear of obstructions.`)
  return { ...fit, coverage, verdict, reasons }
}

export function formatLatLon({ lat, lon }: LatLon) {
  return `${Math.abs(lat).toFixed(5)}° ${lat >= 0 ? 'N' : 'S'}, ${Math.abs(lon).toFixed(5)}° ${lon >= 0 ? 'E' : 'W'}`
}

export function parseLatLon(text: string): LatLon | null {
  const match = text.trim().match(/^(-?\d+(?:\.\d+)?)\s*[, ]\s*(-?\d+(?:\.\d+)?)$/)
  if (!match) return null
  const lat = Number(match[1]), lon = Number(match[2])
  if (!isFinite(lat) || !isFinite(lon) || Math.abs(lat) > 90 || Math.abs(lon) > 180) return null
  return { lat, lon }
}

export type Place = { name: string; lat: number; lon: number }

/** Cesium ion's geocoder. Free on a Community token with the geocode scope. */
export async function geocode(query: string, signal?: AbortSignal): Promise<Place[]> {
  if (!ionToken) throw new Error('Set VITE_CESIUM_ION_TOKEN in .env to search for a location.')
  const url = `https://api.cesium.com/v1/geocode/search?text=${encodeURIComponent(query)}`
  const response = await fetch(url, { headers: { Authorization: `Bearer ${ionToken}` }, signal })
  if (!response.ok) throw new Error(response.status === 401 ? 'The Cesium ion token was rejected. Check it has the geocode scope.' : `Search failed (${response.status}).`)
  const body = await response.json()
  return (body.features || []).flatMap((feature: any) => {
    const box = feature.bbox
    if (!Array.isArray(box) || box.length < 4) return []
    return [{ name: String(feature.properties?.label || feature.properties?.name || query), lon: (box[0] + box[2]) / 2, lat: (box[1] + box[3]) / 2 }]
  }).slice(0, 6)
}
