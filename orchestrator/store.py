import logging
import os
from pathlib import Path
from typing import Any, Optional

from orchestrator.models import (
    CommandStatus,
    EventStatus,
    OrchestratorCommand,
    OrchestratorEvent,
    WorkflowState,
    WorkflowStatus,
    safe_filename,
)
from orchestrator.jsonio import read_json, write_json_atomic

logger = logging.getLogger(__name__)

class OrchestratorStore:
    """Filesystem-based durable storage for the orchestrator."""

    def __init__(self, root: Path):
        self.root = root
        self.events_root = root / "events"
        self.commands_root = root / "commands"
        self.workflows_root = root / "workflows"
        self.logs_root = root / "logs"

    def initialize(self):
        for d in [self.events_root, self.commands_root, self.workflows_root, self.logs_root]:
            d.mkdir(parents=True, exist_ok=True)
        for s in EventStatus:
            (self.events_root / s.value).mkdir(exist_ok=True)

    def save_event(self, event: OrchestratorEvent, status: EventStatus):
        path = self.events_root / status.value / f"{safe_filename(event.event_id)}.json"
        write_json_atomic(path, event.to_dict())

    def claim_next_event(self) -> Optional[OrchestratorEvent]:
        pending_dir = self.events_root / EventStatus.PENDING.value
        paths = sorted(pending_dir.glob("*.json"))
        if not paths:
            return None
        path = paths[0]
        event = OrchestratorEvent.from_dict(read_json(path))
        target = self.events_root / EventStatus.PROCESSING.value / path.name
        os.replace(path, target)
        return event

    def mark_event_completed(self, event: OrchestratorEvent):
        source = self.events_root / EventStatus.PROCESSING.value / f"{safe_filename(event.event_id)}.json"
        target = self.events_root / EventStatus.COMPLETED.value / f"{safe_filename(event.event_id)}.json"
        if source.exists():
            os.replace(source, target)

    def mark_event_failed(self, event: OrchestratorEvent):
        source = self.events_root / EventStatus.PROCESSING.value / f"{safe_filename(event.event_id)}.json"
        target = self.events_root / EventStatus.FAILED.value / f"{safe_filename(event.event_id)}.json"
        if source.exists():
            os.replace(source, target)

    def create_workflow(self, workflow_id: str) -> WorkflowState:
        state = WorkflowState(workflow_id, WorkflowStatus.NEW)
        self.save_workflow_state(state)
        return state

    def save_workflow_state(self, state: WorkflowState):
        path = self.workflows_root / safe_filename(state.workflow_id) / "state.json"
        write_json_atomic(path, state.to_dict())

    def read_workflow_state(self, workflow_id: str) -> Optional[WorkflowState]:
        path = self.workflows_root / safe_filename(workflow_id) / "state.json"
        if not path.exists():
            return None
        return WorkflowState.from_dict(read_json(path))

    def update_workflow_status(self, workflow_id: str, status: WorkflowStatus):
        state = self.read_workflow_state(workflow_id)
        if state:
            new_state = WorkflowState(
                workflow_id=state.workflow_id,
                status=status,
                active_command_id=state.active_command_id,
                history=state.history + [f"{state.status} -> {status}"]
            )
            self.save_workflow_state(new_state)

    def enqueue_command(self, command: OrchestratorCommand):
        path = self.commands_root / safe_filename(command.command_type) / CommandStatus.PENDING.value / f"{safe_filename(command.command_id)}.json"
        write_json_atomic(path, command.to_dict())

    def list_pending_commands(self, command_type: str) -> list[OrchestratorCommand]:
        pending_dir = self.commands_root / safe_filename(command_type) / CommandStatus.PENDING.value
        if not pending_dir.exists():
            return []
        paths = sorted(pending_dir.glob("*.json"))
        return [OrchestratorCommand.from_dict(read_json(p)) for p in paths]

    def claim_command(self, command: OrchestratorCommand, timeout: int) -> Any:
        # Move from pending to running
        source = self.commands_root / safe_filename(command.command_type) / CommandStatus.PENDING.value / f"{safe_filename(command.command_id)}.json"
        target = self.commands_root / safe_filename(command.command_type) / CommandStatus.RUNNING.value / f"{safe_filename(command.command_id)}.json"
        os.replace(source, target)
        
        # Update workflow active command
        state = self.read_workflow_state(command.workflow_id)
        if state:
            new_state = WorkflowState(
                workflow_id=state.workflow_id,
                status=state.status,
                active_command_id=command.command_id,
                history=state.history
            )
            self.save_workflow_state(new_state)
        
        from orchestrator.models import CommandLease, utc_now_iso
        now = utc_now_iso()
        return CommandLease(command.command_id, command.workflow_id, now, now)

    def mark_command_completed(self, command: OrchestratorCommand, result: dict):
        source = self.commands_root / safe_filename(command.command_type) / CommandStatus.RUNNING.value / f"{safe_filename(command.command_id)}.json"
        target = self.commands_root / safe_filename(command.command_type) / CommandStatus.COMPLETED.value / f"{safe_filename(command.command_id)}.json"
        if source.exists():
            os.replace(source, target)
        
        state = self.read_workflow_state(command.workflow_id)
        if state and state.active_command_id == command.command_id:
            new_state = WorkflowState(state.workflow_id, state.status, active_command_id=None, history=state.history)
            self.save_workflow_state(new_state)

    def mark_command_failed(self, command: OrchestratorCommand, error: str):
        source = self.commands_root / safe_filename(command.command_type) / CommandStatus.RUNNING.value / f"{safe_filename(command.command_id)}.json"
        target = self.commands_root / safe_filename(command.command_type) / CommandStatus.FAILED.value / f"{safe_filename(command.command_id)}.json"
        if source.exists():
            os.replace(source, target)

        state = self.read_workflow_state(command.workflow_id)
        if state and state.active_command_id == command.command_id:
            new_state = WorkflowState(state.workflow_id, state.status, active_command_id=None, history=state.history)
            self.save_workflow_state(new_state)

    def list_workflows(self) -> list[WorkflowState]:
        states = []
        for d in self.workflows_root.iterdir():
            if d.is_dir():
                p = d / "state.json"
                if p.exists():
                    states.append(WorkflowState.from_dict(read_json(p)))
        return sorted(states, key=lambda x: x.workflow_id)
