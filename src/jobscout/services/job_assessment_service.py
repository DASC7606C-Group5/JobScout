"""Read job details, check model claims against source quotes, and order jobs for each session."""

import asyncio
import hashlib
import json
import logging
import math
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, ValidationError

from jobscout.schemas.conversation import MatchingReason, SourceQuoteReference
from jobscout.schemas.job import FreshnessStatus, JobPosting, SourceDocument
from jobscout.schemas.job_status import ExclusionReason, ReviewIssue
from jobscout.schemas.matching import DimensionAssessment, MatchDimension
from jobscout.schemas.profile import EmploymentType, UserProfile
from jobscout.schemas.recommendation import (
    RecommendationFit,
    RecommendationItem,
    RecommendationResult,
)
from jobscout.services.job_processing_service import select_candidates
from jobscout.services.llm_service import LLMProvider, ModelRouter, ModelServiceError
from jobscout.services.location_service import get_location_catalog, within
from jobscout.services.matching_score import build_match_score
from jobscout.services.notice_service import finalize_recommendation, make_notice
from jobscout.services.prompts import JOB_ANALYSIS_PROMPT, MATCHING_PROMPT, SUMMARY_MATCHING_PROMPT
from jobscout.services.ranking import recommendation_key
from jobscout.services.recommendation_service import (
    RecommendationError,
    _normalize,
    _preference_check,
    _unique_skills,
    eligibility_exclusions,
    validate_recommendation_profile,
)
from jobscout.services.recommendation_service import (
    eligible_jobs as eligible_jobs,
)
from jobscout.services.review_response import ReviewResponse, SummaryReviewResponse, profile_quotes

MAX_CANDIDATES = 30
BATCH_SIZE = 3
CONCURRENCY = 2
_SCHEMA_VERSION = "job-assessment-v11"
_LOGGER = logging.getLogger(__name__)


async def _gather_results[ResultT](*operations: Awaitable[ResultT]) -> list[ResultT]:
    """Drain sibling operations before a failed assessment releases its session lock."""
    tasks = [asyncio.ensure_future(operation) for operation in operations]
    try:
        return list(await asyncio.gather(*tasks))
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceQuote(_StrictModel):
    document_id: str = Field(min_length=1)
    excerpt: str = Field(min_length=1)


_PROFILE_FIELDS = ("education", "skills", "internships", "projects")


def _profile_facts(profile: UserProfile) -> dict[str, dict[str, str]]:
    return {
        f"{field}:{index}": {"field": field, "text": text}
        for field in _PROFILE_FIELDS
        for index, text in enumerate(getattr(profile, field))
    }


class Requirement(_StrictModel):
    requirement_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    skill_terms: list[str] = Field(default_factory=list, max_length=8)
    category: Literal[
        "skill", "responsibility", "experience", "seniority", "education", "preference", "other"
    ] = "skill"
    source_quotes: list[SourceQuote] = Field(min_length=1)
    qualification_options: list[str] = Field(default_factory=list, max_length=10)
    minimum_experience_months: int | None = Field(default=None, ge=0, le=1200, strict=True)


class JobLocation(_StrictModel):
    query: str
    source_quotes: list[SourceQuote] = Field(min_length=1)


class JobEmploymentType(_StrictModel):
    value: EmploymentType
    source_quotes: list[SourceQuote] = Field(min_length=1)


class ConditionAssessment(_StrictModel):
    job_id: str
    locations: list[JobLocation] = Field(default_factory=list)
    employment: list[JobEmploymentType] = Field(default_factory=list)
    direction: Literal["match", "mismatch", "unknown"] = "unknown"
    direction_quotes: list[SourceQuote] = Field(default_factory=list)


class JobAnalysis(ConditionAssessment):
    job_id: str
    work_summary: str = Field(default="", max_length=800)
    requirements: list[Requirement] = Field(default_factory=list, max_length=30)
    incomplete: bool = False


class JDAnalysisBatch(_StrictModel):
    jobs: list[JobAnalysis] = Field(max_length=BATCH_SIZE)


class RequirementMatch(_StrictModel):
    requirement_id: str
    level: Literal["strong", "partial", "related_experience", "not_documented"]
    profile_source_quotes: list[SourceQuote] = Field(default_factory=list)
    experience_source_quotes: list[SourceQuote] = Field(default_factory=list)
    profile_fact_ids: list[str] = Field(default_factory=list)
    experience_fact_ids: list[str] = Field(default_factory=list)
    qualifications: list[str] = Field(default_factory=list)
    qualification_relation: Literal["meets", "partial", "does_not_meet", "unknown"] | None = None
    experience_months: int | None = Field(default=None, ge=0, le=1200, strict=True)
    explanation: str = Field(default="", max_length=500)


class PreparationSuggestion(_StrictModel):
    requirement_id: str
    suggestion: str = Field(min_length=1, max_length=500)


class JobMatch(_StrictModel):
    _invalid_claims: bool = PrivateAttr(default=False)

    job_id: str
    dimensions: list[DimensionAssessment] = Field(default_factory=list, max_length=6)
    recommendation_fit: RecommendationFit = "unknown"
    recommendation_reason: str = Field(default="", max_length=600)
    matches: list[RequirementMatch] = Field(default_factory=list, max_length=30)
    preparation_suggestions: list[PreparationSuggestion] = Field(
        default_factory=list, max_length=10
    )
    incomplete: bool = False


