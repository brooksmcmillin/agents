"""Query builder helpers for PostgreSQL queries with dynamic filters."""

import re
from typing import Any


class MetadataFilterBuilder:
    """Helper for building PostgreSQL queries with metadata JSONB filtering.

    This helper constructs WHERE clauses for filtering on JSONB metadata fields,
    managing parameter placeholders and values for safe parameterized queries.

    Example:
        builder = MetadataFilterBuilder(base_params=["embedding_vector"])
        builder.add_metadata_filter({"source": "docs", "version": "1.0"})

        query = f"SELECT * FROM documents WHERE {builder.get_where_clause()}"
        results = await conn.fetch(query, *builder.get_params())
    """

    def __init__(self, base_params: list[Any] | None = None):
        """Initialize the builder.

        Args:
            base_params: Initial parameters to include (e.g., embedding vectors).
                        The metadata filter params will be appended to this list.
        """
        self.params: list[Any] = base_params if base_params is not None else []
        self.conditions: list[str] = []

    def add_metadata_filter(self, metadata_filter: dict[str, Any]) -> "MetadataFilterBuilder":
        """Add metadata filtering conditions.

        Generates conditions like: metadata->>'key' = $N

        Args:
            metadata_filter: Dictionary of metadata key-value pairs to filter on.

        Returns:
            Self for method chaining.

        Raises:
            ValueError: If metadata key contains invalid characters (SQL injection protection).
        """
        for key, value in metadata_filter.items():
            # Validate key is a safe SQL identifier to prevent SQL injection
            # Allow only: letters, numbers, underscores, starting with letter or underscore
            if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", key):
                raise ValueError(
                    f"Invalid metadata key '{key}': must start with letter or underscore "
                    "and contain only letters, numbers, and underscores"
                )

            param_idx = len(self.params) + 1
            self.conditions.append(f"metadata->>'{key}' = ${param_idx}")
            self.params.append(str(value))
        return self

    def has_conditions(self) -> bool:
        """Check if any filter conditions have been added.

        Returns:
            True if conditions exist, False otherwise.
        """
        return len(self.conditions) > 0

    def get_where_clause(self) -> str:
        """Get the complete WHERE clause (without the 'WHERE' keyword).

        Returns:
            Joined conditions string, or empty string if no conditions.
        """
        return " AND ".join(self.conditions) if self.conditions else ""

    def get_params(self) -> list[Any]:
        """Get the parameter list for the query.

        Returns:
            List of all parameters (base_params + metadata filter params).
        """
        return self.params

    def build_query_with_filter(
        self,
        base_query: str,
        order_by: str = "",
        limit: int | None = None,
        offset: int | None = None,
    ) -> str:
        """Build complete query by appending WHERE, ORDER BY, LIMIT, and OFFSET.

        Args:
            base_query: Base SELECT query (e.g., "SELECT * FROM table")
            order_by: Optional ORDER BY clause (e.g., "created_at DESC")
            limit: Optional LIMIT value
            offset: Optional OFFSET value

        Returns:
            Complete SQL query string.
        """
        query = base_query

        if self.has_conditions():
            query += " WHERE " + self.get_where_clause()

        if order_by:
            query += f" ORDER BY {order_by}"

        if limit is not None:
            query += f" LIMIT {limit}"

        if offset is not None:
            query += f" OFFSET {offset}"

        return query
