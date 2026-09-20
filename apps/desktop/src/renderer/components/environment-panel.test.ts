import { describe, expect, it } from 'vitest'
import { azimuthFromPoint, cardinal, dayPeriod, formatClock } from './environment-panel'

describe('environment labels', () => {
  it('formats fractional hours as a 24-hour clock', () => {
    expect(formatClock(16.75)).toBe('16:45')
    expect(formatClock(0)).toBe('00:00')
    expect(formatClock(23.75)).toBe('23:45')
  })

  it('names the light period from solar time', () => {
    expect(dayPeriod(6)).toBe('Dawn')
    expect(dayPeriod(12)).toBe('Midday')
    expect(dayPeriod(16.75)).toBe('Golden hour')
    expect(dayPeriod(22)).toBe('Night')
  })

  it('rounds azimuth to an 8-wind compass', () => {
    expect(cardinal(0)).toBe('N')
    expect(cardinal(228)).toBe('SW')
    expect(cardinal(359)).toBe('N')
  })

  it('reads compass clicks clockwise from north', () => {
    expect(azimuthFromPoint(36, 6, 36, 36)).toBe(0)
    expect(azimuthFromPoint(66, 36, 36, 36)).toBe(90)
    expect(azimuthFromPoint(36, 66, 36, 36)).toBe(180)
    expect(azimuthFromPoint(6, 36, 36, 36)).toBe(270)
  })
})
