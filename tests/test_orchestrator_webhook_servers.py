"""Tests for orchestrator-owned webhook server lifecycle."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from orchestrator.service import OrchestratorService
from orchestrator.settings import (
    GitHubWebhookServerSettings,
    JiraWebhookServerSettings,
    OrchestratorSettings,
    WebhookServerSettings,
)


class OrchestratorWebhookServerTestCase(unittest.TestCase):
    def test_initialize_starts_jira_and_github_webhook_servers(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            settings = OrchestratorSettings(
                repo_root=Path.cwd(),
                storage_root=temp_root / ".orchestrator",
                exports_root=temp_root / "exports",
                webhook_servers=WebhookServerSettings(
                    auto_start=True,
                    jira=JiraWebhookServerSettings(port=0, store_path=str(temp_root / "jira-webhooks")),
                    github=GitHubWebhookServerSettings(port=0, store_path=str(temp_root / "github-webhooks")),
                ),
            )
            service = OrchestratorService(settings)

            with (
                patch("orchestrator.webhook_manager.create_webhook_server", return_value=FakeServer("jira", 18090)),
                patch("orchestrator.webhook_manager.create_github_webhook_server", return_value=FakeServer("github", 18091)),
            ):
                service.initialize()
                try:
                    endpoints = service.webhook_manager.endpoints()

                    self.assertIn("jira", endpoints)
                    self.assertIn("github", endpoints)
                    self.assertEqual(endpoints["jira"]["port"], 18090)
                    self.assertEqual(endpoints["github"]["port"], 18091)
                finally:
                    service.shutdown()


class FakeServer:
    def __init__(self, name, port):
        self.name = name
        self.server_address = ("127.0.0.1", port)
        self.served = False
        self.closed = False

    def serve_forever(self):
        self.served = True

    def shutdown(self):
        return None

    def server_close(self):
        self.closed = True


if __name__ == "__main__":
    unittest.main()
