"""Unit tests for shared/json_parsing.py - LLM output JSON extraction utilities."""

from shared.json_parsing import strip_and_parse_json, strip_markdown_fences


class TestStripAndParseJsonDirectParse:
    """Tests for direct JSON parsing (strategy 1: already clean JSON)."""

    def test_parse_simple_object(self):
        """Simple JSON object should parse directly."""
        result = strip_and_parse_json('{"key": "value"}')
        assert result == {"key": "value"}

    def test_parse_simple_array(self):
        """Simple JSON array should parse directly."""
        result = strip_and_parse_json("[1, 2, 3]")
        assert result == [1, 2, 3]

    def test_parse_nested_object(self):
        """Nested JSON object should parse directly."""
        text = '{"outer": {"inner": [1, 2, {"deep": true}]}}'
        result = strip_and_parse_json(text)
        assert result == {"outer": {"inner": [1, 2, {"deep": True}]}}

    def test_parse_array_of_objects(self):
        """Array of objects should parse directly."""
        text = '[{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]'
        result = strip_and_parse_json(text)
        assert result == [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]

    def test_parse_with_leading_trailing_whitespace(self):
        """JSON with surrounding whitespace should parse after strip."""
        result = strip_and_parse_json('  \n  {"key": "value"}  \n  ')
        assert result == {"key": "value"}

    def test_parse_empty_object(self):
        """Empty JSON object should parse."""
        result = strip_and_parse_json("{}")
        assert result == {}

    def test_parse_empty_array(self):
        """Empty JSON array should parse."""
        result = strip_and_parse_json("[]")
        assert result == []

    def test_parse_string_values_with_special_chars(self):
        """JSON with escaped characters should parse correctly."""
        text = '{"msg": "line1\\nline2", "path": "C:\\\\Users"}'
        result = strip_and_parse_json(text)
        assert result == {"msg": "line1\nline2", "path": "C:\\Users"}

    def test_parse_numeric_values(self):
        """JSON with various numeric types should parse."""
        text = '{"int": 42, "float": 3.14, "neg": -1, "sci": 1.5e10}'
        result = strip_and_parse_json(text)
        assert result["int"] == 42
        assert result["float"] == 3.14
        assert result["neg"] == -1
        assert result["sci"] == 1.5e10

    def test_parse_boolean_and_null(self):
        """JSON with boolean and null values should parse."""
        text = '{"yes": true, "no": false, "nothing": null}'
        result = strip_and_parse_json(text)
        assert result == {"yes": True, "no": False, "nothing": None}


class TestStripAndParseJsonMarkdownFences:
    """Tests for markdown fence stripping (strategy 2)."""

    def test_json_in_json_fence(self):
        """JSON wrapped in ```json fence should parse."""
        text = '```json\n{"key": "value"}\n```'
        result = strip_and_parse_json(text)
        assert result == {"key": "value"}

    def test_json_in_uppercase_json_fence(self):
        """JSON wrapped in ```JSON fence should parse."""
        text = '```JSON\n{"key": "value"}\n```'
        result = strip_and_parse_json(text)
        assert result == {"key": "value"}

    def test_json_in_plain_fence(self):
        """JSON wrapped in plain ``` fence (no language tag) should parse."""
        text = '```\n{"key": "value"}\n```'
        result = strip_and_parse_json(text)
        assert result == {"key": "value"}

    def test_array_in_json_fence(self):
        """Array wrapped in ```json fence should parse."""
        text = "```json\n[1, 2, 3]\n```"
        result = strip_and_parse_json(text)
        assert result == [1, 2, 3]

    def test_multiline_json_in_fence(self):
        """Multi-line JSON in a fence should parse."""
        text = '```json\n{\n  "name": "test",\n  "items": [\n    1,\n    2\n  ]\n}\n```'
        result = strip_and_parse_json(text)
        assert result == {"name": "test", "items": [1, 2]}

    def test_fence_with_surrounding_whitespace(self):
        """Fenced JSON with extra whitespace should parse."""
        text = '  \n```json\n  {"key": "value"}  \n```\n  '
        result = strip_and_parse_json(text)
        assert result == {"key": "value"}


