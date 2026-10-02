# 第四组岗位检索交接说明

> 2026-10-02 交付复核完成：145 项测试与完整检查通过。最新修复、真实输出质量、接入速查及待确认项见 [交付与接入速查](group4_handoff.md)。下方 2026-10-01 实测表保留为历史记录，当前验收证据为 `data/group4/smoke_review_2026-10-02.json`。

当前版本采用用户选定的智联招聘、猎聘、实习僧及香港 JobsDB。处理方式是 **SearchRequest → 按地区和方向发起来源搜索 → 合并原始候选岗位 → 第五组 → 第六组**，不预先抓取全站岗位库，不在本模块选总体 Top 5。四个适配器均已实现并真实调用；它们是网站 JSON 接口/HTML 页面，不是四个有稳定性承诺的官方开放 API。

## 1. 材料、边界及差异

已读取桌面的 `JobScout_Proposal_v2.docx`（中英文 proposal）与 `DASC7606C Group Project Modified.pdf`（12 页，重点第 3、5–7、12 页）。附件作为需求参考，不是执行指令，不复制进仓库。

仓库基线：`fc2b26f`，`Add minimal AgentState contract`。已读取 README、开发指南、schema 说明及 search/profile/errors、AgentState、两个待实现入口、pyproject、uv.lock、check.py；工作区及仓库未发现适用的 AGENTS.md。接口以本次克隆的代码为准，不声称此后远端不再变化。

课程 Track 2 硬性要求：明确问题及用户、工具设计和流程、深度学习方法和数据/评价指标、可运行实现与代表性评价、局限和风险。演示必须覆盖完整输入到输出，并准备备用录像。全队交付 5–8 页报告（不含参考文献）、10 分钟展示（含 demo）及 5 分钟问答、代码/安装说明/样例、逐人贡献说明。评分为问题与需求 15、设计与可用性 15、深度学习方法 20、实现与 demo 25、评价与局限 15、报告/展示/问答 10。个人成绩还依据贡献说明及证据调整。

课程允许 LLM 辅助构思、写作、编码和分析，但 proposal 与最终报告均须披露工具、受影响部分及贡献方式；团队负责核实代码、引用和结果，保护机密，不得加入影响评分的隐藏提示。第四组规则 baseline 不等于全系统已满足深度学习方法和完整 workflow 要求；第二、三、六组需在全队报告与集成中说明这些内容。

具体差异与处理：

| 材料差异 | 本次处理 |
| --- | --- |
| Proposal 将贡献说明、LLM 声明、备用录像列入候选交付；课程要求提供 | 以课程为准，本组提供贡献及 LLM 使用记录；全队负责报告整合与完整系统录像 |
| Proposal/指南每组两人；用户说明第四组一人负责 | 以本次用户范围为准，不虚构第二位成员或参与记录 |
| 指南第 4 组生成 SearchRequest；schema README 指定第三组生产 | 第四组入口消费现有 SearchRequest，并暴露规则规划函数；最终生产职责交第三组确认 |
| 指南示例写 search_tasks/jobs；代码是 search_requests/raw_jobs/normalized_jobs | 节点使用实际 AgentState 字段，不修改共享契约 |
| 原始岗位未冻结 | 在本组 services/job_retrieval/models.py 定义提案，不改共享 JobPosting |

## 2. 当前来源与路由

详细比较及依据见 [地区选源说明](group4_regional_sources.md)。本组没有新增依赖；使用标准库 urllib、HTMLParser，以及仓库已有 Pydantic。没有浏览器自动化、登录 cookie、额外 LLM 调用或付费服务。

