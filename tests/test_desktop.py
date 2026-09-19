import time
from fastapi.testclient import TestClient
from plancheck.api.main import app
from plancheck.mocks.generation import demo_home,demo_rules
from plancheck.services.repository import FileProjectRepository,RevisionConflict
from plancheck.services.commands import apply_commands
from plancheck.services.repairs import propose_repairs
from plancheck.services.compliance import check_building
import pytest

def test_repair_real_geometry_and_undo(tmp_path):
    repo=FileProjectRepository(tmp_path);b=demo_home();rules=demo_rules();p=repo.create('Test home',b,rules)
    preview=propose_repairs(b,rules)
    assert preview['commands']
    assert repo.load(p.project_id).revision==1
    def change(s):s['building']=apply_commands(b,preview['commands'],actor='agent').model_dump();return s
    updated=repo.commit(p.project_id,1,change)
    assert sum(c['status']=='fail' for c in check_building(updated.building,rules))<sum(c['status']=='fail' for c in check_building(b,rules))
    with pytest.raises(RevisionConflict):repo.commit(p.project_id,1,change)
    undone=repo.history(p.project_id,updated.revision,'undo');assert undone.building==b
    redone=repo.history(p.project_id,undone.revision,'redo');assert redone.building==updated.building
    assert repo.load(p.project_id).building==redone.building

def test_structural_lock_and_failed_batch_are_atomic():
    b=demo_home();w=next(w for w in b.walls if w.locked)
    with pytest.raises(ValueError):apply_commands(b,[{'kind':'move_wall','target_id':w.id,'params':{'dx':3,'dy':0}}],actor='agent')
    assert b==demo_home()

def test_api_complete_workflow(monkeypatch,tmp_path):
    from plancheck.core.settings import reset_settings
    monkeypatch.setenv('PLANCHECK_DATA_DIR',str(tmp_path));reset_settings()
    c=TestClient(app);r=c.post('/api/desktop/generate',json={'name':'Integration home'});assert r.status_code==200
    jid=r.json()['job_id']
    for _ in range(100):
        j=c.get('/api/desktop/jobs/'+jid).json()
        if j['state'] in ['done','error']:break
        time.sleep(.05)
    assert j['state']=='done',j
    pid=j['result']['project_id'];p=c.get('/api/desktop/projects/'+pid).json();assert len(p['building']['floors'])==2
    r=c.post(f'/api/desktop/projects/{pid}/commands',json={'expected_revision':p['revision'],'commands':[{'kind':'set_environment','params':{'time':18}}]});assert r.status_code==200,r.text
    assert r.json()['building']['environment']['time']==18
    stale=c.post(f'/api/desktop/projects/{pid}/commands',json={'expected_revision':p['revision'],'commands':[{'kind':'set_environment','params':{'time':8}}]});assert stale.status_code==409
    assert c.post(f'/api/desktop/projects/{pid}/undo',json={'expected_revision':r.json()['revision']}).status_code==200
