"""Service layer for creating Codex analysis artifacts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Protocol

from codex_analysis.prompt_builder import CodexAnalysisPromptBuilder
from codex_analysis.runner import CodexCliRunner, CodexRunnerResult
from codex_analysis.settings import CodexAnalysisSettings
from webhooks.models import WebhookEvent, utc_now_iso


class CodexRunner(Protocol):
    """Small protocol implemented by Codex analysis runners."""

    def run(self, prompt: str, repo_root: Path, analysis_path: Path, log_path: Path) -> CodexRunnerResult:
        """Run analysis and return result metadata."""


@dataclass(frozen=True)
class CodexAnalysisService:
    """Create analysis prompts, run Codex, and persist result metadata."""

    settings: CodexAnalysisSettings
    repo_root: Path
    runner: CodexRunner

    def analyze_export(self, event: WebhookEvent, export_result: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze an exported Jira issue and return stored artifact metadata."""

        issue_dir = _path_from_result(export_result, "issue_dir")
        manifest_path = _path_from_result(export_result, "manifest_path")
        if issue_dir is None and manifest_path is not None:
            issue_dir = manifest_path.parent
        if issue_dir is None:
            raise ValueError("Codex analysis requires export_result.issue_dir or export_result.manifest_path.")

        analysis_dir = issue_dir / self.settings.output_dir_name
        analysis_dir.mkdir(parents=True, exist_ok=True)
        prompt_path = analysis_dir / self.settings.prompt_file_name
        analysis_path = analysis_dir / self.settings.analysis_file_name
        log_path = analysis_dir / self.settings.log_file_name
        result_path = analysis_dir / self.settings.result_file_name

        prompt = CodexAnalysisPromptBuilder(self.repo_root).build(event, issue_dir, analysis_path)
        prompt_path.write_text(prompt, encoding="utf-8")

        started_at = utc_now_iso()
        runner_result = self.runner.run(prompt, self.repo_root, analysis_path, log_path)
        result = {
            "enabled": True,
            "status": "success",
            "issue_key": event.issue_key,
            "started_at": started_at,
            "finished_at": utc_now_iso(),
            "issue_dir": str(issue_dir),
            "manifest_path": str(manifest_path) if manifest_path else None,
            "output_dir": str(analysis_dir),
            "prompt_path": str(prompt_path),
            "analysis_path": str(analysis_path),
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


def create_codex_analysis_service(
    repo_root: Optional[Path] = None,
    env: Optional[Dict[str, str]] = None,
    runner: Optional[CodexRunner] = None,
) -> Optional[CodexAnalysisService]:
    """Create the default analysis service, or None when disabled."""

    settings = CodexAnalysisSettings.from_env(env)
    if not settings.enabled:
        return None

    resolved_root = _resolve_repo_root(Path(settings.repo_root) if settings.repo_root else repo_root)
    return CodexAnalysisService(
        settings=settings,
        repo_root=resolved_root,
        runner=runner or CodexCliRunner(settings),
    )


def _path_from_result(export_result: Dict[str, Any], *keys: str) -> Optional[Path]:
    """Return a normalized Path from export result metadata."""

    for key in keys:
        value = export_result.get(key)
        if value:
            return Path(value).expanduser()
    return None


def _resolve_repo_root(value: Optional[Path]) -> Path:
    """Resolve the workspace root used for Codex execution."""

    if value is not None:
        return value.expanduser().resolve()
    return Path(__file__).resolve().parents[1]
