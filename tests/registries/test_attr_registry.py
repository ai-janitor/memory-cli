# =============================================================================
# Module: test_attr_registry.py
# Purpose: Test the attribute key registry CRUD operations — add, list, remove —
#   plus normalization, idempotent add, empty name rejection, and in-use block.
# Rationale: Attr keys follow the identical pattern to tags. This test file
#   mirrors test_tag_registry.py to verify the attr registry has the same
#   correctness guarantees. Cross-registry collision is explicitly tested to
#   confirm that a tag and attr key can share the same name.
# Responsibility:
#   - Verify attr_add creates new attr keys and returns correct dict
#   - Verify attr_add is idempotent (same name returns same entry)
#   - Verify normalization: lowercase, strip whitespace, preserve internal spaces
#   - Verify empty/whitespace-only names are rejected
#   - Verify attr_list returns all keys ordered by id, empty list is OK
#   - Verify attr_remove by name and by ID
#   - Verify attr_remove blocks when attr key is in use (referential integrity)
#   - Verify attr_remove returns False for not-found
#   - Verify attr_autocreate creates and returns ID
#   - Verify cross-registry collision is OK (same name in tags and attrs)
# Organization:
#   1. Imports and fixtures (in-memory DB with schema)
#   2. Test class: TestAttrAdd
#   3. Test class: TestAttrNormalization
#   4. Test class: TestAttrList
#   5. Test class: TestAttrRemove
#   6. Test class: TestAttrAutocreate
#   7. Test class: TestCrossRegistryCollision
# =============================================================================

from __future__ import annotations

import sqlite3

import pytest

from memory_cli.registries.attr_registry_crud_normalize_autocreate import (
    AttrRegistryError,
    attr_add,
    attr_autocreate,
    attr_list,
    attr_remove,
    normalize_attr_name,
)
from memory_cli.registries.tag_registry_crud_normalize_autocreate import tag_add


# -----------------------------------------------------------------------------
# Fixtures — in-memory SQLite DB with attr_keys and neuron_attrs schema.
# Every test gets a fresh database.
# -----------------------------------------------------------------------------


@pytest.fixture
def conn():
    """Create an in-memory SQLite DB with attr_keys, neuron_attrs, and tags tables.

    Schema:
    - attr_keys: id (auto PK), name (unique text), created_at (datetime default now)
    - neuron_attrs: neuron_id (int), attr_key_id (int FK to attr_keys.id), value (text)
      Used to simulate in-use references for removal blocking tests.
    - tags: same schema as attr_keys — included for cross-registry collision tests
    """
    # --- Setup ---
    # 1. Create in-memory connection
    # 2. CREATE TABLE attr_keys (id INTEGER PRIMARY KEY AUTOINCREMENT,
    #      name TEXT UNIQUE NOT NULL,
    #      created_at TEXT NOT NULL DEFAULT (datetime('now')))
    # 3. CREATE TABLE neuron_attrs (neuron_id INTEGER NOT NULL,
    #      attr_key_id INTEGER NOT NULL, value TEXT NOT NULL)
    # 4. CREATE TABLE tags (id INTEGER PRIMARY KEY AUTOINCREMENT,
    #      name TEXT UNIQUE NOT NULL,
    #      created_at TEXT NOT NULL DEFAULT (datetime('now')))
    # 5. Yield connection
    # 6. Close connection in teardown
    c = sqlite3.connect(":memory:")
    c.execute("""
        CREATE TABLE attr_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            created_at INTEGER NOT NULL DEFAULT 0
        )
    """)
    c.execute("""
        CREATE TABLE neuron_attrs (
            neuron_id INTEGER NOT NULL,
            attr_key_id INTEGER NOT NULL,
            value TEXT NOT NULL
        )
    """)
    c.execute("""
        CREATE TABLE tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            created_at INTEGER NOT NULL DEFAULT 0
        )
    """)
    yield c
    c.close()


