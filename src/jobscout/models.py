"""Durable shared workspace records; graph checkpoints share the same SQLite file."""

from typing import Any

from tortoise import fields
from tortoise.models import Model


class SearchSession(Model):
    owner_id = fields.CharField(max_length=36, db_index=True)
    session_id = fields.CharField(max_length=36, primary_key=True)
    state: fields.JSONField[dict[str, Any]] = fields.JSONField()
    revision = fields.IntField(default=1)
    snapshot_version = fields.IntField(default=0)
    outcome = fields.CharField(max_length=16, default="running")
    mode = fields.CharField(max_length=16)
    thread_id = fields.CharField(max_length=64)
    thread_ids: fields.JSONField[list[str]] = fields.JSONField()
    created_at = fields.DatetimeField()
    updated_at = fields.DatetimeField(db_index=True)
    deleting = fields.BooleanField(default=False)

    class Meta:
        table = "workspace_sessions"
        indexes = (("owner_id", "deleting", "updated_at", "session_id"),)


class AcceptedRequest(Model):
    owner_id = fields.CharField(max_length=36, db_index=True)
    id = fields.IntField(primary_key=True)
    scope = fields.CharField(max_length=192)
    request_id = fields.CharField(max_length=128)
    fingerprint = fields.CharField(max_length=64)
    session_id = fields.CharField(max_length=36, null=True)

    class Meta:
        table = "workspace_requests"
        unique_together = (("owner_id", "scope", "request_id"),)


class WorkspaceDraft(Model):
    id = fields.IntField(primary_key=True)
    owner_id = fields.CharField(max_length=36, db_index=True)
    scope = fields.CharField(max_length=192)
    session_id = fields.CharField(max_length=36, null=True, db_index=True)
    revision = fields.IntField(default=0)
    data: fields.JSONField[dict[str, object]] = fields.JSONField()
    updated_at = fields.DatetimeField()

    class Meta:
        table = "workspace_drafts"
        unique_together = (("owner_id", "scope"),)


class SavedJob(Model):
    id = fields.IntField(primary_key=True)
    owner_id = fields.CharField(max_length=36, db_index=True)
    job_id = fields.CharField(max_length=512)
    item: fields.JSONField[dict[str, object]] = fields.JSONField()
    session_id = fields.CharField(max_length=36)
    session_revision = fields.IntField()
    saved_at = fields.DatetimeField()

    class Meta:
        table = "workspace_saved_jobs"
        unique_together = (("owner_id", "job_id"),)


class User(Model):
    user_id = fields.CharField(max_length=36, primary_key=True)
    username = fields.CharField(max_length=32, unique=True)
    password_hash = fields.TextField()


class LoginSession(Model):
    token_hash = fields.CharField(max_length=64, primary_key=True)
    owner_id = fields.CharField(max_length=36, db_index=True)
    csrf_token = fields.CharField(max_length=64)
    expires_at = fields.DatetimeField(db_index=True)


class PersonalModel(Model):
    id = fields.IntField(primary_key=True)
    owner_id = fields.CharField(max_length=36, db_index=True)
    role = fields.CharField(max_length=16)
    endpoint_id = fields.CharField(max_length=64)
    model = fields.CharField(max_length=128)
    encrypted_key = fields.TextField()
    thinking = fields.BooleanField(default=False)
    thinking_level = fields.CharField(max_length=32, default="high")

    class Meta:
        unique_together = (("owner_id", "role"),)


class DailyUsage(Model):
    id = fields.IntField(primary_key=True)
    owner_id = fields.CharField(max_length=36)
    day = fields.CharField(max_length=10)
    operations = fields.IntField(default=0)
    reserved = fields.IntField(default=0)

    class Meta:
        unique_together = (("owner_id", "day"),)


class SessionOperation(Model):
    id = fields.IntField(primary_key=True)
    operation_id = fields.CharField(max_length=36, unique=True)
    owner_id = fields.CharField(max_length=36, db_index=True)
    session_id = fields.CharField(max_length=36, db_index=True)
    request_id = fields.CharField(max_length=128)
    revision = fields.IntField()
    kind = fields.CharField(max_length=32)
    status = fields.CharField(max_length=16, default="queued")
    encrypted_input = fields.TextField(default="")
    encrypted_models = fields.TextField(default="")
    quota_day = fields.CharField(max_length=10, null=True)
    quota_status = fields.CharField(max_length=16, default="none")
    enqueued_at = fields.DatetimeField()
    expires_at = fields.DatetimeField()
    started_at = fields.DatetimeField(null=True)
    finished_at = fields.DatetimeField(null=True)

    class Meta:
        table = "session_operations"
        indexes = (("status", "id"), ("owner_id", "status"), ("status", "finished_at"))
