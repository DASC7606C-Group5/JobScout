"""Dimension scores comparing applicant background with job requirements; totals are calculated by the server."""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from jobscout.schemas.conversation import SourceQuoteReference

DimensionId = Literal[
    "skills", "responsibilities", "experience", "seniority", "education", "preferences"
]
DIMENSION_WEIGHTS: dict[DimensionId, int] = {
    "skills": 30,
    "responsibilities": 25,
    "experience": 20,
    "seniority": 10,
    "education": 5,
    "preferences": 10,
}


class DimensionAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: DimensionId
    score: int | None = Field(default=None, ge=0, le=100, strict=True)
    status: Literal["assessed", "unknown", "not_applicable"] = "unknown"
    explanation: str = Field(default="", max_length=800)
    requirement_ids: list[str] = Field(default_factory=list, max_length=30)
    profile_fact_ids: list[str] = Field(default_factory=list, max_length=30)
    job_source_quotes: list[SourceQuoteReference] = Field(default_factory=list, max_length=10)
    profile_source_quotes: list[SourceQuoteReference] = Field(default_factory=list, max_length=10)
    missing_information: list[str] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def consistent_score(self) -> Self:
        if (self.status == "assessed") != (self.score is not None):
            raise ValueError("Only assessed dimensions have a numeric score")
        return self


class MatchDimension(DimensionAssessment):
    weight: int
    input_hash: str


class MatchScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total: int | None = Field(ge=0, le=100)
    dimensions: list[MatchDimension] = Field(min_length=6, max_length=6)
    assessed_weight: int
    applicable_weight: int
    assessed_percentage: int = Field(ge=0, le=100)
    provisional: bool
    completeness: Literal["complete", "partial", "unknown"]
    input_hash: str

    @model_validator(mode="after")
    def fixed_dimensions(self) -> Self:
        if [dimension.id for dimension in self.dimensions] != list(DIMENSION_WEIGHTS):
            raise ValueError("Dimensions must contain the six fixed IDs in weight order")
        return self
