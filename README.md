# Archetype

Archetype is a local-first Electron desktop editor for architectural projects. It includes a guided project generator, managed local project storage, an editable 2D floor plan, a derived 3D view, standards checks, and deterministic repair previews. The FastAPI service owns the versioned model and command history; the Electron renderer never writes project JSON directly.

## Run the app

Install Python dependencies into `.venv`, install the workspace packages with `pnpm install`, then run `pnpm dev:local`. That starts the local API and Electron shell together. The API is available at `http://127.0.0.1:8000`; project data is kept under `local-data/projects/` and is ignored by git. Copy `.env.example` to `.env` when changing local settings. Docker support is provided by `compose.yaml` for environments with Docker installed.

The main workflow is:

1. Generate a demo project through the six-question brief, or import a PDF, DXF, or IFC source.
2. Edit the shared model in the 2D Floor Plan view and inspect the derived 3D Model view.
3. Ask the local mock agent to analyze or repair issues; review the proposed commands before applying them.
4. Save, undo, redo, and reopen the project from the recent-projects sidebar.

Source drawings and standards documents remain outside version control. Imported geometry that cannot be measured confidently is preserved as review content rather than silently promoted to editable geometry.

The acceptance dataset is documented in the implementation plan supplied with the project. The real PDF pipeline preserves page rotation, source references, CAD layers, unresolved regions, and standards provenance. Native DXF/IFC fixtures are covered by tests; the supplied archive itself contains PDFs only.

The sections below describe the original PlanCheck pipeline and remain useful for engine-level work.

Hotel drawing compliance pipeline. Reads an architectural drawing set (PDF) and a brand-standards manual (PDF), builds a structured model of the building, and checks every **space type** against every extracted rule.

This repository is the **scaffold**: contracts, plumbing, a real classifier, and stub engines that return valid fake data. Real extract / model / rules / check / agent implementations swap in behind the same function signatures with zero changes elsewhere.

It solves: proving ~400 rooms comply currently takes a person days, by hand, against a 349-page manual, and it is redone every revision. PlanCheck checks all 84 instances of a room type at once.

Key technical fact: the PDFs were exported from AutoCAD with layers intact. `page.get_drawings()` returns a `layer` key on every path. This is a CAD database wrapped in a PDF, not computer vision. No `.dwg` is ever needed. No LLM, no OpenCV, no database.

## Architecture

```
drawings.pdf ──► classify ──► project.json ──► extract ──► sheets/*.json ──► build_model ──┐
                                                                │                          │
                                                                └──► 2D viewer        model.json
                                                                                           │
standards.pdf ─────────────► extract_rules ──► rules.json ──────────────► check ◄───────────┤
                                                                            │              │
                                                                     mismatches.json       │
                                                                            │              │
                                                            ┌───────────────┼──────────────┤
                                                            ▼               ▼              ▼
                                                          agent         3D viewer     blast radius
                                                            │
                                                     proposed_edits.json
```

Stages 1–3 and 4–5 are independent tracks. They only meet at stage 5.

Storage is the filesystem: `plancheck/data/projects/<project_id>/`. No DB, no ORM.

```
<project_id>/
  project.json
  uploads/drawings/…
  uploads/standards/…
  sheets/<sheet_id>.json
  sheets/<sheet_id>.raster.png
  model.json
  rules.json
  mismatches.json
  proposed_edits.json
```

`model.json` is the central artifact. The 2D viewer reads **sheets**, not the model. The 3D viewer, checker, blast-radius count, and agent all read the model.

## Six stages

| # | Engine | Module | Input | Output | This scaffold |
|---|--------|--------|-------|--------|---------------|
| 1 | classify | `engines/classify.py` | drawings PDF | `project.json` | **real** |
| 2 | extract | `engines/extract_sheet.py` | one PDF page | `sheets/<id>.json` | stub |
| 3 | model | `engines/build_model.py` | `sheets/*.json` | `model.json` | stub |
| 4 | rules | `engines/extract_rules.py` | standards PDF | `rules.json` | stub |
| 5 | check | `engines/check.py` | model + rules | `mismatches.json` | stub |
| 6 | agent | `engines/agent.py` | mismatches + model | `proposed_edits.json` | stub |

