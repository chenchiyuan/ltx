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
LTX_REPO="${LTX_HF_REPO:-Lightricks/LTX-2.3}"
GEMMA_REPO="${GEMMA_HF_REPO:-Comfy-Org/ltx-2}"
LTX_CHECKPOINT_FILE="${LTX_CHECKPOINT_FILE:-ltx-2.3-22b-dev.safetensors}"
LTX_LORA_FILE="${LTX_LORA_FILE:-ltx-2.3-22b-distilled-lora-384-1.1.safetensors}"
GEMMA_HF_FILE="${GEMMA_HF_FILE:-split_files/text_encoders/gemma_3_12B_it.safetensors}"
GEMMA_TARGET_FILE="${GEMMA_TARGET_FILE:-comfy_gemma_3_12B_it.safetensors}"

required_files=(
  "checkpoints/${LTX_CHECKPOINT_FILE}"
  "loras/ltxv/ltx2/${LTX_LORA_FILE}"
  "text_encoders/${GEMMA_TARGET_FILE}"
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
export HF_TOKEN="${hf_token}"

download_file() {
  local repo="$1"
  local host_dir="$2"
  local container_dir="$3"
  local file="$4"
  local label="$5"

  echo "Downloading ${label} from ${repo}:${file}..."
  if command -v hf >/dev/null 2>&1; then
    HF_TOKEN="${hf_token}" hf download "${repo}" "${file}" --local-dir "${host_dir}"
  elif command -v huggingface-cli >/dev/null 2>&1; then
    HF_TOKEN="${hf_token}" huggingface-cli download "${repo}" "${file}" --local-dir "${host_dir}"
  else
    docker compose --env-file .env run --rm --no-deps \
      -e HF_TOKEN \
      --entrypoint hf \
      worker-0 download "${repo}" "${file}" --local-dir "${container_dir}"
  fi
}

download_file \
  "${LTX_REPO}" \
  "${MODEL_DIR}/checkpoints" \
  /opt/comfyui/models/checkpoints \
  "${LTX_CHECKPOINT_FILE}" \
  "LTX checkpoint"

download_file \
  "${LTX_REPO}" \
  "${MODEL_DIR}/loras/ltxv/ltx2" \
  /opt/comfyui/models/loras/ltxv/ltx2 \
  "${LTX_LORA_FILE}" \
  "LTX distilled LoRA"

download_file \
  "${GEMMA_REPO}" \
  "${MODEL_DIR}/text_encoders" \
  /opt/comfyui/models/text_encoders \
  "${GEMMA_HF_FILE}" \
  "Gemma text encoder"

gemma_target="${MODEL_DIR}/text_encoders/${GEMMA_TARGET_FILE}"
if [ ! -s "${gemma_target}" ]; then
  gemma_source="$(find "${MODEL_DIR}/text_encoders" -type f -name "$(basename "${GEMMA_HF_FILE}")" -print -quit)"
  if [ -n "${gemma_source}" ]; then
    gemma_relative="${gemma_source#"${MODEL_DIR}/text_encoders/"}"
    ln -sfn "${gemma_relative}" "${gemma_target}"
    echo "Linked ${gemma_target} -> ${gemma_relative}"
  fi
fi

cat <<EOF

Gemma text encoder is expected at:
  ${gemma_target}

The script downloads ${GEMMA_REPO}:${GEMMA_HF_FILE} and links it to the file name referenced by the current ComfyUI-LTXVideo workflow.
EOF

for file in "${required_files[@]}"; do
  if [ ! -s "${MODEL_DIR}/${file}" ]; then
    echo "Still missing: ${file}" >&2
    exit 1
  fi
done

echo "All required LTX 2.3 model files are present in ${MODEL_DIR}."
