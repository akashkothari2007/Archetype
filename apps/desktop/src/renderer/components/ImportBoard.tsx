import {base} from '../api'
import type {Job} from '../types'

const PHASES = [
  {match: /classif/i, label: 'Classifying'},
  {match: /reading|extract/i, label: 'Reading sheets'},
  {match: /building rooms|build/i, label: 'Building rooms'},
  {match: /rules|standards/i, label: 'Standards'},
  {match: /saving/i, label: 'Saving'},
]

function phaseIndex(job: Job) {
  const text = `${job.phase || ''} ${job.message || ''}`
  const found = PHASES.findIndex(p => p.match.test(text))
  return found < 0 ? 0 : found
}

export function ImportBoard({job, projectId}: {job: Job; projectId?: string | null}) {
  const sheets = job.sheets_done || []
  const totals = job.totals || {}
  const pages = totals.pages || sheets.length
  const read = totals.pages_read || sheets.filter(s => s.extracted).length
  const walls = totals.walls || 0
  const rooms = totals.rooms || 0
  const doors = totals.doors || 0
  const active = phaseIndex(job)
  return (
    <div className="import-board">
      <header className="import-board-head">
        <p className="import-kicker">Reading the set</p>
        <h1>{job.message || 'Importing drawings'}</h1>
        <ol className="import-phases">
          {PHASES.map((phase, i) => (
            <li key={phase.label} className={i === active ? 'active' : i < active ? 'done' : ''}>{phase.label}</li>
          ))}
        </ol>
        <dl className="import-totals">
          <div><dt>Pages read</dt><dd>{read}<small> / {pages || '—'}</small></dd></div>
          <div><dt>Walls</dt><dd>{walls.toLocaleString()}</dd></div>
          <div><dt>Rooms</dt><dd>{rooms.toLocaleString()}</dd></div>
          <div><dt>Doors</dt><dd>{doors.toLocaleString()}</dd></div>
        </dl>
        <div className="progress-track import-track"><div style={{width: `${Math.max(2, job.progress * 100)}%`}} /></div>
      </header>
      <div className="import-grid">
        {sheets.length ? sheets.map(sheet => {
          const thumb = sheet.extracted && sheet.thumb_url && projectId ? `${base}/projects/${projectId}/files/${sheet.thumb_url}?p=${sheet.page}` : ''
          return (
            <article key={sheet.sheet_id} className={'import-card' + (sheet.extracted ? ' extracted' : ' skipped')}>
              <div className="import-thumb">
                {thumb ? <img src={thumb} alt="" /> : <span>{sheet.sheet_no}</span>}
              </div>
              <div className="import-card-meta">
                <strong>{sheet.sheet_no}</strong>
                <em>{sheet.title || sheet.role.replaceAll('_', ' ')}</em>
                {sheet.extracted
                  ? <small>{sheet.walls} walls · {sheet.rooms} rooms</small>
                  : <small className="import-reason">{sheet.reason}</small>}
              </div>
            </article>
          )
        }) : Array.from({length: 12}, (_, i) => <article key={i} className="import-card pending"><div className="import-thumb" /><div className="import-card-meta"><strong>—</strong><em>Waiting on the first page</em></div></article>)}
      </div>
    </div>
  )
}
