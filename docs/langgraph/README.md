# JobScout LangGraph 学习路径

本目录把 LangGraph 教程拆成可按需阅读的章节。教程解释 LangGraph 概念及其在 JobScout 中的用法，不定义项目正式接口。

## 开始前必读

- [JobScout 开发指南](../JobScout_Development_Guide.md)：项目流程、MVP、正式数据契约和验收标准。字段冲突以此为准。
- [JobScout 项目 README](../../README.md)：目录职责、协作边界和开发约定。

教程示例用于学习 LangGraph，可能省略项目字段或流程步骤；不要将示例类型直接复制成正式 schema。

## 全员共同基础

所有小组先读以下三篇，建立共同概念：

1. [LangGraph 解决什么问题](01-langgraph-basics.md)
2. [最小可运行 graph](02-minimal-graph.md)
3. [State、Node、Edge 与路由](03-state-nodes-routing.md)

再阅读 [JobScout 状态与数据契约](04-jobscout-state-contracts.md)，了解教程示例与正式 schema 的边界。

## 分组阅读路线

| 小组 | 必读 | 按实现需要选读 |
| --- | --- | --- |
| 第 1 组：前端与交互 | 全员共同基础；[运行、流式输出与调试](09-running-and-observability.md) 中的 API 交互边界；[澄清与恢复](06-clarification-and-resume.md) 的前端交互部分 | [错误处理与幂等性](11-errors-and-idempotency.md) |
| 第 2 组：用户画像与信息确认 | 全员共同基础；[JobScout 主 graph](05-jobscout-main-graph.md)；[澄清与恢复](06-clarification-and-resume.md) | [测试 graph](12-testing.md) |
| 第 3 组：整体 Workflow | 全部教程文档，按编号顺序 | 必须重点掌握主 graph、澄清恢复、持久化、测试和调试 |
| 第 4 组：岗位检索 | 全员共同基础；[服务边界与依赖注入](10-llm-services-and-boundaries.md)；[错误处理与幂等性](11-errors-and-idempotency.md)；[测试 graph](12-testing.md) | [Mock 接入真实服务](13-mock-to-real-services.md) |
| 第 5 组：岗位理解与数据质量 | 全员共同基础；[服务边界与依赖注入](10-llm-services-and-boundaries.md)；[错误处理与幂等性](11-errors-and-idempotency.md)；[测试 graph](12-testing.md) | [什么时候使用 subgraph](08-subgraphs.md) |
| 第 6 组：匹配与推荐 | 全员共同基础；[JobScout 状态与数据契约](04-jobscout-state-contracts.md)；[服务边界与依赖注入](10-llm-services-and-boundaries.md)；[测试 graph](12-testing.md) | [Mock 接入真实服务](13-mock-to-real-services.md) |

## 章节目录

1. [LangGraph 解决什么问题](01-langgraph-basics.md)
2. [最小可运行 graph](02-minimal-graph.md)
3. [State、Node、Edge 与路由](03-state-nodes-routing.md)
4. [JobScout 状态与数据契约](04-jobscout-state-contracts.md)
5. [构建 JobScout 主 graph](05-jobscout-main-graph.md)
6. [人工澄清：interrupt 与恢复](06-clarification-and-resume.md)
7. [持久化：checkpointer 与 thread_id](07-checkpointing.md)
8. [什么时候使用 subgraph](08-subgraphs.md)
9. [运行、流式输出与调试](09-running-and-observability.md)
10. [LLM、Service 与 API/Graph 边界](10-llm-services-and-boundaries.md)
11. [错误处理、重试与幂等性](11-errors-and-idempotency.md)
12. [测试 graph](12-testing.md)
13. [从 Mock 逐步接入真实服务](13-mock-to-real-services.md)

## 项目开工顺序

六组职责、共享契约冻结、Mock 交付、集成顺序和验收场景统一以开发指南为准。推荐顺序是：冻结接口与 Mock → 各组并行开发和测试 → 第三组用 Mock nodes 串起 graph → 替换真实模块 → 全组端到端验收。

## 版本与官方参考

示例采用 LangGraph Python Graph API 的常见接口。开始实现前，按项目实际依赖版本核对[官方 Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api)、[中断](https://docs.langchain.com/oss/python/langgraph/interrupts)、[持久化](https://docs.langchain.com/oss/python/langgraph/persistence)和[流式输出](https://docs.langchain.com/oss/python/langgraph/streaming)文档。`InMemorySaver` 仅适用于学习与测试，不适用于进程重启后恢复的生产场景。