# =============================================================================
# Module: test_tag_registry.py
# Purpose: Test the tag registry CRUD operations — add, list, remove — plus
#   normalization, idempotent add, empty name rejection, and in-use block.
# Rationale: Tags are the primary classification mechanism. If add is not
#   idempotent, neuron add will break. If remove doesn't check references,
#   orphaned tag IDs will appear in neuron_tags. If normalization is wrong,
#   duplicate tags will proliferate. Every edge case matters.
# Responsibility:
#   - Verify tag_add creates new tags and returns correct dict
#   - Verify tag_add is idempotent (same name returns same entry)
#   - Verify normalization: lowercase, strip whitespace, preserve internal spaces
#   - Verify empty/whitespace-only names are rejected
#   - Verify tag_list returns all tags ordered by id, empty list is OK
#   - Verify tag_remove by name and by ID
#   - Verify tag_remove blocks when tag is in use (referential integrity)
#   - Verify tag_remove returns False for not-found
#   - Verify tag_autocreate creates and returns ID
# Organization:
#   1. Imports and fixtures (in-memory DB with schema)
#   2. Test class: TestTagAdd
#   3. Test class: TestTagNormalization
#   4. Test class: TestTagList
#   5. Test class: TestTagRemove
#   6. Test class: TestTagAutocreate
# =============================================================================

from __future__ import annotations

import sqlite3

import pytest

from memory_cli.registries.tag_registry_crud_normalize_autocreate import (
    TagRegistryError,
    normalize_tag_name,
    tag_add,
    tag_autocreate,
    tag_list,
    tag_remove,
)


# -----------------------------------------------------------------------------
# Fixtures — in-memory SQLite DB with the tags and neuron_tags schema.
# Every test gets a fresh database.
# -----------------------------------------------------------------------------


@pytest.fixture
def conn():
    """Create an in-memory SQLite DB with tags and neuron_tags tables.

    Schema:
    - tags: id (auto PK), name (unique text), created_at (datetime default now)
    - neuron_tags: neuron_id (int), tag_id (int FK to tags.id)
      Used to simulate in-use references for removal blocking tests.
    """
    # --- Setup ---
    # 1. Create in-memory connection
    # 2. CREATE TABLE tags (id INTEGER PRIMARY KEY AUTOINCREMENT,
    #      name TEXT UNIQUE NOT NULL,
    #      created_at TEXT NOT NULL DEFAULT (datetime('now')))
    # 3. CREATE TABLE neuron_tags (neuron_id INTEGER NOT NULL,
    #      tag_id INTEGER NOT NULL)
    # 4. Yield connection
    # 5. Close connection in teardown
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
    yield c
    c.close()


# =============================================================================
# TestTagAdd — creating tags, idempotency, return value shape
# =============================================================================
class TestTagAdd:
    """Tests for tag_add function."""

    def test_add_new_tag_returns_dict_with_id_name_created_at(self, conn):
        """Adding a new tag returns a dict with id, name, and created_at keys."""
        # 1. Call tag_add(conn, "project")
        # 2. Assert result is a dict
        # 3. Assert "id" key exists and is int
        # 4. Assert "name" key equals "project"
        # 5. Assert "created_at" key exists and is non-empty string
        result = tag_add(conn, "project")
        assert isinstance(result, dict)
        assert isinstance(result["id"], int)
        assert result["name"] == "project"
        assert "created_at" in result
        assert result["created_at"] is not None

    def test_add_duplicate_tag_is_idempotent(self, conn):
        """Adding the same tag name twice returns the same entry both times."""
        # 1. Call tag_add(conn, "important") -> result1
        # 2. Call tag_add(conn, "important") -> result2
        # 3. Assert result1["id"] == result2["id"]
        # 4. Assert result1["name"] == result2["name"]
        result1 = tag_add(conn, "important")
        result2 = tag_add(conn, "important")
        assert result1["id"] == result2["id"]
        assert result1["name"] == result2["name"]

    def test_add_case_variant_is_idempotent(self, conn):
        """Adding "Urgent" after "urgent" returns the same entry (normalization)."""
        # 1. Call tag_add(conn, "urgent") -> result1
        # 2. Call tag_add(conn, "Urgent") -> result2
        # 3. Assert same id (normalization made them the same)
        result1 = tag_add(conn, "urgent")
        result2 = tag_add(conn, "Urgent")
        assert result1["id"] == result2["id"]

    def test_add_whitespace_variant_is_idempotent(self, conn):
        """Adding "  todo  " after "todo" returns the same entry."""
        # 1. Call tag_add(conn, "todo") -> result1
        # 2. Call tag_add(conn, "  todo  ") -> result2
        # 3. Assert same id
        result1 = tag_add(conn, "todo")
        result2 = tag_add(conn, "  todo  ")
        assert result1["id"] == result2["id"]

    def test_add_multiple_tags_get_distinct_ids(self, conn):
        """Different tag names get different IDs."""
        # 1. tag_add(conn, "alpha") -> r1
        # 2. tag_add(conn, "beta") -> r2
        # 3. Assert r1["id"] != r2["id"]
        r1 = tag_add(conn, "alpha")
        r2 = tag_add(conn, "beta")
        assert r1["id"] != r2["id"]


