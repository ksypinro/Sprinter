"""Tests for GitHub worker services."""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from github_service.client import GitHubClient
from github_service.git import GitAdapter, GitCommandResult
from github_service.pusher import GitPusherService
from github_service.review_runner import ReviewRunnerResult
from github_service.reviewer import GitReviewerService
from github_service.settings import GitHubSettings, GitHubSettingsError


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text or json.dumps(self._payload)

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.headers = {}
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        return self.response


class FakeGit:
    def __init__(self, has_changes=True, current_branch="sprinter/SCRUM-1-command"):
        self.calls = []
        self._has_changes = has_changes
        self._current_branch = current_branch

    def has_changes(self):
        return self._has_changes

    def changed_files(self):
        return ["app.py", "tests/test_app.py"]

    def current_branch(self):
        self.calls.append(("current_branch",))
        return self._current_branch

    def create_branch(self, branch):
        self.calls.append(("create_branch", branch))

    def add_all(self):
        self.calls.append(("add_all",))

    def commit(self, message, body):
        self.calls.append(("commit", message, body))

    def push(self, remote, branch, token=None):
        self.calls.append(("push", remote, branch, bool(token)))

    def head_sha(self):
        return "abc123"


class FakeGitHubClient:
    def __init__(self):
        self.created_pr = None
        self.find_calls = []

    def find_open_pull_request(self, head, base):
        self.find_calls.append({"head": head, "base": base})
        return None

    def create_pull_request(self, title, head, base, body, draft):
        self.created_pr = {"title": title, "head": head, "base": base, "body": body, "draft": draft}
        return {"number": 12, "html_url": "https://github.example/pull/12", "diff_url": "https://github.example/pull/12.diff", "draft": draft}


class FailingCreatePullRequestClient(FakeGitHubClient):
    def create_pull_request(self, title, head, base, body, draft):
        raise RuntimeError("temporary API failure")


class FakeReviewRunner:
    def run(self, prompt, repo_root, review_path, log_path):
        review_path.write_text("No blocking issues found.\n", encoding="utf-8")
        log_path.write_text("fake review log\n", encoding="utf-8")
        return ReviewRunnerResult(0, review_path, log_path)


class FakeReviewClient:
    def __init__(self):
        self.comment = None

    def get_pull_request(self, pr_number):
        return {
            "number": pr_number,
            "title": "Implement SCRUM-1",
            "html_url": "https://github.example/pull/12",
            "base": {"ref": "main"},
            "head": {"ref": "sprinter/SCRUM-1"},
        }

    def list_pull_request_files(self, pr_number):
        return [{"filename": "app.py", "status": "modified", "additions": 3, "deletions": 1}]

    def get_pull_request_diff(self, pr_number):
        return "diff --git a/app.py b/app.py\n+hello\n"

    def create_issue_comment(self, issue_number, body):
        self.comment = {"issue_number": issue_number, "body": body}
        return {"html_url": "https://github.example/pull/12#comment"}

    def pull_requests_for_commit(self, sha):
        return [{"number": 12}]


class GitHubSettingsTestCase(unittest.TestCase):
    def test_from_env_reads_defaults_and_overrides(self):
        settings = GitHubSettings.from_env({
            "SPRINTER_GITHUB_TOKEN": "token",
            "SPRINTER_GITHUB_OWNER": "owner",
            "SPRINTER_GITHUB_REPO": "repo",
            "SPRINTER_GITHUB_DRAFT_PR": "false",
            "SPRINTER_GITHUB_REQUEST_TIMEOUT_SECONDS": "12.5",
        })

        self.assertEqual(settings.base_branch, "main")
        self.assertFalse(settings.draft_pr)
        self.assertEqual(settings.request_timeout_seconds, 12.5)
        settings.require_api()

    def test_require_api_reports_missing_values(self):
        with self.assertRaises(GitHubSettingsError):
            GitHubSettings.from_env({}).require_api()


