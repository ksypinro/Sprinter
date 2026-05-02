"""Settings for GitHub automation workers and webhooks."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping, Optional


class GitHubSettingsError(ValueError):
    """Raised when GitHub settings are invalid."""


@dataclass(frozen=True)
class GitHubSettings:
    token: Optional[str] = None
    owner: Optional[str] = None
    repo: Optional[str] = None
    webhook_secret: Optional[str] = None
    base_branch: str = "main"
    remote: str = "origin"
    branch_prefix: str = "sprinter/"
    draft_pr: bool = True
    api_base_url: str = "https://api.github.com"
    request_timeout_seconds: float = 20.0
    codex_command: str = "codex"
    codex_sandbox: str = "read-only"
    codex_json: bool = True
    codex_timeout_seconds: int = 900

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "GitHubSettings":
        source = env or os.environ
        review_timeout_value = source.get("SPRINTER_GITHUB_REVIEW_TIMEOUT_SECONDS", str(cls.codex_timeout_seconds))
        request_timeout_value = source.get("SPRINTER_GITHUB_REQUEST_TIMEOUT_SECONDS", str(cls.request_timeout_seconds))
        try:
            review_timeout_seconds = int(review_timeout_value)
        except ValueError as exc:
            raise GitHubSettingsError("SPRINTER_GITHUB_REVIEW_TIMEOUT_SECONDS must be an integer.") from exc
        try:
            request_timeout_seconds = float(request_timeout_value)
        except ValueError as exc:
            raise GitHubSettingsError("SPRINTER_GITHUB_REQUEST_TIMEOUT_SECONDS must be a number.") from exc

        settings = cls(
            token=_optional(source.get("SPRINTER_GITHUB_TOKEN")),
            owner=_optional(source.get("SPRINTER_GITHUB_OWNER")),
            repo=_optional(source.get("SPRINTER_GITHUB_REPO")),
            webhook_secret=_optional(source.get("SPRINTER_GITHUB_WEBHOOK_SECRET")),
            base_branch=source.get("SPRINTER_GITHUB_BASE_BRANCH", cls.base_branch).strip() or cls.base_branch,
            remote=source.get("SPRINTER_GITHUB_REMOTE", cls.remote).strip() or cls.remote,
            branch_prefix=source.get("SPRINTER_GITHUB_BRANCH_PREFIX", cls.branch_prefix).strip() or cls.branch_prefix,
            draft_pr=_parse_bool(source.get("SPRINTER_GITHUB_DRAFT_PR"), cls.draft_pr, "SPRINTER_GITHUB_DRAFT_PR"),
            api_base_url=source.get("SPRINTER_GITHUB_API_BASE_URL", cls.api_base_url).rstrip("/"),
            request_timeout_seconds=request_timeout_seconds,
            codex_command=source.get("SPRINTER_GITHUB_REVIEW_CODEX_COMMAND", cls.codex_command).strip() or cls.codex_command,
            codex_sandbox=source.get("SPRINTER_GITHUB_REVIEW_CODEX_SANDBOX", cls.codex_sandbox).strip() or cls.codex_sandbox,
            codex_json=_parse_bool(source.get("SPRINTER_GITHUB_REVIEW_CODEX_JSON"), cls.codex_json, "SPRINTER_GITHUB_REVIEW_CODEX_JSON"),
            codex_timeout_seconds=review_timeout_seconds,
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if not self.base_branch:
            raise GitHubSettingsError("GitHub base branch must not be empty.")
        if not self.remote:
            raise GitHubSettingsError("GitHub remote must not be empty.")
        if not self.branch_prefix:
            raise GitHubSettingsError("GitHub branch prefix must not be empty.")
        if self.codex_sandbox != "read-only":
            raise GitHubSettingsError("GitHub reviewer Codex sandbox must be read-only.")
        if self.request_timeout_seconds <= 0:
            raise GitHubSettingsError("GitHub API request timeout must be positive.")
        if self.codex_timeout_seconds <= 0:
            raise GitHubSettingsError("GitHub reviewer timeout must be positive.")

    def require_api(self) -> None:
        missing = []
        if not self.token:
            missing.append("SPRINTER_GITHUB_TOKEN")
        if not self.owner:
            missing.append("SPRINTER_GITHUB_OWNER")
        if not self.repo:
            missing.append("SPRINTER_GITHUB_REPO")
        if missing:
            raise GitHubSettingsError(f"Missing GitHub API settings: {', '.join(missing)}")

    def require_webhook(self) -> None:
        if not self.webhook_secret:
            raise GitHubSettingsError("Missing GitHub webhook secret: SPRINTER_GITHUB_WEBHOOK_SECRET")


def _optional(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _parse_bool(value: Optional[str], default: bool, field_name: str) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise GitHubSettingsError(f"{field_name} must be a boolean value.")
