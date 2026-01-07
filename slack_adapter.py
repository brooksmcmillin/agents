"""Multi-agent Slack adapter for Task Manager and PR Agent.

This module creates a Slack bot that routes messages to the appropriate agent
based on keywords and context. It uses the MultiAgentSlackAdapter from
agent_framework to handle multiple agents with intelligent routing.
"""

import os

from agent_framework import MultiAgentSlackAdapter, RoutingStrategy
from dotenv import load_dotenv

from agents.task_manager.main import TaskManagerAgent
from agents.pr_agent.main import PRAgent
from shared import setup_logging

# Load environment variables
load_dotenv()

# Configure logging
logger = setup_logging(__name__)


def main() -> None:
    """Start the multi-agent Slack adapter."""
    # Get tokens from environment
    bot_token = os.getenv("SLACK_BOT_TOKEN")
    app_token = os.getenv("SLACK_APP_TOKEN")

    if not bot_token or not app_token:
        print("Error: SLACK_BOT_TOKEN and SLACK_APP_TOKEN must be set in .env")
        return

    # Get MCP URL for task manager agent
    mcp_url = os.getenv("MCP_SERVER_URL", "https://mcp.brooksmcmillin.com/mcp")

    # Create agents
    task_agent = TaskManagerAgent(
        mcp_urls=[mcp_url],
        mcp_client_config={
            "prefer_device_flow": True,  # Use Device Flow instead of browser
        },
    )

    pr_agent = PRAgent()  # PR agent uses local MCP server

    # Create the multi-agent adapter
    adapter = MultiAgentSlackAdapter(
        bot_token=bot_token,
        app_token=app_token,
        routing_strategy=RoutingStrategy.HYBRID,
        inactivity_timeout=86400,  # 24 hours
    )

    # Register agents with keywords for routing
    adapter.register_agent(
        name="tasks",
        agent=task_agent,
        keywords=["task", "todo", "schedule", "reminder", "due", "deadline", "overdue"],
        description="Task management - creating, updating, and tracking tasks",
    )
    adapter.register_agent(
        name="pr",
        agent=pr_agent,
        keywords=[
            "pr",
            "review",
            "code",
            "website",
            "seo",
            "content",
            "social",
            "twitter",
            "linkedin",
        ],
        description="PR and content strategy - website analysis, SEO, social media",
    )

    # Set default agent for messages that don't match keywords
    adapter.set_default_agent("tasks")

    logger.info("Starting multi-agent Slack adapter...")
    adapter.start()


if __name__ == "__main__":
    main()
