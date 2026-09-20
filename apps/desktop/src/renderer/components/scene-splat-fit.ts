type Size = { x: number; y: number; z: number }
type Bounds = { cx: number; cy: number; width: number; height: number }
type Quat = { x: number; y: number; z: number; w: number }
export type SplatFileKind = 'ply' | 'spz' | 'splat' | 'ksplat'
export type SplatBounds = { min: Size; max: Size }

const UNIT = { x: 0.5, y: 0.5, z: 0.5 }
export const IDENTITY: Quat = { x: 0, y: 0, z: 0, w: 1 }
/** Rotate the generated image plane 180° without introducing a negative scale. */
export const SPLAT_UPRIGHT: Quat = { x: 0, y: 0, z: 1, w: 0 }

export function splatFileHint(url: string) {
  const fileName = url.split(/[?#]/, 1)[0].split('/').pop() || 'appearance.splat'
  const ext = fileName.includes('.') ? fileName.slice(fileName.lastIndexOf('.') + 1).toLowerCase() : ''
  const fileType: SplatFileKind = ext === 'ply' || ext === 'spz' || ext === 'ksplat' ? ext : 'splat'
  return { fileName, fileType }
}

/** Read the dense building core from raw .splat records, excluding stray reconstruction points. */
export function robustSplatBounds(bytes: ArrayBuffer, kind: SplatFileKind): SplatBounds | null {
  const stride = 32
  if (kind !== 'splat' || bytes.byteLength < stride * 128 || bytes.byteLength % stride) return null
  const view = new DataView(bytes)
  const axes: number[][] = [[], [], []]
  for (let offset = 0; offset < bytes.byteLength; offset += stride) {
    // rgba occupies bytes 24–27. Very faint points are usually matte/background debris.
    if (view.getUint8(offset + 27) < 8) continue
    const point = [view.getFloat32(offset, true), view.getFloat32(offset + 4, true), view.getFloat32(offset + 8, true)]
    if (!point.every(Number.isFinite)) continue
    for (let axis = 0; axis < 3; axis++) axes[axis].push(point[axis])
  }
  if (axes[0].length < 128) return null
  const range = axes.map(values => {
    values.sort((a, b) => a - b)
    const last = values.length - 1
    const low = values[Math.floor(last * .01)]
    const high = values[Math.ceil(last * .99)]
    const pad = Math.max((high - low) * .02, 1e-4)
    return [low - pad, high + pad]
  })
  return {
    min: { x: range[0][0], y: range[1][0], z: range[2][0] },
    max: { x: range[0][1], y: range[1][1], z: range[2][1] },
  }
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

/**
 * Fit the generated presentation skin to the measured CAD envelope.
 *
 * Single-image reconstruction does not preserve architectural proportions. A
 * uniform height-derived scale made the saved 40×30×20 ft demo house roughly
 * 24×24×20 ft, so its real interior visibly protruded through the skin. Axis
 * scales are intentional here: the CAD model remains the source of truth.
 */
export function splatPlacement(
  size: Size,
  center: Size,
  minY: number,
  bounds: Bounds,
  height: number,
) {
  const roof = Math.max(height, 8)
  // A slight plan overscan keeps the CAD partitions behind the exterior skin.
  const scale = {
    x: bounds.width * 1.015 / Math.max(size.x, 0.01),
    y: roof / Math.max(size.y, 0.01),
    z: bounds.height * 1.015 / Math.max(size.z, 0.01),
  }
  return {
    scale,
    x: bounds.cx - center.x * scale.x,
    y: -minY * scale.y,
    z: bounds.cy - center.z * scale.z,
  }
}
