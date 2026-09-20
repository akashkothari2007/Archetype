export type TraceSource = {
  title: string
  note?: string
  origin?: string
  url?: string
  external?: boolean
}

export type TraceRoom = {
  name: string
  category?: string
  why?: string
  typical_area_sqft?: number
  area_sqft?: number
  floor?: string
  from_brief?: boolean
}

export type TraceEvent = {
  message: string
  phase?: string
  progress?: number
  kind?: string
  label?: string
  detail?: string
  sources?: TraceSource[]
  rooms?: TraceRoom[]
  items?: string[]
}

export type TraceGroup = {
  kind: string
  label: string
  events: TraceEvent[]
}

const TRACE_KINDS = new Set(['thinking', 'research', 'source', 'rooms', 'planning', 'working'])
const PHASE_KIND: Record<string, string> = {
  analyzing: 'thinking',
  researching: 'research',
  planning: 'planning',
  working: 'working',
  validating: 'working',
  saving: 'working',
}

export function traceLabel(value?: string | null) {
  const text = (value || '').trim().replace(/[-_]+/g, ' ')
  if (!text) return 'Working'
  if (/[a-z]/.test(text) && /[A-Z]/.test(text.slice(1))) return text
  return text.charAt(0).toUpperCase() + text.slice(1).toLowerCase()
}

function eventText(event: TraceEvent) {
  return (event.detail || event.message || '').trim()
}

function isQueued(event: TraceEvent) {
  return /^queued$/i.test(eventText(event))
}

export function visibleTrace(events?: TraceEvent[] | null): TraceEvent[] {
  const list = events || []
  const tagged = list.filter(event => event.kind && TRACE_KINDS.has(event.kind))
  const source = (tagged.length ? tagged : list.filter(event => eventText(event))).filter(event => !isQueued(event))
  const out: TraceEvent[] = []
  for (const event of source) {
    const last = out[out.length - 1]
    if (last && (last.kind || '') === (event.kind || '') && eventText(last) === eventText(event)) continue
    out.push(event)
  }
  return out
}

export function liveTrace(job?: {events?: TraceEvent[] | null; message?: string; phase?: string; state?: string} | null): TraceEvent[] {
  const events = visibleTrace(job?.events)
  const live = job?.state === 'running' || job?.state === 'queued'
  const message = (job?.message || '').trim()
  if (!live || !message || (events[events.length - 1] && eventText(events[events.length - 1]) === message)) return events
  const kind = PHASE_KIND[job?.phase || ''] || (job?.phase && TRACE_KINDS.has(job.phase) ? job.phase : 'working')
  return [...events, {message, phase: job?.phase, kind, label: traceLabel(job?.phase || (kind === 'thinking' ? 'Thinking' : 'Working'))}]
}

export function groupedTrace(events?: TraceEvent[] | null): TraceGroup[] {
  const groups: TraceGroup[] = []
  for (const event of events || []) {
    const kind = event.kind || 'working'
    const last = groups[groups.length - 1]
    if (last && last.kind === 'thinking' && event.kind === 'thinking') {
      last.events.push(event)
      continue
    }
    groups.push({
      kind,
      label: traceLabel(event.label || event.kind || event.phase || 'Working'),
      events: [event],
    })
  }
  return groups
}

export function citedSources(events?: TraceEvent[] | null): TraceSource[] {
  const seen = new Set<string>()
  const list: TraceSource[] = []
  for (const source of visibleTrace(events).flatMap(event => event.sources || [])) {
    const key = source.url || source.title
    if (!key || seen.has(key)) continue
    seen.add(key)
    list.push(source)
  }
  return list
}

export function externalSources(sources?: TraceSource[] | null): TraceSource[] {
  return (sources || []).filter(source => source.external || !!source.url)
}

export function sourceChipLabel(source: TraceSource) {
  const title = (source.title || '').trim()
  return title
    .replace(/^Whole Building Design Guide\s*[—–-]\s*/i, 'WBDG — ')
    .replace(/^Wikipedia\s*[—–-]\s*/i, '')
    || title
    || 'Source'
}

export function sourceChipHint(source: TraceSource) {
  const host = (source.url || '').replace(/^https?:\/\//, '').replace(/\/$/, '')
  return [source.note, host].filter(Boolean).join(' · ')
}

export function generationRecap(
  job?: {events?: TraceEvent[]; message?: string} | null,
  result?: {notes?: string; research?: {blurb?: string; thinking?: string[]; label?: string}} | null,
) {
  const events = visibleTrace(job?.events)
  const sources = citedSources(job?.events)
  const rooms = events.flatMap(event => event.rooms || [])
  const thinking = Array.from(new Set(
    (result?.research?.thinking || events.filter(event => event.kind === 'thinking').map(eventText)).filter(Boolean),
  ))
  const notes = (result?.notes || '').trim()
  const blurb = (result?.research?.blurb || '').trim()
  const text = notes || blurb || 'I planned the spaces from your brief.'
  return [{
    role: 'assistant',
    text,
    thinking,
    sources,
    rooms,
    trace: 'recap',
  }]
}
