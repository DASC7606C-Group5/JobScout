"""Deterministic planning; input remains the team's SearchRequest."""

import re
from dataclasses import dataclass

from jobscout.schemas.search import SearchRequest

from .models import RetrievalFailure

DEFAULT_SOURCES = ("zhaopin", "liepin", "shixiseng", "jobsdb")
FEED_SOURCES = ("remotive", "arbeitnow")
REGIONAL_SOURCES = {"hk": ("jobsdb",), "cn": ("zhaopin", "liepin", "shixiseng")}


def location_region(location: str | None) -> str | None:
    """Small explicit routing table, not a geocoder; unknown locations stay unknown."""
    value = (location or "").strip().casefold()
    aliases = {
        "hk": (
            "hong kong",
            "hongkong",
            "香港",
            "kowloon",
            "九龍",
            "九龙",
            "新界",
            "new territories",
        ),
        "cn": (
            "mainland china",
            "中国大陆",
            "中國大陸",
            "中国内地",
            "中國內地",
            "beijing",
            "shanghai",
            "shenzhen",
            "guangzhou",
            "hangzhou",
            "chengdu",
            "北京",
            "上海",
            "深圳",
            "广州",
            "廣州",
            "杭州",
            "成都",
            "武汉",
            "武漢",
            "南京",
            "苏州",
            "蘇州",
            "天津",
            "重庆",
            "重慶",
            "西安",
            "厦门",
            "廈門",
            "广东",
            "廣東",
            "浙江",
            "江苏",
            "江蘇",
            "四川",
            "湖北",
            "福建",
            "山东",
            "山東",
        ),
        "de": (
            "germany",
            "deutschland",
            "德国",
            "德國",
            "berlin",
            "munich",
            "hamburg",
            "cologne",
            "frankfurt",
        ),
    }
    if value in {"hk", "香港特别行政区", "香港特別行政區"}:
        return "hk"
    if value in {"cn", "china", "中国", "中國", "中国大陆", "中國大陸", "全国"}:
        return "cn"
    for region, names in aliases.items():
        if any(
            name in value
            if any(ord(c) > 127 for c in name)
            else re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", value)
            for name in names
        ):
            return region
    return None


EMPLOYMENT_ALIASES = {
    "full-time": {
        "full time",
        "fulltime",
        "fulltime permanent",
        "fulltime fixed term",
        "full time permanent",
        "permanent full time",
        "employee / full time",
        "full time (100%)",
        "vollzeit",
    },
    "part-time": {"part time", "parttime", "parttime permanent", "parttime fixed term", "teilzeit"},
    "internship": {"internship", "intern", "praktikum"},
    "contract": {"contract"},
    "freelance": {"freelance"},
}


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
        normalized(k) for k in EMPLOYMENT_ALIASES
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
    """Preserve supplied phrases; baseline is the direction itself, without LLM expansion."""
    return list(request.keywords) if request.keywords else [request.target_direction.strip()]


def select_sources(request: SearchRequest) -> list[str]:
    """Explicit selection wins; otherwise route by supported geographic coverage."""
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
    region = location_region(request.location)
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
    # One bounded snapshot serves all directions. Neither feed documents native
    # location/employment filters. Do not send invented query parameters.
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
