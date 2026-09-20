"""Validated geometry commands. All callers receive a copy; failures change nothing."""
from __future__ import annotations
import math
import uuid
from typing import Any
from shapely.geometry import LineString, Polygon
from shapely.ops import polygonize, unary_union
from plancheck.core.building import Building, BuildingWall, Vertex, Opening, PlacedObject, Room, ModelCommand

class CommandError(ValueError):
    pass

def uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"

def wall_points(b: Building, w: BuildingWall):
    vs={v.id:v for v in b.vertices}
    return vs[w.start_id],vs[w.end_id]

def wall_length(b: Building,w: BuildingWall) -> float:
    a,c=wall_points(b,w);return math.hypot(c.x-a.x,c.y-a.y)

def _wall_allowed(w: BuildingWall,actor: str):
    if w.locked or (actor=='agent' and w.structural!='nonstructural'):
        raise CommandError(f'Wall {w.id} is locked or is not reviewed nonstructural geometry')

def validate_building(b: Building) -> None:
    ids=[e.id for seq in [b.floors,b.vertices,b.walls,b.openings,b.rooms,b.objects] for e in seq]
    if len(ids)!=len(set(ids)):raise CommandError('Entity identifiers must be unique')
    floors={f.id for f in b.floors}; vs={v.id:v for v in b.vertices}; ws={w.id:w for w in b.walls}
    for v in b.vertices:
        if v.floor_id not in floors:raise CommandError('Vertex references an unknown floor')
    for w in b.walls:
        if w.start_id not in vs or w.end_id not in vs:raise CommandError('Wall endpoint is missing')
        if w.floor_id not in floors or any(vs[k].floor_id!=w.floor_id for k in [w.start_id,w.end_id]):raise CommandError('Wall crosses floors')
        if wall_length(b,w)<.02:raise CommandError('Wall must be longer than 0.02 feet')
    intervals={}
    for op in b.openings:
        w=ws.get(op.wall_id)
        if not w:raise CommandError('Opening host wall is missing')
        if op.offset_ft<0 or op.offset_ft+op.width_ft>wall_length(b,w)+1e-5:raise CommandError('Opening does not fit within its wall')
        if op.sill_ft+op.height_ft>w.height_ft+1e-5:raise CommandError('Opening extends above its host wall')
        for a,c in intervals.get(w.id,[]):
            if min(c,op.offset_ft+op.width_ft)-max(a,op.offset_ft)>1e-5:raise CommandError('Openings overlap on their host wall')
        intervals.setdefault(w.id,[]).append((op.offset_ft,op.offset_ft+op.width_ft))
    for r in b.rooms:
        if r.floor_id not in floors:raise CommandError('Room references unknown floor')
        if r.polygon and (len(r.polygon)<3 or not Polygon(r.polygon).is_valid):raise CommandError('Room polygon is invalid')
    for obj in b.objects:
        if obj.floor_id not in floors:raise CommandError('Object references unknown floor')

def recompute_rooms(b: Building, floor_ids: set[str]) -> None:
    """Recover interior faces from wall topology; preserve semantic IDs by overlap."""
    untouched=[r for r in b.rooms if r.floor_id not in floor_ids]
    for floor in sorted(floor_ids):
        walls=[w for w in b.walls if w.floor_id==floor]
        lines=[LineString([(a.x,a.y),(c.x,c.y)]) for w in walls for a,c in [wall_points(b,w)]]
        old=[r for r in b.rooms if r.floor_id==floor]
        if not lines:continue
        faces=list(polygonize(unary_union(lines)))
        buffers=unary_union([line.buffer(w.thickness_ft/2,cap_style=2,join_style=2) for w,line in zip(walls,lines)])
        used=set()
        for face in sorted(faces,key=lambda p:(p.centroid.x,p.centroid.y)):
            interior=face.difference(buffers)
            if interior.is_empty:continue
            if interior.geom_type=='MultiPolygon':interior=max(interior.geoms,key=lambda p:p.area)
            if interior.geom_type!='Polygon' or interior.area<.1:continue
            scores=sorted([(Polygon(r.polygon).intersection(interior).area,r.id,r) for r in old if r.polygon and r.id not in used],key=lambda x:(-x[0],x[1]))
            matches=[v for v in scores if v[0]>.1]
            if matches:
                r=matches[0][2].model_copy(deep=True);used.add(r.id)
                if len(matches)>1 and matches[1][0]>1:r.needs_review=True
            else:
                r=Room(id=uid('room'),floor_id=floor,name='Room',polygon=[],needs_review=True)
            r.polygon=list(interior.exterior.coords)[:-1]
            r.wall_ids=[w.id for w,line in zip(walls,lines) if face.boundary.intersection(line).length>.01]
            untouched.append(r)
        if not faces:
            for r in old:r.needs_review=True;untouched.append(r)
    b.rooms=untouched

