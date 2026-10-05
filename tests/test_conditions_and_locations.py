"""Language interpretations must resolve to trusted identities and preserve intent."""

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from jobscout.schemas.profile import (
    ProfilePreferences,
    RawProfilePreferences,
    SearchOptions,
    UserProfile,
)
from jobscout.services.condition_service import ConditionService, PreferenceMeaning
from jobscout.services.conversation_service import ProfileChange, apply_changes, missing_fields
from jobscout.services.job_retrieval.models import RetrievalFailure
from jobscout.services.job_retrieval.web_transport import WebPage
from jobscout.services.location_service import (
    CN_DIRECTORY,
    LocationCatalog,
    parse_cn_directory,
    parse_hk_directory,
    within,
)
from tests.location_fixtures import catalog_snapshot

NOW = datetime(2026, 10, 6, tzinfo=UTC)


class MeaningProvider:
    def __init__(self, meaning: dict[str, Any]) -> None:
        self.meaning = meaning
        self.location_catalog = catalog_snapshot()
        self.payloads: list[dict[str, Any]] = []

    async def structured[T: BaseModel](
        self, schema: type[T], messages: list[dict[str, str]], *, deadline: float | None = None
    ) -> T:
        self.payloads.append(json.loads(messages[-1]["content"]))
        return schema.model_validate(self.meaning)


def test_multilingual_combinations_and_exclusions_preserve_raw_text() -> None:
    user = UserProfile(
        profile_id="p",
        target_directions=["Research Engineer"],
        preferences=ProfilePreferences(
            location="上海或Wuhan，排除浦東", employment_type="全职或者实习，不做freelance"
        ),
    )
    original = user.model_dump_json()
    provider = MeaningProvider(
        {
            "locations": {"included": ["上海", "Wuhan"], "excluded": ["浦东新区"]},
            "employment": {"included": ["full-time", "internship"], "excluded": ["freelance"]},
        }
    )
    result = asyncio.run(ConditionService(provider).resolve(user))
    assert [ref.id for ref in result.preferences.locations.included] == ["cn:538", "cn:736"]
    assert [ref.id for ref in result.preferences.locations.excluded] == ["cn:2031"]
    assert result.preferences.employment.included == ["full-time", "internship"]
    assert (
        result.preferences.location
        == result.preferences.locations.raw_text
        == "上海或Wuhan，排除浦東"
    )
    assert (
        result.preferences.employment_type
        == result.preferences.employment.raw_text
        == "全职或者实习，不做freelance"
    )
    assert missing_fields(result) == []
    assert user.model_dump_json() == original


@pytest.mark.parametrize("name", ["Atlantis", "London", "Shanghai Pudong Unknown"])
def test_unknown_place_cannot_silently_become_city_or_unrestricted(name: str) -> None:
    provider = MeaningProvider(
        {"locations": {"included": [name]}, "employment": {"included": ["full-time"]}}
    )
    result = asyncio.run(
        ConditionService(provider).resolve(
            UserProfile(
                profile_id="p",
                target_directions=["Engineer"],
                preferences=ProfilePreferences(location=name, employment_type="full-time"),
            )
        )
    )
    assert result.preferences.locations.included == []
    assert not result.preferences.locations.unrestricted
    assert "preferences.location" in missing_fields(result)


def test_excluded_ancestor_conflict_requires_clarification() -> None:
    provider = MeaningProvider(
        {
            "locations": {"included": ["浦东新区"], "excluded": ["上海"]},
            "employment": {"included": ["full-time"]},
        }
    )
    result = asyncio.run(
        ConditionService(provider).resolve(
            UserProfile(
                profile_id="p",
                preferences=ProfilePreferences(
                    location="浦东，不去上海", employment_type="full-time"
                ),
            )
        )
    )
    assert "preferences.location" in result.conflicts
    assert result.preferences.locations.included[0].id == "cn:2031"


def test_contradictory_employment_requires_clarification_without_erasing_original_text() -> None:
    provider = MeaningProvider(
        {
            "locations": {"included": ["香港"]},
            "employment": {"included": ["internship"], "excluded": ["internship"]},
        }
    )
    user = UserProfile(
        profile_id="p",
        target_directions=["Analyst"],
        preferences=ProfilePreferences(location="香港", employment_type="实习，但排除实习"),
    )
    result = asyncio.run(ConditionService(provider).resolve(user))
    assert (
        result.preferences.employment.raw_text
        == result.preferences.employment_type
        == "实习，但排除实习"
    )
    assert "preferences.employment_type" in result.conflicts
    assert "preferences.employment_type" in missing_fields(result)


def test_explicit_edit_invalidates_resolved_conditions_and_clears_only_changed_conflict() -> None:
    user = UserProfile(profile_id="p", conflicts=["preferences.location", "education"])
    user.preferences.locations.included = [catalog_snapshot().find("Shanghai")[0]]
    edited = apply_changes(user, [ProfileChange(field="preferences.location", value="香港")])
    assert edited.preferences.location == "香港"
    assert edited.preferences.locations.included == []
    assert edited.conflicts == ["education"]
    assert user.preferences.locations.included[0].id == "cn:538"


