"""Point .env at a Baseten TripoSplat deployment, reusing the key already there.

Usage: python scripts/wire_splat_env.py <model_id>
"""

import sys
from pathlib import Path

ENV = Path(".env")


def set_value(lines: list[str], key: str, value: str) -> list[str]:
    out, replaced = [], False
    for raw in lines:
        if raw.strip().startswith(f"{key}=") or raw.strip().startswith(f"# {key}="):
            out.append(f"{key}={value}")
            replaced = True
        else:
            out.append(raw)
    if not replaced:
        out.append(f"{key}={value}")
    return out


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python scripts/wire_splat_env.py <model_id>")
        return 1
    model_id = sys.argv[1]
    lines = ENV.read_text(encoding="utf-8").splitlines()
    key = ""
    for raw in lines:
        if raw.strip().startswith("PLANCHECK_IMAGE_API_KEY="):
            key = raw.partition("=")[2].strip().strip('"').strip("'")
    if not key:
        print("PLANCHECK_IMAGE_API_KEY is empty in .env")
        return 1
    url = f"https://model-{model_id}.api.baseten.co/environments/production/predict"
    lines = set_value(lines, "PLANCHECK_SPLAT_URL", url)
    lines = set_value(lines, "PLANCHECK_SPLAT_API_KEY", key)
    ENV.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("PLANCHECK_SPLAT_URL ->", url)
    print("PLANCHECK_SPLAT_API_KEY -> reused the Baseten key from .env")
    return 0


if __name__ == "__main__":
    sys.exit(main())
