# 实现记录

## Phase 1 历史记录

⚠️ Phase 1 历史说明: 当时 `review-logs/plan_review.md` 不存在，工程规划未经独立 plan review 文件验证。本轮 Phase 2 T-201 已补齐 `plan_review` PASS。

## 范围

本轮只实现 Phase 1 非 GPU 控制面：

- API-only 接入、API Key 鉴权与资源隔离。
- 资产上传/读取与本地 ObjectStorageAdapter。
- 工作流模板、版本、profile、发布和回滚。
- 异步任务、状态机、取消、attempt、重试、用量账本。
- Internal Admin、健康检查、metrics。
- mock/local ExecutorAdapter。

未实现 GPU 服务器、GPU Worker、ComfyUI/LTX 真实执行、Kubernetes/GPU Operator、DCGM。

## 本地调研结论

仓库在实现前只有架构、澄清和规划文档，没有既有服务代码可复用。实现采用当前环境已可用的 FastAPI、SQLAlchemy、Pydantic、pytest/TestClient，并以 `src/ltx_service` 建立最小服务结构。

## Phase 2 T-201 实现记录

### T-201: Phase 2 运行配置与共享存储边界

- **状态**: 已完成
- **调研结论**:
  - `src/ltx_service/config.py` 已集中管理环境变量，适合扩展 `storage_backend` 与 MinIO 配置。
  - `src/ltx_service/storage.py` 已有 `ObjectStorageAdapter` 和本地文件实现，可直接扩展 URI 生成与 health probe。
  - `assets.py` 和 `tasks.py` 是输入图/输出视频写入点，原先写死 `local://`，需要收敛到 adapter。
  - `/health` 已暴露 storage health，适合直接承载共享目录不可写探针。
- **实现文件**:
  - `src/ltx_service/config.py`
  - `src/ltx_service/storage.py`
  - `src/ltx_service/app.py`
  - `src/ltx_service/assets.py`
  - `src/ltx_service/tasks.py`
  - `tests/test_phase1_api.py`
  - `docs/iterations/ltx-video-service/implementation/protocol.md`
  - `docs/iterations/ltx-video-service/implementation/implementation.md`
- **关键决策**:
  - 新增 `storage_backend=local_shared|minio`；`local_shared` 为当前可运行后端。
  - `minio` 先作为配置和 adapter 边界，真实生产切换仍归 T-302。
  - 输入图和输出视频都通过 `ObjectStorageAdapter.uri_for(...)` 生成 storage URI，业务层不再硬编码本地路径。
  - `local_shared` health 使用写入/读取/删除探针，不在 health 响应中暴露本地目录。
- **验收覆盖**:
  - local_shared 正常路径: health ok、输入/输出 asset URI 不泄露本地路径。
  - local_shared 异常路径: root 不可写时 health degraded/storage failed。
  - 输出写入失败路径: 任务不会被标记为 succeeded。
  - MinIO 配置路径: `require_env` 下缺少 MinIO 变量会明确列出变量名。
- **遗留问题**:
  - 未连接真实 MinIO 服务；生产对象存储切换属于 T-302。
  - 未实现 GPU Worker 侧共享挂载；属于 T-204/T-207。

### T-202: Worker Registry 数据模型与内部 API

- **状态**: 已完成
- **调研结论**:
  - `api.py` 已有 Admin/internal endpoint 组织方式，可直接增加 Worker internal endpoints。
  - `dependencies.py` 已有 header token 认证模式，可复用为 `X-Worker-Token`。
  - `models.py` 使用 SQLAlchemy declarative model 和 `Base.metadata.create_all`，新增 `gpu_nodes`/`gpu_workers` 不需要额外迁移脚本即可在新环境创建。
  - `tests/test_phase1_api.py` 已有 TestClient fixture 和 Admin header 模式，可直接覆盖 register/heartbeat/Admin 列表。
- **实现文件**:
  - `src/ltx_service/config.py`
  - `src/ltx_service/dependencies.py`
  - `src/ltx_service/app.py`
  - `src/ltx_service/models.py`
  - `src/ltx_service/schemas.py`
  - `src/ltx_service/worker_registry.py`
  - `src/ltx_service/api.py`
  - `tests/test_phase1_api.py`
  - `docs/iterations/ltx-video-service/implementation/protocol.md`
  - `docs/iterations/ltx-video-service/implementation/implementation.md`
