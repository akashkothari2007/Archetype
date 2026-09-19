"""Real source adapters. Unsupported/ambiguous semantics remain explicit review items."""
from __future__ import annotations
import math,re,json,uuid
from pathlib import Path
from shapely.geometry import LineString,Polygon,MultiPoint,Point
from shapely.ops import unary_union,polygonize
from plancheck.core.building import Building,Floor,Vertex,BuildingWall,Opening,Room,ReviewItem,Source,TypeCatalogueEntry,CatalogueFixture
from plancheck.core.schemas import Sheet,Project,SheetGeometry,Model,ModelOrigin,Level,SpaceType,Space
from plancheck.core.settings import get_settings
from plancheck.services.repository import atomic_json

GAP_BRIDGE_FT = 3.0
MIN_ROOM_AREA_FT2 = 40.0
OPENING_SNAP_FT = 1.5
STOREY_HEIGHT_FT = 10.0
AREA_MATCH_TOL = 0.08
ASPECT_MATCH_TOL = 0.15
GUESTROOM_AREA_MIN = 140.0
GUESTROOM_AREA_MAX = 520.0

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

def from_segments(segments,floor_id,name,source:Source,thickness=.35,room_names=None):
    b=Building(floors=[Floor(id=floor_id,name=name)])
    known={};edges=set()
    for start,end,structural in segments:
        if math.dist(start,end)<.04:continue
        keys=[]
        for p in [start,end]:
            coord=(round(p[0],4),round(p[1],4))
            if coord not in known:
                key=f'{floor_id}-v{len(known)}';known[coord]=key;b.vertices.append(Vertex(id=key,floor_id=floor_id,x=coord[0],y=coord[1]))
            keys.append(known[coord])
        edge=tuple(sorted(keys))
        if edge in edges:continue
        edges.add(edge);b.walls.append(BuildingWall(id=f'{floor_id}-w{len(b.walls)}',floor_id=floor_id,start_id=keys[0],end_id=keys[1],thickness_ft=thickness,structural=structural,locked=structural!='nonstructural',confidence=.65,source=source))
    usable=[(start,end) for start,end,_ in segments if math.dist(start,end)>.04]
    if usable:
        # Doorway gaps break raw polygonize; extend along each segment, then keep the bridged face.
        bridged=[LineString(_extend_segment(start,end)) for start,end in usable]
        faces=[p for p in polygonize(unary_union(bridged)) if p.area>MIN_ROOM_AREA_FT2 and p.is_valid]
        wall_lines=[(w,LineString([(v.x,v.y) for v in [next(v for v in b.vertices if v.id==w.start_id),next(v for v in b.vertices if v.id==w.end_id)]])) for w in b.walls]
        for i,p in enumerate(sorted(faces,key=lambda p:(p.centroid.x,p.centroid.y))):
            label=None
            for text,xy in room_names or []:
                if p.covers(Point(xy)) and re.search(r'ROOM|BED|STUDIO|BATH|KITCHEN|CORRIDOR|LIVING|OFFICE|\b\d{3}\b',text,re.I):label=text;break
            area=p.area
            category='bathroom' if label and re.search('BATH|WASHROOM',label,re.I) else 'circulation' if label and 'CORRIDOR' in label.upper() else 'guestroom' if (label and re.search('STUDIO|BEDROOM',label,re.I)) or GUESTROOM_AREA_MIN<=area<=GUESTROOM_AREA_MAX else 'other'
            b.rooms.append(Room(id=f'{floor_id}-r{i}',floor_id=floor_id,name=label or f'Space {i+1}',category=category,polygon=list(p.exterior.coords)[:-1],wall_ids=[w.id for w,line in wall_lines if p.boundary.intersection(line).length>.02],confidence=.55,needs_review=True,source=source))
    b.review.append(ReviewItem(id=f'{floor_id}-review',kind='geometry',message=f'{len(b.walls)} measured wall segments and {len(b.rooms)} enclosed faces recovered. Review room identity, wall centerlines/thickness, and structural classification before compliance checks.',document_id=source.document_id,sheet_id=source.sheet_id))
    return b

def _wall_lookup(building:Building):
    vertices={v.id:v for v in building.vertices}
    return [(w,vertices[w.start_id],vertices[w.end_id]) for w in building.walls if w.start_id in vertices and w.end_id in vertices]

def _in_bbox(p,bbox,pad=.1):
    x0,y0,x1,y1=bbox
    return x0-pad<=p[0]<=x1+pad and y0-pad<=p[1]<=y1+pad

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
    def snap(xy):
        best=None
        for wall,a,c in walls:
            offset,dist,length=_project_point(xy[0],xy[1],a.x,a.y,c.x,c.y)
            if dist<=OPENING_SNAP_FT and length>.05 and (best is None or dist<best[0]):
                best=(dist,wall,a,c,offset,length)
        return best
    for kind,oid,xy,width in candidates:
        hit=snap(xy)
        if not hit:continue
        _dist,wall,_a,_c,offset,length=hit
        width=min(max(width,0.5),length-0.02)
        if width<=0.2:continue
        start=max(0.0,min(length-width,offset-width/2))
        interval=occupied.setdefault(wall.id,[])
        if any(min(start+width,other[1])-max(start,other[0])>1e-5 for other in interval):continue
        interval.append((start,start+width))
        building.openings.append(Opening(id=oid,wall_id=wall.id,kind=kind,offset_ft=start,width_ft=width,height_ft=7 if kind=='door' else 4,sill_ft=0 if kind=='door' else 3,source=source))
    if building.openings:
        building.review.append(ReviewItem(id=f'{source.sheet_id or building.floors[0].id}-openings',kind='openings',message=f'{len(building.openings)} openings snapped to the nearest wall within {OPENING_SNAP_FT:g} ft. Confirm clear widths and swing before compliance checks.',document_id=source.document_id,sheet_id=source.sheet_id))

