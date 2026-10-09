"""Explicit allowlist for the workflow's durable checkpoint values."""

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from jobscout.schemas.conversation import ConversationMessage, SearchSummary
from jobscout.schemas.errors import WorkflowError
from jobscout.schemas.execution import SearchEvent, SearchProgress
from jobscout.schemas.feedback import JobFeedback, ResultExclusion, ResultPreferences
from jobscout.schemas.job import FreshnessStatus, JobPosting, SourceDocument
from jobscout.schemas.matching import MatchDimension, MatchScore
from jobscout.schemas.notices import ApplicantNotice
from jobscout.schemas.profile import UserProfile
from jobscout.schemas.recommendation import RecommendationResult
from jobscout.schemas.search import ClarificationMessage, ClarificationStatus
from jobscout.services.job_retrieval.models import SourceOutcome


def checkpoint_serializer() -> JsonPlusSerializer:
    return JsonPlusSerializer(
        allowed_msgpack_modules=(
            UserProfile,
            ClarificationMessage,
            ClarificationStatus,
            ConversationMessage,
            SearchSummary,
            RecommendationResult,
            MatchScore,
            MatchDimension,
            JobPosting,
            FreshnessStatus,
            SourceDocument,
            WorkflowError,
            ApplicantNotice,
            SourceOutcome,
            SearchProgress,
            SearchEvent,
            JobFeedback,
            ResultExclusion,
            ResultPreferences,
        )
    )
