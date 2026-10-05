"""Deterministic matching against Schema v1, with no external services."""

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from fractions import Fraction

from jobscout.schemas.errors import WorkflowError
from jobscout.schemas.job import FreshnessStatus, JobPosting
from jobscout.schemas.profile import UserProfile
from jobscout.schemas.recommendation import RecommendationItem, RecommendationResult
from jobscout.services.job_retrieval.local_sources import CITY_CODES

_SKILL_ALIASES = (
    ("javascript", "js"),
    ("typescript", "ts"),
    ("postgresql", "postgres"),
    ("kubernetes", "k8s"),
    ("excel", "microsoft excel"),
    ("power bi", "powerbi"),
    ("machine learning", "机器学习"),
)
_EMPLOYMENT_ALIASES = {
    "internship": ("internship", "intern", "实习"),
    "part-time": ("part-time", "part time", "parttime", "兼职"),
    "full-time": ("full-time", "full time", "fulltime", "全职"),
}
_HONG_KONG_ALIASES = (
    "hong kong",
    "hongkong",
    "hong kong sar",
    "hk",
    "香港",
    "香港特别行政区",
    "香港特別行政區",
)
_DEGREE_ALIASES = {
    1: ("bachelor", "bachelor's", "bachelors", "本科", "学士"),
    2: ("master", "master's", "masters", "硕士"),
    3: ("phd", "ph.d.", "doctorate", "doctoral", "博士"),
}


class RecommendationError(ValueError):
    """A Python exception carrying the shared workflow error contract."""

    def __init__(self, code: str, message: str) -> None:
        self.error = WorkflowError(code=code, message=message, stage="recommend")
        super().__init__(message)


@dataclass(frozen=True)
class _Candidate:
    item: RecommendationItem
    score: Fraction
    warnings: tuple[str, ...]


def _normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def _contains(text: str, phrase: str) -> bool:
    """Match whole Latin tokens (C, C++, C# remain distinct), and CJK phrases."""
    phrase = _normalize(phrase)
    if not phrase:
        return False
    return (
        re.search(r"(?<![a-z0-9_+#])" + re.escape(phrase) + r"(?![a-z0-9_+#])", _normalize(text))
        is not None
    )


def _mentions(text: str, phrase: str) -> bool:
    # Chinese words are not whitespace-delimited; use literal phrase matching there.
    if re.search(r"[\u3400-\u9fff]", phrase):
        return _normalize(phrase) in _normalize(text)
    return _contains(text, phrase)


def _skill_key(skill: str) -> str:
    key = _normalize(skill)
    for aliases in _SKILL_ALIASES:
        if key in aliases:
            return aliases[0]
    return key


