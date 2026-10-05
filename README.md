# JobScout

JobScout 是个性化岗位发现与推荐 Agent 原型。用户提供简历或个人描述，以及求职方向后，系统确认必要信息、检索和整理岗位，并返回推荐岗位、技能差距和申请准备建议。

前端使用 React + TypeScript，后端使用 FastAPI + LangGraph。

## 快速启动

先安装 [uv](https://docs.astral.sh/uv/getting-started/installation/) 和 [Bun](https://bun.sh/docs/installation)。

在仓库根目录安装依赖并启动后端：

```sh
uv sync --locked
uv run --locked uvicorn jobscout.main:app --reload
```

后端默认地址为 [http://127.0.0.1:8000](http://127.0.0.1:8000)，接口文档位于 [/docs](http://127.0.0.1:8000/docs)。

另开一个终端，在仓库根目录启动前端：

```sh
cd web
bun i
bun dev
```

打开终端显示的地址，默认是 [http://localhost:3000](http://localhost:3000)。

后端本地配置示例见 [.env.example](.env.example)，真实模型调用需配置服务端 `LLM_API_KEY`。数据库设置见 [Python 开发说明](docs/python-development.md)。显式合成回放可在后端终端设置 `JOBSCOUT_MODE=replay`，操作见 [演示说明](docs/demo-walkthrough.md)；live 失败不会自动切换回放。

后端地址不同时，在 `web/` 中将 [.env.example](web/.env.example) 复制为 `.env.local`，修改 `API_PROXY_TARGET` 后重启 Vite。

## 日常开发

| 命令                                      | 执行目录   | 用途                                   |
| ----------------------------------------- | ---------- | -------------------------------------- |
| `uv run --locked python scripts/check.py` | 仓库根目录 | 检查 Python 代码、格式、类型并运行测试 |
| `bun test`                                | `web/`     | 运行前端单元测试                       |
| `bun check`                               | `web/`     | 检查前端类型、代码问题和格式           |
| `bun lint:fix`                            | `web/`     | 修复可以自动处理的代码问题             |
| `bun format`                              | `web/`     | 整理前端代码格式                       |
| `bun run build`                           | `web/`     | 检查类型并生成前端构建文件             |
| `bun preview`                             | `web/`     | 在本地预览前端构建结果                 |

提交前，后端运行全部检查，前端运行 `bun test` 和 `bun check`。修复或格式化后，查看改动并重新检查。

## 文档导航

| 文档                                                       | 内容                                       |
| ---------------------------------------------------------- | ------------------------------------------ |
| [实施规范](docs/implementation-plan.md) | 功能范围、预算与交付要求 |
| [系统架构](docs/architecture.md) | 模型边界、图流程、异步操作与证据 |
| [异步会话 API](docs/session-api.md) | 确认、版本、幂等、轮询和删除 |
| [固定评估](docs/evaluation.md) | 合成标注、规则基线、回放和指标局限 |
| [演示与备用录制](docs/demo-walkthrough.md) | 样例输入、显式回放和演示步骤 |
| [实际贡献记录](docs/contributions.md) | 本轮实施与验证范围 |
| [项目结构与协作](docs/project-structure.md)                | 目录职责、后端入口、运行状态和共享文件维护 |
| [Python 开发说明](docs/python-development.md)              | 后端配置、检查工具、依赖管理和提交钩子     |
| [前端架构与会话流程](docs/frontend-architecture.md)        | 路由、状态管理、API 交互和部署配置         |
| [团队开发指南](docs/JobScout_Development_Guide.md)         | 小组分工、接口基线和集成验收               |
| [LangGraph 学习路径](docs/langgraph/README.md)             | 工作流概念、状态和暂停恢复                 |
| [用户画像与确认](docs/profile-and-clarification-design.md) | 画像提取、缺失信息和追问处理               |
| [简历上传模块](docs/resume-upload-design.md)               | 支持格式、解析接口和上传交互               |
| [岗位检索模块](docs/group4_handoff.md)                     | 岗位来源、搜索调用和错误处理               |
| [岗位处理模块](docs/job-processing-design.md)              | 标准化、去重和时效判断                     |
| [匹配与推荐模块](docs/group6-recommendation.md)            | 筛选、排序、技能差距和准备建议             |
