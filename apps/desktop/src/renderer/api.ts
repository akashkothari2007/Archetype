import type {Building,DesktopProject,Job} from './types';
export const base='http://127.0.0.1:8000/api/desktop';
export type BuildingPatch = {
  revision:number
  can_undo:boolean
  can_redo:boolean
  changed:{vertices?:Building['vertices'];walls?:Building['walls'];rooms?:Building['rooms'];openings?:Building['openings'];objects?:Building['objects']}
  removed_ids:string[]
  checks:DesktopProject['checks']
  environment?:Building['environment']
  site?:Building['site']
}
export function isDesktopProject(value:unknown):value is DesktopProject{
  const project=value as DesktopProject
  return !!project && typeof project==='object' && !!project.building && Array.isArray(project.building.floors)
}
export function applyPatch(project:DesktopProject,patch:BuildingPatch):DesktopProject{
  const removed=new Set(patch.removed_ids||[])
  const merge=<T extends {id:string}>(list:T[],updates?:T[]):T[]=>{
    const next=list.filter(e=>!removed.has(e.id))
    if(!updates?.length)return next
    const byId=new Map(next.map(e=>[e.id,e] as const))
    for(const item of updates)byId.set(item.id,item)
    const seen=new Set<string>()
    const out:T[]=[]
    for(const item of next){
      const current=byId.get(item.id)!
      if(!seen.has(current.id)){out.push(current);seen.add(current.id)}
    }
    for(const item of updates)if(!seen.has(item.id)){out.push(item);seen.add(item.id)}
    return out
  }
  const building=project.building
  return {
    ...project,
    revision:patch.revision,
    can_undo:patch.can_undo,
    can_redo:patch.can_redo,
    checks:patch.checks,
    building:{
      ...building,
      vertices:merge(building.vertices,patch.changed.vertices),
      walls:merge(building.walls,patch.changed.walls),
      rooms:merge(building.rooms,patch.changed.rooms),
      openings:merge(building.openings,patch.changed.openings),
      objects:merge(building.objects,patch.changed.objects),
      environment:patch.environment??building.environment,
      site:patch.site??building.site??{lat:null,lon:null,rotation_deg:0,ground_offset_ft:0,address:''},
    },
  }
}
export async function api<T=any>(path:string,body?:unknown,method?:string):Promise<T>{const response=await fetch(base+path,{method:method||(body?'POST':'GET'),headers:body instanceof FormData?undefined:{'Content-Type':'application/json'},body:body instanceof FormData?body:body?JSON.stringify(body):undefined});if(!response.ok){const e=await response.json().catch(()=>({detail:response.statusText}));throw new Error(typeof e.detail==='string'?e.detail:JSON.stringify(e.detail))}return response.json()}
export async function waitJob(id:string,onProgress:(job:Job)=>void):Promise<any>{for(;;){const j=await api<Job>('/jobs/'+id);onProgress(j);if(j.state==='done')return j.result;if(j.state==='error'||j.state==='cancelled')throw new Error(j.error||j.message);await new Promise(r=>setTimeout(r,120));}}