# =============================================================================
# TestTagNormalization — edge cases in name normalization
# =============================================================================
class TestTagNormalization:
    """Tests for normalize_tag_name and rejection of invalid names."""

    def test_empty_string_rejected(self, conn):
        """Empty string raises TagRegistryError."""
        # 1. Call tag_add(conn, "") -> expect TagRegistryError
        with pytest.raises(TagRegistryError):
            tag_add(conn, "")

    def test_whitespace_only_rejected(self, conn):
        """Whitespace-only string raises TagRegistryError."""
        # 1. Call tag_add(conn, "   ") -> expect TagRegistryError
        with pytest.raises(TagRegistryError):
            tag_add(conn, "   ")

    def test_internal_whitespace_preserved(self, conn):
        """Tag "my project" preserves the internal space."""
        # 1. Call tag_add(conn, "my project") -> result
        # 2. Assert result["name"] == "my project"
        result = tag_add(conn, "my project")
        assert result["name"] == "my project"

    def test_mixed_case_lowered(self, conn):
        """Tag "FooBar" is stored as "foobar"."""
        # 1. Call tag_add(conn, "FooBar") -> result
        # 2. Assert result["name"] == "foobar"
        result = tag_add(conn, "FooBar")
        assert result["name"] == "foobar"

    def test_leading_trailing_whitespace_stripped(self, conn):
        """Tag "  hello  " is stored as "hello"."""
        # 1. Call tag_add(conn, "  hello  ") -> result
        # 2. Assert result["name"] == "hello"
        result = tag_add(conn, "  hello  ")
        assert result["name"] == "hello"


# =============================================================================
# TestTagList — enumeration of all tags
# =============================================================================
class TestTagList:
    """Tests for tag_list function."""

    def test_list_empty_registry_returns_empty_list(self, conn):
        """Empty registry returns [] not an error."""
        # 1. Call tag_list(conn) -> result
        # 2. Assert result == []
        result = tag_list(conn)
        assert result == []

    def test_list_returns_all_tags_ordered_by_id(self, conn):
        """Tags are returned in insertion order (by id)."""
        # 1. tag_add(conn, "charlie")
        # 2. tag_add(conn, "alpha")
        # 3. tag_add(conn, "bravo")
        # 4. Call tag_list(conn) -> result
        # 5. Assert len(result) == 3
        # 6. Assert result[0]["name"] == "charlie" (first inserted, lowest id)
        # 7. Assert IDs are monotonically increasing
        tag_add(conn, "charlie")
        tag_add(conn, "alpha")
        tag_add(conn, "bravo")
        result = tag_list(conn)
        assert len(result) == 3
        assert result[0]["name"] == "charlie"
        assert result[1]["name"] == "alpha"
        assert result[2]["name"] == "bravo"
        assert result[0]["id"] < result[1]["id"] < result[2]["id"]

    def test_list_entries_have_correct_shape(self, conn):
        """Each entry has id, name, and created_at."""
        # 1. tag_add(conn, "test")
        # 2. tag_list(conn) -> result
        # 3. Assert each entry has keys: id, name, created_at
        tag_add(conn, "test")
        result = tag_list(conn)
        for entry in result:
            assert "id" in entry
            assert "name" in entry
            assert "created_at" in entry