Each engine has `run_stub` and `run_real` with the same signature, plus a CLI:

```bash
python -m plancheck.engines.classify --project pc-…
python -m plancheck.engines.extract_sheet --project pc-… --sheet drw-01-p051
python -m plancheck.engines.build_model --project pc-…
python -m plancheck.engines.extract_rules --project pc-…
python -m plancheck.engines.check --project pc-…
python -m plancheck.engines.agent --project pc-…
```

Selection is per-engine via env var. Default: classify real, everything else stub.

```bash
PLANCHECK_ENGINES=classify:real,extract:stub,model:stub,rules:stub,check:stub,agent:stub
```

Swap extract to real with **zero** other changes:

```bash
PLANCHECK_ENGINES=classify:real,extract:real,model:stub,rules:stub,check:stub,agent:stub
```

Stubs load `plancheck/fixtures/<artifact>.json`, rewrite ids to the current project, and return a validated Pydantic model. `PLANCHECK_STUB_DELAY_MS` (default 400) exercises frontend loading states.

## Coordinate conventions

**One flip, one place.**

| Space | Units | Origin | Y |
|-------|-------|--------|---|
| Sheet | PDF points | bottom-left | up |
| Building | feet | named grid intersection | up |
| World (3D) | feet | same XY as building, mapped | plan `(x,y)` → world `(x,z)`, extrude along world **y** |

PyMuPDF returns y **down** from top-left. Convert exactly once at the read boundary:

```python
from plancheck.core.geometry import flip_y
y_out = flip_y(y_pymupdf, page.rect.height)  # page.rect.height - y_pymupdf
```

That helper is the only place PlanCheck inverts y. The 2D SVG applies `matrix(1 0 0 -1 0 height)` so y-up data renders upright — that is a **view** transform, not a data flip.

Building feet from sheet points:

```
ft = (pt − sheet_origin_pt) / scale_pts_per_ft
```

(`plancheck.core.geometry.pt_to_ft`)

The grid is the shared coordinate system between sheets and disciplines. Extract it on every sheet even when unused.

**Rendering conventions, not extracted data:** `ASSUMED_WALL_HEIGHT_FT = 9.0` and `ASSUMED_WALL_THICKNESS_FT = 0.5` in `core/geometry.py`. 2D plans carry no elevation. Label them *assumed* anywhere they are shown. Never say “clash detection.”

