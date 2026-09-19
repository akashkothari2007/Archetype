import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { Building, Room } from "@plancheck/schemas";
import { bboxCenter, isLowConfidence, planFrame, polygonPath, roomFill, roomStroke } from "../lib/plan";

interface Props {
  building: Building;
  selectedRoomId: string | null;
  onSelectRoom: (roomId: string | null) => void;
}

interface View {
  k: number;
  tx: number;
  ty: number;
}

const IDENTITY: View = { k: 1, tx: 0, ty: 0 };
const MIN_ZOOM = 0.3;
const MAX_ZOOM = 24;

export function PlanViewer2D({ building, selectedRoomId, onSelectRoom }: Props) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [view, setView] = useState<View>(IDENTITY);
  const [showLabels, setShowLabels] = useState(true);
  const [showDoors, setShowDoors] = useState(true);
  const drag = useRef<{ x: number; y: number; tx: number; ty: number } | null>(null);

  const frame = useMemo(() => planFrame(building.meta.bounds_ft), [building.meta.bounds_ft]);

  // Reset the camera whenever a different extraction loads.
  useEffect(() => setView(IDENTITY), [building.meta.extracted_at]);

  const zoomAt = useCallback((clientX: number, clientY: number, factor: number) => {
    const svg = svgRef.current;
    if (!svg) return;
    const rect = svg.getBoundingClientRect();
    // Cursor position in viewBox units, so zoom keeps the point under the mouse.
    const px = ((clientX - rect.left) / rect.width) * svg.viewBox.baseVal.width;
    const py = ((clientY - rect.top) / rect.height) * svg.viewBox.baseVal.height;

    setView((prev) => {
      const k = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, prev.k * factor));
      const ratio = k / prev.k;
      return { k, tx: px - (px - prev.tx) * ratio, ty: py - (py - prev.ty) * ratio };
    });
  }, []);

  return (
    <div className="relative h-full w-full overflow-hidden bg-ink-950">
      <svg
        ref={svgRef}
        viewBox={`0 0 ${frame.width} ${frame.height}`}
        preserveAspectRatio="xMidYMid meet"
        className="h-full w-full cursor-grab touch-none active:cursor-grabbing"
        onWheel={(e) => zoomAt(e.clientX, e.clientY, e.deltaY < 0 ? 1.12 : 1 / 1.12)}
        onPointerDown={(e) => {
          e.currentTarget.setPointerCapture(e.pointerId);
          drag.current = { x: e.clientX, y: e.clientY, tx: view.tx, ty: view.ty };
        }}
        onPointerMove={(e) => {
          const start = drag.current;
          const svg = svgRef.current;
          if (!start || !svg) return;
          const rect = svg.getBoundingClientRect();
          const scaleX = svg.viewBox.baseVal.width / rect.width;
          const scaleY = svg.viewBox.baseVal.height / rect.height;
          setView((prev) => ({
            ...prev,
            tx: start.tx + (e.clientX - start.x) * scaleX,
            ty: start.ty + (e.clientY - start.y) * scaleY,
          }));
        }}
        onPointerUp={() => {
          drag.current = null;
        }}
        onPointerCancel={() => {
          drag.current = null;
        }}
      >
        <defs>
          {/* Low-confidence rooms are hatched. Flagging our own uncertainty is a
              feature — it is the difference between a tool and a guess. */}
          <pattern id="needs-review" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <line x1="0" y1="0" x2="0" y2="6" stroke="#c98a3e" strokeWidth="1.4" opacity="0.5" />
          </pattern>
        </defs>

        <g transform={`translate(${view.tx} ${view.ty}) scale(${view.k})`}>
          <rect
            x={0}
            y={0}
            width={frame.width}
            height={frame.height}
            fill="transparent"
            onClick={() => onSelectRoom(null)}
          />

          {building.rooms.map((room) => (
            <RoomShape
              key={room.id}
              room={room}
              frame={frame}
              zoom={view.k}
              selected={room.id === selectedRoomId}
              showLabel={showLabels}
              onSelect={onSelectRoom}
            />
          ))}

          {showDoors &&
            building.openings.map((opening) => {
              const [x, y] = frame.project(opening.xy_ft);
              return (
                <circle
                  key={opening.id}
                  cx={x}
                  cy={y}
                  r={Math.max(0.6, 1.2 / view.k)}
                  fill="#6ea8fe"
                  opacity={0.75}
                />
              );
            })}
        </g>
      </svg>

      <div className="pointer-events-none absolute inset-x-0 top-0 flex items-start justify-between gap-3 p-3">
        <div className="pointer-events-auto flex gap-1 rounded-md border border-ink-700 bg-ink-900/90 p-1 backdrop-blur">
          <Toggle active={showLabels} onClick={() => setShowLabels((v) => !v)}>
            Labels
          </Toggle>
          <Toggle active={showDoors} onClick={() => setShowDoors((v) => !v)}>
            Doors
          </Toggle>
          <button
            type="button"
            onClick={() => setView(IDENTITY)}
            className="rounded px-2 py-1 text-xs text-neutral-400 hover:bg-ink-700 hover:text-neutral-200"
          >
            Reset
          </button>
        </div>

        <div className="rounded-md border border-ink-700 bg-ink-900/90 px-2 py-1 text-right text-[11px] text-neutral-500 backdrop-blur">
          <div>
            {Math.round(frame.width)} × {Math.round(frame.height)} ft
          </div>
          <div>{view.k.toFixed(1)}× zoom</div>
        </div>
      </div>

      <div className="pointer-events-none absolute bottom-3 left-3 flex flex-wrap gap-3 rounded-md border border-ink-700 bg-ink-900/90 px-3 py-2 text-[11px] text-neutral-400 backdrop-blur">
        <Swatch fill="#1e2a3d">Guestroom</Swatch>
        <Swatch fill="#232a22">Circulation</Swatch>
        <Swatch fill="#2a2434">Core</Swatch>
        <Swatch fill="url(#needs-review-legend)" hatched>
          Needs review
        </Swatch>
      </div>
      <svg className="absolute size-0">
        <defs>
          <pattern id="needs-review-legend" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <line x1="0" y1="0" x2="0" y2="6" stroke="#c98a3e" strokeWidth="1.4" opacity="0.6" />
          </pattern>
        </defs>
      </svg>
    </div>
  );
}

