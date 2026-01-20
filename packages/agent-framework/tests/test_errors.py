"""Tests for the error types module."""

import pytest

from agent_framework.utils.errors import (
    AgentError,
    AuthenticationError,
    ToolExecutionError,
    ValidationError,
)


class TestAgentError:
    """Tests for AgentError base exception."""

    def test_agent_error_creation(self):
        """Test creating an AgentError."""
        error = AgentError("Test error message")
        assert str(error) == "Test error message"

    def test_agent_error_is_exception(self):
        """Test that AgentError is an Exception."""
        error = AgentError("Test")
        assert isinstance(error, Exception)

    def test_agent_error_can_be_raised(self):
        """Test that AgentError can be raised and caught."""
        with pytest.raises(AgentError) as exc_info:
            raise AgentError("Raised error")
        assert str(exc_info.value) == "Raised error"


class TestValidationError:
    """Tests for ValidationError exception."""

    def test_validation_error_creation(self):
        """Test creating a ValidationError."""
        error = ValidationError("Invalid input")
        assert str(error) == "Invalid input"

    def test_validation_error_inheritance(self):
        """Test that ValidationError inherits from AgentError."""
        error = ValidationError("Test")
        assert isinstance(error, AgentError)
        assert isinstance(error, Exception)

    def test_validation_error_catch_as_agent_error(self):
        """Test that ValidationError can be caught as AgentError."""
        with pytest.raises(AgentError):
            raise ValidationError("Validation failed")


class TestAuthenticationError:
    """Tests for AuthenticationError exception."""

    def test_authentication_error_creation(self):
        """Test creating an AuthenticationError."""
        error = AuthenticationError("Auth failed")
        assert str(error) == "Auth failed"

    def test_authentication_error_inheritance(self):
        """Test that AuthenticationError inherits from AgentError."""
        error = AuthenticationError("Test")
        assert isinstance(error, AgentError)
        assert isinstance(error, Exception)

    def test_authentication_error_catch_as_agent_error(self):
        """Test that AuthenticationError can be caught as AgentError."""
        with pytest.raises(AgentError):
            raise AuthenticationError("Not authenticated")


class TestToolExecutionError:
    """Tests for ToolExecutionError exception."""

    def test_tool_execution_error_creation(self):
        """Test creating a ToolExecutionError."""
        error = ToolExecutionError("Tool failed")
        assert str(error) == "Tool failed"

    def test_tool_execution_error_inheritance(self):
        """Test that ToolExecutionError inherits from AgentError."""
        error = ToolExecutionError("Test")
        assert isinstance(error, AgentError)
        assert isinstance(error, Exception)

    def test_tool_execution_error_catch_as_agent_error(self):
        """Test that ToolExecutionError can be caught as AgentError."""
        with pytest.raises(AgentError):
            raise ToolExecutionError("Execution failed")


class TestErrorHierarchy:
    """Tests for the error class hierarchy."""

    def test_all_errors_derive_from_agent_error(self):
        """Test that all custom errors derive from AgentError."""
        errors = [
            ValidationError("test"),
            AuthenticationError("test"),
            ToolExecutionError("test"),
        ]

        for error in errors:
            assert isinstance(error, AgentError)

    def test_errors_can_be_distinguished(self):
        """Test that different error types can be distinguished."""
        errors = {
            "validation": ValidationError("validation"),
            "auth": AuthenticationError("auth"),
            "execution": ToolExecutionError("execution"),
        }

        assert isinstance(errors["validation"], ValidationError)
        assert not isinstance(errors["validation"], AuthenticationError)
        assert not isinstance(errors["validation"], ToolExecutionError)

        assert isinstance(errors["auth"], AuthenticationError)
        assert not isinstance(errors["auth"], ValidationError)
        assert not isinstance(errors["auth"], ToolExecutionError)

        assert isinstance(errors["execution"], ToolExecutionError)
        assert not isinstance(errors["execution"], ValidationError)
        assert not isinstance(errors["execution"], AuthenticationError)
