# =============================================================================
# Module: test_tag_filter_and_or.py
# Purpose: Test the AND/OR tag filtering primitives — specifier resolution,
#   SQL fragment generation, empty filter pass-through, and the convenience
#   apply_tag_filter function.
# Rationale: Tag filtering is the primary search narrowing mechanism. If AND
#   filter produces wrong SQL, searches return too many or too few results.
#   If OR filter has a bug, any-tag queries break. If empty filter doesn't
#   pass through, unfiltered searches fail. Resolution failures must surface
#   clearly so users know which tag name/ID was bad.
# Responsibility:
#   - Test resolve_tag_specifiers: name resolution, ID resolution, not-found error
#   - Test build_and_filter: correct SQL shape, param count, empty pass-through
#   - Test build_or_filter: correct SQL shape, param count, empty pass-through
#   - Test apply_tag_filter: end-to-end convenience function
# Organization:
#   1. Imports and fixtures
#   2. Test class: TestResolveTagSpecifiers
#   3. Test class: TestBuildAndFilter
#   4. Test class: TestBuildOrFilter
#   5. Test class: TestApplyTagFilter
# =============================================================================

from __future__ import annotations

import sqlite3

import pytest

from memory_cli.registries.tag_filter_and_or_primitives import (
    TagFilterError,
    apply_tag_filter,
    build_and_filter,
    build_or_filter,
    resolve_tag_specifiers,
)


# -----------------------------------------------------------------------------
# Fixtures — in-memory SQLite DB with tags and neuron_tags for filter testing.
# -----------------------------------------------------------------------------


@pytest.fixture
def conn():
    """Create an in-memory SQLite DB with tags and neuron_tags tables.

    Seed tags:
    - id=1, name="python"
    - id=2, name="rust"
    - id=3, name="meeting"

    Seed neuron_tags (for integration-style filter tests):
    - neuron 10 has tags: python, rust       (IDs 1, 2)
    - neuron 20 has tags: python, meeting    (IDs 1, 3)
    - neuron 30 has tags: rust               (ID 2)
    - neuron 40 has no tags
    """
    # --- Setup ---
    # 1. Create in-memory connection
    # 2. CREATE TABLE tags (...)
    # 3. CREATE TABLE neuron_tags (neuron_id INTEGER, tag_id INTEGER)
    # 4. INSERT seed tags
    # 5. INSERT seed neuron_tags associations
    # 6. Yield connection
    # 7. Close in teardown
    c = sqlite3.connect(":memory:")
    c.execute("""
        CREATE TABLE tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            created_at INTEGER NOT NULL DEFAULT 0
        )
    """)
    c.execute("""
        CREATE TABLE neuron_tags (
            neuron_id INTEGER NOT NULL,
            tag_id INTEGER NOT NULL
        )
    """)
    # Seed tags: id=1 "python", id=2 "rust", id=3 "meeting"
    c.execute("INSERT INTO tags (name, created_at) VALUES ('python', 1000)")
    c.execute("INSERT INTO tags (name, created_at) VALUES ('rust', 1000)")
    c.execute("INSERT INTO tags (name, created_at) VALUES ('meeting', 1000)")
    # Seed neuron_tags
    # neuron 10: python (1), rust (2)
    c.execute("INSERT INTO neuron_tags (neuron_id, tag_id) VALUES (10, 1)")
    c.execute("INSERT INTO neuron_tags (neuron_id, tag_id) VALUES (10, 2)")
    # neuron 20: python (1), meeting (3)
    c.execute("INSERT INTO neuron_tags (neuron_id, tag_id) VALUES (20, 1)")
    c.execute("INSERT INTO neuron_tags (neuron_id, tag_id) VALUES (20, 3)")
    # neuron 30: rust (2)
    c.execute("INSERT INTO neuron_tags (neuron_id, tag_id) VALUES (30, 2)")
    # neuron 40: no tags
    yield c
    c.close()


