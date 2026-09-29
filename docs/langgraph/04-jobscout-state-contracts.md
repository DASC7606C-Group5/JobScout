# JobScout 状态与数据契约

[返回学习入口](README.md) · 适用：全员，尤其第 2、3、6 组 · 前置：[State、Node、Edge 与路由](03-state-nodes-routing.md)

业务对象描述业务领域；`AgentState` 描述 workflow 当前运行需要什么。不要把二者混成一个万能 State。正式契约定义在[开发指南第 4 节](../JobScout_Development_Guide.md#4-共享数据接口)，共享 schema 位于 `src/jobscout/schemas/`，graph 状态位于 `src/jobscout/graph/state.py`。

以下仅为结构关系示意，不是可复制使用的正式 schema：

```python
class AgentState(TypedDict):
    session_id: str
    messages: list[dict[str, object]]
    profile: NotRequired[UserProfile]
    search_tasks: NotRequired[list[SearchRequest]]
    jobs: NotRequired[list[JobPosting]]
    current_stage: NotRequired[str]
    result: NotRequired[RecommendationResult]
```

开发指南还定义 `ClarificationMessage` 和统一错误结构。业务/服务边界的数据契约不必全部成为 graph state key；只有 workflow 需要读取、更新、路由或持久化的值才进入 State。

字段类型、必填规则和完整定义以开发指南为准。接口变更应同步更新共享 schema、Mock JSON 和受影响测试。不要从本教程的教学代码复制字段定义。

下一步：[构建 JobScout 主 graph](05-jobscout-main-graph.md) · [澄清与恢复](06-clarification-and-resume.md)