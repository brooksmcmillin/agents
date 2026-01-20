"""Multi-agent Slack adapter for routing messages to different agents.

This module provides the MultiAgentSlackAdapter class that enables multiple
Agent subclasses to share a single Slack bot, with intelligent routing
based on keywords, explicit commands, or channel configuration.

Example usage:
    from agent_framework.adapters import MultiAgentSlackAdapter

    adapter = MultiAgentSlackAdapter()

    # Create a callback to post OAuth device authorization URLs to Slack
    # (useful when agents connect to MCP servers requiring OAuth)
    auth_callback = adapter.create_device_auth_callback(
        channel="#bot-auth",
        mention_user="U1234567890"  # Optional: @mention someone
    )

    # Register agents with keywords for automatic routing
    adapter.register_agent(
        name="tasks",
        agent=TaskManagerAgent(
            mcp_urls=["https://mcp.example.com/mcp/"],
            mcp_client_config={
                "prefer_device_flow": True,
                "device_authorization_callback": auth_callback,
            }
        ),
        keywords=["task", "todo", "schedule", "overdue", "deadline"],
        description="Task and schedule management",
    )

    adapter.register_agent(
        name="pr",
        agent=PRReviewAgent(),
        keywords=["pr", "pull request", "review", "github", "code review"],
        description="Pull request reviews",
    )

    # Set a default agent for unmatched messages
    adapter.set_default_agent("tasks")

    # Start the bot
    adapter.start()
"""

import asyncio
import contextlib
import logging
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from ..core.config import settings
from ..oauth.device_flow import DeviceAuthorizationCallback, DeviceAuthorizationInfo

if TYPE_CHECKING:
    from ..core.agent import Agent

logger = logging.getLogger(__name__)

# Default inactivity timeout (24 hours in seconds)
DEFAULT_INACTIVITY_TIMEOUT = 24 * 60 * 60

# Slack message length limit (4000 chars with safety buffer)
SLACK_MAX_MESSAGE_LENGTH = 3900


class RoutingStrategy(Enum):
    """Strategy for routing messages to agents."""

    KEYWORD = "keyword"  # Route based on keywords in message
    EXPLICIT = "explicit"  # Route based on explicit @agent or "ask agent:" patterns
    CHANNEL = "channel"  # Route based on channel ID
    HYBRID = "hybrid"  # Try explicit first, then keywords, then default


@dataclass
class RegisteredAgent:
    """Configuration for a registered agent."""

    name: str
    agent: "Agent"
    keywords: list[str] = field(default_factory=list)
    description: str = ""
    channels: list[str] = field(default_factory=list)  # Channel IDs for channel-based routing


@dataclass
class ConversationContext:
    """Tracks conversation state for a Slack thread or DM, per agent."""

    channel_id: str
    agent_name: str
    thread_ts: str | None = None
    user_id: str | None = None


