import type { BBoxFt, PointFt, Room } from "@plancheck/schemas";

/**
 * building.json is y-up with the origin at the sheet's bottom-left. SVG is
 * y-down. The flip happens here and nowhere else, so every component below
 * can treat coordinates as plain screen space.
 */
export interface PlanFrame {
  width: number;
  height: number;
  project: (point: PointFt) => PointFt;
}

export function planFrame(bounds: BBoxFt): PlanFrame {
  const [minX, minY, maxX, maxY] = bounds;
  const width = Math.max(maxX - minX, 1);
  const height = Math.max(maxY - minY, 1);
  return {
    width,
    height,
    project: ([x, y]) => [x - minX, maxY - y],
  };
}

export function polygonPath(polygon: PointFt[], frame: PlanFrame): string {
  if (polygon.length === 0) return "";
  const points = polygon.map((p) => frame.project(p));
  const [first, ...rest] = points;
  if (!first) return "";
  return `M ${first[0]} ${first[1]} ${rest.map((p) => `L ${p[0]} ${p[1]}`).join(" ")} Z`;
}

export function bboxCenter(bbox: BBoxFt, frame: PlanFrame): PointFt {
  const [minX, minY, maxX, maxY] = bbox;
  return frame.project([(minX + maxX) / 2, (minY + maxY) / 2]);
}

/** Rooms scoring below this are hatched and labelled "needs review". */
export const LOW_CONFIDENCE = 0.6;

export function isLowConfidence(room: Room): boolean {
  return room.confidence < LOW_CONFIDENCE;
}

/** Fill colours by room family. Violation colouring lands on top of this later. */
export function roomFill(room: Room): string {
  if (isLowConfidence(room)) return "#3a2a1c";
  if (room.type.startsWith("guestroom.")) return "#1e2a3d";
  switch (room.type) {
    case "corridor":
      return "#232a22";
    case "stair":
    case "elevator":
      return "#2a2434";
    case "lobby":
    case "public":
      return "#1f2b2c";
    default:
      return "#1f232b";
  }
}

export function roomStroke(room: Room, selected: boolean): string {
  if (selected) return "#6ea8fe";
  if (isLowConfidence(room)) return "#c98a3e";
  return "#59616f";
}

export function metricLabel(key: string): string {
  return key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let value = bytes / 1024;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  return `${value.toFixed(1)} ${units[unitIndex]}`;
}
