"""Tests for Codex analysis artifact generation."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from codex_analysis.runner import CodexCliRunner, CodexRunnerResult
from codex_analysis.service import CodexAnalysisService, create_codex_analysis_service
from codex_analysis.settings import CodexAnalysisSettings
from webhooks.models import WebhookEvent
from webhooks.worker import WebhookExportService


def webhook_event():
    """Return a representative normalized Jira event."""

    return WebhookEvent(
        provider="jira",
        event_id="evt-1",
        event_type="jira:issue_created",
        issue_key="SCRUM-1",
        issue_url="https://example.atlassian.net/browse/SCRUM-1",
        project_key="SCRUM",
        actor="dev@example.com",
        raw_payload={"webhookEvent": "jira:issue_created"},
    )


class FakeCodexRunner:
    """Fake runner that writes deterministic analysis output."""

    def __init__(self):
        """Initialize the fake runner."""

        self.prompts = []

    def run(self, prompt, repo_root, analysis_path, log_path):
        """Pretend to run Codex and write output files."""

        self.prompts.append(prompt)
        analysis_path.write_text("# Codex Analysis and Plan for SCRUM-1\n", encoding="utf-8")
        log_path.write_text("fake codex log\n", encoding="utf-8")
        return CodexRunnerResult(returncode=0, log_path=log_path, analysis_path=analysis_path)


class CodexAnalysisSettingsTestCase(unittest.TestCase):
    """Unit tests for Codex analysis settings."""

    def test_from_env_can_disable_analysis(self):
        """The factory should return None when analysis is disabled."""

        service = create_codex_analysis_service(env={"SPRINTER_CODEX_ANALYSIS_ENABLED": "false"})

        self.assertIsNone(service)

    def test_from_env_reads_package_defaults(self):
        """Package config should enable the analysis runner by default."""

        settings = CodexAnalysisSettings.from_env({})

        self.assertTrue(settings.enabled)
        self.assertEqual(settings.command, "codex")
        self.assertEqual(settings.sandbox, "read-only")

    def test_from_env_reads_repo_root_override(self):
        """Repo root can be overridden for non-source deployments."""

        settings = CodexAnalysisSettings.from_env({"SPRINTER_CODEX_ANALYSIS_REPO_ROOT": "/tmp/sprinter"})

        self.assertEqual(settings.repo_root, "/tmp/sprinter")


class CodexCliRunnerTestCase(unittest.TestCase):
    """Unit tests for Codex CLI command resolution."""

    def test_build_command_uses_path_match_when_available(self):
        """The runner should prefer PATH resolution for the configured command."""

        with patch("codex_analysis.runner.shutil.which", return_value="/custom/bin/codex"):
            runner = CodexCliRunner(CodexAnalysisSettings())
            command = runner._build_command(Path("."), Path("analysis.md"))

        self.assertEqual(command[0], "/custom/bin/codex")

    def test_build_command_falls_back_to_candidate_codex_binary(self):
        """Service-style environments may not expose Codex on PATH."""

        with tempfile.TemporaryDirectory() as temp_dir:
            fake_codex = Path(temp_dir) / "codex"
            fake_codex.write_text("#!/bin/sh\n", encoding="utf-8")
            fake_codex.chmod(0o755)

            with patch("codex_analysis.runner.shutil.which", return_value=None):
                runner = CodexCliRunner(CodexAnalysisSettings(), command_candidates=(fake_codex,))
                command = runner._build_command(Path("."), Path("analysis.md"))

        self.assertEqual(command[0], str(fake_codex))

    def test_build_command_keeps_explicit_path(self):
        """Explicit command paths should not be replaced by fallback lookup."""

        settings = CodexAnalysisSettings(command="/tmp/codex")
        runner = CodexCliRunner(settings)
        command = runner._build_command(Path("."), Path("analysis.md"))

        self.assertEqual(command[0], "/tmp/codex")


class CodexAnalysisServiceTestCase(unittest.TestCase):
    """Unit tests for analysis artifact creation."""

    def test_factory_defaults_repo_root_to_project_root_not_process_cwd(self):
        """MCP clients may start servers from a cwd outside the repository."""

        service = create_codex_analysis_service()

        self.assertIsNotNone(service)
        self.assertEqual(service.repo_root, Path(__file__).resolve().parents[1])

    def test_factory_uses_repo_root_override(self):
        """Explicit repo root settings should win over the package default."""

        with tempfile.TemporaryDirectory() as temp_dir:
            service = create_codex_analysis_service(env={"SPRINTER_CODEX_ANALYSIS_REPO_ROOT": temp_dir})

            self.assertIsNotNone(service)
            self.assertEqual(service.repo_root, Path(temp_dir).resolve())

    def test_analyze_export_writes_prompt_analysis_log_and_result(self):
        """Analysis service should create a complete codex_analysis packet."""

        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            issue_dir = repo_root / "exports" / "SCRUM-1"
            issue_dir.mkdir(parents=True)
            (issue_dir / "issue.json").write_text(json.dumps({"key": "SCRUM-1"}), encoding="utf-8")
            manifest_path = issue_dir / "export_manifest.json"
            manifest_path.write_text(json.dumps({"status": "success"}), encoding="utf-8")

            runner = FakeCodexRunner()
            service = CodexAnalysisService(CodexAnalysisSettings(), repo_root, runner)
            result = service.analyze_export(
                webhook_event(),
                {"issue_dir": str(issue_dir), "manifest_path": str(manifest_path)},
            )

            analysis_dir = issue_dir / "codex_analysis"
            self.assertTrue((analysis_dir / "codex_prompt.md").exists())
            self.assertTrue((analysis_dir / "analysis_and_plan.md").exists())
            self.assertTrue((analysis_dir / "codex_output.log").exists())
            self.assertTrue((analysis_dir / "analysis_result.json").exists())
            self.assertEqual(result["status"], "success")
            self.assertIn("exports/SCRUM-1/issue.json", runner.prompts[0])

    def test_webhook_export_service_records_analysis_in_manifest(self):
        """Webhook export adapter should add Codex analysis metadata after export."""

        class FakeExportService:
            def __init__(self, issue_dir):
                self.issue_dir = issue_dir

            def export_issue(self, ticket_url):
                manifest_path = os.path.join(self.issue_dir, "export_manifest.json")
                with open(manifest_path, "w", encoding="utf-8") as handle:
                    json.dump({"status": "success"}, handle)
                return {
                    "issue_key": "SCRUM-1",
                    "issue_dir": self.issue_dir,
                    "manifest_path": manifest_path,
                }

        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            issue_dir = repo_root / "exports" / "SCRUM-1"
            issue_dir.mkdir(parents=True)
            (issue_dir / "issue.json").write_text(json.dumps({"key": "SCRUM-1"}), encoding="utf-8")

            analysis_service = CodexAnalysisService(CodexAnalysisSettings(), repo_root, FakeCodexRunner())
            export_service = WebhookExportService(
                service=FakeExportService(str(issue_dir)),
                analysis_service=analysis_service,
            )

            result = export_service.export_event(webhook_event())

            self.assertIn("codex_analysis", result)
            with open(issue_dir / "export_manifest.json", "r", encoding="utf-8") as handle:
                manifest = json.load(handle)
            self.assertEqual(manifest["trigger"]["type"], "webhook")
            self.assertEqual(manifest["codex_analysis"]["status"], "success")


if __name__ == "__main__":
    unittest.main()
