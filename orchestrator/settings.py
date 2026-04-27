from __future__ import annotations
from dataclasses import dataclass
import os
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
    workers: dict[str, WorkerSettings] = None

    @classmethod
    def from_env(cls) -> "OrchestratorSettings":
        repo_root = Path.cwd()
        config_path = repo_root / "orchestrator/config.yaml"
        with config_path.open("r") as f:
            data = yaml.safe_load(f)
        
        orch = data.get("orchestrator", {})
        storage_root = repo_root / orch.get("storage_root", "exports/.orchestrator")
        exports_root = repo_root / orch.get("exports_root", "exports")
        
        worker_data = data.get("workers", {})
        workers = {name: WorkerSettings.from_dict(name, val) for name, val in worker_data.items()}
        
        return cls(
            repo_root=repo_root,
            storage_root=storage_root,
            exports_root=exports_root,
            log_level=orch.get("log_level", "INFO"),
            log_file=repo_root / orch.get("log_file") if orch.get("log_file") else None,
            safety=SafetySettings.from_dict(data.get("safety", {})),
            workers=workers
        )

    def worker(self, name: str) -> WorkerSettings:
        return self.workers[name]
