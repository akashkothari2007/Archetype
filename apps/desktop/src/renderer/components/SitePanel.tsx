import { useEffect, useRef, useState } from 'react'
import { Map as MapLibreMap, Marker, NavigationControl, type MapMouseEvent, type StyleSpecification } from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { LoaderCircle, MapPin, Search, Move3d } from 'lucide-react'
import type { Building, ModelCommand } from '../types'
import { METERS_PER_FOOT, emptySite, formatLatLon, geocode, ionToken, parseLatLon, siteFootprint, type Place, type SiteReport } from './site-geometry'
import { buildingHeightFt } from './scene-building'

const basemap: StyleSpecification = {
  version: 8,
  sources: { osm: { type: 'raster', tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'], tileSize: 256, attribution: '© OpenStreetMap contributors' } },
  layers: [{ id: 'osm', type: 'raster', source: 'osm' }],
}

const verdictLabel: Record<string, string> = { buildable: 'Buildable', caution: 'Check this site', blocked: 'Not buildable', unknown: 'Not measured yet' }

export function SitePanel({ building, onCommand }: { building: Building; onCommand: (commands: ModelCommand[]) => void }) {
  const site = building.site ?? emptySite
  const sited = site?.lat != null && site?.lon != null
  const host = useRef<HTMLDivElement>(null)
  const map = useRef<MapLibreMap | null>(null)
  const marker = useRef<Marker | null>(null)
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<Place[]>([])
  const [searching, setSearching] = useState(false)
  const [error, setError] = useState('')
  const [rotation, setRotation] = useState(site?.rotation_deg ?? 0)
  const [report, setReport] = useState<SiteReport | null>(null)
  const footprint = siteFootprint(building)
  const size = { w: footprint.width * METERS_PER_FOOT, d: footprint.height * METERS_PER_FOOT, h: buildingHeightFt(building) * METERS_PER_FOOT }

  useEffect(() => setRotation(site?.rotation_deg ?? 0), [site?.rotation_deg])
  useEffect(() => {
    const listener = (event: Event) => setReport((event as CustomEvent<SiteReport | null>).detail)
    window.addEventListener('archetype:site-report', listener)
    return () => window.removeEventListener('archetype:site-report', listener)
  }, [])

  const place = (lat: number, lon: number, address = '') => {
    onCommand([{ kind: 'set_site', target_id: '', params: address ? { lat, lon, address } : { lat, lon } }])
  }

  useEffect(() => {
    if (!host.current || map.current) return
    const instance = new MapLibreMap({
      container: host.current,
      style: basemap,
      center: [site?.lon ?? -80.5449, site?.lat ?? 43.4723],
      zoom: sited ? 17 : 11,
      attributionControl: { compact: true },
    })
    instance.addControl(new NavigationControl({ showCompass: false }), 'top-right')
    instance.on('click', (event: MapMouseEvent) => place(event.lngLat.lat, event.lngLat.lng))
    map.current = instance
    return () => { instance.remove(); map.current = null; marker.current = null }
  }, [])

  // Keep the pin and the camera in step with whatever the model says the site is.
  useEffect(() => {
    const instance = map.current
    if (!instance) return
    if (!sited) { marker.current?.remove(); marker.current = null; return }
    const position: [number, number] = [site.lon as number, site.lat as number]
    if (!marker.current) {
      marker.current = new Marker({ color: '#3d5c78', draggable: true }).setLngLat(position).addTo(instance)
      marker.current.on('dragend', () => { const point = marker.current!.getLngLat(); place(point.lat, point.lng) })
    } else marker.current.setLngLat(position)
    const centre = instance.getCenter()
    if (Math.hypot(centre.lng - position[0], centre.lat - position[1]) > 0.002) instance.easeTo({ center: position, zoom: Math.max(instance.getZoom(), 17), duration: 700 })
  }, [site?.lat, site?.lon, sited])

  async function search(event: React.FormEvent) {
    event.preventDefault()
    const text = query.trim()
    if (!text) return
    const pasted = parseLatLon(text)
    if (pasted) { place(pasted.lat, pasted.lon, formatLatLon(pasted)); setResults([]); return }
    setSearching(true); setError(''); setResults([])
    try {
      const found = await geocode(text)
      if (!found.length) setError('Nothing found for that search.')
      setResults(found)
    } catch (problem) { setError(problem instanceof Error ? problem.message : 'Search failed.') }
    finally { setSearching(false) }
  }

  return <div className="editor-site">
    <div className="editor-site-map" ref={host} aria-label="Site location map" />
    <div className="editor-site-controls">
      <form className="editor-site-search" onSubmit={search}>
        <Search size={13} />
        <input aria-label="Search for a location" placeholder="Address, place, or 43.4723, -80.5449" value={query} onChange={e => setQuery(e.target.value)} />
        <button type="submit" disabled={searching || !query.trim()}>{searching ? <LoaderCircle size={13} className="editor-spin" /> : 'Find'}</button>
      </form>
      {results.length > 0 && <div className="editor-site-results">{results.map(item => (
        <button key={`${item.lat},${item.lon}`} onClick={() => { place(item.lat, item.lon, item.name); setResults([]); setQuery(item.name) }}><MapPin size={12} />{item.name}</button>
      ))}</div>}
      {error && <p className="editor-site-error">{error}</p>}
      {!ionToken && <p className="editor-site-error">Set VITE_CESIUM_ION_TOKEN in .env to search and to stream the 3D site.</p>}
      {sited ? <>
        <div className="editor-site-where"><strong>{site.address || 'Dropped pin'}</strong><span>{formatLatLon({ lat: site.lat as number, lon: site.lon as number })}</span></div>
        <label>Rotation <output>{Math.round(rotation)}°</output>
          <input type="range" aria-label="Building rotation from north" min="0" max="359" value={rotation} onChange={e => setRotation(Number(e.target.value))} onPointerUp={() => onCommand([{ kind: 'set_site', target_id: '', params: { rotation_deg: rotation } }])} onKeyUp={() => onCommand([{ kind: 'set_site', target_id: '', params: { rotation_deg: rotation } }])} />
        </label>
        <div className="editor-site-size">Footprint {size.w.toFixed(1)} × {size.d.toFixed(1)} m · {size.h.toFixed(1)} m tall, from the floor plan</div>
        <div className={`editor-site-verdict ${report?.verdict || 'unknown'}`}>
          <strong>{verdictLabel[report?.verdict || 'unknown']}</strong>
          {report ? <><span>{report.tiltDeg.toFixed(1)}° tilt · {report.roughnessM.toFixed(2)} m roughness · {report.spreadM.toFixed(1)} m range</span><p>{report.reasons[0]}</p></> : <p>Open the On site view to measure the ground under the footprint.</p>}
        </div>
        <button className="editor-site-open" onClick={() => window.dispatchEvent(new CustomEvent('archetype:show-site'))}><Move3d size={13} /> View on site</button>
      </> : <p className="editor-site-hint">Search for an address or click the map to stand this building on Google's photorealistic 3D map. The footprint and storey heights come straight from your floor plan.</p>}
    </div>
  </div>
}

export default SitePanel
