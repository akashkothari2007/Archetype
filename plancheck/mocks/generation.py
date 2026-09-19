"""Temporary deterministic generation provider. Replace this module, not geometry services."""
from __future__ import annotations
from plancheck.core.building import Building,Floor,Vertex,BuildingWall,Room,Opening,PlacedObject,Source
from plancheck.services.commands import recompute_rooms,validate_building


def demo_home() -> Building:
    b=Building(floors=[Floor(id='ground',name='Ground floor'),Floor(id='upper',name='First floor',elevation_ft=10)])
    layouts={
      'ground': [('living','Living room','living',0,0,24,16),('kitchen','Kitchen','kitchen',24,0,40,16),('dining','Dining room','dining',0,16,16,30),('foyer','Entry & stair','circulation',16,16,26,30),('utility','Utility','service',26,16,33,23),('bath','Bathroom','bathroom',33,16,40,23),('study','Study','office',26,23,40,30)],
      'upper':[('bed1','Primary bedroom','bedroom',0,0,24,16),('bed2','Bedroom 02','bedroom',24,0,40,16),('bed3','Bedroom 03','bedroom',0,16,16,30),('landing','Landing','circulation',16,16,26,30),('bath2','Bathroom','bathroom',26,16,34,30),('closet','Dressing room','storage',34,16,40,30)]}
    for floor,rects in layouts.items():
        points=set();segments=[]
        for rid,name,category,x1,y1,x2,y2 in rects:
            pts=[(x1,y1),(x2,y1),(x2,y2),(x1,y2)];points.update(pts)
            segments.extend(zip(pts,pts[1:]+pts[:1]))
            b.rooms.append(Room(id=f'{floor}-{rid}',floor_id=floor,name=name,category=category,type_ref='home.bedroom' if category=='bedroom' else f'home.{category}',polygon=pts,floor_material='tile' if category=='bathroom' else 'oak',source=Source(method='demo-template')))
        edges=set()
        for a,c in segments:
            on=sorted([p for p in points if min(a[0],c[0])<=p[0]<=max(a[0],c[0]) and min(a[1],c[1])<=p[1]<=max(a[1],c[1]) and (c[0]-a[0])*(p[1]-a[1])==(c[1]-a[1])*(p[0]-a[0])])
            edges.update(tuple(sorted([p,q])) for p,q in zip(on,on[1:]))
        vertices={p:f'{floor}-v-{i}' for i,p in enumerate(sorted(points))}
        b.vertices.extend(Vertex(id=id,floor_id=floor,x=p[0],y=p[1]) for p,id in vertices.items())
        for i,(a,c) in enumerate(sorted(edges)):
            external=(a[0]==c[0] and a[0] in [0,40]) or (a[1]==c[1] and a[1] in [0,30])
            w=BuildingWall(id=f'{floor}-wall-{i}',floor_id=floor,start_id=vertices[a],end_id=vertices[c],thickness_ft=.65 if external else .4,structural='loadbearing' if external else 'nonstructural',locked=external,source=Source(method='demo-template'))
            b.walls.append(w)
            length=((c[0]-a[0])**2+(c[1]-a[1])**2)**.5
            if external and length>=9:
                is_entry=floor=='ground' and a==(16,30) and c==(26,30)
                b.openings.append(Opening(id=f'{w.id}-opening',wall_id=w.id,kind='door' if is_entry else 'window',offset_ft=(length-(3.3 if is_entry else 5))/2,width_ft=3.3 if is_entry else 5,height_ft=7 if is_entry else 4,sill_ft=0 if is_entry else 3))
            elif not external and length>=5:
                b.openings.append(Opening(id=f'{w.id}-opening',wall_id=w.id,kind='door',offset_ft=max(.5,(length-2.8)/2),width_ft=2.8,height_ft=7))
        for r in [r for r in b.rooms if r.floor_id==floor and r.category=='bathroom']:
            x,y=r.polygon[0]
            b.objects.extend([PlacedObject(id=f'{r.id}-wc',floor_id=floor,asset_id='toilet',kind='fixture',x=x+2,y=y+2,width_ft=1.8,depth_ft=2.5,height_ft=2.5),PlacedObject(id=f'{r.id}-sink',floor_id=floor,asset_id='sink',kind='fixture',x=x+5,y=y+2,width_ft=2,depth_ft=1.6,height_ft=2.8)])
        b.objects.append(PlacedObject(id=f'{floor}-stairs',floor_id=floor,asset_id='stairs',kind='reference',x=20,y=25,width_ft=3.2,depth_ft=8,height_ft=8))
    recompute_rooms(b,{'ground','upper'});validate_building(b)
    return b


def demo_rules() -> list[dict]:
    return [dict(rule_id='DEMO-DOOR-001',applies_to='*',metric='aperture_width',operator='>=',value=.9,unit='m',source_doc='Demo project requirements',source_page=1,source_text='For this demo, modeled door apertures should be at least 0.90 m.',source_section='Demo requirements — not building code',status='approved',scope='opening',target_ids=[],supported=True),dict(rule_id='DEMO-BATH-001',applies_to='bathroom',metric='area',operator='>=',value=6,unit='m2',source_doc='Demo project requirements',source_page=1,source_text='For this demo, bathroom interior area should be at least 6 m².',source_section='Demo requirements — not building code',status='approved',scope='room',target_ids=[],supported=True)]
