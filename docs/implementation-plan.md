# JobScout: Evidence-Based Job Discovery with Interactive Clarification

## Summary

Complete the existing JobScout repository as a usable job discovery agent for students, postgraduate students, and career changers.

Preserve the current three-step interface:

**Introduce yourself → Confirm your direction → Discover opportunities**

The completed workflow accepts a resume or personal description, understands the user’s background, clarifies missing or conflicting information, confirms a search plan, retrieves real vacancies, and returns an overall Top 5 with evidence-supported matching reasons and preparation suggestions.

Deliver runnable code, automated tests, representative evaluation cases, architecture documentation, and demonstration materials. Final report writing and slide production remain outside this implementation.

## Research Patterns to Adopt

| Reference | Pattern adopted in JobScout |
|---|---|
| [Open Deep Research](https://github.com/langchain-ai/open_deep_research/blob/main/src/open_deep_research/deep_researcher.py) | Convert clarified conversation into a focused search brief; enforce explicit iteration limits. |
| [Job Market Intelligence System](https://github.com/Mostafa-M-Abla/job-market-intelligence-system) | Pause before retrieval so the user can confirm or revise search parameters. |
| [LangGraph Resume Copilot](https://github.com/EchoEvelyn/LangGraph_Resume_Copilot) | Separate model-based understanding from deterministic scoring; reuse validated extraction results. |
| [GPT Researcher](https://github.com/assafelovic/gpt-researcher) | Preserve source information during retrieval and analysis so final claims can be checked. |

Implement these patterns within the existing architecture. These repositories serve as design references, rather than additional application dependencies.

## Implementation Changes

### User experience

- Preserve the existing layout, styling, navigation, resume upload, result cards, filtering, and saved-job functionality.
- Keep the introductory form. Allow partial direction and preference information; change its submit action to begin AI analysis and clarification.
- Replace the separate clarification questionnaire with a conversation containing structured answer controls: single choice, multiple choice, and text input. Informational assistant messages require no answer.
- Show at most three questions per turn. Accept free-text additions and corrections alongside structured answers, and retain previous messages and answers.
- Display the current understood profile and search conditions in an editable summary within the confirmation step.
- Require a direction, supported location or explicit unrestricted location, and employment type or explicit unrestricted type. Optional questions can be skipped and must not subsequently reappear without new relevant information.
- Ask follow-up questions when answers remain ambiguous. After three optional clarification rounds, move to the summary. After two unsuccessful attempts to resolve the same required field, offer direct editing instead of repeating generated questions.
- Search only after the user confirms the displayed summary through the button or a clear textual instruction. Corrections invalidate the previous confirmation.
- Present a short assistant introduction followed by the existing structured result cards. Keep the conversation available as collapsed history. Changing search conditions returns to confirmation and clears the previous recommendation.

### Model understanding and workflow

- Introduce an injectable, typed model service with a native DeepSeek implementation using asynchronous HTTP requests and Pydantic validation.
- Use the model for profile extraction, contextual clarification, search phrasing, JD understanding, semantic matching evidence, and preparation suggestions.
- Preserve useful deterministic code for file parsing, input validation, source routing, normalization, deduplication, freshness classification, eligibility checks, and ranking.
- Replace the current rule that treats different resume and description skill lists as a conflict. Complementary information should merge; contradictory claims require confirmation. Explicit user corrections take precedence.
- Implement the LangGraph sequence: **extract → validate → clarification loop → confirm → plan → retrieve → normalize and understand → assess coverage → recommend → present**.
- Place user waits in dedicated interrupt nodes. Model calls and retrieval must not repeat merely because an interrupted graph resumes.
- Limit search plans to three user-selected directions. Generate source-appropriate phrases without silently adding skill filters or changing confirmed constraints.
- If fewer than five eligible candidates remain, permit one additional retrieval round using alternative phrases for the same directions. Never broaden location or employment type automatically.

### Retrieval, evidence, and recommendations

- Retain JobsDB, Zhaopin, Liepin, and Shixiseng adapters and their regional routing. Describe this as searching supported recruitment sources in Hong Kong and mainland China.
- Preserve successful results when another source fails. Separate fatal workflow errors from source-level diagnostics; distinguish successful empty searches from blocked or unavailable sources.
- Support unrestricted employment type without rejecting it or inventing a specific type. Keep salary, industry, and work mode as advisory preferences where sources cannot reliably verify them.
- Default each source query to one listing page, ten returned candidates, and three detail requests. Bound retrieval to 60 seconds and the complete search operation to 180 seconds.
- Normalize and deduplicate before model analysis. Analyze at most twenty candidates, selected by balanced rotation across directions and sources, preferring complete descriptions and using stable IDs for ties.
- Process model analysis in batches of five candidates with concurrency two. Reuse validated JD analysis within the session using content, model, and schema hashes.
- Preserve original JD text, excerpt status, source metadata, employment type when available, and fetch timestamps. Model extraction must not overwrite URLs, dates, salary, or vacancy status.
- Require supporting source excerpts for extracted requirements and matching claims. Verify that excerpts occur in the corresponding source text; reject unsupported claims.
- Classify requirement matches as strong, partial, related experience, or not evidenced. Describe the latter as information absent from the supplied materials, rather than proven lack of ability.
- Retain deterministic scoring weights: 70% requirement coverage, 20% relevant project or internship evidence, and 10% education alignment. Requirement match values are respectively 1, 0.5, 0.25, and 0. Education receives credit only when supported.
- Exclude expired vacancies and verified hard-condition mismatches. Preserve the existing preference for active over unknown vacancies, then order by score with stable tie-breaking.
- Return at most five unique vacancies across all directions. Each includes matching reasons, supporting evidence, skill gaps, preparation suggestions, source links, and uncertainty notices. Never fabricate vacancies to fill the list.

### API, state, and failure handling

- Keep session creation, retrieval, deletion, and resume parsing endpoints. Extend the session resume request to accept a free-text message, typed question answers, skipped question IDs, and an explicit search action.
- Extend session responses with conversation history, question control types and options, search summary, current stage, revision, source outcomes, and a `running` outcome.
- Extend recommendation items with matching reasons and evidence references. Preserve existing recommendation and vacancy fields.
- Execute workflow operations asynchronously and return accepted session snapshots. Poll GET once per second while running; stop polling when waiting for the user or finished. Token streaming is outside v1.
- Permit one active operation per session. Use request IDs for duplicate detection and revisions to reject stale submissions. Deleting a session cancels its operation and prevents late responses from restoring it.
- Validate JSON syntax, schemas, referenced IDs, and evidence before applying model output. Allow one repair attempt for invalid output. Authentication errors fail immediately; transient failures permit one bounded retry.
- Profile-understanding failures retain user input and expose retry. Individual JD or matching failures retain deterministic analysis with an explicit warning. Never silently substitute demo data during live operation.
- Log stage timing, source counts, model usage, and error codes without logging resumes, credentials, or private reasoning.

## Validation and Delivery

- Cover complete input, resume-only input, bilingual descriptions, complementary information, contradictions, insufficient answers, optional skips, unrestricted preferences, explicit confirmation, and corrections after confirmation.
- Cover multiple directions, duplicate vacancies, partial source failures, total retrieval failure, empty results, missing JD details, expiry evidence, invalid model output, unsupported claims, duplicate submissions, deletion during processing, and session isolation.
- Add browser-level tests for the complete three-step workflow, dynamic controls, keyboard interaction, retry, and changing conditions.
- Build a fixed evaluation set with twelve synthetic user profiles and thirty annotated vacancies. Compare the existing rules baseline against model-assisted understanding using identical candidates.
- Report profile extraction precision/recall, clarification completion, constraint violations, Precision@5, evidence support, latency, and model usage. Identify annotation provenance and distinguish synthetic, replayed, and live results.
- Keep routine tests offline through injected model and retrieval fixtures. Verify live DeepSeek and supported-source retrieval separately before describing the live integration as complete.
- Run backend lint, formatting checks, type checking, and tests; frontend tests, type checking, lint, formatting checks, production build, and React Doctor regression checks. Resolve the observed Node runtime configuration issue before claiming frontend checks pass.
- Provide sample inputs, sanitized replay fixtures, evaluation output, an architecture diagram, and a demonstration walkthrough covering input through recommendation. Include backup-recording instructions and a clearly labelled replay mode.
- Save this English specification as `docs/implementation-plan.md` when implementation begins. Update relevant architecture and feature documents under `docs/`; keep README changes limited to setup, common commands, and documentation links.

## Assumptions and Defaults

- Use DeepSeek’s `deepseek-flash` model by default, with thinking disabled and configuration through backend environment variables. The current official documentation identifies this model and supports JSON output; application-level schema validation remains required. [Model documentation](https://api-docs.deepseek.com/quick_start/pricing/), [JSON output documentation](https://api-docs.deepseek.com/guides/json_mode/)
- Preserve React, TypeScript, daisyUI, FastAPI, and LangGraph. Update affected contracts and their callers together.
- Use Chinese interface copy while accepting Chinese and English user materials and vacancies.
- Keep the single-process, in-memory session model for v1. Store only the session ID in browser session storage for refresh recovery; backend restart expires sessions.
- Explain before submission that resume text is sent to the configured model provider. Keep credentials server-side and exclude private resumes from committed fixtures.
- Exclude resume rewriting, interview simulation, automatic applications, long-term monitoring, general career chat, additional search providers, authentication, and production hosting.
- Record actual implementation and review work in contribution materials; do not infer individual contributions from the original allocation.

## Confirmed Budget Interpretation

The 60-second retrieval budget and the limit of twenty model-analyzed candidates apply cumulatively to one confirmed search, including its optional additional retrieval round. The entire search remains bounded to 180 seconds; human clarification and confirmation waits are excluded. An additional round must use remaining budgets and may not broaden confirmed constraints.
