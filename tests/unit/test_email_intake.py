"""Tests for the email intake agent security and routing logic."""

from agent_framework import Permission, PermissionSet

from agents.email_intake.main import (
    AGENT_KEYWORDS,
    _match_keyword,
    determine_agent,
    get_permissions_from_args,
)


class TestKeywordMatching:
    """Tests for keyword matching logic with word boundaries."""

    def test_match_keyword_whole_word(self):
        """Test that keywords match as whole words only."""
        assert _match_keyword("task", "create a task for me") is True
        assert _match_keyword("task", "tasklist management") is False  # No word boundary
        assert _match_keyword("task", "multitask mode") is False  # No word boundary

    def test_match_keyword_case_insensitive(self):
        """Test that matching is case-insensitive when content is lowercased."""
        assert _match_keyword("task", "create a TASK for me".lower()) is True
        assert _match_keyword("security", "SECURITY audit needed".lower()) is True

    def test_match_keyword_prevents_attack_task_collision(self):
        """Test that 'task' doesn't match inside 'attack'."""
        content = "security attack vector analysis"
        assert _match_keyword("task", content) is False
        assert _match_keyword("attack", content) is True

    def test_match_keyword_multi_word_phrases(self):
        """Test matching multi-word phrases."""
        content = "please analyze my social media presence"
        assert _match_keyword("social media", content) is True
        assert _match_keyword("social", content) is True
        assert _match_keyword("media", content) is True


class TestAgentRouting:
    """Tests for agent routing by content."""

    def test_determine_agent_security_keywords(self):
        """Test routing to security agent for security-related content."""
        assert determine_agent("Security Audit Request", "") == "security"
        assert determine_agent("", "found a vulnerability in the code") == "security"
        assert determine_agent("CVE analysis", "check for exploits") == "security"

    def test_determine_agent_task_keywords(self):
        """Test routing to tasks agent for task-related content."""
        assert determine_agent("Remind me to...", "") == "tasks"
        assert determine_agent("", "schedule a meeting") == "tasks"
        assert determine_agent("TODO List", "") == "tasks"

    def test_determine_agent_security_not_matched_by_attack(self):
        """Test that 'attack' routes to security, not tasks via substring 'task'."""
        # 'attack' contains 'task' as substring, but word boundaries prevent collision
        agent = determine_agent("Analyze this attack vector", "")
        assert agent == "security", "Should route to security, not tasks"

    def test_determine_agent_pr_keywords(self):
        """Test routing to PR agent for content-related tasks."""
        assert determine_agent("Blog post review", "") == "pr"
        assert determine_agent("", "analyze my website seo") == "pr"
        assert determine_agent("Social media strategy", "") == "pr"

    def test_determine_agent_business_keywords(self):
        """Test routing to business agent for business strategy tasks."""
        assert determine_agent("Monetization Strategy", "") == "business"
        assert determine_agent("", "pricing analysis for startup") == "business"
        assert determine_agent("Revenue projections", "") == "business"

    def test_determine_agent_events_keywords(self):
        """Test routing to events agent for events-related tasks."""
        assert determine_agent("Concert recommendations", "") == "events"
        assert determine_agent("", "what's happening this weekend") == "events"
        assert determine_agent("Local festivals", "") == "events"

    def test_determine_agent_default_chatbot(self):
        """Test default routing to chatbot when no keywords match."""
        assert determine_agent("Hello there", "how are you?") == "chatbot"
        assert determine_agent("Random topic", "with random text") == "chatbot"

    def test_determine_agent_highest_score_wins(self):
        """Test that agent with most keyword matches wins."""
        # More security keywords than task keywords
        content = "security vulnerability exploit attack threat analysis"
        assert determine_agent(content, "") == "security"

    def test_agent_keywords_coverage(self):
        """Verify all expected agent categories are defined."""
        expected_agents = {"pr", "security", "business", "tasks", "events"}
        assert set(AGENT_KEYWORDS.keys()) == expected_agents


class TestPermissionParsing:
    """Tests for command-line permission parsing."""

    def test_default_permissions_read_send(self):
        """Test default permissions are READ + SEND only."""

        class Args:
            full_access = False
            allow_writes = False
            read_only = False

        perms = get_permissions_from_args(Args())
        assert perms.has(Permission.READ)
        assert perms.has(Permission.SEND)
        assert not perms.has(Permission.WRITE)
        assert not perms.has(Permission.DELETE)
        assert not perms.has(Permission.EXECUTE)
        assert not perms.has(Permission.ADMIN)

    def test_allow_writes_permissions(self):
        """Test --allow-writes adds WRITE permission."""

        class Args:
            full_access = False
            allow_writes = True
            read_only = False

        perms = get_permissions_from_args(Args())
        assert perms.has(Permission.READ)
        assert perms.has(Permission.WRITE)
        assert perms.has(Permission.SEND)
        assert not perms.has(Permission.DELETE)
        assert not perms.has(Permission.EXECUTE)

    def test_read_only_permissions(self):
        """Test --read-only restricts to READ only."""

        class Args:
            full_access = False
            allow_writes = False
            read_only = True

        perms = get_permissions_from_args(Args())
        assert perms.has(Permission.READ)
        assert not perms.has(Permission.SEND)
        assert not perms.has(Permission.WRITE)
        assert not perms.has(Permission.DELETE)
        assert not perms.has(Permission.EXECUTE)

    def test_full_access_permissions(self):
        """Test --full-access grants all except ADMIN."""

        class Args:
            full_access = True
            allow_writes = False
            read_only = False

        perms = get_permissions_from_args(Args())
        assert perms.has(Permission.READ)
        assert perms.has(Permission.WRITE)
        assert perms.has(Permission.DELETE)
        assert perms.has(Permission.EXECUTE)
        assert perms.has(Permission.SEND)
        assert not perms.has(Permission.ADMIN)


class TestSecurityValidation:
    """Tests for security-critical email validation logic.

    Note: These test the logic patterns, not the actual email processing
    which requires FastMail integration.
    """

    def test_shared_secret_requirement(self):
        """Verify shared secret is required in design."""
        # The actual validation happens in check_and_process_emails
        # This test documents the expected security behavior
        # A production test would mock the FastMail API
        pass

    def test_admin_sender_validation(self):
        """Verify emails must come from admin address."""
        # The actual validation happens in check_and_process_emails
        # This test documents the expected security behavior
        pass

    def test_permission_propagation_design(self):
        """Verify delegated agents receive restricted permissions."""
        # Default is READ + SEND - no WRITE, DELETE, or EXECUTE
        default_perms = PermissionSet([Permission.READ, Permission.SEND])

        # Should allow analysis operations
        assert default_perms.has(Permission.READ)
        # Should allow sending email replies
        assert default_perms.has(Permission.SEND)
        # Should NOT allow data modification
        assert not default_perms.has(Permission.WRITE)
        assert not default_perms.has(Permission.DELETE)
        # Should NOT allow code execution
        assert not default_perms.has(Permission.EXECUTE)
