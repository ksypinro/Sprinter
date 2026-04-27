import logging
from typing import Optional

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

    def initialize(self):
        """Ensure storage is ready."""
        self.store.initialize()

    def submit_jira_created(self, workflow_id: str, issue_url: Optional[str] = None) -> str:
        event = OrchestratorEvent.new(EventType.JIRA_ISSUE_CREATED, workflow_id, {"issue_url": issue_url})
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
