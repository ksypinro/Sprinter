"""Small git command adapter for GitHub workers."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional


class GitCommandError(RuntimeError):
    """Raised when a git command fails."""


@dataclass(frozen=True)
class GitCommandResult:
    args: list[str]
    returncode: int
    stdout: str
    stderr: str


CommandRunner = Callable[[list[str], Path], GitCommandResult]


def subprocess_runner(args: list[str], cwd: Path) -> GitCommandResult:
    completed = subprocess.run(args, cwd=cwd, text=True, capture_output=True, check=False)
    return GitCommandResult(args, completed.returncode, completed.stdout, completed.stderr)


class GitAdapter:
    """Wrap git subprocess calls behind a testable API."""

    def __init__(self, repo_root: Path, runner: Optional[CommandRunner] = None):
        self.repo_root = repo_root
        self.runner = runner or subprocess_runner

    def run(self, *args: str) -> GitCommandResult:
        result = self.runner(["git", *args], self.repo_root)
        if result.returncode != 0:
            raise GitCommandError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
        return result

    def status_porcelain(self) -> str:
        return self.run("status", "--porcelain", "--untracked-files=all").stdout

    def has_changes(self) -> bool:
        return bool(self.status_porcelain().strip())

    def current_branch(self) -> str:
        return self.run("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()

    def create_branch(self, branch: str) -> None:
        self.run("checkout", "-b", branch)

    def add_all(self) -> None:
        self.run("add", "-A")

    def commit(self, message: str, body: str) -> None:
        self.run("commit", "-m", message, "-m", body)

    def push(self, remote: str, branch: str) -> None:
        self.run("push", "-u", remote, branch)

    def head_sha(self) -> str:
        return self.run("rev-parse", "HEAD").stdout.strip()

    def changed_files(self) -> list[str]:
        output = self.run("diff", "--name-only", "HEAD").stdout
        staged = self.run("diff", "--cached", "--name-only").stdout
        files = {line.strip() for line in (output + "\n" + staged).splitlines() if line.strip()}
        for line in self.status_porcelain().splitlines():
            if len(line) <= 3:
                continue
            path = line[3:].strip()
            if " -> " in path:
                path = path.split(" -> ", 1)[1].strip()
            if path:
                files.add(path.strip('"'))
        return sorted(files)
