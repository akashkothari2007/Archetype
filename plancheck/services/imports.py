"""Real source adapters. Unsupported/ambiguous semantics remain explicit review items."""
from __future__ import annotations
import math,os,re,json,time,uuid
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
from shapely.geometry import LineString,Polygon,MultiPoint,Point
from shapely.ops import unary_union,polygonize
from plancheck.core.building import Building,Floor,Vertex,BuildingWall,Opening,Room,ReviewItem,Source,TypeCatalogueEntry,CatalogueFixture
from plancheck.core.schemas import Sheet,Project,SheetGeometry,Model,ModelOrigin,Level,SpaceType,Space
from plancheck.core.settings import get_settings
from plancheck.services.repository import atomic_json
from plancheck.services.wall_collapse import DEFAULT_THICKNESS_FT,CollapsedWall,collapse_wall_segments,snap_point

GAP_BRIDGE_FT = 3.0
MIN_ROOM_AREA_FT2 = 40.0
OPENING_SNAP_FT = 1.5
DOOR_SNAP_FT = 2.5
DOOR_MIN_FT = 1.5
DOOR_MAX_FT = 8.0
GAP_DISAGREE = 0.20
GAP_ALONG_FT = 2.5
STOREY_HEIGHT_FT = 10.0
AREA_MATCH_TOL = 0.08
ASPECT_MATCH_TOL = 0.15
GUESTROOM_AREA_MIN = 140.0
GUESTROOM_AREA_MAX = 520.0
MAX_ROOM_SQFT = 700.0
NEST_ROOM_SQFT = 140.0
TAG_SNAP_FT = 6.0
UNDERSZ_MEDIAN_FRAC = 0.35
EXTRACT_ROLES = frozenset({'floor_plan','unit_plan','schedule'})
SKIP_LABELS = {
    'elevation':'elevation — no plan geometry',
    'section':'section — no plan geometry',
    'detail':'detail — no room data',
    'roof':'roof — no rooms',
    'site':'site — no interior',
    'slab_edge':'slab edge — no rooms',
    'enlarged_plan':'enlarged — gated',
    'unknown':'title did not parse',
}

def merge_buildings(a:Building,b:Building)->Building:
    result=a.model_copy(deep=True)
    seen={f.id for f in result.floors}
    for floor in b.floors:
        if floor.id not in seen:
            result.floors.append(floor);seen.add(floor.id)
    refs={e.type_ref for e in result.type_catalogue}
    for entry in b.type_catalogue:
        if entry.type_ref not in refs:
            result.type_catalogue.append(entry);refs.add(entry.type_ref)
    for name in ['vertices','walls','openings','rooms','objects','review']:getattr(result,name).extend(getattr(b,name))
    return result

def _extend_segment(start,end,extra=GAP_BRIDGE_FT):
    dx=end[0]-start[0];dy=end[1]-start[1];length=math.hypot(dx,dy)
    if length<1e-9:return start,end
    ux,uy=dx/length,dy/length
    return (start[0]-ux*extra,start[1]-uy*extra),(end[0]+ux*extra,end[1]+uy*extra)

def _project_point(px,py,ax,ay,bx,by):
    dx,dy=bx-ax,by-ay;length=math.hypot(dx,dy)
    if length<1e-9:return 0.0,math.hypot(px-ax,py-ay),0.0
    t=((px-ax)*dx+(py-ay)*dy)/(length*length)
    t_clamp=max(0.0,min(1.0,t))
    qx,qy=ax+t_clamp*dx,ay+t_clamp*dy
    return t_clamp*length,math.hypot(px-qx,py-qy),length

