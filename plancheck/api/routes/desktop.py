"""Desktop application endpoints; revisioned writes wrap the shared command service."""
from __future__ import annotations
import json,uuid,time,asyncio,shutil
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor,wait,FIRST_COMPLETED
from fastapi import APIRouter,Body,UploadFile,File,Form,HTTPException,Query
from fastapi.responses import FileResponse,StreamingResponse
from pydantic import BaseModel,Field
from plancheck.core.building import Building,DesignBrief,CommandBatch,RevisionRequest,DesktopProject,BuildingPatch
from plancheck.core.settings import get_settings
from plancheck.services.repository import FileProjectRepository,RevisionConflict,atomic_json
from plancheck.services.commands import apply_commands,validate_building
from plancheck.services.compliance import evaluate_building
from plancheck.services.reliability import apply_reliability
from plancheck.services.baseline_rules import layer_rules
from plancheck.api import jobs
router=APIRouter(prefix='/desktop')
_import_pool=ProcessPoolExecutor(max_workers=2)

def repo():return FileProjectRepository()
def load(pid):return repo().load(pid)
def recheck(snapshot):
    building=Building.model_validate(snapshot['building'])
    apply_reliability(building)
    snapshot['building']=building.model_dump(mode='json')
    result=evaluate_building(building,snapshot.get('rules',[]))
    snapshot['checks']=result['checks']
    snapshot['coverage']=result['coverage']
    snapshot['quarantined']=result['quarantined']
    return snapshot

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
        payload={'revision':after.revision,'can_undo':after.can_undo,'can_redo':after.can_redo,'changed':changed,'removed_ids':removed,'checks':after.checks,'coverage':after.coverage}
    if before.building.environment.model_dump()!=after.building.environment.model_dump():
        payload['environment']=after.building.environment.model_dump(mode='json')
    if before.building.site.model_dump()!=after.building.site.model_dump():
        payload['site']=after.building.site.model_dump(mode='json')
    return payload

@router.get('/health')
def health():
    settings=get_settings()
    live=settings.agent_live()
    return {
        'status':'ready',
        'schema_version':2,
        'agent_provider':'baseten' if live else 'mock',
        'generation_provider':settings.generation_provider,
        'orchestrator_model':settings.orchestrator_slug() if live else None,
        'subagent_model':settings.subagent_slug() if live else None,
        'image_model_id':settings.image_model_id or None,
        'image_ready':settings.image_live(),
        'splat_ready':settings.splat_live(),
    }

@router.get('/projects')
def projects():return repo().list()

class ProjectRename(BaseModel):
    name:str=Field(min_length=1,max_length=160)

@router.patch('/projects/{pid}')
def rename_project(pid:str,body:ProjectRename):
    return repo().rename(pid,body.name)

@router.delete('/projects/{pid}')
def delete_project(pid:str):
    repo().delete(pid)
    return {'ok':True}

@router.post('/generate')
def generate(brief:DesignBrief):
    name=repo().unique_name(brief.name)
    if name!=brief.name:brief=brief.model_copy(update={'name':name})
    def work(report):
        from plancheck.generation import generate_from_brief
        result=generate_from_brief(brief,report)
        report(phase='saving',progress=.94,kind='working',label='Saving',message='Saving your editable project')
        project=repo().create(brief.name,result.building,layer_rules(result.rules or []),brief)
        if result.program:
            # Keep the interpretation of the prompt auditable next to the geometry.
            atomic_json(repo().path(project.project_id)/'program.json',{'program':result.program,'layouts':result.layouts,'notes':result.notes,'llm_calls':result.llm_calls,'recovered_from':result.recovered_from,'research':result.research})
        project=repo().commit(project.project_id,project.revision,recheck)
        return {'project_id':project.project_id,'notes':result.notes,'research':result.research}
    return {'job_id':jobs.submit(work,'Preparing your project')}

class AppearanceRequest(BaseModel):
    image:str
    projector:list[float]=Field(default_factory=list)
    prompt:str=''

