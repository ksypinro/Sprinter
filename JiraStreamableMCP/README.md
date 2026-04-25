# JiraStreamableMCP

`JiraStreamableMCP` is a separate HTTP-first MCP package for Sprinter. It does not replace the existing `MCPJira` stdio package. It exposes Jira export and create workflows through the MCP Streamable HTTP transport.

Default endpoint:

```text
http://127.0.0.1:8000/mcp
```

## Install

From the repository root:

```bash
.venv/bin/pip install -r JiraStreamableMCP/requirements.txt
```

## Run

```bash
.venv/bin/python -m JiraStreamableMCP.server
```

With explicit options:

```bash
.venv/bin/python -m JiraStreamableMCP.server \
  --host 127.0.0.1 \
  --port 8000 \
  --path /mcp \
  --config config.yaml \
  --enable-cors \
  --cors-origins "http://localhost:*,http://127.0.0.1:*"
```

## Browser-based MCP clients

Browser clients need CORS because they send MCP requests from a web origin to the Streamable HTTP endpoint. `JiraStreamableMCP` enables CORS by default for local development origins:

```text
http://localhost:*
http://127.0.0.1:*
http://[::1]:*
https://localhost:*
https://127.0.0.1:*
https://[::1]:*
```

The CORS middleware allows `GET`, `POST`, `DELETE`, and `OPTIONS`, accepts the MCP request headers `mcp-session-id`, `mcp-protocol-version`, and `last-event-id`, and exposes `mcp-session-id` so browser clients can keep the Streamable HTTP session.

To allow a specific hosted browser client:

```bash
JIRA_STREAMABLE_MCP_CORS_ORIGINS="https://mcp-client.example.com" \
.venv/bin/python -m JiraStreamableMCP.server
```

To disable CORS:

```bash
.venv/bin/python -m JiraStreamableMCP.server --disable-cors
```

## Cline configuration

Cline does not start this HTTP server for you. Start the server first:

```bash
cd path/to/Sprinter

NO_PROXY="localhost,127.0.0.1,::1" \
.venv/bin/python -m JiraStreamableMCP.server \
  --host 127.0.0.1 \
  --port 8000 \
  --path /mcp \
  --config config.yaml
```

Then add this to `cline_mcp_settings.json`:

```json
{
  "mcpServers": {
    "sprinter-streamable": {
      "url": "http://127.0.0.1:8000/mcp",
      "type": "streamableHttp",
      "disabled": false,
      "timeout": 180
    }
  }
}
```

Use `type: "streamableHttp"`. Do not use `transportType: "streamable-http"` for this Cline remote-server entry.

## Troubleshooting Cline connections

If Cline cannot connect, first verify that the server is listening:

```bash
lsof -nP -iTCP:8000 -sTCP:LISTEN
```

Do not use a browser as the main test. Opening `http://127.0.0.1:8000/mcp` directly can return:

```text
406 Not Acceptable: Client must accept text/event-stream
```

That response does not mean the server is broken. Streamable HTTP MCP expects MCP-specific headers and JSON-RPC messages.

Use this initialize probe instead:

```bash
curl -i -X POST http://127.0.0.1:8000/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl","version":"0"}}}'
```

Expected result:

```text
HTTP/1.1 200 OK
```

If this works but Cline still fails, the problem is usually Cline configuration, proxy behavior, or where Cline is running from.

If Cline is running inside WSL, SSH remote, or a dev container, `127.0.0.1` points to that environment, not necessarily to the host running this Python process. In that case, either run the server in the same environment as Cline or bind to all interfaces:

```bash
.venv/bin/python -m JiraStreamableMCP.server \
  --host 0.0.0.0 \
  --port 8000 \
  --path /mcp \
  --config config.yaml
```

Then configure Cline with the host machine IP:

```json
{
  "mcpServers": {
    "sprinter-streamable": {
      "url": "http://YOUR_HOST_IP:8000/mcp",
      "type": "streamableHttp",
      "disabled": false,
      "timeout": 180
    }
  }
}
```

Only bind to `0.0.0.0` on a trusted network or behind firewall controls.

In corporate environments, make sure localhost traffic bypasses proxies:

```bash
export NO_PROXY="localhost,127.0.0.1,::1"
export no_proxy="localhost,127.0.0.1,::1"
```

## Environment variables

- `JIRA_STREAMABLE_MCP_HOST`: HTTP bind host. Default: `127.0.0.1`.
- `JIRA_STREAMABLE_MCP_PORT`: HTTP bind port. Default: `8000`.
- `JIRA_STREAMABLE_MCP_PATH`: Streamable HTTP path. Default: `/mcp`.
- `JIRA_STREAMABLE_MCP_CONFIG`: Sprinter config path.
- `SPRINTER_CONFIG`: fallback config path when `JIRA_STREAMABLE_MCP_CONFIG` is not set.
- `JIRA_STREAMABLE_MCP_LOG_LEVEL`: server log level. Default: `INFO`.
- `JIRA_STREAMABLE_MCP_STATELESS_HTTP`: boolean flag for stateless HTTP sessions.
- `JIRA_STREAMABLE_MCP_CORS_ENABLED`: boolean flag for browser CORS support. Default: `true`.
- `JIRA_STREAMABLE_MCP_CORS_ORIGINS`: comma-separated allowed origins. `:*` allows any port for that origin host. Default: localhost, `127.0.0.1`, and `[::1]` for HTTP and HTTPS.
- `JIRA_STREAMABLE_MCP_CORS_ALLOW_CREDENTIALS`: boolean flag for credentialed CORS requests. Default: `false`. Do not combine this with `JIRA_STREAMABLE_MCP_CORS_ORIGINS="*"`.

Corporate SSL and proxy variables are still honored by Python `requests`:

```bash
export REQUESTS_CA_BUNDLE="/path/to/company-ca-bundle.crt"
export SSL_CERT_FILE="/path/to/company-ca-bundle.crt"
export HTTPS_PROXY="http://proxy.company.com:8080"
export HTTP_PROXY="http://proxy.company.com:8080"
export NO_PROXY="localhost,127.0.0.1,::1"
```

`NO_PROXY` is important for local clients so calls to `127.0.0.1:8000` do not go through the corporate proxy.

## Tools

- `jira_streamable_server_info()`
- `jira_stream_export_issue(ticket_url: str)`
- `jira_stream_create_issue(payload: dict)`
- `jira_stream_get_export_manifest(issue_key: str)`
- `jira_stream_get_created_issue_response(issue_key: str)`

## Resources

- `jirastream://exports/{issue_key}/manifest`
- `jirastream://created/{issue_key}/response`

## Security notes

Keep the default host as `127.0.0.1` unless you have a clear reason to expose the server to other machines. If you bind to `0.0.0.0`, protect the process with firewall rules, a trusted network boundary, and HTTPS/auth at a reverse proxy.

The server has access to Jira/Confluence credentials through `config.yaml` or environment variables. Treat the HTTP endpoint as privileged.

## Tests

```bash
.venv/bin/python -m unittest discover -s JiraStreamableMCP/tests
```
