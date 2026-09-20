import {useEffect,useRef,useState} from 'react';
import {FileText,FolderOpen,MoreHorizontal,Plus,Search} from 'lucide-react';
import {useApp} from '../app-context';
import {duplicateNameIds,findNameConflict,normalizeProjectName} from '../project-names';
import type {ProjectSummary} from '../types';

export function ProjectSidebar(){
  const a=useApp();
  const [query,setQuery]=useState('');
  const [menuId,setMenuId]=useState<string|null>(null);
  const [renamingId,setRenamingId]=useState<string|null>(null);
  const [draft,setDraft]=useState('');
  const [deleting,setDeleting]=useState<ProjectSummary|null>(null);
  const [busy,setBusy]=useState(false);
  const menuRef=useRef<HTMLDivElement>(null);
  const renameRef=useRef<HTMLInputElement>(null);
  const duplicates=duplicateNameIds(a.projects);
  const needle=query.trim().toLowerCase();
  const visible=a.projects.filter((project:ProjectSummary)=>!needle||project.name.toLowerCase().includes(needle));

  useEffect(()=>{
    if(!menuId)return;
    const close=(event:PointerEvent)=>{
      if(!menuRef.current?.contains(event.target as Node))setMenuId(null);
    };
    window.addEventListener('pointerdown',close);
    return()=>window.removeEventListener('pointerdown',close);
  },[menuId]);

  useEffect(()=>{
    if(renamingId)renameRef.current?.select();
  },[renamingId]);

  function startRename(project:ProjectSummary){
    setMenuId(null);
    setRenamingId(project.project_id);
    setDraft(project.name);
  }

  async function commitRename(project:ProjectSummary){
    const name=normalizeProjectName(draft);
    if(!renamingId)return;
    if(!name||name===project.name){
      setRenamingId(null);
      return;
    }
    const clash=findNameConflict(a.projects,name,project.project_id);
    if(clash)return;
    setBusy(true);
    try{
      await a.renameProject(project.project_id,name);
      setRenamingId(null);
    }finally{
      setBusy(false);
    }
  }

  async function confirmDelete(){
    if(!deleting)return;
    setBusy(true);
    try{
      await a.deleteProject(deleting.project_id);
      setDeleting(null);
    }finally{
      setBusy(false);
    }
  }

  const clash=renamingId?findNameConflict(a.projects,draft,renamingId):null;

  return <div className="projects-pane">
    <button className="new-project" onClick={a.newProject}><Plus size={15}/> New project</button>
    <label className="sidebar-search">
      <Search size={14}/>
      <input aria-label="Search projects" placeholder="Search" value={query} onChange={e=>setQuery(e.target.value)}/>
    </label>
    <div className="sidebar-label">Projects</div>
    <div className="project-list">
      {visible.map((project:ProjectSummary)=>{
        const selected=project.project_id===a.project?.project_id;
        const renaming=renamingId===project.project_id;
        return <div key={project.project_id} className={'project-item'+(selected?' is-open':'')} ref={menuId===project.project_id?menuRef:undefined}>
          {renaming
            ? <div className="project-rename">
                <input
                  ref={renameRef}
                  aria-label="Project name"
                  aria-invalid={!!clash||!normalizeProjectName(draft)}
                  value={draft}
                  disabled={busy}
                  onChange={e=>setDraft(e.target.value)}
                  onBlur={()=>commitRename(project)}
                  onKeyDown={e=>{
                    if(e.key==='Enter'){e.preventDefault();void commitRename(project)}
                    if(e.key==='Escape'){e.preventDefault();setRenamingId(null)}
                  }}
                />
                {clash&&<span className="field-error">“{clash.name}” already exists</span>}
                {!clash&&!normalizeProjectName(draft)&&<span className="field-error">Enter a name</span>}
              </div>
            : <button
                className={'project-row'+(selected?' selected':'')}
                onClick={()=>a.open(project.project_id)}
                onDoubleClick={e=>{e.preventDefault();startRename(project)}}
              >
                <span className="project-row-name">{project.name}</span>
                {duplicates.has(project.project_id)&&<span className="duplicate-flag">Same name</span>}
              </button>}
          <button
            className="project-more"
            aria-label={`Actions for ${project.name}`}
            aria-expanded={menuId===project.project_id}
            onClick={e=>{e.stopPropagation();setMenuId(id=>id===project.project_id?null:project.project_id)}}
          >
            <MoreHorizontal size={15}/>
          </button>
          {menuId===project.project_id&&<div className="project-menu" role="menu">
            <button role="menuitem" onClick={()=>startRename(project)}>Rename</button>
            <button role="menuitem" className="danger" onClick={()=>{setMenuId(null);setDeleting(project)}}>Delete</button>
          </div>}
          {selected&&a.project&&<div className="project-files">
            {a.project.files.map((file:any)=>(
              <button key={file.path} className={file.origin==='generated'?'generated':''} onClick={()=>a.setFile(file)}>
                <FileText size={12}/>
                <span>{file.name}</span>
              </button>
            ))}
          </div>}
        </div>;
      })}
      {!a.projects.length&&<p className="empty-projects">Your projects live here. Generate one, or import a folder.</p>}
      {!!a.projects.length&&!visible.length&&<p className="empty-projects">No projects match “{query.trim()}”.</p>}
    </div>
    <button className="import-side" onClick={a.importFolder}><FolderOpen size={14}/> Import a project</button>
    {deleting&&<div className="sheet-backdrop" onClick={()=>!busy&&setDeleting(null)}>
      <div className="confirm-sheet" role="alertdialog" aria-labelledby="delete-title" aria-describedby="delete-copy" onClick={e=>e.stopPropagation()}>
        <h2 id="delete-title">Delete “{deleting.name}”?</h2>
        <p id="delete-copy">This removes the project from this computer. It cannot be undone.</p>
        <div className="sheet-actions">
          <button disabled={busy} onClick={()=>setDeleting(null)}>Cancel</button>
          <button className="destructive" disabled={busy} onClick={()=>void confirmDelete()}>Delete</button>
        </div>
      </div>
    </div>}
  </div>;
}

export function Projects(){
  return <ProjectSidebar/>;
}
