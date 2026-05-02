from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional, Protocol

from webhooks.models import WebhookEvent


class Analyzer(Protocol):
    """Protocol for services that analyze an exported issue."""

    def analyze_export(self, event: WebhookEvent, export_result: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze exported issue artifacts and return worker artifact metadata."""
        ...


class AnalyzerFactory(Protocol):
    """Factory protocol for optional analyzer services."""

    def __call__(self, repo_root: Path) -> Optional[Analyzer]:
        """Create an analyzer for the repository root, or None when disabled."""
        ...


class Implementer(Protocol):
    """Protocol for services that implement an analysis plan."""

    def implement_plan(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Implement the plan described by the worker payload."""
        ...


class ImplementerFactory(Protocol):
    """Factory protocol for optional implementer services."""

    def __call__(self, repo_root: Path) -> Optional[Implementer]:
        """Create an implementer for the repository root, or None when disabled."""
        ...
