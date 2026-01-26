"""Tests for shared task utilities.

Tests cover task result parsing, priority normalization, and emoji formatting
for task management features used across agents.
"""

import json

import pytest

from shared.task_utils import format_priority_emoji, parse_priority, parse_task_result


class TestParseTaskResult:
    """Tests for parse_task_result function."""

    def test_parse_json_string_with_tasks(self):
        """Test parsing valid JSON string containing tasks."""
        json_string = json.dumps(
            {
                "tasks": [
                    {"id": 1, "title": "Task 1"},
                    {"id": 2, "title": "Task 2"},
                ]
            }
        )

        result = parse_task_result(json_string)

        assert len(result) == 2
        assert result[0]["id"] == 1
        assert result[0]["title"] == "Task 1"
        assert result[1]["id"] == 2
        assert result[1]["title"] == "Task 2"

    def test_parse_dict_with_tasks(self):
        """Test parsing dict directly."""
        data = {
            "tasks": [
                {"id": 1, "title": "Task 1"},
                {"id": 2, "title": "Task 2"},
            ]
        }

        result = parse_task_result(data)

        assert len(result) == 2
        assert result[0]["id"] == 1
        assert result[1]["id"] == 2

    def test_parse_empty_tasks_list(self):
        """Test parsing result with empty tasks list."""
        data = {"tasks": []}

        result = parse_task_result(data)

        assert result == []

    def test_parse_missing_tasks_key(self):
        """Test parsing result without tasks key returns empty list."""
        data = {"other_data": "value"}

        result = parse_task_result(data)

        assert result == []

    def test_parse_json_string_missing_tasks_key(self):
        """Test parsing JSON string without tasks key."""
        json_string = json.dumps({"other_data": "value"})

        result = parse_task_result(json_string)

        assert result == []

    def test_parse_complex_task_structure(self):
        """Test parsing tasks with complex nested structure."""
        data = {
            "tasks": [
                {
                    "id": 1,
                    "title": "Complex Task",
                    "priority": "high",
                    "tags": ["work", "urgent"],
                    "metadata": {"created_by": "user1"},
                }
            ]
        }

        result = parse_task_result(data)

        assert len(result) == 1
        assert result[0]["id"] == 1
        assert result[0]["title"] == "Complex Task"
        assert result[0]["priority"] == "high"
        assert result[0]["tags"] == ["work", "urgent"]
        assert result[0]["metadata"]["created_by"] == "user1"

    def test_parse_invalid_json_string_raises_error(self):
        """Test that invalid JSON string raises JSONDecodeError."""
        invalid_json = "not valid json {{"

        with pytest.raises(json.JSONDecodeError):
            parse_task_result(invalid_json)

    def test_parse_json_string_with_unicode(self):
        """Test parsing JSON with unicode characters."""
        json_string = json.dumps({"tasks": [{"id": 1, "title": "Task with émojis 🎯"}]})

        result = parse_task_result(json_string)

        assert len(result) == 1
        assert result[0]["title"] == "Task with émojis 🎯"

    def test_parse_preserves_task_order(self):
        """Test that task order is preserved."""
        data = {
            "tasks": [
                {"id": 3, "title": "Third"},
                {"id": 1, "title": "First"},
                {"id": 2, "title": "Second"},
            ]
        }

        result = parse_task_result(data)

        assert result[0]["id"] == 3
        assert result[1]["id"] == 1
        assert result[2]["id"] == 2


