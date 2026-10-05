# 前端架构与会话流程

本文件记录 `web/` 的实现结构和运行行为。安装、启动及常用命令见[项目 README](../README.md)，简历解析的接口与限制见[简历上传模块](resume-upload-design.md)。

## 路由与布局

前端使用 TanStack Router 的文件路由，支持直接访问、刷新和浏览器前进/后退。

| 路由     | 页面     | 代码入口                              |
| -------- | -------- | ------------------------------------- |
| `/`      | 发现机会 | `web/src/routes/_workspace.index.tsx` |
| `/saved` | 收藏岗位 | `web/src/routes/_workspace.saved.tsx` |

两个页面共享 `_workspace.tsx` 布局和 `ScoutProvider`。会话流程位于共享 Provider 中，切换到收藏页不会中断请求。

## 模块职责

以下路径相对于 `web/`：

| 路径                        | 职责                                                                             |
| --------------------------- | -------------------------------------------------------------------------------- |
| `src/components/layout/`    | 侧边栏、顶栏和页面标题                                                           |
| `src/components/discovery/` | 检索阶段、进度和加载/失败状态                                                    |
| `src/components/profile/`   | 个人介绍、简历、求职方向和偏好字段                                               |
| `src/components/results/`   | 结果筛选、空态和提示；岗位卡片独立复用                                           |
| `src/lib/session-client.ts` | Session HTTP 请求和错误提示                                                      |
| `src/lib/resume-client.ts`  | TXT 本地读取、PDF / DOCX 上传解析，统一返回 `{ name, text }`                     |
| `src/lib/session-query.ts`  | 会话 Query key、查询和重试规则                                                   |
| `src/state/`                | Zustand 草稿和收藏、React Query 会话流程；`ScoutProvider` 可注入 `SessionClient` |

## 表单与状态管理

React Hook Form 管理首次资料表单的字段、校验和错误聚焦。资料字段通过 `useController` 绑定，表单订阅把草稿同步到 Zustand。允许暂不填写方向、地点和工作类型；简历与介绍至少提供一项。提交前明确告知个人介绍和简历文本将发送给后端配置的模型服务商。

Zustand 保留草稿和收藏；当前对话输入和摘要编辑留在组件内存中，服务端会话由 React Query 缓存管理。`sessionStorage` **仅保存** `jobscout.session_id`，不保存简历、介绍、画像、答案、岗位或密钥；不使用 `localStorage`。刷新后按 ID 读取服务端快照，未提交的文字和收藏不跨刷新持久化。浏览器禁用存储时仍可使用当前内存会话。关闭 TanStack Router 的 `scrollRestoration`，避免其在刷新后额外写入滚动位置缓存，保证存储中仅有会话 ID。

### 对话与确认

- `ClarificationForm` 每次最多展示三个 `pending` 后端问题，支持原生键盘可操作的单选、多选及文本输入。请求使用 `question_id` 和选项 `id`，不是标签或字段名。仅选填问题可跳过；`answered` / `skipped` 不再作为当前问题展示。
- 独立自由文本框允许补充、纠正，甚至只发文字；是否足够、追问轮次及必填冲突均由后端判断。历史保留后端消息、回答及“已跳过”标记，普通助手说明不生成额外问题。
- `SearchSummary` 展示教育、技能、实习、项目、最多三个方向以及偏好；根据 `editable_fields` 控制可编辑性。更新字典使用平铺键（例如 `preferences.location`），列表按换行或逗号分隔。地点和工作类型均提供显式“不限”。
- 修改后先点击“保存修改”，后端返回最新摘要，再点击“确认并开始搜索”；本地脏表单不能直接确认。`ready` 未满足或摘要 revision 与当前会话 revision 不同时确认按钮禁用。自由文字修正同样送给后端，前端不自行推断确认。
- 结果页显示助手引言和原有岗位卡片，历史默认折叠。“调整求职条件”使用同一会话的 `edit_conditions`，等待新的确认摘要，不创建新会话；后端必须清除旧推荐并使确认失效。
- 卡片展示 `MatchingReason` 的要求、等级、解释和两组证据摘录（文档 ID、可安全打开的 HTTP(S) 来源链接）。缺少证据仅表示材料未体现，不代表缺乏能力。招聘时效、仅摘要的 JD、不确定性及来源结果分别展示。筛选、收藏与上传功能保留。

