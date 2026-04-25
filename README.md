# Sprinter

Sprinter is a local Python utility for working with Atlassian data. It can export a Jira issue, the issue's Jira-side activity, and any Confluence pages linked through Jira remote links into a local artifact tree. It can also create a Jira issue from a JSON payload and record the exact request and response for traceability.

The project has two entry surfaces:

- `main.py`: command-line interface for export and create workflows.
- `MCPJira/`: optional stdio MCP server that exposes the same workflows to MCP-capable clients such as Codex or Cline.
- `JiraStreamableMCP/`: optional Streamable HTTP MCP server with a separate package and HTTP-first entrypoint.
- `JiraSSEMCP/`: optional SSE MCP server for clients that still require the older SSE transport.
- `webhooks/`: optional webhook receiver, filesystem queue, worker, ngrok setup automation, and webhook runtime settings.
- `webhookAPI/`: optional Jira webhook management CLI/client for creating, listing, deleting, and refreshing webhook registrations.

## Capabilities

- Export one Jira issue from a configured Jira site.
- Save issue metadata, comments, worklogs, changelog, remote links, and attachment metadata.
- Optionally download Jira attachment binaries.
- Resolve Confluence pages from same-host Jira remote links.
- Export Confluence storage-format page bodies, ancestors, descendants, comments, and attachments.
- Create a Jira issue from a local JSON payload shaped for Jira's create-issue API.
- Persist logs and manifests for both export and create runs.
- Expose compact MCP tools and read-only MCP resources through stdio, Streamable HTTP, or SSE MCP packages.

## Project layout

```text
.
  main.py                    CLI commands and workflow orchestration
  fetcher.py                 Jira and Confluence HTTP clients
  utils.py                   URL, path, filename, and JSON/text helpers
  config.yaml                Runtime configuration
  ticket.json.example        Minimal create-issue payload example
  requirements.txt           CLI/runtime dependencies
  architecture.html          Human-readable architecture reference
  tests/                     Unit tests for the CLI/core helpers
  MCPJira/
    server.py                FastMCP tool and resource registration
    service.py               MCP facade over the Sprinter workflows
    requirements.txt         MCP dependency overlay
    README.md                MCP-specific setup and usage notes
    config-examples/         Example Codex and Cline MCP configs
    tests/                   Unit tests for the MCP service facade
  JiraStreamableMCP/
    app.py                   Streamable HTTP FastMCP app factory
    server.py                Streamable HTTP server entrypoint
    service.py               Independent HTTP MCP facade
    settings.py              Environment-backed HTTP server settings
    requirements.txt         HTTP MCP dependency overlay
    README.md                Streamable HTTP MCP setup and usage notes
    tests/                   Unit tests for HTTP MCP settings and service
  JiraSSEMCP/
    app.py                   SSE FastMCP app factory
    server.py                SSE server entrypoint
    service.py               Independent SSE MCP facade
    settings.py              Environment-backed SSE server settings
    requirements.txt         SSE MCP dependency overlay
    README.md                SSE MCP setup and usage notes
    tests/                   Unit tests for SSE MCP settings and service
  webhooks/
    app.py                   stdlib HTTP webhook receiver
    server.py                webhook server entrypoint
    setup.py                 webhook server + ngrok + Jira registration orchestration
    store.py                 filesystem-backed event/job store
    worker.py                background export worker
    config.yaml              webhook receiver settings and signing secret
    ngrok_config.yaml        ngrok and Jira webhook setup settings
  webhookAPI/
    client.py                Jira admin/dynamic webhook API client
    cli.py                   programmatic webhook management CLI
    factory.py               config-backed client factory
```

Generated artifacts are written under `storage.export_path`, usually `exports/`.
The `exports/` directory is generated output and is ignored by version control.

```text
exports/
  SCRUM-1/
    issue.json
    comments.json
    worklogs.json
    changelog.json
    remote_links.json
    attachments.json
    attachments/
    wiki/
      linked_pages.json
      unresolved_links.json
      page_123/
        page.json
        ancestors.json
        descendants.json
        footer_comments.json
        inline_comments.json
        attachments.json
        <page title>.storage.html
        attachments/
    export.log
    export_manifest.json
  created/
    SCRUM-100/
      ticket_request.json
      ticket_response.json
      ticket_source.json
      export.log
      export_manifest.json
    pending/
      export.log
      export_manifest.json
```

