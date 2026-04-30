"""Filesystem dedupe store for GitHub webhooks."""

from __future__ import annotations

import json
import time
from pathlib import Path


class GitHubWebhookStore:
    def __init__(self, root: Path, ttl_seconds: int = 86400):
        self.root = root
        self.ttl_seconds = ttl_seconds
        self.deliveries = root / "deliveries"

    def record_delivery(self, delivery_id: str, payload: dict) -> bool:
        self.deliveries.mkdir(parents=True, exist_ok=True)
        path = self.deliveries / f"{delivery_id}.json"
        if path.exists():
            if time.time() - path.stat().st_mtime <= self.ttl_seconds:
                return False
            path.unlink()
        with path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        return True
