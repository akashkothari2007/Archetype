import { useEffect, useRef, useState } from 'react'
import { Paintbrush, Search } from 'lucide-react'
import type { Building, ModelCommand } from '../types'
import { assetMime, fixtures, furniture, materials, type Asset } from './editor-geometry'
import { azimuthFromPoint, cardinal, dayPeriod, formatClock, SEASONS, SUN_STOPS, TIME_STOPS, type SeasonId } from './environment-panel'
import { requestImagineFurniture } from './furniture-imagine'
import { XrayScrubber, type LayerStop } from './plan-layers'
import { SitePanel } from './SitePanel'
import './editor-view.css'

export type LibraryTab = 'layers' | 'fixtures' | 'furniture' | 'materials' | 'environment' | 'site'

export function AssetSymbol({ id }: { id: string }) {
  const common = { fill: 'none', stroke: 'currentColor', strokeWidth: 1.4 }
  return <svg viewBox="0 0 64 64" aria-hidden="true" {...common}>
    {id === 'door' ? <><path d="M15 49V15H49M15 49A34 34 0 0 0 49 15" /><path d="M12 49h6M49 12v6" /></> :
      id === 'window' ? <><path d="M11 21h42v22H11zM11 28h42M11 36h42M32 21v22" /></> :
      id === 'toilet' ? <><rect x="22" y="11" width="20" height="11" rx="2" /><path d="M23 22c-9 25-3 31 9 31s18-6 9-31z" /><ellipse cx="32" cy="36" rx="9" ry="12" /></> :
      id === 'sink' ? <><rect x="11" y="18" width="42" height="33" rx="3" /><ellipse cx="32" cy="35" rx="15" ry="10" /><path d="M29 25v-9h6v9" /></> :
      id === 'bath' ? <><rect x="17" y="8" width="30" height="49" rx="4" /><rect x="21" y="14" width="22" height="37" rx="10" /><circle cx="32" cy="44" r="2" /><path d="M29 8v7h6V8" /></> :
      id === 'shower' ? <><rect x="11" y="11" width="42" height="42" rx="2" /><path d="m11 11 42 42m0-42L11 53" /><circle cx="32" cy="32" r="4" fill="white" /></> :
      id === 'closet' ? <><rect x="9" y="17" width="46" height="30" /><path d="M12 22h40M32 17v30m-5-6v-5m10 0v5" /></> :
      <><rect x="9" y="18" width="46" height="28" /><path d="M12 21h40v22H12zM25 21v22m15-22v22" /></>}
  </svg>
}

export function AssetLibrary({ tab, mode, building, onCommand, layerStop, layerCounts, onLayerStop }: { tab: LibraryTab; mode: '2d' | '3d'; building: Building; onCommand: (commands: ModelCommand[]) => void; layerStop: LayerStop; layerCounts: number[]; onLayerStop: (stop: LayerStop) => void }) {
  const [query, setQuery] = useState('')
  const [environment, setEnvironment] = useState(building.environment)
  useEffect(() => setEnvironment(building.environment), [building.environment])
  const catalog = tab === 'materials' ? materials : tab === 'furniture' ? furniture : fixtures
  const items = catalog.filter(a => a.label.toLowerCase().includes(query.toLowerCase()))
  const saveEnvironment = (value = environment) => onCommand([{ kind: 'set_environment', target_id: '', params: value }])
  return <section className="editor-library" aria-label={tab}>
    {(tab === 'fixtures' || tab === 'furniture' || tab === 'materials') && <div className="editor-library-header">
      <label className="editor-asset-search"><Search size={13} /><input aria-label="Find an asset" placeholder="Search library" value={query} onChange={e => setQuery(e.target.value)} onKeyDown={event => event.stopPropagation()} /></label>
    </div>}
    {tab === 'layers' ? <XrayScrubber stop={layerStop} counts={layerCounts} onChange={onLayerStop} /> : tab === 'site' ? <SitePanel building={building} onCommand={onCommand} /> : tab === 'environment' ? <EnvironmentPanel environment={environment} setEnvironment={setEnvironment} saveEnvironment={saveEnvironment} /> : <>
      <div className="editor-asset-grid">
        {tab === 'furniture' && <button type="button" className="editor-asset editor-asset-imagine" title="Paint a piece into the 3D room" aria-label="Imagine furniture" onClick={requestImagineFurniture}>
          <span className="editor-asset-preview imagine"><Paintbrush size={28} /></span>
          <span>Imagine furniture</span>
        </button>}
        {items.map((asset: Asset) => (
          <button key={asset.id} className="editor-asset" draggable title={`Drag ${asset.label.toLowerCase()} into the ${mode === '2d' ? 'plan' : 'model'}`} onDragStart={event => { event.dataTransfer.setData(assetMime, JSON.stringify(asset)); event.dataTransfer.effectAllowed = 'copy'; window.dispatchEvent(new CustomEvent('archetype:asset-drag', { detail: asset })) }} onDragEnd={() => window.dispatchEvent(new CustomEvent('archetype:asset-drag', { detail: null }))}>
            <span className={`editor-asset-preview ${asset.kind === 'material' ? 'material' : ''}`} style={asset.color ? { background: asset.color } : undefined}>{asset.preview ? <img src={asset.preview} alt="" draggable={false} /> : asset.kind !== 'material' ? <AssetSymbol id={asset.id} /> : null}</span>
            <span>{asset.label}</span>
          </button>
        ))}
      </div>
    </>}
  </section>
}

