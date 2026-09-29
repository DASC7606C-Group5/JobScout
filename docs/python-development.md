# Python 开发说明

首次安装与日常提交步骤见 [README](../README.md)。以下命令在仓库根目录执行。

## 启动后端

后端使用 FastAPI 和 Uvicorn，默认通过 SQLite 文件运行。需要使用 PostgreSQL 时，在 `.env` 中设置 `DATABASE_URL`；变量名称和默认值见 [.env.example](../.env.example)。

在仓库根目录启动开发服务器：

```powershell
uv run --locked uvicorn jobscout.main:app --reload
```

基础健康检查接口：

```text
GET http://127.0.0.1:8000/api/v1/health
```

当前数据库配置只负责初始化和关闭 Tortoise ORM 连接，尚未包含业务模型、迁移或 Session CRUD。

## 单独运行检查

| 目的 | 命令 |
| --- | --- |
| 运行全部检查 | `uv run --locked python scripts/check.py` |
| 检查代码问题与 import 顺序 | `uv run --locked ruff check .` |
| 检查格式 | `uv run --locked ruff format --check .` |
| 检查类型 | `uv run --locked mypy` |
| 运行全部测试 | `uv run --locked pytest` |
| 运行一个测试文件 | `uv run --locked pytest tests/test_environment.py` |
| 手动运行提交钩子 | `uv run --locked pre-commit run --all-files` |
| 构建源码包和 wheel | `uv build` |

全部检查命令会运行每一项检查，并在最后列出失败项。它不会自动修改代码；只要有一项失败，命令就以非零状态退出。

## 编写带类型的函数

mypy 检查后端源码、测试和 `scripts/`。函数的参数与返回值都需要类型标注，包括返回 `None` 的函数。例如：

```python
def normalize_skills(skills: list[str]) -> list[str]:
    return [skill.strip().lower() for skill in skills if skill.strip()]
```

如果一个值可能不存在，用 `str | None` 等类型表示，并在使用前处理 `None`。遇到类型错误时，先检查函数签名和调用处是否一致；工具设置集中在 `pyproject.toml`。

## 导入与目录

从 `jobscout` 导入后端模块：

```python
from jobscout.graph import builder
```

`uv sync` 会安装本地包，之后修改源码无需重新安装。新增业务模块放在 `src/jobscout/`，测试放在 `tests/`。`scripts/check.py` 只用于开发检查，不属于应用运行时。

## 测试约定

测试文件命名为 `test_*.py`，测试函数命名为 `test_*`。为业务模块准备固定输入，覆盖正常流程和失败场景，避免在测试中请求真实岗位或模型服务。

pytest 已开启 strict 模式：未注册的测试标记、错误的配置项、重复的参数化测试 ID，以及意外通过的预期失败测试都会导致检查失败。`uv.lock` 固定 pytest 版本；升级后应重新运行全部检查。

## 工具参考

- [uv 项目与锁文件](https://docs.astral.sh/uv/concepts/projects/sync/)
- [Ruff 配置](https://docs.astral.sh/ruff/configuration/)
- [mypy 错误说明](https://mypy.readthedocs.io/en/stable/error_code_list.html)
- [pytest 开发建议](https://docs.pytest.org/en/stable/explanation/goodpractices.html)
