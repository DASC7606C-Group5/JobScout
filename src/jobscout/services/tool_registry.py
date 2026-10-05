"""Closed, typed search capabilities. Tool arguments never grant new authority."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ToolArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LocationLookup(ToolArguments):
    text: str = Field(min_length=1, max_length=200)


class SearchJobs(ToolArguments):
    direction: str = Field(min_length=1, max_length=200)
    source: str = Field(min_length=1, max_length=40)
    keywords: list[str] = Field(min_length=1, max_length=3)
    location_ids: list[str] = Field(default_factory=list, max_length=10)
    employment_types: list[str] = Field(default_factory=list, max_length=5)
    page: int = Field(default=1, ge=1, le=5)


class CandidateSelection(ToolArguments):
    job_ids: list[str] = Field(min_length=1, max_length=10)


class FinishSearch(ToolArguments):
    reason: Literal["target_reached", "source_exhausted"]


class ToolRegistry:
    """A single registry drives native function schemas and server-side validation."""

    definitions: dict[str, tuple[type[BaseModel], str]] = {
        "lookup_locations": (
            LocationLookup,
            "Look up trusted location names and identities; does not change confirmed conditions.",
        ),
        "search_jobs": (
            SearchJobs,
            "Search one supported source with equivalent job phrasing and a page. "
            "Direction, location identities, and employment types must come from confirmed conditions.",
        ),
        "fetch_job_details": (
            CandidateSelection,
            "Fetch fuller source evidence for existing job IDs. No arbitrary URLs are accepted.",
        ),
        "assess_candidates": (
            CandidateSelection,
            "Analyze existing jobs and independently review the result against original evidence. "
            "Only complete, reviewed analyses become available results.",
        ),
        "review_results": (
            CandidateSelection,
            "Review existing analyses and obtain concrete defects and repair suggestions. "
            "A failed analysis may be corrected once using assess_candidates.",
        ),
        "finish_search": (
            FinishSearch,
            "Deliver completed results after reaching the target or exhausting useful source queries.",
        ),
    }

    def schemas(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": schema.model_json_schema(),
                },
            }
            for name, (schema, description) in self.definitions.items()
        ]

    def validate(self, name: str, arguments: dict[str, Any]) -> BaseModel:
        if name not in self.definitions:
            raise ValueError("unknown_tool")
        return self.definitions[name][0].model_validate(arguments)
