"""Shared webhook data models.

The webhook server normalizes provider-specific request payloads into these
small objects before storage or export work begins. That keeps the HTTP layer,
filesystem store, and worker from depending on Jira's raw JSON shape.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional


def utc_now_iso() -> str:
    """Return an ISO-8601 UTC timestamp."""

    return datetime.now(timezone.utc).isoformat()


class JobStatus(str, Enum):
    """Lifecycle states for webhook-triggered export jobs."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    IGNORED = "ignored"


class WebhookParseError(ValueError):
    """Raised when a webhook payload cannot be normalized."""


@dataclass(frozen=True)
class WebhookEvent:
    """Normalized event extracted from a provider webhook payload."""

    provider: str
    event_id: str
    event_type: str
    issue_key: str
    issue_url: str
    project_key: Optional[str] = None
    actor: Optional[str] = None
    received_at: str = field(default_factory=utc_now_iso)
    raw_payload: Dict[str, Any] = field(default_factory=dict)

    def dedupe_key(self) -> str:
        """Return the stable key used to suppress duplicate deliveries."""

        return f"{self.provider}:{self.event_id}"

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the event for filesystem storage."""

        return {
            "provider": self.provider,
            "event_id": self.event_id,
            "event_type": self.event_type,
            "issue_key": self.issue_key,
            "issue_url": self.issue_url,
            "project_key": self.project_key,
            "actor": self.actor,
            "received_at": self.received_at,
            "raw_payload": self.raw_payload,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WebhookEvent":
        """Restore an event from stored JSON data."""

        return cls(
            provider=data["provider"],
            event_id=data["event_id"],
            event_type=data["event_type"],
            issue_key=data["issue_key"],
            issue_url=data["issue_url"],
            project_key=data.get("project_key"),
            actor=data.get("actor"),
            received_at=data.get("received_at") or utc_now_iso(),
            raw_payload=data.get("raw_payload") or {},
        )


@dataclass(frozen=True)
class WebhookDecision:
    """Decision made after event parsing and filtering."""

    accepted: bool
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the decision for event audit records."""

        return {"accepted": self.accepted, "reason": self.reason}


@dataclass
class WebhookJob:
    """Filesystem-backed job created from an accepted webhook event."""

    job_id: str
    event: WebhookEvent
    status: JobStatus = JobStatus.QUEUED
    queued_at: str = field(default_factory=utc_now_iso)
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    attempts: int = 0
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the job for filesystem storage."""

        return {
            "job_id": self.job_id,
            "event": self.event.to_dict(),
            "status": self.status.value,
            "queued_at": self.queued_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "attempts": self.attempts,
            "result": self.result,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WebhookJob":
        """Restore a job from stored JSON data."""

        return cls(
            job_id=data["job_id"],
            event=WebhookEvent.from_dict(data["event"]),
            status=JobStatus(data.get("status", JobStatus.QUEUED.value)),
            queued_at=data.get("queued_at") or utc_now_iso(),
            started_at=data.get("started_at"),
            finished_at=data.get("finished_at"),
            attempts=int(data.get("attempts", 0)),
            result=data.get("result"),
            error=data.get("error"),
        )
