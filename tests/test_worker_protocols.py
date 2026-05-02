"""Tests for analyzer and implementer worker protocol injection."""

import tempfile
import unittest
from pathlib import Path

from orchestrator.models import OrchestratorCommand, utc_now_iso
from workers import implementer_worker, planner_worker
from workers.base import WorkerRuntime


def make_runtime(temp_dir, command_type, payload=None, workflow_id="SCRUM-1"):
    """Create a worker runtime for protocol boundary tests."""

    command = OrchestratorCommand(
        command_id=f"{command_type}-1",
        command_type=command_type,
        workflow_id=workflow_id,
        payload=payload or {},
        created_at=utc_now_iso(),
    )
    return WorkerRuntime(
        repo_root=Path(temp_dir),
        command=command,
        result_path=Path(temp_dir) / "result.json",
    )


class FakeAnalyzer:
    """Analyzer protocol implementation used by planner worker tests."""

    def __init__(self):
        self.events = []
        self.export_results = []

    def analyze_export(self, event, export_result):
        self.events.append(event)
        self.export_results.append(export_result)
        return {
            "enabled": True,
            "status": "success",
            "issue_key": event.issue_key,
            "analysis_path": f"{export_result['issue_dir']}/codex_analysis/analysis_and_plan.md",
            "issue_dir": export_result["issue_dir"],
            "manifest_path": export_result["manifest_path"],
            "result_path": f"{export_result['issue_dir']}/codex_analysis/analysis_result.json",
        }


class FakeImplementer:
    """Implementer protocol implementation used by implementer worker tests."""

    def __init__(self):
        self.payloads = []

    def implement_plan(self, payload):
        self.payloads.append(payload)
        issue_dir = payload.get("issue_dir", "exports/SCRUM-1")
        return {
            "enabled": True,
            "status": "success",
            "analysis_path": payload["analysis_path"],
            "issue_dir": issue_dir,
            "commit_log_path": f"{issue_dir}/codex_implementation/commit_log.md",
        }


class WorkerProtocolTestCase(unittest.TestCase):
    """Unit tests for worker-level analyzer and implementer protocols."""

    def test_planner_worker_uses_injected_analyzer(self):
        """The analyzer worker should accept any service matching the protocol."""

        with tempfile.TemporaryDirectory() as temp_dir:
            fake = FakeAnalyzer()
            factory_roots = []
            issue_dir = str(Path(temp_dir) / "exports" / "SCRUM-1")
            manifest_path = str(Path(issue_dir) / "export_manifest.json")
            runtime = make_runtime(
                temp_dir,
                "analyze_issue",
                {"issue_dir": issue_dir, "manifest_path": manifest_path},
            )

            def factory(repo_root):
                factory_roots.append(repo_root)
                return fake

            result = planner_worker.run(runtime, analyzer_factory=factory)

        self.assertTrue(result.success)
        self.assertEqual(result.artifacts["status"], "success")
        self.assertEqual(result.artifacts["analysis_path"], f"{issue_dir}/codex_analysis/analysis_and_plan.md")
        self.assertEqual(factory_roots, [Path(temp_dir)])
        self.assertEqual(fake.events[0].event_type, "orchestrator:analyze_issue")
        self.assertEqual(fake.export_results[0]["manifest_path"], manifest_path)

    def test_planner_worker_skips_when_analyzer_factory_returns_none(self):
        """Disabled analyzer service behavior should remain compatible."""

        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = make_runtime(temp_dir, "analyze_issue")
            result = planner_worker.run(runtime, analyzer_factory=lambda repo_root: None)

        self.assertTrue(result.success)
        self.assertEqual(result.artifacts, {"enabled": False, "status": "skipped", "issue_key": "SCRUM-1"})

    def test_implementer_worker_uses_injected_implementer(self):
        """The implementer worker should accept any service matching the protocol."""

        with tempfile.TemporaryDirectory() as temp_dir:
            fake = FakeImplementer()
            factory_roots = []
            payload = {
                "analysis_path": "exports/SCRUM-1/codex_analysis/analysis_and_plan.md",
                "issue_dir": "exports/SCRUM-1",
            }
            runtime = make_runtime(temp_dir, "execute_plan", payload)

            def factory(repo_root):
                factory_roots.append(repo_root)
                return fake

            result = implementer_worker.run(runtime, implementer_factory=factory)

        self.assertTrue(result.success)
        self.assertEqual(result.artifacts["status"], "success")
        self.assertEqual(
            result.artifacts["commit_log_path"],
            "exports/SCRUM-1/codex_implementation/commit_log.md",
        )
        self.assertEqual(factory_roots, [Path(temp_dir)])
        self.assertEqual(fake.payloads, [payload])

    def test_implementer_worker_skips_when_implementer_factory_returns_none(self):
        """Disabled implementer service behavior should remain compatible."""

        with tempfile.TemporaryDirectory() as temp_dir:
            payload = {"analysis_path": "exports/SCRUM-1/codex_analysis/analysis_and_plan.md"}
            runtime = make_runtime(temp_dir, "execute_plan", payload)
            result = implementer_worker.run(runtime, implementer_factory=lambda repo_root: None)

        self.assertTrue(result.success)
        self.assertEqual(
            result.artifacts,
            {
                "enabled": False,
                "status": "skipped",
                "analysis_path": "exports/SCRUM-1/codex_analysis/analysis_and_plan.md",
            },
        )


if __name__ == "__main__":
    unittest.main()
