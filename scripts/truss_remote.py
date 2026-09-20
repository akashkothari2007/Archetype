"""Write ~/.trussrc from the Baseten key already in .env (never prints the key)."""

import os
import sys
from pathlib import Path

WANTED = "PLANCHECK_IMAGE_API_KEY"


def env_values() -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in Path(".env").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def main() -> int:
    key = env_values().get(WANTED, "")
    if not key:
        print(f"{WANTED} is empty in .env")
        return 1
    rc = Path(os.path.expanduser("~")) / ".trussrc"
    if rc.is_file() and "api_key" in rc.read_text(encoding="utf-8"):
        print("~/.trussrc already has a remote; leaving it alone")
        return 0
    rc.write_text(
        "[baseten]\nremote_provider = baseten\napi_key = "
        + key
        + "\nremote_url = https://app.baseten.co\n",
        encoding="utf-8",
    )
    print(f"wrote ~/.trussrc from {WANTED} (Hack the North workspace)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
