# JobScout

JobScout is a prototype agent for personalized job discovery and recommendations.

The frontend is built with React and TypeScript. The backend uses FastAPI and LangGraph.

## Quick start

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and [Bun](https://bun.sh/docs/installation).

From the repository root, install the dependencies and start the backend:

```sh
uv sync --locked
uv run --locked uvicorn jobscout.main:app --reload
```

The backend runs at [http://127.0.0.1:8000](http://127.0.0.1:8000) by default. Browse to [/docs](http://127.0.0.1:8000/docs) for the API documentation.

In a separate terminal, start the frontend from the repository root:

```sh
cd web
bun i
bun dev
```

Open the URL printed in the terminal. By default, it is [http://localhost:3000](http://localhost:3000).

See [.env.example](.env.example) for an example of the backend's local configuration. To make live model calls, set the server-side `LLM_SEMANTIC_API_KEY` and `LLM_DECISION_API_KEY`.

If the backend is running at a different address, copy [`web/.env.example`](web/.env.example) to `web/.env.local`, update `API_PROXY_TARGET`, and restart Vite.

## Development commands

| Command | Run from | Purpose |
| --- | --- | --- |
| `uv run --locked python scripts/check.py` | Repository root | Check Python code, formatting, and types, then run the tests |
| `bun test` | `web/` | Run frontend unit tests |
| `bun check` | `web/` | Check frontend types, code issues, and formatting |
| `bun lint:fix` | `web/` | Automatically fix code issues where possible |
| `bun format` | `web/` | Format the frontend code |
| `bun run build` | `web/` | Check types and build the frontend |
| `bun preview` | `web/` | Preview the frontend build locally |

Before committing, run all backend checks, plus `bun test` and `bun check` for the frontend. After fixing or formatting code, review the changes and run the checks again.

## Team responsibilities

Both members of each group jointly handle coding and testing. One member in each group acts as the Report Liaison and the other as the Presentation Liaison, organizing the group's work for the final report and the presentation/demo while both remain involved in technical discussions and coding.

| Group | Members | Coding responsibilities |
| --- | --- | --- |
| 1: Frontend and Interaction | 龙良茂 (Long Liangmao, Foah), 张凯森 (Zhang Kaisen) | Build the React interface for resume upload, profile editing, clarification, search confirmation, live progress, job results with a user-selected limit of 5–20, saved jobs, feedback, and settings; connect these views to the backend API. |
| 2: User Profile and Information Confirmation | 王寒正 (Wang Hanzheng), 赵钧翊 (Zhao Junyi) | Parse resumes and descriptions, extract education, skills, internships, and projects into `UserProfile`, interpret preferences, identify missing or conflicting information, generate clarification questions, and apply user corrections. |
| 3: Overall Workflow | 施雨君 (Shi Yujun), 赫锦竹 (He Jinzhu) | Connect the modules through LangGraph; manage search confirmation, pause/resume, session persistence, operation queues, progress updates, stopping, and recovery; coordinate the agent's search and assessment actions. |
| 4: Job Retrieval | 陈泉睿 (Chen Quanrui), 李浚萁 (Li Junqi) | Connect supported job sources, translate search requests into source-specific queries, retrieve listings and fuller descriptions, and handle pagination, caching, and source failures; return raw job data for processing. |
| 5: Job Understanding and Data Quality | 朱俊舟 (Zhu Junzhou), 罗书航 (Luo Shuhang) | Standardize job records, merge duplicate postings, preserve source links and quotations, check freshness, and extract individual job requirements for matching. |
| 6: Matching and Recommendation | 肖隽 (Xiao Jun), 卜轩 (Bu Xuan) | Compare applicant background with job requirements, validate supporting quotations, calculate six-dimensional scores, rank results up to the user-selected limit of 5–20, provide preparation advice, and handle result preferences and follow-up recommendations; output `RecommendationResult`. |

## Documentation

- [Design](DESIGN.md): visual identity and shared component conventions.