class _JDCacheSnapshot(_StrictModel):
    version: str
    session_id: str
    entries: dict[str, JobAnalysis]
    dimension_scores: dict[str, MatchDimension] = Field(default_factory=dict)


class _InvalidAssessment(ValueError):
    pass


class AssessmentDiagnostic(_StrictModel):
    code: Literal[
        "invalid_analysis", "model_failure", "insufficient_job_information", "condition_mismatch"
    ]
    stage: str
    detail: str
    retryable: bool
    public_issue: ReviewIssue | None = None
    exclusion_reasons: list[ExclusionReason] = Field(default_factory=list)

    def review_issue(self) -> ReviewIssue:
        if self.public_issue is not None:
            return self.public_issue
        stage: Literal["jd_analysis", "matching"] | None = (
            "jd_analysis"
            if self.stage == "jd_analysis"
            else "matching"
            if self.stage == "matching"
            else None
        )
        if self.code == "model_failure":
            if self.detail == "model_timeout":
                return ReviewIssue(code="timeout", stage=stage)
            if self.detail == "model_output":
                return ReviewIssue(code="invalid_output", stage=stage)
            if self.detail in {
                "model_auth",
                "model_configuration",
                "model_transport",
                "model_http",
            }:
                return ReviewIssue(code="service_unavailable", stage=stage)
        return ReviewIssue(code="failed", stage=stage)


@dataclass(frozen=True)
class _Ranked:
    item: RecommendationItem
    diagnostics: tuple[str, ...]


def _documents(job: JobPosting) -> dict[str, SourceDocument]:
    documents: dict[str, SourceDocument] = {}
    for document in job.source_documents:
        if not document.document_id.strip():
            raise _InvalidAssessment("empty document ID")
        if document.document_id in documents and documents[document.document_id] != document:
            raise _InvalidAssessment("ambiguous document ID")
        if document.text.strip():
            documents[document.document_id] = document
    if not documents and job.description.strip():
        document = SourceDocument(
            document_id=f"job:{job.job_id}:description",
            source=job.source,
            source_url=job.source_url,
            text=job.description,
            fetched_at=job.fetched_at,
            is_excerpt=job.description_is_excerpt,
        )
        documents[document.document_id] = document
    metadata = SourceDocument(
        document_id=f"job:{job.job_id}:metadata",
        source=job.source,
        source_url=job.source_url,
        fetched_at=job.fetched_at,
        text="\n".join([job.title, job.location, job.employment_type or ""]),
    )
    documents[metadata.document_id] = metadata
    return documents


def _references(
    quotes: Sequence[SourceQuote], documents: dict[str, str], urls: dict[str, str] | None = None
) -> list[SourceQuoteReference]:
    references: list[SourceQuoteReference] = []
    for quote in quotes:
        if not quote.excerpt.strip() or quote.excerpt not in documents.get(quote.document_id, ""):
            raise _InvalidAssessment("quote absent from referenced document")
        references.append(
            SourceQuoteReference(
                document_id=quote.document_id,
                excerpt=quote.excerpt,
                source_url=urls.get(quote.document_id) if urls else None,
            )
        )
    return references


def _validate_analysis(analysis: JobAnalysis, documents: dict[str, SourceDocument]) -> None:
    ids: set[str] = set()
    texts: set[str] = set()
    retained: list[Requirement] = []
    incomplete = analysis.incomplete
    source_texts = {key: value.text for key, value in documents.items()}
    for field in ("locations", "employment"):
        retained_conditions = []
        for condition in getattr(analysis, field):
            try:
                _references(condition.source_quotes, source_texts)
            except _InvalidAssessment:
                continue
            retained_conditions.append(condition)
        setattr(analysis, field, retained_conditions)
    try:
        _references(analysis.direction_quotes, source_texts)
    except _InvalidAssessment:
        analysis.direction_quotes = []
    if not analysis.direction_quotes:
        analysis.direction = "unknown"
    for requirement in analysis.requirements:
        key = _normalize(requirement.text)
        if (
            not key
            or not requirement.requirement_id.strip()
            or requirement.requirement_id in ids
            or key in texts
        ):
            incomplete = True
            continue
        ids.add(requirement.requirement_id)
        texts.add(key)
        quotes = [
            quote
            for quote in requirement.source_quotes
            if quote.excerpt.strip() and quote.excerpt in source_texts.get(quote.document_id, "")
        ]
        incomplete |= len(quotes) != len(requirement.source_quotes)
        if not quotes:
            incomplete = True
            continue
        retained.append(
            requirement.model_copy(
                update={
                    "source_quotes": quotes,
                    "skill_terms": requirement.skill_terms
                    if requirement.category == "skill"
                    else [],
                    "qualification_options": [
                        value for value in requirement.qualification_options if value.strip()
                    ]
                    if requirement.category == "education"
                    else [],
                }
            )
        )
    analysis.requirements = retained
    analysis.incomplete = incomplete


def _requirement_terms(requirement: Requirement, profile: UserProfile | None = None) -> list[str]:
    if requirement.category != "skill":
        return []
    return _unique_skills(requirement.skill_terms) or [requirement.text]


def _requirement_label(requirement: Requirement) -> str:
    terms = _requirement_terms(requirement)
    label = (
        " / ".join(terms[:2])
        if terms and requirement.minimum_experience_months is None
        else requirement.text
    )
    if len(terms) > 2:
        label += f" + {len(terms) - 2} more"
    return label if len(label) <= 100 else label[:97].rstrip() + "..."


