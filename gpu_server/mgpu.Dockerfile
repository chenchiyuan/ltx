FROM nvidia/cuda:12.4.1-cudnn-devel-ubuntu22.04

ARG LTX2_REPO=https://github.com/Lightricks/LTX-2.git
ARG LTX2_REF=9377758131b1ffde4b7f766804590a6617bf2ab9
ARG PYTORCH_INDEX_URL=https://download.pytorch.org/whl/cu128
ARG TORCH_VERSION=2.8.0+cu128
ARG TORCHVISION_VERSION=0.23.0+cu128
ARG TORCHAUDIO_VERSION=2.8.0+cu128

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV LTX_WORKER_DIR=/opt/ltx
ENV LTX2_DIR=/opt/LTX-2
ENV TORCH_CUDA_ARCH_LIST=8.9

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        curl \
        ffmpeg \
        git \
        libgl1 \
        libglib2.0-0 \
        ninja-build \
        python3 \
        python3-pip \
        python3-venv \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m pip install --no-cache-dir --upgrade pip setuptools wheel requests uv_build

RUN python3 -m pip install --no-cache-dir \
        --index-url "${PYTORCH_INDEX_URL}" \
        "torch==${TORCH_VERSION}" \
        "torchvision==${TORCHVISION_VERSION}" \
        "torchaudio==${TORCHAUDIO_VERSION}"

RUN git clone "${LTX2_REPO}" "${LTX2_DIR}" \
    && cd "${LTX2_DIR}" \
    && git checkout "${LTX2_REF}" \
    && python3 -m pip install --no-cache-dir -e packages/ltx-core -e packages/ltx-pipelines \
    && TORCH_CUDA_ARCH_LIST="${TORCH_CUDA_ARCH_LIST}" \
        python3 -m pip install --no-cache-dir -e packages/ltx-kernels --no-build-isolation

COPY gpu_server/worker_adapter "${LTX_WORKER_DIR}/worker_adapter"
COPY gpu_server/scripts/container_entrypoint.sh /usr/local/bin/ltx-worker-entrypoint

RUN chmod +x /usr/local/bin/ltx-worker-entrypoint

WORKDIR /opt/ltx

ENTRYPOINT ["/usr/local/bin/ltx-worker-entrypoint"]
