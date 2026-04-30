"""Backward-compatible module name for the Codex implementer worker."""

from workers.implementer_worker import main, run

__all__ = ["main", "run"]


if __name__ == "__main__":
    raise SystemExit(main())
