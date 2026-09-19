"""Measured CAD PDF paths normalized to displayed sheet coordinates, y up."""
from pathlib import Path
from collections import Counter
import math,re
import pymupdf
from plancheck.core.schemas import Sheet,SheetGeometry,Wall,Door,Window,Fixture,RoomTag,RasterRef,Dimension
from plancheck.core.layers import bucket_for,normalise

ROOM_TAG_REJECT=re.compile(r"""[\d\[\]'"]""")
STACK_X_PT=12.0
STACK_Y_PT=18.0

def _point_in_bbox(xy,bbox)->bool:
 return bbox[0]<=xy[0]<=bbox[2] and bbox[1]<=xy[1]<=bbox[3]

def is_fallback_room_tag(text:str)->bool:
 cleaned=' '.join(text.split())
 return len(cleaned)>=3 and cleaned==cleaned.upper() and re.fullmatch(r'[A-Z]+(?: [A-Z]+)*',cleaned) is not None and not ROOM_TAG_REJECT.search(cleaned)

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
  drawings=page.get_drawings();counts=Counter();frames=[];tag_boxes=[];text_items=[]
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
    width=max(w,h);geom.doors.append(Door(id=f'{sheet.sheet_id}-d{i}',xy=[(rr[0]+rr[2])/2,(rr[1]+rr[3])/2],bbox=rr,width_pt=width,width_ft=width/scale if scale else 0))
   elif bucket=='window':
    for j,(a,b) in enumerate(segments):
     if math.dist(a,b)>1:geom.windows.append(Window(id=f'{sheet.sheet_id}-win{i}-{j}',a=a,b=b,width_ft=math.dist(a,b)/scale if scale else 0))
   elif bucket=='fixture':geom.fixtures.append(Fixture(id=f'{sheet.sheet_id}-f{i}',xy=[(rr[0]+rr[2])/2,(rr[1]+rr[3])/2],bbox=rr,layer=layer))
   elif bucket=='room_tag':tag_boxes.append(rr)
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
  for name,rr in sorted(labels,key=lambda x:(-x[1][1],x[1][0])):
   cx=(rr[0]+rr[2])/2
   candidates=[f for f in frames if f[0]<=cx<=f[2] and rr[3]-15<=f[1]<=rr[3]+100]
   if candidates:
    region=min(candidates,key=lambda f:(abs(f[1]-rr[3]),(f[2]-f[0])*(f[3]-f[1])))
    if not any(math.dist(region,r['bbox_pt'])<1 for r in geom.regions):geom.regions.append({'id':f'{sheet.sheet_id}-region-{len(geom.regions)+1}','name':name,'bbox_pt':region,'scale_pts_per_ft':scale,'kind':'unit','confidence':.95})
  geom.excluded.furniture=counts['furniture'];geom.excluded.wall_hatch=counts['wall_hatch'];geom.excluded.unmapped=counts['unmapped']
  geom.extraction_stats={'paths':len(drawings),**dict(counts),'regions':len(geom.regions),'raw_walls':len(geom.walls)}
  if scale and geom.walls:
    from plancheck.services.wall_collapse import collapse_sheet_walls
    geom.walls=collapse_sheet_walls(geom.walls,scale,sheet.sheet_id)
  geom.extraction_stats['collapsed_walls']=len(geom.walls)
  if not scale:geom.warnings.append('Scale is unknown. Set a calibrated scale before metric reconstruction.')
  if not geom.walls:geom.warnings.append('No recognized wall layers; use the sheet as reference or review layer mappings.')
  raster.parent.mkdir(parents=True,exist_ok=True);pix=page.get_pixmap(matrix=pymupdf.Matrix(.6,.6),alpha=False);pix.save(raster)
  geom.raster=RasterRef(dpi=43.2,file=f'sheets/{raster.name}',size_px=[pix.width,pix.height])
  return geom
