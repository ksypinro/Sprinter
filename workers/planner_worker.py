from __future__ import annotations
from pathlib import Path
from typing import Optional

from codex_analysis.service import create_codex_analysis_service
from orchestrator.models import WorkerResult, utc_now_iso
from webhooks.models import WebhookEvent
from workers.base import WorkerRuntime, main_worker
from workers.protocols import AnalyzerFactory


def run(
    runtime: WorkerRuntime,
    analyzer_factory: AnalyzerFactory = create_codex_analysis_service,
) -> WorkerResult:
    started_at = utc_now_iso()
    analysis_service = analyzer_factory(runtime.repo_root)
    
    issue_key = runtime.command.workflow_id
    issue_dir = runtime.command.payload.get("issue_dir") or str(runtime.repo_root / "exports" / issue_key)
    manifest_path = runtime.command.payload.get("manifest_path") or str(Path(issue_dir) / "export_manifest.json")

    event = WebhookEvent(
        provider="orchestrator",
        event_id=runtime.command.command_id,
        event_type="orchestrator:analyze_issue",
        issue_key=issue_key,
        issue_url=str(runtime.command.payload.get("issue_url") or issue_key),
        actor="orchestrator",
        raw_payload=runtime.command.payload
    )
    
    if analysis_service:
        result = analysis_service.analyze_export(event, {
            "issue_key": issue_key,
            "issue_dir": issue_dir,
            "manifest_path": manifest_path,
        })
    else:
        result = {"enabled": False, "status": "skipped", "issue_key": issue_key}
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