def test_client_cannot_submit_location_ids_or_source_codes() -> None:
    with pytest.raises(ValidationError):
        RawProfilePreferences.model_validate(
            {
                "location": "Shanghai",
                "locations": {"included": [{"id": "cn:538", "source_codes": {"liepin": "forged"}}]},
            }
        )
    with pytest.raises(ValidationError):
        PreferenceMeaning.model_validate({"locations": {"included": [{"id": "forged"}]}})


@pytest.mark.parametrize("count", [4, 21, True, 5.5])
def test_result_count_rejects_values_outside_contract(count: object) -> None:
    with pytest.raises(ValidationError):
        SearchOptions.model_validate({"result_count": count})


def cn_rows() -> list[dict[str, Any]]:
    return [
        {"strKey": "489", "parentStrKey": "0", "value": "全国", "itemAliasValue1": "COUNTRY"},
        {
            "strKey": "538",
            "parentStrKey": "489",
            "value": "上海",
            "itemAliasValue1": "MUNICIPALITY",
            "aliasEnglishValue": "SHANGHAI",
            "attributeValue": {"fullName": "上海市"},
        },
        {
            "strKey": "2031",
            "parentStrKey": "538",
            "value": "浦东新区",
            "itemAliasValue1": "DISTRICT",
            "attributeValue": {"shortName": "浦东"},
        },
        {"strKey": "987", "parentStrKey": "0", "value": "Foreign place", "itemAliasValue1": "CITY"},
    ]


def test_public_directory_parses_json_without_executing_script_and_preserves_district() -> None:
    script = (
        "var zpBaseData={}; zpBaseData.region_relation = "
        + json.dumps(cn_rows())
        + "; throw new Error('never execute');"
    )
    entries = parse_cn_directory(script, NOW)
    directory = LocationCatalog(entries=entries)
    city = directory.find("Shanghai")[0]
    district = directory.find("浦东")[0]
    assert city.source_codes["zhaopin"] == "538"
    assert district.id == "cn:2031" and district.parent_id == city.id
    assert within(district, city) and not within(city, district)
    assert directory.find("Foreign place") == []
    assert all(entry.source_url == CN_DIRECTORY and entry.fetched_at == NOW for entry in entries)
    assert directory.find("上海市浦东新区")[0].id == "cn:2031"
    assert directory.find("Shanghai/Pudong/Unknown") == []


def hk_page(prefix: str = "District") -> str:
    return '<div class="area-title">Region</div>' + "".join(
        f'<a href="https://www.had.gov.hk/en/18_districts/my_map_{index:02}.php">{prefix} {index}</a>'
        for index in range(1, 19)
    )


def test_hk_official_page_id_keeps_translation_and_parent_identity() -> None:
    english = parse_hk_directory(hk_page(), NOW)
    translated = parse_hk_directory(hk_page("区域"), NOW)
    directory = LocationCatalog(entries=english)
    directory._merge(translated, translations=True)
    place = directory.find("区域 3")[0]
    assert place.id == "hk:district:03" and place.name == "District 3"
    assert place.ancestor_ids == ["hk:region:1", "hk"]
    with pytest.raises(RetrievalFailure):
        parse_hk_directory(hk_page().replace("my_map_18.php", "unrecognized.php"), NOW)


def test_catalog_refresh_updates_hierarchy_and_removes_disappeared_entries() -> None:
    class Client:
        async def request_async(
            self,
            url: str,
            *,
            body: dict[str, object] | None = None,
            headers: dict[str, str] | None = None,
        ) -> WebPage:
            rows = cn_rows()
            rows = [row for row in rows if row["strKey"] != "2031"]
            rows[1]["value"] = "Updated source name"
            return WebPage(
                "region_relation=" + json.dumps(rows) if url == CN_DIRECTORY else hk_page(), NOW
            )

    directory = catalog_snapshot()
    directory.client = Client()
    directory._loaded_at = None
    asyncio.run(directory.refresh())
    assert directory.find("浦东新区") == []
    assert directory.resolve("cn:538").name == "Updated source name"  # type: ignore[union-attr]


def test_source_native_code_is_authoritative_and_forged_identity_rejected() -> None:
    directory = catalog_snapshot()
    city = directory.find("Shanghai")[0]
    city.source_codes["liepin"] = "forged"
    mapped = asyncio.run(directory.source_location(city, "liepin"))
    assert mapped.source_codes["liepin"] == "020"
    district = directory.find("浦东新区")[0]
    mapped = asyncio.run(directory.source_location(district, "zhaopin"))
    assert mapped.id == district.id and mapped.source_codes["zhaopin"] == "538"
    city.name = "Fabricated identity"
    with pytest.raises(RetrievalFailure) as error:
        asyncio.run(directory.source_location(city, "liepin"))
    assert error.value.code == "SEARCH_LOCATION_UNSUPPORTED"
