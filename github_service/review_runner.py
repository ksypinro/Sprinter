"""Codex runner used by the GitHub reviewer worker."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from github_service.settings import GitHubSettings


DEFAULT_CODEX_COMMAND_CANDIDATES = (
    Path("/Applications/Codex.app/Contents/Resources/codex"),
    Path("/opt/homebrew/bin/codex"),
    Path("/usr/local/bin/codex"),
)


class GitHubReviewError(RuntimeError):
    """Raised when Codex review cannot be completed."""


@dataclass(frozen=True)
class ReviewRunnerResult:
    returncode: int
    review_path: Path
    log_path: Path


class CodexReviewRunner:
    def __init__(self, settings: GitHubSettings):
        self.settings = settings

    def run(self, prompt: str, repo_root: Path, review_path: Path, log_path: Path) -> ReviewRunnerResult:
        review_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        command = self._build_command(repo_root, review_path)
        completed = subprocess.run(command, input=prompt, text=True, capture_output=True, timeout=self.settings.codex_timeout_seconds, check=False)
        log_path.write_text(
            "\n".join(["COMMAND: " + shlex.join(command), "", "STDOUT:", completed.stdout, "", "STDERR:", completed.stderr, ""]),
            encoding="utf-8",
        )
        if completed.returncode != 0:
            raise GitHubReviewError(f"Codex review failed with exit code {completed.returncode}.")
        if not review_path.exists() or not review_path.read_text(encoding="utf-8").strip():
            raise GitHubReviewError(f"Codex did not create review output: {review_path}")
        return ReviewRunnerResult(completed.returncode, review_path, log_path)

    def _build_command(self, repo_root: Path, review_path: Path) -> list[str]:
        command = [
            self._resolve_command(),
            "exec",
            "--cd",
            str(repo_root),
            "--sandbox",
            self.settings.codex_sandbox,
            "--output-last-message",
            str(review_path),
        ]
        if self.settings.codex_json:
            command.append("--json")
        return command

    def _resolve_command(self) -> str:
        configured = self.settings.codex_command
        if os.sep in configured or (os.altsep and os.altsep in configured):
            return configured
        found = shutil.which(configured)
        if found:
            return found
        for candidate in DEFAULT_CODEX_COMMAND_CANDIDATES:
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate)
        return configured
