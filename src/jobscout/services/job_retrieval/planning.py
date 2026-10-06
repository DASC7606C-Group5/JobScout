"""Choose sources and build query parameters from a SearchRequest."""

import re
from dataclasses import dataclass
from typing import get_args

from jobscout.schemas.profile import EmploymentType
from jobscout.schemas.search import SearchRequest

from .models import RetrievalFailure

DEFAULT_SOURCES = ("zhaopin", "liepin", "shixiseng", "jobsdb")
FEED_SOURCES = ("remotive", "arbeitnow")
REGIONAL_SOURCES = {"hk": ("jobsdb",), "cn": ("zhaopin", "liepin", "shixiseng")}


def location_region(location: str | None) -> str | None:
    """Look up the region in the cached place directory; let the model interpret free text."""
    from jobscout.services.location_service import get_location_catalog

    candidates = get_location_catalog().find(location or "")
    regions = {item.region for item in candidates}
    return next(iter(regions)) if len(regions) == 1 else None


def normalized(value: str) -> str:
    return " ".join(value.casefold().replace("_", " ").replace("-", " ").split())


def validate_request(request: SearchRequest) -> None:
    if not request.target_direction.strip():
        raise RetrievalFailure("SEARCH_INPUT", "target_direction must not be blank.")
    if any(not keyword.strip() for keyword in request.keywords):
        raise RetrievalFailure("SEARCH_INPUT", "keywords must not contain blank entries.")
    if bool(request.location and request.location.strip()) == request.location_unrestricted:
        raise RetrievalFailure("SEARCH_INPUT", "Specify a location OR location_unrestricted=true.")
    if bool(request.employment_type.strip()) == request.employment_type_unrestricted:
        raise RetrievalFailure(
            "SEARCH_INPUT", "Specify employment_type OR employment_type_unrestricted=true."
        )
    if not request.employment_type_unrestricted and normalized(request.employment_type) not in {
        normalized(k) for k in get_args(EmploymentType)
    }:
        raise RetrievalFailure("SEARCH_INPUT", "Unsupported employment_type; see retrieval guide.")
    if request.work_mode and normalized(request.work_mode) not in {
        "remote",
        "hybrid",
        "onsite",
        "on site",
    }:
        raise RetrievalFailure("SEARCH_INPUT", "work_mode must be remote, hybrid or onsite.")


def plan_keywords(request: SearchRequest) -> list[str]:
    """Use supplied keywords, or the desired role when no keywords are provided."""
    return list(request.keywords) if request.keywords else [request.target_direction.strip()]


def select_sources(request: SearchRequest) -> list[str]:
    """Use requested sources, or choose sources that serve the requested region."""
    if request.sources:
        return list(dict.fromkeys(request.sources))
    if request.location_unrestricted:
        return [
            s
            for s in DEFAULT_SOURCES
            if s != "shixiseng"
            or request.employment_type_unrestricted
            or normalized(request.employment_type) == "internship"
        ]
    region = (
        request.location_ref.region if request.location_ref else location_region(request.location)
    )
    if region in REGIONAL_SOURCES:
        return [
            s
            for s in REGIONAL_SOURCES[region]
            if s != "shixiseng"
            or request.employment_type_unrestricted
            or normalized(request.employment_type) == "internship"
        ]
    return []


@dataclass(frozen=True)
class SourceQuery:
    source: str
    params: dict[str, str | int]
    keywords: tuple[str, ...]
    location: str | None
    employment_type: str
    work_mode: str | None


def plan_source_query(
    request: SearchRequest, source: str, *, page: int = 1, candidate_limit: int = 1000
) -> SourceQuery:
    validate_request(request)
    if source not in FEED_SOURCES:
        raise RetrievalFailure("SEARCH_UNKNOWN_SOURCE", "Unknown job source.")
    # Reuse one limited set of fetched jobs for all desired roles. Neither feed documents
    # location/employment query parameters. Do not send invented parameters.
    params: dict[str, str | int] = (
        {"limit": candidate_limit} if source == "remotive" else {"page": page}
    )
    return SourceQuery(
        source,
        params,
        tuple(plan_keywords(request)),
        request.location,
        normalized(request.employment_type),
        request.work_mode,
    )


def matches_text(text: str, phrase: str) -> bool:
    """Literal phrase, case/whitespace insensitive, with word boundaries."""
    return (
        re.search(r"(?<!\w)" + re.escape(normalized(phrase)) + r"(?!\w)", normalized(text))
        is not None
    )
