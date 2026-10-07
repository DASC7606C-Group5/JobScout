"""Durable shared workspace records; graph checkpoints share the same SQLite file."""

from typing import Any

from tortoise import fields
from tortoise.models import Model


class SearchSession(Model):
    session_id = fields.CharField(max_length=36, primary_key=True)
    state: fields.JSONField[dict[str, Any]] = fields.JSONField()
    revision = fields.IntField(default=1)
    outcome = fields.CharField(max_length=16, default="running")
    mode = fields.CharField(max_length=16)
    thread_id = fields.CharField(max_length=64)
    thread_ids: fields.JSONField[list[str]] = fields.JSONField()
    created_at = fields.DatetimeField()
    updated_at = fields.DatetimeField(db_index=True)
    deleting = fields.BooleanField(default=False)

    class Meta:
        table = "workspace_sessions"


class AcceptedRequest(Model):
    id = fields.IntField(primary_key=True)
    scope = fields.CharField(max_length=192)
    request_id = fields.CharField(max_length=128)
    fingerprint = fields.CharField(max_length=64)
    session_id = fields.CharField(max_length=36, null=True)

    class Meta:
        table = "workspace_requests"
        unique_together = (("scope", "request_id"),)


class WorkspaceDraft(Model):
    scope = fields.CharField(max_length=192, primary_key=True)
    session_id = fields.CharField(max_length=36, null=True, db_index=True)
    revision = fields.IntField(default=0)
    data: fields.JSONField[dict[str, object]] = fields.JSONField()
    updated_at = fields.DatetimeField()

    class Meta:
        table = "workspace_drafts"


class SavedJob(Model):
    job_id = fields.CharField(max_length=512, primary_key=True)
    item: fields.JSONField[dict[str, object]] = fields.JSONField()
    session_id = fields.CharField(max_length=36)
    session_revision = fields.IntField()
    saved_at = fields.DatetimeField()

    class Meta:
        table = "workspace_saved_jobs"


class PersonalProfileRecord(Model):
    key = fields.CharField(max_length=16, primary_key=True)
    revision = fields.IntField(default=0)
    data: fields.JSONField[dict[str, Any]] = fields.JSONField()
    updated_at = fields.DatetimeField()

    class Meta:
        table = "career_profile"


class TaskJobFeedbackRecord(Model):
    id = fields.IntField(primary_key=True)
    session_id = fields.CharField(max_length=36)
    job_id = fields.CharField(max_length=512)
    data: fields.JSONField[dict[str, Any]] = fields.JSONField()

    class Meta:
        table = "career_feedback"
        unique_together = (("session_id", "job_id"),)


class JobApplicationRecord(Model):
    job_id = fields.CharField(max_length=512, primary_key=True)
    data: fields.JSONField[dict[str, Any]] = fields.JSONField()

    class Meta:
        table = "career_applications"
