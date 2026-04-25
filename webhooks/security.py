"""Webhook request verification helpers."""

from __future__ import annotations

import hashlib
import hmac
from typing import Mapping, Optional


class WebhookAuthError(PermissionError):
    """Raised when a webhook request cannot be authenticated."""


class SecretVerifier:
    """Validate webhooks with local shared-secret or Jira HMAC headers."""

    def __init__(
        self,
        secret: Optional[str],
        header_name: str = "X-Sprinter-Webhook-Secret",
        signature_header_name: str = "X-Hub-Signature",
    ):
        """Initialize the verifier.

        Args:
            secret: Expected shared secret. ``None`` means verification cannot
                succeed because webhook authentication is mandatory.
            header_name: Request header that carries a local shared secret.
            signature_header_name: Jira header that carries the HMAC signature.
        """

        self.secret = secret
        self.header_name = header_name
        self.signature_header_name = signature_header_name

    def verify(self, headers: Mapping[str, str], body: bytes = b"") -> None:
        """Validate the configured secret against request headers."""

        if not self.secret:
            raise WebhookAuthError("Webhook secret is not configured.")

        candidate = self._get_header(headers, self.header_name)
        if candidate:
            if hmac.compare_digest(candidate, self.secret):
                return
            raise WebhookAuthError("Invalid webhook secret.")

        signature = self._get_header(headers, self.signature_header_name)
        if signature:
            self._verify_hmac_signature(signature, body)
            return

        raise WebhookAuthError(f"Missing webhook authentication header: {self.header_name} or {self.signature_header_name}")

    def _verify_hmac_signature(self, signature_header: str, body: bytes) -> None:
        """Validate Jira's X-Hub-Signature header against the raw body."""

        try:
            method, signature = signature_header.split("=", 1)
        except ValueError as exc:
            raise WebhookAuthError("Invalid webhook signature format.") from exc

        method = method.strip().lower()
        signature = signature.strip()
        digest_constructor = getattr(hashlib, method, None)
        if digest_constructor is None or method.startswith("shake_"):
            raise WebhookAuthError(f"Unsupported webhook signature method: {method}")

        expected_signature = hmac.new(
            self.secret.encode("utf-8"),
            msg=body,
            digestmod=digest_constructor,
        ).hexdigest()

        if not hmac.compare_digest(f"{method}={expected_signature}", f"{method}={signature}"):
            raise WebhookAuthError("Invalid webhook signature.")

    @staticmethod
    def _get_header(headers: Mapping[str, str], header_name: str) -> Optional[str]:
        """Return a header value using case-insensitive lookup."""

        lowered = header_name.lower()
        for key, value in headers.items():
            if key.lower() == lowered:
                return value
        return None


def redact_secret(value: Optional[str]) -> str:
    """Return a safe diagnostic representation of a secret value."""

    if not value:
        return "<unset>"
    if len(value) <= 4:
        return "****"
    return f"{value[:2]}****{value[-2:]}"
