---
dimension: architecture
round: 3
scope: "ComfyUI + LTX 2.3 工作流管理与 ComfyUI 集成方式"
caller: pb-v1-talk
status: 生效
created: 2026-07-13
updated: 2026-07-13
---

# 架构方向 - Round 3

## 大原则确认

### 目标
收敛 ComfyUI 在系统中的职责边界，以及 LTX 工作流如何模板化、版本化并接入任务进度。

### 范围
- 包含: ComfyUI headless Worker、工作流双格式管理、WebSocket + History 进度接入、LTX 官方模板、质量档位。
- 不包含: 具体工作流 JSON 内容、节点参数细节、最终 UI 设计、代码实现。

---

## 讨论清单

### CLR-ARCH-009: ComfyUI 暴露边界
- **模糊点**: 是否把 ComfyUI 原生界面暴露给外部用户。
- **影响范围**: 产品体验、安全边界、工作流可控性、任务隔离。
- **推荐选项**: ComfyUI 只作为 headless Worker，不对外暴露原生界面。
- **结论**: ComfyUI 只作为 headless Worker；外部用户使用 SaaS 界面，生产任务通过 ComfyUI Server API 下发。
- **来源分类**: user_confirmed
- **状态**: 生效
- **确认时间**: 2026-07-13

### CLR-ARCH-010: 工作流双格式管理
- **模糊点**: 是否同时保存可视化源 workflow 和生产 API Format。
- **影响范围**: 工作流编辑、发布、回滚、生产执行稳定性。
- **推荐选项**: 双格式管理，源格式用于编辑，API Format 用于执行。
- **结论**: 工作流采用双格式管理：保存可视化源 workflow，同时发布 API Format 作为执行版本。
- **来源分类**: user_confirmed
- **状态**: 生效
- **确认时间**: 2026-07-13

### CLR-ARCH-011: ComfyUI 进度接入方式
- **模糊点**: 如何获取 ComfyUI 任务进度和结果。
- **影响范围**: 任务状态机、前端进度展示、失败诊断、结果回收。
- **推荐选项**: 按 ComfyUI 官方推荐采用 WebSocket + History。
- **结论**: 任务进度按 ComfyUI 官方推荐的 WebSocket + History 方式接入。
- **来源分类**: user_confirmed
- **状态**: 生效
- **确认时间**: 2026-07-13

### CLR-ARCH-012: LTX 工作流开放范围
- **模糊点**: 第一阶段是否允许用户自由编辑 ComfyUI 节点图。
- **影响范围**: 安全、依赖管理、显存控制、产品复杂度。
- **推荐选项**: 第一阶段只内置 LTX 官方 Text/Image to Video 模板，不开放用户自由编辑节点图。
- **结论**: 第一阶段只内置 LTX 官方 Text/Image to Video 模板，采用参数化模板，不开放用户自由编辑节点图。
- **来源分类**: user_confirmed
- **状态**: 生效
- **确认时间**: 2026-07-13

### CLR-ARCH-013: 生成质量档位
- **模糊点**: 是否需要多个生成 profile。
- **影响范围**: 工作流版本、GPU 调度、计费倍率、用户体验。
- **推荐选项**: 第一阶段提供快速版和高质量版两个固定 profile。
- **结论**: 第一阶段提供两个固定生成档位：快速版和高质量版。
- **来源分类**: user_confirmed
- **状态**: 生效
- **确认时间**: 2026-07-13

---

## 冲突处理

无
