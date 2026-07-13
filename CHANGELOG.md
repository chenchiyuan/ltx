# Changelog

## v0.1.0 - 2026-07-13

### Added

- Phase 1 非 GPU 控制面 FastAPI 服务。
- API Key 鉴权、资产上传、文生视频/图生视频异步任务 API。
- Workflow template/version/profile 管理和 publish/rollback 流程。
- Task 状态机、取消、attempt、retryable failure、usage ledger。
- Admin API/HTML、health check 和 Prometheus 兼容 metrics。
- mock/local ExecutorAdapter，用于在不接 GPU 的情况下验证控制面闭环。
- Phase 1 API 示例、Runbook、pb-v1 implementation/testing/shipping 记录。

### Notes

- 本版本不包含 GPU Worker、ComfyUI/LTX 真实执行、Kubernetes/GPU Operator、DCGM。

