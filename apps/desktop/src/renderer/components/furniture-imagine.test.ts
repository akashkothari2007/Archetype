import { afterEach, describe, expect, it } from 'vitest'
import { consumeImagineFurniture, expandInk, furnitureFromSketch, hasInk, ndcFromPixel, requestImagineFurniture } from './furniture-imagine'
import { fitObjectSplat } from './scene-splat-fit'

describe('imagine furniture intent', () => {
  afterEach(() => { consumeImagineFurniture() })

  it('keeps the request until the 3D view consumes it', () => {
    requestImagineFurniture()
    expect(consumeImagineFurniture()).toBe(true)
    expect(consumeImagineFurniture()).toBe(false)
  })
})

describe('furniture sketch placement', () => {
  it('maps the drawing centroid into NDC', () => {
    expect(ndcFromPixel(50, 25, { width: 100, height: 100 })).toEqual({ nx: 0, ny: 0.5 })
  })

  it('sizes the object from the ink span at the floor hit', () => {
    const pose = furnitureFromSketch(
      { minX: 40, minY: 40, maxX: 80, maxY: 70 },
      { width: 200, height: 100 },
      (nx, ny) => ({ x: nx * 10, y: ny * 10 }),
      () => 0.2,
      () => 90,
      { x: 0, y: 0 },
    )
    expect(pose.x).toBeCloseTo(-4)
    expect(pose.y).toBeCloseTo(-1)
    expect(pose.width_ft).toBeCloseTo(8)
    expect(pose.height_ft).toBeCloseTo(6)
    expect(pose.depth_ft).toBeCloseTo(5.76)
    expect(pose.rotation_deg).toBe(90)
  })

  it('uses the fallback when the sketch misses the floor', () => {
    const pose = furnitureFromSketch(
      { minX: 0, minY: 0, maxX: 20, maxY: 20 },
      { width: 100, height: 100 },
      () => null,
      () => 0.1,
      () => 0,
      { x: 12, y: 8 },
    )
    expect(pose).toMatchObject({ x: 12, y: 8 })
    expect(hasInk({ minX: 0, minY: 0, maxX: 2, maxY: 2 })).toBe(false)
    expect(hasInk(expandInk(null, 10, 10, 8))).toBe(true)
  })
})

describe('object splat fit', () => {
  it('uniformly scales the reconstruction into the placed box', () => {
    const place = fitObjectSplat({ x: 2, y: 1, z: 1 }, { x: 0, y: 0.5, z: 0 }, 0, { width: 6, height: 3, depth: 4 })
    expect(place.scale).toBeCloseTo(3)
    expect(place.x).toBeCloseTo(0)
    expect(place.y).toBeCloseTo(0)
    expect(place.z).toBeCloseTo(0)
  })
})
