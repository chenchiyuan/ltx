# 实现协议

## 约束来源

- `docs/iterations/ltx-video-service/architecture.md`: 模块划分、API 契约、数据模型、状态机、非功能要求。
- `docs/iterations/ltx-video-service/arch_decisions.md`: D16 明确 Phase 1 只交付非 GPU 控制面；D19 明确 Phase 2 可先用本地共享存储并保持 `ObjectStorageAdapter` 边界。
- `docs/iterations/ltx-video-service/tasks.md`: Phase 1 P0/P1 任务、Phase 2 T-201 验收标准和依赖。

## Phase 1 范围

Phase 1 只实现 web/control 节点能力：

- FastAPI API-only 接入。
- API Key 认证与资源隔离。
- ObjectStorageAdapter，默认本地文件实现，可作为 MinIO/S3 适配边界。
- Workflow Service，保存 T2V/I2V 模板、profile、source workflow 和 API Format。
- Task Service，状态机、attempt、幂等、重试、错误分类。
- QueueAdapter/Dispatcher，Phase 1 使用 Postgres/SQL 数据库领取 queued task。
- ExecutorAdapter，Phase 1 使用 mock/local executor。
- Usage Ledger，记录 task/profile/attempt/result/runtime。
- Internal Admin/Test Console 和 Admin JSON API。
- 控制面健康检查与 metrics。

Phase 1 禁止实现：

- GPU 服务器、GPU Worker、Worker Registry、ComfyUI/LTX 真实执行、Kubernetes/GPU Operator、DCGM。

## Phase 2 T-201 范围

T-201 只实现运行配置与共享存储边界：

- `Settings.storage_backend` 支持 `local_shared` 和 `minio` 配置值。
- `local_shared` 是当前可运行后端，输入图和输出视频都必须经 `ObjectStorageAdapter` 生成 `storage_uri` 并读写。
- `minio` 作为后续 T-302 生产对象存储切换的配置边界；当前 adapter 可构建，但真实运行依赖 MinIO SDK 和 MinIO 服务。
- `/health` 必须用写入型探针发现本地共享目录不可写，并返回 `storage=failed`。
- 外部 API、asset metadata 和 health detail 不得暴露本地文件系统路径。
- 存储异常发生在输出写入前时，任务不能被标记为 `succeeded`。

T-201 禁止实现：

- Worker Registry、GPU Dispatcher、GPU Worker Adapter、ComfyUI/LTX 真实执行、`gpu_server/` 部署目录。

## Phase 2 T-202 范围

T-202 只实现 Worker Registry 数据模型与内部 API：

- 新增 `gpu_nodes` 和 `gpu_workers` 数据模型。
- `POST /internal/workers/register` 使用 Worker service token 注册 Worker，并按 `worker_name` 幂等返回稳定 `worker_id`。
- `POST /internal/workers/{worker_id}/heartbeat` 更新 status、queue_depth、capabilities、current_attempt_id、metrics_url 和 last_heartbeat_at。
- `/admin/workers` 返回 Worker 列表、GPU index、状态、心跳延迟、queue_depth、当前 attempt。
- 心跳超时 Worker 标记为 `offline`，并从 `list_available_workers(...)` 中排除，供 T-203 Dispatcher 复用。
- Worker 内部 API 通过 `X-Worker-Token` 认证，缺失返回 401，错误返回 403。

T-202 禁止实现：

- queued task 派发到 GPU Worker、Worker Adapter 调用 ComfyUI、真实 GPU E2E、`gpu_server/` 部署。

## 技术栈

- Python 3.12
- FastAPI
- SQLAlchemy
- Pydantic
- pytest + FastAPI TestClient

本地实现默认使用 SQLite 与本地文件对象存储，代码边界保留 PostgreSQL/MinIO 演进能力。

## 模块到代码目录

| 模块 | 代码目录 |
|---|---|
| Edge Gateway / API Key Auth | `src/ltx_service/api.py`, `src/ltx_service/security.py` |
| Task Service / QueueAdapter | `src/ltx_service/tasks.py` |
| ExecutorAdapter mock/local | `src/ltx_service/executor.py` |
| Workflow Service | `src/ltx_service/workflows.py` |
| Asset Service / ObjectStorageAdapter | `src/ltx_service/assets.py`, `src/ltx_service/storage.py` |
| Usage Ledger | `src/ltx_service/usage.py` |
| Admin | `src/ltx_service/api.py` |
| Data Models | `src/ltx_service/models.py` |
| App Composition | `src/ltx_service/app.py` |
| Runtime Config | `src/ltx_service/config.py` |
| Worker Registry | `src/ltx_service/worker_registry.py`, `src/ltx_service/models.py`, `src/ltx_service/api.py` |

## 状态机

```mermaid
stateDiagram-v2
  [*] --> queued
  queued --> running: dispatcher claims
  running --> succeeded: executor succeeds and output asset stored
  running --> queued: retryable failure and attempts < 3
  running --> failed: non-retryable or attempts >= 3
  queued --> canceled: cancel
  running --> canceled: cancel before completion
  succeeded --> [*]
  failed --> [*]
  canceled --> [*]
```

