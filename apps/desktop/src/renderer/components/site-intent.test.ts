import { afterEach, describe, expect, it } from 'vitest'
import { consumeSiteFrame, consumeSitePlace, consumeSiteView, peekSitePlace, requestSiteFrame, requestSitePlace, requestSiteView } from './site-intent'

describe('site placement intent', () => {
  afterEach(() => {
    consumeSiteView()
    consumeSitePlace()
    consumeSiteFrame()
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
})
