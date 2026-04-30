"""Tests for Codex implementation artifact generation."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from codex_implementer.runner import CodexCliImplementerRunner, CodexImplementerRunnerResult
from codex_implementer.service import CodexImplementerService, create_codex_implementer_service
from codex_implementer.settings import CodexImplementerSettings, CodexImplementerSettingsError


class FakeImplementerRunner:
    """Fake Codex implementer runner for deterministic service tests."""

    def __init__(self, write_commit_log=True):
        self.prompts = []
        self.write_commit_log = write_commit_log

    def run(self, prompt, repo_root, output_path, log_path):
        self.prompts.append(prompt)
        output_path.write_text("Implementation completed.\n", encoding="utf-8")
        log_path.write_text("fake implementer log\n", encoding="utf-8")
        commit_log_path = output_path.parent / "commit_log.md"
        if self.write_commit_log:
            commit_log_path.write_text(
                "\n".join(
                    [
                        "# Implementation Commit Log",
                        "## Summary",
                        "Updated the smoke file.",
                        "## Files Changed",
                        "- app.txt: changed smoke content.",
                        "## Verification",
                        "- Fake runner.",
                        "## Observations",
                        "None",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
        return CodexImplementerRunnerResult(returncode=0, log_path=log_path, output_path=output_path)


class CodexImplementerSettingsTestCase(unittest.TestCase):
    """Unit tests for Codex implementer settings."""

    def test_from_env_can_disable_implementer(self):
        """The factory should return None when implementation is disabled."""

        service = create_codex_implementer_service(env={"SPRINTER_CODEX_IMPLEMENTER_ENABLED": "false"})

        self.assertIsNone(service)

    def test_from_env_reads_package_defaults(self):
        """Package config should enable workspace-write implementation by default."""

        settings = CodexImplementerSettings.from_env({})

        self.assertTrue(settings.enabled)
        self.assertEqual(settings.command, "codex")
        self.assertEqual(settings.sandbox, "workspace-write")
        self.assertEqual(settings.commit_log_file_name, "commit_log.md")

    def test_read_only_sandbox_is_rejected(self):
        """Implementation requires a write-enabled Codex sandbox."""

        with self.assertRaises(CodexImplementerSettingsError):
            CodexImplementerSettings(sandbox="read-only").validate()


class CodexCliImplementerRunnerTestCase(unittest.TestCase):
    """Unit tests for Codex implementer CLI command resolution."""

    def test_build_command_uses_workspace_write_and_output_file(self):
        """The runner should pass workspace-write and output-last-message."""

        with patch("codex_implementer.runner.shutil.which", return_value="/custom/bin/codex"):
            runner = CodexCliImplementerRunner(CodexImplementerSettings())
            command = runner._build_command(Path("."), Path("codex_output.md"))

        self.assertEqual(command[0], "/custom/bin/codex")
        self.assertIn("workspace-write", command)
        self.assertIn("codex_output.md", command)

    def test_build_command_keeps_explicit_path(self):
        """Explicit command paths should not be replaced by fallback lookup."""

        settings = CodexImplementerSettings(command="/tmp/codex")
        runner = CodexCliImplementerRunner(settings)
        command = runner._build_command(Path("."), Path("codex_output.md"))

        self.assertEqual(command[0], "/tmp/codex")


class CodexImplementerServiceTestCase(unittest.TestCase):
    """Unit tests for implementer artifact creation."""

    def test_implement_plan_writes_prompt_commit_log_and_result(self):
        """Implementer service should create a complete implementation packet."""

        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            issue_dir = repo_root / "exports" / "SCRUM-1"
            analysis_dir = issue_dir / "codex_analysis"
            analysis_dir.mkdir(parents=True)
            analysis_path = analysis_dir / "analysis_and_plan.md"
            analysis_path.write_text("# Codex Analysis and Plan for SCRUM-1\n", encoding="utf-8")

            runner = FakeImplementerRunner()
            service = CodexImplementerService(CodexImplementerSettings(), repo_root, runner)
            result = service.implement_plan({"analysis_path": str(analysis_path)})

            implementation_dir = issue_dir / "codex_implementation"
            self.assertTrue((implementation_dir / "implementer_prompt.md").exists())
            self.assertTrue((implementation_dir / "codex_output.md").exists())
            self.assertTrue((implementation_dir / "codex_implementer.log").exists())
            self.assertTrue((implementation_dir / "implementation_result.json").exists())
            self.assertTrue((implementation_dir / "commit_log.md").exists())
            self.assertEqual(result["status"], "success")
            self.assertIn("exports/SCRUM-1/codex_analysis/analysis_and_plan.md", runner.prompts[0])

            saved = json.loads((implementation_dir / "implementation_result.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["commit_log_path"], str(implementation_dir / "commit_log.md"))

    def test_implement_plan_fails_when_commit_log_is_missing(self):
        """The service should fail if Codex does not write commit_log.md."""

        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            issue_dir = repo_root / "exports" / "SCRUM-1"
            analysis_dir = issue_dir / "codex_analysis"
            analysis_dir.mkdir(parents=True)
            analysis_path = analysis_dir / "analysis_and_plan.md"
            analysis_path.write_text("# Plan\n", encoding="utf-8")

            service = CodexImplementerService(
                CodexImplementerSettings(),
                repo_root,
                FakeImplementerRunner(write_commit_log=False),
            )

            with self.assertRaises(ValueError):
                service.implement_plan({"analysis_path": str(analysis_path)})

    def test_implement_plan_resolves_analysis_from_issue_dir(self):
        """Payloads may provide issue_dir instead of a direct analysis path."""

        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            issue_dir = repo_root / "exports" / "SCRUM-1"
            analysis_dir = issue_dir / "codex_analysis"
            analysis_dir.mkdir(parents=True)
            (analysis_dir / "analysis_and_plan.md").write_text("# Plan\n", encoding="utf-8")

            service = CodexImplementerService(CodexImplementerSettings(), repo_root, FakeImplementerRunner())
            result = service.implement_plan({"issue_dir": str(issue_dir)})

            self.assertEqual(result["status"], "success")


if __name__ == "__main__":
    unittest.main()
