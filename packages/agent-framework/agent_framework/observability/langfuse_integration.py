"""Langfuse integration for agent observability.

This module provides automatic tracing of:
- Anthropic API calls (via OpenTelemetry instrumentation)
- Tool executions
- Full conversation traces with metadata

Usage:
    # Initialize at agent startup
    init_observability()

    # Create a trace for a conversation turn
    with start_trace(name="process_message", metadata={"agent": "chatbot"}) as trace:
        # Anthropic calls are automatically traced
        response = await client.messages.create(...)

        # Manually trace tool calls
        with observe_tool_call(trace, "fetch_web_content", {"url": "..."}) as span:
            result = await tool(...)
            span.end(output=result)

    # Shutdown cleanly
    shutdown_observability()
"""

import logging
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

from ..core.config import settings

logger = logging.getLogger(__name__)

# Global state
_langfuse_client = None
_instrumentor = None
_initialized = False


def init_observability() -> bool:
    """Initialize Langfuse observability.

    Sets up:
    - Langfuse client for trace management
    - OpenTelemetry Anthropic instrumentor for automatic LLM call tracing

    Returns:
        True if initialization successful, False if disabled or failed
    """
    global _langfuse_client, _instrumentor, _initialized

    if _initialized:
        return _langfuse_client is not None

    # Check if Langfuse is enabled and configured
    if not settings.langfuse_enabled:
        logger.debug("Langfuse observability disabled (LANGFUSE_ENABLED=false)")
        _initialized = True
        return False

    if not settings.langfuse_public_key or not settings.langfuse_secret_key:
        logger.warning(
            "Langfuse enabled but missing credentials. "
            "Set LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY."
        )
        _initialized = True
        return False

    try:
        from langfuse import Langfuse
        from opentelemetry.instrumentation.anthropic import AnthropicInstrumentor

        # Initialize Langfuse client
        langfuse_kwargs: dict[str, Any] = {
            "public_key": settings.langfuse_public_key,
            "secret_key": settings.langfuse_secret_key,
        }
        if settings.langfuse_host:
            langfuse_kwargs["host"] = settings.langfuse_host

        _langfuse_client = Langfuse(**langfuse_kwargs)

        # Initialize Anthropic instrumentor for automatic tracing
        _instrumentor = AnthropicInstrumentor()
        _instrumentor.instrument()

        _initialized = True
        logger.info(
            f"Langfuse observability initialized "
            f"(host: {settings.langfuse_host or 'cloud.langfuse.com'})"
        )
        return True

    except ImportError as e:
        logger.warning(f"Langfuse dependencies not available: {e}")
        _initialized = True
        return False
    except Exception as e:
        logger.error(f"Failed to initialize Langfuse: {e}")
        _initialized = True
        return False


def shutdown_observability() -> None:
    """Shutdown Langfuse cleanly, flushing any pending traces."""
    global _langfuse_client, _instrumentor, _initialized

    if _instrumentor is not None:
        try:
            _instrumentor.uninstrument()
        except Exception as e:
            logger.debug(f"Error uninstrumenting Anthropic: {e}")
        _instrumentor = None

    if _langfuse_client is not None:
        try:
            _langfuse_client.flush()
            _langfuse_client.shutdown()
        except Exception as e:
            logger.debug(f"Error shutting down Langfuse: {e}")
        _langfuse_client = None

    _initialized = False
    logger.debug("Langfuse observability shutdown complete")


def get_langfuse():
    """Get the Langfuse instance.

    Returns:
        Langfuse instance or None if not initialized
    """
    return _langfuse_client


