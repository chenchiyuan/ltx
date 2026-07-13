# Phase 1 实现记录

⚠️ 前置门禁跳过: `review-logs/plan_review.md` 不存在，工程规划未经独立 plan review 文件验证。本轮基于用户确认的 Phase 1 边界继续实现。

⚠️ 提交限制: 当前工作目录不是 git repository，无法按 `pb-v1-implementing` 要求做逐任务 commit。

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
