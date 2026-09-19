# Archetype

Drop a folder with the arch PDF + brand standards PDF into **Import a project** (not "Generate", that's the mock house). `classify` reads the title block on all 51 pages and keeps ~13. `extract` pulls each page apart **by CAD layer** — these came out of AutoCAD with layers intact, so every line already knows if it's `WALL-STUD-LOADBEARING` or `DOOR` or `I-FURN`. No CV, no guessing. Segments get scaled to feet, shapely polygonizes them into rooms, that's `Building`. Separately `extract_rules` regexes the 349-page manual into rules with page citations, you approve them in Standards, `compliance.py` measures rooms against them, Checks tab shows failures. Agent proposes fixes, human applies.

Everything hangs off `Building` / `model.json`. Classify, extract, build_model, rules, compliance, undo/redo, import are real. Agent and generator are mocks.

**Akash** — `services/pdf_extract.py`, `services/imports.py`
- Extend wall segments ~3ft before polygonize or doorway gaps leak (3ft → 2742 sqft / 9 rooms, 0ft → 302 sqft / 13 slivers)
- `room_tags` is grabbing dimensions not names, everything is "Space 1" — filter to `ANNO-ROOM TAG`
- Openings = 0, attach doors/windows to walls or 3D has no doorways
- Unit plans (p51) are a type catalogue, not floors. Floors = A.201 + A.202 only
- Pages 51, 8, 7. Page 8 is 210k paths, that's the fight

**Frontend** — `apps/desktop/src/renderer/`
- Furniture back as a 2D display-only layer, already extracted, makes plans look real
- Stack floors in 3D with a cutaway slider + crude stair core, walkthrough if time
- Mismatches need to pop — red rooms, "×84 units" badge, click → quoted clause + page
- `confidence < 0.6` renders hatched, don't hide uncertainty

**Compliance** — `engines/extract_rules.py`, `services/compliance.py`
- More rules parsing, lots come back `supported: false`
- Add corridor width, door clear width, accessible turning (`FLOOR-CLR SPACE` is extracted, unused)
- Keep the approval step in Standards, it's the answer to "how do you know the AI got the rule right"

**Agent** — `mocks/agent_provider.py`
- Real model call, same `respond()` signature, mock as fallback. `/health` says `agent_provider: mock`, that's the finish line
- Model never decides pass/fail, compliance.py does. It explains and proposes a `CommandBatch`
- Block anything touching `structural: "loadbearing"` in code, not in the prompt
- violation → proposal → apply → re-check green is the demo

Notes: don't say clash detection, no heights in 2D plans. MEP PDFs are flattened and useless, fixtures come from the arch drawing. Don't push the drawings to a public repo. Pitch is "this takes a person two days", not "nobody catches these".