class TraceContext:
    """Context manager for Langfuse traces using v3 SDK."""

    def __init__(
        self,
        name: str,
        user_id: str | None = None,
        session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ):
        self.name = name
        self.user_id = user_id
        self.session_id = session_id
        self.metadata = metadata or {}
        self.tags = tags or []
        self.observation = None
        self._context_manager = None

    def __enter__(self):
        if _langfuse_client is None:
            return self

        try:
            # Build observation kwargs
            obs_kwargs: dict[str, Any] = {
                "name": self.name,
                "as_type": "span",
            }
            if self.metadata:
                obs_kwargs["input"] = self.metadata
            if self.user_id:
                obs_kwargs["user_id"] = self.user_id
            if self.session_id:
                obs_kwargs["session_id"] = self.session_id
            if self.tags:
                obs_kwargs["tags"] = self.tags

            self._context_manager = _langfuse_client.start_as_current_observation(**obs_kwargs)
            self.observation = self._context_manager.__enter__()
        except Exception as e:
            logger.debug(f"Failed to create Langfuse observation: {e}")

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._context_manager is not None:
            try:
                # Update with error info if exception occurred
                if exc_type is not None and self.observation is not None:
                    self.observation.update(
                        metadata={
                            **self.metadata,
                            "error": str(exc_val),
                            "error_type": exc_type.__name__,
                        }
                    )
                self._context_manager.__exit__(exc_type, exc_val, exc_tb)
            except Exception as e:
                logger.debug(f"Failed to close observation: {e}")
        return False  # Don't suppress exceptions

    def span(
        self,
        name: str,
        input_data: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> "SpanContext":
        """Create a span within this trace.

        Args:
            name: Span name (e.g., tool name)
            input_data: Input data for the span
            metadata: Additional metadata

        Returns:
            SpanContext that can be used to end the span with output
        """
        return SpanContext(name, input_data, metadata)

    def update(
        self,
        output: Any = None,
        metadata: dict[str, Any] | None = None,
        usage: dict[str, int] | None = None,
    ) -> None:
        """Update the trace with output data.

        Args:
            output: Output data from the traced operation
            metadata: Additional metadata to merge
            usage: Token usage dict with input, output keys
        """
        if self.observation is None:
            return

        try:
            update_kwargs: dict[str, Any] = {}
            if output is not None:
                update_kwargs["output"] = output
            if metadata:
                update_kwargs["metadata"] = {**self.metadata, **metadata}
            if usage:
                # Langfuse v3 uses usage_details
                update_kwargs["usage_details"] = usage
            if update_kwargs:
                self.observation.update(**update_kwargs)
        except Exception as e:
            logger.debug(f"Failed to update observation: {e}")


class SpanContext:
    """Context manager for Langfuse spans within a trace."""

    def __init__(
        self,
        name: str,
        input_data: Any = None,
        metadata: dict[str, Any] | None = None,
    ):
        self.name = name
        self.input_data = input_data
        self.metadata = metadata or {}
        self.observation = None
        self._context_manager = None

    def __enter__(self):
        if _langfuse_client is None:
            return self

        try:
            obs_kwargs: dict[str, Any] = {
                "name": self.name,
                "as_type": "span",
            }
            if self.input_data is not None:
                obs_kwargs["input"] = self.input_data
            if self.metadata:
                obs_kwargs["metadata"] = self.metadata

            self._context_manager = _langfuse_client.start_as_current_observation(**obs_kwargs)
            self.observation = self._context_manager.__enter__()
        except Exception as e:
            logger.debug(f"Failed to create Langfuse span: {e}")

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._context_manager is not None:
            try:
                if exc_type is not None and self.observation is not None:
                    self.observation.update(
                        metadata={
                            **self.metadata,
                            "error": str(exc_val),
                            "error_type": exc_type.__name__,
                        }
                    )
                self._context_manager.__exit__(exc_type, exc_val, exc_tb)
            except Exception as e:
                logger.debug(f"Failed to close span: {e}")
        return False  # Don't suppress exceptions

    def end(
        self,
        output: Any = None,
        metadata: dict[str, Any] | None = None,
        level: str | None = None,
    ) -> None:
        """End the span with output data.

        Args:
            output: Output data from the operation
            metadata: Additional metadata to merge
            level: Log level (DEBUG, DEFAULT, WARNING, ERROR)
        """
        if self.observation is None:
            return

        try:
            update_kwargs: dict[str, Any] = {}
            if output is not None:
                update_kwargs["output"] = output
            if metadata:
                update_kwargs["metadata"] = {**self.metadata, **metadata}
            if level:
                update_kwargs["level"] = level
            if update_kwargs:
                self.observation.update(**update_kwargs)
        except Exception as e:
            logger.debug(f"Failed to update span: {e}")


@contextmanager
def start_trace(
    name: str,
    user_id: str | None = None,
    session_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    tags: list[str] | None = None,
) -> Generator[TraceContext, None, None]:
    """Start a new Langfuse trace.

    Args:
        name: Trace name (e.g., "process_message", "conversation_turn")
        user_id: Optional user identifier for filtering
        session_id: Optional session/conversation ID for grouping
        metadata: Additional metadata (agent name, model, etc.)
        tags: Optional tags for filtering traces

    Yields:
        TraceContext for creating spans and updating the trace

    Example:
        with start_trace("process_message", metadata={"agent": "chatbot"}) as trace:
            # Do work...
            trace.update(output="response text", usage={"input": 100, "output": 50})
    """
    ctx = TraceContext(name, user_id, session_id, metadata, tags)
    try:
        yield ctx.__enter__()
    finally:
        ctx.__exit__(None, None, None)


@contextmanager
def observe_tool_call(
    trace: TraceContext,
    tool_name: str,
    arguments: dict[str, Any],
    metadata: dict[str, Any] | None = None,
) -> Generator[SpanContext, None, None]:
    """Create a span for a tool call within a trace.

    Args:
        trace: Parent TraceContext (unused in v3, kept for API compatibility)
        tool_name: Name of the tool being called
        arguments: Tool arguments
        metadata: Additional metadata

    Yields:
        SpanContext for ending the span with output

    Example:
        with observe_tool_call(trace, "fetch_web_content", {"url": "..."}) as span:
            result = await fetch_web_content(url)
            span.end(output=result)
    """
    span_metadata = {"tool_name": tool_name, **(metadata or {})}
    span_ctx = SpanContext(
        name=f"tool:{tool_name}",
        input_data=arguments,
        metadata=span_metadata,
    )
    try:
        yield span_ctx.__enter__()
    finally:
        span_ctx.__exit__(None, None, None)
