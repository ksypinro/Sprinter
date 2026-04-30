"""Service that reviews GitHub PRs and posts review comments."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Protocol

from github_service.artifacts import issue_dir_from_payload, write_json
from github_service.client import GitHubClient
from github_service.review_runner import CodexReviewRunner, ReviewRunnerResult
from github_service.settings import GitHubSettings
from orchestrator.models import utc_now_iso


class ReviewRunner(Protocol):
    def run(self, prompt: str, repo_root: Path, review_path: Path, log_path: Path) -> ReviewRunnerResult:
        ...


@dataclass(frozen=True)
class GitReviewerService:
    settings: GitHubSettings
    repo_root: Path
    client: GitHubClient
    runner: ReviewRunner

    @classmethod
    def create(cls, repo_root: Path, settings: Optional[GitHubSettings] = None) -> "GitReviewerService":
        settings = settings or GitHubSettings.from_env()
        return cls(settings=settings, repo_root=repo_root, client=GitHubClient(settings), runner=CodexReviewRunner(settings))

    def review(self, workflow_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.settings.require_api()
        pr_number = payload.get("pr_number")
        commit_sha = payload.get("commit_sha")
        if not pr_number and commit_sha:
            prs = self.client.pull_requests_for_commit(commit_sha)
            if not prs:
                return self._write_skipped(workflow_id, payload, "No pull request is associated with this commit.")
            pr_number = prs[0].get("number")
        if not pr_number:
            return self._write_skipped(workflow_id, payload, "No pull request number was provided.")

        pr_number = int(pr_number)
        issue_dir = issue_dir_from_payload(self.repo_root, workflow_id, payload)
        output_dir = issue_dir / "github_review"
        prompt_path = output_dir / "review_prompt.md"
        review_path = output_dir / "review.md"
        log_path = output_dir / "codex_review.log"
        comment_payload_path = output_dir / "github_comment_payload.json"
        result_path = output_dir / "review_result.json"

        pr = self.client.get_pull_request(pr_number)
        files = self.client.list_pull_request_files(pr_number)
        diff = self.client.get_pull_request_diff(pr_number)
        prompt = self._build_prompt(pr, files, diff)
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path.write_text(prompt, encoding="utf-8")
        runner_result = self.runner.run(prompt, self.repo_root, review_path, log_path)
        review_body = review_path.read_text(encoding="utf-8")
        comment_body = self._comment_body(pr_number, review_body)
        comment_payload = {"body": comment_body}
        write_json(comment_payload_path, comment_payload)
        comment = self.client.create_issue_comment(pr_number, comment_body)

        result = {
            "status": "success",
            "workflow_id": workflow_id,
            "pr_number": pr_number,
            "html_url": pr.get("html_url"),
            "comment_url": comment.get("html_url") or comment.get("url"),
            "issue_dir": str(issue_dir),
            "prompt_path": str(prompt_path),
            "review_path": str(review_path),
            "log_path": str(log_path),
            "comment_payload_path": str(comment_payload_path),
            "result_path": str(result_path),
            "returncode": runner_result.returncode,
            "created_at": utc_now_iso(),
        }
        write_json(result_path, result)
        return result

    def _write_skipped(self, workflow_id: str, payload: dict[str, Any], reason: str) -> dict[str, Any]:
        issue_dir = issue_dir_from_payload(self.repo_root, workflow_id, payload)
        result_path = issue_dir / "github_review" / "review_result.json"
        result = {"status": "skipped", "workflow_id": workflow_id, "reason": reason, "result_path": str(result_path), "created_at": utc_now_iso()}
        write_json(result_path, result)
        return result

    @staticmethod
    def _build_prompt(pr: dict[str, Any], files: list[dict[str, Any]], diff: str) -> str:
        file_lines = "\n".join(f"- {f.get('filename')} ({f.get('status')}, +{f.get('additions', 0)}/-{f.get('deletions', 0)})" for f in files)
        return f"""# GitHub PR Review Task

Review pull request #{pr.get('number')}: {pr.get('title')}

URL: {pr.get('html_url')}
Base: {pr.get('base', {}).get('ref')}
Head: {pr.get('head', {}).get('ref')}

Focus on bugs, regressions, missing tests, security issues, and integration risks.
If no blocking issues are found, say "No blocking issues found".

## Changed Files

{file_lines or "- No files returned by GitHub."}

## Diff

```diff
{diff}
```
"""

    @staticmethod
    def _comment_body(pr_number: int, review_body: str) -> str:
        return f"## Sprinter Automated Review for PR #{pr_number}\n\n{review_body.strip()}\n"
