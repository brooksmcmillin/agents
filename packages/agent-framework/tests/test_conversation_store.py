"""Tests for the database conversation storage module.

These tests use pytest-asyncio and require a PostgreSQL database.
Tests are skipped if no database URL is provided.

To run these tests:
    DATABASE_URL=postgresql://user:pass@host:5432/dbname pytest tests/test_conversation_store.py -v
"""

import os
import uuid

import pytest

# Skip all tests in this module if no database URL is available
pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="Database URL not configured (set DATABASE_URL)",
)


@pytest.fixture
def database_url() -> str:
    """Get database URL from environment."""
    return os.environ.get("DATABASE_URL", "")


@pytest.fixture
async def conversation_store(database_url: str):
    """Create a DatabaseConversationStore for testing.

    Uses unique IDs to avoid conflicts between test runs.
    """
    from agent_framework.storage.conversation_store import DatabaseConversationStore

    store = DatabaseConversationStore(database_url)
    await store.initialize()

    yield store

    # Cleanup: delete test conversations (those with test_ prefix in title)
    async with store._get_connection() as conn:
        await conn.execute("DELETE FROM conversations WHERE title LIKE 'test_%'")

    await store.close()


@pytest.fixture
def unique_id() -> str:
    """Generate a unique ID for test isolation."""
    return f"test_{uuid.uuid4().hex[:8]}"


class TestConversationStoreInitialization:
    """Tests for DatabaseConversationStore initialization."""

    @pytest.mark.asyncio
    async def test_initialization_creates_tables(self, database_url: str):
        """Test that initialization creates the required tables."""
        from agent_framework.storage.conversation_store import DatabaseConversationStore

        store = DatabaseConversationStore(database_url)
        await store.initialize()

        async with store._get_connection() as conn:
            # Check conversations table
            result = await conn.fetchval(
                "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'conversations')"
            )
            assert result is True

            # Check messages table
            result = await conn.fetchval(
                "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'conversation_messages')"
            )
            assert result is True

        await store.close()

    @pytest.mark.asyncio
    async def test_initialization_is_idempotent(self, database_url: str):
        """Test that calling initialize multiple times is safe."""
        from agent_framework.storage.conversation_store import DatabaseConversationStore

        store = DatabaseConversationStore(database_url)

        await store.initialize()
        await store.initialize()
        await store.initialize()

        assert store._initialized is True
        await store.close()

    @pytest.mark.asyncio
    async def test_close_and_reinitialize(self, database_url: str):
        """Test that store can be closed and reinitialized."""
        from agent_framework.storage.conversation_store import DatabaseConversationStore

        store = DatabaseConversationStore(database_url)
        await store.initialize()
        await store.close()

        await store.initialize()
        assert store._initialized is True
        await store.close()


