"""Tests for JiraStreamableMCP settings."""

import unittest

from JiraStreamableMCP.settings import JiraStreamableMCPSettings, JiraStreamableMCPSettingsError


class JiraStreamableMCPSettingsTestCase(unittest.TestCase):
    """Unit tests for environment-backed HTTP MCP settings."""

    def test_from_env_uses_overrides(self):
        """Environment values should override HTTP server defaults."""

        settings = JiraStreamableMCPSettings.from_env(
            {
                "JIRA_STREAMABLE_MCP_HOST": "0.0.0.0",
                "JIRA_STREAMABLE_MCP_PORT": "9001",
                "JIRA_STREAMABLE_MCP_PATH": "/jira-mcp",
                "JIRA_STREAMABLE_MCP_CONFIG": "/tmp/sprinter.yaml",
                "JIRA_STREAMABLE_MCP_LOG_LEVEL": "debug",
                "JIRA_STREAMABLE_MCP_STATELESS_HTTP": "true",
                "JIRA_STREAMABLE_MCP_CORS_ENABLED": "true",
                "JIRA_STREAMABLE_MCP_CORS_ORIGINS": "http://localhost:5173,https://tools.example",
                "JIRA_STREAMABLE_MCP_CORS_ALLOW_CREDENTIALS": "true",
            }
        )

        self.assertEqual(settings.host, "0.0.0.0")
        self.assertEqual(settings.port, 9001)
        self.assertEqual(settings.path, "/jira-mcp")
        self.assertEqual(settings.config_path, "/tmp/sprinter.yaml")
        self.assertEqual(settings.log_level, "DEBUG")
        self.assertTrue(settings.stateless_http)
        self.assertTrue(settings.cors_enabled)
        self.assertEqual(settings.cors_origins, ("http://localhost:5173", "https://tools.example"))
        self.assertTrue(settings.cors_allow_credentials)

    def test_from_env_rejects_invalid_path(self):
        """The streamable HTTP path must be absolute."""

        with self.assertRaisesRegex(JiraStreamableMCPSettingsError, "must start"):
            JiraStreamableMCPSettings.from_env({"JIRA_STREAMABLE_MCP_PATH": "mcp"})

    def test_from_env_rejects_empty_cors_origins_when_enabled(self):
        """CORS must have at least one allowed origin when enabled."""

        with self.assertRaisesRegex(JiraStreamableMCPSettingsError, "CORS_ORIGINS"):
            JiraStreamableMCPSettings.from_env(
                {
                    "JIRA_STREAMABLE_MCP_CORS_ENABLED": "true",
                    "JIRA_STREAMABLE_MCP_CORS_ORIGINS": "",
                }
            )

    def test_from_env_rejects_wildcard_origin_with_credentials(self):
        """Credentialed CORS cannot use the wildcard origin."""

        with self.assertRaisesRegex(JiraStreamableMCPSettingsError, "cannot include"):
            JiraStreamableMCPSettings.from_env(
                {
                    "JIRA_STREAMABLE_MCP_CORS_ORIGINS": "*",
                    "JIRA_STREAMABLE_MCP_CORS_ALLOW_CREDENTIALS": "true",
                }
            )


if __name__ == "__main__":
    unittest.main()