def _validate_matches(
    match: JobMatch,
    analysis: JobAnalysis,
    profile: UserProfile,
    documents: dict[str, str],
) -> None:
    expected = {item.requirement_id: item for item in analysis.requirements}
    if len(match.matches) != len(expected) or {m.requirement_id for m in match.matches} != set(
        expected
    ):
        raise _InvalidAssessment("missing, duplicate or unknown requirement ID")
    if any(item.requirement_id not in expected for item in match.preparation_suggestions):
        raise _InvalidAssessment("preparation advice references unknown requirement")
    if any(not item.suggestion.strip() for item in match.preparation_suggestions):
        raise _InvalidAssessment("empty preparation advice")
    facts = _profile_facts(profile)
    for item in match.matches:
        _references(item.profile_source_quotes, documents)
        _references(item.experience_source_quotes, documents)
        identifiers = [*item.profile_fact_ids, *item.experience_fact_ids]
        if any(identity not in facts for identity in identifiers):
            raise _InvalidAssessment("unknown current profile fact")
        if item.level != "not_documented" and not item.profile_source_quotes:
            raise _InvalidAssessment("positive match without applicant source quotes")
        if item.level == "not_documented" and (
            item.profile_source_quotes
            or item.experience_source_quotes
            or identifiers
            or item.qualifications
            or item.qualification_relation is not None
            or item.experience_months is not None
        ):
            raise _InvalidAssessment("undocumented match contains supporting quotes")
        requirement = expected[item.requirement_id]
        if requirement.category == "education" and item.experience_source_quotes:
            raise _InvalidAssessment("experience cannot prove an education requirement")
        if bool(item.experience_source_quotes) != bool(item.experience_fact_ids) or any(
            facts[identity]["field"] not in {"projects", "internships"}
            for identity in item.experience_fact_ids
        ):
            raise _InvalidAssessment(
                "experience quote does not match supplied projects or internships"
            )
        if requirement.category == "education" and item.level != "not_documented":
            if any(facts[identity]["field"] != "education" for identity in item.profile_fact_ids):
                raise _InvalidAssessment("education quote does not match supplied qualifications")
            if not item.qualifications or any(not value.strip() for value in item.qualifications):
                raise _InvalidAssessment("education match requires cited qualifications")
            if item.level == "strong" and item.qualification_relation != "meets":
                raise _InvalidAssessment("qualification requirement not met")
            if item.qualification_relation is None:
                raise _InvalidAssessment("qualification relationship is missing")
        if (
            item.qualifications or item.qualification_relation is not None
        ) and requirement.category != "education":
            raise _InvalidAssessment("non-education match has a qualification comparison")
        if item.experience_months is not None and (
            not item.experience_fact_ids
            or any(
                facts[identity]["field"] != "internships" for identity in item.experience_fact_ids
            )
        ):
            raise _InvalidAssessment("work duration requires work-history facts and source quotes")
        if (
            item.level == "strong"
            and requirement.minimum_experience_months is not None
            and (
                item.experience_months is None
                or item.experience_months < requirement.minimum_experience_months
            )
        ):
            raise _InvalidAssessment("employment duration not established by supplied work history")


def _validate_match(
    match: JobMatch,
    analysis: JobAnalysis,
    profile: UserProfile,
    documents: dict[str, str],
) -> None:
    """Keep supported conclusions; one damaged conclusion does not discard the vacancy."""
    retained: list[RequirementMatch] = []
    incomplete = match.incomplete
    expected = {row.requirement_id: row for row in analysis.requirements}
    for requirement_id, requirement in expected.items():
        rows = [row for row in match.matches if row.requirement_id == requirement_id]
        if len(rows) != 1:
            incomplete = True
            continue
        row = rows[0].model_copy(deep=True)
        for field in ("profile_source_quotes", "experience_source_quotes"):
            quotes = getattr(row, field)
            valid = [
                quote
                for quote in quotes
                if quote.excerpt.strip() and quote.excerpt in documents.get(quote.document_id, "")
            ]
            incomplete |= len(valid) != len(quotes)
            setattr(row, field, valid)
        try:
            _validate_matches(
                JobMatch(job_id=match.job_id, matches=[row]),
                JobAnalysis(job_id=analysis.job_id, requirements=[requirement]),
                profile,
                documents,
            )
        except _InvalidAssessment:
            incomplete = True
        else:
            retained.append(row)
    incomplete |= any(row.requirement_id not in expected for row in match.matches)
    match.matches = retained
    match.incomplete = incomplete
    valid_ids = {row.requirement_id for row in retained}
    match.preparation_suggestions = [
        suggestion
        for suggestion in match.preparation_suggestions
        if suggestion.requirement_id in valid_ids and suggestion.suggestion.strip()
    ][:2]