- **关键决策**:
  - 新增 `LTX_WORKER_TOKEN`，Worker 内部 API 使用 `X-Worker-Token`，与 Admin token 分离。
  - Worker 注册按 `worker_name` 幂等，重复注册返回稳定 `worker_id`。
  - 心跳超时阈值为 600 秒；超时 Worker 标记 `offline`，并从 `list_available_workers(...)` 结果中排除。
  - `/admin/workers` 在没有 Worker 时保持 Phase 1 兼容；有 Worker 后进入 `phase-2-worker-registry` 展示。
- **验收覆盖**:
  - 8 Worker 注册与 Admin 列表展示。
  - 重复注册同一 `worker_name` 不创建重复可用 Worker。
  - heartbeat 更新 status、queue_depth、capabilities、current_attempt_id。
  - stale Worker 标记 offline 并从可用列表排除。
  - Worker token 缺失/错误分别返回 401/403。
- **遗留问题**:
  - Dispatcher 尚未使用 `list_available_workers(...)` 派发任务；属于 T-203。
  - `gpu_server/` Worker 进程尚未实现注册调用；属于 T-204/T-207。

### T-203: GPU Dispatcher 与 ExecutorAdapter 派发改造

- **状态**: 已完成
- **调研结论**:
  - `tasks.py` 已集中处理 queued/running/attempt 状态，适合在同一边界内加入 gpu-worker dispatch 分支。
  - `executor.py` 已有 `ExecutorAdapter` 和 `MockLocalExecutor`，可扩展 `GpuWorkerExecutor.assign(...)` 边界而不改变 Phase 1 mock 执行。
  - `worker_registry.py` 已提供 `list_available_workers(...)`，可直接复用 capability 匹配和 stale worker 摘除逻辑。
  - `api.py` 的 `/internal/dispatch/run-once` 是现有派发入口，保持 `dispatched` 字段兼容即可。
- **实现文件**:
  - `src/ltx_service/config.py`
  - `src/ltx_service/executor.py`
  - `src/ltx_service/app.py`
  - `src/ltx_service/database.py`
  - `src/ltx_service/models.py`
  - `src/ltx_service/tasks.py`
  - `src/ltx_service/api.py`
  - `tests/test_phase1_api.py`
  - `docs/iterations/ltx-video-service/implementation/protocol.md`
  - `docs/iterations/ltx-video-service/implementation/implementation.md`
- **关键决策**:
  - 新增 `LTX_EXECUTOR_BACKEND=mock-local|gpu-worker`，默认保持 `mock-local`。
  - `gpu-worker` 首版实现 async assignment 边界，不做真实 HTTP Worker Adapter 调用；真实调用归 T-206。
  - `DispatchOutcome` 保留 API 兼容的 `dispatched` 字段，并补充 reason、attempt_id、worker_id。
  - `task_attempts.worker_id` 是 nullable 字段；为已有 SQLite 表增加最小兼容迁移。
  - `/internal/dispatch/complete-running` 只完成 `mock-local` attempt，避免误终止等待 Worker event 的 gpu-worker attempt。
- **验收覆盖**:
  - gpu-worker 无可用 Worker 时 task 保持 queued，`CAPACITY_UNAVAILABLE` 在 Admin/Metrics 可见。
  - mixed profiles 下只选择 capabilities 匹配的 idle Worker。
  - 派发成功后 attempt 记录 worker_id，Worker 进入 busy/current_attempt 状态。
  - 同一 task 已转出 queued 后，重复 dispatch 不创建第二个 attempt。
  - gpu-worker running attempt 调用 mock complete endpoint 时保持 running。
  - assign retryable failure 重新 queued；non-retryable failure 进入 failed 并记录 usage。
  - 旧 SQLite `task_attempts` 表缺少 `worker_id` 时启动会补列。
- **遗留问题**:
  - `GpuWorkerExecutor.assign(...)` 仍是控制面边界实现，不调用真实 Worker Adapter HTTP；属于 T-206。
  - Worker events 回调和真实 GPU completion 尚未实现；属于 T-206/T-209。

### T-204: `gpu_server/` 部署子项目骨架

- **状态**: 已完成
- **调研结论**:
  - 仓库已有 FastAPI control plane 启动入口，可用 `control.Dockerfile` 在 GPU 服务器同机部署。
  - Phase 2 规划要求 GPU 部署入口独立在 `gpu_server/`，不能把 GPU 脚本散落到根目录。
  - 目标测试机 `162.62.55.111` 是 Ubuntu 22.04，8 张 NVIDIA L20 46GB，Docker/Compose 已安装，但需验证 Docker GPU runtime。
  - ComfyUI 当前 HEAD 固定为 `5697b970173bc0c16a05c30d509d0911f2b84822`；ComfyUI-LTXVideo 当前 master 固定为 `aceeae9635f6d493f2893ba3c411a1c36031788a`。