`wiki/` is only created when the exported Jira issue has resolvable or unresolved Confluence remote links. `created/pending/` is used before Jira returns a final issue key or when creation fails before a keyed directory can be created.

## Requirements

- Python 3.10 or newer.
- Network access to your Jira and Confluence Cloud sites.
- Atlassian credentials that can read the target Jira issue and linked Confluence pages.
- Jira create permission if you use the create workflow.
- Optional: `ngrok` CLI installed and authenticated if you use `webhooks.setup` to expose the local webhook server.

Install the CLI/runtime dependencies:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Install the optional MCP server dependencies:

```bash
.venv/bin/pip install -r MCPJira/requirements.txt
```

Install the optional Streamable HTTP MCP server dependencies:

```bash
.venv/bin/pip install -r JiraStreamableMCP/requirements.txt
```

Install the optional SSE MCP server dependencies:

```bash
.venv/bin/pip install -r JiraSSEMCP/requirements.txt
```

## Configuration

Sprinter reads `config.yaml` by default. Both `export` and `create` require the top-level `jira`, `confluence`, and `storage` sections because the same config loader is shared across workflows.

Prefer environment variables for secrets:

```yaml
jira:
  base_url: "https://your-domain.atlassian.net"
  auth:
    type: "basic"
    email_env: "ATLASSIAN_EMAIL"
    token_env: "ATLASSIAN_API_TOKEN"

confluence:
  base_url: "https://your-domain.atlassian.net/wiki"
  auth:
    type: "basic"
    email_env: "ATLASSIAN_EMAIL"
    token_env: "ATLASSIAN_API_TOKEN"

requests:
  timeout_seconds: 30
  retries: 3
  page_size: 100
  log_level: "INFO"

storage:
  export_path: "./exports"
  download_attachments: true
  include_confluence_descendants: true
  confluence_descendant_depth: 5
```

Supported auth fields:

- `auth.type`: `basic` or `bearer`.
- `auth.token`: inline token value, useful for local testing only.
- `auth.token_env`: environment variable that contains the token.
- `auth.email`: inline email value for `basic` auth.
- `auth.email_env`: environment variable that contains the email for `basic` auth.
- `pat`: older Jira/Confluence token fallback, treated as bearer auth when no `auth.token` is supplied.

For Atlassian Cloud API tokens, `basic` auth with email plus API token is usually the expected setup:

```bash
export ATLASSIAN_EMAIL="you@example.com"
export ATLASSIAN_API_TOKEN="your-api-token"
```

## CLI usage

Export a Jira issue and any linked Confluence content:

```bash
.venv/bin/python main.py export "https://your-domain.atlassian.net/browse/SCRUM-1"
```

Create a Jira issue from a local payload:

```bash
.venv/bin/python main.py create ticket.json
```

Use a non-default config file:

```bash
.venv/bin/python main.py --config custom-config.yaml export "https://your-domain.atlassian.net/browse/SCRUM-1"
.venv/bin/python main.py --config custom-config.yaml create ticket.json
```

## Export workflow

1. The CLI parses the Jira issue key from the provided URL and verifies that the host matches `jira.base_url`.
2. `main.py` builds configured Jira and Confluence fetchers.
3. The Jira fetcher saves issue JSON, comments, worklogs, changelog, remote links, and attachment metadata.
4. If attachment downloads are enabled, Jira attachment binaries are saved under `attachments/`.
5. Remote links whose host matches `confluence.base_url` are inspected for page IDs.
6. Legacy `/display/SPACE/Title` links are resolved through Confluence search when possible.
7. Each linked page and configured descendants are saved under `wiki/page_<id>/`.
8. The run writes `export.log` and `export_manifest.json` with status, timestamps, counts, exported page IDs, and errors.

## Create workflow

Sprinter sends a JSON object to Jira's create-issue endpoint and stores the evidence of the call.

The typical minimum payload is:

