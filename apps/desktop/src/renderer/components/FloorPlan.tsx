import { useEffect, useMemo, useRef, useState } from 'react'
import { Stage, Layer, Group, Line, Rect, Circle, Text, Shape } from 'react-konva'
import type Konva from 'konva'
import type { KonvaEventObject } from 'konva/lib/Node'
import { MousePointer2, Hand, Ruler, Plus, Minus, Maximize, PencilLine, Scissors, Link, Copy, Trash2, LockKeyhole, RotateCw, Magnet, X } from 'lucide-react'
import { assetMime, distance, floorBounds, interiorPoint, lengthLabel, placementCommand, polygonArea, projectPoint, type Asset, type EditorProps, type Point } from './editor-geometry'
import './editor-view.css'

type Tool = 'select' | 'pan' | 'wall' | 'measure'
export function FloorPlan({ building, floorId, onCommand, selectedId, onSelect, units, busy }: EditorProps) {
  const host = useRef<HTMLDivElement>(null)
  const stage = useRef<Konva.Stage>(null)
  const wallDrag = useRef<{ pointer: Point; a: Point; b: Point } | null>(null)
  const [size, setSize] = useState({ width: 800, height: 600 })
  const [view, setView] = useState({ x: 100, y: 100, scale: 15 })
  const [tool, setTool] = useState<Tool>('select')
  const [snap, setSnap] = useState(true)
  const [selection, setSelection] = useState<string[]>([])
  const [start, setStart] = useState<Point | null>(null)
  const [cursor, setCursor] = useState<Point | null>(null)
  const [marquee, setMarquee] = useState<Point | null>(null)
  const [measurement, setMeasurement] = useState<[Point, Point] | null>(null)
  const [preview, setPreview] = useState<Record<string, Point>>({})
  const [notice, setNotice] = useState('')
  const [unlock, setUnlock] = useState(false)
  const [reason, setReason] = useState('')
  const [structural, setStructural] = useState<'nonstructural' | 'loadbearing' | 'unknown'>('nonstructural')
  const [matching, setMatching] = useState(false)
  const vertices = useMemo(() => new Map(building.vertices.map(v => [v.id, { ...v, ...(preview[v.id] || {}) }])), [building.vertices, preview])
  const walls = building.walls.filter(w => w.floor_id === floorId)
  const rooms = building.rooms.filter(r => r.floor_id === floorId)
  const objects = building.objects.filter(o => o.floor_id === floorId)
  const bounds = useMemo(() => floorBounds(building, floorId), [building, floorId])
  const selectedWall = walls.find(w => w.id === selectedId)
  const selectedOpening = building.openings.find(o => o.id === selectedId)
  const selectedObject = objects.find(o => o.id === selectedId)
  const selectedRoom = rooms.find(r => r.id === selectedId)
  const matchingRooms = selectedRoom?.type_ref ? building.rooms.filter(r => r.type_ref === selectedRoom.type_ref) : []
  useEffect(() => { if (selectedId && !selection.includes(selectedId)) setSelection([selectedId]); if (!selectedId) setSelection([]) }, [selectedId])
  useEffect(() => { setPreview({}) }, [building])
  useEffect(() => {
    if (!host.current) return
    const observer = new ResizeObserver(([entry]) => setSize({ width: entry.contentRect.width, height: entry.contentRect.height }))
    observer.observe(host.current)
    return () => observer.disconnect()
  }, [])
  const fit = () => {
    const scale = Math.max(.02, Math.min((size.width - 160) / bounds.width, (size.height - 160) / bounds.height, 45))
    setView({ scale, x: size.width / 2 - bounds.cx * scale, y: size.height / 2 - bounds.cy * scale })
  }
  const lastFloor = useRef('')
  useEffect(() => { if (size.width > 100 && size.height > 100 && lastFloor.current !== floorId) { fit(); lastFloor.current = floorId } }, [floorId, size, bounds])
  useEffect(() => { if (!notice) return; const t = setTimeout(() => setNotice(''), 4500); return () => clearTimeout(t) }, [notice])
  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      if (['INPUT', 'TEXTAREA', 'SELECT'].includes((event.target as HTMLElement)?.tagName)) return
      if (!host.current?.contains(document.activeElement) && document.activeElement !== document.body) return
      if (event.key === 'Escape') { setStart(null); setMeasurement(null); setMarquee(null); setTool('select'); setUnlock(false) }
      if (event.key.toLowerCase() === 'v') setTool('select')
      if (event.key.toLowerCase() === 'h') setTool('pan')
      if (event.key.toLowerCase() === 'w') setTool('wall')
      if (event.key.toLowerCase() === 'm') setTool('measure')
      if ((event.key === 'Backspace' || event.key === 'Delete') && selection.length) { event.preventDefault(); onCommand(selection.map(id => ({ kind: 'delete', target_id: id, params: {} }))) }
    }
    window.addEventListener('keydown', key)
    return () => window.removeEventListener('keydown', key)
  }, [selection, onCommand])
  function rawPoint() {
    const p = stage.current?.getPointerPosition()
    return p ? { x: (p.x - view.x) / view.scale, y: (p.y - view.y) / view.scale } : { x: 0, y: 0 }
  }
  function snapped(p: Point, anchor?: Point | null, exclude?: string): Point {
    if (!snap) return p
    const threshold = 10 / view.scale
    const exact = [...vertices.values()].filter(v => v.floor_id === floorId && v.id !== exclude).sort((a, b) => distance(a, p) - distance(b, p))[0]
    if (exact && distance(exact, p) < threshold) return { x: exact.x, y: exact.y }
    const step = units === 'metric' ? .1 / .3048 : .25
    let q = { x: Math.round(p.x / step) * step, y: Math.round(p.y / step) * step }
    if (anchor) { if (Math.abs(q.x - anchor.x) < threshold) q.x = anchor.x; if (Math.abs(q.y - anchor.y) < threshold) q.y = anchor.y }
    for (const wall of walls) {
      const a = vertices.get(wall.start_id), b = vertices.get(wall.end_id)
      if (!a || !b || wall.start_id === exclude || wall.end_id === exclude) continue
      const projection = projectPoint(q, a, b)
      if (projection.distance < threshold / 2) { q = { x: projection.x, y: projection.y }; break }
    }
    return q
  }
  function select(id: string, event?: KonvaEventObject<Event>) {
    if (tool !== 'select') return
    if (event) event.cancelBubble = true
    const additive = event && 'shiftKey' in event.evt && event.evt.shiftKey
    setSelection(additive ? selection.includes(id) ? selection.filter(s => s !== id) : [...selection, id] : [id])
    onSelect(id)
  }
  function pointerDown(event: KonvaEventObject<MouseEvent | TouchEvent>) {
    host.current?.focus()
    if ('button' in event.evt && event.evt.button !== 0) return
    const p = snapped(rawPoint(), start)
    if (tool === 'wall' || tool === 'measure') {
      if (!start) { setStart(p); setCursor(p); return }
      if (tool === 'wall' && distance(start, p) > .25) {
        onCommand([{ kind: 'create_wall', target_id: '', params: { floor_id: floorId, x1: start.x, y1: start.y, x2: p.x, y2: p.y, thickness_ft: .5, height_ft: building.floors.find(f => f.id === floorId)?.height_ft || 9 } }])
        setStart(p)
      } else { setMeasurement([start, p]); setStart(null) }
    } else if (tool === 'select' && event.target === stage.current) { onSelect(null); setSelection([]); setMarquee(p); setCursor(p) }
  }
  function pointerUp() {
    if (marquee && cursor && distance(marquee, cursor) > 3 / view.scale) {
      const minX = Math.min(marquee.x, cursor.x), maxX = Math.max(marquee.x, cursor.x), minY = Math.min(marquee.y, cursor.y), maxY = Math.max(marquee.y, cursor.y)
      const contains = (p: Point) => p.x >= minX && p.x <= maxX && p.y >= minY && p.y <= maxY
      const ids = [...walls.filter(w => { const a = vertices.get(w.start_id), b = vertices.get(w.end_id); return a && b && contains(a) && contains(b) }).map(w => w.id), ...objects.filter(contains).map(o => o.id)]
      onSelect(ids[0] || null); setSelection(ids)
    }
    setMarquee(null)
  }
  function zoom(factor: number, anchor = { x: size.width / 2, y: size.height / 2 }) {
    const scale = Math.max(.02, Math.min(120, view.scale * factor))
    setView({ scale, x: anchor.x - (anchor.x - view.x) * scale / view.scale, y: anchor.y - (anchor.y - view.y) * scale / view.scale })
  }
  function rotate(angle: number) {
    const points = selection.flatMap(id => { const w = walls.find(w => w.id === id); return w ? [vertices.get(w.start_id), vertices.get(w.end_id)].filter(Boolean) as Point[] : objects.filter(o => o.id === id) })
    if (!points.length) return
    onCommand([{ kind: 'rotate_selection', target_id: '', params: { ids: selection, angle_deg: angle, cx: points.reduce((s, p) => s + p.x, 0) / points.length, cy: points.reduce((s, p) => s + p.y, 0) / points.length } }])
  }
  const gridStep = view.scale < .5 ? 100 : view.scale < 2 ? 20 : view.scale < 6 ? 5 : view.scale < 15 ? 2 : 1
  const gx0 = Math.floor(-view.x / view.scale / gridStep) * gridStep, gy0 = Math.floor(-view.y / view.scale / gridStep) * gridStep
  const gx1 = (size.width - view.x) / view.scale, gy1 = (size.height - view.y) / view.scale
  const gridX = Array.from({ length: Math.min(200, Math.ceil((gx1 - gx0) / gridStep) + 1) }, (_, i) => gx0 + i * gridStep)
  const gridY = Array.from({ length: Math.min(200, Math.ceil((gy1 - gy0) / gridStep) + 1) }, (_, i) => gy0 + i * gridStep)
  const scaleUnits = units === 'metric' ? .3048 : 1
  const approximate = 80 / view.scale * scaleUnits
  const magnitude = 10 ** Math.floor(Math.log10(approximate))
  const scaleDistance = [1, 2, 5, 10].map(v => v * magnitude).find(v => v >= approximate) || 10 * magnitude
  const stroke = 1 / view.scale
  return <div ref={host} tabIndex={0} className={`editor-floorplan tool-${tool}`} aria-label="2D floor plan editor" onDragOver={e => e.preventDefault()} onDrop={e => {
    e.preventDefault()
    const data = e.dataTransfer.getData(assetMime)
    if (!data) return
    try { const asset = JSON.parse(data) as Asset; const rect = host.current!.getBoundingClientRect(); const p = snapped({ x: (e.clientX - rect.left - view.x) / view.scale, y: (e.clientY - rect.top - view.y) / view.scale }); const command = placementCommand(asset, p, building, floorId); if (command) onCommand([command]); else setNotice('Place this opening on a wall with enough space.') } catch { setNotice('This asset could not be placed.') }
  }}>
    <div className="editor-floating-tools" role="toolbar" aria-label="Drawing tools">
      {[['select', MousePointer2, 'Select · V'], ['pan', Hand, 'Pan · H'], ['wall', PencilLine, 'Draw wall · W'], ['measure', Ruler, 'Measure · M']].map(([id, Icon, title]) => { const I = Icon as typeof MousePointer2; return <button key={id as string} className={tool === id ? 'active' : ''} title={title as string} aria-label={title as string} onClick={() => { setTool(id as Tool); setStart(null) }}><I size={17} /></button> })}
      <span className="editor-tool-divider" /><button className={snap ? 'active' : ''} title="Snap to grid and geometry" aria-label="Toggle snapping" aria-pressed={snap} onClick={() => setSnap(!snap)}><Magnet size={17} /></button>
    </div>
    {selection.length > 0 && <div className="editor-selection-tools" role="toolbar" aria-label="Selection tools">
      <span>{selection.length > 1 ? `${selection.length} selected` : selectedWall ? 'Wall' : selectedOpening?.kind || selectedObject?.asset_id.replaceAll('_', ' ') || selectedRoom?.name || 'Selection'}</span>
      {(selectedWall || selectedObject) && <><button title="Rotate 15°" aria-label="Rotate selection 15 degrees" onClick={() => rotate(15)}><RotateCw size={14} /></button><button title="Duplicate" aria-label="Duplicate selection" onClick={() => onCommand(selection.map(id => ({ kind: 'duplicate', target_id: id, params: { dx: 2, dy: 2 } })))}><Copy size={14} /></button></>}
      {selectedWall && <><button title="Split at midpoint" aria-label="Split wall at midpoint" onClick={() => { const a = vertices.get(selectedWall.start_id), b = vertices.get(selectedWall.end_id); if (a && b) onCommand([{ kind: 'split_wall', target_id: selectedWall.id, params: { offset_ft: distance(a, b) / 2 } }]) }}><Scissors size={14} /></button>{selection.length === 2 && <button title="Join selected walls" aria-label="Join selected walls" onClick={() => onCommand([{ kind: 'join_walls', target_id: selection[0], params: { other_id: selection[1] } }])}><Link size={14} /></button>}</>}
      {!selectedRoom && <button title="Delete" aria-label="Delete selection" onClick={() => onCommand(selection.map(id => ({ kind: 'delete', target_id: id, params: {} })))}><Trash2 size={14} /></button>}
      <button aria-label="Clear selection" onClick={() => onSelect(null)}><X size={13} /></button>
    </div>}
    <Stage ref={stage} width={size.width} height={size.height} x={view.x} y={view.y} scaleX={view.scale} scaleY={view.scale} draggable={tool === 'pan'} onDragEnd={e => { if (e.target === stage.current) setView(v => ({ ...v, x: e.target.x(), y: e.target.y() })) }} onMouseDown={pointerDown} onTouchStart={pointerDown} onMouseMove={() => setCursor(snapped(rawPoint(), start))} onTouchMove={() => setCursor(snapped(rawPoint(), start))} onMouseUp={pointerUp} onTouchEnd={pointerUp} onWheel={e => { e.evt.preventDefault(); const p = stage.current?.getPointerPosition(); if (e.evt.ctrlKey || e.evt.metaKey) zoom(Math.exp(-e.evt.deltaY * .01), p || undefined); else setView(v => ({ ...v, x: v.x - e.evt.deltaX, y: v.y - e.evt.deltaY })) }}>
      <Layer listening={false}>
        {gridX.map(x => <Line key={`x${x}`} points={[x, gy0, x, gy1]} stroke={Math.round(x / gridStep) % 5 ? '#eff0f1' : '#e6e8ea'} strokeWidth={stroke} />)}
        {gridY.map(y => <Line key={`y${y}`} points={[gx0, y, gx1, y]} stroke={Math.round(y / gridStep) % 5 ? '#eff0f1' : '#e6e8ea'} strokeWidth={stroke} />)}
      </Layer>
      <Layer>
        {rooms.map(room => { const center = interiorPoint(room.polygon); return <Group key={room.id} onClick={e => select(room.id, e)} onTap={e => select(room.id, e)}>
          <Line points={room.polygon.flat()} closed fill={selectedId === room.id ? '#eaf2fa' : '#ffffff'} opacity={.86} stroke={room.needs_review ? '#d3ad6a' : undefined} dash={room.needs_review ? [4 * stroke, 4 * stroke] : undefined} strokeWidth={stroke} listening={tool === 'select'} />
          <Text x={center.x - 6} y={center.y - .7} width={12} text={room.name.toUpperCase()} align="center" fontFamily="Inter, -apple-system, sans-serif" fontSize={Math.max(.45, Math.min(.72, 12 / view.scale))} letterSpacing={.04} fill="#33383e" listening={false} />
          <Text x={center.x - 5} y={center.y + .2} width={10} text={`${(polygonArea(room.polygon) * (units === 'metric' ? .092903 : 1)).toFixed(1)} ${units === 'metric' ? 'm²' : 'sq ft'}${room.needs_review ? ' · review' : ''}`} align="center" fontSize={Math.max(.35, Math.min(.6, 10 / view.scale))} fill="#898e95" listening={false} />
        </Group> })}
        {walls.map(wall => {
          const a = vertices.get(wall.start_id), b = vertices.get(wall.end_id)
          if (!a || !b) return null
          const chosen = selection.includes(wall.id), length = distance(a, b), angle = Math.atan2(b.y - a.y, b.x - a.x)
          const normal = { x: -Math.sin(angle), y: Math.cos(angle) }
          return <Group key={wall.id}>
            {chosen && <Line points={[a.x, a.y, b.x, b.y]} stroke="#a7cef8" strokeWidth={wall.thickness_ft + 7 * stroke} listening={false} />}
            <Line points={[a.x, a.y, b.x, b.y]} stroke={chosen ? '#234c76' : '#242628'} strokeWidth={wall.thickness_ft} hitStrokeWidth={Math.max(wall.thickness_ft, 12 * stroke)} lineCap="square" draggable={tool === 'select' && !wall.locked && !busy} onMouseDown={e => { if (tool === 'select') e.cancelBubble = true }} onClick={e => select(wall.id, e)} onTap={e => select(wall.id, e)} onDragStart={e => { e.cancelBubble = true; select(wall.id); wallDrag.current = { pointer: rawPoint(), a: { x: a.x, y: a.y }, b: { x: b.x, y: b.y } } }} onDragMove={e => { e.cancelBubble = true; const drag = wallDrag.current; if (!drag) return; const pointer = rawPoint(); const p = snapped({ x: drag.a.x + pointer.x - drag.pointer.x, y: drag.a.y + pointer.y - drag.pointer.y }, null, a.id); const dx = p.x - drag.a.x, dy = p.y - drag.a.y; setPreview({ [a.id]: p, [b.id]: { x: drag.b.x + dx, y: drag.b.y + dy } }); e.target.position({ x: 0, y: 0 }) }} onDragEnd={e => { e.cancelBubble = true; const original = building.vertices.find(v => v.id === a.id)!; const p = preview[a.id] || a; onCommand([{ kind: 'move_wall', target_id: wall.id, params: { dx: p.x - original.x, dy: p.y - original.y } }]); e.target.position({ x: 0, y: 0 }); setPreview({}) }} />
            {(chosen || length > 5) && <Group listening={false} x={(a.x + b.x) / 2 - normal.x * (wall.thickness_ft / 2 + .55)} y={(a.y + b.y) / 2 - normal.y * (wall.thickness_ft / 2 + .55)} rotation={angle * 180 / Math.PI + (angle > Math.PI / 2 || angle < -Math.PI / 2 ? 180 : 0)}><Text text={lengthLabel(length, units)} x={-3} y={-.27} width={6} align="center" fontSize={Math.max(.28, Math.min(.5, 10 / view.scale))} fill="#72777b" /></Group>}
            {chosen && !wall.locked && [a, b].map(v => <Circle key={v.id} x={v.x} y={v.y} radius={5 * stroke} fill="white" stroke="#397dbb" strokeWidth={1.5 * stroke} draggable onMouseDown={e => { e.cancelBubble = true }} onDragMove={e => { e.cancelBubble = true; const p = snapped(e.target.position(), v.id === a.id ? b : a, v.id); e.target.position(p); setPreview(old => ({ ...old, [v.id]: p })) }} onDragEnd={e => { e.cancelBubble = true; const p = snapped(e.target.position(), v.id === a.id ? b : a, v.id); onCommand([{ kind: 'move_vertex', target_id: v.id, params: p }]); setPreview({}) }} />)}
          </Group>
        })}
        {building.openings.map(opening => {
          const wall = walls.find(w => w.id === opening.wall_id), a = wall && vertices.get(wall.start_id), b = wall && vertices.get(wall.end_id)
          if (!wall || !a || !b) return null
          const angle = Math.atan2(b.y - a.y, b.x - a.x), length = distance(a, b)
          const p = { x: a.x + Math.cos(angle) * opening.offset_ft, y: a.y + Math.sin(angle) * opening.offset_ft }
          const selected = selectedId === opening.id, color = selected ? '#2d81be' : '#282c31'
          return <Group key={opening.id} x={p.x} y={p.y} rotation={angle * 180 / Math.PI} onClick={e => select(opening.id, e)} onTap={e => select(opening.id, e)} draggable={tool === 'select' && !wall.locked && !busy} onMouseDown={e => { if (tool === 'select') e.cancelBubble = true }} onDragEnd={e => { e.cancelBubble = true; const q = projectPoint(e.target.position(), a, b); onCommand([{ kind: 'update_opening', target_id: opening.id, params: { offset_ft: Math.max(0, Math.min(length - opening.width_ft, q.offset)) } }]); e.target.position(p) }}>
            <Rect x={0} y={-wall.thickness_ft / 2 - stroke} width={opening.width_ft} height={wall.thickness_ft + 2 * stroke} fill="white" stroke={selected ? color : undefined} strokeWidth={stroke} />
            {opening.kind === 'window' ? <><Line points={[0, -wall.thickness_ft / 2, opening.width_ft, -wall.thickness_ft / 2, opening.width_ft, wall.thickness_ft / 2, 0, wall.thickness_ft / 2]} closed stroke={color} strokeWidth={stroke} /><Line points={[0, 0, opening.width_ft, 0]} stroke={color} strokeWidth={stroke} /></> : <Group x={opening.hinge === 'right' ? opening.width_ft : 0} scaleX={opening.hinge === 'right' ? -1 : 1} scaleY={opening.swing === 'out' ? -1 : 1}><Line points={[0, 0, 0, opening.width_ft]} stroke={color} strokeWidth={1.5 * stroke} /><Shape stroke={color} strokeWidth={stroke} sceneFunc={(ctx, shape) => { ctx.beginPath(); ctx.arc(0, 0, opening.width_ft, 0, Math.PI / 2); ctx.strokeShape(shape) }} /></Group>}
          </Group>
        })}
        {objects.map(object => <Group key={object.id} x={object.x} y={object.y} rotation={object.rotation_deg} draggable={tool === 'select' && !busy} onMouseDown={e => { if (tool === 'select') e.cancelBubble = true }} onClick={e => select(object.id, e)} onTap={e => select(object.id, e)} onDragEnd={e => { e.cancelBubble = true; const p = snapped(e.target.position()); onCommand([{ kind: 'update_object', target_id: object.id, params: { x: p.x, y: p.y } }]) }}>
          <Rect x={-object.width_ft / 2} y={-object.depth_ft / 2} width={object.width_ft} height={object.depth_ft} fill={selection.includes(object.id) ? '#e9f3ff' : '#fafafa'} stroke={selection.includes(object.id) ? '#4d91c9' : '#74787a'} strokeWidth={stroke} cornerRadius={object.asset_id === 'toilet' || object.asset_id === 'bath' ? Math.min(object.width_ft, object.depth_ft) * .22 : .08} />
          {object.asset_id === 'toilet' || object.asset_id === 'sink' || object.asset_id === 'bath' ? <Rect x={-object.width_ft * .35} y={-object.depth_ft * .32} width={object.width_ft * .7} height={object.depth_ft * .65} cornerRadius={object.width_ft * .25} stroke="#7b7e81" strokeWidth={stroke} /> : <Line points={[-object.width_ft / 2 + .15, -object.depth_ft / 2 + .2, object.width_ft / 2 - .15, -object.depth_ft / 2 + .2]} stroke="#929598" strokeWidth={stroke} />}
        </Group>)}
        {start && cursor && <Group listening={false}><Line points={[start.x, start.y, cursor.x, cursor.y]} stroke={tool === 'wall' ? '#507b9c' : '#b36b98'} strokeWidth={tool === 'wall' ? .5 : stroke} opacity={.6} dash={tool === 'measure' ? [5 * stroke, 4 * stroke] : undefined} /><Circle x={cursor.x} y={cursor.y} radius={4 * stroke} fill="#5283a7" /><Text x={(start.x + cursor.x) / 2} y={(start.y + cursor.y) / 2 - 18 * stroke} text={lengthLabel(distance(start, cursor), units)} fontSize={12 * stroke} fill="#3b688a" /></Group>}
        {measurement && <Group listening={false}><Line points={measurement.flatMap(p => [p.x, p.y])} stroke="#ad6498" strokeWidth={1.5 * stroke} dash={[5 * stroke, 3 * stroke]} /><Text x={(measurement[0].x + measurement[1].x) / 2} y={(measurement[0].y + measurement[1].y) / 2 - 20 * stroke} text={lengthLabel(distance(...measurement), units)} fontSize={12 * stroke} fill="#ad6498" /></Group>}
        {marquee && cursor && <Rect x={Math.min(marquee.x, cursor.x)} y={Math.min(marquee.y, cursor.y)} width={Math.abs(cursor.x - marquee.x)} height={Math.abs(cursor.y - marquee.y)} fill="#438aca18" stroke="#438aca" strokeWidth={stroke} listening={false} />}
      </Layer>
    </Stage>
    {(selectedWall || selectedOpening || selectedObject || selectedRoom) && <div className="editor-properties">
      {selectedWall && <><div className="editor-property-title">Wall properties {selectedWall.locked && <LockKeyhole size={12} />}</div><label>Thickness <DimensionInput value={selectedWall.thickness_ft} units={units} disabled={selectedWall.locked} onSave={value => onCommand([{ kind: 'update_wall', target_id: selectedWall.id, params: { thickness_ft: value } }])} /></label><label>Height <DimensionInput value={selectedWall.height_ft} units={units} disabled={selectedWall.locked} onSave={value => onCommand([{ kind: 'update_wall', target_id: selectedWall.id, params: { height_ft: value } }])} /></label><label>Length <DimensionInput value={distance(vertices.get(selectedWall.start_id)!, vertices.get(selectedWall.end_id)!)} units={units} disabled={selectedWall.locked} onSave={value => { const a = vertices.get(selectedWall.start_id)!, b = vertices.get(selectedWall.end_id)!, ratio = value / distance(a, b); onCommand([{ kind: 'move_vertex', target_id: b.id, params: { x: a.x + (b.x - a.x) * ratio, y: a.y + (b.y - a.y) * ratio } }]) }} /></label>{selectedWall.locked ? <button className="editor-text-action" onClick={() => setUnlock(true)}>Review and unlock…</button> : <span className="editor-property-muted">{selectedWall.structural}</span>}</>}
      {selectedOpening && <><div className="editor-property-title">{selectedOpening.kind === 'door' ? 'Door' : 'Window'}</div><label>Width <DimensionInput value={selectedOpening.width_ft} units={units} onSave={v => onCommand([{ kind: 'update_opening', target_id: selectedOpening.id, params: { width_ft: v } }])} /></label><label>Offset <DimensionInput value={selectedOpening.offset_ft} units={units} onSave={v => onCommand([{ kind: 'update_opening', target_id: selectedOpening.id, params: { offset_ft: v } }])} /></label>{selectedOpening.kind === 'door' && <button className="editor-text-action" onClick={() => onCommand([{ kind: 'update_opening', target_id: selectedOpening.id, params: { hinge: selectedOpening.hinge === 'left' ? 'right' : 'left' } }])}>Flip hinge</button>}</>}
      {selectedObject && <><div className="editor-property-title">Object transform</div><label>Width <DimensionInput value={selectedObject.width_ft} units={units} onSave={v => onCommand([{ kind: 'update_object', target_id: selectedObject.id, params: { width_ft: v } }])} /></label><label>Depth <DimensionInput value={selectedObject.depth_ft} units={units} onSave={v => onCommand([{ kind: 'update_object', target_id: selectedObject.id, params: { depth_ft: v } }])} /></label><label>Rotation <input key={`${selectedObject.id}-${selectedObject.rotation_deg}`} type="number" aria-label="Object rotation" defaultValue={selectedObject.rotation_deg} onBlur={e => { const v = Number(e.target.value); if (Number.isFinite(v) && v !== selectedObject.rotation_deg) onCommand([{ kind: 'update_object', target_id: selectedObject.id, params: { rotation_deg: v } }]) }} /></label></>}
      {selectedRoom && <><div className="editor-property-title">Room</div><input key={selectedRoom.id} aria-label="Room name" defaultValue={selectedRoom.name} onBlur={e => { if (e.target.value && e.target.value !== selectedRoom.name) onCommand((matching ? matchingRooms : [selectedRoom]).map(r => ({ kind: 'rename_room', target_id: r.id, params: { name: e.target.value } }))) }} />{matchingRooms.length > 1 && <label className="editor-match-label"><input type="checkbox" checked={matching} onChange={e => setMatching(e.target.checked)} />Apply to {matchingRooms.length} matching rooms</label>}<span className="editor-property-muted">{selectedRoom.needs_review ? 'Boundary needs review' : 'Shared partitions affect adjacent rooms'}</span></>}
    </div>}
    {unlock && selectedWall && <div className="editor-review-dialog" role="dialog" aria-label="Review wall classification"><strong>Review this wall</strong><p>Confirm the structural classification before enabling edits. Connected walls may still be locked.</p><select aria-label="Structural classification" value={structural} onChange={e => setStructural(e.target.value as typeof structural)}><option value="nonstructural">Nonstructural partition</option><option value="loadbearing">Load-bearing wall</option><option value="unknown">Unknown</option></select><textarea aria-label="Review reason" value={reason} onChange={e => setReason(e.target.value)} placeholder="Record the reason and drawing reference" /><div><button onClick={() => setUnlock(false)}>Cancel</button><button disabled={!reason.trim()} onClick={() => { onCommand([{ kind: 'unlock_wall', target_id: selectedWall.id, params: { structural, reason } }]); setUnlock(false); setReason('') }}>Save review and unlock</button></div></div>}
    <div className="editor-canvas-hint">{tool === 'wall' ? 'Click to start a wall, click to connect · Esc to finish' : tool === 'measure' ? 'Click two points to measure' : tool === 'pan' ? 'Drag to pan · Pinch to zoom' : 'Select to edit · Shift for multiple · Pinch to zoom'}</div>
    {notice && <div className="editor-notice" role="status">{notice}</div>}
    <div className="editor-zoom"><div className="editor-scale"><span style={{ width: scaleDistance / scaleUnits * view.scale }} /><small>{scaleDistance} {units === 'metric' ? 'm' : 'ft'}</small></div><button aria-label="Zoom out" onClick={() => zoom(1 / 1.2)}><Minus size={14} /></button><span>{Math.round(view.scale / 20 * 100)}%</span><button aria-label="Zoom in" onClick={() => zoom(1.2)}><Plus size={14} /></button><button aria-label="Fit floor plan" onClick={fit}><Maximize size={14} /></button></div>
  </div>
}
function DimensionInput({ value, units, onSave, disabled }: { value: number; units: 'metric' | 'imperial'; onSave: (v: number) => void; disabled?: boolean }) {
  const displayed = Number((value * (units === 'metric' ? .3048 : 1)).toFixed(3))
  return <span className="editor-dimension-input"><input key={`${displayed}-${units}`} type="number" step=".1" min="0" defaultValue={displayed} disabled={disabled} onKeyDown={e => { if (e.key === 'Enter') e.currentTarget.blur() }} onBlur={e => { const number = Number(e.target.value); if (Number.isFinite(number) && number >= 0 && number !== displayed) onSave(number / (units === 'metric' ? .3048 : 1)) }} /><small>{units === 'metric' ? 'm' : 'ft'}</small></span>
}
export default FloorPlan
