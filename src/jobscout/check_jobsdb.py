"""Check JobsDB search and complete descriptions from the deployment server."""

import argparse
import asyncio
import json

from jobscout.schemas.search import SearchRequest
from jobscout.services.job_search_service import JobSearchService


async def check(keyword: str, count: int) -> int:
    result = await JobSearchService(page_size=count, result_limit=count).search_many_async(
        [
            SearchRequest(
                target_direction=keyword,
                location_unrestricted=True,
                employment_type_unrestricted=True,
                sources=["jobsdb"],
            )
        ],
        timeout=60,
    )
    complete = [
        job for job in result.raw_jobs if job.description and not job.description_is_excerpt
    ]
    passed = bool(complete) and len(complete) == len(result.raw_jobs) and not result.errors
    print(
        json.dumps(
            {
                "status": "ok" if passed else "failed",
                "requested_count": count,
                "returned_count": len(result.raw_jobs),
                "complete_description_count": len(complete),
                "jobs": [
                    {
                        "source_job_id": job.source_job_id,
                        "description_characters": len(job.description or ""),
                        "description_is_excerpt": job.description_is_excerpt,
                    }
                    for job in result.raw_jobs
                ],
                "errors": [error.code for error in result.errors],
            },
            indent=2,
        )
    )
    return 0 if passed else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keyword", default="Data Analyst")
    parser.add_argument("--count", type=int, choices=range(1, 11), default=10)
    arguments = parser.parse_args()
    return asyncio.run(check(arguments.keyword, arguments.count))


if __name__ == "__main__":
    raise SystemExit(main())
