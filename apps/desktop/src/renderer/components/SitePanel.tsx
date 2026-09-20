import { useEffect, useState } from 'react'
import { LoaderCircle, MapPin, Search } from 'lucide-react'
import type { Building, ModelCommand } from '../types'
import { METERS_PER_FOOT, emptySite, formatLatLon, geocode, ionToken, parseLatLon, siteFootprint, type Place, type SiteReport } from './site-geometry'
import { buildingHeightFt } from './scene-building'
import { requestSiteFrame, requestSiteLook, requestSitePlace, requestSiteView } from './site-intent'

const verdictLabel: Record<string, string> = { buildable: 'Buildable', caution: 'Check this site', blocked: 'Not buildable', unknown: 'Not measured yet' }

export function SitePanel({ building }: { building: Building; onCommand: (commands: ModelCommand[]) => void }) {
  const site = building.site ?? emptySite
  const sited = site?.lat != null && site?.lon != null
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<Place[]>([])
  const [searching, setSearching] = useState(false)
  const [error, setError] = useState('')
  const [report, setReport] = useState<SiteReport | null>(null)
  const [placing, setPlacing] = useState(!sited)
  const [pending, setPending] = useState('')
  const footprint = siteFootprint(building)
  const size = { w: footprint.width * METERS_PER_FOOT, d: footprint.height * METERS_PER_FOOT, h: buildingHeightFt(building) * METERS_PER_FOOT }

  useEffect(() => setPlacing(!sited), [sited])
  useEffect(() => {
    const reportListener = (event: Event) => setReport((event as CustomEvent<SiteReport | null>).detail)
    const placingListener = (event: Event) => {
      const next = !!(event as CustomEvent<boolean>).detail
      setPlacing(next)
      if (!next) setPending('')
    }
    window.addEventListener('archetype:site-report', reportListener)
    window.addEventListener('archetype:site-placing', placingListener)
    return () => {
      window.removeEventListener('archetype:site-report', reportListener)
      window.removeEventListener('archetype:site-placing', placingListener)
    }
  }, [])

  const aim = (lat: number, lon: number, address = '') => {
    setPending(address || formatLatLon({ lat, lon }))
    requestSiteLook(lat, lon, address)
  }

  async function search(event: React.FormEvent) {
    event.preventDefault()
    const text = query.trim()
    if (!text) return
    const pasted = parseLatLon(text)
    if (pasted) { aim(pasted.lat, pasted.lon, formatLatLon(pasted)); setResults([]); return }
    setSearching(true); setError(''); setResults([])
    try {
      const found = await geocode(text)
      if (!found.length) setError('Nothing found for that search.')
      setResults(found)
    } catch (problem) { setError(problem instanceof Error ? problem.message : 'Search failed.') }
    finally { setSearching(false) }
  }

  return <div className="editor-site editor-site-panel">
    <div className="editor-site-cluster">
      <form className="editor-site-search" onSubmit={search}>
        <Search size={13} />
        <input aria-label="Search for a location" placeholder="Search an address" value={query} onChange={e => setQuery(e.target.value)} onKeyDown={event => event.stopPropagation()} />
        <button type="submit" disabled={searching || !query.trim()}>{searching ? <LoaderCircle size={13} className="editor-spin" /> : 'Find'}</button>
      </form>
      {results.length > 0 && <div className="editor-site-results">{results.map(item => (
        <button key={`${item.lat},${item.lon}`} onClick={() => { aim(item.lat, item.lon, item.name); setResults([]); setQuery(item.name) }}><MapPin size={12} />{item.name}</button>
      ))}</div>}
      {error && <p className="editor-site-error">{error}</p>}
      {!ionToken && <p className="editor-site-error">Set VITE_CESIUM_ION_TOKEN in .env to search and to stream the 3D globe.</p>}
      {pending && placing ? <div className="editor-site-where"><strong>Click the globe to place</strong><span>{pending}</span></div>
        : sited ? <div className="editor-site-where"><strong>{site.address || 'Dropped pin'}</strong><span>{formatLatLon({ lat: site.lat as number, lon: site.lon as number })}</span></div>
        : <p className="editor-site-hint">Search, then click the globe to place.</p>}
    </div>
    <div className="editor-site-cluster">
      <div className="editor-site-tools">
        <button className={placing ? 'active' : ''} onClick={requestSitePlace}>{sited ? 'Move building' : 'Place building'}</button>
        {sited ? <button onClick={requestSiteFrame}>Frame site</button> : <button onClick={requestSiteView}>Open globe</button>}
      </div>
      {sited && <div className="editor-site-size">Footprint {size.w.toFixed(1)} × {size.d.toFixed(1)} m · {size.h.toFixed(1)} m tall, from the floor plan</div>}
    </div>
    {report && <div className="editor-site-cluster editor-site-cluster-verdict">
      <div className={`editor-site-verdict ${report.verdict}`}>
        <strong>{verdictLabel[report.verdict]}</strong>
        <span>{report.tiltDeg.toFixed(1)}° tilt · {report.roughnessM.toFixed(2)} m roughness · {report.spreadM.toFixed(1)} m range</span>
        <p>{report.reasons[0]}</p>
      </div>
    </div>}
  </div>
}

export default SitePanel
