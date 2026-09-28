# 人工澄清：interrupt 与恢复

[返回学习入口](README.md) · 适用：第 1、2、3 组 · 前置：[构建 JobScout 主 graph](05-jobscout-main-graph.md)

当 `UserProfile` 缺少必要字段或存在待确认冲突时，JobScout 应暂停 graph，向前端返回 `ClarificationMessage` 并等待用户回答。下面是**独立教学片段**：仅演示暂停与恢复，不实现答案写回 `UserProfile`、重新校验和完整路由；正式契约以开发指南为准。

```python
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command, interrupt


def clarify(state: JobScoutState) -> dict[str, object]:
    answer = interrupt(
        {
            "type": "clarification",
            "question": state["clarification_question"],
        }
    )
    return {"clarification_answer": answer}


builder = StateGraph(JobScoutState)
builder.add_node("clarify", clarify)
builder.add_edge(START, "clarify")
graph = builder.compile(checkpointer=InMemorySaver())

config = {"configurable": {"thread_id": "jobscout-session-42"}}
paused = graph.invoke(
    {"clarification_question": "你希望申请哪些岗位？"},
    config=config,
)
question = paused["__interrupt__"][0].value
print(question)

completed = graph.invoke(Command(resume="Data Analyst"), config=config)
```

恢复时必须使用原来的 `thread_id`。`Command(resume=...)` 的值会成为 `interrupt()` 的返回值。恢复会从调用 `interrupt()` 的整个 node 函数开头重新执行，而不是从暂停行继续；因此 interrupt 之前的副作用必须幂等，也不要用宽泛的 `try/except Exception` 包住 `interrupt()`。

项目闭环还需要把回答应用到画像、重新校验，并在必要信息齐全后进入检索。`ClarificationMessage` 的外部格式和 session API 由开发指南及团队确认的接口决定。