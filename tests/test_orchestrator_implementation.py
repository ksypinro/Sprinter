"""Tests for orchestrator analysis-to-implementation handoff."""

import tempfile
import unittest
from pathlib import Path

from orchestrator.engine import WorkflowEngine
from orchestrator.models import EventType, OrchestratorEvent, WorkflowStatus
from orchestrator.settings import OrchestratorSettings, SafetySettings, WorkerSettings
from orchestrator.store import OrchestratorStore


class OrchestratorImplementationTestCase(unittest.TestCase):
    """Unit tests for automatic implementation orchestration."""

    def make_engine(self, temp_dir, auto_execute=True):
        repo_root = Path(temp_dir)
        settings = OrchestratorSettings(
            repo_root=repo_root,
            storage_root=repo_root / ".orchestrator",
            exports_root=repo_root / "exports",
            safety=SafetySettings(auto_execute_after_plan=auto_execute),
            workers={
                "execute_plan": WorkerSettings(name="execute_plan"),
            },
        )
        store = OrchestratorStore(settings.storage_root)
        store.initialize()
        return WorkflowEngine(settings, store), store

    def test_analysis_success_enqueues_execute_plan(self):
        """Successful analysis artifacts should trigger implementation."""

        with tempfile.TemporaryDirectory() as temp_dir:
            engine, store = self.make_engine(temp_dir)
            store.create_workflow("SCRUM-1")

            event = OrchestratorEvent.new(
                EventType.WORKER_COMMAND_SUCCEEDED,
                "SCRUM-1",
                {
                    "command_id": "analysis-1",
                    "command_type": "analyze_issue",
                    "artifacts": {
                        "status": "success",
                        "analysis_path": "/tmp/analysis_and_plan.md",
                        "issue_dir": "/tmp/SCRUM-1",
                        "manifest_path": "/tmp/SCRUM-1/export_manifest.json",
                        "result_path": "/tmp/SCRUM-1/codex_analysis/analysis_result.json",
                    },
                },
            )

            self.assertTrue(engine.process_event(event))
            state = store.read_workflow_state("SCRUM-1")
            commands = store.list_pending_commands("execute_plan")

            self.assertEqual(state.status, WorkflowStatus.EXECUTION_REQUESTED)
            self.assertEqual(len(commands), 1)
            self.assertEqual(commands[0].payload["analysis_path"], "/tmp/analysis_and_plan.md")

    def test_analysis_success_can_leave_execution_manual(self):
        """The safety flag should allow analysis-only operation."""

        with tempfile.TemporaryDirectory() as temp_dir:
            engine, store = self.make_engine(temp_dir, auto_execute=False)
            store.create_workflow("SCRUM-1")

            event = OrchestratorEvent.new(
                EventType.WORKER_COMMAND_SUCCEEDED,
                "SCRUM-1",
                {
                    "command_id": "analysis-1",
                    "command_type": "analyze_issue",
                    "artifacts": {"status": "success", "analysis_path": "/tmp/analysis.md"},
                },
            )

            self.assertTrue(engine.process_event(event))
            state = store.read_workflow_state("SCRUM-1")

            self.assertEqual(state.status, WorkflowStatus.ANALYSIS_COMPLETED)
            self.assertEqual(store.list_pending_commands("execute_plan"), [])

    def test_execute_plan_success_completes_execution(self):
        """Successful implementer results should complete execution."""

        with tempfile.TemporaryDirectory() as temp_dir:
            engine, store = self.make_engine(temp_dir)
            store.create_workflow("SCRUM-1")

            event = OrchestratorEvent.new(
                EventType.WORKER_COMMAND_SUCCEEDED,
                "SCRUM-1",
                {
                    "command_id": "execute-1",
                    "command_type": "execute_plan",
                    "artifacts": {"status": "success", "commit_log_path": "/tmp/commit_log.md"},
                },
            )

            self.assertTrue(engine.process_event(event))
            state = store.read_workflow_state("SCRUM-1")

            self.assertEqual(state.status, WorkflowStatus.EXECUTION_COMPLETED)


if __name__ == "__main__":
    unittest.main()
