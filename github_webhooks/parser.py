"""Parse GitHub webhook payloads into orchestrator events."""

from __future__ import annotations

import re
from typing import Any, Optional

from orchestrator.models import EventType, OrchestratorEvent


WORKFLOW_RE = re.compile(r"[A-Z][A-Z0-9]+-\d+")


class GitHubWebhookParseError(ValueError):
    """Raised when a GitHub payload cannot be normalized."""


class GitHubWebhookParser:
    def __init__(self, base_branch: str = "main"):
        self.base_branch = base_branch

    def parse(self, event_name: str, payload: dict[str, Any]) -> Optional[OrchestratorEvent]:
        if event_name == "pull_request":
            return self._parse_pull_request(payload)
        if event_name == "push":
            return self._parse_push(payload)
        if event_name == "pull_request_review_comment":
            return self._parse_review_comment(payload)
        return None

    def _parse_pull_request(self, payload: dict[str, Any]) -> Optional[OrchestratorEvent]:
        action = payload.get("action")
        mapping = {
            "opened": EventType.GITHUB_PR_OPENED,
            "synchronize": EventType.GITHUB_PR_SYNCHRONIZE,
            "reopened": EventType.GITHUB_PR_REOPENED,
        }
        event_type = mapping.get(action)
        if not event_type:
            return None
        pr = payload.get("pull_request") or {}
        head = pr.get("head") or {}
        base = pr.get("base") or {}
        workflow_id = self._workflow_id(
            head.get("ref"),
            pr.get("title"),
            pr.get("body"),
            fallback=f"github-pr-{pr.get('number')}",
        )
        return OrchestratorEvent.new(event_type, workflow_id, {
            "pr_number": pr.get("number"),
            "action": action,
            "head_branch": head.get("ref"),
            "base_branch": base.get("ref"),
            "html_url": pr.get("html_url"),
            "diff_url": pr.get("diff_url"),
            "commit_sha": (head.get("sha")),
        })

    def _parse_push(self, payload: dict[str, Any]) -> Optional[OrchestratorEvent]:
        ref = payload.get("ref")
        if ref != f"refs/heads/{self.base_branch}":
            return None
        after = payload.get("after")
        workflow_id = self._workflow_id(payload.get("head_commit", {}).get("message"), after, fallback=f"github-push-{str(after or '')[:8]}")
        return OrchestratorEvent.new(EventType.GITHUB_PUSH_MAIN, workflow_id, {
            "commit_sha": after,
            "base_branch": self.base_branch,
            "html_url": payload.get("compare"),
        })

    def _parse_review_comment(self, payload: dict[str, Any]) -> Optional[OrchestratorEvent]:
        if payload.get("action") != "created":
            return None
        pr = payload.get("pull_request") or {}
        comment = payload.get("comment") or {}
        head = pr.get("head") or {}
        base = pr.get("base") or {}
        workflow_id = self._workflow_id(
            head.get("ref"),
            pr.get("title"),
            pr.get("body"),
            comment.get("body"),
            fallback=f"github-pr-{pr.get('number')}",
        )
        return OrchestratorEvent.new(EventType.GITHUB_PR_REVIEW_COMMENT, workflow_id, {
            "pr_number": pr.get("number"),
            "action": payload.get("action"),
            "comment_id": comment.get("id"),
            "comment_url": comment.get("html_url"),
            "head_branch": head.get("ref"),
            "base_branch": base.get("ref"),
            "html_url": pr.get("html_url"),
            "commit_sha": head.get("sha"),
        })

    @staticmethod
    def _workflow_id(*values: Any, fallback: str) -> str:
        for value in values:
            if not value:
                continue
            match = WORKFLOW_RE.search(str(value))
            if match:
                return match.group(0)
        return fallback
