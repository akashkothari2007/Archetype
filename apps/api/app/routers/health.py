from __future__ import annotations

import shutil

from fastapi import APIRouter

from app.models.building import SCHEMA_VERSION
from app.services.classifier import GENERATOR as CLASSIFIER_GENERATOR
from app.services.extractor import GENERATOR as EXTRACTOR_GENERATOR

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, object]:
    """Liveness, plus whether the real extraction toolchain is installed.

    qpdf splits pages before pdfplumber sees them and pdftoppm rasterizes for
    the flood fill. Neither is needed while the extractor is stubbed, so this
    reports rather than fails.
    """
    return {
        "status": "ok",
        "schema_version": SCHEMA_VERSION,
        "engines": {
            "classifier": CLASSIFIER_GENERATOR,
            "extractor": EXTRACTOR_GENERATOR,
        },
        "toolchain": {
            "qpdf": shutil.which("qpdf") is not None,
            "pdftoppm": shutil.which("pdftoppm") is not None,
        },
    }
