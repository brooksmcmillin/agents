"""Tests for query_builder SQL injection validation."""

import pytest
from agent_framework.storage.query_builder import MetadataFilterBuilder


class TestMetadataKeyValidation:
    """Tests for MetadataFilterBuilder key validation (SQL injection protection)."""

    def test_reject_key_with_sql_injection_semicolon(self):
        """Key containing semicolons and SQL commands should be rejected."""
        builder = MetadataFilterBuilder()
        with pytest.raises(ValueError, match="Invalid metadata key"):
            builder.add_metadata_filter({"'; DROP TABLE users--": "val"})

    def test_reject_key_with_equals_sign(self):
        """Key containing equals sign should be rejected."""
        builder = MetadataFilterBuilder()
        with pytest.raises(ValueError, match="Invalid metadata key"):
            builder.add_metadata_filter({"key=value": "val"})

    def test_reject_key_with_backticks(self):
        """Key containing backticks should be rejected."""
        builder = MetadataFilterBuilder()
        with pytest.raises(ValueError, match="Invalid metadata key"):
            builder.add_metadata_filter({"`injected`": "val"})

    def test_reject_key_with_single_quotes(self):
        """Key containing single quotes should be rejected."""
        builder = MetadataFilterBuilder()
        with pytest.raises(ValueError, match="Invalid metadata key"):
            builder.add_metadata_filter({"key'injection": "val"})

    def test_reject_key_with_double_quotes(self):
        """Key containing double quotes should be rejected."""
        builder = MetadataFilterBuilder()
        with pytest.raises(ValueError, match="Invalid metadata key"):
            builder.add_metadata_filter({'key"injection': "val"})

    def test_reject_key_with_spaces(self):
        """Key containing spaces should be rejected."""
        builder = MetadataFilterBuilder()
        with pytest.raises(ValueError, match="Invalid metadata key"):
            builder.add_metadata_filter({"key name": "val"})

    def test_reject_key_with_parentheses(self):
        """Key containing parentheses should be rejected."""
        builder = MetadataFilterBuilder()
        with pytest.raises(ValueError, match="Invalid metadata key"):
            builder.add_metadata_filter({"key()": "val"})

    def test_reject_key_with_dash(self):
        """Key containing dashes should be rejected."""
        builder = MetadataFilterBuilder()
        with pytest.raises(ValueError, match="Invalid metadata key"):
            builder.add_metadata_filter({"key-name": "val"})

    def test_reject_key_starting_with_digit(self):
        """Key starting with a digit should be rejected."""
        builder = MetadataFilterBuilder()
        with pytest.raises(ValueError, match="Invalid metadata key"):
            builder.add_metadata_filter({"1column": "val"})

    def test_reject_key_starting_with_digit_only(self):
        """Key that is just digits should be rejected."""
        builder = MetadataFilterBuilder()
        with pytest.raises(ValueError, match="Invalid metadata key"):
            builder.add_metadata_filter({"123": "val"})

    def test_reject_empty_key(self):
        """Empty string key should be rejected."""
        builder = MetadataFilterBuilder()
        with pytest.raises(ValueError, match="Invalid metadata key"):
            builder.add_metadata_filter({"": "val"})

    def test_accept_valid_alpha_key(self):
        """Simple alphabetic key should be accepted."""
        builder = MetadataFilterBuilder()
        builder.add_metadata_filter({"source": "docs"})
        assert builder.has_conditions()
        assert "source" in builder.get_where_clause()

    def test_accept_valid_key_with_underscore(self):
        """Key with underscores should be accepted."""
        builder = MetadataFilterBuilder()
        builder.add_metadata_filter({"created_by": "admin"})
        assert builder.has_conditions()
        assert "created_by" in builder.get_where_clause()

    def test_accept_valid_key_starting_with_underscore(self):
        """Key starting with underscore should be accepted."""
        builder = MetadataFilterBuilder()
        builder.add_metadata_filter({"_internal": "true"})
        assert builder.has_conditions()
        assert "_internal" in builder.get_where_clause()

    def test_accept_valid_key_with_digits(self):
        """Key containing digits (not leading) should be accepted."""
        builder = MetadataFilterBuilder()
        builder.add_metadata_filter({"version2": "latest"})
        assert builder.has_conditions()
        assert "version2" in builder.get_where_clause()

    def test_accept_valid_key_mixed_case(self):
        """Key with mixed case should be accepted."""
        builder = MetadataFilterBuilder()
        builder.add_metadata_filter({"CamelCase": "value"})
        assert builder.has_conditions()
        assert "CamelCase" in builder.get_where_clause()

    def test_multiple_valid_filters(self):
        """Multiple valid filters should all be added."""
        builder = MetadataFilterBuilder()
        builder.add_metadata_filter({"source": "docs", "version": "1"})
        assert len(builder.conditions) == 2
        assert len(builder.params) == 2

    def test_invalid_key_in_multi_filter_rejects_all(self):
        """If any key is invalid in a dict, ValueError is raised mid-iteration."""
        builder = MetadataFilterBuilder()
        # Depending on dict iteration order, the invalid key may be hit first or second.
        # Either way, a ValueError should be raised.
        with pytest.raises(ValueError, match="Invalid metadata key"):
            builder.add_metadata_filter({"valid_key": "ok", "1bad": "nope"})


