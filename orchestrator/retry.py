from __future__ import annotations
from dataclasses import dataclass
from datetime import timedelta
import logging
from orchestrator.models import OrchestratorCommand, OrchestratorEvent, RetryPolicy, utc_now_iso
from orchestrator.settings import OrchestratorSettings

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class RetryDecision:
    should_retry: bool
    next_attempt: int | None
    available_at: str | None
    reason: str

class RetryManager:
    def __init__(self, settings: OrchestratorSettings):
        self.settings = settings
        self.default_policy = RetryPolicy(
            max_attempts=settings.default_max_attempts,
            backoff_seconds=settings.default_retry_backoff_seconds,
        )

    def for_command(self, command: OrchestratorCommand) -> RetryPolicy:
        worker = self.settings.workers.get(command.command_type)
        if not worker:
            return self.default_policy
        return RetryPolicy(
            max_attempts=worker.max_attempts,
            backoff_seconds=self.settings.default_retry_backoff_seconds,
        )

    def decide(self, command: OrchestratorCommand, failed_at: str | None = None) -> RetryDecision:
        policy = self.for_command(command)
        if not policy.should_retry(command.attempt):
            return RetryDecision(False, None, None, "max attempts exhausted")

        next_attempt = policy.next_attempt(command.attempt)
        delay = policy.delay_for_attempt(command.attempt)
        available_at = _iso_plus_seconds(failed_at or utc_now_iso(), delay)
        return RetryDecision(True, next_attempt, available_at, "retry scheduled")

    def build_retry_command(self, command: OrchestratorCommand, failed_event: OrchestratorEvent) -> OrchestratorCommand:
        decision = self.decide(command, failed_event.received_at)
        if not decision.should_retry or decision.next_attempt is None or decision.available_at is None:
            raise ValueError("Retry not allowed")
        return OrchestratorCommand.new(
            command_type=command.command_type,
            workflow_id=command.workflow_id,
            payload=command.payload,
            caused_by_event_id=failed_event.event_id,
            attempt=decision.next_attempt,
            max_attempts=command.max_attempts,
            retry_of=command.command_id,
            available_at=decision.available_at,
        )

def _iso_plus_seconds(value: str, seconds: int) -> str:
    from datetime import datetime
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return (parsed + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")
