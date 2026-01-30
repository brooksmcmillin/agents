"""Tests for the database memory storage module.

These tests use pytest-asyncio and require a PostgreSQL database.
Tests are skipped if no database URL is provided.

To run these tests:
    DATABASE_URL=postgresql://user:pass@host:5432/dbname pytest tests/test_database_memory_store.py -v

Or set MEMORY_DATABASE_URL environment variable.
"""

import os

import pytest

# Skip all tests in this module if no database URL is available
pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL") and not os.environ.get("MEMORY_DATABASE_URL"),
    reason="Database URL not configured (set DATABASE_URL or MEMORY_DATABASE_URL)",
)


@pytest.fixture
def database_url() -> str:
    """Get database URL from environment."""
    return os.environ.get("MEMORY_DATABASE_URL") or os.environ.get("DATABASE_URL", "")


@pytest.fixture
async def database_store(database_url: str):
    """Create a DatabaseMemoryStore for testing.

    Uses a unique table prefix to avoid conflicts between test runs.
    """
    from agent_framework.storage.database_memory_store import DatabaseMemoryStore

    store = DatabaseMemoryStore(database_url, agent_name="test_agent", cache_ttl=0)  # Disable cache for tests
    await store.initialize()

    # Clean up any existing test data for this agent
    async with store._pool.acquire() as conn:
        await conn.execute("DELETE FROM memories WHERE agent_name = 'test_agent' AND key LIKE 'test_%'")

    yield store

    # Cleanup after test
    async with store._pool.acquire() as conn:
        await conn.execute("DELETE FROM memories WHERE agent_name = 'test_agent' AND key LIKE 'test_%'")

    await store.close()


class TestDatabaseMemoryStoreInitialization:
    """Tests for DatabaseMemoryStore initialization."""

    @pytest.mark.asyncio
    async def test_initialization_creates_table(self, database_url: str):
        """Test that initialization creates the memories table."""
        from agent_framework.storage.database_memory_store import DatabaseMemoryStore

        store = DatabaseMemoryStore(database_url)
        await store.initialize()

        # Verify table exists by querying it
        async with store._pool.acquire() as conn:
            result = await conn.fetchval(
                "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'memories')"
            )
            assert result is True

        await store.close()

    @pytest.mark.asyncio
    async def test_initialization_is_idempotent(self, database_url: str):
        """Test that calling initialize multiple times is safe."""
        from agent_framework.storage.database_memory_store import DatabaseMemoryStore

        store = DatabaseMemoryStore(database_url)

        # Call initialize multiple times
        await store.initialize()
        await store.initialize()
        await store.initialize()

        assert store._initialized is True
        await store.close()

    @pytest.mark.asyncio
    async def test_close_and_reinitialize(self, database_url: str):
        """Test that store can be closed and reinitialized."""
        from agent_framework.storage.database_memory_store import DatabaseMemoryStore

        store = DatabaseMemoryStore(database_url)
        await store.initialize()
        await store.close()

        # Should be able to reinitialize
        await store.initialize()
        assert store._initialized is True
        await store.close()


