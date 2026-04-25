"""Environment-backed settings for the Jira Streamable HTTP MCP server."""

from dataclasses import dataclass
import os
from typing import Mapping, Optional


class JiraStreamableMCPSettingsError(ValueError):
    """Raised when HTTP MCP server settings are invalid."""


@dataclass(frozen=True)
class JiraStreamableMCPSettings:
    """Runtime settings for the Streamable HTTP MCP entrypoint."""

    DEFAULT_CORS_ORIGINS = (
        "http://localhost:*",
        "http://127.0.0.1:*",
        "http://[::1]:*",
        "https://localhost:*",
        "https://127.0.0.1:*",
        "https://[::1]:*",
    )

    host: str = "127.0.0.1"
    port: int = 8000
    path: str = "/mcp"
    config_path: str = "config.yaml"
    log_level: str = "INFO"
    stateless_http: bool = False
    cors_enabled: bool = True
    cors_origins: tuple[str, ...] = DEFAULT_CORS_ORIGINS
    cors_allow_credentials: bool = False

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "JiraStreamableMCPSettings":
        """Build settings from environment variables.

        Supported variables:
        - ``JIRA_STREAMABLE_MCP_HOST``
        - ``JIRA_STREAMABLE_MCP_PORT``
        - ``JIRA_STREAMABLE_MCP_PATH``
        - ``JIRA_STREAMABLE_MCP_CONFIG`` or ``SPRINTER_CONFIG``
        - ``JIRA_STREAMABLE_MCP_LOG_LEVEL``
        - ``JIRA_STREAMABLE_MCP_STATELESS_HTTP``
        - ``JIRA_STREAMABLE_MCP_CORS_ENABLED``
        - ``JIRA_STREAMABLE_MCP_CORS_ORIGINS``
        - ``JIRA_STREAMABLE_MCP_CORS_ALLOW_CREDENTIALS``
        """

        source = env or os.environ
        host = source.get("JIRA_STREAMABLE_MCP_HOST", cls.host).strip()
        path = source.get("JIRA_STREAMABLE_MCP_PATH", cls.path).strip()
        config_path = source.get("JIRA_STREAMABLE_MCP_CONFIG") or source.get("SPRINTER_CONFIG", cls.config_path)
        log_level = source.get("JIRA_STREAMABLE_MCP_LOG_LEVEL", cls.log_level).strip().upper()
        stateless = cls._parse_bool(
            source.get("JIRA_STREAMABLE_MCP_STATELESS_HTTP"),
            default=cls.stateless_http,
            field_name="JIRA_STREAMABLE_MCP_STATELESS_HTTP",
        )
        cors_enabled = cls._parse_bool(
            source.get("JIRA_STREAMABLE_MCP_CORS_ENABLED"),
            default=cls.cors_enabled,
            field_name="JIRA_STREAMABLE_MCP_CORS_ENABLED",
        )
        cors_allow_credentials = cls._parse_bool(
            source.get("JIRA_STREAMABLE_MCP_CORS_ALLOW_CREDENTIALS"),
            default=cls.cors_allow_credentials,
            field_name="JIRA_STREAMABLE_MCP_CORS_ALLOW_CREDENTIALS",
        )
        cors_origins = cls._parse_csv(
            source.get("JIRA_STREAMABLE_MCP_CORS_ORIGINS"),
            default=cls.DEFAULT_CORS_ORIGINS,
        )

        try:
            port = int(source.get("JIRA_STREAMABLE_MCP_PORT", str(cls.port)))
        except ValueError as exc:
            raise JiraStreamableMCPSettingsError("JIRA_STREAMABLE_MCP_PORT must be an integer.") from exc

        if not host:
            raise JiraStreamableMCPSettingsError("JIRA_STREAMABLE_MCP_HOST must not be empty.")
        if port < 1 or port > 65535:
            raise JiraStreamableMCPSettingsError("JIRA_STREAMABLE_MCP_PORT must be between 1 and 65535.")
        if not path.startswith("/"):
            raise JiraStreamableMCPSettingsError("JIRA_STREAMABLE_MCP_PATH must start with '/'.")
        if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise JiraStreamableMCPSettingsError("JIRA_STREAMABLE_MCP_LOG_LEVEL is not a valid Python logging level.")
        if cors_enabled and not cors_origins:
            raise JiraStreamableMCPSettingsError("JIRA_STREAMABLE_MCP_CORS_ORIGINS must not be empty when CORS is enabled.")
        if cors_enabled and cors_allow_credentials and "*" in cors_origins:
            raise JiraStreamableMCPSettingsError(
                "JIRA_STREAMABLE_MCP_CORS_ORIGINS cannot include '*' when CORS credentials are enabled."
            )

        return cls(
            host=host,
            port=port,
            path=path,
            config_path=config_path.strip() if config_path else cls.config_path,
            log_level=log_level,
            stateless_http=stateless,
            cors_enabled=cors_enabled,
            cors_origins=cors_origins,
            cors_allow_credentials=cors_allow_credentials,
        )

    @staticmethod
    def _parse_bool(value: Optional[str], default: bool, field_name: str) -> bool:
        """Parse a small set of environment-friendly boolean strings."""

        if value is None:
            return default
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        raise JiraStreamableMCPSettingsError(f"{field_name} must be a boolean value.")

    @staticmethod
    def _parse_csv(value: Optional[str], default: tuple[str, ...]) -> tuple[str, ...]:
        """Parse a comma-separated environment variable into a trimmed tuple."""

        if value is None:
            return default
        return tuple(item.strip() for item in value.split(",") if item.strip())
