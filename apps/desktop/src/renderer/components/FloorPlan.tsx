import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Stage, Layer, Group, Line, Rect, Circle, Text, Shape, Image as KonvaImage } from 'react-konva'
import type Konva from 'konva'
import type { KonvaEventObject } from 'konva/lib/Node'
import { MousePointer2, Hand, Ruler, Plus, Minus, Maximize, PencilLine, Scissors, Link, Copy, Trash2, LockKeyhole, RotateCw, Magnet, X, Download, Eye, EyeOff } from 'lucide-react'
import { assetMime, distance, floorBounds, interiorPoint, isTypingTarget, lengthLabel, placementCommand, polygonArea, projectPoint, type Asset, type EditorProps, type Point } from './editor-geometry'
import { computeLayerCounts, type LayerStop } from './plan-layers'
import { base } from '../api'
import type { Check, Floor, SheetCard, MepData, MepDisciplineLayer } from '../types'
import './editor-view.css'

type Tool = 'select' | 'pan' | 'wall' | 'measure'
type CheckHit = Check & { type_ref?: string; instances_affected?: number; affected_space_ids?: string[] }
type SheetGeom = {
  walls?: { a: number[]; b: number[]; cls?: string }[]
  doors?: unknown[]
  windows?: unknown[]
  fixtures?: { xy: number[] }[]
  size_pt?: number[]
  scale_pts_per_ft?: number
  excluded?: { furniture?: number }
  extraction_stats?: { furniture?: number }
}
type FloorPlanProps = EditorProps & {
  checks?: CheckHit[]
  sheets?: SheetCard[]
  projectId?: string
  onFloor?: (id: string) => void
  checkPulse?: number
  layerStop: LayerStop
  onLayerCounts: (counts: number[]) => void
  onExportSchematic?: () => void
}
const revealedSheets = new Set<string>()
const reducedMotion = () => typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches
function loadRaster(url: string) {
  return new Promise<HTMLImageElement>((resolve, reject) => {
    const image = new window.Image()
    image.crossOrigin = 'anonymous'
    image.onload = () => resolve(image)
    image.onerror = () => reject(new Error('raster'))
    image.src = url
  })
}

function roomIdsFor(check: CheckHit) {
  const ids = [...(check.affected_space_ids || []), ...(check.entity_ids || []), check.entity_id]
  return ids.filter(Boolean)
}

function chipName(floor: Floor, index: number) {
  const digits = floor.name.match(/\d+/)
  if (digits) return `L${digits[0]}`
  if (/ground/i.test(floor.name)) return 'G'
  return floor.name.length <= 4 ? floor.name : `L${index + 1}`
}

function stagger(dist: number, maxDist: number, start: number, end: number, duration: number) {
  const window = Math.max(0.05, end - start - duration)
  return start + (maxDist ? dist / maxDist : 0) * window
}

type PlotterSeg = { key: string; d: string; len: number; delay: number; duration: number; width: number; color: string; kind: string }

const PlotterOverlay = memo(function PlotterOverlay({
  segs, labels, fixtures, rooms, view, size, skip,
}: {
  segs: PlotterSeg[]
  labels: { key: string; x: number; y: number; name: string; area: string }[]
  fixtures: { key: string; x: number; y: number }[]
  rooms: { key: string; points: string }[]
  view: { x: number; y: number; scale: number }
  size: { width: number; height: number }
  skip: boolean
}) {
  return (
    <svg className={'plotter-overlay' + (skip ? ' plotter-skip' : '')} width={size.width} height={size.height} aria-hidden>
      <g transform={`translate(${view.x} ${view.y}) scale(${view.scale})`}>
        {rooms.map(room => <polygon key={room.key} points={room.points} fill="#fff" opacity={0.86} />)}
        {segs.map(seg => (
          <path
            key={seg.key}
            className={`plotter-${seg.kind}`}
            d={seg.d}
            stroke={seg.color}
            strokeWidth={seg.width}
            style={{ strokeDasharray: seg.len, strokeDashoffset: skip ? 0 : seg.len, animationDuration: `${seg.duration}s`, animationDelay: `${seg.delay}s` }}
          />
        ))}
        <g className="plotter-fixtures">
          {fixtures.map(item => <circle key={item.key} cx={item.x} cy={item.y} r={0.12} fill="#6d7174" />)}
        </g>
        <g className="plotter-labels">
          {labels.map(label => (
            <text key={label.key} x={label.x} y={label.y} textAnchor="middle" fontSize={0.62} fill="#33383e" fontFamily="Inter, -apple-system, sans-serif">{label.name}<tspan x={label.x} dy={0.85} fontSize={0.42} fill="#898e95">{label.area}</tspan></text>
          ))}
        </g>
      </g>
    </svg>
  )
})

const FixtureDots = memo(function FixtureDots({ fixtures }: { fixtures: { key: string; x: number; y: number }[] }) {
  return <>{fixtures.map(item => <circle key={item.key} cx={item.x} cy={item.y} r={0.11} fill="#6d7174" opacity={0.85} />)}</>
})

const PlanFx = memo(function PlanFx({
  view, size, floorId, hatch, pings, flash, fixtures, showFixtures, pinging, flashing,
}: {
  view: { x: number; y: number; scale: number }
  size: { width: number; height: number }
  floorId: string
  hatch: { id: string; points: string }[]
  pings: { id: string; x: number; y: number; delay: number }[]
  flash: { id: string; points: string }[]
  fixtures: { key: string; x: number; y: number }[]
  showFixtures: boolean
  pinging: boolean
  flashing: boolean
}) {
  return (
    <svg className="plan-fx" width={size.width} height={size.height} aria-hidden>
      <defs>
        <pattern id={`quarantine-hatch-${floorId}`} patternUnits="userSpaceOnUse" width="0.65" height="0.65" patternTransform="rotate(38)">
          <line x1="0" y1="0" x2="0" y2="0.65" stroke="#b7b0a6" strokeWidth="0.08" />
        </pattern>
      </defs>
      <g transform={`translate(${view.x} ${view.y}) scale(${view.scale})`}>
        {hatch.map(room => (
          <polygon key={room.id} className="quarantine-fill" points={room.points} fill={`url(#quarantine-hatch-${floorId})`} stroke="#b7b0a6" strokeWidth={0.06} strokeDasharray="0.35 0.28" />
        ))}
        {flashing && flash.map(room => <polygon key={room.id} className="blast-fill" points={room.points} />)}
        {pinging && pings.map(ping => (
          <circle key={ping.id} className="sonar-ring" cx={ping.x} cy={ping.y} r={9} style={{ animationDelay: `${ping.delay}ms` }} />
        ))}
        {showFixtures && <FixtureDots fixtures={fixtures} />}
      </g>
    </svg>
  )
})

