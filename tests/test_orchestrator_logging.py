"""Tests for orchestrator logging startup wiring."""

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from orchestrator import cli
from orchestrator.logging_utils import get_logging_manager


class OrchestratorLoggingTestCase(unittest.TestCase):
    def test_status_command_configures_log_file_from_orchestrator_settings(self):
        previous_cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            config_dir = temp_root / "orchestrator"
            config_dir.mkdir()
            (config_dir / "config.yaml").write_text(
                """
orchestrator:
  storage_root: exports/.orchestrator
  exports_root: exports
  log_level: DEBUG
  log_file: exports/.orchestrator/logs/orchestrator.log
webhook_servers:
  auto_start: false
""",
                encoding="utf-8",
            )

            try:
                os.chdir(temp_root)
                stdout = io.StringIO()
                with contextlib.redirect_stdout(stdout):
                    result = cli.main(["status", "--json"])
            finally:
                os.chdir(previous_cwd)
                get_logging_manager().close()

            self.assertEqual(result, 0)
            self.assertEqual(json.loads(stdout.getvalue()), [])
            self.assertTrue((temp_root / "exports/.orchestrator/logs/orchestrator.log").exists())


if __name__ == "__main__":
    unittest.main()
