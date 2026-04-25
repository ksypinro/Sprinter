"""Command-line entrypoint for the Sprinter webhook HTTP server."""

from __future__ import annotations

import argparse
import logging
import os

from webhooks.app import create_webhook_application, create_webhook_server
from webhooks.settings import WebhookSettings, WebhookSettingsError


def parse_args() -> argparse.Namespace:
    """Parse optional command-line overrides for the webhook server."""

    parser = argparse.ArgumentParser(description="Run the Sprinter webhook server.")
    parser.add_argument("--host", help=f"HTTP bind host. Defaults to {WebhookSettings.host}.")
    parser.add_argument("--port", type=int, help=f"HTTP bind port. Defaults to {WebhookSettings.port}.")
    parser.add_argument("--path", dest="jira_path", help=f"Jira webhook path. Defaults to {WebhookSettings.jira_path}.")
    parser.add_argument("--config", dest="config_path", help="Sprinter config path. Defaults to config.yaml.")
    parser.add_argument("--webhook-config", help="Webhook settings file. Defaults to webhooks/config.yaml.")
    parser.add_argument("--store-path", help="Filesystem store path. Defaults to <storage.export_path>/.webhooks.")
    parser.add_argument("--log-level", help=f"Python logging level. Defaults to {WebhookSettings.log_level}.")
    parser.add_argument("--no-worker", action="store_true", help="Receive and queue webhooks without processing jobs.")
    return parser.parse_args()


def settings_from_args(args: argparse.Namespace) -> WebhookSettings:
    """Merge CLI overrides into environment-backed settings."""

    env = dict(os.environ)
    if args.host:
        env["SPRINTER_WEBHOOK_HOST"] = args.host
    if args.port:
        env["SPRINTER_WEBHOOK_PORT"] = str(args.port)
    if args.jira_path:
        env["SPRINTER_WEBHOOK_JIRA_PATH"] = args.jira_path
    if args.config_path:
        env["SPRINTER_WEBHOOK_CONFIG"] = args.config_path
    if args.webhook_config:
        env["SPRINTER_WEBHOOK_SETTINGS_FILE"] = args.webhook_config
    if args.store_path:
        env["SPRINTER_WEBHOOK_STORE_PATH"] = args.store_path
    if args.log_level:
        env["SPRINTER_WEBHOOK_LOG_LEVEL"] = args.log_level
    if args.no_worker:
        env["SPRINTER_WEBHOOK_WORKER_ENABLED"] = "false"
    return WebhookSettings.from_env(env)


def main() -> None:
    """Run the webhook server."""

    try:
        settings = settings_from_args(parse_args())
    except WebhookSettingsError as exc:
        raise SystemExit(f"Webhook settings error: {exc}") from exc

    logging.basicConfig(level=getattr(logging, settings.log_level), format="%(asctime)s %(levelname)s %(message)s")
    application = create_webhook_application(settings=settings)
    server = create_webhook_server(application)

    if application.worker:
        application.worker.start()

    logging.info("Sprinter webhook server listening on http://%s:%s%s", settings.host, settings.port, settings.jira_path)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logging.info("Stopping Sprinter webhook server.")
    finally:
        if application.worker:
            application.worker.stop()
        server.server_close()


if __name__ == "__main__":
    main()
