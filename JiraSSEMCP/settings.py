"""Environment-backed settings for the Jira SSE MCP server."""

from dataclasses import dataclass
import os
from typing import Mapping, Optional


class JiraSSEMCPSettingsError(ValueError):
    """Raised when SSE MCP server settings are invalid."""


@dataclass(frozen=True)
class JiraSSEMCPSettings:
    """Runtime settings for the SSE MCP entrypoint."""

    host: str = "127.0.0.1"
    port: int = 8001
    mount_path: str = "/"
    sse_path: str = "/sse"
    message_path: str = "/messages/"
    config_path: str = "config.yaml"
    log_level: str = "INFO"

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "JiraSSEMCPSettings":
        """Build settings from environment variables.

        Supported variables:
        - ``JIRA_SSE_MCP_HOST``
        - ``JIRA_SSE_MCP_PORT``
        - ``JIRA_SSE_MCP_MOUNT_PATH``
        - ``JIRA_SSE_MCP_SSE_PATH``
        - ``JIRA_SSE_MCP_MESSAGE_PATH``
        - ``JIRA_SSE_MCP_CONFIG`` or ``SPRINTER_CONFIG``
        - ``JIRA_SSE_MCP_LOG_LEVEL``
        """

        source = env or os.environ
        host = source.get("JIRA_SSE_MCP_HOST", cls.host).strip()
        mount_path = source.get("JIRA_SSE_MCP_MOUNT_PATH", cls.mount_path).strip()
        sse_path = source.get("JIRA_SSE_MCP_SSE_PATH", cls.sse_path).strip()
        message_path = source.get("JIRA_SSE_MCP_MESSAGE_PATH", cls.message_path).strip()
        config_path = source.get("JIRA_SSE_MCP_CONFIG") or source.get("SPRINTER_CONFIG", cls.config_path)
        log_level = source.get("JIRA_SSE_MCP_LOG_LEVEL", cls.log_level).strip().upper()

        try:
            port = int(source.get("JIRA_SSE_MCP_PORT", str(cls.port)))
        except ValueError as exc:
            raise JiraSSEMCPSettingsError("JIRA_SSE_MCP_PORT must be an integer.") from exc

        if not host:
            raise JiraSSEMCPSettingsError("JIRA_SSE_MCP_HOST must not be empty.")
        if port < 1 or port > 65535:
            raise JiraSSEMCPSettingsError("JIRA_SSE_MCP_PORT must be between 1 and 65535.")
        for field_name, path in (
            ("JIRA_SSE_MCP_MOUNT_PATH", mount_path),
            ("JIRA_SSE_MCP_SSE_PATH", sse_path),
            ("JIRA_SSE_MCP_MESSAGE_PATH", message_path),
        ):
            if not path.startswith("/"):
                raise JiraSSEMCPSettingsError(f"{field_name} must start with '/'.")
        if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise JiraSSEMCPSettingsError("JIRA_SSE_MCP_LOG_LEVEL is not a valid Python logging level.")

        return cls(
            host=host,
            port=port,
            mount_path=mount_path,
            sse_path=sse_path,
            message_path=message_path,
            config_path=config_path.strip() if config_path else cls.config_path,
            log_level=log_level,
        )