## API 契约

External API:

- `POST /v1/assets/uploads`
- `PUT /v1/assets/{asset_id}/content`
- `GET /v1/assets/{asset_id}/content`
- `POST /v1/video-generations`
- `GET /v1/video-generations/{task_id}`
- `POST /v1/video-generations/{task_id}/cancel`
- `GET /v1/video-generations/{task_id}/result`

Internal/Admin:

- `POST /internal/dispatch/run-once`
- `POST /internal/dispatch/complete-running`
- `GET /admin`
- `GET /admin/tasks`
- `POST /admin/tasks/{task_id}/retry`
- `GET /admin/workflow-templates`
- `POST /admin/workflow-versions`
- `POST /admin/workflow-versions/{id}/test`
- `POST /admin/workflow-versions/{id}/publish`
- `POST /admin/workflow-versions/{id}/rollback`
- `GET /admin/workers`
- `GET /admin/usage`
- `GET /health`
- `GET /metrics`
- `POST /internal/workers/register`
- `POST /internal/workers/{worker_id}/heartbeat`

## 测试矩阵

| 场景 | 输入 | 预期输出 | 边界 |
|---|---|---|---|
| API Key 正常 | `Authorization: Bearer <valid>` | 允许访问 | F-001 |
| API Key 无效 | invalid bearer | 401 `AUTH_INVALID_API_KEY` | F-001 |
| 停用 Key | disabled key | 403 `AUTH_KEY_DISABLED` | F-001 |
| 创建上传槽 | filename/content_type/size | asset_id + upload_url | F-008 |
| 上传并读取资产 | PUT/GET asset content | bytes roundtrip | F-008 |
| 图生缺图 | `mode=image_to_video` no image | 422 `REQUEST_IMAGE_REQUIRED` | F-003 |
| 幂等提交 | same API key + Idempotency-Key | same task_id | F-004 |
| queued -> running -> succeeded | run-once + complete-running | status transitions and result asset | F-004/F-009 |
| cancel queued task | cancel endpoint | `canceled` status | F-004 |
| retryable failure | mock transient once | new attempt, then success | F-009 |
| invalid_input | mock invalid | failed, no retry | F-009 |
| usage ledger | completed task | profile/runtime/attempt/result recorded | F-010 |
| Admin access | valid admin token | tasks/workflows/usage visible | F-011 |
| Admin forbidden | missing token | 401/403 | F-011 |
| Health | services available | db/storage/executor healthy | F-012 |
| Metrics | tasks exist | text metrics include task counts | F-012 |
| T-201 local_shared URI boundary | local_shared backend + asset upload + output | input/output `storage_uri` uses adapter URI and does not expose local path | F-008/F-010 |
| T-201 storage health failure | local_shared root points to invalid file path | `/health` returns degraded and `storage=failed` | F-008 |
| T-201 output write failure | storage write fails before task completion | completion fails and task remains non-succeeded | F-008/F-009 |
| T-201 minio required env | `LTX_REQUIRE_ENV=true`, backend `minio`, missing MinIO vars | RuntimeError lists missing MinIO env vars | F-008 |
| T-202 worker register | 8 register payloads with valid `X-Worker-Token` | 8 stable worker records and Admin list | F-007/F-012 |
| T-202 duplicate register | same `worker_name` registered again | same `worker_id`, no duplicate available worker | F-007 |
| T-202 heartbeat | busy heartbeat with queue/current attempt | Worker status, queue_depth, capabilities, current_attempt updated | F-007/F-012 |
| T-202 stale heartbeat | last heartbeat older than timeout | Worker marked offline and unavailable | F-007 |
| T-202 worker token missing | register without `X-Worker-Token` | 401 `WORKER_TOKEN_REQUIRED` | F-007 |
| T-202 worker token invalid | register with wrong token | 403 `WORKER_FORBIDDEN` | F-007 |

## 还原检查清单

- [ ] Phase 1 不引入 GPU runtime 依赖。
- [ ] 所有 `/v1/*` API 需要 API Key。
- [ ] API Key 只存 hash。
- [ ] Task Service 通过 `ExecutorAdapter` 执行，不直接内联 mock 逻辑。
- [ ] Queue/dispatch 通过边界方法处理 queued/running。
- [ ] Object storage 通过 `ObjectStorageAdapter`。
- [ ] 输入图和输出视频的 `storage_uri` 由 `ObjectStorageAdapter.uri_for` 生成。
- [ ] `local_shared` health probe 验证目录可写，不泄露本地路径。
- [ ] `minio` 配置边界存在，缺少必要配置时快速失败并列出变量名。
- [ ] Worker Registry 数据模型包含 node、worker、capabilities、queue_depth、last_heartbeat、metrics_url。
- [ ] Worker register/heartbeat 内部 API 使用 service token。
- [ ] Admin workers 输出可用于观察 8 Worker 状态。
- [ ] Stale Worker 不会出现在可用 Worker 查询中。
- [ ] Workflow 保存 source 和 API JSON。
- [ ] Usage ledger 与 task completion 同步写入。
- [ ] Tests 覆盖正常路径和异常路径。
