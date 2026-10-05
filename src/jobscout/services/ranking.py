"""A shared, count-normalized support score; source freshness is ranked separately."""

from collections.abc import Sequence
from fractions import Fraction

from jobscout.schemas.conversation import MatchingReason

_SUPPORT = {
    "strong": Fraction(1),
    "partial": Fraction(1, 2),
    "related_experience": Fraction(1, 4),
    "not_documented": Fraction(0),
}


def evidence_score(reasons: Sequence[MatchingReason]) -> Fraction:
    if not reasons:
        return Fraction(0)
    # Averaging avoids rewarding a longer JD or more granular extraction.
    return sum((_SUPPORT[reason.level] for reason in reasons), Fraction(0)) / len(reasons)
