# MCP Servers

Sprinter ships four Model Context Protocol (MCP) servers that expose Jira export/create, orchestrator control, and webhook tools to LLM-powered clients such as Codex, Cline, and Antigravity.

Each server shares the same underlying Sprinter service layer. The only difference is the transport and the set of exposed tools.

## Server Overview

| Server | Package | Transport | Default Port | Purpose |
|---|---|---|---|---|
| MCPJira | `MCPJira` | stdio | – | Jira export/create tools and read-only resources |
| JiraSSEMCP | `JiraSSEMCP` | SSE | 8001 | Same tools as MCPJira, accessible over HTTP SSE |
| JiraStreamableMCP | `JiraStreamableMCP` | Streamable HTTP | 8000 | Same tools, with CORS, stateless mode, and HTTP streaming |
| OrchestratorMCP | `OrchestratorMCP` | stdio | – | Orchestrator status, workflow control, and manual triggers |

---

## MCPJira (stdio)

The simplest and most commonly used server. It runs over stdio so any local MCP client can start it as a subprocess.

### Source Files

```text
MCPJira/
  __init__.py
  server.py      # FastMCP entrypoint, tool and resource definitions
  service.py     # SprinterService facade wrapping export/create workflows
```

### Tools

| Tool | Description |
|---|---|
| `jira_export_issue(ticket_url)` | Export a Jira issue and linked Confluence pages into local artifacts |
| `jira_create_issue(payload)` | Create a Jira issue from a structured JSON payload |
| `jira_get_export_manifest(issue_key)` | Return the saved export manifest for an already exported issue |
| `jira_get_created_issue_response(issue_key)` | Return the saved Jira create-issue response for an issue key |

### Resources

| URI Pattern | Description |
|---|---|
| `sprinter://exports/{issue_key}/manifest` | Read-only JSON export manifest |
| `sprinter://created/{issue_key}/response` | Read-only created-issue response |

### Configuration

The server reads its Sprinter config from:
1. `SPRINTER_CONFIG` environment variable
2. Falls back to `config.yaml` in the working directory

### MCP Client Configuration

```json
{
  "sprinter-stdio": {
    "type": "stdio",
    "command": "/path/to/Sprinter/.venv/bin/python",
    "args": ["-m", "MCPJira.server"],
    "env": {
      "PYTHONPATH": "/path/to/Sprinter",
      "SPRINTER_CONFIG": "/path/to/Sprinter/config.yaml"
    }
  }
}
```

### Running Manually

```bash
.venv/bin/python -m MCPJira.server
```

---

## JiraSSEMCP (SSE)

An HTTP server exposing the same Jira tools over Server-Sent Events. Useful for browser-based or remote MCP clients that cannot use stdio.

### Source Files

```text
JiraSSEMCP/
  __init__.py
  app.py         # SSE MCP application factory
  server.py      # CLI entrypoint with argument parsing
  service.py     # Shared JiraSSEMCPService (same tools as MCPJira)
  settings.py    # Environment-backed settings dataclass
```

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `JIRA_SSE_MCP_HOST` | `127.0.0.1` | HTTP bind host |
| `JIRA_SSE_MCP_PORT` | `8001` | HTTP bind port |
| `JIRA_SSE_MCP_MOUNT_PATH` | `/` | Mount path for the SSE application |
| `JIRA_SSE_MCP_SSE_PATH` | `/sse` | Path clients subscribe to for SSE events |
| `JIRA_SSE_MCP_MESSAGE_PATH` | `/messages/` | Path clients POST messages to |
| `JIRA_SSE_MCP_CONFIG` | `config.yaml` | Sprinter config path |
| `JIRA_SSE_MCP_LOG_LEVEL` | `INFO` | Server log level |

### Running

```bash
.venv/bin/python -m JiraSSEMCP.server
# or with overrides:
.venv/bin/python -m JiraSSEMCP.server --host 0.0.0.0 --port 9001 --config /path/to/config.yaml
```

### MCP Client Configuration

```json
{
  "sprinter-sse": {
    "type": "sse",
    "url": "http://127.0.0.1:8001/sse"
  }
}
```

---

## JiraStreamableMCP (Streamable HTTP)

