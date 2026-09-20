import { describe, expect, it } from 'vitest'
import { IDENTITY, splatExtents, splatFileHint, splatPlacement } from './scene-splat-fit'

const house = { cx: 20, cy: 12, width: 40, height: 24 }
const zUp = { x: 1, y: 0, z: 0, w: 0 }

describe('splat file hints', () => {
  it('keeps the filename when the URL is cache-busted', () => {
    expect(splatFileHint('http://127.0.0.1:8000/api/desktop/projects/p/files/appearance.splat?t=9')).toEqual({
      fileName: 'appearance.splat',
      fileType: 'splat',
    })
  })

  it('detects ply from the path, not the query string', () => {
    expect(splatFileHint('/files/appearance.ply?t=1').fileType).toBe('ply')
  })
})

describe('splat placement', () => {
  it('keeps storey height for an already Y-up reconstruction', () => {
    const extents = splatExtents(
      { x: -0.5, y: -0.1, z: -0.4 },
      { x: 0.5, y: 0.9, z: 0.4 },
      IDENTITY,
    )
    expect(extents.size.y).toBeCloseTo(1)
    expect(extents.minY).toBeCloseTo(-0.1)
  })

  it('matches storey height when the reconstruction includes a wide ground disc', () => {
    const place = splatPlacement({ x: 80, y: 18, z: 80 }, { x: 0, y: 9, z: 0 }, 0, house, 18)
    expect(place.scale).toBeCloseTo(1)
    expect(place.y).toBeCloseTo(0)
    expect(place.x).toBeCloseTo(20)
    expect(place.z).toBeCloseTo(12)
  })

  it('fills the CAD footprint when the splat is only the building', () => {
    const place = splatPlacement({ x: 20, y: 9, z: 12 }, { x: 0, y: 4.5, z: 0 }, 0, house, 18)
    expect(place.scale).toBeGreaterThan(1.9)
    expect(place.y).toBeCloseTo(0)
  })

  it('enlarges a native unit-cube reconstruction to the CAD house', () => {
    const extents = splatExtents(
      { x: -0.5, y: -0.42, z: -0.48 },
      { x: 0.5, y: 0.39, z: 0.48 },
      zUp,
    )
    const place = splatPlacement(extents.size, extents.center, extents.minY, house, 18)
    expect(place.scale).toBeGreaterThan(20)
    expect(place.y).toBeCloseTo(-extents.minY * place.scale)
  })

  it('falls back to a unit cube when the splat AABB is empty', () => {
    const extents = splatExtents(
      { x: Infinity, y: Infinity, z: Infinity },
      { x: -Infinity, y: -Infinity, z: -Infinity },
      zUp,
    )
    const place = splatPlacement(extents.size, extents.center, extents.minY, house, 18)
    expect(extents.size.x).toBeCloseTo(1)
    expect(place.scale).toBeGreaterThan(20)
  })
})