class TestOrderByInjectionProtection:
    """Tests for ORDER BY clause SQL injection protection."""

    def test_reject_order_by_with_semicolon(self):
        """ORDER BY containing semicolons should be rejected."""
        builder = MetadataFilterBuilder()
        with pytest.raises(ValueError, match="Invalid order_by"):
            builder.build_query_with_filter("SELECT * FROM t", order_by="id; DROP TABLE t")

    def test_reject_order_by_with_comment(self):
        """ORDER BY containing SQL comments should be rejected."""
        builder = MetadataFilterBuilder()
        with pytest.raises(ValueError, match="Invalid order_by"):
            builder.build_query_with_filter("SELECT * FROM t", order_by="id -- comment")

    def test_reject_order_by_with_parentheses(self):
        """ORDER BY containing function calls should be rejected."""
        builder = MetadataFilterBuilder()
        with pytest.raises(ValueError, match="Invalid order_by"):
            builder.build_query_with_filter("SELECT * FROM t", order_by="SLEEP(5)")

    def test_reject_order_by_with_comma(self):
        """ORDER BY containing comma (multi-column) should be rejected."""
        builder = MetadataFilterBuilder()
        with pytest.raises(ValueError, match="Invalid order_by"):
            builder.build_query_with_filter("SELECT * FROM t", order_by="col1, col2")

    def test_reject_order_by_with_subquery(self):
        """ORDER BY containing subquery syntax should be rejected."""
        builder = MetadataFilterBuilder()
        with pytest.raises(ValueError, match="Invalid order_by"):
            builder.build_query_with_filter("SELECT * FROM t", order_by="(SELECT 1 FROM users)")

    def test_reject_order_by_starting_with_digit(self):
        """ORDER BY starting with a digit should be rejected."""
        builder = MetadataFilterBuilder()
        with pytest.raises(ValueError, match="Invalid order_by"):
            builder.build_query_with_filter("SELECT * FROM t", order_by="1")

    def test_reject_order_by_with_union(self):
        """ORDER BY containing UNION injection should be rejected."""
        builder = MetadataFilterBuilder()
        with pytest.raises(ValueError, match="Invalid order_by"):
            builder.build_query_with_filter(
                "SELECT * FROM t", order_by="id UNION SELECT * FROM secrets"
            )

    def test_accept_valid_order_by_column(self):
        """Simple column name should be accepted."""
        builder = MetadataFilterBuilder()
        query = builder.build_query_with_filter("SELECT * FROM t", order_by="created_at")
        assert "ORDER BY created_at" in query

    def test_accept_valid_order_by_asc(self):
        """Column with ASC should be accepted."""
        builder = MetadataFilterBuilder()
        query = builder.build_query_with_filter("SELECT * FROM t", order_by="name ASC")
        assert "ORDER BY name ASC" in query

    def test_accept_valid_order_by_desc(self):
        """Column with DESC should be accepted."""
        builder = MetadataFilterBuilder()
        query = builder.build_query_with_filter("SELECT * FROM t", order_by="updated_at DESC")
        assert "ORDER BY updated_at DESC" in query

    def test_accept_order_by_desc_case_insensitive(self):
        """Column with lowercase desc should be accepted."""
        builder = MetadataFilterBuilder()
        query = builder.build_query_with_filter("SELECT * FROM t", order_by="id desc")
        assert "ORDER BY id desc" in query

    def test_empty_order_by_skipped(self):
        """Empty order_by should not add ORDER BY clause."""
        builder = MetadataFilterBuilder()
        query = builder.build_query_with_filter("SELECT * FROM t", order_by="")
        assert "ORDER BY" not in query

    def test_build_query_full(self):
        """Full query with WHERE, ORDER BY, LIMIT, and OFFSET."""
        builder = MetadataFilterBuilder(base_params=["vec"])
        builder.add_metadata_filter({"source": "docs"})
        query = builder.build_query_with_filter(
            "SELECT * FROM documents",
            order_by="created_at DESC",
            limit=10,
            offset=20,
        )
        assert "WHERE" in query
        assert "ORDER BY created_at DESC" in query
        assert "LIMIT 10" in query
        assert "OFFSET 20" in query
