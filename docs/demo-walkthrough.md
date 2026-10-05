# 演示与备用录制

## 模式说明

- **live**：使用配置的 DeepSeek 与支持招聘来源。模型 key 在服务端设置，不在浏览器输入或提交。
- **replay**：显式合成演示，岗位不是正在招聘的信息，模型回答由规则/fixtures 生成。界面必须显示回放标识。不能用它宣称真实模型理解效果。

在 PowerShell 的后端终端启动回放：

```powershell
$env:JOBSCOUT_MODE = 'replay'
uv run --locked uvicorn jobscout.main:app --host 127.0.0.1 --port 8000
```

另开终端运行前端：

```powershell
Set-Location web
bun run dev
```

恢复 live 时在启动后端前设置 `$env:JOBSCOUT_MODE = 'live'`。模型配置见 `.env.example`。回放不是 live 出错的默认处理；只能显式选择。

## 完整路径

1. 介绍自己：粘贴以下合成材料，方向填写 `Data Analyst`，地点 `Hong Kong`，类型 `internship`。先展示文本会发送给模型供应商的提示（回放模式则不外发）。
2. 确认方向：检查可编辑画像与搜索条件，展示未点击确认前没有检索。更正条件时摘要版本变化，旧确认失效。
3. 发现机会：确认后观察阶段进度，展示最多五条结果及匹配理由、来源原文、材料未体现项和准备建议。回放结果数量可能不足五条，不补造岗位。
4. 展示原有过滤/收藏和折叠历史；刷新页面验证会话 ID 恢复。
5. 点击修改条件，说明旧推荐已清除，回到确认而非自动重新搜索。

```text
Skills: Python, SQL
Education: Bachelor in Computer Science
Projects: Python SQL dashboard for a synthetic course project.
```

动态澄清演示：只填上述个人描述，留空方向、地点和类型。回放将显示多选方向、单选地点、单选类型；可使用键盘选择。回放仅支持部分自由文本修正语法（如 `地点：深圳`），完整自由语言理解需 live 模型；始终可使用摘要编辑器。

失败恢复：缺少模型 key 的 live 环境会提示失败并保留输入；修复配置通常需要重启后端（重启会话会过期），重新创建会话。临时 provider 失败的单会话重试由自动化测试覆盖，不要伪造外部服务失败截图。

## 验证与评估

- 后端完整检查：`uv run --locked python scripts/check.py`。
- 前端命令及浏览器测试见 `web/package.json` 与 [前端架构](frontend-architecture.md)。
- 固定基线与 authored replay：见 [评估说明](evaluation.md)。
- 四来源检索实测：见 [来源验证](retrieval-live-validation-2026-10-04.json)。DeepSeek live 若无凭证仍应标记未验证。

## 备用录屏

1. 使用合成输入，不打开 key、`.env` 或个人简历目录；关闭可能显示隐私的通知。
2. 录制前检查后端与前端可响应、回放标识清晰。
3. 连续录制输入 → 澄清/确认 → 结果 → 证据 → 修改条件，保留真实等待和错误说明，不剪辑成不存在的功能。
4. 在录制标题和开头注明 live/replay、数据来源和已验证范围。回放不能标为实时招聘。
5. 将视频保存在项目外的交付位置；记录实际所用命令和检查结果，避免把私密屏幕内容提交进仓库。
