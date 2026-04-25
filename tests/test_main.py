"""Tests for the export orchestration layer in ``main.py``."""

import json
import logging
import os
import tempfile
import unittest

from main import (
    attach_file_logging,
    build_run_manifest,
    create_jira_issue_from_file,
    collect_confluence_page_ids,
    export_confluence_content_with_manifest,
    export_jira_issue,
    finalize_run_manifest,
    load_ticket_payload,
    load_config,
    write_manifest,
)


class FakeJiraFetcher:
    """Minimal Jira fetcher test double used to isolate orchestration logic."""

    def __init__(self):
        """Initialize download tracking for assertions."""

        self.downloads = []

    def fetch_issue(self, issue_key):
        """Return a small synthetic Jira issue payload for tests."""

        return {
            "key": issue_key,
            "fields": {
                "attachment": [
                    {"id": "10", "filename": "report?.txt", "content": "https://files.example/report"},
                ]
            },
        }

    def fetch_comments(self, issue_key, page_size=100):
        """Return fake comments without touching the network."""

        return [{"id": "c1", "body": "hello"}]

    def fetch_worklogs(self, issue_key, page_size=100):
        """Return fake worklogs without touching the network."""

        return [{"id": "w1"}]

    def fetch_changelog(self, issue_key, page_size=100):
        """Return fake changelog entries without touching the network."""

        return [{"id": "h1"}]

    def fetch_remote_links(self, issue_key):
        """Return a Jira remote link that points to Confluence."""

        return [{"object": {"url": "https://example.atlassian.net/wiki/pages/viewpage.action?pageId=123"}}]

    def create_issue(self, payload):
        """Return a synthetic create-issue response without touching Jira."""

        return {"id": "10001", "key": "SPR-100", "self": "https://example.atlassian.net/rest/api/3/issue/10001"}

    def download_attachment(self, url, dest_path):
        """Persist a tiny local file to simulate attachment download."""

        self.downloads.append((url, dest_path))
        with open(dest_path, "wb") as handle:
            handle.write(b"jira attachment")


class FakeConfluenceFetcher:
    """Minimal Confluence fetcher test double used by export tests."""

    def __init__(self):
        """Initialize download tracking for assertions."""

        self.downloads = []

    def fetch_page(self, page_id):
        """Return a synthetic page payload for the given page id."""

        return {
            "id": page_id,
            "title": f"Page {page_id}",
            "body": {"storage": {"value": f"<p>{page_id}</p>"}},
        }

    def search_page_by_space_and_title(self, space_key, title):
        """Resolve a legacy display URL to a page id for one known test case."""

        if space_key == "SPACE" and title == "Runbook":
            return "999"
        return None

    def fetch_page_ancestors(self, page_id):
        """Return a stub ancestor chain for tests."""

        return [{"id": "1", "type": "page"}]

    def fetch_page_descendants(self, page_id, depth=5):
        """Return one child page for the root page under test."""

        if page_id == "123":
            return [{"id": "456", "type": "page"}]
        return []

    def fetch_page_footer_comments(self, page_id):
        """Return a stub footer comment collection."""

        return [{"id": f"footer-{page_id}"}]

    def fetch_page_inline_comments(self, page_id):
        """Return a stub inline comment collection."""

        return [{"id": f"inline-{page_id}"}]

    def fetch_page_attachments(self, page_id):
        """Return a stub attachment record for the requested page."""

        return [{"id": f"a-{page_id}", "title": f"doc-{page_id}.txt", "downloadLink": f"/download/{page_id}.txt"}]

    def download_attachment(self, url, dest_path):
        """Persist a tiny local file to simulate attachment download."""

        self.downloads.append((url, dest_path))
        with open(dest_path, "wb") as handle:
            handle.write(b"confluence attachment")


