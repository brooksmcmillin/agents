"""Session persistence for agent conversations.

Provides save/load functionality so CLI agent sessions can be resumed,
similar to Claude Code's --resume flag.
"""

import json
import logging
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
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def _session_path(self, session_id: str) -> Path:
        """Get the file path for a session."""
        # Sanitize session_id for filesystem safety
        safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in session_id)
        return self.sessions_dir / f"{safe_id}.json"

    def save(
        self,
        session_id: str,
        agent_name: str,
        messages: list[dict[str, Any]],
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

        # Atomic write: write to temp file then rename
        tmp_path = session_path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
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
            logger.debug(
                f"Session loaded: {session_id} ({len(data.get('messages', []))} messages)"
            )
            return data
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"Failed to load session {session_id}: {e}")
            return None

    def list_sessions(
        self, agent_name: str | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
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
                sessions.append({
                    "session_id": data.get("session_id", path.stem),
                    "agent_name": data.get("agent_name", "unknown"),
                    "model": data.get("model", "unknown"),
                    "messages": len(data.get("messages", [])),
                    "total_input_tokens": data.get("total_input_tokens", 0),
                    "total_output_tokens": data.get("total_output_tokens", 0),
                    "created_at": data.get("created_at", ""),
                    "updated_at": data.get("updated_at", ""),
                })
            except (json.JSONDecodeError, OSError):
                continue

        # Sort by updated_at descending (most recent first)
        sessions.sort(key=lambda s: s.get("updated_at", ""), reverse=True)
        return sessions[:limit]

    def get_most_recent_session(self, agent_name: str) -> dict[str, Any] | None:
        """Get the most recently updated session for a given agent.

        Args:
            agent_name: Name of the agent to find sessions for.

        Returns:
            Session data dict, or None if no sessions exist.
        """
        sessions = self.list_sessions(agent_name=agent_name, limit=1)
        if not sessions:
            return None
        return self.load(sessions[0]["session_id"])

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

    Format: {agent_name}-{timestamp_hex}
    Example: chatbot-1a2b3c4d

    Args:
        agent_name: Name of the agent.

    Returns:
        Unique session identifier.
    """
    # Use monotonic-ish timestamp for uniqueness, hex for brevity
    timestamp_hex = hex(int(time.time() * 1000))[2:][-8:]
    safe_name = "".join(c if c.isalnum() or c == "-" else "-" for c in agent_name.lower())
    return f"{safe_name}-{timestamp_hex}"


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
        return obj.model_dump()

    # Handle objects with __dict__
    if hasattr(obj, "__dict__"):
        return {k: _make_serializable(v) for k, v in obj.__dict__.items() if not k.startswith("_")}

    # Fallback: convert to string
    return str(obj)
