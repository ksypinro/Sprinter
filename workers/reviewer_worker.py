"""Backward-compatible module name for the GitHub reviewer worker."""

from workers.github_reviewer_worker import main, run

__all__ = ["main", "run"]


if __name__ == "__main__":
    raise SystemExit(main())
