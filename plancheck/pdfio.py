"""PDF I/O: page splitting, rendering, and positioned text.

pdfplumber is OOM-killed (exit 137) opening the full 51-page file, so every
pdfplumber call goes through a single-page split made by qpdf. PyMuPDF handles
the full document without trouble and is used wherever a split would be waste.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pymupdf

from . import geometry


class ToolMissing(RuntimeError):
    """A required external binary is not on PATH."""


def require(tool: str, install_hint: str) -> str:
    path = shutil.which(tool)
    if path is None:
        raise ToolMissing(f"{tool!r} not found on PATH. Install it with: {install_hint}")
    return path


@contextmanager
def split_page(src: Path, page: int, keep_dir: Path | None = None) -> Iterator[Path]:
    """Yield a one-page PDF extracted by qpdf. `page` is 1-based.

    Required because pdfplumber cannot open the full set. Deleted on exit
    unless `keep_dir` is given.
    """
    qpdf = require("qpdf", "brew install qpdf")
    target_dir = keep_dir or Path(tempfile.mkdtemp(prefix="plancheck-"))
    target_dir.mkdir(parents=True, exist_ok=True)
    out = target_dir / f"page_{page}.pdf"

    result = subprocess.run(
        [qpdf, str(src), "--pages", ".", str(page), "--", str(out)],
        capture_output=True,
        text=True,
    )
    # qpdf returns 3 for recoverable warnings and still writes valid output.
    if result.returncode not in (0, 3) or not out.is_file():
        raise RuntimeError(f"qpdf failed to split page {page}: {result.stderr.strip()}")

    try:
        yield out
    finally:
        if keep_dir is None:
            shutil.rmtree(target_dir, ignore_errors=True)


def render_png(src: Path, page: int, out_path: Path, dpi: int = 150) -> Path:
    """Render one page to PNG, preferring pdftoppm and falling back to PyMuPDF."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pdftoppm = shutil.which("pdftoppm")

    if pdftoppm is not None:
        stem = out_path.with_suffix("")
        result = subprocess.run(
            [pdftoppm, "-png", "-r", str(dpi), "-f", str(page), "-l", str(page),
             "-singlefile", str(src), str(stem)],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and out_path.is_file():
            return out_path

    with pymupdf.open(src) as doc:
        pix = doc[page - 1].get_pixmap(dpi=dpi)
        pix.save(out_path)
    return out_path


def plumber_words(page_pdf: Path) -> list[dict]:
    """Positioned words from a single-page PDF via pdfplumber.

    Coordinates stay in pdfplumber's own space (y-down from the top-left);
    the caller flips them once through PageTransform.
    """
    import pdfplumber

    with pdfplumber.open(page_pdf) as pdf:
        return pdf.pages[0].extract_words(
            use_text_flow=False,
            keep_blank_chars=False,
            extra_attrs=["size"],
        )


def words_display(page_pdf: Path, tf: geometry.PageTransform) -> list[dict]:
    """pdfplumber words converted to output space, with a centre precomputed."""
    out = []
    for w in plumber_words(page_pdf):
        y0 = tf.flip_top(w["bottom"])
        y1 = tf.flip_top(w["top"])
        bbox = [round(w["x0"], 3), y0, round(w["x1"], 3), y1]
        out.append(
            {
                "text": w["text"],
                "bbox": bbox,
                "centre": geometry.centre_of(bbox),
                "size": round(float(w.get("size", 0.0)), 2),
            }
        )
    return out


def pymupdf_words_display(page: pymupdf.Page) -> list[dict]:
    """Positioned words straight from PyMuPDF, in output space.

    Classification reads every page of every document, and splitting 51 pages
    with qpdf just to count words costs far more than it returns. Extraction,
    which needs pdfplumber's tighter word grouping, uses `words_display`.
    """
    tf = geometry.PageTransform.for_page(page)
    out = []
    for x0, y0, x1, y1, text, *_ in page.get_text("words"):
        bbox = tf.bbox(pymupdf.Rect(x0, y0, x1, y1))
        out.append(
            {
                "text": text,
                "bbox": bbox,
                "centre": geometry.centre_of(bbox),
                "size": 0.0,
            }
        )
    return out


def document_layers(doc: pymupdf.Document) -> list[str]:
    """Every optional content group name in the document, normalised."""
    from . import layers as layer_map

    names = set()
    for ocg in (doc.get_ocgs() or {}).values():
        name = ocg.get("name")
        if name:
            names.add(layer_map.normalise(name))
    return sorted(names)
