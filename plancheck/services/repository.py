"""Filesystem unit-of-work with immutable revisions and an atomic manifest pointer."""
from __future__ import annotations
import json, os, uuid
from pathlib import Path
from datetime import datetime,timezone
from typing import Protocol, Callable
from filelock import FileLock
from plancheck.core.building import Building,DesignBrief,DesktopProject
from plancheck.core.settings import get_settings

class RevisionConflict(ValueError):pass

def now():return datetime.now(timezone.utc).isoformat()
def atomic_json(path:Path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        with tmp.open('w',encoding='utf8') as f:json.dump(data,f,indent=2,ensure_ascii=False,allow_nan=False);f.write('\n');f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if tmp.exists():tmp.unlink()

class ProjectRepository(Protocol):
    def load(self,project_id:str)->DesktopProject:...
    def commit(self,project_id:str,expected_revision:int,update:Callable)->DesktopProject:...

class FileProjectRepository:
    def __init__(self,root:Path|None=None):self.root=root or get_settings().data_dir
    def path(self,pid):
        if not pid or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in pid):raise ValueError('Invalid project identifier')
        return self.root/pid
    def manifest(self,pid):
        p=self.path(pid)/'project.json'
        if not p.exists():raise FileNotFoundError('Project not found')
        data=json.loads(p.read_text())
        if 'current_revision' not in data:raise ValueError('Legacy project needs model migration before editing')
        return data
    def list(self):
        if not self.root.exists():return []
        out=[]
        for path in self.root.glob('*/project.json'):
            try:
                m=json.loads(path.read_text());out.append({'project_id':m['project_id'],'name':m['name'],'updated_at':m.get('updated_at',m.get('created_at','')),'revision':m.get('current_revision',0),'source':m.get('source','import'),'ready':'current_revision' in m})
            except (ValueError,KeyError,OSError):continue
        return sorted(out,key=lambda p:p['updated_at'],reverse=True)
    def _snapshot(self,pid,revision):return json.loads((self.path(pid)/'revisions'/str(revision)/'model.json').read_text())
    def load(self,pid):
        m=self.manifest(pid);s=self._snapshot(pid,m['current_revision'])
        return DesktopProject(project_id=pid,name=m['name'],revision=m['current_revision'],created_at=m['created_at'],updated_at=m['updated_at'],brief=m.get('brief'),building=s['building'],rules=s.get('rules',[]),checks=s.get('checks',[]),coverage=s.get('coverage') or {},files=self.files(pid,m),sheets=m.get('sheets',[]),import_meta=m.get('import_meta') or {},can_undo=bool(m.get('undo')),can_redo=bool(m.get('redo')))
    def files(self,pid,m=None):
        m=m or self.manifest(pid)
        files=[{'name':'model.json','path':f"revisions/{m['current_revision']}/model.json",'origin':'generated'},{'name':'rules.json','path':f"revisions/{m['current_revision']}/rules.json",'origin':'generated'},{'name':'mismatches.json','path':f"revisions/{m['current_revision']}/mismatches.json",'origin':'generated'}]
        files.extend(m.get('source_files',[]))
        for p in sorted((self.path(pid)/'notes').glob('*.md')):files.append({'name':p.name,'path':str(p.relative_to(self.path(pid))),'origin':'user'})
        return files
    def _write_snapshot(self,pid,rev,snapshot):
        directory=self.path(pid)/'revisions'/str(rev);directory.mkdir(parents=True,exist_ok=False)
        atomic_json(directory/'model.json',snapshot)
        atomic_json(directory/'rules.json',{'rules':snapshot.get('rules',[])})
        atomic_json(directory/'mismatches.json',{'checks':snapshot.get('checks',[]),'coverage':snapshot.get('coverage') or {}})
    def create(self,name,building:Building,rules=None,brief:DesignBrief|None=None,source='generated',project_id=None,source_files=None,sheets=None,import_meta=None):
        pid=project_id or 'pc-'+uuid.uuid4().hex[:12];directory=self.path(pid);directory.mkdir(parents=True,exist_ok=True)
        if (directory/'project.json').exists():raise ValueError('Project already exists')
        timestamp=now();snapshot={'building':building.model_dump(mode='json'),'rules':rules or [],'checks':[]}
        self._write_snapshot(pid,1,snapshot)
        m={'schema_version':2,'project_id':pid,'name':name,'created_at':timestamp,'updated_at':timestamp,'current_revision':1,'next_revision':2,'undo':[],'redo':[],'brief':brief.model_dump() if brief else None,'source':source,'source_files':source_files or [],'documents':[],'sheets':sheets or [],'import_meta':import_meta or {},'units':'ft','model_file':'revisions/1/model.json'}
        atomic_json(directory/'project.json',m);(directory/'notes').mkdir(exist_ok=True)
        return self.load(pid)
    def commit(self,pid,expected_revision,update):
        directory=self.path(pid)
        with FileLock(str(directory/'.write.lock')):
            m=self.manifest(pid)
            if m['current_revision']!=expected_revision:raise RevisionConflict('This project changed. Reload before applying this edit.')
            snapshot=self._snapshot(pid,expected_revision);result=update(snapshot)
            if result is not None:snapshot=result
            Building.model_validate(snapshot['building'])
            revision=m['next_revision']
            # Orphaned revisions from an interrupted commit are never reused.
            while (directory/'revisions'/str(revision)).exists():revision+=1
            self._write_snapshot(pid,revision,snapshot)
            m.update(current_revision=revision,next_revision=revision+1,updated_at=now(),undo=m.get('undo',[])+[expected_revision],redo=[],model_file=f'revisions/{revision}/model.json')
            atomic_json(directory/'project.json',m)
        return self.load(pid)
    def history(self,pid,expected_revision,direction):
        with FileLock(str(self.path(pid)/'.write.lock')):
            m=self.manifest(pid)
            if m['current_revision']!=expected_revision:raise RevisionConflict('Project revision changed')
            stack=m.get(direction,[])
            if not stack:raise ValueError(f'Nothing to {direction}')
            other='redo' if direction=='undo' else 'undo';target=stack.pop();m.setdefault(other,[]).append(m['current_revision'])
            # A fresh revision prevents ABA races against previously previewed repairs.
            revision=m['next_revision']
            while (self.path(pid)/'revisions'/str(revision)).exists():revision+=1
            self._write_snapshot(pid,revision,self._snapshot(pid,target));m.update(current_revision=revision,next_revision=revision+1,updated_at=now(),model_file=f'revisions/{revision}/model.json')
            atomic_json(self.path(pid)/'project.json',m)
        return self.load(pid)
