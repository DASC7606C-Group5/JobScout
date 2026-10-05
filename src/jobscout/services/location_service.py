"""Trusted geography catalogs and hierarchy comparisons for semantic search."""

import asyncio
import json
import re
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal
from urllib.parse import urljoin, urlsplit

from jobscout.schemas.profile import LocationRef
from jobscout.services.job_retrieval.async_transport import AsyncHttpWebClient
from jobscout.services.job_retrieval.html_fields import Tree
from jobscout.services.job_retrieval.models import RetrievalFailure
from jobscout.services.job_retrieval.web_transport import AsyncWebClient

CN_DIRECTORY = "https://dict.zhaopin.cn/dict/dictOpenService/getDict?dictNames=region_relation"
HK_DIRECTORY = "https://www.had.gov.hk/en/18_districts/my_map.htm"
LIEPIN_DIRECTORY = "https://www.liepin.com/citylist/"
CATALOG_TTL = 24 * 60 * 60


def location_key(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


@dataclass
class CatalogEntry:
    location: LocationRef
    names: set[str]
    source_url: str
    fetched_at: datetime = field(default_factory=lambda: datetime.now(UTC))


def parse_cn_directory(text: str, fetched_at: datetime) -> list[CatalogEntry]:
    """Decode the JSON value in the published script; never evaluate JavaScript."""
    marker = re.search(r"(?:zpBaseData\.)?region_relation\s*=\s*", text)
    if marker is None:
        raise RetrievalFailure("LOCATION_CATALOG_INVALID", "The location directory changed.")
    try:
        values, _ = json.JSONDecoder().raw_decode(text[marker.end() :])
    except ValueError, TypeError:
        raise RetrievalFailure(
            "LOCATION_CATALOG_INVALID", "The location directory is invalid."
        ) from None
    if not isinstance(values, list):
        raise RetrievalFailure("LOCATION_CATALOG_INVALID", "The location directory is invalid.")
    rows = {str(row.get("strKey")): row for row in values if isinstance(row, dict)}
    result: list[CatalogEntry] = []
    for key, row in rows.items():
        if not key.isdigit() or not isinstance(row.get("value"), str):
            continue
        kind = row.get("itemAliasValue1")
        if kind not in {"CITY", "MUNICIPALITY", "DISTRICT", "PROVINCE", "COUNTRY"}:
            continue
        parents: list[str] = []
        parent = str(row.get("parentStrKey", ""))
        current = parent
        while current in rows and current not in parents and current != key:
            parents.append(current)
            current = str(rows[current].get("parentStrKey", ""))
        # The catalog includes foreign locations. Only descendants of mainland
        # China's catalog identity are available to this product.
        if key != "489" and "489" not in parents:
            continue
        if key in {"561", "562", "563"} or set(parents) & {"561", "562", "563"}:
            continue
        names = {row["value"]}
        for name in ("aliasEnglishValue", "aliasPinYinValue", "shortName"):
            if isinstance(row.get(name), str) and row[name].strip():
                names.add(row[name])
        attributes = row.get("attributeValue")
        if isinstance(attributes, str):
            try:
                attributes = json.loads(attributes)
            except ValueError:
                attributes = None
        if isinstance(attributes, dict):
            for name in ("fullName", "shortName"):
                if isinstance(attributes.get(name), str):
                    names.add(attributes[name])
        level: Literal["country", "region", "city", "district"] = (
            "city"
            if kind in {"CITY", "MUNICIPALITY"}
            else "district"
            if kind == "DISTRICT"
            else "region"
            if kind == "PROVINCE"
            else "country"
        )
        result.append(
            CatalogEntry(
                location=LocationRef(
                    id=f"cn:{key}",
                    name=row["value"],
                    region="cn",
                    level=level,
                    parent_id=f"cn:{parent}" if parent in parents else None,
                    ancestor_ids=[f"cn:{item}" for item in parents],
                    source_codes={"zhaopin": key},
                ),
                names=names,
                source_url=CN_DIRECTORY,
                fetched_at=fetched_at,
            )
        )
    if not result:
        raise RetrievalFailure(
            "LOCATION_CATALOG_INVALID", "The location directory has no supported entries."
        )
    return result


def parse_hk_directory(text: str, fetched_at: datetime) -> list[CatalogEntry]:
    result: list[CatalogEntry] = []
    group: CatalogEntry | None = None
    # Both language versions preserve the official district page identity.
    tokens = re.finditer(
        r'<div\b[^>]*class=["\']area-title["\'][^>]*>(.*?)</div>|'
        r'<a\b[^>]*href=["\']([^"\']*/my_map_(\d{2})\.php)["\'][^>]*>(.*?)</a>',
        text,
        re.S | re.I,
    )
    group_index = 0
    for token in tokens:
        if token.group(1) is not None:
            group_index += 1
            name = Tree(token.group(1)).root.text()
            group = CatalogEntry(
                LocationRef(
                    id=f"hk:region:{group_index}",
                    name=name,
                    region="hk",
                    level="region",
                    parent_id="hk",
                    ancestor_ids=["hk"],
                ),
                {name},
                HK_DIRECTORY,
                fetched_at,
            )
            result.append(group)
        elif group is not None:
            name = Tree(token.group(4)).root.text()
            result.append(
                CatalogEntry(
                    LocationRef(
                        id=f"hk:district:{token.group(3)}",
                        name=name,
                        region="hk",
                        level="district",
                        parent_id=group.location.id,
                        ancestor_ids=[group.location.id, "hk"],
                    ),
                    {name},
                    token.group(2),
                    fetched_at,
                )
            )
    if len([row for row in result if row.location.level == "district"]) != 18:
        raise RetrievalFailure(
            "LOCATION_CATALOG_INVALID", "The Hong Kong district directory changed."
        )
    return result


class LocationCatalog:
    """Public facts cached separately from private user data and model output."""

    def __init__(
        self, client: AsyncWebClient | None = None, *, entries: list[CatalogEntry] | None = None
    ) -> None:
        self.client = client or AsyncHttpWebClient()
        self.entries: dict[str, CatalogEntry] = {}
        self._loaded_at: float | None = None
        self._lock = asyncio.Lock()
        self._liepin_links: dict[str, str] | None = None
        self._merge(
            [
                CatalogEntry(
                    LocationRef(
                        id="cn:489",
                        name="Mainland China",
                        region="cn",
                        level="country",
                        source_codes={"zhaopin": "489"},
                    ),
                    {
                        "Mainland China",
                        "China",
                        "cn",
                        "中国大陆",
                        "中國大陸",
                        "中国",
                        "中國",
                        "全国",
                    },
                    CN_DIRECTORY,
                ),
                CatalogEntry(
                    LocationRef(id="hk", name="Hong Kong", region="hk", level="country"),
                    {"Hong Kong", "hk", "香港"},
                    HK_DIRECTORY,
                ),
                *(entries or []),
            ]
        )
        if entries is not None:
            self._loaded_at = time.monotonic()

    def _merge(self, entries: list[CatalogEntry], *, translations: bool = False) -> None:
        for entry in entries:
            if entry.location.id in self.entries:
                previous = self.entries[entry.location.id]
                entry.names |= previous.names
                # English catalog is the display language; translated catalog
                # entries contribute official names without changing identity.
                if translations:
                    entry.location = previous.location.model_copy(deep=True)
            self.entries[entry.location.id] = entry

    async def refresh(self, *, deadline: float | None = None) -> None:
        if self._loaded_at is not None and time.monotonic() - self._loaded_at < CATALOG_TTL:
            return
        async with self._lock:
            if self._loaded_at is not None and time.monotonic() - self._loaded_at < CATALOG_TTL:
                return
            async with asyncio.timeout_at(deadline):
                pages = await asyncio.gather(
                    self.client.request_async(CN_DIRECTORY),
                    self.client.request_async(HK_DIRECTORY),
                    self.client.request_async(HK_DIRECTORY.replace("/en/", "/tc/")),
                    return_exceptions=True,
                )
            accepted = False
            for index, page in enumerate(pages):
                if isinstance(page, BaseException):
                    continue
                try:
                    rows = (
                        parse_cn_directory(page.text, page.fetched_at)
                        if index == 0
                        else parse_hk_directory(page.text, page.fetched_at)
                    )
                except RetrievalFailure:
                    continue
                if index in {0, 1}:
                    region = "cn" if index == 0 else "hk"
                    self.entries = {
                        identity: entry
                        for identity, entry in self.entries.items()
                        if entry.location.region != region or entry.location.level == "country"
                    }
                self._merge(rows, translations=index == 2)
                accepted = True
            if accepted:
                self._loaded_at = time.monotonic()

    def find(self, query: str) -> list[LocationRef]:
        key = location_key(query)
        if not key:
            return []
        exact = [
            entry.location.model_copy(deep=True)
            for entry in self.entries.values()
            if key in {location_key(name) for name in entry.names}
        ]
        if exact:
            return exact
        # Parent-qualified official names disambiguate repeated district names.
        # Require the entire input to be consumed so a district or exclusion
        # cannot disappear because the city happens to match a substring.
        compact = re.sub(r"[\s,，/·-]+", "", key)
        qualified: list[LocationRef] = []
        for entry in self.entries.values():
            if entry.location.level not in {"district", "city"}:
                continue
            ancestors = [
                self.entries[identity]
                for identity in entry.location.ancestor_ids
                if identity in self.entries
            ]
            if any(
                compact == re.sub(r"[\s,，/·-]+", "", location_key(parent_name + name))
                for parent in ancestors
                for parent_name in parent.names
                for name in entry.names
            ):
                qualified.append(entry.location.model_copy(deep=True))
        return qualified

    async def lookup(self, query: str, *, deadline: float | None = None) -> list[LocationRef]:
        known = self.find(query)
        if known and all(item.level == "country" for item in known):
            return known
        await self.refresh(deadline=deadline)
        return self.find(query)

    def resolve(self, identity: str) -> LocationRef | None:
        entry = self.entries.get(identity)
        return entry.location.model_copy(deep=True) if entry else None

    def city(self, location: LocationRef) -> LocationRef | None:
        for identity in [location.id, *location.ancestor_ids]:
            candidate = self.resolve(identity)
            if candidate and candidate.level in {"city", "country"}:
                return candidate
        return None

    async def source_location(
        self, location: LocationRef, source: str, *, deadline: float | None = None
    ) -> LocationRef:
        """Return a catalog copy enriched with a verified native city parameter."""
        trusted = self.resolve(location.id)
        if trusted is None or trusted.model_dump(exclude={"source_codes"}) != location.model_dump(
            exclude={"source_codes"}
        ):
            raise RetrievalFailure(
                "SEARCH_LOCATION_UNSUPPORTED",
                "The location is not present in the trusted directory.",
            )
        if trusted.region != "cn" or trusted.level == "country":
            return trusted
        city = self.city(trusted)
        if city is None:
            raise RetrievalFailure(
                "SEARCH_LOCATION_UNSUPPORTED", "This source has no verified city mapping."
            )
        if source != "liepin":
            return trusted.model_copy(
                update={"source_codes": {**trusted.source_codes, **city.source_codes}}
            )
        if "liepin" not in city.source_codes:
            async with asyncio.timeout_at(deadline):
                if self._liepin_links is None:
                    directory = await self.client.request_async(LIEPIN_DIRECTORY)
                    links: dict[str, str] = {}
                    for anchor in Tree(directory.text).root.find(tag="a"):
                        href = urljoin(LIEPIN_DIRECTORY, anchor.attrs.get("href", ""))
                        parts = urlsplit(href)
                        if (
                            parts.scheme == "https"
                            and parts.netloc == "www.liepin.com"
                            and re.fullmatch(r"/city-[a-z0-9-]+/", parts.path)
                        ):
                            links[location_key(anchor.text())] = href
                    self._liepin_links = links
                city_url = next(
                    (
                        self._liepin_links[location_key(name)]
                        for name in self.entries[city.id].names
                        if location_key(name) in self._liepin_links
                    ),
                    None,
                )
                if city_url is None:
                    raise RetrievalFailure(
                        "SEARCH_LOCATION_UNSUPPORTED", "This source has no verified city mapping."
                    )
                page = await self.client.request_async(city_url)
                name = re.search(r'["\']adDqName["\']\s*:\s*["\']([^"\']+)["\']', page.text)
                code = re.search(r'["\']dqCode["\']\s*:\s*["\'](\d+)["\']', page.text)
                if (
                    not name
                    or not code
                    or location_key(name.group(1))
                    not in {location_key(value) for value in self.entries[city.id].names}
                ):
                    raise RetrievalFailure(
                        "SEARCH_LOCATION_UNSUPPORTED",
                        "The source city mapping could not be verified.",
                    )
                self.entries[city.id].location.source_codes["liepin"] = code.group(1)
                city = self.entries[city.id].location
        return trusted.model_copy(
            update={"source_codes": {**trusted.source_codes, "liepin": city.source_codes["liepin"]}}
        )


def within(actual: LocationRef, requested: LocationRef) -> bool:
    return actual.id == requested.id or requested.id in actual.ancestor_ids


_catalog: LocationCatalog | None = None


def get_location_catalog() -> LocationCatalog:
    global _catalog
    if _catalog is None:
        _catalog = LocationCatalog()
    return _catalog
