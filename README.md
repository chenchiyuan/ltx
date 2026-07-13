# LTX Video Service

Phase 1 非 GPU 控制面，用于验证 LTX 文生视频/图生视频服务的 API、任务系统、工作流管理、对象存储边界、重试计数和内部管理能力。

## 范围

Phase 1 只包含 web/control 节点：

- FastAPI API-only 服务
- API Key 认证与资源隔离
- 资产上传和结果访问
- 文生视频、图生视频异步任务 API
- Workflow template/version/profile 管理
- Task attempt、重试、取消、usage ledger
- Admin API/HTML、`/health`、`/metrics`
- mock/local `ExecutorAdapter`

不包含 GPU 服务器、ComfyUI/LTX 真实执行、Kubernetes/GPU Operator、DCGM 或 Worker Registry。

## 本地启动

```bash
export PYTHONPATH=src
export LTX_DATABASE_URL="sqlite:///./.data/ltx.db"
export LTX_STORAGE_ROOT="./.data/object-storage"
export LTX_BOOTSTRAP_API_KEY="dev-api-key"
export LTX_ADMIN_TOKEN="dev-admin-token"
python3 -m uvicorn ltx_service.app:app --host 127.0.0.1 --port 8000
```

## 验证

```bash
python3 -m pytest
python3 -m compileall -q src tests
curl -s http://127.0.0.1:8000/health
```

更多上下文见 `docs/iterations/ltx-video-service/`。

