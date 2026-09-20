import { useEffect, useRef, useState } from 'react'
import { Eraser, LoaderCircle, Paintbrush, Sparkles, X } from 'lucide-react'
import { BRUSH_SIZES, FURNITURE_COLORS, expandInk, hasInk, type InkBounds } from './furniture-imagine'

type Props = {
  snapshot: string
  busy: boolean
  onCancel: () => void
  onGenerate: (image: string, ink: InkBounds, prompt: string) => void
}

export function FurnitureDraw({ snapshot, busy, onCancel, onGenerate }: Props) {
  const canvas = useRef<HTMLCanvasElement>(null)
  const ink = useRef<InkBounds | null>(null)
  const drawing = useRef(false)
  const last = useRef<{ x: number; y: number } | null>(null)
  const [color, setColor] = useState<string>(FURNITURE_COLORS[3])
  const [size, setSize] = useState<(typeof BRUSH_SIZES)[number]>(10)
  const [erase, setErase] = useState(false)
  const [prompt, setPrompt] = useState('')
  const [cursor, setCursor] = useState<{ x: number; y: number } | null>(null)
  const [empty, setEmpty] = useState(false)

  useEffect(() => {
    const node = canvas.current
    if (!node) return
    const resize = () => {
      const parent = node.parentElement
      if (!parent) return
      const dpr = Math.min(window.devicePixelRatio || 1, 2)
      const next = { width: parent.clientWidth, height: parent.clientHeight }
      if (next.width < 2 || next.height < 2) return
      if (node.width === Math.floor(next.width * dpr) && node.height === Math.floor(next.height * dpr)) return
      const copy = document.createElement('canvas')
      copy.width = node.width
      copy.height = node.height
      copy.getContext('2d')?.drawImage(node, 0, 0)
      node.width = Math.max(1, Math.floor(next.width * dpr))
      node.height = Math.max(1, Math.floor(next.height * dpr))
      const ctx = node.getContext('2d')
      if (!ctx) return
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      if (copy.width && copy.height) ctx.drawImage(copy, 0, 0, next.width, next.height)
    }
    resize()
    const observer = new ResizeObserver(resize)
    if (node.parentElement) observer.observe(node.parentElement)
    return () => observer.disconnect()
  }, [])

  function localPoint(event: React.PointerEvent<HTMLCanvasElement>) {
    const rect = event.currentTarget.getBoundingClientRect()
    return { x: event.clientX - rect.left, y: event.clientY - rect.top }
  }

  function stroke(from: { x: number; y: number }, to: { x: number; y: number }) {
    const ctx = canvas.current?.getContext('2d')
    if (!ctx) return
    ctx.save()
    ctx.lineCap = 'round'
    ctx.lineJoin = 'round'
    ctx.lineWidth = size
    ctx.globalCompositeOperation = erase ? 'destination-out' : 'source-over'
    ctx.strokeStyle = color
    ctx.beginPath()
    ctx.moveTo(from.x, from.y)
    ctx.lineTo(to.x, to.y)
    ctx.stroke()
    ctx.restore()
    if (!erase) ink.current = expandInk(expandInk(ink.current, from.x, from.y, size / 2), to.x, to.y, size / 2)
    setEmpty(false)
  }

  function clear() {
    const node = canvas.current
    const ctx = node?.getContext('2d')
    if (!node || !ctx) return
    ctx.save()
    ctx.setTransform(1, 0, 0, 1, 0, 0)
    ctx.clearRect(0, 0, node.width, node.height)
    ctx.restore()
    ink.current = null
    setEmpty(false)
  }

  function generate() {
    const node = canvas.current
    if (!node) return
    if (!hasInk(ink.current)) { setEmpty(true); return }
    const exportCanvas = document.createElement('canvas')
    exportCanvas.width = node.width
    exportCanvas.height = node.height
    const ctx = exportCanvas.getContext('2d')
    if (!ctx) return
    ctx.drawImage(node, 0, 0)
    onGenerate(exportCanvas.toDataURL('image/png'), ink.current!, prompt)
  }

  return <div className={`editor-imagine${busy ? ' is-busy' : ''}`}>
    <img className="editor-imagine-shot" src={snapshot} alt="" draggable={false} />
    <canvas
      ref={canvas}
      aria-label="Furniture sketch"
      onPointerDown={event => {
        if (busy) return
        event.currentTarget.setPointerCapture(event.pointerId)
        drawing.current = true
        last.current = localPoint(event)
        stroke(last.current, last.current)
      }}
      onPointerMove={event => {
        const point = localPoint(event)
        setCursor(point)
        if (!drawing.current || busy || !last.current) return
        stroke(last.current, point)
        last.current = point
      }}
      onPointerUp={() => { drawing.current = false; last.current = null }}
      onPointerCancel={() => { drawing.current = false; last.current = null }}
      onPointerLeave={() => { setCursor(null); drawing.current = false; last.current = null }}
    />
    {cursor && !busy && <span className="editor-imagine-cursor" style={{ left: cursor.x, top: cursor.y, width: size, height: size, borderColor: erase ? '#9aa3aa' : color }} />}
    <div className="editor-imagine-tools" role="toolbar" aria-label="Furniture paint tools">
      <span className="editor-imagine-label"><Paintbrush size={14} /> Imagine furniture</span>
      <span className="editor-tool-divider" />
      {FURNITURE_COLORS.map(swatch => <button key={swatch} type="button" className={`editor-imagine-swatch${color === swatch && !erase ? ' active' : ''}`} style={{ background: swatch }} aria-label={`Paint ${swatch}`} disabled={busy} onClick={() => { setColor(swatch); setErase(false) }} />)}
      <span className="editor-tool-divider" />
      {BRUSH_SIZES.map(value => <button key={value} type="button" className={size === value ? 'active' : ''} aria-label={`Brush size ${value}`} disabled={busy} onClick={() => setSize(value)}><span className="editor-imagine-nib" style={{ width: value * 0.7, height: value * 0.7 }} /></button>)}
      <button type="button" className={erase ? 'active' : ''} title="Eraser" aria-label="Eraser" disabled={busy} onClick={() => setErase(on => !on)}><Eraser size={15} /></button>
      <button type="button" disabled={busy} onClick={clear}>Clear</button>
    </div>
    <form className="editor-imagine-panel" onSubmit={event => { event.preventDefault(); if (!busy) generate() }}>
      <header>
        <div>
          <strong>Draw in this view</strong>
          <span>Camera is locked · paint the piece you want</span>
        </div>
        <button type="button" aria-label="Cancel imagined furniture" disabled={busy} onClick={onCancel}><X size={14} /></button>
      </header>
      <label htmlFor="imagine-furniture-note">Optional: what is it?</label>
      <input id="imagine-furniture-note" value={prompt} onChange={event => setPrompt(event.target.value)} placeholder="e.g. a low walnut credenza…" disabled={busy} />
      {empty && <p className="editor-imagine-empty">Paint the furniture first — the room view stays as a guide.</p>}
      <div className="editor-appearance-actions">
        <button type="button" disabled={busy} onClick={onCancel}>Cancel</button>
        <button type="submit" disabled={busy}>{busy ? <><LoaderCircle size={13} className="editor-spin" /> Generating…</> : <><Sparkles size={13} /> Make furniture</>}</button>
      </div>
    </form>
  </div>
}
