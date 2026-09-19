import { useEffect, useState } from 'react'
import { Search } from 'lucide-react'
import type { Building, ModelCommand } from '../types'
import { assetMime, fixtures, furniture, materials, type Asset } from './editor-geometry'
import { SitePanel } from './SitePanel'
import './editor-view.css'

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

export function AssetLibrary({ mode, building, onCommand }: { mode: '2d' | '3d'; building: Building; onCommand: (commands: ModelCommand[]) => void }) {
  const [tab, setTab] = useState('assets')
  const [query, setQuery] = useState('')
  const [environment, setEnvironment] = useState(building.environment)
  useEffect(() => setEnvironment(building.environment), [building.environment])
  useEffect(() => setTab('assets'), [mode])
  const items = (tab === 'materials' ? materials : mode === '2d' ? fixtures : furniture).filter(a => a.label.toLowerCase().includes(query.toLowerCase()))
  const saveEnvironment = (value = environment) => onCommand([{ kind: 'set_environment', target_id: '', params: value }])
  return <section className="editor-library" aria-label="Asset library">
    <div className="editor-library-header">
      <div className="editor-tabs" role="tablist" aria-label="Library category">
        <button role="tab" aria-selected={tab === 'assets'} className={tab === 'assets' ? 'active' : ''} onClick={() => setTab('assets')}>{mode === '2d' ? 'Fixtures' : 'Furniture'}</button>
        {mode === '3d' && <><button role="tab" aria-selected={tab === 'materials'} className={tab === 'materials' ? 'active' : ''} onClick={() => setTab('materials')}>Materials</button><button role="tab" aria-selected={tab === 'environment'} className={tab === 'environment' ? 'active' : ''} onClick={() => setTab('environment')}>Environment</button><button role="tab" aria-selected={tab === 'site'} className={tab === 'site' ? 'active' : ''} onClick={() => setTab('site')}>Site</button></>}
      </div>
      {tab !== 'environment' && tab !== 'site' && <label className="editor-asset-search"><Search size={13} /><input aria-label="Find an asset" placeholder="Search library" value={query} onChange={e => setQuery(e.target.value)} /></label>}
    </div>
    {tab === 'site' ? <SitePanel building={building} onCommand={onCommand} /> : tab === 'environment' ? <div className="editor-environment">
      <label>Time of day <output>{Math.floor(environment.time).toString().padStart(2, '0')}:{Math.round(environment.time % 1 * 60).toString().padStart(2, '0')}</output><input type="range" aria-label="Time of day" min="0" max="23.75" step=".25" value={environment.time} onChange={e => setEnvironment({ ...environment, time: Number(e.target.value) })} onPointerUp={() => saveEnvironment()} onKeyUp={() => saveEnvironment()} /></label>
      <label>Sun direction <output>{environment.sun_azimuth}°</output><input type="range" aria-label="Sun direction" min="0" max="360" value={environment.sun_azimuth} onChange={e => setEnvironment({ ...environment, sun_azimuth: Number(e.target.value) })} onPointerUp={() => saveEnvironment()} onKeyUp={() => saveEnvironment()} /></label>
      <label>Season<select aria-label="Season" value={environment.season} onChange={e => { const value = { ...environment, season: e.target.value as Building['environment']['season'] }; setEnvironment(value); saveEnvironment(value) }}>{['spring', 'summer', 'autumn', 'winter'].map(s => <option key={s} value={s}>{s[0].toUpperCase() + s.slice(1)}</option>)}</select></label>
      <p>Lighting is a visual study. Solar position is illustrative.</p>
    </div> : <>
      <div className="editor-asset-grid">{items.map((asset: Asset) => <button key={asset.id} className="editor-asset" draggable title={`Drag ${asset.label.toLowerCase()} into the ${mode === '2d' ? 'plan' : 'model'}`} onDragStart={event => { event.dataTransfer.setData(assetMime, JSON.stringify(asset)); event.dataTransfer.effectAllowed = 'copy'; window.dispatchEvent(new CustomEvent('archetype:asset-drag', { detail: asset })) }} onDragEnd={() => window.dispatchEvent(new CustomEvent('archetype:asset-drag', { detail: null }))}>
        <span className={`editor-asset-preview ${asset.kind === 'material' ? 'material' : ''}`} style={asset.color ? { background: asset.color } : undefined}>{asset.preview ? <img src={asset.preview} alt="" draggable={false} /> : asset.kind !== 'material' ? <AssetSymbol id={asset.id} /> : null}</span><span>{asset.label}</span>
      </button>)}</div>
      <div className="editor-library-hint">{tab === 'materials' ? 'Drag a finish onto a wall or floor' : mode === '2d' ? 'Drag into your plan · Doors and windows snap to walls' : 'Drag into your model · Poly Haven · CC0 licensed'}</div>
    </>}
  </section>
}
export default AssetLibrary