def from_segments(segments,floor_id,name,source:Source,thickness=DEFAULT_THICKNESS_FT,room_names=None,collapse=True,fixtures=None,max_room_sqft=None):
    b=Building(floors=[Floor(id=floor_id,name=name)])
    known={};edges=set()
    if collapse:
        collapsed=collapse_wall_segments(segments)
    else:
        collapsed=[]
        for item in segments:
            start,end=item[0],item[1]
            structural=item[2] if len(item)>2 else 'unknown'
            thick=float(item[3]) if len(item)>3 else thickness
            assumed=bool(item[4]) if len(item)>4 else True
            collapsed.append(CollapsedWall(start,end,structural,thick,assumed))
    for wall in collapsed:
        start,end=wall.start,wall.end
        if math.dist(start,end)<.04:continue
        keys=[]
        for p in [start,end]:
            coord=snap_point(p)
            if coord not in known:
                key=f'{floor_id}-v{len(known)}';known[coord]=key;b.vertices.append(Vertex(id=key,floor_id=floor_id,x=coord[0],y=coord[1]))
            keys.append(known[coord])
        if keys[0]==keys[1]:continue
        edge=tuple(sorted(keys))
        if edge in edges:continue
        edges.add(edge)
        wall_source=source.model_copy(update={'assumed':wall.assumed})
        b.walls.append(BuildingWall(id=f'{floor_id}-w{len(b.walls)}',floor_id=floor_id,start_id=keys[0],end_id=keys[1],thickness_ft=wall.thickness_ft or thickness,structural=wall.structural,locked=wall.structural!='nonstructural',confidence=.65,source=wall_source))
    usable=[(wall.start,wall.end) for wall in collapsed if math.dist(wall.start,wall.end)>.04]
    if usable:
        # Doorway gaps break raw polygonize; extend along each segment, then keep the bridged face.
        bridged=[LineString(_extend_segment(start,end)) for start,end in usable]
        faces=[p for p in polygonize(unary_union(bridged)) if p.area>MIN_ROOM_AREA_FT2 and p.is_valid]
        wall_lines=[(w,LineString([(v.x,v.y) for v in [next(v for v in b.vertices if v.id==w.start_id),next(v for v in b.vertices if v.id==w.end_id)]])) for w in b.walls]
        kept=[]
        for p in sorted(faces,key=lambda p:(p.centroid.x,p.centroid.y)):
            if max_room_sqft and p.area>max_room_sqft:
                b.review.append(ReviewItem(id=f'{floor_id}-oversize-{len(b.review)}',kind='geometry',message=f'Rejected a {p.area:.0f} sqft face over {max_room_sqft:g} sqft; not a single room.',document_id=source.document_id,sheet_id=source.sheet_id))
                continue
            kept.append(p)
        for i,p in enumerate(kept):
            area=p.area
            fallback='Unnamed' if room_names else f'Space {i+1}'
            b.rooms.append(Room(id=f'{floor_id}-r{i}',floor_id=floor_id,name=fallback,category='guestroom' if GUESTROOM_AREA_MIN<=area<=GUESTROOM_AREA_MAX else 'other',polygon=list(p.exterior.coords)[:-1],wall_ids=[w.id for w,line in wall_lines if p.boundary.intersection(line).length>.02],confidence=.55,needs_review=True,source=source))
        tag_inside=_apply_room_names(b.rooms,room_names)
        nested=_inherit_nested_rooms(b.rooms,fixtures or [])
        _drop_unlabelled_fragments(b)
        _finalize_room_flags(b.rooms,tag_inside,nested)
        assign_shared_type_refs(b)
    b.review.append(ReviewItem(id=f'{floor_id}-review',kind='geometry',message=f'{len(b.walls)} measured wall segments and {len(b.rooms)} enclosed faces recovered. Review room identity, wall centerlines/thickness, and structural classification before compliance checks.',document_id=source.document_id,sheet_id=source.sheet_id))
    return b

def _wall_lookup(building:Building):
    vertices={v.id:v for v in building.vertices}
    return [(w,vertices[w.start_id],vertices[w.end_id]) for w in building.walls if w.start_id in vertices and w.end_id in vertices]

def _in_bbox(p,bbox,pad=.1):
    x0,y0,x1,y1=bbox
    return x0-pad<=p[0]<=x1+pad and y0-pad<=p[1]<=y1+pad

def _collinear_gap(walls, a, c, offset: float):
    ax, ay, cx, cy = a.x, a.y, c.x, c.y
    length = math.hypot(cx - ax, cy - ay)
    if length < 1e-9:
        return None
    ux, uy = (cx - ax) / length, (cy - ay) / length

    def project(x, y):
        return (x - ax) * ux + (y - ay) * uy

    def dist_line(x, y):
        t = project(x, y)
        return math.hypot(x - (ax + ux * t), y - (ay + uy * t))

    intervals = []
    for _wall, va, vc in walls:
        if dist_line(va.x, va.y) > 0.35 or dist_line(vc.x, vc.y) > 0.35:
            continue
        wx, wy = vc.x - va.x, vc.y - va.y
        wall_len = math.hypot(wx, wy)
        if wall_len < 0.05:
            continue
        if abs((wx / wall_len) * ux + (wy / wall_len) * uy) < 0.95:
            continue
        t0, t1 = project(va.x, va.y), project(vc.x, vc.y)
        lo, hi = min(t0, t1), max(t0, t1)
        intervals.append((lo, hi))
    if not intervals:
        return None
    intervals.sort()
    merged = []
    for lo, hi in intervals:
        if not merged or lo > merged[-1][1] + 0.15:
            merged.append([lo, hi])
        else:
            merged[-1][1] = max(merged[-1][1], hi)
    gaps = []
    for i in range(len(merged) - 1):
        g0, g1 = merged[i][1], merged[i + 1][0]
        gw = g1 - g0
        if DOOR_MIN_FT <= gw <= DOOR_MAX_FT:
            mid = (g0 + g1) / 2
            along = abs(mid - offset)
            if along <= GAP_ALONG_FT:
                gaps.append((along, gw))
    if not gaps:
        return None
    gaps.sort()
    return gaps[0][1]


