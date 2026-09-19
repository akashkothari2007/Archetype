"""Desktop application endpoints; revisioned writes wrap the shared command service."""
from __future__ import annotations
import json,uuid,time,asyncio,shutil
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
from fastapi import APIRouter,Body,UploadFile,File,Form,HTTPException,Query
from fastapi.responses import FileResponse,StreamingResponse
from pydantic import BaseModel,Field
from plancheck.core.building import Building,DesignBrief,CommandBatch,RevisionRequest,DesktopProject,BuildingPatch
from plancheck.services.repository import FileProjectRepository,RevisionConflict,atomic_json
from plancheck.services.commands import apply_commands,validate_building
from plancheck.services.compliance import check_building
from plancheck.api import jobs
router=APIRouter(prefix='/desktop')
_import_pool=ProcessPoolExecutor(max_workers=2)

def repo():return FileProjectRepository()
def load(pid):return repo().load(pid)
def recheck(snapshot):snapshot['checks']=check_building(Building.model_validate(snapshot['building']),snapshot.get('rules',[]));return snapshot

_COLLECTIONS=('vertices','walls','rooms','openings','objects')

def building_patch(before:DesktopProject,after:DesktopProject)->dict:
    changed={}
    removed=[]
    for name in _COLLECTIONS:
        prev={e.id:e.model_dump(mode='json') for e in getattr(before.building,name)}
        nxt={e.id:e.model_dump(mode='json') for e in getattr(after.building,name)}
        updates=[nxt[i] for i in nxt if prev.get(i)!=nxt[i]]
        if updates:changed[name]=updates
        removed.extend(i for i in prev if i not in nxt)
    payload={'revision':after.revision,'can_undo':after.can_undo,'can_redo':after.can_redo,'changed':changed,'removed_ids':removed,'checks':after.checks}
    if before.building.environment.model_dump()!=after.building.environment.model_dump():
        payload['environment']=after.building.environment.model_dump(mode='json')
    return payload

@router.get('/health')
def health():return {'status':'ready','schema_version':2,'agent_provider':'mock','generation_provider':'demo'}

@router.get('/projects')
def projects():return repo().list()

@router.post('/generate')
def generate(brief:DesignBrief):
    def work(report):
        from plancheck.mocks.generation import demo_home,demo_rules
        for i,message in enumerate(['Reading your design brief','Arranging the two-storey demo layout','Connecting walls and openings','Preparing materials and fixtures','Validating editable geometry']):
            report(phase=['analyzing','planning','working','working','validating'][i],progress=.1+i*.16,message=message);time.sleep(.32)
        building=demo_home();report(phase='saving',progress=.94,message='Saving your editable project')
        project=repo().create(brief.name,building,demo_rules(),brief)
        project=repo().commit(project.project_id,project.revision,recheck)
        return {'project_id':project.project_id}
    return {'job_id':jobs.submit(work,'Preparing your project')}

@router.get('/projects/{pid}',response_model=DesktopProject)
def project(pid:str):return load(pid)

@router.post('/projects/{pid}/commands')
def commands(pid:str,batch:CommandBatch,full:bool=Query(False)):
    before=load(pid)
    def update(s):
        s['building']=apply_commands(Building.model_validate(s['building']),batch.commands).model_dump(mode='json');return recheck(s)
    after=repo().commit(pid,batch.expected_revision,update)
    return after if full else BuildingPatch.model_validate(building_patch(before,after))

@router.post('/projects/{pid}/undo',response_model=DesktopProject)
def undo(pid:str,body:RevisionRequest):return repo().history(pid,body.expected_revision,'undo')

@router.post('/projects/{pid}/redo',response_model=DesktopProject)
def redo(pid:str,body:RevisionRequest):return repo().history(pid,body.expected_revision,'redo')

class ChatRequest(RevisionRequest):
    message:str=Field(default='Check and fix issues',max_length=4000)
    context:str='2D'
    selected_ids:list[str]=Field(default_factory=list)

@router.post('/projects/{pid}/agent')
def agent(pid:str,body:ChatRequest):
    project=load(pid)
    if project.revision!=body.expected_revision:raise RevisionConflict('The project changed before the repair started')
    def work(report):
        from plancheck.mocks.agent_provider import respond
        report(phase='analyzing',progress=.08,message='Reading the selected model and approved requirements');time.sleep(.3)
        report(phase='planning',progress=.18,message='Assigning bounded tasks to geometry workers');time.sleep(.3)
        result=respond(project.building,project.rules,body.message,body.context,body.selected_ids,report)
        report(phase='preview-ready',progress=.96,message='Preparing changes for your review')
        run_id=uuid.uuid4().hex[:12];result.update(run_id=run_id,expected_revision=body.expected_revision)
        atomic_json(repo().path(pid)/'repairs'/f'{run_id}.json',result)
        return result
    return {'job_id':jobs.submit(work,'Reviewing your request')}

@router.post('/projects/{pid}/repairs/{run_id}/apply',response_model=DesktopProject)
def apply_repair(pid:str,run_id:str,body:RevisionRequest):
    if not run_id.isalnum():raise ValueError('Invalid repair identifier')
    proposal=json.loads((repo().path(pid)/'repairs'/f'{run_id}.json').read_text())
    if proposal['expected_revision']!=body.expected_revision:raise RevisionConflict('This preview is stale. Run the request again.')
    if not proposal['commands']:raise ValueError('This preview has no changes to apply')
    def update(s):
        s['building']=apply_commands(Building.model_validate(s['building']),proposal['commands'],actor=proposal.get('actor','agent')).model_dump(mode='json');return recheck(s)
    return repo().commit(pid,body.expected_revision,update)

