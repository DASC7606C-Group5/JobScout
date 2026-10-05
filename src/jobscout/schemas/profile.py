"""User profile contracts shared by profile, workflow, and recommendation modules."""

from pydantic import BaseModel, ConfigDict, Field


class ProfileSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resume: bool = False
    description: bool = False


class ProfilePreferences(BaseModel):
    model_config = ConfigDict(extra="forbid")

    location: str | None = None
    location_unrestricted: bool = False
    employment_type: str | None = None
    employment_type_unrestricted: bool = False
    salary_range: str | None = None
    work_mode: str | None = None
    industry: str | None = None


class UserProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_id: str
    source: ProfileSource = Field(default_factory=ProfileSource)
    education: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    internships: list[str] = Field(default_factory=list)
    projects: list[str] = Field(default_factory=list)
    target_directions: list[str] = Field(default_factory=list)
    preferences: ProfilePreferences = Field(default_factory=ProfilePreferences)
    confirmed_fields: list[str] = Field(default_factory=list)
    missing_required_fields: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
