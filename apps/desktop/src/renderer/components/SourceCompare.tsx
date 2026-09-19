import {useEffect, useMemo, useRef, useState} from 'react'
import {Stage, Layer, Line, Image as KonvaImage, Group, Text} from 'react-konva'
import type {KonvaEventObject} from 'konva/lib/Node'
import {base} from '../api'
import type {DesktopProject, SheetCard} from '../types'
import './editor-view.css'

type Geom = {walls?: {a: number[]; b: number[]}[]; size_pt?: number[]; scale_pts_per_ft?: number}
type Mode = 'overlay' | 'wipe' | 'split'

function loadImage(url: string) {
  return new Promise<HTMLImageElement>((resolve, reject) => {
    const image = new window.Image()
    image.crossOrigin = 'anonymous'
    image.onload = () => resolve(image)
    image.onerror = () => reject(new Error('raster'))
    image.src = url
  })
}

function bbox(lines: number[][]) {
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
  for (const pts of lines) {
    for (let i = 0; i < pts.length; i += 2) {
      minX = Math.min(minX, pts[i]); maxX = Math.max(maxX, pts[i])
      minY = Math.min(minY, pts[i + 1]); maxY = Math.max(maxY, pts[i + 1])
    }
  }
  if (!Number.isFinite(minX)) return null
  return {minX, minY, maxX, maxY, cx: (minX + maxX) / 2, cy: (minY + maxY) / 2}
}

