"""Environment-backed settings for the Sprinter webhook server."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Mapping, Optional

import yaml


class WebhookSettingsError(ValueError):
    """Raised when webhook server settings are invalid."""


@dataclass(frozen=True)
class WebhookSettings:
    """Runtime settings for the standalone webhook server."""

    DEFAULT_CONFIG_PATH = Path(__file__).with_name("config.yaml")

    DEFAULT_ALLOWED_EVENTS = (
        "jira:issue_created",
        "jira:issue_updated",
        "jira:issue_deleted",
        "comment_created",
        "comment_updated",
        "comment_deleted",
        "worklog_created",
        "worklog_updated",
        "worklog_deleted",
        "attachment_created",
        "attachment_deleted",
        "issuelink_created",
        "issuelink_deleted",
        "issue_property_set",
        "issue_property_deleted",
    )

    host: str = "127.0.0.1"
    port: int = 8090
    jira_path: str = "/webhooks/jira"
    config_path: str = "config.yaml"
    log_level: str = "INFO"
    secret_env: str = "SPRINTER_WEBHOOK_SECRET"
    secret: Optional[str] = None
    secret_header: str = "X-Sprinter-Webhook-Secret"
    allowed_events: tuple[str, ...] = DEFAULT_ALLOWED_EVENTS
    allowed_projects: tuple[str, ...] = ()
    ignored_actors: tuple[str, ...] = ()
    idempotency_ttl_seconds: int = 86400
    store_path: Optional[str] = None
    poll_interval_seconds: float = 1.0
    worker_enabled: bool = True

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "WebhookSettings":
        """Build settings from environment variables.

        Supported variables:
        - ``SPRINTER_WEBHOOK_SETTINGS_FILE``
        - ``SPRINTER_WEBHOOK_HOST``
        - ``SPRINTER_WEBHOOK_PORT``
        - ``SPRINTER_WEBHOOK_JIRA_PATH``
        - ``SPRINTER_WEBHOOK_CONFIG`` or ``SPRINTER_CONFIG``
        - ``SPRINTER_WEBHOOK_LOG_LEVEL``
        - ``SPRINTER_WEBHOOK_SECRET_ENV``
        - ``SPRINTER_WEBHOOK_SECRET`` by default
        - ``SPRINTER_WEBHOOK_SECRET_HEADER``
        - ``SPRINTER_WEBHOOK_ALLOWED_EVENTS``
        - ``SPRINTER_WEBHOOK_ALLOWED_PROJECTS``
        - ``SPRINTER_WEBHOOK_IGNORED_ACTORS``
        - ``SPRINTER_WEBHOOK_IDEMPOTENCY_TTL_SECONDS``
        - ``SPRINTER_WEBHOOK_STORE_PATH``
        - ``SPRINTER_WEBHOOK_POLL_INTERVAL_SECONDS``
        - ``SPRINTER_WEBHOOK_WORKER_ENABLED``
        """

        source = env or os.environ
        webhook_config = cls._load_webhook_config(source.get("SPRINTER_WEBHOOK_SETTINGS_FILE"))
        server_config = cls._section(webhook_config, "server")
        auth_config = cls._section(webhook_config, "auth")
        events_config = cls._section(webhook_config, "events")
        store_config = cls._section(webhook_config, "store")
        worker_config = cls._section(webhook_config, "worker")

        secret_env = source.get("SPRINTER_WEBHOOK_SECRET_ENV", auth_config.get("secret_env", cls.secret_env)).strip()
        secret = source.get(secret_env) or source.get("SPRINTER_WEBHOOK_SECRET") or auth_config.get("secret")
        config_path = (
            source.get("SPRINTER_WEBHOOK_CONFIG")
            or source.get("SPRINTER_CONFIG")
            or server_config.get("config_path")
            or cls.config_path
        )

        try:
            port = int(source.get("SPRINTER_WEBHOOK_PORT", str(server_config.get("port", cls.port))))
        except ValueError as exc:
            raise WebhookSettingsError("SPRINTER_WEBHOOK_PORT must be an integer.") from exc

        try:
            ttl_seconds = int(
                source.get(
                    "SPRINTER_WEBHOOK_IDEMPOTENCY_TTL_SECONDS",
                    str(store_config.get("idempotency_ttl_seconds", cls.idempotency_ttl_seconds)),
                )
            )
        except ValueError as exc:
            raise WebhookSettingsError("SPRINTER_WEBHOOK_IDEMPOTENCY_TTL_SECONDS must be an integer.") from exc

        try:
            poll_interval = float(
                source.get(
                    "SPRINTER_WEBHOOK_POLL_INTERVAL_SECONDS",
                    str(worker_config.get("poll_interval_seconds", cls.poll_interval_seconds)),
                )
            )
        except ValueError as exc:
            raise WebhookSettingsError("SPRINTER_WEBHOOK_POLL_INTERVAL_SECONDS must be numeric.") from exc

        worker_enabled = cls._parse_bool(
            source.get("SPRINTER_WEBHOOK_WORKER_ENABLED"),
            default=bool(worker_config.get("enabled", cls.worker_enabled)),
            field_name="SPRINTER_WEBHOOK_WORKER_ENABLED",
        )

        settings = cls(
            host=source.get("SPRINTER_WEBHOOK_HOST", server_config.get("host", cls.host)).strip(),
            port=port,
            jira_path=source.get("SPRINTER_WEBHOOK_JIRA_PATH", server_config.get("jira_path", cls.jira_path)).strip(),
            config_path=config_path.strip() if config_path else cls.config_path,
            log_level=source.get("SPRINTER_WEBHOOK_LOG_LEVEL", server_config.get("log_level", cls.log_level)).strip().upper(),
            secret_env=secret_env,
            secret=secret.strip() if secret else None,
            secret_header=source.get("SPRINTER_WEBHOOK_SECRET_HEADER", auth_config.get("secret_header", cls.secret_header)).strip(),
            allowed_events=cls._parse_csv(
                source.get("SPRINTER_WEBHOOK_ALLOWED_EVENTS"),
                default=cls._parse_config_sequence(events_config.get("allowed_events"), cls.DEFAULT_ALLOWED_EVENTS),
            ),
            allowed_projects=cls._parse_csv(
                source.get("SPRINTER_WEBHOOK_ALLOWED_PROJECTS"),
                default=cls._parse_config_sequence(events_config.get("allowed_projects"), ()),
            ),
            ignored_actors=cls._parse_csv(
                source.get("SPRINTER_WEBHOOK_IGNORED_ACTORS"),
                default=cls._parse_config_sequence(events_config.get("ignored_actors"), ()),
            ),
            idempotency_ttl_seconds=ttl_seconds,
            store_path=(source.get("SPRINTER_WEBHOOK_STORE_PATH") or store_config.get("store_path") or "").strip() or None,
            poll_interval_seconds=poll_interval,
            worker_enabled=worker_enabled,
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        """Validate settings values after construction."""

        if not self.host:
            raise WebhookSettingsError("SPRINTER_WEBHOOK_HOST must not be empty.")
        if self.port < 1 or self.port > 65535:
            raise WebhookSettingsError("SPRINTER_WEBHOOK_PORT must be between 1 and 65535.")
        if not self.jira_path.startswith("/"):
            raise WebhookSettingsError("SPRINTER_WEBHOOK_JIRA_PATH must start with '/'.")
        if not self.config_path:
            raise WebhookSettingsError("SPRINTER_WEBHOOK_CONFIG must not be empty.")
        if self.log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise WebhookSettingsError("SPRINTER_WEBHOOK_LOG_LEVEL is not a valid Python logging level.")
        if not self.secret_header:
            raise WebhookSettingsError("SPRINTER_WEBHOOK_SECRET_HEADER must not be empty.")
        if self.secret is None:
            raise WebhookSettingsError(f"{self.secret_env} must be set for webhook authentication.")
        if not self.allowed_events:
            raise WebhookSettingsError("SPRINTER_WEBHOOK_ALLOWED_EVENTS must not be empty.")
        if self.idempotency_ttl_seconds < 1:
            raise WebhookSettingsError("SPRINTER_WEBHOOK_IDEMPOTENCY_TTL_SECONDS must be positive.")
        if self.poll_interval_seconds <= 0:
            raise WebhookSettingsError("SPRINTER_WEBHOOK_POLL_INTERVAL_SECONDS must be positive.")

    @staticmethod
    def _parse_bool(value: Optional[str], default: bool, field_name: str) -> bool:
        """Parse environment-friendly boolean strings."""

        if value is None:
            return default
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        raise WebhookSettingsError(f"{field_name} must be a boolean value.")

    @staticmethod
    def _parse_csv(value: Optional[str], default: tuple[str, ...]) -> tuple[str, ...]:
        """Parse a comma-separated environment variable."""

        if value is None:
            return default
        return tuple(item.strip() for item in value.split(",") if item.strip())

    @classmethod
    def _load_webhook_config(cls, path: Optional[str]) -> Mapping[str, object]:
        """Load package-level webhook settings from YAML."""

        config_path = Path(path).expanduser() if path else cls.DEFAULT_CONFIG_PATH
        if not config_path.exists():
            if path:
                raise WebhookSettingsError(f"Webhook settings file not found: {config_path}")
            return {}

        try:
            with config_path.open("r", encoding="utf-8") as handle:
                data = yaml.safe_load(handle) or {}
        except yaml.YAMLError as exc:
            raise WebhookSettingsError(f"Webhook settings file is not valid YAML: {config_path}") from exc
        except OSError as exc:
            raise WebhookSettingsError(f"Could not read webhook settings file: {config_path}") from exc

        if not isinstance(data, dict):
            raise WebhookSettingsError("Webhook settings file must contain a YAML object.")
        return data

    @staticmethod
    def _section(config: Mapping[str, object], name: str) -> Mapping[str, object]:
        """Return a named config section as a mapping."""

        section = config.get(name, {})
        if section is None:
            return {}
        if not isinstance(section, dict):
            raise WebhookSettingsError(f"Webhook config section must be an object: {name}")
        return section

    @staticmethod
    def _parse_config_sequence(value: object, default: tuple[str, ...]) -> tuple[str, ...]:
        """Normalize YAML scalar/list config values into a string tuple."""

        if value is None:
            return default
        if isinstance(value, str):
            return tuple(item.strip() for item in value.split(",") if item.strip())
        if isinstance(value, list):
            return tuple(str(item).strip() for item in value if str(item).strip())
        raise WebhookSettingsError("Webhook config sequence values must be strings or lists.")
