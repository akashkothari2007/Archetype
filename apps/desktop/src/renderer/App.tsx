import {useEffect,useRef,useState,type MouseEvent} from 'react';
import {DockviewReact,type DockviewReadyEvent,type IDockviewPanelProps} from 'dockview-react';
import {ArrowUp,ArrowLeft,Plus,FolderOpen,Folder,Check,LoaderCircle,Undo2,Redo2,LayoutTemplate, X, ArrowRight} from 'lucide-react';
import {FloorPlan} from './components/FloorPlan';
import {ModelView,type PaintFn} from './components/ModelView';
import {AssetLibrary} from './components/AssetLibrary';
import {ImportBoard} from './components/ImportBoard';
import {ImportOverview} from './components/ImportOverview';
import {SourceCompare} from './components/SourceCompare';
import {FilePreview} from './components/FilePreview';
import {Projects} from './components/ProjectSidebar';
import {HomeSidebar,LogPanel} from './components/LogPanel';
import type {DesktopProject,DesignBrief,ModelCommand,Job,ProjectSummary,ImportSummary} from './types';
import {api,applyPatch,base,isDesktopProject,waitJob} from './api';
import {AppContext,useApp} from './app-context';
import {findNameConflict} from './project-names';
import {type LayerStop} from './components/plan-layers';
const initial:DesignBrief={name:'Willow House',building_use:'Home',floors:'2',rooms:'3 bedrooms, 2 bathrooms, kitchen, living room',area:'2,400 sq ft',style:'Warm minimal',prompt:''};
const steps:[keyof DesignBrief,string,string,boolean?][]=[['name','What will you call your project?','A name for your next idea.'],['building_use','What kind of building is it?','Home, office, retail, or something else.'],['floors','How many floors do you have in mind?','We’ll keep this in your design brief.'],['rooms','What spaces should it include?','Describe the rooms and the way you’ll use them.'],['area','How much space are you working with?','Include your preferred unit: square feet or square meters.'],['style','How should the space feel?','Materials, light, colors, or a few words about the atmosphere.'],['prompt','Anything else the design should answer to?','Adjacencies, who uses it, constraints of the site — write it the way you’d brief a colleague. Optional.',true]];
const lastStep=steps.length-1;
const desktop=(window as any).archetype as {platform?:string;importFolder:()=>Promise<any>;popupMenu?:(name:string,x:number,y:number)=>void;onMenuCommand?:(cb:(command:string)=>void)=>()=>void}|undefined;
const showWindowMenu=desktop?.platform==='win32'||desktop?.platform==='linux';
function Brand(){return <span className="brand-mark"><svg width="25" height="25" viewBox="0 0 28 28" fill="none"><path d="M4 21V9L14 3l10 6v12l-10 5L4 21Z M4 9l10 6 10-6M14 15v11M9 6l10 6v11" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round"/></svg></span>}
function AppMenu(){if(!showWindowMenu)return null;const open=(name:string,e:MouseEvent<HTMLButtonElement>)=>{const r=e.currentTarget.getBoundingClientRect();desktop?.popupMenu?.(name,Math.round(r.left),Math.round(r.bottom))};return <nav className="app-menu">{['File','Edit','View','Help'].map(name=><button key={name} type="button" onClick={e=>open(name,e)}>{name}</button>)}</nav>}
function Workspace({params}:IDockviewPanelProps){const a=useApp();if(!a.project)return null;const props={building:a.project.building,floorId:a.floor,onCommand:a.command,selectedId:a.selected,onSelect:a.setSelected,units:a.units,busy:!!a.job,checks:a.project.checks,sheets:a.project.sheets,projectId:a.project.project_id,onFloor:a.setFloor,checkPulse:a.checkPulse};return params.mode==='3d'?<ModelView {...props} registerPaint={a.registerPaint}/>:<FloorPlan {...props} layerStop={a.layerStop} onLayerCounts={a.setLayerCounts}/>}
function Assets({params}:IDockviewPanelProps){const a=useApp();return a.project?<AssetLibrary tab={params.tab||'furniture'} mode={a.mode} building={a.project.building} onCommand={a.command} layerStop={a.layerStop} layerCounts={a.layerCounts} onLayerStop={a.setLayerStop}/>:null}
function Assistant(){
  const a=useApp();
  const [text,setText]=useState('');
  const messages=useRef<HTMLDivElement>(null);
  useEffect(()=>{messages.current?.scrollTo(0,messages.current.scrollHeight)},[a.messages,a.job]);
  const send=()=>{if(text.trim()){a.chat(text);setText('')}};
  return <div className="agent-pane">
    <div className="messages" ref={messages}>
      {!a.messages.length&&<div className="agent-welcome">
        <Brand/>
        <h3>A second pair of eyes.</h3>
        <p>Explore your design, review requirements, and make considered changes together.</p>
        <button onClick={()=>a.chat('Check and fix issues')}>Review this building <ArrowRight size={13}/></button>
        <button onClick={()=>a.chat('Enlarge the kitchen toward the living room')}>Enlarge the kitchen <ArrowRight size={13}/></button>
        <button onClick={()=>a.chat('Make the exterior warm brick')}>Make the exterior warm brick <ArrowRight size={13}/></button>
        <button onClick={()=>a.chat('Set evening lighting')}>See it in evening light <ArrowRight size={13}/></button>
        <small>Local demo agent · changes use real geometry tools</small>
      </div>}
      {a.messages.map((m:any,i:number)=><div key={i} className={'message '+m.role}>{m.role==='assistant'&&<span className="assistant-label"><Brand/> Archetype</span>}<p>{m.text}</p></div>)}
      {a.job&&<div className="thinking"><LoaderCircle size={14} className="spin"/><span>{a.job.message}</span><button onClick={()=>api('/jobs/'+a.job.job_id+'/cancel',{})}>Stop</button></div>}
      {a.summary&&<div className="proposal">
        <div className="proposal-title"><Check size={15}/> {a.summary.commands?.length?'Changes applied':'Nothing changed'}</div>
        {a.summary.commands?.map((c:any,i:number)=><div className="task-row" key={i}>{c.kind.replaceAll('_',' ')}<small>{c.target_id}</small></div>)}
        {a.summary.blocked?.map((b:any,i:number)=><p key={i} className="blocked">{b.reason}</p>)}
        <p>{a.summary.commands?.length||0} edits · Undo in the title bar</p>
        <button className="text-button" onClick={()=>a.setSummary(null)}>Dismiss</button>
      </div>}
      {a.proposal&&<div className="proposal">
        <div className="proposal-title"><Check size={15}/> {a.proposal.commands?.length?'Changes ready to review':'Nothing could be changed'}</div>
        <p>{a.proposal.commands?.length||0} edits proposed · {a.proposal.blocked?.length||0} blocked</p>
        <details><summary>View proposed changes</summary>
          {a.proposal.commands?.map((c:any,i:number)=><div className="task-row" key={i}>{c.kind.replaceAll('_',' ')}<small>{c.target_id}</small></div>)}
          {a.proposal.blocked?.map((b:any,i:number)=><p key={i} className="blocked">{b.reason}</p>)}
        </details>
        {!!a.proposal.commands?.length&&<button className="primary" disabled={a.saving} onClick={a.apply}>Apply changes</button>}
        <button className="text-button" onClick={()=>a.setProposal(null)}>Dismiss</button>
      </div>}
    </div>
    <div className="composer">
      <span className={'context-chip '+a.mode}>{a.mode==='2d'?'2D Floor Plan':'3D Model'}{a.selected?' · Selection':''}</span>
      <textarea aria-label="Message Archetype" placeholder="Move a wall, change a finish, ask about your building…" value={text} onChange={e=>setText(e.target.value)} onKeyDown={e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();send()}}}/>
      <div className="composer-foot">
        <span>Edits apply to your design · Undo anytime</span>
        <button aria-label="Send message" disabled={!text.trim()||!!a.job} onClick={send}><ArrowUp size={16}/></button>
      </div>
    </div>
  </div>;
}
function Checks(){
  const a=useApp();
  const checks=a.project?.checks||[];
  const failures=checks.filter((c:any)=>c.status==='fail');
  const quarantined=checks.filter((c:any)=>c.status==='quarantined');
  return <div className="agent-pane"><div className="review-list">
    <h3>{failures.length} items to review{quarantined.length?` · ${quarantined.length} quarantined`:''}</h3>
    <p className="muted">Measured from the current model and your approved requirements.</p>
    <button className="primary" disabled={!!a.job} onClick={()=>{a.openPanel('assistant');a.chat('Check and fix issues')}}>Prepare repairs</button>
    {checks.filter((c:any)=>c.status!=='pass').map((c:any)=><button className={'check-item '+c.status} key={c.id} onClick={()=>{a.setSelected(c.entity_id);a.pulseCheck()}}>
      <span className="check-status">{c.status.replace('_',' ')}</span>
      <strong>{c.metric.replaceAll('_',' ')}</strong>
      <p>{c.message}</p>
      <small>{c.source_doc}{c.source_page?` · p. ${c.source_page}`:''}</small>
    </button>)}
    {!checks.filter((c:any)=>c.status!=='pass').length&&<p>Approve a requirement in Standards to begin checking.</p>}
  </div></div>;
}
function Standards(){
  const a=useApp();
  return <div className="agent-pane"><div className="review-list">
    <h3>Project requirements</h3>
    <p className="muted">Review the source, scope, and units before activating a requirement.</p>
    {a.project?.rules.map((r:any)=><Rule key={r.rule_id} rule={r}/>)}
    {!a.project?.rules.length&&<p>No standards imported yet. Include a standards PDF when importing a project.</p>}
  </div></div>;
}
function Rule({rule:r}:{rule:any}){
  const a=useApp();
  const [scope,setScope]=useState(r.applies_to);
  const [value,setValue]=useState(r.value);
  const winner=r.superseded_by&&a.project?.rules.find((item:any)=>item.rule_id===r.superseded_by);
  return <details className={'rule-item'+(r.superseded_by?' superseded':'')}>
    <summary>
      <span>{r.metric.replaceAll('_',' ')}</span>
      <span className="rule-meta">
        {r.origin==='baseline'&&<span className="baseline-badge">Archetype Baseline</span>}
        <small>{r.superseded_by?`overridden by ${winner?.source_doc||r.superseded_by}`:r.status}</small>
      </span>
    </summary>
    <p>{r.source_text}</p>
    <small>{r.source_doc}{r.source_page?` · p. ${r.source_page}`:''}{r.source_section?` · ${r.source_section}`:''}</small>
    {r.superseded_by&&<p className="muted">overridden by {winner?.source_doc||r.superseded_by}</p>}
    <label>Applies to<input value={scope} onChange={e=>setScope(e.target.value)}/></label>
    <label>Requirement ({r.unit})<input type="number" value={value} onChange={e=>setValue(Number(e.target.value))}/></label>
    {r.qualifiers?.map((q:string)=><p className="muted" key={q}>{q}</p>)}
    {!r.superseded_by&&<button className="primary" onClick={()=>a.review(r.rule_id,r.status==='approved'?'pending':'approved',{applies_to:scope,value})}>{r.status==='approved'?'Return to review':'Approve requirement'}</button>}
  </details>;
}
function SourcePanel(){const a=useApp();return a.project?<SourceCompare project={a.project}/>:null}
function Logs(){return <LogPanel/>}
const components={projects:Projects,logs:Logs,workspace:Workspace,assets:Assets,assistant:Assistant,checks:Checks,standards:Standards,source:SourcePanel};
function addLibraryTabs(d:DockviewReadyEvent['api'], furniture:any){
  d.addPanel({id:'fixtures',component:'assets',title:'Fixtures',params:{tab:'fixtures'},position:{referencePanel:furniture,direction:'within'},inactive:true});
  d.addPanel({id:'materials',component:'assets',title:'Materials',params:{tab:'materials'},position:{referencePanel:furniture,direction:'within'},inactive:true});
  d.addPanel({id:'environment',component:'assets',title:'Environment',params:{tab:'environment'},position:{referencePanel:furniture,direction:'within'},inactive:true});
}
function syncLibraryForMode(d:DockviewReadyEvent['api']|null|undefined, mode:'2d'|'3d'){
  if(!d)return;
  const furniture=d.getPanel('furniture');
  if(!furniture)return;
  const site=d.getPanel('site');
  if(!site){
    d.addPanel({id:'site',component:'assets',title:'Site',params:{tab:'site'},position:{referencePanel:furniture,direction:'within'},inactive:true});
    try{d.getPanel('site')?.api.moveTo({index:1,skipSetActive:true})}catch{}
  }
}
function layoutDefault(d:DockviewReadyEvent['api']){
  if(!d.getPanel('plan')){
    const plan=d.addPanel({id:'plan',component:'workspace',title:'2D Floor Plan',params:{mode:'2d'}});
    d.addPanel({id:'model',component:'workspace',title:'3D Model',params:{mode:'3d'},position:{referencePanel:plan,direction:'within'},inactive:true});
    d.addPanel({id:'source',component:'source',title:'Source · Model',position:{referencePanel:plan,direction:'within'},inactive:true});
    const left=d.addPanel({id:'projects',component:'projects',title:'Projects',position:{referencePanel:plan,direction:'left'}});
    left.api.setSize({width:252});
    d.addPanel({id:'logs',component:'logs',title:'Logs',position:{referencePanel:left,direction:'within'},inactive:true});
    const assistant=d.addPanel({id:'assistant',component:'assistant',title:'Assistant',position:{referencePanel:plan,direction:'right'}});
    assistant.api.setSize({width:330});
    d.addPanel({id:'checks',component:'checks',title:'Checks',position:{referencePanel:assistant,direction:'within'},inactive:true});
    d.addPanel({id:'standards',component:'standards',title:'Standards',position:{referencePanel:assistant,direction:'within'},inactive:true});
    const furniture=d.addPanel({id:'furniture',component:'assets',title:'Furniture',params:{tab:'furniture'},position:{referencePanel:plan,direction:'below'}});
    furniture.api.setSize({height:248});
    addLibraryTabs(d, furniture);
    plan.api.setActive();
    return;
  }
  if(!d.getPanel('assistant')){
    const ref=d.getPanel('agent')||d.getPanel('plan')!;
    const assistant=d.addPanel({id:'assistant',component:'assistant',title:'Assistant',position:{referencePanel:ref,direction:d.getPanel('agent')?'within':'right'}});
    if(!d.getPanel('agent'))assistant.api.setSize({width:330});
    d.addPanel({id:'checks',component:'checks',title:'Checks',position:{referencePanel:assistant,direction:'within'},inactive:true});
    d.addPanel({id:'standards',component:'standards',title:'Standards',position:{referencePanel:assistant,direction:'within'},inactive:true});
    d.getPanel('agent')?.api.close();
  }
  if(!d.getPanel('furniture')){
    const ref=d.getPanel('assets')||d.getPanel('plan')!;
    const furniture=d.addPanel({id:'furniture',component:'assets',title:'Furniture',params:{tab:'furniture'},position:{referencePanel:ref,direction:d.getPanel('assets')?'within':'below'}});
    if(!d.getPanel('assets'))furniture.api.setSize({height:248});
    addLibraryTabs(d, furniture);
    d.getPanel('assets')?.api.close();
  }
  if(!d.getPanel('logs')){
    const left=d.getPanel('projects');
    if(left)d.addPanel({id:'logs',component:'logs',title:'Logs',position:{referencePanel:left,direction:'within'},inactive:true});
  }
  // Keep the permanent work surfaces available even if one is closed accidentally.
  const plan=d.getPanel('plan');
  if(plan&&!d.getPanel('model'))d.addPanel({id:'model',component:'workspace',title:'3D Model',params:{mode:'3d'},position:{referencePanel:plan,direction:'within'},inactive:true});
  if(plan&&!d.getPanel('source'))d.addPanel({id:'source',component:'source',title:'Source · Model',position:{referencePanel:plan,direction:'within'},inactive:true});
}
export default function App(){
  const [project,setProject]=useState<DesktopProject|null>(null);
  const [projects,setProjects]=useState<ProjectSummary[]>([]);
  const [floor,setFloor]=useState('ground');
  const [mode,setMode]=useState<'2d'|'3d'>('2d');
  const [layerStop,setLayerStop]=useState<LayerStop>(5);
  const [layerCounts,setLayerCounts]=useState([0,0,0,0,0,0]);
  const [units,setUnits]=useState<'metric'|'imperial'>('imperial');
  const [selected,setSelected]=useState<string|null>(null);
  const [intake,setIntake]=useState(false);
  const [step,setStep]=useState(0);
  const [brief,setBrief]=useState(initial);
  const [job,setJob]=useState<Job|null>(null);
  const [saving,setSaving]=useState(false);
  const [error,setError]=useState('');
  const [online,setOnline]=useState(false);
  const [generating,setGenerating]=useState(false);
  const [messages,setMessages]=useState<any[]>([]);
  const [proposal,setProposal]=useState<any>(null);
  const [summary,setSummary]=useState<any>(null);
  const [file,setFile]=useState<any>(null);
  const [fileText,setFileText]=useState('');
  const [layoutKey,setLayoutKey]=useState(0);
  const [importPid,setImportPid]=useState<string|null>(null);
  const [overview,setOverview]=useState<ImportSummary|null>(null);
  const [pendingPid,setPendingPid]=useState<string|null>(null);
  const [pendingPanel,setPendingPanel]=useState<string|null>(null);
  const [checkPulse,setCheckPulse]=useState(0);
  const input=useRef<HTMLInputElement>(null);
  const dock=useRef<any>(null);
  const painter=useRef<PaintFn|null>(null);
  const registerPaint=useRef((fn:PaintFn|null)=>{painter.current=fn}).current;
  const current=useRef(project);current.current=project;
  const nameClash=findNameConflict(projects,brief.name);
  async function refresh(){try{setProjects(await api('/projects'));setOnline(true)}catch{setOnline(false)}}
  useEffect(()=>{refresh();const timer=setInterval(refresh,5000);api<any>('/health').then(h=>setGenerating(!!h.generation_provider&&h.generation_provider!=='demo')).catch(()=>{});return()=>clearInterval(timer)},[]);
  useEffect(()=>{const platform=desktop?.platform||'web';document.documentElement.dataset.platform=platform;document.documentElement.classList.toggle('desktop',!!desktop);document.documentElement.style.colorScheme='light'},[]);
  useEffect(()=>{if(!error)return;const t=setTimeout(()=>setError(''),9000);return()=>clearTimeout(t)},[error]);
  useEffect(()=>{const show=()=>{const d=dock.current;d?.getPanel('model')?.api.setActive();syncLibraryForMode(d,'3d');d?.getPanel('site')?.api.setActive()};window.addEventListener('archetype:show-site',show);return()=>window.removeEventListener('archetype:show-site',show)},[]);
  useEffect(()=>{if(file&&project&&!file.name.toLowerCase().endsWith('.pdf'))fetch(base+`/projects/${project.project_id}/files/${file.path}`).then(r=>r.text()).then(setFileText).catch(e=>setFileText(String(e)))},[file,project?.project_id]);
  async function open(id:string){try{const p=await api<DesktopProject>('/projects/'+id);setProject(p);setFloor(p.building.floors[0]?.id||'');setSelected(null);setMessages([]);setProposal(null);setSummary(null);setIntake(false)}catch(e){setError(String(e))}}
  function newProject(){setProject(null);setIntake(true);setStep(0);setBrief(initial)}
  async function generate(){const clash=findNameConflict(projects,brief.name);if(clash){setError(`A project named “${clash.name}” already exists. Choose a different name.`);return}try{const {job_id}=await api('/generate',brief);const result=await waitJob(job_id,setJob);await refresh();await open(result.project_id)}catch(e){setError(String(e))}finally{setJob(null)}}
  async function command(commands:ModelCommand[]){const p=current.current;if(!p||saving)return;setSaving(true);try{const updated=await api(`/projects/${p.project_id}/commands`,{expected_revision:p.revision,commands});setProject(isDesktopProject(updated)?updated:applyPatch(p,updated));setProposal(null)}catch(e){setError(String(e))}finally{setSaving(false)}}
  async function history(direction:string){if(!project||saving)return;setSaving(true);try{setProject(await api(`/projects/${project.project_id}/${direction}`,{expected_revision:project.revision}));setProposal(null)}catch(e){setError(String(e))}finally{setSaving(false)}}
  useEffect(()=>{const key=(e:KeyboardEvent)=>{if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='z'&&!['INPUT','TEXTAREA'].includes((e.target as HTMLElement)?.tagName)){e.preventDefault();history(e.shiftKey?'redo':'undo')}};window.addEventListener('keydown',key);return()=>window.removeEventListener('keydown',key)},[project,saving]);
  useEffect(()=>{if(!desktop?.onMenuCommand)return;return desktop.onMenuCommand(cmd=>{if(cmd==='new-project')newProject();if(cmd==='import')importFolder();if(cmd==='close-project'){setProject(null);setIntake(false);setOverview(null);setPendingPid(null)}if(cmd==='undo')history('undo');if(cmd==='redo')history('redo');if(cmd==='reset-layout'){localStorage.removeItem('archetype-layout');setLayoutKey(k=>k+1)}})},[project,saving]);
  async function chat(text:string){if(!project||job)return;openPanel('assistant');const turn={role:'user',text};setMessages(m=>[...m,turn]);setProposal(null);setSummary(null);try{const {job_id}=await api(`/projects/${project.project_id}/agent`,{expected_revision:project.revision,message:text,context:mode,floor_id:floor,selected_ids:selected?[selected]:[],history:[...messages,turn].slice(-6).map((m:any)=>({role:m.role,text:m.text}))});const result=await waitJob(job_id,setJob);setMessages(m=>[...m,{role:'assistant',text:result.message}]);if(result.intent==='appear'&&result.appearance_prompt){dock.current?.getPanel('model')?.api.setActive();for(let i=0;i<40&&!painter.current;i++)await new Promise(r=>setTimeout(r,50));if(!painter.current)setMessages(m=>[...m,{role:'assistant',text:'Open the 3D Model tab so I can paint the exterior.'}]);else await painter.current(result.appearance_prompt);return}if(result.commands?.length){if(result.applied){setProject(await api('/projects/'+project.project_id));setSummary(result)}else{try{const p=current.current||project;setProject(await api(`/projects/${p.project_id}/repairs/${result.run_id}/apply`,{expected_revision:p.revision}));setSummary(result)}catch{setProposal(result)}}}else if(result.blocked?.length)setProposal(result)}catch(e){setError(String(e))}finally{setJob(null)}}
  async function apply(){if(!project||!proposal)return;setSaving(true);try{setProject(await api(`/projects/${project.project_id}/repairs/${proposal.run_id}/apply`,{expected_revision:project.revision}));setSummary(proposal);setProposal(null)}catch(e){setError(String(e))}finally{setSaving(false)}}
  async function review(id:string,status:string,changes:object){if(!project)return;try{setProject(await api(`/projects/${project.project_id}/rules/${id}`,{expected_revision:project.revision,status,changes},'PATCH'));setProposal(null)}catch(e){setError(String(e))}}
  async function importFolder(){if(desktop){try{const result=await desktop.importFolder();if(!result)return;if(result.job_id){setImportPid(result.project_id||null);const done=await waitJob(result.job_id,setJob);await refresh();if(done.summary){setOverview(done.summary);setPendingPid(done.project_id)}else await open(done.project_id)}else{await refresh();await open(result.project_id)}}catch(e){setError(String(e))}finally{setJob(null);setImportPid(null)}}else input.current?.click()}
  async function renameProject(id:string,name:string){try{const updated=await api<DesktopProject>('/projects/'+id,{name},'PATCH');await refresh();if(current.current?.project_id===id)setProject(updated)}catch(e){setError(String(e));throw e}}
  async function deleteProject(id:string){try{await api('/projects/'+id,undefined,'DELETE');if(current.current?.project_id===id){setProject(null);setIntake(false);setOverview(null);setPendingPid(null);setFile(null);setMessages([]);setProposal(null);setSummary(null)}await refresh()}catch(e){setError(String(e));throw e}}
  async function importFiles(files:FileList|null){if(!files?.length)return;try{const list=Array.from(files);const manifest=list.find(f=>f.name==='project.json');if(manifest){const m=JSON.parse(await manifest.text());const snapshot=list.find(f=>f.webkitRelativePath.endsWith(`/revisions/${m.current_revision}/model.json`));if(snapshot){const s=JSON.parse(await snapshot.text());const p=await api('/import-native',{name:m.name,brief:m.brief,...s});await refresh();await open(p.project_id);return}}const form=new FormData();for(const f of list)if(/\.(pdf|dxf|ifc|md)$/i.test(f.name))form.append('files',f,f.webkitRelativePath||f.name);form.append('name',list[0].webkitRelativePath.split('/')[0]||'Imported building');const started=await api('/import',form);setImportPid(started.project_id||null);const result=await waitJob(started.job_id,setJob);await refresh();if(result.summary){setOverview(result.summary);setPendingPid(result.project_id)}else await open(result.project_id)}catch(e){setError(String(e))}finally{setJob(null);setImportPid(null);if(input.current)input.current.value=''}}
  async function enterImported(target:string){const id=pendingPid;if(!id)return;setOverview(null);setPendingPanel(target);await open(id)}
  useEffect(()=>{if(!project||!pendingPanel)return;const api=dock.current;const map:{[k:string]:string}={floors:'plan',rooms:'plan',area:'plan',openings:'plan',open:'plan',source:'source',rules:'standards',checks:'checks'};const id=map[pendingPanel]||'plan';api?.getPanel(id)?.api.setActive();setPendingPanel(null)},[project,pendingPanel]);
  function openPanel(id:string){dock.current?.getPanel(id)?.api.setActive()}
  function syncDockTitles(d=dock.current){const n=(current.current?.checks||[]).filter((c:any)=>c.status==='fail').length;d?.getPanel('checks')?.api.setTitle(n?`Checks (${n})`:'Checks')}
  function onReady({api:d}:DockviewReadyEvent){dock.current=d;try{layoutDefault(d)}catch(err){console.warn('dock layout failed',err)}syncDockTitles(d);syncLibraryForMode(d,'2d');d.onDidActivePanelChange(p=>{if(p?.id==='plan'){setMode('2d');syncLibraryForMode(d,'2d')}if(p?.id==='model'){setMode('3d');syncLibraryForMode(d,'3d')}});d.onDidRemovePanel(p=>{if(p.id==='plan'||p.id==='model'||p.id==='source')queueMicrotask(()=>layoutDefault(d))})}
  useEffect(()=>syncDockTitles(),[project?.checks,layoutKey]);
  const state={project,projects,floor,setFloor,mode,units,selected,setSelected,newProject,open,importFolder,renameProject,deleteProject,command,job,saving,messages,proposal,setProposal,summary,setSummary,registerPaint,chat,apply,review,setFile,openPanel,checkPulse,pulseCheck:()=>setCheckPulse(n=>n+1),layerStop,setLayerStop,layerCounts,setLayerCounts};
  return <AppContext.Provider value={state}><div className="app"><header className="titlebar"><button className="app-logo" title="Archetype" onClick={()=>{setProject(null);setIntake(false);setOverview(null);setPendingPid(null)}}><Brand/></button><AppMenu/><button className="app-brand" onClick={()=>{setProject(null);setIntake(false);setOverview(null);setPendingPid(null)}}><span>Archetype</span></button>{project?<><span className="breadcrumb">/</span><span className="project-title">{project.name}</span><div className="top-controls"><select aria-label="Active floor" value={floor} onChange={e=>{setFloor(e.target.value);setSelected(null)}}>{project.building.floors.map(f=><option key={f.id} value={f.id}>{f.name}</option>)}</select><button title="Undo" disabled={!project.can_undo||saving} onClick={()=>history('undo')}><Undo2 size={16}/></button><button title="Redo" disabled={!project.can_redo||saving} onClick={()=>history('redo')}><Redo2 size={16}/></button><select aria-label="Display units" value={units} onChange={e=>setUnits(e.target.value as any)}><option value="imperial">ft / in</option><option value="metric">m / cm</option></select><button title="Reset layout" onClick={()=>{localStorage.removeItem('archetype-layout');setLayoutKey(k=>k+1)}}><LayoutTemplate size={16}/></button></div></>:<span className="home-status"><span className={'local-dot '+(!online?'offline':'')}/>{online?'Your ideas, kept local':'Connecting to your workspace…'}</span>}</header>{project?<div className="editor-shell"><DockviewReact key={`${layoutKey}-tabs`} className="dockview-theme-light" components={components} onReady={onReady}/></div>:<div className="home-shell"><aside><HomeSidebar/></aside><main className={'home-main'+(overview||job&&(importPid||job.sheets_done?.length)?' importing':'')}>{overview?<ImportOverview summary={overview} onOpen={enterImported}/>:job&&(importPid||job.sheets_done?.length)?<ImportBoard job={job} projectId={importPid}/>:job?<div className="generation-progress"><div className="progress-orbit"><Brand/></div><h1>Making room for your idea.</h1><p>{job.message}</p><div className="progress-track"><div style={{width:job.progress*100+'%'}}/></div><small>{generating?'Planning the spaces, then compiling an editable plan':'Demo generation · an editable two-storey home'}</small></div>:intake?<div className="intake"><button className="back" onClick={()=>step?setStep(step-1):setIntake(false)}><ArrowLeft size={15}/> Back</button><div className="step-dots">{steps.map((s,i)=><span key={s[0]} className={i<=step?'active':''}/>)}</div><h1>{steps[step][1]}</h1><p>{steps[step][2]}</p>{steps[step][0]==='prompt'?<textarea autoFocus key={step} rows={5} aria-label={steps[step][1]} value={String(brief.prompt)} onChange={e=>setBrief({...brief,prompt:e.target.value})}/>:<input autoFocus key={step} aria-label={steps[step][1]} value={String(brief[steps[step][0]])} onChange={e=>setBrief({...brief,[steps[step][0]]:e.target.value})} onKeyDown={e=>{if(e.key==='Enter'&&String(brief[steps[step][0]]).trim()&&!(steps[step][0]==='name'&&nameClash))step===lastStep?generate():setStep(step+1)}}/>}{steps[step][0]==='name'&&nameClash&&<p className="field-error" role="alert">A project named &ldquo;{nameClash.name}&rdquo; already exists. Choose a different name.</p>}<button className="primary" disabled={(!steps[step][3]&&!String(brief[steps[step][0]]).trim())||!online||(steps[step][0]==='name'&&!!nameClash)} onClick={()=>step===lastStep?generate():setStep(step+1)}>{step===lastStep?'Generate design':'Continue'}<ArrowRight size={15}/></button><small>{generating?'Your brief becomes a space program, then walls, doors and windows you can edit.':'The demo saves your brief and creates a fixed two-storey home.'}</small></div>:<div className="welcome"><div className="welcome-symbol"><Brand/></div><h1>Every building starts<br/>with a plan.</h1><p>A thoughtful space to design, explore, and refine.</p><div className="home-actions"><button className="primary" disabled={!online} onClick={newProject}><Plus size={17}/> Generate a building design <ArrowRight size={15}/></button><button className="secondary" disabled={!online} onClick={importFolder}><FolderOpen size={17}/> Import a project</button></div><small>PDF, DXF, IFC, or an existing Archetype project</small>{projects.length>0&&<div className="recent"><span>Pick up where you left off</span>{projects.slice(0,3).map(p=><button key={p.project_id} onClick={()=>open(p.project_id)}><span><Folder size={15}/>{p.name}</span><ArrowRight size={14}/></button>)}</div>}</div>}<div className="home-footer">A little clarity. A lot of possibility.</div></main></div>}{error&&<div role="alert" className="toast"><span>{error.replace(/^Error: /,'')}</span><button onClick={()=>setError('')}><X size={15}/></button></div>}{file&&project&&<FilePreview file={file} project={project} text={fileText} onClose={()=>setFile(null)}/>}<input ref={input} hidden type="file" multiple {...{webkitdirectory:''} as any} onChange={e=>importFiles(e.target.files)}/></div></AppContext.Provider>;
}