def _review_match(
    review: SummaryReviewResponse,
    analysis: JobAnalysis,
    profile: UserProfile,
    documents: dict[str, str],
) -> JobMatch:
    quotes = profile_quotes(documents)
    facts = _profile_facts(profile)
    requirements = {r.requirement_id: r for r in analysis.requirements}
    matches = []
    invalid_claims = False
    for row in review.matches:
        if row.level == "not_documented":
            matches.append(
                RequirementMatch(
                    requirement_id=row.requirement_id,
                    level=row.level,
                    explanation=row.explanation,
                )
            )
            continue
        invalid_claims |= any(key not in quotes for key in row.profile_quote_ids)
        references = [SourceQuote(**quotes[key]) for key in row.profile_quote_ids if key in quotes]
        experience_ids = [
            key
            for key in row.profile_fact_ids
            if facts.get(key, {}).get("field")
            in (
                {"internships"}
                if row.experience_months is not None
                else {"internships", "projects"}
            )
        ]
        matches.append(
            RequirementMatch(
                requirement_id=row.requirement_id,
                level=row.level,
                profile_fact_ids=row.profile_fact_ids,
                profile_source_quotes=references,
                experience_fact_ids=experience_ids,
                experience_source_quotes=references if experience_ids else [],
                qualifications=[
                    facts[key]["text"]
                    for key in row.profile_fact_ids
                    if facts.get(key, {}).get("field") == "education"
                    and row.requirement_id in requirements
                    and requirements[row.requirement_id].category == "education"
                ],
                qualification_relation=row.qualification_relation
                if row.requirement_id in requirements
                and requirements[row.requirement_id].category == "education"
                else None,
                experience_months=row.experience_months,
                explanation=row.explanation,
            )
        )
    match = JobMatch(
        job_id=review.job_id,
        matches=matches,
        recommendation_fit=review.recommendation_fit,
        recommendation_reason=review.recommendation_reason,
        incomplete=review.incomplete or invalid_claims,
    )
    original = match.model_copy(deep=True)
    _validate_match(match, analysis, profile, documents)
    match._invalid_claims = invalid_claims or original != match
    for dimension in review.dimensions if isinstance(review, ReviewResponse) else []:
        comparisons = [r for r in match.matches if r.requirement_id in dimension.requirement_ids]
        job_refs = [
            q
            for key in dimension.requirement_ids
            if key in requirements
            for q in requirements[key].source_quotes
        ]
        if dimension.id == "preferences":
            job_refs += analysis.direction_quotes
            job_refs += [q for location in analysis.locations for q in location.source_quotes]
            job_refs += [q for kind in analysis.employment for q in kind.source_quotes]
        match.dimensions.append(
            DimensionAssessment(
                **dimension.model_dump(),
                job_source_quotes=[SourceQuoteReference(**q.model_dump()) for q in job_refs][:10],
                profile_fact_ids=list(
                    dict.fromkeys(key for r in comparisons for key in r.profile_fact_ids)
                ),
                profile_source_quotes=[
                    SourceQuoteReference(**q.model_dump())
                    for r in comparisons
                    for q in r.profile_source_quotes
                ][:10],
            )
        )
    valid_ids = [r.requirement_id for r in match.matches]
    if valid_ids and isinstance(review, ReviewResponse):
        match.preparation_suggestions = [
            PreparationSuggestion(requirement_id=valid_ids[0], suggestion=text)
            for text in review.preparation_suggestions
            if text.strip()
        ]
    return match


def _match_explanation(
    requirement: Requirement, match: RequirementMatch, profile: UserProfile
) -> str:
    if match.explanation.strip():
        return match.explanation.strip()
    if match.level == "not_documented":
        return ""
    candidates = match.experience_source_quotes or match.profile_source_quotes
    if not candidates:
        return ""
    quote = candidates[0]
    excerpt = quote.excerpt.strip()
    if len(excerpt) > 220:
        excerpt = excerpt[:217].rstrip() + "..."
    labels = {
        "strong": "Matches",
        "partial": "Partial match for",
        "related_experience": "Related experience for",
    }
    explanation = f"{labels[match.level]} {_requirement_label(requirement)}: “{excerpt}”."
    return explanation


def _render(
    profile: UserProfile,
    job: JobPosting,
    analysis: JobAnalysis,
    match: JobMatch,
    documents: dict[str, SourceDocument],
    profile_documents: dict[str, str],
    diagnostics: list[str],
    analysis_status: Literal["complete", "partial", "unavailable"] = "complete",
    dimension_cache: dict[str, MatchDimension] | None = None,
) -> _Ranked:
    reasons: list[MatchingReason] = []
    suggestions: list[str] = []
    matches = {item.requirement_id: item for item in match.matches}
    for requirement in analysis.requirements:
        if requirement.requirement_id not in matches:
            continue
        item = matches[requirement.requirement_id]
        job_refs = _references(
            requirement.source_quotes,
            {key: value.text for key, value in documents.items()},
            {key: value.source_url for key, value in documents.items()},
        )
        user_refs = _references(item.profile_source_quotes, profile_documents)
        for reference in _references(item.experience_source_quotes, profile_documents):
            if reference not in user_refs:
                user_refs.append(reference)
        label = _requirement_label(requirement)
        explanation = _match_explanation(requirement, item, profile)
        reasons.append(
            MatchingReason(
                requirement=label,
                level=item.level,
                explanation=explanation,
                job_source_quotes=job_refs,
                profile_source_quotes=user_refs,
            )
        )
    full_description = job.has_full_description()
    score = (
        build_match_score(
            match.dimensions,
            analysis,
            profile,
            {key: value.text for key, value in documents.items()},
            profile_documents,
            incomplete=match.incomplete,
            dimension_cache=dimension_cache,
        )
        if full_description
        else None
    )
    has_comparison = bool(reasons) or (
        score is not None
        and any(
            dimension.status == "assessed" and dimension.id != "preferences"
            for dimension in score.dimensions
        )
    )
    has_summary_advice = (
        not full_description and bool(match.recommendation_reason.strip()) and not match.incomplete
    )
    if not has_comparison and not has_summary_advice:
        analysis_status = "unavailable"
        diagnostics.append(f"Job {job.job_id} has no validated matching conclusions.")
    elif not full_description:
        analysis_status = "partial"
    diagnostics.extend(_preference_check(profile, job)[1])
    if job.freshness_status == FreshnessStatus.UNKNOWN:
        diagnostics.append(
            f"The status of job {job.job_id} is unknown. Check the source before applying."
        )
    if not documents:
        diagnostics.append(
            f"Job {job.job_id} has no original job description, so source excerpts are unavailable."
        )
    elif any(document.is_excerpt for document in documents.values()):
        diagnostics.append(
            f"The source for job {job.job_id} contains only a summary, so requirements may be incomplete. See the original listing."
        )
    for suggestion in match.preparation_suggestions:
        text = suggestion.suggestion.strip()
        if text not in suggestions:
            suggestions.append(text)
        if len(suggestions) == 2:
            break
    return _Ranked(
        item=RecommendationItem(
            job=job.model_copy(
                update={
                    "source_documents": [
                        document.model_copy(deep=True) for document in documents.values()
                    ]
                },
                deep=True,
            ),
            preparation_suggestions=suggestions,
            matching_reasons=reasons,
            analysis_status=analysis_status,
            match_score=score,
            recommendation_fit=match.recommendation_fit
            if analysis_status != "unavailable"
            else "unknown",
            recommendation_reason=match.recommendation_reason.strip()
            if analysis_status != "unavailable"
            else "",
        ),
        diagnostics=tuple(dict.fromkeys(diagnostics)),
    )


