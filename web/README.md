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
