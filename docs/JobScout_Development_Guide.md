# JobScout 开发文档

*Developer Guide for the JobScout Agent Prototype*

本文档与 proposal 配套使用。Proposal 说明项目要做什么；本文档说明组员需要如何共同完成一个可运行的 demo。本文档中的接口和流程是当前开发基线，若团队后续修改，必须同步更新所有相关模块。

# 1. 项目概览

**Project track：**Track 2: Agentic Framework Design

**项目名称：**JobScout: A Personalized Job Discovery and Recommendation Agent

**核心目标：**用户提供简历、个人描述和一个或多个求职方向后，系统检索当前岗位，完成岗位信息处理和用户匹配，并返回整体 Top 5 岗位。

**目标用户：**已经有一定求职思路的本科生、硕士生和跨行业求职者。用户需要提出至少一个求职方向；JobScout 不负责替完全没有方向的用户从零决定职业。

**核心展示：**本地 HTML 页面展示从用户输入、必要信息追问，到最终岗位推荐的完整流程。

## 1.1 当前 MVP 输出

每个推荐岗位至少展示以下字段：

- 职位名称、公司名称、工作地点；
- 薪资信息（如来源提供）；
- 岗位来源和链接；
- 岗位主要职责和关键技能要求；
- 用户可能缺少的技能；
- 申请该岗位前的建议；
- 岗位状态：active、expired 或 unknown。

当前不要求在前端显示数字化匹配分数、强匹配标签或单独的推荐理由字段；后续可根据 demo 效果扩展。最终返回总体 Top 5，而不是每个方向各返回 5 个。

# 2. 端到端用户流程

用户输入  
→ 用户画像提取  
→ 必要信息检查  
→ 缺失/冲突信息追问（必要时循环）  
→ 生成搜索条件  
→ 按求职方向分别检索多个来源  
→ 岗位标准化与 JD 信息提取  
→ 重复岗位合并  
→ 岗位时效性检查  
→ 用户-岗位匹配与准备建议  
→ 全局 Top 5  
→ HTML 展示

## 2.1 用户输入

初版支持以下输入组合：

- 简历上传；
- 用户直接描述个人背景；
- 简历与个人描述同时提供；
- 一个或多个目标职位/职位方向，以及用户已知的搜索需求。

简历和文字描述出现冲突时，系统应识别冲突并向用户确认；未经确认的信息不能静默地当作完全可靠的事实。

## 2.2 信息确认门槛

建议将以下信息作为开始搜索前的最低必要信息；如果团队决定改变字段，必须同步修改第二组和第三组的接口：

| 信息 | 处理规则 |
| --- | --- |
| 用户背景来源 | 至少提供简历或个人描述之一。 |
| 目标方向 | 至少一个职位或职位方向；不设用户可见的数量上限。 |
| 工作地点 | 具体地点，或用户明确表示地点不限。 |
| 工作类型 | 例如 full-time、part-time 或 internship。 |
| 其他偏好 | 薪资、行业、工作模式、愿意学习的技能等建议提供但可跳过。 |

必要信息未确认时，系统先追问，不开始岗位检索。必要信息确认后直接开始搜索，不再要求用户额外确认系统生成的搜索条件。

# 3. 系统架构

```text
HTML Frontend
      ↕  JSON / session messages
Session API / LangGraph entrypoint
      ↓
LangGraph StateGraph（状态、顺序、条件分支、暂停/恢复）
      ├─ Profile & Clarification nodes
      ├─ Search planning and retrieval tools
      ├─ Job normalization / deduplication / freshness modules
      └─ Matching and recommendation nodes
      ↓
RecommendationResult → Frontend
```

架构采用混合方式：需要理解文本和生成内容的部分可以使用 LLM-based Agent nodes；岗位去重、状态分类、Top 5 截取、字段校验和输出格式等稳定任务优先使用普通程序或规则。LangGraph node 不等于 Agent，component 也不一定是独立 Agent。

## 3.1 LangGraph 节点建议

