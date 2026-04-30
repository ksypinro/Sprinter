# Codex Implementer

The Codex Implementer is the write-enabled stage that runs after Codex Analyzer creates `analysis_and_plan.md`.

It reads the analyzer plan, maps the plan against the repository, applies the necessary code changes with Codex CLI, and writes implementation artifacts back to the issue export directory.

## Pipeline

The orchestrated flow is:

1. `export_jira_issue` exports the Jira issue.
2. `analyze_issue` writes `codex_analysis/analysis_and_plan.md`.
3. The orchestrator receives the successful analyzer worker result.
4. If `safety.auto_execute_after_plan` is enabled, the orchestrator queues `execute_plan`.
5. `workers.implementer_worker` runs the Codex Implementer.
6. The implementer applies code changes and writes `codex_implementation/commit_log.md`.
7. The worker reports success to the orchestrator.
8. The workflow moves to `execution_completed`.

## Output Artifacts

For an issue export at:

```text
exports/SCRUM-123/
```

the implementer writes:

```text
exports/SCRUM-123/codex_implementation/
  implementer_prompt.md
  codex_output.md
  codex_implementer.log
  implementation_result.json
  commit_log.md
```

`commit_log.md` must include:

- `# Implementation Commit Log`
- `## Summary`
- `## Files Changed`
- `## Verification`
- `## Observations`

The implementer does not commit, stage, push, branch, or open pull requests. It only edits files and records what it did.

## Use With Orchestrator

The default orchestrator config now enables the implementer stage:

```yaml
safety:
  auto_execute_after_plan: true

workers:
  execute_plan:
    enabled: true
    command: .venv/bin/python
    args:
      - -m
      - workers.implementer_worker
```

Start the orchestrator:

```bash
.venv/bin/python -m orchestrator start
```

Submit a Jira-created workflow manually:

```bash
.venv/bin/python -m orchestrator submit-jira-created SCRUM-123 --url "https://example.atlassian.net/browse/SCRUM-123"
```

Watch status:

```bash
.venv/bin/python -m orchestrator status
.venv/bin/python -m orchestrator workflow SCRUM-123 --history
```

To keep implementation manual, set:

```yaml
safety:
  auto_execute_after_plan: false
```

Then queue or run `execute_plan` directly only after reviewing the analyzer output.

## Use Without Orchestrator

Run the worker directly against an existing analysis file:

```bash
SPRINTER_WORKER_COMMAND_ID=manual-implement \
SPRINTER_WORKER_COMMAND_TYPE=execute_plan \
SPRINTER_WORKER_WORKFLOW_ID=SCRUM-123 \
SPRINTER_WORKER_RESULT_PATH=/tmp/sprinter-implementer-result.json \
.venv/bin/python -m workers.implementer_worker \
  --payload '{"analysis_path":"exports/SCRUM-123/codex_analysis/analysis_and_plan.md"}'
```

Or call the service from Python:

```python
from pathlib import Path
from codex_implementer.service import create_codex_implementer_service

service = create_codex_implementer_service(repo_root=Path.cwd())
result = service.implement_plan({
    "analysis_path": "exports/SCRUM-123/codex_analysis/analysis_and_plan.md",
})
print(result["commit_log_path"])
```

## Configuration

Default settings live in:

```text
codex_implementer/config.yaml
```

Useful environment overrides:

```text
SPRINTER_CODEX_IMPLEMENTER_ENABLED=false
SPRINTER_CODEX_IMPLEMENTER_COMMAND=/absolute/path/to/codex
SPRINTER_CODEX_IMPLEMENTER_SANDBOX=workspace-write
SPRINTER_CODEX_IMPLEMENTER_TIMEOUT_SECONDS=1800
SPRINTER_CODEX_IMPLEMENTER_MODEL=<model>
SPRINTER_CODEX_IMPLEMENTER_PROFILE=<profile>
SPRINTER_CODEX_IMPLEMENTER_REPO_ROOT=/path/to/repo
```

The implementer rejects `read-only` sandbox mode because it must edit code and write `commit_log.md`.

## Tests

Run implementer-only tests:

```bash
.venv/bin/python -m unittest tests.test_codex_implementer -v
.venv/bin/python -m unittest tests.test_orchestrator_implementation -v
```

Run the full suite:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

## Smoke Test

For a live Codex CLI smoke test, create a temporary repo with an `analysis_and_plan.md`, then run:

```bash
.venv/bin/python - <<'PY'
from pathlib import Path
import json
import shutil
import subprocess
from codex_implementer.service import create_codex_implementer_service

root = Path("/tmp/sprinter-implementer-smoke")
shutil.rmtree(root, ignore_errors=True)
root.mkdir(parents=True)
subprocess.run(["git", "init"], cwd=root, check=True)
issue_dir = root / "exports" / "SCRUM-SMOKE"
analysis_dir = issue_dir / "codex_analysis"
analysis_dir.mkdir(parents=True)
(root / "app.txt").write_text("before\n", encoding="utf-8")
(analysis_dir / "analysis_and_plan.md").write_text(
    "# Plan\n\nChange app.txt from before to after. Write commit_log.md.\n",
    encoding="utf-8",
)

service = create_codex_implementer_service(repo_root=root)
result = service.implement_plan({
    "analysis_path": str(analysis_dir / "analysis_and_plan.md"),
})
print(json.dumps(result, indent=2))
PY
```

Expected result:

- `app.txt` changes according to the plan.
- `exports/SCRUM-SMOKE/codex_implementation/commit_log.md` exists.
- `implementation_result.json` reports `status: success`.

When running from a sandboxed desktop session, Codex CLI may need permission to access its session files.