class GitAdapterTestCase(unittest.TestCase):
    def test_git_adapter_wraps_runner_commands(self):
        calls = []

        def runner(args, cwd, env=None):
            calls.append((args, cwd))
            return GitCommandResult(args, 0, "main\n", "")

        adapter = GitAdapter(Path("/repo"), runner=runner)

        self.assertEqual(adapter.current_branch(), "main")
        self.assertEqual(calls[0][0], ["git", "rev-parse", "--abbrev-ref", "HEAD"])

    def test_push_uses_token_backed_askpass_without_putting_token_in_args(self):
        calls = []

        def runner(args, cwd, env=None):
            calls.append((args, env))
            return GitCommandResult(args, 0, "", "")

        adapter = GitAdapter(Path("/repo"), runner=runner)

        adapter.push("origin", "sprinter/SCRUM-1", token="secret-token")

        args, env = calls[0]
        self.assertEqual(args, ["git", "push", "-u", "origin", "sprinter/SCRUM-1"])
        self.assertNotIn("secret-token", args)
        self.assertEqual(env["GIT_TERMINAL_PROMPT"], "0")
        self.assertEqual(env["SPRINTER_GIT_TOKEN"], "secret-token")


class GitHubClientTestCase(unittest.TestCase):
    def test_create_pull_request_posts_expected_payload(self):
        session = FakeSession(FakeResponse(payload={"number": 1}))
        client = GitHubClient(
            GitHubSettings(token="token", owner="owner", repo="repo"),
            session=session,
        )

        client.create_pull_request("Title", "head", "main", "body", True)

        call = session.calls[0]
        self.assertEqual(call["method"], "POST")
        self.assertTrue(call["url"].endswith("/repos/owner/repo/pulls"))
        self.assertEqual(call["json"]["draft"], True)
        self.assertEqual(call["timeout"], 20.0)

    def test_find_open_pull_request_uses_head_base_and_timeout(self):
        session = FakeSession(FakeResponse(payload=[{"number": 1}]))
        client = GitHubClient(
            GitHubSettings(token="token", owner="owner", repo="repo", request_timeout_seconds=7),
            session=session,
        )

        pr = client.find_open_pull_request("sprinter/SCRUM-1", "main")

        self.assertEqual(pr["number"], 1)
        call = session.calls[0]
        self.assertEqual(call["method"], "GET")
        self.assertEqual(call["params"]["head"], "owner:sprinter/SCRUM-1")
        self.assertEqual(call["params"]["base"], "main")
        self.assertEqual(call["params"]["state"], "open")
        self.assertEqual(call["timeout"], 7)