# =============================================================================
# TestTagRemove — removal by name/id, not-found, in-use block
# =============================================================================
class TestTagRemove:
    """Tests for tag_remove function."""

    def test_remove_by_name(self, conn):
        """Remove a tag by its name."""
        # 1. tag_add(conn, "deleteme")
        # 2. tag_remove(conn, "deleteme") -> True
        # 3. tag_list(conn) -> empty list
        tag_add(conn, "deleteme")
        result = tag_remove(conn, "deleteme")
        assert result is True
        assert tag_list(conn) == []

    def test_remove_by_id(self, conn):
        """Remove a tag by its integer ID."""
        # 1. tag_add(conn, "byid") -> result, get id
        # 2. tag_remove(conn, result["id"]) -> True
        # 3. tag_list(conn) -> empty list
        added = tag_add(conn, "byid")
        result = tag_remove(conn, added["id"])
        assert result is True
        assert tag_list(conn) == []

    def test_remove_by_string_id(self, conn):
        """Remove using a string that parses as int, e.g., "1"."""
        # 1. tag_add(conn, "stringid") -> result
        # 2. tag_remove(conn, str(result["id"])) -> True
        added = tag_add(conn, "stringid")
        result = tag_remove(conn, str(added["id"]))
        assert result is True

    def test_remove_not_found_returns_false(self, conn):
        """Removing a tag that doesn't exist returns False."""
        # 1. tag_remove(conn, "nonexistent") -> False
        result = tag_remove(conn, "nonexistent")
        assert result is False

    def test_remove_not_found_by_id_returns_false(self, conn):
        """Removing a non-existent ID returns False."""
        # 1. tag_remove(conn, 9999) -> False
        result = tag_remove(conn, 9999)
        assert result is False

    def test_remove_in_use_blocked(self, conn):
        """Removing a tag referenced by neurons raises TagRegistryError."""
        # 1. tag_add(conn, "inuse") -> result
        # 2. INSERT INTO neuron_tags (neuron_id, tag_id) VALUES (1, result["id"])
        # 3. tag_remove(conn, "inuse") -> expect TagRegistryError
        # 4. Verify tag still exists in tag_list
        added = tag_add(conn, "inuse")
        conn.execute(
            "INSERT INTO neuron_tags (neuron_id, tag_id) VALUES (1, ?)",
            (added["id"],)
        )
        with pytest.raises(TagRegistryError):
            tag_remove(conn, "inuse")
        # Verify tag still exists
        remaining = tag_list(conn)
        assert any(t["name"] == "inuse" for t in remaining)

    def test_remove_normalizes_name(self, conn):
        """Removing "  MyTag  " matches stored "mytag"."""
        # 1. tag_add(conn, "mytag")
        # 2. tag_remove(conn, "  MyTag  ") -> True
        tag_add(conn, "mytag")
        result = tag_remove(conn, "  MyTag  ")
        assert result is True


# =============================================================================
# TestTagAutocreate — auto-create on reference
# =============================================================================
class TestTagAutocreate:
    """Tests for tag_autocreate function."""

    def test_autocreate_new_tag_returns_id(self, conn):
        """Auto-creating a new tag returns its integer ID."""
        # 1. tag_autocreate(conn, "auto") -> tag_id
        # 2. Assert tag_id is an int
        # 3. Verify tag exists in tag_list
        tag_id = tag_autocreate(conn, "auto")
        assert isinstance(tag_id, int)
        tags = tag_list(conn)
        assert any(t["id"] == tag_id and t["name"] == "auto" for t in tags)

    def test_autocreate_existing_tag_returns_same_id(self, conn):
        """Auto-creating an existing tag returns the same ID (idempotent)."""
        # 1. tag_add(conn, "existing") -> result
        # 2. tag_autocreate(conn, "existing") -> tag_id
        # 3. Assert tag_id == result["id"]
        result = tag_add(conn, "existing")
        tag_id = tag_autocreate(conn, "existing")
        assert tag_id == result["id"]

    def test_autocreate_normalizes_name(self, conn):
        """Auto-create normalizes the name before creating."""
        # 1. tag_autocreate(conn, "  NEW TAG  ") -> id1
        # 2. tag_autocreate(conn, "new tag") -> id2
        # 3. Assert id1 == id2
        id1 = tag_autocreate(conn, "  NEW TAG  ")
        id2 = tag_autocreate(conn, "new tag")
        assert id1 == id2

    def test_autocreate_empty_name_rejected(self, conn):
        """Auto-create rejects empty names."""
        # 1. tag_autocreate(conn, "") -> expect TagRegistryError
        with pytest.raises(TagRegistryError):
            tag_autocreate(conn, "")
