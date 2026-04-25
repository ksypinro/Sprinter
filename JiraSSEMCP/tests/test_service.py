"""Tests for the JiraSSEMCP service facade."""

import os
import tempfile
import unittest

from JiraSSEMCP.app import create_sse_mcp
from JiraSSEMCP.service import JiraSSEService
from JiraSSEMCP.settings import JiraSSEMCPSettings


class FakeJiraFetcher:
    """Simple Jira test double for SSE service tests."""

    def fetch_issue(self, issue_key):
        """Return a minimal Jira issue payload."""

        return {
            "key": issue_key,
            "fields": {
                "attachment": [
                    {"id": "10", "filename": "artifact?.txt", "content": "https://files.example/artifact"},
                ]
            },
        }

    def fetch_comments(self, issue_key, page_size=100):
        """Return fake comments."""

        return [{"id": "c1"}]

    def fetch_worklogs(self, issue_key, page_size=100):
        """Return fake worklogs."""

        return [{"id": "w1"}]

    def fetch_changelog(self, issue_key, page_size=100):
        """Return fake changelog history."""

        return [{"id": "h1"}]

    def fetch_remote_links(self, issue_key):
        """Return one Confluence link."""

        return [{"object": {"url": "https://example.atlassian.net/wiki/pages/viewpage.action?pageId=123"}}]

    def download_attachment(self, url, dest_path):
        """Persist a small local file to simulate downloads."""

        with open(dest_path, "wb") as handle:
            handle.write(b"jira attachment")

    def create_issue(self, payload):
        """Return a synthetic Jira create-issue response."""

        return {"id": "10001", "key": "SCRUM-300", "self": "https://example.atlassian.net/rest/api/3/issue/10001"}


class FakeConfluenceFetcher:
    """Simple Confluence test double for SSE service tests."""

    def fetch_page(self, page_id):
        """Return a minimal page payload."""

        return {"id": page_id, "title": f"Page {page_id}", "body": {"storage": {"value": "<p>page</p>"}}}

    def fetch_page_ancestors(self, page_id):
        """Return a fake ancestor chain."""

        return [{"id": "1", "type": "page"}]

    def fetch_page_descendants(self, page_id, depth=5):
        """Return one child page for the root page."""

        if page_id == "123":
            return [{"id": "456", "type": "page"}]
        return []

    def fetch_page_footer_comments(self, page_id):
        """Return fake footer comments."""

        return [{"id": f"footer-{page_id}"}]

    def fetch_page_inline_comments(self, page_id):
        """Return fake inline comments."""

        return [{"id": f"inline-{page_id}"}]

    def fetch_page_attachments(self, page_id):
        """Return a fake attachment record."""

        return [{"id": f"a-{page_id}", "title": f"page-{page_id}.txt", "downloadLink": f"/download/{page_id}.txt"}]

    def download_attachment(self, url, dest_path):
        """Persist a small local file to simulate downloads."""

        with open(dest_path, "wb") as handle:
            handle.write(b"confluence attachment")

    def search_page_by_space_and_title(self, space_key, title):
        """Resolve no legacy links in these tests."""

        return None


class FakeJiraSSEService(JiraSSEService):
    """SSE service subclass that injects fake fetchers."""

    def __init__(self, export_root):
        """Initialize the fake service with a temporary export root."""

        super().__init__(config_path="unused.yaml")
        self.export_root = export_root
        self.fake_jira = FakeJiraFetcher()
        self.fake_confluence = FakeConfluenceFetcher()

    def _load_config(self):
        """Return a small in-memory config for tests."""

        return {
            "jira": {
                "base_url": "https://example.atlassian.net",
                "auth": {"type": "bearer", "token": "jira-token"},
            },
            "confluence": {
                "base_url": "https://example.atlassian.net/wiki",
                "auth": {"type": "bearer", "token": "conf-token"},
            },
            "requests": {
                "timeout_seconds": 30,
                "retries": 3,
                "page_size": 100,
                "log_level": "INFO",
            },
            "storage": {
                "export_path": self.export_root,
                "download_attachments": True,
                "include_confluence_descendants": True,
                "confluence_descendant_depth": 5,
            },
        }

    def _build_jira_fetcher(self, config):
        """Return the fake Jira client."""

        return self.fake_jira

    def _build_confluence_fetcher(self, config):
        """Return the fake Confluence client."""

        return self.fake_confluence

    def _configure_logging(self, config):
        """Skip root logging setup during tests."""

        return None


class JiraSSEServiceTestCase(unittest.TestCase):
    """Unit tests for the SSE service facade."""

    def test_export_issue_returns_sse_summary(self):
        """Exporting should return SSE transport metadata and resource URI."""

        with tempfile.TemporaryDirectory() as temp_dir:
            service = FakeJiraSSEService(temp_dir)
            result = service.export_issue("https://example.atlassian.net/browse/SCRUM-1")

            self.assertEqual(result["issue_key"], "SCRUM-1")
            self.assertEqual(result["transport"], "sse")
            self.assertEqual(result["manifest_resource"], "jirasse://exports/SCRUM-1/manifest")
            self.assertTrue(os.path.exists(result["manifest_path"]))
            self.assertEqual(service.read_export_manifest("SCRUM-1")["status"], "success")

    def test_create_issue_returns_sse_response_resource(self):
        """Creating should persist response artifacts and return a jirasse URI."""

        with tempfile.TemporaryDirectory() as temp_dir:
            service = FakeJiraSSEService(temp_dir)
            result = service.create_issue(
                {
                    "fields": {
                        "project": {"key": "SCRUM"},
                        "issuetype": {"name": "Task"},
                        "summary": "Created from SSE MCP",
                    }
                }
            )

            self.assertEqual(result["issue_key"], "SCRUM-300")
            self.assertEqual(result["transport"], "sse")
            self.assertEqual(result["response_resource"], "jirasse://created/SCRUM-300/response")
            self.assertTrue(os.path.exists(result["response_path"]))

    def test_create_sse_mcp_builds_app(self):
        """The app factory should build a FastMCP app without starting HTTP."""

        with tempfile.TemporaryDirectory() as temp_dir:
            service = FakeJiraSSEService(temp_dir)
            settings = JiraSSEMCPSettings(host="127.0.0.1", port=8889, sse_path="/events", message_path="/post/")
            app = create_sse_mcp(settings=settings, service=service)

            self.assertEqual(app.name, "JiraSSEMCP")


if __name__ == "__main__":
    unittest.main()
