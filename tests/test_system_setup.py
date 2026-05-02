"""Tests for the local system setup helper."""

from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import yaml

import systemSetup


class SystemSetupWebhookConfigTestCase(unittest.TestCase):
    def test_ensure_orchestrator_webhook_autostart_adds_missing_section(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "orchestrator" / "config.yaml"
            config_path.parent.mkdir(parents=True)
            config_path.write_text("orchestrator:\n  storage_root: exports/.orchestrator\n", encoding="utf-8")

            self.assertTrue(self._run_with_config(config_path))

            data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            servers = data["webhook_servers"]
            self.assertTrue(servers["auto_start"])
            self.assertTrue(servers["jira"]["enabled"])
            self.assertEqual(servers["jira"]["port"], 8090)
            self.assertTrue(servers["github"]["enabled"])
            self.assertEqual(servers["github"]["port"], 8091)

    def test_ensure_orchestrator_webhook_autostart_preserves_existing_endpoints(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "orchestrator" / "config.yaml"
            config_path.parent.mkdir(parents=True)
            config_path.write_text(
                "\n".join(
                    [
                        "webhook_servers:",
                        "  auto_start: false",
                        "  jira:",
                        "    enabled: false",
                        "    host: 0.0.0.0",
                        "    port: 19090",
                        "    path: /custom/jira",
                        "  github:",
                        "    enabled: false",
                        "    host: 0.0.0.0",
                        "    port: 19091",
                        "    path: /custom/github",
                    ]
                ),
                encoding="utf-8",
            )

            self.assertTrue(self._run_with_config(config_path))

            data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            servers = data["webhook_servers"]
            self.assertTrue(servers["auto_start"])
            self.assertTrue(servers["jira"]["enabled"])
            self.assertEqual(servers["jira"]["host"], "0.0.0.0")
            self.assertEqual(servers["jira"]["port"], 19090)
            self.assertEqual(servers["jira"]["path"], "/custom/jira")
            self.assertTrue(servers["github"]["enabled"])
            self.assertEqual(servers["github"]["host"], "0.0.0.0")
            self.assertEqual(servers["github"]["port"], 19091)
            self.assertEqual(servers["github"]["path"], "/custom/github")

    def test_start_stack_args_are_parsed(self):
        args = systemSetup.parse_args(["--start-stack", "--router-port", "18888"])

        self.assertTrue(args.start_stack)
        self.assertEqual(args.router_port, 18888)

    def test_build_router_script_includes_configured_webhook_routes(self):
        endpoints = {
            "jira": {"host": "127.0.0.1", "port": 19090, "path": "/custom/jira"},
            "github": {"host": "127.0.0.1", "port": 19091, "path": "/custom/github"},
        }

        script = systemSetup.build_router_script("127.0.0.1", 18888, endpoints)

        self.assertIn("/custom/jira", script)
        self.assertIn("/custom/github", script)
        self.assertIn("19090", script)
        self.assertIn("19091", script)

    def test_delete_stale_ngrok_github_hooks_only_removes_matching_path(self):
        class FakeHookClient:
            def __init__(self):
                self.deleted = []

            def list_hooks(self):
                return [
                    {"id": 1, "name": "web", "config": {"url": "https://old.ngrok-free.dev/webhooks/github"}},
                    {"id": 2, "name": "web", "config": {"url": "https://old.ngrok-free.dev/other"}},
                    {"id": 3, "name": "web", "config": {"url": "https://example.com/webhooks/github"}},
                ]

            def delete_hook(self, hook_id):
                self.deleted.append(hook_id)

        client = FakeHookClient()

        deleted = systemSetup.delete_stale_ngrok_github_hooks(client, "https://new.ngrok-free.dev/webhooks/github")

        self.assertEqual(deleted, ["1"])
        self.assertEqual(client.deleted, [1])

    def _run_with_config(self, config_path: Path) -> bool:
        old_path = systemSetup.ORCHESTRATOR_CONFIG_FILE
        systemSetup.ORCHESTRATOR_CONFIG_FILE = config_path
        try:
            with redirect_stdout(io.StringIO()):
                return systemSetup.ensure_orchestrator_webhook_autostart()
        finally:
            systemSetup.ORCHESTRATOR_CONFIG_FILE = old_path


if __name__ == "__main__":
    unittest.main()
