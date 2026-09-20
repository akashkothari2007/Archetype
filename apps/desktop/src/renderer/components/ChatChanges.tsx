import type { ModelCommand } from '../types'
import { placedCommands, otherCommands, placementPreview } from './chat-placements'
import { AssetSymbol } from './AssetLibrary'
import './editor-view.css'

export { placedCommands, otherCommands, placementPreview }

export function PlacedObjectGrid({commands}: {commands?: ModelCommand[] | null}) {
  const placed = placedCommands(commands)
  if (!placed.length) return null
  return (
    <div className="editor-asset-grid chat-placed-grid" aria-label="Placed objects">
      {placed.map((command, index) => {
        const item = placementPreview(command)
        return (
          <div key={`${item.id}-${index}`} className="editor-asset">
            <span className="editor-asset-preview">
              {item.preview ? <img src={item.preview} alt="" /> : <AssetSymbol id={item.symbol} />}
            </span>
            <span>{item.label}</span>
          </div>
        )
      })}
    </div>
  )
}

export function CommandRows({commands, blocked}: {commands?: ModelCommand[] | null; blocked?: {reason?: string}[] | null}) {
  const other = otherCommands(commands)
  return (
    <>
      {other.map((command, index) => (
        <div className="task-row" key={`${command.kind}-${command.target_id || index}`}>
          {String(command.kind || '').replaceAll('_', ' ')}
          {command.target_id ? <small>{command.target_id}</small> : null}
        </div>
      ))}
      {(blocked || []).map((item, index) => <p key={index} className="blocked">{item.reason}</p>)}
    </>
  )
}
