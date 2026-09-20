export type TreeSite = { width: number; height: number }

export type LandscapeTree = {
  x: number
  z: number
  size: number
  width: number
  canopy: number
  canopyY: number
  yaw: number
  pitch: number
  roll: number
  leaf: [number, number, number]
  shadow: boolean
}

function seeded(index: number, salt = 0) {
  const value = Math.sin(index * 127.1 + salt * 311.7) * 43758.5453
  return value - Math.floor(value)
}

function lerp(a: number, b: number, t: number) {
  return a + (b - a) * t
}

const KINDS = [
  { size: [19, 26], width: [1.22, 1.58], canopy: [1.18, 1.48], canopyY: [0.72, 0.92], pitch: 0.04, leaf: [0.88, 1.08, 0.96, 1.12, 0.42, 0.68] },
  { size: [28, 38], width: [0.55, 0.78], canopy: [0.68, 0.9], canopyY: [1.12, 1.38], pitch: 0.05, leaf: [0.52, 0.78, 0.92, 1.16, 0.48, 0.78] },
  { size: [11, 17], width: [0.88, 1.16], canopy: [0.92, 1.22], canopyY: [0.88, 1.12], pitch: 0.03, leaf: [0.95, 1.18, 1.02, 1.22, 0.58, 0.9] },
  { size: [22, 30], width: [0.9, 1.18], canopy: [0.95, 1.22], canopyY: [0.86, 1.06], pitch: 0.1, leaf: [0.68, 0.92, 0.82, 1.02, 0.38, 0.62] },
]

const GROVES: { x: number; z: number; count: number; radius: number; shadow: boolean }[] = [
  { x: -1, z: -1, count: 3, radius: 8, shadow: true },
  { x: 1, z: -1, count: 3, radius: 9, shadow: true },
  { x: -1, z: 1, count: 4, radius: 12, shadow: true },
  { x: 1, z: 1, count: 4, radius: 13, shadow: true },
  { x: -0.35, z: 1.7, count: 3, radius: 11, shadow: false },
  { x: 0.4, z: 1.95, count: 3, radius: 12, shadow: false },
  { x: -1.85, z: 2.2, count: 4, radius: 16, shadow: false },
  { x: 2, z: 2.35, count: 4, radius: 17, shadow: false },
  { x: -1.45, z: 0.15, count: 2, radius: 8, shadow: true },
  { x: 1.55, z: 0.1, count: 2, radius: 8, shadow: true },
]

export function landscapeTreePlacements(bounds: TreeSite): LandscapeTree[] {
  const w = bounds.width / 2, h = bounds.height / 2
  const trees: LandscapeTree[] = []
  let index = 0
  for (const grove of GROVES) {
    const cx = grove.x * (w + 22)
    const cz = grove.z * (h + 18)
    for (let n = 0; n < grove.count; n++) {
      let placed = false
      for (let attempt = 0; attempt < 8 && !placed; attempt++) {
        const kind = KINDS[index % KINDS.length]
        const angle = seeded(index, attempt + 2) * Math.PI * 2
        const dist = Math.sqrt(seeded(index, attempt + 3)) * grove.radius
        const x = cx + Math.cos(angle) * dist
        const z = cz + Math.sin(angle) * dist
        const onBuilding = Math.abs(x) < w + 7 && Math.abs(z) < h + 7
        const onRoad = z < -h - 20
        index++
        if (onBuilding || onRoad) continue
        const leaf = kind.leaf
        trees.push({
          x, z,
          size: lerp(kind.size[0], kind.size[1], seeded(index, 4)),
          width: lerp(kind.width[0], kind.width[1], seeded(index, 5)),
          canopy: lerp(kind.canopy[0], kind.canopy[1], seeded(index, 6)),
          canopyY: lerp(kind.canopyY[0], kind.canopyY[1], seeded(index, 7)),
          yaw: seeded(index, 8) * Math.PI * 2,
          pitch: (seeded(index, 9) - 0.5) * kind.pitch,
          roll: (seeded(index, 10) - 0.5) * kind.pitch,
          leaf: [
            lerp(leaf[0], leaf[1], seeded(index, 11)),
            lerp(leaf[2], leaf[3], seeded(index, 12)),
            lerp(leaf[4], leaf[5], seeded(index, 13)),
          ],
          shadow: grove.shadow,
        })
        placed = true
      }
    }
  }
  return trees
}
