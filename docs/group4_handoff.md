# JobScout 岗位检索模块使用说明

本模块接收求职搜索条件，向多个岗位来源检索，返回原始候选岗位及诊断信息。第三组调用，第五组接收原始岗位进行后续处理。

## 模块简介

岗位检索是 JobScout 求职推荐流程中的数据获取环节。调用方先提供已经确认的求职方向、地点和工作类型，本模块再向对应招聘平台发起查询，合并返回原始候选岗位。不会预先抓取全站岗位库，也不会直接读取简历。

调用关系：**上游生成 SearchRequest → 本模块按条件检索多个来源 → 第五组标准化、去重和时效处理 → 第六组匹配与总体 Top 5 → 前端展示**。

主要能力包括单方向/多方向检索、按地区选源、获取岗位列表和预算内详情、保留原始链接与抓取时间，以及报告部分失败。输出是候选数据，不是已经匹配、去重或确认仍在招聘的最终推荐。

### 使用的招聘来源与接口

| 招聘平台 | sources 标识 | 主要覆盖 | 获取方式 |
| --- | --- | --- | --- |
| 智联招聘 | zhaopin | 中国大陆岗位，包括实习和社会招聘 | 调用网站 POST JSON 搜索接口；从响应读取岗位字段和描述 |
| 猎聘 | liepin | 中国大陆岗位，包括实习和社会招聘 | 调用网站 POST JSON 搜索接口；按需读取岗位详情页 |
| 实习僧 | shixiseng | 中国大陆实习岗位 | 获取公开实习搜索页面并解析 HTML；按需读取详情页 |
| JobsDB 香港站 | jobsdb | 香港岗位，包括实习和社会招聘 | 调用网站 GET JSON 搜索接口；按需读取详情页补充列表摘要 |

这里的 JSON 接口是招聘网站自身使用的网页接口，**不是已确认提供稳定开发者契约的官方开放 API**；实习僧则主要采用 HTML 页面解析。当前四来源不需要调用方提供 API key 或登录 cookie，但使用 live 模式需要联网，网站可能限流、拒绝访问或改变页面/接口。

调用方只需使用本模块的统一 Python 接口，无需分别对接四个平台，也无需处理各网站的原始响应结构。来源字段映射和请求差异由模块内部处理；字段含义、缺失信息和覆盖限制仍需按本文约定处理。

运行使用 Python 3.14 和项目 uv 环境，不需要额外的 LLM API。获取的数据至少保留来源、求职方向和抓取时间；标题、公司、地点、薪资、描述、岗位链接及发布日期/截止日期按来源实际提供情况返回，不编造缺失内容。

## 1. 运行准备

在项目根目录执行：

```powershell
uv sync --locked
```

使用项目的 Python 3.14 环境。无需启动前端、数据库服务或完整工作流，当前四个默认来源无需 API key。

## 2. 调用入口

本模块提供 Python 接口，不提供独立 HTTP 路由。

```python
from jobscout.schemas.search import SearchRequest
from jobscout.services.job_search_service import JobSearchService

requests = [
    SearchRequest(
        target_direction="Data Analyst",
        location="上海",
        employment_type="internship",
    ),
    SearchRequest(
        target_direction="Business Analyst",
        location="Hong Kong",
        employment_type="internship",
    ),
]

service = JobSearchService()
result = await service.search_many_async(requests, timeout=60.0)
payload = result.model_dump(mode="json")

raw_jobs = payload["raw_jobs"]
errors = payload["errors"]
warnings = payload["warnings"]
```

- 单个请求：`service.search(request)`。
- 多个请求：`service.search_many(requests)`。
- 参数为 `SearchRequest` 对象；来自 JSON 的字典先执行 `SearchRequest.model_validate(data)`。结构不合法时由 Pydantic 报错，调用方负责处理。
- 每批/会话使用一个 service 实例，不将其作为多个线程共用的全局对象。
- 异步服务使用 `await service.search_many_async(requests, timeout=remaining_seconds)`。原生 httpx 异步 I/O、重试和限流等待均可取消；最多四个并行来源。完成顺序不会改变返回顺序。
- `timeout` 是本轮剩余预算，最多 60 秒；调用方累计所有轮次的 60 秒检索预算与 180 秒总操作预算。零预算不启动请求。超时保留其他来源及当前来源已完成的岗位；取消操作会取消并等待全部子任务退出。
- 同步入口保留给脚本/旧测试，不应放入异步事件循环或通过不可取消的线程伪装异步。自定义 async adapter 必须提供协作取消的 `search_async`；仅同步的 adapter 在异步入口报告 `SEARCH_ASYNC_UNAVAILABLE`。现有非默认 feed/Careerjet 兼容适配器仅用于同步入口。

## 3. 输入 SearchRequest

一个请求表示一个方向、一个地点条件和一种工作类型。多方向或多地点请分别构造请求。

