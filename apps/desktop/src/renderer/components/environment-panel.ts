export const SEASONS = ['spring', 'summer', 'autumn', 'winter'] as const
export type SeasonId = (typeof SEASONS)[number]

export const TIME_STOPS = [
  { time: 6, label: 'Dawn' },
  { time: 12, label: 'Noon' },
  { time: 17, label: 'Golden' },
  { time: 21, label: 'Night' },
] as const

export const SUN_STOPS = [
  { azimuth: 0, label: 'N' },
  { azimuth: 90, label: 'E' },
  { azimuth: 180, label: 'S' },
  { azimuth: 270, label: 'W' },
] as const

const CARDINALS = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'] as const

function wrapHours(time: number) {
  return ((time % 24) + 24) % 24
}

export function formatClock(time: number) {
  const wrapped = wrapHours(time)
  const hours = Math.floor(wrapped)
  const minutes = Math.round((wrapped - hours) * 60)
  if (minutes === 60) return `${String((hours + 1) % 24).padStart(2, '0')}:00`
  return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}`
}

export function dayPeriod(time: number) {
  const t = wrapHours(time)
  if (t >= 5 && t < 7) return 'Dawn'
  if (t >= 7 && t < 11) return 'Morning'
  if (t >= 11 && t < 13.5) return 'Midday'
  if (t >= 13.5 && t < 16) return 'Afternoon'
  if (t >= 16 && t < 18.5) return 'Golden hour'
  if (t >= 18.5 && t < 21) return 'Dusk'
  return 'Night'
}

export function cardinal(azimuth: number) {
  const wrapped = ((azimuth % 360) + 360) % 360
  return CARDINALS[Math.round(wrapped / 45) % 8]
}

export function azimuthFromPoint(x: number, y: number, cx: number, cy: number) {
  const deg = Math.atan2(x - cx, cy - y) * 180 / Math.PI
  return Math.round((deg + 360) % 360)
}
