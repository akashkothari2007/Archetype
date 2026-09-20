import { describe, expect, it } from 'vitest'
import { IDENTITY, SPLAT_UPRIGHT, robustSplatBounds, splatExtents, splatFileHint, splatPlacement } from './scene-splat-fit'

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

describe('robust splat bounds', () => {
  it('ignores isolated reconstruction points when fitting the building', () => {
    const count = 1002
    const bytes = new ArrayBuffer(count * 32)
    const view = new DataView(bytes)
    for (let i = 0; i < 1000; i++) {
      const offset = i * 32
      view.setFloat32(offset, (i % 10) / 9 - .5, true)
      view.setFloat32(offset + 4, (Math.floor(i / 10) % 10) / 9, true)
      view.setFloat32(offset + 8, (Math.floor(i / 100) % 10) / 9 - .5, true)
      view.setUint8(offset + 27, 255)
    }
    for (const [index, value] of [[1000, -80], [1001, 120]] as const) {
      const offset = index * 32
      view.setFloat32(offset, value, true)
      view.setFloat32(offset + 4, value, true)
      view.setFloat32(offset + 8, value, true)
      view.setUint8(offset + 27, 255)
    }
    const bounds = robustSplatBounds(bytes, 'splat')!
    expect(bounds.max.x - bounds.min.x).toBeLessThan(1.2)
    expect(bounds.max.y - bounds.min.y).toBeLessThan(1.2)
    expect(bounds.max.z - bounds.min.z).toBeLessThan(1.2)
  })

  it('leaves other formats to their native bounding-box reader', () => {
    expect(robustSplatBounds(new ArrayBuffer(4096), 'ply')).toBeNull()
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
    expect(place.scale.y).toBeCloseTo(1)
    expect(place.scale.x).toBeCloseTo(.5075)
    expect(place.scale.z).toBeCloseTo(.3045)
    expect(place.y).toBeCloseTo(0)
    expect(place.x).toBeCloseTo(20)
    expect(place.z).toBeCloseTo(12)
  })

  it('fills the CAD footprint when the splat is only the building', () => {
    const place = splatPlacement({ x: 20, y: 9, z: 12 }, { x: 0, y: 4.5, z: 0 }, 0, house, 18)
    expect(place.scale.x).toBeCloseTo(2.03)
    expect(place.scale.y).toBeCloseTo(2)
    expect(place.scale.z).toBeCloseTo(2.03)
    expect(place.y).toBeCloseTo(0)
  })

  it('enlarges a native unit-cube reconstruction to the CAD house', () => {
    const extents = splatExtents(
      { x: -0.5, y: -0.42, z: -0.48 },
      { x: 0.5, y: 0.39, z: 0.48 },
      zUp,
    )
    const place = splatPlacement(extents.size, extents.center, extents.minY, house, 18)
    expect(place.scale.x).toBeGreaterThan(40)
    expect(place.scale.y).toBeGreaterThan(20)
    expect(place.y).toBeCloseTo(-extents.minY * place.scale.y)
  })

  it('rotates image-down splats upright before placement', () => {
    const extents = splatExtents(
      { x: -2, y: -1, z: -3 },
      { x: 4, y: 5, z: 3 },
      SPLAT_UPRIGHT,
    )
    expect(extents.minY).toBeCloseTo(-5)
    expect(extents.center.x).toBeCloseTo(-1)
    expect(extents.size).toEqual({ x: 6, y: 6, z: 6 })
  })

  it('falls back to a unit cube when the splat AABB is empty', () => {
    const extents = splatExtents(
      { x: Infinity, y: Infinity, z: Infinity },
      { x: -Infinity, y: -Infinity, z: -Infinity },
      zUp,
    )
    const place = splatPlacement(extents.size, extents.center, extents.minY, house, 18)
    expect(extents.size.x).toBeCloseTo(1)
    expect(place.scale.x).toBeGreaterThan(40)
  })
})
