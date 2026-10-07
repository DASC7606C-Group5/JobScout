"""Validate dimension evidence independently and aggregate fixed weights."""

import hashlib
import json
from collections.abc import Sequence
from typing import TYPE_CHECKING

from jobscout.schemas.matching import (
    DIMENSION_WEIGHTS,
    DimensionAssessment,
    MatchDimension,
    MatchScore,
)
from jobscout.schemas.profile import UserProfile

if TYPE_CHECKING:
    from jobscout.services.job_assessment_service import JobAnalysis


def fingerprint(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def aggregate(dimensions: list[MatchDimension], *, incomplete: bool = False) -> MatchScore:
    assessed = sum(d.weight for d in dimensions if d.status == "assessed")
    applicable = sum(d.weight for d in dimensions if d.status != "not_applicable")
    numerator = sum(d.weight * d.score for d in dimensions if d.score is not None)
    # Integer half-up rounding avoids runtime-dependent or banker's rounding.
    total = (2 * numerator + assessed) // (2 * assessed) if assessed else None
    coverage = (200 * assessed + applicable) // (2 * applicable) if applicable else 0
    provisional = incomplete or assessed != applicable or total is None
    return MatchScore(
        total=total,
        dimensions=dimensions,
        assessed_weight=assessed,
        applicable_weight=applicable,
        coverage=coverage,
        provisional=provisional,
        completeness="unknown" if total is None else "partial" if provisional else "complete",
        input_fingerprint=fingerprint([d.input_fingerprint for d in dimensions]),
    )


def build_match_score(
    judgments: Sequence[DimensionAssessment],
    analysis: JobAnalysis,
    profile: UserProfile,
    job_documents: dict[str, str],
    profile_documents: dict[str, str],
    *,
    incomplete: bool = False,
    dimension_cache: dict[str, MatchDimension] | None = None,
) -> MatchScore:
    categories = {
        "skills": "skill",
        "responsibilities": "responsibility",
        "experience": "experience",
        "seniority": "seniority",
        "education": "education",
        "preferences": "preference",
    }
    facts = {
        f"{field}:{index}": text
        for field in ("skills", "education", "internships", "projects")
        for index, text in enumerate(getattr(profile, field))
    }
    dimensions: list[MatchDimension] = []
    for identity, weight in DIMENSION_WEIGHTS.items():
        requirements = [r for r in analysis.requirements if r.category == categories[identity]]
        expected = {r.requirement_id for r in requirements}
        rows = [row for row in judgments if row.id == identity]
        row = rows[0] if len(rows) == 1 else DimensionAssessment(id=identity)
        valid_job = [
            q
            for q in row.job_source_quotes
            if q.excerpt.strip() and q.excerpt in job_documents.get(q.document_id, "")
        ]
        valid_profile = [
            q
            for q in row.profile_source_quotes
            if q.excerpt.strip() and q.excerpt in profile_documents.get(q.document_id, "")
        ]
        valid = (
            len(valid_job) == len(row.job_source_quotes)
            and len(valid_profile) == len(row.profile_source_quotes)
            and all(key in facts for key in row.profile_fact_ids)
            and set(row.requirement_ids).issubset(expected)
        )
        if row.status == "assessed":
            valid &= bool(valid_job) and bool(row.explanation.strip())
            if identity != "preferences":
                valid &= bool(valid_profile) and bool(row.profile_fact_ids)
                valid &= all(
                    any(
                        q.excerpt.casefold() in facts.get(key, "").casefold()
                        for key in row.profile_fact_ids
                    )
                    for q in valid_profile
                )
                valid &= bool(expected) and set(row.requirement_ids) == expected
                if identity == "education":
                    valid &= all(key.startswith("education:") for key in row.profile_fact_ids)
            else:
                valid &= bool(
                    profile.target_directions
                    or any(
                        value
                        for value in profile.preferences.model_dump().values()
                        if isinstance(value, str)
                    )
                )
        elif row.status == "not_applicable":
            # Absence in a listing does not establish that a requirement is waived.
            valid &= not expected and bool(valid_job) and bool(row.explanation.strip())
            valid &= not analysis.incomplete
        if not valid:
            row = DimensionAssessment(
                id=identity,
                missing_information=["The dimension needs verifiable current evidence."],
            )
            incomplete = True
        background = {
            field: getattr(profile, field)
            for field in (
                ("education",)
                if identity == "education"
                else ("internships", "projects")
                if identity in {"experience", "seniority", "responsibilities"}
                else ("skills", "internships", "projects")
            )
        }
        inputs = {
            "rubric": "six-dimension-v1",
            "dimension": identity,
            "requirements": [r.model_dump(mode="json") for r in requirements],
            "job_documents": job_documents,
            "profile": {
                "preferences": profile.preferences.model_dump(mode="json"),
                "directions": profile.target_directions,
            }
            if identity == "preferences"
            else background,
            "profile_evidence": {
                text: sorted(
                    key
                    for key, document in profile_documents.items()
                    if text.casefold() in document.casefold()
                )
                for values in background.values()
                for text in values
            }
            if identity != "preferences"
            else {},
        }
        key = fingerprint(inputs)
        dimension = MatchDimension(**row.model_dump(), weight=weight, input_fingerprint=key)
        if dimension_cache is not None:
            cached = dimension_cache.get(key)
            if cached is not None and all(
                q.excerpt in profile_documents.get(q.document_id, "")
                for q in cached.profile_source_quotes
            ):
                dimension = cached.model_copy(deep=True)
            elif dimension.status != "unknown":
                dimension_cache[key] = dimension.model_copy(deep=True)
        dimensions.append(dimension)
    return aggregate(dimensions, incomplete=incomplete or analysis.incomplete)
