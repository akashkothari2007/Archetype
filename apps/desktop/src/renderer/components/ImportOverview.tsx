import type {ImportSummary} from '../types'

type Target = 'floors' | 'rooms' | 'area' | 'openings' | 'rules' | 'checks' | 'source' | 'open'

const ITEMS: {key: keyof ImportSummary; label: string; hint: string; target: Target; format?: (n: number) => string}[] = [
  {key: 'floors', label: 'Floors', hint: 'Open the plan', target: 'floors'},
  {key: 'rooms', label: 'Rooms', hint: 'Named spaces', target: 'rooms'},
  {key: 'area_sqft', label: 'Area', hint: 'Enclosed floor area', target: 'area', format: n => n.toLocaleString() + ' sq ft'},
  {key: 'doors', label: 'Doors', hint: 'Snapped openings', target: 'openings'},
  {key: 'windows', label: 'Windows', hint: 'On wall centerlines', target: 'openings'},
  {key: 'rules', label: 'Rules', hint: 'From standards', target: 'rules'},
  {key: 'violations', label: 'Violations', hint: 'Current checks', target: 'checks'},
]

export function ImportOverview({summary, onOpen}: {summary: ImportSummary; onOpen: (target: Target) => void}) {
  const seconds = summary.elapsed_s
  const timing = seconds < 10 ? `${seconds.toFixed(1)} s` : `${Math.round(seconds)} s`
  return (
    <div className="import-overview">
      <p className="import-kicker">Imported</p>
      <h1>{summary.name}</h1>
      <p className="import-overview-lead">The drawing set is a building now. {timing} from file to model.</p>
      <ul className="import-stats">
        {ITEMS.map(item => {
          const value = Number(summary[item.key] ?? 0)
          return (
            <li key={item.key}>
              <button type="button" onClick={() => onOpen(item.target)}>
                <span className="import-stat-value">{item.format ? item.format(value) : value.toLocaleString()}</span>
                <span className="import-stat-label">{item.label}</span>
                <span className="import-stat-hint">{item.hint}</span>
              </button>
            </li>
          )
        })}
      </ul>
      <div className="import-overview-actions">
        <button className="primary" onClick={() => onOpen('open')}>Open the editor</button>
        <button className="secondary" onClick={() => onOpen('source')}>Overlay source and model</button>
      </div>
    </div>
  )
}