class JobAssessmentService:
    """Create one instance per session; cache JD extraction, never user matching."""

    def __init__(
        self, provider: LLMProvider, *, decision_provider: LLMProvider | None = None
    ) -> None:
        self.provider = provider
        if decision_provider is not None:
            self.decision_provider = decision_provider
        elif isinstance(provider, ModelRouter):
            self.decision_provider = provider.decision
        else:
            self.decision_provider = provider
        self.catalog = getattr(provider, "location_catalog", None) or get_location_catalog()
        self.cache: dict[str, JobAnalysis] = {}
        self.dimension_scores: dict[str, MatchDimension] = {}
        self.diagnostics: dict[str, AssessmentDiagnostic] = {}
        self._analyzed_ids: set[str] = set()
        self._session_id: str | None = None
        self._search_id: str | None = None
        self._closed = False
        self._lock = asyncio.Lock()
        self._matching_slots = asyncio.Semaphore(CONCURRENCY)

    @property
    def analyzed_count(self) -> int:
        """Unique candidates assessed in the current confirmed search, across rounds."""
        return len(self._analyzed_ids)

    def _ensure_open(self) -> None:
        if self._closed:
            raise RecommendationError(
                "recommendation_invalid_session", "The job assessment session has been cleared."
            )

    async def begin_search(self, search_id: str) -> None:
        """Reset only the candidate budget for a newly confirmed search.

        Reusing the same stable confirmation ID is a no-op, including on graph
        resume. JD cache survives new searches; matching is never cached here.
        """
        if not search_id.strip():
            raise RecommendationError(
                "recommendation_invalid_search", "A non-empty search_id is required for a search."
            )
        async with self._lock:
            self._ensure_open()
            if self._search_id != search_id:
                self._search_id = search_id
                self._analyzed_ids.clear()
                self.diagnostics.clear()

    async def cleanup_session(self, session_id: str) -> None:
        """Clear session analyses and permanently reject reuse of this instance.

        The session manager should cancel and await its operation first, then
        remove the service from its registry. No process-global cache exists here.
        """
        if not session_id.strip() or (
            self._session_id is not None and self._session_id != session_id
        ):
            raise RecommendationError(
                "recommendation_invalid_session", "The session ID does not match."
            )
        self._closed = True
        async with self._lock:
            self.cache.clear()
            self.dimension_scores.clear()
            self.diagnostics.clear()
            self._analyzed_ids.clear()
            self._search_id = None

    def export_cache(self) -> dict[str, object]:
        """Export detached JSON-safe JD analyses for this session's checkpoint only."""
        self._ensure_open()
        if self._session_id is None or self._lock.locked():
            raise RecommendationError(
                "recommendation_invalid_cache",
                "Only session caches with completed evaluations can be exported.",
            )
        return _JDCacheSnapshot(
            version=_SCHEMA_VERSION,
            session_id=self._session_id,
            entries=self.cache,
            dimension_scores=self.dimension_scores,
        ).model_dump(mode="json")

    def import_cache(self, snapshot: object, session_id: str) -> None:
        """Restore a server-owned checkpoint; never import a client-provided payload.

        Candidate budgets and user matches are deliberately absent. Cache hits are
        revalidated against the current source documents before they are used.
        """
        self._ensure_open()
        if self._lock.locked() or not session_id.strip():
            raise RecommendationError(
                "recommendation_invalid_cache", "The session cache could not be imported."
            )
        try:
            value = _JDCacheSnapshot.model_validate(snapshot)
        except ValidationError:
            raise RecommendationError(
                "recommendation_invalid_cache", "The session cache format is invalid."
            ) from None
        if value.session_id != session_id or (
            self._session_id is not None and self._session_id != session_id
        ):
            raise RecommendationError(
                "recommendation_invalid_session", "The session ID does not match."
            )
        if value.version != _SCHEMA_VERSION or any(
            len(key) != 64 or any(character not in "0123456789abcdef" for character in key)
            for key in value.entries
        ):
            raise RecommendationError(
                "recommendation_invalid_cache", "The session cache version or key is invalid."
            )
        self._session_id = session_id
        self.cache.update({key: item.model_copy(deep=True) for key, item in value.entries.items()})
        self.dimension_scores.update(
            {
                key: item.model_copy(deep=True)
                for key, item in value.dimension_scores.items()
                if key == item.input_hash
            }
        )

    def _cache_key(
        self, job: JobPosting, documents: dict[str, SourceDocument], directions: list[str]
    ) -> str:
        payload = {
            "schema_version": _SCHEMA_VERSION,
            "instruction": JOB_ANALYSIS_PROMPT,
            "directions": sorted(set(directions)),
            "schema": JDAnalysisBatch.model_json_schema(),
            "model": getattr(
                self.provider,
                "cache_identity",
                str(getattr(self.provider, "model", type(self.provider).__qualname__)),
            ),
            "documents": [
                {"document_id": key, "text": value.text, "is_excerpt": value.is_excerpt}
                for key, value in sorted(documents.items())
            ],
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    async def _request[ResultT: BaseModel](
        self, schema: type[ResultT], payload: dict[str, object], deadline: float | None
    ) -> ResultT:
        self._ensure_open()
        instruction = (
            JOB_ANALYSIS_PROMPT
            if schema is JDAnalysisBatch
            else SUMMARY_MATCHING_PROMPT
            if schema is SummaryReviewResponse
            else MATCHING_PROMPT
        )
        provider = self.provider if schema is JDAnalysisBatch else self.decision_provider
        async with asyncio.timeout_at(deadline):
            response = await provider.structured(
                schema,
                [
                    {"role": "system", "content": instruction},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                deadline=deadline,
            )
            return schema.model_validate(response)

    async def _validated_rows[
        RowT: (JobAnalysis, JobMatch),
        BatchT: BaseModel,
    ](
        self,
        schema: type[BatchT],
        payload: dict[str, object],
        job_payloads: list[dict[str, object]],
        validate: Callable[[RowT], None],
        rows: Callable[[BatchT], list[RowT]],
        deadline: float | None,
    ) -> dict[str, RowT]:
        accepted: dict[str, RowT] = {}
        # The provider owns the sole invalid-output repair. A second structured()
        # call here would silently renew that budget after a syntax/schema repair.
        try:
            response = await self._request(schema, {**payload, "jobs": job_payloads}, deadline)
            entries = rows(response)
        except (ModelServiceError, ValidationError, TimeoutError, ValueError) as error:
            for job in job_payloads:
                self.diagnostics[str(job["job_id"])] = AssessmentDiagnostic(
                    code="model_failure",
                    stage=str(payload.get("task")),
                    detail="model_timeout"
                    if isinstance(error, TimeoutError)
                    else getattr(error, "code", "model_output"),
                    retryable=True,
                )
            _LOGGER.warning(
                "analysis_request_failed task=%s error=%s",
                payload.get("task"),
                getattr(error, "code", type(error).__name__),
            )
            return accepted
        expected = {item["job_id"] for item in job_payloads}
        for job_id in expected:
            found = [entry for entry in entries if entry.job_id == job_id]
            try:
                if len(found) != 1:
                    raise _InvalidAssessment("missing or duplicated job ID")
                original = found[0].model_copy(deep=True)
                validate(found[0])
                accepted[found[0].job_id] = found[0]
                if getattr(found[0], "incomplete", False):
                    self.diagnostics[str(job_id)] = AssessmentDiagnostic(
                        code="invalid_analysis",
                        stage=str(payload.get("task")),
                        detail="The supplied documents do not support some conclusions; correct only those conclusions.",
                        retryable=True,
                        public_issue=ReviewIssue(
                            code="unverifiable_claims"
                            if original != found[0] or getattr(found[0], "_invalid_claims", False)
                            else "incomplete_review",
                            stage="jd_analysis" if schema is JDAnalysisBatch else "matching",
                        ),
                    )
            except _InvalidAssessment as error:
                self.diagnostics[str(job_id)] = AssessmentDiagnostic(
                    code="invalid_analysis",
                    stage=str(payload.get("task")),
                    detail=str(error),
                    retryable=True,
                    public_issue=ReviewIssue(
                        code="invalid_output",
                        stage="jd_analysis" if schema is JDAnalysisBatch else "matching",
                    ),
                )
        return accepted

    async def _condition_status(
        self, profile: UserProfile, row: ConditionAssessment, *, deadline: float | None
    ) -> tuple[list[ExclusionReason], list[str]]:
        conflicts: list[ExclusionReason] = []
        if row.direction == "mismatch":
            conflicts.append("role")
        unknown = ["target_direction"] if row.direction == "unknown" else []
        actual_locations = []
        unresolved = False
        for location in row.locations:
            candidates = await self.catalog.lookup(location.query, deadline=deadline)
            if len(candidates) != 1:
                unresolved = True
            else:
                actual_locations.append(candidates[0])
        condition = profile.preferences.locations
        if condition.excluded and (not actual_locations or unresolved):
            unknown.append("location")
        if any(
            within(actual, excluded)
            for actual in actual_locations
            for excluded in condition.excluded
        ):
            conflicts.append("location")
        if any(
            within(excluded, actual)
            for actual in actual_locations
            for excluded in condition.excluded
        ):
            unknown.append("location")
        if not condition.unrestricted:
            if not actual_locations or not condition.included:
                unknown.append("location")
            elif not any(
                within(actual, wanted)
                for actual in actual_locations
                for wanted in condition.included
            ):
                if unresolved or any(
                    within(wanted, actual)
                    for actual in actual_locations
                    for wanted in condition.included
                ):
                    unknown.append("location")
                else:
                    conflicts.append("location")
        employment = profile.preferences.employment
        kinds = {item.value for item in row.employment}
        if kinds & set(employment.excluded):
            conflicts.append("employment_type")
        if employment.excluded and not kinds:
            unknown.append("employment_type")
        if not employment.unrestricted:
            if not kinds or not employment.included:
                unknown.append("employment_type")
            elif not kinds & set(employment.included):
                conflicts.append("employment_type")
        return list(dict.fromkeys(conflicts)), list(dict.fromkeys(unknown))

    async def _batch(
        self,
        profile: UserProfile,
        jobs: list[JobPosting],
        profile_documents: dict[str, str],
        deadline: float | None,
        repair_feedback: dict[str, str] | None = None,
    ) -> list[_Ranked]:
        documents: dict[str, dict[str, SourceDocument]] = {}
        analyses: dict[str, JobAnalysis] = {}
        for job in jobs:
            try:
                documents[job.job_id] = _documents(job)
            except _InvalidAssessment:
                self.diagnostics[job.job_id] = AssessmentDiagnostic(
                    code="invalid_analysis",
                    stage="jd_analysis",
                    detail="Source document identifiers are invalid.",
                    retryable=False,
                    public_issue=ReviewIssue(code="unverifiable_claims", stage="jd_analysis"),
                )
                continue
            key = self._cache_key(job, documents[job.job_id], profile.target_directions)
            feedback = (repair_feedback or {}).get(job.job_id, "")
            if key in self.cache and (not feedback or feedback.startswith("matching:")):
                try:
                    _validate_analysis(self.cache[key], documents[job.job_id])
                except _InvalidAssessment:
                    self.cache.pop(key, None)
                else:
                    analyses[job.job_id] = self.cache[key].model_copy(
                        update={"job_id": job.job_id}, deep=True
                    )
        valid_jobs = [job for job in jobs if job.job_id in documents]
        uncached = [job for job in valid_jobs if job.job_id not in analyses]
        job_payloads: list[dict[str, object]] = [
            {
                "job_id": job.job_id,
                "documents": [
                    document.model_dump(mode="json") for document in documents[job.job_id].values()
                ],
            }
            for job in valid_jobs
        ]
        if uncached:
            responses = await self._validated_rows(
                JDAnalysisBatch,
                {
                    "task": "jd_analysis",
                    "target_directions": profile.target_directions,
                    "repair_feedback": repair_feedback or {},
                },
                [payload for payload in job_payloads if payload["job_id"] not in analyses],
                lambda entry: _validate_analysis(entry, documents[entry.job_id]),
                lambda batch: batch.jobs,
                deadline,
            )
            for job in uncached:
                if job.job_id in responses:
                    analyses[job.job_id] = responses[job.job_id]
                    self.cache[
                        self._cache_key(job, documents[job.job_id], profile.target_directions)
                    ] = responses[job.job_id].model_copy(deep=True)
        eligible: dict[str, list[str]] = {}
        for job in valid_jobs:
            if job.job_id in analyses:
                conflicts, missing = await self._condition_status(
                    profile, analyses[job.job_id], deadline=deadline
                )
                if not conflicts:
                    eligible[job.job_id] = missing
                else:
                    self.diagnostics[job.job_id] = AssessmentDiagnostic(
                        code="condition_mismatch",
                        stage="conditions",
                        detail="Job details conflict with confirmed search conditions.",
                        retryable=False,
                        exclusion_reasons=conflicts,
                    )
            else:
                eligible[job.job_id] = list(
                    dict.fromkeys(["target_direction", *_preference_check(profile, job)[1]])
                )

        async def compare(identity: str) -> dict[str, JobMatch]:
            async with self._matching_slots:
                job = next(job for job in valid_jobs if job.job_id == identity)
                return await self._validated_rows(
                    ReviewResponse if job.has_full_description() else SummaryReviewResponse,
                    {
                        "task": "matching",
                        "assessment_date": datetime.now(UTC).date().isoformat(),
                        "target_directions": profile.target_directions,
                        "preferences": profile.preferences.model_dump(mode="json"),
                        "profile_quotes": {
                            key: row["excerpt"]
                            for key, row in profile_quotes(profile_documents).items()
                        },
                        "profile_facts": _profile_facts(profile),
                        "repair_feedback": {identity: repair_feedback[identity]}
                        if repair_feedback and identity in repair_feedback
                        else {},
                    },
                    [
                        {
                            **analyses[identity].model_dump(),
                            "title": job.title,
                            "salary": job.salary,
                            "summary": job.description if not job.has_full_description() else None,
                            "listing_scope": "full" if job.has_full_description() else "summary",
                        }
                    ],
                    lambda entry: None,
                    lambda response: [
                        _review_match(response, analyses[identity], profile, profile_documents)
                    ],
                    deadline,
                )

        compared = await _gather_results(
            *(compare(identity) for identity in eligible if identity in analyses)
        )
        matches = {identity: match for response in compared for identity, match in response.items()}
        ranked: list[_Ranked] = []
        for job in valid_jobs:
            if job.job_id not in eligible:
                continue
            analysis = analyses.get(job.job_id, JobAnalysis(job_id=job.job_id))
            match = matches.get(job.job_id, JobMatch(job_id=job.job_id))
            rendered = _render(
                profile,
                job,
                analysis,
                match,
                documents[job.job_id],
                profile_documents,
                [],
                "partial" if analysis.incomplete or match.incomplete else "complete",
                self.dimension_scores,
            )
            missing = eligible[job.job_id]
            rendered.item.verification_status = "pending" if missing else "confirmed"
            rendered.item.unknown_conditions = missing
            issue = self.diagnostics.get(job.job_id)
            if issue is not None:
                rendered.item.review_issue = issue.review_issue()
            elif rendered.item.analysis_status == "unavailable":
                if not analysis.requirements:
                    rendered.item.review_issue = ReviewIssue(
                        code="incomplete_review"
                        if analysis.incomplete
                        else "insufficient_job_information",
                        stage="jd_analysis",
                    )
                else:
                    rendered.item.review_issue = ReviewIssue(code="failed", stage="matching")
            ranked.append(rendered)
        return ranked

    async def assess(
        self,
        profile: UserProfile,
        jobs: list[JobPosting],
        profile_documents: dict[str, str],
        session_id: str,
        deadline: float | None = None,
        *,
        on_batch: Callable[[RecommendationResult], Awaitable[None]] | None = None,
        repair_feedback: dict[str, str] | None = None,
    ) -> RecommendationResult:
        """Assess a bounded number of unique candidates per confirmed search, across rounds.

        Call begin_search with a stable confirmation ID before assessment. A new
        confirmation resets the candidate budget, not the JD cache.
        `deadline` is an absolute event-loop monotonic time. A service may not be
        shared between sessions. Every assessment re-matches the current profile;
        interrupted graphs must reuse their completed assessment checkpoint.
        """
        validate_recommendation_profile(profile, session_id)
        if deadline is not None and not math.isfinite(deadline):
            raise RecommendationError(
                "recommendation_invalid_time", "The deadline must be a finite value."
            )
        async with self._lock:
            self._ensure_open()
            if self._search_id is None:
                raise RecommendationError(
                    "recommendation_search_not_started",
                    "Begin a confirmed search before assessing job candidates.",
                )
            if self._session_id is not None and self._session_id != session_id:
                raise RecommendationError(
                    "recommendation_invalid_session",
                    "The job assessment service cannot be shared across sessions.",
                )
            self._session_id = session_id
            candidates: list[JobPosting] = []
            if repair_feedback:
                self.dimension_scores.clear()
            excluded = eligibility_exclusions(profile, jobs)
            unique = eligible_jobs(profile, jobs)
            for job in jobs:
                self.diagnostics.pop(job.job_id, None)
                if job.job_id not in {candidate.job_id for candidate in unique}:
                    self.diagnostics[job.job_id] = AssessmentDiagnostic(
                        code="condition_mismatch",
                        stage="eligibility",
                        detail="The listing was excluded by the eligibility rules.",
                        retryable=False,
                        exclusion_reasons=excluded.get(job.job_id, []),
                    )
            eligible = select_candidates(unique, limit=len(unique))
            for job in eligible:
                if job.job_id in self._analyzed_ids or self.analyzed_count < MAX_CANDIDATES:
                    candidates.append(job)
                    self._analyzed_ids.add(job.job_id)
            semaphore = asyncio.Semaphore(CONCURRENCY)

            async def process(batch: list[JobPosting]) -> list[_Ranked]:
                async with semaphore:
                    completed = await self._batch(
                        profile, batch, profile_documents, deadline, repair_feedback
                    )
                    if on_batch is not None:
                        await on_batch(
                            RecommendationResult(
                                session_id=session_id,
                                generated_at=datetime.now(UTC),
                                jobs=[
                                    row.item
                                    for row in completed
                                    if row.item.verification_status == "confirmed"
                                ],
                                pending_jobs=[
                                    row.item
                                    for row in completed
                                    if row.item.verification_status == "pending"
                                ],
                            )
                        )
                    return completed

            batches = await _gather_results(
                *(
                    process(candidates[i : i + BATCH_SIZE])
                    for i in range(0, len(candidates), BATCH_SIZE)
                )
            )
            self._ensure_open()
            ranked = [item for batch in batches for item in batch]
            ranked.sort(key=lambda row: recommendation_key(row.item))
            diagnostics = [warning for item in ranked for warning in item.diagnostics]
            notices = []
            if len(eligible) > len(candidates):
                notices.append(make_notice("coverage_limited"))
                diagnostics.append(
                    "This confirmed search reached its candidate analysis budget. The remaining candidates were not analyzed."
                )
            if not ranked:
                diagnostics.append("No recommended jobs match the current criteria.")
            for field in ("salary_range", "work_mode", "industry"):
                if f"preferences.{field}" in profile.confirmed_fields and getattr(
                    profile.preferences, field
                ):
                    diagnostics.append(
                        f"Could not reliably verify the {field} preference. Check the original job description."
                    )
            for diagnostic in dict.fromkeys(diagnostics):
                _LOGGER.info(
                    "recommendation_diagnostic session=%s detail=%s", session_id, diagnostic
                )
            return finalize_recommendation(
                RecommendationResult(
                    session_id=session_id,
                    generated_at=datetime.now(UTC),
                    jobs=[
                        item.item for item in ranked if item.item.verification_status == "confirmed"
                    ][: profile.search_options.result_count],
                    pending_jobs=[
                        item.item for item in ranked if item.item.verification_status == "pending"
                    ][: profile.search_options.result_count],
                    introduction="Explore roles that connect with your background and preferences.",
                ),
                notices=notices,
            )
