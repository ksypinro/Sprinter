"""Background worker for webhook-triggered Sprinter exports."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional, Protocol

from JiraStreamableMCP.service import JiraStreamableService
from webhooks.models import WebhookEvent, WebhookJob, utc_now_iso
from webhooks.store import FilesystemWebhookStore
from workers.protocols import Analyzer


class WorkerError(RuntimeError):
    """Raised when a webhook job cannot be processed."""


class ExportService(Protocol):
    """Small protocol for the export service used by the worker."""

    def export_issue(self, ticket_url: str) -> Dict[str, Any]:
        """Export a Jira issue and return summary metadata."""


class WebhookExportService:
    """Adapter from normalized webhook events to Sprinter exports."""

    def __init__(
        self,
        config_path: str = "config.yaml",
        service: Optional[ExportService] = None,
        analysis_service: Optional[Analyzer] = None,
    ):
        """Initialize the export adapter."""

        self.service = service or JiraStreamableService(config_path=config_path)
        self.analysis_service = analysis_service

    def export_event(self, event: WebhookEvent) -> Dict[str, Any]:
        """Export the issue referenced by a webhook event."""

        result = self.service.export_issue(event.issue_url)
        manifest_path = result.get("manifest_path")
        if manifest_path:
            self._augment_manifest(Path(manifest_path), event)
        if self.analysis_service:
            analysis_result = self.analysis_service.analyze_export(event, result)
            result["codex_analysis"] = analysis_result
            if manifest_path:
                self._augment_manifest(Path(manifest_path), event, codex_analysis=analysis_result)
        return result

    def _augment_manifest(
        self,
        manifest_path: Path,
        event: WebhookEvent,
        codex_analysis: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record webhook trigger metadata in the export manifest."""

        try:
            with manifest_path.open("r", encoding="utf-8") as handle:
                manifest = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise WorkerError(f"Could not read export manifest: {manifest_path}") from exc

        manifest["trigger"] = {
            "type": "webhook",
            "provider": event.provider,
            "event_id": event.event_id,
            "event_type": event.event_type,
            "issue_key": event.issue_key,
            "actor": event.actor,
            "received_at": event.received_at,
            "recorded_at": utc_now_iso(),
        }
        if codex_analysis is not None:
            manifest["codex_analysis"] = codex_analysis
        self._atomic_write_json(manifest_path, manifest)

    def _atomic_write_json(self, path: Path, payload: Dict[str, Any]) -> None:
        """Write JSON atomically beside the target manifest."""

        temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temp_path.open("w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, ensure_ascii=False)
                handle.write("\n")
            os.replace(temp_path, path)
        except OSError as exc:
            temp_path.unlink(missing_ok=True)
            raise WorkerError(f"Could not update export manifest: {path}") from exc


class WebhookWorker:
    """Poll a filesystem store and process queued webhook jobs."""

    def __init__(
        self,
        store: FilesystemWebhookStore,
        export_service: WebhookExportService,
        poll_interval_seconds: float = 1.0,
    ):
        """Initialize the worker."""

        self.store = store
        self.export_service = export_service
        self.poll_interval_seconds = poll_interval_seconds
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Start the worker in a background thread."""

        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self.run_forever, name="sprinter-webhook-worker", daemon=True)
        self._thread.start()

    def stop(self, timeout: Optional[float] = 5.0) -> None:
        """Signal the worker to stop and wait briefly for it."""

        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=timeout)

    def run_forever(self) -> None:
        """Process queued jobs until stopped."""

        while not self._stop_event.is_set():
            processed = self.run_once()
            if not processed:
                time.sleep(self.poll_interval_seconds)

    def run_once(self) -> bool:
        """Process one queued job if present."""

        job = self.store.claim_next_job()
        if job is None:
            return False

        try:
            result = self.process_job(job)
            self.store.mark_success(job.job_id, result)
            logging.info("Webhook export job %s completed for %s", job.job_id, job.event.issue_key)
        except Exception as exc:
            logging.exception("Webhook export job %s failed", job.job_id)
            self.store.mark_failed(job.job_id, str(exc))
        return True

    def process_job(self, job: WebhookJob) -> Dict[str, Any]:
        """Run the export for a claimed webhook job."""

        return self.export_service.export_event(job.event)
