"""Tests for GitHub webhook handling."""

import hashlib
import hmac
import json
import tempfile
import unittest
from pathlib import Path

from github_service.settings import GitHubSettings
from github_webhooks.app import GitHubWebhookApplication
from github_webhooks.parser import GitHubWebhookParser
from github_webhooks.security import verify_signature
from github_webhooks.store import GitHubWebhookStore
from orchestrator.models import EventType


def sign(secret, body):
    return "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


class FakeOrchestrator:
    def __init__(self):
        self.events = []

    def submit_event(self, event):
        self.events.append(event)
        return event.event_id


class GitHubWebhookSecurityTestCase(unittest.TestCase):
    def test_verify_signature_accepts_github_hmac(self):
        body = b'{"ok": true}'

        verify_signature("secret", {"X-Hub-Signature-256": sign("secret", body)}, body)


class GitHubWebhookParserTestCase(unittest.TestCase):
    def test_parser_extracts_pr_event(self):
        event = GitHubWebhookParser().parse("pull_request", {
            "action": "opened",
            "pull_request": {
                "number": 7,
                "title": "Implement SCRUM-7",
                "html_url": "https://github.example/pull/7",
                "diff_url": "https://github.example/pull/7.diff",
                "head": {"ref": "sprinter/SCRUM-7", "sha": "abc"},
                "base": {"ref": "main"},
            },
        })

        self.assertEqual(event.event_type, EventType.GITHUB_PR_OPENED)
        self.assertEqual(event.workflow_id, "SCRUM-7")
        self.assertEqual(event.payload["pr_number"], 7)

    def test_parser_extracts_main_push(self):
        event = GitHubWebhookParser().parse("push", {
            "ref": "refs/heads/main",
            "after": "abcdef123456",
            "compare": "https://github.example/compare",
            "head_commit": {"message": "Merge SCRUM-8"},
        })

        self.assertEqual(event.event_type, EventType.GITHUB_PUSH_MAIN)
        self.assertEqual(event.workflow_id, "SCRUM-8")

    def test_parser_extracts_review_comment_without_review_trigger(self):
        event = GitHubWebhookParser().parse("pull_request_review_comment", {
            "action": "created",
            "pull_request": {
                "number": 10,
                "title": "Implement SCRUM-10",
                "html_url": "https://github.example/pull/10",
                "head": {"ref": "sprinter/SCRUM-10", "sha": "abc"},
                "base": {"ref": "main"},
            },
            "comment": {
                "id": 42,
                "html_url": "https://github.example/pull/10#discussion_r42",
                "body": "Looks good",
            },
        })

        self.assertEqual(event.event_type, EventType.GITHUB_PR_REVIEW_COMMENT)
        self.assertEqual(event.workflow_id, "SCRUM-10")
        self.assertEqual(event.payload["comment_id"], 42)


class GitHubWebhookApplicationTestCase(unittest.TestCase):
    def test_app_reports_missing_webhook_secret(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app = GitHubWebhookApplication(
                GitHubSettings(),
                GitHubWebhookStore(Path(temp_dir)),
                GitHubWebhookParser(),
                FakeOrchestrator(),
            )

            response = app.handle({
                "X-GitHub-Delivery": "delivery-1",
                "X-GitHub-Event": "pull_request",
            }, b"{}")

            self.assertEqual(response.status_code, 500)
            self.assertEqual(response.body["status"], "error")

    def test_app_accepts_signed_pr_event_and_submits_orchestrator_event(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            body = json.dumps({
                "action": "opened",
                "pull_request": {
                    "number": 9,
                    "title": "Implement SCRUM-9",
                    "head": {"ref": "sprinter/SCRUM-9", "sha": "abc"},
                    "base": {"ref": "main"},
                },
            }).encode("utf-8")
            orchestrator = FakeOrchestrator()
            app = GitHubWebhookApplication(
                GitHubSettings(webhook_secret="secret"),
                GitHubWebhookStore(Path(temp_dir)),
                GitHubWebhookParser(),
                orchestrator,
            )

            response = app.handle({
                "X-GitHub-Delivery": "delivery-1",
                "X-GitHub-Event": "pull_request",
                "X-Hub-Signature-256": sign("secret", body),
            }, body)

            self.assertEqual(response.status_code, 202)
            self.assertEqual(response.body["status"], "accepted")
            self.assertEqual(orchestrator.events[0].workflow_id, "SCRUM-9")


if __name__ == "__main__":
    unittest.main()