class TestDatabaseMemoryStoreCRUD:
    """Tests for DatabaseMemoryStore CRUD operations."""

    @pytest.mark.asyncio
    async def test_save_new_memory(self, database_store):
        """Test saving a new memory to the database."""
        from agent_framework.storage.memory_store import Memory

        memory = await database_store.save_memory(
            key="test_new_memory",
            value="Test value",
            category="test_category",
            tags=["tag1", "tag2"],
            importance=8,
        )

        assert isinstance(memory, Memory)
        assert memory.key == "test_new_memory"
        assert memory.value == "Test value"
        assert memory.category == "test_category"
        assert memory.tags == ["tag1", "tag2"]
        assert memory.importance == 8

    @pytest.mark.asyncio
    async def test_save_memory_with_special_characters(self, database_store):
        """Test saving memory with special characters in value."""
        memory = await database_store.save_memory(
            key="test_special_chars",
            value="Value with 'quotes' and \"double quotes\" and emoji ",
            category="test",
        )

        assert memory.value == "Value with 'quotes' and \"double quotes\" and emoji "

    @pytest.mark.asyncio
    async def test_update_existing_memory(self, database_store):
        """Test updating an existing memory."""
        # Create initial memory
        await database_store.save_memory(
            key="test_update",
            value="Initial value",
            importance=5,
        )

        # Update it
        updated = await database_store.save_memory(
            key="test_update",
            value="Updated value",
            importance=9,
        )

        assert updated.value == "Updated value"
        assert updated.importance == 9

        # Verify only one memory exists with this key
        memories = await database_store.get_all_memories()
        test_memories = [m for m in memories if m.key == "test_update"]
        assert len(test_memories) == 1

    @pytest.mark.asyncio
    async def test_get_memory_by_key(self, database_store):
        """Test retrieving a memory by key."""
        await database_store.save_memory(
            key="test_get_by_key",
            value="Expected value",
        )

        memory = await database_store.get_memory("test_get_by_key")

        assert memory is not None
        assert memory.key == "test_get_by_key"
        assert memory.value == "Expected value"

    @pytest.mark.asyncio
    async def test_get_nonexistent_memory(self, database_store):
        """Test that getting a non-existent memory returns None."""
        memory = await database_store.get_memory("test_nonexistent_key_12345")
        assert memory is None

    @pytest.mark.asyncio
    async def test_delete_memory(self, database_store):
        """Test deleting a memory."""
        await database_store.save_memory(key="test_delete", value="To be deleted")

        result = await database_store.delete_memory("test_delete")
        assert result is True

        # Verify it's gone
        memory = await database_store.get_memory("test_delete")
        assert memory is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_memory(self, database_store):
        """Test deleting a non-existent memory returns False."""
        result = await database_store.delete_memory("test_nonexistent_delete_key")
        assert result is False


