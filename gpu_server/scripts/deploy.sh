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

services=(control-plane)
if [ "${START_GPU_WORKERS:-true}" = "true" ]; then
  IFS=',' read -r -a gpu_indices <<< "${GPU_INDICES:-0,1,2,3,4,5,6,7}"
  for gpu_index in "${gpu_indices[@]}"; do
    services+=("worker-${gpu_index}")
  done
fi

docker compose --env-file .env up -d --build "${services[@]}"
./scripts/healthcheck.sh
