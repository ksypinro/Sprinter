"""GitHub REST API client for Sprinter workers."""

from __future__ import annotations

from typing import Any, Optional

import requests

from github_service.settings import GitHubSettings


class GitHubAPIError(RuntimeError):
    """Raised when GitHub API calls fail."""


class GitHubClient:
    def __init__(self, settings: GitHubSettings, session: Optional[requests.Session] = None):
        settings.require_api()
        self.settings = settings
        self.session = session or requests.Session()
        self.session.headers.update({
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {settings.token}",
            "X-GitHub-Api-Version": "2022-11-28",
        })

    @property
    def repo_path(self) -> str:
        return f"/repos/{self.settings.owner}/{self.settings.repo}"

    def create_pull_request(self, title: str, head: str, base: str, body: str, draft: bool) -> dict[str, Any]:
        return self._request("POST", f"{self.repo_path}/pulls", json={
            "title": title,
            "head": head,
            "base": base,
            "body": body,
            "draft": draft,
        })

    def find_open_pull_request(self, head: str, base: str) -> Optional[dict[str, Any]]:
        pulls = self._request(
            "GET",
            f"{self.repo_path}/pulls",
            params={"head": f"{self.settings.owner}:{head}", "base": base, "state": "open"},
        )
        return pulls[0] if pulls else None

    def get_pull_request(self, pr_number: int) -> dict[str, Any]:
        return self._request("GET", f"{self.repo_path}/pulls/{pr_number}")

    def list_pull_request_files(self, pr_number: int) -> list[dict[str, Any]]:
        return self._request("GET", f"{self.repo_path}/pulls/{pr_number}/files")

    def get_pull_request_diff(self, pr_number: int) -> str:
        return self._request("GET", f"{self.repo_path}/pulls/{pr_number}", accept="application/vnd.github.diff", text=True)

    def create_issue_comment(self, issue_number: int, body: str) -> dict[str, Any]:
        return self._request("POST", f"{self.repo_path}/issues/{issue_number}/comments", json={"body": body})

    def pull_requests_for_commit(self, sha: str) -> list[dict[str, Any]]:
        return self._request("GET", f"{self.repo_path}/commits/{sha}/pulls", accept="application/vnd.github+json")

    def _request(
        self,
        method: str,
        path: str,
        json: Optional[dict[str, Any]] = None,
        params: Optional[dict[str, Any]] = None,
        accept: Optional[str] = None,
        text: bool = False,
    ):
        headers = {"Accept": accept} if accept else None
        response = self.session.request(
            method,
            f"{self.settings.api_base_url}{path}",
            json=json,
            params=params,
            headers=headers,
            timeout=self.settings.request_timeout_seconds,
        )
        if response.status_code >= 400:
            raise GitHubAPIError(f"GitHub API {method} {path} failed: {response.status_code} {response.text}")
        return response.text if text else response.json()
