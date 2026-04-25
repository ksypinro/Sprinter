"""FastMCP app factory for the Jira Streamable HTTP server."""

import json
import re
from typing import Optional

from mcp.server.fastmcp import FastMCP
from starlette.middleware.cors import CORSMiddleware

from JiraStreamableMCP.service import JiraStreamableService
from JiraStreamableMCP.settings import JiraStreamableMCPSettings


_CORS_ALLOW_METHODS = ("GET", "POST", "DELETE", "OPTIONS")
_CORS_ALLOW_HEADERS = (
    "accept",
    "authorization",
    "content-type",
    "last-event-id",
    "mcp-protocol-version",
    "mcp-session-id",
)
_CORS_EXPOSE_HEADERS = ("mcp-session-id", "www-authenticate")


class JiraStreamableFastMCP(FastMCP):
    """FastMCP variant that adds CORS to the generated Streamable HTTP app."""

    def __init__(self, *args, jira_settings: JiraStreamableMCPSettings, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._jira_settings = jira_settings

    def streamable_http_app(self):
        """Return a Streamable HTTP Starlette app with configured CORS support."""

        app = super().streamable_http_app()
        if not self._jira_settings.cors_enabled:
            return app

        allow_origins, allow_origin_regex = _split_cors_origins(self._jira_settings.cors_origins)
        app.add_middleware(
            CORSMiddleware,
            allow_origins=allow_origins,
            allow_origin_regex=allow_origin_regex,
            allow_methods=list(_CORS_ALLOW_METHODS),
            allow_headers=list(_CORS_ALLOW_HEADERS),
            expose_headers=list(_CORS_EXPOSE_HEADERS),
            allow_credentials=self._jira_settings.cors_allow_credentials,
        )
        return app


def _split_cors_origins(origins: tuple[str, ...]) -> tuple[list[str], str | None]:
    """Split exact CORS origins from local wildcard-port origin patterns."""

    if "*" in origins:
        return ["*"], None

    exact_origins: list[str] = []
    wildcard_patterns: list[str] = []
    for origin in origins:
        if origin.endswith(":*"):
            wildcard_patterns.append(f"{re.escape(origin[:-2])}(?::[0-9]+)?")
        else:
            exact_origins.append(origin)

    allow_origin_regex = f"^(?:{'|'.join(wildcard_patterns)})$" if wildcard_patterns else None
    return exact_origins, allow_origin_regex


def create_streamable_mcp(
    settings: Optional[JiraStreamableMCPSettings] = None,
    service: Optional[JiraStreamableService] = None,
) -> FastMCP:
    """Create a Streamable HTTP-focused FastMCP app.

    Args:
        settings: Optional server settings. Environment-backed defaults are
            used when omitted.
        service: Optional service instance, primarily useful for tests.

    Returns:
        FastMCP: Configured MCP application with tools and resources.
    """

    resolved_settings = settings or JiraStreamableMCPSettings.from_env()
    resolved_service = service or JiraStreamableService(config_path=resolved_settings.config_path)

    mcp = JiraStreamableFastMCP(
        "JiraStreamableMCP",
        jira_settings=resolved_settings,
        json_response=True,
        host=resolved_settings.host,
        port=resolved_settings.port,
        streamable_http_path=resolved_settings.path,
        stateless_http=resolved_settings.stateless_http,
        log_level=resolved_settings.log_level,
    )

    @mcp.tool()
    def jira_streamable_server_info() -> dict:
        """Return non-secret server configuration and resource URI templates."""

        return {
            **resolved_service.server_info(),
            "host": resolved_settings.host,
            "port": resolved_settings.port,
            "path": resolved_settings.path,
            "stateless_http": resolved_settings.stateless_http,
            "cors_enabled": resolved_settings.cors_enabled,
            "cors_origins": list(resolved_settings.cors_origins),
            "cors_allow_credentials": resolved_settings.cors_allow_credentials,
        }

    @mcp.tool()
    def jira_stream_export_issue(ticket_url: str) -> dict:
        """Export a Jira issue and linked Confluence content through HTTP MCP."""

        return resolved_service.export_issue(ticket_url)

    @mcp.tool()
    def jira_stream_create_issue(payload: dict) -> dict:
        """Create a Jira issue from a structured JSON payload through HTTP MCP."""

        return resolved_service.create_issue(payload)

    @mcp.tool()
    def jira_stream_get_export_manifest(issue_key: str) -> dict:
        """Return a saved export manifest for an already exported issue."""

        return resolved_service.read_export_manifest(issue_key)

    @mcp.tool()
    def jira_stream_get_created_issue_response(issue_key: str) -> dict:
        """Return a saved Jira create-issue response for an issue key."""

        return resolved_service.read_created_issue_response(issue_key)

    @mcp.resource("jirastream://exports/{issue_key}/manifest")
    def export_manifest_resource(issue_key: str) -> str:
        """Expose an exported issue manifest as a read-only JSON resource."""

        return json.dumps(resolved_service.read_export_manifest(issue_key), indent=2, ensure_ascii=False)

    @mcp.resource("jirastream://created/{issue_key}/response")
    def created_issue_response_resource(issue_key: str) -> str:
        """Expose a created-issue response as a read-only JSON resource."""

        return json.dumps(resolved_service.read_created_issue_response(issue_key), indent=2, ensure_ascii=False)

    return mcp
