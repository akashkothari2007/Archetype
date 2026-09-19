/**
 * building.json — the central artifact of PlanCheck.
 *
 * Everything hangs off this file: the 2D SVG viewer, the 3D viewer, the
 * compliance comparison, and the fix agent. E1 is the only thing that writes
 * it. Nothing downstream may reach past it into a PDF.
 *
 * CONVENTIONS
 *   Coordinates are FEET, origin at sheet bottom-left, y increasing upward.
 *   The extractor performs the y-flip so nothing downstream has to.
 *   Areas are carried in both sqft and m2 because the drawings are imperial
 *   and the brand standards are metric. Never convert at read time.
 *
 * ASSEMBLY
 *   One building is assembled from MANY sheets at three different scales
 *   (whole floor for counts, enlarged segments and unit plans for geometry).
 *   Every room therefore carries its own `source`. When two sheets disagree
 *   about the same room, provenance is how you find out which to trust.
 */

export type RoomType =
  | `guestroom.${string}`
  | "corridor"
  | "lobby"
  | "stair"
  | "elevator"
  | "vestibule"
  | "public"
  | "back_of_house"
  | "unknown";

/** [x, y] in feet. */
export type PointFt = [number, number];

/** [minX, minY, maxX, maxY] in feet. */
export type BBoxFt = [number, number, number, number];

/** Which tier of drawing a value came from. Precision increases down the list. */
export type SheetTier = "floor_plan" | "enlarged_plan" | "unit_plan" | "schedule";

/** How a value was obtained. Drives the confidence score and the UI badge. */
export type ExtractionMethod =
  | "floodfill"
  | "dimension_string"
  | "schedule_text"
  | "inferred"
  | "assumed"
  | "stub";

export interface Provenance {
  page: number;
  sheet_no: string | null;
  tier: SheetTier | null;
  method: ExtractionMethod;
}

// ---------------------------------------------------------------------------
// Metrics — the surface E3 checks against
// ---------------------------------------------------------------------------

/**
 * Every measurable property of a room, keyed by metric name.
 *
 * This is deliberately an open map rather than fixed fields. A rule says
 * `metric: "clear_width"` and E3 looks up `room.metrics["clear_width"]`. New
 * rule types then need zero schema changes — which is the whole reason the
 * rules engine can be built in parallel with the document engine.
 *
 * A metric that could not be measured must be ABSENT, never zero. E3 reports
 * "not measurable" rather than inventing a passing or failing comparison.
 */
export type MetricKey =
  | "area"
  | "width"
  | "length"
  | "clear_width"
  | "perimeter"
  | "ceiling_height"
  | "door_width"
  | (string & {});

export interface Metric {
  value: number;
  unit: "m2" | "sqft" | "m" | "ft" | "mm" | "in";
  /** 0..1 confidence in this specific number, independent of the room's overall score. */
  confidence: number;
  source: Provenance;
}

export type RoomMetrics = Partial<Record<MetricKey, Metric>>;

// ---------------------------------------------------------------------------
// Rooms
// ---------------------------------------------------------------------------

export interface Room {
  id: string;
  /** Normalized key that rules match against, e.g. "guestroom.studio_king". */
  type: RoomType;
  /** Raw text as it appears on the drawing, e.g. "STUDIO KING". Keep both. */
  label: string;
  /** Room number off the drawing or door schedule, e.g. "004a". Null if none. */
  number: string | null;
  level_id: string;

  polygon_ft: PointFt[];
  bbox_ft: BBoxFt;

  /** Everything checkable about this room. See RoomMetrics. */
  metrics: RoomMetrics;

  /**
   * Blast radius. If this room is one instance of a unit type that repeats 84
   * times, this points at that type and E3 multiplies by its count.
   */
  unit_type_id: string | null;

  /** 0..1. Below ~0.6 the viewer hatches the room and says "needs review". */
  confidence: number;
  /** Plain-language reasons the score was reduced. Shown verbatim in the UI. */
  confidence_notes: string[];

  source: Provenance;

  opening_ids: string[];
  fixture_ids: string[];
  /** Populated by E3. Always present, empty out of E1. */
  violation_ids: string[];
}

// ---------------------------------------------------------------------------
// Unit types — where blast radius comes from
// ---------------------------------------------------------------------------