@router.get('/projects/{pid}/appearance')
def get_appearance(pid:str):
    folder=repo().path(pid)
    if not (folder/'project.json').is_file():
        raise HTTPException(404,'Project not found')
    path=folder/'appearance.json'
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding='utf-8'))

@router.post('/projects/{pid}/appearance')
def appearance(pid:str,body:AppearanceRequest):
    load(pid)
    settings=get_settings()
    if not settings.image_live():
        raise HTTPException(400,'Flux is not configured. Set PLANCHECK_IMAGE_MODEL_ID and a Hack the North API key as PLANCHECK_IMAGE_API_KEY.')
    try:
        from plancheck.services.image_edit import decode_png
        png=decode_png(body.image)
    except Exception as exc:
        raise HTTPException(400,str(exc)) from None
    projector=body.projector[:16] if len(body.projector)>=16 else []
    user_prompt=(body.prompt or '').strip()
    def work(report, snapshot=png, matrix=projector, style=user_prompt):
        from plancheck.services.image_edit import guide_prompt, edit_png
        from plancheck.services.appearance_style import sample_palette
        report(phase='editing',progress=.15,message='Painting a photoreal guide with Flux')
        scene=guide_prompt(load(pid).brief, style)
        result=edit_png(snapshot, prompt=scene, on_status=lambda msg: report(phase='editing',progress=.12,message=msg))
        report(phase='saving',progress=.82,message='Applying the enhanced exterior materials')
        folder=repo().path(pid)
        (folder/'appearance.png').write_bytes(result)
        meta={'projector':matrix,'scope':'exterior','prompt':style,'palette':sample_palette(result)}
        atomic_json(folder/'appearance.json',meta)
        return {'palette':meta['palette']}
    return {'job_id':jobs.submit(work,'Painting the 3D view')}

class ImagineFurnitureRequest(BaseModel):
    image:str
    prompt:str=''
    floor_id:str
    x:float
    y:float
    rotation_deg:float=0
    width_ft:float=Field(default=4,gt=0,le=40)
    depth_ft:float=Field(default=3,gt=0,le=40)
    height_ft:float=Field(default=3,gt=0,le=20)

@router.post('/projects/{pid}/imagine-furniture')
def imagine_furniture(pid:str,body:ImagineFurnitureRequest):
    project=load(pid)
    if not any(floor.id==body.floor_id for floor in project.building.floors):
        raise HTTPException(400,'That floor is not in this project')
    settings=get_settings()
    if not settings.image_live():
        raise HTTPException(400,'Flux is not configured. Set PLANCHECK_IMAGE_MODEL_ID and a Hack the North API key as PLANCHECK_IMAGE_API_KEY.')
    if not settings.splat_live():
        raise HTTPException(400,'TripoSplat is not configured. Set PLANCHECK_SPLAT_URL and PLANCHECK_SPLAT_API_KEY.')
    try:
        from plancheck.services.image_edit import decode_png, prepare_furniture_guide
        png=prepare_furniture_guide(decode_png(body.image))
    except Exception as exc:
        raise HTTPException(400,str(exc)) from None
    style=(body.prompt or '').strip()
    place={
        'floor_id':body.floor_id,
        'x':body.x,
        'y':body.y,
        'rotation_deg':body.rotation_deg,
        'width_ft':body.width_ft,
        'depth_ft':body.depth_ft,
        'height_ft':body.height_ft,
    }
    def work(report, snapshot=png, extra=style, pose=place):
        from plancheck.services.commands import uid
        from plancheck.services.image_edit import furniture_prompt, edit_png
        from plancheck.services.splat import generate_splat, splat_filename
        object_id=uid('object')
        report(phase='editing',progress=.12,message='Painting the furniture with Flux')
        photo=edit_png(snapshot, prompt=furniture_prompt(extra), on_status=lambda msg: report(phase='editing',progress=.18,message=msg))
        report(phase='splatting',progress=.52,message='Reconstructing the furniture with TripoSplat')
        splat=generate_splat(photo, num_gaussians=65536)
        folder=repo().path(pid)/'furniture'
        folder.mkdir(parents=True,exist_ok=True)
        stem=f'furniture/{object_id}'
        (repo().path(pid)/f'{stem}.png').write_bytes(photo)
        splat_name=splat_filename(splat, stem)
        (repo().path(pid)/splat_name).write_bytes(splat)
        return {'object':{'id':object_id,'asset_id':'imagine','kind':'furniture','splat':splat_name,**pose}}
    return {'job_id':jobs.submit(work,'Imagining furniture')}

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
    floor_id:str=''
    history:list[dict]=Field(default_factory=list)
    violations:list[dict]|None=None
    fix_new_issues:bool=True