- **实现文件**:
  - `gpu_server/README.md`
  - `gpu_server/.env.example`
  - `gpu_server/control.Dockerfile`
  - `gpu_server/Dockerfile`
  - `gpu_server/docker-compose.yml`
  - `gpu_server/scripts/deploy.sh`
  - `gpu_server/scripts/healthcheck.sh`
  - `gpu_server/scripts/download_models.sh`
  - `gpu_server/scripts/container_entrypoint.sh`
  - `gpu_server/worker_adapter/runtime.py`
  - `gpu_server/config/worker.yaml`
  - `gpu_server/workflows/README.md`
  - `tests/test_gpu_server_project.py`
- **关键决策**:
  - Compose 同时定义 `control-plane` 和 `worker-0` 到 `worker-7`，满足“同一台机器既对外提供接口，也是 GPU 服务器”的测试部署形态。
  - Worker service 使用 Docker device reservation，每个 Worker 固定唯一 `device_ids`，保持单任务单卡的容量单位。
  - 显式安装 `torch==2.8.0+cu128`、`torchvision==0.23.0+cu128`、`torchaudio==2.8.0+cu128`，避免 ComfyUI 在 2026 当前解析到 CUDA 13 wheel 后与 NVIDIA 575/CUDA 12.9 驱动不兼容。
  - T-204 的 Worker Adapter 只做 register/heartbeat 骨架，默认 `WORKER_STATUS=unhealthy`，避免真实 LTX 执行未完成前被 Dispatcher 派发任务。
  - `deploy.sh` 在启动 Worker 前执行 `docker run --rm --gpus`，如果 NVIDIA Container Toolkit 未配置会快速失败。
  - `download_models.sh` 当前只创建模型目录并输出 T-205 提示，不伪造模型下载清单。
- **验收覆盖**:
  - `gpu_server/` 必需文件存在。
  - `.env.example` 包含 Phase 2 部署契约变量。
  - GPU Dockerfile 固定 ComfyUI/ComfyUI-LTXVideo 40 位 commit。
  - Compose 定义 8 个单 GPU Worker，并与 GPU index 一一对应。
  - 部署/健康脚本包含 GPU 可见性和 Docker GPU runtime fail-fast 检查。
- **远端部署验证**:
  - 目标机器: `162.62.55.111`, Ubuntu 22.04, 8 x NVIDIA L20, driver `575.51.03`, CUDA runtime `12.9`。
  - 部署目录: `~/projects/ltx/gpu_server`。
  - 已安装并配置 NVIDIA Container Toolkit，`docker run --rm --gpus 'device=0' nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi` 通过。
  - 同机启动 `control-plane` 和 `worker-0` 到 `worker-7`，`docker compose ps` 显示 control-plane healthy、8 个 worker running。
  - `./scripts/healthcheck.sh` 返回 `/health` ok、executor `gpu-worker` healthy、`worker_count=8`。
  - Admin workers 查询显示 8 个 worker 均已注册，且 capabilities 中 `comfyui_healthy=true`。
  - `worker-0` 日志确认 ComfyUI 启动、ComfyUI-LTXVideo 自定义节点导入成功、容器内识别 `NVIDIA L20` 和 `torch 2.8.0+cu128`。
  - `worker-0` 容器内 `nvidia-smi -L` 可见单张 `GPU 0: NVIDIA L20`，符合单 Worker 单卡绑定。
- **远端残余风险**:
  - 服务器内访问 `127.0.0.1:8000/health` 正常，`0.0.0.0:8000` 已监听且 `ufw` inactive；但从本机访问 `http://162.62.55.111:8000/health` 未进入 uvicorn access log，需要在云安全组/公网入口放通 TCP 8000，或后续改成 80/443 反向代理。
  - 8 个 Worker 当前故意保持 `WORKER_STATUS=unhealthy`，`not_ready_reason=T204_ADAPTER_SKELETON`，避免真实 LTX 执行链路未完成前接收任务。
- **遗留问题**:
  - 真实 LTX 2.3 workflow 与模型缓存下载属于 T-205。
  - Worker Adapter 调用 ComfyUI `/prompt`、轮询 history、回传结果属于 T-206。
  - Worker 注册为 `idle` 并可承接任务属于 T-207/T-209 验收。

### T-205: LTX 2.3 distilled single-stage workflow 与模型缓存