```json
{
  "fields": {
    "project": { "key": "SCRUM" },
    "issuetype": { "name": "Task" },
    "summary": "Follow up on exporter rollout"
  }
}
```

Notes:

- Start from `ticket.json.example` when creating a new payload.
- Rich text fields such as `description` should use Atlassian Document Format.
- Custom fields can be included directly under `fields`, for example `customfield_10042`.
- Subtasks can be created when the issue type and required `parent` field match your Jira project configuration.
- On success, artifacts are written to `exports/created/<ISSUE-KEY>/`.

## MCP extensions

The MCP servers are optional. They are useful when you want an MCP client to call Sprinter as a local tool while keeping large JSON artifacts on disk.

The existing stdio server is launched by the client as a subprocess:

```bash
.venv/bin/python -m MCPJira.server
```

The Streamable HTTP server runs as a local HTTP service:

```bash
.venv/bin/python -m JiraStreamableMCP.server
```

Default HTTP endpoint:

```text
http://127.0.0.1:8000/mcp
```

The SSE server runs as a local HTTP service with separate stream and message endpoints:

```bash
.venv/bin/python -m JiraSSEMCP.server
```

Default SSE endpoints:

```text
http://127.0.0.1:8001/sse
http://127.0.0.1:8001/messages/
```

All MCP packages read `SPRINTER_CONFIG` when it is set, otherwise they fall back to `config.yaml`. `JiraStreamableMCP` supports `JIRA_STREAMABLE_MCP_*` environment variables. `JiraSSEMCP` supports `JIRA_SSE_MCP_*` environment variables.

See `MCPJira/README.md`, `JiraStreamableMCP/README.md`, and `JiraSSEMCP/README.md` for tool names, resource URIs, and client configuration notes.

## Webhook server

Sprinter can also run a local webhook server that receives Jira events, verifies the webhook secret or Jira's signed `X-Hub-Signature`, deduplicates repeated deliveries on the filesystem, queues export jobs, and reuses the existing export workflow.

For a full step-by-step runbook, see `webhooks/README.md`.

Webhook defaults live in `webhooks/config.yaml`, including the local shared secret used by the server at startup. You can still override the secret with an environment variable when needed:

```bash
export SPRINTER_WEBHOOK_SECRET="choose-a-long-random-value"
```

Run the server:

```bash
.venv/bin/python -m webhooks.server
```

Default endpoints:

```text
POST http://127.0.0.1:8090/webhooks/jira
GET  http://127.0.0.1:8090/health
GET  http://127.0.0.1:8090/ready
GET  http://127.0.0.1:8090/jobs/<job_id>
```

For local smoke tests, send the shared secret header:

```text
X-Sprinter-Webhook-Secret: <auth.secret from webhooks/config.yaml or SPRINTER_WEBHOOK_SECRET>
```

For Jira admin webhooks, set the same value as the Jira webhook `Secret`. Jira will sign the payload and Sprinter will verify the `X-Hub-Signature` header.

Webhook state is stored under `<storage.export_path>/.webhooks/` by default:

```text
events/        dedupe records
jobs/queued/   accepted jobs waiting for export
jobs/running/  jobs currently being exported
jobs/success/  completed jobs
jobs/failed/   failed jobs with errors
```

The default event list covers issue-scoped Jira events: issue created/updated/deleted, comments, worklogs, attachments, issue links, and issue properties. `jira:issue_deleted` is recorded for audit and dedupe, but it does not create an export job because the deleted issue may no longer be readable through Jira's API.

Useful environment variables:

- `SPRINTER_WEBHOOK_SETTINGS_FILE`: override the webhook settings file, default `webhooks/config.yaml`.
- `SPRINTER_WEBHOOK_HOST`: bind host, default `127.0.0.1`.
- `SPRINTER_WEBHOOK_PORT`: bind port, default `8090`.
- `SPRINTER_WEBHOOK_JIRA_PATH`: Jira webhook route, default `/webhooks/jira`.
- `SPRINTER_WEBHOOK_ALLOWED_EVENTS`: comma-separated Jira events to export.
- `SPRINTER_WEBHOOK_ALLOWED_PROJECTS`: optional comma-separated Jira project keys.
- `SPRINTER_WEBHOOK_STORE_PATH`: override filesystem state directory.
- `SPRINTER_WEBHOOK_WORKER_ENABLED`: set to `false` to receive and queue without processing.

