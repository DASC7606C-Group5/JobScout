# 岗位处理模块设计文档（第 5 组）

*Job Processing Design — raw jobs → 统一 JobPosting*

本文档是第 5 组（岗位理解与数据质量）模块实现的设计依据，对应任务 JOBS-3，实现任务为 JOBS-1。
内容覆盖：字段映射、职责与技能解析策略、去重与合并规则、时效判定规则、接口设计和测试计划。
本文档不修改任何共享契约；文末列出已发现的契约缺口，待相关组确认。

## 1. 范围与职责

模块把第 4 组检索返回的原始岗位（raw jobs）转换为统一、可比较、可验证的 `JobPosting` 列表：

- 标准化职位、公司、地点、薪资、职责、技能、时间和链接字段；
- 从 JD 文本中确定性提取主要职责和关键技能要求；
- 合并跨来源重复岗位，保留全部来源链接与抓取时间；
- 标记时效状态 `active` / `expired` / `unknown`，无法确认时标 `unknown`；
- 记录处理过程中的 warnings，供 workflow 汇总与前端展示。

模块只做数据加工，不决定流程走向（路由由第 3 组负责），不调用任何外部服务。

## 2. 契约现状（2026-09-29 验证结论）

| 项 | 现状 |
| --- | --- |
| `src/jobscout/schemas/job.py` | 只有 TODO docstring，`JobPosting` 未定义、未冻结。基线只能依据开发指南 §4.2 的建议字段。 |
| `data/mock_jobs.json` | 单条样例，字段与开发指南 §4.2 一致（`job_id/source/source_url/title/company/location/salary/target_direction/responsibilities/required_skills/posted_at/expiry_at/freshness_status/fetched_at/source_links`）。注意：该样例是"已标准化"形态，不代表多来源异构 raw 输入。 |
| `src/jobscout/graph/state.py` | 只有 TODO docstring，`AgentState` 未定义；岗位列表在状态中的键名与形态未知。 |
| 第 4 组（检索） | `job_search_service.py`、`graph/nodes/search.py` 均为 TODO stub；raw job schema 未冻结。 |
| 第 6 组（推荐） | `recommendation_service.py`、`graph/nodes/recommend.py` 均为 TODO stub；`schemas/recommendation.py` 未定义。 |
| 其他共享 schema | `profile.py` / `search.py` / `errors.py` 均为 TODO stub，全部未冻结。 |

结论：可以以开发指南 §4.2 + `mock_jobs.json` 为设计基线并行开发；所有 schema 落地需第 3 组集中维护时确认。

## 3. 输入：raw job 假设格式

第 4 组的 raw job schema 尚未冻结（见 §9 缺口 2）。本模块按以下**超集假设**设计，每个字段都按可缺失处理：

```json
{
  "job_id": "来源内 id（可缺失）",
  "source": "来源名，如 mock / jobsdb / linkedin",
  "source_url": "岗位详情页链接",
  "title": "原始职位名",
  "company": "原始公司名",
  "location": "原始地点文本",
  "salary": "来源原文（字符串）或 null",
  "target_direction": "该岗位对应的求职方向（第 4 组写入）",
  "description": "JD 原文（可缺失）",
  "responsibilities": ["来源已结构化的职责（可缺失）"],
  "required_skills": ["来源已结构化的技能（可缺失）"],
  "posted_at": "ISO-8601 或 null",
  "expiry_at": "ISO-8601 或 null",
  "is_active": "来源显式状态（可缺失，true/false）",
  "fetched_at": "抓取时间（ISO-8601）"
}
```

输入在代码层面按 `list[dict]`（JSON 风格）接收，模块内部逐条校验与容错：**单条数据损坏不拖垮整批**，坏记录跳过并记 warning。

## 4. 输出：JobPosting 与处理结果

`JobPosting` 字段以开发指南 §4.2 为准（待第 3 组在 `schemas/job.py` 落地，建议用 pydantic 模型，与仓库 FastAPI/pydantic 技术栈一致）。字段映射表：

