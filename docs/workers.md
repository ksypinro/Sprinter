# Workers

Workers are the subprocess units that the orchestrator dispatches to perform individual stages of the Sprinter pipeline. Each worker receives a command from the orchestrator, performs its task, and writes a `WorkerResult` JSON file.

## Worker Contract

Every worker follows a strict contract defined in `workers/base.py`:

### WorkerRuntime

```python
@dataclass(frozen=True)
class WorkerRuntime:
    repo_root: Path                    # Repository root directory
    command: OrchestratorCommand       # The dispatched command with payload
    result_path: Path                  # Where to write WorkerResult JSON
```

### Environment Variables

The orchestrator's `ProcessManager` sets these environment variables before spawning a worker subprocess:

| Variable | Description |
|---|---|
| `SPRINTER_WORKER_COMMAND_ID` | Unique ID of the dispatched command |
| `SPRINTER_WORKER_COMMAND_TYPE` | Worker type (e.g. `export_jira_issue`) |
| `SPRINTER_WORKER_WORKFLOW_ID` | Issue key / workflow identifier (e.g. `SCRUM-123`) |
| `SPRINTER_WORKER_RESULT_PATH` | Absolute path where the worker must write its result JSON |
| `PYTHONPATH` | Set to the project root so all imports resolve correctly |

### Command-line Interface

Every worker accepts:

```bash
.venv/bin/python -m workers.<worker_module> --payload '<json>'
```

The `--payload` argument contains the JSON command payload from the orchestrator.

### WorkerResult

Every worker must write a `WorkerResult` JSON file to `SPRINTER_WORKER_RESULT_PATH`:

```json
{
  "command_id": "...",
  "workflow_id": "SCRUM-123",
  "command_type": "export_jira_issue",
  "success": true,
  "returncode": 0,
  "started_at": "2026-05-01T00:00:00Z",
  "finished_at": "2026-05-01T00:01:00Z",
  "artifacts": { ... },
  "error": null
}
```

The `artifacts` dict is worker-specific and carries paths and metadata needed by the next pipeline stage.

### Analyzer and Implementer Protocols

The `analyze_issue` and `execute_plan` workers depend on service-level protocols from `workers.protocols`:

- `Analyzer.analyze_export(event, export_result) -> dict`
- `Implementer.implement_plan(payload) -> dict`

Codex remains the default implementation through `create_codex_analysis_service` and `create_codex_implementer_service`. Tests or future providers can inject alternate factories into the worker `run` functions as long as they preserve the same artifact keys expected by the orchestrator.

### main_worker Helper

The `main_worker(run_func)` helper in `workers/base.py` handles all boilerplate:
1. Parses `--payload` from argv
2. Reads environment variables into an `OrchestratorCommand`
3. Creates a `WorkerRuntime`
4. Calls the provided `run_func(runtime) -> WorkerResult`
5. Writes the result JSON
6. Returns exit code 0 on success, 1 on failure

---

## Worker Types

### 1. Export Jira Issue (`export_jira_worker`)

**Module**: `workers.export_jira_worker`
**Command type**: `export_jira_issue`
**Service**: `JiraStreamableMCP.service.JiraStreamableService`

Exports a Jira issue and all linked Confluence pages, attachments, comments, worklogs, and changelogs into the `exports/<ISSUE_KEY>/` directory.

**Payload**:
```json
{
  "issue_url": "https://example.atlassian.net/browse/SCRUM-123"
}
```

If `issue_url` is omitted, the worker constructs it from the workflow ID and the Jira base URL in `config.yaml`.

**Output artifacts**:
```text
exports/SCRUM-123/
  issue.json
  comments.json
  worklogs.json
  changelog.json
  remote_links.json
  attachments.json
  export_manifest.json
  export.log
  confluence/         # linked Confluence pages
  attachments/        # downloaded attachment files
```

**Standalone usage**:
```bash
SPRINTER_WORKER_COMMAND_ID=manual-export \
SPRINTER_WORKER_COMMAND_TYPE=export_jira_issue \
SPRINTER_WORKER_WORKFLOW_ID=SCRUM-123 \
SPRINTER_WORKER_RESULT_PATH=/tmp/export-result.json \
.venv/bin/python -m workers.export_jira_worker \
  --payload '{"issue_url":"https://example.atlassian.net/browse/SCRUM-123"}'
```