# =============================================================================
# TestResolveTagSpecifiers — resolve names/IDs to tag IDs
# =============================================================================
class TestResolveTagSpecifiers:
    """Tests for resolve_tag_specifiers function."""

    def test_resolve_names(self, conn):
        """Resolving tag names returns their integer IDs."""
        # 1. resolve_tag_specifiers(conn, ["python", "rust"])
        # 2. Assert result == [1, 2]
        result = resolve_tag_specifiers(conn, ["python", "rust"])
        assert result == [1, 2]

    def test_resolve_ids(self, conn):
        """Resolving string-encoded IDs returns those IDs as ints."""
        # 1. resolve_tag_specifiers(conn, ["1", "3"])
        # 2. Assert result == [1, 3]
        result = resolve_tag_specifiers(conn, ["1", "3"])
        assert result == [1, 3]

    def test_resolve_mixed_names_and_ids(self, conn):
        """Resolving a mix of names and IDs works."""
        # 1. resolve_tag_specifiers(conn, ["python", "3"])
        # 2. Assert result == [1, 3]
        result = resolve_tag_specifiers(conn, ["python", "3"])
        assert result == [1, 3]

    def test_resolve_nonexistent_name_raises(self, conn):
        """Resolving a name that doesn't exist raises TagFilterError."""
        # 1. resolve_tag_specifiers(conn, ["python", "nonexistent"])
        # 2. Expect TagFilterError
        with pytest.raises(TagFilterError):
            resolve_tag_specifiers(conn, ["python", "nonexistent"])

    def test_resolve_nonexistent_id_raises(self, conn):
        """Resolving an ID that doesn't exist raises TagFilterError."""
        # 1. resolve_tag_specifiers(conn, ["9999"])
        # 2. Expect TagFilterError
        with pytest.raises(TagFilterError):
            resolve_tag_specifiers(conn, ["9999"])

    def test_resolve_empty_list(self, conn):
        """Resolving an empty list returns an empty list."""
        # 1. resolve_tag_specifiers(conn, [])
        # 2. Assert result == []
        result = resolve_tag_specifiers(conn, [])
        assert result == []

    def test_resolve_normalizes_names(self, conn):
        """Resolving "  PYTHON  " finds tag "python" via normalization."""
        # 1. resolve_tag_specifiers(conn, ["  PYTHON  "])
        # 2. Assert result == [1]
        result = resolve_tag_specifiers(conn, ["  PYTHON  "])
        assert result == [1]


# =============================================================================
# TestBuildAndFilter — SQL generation for AND (must have all)
# =============================================================================
class TestBuildAndFilter:
    """Tests for build_and_filter function."""

    def test_empty_ids_returns_passthrough(self):
        """Empty tag ID list returns empty SQL and empty params."""
        # 1. build_and_filter([])
        # 2. Assert sql == "" and params == []
        sql, params = build_and_filter([])
        assert sql == ""
        assert params == []

    def test_single_tag_sql_shape(self):
        """Single tag produces SQL with one placeholder and HAVING COUNT = 1."""
        # 1. build_and_filter([1]) -> (sql, params)
        # 2. Assert sql contains "tag_id IN" with one placeholder
        # 3. Assert sql contains "HAVING COUNT"
        # 4. Assert params includes tag ID and count
        sql, params = build_and_filter([1])
        assert "tag_id IN" in sql
        assert "HAVING COUNT" in sql
        assert 1 in params

    def test_multiple_tags_sql_shape(self):
        """Multiple tags produce SQL with correct placeholder count."""
        # 1. build_and_filter([1, 2, 3]) -> (sql, params)
        # 2. Assert sql has 3 placeholders in IN clause
        # 3. Assert params == [1, 2, 3, 3] (tag IDs + count)
        sql, params = build_and_filter([1, 2, 3])
        assert sql.count("?") == 4  # 3 for IN + 1 for HAVING count
        assert params == [1, 2, 3, 3]

    def test_and_filter_returns_string_and_list(self):
        """Return type is (str, list[int])."""
        # 1. build_and_filter([1]) -> (sql, params)
        # 2. Assert isinstance(sql, str)
        # 3. Assert isinstance(params, list)
        sql, params = build_and_filter([1])
        assert isinstance(sql, str)
        assert isinstance(params, list)


