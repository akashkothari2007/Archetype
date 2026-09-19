"""Deterministic demo building. A fixed program run through the real compiler.

This is the `PLANCHECK_GENERATION_PROVIDER=demo` path: no model, no packer, just
a hand-authored program and layout so the app always has something to open. The
geometry itself is built by the same compiler the generation agent uses.
"""
from __future__ import annotations

from plancheck.core.building import Building
from plancheck.generation.compiler import CompileOptions, compile_building
from plancheck.generation.program import BuildingProgram, FloorLayout

# id, name, category, x1, y1, x2, y2
_GROUND = [
    ('living', 'Living room', 'living', 0, 0, 24, 16),
    ('kitchen', 'Kitchen', 'kitchen', 24, 0, 40, 16),
    ('dining', 'Dining room', 'dining', 0, 16, 16, 30),
    ('foyer', 'Entry & stair', 'circulation', 16, 16, 26, 30),
    ('utility', 'Utility', 'service', 26, 16, 33, 23),
    ('bath', 'Bathroom', 'bathroom', 33, 16, 40, 23),
    ('study', 'Study', 'office', 26, 23, 40, 30),
]
_UPPER = [
    ('bed1', 'Primary bedroom', 'bedroom', 0, 0, 24, 16),
    ('bed2', 'Bedroom 02', 'bedroom', 24, 0, 40, 16),
    ('bed3', 'Bedroom 03', 'bedroom', 0, 16, 16, 30),
    ('landing', 'Landing', 'circulation', 16, 16, 26, 30),
    ('bath2', 'Bathroom', 'bathroom', 26, 16, 34, 30),
    ('closet', 'Dressing room', 'storage', 34, 16, 40, 30),
]
_PLAN = {'ground': ('Ground floor', _GROUND), 'upper': ('First floor', _UPPER)}
# Narrower than the 0.9 m demo requirement on purpose: the repair agent has to
# have something real to widen.
_OPTIONS = CompileOptions(door_width_ft=2.8, method='demo-template', door_every_partition=True)


def demo_program() -> tuple[BuildingProgram, dict[str, FloorLayout]]:
    program = BuildingProgram(
        building_use='home',
        storeys=[{'id': fid, 'name': name, 'height_ft': 10} for fid, (name, _) in _PLAN.items()],
        spaces=[
            {
                'id': rid,
                'name': name,
                'floor_id': fid,
                'category': category,
                'target_area_sqft': (x2 - x1) * (y2 - y1),
                'min_side_ft': min(x2 - x1, y2 - y1),
                'stair': rid == 'foyer',
                'entry': rid == 'foyer',
            }
            for fid, (_, rects) in _PLAN.items()
            for rid, name, category, x1, y1, x2, y2 in rects
        ],
        notes='Fixed demo house used when no generation model is configured.',
    )
    layouts = {
        fid: FloorLayout(
            floor_id=fid,
            width_ft=40,
            depth_ft=30,
            rooms=[
                {'space_id': rid, 'x1': x1, 'y1': y1, 'x2': x2, 'y2': y2}
                for rid, _, _, x1, y1, x2, y2 in rects
            ],
        )
        for fid, (_, rects) in _PLAN.items()
    }
    return program, layouts


def demo_home() -> Building:
    program, layouts = demo_program()
    return compile_building(program, layouts, _OPTIONS)


def demo_rules() -> list[dict]:
    return [dict(rule_id='DEMO-DOOR-001',applies_to='*',metric='aperture_width',operator='>=',value=.9,unit='m',source_doc='Demo project requirements',source_page=1,source_text='For this demo, modeled door apertures should be at least 0.90 m.',source_section='Demo requirements — not building code',status='approved',scope='opening',target_ids=[],supported=True),dict(rule_id='DEMO-BATH-001',applies_to='bathroom',metric='area',operator='>=',value=6,unit='m2',source_doc='Demo project requirements',source_page=1,source_text='For this demo, bathroom interior area should be at least 6 m².',source_section='Demo requirements — not building code',status='approved',scope='room',target_ids=[],supported=True)]
