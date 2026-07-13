---
dimension: architecture
round: 4
scope: "ComfyUI + LTX 2.3 任务可靠性与 GPU 服务发现/挂载"
caller: pb-v1-talk
status: 生效
created: 2026-07-13
updated: 2026-07-13
---

# 架构方向 - Round 4

## 大原则确认

### 目标
收敛全局任务系统、ComfyUI 本地执行队列、GPU Worker 发现、Worker 粒度和模型/资产存储边界。

### 范围
- 包含: 全局排队、业务任务与 ComfyUI prompt 的关系、Kubernetes + NVIDIA GPU Operator、单 GPU Worker、模型缓存、输入输出对象存储。
- 不包含: 具体 Kubernetes YAML、对象存储厂商选型、数据库表结构细节、代码实现。

---

## 讨论清单

### CLR-ARCH-014: 全局排队边界
- **模糊点**: ComfyUI 内部队列是否承担全局任务调度。
- **影响范围**: 用户级排队、重试、计数、优先级、取消、任务状态机。
- **推荐选项**: ComfyUI 内部队列只作为 Worker 本地执行队列，全局排队由 Task Service 管。
- **结论**: ComfyUI 内部队列只作为 Worker 本地执行队列，全局排队由系统 Task Service 管理。
- **来源分类**: user_confirmed
- **状态**: 生效
- **确认时间**: 2026-07-13

### CLR-ARCH-015: 业务任务与 ComfyUI prompt 关系
- **模糊点**: 业务任务和 ComfyUI prompt_id 如何对应。
- **影响范围**: 幂等、重试、失败审计、用户可见任务状态。
- **推荐选项**: 一个业务任务对应一次或多次 ComfyUI prompt 尝试；失败后由 Task Service 重新派发。
- **结论**: 一个业务任务等于一次 ComfyUI prompt 执行；失败重试时由 Task Service 重新派发并形成新的执行尝试。
- **来源分类**: user_confirmed
- **状态**: 生效
- **确认时间**: 2026-07-13

### CLR-ARCH-016: GPU 集群管理方式
- **模糊点**: GPU 服务器是否统一纳入 Kubernetes 管理。
- **影响范围**: 服务发现、资源声明、Pod 重启、节点健康、部署自动化。
- **推荐选项**: Kubernetes + NVIDIA GPU Operator。
- **结论**: GPU 集群管理采用 Kubernetes + NVIDIA GPU Operator，而不是每台机器手工部署。
- **来源分类**: user_confirmed
- **状态**: 生效
- **确认时间**: 2026-07-13

### CLR-ARCH-017: Worker 资源粒度
- **模糊点**: 每个 ComfyUI Worker 绑定多少 GPU。
- **影响范围**: 调度隔离、失败影响面、容量计数、显存管理。
- **推荐选项**: 每张 GPU 一个 ComfyUI Worker 进程/容器。
- **结论**: 每张 GPU 一个 ComfyUI Worker 进程或容器，通过 CUDA_VISIBLE_DEVICES 或 K8s GPU limit 绑定。
- **来源分类**: user_confirmed
- **状态**: 生效
- **确认时间**: 2026-07-13

### CLR-ARCH-018: 模型与用户资产存储边界
- **模糊点**: 模型文件、输入文件、输出文件如何存储。
- **影响范围**: 冷启动速度、任务稳定性、结果访问、存储成本、迁移能力。
- **推荐选项**: 模型走节点本地 NVMe/PVC 缓存；输入输出走对象存储抽象。
- **结论**: 模型文件走节点本地 NVMe/PVC 缓存；输入输出走对象存储抽象，但对象存储不限定为 S3 或 MinIO。
- **来源分类**: user_confirmed
- **状态**: 生效
- **确认时间**: 2026-07-13

---

## 冲突处理

无
