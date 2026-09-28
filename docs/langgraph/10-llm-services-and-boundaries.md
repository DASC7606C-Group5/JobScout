# LLM、Service 与 API/Graph 边界

[返回学习入口](README.md) · 适用：全员，尤其第 1、3、4、5、6 组 · 前置：[State、Node、Edge 与路由](03-state-nodes-routing.md)

LangGraph 管理 workflow 状态和控制流，本身不要求使用某个模型。节点可以调用模型、现有 Python 服务或外部 API。

JobScout 的职责示例：

- `extract_profile`：可用 LLM 从简历抽取信息，再由 schema 校验结果。
- `validate_profile`：用确定性规则检查必填字段与格式。
- `plan_search`：把画像转为 `SearchRequest`。
- `retrieve_jobs`：调用检索服务并返回原始岗位数据。
- `process_jobs`：标准化、去重并标记岗位信息状态。
- `recommend`：比较用户画像与岗位要求，生成技能差距和建议。

这些职责不意味着每项必须实现成独立 node。若 LLM 只负责结构化抽取，不必把整个 graph 改造成自主工具调用 Agent。数字匹配分数是否展示以开发指南为准；MVP 不强制展示。

## 依赖边界

```text
Frontend
   ↓ HTTP
Session API / Controller
   ↓ 调用与映射输入输出
Graph Runner / Compiled Graph
   ↓ 调用依赖
Profile、Job Search、Job Processing、Recommendation Services
   ↓
LLM Provider、Job APIs、Database、Rules
```

- **API 层**：请求校验、会话入口，以及把暂停状态映射成前端响应；不承载 graph 编排。
- **Graph 层**：State、节点、边、路由和中断点，负责编排。
- **Service 层**：外部 API、LLM、业务规则和存储接口；应能脱离 LangGraph 单测。
- **Schema 层**：定义跨模块稳定契约；前端依赖约定 JSON，不读取 LLM 原始响应。

Graph 节点依赖 service 接口，而不是在节点内部构造全局 HTTP 客户端或读取环境变量，以便测试时注入 Mock。后端框架、session API 和持久化细节仍以团队决策为准。