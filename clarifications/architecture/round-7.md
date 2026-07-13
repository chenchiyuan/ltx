---
dimension: architecture
round: 7
scope: "Phase 2 GPU 执行层部署边界与首版验收口径"
caller: pb-v1-talk
status: 生效
created: 2026-07-13
updated: 2026-07-13
---

# 架构方向 - Round 7

## 大原则确认

### 目标
收敛 Phase 2 GPU 执行层的首版验收范围、存储策略、LTX profile 和 GPU 服务器部署目录边界。

### 范围
- 包含: 8 卡/8 Worker 验收、对象存储过渡方案、首个 LTX profile、`gpu_server/` 子项目交付边界。
- 不包含: Phase 2 代码实现、GPU 型号最终性能参数、生产级多节点自动扩容。

---

## 讨论清单

### CLR-ARCH-029: Phase 2 首版 GPU 容量验收
- **模糊点**: Phase 2 第一版以 1 张 GPU 跑通 E2E，还是直接吃满一台 8 卡服务器。
- **影响范围**: Worker Registry、GPU Worker 部署、Dispatcher 容量模型、E2E 验收压力。
- **推荐选项**: 先 1 卡 E2E，再扩到 8 worker。
- **结论**: Phase 2 第一版按一台 8 卡 GPU 服务器吃满 8 卡验收，部署 8 个 Worker；Worker 数量必须可配置。
- **来源分类**: user_confirmed
- **状态**: 生效
- **确认时间**: 2026-07-13

### CLR-ARCH-030: Phase 2 对象存储过渡策略
- **模糊点**: Phase 2 是否必须先接 MinIO，还是可在单机 GPU 场景下使用本地共享存储。
- **影响范围**: Asset Service、Worker 输入下载、输出上传、后续对象存储替换成本。
- **推荐选项**: 使用 MinIO 作为共享对象存储。
- **结论**: Phase 2 可以使用 MinIO；考虑第一版只有一台 GPU 服务器，也可以先做本地共享存储，但必须经 `ObjectStorageAdapter` 保持后续替换为对象存储的边界。
- **来源分类**: user_confirmed
- **状态**: 生效
- **确认时间**: 2026-07-13

### CLR-ARCH-031: Phase 2 首个真实 LTX profile
- **模糊点**: 首个真实 LTX profile 是否直接做 two-stage/upscale。
- **影响范围**: 模型下载、显存压力、E2E 首次验收耗时和失败面。
- **推荐选项**: 首个真实 profile 使用 distilled single-stage，two-stage/upscale 后置。
- **结论**: Phase 2 首个真实 LTX profile 按 distilled single-stage 优先；two-stage/upscale 作为后续增强。
- **来源分类**: user_confirmed
- **状态**: 生效
- **确认时间**: 2026-07-13

### CLR-ARCH-032: GPU 部署子项目边界
- **模糊点**: GPU 部署脚本散落在项目根目录，还是作为独立 GPU 服务目录交付。
- **影响范围**: GPU 服务器 clone 后部署体验、镜像构建、配置隔离、后续运维文档。
- **推荐选项**: 新建 `gpu_server/`，作为 GPU 节点部署子项目。
- **结论**: Phase 2 必须新增独立 `gpu_server/` 目录。目标效果是 clone 项目后，在 GPU 服务器进入 `gpu_server/`，即可按目录内方案构建/拉取镜像并部署 8 个可配置 Worker。
- **来源分类**: user_confirmed
- **状态**: 生效
- **确认时间**: 2026-07-13

---

## 冲突处理

无
