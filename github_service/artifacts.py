"""Artifact helpers for GitHub workers."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any


def issue_dir_from_payload(repo_root: Path, workflow_id: str, payload: dict[str, Any]) -> Path:
    if payload.get("issue_dir"):
        return repo_path(repo_root, payload["issue_dir"])
    for key in ("commit_log_path", "implementation_result_path", "analysis_path"):
        value = payload.get(key)
        if value:
            path = repo_path(repo_root, value)
            if path.parent.name in {"codex_implementation", "codex_analysis", "github_pr", "github_review"}:
                return path.parent.parent
            return path.parent
    return repo_root / "exports" / workflow_id


def repo_path(repo_root: Path, value: str) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return repo_root / path


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    with temp.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    temp.replace(path)


def read_text_required(path: Path, label: str) -> str:
    if not path.exists():
        raise FileNotFoundError(f"{label} not found: {path}")
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError(f"{label} is empty: {path}")
    return text