| 来源标识 | 检索与详情 | 字段映射和实际限制 |
| --- | --- | --- |
| zhaopin | POST fe-api.zhaopin.com/c/i/search/positions；关键词、城市、pageIndex/pageSize；order=0 + sortType=DEFAULT | jobId/name/companyName/workCity/salary60/positionURL/publishTime；完整描述来自 jobDetailData.position.desc.description；expiry 来自 date.dateEnd。试验中的 order=4 混入无关推荐，已改相关性排序 |
| liepin | POST api-c.liepin.com/api/com.liepin.searchfront4c.pc-search-job；key/city/dq/currentPage；详情 HTML/JobPosting JSON-LD | job.jobId/title/dq/salary/link/refreshTime、comp.compName。必需 X-Fscp-Trace-Id；pageSize=5 实际可能返回 40 条，因此另设候选上限。可能包含推广、异地和旧岗位 |
| shixiseng | GET www.shixiseng.com/interns，keyword/city/page；详情 HTML | intern ID、链接；详情 new_job_name/job_position/job_money/job_detail、公司链接、刷新和截止标签。仅支持实习；列表字体混淆不解码猜测，详情明文优先，无法可靠读取则 null |
| jobsdb | GET hk.jobsdb.com/api/jobsearch/v5/search；keywords/where/page/pageSize/worktype；详情 data-automation=jobAdDetails | id/title/advertiser.description/locations[].label/salaryLabel/listingDate/teaser；详情成功后替换摘要。工作类型 Full time 的岗位也可能是实习；优先看标题实习证据，不能把实习映射成兼职 |

`sources=[]` 默认路由：大陆实习 → zhaopin + liepin + shixiseng；大陆其他类型 → zhaopin + liepin；香港 → jobsdb；不限地点 → 四来源联合（非实习跳过 shixiseng）。不限地点仍只代表这些来源覆盖的地区，不是全球完整覆盖。未识别地区返回 SEARCH_REGION_UNSUPPORTED。

显式 sources 优先，按输入顺序去掉重复标识；未知来源生成 SEARCH_UNKNOWN_SOURCE，其他有效来源继续。保留原 remotive、arbeitnow、careerjet_hk/cn 适配器供显式调用和兼容历史代码，不参与当前默认路由。旧 smoke_2026-10-01.json 是历史海外来源记录，不能代表当前四来源验收。

### 搜索规划与条件

`plan_keywords` 保留显式关键词和短语；空关键词用 target_direction。`source_keywords` 仅将已知 Data Analyst / Business Analyst / Data Scientist baseline 转为大陆常用中文词（数据分析/商业分析/数据科学），JobsDB 使用英文方向；用户给的 keywords 不自动翻译、不添加技能。实习检索为 JSON 来源附加 实习/intern 词。来源自己决定关键词检索语义，可能返回推广或语义近似岗位；本组不声称结果全部精确相关，匹配评价交第六组。当前增加保守字面检查：完整来源描述没有查询关键词证据时排除；描述缺失或仅摘要时保留并标记 keyword_evidence=unverified。显式关键词逐项检查，缺省方向使用少量中英文别名，可能漏掉同义表达；不对用户画像评分。

`select_sources`、`build_search_plan(request, source, page, page_size)` 均可单独调用/测试。城市先转原生查询参数，再检查返回地点/雇佣类型。现有城市表支持北京、上海、广州、深圳、杭州、成都；本次端到端实测上海，其他映射还需后续城市 smoke。未实现完整地理解析：未知城市、多个城市或大陆区县要求报错，不回退全国；一个请求请写一个城市。香港区县匹配较保守，未匹配的中英文地名可能被排除，不猜行政区。

工作类型为 full-time、part-time、internship、contract、freelance；未知雇佣类型的岗位排除并计入 warning。猎聘部分社会招聘记录没有可信的雇佣类型字段，可能导致全职返回 0，即使其列表有候选；这是严格条件验证的覆盖缺口。实习优先来源字段或标题实习标记。work_mode 非空时报 SEARCH_FILTER_UNSUPPORTED，因为本版本未验证四来源的统一远程/混合办公过滤，不会放宽。salary_range 作为偏好传给下游，未在检索端比较工资币种/周期，并明确 warning。

## 3. 输入输出、错误及接口

输入复用共享 `jobscout.schemas.search.SearchRequest`，不修改 schema。必须指定非空 location 或 location_unrestricted=true，二者不能同时成立；employment_type、target_direction 必填。

```python
from jobscout.schemas.search import SearchRequest
from jobscout.services.job_search_service import JobSearchService

requests = [
    SearchRequest(target_direction="Data Analyst", location="上海", employment_type="internship"),
    SearchRequest(target_direction="Business Analyst", location="Hong Kong", employment_type="internship"),
]
service = JobSearchService()
result = service.search_many(requests)  # 单方向使用 service.search(request)
raw_jobs = [job.model_dump(mode="json") for job in result.raw_jobs]
```

