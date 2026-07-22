# LTX GPU Server

`gpu_server/` 是 Phase 2 的 GPU 单机部署入口。目标是：在一台 GPU 服务器上 clone 仓库后，进入本目录即可部署 control plane、Web 前端、dispatcher 和 GPU workers。

当前已跑通的拓扑是同机部署：

| 服务 | 职责 | 默认端口/资源 |
|---|---|---|
| `control-plane` | FastAPI API、任务状态机、Worker Registry、资产/usage 管理 | `8000` |
| `dispatcher` | 从 queued task 派发到可用 worker | 内部服务 |
| `web-frontend` | 内部测试前端，走 `/api/*` 反代 control plane | `WEB_PORT`, 默认 `80` |
| `worker-fast-0..3` | ComfyUI + ComfyUI-LTXVideo，单卡 fast profile | GPU `0..3` |
| `worker-vip` | LTX-2 MGPU distilled pipeline，四卡 vip profile | GPU `4,5,6,7` |

Compose 里也保留了 `worker-fast-4..7` 和 `worker-ultra` 服务模板，实际启动哪些服务由 `.env` 的 `WORKER_SERVICES` 控制。

## 目录边界

```text
gpu_server/
  .env.example              # 部署配置模板，不提交真实 .env
  docker-compose.yml        # 同机 control + web + worker 编排
  control.Dockerfile        # API/dispatcher 镜像
  Dockerfile                # ComfyUI 单卡 worker 镜像
  mgpu.Dockerfile           # LTX-2 MGPU worker 镜像
  scripts/
    deploy.sh               # 构建/启动/健康检查
    download_models.sh      # 模型下载与路径校验
    healthcheck.sh          # 本机健康检查
  worker_adapter/           # Worker 运行时、ComfyUI/MGPU 适配、输入契约处理
  config/worker.yaml        # 当前推荐 worker 布局说明
```

业务边界不要放进 ComfyUI 节点里：任务状态、重试、计量、Worker 选择在 control plane；单次推理执行、进度回调、结果写入在 worker adapter。

## 前置条件

建议机器规格：

- Ubuntu 22.04 或等价 Linux。
- NVIDIA driver 可通过 `nvidia-smi` 看到全部 GPU。
- Docker Engine + Docker Compose v2。
- NVIDIA Container Toolkit 已配置到 Docker。
- 8 卡部署建议至少 300 GB 可用磁盘。模型约 100 GB，Docker build/cache 也会吃大量空间。
- Hugging Face token 已接受相关条款：
  - `Lightricks/LTX-2.3`
  - `Comfy-Org/ltx-2`
  - `google/gemma-3-12b-it`，启用 `vip`/MGPU 时需要。

快速检查：

```bash
nvidia-smi
docker compose version
docker run --rm --gpus '"device=0"' nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi
```

## 配置

```bash
cd gpu_server
cp .env.example .env
vi .env
```

必须改的值：

| 变量 | 用途 |
|---|---|
| `BOOTSTRAP_API_KEY` | 外部 `/v1/*` API Key |
| `ADMIN_TOKEN` | `/admin/*` 和运维接口 token |
| `WORKER_TOKEN` | worker 注册、心跳、attempt event 回调 token |
| `PUBLIC_BASE_URL` | control plane 对外 URL，例如 `http://GPU_IP:8000` |
| `CONTROL_PLANE_PUBLIC_URL` | 本机脚本访问 control plane 的 URL，单机通常为 `http://127.0.0.1:8000` |
| `APP_DATA_DIR` | SQLite/control-plane 数据目录 |
| `MODEL_DIR` | ComfyUI/LTX 模型目录 |
| `STORAGE_DIR` | 输入/输出共享存储目录 |

当前推荐 8 卡混合布局：

```dotenv
WORKER_SERVICES=worker-fast-0,worker-fast-1,worker-fast-2,worker-fast-3,worker-vip
GPU_LAYOUT="fast:0;fast:1;fast:2;fast:3;vip:4,5,6,7"
ENABLE_MGPU_EXPERIMENTAL=true
WORKER_STATUS=idle
```

含义：

- `fast`：4 个单卡 ComfyUI worker，适合并发小任务。
- `vip`：1 个四卡 LTX-2 MGPU worker，适合高优先级或长任务。
- `ultra`：compose 中保留两卡模板，但当前默认不启用。

只跑单卡 worker 时：

```dotenv
WORKER_SERVICES=worker-fast-0,worker-fast-1,worker-fast-2,worker-fast-3,worker-fast-4,worker-fast-5,worker-fast-6,worker-fast-7
GPU_LAYOUT="fast:0;fast:1;fast:2;fast:3;fast:4;fast:5;fast:6;fast:7"
ENABLE_MGPU_EXPERIMENTAL=false
```

只启动 control plane、dispatcher 和 Web，不启动 GPU worker：

```bash
START_GPU_WORKERS=false ./scripts/deploy.sh
```

## 模型准备

运行前先准备模型：

```bash
HF_TOKEN=... ./scripts/download_models.sh
```

脚本会校验并下载：