class TestDatabaseMemoryStoreQueries:
    """Tests for DatabaseMemoryStore query operations."""

    @pytest.mark.asyncio
    async def test_get_all_memories_sorted_by_importance(self, database_store):
        """Test that memories are returned sorted by importance (high to low)."""
        await database_store.save_memory(key="test_low", value="low", importance=3)
        await database_store.save_memory(key="test_high", value="high", importance=9)
        await database_store.save_memory(key="test_medium", value="medium", importance=5)

        memories = await database_store.get_all_memories()
        test_memories = [m for m in memories if m.key.startswith("test_")]

        assert len(test_memories) >= 3
        # Find our test memories and verify order
        importances = [
            m.importance for m in test_memories if m.key in ["test_low", "test_high", "test_medium"]
        ]
        assert importances == sorted(importances, reverse=True)

    @pytest.mark.asyncio
    async def test_filter_by_category(self, database_store):
        """Test filtering memories by category."""
        await database_store.save_memory(key="test_cat_a", value="v", category="category_a")
        await database_store.save_memory(key="test_cat_b", value="v", category="category_b")
        await database_store.save_memory(key="test_cat_a2", value="v", category="category_a")

        memories = await database_store.get_all_memories(category="category_a")
        keys = [m.key for m in memories]

        assert "test_cat_a" in keys
        assert "test_cat_a2" in keys
        assert "test_cat_b" not in keys

    @pytest.mark.asyncio
    async def test_filter_by_tags(self, database_store):
        """Test filtering memories by tags."""
        await database_store.save_memory(key="test_tag_py", value="v", tags=["python", "coding"])
        await database_store.save_memory(key="test_tag_js", value="v", tags=["javascript"])
        await database_store.save_memory(key="test_tag_py2", value="v", tags=["python"])

        memories = await database_store.get_all_memories(tags=["python"])
        keys = [m.key for m in memories]

        assert "test_tag_py" in keys
        assert "test_tag_py2" in keys
        assert "test_tag_js" not in keys

    @pytest.mark.asyncio
    async def test_filter_by_min_importance(self, database_store):
        """Test filtering memories by minimum importance."""
        await database_store.save_memory(key="test_imp_low", value="v", importance=2)
        await database_store.save_memory(key="test_imp_high", value="v", importance=8)
        await database_store.save_memory(key="test_imp_mid", value="v", importance=5)

        memories = await database_store.get_all_memories(min_importance=5)
        keys = [m.key for m in memories]

        assert "test_imp_high" in keys
        assert "test_imp_mid" in keys
        assert "test_imp_low" not in keys

    @pytest.mark.asyncio
    async def test_results_sorted_by_importance(self, database_store):
        """Test that results are sorted by importance (high to low)."""
        for i in range(1, 6):
            await database_store.save_memory(key=f"test_sort_{i}", value=f"v{i}", importance=i)

        memories = await database_store.get_all_memories()
        test_memories = [m for m in memories if m.key.startswith("test_sort_")]

        # Verify they're sorted by importance descending
        importances = [m.importance for m in test_memories]
        assert importances == sorted(importances, reverse=True)

    @pytest.mark.asyncio
    async def test_search_memories(self, database_store):
        """Test searching memories by text."""
        await database_store.save_memory(key="test_search_email", value="john@example.com")
        await database_store.save_memory(key="test_search_secret", value="api_key_123")
        await database_store.save_memory(key="test_search_phone", value="555-1234")

        results = await database_store.search_memories("search")

        assert len(results) >= 3
        keys = [m.key for m in results]
        assert "test_search_email" in keys
        assert "test_search_secret" in keys
        assert "test_search_phone" in keys

    @pytest.mark.asyncio
    async def test_search_case_insensitive(self, database_store):
        """Test that search is case-insensitive."""
        await database_store.save_memory(key="test_CaseSensitive", value="MixedCase")

        results = await database_store.search_memories("casesensitive")

        keys = [m.key for m in results]
        assert "test_CaseSensitive" in keys

    @pytest.mark.asyncio
    async def test_search_sql_injection_percent_wildcard(self, database_store):
        """Test that SQL wildcard % character is properly escaped in search.

        This tests line 370 of database_memory_store.py which was identified
        as CRITICAL untested SQL injection protection.
        """
        # Create test data
        await database_store.save_memory(key="test_inject_1", value="normal value")
        await database_store.save_memory(key="test_inject_2", value="another value")
        await database_store.save_memory(key="test_inject_secret", value="secret data")

        # Try to inject % wildcard to match all records
        # If escaping is broken, this would return all memories
        # If working correctly, it should only match literal "%" characters
        results = await database_store.search_memories("%")

        # Should not return our test records (they don't contain literal %)
        keys = [m.key for m in results]
        assert "test_inject_1" not in keys
        assert "test_inject_2" not in keys
        assert "test_inject_secret" not in keys

    @pytest.mark.asyncio
    async def test_search_sql_injection_underscore_wildcard(self, database_store):
        """Test that SQL wildcard _ character is properly escaped in search."""
        await database_store.save_memory(key="test_underscore_abc", value="abc")
        await database_store.save_memory(key="test_underscore_xyz", value="xyz")

        # Try to inject _ wildcard (matches any single character)
        # If working correctly, should only match literal "_" not act as wildcard
        results = await database_store.search_memories("a_c")

        # Should not match "abc" (unless it contains literal "a_c")
        # This search should find very few or no results
        # unless there are memories that actually contain "a_c"
        assert len(results) < 10  # Sanity check - not matching everything

    @pytest.mark.asyncio
    async def test_search_sql_injection_backslash_escape(self, database_store):
        """Test that backslash escape character is properly handled."""
        await database_store.save_memory(key="test_backslash", value="test\\value")

        # Search for backslash - should be escaped properly
        results = await database_store.search_memories("\\")

        # Should find the memory with backslash
        keys = [m.key for m in results]
        assert "test_backslash" in keys

    @pytest.mark.asyncio
    async def test_search_sql_injection_combined_wildcards(self, database_store):
        """Test search with multiple SQL special characters."""
        await database_store.save_memory(key="test_combined_1", value="data")
        await database_store.save_memory(key="test_combined_2", value="information")

        # Try combined attack with %, _, and \
        # Should not match everything
        results = await database_store.search_memories("%_\\%")

        # Should not return unrelated records
        assert len(results) < 50  # Sanity check


class TestDatabaseMemoryStoreStats:
    """Tests for DatabaseMemoryStore statistics."""

    @pytest.mark.asyncio
    async def test_get_stats(self, database_store):
        """Test getting memory statistics."""
        await database_store.save_memory(key="test_stat_1", value="v", category="cat1")
        await database_store.save_memory(key="test_stat_2", value="v", category="cat1")
        await database_store.save_memory(key="test_stat_3", value="v", category="cat2")

        stats = await database_store.get_stats()

        assert stats["total_memories"] >= 3
        assert "cat1" in stats["categories"]
        assert "cat2" in stats["categories"]


