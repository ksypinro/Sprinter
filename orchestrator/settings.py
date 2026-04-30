from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional
import yaml

@dataclass(frozen=True)
class WorkerSettings:
    name: str
    enabled: bool = True
    instances: int = 1
    timeout_seconds: int = 300
    max_attempts: int = 3
    command: str = ".venv/bin/python"
    args: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, name: str, data: Mapping[str, Any]) -> "WorkerSettings":
        args = data.get("args", ())
        if isinstance(args, str): args = (args,)
        return cls(
            name=name,
            enabled=data.get("enabled", True),
            instances=int(data.get("instances", 1)),
            timeout_seconds=int(data.get("timeout_seconds", 300)),
            max_attempts=int(data.get("max_attempts", 3)),
            command=str(data.get("command", ".venv/bin/python")),
            args=tuple(args),
        )

@dataclass(frozen=True)
class SafetySettings:
    auto_export_after_issue_created: bool = True
    auto_analyze_after_export: bool = True
    auto_execute_after_plan: bool = False
    auto_create_pr_after_execution: bool = False
    auto_review_after_pr: bool = False

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SafetySettings":
        return cls(**{k: v for k, v in data.items() if hasattr(cls, k)})

@dataclass(frozen=True)
class JiraWebhookServerSettings:
    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = 8090
    path: str = "/webhooks/jira"
    config_path: str = "config.yaml"
    settings_file: Optional[str] = None
    store_path: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "JiraWebhookServerSettings":
        return cls(
            enabled=_parse_bool(data.get("enabled"), cls.enabled),
            host=str(data.get("host", cls.host)),
            port=int(data.get("port", cls.port)),
            path=str(data.get("path", cls.path)),
            config_path=str(data.get("config_path", cls.config_path)),
            settings_file=_optional_str(data.get("settings_file")),
            store_path=_optional_str(data.get("store_path")),
        )

@dataclass(frozen=True)
class GitHubWebhookServerSettings:
    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = 8091
    path: str = "/webhooks/github"
    store_path: str = "exports/.github_webhooks"

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "GitHubWebhookServerSettings":
        return cls(
            enabled=_parse_bool(data.get("enabled"), cls.enabled),
            host=str(data.get("host", cls.host)),
            port=int(data.get("port", cls.port)),
            path=str(data.get("path", cls.path)),
            store_path=str(data.get("store_path", cls.store_path)),
        )

@dataclass(frozen=True)
class WebhookServerSettings:
    auto_start: bool = True
    jira: JiraWebhookServerSettings = JiraWebhookServerSettings()
    github: GitHubWebhookServerSettings = GitHubWebhookServerSettings()

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "WebhookServerSettings":
        return cls(
            auto_start=_parse_bool(data.get("auto_start"), cls.auto_start),
            jira=JiraWebhookServerSettings.from_dict(_section(data, "jira")),
            github=GitHubWebhookServerSettings.from_dict(_section(data, "github")),
        )

@dataclass(frozen=True)
class OrchestratorSettings:
    repo_root: Path
    storage_root: Path
    exports_root: Path
    event_poll_interval_seconds: float = 1.0
    command_poll_interval_seconds: float = 1.0
    worker_monitor_interval_seconds: float = 5.0
    default_max_attempts: int = 3
    default_retry_backoff_seconds: tuple[int, ...] = (10, 30, 90)
    log_level: str = "INFO"
    log_file: Optional[Path] = None
    safety: SafetySettings = SafetySettings()
    workers: dict[str, WorkerSettings] = field(default_factory=dict)
    webhook_servers: WebhookServerSettings = WebhookServerSettings()

    @classmethod
    def from_env(cls) -> "OrchestratorSettings":
        repo_root = Path.cwd()
        config_path = repo_root / "orchestrator/config.yaml"
        with config_path.open("r") as f:
            data = yaml.safe_load(f) or {}
        
        orch = data.get("orchestrator", {})
        storage_root = repo_root / orch.get("storage_root", "exports/.orchestrator")
        exports_root = repo_root / orch.get("exports_root", "exports")
        
        worker_data = data.get("workers", {})
        workers = {name: WorkerSettings.from_dict(name, val) for name, val in worker_data.items()}
        webhook_data = data.get("webhook_servers", {})
        
        return cls(
            repo_root=repo_root,
            storage_root=storage_root,
            exports_root=exports_root,
            event_poll_interval_seconds=float(orch.get("event_poll_interval_seconds", 1.0)),
            command_poll_interval_seconds=float(orch.get("command_poll_interval_seconds", 1.0)),
            worker_monitor_interval_seconds=float(orch.get("worker_monitor_interval_seconds", 5.0)),
            default_max_attempts=int(orch.get("default_max_attempts", 3)),
            default_retry_backoff_seconds=tuple(
                int(v) for v in orch.get("default_retry_backoff_seconds", (10, 30, 90))
            ),
            log_level=orch.get("log_level", "INFO"),
            log_file=repo_root / orch.get("log_file") if orch.get("log_file") else None,
            safety=SafetySettings.from_dict(data.get("safety", {})),
            workers=workers,
            webhook_servers=WebhookServerSettings.from_dict(webhook_data),
        )

    def worker(self, name: str) -> WorkerSettings:
        return self.workers[name]


def _section(data: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    value = data.get(name, {})
    return value if isinstance(value, Mapping) else {}


def _optional_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default