class GitPusherServiceTestCase(unittest.TestCase):
    def test_create_pull_request_writes_artifacts_and_calls_git(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            issue_dir = repo_root / "exports" / "SCRUM-1"
            impl_dir = issue_dir / "codex_implementation"
            impl_dir.mkdir(parents=True)
            commit_log = impl_dir / "commit_log.md"
            commit_log.write_text("# Implementation Commit Log\n\n## Summary\nDone.\n", encoding="utf-8")
            fake_git = FakeGit()
            fake_client = FakeGitHubClient()
            service = GitPusherService(
                settings=GitHubSettings(token="token", owner="owner", repo="repo"),
                repo_root=repo_root,
                git=fake_git,
                client=fake_client,
            )

            result = service.create_pull_request(
                "SCRUM-1",
                "command-12345678",
                {"commit_log_path": "exports/SCRUM-1/codex_implementation/commit_log.md"},
            )

            self.assertEqual(result["status"], "success")
            self.assertEqual(result["pr_number"], 12)
            self.assertTrue((issue_dir / "github_pr" / "github_pr_result.json").exists())
            self.assertTrue((issue_dir / "github_pr" / "push_state.json").exists())
            self.assertEqual(fake_git.calls[0][0], "create_branch")
            self.assertEqual(fake_git.calls[3], ("push", "origin", "sprinter/SCRUM-1-command-", True))
            self.assertEqual(fake_client.created_pr["base"], "main")

    def test_retry_after_push_reuses_pushed_branch_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            issue_dir = repo_root / "exports" / "SCRUM-1"
            impl_dir = issue_dir / "codex_implementation"
            impl_dir.mkdir(parents=True)
            commit_log = impl_dir / "commit_log.md"
            commit_log.write_text("# Implementation Commit Log\n\n## Summary\nDone.\n", encoding="utf-8")

            first_service = GitPusherService(
                settings=GitHubSettings(token="token", owner="owner", repo="repo"),
                repo_root=repo_root,
                git=FakeGit(),
                client=FailingCreatePullRequestClient(),
            )
            with self.assertRaises(RuntimeError):
                first_service.create_pull_request(
                    "SCRUM-1",
                    "command-12345678",
                    {"commit_log_path": "exports/SCRUM-1/codex_implementation/commit_log.md"},
                )

            retry_git = FakeGit(has_changes=False)
            retry_client = FakeGitHubClient()
            retry_service = GitPusherService(
                settings=GitHubSettings(token="token", owner="owner", repo="repo"),
                repo_root=repo_root,
                git=retry_git,
                client=retry_client,
            )

            result = retry_service.create_pull_request(
                "SCRUM-1",
                "retry-99999999",
                {"commit_log_path": "exports/SCRUM-1/codex_implementation/commit_log.md"},
            )

            self.assertEqual(result["status"], "success")
            self.assertEqual(result["branch"], "sprinter/SCRUM-1-command-")
            self.assertNotIn(("create_branch", "sprinter/SCRUM-1-retry-99"), retry_git.calls)
            self.assertFalse([call for call in retry_git.calls if call[0] == "push"])
            self.assertEqual(retry_client.created_pr["head"], "sprinter/SCRUM-1-command-")

    @unittest.skipIf(shutil.which("git") is None, "git executable is required for smoke test")
    def test_create_pull_request_smoke_with_temp_git_repo(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            remote = temp_root / "remote.git"
            repo_root = temp_root / "repo"
            repo_root.mkdir()
            subprocess.run(["git", "init", "--bare", str(remote)], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            subprocess.run(["git", "init"], cwd=repo_root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            subprocess.run(["git", "checkout", "-b", "main"], cwd=repo_root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            subprocess.run(["git", "config", "user.name", "Sprinter Test"], cwd=repo_root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            subprocess.run(["git", "config", "user.email", "sprinter@example.test"], cwd=repo_root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=repo_root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            (repo_root / "app.py").write_text("print('before')\n", encoding="utf-8")
            subprocess.run(["git", "add", "app.py"], cwd=repo_root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=repo_root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            subprocess.run(["git", "push", "-u", "origin", "main"], cwd=repo_root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

            issue_dir = repo_root / "exports" / "SCRUM-1"
            impl_dir = issue_dir / "codex_implementation"
            impl_dir.mkdir(parents=True)
            commit_log = impl_dir / "commit_log.md"
            commit_log.write_text("# Implementation Commit Log\n\n## Summary\nChanged app.py.\n", encoding="utf-8")
            (repo_root / "app.py").write_text("print('after')\n", encoding="utf-8")
            fake_client = FakeGitHubClient()
            service = GitPusherService(
                settings=GitHubSettings(token="token", owner="owner", repo="repo"),
                repo_root=repo_root,
                git=GitAdapter(repo_root),
                client=fake_client,
            )

            result = service.create_pull_request("SCRUM-1", "cmd12345678", {"commit_log_path": str(commit_log)})

            self.assertEqual(result["status"], "success")
            self.assertEqual(result["branch"], "sprinter/SCRUM-1-cmd12345")
            self.assertIn("app.py", result["changed_files"])
            self.assertIn("exports/SCRUM-1/codex_implementation/commit_log.md", result["changed_files"])
            self.assertTrue((issue_dir / "github_pr" / "github_pr_result.json").exists())
            remote_heads = subprocess.run(
                ["git", "ls-remote", "--heads", "origin", result["branch"]],
                cwd=repo_root,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.assertIn(f"refs/heads/{result['branch']}", remote_heads.stdout)


class GitReviewerServiceTestCase(unittest.TestCase):
    def test_review_writes_artifacts_and_posts_comment(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            service = GitReviewerService(
                settings=GitHubSettings(token="token", owner="owner", repo="repo"),
                repo_root=repo_root,
                client=FakeReviewClient(),
                runner=FakeReviewRunner(),
            )

            result = service.review("SCRUM-1", {"pr_number": 12})

            self.assertEqual(result["status"], "success")
            self.assertTrue(Path(result["review_path"]).exists())
            self.assertTrue(Path(result["comment_payload_path"]).exists())

    def test_review_skips_commit_without_associated_pr(self):
        class NoPRClient(FakeReviewClient):
            def pull_requests_for_commit(self, sha):
                return []

        with tempfile.TemporaryDirectory() as temp_dir:
            service = GitReviewerService(
                settings=GitHubSettings(token="token", owner="owner", repo="repo"),
                repo_root=Path(temp_dir),
                client=NoPRClient(),
                runner=FakeReviewRunner(),
            )

            result = service.review("github-push-abc", {"commit_sha": "abc"})

            self.assertEqual(result["status"], "skipped")


if __name__ == "__main__":
    unittest.main()
