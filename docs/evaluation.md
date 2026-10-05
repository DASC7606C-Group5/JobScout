# 固定评估与结果解释

数据位于 `data/evaluation/dataset.json`：12 个合成用户、30 个合成岗位。所有岗位使用保留的 `.invalid` 域名，不是真实招聘；全部标注由 AI 辅助编写，尚未经过独立人工复核。它们可用于回归和演示，不能代表真实招聘市场效果。

## 可重复性

`manifest.json` 固定数据 SHA-256 和原规则 baseline 的来源提交及文件哈希。冻结的 `baseline/profile_service.py` 与 `baseline/recommendation_service.py` 不应随新实现修改。runner 会检查哈希、数量、ID、证据片段和标注一致性。

```powershell
uv run --locked python scripts/evaluate.py --mode baseline --output data/evaluation/results/baseline.json
uv run --locked python scripts/evaluate.py --mode authored-replay --output data/evaluation/results/authored-replay.json
```

- **baseline**：原画像规则与原推荐规则。
- **authored-replay**：手工编写的合成模型输出，仅验证证据和评估管线；不是真实模型输出，`quality_evidence=false`。
- **live**：对合成材料调用已配置的真实模型，可记录脱敏响应。
- **recorded-replay**：重放此前真实合成材料调用，以 schema+prompt 哈希精确匹配；缺少录制时失败，不自动调用网络。

```powershell
uv run --locked python scripts/evaluate.py --mode live --output data/evaluation/results/live.json --record-output data/evaluation/replay/live-recording.json
uv run --locked python scripts/evaluate.py --mode recorded-replay --replay data/evaluation/replay/live-recording.json --output data/evaluation/results/recorded-replay.json
```

真实评估需服务端模型配置。不得将真实私密简历加入 fixtures 或录制文件。

## 比较协议与指标

两组画像理解使用相同输入和预设回答。排序比较使用相同的标注确认画像与相同候选池，逐例记录 candidate hash，避免候选差异掩盖理解/评分变化。这是组件评估，不是整个生产对话的端到端质量评估；生产交互通过单独的图/API/浏览器测试覆盖。

- **画像 precision/recall**：education、skills、internships、projects 的规范化事实集合，微平均；分母为零记 null。
- **澄清完成率**：需要交互的案例中，应用脚本回答后约束与标注一致且无未解决缺失/冲突的比例。可选问题跳过行为由图和浏览器测试验证，不在该组件指标中测量。
- **约束违规率**：返回岗位中命中标注硬约束违规的比例；没有返回岗位记 null。
- **Precision@5**：相关岗位数除以 5，少于五条也不缩小分母；另报 precision_returned。
- **证据支持率**：匹配理由所需 JD 及用户片段均存在于对应文档的比例。未体现项只需 JD 证据。它检查引用支持，不等同语义蕴含验证；semantic_entailment_rate 保持 null。
- **延迟与 usage**：记录本地执行耗时、structured calls、网络请求及供应商 usage；回放延迟不能当作 live 模型延迟。

## 当前可复查输出

已保存 baseline 和 authored-replay 输出。两种模式均完成 12 个案例；原规则 extraction precision 约 0.929、recall 约 0.945。两者 Precision@5 约 0.255，约束违规率为 0。手工回放的完美抽取/证据值是 fixtures 的构造结果，**不能证明 DeepSeek 质量提升**。

DeepSeek live/recorded 模型质量对比尚未验证：当前没有配置凭证。四个来源的独立 live 检索记录见 [检索验证结果](retrieval-live-validation-2026-10-04.json)，不能替代真实模型评估。
