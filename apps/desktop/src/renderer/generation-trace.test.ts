import {describe, expect, it} from 'vitest'
import {citedSources, externalSources, generationRecap, groupedTrace, liveTrace, sourceChipHint, sourceChipLabel, traceLabel, visibleTrace} from './generation-trace'

const events = [
  {message: 'Queued', phase: 'queued', progress: 0},
  {kind: 'thinking', label: 'Thinking', message: 'This reads as a hospital.', phase: 'analyzing', progress: 0.06},
  {kind: 'thinking', label: 'Thinking', message: 'Wards above a public lobby, not a house plan.', phase: 'analyzing', progress: 0.08},
  {kind: 'thinking', label: 'Thinking', message: 'The brief names wards and an OR. Those rooms stay.', phase: 'analyzing', progress: 0.1},
  {kind: 'source', label: 'Finding sources', message: 'Found 3 sources.', sources: [
    {title: 'Hospital library', note: 'Wards and ORs'},
    {title: 'Whole Building Design Guide — Hospitals', note: 'Department stacking', url: 'https://www.wbdg.org/building-types/health-care-facilities', external: true},
  ], phase: 'researching', progress: 0.24},
  {kind: 'rooms', label: 'Gathering rooms', message: 'Gathering rooms.', rooms: [{name: 'Ward', typical_area_sqft: 900, why: 'Inpatient'}], phase: 'planning', progress: 0.32},
  {kind: 'working', label: 'Building', message: 'Building walls', phase: 'working', progress: 0.7},
  {kind: 'working', label: 'Building', message: 'Building walls', phase: 'working', progress: 0.7},
]

describe('generation trace', () => {
  it('keeps every thinking line and later stages, dropping only queued noise', () => {
    const shown = visibleTrace(events)
    expect(shown.map(event => event.kind)).toEqual(['thinking', 'thinking', 'thinking', 'source', 'rooms', 'working'])
    expect(shown.filter(event => event.kind === 'thinking').map(event => event.message)).toEqual([
      'This reads as a hospital.',
      'Wards above a public lobby, not a house plan.',
      'The brief names wards and an OR. Those rooms stay.',
    ])
    expect(shown[3].sources?.[0].title).toBe('Hospital library')
  })

  it('groups consecutive thinking into one log instead of replacing the stage', () => {
    const groups = groupedTrace(visibleTrace(events))
    expect(groups.map(group => group.kind)).toEqual(['thinking', 'source', 'rooms', 'working'])
    expect(groups[0].events.map(event => event.message)).toHaveLength(3)
  })

  it('appends the live stage to the log instead of replacing the last thought', () => {
    const live = liveTrace({
      state: 'running',
      message: 'Writing a space program from those rooms',
      phase: 'planning',
      events,
    })
    expect(live.map(event => event.message).slice(-2)).toEqual([
      'Building walls',
      'Writing a space program from those rooms',
    ])
  })

  it('keeps earlier thinking when a new thought arrives', () => {
    const live = liveTrace({
      state: 'running',
      message: 'Those counts are separate rooms on the plan.',
      phase: 'analyzing',
      events: events.slice(0, 3),
    })
    expect(live.filter(event => event.kind === 'thinking').map(event => event.message)).toEqual([
      'This reads as a hospital.',
      'Wards above a public lobby, not a house plan.',
      'Those counts are separate rooms on the plan.',
    ])
    expect(groupedTrace(live)[0].events).toHaveLength(3)
  })

  it('shows phase names in regular case instead of raw slugs', () => {
    expect(traceLabel('analyzing')).toBe('Analyzing')
    expect(traceLabel('preview-ready')).toBe('Preview ready')
    expect(traceLabel('Finding sources')).toBe('Finding sources')
    expect(groupedTrace(visibleTrace([{message: 'Reading the building', phase: 'analyzing'}]))[0].label).toBe('Analyzing')
    expect(groupedTrace(liveTrace({state: 'running', message: 'Reading the building', phase: 'analyzing', events: []}))[0].label).toBe('Analyzing')
  })

  it('keeps untagged job stages as separate log lines', () => {
    const groups = groupedTrace(visibleTrace([
      {message: 'Orchestrator is assigning work', phase: 'planning', progress: 0.2},
      {message: 'Running 1 edit worker', phase: 'working', progress: 0.4},
      {message: 'Validating design', phase: 'working', progress: 0.6},
    ]))
    expect(groups.map(group => group.events[0].message)).toEqual([
      'Orchestrator is assigning work',
      'Running 1 edit worker',
      'Validating design',
    ])
  })

  it('falls back to plain job events when nothing is tagged', () => {
    expect(visibleTrace([{message: 'Preparing your project'}]).map(event => event.message)).toEqual([
      'Preparing your project',
    ])
  })

  it('builds a recap that keeps the full thinking log', () => {
    const recap = generationRecap(
      {events},
      {notes: 'Wards above a public lobby.', research: {blurb: 'A clinical building.', thinking: [
        'This reads as a hospital.',
        'Wards above a public lobby, not a house plan.',
        'The brief names wards and an OR. Those rooms stay.',
      ]}},
    )
    expect(recap).toHaveLength(1)
    expect(recap[0].text).toContain('Wards above a public lobby.')
    expect(recap[0].thinking).toHaveLength(3)
    expect(recap[0].sources?.[0].title).toBe('Hospital library')
    expect(recap[0].rooms?.[0].name).toBe('Ward')
  })

  it('keeps external citations with urls for the chat dock', () => {
    const found = citedSources(events)
    expect(found.map(source => source.title)).toContain('Whole Building Design Guide — Hospitals')
    expect(externalSources(found)[0].url).toContain('wbdg.org')
  })

  it('shortens source cards into chip labels and hover hints', () => {
    expect(sourceChipLabel({title: 'Whole Building Design Guide — Residential'})).toBe('WBDG — Residential')
    expect(sourceChipLabel({title: 'Wikipedia — Vernacular architecture'})).toBe('Vernacular architecture')
    expect(sourceChipHint({
      title: 'Whole Building Design Guide — Residential',
      note: 'Open living-kitchen-dining',
      url: 'https://www.wbdg.org/building-types/residential',
    })).toBe('Open living-kitchen-dining · www.wbdg.org/building-types/residential')
  })
})
