import {useEffect,useMemo,useRef,useState} from 'react';
import {Search,Trash2} from 'lucide-react';
import {clearLogs,logEntries,subscribeLogs,type LogEntry,type LogKind} from '../debug-log';
import {Projects} from './ProjectSidebar';

function stamp(t:number){
  const date=new Date(t);
  return `${String(date.getHours()).padStart(2,'0')}:${String(date.getMinutes()).padStart(2,'0')}:${String(date.getSeconds()).padStart(2,'0')}`;
}

function LogRow({entry}:{entry:LogEntry}){
  const tone=entry.kind==='net'
    ?(entry.pending?'pending':entry.status&&entry.status>=400?'error':entry.status&&entry.status>=300?'warn':'ok')
    :entry.level;
  const body=<><span className="log-time">{stamp(entry.t)}</span><span className="log-kind">{entry.kind==='net'?(entry.method||'GET'):entry.level}</span><span className="log-text">{entry.text}</span></>;
  if(!entry.detail)return <div className={'log-row '+tone}>{body}</div>;
  return <details className={'log-row '+tone}>
    <summary>{body}</summary>
    <pre>{entry.detail}</pre>
  </details>;
}

export function LogPanel(){
  const [tick,setTick]=useState(0);
  const [query,setQuery]=useState('');
  const [filter,setFilter]=useState<'all'|LogKind>('all');
  const scroller=useRef<HTMLDivElement>(null);
  const stick=useRef(true);

  useEffect(()=>subscribeLogs(()=>setTick(n=>n+1)),[]);

  const items=logEntries();
  const visible=useMemo(()=>{
    const needle=query.trim().toLowerCase();
    return items.filter(entry=>{
      if(filter!=='all'&&entry.kind!==filter)return false;
      if(!needle)return true;
      return (entry.text+' '+(entry.detail||'')+' '+(entry.url||'')).toLowerCase().includes(needle);
    });
  },[items,query,filter,tick]);

  useEffect(()=>{
    if(!stick.current)return;
    const node=scroller.current;
    if(node)node.scrollTop=node.scrollHeight;
  },[visible.length,tick]);

  return <div className="logs-pane">
    <div className="logs-toolbar">
      <button className={filter==='all'?'active':''} onClick={()=>setFilter('all')}>All</button>
      <button className={filter==='net'?'active':''} onClick={()=>setFilter('net')}>Net</button>
      <button className={filter==='console'?'active':''} onClick={()=>setFilter('console')}>Console</button>
      <span className="logs-count">{visible.length}</span>
      <button className="logs-clear" title="Clear logs" onClick={clearLogs}><Trash2 size={13}/></button>
    </div>
    <label className="sidebar-search">
      <Search size={14}/>
      <input aria-label="Search logs" placeholder="Filter" value={query} onChange={e=>setQuery(e.target.value)}/>
    </label>
    <div
      className="logs-list"
      ref={scroller}
      onScroll={e=>{
        const node=e.currentTarget;
        stick.current=node.scrollHeight-node.scrollTop-node.clientHeight<40;
      }}
    >
      {visible.map(entry=><LogRow key={entry.id} entry={entry}/>)}
      {!visible.length&&<p className="empty-projects">Network calls and console output show up here.</p>}
    </div>
  </div>;
}

export function HomeSidebar(){
  const [tab,setTab]=useState<'projects'|'logs'>('projects');
  return <div className="home-sidebar">
    <div className="home-side-tabs" role="tablist">
      <button role="tab" aria-selected={tab==='projects'} className={tab==='projects'?'active':''} onClick={()=>setTab('projects')}>Projects</button>
      <button role="tab" aria-selected={tab==='logs'} className={tab==='logs'?'active':''} onClick={()=>setTab('logs')}>Logs</button>
    </div>
    {tab==='projects'?<Projects/>:<LogPanel/>}
  </div>;
}
