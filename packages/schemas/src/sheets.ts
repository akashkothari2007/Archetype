/**
 * sheets.json — output of the classifier.
 *
 * The classifier reads the title block (which is structured text on every
 * page) and sorts the full set into roles, so the user drops in the whole
 * PDF instead of being asked which pages matter.
 */

export type SheetRole =
  /** Whole repeating floor at 1/16". Source of room inventory and repeat counts. */
  | "floor_plan"
  /** Enlarged segment at 3/16" or 1/4". Source of accurate geometry. */
  | "enlarged_plan"
  /** One drawing per unit type, highest precision. */
  | "unit_plan"
  /** Door / wall / finish schedules. Tabular text, used to validate labels. */
  | "schedule"
  /** Building code compliance matrix. Hook for the city-codes feature later. */
  | "code_matrix"
  | "elevation"
  | "section"
  | "detail"
  | "site"
  | "roof"
  | "edge_of_slab"
  | "index"
  | "unknown";

export interface Sheet {
  /** 1-indexed page in the uploaded PDF. */
  page: number;
  /** From the title block, e.g. "A.502c". Null when unparseable. */
  sheet_no: string | null;
  title: string | null;
  role: SheetRole;
  /** As printed, e.g. "3/16\"=1'-0\"". */
  scale: string | null;
  scale_pts_per_ft: number | null;
  /** Dimension-token count. A real plan sheet has 60+; a details sheet under 20. */
  dim_tokens: number | null;
  /** Whether extraction should run on this page. */
  use: boolean;
  /** Why it is or isn't used. Shown verbatim in the UI. */
  reason: string;
}
