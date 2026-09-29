# 最小可运行 graph

[返回学习入口](README.md) · 适用：全员 · 前置：[LangGraph 解决什么问题](01-langgraph-basics.md)

在仓库根目录安装锁定的依赖（包括 LangGraph）：

```bash
uv sync --locked
```

下面的 graph 把输入字符串转为大写。保存为 Python 文件后，用 `uv run 文件名.py` 运行：

```python
from typing import TypedDict

from langgraph.graph import END, START, StateGraph


class State(TypedDict):
    text: str
    result: str


def uppercase(state: State) -> dict[str, str]:
    return {"result": state["text"].upper()}


builder = StateGraph(State)
builder.add_node("uppercase", uppercase)
builder.add_edge(START, "uppercase")
builder.add_edge("uppercase", END)

graph = builder.compile()
result = graph.invoke({"text": "hello", "result": ""})
print(result["result"])
```

构建顺序是：定义状态 schema、注册节点、添加从 `START` 开始并到 `END` 结束的边，最后调用 `compile()` 得到可执行 graph。未编译的 builder 只是图定义，不能直接执行。

继续：[State、Node、Edge 与路由](03-state-nodes-routing.md)
