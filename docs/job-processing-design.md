# 岗位处理模块设计文档（第 5 组）

*Job Processing Design — raw jobs → 统一 JobPosting*

本文档是第 5 组（岗位理解与数据质量）模块实现的设计依据，对应任务 JOBS-3，实现任务为 JOBS-1。
内容覆盖：字段映射、职责与技能解析策略、去重与合并规则、时效判定规则、接口设计和测试计划。
本文档不修改任何共享契约；文末列出仍开放的契约缺口，待相关组确认。

> **修订记录（2026-10-02，JOBS-1 迁移迭代）**：schema v1（commit `0e3a007`）与 `AgentState`（commit `fc2b26f`，含 append reducer 见 commit `be26469`）已在 main 冻结。两位成员于 2026-09-30 确认了迁移决策，本文档已同步：§2 契约现状、§4 缺失字段处理规则、§7 时效判定规则、§8 状态键名与接口、§9 缺口清单、§10 测试计划。§5/§6 中与已确认"逻辑不变"的实现不一致的描述（职责全文回退、技能别名、基准记录选取、`posted_at` 合并取值）一并按实现校正。

## 1. 范围与职责

模块把第 4 组检索返回的原始岗位（raw jobs）转换为统一、可比较、可验证的 `JobPosting` 列表：

- 标准化职位、公司、地点、薪资、职责、技能、时间和链接字段；
- 从 JD 文本中确定性提取主要职责和关键技能要求；
- 合并跨来源重复岗位，保留全部来源链接与抓取时间；
- 标记时效状态 `active` / `expired` / `unknown`，无法确认时标 `unknown`；
- 记录处理过程中的 warnings，供 workflow 汇总与前端展示。

模块只做数据加工，不决定流程走向（路由由第 3 组负责），不调用任何外部服务。

## 2. 契约现状（2026-10-02 验证结论）

| 项 | 现状 |
| --- | --- |
| `src/jobscout/schemas/job.py` | **已冻结（schema v1，commit `0e3a007`）**。`JobPosting` 为 pydantic 模型（`extra="forbid"`），`FreshnessStatus` 为 `StrEnum`（`active`/`expired`/`unknown`）。必填无默认值字段：`job_id`、`source`、`source_url`、`title`、`company`、`location`、`target_direction`、`fetched_at`；可选：`salary`、`posted_at`、`expiry_at`（默认 `None`）；`responsibilities`、`required_skills`、`source_links` 默认空列表；`freshness_status` 默认 `unknown`。 |
| `src/jobscout/graph/state.py` | **已冻结（commit `fc2b26f`）**。相关键：`raw_jobs: list[dict]`（输入）、`normalized_jobs: list[JobPosting]`（本模块输出）；`warnings` / `errors` 键已带 `operator.add` append reducer（commit `be26469`，由本组向第 3 组提出并获接受），多节点写同键不再互相覆盖。 |
| `data/mock_jobs.json` | 单条样例，字段与开发指南 §4.2 一致。注意：该样例是"已标准化"形态，不代表多来源异构 raw 输入；其 `salary`/`posted_at`/`expiry_at` 为 `null`，按 §4 规则会产生可选字段缺失 warning（保留记录，字段置 `None`）。 |
| 第 4 组（检索） | raw job schema 未冻结；检索开发在 `feature/group4-job-retrieval` 分支进行。本模块按 §3 超集假设容错。 |
| 第 6 组（推荐） | `recommendation_service.py` 为 TODO stub；岗位输入契约以 frozen `JobPosting` 为准，下游语义见 §9 缺口 3/4。 |

## 3. 输入：raw job 假设格式

