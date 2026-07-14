#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GPU_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${GPU_DIR}"

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created gpu_server/.env from .env.example. Edit secrets before running again." >&2
  exit 1
fi

set -a
# shellcheck disable=SC1091
. ./.env
set +a

for command_name in docker nvidia-smi; do
  if ! command -v "${command_name}" >/dev/null 2>&1; then
    echo "Missing required command: ${command_name}" >&2
    exit 1
  fi
done

if ! docker compose version >/dev/null 2>&1; then
  echo "Docker Compose v2 is required." >&2
  exit 1
fi

mkdir -p "${APP_DATA_DIR:?APP_DATA_DIR is required}" "${MODEL_DIR:?MODEL_DIR is required}" "${STORAGE_DIR:?STORAGE_DIR is required}"

if [ "${START_GPU_WORKERS:-true}" = "true" ]; then
  if ! docker run --rm --gpus '"device=0"' nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi >/dev/null; then
    echo "Docker cannot run GPU containers. Install/configure NVIDIA Container Toolkit first." >&2
    exit 1
  fi
fi

services=(control-plane dispatcher web-frontend)
skipped_worker_names=()
if [ "${START_GPU_WORKERS:-true}" = "true" ]; then
  IFS=',' read -r -a worker_services <<< "${WORKER_SERVICES:-worker-fast-0,worker-fast-1,worker-fast-2,worker-fast-3,worker-fast-4,worker-fast-5,worker-fast-6,worker-fast-7}"
  for worker_service in "${worker_services[@]}"; do
    if [[ "${worker_service}" =~ ^worker-(ultra|vip)$ && "${ENABLE_MGPU_EXPERIMENTAL:-false}" != "true" ]]; then
      echo "Skipping ${worker_service}; set ENABLE_MGPU_EXPERIMENTAL=true only after MGPU E2E validation." >&2
      skipped_worker_names+=("ltx-${worker_service}")
      continue
    fi
    services+=("${worker_service}")
  done
fi

docker compose --env-file .env up -d --build --remove-orphans "${services[@]}"

if [ "${#skipped_worker_names[@]}" -gt 0 ]; then
  skipped_csv="$(IFS=,; echo "${skipped_worker_names[*]}")"
  SKIPPED_WORKER_NAMES="${skipped_csv}" python3 - <<'PY'
import json
import os
import urllib.request

base_url = os.environ.get("CONTROL_PLANE_PUBLIC_URL", "http://127.0.0.1:8000").rstrip("/")
admin_token = os.environ["ADMIN_TOKEN"]
worker_token = os.environ["WORKER_TOKEN"]
skipped = set(filter(None, os.environ.get("SKIPPED_WORKER_NAMES", "").split(",")))

request = urllib.request.Request(
    base_url + "/admin/workers",
    headers={"X-Admin-Token": admin_token},
)
with urllib.request.urlopen(request, timeout=10) as response:
    workers = json.loads(response.read().decode()).get("workers", [])

for worker in workers:
    if worker.get("worker_name") not in skipped:
        continue
    payload = json.dumps({"status": "offline", "queue_depth": 0}).encode()
    heartbeat = urllib.request.Request(
        base_url + f"/internal/workers/{worker['worker_id']}/heartbeat",
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json", "X-Worker-Token": worker_token},
    )
    urllib.request.urlopen(heartbeat, timeout=10).read()
    print(f"Marked skipped worker offline: {worker['worker_name']}")
PY
fi

./scripts/healthcheck.sh