| 路径 | 用途 |
|---|---|
| `${MODEL_DIR}/checkpoints/ltx-2.3-22b-dev.safetensors` | ComfyUI workflow checkpoint |
| `${MODEL_DIR}/loras/ltxv/ltx2/ltx-2.3-22b-distilled-lora-384-1.1.safetensors` | ComfyUI distilled LoRA |
| `${MODEL_DIR}/text_encoders/comfy_gemma_3_12B_it.safetensors` | ComfyUI Gemma text encoder |
| `${MODEL_DIR}/upscalers/ltx-2.3-spatial-upscaler-x2-1.1.safetensors` | LTX spatial upsampler |
| `${MGPU_DISTILLED_CACHE_DIR}/ltx-2-19b-distilled-fp8.safetensors` | vip/MGPU distilled FP8 checkpoint from `Lightricks/LTX-2` |
| `${MGPU_GEMMA_CACHE_DIR}/config.json` 等 Gemma 文件 | vip/MGPU official Gemma root |

`MGPU_DISTILLED_CACHE_DIR` 和 `MGPU_GEMMA_CACHE_DIR` 可以放在普通磁盘。当前测试机为了降低加载时间，把它们放到 `/dev/shm`，这只是性能优化，不是架构要求。

## 部署

```bash
./scripts/deploy.sh
```

脚本会做这些事：

1. 检查 `.env` 是否存在。
2. 检查 `docker`、`docker compose`、`nvidia-smi`。
3. 创建 `APP_DATA_DIR`、`MODEL_DIR`、`STORAGE_DIR`。
4. 用 `docker run --gpus` 验证 Docker GPU runtime。
5. 按 `WORKER_SERVICES` 构建并启动服务。
6. 执行 `scripts/healthcheck.sh`。

常用重启：

```bash
docker compose --env-file .env up -d --build --remove-orphans control-plane dispatcher web-frontend
docker compose --env-file .env up -d --build --remove-orphans worker-fast-0 worker-fast-1 worker-fast-2 worker-fast-3 worker-vip
```

停机：

```bash
docker compose --env-file .env down
```

默认不会删除数据目录。需要保留：

- `APP_DATA_DIR`
- `MODEL_DIR`
- `STORAGE_DIR`
- `MGPU_DISTILLED_CACHE_DIR`
- `MGPU_GEMMA_CACHE_DIR`

## 验证

本机检查：

```bash
./scripts/healthcheck.sh
docker compose --env-file .env ps
curl -s http://127.0.0.1:8000/health
```

Worker 注册检查：

```bash
curl -s \
  -H "X-Admin-Token: ${ADMIN_TOKEN}" \
  "${CONTROL_PLANE_PUBLIC_URL}/admin/workers"
```

GPU 检查：

```bash
nvidia-smi
docker compose --env-file .env logs --tail=80 worker-vip
docker compose --env-file .env logs --tail=80 worker-fast-0
```

成功状态应满足：

- `/health` 返回 `status=ok`。
- `control-plane` 为 healthy。
- `dispatcher`、`web-frontend`、配置的 worker 均为 running。
- `/admin/workers` 中 worker 状态为 `idle` 或任务运行时 `busy`。
- 提交任务后，dispatcher 将 queued task 派发给 profile 匹配的 idle worker。

## 运行机制

### 存储

单机默认使用 `local_shared`：

- control plane 通过 `LTX_STORAGE_ROOT=/data/ltx-storage` 读写资产。
- worker 通过 `STORAGE_DIR=/data/ltx-storage` 读取输入、写入输出。
- 宿主机同一个 `STORAGE_DIR` 同时挂载给 control plane 和 worker。

多机前必须切换到 MinIO/S3/OSS 等对象存储实现，业务代码仍只依赖 `ObjectStorageAdapter`。

### Worker 与 profile

调度按 `mode + profile` 匹配 worker capabilities：

- `fast` worker 的 `WORKER_PROFILES=fast`，`WORKER_EXECUTION_BACKEND=comfyui`。
- `vip` worker 的 `WORKER_PROFILES=vip`，`WORKER_EXECUTION_BACKEND=ltx_mgpu`。
- 同一个 worker 一次只接受一个 attempt。
- usage 里的 `actual_gpu_seconds` 按 `runtime_seconds * gpu_count` 记录。

### 图生视频输入契约

control plane 会随 assignment 下发 `workflow_input_contract`。当前默认要求图片输入转为 `RGB PNG`，透明通道按白底合成。ComfyUI worker 和 MGPU worker 都执行同一输入契约，避免灰度图、RGBA 图在不同后端表现不一致。

## 排障

| 现象 | 优先检查 |
|---|---|
| `CAPACITY_UNAVAILABLE` | `/admin/workers` 是否有 profile 匹配且 `idle` 的 worker |
| worker 一直 `unhealthy` | `.env` 的 `WORKER_STATUS`、模型文件、ComfyUI `/system_stats` |
| `COMFYUI_UNAVAILABLE` | `worker-fast-*` 日志、ComfyUI 是否启动、模型路径是否挂载 |
| `COMFYUI_PROMPT_FAILED` | workflow 文件、模型文件名、ComfyUI-LTXVideo/RES4LYF 节点是否加载 |
| `LTX_MGPU_FAILED` | `worker-vip` 日志、`MGPU_DISTILLED_CACHE_DIR`、`MGPU_GEMMA_CACHE_DIR`、GPU 4-7 是否空闲 |
| `IMAGE_PREPROCESS_FAILED` | 输入文件是否为有效图片，worker 会按 workflow 契约自动转 RGB |
| Docker build 空间不足 | `docker system df`，清理 build cache 或把模型/cache 放到更大磁盘 |

日志命令：

```bash
docker compose --env-file .env logs --tail=120 control-plane
docker compose --env-file .env logs --tail=120 dispatcher
docker compose --env-file .env logs --tail=120 worker-vip
```
