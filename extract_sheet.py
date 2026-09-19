#!/usr/bin/env python3
"""Extract one drawing page into a structured layer model.

    python extract_sheet.py <drawings.pdf> --page 51 -o sheets/A.801.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from plancheck.sheet import extract_sheet


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--page", type=int, required=True, help="1-indexed page number.")
    parser.add_argument("-o", "--out", type=Path, default=None)
    parser.add_argument(
        "--render-dir",
        type=Path,
        default=Path("renders"),
        help="Where the 150 dpi PNG is written.",
    )
    parser.add_argument("--dpi", type=int, default=150)
    parser.add_argument("--no-render", action="store_true", help="Skip the PNG.")
    args = parser.parse_args(argv)

    if not args.pdf.is_file():
        parser.error(f"No such file: {args.pdf}")

    started = time.perf_counter()
    result = extract_sheet(
        args.pdf,
        args.page,
        render_dir=None if args.no_render else args.render_dir,
        dpi=args.dpi,
    )
    elapsed = time.perf_counter() - started

    out = args.out or Path("sheets") / f"{result.sheet_id}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    # Separators matter: the default ", " adds megabytes across 30k segments.
    out.write_text(json.dumps(result.payload, separators=(",", ":")))

    print_summary(result.payload, out, elapsed)
    return 0


def print_summary(payload: dict, out: Path, elapsed: float) -> None:
    sheet = payload["sheet"]
    size_mb = out.stat().st_size / 1_048_576

    print(
        f"{payload['source']['pdf']} page {payload['source']['page']}  ->  "
        f"{sheet['sheet_no'] or '—'}  {sheet['title'] or '—'}"
    )
    print(f"  role {sheet['role']} · scale {sheet['scale'] or '—'}")

    print("\n  paths by bucket")
    for bucket, detail in payload["layers"].items():
        names = ", ".join(f"{k} {v}" for k, v in list(detail["layers"].items())[:4])
        print(f"    {bucket:<12} {detail['paths']:>7}   {names}")

    if payload["excluded"]:
        dropped = ", ".join(f"{k} {v}" for k, v in payload["excluded"].items())
        print(f"\n  excluded at extract time: {dropped}")

    if payload["unmapped"]:
        top = list(payload["unmapped"].items())[:6]
        total = sum(payload["unmapped"].values())
        print(
            f"  unmapped layers: {len(payload['unmapped'])} ({total} paths) e.g. "
            + ", ".join(f"{k} {v}" for k, v in top)
        )

    print("\n  extracted")
    counts = payload["counts"]
    for key in (
        "walls",
        "doors",
        "windows",
        "fixtures",
        "columns",
        "stairs",
        "grid_lines",
        "grid_labels",
        "room_tags",
        "dimensions",
    ):
        print(f"    {key:<12} {counts[key]:>7}")

    sources: dict[str, int] = {}
    for dim in payload["dimensions"]:
        sources[dim["source"]] = sources.get(dim["source"], 0) + 1
    if sources:
        print("    dimension sources: " + ", ".join(f"{k} {v}" for k, v in sources.items()))

    print(f"\n  wrote {out}  ({size_mb:.2f} MB) in {elapsed:.1f}s")


if __name__ == "__main__":
    sys.exit(main())
