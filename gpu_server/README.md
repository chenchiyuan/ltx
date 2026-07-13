# LTX GPU Server

`gpu_server/` is the Phase 2 deployment entrypoint for one GPU host. For the first test environment, the same machine can run both the FastAPI control plane and the GPU worker containers.

Current scope is T-204: deployment skeleton and GPU runtime validation. It starts the control plane and can start 1-8 GPU worker containers with ComfyUI installed. The worker process registers and heartbeats, but defaults to `WORKER_STATUS=unhealthy` until T-205/T-206 add real LTX workflow execution.

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
- `MODEL_DIR`: ComfyUI/LTX model cache directory
- `GPU_INDICES`: comma-separated GPU ids to start, for example `0,1,2,3,4,5,6,7`

For T-204 keep `WORKER_STATUS=unhealthy`; this prevents the dispatcher from assigning real tasks before the Worker Adapter can execute LTX workflows.

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

Expected Worker state during T-204:

- containers are running
- each worker can see its assigned GPU
- `/admin/workers` shows registered workers as `unhealthy`

Workers are intentionally not `idle` yet. T-206 will change the adapter to execute ComfyUI prompts and report real success/failure events.

## Uninstall

```bash
docker compose --env-file .env down
```

Data directories are not deleted automatically:

- `APP_DATA_DIR`
- `STORAGE_DIR`
- `MODEL_DIR`