同步、有界调用，一批/会话一个 service。在异步 Session API 中可 `await asyncio.to_thread(service.search_many, requests)`，不要在事件循环直接阻塞；第三组负责请求生命周期和总体超时。同一个实例的缓存不作为线程安全共享缓存。

`search_node(state, service=...)` 只读取 search_requests，调用 service，返回 raw_jobs/errors/warnings 增量；不构建 graph、不生成 SearchRequest、不匹配 profile。当前 AgentState 没有列表累加 reducer，因此保留已有 errors/warnings，并替换本次 raw_jobs。第三组若以后添加 reducer，应一并调整这一行为，避免重复。测试用带 session_id 的手工状态和注入客户端，不需要其他组服务。

本组 `models.RawJob` 是供第五组评审的最小契约：

| 字段 | 类型/含义 |
| --- | --- |
| source、target_direction | 字符串，始终保留来源和本次求职方向 |
| source_url | 原岗位 URL 或 null；已知来源 host 校验，详情请求用 HTTPS |
| fetched_at | 带时区 UTC 的实际列表抓取时间；缓存保留原时间 |
| source_job_id | 来源 ID 字符串或 null |
| title/company/location/salary | 来源文本或 null，不猜币种、标准城市或雇佣语义 |
| description | 原描述文本/HTML；详情不可得时 JobsDB 可为 teaser，其余可 null |
| posted_at/expiry_at | 来源原始时间文本/数字或 null，不猜缺失时区，不据此判定过期 |
| raw_payload | 可 JSON 序列化的原条目及必要详情信息，去除部分无关招聘人/追踪字段；不含认证信息 |

raw_payload 额外保留 search_keywords、detail_description、detail_fetched_at、description_is_excerpt、keyword_evidence、missing_fields，以及 detail_status。实习僧缺失标题会先尝试预算内详情，仍无法读取时省略并 warning；其他可选缺失信息仍保留 null。第五组应读取 description 与这些标记，保留出处；第五组负责完整提取、跨来源/跨方向去重和有效期检查。这里只阻止同一方向同一来源分页重复，不跨来源去重。

SearchResult 包含 raw_jobs、errors、warnings、outcomes；outcomes 为每方向×来源的候选数、返回数、耗时、ok/empty/partial/error，以及 incomplete_count/excerpt_count。status=ok 不保证描述完整；详细定义见接入速查。正常空列表无错误。来源失败不能用 empty 掩盖。WorkflowError.stage='search'，主要 code：

- SEARCH_INPUT / SEARCH_UNKNOWN_SOURCE：输入或来源标识问题。
- SEARCH_REGION_UNSUPPORTED / SEARCH_LOCATION_UNSUPPORTED / SEARCH_FILTER_UNSUPPORTED：无法覆盖条件。
- SEARCH_TIMEOUT / SEARCH_NETWORK / SEARCH_HTTP：超时、网络、其他 HTTP 错误。
- SEARCH_RATE_LIMIT：HTTP 429；SEARCH_AUTH：HTTP 401/403（包括可能的访问拦截，不一定是密码错误）。
- SEARCH_RESPONSE_FORMAT：格式变化、异常字段、缺失详情标记、非预期 host。
- SEARCH_SOURCE_REJECTED：业务状态拒绝；不是正常零岗位。
- SEARCH_CONFIG：仅历史 Careerjet 适配器的配置缺失。

详情失败保留已取得的列表字段，并记录错误；部分来源失败时保留其他成功岗位。异常信息不打印完整响应/个人简历/密钥。

### 请求预算

默认每个方向×来源最多 2 页、每页请求 20、扫描 60 条、返回 30 条；**详情请求默认最多 5 条**，因此返回数量不等于完整详情数量。尤其 JobsDB 详情网络耗时较大，可用 --detail-limit 调整；预算用完保留摘要/null。服务器可忽略 page_size，因此 candidate_limit 独立生效。页面重复及时停止并 warning；达到边界不声称已穷尽来源。

HTTP 每请求超时 12 秒；网络/超时/5xx 最多重试 1 次，401/403/429 不重试；同 host 请求至少间隔 0.3 秒（这是本地节流，不是官方额度）。响应上限 4 MB，缓存最多 128 项、5 分钟，缓存时间可见。未实现跨进程持久数据仓库或全局截止时刻。