| 字段 | 类型 | 规则 |
| --- | --- | --- |
| target_direction | str | 必填、非空，例如 Data Analyst |
| keywords | list[str] | 可选，默认 []；有值时使用给定词语，不自动翻译；不要传空白词 |
| location | str 或 null | 指定一个地点，例如 上海、Hong Kong |
| location_unrestricted | bool | 默认 false；明确不限地点时设 true，同时 location=null |
| employment_type | str | 默认空；具体类型使用 full-time、part-time、internship、contract 或 freelance |
| employment_type_unrestricted | bool | 明确不限类型时 true，employment_type 必须为空；未回答不等于不限 |
| sources | list[str] | 可选，默认 []，自动按地区选源；也可显式指定来源标识 |
| salary_range | str 或 null | 可选偏好；检索端不做薪资数值过滤，调用方应保留给后续匹配 |
| work_mode | str 或 null | remote/hybrid/onsite 为建议偏好；四个默认来源无法可靠验证，不做硬过滤并报告 warning |

`location` 与 `location_unrestricted=true` 二选一，不能都不指定或同时指定。

关键词为空时使用方向名称；已知 Data Analyst、Business Analyst、Data Scientist 方向可按来源转换为中文/英文基线词。其他方向建议调用方明确给出适合来源的关键词，例如 `keywords=["会计"]`。关键词组合存在字面检查，同义表达可能漏检。

## 4. 来源与覆盖

| 地点条件 | sources 为空时使用的来源 |
| --- | --- |
| 大陆实习 | zhaopin（智联）、liepin（猎聘）、shixiseng（实习僧） |
| 大陆其他工作类型 | zhaopin、liepin |
| 香港 | jobsdb |
| 不限地点 | 上述来源联合；具体非实习类型跳过 shixiseng，明确不限类型保留四来源 |

显式来源示例：`sources=["zhaopin", "liepin"]`。未知标识产生错误，其他有效来源继续。

大陆城市参数支持北京、上海、广州、深圳、杭州、成都；未知城市或区县条件可能返回不支持错误。香港区县名称匹配较保守。不限地点只覆盖所选来源能提供的地区，不代表全球覆盖。实习僧仅支持实习；其他来源可能因缺少明确工作类型而排除候选。

## 5. 返回 SearchResult

| 字段 | 内容 |
| --- | --- |
| raw_jobs | 原始岗位列表，保留各条岗位的求职方向 |
| errors | WorkflowError 列表，表示输入、来源或详情请求问题 |
| warnings | 字符串列表，说明过滤、截断、缺失或覆盖限制 |
| outcomes | 每个请求×来源的数量、耗时、状态和完整性统计 |

`result.model_dump(mode="json")` 可将整个结果转换为可 JSON 序列化的字典。

### 原始岗位字段

| 字段 | 含义 |
| --- | --- |
| source | 来源标识 |
| source_url | 岗位原链接，可能为空 |
| source_job_id | 来源岗位 ID，可能为空 |
| fetched_at | 带 UTC 时区的抓取时间；缓存结果保留原抓取时间 |
| target_direction | 对应输入的求职方向 |
| title、company、location、salary | 来源提供的文本，缺失时为 null |
| description | 原岗位描述；可能是 HTML、文本、摘要或 null |
| description_is_excerpt | 摘录/缺失描述标志；同时保留 raw_payload 兼容字段 |
| employment_type | 来源证据支持的类型；未知为 null，不能复制请求类型推定 |
| posted_at、expiry_at | 来源原始时间文本/数字或 null，尚未统一日期格式和时区 |
| raw_payload | 来源数据及辅助诊断字段 |

规范化层将原文、来源 URL、实际抓取时间和摘录状态保存为 `SourceDocument`，跨方向/来源去重不丢证据。详情替换列表摘录时，raw_payload 的 listing_description/listing_fetched_at 与 detail_description/detail_fetched_at 保留两个快照。

第五组应检查 raw_payload 中以下字段：

| 字段 | 使用方式 |
| --- | --- |
| missing_fields | 缺失的主要字段名称列表，涵盖标题、链接、公司、地点、描述 |
| description_is_excerpt | true 表示只有摘要，不能视为完整 JD |
| detail_status | ok、failed、limit_reached 或 missing_url；无需详情请求的来源可能没有此字段 |
| keyword_evidence | matched 表示存在字面关键词证据；unverified 表示信息不足，不能确认；都不是用户匹配分数 |

缺失字段不应自行补写为事实。返回记录尚未跨来源去重或判定有效性，同一岗位可能出现在多个方向。第五组需显式映射到共享 `JobPosting`；不要直接对整个原始字典执行 `JobPosting.model_validate()`，两者字段和类型不同。

`outcomes.status` 取值为 ok、empty、partial、blocked、unavailable。empty 必须是已验证成功的零结果；验证码/认证/限流为 blocked；网络/超时/格式变化为 unavailable（超时诊断码 SEARCH_TIMEOUT）。ok 仅表示未报告来源错误，不保证字段完整。`incomplete_count` 统计标题、链接、公司、地点、描述中任一缺失的记录数；`excerpt_count` 统计摘要记录，两者可能重叠。

## 6. 异常与空结果

调用后始终检查 errors 和 warnings；errors 非空时仍可能有可用岗位。

