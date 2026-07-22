# LTX Video Service

基于 FastAPI、ComfyUI 和 LTX 2.3 的文生视频/图生视频服务。当前仓库包含控制面、内部 Web 测试前端、GPU worker 适配器和单机 GPU 部署入口。

## 范围

已经实现的核心能力：

- FastAPI API-only 服务
- API Key 认证与资源隔离
- 资产上传和结果访问
- 文生视频、图生视频异步任务 API
- Workflow template/version/profile 管理
- Task attempt、重试、取消、usage ledger
- Admin API/HTML、内部 Web 测试前端、`/health`、`/metrics`
- mock/local `ExecutorAdapter`
- GPU Worker Registry、dispatcher、worker heartbeat
- ComfyUI 单卡 worker：`fast`
- LTX-2 MGPU worker：`vip` 四卡 distilled pipeline
- workflow 输入契约：图生视频输入统一转为 `RGB PNG`

后续仍未进入当前单机阶段的能力：

- 多 GPU 服务器资源池
- Kubernetes/GPU Operator/KEDA
- 独立 MinIO/S3 对象存储部署
- 复杂组织/团队权限和价格系统

## 本地启动

本地默认用于控制面开发，不启动真实 GPU worker：

```bash
export PYTHONPATH=src
export LTX_DATABASE_URL="sqlite:///./.data/ltx.db"
export LTX_STORAGE_ROOT="./.data/object-storage"
export LTX_BOOTSTRAP_API_KEY="dev-api-key"
export LTX_ADMIN_TOKEN="dev-admin-token"
export LTX_WORKER_TOKEN="dev-worker-token"
export LTX_EXECUTOR_BACKEND="mock-local"
python3 -m uvicorn ltx_service.app:app --host 127.0.0.1 --port 8000
```

## 验证

```bash
python3 -m pytest
python3 -m compileall -q src tests
curl -s http://127.0.0.1:8000/health
```

更多上下文见 `docs/iterations/ltx-video-service/`。

## Phase 2 GPU 服务器

单机 GPU 部署入口位于 `gpu_server/`。

当前推荐 8 卡布局：

- `worker-fast-0..3`：4 个单卡 ComfyUI worker。
- `worker-vip`：1 个四卡 LTX-2 MGPU worker，使用 GPU `4,5,6,7`。
- 同机运行 `control-plane`、`dispatcher`、`web-frontend`。

部署路径：

```bash
cd gpu_server
cp .env.example .env
vi .env
HF_TOKEN=... ./scripts/download_models.sh
./scripts/deploy.sh
./scripts/healthcheck.sh
```

完整部署说明见 `gpu_server/README.md`。
