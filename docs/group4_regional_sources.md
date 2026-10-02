# 大陆与香港来源选型（当前四来源版）

> 2026-10-02 已完成交付复核，最新 31 条真实候选、字段质量和 145 项测试结果见 [接入速查](group4_handoff.md)。本文 2026-10-01 数量为选型时历史实测。

本说明替代此前 Careerjet 默认方案。根据用户选择，大陆采用智联招聘、猎聘、实习僧；香港选择 JobsDB。按 SearchRequest 先搜索再返回原始候选，不建立全站岗位库。当前入口、错误、预算及完整验证表见 [交接说明](group4_job_retrieval.md)。

## 方法与证据

| 来源 | 本次方法 | 地区/类型 | 凭证、费用、分页与字段 | 状态 |
| --- | --- | --- | --- | --- |
| 智联招聘 | 网站 POST JSON 接口 | 大陆城市、多类职位 | 实测无需 key/cookie；pageIndex/pageSize；完整原始描述、URL、薪资与发布时间可得；截止时间可能空。order=4 会混入推荐，使用 order=0 | 适配器完成、固定测试通过、上海两个实习方向均实际返回 10 条 |
| 猎聘 | 网站 POST JSON + HTML/JSON-LD 详情 | 大陆社会招聘及实习 | 实测无需 key/cookie，需要 trace ID 请求头；currentPage 从 0 开始，服务器未严格遵守请求 pageSize；列表时间有旧日期，部分全职记录缺雇佣类型 | 适配器完成、固定测试通过、上海两个实习方向各 10 条；不限地点全职样本因类型不明而排除 |
| 实习僧 | 简单 HTML 列表及详情解析 | 大陆实习 | 无 key/cookie；keyword/city/page。详情可取得描述、部分薪资及截止日期；列表私有字体不能可靠当正常文字；全国推广需地点过滤 | 适配器完成、固定测试通过、上海两个方向各 10 条；18/20 有详情，其余达到预算 |
| JobsDB | 香港站搜索 JSON + HTML 详情 | 香港多类商业岗位及实习 | 无 key/cookie；keywords/where/worktype/page/pageSize；时间、公司、链接和摘要；详情额外请求；实习可能标成 Full time | 适配器完成、固定测试通过；香港 DA 实习 10 条，1 次详情网络错误被保留为明确 partial |
| CPJobs | 候选公开招聘网站，未接入 | 香港本地岗位 | 官网当前提供关键词、地区/职位展示；本次没有为它建立并验证同等 JSON 适配器与分页契约 | 可作后备研究；没有把它标为失败或不可抓取 |

香港选 JobsDB 的理由是本次已验证搜索 JSON、原生参数、分页和详情，能用一个轻量适配器交付。CPJobs 官网可读，不代表它不合适；本次未做等量覆盖/召回对比，不能声称 JobsDB 一定岗位更多。选型依据是已验证的实现路径和课程工作量。

这些网站端点不等于已取得正式开发者 API 授权或长期免费服务合同。本次未找到适用于这四个搜索端点的公开开发者配额/计费/SLA 文档，所以不编造每日额度或更新保证；实测匿名可读也不证明无限开放。模块保留来源链接、限制请求次数，遇到 401/403/429/挑战页面报告失败，无登录/验证码绕过。网页变动可能要求调整适配器。平台发布/更新时间仍需第五组判断，不因接口有响应就断言仍在招聘。

## 依据与研究线索（2026-10-01）

- [智联官网](https://www.zhaopin.com/)；[实际网站搜索端点](https://fe-api.zhaopin.com/c/i/search/positions) 为 POST，浏览器直接 GET 不是调用测试。当前参数以实际 POST 结果为准。
- 用户提供的 [CSDN 经验帖](https://blog.csdn.net/qq_65787661/article/details/160145909) 提供了智联端点线索；它不是官方契约。实现由本项目独立编写。实测其 order=4 查询会混入不相关岗位，已采用 order=0，未盲目复用其将失败返回空数组的方式。
- [猎聘官网](https://www.liepin.com/)；[网站搜索端点](https://api-c.liepin.com/api/com.liepin.searchfront4c.pc-search-job)。实际响应 jobCardList 及公开详情页是字段映射依据。
- [实习僧官网](https://www.shixiseng.com/)；[公开实习列表](https://www.shixiseng.com/interns)。DOM 选择器由实际列表与详情检查确认。
- [JobsDB 香港官网](https://hk.jobsdb.com/)、[实际搜索端点](https://hk.jobsdb.com/api/jobsearch/v5/search?siteKey=HK-Main&keywords=Data%20Analyst%20intern&where=Hong%20Kong&page=1&pageSize=5&locale=en-HK)、[CPJobs 香港官网](https://www.cpjobs.com/hk/en)。官网作为地区覆盖与公开页面依据，JSON 契约由本次实际请求验证。

## 与原方案的关系

Careerjet 有 [香港官方 API 入口](https://www.careerjet.com.hk/partners/api) 和 [大陆入口](https://www.careerjet.cn/partners/api)，适合有发布商凭证时作为备用，但当前用户选择四个本地网站，不再默认请求 Careerjet。其历史适配器及 Remotive/Arbeitnow 保留兼容，只在显式 sources 指定时运行。

旧 data/group4/smoke_2026-10-01.json 是早期海外来源的测试，不能说明本地岗位搜不到。当前 data/group4/smoke_local_2026-10-01.json 才是选定四来源联合验证；不限地点补充记录见 smoke_local_unrestricted_2026-10-01.json。四来源无需用户提供密钥；未完成的第三组/第五组/第六组不是本组来源检索为空的原因。

本次 LLM 使用：Codex 辅助研究线索、构造只读探测、编写适配器和固定测试、分析失败及整理文档。最终贡献说明应由第四组负责同学审阅并整合至全队披露。
