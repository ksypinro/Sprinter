# MCPJira

`MCPJira` is the optional MCP surface for Sprinter. It lets an MCP-capable client call the existing Jira export and Jira create workflows without replacing the `main.py` CLI.

The server is intentionally small:

- `MCPJira/server.py` registers FastMCP tools and resources.
- `MCPJira/service.py` adapts tool calls to the existing Sprinter functions.
- Large results stay in `exports/`; tool responses return compact summaries and resource URIs.
- The server runs locally over `stdio` and does not contain an LLM.

## Install

From the repository root:

```bash
.venv/bin/pip install -r MCPJira/requirements.txt
```

`MCPJira/requirements.txt` includes the root Sprinter runtime requirements and adds the MCP SDK.

## Configuration

The MCP service uses the same `config.yaml` structure as the CLI.

By default it reads:

```text
config.yaml
```

Set `SPRINTER_CONFIG` to point at another file:

```bash
export SPRINTER_CONFIG="config.yaml"
```

When a client launches the server from outside the repository root, either start the client from the Sprinter root or adjust `PYTHONPATH` and `SPRINTER_CONFIG` to match that launch directory. The examples in `MCPJira/config-examples/` use relative paths and assume the repository root as the working directory.

## Run

```bash
.venv/bin/python -m MCPJira.server
```

Most MCP clients launch this command for you from their configuration file. The process communicates over standard input/output, so it does not need a port or a browser session.

## Tools

### `jira_export_issue(ticket_url: str)`

Exports a Jira issue and linked Confluence pages into local artifacts.

Returns:

- `issue_key`
- `issue_dir`
- `manifest_path`
- `log_path`
- `manifest_resource`
- `remote_link_count`
- `linked_page_count`
- `exported_page_count`

### `jira_create_issue(payload: dict)`

Creates a Jira issue from a structured JSON payload.

Returns:

- `issue_key`
- `issue_dir`
- `response_path`
- `manifest_path`
- `response_resource`

### `jira_get_export_manifest(issue_key: str)`

Reads `exports/<ISSUE-KEY>/export_manifest.json` and returns it as a structured tool result.

### `jira_get_created_issue_response(issue_key: str)`

Reads `exports/created/<ISSUE-KEY>/ticket_response.json` and returns it as a structured tool result.

## Resources

- `sprinter://exports/{issue_key}/manifest`
- `sprinter://created/{issue_key}/response`

Resources are read-only views over JSON artifacts already written to disk. They are meant for larger payloads that should not be embedded directly in tool responses.

## Client configuration

Ready-to-edit examples for this workspace are included in:

- `MCPJira/config-examples/codex.config.toml`
- `MCPJira/config-examples/cline_mcp_settings.json`

### Codex

Codex reads MCP server configuration from TOML under the `mcp_servers` key. Use the example in:

```text
MCPJira/config-examples/codex.config.toml
```

Common locations:

- `~/.codex/config.toml`
- `.codex/config.toml`

Then verify tool discovery from Codex:

```bash
codex mcp list
```

### Cline

Cline reads MCP server configuration from JSON under the `mcpServers` key. Use the example in:

```text
MCPJira/config-examples/cline_mcp_settings.json
```

Typical settings paths:

- macOS: `~/Library/Application Support/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json`
- Linux: `~/.config/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json`
- Windows: `%APPDATA%/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json`

Restart Cline or the host IDE after editing the settings file.

## Recommended client flow

1. Call `jira_export_issue` with a Jira issue URL.
2. Read `sprinter://exports/{issue_key}/manifest` for the full run summary.
3. Call `jira_create_issue` with a Jira create-issue payload when you need to create a ticket.
4. Read `sprinter://created/{issue_key}/response` for the saved Jira response.

## Tests

```bash
.venv/bin/python -m unittest discover -s MCPJira/tests
```

These tests use fake Jira and Confluence clients, so they do not call Atlassian APIs.
