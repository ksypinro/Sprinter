import logging
import time
from typing import Optional

from orchestrator.process_manager import ProcessManager
from orchestrator.settings import OrchestratorSettings
from orchestrator.store import OrchestratorStore

logger = logging.getLogger(__name__)

class Dispatcher:
    """Polls pending commands and starts worker subprocesses."""

    def __init__(self, settings: OrchestratorSettings, store: OrchestratorStore, process_manager: ProcessManager):
        self.settings = settings
        self.store = store
        self.pm = process_manager

    def dispatch_all_workers(self, force: bool = False) -> int:
        """Attempt to dispatch pending commands for every worker type."""

        count = 0
        for worker_type in self.settings.workers:
            count += self.dispatch_worker(worker_type, force=force)
        return count

    def dispatch_worker(self, worker_type: str, force: bool = False, max_to_start: Optional[int] = None) -> int:
        """Dispatch up to 'max_to_start' pending commands for a specific worker type."""

        worker_settings = self.settings.worker(worker_type)
        if not worker_settings.enabled and not force:
            return 0

        running_count = self.pm.running_count(worker_type)
        capacity = worker_settings.instances - running_count
        if capacity <= 0:
            return 0

        to_dispatch = capacity
        if max_to_start is not None:
            to_dispatch = min(to_dispatch, max_to_start)

        pending = self.store.list_pending_commands(worker_type)
        started = 0
        for command in pending:
            if started >= to_dispatch:
                break

            if not command.is_available():
                continue

            # Check if workflow is already busy (avoid overlapping commands for same issue)
            # This is a safety check if multiple workers of different types target same issue.
            # Usually the engine handles this by only enqueuing one at a time.
            state = self.store.read_workflow_state(command.workflow_id)
            if state and state.active_command_id and state.active_command_id != command.command_id:
                # If the active command is actually running, we wait.
                # If it's a zombie, the lease monitor will eventually clean it.
                continue

            try:
                lease = self.store.claim_command(command, worker_settings.timeout_seconds)
                self.pm.start_worker(command, lease, worker_settings)
                started += 1
            except Exception:
                logger.exception("Failed to dispatch command %s", command.command_id)

        return started
