"""Tests for automated GitHub webhook setup helpers."""

import os
import tempfile
import unittest

from github_service.settings import GitHubSettings
from github_webhooks.setup import (
    GitHubHookClient,
    build_ngrok_command,
    build_signature,
    load_setup_config,
    register_github_webhook,
    resolve_ngrok_auth_token,
)


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.headers = {}
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        return self.responses.pop(0)


class GitHubWebhookSetupTestCase(unittest.TestCase):
    """Unit tests for GitHub setup configuration and helper functions."""

    def test_load_setup_config_reads_required_sections(self):
        """Setup config should parse ngrok, server, GitHub hook, and checks."""

        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = os.path.join(temp_dir, "ngrok_config.yaml")
            with open(config_path, "w", encoding="utf-8") as handle:
                handle.write(
                    """
ngrok:
  command: "ngrok"
  auth_token: "token"
  auth_token_env: "NGROK_AUTHTOKEN"
  addr: "http://127.0.0.1:8091"
  api_url: "http://127.0.0.1:4040/api/tunnels"
  inspect: false
webhook_server:
  host: "127.0.0.1"
  port: 8091
  path: "/webhooks/github"
  store_path: "exports/.github_webhooks"
github_webhook:
  active: true
  content_type: "json"
  insecure_ssl: "0"
  replace_existing: true
  delete_on_exit: false
  events:
    - "pull_request"
    - "push"
checks:
  timeout_seconds: 30
  poll_interval_seconds: 1
  run_smoke_test: true
  smoke_workflow_id: "SCRUM-1"
  smoke_pr_number: 5
"""
                )

            config = load_setup_config(config_path)

        self.assertEqual(config.ngrok.auth_token, "token")
        self.assertFalse(config.ngrok.inspect)
        self.assertEqual(config.webhook_server.port, 8091)
        self.assertEqual(config.github_webhook.events, ("pull_request", "push"))
        self.assertEqual(config.checks.smoke_workflow_id, "SCRUM-1")
        self.assertEqual(config.checks.smoke_pr_number, 5)

    def test_build_ngrok_command_includes_addr_and_log_format(self):
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

    def test_build_signature_matches_github_header_shape(self):
        """Smoke-test signatures should use GitHub's X-Hub-Signature-256 format."""

        signature = build_signature("It's a Secret to Everybody", b"Hello World!")

        self.assertEqual(
            signature,
            "sha256=a4771c39fbe90f317c7824e83ddef3caae9cb3d976c214ace1f2937e133263c9",
        )

    def test_register_github_webhook_replaces_matching_url_and_posts_expected_payload(self):
        """Registration should delete a matching URL and create a repository webhook."""

        config = load_setup_config()
        session = FakeSession(
            [
                FakeResponse(payload=[{"id": 7, "name": "web", "config": {"url": "https://hook.example/webhooks/github"}}]),
                FakeResponse(status_code=204),
                FakeResponse(payload={"id": 8}),
            ]
        )
        client = GitHubHookClient(
            GitHubSettings(token="token", owner="owner", repo="repo", webhook_secret="secret"),
            session=session,
        )

        hook_id = register_github_webhook("https://hook.example/webhooks/github", "secret", config, client)

        self.assertEqual(hook_id, "8")
        self.assertEqual(session.calls[1]["method"], "DELETE")
        self.assertTrue(session.calls[1]["url"].endswith("/repos/owner/repo/hooks/7"))
        create_call = session.calls[2]
        self.assertEqual(create_call["method"], "POST")
        self.assertTrue(create_call["url"].endswith("/repos/owner/repo/hooks"))
        self.assertEqual(create_call["json"]["name"], "web")
        self.assertEqual(create_call["json"]["config"]["url"], "https://hook.example/webhooks/github")
        self.assertEqual(create_call["json"]["config"]["secret"], "secret")
        self.assertIn("pull_request", create_call["json"]["events"])


if __name__ == "__main__":
    unittest.main()
