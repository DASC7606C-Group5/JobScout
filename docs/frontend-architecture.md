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

React Hook Form 管理资料及追问表单的字段、校验和错误聚焦。资料字段通过 `useController` 绑定，表单订阅把草稿同步到 Zustand。

Zustand 保留草稿、追问回答和收藏，服务端会话由 React Query 缓存管理。刷新页面后前端内存状态清空；简历不会写入浏览器持久存储。个人介绍和简历文字在提交资料时发送至后端。

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
| 创建 | `POST /api/v1/sessions`                     | 发送求职资料，按 `outcome` 显示追问、结果或业务失败         |
| 查询 | `GET /api/v1/sessions/{session_id}`         | 刷新当前会话                                                |
| 回答 | `POST /api/v1/sessions/{session_id}/resume` | 发送 `{ answers }`，保留包含点号的字段名                    |
| 删除 | `DELETE /api/v1/sessions/{session_id}`      | “清除会话”删除服务端会话及其 Query 缓存，保留本地草稿和收藏 |

创建、回答和删除使用 `useMutation`；`useQuery` 读取 `['sessions', session_id]`。创建及回答返回完整快照后直接写入缓存，避免重复 GET。

GET 最多自动重试一次，4xx 不自动重试；POST/DELETE 均不自动重试。页面防止重复提交，取消查询时将 `AbortSignal` 传给 fetch，放弃的响应不会覆盖新会话。

## 错误处理与会话恢复

HTTP 404 提供重新调整入口，409 提供刷新入口，422 保留资料并提示检查格式。网络及服务错误可以手动重试原请求。

后端没有失败会话的重跑接口，业务 `outcome: failed` 的重试会按已更新的草稿创建新会话。推荐及会话中的 warnings 都会展示。后端当前使用内存 checkpoint，重启后旧会话可能返回 404。

## 开发配置与部署

前端默认请求 `/api/v1`。Vite 的开发和预览服务器将 `/api` 转发到 `http://127.0.0.1:8000`，配置位于 [`web/vite.config.ts`](../web/vite.config.ts)。

环境变量示例见 [`web/.env.example`](../web/.env.example)。在 `web/.env.local` 中设置 `API_PROXY_TARGET` 可以修改代理目标，`VITE_API_BASE_URL` 控制浏览器请求前缀；修改后需重启 Vite。

部署时，Web 服务器需要配置 `/api` 反向代理，并将页面路由回退到 `index.html`。Vite 开发代理不会进入构建文件。使用跨域的 `VITE_API_BASE_URL` 时，API 服务器需要允许前端域名的 CORS 请求。

## 开发工具与验证

代码检查使用 Oxlint，格式整理使用 Oxfmt；React Compiler 已在开发和构建时启用。命令入口见 [`web/package.json`](../web/package.json)。

`bun test` 覆盖 HTTP 路径与请求体、错误和取消、查询缓存、表单数据转换与草稿/收藏状态；`bun run doctor -- --scope full` 可进行全量 React 检查。
