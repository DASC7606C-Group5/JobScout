"""Order opportunities by overall fit, independently of requirement counts."""

from jobscout.schemas.recommendation import RecommendationItem

MIN_RANKING_COVERAGE = 60


def recommendation_key(item: RecommendationItem) -> tuple[int, bool, int, int, bool, str]:
    # Unknown fit stays explorable; missing information is not a negative verdict.
    fit = {"recommended": 0, "possible": 1, "unknown": 1, "unlikely": 2}
    score = item.match_score
    reliable = (
        score is not None
        and score.total is not None
        and score.coverage >= MIN_RANKING_COVERAGE
        and item.analysis_status == "complete"
    )
    return (
        fit[item.recommendation_fit],
        not reliable,
        -(score.total or 0) if reliable and score else 0,
        -score.coverage if score else 0,
        item.job.freshness_status != "active",
        item.job.job_id,
    )
