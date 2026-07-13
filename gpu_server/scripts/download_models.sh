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

MODEL_DIR="${MODEL_DIR:-/opt/ltx/models}"
mkdir -p "${MODEL_DIR}"

cat <<EOF
MODEL_DIR=${MODEL_DIR}

T-204 only prepares the model cache directory.
T-205 will add pinned LTX 2.3 distilled model manifests and download/checksum logic.
EOF
