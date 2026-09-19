"""Deterministic scoped repair workers. Proposals never persist geometry."""
from concurrent.futures import ThreadPoolExecutor
import math
from plancheck.core.building import Building
from plancheck.services.commands import apply_commands,wall_length,wall_points,CommandError
from plancheck.services.compliance import check_building,from_rule_units

def _candidate(building:Building,check:dict):
    walls={w.id:w for w in building.walls};opens={o.id:o for o in building.openings}
    eid=check['entity_id'];metric=check['metric'];required=from_rule_units(check['required'],check['unit'],metric=='area')
    if metric in ['aperture_width','opening_distance']:
        opening=opens.get(eid)
        if not opening:raise ValueError('Opening is unavailable')
        host=walls[opening.wall_id]
        if host.locked or host.structural!='nonstructural':raise ValueError('Host wall is locked or not reviewed nonstructural')
        if metric=='aperture_width':
            offset=opening.offset_ft-(required-opening.width_ft)/2
            return [{'kind':'update_opening','target_id':eid,'params':{'width_ft':required,'offset_ft':max(0,offset)}}],{host.id}
        ids=check['entity_ids'];other=opens[ids[1]]
        if other.wall_id!=host.id:raise ValueError('Only separation on one straight wall is supported')
        candidates=[other.offset_ft-required-opening.width_ft,other.offset_ft+other.width_ft+required]
        valid=[x for x in candidates if 0<=x and x+opening.width_ft<=wall_length(building,host)]
        if not valid:raise ValueError('There is no free interval for the required separation')
        offset=min(valid,key=lambda x:(abs(x-opening.offset_ft),x))
        return [{'kind':'update_opening','target_id':eid,'params':{'offset_ft':offset}}],{host.id}
    if metric in ['area','min_side']:
        from plancheck.services.compliance import rectangle_sides,room_area
        room=next(r for r in building.rooms if r.id==eid);sx,sy=rectangle_sides(room)
        alternatives=[]
        for wid in room.wall_ids:
            wall=walls.get(wid)
            if not wall or wall.locked or wall.structural!='nonstructural':continue
            a,b=wall_points(building,wall);length=wall_length(building,wall)
            cx=sum(x for x,y in room.polygon)/len(room.polygon);cy=sum(y for x,y in room.polygon)/len(room.polygon)
            nx=-(b.y-a.y)/length;ny=(b.x-a.x)/length
            if (cx-a.x)*nx+(cy-a.y)*ny>0:nx=-nx;ny=-ny
            delta=(required-room_area(room))/length if metric=='area' else required-min(sx,sy)
            if delta<=0:continue
            alternatives.append((delta,wid,[{'kind':'offset_partition','target_id':wid,'params':{'dx':nx*(delta+.005),'dy':ny*(delta+.005)}}]))
        for delta,wid,cmds in sorted(alternatives):
            try:
                apply_commands(building,cmds,actor='agent');return cmds,{wid,*room.wall_ids}
            except (ValueError,KeyError):continue
        raise ValueError('No supported nonstructural partition can move without crossing a locked boundary or invalidating an opening')
    raise ValueError('This measurement has no supported deterministic repair')

def propose_repairs(building:Building,rules:list[dict],report=None)->dict:
    before=check_building(building,rules);failures=sorted([c for c in before if c['status']=='fail'],key=lambda c:(c['rule_id'],c['entity_id']))
    blocked=[];tasks=[];accepted=[];current=building.model_copy(deep=True);writes=set()
    def prepare(check):
        try:
            commands,scope=_candidate(building,check);return check,commands,scope,None
        except (ValueError,KeyError,StopIteration) as exc:return check,[],set(),str(exc)
    with ThreadPoolExecutor(max_workers=4,thread_name_prefix='repair') as pool:
        prepared=list(pool.map(prepare,failures))
    for index,(check,commands,scope,error) in enumerate(prepared):
        if report:report(progress=.25+.6*(index+1)/max(1,len(failures)),phase='validating',message=f"Verifying repair {index+1} of {len(failures)}")
        task={'id':check['id'],'target_id':check['entity_id'],'metric':check['metric'],'allowed_tools':['update_opening'] if check['metric'] in ['aperture_width','opening_distance'] else ['offset_partition'],'execution':'serial-conflict' if scope&writes else 'parallel','status':'blocked'}
        if not error:
            try:
                if scope&writes:commands,scope=_candidate(current,check)
                candidate=apply_commands(current,commands,actor='agent');results=check_building(candidate,rules)
                old={r['id']:r for r in check_building(current,rules)}
                # A new failure, worsened existing failure, or lost verification is never an acceptable fix.
                for r in results:
                    prev=old.get(r['id'])
                    if r['status']=='fail' and (not prev or prev['status']!='fail' or (r['actual'] is not None and prev['actual'] is not None and r['actual']<prev['actual']-1e-5)):raise ValueError('The proposal introduces or worsens another requirement')
                    if r['status']=='cannot_verify' and prev and prev['status']=='pass':raise ValueError('The proposal loses a previously verified requirement')
                target=next((r for r in results if r['id']==check['id']),None)
                if not target or target['status']!='pass':raise ValueError('The proposed edit does not resolve this issue')
                current=candidate;accepted.extend(commands);writes.update(scope);task['status']='ready';task['commands']=commands
            except (ValueError,KeyError) as exc:error=str(exc)
        if error:task['reason']=error;blocked.append({'check_id':check['id'],'entity_id':check['entity_id'],'reason':error})
        tasks.append(task)
    after=check_building(current,rules)
    return {'tasks':tasks,'commands':accepted,'blocked':blocked,'before':before,'after':after,'summary':{'proposed':sum(t['status']=='ready' for t in tasks),'blocked':len(blocked),'workers':min(4,len(failures)),'before_failures':len(failures),'after_failures':sum(c['status']=='fail' for c in after)}}
