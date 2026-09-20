import { afterEach, describe, expect, it } from 'vitest'
import { consumeSiteFrame, consumeSiteLook, consumeSitePlace, consumeSiteView, peekSiteLook, peekSitePlace, requestSiteFrame, requestSiteLook, requestSitePlace, requestSiteView } from './site-intent'

describe('site placement intent', () => {
  afterEach(() => {
    consumeSiteView()
    consumeSitePlace()
    consumeSiteFrame()
    consumeSiteLook()
  })

  it('opens the globe without entering place mode', () => {
    requestSiteView()
    expect(peekSitePlace()).toBe(false)
    expect(consumeSiteView()).toBe(true)
    expect(consumeSiteView()).toBe(false)
  })

  it('keeps place and frame requests until the globe consumes them', () => {
    requestSitePlace()
    requestSiteFrame()
    requestSiteFrame()
    expect(peekSitePlace()).toBe(true)
    expect(consumeSiteView()).toBe(true)
    expect(consumeSitePlace()).toBe(true)
    expect(consumeSitePlace()).toBe(false)
    expect(consumeSiteFrame()).toBe(2)
    expect(consumeSiteFrame()).toBe(0)
  })

  it('flies to an address and starts placing without dropping a pin', () => {
    requestSiteLook(43.47, -80.54, '200 University Ave W')
    expect(peekSitePlace()).toBe(true)
    expect(peekSiteLook()).toEqual({ lat: 43.47, lon: -80.54, address: '200 University Ave W' })
    expect(consumeSiteLook()).toEqual({ lat: 43.47, lon: -80.54, address: '200 University Ave W' })
    expect(consumeSiteLook()).toBeNull()
    expect(consumeSitePlace()).toBe(true)
    expect(consumeSiteFrame()).toBe(1)
  })
})