def _unique_skills(skills: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for skill in skills:
        key = _skill_key(skill)
        if key and key not in seen:
            result.append(skill.strip())
            seen.add(key)
    return result


def _skill_in_evidence(skill: str, evidence: Sequence[str]) -> bool:
    key = _skill_key(skill)
    aliases = next((group for group in _SKILL_ALIASES if key == group[0]), (key,))
    return any(_mentions(text, alias) for text in evidence for alias in aliases)


def _confirmed(profile: UserProfile, field: str) -> bool:
    return f"preferences.{field}" in profile.confirmed_fields


def _employment_type(text: str) -> str | None:
    for kind, aliases in _EMPLOYMENT_ALIASES.items():
        if any(_mentions(text, alias) for alias in aliases):
            return kind
    return None


def _job_employment_type(job: JobPosting) -> str | None:
    if job.employment_type and job.employment_type.strip():
        return _employment_type(job.employment_type)
    kind = _employment_type(job.title)
    if kind is not None:
        return kind
    # A mention of interns or full-time colleagues in duties is not job metadata.
    for text in job.responsibilities:
        if re.match(r"^(employment type|job type|工作类型|雇佣类型)\s*[:：]", _normalize(text)):
            return _employment_type(text)
    return None


def _location_matches(actual: str, requested: str) -> bool:
    normalized_request = _normalize(requested)
    if normalized_request in _HONG_KONG_ALIASES:
        return any(_mentions(actual, alias) for alias in _HONG_KONG_ALIASES)
    for chinese, (_, _, english) in CITY_CODES.items():
        aliases = (chinese, chinese + "市", english)
        if normalized_request in aliases:
            return any(_mentions(actual, alias) for alias in aliases)
    return _mentions(actual, requested)


def _preference_check(profile: UserProfile, job: JobPosting) -> tuple[bool, list[str]]:
    warnings: list[str] = []
    preferences = profile.preferences
    unrestricted = preferences.location_unrestricted and _confirmed(
        profile, "location_unrestricted"
    )
    if _confirmed(profile, "location") and preferences.location and not unrestricted:
        if not job.location.strip() or _normalize(job.location) == "unknown":
            warnings.append(
                f"The location of job {job.job_id} is unknown. Confirm it before applying."
            )
        elif not _location_matches(job.location, preferences.location):
            return False, []
    employment_unrestricted = preferences.employment_type_unrestricted and _confirmed(
        profile, "employment_type_unrestricted"
    )
    if (
        _confirmed(profile, "employment_type")
        and preferences.employment_type
        and not employment_unrestricted
    ):
        requested = _employment_type(preferences.employment_type)
        actual = _job_employment_type(job)
        if requested is None or actual is None:
            warnings.append(
                f"The employment type of job {job.job_id} could not be verified. Confirm it before applying."
            )
        elif requested != actual:
            return False, []
    return True, warnings


def _direction_matches(profile: UserProfile, job: JobPosting) -> bool:
    directions = {_normalize(value) for value in profile.target_directions if value.strip()}
    return any(
        _normalize(value) in directions for value in [job.target_direction, *job.target_directions]
    )


def eligible_jobs(profile: UserProfile, jobs: Sequence[JobPosting]) -> list[JobPosting]:
    """Return unique eligible vacancies before coverage checks and model analysis.

    Only confirmed hard constraints exclude candidates. Unknown conditions remain
    eligible; normalized company/title/location and source URLs prevent duplicates
    from inflating coverage. Input objects are not changed.
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


def _degree_level(texts: Sequence[str]) -> int:
    return max(
        (
            level
            for level, aliases in _DEGREE_ALIASES.items()
            if any(_mentions(text, alias) for text in texts for alias in aliases)
        ),
        default=0,
    )


def _required_degree(job: JobPosting) -> int:
    requirements = list(job.required_skills)
    requirements.extend(
        text
        for text in job.responsibilities
        if re.search(r"required|requirement|minimum|at least|要求|至少|学历", _normalize(text))
    )
    # For alternatives such as bachelor's or master's, use the lowest stated level.
    return min(
        (
            level
            for level, aliases in _DEGREE_ALIASES.items()
            if any(_mentions(text, alias) for text in requirements for alias in aliases)
        ),
        default=0,
    )


def _evaluate(profile: UserProfile, job: JobPosting, warnings: list[str]) -> _Candidate:
    requirements = _unique_skills(job.required_skills)
    user_skills = {_skill_key(skill) for skill in profile.skills if skill.strip()}
    missing = [skill for skill in requirements if _skill_key(skill) not in user_skills]
    evidence = [*profile.internships, *profile.projects]
    relevant = [skill for skill in requirements if _skill_in_evidence(skill, evidence)]
    score = Fraction(0)
    if requirements:
        score += 70 * Fraction(len(requirements) - len(missing), len(requirements))
        score += 20 * Fraction(len(relevant), len(requirements))
    else:
        warnings.append(
            f"Job {job.job_id} has no structured skill requirements, so there is limited evidence for assessing the skills match."
        )

    suggestions = [
        f"Build your {skill} skills through study or practice, and prepare an exercise or project to demonstrate them."
        for skill in missing
    ]
    if relevant:
        suggestions.append(
            f"Gather project or internship evidence related to {', '.join(relevant)}, and describe your responsibilities and results."
        )
    else:
        suggestions.append(
            "Prepare project or internship examples that relate to the job responsibilities, and describe your contributions and results."
        )

    required_degree = _required_degree(job)
    if required_degree:
        if _degree_level(profile.education) >= required_degree:
            score += 10
            suggestions.append(
                "List the education that meets the job’s education requirements on your resume."
            )
        else:
            suggestions.append(
                "Your current education information does not show that you meet the job’s education requirements. Verify your eligibility or equivalent experience before applying."
            )
    if any(re.search(r"\d+\s*(?:years?|年)", text, re.IGNORECASE) for text in job.responsibilities):
        suggestions.append(
            "Check the experience requirements in the job description. Time spent on projects does not automatically count as equivalent full-time work experience."
        )
    if job.freshness_status == FreshnessStatus.UNKNOWN:
        warnings.append(
            f"The status of job {job.job_id} is unknown. Check the source before applying."
        )
        suggestions.append("Visit the job source to confirm that applications are still open.")
    if warnings:
        suggestions.append(
            "Verify any unknown details in the job listing before deciding whether to apply."
        )
    suggestions.append(
        "Tailor your resume to the job responsibilities, prepare interview examples, and check the source link for the full application requirements."
    )
    return _Candidate(
        item=RecommendationItem(
            job=job.model_copy(deep=True),
            missing_skills=missing,
            preparation_suggestions=suggestions,
        ),
        score=score,
        warnings=tuple(warnings),
    )


def recommend_jobs(
    profile: UserProfile,
    jobs: Sequence[JobPosting],
    *,
    session_id: str,
    warnings: Sequence[str] = (),
    now: datetime | None = None,
) -> RecommendationResult:
    """Return at most five jobs across all directions, without changing inputs.

    Known expired, off-direction and confirmed preference mismatches are excluded.
    Active jobs precede unknown jobs, then skill/background score and stable IDs
    break ties. Scores stay internal. Upstream warnings are preserved in the result.
    """
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
    generated_at = datetime.now(UTC) if now is None else now
    if generated_at.tzinfo is None or generated_at.utcoffset() is None:
        raise RecommendationError(
            "recommendation_invalid_time", "The generation time must include a time zone."
        )
    generated_at = generated_at.astimezone(UTC)
    result_warnings = list(warnings)
    for field in ("salary_range", "work_mode", "industry"):
        if _confirmed(profile, field) and getattr(profile.preferences, field):
            result_warnings.append(
                f"Schema v1 cannot reliably verify the {field} preference. Check the original job description."
            )

    candidates: list[_Candidate] = []
    seen_ids: set[str] = set()
    excluded = 0
    for job in jobs:
        if job.job_id in seen_ids:
            result_warnings.append(
                f"Duplicate job ID {job.job_id}; later records were skipped. Merge their sources in the job processing module."
            )
            continue
        seen_ids.add(job.job_id)
        if job.freshness_status == FreshnessStatus.EXPIRED or not _direction_matches(profile, job):
            excluded += 1
            continue
        eligible, job_warnings = _preference_check(profile, job)
        if not eligible:
            excluded += 1
            continue
        candidates.append(_evaluate(profile, job, job_warnings))
    candidates.sort(
        key=lambda candidate: (
            candidate.item.job.freshness_status != FreshnessStatus.ACTIVE,
            -candidate.score,
            candidate.item.job.job_id,
            candidate.item.job.source_url,
        )
    )
    selected = candidates[:5]
    for candidate in selected:
        result_warnings.extend(candidate.warnings)
    if excluded == 1:
        result_warnings.append(
            "Excluded 1 job because it was expired, outside your selected directions, or conflicted with confirmed preferences."
        )
    elif excluded > 1:
        result_warnings.append(
            f"Excluded {excluded} jobs because they were expired, outside your selected directions, or conflicted with confirmed preferences."
        )
    if not selected:
        result_warnings.append("No recommended jobs match the current criteria.")
    return RecommendationResult(
        session_id=session_id,
        generated_at=generated_at,
        jobs=[candidate.item for candidate in selected],
        warnings=list(dict.fromkeys(result_warnings)),
    )