class TestParsePriority:
    """Tests for parse_priority function."""

    # --- None and Default Values ---

    def test_parse_none_returns_default(self):
        """Test that None returns default priority of 5."""
        assert parse_priority(None) == 5

    # --- Integer Priority Values ---

    def test_parse_integer_low_priority(self):
        """Test parsing low integer priority."""
        assert parse_priority(1) == 1
        assert parse_priority(2) == 2

    def test_parse_integer_medium_priority(self):
        """Test parsing medium integer priority."""
        assert parse_priority(5) == 5

    def test_parse_integer_high_priority(self):
        """Test parsing high integer priority."""
        assert parse_priority(8) == 8
        assert parse_priority(9) == 9
        assert parse_priority(10) == 10

    def test_parse_integer_boundary_values(self):
        """Test edge case integer values."""
        assert parse_priority(0) == 0
        assert parse_priority(7) == 7
        assert parse_priority(11) == 11  # Outside 1-10 range but valid int

    # --- Numeric String Priority Values ---

    def test_parse_numeric_string(self):
        """Test parsing numeric strings."""
        assert parse_priority("1") == 1
        assert parse_priority("5") == 5
        assert parse_priority("9") == 9
        assert parse_priority("10") == 10

    def test_parse_numeric_string_with_whitespace(self):
        """Test parsing numeric strings with whitespace."""
        assert parse_priority("  5  ") == 5
        assert parse_priority("\t8\n") == 8

    # --- Text Priority Values (urgent/high/critical) ---

    def test_parse_text_urgent(self):
        """Test parsing 'urgent' text priority."""
        assert parse_priority("urgent") == 9

    def test_parse_text_high(self):
        """Test parsing 'high' text priority."""
        assert parse_priority("high") == 9

    def test_parse_text_critical(self):
        """Test parsing 'critical' text priority."""
        assert parse_priority("critical") == 9

    # --- Text Priority Values (medium/normal) ---

    def test_parse_text_medium(self):
        """Test parsing 'medium' text priority."""
        assert parse_priority("medium") == 5

    def test_parse_text_normal(self):
        """Test parsing 'normal' text priority."""
        assert parse_priority("normal") == 5

    # --- Text Priority Values (low) ---

    def test_parse_text_low(self):
        """Test parsing 'low' text priority."""
        assert parse_priority("low") == 2

    # --- Case Insensitivity ---

    def test_parse_text_case_insensitive(self):
        """Test that text priority parsing is case insensitive."""
        assert parse_priority("URGENT") == 9
        assert parse_priority("High") == 9
        assert parse_priority("CrItIcAl") == 9
        assert parse_priority("MEDIUM") == 5
        assert parse_priority("Normal") == 5
        assert parse_priority("LOW") == 2

    # --- Unknown/Invalid Text Values ---

    def test_parse_unknown_text_returns_default(self):
        """Test that unknown text values return default priority."""
        assert parse_priority("unknown") == 5
        assert parse_priority("whatever") == 5
        assert parse_priority("") == 5
        assert parse_priority("priority") == 5

    def test_parse_invalid_numeric_string_returns_default(self):
        """Test that non-numeric strings return default priority."""
        assert parse_priority("abc") == 5
        assert parse_priority("12.5") == 5  # Float string not supported
        assert parse_priority("1a") == 5

    # --- Type Handling ---

    def test_parse_float_converts_to_string_then_default(self):
        """Test that float values are handled."""
        # Floats aren't directly handled as ints, so they go through string conversion
        result = parse_priority(5.5)
        # Should convert to string "5.5", fail int conversion, return default
        assert result == 5

    def test_parse_boolean_converts_to_int(self):
        """Test boolean values (since bool is subclass of int in Python)."""
        # In Python, True == 1 and False == 0, and isinstance(True, int) is True
        assert parse_priority(True) == 1
        assert parse_priority(False) == 0

    def test_parse_list_converts_to_string_default(self):
        """Test that list value returns default."""
        result = parse_priority([1, 2, 3])
        assert result == 5

    def test_parse_dict_converts_to_string_default(self):
        """Test that dict value returns default."""
        result = parse_priority({"priority": 5})
        assert result == 5

    # --- Whitespace in Text Values ---

    def test_parse_text_with_leading_trailing_whitespace(self):
        """Test text priority with whitespace.

        Note: Current implementation does not strip whitespace from text
        priorities, so these return default value. This could be improved
        by adding .strip() to line 63 of task_utils.py.
        """
        # Current behavior - whitespace not stripped, returns default
        assert parse_priority("  urgent  ") == 5
        assert parse_priority("\tlow\n") == 5
        assert parse_priority(" medium ") == 5

        # These work because int() strips whitespace automatically
        assert parse_priority("  9  ") == 9

    # --- Edge Cases from Examples ---

    def test_examples_from_docstring(self):
        """Test all examples from the function docstring."""
        assert parse_priority(9) == 9
        assert parse_priority("7") == 7
        assert parse_priority("urgent") == 9
        assert parse_priority("low") == 2
        assert parse_priority(None) == 5


