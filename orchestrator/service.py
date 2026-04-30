import logging
from typing import Any, Optional

from orchestrator.dispatcher import Dispatcher
from orchestrator.engine import WorkflowEngine
from orchestrator.event_buffer import EventBuffer
from orchestrator.models import EventType, OrchestratorEvent, WorkflowState, WorkflowStatus
from orchestrator.process_manager import ProcessManager
from orchestrator.settings import OrchestratorSettings
from orchestrator.store import OrchestratorStore

logger = logging.getLogger(__name__)

class OrchestratorService:
    """The public API for the orchestrator."""

    def __init__(self, settings: OrchestratorSettings):
        self.settings = settings
        self.store = OrchestratorStore(settings.storage_root)
        self.event_buffer = EventBuffer(self.store)
        self.engine = WorkflowEngine(settings, self.store)
        self.pm = ProcessManager(settings, self.store, self.event_buffer)
        self.dispatcher = Dispatcher(settings, self.store, self.pm)
        self.webhook_manager = None

    def initialize(self, start_webhooks: Optional[bool] = None):
        """Ensure storage is ready."""
        self.store.initialize()
        should_start_webhooks = self.settings.webhook_servers.auto_start if start_webhooks is None else start_webhooks
        if should_start_webhooks:
            self.start_webhooks()

    def start_webhooks(self) -> None:
        """Start orchestrator-owned webhook servers if configured."""

        if self.webhook_manager is None:
            from orchestrator.webhook_manager import WebhookServerManager

            self.webhook_manager = WebhookServerManager(self.settings, self)
        self.webhook_manager.start()

    def shutdown(self) -> None:
        """Stop orchestrator-owned background services."""

        if self.webhook_manager is not None:
            self.webhook_manager.stop()

    def submit_jira_created(self, workflow_id: str, issue_url: Optional[str] = None) -> str:
        event = OrchestratorEvent.new(EventType.JIRA_ISSUE_CREATED, workflow_id, {"issue_url": issue_url})
        return self.event_buffer.submit(event)

    def submit_jira_webhook(self, webhook_event: Any) -> str:
        """Submit a normalized Jira webhook as an orchestrator trigger."""

        payload = {
            "issue_url": webhook_event.issue_url,
            "provider": webhook_event.provider,
            "webhook_event_id": webhook_event.event_id,
            "webhook_event_type": webhook_event.event_type,
            "project_key": webhook_event.project_key,
            "actor": webhook_event.actor,
            "received_at": webhook_event.received_at,
        }
        event = OrchestratorEvent.new(EventType.JIRA_ISSUE_CREATED, webhook_event.issue_key, payload)
        return self.event_buffer.submit(event)

    def submit_event(self, event: OrchestratorEvent) -> str:
        return self.event_buffer.submit(event)

    def retry_workflow(self, workflow_id: str):
        event = OrchestratorEvent.new(EventType.RETRY_REQUESTED, workflow_id)
        self.event_buffer.submit(event)

    def pause_workflow(self, workflow_id: str):
        event = OrchestratorEvent.new(EventType.PAUSE_REQUESTED, workflow_id)
        self.event_buffer.submit(event)

    def resume_workflow(self, workflow_id: str):
        event = OrchestratorEvent.new(EventType.RESUME_REQUESTED, workflow_id)
        self.event_buffer.submit(event)

    def get_workflow_state(self, workflow_id: str) -> Optional[WorkflowState]:
        return self.store.read_workflow_state(workflow_id)

    def process_pending_events(self, limit: int = 10) -> int:
        count = 0
        for _ in range(limit):
            event = self.event_buffer.poll()
            if not event:
                break
            if self.engine.process_event(event):
                self.store.mark_event_completed(event)
                count += 1
            else:
                self.store.mark_event_failed(event)
        return count