- **状态**: 已完成模型缓存边界和 workflow 转换准备；真实模型下载待 HF token/模型条款满足后验收
- **调研结论**:
  - 官方 ComfyUI-LTXVideo 2.3 workflow 位于 `example_workflows/2.3/`，首个单阶段文件为 `LTX-2.3_T2V_I2V_Single_Stage_Distilled_Full.json`。
  - 官方 workflow 是 ComfyUI save-format，不是 `/prompt` 可直接提交的 API Format；Worker 必须基于 `/object_info` 转换。
  - workflow 引用的首批模型文件包括 `ltx-2.3-22b-dev.safetensors`、`ltx-2.3-22b-distilled-lora-384-1.1.safetensors` 和 `comfy_gemma_3_12B_it.safetensors`。
  - ComfyUI 默认从 `/opt/comfyui/models` 查找模型，原先挂载到 `/models/ltx` 会导致真实执行找不到模型。
- **实现文件**:
  - `gpu_server/docker-compose.yml`
  - `gpu_server/scripts/download_models.sh`
  - `gpu_server/worker_adapter/comfyui.py`
  - `gpu_server/.env.example`
  - `gpu_server/README.md`
- **关键决策**:
  - `MODEL_DIR` host 目录挂载到容器内 `/opt/comfyui/models`，直接复用 ComfyUI 默认模型发现路径。
  - `download_models.sh` 先做缺失清单和 HF token 检查；Gemma gated 模型不伪造自动成功。
  - Worker 在运行时读取官方 save-format workflow，并用 `/object_info` 转为 API Format，减少手写节点 JSON 漂移。
- **遗留问题**:
  - 真实模型文件尚未在远端下载完成；Gemma 可能需要 Hugging Face token 和 license acceptance。
  - 真实 T2V/I2V 生成质量和耗时需要 T-209 smoke/e2e 实测。

### T-206: GPU Worker Adapter 接入 ComfyUI API

- **状态**: 已完成执行边界、事件回调和本地可测成功路径；真实 ComfyUI 生成待模型到位后验收
- **调研结论**:
  - 现有 `GpuWorkerExecutor.assign(...)` 只在控制面内返回 accepted，无法证明 Worker 可观测或可执行。
  - `Task Service` 已有 attempt 状态机和 usage ledger，适合新增 Worker event 回调作为 GPU task 唯一完成路径。
  - 单机 compose 网络内 control-plane 可通过 service name 访问 `worker-N:9000`，不需要暴露 worker 端口到公网。
- **实现文件**:
  - `src/ltx_service/executor.py`
  - `src/ltx_service/tasks.py`
  - `src/ltx_service/api.py`
  - `src/ltx_service/schemas.py`
  - `gpu_server/worker_adapter/runtime.py`
  - `gpu_server/worker_adapter/comfyui.py`
  - `gpu_server/worker_adapter/storage.py`
  - `gpu_server/docker-compose.yml`
  - `tests/test_phase1_api.py`
- **关键决策**:
  - Worker capabilities 增加 `assign_url`，Dispatcher 派发 attempt 时同步 POST 到 worker 内部 `/worker/attempts`。
  - assignment payload 包含输入资产 URI 和预分配输出 URI，Worker 负责写共享存储，Control plane 负责登记资产与 usage。
  - 新增 `/internal/attempts/{attempt_id}/events`，Worker 通过 service token 回传 progress/succeeded/failed。
  - Worker Adapter 默认 `WORKER_EXECUTION_BACKEND=comfyui`，同时保留 `mock` 用于无模型环境的 adapter smoke test。
  - `/internal/dispatch/complete-running` 继续只服务 mock-local，GPU task 不能被控制面同步完成。
- **验收覆盖**:
  - `python3 -m pytest` 覆盖 assignment HTTP payload、worker succeeded event、output asset、usage 和 worker 释放。
  - `python3 -m compileall -q src tests gpu_server/worker_adapter` 通过。
  - `docker compose --env-file /private/tmp/ltx-gpu.env -f gpu_server/docker-compose.yml config --quiet` 通过。
- **遗留问题**:
  - 真实 ComfyUI `/prompt` smoke 尚未执行，依赖模型下载和 Worker 从 `unhealthy` 切换为 `idle`。
  - WebSocket 细粒度进度和 GPU 指标属于 T-208。

## Task 还原

### T-001: Phase 1 环境边界与配置基线

- **状态**: 已完成
- **实现文件**:
  - `src/ltx_service/config.py`
  - `src/ltx_service/app.py`
  - `pyproject.toml`
