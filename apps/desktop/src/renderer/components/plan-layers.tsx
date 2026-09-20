export type LayerStop = 0 | 1 | 2 | 3 | 4 | 5

export const LAYER_STOPS: { id: LayerStop; label: string }[] = [
  { id: 0, label: 'Structure' },
  { id: 1, label: 'Partitions' },
  { id: 2, label: 'Doors & Windows' },
  { id: 3, label: 'Fixtures' },
  { id: 4, label: 'Furniture' },
  { id: 5, label: 'All' },
]

export function computeLayerCounts(input: {
  sheetWalls?: { cls?: string }[]
  sheetDoors?: number
  sheetWindows?: number
  sheetFixtures?: number
  sheetFurniture?: number
  floorWalls: { structural: string }[]
  floorOpenings: number
  floorFixtures: number
  floorFurniture: number
}) {
  const sheetWalls = input.sheetWalls || []
  const structure = sheetWalls.filter(w => w.cls === 'loadbearing').length || input.floorWalls.filter(w => w.structural === 'loadbearing').length
  const partitions = sheetWalls.filter(w => w.cls !== 'loadbearing').length || input.floorWalls.filter(w => w.structural !== 'loadbearing').length
  const openings = (input.sheetDoors || 0) + (input.sheetWindows || 0) || input.floorOpenings
  const fixtures = (input.sheetFixtures || 0) + input.floorFixtures
  const furniture = input.sheetFurniture || input.floorFurniture
  return [structure, partitions, openings, fixtures, furniture, structure + partitions + openings + fixtures + furniture]
}

export function XrayScrubber({ stop, counts, onChange }: { stop: LayerStop; counts: number[]; onChange: (stop: LayerStop) => void }) {
  const current = LAYER_STOPS[stop]
  return (
    <div className="xray-scrubber">
      <div className="xray-head">
        <span>{current.label} · {(counts[stop] || 0).toLocaleString()} segments</span>
      </div>
      <input type="range" min={0} max={5} step={1} value={stop} aria-label="Layer x-ray" onChange={e => onChange(Number(e.target.value) as LayerStop)} />
      <div className="xray-stops">
        {LAYER_STOPS.map(item => (
          <button key={item.id} type="button" className={stop === item.id ? 'active' : stop > item.id ? 'passed' : ''} onClick={() => onChange(item.id)}>{item.label}</button>
        ))}
      </div>
    </div>
  )
}
