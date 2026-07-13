# Phase 1 本地 Runbook

## 范围

本 Runbook 只覆盖非 GPU web/control 节点：FastAPI、SQLite/PostgreSQL 兼容数据库边界、本地 ObjectStorageAdapter、Admin、mock/local executor。不启动 GPU、ComfyUI、Kubernetes 或 Worker Registry。

## 启动

```bash
export PYTHONPATH=src
export LTX_DATABASE_URL="sqlite:///./.data/ltx.db"
export LTX_STORAGE_ROOT="./.data/object-storage"
export LTX_BOOTSTRAP_API_KEY="<dev-api-key>"
export LTX_ADMIN_TOKEN="<dev-admin-token>"
python3 -m uvicorn ltx_service.app:app --host 0.0.0.0 --port 8000
```

## Smoke Test

```bash
python3 -m pytest tests/test_phase1_api.py -q
```

预期输出：

```text
9 passed
```

## 健康检查

```bash
curl -sS http://127.0.0.1:8000/health
curl -sS http://127.0.0.1:8000/metrics
```

健康状态应显示 `database=ok`、`storage=ok`、`executor.executor_type=mock-local`。

## Admin

```bash
curl -sS http://127.0.0.1:8000/admin/tasks \
  -H "X-Admin-Token: $LTX_ADMIN_TOKEN"

curl -sS http://127.0.0.1:8000/admin/workflow-templates \
  -H "X-Admin-Token: $LTX_ADMIN_TOKEN"

curl -sS http://127.0.0.1:8000/admin/usage \
  -H "X-Admin-Token: $LTX_ADMIN_TOKEN"
```

## 常见故障

数据库不可用：检查 `LTX_DATABASE_URL` 路径或连接串，确认进程有写入权限。

对象存储失败：检查 `LTX_STORAGE_ROOT` 是否存在且可写；Phase 1 默认使用本地文件实现，后续可替换为 MinIO/S3 兼容实现。

API Key 无效：确认请求头是 `Authorization: Bearer <key>`，并确认服务启动时的 `LTX_BOOTSTRAP_API_KEY` 与调用方一致。

Admin 403：确认请求头是 `X-Admin-Token: <token>`，并与 `LTX_ADMIN_TOKEN` 一致。

executor 不可用：Phase 1 使用 `MockLocalExecutor`。如果任务长时间停留 queued，先检查是否调用了 `/internal/dispatch/run-once` 和 `/internal/dispatch/complete-running`。
