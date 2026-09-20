import { describe, expect, it } from 'vitest'
import { skyCloudFields } from './scene-clouds'
import { landscapeTreePlacements } from './scene-trees'

describe('sky cloud layout', () => {
  const bounds = { minX: 0, maxX: 40, minY: 0, maxY: 30, width: 40, height: 30, cx: 20, cy: 15 }

  it('keeps cloud banks in the sky above the trees', () => {
    const fields = skyCloudFields(bounds)
    const copies = [...fields.main, ...fields.cluster]
    expect(copies.length).toBeGreaterThanOrEqual(12)
    for (const copy of copies) {
      const [sx, sy] = copy.scale
      const reach = Math.hypot(copy.x - bounds.cx, copy.z - bounds.cy)
      expect(copy.y - sy).toBeGreaterThan(55)
      expect(reach).toBeGreaterThan(sx * 1.6)
      expect(copy.y / reach).toBeGreaterThan(0.28)
      expect(copy.y / reach).toBeLessThan(0.85)
    }
  })
})

describe('landscape tree variety', () => {
  const bounds = { width: 40, height: 30 }
  const trees = landscapeTreePlacements(bounds)
  const w = bounds.width / 2, h = bounds.height / 2

  it('plants a mixed grove instead of a handful of identical copies', () => {
    expect(trees.length).toBeGreaterThanOrEqual(16)
    const sizes = trees.map(tree => tree.size)
    expect(Math.max(...sizes) / Math.min(...sizes)).toBeGreaterThan(1.8)
    const widths = trees.map(tree => tree.width)
    expect(Math.max(...widths) - Math.min(...widths)).toBeGreaterThan(0.4)
    const canopies = trees.map(tree => tree.canopy / tree.canopyY)
    expect(Math.max(...canopies) / Math.min(...canopies)).toBeGreaterThan(1.3)
  })

  it('keeps trees off the building and the road', () => {
    for (const tree of trees) {
      const onBuilding = Math.abs(tree.x) < w + 6 && Math.abs(tree.z) < h + 6
      expect(onBuilding).toBe(false)
      expect(tree.z).toBeGreaterThan(-h - 20)
    }
  })

  it('varies facing, lean, and leaf tint so the copies do not match', () => {
    const yaws = new Set(trees.map(tree => Math.round(tree.yaw * 8)))
    expect(yaws.size).toBeGreaterThan(8)
    const tints = new Set(trees.map(tree => tree.leaf.map(channel => channel.toFixed(2)).join(',')))
    expect(tints.size).toBeGreaterThan(8)
    expect(trees.some(tree => Math.abs(tree.pitch) + Math.abs(tree.roll) > 0.01)).toBe(true)
  })
})
