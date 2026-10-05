"""Small offline directory snapshots used to test source-native location routing."""

from jobscout.schemas.profile import LocationRef
from jobscout.services.location_service import CatalogEntry, LocationCatalog, get_location_catalog


def catalog_snapshot() -> LocationCatalog:
    entries = [
        CatalogEntry(
            LocationRef(id="hk", name="Hong Kong", region="hk", level="country"),
            {"Hong Kong", "香港", "中国香港"},
            "synthetic-directory",
        ),
        CatalogEntry(
            LocationRef(
                id="cn:489",
                name="中国",
                region="cn",
                level="country",
                source_codes={"zhaopin": "489"},
            ),
            {"China", "中国", "中国大陆", "cn"},
            "synthetic-directory",
        ),
        CatalogEntry(
            LocationRef(
                id="hk:region:2",
                name="Kowloon",
                region="hk",
                level="region",
                parent_id="hk",
                ancestor_ids=["hk"],
            ),
            {"Kowloon", "九龙", "九龍"},
            "synthetic-directory",
        ),
    ]
    for code, native_code, chinese, english in [
        ("530", "010", "北京", "Beijing"),
        ("538", "020", "上海", "Shanghai"),
        ("765", "050090", "深圳", "Shenzhen"),
        ("736", "170020", "武汉", "Wuhan"),
    ]:
        entries.append(
            CatalogEntry(
                LocationRef(
                    id=f"cn:{code}",
                    name=chinese,
                    region="cn",
                    level="city",
                    parent_id="cn:489",
                    ancestor_ids=["cn:489"],
                    source_codes={"zhaopin": code, "liepin": native_code},
                ),
                {chinese, english},
                "synthetic-directory",
            )
        )
    entries.append(
        CatalogEntry(
            LocationRef(
                id="cn:2031",
                name="浦东新区",
                region="cn",
                level="district",
                parent_id="cn:538",
                ancestor_ids=["cn:538", "cn:489"],
                source_codes={"zhaopin": "2031"},
            ),
            {"浦东新区", "浦东", "Pudong"},
            "synthetic-directory",
        )
    )
    return LocationCatalog(entries=entries)


def bound_location(text: object) -> LocationRef | None:
    # Simulated semantic output is bound to the directory before reaching adapters.
    query = {"Kowloon, Hong Kong": "Kowloon", "Beijing, China": "Beijing"}.get(str(text), str(text))
    choices = get_location_catalog().find(query)
    return choices[0] if len(choices) == 1 else None
