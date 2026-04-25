"""FastMCP app factory for the Jira SSE server."""

import json
from typing import Optional

from mcp.server.fastmcp import FastMCP

from JiraSSEMCP.service import JiraSSEService
from JiraSSEMCP.settings import JiraSSEMCPSettings


def create_sse_mcp(
    settings: Optional[JiraSSEMCPSettings] = None,
    service: Optional[JiraSSEService] = None,
) -> FastMCP:
    """Create an SSE-focused FastMCP app.

    Args:
        settings: Optional server settings. Environment-backed defaults are
            used when omitted.
        service: Optional service instance, primarily useful for tests.

    Returns:
        FastMCP: Configured MCP application with SSE paths and handlers.
    """

    resolved_settings = settings or JiraSSEMCPSettings.from_env()
    resolved_service = service or JiraSSEService(config_path=resolved_settings.config_path)

    mcp = FastMCP(
        "JiraSSEMCP",
        json_response=True,
        host=resolved_settings.host,
        port=resolved_settings.port,
        mount_path=resolved_settings.mount_path,
        sse_path=resolved_settings.sse_path,
        message_path=resolved_settings.message_path,
        log_level=resolved_settings.log_level,
    )

    @mcp.tool()
    def jira_sse_server_info() -> dict:
        """Return non-secret server configuration and resource URI templates."""

        return {
            **resolved_service.server_info(),
            "host": resolved_settings.host,
            "port": resolved_settings.port,
            "mount_path": resolved_settings.mount_path,
            "sse_path": resolved_settings.sse_path,
            "message_path": resolved_settings.message_path,
        }

    @mcp.tool()
    def jira_sse_export_issue(ticket_url: str) -> dict:
        """Export a Jira issue and linked Confluence content through SSE MCP."""

        return resolved_service.export_issue(ticket_url)

    @mcp.tool()
    def jira_sse_create_issue(payload: dict) -> dict:
        """Create a Jira issue from a structured JSON payload through SSE MCP."""

        return resolved_service.create_issue(payload)

    @mcp.tool()
    def jira_sse_get_export_manifest(issue_key: str) -> dict:
        """Return a saved export manifest for an already exported issue."""

        return resolved_service.read_export_manifest(issue_key)

    @mcp.tool()
    def jira_sse_get_created_issue_response(issue_key: str) -> dict:
        """Return a saved Jira create-issue response for an issue key."""

        return resolved_service.read_created_issue_response(issue_key)

    @mcp.resource("jirasse://exports/{issue_key}/manifest")
    def export_manifest_resource(issue_key: str) -> str:
        """Expose an exported issue manifest as a read-only JSON resource."""

        return json.dumps(resolved_service.read_export_manifest(issue_key), indent=2, ensure_ascii=False)

    @mcp.resource("jirasse://created/{issue_key}/response")
    def created_issue_response_resource(issue_key: str) -> str:
        """Expose a created-issue response as a read-only JSON resource."""

        return json.dumps(resolved_service.read_created_issue_response(issue_key), indent=2, ensure_ascii=False)

    return mcp
