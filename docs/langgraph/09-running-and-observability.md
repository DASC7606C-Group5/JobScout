# 运行、流式输出与调试

[返回学习入口](README.md) · 适用：第 1、3 组 · 前置：[构建 JobScout 主 graph](05-jobscout-main-graph.md)

- `graph.invoke(input, config=...)`：运行到结束或暂停并返回结果。
- `graph.stream(input, stream_mode="updates")`：逐步取得节点更新；`values` 提供每步完整状态快照。
- `graph.get_state(config)`：在启用 checkpointer 并提供 thread 配置时查看状态快照及后续任务信息。
- 异步应用可使用 `graph.ainvoke(...)`、`graph.astream(...)`。

```python
for event in jobscout_graph.stream(
    {
        "resume_text": "Skills: Python, SQL",
        "target_directions": ["Data Analyst"],
        "preferences": {"location": "Hong Kong"},
    },
    stream_mode="updates",
):
    print(event)
```

流式输出可能包含中间状态；不要未经筛选就把内部字段、简历原文或敏感信息发给客户端。事件格式依 LangGraph 版本和参数而异，应按项目实际版本文档实现。

开发时可用 `updates` 查看每个节点写入的值，有 checkpointer 时用 `get_state(config)` 检查 thread 快照。结构化日志可记录 `thread_id`、node 名、耗时、外部请求标识和错误类别，但避免记录完整简历、密钥或不必要的个人信息。需要更深入的 trace、耗时分析或可视化时，再评估 LangSmith 等工具并按数据策略脱敏。