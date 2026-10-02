# JobScout 前端

## 启动

安装 [Bun](https://bun.sh/docs/installation)，使用 `package.json` 中记录的版本。在仓库根目录执行：

```sh
cd web
bun install --frozen-lockfile
bun run dev
```

打开终端显示的地址，默认是 http://localhost:3000。

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
- `src/state/`：Zustand 工作空间状态和可注入 `SessionClient` 的 store。

React Hook Form 管理资料及追问表单的字段、校验和错误聚焦，通过订阅把草稿同步到 Zustand。组件使用字段级订阅；Zustand 保留跨路由的草稿、会话、检索状态和收藏。切换路由不会中断检索，刷新后内存状态清空，不将简历写入浏览器持久存储。

资料字段通过 `useController` 绑定，确保开启 React Compiler 时，“填入示例”等程序化重置也能同步到输入框。

当前会话仍使用 `session-client.ts` 的本地示例适配器。会话命令由 store 统一执行并防止过期响应覆盖新草稿；此流程没有服务端查询缓存，因此不添加无效的 Query invalidation。保留的 TanStack Query 基础设施可用于后续真实 API 查询，接入时应明确服务端数据的唯一来源，避免与 store 重复保存。

`bun test` 覆盖示例适配器、表单数据转换、状态流转与失败重试；`bun run doctor -- --scope full` 可进行全量 React 检查。
