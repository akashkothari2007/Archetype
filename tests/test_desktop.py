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
    r=c.post(f'/api/desktop/projects/{pid}/commands?full=true',json={'expected_revision':p['revision'],'commands':[{'kind':'set_environment','params':{'time':18}}]});assert r.status_code==200,r.text
    assert r.json()['building']['environment']['time']==18
    wall=p['building']['walls'][0]['id']
    material=c.post(f'/api/desktop/projects/{pid}/commands',json={'expected_revision':r.json()['revision'],'commands':[{'kind':'set_material','target_id':wall,'params':{'material':'sage'}}]})
    assert material.status_code==200,material.text
    assert len(material.content)<50_000
    assert 'floors' not in material.json().get('building',{})
    assert any(item['id']==wall and item['material']=='sage' for item in material.json()['changed']['walls'])
    stale=c.post(f'/api/desktop/projects/{pid}/commands',json={'expected_revision':p['revision'],'commands':[{'kind':'set_environment','params':{'time':8}}]});assert stale.status_code==409
    assert c.post(f'/api/desktop/projects/{pid}/undo',json={'expected_revision':material.json()['revision']}).status_code==200

def test_rename_delete_and_duplicate_names(tmp_path):
    from plancheck.mocks.generation import demo_home,demo_rules
    repo=FileProjectRepository(tmp_path)
    first=repo.create('Willow House',demo_home(),demo_rules())
    second=repo.create('North Annex',demo_home(),demo_rules())
    renamed=repo.rename(second.project_id,'north annex')
    assert renamed.name=='north annex'
    try:
        repo.rename(second.project_id,'willow house')
        raise AssertionError('duplicate names should be rejected')
    except ValueError as exc:
        assert 'already exists' in str(exc)
    try:
        repo.create('WILLOW HOUSE',demo_home(),demo_rules())
        raise AssertionError('create should reject the same name')
    except ValueError as exc:
        assert 'already exists' in str(exc)
    repo.delete(second.project_id)
    assert [item['project_id'] for item in repo.list()]==[first.project_id]

def test_rename_delete_api(tmp_path,monkeypatch):
    from plancheck.core.settings import reset_settings
    monkeypatch.setenv('PLANCHECK_DATA_DIR',str(tmp_path));reset_settings()
    from plancheck.mocks.generation import demo_home,demo_rules
    repo=FileProjectRepository(tmp_path)
    one=repo.create('Alpha House',demo_home(),demo_rules())
    two=repo.create('Beta House',demo_home(),demo_rules())
    c=TestClient(app)
    clash=c.patch(f'/api/desktop/projects/{two.project_id}',json={'name':'alpha house'})
    assert clash.status_code==422
    ok=c.patch(f'/api/desktop/projects/{two.project_id}',json={'name':'Cedar House'})
    assert ok.status_code==200
    assert ok.json()['name']=='Cedar House'
    gone=c.delete(f'/api/desktop/projects/{two.project_id}')
    assert gone.status_code==200
    assert c.get(f'/api/desktop/projects/{two.project_id}').status_code==404
    assert c.get('/api/desktop/projects').json()[0]['project_id']==one.project_id

