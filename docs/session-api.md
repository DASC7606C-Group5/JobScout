# 异步会话 API

接口前缀为 `/api/v1`。会话和 checkpoint 仅保存在单进程内存中，后端重启后过期。所有简历和个人描述只在请求处理及会话内存中使用；模型功能会发送相关文本至配置的模型供应商，提交前应告知用户。

## 创建与运行

`POST /sessions` 接受 `request_id`、`description`、可选 `resume: {name,text}`、`target_directions` 和 `preferences`。至少提供简历文本或个人描述。方向和偏好可以暂缺，由后续对话补齐。`request_id` 是调用方生成的非空唯一字符串，同一网络重试必须复用相同 ID 和内容。

创建及继续操作返回 HTTP **202** 和快照，不等待模型或检索结束。响应的 `outcome` 为 `running`、`paused`、`completed` 或 `failed`。只有 `running` 时每秒调用一次 `GET /sessions/{session_id}`；其他状态停止周期轮询。

快照保留既有 profile、clarification_questions、recommendation、errors、warnings，同时包含：

- `current_stage`：当前业务阶段；`clarify` / `confirm` 表示用户交互阶段。
- `revision`：本会话已接受操作的版本。
- `conversation`：用户和助理消息；不包含模型私有推理。
- `search_summary`：可编辑画像、有效性、确认状态和绑定版本。
- `source_outcomes`：各来源的独立状态、数量与耗时。
- `retryable`：失败后是否提供重试入口。
- `mode`：`live` 或明确标记的 `replay`。

## 继续操作

`POST /sessions/{session_id}/resume`：

```json
{
  "request_id": "unique-client-operation-id",
  "expected_revision": 1,
  "action": "answer",
  "message": "补充或更正信息",
  "answers": [{"question_id": "question-id", "value": "option-id-or-text"}],
  "skipped_question_ids": [],
  "profile_updates": {}
}
```

- `action` 为 `answer`、`confirm_search`、`edit_conditions` 或 `retry`。
- `answers[].value`：文本/单选为字符串，多选为字符串列表。选项使用 `options[].id`，不是标签。
- 问题只能回答当前 pending ID；不能重复回答、同时回答和跳过、跳过必填项或提交不存在的选项。
- `profile_updates` 是扁平白名单字段映射：education、skills、internships、projects、target_directions 使用字符串列表；`preferences.location_unrestricted` 和 `preferences.employment_type_unrestricted` 使用布尔值；其余 preferences 字段使用字符串或 null。
- 有效摘要显示之后才可 `confirm_search`。更正内容先生成新摘要，必须重新确认。明确文字确认也只能确认当前有效摘要。
- 成功结束后修改条件使用 `edit_conditions`，保留会话历史但清除旧推荐；失败后使用 `retry` 或编辑条件。

`employment_type=null` 且 `employment_type_unrestricted=false` 是未回答；后者为 true 才表示不限。地点同理。不限地点只覆盖当前香港/中国内地支持来源，不表示全球检索。

## 并发、幂等与删除

- 每会话至多一个 active operation。不同请求并发、旧 revision、同 request ID 改变内容返回 **409**。
- 已接受操作的相同请求重试不会再调用模型或检索。服务端先识别相同请求，再判断版本。
- 输入/ID/选项/字段校验失败返回 **422**，不会接受操作。
- `DELETE /sessions/{session_id}` 先使会话失效，取消操作并清理 checkpoint，再返回 **204**。迟到结果不能重建会话；后续读取返回 **404**。
- 删除后的创建请求 ID 不得复用来悄悄恢复旧会话；创建新会话需新 ID。
- 结束或失败后的编辑/重试保留公开 session ID，但使用新的内部 checkpoint thread，避免累加型状态保留旧错误；删除清理该会话的全部内部 thread。
- 浏览器 sessionStorage 只保存 session ID；404 后清理 ID。勿保存简历、画像或 API key。

## 错误边界

来源失败在 source outcomes 中单独呈现，成功来源的岗位仍可进入处理；成功为空与所有来源不可用不是同一状态。用户输入、画像理解或工作流失败保留可恢复输入。单岗位理解/匹配降级需提示，不替换为 demo 岗位。

服务端错误只提供安全错误码和可展示说明，不返回供应商响应正文、凭证或简历内容。模型密钥只在服务端环境配置中保存。API 的真实当前字段以 [Pydantic 定义](../src/jobscout/schemas/session.py) 为准。
