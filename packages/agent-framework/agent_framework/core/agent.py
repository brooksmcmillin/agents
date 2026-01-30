"""Base agent class for building LLM agents with MCP tools.

This module provides the foundational Agent class that handles:
- Conversation management
- Tool execution via MCP
- Token usage tracking
- Interactive CLI interface
"""

import asyncio
import json
import logging
import os
import select
import sys
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Any, TextIO, cast

from anthropic import AsyncAnthropic
from anthropic.types import (
    MessageParam,
    ServerToolUseBlock,
    TextBlock,
    ToolParam,
    ToolUseBlock,
    WebSearchToolResultBlock,
)
from dotenv import load_dotenv

from agent_framework.utils.errors import MissingAPIKeyError

from .config import settings
from .mcp_client import MCPClient
from .remote_mcp_client import RemoteMCPClient

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
    from ..security import LakeraSecurityResult
    from ..utils.errors import PromptInjectionError

    SECURITY_AVAILABLE = True
except ImportError:
    SECURITY_AVAILABLE = False
    _LakeraGuard = None
    LakeraSecurityResult = None  # type: ignore[misc]
    PromptInjectionError = None  # type: ignore[misc]

# Load environment variables
load_dotenv()

# Constants for agent behavior
MAX_AGENT_ITERATIONS = 10  # Maximum iterations in agentic loop to prevent infinite loops
WEB_SEARCH_MAX_USES = 10  # Maximum web searches allowed per turn (Anthropic API limit)
HIGH_IMPORTANCE_THRESHOLD = 7  # Minimum importance level for memory injection
MAX_INJECTED_MEMORIES = 10  # Maximum memories to inject after context trimming

# Memory tools that should have agent_name auto-injected for isolation
MEMORY_TOOLS = frozenset({
    "save_memory",
    "get_memories",
    "search_memories",
    "delete_memory",
    "get_memory_stats",
})

# Agent email tools that should have agent_name auto-injected
AGENT_EMAIL_TOOLS = frozenset({
    "send_agent_report",
})

# Module-level logger (will be configured per-agent)
logger = logging.getLogger(__name__)


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


class _StderrToLogFile:
    """Wrapper that redirects stderr to a log file only (not console).

    This captures stderr output (from subprocesses, exceptions, etc.) and
    writes it only to the log file, keeping the console clean. The original
    stderr is preserved for fileno() and isatty() compatibility but writes
    are not echoed to it.
    """

    def __init__(self, log_file_path: Path, original_stderr: TextIO | None):
        self.log_file_path = log_file_path
        self.original_stderr = original_stderr
        self._log_file = None

    def _ensure_file_open(self) -> None:
        """Open log file lazily."""
        import contextlib

        if self._log_file is None:
            with contextlib.suppress(OSError):
                self._log_file = open(  # noqa: SIM115
                    self.log_file_path, "a", encoding="utf-8"
                )

    def write(self, data: str) -> None:
        """Write to log file only (not echoed to console)."""
        import contextlib

        # Write only to log file - do NOT echo to console
        self._ensure_file_open()
        if self._log_file:
            with contextlib.suppress(OSError):
                self._log_file.write(data)
                self._log_file.flush()

    def flush(self) -> None:
        """Flush the log file stream."""
        import contextlib

        if self._log_file:
            with contextlib.suppress(OSError):
                self._log_file.flush()

    def fileno(self) -> int:
        """Return file descriptor of original stderr."""
        if self.original_stderr:
            return self.original_stderr.fileno()
        raise OSError("No stderr available")

    def isatty(self) -> bool:
        """Check if original stderr is a tty."""
        if self.original_stderr:
            return self.original_stderr.isatty()
        return False

    def close(self) -> None:
        """Close the log file (but not original stderr)."""
        import contextlib

        if self._log_file:
            with contextlib.suppress(OSError):
                self._log_file.close()
            self._log_file = None


# Global reference to stderr wrapper for cleanup
_stderr_wrapper: _StderrToLogFile | None = None


