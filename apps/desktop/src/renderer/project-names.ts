export type NamedProject={project_id:string;name:string};

export function normalizeProjectName(name:string){
  return name.trim().replace(/\s+/g,' ');
}

export function projectNameKey(name:string){
  return normalizeProjectName(name).toLowerCase();
}

export function findNameConflict(projects:NamedProject[],name:string,excludeId?:string){
  const key=projectNameKey(name);
  if(!key)return null;
  return projects.find(project=>project.project_id!==excludeId&&projectNameKey(project.name)===key)||null;
}

export function duplicateNameIds(projects:NamedProject[]){
  const counts=new Map<string,number>();
  for(const project of projects){
    const key=projectNameKey(project.name);
    counts.set(key,(counts.get(key)||0)+1);
  }
  return new Set(projects.filter(project=>(counts.get(projectNameKey(project.name))||0)>1).map(project=>project.project_id));
}