class TestFormatPriorityEmoji:
    """Tests for format_priority_emoji function."""

    def test_high_priority_emoji(self):
        """Test emoji for high priority (>= 8)."""
        assert format_priority_emoji(8) == ":exclamation:"
        assert format_priority_emoji(9) == ":exclamation:"
        assert format_priority_emoji(10) == ":exclamation:"

    def test_low_priority_emoji(self):
        """Test emoji for low/medium priority (< 8)."""
        assert format_priority_emoji(1) == ":small_orange_diamond:"
        assert format_priority_emoji(2) == ":small_orange_diamond:"
        assert format_priority_emoji(5) == ":small_orange_diamond:"
        assert format_priority_emoji(7) == ":small_orange_diamond:"

    def test_boundary_value(self):
        """Test the boundary at priority 8."""
        assert format_priority_emoji(7) == ":small_orange_diamond:"
        assert format_priority_emoji(8) == ":exclamation:"

    def test_edge_case_zero(self):
        """Test priority 0."""
        assert format_priority_emoji(0) == ":small_orange_diamond:"

    def test_edge_case_negative(self):
        """Test negative priority."""
        assert format_priority_emoji(-1) == ":small_orange_diamond:"

    def test_edge_case_very_high(self):
        """Test very high priority values."""
        assert format_priority_emoji(100) == ":exclamation:"
        assert format_priority_emoji(1000) == ":exclamation:"

    def test_examples_from_docstring(self):
        """Test examples from the function docstring."""
        assert format_priority_emoji(9) == ":exclamation:"
        assert format_priority_emoji(5) == ":small_orange_diamond:"


class TestTaskUtilsIntegration:
    """Integration tests combining multiple task utility functions."""

    def test_parse_and_format_workflow(self):
        """Test typical workflow of parsing tasks and formatting priorities."""
        json_result = json.dumps(
            {
                "tasks": [
                    {"id": 1, "title": "Urgent task", "priority": "urgent"},
                    {"id": 2, "title": "Normal task", "priority": 5},
                    {"id": 3, "title": "Low priority", "priority": "low"},
                ]
            }
        )

        tasks = parse_task_result(json_result)

        assert len(tasks) == 3

        # Parse priorities and format emojis
        priority_1 = parse_priority(tasks[0]["priority"])
        emoji_1 = format_priority_emoji(priority_1)
        assert priority_1 == 9
        assert emoji_1 == ":exclamation:"

        priority_2 = parse_priority(tasks[1]["priority"])
        emoji_2 = format_priority_emoji(priority_2)
        assert priority_2 == 5
        assert emoji_2 == ":small_orange_diamond:"

        priority_3 = parse_priority(tasks[2]["priority"])
        emoji_3 = format_priority_emoji(priority_3)
        assert priority_3 == 2
        assert emoji_3 == ":small_orange_diamond:"

    def test_parse_tasks_with_various_priority_formats(self):
        """Test parsing tasks with mixed priority formats."""
        data = {
            "tasks": [
                {"id": 1, "priority": 9},
                {"id": 2, "priority": "5"},
                {"id": 3, "priority": "high"},
                {"id": 4, "priority": None},
            ]
        }

        tasks = parse_task_result(data)

        priorities = [parse_priority(task["priority"]) for task in tasks]

        assert priorities == [9, 5, 9, 5]
