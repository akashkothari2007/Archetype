import {useEffect, useMemo, useRef, useState} from 'react'
import {Stage, Layer, Line, Image as KonvaImage, Group, Text} from 'react-konva'
import type {KonvaEventObject} from 'konva/lib/Node'
import {base} from '../api'
import type {DesktopProject, SheetCard} from '../types'

type Geom = {walls?: {a: number[]; b: number[]}[]; size_pt?: number[]; scale_pts_per_ft?: number}

function loadImage(url: string) {
  return new Promise<HTMLImageElement>((resolve, reject) => {
    const image = new window.Image()
    image.crossOrigin = 'anonymous'
    image.onload = () => resolve(image)
    image.onerror = () => reject(new Error('raster'))
    image.src = url
  })
}

export function SourceCompare({project}: {project: DesktopProject}) {
  const host = useRef<HTMLDivElement>(null)
  const [size, setSize] = useState({width: 900, height: 520})
  const [view, setView] = useState({x: 40, y: 40, scale: 12})
  const [fade, setFade] = useState(0)
  const [sheetId, setSheetId] = useState(project.sheets?.find(s => s.extracted)?.sheet_id || project.sheets?.[0]?.sheet_id || '')
  const [raster, setRaster] = useState<HTMLImageElement | null>(null)
  const [geom, setGeom] = useState<Geom | null>(null)
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
  const modelWalls = useMemo(() => {
    if (floorId) {
      const verts = new Map(project.building.vertices.map(v => [v.id, v]))
      return project.building.walls.filter(w => w.floor_id === floorId).map(w => {
        const a = verts.get(w.start_id), b = verts.get(w.end_id)
        return a && b ? [a.x, a.y, b.x, b.y] : null
      }).filter(Boolean) as number[][]
    }
    return (geom?.walls || []).map(w => [w.a[0] / scale, w.a[1] / scale, w.b[0] / scale, w.b[1] / scale])
  }, [project.building, floorId, geom, scale])
  const pane = (size.width - 28) / 2
  useEffect(() => {
    if (size.width < 80) return
    const next = Math.max(.02, Math.min((pane - 48) / world.width, (size.height - 120) / world.height, 40))
    setView({scale: next, x: 36, y: 28})
  }, [sheetId, size.width, size.height, world.width, world.height, pane])
  function panZoom(event: KonvaEventObject<WheelEvent>) {
    event.evt.preventDefault()
    const stage = event.target.getStage()
    const pointer = stage?.getPointerPosition()
    if (event.evt.ctrlKey || event.evt.metaKey) {
      const factor = Math.exp(-event.evt.deltaY * .01)
      const next = Math.max(.02, Math.min(80, view.scale * factor))
      const ax = pointer?.x ?? pane / 2, ay = pointer?.y ?? size.height / 2
      setView({scale: next, x: ax - (ax - view.x) * next / view.scale, y: ay - (ay - view.y) * next / view.scale})
    } else setView(v => ({...v, x: v.x - event.evt.deltaX, y: v.y - event.evt.deltaY}))
  }
  const sourceOpacity = 1 - fade
  const modelOpacity = fade === 0 ? 0 : fade
  const rightSource = fade
  const stroke = 1 / view.scale
  return (
    <div ref={host} className="source-compare">
      <div className="source-toolbar">
        <select aria-label="Drawing sheet" value={sheet?.sheet_id || ''} onChange={e => setSheetId(e.target.value)}>
          {sheets.map((item: SheetCard) => <option key={item.sheet_id} value={item.sheet_id}>{item.sheet_no} · {item.title || item.role}</option>)}
        </select>
        <label className="source-fade">Source
          <input type="range" min="0" max="100" value={Math.round(fade * 100)} onChange={e => setFade(Number(e.target.value) / 100)} aria-label="Fade between source and model" />
          Model
        </label>
      </div>
      <div className="source-panes">
        {[{label: 'Source', source: sourceOpacity, model: modelOpacity}, {label: 'Model', source: rightSource, model: 1}].map((paneView, index) => (
          <div key={paneView.label} className="source-pane">
            <span>{paneView.label}</span>
            <Stage width={pane} height={size.height - 64} x={view.x} y={view.y} scaleX={view.scale} scaleY={view.scale} draggable onDragEnd={e => { const t = e.target; setView(v => ({...v, x: t.x(), y: t.y()})) }} onWheel={panZoom}>
              <Layer>
                {raster && <KonvaImage image={raster} x={0} y={world.height} width={world.width} height={world.height} scaleY={-1} opacity={paneView.source} listening={false} />}
                <Group opacity={paneView.model} listening={false}>
                  {modelWalls.map((pts, i) => <Line key={i} points={pts} stroke="#1c1e1b" strokeWidth={Math.max(stroke, .12)} lineCap="square" perfectDrawEnabled={false} shadowForStrokeEnabled={false} />)}
                </Group>
                {!raster && !modelWalls.length && <Text text={sheet?.reason || 'No geometry for this sheet'} fontSize={12 * stroke} fill="#7d8478" />}
              </Layer>
            </Stage>
            {index === 0 && <small>Scroll to pan · pinch or ctrl-scroll to zoom. Both views stay locked.</small>}
          </div>
        ))}
      </div>
    </div>
  )
}
