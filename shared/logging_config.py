"""Centralized logging configuration.

This module provides consistent logging setup across all agents and scripts.
"""

import logging
import os
from pathlib import Path


def setup_logging(
    name: str = "agents",
    level: str | None = None,
    log_file: Path | None = None,
) -> logging.Logger:
    """Configure logging with consistent format.

    Args:
        name: Logger name (typically __name__ from the calling module)
        level: Log level (defaults to LOG_LEVEL env var or INFO)
        log_file: Optional file path for logging output

    Returns:
        Configured logger instance
    """
    level = level or os.getenv("LOG_LEVEL", "INFO")

    handlers: list[logging.Handler] = [logging.StreamHandler()]

    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file))

    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=handlers,
        force=True,  # Override any existing configuration
    )

    return logging.getLogger(name)
