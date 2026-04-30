"""Codex CLI runner for analysis-only jobs."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

from codex_analysis.settings import CodexAnalysisSettings


DEFAULT_CODEX_COMMAND_CANDIDATES = (
    Path("/Applications/Codex.app/Contents/Resources/codex"),
    Path("/opt/homebrew/bin/codex"),
    Path("/usr/local/bin/codex"),
)


class CodexAnalysisError(RuntimeError):
    """Raised when Codex analysis cannot be completed."""


@dataclass(frozen=True)
class CodexRunnerResult:
    """Result metadata from a Codex CLI execution."""

    returncode: int
    log_path: Path
    analysis_path: Path


class CodexCliRunner:
    """Run Codex in non-interactive mode to produce an analysis Markdown file."""

    def __init__(
        self,
        settings: CodexAnalysisSettings,
        command_candidates: Optional[Sequence[Path]] = None,
    ):
        """Initialize the runner."""

        self.settings = settings
        self.command_candidates = tuple(command_candidates or DEFAULT_CODEX_COMMAND_CANDIDATES)

    def run(self, prompt: str, repo_root: Path, analysis_path: Path, log_path: Path) -> CodexRunnerResult:
        """Run Codex and write command output to the log file."""

        analysis_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        command = self._build_command(repo_root, analysis_path)

        try:
            completed = subprocess.run(
                command,
                input=prompt,
                text=True,
                capture_output=True,
                timeout=self.settings.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            log_path.write_text(
                f"Codex analysis timed out after {self.settings.timeout_seconds} seconds.\n",
                encoding="utf-8",
            )
            raise CodexAnalysisError(f"Codex analysis timed out after {self.settings.timeout_seconds} seconds.") from exc
        except OSError as exc:
            log_path.write_text(
                "\n".join(
                    [
                        f"Could not start Codex command: {exc}",
                        f"Configured command: {self.settings.command}",
                        f"Resolved command: {command[0]}",
                        f"PATH: {os.environ.get('PATH', '')}",
                        "Hint: set SPRINTER_CODEX_ANALYSIS_COMMAND to the absolute Codex CLI path if needed.",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            raise CodexAnalysisError(f"Could not start Codex command: {exc}") from exc

        log_path.write_text(
            "\n".join(
                [
                    f"COMMAND: {shlex.join(command)}",
                    "",
                    "STDOUT:",
                    completed.stdout,
                    "",
                    "STDERR:",
                    completed.stderr,
                    "",
                ]
            ),
            encoding="utf-8",
        )

        if completed.returncode != 0:
            raise CodexAnalysisError(f"Codex analysis failed with exit code {completed.returncode}.")

        if not analysis_path.exists() or not analysis_path.read_text(encoding="utf-8").strip():
            raise CodexAnalysisError(f"Codex did not create analysis output: {analysis_path}")

        return CodexRunnerResult(completed.returncode, log_path, analysis_path)

    def _build_command(self, repo_root: Path, analysis_path: Path) -> list[str]:
        """Build the non-interactive Codex command."""

        command = [
            self._resolve_command(),
            "exec",
            "--cd",
            str(repo_root),
            "--sandbox",
            self.settings.sandbox,
            "--output-last-message",
            str(analysis_path),
        ]
        if self.settings.json_output:
            command.append("--json")
        if self.settings.model:
            command.extend(["--model", self.settings.model])
        if self.settings.profile:
            command.extend(["--profile", self.settings.profile])
        return command

    def _resolve_command(self) -> str:
        """Resolve the configured Codex command for service-style environments."""

        configured = self.settings.command
        if self._contains_path_separator(configured):
            return configured

        path_match = shutil.which(configured)
        if path_match:
            return path_match

        for candidate in self.command_candidates:
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate)

        return configured

    @staticmethod
    def _contains_path_separator(command: str) -> bool:
        """Return whether a command already includes a filesystem path."""

        return os.sep in command or bool(os.altsep and os.altsep in command)