def apply_commands(building: Building, commands: list[ModelCommand|dict], actor: str='user') -> Building:
    b=building.model_copy(deep=True);changed=set()
    for raw in commands:
        cmd=raw if isinstance(raw,ModelCommand) else ModelCommand.model_validate(raw)
        k,t,p=cmd.kind,cmd.target_id,cmd.params
        ws={w.id:w for w in b.walls};vs={v.id:v for v in b.vertices};ops={o.id:o for o in b.openings};objs={o.id:o for o in b.objects};rooms={r.id:r for r in b.rooms}
        def require(items):
            if t not in items:raise CommandError(f'Unknown target {t}')
            return items[t]
        def move_vertices(keys,fn):
            for w in b.walls:
                if w.start_id in keys or w.end_id in keys:_wall_allowed(w,actor)
            for key in keys:
                v=vs[key];v.x,v.y=fn(v.x,v.y);changed.add(v.floor_id)
        if k=='move_vertex':
            v=require(vs);dx=float(p['x'])-v.x;dy=float(p['y'])-v.y
            move_vertices({t},lambda x,y:(x+dx,y+dy))
        elif k=='move_wall':
            w=require(ws);dx=float(p.get('dx',0));dy=float(p.get('dy',0))
            move_vertices({w.start_id,w.end_id},lambda x,y:(x+dx,y+dy))
        elif k=='offset_partition':
            w=require(ws);_wall_allowed(w,actor)
            keys={w.start_id,w.end_id};dx=float(p.get('dx',0));dy=float(p.get('dy',0))
            neighbors=[wall for wall in b.walls if wall.id!=w.id and (wall.start_id in keys or wall.end_id in keys)]
            fixed=[wall for wall in neighbors if wall.locked or wall.structural!='nonstructural']
            before=unary_union([LineString([(a.x,a.y),(c.x,c.y)]).buffer(wall.thickness_ft/2,cap_style=2) for wall in fixed for a,c in [wall_points(b,wall)]])
            # Snapshot neighbor orientations before the move
            _AXIS_TOL=0.05
            nbr_orient={}
            for nb in neighbors:
                a,c=wall_points(b,nb)
                if abs(a.y-c.y)<_AXIS_TOL:nbr_orient[nb.id]='h'
                elif abs(a.x-c.x)<_AXIS_TOL:nbr_orient[nb.id]='v'
            opening_positions={}
            for o in b.openings:
                if o.wall_id in {wall.id for wall in neighbors}:
                    host=ws[o.wall_id];a,c=wall_points(b,host);length=wall_length(b,host)
                    opening_positions[o.id]=(a.x+(c.x-a.x)*o.offset_ft/length,a.y+(c.y-a.y)*o.offset_ft/length)
            for key in keys:vs[key].x+=dx;vs[key].y+=dy
            after=unary_union([LineString([(a.x,a.y),(c.x,c.y)]).buffer(wall.thickness_ft/2,cap_style=2) for wall in fixed for a,c in [wall_points(b,wall)]])
            if before.symmetric_difference(after).area>1e-4:raise CommandError('Partition movement changes locked structural geometry')
            # Auto-correct diagonals: if a neighbor was axis-aligned and is now diagonal,
            # propagate the offset to its other endpoint, or decouple the vertex if pinned.
            decoupled={}  # moved_vid -> new_vid (avoid duplicate vertices per shared endpoint)
            for nb in neighbors:
                orient=nbr_orient.get(nb.id)
                if not orient:continue  # was already diagonal, leave it
                if nb.locked or nb.structural!='nonstructural':continue
                a,c=wall_points(b,nb)
                still_aligned=(abs(a.y-c.y)<_AXIS_TOL) if orient=='h' else (abs(a.x-c.x)<_AXIS_TOL)
                if still_aligned:continue  # still axis-aligned, fine
                # Determine which endpoint was NOT moved (the "far" one)
                moved_vid=nb.start_id if nb.start_id in keys else nb.end_id
                far_vid=nb.end_id if moved_vid==nb.start_id else nb.start_id
                # Check if far vertex is pinned to a locked/structural wall
                far_pinned=any(ow for ow in b.walls if ow.id!=nb.id and (ow.start_id==far_vid or ow.end_id==far_vid) and (ow.locked or ow.structural!='nonstructural'))
                if far_pinned:
                    # Decouple: create a new vertex at the original position and redirect
                    # the neighbor, adding a short step wall to bridge the gap.
                    if moved_vid not in decoupled:
                        ox=vs[moved_vid].x-dx;oy=vs[moved_vid].y-dy
                        step_len=math.hypot(dx,dy)
                        if step_len<0.02:
                            for key in keys:vs[key].x-=dx;vs[key].y-=dy
                            raise CommandError(f'Offset too small to decouple vertex on {nb.id}')
                        nv=Vertex(id=uid('v'),floor_id=nb.floor_id,x=ox,y=oy)
                        b.vertices.append(nv);vs[nv.id]=nv
                        sw=BuildingWall(id=uid('wall'),floor_id=nb.floor_id,start_id=nv.id,end_id=moved_vid,
                                        thickness_ft=w.thickness_ft,height_ft=w.height_ft,structural='nonstructural',locked=False)
                        b.walls.append(sw)
                        decoupled[moved_vid]=nv.id
                    new_vid=decoupled[moved_vid]
                    if nb.start_id==moved_vid:nb.start_id=new_vid
                    else:nb.end_id=new_vid
                else:
                    # Propagate: move far vertex to restore alignment
                    if orient=='h':vs[far_vid].y+=dy
                    else:vs[far_vid].x+=dx
            for o in b.openings:
                if o.id in opening_positions:
                    host=ws[o.wall_id];a,c=wall_points(b,host);length=wall_length(b,host);x,y=opening_positions[o.id]
                    if length<.02:raise CommandError('Wall must be longer than 0.02 feet')
                    o.offset_ft=((x-a.x)*(c.x-a.x)+(y-a.y)*(c.y-a.y))/length
                    max_off=length-o.width_ft
                    if max_off<-1e-5:raise CommandError('Partition movement leaves an opening off its wall')
                    o.offset_ft=min(max(float(o.offset_ft),0.0),max(0.0,max_off))
            changed.add(w.floor_id)
        elif k=='update_wall':
            w=require(ws);_wall_allowed(w,actor)
            for key in ['thickness_ft','height_ft']:
                if key in p:setattr(w,key,float(p[key]))
            changed.add(w.floor_id)
        elif k=='unlock_wall':
            if actor!='user':raise CommandError('Agents cannot unlock walls')
            w=require(ws)
            if not str(p.get('reason','')).strip():raise CommandError('Record the review reason before unlocking a wall')
            if p.get('structural') not in ['nonstructural','loadbearing','unknown']:raise CommandError('Choose a structural classification')
            w.structural=p['structural'];w.locked=False
            w.source.method='user-reviewed: '+str(p['reason'])[:200]
        elif k=='create_wall':
            floor=p['floor_id'];coords=[(float(p['x1']),float(p['y1'])),(float(p['x2']),float(p['y2']))];keys=[]
            for x,y in coords:
                v=next((v for v in b.vertices if v.floor_id==floor and math.hypot(v.x-x,v.y-y)<.02),None)
                if v is None:v=Vertex(id=uid('v'),floor_id=floor,x=x,y=y);b.vertices.append(v)
                keys.append(v.id)
            b.walls.append(BuildingWall(id=p.get('id',uid('wall')),floor_id=floor,start_id=keys[0],end_id=keys[1],thickness_ft=p.get('thickness_ft',.5),height_ft=p.get('height_ft',9),structural='nonstructural',locked=False))
            changed.add(floor)
        elif k=='split_wall':
            w=require(ws);_wall_allowed(w,actor);a,c=wall_points(b,w);length=wall_length(b,w);offset=float(p['offset_ft'])
            if not .05<offset<length-.05:raise CommandError('Split point must be inside the wall')
            if any(o.wall_id==w.id and o.offset_ft<offset<o.offset_ft+o.width_ft for o in b.openings):raise CommandError('Cannot split through an opening')
            v=Vertex(id=uid('v'),floor_id=w.floor_id,x=a.x+(c.x-a.x)*offset/length,y=a.y+(c.y-a.y)*offset/length);b.vertices.append(v)
            tail=w.model_copy(deep=True);tail.id=uid('wall');tail.start_id=v.id;w.end_id=v.id;b.walls.append(tail)
            for o in b.openings:
                if o.wall_id==w.id and o.offset_ft>=offset:o.wall_id=tail.id;o.offset_ft-=offset
            changed.add(w.floor_id)
        elif k=='join_walls':
            w=require(ws);other=ws.get(p['other_id'])
            if not other:raise CommandError('Other wall is missing')
            _wall_allowed(w,actor);_wall_allowed(other,actor)
            shared={w.start_id,w.end_id}&{other.start_id,other.end_id}
            if len(shared)!=1:raise CommandError('Walls must share exactly one junction')
            joint=next(iter(shared))
            if sum(joint in (wall.start_id,wall.end_id) for wall in b.walls)!=2:raise CommandError('Cannot remove a branched junction')
            start=vs[next(iter({w.start_id,w.end_id}-{joint}))];end=vs[next(iter({other.start_id,other.end_id}-{joint}))];j=vs[joint]
            if abs((j.x-start.x)*(end.y-start.y)-(j.y-start.y)*(end.x-start.x))>.01:raise CommandError('Join requires collinear walls')
            length=math.hypot(end.x-start.x,end.y-start.y)
            for o in b.openings:
                if o.wall_id in [w.id,other.id]:
                    host=ws[o.wall_id];ha,hc=wall_points(b,host);hl=wall_length(b,host)
                    points=[(ha.x+(hc.x-ha.x)*s/hl,ha.y+(hc.y-ha.y)*s/hl) for s in [o.offset_ft,o.offset_ft+o.width_ft]]
                    o.offset_ft=min(((x-start.x)*(end.x-start.x)+(y-start.y)*(end.y-start.y))/length for x,y in points);o.wall_id=w.id
            w.start_id=start.id;w.end_id=end.id;b.walls.remove(other);changed.add(w.floor_id)
        elif k=='place_opening':
            w=ws.get(p['wall_id'])
            if not w:raise CommandError('Host wall is missing')
            _wall_allowed(w,actor);b.openings.append(Opening(id=p.get('id',uid('opening')),**{key:value for key,value in p.items() if key!='id'}))
        elif k=='update_opening':
            o=require(ops);_wall_allowed(ws[o.wall_id],actor)
            permitted={'offset_ft','width_ft','height_ft','sill_ft','hinge','swing','clear_width_ft'}
            if set(p)-permitted:raise CommandError('Unsupported opening change')
            for key,value in p.items():setattr(o,key,value)
        elif k=='place_object':b.objects.append(PlacedObject(id=p.get('id',uid('object')),**{key:value for key,value in p.items() if key!='id'}))
        elif k=='update_object':
            o=require(objs)
            for key,value in p.items():
                if key not in ['x','y','rotation_deg','width_ft','depth_ft','height_ft','splat']:raise CommandError('Unsupported object change')
                setattr(o,key,value)
        elif k=='set_material':
            if t in ws:ws[t].material=str(p['material'])
            elif t in rooms:rooms[t].floor_material=str(p['material'])
            else:raise CommandError('Choose a wall or room surface')
        elif k=='set_environment':
            b.environment=b.environment.model_copy(update=p)
        elif k=='set_site':
            permitted={'lat','lon','rotation_deg','ground_offset_ft','address'}
            if set(p)-permitted:raise CommandError('Unsupported site change')
            if ('lat' in p)!=('lon' in p):raise CommandError('Set latitude and longitude together')
            b.site=b.site.model_copy(update=p)
        elif k=='rename_room':
            r=require(rooms);r.name=str(p['name']);r.category=str(p.get('category',r.category));r.needs_review=False
        elif k=='apply_room_material_to_type':
            source=require(rooms)
            if not source.type_ref:raise CommandError('This room has no repeated type')
            for r in b.rooms:
                if r.type_ref==source.type_ref:r.floor_material=source.floor_material
        elif k=='rotate_selection':
            angle=math.radians(float(p['angle_deg']));cx=float(p['cx']);cy=float(p['cy']);keys=set()
            for entity in p['ids']:
                if entity in ws:keys.update([ws[entity].start_id,ws[entity].end_id])
                if entity in objs:
                    o=objs[entity];x=o.x-cx;y=o.y-cy;o.x=cx+x*math.cos(angle)-y*math.sin(angle);o.y=cy+x*math.sin(angle)+y*math.cos(angle);o.rotation_deg+=float(p['angle_deg'])
            move_vertices(keys,lambda x,y:(cx+(x-cx)*math.cos(angle)-(y-cy)*math.sin(angle),cy+(x-cx)*math.sin(angle)+(y-cy)*math.cos(angle)))
        elif k=='duplicate':
            o=require(objs).model_copy(deep=True);o.id=uid('object');o.x+=float(p.get('dx',2));o.y+=float(p.get('dy',2));b.objects.append(o)
        elif k=='delete':
            if t in ws:
                _wall_allowed(ws[t],actor);changed.add(ws[t].floor_id);b.walls.remove(ws[t]);b.openings=[o for o in b.openings if o.wall_id!=t]
            elif t in ops:_wall_allowed(ws[ops[t].wall_id],actor);b.openings.remove(ops[t])
            elif t in objs:b.objects.remove(objs[t])
            else:raise CommandError('Select a wall, opening, or object to delete')
        else:raise CommandError(f'Unsupported command: {k}')
    # Pydantic revalidation catches nonfinite coordinates and illegal numeric bounds.
    b=Building.model_validate(b.model_dump())
    validate_building(b)
    if changed:recompute_rooms(b,changed)
    validate_building(b)
    return b
