"""Dependency-free GitHub webhook app and HTTP server."""

from __future__ import annotations

import json
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping

from github_service.settings import GitHubSettings, GitHubSettingsError
from github_webhooks.parser import GitHubWebhookParser
from github_webhooks.security import GitHubWebhookAuthError, verify_signature
from github_webhooks.store import GitHubWebhookStore
from orchestrator.service import OrchestratorService


@dataclass(frozen=True)
class GitHubWebhookResponse:
    status_code: int
    body: dict[str, Any]


class GitHubWebhookApplication:
    def __init__(self, settings: GitHubSettings, store: GitHubWebhookStore, parser: GitHubWebhookParser, orchestrator: OrchestratorService):
        self.settings = settings
        self.store = store
        self.parser = parser
        self.orchestrator = orchestrator

    def handle(self, headers: Mapping[str, str], body: bytes) -> GitHubWebhookResponse:
        try:
            self.settings.require_webhook()
            verify_signature(self.settings.webhook_secret or "", headers, body)
        except GitHubSettingsError as exc:
            return GitHubWebhookResponse(500, {"status": "error", "message": str(exc)})
        except GitHubWebhookAuthError as exc:
            return GitHubWebhookResponse(401, {"status": "error", "message": str(exc)})

        delivery_id = _get_header(headers, "X-GitHub-Delivery")
        event_name = _get_header(headers, "X-GitHub-Event")
        if not delivery_id or not event_name:
            return GitHubWebhookResponse(400, {"status": "error", "message": "Missing GitHub delivery or event header."})

        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            return GitHubWebhookResponse(400, {"status": "error", "message": str(exc)})

        if not self.store.record_delivery(delivery_id, payload):
            return GitHubWebhookResponse(202, {"status": "duplicate", "delivery_id": delivery_id})

        event = self.parser.parse(event_name, payload)
        if not event:
            return GitHubWebhookResponse(202, {"status": "ignored", "delivery_id": delivery_id})

        event_id = self.orchestrator.submit_event(event)
        return GitHubWebhookResponse(202, {"status": "accepted", "event_id": event_id, "workflow_id": event.workflow_id})


def create_github_webhook_application(settings: GitHubSettings, orchestrator: OrchestratorService, storage_root: Path) -> GitHubWebhookApplication:
    return GitHubWebhookApplication(
        settings=settings,
        store=GitHubWebhookStore(storage_root),
        parser=GitHubWebhookParser(settings.base_branch),
        orchestrator=orchestrator,
    )


def create_github_webhook_server(application: GitHubWebhookApplication, host: str = "127.0.0.1", port: int = 8091, path: str = "/webhooks/github") -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            if self.path != path:
                self._send(GitHubWebhookResponse(404, {"status": "error", "message": "not found"}))
                return
            length = int(self.headers.get("Content-Length", "0"))
            self._send(application.handle(dict(self.headers.items()), self.rfile.read(length)))

        def do_GET(self) -> None:
            if self.path == "/ready":
                self._send(GitHubWebhookResponse(200, {"status": "ready"}))
                return
            self._send(GitHubWebhookResponse(404, {"status": "error", "message": "not found"}))

        def log_message(self, format: str, *args: object) -> None:
            return

        def _send(self, response: GitHubWebhookResponse) -> None:
            payload = json.dumps(response.body).encode("utf-8")
            self.send_response(response.status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    return ThreadingHTTPServer((host, port), Handler)


def _get_header(headers: Mapping[str, str], name: str) -> str:
    lowered = name.lower()
    for key, value in headers.items():
        if key.lower() == lowered:
            return value
    return ""
