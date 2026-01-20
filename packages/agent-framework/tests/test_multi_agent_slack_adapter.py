"""Tests for MultiAgentSlackAdapter routing logic."""

from unittest.mock import MagicMock, patch

import pytest

from agent_framework.adapters.multi_agent_slack_adapter import (
    MultiAgentSlackAdapter,
    RoutingStrategy,
)


@pytest.fixture
def mock_agent():
    """Create a mock agent."""
    agent = MagicMock()
    agent.get_agent_name.return_value = "MockAgent"
    agent.get_system_prompt.return_value = "Test prompt"
    agent.reset_conversation = MagicMock()
    return agent


@pytest.fixture
def adapter():
    """Create a MultiAgentSlackAdapter with mocked Slack app."""
    with patch("agent_framework.adapters.multi_agent_slack_adapter.App"):
        adapter = MultiAgentSlackAdapter(
            bot_token="xoxb-test-token",
            app_token="xapp-test-token",
            routing_strategy=RoutingStrategy.HYBRID,
        )
        return adapter


class TestRouting:
    """Tests for message routing logic."""

    def test_keyword_routing_single_match(self, adapter, mock_agent):
        """Test routing based on a single keyword match."""
        adapter.register_agent(
            name="tasks",
            agent=mock_agent,
            keywords=["task", "tasks", "todo", "schedule"],
        )

        result = adapter._route_by_keywords("what are my tasks for today?")
        assert result == "tasks"

    def test_keyword_routing_multiple_matches(self, adapter, mock_agent):
        """Test routing with multiple keywords matching."""
        mock_agent2 = MagicMock()
        mock_agent2.get_agent_name.return_value = "PRAgent"

        adapter.register_agent(
            name="tasks",
            agent=mock_agent,
            keywords=["task", "todo"],
        )
        adapter.register_agent(
            name="pr",
            agent=mock_agent2,
            keywords=["pr", "review", "code"],
        )

        # "task" matches tasks agent
        result = adapter._route_by_keywords("show me my task list")
        assert result == "tasks"

        # "review code" matches pr agent with higher score
        result = adapter._route_by_keywords("please review this code")
        assert result == "pr"

    def test_keyword_routing_no_match(self, adapter, mock_agent):
        """Test routing when no keywords match."""
        adapter.register_agent(
            name="tasks",
            agent=mock_agent,
            keywords=["task", "todo"],
        )

        result = adapter._route_by_keywords("hello how are you")
        assert result is None

    def test_explicit_routing_at_mention(self, adapter, mock_agent):
        """Test explicit routing with @agent pattern."""
        adapter.register_agent(name="tasks", agent=mock_agent)

        result = adapter._route_by_explicit("@tasks show my todos")
        assert result == "tasks"

    def test_explicit_routing_ask_pattern(self, adapter, mock_agent):
        """Test explicit routing with 'ask agent:' pattern."""
        adapter.register_agent(name="pr", agent=mock_agent)

        result = adapter._route_by_explicit("ask pr: review this code")
        assert result == "pr"

    def test_explicit_routing_colon_prefix(self, adapter, mock_agent):
        """Test explicit routing with 'agent:' prefix."""
        adapter.register_agent(name="tasks", agent=mock_agent)

        result = adapter._route_by_explicit("tasks: show overdue items")
        assert result == "tasks"

    def test_channel_routing(self, adapter, mock_agent):
        """Test routing based on channel ID."""
        adapter.register_agent(
            name="tasks",
            agent=mock_agent,
            channels=["C123456"],
        )

        result = adapter._route_by_channel("C123456")
        assert result == "tasks"

        result = adapter._route_by_channel("C999999")
        assert result is None

    def test_hybrid_routing_explicit_priority(self, adapter, mock_agent):
        """Test hybrid routing prioritizes explicit over keywords."""
        mock_agent2 = MagicMock()
        mock_agent2.get_agent_name.return_value = "PRAgent"

        adapter.register_agent(
            name="tasks",
            agent=mock_agent,
            keywords=["task", "review"],  # "review" keyword here
        )
        adapter.register_agent(
            name="pr",
            agent=mock_agent2,
            keywords=["pr", "code"],
        )
        adapter.set_default_agent("tasks")

        # Explicit @pr should win over keyword match
        thread_key = ("C123", None)
        result = adapter._route_message("@pr review this task", "C123", thread_key)
        assert result == "pr"

    def test_hybrid_routing_falls_back_to_keywords(self, adapter, mock_agent):
        """Test hybrid routing uses keywords when no explicit match."""
        adapter.register_agent(
            name="tasks",
            agent=mock_agent,
            keywords=["task", "todo"],
        )
        adapter.set_default_agent("tasks")

        thread_key = ("C123", None)
        result = adapter._route_message("show me my todos", "C123", thread_key)
        assert result == "tasks"

    def test_hybrid_routing_thread_continuity(self, adapter, mock_agent):
        """Test hybrid routing remembers last agent in thread."""
        mock_agent2 = MagicMock()
        mock_agent2.get_agent_name.return_value = "PRAgent"

        adapter.register_agent(name="tasks", agent=mock_agent, keywords=["task"])
        adapter.register_agent(name="pr", agent=mock_agent2, keywords=["pr"])
        adapter.set_default_agent("tasks")

        thread_key = ("C123", "1234567890.123456")

        # Simulate previous interaction with pr agent
        adapter.last_agent_in_thread[thread_key] = "pr"

        # No keywords match, should use last agent
        result = adapter._route_message("yes that looks good", "C123", thread_key)
        assert result == "pr"

    def test_hybrid_routing_default_fallback(self, adapter, mock_agent):
        """Test hybrid routing falls back to default agent."""
        adapter.register_agent(name="tasks", agent=mock_agent, keywords=["task"])
        adapter.set_default_agent("tasks")

        thread_key = ("C123", None)
        result = adapter._route_message("hello there", "C123", thread_key)
        assert result == "tasks"


