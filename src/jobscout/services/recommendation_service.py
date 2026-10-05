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
            warnings.append(f"岗位 {job.job_id} 的地点未知，申请前请确认。")
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
            warnings.append(f"岗位 {job.job_id} 的工作类型无法验证，申请前请确认。")
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
        warnings.append(f"岗位 {job.job_id} 缺少结构化技能要求，技能匹配依据不足。")

    suggestions = [f"补充 {skill} 的学习与实践，并准备可展示的练习或项目。" for skill in missing]
    if relevant:
        suggestions.append(f"整理与 {', '.join(relevant)} 相关的项目或实习证据，说明职责与成果。")
    else:
        suggestions.append("对照岗位职责准备相关项目或实习案例，说明个人贡献与成果。")

    required_degree = _required_degree(job)
    if required_degree:
        if _degree_level(profile.education) >= required_degree:
            score += 10
            suggestions.append("在简历中列明与岗位学历要求对应的教育经历。")
        else:
            suggestions.append(
                "当前教育信息未证明满足岗位学历要求，申请前请核实资格或同等经验条件。"
            )
    if any(re.search(r"\d+\s*(?:years?|年)", text, re.IGNORECASE) for text in job.responsibilities):
        suggestions.append("核对 JD 中的经验年限要求；项目经历不能直接视为等量的全职工作年限。")
    if job.freshness_status == FreshnessStatus.UNKNOWN:
        warnings.append(f"岗位 {job.job_id} 的有效状态为 unknown，申请前请访问来源确认。")
        suggestions.append("访问岗位来源链接，确认岗位仍开放申请。")
    if warnings:
        suggestions.append("核实岗位提示中的未知信息，再决定是否申请。")
    suggestions.append("根据岗位职责调整简历，准备面试示例，并通过来源链接查看完整申请要求。")
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
        raise RecommendationError("recommendation_invalid_session", "推荐需要非空的 session_id。")
    if (
        profile.missing_required_fields
        or profile.conflicts
        or not any(direction.strip() for direction in profile.target_directions)
    ):
        raise RecommendationError(
            "recommendation_profile_not_ready", "画像存在缺失信息或待确认冲突。"
        )
    generated_at = datetime.now(UTC) if now is None else now
    if generated_at.tzinfo is None or generated_at.utcoffset() is None:
        raise RecommendationError("recommendation_invalid_time", "生成时间必须包含时区。")
    generated_at = generated_at.astimezone(UTC)
    result_warnings = list(warnings)
    for field in ("salary_range", "work_mode", "industry"):
        if _confirmed(profile, field) and getattr(profile.preferences, field):
            result_warnings.append(f"Schema v1 无法可靠验证 {field} 偏好，请在来源 JD 中核实。")

    candidates: list[_Candidate] = []
    seen_ids: set[str] = set()
    excluded = 0
    for job in jobs:
        if job.job_id in seen_ids:
            result_warnings.append(
                f"岗位标识 {job.job_id} 重复，已跳过后续记录；请由岗位处理模块合并来源。"
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
    if excluded:
        result_warnings.append(f"已排除 {excluded} 条过期、方向不符或已确认偏好不符的岗位。")
    if not selected:
        result_warnings.append("没有符合当前条件的可推荐岗位。")
    return RecommendationResult(
        session_id=session_id,
        generated_at=generated_at,
        jobs=[candidate.item for candidate in selected],
        warnings=list(dict.fromkeys(result_warnings)),
    )