第 4 组的 raw job schema 尚未冻结（见 §9 缺口 1）。本模块按以下**超集假设**设计，每个字段都按可缺失处理：

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
  "freshness_status": "来源显式状态（可缺失，active/expired/unknown，大小写不敏感）",
  "fetched_at": "抓取时间（ISO-8601）",
  "source_links": ["额外来源链接（可缺失）"]
}
```

输入在代码层面按 `list[dict]`（JSON 风格）接收，模块内部逐条校验与容错：**单条数据损坏不拖垮整批**，坏记录按 §4 规则丢弃并记 warning。

## 4. 输出：JobPosting 与处理结果

`JobPosting` 采用 `jobscout/schemas/job.py` 已冻结的 pydantic 模型（schema v1，第 3 组维护），本模块不再自定义岗位模型；序列化使用 pydantic 的 `model_dump()`。缺失字段处理按 2026-09-30 成员确认的决策：**必填字段缺失 → 丢弃记录 + 记 warning；可选字段缺失 → 保留记录、字段置 `None` + 记 warning**。字段映射表：

| JobPosting 字段 | 来源与规则 |
| --- | --- |
| `job_id` | 取 raw `job_id`；缺失时用去重键（§6）生成稳定 id（规范化键的 SHA-256 前 16 位，加 `gen-` 前缀），保证同一岗位重复处理时 id 稳定。 |
| `source` | 取 raw `source`；缺失记 warning，合并后来源名取各记录非空来源的 `", "` 连接，全部缺失时为 `"unknown"`。 |
| `source_url` | **必填**：取 raw `source_url`，原样保留，不改写；缺失 → 丢弃 + warning。合并后取去重链接列表的首个（即首条记录的 `source_url`）。 |
| `title` | **必填**：去首尾空白、压缩连续空白；缺失/为空 → 丢弃 + warning（职位名是展示与去重的最低要求）。 |
| `company` | **必填**：同上清洗；缺失/为空 → 丢弃 + warning。 |
| `location` | **必填**：同上清洗；缺失/为空 → 丢弃 + warning。 |
| `salary` | 可选：MVP 保留来源原文（字符串），不做数值解析；缺失置 `None` + warning。 |
| `target_direction` | **必填**：取 raw `target_direction`；缺失 → 丢弃 + warning。 |
| `responsibilities` | 见 §5 解析策略；无来源时为 `[]`。 |
| `required_skills` | 见 §5 解析策略；无来源时为 `[]`。 |
| `posted_at` | 可选：解析 ISO-8601 为 timezone-aware datetime；缺失或解析失败置 `None` + warning。 |
| `expiry_at` | 可选：同上。 |
| `freshness_status` | 不直接继承 raw 值，由 §7 规则重新判定（raw 的显式状态仅作为判据之一）。 |
| `fetched_at` | **必填**：取 raw `fetched_at` 并解析；缺失或解析失败 → 丢弃 + warning。**有效记录永不丢失抓取时间**，满足"必须保留抓取时间"的约定。 |
| `source_links` | 初始化为 `[source_url]` 与 raw `source_links` 的并集（去重、保持插入顺序）；合并时取全记录并集。 |

服务返回 `ProcessingResult`（`NamedTuple`，字段 `jobs: list[JobPosting]` 与 `warnings: list[str]`），既支持属性访问，也支持解包：`jobs, warnings = process_jobs(raw_jobs)`。warnings 最终写入 `AgentState.warnings`（append reducer 汇总各节点输出）。

## 5. 职责与技能解析策略（确定性优先）

不引入任何未经团队确认的外部模型或依赖。按数据来源分三级处理：

1. **来源已结构化**（raw 带 `responsibilities` / `required_skills` 列表）：逐项去空白、丢空项、按大小写不敏感去重，保留原始写法。
2. **仅有 JD 原文**（`description` 文本）：
   - 职责：识别常见小节标题（`Responsibilities` / `What you'll do` / `Your role` / `Duties` 等，大小写不敏感），收集该小节内的项目符号行（`•`、`-`、`*`、`·`、数字序号开头）与短行；找不到小节时职责留空（不做全文猜测）。
   - 技能：优先取 `Requirements` / `Qualifications` / `Skills` 等小节的条目；无任何技能小节时，用内置**技能词表**（常见语言/框架/工具，随仓库维护，属于数据而非新依赖）对全文做大小写不敏感的词边界匹配作为兜底。