def setup_logging(
    agent_name: str,
    console_level: int = logging.WARNING,
    file_level: int = logging.DEBUG,
    redirect_stderr: bool = True,
) -> logging.Logger:
    """
    Set up logging with both file and console handlers.

    Args:
        agent_name: Name of the agent (used for log file name)
        console_level: Log level for console output (default: WARNING)
        file_level: Log level for file output (default: DEBUG)
        redirect_stderr: If True, redirect sys.stderr to also write to log file (default: True)

    Returns:
        Configured logger instance
    """
    global _stderr_wrapper

    # Get log file path using settings helper
    log_file = settings.get_log_file(agent_name)

    # Get the root logger for agent_framework
    agent_logger = logging.getLogger("agent_framework")
    agent_logger.setLevel(logging.DEBUG)  # Capture all levels
    agent_logger.propagate = False  # Don't propagate to root logger (prevents duplicate output)

    # Remove existing handlers to avoid duplicates on reload
    agent_logger.handlers.clear()

    # File handler - captures all debug info
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(file_level)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )
    agent_logger.addHandler(file_handler)

    # Console handler - only important messages
    console_handler = logging.StreamHandler()
    console_handler.setLevel(console_level)
    console_handler.setFormatter(logging.Formatter("%(message)s"))
    agent_logger.addHandler(console_handler)

    # Also configure httpx and mcp loggers to file only
    for lib_logger_name in ["httpx", "mcp", "mcp_server"]:
        lib_logger = logging.getLogger(lib_logger_name)
        lib_logger.setLevel(logging.DEBUG)
        lib_logger.handlers.clear()
        lib_logger.addHandler(file_handler)
        lib_logger.propagate = False

    # Redirect sys.stderr to also write to log file
    if redirect_stderr:
        import sys

        # Only wrap if not already wrapped
        if not isinstance(sys.stderr, _StderrToLogFile):
            _stderr_wrapper = _StderrToLogFile(log_file, sys.stderr)
            sys.stderr = _stderr_wrapper  # type: ignore[assignment]
            agent_logger.debug("sys.stderr redirected to log file")

    agent_logger.info(f"Logging initialized. Log file: {log_file}")

    return agent_logger


class InvalidToolName(Exception):
    def __init__(self, message: str):
        super().__init__(f"{message} tool not found!")


