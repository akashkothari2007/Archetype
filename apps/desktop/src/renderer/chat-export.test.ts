import {afterEach,describe,expect,it,vi} from 'vitest'
import {chatExportFilename,downloadTextFile,formatChatMarkdown} from './chat-export'

afterEach(()=>{
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('chat export', () => {
  it('slugs the project name into a dated markdown filename', () => {
    expect(chatExportFilename('Willow House', new Date('2026-09-20T12:00:00Z'))).toBe('archetype-chat-willow-house-2026-09-20.md')
    expect(chatExportFilename('  ', new Date('2026-01-02T00:00:00Z'))).toBe('archetype-chat-project-2026-01-02.md')
  })

  it('formats turns, speakers, and issue notes as markdown', () => {
    const md = formatChatMarkdown({
      projectName: 'Willow House',
      exportedAt: new Date('2026-09-20T13:45:00Z'),
      messages: [
        {role: 'user', text: 'Enlarge the kitchen'},
        {
          role: 'assistant',
          text: 'Moved the kitchen wall two feet.',
          new_issues_found: [{metric: 'min_room_area', message: 'Kitchen is under 70 sq ft'}],
          fixed_new_issues: [],
          unfixed_new_issues: [{metric: 'min_room_area', message: 'Kitchen is under 70 sq ft'}],
        },
      ],
    })
    expect(md).toContain('# Archetype chat — Willow House')
    expect(md).toContain('Exported 2026-09-20 13:45 UTC')
    expect(md).toContain('## You')
    expect(md).toContain('Enlarge the kitchen')
    expect(md).toContain('## Archetype')
    expect(md).toContain('Moved the kitchen wall two feet.')
    expect(md).toContain('Still need attention:')
    expect(md).toContain('- min room area: Kitchen is under 70 sq ft')
  })

  it('includes researched sources and rooms in the export', () => {
    const md = formatChatMarkdown({
      projectName: 'Riverside Hospital',
      exportedAt: new Date('2026-09-20T13:45:00Z'),
      messages: [{
        role: 'assistant',
        text: 'Planned as a hospital.',
        thinking: ['This reads as a hospital.', 'Wards stack above a public lobby.'],
        sources: [{title: 'Hospital library', note: 'Wards and ORs', url: 'https://www.wbdg.org/building-types/health-care-facilities', external: true}],
        rooms: [{name: 'Ward', typical_area_sqft: 900, why: 'Inpatient'}],
      }],
    })
    expect(md).toContain('Thinking')
    expect(md).toContain('- This reads as a hospital.')
    expect(md).toContain('Sources')
    expect(md).toContain('- Hospital library — Wards and ORs (https://www.wbdg.org/building-types/health-care-facilities)')
    expect(md).toContain('Rooms')
    expect(md).toContain('- Ward (900 sq ft) — Inpatient')
  })

  it('downloads a markdown file in the browser', () => {
    const click = vi.fn()
    const remove = vi.fn()
    const link = {href: '', download: '', rel: '', click, remove}
    const body = {appendChild: vi.fn(() => link)}
    vi.stubGlobal('document', {createElement: () => link, body})
    vi.stubGlobal('URL', {createObjectURL: () => 'blob:chat', revokeObjectURL: vi.fn()})
    downloadTextFile('chat.md', '# hello')
    expect(link.download).toBe('chat.md')
    expect(body.appendChild).toHaveBeenCalled()
    expect(click).toHaveBeenCalled()
    expect(remove).toHaveBeenCalled()
  })
})