| 阶段/节点 | 主要职责 | 建议实现 |
| --- | --- | --- |
| `ingest_input` | 接收简历、文字描述和求职需求。 | 普通代码/API |
| `extract_profile` | 提取用户画像和结构化需求。 | LLM structured output |
| `validate_profile` | 检查必要字段和冲突。 | 规则 + LLM 辅助 |
| `clarify` | 生成问题并等待用户回答。 | LLM + interrupt/resume |
| `update_profile` | 合并回答，更新确认状态。 | 普通代码 + LLM |
| `plan_search` | 将方向转换为各来源搜索条件。 | LLM structured output |
| `retrieve_jobs` | 按方向调用多个来源。 | API/web tools |
| `process_jobs` | 标准化并提取 JD 字段。 | 普通代码 + LLM |
| `deduplicate/freshness` | 去重和状态检查。 | 规则/API/普通代码 |
| `recommend` | 匹配、技能差距、准备建议、Top 5。 | 规则 baseline + LLM |
| `format_output` | 生成前端可渲染的结果。 | 普通代码 |

# 4. 共享数据接口

三类核心数据结构必须在各组开始编码前确定。下面是建议字段；字段名称可以调整。

## 4.1 UserProfile

```json
{
  "profile_id": "string",
  "source": {"resume": true, "description": true},
  "education": [],
  "skills": [],
  "internships": [],
  "projects": [],
  "target_directions": [],
  "preferences": {
    "location": null,
    "employment_type": null,
    "salary_range": null,
    "work_mode": null,
    "industry": null
  },
  "confirmed_fields": [],
  "missing_required_fields": [],
  "conflicts": []
}
```

第二组负责生成和更新该结构；第三组只负责根据状态决定流程走向，不重复实现画像解析逻辑。

## 4.2 JobPosting

```json
{
  "job_id": "stable-or-generated-id",
  "source": "source-name",
  "source_url": "https://...",
  "title": "string",
  "company": "string",
  "location": "string",
  "salary": null,
  "target_direction": "string",
  "responsibilities": [],
  "required_skills": [],
  "posted_at": null,
  "expiry_at": null,
  "freshness_status": "active|expired|unknown",
  "fetched_at": "timestamp",
  "source_links": []
}
```

第五组负责输出标准化 JobPosting；第四组可以先输出 raw job，再由第五组转换。重复岗位合并后应保留多个来源链接。

## 4.3 RecommendationResult

```json
{
  "session_id": "string",
  "generated_at": "timestamp",
  "jobs": [
    {
      "job": { /* JobPosting */ },
      "missing_skills": [],
      "preparation_suggestions": []
    }
  ],
  "warnings": []
}
```

第六组负责生成该结构；前端只依赖该结构展示结果，不应直接读取内部 LLM 响应。

## 4.4 其他必须约定的接口

- **SearchRequest：**包含 `target_direction`、`keywords`、`location`、`employment_type` 以及可选薪资和来源参数。
- **ClarificationMessage：**包含 `question`、`field`、`reason`、`required` 和 answer 状态。
- **AgentState：**LangGraph 内部状态，至少保存 `session_id`、`messages`、`UserProfile`、`search_tasks`、`jobs` 和当前阶段。
- **统一错误格式：**至少包含 `code`、`message`、`stage` 和可选 `details`，便于前端展示和调试。

# 5. 六个代码小组的开发说明

每组 2 人共同编码和测试。一人后续担任 Report Liaison，另一人担任 Presentation Liaison；这两个角色不减少任何成员的代码责任。

## 第 1 组：前端与交互

负责把 Agent 做成可操作的本地 HTML demo。

- 实现简历上传、个人描述输入、求职方向和偏好输入。
- 实现 Agent 追问界面、用户回答提交、加载状态和错误提示。
- 展示 Top 5 岗位及所有约定字段，包括链接、技能差距和准备建议。
- 只依赖约定的 JSON/API，不在前端复制画像解析或推荐逻辑。
- 使用 Mock RecommendationResult 在后端尚未完成时独立开发。

