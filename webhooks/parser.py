"""Jira webhook payload parsing and filtering."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Iterable, Optional

from webhooks.models import WebhookDecision, WebhookEvent, WebhookParseError


class JiraWebhookParser:
    """Normalize Jira webhook payloads into Sprinter webhook events."""

    def __init__(
        self,
        jira_base_url: str,
        allowed_events: Iterable[str],
        allowed_projects: Iterable[str] = (),
        ignored_actors: Iterable[str] = (),
    ):
        """Initialize parser and filter configuration."""

        self.jira_base_url = jira_base_url.rstrip("/")
        self.allowed_events = set(allowed_events)
        self.allowed_projects = {project.upper() for project in allowed_projects}
        self.ignored_actors = {actor.lower() for actor in ignored_actors}

    def parse(self, payload: Dict[str, Any]) -> WebhookEvent:
        """Parse a raw Jira webhook payload into a normalized event."""

        if not isinstance(payload, dict):
            raise WebhookParseError("Jira webhook payload must be a JSON object.")

        event_type = self.extract_event_type(payload)
        issue_key = self.extract_issue_key(payload)
        project_key = self.extract_project_key(payload, issue_key)
        actor = self.extract_actor(payload)
        issue_url = self.build_issue_url(issue_key)
        event_id = self.build_event_id(payload, event_type, issue_key)

        return WebhookEvent(
            provider="jira",
            event_id=event_id,
            event_type=event_type,
            issue_key=issue_key,
            issue_url=issue_url,
            project_key=project_key,
            actor=actor,
            raw_payload=payload,
        )

    def decide(self, event: WebhookEvent) -> WebhookDecision:
        """Return whether an event should create an export job."""

        if event.event_type not in self.allowed_events:
            return WebhookDecision(False, f"Event type is not enabled: {event.event_type}")

        if self.allowed_projects and (event.project_key or "").upper() not in self.allowed_projects:
            return WebhookDecision(False, f"Project is not enabled: {event.project_key or '<unknown>'}")

        if event.actor and event.actor.lower() in self.ignored_actors:
            return WebhookDecision(False, f"Actor is ignored: {event.actor}")

        return WebhookDecision(True, "accepted")

    def extract_event_type(self, payload: Dict[str, Any]) -> str:
        """Extract the Jira webhook event type."""

        event_type = payload.get("webhookEvent") or payload.get("eventType") or payload.get("event_type")
        if not isinstance(event_type, str) or not event_type.strip():
            raise WebhookParseError("Jira webhook payload is missing webhookEvent.")
        return event_type.strip()

    def extract_issue_key(self, payload: Dict[str, Any]) -> str:
        """Extract the Jira issue key from common webhook payload shapes."""

        issue = payload.get("issue")
        if isinstance(issue, dict):
            issue_key = issue.get("key")
            if isinstance(issue_key, str) and issue_key.strip():
                return issue_key.strip().upper()

        issue_key = payload.get("issueKey") or payload.get("issue_key")
        if isinstance(issue_key, str) and issue_key.strip():
            return issue_key.strip().upper()

        issue_link = payload.get("issueLink")
        if isinstance(issue_link, dict):
            for key in ("sourceIssueKey", "destinationIssueKey"):
                linked_issue_key = issue_link.get(key)
                if isinstance(linked_issue_key, str) and linked_issue_key.strip():
                    return linked_issue_key.strip().upper()

            for key in ("sourceIssue", "destinationIssue"):
                linked_issue = issue_link.get(key)
                if isinstance(linked_issue, dict):
                    linked_issue_key = linked_issue.get("key")
                    if isinstance(linked_issue_key, str) and linked_issue_key.strip():
                        return linked_issue_key.strip().upper()

        raise WebhookParseError("Jira webhook payload is missing issue.key.")

    def extract_project_key(self, payload: Dict[str, Any], issue_key: str) -> Optional[str]:
        """Extract a Jira project key, falling back to the issue key prefix."""

        issue = payload.get("issue")
        if isinstance(issue, dict):
            fields = issue.get("fields")
            if isinstance(fields, dict):
                project = fields.get("project")
                if isinstance(project, dict):
                    project_key = project.get("key")
                    if isinstance(project_key, str) and project_key.strip():
                        return project_key.strip().upper()

        if "-" in issue_key:
            return issue_key.split("-", 1)[0].upper()
        return None

    def extract_actor(self, payload: Dict[str, Any]) -> Optional[str]:
        """Extract a useful actor identifier from Jira webhook user data."""

        user = payload.get("user")
        if not isinstance(user, dict):
            return None

        for key in ("emailAddress", "accountId", "name", "displayName"):
            value = user.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    def build_issue_url(self, issue_key: str) -> str:
        """Build the Jira browse URL used by the existing export workflow."""

        return f"{self.jira_base_url}/browse/{issue_key}"

    def build_event_id(self, payload: Dict[str, Any], event_type: str, issue_key: str) -> str:
        """Build a stable event id for duplicate suppression."""

        for key in ("webhookEventId", "eventId", "id"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, int):
                return str(value)

        created = payload.get("timestamp") or payload.get("created") or payload.get("eventTime")
        changelog = payload.get("changelog") if isinstance(payload.get("changelog"), dict) else {}
        changelog_id = changelog.get("id")
        seed = {
            "event_type": event_type,
            "issue_key": issue_key,
            "timestamp": created,
            "changelog_id": changelog_id,
            "payload": payload,
        }
        return hashlib.sha256(json.dumps(seed, sort_keys=True, default=str).encode("utf-8")).hexdigest()