class MainTestCase(unittest.TestCase):
    """Unit tests covering the top-level export orchestration behavior."""

    def test_load_config_uses_defaults_and_requires_sections(self):
        """Config loading should inject defaults into a minimal valid config."""

        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = os.path.join(temp_dir, "config.yaml")
            with open(config_path, "w", encoding="utf-8") as handle:
                handle.write(
                    """
jira:
  base_url: "https://example.atlassian.net"
  auth:
    type: "bearer"
    token: "jira-token"
confluence:
  base_url: "https://example.atlassian.net/wiki"
  auth:
    type: "bearer"
    token: "conf-token"
storage:
  export_path: "./exports"
"""
                )

            config = load_config(config_path)
            self.assertEqual(config["requests"]["timeout_seconds"], 30)
            self.assertTrue(config["storage"]["download_attachments"])

    def test_collect_confluence_page_ids_separates_unresolved_links(self):
        """Resolvable page ids and unresolved same-host links should be split."""

        remote_links = [
            {"object": {"url": "https://example.atlassian.net/wiki/pages/viewpage.action?pageId=123"}},
            {"object": {"url": "https://example.atlassian.net/wiki/display/SPACE/Runbook"}},
            {"object": {"url": "https://other.example/wiki/pages/viewpage.action?pageId=999"}},
        ]
        page_ids, unresolved = collect_confluence_page_ids(remote_links, "https://example.atlassian.net/wiki")
        self.assertEqual(page_ids, ["123"])
        self.assertEqual(len(unresolved), 1)

    def test_collect_confluence_page_ids_resolves_display_links_with_fetcher(self):
        """Legacy display links should resolve through Confluence search."""

        remote_links = [
            {"object": {"url": "https://example.atlassian.net/wiki/display/SPACE/Runbook"}},
        ]
        page_ids, unresolved = collect_confluence_page_ids(
            remote_links,
            "https://example.atlassian.net/wiki",
            confluence_fetcher=FakeConfluenceFetcher(),
        )
        self.assertEqual(page_ids, ["999"])
        self.assertEqual(unresolved, [])

    def test_export_jira_issue_writes_complete_bundle(self):
        """Jira export should write all expected issue artifacts and files."""

        fetcher = FakeJiraFetcher()
        with tempfile.TemporaryDirectory() as temp_dir:
            issue_dir = os.path.join(temp_dir, "SPR-42")
            remote_links = export_jira_issue(
                fetcher,
                "SPR-42",
                issue_dir,
                page_size=100,
                download_attachments=True,
            )

            self.assertTrue(os.path.exists(os.path.join(issue_dir, "issue.json")))
            self.assertTrue(os.path.exists(os.path.join(issue_dir, "comments.json")))
            self.assertTrue(os.path.exists(os.path.join(issue_dir, "worklogs.json")))
            self.assertTrue(os.path.exists(os.path.join(issue_dir, "changelog.json")))
            self.assertTrue(os.path.exists(os.path.join(issue_dir, "remote_links.json")))
            self.assertEqual(remote_links[0]["object"]["url"], "https://example.atlassian.net/wiki/pages/viewpage.action?pageId=123")
            self.assertEqual(len(fetcher.downloads), 1)
            self.assertTrue(fetcher.downloads[0][1].endswith("10_report_.txt"))

    def test_export_confluence_content_exports_root_and_descendants(self):
        """Confluence export should persist root pages and traversed children."""

        fetcher = FakeConfluenceFetcher()
        remote_links = [{"object": {"url": "https://example.atlassian.net/wiki/pages/viewpage.action?pageId=123"}}]

        with tempfile.TemporaryDirectory() as temp_dir:
            issue_dir = os.path.join(temp_dir, "SPR-42")
            os.makedirs(issue_dir, exist_ok=True)

            manifest = export_confluence_content_with_manifest(
                fetcher,
                remote_links,
                issue_dir,
                confluence_base_url="https://example.atlassian.net/wiki",
                descendant_depth=5,
                include_descendants=True,
                download_attachments=True,
            )

            linked_pages_path = os.path.join(issue_dir, "wiki", "linked_pages.json")
            with open(linked_pages_path, "r", encoding="utf-8") as handle:
                linked_pages = json.load(handle)

            self.assertEqual(linked_pages, ["123"])
            self.assertTrue(os.path.exists(os.path.join(issue_dir, "wiki", "page_123", "page.json")))
            self.assertTrue(os.path.exists(os.path.join(issue_dir, "wiki", "page_456", "page.json")))
            self.assertEqual(len(fetcher.downloads), 2)
            self.assertEqual(manifest["exported_pages"], ["123", "456"])

    def test_load_ticket_payload_validates_required_fields(self):
        """Ticket payloads should require Jira create-issue essentials."""

        with tempfile.TemporaryDirectory() as temp_dir:
            ticket_file = os.path.join(temp_dir, "ticket.json")
            with open(ticket_file, "w", encoding="utf-8") as handle:
                json.dump({"fields": {"project": {"key": "SPR"}, "summary": "Missing issue type"}}, handle)

            with self.assertRaisesRegex(Exception, "fields.issuetype"):
                load_ticket_payload(ticket_file)

    def test_create_jira_issue_from_file_writes_request_and_response(self):
        """Create workflow should persist both the request payload and Jira response."""

        fetcher = FakeJiraFetcher()
        with tempfile.TemporaryDirectory() as temp_dir:
            ticket_file = os.path.join(temp_dir, "ticket.json")
            with open(ticket_file, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "fields": {
                            "project": {"key": "SPR"},
                            "issuetype": {"name": "Task"},
                            "summary": "Created from json",
                        }
                    },
                    handle,
                )

            issue_dir, payload, response = create_jira_issue_from_file(fetcher, ticket_file, temp_dir)

            self.assertEqual(response["key"], "SPR-100")
            self.assertEqual(payload["fields"]["summary"], "Created from json")
            self.assertTrue(os.path.exists(os.path.join(issue_dir, "ticket_request.json")))
            self.assertTrue(os.path.exists(os.path.join(issue_dir, "ticket_response.json")))

    def test_manifest_and_file_logging_write_artifacts(self):
        """Manifest and log helpers should write durable run artifacts."""

        with tempfile.TemporaryDirectory() as temp_dir:
            manifest = build_run_manifest("https://example.atlassian.net/browse/SPR-42", "SPR-42")
            logger = logging.getLogger()
            previous_level = logger.level
            logger.setLevel(logging.INFO)
            handler = attach_file_logging(os.path.join(temp_dir, "export.log"))
            try:
                logging.info("hello manifest")
            finally:
                logger.removeHandler(handler)
                handler.close()
                logger.setLevel(previous_level)

            finalize_run_manifest(manifest, "success")
            write_manifest(temp_dir, manifest)

            with open(os.path.join(temp_dir, "export_manifest.json"), "r", encoding="utf-8") as handle:
                persisted_manifest = json.load(handle)

            with open(os.path.join(temp_dir, "export.log"), "r", encoding="utf-8") as handle:
                log_text = handle.read()

            self.assertEqual(persisted_manifest["status"], "success")
            self.assertIn("hello manifest", log_text)


if __name__ == "__main__":
    unittest.main()