**完成标准：**用户可以完成输入、回答追问并看到结构化 Top 5 结果；API 失败或 unknown 岗位状态能被清晰显示。

## 第 2 组：用户画像与信息确认

负责理解用户提供的资料，并确定是否可以进入搜索。

- 实现简历文本提取和个人描述解析；具体文件格式先确定一个 MVP 支持集。
- 提取 `education`、`skills`、`internships`、`projects`、`target_directions` 和 `preferences`。
- 合并简历与文字描述；发现冲突时生成 `conflicts`，不自行覆盖。
- 检查必要字段，生成 clarification questions，并根据用户回答更新 UserProfile。
- 为完整、缺失和冲突三类输入准备 Mock JSON 和单元测试。

**完成标准：**输入可转换为统一 UserProfile；缺失或冲突信息可被明确返回；追问内容可供第三组调用。

## 第 3 组：整体 Workflow

负责 JobScout 的流程编排和系统集成，而不是重新实现其他组的业务逻辑。

- 使用 LangGraph 定义 AgentState、节点、条件边和 session 生命周期。
- 控制 extract → validate → clarify loop → search → process → recommend → format 的顺序。
- 必要信息缺失时暂停并恢复；确认后直接触发搜索。
- 调用第二组及其他小组的模块，并处理模块间数据传递和错误。
- 先用 Mock nodes 串成可运行骨架，最后替换为真实模块。

**完成标准：**单次 session 能从输入走到输出；缺失信息能暂停并继续；各模块可以被替换而不改变整体状态契约。

## 第 4 组：岗位检索

负责从外部岗位来源获取 raw job data。

- 调研并接入选定的岗位 API 或公开来源，封装为统一 retrieval tool。
- 根据每个 target direction 生成搜索关键词和 SearchRequest。
- 分别搜索各个方向，再返回带来源、链接和抓取时间的原始结果。
- 不在本组完成最终去重、匹配和 Top 5 排序。
- API keys 使用环境变量，不写入代码、Mock 或提交记录。

**完成标准：**给定一个或多个方向和搜索条件，可以返回可供第五组处理的 raw job 列表，并保留来源信息。

## 第 5 组：岗位理解与数据质量

负责把不同来源的岗位转换成可比较、可验证的 JobPosting。

- 统一职位、公司、地点、薪资、职责、技能、时间和链接字段。
- 从 JD 中提取主要职责和关键技能要求。
- 按公司、职位和地点的标准化结果合并重复岗位，并保留多个 source_links。
- 将岗位标记为 active、expired 或 unknown；无法判断时不能假装 active。
- 记录标准化和判断过程中的 warnings，便于前端和调试使用。

**完成标准：**不同来源的 raw jobs 能转换为统一 JobPosting；重复职位不会重复占用 Top 5；过期和未知状态可区分。

## 第 6 组：匹配与推荐

负责根据用户画像筛选并解释最终岗位推荐。

- 比较 skills、education、experience/projects 与 required_skills 和岗位要求。
- 考虑用户求职方向和已确认的地点、工作类型等偏好。
- 识别用户可能缺少的技能，并生成申请前的准备建议。
- 合并所有方向的岗位，筛选总体 Top 5，并保留 target_direction。
- 当前不强制显示数字匹配分数；内部可以先实现可解释的排序 baseline。

**完成标准：**给定 UserProfile 和标准化 JobPosting 列表，可以稳定输出符合 RecommendationResult 的 Top 5 结果。

# 6. 并行开发与集成顺序

六组可以并行开发，但前提是先冻结接口。功能开发可以并行，系统集成必须在接口稳定后进行。

1. **接口会议：**确定 UserProfile、SearchRequest、JobPosting、RecommendationResult、AgentState 和错误格式。
2. **Mock 阶段：**各组只使用固定 JSON，独立完成本组模块和单元测试。
3. **骨架集成：**第三组使用 Mock nodes 串起完整 LangGraph，第一组接入 Mock 前端。
4. **真实模块替换：**依次接入第二、四、五、六组模块，任何接口变化必须同步通知相关组。
5. **端到端测试：**所有组共同验证完整输入、追问、搜索、处理和 Top 5 展示。
6. **Demo hardening：**在 presentation 前检查 API、链接、岗位时效性、环境配置，并准备候选备用数据。

