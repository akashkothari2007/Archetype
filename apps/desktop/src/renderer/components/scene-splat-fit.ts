type Size = { x: number; y: number; z: number }
type Bounds = { cx: number; cy: number; width: number; height: number }
type Quat = { x: number; y: number; z: number; w: number }
export type SplatFileKind = 'ply' | 'spz' | 'splat' | 'ksplat'

const UNIT = { x: 0.5, y: 0.5, z: 0.5 }
export const IDENTITY: Quat = { x: 0, y: 0, z: 0, w: 1 }

export function splatFileHint(url: string) {
  const fileName = url.split(/[?#]/, 1)[0].split('/').pop() || 'appearance.splat'
  const ext = fileName.includes('.') ? fileName.slice(fileName.lastIndexOf('.') + 1).toLowerCase() : ''
  const fileType: SplatFileKind = ext === 'ply' || ext === 'spz' || ext === 'ksplat' ? ext : 'splat'
  return { fileName, fileType }
}

function rotate(p: Size, q: Quat): Size {
  const ix = q.w * p.x + q.y * p.z - q.z * p.y
  const iy = q.w * p.y + q.z * p.x - q.x * p.z
  const iz = q.w * p.z + q.x * p.y - q.y * p.x
  const iw = -q.x * p.x - q.y * p.y - q.z * p.z
  return {
    x: ix * q.w + iw * -q.x + iy * -q.z - iz * -q.y,
    y: iy * q.w + iw * -q.y + iz * -q.x - ix * -q.z,
    z: iz * q.w + iw * -q.z + ix * -q.y - iy * -q.x,
  }
}

/** Spark stores splat centers in object space. Rotate the AABB into world axes before fitting. */
export function splatExtents(min: Size, max: Size, quaternion: Quat) {
  let minX = Infinity, minY = Infinity, minZ = Infinity
  let maxX = -Infinity, maxY = -Infinity, maxZ = -Infinity
  for (const x of [min.x, max.x]) {
    for (const y of [min.y, max.y]) {
      for (const z of [min.z, max.z]) {
        const p = rotate({ x, y, z }, quaternion)
        minX = Math.min(minX, p.x)
        minY = Math.min(minY, p.y)
        minZ = Math.min(minZ, p.z)
        maxX = Math.max(maxX, p.x)
        maxY = Math.max(maxY, p.y)
        maxZ = Math.max(maxZ, p.z)
      }
    }
  }
  if (!Number.isFinite(minX) || maxX - minX < 1e-4) {
    minX = -UNIT.x
    minY = -UNIT.y
    minZ = -UNIT.z
    maxX = UNIT.x
    maxY = UNIT.y
    maxZ = UNIT.z
  }
  return {
    size: { x: Math.max(maxX - minX, 0.01), y: Math.max(maxY - minY, 0.01), z: Math.max(maxZ - minZ, 0.01) },
    center: { x: (minX + maxX) / 2, y: (minY + maxY) / 2, z: (minZ + maxZ) / 2 },
    minY,
  }
}

/** Fit a reconstructed Gaussian to the CAD envelope. Ignore a wide ground disc so the house keeps storey height. */
export function splatPlacement(
  size: Size,
  center: Size,
  minY: number,
  bounds: Bounds,
  height: number,
) {
  const roof = Math.max(height, 8)
  const byHeight = roof / Math.max(size.y, 0.01)
  const byPlan = Math.min(
    bounds.width / Math.max(size.x, 0.01),
    bounds.height / Math.max(size.z, 0.01),
  )
  const scale = Math.max(byHeight, Math.min(byPlan, byHeight * 2.4))
  return {
    scale,
    x: bounds.cx - center.x * scale,
    y: -minY * scale,
    z: bounds.cy - center.z * scale,
  }
}
