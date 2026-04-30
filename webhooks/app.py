"""Dependency-free webhook application core and HTTP adapter."""

from __future__ import annotations

import json
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping, Optional, Protocol

from main import load_config
from webhooks.models import WebhookParseError
from webhooks.parser import JiraWebhookParser
from webhooks.security import SecretVerifier, WebhookAuthError
from webhooks.settings import WebhookSettings
from webhooks.store import FilesystemWebhookStore
from webhooks.worker import WebhookExportService, WebhookWorker


class OrchestratorWebhookSink(Protocol):
    """Small orchestrator surface used by Jira webhooks."""

    def submit_jira_webhook(self, event: Any) -> str:
        """Submit a normalized Jira webhook event to the orchestrator."""


@dataclass(frozen=True)
class WebhookResponse:
    """Small response object used by tests and the HTTP adapter."""

    status_code: int
    body: dict[str, Any]


class WebhookApplication:
    """Testable application core for Jira webhook requests."""

    def __init__(
        self,
        settings: WebhookSettings,
        verifier: SecretVerifier,
        parser: JiraWebhookParser,
        store: FilesystemWebhookStore,
        worker: Optional[WebhookWorker] = None,
        orchestrator: Optional[OrchestratorWebhookSink] = None,
    ):
        """Initialize the application core."""

        self.settings = settings
        self.verifier = verifier
        self.parser = parser
        self.store = store
        self.worker = worker
        self.orchestrator = orchestrator

    def handle_jira_webhook(self, headers: Mapping[str, str], body: bytes) -> WebhookResponse:
        """Authenticate, parse, record, and optionally enqueue one webhook."""

        try:
            self.verifier.verify(headers, body)
        except WebhookAuthError as exc:
            return WebhookResponse(401, {"status": "error", "message": str(exc)})

        try:
            payload = json.loads(body.decode("utf-8"))
            event = self.parser.parse(payload)
            decision = self.parser.decide(event)
        except (UnicodeDecodeError, json.JSONDecodeError, WebhookParseError) as exc:
            return WebhookResponse(400, {"status": "error", "message": str(exc)})

        is_new = self.store.record_event(event, decision)
        if not is_new:
            return WebhookResponse(202, {"status": "duplicate", "event_id": event.event_id})

        if not decision.accepted:
            return WebhookResponse(202, {"status": "ignored", "reason": decision.reason, "event_id": event.event_id})

        if event.event_type == "jira:issue_deleted":
            return WebhookResponse(202, {"status": "recorded", "event_id": event.event_id})

        if self.orchestrator:
            orchestrator_event_id = self.orchestrator.submit_jira_webhook(event)
            return WebhookResponse(
                202,
                {
                    "status": "accepted",
                    "event_id": event.event_id,
                    "workflow_id": event.issue_key,
                    "orchestrator_event_id": orchestrator_event_id,
                },
            )

        job = self.store.enqueue_job(event)
        return WebhookResponse(202, {"status": "accepted", "event_id": event.event_id, "job_id": job.job_id})


def create_webhook_application(
    settings: Optional[WebhookSettings] = None,
    orchestrator: Optional[OrchestratorWebhookSink] = None,
) -> WebhookApplication:
    """Create a configured webhook application."""

    settings = settings or WebhookSettings.from_env()
    config = load_config(settings.config_path)
    jira_base_url = config["jira"]["base_url"]
    store_path = settings.store_path or str(Path(config["storage"]["export_path"]) / ".webhooks")

    store = FilesystemWebhookStore(store_path, ttl_seconds=settings.idempotency_ttl_seconds)
    verifier = SecretVerifier(settings.secret, settings.secret_header)
    parser = JiraWebhookParser(
        jira_base_url,
        settings.allowed_events,
        allowed_projects=settings.allowed_projects,
        ignored_actors=settings.ignored_actors,
    )

    worker = None
    if settings.worker_enabled and not (settings.use_orchestrator and orchestrator):
        export_service = WebhookExportService(config_path=settings.config_path)
        worker = WebhookWorker(store, export_service, settings.poll_interval_seconds)

    return WebhookApplication(
        settings=settings,
        verifier=verifier,
        parser=parser,
        store=store,
        worker=worker,
        orchestrator=orchestrator if settings.use_orchestrator else None,
    )


def create_webhook_server(application: WebhookApplication) -> ThreadingHTTPServer:
    """Create a basic JSON HTTP server for the webhook app."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/ready":
                self._send_json(WebhookResponse(200, {"status": "ready"}))
                return
            self._send_json(WebhookResponse(404, {"status": "error", "message": "not found"}))

        def do_POST(self) -> None:
            if self.path != application.settings.jira_path:
                self._send_json(WebhookResponse(404, {"status": "error", "message": "not found"}))
                return

            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self._send_json(WebhookResponse(400, {"status": "error", "message": "invalid content length"}))
                return

            response = application.handle_jira_webhook(dict(self.headers.items()), self.rfile.read(length))
            self._send_json(response)

        def log_message(self, format: str, *args: object) -> None:
            return

        def _send_json(self, response: WebhookResponse) -> None:
            payload = json.dumps(response.body).encode("utf-8")
            self.send_response(response.status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    return ThreadingHTTPServer((application.settings.host, application.settings.port), Handler)
