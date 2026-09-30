# Shared Schemas

这里定义跨模块共享的数据契约。字段变更需要相关小组共同确认。目前的字段是Schema v1版本，后续开发过程中如果需要进行调整、修改，请在群内沟通后再进行。

## UserProfile

用户画像，由画像模块生成和更新，Workflow 读取其确认、缺失和冲突状态。

- 生产方：第 2 组（用户画像与确认）。
- 使用方：第 3 组 Workflow、第 6 组匹配与推荐。

- `profile_id`: 画像标识。
- `source`: 是否来自简历或用户描述。
- `education`、`skills`、`internships`、`projects`: 用户背景信息。
- `target_directions`: 一个或多个求职方向。
- `preferences`: 地点、雇佣类型、薪资、工作模式和行业偏好。
- `confirmed_fields`: 已确认的字段名。
- `missing_required_fields`: 尚未满足的必要字段名。
- `conflicts`: 等待用户确认的冲突信息。

`preferences.location=None` 且 `preferences.location_unrestricted=False` 表示地点尚未确定；`location_unrestricted=True` 表示用户明确接受不限地点。

## SearchRequest

岗位检索输入，由 Workflow 根据已确认的画像生成，岗位检索模块消费。

- 生产方：第 3 组 Workflow。
- 使用方：第 4 组岗位检索。

- `target_direction`: 本次检索对应的求职方向。
- `keywords`: 检索关键词。
- `location`: 指定地点；不限地点时可以为 `None`。
- `location_unrestricted`: 是否明确接受不限地点。
- `employment_type`: 雇佣类型，例如 `full-time`、`part-time` 或 `internship`。
- `salary_range`、`work_mode`: 可选偏好。
- `sources`: 可选岗位来源限制。

## ClarificationMessage

需要用户回答的追问，由画像/Workflow 模块生成，Session API 和前端消费。

- 生产方：第 2 组用户画像与确认、第 3 组 Workflow。
- 使用方：第 1 组前端与交互、第 3 组 Session API。

- `question`: 给用户显示的问题。
- `field`: 问题涉及的画像字段。
- `reason`: 需要追问的原因。
- `required`: 是否为继续流程所必需。
- `status`: `pending` 或 `answered`。
- `answer`: 用户回答；未回答时为 `None`。

## JobPosting

标准化后的岗位，由岗位处理模块生成，推荐模块和前端消费。它不是外部岗位来源的原始响应。

- 生产方：第 5 组岗位理解与数据质量。
- 使用方：第 3 组 Workflow、第 6 组匹配与推荐、第 1 组前端与交互。

- `job_id`: 稳定或生成的岗位标识。
- `source`、`source_url`: 主来源及主链接。
- `source_links`: 去重合并后的全部来源链接。
- `title`、`company`、`location`、`salary`: 前端展示信息。
- `target_direction`: 岗位对应的求职方向。
- `responsibilities`、`required_skills`: 岗位职责和技能要求。
- `posted_at`、`expiry_at`、`fetched_at`: 岗位时间信息。
- `freshness_status`: `active`、`expired` 或 `unknown`。

无法确认岗位是否有效时，必须使用 `unknown`，不能推断为 `active`。

## RecommendationResult

最终推荐输出，由推荐模块生成，前端消费。

- 生产方：第 6 组匹配与推荐。
- 使用方：第 3 组 Workflow、第 1 组前端与交互。

- `session_id`: 对应的会话标识。
- `generated_at`: 结果生成时间。
- `jobs`: 推荐项目列表，最多 5 条，按总体推荐结果返回，不按求职方向分别返回。
- `warnings`: 不影响结果生成但需要提示用户的信息。

每个推荐项目包含一个 `JobPosting`、`missing_skills` 和 `preparation_suggestions`。

## WorkflowError

跨模块和 API 使用的统一错误数据，不替代 Python exception。

- 生产方：产生错误的模块；第 3 组负责统一接入 Workflow 和 API。
- 使用方：第 3 组 Workflow/API、第 1 组前端与交互，以及需要处理失败的业务组。

- `code`: 稳定的错误代码。
- `message`: 可展示给用户的错误说明。
- `stage`: 发生错误的流程阶段。
- `details`: 可选的补充信息。

