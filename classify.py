#!/usr/bin/env python3
"""Classify every page of one or more drawing sets.

    python classify.py <drawings.pdf> [more.pdf ...] -o project.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from plancheck.classifier import DocumentInfo, classify_document, to_dict


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("pdfs", nargs="+", type=Path, help="Drawing set PDFs.")
    parser.add_argument("-o", "--out", type=Path, default=Path("project.json"))
    parser.add_argument("--quiet", action="store_true", help="Suppress the table.")
    args = parser.parse_args(argv)

    missing = [p for p in args.pdfs if not p.is_file()]
    if missing:
        parser.error(f"No such file: {', '.join(str(p) for p in missing)}")

    documents = []
    for pdf in args.pdfs:
        info = classify_document(pdf)
        documents.append(info)
        if not args.quiet:
            print_document(info)

    payload = {"schema_version": "0.1.0", "documents": [to_dict(d) for d in documents]}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2))

    usable = sum(1 for d in documents for s in d.sheets if s.use)
    total = sum(d.page_count for d in documents)
    print(f"\nWrote {args.out}  ({usable} of {total} sheets usable)")
    return 0


def print_document(info: DocumentInfo) -> None:
    print(f"\n{info.filename}")
    print(
        f"  {info.page_count} pages · {info.page_width:.0f}x{info.page_height:.0f}pt "
        f"· rotation {info.rotation} · text {'yes' if info.text_extracts else 'NO'} "
        f"· {info.ocg_count} OCGs · {info.layer_count} distinct layers"
    )

    header = f"  {'pg':>3}  {'sheet':<8} {'role':<14} {'scale':<14} {'walls':>7}  {'use':<4} title"
    print(header)
    print("  " + "-" * (len(header) - 2))
    for s in info.sheets:
        flag = "!" if s.review else " "
        print(
            f"  {s.page:>3}{flag} {s.sheet_no or '—':<8} {s.role:<14} "
            f"{s.scale or '—':<14} {s.wall_paths:>7}  {'yes' if s.use else 'no':<4} "
            f"{(s.title or '—')[:44]}"
        )

    flagged = [s for s in info.sheets if s.review]
    if flagged:
        print(f"\n  {len(flagged)} sheet(s) flagged for review:")
        for s in flagged:
            print(f"    p{s.page}: {s.review_reason}")


if __name__ == "__main__":
    sys.exit(main())
