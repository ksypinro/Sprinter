"""Service layer for implementing Codex analysis plans."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Protocol

from codex_implementer.prompt_builder import CodexImplementerPromptBuilder
from codex_implementer.runner import CodexCliImplementerRunner, CodexImplementerRunnerResult
from codex_implementer.settings import CodexImplementerSettings
from orchestrator.models import utc_now_iso


class ImplementerRunner(Protocol):
    """Small protocol implemented by Codex implementer runners."""

    def run(self, prompt: str, repo_root: Path, output_path: Path, log_path: Path) -> CodexImplementerRunnerResult:
        """Run implementation and return result metadata."""


@dataclass(frozen=True)
class CodexImplementerService:
    """Read an analysis plan, run Codex, and persist implementation metadata."""

    settings: CodexImplementerSettings
    repo_root: Path
    runner: ImplementerRunner

    def implement_plan(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Implement a Codex analysis plan and return stored artifact metadata."""

        analysis_path = self._resolve_analysis_path(payload)
        issue_dir = self._resolve_issue_dir(payload, analysis_path)
        output_dir = issue_dir / self.settings.output_dir_name
        output_dir.mkdir(parents=True, exist_ok=True)

        prompt_path = output_dir / self.settings.prompt_file_name
        output_path = output_dir / self.settings.output_file_name
        log_path = output_dir / self.settings.log_file_name
        result_path = output_dir / self.settings.result_file_name
        commit_log_path = output_dir / self.settings.commit_log_file_name

        prompt = CodexImplementerPromptBuilder(self.repo_root).build(analysis_path, commit_log_path, output_path)
        prompt_path.write_text(prompt, encoding="utf-8")

        started_at = utc_now_iso()
        runner_result = self.runner.run(prompt, self.repo_root, output_path, log_path)

        if not commit_log_path.exists() or not commit_log_path.read_text(encoding="utf-8").strip():
            raise ValueError(f"Codex implementer did not write commit log: {commit_log_path}")

        result = {
            "enabled": True,
            "status": "success",
            "started_at": started_at,
            "finished_at": utc_now_iso(),
            "analysis_path": str(analysis_path),
            "issue_dir": str(issue_dir),
            "output_dir": str(output_dir),
            "prompt_path": str(prompt_path),
            "output_path": str(output_path),
            "commit_log_path": str(commit_log_path),
            "log_path": str(log_path),
            "result_path": str(result_path),
            "codex": {
                "command": self.settings.command,
                "sandbox": self.settings.sandbox,
                "json": self.settings.json_output,
                "model": self.settings.model,
                "profile": self.settings.profile,
                "returncode": runner_result.returncode,
            },
        }
        result_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        return result

    def _resolve_analysis_path(self, payload: Dict[str, Any]) -> Path:
        """Resolve the analysis_and_plan.md path from command payload."""

        direct = payload.get("analysis_path")
        if direct:
            path = Path(direct).expanduser()
            if path.exists():
                return path
            raise ValueError(f"Analysis plan not found: {path}")

        issue_dir = payload.get("issue_dir")
        if issue_dir:
            path = Path(issue_dir).expanduser() / "codex_analysis" / "analysis_and_plan.md"
            if path.exists():
                return path

        raise ValueError("Codex implementer requires payload.analysis_path or payload.issue_dir.")

    def _resolve_issue_dir(self, payload: Dict[str, Any], analysis_path: Path) -> Path:
        """Resolve the issue export directory for implementer artifacts."""

        issue_dir = payload.get("issue_dir")
        if issue_dir:
            return Path(issue_dir).expanduser()

        if analysis_path.parent.name == "codex_analysis":
            return analysis_path.parent.parent
        return analysis_path.parent


def create_codex_implementer_service(
    repo_root: Optional[Path] = None,
    env: Optional[Dict[str, str]] = None,
    runner: Optional[ImplementerRunner] = None,
) -> Optional[CodexImplementerService]:
    """Create the default implementer service, or None when disabled."""

    settings = CodexImplementerSettings.from_env(env)
    if not settings.enabled:
        return None

    resolved_root = _resolve_repo_root(Path(settings.repo_root) if settings.repo_root else repo_root)
    return CodexImplementerService(
        settings=settings,
        repo_root=resolved_root,
        runner=runner or CodexCliImplementerRunner(settings),
    )


def _resolve_repo_root(value: Optional[Path]) -> Path:
    """Resolve the workspace root used for Codex execution."""

    if value is not None:
        return value.expanduser().resolve()
    return Path(__file__).resolve().parents[1]
