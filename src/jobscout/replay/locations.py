"""Synthetic locations and explicit preferences for offline simulations."""

import re
from functools import lru_cache
from typing import Any

from jobscout.schemas.profile import LocationRef
from jobscout.services.location_service import CatalogEntry, LocationCatalog


@lru_cache(maxsize=1)
def replay_catalog() -> LocationCatalog:
    """Offline synthetic geography for the explicitly selected replay mode."""
    cities = [
        ("530", "北京", "Beijing"),
        ("538", "上海", "Shanghai"),
        ("763", "广州", "Guangzhou"),
        ("765", "深圳", "Shenzhen"),
        ("653", "杭州", "Hangzhou"),
        ("801", "成都", "Chengdu"),
        ("736", "武汉", "Wuhan"),
    ]
    return LocationCatalog(
        entries=[
            CatalogEntry(
                LocationRef(id="hk", name="Hong Kong", region="hk", level="country"),
                {"Hong Kong", "hongkong", "hk", "香港"},
                "synthetic-replay",
            ),
            CatalogEntry(
                LocationRef(id="cn:489", name="Mainland China", region="cn", level="country"),
                {"Mainland China", "China", "中国", "中國", "全国", "cn"},
                "synthetic-replay",
            ),
            *(
                CatalogEntry(
                    LocationRef(
                        id=f"cn:{code}",
                        name=name,
                        region="cn",
                        level="city",
                        parent_id="cn:489",
                        ancestor_ids=["cn:489"],
                        source_codes={"zhaopin": code},
                    ),
                    {name, english},
                    "synthetic-replay",
                )
                for code, name, english in cities
            ),
        ]
    )


def replay_preferences(payload: dict[str, Any]) -> dict[str, Any]:
    locations: dict[str, Any] = {
        "included": [],
        "excluded": [],
        "unrestricted": bool(payload.get("location_unrestricted")),
    }
    employment: dict[str, Any] = {
        "included": [],
        "excluded": [],
        "unrestricted": bool(payload.get("employment_type_unrestricted")),
    }
    unrestricted = {
        "unrestricted",
        "any",
        "anywhere",
        "any location",
        "any employment type",
        "no preference",
        "不限",
    }
    employment_names = {
        "全职": "full-time",
        "实习": "internship",
        "兼职": "part-time",
        "合同": "contract",
        "自由职业": "freelance",
        "full time": "full-time",
        "part time": "part-time",
        "intern": "internship",
    }
    for raw, target in (
        (payload.get("location"), locations),
        (payload.get("employment_type"), employment),
    ):
        if not raw:
            continue
        if str(raw).strip().casefold() in unrestricted:
            target["unrestricted"] = True
            continue
        for part in re.split(r"[,，;/]|\s+(?:or|and)\s+", str(raw)):
            value = part.strip()
            if not value:
                continue
            if target is employment:
                canonical = employment_names.get(value.casefold(), value.casefold())
                if canonical in {"full-time", "part-time", "internship", "contract", "freelance"}:
                    target["included"].append(canonical)
            else:
                target["included"].append(value)
    work_mode = payload.get("work_mode")
    # Replay accepts only explicit UI enum values; live interpretation uses the model.
    return {
        "locations": locations,
        "employment": employment,
        "work_modes": [work_mode] if work_mode in {"remote", "hybrid", "onsite"} else [],
        "work_mode_uncertain": bool(work_mode) and work_mode not in {"remote", "hybrid", "onsite"},
    }
