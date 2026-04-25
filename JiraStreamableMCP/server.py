"""Streamable HTTP MCP server entrypoint for Sprinter Jira workflows."""

import argparse

from JiraStreamableMCP.app import create_streamable_mcp
from JiraStreamableMCP.settings import JiraStreamableMCPSettings


def parse_args() -> argparse.Namespace:
    """Parse optional command-line overrides for the HTTP MCP server."""

    env_defaults = JiraStreamableMCPSettings.from_env()
    parser = argparse.ArgumentParser(description="Run the JiraStreamableMCP Streamable HTTP server.")
    parser.add_argument("--host", default=env_defaults.host, help="HTTP bind host. Defaults to 127.0.0.1.")
    parser.add_argument("--port", default=env_defaults.port, type=int, help="HTTP bind port. Defaults to 8000.")
    parser.add_argument("--path", default=env_defaults.path, help="Streamable HTTP MCP path. Defaults to /mcp.")
    parser.add_argument("--config", default=env_defaults.config_path, help="Sprinter config path. Defaults to config.yaml.")
    parser.add_argument("--log-level", default=env_defaults.log_level, help="Server log level.")
    cors_group = parser.add_mutually_exclusive_group()
    cors_group.add_argument("--enable-cors", dest="cors_enabled", action="store_true", help="Enable browser CORS support.")
    cors_group.add_argument("--disable-cors", dest="cors_enabled", action="store_false", help="Disable browser CORS support.")
    parser.set_defaults(cors_enabled=env_defaults.cors_enabled)
    parser.add_argument(
        "--cors-origins",
        default=",".join(env_defaults.cors_origins),
        help="Comma-separated allowed CORS origins. Use :* to allow any port, or * to allow every origin.",
    )
    cors_credentials_group = parser.add_mutually_exclusive_group()
    cors_credentials_group.add_argument(
        "--cors-allow-credentials",
        dest="cors_allow_credentials",
        action="store_true",
        help="Allow credentialed CORS requests.",
    )
    cors_credentials_group.add_argument(
        "--no-cors-allow-credentials",
        dest="cors_allow_credentials",
        action="store_false",
        help="Disallow credentialed CORS requests.",
    )
    parser.set_defaults(cors_allow_credentials=env_defaults.cors_allow_credentials)
    parser.add_argument(
        "--stateless-http",
        action="store_true",
        default=env_defaults.stateless_http,
        help="Use stateless Streamable HTTP sessions.",
    )
    return parser.parse_args()


def settings_from_args(args: argparse.Namespace) -> JiraStreamableMCPSettings:
    """Convert parsed CLI args into validated settings."""

    env = {
        "JIRA_STREAMABLE_MCP_HOST": args.host,
        "JIRA_STREAMABLE_MCP_PORT": str(args.port),
        "JIRA_STREAMABLE_MCP_PATH": args.path,
        "JIRA_STREAMABLE_MCP_CONFIG": args.config,
        "JIRA_STREAMABLE_MCP_LOG_LEVEL": args.log_level,
        "JIRA_STREAMABLE_MCP_STATELESS_HTTP": "true" if args.stateless_http else "false",
        "JIRA_STREAMABLE_MCP_CORS_ENABLED": "true" if args.cors_enabled else "false",
        "JIRA_STREAMABLE_MCP_CORS_ORIGINS": args.cors_origins,
        "JIRA_STREAMABLE_MCP_CORS_ALLOW_CREDENTIALS": "true" if args.cors_allow_credentials else "false",
    }
    return JiraStreamableMCPSettings.from_env(env)


def main() -> None:
    """Run the MCP server using the Streamable HTTP transport."""

    settings = settings_from_args(parse_args())
    create_streamable_mcp(settings).run(transport="streamable-http")


if __name__ == "__main__":
    main()
