"""Example Slack Bot Agent using the MultiAgentSlackAdapter.

This example demonstrates how to create a Slack bot using the MultiAgentSlackAdapter
to connect Agent subclasses to Slack via Socket Mode.

Setup:
    1. Create a Slack App at https://api.slack.com/apps
    2. Enable Socket Mode in your app settings
    3. Add the following Bot Token Scopes:
       - app_mentions:read
       - channels:history
       - chat:write
       - groups:history
       - im:history
       - im:write
       - users:read
    4. Install the app to your workspace
    5. Set environment variables:
       - SLACK_BOT_TOKEN: Bot User OAuth Token (xoxb-...)
       - SLACK_APP_TOKEN: App-Level Token (xapp-...)
       - ANTHROPIC_API_KEY: Your Anthropic API key

Usage:
    python examples/slack_bot_agent.py

The bot will:
    - Respond to @mentions in channels
    - Respond to direct messages
    - Maintain conversation context within threads
    - Use Claude to generate intelligent responses
    - Route messages to appropriate agents based on keywords
"""

from agent_framework import Agent, MultiAgentSlackAdapter, RoutingStrategy


class SlackAssistant(Agent):
    """A helpful Slack assistant powered by Claude.

    This agent is designed specifically for Slack conversations,
    with a system prompt optimized for chat-style interactions.
    """

    def get_system_prompt(self) -> str:
        return """You are a helpful Slack assistant powered by Claude.

Your role is to help team members with questions, tasks, and discussions.

Guidelines for Slack conversations:
1. Keep responses concise and scannable - Slack is fast-paced
2. Use bullet points and formatting when listing information
3. Break up long responses into digestible paragraphs
4. Use code blocks (```) for code snippets
5. Be friendly but professional

You have access to various tools including:
- Web search for finding current information
- Memory for remembering important facts from conversations
- Web reading for fetching content from URLs

When users ask questions:
- Provide direct, actionable answers
- Offer to elaborate if the topic is complex
- Cite sources when sharing factual information

Remember that Slack conversations are often collaborative, so be ready to:
- Clarify when asked follow-up questions
- Adjust your responses based on feedback
- Help facilitate team discussions"""

    def get_agent_name(self) -> str:
        return "Slack Assistant"

    def get_greeting(self) -> str:
        return "Hello! I'm your Slack Assistant. How can I help?"


class SlackResearchBot(Agent):
    """A research-focused Slack bot with web search capabilities.

    This agent specializes in finding and synthesizing information
    from the web to answer research questions in Slack.
    """

    def get_system_prompt(self) -> str:
        return """You are a research assistant bot for Slack with web search capabilities.

Your specialty is:
1. Finding accurate, up-to-date information
2. Synthesizing multiple sources
3. Providing well-cited responses
4. Answering technical and factual questions

When answering research questions:
- Always search the web for current information
- Cite your sources with links
- Distinguish between facts and opinions
- Acknowledge uncertainty when appropriate

For Slack formatting:
- Use bullet points for lists
- Use bold for emphasis on key points
- Include source links at the end
- Keep initial responses brief, offer to expand"""

    def get_agent_name(self) -> str:
        return "Research Bot"


class SlackCodeHelper(Agent):
    """A code-focused Slack bot for developer teams.

    This agent helps with code questions, debugging,
    and technical discussions.
    """

    def get_system_prompt(self) -> str:
        return """You are a coding assistant bot for developer teams on Slack.

Your expertise includes:
1. Answering programming questions
2. Helping debug code snippets
3. Explaining technical concepts
4. Suggesting best practices

When helping with code:
- Always use code blocks with language hints (```python, ```javascript, etc.)
- Explain the reasoning behind solutions
- Suggest improvements when appropriate
- Consider edge cases and error handling

Keep responses focused and practical. Developers appreciate:
- Direct answers to specific questions
- Working code examples
- Links to relevant documentation
- Acknowledgment of trade-offs in solutions"""

    def get_agent_name(self) -> str:
        return "Code Helper"


def run_single_agent():
    """Run a single agent Slack bot using MultiAgentSlackAdapter."""
    agent = SlackAssistant(
        mcp_server_path="mcp_server/server.py",
        enable_web_search=True,
    )

    adapter = MultiAgentSlackAdapter(
        routing_strategy=RoutingStrategy.HYBRID,
        respond_to_mentions_only=False,  # Respond to all messages
        use_threads=True,  # Reply in threads
        show_typing=True,  # Show typing indicator
    )

    adapter.register_agent(
        name="assistant",
        agent=agent,
        keywords=["help", "question", "assist"],
        description="General purpose assistant",
    )

    adapter.set_default_agent("assistant")
    adapter.start()


def run_multi_agent():
    """Run a multi-agent Slack bot with routing based on message content."""
    # Create specialized agents
    assistant = SlackAssistant(
        mcp_server_path="mcp_server/server.py",
        enable_web_search=True,
    )

    researcher = SlackResearchBot(
        mcp_server_path="mcp_server/server.py",
        enable_web_search=True,
        web_search_config={
            "max_uses": 5,  # Allow multiple searches per response
        },
    )

    coder = SlackCodeHelper(
        mcp_server_path="mcp_server/server.py",
        enable_web_search=True,
        web_search_config={
            "allowed_domains": [
                "docs.python.org",
                "developer.mozilla.org",
                "stackoverflow.com",
                "github.com",
            ],
        },
    )

    # Create adapter with hybrid routing
    adapter = MultiAgentSlackAdapter(
        routing_strategy=RoutingStrategy.HYBRID,
        respond_to_mentions_only=True,  # Only respond when @mentioned
        use_threads=True,
    )

    # Register agents with keywords
    adapter.register_agent(
        name="assistant",
        agent=assistant,
        keywords=["help", "question", "how do i", "what is"],
        description="General purpose assistant",
    )

    adapter.register_agent(
        name="research",
        agent=researcher,
        keywords=["research", "find", "search", "look up", "information about"],
        description="Research and information lookup",
    )

    adapter.register_agent(
        name="code",
        agent=coder,
        keywords=["code", "python", "javascript", "debug", "error", "function", "api"],
        description="Code help and debugging",
    )

    # Set default for unmatched messages
    adapter.set_default_agent("assistant")

    adapter.start()


if __name__ == "__main__":
    # Run the single agent by default
    # Uncomment to try multi-agent configuration:
    # run_multi_agent()

    run_single_agent()
