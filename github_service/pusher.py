"""Service that commits implementation changes and opens a GitHub PR."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from github_service.artifacts import issue_dir_from_payload, read_text_required, repo_path, write_json
from github_service.client import GitHubClient
from github_service.git import GitAdapter
from github_service.settings import GitHubSettings
from orchestrator.models import utc_now_iso


@dataclass(frozen=True)
class GitPusherService:
    settings: GitHubSettings
    repo_root: Path
    git: GitAdapter
    client: GitHubClient

    @classmethod
    def create(cls, repo_root: Path, settings: Optional[GitHubSettings] = None) -> "GitPusherService":
        settings = settings or GitHubSettings.from_env()
        return cls(settings=settings, repo_root=repo_root, git=GitAdapter(repo_root), client=GitHubClient(settings))

    def create_pull_request(self, workflow_id: str, command_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.settings.require_api()
        issue_dir = issue_dir_from_payload(self.repo_root, workflow_id, payload)
        commit_log_path = repo_path(self.repo_root, payload["commit_log_path"])
        commit_log = read_text_required(commit_log_path, "commit log")

        if not self.git.has_changes():
            raise ValueError("No git changes found to commit.")

        branch = self._branch_name(workflow_id, command_id)
        if branch == self.settings.base_branch:
            raise ValueError("Refusing to create a pull request from the base branch.")

        changed_files = self.git.changed_files()
        self.git.create_branch(branch)
        self.git.add_all()
        self.git.commit(self._commit_subject(workflow_id), commit_log)
        self.git.push(self.settings.remote, branch)
        commit_sha = self.git.head_sha()

        output_dir = issue_dir / "github_pr"
        description_path = output_dir / "pr_description.md"
        result_path = output_dir / "github_pr_result.json"
        description = self._pr_body(workflow_id, commit_log, changed_files)
        description_path.parent.mkdir(parents=True, exist_ok=True)
        description_path.write_text(description, encoding="utf-8")

        pr = self.client.create_pull_request(
            title=self._commit_subject(workflow_id),
            head=branch,
            base=self.settings.base_branch,
            body=description,
            draft=self.settings.draft_pr,
        )

        result = {
            "status": "success",
            "workflow_id": workflow_id,
            "branch": branch,
            "base_branch": self.settings.base_branch,
            "commit_sha": commit_sha,
            "changed_files": changed_files,
            "pr_number": pr.get("number"),
            "html_url": pr.get("html_url"),
            "diff_url": pr.get("diff_url"),
            "draft": pr.get("draft", self.settings.draft_pr),
            "issue_dir": str(issue_dir),
            "commit_log_path": str(commit_log_path),
            "description_path": str(description_path),
            "result_path": str(result_path),
            "created_at": utc_now_iso(),
        }
        write_json(result_path, result)
        return result

    def _branch_name(self, workflow_id: str, command_id: str) -> str:
        safe_workflow = workflow_id.replace("/", "-").replace(" ", "-")
        return f"{self.settings.branch_prefix}{safe_workflow}-{command_id[:8]}"

    @staticmethod
    def _commit_subject(workflow_id: str) -> str:
        return f"Implement {workflow_id}"

    @staticmethod
    def _pr_body(workflow_id: str, commit_log: str, changed_files: list[str]) -> str:
        files = "\n".join(f"- `{path}`" for path in changed_files) or "- No changed files detected before commit."
        return f"""## Sprinter Automated PR

Workflow: `{workflow_id}`

## Changed Files

{files}

## Implementation Log

{commit_log}
"""
