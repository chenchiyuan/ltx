# LTX GPU Server

`gpu_server/` is the Phase 2 deployment entrypoint for one GPU host. For the first test environment, the same machine can run both the FastAPI control plane and the GPU worker containers.

Current scope is Phase 2 GPU execution. It starts the control plane and can start 1-8 GPU worker containers with ComfyUI installed. The worker process registers, heartbeats, exposes an internal assignment endpoint, and can call ComfyUI. Keep `WORKER_STATUS=unhealthy` until the LTX 2.3 models are present and a smoke generation has passed.

The worker image installs ComfyUI, ComfyUI-LTXVideo, and RES4LYF. RES4LYF is required by the first official LTX 2.3 workflow because it uses `ClownSampler_Beta`.

## Prerequisites

- Ubuntu 22.04
- NVIDIA driver visible through `nvidia-smi`
- Docker Engine with Compose v2
- NVIDIA Container Toolkit configured for Docker GPU containers
- At least 100 GB free local disk for model/cache growth

## Configure

```bash
cd gpu_server
cp .env.example .env
vi .env
```

Required values:

- `BOOTSTRAP_API_KEY`: external API key for `/v1/*`
- `ADMIN_TOKEN`: internal admin token
- `WORKER_TOKEN`: token used by GPU workers against `/internal/workers/*`
- `APP_DATA_DIR`: SQLite/control-plane data directory
- `STORAGE_DIR`: shared input/output asset directory
- `MODEL_DIR`: host-side ComfyUI model cache directory, mounted to `/opt/comfyui/models` in each worker
- `GPU_INDICES`: comma-separated GPU ids to start, for example `0,1,2,3,4,5,6,7`
- `WORKER_EXECUTION_BACKEND`: `comfyui` for real generation, `mock` for adapter smoke tests without models
- `WORKFLOW_PATH`: LTX 2.3 workflow source JSON to convert and submit to ComfyUI

Keep `WORKER_STATUS=unhealthy` while models are missing. Set it to `idle` only after `scripts/download_models.sh` has verified the required files and a worker can complete a smoke generation.

## Models

```bash
HF_TOKEN=... ./scripts/download_models.sh
```

The script downloads and verifies the model files referenced by the first LTX 2.3 distilled workflow:

- `checkpoints/ltx-2.3-22b-dev.safetensors`
- `loras/ltxv/ltx2/ltx-2.3-22b-distilled-lora-384-1.1.safetensors`
- `text_encoders/comfy_gemma_3_12B_it.safetensors`

By default, LTX files are fetched from `Lightricks/LTX-2.3`. The Gemma text encoder is fetched from `Comfy-Org/ltx-2` at `split_files/text_encoders/gemma_3_12B_it.safetensors`, then linked to the file name expected by the current ComfyUI-LTXVideo workflow. These files require Hugging Face authentication and accepted model terms.

## Deploy

```bash
./scripts/deploy.sh
```

To start only the control plane:

```bash
START_GPU_WORKERS=false ./scripts/deploy.sh
```

## Health Check

```bash
./scripts/healthcheck.sh
```

Expected control-plane health:

```json
{"status":"ok", "...":"..."}
```

Expected Worker state before models are ready:

- containers are running
- each worker can see its assigned GPU
- `/admin/workers` shows registered workers as `unhealthy`

Expected Worker state after models are ready and `WORKER_STATUS=idle`:

- `/admin/workers` shows idle workers with `assign_url`
- dispatching a task posts to the worker's internal `/worker/attempts`
- completed attempts call back to `/internal/attempts/{attempt_id}/events`

## Uninstall

```bash
docker compose --env-file .env down
```

Data directories are not deleted automatically:

- `APP_DATA_DIR`
- `STORAGE_DIR`
- `MODEL_DIR`
