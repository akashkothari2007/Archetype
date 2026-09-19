"""Report Baseten model/deployment status using the key in .env (prints no secrets).

Usage: python scripts/baseten_status.py [model_id]
"""

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

API = "https://api.baseten.co/v1"


def env_values() -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in Path(".env").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def get(path: str, key: str) -> dict:
    request = urllib.request.Request(API + path, headers={"Authorization": f"Api-Key {key}"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return {"error": exc.code, "detail": exc.read().decode("utf-8", errors="replace")[:300]}


def main() -> int:
    key = env_values().get("PLANCHECK_IMAGE_API_KEY", "")
    if not key:
        print("PLANCHECK_IMAGE_API_KEY is empty in .env")
        return 1
    wanted = sys.argv[1] if len(sys.argv) > 1 else None
    models = get("/models", key)
    if "error" in models:
        print("models:", models)
        return 1
    for model in models.get("models", []):
        if wanted and model.get("id") != wanted:
            continue
        print(f"{model.get('name')}  id={model.get('id')}")
        deployments = get(f"/models/{model['id']}/deployments", key)
        for deployment in deployments.get("deployments", []):
            print(
                f"  deployment {deployment.get('id')}"
                f"  status={deployment.get('status')}"
                f"  env={deployment.get('environment')}"
                f"  active_replicas={deployment.get('active_replica_count')}"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
