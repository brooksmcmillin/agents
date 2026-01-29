"""Claude Code interactive session management for web interface.

This module provides real-time, interactive Claude Code sessions via WebSocket,
allowing users to interact with Claude Code through a web browser with full
permission request handling.

This is separate from the MCP `run_claude_code` tool which is designed for
agent-to-agent automation. This module is specifically for human-to-Claude Code
interaction through the web UI.
"""

import asyncio
import json
import logging
import os
import pty
import re
import shutil
import signal
import struct
import fcntl
import termios
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, AsyncIterator
from uuid import uuid4

logger = logging.getLogger(__name__)

# Default workspace directory (can be overridden by environment variable)
DEFAULT_WORKSPACES_DIR = os.environ.get(
    "CLAUDE_CODE_WORKSPACES_DIR",
    str(Path.home() / ".claude_code_workspaces"),
)


class SessionState(str, Enum):
    """State of a Claude Code session."""

    STARTING = "starting"
    RUNNING = "running"
    WAITING_PERMISSION = "waiting_permission"
    WAITING_INPUT = "waiting_input"
    COMPLETED = "completed"
    ERROR = "error"
    TERMINATED = "terminated"


class EventType(str, Enum):
    """Types of events emitted by Claude Code sessions."""

    OUTPUT = "output"  # Regular terminal output
    PERMISSION_REQUEST = "permission_request"  # Tool permission prompt
    QUESTION = "question"  # Claude asking for clarification
    STATE_CHANGE = "state_change"  # Session state changed
    ERROR = "error"  # Error occurred
    COMPLETED = "completed"  # Session ended normally


@dataclass
class PermissionRequest:
    """A permission request from Claude Code."""

    id: str
    tool_type: str  # "bash", "edit", "write", "read", etc.
    description: str
    command: str | None = None  # For bash commands
    file_path: str | None = None  # For file operations
    raw_text: str = ""  # Original prompt text


