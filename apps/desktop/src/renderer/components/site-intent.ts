let wantView = false
let wantPlace = false
let wantFrame = 0
let wantLook: SiteLook | null = null

export type SiteLook = { lat: number; lon: number; address: string }

export function requestSiteView() {
  wantView = true
  if (typeof window !== 'undefined') window.dispatchEvent(new CustomEvent('archetype:show-site'))
}

export function requestSitePlace() {
  wantPlace = true
  requestSiteView()
}

export function requestSiteFrame() {
  wantFrame += 1
  requestSiteView()
}

/** Fly to an address at building scale and start placing, without dropping the pin yet. */
export function requestSiteLook(lat: number, lon: number, address = '') {
  wantLook = { lat, lon, address }
  wantPlace = true
  wantFrame += 1
  requestSiteView()
}

export function consumeSiteView() {
  if (!wantView) return false
  wantView = false
  return true
}

export function consumeSitePlace() {
  if (!wantPlace) return false
  wantPlace = false
  return true
}

export function consumeSiteFrame() {
  const n = wantFrame
  wantFrame = 0
  return n
}

export function peekSitePlace() {
  return wantPlace
}

export function consumeSiteLook() {
  const look = wantLook
  wantLook = null
  return look
}

export function peekSiteLook() {
  return wantLook
}