@router.post('/projects/{pid}/agent')
def agent(pid:str,body:ChatRequest):
    project=load(pid)
    if project.revision!=body.expected_revision:raise RevisionConflict('The project changed before the repair started')
    def work(report):
        from plancheck.services.agent import respond_new
        report(phase='analyzing',progress=.08,message='Reading the building and approved requirements');time.sleep(.3)
        result=respond_new(building=project.building,rules=project.rules,prompt=body.message,fix_new_issues=body.fix_new_issues,violations=body.violations,report=report,context=body.context,floor_id=body.floor_id or None,selected_ids=body.selected_ids,history=body.history)
        report(phase='preview-ready',progress=.96,message='Preparing changes for your review')
        run_id=uuid.uuid4().hex[:12];result.update(run_id=run_id,expected_revision=body.expected_revision)
        atomic_json(repo().path(pid)/'repairs'/f'{run_id}.json',result)
        return result
    return {'job_id':jobs.submit(work,'Reviewing your request')}

@router.post('/projects/{pid}/repairs/{run_id}/apply',response_model=DesktopProject)
def apply_repair(pid:str,run_id:str,body:RevisionRequest):
    if not run_id.isalnum():raise ValueError('Invalid repair identifier')
    proposal=json.loads((repo().path(pid)/'repairs'/f'{run_id}.json').read_text(encoding='utf8'))
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
        allowed={'applies_to','metric','operator','value','unit','target_ids','supported','qualifiers','excludes','applies_to_filter'}
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

@router.get('/projects/{pid}/mep')
def get_mep(pid:str):
    """Return mep.json for the project, or empty structure if none."""
    load(pid)
    mep_path=repo().path(pid)/'mep.json'
    if mep_path.is_file():
        return json.loads(mep_path.read_text(encoding='utf8'))
    return {'floors':[]}

@router.get('/projects/{pid}/files/{relative:path}')
def get_file(pid:str,relative:str):
    base=repo().path(pid).resolve();path=(base/relative).resolve()
    if not path.is_relative_to(base) or path.suffix.lower() not in ['.json','.md','.pdf','.png','.dxf','.ifc','.splat','.ply','.spz']:raise HTTPException(403,'File is outside this project')
    if not path.is_file():raise HTTPException(404,'File not found')
    types={'.pdf':'application/pdf','.png':'image/png','.json':'application/json','.md':'text/markdown; charset=utf-8','.dxf':'application/dxf','.ifc':'application/octet-stream'}
    return FileResponse(path,media_type=types.get(path.suffix.lower(),'application/octet-stream'),content_disposition_type='inline',filename=path.name)

@router.post('/import-native',response_model=DesktopProject)
def import_native(body:dict=Body(...)):
    name=repo().unique_name(str(body.get('name') or 'Imported project'))
    building=Building.model_validate(body['building']);validate_building(building)
    return repo().create(name,building,layer_rules(body.get('rules',[])),DesignBrief.model_validate(body['brief']) if body.get('brief') else None,source='import')

