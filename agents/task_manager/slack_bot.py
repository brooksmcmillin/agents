import os

from agent_framework import MultiAgentSlackAdapter

from .main import TaskManagerAgent


def main() -> None:
    # Get MCP URL from environment or use default
    mcp_url = os.getenv("MCP_SERVER_URL", "https://mcp.brooksmcmillin.com/mcp")

    # Create the agent
    agent = TaskManagerAgent(
        mcp_urls=[mcp_url],
        mcp_client_config={
            "prefer_device_flow": True,  # Use Device Flow instead of browser
        },
    )

    # Create adapter and register the agent
    adapter = MultiAgentSlackAdapter(
        respond_to_mentions_only=False,  # Respond to all messages
        use_threads=True,  # Reply in threads
        show_typing=True,  # Show typing indicator
    )
    adapter.register_agent("task_manager", agent, description="Task management agent")
    adapter.set_default_agent("task_manager")

    adapter.start()


if __name__ == "__main__":
    main()
