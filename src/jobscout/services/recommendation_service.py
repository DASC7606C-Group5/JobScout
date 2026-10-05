"""Profile guards, candidate eligibility, and evidence-validation primitives."""

import unicodedata
from collections.abc import Sequence

from jobscout.schemas.errors import WorkflowError
from jobscout.schemas.job import FreshnessStatus, JobPosting
from jobscout.schemas.profile import UserProfile
from jobscout.services.location_service import get_location_catalog, within


class RecommendationError(ValueError):
    """A Python exception carrying the shared workflow error contract."""

    def __init__(self, code: str, message: str) -> None:
        self.error = WorkflowError(code=code, message=message, stage="recommend")
        super().__init__(message)


def _normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def _unique_skills(skills: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for skill in skills:
        key = _normalize(skill)
        if key and key not in seen:
            result.append(skill.strip())
            seen.add(key)
    return result


def _employment_type(text: str) -> str | None:
    return (
        text if text in {"full-time", "part-time", "internship", "contract", "freelance"} else None
    )


def _job_employment_type(job: JobPosting) -> str | None:
    return _employment_type(job.employment_type or "")


def _preference_check(profile: UserProfile, job: JobPosting) -> tuple[bool, list[str]]:
    """Reject only explicit catalog/native facts; unresolved semantics await analysis."""
    warnings: list[str] = []
    preferences = profile.preferences
    condition = preferences.locations
    places = get_location_catalog().find(job.location)
    if condition.included or condition.excluded or not condition.unrestricted:
        if len(places) != 1:
            warnings.append("location")
        else:
            actual = places[0]
            if any(within(actual, excluded) for excluded in condition.excluded):
                return False, []
            if any(within(excluded, actual) for excluded in condition.excluded):
                warnings.append("location")
            if condition.included and not any(
                within(actual, wanted) for wanted in condition.included
            ):
                if any(within(wanted, actual) for wanted in condition.included):
                    warnings.append("location")
                else:
                    return False, []
            elif not condition.included and not condition.unrestricted:
                warnings.append("location")
    employment = preferences.employment
    actual_type = _job_employment_type(job)
    if employment.included or employment.excluded or not employment.unrestricted:
        if actual_type is None:
            warnings.append("employment_type")
        elif actual_type in employment.excluded or (
            employment.included and actual_type not in employment.included
        ):
            return False, []
        elif not employment.included and not employment.unrestricted:
            warnings.append("employment_type")
    return True, list(dict.fromkeys(warnings))


def _direction_matches(profile: UserProfile, job: JobPosting) -> bool:
    directions = {_normalize(value) for value in profile.target_directions if value.strip()}
    return any(
        _normalize(value) in directions for value in [job.target_direction, *job.target_directions]
    )


def eligible_jobs(profile: UserProfile, jobs: Sequence[JobPosting]) -> list[JobPosting]:
    """Return unique eligible vacancies before result-count checks and model analysis.

    Only confirmed hard constraints exclude candidates. Unknown conditions remain
    eligible; normalized company/title/location and source URLs prevent duplicates
    from inflating the candidate count. Input objects are not changed.
    """
    selected: list[JobPosting] = []
    seen_ids: set[str] = set()
    seen_urls: set[str] = set()
    seen_keys: set[tuple[str, str, str]] = set()
    for job in sorted(jobs, key=lambda item: (item.job_id, item.source_url)):
        if (
            job.freshness_status == FreshnessStatus.EXPIRED
            or not _direction_matches(profile, job)
            or not _preference_check(profile, job)[0]
        ):
            continue
        key = (_normalize(job.company), _normalize(job.title), _normalize(job.location))
        urls = {url.rstrip("/") for url in [job.source_url, *job.source_links] if url.strip()}
        if job.job_id in seen_ids or urls & seen_urls or key in seen_keys:
            continue
        seen_ids.add(job.job_id)
        seen_urls.update(urls)
        seen_keys.add(key)
        selected.append(job)
    return selected


def validate_recommendation_profile(profile: UserProfile, session_id: str) -> None:
    """Reject invalid recommendation requests before model work or cache mutations."""
    if not session_id.strip():
        raise RecommendationError(
            "recommendation_invalid_session",
            "A non-empty session_id is required for recommendations.",
        )
    if (
        profile.missing_required_fields
        or profile.conflicts
        or not any(direction.strip() for direction in profile.target_directions)
    ):
        raise RecommendationError(
            "recommendation_profile_not_ready",
            "The profile has missing information or unresolved conflicts.",
        )
