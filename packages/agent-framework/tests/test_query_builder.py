"""Tests for MetadataFilterBuilder SQL injection protection and query building."""

import pytest

from agent_framework.storage.query_builder import MetadataFilterBuilder


class TestMetadataFilterValidation:
    """Test SQL injection guards on metadata keys."""

    def test_valid_key_accepted(self) -> None:
        builder = MetadataFilterBuilder()
        builder.add_metadata_filter({"source": "docs"})
        assert builder.has_conditions()

    def test_valid_key_with_underscore_prefix(self) -> None:
        builder = MetadataFilterBuilder()
        builder.add_metadata_filter({"_private": "val"})
        assert builder.has_conditions()

    def test_valid_key_with_numbers(self) -> None:
        builder = MetadataFilterBuilder()
        builder.add_metadata_filter({"field2_name": "val"})
        assert builder.has_conditions()

    def test_rejects_sql_injection_in_key(self) -> None:
        builder = MetadataFilterBuilder()
        with pytest.raises(ValueError, match="Invalid metadata key"):
            builder.add_metadata_filter({"key'; DROP TABLE memories; --": "val"})

    def test_rejects_key_starting_with_digit(self) -> None:
        builder = MetadataFilterBuilder()
        with pytest.raises(ValueError, match="Invalid metadata key"):
            builder.add_metadata_filter({"1key": "val"})

    def test_rejects_key_with_spaces(self) -> None:
        builder = MetadataFilterBuilder()
        with pytest.raises(ValueError, match="Invalid metadata key"):
            builder.add_metadata_filter({"bad key": "val"})

    def test_rejects_key_with_special_chars(self) -> None:
        builder = MetadataFilterBuilder()
        with pytest.raises(ValueError, match="Invalid metadata key"):
            builder.add_metadata_filter({"key-name": "val"})

    def test_rejects_empty_key(self) -> None:
        builder = MetadataFilterBuilder()
        with pytest.raises(ValueError, match="Invalid metadata key"):
            builder.add_metadata_filter({"": "val"})

    def test_rejects_key_with_quotes(self) -> None:
        builder = MetadataFilterBuilder()
        with pytest.raises(ValueError, match="Invalid metadata key"):
            builder.add_metadata_filter({"key'value": "val"})

    def test_rejects_key_with_semicolon(self) -> None:
        builder = MetadataFilterBuilder()
        with pytest.raises(ValueError, match="Invalid metadata key"):
            builder.add_metadata_filter({"key;": "val"})


class TestMetadataFilterBuilding:
    """Test parameterized query construction."""

    def test_no_conditions_returns_empty(self) -> None:
        builder = MetadataFilterBuilder()
        assert builder.get_where_clause() == ""
        assert not builder.has_conditions()

    def test_single_condition(self) -> None:
        builder = MetadataFilterBuilder()
        builder.add_metadata_filter({"source": "docs"})
        assert builder.get_where_clause() == "metadata->>'source' = $1"
        assert builder.get_params() == ["docs"]

    def test_multiple_conditions(self) -> None:
        builder = MetadataFilterBuilder()
        builder.add_metadata_filter({"source": "docs", "version": "1.0"})
        clause = builder.get_where_clause()
        assert "metadata->>'source' = $1" in clause
        assert "metadata->>'version' = $2" in clause
        assert " AND " in clause
        assert builder.get_params() == ["docs", "1.0"]

    def test_base_params_offset_placeholders(self) -> None:
        builder = MetadataFilterBuilder(base_params=["embedding_vec"])
        builder.add_metadata_filter({"source": "docs"})
        assert builder.get_where_clause() == "metadata->>'source' = $2"
        assert builder.get_params() == ["embedding_vec", "docs"]

    def test_values_are_stringified(self) -> None:
        builder = MetadataFilterBuilder()
        builder.add_metadata_filter({"count": 42})
        assert builder.get_params() == ["42"]

    def test_method_chaining(self) -> None:
        builder = MetadataFilterBuilder()
        result = builder.add_metadata_filter({"a": "1"})
        assert result is builder


class TestBuildQueryWithFilter:
    """Test full query building with ORDER BY, LIMIT, OFFSET."""

    def test_base_query_no_filters(self) -> None:
        builder = MetadataFilterBuilder()
        query = builder.build_query_with_filter("SELECT * FROM docs")
        assert query == "SELECT * FROM docs"

    def test_query_with_where_clause(self) -> None:
        builder = MetadataFilterBuilder()
        builder.add_metadata_filter({"source": "docs"})
        query = builder.build_query_with_filter("SELECT * FROM docs")
        assert query == "SELECT * FROM docs WHERE metadata->>'source' = $1"

    def test_query_with_order_by(self) -> None:
        builder = MetadataFilterBuilder()
        query = builder.build_query_with_filter("SELECT * FROM docs", order_by="created_at DESC")
        assert "ORDER BY created_at DESC" in query

    def test_query_with_order_by_asc(self) -> None:
        builder = MetadataFilterBuilder()
        query = builder.build_query_with_filter("SELECT * FROM docs", order_by="name ASC")
        assert "ORDER BY name ASC" in query

    def test_query_with_limit_and_offset(self) -> None:
        builder = MetadataFilterBuilder()
        query = builder.build_query_with_filter("SELECT * FROM docs", limit=10, offset=20)
        assert "LIMIT 10" in query
        assert "OFFSET 20" in query

    def test_query_with_all_clauses(self) -> None:
        builder = MetadataFilterBuilder(base_params=["vec"])
        builder.add_metadata_filter({"source": "docs"})
        query = builder.build_query_with_filter(
            "SELECT * FROM docs", order_by="created_at DESC", limit=10, offset=5
        )
        assert "WHERE metadata->>'source' = $2" in query
        assert "ORDER BY created_at DESC" in query
        assert "LIMIT 10" in query
        assert "OFFSET 5" in query

    def test_order_by_rejects_sql_injection(self) -> None:
        builder = MetadataFilterBuilder()
        with pytest.raises(ValueError, match="Invalid order_by"):
            builder.build_query_with_filter(
                "SELECT * FROM docs", order_by="created_at; DROP TABLE docs"
            )

    def test_order_by_rejects_subquery(self) -> None:
        builder = MetadataFilterBuilder()
        with pytest.raises(ValueError, match="Invalid order_by"):
            builder.build_query_with_filter("SELECT * FROM docs", order_by="(SELECT 1)")

    def test_order_by_rejects_multiple_columns(self) -> None:
        builder = MetadataFilterBuilder()
        with pytest.raises(ValueError, match="Invalid order_by"):
            builder.build_query_with_filter("SELECT * FROM docs", order_by="col1, col2")

    def test_order_by_column_only(self) -> None:
        builder = MetadataFilterBuilder()
        query = builder.build_query_with_filter("SELECT * FROM docs", order_by="created_at")
        assert "ORDER BY created_at" in query