3. **两者皆无**：合并后职责与技能仍为空列表时记 warning，不做无依据补全。

LLM 辅助提取作为后续可选增强，需团队确认后另行立项，不在本模块默认路径内。

## 6. 去重键与跨来源合并规则

**规范化函数**（用于 title/company/location）：小写化 → 去除非字母数字字符（标点、符号）→ 压缩空白。

**去重键** = `(norm(company), norm(title), norm(location))`：同一来源内键重复同样合并；由于 company/title/location 均为必填，去重键不会出现空分量。

**合并规则**（同键多条 → 一条 JobPosting）：

- 基准记录：首条记录；标量字段（`title`/`company`/`location`/`target_direction`/`job_id`）取基准记录值（必填字段已经 §4 校验，基准必有值）；
- `salary`：取各记录首个非空值；
- `responsibilities` / `required_skills`：全记录并集，按大小写不敏感去重，保持首次出现顺序；
- `source_links`：全记录链接并集，保持插入顺序——**重复岗位只出现一次，但保留各来源链接**；`source_url` 取并集首个；
- `source`：各记录非空来源名以 `", "` 连接（如 `jobsdb, linkedin`）；全部缺失为 `"unknown"`；
- `fetched_at`：取最大者（最新一次抓取）；
- `posted_at`：取非空值中最早者；`expiry_at`：取非空值中最早者（保守，宁可早判过期）；
- `freshness_status`：合并完成后按 §7 重新判定；
- `job_id`：基准记录的来源 id；基准无 id 时按 §4 规则生成。

## 7. 时效判定规则

判据只使用数据内证据：`expiry_at` 与来源显式 `freshness_status`。以处理时刻 `now`（可注入，测试用固定值）比较：

| 条件（按优先级） | 判定 |
| --- | --- |
| `expiry_at < now` | `expired` |
| `expiry_at >= now` | `active` |
| 无 `expiry_at`，合并记录中存在显式 `expired` 状态 | `expired` |
| 无 `expiry_at`，合并记录中存在显式 `active` 状态（且无 `expired`） | `active` |
| 其他一切情况（无任何时间证据与显式状态、状态不可识别） | `unknown` |

- 显式状态冲突时 `expired` 优先（保守）；`unknown` 显式状态不影响判定；
- **`posted_at` 单独绝不作为 `active` 的证据**（早期设计的新鲜窗口 N=30 天方案已废弃，见 §9 缺口 5 的关闭说明）；
- **无法确认时一律 `unknown`，绝不假装 `active`**；
- 时间字段统一解析为 timezone-aware datetime；`expiry_at` 无法解析按缺失处理并记 warning。

## 8. 模块接口设计（签名以代码为准）

`services/job_processing_service.py`：

```python
class ProcessingResult(NamedTuple):
    jobs: list[JobPosting]
    warnings: list[str]

def process_jobs(
    raw_jobs: list[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> ProcessingResult:
    """标准化 → 解析 → 去重合并 → 时效判定。

    now 可注入以便测试；为 None 时取当前 UTC 时间。
    必填字段缺失的记录丢弃并记 warning，不中断整批。
    返回值支持解包：jobs, warnings = process_jobs(...)。
    """
```

`graph/nodes/process_jobs.py`：从 `AgentState` 读取 `raw_jobs`，调用 `process_jobs`，返回状态更新 `{"normalized_jobs": [...], "warnings": [...]}`（frozen 契约键；`warnings` 只返回本次新增，由 `operator.add` reducer 合并）。节点不含业务逻辑，签名类型为 `AgentState -> ProcessJobsNodeUpdate`。

## 9. 契约缺口（待确认清单）