function EnvironmentPanel({ environment, setEnvironment, saveEnvironment }: {
  environment: Building['environment']
  setEnvironment: (value: Building['environment']) => void
  saveEnvironment: (value?: Building['environment']) => void
}) {
  const setTime = (time: number, persist = false) => {
    const value = { ...environment, time }
    setEnvironment(value)
    if (persist) saveEnvironment(value)
  }
  const setAzimuth = (sun_azimuth: number, persist = false) => {
    const value = { ...environment, sun_azimuth }
    setEnvironment(value)
    if (persist) saveEnvironment(value)
  }
  const setSeason = (season: SeasonId) => {
    const value = { ...environment, season }
    setEnvironment(value)
    saveEnvironment(value)
  }
  return <div className="editor-environment">
    <div className="editor-environment-card">
      <div className="editor-environment-head">
        <span>Time of day</span>
        <output>{formatClock(environment.time)} · {dayPeriod(environment.time)}</output>
      </div>
      <input className="editor-environment-slider time" type="range" aria-label="Time of day" min="0" max="23.75" step=".25" value={environment.time} onChange={e => setTime(Number(e.target.value))} onPointerUp={e => setTime(Number((e.target as HTMLInputElement).value), true)} onKeyUp={e => setTime(Number((e.currentTarget as HTMLInputElement).value), true)} />
      <div className="editor-environment-stops">
        {TIME_STOPS.map(stop => (
          <button key={stop.label} type="button" className={Math.abs(environment.time - stop.time) < 0.26 ? 'active' : ''} onClick={() => setTime(stop.time, true)}>{stop.label}</button>
        ))}
      </div>
    </div>
    <div className="editor-environment-card sun">
      <div className="editor-environment-head">
        <span>Sun</span>
        <output>{environment.sun_azimuth}° {cardinal(environment.sun_azimuth)}</output>
      </div>
      <div className="editor-environment-sun">
        <SunDial azimuth={environment.sun_azimuth} onChange={setAzimuth} />
        <div className="editor-environment-sun-track">
          <input className="editor-environment-slider" type="range" aria-label="Sun direction" min="0" max="360" value={environment.sun_azimuth} onChange={e => setAzimuth(Number(e.target.value))} onPointerUp={e => setAzimuth(Number((e.target as HTMLInputElement).value), true)} onKeyUp={e => setAzimuth(Number((e.currentTarget as HTMLInputElement).value), true)} />
          <div className="editor-environment-stops">
            {SUN_STOPS.map(stop => (
              <button key={stop.label} type="button" className={environment.sun_azimuth === stop.azimuth ? 'active' : ''} onClick={() => setAzimuth(stop.azimuth, true)}>{stop.label}</button>
            ))}
          </div>
        </div>
      </div>
    </div>
    <div className="editor-environment-card season">
      <div className="editor-environment-head">
        <span>Season</span>
        <output>{environment.season[0].toUpperCase() + environment.season.slice(1)}</output>
      </div>
      <div className="editor-environment-seasons" role="radiogroup" aria-label="Season">
        {SEASONS.map(season => (
          <button key={season} type="button" role="radio" aria-checked={environment.season === season} className={environment.season === season ? 'active' : ''} onClick={() => setSeason(season)}>{season[0].toUpperCase() + season.slice(1)}</button>
        ))}
      </div>
    </div>
  </div>
}

function SunDial({ azimuth, onChange }: { azimuth: number; onChange: (azimuth: number, persist?: boolean) => void }) {
  const ref = useRef<SVGSVGElement>(null)
  const point = (event: React.PointerEvent<SVGSVGElement>) => {
    const box = ref.current?.getBoundingClientRect()
    if (!box) return azimuth
    return azimuthFromPoint(event.clientX, event.clientY, box.left + box.width / 2, box.top + box.height / 2)
  }
  return (
    <svg ref={ref} className="editor-sun-dial" viewBox="0 0 72 72" aria-label="Sun compass" role="slider" aria-valuemin={0} aria-valuemax={360} aria-valuenow={azimuth} tabIndex={0}
      onPointerDown={event => { event.currentTarget.setPointerCapture(event.pointerId); onChange(point(event)) }}
      onPointerMove={event => { if (event.currentTarget.hasPointerCapture(event.pointerId)) onChange(point(event)) }}
      onPointerUp={event => { event.currentTarget.releasePointerCapture(event.pointerId); onChange(point(event), true) }}
      onKeyDown={event => {
        const step = event.shiftKey ? 15 : 5
        if (event.key === 'ArrowRight' || event.key === 'ArrowUp') { event.preventDefault(); onChange((azimuth + step) % 360, true) }
        else if (event.key === 'ArrowLeft' || event.key === 'ArrowDown') { event.preventDefault(); onChange((azimuth - step + 360) % 360, true) }
      }}>
      <circle cx="36" cy="36" r="31" />
      <text x="36" y="12">N</text>
      <text x="62" y="39">E</text>
      <text x="36" y="66">S</text>
      <text x="10" y="39">W</text>
      <g transform={`rotate(${azimuth} 36 36)`}>
        <line x1="36" y1="36" x2="36" y2="14" />
        <circle className="sun" cx="36" cy="14" r="5" />
      </g>
    </svg>
  )
}

export default AssetLibrary
