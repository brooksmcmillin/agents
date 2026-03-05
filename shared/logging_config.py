"""Centralized logging configuration.

This module re-exports setup_logging from agent_framework.logging so that
all agents and scripts use the same full-featured implementation (file handler,
console handler, JSON/Loki format, stderr redirect).
"""

from agent_framework.logging import setup_logging

__all__ = ["setup_logging"]