1. **raw job schema 未冻结**（待第 4 组）：§3 是本组的超集假设。需确认：是否提供 `description` 原文、`posted_at`/`expiry_at` 的覆盖率与格式、显式 `freshness_status` 是否存在、`source` 命名清单、`target_direction` 由谁写入。注意：schema v1 将 `target_direction`/`location`/`source_url` 定为必填，本模块对缺失记录一律丢弃，若第 4 组来源覆盖率低会造成较高丢弃率，联调时需核对。
2. **跨方向重复岗位的 `target_direction`**（待第 6 组）：字段为单值且必填，合并跨方向重复时取基准记录值；若推荐侧需要"一岗多方向"，需契约扩展（如 `target_directions: list`）。
3. **过期岗位的下游语义**（待第 6 组）：本组输出保留全部岗位含 `expired`/`unknown` 并如实标记；是否过滤、如何降权由推荐侧决定。

**已关闭**（2026-10-02 记录）：

- ~~JobPosting 未落地~~ → schema v1 已冻结（commit `0e3a007`），本模块已迁移至官方 pydantic 模型。
- ~~AgentState 未定义~~ → 已冻结（commit `fc2b26f`）：raw 与处理后岗位分键（`raw_jobs` / `normalized_jobs`）。
- ~~处理 warnings 的承载位置~~ → 写入 `AgentState.warnings`；append reducer 已由第 3 组落地（commit `be26469`），多节点写同键不再覆盖。
- ~~新鲜窗口 N=30 天~~ → 不采用：成员确认"仅凭 `posted_at` 绝不推断 `active`"，§7 已按此修订，无可配置参数遗留。

## 10. 测试计划（全部使用固定 Mock，不调用外部服务）

| 场景 | 样例设计 | 断言要点 |
| --- | --- | --- |
| 正常转换 | 字段完整的 raw job（含结构化职责/技能） | 字段映射正确；`source_url`/`fetched_at` 原样保留；`source_links` 初始化正确；无 warning；`model_dump(mode="json")` 可序列化 |
| 返回值解包 | 正常记录 | `jobs, warnings = process_jobs(...)` 可用；属性访问同样有效 |
| 必填字段缺失 | 分别缺 `title`/`company`/`source_url`/`location`/`target_direction`/`fetched_at`（含 `fetched_at` 无法解析）的记录 | 记录丢弃；warning 含记录标识与缺失字段名；正常记录照常输出 |
| 可选字段缺失 | 缺 `salary`/`posted_at`/`expiry_at` 的记录 | 不抛异常；字段为 `None`；每项产生 warning |
| 来源缺失 | 缺 `source` 的记录 | 保留记录；`source == "unknown"`；产生 warning |
| 职责技能均无来源 | `responsibilities`/`required_skills` 为空且无 `description` | 字段为空列表；产生 warning |
| 重复岗位合并 | 两来源同一岗位，title/company 含大小写、空白、标点差异 | 输出仅一条；`source_links` 含两个链接；职责/技能取并集；`fetched_at` 取最新；`source` 为 `", "` 连接 |
| 时效-过期 | `expiry_at` 早于 now | `expired`（显式 `active` 状态不能推翻 `expiry_at`） |
| 时效-活跃 | `expiry_at` 晚于 now | `active`（now 注入固定值） |
| 时效-显式状态 | 无 `expiry_at`，raw 显式状态大小写混合 | 按显式状态判定 |
| 时效-未知 | 无 `expiry_at` 且无显式状态；仅有 `posted_at` | `unknown`；绝不输出 `active` |
| JD 文本解析 | 只有 `description`（含职责/技能小节；或无小节时走技能词表兜底） | 职责/技能被确定性提取 |
| 空输入 | `[]` | 返回 `([], [])` |
| 节点行为 | 含/不含 `raw_jobs` 的状态 | 输出 `normalized_jobs` 与 `warnings` 键；缺键时输出空列表 |
| 共享 Mock 样例 | `data/mock_jobs.json` | 时效为 `unknown`；来源链接与抓取时间保留；可选字段缺失产生 warning 且字段为 `None` |

边界样例独立构造，不依赖 `data/mock_jobs.json` 的单条记录。