## 6.1 依赖关系

| 模块 | 主要依赖 | 可先并行的内容 |
| --- | --- | --- |
| 前端 | RecommendationResult、ClarificationMessage | 先用 Mock JSON 做全部页面和交互。 |
| 用户画像/确认 | UserProfile、AgentState | 先用文本样例做解析、缺失和冲突测试。 |
| Workflow | 所有模块接口 | 先用 Mock nodes 实现状态图和暂停/恢复。 |
| 岗位检索 | SearchRequest、raw job schema | 先对单一 API 或固定 JSON 做 adapter。 |
| 岗位处理 | raw job schema、JobPosting | 先用多来源样例实现标准化、去重和状态分类。 |
| 匹配推荐 | UserProfile、JobPosting、RecommendationResult | 先用固定画像和岗位集实现排序与建议。 |

# 7. 最低测试场景

每组至少准备与本组职责对应的测试；集成阶段至少通过以下场景：

| 场景 | 验收要求 |
| --- | --- |
| 完整输入 | 简历/描述、目标方向、地点和工作类型齐全，直接检索并返回 Top 5。 |
| 缺少必要信息 | 没有地点或工作类型时，系统追问，不调用岗位检索；回答后继续。 |
| 资料冲突 | 简历和文字描述对技能或目标方向不一致，系统要求确认后再搜索。 |
| 多个方向 | 分别搜索两个或多个方向，最终合并为总体 Top 5，并保留 target_direction。 |
| 重复岗位 | 同一公司、岗位、地点来自两个来源时只展示一次，并保留多个链接。 |
| 岗位状态 | 明确过期岗位不进入优先推荐；无法判断的岗位标记 unknown。 |
| 结果字段 | 每个岗位可展示职位、公司、地点、来源、职责、技能、缺失技能和准备建议。 |

# 8. 开发约定与风险控制

- 所有 API keys、个人简历和受限数据只放在本地环境变量或脱敏样例中，不提交到代码仓库。
- 外部岗位信息必须保留 source_url 和 fetched_at；不确定的信息使用 unknown 或 warning，不进行无依据补全。
- 模块之间只通过约定的数据结构通信；不要直接读取其他小组的内部变量或 LLM 原始输出。
- API 真实接入用于最终 demo；并行开发和自动化测试必须保留 Mock 数据，避免外部服务阻塞开发。
- 第三组负责集成，但所有小组共同解决集成问题；Report Liaison 和 Presentation Liaison 仍需参与编码。

# 9. 各组提交清单

| 每组必须提交 | 说明 |
| --- | --- |
| 代码模块 | 可独立运行或被调用，包含清晰入口。 |
| 接口说明 | 输入、输出、错误格式和一个 Mock JSON 示例。 |
| 测试 | 至少覆盖正常输入和一个失败/边界场景。 |
| 集成说明 | 依赖哪些组、如何被 Workflow 调用、需要哪些环境变量。 |
| 报告/演示素材 | Report Liaison 提供技术摘要；Presentation Liaison 提供演示要点和截图/流程。 |

# 10. 当前待确认事项

以下事项不阻碍各组开始 Mock 开发，但必须在真实集成前由团队确认：

- 最终使用哪些岗位 API/公开来源，以及每个来源的字段和访问限制。
- MVP 支持的简历文件格式和具体文件解析库。
- 后端服务框架、前后端通信方式和 session 持久化方式。
- 必要信息字段的最终列表，以及岗位匹配/排序的具体 baseline。
- 是否显示额外的匹配解释、数字分数或标签。

在这些事项确认前，各组应使用本文档中的接口和 Mock 数据继续开发，不要等待真实 API 或最终 UI 才开始。