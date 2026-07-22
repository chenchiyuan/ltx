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
MGPU_GEMMA_REPO="${MGPU_GEMMA_HF_REPO:-google/gemma-3-12b-it-qat-q4_0-unquantized}"
LTX_CHECKPOINT_FILE="${LTX_CHECKPOINT_FILE:-ltx-2.3-22b-dev.safetensors}"
LTX_LORA_FILE="${LTX_LORA_FILE:-ltx-2.3-22b-distilled-lora-384-1.1.safetensors}"
LTX_SPATIAL_UPSAMPLER_FILE="${LTX_SPATIAL_UPSAMPLER_FILE:-ltx-2.3-spatial-upscaler-x2-1.1.safetensors}"
GEMMA_HF_FILE="${GEMMA_HF_FILE:-split_files/text_encoders/gemma_3_12B_it.safetensors}"
GEMMA_TARGET_FILE="${GEMMA_TARGET_FILE:-comfy_gemma_3_12B_it.safetensors}"
MGPU_GEMMA_CACHE_DIR="${MGPU_GEMMA_CACHE_DIR:-${MODEL_DIR}/gemma-3-12b-qat}"
ENABLE_MGPU_EXPERIMENTAL="${ENABLE_MGPU_EXPERIMENTAL:-false}"
WORKER_SERVICES="${WORKER_SERVICES:-worker-vip}"

fast_enabled=false
if [[ ",${WORKER_SERVICES}," == *",worker-fast-"* ]]; then
  fast_enabled=true
fi

mgpu_enabled=false
if [ "${ENABLE_MGPU_EXPERIMENTAL}" = "true" ] \
  && [[ ",${WORKER_SERVICES}," == *",worker-ultra,"* || ",${WORKER_SERVICES}," == *",worker-vip,"* ]]; then
  mgpu_enabled=true
fi

download_service=worker-fast-0
container_model_dir=/opt/comfyui/models
if [ "${mgpu_enabled}" = "true" ]; then
  download_service=worker-vip
  container_model_dir=/opt/ltx/models
fi

required_files=(
  "checkpoints/${LTX_CHECKPOINT_FILE}"
  "loras/ltxv/ltx2/${LTX_LORA_FILE}"
  "upscalers/${LTX_SPATIAL_UPSAMPLER_FILE}"
)
if [ "${fast_enabled}" = "true" ]; then
  required_files+=("text_encoders/${GEMMA_TARGET_FILE}")
fi

mkdir -p \
  "${MODEL_DIR}/checkpoints" \
  "${MODEL_DIR}/loras/ltxv/ltx2" \
  "${MODEL_DIR}/upscalers"
if [ "${fast_enabled}" = "true" ]; then
  mkdir -p "${MODEL_DIR}/text_encoders"
fi
if [ "${mgpu_enabled}" = "true" ]; then
  mkdir -p "${MGPU_GEMMA_CACHE_DIR}"
fi

missing=()
for file in "${required_files[@]}"; do
  if [ ! -s "${MODEL_DIR}/${file}" ]; then
    missing+=("${MODEL_DIR}/${file}")
  fi
done
if [ "${mgpu_enabled}" = "true" ]; then
  for file in config.json model.safetensors.index.json tokenizer.json; do
    if [ ! -s "${MGPU_GEMMA_CACHE_DIR}/${file}" ]; then
      missing+=("${MGPU_GEMMA_CACHE_DIR}/${file}")
    fi
  done
fi

if [ "${#missing[@]}" -eq 0 ]; then
  echo "All required LTX 2.3 model files are present in ${MODEL_DIR}."
  exit 0
fi

