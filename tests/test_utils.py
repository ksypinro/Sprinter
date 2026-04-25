"""Tests for standalone helpers in ``utils.py``."""

import os
import tempfile
import unittest

from utils import attachment_filename, extract_confluence_page_id, parse_jira_url, unique_path


class UtilsTestCase(unittest.TestCase):
    """Unit tests for path, URL, and naming helpers."""

    def test_parse_jira_url_accepts_expected_host(self):
        """A Jira URL from the configured host should yield an issue key."""

        issue_key = parse_jira_url(
            "https://example.atlassian.net/browse/SPR-42",
            expected_host="example.atlassian.net",
        )
        self.assertEqual(issue_key, "SPR-42")

    def test_parse_jira_url_rejects_wrong_host(self):
        """A Jira URL from another host should be ignored."""

        issue_key = parse_jira_url(
            "https://other.atlassian.net/browse/SPR-42",
            expected_host="example.atlassian.net",
        )
        self.assertIsNone(issue_key)

    def test_extract_confluence_page_id_from_query(self):
        """A Confluence viewpage URL should resolve its query-string page id."""

        page_id = extract_confluence_page_id(
            "https://example.atlassian.net/wiki/pages/viewpage.action?pageId=12345",
            expected_host="example.atlassian.net",
        )
        self.assertEqual(page_id, "12345")

    def test_extract_confluence_page_id_from_path(self):
        """A Confluence path-style URL should resolve its embedded page id."""

        page_id = extract_confluence_page_id(
            "https://example.atlassian.net/wiki/spaces/ENG/pages/98765/Runbook",
            expected_host="example.atlassian.net",
        )
        self.assertEqual(page_id, "98765")

    def test_attachment_filename_prefixes_attachment_id(self):
        """Attachment filenames should include ids and sanitized names."""

        self.assertEqual(attachment_filename(7, "log?.txt"), "7_log_.txt")

    def test_unique_path_appends_suffix_on_collision(self):
        """A colliding output path should gain a numeric suffix."""

        with tempfile.TemporaryDirectory() as temp_dir:
            original = os.path.join(temp_dir, "artifact.txt")
            with open(original, "w", encoding="utf-8") as handle:
                handle.write("hello")

            candidate = unique_path(original)
            self.assertTrue(candidate.endswith("artifact_1.txt"))

    def test_resolve_url_preserves_context_path(self):
        """Relative URLs should preserve Atlassian context paths like /wiki."""

        from utils import resolve_url
        base = "https://example.atlassian.net/wiki"
        # Leading slash should keep the context path
        self.assertEqual(resolve_url(base, "/api/v2"), "https://example.atlassian.net/wiki/api/v2")
        # Relative path should append
        self.assertEqual(resolve_url(base, "api/v2"), "https://example.atlassian.net/wiki/api/v2")
        # Absolute URL should remain absolute
        self.assertEqual(resolve_url(base, "https://other.com/api"), "https://other.com/api")


if __name__ == "__main__":
    unittest.main()