For Jira Cloud to reach a local machine, expose this server through a tunnel such as ngrok or cloudflared, then configure the Jira webhook URL to point to the public tunnel URL plus `/webhooks/jira`.

## Webhook setup automation

`webhooks/setup.py` can start the webhook server, start ngrok, discover the public HTTPS URL, register the Jira admin webhook, and run readiness checks in one command.

Add your ngrok auth token to `webhooks/ngrok_config.yaml` on your machine:

```yaml
ngrok:
  auth_token: "your-ngrok-authtoken"
```

You can also keep the config file blank and use an environment variable:

```bash
export NGROK_AUTHTOKEN="your-ngrok-authtoken"
```

Run the full setup:

```bash
.venv/bin/python -m webhooks.setup
```

The setup command uses:

```text
webhooks/ngrok_config.yaml     ngrok, Jira webhook, and smoke-test settings
webhooks/config.yaml           webhook signing secret
config.yaml                    Jira credentials and export settings
```

By default it replaces any existing Jira admin webhook with the same name, registers the new ngrok URL, sends a signed smoke event for the configured issue key, and keeps the webhook server and ngrok running until you press `Ctrl+C`.

Useful options:

```bash
.venv/bin/python -m webhooks.setup --skip-smoke-test
.venv/bin/python -m webhooks.setup --keep-existing
.venv/bin/python -m webhooks.setup --no-register
```

## Webhook API package

`webhookAPI/` manages Jira webhook registrations programmatically. It uses the same `config.yaml` Jira credentials as the exporter.

Create the admin webhook that points Jira at your current ngrok URL:

```bash
WEBHOOK_SECRET=$(.venv/bin/python -c "import yaml; print(yaml.safe_load(open('webhooks/config.yaml', encoding='utf-8'))['auth']['secret'])")

.venv/bin/python -m webhookAPI admin-create \
  --name "Sprinter local export webhook" \
  --url "https://<your-ngrok-domain>/webhooks/jira" \
  --jql "project = SCRUM" \
  --secret "$WEBHOOK_SECRET"
```

List, inspect, and delete Jira admin webhooks:

```bash
.venv/bin/python -m webhookAPI admin-list
.venv/bin/python -m webhookAPI admin-get <webhook_id>
.venv/bin/python -m webhookAPI admin-delete <webhook_id>
```

The package also includes dynamic app webhook helpers:

```bash
.venv/bin/python -m webhookAPI dynamic-register --url "https://example.com/webhooks/jira" --jql "project = SCRUM"
.venv/bin/python -m webhookAPI dynamic-list
.venv/bin/python -m webhookAPI dynamic-delete <webhook_id> [<webhook_id> ...]
.venv/bin/python -m webhookAPI dynamic-refresh <webhook_id> [<webhook_id> ...]
```

Jira's dynamic webhook API is intended for Connect/OAuth app contexts. Normal Jira administrator/API-token workflows should use the `admin-*` commands.

## Tests

Run the core tests:

```bash
.venv/bin/python -m unittest discover -s tests
```

Run the MCP service tests:

```bash
.venv/bin/python -m unittest discover -s MCPJira/tests
```

Run the Streamable HTTP MCP tests:

```bash
.venv/bin/python -m unittest discover -s JiraStreamableMCP/tests
```

Run the SSE MCP tests:

```bash
.venv/bin/python -m unittest discover -s JiraSSEMCP/tests
```

## Current limitations

- Confluence discovery starts from Jira remote links only. Sprinter does not scan issue descriptions, comments, or arbitrary fields for Confluence URLs.
- Only same-host Confluence links are considered, based on `confluence.base_url`.
- Legacy Confluence display URLs are resolved through search when possible; custom or unusual URL formats may remain in `wiki/unresolved_links.json`.
- Page bodies are saved in Confluence storage format, not rendered browser HTML.
- The exporter is single-issue oriented. Bulk export would need a wrapper or a new workflow.
