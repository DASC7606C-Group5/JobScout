"""Interpret search preferences with the model and look up location IDs on the server."""

import json

from pydantic import BaseModel, ConfigDict, Field

from jobscout.schemas.profile import (
    EmploymentCondition,
    EmploymentType,
    LocationCondition,
    LocationRef,
    UserProfile,
    WorkArrangement,
    WorkMode,
)
from jobscout.services.llm_service import LLMProvider
from jobscout.services.location_service import LocationCatalog, get_location_catalog, within
from jobscout.services.prompts import PREFERENCE_PROMPT


class LocationMeaning(BaseModel):
    model_config = ConfigDict(extra="forbid")

    included: list[str] = Field(default_factory=list, max_length=12)
    excluded: list[str] = Field(default_factory=list, max_length=12)
    unrestricted: bool = False
    uncertain: bool = False


class EmploymentMeaning(BaseModel):
    model_config = ConfigDict(extra="forbid")

    included: list[EmploymentType] = Field(default_factory=list)
    excluded: list[EmploymentType] = Field(default_factory=list)
    unrestricted: bool = False


class PreferenceMeaning(BaseModel):
    model_config = ConfigDict(extra="forbid")

    locations: LocationMeaning = Field(default_factory=LocationMeaning)
    employment: EmploymentMeaning = Field(default_factory=EmploymentMeaning)
    work_modes: list[WorkMode] = Field(default_factory=list)
    excluded_work_modes: list[WorkMode] = Field(default_factory=list)
    work_mode_unrestricted: bool = False
    work_mode_uncertain: bool = False
    conflicts: list[str] = Field(default_factory=list)


class ConditionService:
    def __init__(self, provider: LLMProvider, catalog: LocationCatalog | None = None) -> None:
        self.provider = provider
        self.catalog = (
            catalog or getattr(provider, "location_catalog", None) or get_location_catalog()
        )

    async def resolve(self, profile: UserProfile, *, deadline: float | None = None) -> UserProfile:
        result = profile.model_copy(deep=True)
        preferences = result.preferences
        if (
            not preferences.location
            and not preferences.employment_type
            and not preferences.work_mode
        ):
            preferences.locations = LocationCondition(
                unrestricted=preferences.location_unrestricted
            )
            preferences.employment = EmploymentCondition(
                unrestricted=preferences.employment_type_unrestricted
            )
            preferences.work_arrangement = WorkArrangement()
            return result
        location_current = (
            preferences.locations.raw_text == preferences.location
            and (preferences.locations.unrestricted or bool(preferences.locations.included))
            and preferences.location_unrestricted == preferences.locations.unrestricted
        )
        employment_current = (
            preferences.employment.raw_text == preferences.employment_type
            and (preferences.employment.unrestricted or bool(preferences.employment.included))
            and preferences.employment_type_unrestricted == preferences.employment.unrestricted
        )
        work_current = preferences.work_arrangement.raw_text == preferences.work_mode
        if location_current and employment_current and work_current:
            return result
        meaning = await self.provider.structured(
            PreferenceMeaning,
            [
                {
                    "role": "system",
                    "content": PREFERENCE_PROMPT,
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "location": preferences.location,
                            "location_unrestricted": preferences.location_unrestricted,
                            "employment_type": preferences.employment_type,
                            "employment_type_unrestricted": preferences.employment_type_unrestricted,
                            "work_mode": preferences.work_mode,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            deadline=deadline,
        )
        meaning = PreferenceMeaning.model_validate(meaning)
        conflicts = list(result.conflicts)
        conflicts.extend(
            field
            for field in meaning.conflicts
            if field
            in {"preferences.location", "preferences.employment_type", "preferences.work_mode"}
        )
        locations = LocationCondition(
            raw_text=preferences.location,
            unrestricted=preferences.location_unrestricted or meaning.locations.unrestricted,
        )
        for mode in ("included", "excluded"):
            for query in getattr(meaning.locations, mode):
                candidates = await self.catalog.lookup(query, deadline=deadline)
                if len(candidates) != 1:
                    conflicts.append("preferences.location")
                    continue
                rows: list[LocationRef] = getattr(locations, mode)
                if candidates[0].id not in {row.id for row in rows}:
                    rows.append(candidates[0])
        if meaning.locations.uncertain or any(
            within(item, excluded) for item in locations.included for excluded in locations.excluded
        ):
            conflicts.append("preferences.location")
        employment_conflict = bool(
            set(meaning.employment.included) & set(meaning.employment.excluded)
        )
        if employment_conflict:
            conflicts.append("preferences.employment_type")
        employment = EmploymentCondition(
            raw_text=preferences.employment_type,
            included=[] if employment_conflict else meaning.employment.included,
            excluded=[] if employment_conflict else meaning.employment.excluded,
            unrestricted=preferences.employment_type_unrestricted
            or meaning.employment.unrestricted,
        )
        preferences.locations = locations
        preferences.employment = employment
        work_conflict = bool(set(meaning.work_modes) & set(meaning.excluded_work_modes))
        work_uncertain = (
            meaning.work_mode_uncertain
            or work_conflict
            or bool(
                preferences.work_mode
                and not (
                    meaning.work_modes
                    or meaning.excluded_work_modes
                    or meaning.work_mode_unrestricted
                )
            )
        )
        if work_uncertain:
            conflicts.append("preferences.work_mode")
        preferences.work_arrangement = WorkArrangement(
            raw_text=preferences.work_mode,
            included=meaning.work_modes,
            excluded=meaning.excluded_work_modes,
            unrestricted=meaning.work_mode_unrestricted,
            uncertain=work_uncertain,
        )
        preferences.location_unrestricted = locations.unrestricted
        preferences.employment_type_unrestricted = employment.unrestricted
        result.conflicts = list(dict.fromkeys(conflicts))
        return result
