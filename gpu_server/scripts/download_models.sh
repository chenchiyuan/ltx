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
LTX_REPO="${LTX_HF_REPO:-Lightricks/LTX-Video}"
GEMMA_REPO="${GEMMA_HF_REPO:-google/gemma-3-12b-it-qat-q4_0-unquantized}"

required_files=(
  "checkpoints/ltx-2.3-22b-dev.safetensors"
  "loras/ltxv/ltx2/ltx-2.3-22b-distilled-lora-384-1.1.safetensors"
  "text_encoders/comfy_gemma_3_12B_it.safetensors"
)

mkdir -p \
  "${MODEL_DIR}/checkpoints" \
  "${MODEL_DIR}/loras/ltxv/ltx2" \
  "${MODEL_DIR}/text_encoders"

missing=()
for file in "${required_files[@]}"; do
  if [ ! -s "${MODEL_DIR}/${file}" ]; then
    missing+=("${file}")
  fi
done

if [ "${#missing[@]}" -eq 0 ]; then
  echo "All required LTX 2.3 model files are present in ${MODEL_DIR}."
  exit 0
fi

cat <<EOF
MODEL_DIR=${MODEL_DIR}

Missing required LTX 2.3 model files:
EOF
printf '  - %s\n' "${missing[@]}"

if [ -z "${HF_TOKEN:-}" ] && [ -z "${HUGGING_FACE_HUB_TOKEN:-}" ]; then
  cat <<EOF

HF_TOKEN/HUGGING_FACE_HUB_TOKEN is not set. Set a token that has accepted the required model terms, then rerun:

  HF_TOKEN=... ./scripts/download_models.sh

EOF
  exit 1
fi

hf_token="${HF_TOKEN:-${HUGGING_FACE_HUB_TOKEN:-}}"

echo "Attempting LTX model download from ${LTX_REPO}..."
if command -v hf >/dev/null 2>&1; then
  hf download "${LTX_REPO}" \
    --local-dir "${MODEL_DIR}" \
    --include \
    "checkpoints/ltx-2.3-22b-dev.safetensors" \
    "loras/ltxv/ltx2/ltx-2.3-22b-distilled-lora-384-1.1.safetensors"
elif command -v huggingface-cli >/dev/null 2>&1; then
  huggingface-cli download "${LTX_REPO}" \
    --local-dir "${MODEL_DIR}" \
    --include \
    "checkpoints/ltx-2.3-22b-dev.safetensors" \
    "loras/ltxv/ltx2/ltx-2.3-22b-distilled-lora-384-1.1.safetensors"
else
  docker compose --env-file .env run --rm --no-deps \
    -e HF_TOKEN="${hf_token}" \
    --entrypoint hf \
    worker-0 download "${LTX_REPO}" \
    --local-dir /opt/comfyui/models \
    --include \
    "checkpoints/ltx-2.3-22b-dev.safetensors" \
    "loras/ltxv/ltx2/ltx-2.3-22b-distilled-lora-384-1.1.safetensors"
fi

cat <<EOF

Gemma text encoder is expected at:
  ${MODEL_DIR}/text_encoders/comfy_gemma_3_12B_it.safetensors

If your Hugging Face account has accepted ${GEMMA_REPO}, download or convert the Gemma checkpoint to that file name.
Rerun this script afterwards to verify the cache.
EOF

for file in "${required_files[@]}"; do
  if [ ! -s "${MODEL_DIR}/${file}" ]; then
    echo "Still missing: ${file}" >&2
    exit 1
  fi
done

echo "All required LTX 2.3 model files are present in ${MODEL_DIR}."
