from __future__ import annotations

from typing import Optional

from github_service.pusher import GitPusherService
from orchestrator.models import WorkerResult, utc_now_iso
from workers.base import WorkerRuntime, main_worker


def run(runtime: WorkerRuntime) -> WorkerResult:
    started_at = utc_now_iso()
    result = GitPusherService.create(runtime.repo_root).create_pull_request(
        runtime.command.workflow_id,
        runtime.command.command_id,
        runtime.command.payload,
    )
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