| JobPosting 字段 | 来源与规则 |
| --- | --- |
| `job_id` | 取 raw `job_id`；缺失时用去重键（§6）生成稳定 id（规范化键的 SHA-256 前 16 位，加 `gen-` 前缀），保证同一岗位重复处理时 id 稳定。 |
| `source` | 取 raw `source`；缺失记 `unknown` 并 warning。合并后保留首个来源名，全部来源链接见 `source_links`。 |
| `source_url` | 取 raw `source_url`，原样保留，不改写。 |
| `title` | 去首尾空白、压缩连续空白；缺失/为空时该条不可作为有效岗位：跳过并 warning（职位名是展示与去重的最低要求）。 |
| `company` | 同上清洗；缺失置 `null` 并 warning（不去重键为空仍可处理，见 §6）。 |
| `location` | 同上清洗；缺失置 `null`。 |
| `salary` | MVP 保留来源原文（字符串），不做数值解析；缺失置 `null`。 |
| `target_direction` | 取 raw `target_direction`；缺失置 `null`。 |
| `responsibilities` | 见 §5 解析策略。 |
| `required_skills` | 见 §5 解析策略。 |
| `posted_at` | 解析 ISO-8601 为 timezone-aware datetime；解析失败按缺失处理并 warning。 |
| `expiry_at` | 同上。 |
| `freshness_status` | 不继承 raw 值，由 §7 规则重新判定（raw 的 `is_active` 仅作为判据之一）。 |
| `fetched_at` | 取 raw `fetched_at` 并解析；缺失时取处理时刻并 warning。**永不丢弃**，满足"必须保留抓取时间"的约定。 |
| `source_links` | 初始化为 `[source_url]`（去重）；合并时取并集，保持插入顺序。 |

服务返回值建议为 `(jobs: list[JobPosting], warnings: list[str])`——warnings 的承载位置见 §9 缺口 4，实现前与第 3/6 组确认。

## 5. 职责与技能解析策略（确定性优先）

不引入任何未经团队确认的外部模型或依赖。按数据来源分三级处理：

1. **来源已结构化**（raw 带 `responsibilities` / `required_skills` 列表）：逐项去空白、丢空项、按大小写不敏感去重，保留原始写法。
2. **仅有 JD 原文**（`description` 文本）：
   - 职责：按行拆分，识别常见小节标题（`Responsibilities` / `职责` / `岗位职责` / `What you'll do` 等，大小写不敏感），收集该小节内的项目符号行（`•`、`-`、`*`、`·`、数字序号开头）；无小节时回退为全文项目符号行。结果去重、限制单条长度。
   - 技能：内置**技能词典**（常见语言/框架/工具及别名，如 `k8s`→`Kubernetes`、`Postgres`→`PostgreSQL`），对全文做大小写不敏感的词边界匹配；`Requirements` / `技能要求` 小节内的命中优先。词典随仓库维护，属于数据而非新依赖。
3. **两者皆无**：字段为空列表并记 warning，不做无依据补全。

LLM 辅助提取作为后续可选增强，需团队确认后另行立项，不在本模块默认路径内。

## 6. 去重键与跨来源合并规则

**规范化函数**（用于 title/company/location）：小写化 → 去除首尾与压缩连续空白 → 去除标点 → 公司名额外去除常见法律后缀（`ltd`、`limited`、`inc`、`co`, `company`、`有限公司` 等保守清单）。

**去重键** = `(norm(title), norm(company), norm(location))`：

- company 或 location 缺失时对应分量按空字符串参与比较（即"同职位 + 都缺公司"才会合并，保守不误并）；
- 同一来源内键重复同样合并。

**合并规则**（同键多条 → 一条 JobPosting）：

- 基准记录：字段完整度最高的一条（非空字段计数，并列取先出现者）；
- 标量字段（company/location/salary/title/posted_at 等）：基准缺失时从其余记录取首个非空补齐；
- `responsibilities` / `required_skills`：全记录并集，按大小写不敏感去重，保持首次出现顺序；
- `source_links`：全记录链接并集，保持插入顺序——**重复岗位只出现一次，但保留各来源链接**；
- `source`：保留基准记录的来源名；
- `target_direction`：取首个非空值（跨方向重复的边界情况见 §9 缺口 6）；
- `fetched_at`：取最大者（最新一次抓取）；
- `posted_at`：取非空值中最新者；`expiry_at`：取非空值中最早者（保守，宁可早判过期）；
- `freshness_status`：合并完成后按 §7 重新判定；
- `job_id`：基准记录的来源 id；基准无 id 时按 §4 规则生成。

## 7. 时效判定规则

判据只使用数据内证据：`expiry_at`、`posted_at`、`fetched_at`、来源显式 `is_active`。以处理时刻 `now`（可注入，测试用固定值）比较：

| 条件（按优先级） | 判定 |
| --- | --- |
| 来源显式 `is_active == false`，或 `expiry_at < now` | `expired` |
| `expiry_at >= now` | `active` |
| `posted_at` 距 `now` 不超过新鲜窗口 N 天 | `active` |
| 其他一切情况（无任何时间、posted_at 超窗且无 expiry、时间解析失败） | `unknown` |

