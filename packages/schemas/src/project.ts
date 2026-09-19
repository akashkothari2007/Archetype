import type { Building } from "./building";
import type { Sheet } from "./sheets";

export type DocumentKind = "drawings" | "standards";

export interface UploadedDocument {
  kind: DocumentKind;
  filename: string;
  bytes: number;
  page_count: number | null;
  sha256: string;
}

export interface Project {
  project_id: string;
  created_at: string;
  documents: UploadedDocument[];
  /** Classification of every page of the drawings PDF. */
  sheets: Sheet[];
  warnings: string[];
}

/** Response of POST /api/projects/{id}/extract */
export interface ExtractResponse {
  project_id: string;
  pages: number[];
  building: Building;
  /** Wall-clock milliseconds, shown in the UI so slow pages are visible. */
  elapsed_ms: number;
}

export interface ExtractRequest {
  /** Explicit page list, or "auto" to take every sheet the classifier marked use: true. */
  pages: number[] | "auto";
}

export interface ApiError {
  detail: string;
}