@router.post('/import')
def import_sources(files:list[UploadFile]=File(...),name:str=Form('Imported building'),roles:str=Form('{}')):
    name=repo().unique_name(name)
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
        from shapely.geometry import Polygon
        started=time.perf_counter()
        building=Building();rules=[];sheet_cards=[];progress_path=str(base/'_import_progress.jsonl')
        Path(progress_path).write_text('')
        cursor=0
        sheets_done=[]
        totals={'pages':0,'pages_read':0,'walls':0,'rooms':0,'doors':0,'windows':0,'skipped':0,'rules':0}

        def upsert(card):
            sid=card.get('sheet_id') or f"{card.get('sheet_no')}-{card.get('page')}"
            for i,existing in enumerate(sheets_done):
                if existing.get('sheet_id')==sid:
                    sheets_done[i]=card;return
            sheets_done.append(card)

        def recompute():
            totals['pages']=len(sheets_done) or totals['pages']
            totals['pages_read']=sum(1 for s in sheets_done if s.get('extracted'))
            totals['skipped']=sum(1 for s in sheets_done if not s.get('extracted'))
            totals['walls']=sum(s.get('walls') or 0 for s in sheets_done if s.get('extracted'))
            totals['rooms']=sum(s.get('rooms') or 0 for s in sheets_done if s.get('extracted'))
            totals['doors']=sum(s.get('doors') or 0 for s in sheets_done if s.get('extracted'))
            totals['windows']=sum(s.get('windows') or 0 for s in sheets_done if s.get('extracted'))

        def drain(progress=None,phase=None,message=None):
            nonlocal cursor
            path=Path(progress_path)
            if path.exists():
                lines=path.read_text().splitlines()
                for line in lines[cursor:]:
                    if not line.strip():continue
                    try:event=json.loads(line)
                    except json.JSONDecodeError:continue
                    if event.get('kind')=='classified':
                        for card in event.get('sheets') or []:upsert(card)
                        report(progress=event.get('progress',0.15),phase='classify',message=event.get('message') or 'Classifying pages',sheets_done=list(sheets_done),totals=dict(totals))
                    elif event.get('kind')=='sheet':
                        upsert(event.get('sheet') or {})
                        recompute()
                        report(progress=event.get('progress',0.5),phase='extracting',message=event.get('message') or 'Reading sheets',sheets_done=list(sheets_done),totals=dict(totals))
                    elif event.get('kind')=='phase':
                        if event.get('phase')=='standards' and event.get('rules') is not None:totals['rules']=event['rules']
                        report(progress=event.get('progress',progress or 0.2),phase=event.get('phase') or phase or 'working',message=event.get('message') or message or '',sheets_done=list(sheets_done),totals=dict(totals))
                cursor=len(lines)
            if message:
                recompute();report(progress=progress or 0,phase=phase or 'working',message=message,sheets_done=list(sheets_done),totals=dict(totals))

        all_mep_infos=[]
        futures={}
        for document in documents:
            if document['role']=='standards' and document['name'].lower().endswith('.pdf'):
                futures[_import_pool.submit(extract_standards,document,progress_path)]=('standards',document)
            elif Path(document['name']).suffix.lower() in ['.pdf','.dxf','.ifc']:
                futures[_import_pool.submit(import_document,document,str(base),progress_path)]=('drawing',document)
        drain(progress=0.02,phase='classify',message='Classifying pages')
        pending=set(futures)
        while pending:
            finished,pending=wait(pending,timeout=0.12,return_when=FIRST_COMPLETED)
            drain()
            for future in finished:
                kind,_document=futures[future]
                payload=future.result()
                if kind=='standards':
                    rules.extend(payload);totals['rules']=len(rules)
                    drain(progress=0.88,phase='standards',message='Extracting rules from standards')
                else:
                    building=merge_buildings(building,Building.model_validate(payload.get('building',payload)))
                    for card in payload.get('sheets') or []:upsert(card)
                    all_mep_infos.extend(payload.get('mep_sheets') or [])
                    recompute()
                    drain(progress=0.9,phase='build',message='Building rooms and openings')
        drain()
        report(progress=.95,phase='saving',message='Saving',sheets_done=list(sheets_done),totals=dict(totals))
        floors={f.id for f in building.floors}
        for card in sheets_done:
            ids=[]
            for raw in card.get('levels') or []:
                try:level=int(str(raw).strip())
                except (TypeError,ValueError):continue
                fid=f'level-{level}'
                if fid in floors:ids.append(fid)
            card['floor_ids']=ids
        area=0.0
        for room in building.rooms:
            if room.polygon and len(room.polygon)>=3:
                try:area+=abs(Polygon(room.polygon).area)
                except Exception:pass
        elapsed=time.perf_counter()-started
        from plancheck.core.settings import get_settings
        if get_settings().auto_approve:
            for rule in rules:
                if rule.get('supported'):
                    rule['status']='approved'
        rules=layer_rules(rules)
        totals.update({'rooms':len(building.rooms),'walls':len(building.walls),'doors':sum(1 for o in building.openings if o.kind=='door'),'windows':sum(1 for o in building.openings if o.kind=='window'),'pages_read':sum(1 for s in sheets_done if s.get('extracted'))})
        source_files=[{k:v for k,v in d.items() if k!='absolute_path'} for d in documents]
        summary={'name':name,'floors':len(building.floors),'rooms':len(building.rooms),'area_sqft':round(area),'doors':totals['doors'],'windows':totals['windows'],'walls':len(building.walls),'rules':len(rules),'violations':0,'elapsed_s':round(elapsed,2),'pages':totals['pages'],'pages_read':totals['pages_read']}
        project=repo().create(name,building,rules,source='import',project_id=pid,source_files=source_files,sheets=sheets_done,import_meta=summary)
        project=repo().commit(pid,project.revision,recheck)
        summary['violations']=sum(1 for c in project.checks if c.get('status')=='fail')
        print(f"[import] save {elapsed:.2f}s walls={len(building.walls)} rooms={len(building.rooms)}",flush=True)
        # MEP registration + mep.json assembly (after project save so file persists)
        if all_mep_infos:
            try:
                from plancheck.services.mep import register_sheet,assign_rooms,build_mep_json
                from plancheck.core.schemas import MepSheetData,SheetGeometry
                arch_geom=None;arch_scale=1.0
                for card in sheets_done:
                    if card.get('extracted') and card.get('geometry_url') and card.get('discipline','architectural')=='architectural':
                        gpath=base/card['geometry_url']
                        if gpath.is_file():
                            g=SheetGeometry.model_validate_json(gpath.read_text())
                            if g.grid.bubbles and g.scale_pts_per_ft:
                                arch_geom=g;arch_scale=g.scale_pts_per_ft;break
                registrations={};room_dicts=[{'id':r.id,'polygon':r.polygon} for r in building.rooms]
                for info in all_mep_infos:
                    mep_path=base/'sheets'/f'{info["sheet_id"]}.mep.json'
                    if not mep_path.is_file():continue
                    mep_data=MepSheetData.model_validate_json(mep_path.read_text())
                    if arch_geom:
                        reg=register_sheet(arch_geom,mep_data,arch_scale)
                        if reg.get('equipment') and room_dicts:assign_rooms(reg['equipment'],room_dicts)
                        registrations[info['sheet_id']]=reg
                    else:
                        registrations[info['sheet_id']]={'transform':[1,0,0,0,1,0],'matched_labels':[],'rms_error_ft':9999.0,'confidence':'manual','equipment':[{'tag':eq.tag,'xy_ft':[eq.xy_pt[0]/arch_scale,eq.xy_pt[1]/arch_scale],'in_room':None,'kind':eq.kind,'assumed_z_ft':1.5,'z_assumed':True} for eq in mep_data.equipment]}
                floor_map={}
                for info in all_mep_infos:
                    levels=info.get('levels') or []
                    if levels:
                        try:floor_map[info['sheet_id']]=f'level-{int(str(levels[0]).strip())}'
                        except (TypeError,ValueError):pass
                    if info['sheet_id'] not in floor_map:
                        floor_map[info['sheet_id']]=building.floors[0].id if building.floors else 'unknown'
                mep_result=build_mep_json(all_mep_infos,registrations,floor_map)
                from plancheck.services.repository import atomic_json as _aj
                _aj(base/'mep.json',mep_result)
                print(f"[import] mep.json written floors={len(mep_result.get('floors',[]))} sheets={len(all_mep_infos)} registered={len(registrations)}",flush=True)
            except Exception as exc:
                import traceback;traceback.print_exc()
                print(f"[import] mep.json assembly failed: {exc}",flush=True)
        return {'project_id':pid,'review_count':len(building.review),'summary':summary}
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
