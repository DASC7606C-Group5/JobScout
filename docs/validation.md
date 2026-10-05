# 验证记录与剩余限制

## 当前已执行

| 检查 | 结果 |
| --- | --- |
| Python 全量 pytest | 595 passed；`uv run --locked python scripts/check.py` 完整通过 |
| Ruff lint / format check | 通过 |
| mypy | 80 个源文件通过 |
| 前端单元测试 | 25 passed |
| Mock API 浏览器测试 | 10 passed |
| 前端 typecheck、lint、format、生产构建 | 通过 |
| React Doctor | 零问题 |
| 真实本地后端 + 回放浏览器 | 2/2 通过：完整输入和动态澄清，包含确认、证据卡片、刷新 |
| HTTP 回放集成 | 输入、动态澄清、确认、结果、修改条件及再次确认、删除；画像失败后重试通过 |
| 会话缓存与日志 | JD 缓存跨条件修改/图重建复用、跨会话拒绝、每次搜索预算重置和安全阶段计时测试通过 |
| 固定评估 baseline / authored-replay | 各 12 个案例运行成功；数据 12 个画像、30 个岗位 |
| 四招聘来源 live | 四个来源均返回结果，见独立记录 |
| DeepSeek live | **未完成：没有配置凭证** |

命令与测试配置分别见 `scripts/check.py`、`web/package.json`、`web/playwright.config.ts` 和 [前端架构](frontend-architecture.md)。Node v24.18.1，Python 3.14；Bun 使用前端本地工具路径，环境安装与运行说明见前端文档。

## 解释限制

- [来源 live 记录](retrieval-live-validation-2026-10-04.json) 只证明该次有界合成检索返回结果，不保证来源持续可用。
- authored replay 是人为生成的模型响应，用于管线/引用回归，不是 DeepSeek 输出，不证明模型效果改善。详见 [评估](evaluation.md)。
- 真实 DeepSeek 模型名、thinking/JSON 参数和生产网络行为仍需配置凭证后完成 live 验收。缺少凭证会显式失败，不会偷偷切换演示。
- 自动测试默认离线；合成标注尚未经过独立人工复核。未执行独立人工 code review。
- 单进程内存会话没有持久化、认证或生产部署保证；重启后失效。
