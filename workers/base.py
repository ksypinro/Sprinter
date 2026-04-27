from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional
import json
import logging
import os
import sys

from orchestrator.models import OrchestratorCommand, WorkerResult, utc_now_iso

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class WorkerRuntime:
    repo_root: Path
    command: OrchestratorCommand
    result_path: Path

    def write_result(self, result: WorkerResult):
        self.result_path.parent.mkdir(parents=True, exist_ok=True)
        with self.result_path.open("w", encoding="utf-8") as f:
            json.dump(result.to_dict(), f, indent=2)

def main_worker(run_func: Callable[[WorkerRuntime], WorkerResult], argv: Optional[list[str]] = None) -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--payload", help="JSON payload of the command.")
    args = parser.parse_args(argv or sys.argv[1:])

    repo_root = Path.cwd()
    command_id = os.environ.get("SPRINTER_WORKER_COMMAND_ID", "debug")
    workflow_id = os.environ.get("SPRINTER_WORKER_WORKFLOW_ID", "debug")
    result_path = Path(os.environ.get("SPRINTER_WORKER_RESULT_PATH", "result.json"))

    payload = json.loads(args.payload) if args.payload else {}
    command = OrchestratorCommand.from_dict({
        "command_id": command_id,
        "command_type": "worker",
        "workflow_id": workflow_id,
        "payload": payload,
        "created_at": utc_now_iso()
    })

    runtime = WorkerRuntime(repo_root, command, result_path)
    try:
        result = run_func(runtime)
        runtime.write_result(result)
        return 0 if result.success else 1
    except Exception as exc:
        logger.exception("Worker failed")
        now = utc_now_iso()
        result = WorkerResult(
            command_id=command.command_id,
            workflow_id=command.workflow_id,
            command_type=command.command_type,
            success=False,
            returncode=1,
            started_at=now,
            finished_at=now,
            error=str(exc)
        )
        runtime.write_result(result)
        return 1