运行时的画像、追问、岗位、技能差距和准备建议均来自 Session API。后端失败或返回空结果时，页面显示相应错误或空态。单元测试的固定资料及岗位数据位于 `web/tests/fixtures.ts`，仅由 `.test.ts` 文件引用，不进入应用构建。

收藏使用后端返回的岗位数据，目前保存在本地内存中；后端尚未提供收藏接口。

## 简历上传的接入

`resume-client.ts` 将文件转换为草稿中的 `{ name, text }`。TXT 在浏览器中读取，PDF / DOCX 通过上传接口提取文字。

解析期间禁止提交；离开表单会取消上传，失败时保留已有资料。上传成功后显示文件名和成功标记，悬停或键盘聚焦时切换为红色的移除操作，点击后恢复上传入口。

支持格式、文件限制、解析服务与留存行为统一记录在[简历上传模块](resume-upload-design.md)。

## Session API 与查询缓存

会话 API 与 [`src/jobscout/schemas/session.py`](../src/jobscout/schemas/session.py) 对齐：

| 操作 | 请求                                        | 页面行为                                                    |
| ---- | ------------------------------------------- | ----------------------------------------------------------- |
| 创建 | `POST /api/v1/sessions`                     | 资料加 `request_id`，202 返回 `running` 快照 |
| 查询 | `GET /api/v1/sessions/{session_id}`         | 按 ID 恢复；运行期间每秒轮询一次 |
| 回答 / 动作 | `POST /api/v1/sessions/{session_id}/resume` | `request_id`、`expected_revision`、`message`、`answers: [{question_id, value: string|string[]}]`、`skipped_question_ids`、`action`、平铺 `profile_updates` |
| 删除 | `DELETE /api/v1/sessions/{session_id}`      | 删除后端会话、ID 和 Query 缓存；保留本地草稿和收藏 |

`action` 为 `answer`、`confirm_search`、`edit_conditions` 或 `retry`。响应保留原有字段，增加 `current_stage`、`revision`、`conversation`、`search_summary`、`source_outcomes`、`retryable` 及 `mode`。`mode: replay` 始终显著标记为回放演示，不宣称实时检索。

创建、回答和删除使用 `useMutation`；`useQuery` 读取 `['sessions', session_id]`。202 快照直接写入缓存。只有 `outcome: running` 才每 1000ms GET；暂停、完成、失败立即停止，GET 重试耗尽也停止并提供重试入口。初始 GET 恢复时不重新 POST。

GET 最多自动重试一次，4xx 不自动重试；POST/DELETE 均不自动重试。每个逻辑提交创建一个 UUID，网络失败手动重试复用原请求体和原 ID；新操作生成新 ID 并携带当前快照 revision。页面禁止运行时重复提交。取消查询时传递 `AbortSignal`；删除可打断运行，操作代次检查及 Query 取消防止晚返回的响应恢复会话。

## 错误处理与会话恢复

HTTP 404 提供重新开始入口；409 自动使缓存失效、GET 最新快照，并保留手动刷新入口，不重放旧 revision；422 保留当前输入并提示修改提交内容。网络及服务错误可以手动重试原请求。暂时请求失败不卸载当前表单，因此修正文字和结构化答案仍在。

业务 `outcome: failed` 且 `retryable: true` 时调用现有会话的后端 `retry` 动作，绝不创建替代会话。来源失败与业务失败分开呈现，成功空结果不等同来源不可用。推荐和会话 warnings 都会展示。后端当前使用内存 checkpoint，重启后旧会话可能返回 404。

## 开发配置与部署

前端默认请求 `/api/v1`。Vite 的开发和预览服务器将 `/api` 转发到 `http://127.0.0.1:8000`，配置位于 [`web/vite.config.ts`](../web/vite.config.ts)。

环境变量示例见 [`web/.env.example`](../web/.env.example)。在 `web/.env.local` 中设置 `API_PROXY_TARGET` 可以修改代理目标，`VITE_API_BASE_URL` 控制浏览器请求前缀；修改后需重启 Vite。

