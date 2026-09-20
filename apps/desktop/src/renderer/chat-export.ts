export type ChatIssue = {
  rule_id?: string
  rule_name?: string
  metric?: string
  message?: string
}

export type ChatMessage = {
  role: string
  text?: string
  thinking?: string[]
  new_issues_found?: ChatIssue[]
  fixed_new_issues?: ChatIssue[]
  unfixed_new_issues?: ChatIssue[]
  sources?: {title?: string; note?: string; origin?: string; url?: string; external?: boolean}[]
  rooms?: {name?: string; why?: string; typical_area_sqft?: number; area_sqft?: number}[]
}

function slug(value: string) {
  return value.trim().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '')
}

export function chatExportFilename(projectName?: string, at = new Date()) {
  const stamp = at.toISOString().slice(0, 10)
  return `archetype-chat-${slug(projectName || '') || 'project'}-${stamp}.md`
}

function issueLine(issue: ChatIssue) {
  const title = issue.rule_name || issue.metric?.replaceAll('_', ' ') || issue.rule_id || 'Issue'
  return issue.message ? `- ${title}: ${issue.message}` : `- ${title}`
}

export function formatChatMarkdown(input: {
  projectName?: string
  messages: ChatMessage[]
  exportedAt?: Date
}) {
  const when = (input.exportedAt || new Date()).toISOString().replace('T', ' ').slice(0, 16)
  const title = input.projectName ? `Archetype chat — ${input.projectName}` : 'Archetype chat'
  const parts = [`# ${title}`, '', `Exported ${when} UTC`, '']
  for (const message of input.messages) {
    const speaker = message.role === 'assistant' ? 'Archetype' : message.role === 'user' ? 'You' : message.role
    parts.push(`## ${speaker}`, '')
    const thinking = (message.thinking || []).filter(Boolean)
    if (thinking.length) {
      parts.push('Thinking', '')
      for (const line of thinking) parts.push(`- ${line}`)
      parts.push('')
    }
    parts.push((message.text || '').trim() || '_(empty)_', '')
    const sources = message.sources || []
    if (sources.length) {
      parts.push('Sources', '')
      for (const source of sources) {
        const title = source.title || 'Source'
        const note = source.note ? ` — ${source.note}` : ''
        const href = source.url ? ` (${source.url})` : ''
        parts.push(`- ${title}${note}${href}`)
      }
      parts.push('')
    }
    const rooms = message.rooms || []
    if (rooms.length) {
      parts.push('Rooms', '')
      for (const room of rooms) {
        const area = room.typical_area_sqft || room.area_sqft
        const why = room.why ? ` — ${room.why}` : ''
        parts.push(`- ${room.name || 'Room'}${area ? ` (${Math.round(area)} sq ft)` : ''}${why}`)
      }
      parts.push('')
    }
    const issues = message.new_issues_found || []
    if (!issues.length) continue
    parts.push(`New issues (${issues.length})`, '')
    const fixed = message.fixed_new_issues || []
    const unfixed = message.unfixed_new_issues || []
    if (fixed.length) parts.push('Fixed:', ...fixed.map(issueLine), '')
    if (unfixed.length) parts.push('Still need attention:', ...unfixed.map(issueLine), '')
    if (!fixed.length && !unfixed.length) parts.push(...issues.map(issueLine), '')
  }
  return `${parts.join('\n').trim()}\n`
}

export function downloadTextFile(filename: string, content: string, mime = 'text/markdown;charset=utf-8') {
  const blob = new Blob([content], {type: mime})
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.rel = 'noopener'
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}
