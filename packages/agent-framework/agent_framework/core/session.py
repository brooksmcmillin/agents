"""Session persistence for agent conversations.

Provides save/load functionality so CLI agent sessions can be saved
and resumed later, similar to Claude Code's --resume flag.
"""

import contextlib
import json
import logging
import os
import secrets
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Default session storage directory
DEFAULT_SESSIONS_DIR = Path.home() / ".agents" / "sessions"


class SessionStore:
    """Manages persistent storage of agent conversation sessions.

    Sessions are stored as JSON files with conversation history,
    token usage, and metadata for resuming later.
    """

    def __init__(self, sessions_dir: Path | None = None) -> None:
        self.sessions_dir = sessions_dir or DEFAULT_SESSIONS_DIR
        self.sessions_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Fix permissions on directories created by older versions
        if self.sessions_dir.stat().st_mode & 0o777 != 0o700:
            self.sessions_dir.chmod(0o700)
        # Clean up orphaned .tmp files from interrupted saves
        for tmp in self.sessions_dir.glob("*.tmp"):
            with contextlib.suppress(OSError):
                tmp.unlink()

    def _session_path(self, session_id: str) -> Path:
        """Get the file path for a session.

        Sanitizes the session_id to ensure filesystem safety (dots become
        underscores, only alphanumeric/hyphens/underscores are kept).
        """
        safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in session_id)
        return self.sessions_dir / f"{safe_id}.json"

    def save(
        self,
        session_id: str,
        agent_name: str,
        messages: list[Any],
        model: str,
        total_input_tokens: int = 0,
        total_output_tokens: int = 0,
    ) -> Path:
        """Save a session to disk.

        Args:
            session_id: Unique session identifier.
            agent_name: Name of the agent class.
            messages: Conversation history (list of MessageParam dicts).
            model: Model name used for the session.
            total_input_tokens: Cumulative input token count.
            total_output_tokens: Cumulative output token count.

        Returns:
            Path to the saved session file.
        """
        session_path = self._session_path(session_id)

        # Serialize messages - convert any non-serializable objects
        serializable_messages = _make_serializable(messages)

        data = {
            "session_id": session_id,
            "agent_name": agent_name,
            "model": model,
            "messages": serializable_messages,
            "total_input_tokens": total_input_tokens,
            "total_output_tokens": total_output_tokens,
            "updated_at": datetime.now(UTC).isoformat(),
        }

        # Preserve created_at from existing session
        if session_path.exists():
            try:
                existing = json.loads(session_path.read_text(encoding="utf-8"))
                data["created_at"] = existing.get("created_at", data["updated_at"])
            except (json.JSONDecodeError, OSError):
                data["created_at"] = data["updated_at"]
        else:
            data["created_at"] = data["updated_at"]

        # Atomic write: create temp file with restricted permissions, then rename
        tmp_path = session_path.with_suffix(".tmp")
        fd = os.open(str(tmp_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(data, indent=2, default=str))
        tmp_path.rename(session_path)

        logger.debug(f"Session saved: {session_id} ({len(messages)} messages)")
        return session_path

    def load(self, session_id: str) -> dict[str, Any] | None:
        """Load a session from disk.

        Args:
            session_id: Session identifier to load.

        Returns:
            Session data dict, or None if not found.
        """
        session_path = self._session_path(session_id)
        if not session_path.exists():
            return None

        try:
            data = json.loads(session_path.read_text(encoding="utf-8"))
            logger.debug(f"Session loaded: {session_id} ({len(data.get('messages', []))} messages)")
            return data
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"Failed to load session {session_id}: {e}")
            return None

    def list_sessions(self, agent_name: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        """List available sessions, optionally filtered by agent name.

        Args:
            agent_name: If provided, only show sessions for this agent.
            limit: Maximum number of sessions to return.

        Returns:
            List of session metadata dicts, sorted by most recently updated.
        """
        sessions: list[dict[str, Any]] = []

        for path in self.sessions_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if agent_name and data.get("agent_name") != agent_name:
                    continue
                sessions.append(
                    {
                        "session_id": data.get("session_id", path.stem),
                        "agent_name": data.get("agent_name", "unknown"),
                        "model": data.get("model", "unknown"),
                        "messages": len(data.get("messages", [])),
                        "total_input_tokens": data.get("total_input_tokens", 0),
                        "total_output_tokens": data.get("total_output_tokens", 0),
                        "created_at": data.get("created_at", ""),
                        "updated_at": data.get("updated_at", ""),
                    }
                )
            except (json.JSONDecodeError, OSError):
                continue

        # Sort by updated_at descending (most recent first)
        sessions.sort(key=lambda s: s.get("updated_at", ""), reverse=True)
        return sessions[:limit]

    def get_most_recent_session_id(self, agent_name: str) -> str | None:
        """Get the session ID of the most recently updated session for an agent.

        Args:
            agent_name: Name of the agent to find sessions for.

        Returns:
            Session ID string, or None if no sessions exist.
        """
        sessions = self.list_sessions(agent_name=agent_name, limit=1)
        if not sessions:
            return None
        return sessions[0]["session_id"]

    def delete(self, session_id: str) -> bool:
        """Delete a session file.

        Args:
            session_id: Session identifier to delete.

        Returns:
            True if deleted, False if not found.
        """
        session_path = self._session_path(session_id)
        if session_path.exists():
            session_path.unlink()
            logger.info(f"Session deleted: {session_id}")
            return True
        return False


def generate_session_id(agent_name: str) -> str:
    """Generate a unique session ID for a new session.

    Format: {agent_name}-{timestamp_hex}{rand_suffix}
    Example: chatbot-1a2b3c4dabcd

    Args:
        agent_name: Name of the agent.

    Returns:
        Unique session identifier.
    """
    # Timestamp for rough ordering + random suffix to avoid collisions
    timestamp_hex = hex(int(time.time() * 1000))[2:][-8:]
    rand_suffix = secrets.token_hex(2)
    safe_name = "".join(c if c.isalnum() or c == "-" else "-" for c in agent_name.lower())
    return f"{safe_name}-{timestamp_hex}{rand_suffix}"


def _make_serializable(obj: Any) -> Any:
    """Recursively convert objects to JSON-serializable forms.

    Handles Anthropic SDK response objects (TextBlock, ToolUseBlock, etc.)
    by converting them to plain dicts.
    """
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj

    if isinstance(obj, dict):
        return {k: _make_serializable(v) for k, v in obj.items()}

    if isinstance(obj, (list, tuple)):
        return [_make_serializable(item) for item in obj]

    # Handle Pydantic models (Anthropic SDK types like TextBlock, ToolUseBlock)
    if hasattr(obj, "model_dump"):
        return _make_serializable(obj.model_dump())

    # Handle objects with __dict__
    if hasattr(obj, "__dict__"):
        return {k: _make_serializable(v) for k, v in obj.__dict__.items() if not k.startswith("_")}

    # Fallback: convert to string (log a warning for debugging unexpected types)
    logger.warning(f"Unexpected type in session data: {type(obj).__name__}, converting to str")
    return str(obj)
