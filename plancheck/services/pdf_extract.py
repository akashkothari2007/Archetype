"""Measured CAD PDF paths normalized to displayed sheet coordinates, y up."""
from pathlib import Path
from collections import Counter
import hashlib,math,re,shutil
import pymupdf
from plancheck.core.schemas import Sheet,SheetGeometry,Wall,Door,Window,Fixture,RoomTag,RasterRef,Dimension
from plancheck.core.layers import bucket_for,normalise
from plancheck.core.settings import get_settings

EXTRACTOR_VERSION='5'
ROOM_TAG_REJECT=re.compile(r"""[\d\[\]'"]""")
STACK_X_PT=12.0
STACK_Y_PT=18.0
DOOR_CLUSTER_FT=0.5

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

def _bbox_gap(a,b)->float:
 dx=max(0.0,a[0]-b[2],b[0]-a[2]);dy=max(0.0,a[1]-b[3],b[1]-a[3])
 return math.hypot(dx,dy)

def _longest_straight(segments):
 best=None
 for a,b in segments:
  length=math.dist(a,b)
  if best is None or length>best[0]:best=(length,a,b)
 return best

def cluster_door_fragments(fragments:list[dict],scale:float,cluster_ft:float=DOOR_CLUSTER_FT)->list[dict]:
 """Group DOOR-layer paths whose bboxes are within cluster_ft, then measure the leaf.

 The layer stores the leaf, swing arc and jamb marks as separate paths. Width is
 the longest straight segment in the cluster (the leaf) — not the bbox diagonal
 and not an arc.
 """
 n=len(fragments)
 if not n:return []
 parent=list(range(n))
 def find(i):
  while parent[i]!=i:parent[i]=parent[parent[i]];i=parent[i]
  return i
 thresh=(cluster_ft*scale) if scale else cluster_ft
 for i in range(n):
  for j in range(i+1,n):
   if _bbox_gap(fragments[i]['bbox'],fragments[j]['bbox'])<=thresh:
    a,b=find(i),find(j)
    if a!=b:parent[a]=b
 groups={}
 for i in range(n):groups.setdefault(find(i),[]).append(fragments[i])
 doors=[]
 for group in groups.values():
  segments=[seg for frag in group for seg in frag.get('segments') or []]
  longest=_longest_straight(segments)
  xs=[c for frag in group for c in (frag['bbox'][0],frag['bbox'][2])]
  ys=[c for frag in group for c in (frag['bbox'][1],frag['bbox'][3])]
  bbox=[min(xs),min(ys),max(xs),max(ys)]
  if longest:
   width_pt,a,b=longest
   xy=[(a[0]+b[0])/2,(a[1]+b[1])/2]
  else:
   width_pt=0.0;xy=[(bbox[0]+bbox[2])/2,(bbox[1]+bbox[3])/2]
  doors.append({'xy':xy,'bbox':bbox,'width_pt':width_pt,'width_ft':width_pt/scale if scale else 0.0})
 return doors

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
   elif bucket=='door' and w>1 and h>1:
    door_frags.append({'bbox':rr,'segments':segments})
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
  for i,door in enumerate(cluster_door_fragments(door_frags,scale)):
   geom.doors.append(Door(id=f'{sheet.sheet_id}-d{i}',xy=door['xy'],bbox=door['bbox'],width_pt=door['width_pt'],width_ft=door['width_ft']))
  for name,rr in sorted(labels,key=lambda x:(-x[1][1],x[1][0])):
   cx=(rr[0]+rr[2])/2
   candidates=[f for f in frames if f[0]<=cx<=f[2] and rr[3]-15<=f[1]<=rr[3]+100]
   if candidates:
    region=min(candidates,key=lambda f:(abs(f[1]-rr[3]),(f[2]-f[0])*(f[3]-f[1])))
    if not any(math.dist(region,r['bbox_pt'])<1 for r in geom.regions):geom.regions.append({'id':f'{sheet.sheet_id}-region-{len(geom.regions)+1}','name':name,'bbox_pt':region,'scale_pts_per_ft':scale,'kind':'unit','confidence':.95})
  geom.excluded.furniture=counts['furniture'];geom.excluded.wall_hatch=counts['wall_hatch'];geom.excluded.unmapped=counts['unmapped']
  geom.extraction_stats={'paths':len(drawings),**dict(counts),'regions':len(geom.regions),'raw_walls':len(geom.walls),'door_fragments':len(door_frags),'door_clusters':len(geom.doors)}
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
