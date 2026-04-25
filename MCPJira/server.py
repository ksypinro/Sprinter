"""Minimal MCP server for Sprinter.

The server exposes coarse Jira export/create tools and a couple of read-only
resources for larger JSON artifacts. It is designed to run over stdio so local
clients such as Codex or Cline can use it with minimal overhead.
"""

import json

from mcp.server.fastmcp import FastMCP

from MCPJira.service import SprinterService


mcp = FastMCP("MCPJira", json_response=True)
service = SprinterService()


@mcp.tool()
def jira_export_issue(ticket_url: str) -> dict:
    """Export a Jira issue and linked Confluence pages into local artifacts."""

    return service.export_issue(ticket_url)


@mcp.tool()
def jira_create_issue(payload: dict) -> dict:
    """Create a Jira issue from a structured JSON payload."""

    return service.create_issue(payload)


@mcp.tool()
def jira_get_export_manifest(issue_key: str) -> dict:
    """Return the saved export manifest for an already exported issue."""

    return service.read_export_manifest(issue_key)


@mcp.tool()
def jira_get_created_issue_response(issue_key: str) -> dict:
    """Return the saved Jira create-issue response for an issue key."""

    return service.read_created_issue_response(issue_key)


@mcp.resource("sprinter://exports/{issue_key}/manifest")
def export_manifest_resource(issue_key: str) -> str:
    """Expose an export manifest as a read-only JSON resource."""

    return json.dumps(service.read_export_manifest(issue_key), indent=2, ensure_ascii=False)


@mcp.resource("sprinter://created/{issue_key}/response")
def created_issue_response_resource(issue_key: str) -> str:
    """Expose a created-issue response artifact as a read-only JSON resource."""

    return json.dumps(service.read_created_issue_response(issue_key), indent=2, ensure_ascii=False)


def main() -> None:
    """Run the MCP server over stdio for local client integration."""

    mcp.run()


if __name__ == "__main__":
    main()
