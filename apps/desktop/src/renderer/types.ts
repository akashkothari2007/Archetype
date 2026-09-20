import type { DesktopProject as ContractProject } from '@archetype/contracts'
export type { Building, Floor, Vertex, BuildingWall, Opening, Room, PlacedObject, Environment, Site, Source, ReviewItem, DesignBrief, ModelCommand } from '@archetype/contracts'
export type DesktopProject = ContractProject & { sheets?: SheetCard[]; import_meta?: ImportSummary }
export type Check = {id:string;rule_id:string;entity_id:string;entity_ids:string[];status:'pass'|'fail'|'cannot_verify'|'quarantined';metric:string;actual:number|null;required:number;unit:string;message:string;source_doc:string;source_page?:number;source_text:string};
export type SheetCard = {
  sheet_id:string
  sheet_no:string
  title:string
  role:string
  page:number
  use:boolean
  extracted:boolean
  reason:string
  walls:number
  rooms:number
  doors:number
  windows?:number
  thumb_url:string
  raster_url?:string
  geometry_url?:string
  levels?:string[]
  floor_ids?:string[]
  scale_pts_per_ft?:number|null
  size_pt?:number[]|null
}
export type ImportSummary = {
  name:string
  floors:number
  rooms:number
  area_sqft:number
  doors:number
  windows:number
  walls:number
  rules:number
  violations:number
  elapsed_s:number
  pages?:number
  pages_read?:number
}
export type Job = {
  job_id:string
  state:'queued'|'running'|'done'|'error'|'cancelled'
  progress:number
  message:string
  phase?:string
  error?:string
  result?:Record<string,any>
  events?:{message:string;phase:string;progress:number}[]
  sheets_done?:SheetCard[]
  totals?:{pages?:number;pages_read?:number;walls?:number;rooms?:number;doors?:number;windows?:number;skipped?:number;rules?:number}
};
export type ProjectSummary = {project_id:string;name:string;updated_at:string;revision:number;source:string;ready:boolean};
