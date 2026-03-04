"""Base agent class for building LLM agents with MCP tools.

This module provides the foundational Agent class that handles:
- Conversation management
- Tool execution via MCP
- Token usage tracking
- Interactive CLI interface
- Permission-based access control via ExecutionContext
"""

import asyncio
import contextvars
import json
import logging
import os
import select
import sys
from abc import ABC, abstractmethod
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from anthropic import APIConnectionError, APIStatusError, AsyncAnthropic
from anthropic.types import (
    Message,
    MessageParam,
    ServerToolUseBlock,
    TextBlock,
    ToolParam,
    ToolUseBlock,
    WebSearchToolResultBlock,
)
from dotenv import load_dotenv

from agent_framework.permissions import (
    AgentIdentity,
    ExecutionContext,
    PermissionSet,
    get_required_permissions,
)
from agent_framework.security.context_trimming import (
    PINNED_EVENT_KEY,
    SECURITY_EVENT_KEY,
    trim_with_security_awareness,
)
from agent_framework.utils.errors import MissingAPIKeyError

from ..logging import setup_logging
from ..telemetry.decision_logger import (
    DECISION_TYPE_ERROR_HANDLING,
    DECISION_TYPE_TOOL_SELECTION,
    log_decision,
)
from .config import settings
from .mcp_client import MCPClient
from .remote_mcp_client import RemoteMCPClient
from .session import SessionStore, generate_session_id

# Import observability (optional - graceful degradation if unavailable)
try:
    from ..observability import (
        init_observability,
        observe_tool_call,
        shutdown_observability,
        start_trace,
    )

    OBSERVABILITY_AVAILABLE = True
except ImportError:
    OBSERVABILITY_AVAILABLE = False
    init_observability = None
    shutdown_observability = None
    start_trace = None
    observe_tool_call = None

if TYPE_CHECKING:
    from ..security import LakeraGuard

# Import security components (optional - for Lakera Guard integration)
try:
    from ..security import LakeraGuard as _LakeraGuard
    from ..security import LakeraSecurityResult, SecurityCheckError
    from ..utils.errors import PromptInjectionError

    SECURITY_AVAILABLE = True
except ImportError:
    SECURITY_AVAILABLE = False
    _LakeraGuard = None
    LakeraSecurityResult = None  # type: ignore[misc]
    PromptInjectionError = None  # type: ignore[misc]
    SecurityCheckError = None  # type: ignore[misc]

# Load environment variables
load_dotenv()

# Constants for agent behavior
MAX_AGENT_ITERATIONS = 10  # Maximum iterations in agentic loop to prevent infinite loops
WEB_SEARCH_MAX_USES = 10  # Maximum web searches allowed per turn (Anthropic API limit)
HIGH_IMPORTANCE_THRESHOLD = 9  # Minimum importance level for memory injection
MAX_INJECTED_MEMORIES = 10  # Maximum memories to inject after context trimming
MAX_TOOL_RESULT_CHARS = 80_000  # Safety net for tool results (~20K tokens)

# Memory tools that should have agent_name auto-injected for isolation
MEMORY_TOOLS = frozenset(
    {
        "save_memory",
        "get_memories",
        "search_memories",
        "recall_memories",
        "delete_memory",
        "get_memory_stats",
    }
)

# Agent email tools that should have agent_name auto-injected
AGENT_EMAIL_TOOLS = frozenset(
    {
        "send_agent_report",
    }
)

# Module-level logger (will be configured per-agent)
logger = logging.getLogger(__name__)

# Request-scoped execution context using ContextVar for thread/async safety
# This ensures concurrent requests don't share or leak permission contexts
_execution_context_var: contextvars.ContextVar[ExecutionContext | None] = contextvars.ContextVar(
    "execution_context", default=None
)


def _truncate_tool_result(content: str, max_chars: int = MAX_TOOL_RESULT_CHARS) -> str:
    """Truncate a tool result string if it exceeds max_chars.

    This is a safety net to prevent oversized tool results from blowing
    out the context window.  Individual tools should limit their own
    output, but this catches anything that slips through.

    Args:
        content: The stringified tool result.
        max_chars: Maximum allowed characters (default MAX_TOOL_RESULT_CHARS).

    Returns:
        The original content if within limits, otherwise a truncated version
        with a note explaining what happened.
    """
    if len(content) <= max_chars:
        return content
    truncated_len = len(content) - max_chars
    logger.warning(
        "Tool result truncated: %d chars exceeded limit of %d (removed %d chars)",
        len(content),
        max_chars,
        truncated_len,
    )
    return (
        content[:max_chars] + f"\n\n[TRUNCATED: result was {len(content):,} chars, "
        f"limit is {max_chars:,}. {truncated_len:,} chars removed.]"
    )


def _read_multiline_input(prompt: str) -> str:
    """Read user input, accumulating multiple lines when pasted.

    Uses select() to detect if additional data is buffered in stdin after
    reading the first line. This handles paste operations where multiple
    lines are added to the buffer at once.

    Args:
        prompt: The prompt to display before input.

    Returns:
        The complete user input, potentially spanning multiple lines.
    """
    # Print prompt and read first line
    first_line = input(prompt)
    lines = [first_line]

    # Check if more data is available in stdin (indicates paste operation)
    # This uses select() which works on Unix-like systems
    try:
        while select.select([sys.stdin], [], [], 0.0)[0]:
            # More data available, read next line
            line = sys.stdin.readline()
            if not line:
                break
            # readline() includes trailing newline, strip it
            lines.append(line.rstrip("\n"))
    except (ValueError, OSError):
        # select() may not work on all platforms (e.g., Windows without PTY)
        # In that case, just return the first line
        pass

    return "\n".join(lines)


