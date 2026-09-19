"""PlanCheck — deterministic ingestion of architectural drawings.

No ML, no LLM calls. Every value in the output is either read directly out of
the PDF or derived from it by arithmetic.

The central trick: these PDFs were exported from AutoCAD with optional content
groups intact, so every CAD layer survived. `page.get_drawings()` returns a
"layer" key on each path. We read what a line *is* rather than guessing from
its pixels.
"""

__version__ = "0.1.0"
