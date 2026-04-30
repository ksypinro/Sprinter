"""Tests for GitHub-related orchestrator transitions."""

import tempfile
import unittest
from pathlib import Path

from orchestrator.engine import WorkflowEngine
from orchestrator.models import EventType, OrchestratorEvent, WorkflowStatus
from orchestrator.settings import OrchestratorSettings, SafetySettings, WorkerSettings
from orchestrator.store import OrchestratorStore


class OrchestratorGitHubTestCase(unittest.TestCase):
    def make_engine(self, temp_dir):
        repo_root = Path(temp_dir)
        settings = OrchestratorSettings(
            repo_root=repo_root,
            storage_root=repo_root / ".orchestrator",
            exports_root=repo_root / "exports",
            safety=SafetySettings(
                auto_create_pr_after_execution=True,
                auto_review_after_pr=True,
            ),
            workers={
                "create_pull_request": WorkerSettings(name="create_pull_request"),
                "review_pull_request": WorkerSettings(name="review_pull_request"),
            },
        )
        store = OrchestratorStore(settings.storage_root)
        store.initialize()
        return WorkflowEngine(settings, store), store

    def test_execute_plan_success_queues_pull_request(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            engine, store = self.make_engine(temp_dir)
            store.create_workflow("SCRUM-1")

            event = OrchestratorEvent.new(EventType.WORKER_COMMAND_SUCCEEDED, "SCRUM-1", {
                "command_id": "exec-1",
                "command_type": "execute_plan",
                "artifacts": {
                    "status": "success",
                    "commit_log_path": "/tmp/commit_log.md",
                    "issue_dir": "/tmp/SCRUM-1",
                    "result_path": "/tmp/implementation_result.json",
                },
            })

            self.assertTrue(engine.process_event(event))
            self.assertEqual(store.read_workflow_state("SCRUM-1").status, WorkflowStatus.PR_REQUESTED)
            self.assertEqual(len(store.list_pending_commands("create_pull_request")), 1)

    def test_pull_request_success_queues_review(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            engine, store = self.make_engine(temp_dir)
            store.create_workflow("SCRUM-1")

            event = OrchestratorEvent.new(EventType.WORKER_COMMAND_SUCCEEDED, "SCRUM-1", {
                "command_id": "pr-1",
                "command_type": "create_pull_request",
                "artifacts": {"status": "success", "pr_number": 4, "html_url": "https://github.example/pull/4"},
            })

            self.assertTrue(engine.process_event(event))
            self.assertEqual(store.read_workflow_state("SCRUM-1").status, WorkflowStatus.REVIEW_REQUESTED)
            self.assertEqual(store.list_pending_commands("review_pull_request")[0].payload["pr_number"], 4)

    def test_github_pr_event_queues_review_for_new_workflow(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            engine, store = self.make_engine(temp_dir)

            event = OrchestratorEvent.new(EventType.GITHUB_PR_OPENED, "SCRUM-2", {
                "pr_number": 8,
                "head_branch": "sprinter/SCRUM-2",
                "base_branch": "main",
            })

            self.assertTrue(engine.process_event(event))
            self.assertEqual(store.read_workflow_state("SCRUM-2").status, WorkflowStatus.REVIEW_REQUESTED)
            self.assertEqual(store.list_pending_commands("review_pull_request")[0].payload["pr_number"], 8)

    def test_main_push_event_queues_commit_review(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            engine, store = self.make_engine(temp_dir)

            event = OrchestratorEvent.new(EventType.GITHUB_PUSH_MAIN, "github-push-abc", {
                "commit_sha": "abcdef",
                "base_branch": "main",
            })

            self.assertTrue(engine.process_event(event))
            command = store.list_pending_commands("review_pull_request")[0]
            self.assertEqual(command.payload["commit_sha"], "abcdef")

    def test_review_comment_event_is_observed_without_queueing_review(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            engine, store = self.make_engine(temp_dir)

            event = OrchestratorEvent.new(EventType.GITHUB_PR_REVIEW_COMMENT, "SCRUM-3", {
                "pr_number": 9,
                "comment_id": 42,
            })

            self.assertTrue(engine.process_event(event))
            self.assertEqual(store.read_workflow_state("SCRUM-3").status, WorkflowStatus.NEW)
            self.assertEqual(store.list_pending_commands("review_pull_request"), [])


if __name__ == "__main__":
    unittest.main()