/**
 * A repeating guestroom type. Geometry comes from the unit plan sheet, the
 * count comes from the whole-floor plan. Each tier does the job it is good at.
 */
export interface UnitType {
  id: string;
  /** e.g. "guestroom.studio_king" */
  type: RoomType;
  label: string;
  /** How many instances exist across the whole building. */
  count: number;
  /** Per level, so "84 total, 28 per floor" is answerable. */
  count_by_level: Record<string, number>;
  /** The room whose geometry is treated as authoritative for this type. */
  representative_room_id: string | null;
  /** Rooms counted as instances of this type. */
  member_room_ids: string[];
  source: Provenance;
}

// ---------------------------------------------------------------------------
// Levels — needed the moment the 3D viewer stacks floors
// ---------------------------------------------------------------------------

export interface Level {
  id: string;
  name: string;
  /** Storey index: 0 = ground. */
  index: number;
  /** ASSUMED unless read from a section. See `elevation_assumed`. */
  elevation_ft: number;
  floor_to_floor_ft: number;
  /** True whenever the two numbers above are rendering conventions, not data. */
  elevation_assumed: boolean;
  /** Pages of the drawing set that describe this level. */
  source_pages: number[];
}

// ---------------------------------------------------------------------------
// Openings — doors are a real brand and accessibility rule
// ---------------------------------------------------------------------------

export interface Opening {
  id: string;
  kind: "door" | "window" | "opening";
  /** Door mark off the schedule, e.g. "004a". */
  tag: string | null;
  /** Rooms on either side. Second entry is null when it opens to outside. */
  connects: [string, string | null];
  /** Midpoint of the opening, in feet. */
  xy_ft: PointFt;
  width_ft: number | null;
  height_ft: number | null;
  height_assumed: boolean;
  source: Provenance;
}

// ---------------------------------------------------------------------------
// Dimensions and fixtures
// ---------------------------------------------------------------------------

export interface Dimension {
  /** Raw token as extracted, mangling and all. Keep it for debugging. */
  text: string;
  feet: number | null;
  metres: number | null;
  xy_ft: PointFt;
  near_room_id: string | null;
  /**
   * Which token the value was parsed from. Imperial fractions extract mangled
   * (31'-2 1/2" comes out 31'-212), so the metric bracket is the reliable one.
   */
  parsed_from: "metric_bracket" | "imperial" | "computed";
  source: Provenance;
}

export interface Fixture {
  id: string;
  tag: string;
  discipline: "hvac" | "plumbing" | "electrical";
  xy_ft: PointFt;
  /** Never extracted. Assigned per discipline for rendering only. */
  assumed_z_ft: number;
  in_room_id: string | null;
  source: Provenance;
}

// ---------------------------------------------------------------------------
// Top level
// ---------------------------------------------------------------------------

/** Per-sheet scale record. One entry per page that contributed to this building. */
export interface SheetSource {
  page: number;
  sheet_no: string | null;
  title: string | null;
  tier: SheetTier;
  /** As printed in the title block, e.g. "3/16\"=1'-0\"". */
  scale_label: string | null;
  scale_pts_per_ft: number | null;
  /** Raster DPI used for the floodfill pass. */
  dpi: number | null;
  /** True when the printed scale was confirmed against repeated dimension strings. */
  scale_verified: boolean;
}

export interface BuildingMeta {
  schema_version: string;
  source_pdf: string;
  /** Every page that contributed. Provenance on each room says which. */
  pages: number[];
  units: "ft";
  /** "stub" until E1 is real. This field must never silently disappear. */
  generator: string;
  extracted_at: string;
  /** Extent of all geometry, so the viewer can frame without a first pass. */
  bounds_ft: BBoxFt;
}

/**
 * Rendering conventions, not extracted data. 2D plans carry no elevation
 * information. Anywhere these reach the screen they must be labelled assumed.
 */
export interface BuildingDefaults {
  wall_height_ft: number;
  wall_thickness_ft: number;
  door_height_ft: number;
  assumed: true;
}

export interface Building {
  meta: BuildingMeta;
  defaults: BuildingDefaults;
  sheets_used: SheetSource[];
  levels: Level[];
  unit_types: UnitType[];
  rooms: Room[];
  openings: Opening[];
  dimensions: Dimension[];
  fixtures: Fixture[];
  /** What the extractor could not do. Surfaced in the UI, never swallowed. */
  warnings: string[];
}