interface RoomShapeProps {
  room: Room;
  frame: ReturnType<typeof planFrame>;
  zoom: number;
  selected: boolean;
  showLabel: boolean;
  onSelect: (roomId: string) => void;
}

function RoomShape({ room, frame, zoom, selected, showLabel, onSelect }: RoomShapeProps) {
  const path = polygonPath(room.polygon_ft, frame);
  const [cx, cy] = bboxCenter(room.bbox_ft, frame);
  const [x0, y0, x1, y1] = room.bbox_ft;
  const fits = (x1 - x0) * zoom > 34 && (y1 - y0) * zoom > 18;

  return (
    <g
      onClick={(e) => {
        e.stopPropagation();
        onSelect(room.id);
      }}
      className="cursor-pointer"
    >
      <path d={path} fill={roomFill(room)} stroke={roomStroke(room, selected)} strokeWidth={selected ? 1.2 : 0.4} />
      {isLowConfidence(room) && <path d={path} fill="url(#needs-review)" stroke="none" pointerEvents="none" />}

      {showLabel && fits && (
        <g pointerEvents="none" textAnchor="middle">
          <text x={cx} y={cy - 1} fill="#c8cdd6" fontSize={2.6} fontWeight={500}>
            {room.label}
          </text>
          <text x={cx} y={cy + 2.6} fill="#79808c" fontSize={2.1}>
            {room.metrics.area ? `${room.metrics.area.value.toFixed(1)} m²` : "area n/a"}
          </text>
        </g>
      )}
    </g>
  );
}

function Toggle({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded px-2 py-1 text-xs transition ${
        active ? "bg-ink-700 text-neutral-100" : "text-neutral-500 hover:text-neutral-300"
      }`}
    >
      {children}
    </button>
  );
}

function Swatch({ fill, hatched, children }: { fill: string; hatched?: boolean; children: React.ReactNode }) {
  return (
    <span className="flex items-center gap-1.5">
      <svg width="10" height="10" className="shrink-0">
        <rect
          width="10"
          height="10"
          rx="2"
          fill={hatched ? "#3a2a1c" : fill}
          stroke={hatched ? "#c98a3e" : "#59616f"}
          strokeWidth="1"
        />
        {hatched && <rect width="10" height="10" rx="2" fill={fill} />}
      </svg>
      {children}
    </span>
  );
}
