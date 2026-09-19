export type { Building, Floor, Vertex, BuildingWall, Opening, Room, PlacedObject, Environment, Source, ReviewItem, DesktopProject, DesignBrief, ModelCommand } from '@archetype/contracts';
export type Check = {id:string;rule_id:string;entity_id:string;entity_ids:string[];status:'pass'|'fail'|'cannot_verify';metric:string;actual:number|null;required:number;unit:string;message:string;source_doc:string;source_page?:number;source_text:string};
export type Job = {job_id:string;state:'queued'|'running'|'done'|'error'|'cancelled';progress:number;message:string;phase?:string;error?:string;result?:Record<string,any>;events?:{message:string;phase:string;progress:number}[]};
export type ProjectSummary = {project_id:string;name:string;updated_at:string;revision:number;source:string;ready:boolean};
