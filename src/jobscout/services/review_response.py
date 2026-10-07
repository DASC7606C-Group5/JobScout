"""Compact model output for one job; source quotations are resolved by the server."""

from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from jobscout.schemas.matching import DimensionId
from jobscout.schemas.recommendation import RecommendationFit


class Comparison(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirement_id: str
    level: Literal["strong", "partial", "related_experience", "not_documented"]
    profile_fact_ids: list[str] = Field(default_factory=list)
    profile_quote_ids: list[str] = Field(default_factory=list)
    qualification_relation: Literal["meets", "partial", "does_not_meet", "unknown"] | None = None
    experience_months: int | None = Field(default=None, ge=0, le=1200, strict=True)
    explanation: str = Field(max_length=500)


class DimensionSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: DimensionId
    score: int | None = Field(default=None, ge=0, le=100, strict=True)
    status: Literal["assessed", "unknown", "not_applicable"] = "unknown"
    requirement_ids: list[str] = Field(default_factory=list, max_length=30)
    explanation: str = Field(default="", max_length=500)
    missing_information: list[str] = Field(default_factory=list, max_length=3)

    @model_validator(mode="after")
    def consistent_score(self) -> Self:
        if (self.status == "assessed") != (self.score is not None):
            raise ValueError("Only assessed dimensions have a numeric score")
        return self


class SummaryReviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    recommendation_fit: RecommendationFit
    recommendation_reason: str = Field(max_length=600)
    matches: list[Comparison] = Field(default_factory=list, max_length=30)
    incomplete: bool = False

    @model_validator(mode="before")
    @classmethod
    def retain_valid_sections(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        result = dict(value)
        for field, schema in (("matches", Comparison), ("dimensions", DimensionSummary)):
            if not isinstance(result.get(field), list):
                continue
            retained = []
            for row in result[field]:
                try:
                    retained.append(schema.model_validate(row))
                except ValidationError:
                    result["incomplete"] = True
            result[field] = retained
        return result


class ReviewResponse(SummaryReviewResponse):
    dimensions: list[DimensionSummary] = Field(default_factory=list, max_length=6)
    preparation_suggestions: list[str] = Field(default_factory=list, max_length=2)


def profile_quotes(documents: dict[str, str]) -> dict[str, dict[str, str]]:
    """Give original, nonempty lines short IDs; never ask the model to copy PDF text."""
    quotes: dict[str, dict[str, str]] = {}
    for document_id, text in documents.items():
        for line in text.splitlines():
            if line.strip():
                quotes[f"p{len(quotes)}"] = {"document_id": document_id, "excerpt": line}
    return quotes