class TestAgentRegistration:
    """Tests for agent registration."""

    def test_register_agent(self, adapter, mock_agent):
        """Test basic agent registration."""
        adapter.register_agent(
            name="tasks",
            agent=mock_agent,
            keywords=["task", "todo"],
            description="Task management",
        )

        assert "tasks" in adapter.agents
        assert adapter.agents["tasks"].agent == mock_agent
        assert adapter.agents["tasks"].keywords == ["task", "todo"]
        assert adapter.agents["tasks"].description == "Task management"

    def test_set_default_agent(self, adapter, mock_agent):
        """Test setting default agent."""
        adapter.register_agent(name="tasks", agent=mock_agent)
        adapter.set_default_agent("tasks")

        assert adapter.default_agent_name == "tasks"

    def test_set_default_agent_not_registered(self, adapter):
        """Test setting default agent that isn't registered."""
        with pytest.raises(ValueError, match="not registered"):
            adapter.set_default_agent("nonexistent")


class TestConversationIsolation:
    """Tests for per-agent conversation isolation."""

    def test_separate_conversation_contexts(self, adapter, mock_agent):
        """Test that different agents have separate contexts."""
        mock_agent2 = MagicMock()
        mock_agent2.get_agent_name.return_value = "PRAgent"

        adapter.register_agent(name="tasks", agent=mock_agent)
        adapter.register_agent(name="pr", agent=mock_agent2)

        # Create contexts for different agents in same thread
        context1 = ("C123", "1234567890.123", "tasks")
        context2 = ("C123", "1234567890.123", "pr")

        # These should be different context keys
        assert context1 != context2

    def test_reset_specific_agent_conversation(self, adapter, mock_agent):
        """Test resetting a specific agent's conversation."""
        mock_agent2 = MagicMock()
        mock_agent2.get_agent_name.return_value = "PRAgent"

        adapter.register_agent(name="tasks", agent=mock_agent)
        adapter.register_agent(name="pr", agent=mock_agent2)

        # Add some contexts
        adapter.conversations[("C123", None, "tasks")] = MagicMock()
        adapter.conversations[("C123", None, "pr")] = MagicMock()

        # Reset only tasks
        adapter.reset_conversation("C123", None, agent_name="tasks")

        assert ("C123", None, "tasks") not in adapter.conversations
        assert ("C123", None, "pr") in adapter.conversations

    def test_reset_all_agents_in_thread(self, adapter, mock_agent):
        """Test resetting all agents' conversations in a thread."""
        mock_agent2 = MagicMock()
        mock_agent2.get_agent_name.return_value = "PRAgent"

        adapter.register_agent(name="tasks", agent=mock_agent)
        adapter.register_agent(name="pr", agent=mock_agent2)

        # Add contexts
        adapter.conversations[("C123", "thread1", "tasks")] = MagicMock()
        adapter.conversations[("C123", "thread1", "pr")] = MagicMock()
        adapter.last_agent_in_thread[("C123", "thread1")] = "tasks"

        # Reset all in thread
        adapter.reset_conversation("C123", "thread1")

        assert ("C123", "thread1", "tasks") not in adapter.conversations
        assert ("C123", "thread1", "pr") not in adapter.conversations
        assert ("C123", "thread1") not in adapter.last_agent_in_thread


class TestRoutingPrefixRemoval:
    """Tests for removing routing prefixes from messages."""

    def test_remove_at_mention_prefix(self, adapter, mock_agent):
        """Test removing @agent prefix."""
        adapter.register_agent(name="tasks", agent=mock_agent)

        result = adapter._remove_routing_prefix("@tasks show my todos", "tasks")
        assert result == "show my todos"

    def test_remove_ask_prefix(self, adapter, mock_agent):
        """Test removing 'ask agent:' prefix."""
        adapter.register_agent(name="pr", agent=mock_agent)

        result = adapter._remove_routing_prefix("ask pr: review this", "pr")
        assert result == "review this"

    def test_remove_colon_prefix(self, adapter, mock_agent):
        """Test removing 'agent:' prefix."""
        adapter.register_agent(name="tasks", agent=mock_agent)

        result = adapter._remove_routing_prefix("tasks: get overdue items", "tasks")
        assert result == "get overdue items"

    def test_no_prefix_unchanged(self, adapter, mock_agent):
        """Test message without prefix stays unchanged."""
        adapter.register_agent(name="tasks", agent=mock_agent)

        result = adapter._remove_routing_prefix("show my tasks", "tasks")
        assert result == "show my tasks"


class TestListAgents:
    """Tests for listing registered agents."""

    def test_list_agents_empty(self, adapter):
        """Test listing when no agents registered."""
        result = adapter.list_agents()
        assert "No agents registered" in result

    def test_list_agents_with_agents(self, adapter, mock_agent):
        """Test listing with registered agents."""
        adapter.register_agent(
            name="tasks",
            agent=mock_agent,
            keywords=["task", "todo"],
            description="Task management",
        )
        adapter.set_default_agent("tasks")

        result = adapter.list_agents()
        assert "tasks" in result
        assert "(default)" in result
        assert "Task management" in result
        assert "task" in result