---

### 2. Analyze Issue (`planner_worker`)

**Module**: `workers.planner_worker`
**Command type**: `analyze_issue`
**Default service**: `codex_analysis.service.CodexAnalysisService`

Reads the exported Jira issue artifacts, builds an analysis prompt, runs Codex CLI in **read-only** mode, and writes `analysis_and_plan.md`.

**Payload**:
```json
{
  "issue_dir": "exports/SCRUM-123",
  "manifest_path": "exports/SCRUM-123/export_manifest.json"
}
```

Both fields are optional — the worker derives them from the workflow ID if missing.

**Output artifacts**:
```text
exports/SCRUM-123/codex_analysis/
  codex_prompt.md
  analysis_and_plan.md
  codex_output.log
  analysis_result.json
```

**Standalone usage**:
```bash
SPRINTER_WORKER_COMMAND_ID=manual-analysis \
SPRINTER_WORKER_COMMAND_TYPE=analyze_issue \
SPRINTER_WORKER_WORKFLOW_ID=SCRUM-123 \
SPRINTER_WORKER_RESULT_PATH=/tmp/analysis-result.json \
.venv/bin/python -m workers.planner_worker \
  --payload '{"issue_dir":"exports/SCRUM-123"}'
```

See [Codex Analyzer documentation](codex_analysis.md) for full details.

---

### 3. Execute Plan (`implementer_worker`)

**Module**: `workers.implementer_worker`
**Command type**: `execute_plan`
**Default service**: `codex_implementer.service.CodexImplementerService`

Reads `analysis_and_plan.md`, runs Codex CLI in **workspace-write** mode, applies the required code changes, and writes `commit_log.md`.

**Payload**:
```json
{
  "analysis_path": "exports/SCRUM-123/codex_analysis/analysis_and_plan.md",
  "issue_dir": "exports/SCRUM-123"
}
```

**Output artifacts**:
```text
exports/SCRUM-123/codex_implementation/
  implementer_prompt.md
  codex_output.md
  codex_implementer.log
  implementation_result.json
  commit_log.md
```

**Standalone usage**:
```bash
SPRINTER_WORKER_COMMAND_ID=manual-implement \
SPRINTER_WORKER_COMMAND_TYPE=execute_plan \
SPRINTER_WORKER_WORKFLOW_ID=SCRUM-123 \
SPRINTER_WORKER_RESULT_PATH=/tmp/implementer-result.json \
.venv/bin/python -m workers.implementer_worker \
  --payload '{"analysis_path":"exports/SCRUM-123/codex_analysis/analysis_and_plan.md"}'
```

See [Codex Implementer documentation](codex_implementer.md) for full details.

---

### 4. Create Pull Request (`github_pusher_worker`)

**Module**: `workers.github_pusher_worker`
**Command type**: `create_pull_request`
**Service**: `github_service.pusher.GitPusherService`

Creates a new git branch (`sprinter/<ISSUE_KEY>-<short_id>`), stages all changes, commits with the implementation log, pushes to the remote, and opens a draft GitHub pull request.

**Payload**:
```json
{
  "commit_log_path": "exports/SCRUM-123/codex_implementation/commit_log.md",
  "issue_dir": "exports/SCRUM-123",
  "changed_files": ["src/app.py", "tests/test_app.py"]
}
```

**Required environment variables** (in addition to `SPRINTER_WORKER_*`):
| Variable | Description |
|---|---|
| `SPRINTER_GITHUB_TOKEN` | GitHub personal access token |
| `SPRINTER_GITHUB_OWNER` | Repository owner |
| `SPRINTER_GITHUB_REPO` | Repository name |

For HTTPS remotes, the pusher uses `SPRINTER_GITHUB_TOKEN` via a temporary `GIT_ASKPASS` helper with terminal prompts disabled. Retries after a successful branch push reuse `github_pr/push_state.json` instead of requiring fresh worktree changes.

**Output artifacts**:
```text
exports/SCRUM-123/github_pr/
  push_state.json
  pr_description.md
  github_pr_result.json
```

