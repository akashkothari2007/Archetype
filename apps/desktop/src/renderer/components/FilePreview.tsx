import {useState} from 'react'
import {FileText, X} from 'lucide-react'
import {projectFileUrl} from '../api'
import type {DesktopProject, SheetCard} from '../types'

function sheetsForFile(project: DesktopProject, file: {path?: string; name?: string}) {
  const parts = (file.path || '').split('/').filter(Boolean)
  const docId = parts[0] === 'sources' ? parts[1] : ''
  const sheets = (project.sheets || []) as SheetCard[]
  if (!docId) return sheets.filter(sheet => sheet.thumb_url || sheet.raster_url)
  return sheets.filter(sheet =>
    sheet.sheet_id.startsWith(docId) && (sheet.raster_url || sheet.thumb_url)
  )
}

function PageImage({projectId, sheet}: {projectId: string; sheet: SheetCard}) {
  const [failed, setFailed] = useState(false)
  const src = projectFileUrl(projectId, sheet.raster_url || sheet.thumb_url || '')
  if (failed || !src) {
    return <div className="file-page-fallback">{sheet.sheet_no}</div>
  }
  return <img src={src} alt={sheet.sheet_no} onError={() => setFailed(true)} />
}

export function FilePreview({
  file,
  project,
  text,
  onClose,
}: {
  file: {name: string; path: string}
  project: DesktopProject
  text: string
  onClose: () => void
}) {
  const pdf = file.name.toLowerCase().endsWith('.pdf')
  const pages = pdf ? sheetsForFile(project, file) : []
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="file-modal" onClick={e => e.stopPropagation()}>
        <header>
          <FileText size={16} />
          {file.name}
          <button type="button" onClick={onClose} aria-label="Close file">
            <X size={18} />
          </button>
        </header>
        {pdf ? (
          pages.length ? (
            <div className="file-pages">
              {pages.map(sheet => (
                <figure key={sheet.sheet_id}>
                  <PageImage projectId={project.project_id} sheet={sheet} />
                  <figcaption>
                    <strong>{sheet.sheet_no}</strong>
                    <span>{sheet.title || sheet.role.replaceAll('_', ' ')}</span>
                  </figcaption>
                </figure>
              ))}
            </div>
          ) : (
            <div className="file-empty">
              <p>
                This PDF is too large to open in the app. Extracted drawing pages
                show here after import; standards files stay as source text only.
              </p>
            </div>
          )
        ) : (
          <pre>{text}</pre>
        )}
      </div>
    </div>
  )
}
