"""Explicit allowlist for the workflow's durable checkpoint values."""

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from jobscout.schemas.conversation import ConversationMessage, SearchSummary
from jobscout.schemas.errors import WorkflowError
from jobscout.schemas.job import FreshnessStatus, JobPosting, SourceDocument
from jobscout.schemas.notices import ApplicantNotice
from jobscout.schemas.profile import UserProfile
from jobscout.schemas.recommendation import RecommendationResult
from jobscout.schemas.search import ClarificationMessage, ClarificationStatus, SearchRequest
from jobscout.services.job_retrieval.models import SourceOutcome


def checkpoint_serializer() -> JsonPlusSerializer:
    return JsonPlusSerializer(
        allowed_msgpack_modules=(
            UserProfile,
            ClarificationMessage,
            ClarificationStatus,
            SearchRequest,
            ConversationMessage,
            SearchSummary,
            RecommendationResult,
            JobPosting,
            FreshnessStatus,
            SourceDocument,
            WorkflowError,
            ApplicantNotice,
            SourceOutcome,
        )
    )
