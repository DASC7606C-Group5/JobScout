# JobScout 前端

## 启动

安装 [Bun](https://bun.sh/docs/installation)，使用 `package.json` 中记录的版本。在仓库根目录执行：

```sh
cd web
bun install --frozen-lockfile
bun run dev
```

打开终端显示的地址，默认是 http://localhost:3000。

前端默认请求 `/api/v1`，Vite 的开发和预览服务器会将 `/api` 转发到 `http://127.0.0.1:8000`。另开一个终端，在仓库根目录启动后端：

```sh
uv run --locked uvicorn jobscout.main:app --reload
```

后端地址不同时，将 `.env.example` 复制为 `.env.local` 并修改 `API_PROXY_TARGET`；浏览器请求前缀由 `VITE_API_BASE_URL` 控制。修改后重启 Vite。部署时需要在 Web 服务器配置 `/api` 反向代理；Vite 开发代理不会进入构建文件。使用跨域的 `VITE_API_BASE_URL` 时，API 服务器需要允许前端域名的 CORS 请求。

## 日常开发

以下命令均在 `web/` 中运行：

| 命令               | 用途                            |
| ------------------ | ------------------------------- |
| `bun run check`    | 检查类型、代码问题和格式        |
| `bun run lint:fix` | 修复可以自动处理的代码问题      |
| `bun run format`   | 整理代码、import 和样式类的顺序 |
| `bun run build`    | 检查类型并生成可发布文件        |
| `bun run preview`  | 在本地查看构建后的页面          |

修复或格式化后，查看改动并重新运行 `bun run check`。代码检查使用 Oxlint，格式整理使用 Oxfmt；React Compiler 已在开发和构建时启用。

新增依赖用 `bun add package-name`，开发工具用 `bun add -d package-name`。把 `package.json` 和 `bun.lock` 一起提交，队友拉取后重新运行 `bun install --frozen-lockfile`。

## 路由与状态

侧边栏使用 TanStack Router 的文件路由：`/` 为发现机会，`/saved` 为收藏岗位。两者共享 `_workspace.tsx` 布局与 `ScoutProvider`，支持直接访问、刷新、浏览器前进/后退。部署时需要将页面路由回退到 `index.html`。

- `src/components/layout/`：侧边栏、顶栏和页面标题。
- `src/components/discovery/`：检索阶段、进度和加载/失败状态。
- `src/components/profile/`：个人介绍、简历、求职方向和偏好字段。
- `src/components/results/`：结果筛选、空态和提示；岗位卡片独立复用。
- `src/lib/session-client.ts`：Session HTTP 请求和错误提示。
- `src/lib/resume-client.ts`：TXT 本地读取和 PDF / DOCX 上传解析，统一返回 `{ name, text }`。
- `src/lib/session-query.ts`：会话 Query key、查询和重试规则。
- `src/state/`：Zustand 草稿和收藏、React Query 会话流程；`ScoutProvider` 可注入 `SessionClient`。

React Hook Form 管理资料及追问表单的字段、校验和错误聚焦，通过订阅把草稿同步到 Zustand。Zustand 保留草稿、追问回答和收藏；服务端会话由 React Query 缓存管理。流程位于共享布局的 `ScoutProvider`，切换到收藏页不会中断请求。刷新页面后前端内存状态清空，不将简历写入浏览器持久存储；提交资料时，个人介绍和简历文字会发送至后端。

简历支持 PDF、DOCX 和 UTF-8 TXT，文件最大 10 MB、提取文字最多 100,000 字。TXT 在浏览器中读取；选择 PDF / DOCX 时以 `multipart/form-data` 上传至 `POST /api/v1/resumes/parse`，字段名为 `file`，解析成功后再写入草稿。Word 提取段落、表格和页眉页脚；PDF 最多 50 页，扫描件需先进行 OCR，加密文件需先移除密码。解析期间禁止提交，离开表单会取消上传，失败时保留已有资料。上传后显示文件名及成功标记，悬停时切换成红色的移除操作，点击后恢复上传入口。后端不保存原始文件到业务存储，也不调用外部解析服务。接口及模块设计见[简历上传说明](../docs/resume-upload-design.md)。

资料字段通过 `useController` 绑定，保持输入框和表单状态同步。

运行时的画像、追问、岗位、技能差距和准备建议均来自 Session API；后端失败或返回空结果时，页面显示相应错误或空态，不回退到固定岗位。单元测试的固定资料及岗位数据位于 `tests/fixtures.ts`，仅由 `.test.ts` 文件引用，不进入应用构建。收藏使用后端返回的岗位数据，目前仅保存在本地内存中；后端尚未提供收藏接口。

会话 API 与 `src/jobscout/schemas/session.py` 对齐：

| 操作 | 请求                                        | 页面行为                                                    |
| ---- | ------------------------------------------- | ----------------------------------------------------------- |
| 创建 | `POST /api/v1/sessions`                     | 发送求职资料，按 `outcome` 显示追问、结果或业务失败         |
| 查询 | `GET /api/v1/sessions/{session_id}`         | 刷新当前会话                                                |
| 回答 | `POST /api/v1/sessions/{session_id}/resume` | 发送 `{ answers }`，保留包含点号的字段名                    |
| 删除 | `DELETE /api/v1/sessions/{session_id}`      | “清除会话”删除服务端会话及其 Query 缓存，保留本地草稿和收藏 |

创建、回答和删除使用 `useMutation`；`useQuery` 读取 `['sessions', session_id]`。创建及回答返回完整快照后直接写入缓存，避免重复 GET。GET 最多自动重试一次，4xx 不自动重试；POST/DELETE 均不自动重试。页面防止重复提交，取消查询时将 `AbortSignal` 传给 fetch，放弃的响应不会覆盖新会话。

HTTP 404 提供重新调整入口，409 提供刷新入口，422 保留资料并提示检查格式，网络及服务错误可以手动重试原请求。后端没有失败会话的重跑接口，业务 `outcome: failed` 的重试会按已更新的草稿创建新会话。推荐及会话中的 warnings 都会展示。后端当前使用内存 checkpoint，重启后旧会话可能返回 404。

`bun test` 覆盖 HTTP 路径与请求体、错误和取消、查询缓存、表单数据转换与草稿/收藏状态；`bun run doctor -- --scope full` 可进行全量 React 检查。
