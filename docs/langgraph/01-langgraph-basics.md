# LangGraph 解决什么问题

[返回学习入口](README.md) · 适用：全员 · 前置：无

普通函数串联适合简单、线性的流程：调用 A，再调用 B，再调用 C。当流程需要条件分支、循环澄清、并行处理、暂停等待用户、失败后从中间恢复或检查执行过程时，显式管理流程状态会更清楚。

LangGraph 把 workflow 表示为有向图：

- **State**：一次执行过程中的共享数据快照。
- **Node**：读取当前 State，执行一段逻辑，返回部分状态更新。
- **Edge**：规定一个节点之后执行哪些节点。
- **Conditional edge**：根据当前 State 决定下一步。
- **Checkpointer**：保存 thread 的状态快照，以便恢复、检查或回放。

节点不等同于 Agent。节点可以只是校验字段的 Python 函数；只有需要模型进行非确定性判断或生成时才调用 LLM。业务规则、字段校验、排序和状态变更应尽量显式且可测试。

继续：[最小可运行 graph](02-minimal-graph.md) → [State、Node、Edge 与路由](03-state-nodes-routing.md)