def attach_openings(building:Building,geom:SheetGeometry,point,source:Source,bbox=None):
    walls=_wall_lookup(building)
    if not walls:return
    occupied={}
    candidates=[]
    for door in geom.doors:
        if bbox and not _in_bbox(door.xy,bbox,pad=1):continue
        candidates.append(('door',door.id,point(door.xy),door.width_ft or 3.0))
    for window in geom.windows:
        mid=((window.a[0]+window.b[0])/2,(window.a[1]+window.b[1])/2)
        if bbox and not _in_bbox(mid,bbox,pad=1):continue
        candidates.append(('window',window.id,point(mid),window.width_ft or 3.0))

    def snap_window(xy):
        best=None
        for wall,a,c in walls:
            offset,dist,length=_project_point(xy[0],xy[1],a.x,a.y,c.x,c.y)
            if dist<=OPENING_SNAP_FT and length>.05 and (best is None or dist<best[0]):
                best=(dist,wall,a,c,offset,length)
        return best

    def snap_door(xy):
        hits=[]
        for wall,a,c in walls:
            offset,dist,length=_project_point(xy[0],xy[1],a.x,a.y,c.x,c.y)
            if dist<=DOOR_SNAP_FT and length>.05:
                hits.append((dist,-length,wall,a,c,offset,length))
        if not hits:return None
        long_hits=[h for h in hits if h[6]>=DOOR_MIN_FT]
        pool=long_hits or hits
        with_gap=[]
        for h in pool:
            dist,_neg,wall,a,c,offset,length=h
            gap=_collinear_gap(walls,a,c,offset)
            if gap and length>=gap+0.02:
                with_gap.append((dist,h,gap))
        if with_gap:
            with_gap.sort(key=lambda item:(item[0], item[1][2].id))
            _dist,h,gap=with_gap[0]
            return h[2],h[3],h[4],h[5],h[6],gap
        pool.sort(key=lambda h:(h[0], h[1], h[2].id))
        h=pool[0]
        return h[2],h[3],h[4],h[5],h[6],None

    dropped=0
    for kind,oid,xy,width in candidates:
        if kind=='door':
            hit=snap_door(xy)
            if not hit:
                dropped+=1
                continue
            wall,_a,_c,offset,length,gap=hit
            path_width=width
            # A door symbol on a continuous wall has no opening to measure.
            # The wall-run gap is ground truth; without one, drop the fragment.
            if gap is None:
                dropped+=1
                continue
            if path_width<=0 or abs(gap-path_width)/max(path_width,1e-9)>GAP_DISAGREE:
                width=gap
            if width<DOOR_MIN_FT or width>DOOR_MAX_FT:
                dropped+=1
                continue
            if width>length-0.02:
                dropped+=1
                continue
        else:
            hit=snap_window(xy)
            if not hit:continue
            _dist,wall,_a,_c,offset,length=hit
            width=min(width,length-0.02)
            if width<1.0 or width>DOOR_MAX_FT:continue
        start=max(0.0,min(length-width,offset-width/2))
        interval=occupied.setdefault(wall.id,[])
        if any(min(start+width,other[1])-max(start,other[0])>1e-5 for other in interval):continue
        interval.append((start,start+width))
        building.openings.append(Opening(id=oid,wall_id=wall.id,kind=kind,offset_ft=start,width_ft=width,height_ft=7 if kind=='door' else 4,sill_ft=0 if kind=='door' else 3,source=source))
    if dropped:
        building.review.append(ReviewItem(id=f'{source.sheet_id or building.floors[0].id}-dropped-doors',kind='extraction',message=f'Dropped {dropped} door fragments outside {DOOR_MIN_FT:g}–{DOOR_MAX_FT:g} ft or without a host wall; counted as extraction_warnings, not openings.',document_id=source.document_id,sheet_id=source.sheet_id))
    if building.openings:
        building.review.append(ReviewItem(id=f'{source.sheet_id or building.floors[0].id}-openings',kind='openings',message=f'{len(building.openings)} openings snapped to the nearest wall. Confirm clear widths and swing before compliance checks.',document_id=source.document_id,sheet_id=source.sheet_id))

def _structural(cls:str):
    return 'loadbearing' if cls=='loadbearing' else 'nonstructural' if cls=='interior' else 'unknown'

def _aspect(polygon)->float:
    if not polygon:return 0.0
    xs=[p[0] for p in polygon];ys=[p[1] for p in polygon]
    width=max(xs)-min(xs);depth=max(ys)-min(ys)
    short=min(width,depth);long=max(width,depth)
    return long/short if short>1e-6 else 0.0

def _is_named(room:Room)->bool:
    name=(room.name or '').strip()
    return bool(name) and name not in {'Unnamed'} and not name.startswith('Space ')

def _is_guestroom_label(text:str)->bool:
    return bool(re.search(r'STUDIO|\bKING\b|\bQQ\b|\bQUEEN\b|SUITE|BEDROOM',text or '',re.I))

def _normalise_name(name:str)->str:
    text=re.sub(r'\s+',' ',(name or '').upper().strip())
    return re.sub(r'\s+\d+$','',text).strip()

def _room_area(room:Room)->float:
    if not room.polygon or len(room.polygon)<3:return 0.0
    try:return float(Polygon(room.polygon).area)
    except Exception:return 0.0

def _unname(room:Room)->None:
    room.name='Unnamed'
    room.category='other' if room.category=='guestroom' else room.category

def _can_apply_label(room:Room,text:str)->bool:
    area=_room_area(room)
    if _is_guestroom_label(text) and area<GUESTROOM_AREA_MIN:return False
    if _category_from_name(text)=='circulation' and area<80:return False
    return True

def _is_unit_parent(room:Room)->bool:
    if room.category=='circulation':return False
    if re.search(r'CORRIDOR|STAIR|LOBBY|SHAFT|ELEVATOR',room.name or '',re.I):return False
    if room.category=='guestroom' or _is_guestroom_label(room.name):return True
    return GUESTROOM_AREA_MIN<=_room_area(room)<=MAX_ROOM_SQFT

def _nested_in_parent(child:Polygon,parent:Polygon,loose=False)->bool:
    if not parent.is_valid or not child.is_valid:return False
    dist=parent.distance(child)
    hull=parent.convex_hull
    if hull.contains(child) or hull.buffer(0.75).contains(child.centroid):return True
    if parent.envelope.buffer(0.5).contains(child.centroid) and dist<=0.6:return True
    if dist<=0.35:return True
    return bool(loose and parent.buffer(8.0).contains(child.centroid))

def _has_fixture(poly:Polygon,points)->bool:
    return any(poly.buffer(0.75).covers(point) or poly.distance(point)<0.75 for point in points)