class TestConversationCRUD:
    """Tests for conversation CRUD operations."""

    @pytest.mark.asyncio
    async def test_create_conversation(self, conversation_store, unique_id):
        """Test creating a new conversation."""
        conv = await conversation_store.create_conversation(
            agent_name="chatbot",
            title=f"test_{unique_id}",
            metadata={"key": "value"},
        )

        assert conv.id is not None
        assert conv.agent_name == "chatbot"
        assert conv.title == f"test_{unique_id}"
        assert conv.metadata == {"key": "value"}
        assert conv.message_count == 0

    @pytest.mark.asyncio
    async def test_create_conversation_with_custom_id(self, conversation_store, unique_id):
        """Test creating a conversation with a specific ID."""
        custom_id = f"custom-{unique_id}"
        conv = await conversation_store.create_conversation(
            agent_name="pr",
            title=f"test_{unique_id}",
            conversation_id=custom_id,
        )

        assert conv.id == custom_id

    @pytest.mark.asyncio
    async def test_get_conversation(self, conversation_store, unique_id):
        """Test retrieving a conversation by ID."""
        created = await conversation_store.create_conversation(
            agent_name="chatbot",
            title=f"test_{unique_id}",
        )

        fetched = await conversation_store.get_conversation(created.id)

        assert fetched is not None
        assert fetched.id == created.id
        assert fetched.agent_name == "chatbot"
        assert fetched.title == f"test_{unique_id}"

    @pytest.mark.asyncio
    async def test_get_nonexistent_conversation(self, conversation_store):
        """Test that getting a non-existent conversation returns None."""
        result = await conversation_store.get_conversation("nonexistent-id-12345")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_conversation_with_messages(self, conversation_store, unique_id):
        """Test retrieving a conversation with its messages."""
        conv = await conversation_store.create_conversation(
            agent_name="chatbot",
            title=f"test_{unique_id}",
        )

        # Add messages
        await conversation_store.add_message(conv.id, "user", "Hello")
        await conversation_store.add_message(conv.id, "assistant", "Hi there!")

        result = await conversation_store.get_conversation_with_messages(conv.id)

        assert result is not None
        assert len(result.messages) == 2
        assert result.messages[0].role == "user"
        assert result.messages[0].content == "Hello"
        assert result.messages[1].role == "assistant"
        assert result.messages[1].content == "Hi there!"

    @pytest.mark.asyncio
    async def test_update_conversation_title(self, conversation_store, unique_id):
        """Test updating a conversation's title."""
        conv = await conversation_store.create_conversation(
            agent_name="chatbot",
            title=f"test_{unique_id}",
        )

        updated = await conversation_store.update_conversation(
            conv.id,
            title=f"test_updated_{unique_id}",
        )

        assert updated is not None
        assert updated.title == f"test_updated_{unique_id}"

    @pytest.mark.asyncio
    async def test_update_conversation_metadata(self, conversation_store, unique_id):
        """Test updating a conversation's metadata."""
        conv = await conversation_store.create_conversation(
            agent_name="chatbot",
            title=f"test_{unique_id}",
            metadata={"old": "value"},
        )

        updated = await conversation_store.update_conversation(
            conv.id,
            metadata={"new": "value", "extra": 123},
        )

        assert updated is not None
        assert updated.metadata == {"new": "value", "extra": 123}

    @pytest.mark.asyncio
    async def test_update_nonexistent_conversation(self, conversation_store):
        """Test updating a non-existent conversation returns None."""
        result = await conversation_store.update_conversation(
            "nonexistent-id",
            title="new title",
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_conversation(self, conversation_store, unique_id):
        """Test deleting a conversation."""
        conv = await conversation_store.create_conversation(
            agent_name="chatbot",
            title=f"test_{unique_id}",
        )

        result = await conversation_store.delete_conversation(conv.id)
        assert result is True

        # Verify it's gone
        fetched = await conversation_store.get_conversation(conv.id)
        assert fetched is None

    @pytest.mark.asyncio
    async def test_delete_conversation_cascades_messages(self, conversation_store, unique_id):
        """Test that deleting a conversation also deletes its messages."""
        conv = await conversation_store.create_conversation(
            agent_name="chatbot",
            title=f"test_{unique_id}",
        )

        # Add messages
        await conversation_store.add_message(conv.id, "user", "Hello")
        await conversation_store.add_message(conv.id, "assistant", "Hi!")

        # Delete conversation
        await conversation_store.delete_conversation(conv.id)

        # Verify messages are also gone
        messages = await conversation_store.get_messages(conv.id)
        assert len(messages) == 0

    @pytest.mark.asyncio
    async def test_delete_nonexistent_conversation(self, conversation_store):
        """Test deleting a non-existent conversation returns False."""
        result = await conversation_store.delete_conversation("nonexistent-id")
        assert result is False


class TestConversationListing:
    """Tests for listing conversations."""

    @pytest.mark.asyncio
    async def test_list_conversations(self, conversation_store, unique_id):
        """Test listing all conversations."""
        # Create multiple conversations
        for i in range(3):
            await conversation_store.create_conversation(
                agent_name="chatbot",
                title=f"test_{unique_id}_{i}",
            )

        conversations = await conversation_store.list_conversations()

        # Should have at least our 3 test conversations
        assert len(conversations) >= 3

    @pytest.mark.asyncio
    async def test_list_conversations_filter_by_agent(self, conversation_store, unique_id):
        """Test filtering conversations by agent name."""
        await conversation_store.create_conversation(
            agent_name="chatbot",
            title=f"test_{unique_id}_chatbot",
        )
        await conversation_store.create_conversation(
            agent_name="pr",
            title=f"test_{unique_id}_pr",
        )

        chatbot_convs = await conversation_store.list_conversations(agent_name="chatbot")
        pr_convs = await conversation_store.list_conversations(agent_name="pr")

        chatbot_titles = [c.title for c in chatbot_convs]
        pr_titles = [c.title for c in pr_convs]

        assert f"test_{unique_id}_chatbot" in chatbot_titles
        assert f"test_{unique_id}_pr" not in chatbot_titles
        assert f"test_{unique_id}_pr" in pr_titles

    @pytest.mark.asyncio
    async def test_list_conversations_pagination(self, conversation_store, unique_id):
        """Test conversation listing pagination."""
        # Create 5 conversations
        for i in range(5):
            await conversation_store.create_conversation(
                agent_name="chatbot",
                title=f"test_{unique_id}_page_{i}",
            )

        # Get first 2
        page1 = await conversation_store.list_conversations(limit=2, offset=0)
        # Get next 2
        page2 = await conversation_store.list_conversations(limit=2, offset=2)

        assert len(page1) == 2
        assert len(page2) == 2
        # Pages should have different conversations
        page1_ids = {c.id for c in page1}
        page2_ids = {c.id for c in page2}
        assert page1_ids.isdisjoint(page2_ids)

    @pytest.mark.asyncio
    async def test_list_conversations_sorted_by_updated(self, conversation_store, unique_id):
        """Test that conversations are sorted by updated_at descending."""
        conv1 = await conversation_store.create_conversation(
            agent_name="chatbot",
            title=f"test_{unique_id}_first",
        )
        await conversation_store.create_conversation(
            agent_name="chatbot",
            title=f"test_{unique_id}_second",
        )

        # Update the first conversation to make it newer
        await conversation_store.update_conversation(
            conv1.id, title=f"test_{unique_id}_first_updated"
        )

        conversations = await conversation_store.list_conversations()

        # Find our test conversations
        test_convs = [c for c in conversations if unique_id in (c.title or "")]
        assert len(test_convs) >= 2

        # First updated should come first (most recently updated)
        first_idx = next(
            i for i, c in enumerate(test_convs) if c.title == f"test_{unique_id}_first_updated"
        )
        second_idx = next(
            i for i, c in enumerate(test_convs) if c.title == f"test_{unique_id}_second"
        )
        assert first_idx < second_idx


class TestMessageOperations:
    """Tests for message CRUD operations."""

    @pytest.mark.asyncio
    async def test_add_message(self, conversation_store, unique_id):
        """Test adding a message to a conversation."""
        conv = await conversation_store.create_conversation(
            agent_name="chatbot",
            title=f"test_{unique_id}",
        )

        msg = await conversation_store.add_message(
            conv.id,
            role="user",
            content="Hello, world!",
        )

        assert msg.role == "user"
        assert msg.content == "Hello, world!"
        assert msg.turn_number == 0

    @pytest.mark.asyncio
    async def test_add_message_with_token_count(self, conversation_store, unique_id):
        """Test adding a message with token count."""
        conv = await conversation_store.create_conversation(
            agent_name="chatbot",
            title=f"test_{unique_id}",
        )

        msg = await conversation_store.add_message(
            conv.id,
            role="assistant",
            content="Response",
            token_count=42,
        )

        assert msg.token_count == 42

    @pytest.mark.asyncio
    async def test_add_message_increments_turn_number(self, conversation_store, unique_id):
        """Test that turn numbers increment correctly."""
        conv = await conversation_store.create_conversation(
            agent_name="chatbot",
            title=f"test_{unique_id}",
        )

        msg1 = await conversation_store.add_message(conv.id, "user", "First")
        msg2 = await conversation_store.add_message(conv.id, "assistant", "Second")
        msg3 = await conversation_store.add_message(conv.id, "user", "Third")

        assert msg1.turn_number == 0
        assert msg2.turn_number == 1
        assert msg3.turn_number == 2

    @pytest.mark.asyncio
    async def test_add_message_with_complex_content(self, conversation_store, unique_id):
        """Test adding a message with complex content (list of content blocks)."""
        conv = await conversation_store.create_conversation(
            agent_name="chatbot",
            title=f"test_{unique_id}",
        )

        complex_content = [
            {"type": "text", "text": "Here's the analysis:"},
            {"type": "tool_use", "id": "tool_123", "name": "analyze", "input": {}},
        ]

        msg = await conversation_store.add_message(conv.id, "assistant", complex_content)

        assert msg.content == complex_content

        # Verify it roundtrips correctly
        fetched = await conversation_store.get_conversation_with_messages(conv.id)
        assert fetched.messages[0].content == complex_content

    @pytest.mark.asyncio
    async def test_add_messages_batch(self, conversation_store, unique_id):
        """Test adding multiple messages at once."""
        conv = await conversation_store.create_conversation(
            agent_name="chatbot",
            title=f"test_{unique_id}",
        )

        messages = [
            {"role": "user", "content": "Question 1"},
            {"role": "assistant", "content": "Answer 1"},
            {"role": "user", "content": "Question 2"},
            {"role": "assistant", "content": "Answer 2"},
        ]

        result = await conversation_store.add_messages_batch(conv.id, messages)

        assert len(result) == 4
        assert result[0].turn_number == 0
        assert result[1].turn_number == 1
        assert result[2].turn_number == 2
        assert result[3].turn_number == 3

    @pytest.mark.asyncio
    async def test_add_messages_batch_empty(self, conversation_store, unique_id):
        """Test adding an empty batch returns empty list."""
        conv = await conversation_store.create_conversation(
            agent_name="chatbot",
            title=f"test_{unique_id}",
        )

        result = await conversation_store.add_messages_batch(conv.id, [])
        assert result == []

    @pytest.mark.asyncio
    async def test_get_messages(self, conversation_store, unique_id):
        """Test retrieving messages from a conversation."""
        conv = await conversation_store.create_conversation(
            agent_name="chatbot",
            title=f"test_{unique_id}",
        )

        await conversation_store.add_message(conv.id, "user", "Hello")
        await conversation_store.add_message(conv.id, "assistant", "Hi!")

        messages = await conversation_store.get_messages(conv.id)

        assert len(messages) == 2
        assert messages[0].role == "user"
        assert messages[1].role == "assistant"

    @pytest.mark.asyncio
    async def test_get_messages_pagination(self, conversation_store, unique_id):
        """Test paginated message retrieval."""
        conv = await conversation_store.create_conversation(
            agent_name="chatbot",
            title=f"test_{unique_id}",
        )

        # Add 5 messages
        for i in range(5):
            await conversation_store.add_message(conv.id, "user", f"Message {i}")

        # Get first 2
        page1 = await conversation_store.get_messages(conv.id, limit=2, offset=0)
        # Get next 2
        page2 = await conversation_store.get_messages(conv.id, limit=2, offset=2)

        assert len(page1) == 2
        assert len(page2) == 2
        assert page1[0].content == "Message 0"
        assert page2[0].content == "Message 2"

    @pytest.mark.asyncio
    async def test_clear_messages(self, conversation_store, unique_id):
        """Test clearing all messages from a conversation."""
        conv = await conversation_store.create_conversation(
            agent_name="chatbot",
            title=f"test_{unique_id}",
        )

        # Add messages
        await conversation_store.add_message(conv.id, "user", "Hello")
        await conversation_store.add_message(conv.id, "assistant", "Hi!")

        # Clear them
        count = await conversation_store.clear_messages(conv.id)
        assert count == 2

        # Verify they're gone
        messages = await conversation_store.get_messages(conv.id)
        assert len(messages) == 0

        # Verify conversation still exists
        conv_after = await conversation_store.get_conversation(conv.id)
        assert conv_after is not None


class TestConversationStats:
    """Tests for conversation statistics."""

    @pytest.mark.asyncio
    async def test_get_stats(self, conversation_store, unique_id):
        """Test getting conversation statistics."""
        # Create conversations with messages
        conv1 = await conversation_store.create_conversation(
            agent_name="chatbot",
            title=f"test_{unique_id}_1",
        )
        await conversation_store.add_message(conv1.id, "user", "Hello")
        await conversation_store.add_message(conv1.id, "assistant", "Hi!")

        conv2 = await conversation_store.create_conversation(
            agent_name="pr",
            title=f"test_{unique_id}_2",
        )
        await conversation_store.add_message(conv2.id, "user", "Review my PR")

        stats = await conversation_store.get_stats()

        assert stats["total_conversations"] >= 2
        assert stats["total_messages"] >= 3
        assert "chatbot" in stats["conversations_by_agent"]
        assert "pr" in stats["conversations_by_agent"]

    @pytest.mark.asyncio
    async def test_stats_empty_database(self, database_url):
        """Test stats on a fresh database."""
        from agent_framework.storage.conversation_store import DatabaseConversationStore

        store = DatabaseConversationStore(database_url)
        await store.initialize()

        stats = await store.get_stats()

        assert stats["total_conversations"] >= 0
        assert stats["total_messages"] >= 0
        assert isinstance(stats["conversations_by_agent"], dict)

        await store.close()


class TestMessageCountTracking:
    """Tests for conversation message count tracking."""

    @pytest.mark.asyncio
    async def test_message_count_updates(self, conversation_store, unique_id):
        """Test that message_count is updated correctly."""
        conv = await conversation_store.create_conversation(
            agent_name="chatbot",
            title=f"test_{unique_id}",
        )
        assert conv.message_count == 0

        # Add messages
        await conversation_store.add_message(conv.id, "user", "Hello")
        await conversation_store.add_message(conv.id, "assistant", "Hi!")

        # Check count
        updated = await conversation_store.get_conversation(conv.id)
        assert updated.message_count == 2

    @pytest.mark.asyncio
    async def test_message_count_after_clear(self, conversation_store, unique_id):
        """Test that message_count is 0 after clearing messages."""
        conv = await conversation_store.create_conversation(
            agent_name="chatbot",
            title=f"test_{unique_id}",
        )

        await conversation_store.add_message(conv.id, "user", "Hello")
        await conversation_store.add_message(conv.id, "assistant", "Hi!")
        await conversation_store.clear_messages(conv.id)

        updated = await conversation_store.get_conversation(conv.id)
        assert updated.message_count == 0