**Standalone usage**:
```bash
SPRINTER_WORKER_COMMAND_ID=manual-pr \
SPRINTER_WORKER_COMMAND_TYPE=create_pull_request \
SPRINTER_WORKER_WORKFLOW_ID=SCRUM-123 \
SPRINTER_WORKER_RESULT_PATH=/tmp/pr-result.json \
SPRINTER_GITHUB_TOKEN=<token> \
SPRINTER_GITHUB_OWNER=<owner> \
SPRINTER_GITHUB_REPO=<repo> \
.venv/bin/python -m workers.github_pusher_worker \
  --payload '{"commit_log_path":"exports/SCRUM-123/codex_implementation/commit_log.md","issue_dir":"exports/SCRUM-123"}'
```

See [GitHub Workers documentation](github_workers.md) for full details.

---

### 5. Review Pull Request (`github_reviewer_worker`)

**Module**: `workers.github_reviewer_worker`
**Command type**: `review_pull_request`
**Service**: `github_service.reviewer.GitReviewerService`

Fetches the PR diff and file list from GitHub, builds a review prompt, runs Codex CLI in **read-only** mode, and posts the review as a comment on the PR.

**Payload**:
```json
{
  "pr_number": 42,
  "commit_sha": "abc123def",
  "issue_dir": "exports/SCRUM-123"
}
```

If `pr_number` is not provided but `commit_sha` is, the worker looks up associated PRs via the GitHub API. If no PR can be found, the worker records a `skipped` result.

**Output artifacts**:
```text
exports/SCRUM-123/github_review/
  review_prompt.md
  review.md
  codex_review.log
  github_comment_payload.json
  review_result.json
```

**Standalone usage**:
```bash
SPRINTER_WORKER_COMMAND_ID=manual-review \
SPRINTER_WORKER_COMMAND_TYPE=review_pull_request \
SPRINTER_WORKER_WORKFLOW_ID=SCRUM-123 \
SPRINTER_WORKER_RESULT_PATH=/tmp/review-result.json \
SPRINTER_GITHUB_TOKEN=<token> \
SPRINTER_GITHUB_OWNER=<owner> \
SPRINTER_GITHUB_REPO=<repo> \
.venv/bin/python -m workers.github_reviewer_worker \
  --payload '{"pr_number":42,"issue_dir":"exports/SCRUM-123"}'
```

See [GitHub Workers documentation](github_workers.md) for full details.

---

## Compatibility Wrappers

Two thin compatibility wrappers exist for legacy references:

| Wrapper | Delegates to |
|---|---|
| `workers.github_pr_worker` | `workers.github_pusher_worker` |
| `workers.reviewer_worker` | `workers.github_reviewer_worker` |
| `workers.executor_worker` | `workers.implementer_worker` |

---

## Orchestrator Worker Configuration

Workers are configured in `orchestrator/config.yaml` under the `workers:` section:

```yaml
workers:
  export_jira_issue:
    enabled: true
    instances: 3            # Max concurrent subprocesses
    timeout_seconds: 300    # Kill worker after this duration
    max_attempts: 3         # Retries before workflow becomes blocked
    command: .venv/bin/python
    args:
      - -m
      - workers.export_jira_worker

  analyze_issue:
    enabled: true
    instances: 2
    timeout_seconds: 900
    max_attempts: 3
    command: .venv/bin/python
    args:
      - -m
      - workers.planner_worker

  execute_plan:
    enabled: true
    instances: 1
    timeout_seconds: 1800
    max_attempts: 3
    command: .venv/bin/python
    args:
      - -m
      - workers.implementer_worker

  create_pull_request:
    enabled: true
    instances: 1
    timeout_seconds: 300
    max_attempts: 3
    command: .venv/bin/python
    args:
      - -m
      - workers.github_pusher_worker

  review_pull_request:
    enabled: true
    instances: 2
    timeout_seconds: 900
    max_attempts: 3
    command: .venv/bin/python
    args:
      - -m
      - workers.github_reviewer_worker
```

## Tests

```bash
# All worker and service tests
.venv/bin/python -m unittest tests.test_codex_analysis tests.test_codex_implementer tests.test_github_service -v

# Orchestrator integration tests that exercise workers
.venv/bin/python -m unittest tests.test_orchestrator_implementation tests.test_orchestrator_github -v

# Full suite
.venv/bin/python -m unittest discover -s tests -v
```
