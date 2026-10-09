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

See [.env.example](.env.example) for an example of the backend's local configuration. To make live model calls, set the server-side `LLM_API_KEY`.

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

| Group | Coding responsibilities |
| --- | --- |
| 1: Frontend and Interaction | Develop the HTML input interface, resume upload, text input, clarification interaction, loading states, and Top 5 result display; call the backend interface. |
| 2: User Profile and Information Confirmation | Process resumes and descriptions, extract education, skills, internships, and projects, output `UserProfile`, check essential information, identify conflicts, and generate clarification content. |
| 3: Overall Workflow | Use LangGraph to manage the JobScout workflow, session state, and node order, pause/resume the process, and call and connect the modules developed by other groups. |
| 4: Job Retrieval | Integrate job APIs/public sources, generate search conditions for different directions, search separately, and output raw job data. |
| 5: Job Understanding and Data Quality | Extract responsibilities and skills, standardize job fields, merge duplicate postings, preserve source links, and check freshness. |
| 6: Matching and Recommendation | Compare profiles with job requirements, generate skill-gap and preparation advice, integrate postings, select Top 5, and output `RecommendationResult`. |

## Documentation

- [Design](DESIGN.md): visual identity and shared component conventions.
