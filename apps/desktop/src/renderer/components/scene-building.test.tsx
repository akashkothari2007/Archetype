import { describe, expect, it } from 'vitest'
import { facadeKind } from './scene-building'

describe('facadeKind', () => {
  it.each([
    ['townhouse', 'home'],
    ['creative office', 'office'],
    ['neighbourhood cafe', 'retail'],
    ['boutique hotel', 'mixed'],
    ['public library', 'civic'],
    ['light industrial workshop', 'industrial'],
  ] as const)('matches %s to %s', (buildingUse, expected) => {
    expect(facadeKind(buildingUse)).toBe(expected)
  })
})
