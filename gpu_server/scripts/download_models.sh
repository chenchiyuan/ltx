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
MGPU_GEMMA_REPO="${MGPU_GEMMA_HF_REPO:-google/gemma-3-12b-it}"
MGPU_DISTILLED_REPO="${MGPU_DISTILLED_HF_REPO:-Lightricks/LTX-2}"
LTX_CHECKPOINT_FILE="${LTX_CHECKPOINT_FILE:-ltx-2.3-22b-dev.safetensors}"
LTX_LORA_FILE="${LTX_LORA_FILE:-ltx-2.3-22b-distilled-lora-384-1.1.safetensors}"
LTX_SPATIAL_UPSAMPLER_FILE="${LTX_SPATIAL_UPSAMPLER_FILE:-ltx-2.3-spatial-upscaler-x2-1.1.safetensors}"
GEMMA_HF_FILE="${GEMMA_HF_FILE:-split_files/text_encoders/gemma_3_12B_it.safetensors}"
GEMMA_TARGET_FILE="${GEMMA_TARGET_FILE:-comfy_gemma_3_12B_it.safetensors}"
MGPU_DISTILLED_FILE="${MGPU_DISTILLED_FILE:-ltx-2-19b-distilled-fp8.safetensors}"
MGPU_DISTILLED_CACHE_DIR="${MGPU_DISTILLED_CACHE_DIR:-${MODEL_DIR}/checkpoints}"
MGPU_GEMMA_CACHE_DIR="${MGPU_GEMMA_CACHE_DIR:-${MODEL_DIR}/gemma-3-12b-local}"
ENABLE_MGPU_EXPERIMENTAL="${ENABLE_MGPU_EXPERIMENTAL:-false}"
WORKER_SERVICES="${WORKER_SERVICES:-worker-fast-0,worker-fast-1,worker-fast-2,worker-fast-3,worker-fast-4,worker-fast-5,worker-fast-6,worker-fast-7}"

required_files=(
  "checkpoints/${LTX_CHECKPOINT_FILE}"
  "loras/ltxv/ltx2/${LTX_LORA_FILE}"
  "text_encoders/${GEMMA_TARGET_FILE}"
  "upscalers/${LTX_SPATIAL_UPSAMPLER_FILE}"
)

mkdir -p \
  "${MODEL_DIR}/checkpoints" \
  "${MODEL_DIR}/loras/ltxv/ltx2" \
  "${MODEL_DIR}/text_encoders" \
  "${MODEL_DIR}/upscalers" \
  "${MGPU_DISTILLED_CACHE_DIR}" \
  "${MGPU_GEMMA_CACHE_DIR}"

missing=()
for file in "${required_files[@]}"; do
  if [ ! -s "${MODEL_DIR}/${file}" ]; then
    missing+=("${file}")
  fi
done

mgpu_enabled=false
if [ "${ENABLE_MGPU_EXPERIMENTAL}" = "true" ] \
  && [[ ",${WORKER_SERVICES}," == *",worker-ultra,"* || ",${WORKER_SERVICES}," == *",worker-vip,"* ]]; then
  mgpu_enabled=true
fi

if [ "${mgpu_enabled}" = "true" ]; then
  if [ ! -s "${MGPU_DISTILLED_CACHE_DIR}/${MGPU_DISTILLED_FILE}" ]; then
    missing+=("${MGPU_DISTILLED_CACHE_DIR}/${MGPU_DISTILLED_FILE}")
  fi
  for file in config.json model.safetensors tokenizer.json; do
    if [ ! -s "${MGPU_GEMMA_CACHE_DIR}/${file}" ]; then
      missing+=("${MGPU_GEMMA_CACHE_DIR}/${file}")
    fi
  done
fi

if [ "${#missing[@]}" -eq 0 ]; then
  echo "All required LTX 2.3 model files are present in ${MODEL_DIR}."
  if [ "${mgpu_enabled}" = "true" ]; then
    echo "MGPU files are present in ${MGPU_DISTILLED_CACHE_DIR} and ${MGPU_GEMMA_CACHE_DIR}."
  fi
  exit 0
fi

