export type CloudCopy = { x: number; y: number; z: number; scale: [number, number, number]; yaw: number }

export function skyCloudFields(bounds: { width: number; height: number; cx: number; cy: number }) {
  const span = Math.max(bounds.width, bounds.height, 35)
  const radius = Math.max(span * 4.6, 175)
  const lift = Math.max(112, span * 2.5)
  const main = Math.max(span * 1.35, 48)
  const puff = Math.max(span * 0.9, 32)
  const around = (count: number, sx: number, sy: number, sz: number, reach: number, y: number, yaw0: number) =>
    Array.from({ length: count }, (_, i) => {
      const angle = yaw0 + i * (Math.PI * 2 / count)
      const radial = reach * (0.9 + (i % 3) * 0.08)
      const size = 0.84 + (i % 4) * 0.08
      return {
        x: bounds.cx + Math.cos(angle) * radial,
        y: y * (0.92 + (i % 2) * 0.12),
        z: bounds.cy + Math.sin(angle) * radial,
        scale: [sx * size, sy * size, sz * size] as [number, number, number],
        yaw: angle + Math.PI / 2,
      }
    })
  return {
    main: around(10, main, main * 0.4, main * 1.05, radius, lift, 0.18),
    cluster: around(8, puff, puff * 0.46, puff, radius * 1.2, lift * 1.16, 0.5),
  }
}
