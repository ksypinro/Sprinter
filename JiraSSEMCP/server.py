"""SSE MCP server entrypoint for Sprinter Jira workflows."""

import argparse

from JiraSSEMCP.app import create_sse_mcp
from JiraSSEMCP.settings import JiraSSEMCPSettings


def parse_args() -> argparse.Namespace:
    """Parse optional command-line overrides for the SSE MCP server."""

    env_defaults = JiraSSEMCPSettings.from_env()
    parser = argparse.ArgumentParser(description="Run the JiraSSEMCP SSE server.")
    parser.add_argument("--host", default=env_defaults.host, help="HTTP bind host. Defaults to 127.0.0.1.")
    parser.add_argument("--port", default=env_defaults.port, type=int, help="HTTP bind port. Defaults to 8001.")
    parser.add_argument("--mount-path", default=env_defaults.mount_path, help="Advertised mount path. Defaults to /.")
    parser.add_argument("--sse-path", default=env_defaults.sse_path, help="SSE GET path. Defaults to /sse.")
    parser.add_argument(
        "--message-path",
        default=env_defaults.message_path,
        help="Client POST message path. Defaults to /messages/.",
    )
    parser.add_argument("--config", default=env_defaults.config_path, help="Sprinter config path. Defaults to config.yaml.")
    parser.add_argument("--log-level", default=env_defaults.log_level, help="Server log level.")
    return parser.parse_args()


def settings_from_args(args: argparse.Namespace) -> JiraSSEMCPSettings:
    """Convert parsed CLI args into validated settings."""

    env = {
        "JIRA_SSE_MCP_HOST": args.host,
        "JIRA_SSE_MCP_PORT": str(args.port),
        "JIRA_SSE_MCP_MOUNT_PATH": args.mount_path,
        "JIRA_SSE_MCP_SSE_PATH": args.sse_path,
        "JIRA_SSE_MCP_MESSAGE_PATH": args.message_path,
        "JIRA_SSE_MCP_CONFIG": args.config,
        "JIRA_SSE_MCP_LOG_LEVEL": args.log_level,
    }
    return JiraSSEMCPSettings.from_env(env)


def main() -> None:
    """Run the MCP server using the SSE transport."""

    settings = settings_from_args(parse_args())
    create_sse_mcp(settings).run(transport="sse", mount_path=settings.mount_path)


if __name__ == "__main__":
    main()
