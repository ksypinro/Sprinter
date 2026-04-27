from __future__ import annotations
from typing import Optional
from JiraStreamableMCP.service import JiraStreamableService
from main import load_config
from orchestrator.models import WorkerResult, utc_now_iso
from workers.base import WorkerRuntime, main_worker

def run(runtime: WorkerRuntime) -> WorkerResult:
    started_at = utc_now_iso()
    issue_url = runtime.command.payload.get("issue_url")
    config = load_config(str(runtime.repo_root / "config.yaml"))
    if not issue_url:
        issue_key = runtime.command.workflow_id
        issue_url = f"{config['jira']['base_url'].rstrip('/')}/browse/{issue_key}"

    service = JiraStreamableService(config_path=str(runtime.repo_root / "config.yaml"))
    result = service.export_issue(str(issue_url))
    finished_at = utc_now_iso()
    
    return WorkerResult(
        command_id=runtime.command.command_id,
        workflow_id=runtime.command.workflow_id,
        command_type=runtime.command.command_type,
        success=True,
        returncode=0,
        started_at=started_at,
        finished_at=finished_at,
        artifacts=result
    )

def main(argv: Optional[list[str]] = None) -> int:
    return main_worker(run, argv)

if __name__ == "__main__":
    raise SystemExit(main())
