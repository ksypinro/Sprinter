"""Shared logging configuration for Sprinter entrypoints."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional, TextIO


DEFAULT_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
EXPORT_LOG_FORMAT = "%(asctime)s %(levelname)s %(message)s"
_OWNED_HANDLER_ATTR = "_sprinter_logging_manager_owned"


class SprinterLoggingManager:
    """Own and clean up Sprinter's process-level logging handlers."""

    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger()
        self._handlers: list[logging.Handler] = []

    @property
    def handlers(self) -> tuple[logging.Handler, ...]:
        """Return handlers owned by this manager."""

        return tuple(self._handlers)

    def configure(
        self,
        level: str | int = "INFO",
        log_file: str | Path | None = None,
        *,
        console: bool = True,
        stream: TextIO | None = None,
        log_format: str = DEFAULT_LOG_FORMAT,
    ) -> "SprinterLoggingManager":
        """Configure root-compatible logging and optional durable file output."""

        self.close()
        self.logger.setLevel(_coerce_level(level))
        formatter = logging.Formatter(log_format)

        if console:
            console_handler = logging.StreamHandler(stream or sys.stderr)
            console_handler.setFormatter(formatter)
            self._add_owned_handler(console_handler)

        if log_file:
            file_handler = make_file_handler(log_file, formatter=formatter)
            self._add_owned_handler(file_handler)

        return self

    def get_logger(self, name: str | None = None) -> logging.Logger:
        """Return a logger that participates in this shared configuration."""

        return logging.getLogger(name)

    def close(self) -> None:
        """Flush, remove, and close handlers owned by this manager."""

        for handler in list(self._handlers):
            remove_and_close_handler(handler, logger=self.logger)
        self._handlers.clear()

        for handler in list(self.logger.handlers):
            if getattr(handler, _OWNED_HANDLER_ATTR, False):
                remove_and_close_handler(handler, logger=self.logger)

    def __enter__(self) -> "SprinterLoggingManager":
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    def _add_owned_handler(self, handler: logging.Handler) -> None:
        setattr(handler, _OWNED_HANDLER_ATTR, True)
        self.logger.addHandler(handler)
        self._handlers.append(handler)


_default_manager = SprinterLoggingManager()


def get_logging_manager() -> SprinterLoggingManager:
    """Return the process-wide Sprinter logging manager."""

    return _default_manager


def setup_logging(
    level: str | int = "INFO",
    log_file: str | Path | None = None,
    *,
    console: bool = True,
) -> SprinterLoggingManager:
    """Configure process-level Sprinter logging and return the manager."""

    return _default_manager.configure(level=level, log_file=log_file, console=console)


def ensure_logging(
    level: str | int = "INFO",
    *,
    console: bool = True,
    stream: TextIO | None = None,
    log_format: str = DEFAULT_LOG_FORMAT,
) -> SprinterLoggingManager:
    """Set the root level and add a Sprinter console handler if needed."""

    _default_manager.logger.setLevel(_coerce_level(level))
    if console and not _has_owned_console_handler(_default_manager.logger):
        console_handler = logging.StreamHandler(stream or sys.stderr)
        console_handler.setFormatter(logging.Formatter(log_format))
        _default_manager._add_owned_handler(console_handler)
    return _default_manager


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a stdlib logger configured through the shared manager."""

    return logging.getLogger(name)


def make_file_handler(
    log_path: str | Path,
    *,
    formatter: logging.Formatter | None = None,
    level: str | int | None = None,
) -> logging.FileHandler:
    """Create a UTF-8 file handler, creating parent directories first."""

    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(formatter or logging.Formatter(EXPORT_LOG_FORMAT))
    if level is not None:
        handler.setLevel(_coerce_level(level))
    return handler


def attach_file_handler(
    log_path: str | Path,
    *,
    logger: Optional[logging.Logger] = None,
    formatter: logging.Formatter | None = None,
    level: str | int | None = None,
) -> logging.Handler:
    """Attach a durable file handler to a logger and return it for cleanup."""

    target_logger = logger or logging.getLogger()
    handler = make_file_handler(log_path, formatter=formatter, level=level)
    target_logger.addHandler(handler)
    return handler


def remove_and_close_handler(
    handler: Optional[logging.Handler],
    *,
    logger: Optional[logging.Logger] = None,
) -> None:
    """Remove a handler from a logger, then flush and close it."""

    if handler is None:
        return
    target_logger = logger or logging.getLogger()
    if handler in target_logger.handlers:
        target_logger.removeHandler(handler)
    try:
        handler.flush()
    finally:
        handler.close()


def _coerce_level(level: str | int) -> int:
    if isinstance(level, int):
        return level
    return getattr(logging, str(level).upper(), logging.INFO)


def _has_owned_console_handler(logger: logging.Logger) -> bool:
    return any(
        getattr(handler, _OWNED_HANDLER_ATTR, False)
        and isinstance(handler, logging.StreamHandler)
        and not isinstance(handler, logging.FileHandler)
        for handler in logger.handlers
    )
