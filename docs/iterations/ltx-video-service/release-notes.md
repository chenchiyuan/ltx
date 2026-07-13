# 发布记录: v0.1.0

**发布日期**: 2026-07-13T16:53:35+08:00  
**迭代**: ltx-video-service  
**发布者**: pb-v1-shipping

---

## 1. 版本信息

- 版本号: v0.1.0
- 版本类型: minor
- 关联迭代: ltx-video-service
- 关联分支: main

## 2. 变更摘要

### 新增功能

- Phase 1 非 GPU 控制面服务，覆盖 API、Admin、Task、Workflow、Asset、Usage 和 Observability。
- 文生视频/图生视频 API 使用 mock/local ExecutorAdapter 完成状态机闭环。
- 工作流 draft/testing/published/rollback 管理。
- 任务幂等、取消、attempt、retryable failure 和 usage ledger。
- API 示例、Phase 1 Runbook、测试报告和实施记录。

### 修改

- 无既有生产代码修改；本次为项目首个提交。

### 修复

- SQLite 数据库文件父目录不存在时自动创建，保证本地启动路径可用。

### 破坏性变更

- 无。首版发布。

## 3. 交付清单

- [x] 测试报告: READY
- [x] 版本号: v0.1.0
- [x] CHANGELOG.md 已生成
- [x] 本地 git 项目已初始化
- [x] 代码提交到本地主干 main
- [x] Tag 已创建: v0.1.0
- [ ] GitHub remote 待用户提供
- [ ] 代码待推送到 GitHub

## 4. 测试摘要

- 总测试数: 9
- 通过率: 100%
- 残余缺陷: 0
- 测试报告: `docs/iterations/ltx-video-service/test-report.md`

## 5. 回滚方案

如需回滚本地提交：

1. 在 GitHub 推送前，可删除本地 tag 和 commit 后重新提交。
2. 推送后，使用 `git revert <commit>` 生成回滚提交，不使用 force push。
3. 运行 `python3 -m pytest` 和 `python3 -m compileall -q src tests` 确认回滚后状态。
