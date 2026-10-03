# 项目结构与协作

本文件记录仓库的目录职责、后端运行方式和共享文件维护约定。安装和启动见[项目 README](../README.md)，团队任务与验收场景见[开发指南](JobScout_Development_Guide.md)。

## 目录职责

| 路径                     | 职责                                                                                  |
| ------------------------ | ------------------------------------------------------------------------------------- |
| `web/`                   | React + TypeScript 前端及其测试；路由和状态管理见[前端架构](frontend-architecture.md) |
| `src/jobscout/api/`      | FastAPI 接口，负责请求校验、会话操作和简历解析入口                                    |
| `src/jobscout/graph/`    | LangGraph 状态、节点、条件路由和暂停恢复                                              |
| `src/jobscout/schemas/`  | 跨模块共享的数据契约                                                                  |
| `src/jobscout/services/` | 画像、简历解析、岗位检索、岗位处理和推荐的业务实现                                    |
| `tests/`                 | 后端模块、API、工作流和环境测试                                                       |
| `scripts/`               | 开发检查和岗位检索演示工具                                                            |
| `data/`                  | 固定样例与模块演示数据                                                                |
| `docs/`                  | 架构、实现细节、模块设计、协作和学习资料                                              |

根目录的 `pyproject.toml` 管理 Python 依赖和检查工具配置，`uv.lock` 固定依赖版本；前端对应文件为 `web/package.json` 和 `web/bun.lock`。

`.env.example` 提供可提交的配置示例，`.env` 保存本地配置。API keys、真实简历和受限数据不提交到版本库，演示与测试优先使用脱敏固定样例。

## 后端入口与运行状态

[`main.py`](../src/jobscout/main.py) 创建 FastAPI 应用，挂载 Session 与简历解析接口，初始化数据库连接和 LangGraph 工作流。

[`config.py`](../src/jobscout/config.py) 从环境变量及 `.env` 读取配置。当前 `DATABASE_URL` 默认指向 SQLite，也可以使用 PostgreSQL；具体设置见[Python 开发说明](python-development.md)。

[`database.py`](../src/jobscout/database.py) 管理 Tortoise ORM 连接的初始化和关闭，当前没有业务模型和数据库迁移。Session API 已提供创建、查询、回答追问和删除操作，会话状态由 `InMemorySaver` 保存，重启后不保留。数据库连接与会话存储是两个独立部分。

| 入口                                                   | 职责                                               |
| ------------------------------------------------------ | -------------------------------------------------- |
| [`api/sessions.py`](../src/jobscout/api/sessions.py)   | 健康检查及 Session 创建、查询、恢复和删除          |
| [`api/resumes.py`](../src/jobscout/api/resumes.py)     | 上传 PDF / DOCX 并提取简历文字                     |
| [`graph/state.py`](../src/jobscout/graph/state.py)     | 定义节点共享的 `AgentState`                        |
| [`graph/builder.py`](../src/jobscout/graph/builder.py) | 连接节点与条件分支，提供业务图和 Mock 图的构建入口 |
| [`graph/routing.py`](../src/jobscout/graph/routing.py) | 判断追问、检索、处理、推荐和结束分支               |
| [`graph/runner.py`](../src/jobscout/graph/runner.py)   | 启动或恢复工作流，统一返回运行结果                 |

应用启动时使用 `build_graph` 接入各业务节点；`build_mock_graph` 使用固定节点，供测试与独立验证流程使用。Mock 样例用于开发和测试，前端的运行时结果来自 Session API。

## 节点、服务与数据契约

图节点从 `AgentState` 读取输入、调用业务服务并返回状态更新；业务服务负责解析、检索、整理和推荐。流程顺序和分支由图控制，复杂业务处理放在服务层。

| 模块           | 图节点                                                   | 服务与详细说明                                                                             |
| -------------- | -------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| 用户画像与确认 | `graph/nodes/profile.py`、`graph/nodes/clarification.py` | `services/profile_service.py`；[模块设计](profile-and-clarification-design.md)             |
| 简历解析       | 通过上传 API 接入资料表单                                | `services/resume_service.py`；[模块设计](resume-upload-design.md)                          |
| 岗位检索       | `graph/nodes/search.py`                                  | `services/job_search_service.py`、`services/job_retrieval/`；[调用说明](group4_handoff.md) |
| 岗位处理       | `graph/nodes/process_jobs.py`                            | `services/job_processing_service.py`；[模块设计](job-processing-design.md)                 |
| 匹配与推荐     | `graph/nodes/recommend.py`                               | `services/recommendation_service.py`；[交付说明](group6-recommendation.md)                 |

上述代码路径相对于 `src/jobscout/`。共享 schema 包括 `UserProfile`、`SearchRequest`、`ClarificationMessage`、`JobPosting`、`RecommendationResult`、Session 请求/响应和 `WorkflowError`，定义位于 `schemas/`。

模块之间通过共享契约交接数据，避免读取其他模块的内部变量。多个求职方向合并为总体最多 5 个推荐岗位；无法确认岗位时效时保留 `unknown`，来源与抓取时间随岗位数据传递。

## 测试与样例

后端测试位于 `tests/`，覆盖环境、API、画像、检索、处理、推荐及工作流分支。前端测试位于 `web/tests/`；固定资料和岗位样例不进入应用构建。

`data/mock_jobs.json` 提供基本岗位样例，`data/group4/` 和 `data/group6/` 保存检索与推荐模块的样例及演示资料。自动化测试使用固定输入覆盖正常、失败和边界行为，外部来源的独立演示见[岗位检索说明](group4_handoff.md)。

## 共享文件维护

各小组的职责和交付清单以[团队开发指南](JobScout_Development_Guide.md)为准。代码维护入口如下：

| 小组                        | 主要代码入口                                                                |
| --------------------------- | --------------------------------------------------------------------------- |
| 第 1 组：前端与交互         | `web/src/`                                                                  |
| 第 2 组：用户画像与确认     | `services/profile_service.py`、`services/resume_service.py` 及画像/追问节点 |
| 第 3 组：整体 Workflow      | `main.py`、`config.py`、`database.py`、`api/`、图编排与共享 schema          |
| 第 4 组：岗位检索           | `services/job_search_service.py`、`services/job_retrieval/`、检索节点       |
| 第 5 组：岗位理解与数据质量 | `services/job_processing_service.py`、岗位处理节点                          |
| 第 6 组：匹配与推荐         | `services/recommendation_service.py`、推荐节点                              |

后端路径相对于 `src/jobscout/`。以上是建议的维护归属，所有小组共同参与集成和修复自身模块的问题。

共享 schema 和配置建议由第 3 组集中维护，字段变更由相关生产方和使用方共同确认。外部岗位来源、模型或解析服务由使用它们的业务组调研；新增依赖、配置和成本需与团队对齐。

跨组变更先确认输入、输出和错误格式，再用固定样例验证模块与图的接入，最后完成端到端验收。每组交付模块入口、接口说明、样例、测试和集成说明。