部署时，Web 服务器需要配置 `/api` 反向代理，并将页面路由回退到 `index.html`。Vite 开发代理不会进入构建文件。使用跨域的 `VITE_API_BASE_URL` 时，API 服务器需要允许前端域名的 CORS 请求。

## 开发工具与验证

代码检查使用 Oxlint，格式整理使用 Oxfmt；React Compiler 已在开发和构建时启用。命令入口见 [`web/package.json`](../web/package.json)。

使用 Node ≥22.12（本地验证为 v24.18.1）与 Bun ≥1.4.2。若 Windows 上 Bun 不在 PATH，可在 `web` 内安装 `npm install --prefix .tools --no-package-lock --no-save bun@1.4.2`，再将 `.tools\node_modules\bun\bin` 加入当前 PowerShell 的 PATH。`.tools` 被 Git、格式器、linter 和 Vite watcher 忽略；不会更改已有的未跟踪 `package-lock.json`。依赖以 `bun.lock` 为准。`web/.gitattributes` 固定文本为 LF，避免 Windows `core.autocrlf` 与 Oxfmt 的默认行尾冲突。

- `bun run test`：离线 Bun 单元测试，覆盖 HTTP 202 与精确请求体、错误/取消、查询缓存、问题数量/ID/跳过、摘要更新以及草稿/收藏。
- `bun run test:browser`：Playwright 在 3018 启动 Vite，默认使用已安装的 Microsoft Edge（Chromium），拦截 API 返回严格合成快照，不联系模型、不上传真实简历。覆盖完整三步、键盘选择、多选/文本/跳过、显式确认、自由纠正、结果证据、收藏、同会话修改、轮询、刷新恢复、409、网络幂等重试和后端失败重试。无 Edge 的环境可设置 `PLAYWRIGHT_CHANNEL=chromium` 并先运行 `bunx playwright install chromium`。
- 真实回放联调：先独立启动 `JOBSCOUT_MODE=replay` 的后端，再在 `web` 设置 `JOBSCOUT_REPLAY_E2E=1` 和 `JOBSCOUT_REPLAY_API_URL=http://127.0.0.1:8018`，运行 `bun run test:browser`。测试在 3019 启动并停止独占 Vite，不拦截 API；验证 202、确认前不检索、revision、问题控件、真实合成岗位/证据摘录、刷新恢复、ID-only 存储和浏览器错误。后端须由调用者停止；测试会删除自己创建的会话。
- `bun run check`：路由生成、TypeScript（含浏览器测试）、Oxlint 与 Oxfmt。
- `bun run build`：类型检查及生产构建。
- `bun run doctor --scope full --no-cache --yes`：使用已锁定的本地 React Doctor，关闭遥测、评分 API 和供应链联网检查，报告写入 `.tools/doctor`。

需要将工具运行文件限制在仓库内时，可先创建 `web/.tools/runtime` 并将当前进程 `TEMP` / `TMP` 设为该目录。真实回放命令示例（两个 PowerShell 终端）：

```powershell
# 终端一：JobScout 根目录，保持前台运行，测试后 Ctrl+C 停止
$env:JOBSCOUT_MODE = 'replay'
$env:LLM_API_KEY = ''
$env:DATABASE_URL = 'sqlite://:memory:'
.\.venv\Scripts\python.exe -m uvicorn jobscout.main:app --host 127.0.0.1 --port 8018 --log-level warning
```

```powershell
# 终端二：web 目录
$env:PATH = "$PWD\.tools\node_modules\bun\bin;$env:PATH"
New-Item -ItemType Directory -Force .tools\runtime | Out-Null
$env:TEMP = "$PWD\.tools\runtime"
$env:TMP = $env:TEMP
$env:JOBSCOUT_REPLAY_E2E = '1'
$env:JOBSCOUT_REPLAY_API_URL = 'http://127.0.0.1:8018'
bun run test:browser
# 常规离线测试前取消真实后端测试开关
Remove-Item Env:JOBSCOUT_REPLAY_E2E
```

回放 E2E 使用真实 API、会话管理器、LangGraph 和证据服务，但模型输出和岗位仍为显式合成数据；不等同真实 DeepSeek 或招聘来源联调，后者需独立验证。
