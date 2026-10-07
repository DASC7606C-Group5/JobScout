"""Applicant background and search preferences used across the application."""

from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from jobscout.schemas.wire import WireModel

EmploymentType = Literal["full-time", "part-time", "internship", "contract", "freelance"]
WorkMode = Literal["remote", "hybrid", "onsite"]


class LocationRef(WireModel):
    """A place and its catalog ID, looked up rather than invented by the model."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    region: Literal["cn", "hk"]
    level: Literal["country", "region", "city", "district"]
    parent_id: str | None = None
    ancestor_ids: list[str] = Field(default_factory=list)
    source_codes: dict[str, str] = Field(default_factory=dict)
    resolution: Literal["resolved", "ambiguous", "unsupported"] = "resolved"


class LocationCondition(WireModel):
    model_config = ConfigDict(extra="forbid")

    raw_text: str | None = None
    included: list[LocationRef] = Field(default_factory=list)
    excluded: list[LocationRef] = Field(default_factory=list)
    unrestricted: bool = False


class EmploymentCondition(WireModel):
    model_config = ConfigDict(extra="forbid")

    raw_text: str | None = None
    included: list[EmploymentType] = Field(default_factory=list)
    excluded: list[EmploymentType] = Field(default_factory=list)
    unrestricted: bool = False

    @model_validator(mode="after")
    def validate_conditions(self) -> EmploymentCondition:
        if set(self.included) & set(self.excluded):
            raise ValueError("An employment type cannot be both included and excluded.")
        return self


class SearchOptions(WireModel):
    model_config = ConfigDict(extra="forbid")

    result_count: int = Field(default=10, ge=5, le=20, strict=True)


class WorkArrangement(WireModel):
    model_config = ConfigDict(extra="forbid")

    raw_text: str | None = None
    included: list[WorkMode] = Field(default_factory=list)
    excluded: list[WorkMode] = Field(default_factory=list)
    unrestricted: bool = False
    uncertain: bool = False

    @property
    def source_filter(self) -> WorkMode | None:
        if self.uncertain or self.unrestricted or self.excluded or len(self.included) != 1:
            return None
        return self.included[0]


class ProfileSource(WireModel):
    model_config = ConfigDict(extra="forbid")

    resume: bool = False
    description: bool = False


class RawProfilePreferences(WireModel):
    model_config = ConfigDict(extra="forbid")

    location: str | None = None
    location_unrestricted: bool = False
    employment_type: str | None = None
    employment_type_unrestricted: bool = False
    salary_range: str | None = None
    work_mode: str | None = None
    industry: str | None = None


class ProfilePreferences(RawProfilePreferences):
    locations: LocationCondition = Field(default_factory=LocationCondition)
    employment: EmploymentCondition = Field(default_factory=EmploymentCondition)
    work_arrangement: WorkArrangement = Field(default_factory=WorkArrangement)


class UserProfile(WireModel):
    model_config = ConfigDict(extra="forbid")

    profile_id: str
    source: ProfileSource = Field(default_factory=ProfileSource)
    education: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    internships: list[str] = Field(default_factory=list)
    projects: list[str] = Field(default_factory=list)
    target_directions: list[str] = Field(default_factory=list)
    preferences: ProfilePreferences = Field(default_factory=ProfilePreferences)
    search_options: SearchOptions = Field(default_factory=SearchOptions)
    confirmed_fields: list[str] = Field(default_factory=list)
    missing_required_fields: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
