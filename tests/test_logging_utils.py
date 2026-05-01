"""Tests for Sprinter's shared logging configuration."""

import logging
import io
import tempfile
import unittest
from pathlib import Path

from orchestrator.logging_utils import (
    SprinterLoggingManager,
    attach_file_handler,
    ensure_logging,
    get_logging_manager,
    remove_and_close_handler,
)


class LoggingUtilsTestCase(unittest.TestCase):
    def setUp(self):
        self._previous_level = logging.getLogger().level

    def tearDown(self):
        get_logging_manager().close()
        logging.getLogger().setLevel(self._previous_level)

    def test_manager_creates_parent_directory_and_writes_log_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "nested" / "sprinter.log"
            manager = SprinterLoggingManager().configure("INFO", log_path, console=False)
            try:
                logging.getLogger("sprinter.test").info("durable message")
            finally:
                manager.close()

            self.assertTrue(log_path.exists())
            self.assertIn("durable message", log_path.read_text(encoding="utf-8"))

    def test_repeated_configure_does_not_duplicate_file_handlers(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "sprinter.log"
            manager = SprinterLoggingManager()
            try:
                manager.configure("INFO", log_path, console=False)
                manager.configure("INFO", log_path, console=False)
                logging.getLogger("sprinter.test").info("only once")
            finally:
                manager.close()

            self.assertEqual(log_path.read_text(encoding="utf-8").count("only once"), 1)

    def test_close_removes_and_closes_owned_handlers(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "sprinter.log"
            manager = SprinterLoggingManager().configure("INFO", log_path, console=False)
            handler = manager.handlers[0]

            self.assertIn(handler, logging.getLogger().handlers)
            manager.close()

            self.assertNotIn(handler, logging.getLogger().handlers)
            self.assertIsNone(handler.stream)

    def test_attach_file_handler_can_be_removed_without_closing_base_logging(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base_log = Path(temp_dir) / "base.log"
            export_log = Path(temp_dir) / "exports" / "SCRUM-14" / "export.log"
            manager = get_logging_manager().configure("INFO", base_log, console=False)
            handler = attach_file_handler(export_log)
            try:
                logging.info("base and export")
            finally:
                remove_and_close_handler(handler)

            logging.info("base only")
            manager.close()

            self.assertIn("base and export", base_log.read_text(encoding="utf-8"))
            self.assertIn("base only", base_log.read_text(encoding="utf-8"))
            self.assertIn("base and export", export_log.read_text(encoding="utf-8"))
            self.assertNotIn("base only", export_log.read_text(encoding="utf-8"))

    def test_ensure_logging_preserves_existing_process_log_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "server.log"
            manager = get_logging_manager().configure("INFO", log_path, console=False)
            ensure_logging("DEBUG", console=True, stream=io.StringIO())
            try:
                logging.debug("still in server log")
            finally:
                manager.close()

            self.assertIn("still in server log", log_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