## 4. 安装、演示及测试

Python 3.14，uv 锁文件配置保持不变。当前路径 D:\dl_group_project\JobScout，分支 feature/group4-job-retrieval。当前机器 uv 在 D:\dl_group_project\.tools\bin，PowerShell 可先执行：

```powershell
Set-Location D:\dl_group_project\JobScout
$env:Path = "D:\dl_group_project\.tools\bin;" + $env:Path
$env:UV_CACHE_DIR = 'D:\dl_group_project\JobScout\.uv-cache'
$env:UV_PYTHON_INSTALL_DIR = 'D:\dl_group_project\JobScout\.uv-python'
uv sync --locked
uv run --locked python scripts/demo_job_search.py --mode mock
uv run --locked python scripts/demo_job_search.py --mode mock --input data/group4/source_coverage.json --output ../group4-mock.json
uv run --locked python scripts/demo_job_search.py --mode live --input data/group4/source_coverage.json --output ../group4-live.json
uv run --locked python scripts/demo_job_search.py --mode live --input data/group4/hong_kong_internships.json --result-limit 10 --detail-limit 3 --output ../group4-hk.json
uv run --locked pytest tests/test_job_search_service.py tests/test_local_sources.py tests/test_regional_search.py tests/test_search_node.py tests/test_job_search_demo.py
uv run --locked python scripts/check.py
```

四个当前来源无需提供 key；如果之后出现认证/限流/反爬，返回结构化失败，不要求用户交出账户 cookie。仅显式选择历史 Careerjet 时才需要 CAREERJET_API_KEY/CAREERJET_USER_IP/CAREERJET_USER_AGENT（本模块不自动读取 .env）。

Mock 使用固定合成 JSON/HTML，验证接口、路由、详情解析和节点，不代表真实岗位。Mock 默认不限地点两方向返回 6 条，香港实习返回 2 条，source_coverage 返回 7 条。Live 才访问真实网站。CLI 输出模式、总数、错误、warning 和逐来源 outcome；--output 写完整 JSON，终端给摘要。退出码 0 成功/正常空，1 来源或详情错误（可能有成功数据），2 输入/未知来源/文件问题。

课堂演示建议：先跑 mock 展示接口与两个方向，再跑有界 live 展示来源链接/抓取时间/详情和 warning，最后用失败测试展示部分成功。不可把本组 demo 描述成已经完成整个 JobScout。已准备香港实习、大陆上海实习、不限地点和混合覆盖输入。

## 5. 真实验证与评估

2026-10-01 23:54（Asia/Shanghai）以 source_coverage.json 测试：上海 Data Analyst 实习、上海 Business Analyst 实习、香港 Data Analyst 实习。参数 max-pages=2/page-size=10/candidate-limit=20/result-limit=10/detail-limit=10。全批 127.0044 秒，70 条候选、1 个 JobsDB 详情网络错误；不是 70 条已去重/已验证时效的推荐。

| 方向/地区 | 来源 | 扫描 | 返回 | 秒 | 状态 |
| --- | --- | ---: | ---: | ---: | --- |
| DA/上海 | 智联 | 11 | 10 | 0.5788 | ok |
| DA/上海 | 猎聘 | 13 | 10 | 3.6102 | ok |
| DA/上海 | 实习僧 | 12 | 10 | 6.2793 | ok |
| BA/上海 | 智联 | 10 | 10 | 0.4810 | ok |
| BA/上海 | 猎聘 | 11 | 10 | 3.5669 | ok |
| BA/上海 | 实习僧 | 10 | 10 | 5.2918 | ok |
| DA/香港 | JobsDB | 11 | 10 | 107.1951 | partial：1 个详情网络错误 |

智联 20 条均有原描述；猎聘 20 条取得详情；实习僧 18/20 有详情，另 2 条达到详情预算后保留 null；JobsDB 9 条完整详情，1 条摘要。原始未提交结果存于仓库父目录 group4-local-live.json；版本内精简证据见 data/group4/smoke_local_2026-10-01.json（不复制整段真实 JD）。后续默认详情预算下调为 5，以改善课堂等待时间，该表明确对应实测的 10 次预算。