class InvalidToolName(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(f"{message} tool not found!")


class Agent(ABC):
    """
    Base agent class using Claude and MCP tools.

    This class provides the core agentic loop that:
    1. Accepts user requests
    2. Calls Claude via Anthropic SDK
    3. Executes MCP tools as needed (with permission checking)
    4. Processes results and continues until done

    Subclasses should override:
    - get_system_prompt(): Return the system prompt for the agent
    - get_greeting(): Return the greeting message shown to users (optional)
    - get_agent_name(): Return the agent name for display (optional)
    - get_default_permissions(): Return the agent's default permission set (optional)

    Permission Model:
    - Agents have a default permission set (overridable via get_default_permissions)
    - When called with an ExecutionContext, permissions are the intersection
      of the context permissions and the agent's defaults
    - Tools check permissions before execution

    Delegation:
    - Agents with enable_delegation=True get a ``request_agent`` virtual tool
      that allows consulting other specialized agents.
    - Delegation preserves the permission model via ExecutionContext intersection.
    - _delegation_config is set at the class level by shared.delegation.setup_delegation().
    """

    # Class-level delegation configuration, set by shared.delegation.setup_delegation().
    # Contains "handler" (async callable) and "schema_builder" (callable) when configured.
    _delegation_config: dict[str, Any] = {}

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "claude-sonnet-4-6",
        mcp_server_path: str = "mcp_server/server.py",
        mcp_urls: list[str] | None = None,
        enable_web_search: bool = True,
        web_search_config: dict[str, Any] | None = None,
        log_dir: Path | None = None,
        mcp_client_config: dict[str, Any] | None = None,
        max_context_messages: int | None = 30,
        inject_memories_on_trim: bool = True,
        allowed_tools: list[str] | None = None,
        enable_security_checks: bool = True,
        skip_failed_mcp_urls: bool = False,
        backup_model: str | None = None,
        backup_api_key: str | None = None,
        enable_delegation: bool = False,
    ):
        """
        Initialize the agent.

        Args:
            api_key: Anthropic API key (defaults to ANTHROPIC_API_KEY env var)
            model: Claude model to use
            mcp_server_path: Path to MCP server script
            mcp_urls: List of remote MCP server URLs
            enable_web_search: Enable Claude's built-in web search capability
            web_search_config: Optional configuration for web search tool:
                - max_uses: Maximum number of web searches per turn (1-10, default: 5)
                - allowed_domains: List of domains to restrict searches to
                - blocked_domains: List of domains to exclude from searches
                - user_location: Dict with type, city, region, country for localized results
            log_dir: Deprecated - use LOG_DIR env var or settings.log_dir instead
            mcp_client_config: Optional configuration for remote MCP clients:
                - auth_token: Manual bearer token (e.g., GitHub PAT) - bypasses OAuth
                - enable_oauth: Enable OAuth discovery (default: True if no auth_token)
                - prefer_device_flow: Use Device Flow (RFC 8628) for OAuth instead of browser
                - oauth_scopes: Space-separated OAuth scopes to request
                - token_storage_dir: Directory for token storage
                - device_authorization_callback: Async callback invoked when device auth is
                    required. Use to notify users via Slack, email, etc. Receives
                    DeviceAuthorizationInfo with user_code and verification URLs.
            max_context_messages: Maximum number of messages to keep in context.
                Set to None to disable automatic trimming. Default: 30
            inject_memories_on_trim: If True, inject high-importance memories into
                context after trimming to preserve key information. Default: True
            allowed_tools: A list of local tools that are explicitly allowed. If None
                then allow all local tools. This does not affect remote tools at all.
            enable_security_checks: If True and LAKERA_API_KEY is set, enable
                Lakera Guard security checks for prompt injection detection.
                If LAKERA_API_KEY is not set, checks are silently skipped. Default: True
            skip_failed_mcp_urls: If True, silently skip remote MCP URLs that fail
                to connect (e.g., due to OAuth prompts) instead of blocking or
                aborting. Useful for subprocess/demo contexts. Default: False
            backup_model: LiteLLM model identifier for fallback when the Anthropic
                API is unavailable (e.g. "openai/gpt-4o"). Defaults to
                BACKUP_MODEL env var. If not set, no fallback is attempted.
            backup_api_key: API key for the backup model provider. Defaults to
                BACKUP_API_KEY env var.
            enable_delegation: If True and delegation is configured (via
                shared.delegation.setup_delegation), adds a ``request_agent`` tool
                that lets this agent consult other specialized agents. Default: False
        """
        # Set up logging first (need agent name, so call get_agent_name early)
        self.log_dir = settings.log_dir
        self.log_file = settings.get_log_file(self.get_agent_name())
        setup_logging(self.get_agent_name())

        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise MissingAPIKeyError("ANTHROPIC_API_KEY")

        self.model = model
        self.mcp_server_path = mcp_server_path
        self.mcp_urls: list[str] = mcp_urls or []
        self.enable_web_search = enable_web_search
        self.web_search_config = web_search_config or {}
        self.mcp_client_config = mcp_client_config or {}
        self.skip_failed_mcp_urls = skip_failed_mcp_urls
        self.enable_delegation = enable_delegation
        self._cached_delegation_schema: dict[str, Any] | None = None
        self.tools: dict[str, list[str]] = {}

        # Context management
        self.max_context_messages = max_context_messages
        self.inject_memories_on_trim = inject_memories_on_trim

        # Initialize Anthropic client
        self.client = AsyncAnthropic(api_key=self.api_key)

        # Backup model fallback (resolved from args -> env -> settings)
        self.backup_model = backup_model or settings.backup_model
        self.backup_api_key = backup_api_key or settings.backup_api_key
        self.use_backup_model = settings.use_backup_model

        # Initialize MCP client with stderr logging to agent's log file
        self.mcp_client = MCPClient(
            mcp_server_path,
            agent_name=self.get_agent_name(),
            stderr_log_file=self.log_file,
            allowed_tools=allowed_tools,
        )

        # Initialize security guard (Lakera Guard) if enabled and available
        self.security_guard: LakeraGuard | None = None
        if enable_security_checks and SECURITY_AVAILABLE and _LakeraGuard is not None:
            # Use API key from settings or environment
            lakera_key = settings.lakera_api_key
            if lakera_key:
                self.security_guard = _LakeraGuard(
                    api_key=lakera_key,
                    project_id=settings.lakera_project_id,
                    fail_open=settings.lakera_fail_open,
                )
                logger.info("Lakera Guard security checks enabled")
            else:
                logger.warning("Prompt injection detection is DISABLED")

        # Conversation history
        self.messages: list[MessageParam] = []

        # Token usage tracking
        self.total_input_tokens = 0
        self.total_output_tokens = 0

        # Session persistence
        self._session_store = SessionStore()

        # Initialize observability (Langfuse)
        self._observability_enabled = False
        if OBSERVABILITY_AVAILABLE and init_observability is not None:
            self._observability_enabled = init_observability()
            if self._observability_enabled:
                logger.info("Langfuse observability enabled for this agent")

        web_search_status = "enabled" if enable_web_search else "disabled"
        logger.info(
            f"Initialized {self.get_agent_name()} with model: {model}, "
            f"web search: {web_search_status}"
        )

    @abstractmethod
    def get_system_prompt(self) -> str:
        """
        Return the system prompt for this agent.

        This defines the agent's role, capabilities, and behavior.
        Should be implemented by subclasses.

        Returns:
            System prompt string
        """
        pass

    def get_agent_name(self) -> str:
        """
        Return the agent name for display.

        Override this to customize the agent name shown in the CLI.

        Returns:
            Agent name (defaults to class name)
        """
        return self.__class__.__name__

    def get_greeting(self) -> str:
        """
        Return the greeting message shown to users.

        Override this to customize the greeting.

        Returns:
            Greeting message
        """
        return f"Hello! I'm {self.get_agent_name()}. How can I help you today?"

    def get_default_permissions(self) -> PermissionSet:
        """
        Return the default permission set for this agent.

        Override this to customize the agent's default permissions.
        When an agent is called with an ExecutionContext, the effective
        permissions are the intersection of the context and agent defaults.

        Returns:
            PermissionSet - defaults to full_access()
        """
        return PermissionSet.full_access()

    def get_execution_context(self) -> ExecutionContext:
        """
        Get the current execution context.

        Uses contextvars for request-scoped storage to ensure concurrent
        requests don't share or leak permission contexts.

        If no context was set (e.g., direct CLI invocation), creates
        a default context with the agent's default permissions.

        Returns:
            Current ExecutionContext
        """
        ctx = _execution_context_var.get()
        if ctx is not None:
            return ctx

        # Create default context for direct invocation
        return ExecutionContext(
            caller=AgentIdentity(name=self.get_agent_name(), source="direct"),
            permissions=self.get_default_permissions(),
        )

    def _create_remote_mcp_client(self, url: str) -> RemoteMCPClient:
        """
        Create a RemoteMCPClient with the configured options.

        Args:
            url: The remote MCP server URL

        Returns:
            Configured RemoteMCPClient instance
        """
        # Determine OAuth behavior - disable if auth_token is provided
        auth_token = self.mcp_client_config.get("auth_token")
        enable_oauth = self.mcp_client_config.get(
            "enable_oauth",
            auth_token is None,  # Default: enable OAuth only if no token
        )

        return RemoteMCPClient(
            url,
            auth_token=auth_token,
            enable_oauth=enable_oauth,
            prefer_device_flow=self.mcp_client_config.get("prefer_device_flow", False),
            oauth_scopes=self.mcp_client_config.get("oauth_scopes"),
            token_storage_dir=self.mcp_client_config.get("token_storage_dir"),
            device_authorization_callback=self.mcp_client_config.get(
                "device_authorization_callback"
            ),
            non_interactive=self.mcp_client_config.get("non_interactive", False),
        )

    _TOOL_NOT_FOUND = object()  # Sentinel to distinguish "local" from "not found"

    def _find_tool_server(self, tool_name: str) -> str | object | None:
        """Find which server provides a tool.

        Args:
            tool_name: Name of the tool to find

        Returns:
            Server URL string if found in a remote server,
            None if local,
            _TOOL_NOT_FOUND sentinel if not found in any registry
        """
        # Check if it's a local tool
        if tool_name in self.tools.get("local", []):
            return None

        # Check remote servers
        for url in self.mcp_urls:
            if tool_name in self.tools.get(url, []):
                return url

        return self._TOOL_NOT_FOUND

    def _check_tool_permissions(self, tool_name: str, server_url: str | None = None) -> None:
        """Check if current context has permission to execute a tool.

        Args:
            tool_name: Name of the tool
            server_url: Optional server URL for remote tools

        Raises:
            PermissionError: If permissions are insufficient
        """
        context = self.get_execution_context()
        required_perms = get_required_permissions(tool_name, server_url)
        missing_perms = [p for p in required_perms if not context.can(p)]

        if missing_perms:
            missing_names = [p.name for p in missing_perms]
            server_info = f" (server: {server_url})" if server_url else ""
            logger.warning(
                f"Permission denied for tool '{tool_name}'{server_info}: "
                f"{context.caller.name} lacks {missing_names}"
            )
            raise PermissionError(
                f"Permission denied: {context.caller.name} cannot execute '{tool_name}'. "
                f"Required permissions: {[p.name for p in required_perms]}. "
                f"Missing: {missing_names}."
            )

        logger.debug(f"Permission check passed for {tool_name}: {context.caller.name}")

    async def _call_mcp_tool_with_reconnect(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Call an MCP tool with automatic reconnection and permission checking.

        This allows the MCP server to be restarted between calls
        without losing the agent's conversation context.

        For memory tools, automatically injects the agent_name parameter
        to ensure memory isolation between different agents.

        Permission checking:
        - Determines which server provides the tool
        - Checks required permissions using server-specific config
        - Raises PermissionError if permissions are insufficient

        Args:
            tool_name: Name of the tool to call
            arguments: Tool arguments

        Returns:
            Tool result

        Raises:
            InvalidToolName: If the tool is not registered in any server
            PermissionError: If the current context lacks required permissions
        """
        # Find which server provides this tool
        server_url = self._find_tool_server(tool_name)

        # Fail fast if tool not found in any registry
        if server_url is self._TOOL_NOT_FOUND:
            raise InvalidToolName(tool_name)

        # Check permissions with server context (server_url is None for local, str for remote)
        self._check_tool_permissions(tool_name, server_url)  # type: ignore[arg-type]

        # Auto-inject agent_name for memory tools and agent email tools
        # Only inject if not already specified (allow explicit override)
        if (
            tool_name in MEMORY_TOOLS or tool_name in AGENT_EMAIL_TOOLS
        ) and "agent_name" not in arguments:
            arguments = {**arguments, "agent_name": self.get_agent_name()}
            logger.debug(f"Auto-injected agent_name='{self.get_agent_name()}' for {tool_name}")

        # Route to the correct server using the result from _find_tool_server
        if server_url is None:
            # Local tool
            async with self.mcp_client.connect():
                return await self.mcp_client.call_tool(tool_name, arguments)
        else:
            # Remote tool - server_url is the URL string
            async with self._create_remote_mcp_client(server_url) as mcp:  # type: ignore[arg-type]
                result = await mcp.call_tool(tool_name, arguments)

                # Handle result - could be string or dict
                if isinstance(result, str):
                    try:
                        result_dict = json.loads(result)
                        return result_dict
                    except json.JSONDecodeError:
                        return {"result": result}
                else:
                    return result

    async def _collect_remote_tools(self, url: str) -> list[dict[str, Any]]:
        """Connect to a single remote MCP server and collect its tools.

        Side-effect: populates ``self.tools[url]`` with a list of tool *name*
        strings (used by the tool-routing logic in ``_find_tool_server``).

        Return value: the raw tool definitions list (name + description +
        input_schema dicts) needed to convert to Anthropic format. The two
        representations differ intentionally — routing only requires names
        while Anthropic format conversion requires the full dict.

        Args:
            url: The URL of the remote MCP server.

        Returns:
            Raw list of tool definitions returned by the remote server.
        """
        async with self._create_remote_mcp_client(url) as mcp:
            mcp_tools = await asyncio.wait_for(mcp.list_tools(), timeout=10.0)
            self.tools[url] = [tool["name"] for tool in mcp_tools]
            return mcp_tools

    async def _update_remote_tools(self) -> dict[str, list[dict[str, Any]]]:
        """Fetch tools from all configured remote MCP servers, pruning failed URLs.

        Iterates ``self.mcp_urls``, calls ``_collect_remote_tools`` for each, and
        removes any URL that raises a connection-related error when
        ``skip_failed_mcp_urls`` is enabled.

        Returns:
            Mapping of URL to raw tool list for each successfully connected server.
            Callers that only need the side-effect (``self.tools`` population) may
            discard the return value.
        """
        failed_urls: list[str] = []
        results: dict[str, list[dict[str, Any]]] = {}
        for url in self.mcp_urls:
            logger.debug(f"Getting tools from {url}")
            try:
                results[url] = await self._collect_remote_tools(url)
            except (ConnectionError, TimeoutError, OSError, ValueError, RuntimeError) as e:
                if self.skip_failed_mcp_urls:
                    logger.warning(f"Skipping failed remote MCP server {url}: {e}")
                    failed_urls.append(url)
                else:
                    raise

        # Remove failed URLs so they aren't retried later
        for url in failed_urls:
            self.mcp_urls.remove(url)

        return results

    async def _get_available_tools(self) -> list[str]:
        """Get list of available MCP tools (reconnects to server)."""

        # Get tools from local MCP server
        async with self.mcp_client.connect():
            self.tools["local"] = self.mcp_client.get_available_tools()

        # Get tools from remote MCP server(s) if applicable; return value not
        # needed here — _update_remote_tools populates self.tools[url] as a
        # side effect, and the concatenation below reads from self.tools.
        logger.debug("Getting available remote tools.")
        _ = await self._update_remote_tools()

        # Return the concatenation of all the tool lists
        return [item for lst in self.tools.values() for item in lst]

    async def start(self, session_id: str | None = None) -> None:
        """Start an interactive session with the agent.

        Args:
            session_id: Optional session ID to resume. When provided, loads
                the previous conversation history. When None, starts a new
                session. Pass the special value ``"last"`` to resume the most
                recent session for this agent.
        """
        session_id, resumed = self._resolve_session(session_id)
        logger.info(f"Starting {self.get_agent_name()} interactive session (session: {session_id})")
        self._print_startup_banner(session_id, resumed)

        # Discover available tools (will reconnect each time we need them)
        try:
            tools_list = await self._get_available_tools()
            logger.info(f"Discovered MCP tools: {tools_list}")
        except Exception as e:
            logger.error(f"Failed to connect to MCP server: {e}")
            print(f"\n⚠️  Warning: Could not connect to MCP server: {e}")
            print("Make sure the MCP server is running and try again.\n")

        # Test remote MCP connection(s)
        if not await self._test_remote_connections():
            return

        await self._run_interactive_loop(session_id)

    def _resolve_session(self, session_id: str | None) -> tuple[str, bool]:
        """Resolve session ID: handle 'last', load existing, or generate new.

        Returns:
            Tuple of (resolved session_id, whether session was resumed).
        """
        resumed = False

        if session_id == "last":
            recent_id = self._session_store.get_most_recent_session_id(self.get_agent_name())
            if recent_id:
                session_id = recent_id
            else:
                print(
                    f"No previous sessions found for {self.get_agent_name()}. Starting new session."
                )
                session_id = None

        if session_id:
            if self.load_session(session_id):
                resumed = True
            else:
                print(f"Session '{session_id}' not found. Starting new session.")
                session_id = None

        if not session_id:
            session_id = generate_session_id(self.get_agent_name())

        return session_id, resumed

    def _print_startup_banner(self, session_id: str, resumed: bool) -> None:
        """Print the agent startup banner with session info."""
        print("\n" + "=" * 70)
        print(self.get_agent_name().upper())
        print("=" * 70)
        if resumed:
            user_turns = sum(1 for m in self.messages if m.get("role") == "user")
            print(f"Resumed session: {session_id} ({user_turns} previous turns)")
        else:
            print(self.get_greeting())
        print(f"\nSession: {session_id}")
        print("\nType 'exit' or 'quit' to end the session.")
        print("Type 'stats' to see token usage statistics.")
        print("Type 'reload' to reconnect to MCP server and discover updated tools.")
        print(f"Logs: {self.log_file}")
        print("=" * 70 + "\n")

    async def _test_remote_connections(self) -> bool:
        """Test remote MCP connections, removing failed URLs if configured to skip.

        Returns:
            True if all connections succeeded or were skipped, False if a fatal
            connection failure occurred and the agent should stop.
        """
        failed_urls: list[str] = []
        for url in self.mcp_urls:
            try:
                print(f"🔌 Connecting to remote MCP server {url}...", flush=True)
                async with self._create_remote_mcp_client(url) as mcp:
                    tools = await asyncio.wait_for(mcp.list_tools(), timeout=10.0)
                    logger.info(f"Connected to MCP server with {len(tools)} tools")
                    print(f"✅ Connected to {url}")
                    print(f"✅ Found {len(tools)} tools\n", flush=True)
            except TimeoutError:
                if self.skip_failed_mcp_urls:
                    logger.warning(f"Timeout connecting to remote MCP server at {url}, skipping")
                    print(f"⚠️  Skipping {url} (timeout)", flush=True)
                    failed_urls.append(url)
                    continue
                print(f"❌ Timeout while connecting to MCP server at {url}")
                print("The connection was established but listing tools timed out.")
                return False
            except (ConnectionError, OSError, ValueError, RuntimeError) as e:
                if self.skip_failed_mcp_urls:
                    logger.warning(
                        f"Failed to connect to remote MCP server at {url}: {e}, skipping"
                    )
                    print(f"⚠️  Skipping {url} ({type(e).__name__})", flush=True)
                    failed_urls.append(url)
                    continue
                print(f"❌ Failed to connect to MCP server at {url}")
                print(f"Error: {e}")
                print("\nPlease ensure:")
                print("1. The MCP server is running")
                print("2. The URL is correct")
                print("3. The server is accessible")
                return False

        for url in failed_urls:
            self.mcp_urls.remove(url)
        return True

    async def _run_interactive_loop(self, session_id: str) -> None:
        """Run the main interactive REPL loop."""
        while True:
            try:
                user_input = _read_multiline_input("\nYou: ").strip()

                if not user_input:
                    continue

                # Handle special commands
                if user_input.lower() in ["exit", "quit"]:
                    if self.messages:
                        self.save_session(session_id)
                        print(f"\nSession saved: {session_id}")
                        print(
                            f"Resume with: uv run python bin/run-agent {self.get_agent_name()} --resume {session_id}"
                        )
                    print("Goodbye! 👋")
                    break

                if user_input.lower() == "stats":
                    self._print_stats()
                    continue

                if user_input.lower() == "reload":
                    print("\n🔄 Reconnecting to MCP server...")
                    try:
                        tools_list = await self._get_available_tools()
                        print(f"✓ Connected! Available tools: {', '.join(tools_list)}")
                    except Exception as e:
                        print(f"✗ Failed to connect: {e}")
                    continue

                # Process user message with streaming output
                first_token = True

                def _stream_to_terminal(text: str) -> None:
                    nonlocal first_token
                    if first_token:
                        sys.stdout.write("\nAssistant: ")
                        first_token = False
                    sys.stdout.write(text)
                    sys.stdout.flush()

                def _show_tool_status(tool_name: str) -> None:
                    nonlocal first_token
                    sys.stdout.write("\n")
                    sys.stdout.write(f"  [calling {tool_name}...]\n")
                    sys.stdout.flush()
                    first_token = True  # reset so next text chunk prints "Assistant: "

                response = await self.process_message(
                    user_input,
                    session_id=session_id,
                    on_text_delta=_stream_to_terminal,
                    on_tool_start=_show_tool_status,
                )

                if not first_token:
                    sys.stdout.write("\n")
                    sys.stdout.flush()
                else:
                    print(f"\nAssistant: {response}")

                # Auto-save session after each turn
                self.save_session(session_id)

            except KeyboardInterrupt:
                self.save_session(session_id)
                print("\n\nSession interrupted. Goodbye! 👋")
                print(f"Session saved: {session_id}")
                print(
                    f"Resume with: uv run python bin/run-agent {self.get_agent_name()} --resume {session_id}"
                )
                break

            except Exception as e:
                logger.exception(f"Error in interaction loop: {e}")
                print(f"\nError: {e}")
                print("Please try again or type 'exit' to quit.")

    async def process_message(
        self,
        user_message: str,
        user_id: str | None = None,
        session_id: str | None = None,
        execution_context: ExecutionContext | None = None,
        on_text_delta: Callable[[str], None] | None = None,
        on_tool_start: Callable[[str], None] | None = None,
    ) -> str:
        """
        Process a user message and return the agent's response.

        This implements the agentic loop:
        1. Manage context (trim if needed, inject memories)
        2. Add user message to conversation
        3. Call Claude with available tools
        4. Execute any tool calls via MCP (with permission checking)
        5. Continue until Claude provides a final response

        Args:
            user_message: The user's input message
            user_id: Optional user ID for observability tracing
            session_id: Optional session/conversation ID for observability tracing
            execution_context: Optional execution context for permission control.
                When provided, the effective permissions are the intersection
                of the context permissions and the agent's default permissions.
                This enables permission propagation through agent chains.
            on_text_delta: Optional callback invoked with each text chunk as it
                arrives from the streaming API. When provided, uses streaming;
                when None, uses the standard blocking API call.
            on_tool_start: Optional callback invoked when a tool call begins,
                receiving the tool name. Useful for showing status indicators
                between streaming text chunks during multi-turn tool use.

        Returns:
            The agent's response as a string
        """
        # Set execution context for this request using ContextVar for async safety
        # This ensures concurrent requests don't share or leak permission contexts
        context_token = None
        if execution_context is not None:
            # Intersect with agent's default permissions (most restrictive wins)
            effective_permissions = execution_context.permissions.intersection(
                self.get_default_permissions()
            )
            # Determine the caller identity - delegate only if from a different agent
            if execution_context.caller.name != self.get_agent_name():
                caller_identity = execution_context.caller.delegate_to(self.get_agent_name())
            else:
                caller_identity = execution_context.caller

            # Create a new context with the effective permissions
            new_context = ExecutionContext(
                caller=caller_identity,
                permissions=effective_permissions,
                parent=execution_context,
                metadata=execution_context.metadata,
            )
            context_token = _execution_context_var.set(new_context)
            logger.info(
                f"Processing with context: {new_context.caller}, "
                f"permissions: {new_context.permissions}"
            )

        # Start observability trace for this message
        trace_ctx = None
        if self._observability_enabled and start_trace is not None:
            trace_ctx = start_trace(
                name="process_message",
                user_id=user_id,
                session_id=session_id,
                metadata={
                    "agent": self.get_agent_name(),
                    "model": self.model,
                },
                tags=[self.get_agent_name()],
            ).__enter__()

        exc_info: tuple | None = None
        try:
            return await self._process_message_internal(
                user_message, trace_ctx, on_text_delta, on_tool_start, session_id
            )
        except BaseException:
            import sys

            exc_info = sys.exc_info()
            raise
        finally:
            # Reset execution context to prevent leaking between requests
            if context_token is not None:
                _execution_context_var.reset(context_token)

            if trace_ctx is not None and exc_info is not None:
                trace_ctx.__exit__(*exc_info)
            elif trace_ctx is not None:
                trace_ctx.__exit__(None, None, None)

    def _messages_for_api(self) -> list[MessageParam]:
        """Return a copy of self.messages with internal metadata stripped.

        The ``_security_event`` and ``_pinned`` keys are used by the
        context-trimming logic to pin messages, but the Anthropic API rejects
        extra fields on tool_result blocks.  Strip them before sending.
        """
        _internal_keys = {SECURITY_EVENT_KEY, PINNED_EVENT_KEY}
        cleaned: list[MessageParam] = []
        for msg in self.messages:
            # Tool result blocks are plain dicts at runtime (built by
            # _make_tool_error_result), but MessageParam types them as
            # ContentBlockParam which doesn't include dict.  Use Any to
            # avoid pyright narrowing to Never.
            content: Any = msg.get("content")
            if isinstance(content, list) and any(
                isinstance(block, dict) and _internal_keys & block.keys() for block in content
            ):
                new_blocks: list[Any] = []
                for block in content:
                    if isinstance(block, dict) and _internal_keys & block.keys():
                        new_blocks.append(
                            {k: v for k, v in block.items() if k not in _internal_keys}
                        )
                    else:
                        new_blocks.append(block)
                cleaned.append(cast(MessageParam, {**msg, "content": new_blocks}))
            else:
                cleaned.append(cast(MessageParam, msg))
        return cleaned

    async def _call_claude(
        self,
        tools: list[dict[str, Any]],
        on_text_delta: Callable[[str], None] | None = None,
    ) -> Message:
        """Call Claude API, using streaming when a text callback is provided.

        If the Anthropic API is unreachable and a ``backup_model`` is configured,
        the request is automatically retried via LiteLLM against the backup
        provider. The response is converted back to an Anthropic ``Message`` so
        downstream code is unaffected.

        Args:
            tools: Tool definitions in Anthropic format.
            on_text_delta: Optional callback for streaming text deltas.
                When provided, the streaming API is used; otherwise the
                blocking ``messages.create`` endpoint is called.

        Returns:
            The final ``Message`` from the Claude API (or backup model).
        """
        # USE_BACKUP_MODEL=true → skip Anthropic entirely and route through LiteLLM
        if self.use_backup_model and self.backup_model:
            logger.info("USE_BACKUP_MODEL is set, routing to backup model: %s", self.backup_model)
            from .backup_model import call_backup_model

            return await call_backup_model(
                model=self.backup_model,
                api_key=self.backup_api_key,
                system_prompt=self.get_system_prompt(),
                messages=self.messages,
                tools=tools,
                max_tokens=16000,
                on_text_delta=on_text_delta,
            )

        api_messages = self._messages_for_api()
        try:
            if on_text_delta is not None:
                async with self.client.messages.stream(
                    model=self.model,
                    max_tokens=16000,
                    system=self.get_system_prompt(),
                    messages=api_messages,
                    tools=cast(list[ToolParam], tools),
                ) as stream:
                    async for text in stream.text_stream:
                        on_text_delta(text)
                    return await stream.get_final_message()
            else:
                return await self.client.messages.create(
                    model=self.model,
                    max_tokens=16000,
                    system=self.get_system_prompt(),
                    messages=api_messages,
                    tools=cast(list[ToolParam], tools),
                )
        except (APIConnectionError, APIStatusError) as exc:
            # Only fall back on server-side / connectivity errors, not auth errors
            if isinstance(exc, APIStatusError) and exc.status_code < 500:
                raise
            if not self.backup_model:
                raise
            logger.warning(
                "Anthropic API unavailable (%s), falling back to backup model: %s",
                exc,
                self.backup_model,
            )
            from .backup_model import call_backup_model

            return await call_backup_model(
                model=self.backup_model,
                api_key=self.backup_api_key,
                system_prompt=self.get_system_prompt(),
                messages=self.messages,
                tools=tools,
                max_tokens=16000,
                on_text_delta=on_text_delta,
            )

    def _make_tool_error_result(
        self,
        tool_use_id: str,
        error: Exception,
        *,
        is_permission_error: bool = False,
    ) -> dict[str, Any]:
        """Build a tool-result dict that reports an error back to Claude.

        Args:
            tool_use_id: The ``id`` of the ``ToolUseBlock`` that failed.
            error: The exception that was raised.
            is_permission_error: When ``True``, the result is tagged with a
                ``permission_denied`` security event and uses a
                "Permission denied" prefix.  Otherwise the result uses a
                "Tool execution failed" prefix and is additionally checked
                for SSRF-related keywords.

        Returns:
            A dict suitable for inclusion in the ``tool_results`` list sent
            back to the Claude API.
        """
        if is_permission_error:
            return {
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "content": f"Permission denied: {error}",
                "is_error": True,
                SECURITY_EVENT_KEY: "permission_denied",
            }

        error_result: dict[str, Any] = {
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "content": f"Tool execution failed: {error}",
            "is_error": True,
        }
        # Tag SSRF-related errors for context-aware trimming
        error_str = str(error).lower()
        if any(
            kw in error_str
            for kw in (
                "ssrf",
                "blocked hostname",
                "blocked ip",
                "private ip",
                "metadata endpoint",
            )
        ):
            error_result[SECURITY_EVENT_KEY] = "ssrf_block"
        return error_result

    async def _execute_tool_calls(
        self,
        tool_calls: list[ToolUseBlock],
        trace_ctx,
        on_tool_start: Callable[[str], None] | None = None,
        session_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Execute a batch of tool calls and return their results.

        Each tool is called via :pymethod:`_call_mcp_tool_with_reconnect`
        with optional observability spans.  Errors (including
        ``PermissionError``) are caught per-tool and reported back to the
        model via error result dicts.

        Args:
            tool_calls: ``ToolUseBlock`` instances extracted from the
                assistant response.
            trace_ctx: Optional observability trace context.
            on_tool_start: Optional callback invoked when a tool call
                begins, receiving the tool name.
            session_id: Optional session ID for decision log correlation.

        Returns:
            A list of tool-result dicts ready to append to the conversation.
        """
        tool_results: list[dict[str, Any]] = []
        for tool_call in tool_calls:
            logger.info(f"Executing tool: {tool_call.name}")
            if on_tool_start is not None:
                on_tool_start(tool_call.name)

            # Prepare tool input for observability (preserve non-dict inputs)
            tool_input = (
                tool_call.input
                if isinstance(tool_call.input, dict)
                else {"_raw_input": str(tool_call.input)}
            )

            # Start tool span for observability
            tool_span = None
            tool_span_exc_info: tuple | None = None
            if (
                trace_ctx is not None
                and self._observability_enabled
                and observe_tool_call is not None
            ):
                tool_span = observe_tool_call(
                    trace_ctx,
                    tool_call.name,
                    tool_input,
                ).__enter__()

            try:
                # Handle delegation tool calls in-process (not via MCP)
                if (
                    tool_call.name == "request_agent"
                    and self.enable_delegation
                    and "handler" in self._delegation_config
                ):
                    self._check_tool_permissions("request_agent")
                    handler = self._delegation_config["handler"]
                    input_dict = tool_call.input if isinstance(tool_call.input, dict) else {}
                    result = await handler(
                        input_dict.get("agent_name", ""),
                        input_dict.get("message", ""),
                        self,
                    )
                else:
                    # Call MCP tool (reconnects to server each time)
                    result = await self._call_mcp_tool_with_reconnect(
                        tool_call.name,
                        tool_call.input,
                    )

                # End tool span with success
                if tool_span is not None:
                    result_str = str(result)
                    truncated_output = (
                        result_str[:500] + "... [truncated]"
                        if len(result_str) > 500
                        else result_str
                    )
                    tool_span.end(output=truncated_output, level="DEFAULT")

                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_call.id,
                        "content": _truncate_tool_result(str(result)),
                    }
                )

            except PermissionError as e:
                # Handle permission errors gracefully - return as tool error
                # so Claude can explain the limitation to the user naturally
                logger.warning(f"Permission denied for {tool_call.name}: {e}")
                tool_span_exc_info = (type(e), e, e.__traceback__)

                # End tool span with error
                if tool_span is not None:
                    tool_span.end(
                        output=f"Permission denied: {e}",
                        level="WARNING",
                        metadata={"error_type": "PermissionError"},
                    )

                # Log permission error handling decision.
                # Use type(e).__name__ rather than str(e) to avoid leaking
                # sensitive permission details into the decision log.
                log_decision(
                    agent=self.get_agent_name(),
                    decision_type=DECISION_TYPE_ERROR_HANDLING,
                    inputs={
                        "tool_name": tool_call.name,
                        "error_type": type(e).__name__,
                    },
                    output={"action": "return_permission_error_to_model"},
                    reasoning=type(e).__name__,
                    session_id=session_id,
                )

                tool_results.append(
                    self._make_tool_error_result(tool_call.id, e, is_permission_error=True)
                )

            except Exception as e:
                # Handle other tool errors
                logger.error(f"Tool execution error for {tool_call.name}: {e}")
                tool_span_exc_info = (type(e), e, e.__traceback__)

                # End tool span with error
                if tool_span is not None:
                    tool_span.end(
                        output=f"Tool execution failed: {e}",
                        level="ERROR",
                        metadata={"error_type": type(e).__name__},
                    )

                # Log tool execution error handling decision
                # Use type name only — not str(e) — to avoid leaking
                # sensitive data (API keys, connection strings, etc.) from
                # exception messages into the decision log.
                log_decision(
                    agent=self.get_agent_name(),
                    decision_type=DECISION_TYPE_ERROR_HANDLING,
                    inputs={
                        "tool_name": tool_call.name,
                        "error_type": type(e).__name__,
                    },
                    output={"action": "return_tool_error_to_model"},
                    reasoning=type(e).__name__,
                    session_id=session_id,
                )

                tool_results.append(self._make_tool_error_result(tool_call.id, e))

            finally:
                # Always close the tool span context manager
                if tool_span is not None:
                    if tool_span_exc_info is not None:
                        tool_span.__exit__(*tool_span_exc_info)
                    else:
                        tool_span.__exit__(None, None, None)

        return tool_results

    async def _process_message_internal(
        self,
        user_message: str,
        trace_ctx,
        on_text_delta: Callable[[str], None] | None = None,
        on_tool_start: Callable[[str], None] | None = None,
        session_id: str | None = None,
    ) -> str:
        """Internal message processing with observability context.

        Args:
            user_message: The user's input message
            trace_ctx: Optional TraceContext for observability
            on_text_delta: Optional callback for streaming text deltas
            on_tool_start: Optional callback invoked when a tool call begins
            session_id: Optional session ID for decision log correlation

        Returns:
            The agent's response as a string
        """
        # Manage context before processing (trim old messages, inject memories if needed)
        await self._manage_context()

        # Security check: Screen user input for prompt injection and other threats
        if self.security_guard is not None:
            try:
                security_result = await self.security_guard.check_input(user_message)
            except Exception as e:
                if SecurityCheckError is not None and isinstance(e, SecurityCheckError):
                    # Lakera API is unreachable and fail_open=False: block the request
                    logger.warning(f"Lakera Guard API error (fail-closed): {e}")
                    return (
                        "I'm sorry, but the security check service is temporarily unavailable. "
                        "Please try again later."
                    )
                raise
            if security_result.skipped:
                logger.debug("Lakera Guard check was skipped (no API key or disabled)")
            elif security_result.flagged:
                logger.warning(
                    f"Security threat detected in user input: {security_result.categories}"
                )
                # Raise PromptInjectionError if available, otherwise return error message
                if PromptInjectionError is not None:
                    raise PromptInjectionError(
                        f"Security threat detected: {security_result.categories}. "
                        "Your message was blocked for safety reasons."
                    )
                return (
                    "I'm sorry, but your message was flagged by our security system "
                    "and cannot be processed. Please rephrase your request."
                )

        # Add user message to conversation history
        self.messages.append(
            {
                "role": "user",
                "content": user_message,
            }
        )

        # Convert MCP tools to Anthropic tool format (reconnects to get latest)
        tools = await self._convert_mcp_tools_to_anthropic()

        # Agentic loop - continue until we get a text response
        iteration = 0

        while iteration < MAX_AGENT_ITERATIONS:
            iteration += 1
            logger.info(f"Agent iteration {iteration}")

            try:
                # Call Claude (streaming when callback provided, blocking otherwise)
                response = await self._call_claude(tools, on_text_delta)

                # Track token usage
                self.total_input_tokens += response.usage.input_tokens
                self.total_output_tokens += response.usage.output_tokens

                logger.info(
                    f"Claude response - input tokens: {response.usage.input_tokens}, "
                    f"output tokens: {response.usage.output_tokens}"
                )

                # Check stop reason
                if response.stop_reason == "end_turn":
                    # Extract text response
                    text_response = self._extract_text_from_response(response.content)

                    # Add assistant response to conversation (ensure non-empty)
                    self.messages.append(
                        {
                            "role": "assistant",
                            "content": self._ensure_non_empty_content(response.content),
                        }
                    )

                    # Update trace with final output and token usage
                    if trace_ctx is not None:
                        trace_ctx.update(
                            output=(
                                text_response[:1000] + "... [truncated]"
                                if len(text_response) > 1000
                                else text_response
                            ),
                            usage={
                                "input": self.total_input_tokens,
                                "output": self.total_output_tokens,
                            },
                            metadata={"iterations": iteration},
                        )

                    return text_response

                elif response.stop_reason == "tool_use":
                    # Extract tool calls
                    tool_calls = [
                        block for block in response.content if isinstance(block, ToolUseBlock)
                    ]

                    if not tool_calls:
                        logger.warning("No tool calls found despite tool_use stop reason")
                        text_response = self._extract_text_from_response(response.content)
                        self.messages.append(
                            {
                                "role": "assistant",
                                "content": self._ensure_non_empty_content(response.content),
                            }
                        )
                        return text_response

                    # Log tool selection decision
                    log_decision(
                        agent=self.get_agent_name(),
                        decision_type=DECISION_TYPE_TOOL_SELECTION,
                        inputs={
                            "iteration": iteration,
                            "available_tool_count": sum(len(v) for v in self.tools.values()),
                            "message_count": len(self.messages),
                        },
                        output={
                            "selected_tools": [tc.name for tc in tool_calls],
                            "tool_count": len(tool_calls),
                        },
                        session_id=session_id,
                    )

                    # Add assistant response to conversation (with tool calls)
                    # Note: tool_use responses should always have content, but ensure non-empty
                    self.messages.append(
                        {
                            "role": "assistant",
                            "content": self._ensure_non_empty_content(response.content),
                        }
                    )

                    # Execute tool calls and collect results
                    tool_results = await self._execute_tool_calls(
                        tool_calls, trace_ctx, on_tool_start, session_id
                    )

                    # Add tool results to conversation
                    self.messages.append(
                        cast(
                            MessageParam,
                            {
                                "role": "user",
                                "content": tool_results,
                            },
                        )
                    )

                    # Continue loop to get Claude's response to tool results

                else:
                    # Unexpected stop reason
                    logger.warning(f"Unexpected stop reason: {response.stop_reason}")
                    text_response = self._extract_text_from_response(response.content)
                    self.messages.append(
                        {
                            "role": "assistant",
                            "content": self._ensure_non_empty_content(response.content),
                        }
                    )
                    return text_response

            except Exception as e:
                logger.exception(f"Error in agent loop: {e}")
                # Update trace with error
                if trace_ctx is not None:
                    trace_ctx.update(
                        metadata={
                            "error": str(e),
                            "error_type": type(e).__name__,
                            "iterations": iteration,
                        }
                    )
                return f"I encountered an error: {e}. Please try again."

        # Max iterations reached
        logger.warning(f"Max iterations ({MAX_AGENT_ITERATIONS}) reached")
        # Update trace with max iterations warning
        if trace_ctx is not None:
            trace_ctx.update(
                metadata={
                    "warning": "max_iterations_reached",
                    "iterations": MAX_AGENT_ITERATIONS,
                }
            )
        return "I apologize, but I'm having trouble completing this request. Please try rephrasing or breaking it into smaller steps."

    async def _convert_mcp_tools_to_anthropic(self) -> list[dict[str, Any]]:
        """
        Convert MCP tool definitions to Anthropic tool format.

        Reconnects to MCP server to get latest tool definitions.
        This allows tools to be updated without restarting the agent.
        Also populates self.tools for use by _call_mcp_tool_with_reconnect().

        Returns:
            List of tool definitions in Anthropic format
        """
        anthropic_tools: list[dict[str, Any]] = []

        # Add Claude's built-in web search tool if enabled
        if self.enable_web_search:
            web_search_tool = self._build_web_search_tool()
            anthropic_tools.append(web_search_tool)
            logger.info(f"Added web search tool to available tools: {web_search_tool}")

        # Reconnect to get latest tools from local MCP server
        async with self.mcp_client.connect():
            # Populate self.tools["local"] for tool routing
            self.tools["local"] = self.mcp_client.get_available_tools()

            for _, tool_info in self.mcp_client.available_tools.items():
                anthropic_tools.append(
                    {
                        "name": tool_info.name,
                        "description": tool_info.description,
                        "input_schema": tool_info.inputSchema,
                    }
                )

        # Get remote MCP Server tools
        logger.debug("Starting Remote MCP Server Checks")
        remote_tools = await self._update_remote_tools()
        for mcp_tools in remote_tools.values():
            # Convert to Anthropic format
            anthropic_tools += [
                {
                    "name": tool["name"],
                    "description": tool["description"],
                    "input_schema": tool["input_schema"],
                }
                for tool in mcp_tools
            ]

        # Add delegation tool (request_agent) if enabled and configured
        if self.enable_delegation and self._delegation_config:
            if self._cached_delegation_schema is None:
                schema_builder = self._delegation_config.get("schema_builder")
                if schema_builder:
                    self._cached_delegation_schema = schema_builder(
                        exclude_class_name=self.__class__.__name__
                    )
            if self._cached_delegation_schema:
                anthropic_tools.append(self._cached_delegation_schema)

        return anthropic_tools

    def _build_web_search_tool(self) -> dict[str, Any]:
        """
        Build the Claude web search tool configuration.

        Returns:
            Web search tool definition in Anthropic format
        """
        web_search_tool: dict[str, Any] = {
            "type": "web_search_20250305",
            "name": "web_search",
        }

        # Add optional configuration
        if "max_uses" in self.web_search_config:
            max_uses = self.web_search_config["max_uses"]
            if isinstance(max_uses, int) and 1 <= max_uses <= WEB_SEARCH_MAX_USES:
                web_search_tool["max_uses"] = max_uses

        if "allowed_domains" in self.web_search_config:
            domains = self.web_search_config["allowed_domains"]
            if isinstance(domains, list) and all(isinstance(d, str) for d in domains):
                web_search_tool["allowed_domains"] = domains

        if "blocked_domains" in self.web_search_config:
            domains = self.web_search_config["blocked_domains"]
            if isinstance(domains, list) and all(isinstance(d, str) for d in domains):
                web_search_tool["blocked_domains"] = domains

        if "user_location" in self.web_search_config:
            location = self.web_search_config["user_location"]
            if isinstance(location, dict):
                web_search_tool["user_location"] = location

        return web_search_tool

    def _extract_text_from_response(self, content: list[Any]) -> str:
        """
        Extract text content from Claude's response.

        Handles regular text blocks and web search result blocks.

        Args:
            content: Response content blocks

        Returns:
            Concatenated text content including web search sources
        """
        text_parts = []
        sources = []

        for block in content:
            if isinstance(block, TextBlock):
                text_parts.append(block.text)
            # Log web search queries when Claude performs searches
            elif isinstance(block, ServerToolUseBlock):
                if block.name == "web_search":
                    query = block.input.get("query", "") if isinstance(block.input, dict) else ""
                    logger.info(f"Web search performed with query: {query}")
            # Handle web search results - extract source citations
            elif (
                isinstance(block, WebSearchToolResultBlock)
                and hasattr(block, "content")
                and block.content
                and isinstance(block.content, list)
            ):
                logger.info(f"Web search returned {len(block.content)} results")
                for result_content in block.content:
                    if hasattr(result_content, "url") and hasattr(result_content, "title"):
                        sources.append(
                            f"- [{result_content.title}]({result_content.url})"  # type: ignore
                        )

        response_text = "\n\n".join(text_parts) if text_parts else ""

        # Append sources if available
        if sources:
            unique_sources = list(dict.fromkeys(sources))  # Remove duplicates
            response_text += "\n\n**Sources:**\n" + "\n".join(unique_sources)

        # Return fallback if response is empty to prevent API errors
        # (Anthropic requires non-empty content for non-final assistant messages)
        if not response_text:
            return "<No text in response>"

        return response_text

    def _ensure_non_empty_content(self, content: list[Any]) -> list[Any]:
        """
        Ensure content list is not empty for assistant messages.

        The Anthropic API requires all messages (except the optional final
        assistant message) to have non-empty content. This method returns
        a fallback text block if the content is empty.

        Args:
            content: Response content blocks

        Returns:
            Original content if non-empty, otherwise a fallback text block
        """
        if content:
            return content

        logger.warning("Empty content detected in assistant response, adding fallback")
        return [TextBlock(type="text", text="<No text in response>")]

    def _print_stats(self) -> None:
        """Print token usage statistics."""
        total_tokens = self.total_input_tokens + self.total_output_tokens

        print("\n" + "=" * 70)
        print("TOKEN USAGE STATISTICS")
        print("=" * 70)
        print(f"Input tokens:  {self.total_input_tokens:,}")
        print(f"Output tokens: {self.total_output_tokens:,}")
        print(f"Total tokens:  {total_tokens:,}")
        print(f"Conversations: {len([m for m in self.messages if m['role'] == 'user'])}")
        print("=" * 70)

    def reset_conversation(self) -> None:
        """Reset the conversation history."""
        self.messages = []
        logger.info("Conversation history reset")

    # ── Session persistence ──────────────────────────────────────────

    def save_session(self, session_id: str) -> Path:
        """Save the current conversation to disk so it can be resumed later.

        Args:
            session_id: Unique session identifier.

        Returns:
            Path to the saved session file.
        """
        return self._session_store.save(
            session_id=session_id,
            agent_name=self.get_agent_name(),
            messages=self.messages,
            model=self.model,
            total_input_tokens=self.total_input_tokens,
            total_output_tokens=self.total_output_tokens,
        )

    def load_session(self, session_id: str) -> bool:
        """Restore a previously saved session into this agent.

        Args:
            session_id: Session identifier to load.

        Returns:
            True if session was loaded successfully, False otherwise.
        """
        data = self._session_store.load(session_id)
        if data is None:
            logger.warning(f"Session not found: {session_id}")
            return False

        messages = data.get("messages", [])
        if not isinstance(messages, list):
            logger.error(f"Corrupt session {session_id}: 'messages' is not a list")
            return False

        # Note: individual message items are trusted from disk without integrity
        # verification. Session files are protected by 0o600 permissions, which is
        # sufficient for a single-user CLI tool. Multi-user deployments should add
        # HMAC-based tamper detection.
        self.messages = messages
        self.total_input_tokens = data.get("total_input_tokens", 0)
        self.total_output_tokens = data.get("total_output_tokens", 0)
        logger.info(
            f"Session restored: {session_id} ({len(self.messages)} messages, "
            f"{self.total_input_tokens + self.total_output_tokens:,} tokens)"
        )
        return True

    def _trim_context_if_needed(self) -> bool:
        """Trim conversation context if it exceeds max_context_messages.

        Uses context-aware trimming that preserves security-critical messages
        (permission denials, SSRF blocks, prompt injection detections) to prevent
        attackers from exploiting context trimming to retry blocked attacks.

        Returns:
            True if context was trimmed, False otherwise
        """
        if self.max_context_messages is None:
            return False

        if len(self.messages) <= self.max_context_messages:
            return False

        trimmed, num_removed, num_pinned = trim_with_security_awareness(
            cast(list[dict[str, Any]], self.messages),
            max_messages=self.max_context_messages,
        )
        self.messages = cast(list[MessageParam], trimmed)

        return True

    async def _inject_memories_into_context(self) -> None:
        """Inject high-importance memories into the conversation context.

        This helps preserve key information after context trimming.
        Memories are injected as a system-style user message.
        Uses the agent's name for memory isolation.
        Respects the configured MEMORY_BACKEND (file or database).
        """
        try:
            from ..tools.memory import (
                get_database_memory_store,
                get_memory_backend,
                get_memory_store,
            )

            agent_name = self.get_agent_name()
            backend = get_memory_backend()

            if backend == "database":
                store = await get_database_memory_store(agent_name=agent_name)
                memories = await store.get_all_memories(min_importance=HIGH_IMPORTANCE_THRESHOLD)
            else:
                store = get_memory_store(agent_name=agent_name)
                memories = store.get_all_memories(min_importance=HIGH_IMPORTANCE_THRESHOLD)

            if not memories:
                logger.debug("No high-importance memories to inject")
                return

            # Format memories as context
            memory_lines = ["[Context from previous conversations - key information to remember:]"]
            for m in memories[:MAX_INJECTED_MEMORIES]:
                memory_lines.append(f"• {m.key}: {m.value}")

            memory_context = "\n".join(memory_lines)

            # Insert as a user message at the beginning of the trimmed context
            # This ensures Claude sees it but it's not in the middle of a conversation
            self.messages.insert(
                0,
                {
                    "role": "user",
                    "content": f"[SYSTEM CONTEXT]\n{memory_context}\n[END SYSTEM CONTEXT]\n\nPlease acknowledge you've received this context briefly.",
                },
            )
            self.messages.insert(
                1,
                {
                    "role": "assistant",
                    "content": "Understood, I've noted the key context from previous conversations.",
                },
            )

            logger.info(
                f"Injected {len(memories[:MAX_INJECTED_MEMORIES])} high-importance memories into context"
            )

        except Exception as e:
            logger.warning(f"Failed to inject memories: {e}")

    async def _manage_context(self) -> None:
        """Manage conversation context - trim if needed and optionally inject memories."""
        was_trimmed = self._trim_context_if_needed()

        if was_trimmed and self.inject_memories_on_trim:
            await self._inject_memories_into_context()

    def get_context_stats(self) -> dict[str, Any]:
        """Get statistics about the current conversation context.

        Returns:
            Dict with context statistics including message count, estimated tokens, etc.
        """
        user_messages = sum(1 for m in self.messages if m.get("role") == "user")
        assistant_messages = sum(1 for m in self.messages if m.get("role") == "assistant")

        # Rough token estimate (4 chars per token average)
        total_chars = sum(len(str(m.get("content", ""))) for m in self.messages)
        estimated_tokens = total_chars // 4

        return {
            "total_messages": len(self.messages),
            "user_messages": user_messages,
            "assistant_messages": assistant_messages,
            "max_messages": self.max_context_messages,
            "estimated_context_tokens": estimated_tokens,
            "total_input_tokens_used": self.total_input_tokens,
            "total_output_tokens_used": self.total_output_tokens,
        }
