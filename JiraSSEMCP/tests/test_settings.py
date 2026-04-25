"""Tests for JiraSSEMCP settings."""

import unittest

from JiraSSEMCP.settings import JiraSSEMCPSettings, JiraSSEMCPSettingsError


class JiraSSEMCPSettingsTestCase(unittest.TestCase):
    """Unit tests for environment-backed SSE MCP settings."""

    def test_from_env_uses_overrides(self):
        """Environment values should override SSE server defaults."""

        settings = JiraSSEMCPSettings.from_env(
            {
                "JIRA_SSE_MCP_HOST": "0.0.0.0",
                "JIRA_SSE_MCP_PORT": "9101",
                "JIRA_SSE_MCP_MOUNT_PATH": "/jira",
                "JIRA_SSE_MCP_SSE_PATH": "/events",
                "JIRA_SSE_MCP_MESSAGE_PATH": "/post/",
                "JIRA_SSE_MCP_CONFIG": "/tmp/sprinter.yaml",
                "JIRA_SSE_MCP_LOG_LEVEL": "debug",
            }
        )

        self.assertEqual(settings.host, "0.0.0.0")
        self.assertEqual(settings.port, 9101)
        self.assertEqual(settings.mount_path, "/jira")
        self.assertEqual(settings.sse_path, "/events")
        self.assertEqual(settings.message_path, "/post/")
        self.assertEqual(settings.config_path, "/tmp/sprinter.yaml")
        self.assertEqual(settings.log_level, "DEBUG")

    def test_from_env_rejects_invalid_sse_path(self):
        """The SSE path must be absolute."""

        with self.assertRaisesRegex(JiraSSEMCPSettingsError, "must start"):
            JiraSSEMCPSettings.from_env({"JIRA_SSE_MCP_SSE_PATH": "sse"})


if __name__ == "__main__":
    unittest.main()