def _structural(cls:str):
    return 'loadbearing' if cls=='loadbearing' else 'nonstructural' if cls=='interior' else 'unknown'

def _aspect(polygon)->float:
    if not polygon:return 0.0
    xs=[p[0] for p in polygon];ys=[p[1] for p in polygon]
    width=max(xs)-min(xs);depth=max(ys)-min(ys)
    short=min(width,depth);long=max(width,depth)
    return long/short if short>1e-6 else 0.0

def _category_from_name(name:str)->str:
    text=name or ''
    if re.search(r'BATH|WASHROOM',text,re.I):return 'bathroom'
    if re.search(r'CORRIDOR',text,re.I):return 'circulation'
    if re.search(r'STUDIO|BEDROOM|KING|QUEEN|SUITE|GUEST',text,re.I):return 'guestroom'
    return 'other'

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

def _convert_walls(geom:SheetGeometry,point,bbox=None):
    walls=[]
    for w in geom.walls:
        if bbox and not (_in_bbox(w.a,bbox,pad=1) and _in_bbox(w.b,bbox,pad=1)):continue
        walls.append((point(w.a),point(w.b),_structural(w.cls)))
    return walls

def _extract_plan(geom:SheetGeometry,sheet:Sheet|None,source:Source,origin=(0.0,0.0),scale=None,bbox=None,floor_id=None,name=None):
    scale=scale or geom.scale_pts_per_ft
    x0,y0=origin
    def point(p,x0=x0,y0=y0,scale=scale):return ((p[0]-x0)/scale,(p[1]-y0)/scale)
    fid=floor_id or f'{geom.sheet_id}-src'
    label=name or (sheet.title if sheet else geom.sheet_id)
    building=from_segments(_convert_walls(geom,point,bbox),fid,label,source,room_names=[(t.text,point(t.xy)) for t in geom.room_tags])
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
        scratch=from_segments(_convert_walls(geom,point,bbox),region['id'],label,source,room_names=[(t.text,point(t.xy)) for t in geom.room_tags])
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

def extract_standards(document:dict):
    from plancheck.engines.extract_rules import run_real
    project=Project(project_id='import',name='Import',created_at='')
    rules=run_real(project,[Path(document['absolute_path'])]);return [dict(r.model_dump(),source_doc=document['id'],source_filename=document['name']) for r in rules.rules]

def import_document(document:dict,project_dir:str)->dict:
    path=Path(document['absolute_path']);did=document['id']
    if path.suffix.lower() in ['.dxf','.ifc']:return import_cad(path,did).model_dump(mode='json')
    import pymupdf
    from plancheck.engines.classify import title_block_text,parse_title,parse_sheet_no,assign_role,parse_levels,sheet_title_field
    from plancheck.core.scale import find_scale
    from plancheck.services.pdf_extract import extract
    from plancheck.core.settings import get_settings
    sheets=[]
    with pymupdf.open(path) as doc:
        for index,page in enumerate(doc):
            text=page.get_text();block=title_block_text(page);title=parse_title(block,text);no=parse_sheet_no(block) or parse_sheet_no(text);st,scale=find_scale(block)
            if not scale:st,scale=find_scale(text)
            role=assign_role(no,title,scale)
            use=role in ['floor_plan','unit_plan'] or (role=='enlarged_plan' and get_settings().use_enlarged)
            sheets.append(Sheet(sheet_id=f'{did}-p{index+1:03}',doc_id=did,page=index+1,sheet_no=no,title=title,role=role,scale_text=st,scale_pts_per_ft=scale,levels=parse_levels(sheet_title_field(block)) or parse_levels(title),use=use,reason='Selected plan geometry' if use else 'Retained source reference'))
    selected=[s for s in sheets if s.use][:10];project=Project(project_id='import',name=path.stem,created_at='',sheets=sheets)
    atomic_json(Path(project_dir)/'sources'/did/'sheets.json',{'sheets':[s.model_dump() for s in sheets]})
    geometries=[]
    for sheet in selected:
        geom=extract(sheet,path,Path(project_dir)/'sheets'/f'{sheet.sheet_id}.raster.png');atomic_json(Path(project_dir)/'sheets'/f'{sheet.sheet_id}.json',geom.model_dump(mode='json'));geometries.append(geom)
    result=build_from_sheets(project,geometries)
    if not selected:result.review.append(ReviewItem(id=did+'-reference',kind='reference',message='No recognized, scaled floor-plan sheet. Source PDF retained for review; no building geometry was invented.',document_id=did))
    return result.model_dump(mode='json')