Geometry rule for the real model engine: shapes come from the most precise sheet that contains them (p51 1/4" > p33–37 3/16" > p8 1/16"). Placement always comes from the floor plan (p8). Never mix.

## Schemas (`core/schemas.py`)

Every JSON file that crosses a boundary has a Pydantic v2 model. Stubs return validated instances, not dicts.

### `project.json` — `Project`

`project_id`, `name`, `created_at`, `units` (`ft`), `documents[]`, `sheets[]`, `model_file`.

**Document:** `doc_id`, `filename`, `slot` (`drawings` \| `standards`), `discipline`, `pages`, `page_size_pt[2]`, `text_extractable`, `layered` (has OCGs), `layer_count`.

**Sheet:** `sheet_id`, `doc_id`, `page` (1-based), `sheet_no`, `title`, `discipline`, `role`, `scale_text`, `scale_pts_per_ft`, `scale_source`, `levels[]`, `use`, `reason`, `stats{paths,words,layers,dim_tokens}`, `geometry_file`.

`use=false` **must** carry a human-readable `reason`. Roles: `unit_plan`, `enlarged_plan`, `floor_plan`, `slab_edge`, `schedule`, `elevation`, `section`, `detail`, `roof`, `site`, `unknown`.

`use=true` only for `unit_plan`, `enlarged_plan`, `floor_plan`, `schedule`.

`sheet_id` is stable (`{doc_id}-p{page:03d}`). `sheet_no` is the title-block number (`A.801`).

### `sheets/<id>.json` — `SheetGeometry`

Sheet space. `cls` on a wall comes from the CAD layer, not geometry — that is what stops the agent proposing structurally impossible edits. Fixture `kind` starts as `unknown`; do not guess. `excluded` makes dropped furniture / hatch / unmapped paths auditable.

Wall, Door, Window, Fixture, SheetGrid (`x_axes`/`y_axes` with `pos_pt`, `bubbles`), RoomTag, Dimension, ClearSpace (`polygon`), CoordinateSystem, RasterRef (`dpi`, `file`, `size_px`).

Prefer the **metric bracket** on dimensions. Imperial fractions extract mangled (`31'-2½"` → `"31'-212"`).

### `model.json` — `Model`

Building space. Units `feet`. Origin `{grid_x, grid_y}`. Grid axes `{label, x_ft}` / `{label, y_ft}`.

**Level:** `index`, `name`, `sheets[]`, optional `repeats_as` (from titles like `TYPICAL FLOOR PLAN (2ND & 3RD)`).

**SpaceType:** geometry lives on the type. `type_id`, `name`, `category`, `accessible`, `source_sheet`, `source_region_pt`, `boundary_ft`, `area_sqft`, `area_m2`, `bbox_ft{w,d}`, `children[]`, type-level `doors`/`windows`/`fixtures`, `confidence`, `method`, `instance_count` (blast radius).

**Space:** one instance. `space_id`, `type_ref`, `level`, `number`, `origin_ft`, `rotation_deg`, `mirrored`, `source_sheet`, `confidence`. No geometry.

Compliance runs once per type, not once per room. `instance_count` is `count(spaces where type_ref == X)`. Degenerate v0 (p51 only): `instance_count: 1` and one synthetic space each. Adding p8 fills real counts. The schema does not change.

Confidence below 0.6 is a shipped UI feature (hatched + “needs review”), not a debug field.

Which sheet fills which field (real model engine):

| Field | Comes from |
|-------|------------|
| `space_types[].boundary_ft`, areas, children, fixtures | p51 (1/4"), fallback p33–37 (3/16") |
| `space_types[].accessible` | p51 label prefix `ACC.` |
| `space_types[].instance_count` | count of matching spaces from p8 |
| `spaces[]` | p8 room tags + positions |
| `grid` | p8 GRID layer |
| `levels[].repeats_as` | p8 title |
| `doors[].width_ft` | p51 geometry, validated against p48 schedule |

### `rules.json` — `Ruleset`

`rules[]` of **Rule:** `rule_id`, `applies_to` (glob over `type_id`), `metric`, `operator`, `value`, `unit`, `source_doc`, `source_page`, `source_text`, `extraction`.

### `mismatches.json` — `CheckResult`

Violations attach to **types**, not rooms. **Mismatch:** `id`, `type_ref`, `rule_id`, `severity` (`fail` \| `warn` \| `cannot_verify`), `metric`, `actual`, `required`, `unit`, `delta`, `instances_affected`, `affected_space_ids[]`, `message`, `source_page`, `source_text`, `model_confidence`.

`cannot_verify` is for “this rule exists but the geometry was not extractable.” Stronger than silently omitting it.

Check never walks `spaces[]`. Blast radius is a count.

### `proposed_edits.json` — `ProposedEdits`

**ProposedEdit:** `edit_id`, `mismatch_id`, `action`, `target`, `change`, `geometry`, `blocked_by[]`, `note`, `affects_instances`.

Agent rules (non-negotiable):

- May only propose edits `check.py` can re-verify.
- Writes `proposed_edits.json` only. Never mutates `model.json`. Never touches a PDF. A human applies.
- Must refuse edits whose affected walls have `cls: loadbearing` (`blocked_by` populated).
- MEP is read-only.

## Layers (`core/layers.py`)

Normalise by splitting on `|` and taking the last segment:

```
21-039_XREF Floor Plans - CFS|WALL-STUD-LOADBEARING  →  WALL-STUD-LOADBEARING
```

Unknown layers go to `unmapped` with counts. Never crash, never silently drop.

| Bucket | Layer names |
|--------|-------------|
| wall | `WALL`, `WALL-INTR`, `WALL-STUD`, `WALL-STUD-LOADBEARING` |
| wall_hatch (excluded) | `WALL-INSUL`, `WALL-HATCH LIGHT`, `HATCH-CONC. WALL` |
| door | `DOOR`, `DOOR-FINE`, `DOOR-HIDDEN` |
| window | `WINDOW` |
| fixture | `PLUMBING FIXTURE`, `P-SANR-FIXT`, `A-PLMG-FIXT`, `NEW-PLUMB`, `NEW-PMB-DRAINS` |
| grid | `GRID`, `ANNO-GRID` |
| column | `COLUMN` |
| stair | `STAIR`, `A-STAIRS` |
| elevator | `ELEVATOR` |
| shaft | `MECH-SHAFT` |
| clear_space | `FLOOR-CLR SPACE`, `ANNO-CLEAR SPACE` |
| room_tag | `ANNO-ROOM TAG` |
| dimension | `ANNO-DIMS` |
| furniture (excluded) | `I-FURN`, `FURNITURE`, `ID FURN`, `FUR`, `MILLWORK` |

## Classify (real)

For every page of every uploaded drawings PDF, title-block parse:

- `sheet_no` — `Drawing No:\s*([A-Z0-9.\-]+)`
- `scale` — `(\d+(?:/\d+)?"\s*=\s*\d+'-\d+")` → points per foot (72 pt/in). `1/4" = 1'-0"` → 18.0, `3/16"` → 13.5, `1/16"` → 4.5.
- `title` — first match in page order of `FLOOR PLAN | UNIT PLAN | ELEVATION | SECTION | DETAIL | SCHEDULE | ROOF | EDGE OF SLAB | SITE`

Role:

| Role | When | use |
|------|------|-----|
| unit_plan | `sheet_no` starts `A.8` **or** title contains `UNIT PLAN` | true |
| enlarged_plan | title has `FLOOR PLAN` and `pts_per_ft >= 13.0` | true |
| floor_plan | title has `FLOOR PLAN` and `pts_per_ft < 13.0` | true |
| slab_edge | title has `EDGE OF SLAB` | false |
| schedule | title has `SCHEDULE` | false |
| otherwise | derived from title keyword | false |

Text is extracted **per page**. The whole 51-page file is never loaded as one string.

On the real Sidney set, classify keeps 13 of 51 pages. Minimum viable extract set is 7: pages **8, 33–37, 51**. Page 8 is the hard one (~210k paths). Split with `qpdf src.pdf --pages . N -- p.pdf` before heavy extract — pdfplumber OOMs on the full file.

CAD sheets in this set are stored at `/Rotate 270`. Classify maps word boxes through `page.rotation_matrix` into display space, then reads the **bottom-right title block** (`Sheet Title:`, `Drawing No:`). The spec regexes run on that reconstructed text first; a full-page fallback covers simple demo PDFs. `PROOF` is not `ROOF`. `A.501c` needs a-z in the sheet-number capture; `A206` is normalised to `A.206`.

Never parse: Electrical TPS (symbols, no text tags), Hyatt BP (broken fonts), ID IFC (226MB). HVAC/Plumbing PDFs are flattened — raster overlay only. Plumbing fixtures come from the architectural drawing.

## API

Long operations return `{ "job_id" }` immediately and run in a background thread. Poll `GET /api/jobs/{job_id}` → `{ state, progress, message, error }`.

| Method | Path | Notes |
|--------|------|-------|
| POST | `/api/projects` | multipart `drawings[]`, `standards[]` → `{ project_id, documents[], job_id }` (classify job) |
| GET | `/api/projects` | list |
| GET | `/api/projects/{id}` | `project.json` |
| PATCH | `/api/projects/{id}/sheets/{sheet_id}` | `{ use, role }` user override |
| POST | `/api/projects/{id}/extract` | `{ pages: [51, …] }` or `{ pages: "auto" }` |
| GET | `/api/projects/{id}/sheets/{sheet_id}` | `sheets/<id>.json` |
| GET | `/api/projects/{id}/sheets/{sheet_id}/raster.png` | placeholder PNG from stub |
| POST | `/api/projects/{id}/model` | job → `model.json` |
| GET | `/api/projects/{id}/model` | |
| POST | `/api/projects/{id}/rules` | job → `rules.json` |
| GET | `/api/projects/{id}/rules` | |
| POST | `/api/projects/{id}/check` | job → `mismatches.json` |
| GET | `/api/projects/{id}/mismatches` | |
| POST | `/api/projects/{id}/agent` | job → `proposed_edits.json` |
| GET | `/api/projects/{id}/proposed-edits` | |
| GET | `/api/jobs/{job_id}` | |

Frontend: vanilla JS, no framework, no build, no CDN. Three tabs — Upload (drop zones + classification table + extract), Sheet (SVG, layer toggles, pan/zoom), Model (space type list + 3D placeholder). CORS is open for local dev.

## Run

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
make demo          # or: python -m plancheck.demo
make serve         # http://127.0.0.1:8000
make test
```

`make demo` generates a tiny title-block PDF, runs classify for real, then extract/model/rules/check/agent stubs, and writes a complete fake project under `plancheck/data/projects/`.

Override data dir: `PLANCHECK_DATA_DIR=/tmp/pc-data`.

## Tests

```bash
PLANCHECK_STUB_DELAY_MS=0 pytest
```

Coverage: schema round-trips of every fixture, scale parsing (`1/4"`, `3/16"`, `1/16"`), layer normalisation including the xref `|` prefix, the y-flip helper, and one end-to-end stub pipeline (classify real on a generated PDF, remaining engines stub).

## Who owns what

| Owner | Modules | Blocked by |
|-------|---------|------------|
| Scaffold (done) | `core/schemas.py`, `core/layers.py`, `core/scale.py`, `core/geometry.py`, `engines/classify.py` (real), `api/*`, `web/` shell, fixtures, tests | — |
| Akash | `engines/extract_sheet.py`, `engines/build_model.py` | nothing — start on p51 |
| Compliance | `engines/extract_rules.py`, `engines/check.py` | nothing — needs only the manual |
| Agent | `engines/agent.py` (after API/storage/jobs, which are in this scaffold) | waits on real `mismatches.json` for production quality; stub shape is already there |
| Frontend | `web/` — upload, review table, 2D SVG, then 3D | nothing — stubs return real-shaped data |
| Design | `web/css/app.css` | nothing |

Build order for extract/model: **p51 → p8 → everything else**. Scaffold stubs mean no one waits.

The unproven step in extract is turning wall segments into closed room polygons. Fallback: render walls-only to raster (furniture already excluded) and flood fill from room-tag coordinates.

## Out of scope (say on stage, do not build)

Revision diff / regression detection · brand comment-log closure · city code as another `rules.json` (zero engine changes when it happens) · cost/BOM per change · wall-constraint solving for shared walls.

Honest caveat: of 335 real Hyatt brand-review comments, only ~6 are things this catches. Most brand review is subjective interior-design taste. Lead with “this takes a person two days,” never with “nobody catches these.”