# =============================================================================
# TestAttrAdd — creating attr keys, idempotency, return value shape
# =============================================================================
class TestAttrAdd:
    """Tests for attr_add function."""

    def test_add_new_attr_returns_dict_with_id_name_created_at(self, conn):
        """Adding a new attr key returns a dict with id, name, and created_at."""
        # 1. Call attr_add(conn, "priority")
        # 2. Assert result is a dict with id (int), name ("priority"), created_at (str)
        result = attr_add(conn, "priority")
        assert isinstance(result, dict)
        assert isinstance(result["id"], int)
        assert result["name"] == "priority"
        assert "created_at" in result

    def test_add_duplicate_attr_is_idempotent(self, conn):
        """Adding the same attr key twice returns the same entry both times."""
        # 1. attr_add(conn, "status") -> r1
        # 2. attr_add(conn, "status") -> r2
        # 3. Assert r1["id"] == r2["id"]
        r1 = attr_add(conn, "status")
        r2 = attr_add(conn, "status")
        assert r1["id"] == r2["id"]

    def test_add_case_variant_is_idempotent(self, conn):
        """Adding "Priority" after "priority" returns the same entry."""
        # 1. attr_add(conn, "priority") -> r1
        # 2. attr_add(conn, "Priority") -> r2
        # 3. Assert same id
        r1 = attr_add(conn, "priority")
        r2 = attr_add(conn, "Priority")
        assert r1["id"] == r2["id"]

    def test_add_multiple_attrs_get_distinct_ids(self, conn):
        """Different attr key names get different IDs."""
        # 1. attr_add(conn, "color") -> r1
        # 2. attr_add(conn, "size") -> r2
        # 3. Assert r1["id"] != r2["id"]
        r1 = attr_add(conn, "color")
        r2 = attr_add(conn, "size")
        assert r1["id"] != r2["id"]


# =============================================================================
# TestAttrNormalization — edge cases in name normalization
# =============================================================================
class TestAttrNormalization:
    """Tests for normalize_attr_name and rejection of invalid names."""

    def test_empty_string_rejected(self, conn):
        """Empty string raises AttrRegistryError."""
        # 1. attr_add(conn, "") -> expect AttrRegistryError
        with pytest.raises(AttrRegistryError):
            attr_add(conn, "")

    def test_whitespace_only_rejected(self, conn):
        """Whitespace-only string raises AttrRegistryError."""
        # 1. attr_add(conn, "   ") -> expect AttrRegistryError
        with pytest.raises(AttrRegistryError):
            attr_add(conn, "   ")

    def test_internal_whitespace_preserved(self, conn):
        """Attr key "due date" preserves the internal space."""
        # 1. attr_add(conn, "due date") -> result
        # 2. Assert result["name"] == "due date"
        result = attr_add(conn, "due date")
        assert result["name"] == "due date"

    def test_mixed_case_lowered(self, conn):
        """Attr key "DueDate" is stored as "duedate"."""
        # 1. attr_add(conn, "DueDate") -> result
        # 2. Assert result["name"] == "duedate"
        result = attr_add(conn, "DueDate")
        assert result["name"] == "duedate"


# =============================================================================
# TestAttrList — enumeration of all attr keys
# =============================================================================
class TestAttrList:
    """Tests for attr_list function."""

    def test_list_empty_registry_returns_empty_list(self, conn):
        """Empty registry returns [] not an error."""
        # 1. attr_list(conn) -> []
        assert attr_list(conn) == []

    def test_list_returns_all_attrs_ordered_by_id(self, conn):
        """Attr keys are returned in insertion order (by id)."""
        # 1. attr_add(conn, "zebra")
        # 2. attr_add(conn, "apple")
        # 3. attr_list(conn) -> result
        # 4. Assert result[0]["name"] == "zebra" (first inserted)
        # 5. Assert len(result) == 2
        attr_add(conn, "zebra")
        attr_add(conn, "apple")
        result = attr_list(conn)
        assert len(result) == 2
        assert result[0]["name"] == "zebra"


