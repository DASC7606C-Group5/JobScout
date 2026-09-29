"""Graph node entry point for job normalization and data quality checks.

The node itself holds no business logic: it reads the raw retrieval results
from the shared ``AgentState``, delegates normalization, deduplication and
freshness classification to
:func:`jobscout.services.job_processing_service.process_jobs`, and returns the
state update for LangGraph to merge.

``AgentState`` (``jobscout/graph/state.py``) is owned by Group 3 and not frozen
yet, so this node uses the keys agreed in the development guide (section 4.4)
plus one assumption documented on the issue:

- input: ``raw_jobs`` — raw records returned by Group 4's retrieval;
- output: ``jobs`` — normalized ``JobPosting`` objects for Group 6;
- output: ``job_processing_warnings`` — data-quality warnings collected while
  processing, kept separate from the user-facing result ``warnings``.
"""

from collections.abc import Mapping
from typing import Any

from jobscout.services.job_processing_service import process_jobs


def process_jobs_node(state: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize ``state['raw_jobs']`` into unified job postings."""
    raw = state.get("raw_jobs") or []
    result = process_jobs(list(raw))
    return {
        "jobs": result.jobs,
        "job_processing_warnings": result.warnings,
    }
