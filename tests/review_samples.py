"""Encode hand-authored test comparisons using the model's short quotation IDs."""

from typing import Any


def wire_review(row: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    result = dict(row)
    result.setdefault("recommendation_fit", "possible")
    result.setdefault("recommendation_reason", "The supplied experience is relevant to this role.")
    result["matches"] = []
    for match in row.get("matches", []):
        result["matches"].append(
            {
                key: value
                for key, value in match.items()
                if key
                not in {
                    "profile_source_quotes",
                    "experience_source_quotes",
                    "experience_fact_ids",
                    "qualifications",
                }
            }
        )
        comparison = result["matches"][-1]
        comparison.setdefault(
            "explanation", "The supplied background was compared with this requirement."
        )
        comparison.setdefault(
            "profile_quote_ids",
            [
                next(
                    (
                        key
                        for key, text in payload["profile_quotes"].items()
                        if quote["excerpt"] in text
                    ),
                    "missing",
                )
                for quote in match.get("profile_source_quotes", [])
            ],
        )
    result["dimensions"] = [
        {
            key: value
            for key, value in row.items()
            if key not in {"profile_source_quotes", "job_source_quotes", "profile_fact_ids"}
        }
        for row in row.get("dimensions", [])
    ]
    result["preparation_suggestions"] = [
        suggestion["suggestion"] if isinstance(suggestion, dict) else suggestion
        for suggestion in row.get("preparation_suggestions", [])
    ][:2]
    return result
