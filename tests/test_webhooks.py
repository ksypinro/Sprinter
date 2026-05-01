"""Tests for the filesystem-backed webhook server."""

import hmac
import hashlib
import json
import os
import tempfile
import unittest

from webhooks.app import WebhookApplication
from webhooks.models import JobStatus, WebhookDecision, WebhookEvent
from webhooks.parser import JiraWebhookParser
from webhooks.security import SecretVerifier, WebhookAuthError
from webhooks.settings import WebhookSettings, WebhookSettingsError
from webhooks.store import FilesystemWebhookStore
from webhooks.worker import WebhookExportService, WebhookWorker


def jira_payload(event_id="evt-1", event_type="jira:issue_updated", issue_key="SCRUM-1"):
    """Return a representative Jira webhook payload."""

    return {
        "webhookEvent": event_type,
        "webhookEventId": event_id,
        "issue": {
            "key": issue_key,
            "fields": {
                "project": {"key": issue_key.split("-", 1)[0]},
            },
        },
        "user": {
            "emailAddress": "dev@example.com",
            "accountId": "abc123",
        },
    }


def webhook_event(event_id="evt-1"):
    """Return a normalized event for store tests."""

    return WebhookEvent(
        provider="jira",
        event_id=event_id,
        event_type="jira:issue_updated",
        issue_key="SCRUM-1",
        issue_url="https://example.atlassian.net/browse/SCRUM-1",
        project_key="SCRUM",
        actor="dev@example.com",
        raw_payload=jira_payload(event_id=event_id),
    )


class WebhookSettingsTestCase(unittest.TestCase):
    """Unit tests for webhook settings parsing."""

    def test_from_env_reads_settings_file_secret_by_default(self):
        """The webhook config file should provide startup defaults."""

        with tempfile.TemporaryDirectory() as temp_dir:
            settings_path = os.path.join(temp_dir, "webhook.yaml")
            with open(settings_path, "w", encoding="utf-8") as handle:
                handle.write(
                    """
server:
  jira_path: "/webhooks/jira"
auth:
  secret: "change-me-local-webhook-secret"
events:
  allowed_events:
    - "jira:issue_deleted"
    - "attachment_created"
    - "issue_property_deleted"
"""
                )

            settings = WebhookSettings.from_env({"SPRINTER_WEBHOOK_SETTINGS_FILE": settings_path})

        self.assertEqual(settings.secret, "change-me-local-webhook-secret")
        self.assertEqual(settings.jira_path, "/webhooks/jira")
        self.assertIn("jira:issue_deleted", settings.allowed_events)
        self.assertIn("attachment_created", settings.allowed_events)
        self.assertIn("issue_property_deleted", settings.allowed_events)

    def test_from_env_requires_secret_and_parses_filters(self):
        """Settings should resolve secrets and CSV filters from env."""

        settings = WebhookSettings.from_env(
            {
                "SPRINTER_WEBHOOK_SECRET": "shared-secret",
                "SPRINTER_WEBHOOK_ALLOWED_EVENTS": "jira:issue_updated,comment_created",
                "SPRINTER_WEBHOOK_ALLOWED_PROJECTS": "SCRUM,OPS",
                "SPRINTER_WEBHOOK_LOG_FILE": "/tmp/sprinter-webhook.log",
                "SPRINTER_WEBHOOK_WORKER_ENABLED": "false",
            }
        )

        self.assertEqual(settings.secret, "shared-secret")
        self.assertEqual(settings.allowed_events, ("jira:issue_updated", "comment_created"))
        self.assertEqual(settings.allowed_projects, ("SCRUM", "OPS"))
        self.assertEqual(settings.log_file, "/tmp/sprinter-webhook.log")
        self.assertFalse(settings.worker_enabled)

    def test_from_env_rejects_missing_secret(self):
        """Webhook authentication should be mandatory by default."""

        with tempfile.TemporaryDirectory() as temp_dir:
            settings_path = os.path.join(temp_dir, "webhook.yaml")
            with open(settings_path, "w", encoding="utf-8") as handle:
                handle.write(
                    """
server:
  host: "127.0.0.1"
auth:
  secret:
"""
                )

            with self.assertRaises(WebhookSettingsError):
                WebhookSettings.from_env({"SPRINTER_WEBHOOK_SETTINGS_FILE": settings_path})


