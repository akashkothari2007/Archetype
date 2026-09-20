import {useEffect,useRef,useState} from 'react';
import {ChevronDown,FileText,FolderOpen,MoreHorizontal,Plus,Search} from 'lucide-react';
import {useApp} from '../app-context';
import {normalizeProjectName,uniqueProjectName} from '../project-names';
import type {ProjectSummary} from '../types';

export function ProjectSidebar(){
  const a=useApp();
  const [query,setQuery]=useState('');
  const [menuId,setMenuId]=useState<string|null>(null);
  const [renamingId,setRenamingId]=useState<string|null>(null);
  const [draft,setDraft]=useState('');
  const [deleting,setDeleting]=useState<ProjectSummary|null>(null);
  const [busy,setBusy]=useState(false);
  const [createOpen,setCreateOpen]=useState(false);
  const menuRef=useRef<HTMLDivElement>(null);
  const createRef=useRef<HTMLDivElement>(null);
  const renameRef=useRef<HTMLInputElement>(null);
  const needle=query.trim().toLowerCase();
  const visible=a.projects.filter((project:ProjectSummary)=>!needle||project.name.toLowerCase().includes(needle));

  useEffect(()=>{
    if(!menuId&&!createOpen)return;
    const close=(event:PointerEvent)=>{
      const target=event.target as Node;
      if(menuRef.current?.contains(target)||createRef.current?.contains(target))return;
      setMenuId(null);
      setCreateOpen(false);
    };
    const onKey=(event:KeyboardEvent)=>{
      if(event.key==='Escape'){setMenuId(null);setCreateOpen(false)}
    };
    window.addEventListener('pointerdown',close);
    window.addEventListener('keydown',onKey);
    return()=>{window.removeEventListener('pointerdown',close);window.removeEventListener('keydown',onKey)};
  },[menuId,createOpen]);

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
    setBusy(true);
    try{
      await a.renameProject(project.project_id,uniqueProjectName(a.projects,name,project.project_id));
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

  return <div className="projects-pane">
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
                  aria-invalid={!normalizeProjectName(draft)}
                  value={draft}
                  disabled={busy}
                  onChange={e=>setDraft(e.target.value)}
                  onBlur={()=>commitRename(project)}
                  onKeyDown={e=>{
                    if(e.key==='Enter'){e.preventDefault();void commitRename(project)}
                    if(e.key==='Escape'){e.preventDefault();setRenamingId(null)}
                  }}
                />
                {!normalizeProjectName(draft)&&<span className="field-error">Enter a name</span>}
              </div>
            : <button
                className={'project-row'+(selected?' selected':'')}
                onClick={()=>a.open(project.project_id)}
                onDoubleClick={e=>{e.preventDefault();startRename(project)}}
              >
                <span className="project-row-name">{project.name}</span>
              </button>}
          <button
            className="project-more"
            aria-label={`Actions for ${project.name}`}
            aria-expanded={menuId===project.project_id}
            onClick={e=>{e.stopPropagation();setCreateOpen(false);setMenuId(id=>id===project.project_id?null:project.project_id)}}
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
    <div className="create-side" ref={createRef}>
      <button className="new-project" aria-haspopup="menu" aria-expanded={createOpen} onClick={()=>{setMenuId(null);setCreateOpen(open=>!open)}}>
        <Plus size={15}/> New project <ChevronDown size={14}/>
      </button>
      {createOpen&&<div className="project-menu create-menu" role="menu">
        <button role="menuitem" onClick={()=>{setCreateOpen(false);a.newProject()}}><Plus size={14}/> Generate</button>
        <button role="menuitem" onClick={()=>{setCreateOpen(false);a.importFolder()}}><FolderOpen size={14}/> Import</button>
      </div>}
    </div>
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