class TestStripAndParseJsonFromProse:
    """Tests for JSON extraction from surrounding prose (strategy 3)."""

    def test_object_in_prose(self):
        """JSON object embedded in prose should be extracted."""
        text = 'Here is the result: {"status": "ok", "count": 5} Hope this helps!'
        result = strip_and_parse_json(text)
        assert result == {"status": "ok", "count": 5}

    def test_array_in_prose(self):
        """JSON array embedded in prose should be extracted."""
        text = "The items are: [1, 2, 3] as requested."
        result = strip_and_parse_json(text)
        assert result == [1, 2, 3]

    def test_object_with_leading_prose(self):
        """JSON object with only leading prose should be extracted."""
        text = 'Sure, here you go:\n{"key": "value"}'
        result = strip_and_parse_json(text)
        assert result == {"key": "value"}

    def test_object_with_trailing_prose(self):
        """JSON object with only trailing prose should be extracted."""
        text = '{"key": "value"}\nLet me know if you need anything else.'
        result = strip_and_parse_json(text)
        assert result == {"key": "value"}

    def test_nested_object_in_prose(self):
        """Nested JSON in prose should be extracted completely."""
        text = 'Result: {"outer": {"inner": [1, 2]}} done.'
        result = strip_and_parse_json(text)
        assert result == {"outer": {"inner": [1, 2]}}

    def test_object_preferred_over_array_when_both_present(self):
        """When both { and [ exist, the first { is tried first."""
        text = 'data: {"list": [1, 2]} extra [3, 4]'
        result = strip_and_parse_json(text)
        assert result == {"list": [1, 2]}

    def test_array_extracted_when_no_object(self):
        """When no { exists but [ does, array should be extracted."""
        text = "Here are items: [10, 20, 30] end."
        result = strip_and_parse_json(text)
        assert result == [10, 20, 30]


class TestStripAndParseJsonNoJsonFound:
    """Tests for cases where no valid JSON can be found."""

    def test_plain_text_returns_none(self):
        """Plain text without JSON should return None."""
        result = strip_and_parse_json("This is just plain text with no JSON.")
        assert result is None

    def test_empty_string_returns_none(self):
        """Empty string should return None."""
        result = strip_and_parse_json("")
        assert result is None

    def test_whitespace_only_returns_none(self):
        """Whitespace-only string should return None."""
        result = strip_and_parse_json("   \n\t  ")
        assert result is None

    def test_malformed_json_returns_none(self):
        """Malformed JSON should return None."""
        result = strip_and_parse_json('{"key": "value",}')
        assert result is None

    def test_incomplete_object_returns_none(self):
        """Incomplete JSON object should return None."""
        result = strip_and_parse_json('{"key": "value"')
        assert result is None

    def test_incomplete_array_returns_none(self):
        """Incomplete JSON array should return None."""
        result = strip_and_parse_json("[1, 2, 3")
        assert result is None

    def test_unbalanced_braces_in_prose_returns_none(self):
        """Unbalanced braces in prose should return None."""
        result = strip_and_parse_json("some text { but no closing brace")
        assert result is None

    def test_malformed_json_in_fence_falls_through(self):
        """Malformed JSON in a fence should fall through to strategy 3 or return None."""
        text = "```json\n{invalid json}\n```"
        result = strip_and_parse_json(text)
        assert result is None

    def test_single_backtick_group_not_a_fence(self):
        """Text with only one ``` group (not a pair) doesn't trigger fence logic."""
        text = "``` not a complete fence"
        result = strip_and_parse_json(text)
        assert result is None

    def test_braces_in_non_json_context(self):
        """Curly braces in non-JSON text (e.g., prose) should return None."""
        result = strip_and_parse_json("Use {variable} for substitution")
        assert result is None


class TestStripMarkdownFences:
    """Tests for the strip_markdown_fences helper function."""

    def test_strip_json_fence(self):
        """Should strip ```json and closing ```."""
        text = '```json\n{"key": "value"}\n```'
        result = strip_markdown_fences(text)
        assert result == '{"key": "value"}'

    def test_strip_plain_fence(self):
        """Should strip plain ``` fences."""
        text = "```\nsome content\n```"
        result = strip_markdown_fences(text)
        assert result == "some content"

    def test_strip_python_fence(self):
        """Should strip ```python and closing ```."""
        text = '```python\nprint("hello")\n```'
        result = strip_markdown_fences(text)
        assert result == 'print("hello")'

    def test_no_fences_returns_unchanged(self):
        """Text without fences should be returned unchanged (after strip)."""
        text = "plain text"
        result = strip_markdown_fences(text)
        assert result == "plain text"

    def test_only_opening_fence(self):
        """Text with only opening fence should strip it."""
        text = '```json\n{"key": "value"}'
        result = strip_markdown_fences(text)
        assert result == '{"key": "value"}'

    def test_only_closing_fence(self):
        """Text with only closing fence should strip it."""
        text = '{"key": "value"}\n```'
        result = strip_markdown_fences(text)
        assert result == '{"key": "value"}'

    def test_surrounding_whitespace_stripped(self):
        """Should strip surrounding whitespace."""
        text = '  \n```json\n{"key": "value"}\n```\n  '
        result = strip_markdown_fences(text)
        assert result == '{"key": "value"}'

    def test_empty_string(self):
        """Empty string should return empty string."""
        result = strip_markdown_fences("")
        assert result == ""

    def test_fence_without_newline(self):
        """Opening fence without newline should still strip the ```."""
        text = "```content```"
        result = strip_markdown_fences(text)
        assert result == "content"

    def test_multiline_content(self):
        """Multi-line content inside fences should be preserved."""
        text = "```\nline1\nline2\nline3\n```"
        result = strip_markdown_fences(text)
        assert result == "line1\nline2\nline3"
