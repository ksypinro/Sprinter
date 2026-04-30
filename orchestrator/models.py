from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
import uuid
from enum import Enum
from typing import Any, Optional

def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def safe_filename(name: str) -> str:
    return name.replace("/", "_").replace(":", "_").replace("\\", "_")

class EventType(str, Enum):
    JIRA_ISSUE_CREATED = "jira.issue.created"
    GITHUB_PR_OPENED = "github.pull_request.opened"
    GITHUB_PR_SYNCHRONIZE = "github.pull_request.synchronize"
    GITHUB_PR_REOPENED = "github.pull_request.reopened"
    GITHUB_PR_REVIEW_COMMENT = "github.pull_request_review_comment.created"
    GITHUB_PUSH_MAIN = "github.push.main"
    RETRY_REQUESTED = "retry_requested"
    PAUSE_REQUESTED = "pause_requested"
    RESUME_REQUESTED = "resume_requested"
    WORKER_COMMAND_SUCCEEDED = "worker.command_succeeded"
    WORKER_COMMAND_FAILED = "worker.command_failed"

class EventStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

class CommandStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"

class WorkflowStatus(str, Enum):
    NEW = "new"
    EXPORT_REQUESTED = "export_requested"
    EXPORT_RUNNING = "export_running"
    ISSUE_EXPORTED = "issue_exported"
    ANALYSIS_REQUESTED = "analysis_requested"
    ANALYSIS_RUNNING = "analysis_running"
    ANALYSIS_COMPLETED = "analysis_completed"
    EXECUTION_REQUESTED = "execution_requested"
    EXECUTION_RUNNING = "execution_running"
    EXECUTION_COMPLETED = "execution_completed"
    PR_REQUESTED = "pr_requested"
    PR_RUNNING = "pr_running"
    PR_COMPLETED = "pr_completed"
    REVIEW_REQUESTED = "review_requested"
    REVIEW_RUNNING = "review_running"
    REVIEW_COMPLETED = "review_completed"
    BLOCKED = "blocked"
    PAUSED = "paused"

@dataclass(frozen=True)
class OrchestratorEvent:
    event_id: str
    event_type: EventType
    workflow_id: str
    payload: dict[str, Any] = field(default_factory=dict)
    received_at: str = field(default_factory=utc_now_iso)

    @classmethod
    def new(cls, event_type: EventType | str, workflow_id: str, payload: dict[str, Any] = None) -> OrchestratorEvent:
        return cls(
            event_id=str(uuid.uuid4()),
            event_type=EventType(event_type),
            workflow_id=workflow_id,
            payload=payload or {}
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "workflow_id": self.workflow_id,
            "payload": self.payload,
            "received_at": self.received_at
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OrchestratorEvent:
        return cls(
            event_id=data["event_id"],
            event_type=EventType(data["event_type"]),
            workflow_id=data["workflow_id"],
            payload=data.get("payload", {}),
            received_at=data["received_at"]
        )

@dataclass(frozen=True)
class OrchestratorCommand:
    command_id: str
    command_type: str
    workflow_id: str
    payload: dict[str, Any] = field(default_factory=dict)
    attempt: int = 1
    max_attempts: int = 3
    retry_of: Optional[str] = None
    created_at: str = field(default_factory=utc_now_iso)
    available_at: str = field(default_factory=utc_now_iso)
    caused_by_event_id: Optional[str] = None

    @classmethod
    def new(cls, command_type: str, workflow_id: str, payload: dict[str, Any] = None, **kwargs) -> OrchestratorCommand:
        return cls(
            command_id=str(uuid.uuid4()),
            command_type=command_type,
            workflow_id=workflow_id,
            payload=payload or {},
            **kwargs
        )

    def is_available(self) -> bool:
        return utc_now_iso() >= self.available_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "command_id": self.command_id,
            "command_type": self.command_type,
            "workflow_id": self.workflow_id,
            "payload": self.payload,
            "attempt": self.attempt,
            "max_attempts": self.max_attempts,
            "retry_of": self.retry_of,
            "created_at": self.created_at,
            "available_at": self.available_at,
            "caused_by_event_id": self.caused_by_event_id
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OrchestratorCommand:
        return cls(
            command_id=data["command_id"],
            command_type=data["command_type"],
            workflow_id=data["workflow_id"],
            payload=data.get("payload", {}),
            attempt=data.get("attempt", 1),
            max_attempts=data.get("max_attempts", 3),
            retry_of=data.get("retry_of"),
            created_at=data["created_at"],
            available_at=data.get("available_at", data["created_at"]),
            caused_by_event_id=data.get("caused_by_event_id")
        )

@dataclass(frozen=True)
class WorkflowState:
    workflow_id: str
    status: WorkflowStatus
    updated_at: str = field(default_factory=utc_now_iso)
    active_command_id: Optional[str] = None
    history: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "status": self.status.value,
            "updated_at": self.updated_at,
            "active_command_id": self.active_command_id,
            "history": self.history
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkflowState:
        return cls(
            workflow_id=data["workflow_id"],
            status=WorkflowStatus(data["status"]),
            updated_at=data["updated_at"],
            active_command_id=data.get("active_command_id"),
            history=data.get("history", [])
        )

@dataclass(frozen=True)
class CommandLease:
    command_id: str
    workflow_id: str
    started_at: str
    expires_at: str

    def is_expired(self) -> bool:
        return utc_now_iso() >= self.expires_at

@dataclass(frozen=True)
class WorkerResult:
    command_id: str
    workflow_id: str
    command_type: str
    success: bool
    returncode: int
    started_at: str
    finished_at: str
    artifacts: dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    stdout_path: Optional[str] = None
    stderr_path: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "command_id": self.command_id,
            "workflow_id": self.workflow_id,
            "command_type": self.command_type,
            "success": self.success,
            "returncode": self.returncode,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "artifacts": self.artifacts,
            "error": self.error,
            "stdout_path": self.stdout_path,
            "stderr_path": self.stderr_path,
        }

    def to_event(self) -> OrchestratorEvent:
        return OrchestratorEvent.new(
            event_type=EventType.WORKER_COMMAND_SUCCEEDED if self.success else EventType.WORKER_COMMAND_FAILED,
            workflow_id=self.workflow_id,
            payload={
                "command_id": self.command_id,
                "command_type": self.command_type,
                "success": self.success,
                "error": self.error,
                "artifacts": self.artifacts
            }
        )

@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int
    backoff_seconds: tuple[int, ...]

    def should_retry(self, attempt: int) -> bool:
        return attempt < self.max_attempts

    def next_attempt(self, current: int) -> int:
        return current + 1

    def delay_for_attempt(self, attempt: int) -> int:
        idx = min(attempt - 1, len(self.backoff_seconds) - 1)
        return self.backoff_seconds[idx]
