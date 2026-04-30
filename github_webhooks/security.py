"""GitHub webhook signature verification."""

from __future__ import annotations

import hashlib
import hmac
from typing import Mapping


class GitHubWebhookAuthError(PermissionError):
    """Raised when GitHub webhook authentication fails."""


def verify_signature(secret: str, headers: Mapping[str, str], body: bytes) -> None:
    signature = _get_header(headers, "X-Hub-Signature-256")
    if not secret:
        raise GitHubWebhookAuthError("GitHub webhook secret is not configured.")
    if not signature or not signature.startswith("sha256="):
        raise GitHubWebhookAuthError("Missing or invalid GitHub webhook signature.")
    expected = "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise GitHubWebhookAuthError("Invalid GitHub webhook signature.")


def _get_header(headers: Mapping[str, str], name: str) -> str:
    lowered = name.lower()
    for key, value in headers.items():
        if key.lower() == lowered:
            return value
    return ""
