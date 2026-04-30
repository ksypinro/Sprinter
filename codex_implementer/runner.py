"""Codex CLI runner for implementation jobs."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

from codex_implementer.settings import CodexImplementerSettings


DEFAULT_CODEX_COMMAND_CANDIDATES = (
    Path("/Applications/Codex.app/Contents/Resources/codex"),
    Path("/opt/homebrew/bin/codex"),
    Path("/usr/local/bin/codex"),
)


class CodexImplementerError(RuntimeError):
    """Raised when Codex implementation cannot be completed."""


@dataclass(frozen=True)
class CodexImplementerRunnerResult:
    """Result metadata from a Codex implementer CLI execution."""

    returncode: int
    log_path: Path
    output_path: Path


class CodexCliImplementerRunner:
    """Run Codex in workspace-write mode to implement an analysis plan."""

    def __init__(
        self,
        settings: CodexImplementerSettings,
        command_candidates: Optional[Sequence[Path]] = None,
    ):
        """Initialize the runner."""

        self.settings = settings
        self.command_candidates = tuple(command_candidates or DEFAULT_CODEX_COMMAND_CANDIDATES)

    def run(self, prompt: str, repo_root: Path, output_path: Path, log_path: Path) -> CodexImplementerRunnerResult:
        """Run Codex and write command output to the log file."""

        output_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        command = self._build_command(repo_root, output_path)

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
                f"Codex implementer timed out after {self.settings.timeout_seconds} seconds.\n",
                encoding="utf-8",
            )
            raise CodexImplementerError(
                f"Codex implementer timed out after {self.settings.timeout_seconds} seconds."
            ) from exc
        except OSError as exc:
            log_path.write_text(
                "\n".join(
                    [
                        f"Could not start Codex command: {exc}",
                        f"Configured command: {self.settings.command}",
                        f"Resolved command: {command[0]}",
                        f"PATH: {os.environ.get('PATH', '')}",
                        "Hint: set SPRINTER_CODEX_IMPLEMENTER_COMMAND to the absolute Codex CLI path if needed.",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            raise CodexImplementerError(f"Could not start Codex command: {exc}") from exc

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
            raise CodexImplementerError(f"Codex implementer failed with exit code {completed.returncode}.")

        if not output_path.exists() or not output_path.read_text(encoding="utf-8").strip():
            raise CodexImplementerError(f"Codex did not create implementer output: {output_path}")

        return CodexImplementerRunnerResult(completed.returncode, log_path, output_path)

    def _build_command(self, repo_root: Path, output_path: Path) -> list[str]:
        """Build the non-interactive Codex command."""

        command = [
            self._resolve_command(),
            "exec",
            "--cd",
            str(repo_root),
            "--sandbox",
            self.settings.sandbox,
            "--output-last-message",
            str(output_path),
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
