export type NamedProject={project_id:string;name:string};

const COPY_SUFFIX=/^(.*) \((\d+)\)$/;

export function normalizeProjectName(name:string){
  return name.trim().replace(/\s+/g,' ');
}

export function projectNameKey(name:string){
  return normalizeProjectName(name).toLowerCase();
}

export function uniqueProjectName(projects:NamedProject[],name:string,excludeId?:string){
  const cleaned=normalizeProjectName(name);
  if(!cleaned)return cleaned;
  const keys=new Set(projects.filter(project=>project.project_id!==excludeId).map(project=>projectNameKey(project.name)));
  if(!keys.has(projectNameKey(cleaned)))return cleaned;
  const stem=cleaned.match(COPY_SUFFIX)?.[1]??cleaned;
  for(let n=2;;n++){
    const candidate=`${stem} (${n})`;
    if(!keys.has(projectNameKey(candidate)))return candidate;
  }
}
