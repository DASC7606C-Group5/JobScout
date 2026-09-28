# 什么时候使用 subgraph

[返回学习入口](README.md) · 适用：第 3 组；第 5 组按需 · 前置：[State、Node、Edge 与路由](03-state-nodes-routing.md)

Subgraph 是编译后的 graph，可作为另一个 graph 的节点使用。适用于一段流程足够独立、需要复用、拥有自己的状态边界，或确实需要拆分复杂度的情况。

JobScout 初期通常一个主 graph 足够。不要为了架构看起来更“Agent 化”而把每个步骤都拆成 subgraph。若岗位处理逻辑成长为独立且可复用的流程，例如岗位解析、去重、规范化，再评估是否值得抽出。

跨图状态键、checkpointer 命名空间和中断恢复会增加复杂度。拆分前先确认复用或隔离收益足以抵偿这些成本。