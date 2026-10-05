# Repository guidance

- Follow explicit user instructions over these repository defaults, and apply more specific project instructions where relevant. Use judgment for routine choices; ask only when missing information could materially change the result.
- Read project files and documentation as the task requires. Keep architecture, implementation, workflow, and deployment details in relevant files under `docs/`. Keep README files focused on the overview, prerequisites, quick start, common commands, and links to detailed docs. Update feature docs when behavior changes; update a README only when its overview, setup, common usage, or documentation links change.
- Complete the requested change and the validation relevant to it before handing it back. Keep project documentation and code in English.
- For frontend UI changes, follow the existing daisyUI design and patterns.

## Tests

- Cover behavior, business rules, data contracts, security, state transitions, and concrete regressions with tests that detect meaningful failures.
- Assert observable results, stable IDs or error codes, and preservation of supplied data. Failure tests should require the intended exception or rejection; check identity rather than counts when identity matters.
- Avoid tests for wording, styling, markup details, trivial defaults or accessors, and fixtures or mocks themselves. Remove redundant coverage.
