"""Load replay inputs and expected model answers as a single validated dataset."""

from pathlib import Path
from typing import NotRequired, TypedDict

from pydantic import BaseModel, ConfigDict

# Replay samples live in the repository data directory, not in the installed package.
DEFAULT_DATASET = Path(__file__).resolve().parents[3] / "data" / "replay" / "scenarios.json"


class Resume(TypedDict):
    name: str
    text: str


class Preferences(TypedDict):
    location: str | None
    location_unrestricted: bool
    employment_type: str | None
    employment_type_unrestricted: bool


class ProfileInput(TypedDict):
    description: str
    resume: Resume | None
    target_directions: list[str]
    preferences: Preferences


class Background(TypedDict):
    education: list[str]
    skills: list[str]
    internships: list[str]
    projects: list[str]
    conflicts: list[str]


class ProfileSample(TypedDict):
    case_id: str
    input: ProfileInput
    background: Background


class JobRecord(TypedDict):
    source_url: str
    job_id: str
    fetched_at: str
    title: str
    company: str
    location: str
    target_direction: str
    description: str
    posted_at: str | None
    expiry_at: str | None
    employment_type: str
    freshness_status: str
    description_is_excerpt: bool
    salary: NotRequired[str | None]


class Reference(TypedDict):
    document_id: str
    excerpt: str
    source_url: str


class Requirement(TypedDict):
    requirement_id: str
    text: str
    references: list[Reference]


class JobSample(TypedDict):
    job: JobRecord
    requirements: list[Requirement]


class ReplayDataset(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    profiles: list[ProfileSample]
    jobs: list[JobSample]

    def profile_input(self, case_id: str) -> ProfileInput:
        for profile in self.profiles:
            if profile["case_id"] == case_id:
                return profile["input"]
        raise KeyError(case_id)


def load_dataset(path: Path = DEFAULT_DATASET) -> ReplayDataset:
    return ReplayDataset.model_validate_json(path.read_text(encoding="utf-8"))
