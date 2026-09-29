# JobScout 项目骨架 / 协作起点

JobScout 是个性化岗位发现与推荐 Agent 原型。本仓库当前是供团队分工、确认接口并行开发的**开发骨架/协作起点**：包含目录结构、职责说明、开发指南和 Mock 样例，尚不包含完整业务实现，也不能作为可直接运行的成品。

## 环境准备

项目使用 uv 管理 Python 环境和依赖。

先按 [uv 官方安装说明](https://docs.astral.sh/uv/getting-started/installation/) 安装 uv，然后在仓库根目录 `JobScout/` 执行：

```powershell
uv sync --locked
```

这条命令会准备 Python 3.14、创建 `.venv` 并安装依赖。使用 VS Code 时，选择 `.venv` 中的 Python 解释器即可。

### Python 开发命令

提交代码前，在仓库根目录运行全部检查：

```powershell
uv run --locked python scripts/check.py
```

命令会依次检查代码问题、格式和类型，再运行测试。失败时，终端会显示需要修改的位置；全部通过后会显示 `All checks passed.`。

需要整理代码格式时，运行：

```powershell
uv run --locked ruff check --fix .
uv run --locked ruff format .
```

这两条命令会修改文件。查看修改结果后，再运行一次全部检查。单独运行测试、排查类型错误等操作见 [Python 开发说明](docs/python-development.md)。

如果希望每次提交时自动检查代码，可执行一次：

```powershell
uv run --locked pre-commit install
```

提交时会自动检查格式、代码问题和类型；测试仍通过上面的全部检查命令运行。

### 更新依赖

```powershell
uv add package-name                 # 新增运行时依赖
uv add --dev package-name           # 新增开发工具
uv remove package-name             # 删除依赖
uv lock --upgrade-package langgraph # 有意升级单个依赖
uv sync --locked                    # 按锁文件同步环境
```

更新依赖后，运行全部检查，并将 `pyproject.toml` 和 `uv.lock` 一起提交。拉取队友的依赖更新后，运行 `uv sync --locked`。

## 按小组开始

先阅读[开发指南](docs/JobScout_Development_Guide.md)中的本组职责、共享接口和验收场景；Workflow 相关概念可参考[分组 LangGraph 学习路线](docs/langgraph/README.md)。表中路径是建议的代码入口，不代表所有文件都已创建。

| 小组                | 主责代码文件与目录                                                                                                                                                                                                                                                                                                                                                                          | 交付与协作                                                                            |
| ----------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| 第 1 组：前端与交互       | `frontend/index.html`、`frontend/styles.css`、`frontend/app.js`                                                                                                                                                                                                                                                                                                                      | 交付输入、追问、加载/错误/空结果状态及推荐结果展示；按冻结的 Session API 和 JSON 契约收发数据，并用 Mock 验证正常与失败流程。 |
| 第 2 组：用户画像与确认     | `src/jobscout/services/profile_service.py`、`src/jobscout/graph/nodes/profile.py`、`src/jobscout/graph/nodes/clarification.py`、`tests/test_profile_service.py`                                                                                                                                                                                                                  | 交付画像提取/更新、缺失信息识别和追问处理，并测试完整、缺失及矛盾输入；若采用外部模型或简历解析服务，负责搜寻候选方案、用脱敏样例验证质量、隐私要求、限制和成本，再提交团队评估。与第 3 组对齐状态及回答更新契约。 |
| 第 3 组：整体 Workflow | `src/jobscout/main.py`、`src/jobscout/config.py`、`src/jobscout/api/sessions.py`、`src/jobscout/graph/state.py`、`src/jobscout/graph/builder.py`、`src/jobscout/graph/routing.py`、`src/jobscout/schemas/profile.py`、`src/jobscout/schemas/job.py`、`src/jobscout/schemas/search.py`、`src/jobscout/schemas/recommendation.py`、`src/jobscout/schemas/errors.py`、`tests/test_graph_routing.py` | 交付 Session API、可运行的图编排及流程路由测试；集中维护配置和共享 schema，组织接口冻结与端到端集成。各业务组负责提出并验证本组契约/配置需求；外部服务由使用它的业务组调研，新增依赖及其配置、安全和成本由团队确认。 |
| 第 4 组：岗位检索        | `src/jobscout/services/job_search_service.py`、`src/jobscout/graph/nodes/search.py`                                                                                                                                                                                                                                                                                                   | 负责搜寻岗位数据 API/来源并比较覆盖范围、可访问性、字段、更新时效、限流及使用条件；用样例请求验证响应和失败行为，提交候选方案、字段映射及限制供团队选型。交付按 `SearchRequest` 查询并返回带来源、链接和抓取时间的原始岗位，供第 5 组处理。 |
| 第 5 组：岗位理解与数据质量   | `src/jobscout/services/job_processing_service.py`、`src/jobscout/graph/nodes/process_jobs.py`、`tests/test_job_processing_service.py`                                                                                                                                                                                                                                          | 交付原始岗位到统一 `JobPosting` 的字段转换、去重和时效状态处理，并测试缺失字段、重复及未知状态；与第 4 组确认来源字段，与第 6 组确认岗位输入契约。 |
| 第 6 组：匹配与推荐       | `src/jobscout/services/recommendation_service.py`、`src/jobscout/graph/nodes/recommend.py`                                                                                                                                                                                                                                                                                            | 交付符合契约的总体 Top 5、匹配理由、技能差距和准备建议，并验证排序及边界输入；若采用外部模型或推荐工具，负责搜寻候选方案并测试效果、稳定性、延迟、成本和数据要求，提交评估供团队决定是否引入；输出交第 1 组展示。 |

#### 共享文件的归属说明

- `src/jobscout/schemas/` 下的 `profile.py`、`job.py`、`search.py`、`recommendation.py` 和 `errors.py` 是跨组数据契约，不按业务消费者拆成多人各自维护。所有相关小组共同确认字段和兼容性；建议由第 3 组集中维护文件，各业务组负责提出并评审与自身模块相关的变更。契约冻结前应先达成共同约定。
- `src/jobscout/config.py` 由第 3 组主责，配置项需与使用该配置的业务组确认。
- `tests/test_graph_routing.py` 由第 3 组主责；`test_profile_service.py` 由第 2 组主责；`test_job_processing_service.py` 由第 5 组主责；`test_recommendation_service.py` 由第 6 组主责。跨组端到端和集成测试由第 3 组组织，各组共同修复自身模块问题。
- 上述主责是建议的代码维护归属，不改变开发指南中“所有小组共同参与集成”的约定。`main.py` 和 `api/sessions.py` 的实现仍以团队确认 Session API 和后端框架为前提。

### 共同开工步骤

1. 先冻结共享 schema 和错误格式，再开始跨组集成；接口细节以开发指南为准。
2. 用脱敏固定 Mock 并行开发，各组至少覆盖正常与失败/边界场景。
3. 第 3 组先用 Mock nodes 串流程，第 1 组同时用 Mock 结果完成页面。
4. 契约稳定后替换真实模块，再按开发指南的最低测试场景做端到端验收。

每组交付模块入口、输入/输出说明、Mock 示例、测试和集成说明。后端框架、Session API、简历格式、岗位来源及持久化仍待团队确认；确认前不要将它们当作已冻结的实现约束。

## 目录与文件职责

### 根目录

- `README.md`：项目的快速说明书。新成员可以从这里了解项目要做什么、代码大致放在哪里、各组如何协作，以及从哪里开始开发。
- `.gitignore`：告诉 Git 哪些文件不需要提交，例如 Python 自动生成的缓存、虚拟环境、个人本地配置和临时文件，避免把无关文件或私密内容放进版本库。
- `.env.example`：环境变量的示例清单，说明运行项目时可能需要配置哪些名称，例如 API 密钥或服务地址。这里只写变量名和非敏感示例，不能放真实密钥；具体项目确认后再补充。
- `pyproject.toml`：Python 项目元数据、运行时/开发依赖、包构建配置，以及 Ruff、mypy 和 pytest 的统一配置。

### `frontend/`

- `index.html`：网页的骨架，放用户能看到的页面元素，例如简历或求职目标输入框、追问区域、提交按钮和推荐结果区域。它主要描述页面结构，不负责分析简历或计算推荐。
- `styles.css`：网页的外观设置，例如布局、颜色、字体、间距，以及手机和电脑屏幕上的显示方式。
- `app.js`：网页的交互逻辑，例如读取用户输入、显示加载或错误提示、把请求发送给后端 Session API，再把返回的追问或岗位推荐显示出来。它按双方约定的 JSON 格式收发数据，不在浏览器里实现画像提取或推荐算法。

### `src/jobscout/`

- `main.py`：后端程序启动入口。它可能负责创建 Web 应用、加载配置、挂载 API 路由并准备 LangGraph；具体写法取决于团队最后选择的后端框架。
- `config.py`：集中读取程序运行所需的设置，例如外部 API 密钥、模型名称、服务地址和超时。它应从本地环境变量读取敏感值，不应把密钥直接写进代码；不同小组需要的配置项由它们提出，再由维护者统一加入。
- `api/sessions.py`：定义前端使用的 Session API，例如创建或继续一次求职会话、提交用户回答、取得追问或推荐结果。这里处理 HTTP 请求和响应，再把工作交给 Workflow；具体接口和框架仍待团队确认。
- `graph/state.py`：定义 LangGraph 流程中共享的“工作记录”`AgentState`。它可能保存会话标识、对话消息、用户画像、搜索任务、岗位列表和当前阶段，让图中的不同节点能接续前一步的结果。
- `graph/builder.py`：把各个节点连接成完整流程并编译成可运行的图。这里会说明流程从哪里开始、节点按什么顺序执行，以及哪些情况下要走不同分支；不应把简历解析或岗位匹配等业务细节都塞进来。
- `graph/routing.py`：集中放流程分支判断，例如必要资料是否齐全、接下来该追问还是搜索。它根据画像或状态作决定，但具体提取和更新画像的工作交给相应 service 或节点。
- `graph/nodes/`：存放 LangGraph 每一步的“流程接口”。节点通常从 `AgentState` 取资料、调用业务 service、把结果写回状态；复杂业务处理留在 `services/`，这样流程控制和业务逻辑比较容易分别修改和测试。
  - `profile.py`：调用画像 service，从简历或用户描述中取得、补充或更新画像，并把结果写回流程状态；也可能提供画像是否足以继续的结果。
  - `clarification.py`：准备需要向用户确认的问题，并处理用户回答后继续流程所需的状态更新或恢复信息。
  - `search.py`：根据已确认的求职条件调用岗位搜索 service，把岗位来源返回的原始结果放进流程状态，供后续处理。
  - `process_jobs.py`：调用岗位处理 service，整理搜索结果中的字段、合并重复岗位并标记可确认的时效状态。
  - `recommend.py`：调用推荐 service，为用户和岗位计算匹配结果、技能差距及准备建议，并整理成约定的推荐输出。
- `schemas/`：放项目各部分共同遵守的数据格式，像一份清晰的“表格模板”：字段叫什么、是什么类型、哪些必须提供。前端、service 和 graph 都按这些格式交接数据，避免每组各自使用不兼容的字段；字段变更需要相关组共同确认。
  - `profile.py`：定义用户画像 `UserProfile`，可能包括技能、经验、目标岗位或地点等结构化信息，以及哪些资料仍缺失。
  - `job.py`：定义统一的岗位 `JobPosting` 格式，可能包括职位名称、公司、地点、描述、来源链接、抓取时间和岗位状态等字段。
  - `search.py`：定义搜索请求 `SearchRequest` 以及追问消息 `ClarificationMessage` 等格式，说明搜索条件或前后端追问数据应该如何表达。
  - `recommendation.py`：定义推荐结果 `RecommendationResult`，可能包括岗位列表、匹配理由、技能差距、准备建议和总体 Top 5。
  - `errors.py`：定义各模块共用的错误格式，例如错误代码、给用户看的说明、发生阶段和可选的补充详情，让前端能一致地显示失败信息。
- `services/`：放具体业务能力的实现，例如解析资料、查询岗位和计算推荐。它们接收约定格式的数据并返回结果；通常不负责决定 LangGraph 下一步走哪条路，也不直接管理前端 HTTP 会话。
  - `profile_service.py`：读取简历或用户文字，提取并合并画像信息，识别缺失或互相矛盾的内容；若使用外部解析或模型 API，也在这里或其专门 adapter 中封装调用。
  - `job_search_service.py`：接收 `SearchRequest`，调用一个或多个岗位数据来源，并把不同来源的结果整理成带来源标识和链接的原始岗位记录。若有真实性或时效复核需求，可与第 5 组约定可复用的来源查询能力。
  - `job_processing_service.py`：把来源各异的原始岗位整理成统一的 `JobPosting`，处理字段缺失、重复记录和岗位状态；无法确认是否仍有效时应保留 `unknown`，而不是猜测。
  - `recommendation_service.py`：比较用户画像与岗位要求，整理匹配理由、技能差距和准备建议，并按项目约定产生总体 Top 5；匹配方法和模型调用方式由团队后续确定。

### `tests/`

- `test_environment.py`：检查包安装与 LangGraph 基础运行环境，不调用外部服务。
- `test_graph_routing.py`：用小型测试输入检查流程分支是否正确，例如资料不足时会进入追问、资料齐全时会进入岗位搜索。
- `test_profile_service.py`：检查画像处理是否能应对完整、缺失或互相矛盾的用户资料，并产出符合约定的结果。
- `test_job_processing_service.py`：检查岗位字段整理、重复岗位合并和 `active`、`expired`、`unknown` 状态标记是否符合预期。
- `test_recommendation_service.py`：检查推荐结果是否包含约定字段、总体 Top 5 是否正确，以及不同求职方向是否按需求保留。

### `data/`

- `mock_jobs.json`：一组固定的示例岗位数据，格式尽量接近真实搜索结果，但不放真实用户或受限数据。团队会用它让前端先展示推荐结果、让第 5 组测试岗位字段整理/去重/时效处理、让第 6 组验证推荐排序，并支持跨模块集成测试；它不调用真实岗位 API，也不是正式岗位数据库。测试还应按边界场景准备独立样例，不能只依赖这一条记录。

## 开发约定

1. 先冻结 `UserProfile`、`SearchRequest`、`JobPosting`、`RecommendationResult`、`AgentState` 和错误格式，再由各组基于 Mock 数据并行开发。
2. 第三组先用 Mock nodes 串起完整 LangGraph；真实模块就绪后替换节点依赖，不随意改变 State 契约。
3. 缺少必要信息时追问，收到回答后恢复流程；确认必要信息后直接搜索。
4. 最终推荐为所有目标方向合并后的总体 Top 5。无法确认岗位时效时标记 `unknown`，不得假装 active。
5. 后端框架、Session API 细节、简历文件格式、岗位来源和 session 持久化均待团队确认。本骨架不预设这些决策。
6. 所有 API keys、真实简历和受限数据只存放在本地环境中，不提交到版本库。

## 建议开发顺序

接口确认 → Mock 数据与模块测试 → Mock graph 和前端 → 接入画像、岗位检索、岗位处理与推荐模块 → 端到端测试和 demo 检查。
