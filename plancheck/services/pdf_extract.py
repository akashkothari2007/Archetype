"""Measured CAD PDF paths normalized to displayed sheet coordinates, y up."""
from pathlib import Path
from collections import Counter
import hashlib,math,re,shutil
import pymupdf
from plancheck.core.schemas import Sheet,SheetGeometry,Wall,Door,Window,Fixture,RoomTag,RasterRef,Dimension,GridBubble,MepEquipment,MepSheetData,SheetGrid
from plancheck.core.layers import bucket_for,normalise
from plancheck.core.settings import get_settings

EXTRACTOR_VERSION='7'
ROOM_TAG_REJECT=re.compile(r"""[\d\[\]'"]""")
STACK_X_PT=12.0
STACK_Y_PT=18.0
DOOR_CLUSTER_PAD_FT=0.25
DOOR_CLUSTER_CELL_FT=6.0
DOOR_WIDTH_MIN_FT=1.5
DOOR_WIDTH_MAX_FT=8.0

def cache_root()->Path:
 return get_settings().data_dir.parent/'cache'

def file_digest(path:Path)->str:
 hasher=hashlib.sha256()
 with path.open('rb') as handle:
  for chunk in iter(lambda:handle.read(1024*1024),b''):hasher.update(chunk)
 return hasher.hexdigest()

def cache_paths(digest:str,page:int):
 root=cache_root()/digest/EXTRACTOR_VERSION
 return root/f'{page}.json',root/f'{page}.raster.png',root/f'{page}.thumb.png'

def thumb_path(raster:Path)->Path:
 name=raster.name
 if name.endswith('.raster.png'):return raster.with_name(name.replace('.raster.png','.thumb.png'))
 return raster.with_name(raster.stem+'.thumb.png')

def write_wall_thumb(geom:SheetGeometry,dest:Path,px:int=220):
 dest.parent.mkdir(parents=True,exist_ok=True)
 width,height=geom.size_pt or [100,100]
 scale=px/max(width,height,1)
 page_w=max(8.0,width*scale);page_h=max(8.0,height*scale)
 doc=pymupdf.open();page=doc.new_page(width=page_w,height=page_h)
 shape=page.new_shape()
 for wall in geom.walls:
  shape.draw_line(pymupdf.Point(wall.a[0]*scale,page_h-wall.a[1]*scale),pymupdf.Point(wall.b[0]*scale,page_h-wall.b[1]*scale))
 shape.finish(color=(0.16,0.17,0.16),width=0.45)
 shape.commit()
 pix=page.get_pixmap(alpha=False);pix.save(dest);doc.close()

def _point_in_bbox(xy,bbox)->bool:
 return bbox[0]<=xy[0]<=bbox[2] and bbox[1]<=xy[1]<=bbox[3]

def is_fallback_room_tag(text:str)->bool:
 cleaned=' '.join(text.split())
 return len(cleaned)>=3 and cleaned==cleaned.upper() and re.fullmatch(r'[A-Z]+(?: [A-Z]+)*',cleaned) is not None and not ROOM_TAG_REJECT.search(cleaned)

def _bbox_overlap(a,b)->bool:
 return a[0]<b[2] and b[0]<a[2] and a[1]<b[3] and b[1]<a[3]

def _expand_bbox(bbox,pad):
 return [bbox[0]-pad,bbox[1]-pad,bbox[2]+pad,bbox[3]+pad]

HINGE_TOL_FT=0.3