# =============================================================================
# TestBuildOrFilter — SQL generation for OR (must have any)
# =============================================================================
class TestBuildOrFilter:
    """Tests for build_or_filter function."""

    def test_empty_ids_returns_passthrough(self):
        """Empty tag ID list returns empty SQL and empty params."""
        # 1. build_or_filter([])
        # 2. Assert sql == "" and params == []
        sql, params = build_or_filter([])
        assert sql == ""
        assert params == []

    def test_single_tag_sql_shape(self):
        """Single tag produces SQL with one placeholder, no HAVING."""
        # 1. build_or_filter([1]) -> (sql, params)
        # 2. Assert sql contains "tag_id IN"
        # 3. Assert sql does NOT contain "HAVING"
        # 4. Assert params == [1]
        sql, params = build_or_filter([1])
        assert "tag_id IN" in sql
        assert "HAVING" not in sql
        assert params == [1]

    def test_multiple_tags_sql_shape(self):
        """Multiple tags produce SQL with correct placeholder count."""
        # 1. build_or_filter([1, 2]) -> (sql, params)
        # 2. Assert 2 placeholders
        # 3. Assert params == [1, 2]
        sql, params = build_or_filter([1, 2])
        assert sql.count("?") == 2
        assert params == [1, 2]


# =============================================================================
# TestApplyTagFilter — end-to-end convenience function
# =============================================================================
class TestApplyTagFilter:
    """Tests for apply_tag_filter function."""

    def test_empty_specifiers_passthrough(self, conn):
        """Empty specifier list returns passthrough (no filter)."""
        # 1. apply_tag_filter(conn, [], mode="and")
        # 2. Assert sql == "" and params == []
        sql, params = apply_tag_filter(conn, [], mode="and")
        assert sql == ""
        assert params == []

    def test_none_specifiers_passthrough(self, conn):
        """None specifier list returns passthrough."""
        # 1. apply_tag_filter(conn, None, mode="and")  (if supported)
        # 2. Assert sql == "" and params == []
        sql, params = apply_tag_filter(conn, None, mode="and")
        assert sql == ""
        assert params == []

    def test_and_mode_produces_and_filter(self, conn):
        """mode="and" produces AND filter SQL."""
        # 1. apply_tag_filter(conn, ["python", "rust"], mode="and")
        # 2. Assert sql contains "HAVING COUNT"
        sql, params = apply_tag_filter(conn, ["python", "rust"], mode="and")
        assert "HAVING COUNT" in sql

    def test_or_mode_produces_or_filter(self, conn):
        """mode="or" produces OR filter SQL."""
        # 1. apply_tag_filter(conn, ["python", "rust"], mode="or")
        # 2. Assert sql does NOT contain "HAVING"
        # 3. Assert sql contains "tag_id IN"
        sql, params = apply_tag_filter(conn, ["python", "rust"], mode="or")
        assert "HAVING" not in sql
        assert "tag_id IN" in sql

    def test_invalid_mode_raises(self, conn):
        """Invalid mode raises ValueError."""
        # 1. apply_tag_filter(conn, ["python"], mode="xor")
        # 2. Expect ValueError
        with pytest.raises(ValueError):
            apply_tag_filter(conn, ["python"], mode="xor")

    def test_unresolvable_tag_raises(self, conn):
        """Specifier that can't be resolved raises TagFilterError."""
        # 1. apply_tag_filter(conn, ["nonexistent"], mode="and")
        # 2. Expect TagFilterError
        with pytest.raises(TagFilterError):
            apply_tag_filter(conn, ["nonexistent"], mode="and")
