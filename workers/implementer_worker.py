from __future__ import annotations

from typing import Optional

from codex_implementer.service import create_codex_implementer_service
from orchestrator.models import WorkerResult, utc_now_iso
from workers.base import WorkerRuntime, main_worker
from workers.protocols import ImplementerFactory


def run(
    runtime: WorkerRuntime,
    implementer_factory: ImplementerFactory = create_codex_implementer_service,
) -> WorkerResult:
    started_at = utc_now_iso()
    implementer_service = implementer_factory(runtime.repo_root)

    if implementer_service:
        result = implementer_service.implement_plan(runtime.command.payload)
    else:
        result = {
            "enabled": False,
            "status": "skipped",
            "analysis_path": runtime.command.payload.get("analysis_path"),
        }

    finished_at = utc_now_iso()
    return WorkerResult(
        command_id=runtime.command.command_id,
        workflow_id=runtime.command.workflow_id,
        command_type=runtime.command.command_type,
        success=True,
        returncode=0,
        started_at=started_at,
        finished_at=finished_at,
        artifacts=result,
    )


def main(argv: Optional[list[str]] = None) -> int:
    return main_worker(run, argv)


if __name__ == "__main__":
    raise SystemExit(main())