export function SourceCompare({project}: {project: DesktopProject}) {
  const host = useRef<HTMLDivElement>(null)
  const [size, setSize] = useState({width: 900, height: 520})
  const [view, setView] = useState({x: 40, y: 40, scale: 12})
  const [fade, setFade] = useState(0.46)
  const [wipe, setWipe] = useState(0.5)
  const [mode, setMode] = useState<Mode>('overlay')
  const [sheetId, setSheetId] = useState(project.sheets?.find(s => s.extracted)?.sheet_id || project.sheets?.[0]?.sheet_id || '')
  const [raster, setRaster] = useState<HTMLImageElement | null>(null)
  const [geom, setGeom] = useState<Geom | null>(null)
  const draggingWipe = useRef(false)
  const sheets = project.sheets || []
  const sheet = sheets.find(s => s.sheet_id === sheetId) || sheets.find(s => s.extracted) || sheets[0]
  useEffect(() => {
    if (!host.current) return
    const observer = new ResizeObserver(([entry]) => setSize({width: entry.contentRect.width, height: entry.contentRect.height}))
    observer.observe(host.current)
    return () => observer.disconnect()
  }, [])
  useEffect(() => {
    if (!sheet?.raster_url) { setRaster(null); setGeom(null); return }
    let live = true
    loadImage(`${base}/projects/${project.project_id}/files/${sheet.raster_url}`).then(img => { if (live) setRaster(img) }).catch(() => { if (live) setRaster(null) })
    if (sheet.geometry_url) fetch(`${base}/projects/${project.project_id}/files/${sheet.geometry_url}`).then(r => r.json()).then((data: Geom) => { if (live) setGeom(data) }).catch(() => { if (live) setGeom(null) })
    else setGeom(null)
    return () => { live = false }
  }, [sheet?.sheet_id, sheet?.raster_url, sheet?.geometry_url, project.project_id])
  const scale = sheet?.scale_pts_per_ft || geom?.scale_pts_per_ft || 1
  const sizePt = sheet?.size_pt || geom?.size_pt || [100, 80]
  const world = {width: sizePt[0] / scale, height: sizePt[1] / scale}
  const floorId = sheet?.floor_ids?.[0]
  const sheetWalls = useMemo(
    () => (geom?.walls || []).map(w => [w.a[0] / scale, w.a[1] / scale, w.b[0] / scale, w.b[1] / scale]),
    [geom, scale],
  )
  const modelWalls = useMemo(() => {
    if (floorId) {
      const verts = new Map(project.building.vertices.map(v => [v.id, v]))
      return project.building.walls.filter(w => w.floor_id === floorId).map(w => {
        const a = verts.get(w.start_id), b = verts.get(w.end_id)
        return a && b ? [a.x, a.y, b.x, b.y] : null
      }).filter(Boolean) as number[][]
    }
    return sheetWalls
  }, [project.building, floorId, sheetWalls])
  const offset = useMemo(() => {
    const sourceBox = bbox(sheetWalls)
    const modelBox = bbox(modelWalls)
    if (!sourceBox || !modelBox) return null
    const dx = modelBox.minX - sourceBox.minX
    const dy = modelBox.minY - sourceBox.minY
    if (Math.hypot(dx, dy) < 0.5) return null
    return {dx, dy, dist: Math.hypot(dx, dy)}
  }, [sheetWalls, modelWalls])
  const pane = mode === 'split' ? (size.width - 28) / 2 : size.width
  const stageH = size.height - 52
  useEffect(() => {
    if (size.width < 80) return
    const next = Math.max(.02, Math.min((pane - 48) / world.width, (stageH - 48) / world.height, 40))
    setView({scale: next, x: 36, y: 28})
  }, [sheetId, size.width, size.height, world.width, world.height, pane, stageH, mode])
  function panZoom(event: KonvaEventObject<WheelEvent>) {
    event.evt.preventDefault()
    const pointer = event.target.getStage()?.getPointerPosition()
    if (event.evt.ctrlKey || event.evt.metaKey) {
      const factor = Math.exp(-event.evt.deltaY * .01)
      const next = Math.max(.02, Math.min(80, view.scale * factor))
      const ax = pointer?.x ?? pane / 2, ay = pointer?.y ?? stageH / 2
      setView({scale: next, x: ax - (ax - view.x) * next / view.scale, y: ay - (ay - view.y) * next / view.scale})
    } else setView(v => ({...v, x: v.x - event.evt.deltaX, y: v.y - event.evt.deltaY}))
  }
  const stroke = 1 / view.scale
  const cut = (wipe * pane - view.x) / view.scale
  function moveWipe(clientX: number) {
    const rect = host.current?.querySelector('.source-stage')?.getBoundingClientRect()
    if (!rect) return
    setWipe(Math.max(0.02, Math.min(0.98, (clientX - rect.left) / rect.width)))
  }
  function drawStage(sourceOpacity: number, modelOpacity: number, wipeMode = false) {
    const clipLeft = wipeMode ? (ctx: {rect: (x: number, y: number, w: number, h: number) => void}) => ctx.rect(-1e4, -1e4, cut + 1e4, 2e4) : undefined
    const clipRight = wipeMode ? (ctx: {rect: (x: number, y: number, w: number, h: number) => void}) => ctx.rect(cut, -1e4, 1e5, 2e4) : undefined
    return (
      <Stage width={pane} height={stageH} x={view.x} y={view.y} scaleX={view.scale} scaleY={view.scale} draggable onDragStart={e => { if (draggingWipe.current) e.target.stopDrag() }} onDragEnd={e => { const t = e.target; setView(v => ({...v, x: t.x(), y: t.y()})) }} onWheel={panZoom}>
        <Layer listening={false}>
          <Group opacity={sourceOpacity} clipFunc={clipLeft}>
            {raster && <KonvaImage image={raster} x={0} y={world.height} width={world.width} height={world.height} scaleY={-1} listening={false} />}
          </Group>
          <Group opacity={modelOpacity} clipFunc={clipRight} listening={false}>
            {modelWalls.map((pts, i) => <Line key={`m${i}`} points={pts} stroke="#1c1e1b" strokeWidth={Math.max(stroke, .12)} lineCap="square" perfectDrawEnabled={false} shadowForStrokeEnabled={false} />)}
          </Group>
          {!raster && !modelWalls.length && <Text text={sheet?.reason || 'No geometry for this sheet'} fontSize={12 * stroke} fill="#7d8478" />}
        </Layer>
      </Stage>
    )
  }
  return (
    <div ref={host} className="source-compare">
      <div className="source-toolbar">
        <select aria-label="Drawing sheet" value={sheet?.sheet_id || ''} onChange={e => setSheetId(e.target.value)}>
          {sheets.map((item: SheetCard) => <option key={item.sheet_id} value={item.sheet_id}>{item.sheet_no} · {item.title || item.role}</option>)}
        </select>
        <div className="source-modes" role="tablist" aria-label="Compare mode">
          {([['overlay', 'Overlay'], ['wipe', 'Wipe'], ['split', 'Split']] as const).map(([id, label]) => (
            <button key={id} role="tab" aria-selected={mode === id} className={mode === id ? 'active' : ''} onClick={() => setMode(id)}>{label}</button>
          ))}
        </div>
        {mode === 'overlay' && (
          <label className="source-fade">Raster
            <input type="range" min="0" max="100" value={Math.round(fade * 100)} onChange={e => setFade(Number(e.target.value) / 100)} aria-label="Crossfade between raster and reconstructed geometry" />
            Model
          </label>
        )}
        {mode === 'wipe' && <span className="source-fade">Drag the divider · PDF left, model right</span>}
      </div>
      {offset && (
        <div className="source-offset" role="status">
          Registration offset {offset.dx >= 0 ? '+' : ''}{offset.dx.toFixed(2)} ft x, {offset.dy >= 0 ? '+' : ''}{offset.dy.toFixed(2)} ft y · drawn uncorrected
        </div>
      )}
      {mode === 'split' ? (
        <div className="source-panes">
          {[{label: 'Source', source: 1, model: 0}, {label: 'Model', source: 0, model: 1}].map(paneView => (
            <div key={paneView.label} className="source-pane">
              <span>{paneView.label}</span>
              {drawStage(paneView.source, paneView.model)}
            </div>
          ))}
        </div>
      ) : (
        <div className={'source-stage' + (mode === 'wipe' ? ' wiping' : '')}>
          {mode === 'overlay' ? drawStage(1 - fade, fade) : drawStage(1, 1, true)}
          {mode === 'wipe' && (
            <div
              className="source-wipe-handle"
              style={{left: `${wipe * 100}%`}}
              onPointerDown={e => { draggingWipe.current = true; e.currentTarget.setPointerCapture(e.pointerId); moveWipe(e.clientX) }}
              onPointerMove={e => { if (draggingWipe.current) moveWipe(e.clientX) }}
              onPointerUp={() => { draggingWipe.current = false }}
            />
          )}
          <small>Scroll to pan · pinch or ctrl-scroll to zoom. Same sheet, same scale.</small>
        </div>
      )}
    </div>
  )
}
