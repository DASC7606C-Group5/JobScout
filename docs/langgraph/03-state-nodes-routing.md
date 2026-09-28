# State、Node、Edge 与路由

[返回学习入口](README.md) · 适用：全员 · 前置：[最小可运行 graph](02-minimal-graph.md)

## State

State 是 graph 执行中的共享数据，不是数据库，也不自动等同于用户档案。它只应包含 workflow 执行、路由、恢复或输出确实需要的数据。

```python
from typing import TypedDict


class State(TypedDict):
    query: str
    normalized_query: str
    result: str


def normalize(state: State) -> dict[str, str]:
    return {"normalized_query": state["query"].strip().lower()}
```

没有为某个 key 配 reducer 时，新值会替换旧值。需要累积列表或合并消息时，才为对应 key 配 reducer；列表类型本身不意味着自动 append。并行节点写入同一个 key 时也要明确 reducer。

状态设计建议：明确字段；区分输入、中间数据、错误和最终输出；不要把数据库连接、模型客户端等运行时依赖放进可持久化状态；对简历等敏感数据采取最小化保存、访问控制和保留期限。

## Node

Node 通常接收 State 并返回局部更新。节点尽量保持单一职责，例如画像提取、校验、搜索规划、岗位查询、分析或推荐，便于独立测试和定位故障。

若 node 可能因恢复、重试或 interrupt 而重新执行，应谨慎处理外部副作用。对创建记录等操作使用幂等键或 upsert，或把副作用放在确认之后。

## 固定 Edge

```python
builder.add_edge(START, "extract_profile")
builder.add_edge("extract_profile", "validate_profile")
builder.add_edge("validate_profile", "plan_search")
builder.add_edge("plan_search", END)
```

`START` 和 `END` 是虚拟入口与终点。从同一节点连出多条普通边可能导致多个目标在同一轮执行，并非“任选一个”。择一路径应使用条件边。

## Conditional Edge

```python
from typing import Literal


def route_after_validation(state: State) -> Literal["clarify", "plan_search"]:
    if state.get("errors"):
        return "clarify"
    return "plan_search"


builder.add_conditional_edges(
    "validate_profile",
    route_after_validation,
    {"clarify": "clarify", "plan_search": "plan_search"},
)
```

也可以让 router 返回 `END`。需要同一 node 同时更新 State 并动态决定去向时可使用 `Command(update=..., goto=...)`；不要同时配置静态边和另一套路由机制，以免两条路径都被执行。

下一步：[JobScout 状态与数据契约](04-jobscout-state-contracts.md)