"""Order opportunities by overall fit, independently of requirement counts."""

from jobscout.schemas.recommendation import RecommendationItem


def recommendation_key(item: RecommendationItem) -> tuple[int, bool, str]:
    # Unknown fit stays explorable; missing information is not a negative verdict.
    fit = {"recommended": 0, "possible": 1, "unknown": 1, "unlikely": 2}
    return (
        fit[item.recommendation_fit],
        item.job.freshness_status != "active",
        item.job.job_id,
    )
