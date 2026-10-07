"""Offline retrieval over explicitly supplied synthetic vacancies."""

from jobscout.schemas.search import SearchRequest
from jobscout.services.job_retrieval.models import RawJob, SearchResult, SourceOutcome
from replay.dataset import ReplayDataset


class ReplaySearchService:
    def __init__(self, dataset: ReplayDataset) -> None:
        self.dataset = dataset

    async def search_many_async(
        self,
        requests: list[SearchRequest],
        *,
        timeout: float = 60.0,
    ) -> SearchResult:
        if timeout <= 0:
            raise TimeoutError("Replay retrieval deadline exhausted")
        result = SearchResult(
            warnings=["Replay demo: these are sample listings, not real job postings."]
        )
        for index, request in enumerate(requests):
            selected = []
            for row in self.dataset.jobs:
                job = row["job"]
                if job["target_direction"].casefold() != request.target_direction.casefold():
                    continue
                aliases = {"香港": "hong kong", "hongkong": "hong kong", "hk": "hong kong"}
                requested_location = (request.location or "").strip().casefold()
                actual_location = str(job["location"]).strip().casefold()
                if not request.location_unrestricted and aliases.get(
                    actual_location, actual_location
                ) != aliases.get(requested_location, requested_location):
                    continue
                if (
                    not request.employment_type_unrestricted
                    and job.get("employment_type") != request.employment_type
                ):
                    continue
                selected.append(
                    RawJob.model_validate(
                        {
                            "source": "synthetic-replay",
                            "source_url": job["source_url"],
                            "source_job_id": job["job_id"],
                            "fetched_at": job["fetched_at"],
                            "title": job["title"],
                            "company": job["company"],
                            "location": job["location"],
                            "salary": job.get("salary"),
                            "target_direction": request.target_direction,
                            "description": job["description"],
                            "posted_at": job.get("posted_at"),
                            "expiry_at": job.get("expiry_at"),
                            "employment_type": job.get("employment_type"),
                            "raw_payload": {
                                "freshness_status": job["freshness_status"],
                                "employment_type": job.get("employment_type"),
                                "description_is_excerpt": job.get("description_is_excerpt", False),
                            },
                        }
                    )
                )
                if len(selected) == 10:
                    break
            result.raw_jobs.extend(selected)
            result.outcomes.append(
                SourceOutcome(
                    request_index=index,
                    target_direction=request.target_direction,
                    source="synthetic-replay",
                    returned_count=len(selected),
                    candidate_count=len(selected),
                    status="ok" if selected else "empty",
                )
            )
        return result
