"""Map website employment labels to allowed types and keep unfamiliar text for model review."""

from collections.abc import Mapping

from jobscout.schemas.profile import EmploymentType

# Source field values, not a vocabulary for interpreting applicant messages or JDs.
_SOURCE_VALUES: Mapping[str, EmploymentType] = {
    **dict.fromkeys(
        (
            "full time",
            "fulltime",
            "fulltime permanent",
            "fulltime fixed term",
            "full time permanent",
            "permanent full time",
            "employee / full time",
            "full time (100%)",
            "vollzeit",
            "全职",
            "全職",
        ),
        "full-time",
    ),
    **dict.fromkeys(
        (
            "part time",
            "parttime",
            "parttime permanent",
            "parttime fixed term",
            "teilzeit",
            "兼职",
            "兼職",
        ),
        "part-time",
    ),
    **dict.fromkeys(("internship", "intern", "praktikum", "实习", "實習"), "internship"),
    **dict.fromkeys(("contract", "contract/temp", "合同工"), "contract"),
    **dict.fromkeys(("freelance", "自由职业"), "freelance"),
}


def source_employment_label(value: object) -> str | None:
    values = value if isinstance(value, list) else [value]
    labels = list(
        dict.fromkeys(item.strip() for item in values if isinstance(item, str) and item.strip())
    )
    if not labels:
        return None
    normalized = {
        _SOURCE_VALUES.get(" ".join(label.casefold().replace("_", " ").replace("-", " ").split()))
        for label in labels
    }
    if len(normalized) == 1 and None not in normalized:
        return next(iter(normalized))
    # Mixed or unfamiliar labels cannot become a single verified employment type.
    return "; ".join(labels)