def _pick_parent(poly:Polygon,area:float,named,loose:bool):
    parent=None;parent_area=None
    for other in named:
        outer=Polygon(other.polygon)
        if not outer.is_valid or outer.area<=area*1.2:continue
        if not _nested_in_parent(poly,outer,loose=loose):continue
        if parent is None or outer.area<parent_area:
            parent=other;parent_area=outer.area
    return parent

def _inherit_nested_rooms(rooms,fixtures)->set[str]:
    nested=set()
    named=[room for room in rooms if _is_named(room) and _is_unit_parent(room)]
    points=[Point(xy) for xy in fixtures or []]
    children={}
    for room in rooms:
        if _is_named(room):continue
        poly=Polygon(room.polygon)
        area=poly.area
        if area>=NEST_ROOM_SQFT or not poly.is_valid:continue
        parent=_pick_parent(poly,area,named,loose=False) or _pick_parent(poly,area,named,loose=True)
        if parent is None:continue
        children.setdefault(parent.id,[]).append(room)
    parents={room.id:room for room in named}
    for parent_id,kids in children.items():
        parent=parents[parent_id]
        scored=[]
        for kid in kids:
            poly=Polygon(kid.polygon)
            scored.append((_has_fixture(poly,points),poly.area,kid))
        baths={kid.id for has_fx,_area,kid in scored if has_fx}
        if not baths:
            baths={max(scored,key=lambda item:item[1])[2].id}
        for has_fx,area,kid in scored:
            if kid.id in baths:
                kid.name=f'{parent.name} Bath';kid.category='bathroom'
            else:
                kid.name=f'{parent.name} Closet';kid.category='storage'
            kid.parent_room_id=parent.id
            nested.add(kid.id)
    return nested

def _drop_unlabelled_fragments(building:Building)->None:
    if not any(_is_named(room) for room in building.rooms):return
    kept=[]
    source=building.rooms[0].source if building.rooms else Source()
    for room in building.rooms:
        area=_room_area(room)
        if room.name=='Unnamed' and area<NEST_ROOM_SQFT:
            building.review.append(ReviewItem(id=f'{room.id}-unlabelled',kind='geometry',message=f'Unlabelled {area:.0f} sqft face was not matched to a room tag.',document_id=source.document_id,sheet_id=source.sheet_id))
            continue
        kept.append(room)
    building.rooms=kept

