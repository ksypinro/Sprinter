# JiraSSEMCP

`JiraSSEMCP` is a separate SSE MCP package for Sprinter. It does not replace the existing `MCPJira` stdio package or the `JiraStreamableMCP` Streamable HTTP package.

Default endpoints:

```text
SSE stream:     http://127.0.0.1:8001/sse
POST messages:  http://127.0.0.1:8001/messages/
```

Use this package when a client still expects the older MCP SSE transport. Prefer `JiraStreamableMCP` for clients that support Streamable HTTP.

## Install

From the repository root:

```bash
.venv/bin/pip install -r JiraSSEMCP/requirements.txt
```

## Run

```bash
.venv/bin/python -m JiraSSEMCP.server
```

With explicit options:

```bash
.venv/bin/python -m JiraSSEMCP.server \
  --host 127.0.0.1 \
  --port 8001 \
  --sse-path /sse \
  --message-path /messages/ \
  --config config.yaml
```

## Environment variables

- `JIRA_SSE_MCP_HOST`: HTTP bind host. Default: `127.0.0.1`.
- `JIRA_SSE_MCP_PORT`: HTTP bind port. Default: `8001`.
- `JIRA_SSE_MCP_MOUNT_PATH`: advertised mount path. Default: `/`.
- `JIRA_SSE_MCP_SSE_PATH`: SSE GET path. Default: `/sse`.
- `JIRA_SSE_MCP_MESSAGE_PATH`: client POST message path. Default: `/messages/`.
- `JIRA_SSE_MCP_CONFIG`: Sprinter config path.
- `SPRINTER_CONFIG`: fallback config path when `JIRA_SSE_MCP_CONFIG` is not set.
- `JIRA_SSE_MCP_LOG_LEVEL`: server log level. Default: `INFO`.

Corporate SSL and proxy variables are still honored by Python `requests`:

```bash
export REQUESTS_CA_BUNDLE="/path/to/company-ca-bundle.crt"
export SSL_CERT_FILE="/path/to/company-ca-bundle.crt"
export HTTPS_PROXY="http://proxy.company.com:8080"
export HTTP_PROXY="http://proxy.company.com:8080"
export NO_PROXY="localhost,127.0.0.1,::1"
```

`NO_PROXY` is important for local clients so calls to `127.0.0.1:8001` do not go through the corporate proxy.

## Tools

- `jira_sse_server_info()`
- `jira_sse_export_issue(ticket_url: str)`
- `jira_sse_create_issue(payload: dict)`
- `jira_sse_get_export_manifest(issue_key: str)`
- `jira_sse_get_created_issue_response(issue_key: str)`

## Resources

- `jirasse://exports/{issue_key}/manifest`
- `jirasse://created/{issue_key}/response`

## Security notes

Keep the default host as `127.0.0.1` unless you have a clear reason to expose the server to other machines. If you bind to `0.0.0.0`, protect the process with firewall rules, a trusted network boundary, and HTTPS/auth at a reverse proxy.

The server has access to Jira/Confluence credentials through `config.yaml` or environment variables. Treat the SSE endpoint as privileged.

## Tests

```bash
.venv/bin/python -m unittest discover -s JiraSSEMCP/tests
```