class MultiAgentSlackAdapter:
    """Adapter that routes Slack messages to multiple agents.

    This adapter enables multiple Agent subclasses to share a single Slack bot by:
    - Registering multiple agents with routing configuration
    - Routing messages based on keywords, explicit commands, or channels
    - Maintaining SEPARATE conversation contexts per agent per thread
    - Each agent has its own conversation history, preventing context pollution

    Conversation Isolation:
        When you ask TaskManager a question, then ask PRAgent a question in the
        same thread, they each maintain separate conversation histories. If you
        return to asking TaskManager, it remembers your previous TaskManager
        conversation in that thread.

        The conversation key is: (channel_id, thread_ts, agent_name)

    Routing Strategies:
        - KEYWORD: Automatically routes based on keywords in the message
        - EXPLICIT: Routes based on patterns like "@tasks" or "ask pr:"
        - CHANNEL: Routes based on which Slack channel the message is in
        - HYBRID: Tries explicit first, then keywords, then default (recommended)

    Example:
        ```python
        adapter = MultiAgentSlackAdapter(routing_strategy=RoutingStrategy.HYBRID)

        adapter.register_agent(
            name="tasks",
            agent=TaskManagerAgent(),
            keywords=["task", "todo", "schedule"],
            description="Manages tasks and schedules",
        )

        adapter.register_agent(
            name="pr",
            agent=PRReviewAgent(),
            keywords=["pr", "pull request", "review"],
            description="Reviews pull requests",
        )

        adapter.set_default_agent("tasks")
        adapter.start()
        ```

    Environment Variables:
        SLACK_BOT_TOKEN: Bot User OAuth Token (xoxb-...)
        SLACK_APP_TOKEN: App-Level Token for Socket Mode (xapp-...)
    """

    def __init__(
        self,
        bot_token: str | None = None,
        app_token: str | None = None,
        routing_strategy: RoutingStrategy = RoutingStrategy.HYBRID,
        respond_to_mentions_only: bool = False,
        use_threads: bool = True,
        show_typing: bool = True,
        inactivity_timeout: int = DEFAULT_INACTIVITY_TIMEOUT,
    ):
        """Initialize the multi-agent Slack adapter.

        Args:
            bot_token: Slack Bot User OAuth Token. If not provided,
                uses SLACK_BOT_TOKEN from environment/settings
            app_token: Slack App-Level Token for Socket Mode. If not provided,
                uses SLACK_APP_TOKEN from environment/settings
            routing_strategy: How to route messages to agents. Default: HYBRID
            respond_to_mentions_only: If True, only respond when @mentioned in channels.
                Always responds to DMs regardless of this setting. Default: False
            use_threads: If True, respond in threads when replying to channel messages.
                Default: True
            show_typing: If True, show typing indicator while processing.
                Default: True
            inactivity_timeout: Seconds of inactivity after which to reset agent context.
                Default: 24 hours (86400 seconds). Set to 0 to disable.
        """
        self.routing_strategy = routing_strategy
        self.respond_to_mentions_only = respond_to_mentions_only
        self.use_threads = use_threads
        self.show_typing = show_typing
        self.inactivity_timeout = inactivity_timeout

        # Get tokens from parameters or settings
        self.bot_token = bot_token or settings.slack_bot_token
        self.app_token = app_token or settings.slack_app_token

        if not self.bot_token:
            raise ValueError(
                "Slack bot token is required. Provide bot_token parameter or set "
                "SLACK_BOT_TOKEN in environment/.env file"
            )

        if not self.app_token:
            raise ValueError(
                "Slack app token is required for Socket Mode. Provide app_token parameter "
                "or set SLACK_APP_TOKEN in environment/.env file"
            )

        # Initialize Slack app
        self.app = App(token=self.bot_token)
        self.client: WebClient = self.app.client

        # Bot info (populated on start)
        self.bot_user_id: str | None = None
        self.bot_name: str | None = None

        # Agent registry
        self.agents: dict[str, RegisteredAgent] = {}
        self.default_agent_name: str | None = None

        # Per-agent conversation contexts: (channel_id, thread_ts, agent_name) -> ConversationContext
        # Each agent gets its own conversation history per thread
        self.conversations: dict[tuple[str, str | None, str], ConversationContext] = defaultdict(
            lambda: ConversationContext(channel_id="", agent_name="", thread_ts=None)
        )

        # Track which agent was last used in each thread (for context continuity)
        self.last_agent_in_thread: dict[tuple[str, str | None], str] = {}

        # Track last activity time per agent per thread for inactivity reset
        # Key: (channel_id, thread_ts, agent_name), Value: timestamp
        self.last_activity: dict[tuple[str, str | None, str], float] = {}

        # Add middleware to log all events
        @self.app.middleware
        def log_all_events(payload: dict[str, Any], body: dict[str, Any], next: Any) -> Any:
            """Log all incoming events for debugging."""
            event = body.get("event", {})
            event_type = event.get("type", "unknown")
            logger.info(f"[MIDDLEWARE] Received event type: {event_type}")
            if event:
                logger.info(
                    f"[MIDDLEWARE] Event details: type={event_type}, "
                    f"subtype={event.get('subtype')}, "
                    f"channel_type={event.get('channel_type')}, "
                    f"user={event.get('user')}, "
                    f"text={event.get('text', '')[:50] if event.get('text') else 'N/A'}"
                )
            return next()

        # Register event handlers
        self._register_handlers()

        logger.info("MultiAgentSlackAdapter initialized")

    def register_agent(
        self,
        name: str,
        agent: "Agent",
        keywords: list[str] | None = None,
        description: str = "",
        channels: list[str] | None = None,
    ) -> None:
        """Register an agent with the adapter.

        Args:
            name: Unique name/alias for the agent (e.g., "tasks", "pr")
                  Used for explicit routing like "@tasks" or "ask tasks:"
            agent: The Agent instance
            keywords: Keywords that trigger this agent (e.g., ["task", "todo"])
            description: Human-readable description of what this agent does
            channels: Channel IDs where this agent should handle all messages
        """
        if name in self.agents:
            logger.warning(f"Overwriting existing agent registration: {name}")

        self.agents[name] = RegisteredAgent(
            name=name,
            agent=agent,
            keywords=keywords or [],
            description=description,
            channels=channels or [],
        )

        logger.info(
            f"Registered agent '{name}' ({agent.get_agent_name()}) with keywords: {keywords or []}"
        )

    def set_default_agent(self, name: str) -> None:
        """Set the default agent for messages that don't match any routing rules.

        Args:
            name: Name of a registered agent to use as default

        Raises:
            ValueError: If the agent name is not registered
        """
        if name not in self.agents:
            raise ValueError(
                f"Agent '{name}' not registered. Available agents: {list(self.agents.keys())}"
            )

        self.default_agent_name = name
        logger.info(f"Set default agent to '{name}'")

    def _register_handlers(self) -> None:
        """Register Slack event handlers."""

        @self.app.event("app_mention")
        def handle_mention(event: dict, say) -> None:
            """Handle @mentions of the bot."""
            logger.info(f"[HANDLER] app_mention event received from user {event.get('user')}")
            self._handle_message_event(event, say, is_mention=True)

        @self.app.event("message")
        def handle_message(event: dict, say) -> None:
            """Handle direct messages and channel messages."""
            logger.info(
                f"[HANDLER] message event received: subtype={event.get('subtype')}, "
                f"channel_type={event.get('channel_type')}, bot_id={event.get('bot_id')}"
            )
            # Skip bot messages to avoid loops
            if event.get("bot_id") or event.get("subtype") == "bot_message":
                logger.info("[HANDLER] Skipping bot message")
                return

            # Skip message_changed and other subtypes
            if event.get("subtype"):
                logger.info(f"[HANDLER] Skipping message with subtype: {event.get('subtype')}")
                return

            self._handle_message_event(event, say, is_mention=False)

    def _route_message(
        self, text: str, channel_id: str, thread_key: tuple[str, str | None]
    ) -> str | None:
        """Determine which agent should handle this message.

        Args:
            text: The message text
            channel_id: The channel ID
            thread_key: Tuple of (channel_id, thread_ts)

        Returns:
            Agent name to use, or None if no agent matches
        """
        text_lower = text.lower()

        if self.routing_strategy == RoutingStrategy.CHANNEL:
            return self._route_by_channel(channel_id)

        if self.routing_strategy == RoutingStrategy.EXPLICIT:
            return self._route_by_explicit(text_lower)

        if self.routing_strategy == RoutingStrategy.KEYWORD:
            return self._route_by_keywords(text_lower)

        # HYBRID: Try explicit first, then keywords, then last agent in thread, then default
        if self.routing_strategy == RoutingStrategy.HYBRID:
            # 1. Try explicit routing
            explicit_agent = self._route_by_explicit(text_lower)
            if explicit_agent:
                return explicit_agent

            # 2. Try keyword routing
            keyword_agent = self._route_by_keywords(text_lower)
            if keyword_agent:
                return keyword_agent

            # 3. Try channel-based routing
            channel_agent = self._route_by_channel(channel_id)
            if channel_agent:
                return channel_agent

            # 4. Use last agent in this thread (conversation continuity)
            if thread_key in self.last_agent_in_thread:
                last_agent = self.last_agent_in_thread[thread_key]
                logger.debug(f"Continuing conversation with last agent: {last_agent}")
                return last_agent

            # 5. Fall back to default
            return self.default_agent_name

        return self.default_agent_name

    def _route_by_explicit(self, text_lower: str) -> str | None:
        """Route based on explicit @agent or 'ask agent:' patterns.

        Patterns recognized:
        - @tasks ...
        - ask tasks: ...
        - tasks: ...
        """
        for agent_name in self.agents:
            patterns = [
                rf"@{agent_name}\b",
                rf"\bask\s+{agent_name}[:\s]",
                rf"^{agent_name}:\s",
            ]
            for pattern in patterns:
                if re.search(pattern, text_lower):
                    logger.debug(f"Explicit routing to '{agent_name}' via pattern: {pattern}")
                    return agent_name

        return None

    def _route_by_keywords(self, text_lower: str) -> str | None:
        """Route based on keywords in the message.

        Uses a scoring system - agent with most keyword matches wins.
        """
        scores: dict[str, int] = {}

        for agent_name, registered in self.agents.items():
            score = 0
            for keyword in registered.keywords:
                # Use word boundary matching for more accurate results
                if re.search(rf"\b{re.escape(keyword)}\b", text_lower):
                    score += 1

            if score > 0:
                scores[agent_name] = score

        if scores:
            winner = max(scores, key=lambda k: scores[k])
            logger.debug(f"Keyword routing to '{winner}' with score {scores[winner]}")
            return winner

        return None

    def _route_by_channel(self, channel_id: str) -> str | None:
        """Route based on channel ID."""
        for agent_name, registered in self.agents.items():
            if channel_id in registered.channels:
                logger.debug(f"Channel routing to '{agent_name}' for channel {channel_id}")
                return agent_name

        return None

    def _check_and_reset_inactive_agent(
        self,
        channel_id: str,
        thread_ts: str | None,
        agent_name: str,
    ) -> bool:
        """Check if agent context should be reset due to inactivity.

        Args:
            channel_id: The channel ID
            thread_ts: The thread timestamp
            agent_name: The agent name

        Returns:
            True if context was reset due to inactivity
        """
        if self.inactivity_timeout <= 0:
            return False

        context_key = (channel_id, thread_ts, agent_name)
        last_time = self.last_activity.get(context_key)

        if last_time is None:
            return False

        elapsed = time.time() - last_time
        if elapsed > self.inactivity_timeout:
            logger.info(
                f"Resetting '{agent_name}' context due to inactivity "
                f"({elapsed / 3600:.1f} hours since last activity)"
            )
            # Reset this specific agent's conversation
            if agent_name in self.agents:
                self.agents[agent_name].agent.reset_conversation()

            # Clean up tracking
            if context_key in self.conversations:
                del self.conversations[context_key]
            if context_key in self.last_activity:
                del self.last_activity[context_key]

            return True

        return False

    def _handle_special_commands(
        self,
        text: str,
        channel_id: str,
        thread_ts: str | None,
    ) -> str | None:
        """Handle special commands like /reset, /agents, /stats.

        Args:
            text: The message text
            channel_id: The channel ID
            thread_ts: The thread timestamp

        Returns:
            Response string if command was handled, None otherwise
        """
        text_lower = text.lower().strip()

        # /reset or reset - Reset all agent contexts in this thread
        if text_lower in ["/reset", "reset", "/clear", "clear"]:
            self.reset_conversation(channel_id, thread_ts)
            return "Context cleared for all agents in this conversation. Starting fresh!"

        # /reset @agent - Reset specific agent
        reset_match = re.match(r"(?:/reset|reset)\s+@?(\w+)", text_lower)
        if reset_match:
            agent_name = reset_match.group(1)
            if agent_name in self.agents:
                self.reset_conversation(channel_id, thread_ts, agent_name=agent_name)
                return f"Context cleared for *{agent_name}*. Starting fresh!"
            return f"Agent '{agent_name}' not found. Available: {', '.join(self.agents.keys())}"

        # /agents - List available agents
        if text_lower in ["/agents", "agents", "/help", "help"]:
            return self.list_agents()

        # /stats - Show context statistics
        if text_lower in ["/stats", "stats"]:
            return self._get_stats_message()

        return None

    def _get_stats_message(self) -> str:
        """Get a formatted stats message."""
        lines = ["**Agent Context Statistics:**\n"]

        for name, registered in self.agents.items():
            agent = registered.agent
            stats = agent.get_context_stats()
            lines.append(f"**{name}** ({registered.description or agent.get_agent_name()}):")
            lines.append(
                f"  • Messages in context: {stats['total_messages']}/{stats['max_messages'] or 'unlimited'}"
            )
            lines.append(f"  • Estimated tokens: ~{stats['estimated_context_tokens']:,}")
            lines.append(
                f"  • Total tokens used: {stats['total_input_tokens_used'] + stats['total_output_tokens_used']:,}"
            )
            lines.append("")

        return "\n".join(lines)

    def _handle_message_event(self, event: dict, say, is_mention: bool = False) -> None:
        """Process a message event from Slack.

        Args:
            event: The Slack event payload
            say: The Slack say function for sending responses
            is_mention: Whether this is an @mention event
        """
        # Skip bot messages to avoid loops
        if event.get("bot_id") or event.get("subtype") == "bot_message":
            logger.debug("Ignoring bot message")
            return

        channel_id = event.get("channel", "")
        user_id = event.get("user", "")
        text = event.get("text", "")
        thread_ts = event.get("thread_ts") or event.get("ts")
        channel_type = event.get("channel_type", "")

        # Determine if this is a DM
        is_dm = channel_type == "im"

        # In channels, check if we should respond
        if not is_dm and not is_mention and self.respond_to_mentions_only:
            logger.debug(f"Ignoring non-mention message in channel {channel_id}")
            return

        # Remove bot mention from text if present
        if self.bot_user_id:
            text = re.sub(rf"<@{self.bot_user_id}>", "", text).strip()

        if not text:
            logger.debug("Ignoring empty message after mention removal")
            return

        # Determine thread_ts for response
        if is_dm:
            response_thread_ts = event.get("thread_ts")
        else:
            response_thread_ts = thread_ts if self.use_threads else None

        # Check for special commands first (/reset, /agents, /stats)
        command_response = self._handle_special_commands(text, channel_id, response_thread_ts)
        if command_response:
            self._send_response(channel_id, command_response, response_thread_ts)
            return

        # Route to appropriate agent
        thread_key = (channel_id, response_thread_ts)
        agent_name = self._route_message(text, channel_id, thread_key)

        if not agent_name or agent_name not in self.agents:
            logger.warning(f"No agent found for message, using default: {self.default_agent_name}")
            agent_name = self.default_agent_name

        if not agent_name or agent_name not in self.agents:
            # No agents registered or no default set
            self._send_response(
                channel_id,
                "I'm not sure how to help with that. No agent is configured to handle this type of request.",
                response_thread_ts,
            )
            return

        registered_agent = self.agents[agent_name]
        agent = registered_agent.agent

        logger.info(f"Routing message to '{agent_name}' ({agent.get_agent_name()}): {text[:50]}...")

        # Check for inactivity and reset if needed
        was_reset = self._check_and_reset_inactive_agent(channel_id, response_thread_ts, agent_name)
        if was_reset:
            logger.info(f"Agent '{agent_name}' context was reset due to inactivity")

        # Update last agent in thread for conversation continuity
        self.last_agent_in_thread[thread_key] = agent_name

        # Get or create conversation context for this specific agent in this thread
        context_key = (channel_id, response_thread_ts, agent_name)
        if context_key not in self.conversations:
            self.conversations[context_key] = ConversationContext(
                channel_id=channel_id,
                agent_name=agent_name,
                thread_ts=response_thread_ts,
                user_id=user_id,
            )

        # Update last activity time
        self.last_activity[context_key] = time.time()

        # Show typing indicator if enabled
        if self.show_typing:
            with contextlib.suppress(SlackApiError):
                self.client.chat_postMessage(
                    channel=channel_id,
                    text="...",
                    thread_ts=response_thread_ts,
                    metadata={"event_type": "typing_indicator", "event_payload": {}},
                )

        # Process message with the routed agent
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                # Remove explicit agent routing prefix from message before sending to agent
                clean_text = self._remove_routing_prefix(text, agent_name)
                response = loop.run_until_complete(agent.process_message(clean_text))
            finally:
                loop.close()

            # Optionally prefix response with agent indicator
            # response = f"[{agent_name}] {response}"  # Uncomment to show which agent responded

            self._send_response(channel_id, response, response_thread_ts)
            logger.info(f"Sent response from '{agent_name}' to channel {channel_id}")

        except Exception as e:
            logger.exception(f"Error processing message with '{agent_name}': {e}")
            error_message = (
                f"I encountered an error while processing your request with {agent_name}. "
                "Please try again."
            )
            self._send_response(channel_id, error_message, response_thread_ts)

    def _remove_routing_prefix(self, text: str, agent_name: str) -> str:
        """Remove explicit routing patterns from the message.

        Args:
            text: The original message text
            agent_name: The agent being routed to

        Returns:
            Text with routing prefixes removed
        """
        # Remove patterns like "@tasks", "ask tasks:", "tasks:"
        patterns = [
            rf"@{agent_name}\s*",
            rf"\bask\s+{agent_name}[:\s]+",
            rf"^{agent_name}:\s*",
        ]

        result = text
        for pattern in patterns:
            result = re.sub(pattern, "", result, flags=re.IGNORECASE).strip()

        return result or text

    def _send_response(self, channel_id: str, text: str, thread_ts: str | None = None) -> None:
        """Send a response to Slack, handling long messages."""
        if len(text) <= SLACK_MAX_MESSAGE_LENGTH:
            self._post_message(channel_id, text, thread_ts)
        else:
            parts = self._split_message(text, SLACK_MAX_MESSAGE_LENGTH)
            for i, part in enumerate(parts):
                if i > 0:
                    part = f"_(continued)_\n{part}"
                self._post_message(channel_id, part, thread_ts)

    def _post_message(self, channel_id: str, text: str, thread_ts: str | None = None) -> None:
        """Post a single message to Slack."""
        try:
            kwargs: dict = {
                "channel": channel_id,
                "text": text,
                "mrkdwn": True,
            }
            if thread_ts:
                kwargs["thread_ts"] = thread_ts

            self.client.chat_postMessage(**kwargs)

        except SlackApiError as e:
            logger.error(f"Failed to send message to Slack: {e}")
            raise

    def _split_message(self, text: str, max_length: int) -> list[str]:
        """Split a long message into parts at paragraph boundaries.

        TODO: Refactor this method - cyclomatic complexity is 15.
        Consider extracting:
        - _can_fit(current, new, max_len) for length checking
        - _append_paragraph(current, paragraph) for paragraph appending
        - _split_oversized_paragraph(paragraph, max_len) for large paragraphs
        - _split_by_sentences(sentences, max_len) for sentence-level splitting
        - _split_by_chars(text, max_len) for character-level splitting
        See code optimizer report for detailed recommendations.
        """
        parts = []
        current_part = ""

        paragraphs = text.split("\n\n")

        for paragraph in paragraphs:
            if len(current_part) + len(paragraph) + 2 > max_length:
                if current_part:
                    parts.append(current_part.strip())
                    current_part = ""

                if len(paragraph) > max_length:
                    sentences = re.split(r"(?<=[.!?])\s+", paragraph)
                    for sentence in sentences:
                        if len(sentence) > max_length:
                            while len(sentence) > max_length:
                                if current_part:
                                    parts.append(current_part.strip())
                                    current_part = ""
                                parts.append(sentence[:max_length])
                                sentence = sentence[max_length:]
                            if sentence:
                                current_part = sentence
                        elif len(current_part) + len(sentence) + 1 > max_length:
                            if current_part:
                                parts.append(current_part.strip())
                            current_part = sentence
                        else:
                            current_part += (" " if current_part else "") + sentence
                else:
                    current_part = paragraph
            else:
                current_part += ("\n\n" if current_part else "") + paragraph

        if current_part:
            parts.append(current_part.strip())

        return parts

    def _fetch_bot_info(self) -> None:
        """Fetch and store bot user information."""
        try:
            response = self.client.auth_test()
            self.bot_user_id = response.get("user_id")
            self.bot_name = response.get("user")
            logger.info(f"Bot connected as @{self.bot_name} (ID: {self.bot_user_id})")
        except SlackApiError as e:
            logger.error(f"Failed to fetch bot info: {e}")
            raise

    def list_agents(self) -> str:
        """Get a formatted list of registered agents and their capabilities.

        Returns:
            Human-readable string listing all agents
        """
        if not self.agents:
            return "No agents registered."

        lines = ["**Available Agents:**\n"]
        for name, registered in self.agents.items():
            default_marker = " (default)" if name == self.default_agent_name else ""
            lines.append(f"• **{name}**{default_marker}: {registered.description}")
            if registered.keywords:
                lines.append(f"  Keywords: {', '.join(registered.keywords)}")

        lines.append("\n**Routing Tips:**")
        lines.append(
            "• Explicitly route with: `@agent_name your message` or `ask agent_name: your message`"
        )
        lines.append("• Or just ask naturally - I'll route based on keywords")

        return "\n".join(lines)

    def create_device_auth_callback(
        self,
        channel: str,
        mention_user: str | None = None,
    ) -> DeviceAuthorizationCallback:
        """Create a callback that posts device authorization URLs to Slack.

        Use this to notify users via Slack when an MCP server requires OAuth
        authorization. Pass the returned callback to your Agent's mcp_client_config.

        Args:
            channel: Slack channel ID or name
                to post authorization notifications to.
            mention_user: Optional Slack user ID to @mention in the notification
                (e.g., "U1234567890"). If provided, the user will be pinged.

        Returns:
            A callback function compatible with device_authorization_callback.

        Example:
            ```python
            adapter = MultiAgentSlackAdapter()

            # Create callback that posts to #bot-auth channel
            auth_callback = adapter.create_device_auth_callback(
                channel="#bot-auth",
                mention_user="U1234567890"  # Optional: @mention a user
            )

            # Pass to agent via mcp_client_config
            agent = MyAgent(
                mcp_urls=["https://mcp.example.com/mcp/"],
                mcp_client_config={
                    "prefer_device_flow": True,
                    "device_authorization_callback": auth_callback,
                }
            )

            adapter.register_agent("myagent", agent)
            ```
        """

        def callback(info: DeviceAuthorizationInfo) -> None:
            """Post device authorization info to Slack."""
            # Build the message
            mention = f"<@{mention_user}> " if mention_user else ""
            url = info.verification_uri_complete or info.verification_uri

            blocks = [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": "Authorization Required",
                    },
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            f"{mention}An MCP server requires authorization.\n\n"
                            f"*Click the link below to authorize:*"
                        ),
                    },
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"<{url}|Authorize Now>",
                    },
                },
            ]

            # Add manual code entry option if there's a separate verification_uri
            if (
                info.verification_uri_complete
                and info.verification_uri != info.verification_uri_complete
            ):
                blocks.append(
                    {
                        "type": "context",
                        "elements": [
                            {
                                "type": "mrkdwn",
                                "text": (
                                    f"Or visit `{info.verification_uri}` "
                                    f"and enter code: `{info.user_code}`"
                                ),
                            }
                        ],
                    }
                )

            blocks.append(
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f"This code expires in {info.expires_minutes} minutes.",
                        }
                    ],
                }
            )

            # Fallback text for notifications
            fallback_text = (
                f"Authorization required. Visit {url} "
                f"(code: {info.user_code}, expires in {info.expires_minutes} min)"
            )

            try:
                self.client.chat_postMessage(
                    channel=channel,
                    text=fallback_text,
                    blocks=blocks,
                )
                logger.info(f"Posted device authorization notification to {channel}")
            except SlackApiError as e:
                logger.error(f"Failed to post device auth notification to Slack: {e}")

        return callback

    def reset_conversation(
        self,
        channel_id: str,
        thread_ts: str | None = None,
        agent_name: str | None = None,
    ) -> None:
        """Reset conversation context for a channel/thread.

        Args:
            channel_id: The channel ID
            thread_ts: Optional thread timestamp
            agent_name: If provided, only reset that agent's context.
                       If None, reset all agents in this thread.
        """
        if agent_name:
            # Reset specific agent's context
            context_key = (channel_id, thread_ts, agent_name)
            if context_key in self.conversations:
                del self.conversations[context_key]

            if agent_name in self.agents:
                self.agents[agent_name].agent.reset_conversation()

            logger.info(
                f"Reset conversation for agent '{agent_name}' in channel {channel_id}, "
                f"thread {thread_ts}"
            )
        else:
            # Reset all agents in this thread
            keys_to_delete = [
                key for key in self.conversations if key[0] == channel_id and key[1] == thread_ts
            ]
            for key in keys_to_delete:
                del self.conversations[key]

            # Reset all agents
            for registered in self.agents.values():
                registered.agent.reset_conversation()

            # Clear last agent tracking
            thread_key = (channel_id, thread_ts)
            if thread_key in self.last_agent_in_thread:
                del self.last_agent_in_thread[thread_key]

            logger.info(f"Reset all conversations in channel {channel_id}, thread {thread_ts}")

    def start(self) -> None:
        """Start the Slack bot using Socket Mode.

        This method blocks and runs the bot until interrupted.
        """
        if not self.agents:
            raise ValueError("No agents registered. Use register_agent() before starting.")

        if not self.default_agent_name:
            # Use first registered agent as default
            self.default_agent_name = next(iter(self.agents))
            logger.warning(f"No default agent set, using '{self.default_agent_name}'")

        logger.info("Starting Multi-Agent Slack bot...")

        # Fetch bot info
        self._fetch_bot_info()

        # Print startup banner
        print("\n" + "=" * 60)
        print("MULTI-AGENT SLACK BOT")
        print("=" * 60)
        print(f"Bot User: @{self.bot_name}")
        print(f"Bot ID: {self.bot_user_id}")
        print(f"Routing Strategy: {self.routing_strategy.value}")
        print(f"Default Agent: {self.default_agent_name}")
        print(f"\nRegistered Agents ({len(self.agents)}):")
        for name, registered in self.agents.items():
            keywords_str = ", ".join(registered.keywords[:5])
            if len(registered.keywords) > 5:
                keywords_str += f", ... (+{len(registered.keywords) - 5} more)"
            print(f"  • {name}: {registered.description or registered.agent.get_agent_name()}")
            if keywords_str:
                print(f"    Keywords: {keywords_str}")
        print("\nPress Ctrl+C to stop the bot")
        print("=" * 60 + "\n")

        # Start Socket Mode handler
        handler = SocketModeHandler(self.app, self.app_token)

        try:
            handler.start()
        except KeyboardInterrupt:
            print("\n\nShutting down Multi-Agent Slack bot...")
            handler.close()
            print("Goodbye!")
