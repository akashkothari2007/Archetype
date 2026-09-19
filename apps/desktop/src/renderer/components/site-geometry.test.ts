import { describe, expect, it } from 'vitest'
import type { Building } from '../types'
import { assessSite, fitPlane, parseLatLon, planToLocal, samplePlan, siteFootprint, type Sample } from './site-geometry'

const model: Building = {
  schema_version: 2, units: 'feet',
  floors: [{ id: 'f1', name: 'Ground', elevation_ft: 0, height_ft: 9 }, { id: 'f2', name: 'Upper', elevation_ft: 10, height_ft: 9 }],
  vertices: [
    { id: 'a', floor_id: 'f1', x: 0, y: 0 }, { id: 'b', floor_id: 'f1', x: 40, y: 0 },
    { id: 'c', floor_id: 'f1', x: 40, y: 30 }, { id: 'd', floor_id: 'f2', x: 0, y: 30 },
  ],
  walls: [], openings: [], rooms: [], objects: [], type_catalogue: [],
  environment: { time: 14, sun_azimuth: 135, season: 'summer' },
  site: { lat: null, lon: null, rotation_deg: 0, ground_offset_ft: 0, address: '' },
  review: [],
}

const grid = (fn: (east: number, north: number) => number): Sample[] => {
  const out: Sample[] = []
  for (let i = -2; i <= 2; i++) for (let j = -2; j <= 2; j++) out.push({ east: i * 3, north: j * 3, up: fn(i * 3, j * 3) })
  return out
}

describe('site footprint and sampling', () => {
  it('spans every storey, not just the active floor', () => {
    expect(siteFootprint(model)).toMatchObject({ minX: 0, maxX: 40, minY: 0, maxY: 30 })
  })
  it('samples a full inclusive grid that reaches the footprint corners', () => {
    const points = samplePlan(model, 5)
    expect(points).toHaveLength(25)
    expect(points).toContainEqual({ x: 0, y: 0 })
    expect(points).toContainEqual({ x: 40, y: 30 })
  })
  it('converts plan feet to metres east and north, and rotates clockwise from north', () => {
    const centre = { x: 0, y: 0 }
    const east = planToLocal({ x: 10, y: 0 }, centre, 0)
    expect(east.east).toBeCloseTo(3.048)
    expect(east.north).toBeCloseTo(0)
    const turned = planToLocal({ x: 10, y: 0 }, centre, 90)
    expect(turned.east).toBeCloseTo(0)
    expect(turned.north).toBeCloseTo(-3.048)
  })
  it('runs the plan y axis south so the placed building is not mirrored', () => {
    const south = planToLocal({ x: 0, y: 10 }, { x: 0, y: 0 }, 0)
    expect(south.north).toBeCloseTo(-3.048)
    expect(south.east).toBeCloseTo(0)
  })
})

describe('ground fitting', () => {
  it('reads a dead level pad as zero tilt and zero roughness', () => {
    const fit = fitPlane(grid(() => 12))!
    expect(fit.tiltDeg).toBeCloseTo(0)
    expect(fit.roughnessM).toBeCloseTo(0)
    expect(fit.meanUp).toBeCloseTo(12)
  })
  it('recovers the tilt of a clean constant slope without calling it rough', () => {
    const fit = fitPlane(grid(east => east * Math.tan(10 * Math.PI / 180)))!
    expect(fit.tiltDeg).toBeCloseTo(10, 4)
    expect(fit.roughnessM).toBeCloseTo(0, 6)
  })
  it('separates roughness from tilt when the surface is bumpy but level on average', () => {
    const fit = fitPlane(grid((east, north) => (east + north) % 2 === 0 ? 1 : -1))!
    expect(fit.tiltDeg).toBeLessThan(1)
    expect(fit.roughnessM).toBeGreaterThan(0.5)
  })
  it('treats collinear samples as level rather than dividing by zero', () => {
    const fit = fitPlane([{ east: 0, north: 0, up: 3 }, { east: 1, north: 0, up: 3 }, { east: 2, north: 0, up: 3 }])!
    expect(fit.tiltDeg).toBe(0)
    expect(Number.isFinite(fit.roughnessM)).toBe(true)
  })
  it('needs three points', () => {
    expect(fitPlane([{ east: 0, north: 0, up: 0 }, { east: 1, north: 0, up: 0 }])).toBeNull()
  })
})

describe('buildability verdict', () => {
  it('passes a flat clear lot', () => {
    const report = assessSite(grid(() => 4), 25)
    expect(report.verdict).toBe('buildable')
  })
  it('blocks a footprint with a house standing in it', () => {
    const report = assessSite(grid((east, north) => east > 0 && north > 0 ? 8 : 0), 25)
    expect(report.verdict).toBe('blocked')
    expect(report.reasons[0]).toMatch(/height change/)
  })
  it('cautions on a mild slope rather than blocking it', () => {
    const report = assessSite(grid(east => east * Math.tan(8 * Math.PI / 180)), 25)
    expect(report.verdict).toBe('caution')
    expect(report.reasons.some(r => r.includes('tilts'))).toBe(true)
  })
  it('reports unknown when most rays missed the terrain', () => {
    const report = assessSite(grid(() => 0).slice(0, 5), 25)
    expect(report.verdict).toBe('unknown')
    expect(report.coverage).toBeCloseTo(0.2)
  })
})

describe('coordinate entry', () => {
  it('accepts pasted coordinate pairs and rejects out of range or malformed text', () => {
    expect(parseLatLon('43.4723, -80.5449')).toEqual({ lat: 43.4723, lon: -80.5449 })
    expect(parseLatLon('43.4723 -80.5449')).toEqual({ lat: 43.4723, lon: -80.5449 })
    expect(parseLatLon('91, 0')).toBeNull()
    expect(parseLatLon('Waterloo')).toBeNull()
  })
})
