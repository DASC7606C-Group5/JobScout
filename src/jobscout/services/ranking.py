"""Order opportunities by overall fit, independently of requirement counts."""

from jobscout.schemas.recommendation import RecommendationItem
from jobscout.services.matching_score import MIN_TOTAL_ASSESSED_PERCENTAGE


def recommendation_key(item: RecommendationItem) -> tuple[int, bool, int, bool, str]:
    # Unknown fit stays explorable; missing information is not a negative verdict.
    fit = {"recommended": 0, "possible": 1, "unknown": 2, "unlikely": 3}
    score = item.match_score
    reliable = (
        score is not None
        and score.total is not None
        and score.assessed_percentage >= MIN_TOTAL_ASSESSED_PERCENTAGE
        and item.analysis_status != "unavailable"
    )
    return (
        fit[item.recommendation_fit],
        not reliable,
        -(score.total or 0) if reliable and score else 0,
        item.job.freshness_status != "active",
        item.job.job_id,
    )
