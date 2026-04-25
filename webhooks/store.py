"""Filesystem-backed webhook event and job storage."""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from webhooks.models import JobStatus, WebhookDecision, WebhookEvent, WebhookJob, utc_now_iso


class StoreError(RuntimeError):
    """Raised when webhook state cannot be persisted or loaded."""


class FilesystemWebhookStore:
    """Store webhook events and jobs as JSON files on disk."""

    def __init__(self, root_path: str, ttl_seconds: int = 86400):
        """Initialize a filesystem store.

        Args:
            root_path: Directory where webhook state is stored.
            ttl_seconds: Duplicate event retention window.
        """

        self.root_path = Path(root_path)
        self.ttl_seconds = ttl_seconds
        self.events_dir = self.root_path / "events"
        self.jobs_dir = self.root_path / "jobs"
        self.queued_dir = self.jobs_dir / JobStatus.QUEUED.value
        self.running_dir = self.jobs_dir / JobStatus.RUNNING.value
        self.success_dir = self.jobs_dir / JobStatus.SUCCESS.value
        self.failed_dir = self.jobs_dir / JobStatus.FAILED.value
        self.tmp_dir = self.root_path / "tmp"
        self.lock = threading.Lock()

    def initialize(self) -> None:
        """Create the directory layout required by the store."""

        for directory in (
            self.events_dir,
            self.queued_dir,
            self.running_dir,
            self.success_dir,
            self.failed_dir,
            self.tmp_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)

    def seen_recently(self, event: WebhookEvent) -> bool:
        """Return whether the event has already been recorded within the TTL."""

        path = self.event_path(event)
        if not path.exists():
            return False

        if time.time() - path.stat().st_mtime > self.ttl_seconds:
            path.unlink(missing_ok=True)
            return False

        return True

    def record_event(self, event: WebhookEvent, decision: WebhookDecision) -> bool:
        """Record a received event.

        Returns:
            bool: ``True`` when this is a new event, ``False`` when a fresh
            duplicate already exists.
        """

        self.initialize()
        path = self.event_path(event)
        payload = {
            "event": event.to_dict(),
            "decision": decision.to_dict(),
            "dedupe_key": event.dedupe_key(),
            "recorded_at": utc_now_iso(),
        }

        with self.lock:
            if self.seen_recently(event):
                return False
            try:
                with path.open("x", encoding="utf-8") as handle:
                    json.dump(payload, handle, indent=2, ensure_ascii=False)
                    handle.write("\n")
            except FileExistsError:
                return False
            except OSError as exc:
                raise StoreError(f"Could not record webhook event: {path}") from exc
        return True

    def enqueue_job(self, event: WebhookEvent) -> WebhookJob:
        """Create a queued export job for an accepted event."""

        self.initialize()
        job = WebhookJob(job_id=uuid.uuid4().hex, event=event)
        path = self._job_path(job.job_id, JobStatus.QUEUED)
        with self.lock:
            self._atomic_write_json(path, job.to_dict())
        return job

    def claim_next_job(self) -> Optional[WebhookJob]:
        """Move the oldest queued job into the running state."""

        self.initialize()
        with self.lock:
            for path in self._iter_job_paths(JobStatus.QUEUED):
                running_path = self._job_path(path.stem, JobStatus.RUNNING)
                try:
                    os.replace(path, running_path)
                except FileNotFoundError:
                    continue
                except OSError as exc:
                    raise StoreError(f"Could not claim webhook job: {path}") from exc

                job = self._read_job_at(running_path)
                job.status = JobStatus.RUNNING
                job.started_at = job.started_at or utc_now_iso()
                job.attempts += 1
                self._atomic_write_json(running_path, job.to_dict())
                return job
        return None

    def mark_success(self, job_id: str, result: Dict[str, Any]) -> WebhookJob:
        """Mark a running job as completed successfully."""

        return self._finish_job(job_id, JobStatus.SUCCESS, result=result, error=None)

    def mark_failed(self, job_id: str, error: str) -> WebhookJob:
        """Mark a running job as failed."""

        return self._finish_job(job_id, JobStatus.FAILED, result=None, error=error)

    def cleanup_old_events(self) -> int:
        """Delete stale event records and return the number removed."""

        self.initialize()
        removed = 0
        now = time.time()
        with self.lock:
            for path in self.events_dir.glob("*.json"):
                try:
                    if now - path.stat().st_mtime > self.ttl_seconds:
                        path.unlink()
                        removed += 1
                except FileNotFoundError:
                    continue
        return removed

    def list_jobs(self, status: Optional[JobStatus | str] = None) -> List[WebhookJob]:
        """List stored jobs, optionally filtered by status."""

        self.initialize()
        statuses: Iterable[JobStatus]
        if status is None:
            statuses = (JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.SUCCESS, JobStatus.FAILED)
        else:
            statuses = (self._coerce_status(status),)

        jobs: List[WebhookJob] = []
        for current_status in statuses:
            for path in self._iter_job_paths(current_status):
                jobs.append(self._read_job_at(path))
        return jobs

    def get_job(self, job_id: str) -> WebhookJob:
        """Return a job by id from any lifecycle directory."""

        self.initialize()
        for status in (JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.SUCCESS, JobStatus.FAILED):
            path = self._job_path(job_id, status)
            if path.exists():
                return self._read_job_at(path)
        raise StoreError(f"Webhook job not found: {job_id}")

    def event_path(self, event: WebhookEvent) -> Path:
        """Return the dedupe file path for an event."""

        return self.events_dir / f"{self._event_filename(event)}.json"

    def _finish_job(
        self,
        job_id: str,
        status: JobStatus,
        result: Optional[Dict[str, Any]],
        error: Optional[str],
    ) -> WebhookJob:
        """Move a running job to a terminal status directory."""

        if status not in {JobStatus.SUCCESS, JobStatus.FAILED}:
            raise StoreError(f"Unsupported terminal job status: {status.value}")

        self.initialize()
        with self.lock:
            running_path = self._job_path(job_id, JobStatus.RUNNING)
            if not running_path.exists():
                raise StoreError(f"Running webhook job not found: {job_id}")

            job = self._read_job_at(running_path)
            job.status = status
            job.finished_at = utc_now_iso()
            job.result = result
            job.error = error

            self._atomic_write_json(running_path, job.to_dict())
            final_path = self._job_path(job_id, status)
            try:
                os.replace(running_path, final_path)
            except OSError as exc:
                raise StoreError(f"Could not finish webhook job: {job_id}") from exc
            return job

    def _atomic_write_json(self, path: Path, payload: Dict[str, Any]) -> None:
        """Write JSON through a temporary file and atomically replace target."""

        path.parent.mkdir(parents=True, exist_ok=True)
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        temp_path = self.tmp_dir / f"{uuid.uuid4().hex}.json"
        try:
            with temp_path.open("w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, ensure_ascii=False)
                handle.write("\n")
            os.replace(temp_path, path)
        except OSError as exc:
            temp_path.unlink(missing_ok=True)
            raise StoreError(f"Could not write webhook store file: {path}") from exc

    def _read_job_at(self, path: Path) -> WebhookJob:
        """Read a job file and convert JSON errors into store errors."""

        try:
            with path.open("r", encoding="utf-8") as handle:
                return WebhookJob.from_dict(json.load(handle))
        except (OSError, json.JSONDecodeError, KeyError, ValueError) as exc:
            raise StoreError(f"Could not read webhook job: {path}") from exc

    def _iter_job_paths(self, status: JobStatus) -> List[Path]:
        """Return job paths sorted by modification time and name."""

        directory = self._job_dir(status)
        return sorted(directory.glob("*.json"), key=lambda path: (path.stat().st_mtime, path.name))

    def _job_path(self, job_id: str, status: JobStatus) -> Path:
        """Return a job file path for a status."""

        return self._job_dir(status) / f"{job_id}.json"

    def _job_dir(self, status: JobStatus) -> Path:
        """Return the directory for a status."""

        if status == JobStatus.QUEUED:
            return self.queued_dir
        if status == JobStatus.RUNNING:
            return self.running_dir
        if status == JobStatus.SUCCESS:
            return self.success_dir
        if status == JobStatus.FAILED:
            return self.failed_dir
        raise StoreError(f"Unsupported job status: {status.value}")

    def _event_filename(self, event: WebhookEvent) -> str:
        """Hash the dedupe key into a filesystem-safe filename."""

        import hashlib

        return hashlib.sha256(event.dedupe_key().encode("utf-8")).hexdigest()

    def _coerce_status(self, status: JobStatus | str) -> JobStatus:
        """Normalize a status argument."""

        if isinstance(status, JobStatus):
            return status
        return JobStatus(status)
