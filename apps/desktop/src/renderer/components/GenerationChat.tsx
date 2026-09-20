import {useEffect, useRef} from 'react'
import {LoaderCircle} from 'lucide-react'
import type {Job} from '../types'
import {citedSources, externalSources, groupedTrace, liveTrace, sourceChipHint, sourceChipLabel, type TraceGroup, type TraceRoom, type TraceSource} from '../generation-trace'

function Brand() {
  return (
    <span className="brand-mark">
      <svg width="25" height="25" viewBox="0 0 28 28" fill="none">
        <path d="M4 21V9L14 3l10 6v12l-10 5L4 21Z M4 9l10 6 10-6M14 15v11M9 6l10 6v11" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round"/>
      </svg>
    </span>
  )
}

export function Sources({sources}: {sources: TraceSource[]}) {
  if (!sources.length) return null
  return (
    <ul className="gen-sources">
      {sources.map(source => {
        const label = sourceChipLabel(source)
        const hint = sourceChipHint(source)
        const chip = <strong>{label}</strong>
        return (
          <li key={source.url || source.title} className={source.external || source.url ? 'external' : ''} title={hint || source.title}>
            {source.url
              ? <a className="gen-source-link" href={source.url} target="_blank" rel="noreferrer">{chip}</a>
              : chip}
          </li>
        )
      })}
    </ul>
  )
}

function Rooms({rooms}: {rooms: TraceRoom[]}) {
  if (!rooms.length) return null
  return (
    <ul className="gen-rooms">
      {rooms.map(room => {
        const area = room.typical_area_sqft || room.area_sqft
        return (
          <li key={`${room.category || ''}-${room.name}`} title={room.why || ''}>
            <strong>{room.name}</strong>
            {area ? <small>{Math.round(area).toLocaleString()} sq ft</small> : null}
          </li>
        )
      })}
    </ul>
  )
}

function Line({text, live}: {text: string; live?: boolean}) {
  return (
    <p className={live ? 'gen-live-line' : undefined}>
      {live && <LoaderCircle size={13} className="spin" />}
      <span>{text}</span>
    </p>
  )
}

export function TraceLog({job, compact, onCancel}: {job: Job; compact?: boolean; onCancel?: () => void}) {
  const groups = groupedTrace(liveTrace(job))
  const live = job.state === 'running' || job.state === 'queued'
  return (
    <div className={compact ? 'thinking-log' : undefined}>
      {groups.map((group, index) => (
        <TraceCard
          key={`${group.kind}-${index}`}
          group={group}
          live={live && index === groups.length - 1}
        />
      ))}
      {onCancel && live && (
        <div className="thinking thinking-actions">
          <button type="button" onClick={onCancel}>Stop</button>
        </div>
      )}
    </div>
  )
}

function TraceCard({group, live}: {group: TraceGroup; live?: boolean}) {
  return (
    <div className={'gen-step gen-kind-' + (group.kind || 'thinking') + (live ? ' live' : '')}>
      <small>{group.label}</small>
      {group.events.map((event, index) => (
        <Line
          key={`${event.message}-${index}`}
          text={event.detail || event.message}
          live={live && index === group.events.length - 1}
        />
      ))}
      <Sources sources={group.events.flatMap(event => event.sources || [])} />
      <Rooms rooms={group.events.flatMap(event => event.rooms || [])} />
    </div>
  )
}

export function ThinkingLines({lines}: {lines?: string[] | null}) {
  if (!lines?.length) return null
  const group: TraceGroup = {
    kind: 'thinking',
    label: 'Thinking',
    events: lines.map(message => ({message, kind: 'thinking', label: 'Thinking'})),
  }
  return <TraceCard group={group} />
}

export function GenerationChat({job}: {job: Job}) {
  const scroller = useRef<HTMLDivElement>(null)
  const found = citedSources(job.events)
  const external = externalSources(found)
  useEffect(() => {
    scroller.current?.scrollTo(0, scroller.current.scrollHeight)
  }, [job.events, job.message])
  return (
    <aside className="generation-chat" aria-label="Generation research">
      <header className="generation-chat-head">
        <span className="assistant-label"><Brand /> Archetype</span>
        <small>Thinking through the building</small>
      </header>
      <div className="messages" ref={scroller}>
        <TraceLog job={job} />
      </div>
      {external.length > 0 && (
        <footer className="generation-sources-dock">
          <small>External sources</small>
          <Sources sources={external} />
        </footer>
      )}
    </aside>
  )
}
