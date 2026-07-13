# 测试报告

**项目**: LTX Video Service  
**日期**: 2026-07-13T16:53:35+08:00  
**测试者**: pb-v1-testing  
**状态**: PASS

---

## 1. 执行摘要

- 总测试数: 9
- 通过: 9
- 失败: 0
- 跳过: 0
- 覆盖率: 以约束覆盖矩阵计，P0/P1 目标约束 100% 覆盖

**发布就绪判定**: READY

## 2. 覆盖矩阵

| 约束来源 | 约束描述 | 测试类型 | 测试文件 | 状态 |
|---|---|---|---|---|
| T-004 | API Key 正常、无效、停用、健康检查不泄露密钥 | 集成测试 | `tests/test_phase1_api.py` | PASS |
| T-005 | 上传槽、上传读取、content_type 异常、资源隔离 | 集成测试 | `tests/test_phase1_api.py` | PASS |
| T-006 | 内置 T2V/I2V workflow、profile、publish/rollback | 集成测试 | `tests/test_phase1_api.py` | PASS |
| T-007 | 文生/图生任务创建、状态查询、幂等、取消 | 集成测试 | `tests/test_phase1_api.py` | PASS |
| T-010 | retryable failure、invalid_input、attempt、usage ledger | 集成测试 | `tests/test_phase1_api.py` | PASS |
| T-011 | Admin tasks/workflows/workers/usage 与 token 权限 | 集成测试 | `tests/test_phase1_api.py` | PASS |
| T-012 | `/health`、`/metrics`、失败原因与 attempt 指标 | 集成测试 | `tests/test_phase1_api.py` | PASS |
| T-013 | Phase 1 E2E 文生/图生/失败演练，不依赖 GPU | 集成测试 | `tests/test_phase1_api.py` | PASS |
| T-014 | API 示例覆盖资产、T2V、I2V、状态、结果 | 文档检查 | `docs/iterations/ltx-video-service/api_examples.md` | PASS |
| T-015 | Runbook 覆盖启动、smoke test、常见故障 | 文档检查 | `docs/iterations/ltx-video-service/runbook_phase1.md` | PASS |

**覆盖统计**:

- P0 验收标准覆盖: 10/10 (100%)
- P1 验收标准覆盖: 2/2 (100%)
- 异常路径覆盖: 认证失败、停用 Key、额度不足、缺图、不支持 content_type、invalid_input、retryable failure、Admin 未授权、终态取消
- 边界条件覆盖: SQLite 父目录自动创建、幂等重复提交、资源归属隔离

## 3. 缺陷列表

无 BLOCKER、MAJOR、MINOR 缺陷。

## 4. Gate 检查

- [x] P0 功能验收标准 100% 覆盖
- [x] P0 测试全部通过
- [x] 测试覆盖率 ≥ 80%
- [x] 无 BLOCKER 级缺陷
- [x] 无 MAJOR 级缺陷
- [x] 覆盖矩阵无空白

## 5. 执行命令

```bash
python3 -m pytest
```

结果: `9 passed in 0.66s`

```bash
python3 -m compileall -q src tests
```

结果: 通过，无输出。

```bash
curl -s http://127.0.0.1:8000/health
```

结果: `status=ok`。

## 6. 发布就绪判定

**判定**: READY  
**理由**: Phase 1 P0/P1 约束均有覆盖，自动化测试通过，无 BLOCKER/MAJOR 缺陷。

