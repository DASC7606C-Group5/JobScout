# 持久化：checkpointer 与 thread_id

[返回学习入口](README.md) · 适用：第 3 组 · 前置：[人工澄清：interrupt 与恢复](06-clarification-and-resume.md)

Checkpointer 保存单个 graph thread 的状态快照。`thread_id` 用于定位该执行会话：同一个 ID 读取或恢复既有执行；新会话使用新的 ID。

```python
from langgraph.checkpoint.memory import InMemorySaver

checkpointer = InMemorySaver()
graph = builder.compile(checkpointer=checkpointer)
config = {"configurable": {"thread_id": "jobscout-session-42"}}
```

内存 saver 适合本地演示和测试，程序退出后状态消失。跨进程重启恢复需要受支持的数据库 checkpointer，并管理 schema 初始化、连接、凭证与保留策略。`thread_id` 不是跨所有会话共享的长期用户记忆；用户长期偏好属于另一类持久化需求，可评估 LangGraph Store 或业务数据库。

项目具体持久化方案仍以团队决策为准，不要把教学示例中的 `InMemorySaver` 当作生产配置。