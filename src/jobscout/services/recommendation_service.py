"""Check search preferences, remove duplicate jobs, and validate the applicant's profile."""

import unicodedata
from collections.abc import Sequence

from jobscout.schemas.errors import WorkflowError
from jobscout.schemas.job import FreshnessStatus, JobPosting
from jobscout.schemas.job_status import ExclusionReason
from jobscout.schemas.profile import UserProfile
from jobscout.services.location_service import get_location_catalog, within


class RecommendationError(ValueError):
    """A Python exception containing a WorkflowError code, message and stage."""

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


def _preference_check(
    profile: UserProfile, job: JobPosting
) -> tuple[list[ExclusionReason], list[str]]:
    """Reject known location or employment mismatches; leave unclear details for model analysis."""
    warnings: list[str] = []
    conflicts: list[ExclusionReason] = []
    preferences = profile.preferences
    condition = preferences.locations
    places = get_location_catalog().find(job.location)
    if condition.included or condition.excluded or not condition.unrestricted:
        if len(places) != 1:
            warnings.append("location")
        else:
            actual = places[0]
            if any(within(actual, excluded) for excluded in condition.excluded):
                conflicts.append("location")
            if any(within(excluded, actual) for excluded in condition.excluded):
                warnings.append("location")
            if condition.included and not any(
                within(actual, wanted) for wanted in condition.included
            ):
                if any(within(wanted, actual) for wanted in condition.included):
                    warnings.append("location")
                else:
                    conflicts.append("location")
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
            conflicts.append("employment_type")
        elif not employment.included and not employment.unrestricted:
            warnings.append("employment_type")
    return list(dict.fromkeys(conflicts)), list(dict.fromkeys(warnings))


def _direction_matches(profile: UserProfile, job: JobPosting) -> bool:
    directions = {_normalize(value) for value in profile.target_directions if value.strip()}
    return any(
        _normalize(value) in directions for value in [job.target_direction, *job.target_directions]
    )


def _screen_candidates(
    profile: UserProfile, jobs: Sequence[JobPosting]
) -> tuple[list[JobPosting], dict[str, list[ExclusionReason]]]:
    """Keep the exact exclusion reason while applying the candidate eligibility rules."""
    excluded: dict[str, list[ExclusionReason]] = {}
    selected: list[JobPosting] = []
    seen_ids: set[str] = set()
    seen_urls: set[str] = set()
    seen_keys: set[tuple[str, str, str]] = set()
    for job in sorted(jobs, key=lambda item: (item.job_id, item.source_url)):
        if job.job_id in seen_ids:
            continue
        reasons, _ = _preference_check(profile, job)
        if job.freshness_status == FreshnessStatus.EXPIRED:
            reasons.insert(0, "expired")
        if not _direction_matches(profile, job):
            reasons.append("role")
        if reasons:
            excluded[job.job_id] = reasons
            continue
        key = (_normalize(job.company), _normalize(job.title), _normalize(job.location))
        urls = {url.rstrip("/") for url in [job.source_url, *job.source_links] if url.strip()}
        if urls & seen_urls or key in seen_keys:
            excluded[job.job_id] = ["duplicate"]
            continue
        seen_ids.add(job.job_id)
        excluded.pop(job.job_id, None)
        seen_urls.update(urls)
        seen_keys.add(key)
        selected.append(job)
    return selected, excluded


def eligibility_exclusions(
    profile: UserProfile, jobs: Sequence[JobPosting]
) -> dict[str, list[ExclusionReason]]:
    return _screen_candidates(profile, jobs)[1]


def eligible_jobs(profile: UserProfile, jobs: Sequence[JobPosting]) -> list[JobPosting]:
    """Return distinct eligible candidates; unclear conditions remain eligible."""
    return _screen_candidates(profile, jobs)[0]


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