| 情况 | 调用方处理 |
| --- | --- |
| 正常零结果 | 可以提示本次条件和检索范围内未找到岗位；不代表整个市场没有岗位 |
| SEARCH_INPUT / SEARCH_UNKNOWN_SOURCE | 检查请求或来源标识 |
| SEARCH_REGION_UNSUPPORTED / SEARCH_LOCATION_UNSUPPORTED / SEARCH_FILTER_UNSUPPORTED | 提示条件暂不支持，调整请求或交上游澄清 |
| SEARCH_TIMEOUT / SEARCH_NETWORK / SEARCH_HTTP | 展示暂时无法获取该来源；保留其他成功结果 |
| SEARCH_RATE_LIMIT / SEARCH_AUTH | 来源限流、拒绝访问或要求验证，不作为正常零结果处理 |
| SEARCH_RESPONSE_FORMAT / SEARCH_SOURCE_REJECTED | 来源格式变化或业务拒绝，保留其他结果并记录诊断 |

WorkflowError 包含 code、message、stage（search）、details。details 中的 request_index 从 0 开始，对应输入请求的序号；还可能包含 source、page、phase 或 source_job_id。

## 7. 搜索节点接入

第三组可直接使用节点：

```python
from jobscout.graph.nodes.search import search_node

update = search_node(
    {"session_id": "example-session", "search_requests": requests},
    service=service,
)
```

节点读取 AgentState.search_requests，返回 raw_jobs、errors、warnings、source_outcomes。异步图使用 `await search_node_async(state, service=service, timeout=remaining_seconds)`；同步 search_node 用于兼容。来源错误保留在 outcomes/warnings，不再混为致命 errors；缺失/无效请求仍是 errors。跨轮岗位合并、预算累计与路由由调用方管理。

节点 raw_jobs 已是 JSON 可序列化字典，errors 仍为 WorkflowError 对象；向 HTTP 输出时使用 Pydantic 序列化或逐项 model_dump(mode="json")。

## 8. 数量与耗时设置

以下参数作用于每个请求的每个来源，不是所有方向合并后的总数：

| 参数 | 默认值 | 作用 |
| --- | ---: | --- |
| max_pages | 1 | 最多请求的列表页数 |
| page_size | 10 | 请求的页大小，网站可能不完全遵守 |
| candidate_limit | 60 | 最多扫描的候选数量 |
| result_limit | 10 | 最多返回的记录数，不保证凑满 |
| detail_limit | 3 | 最多请求的详情页数；预算耗尽后可能保留摘要/null |

增加 detail_limit 可改善描述完整度，但会增加耗时，且不能保证详情成功。每次网络请求超时 12 秒；网络/5xx 最多重试一次，认证/限流不重试。异步入口的共享 deadline 覆盖排队、HTTP、重试和限流等待。离线测试验证了取消和部分结果。

### 2026-10-04 live 验证

先通过 69 个检索/处理离线测试，再使用无个人资料的 Data Analyst 实习查询：JobsDB 香港，其他三来源上海。一次批次共 2.1441 秒，60 秒总 deadline；每来源一页、最多十条返回、三次详情。四来源均返回 `ok`，无来源错误；JobsDB 10 条（7 摘录）、Zhaopin 8 条、Liepin 10 条（8 不完整/摘录）、Shixiseng 4 条（1 不完整/摘录）。各来源列表请求一次，除自带 JD 的 Zhaopin 外各三次详情请求。

这是当时的网络可达性与解析验证，不保证持续可用、完整 JD 或招聘有效性；不以 `ok` 表示所有字段齐全。未绕过访问限制，也未保存岗位正文/链接、凭证或个人数据。清理后的时间、数量和状态见 [验证元数据](retrieval-live-validation-2026-10-04.json)。

来源使用网站接口/公开页面，可能变更或拒绝访问。模块不承诺完整召回、语义相关性、实时有效性或固定返回数量。最终标准化、去重、时效判断、画像匹配和总体 Top 5 由后续模块完成。

## 9. 独立演示

在项目根目录运行：

```powershell
# 固定合成样例，不访问网络
uv run --locked python scripts/demo_job_search.py --mode mock --input data/group4/source_coverage.json

# 真实检索，完整结果写入文件
uv run --locked python scripts/demo_job_search.py --mode live --input data/group4/source_coverage.json --result-limit 5 --detail-limit 3 --output ../group4-live.json

# 代码检查与离线测试
uv run --locked python scripts/check.py
```

可用输入文件均在 data/group4：

- source_coverage.json：上海数据分析实习、上海商业分析实习、香港数据分析实习。
- hong_kong_internships.json：香港两个实习方向。
- mainland_internships.json：上海两个实习方向。
- unrestricted.json：不限地点的两个全职方向。

mock 用于验证接口和演示，不是任意岗位搜索的真实模拟器。live 的结果取决于网站和预算。

PyCharm 中选择项目 `.venv/Scripts/python.exe`，工作目录设为项目根目录，脚本选择 `scripts/demo_job_search.py`，参数填写上方命令中 `--mode` 开始的部分。默认不传参数时运行 mock。

CLI 退出码：0=无错误（仍需查看 warnings），1=来源或详情错误且可能保留部分结果，2=输入/未知来源/文件问题。