export function FloorPlan({ building, floorId, onCommand, selectedId, onSelect, units, busy, checks = [], sheets, projectId, onFloor, checkPulse = 0, layerStop, onLayerCounts, onExportSchematic }: FloorPlanProps) {
  const host = useRef<HTMLDivElement>(null)
  const stage = useRef<Konva.Stage>(null)
  const wallDrag = useRef<{ pointer: Point; a: Point; b: Point } | null>(null)
  const interacting = useRef(false)
  const interactTimer = useRef(0)
  const lastCheckSig = useRef('')
  const [size, setSize] = useState({ width: 800, height: 600 })
  const [view, setView] = useState({ x: 100, y: 100, scale: 15 })
  const [tool, setTool] = useState<Tool>('select')
  const [spacePanning, setSpacePanning] = useState(false)
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
  const [revealing, setRevealing] = useState(false)
  const [sheetGeom, setSheetGeom] = useState<SheetGeom | null>(null)
  const [raster, setRaster] = useState<HTMLImageElement | null>(null)
  const [sonarKey, setSonarKey] = useState('')
  const [sonarSettled, setSonarSettled] = useState(true)
  const [blastAt, setBlastAt] = useState(0)
  const [shownCount, setShownCount] = useState(0)
  const [mepData, setMepData] = useState<MepData | null>(null)
  const [activeDiscipline, setActiveDiscipline] = useState<string>('architectural')
  const [mepSheetIdx, setMepSheetIdx] = useState(0)
  const [rasterOpacity, setRasterOpacity] = useState(0)
  const sheet = useMemo(() => (sheets || []).find(s => s.extracted && s.floor_ids?.includes(floorId)) || (sheets || []).find(s => s.extracted), [sheets, floorId])
  const revealKey = sheet?.sheet_id || floorId
  const baseVertices = useMemo(() => new Map(building.vertices.map(v => [v.id, v])), [building.vertices])
  const vertexAt = useCallback((id: string) => {
    const v = baseVertices.get(id); if (!v) return undefined
    const p = preview[id]; return p ? { ...v, ...p } : v
  }, [baseVertices, preview])
  const floorWalls = useMemo(() => building.walls.filter(w => w.floor_id === floorId), [building.walls, floorId])
  const rooms = useMemo(() => building.rooms.filter(r => r.floor_id === floorId), [building.rooms, floorId])
  const floorObjects = useMemo(() => building.objects.filter(o => o.floor_id === floorId), [building.objects, floorId])
  const walls = floorWalls.filter(w => w.structural === 'loadbearing' || layerStop >= 1)
  const openingsVisible = layerStop >= 2
  const fixturesVisible = layerStop >= 3
  const furnitureVisible = layerStop >= 4
  const objects = floorObjects.filter(o => {
    const fixture = o.kind === 'fixture' || ['toilet', 'sink', 'bath', 'shower', 'closet', 'counter'].includes(o.asset_id)
    return fixture ? fixturesVisible : furnitureVisible
  })
  const bounds = useMemo(() => floorBounds(building, floorId), [building, floorId])
  const selectedWall = floorWalls.find(w => w.id === selectedId)
  const selectedOpening = building.openings.find(o => o.id === selectedId)
  const selectedObject = floorObjects.find(o => o.id === selectedId)
  const selectedRoom = rooms.find(r => r.id === selectedId)
  const matchingRooms = selectedRoom?.type_ref ? building.rooms.filter(r => r.type_ref === selectedRoom.type_ref) : []
  const scale = sheet?.scale_pts_per_ft || sheetGeom?.scale_pts_per_ft || 1
  const sizePt = sheet?.size_pt || sheetGeom?.size_pt || [0, 0]
  const world = { width: sizePt[0] / scale, height: sizePt[1] / scale }
  useEffect(() => { if (selectedId && !selection.includes(selectedId)) setSelection([selectedId]); if (!selectedId) setSelection([]) }, [selectedId])
  useEffect(() => { setPreview({}) }, [building])
  useEffect(() => {
    if (!host.current) return
    const observer = new ResizeObserver(([entry]) => setSize({ width: entry.contentRect.width, height: entry.contentRect.height }))
    observer.observe(host.current)
    return () => observer.disconnect()
  }, [])
  const fit = () => {
    const scaleFit = Math.max(.02, Math.min((size.width - 160) / bounds.width, (size.height - 160) / bounds.height, 45))
    setView({ scale: scaleFit, x: size.width / 2 - bounds.cx * scaleFit, y: size.height / 2 - bounds.cy * scaleFit })
  }
  const lastFloor = useRef('')
  useEffect(() => { if (size.width > 100 && size.height > 100 && lastFloor.current !== floorId) { fit(); lastFloor.current = floorId } }, [floorId, size, bounds])
  useEffect(() => { if (!notice) return; const t = setTimeout(() => setNotice(''), 4500); return () => clearTimeout(t) }, [notice])
  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      if (isTypingTarget(event.target) || isTypingTarget(document.activeElement)) return
      if (!host.current?.contains(document.activeElement)) return
      if (event.code === 'Space') { event.preventDefault(); setSpacePanning(true); return }
      if (event.key === 'Escape') { setStart(null); setMeasurement(null); setMarquee(null); setTool('select'); setUnlock(false) }
      if (event.key.toLowerCase() === 'v') setTool('select')
      if (event.key.toLowerCase() === 'h') setTool('pan')
      if (event.key.toLowerCase() === 'w') setTool('wall')
      if (event.key.toLowerCase() === 'm') setTool('measure')
      if ((event.key === 'Backspace' || event.key === 'Delete') && selection.length) { event.preventDefault(); onCommand(selection.map(id => ({ kind: 'delete', target_id: id, params: {} }))) }
    }
    const keyUp = (event: KeyboardEvent) => { if (event.code === 'Space') setSpacePanning(false) }
    const release = () => setSpacePanning(false)
    window.addEventListener('keydown', key)
    window.addEventListener('keyup', keyUp)
    window.addEventListener('blur', release)
    return () => { window.removeEventListener('keydown', key); window.removeEventListener('keyup', keyUp); window.removeEventListener('blur', release) }
  }, [selection, onCommand])
  useEffect(() => {
    if (!sheet?.geometry_url || !projectId) { setSheetGeom(null); setRaster(null); return }
    let live = true
    fetch(`${base}/projects/${projectId}/files/${sheet.geometry_url}`).then(r => r.json()).then((data: SheetGeom) => { if (live) setSheetGeom(data) }).catch(() => { if (live) setSheetGeom(null) })
    if (sheet.raster_url) loadRaster(`${base}/projects/${projectId}/files/${sheet.raster_url}`).then(img => { if (live) setRaster(img) }).catch(() => { if (live) setRaster(null) })
    else setRaster(null)
    return () => { live = false }
  }, [sheet?.sheet_id, sheet?.geometry_url, sheet?.raster_url, projectId])
  // Fetch mep.json once when project loads
  useEffect(() => {
    if (!projectId) { setMepData(null); return }
    let live = true
    fetch(`${base}/projects/${projectId}/mep`).then(r => r.json()).then((data: MepData) => {
      if (live && data.floors?.length) setMepData(data); else if (live) setMepData(null)
    }).catch(() => { if (live) setMepData(null) })
    return () => { live = false }
  }, [projectId])
  const mepFloor = useMemo(() => mepData?.floors?.find(f => f.floor_id === floorId) || mepData?.floors?.[0] || null, [mepData, floorId])
  const availableDisciplines = useMemo(() => {
    const set = new Set<string>(['architectural'])
    if (mepFloor) for (const d of mepFloor.disciplines) set.add(d.discipline)
    return [...set]
  }, [mepFloor])
  // One sheet list per discipline — show the PDF raster as a simple panel image
  const mepSheets: MepDisciplineLayer[] = useMemo(() => {
    if (activeDiscipline === 'architectural' || !mepFloor) return []
    return mepFloor.disciplines
      .filter(d => d.discipline === activeDiscipline && d.raster_url)
      .sort((a, b) => (b.equipment?.length || 0) - (a.equipment?.length || 0))
  }, [activeDiscipline, mepFloor])
  const mepSheet = mepSheets[Math.min(mepSheetIdx, Math.max(0, mepSheets.length - 1))] || null
  const mepSrc = mepSheet?.raster_url && projectId ? `${base}/projects/${projectId}/files/${mepSheet.raster_url}` : ''
  useEffect(() => { setMepSheetIdx(0) }, [activeDiscipline, floorId])
  useEffect(() => {
    if (!availableDisciplines.includes(activeDiscipline)) setActiveDiscipline('architectural')
  }, [availableDisciplines, activeDiscipline])
  useEffect(() => {
    // Keep the floor plan visible immediately when entering the editor.
    setRevealing(false)
  }, [revealKey, floorWalls.length])
  useEffect(() => {
    if (!revealing || !import.meta.env.DEV) return
    let frames = 0, last = performance.now(), min = 120
    let raf = 0
    const tick = (now: number) => {
      frames++
      if (now - last >= 400) { min = Math.min(min, (frames * 1000) / (now - last)); frames = 0; last = now }
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => { cancelAnimationFrame(raf); console.debug(`[plotter] ${revealKey} min ~${min.toFixed(0)} fps`) }
  }, [revealing, revealKey])
  const failChecks = useMemo(() => (checks || []).filter(c => c.status === 'fail'), [checks])
  const quarantineChecks = useMemo(() => (checks || []).filter(c => c.status === 'quarantined'), [checks])
  const failRoomIds = useMemo(() => {
    const ids = new Set<string>()
    for (const check of failChecks) {
      for (const id of roomIdsFor(check)) ids.add(id)
      if (check.type_ref) for (const room of rooms) if (room.type_ref === check.type_ref) ids.add(room.id)
    }
    return ids
  }, [failChecks, rooms])
  const quarantineIds = useMemo(() => {
    const ids = new Set<string>()
    for (const check of quarantineChecks) for (const id of roomIdsFor(check)) ids.add(id)
    for (const room of rooms) if (room.reliability === 'suspect') ids.add(room.id)
    return ids
  }, [quarantineChecks, rooms])
  useEffect(() => {
    const sig = failChecks.map(c => c.id).sort().join(',')
    if (sig === lastCheckSig.current) return
    lastCheckSig.current = sig
    if (!sig || reducedMotion() || interacting.current) { setSonarKey(''); setSonarSettled(true); return }
    setSonarKey(sig)
    setSonarSettled(false)
  }, [failChecks])
  const pingRooms = useMemo(() => {
    if (!sonarKey) return []
    const seen = new Set<string>()
    const ordered: { id: string; x: number; y: number; delay: number }[] = []
    const ranked = [...failChecks].sort((a, b) => (b.instances_affected || 0) - (a.instances_affected || 0))
    for (const check of ranked) {
      const typed = check.type_ref ? rooms.filter(r => r.type_ref === check.type_ref) : []
      const group = typed.length ? typed : rooms.filter(r => roomIdsFor(check).includes(r.id))
      for (const room of group) {
        if (seen.has(room.id) || quarantineIds.has(room.id)) continue
        seen.add(room.id)
        const c = interiorPoint(room.polygon)
        ordered.push({ id: room.id, x: c.x, y: c.y, delay: ordered.length * 60 })
      }
    }
    return ordered
  }, [rooms, quarantineIds, failChecks, sonarKey])
  useEffect(() => {
    if (!sonarKey || !pingRooms.length) { setSonarSettled(true); return }
    const wait = (pingRooms.length - 1) * 60 + 900
    const t = window.setTimeout(() => setSonarSettled(true), wait)
    return () => window.clearTimeout(t)
  }, [sonarKey, pingRooms.length])
  const activeCheck = useMemo(() => {
    if (!selectedId) return undefined
    return failChecks.find(c => c.entity_id === selectedId || (c.entity_ids || []).includes(selectedId) || (c.affected_space_ids || []).includes(selectedId))
      || quarantineChecks.find(c => c.entity_id === selectedId || (c.entity_ids || []).includes(selectedId))
  }, [failChecks, quarantineChecks, selectedId])
  const blastCheck = activeCheck?.status === 'fail' ? activeCheck : undefined
  const blastRooms = useMemo(() => {
    if (!blastCheck) return []
    const typeRef = blastCheck.type_ref
    if (typeRef) return building.rooms.filter(r => r.type_ref === typeRef)
    const ids = new Set(roomIdsFor(blastCheck))
    return building.rooms.filter(r => ids.has(r.id))
  }, [blastCheck, building.rooms])
  const blastHere = blastRooms.filter(r => r.floor_id === floorId)
  const blastCount = blastCheck?.instances_affected || blastRooms.length
  useEffect(() => {
    if (!checkPulse || !blastCheck) return
    setBlastAt(checkPulse)
  }, [checkPulse, blastCheck])
  useEffect(() => {
    if (!blastAt || !blastCount) { setShownCount(0); return }
    if (reducedMotion()) { setShownCount(blastCount); return }
    let n = 0
    const step = Math.max(1, Math.ceil(blastCount / 16))
    const id = window.setInterval(() => {
      n = Math.min(blastCount, n + step)
      setShownCount(n)
      if (n >= blastCount) window.clearInterval(id)
    }, 28)
    return () => window.clearInterval(id)
  }, [blastAt, blastCount])
  const otherFloors = useMemo(() => {
    const counts = new Map<string, number>()
    for (const room of blastRooms) if (room.floor_id !== floorId) counts.set(room.floor_id, (counts.get(room.floor_id) || 0) + 1)
    return building.floors.map((floor, i) => ({ floor, i, count: counts.get(floor.id) || 0 })).filter(item => item.count)
  }, [blastRooms, building.floors, floorId])
  const plotter = useMemo(() => {
    const cx = bounds.cx, cy = bounds.cy
    const wallsRaw: (PlotterSeg & { dist: number })[] = []
    for (const wall of floorWalls) {
      const a = baseVertices.get(wall.start_id), b = baseVertices.get(wall.end_id)
      if (!a || !b) continue
      const len = Math.hypot(b.x - a.x, b.y - a.y)
      wallsRaw.push({ key: wall.id, kind: 'wall', d: `M${a.x} ${a.y}L${b.x} ${b.y}`, len, width: wall.thickness_ft, color: '#242628', delay: 0, duration: 0.45, dist: Math.hypot((a.x + b.x) / 2 - cx, (a.y + b.y) / 2 - cy) })
    }
    const openingsRaw: (PlotterSeg & { dist: number })[] = []
    for (const opening of building.openings) {
      const wall = floorWalls.find(w => w.id === opening.wall_id)
      const a = wall && baseVertices.get(wall.start_id), b = wall && baseVertices.get(wall.end_id)
      if (!wall || !a || !b) continue
      const angle = Math.atan2(b.y - a.y, b.x - a.x)
      const x1 = a.x + Math.cos(angle) * opening.offset_ft, y1 = a.y + Math.sin(angle) * opening.offset_ft
      const x2 = x1 + Math.cos(angle) * opening.width_ft, y2 = y1 + Math.sin(angle) * opening.width_ft
      const len = opening.width_ft || Math.hypot(x2 - x1, y2 - y1)
      openingsRaw.push({ key: opening.id, kind: opening.kind, d: `M${x1} ${y1}L${x2} ${y2}`, len, width: Math.max(wall.thickness_ft * 0.35, 0.08), color: '#282c31', delay: 0, duration: 0.28, dist: Math.hypot((x1 + x2) / 2 - cx, (y1 + y2) / 2 - cy) })
    }
    const maxWall = Math.max(0.001, ...wallsRaw.map(s => s.dist))
    const segs: PlotterSeg[] = wallsRaw.map(s => ({ ...s, delay: stagger(s.dist, maxWall, 0, 1.2, 0.45), duration: 0.45 }))
    const maxOpen = Math.max(0.001, ...openingsRaw.map(s => s.dist), 0.001)
    for (const s of openingsRaw) {
      const door = s.kind === 'door'
      segs.push({ ...s, delay: stagger(s.dist, maxOpen, door ? 1.0 : 1.2, door ? 1.6 : 1.7, 0.28), duration: 0.28 })
    }
    const labels = rooms.map(room => {
      const c = interiorPoint(room.polygon)
      const area = `${(polygonArea(room.polygon) * (units === 'metric' ? .092903 : 1)).toFixed(1)} ${units === 'metric' ? 'm²' : 'sq ft'}`
      return { key: room.id, x: c.x, y: c.y, name: room.name.toUpperCase() + ((room.instance_count || 0) > 1 ? `  ×${room.instance_count}` : ''), area }
    })
    const roomPolys = rooms.map(room => ({ key: room.id, points: room.polygon.map(p => p.join(',')).join(' ') }))
    return { segs, labels, roomPolys }
  }, [floorWalls, building.openings, rooms, baseVertices, bounds.cx, bounds.cy, units])
  const sheetFixtures = useMemo(() => (sheetGeom?.fixtures || []).map((item, i) => ({ key: `fx${i}`, x: item.xy[0] / scale, y: item.xy[1] / scale })), [sheetGeom, scale])
  const layerCounts = useMemo(() => computeLayerCounts({
    sheetWalls: sheetGeom?.walls,
    sheetDoors: sheetGeom?.doors?.length,
    sheetWindows: sheetGeom?.windows?.length,
    sheetFixtures: sheetGeom?.fixtures?.length,
    sheetFurniture: sheetGeom?.excluded?.furniture || sheetGeom?.extraction_stats?.furniture,
    floorWalls,
    floorOpenings: building.openings.filter(o => floorWalls.some(w => w.id === o.wall_id)).length,
    floorFixtures: floorObjects.filter(o => o.kind === 'fixture').length,
    floorFurniture: floorObjects.filter(o => o.kind !== 'fixture').length,
  }), [sheetGeom, floorWalls, building.openings, floorObjects])
  const countsSig = layerCounts.join(',')
  useEffect(() => { onLayerCounts(layerCounts) }, [countsSig, onLayerCounts])
  function markInteract() {
    interacting.current = true
    host.current?.classList.add('is-interacting')
    if (revealing) { revealedSheets.add(revealKey); setRevealing(false) }
    window.clearTimeout(interactTimer.current)
    interactTimer.current = window.setTimeout(() => {
      interacting.current = false
      host.current?.classList.remove('is-interacting')
    }, 200)
  }
  function rawPoint() {
    const p = stage.current?.getPointerPosition()
    return p ? { x: (p.x - view.x) / view.scale, y: (p.y - view.y) / view.scale } : { x: 0, y: 0 }
  }
  function snapped(p: Point, anchor?: Point | null, exclude?: string): Point {
    if (!snap) return p
    const threshold = 10 / view.scale
    let exact: ReturnType<typeof vertexAt> | undefined
    let best = Infinity
    for (const v of baseVertices.values()) {
      if (v.floor_id !== floorId || v.id === exclude) continue
      const point = vertexAt(v.id)
      if (!point) continue
      const d = distance(point, p)
      if (d < best) { best = d; exact = point }
    }
    if (exact && best < threshold) return { x: exact.x, y: exact.y }
    const step = units === 'metric' ? .1 / .3048 : .25
    let q = { x: Math.round(p.x / step) * step, y: Math.round(p.y / step) * step }
    if (anchor) { if (Math.abs(q.x - anchor.x) < threshold) q.x = anchor.x; if (Math.abs(q.y - anchor.y) < threshold) q.y = anchor.y }
    for (const wall of floorWalls) {
      const a = vertexAt(wall.start_id), b = vertexAt(wall.end_id)
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
    if (spacePanning) return
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
      const ids = [...walls.filter(w => { const a = vertexAt(w.start_id), b = vertexAt(w.end_id); return a && b && contains(a) && contains(b) }).map(w => w.id), ...objects.filter(contains).map(o => o.id)]
      onSelect(ids[0] || null); setSelection(ids)
    }
    setMarquee(null)
  }
  function zoom(factor: number, anchor = { x: size.width / 2, y: size.height / 2 }) {
    markInteract()
    const next = Math.max(.02, Math.min(120, view.scale * factor))
    setView({ scale: next, x: anchor.x - (anchor.x - view.x) * next / view.scale, y: anchor.y - (anchor.y - view.y) * next / view.scale })
  }
  function rotate(angle: number) {
    const points = selection.flatMap(id => { const w = walls.find(w => w.id === id); return w ? [vertexAt(w.start_id), vertexAt(w.end_id)].filter(Boolean) as Point[] : objects.filter(o => o.id === id) })
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
  const showModel = !revealing
  const hatch = rooms.filter(r => quarantineIds.has(r.id)).map(r => ({ id: r.id, points: r.polygon.map(p => p.join(',')).join(' ') }))
  const flash = blastHere.map(r => ({ id: r.id, points: r.polygon.map(p => p.join(',')).join(' ') }))
  return <div ref={host} tabIndex={0} className={`editor-floorplan tool-${tool}${spacePanning ? ' space-panning' : ''}`} aria-label="2D floor plan editor" onDragOver={e => e.preventDefault()} onDrop={e => {
    e.preventDefault()
    const data = e.dataTransfer.getData(assetMime)
    if (!data) return
    try { const asset = JSON.parse(data) as Asset; const rect = host.current!.getBoundingClientRect(); const p = snapped({ x: (e.clientX - rect.left - view.x) / view.scale, y: (e.clientY - rect.top - view.y) / view.scale }); const command = placementCommand(asset, p, building, floorId); if (command) onCommand([command]); else setNotice('Place this opening on a wall with enough space.') } catch { setNotice('This asset could not be placed.') }
  }}>
    <div className="editor-floating-tools" role="toolbar" aria-label="Drawing tools">
      {[['select', MousePointer2, 'Select · V'], ['pan', Hand, 'Pan · H'], ['wall', PencilLine, 'Draw wall · W'], ['measure', Ruler, 'Measure · M']].map(([id, Icon, title]) => { const I = Icon as typeof MousePointer2; return <button key={id as string} className={tool === id ? 'active' : ''} title={title as string} aria-label={title as string} onClick={() => { setTool(id as Tool); setStart(null) }}><I size={17} /></button> })}
      <span className="editor-tool-divider" /><button className={snap ? 'active' : ''} title="Snap to grid and geometry" aria-label="Toggle snapping" aria-pressed={snap} onClick={() => setSnap(!snap)}><Magnet size={17} /></button>
      {onExportSchematic && <><span className="editor-tool-divider" /><button title="Export schematic" aria-label="Export schematic" onClick={() => onExportSchematic()}><Download size={16} /></button></>}
    </div>
    {(raster || mepSrc) && activeDiscipline === 'architectural' && <div className="mep-overlay-bar" onPointerDown={markInteract}>
      {raster && <div className="xray-raster">
        <button type="button" title="Toggle source raster" onClick={() => setRasterOpacity(o => o > 0 ? 0 : 0.3)}>{rasterOpacity > 0 ? <Eye size={11} /> : <EyeOff size={11} />}</button>
        <span>Raster</span>
        <input type="range" min={0} max={0.8} step={0.05} value={rasterOpacity} aria-label="Raster opacity" onChange={e => setRasterOpacity(Number(e.target.value))} />
      </div>}
    </div>}
    {availableDisciplines.length > 1 && <div className="discipline-tabs">
      {availableDisciplines.map(d => (
        <button key={d} type="button" className={activeDiscipline === d ? 'active' : ''} onClick={() => setActiveDiscipline(d)}>{d.charAt(0).toUpperCase() + d.slice(1)}</button>
      ))}
    </div>}
    {activeDiscipline !== 'architectural' && (
      <div className="mep-sheet-viewer">
        <div className="mep-sheet-toolbar">
          <button type="button" disabled={mepSheets.length < 2} onClick={() => setMepSheetIdx(i => (i - 1 + mepSheets.length) % mepSheets.length)}>‹</button>
          <span>{activeDiscipline} · sheet {mepSheets.length ? mepSheetIdx + 1 : 0}/{mepSheets.length}</span>
          <button type="button" disabled={mepSheets.length < 2} onClick={() => setMepSheetIdx(i => (i + 1) % mepSheets.length)}>›</button>
        </div>
        {mepSrc
          ? <img key={mepSrc} src={mepSrc} alt={`${activeDiscipline} sheet`} />
          : <div className="mep-sheet-empty">No {activeDiscipline} sheet for this floor</div>}
      </div>
    )}
    {selection.length > 0 && activeDiscipline === 'architectural' && <div className="editor-selection-tools" role="toolbar" aria-label="Selection tools">
      <span>{selection.length > 1 ? `${selection.length} selected` : selectedWall ? 'Wall' : selectedOpening?.kind || selectedObject?.asset_id.replaceAll('_', ' ') || selectedRoom?.name || 'Selection'}</span>
      {(selectedWall || selectedObject) && <><button title="Rotate 15°" aria-label="Rotate selection 15 degrees" onClick={() => rotate(15)}><RotateCw size={14} /></button><button title="Duplicate" aria-label="Duplicate selection" onClick={() => onCommand(selection.map(id => ({ kind: 'duplicate', target_id: id, params: { dx: 2, dy: 2 } })))}><Copy size={14} /></button></>}
      {selectedWall && <><button title="Split at midpoint" aria-label="Split wall at midpoint" onClick={() => { const a = vertexAt(selectedWall.start_id), b = vertexAt(selectedWall.end_id); if (a && b) onCommand([{ kind: 'split_wall', target_id: selectedWall.id, params: { offset_ft: distance(a, b) / 2 } }]) }}><Scissors size={14} /></button>{selection.length === 2 && <button title="Join selected walls" aria-label="Join selected walls" onClick={() => onCommand([{ kind: 'join_walls', target_id: selection[0], params: { other_id: selection[1] } }])}><Link size={14} /></button>}</>}
      {!selectedRoom && <button title="Delete" aria-label="Delete selection" onClick={() => onCommand(selection.map(id => ({ kind: 'delete', target_id: id, params: {} })))}><Trash2 size={14} /></button>}
      <button aria-label="Clear selection" onClick={() => onSelect(null)}><X size={13} /></button>
    </div>}
    <Stage ref={stage} width={size.width} height={size.height} x={view.x} y={view.y} scaleX={view.scale} scaleY={view.scale} draggable={tool === 'pan' || spacePanning} onDragStart={e => { if (e.target === stage.current) markInteract() }} onDragEnd={e => { if (e.target === stage.current) setView(v => ({ ...v, x: e.target.x(), y: e.target.y() })) }} onMouseDown={pointerDown} onTouchStart={pointerDown} onMouseMove={() => { if (!revealing) setCursor(snapped(rawPoint(), start)) }} onTouchMove={() => { if (!revealing) setCursor(snapped(rawPoint(), start)) }} onMouseUp={pointerUp} onTouchEnd={pointerUp} onWheel={e => { e.evt.preventDefault(); markInteract(); const p = stage.current?.getPointerPosition(); if (e.evt.ctrlKey || e.evt.metaKey) zoom(Math.exp(-e.evt.deltaY * .01), p || undefined); else setView(v => ({ ...v, x: v.x - e.evt.deltaX, y: v.y - e.evt.deltaY })) }}>
      <Layer listening={false}>
        {gridX.map(x => <Line key={`x${x}`} points={[x, gy0, x, gy1]} stroke={Math.round(x / gridStep) % 5 ? '#eff0f1' : '#e6e8ea'} strokeWidth={stroke} />)}
        {gridY.map(y => <Line key={`y${y}`} points={[gx0, y, gx1, y]} stroke={Math.round(y / gridStep) % 5 ? '#eff0f1' : '#e6e8ea'} strokeWidth={stroke} />)}
      </Layer>
      <Layer visible={showModel}>
        {activeDiscipline === 'architectural' && rooms.map(room => {
          const chosen = selectedId === room.id
          const quarantined = quarantineIds.has(room.id)
          const violating = sonarSettled && failRoomIds.has(room.id) && !quarantined
          return <Group key={room.id} onClick={e => select(room.id, e)} onTap={e => select(room.id, e)}>
            <Line points={room.polygon.flat()} closed fill={chosen ? '#eaf2fa' : quarantined ? '#f3f1ed' : violating ? '#f6ebe8' : '#ffffff'} opacity={furnitureVisible ? (quarantined ? .45 : .55) : quarantined ? .7 : .86} stroke={quarantined ? '#b7b0a6' : room.needs_review ? '#d3ad6a' : undefined} dash={quarantined || room.needs_review ? [4 * stroke, 4 * stroke] : undefined} strokeWidth={stroke} listening={tool === 'select'} perfectDrawEnabled={false} shadowForStrokeEnabled={false} />
          </Group>
        })}
        {rasterOpacity > 0 && raster && world.width > 0 && activeDiscipline === 'architectural' && <KonvaImage image={raster} x={0} y={world.height} width={world.width} height={world.height} scaleY={-1} opacity={rasterOpacity} listening={false} />}
        {activeDiscipline === 'architectural' && walls.map(wall => {
          const a = vertexAt(wall.start_id), b = vertexAt(wall.end_id)
          if (!a || !b) return null
          const chosen = selection.includes(wall.id)
          return <Group key={wall.id}>
            {chosen && <Line points={[a.x, a.y, b.x, b.y]} stroke="#a7cef8" strokeWidth={wall.thickness_ft + 7 * stroke} listening={false} perfectDrawEnabled={false} shadowForStrokeEnabled={false} />}
            <Line points={[a.x, a.y, b.x, b.y]} stroke={chosen ? '#234c76' : '#242628'} strokeWidth={wall.thickness_ft} hitStrokeWidth={Math.max(wall.thickness_ft, 12 * stroke)} lineCap="square" perfectDrawEnabled={false} shadowForStrokeEnabled={false} draggable={tool === 'select' && !wall.locked && !busy} onMouseDown={e => { if (tool === 'select') e.cancelBubble = true }} onClick={e => select(wall.id, e)} onTap={e => select(wall.id, e)} onDragStart={e => { e.cancelBubble = true; markInteract(); select(wall.id); wallDrag.current = { pointer: rawPoint(), a: { x: a.x, y: a.y }, b: { x: b.x, y: b.y } } }} onDragMove={e => { e.cancelBubble = true; const drag = wallDrag.current; if (!drag) return; const pointer = rawPoint(); const p = snapped({ x: drag.a.x + pointer.x - drag.pointer.x, y: drag.a.y + pointer.y - drag.pointer.y }, null, a.id); const dx = p.x - drag.a.x, dy = p.y - drag.a.y; setPreview({ [a.id]: p, [b.id]: { x: drag.b.x + dx, y: drag.b.y + dy } }); e.target.position({ x: 0, y: 0 }) }} onDragEnd={e => { e.cancelBubble = true; const original = building.vertices.find(v => v.id === a.id)!; const p = preview[a.id] || a; onCommand([{ kind: 'move_wall', target_id: wall.id, params: { dx: p.x - original.x, dy: p.y - original.y } }]); e.target.position({ x: 0, y: 0 }); setPreview({}) }} />
            {chosen && !wall.locked && [a, b].map(v => <Circle key={v.id} x={v.x} y={v.y} radius={5 * stroke} fill="white" stroke="#397dbb" strokeWidth={1.5 * stroke} draggable onMouseDown={e => { e.cancelBubble = true }} onDragMove={e => { e.cancelBubble = true; const p = snapped(e.target.position(), v.id === a.id ? b : a, v.id); e.target.position(p); setPreview(old => ({ ...old, [v.id]: p })) }} onDragEnd={e => { e.cancelBubble = true; const p = snapped(e.target.position(), v.id === a.id ? b : a, v.id); onCommand([{ kind: 'move_vertex', target_id: v.id, params: p }]); setPreview({}) }} />)}
          </Group>
        })}
        {activeDiscipline === 'architectural' && openingsVisible && building.openings.map(opening => {
          const wall = walls.find(w => w.id === opening.wall_id) || floorWalls.find(w => w.id === opening.wall_id), a = wall && vertexAt(wall.start_id), b = wall && vertexAt(wall.end_id)
          if (!wall || !a || !b || (layerStop < 1 && wall.structural !== 'loadbearing')) return null
          const angle = Math.atan2(b.y - a.y, b.x - a.x), length = distance(a, b)
          const p = { x: a.x + Math.cos(angle) * opening.offset_ft, y: a.y + Math.sin(angle) * opening.offset_ft }
          const selected = selectedId === opening.id, color = selected ? '#2d81be' : '#282c31'
          return <Group key={opening.id} x={p.x} y={p.y} rotation={angle * 180 / Math.PI} onClick={e => select(opening.id, e)} onTap={e => select(opening.id, e)} draggable={tool === 'select' && !wall.locked && !busy} onMouseDown={e => { if (tool === 'select') e.cancelBubble = true }} onDragStart={() => markInteract()} onDragEnd={e => { e.cancelBubble = true; const q = projectPoint(e.target.position(), a, b); onCommand([{ kind: 'update_opening', target_id: opening.id, params: { offset_ft: Math.max(0, Math.min(length - opening.width_ft, q.offset)) } }]); e.target.position(p) }}>
            <Rect x={0} y={-wall.thickness_ft / 2 - stroke} width={opening.width_ft} height={wall.thickness_ft + 2 * stroke} fill="white" stroke={selected ? color : undefined} strokeWidth={stroke} />
            {opening.kind === 'window' ? <><Line points={[0, -wall.thickness_ft / 2, opening.width_ft, -wall.thickness_ft / 2, opening.width_ft, wall.thickness_ft / 2, 0, wall.thickness_ft / 2]} closed stroke={color} strokeWidth={stroke} /><Line points={[0, 0, opening.width_ft, 0]} stroke={color} strokeWidth={stroke} /></> : <Group x={opening.hinge === 'right' ? opening.width_ft : 0} scaleX={opening.hinge === 'right' ? -1 : 1} scaleY={opening.swing === 'out' ? -1 : 1}><Line points={[0, 0, 0, opening.width_ft]} stroke={color} strokeWidth={1.5 * stroke} /><Shape stroke={color} strokeWidth={stroke} sceneFunc={(ctx, shape) => { ctx.beginPath(); ctx.arc(0, 0, opening.width_ft, 0, Math.PI / 2); ctx.strokeShape(shape) }} /></Group>}
          </Group>
        })}
        {activeDiscipline === 'architectural' && objects.map(object => <Group key={object.id} x={object.x} y={object.y} rotation={object.rotation_deg} draggable={tool === 'select' && !busy} onMouseDown={e => { if (tool === 'select') e.cancelBubble = true }} onClick={e => select(object.id, e)} onTap={e => select(object.id, e)} onDragStart={() => markInteract()} onDragEnd={e => { e.cancelBubble = true; const p = snapped(e.target.position()); onCommand([{ kind: 'update_object', target_id: object.id, params: { x: p.x, y: p.y } }]) }}>
          <Rect x={-object.width_ft / 2} y={-object.depth_ft / 2} width={object.width_ft} height={object.depth_ft} fill={selection.includes(object.id) ? '#e9f3ff' : '#fafafa'} stroke={selection.includes(object.id) ? '#4d91c9' : '#74787a'} strokeWidth={stroke} cornerRadius={object.asset_id === 'toilet' || object.asset_id === 'bath' ? Math.min(object.width_ft, object.depth_ft) * .22 : .08} />
          {object.asset_id === 'toilet' || object.asset_id === 'sink' || object.asset_id === 'bath' ? <Rect x={-object.width_ft * .35} y={-object.depth_ft * .32} width={object.width_ft * .7} height={object.depth_ft * .65} cornerRadius={object.width_ft * .25} stroke="#7b7e81" strokeWidth={stroke} /> : <Line points={[-object.width_ft / 2 + .15, -object.depth_ft / 2 + .2, object.width_ft / 2 - .15, -object.depth_ft / 2 + .2]} stroke="#929598" strokeWidth={stroke} />}
        </Group>)}
        {start && cursor && <Group listening={false}><Line points={[start.x, start.y, cursor.x, cursor.y]} stroke={tool === 'wall' ? '#507b9c' : '#b36b98'} strokeWidth={tool === 'wall' ? .5 : stroke} opacity={.6} dash={tool === 'measure' ? [5 * stroke, 4 * stroke] : undefined} /><Circle x={cursor.x} y={cursor.y} radius={4 * stroke} fill="#5283a7" /><Text x={(start.x + cursor.x) / 2} y={(start.y + cursor.y) / 2 - 18 * stroke} text={lengthLabel(distance(start, cursor), units)} fontSize={12 * stroke} fill="#3b688a" /></Group>}
        {measurement && <Group listening={false}><Line points={measurement.flatMap(p => [p.x, p.y])} stroke="#ad6498" strokeWidth={1.5 * stroke} dash={[5 * stroke, 3 * stroke]} /><Text x={(measurement[0].x + measurement[1].x) / 2} y={(measurement[0].y + measurement[1].y) / 2 - 20 * stroke} text={lengthLabel(distance(...measurement), units)} fontSize={12 * stroke} fill="#ad6498" /></Group>}
        {marquee && cursor && <Rect x={Math.min(marquee.x, cursor.x)} y={Math.min(marquee.y, cursor.y)} width={Math.abs(cursor.x - marquee.x)} height={Math.abs(cursor.y - marquee.y)} fill="#438aca18" stroke="#438aca" strokeWidth={stroke} listening={false} />}
      </Layer>
      <Layer listening={false} visible={showModel && activeDiscipline === 'architectural'}>
        {rooms.map(room => { const center = interiorPoint(room.polygon); return <Group key={room.id}>
          <Text x={center.x - 6} y={center.y - .7} width={12} text={room.name.toUpperCase() + ((room.instance_count || 0) > 1 ? `  ×${room.instance_count}` : '')} align="center" fontFamily="Inter, -apple-system, sans-serif" fontSize={Math.max(.45, Math.min(.72, 12 / view.scale))} letterSpacing={.04} fill="#33383e" />
          <Text x={center.x - 5} y={center.y + .2} width={10} text={`${(polygonArea(room.polygon) * (units === 'metric' ? .092903 : 1)).toFixed(1)} ${units === 'metric' ? 'm²' : 'sq ft'}${room.needs_review ? ' · review' : ''}`} align="center" fontSize={Math.max(.35, Math.min(.6, 10 / view.scale))} fill="#898e95" />
        </Group> })}
        {walls.map(wall => {
          const a = vertexAt(wall.start_id), b = vertexAt(wall.end_id)
          if (!a || !b) return null
          const chosen = selection.includes(wall.id), length = distance(a, b), angle = Math.atan2(b.y - a.y, b.x - a.x)
          const normal = { x: -Math.sin(angle), y: Math.cos(angle) }
          return (chosen || length > 5) ? <Group key={wall.id} x={(a.x + b.x) / 2 - normal.x * (wall.thickness_ft / 2 + .55)} y={(a.y + b.y) / 2 - normal.y * (wall.thickness_ft / 2 + .55)} rotation={angle * 180 / Math.PI + (angle > Math.PI / 2 || angle < -Math.PI / 2 ? 180 : 0)}><Text text={lengthLabel(length, units)} x={-3} y={-.27} width={6} align="center" fontSize={Math.max(.28, Math.min(.5, 10 / view.scale))} fill="#72777b" /></Group> : null
        })}
      </Layer>
    </Stage>
    {!revealing && activeDiscipline === 'architectural' && <PlanFx view={view} size={size} floorId={floorId} hatch={hatch} pings={pingRooms} flash={flash} fixtures={sheetFixtures} showFixtures={fixturesVisible} pinging={!!sonarKey && !sonarSettled} flashing={blastAt > 0 && blastHere.length > 0} />}
    {blastAt > 0 && blastCheck && <div className="blast-hud" role="status">
      <span className="blast-count">×{shownCount} units affected</span>
      {otherFloors.length > 0 && <div className="blast-floors">{otherFloors.map(item => (
        <button key={item.floor.id} type="button" onClick={() => onFloor?.(item.floor.id)}>{chipName(item.floor, item.i)} · {item.count}</button>
      ))}</div>}
    </div>}
    {(selectedWall || selectedOpening || selectedObject || selectedRoom) && <div className="editor-properties">
      {selectedWall && <><div className="editor-property-title">Wall properties {selectedWall.locked && <LockKeyhole size={12} />}</div><label>Thickness <DimensionInput value={selectedWall.thickness_ft} units={units} disabled={selectedWall.locked} onSave={value => onCommand([{ kind: 'update_wall', target_id: selectedWall.id, params: { thickness_ft: value } }])} /></label><label>Height <DimensionInput value={selectedWall.height_ft} units={units} disabled={selectedWall.locked} onSave={value => onCommand([{ kind: 'update_wall', target_id: selectedWall.id, params: { height_ft: value } }])} /></label><label>Length <DimensionInput value={distance(vertexAt(selectedWall.start_id)!, vertexAt(selectedWall.end_id)!)} units={units} disabled={selectedWall.locked} onSave={value => { const a = vertexAt(selectedWall.start_id)!, b = vertexAt(selectedWall.end_id)!, ratio = value / distance(a, b); onCommand([{ kind: 'move_vertex', target_id: b.id, params: { x: a.x + (b.x - a.x) * ratio, y: a.y + (b.y - a.y) * ratio } }]) }} /></label>{selectedWall.locked ? <button className="editor-text-action" onClick={() => setUnlock(true)}>Review and unlock…</button> : <span className="editor-property-muted">{selectedWall.structural}</span>}</>}
      {selectedOpening && <><div className="editor-property-title">{selectedOpening.kind === 'door' ? 'Door' : 'Window'}</div><label>Width <DimensionInput value={selectedOpening.width_ft} units={units} onSave={v => onCommand([{ kind: 'update_opening', target_id: selectedOpening.id, params: { width_ft: v } }])} /></label><label>Offset <DimensionInput value={selectedOpening.offset_ft} units={units} onSave={v => onCommand([{ kind: 'update_opening', target_id: selectedOpening.id, params: { offset_ft: v } }])} /></label>{selectedOpening.kind === 'door' && <button className="editor-text-action" onClick={() => onCommand([{ kind: 'update_opening', target_id: selectedOpening.id, params: { hinge: selectedOpening.hinge === 'left' ? 'right' : 'left' } }])}>Flip hinge</button>}</>}
      {selectedObject && <><div className="editor-property-title">Object transform</div><label>Width <DimensionInput value={selectedObject.width_ft} units={units} onSave={v => onCommand([{ kind: 'update_object', target_id: selectedObject.id, params: { width_ft: v } }])} /></label><label>Depth <DimensionInput value={selectedObject.depth_ft} units={units} onSave={v => onCommand([{ kind: 'update_object', target_id: selectedObject.id, params: { depth_ft: v } }])} /></label><label>Rotation <input key={`${selectedObject.id}-${selectedObject.rotation_deg}`} type="number" aria-label="Object rotation" defaultValue={selectedObject.rotation_deg} onBlur={e => { const v = Number(e.target.value); if (Number.isFinite(v) && v !== selectedObject.rotation_deg) onCommand([{ kind: 'update_object', target_id: selectedObject.id, params: { rotation_deg: v } }]) }} /></label></>}
      {selectedRoom && <><div className="editor-property-title">Room</div><input key={selectedRoom.id} aria-label="Room name" defaultValue={selectedRoom.name} onBlur={e => { if (e.target.value && e.target.value !== selectedRoom.name) onCommand((matching ? matchingRooms : [selectedRoom]).map(r => ({ kind: 'rename_room', target_id: r.id, params: { name: e.target.value } }))) }} />{(selectedRoom.instance_count || 0) > 1 && <span className="editor-property-muted">×{selectedRoom.instance_count} units</span>}{matchingRooms.length > 1 && <label className="editor-match-label"><input type="checkbox" checked={matching} onChange={e => setMatching(e.target.checked)} />Apply to {matchingRooms.length} matching rooms</label>}<span className="editor-property-muted">{selectedRoom.needs_review ? 'Boundary needs review' : 'Shared partitions affect adjacent rooms'}</span></>}
    </div>}
    {unlock && selectedWall && <div className="editor-review-dialog" role="dialog" aria-label="Review wall classification"><strong>Review this wall</strong><p>Confirm the structural classification before enabling edits. Connected walls may still be locked.</p><select aria-label="Structural classification" value={structural} onChange={e => setStructural(e.target.value as typeof structural)}><option value="nonstructural">Nonstructural partition</option><option value="loadbearing">Load-bearing wall</option><option value="unknown">Unknown</option></select><textarea aria-label="Review reason" value={reason} onChange={e => setReason(e.target.value)} placeholder="Record the reason and drawing reference" /><div><button onClick={() => setUnlock(false)}>Cancel</button><button disabled={!reason.trim()} onClick={() => { onCommand([{ kind: 'unlock_wall', target_id: selectedWall.id, params: { structural, reason } }]); setUnlock(false); setReason('') }}>Save review and unlock</button></div></div>}
    {(spacePanning || tool === 'wall' || tool === 'measure' || tool === 'pan') && <div className="editor-canvas-hint">{spacePanning ? 'Drag to pan · Release Space to resume editing' : tool === 'wall' ? 'Click to start a wall, click to connect · Esc to finish' : tool === 'measure' ? 'Click two points to measure' : 'Drag to pan · Pinch to zoom'}</div>}
    {notice && <div className="editor-notice" role="status">{notice}</div>}
    <div className="editor-view-controls">
      <div className="editor-zoom"><div className="editor-scale"><span style={{ width: scaleDistance / scaleUnits * view.scale }} /><small>{scaleDistance} {units === 'metric' ? 'm' : 'ft'}</small></div><button aria-label="Zoom out" onClick={() => zoom(1 / 1.2)}><Minus size={14} /></button><span>{Math.round(view.scale / 20 * 100)}%</span><button aria-label="Zoom in" onClick={() => zoom(1.2)}><Plus size={14} /></button><button aria-label="Fit floor plan" onClick={fit}><Maximize size={14} /></button></div>
      {!!building.floors.length && <label className="editor-floor-switch">
        <select aria-label="Active floor" value={floorId} onChange={e => { onFloor?.(e.target.value); onSelect(null) }} onKeyDown={event => event.stopPropagation()}>
          {building.floors.map(floor => <option key={floor.id} value={floor.id}>{floor.name}</option>)}
        </select>
      </label>}
    </div>
  </div>
}
function DimensionInput({ value, units, onSave, disabled }: { value: number; units: 'metric' | 'imperial'; onSave: (v: number) => void; disabled?: boolean }) {
  const displayed = Number((value * (units === 'metric' ? .3048 : 1)).toFixed(3))
  return <span className="editor-dimension-input"><input key={`${displayed}-${units}`} type="number" step=".1" min="0" defaultValue={displayed} disabled={disabled} onKeyDown={e => { if (e.key === 'Enter') e.currentTarget.blur() }} onBlur={e => { const number = Number(e.target.value); if (Number.isFinite(number) && number >= 0 && number !== displayed) onSave(number / (units === 'metric' ? .3048 : 1)) }} /><small>{units === 'metric' ? 'm' : 'ft'}</small></span>
}
export default FloorPlan