A more advanced HTTP server that supports Streamable HTTP transport with optional CORS support and stateless sessions. Best for web-based integrations.

### Source Files

```text
JiraStreamableMCP/
  __init__.py
  app.py         # Streamable HTTP MCP application factory
  server.py      # CLI entrypoint with full argument parsing
  service.py     # Shared JiraStreamableMCPService (same tools as MCPJira)
  settings.py    # Environment-backed settings dataclass with CORS options
```

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `JIRA_STREAMABLE_MCP_HOST` | `127.0.0.1` | HTTP bind host |
| `JIRA_STREAMABLE_MCP_PORT` | `8000` | HTTP bind port |
| `JIRA_STREAMABLE_MCP_PATH` | `/mcp` | Streamable HTTP endpoint path |
| `JIRA_STREAMABLE_MCP_CONFIG` | `config.yaml` | Sprinter config path |
| `JIRA_STREAMABLE_MCP_LOG_LEVEL` | `INFO` | Server log level |
| `JIRA_STREAMABLE_MCP_STATELESS_HTTP` | `false` | Enable stateless Streamable HTTP sessions |
| `JIRA_STREAMABLE_MCP_CORS_ENABLED` | `false` | Enable browser CORS support |
| `JIRA_STREAMABLE_MCP_CORS_ORIGINS` | `*` | Comma-separated allowed CORS origins |
| `JIRA_STREAMABLE_MCP_CORS_ALLOW_CREDENTIALS` | `false` | Allow credentialed CORS requests |

### Running

```bash
.venv/bin/python -m JiraStreamableMCP.server
# or with CORS enabled for browser access:
.venv/bin/python -m JiraStreamableMCP.server --enable-cors --cors-origins "http://localhost:3000"
```

### MCP Client Configuration

```json
{
  "sprinter-streamable": {
    "type": "streamableHttp",
    "url": "http://127.0.0.1:8000/mcp"
  }
}
```

---

## OrchestratorMCP (stdio)

A lightweight stdio MCP server that provides workflow management tools. It connects directly to the orchestrator's filesystem store to list, inspect, start, pause, resume, and retry workflows.

### Source Files

```text
OrchestratorMCP/
  server.py      # FastMCP entrypoint with tool definitions
  service.py     # OrchestratorMCPService wrapping OrchestratorService
```

### Tools

| Tool | Description |
|---|---|
| `getOrchestratorStatus()` | Return storage root, workflow count, and all workflow states |
| `listWorkflows()` | List all workflow state dicts |
| `getWorkflow(workflowId)` | Get one workflow's state by issue key |
| `startWorkflow(issueKey, issueUrl?)` | Submit a `jira.issue.created` event to start a new workflow |
| `retryWorkflow(workflowId)` | Request retry of a blocked workflow |
| `pauseWorkflow(workflowId)` | Pause a running workflow |
| `resumeWorkflow(workflowId)` | Resume a paused workflow |

### Configuration

The server reads `orchestrator/config.yaml` from the current working directory to locate the storage root.

### MCP Client Configuration

```json
{
  "sprinter-orchestrator": {
    "type": "stdio",
    "command": "/path/to/Sprinter/.venv/bin/python",
    "args": ["-m", "OrchestratorMCP.server"],
    "env": {
      "PYTHONPATH": "/path/to/Sprinter",
      "SPRINTER_ORCHESTRATOR_STORAGE_ROOT": "/path/to/Sprinter/exports/.orchestrator"
    }
  }
}
```

### Running Manually

```bash
.venv/bin/python -m OrchestratorMCP.server
```

---

## Choosing a Server

- **Local AI coding clients** (Codex, Cline, Antigravity): Use **MCPJira** (stdio) for Jira tools and **OrchestratorMCP** (stdio) for workflow control.
- **Remote or browser-based clients**: Use **JiraStreamableMCP** with CORS enabled.
- **Older SSE-only clients**: Use **JiraSSEMCP**.
- **Full automation**: Use the **Orchestrator CLI** or the **OrchestratorMCP** tools instead of manually calling Jira tools.

## Tests

```bash
# MCPJira tests
.venv/bin/python -m unittest tests.test_main -v

# Full test suite
.venv/bin/python -m unittest discover -s tests -v
```
