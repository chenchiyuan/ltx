#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GPU_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${GPU_DIR}"

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

CONTROL_PLANE_PUBLIC_URL="${CONTROL_PLANE_PUBLIC_URL:-http://127.0.0.1:8000}"
ADMIN_TOKEN="${ADMIN_TOKEN:-}"

nvidia-smi -L >/dev/null
docker compose --env-file .env ps

python3 - <<PY
import json
import sys
import urllib.request

base_url = "${CONTROL_PLANE_PUBLIC_URL}".rstrip("/")
try:
    with urllib.request.urlopen(base_url + "/health", timeout=10) as response:
        body = response.read().decode()
except Exception as exc:
    raise SystemExit(f"control-plane health failed: {exc}")

print(body)
payload = json.loads(body)
if payload.get("status") not in {"ok", "degraded"}:
    raise SystemExit("control-plane health returned unexpected status")
PY

if [ -n "${ADMIN_TOKEN}" ]; then
  python3 - <<PY
import json
import urllib.request

base_url = "${CONTROL_PLANE_PUBLIC_URL}".rstrip("/")
request = urllib.request.Request(
    base_url + "/admin/workers",
    headers={"X-Admin-Token": "${ADMIN_TOKEN}"},
)
with urllib.request.urlopen(request, timeout=10) as response:
    payload = json.loads(response.read().decode())
print(json.dumps({"worker_count": len(payload.get("workers", []))}, ensure_ascii=False))
PY
fi