cat <<EOF
MODEL_DIR=${MODEL_DIR}
MGPU_ENABLED=${mgpu_enabled}

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
export HF_HUB_DISABLE_PROGRESS_BARS="${HF_HUB_DISABLE_PROGRESS_BARS:-1}"

download_file() {
  local repo="$1"
  local host_dir="$2"
  local container_dir="$3"
  local file="$4"
  local label="$5"
  local compose_service="${6:-worker-fast-0}"

  echo "Downloading ${label} from ${repo}:${file}..."
  if command -v hf >/dev/null 2>&1; then
    HF_TOKEN="${hf_token}" hf download --quiet "${repo}" "${file}" --local-dir "${host_dir}"
  elif command -v huggingface-cli >/dev/null 2>&1; then
    HF_TOKEN="${hf_token}" huggingface-cli download "${repo}" "${file}" --local-dir "${host_dir}"
  else
    docker compose --env-file .env run --rm --no-deps \
      -e HF_TOKEN \
      -e HF_HUB_DISABLE_PROGRESS_BARS \
      --entrypoint hf \
      "${compose_service}" download --quiet "${repo}" "${file}" --local-dir "${container_dir}"
  fi
}

download_snapshot() {
  local repo="$1"
  local host_dir="$2"
  local container_dir="$3"
  local label="$4"
  local compose_service="${5:-worker-vip}"

  echo "Downloading ${label} from ${repo}..."
  if command -v hf >/dev/null 2>&1; then
    HF_TOKEN="${hf_token}" hf download --quiet "${repo}" --local-dir "${host_dir}"
  elif command -v huggingface-cli >/dev/null 2>&1; then
    HF_TOKEN="${hf_token}" huggingface-cli download "${repo}" --local-dir "${host_dir}"
  else
    docker compose --env-file .env run --rm --no-deps \
      -e HF_TOKEN \
      -e HF_HUB_DISABLE_PROGRESS_BARS \
      --entrypoint hf \
      "${compose_service}" download --quiet "${repo}" --local-dir "${container_dir}"
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
  "${LTX_REPO}" \
  "${MODEL_DIR}/upscalers" \
  /opt/comfyui/models/upscalers \
  "${LTX_SPATIAL_UPSAMPLER_FILE}" \
  "LTX spatial upsampler"

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

if [ "${mgpu_enabled}" = "true" ]; then
  download_file \
    "${MGPU_DISTILLED_REPO}" \
    "${MGPU_DISTILLED_CACHE_DIR}" \
    /fp8 \
    "${MGPU_DISTILLED_FILE}" \
    "LTX distilled FP8 checkpoint for MGPU" \
    worker-vip

  missing_gemma=false
  for file in config.json model.safetensors tokenizer.json; do
    if [ ! -s "${MGPU_GEMMA_CACHE_DIR}/${file}" ]; then
      missing_gemma=true
    fi
  done
  if [ "${missing_gemma}" = "true" ]; then
    download_snapshot \
      "${MGPU_GEMMA_REPO}" \
      "${MGPU_GEMMA_CACHE_DIR}" \
      /gemma \
      "Gemma 3 12B instruction model for MGPU" \
      worker-vip
  fi
fi

for file in "${required_files[@]}"; do
  if [ ! -s "${MODEL_DIR}/${file}" ]; then
    echo "Still missing: ${file}" >&2
    exit 1
  fi
done

if [ "${mgpu_enabled}" = "true" ]; then
  if [ ! -s "${MGPU_DISTILLED_CACHE_DIR}/${MGPU_DISTILLED_FILE}" ]; then
    echo "Still missing: ${MGPU_DISTILLED_CACHE_DIR}/${MGPU_DISTILLED_FILE}" >&2
    exit 1
  fi
  for file in config.json model.safetensors tokenizer.json; do
    if [ ! -s "${MGPU_GEMMA_CACHE_DIR}/${file}" ]; then
      echo "Still missing: ${MGPU_GEMMA_CACHE_DIR}/${file}" >&2
      exit 1
    fi
  done
fi

echo "All required LTX 2.3 model files are present in ${MODEL_DIR}."
if [ "${mgpu_enabled}" = "true" ]; then
  echo "MGPU files are present in ${MGPU_DISTILLED_CACHE_DIR} and ${MGPU_GEMMA_CACHE_DIR}."
fi