- N 默认 30 天，定义为模块常量，是否调整/可配置待团队确认（§9 缺口 5）；
- `is_active == true` 单独不足以判 `active`（来源可能滞后），仍需时间证据支持，否则 `unknown`；
- **无法确认时一律 `unknown`，绝不假装 `active`**；
- 时间字段统一解析为 timezone-aware datetime；无法解析按缺失处理并记 warning。

## 8. 模块接口设计（实现期落地，签名以代码为准）

`services/job_processing_service.py`：

```python
def process_raw_jobs(
    raw_jobs: list[dict],
    *,
    now: datetime | None = None,
) -> tuple[list[JobPosting], list[str]]:
    """标准化 → 解析 → 去重合并 → 时效判定；返回 (岗位列表, warnings)。

    now 可注入以便测试；为 None 时取当前 UTC 时间。
    单条坏记录跳过并记 warning，不中断整批。
    """
```

`graph/nodes/process_jobs.py`：从 `AgentState` 读取 raw 岗位列表（键名待第 3 组定义，§9 缺口 3），调用 `process_raw_jobs`，把 `jobs` 与 `warnings` 写回状态。节点不含业务逻辑。

## 9. 契约缺口（待确认清单）

1. **JobPosting 未落地**（待第 3 组）：`schemas/job.py` 为空 stub。建议按开发指南 §4.2 + `mock_jobs.json` 落地为 pydantic 模型；`salary` 建议 MVP 用可选字符串（保留来源原文）。
2. **raw job schema 未冻结**（待第 4 组）：§3 是本组的超集假设。需确认：是否提供 `description` 原文、`posted_at`/`expiry_at` 的覆盖率与格式、`is_active` 类显式状态是否存在、`source` 命名清单、`target_direction` 由谁写入。
3. **AgentState 未定义**（待第 3 组）：raw 与处理后岗位建议分两个键（如 `raw_jobs` / `jobs`），warnings 建议入 state 供 `RecommendationResult.warnings` 汇总。
4. **处理 warnings 的承载位置**（待第 3/6 组）：开发指南要求第 5 组记录 warnings，但 §4.2 JobPosting 无 warnings 字段。本设计让服务返回 `(jobs, warnings)`，请确认汇总路径。
5. **新鲜窗口 N=30 天**（待团队确认）：属规则参数，确认后可能需要移入 `config.py`。
6. **跨方向重复岗位的 `target_direction`**（待第 6 组）：字段为单值，合并跨方向重复时本设计取首个非空；若推荐侧需要"一岗多方向"，需契约扩展（如 `target_directions: list`）。
7. **过期岗位的下游语义**（待第 6 组）：本组输出保留全部岗位含 `expired`/`unknown` 并如实标记；是否过滤、如何降权由推荐侧决定。

## 10. 测试计划（全部使用固定 Mock，不调用外部服务）

| 场景 | 样例设计 | 断言要点 |
| --- | --- | --- |
| 正常转换 | 3 条不同来源、字段完整的 raw jobs（含结构化职责/技能） | 字段映射正确；`source_url`/`fetched_at` 原样保留；`source_links` 初始化正确 |
| 缺失字段 | 缺 `salary`/`company`/`posted_at`，`description` 为空的 raw job | 不抛异常；缺失字段为 `null`/空列表；产生 warning；`freshness_status == "unknown"` |
| 坏记录容错 | 缺 `title` 的记录混入正常记录 | 坏记录跳过 + warning，正常记录照常输出 |
| 重复岗位合并 | 两来源同一岗位，title/company 含大小写、空白、标点与公司后缀差异 | 输出仅一条；`source_links` 含两个链接；职责/技能取并集；`fetched_at` 取最新 |
| 时效-过期 | `expiry_at` 早于 now | `expired` |
| 时效-活跃 | `posted_at` 在 30 天窗口内 / `expiry_at` 晚于 now | `active`（now 注入固定值） |
| 时效-未知 | 无任何时间字段；时间字符串无法解析 | `unknown`；解析失败有 warning；绝不输出 `active` |
| JD 文本解析 | 只有 `description`（含职责小节与技能词典词） | 职责/技能被确定性提取；词典别名归一 |
| 空输入 | `[]` | 返回 `([], [])` |

边界样例独立构造，不依赖 `data/mock_jobs.json` 的单条记录。
