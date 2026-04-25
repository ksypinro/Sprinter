"""Standard-library HTTP app for receiving Sprinter webhooks."""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Mapping, Optional
from urllib.parse import urlparse

from main import load_config
from webhooks.models import WebhookParseError
from webhooks.parser import JiraWebhookParser
from webhooks.security import SecretVerifier, WebhookAuthError
from webhooks.settings import WebhookSettings
from webhooks.store import FilesystemWebhookStore, StoreError
from webhooks.worker import ExportService, WebhookExportService, WebhookWorker


RECORD_ONLY_EVENTS = {"jira:issue_deleted"}


@dataclass(frozen=True)
class WebhookResponse:
    """HTTP response produced by the testable webhook application core."""

    status_code: int
    body: Dict[str, Any]


class WebhookApplication:
    """Testable webhook request coordinator."""

    def __init__(
        self,
        settings: WebhookSettings,
        verifier: SecretVerifier,
        parser: JiraWebhookParser,
        store: FilesystemWebhookStore,
        worker: Optional[WebhookWorker] = None,
    ):
        """Initialize the application dependencies."""

        self.settings = settings
        self.verifier = verifier
        self.parser = parser
        self.store = store
        self.worker = worker

    def handle_jira_webhook(self, headers: Mapping[str, str], body: bytes) -> WebhookResponse:
        """Receive, validate, deduplicate, and enqueue a Jira webhook."""

        try:
            self.verifier.verify(headers, body)
        except WebhookAuthError as exc:
            return WebhookResponse(401, {"status": "unauthorized", "error": str(exc)})

        try:
            payload = json.loads(body.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            return WebhookResponse(400, {"status": "bad_request", "error": f"Invalid JSON payload: {exc}"})

        try:
            event = self.parser.parse(payload)
            decision = self.parser.decide(event)
        except WebhookParseError as exc:
            return WebhookResponse(400, {"status": "bad_request", "error": str(exc)})

        try:
            is_new = self.store.record_event(event, decision)
            if not is_new:
                return WebhookResponse(
                    202,
                    {
                        "status": "duplicate",
                        "issue_key": event.issue_key,
                        "event_id": event.event_id,
                    },
                )

            if not decision.accepted:
                return WebhookResponse(
                    202,
                    {
                        "status": "ignored",
                        "issue_key": event.issue_key,
                        "event_id": event.event_id,
                        "reason": decision.reason,
                    },
                )

            if event.event_type in RECORD_ONLY_EVENTS:
                return WebhookResponse(
                    202,
                    {
                        "status": "recorded",
                        "issue_key": event.issue_key,
                        "event_id": event.event_id,
                        "event_type": event.event_type,
                        "reason": "Issue deletion was recorded; export skipped because deleted issues may no longer be readable.",
                    },
                )

            job = self.store.enqueue_job(event)
        except StoreError as exc:
            logging.exception("Webhook store operation failed")
            return WebhookResponse(500, {"status": "store_error", "error": str(exc)})

        return WebhookResponse(
            202,
            {
                "status": "accepted",
                "job_id": job.job_id,
                "issue_key": event.issue_key,
                "event_id": event.event_id,
            },
        )

    def health(self) -> WebhookResponse:
        """Return process liveness details."""

        return WebhookResponse(200, {"status": "ok", "service": "sprinter-webhooks"})

    def ready(self) -> WebhookResponse:
        """Return readiness details."""

        try:
            self.store.initialize()
        except StoreError as exc:
            return WebhookResponse(500, {"status": "not_ready", "error": str(exc)})
        return WebhookResponse(200, {"status": "ready", "worker_enabled": self.settings.worker_enabled})

    def get_job(self, job_id: str) -> WebhookResponse:
        """Return stored job details for diagnostics."""

        try:
            job = self.store.get_job(job_id)
        except StoreError as exc:
            return WebhookResponse(404, {"status": "not_found", "error": str(exc)})
        return WebhookResponse(200, {"status": "ok", "job": job.to_dict()})


class WebhookHTTPServer(ThreadingHTTPServer):
    """Threading HTTP server carrying a webhook application instance."""

    def __init__(self, server_address, request_handler_class, application: WebhookApplication):
        """Initialize the HTTP server with an application dependency."""

        self.webhook_application = application
        super().__init__(server_address, request_handler_class)


class WebhookRequestHandler(BaseHTTPRequestHandler):
    """HTTP request adapter for the webhook application."""

    server: WebhookHTTPServer

    def do_GET(self) -> None:
        """Handle health, readiness, and job diagnostic routes."""

        path = urlparse(self.path).path
        if path == "/health":
            self._send_json(self.server.webhook_application.health())
            return
        if path == "/ready":
            self._send_json(self.server.webhook_application.ready())
            return
        if path.startswith("/jobs/"):
            job_id = path.removeprefix("/jobs/").strip("/")
            self._send_json(self.server.webhook_application.get_job(job_id))
            return
        self._send_json(WebhookResponse(404, {"status": "not_found"}))

    def do_POST(self) -> None:
        """Handle Jira webhook delivery."""

        path = urlparse(self.path).path
        application = self.server.webhook_application
        if path != application.settings.jira_path:
            self._send_json(WebhookResponse(404, {"status": "not_found"}))
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(content_length)
        response = application.handle_jira_webhook(dict(self.headers.items()), body)
        self._send_json(response)

    def log_message(self, format: str, *args) -> None:
        """Route HTTP server access logs through Python logging."""

        logging.info("%s - %s", self.address_string(), format % args)

    def _send_json(self, response: WebhookResponse) -> None:
        """Serialize and send a JSON response."""

        payload = json.dumps(response.body, indent=2, ensure_ascii=False).encode("utf-8")
        self.send_response(response.status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def create_webhook_application(
    settings: Optional[WebhookSettings] = None,
    store: Optional[FilesystemWebhookStore] = None,
    worker: Optional[WebhookWorker] = None,
    export_service: Optional[ExportService] = None,
) -> WebhookApplication:
    """Create a fully wired webhook application."""

    resolved_settings = settings or WebhookSettings.from_env()
    config = load_config(resolved_settings.config_path)
    store_path = resolved_settings.store_path or os.path.join(config["storage"]["export_path"], ".webhooks")
    resolved_store = store or FilesystemWebhookStore(store_path, ttl_seconds=resolved_settings.idempotency_ttl_seconds)
    resolved_store.initialize()

    parser = JiraWebhookParser(
        jira_base_url=config["jira"]["base_url"],
        allowed_events=resolved_settings.allowed_events,
        allowed_projects=resolved_settings.allowed_projects,
        ignored_actors=resolved_settings.ignored_actors,
    )
    verifier = SecretVerifier(resolved_settings.secret, resolved_settings.secret_header)
    resolved_worker = worker
    if resolved_worker is None and resolved_settings.worker_enabled:
        adapter = WebhookExportService(config_path=resolved_settings.config_path, service=export_service)
        resolved_worker = WebhookWorker(
            resolved_store,
            adapter,
            poll_interval_seconds=resolved_settings.poll_interval_seconds,
        )

    return WebhookApplication(
        settings=resolved_settings,
        verifier=verifier,
        parser=parser,
        store=resolved_store,
        worker=resolved_worker,
    )


def create_webhook_server(application: WebhookApplication) -> WebhookHTTPServer:
    """Create the stdlib HTTP server for a webhook application."""

    address = (application.settings.host, application.settings.port)
    return WebhookHTTPServer(address, WebhookRequestHandler, application)
