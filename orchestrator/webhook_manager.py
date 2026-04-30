"""Lifecycle manager for orchestrator-owned webhook HTTP servers."""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from github_service.settings import GitHubSettings
from github_webhooks.app import create_github_webhook_application, create_github_webhook_server
from orchestrator.settings import (
    GitHubWebhookServerSettings,
    JiraWebhookServerSettings,
    OrchestratorSettings,
)
from webhooks.app import create_webhook_application, create_webhook_server
from webhooks.settings import WebhookSettings

logger = logging.getLogger(__name__)


@dataclass
class ManagedWebhookServer:
    name: str
    server: Any
    worker: Optional[Any] = None
    thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        if self.worker:
            self.worker.start()
        self.thread = threading.Thread(target=self.server.serve_forever, name=f"sprinter-{self.name}-webhook", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        if self.worker:
            self.worker.stop()
        self.server.shutdown()
        if self.thread:
            self.thread.join(timeout=5)
        self.server.server_close()

    def endpoint(self) -> dict[str, Any]:
        host, port = self.server.server_address[:2]
        return {"name": self.name, "host": host, "port": port}


class WebhookServerManager:
    """Owns Jira and GitHub webhook servers for the orchestrator process."""

    def __init__(self, settings: OrchestratorSettings, orchestrator: Any):
        self.settings = settings
        self.orchestrator = orchestrator
        self._servers: dict[str, ManagedWebhookServer] = {}

    def start(self) -> None:
        if self._servers:
            return
        try:
            if self.settings.webhook_servers.jira.enabled:
                self._start_jira(self.settings.webhook_servers.jira)
            if self.settings.webhook_servers.github.enabled:
                self._start_github(self.settings.webhook_servers.github)
        except Exception:
            self.stop()
            raise

    def stop(self) -> None:
        for server in reversed(list(self._servers.values())):
            try:
                server.stop()
            except Exception:
                logger.exception("Failed to stop %s webhook server", server.name)
        self._servers.clear()

    def endpoints(self) -> dict[str, dict[str, Any]]:
        return {name: server.endpoint() for name, server in self._servers.items()}

    def _start_jira(self, settings: JiraWebhookServerSettings) -> None:
        env = dict(os.environ)
        env["SPRINTER_WEBHOOK_HOST"] = settings.host
        env["SPRINTER_WEBHOOK_PORT"] = str(settings.port)
        env["SPRINTER_WEBHOOK_JIRA_PATH"] = settings.path
        env["SPRINTER_WEBHOOK_CONFIG"] = settings.config_path
        env["SPRINTER_WEBHOOK_USE_ORCHESTRATOR"] = "true"
        if settings.settings_file:
            env["SPRINTER_WEBHOOK_SETTINGS_FILE"] = settings.settings_file
        if settings.store_path:
            env["SPRINTER_WEBHOOK_STORE_PATH"] = _resolve_path(self.settings.repo_root, settings.store_path)

        webhook_settings = WebhookSettings.from_env(env)
        app = create_webhook_application(settings=webhook_settings, orchestrator=self.orchestrator)
        server = create_webhook_server(app)
        managed = ManagedWebhookServer("jira", server, app.worker)
        managed.start()
        self._servers["jira"] = managed
        host, port = managed.server.server_address[:2]
        logger.info("Jira webhook server listening on http://%s:%s%s", host, port, webhook_settings.jira_path)

    def _start_github(self, settings: GitHubWebhookServerSettings) -> None:
        store_path = Path(_resolve_path(self.settings.repo_root, settings.store_path))
        app = create_github_webhook_application(GitHubSettings.from_env(), self.orchestrator, store_path)
        server = create_github_webhook_server(app, settings.host, settings.port, settings.path)
        managed = ManagedWebhookServer("github", server)
        managed.start()
        self._servers["github"] = managed
        host, port = managed.server.server_address[:2]
        logger.info("GitHub webhook server listening on http://%s:%s%s", host, port, settings.path)


def _resolve_path(repo_root: Path, value: str) -> str:
    path = Path(value).expanduser()
    if path.is_absolute():
        return str(path)
    return str(repo_root / path)
