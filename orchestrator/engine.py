import logging
from typing import Optional

from orchestrator.models import (
    CommandStatus,
    EventStatus,
    EventType,
    OrchestratorCommand,
    OrchestratorEvent,
    WorkflowStatus,
)
from orchestrator.retry import RetryManager
from orchestrator.settings import OrchestratorSettings
from orchestrator.store import OrchestratorStore

logger = logging.getLogger(__name__)

class WorkflowEngine:
    """Processes events and advances workflow state."""

    def __init__(self, settings: OrchestratorSettings, store: OrchestratorStore):
        self.settings = settings
        self.store = store
        self.retry_manager = RetryManager(settings)

    def process_event(self, event: OrchestratorEvent) -> bool:
        """Apply event logic to target workflow and return True if processed."""

        workflow_id = event.workflow_id
        if not workflow_id:
            logger.warning("Event missing workflow_id: %s", event.event_id)
            return False

        state = self.store.read_workflow_state(workflow_id)
        if not state:
            if event.event_type == EventType.JIRA_ISSUE_CREATED:
                state = self.store.create_workflow(workflow_id)
            else:
                logger.warning("Event for unknown workflow: %s", workflow_id)
                return False

        if state.status == WorkflowStatus.PAUSED and event.event_type != EventType.RESUME_REQUESTED:
            logger.debug("Skipping event for paused workflow: %s", workflow_id)
            return False

        try:
            self._handle_event(event, state)
            return True
        except Exception:
            logger.exception("Failed to handle event %s for workflow %s", event.event_id, workflow_id)
            return False

    def _handle_event(self, event: OrchestratorEvent, state):
        """Internal event routing."""

        et = event.event_type

        # 1. State Transitions
        if et == EventType.JIRA_ISSUE_CREATED:
            if self.settings.safety.auto_export_after_issue_created:
                self._request_export(event, state)

        elif et == EventType.RETRY_REQUESTED:
            self._handle_manual_retry(event, state)

        elif et == EventType.PAUSE_REQUESTED:
            self.store.update_workflow_status(state.workflow_id, WorkflowStatus.PAUSED)

        elif et == EventType.RESUME_REQUESTED:
            self.store.update_workflow_status(state.workflow_id, WorkflowStatus.NEW)

        elif et == EventType.WORKER_COMMAND_SUCCEEDED:
            self._handle_worker_success(event, state)

        elif et == EventType.WORKER_COMMAND_FAILED:
            self._handle_worker_failure(event, state)

    def _request_export(self, event: OrchestratorEvent, state):
        command = OrchestratorCommand.new(
            command_type="export_jira_issue",
            workflow_id=state.workflow_id,
            payload={"issue_url": event.payload.get("issue_url")},
            caused_by_event_id=event.event_id,
        )
        self.store.enqueue_command(command)
        self.store.update_workflow_status(state.workflow_id, WorkflowStatus.EXPORT_REQUESTED)

    def _handle_worker_success(self, event: OrchestratorEvent, state):
        cmd_type = event.payload.get("command_type")
        if cmd_type == "export_jira_issue":
            self.store.update_workflow_status(state.workflow_id, WorkflowStatus.ISSUE_EXPORTED)
            if self.settings.safety.auto_analyze_after_export:
                self._request_analysis(event, state)
        elif cmd_type == "analyze_issue":
            self.store.update_workflow_status(state.workflow_id, WorkflowStatus.ANALYSIS_COMPLETED)
            # auto-execute is usually false by default

    def _request_analysis(self, event: OrchestratorEvent, state):
        command = OrchestratorCommand.new(
            command_type="analyze_issue",
            workflow_id=state.workflow_id,
            payload={},
            caused_by_event_id=event.event_id,
        )
        self.store.enqueue_command(command)
        self.store.update_workflow_status(state.workflow_id, WorkflowStatus.ANALYSIS_REQUESTED)

    def _handle_worker_failure(self, event: OrchestratorEvent, state):
        command_id = event.payload.get("command_id")
        if not command_id:
            return

        command_dict = self.store.read_command(event.payload.get("command_type", ""), command_id, CommandStatus.FAILED)
        if not command_dict:
            return
        
        command = OrchestratorCommand.from_dict(command_dict)
        decision = self.retry_manager.decide(command, event.received_at)

        if decision.should_retry:
            retry_cmd = self.retry_manager.build_retry_command(command, event)
            self.store.enqueue_command(retry_cmd)
        else:
            self.store.update_workflow_status(state.workflow_id, WorkflowStatus.BLOCKED)

    def _handle_manual_retry(self, event: OrchestratorEvent, state):
        # Force retry of the last failed command if any
        if state.status == WorkflowStatus.BLOCKED:
            # Finding the last failed command is complex in current store,
            # for now we just reset status to allow manual trigger.
            self.store.update_workflow_status(state.workflow_id, WorkflowStatus.NEW)
