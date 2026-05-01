# Sprinter Agent Guide

This document is designed for AI agents (Codex, Cline, Antigravity, etc.) to understand and use the Sprinter CLI tools effectively.

## Purpose

The `tools` package provides individual, stateless CLI access to every stage of the Sprinter development pipeline. Unlike the Orchestrator (which is an automated event loop), these tools allow an agent to manually execute specific actions, inspect state, and integrate Sprinter capabilities into their own workflows.

## Design Philosophy

- **JSON Output**: All tools output valid JSON to `stdout` on success.
- **Error Handling**: Errors are written to `stderr` as JSON with an `"error"` field.
- **Exit Codes**: `0` for success, `1` for failure.
- **Statelessness**: Most tools call underlying services directly, bypassing the orchestrator's state machine.

---

## Tool Catalog

All tools are invoked via `python -m tools <tool_name> [args...]`.

### 1. Issue Export (`export_issue`)
Exports a Jira issue and linked Confluence pages to the local `exports/` directory.

- **Usage**: `python -m tools export_issue --url <JIRA_URL>` or `--key <ISSUE_KEY>`
- **Example Output**:
  ```json
  {
    "issue_key": "SCRUM-123",
    "issue_dir": "/path/to/Sprinter/exports/SCRUM-123",
    "manifest_path": "/path/to/Sprinter/exports/SCRUM-123/export_manifest.json",
    "remote_link_count": 5
  }
  ```

### 2. Issue Creation (`create_issue`)
Creates a new Jira issue.

- **Usage**: `python -m tools create_issue --payload '<JSON>'` or `--file <PATH>`
- **Example Output**:
  ```json
  {
    "issue_key": "SCRUM-124",
    "response_path": "/path/to/Sprinter/exports/created/SCRUM-124/ticket_response.json"
  }
  ```

### 3. Issue Analysis (`analyze_issue`)
Runs Codex CLI in read-only mode to analyze the exported issue and generate a plan.

- **Usage**: `python -m tools analyze_issue --key <ISSUE_KEY>`
- **Prerequisite**: Must run `export_issue` first.
- **Output**: Path to `analysis_and_plan.md` and related artifacts.

### 4. Implementation (`implement_plan`)
Runs Codex CLI with workspace-write permissions to apply code changes based on a plan.

- **Usage**: `python -m tools implement_plan --key <ISSUE_KEY>`
- **Prerequisite**: Must run `analyze_issue` first.
- **Output**: Path to `commit_log.md` and changed file list.

### 5. PR Creation (`create_pr`)
Automates git branching, committing (using `commit_log.md`), and opening a GitHub PR.

- **Usage**: `python -m tools create_pr --key <ISSUE_KEY>`
- **Prerequisite**: Must run `implement_plan` first.
- **Output**: PR URL, branch name, and status.

### 6. PR Review (`review_pr`)
Runs Codex CLI to review a PR and posts the review as a comment.

- **Usage**: `python -m tools review_pr --key <ISSUE_KEY> --pr-number <NUM>`
- **Output**: Review content and GitHub comment API response.

### 7. Workflow Status (`workflow_status`)
Queries the orchestrator's local store for workflow states.

- **Usage**: `python -m tools workflow_status [--key <ISSUE_KEY>] [--history]`

### 8. Workflow Control (`workflow_control`)
Manually starts, pauses, resumes, or retries workflows in the orchestrator.

- **Usage**: `python -m tools workflow_control {start|pause|resume|retry} --key <ISSUE_KEY>`

---

## Agent Workflow Patterns

### Pattern A: Full Automation Support
If you want to let Sprinter handle everything:
1. `python -m tools workflow_control start --key SCRUM-123`
2. `python -m tools workflow_status --key SCRUM-123` (poll periodically until success)

### Pattern B: Manual Pipeline Control
If you want to intervene at each step:
1. **Export**: `python -m tools export_issue --key SCRUM-123`
2. **Read**: Read `exports/SCRUM-123/issue.json` to understand the task.
3. **Analyze**: `python -m tools analyze_issue --key SCRUM-123`
4. **Edit**: Modify `exports/SCRUM-123/codex_analysis/analysis_and_plan.md` if you want to guide the implementation.
5. **Implement**: `python -m tools implement_plan --key SCRUM-123`
6. **PR**: `python -m tools create_pr --key SCRUM-123`

---

## Environment Prerequisites

Ensure these are set in your environment:
- `ATLASSIAN_API_TOKEN`
- `ATLASSIAN_EMAIL`
- `SPRINTER_GITHUB_TOKEN`
- `SPRINTER_GITHUB_OWNER`
- `SPRINTER_GITHUB_REPO`
- `NGROK_AUTHTOKEN` (if using setup tools)
