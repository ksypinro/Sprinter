"""CLI for programmatic Jira webhook management."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict

from webhookAPI.factory import build_webhook_api_client


DEFAULT_EVENTS = (
    "jira:issue_created",
    "jira:issue_updated",
    "jira:issue_deleted",
    "comment_created",
    "comment_updated",
    "comment_deleted",
    "worklog_created",
    "worklog_updated",
    "worklog_deleted",
    "attachment_created",
    "attachment_deleted",
    "issuelink_created",
    "issuelink_deleted",
    "issue_property_set",
    "issue_property_deleted",
)


def parse_args() -> argparse.Namespace:
    """Parse webhook API CLI arguments."""

    parser = argparse.ArgumentParser(description="Manage Jira webhooks programmatically.")
    parser.add_argument("--config", default="config.yaml", help="Sprinter config path.")

    subparsers = parser.add_subparsers(dest="command", required=True)

    admin_create = subparsers.add_parser("admin-create", aliases=["admin-add"], help="Create a Jira admin webhook.")
    admin_create.add_argument("--name", default="Sprinter webhook", help="Webhook name.")
    admin_create.add_argument("--description", default="Created by Sprinter webhookAPI.", help="Webhook description.")
    admin_create.add_argument("--url", required=True, help="Public webhook callback URL.")
    admin_create.add_argument("--events", default=",".join(DEFAULT_EVENTS), help="Comma-separated Jira events.")
    admin_create.add_argument("--jql", default="project = SCRUM", help="JQL filter for issue-related events.")
    admin_create.add_argument("--secret", help="Webhook HMAC secret. Defaults to no secret if omitted.")
    admin_create.add_argument("--exclude-body", action="store_true", help="Ask Jira not to send the JSON payload.")

    subparsers.add_parser("admin-list", help="List Jira admin webhooks.")

    admin_get = subparsers.add_parser("admin-get", help="Get one Jira admin webhook.")
    admin_get.add_argument("webhook_id", help="Webhook id.")

    admin_delete = subparsers.add_parser("admin-delete", help="Delete one Jira admin webhook.")
    admin_delete.add_argument("webhook_id", help="Webhook id.")

    dynamic_register = subparsers.add_parser("dynamic-register", aliases=["dynamic-add"], help="Register dynamic app webhooks.")
    dynamic_register.add_argument("--url", required=True, help="Public webhook callback URL.")
    dynamic_register.add_argument("--events", default="jira:issue_created,jira:issue_updated", help="Comma-separated Jira events.")
    dynamic_register.add_argument("--jql", default="project = SCRUM", help="Dynamic webhook JQL filter.")

    dynamic_list = subparsers.add_parser("dynamic-list", help="List dynamic app webhooks.")
    dynamic_list.add_argument("--start-at", type=int, default=0, help="Pagination start.")
    dynamic_list.add_argument("--max-results", type=int, default=100, help="Page size.")

    dynamic_delete = subparsers.add_parser("dynamic-delete", help="Delete dynamic app webhooks.")
    dynamic_delete.add_argument("webhook_ids", nargs="+", help="Webhook ids.")

    dynamic_refresh = subparsers.add_parser("dynamic-refresh", help="Refresh dynamic app webhooks.")
    dynamic_refresh.add_argument("webhook_ids", nargs="+", help="Webhook ids.")

    return parser.parse_args()


def main() -> None:
    """Run the webhook API CLI."""

    args = parse_args()
    client = build_webhook_api_client(args.config)
    result: Any

    if args.command == "admin-create":
        result = client.create_admin_webhook(
            name=args.name,
            description=args.description,
            url=args.url,
            events=_parse_events(args.events),
            jql_filter=args.jql,
            exclude_body=args.exclude_body,
            secret=args.secret,
        )
    elif args.command == "admin-list":
        result = client.get_admin_webhooks()
    elif args.command == "admin-get":
        result = client.get_admin_webhook(args.webhook_id)
    elif args.command == "admin-delete":
        result = client.delete_admin_webhook(args.webhook_id)
    elif args.command == "dynamic-register":
        result = client.register_dynamic_webhooks(
            args.url,
            [client.build_dynamic_webhook_details(_parse_events(args.events), args.jql)],
        )
    elif args.command == "dynamic-list":
        result = client.get_dynamic_webhooks(start_at=args.start_at, max_results=args.max_results)
    elif args.command == "dynamic-delete":
        result = client.delete_dynamic_webhooks(args.webhook_ids)
    elif args.command == "dynamic-refresh":
        result = client.refresh_dynamic_webhooks(args.webhook_ids)
    else:
        raise SystemExit(f"Unknown command: {args.command}")

    _write_json(result)


def _parse_events(value: str) -> tuple[str, ...]:
    """Parse comma-separated event names."""

    events = tuple(event.strip() for event in value.split(",") if event.strip())
    if not events:
        raise SystemExit("At least one event is required.")
    return events


def _write_json(payload: Dict[str, Any] | Any) -> None:
    """Print JSON response payload."""

    json.dump(payload, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
