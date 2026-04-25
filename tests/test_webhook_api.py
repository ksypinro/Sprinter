"""Tests for the Jira webhook API package."""

import unittest

from fetcher import AuthConfig
from webhookAPI.client import JiraWebhookAPIClient, JiraWebhookAPIError


class FakeResponse:
    """Small response test double for webhook API client tests."""

    def __init__(self, url="https://example.atlassian.net/rest/test", status_code=200, payload=None, text=""):
        """Initialize fake response fields."""

        self.url = url
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text
        self.content = b"{}" if payload is not None else b""

    def json(self):
        """Return the configured JSON payload."""

        return self._payload

    def raise_for_status(self):
        """Raise an HTTPError-like exception for failures."""

        if self.status_code >= 400:
            import requests

            raise requests.HTTPError("boom")


class FakeSession:
    """Fake requests session that records calls."""

    def __init__(self, response):
        """Initialize the session with one response."""

        self.response = response
        self.headers = {}
        self.auth = None
        self.calls = []

    def request(self, method, url, **kwargs):
        """Record one request call and return the fake response."""

        self.calls.append({"method": method, "url": url, **kwargs})
        return self.response


class WebhookAPIClientTestCase(unittest.TestCase):
    """Unit tests for Jira webhook API clients."""

    def make_client(self, response=None):
        """Build a client with a fake session."""

        client = JiraWebhookAPIClient(
            "https://example.atlassian.net",
            AuthConfig(auth_type="basic", email="dev@example.com", token="token"),
        )
        client.session = FakeSession(response or FakeResponse(payload={"ok": True}))
        return client

    def test_create_admin_webhook_posts_expected_payload(self):
        """Admin webhook creation should use Jira's admin webhook endpoint."""

        client = self.make_client(FakeResponse(payload={"id": 72}))
        result = client.create_admin_webhook(
            name="Sprinter",
            description="Export issues",
            url="https://webhooks.example.com/webhooks/jira",
            events=("jira:issue_created", "jira:issue_updated"),
            jql_filter="project = SCRUM",
            secret="secret",
        )

        call = client.session.calls[0]
        self.assertEqual(result, {"id": 72})
        self.assertEqual(call["method"], "POST")
        self.assertTrue(call["url"].endswith("/rest/webhooks/1.0/webhook"))
        self.assertEqual(call["json"]["name"], "Sprinter")
        self.assertEqual(call["json"]["filters"]["issue-related-events-section"], "project = SCRUM")
        self.assertEqual(call["json"]["secret"], "secret")
        self.assertFalse(call["json"]["excludeBody"])

    def test_delete_admin_webhook_uses_admin_endpoint(self):
        """Admin webhook deletion should target one webhook id."""

        client = self.make_client(FakeResponse(payload=None))
        result = client.delete_admin_webhook(72)

        call = client.session.calls[0]
        self.assertEqual(result, {"deleted": True, "webhook_id": "72", "api": "admin"})
        self.assertEqual(call["method"], "DELETE")
        self.assertTrue(call["url"].endswith("/rest/webhooks/1.0/webhook/72"))

    def test_dynamic_refresh_uses_dynamic_endpoint(self):
        """Dynamic refresh should call Jira's dynamic webhook refresh endpoint."""

        client = self.make_client(FakeResponse(payload={"expirationDate": "2026-05-01T00:00:00.000+0000"}))
        result = client.refresh_dynamic_webhooks([1000, "1001"])

        call = client.session.calls[0]
        self.assertEqual(result["expirationDate"], "2026-05-01T00:00:00.000+0000")
        self.assertEqual(call["method"], "PUT")
        self.assertTrue(call["url"].endswith("/rest/api/3/webhook/refresh"))
        self.assertEqual(call["json"], {"webhookIds": [1000, 1001]})

    def test_dynamic_delete_sends_ids_in_body(self):
        """Dynamic delete should send Jira's expected webhookIds payload."""

        client = self.make_client(FakeResponse(payload=None))
        result = client.delete_dynamic_webhooks(["1000", "1001"])

        call = client.session.calls[0]
        self.assertEqual(result, {"deleted": True, "webhook_ids": [1000, 1001], "api": "dynamic"})
        self.assertEqual(call["method"], "DELETE")
        self.assertTrue(call["url"].endswith("/rest/api/3/webhook"))
        self.assertEqual(call["json"], {"webhookIds": [1000, 1001]})

    def test_http_errors_are_wrapped(self):
        """Failed Jira responses should surface as JiraWebhookAPIError."""

        client = self.make_client(FakeResponse(status_code=403, text="forbidden"))

        with self.assertRaises(JiraWebhookAPIError):
            client.get_admin_webhooks()


if __name__ == "__main__":
    unittest.main()