printf 'Missing required LTX 2.3 model files:\n'
printf '  - %s\n' "${missing[@]}"
if [ -z "${HF_TOKEN:-}" ] && [ -z "${HUGGING_FACE_HUB_TOKEN:-}" ]; then
  echo "HF_TOKEN/HUGGING_FACE_HUB_TOKEN is required to download missing gated models." >&2
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

  echo "Downloading ${label} from ${repo}:${file}..."
  if command -v hf >/dev/null 2>&1; then
    hf download --quiet "${repo}" "${file}" --local-dir "${host_dir}"
  elif command -v huggingface-cli >/dev/null 2>&1; then
    huggingface-cli download "${repo}" "${file}" --local-dir "${host_dir}"
  else
    docker compose --env-file .env run --rm --no-deps \
      -e HF_TOKEN -e HF_HUB_DISABLE_PROGRESS_BARS --entrypoint hf \
      "${download_service}" download --quiet "${repo}" "${file}" --local-dir "${container_dir}"
  fi
}

download_snapshot() {
  local repo="$1"
  local host_dir="$2"
  local container_dir="$3"
  local label="$4"

  echo "Downloading ${label} from ${repo}..."
  if command -v hf >/dev/null 2>&1; then
    hf download --quiet "${repo}" --local-dir "${host_dir}"
  elif command -v huggingface-cli >/dev/null 2>&1; then
    huggingface-cli download "${repo}" --local-dir "${host_dir}"
  else
    docker compose --env-file .env run --rm --no-deps \
      -e HF_TOKEN -e HF_HUB_DISABLE_PROGRESS_BARS --entrypoint hf \
      worker-vip download --quiet "${repo}" --local-dir "${container_dir}"
  fi
}

download_file "${LTX_REPO}" "${MODEL_DIR}/checkpoints" "${container_model_dir}/checkpoints" \
  "${LTX_CHECKPOINT_FILE}" "LTX 2.3 dev checkpoint"
download_file "${LTX_REPO}" "${MODEL_DIR}/loras/ltxv/ltx2" "${container_model_dir}/loras/ltxv/ltx2" \
  "${LTX_LORA_FILE}" "LTX 2.3 distilled LoRA"
download_file "${LTX_REPO}" "${MODEL_DIR}/upscalers" "${container_model_dir}/upscalers" \
  "${LTX_SPATIAL_UPSAMPLER_FILE}" "LTX 2.3 spatial upsampler"

if [ "${fast_enabled}" = "true" ]; then
  download_file "${GEMMA_REPO}" "${MODEL_DIR}/text_encoders" "/opt/comfyui/models/text_encoders" \
    "${GEMMA_HF_FILE}" "ComfyUI Gemma text encoder"
  gemma_target="${MODEL_DIR}/text_encoders/${GEMMA_TARGET_FILE}"
  if [ ! -s "${gemma_target}" ]; then
    gemma_source="$(find "${MODEL_DIR}/text_encoders" -type f -name "$(basename "${GEMMA_HF_FILE}")" -print -quit)"
    if [ -n "${gemma_source}" ]; then
      ln -sfn "${gemma_source#"${MODEL_DIR}/text_encoders/"}" "${gemma_target}"
    fi
  fi
fi

if [ "${mgpu_enabled}" = "true" ] && [ ! -s "${MGPU_GEMMA_CACHE_DIR}/model.safetensors.index.json" ]; then
  download_snapshot "${MGPU_GEMMA_REPO}" "${MGPU_GEMMA_CACHE_DIR}" \
    /opt/ltx/models/gemma-3-12b-qat "official Gemma 3 12B QAT model for LTX MGPU"
fi

for file in "${required_files[@]}"; do
  if [ ! -s "${MODEL_DIR}/${file}" ]; then
    echo "Still missing: ${MODEL_DIR}/${file}" >&2
    exit 1
  fi
done
if [ "${mgpu_enabled}" = "true" ]; then
  for file in config.json model.safetensors.index.json tokenizer.json; do
    if [ ! -s "${MGPU_GEMMA_CACHE_DIR}/${file}" ]; then
      echo "Still missing: ${MGPU_GEMMA_CACHE_DIR}/${file}" >&2
      exit 1
    fi
  done
fi

echo "All required LTX 2.3 model files are present in ${MODEL_DIR}."
