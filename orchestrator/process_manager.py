import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any

from orchestrator.models import CommandLease, OrchestratorCommand, WorkerResult, utc_now_iso
from orchestrator.settings import OrchestratorSettings, WorkerSettings
from orchestrator.store import OrchestratorStore
from orchestrator.event_buffer import EventBuffer

logger = logging.getLogger(__name__)

class ProcessManager:
    """Manages external worker processes."""

    def __init__(self, settings: OrchestratorSettings, store: OrchestratorStore, event_buffer: EventBuffer):
        self.settings = settings
        self.store = store
        self.event_buffer = event_buffer
        self._running: dict[str, subprocess.Popen] = {}

    def running_count(self, worker_type: str) -> int:
        """Return number of active subprocesses for a worker type."""

        return sum(1 for cmd_id in self._running if cmd_id.startswith(f"{worker_type}:"))

    def start_worker(self, command: OrchestratorCommand, lease: CommandLease, worker_settings: WorkerSettings):
        """Start a worker subprocess for a command."""

        cmd_key = f"{command.command_type}:{command.command_id}"
        
        stdout_path = self.store.logs_root / f"{command.command_id}.stdout.log"
        stderr_path = self.store.logs_root / f"{command.command_id}.stderr.log"
        result_path = self.store.logs_root / f"{command.command_id}.result.json"

        env = {
            "PYTHONPATH": self.settings.repo_root.as_posix(),
            "SPRINTER_WORKER_COMMAND_ID": command.command_id,
            "SPRINTER_WORKER_COMMAND_TYPE": command.command_type,
            "SPRINTER_WORKER_WORKFLOW_ID": command.workflow_id,
            "SPRINTER_WORKER_RESULT_PATH": result_path.as_posix(),
        }
        
        args = [worker_settings.command] + list(worker_settings.args) + ["--payload", json.dumps(command.payload)]
        
        logger.info("Spawning worker: %s", " ".join(args))
        
        process = subprocess.Popen(
            args,
            cwd=self.settings.repo_root,
            stdout=stdout_path.open("w"),
            stderr=stderr_path.open("w"),
            env={**os.environ, **env},
        )
        
        self._running[cmd_key] = process
        try:
            # In a real system we would poll this process or use a thread to monitor it.
            # For this implementation, we simulate the monitor in the next step.
            self._monitor_process(command, lease, process, worker_settings, result_path, stdout_path, stderr_path)
        finally:
            self._running.pop(cmd_key, None)

    def _monitor_process(self, command, lease, process, worker_settings, result_path, stdout_path, stderr_path):
        """Wait for process completion and emit result event."""

        returncode = -1
        error = None
        artifacts = {}

        try:
            returncode = process.wait(timeout=worker_settings.timeout_seconds)
            if result_path.exists():
                data = _read_result_file(result_path)
                success = data.get("success", False)
                artifacts = data.get("artifacts", {})
                error = data.get("error")
                if not success and not error:
                    error = "Worker reported failure without error message."
            elif returncode != 0:
                error = f"Worker exited with return code {returncode} and did not write result file."
            else:
                error = "Worker exited successfully but did not write a result file."
        except subprocess.TimeoutExpired:
            process.kill()
            returncode = -1
            error = f"Worker timed out after {worker_settings.timeout_seconds} seconds."
        except Exception as exc:
            error = f"Worker monitor failed: {exc}"

        success = returncode == 0 and error is None
        result = WorkerResult(
            command_id=command.command_id,
            workflow_id=command.workflow_id,
            command_type=command.command_type,
            success=success,
            returncode=returncode,
            started_at=lease.started_at,
            finished_at=utc_now_iso(),
            artifacts=artifacts,
            error=error,
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
        )

        if success:
            self.store.mark_command_completed(command, result.to_dict())
        else:
            self.store.mark_command_failed(command, error or f"Worker failed with return code {returncode}.")

        self.event_buffer.submit(result.to_event())

def _read_result_file(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)