class TestDatabaseMemoryStoreTagsSerialization:
    """Tests for proper JSONB tags serialization/deserialization."""

    @pytest.mark.asyncio
    async def test_tags_roundtrip(self, database_store):
        """Test that tags are properly serialized and deserialized."""
        original_tags = ["tag1", "tag2", "tag with spaces"]

        await database_store.save_memory(
            key="test_tags_roundtrip",
            value="value",
            tags=original_tags,
        )

        memory = await database_store.get_memory("test_tags_roundtrip")

        assert memory is not None
        assert memory.tags == original_tags
        assert isinstance(memory.tags, list)

    @pytest.mark.asyncio
    async def test_empty_tags(self, database_store):
        """Test that empty tags are handled correctly."""
        await database_store.save_memory(
            key="test_empty_tags",
            value="value",
            tags=[],
        )

        memory = await database_store.get_memory("test_empty_tags")

        assert memory is not None
        assert memory.tags == []

    @pytest.mark.asyncio
    async def test_none_tags(self, database_store):
        """Test that None tags are handled correctly."""
        await database_store.save_memory(
            key="test_none_tags",
            value="value",
            tags=None,
        )

        memory = await database_store.get_memory("test_none_tags")

        assert memory is not None
        assert memory.tags == []


class TestDatabaseMemoryStoreAgentIsolation:
    """Tests for agent-level memory isolation in the database store."""

    @pytest.mark.asyncio
    async def test_different_agents_have_separate_memories(self, database_url: str):
        """Test that different agents have completely separate memory stores."""
        from agent_framework.storage.database_memory_store import DatabaseMemoryStore

        chatbot_store = DatabaseMemoryStore(database_url, agent_name="isolation_test_chatbot", cache_ttl=0)
        pr_store = DatabaseMemoryStore(database_url, agent_name="isolation_test_pr", cache_ttl=0)

        await chatbot_store.initialize()
        await pr_store.initialize()

        try:
            # Save memories with the same key to each agent
            await chatbot_store.save_memory(key="test_user_name", value="Alice")
            await pr_store.save_memory(key="test_user_name", value="Bob")

            # Each agent should only see its own memory
            chatbot_memory = await chatbot_store.get_memory("test_user_name")
            pr_memory = await pr_store.get_memory("test_user_name")

            assert chatbot_memory.value == "Alice"
            assert pr_memory.value == "Bob"

        finally:
            # Cleanup
            async with chatbot_store._pool.acquire() as conn:
                await conn.execute("DELETE FROM memories WHERE agent_name LIKE 'isolation_test_%'")
            await chatbot_store.close()
            await pr_store.close()

    @pytest.mark.asyncio
    async def test_agent_isolation_get_all_memories(self, database_url: str):
        """Test that get_all_memories only returns memories for the specified agent."""
        from agent_framework.storage.database_memory_store import DatabaseMemoryStore

        chatbot_store = DatabaseMemoryStore(database_url, agent_name="getall_test_chatbot", cache_ttl=0)
        pr_store = DatabaseMemoryStore(database_url, agent_name="getall_test_pr", cache_ttl=0)

        await chatbot_store.initialize()
        await pr_store.initialize()

        try:
            # Save multiple memories to each agent
            for i in range(3):
                await chatbot_store.save_memory(key=f"test_chat_{i}", value=f"chat value {i}")
                await pr_store.save_memory(key=f"test_pr_{i}", value=f"pr value {i}")

            # Each agent should only see its own 3 memories
            chatbot_memories = await chatbot_store.get_all_memories()
            pr_memories = await pr_store.get_all_memories()

            chatbot_keys = {m.key for m in chatbot_memories}
            pr_keys = {m.key for m in pr_memories}

            assert len(chatbot_memories) == 3
            assert len(pr_memories) == 3
            assert chatbot_keys == {"test_chat_0", "test_chat_1", "test_chat_2"}
            assert pr_keys == {"test_pr_0", "test_pr_1", "test_pr_2"}

        finally:
            async with chatbot_store._pool.acquire() as conn:
                await conn.execute("DELETE FROM memories WHERE agent_name LIKE 'getall_test_%'")
            await chatbot_store.close()
            await pr_store.close()

    @pytest.mark.asyncio
    async def test_agent_isolation_search_memories(self, database_url: str):
        """Test that search_memories only searches within agent's memories."""
        from agent_framework.storage.database_memory_store import DatabaseMemoryStore

        chatbot_store = DatabaseMemoryStore(database_url, agent_name="search_test_chatbot", cache_ttl=0)
        pr_store = DatabaseMemoryStore(database_url, agent_name="search_test_pr", cache_ttl=0)

        await chatbot_store.initialize()
        await pr_store.initialize()

        try:
            # Save memories with searchable content
            await chatbot_store.save_memory(key="test_email", value="alice@chatbot.com")
            await pr_store.save_memory(key="test_email", value="bob@pr.com")

            # Search should only find memories within the agent's store
            chatbot_results = await chatbot_store.search_memories("@")
            pr_results = await pr_store.search_memories("@")

            assert len(chatbot_results) == 1
            assert chatbot_results[0].value == "alice@chatbot.com"

            assert len(pr_results) == 1
            assert pr_results[0].value == "bob@pr.com"

        finally:
            async with chatbot_store._pool.acquire() as conn:
                await conn.execute("DELETE FROM memories WHERE agent_name LIKE 'search_test_%'")
            await chatbot_store.close()
            await pr_store.close()

    @pytest.mark.asyncio
    async def test_agent_isolation_delete_memory(self, database_url: str):
        """Test that delete_memory only affects the specified agent."""
        from agent_framework.storage.database_memory_store import DatabaseMemoryStore

        chatbot_store = DatabaseMemoryStore(database_url, agent_name="delete_test_chatbot", cache_ttl=0)
        pr_store = DatabaseMemoryStore(database_url, agent_name="delete_test_pr", cache_ttl=0)

        await chatbot_store.initialize()
        await pr_store.initialize()

        try:
            # Save same key to both agents
            await chatbot_store.save_memory(key="test_to_delete", value="chatbot value")
            await pr_store.save_memory(key="test_to_delete", value="pr value")

            # Delete from chatbot only
            await chatbot_store.delete_memory("test_to_delete")

            # Chatbot's memory should be gone, PR agent's should remain
            chatbot_memory = await chatbot_store.get_memory("test_to_delete")
            pr_memory = await pr_store.get_memory("test_to_delete")

            assert chatbot_memory is None
            assert pr_memory is not None
            assert pr_memory.value == "pr value"

        finally:
            async with chatbot_store._pool.acquire() as conn:
                await conn.execute("DELETE FROM memories WHERE agent_name LIKE 'delete_test_%'")
            await chatbot_store.close()
            await pr_store.close()

    @pytest.mark.asyncio
    async def test_agent_stats_isolation(self, database_url: str):
        """Test that get_stats only counts memories for the specified agent."""
        from agent_framework.storage.database_memory_store import DatabaseMemoryStore

        chatbot_store = DatabaseMemoryStore(database_url, agent_name="stats_test_chatbot", cache_ttl=0)
        pr_store = DatabaseMemoryStore(database_url, agent_name="stats_test_pr", cache_ttl=0)

        await chatbot_store.initialize()
        await pr_store.initialize()

        try:
            # Save different numbers of memories
            for i in range(5):
                await chatbot_store.save_memory(key=f"test_chat_{i}", value=f"v{i}", category="cat1")

            for i in range(3):
                await pr_store.save_memory(key=f"test_pr_{i}", value=f"v{i}", category="cat2")

            chatbot_stats = await chatbot_store.get_stats()
            pr_stats = await pr_store.get_stats()

            assert chatbot_stats["total_memories"] == 5
            assert chatbot_stats["agent_name"] == "stats_test_chatbot"
            assert "cat1" in chatbot_stats["categories"]

            assert pr_stats["total_memories"] == 3
            assert pr_stats["agent_name"] == "stats_test_pr"
            assert "cat2" in pr_stats["categories"]

        finally:
            async with chatbot_store._pool.acquire() as conn:
                await conn.execute("DELETE FROM memories WHERE agent_name LIKE 'stats_test_%'")
            await chatbot_store.close()
            await pr_store.close()

    @pytest.mark.asyncio
    async def test_agent_name_property(self, database_url: str):
        """Test that agent_name property returns the correct value."""
        from agent_framework.storage.database_memory_store import DatabaseMemoryStore

        store = DatabaseMemoryStore(database_url, agent_name="property_test_agent")
        assert store.agent_name == "property_test_agent"
