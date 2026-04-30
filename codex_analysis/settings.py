"""Settings for Codex analysis runs."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional

import yaml


class CodexAnalysisSettingsError(ValueError):
    """Raised when Codex analysis settings are invalid."""


@dataclass(frozen=True)
class CodexAnalysisSettings:
    """Runtime settings for analysis-only Codex executions."""

    DEFAULT_CONFIG_PATH = Path(__file__).with_name("config.yaml")

    enabled: bool = True
    output_dir_name: str = "codex_analysis"
    prompt_file_name: str = "codex_prompt.md"
    analysis_file_name: str = "analysis_and_plan.md"
    log_file_name: str = "codex_output.log"
    result_file_name: str = "analysis_result.json"
    command: str = "codex"
    sandbox: str = "read-only"
    json_output: bool = True
    timeout_seconds: int = 600
    model: Optional[str] = None
    profile: Optional[str] = None
    repo_root: Optional[str] = None

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "CodexAnalysisSettings":
        """Build settings from YAML and environment overrides."""

        source = env or os.environ
        config = cls._load_config(source.get("SPRINTER_CODEX_ANALYSIS_SETTINGS_FILE"))
        analysis_config = cls._section(config, "codex_analysis")
        codex_config = cls._section(config, "codex")

        timeout_value = source.get(
            "SPRINTER_CODEX_ANALYSIS_TIMEOUT_SECONDS",
            str(codex_config.get("timeout_seconds", cls.timeout_seconds)),
        )
        try:
            timeout_seconds = int(timeout_value)
        except ValueError as exc:
            raise CodexAnalysisSettingsError("SPRINTER_CODEX_ANALYSIS_TIMEOUT_SECONDS must be an integer.") from exc

        settings = cls(
            enabled=cls._parse_bool(
                source.get("SPRINTER_CODEX_ANALYSIS_ENABLED"),
                default=bool(analysis_config.get("enabled", cls.enabled)),
                field_name="SPRINTER_CODEX_ANALYSIS_ENABLED",
            ),
            output_dir_name=str(
                source.get("SPRINTER_CODEX_ANALYSIS_OUTPUT_DIR")
                or analysis_config.get("output_dir_name", cls.output_dir_name)
            ),
            prompt_file_name=str(
                source.get("SPRINTER_CODEX_ANALYSIS_PROMPT_FILE")
                or analysis_config.get("prompt_file_name", cls.prompt_file_name)
            ),
            analysis_file_name=str(
                source.get("SPRINTER_CODEX_ANALYSIS_FILE")
                or analysis_config.get("analysis_file_name", cls.analysis_file_name)
            ),
            log_file_name=str(
                source.get("SPRINTER_CODEX_ANALYSIS_LOG_FILE")
                or analysis_config.get("log_file_name", cls.log_file_name)
            ),
            result_file_name=str(
                source.get("SPRINTER_CODEX_ANALYSIS_RESULT_FILE")
                or analysis_config.get("result_file_name", cls.result_file_name)
            ),
            command=str(source.get("SPRINTER_CODEX_ANALYSIS_COMMAND") or codex_config.get("command", cls.command)),
            sandbox=str(source.get("SPRINTER_CODEX_ANALYSIS_SANDBOX") or codex_config.get("sandbox", cls.sandbox)),
            json_output=cls._parse_bool(
                source.get("SPRINTER_CODEX_ANALYSIS_JSON"),
                default=bool(codex_config.get("json", cls.json_output)),
                field_name="SPRINTER_CODEX_ANALYSIS_JSON",
            ),
            timeout_seconds=timeout_seconds,
            model=cls._optional_string(source.get("SPRINTER_CODEX_ANALYSIS_MODEL") or codex_config.get("model")),
            profile=cls._optional_string(source.get("SPRINTER_CODEX_ANALYSIS_PROFILE") or codex_config.get("profile")),
            repo_root=cls._optional_string(
                source.get("SPRINTER_CODEX_ANALYSIS_REPO_ROOT") or analysis_config.get("repo_root")
            ),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        """Validate settings values."""

        if not self.output_dir_name.strip():
            raise CodexAnalysisSettingsError("Codex analysis output directory name must not be empty.")

        for name in (
            self.prompt_file_name,
            self.analysis_file_name,
            self.log_file_name,
            self.result_file_name,
        ):
            if not name.strip():
                raise CodexAnalysisSettingsError("Codex analysis file names must not be empty.")
            if Path(name).name != name:
                raise CodexAnalysisSettingsError(f"Codex analysis {name} must be a file name, not a path.")

        if not self.command.strip():
            raise CodexAnalysisSettingsError("Codex analysis command must not be empty.")

        if self.sandbox not in {"read-only", "workspace-write", "danger-full-access"}:
            raise CodexAnalysisSettingsError(
                "Codex analysis sandbox must be read-only, workspace-write, or danger-full-access."
            )

        if self.timeout_seconds <= 0:
            raise CodexAnalysisSettingsError("Codex analysis timeout must be positive.")

        if self.repo_root is not None and not self.repo_root.strip():
            raise CodexAnalysisSettingsError("Codex analysis repo root must not be empty when set.")

    @classmethod
    def _load_config(cls, path: Optional[str]) -> Mapping[str, object]:
        """Load Codex analysis YAML config."""

        config_path = Path(path).expanduser() if path else cls.DEFAULT_CONFIG_PATH
        if not config_path.exists():
            raise CodexAnalysisSettingsError(f"Codex analysis settings file not found: {config_path}")

        try:
            with config_path.open("r", encoding="utf-8") as handle:
                data = yaml.safe_load(handle) or {}
        except yaml.YAMLError as exc:
            raise CodexAnalysisSettingsError(f"Codex analysis settings file is not valid YAML: {config_path}") from exc
        except OSError as exc:
            raise CodexAnalysisSettingsError(f"Could not read Codex analysis settings file: {config_path}") from exc

        if not isinstance(data, dict):
            raise CodexAnalysisSettingsError("Codex analysis settings file must contain a YAML object.")
        return data

    @staticmethod
    def _section(config: Mapping[str, object], name: str) -> Mapping[str, object]:
        """Return a named config section as a mapping."""

        section = config.get(name, {})
        if section is None:
            return {}
        if not isinstance(section, dict):
            raise CodexAnalysisSettingsError(f"Codex analysis config section must be a mapping: {name}")
        return section

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
        raise CodexAnalysisSettingsError(f"{field_name} must be a boolean value.")

    @staticmethod
    def _optional_string(value: object) -> Optional[str]:
        """Return a non-empty stripped string, or None."""

        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None
