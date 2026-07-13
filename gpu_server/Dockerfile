FROM nvidia/cuda:12.4.1-cudnn-devel-ubuntu22.04

ARG COMFYUI_REPO=https://github.com/comfyanonymous/ComfyUI.git
ARG COMFYUI_REF=5697b970173bc0c16a05c30d509d0911f2b84822
ARG LTXVIDEO_REPO=https://github.com/Lightricks/ComfyUI-LTXVideo.git
ARG LTXVIDEO_REF=aceeae9635f6d493f2893ba3c411a1c36031788a
ARG RES4LYF_REPO=https://github.com/ClownsharkBatwing/RES4LYF.git
ARG RES4LYF_REF=419de2d7c78f415dde9aa352a7231820ebfc17a4
ARG PYTORCH_INDEX_URL=https://download.pytorch.org/whl/cu128
ARG TORCH_VERSION=2.8.0+cu128
ARG TORCHVISION_VERSION=0.23.0+cu128
ARG TORCHAUDIO_VERSION=2.8.0+cu128

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV COMFYUI_DIR=/opt/comfyui
ENV LTX_WORKER_DIR=/opt/ltx

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        ffmpeg \
        git \
        libgl1 \
        libglib2.0-0 \
        python3 \
        python3-pip \
        python3-venv \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m pip install --no-cache-dir --upgrade pip setuptools wheel requests

RUN python3 -m pip install --no-cache-dir \
        --index-url "${PYTORCH_INDEX_URL}" \
        "torch==${TORCH_VERSION}" \
        "torchvision==${TORCHVISION_VERSION}" \
        "torchaudio==${TORCHAUDIO_VERSION}"

RUN git clone "${COMFYUI_REPO}" "${COMFYUI_DIR}" \
    && cd "${COMFYUI_DIR}" \
    && git checkout "${COMFYUI_REF}" \
    && python3 -m pip install --no-cache-dir -r requirements.txt

RUN mkdir -p "${COMFYUI_DIR}/custom_nodes" \
    && git clone "${LTXVIDEO_REPO}" "${COMFYUI_DIR}/custom_nodes/ComfyUI-LTXVideo" \
    && cd "${COMFYUI_DIR}/custom_nodes/ComfyUI-LTXVideo" \
    && git checkout "${LTXVIDEO_REF}" \
    && if [ -f requirements.txt ]; then python3 -m pip install --no-cache-dir -r requirements.txt; fi

RUN git clone "${RES4LYF_REPO}" "${COMFYUI_DIR}/custom_nodes/RES4LYF" \
    && cd "${COMFYUI_DIR}/custom_nodes/RES4LYF" \
    && git checkout "${RES4LYF_REF}" \
    && if [ -f requirements.txt ]; then python3 -m pip install --no-cache-dir -r requirements.txt; fi

COPY gpu_server/worker_adapter "${LTX_WORKER_DIR}/worker_adapter"
COPY gpu_server/scripts/container_entrypoint.sh /usr/local/bin/ltx-worker-entrypoint

RUN chmod +x /usr/local/bin/ltx-worker-entrypoint

WORKDIR /opt/ltx

ENTRYPOINT ["/usr/local/bin/ltx-worker-entrypoint"]
