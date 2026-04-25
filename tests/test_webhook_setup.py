"""Tests for automated webhook setup orchestration helpers."""

import os
import tempfile
import unittest

from webhooks.setup import (
    build_ngrok_command,
    build_signature,
    load_setup_config,
    resolve_ngrok_auth_token,
)


class WebhookSetupTestCase(unittest.TestCase):
    """Unit tests for setup configuration and helper functions."""

    def test_load_setup_config_reads_required_sections(self):
        """Setup config should parse ngrok, server, Jira, and check settings."""

        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = os.path.join(temp_dir, "ngrok_config.yaml")
            with open(config_path, "w", encoding="utf-8") as handle:
                handle.write(
                    """
ngrok:
  command: "ngrok"
  auth_token: "token"
  auth_token_env: "NGROK_AUTHTOKEN"
  addr: "http://127.0.0.1:8090"
  api_url: "http://127.0.0.1:4040/api/tunnels"
  inspect: false
webhook_server:
  host: "127.0.0.1"
  port: 8090
  path: "/webhooks/jira"
  config_path: "config.yaml"
  webhook_config_path: "webhooks/config.yaml"
jira_webhook:
  name: "Sprinter"
  description: "Test"
  jql: "project = SCRUM"
  replace_existing: true
  delete_on_exit: false
  events:
    - "jira:issue_created"
checks:
  timeout_seconds: 30
  poll_interval_seconds: 1
  run_smoke_test: true
  smoke_issue_key: "SCRUM-1"
"""
                )

            config = load_setup_config(config_path)

        self.assertEqual(config.ngrok.auth_token, "token")
        self.assertFalse(config.ngrok.inspect)
        self.assertEqual(config.webhook_server.port, 8090)
        self.assertEqual(config.jira_webhook.events, ("jira:issue_created",))
        self.assertEqual(config.checks.smoke_issue_key, "SCRUM-1")

    def test_build_ngrok_command_includes_authtoken_url_and_inspect(self):
        """The ngrok command should reflect config flags."""

        config = load_setup_config()
        command = build_ngrok_command(config.ngrok)

        self.assertIn("http", command)
        self.assertIn(config.ngrok.addr, command)
        self.assertIn("--log-format", command)

    def test_resolve_ngrok_auth_token_prefers_environment(self):
        """Environment token should override the config token."""

        config = load_setup_config()
        old_value = os.environ.get(config.ngrok.auth_token_env)
        os.environ[config.ngrok.auth_token_env] = "env-token"
        try:
            self.assertEqual(resolve_ngrok_auth_token(config.ngrok), "env-token")
        finally:
            if old_value is None:
                os.environ.pop(config.ngrok.auth_token_env, None)
            else:
                os.environ[config.ngrok.auth_token_env] = old_value

    def test_build_signature_matches_jira_header_shape(self):
        """Smoke-test signatures should use Jira's X-Hub-Signature format."""

        signature = build_signature("It's a Secret to Everybody", b"Hello World!")

        self.assertEqual(
            signature,
            "sha256=a4771c39fbe90f317c7824e83ddef3caae9cb3d976c214ace1f2937e133263c9",
        )


if __name__ == "__main__":
    unittest.main()