class WebhookSecurityTestCase(unittest.TestCase):
    """Unit tests for webhook shared-secret verification."""

    def test_secret_verifier_accepts_case_insensitive_header_name(self):
        """Header lookup should match HTTP's case-insensitive behavior."""

        verifier = SecretVerifier("secret", "X-Sprinter-Webhook-Secret")
        verifier.verify({"x-sprinter-webhook-secret": "secret"})

    def test_secret_verifier_accepts_jira_hmac_signature(self):
        """Jira admin webhooks sign payloads with X-Hub-Signature."""

        verifier = SecretVerifier("It's a Secret to Everybody")
        verifier.verify(
            {"X-Hub-Signature": "sha256=a4771c39fbe90f317c7824e83ddef3caae9cb3d976c214ace1f2937e133263c9"},
            b"Hello World!",
        )

    def test_secret_verifier_rejects_wrong_jira_hmac_signature(self):
        """A bad Jira signature should fail authentication."""

        verifier = SecretVerifier("secret")
        signature = hmac.new(b"other-secret", msg=b"payload", digestmod=hashlib.sha256).hexdigest()

        with self.assertRaises(WebhookAuthError):
            verifier.verify({"X-Hub-Signature": f"sha256={signature}"}, b"payload")

    def test_secret_verifier_rejects_wrong_secret(self):
        """A wrong secret should fail authentication."""

        verifier = SecretVerifier("secret")
        with self.assertRaises(WebhookAuthError):
            verifier.verify({"X-Sprinter-Webhook-Secret": "wrong"})


class JiraWebhookParserTestCase(unittest.TestCase):
    """Unit tests for Jira payload normalization and filtering."""

    def test_parser_extracts_normalized_event(self):
        """A Jira issue payload should become a clean WebhookEvent."""

        parser = JiraWebhookParser(
            "https://example.atlassian.net/",
            allowed_events=("jira:issue_updated",),
            allowed_projects=("SCRUM",),
        )
        event = parser.parse(jira_payload())

        self.assertEqual(event.event_id, "evt-1")
        self.assertEqual(event.event_type, "jira:issue_updated")
        self.assertEqual(event.issue_key, "SCRUM-1")
        self.assertEqual(event.project_key, "SCRUM")
        self.assertEqual(event.issue_url, "https://example.atlassian.net/browse/SCRUM-1")
        self.assertTrue(parser.decide(event).accepted)

    def test_parser_ignores_disabled_project(self):
        """Project filters should prevent unrelated issues from exporting."""

        parser = JiraWebhookParser(
            "https://example.atlassian.net",
            allowed_events=("jira:issue_updated",),
            allowed_projects=("OPS",),
        )
        decision = parser.decide(parser.parse(jira_payload()))

        self.assertFalse(decision.accepted)
        self.assertIn("Project is not enabled", decision.reason)

    def test_parser_extracts_issue_link_source_issue_key(self):
        """Issue-link webhooks may identify the issue through issueLink."""

        parser = JiraWebhookParser(
            "https://example.atlassian.net",
            allowed_events=("issuelink_created",),
        )
        event = parser.parse(
            {
                "webhookEvent": "issuelink_created",
                "webhookEventId": "link-1",
                "issueLink": {"sourceIssueKey": "scrum-9", "destinationIssueKey": "ops-1"},
            }
        )

        self.assertEqual(event.issue_key, "SCRUM-9")
        self.assertEqual(event.project_key, "SCRUM")


class FilesystemWebhookStoreTestCase(unittest.TestCase):
    """Unit tests for the filesystem-backed webhook store."""

    def test_record_enqueue_claim_and_complete_job(self):
        """The store should handle event dedupe and job lifecycle moves."""

        with tempfile.TemporaryDirectory() as temp_dir:
            store = FilesystemWebhookStore(temp_dir, ttl_seconds=60)
            event = webhook_event()
            decision = WebhookDecision(True, "accepted")

            self.assertTrue(store.record_event(event, decision))
            self.assertFalse(store.record_event(event, decision))

            job = store.enqueue_job(event)
            self.assertEqual(store.get_job(job.job_id).status, JobStatus.QUEUED)

            claimed = store.claim_next_job()
            self.assertIsNotNone(claimed)
            self.assertEqual(claimed.job_id, job.job_id)
            self.assertEqual(store.get_job(job.job_id).status, JobStatus.RUNNING)

            store.mark_success(job.job_id, {"manifest_path": "/tmp/manifest.json"})
            completed = store.get_job(job.job_id)
            self.assertEqual(completed.status, JobStatus.SUCCESS)
            self.assertEqual(completed.result["manifest_path"], "/tmp/manifest.json")