def _analyze_door_swing(segments,curves,scale):
 """Determine hinge point and arc midpoint from a door cluster's geometry.

 The hinge point is the leaf endpoint that coincides (within HINGE_TOL_FT)
 with an arc endpoint. The arc midpoint is the cubic Bezier at t=0.5 of the
 middle curve segment — used later to determine swing side via cross product.

 Returns (hinge_pt, arc_mid_pt) in sheet-space, or (None, None) if no arc.
 """
 if not curves or not segments:return None,None
 # Leaf: longest straight segment in the cluster
 leaf=max(segments,key=lambda s:math.dist(s[0],s[1]),default=None)
 if not leaf or math.dist(leaf[0],leaf[1])<1e-3:return None,None
 # Collect all arc endpoints
 arc_eps=[]
 for c in curves:arc_eps.append(c['start']);arc_eps.append(c['end'])
 if not arc_eps:return None,None
 tol=HINGE_TOL_FT*scale if scale else HINGE_TOL_FT
 d_a=min(math.dist(leaf[0],ep) for ep in arc_eps)
 d_b=min(math.dist(leaf[1],ep) for ep in arc_eps)
 if d_a<=tol and d_a<=d_b:hinge_pt=list(leaf[0])
 elif d_b<=tol:hinge_pt=list(leaf[1])
 else:return None,None
 # Arc midpoint: cubic Bezier at t=0.5 of the middle curve
 c=curves[len(curves)//2]
 p0,p1,p2,p3=c['start'],c['ctrl1'],c['ctrl2'],c['end']
 arc_mid_pt=[0.125*p0[0]+0.375*p1[0]+0.375*p2[0]+0.125*p3[0],0.125*p0[1]+0.375*p1[1]+0.375*p2[1]+0.125*p3[1]]
 return hinge_pt,arc_mid_pt

def cluster_door_fragments(fragments:list[dict],scale:float,pad_ft:float=DOOR_CLUSTER_PAD_FT,cell_ft:float=DOOR_CLUSTER_CELL_FT)->tuple[list[dict],int]:
 """Union-find cluster of DOOR-layer path bboxes, then measure the leaf from the union.

 A door is drawn as many fragments (leaf, swing arc, jamb ticks). No single path
 is the leaf width — on A.202 the longest door segment is 0.56 ft. The clustered
 bbox of leaf plus a 90-degree swing is roughly square, so min(width, height) is
 the leaf. Spatial-hash cells of ~6 ft keep 2k paths off a quadratic scan.
 """
 n=len(fragments)
 if not n:return [],0
 pad=(pad_ft*scale) if scale else pad_ft
 cell=(cell_ft*scale) if scale else cell_ft
 if cell<=0:cell=1.0
 expanded=[_expand_bbox(frag['bbox'],pad) for frag in fragments]
 parent=list(range(n));rank=[0]*n
 def find(i):
  while parent[i]!=i:parent[i]=parent[parent[i]];i=parent[i]
  return i
 def union(i,j):
  a,b=find(i),find(j)
  if a==b:return
  if rank[a]<rank[b]:parent[a]=b
  elif rank[a]>rank[b]:parent[b]=a
  else:parent[b]=a;rank[a]+=1
 buckets={}
 for i,box in enumerate(expanded):
  x0=math.floor(box[0]/cell);x1=math.floor(box[2]/cell)
  y0=math.floor(box[1]/cell);y1=math.floor(box[3]/cell)
  for gx in range(x0,x1+1):
   for gy in range(y0,y1+1):
    buckets.setdefault((gx,gy),[]).append(i)
 seen=set()
 for idxs in buckets.values():
  m=len(idxs)
  for a in range(m):
   ia=idxs[a]
   for b in range(a+1,m):
    ib=idxs[b]
    pair=(ia,ib) if ia<ib else (ib,ia)
    if pair in seen:continue
    seen.add(pair)
    if _bbox_overlap(expanded[ia],expanded[ib]):union(ia,ib)
 groups={}
 for i in range(n):groups.setdefault(find(i),[]).append(fragments[i])
 doors=[];rejected=0
 for group in groups.values():
  xs=[c for frag in group for c in (frag['bbox'][0],frag['bbox'][2])]
  ys=[c for frag in group for c in (frag['bbox'][1],frag['bbox'][3])]
  bbox=[min(xs),min(ys),max(xs),max(ys)]
  width_pt=min(bbox[2]-bbox[0],bbox[3]-bbox[1])
  width_ft=width_pt/scale if scale else 0.0
  if width_ft<DOOR_WIDTH_MIN_FT or width_ft>DOOR_WIDTH_MAX_FT:
   rejected+=1
   continue
  group_segs=[seg for frag in group for seg in frag.get('segments',[])]
  group_curves=[c for frag in group for c in frag.get('curves',[])]
  hinge_pt,arc_mid_pt=_analyze_door_swing(group_segs,group_curves,scale)
  doors.append({'xy':[(bbox[0]+bbox[2])/2,(bbox[1]+bbox[3])/2],'bbox':bbox,'width_pt':width_pt,'width_ft':width_ft,'hinge_pt':hinge_pt,'arc_mid_pt':arc_mid_pt})
 return doors,rejected

def merge_stacked_room_tags(items:list[dict],x_tol:float=STACK_X_PT,y_gap:float=STACK_Y_PT)->list[dict]:
 remaining=sorted(items,key=lambda it:(-it['xy'][1],it['xy'][0]))
 clusters=[]
 for item in remaining:
  for cluster in clusters:
   last=cluster[-1]
   if abs(last['xy'][0]-item['xy'][0])<=x_tol and 0<=last['xy'][1]-item['xy'][1]<y_gap:
    cluster.append(item);break
  else:clusters.append([item])
 out=[]
 for cluster in clusters:
  texts=[c['text'] for c in cluster];xs=[c['xy'][0] for c in cluster];ys=[c['xy'][1] for c in cluster]
  out.append({'text':' '.join(texts),'xy':[sum(xs)/len(xs),sum(ys)/len(ys)],'lines':texts})
 return out

def build_room_tags(items:list[dict],tag_boxes:list[list[float]])->list[RoomTag]:
 if tag_boxes:
  chosen=[it for it in items if any(_point_in_bbox(it['xy'],box) for box in tag_boxes)]
 else:
  chosen=[it for it in items if is_fallback_room_tag(it['text'])]
 tags=[]
 for item in merge_stacked_room_tags(chosen):
  text=item['text']
  tags.append(RoomTag(text=text,xy=item['xy'],lines=item['lines'],number=text if re.fullmatch(r'\d{3,4}',text) else None))
 return tags

def extract(sheet:Sheet,path:Path,raster:Path)->SheetGeometry:
 with pymupdf.open(path) as doc:
  page=doc[sheet.page-1];height=page.rect.height;scale=sheet.scale_pts_per_ft or 0
  def xy(p):
   q=pymupdf.Point(p)*page.rotation_matrix
   return [float(q.x),float(height-q.y)]
  def rect(r):
   q=pymupdf.Rect(r)*page.rotation_matrix
   return [float(q.x0),float(height-q.y1),float(q.x1),float(height-q.y0)]
  geom=SheetGeometry(sheet_id=sheet.sheet_id,page=sheet.page,doc_id=sheet.doc_id,size_pt=[page.rect.width,height],scale_pts_per_ft=scale,source_rotation=page.rotation)
  drawings=page.get_drawings();counts=Counter();frames=[];tag_boxes=[];text_items=[];door_frags=[]
  for i,d in enumerate(drawings):
   layer=normalise(d.get('layer'));bucket=bucket_for(layer);counts[bucket]+=1;geom.layer_map[layer]=bucket
   rr=rect(d['rect']);w=rr[2]-rr[0];h=rr[3]-rr[1]
   if bucket=='unmapped' and w>page.rect.width*.1 and h>height*.2 and w*h<page.rect.width*height*.3:frames.append(rr)
   segments=[]
   for item in d['items']:
    if item[0]=='l':segments.append((xy(item[1]),xy(item[2])))
    elif item[0]=='re':
     r=item[1];pts=[xy(r.tl),xy(r.tr),xy(r.br),xy(r.bl)];segments.extend(zip(pts,pts[1:]+pts[:1]))
    elif item[0]=='qu':
     q=item[1];pts=[xy(q.ul),xy(q.ur),xy(q.lr),xy(q.ll)];segments.extend(zip(pts,pts[1:]+pts[:1]))
   if bucket=='wall':
    cls='loadbearing' if 'LOADBEARING' in layer.upper() else 'interior' if 'INTR' in layer.upper() else 'unknown'
    for j,(a,b) in enumerate(segments):
     length=math.dist(a,b)
     if length>.05:geom.walls.append(Wall(id=f'{sheet.sheet_id}-w{i}-{j}',a=a,b=b,cls=cls,layer=layer,thickness_pt=d.get('width'),len_ft=length/scale if scale else 0))
   elif bucket=='door':
    curves=[]
    for item in d['items']:
     if item[0]=='c':curves.append({'start':xy(item[1]),'end':xy(item[4]),'ctrl1':xy(item[2]),'ctrl2':xy(item[3])})
    door_frags.append({'bbox':rr,'segments':segments,'curves':curves})
   elif bucket=='window':
    for j,(a,b) in enumerate(segments):
     if math.dist(a,b)>1:geom.windows.append(Window(id=f'{sheet.sheet_id}-win{i}-{j}',a=a,b=b,width_ft=math.dist(a,b)/scale if scale else 0))
   elif bucket=='fixture':geom.fixtures.append(Fixture(id=f'{sheet.sheet_id}-f{i}',xy=[(rr[0]+rr[2])/2,(rr[1]+rr[3])/2],bbox=rr,layer=layer))
   elif bucket=='room_tag':
    w,h=rr[2]-rr[0],rr[3]-rr[1]
    if w>=8 and h>=3:tag_boxes.append([rr[0]-STACK_X_PT,rr[1]-8.0,rr[2]+STACK_X_PT,rr[3]+STACK_Y_PT])
  labels=[]
  for block in page.get_text('dict')['blocks']:
   for line in block.get('lines',[]):
    spans=line.get('spans',[]);text=' '.join(s['text'].strip() for s in spans).strip()
    if not text:continue
    rr=rect(line['bbox']);center=[(rr[0]+rr[2])/2,(rr[1]+rr[3])/2]
    if sheet.role=='unit_plan' and max((s['size'] for s in spans),default=0)>12 and re.search(r'STUDIO|BEDROOM|UNIT TYPE|SUITE TYPE',text,re.I):labels.append((text,rr))
    for match in re.finditer(r'\[(\d+(?:\.\d+)?)m\]',text):
     m=float(match.group(1));geom.dimensions.append(Dimension(text=text,feet=m/.3048,metres=m,xy=center,a=[rr[0],rr[1]],b=[rr[2],rr[1]],source='metric_bracket'))
    for span in spans:
     word=span['text'].strip()
     if not word:continue
     sr=rect(span['bbox']);text_items.append({'text':word,'xy':[(sr[0]+sr[2])/2,(sr[1]+sr[3])/2]})
  geom.room_tags=build_room_tags(text_items,tag_boxes)
  clustered,rejected=cluster_door_fragments(door_frags,scale)
  for i,door in enumerate(clustered):
   geom.doors.append(Door(id=f'{sheet.sheet_id}-d{i}',xy=door['xy'],bbox=door['bbox'],width_pt=door['width_pt'],width_ft=door['width_ft'],hinge_pt=door.get('hinge_pt'),arc_mid_pt=door.get('arc_mid_pt')))
  if rejected:
   geom.warnings.append(f'Rejected {rejected} door clusters outside {DOOR_WIDTH_MIN_FT:g}–{DOOR_WIDTH_MAX_FT:g} ft')
  for name,rr in sorted(labels,key=lambda x:(-x[1][1],x[1][0])):
   cx=(rr[0]+rr[2])/2
   candidates=[f for f in frames if f[0]<=cx<=f[2] and rr[3]-15<=f[1]<=rr[3]+100]
   if candidates:
    region=min(candidates,key=lambda f:(abs(f[1]-rr[3]),(f[2]-f[0])*(f[3]-f[1])))
    if not any(math.dist(region,r['bbox_pt'])<1 for r in geom.regions):geom.regions.append({'id':f'{sheet.sheet_id}-region-{len(geom.regions)+1}','name':name,'bbox_pt':region,'scale_pts_per_ft':scale,'kind':'unit','confidence':.95})
  geom.grid.bubbles=extract_grid_bubbles(page,xy,rect)
  geom.excluded.furniture=counts['furniture'];geom.excluded.wall_hatch=counts['wall_hatch'];geom.excluded.unmapped=counts['unmapped']
  geom.extraction_stats={'paths':len(drawings),**dict(counts),'regions':len(geom.regions),'raw_walls':len(geom.walls),'door_fragments':len(door_frags),'door_clusters':len(geom.doors)+rejected,'door_rejected':rejected,'extraction_warnings':rejected}
  if scale and geom.walls:
    from plancheck.services.wall_collapse import collapse_sheet_walls
    geom.walls=collapse_sheet_walls(geom.walls,scale,sheet.sheet_id)
  geom.extraction_stats['collapsed_walls']=len(geom.walls)
  if not scale:geom.warnings.append('Scale is unknown. Set a calibrated scale before metric reconstruction.')
  if not geom.walls:geom.warnings.append('No recognized wall layers; use the sheet as reference or review layer mappings.')
  raster.parent.mkdir(parents=True,exist_ok=True);pix=page.get_pixmap(matrix=pymupdf.Matrix(.6,.6),alpha=False);pix.save(raster)
  write_wall_thumb(geom,thumb_path(raster))
  geom.raster=RasterRef(dpi=43.2,file=f'sheets/{raster.name}',size_px=[pix.width,pix.height])
  return geom

_GRID_LABEL_RE=re.compile(r'^[A-Za-z]{1,2}$|^\d{1,2}[a-z]?$')

_HVAC_TAG_RE=re.compile(r'^(PTAC|RTU-\d+|EF-\d+|AHU-\d+|VAV-\d+|HP-\d+)$')
_PLUMB_TAG_RE=re.compile(r'^(WC-\d+|LAV-\d+|SH-\d+|FD|CO|RD|P-\d+)$')

_HVAC_KIND={
 'PTAC':'hvac','RTU':'hvac','EF':'hvac','AHU':'hvac','VAV':'hvac','HP':'hvac',
}
_PLUMB_KIND={
 'WC':'plumbing','LAV':'plumbing','SH':'plumbing','FD':'plumbing','CO':'plumbing','RD':'plumbing','P':'plumbing',
}

def _kind_from_tag(tag:str)->str:
 prefix=re.split(r'[-\d]',tag)[0].upper()
 return _HVAC_KIND.get(prefix,_PLUMB_KIND.get(prefix,'unknown'))

def extract_grid_bubbles(page,xy_fn,rect_fn)->list[GridBubble]:
 """Extract grid bubble labels from sheet margins."""
 width,height=page.rect.width,page.rect.height
 margin_x=width*0.05
 margin_y=height*0.05
 bubbles=[]
 for block in page.get_text('dict')['blocks']:
  for line in block.get('lines',[]):
   for span in line.get('spans',[]):
    text=span['text'].strip()
    if not text or not _GRID_LABEL_RE.match(text):continue
    rr=rect_fn(span['bbox'])
    cx,cy=(rr[0]+rr[2])/2,(rr[1]+rr[3])/2
    # Must be at sheet margins (within 5% of edges)
    at_left=rr[0]<margin_x
    at_right=rr[2]>width-margin_x
    at_top=rr[3]>height-margin_y  # y-up: top of sheet = high y
    at_bottom=rr[1]<margin_y
    if not (at_left or at_right or at_top or at_bottom):continue
    # Deduplicate: don't add if same label already nearby
    dup=False
    for existing in bubbles:
     if existing.label.upper()==text.upper() and math.dist(existing.xy,[cx,cy])<width*0.02:
      dup=True;break
    if not dup:
     bubbles.append(GridBubble(label=text,xy=[cx,cy]))
 return bubbles


def extract_mep(sheet:Sheet,path:Path,raster_path:Path)->MepSheetData:
 """Extract MEP equipment and grid bubbles from a PDF sheet page."""
 discipline=sheet.discipline or 'unknown'
 with pymupdf.open(path) as doc:
  page=doc[sheet.page-1]
  height=page.rect.height
  def xy(p):
   q=pymupdf.Point(p)*page.rotation_matrix
   return [float(q.x),float(height-q.y)]
  def rect(r):
   q=pymupdf.Rect(r)*page.rotation_matrix
   return [float(q.x0),float(height-q.y1),float(q.x1),float(height-q.y0)]

  # Grid bubbles
  bubbles=extract_grid_bubbles(page,xy,rect)
  grid=SheetGrid(bubbles=bubbles)

  equipment:list[MepEquipment]=[]
  flattened=True
  flattened_reason=''
  layer_map:dict[str,str]={}

  if discipline=='electrical':
   # Electrical: try layered PDF — only load drawings for electrical
   drawings=page.get_drawings()
   layer_names={normalise(d.get('layer')) for d in drawings}
   layer_names.discard('')
   layer_map={name:name for name in layer_names}
   is_layered=len(layer_names)>1
   if is_layered:
    flattened=False
    eq_layers={'e-lite-eqpm','e-equipment'}
    eq_frags:list[list[float]]=[]
    for d in drawings:
     layer=normalise(d.get('layer'))
     if layer.lower() not in eq_layers:continue
     rr=rect(d['rect'])
     eq_frags.append(rr)
    del drawings  # free memory
    if eq_frags:
     cell=30.0
     buckets:dict[tuple[int,int],list[int]]={}
     for i,box in enumerate(eq_frags):
      gx=int(box[0]//cell);gy=int(box[1]//cell)
      for dx in range(-1,2):
       for dy in range(-1,2):
        buckets.setdefault((gx+dx,gy+dy),[]).append(i)
     parent=list(range(len(eq_frags)));rank=[0]*len(eq_frags)
     def find(i):
      while parent[i]!=i:parent[i]=parent[parent[i]];i=parent[i]
      return i
     def union(a,b):
      a,b=find(a),find(b)
      if a==b:return
      if rank[a]<rank[b]:parent[a]=b
      elif rank[a]>rank[b]:parent[b]=a
      else:parent[b]=a;rank[a]+=1
     for idxs in buckets.values():
      for ai in range(len(idxs)):
       for bi in range(ai+1,len(idxs)):
        ia,ib=idxs[ai],idxs[bi]
        a,b=eq_frags[ia],eq_frags[ib]
        if a[0]<b[2] and b[0]<a[2] and a[1]<b[3] and b[1]<a[3]:
         union(ia,ib)
     groups:dict[int,list[int]]={}
     for i in range(len(eq_frags)):groups.setdefault(find(i),[]).append(i)
     for group in groups.values():
      xs=[c for i in group for c in (eq_frags[i][0],eq_frags[i][2])]
      ys=[c for i in group for c in (eq_frags[i][1],eq_frags[i][3])]
      cx=(min(xs)+max(xs))/2;cy=(min(ys)+max(ys))/2
      kind='lighting' if any('lite' in normalise(eq_frags[g][0] if False else '').lower() for g in group[:0]) else 'power'
      equipment.append(MepEquipment(tag=None,xy_pt=[cx,cy],bbox=[min(xs),min(ys),max(xs),max(ys)],discipline='electrical',kind=kind))
   else:
    # Flattened electrical — fall through to text extraction below
    flattened_reason=f"Single-layer PDF; ~{len(drawings)} paths on one layer"
    del drawings

  if flattened:
   # HVAC/Plumbing/flattened electrical: text-only extraction (no get_drawings needed)
   if not flattened_reason:
    flattened=True
    flattened_reason='Text-based extraction'
   for block in page.get_text('dict')['blocks']:
    for line in block.get('lines',[]):
     for span in line.get('spans',[]):
      text=span['text'].strip()
      if not text:continue
      rr=rect(span['bbox'])
      cx,cy=(rr[0]+rr[2])/2,(rr[1]+rr[3])/2
      if _HVAC_TAG_RE.match(text):
       equipment.append(MepEquipment(tag=text,xy_pt=[cx,cy],bbox=rr,discipline='mechanical',kind=_kind_from_tag(text)))
      elif _PLUMB_TAG_RE.match(text):
       equipment.append(MepEquipment(tag=text,xy_pt=[cx,cy],bbox=rr,discipline='plumbing',kind=_kind_from_tag(text)))

  # Save raster — same DPI as architectural (43.2) to avoid OOM on large MEP sheets
  raster_path.parent.mkdir(parents=True,exist_ok=True)
  pix=page.get_pixmap(matrix=pymupdf.Matrix(.6,.6),alpha=False)
  pix.save(raster_path)

  return MepSheetData(
   sheet_id=sheet.sheet_id,
   discipline=discipline,
   equipment=equipment,
   grid=grid,
   flattened=flattened,
   flattened_reason=flattened_reason,
   layer_map=layer_map,
  )


def extract_cached(sheet:Sheet,path:Path,raster:Path,digest:str|None=None)->tuple[SheetGeometry,bool]:
 digest=digest or file_digest(path)
 json_path,raster_cache,thumb_cache=cache_paths(digest,sheet.page)
 thumb=thumb_path(raster)
 if json_path.exists() and raster_cache.exists():
  geom=SheetGeometry.model_validate_json(json_path.read_text())
  geom.sheet_id=sheet.sheet_id;geom.doc_id=sheet.doc_id;geom.page=sheet.page
  raster.parent.mkdir(parents=True,exist_ok=True)
  shutil.copyfile(raster_cache,raster)
  if thumb_cache.exists():shutil.copyfile(thumb_cache,thumb)
  else:write_wall_thumb(geom,thumb)
  geom.raster=RasterRef(dpi=geom.raster.dpi or 43.2,file=f'sheets/{raster.name}',size_px=geom.raster.size_px)
  return geom,True
 geom=extract(sheet,path,raster)
 json_path.parent.mkdir(parents=True,exist_ok=True)
 json_path.write_text(geom.model_dump_json())
 if raster.exists():shutil.copyfile(raster,raster_cache)
 if thumb.exists():shutil.copyfile(thumb,thumb_cache)
 return geom,False