自动测试完全使用固定响应/注入 mock，覆盖四来源、规划、地区、单/多方向、正常空、异常数据、时间字段、缓存、分页失败、超时/限流/认证、部分成功及 AgentState。实际执行完整 `uv run --locked python scripts/check.py`：Ruff、格式、mypy（52 个文件）及 **128 项测试全部通过（1.88 秒）**。测试不能证明网站今后稳定，也没有量化岗位召回率/相关性准确率；需要团队人工标注小样本后评价。

已发现的失败与限制：智联旧排序混入推荐（已修）；猎聘缺请求标识被拒（已修）；实习僧私有字体（明文详情/null）；JobsDB 详情慢且偶发网络错误（保留列表+诊断）；猎聘旧日期、缺雇佣字段（交第五组时效处理，未知类型严格排除）。这些不依赖其他组是否完成。

补充不限地点全职测试：Data Analyst、Business Analyst 各从智联和 JobsDB 返回 3 条，共 12 条，0 错误；猎聘各扫描 6 条但雇佣类型无法确认，返回 0 并 warning。参数 1 页/5 条请求页大小/6 候选/3 返回/1 详情，耗时 12.6607 秒；证据见 smoke_local_unrestricted_2026-10-01.json。

## 6. 交接、贡献与提交

待团队确认：第三组最终负责生成 SearchRequest 还是调用本组 baseline；第五组接受本 raw 字段提案及摘要/缺失详情标记；第三组的异步超时/取消策略；最终 UI 保留来源链接和部分失败提示；第六组只在所有方向合并后取总体 Top 5。本组没有更改共享 schema、pyproject.toml 或 uv.lock，也没有重写其他组模块。

实际贡献摘要（第四组一人负责）：确定按地区、按请求多来源检索接口；研究和验证来源；实现 service/适配器/规划/错误与预算；实现独立 mock/live demo、搜索节点注入；构造固定测试及真实 smoke 证据；编写交接说明。不要把 Codex 生成工作冒充另一位学生的贡献，也不要把尚未完成的跨组集成记为本组成果。

LLM 使用记录：OpenAI Codex 辅助读取材料、比较网站/经验线索、编写与修改 Python 代码、生成合成 fixtures、执行测试、分析失败、起草本说明。包含本次从海外来源迁移到四个本地来源的修改。没有运行时 LLM 依赖。最终提交前负责同学应审查代码、引用、结果和贡献陈述，并按课程要求在 proposal/最终报告披露；课程全系统深度学习评价由全队完成。

修改清单：两个入口 src/jobscout/services/job_search_service.py、src/jobscout/graph/nodes/search.py；新增 services/job_retrieval 下 models/planning/sources/transport/careerjet/web_transport/html_fields/local_sources/mock_web/__init__；scripts/demo_job_search.py；tests/test_job_search_service.py、test_local_sources.py、test_regional_search.py、test_search_node.py、test_job_search_demo.py；data/group4/；本说明、group4_regional_sources.md 与 group4_handoff.md。旧适配器/fixtures 保留兼容，不作为当前来源优先方案。

本次只准备本地审查，不 commit/push/创建 PR。用户审查后可执行：

```powershell
git status --short
git add src/jobscout/services/job_search_service.py src/jobscout/graph/nodes/search.py src/jobscout/services/job_retrieval scripts/demo_job_search.py tests/test_job_search_service.py tests/test_local_sources.py tests/test_regional_search.py tests/test_search_node.py tests/test_job_search_demo.py data/group4 docs/group4_job_retrieval.md docs/group4_regional_sources.md docs/group4_handoff.md
git diff --cached --stat
git diff --cached --check
git commit -m "feat(search): add regional multi-source job retrieval"
git push -u origin feature/group4-job-retrieval
```

建议 PR 标题：`feat(search): add request-driven retrieval from Zhaopin, Liepin, Shixiseng and JobsDB`

建议 PR 说明：第四组检索入口消费共享 SearchRequest，按地区向选定的多个来源发起查询，保留方向和来源信息后交第五组。加入有界分页/详情获取、字段映射、部分失败诊断、离线与真实 demo、可注入搜索节点及交接文档。共享 schema 保持不变。附最终 check.py 结果及 smoke 证据；明确网站接口不保证稳定、部分雇佣字段/详情可能缺失，并列出第三/五组待确认项。