class Agent(ABC):
    """
    Base agent class using Claude and MCP tools.

    This class provides the core agentic loop that:
    1. Accepts user requests
    2. Calls Claude via Anthropic SDK
    3. Executes MCP tools as needed
    4. Processes results and continues until done

    Subclasses should override:
    - get_system_prompt(): Return the system prompt for the agent
    - get_greeting(): Return the greeting message shown to users (optional)
    - get_agent_name(): Return the agent name for display (optional)
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "claude-sonnet-4-5-20250929",
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
        self.tools: dict[str, list[str]] = {}

        # Context management
        self.max_context_messages = max_context_messages
        self.inject_memories_on_trim = inject_memories_on_trim

        # Initialize Anthropic client
        self.client = AsyncAnthropic(api_key=self.api_key)

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
                logger.debug("Lakera Guard not enabled: LAKERA_API_KEY not configured")

        # Conversation history
        self.messages: list[MessageParam] = []

        # Token usage tracking
        self.total_input_tokens = 0
        self.total_output_tokens = 0

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
        )

    async def _call_mcp_tool_with_reconnect(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Call an MCP tool with automatic reconnection.

        This allows the MCP server to be restarted between calls
        without losing the agent's conversation context.

        For memory tools, automatically injects the agent_name parameter
        to ensure memory isolation between different agents.

        Args:
            tool_name: Name of the tool to call
            arguments: Tool arguments

        Returns:
            Tool result
        """
        # Auto-inject agent_name for memory tools and agent email tools
        if tool_name in MEMORY_TOOLS or tool_name in AGENT_EMAIL_TOOLS:
            # Only inject if not already specified (allow explicit override)
            if "agent_name" not in arguments:
                arguments = {**arguments, "agent_name": self.get_agent_name()}
                logger.debug(
                    f"Auto-injected agent_name='{self.get_agent_name()}' for {tool_name}"
                )

        # Local tools should take precedence over remote tools if there are any name collisions.
        # TODO: Throw an error if there are name collisions?
        if tool_name in self.tools["local"]:
            async with self.mcp_client.connect():
                return await self.mcp_client.call_tool(tool_name, arguments)

        for url in self.mcp_urls:
            async with self._create_remote_mcp_client(url) as mcp:
                result = await mcp.call_tool(tool_name, arguments)

                # Handle result - could be string or dict
                if isinstance(result, str):
                    try:
                        # Try to parse as JSON
                        result_dict = json.loads(result)
                        return result_dict
                    except json.JSONDecodeError:
                        return {"result": result}
                else:
                    return result

        # If the tool isn't found, raise an exception.
        raise InvalidToolName(tool_name)

    async def _get_available_tools(self) -> list[str]:
        """Get list of available MCP tools (reconnects to server)."""

        # Get tools from local MCP server
        async with self.mcp_client.connect():
            self.tools["local"] = self.mcp_client.get_available_tools()

        # Get tools from remote MCP server(s) if applicable
        logger.debug("Getting available remote tools.")
        for url in self.mcp_urls:
            logger.debug(f"Getting tools from {url}")
            async with self._create_remote_mcp_client(url) as mcp:
                mcp_tools = await mcp.list_tools()
                self.tools[url] = [tool["name"] for tool in mcp_tools]

        # Return the concatenation of all the tool lists
        return [item for lst in self.tools.values() for item in lst]

    async def start(self) -> None:
        """Start an interactive session with the agent.

        TODO: Refactor this method - cyclomatic complexity is 13.
        Consider extracting:
        - _print_startup_banner() for the startup message
        - _discover_and_test_tools() for tool discovery
        - _test_remote_connection(url) for individual URL testing
        - _run_interactive_loop() for the main REPL
        - _handle_special_command(input) for exit/stats/reload commands
        See code optimizer report for detailed recommendations.
        """
        import uuid

        # Generate session ID for this CLI session (for observability tracing)
        cli_session_id = f"cli-{uuid.uuid4().hex[:12]}"
        logger.info(
            f"Starting {self.get_agent_name()} interactive session (session: {cli_session_id})"
        )

        print("\n" + "=" * 70)
        print(self.get_agent_name().upper())
        print("=" * 70)
        print(self.get_greeting())
        print("\nType 'exit' or 'quit' to end the session.")
        print("Type 'stats' to see token usage statistics.")
        print("Type 'reload' to reconnect to MCP server and discover updated tools.")
        print(f"\nLogs: {self.log_file}")
        if self._observability_enabled:
            print(f"Session: {cli_session_id}")
        print("=" * 70 + "\n")

        # Discover available tools (will reconnect each time we need them)
        try:
            tools_list = await self._get_available_tools()
            logger.info(f"Discovered MCP tools: {tools_list}")
        except Exception as e:
            logger.error(f"Failed to connect to MCP server: {e}")
            print(f"\n⚠️  Warning: Could not connect to MCP server: {e}")
            print("Make sure the MCP server is running and try again.\n")

        # Test remote MCP connection(s)
        for url in self.mcp_urls:
            try:
                print(f"🔌 Connecting to remote MCP server {url}...", flush=True)
                async with self._create_remote_mcp_client(url) as mcp:
                    tools = await asyncio.wait_for(mcp.list_tools(), timeout=10.0)
                    logger.info(f"Connected to MCP server with {len(tools)} tools")
                    print(f"✅ Connected to {url}")
                    print(f"✅ Found {len(tools)} tools\n", flush=True)
            except TimeoutError:
                print(f"❌ Timeout while connecting to MCP server at {url}")
                print("The connection was established but listing tools timed out.")
                return
            except Exception as e:
                print(f"❌ Failed to connect to MCP server at {url}")
                print(f"Error: {e}")
                print("\nPlease ensure:")
                print("1. The MCP server is running")
                print("2. The URL is correct")
                print("3. The server is accessible")
                return

        # Main interaction loop
        while True:
            try:
                # Get user input (supports multiline paste)
                user_input = _read_multiline_input("\nYou: ").strip()

                if not user_input:
                    continue

                # Handle special commands
                if user_input.lower() in ["exit", "quit"]:
                    print("\nGoodbye! 👋")
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

                # Process user message
                response = await self.process_message(user_input, session_id=cli_session_id)

                # Display response
                print(f"\nAssistant: {response}")

            except KeyboardInterrupt:
                print("\n\nSession interrupted. Goodbye! 👋")
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
    ) -> str:
        """
        Process a user message and return the agent's response.

        This implements the agentic loop:
        1. Manage context (trim if needed, inject memories)
        2. Add user message to conversation
        3. Call Claude with available tools
        4. Execute any tool calls via MCP
        5. Continue until Claude provides a final response

        Args:
            user_message: The user's input message
            user_id: Optional user ID for observability tracing
            session_id: Optional session/conversation ID for observability tracing

        Returns:
            The agent's response as a string
        """
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
            return await self._process_message_internal(user_message, trace_ctx)
        except BaseException:
            import sys

            exc_info = sys.exc_info()
            raise
        finally:
            if trace_ctx is not None and exc_info is not None:
                trace_ctx.__exit__(*exc_info)
            elif trace_ctx is not None:
                trace_ctx.__exit__(None, None, None)

    async def _process_message_internal(self, user_message: str, trace_ctx) -> str:
        """Internal message processing with observability context.

        Args:
            user_message: The user's input message
            trace_ctx: Optional TraceContext for observability

        Returns:
            The agent's response as a string
        """
        # Manage context before processing (trim old messages, inject memories if needed)
        await self._manage_context()

        # Security check: Screen user input for prompt injection and other threats
        if self.security_guard is not None:
            security_result = await self.security_guard.check_input(user_message)
            if security_result.flagged:
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
                # Call Claude
                response = await self.client.messages.create(
                    model=self.model,
                    max_tokens=16000,
                    system=self.get_system_prompt(),
                    messages=self.messages,
                    tools=cast(list[ToolParam], tools),
                )

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

                    # Add assistant response to conversation (with tool calls)
                    # Note: tool_use responses should always have content, but ensure non-empty
                    self.messages.append(
                        {
                            "role": "assistant",
                            "content": self._ensure_non_empty_content(response.content),
                        }
                    )

                    # Execute tool calls and collect results
                    tool_results = []
                    for tool_call in tool_calls:
                        logger.info(f"Executing tool: {tool_call.name}")

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
                                    "content": str(result),
                                }
                            )

                        except PermissionError as e:
                            # Handle auth errors
                            logger.warning(f"Authentication error for {tool_call.name}: {e}")
                            tool_span_exc_info = (type(e), e, e.__traceback__)

                            # End tool span with error
                            if tool_span is not None:
                                tool_span.end(
                                    output=f"Authentication required: {e}",
                                    level="ERROR",
                                    metadata={"error_type": "PermissionError"},
                                )

                            tool_results.append(
                                {
                                    "type": "tool_result",
                                    "tool_use_id": tool_call.id,
                                    "content": f"Authentication required: {e}",
                                    "is_error": True,
                                }
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

                            tool_results.append(
                                {
                                    "type": "tool_result",
                                    "tool_use_id": tool_call.id,
                                    "content": f"Tool execution failed: {e}",
                                    "is_error": True,
                                }
                            )

                        finally:
                            # Always close the tool span context manager
                            if tool_span is not None:
                                if tool_span_exc_info is not None:
                                    tool_span.__exit__(*tool_span_exc_info)
                                else:
                                    tool_span.__exit__(None, None, None)

                    # Add tool results to conversation
                    self.messages.append(
                        {
                            "role": "user",
                            "content": tool_results,
                        }
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
        for url in self.mcp_urls:
            logger.debug(f"Checking Remote MCP Server: {url}")
            async with self._create_remote_mcp_client(url) as mcp:
                mcp_tools = await mcp.list_tools()

                # Populate self.tools[url] for tool routing
                self.tools[url] = [tool["name"] for tool in mcp_tools]

                # Convert to Anthropic format
                anthropic_tools += [
                    {
                        "name": tool["name"],
                        "description": tool["description"],
                        "input_schema": tool["input_schema"],
                    }
                    for tool in mcp_tools
                ]

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

    def _trim_context_if_needed(self) -> bool:
        """Trim conversation context if it exceeds max_context_messages.

        Returns:
            True if context was trimmed, False otherwise
        """
        if self.max_context_messages is None:
            return False

        if len(self.messages) <= self.max_context_messages:
            return False

        # Calculate how many messages to remove
        messages_to_remove = len(self.messages) - self.max_context_messages

        # Remove oldest messages
        self.messages = self.messages[messages_to_remove:]

        logger.info(
            f"Trimmed context: removed {messages_to_remove} old messages, "
            f"keeping {len(self.messages)} messages"
        )

        return True

    async def _inject_memories_into_context(self) -> None:
        """Inject high-importance memories into the conversation context.

        This helps preserve key information after context trimming.
        Memories are injected as a system-style user message.
        Uses the agent's name for memory isolation.
        """
        try:
            from ..tools.memory import get_memory_store

            # Use agent's name for memory isolation
            store = get_memory_store(agent_name=self.get_agent_name())
            # Get high-importance memories for this specific agent
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