@dataclass
class SessionEvent:
    """An event from a Claude Code session."""

    type: EventType
    data: Any
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dictionary."""
        result = {
            "type": self.type.value,
            "timestamp": self.timestamp.isoformat(),
        }
        if isinstance(self.data, PermissionRequest):
            result["data"] = {
                "id": self.data.id,
                "tool_type": self.data.tool_type,
                "description": self.data.description,
                "command": self.data.command,
                "file_path": self.data.file_path,
            }
        elif isinstance(self.data, dict):
            result["data"] = self.data
        else:
            result["data"] = str(self.data)
        return result


@dataclass
class WorkspaceInfo:
    """Information about a Claude Code workspace."""

    name: str
    path: str
    is_git_repo: bool
    size_mb: float
    file_count: int
    current_branch: str | None = None


class ClaudeCodeSession:
    """An interactive Claude Code session with PTY communication."""

    # Patterns for detecting permission requests in Claude Code output
    # These patterns match Claude Code's permission prompts
    PERMISSION_PATTERNS = [
        # Bash command permission
        (
            r"(?:Allow|Do you want to allow).*?(?:to run|execute|this command)[:\?]?\s*\n?\s*[`'\"]?(.+?)[`'\"]?\s*\n?\s*\[([yn])\]",
            "bash",
        ),
        # File edit permission
        (
            r"(?:Allow|Do you want to allow).*?(?:to edit|modify|write to)[:\?]?\s*[`'\"]?([^\n`'\"]+)[`'\"]?",
            "edit",
        ),
        # File write permission
        (
            r"(?:Allow|Do you want to allow).*?(?:to create|write)[:\?]?\s*[`'\"]?([^\n`'\"]+)[`'\"]?",
            "write",
        ),
        # Generic tool permission
        (
            r"(?:Allow|Approve).*?tool[:\?]?\s*([^\n]+)",
            "tool",
        ),
        # Yes/No prompt detection (more generic)
        (
            r"(\[y/n\]|\(y/n\)|yes/no)",
            "confirm",
        ),
    ]

    # ANSI escape code pattern for stripping
    ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]|\x1b\].*?\x07")

    def __init__(self, session_id: str, workspace_path: Path):
        """Initialize a Claude Code session.

        Args:
            session_id: Unique identifier for this session
            workspace_path: Path to the workspace directory
        """
        self.session_id = session_id
        self.workspace_path = workspace_path
        self.state = SessionState.STARTING
        self.created_at = datetime.now(timezone.utc)
        self.last_activity = self.created_at

        # PTY and process management
        self.master_fd: int | None = None
        self.process: asyncio.subprocess.Process | None = None
        self._output_buffer = ""
        self._pending_permission: PermissionRequest | None = None

        # Event queue for WebSocket communication
        self._event_queue: asyncio.Queue[SessionEvent] = asyncio.Queue()
        self._read_task: asyncio.Task | None = None
        self._terminated = False

    async def start(self, initial_prompt: str | None = None) -> None:
        """Start the Claude Code process with PTY.

        Args:
            initial_prompt: Optional initial prompt to send to Claude Code
        """
        if not shutil.which("claude"):
            raise RuntimeError(
                "Claude Code CLI not found. Please install it: "
                "https://github.com/anthropics/claude-code"
            )

        # Create PTY
        master_fd, slave_fd = pty.openpty()
        self.master_fd = master_fd

        # Set terminal size
        winsize = struct.pack("HHHH", 40, 120, 0, 0)  # rows, cols, xpixel, ypixel
        fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, winsize)

        # Build command - start Claude Code in interactive mode
        cmd = ["claude"]
        if initial_prompt:
            # If there's an initial prompt, pass it as the first message
            cmd.extend(["--message", initial_prompt])

        try:
            # Start subprocess with PTY
            self.process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                cwd=str(self.workspace_path),
                preexec_fn=os.setsid,  # Create new session for proper signal handling
            )
        finally:
            os.close(slave_fd)

        self.state = SessionState.RUNNING
        self._emit_event(EventType.STATE_CHANGE, {"state": self.state.value})

        # Start reading output in background
        self._read_task = asyncio.create_task(self._read_output())

        logger.info(
            f"Started Claude Code session {self.session_id} in {self.workspace_path}"
        )

    async def _read_output(self) -> None:
        """Continuously read output from PTY and emit events."""
        loop = asyncio.get_event_loop()

        while not self._terminated and self.master_fd is not None:
            try:
                # Read from PTY (non-blocking via executor)
                data = await loop.run_in_executor(
                    None, self._read_pty_chunk
                )

                if data is None:
                    # EOF or error
                    break

                if data:
                    self.last_activity = datetime.now(timezone.utc)
                    self._output_buffer += data

                    # Check for permission requests
                    permission = self._detect_permission_request(self._output_buffer)
                    if permission:
                        self._pending_permission = permission
                        self.state = SessionState.WAITING_PERMISSION
                        self._emit_event(EventType.PERMISSION_REQUEST, permission)
                        self._emit_event(
                            EventType.STATE_CHANGE, {"state": self.state.value}
                        )
                        self._output_buffer = ""
                    else:
                        # Emit output event
                        self._emit_event(EventType.OUTPUT, data)

            except Exception as e:
                logger.error(f"Error reading PTY output: {e}")
                self._emit_event(EventType.ERROR, str(e))
                break

        # Session ended
        if not self._terminated:
            self.state = SessionState.COMPLETED
            self._emit_event(EventType.COMPLETED, {"exit_code": self._get_exit_code()})
            self._emit_event(EventType.STATE_CHANGE, {"state": self.state.value})

    def _read_pty_chunk(self) -> str | None:
        """Read a chunk of data from PTY (blocking, run in executor)."""
        if self.master_fd is None:
            return None

        try:
            data = os.read(self.master_fd, 4096)
            if not data:
                return None
            return data.decode("utf-8", errors="replace")
        except OSError:
            return None

    def _detect_permission_request(self, text: str) -> PermissionRequest | None:
        """Detect if text contains a permission request.

        Args:
            text: Text to analyze (may contain ANSI codes)

        Returns:
            PermissionRequest if detected, None otherwise
        """
        # Strip ANSI codes for pattern matching
        clean_text = self.ANSI_ESCAPE.sub("", text)

        for pattern, tool_type in self.PERMISSION_PATTERNS:
            match = re.search(pattern, clean_text, re.IGNORECASE | re.DOTALL)
            if match:
                return PermissionRequest(
                    id=str(uuid4()),
                    tool_type=tool_type,
                    description=match.group(0).strip(),
                    command=match.group(1) if match.lastindex and tool_type == "bash" else None,
                    file_path=match.group(1) if match.lastindex and tool_type in ("edit", "write") else None,
                    raw_text=clean_text[-500:],  # Last 500 chars for context
                )

        return None

    async def send_input(self, text: str) -> None:
        """Send user input to Claude Code.

        Args:
            text: Text to send (will add newline if not present)
        """
        if self.master_fd is None or self._terminated:
            raise RuntimeError("Session is not active")

        if not text.endswith("\n"):
            text += "\n"

        self.last_activity = datetime.now(timezone.utc)
        os.write(self.master_fd, text.encode())

        # Clear pending permission if responding
        if self._pending_permission and self.state == SessionState.WAITING_PERMISSION:
            self._pending_permission = None
            self.state = SessionState.RUNNING
            self._emit_event(EventType.STATE_CHANGE, {"state": self.state.value})

    async def respond_permission(self, approved: bool) -> None:
        """Respond to a pending permission request.

        Args:
            approved: True to approve, False to deny
        """
        response = "y" if approved else "n"
        await self.send_input(response)
        logger.info(
            f"Session {self.session_id}: Permission "
            f"{'approved' if approved else 'denied'}"
        )

    async def resize_terminal(self, rows: int, cols: int) -> None:
        """Resize the PTY terminal.

        Args:
            rows: Number of rows
            cols: Number of columns
        """
        if self.master_fd is None:
            return

        winsize = struct.pack("HHHH", rows, cols, 0, 0)
        try:
            fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ, winsize)
        except OSError as e:
            logger.warning(f"Failed to resize terminal: {e}")

    def _emit_event(self, event_type: EventType, data: Any) -> None:
        """Emit an event to the queue."""
        event = SessionEvent(type=event_type, data=data)
        try:
            self._event_queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.warning(f"Event queue full for session {self.session_id}")

    async def events(self) -> AsyncIterator[SessionEvent]:
        """Async iterator for session events."""
        while not self._terminated:
            try:
                event = await asyncio.wait_for(
                    self._event_queue.get(), timeout=30.0
                )
                yield event

                if event.type in (EventType.COMPLETED, EventType.ERROR):
                    break
            except asyncio.TimeoutError:
                # Send keepalive/heartbeat
                continue

    def _get_exit_code(self) -> int | None:
        """Get process exit code if available."""
        if self.process is not None:
            return self.process.returncode
        return None

    async def terminate(self) -> None:
        """Terminate the session and clean up resources."""
        if self._terminated:
            return

        self._terminated = True
        self.state = SessionState.TERMINATED

        # Cancel read task
        if self._read_task is not None:
            self._read_task.cancel()
            try:
                await self._read_task
            except asyncio.CancelledError:
                pass

        # Terminate process
        if self.process is not None and self.process.returncode is None:
            try:
                # Send SIGTERM to process group
                os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
                await asyncio.wait_for(self.process.wait(), timeout=5.0)
            except (ProcessLookupError, asyncio.TimeoutError):
                # Force kill if needed
                try:
                    os.killpg(os.getpgid(self.process.pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass

        # Close PTY
        if self.master_fd is not None:
            try:
                os.close(self.master_fd)
            except OSError:
                pass
            self.master_fd = None

        self._emit_event(EventType.STATE_CHANGE, {"state": self.state.value})
        logger.info(f"Terminated Claude Code session {self.session_id}")


class ClaudeCodeSessionManager:
    """Manages multiple Claude Code sessions."""

    def __init__(
        self,
        workspaces_dir: str | None = None,
        max_sessions: int = 10,
        session_ttl_seconds: int = 3600,  # 1 hour
    ):
        """Initialize the session manager.

        Args:
            workspaces_dir: Base directory for workspaces
            max_sessions: Maximum concurrent sessions
            session_ttl_seconds: Session timeout in seconds
        """
        self.workspaces_dir = Path(workspaces_dir or DEFAULT_WORKSPACES_DIR)
        self.max_sessions = max_sessions
        self.session_ttl = session_ttl_seconds

        self._sessions: dict[str, ClaudeCodeSession] = {}
        self._cleanup_task: asyncio.Task | None = None

    def start_cleanup_loop(self) -> None:
        """Start background cleanup task."""
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def _cleanup_loop(self) -> None:
        """Periodically clean up expired sessions."""
        while True:
            await asyncio.sleep(60)  # Check every minute
            await self._cleanup_expired()

    async def _cleanup_expired(self) -> None:
        """Clean up expired or inactive sessions."""
        now = datetime.now(timezone.utc)
        expired = []

        for session_id, session in self._sessions.items():
            age = (now - session.last_activity).total_seconds()
            if age > self.session_ttl or session.state in (
                SessionState.COMPLETED,
                SessionState.ERROR,
                SessionState.TERMINATED,
            ):
                expired.append(session_id)

        for session_id in expired:
            await self.terminate_session(session_id)
            logger.info(f"Cleaned up expired session {session_id}")

    async def create_session(
        self,
        workspace_name: str,
        initial_prompt: str | None = None,
    ) -> ClaudeCodeSession:
        """Create a new Claude Code session.

        Args:
            workspace_name: Name of the workspace directory
            initial_prompt: Optional initial prompt to send

        Returns:
            The created session

        Raises:
            ValueError: If workspace doesn't exist or max sessions reached
        """
        if len(self._sessions) >= self.max_sessions:
            raise ValueError(
                f"Maximum sessions ({self.max_sessions}) reached. "
                "Please close an existing session."
            )

        # Validate workspace
        workspace_path = self._get_workspace_path(workspace_name)

        session_id = str(uuid4())
        session = ClaudeCodeSession(session_id, workspace_path)

        await session.start(initial_prompt)
        self._sessions[session_id] = session

        return session

    def get_session(self, session_id: str) -> ClaudeCodeSession | None:
        """Get an existing session by ID."""
        return self._sessions.get(session_id)

    async def terminate_session(self, session_id: str) -> bool:
        """Terminate and remove a session.

        Returns:
            True if session was terminated, False if not found
        """
        session = self._sessions.pop(session_id, None)
        if session is None:
            return False

        await session.terminate()
        return True

    def list_sessions(self) -> list[dict[str, Any]]:
        """List all active sessions."""
        return [
            {
                "session_id": s.session_id,
                "workspace": str(s.workspace_path.name),
                "state": s.state.value,
                "created_at": s.created_at.isoformat(),
                "last_activity": s.last_activity.isoformat(),
            }
            for s in self._sessions.values()
        ]

    def _get_workspace_path(self, workspace_name: str) -> Path:
        """Get and validate workspace path.

        Args:
            workspace_name: Name of the workspace

        Returns:
            Validated Path to workspace

        Raises:
            ValueError: If workspace name is invalid
            FileNotFoundError: If workspace doesn't exist
        """
        # Validate name (prevent path traversal)
        if not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9_\-\.]*$", workspace_name):
            raise ValueError(f"Invalid workspace name: {workspace_name}")

        if ".." in workspace_name or "/" in workspace_name:
            raise ValueError("Path traversal not allowed")

        workspace_path = self.workspaces_dir / workspace_name

        if not workspace_path.exists():
            raise FileNotFoundError(
                f"Workspace not found: {workspace_name}. "
                f"Available: {[w.name for w in self.workspaces_dir.iterdir() if w.is_dir()]}"
            )

        if not workspace_path.is_dir():
            raise ValueError(f"Not a directory: {workspace_name}")

        return workspace_path

    async def list_workspaces(self) -> list[WorkspaceInfo]:
        """List available workspaces.

        Returns:
            List of workspace information
        """
        self.workspaces_dir.mkdir(parents=True, exist_ok=True)

        workspaces = []
        for item in sorted(self.workspaces_dir.iterdir()):
            if not item.is_dir() or item.name.startswith("."):
                continue

            # Check git repo
            is_git_repo = (item / ".git").exists()
            current_branch = None

            if is_git_repo:
                try:
                    branch_file = item / ".git" / "HEAD"
                    if branch_file.exists():
                        content = branch_file.read_text().strip()
                        if content.startswith("ref: refs/heads/"):
                            current_branch = content[16:]
                except Exception:
                    pass

            # Calculate size and file count
            try:
                files = list(item.rglob("*"))
                file_count = sum(1 for f in files if f.is_file())
                size_bytes = sum(
                    f.stat().st_size for f in files if f.is_file()
                )
                size_mb = round(size_bytes / (1024 * 1024), 2)
            except Exception as e:
                logger.warning(f"Failed to calculate size for {item}: {e}")
                file_count = 0
                size_mb = 0

            workspaces.append(
                WorkspaceInfo(
                    name=item.name,
                    path=str(item),
                    is_git_repo=is_git_repo,
                    size_mb=size_mb,
                    file_count=file_count,
                    current_branch=current_branch,
                )
            )

        return workspaces

    async def create_workspace(
        self,
        name: str,
        git_url: str | None = None,
    ) -> WorkspaceInfo:
        """Create a new workspace.

        Args:
            name: Workspace name
            git_url: Optional git repository to clone

        Returns:
            Information about the created workspace
        """
        # Validate name
        if not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9_\-\.]*$", name):
            raise ValueError(f"Invalid workspace name: {name}")

        workspace_path = self.workspaces_dir / name

        if workspace_path.exists():
            raise ValueError(f"Workspace already exists: {name}")

        self.workspaces_dir.mkdir(parents=True, exist_ok=True)

        if git_url:
            # Clone repository
            process = await asyncio.create_subprocess_exec(
                "git", "clone", git_url, str(workspace_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await process.communicate()

            if process.returncode != 0:
                raise RuntimeError(f"Git clone failed: {stderr.decode()}")
        else:
            # Create empty directory with git init
            workspace_path.mkdir(parents=True)
            process = await asyncio.create_subprocess_exec(
                "git", "init", str(workspace_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await process.communicate()

        return WorkspaceInfo(
            name=name,
            path=str(workspace_path),
            is_git_repo=True,
            size_mb=0,
            file_count=0,
            current_branch="main" if git_url else "master",
        )

    async def delete_workspace(self, name: str, force: bool = False) -> bool:
        """Delete a workspace.

        Args:
            name: Workspace name
            force: Force deletion even with uncommitted changes

        Returns:
            True if deleted

        Raises:
            ValueError: If workspace has uncommitted changes and force=False
        """
        workspace_path = self._get_workspace_path(name)

        # Check for uncommitted changes
        if not force and (workspace_path / ".git").exists():
            process = await asyncio.create_subprocess_exec(
                "git", "status", "--porcelain",
                cwd=str(workspace_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await process.communicate()

            if stdout.strip():
                raise ValueError(
                    f"Workspace has uncommitted changes. Use force=True to delete."
                )

        # Terminate any sessions using this workspace
        for session in list(self._sessions.values()):
            if session.workspace_path == workspace_path:
                await self.terminate_session(session.session_id)

        # Delete workspace
        shutil.rmtree(workspace_path)
        return True

    async def shutdown(self) -> None:
        """Shutdown manager and terminate all sessions."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        for session_id in list(self._sessions.keys()):
            await self.terminate_session(session_id)