class WebhookApplicationTestCase(unittest.TestCase):
    """Unit tests for the testable webhook application core."""

    def test_handle_jira_webhook_submits_orchestrator_event_when_connected(self):
        """Orchestrator-hosted Jira webhooks should not enqueue legacy export jobs."""

        class FakeOrchestrator:
            def __init__(self):
                self.events = []

            def submit_jira_webhook(self, event):
                self.events.append(event)
                return "orchestrator-event-1"

        with tempfile.TemporaryDirectory() as temp_dir:
            settings = WebhookSettings(secret="secret", worker_enabled=True, use_orchestrator=True)
            store = FilesystemWebhookStore(temp_dir, ttl_seconds=60)
            orchestrator = FakeOrchestrator()
            app = WebhookApplication(
                settings=settings,
                verifier=SecretVerifier("secret"),
                parser=JiraWebhookParser("https://example.atlassian.net", settings.allowed_events),
                store=store,
                orchestrator=orchestrator,
            )
            body = json.dumps(jira_payload()).encode("utf-8")

            response = app.handle_jira_webhook({"X-Sprinter-Webhook-Secret": "secret"}, body)

            self.assertEqual(response.status_code, 202)
            self.assertEqual(response.body["status"], "accepted")
            self.assertEqual(response.body["workflow_id"], "SCRUM-1")
            self.assertEqual(response.body["orchestrator_event_id"], "orchestrator-event-1")
            self.assertEqual(orchestrator.events[0].issue_key, "SCRUM-1")
            self.assertEqual(store.list_jobs(JobStatus.QUEUED), [])

    def test_handle_jira_webhook_enqueues_job_and_dedupes_retry(self):
        """Accepted webhook payloads should create one job despite retries."""

        with tempfile.TemporaryDirectory() as temp_dir:
            settings = WebhookSettings(secret="secret", worker_enabled=False)
            store = FilesystemWebhookStore(temp_dir, ttl_seconds=60)
            app = WebhookApplication(
                settings=settings,
                verifier=SecretVerifier("secret"),
                parser=JiraWebhookParser("https://example.atlassian.net", settings.allowed_events),
                store=store,
            )
            headers = {"X-Sprinter-Webhook-Secret": "secret"}
            body = json.dumps(jira_payload()).encode("utf-8")

            first = app.handle_jira_webhook(headers, body)
            second = app.handle_jira_webhook(headers, body)

            self.assertEqual(first.status_code, 202)
            self.assertEqual(first.body["status"], "accepted")
            self.assertEqual(second.body["status"], "duplicate")
            self.assertEqual(len(store.list_jobs(JobStatus.QUEUED)), 1)

    def test_handle_jira_webhook_rejects_bad_secret(self):
        """Requests with the wrong shared secret should be rejected."""

        with tempfile.TemporaryDirectory() as temp_dir:
            settings = WebhookSettings(secret="secret", worker_enabled=False)
            app = WebhookApplication(
                settings=settings,
                verifier=SecretVerifier("secret"),
                parser=JiraWebhookParser("https://example.atlassian.net", settings.allowed_events),
                store=FilesystemWebhookStore(temp_dir),
            )

            response = app.handle_jira_webhook(
                {"X-Sprinter-Webhook-Secret": "wrong"},
                json.dumps(jira_payload()).encode("utf-8"),
            )

            self.assertEqual(response.status_code, 401)

    def test_handle_issue_deleted_records_without_export_job(self):
        """Deleted issues should be recorded without trying to export them."""

        with tempfile.TemporaryDirectory() as temp_dir:
            settings = WebhookSettings(secret="secret", worker_enabled=False)
            store = FilesystemWebhookStore(temp_dir, ttl_seconds=60)
            app = WebhookApplication(
                settings=settings,
                verifier=SecretVerifier("secret"),
                parser=JiraWebhookParser("https://example.atlassian.net", settings.allowed_events),
                store=store,
            )

            response = app.handle_jira_webhook(
                {"X-Sprinter-Webhook-Secret": "secret"},
                json.dumps(jira_payload(event_id="deleted-1", event_type="jira:issue_deleted")).encode("utf-8"),
            )

            self.assertEqual(response.status_code, 202)
            self.assertEqual(response.body["status"], "recorded")
            self.assertEqual(len(store.list_jobs(JobStatus.QUEUED)), 0)


class WebhookWorkerTestCase(unittest.TestCase):
    """Unit tests for worker processing."""

    def test_worker_runs_export_and_records_trigger_metadata(self):
        """A claimed job should run the export service and update the manifest."""

        class FakeService:
            def __init__(self, manifest_path):
                self.manifest_path = manifest_path
                self.ticket_urls = []

            def export_issue(self, ticket_url):
                self.ticket_urls.append(ticket_url)
                with open(self.manifest_path, "w", encoding="utf-8") as handle:
                    json.dump({"status": "success"}, handle)
                return {
                    "issue_key": "SCRUM-1",
                    "manifest_path": self.manifest_path,
                }

        with tempfile.TemporaryDirectory() as temp_dir:
            manifest_path = os.path.join(temp_dir, "export_manifest.json")
            store = FilesystemWebhookStore(os.path.join(temp_dir, "store"))
            event = webhook_event()
            store.enqueue_job(event)

            fake_service = FakeService(manifest_path)
            worker = WebhookWorker(store, WebhookExportService(service=fake_service), poll_interval_seconds=0.01)

            self.assertTrue(worker.run_once())
            self.assertEqual(fake_service.ticket_urls, [event.issue_url])
            self.assertEqual(store.list_jobs(JobStatus.SUCCESS)[0].event.issue_key, "SCRUM-1")

            with open(manifest_path, "r", encoding="utf-8") as handle:
                manifest = json.load(handle)
            self.assertEqual(manifest["trigger"]["type"], "webhook")
            self.assertEqual(manifest["trigger"]["event_id"], event.event_id)


if __name__ == "__main__":
    unittest.main()