def _reject_undersized_labels(rooms)->set[str]:
    dropped=set()
    groups={}
    for room in rooms:
        if not _is_named(room):continue
        groups.setdefault(room.name,[]).append(room)
    for name,group in groups.items():
        areas=[_room_area(r) for r in group]
        median=sorted(areas)[len(areas)//2]
        for room,area in zip(group,areas):
            if area<UNDERSZ_MEDIAN_FRAC*median or not _can_apply_label(room,name):
                dropped.add(room.id);_unname(room)
    return dropped

def _apply_room_names(rooms,room_names,snap_ft:float=TAG_SNAP_FT)->set[str]:
    tag_inside=set()
    if not room_names or not rooms:return tag_inside
    claimed=set()
    assigned={}
    for room in rooms:
        polygon=Polygon(room.polygon)
        inside=[]
        for i,(text,xy) in enumerate(room_names):
            point=Point(xy)
            if polygon.covers(point):inside.append((point.distance(polygon.centroid),i,text))
        if not inside:continue
        _dist,index,text=min(inside)
        if not _can_apply_label(room,text):continue
        claimed.add(index);assigned[room.id]=index;tag_inside.add(room.id)
        room.name=text
        category=_category_from_name(text)
        if category!='other' or room.category=='other':room.category=category
    for room_id in _reject_undersized_labels(rooms):
        tag_inside.discard(room_id)
        index=assigned.pop(room_id,None)
        if index is not None:claimed.discard(index)
    for room in rooms:
        if _is_named(room):continue
        polygon=Polygon(room.polygon)
        nearest=[]
        for i,(text,xy) in enumerate(room_names):
            if i in claimed:continue
            dist=polygon.distance(Point(xy))
            if dist<=snap_ft:nearest.append((dist,i,text))
        if not nearest:continue
        _dist,index,text=min(nearest)
        if not _can_apply_label(room,text):continue
        claimed.add(index);room.name=text
        category=_category_from_name(text)
        if category!='other' or room.category=='other':room.category=category
    for room_id in _reject_undersized_labels(rooms):
        tag_inside.discard(room_id)
    return tag_inside

def _plausible_area(category:str,area:float)->bool:
    if category=='guestroom':return GUESTROOM_AREA_MIN<=area<=GUESTROOM_AREA_MAX
    if category=='bathroom':return 20<=area<NEST_ROOM_SQFT
    if category=='storage':return 20<=area<NEST_ROOM_SQFT
    if category=='circulation':return 40<=area<=MAX_ROOM_SQFT
    return MIN_ROOM_AREA_FT2<=area<=MAX_ROOM_SQFT

def _finalize_room_flags(rooms,tag_inside,nested=None)->None:
    nested=nested or set()
    for room in rooms:
        named=_is_named(room)
        area=_room_area(room)
        plausible=_plausible_area(room.category,area) if named else False
        tagged=room.id in tag_inside
        inherited=room.id in nested
        if named and tagged and plausible:
            room.confidence=0.85;room.needs_review=False
        elif named and inherited and plausible:
            room.confidence=0.8;room.needs_review=False
        elif named and plausible and room.category in {'bathroom','storage','guestroom','circulation','service'} and area>=MIN_ROOM_AREA_FT2:
            room.confidence=0.7;room.needs_review=False
        else:
            room.confidence=0.55;room.needs_review=True

def assign_shared_type_refs(building:Building)->None:
    groups={}
    for room in building.rooms:
        if not _is_named(room):continue
        groups.setdefault(_normalise_name(room.name),[]).append(room)
    counts={}
    for key,group in groups.items():
        category=next((r.category for r in group if r.category!='other'),group[0].category)
        type_ref=_type_ref(key,category)
        counts[type_ref]=len(group)
        for room in group:
            room.type_ref=type_ref
            room.instance_count=len(group)
            if room.category=='other':room.category=category
    for entry in building.type_catalogue:
        if entry.type_ref in counts:entry.instance_count=counts[entry.type_ref]

def _category_from_name(name:str)->str:
    text=(name or '').upper()
    if re.search(r'\bBATH\b|\bWC\b|WASHROOM',text):return 'bathroom'
    if re.search(r'CORRIDOR|VESTIBULE|LOBBY',text):return 'circulation'
    if re.search(r'STAIR|SHAFT|\bMECH\b',text):return 'service'
    if re.search(r'CLOSET|STORAGE|LINEN',text):return 'storage'
    if re.search(r'STUDIO|\bKING\b|\bQQ\b|\bQUEEN\b|SUITE|BEDROOM|GUEST',text):return 'guestroom'
    return 'other'

def should_extract_sheet(sheet:Sheet)->bool:
    if sheet.role=='enlarged_plan':return bool(get_settings().use_enlarged)
    return bool(sheet.use and sheet.role in EXTRACT_ROLES)

def skip_label(sheet:Sheet)->str:
    if sheet.role=='enlarged_plan' and not get_settings().use_enlarged:return SKIP_LABELS['enlarged_plan']
    return SKIP_LABELS.get(sheet.role,sheet.reason)

def emit_progress(progress_path:str|None,event:dict)->None:
    if not progress_path:return
    line=(json.dumps(event)+'\n').encode()
    fd=os.open(progress_path,os.O_APPEND|os.O_CREAT|os.O_WRONLY,0o644)
    try:os.write(fd,line)
    finally:os.close(fd)

def sheet_card(sheet:Sheet,geom:SheetGeometry|None=None,extracted=False)->dict:
    title=sheet.title or ''
    return {
        'sheet_id':sheet.sheet_id,'sheet_no':sheet.sheet_no or f'p.{sheet.page}','title':title,'role':sheet.role,
        'page':sheet.page,'use':sheet.use,'extracted':extracted,
        'reason':'' if extracted else skip_label(sheet),
        'walls':len(geom.walls) if geom else 0,'rooms':len(geom.room_tags) if geom else 0,
        'doors':len(geom.doors) if geom else 0,'windows':len(geom.windows) if geom else 0,
        'thumb_url':f'sheets/{sheet.sheet_id}.thumb.png' if extracted else '',
        'raster_url':f'sheets/{sheet.sheet_id}.raster.png' if extracted else '',
        'geometry_url':f'sheets/{sheet.sheet_id}.json' if extracted else '',
        'levels':list(sheet.levels or []),
        'scale_pts_per_ft':sheet.scale_pts_per_ft,
        'size_pt':list(geom.size_pt) if geom else None,
    }

def _type_ref(name:str,category:str)->str:
    slug=re.sub(r'[^a-z0-9]+','_', (name or 'type').lower())
    slug=re.sub(r'_+','_',slug).strip('_') or 'type'
    prefix=category if category!='other' else 'space'
    return f'{prefix}.{slug}'

def _sheet_levels(sheet:Sheet|None)->list[int]:
    values=[]
    for raw in (sheet.levels if sheet else []):
        try:
            level=int(str(raw).strip())
        except (TypeError,ValueError):
            continue
        if level>=1 and level not in values:values.append(level)
    return values

def _floor_name(level:int)->str:
    return 'Ground' if level<=1 else f'Level {level}'

def retarget_storey(building:Building,floor_id:str,name:str,elevation_ft:float)->Building:
    b=building.model_copy(deep=True)
    remap={}
    def take(old:str)->str:
        new=f'{floor_id}:{old}';remap[old]=new;return new
    height=b.floors[0].height_ft if b.floors else 9
    b.floors=[Floor(id=floor_id,name=name,elevation_ft=elevation_ft,height_ft=height)]
    for v in b.vertices:v.id=take(v.id);v.floor_id=floor_id
    for w in b.walls:
        w.id=take(w.id);w.floor_id=floor_id;w.start_id=remap[w.start_id];w.end_id=remap[w.end_id]
    for opening in b.openings:opening.id=take(opening.id);opening.wall_id=remap[opening.wall_id]
    for room in b.rooms:
        room.id=take(room.id);room.floor_id=floor_id;room.wall_ids=[remap[i] for i in room.wall_ids if i in remap]
    for obj in b.objects:obj.id=take(obj.id);obj.floor_id=floor_id
    for item in b.review:item.id=take(item.id)
    b.type_catalogue=[]
    return b

def _convert_walls(geom:SheetGeometry,point,bbox=None,scale=None):
    scale=scale or geom.scale_pts_per_ft
    walls=[]
    for w in geom.walls:
        if bbox and not (_in_bbox(w.a,bbox,pad=1) and _in_bbox(w.b,bbox,pad=1)):continue
        thick=DEFAULT_THICKNESS_FT;assumed=True
        if w.thickness_pt and scale:
            thick=w.thickness_pt/scale;assumed=False
        walls.append((point(w.a),point(w.b),_structural(w.cls),thick,assumed))
    return walls

def _extract_plan(geom:SheetGeometry,sheet:Sheet|None,source:Source,origin=(0.0,0.0),scale=None,bbox=None,floor_id=None,name=None):
    scale=scale or geom.scale_pts_per_ft
    x0,y0=origin
    def point(p,x0=x0,y0=y0,scale=scale):return ((p[0]-x0)/scale,(p[1]-y0)/scale)
    fid=floor_id or f'{geom.sheet_id}-src'
    label=name or (sheet.title if sheet else geom.sheet_id)
    role=sheet.role if sheet else 'floor_plan'
    limit=MAX_ROOM_SQFT if role in {'floor_plan','unit_plan',None} else None
    fixtures=[point(f.xy) for f in geom.fixtures if not bbox or _in_bbox(f.xy,bbox,pad=1)]
    building=from_segments(_convert_walls(geom,point,bbox,scale),fid,label,source,room_names=[(t.text,point(t.xy)) for t in geom.room_tags],collapse=False,fixtures=fixtures,max_room_sqft=limit)
    attach_openings(building,geom,point,source,bbox=bbox)
    return building

def _region_fixtures(geom:SheetGeometry,point,bbox)->list[CatalogueFixture]:
    out=[]
    for fixture in geom.fixtures:
        if bbox and not _in_bbox(fixture.xy,bbox,pad=1):continue
        x,y=point(fixture.xy)
        out.append(CatalogueFixture(kind=fixture.kind,x=x,y=y,asset_id=fixture.id))
    return out

def _catalogue_from_unit_plan(geom:SheetGeometry,sheet:Sheet,source:Source)->Building:
    result=Building();scale=geom.scale_pts_per_ft
    regions=geom.regions or [{'id':geom.sheet_id,'name':sheet.title if sheet else geom.sheet_id,'bbox_pt':[0,0,*geom.size_pt],'kind':'unit'}]
    used_refs=set()
    for region in regions:
        bbox=region['bbox_pt'];x0,y0=bbox[0],bbox[1]
        def point(p,x0=x0,y0=y0,scale=scale):return ((p[0]-x0)/scale,(p[1]-y0)/scale)
        name=region.get('name') or geom.sheet_id
        label=('Reference · ' if region.get('kind')=='unit' else '')+name
        scratch=from_segments(_convert_walls(geom,point,bbox,scale),region['id'],label,source,room_names=[(t.text,point(t.xy)) for t in geom.room_tags],collapse=False,fixtures=[point(f.xy) for f in geom.fixtures if _in_bbox(f.xy,bbox,pad=1)],max_room_sqft=MAX_ROOM_SQFT)
        if not scratch.rooms:
            result.review.extend(scratch.review);continue
        room=max(scratch.rooms,key=lambda r:Polygon(r.polygon).area)
        area=Polygon(room.polygon).area
        category=_category_from_name(name)
        type_ref=_type_ref(name,category)
        suffix=1
        unique=type_ref
        while unique in used_refs:
            suffix+=1;unique=f'{type_ref}_{suffix}'
        used_refs.add(unique)
        result.type_catalogue.append(TypeCatalogueEntry(type_ref=unique,name=name,label=label,category=category,polygon=room.polygon,area_sqft=area,aspect_ratio=_aspect(room.polygon),fixtures=_region_fixtures(geom,point,bbox),source=source))
        result.review.append(ReviewItem(id=region['id']+'-placement',kind='placement',message='Unit-plan reference geometry. This is not a building storey; placement and repeated-instance matching require confirmation.',sheet_id=geom.sheet_id,document_id=geom.doc_id))
        result.review.extend(scratch.review)
    return result

def link_rooms_to_types(building:Building)->None:
    types=building.type_catalogue
    if not types:return
    for room in building.rooms:
        if not room.polygon:continue
        area=Polygon(room.polygon).area
        if area<=0:continue
        ratio=_aspect(room.polygon)
        best=None
        for entry in types:
            if entry.area_sqft<=0:continue
            area_delta=abs(area-entry.area_sqft)/entry.area_sqft
            if area_delta>AREA_MATCH_TOL:continue
            type_ratio=entry.aspect_ratio or _aspect(entry.polygon)
            if ratio<=0 or type_ratio<=0:continue
            aspect_delta=abs(ratio-type_ratio)/type_ratio
            if aspect_delta>ASPECT_MATCH_TOL:continue
            score=(area_delta,aspect_delta)
            if best is None or score<best[0]:best=(score,entry)
        if best:
            room.type_ref=best[1].type_ref
            if room.category=='other':room.category=best[1].category
    counts={}
    for room in building.rooms:
        if room.type_ref:counts[room.type_ref]=counts.get(room.type_ref,0)+1
    for entry in types:entry.instance_count=counts.get(entry.type_ref,0)

def build_from_sheets(project:Project,geometries:list[SheetGeometry])->Building:
    result=Building();sheets={s.sheet_id:s for s in project.sheets}
    use_enlarged=get_settings().use_enlarged
    for geom in geometries:
        sheet=sheets.get(geom.sheet_id)
        if not geom.scale_pts_per_ft:
            result.review.append(ReviewItem(id=f'{geom.sheet_id}-scale',kind='scale',message='Missing drawing scale; calibrate this source before reconstruction.',sheet_id=geom.sheet_id,document_id=geom.doc_id));continue
        role=sheet.role if sheet else None
        source=Source(document_id=geom.doc_id,sheet_id=geom.sheet_id,page=geom.page,method='cad-layer',assumed=True)
        if role=='enlarged_plan':
            if not use_enlarged:
                continue
            result.review.append(ReviewItem(id=f'{geom.sheet_id}-enlarged',kind='placement',message='Enlarged-plan refinement is gated; this sheet does not create a storey.',sheet_id=geom.sheet_id,document_id=geom.doc_id))
            continue
        if role=='unit_plan':
            result=merge_buildings(result,_catalogue_from_unit_plan(geom,sheet or Sheet(sheet_id=geom.sheet_id,doc_id=geom.doc_id,page=geom.page,use=True,reason='unit'),source))
            continue
        if role and role!='floor_plan':
            continue
        levels=_sheet_levels(sheet)
        if not levels:
            result.review.append(ReviewItem(id=f'{geom.sheet_id}-levels',kind='placement',message='Floor-plan sheet has no storey levels; geometry was not assigned to a floor.',sheet_id=geom.sheet_id,document_id=geom.doc_id));continue
        existing={f.id for f in result.floors}
        new_levels=[level for level in levels if f'level-{level}' not in existing]
        if not new_levels:continue
        scratch=_extract_plan(geom,sheet,source)
        for level in new_levels:
            result=merge_buildings(result,retarget_storey(scratch,f'level-{level}',_floor_name(level),(level-1)*STOREY_HEIGHT_FT))
    link_rooms_to_types(result)
    assign_shared_type_refs(result)
    from plancheck.services.reliability import apply_reliability
    apply_reliability(result)
    return result

def import_dxf(path:Path,document_id:str)->Building:
    import ezdxf
    doc=ezdxf.readfile(path);unit=int(doc.header.get('$INSUNITS',0));factor={1:1/12,2:1,4:1/304.8,5:1/30.48,6:1/.3048}.get(unit)
    if factor is None:return Building(review=[ReviewItem(id=document_id+'-units',kind='units',message='DXF units are absent or unsupported. Specify units before creating editable geometry.',document_id=document_id)])
    lines=[];unsupported=0
    def entity(e):
        nonlocal unsupported
        if e.dxftype()=='INSERT':
            for child in e.virtual_entities():entity(child)
            return
        layer=e.dxf.layer.upper()
        if 'WALL' not in layer:unsupported+=1;return
        structural='loadbearing' if 'LOADBEARING' in layer else 'nonstructural' if 'INTR' in layer or 'INTERIOR' in layer else 'unknown'
        pts=[]
        if e.dxftype()=='LINE':pts=[e.dxf.start,e.dxf.end]
        elif e.dxftype()=='LWPOLYLINE':
            if any(abs(p[4])>1e-7 for p in e.get_points()):unsupported+=1;return
            pts=[p[:2] for p in e.get_points()]
            if e.closed and pts:pts.append(pts[0])
        else:unsupported+=1;return
        lines.extend((((a[0]*factor,a[1]*factor),(b[0]*factor,b[1]*factor),structural) for a,b in zip(pts,pts[1:])))
    for e in doc.modelspace():entity(e)
    result=from_segments(lines,document_id+'-floor',path.stem,Source(document_id=document_id,method='dxf-modelspace',assumed=True))
    result.review.append(ReviewItem(id=document_id+'-unsupported',kind='entities',message=f'{unsupported} non-wall or unsupported DXF entities retained in the source file. Curves and external references require review.',document_id=document_id));return result

def import_ifc(path:Path,document_id:str)->Building:
    import ifcopenshell,ifcopenshell.geom,ifcopenshell.util.element
    doc=ifcopenshell.open(str(path));settings=ifcopenshell.geom.settings();settings.set(settings.USE_WORLD_COORDS,True);groups={};reviews=[]
    for wall in doc.by_type('IfcWall'):
        try:
            shape=ifcopenshell.geom.create_shape(settings,wall);vertices=shape.geometry.verts;points=[(vertices[i]/.3048,vertices[i+1]/.3048) for i in range(0,len(vertices),3)];hull=MultiPoint(points).convex_hull;rect=hull.minimum_rotated_rectangle
            if rect.geom_type!='Polygon' or rect.area<.01:continue
            if hull.area/rect.area<.95:raise ValueError('Nonrectangular wall remains reference geometry')
            corners=list(rect.exterior.coords)[:-1];lengths=[math.dist(corners[i],corners[(i+1)%4]) for i in range(4)];idx=lengths.index(min(lengths));start=tuple((corners[idx][j]+corners[(idx+1)%4][j])/2 for j in [0,1]);end=tuple((corners[(idx+2)%4][j]+corners[(idx+3)%4][j])/2 for j in [0,1]);storey=ifcopenshell.util.element.get_container(wall);fid=document_id+'-'+(storey.GlobalId if storey else 'floor');name=storey.Name if storey else 'Imported floor';props=ifcopenshell.util.element.get_psets(wall);lb=props.get('Pset_WallCommon',{}).get('LoadBearing');struct='loadbearing' if lb is True else 'nonstructural' if lb is False else 'unknown';groups.setdefault(fid,{'name':name,'lines':[]})['lines'].append((start,end,struct))
        except Exception as exc:reviews.append(ReviewItem(id=document_id+'-'+wall.GlobalId,kind='ifc_geometry',message=str(exc),document_id=document_id))
    result=Building()
    for fid,g in groups.items():result=merge_buildings(result,from_segments(g['lines'],fid,g['name'],Source(document_id=document_id,method='ifc-wall-footprint',assumed=True)))
    result.review.extend(reviews);result.review.append(ReviewItem(id=document_id+'-ifc-review',kind='ifc',message='Storeys and straight wall axes imported from real IFC geometry. Complex shapes, thickness reconciliation, and opening-host semantics require review against the retained IFC source.',document_id=document_id));return result

def import_cad(path:Path,document_id:str)->Building:return import_dxf(path,document_id) if path.suffix.lower()=='.dxf' else import_ifc(path,document_id)

def extract_standards(document:dict,progress_path:str|None=None):
    from plancheck.engines.extract_rules import run_real
    emit_progress(progress_path,{'kind':'phase','phase':'standards','message':'Extracting rules from standards','progress':0.2})
    started=time.perf_counter()
    project=Project(project_id='import',name='Import',created_at='')
    rules=run_real(project,[Path(document['absolute_path'])])
    payload=[dict(r.model_dump(),source_doc=document['id'],source_filename=document['name']) for r in rules.rules]
    print(f"[import] standards {time.perf_counter()-started:.2f}s rules={len(payload)}",flush=True)
    emit_progress(progress_path,{'kind':'phase','phase':'standards','message':f'Extracted {len(payload)} rules','progress':0.9,'rules':len(payload)})
    return payload

def import_document(document:dict,project_dir:str,progress_path:str|None=None)->dict:
    path=Path(document['absolute_path']);did=document['id'];root=Path(project_dir)
    if path.suffix.lower() in ['.dxf','.ifc']:
        started=time.perf_counter()
        building=import_cad(path,did)
        print(f"[import] cad {path.name} {time.perf_counter()-started:.2f}s",flush=True)
        return {'building':building.model_dump(mode='json'),'sheets':[],'timings':{'total':time.perf_counter()-started}}
    from plancheck.engines.classify import classify_document
    from plancheck.services.pdf_extract import extract_cached,file_digest
    total_t=time.perf_counter()
    emit_progress(progress_path,{'kind':'phase','phase':'classify','message':f'Classifying pages in {path.name}','progress':0.02})
    classify_t=time.perf_counter()
    _document,sheets=classify_document(path,did)
    print(f"[import] classify {path.name} {time.perf_counter()-classify_t:.2f}s ({len(sheets)} pages)",flush=True)
    selected=[s for s in sheets if should_extract_sheet(s)]
    cards=[sheet_card(s,extracted=False) for s in sheets]
    emit_progress(progress_path,{'kind':'classified','sheets':cards,'progress':0.15,'message':f'Classifying {len(sheets)} pages'})
    atomic_json(root/'sources'/did/'sheets.json',{'sheets':[s.model_dump() for s in sheets]})
    digest=file_digest(path)
    (root/'sheets').mkdir(parents=True,exist_ok=True)
    geometries:dict[str,SheetGeometry]={}
    workers=max(1,min(8,os.cpu_count() or 4,len(selected) or 1))

    def extract_one(sheet:Sheet):
        raster=root/'sheets'/f'{sheet.sheet_id}.raster.png'
        started=time.perf_counter()
        geom,cached=extract_cached(sheet,path,raster,digest)
        atomic_json(root/'sheets'/f'{sheet.sheet_id}.json',geom.model_dump(mode='json'))
        print(f"[import] extract p.{sheet.page} {sheet.sheet_no or ''} {time.perf_counter()-started:.2f}s walls={len(geom.walls)} cached={cached}",flush=True)
        return sheet,geom,cached

    extract_t=time.perf_counter()
    if selected:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures={pool.submit(extract_one,sheet):sheet for sheet in selected}
            done=0
            for future in as_completed(futures):
                sheet,geom,_cached=future.result()
                geometries[sheet.sheet_id]=geom
                done+=1
                frac=0.15+0.65*done/max(1,len(selected))
                label=f"{sheet.sheet_no or f'p.{sheet.page}'} · {sheet.title or sheet.role}"
                emit_progress(progress_path,{'kind':'sheet','sheet':sheet_card(sheet,geom,extracted=True),'progress':frac,'message':f'Reading {label}'})
    print(f"[import] extract {path.name} {time.perf_counter()-extract_t:.2f}s pages={len(selected)}",flush=True)
    emit_progress(progress_path,{'kind':'phase','phase':'build','message':'Building rooms and openings','progress':0.82})
    build_t=time.perf_counter()
    project=Project(project_id='import',name=path.stem,created_at='',sheets=sheets)
    ordered=[geometries[s.sheet_id] for s in selected if s.sheet_id in geometries]
    result=build_from_sheets(project,ordered)
    if not selected:result.review.append(ReviewItem(id=did+'-reference',kind='reference',message='No recognized, scaled floor-plan sheet. Source PDF retained for review; no building geometry was invented.',document_id=did))
    print(f"[import] build {path.name} {time.perf_counter()-build_t:.2f}s walls={len(result.walls)} rooms={len(result.rooms)}",flush=True)
    rooms_by_sheet={}
    for room in result.rooms:
        rooms_by_sheet[room.source.sheet_id]=rooms_by_sheet.get(room.source.sheet_id,0)+1
    final_cards=[]
    for sheet in sheets:
        geom=geometries.get(sheet.sheet_id)
        card=sheet_card(sheet,geom,extracted=sheet.sheet_id in geometries)
        if sheet.sheet_id in rooms_by_sheet:card['rooms']=rooms_by_sheet[sheet.sheet_id]
        final_cards.append(card)
    elapsed=time.perf_counter()-total_t
    print(f"[import] total {path.name} {elapsed:.2f}s",flush=True)
    return {'building':result.model_dump(mode='json'),'sheets':final_cards,'timings':{'total':elapsed,'pages':len(sheets),'extracted':len(selected)}}
