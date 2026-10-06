"""Allowed search tools and their arguments. Calls cannot change confirmed search criteria."""

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
    reason: Literal["results_ready", "target_reached", "source_exhausted"]


class ToolRegistry:
    """Define tool names and arguments for model calls and server-side validation."""

    definitions: dict[str, tuple[type[BaseModel], str]] = {
        "lookup_locations": (
            LocationLookup,
            "Find location names and IDs in the catalog; keep the confirmed search criteria.",
        ),
        "search_jobs": (
            SearchJobs,
            "Search one supported source with equivalent job phrasing and a page. "
            "Desired role, location IDs, and employment types must come from confirmed search criteria.",
        ),
        "fetch_job_details": (
            CandidateSelection,
            "Fetch fuller job descriptions for existing job IDs. No arbitrary URLs are accepted.",
        ),
        "assess_candidates": (
            CandidateSelection,
            "Compare existing jobs with the applicant using source documents. Keep useful jobs even if some comparisons are incomplete; "
            "use skills and experience to order recommendations, not decide whom an employer will hire.",
        ),
        "finish_search": (
            FinishSearch,
            "Deliver useful results with results_ready even below the display limit. "
            "Use target_reached when the display limit is filled or source_exhausted when no useful queries remain.",
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