- **关键决策**: 默认本地 SQLite + 本地对象存储，保留 `LTX_DATABASE_URL` 和 `LTX_STORAGE_ROOT` 作为替换边界。
- **遗留问题**: PostgreSQL/MinIO 运行态未在本机验收。

### T-003: 数据库与对象存储测试底座

- **状态**: 已完成
- **实现文件**:
  - `src/ltx_service/database.py`
  - `src/ltx_service/models.py`
  - `src/ltx_service/storage.py`
- **关键决策**: 所有资产读写经 `ObjectStorageAdapter`，Phase 1 默认 `LocalObjectStorage`。

### T-004: API 服务骨架与 API Key 认证

- **状态**: 已完成
- **实现文件**:
  - `src/ltx_service/api.py`
  - `src/ltx_service/security.py`
  - `src/ltx_service/dependencies.py`
  - `src/ltx_service/errors.py`
- **关键决策**: API Key 只存 SHA-256 hash；所有 `/v1/*` 外部接口走 Bearer 鉴权。

### T-005: 资产上传与结果访问 API

- **状态**: 已完成
- **实现文件**:
  - `src/ltx_service/assets.py`
  - `src/ltx_service/storage.py`
  - `src/ltx_service/api.py`
- **关键决策**: Phase 1 通过后端 URL 代理上传/下载，保持对象存储凭据不外露。

### T-006: LTX 工作流模板与版本服务

- **状态**: 已完成
- **实现文件**:
  - `src/ltx_service/bootstrap.py`
  - `src/ltx_service/workflows.py`
  - `src/ltx_service/models.py`
- **关键决策**: 内置 text_to_video/image_to_video 模板；新建 workflow version 时复制上一版 profile，避免发布后 profile 缺失。

### T-007: 任务 API 与状态机

- **状态**: 已完成
- **实现文件**:
  - `src/ltx_service/tasks.py`
  - `src/ltx_service/executor.py`
  - `src/ltx_service/schemas.py`
  - `src/ltx_service/api.py`
- **关键决策**: Dispatcher 通过 SQL 状态领取 queued 任务；Task Service 只依赖 `ExecutorAdapter`。

### T-010: 重试、attempt 与用量账本

- **状态**: 已完成
- **实现文件**:
  - `src/ltx_service/tasks.py`
  - `src/ltx_service/usage.py`
  - `src/ltx_service/executor.py`
- **关键决策**: retryable failure 在 attempt < 3 时回到 queued；invalid_input 不自动重试；usage ledger 与终态更新同事务提交。

### T-011: 内部管理 Web/Admin

- **状态**: 已完成
- **实现文件**:
  - `src/ltx_service/api.py`
  - `src/ltx_service/usage.py`
- **关键决策**: Phase 1 Admin 与 API 同进程部署，提供 HTML 首页和 JSON 管理接口。

### T-012: Phase 1 控制面可观测性与健康检查

- **状态**: 已完成
- **实现文件**:
  - `src/ltx_service/api.py`
  - `src/ltx_service/storage.py`
  - `src/ltx_service/executor.py`
- **关键决策**: `/health` 区分 web/database/storage/executor；`/metrics` 暴露任务状态、attempt、失败原因、平均 mock runtime、成功率。

### T-013: Phase 1 端到端验收与失败演练

- **状态**: 已完成
- **实现文件**:
  - `tests/test_phase1_api.py`
- **覆盖路径**: 文生、图生、幂等、取消、retryable failure、invalid_input、Admin、usage、metrics、权限错误。

### T-014: API 调用说明与示例脚本

- **状态**: 已完成
- **实现文件**:
  - `docs/iterations/ltx-video-service/api_examples.md`

### T-015: Phase 1 部署 Runbook

- **状态**: 已完成
- **实现文件**:
  - `docs/iterations/ltx-video-service/runbook_phase1.md`

## 验证

```bash
python3 -m pytest
```

结果: `9 passed in 0.60s`

```bash
python3 -m compileall -q src tests
```

结果: 通过，无输出。

```bash
curl -s http://127.0.0.1:8000/health
```

结果: `status=ok`，database/storage/executor 均为 ok。

## 残余风险

- 本机验证使用 SQLite + LocalObjectStorage；PostgreSQL/MinIO 需要在目标测试机做部署验证。
- mock/local executor 只验证控制面契约；真实 ComfyUI/LTX 执行属于 Phase 2。
- 当前目录不是 git 仓库，无法提供逐任务 commit 历史。
