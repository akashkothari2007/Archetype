# PlanCheck

Upload hotel architectural drawings and a brand standards manual. PlanCheck
builds a structured model of the building, checks every room against every
extracted rule, and shows violations in 2D and 3D with the exact clause that
was broken.

> **Status: scaffolding.** The API surface, the schema and the 2D viewer are
> real. The document engine and the sheet classifier are stubs that return
> generated data. Every response says so — see `meta.generator` and
> `GET /api/health`.

## Quick start

```bash
npm run setup     # npm install + uv sync
npm run dev       # api on :8000, web on :5173
```

Open http://localhost:5173, drop in a drawing PDF, pick sheets, hit extract.

Requires Node 22+ and [uv](https://docs.astral.sh/uv/). The backend pins
Python 3.12 — the system 3.14 does not yet have wheels for the CV libraries E1
will need.

## Architecture

The JSON files are the API between engines. No engine reaches into another's
internals, so any one of them can be swapped or faked as long as it emits the
right file. That is what lets several people work at once.

```
  INPUTS                ENGINES                 OUTPUTS
  drawings.pdf    -->   E1 document      -->    building.json
  standards.pdf   -->   E2 rules         -->    rules.json
  (both above)    -->   E3 compare       -->    mismatches.json
  building.json   -->   E5 viewer        -->    2D / 3D scene
  mismatches      -->   E6 agent         -->    proposed_edits.json
```

`building.json` is the centre of the system. The 2D viewer, the 3D viewer, the
compliance check and the fix agent all read it and nothing else. Its contract
is written down twice and the two copies must be edited together:

| Contract             | TypeScript                       | Python                              |
| -------------------- | -------------------------------- | ----------------------------------- |
| `building.json`      | `packages/schemas/src/building.ts` | `apps/api/app/models/building.py` |
| sheet classification | `packages/schemas/src/sheets.ts`   | `apps/api/app/models/sheets.py`   |
| project / API        | `packages/schemas/src/project.ts`  | `apps/api/app/models/project.py`  |

### Layout

```
apps/api/                 FastAPI backend
  app/routers/            HTTP surface only, no logic
  app/services/
    classifier.py         STUB  sheet role detection from the title block
    extractor.py          STUB  E1, the document engine
    scale.py              REAL  printed scale -> points per foot
    storage.py            REAL  one directory per project on disk
  app/models/             Pydantic mirror of the shared contracts
  tests/                  contract tests, not stub-geometry tests

apps/web/                 Vite + React + TypeScript + Tailwind
  src/components/
    UploadPanel.tsx       drag and drop for the drawing set
    SheetTable.tsx        per-page verdict with a stated reason
    PlanViewer2D.tsx      SVG plan, pan / zoom / click to select
    RoomInspector.tsx     metrics, provenance, blast radius, confidence
    JsonPanel.tsx         the raw artifact, copyable and downloadable
  src/lib/plan.ts         the ONLY place the y-flip happens

packages/schemas/         shared contracts
```

## How a drawing set becomes a building

Every architectural set draws the same rooms at three zoom levels, and each
tier is good at a different job. The pipeline uses each for what it is good at:

| Tier              | Sheet     | Scale       | What it contributes            |
| ----------------- | --------- | ----------- | ------------------------------ |
| Whole floor       | `A.202`   | 1/16"=1'-0" | Room inventory, repeat counts  |
| Enlarged segments | `A.502a-e` | 3/16"=1'-0" | Dimensioned geometry           |
| Unit plans        | `A.801`   | 1/4"=1'-0"  | Highest-precision geometry     |

Geometry comes from the unit plans, counts come from the whole-floor plan. You
never take precise dimensions off a 1/16" sheet and never count units off a
unit plan.

Because one building is assembled from many sheets, **every room carries its
own provenance** (`room.source`): page, sheet number, tier and method. When two
sheets disagree about the same room, that field is how you find out which to
trust.

### API

```
GET  /api/health                      which engines are stubbed, is qpdf installed
POST /api/projects                    multipart: drawings, standards -> per-page verdict
GET  /api/projects/{id}
POST /api/projects/{id}/extract       { pages: [8,33,51] | "auto" } -> building.json
GET  /api/projects/{id}/building
```

Classification and extraction are split because they are genuinely different
steps, and because "here is what we found and here is what we are ignoring and
why" is what makes the tool feel like it read the drawings.

## Two deliberate design rules

**Confidence is a shipped, visible field.** Rooms below 0.6 render hatched and
say "needs review", with the reasons listed. Flagging our own uncertainty is a
credibility feature, not an admission.

**Assumed values are labelled everywhere they appear.** 2D plans carry no
elevation data, so wall height, wall thickness and level elevations are
rendering conventions. They live under `defaults` with `assumed: true` and are
never presented as extracted.

## Build order

1. **E1 on one validated page.** `apps/api/app/services/extractor.py`
2. **E1 on the whole-floor sheet, unchanged.** Fix what breaks, then freeze the schema.
3. **E2 rules.** Fully independent, can start immediately.
4. **E3 compare.** Trivial once 1 and 2 land. This is the first real demo.
5. **E5 3D viewer.** Can start now against the stub extractor's output.
6. **E6 agent**, then MEP markers, then nothing else.

## Before E1 can run

Not needed while the extractor is stubbed. `GET /api/health` reports both.

```bash
brew install qpdf poppler
```

`qpdf` splits a single page out before pdfplumber sees it, which is
**mandatory** — pdfplumber is OOM-killed on a full drawing file. `pdftoppm`
rasterizes for the flood fill.

## Data handling

The drawings are real client material under a Marriott brand license. `.gitignore`
hard-excludes `*.pdf`, `*.dwg`, `*.xlsx` and `apps/api/var/`. Uploads land in
`apps/api/var/projects/<id>/uploads/` and never leave the machine. **Do not
commit drawings, and do not push this repo anywhere public with drawings in it.**

## Tests

```bash
cd apps/api && uv run pytest        # 17 contract tests
cd apps/web && npm run typecheck
```

The API tests assert the *contract* — provenance present on every room,
polygons inside declared bounds, unit-type references resolving, confidence in
range. They should keep passing unchanged when the real extractor replaces the
stub.
