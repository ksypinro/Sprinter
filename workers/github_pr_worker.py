"""Backward-compatible module name for the GitHub pusher worker."""

from workers.github_pusher_worker import main, run

__all__ = ["main", "run"]


if __name__ == "__main__":
    raise SystemExit(main())