class RuleReview(RevisionRequest):
    status:str='approved'
    changes:dict=Field(default_factory=dict)

@router.patch('/projects/{pid}/rules/{rule_id}',response_model=DesktopProject)
def review_rule(pid:str,rule_id:str,body:RuleReview):
    from plancheck.core.schemas import Rule
    if body.status not in ['approved','pending','rejected']:raise ValueError('Invalid rule review status')
    def update(s):
        rule=next((r for r in s['rules'] if r['rule_id']==rule_id),None)
        if rule is None:raise ValueError('Unknown rule')
        allowed={'applies_to','metric','operator','value','unit','target_ids','supported','qualifiers'}
        if set(body.changes)-allowed:raise ValueError('This rule field cannot be edited')
        rule.update(body.changes,status=body.status);Rule.model_validate(rule);return recheck(s)
    return repo().commit(pid,body.expected_revision,update)

@router.post('/projects/{pid}/rules',response_model=DesktopProject)
def add_rule(pid:str,body:dict=Body(...)):
    from plancheck.core.schemas import Rule
    rule=Rule.model_validate(body['rule']);rule.status='pending'
    def update(s):
        if any(r['rule_id']==rule.rule_id for r in s['rules']):raise ValueError('Rule identifier already exists')
        s['rules'].append(rule.model_dump());return recheck(s)
    return repo().commit(pid,body['expected_revision'],update)

@router.get('/projects/{pid}/files/{relative:path}')
def get_file(pid:str,relative:str):
    base=repo().path(pid).resolve();path=(base/relative).resolve()
    if not path.is_relative_to(base) or path.suffix.lower() not in ['.json','.md','.pdf','.png','.dxf','.ifc']:raise HTTPException(403,'File is outside this project')
    if not path.is_file():raise HTTPException(404,'File not found')
    return FileResponse(path)

@router.post('/import-native',response_model=DesktopProject)
def import_native(body:dict=Body(...)):
    building=Building.model_validate(body['building']);validate_building(building)
    return repo().create(str(body.get('name','Imported project')),building,body.get('rules',[]),DesignBrief.model_validate(body['brief']) if body.get('brief') else None,source='import')

@router.post('/import')
def import_sources(files:list[UploadFile]=File(...),name:str=Form('Imported building'),roles:str=Form('{}')):
    role_map=json.loads(roles);pid='pc-'+uuid.uuid4().hex[:12];base=repo().path(pid);documents=[]
    for f in files:
        filename=Path(f.filename or 'source').name;suffix=Path(filename).suffix.lower()
        if suffix not in ['.pdf','.dxf','.ifc','.md']:continue
        doc_id='doc-'+uuid.uuid4().hex[:12];relative=f'sources/{doc_id}/{filename}';path=base/relative;path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('wb') as target:shutil.copyfileobj(f.file,target)
        role=role_map.get(f.filename) or ('standards' if any(word in (f.filename or '').lower() for word in ['standard','manual','specification']) else 'drawing')
        documents.append({'id':doc_id,'name':filename,'path':relative,'absolute_path':str(path),'role':role,'origin':'imported'})
    if not documents:raise ValueError('Choose a folder containing PDF, DXF, or IFC files')
    def work(report):
        from plancheck.services.imports import import_document,merge_buildings,extract_standards
        building=Building();rules=[]
        for i,document in enumerate(documents):
            report(progress=.04+.85*i/len(documents),phase='extracting',message=f"Reading {document['name']}")
            if document['role']=='standards' and document['name'].lower().endswith('.pdf'):
                rules.extend(_import_pool.submit(extract_standards,document).result())
            elif Path(document['name']).suffix.lower() in ['.pdf','.dxf','.ifc']:
                result=_import_pool.submit(import_document,document,str(base)).result();building=merge_buildings(building,Building.model_validate(result))
        report(progress=.95,phase='validating',message='Saving source geometry and review items')
        source_files=[{k:v for k,v in d.items() if k!='absolute_path'} for d in documents]
        project=repo().create(name,building,rules,source='import',project_id=pid,source_files=source_files)
        return {'project_id':pid,'review_count':len(building.review)}
    return {'job_id':jobs.submit(work,'Importing your sources'),'project_id':pid}

@router.get('/jobs/{jid}')
def get_job(jid:str):
    result=jobs.get_job(jid)
    if result is None:raise HTTPException(404,'Unknown job')
    return result

@router.post('/jobs/{jid}/cancel')
def cancel_job(jid:str):return jobs.cancel(jid)

@router.get('/jobs/{jid}/events')
async def events(jid:str):
    async def stream():
        previous=''
        while True:
            job=jobs.get_job(jid)
            if job is None:yield 'event: error\ndata: {"error":"Unknown job"}\n\n';return
            payload=job.model_dump_json()
            if payload!=previous:yield f'data: {payload}\n\n';previous=payload
            if job.state in ['done','error','cancelled']:return
            await asyncio.sleep(.3)
    return StreamingResponse(stream(),media_type='text/event-stream')
