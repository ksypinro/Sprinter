"""Command-line entrypoint for the GitHub webhook server."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from github_service.settings import GitHubSettings
from github_webhooks.app import create_github_webhook_application, create_github_webhook_server
from orchestrator.logging_utils import setup_logging
from orchestrator.service import OrchestratorService
from orchestrator.settings import OrchestratorSettings


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Sprinter GitHub webhook server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8091)
    parser.add_argument("--path", default="/webhooks/github")
    parser.add_argument("--store-path", default="exports/.github_webhooks")
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument("--log-file", default="exports/.github_webhooks/webhook-server.log")
    args = parser.parse_args()

    logging_manager = setup_logging(args.log_level, args.log_file, console=True)
    orchestrator = None
    server = None
    try:
        orchestrator = OrchestratorService(OrchestratorSettings.from_env())
        orchestrator.initialize(start_webhooks=False)
        app = create_github_webhook_application(GitHubSettings.from_env(), orchestrator, Path(args.store_path))
        server = create_github_webhook_server(app, args.host, args.port, args.path)
        logging.info("GitHub webhook server listening on http://%s:%s%s", args.host, args.port, args.path)
        server.serve_forever()
    except KeyboardInterrupt:
        logging.info("Stopping GitHub webhook server.")
    finally:
        if server:
            server.server_close()
        if orchestrator:
            orchestrator.shutdown()
        logging_manager.close()


if __name__ == "__main__":
    main()
