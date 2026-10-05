# Node 内部 LLM 使用约定

## 实现状态

当前实现为原生异步 `httpx` DeepSeek provider，默认 `deepseek-flash`，关闭 thinking。
已通过离线合成 HTTP fixtures 验证接口、超时、重试、修复和取消；**live integration unverified**。
本次环境无法访问 DeepSeek 官方文档，因此使用计划指定的
`response_format={"type":"json_object"}` 与 `thinking={"type":"disabled"}` 请求格式，
未调用真实 API，也未确认当前模型可用性。
2026-10-04 使用实际 `Settings()` 做仅输出布尔值的检查：根目录 `.env` 不存在，
`LLM_API_KEY` 未配置。**DeepSeek live validation blocked: missing credentials**。
离线 provider 测试为 68 passed；不得将离线 wire-format 验证视为真实服务验证，
也未绕过官方文档访问限制。

参考：[JSON 输出](https://api-docs.deepseek.com/guides/json_mode/)、
[Thinking](https://api-docs.deepseek.com/guides/thinking_mode/)、
[模型](https://api-docs.deepseek.com/quick_start/pricing/)。

## 目标

LLM 只负责理解自然语言并提取业务语义；系统字段、状态流转和最终 API 契约由 Python 函数与 LangGraph 负责生成和校验。

## 统一流程

```text
用户输入
  ↓
业务 Node 调用 LLM
  ↓
内部 Extraction Schema 校验
  ↓
业务 Service 归一化和规则校验
  ↓
第三组补充系统字段并写入 Graph State
  ↓
对外输出正式 Schema
```

## 职责划分

### 各业务组

各组负责自己业务领域的：

- LLM prompt 和提取逻辑；
- 内部 Extraction Schema；
- 业务字段的归一化和语义校验；
- JD／匹配失败时带明确 warning 的确定性分析；画像理解失败保留输入并暴露重试；
- 对应的单元测试。

### 第三组

第三组负责：

- LangGraph Node 的编排和调用；
- LLM Service 的统一接口；
- Graph State 的读写和状态流转；
- 使用 Python 函数补充系统字段；
- 将提取结果转换为正式 Schema；
- 错误处理、暂停恢复和对外 Session API 契约。

第三组不负责替其他组定义业务字段含义，也不应在 Graph Node 中重复实现业务解析逻辑。

## Schema 约定

LLM 不应直接生成完整的对外 Schema。业务组应先定义内部 Extraction Schema，只包含需要模型理解的字段。例如：

```python
class ProfileExtraction(BaseModel):
    education: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    internships: list[str] = Field(default_factory=list)
    projects: list[str] = Field(default_factory=list)
    target_directions: list[str] = Field(default_factory=list)
    preferences: ProfilePreferences = Field(default_factory=ProfilePreferences)
```

随后由 Python 代码补充或计算：

- `profile_id`、`session_id`；
- `source`；
- `confirmed_fields`；
- `missing_required_fields`；
- `conflicts`；
- `generated_at`、`fetched_at`；
- `job_id`、`source_url`、`source_links`；
- `freshness_status` 和其他流程状态。

当前 `UserProfile`、`JobPosting`、`RecommendationResult` 等正式 Schema 继续作为 Graph、Session API 和前端之间的稳定契约，除非经过团队确认和版本化变更，否则不因接入 LLM 而直接修改。

## 可靠性要求

- LLM 输出必须经过 Pydantic 校验，不能直接写入 Graph State；
- 不允许 LLM 编造岗位来源、链接、ID、抓取时间或其他外部事实；
- 日期、枚举、数量限制和必填字段由程序再次校验；
- LLM 调用失败、超时或输出非法时，必须返回明确错误；仅 JD／匹配可按上述约定降级，不能静默替换为 demo 数据；
- 测试默认使用 mock provider，不依赖真实 API；
- API Key 只能通过环境变量或 `.env` 注入，不能写入代码、测试或提交记录。

## Provider 接口

`jobscout.services.llm_service` 导出以下接口。泛型返回传入 schema 的具体类型，
不接受 LangChain `BaseMessage`，也不使用其同步 `invoke`。

```python
class LLMProvider(Protocol):
    async def structured[SchemaT: BaseModel](
        self,
        schema: type[SchemaT],
        messages: list[dict[str, str]],
        *,
        deadline: float | None = None,
    ) -> SchemaT: ...

provider = get_llm_provider(settings)
result = await provider.structured(
    ProfileExtraction,
    [{"role": "user", "content": "Synthetic profile: Python student"}],
    deadline=asyncio.get_running_loop().time() + 30,
)
```

- `schema` 为业务自有内部 Pydantic model；输出先校验 JSON object，再经 `model_validate_json`。
  推荐 `ConfigDict(extra="forbid")` 和业务 validators。协议只保证 schema 校验，
  引用 ID 和原文证据仍必须由业务节点校验，不得仅因 provider 成功就信任生成的事实。
- `messages` 为非空列表，字典仅包含 `role` 和 `content` 字符串。
  支持 `system`、`user`、`assistant`，不改变传入列表或字典。
- `deadline` 是 `asyncio.get_running_loop().time()` 的绝对单调时钟值，**不是** Unix 时间戳或秒数。
  完整调用（包括连接、读取、重试等待、修复）受它与 `LLM_TIMEOUT` 中较早的截止时间限制。
- 只发送 `POST <LLM_BASE_URL>/chat/completions`；base URL 可包含 `/v1`，但不是完整 endpoint。
  要求 HTTPS，拒绝 URL 内嵌凭证／查询参数／fragment，不跟随重定向。
- 每次逻辑调用最多一次暂时性重试（408/425/429/5xx 和 HTTP transport 异常），
  最多一次 JSON／schema 修复；两者共享预算，最多三次 HTTP 请求。
  401/403 立即失败，其他非成功状态不重试；输出截断／格式错误也需要修复。
  修复只补充原输出与通用 JSON 修复提示，不转发验证错误中的私人字段信息。
- `asyncio.CancelledError` 原样传播；不启动后台线程、隐藏任务或补偿请求。
  一个 provider 可在同一事件循环内并发使用，各调用预算独立。
- `DeepSeekProvider(settings, *, client: httpx.AsyncClient | None = None)` 支持 MockTransport 测试。
  构造器不验证密钥／模型／base URL，生产应用可以在未配置密钥时正常启动；
  实际 `structured()` 调用在任何 HTTP 请求前返回安全的 `model_configuration` 错误。
  注入 client 由调用方管理关闭；未注入时每次调用使用自动关闭的 client。
  `await provider.aclose()` 是幂等、无副作用的生命周期钩子，不关闭借用 client；
  fake 只需实现 `LLMProvider.structured`，不强制实现关闭方法。
- 测试直接注入实现此 async 泛型协议的 fake，不需要密钥或网络。`ModelProvider` 是协议别名。
  没有 demo provider 或自动 fallback；`get_llm_provider` 只接受 `LLM_PROVIDER=deepseek`。
- `.usage` 返回 `ModelUsage` 累计计数的独立快照：`structured_calls`、`successful_calls`、
  `failed_calls`、`cancellations`、`requests`、`retries`、`repairs`、`prompt_tokens`、
  `completion_tokens`、`total_tokens`。失败输出和修复响应返回的 token 也计入；
  无有效 usage 时 token 为零而不是估算。不要将共享实例的累计值误认为单个会话计费。
- provider 不记录或保留 prompt、简历、响应正文、密钥或 reasoning；业务可记录上述计数与安全错误码。

### 安全错误契约

`ModelServiceError(code)` 仅生成固定 `.code`／`.message`，不拼接上游异常、HTTP body 或输入。
`LLMServiceError` 是兼容导出别名；旧的同步 `OpenAICompatibleProvider` 已由异步实现替代。

| Code | 意义 |
|---|---|
| `model_configuration` | 缺少配置、无效 base URL 或不支持的 provider |
| `model_input` | 无效 messages 或非有限 deadline |
| `model_auth` | 401／403，立即失败 |
| `model_timeout` | 请求超时或整个逻辑调用预算耗尽 |
| `model_transport` | 重试后仍无法连接／读取 |
| `model_http` | 非成功 HTTP 状态，重试预算耗尽或不可重试 |
| `model_output` | JSON／Pydantic 校验在一次修复后仍失败 |

### 环境配置

```dotenv
LLM_PROVIDER=deepseek
LLM_MODEL=deepseek-flash
LLM_BASE_URL=https://api.deepseek.com
LLM_API_KEY=
LLM_TIMEOUT=30
LLM_MAX_TOKENS=4096
LLM_RETRY_DELAY=0.25
```

`LLM_TIMEOUT` 必须大于 0、至多 180 秒；`LLM_RETRY_DELAY` 为 0–5 秒；
`LLM_MAX_TOKENS` 为 1–32768。Thinking 始终关闭，不提供开启开关。
`.env.example` 只保存变量名和公开默认值，真实密钥只放在本地 `.env` 中。
`httpx` 是直接依赖；保留用户草稿的 `langchain-openai` 依赖供协调者决定后续移除。

### 离线验证

```powershell
uv run pytest tests\test_llm_service.py -q
uv run ruff check src\jobscout\services\llm_service.py src\jobscout\schemas\model.py src\jobscout\config.py tests\test_llm_service.py
uv run mypy --follow-imports=silent src\jobscout\services\llm_service.py src\jobscout\schemas\model.py src\jobscout\config.py tests\test_llm_service.py
```

测试仅使用合成文本、`.invalid` 域名和假的 token；真实服务验证必须另行进行，且不得把私人简历或密钥提交为 fixtures。