# =============================================================================
# TestAttrRemove — removal by name/id, not-found, in-use block
# =============================================================================
class TestAttrRemove:
    """Tests for attr_remove function."""

    def test_remove_by_name(self, conn):
        """Remove an attr key by its name."""
        # 1. attr_add(conn, "temp")
        # 2. attr_remove(conn, "temp") -> True
        # 3. attr_list(conn) -> empty
        attr_add(conn, "temp")
        result = attr_remove(conn, "temp")
        assert result is True
        assert attr_list(conn) == []

    def test_remove_by_id(self, conn):
        """Remove an attr key by its integer ID."""
        # 1. attr_add(conn, "byid") -> result
        # 2. attr_remove(conn, result["id"]) -> True
        added = attr_add(conn, "byid")
        result = attr_remove(conn, added["id"])
        assert result is True

    def test_remove_not_found_returns_false(self, conn):
        """Removing a non-existent attr key returns False."""
        # 1. attr_remove(conn, "ghost") -> False
        result = attr_remove(conn, "ghost")
        assert result is False

    def test_remove_in_use_blocked(self, conn):
        """Removing an attr key in use by neurons raises AttrRegistryError."""
        # 1. attr_add(conn, "locked") -> result
        # 2. INSERT INTO neuron_attrs (neuron_id, attr_key_id, value)
        #    VALUES (1, result["id"], "some value")
        # 3. attr_remove(conn, "locked") -> expect AttrRegistryError
        # 4. Verify attr key still in attr_list
        added = attr_add(conn, "locked")
        conn.execute(
            "INSERT INTO neuron_attrs (neuron_id, attr_key_id, value) VALUES (1, ?, 'some value')",
            (added["id"],)
        )
        with pytest.raises(AttrRegistryError):
            attr_remove(conn, "locked")
        remaining = attr_list(conn)
        assert any(a["name"] == "locked" for a in remaining)

    def test_remove_normalizes_name(self, conn):
        """Removing "  MyAttr  " matches stored "myattr"."""
        # 1. attr_add(conn, "myattr")
        # 2. attr_remove(conn, "  MyAttr  ") -> True
        attr_add(conn, "myattr")
        result = attr_remove(conn, "  MyAttr  ")
        assert result is True


# =============================================================================
# TestAttrAutocreate — auto-create on reference
# =============================================================================
class TestAttrAutocreate:
    """Tests for attr_autocreate function."""

    def test_autocreate_new_attr_returns_id(self, conn):
        """Auto-creating a new attr key returns its integer ID."""
        # 1. attr_autocreate(conn, "newkey") -> attr_id
        # 2. Assert attr_id is int
        # 3. Verify exists in attr_list
        attr_id = attr_autocreate(conn, "newkey")
        assert isinstance(attr_id, int)
        attrs = attr_list(conn)
        assert any(a["id"] == attr_id and a["name"] == "newkey" for a in attrs)

    def test_autocreate_existing_attr_returns_same_id(self, conn):
        """Auto-creating an existing attr key is idempotent."""
        # 1. attr_add(conn, "existing") -> result
        # 2. attr_autocreate(conn, "existing") -> attr_id
        # 3. Assert attr_id == result["id"]
        result = attr_add(conn, "existing")
        attr_id = attr_autocreate(conn, "existing")
        assert attr_id == result["id"]

    def test_autocreate_empty_name_rejected(self, conn):
        """Auto-create rejects empty names."""
        # 1. attr_autocreate(conn, "") -> expect AttrRegistryError
        with pytest.raises(AttrRegistryError):
            attr_autocreate(conn, "")


# =============================================================================
# TestCrossRegistryCollision — tags and attrs can share names
# =============================================================================
class TestCrossRegistryCollision:
    """Verify that a tag and attr key can have the same name without conflict."""

    def test_same_name_in_both_registries(self, conn):
        """A tag "status" and attr key "status" coexist with independent IDs."""
        # 1. tag_add(conn, "status") -> tag_result  (need tags table + tag_add import)
        # 2. attr_add(conn, "status") -> attr_result
        # 3. Both succeed — no conflict
        # 4. IDs are independent (they're in different tables, so may be same int)
        # 5. Names are both "status"
        tag_result = tag_add(conn, "status")
        attr_result = attr_add(conn, "status")
        assert tag_result["name"] == "status"
        assert attr_result["name"] == "status"
        # Both entries exist independently in their respective tables
        assert tag_result["id"] is not None
        assert attr_result["id"] is not None
