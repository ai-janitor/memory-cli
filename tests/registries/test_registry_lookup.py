# =============================================================================
# Module: test_registry_lookup.py
# Purpose: Test the shared lookup logic — resolve by name (with normalization
#   and optional auto-create) vs by ID (strict, no auto-create), and the
#   name-or-id dispatcher.
# Rationale: Lookup is the glue between user input and registry entries. If
#   name lookup doesn't normalize, users get "not found" for case variants.
#   If ID lookup auto-creates, random ints spawn garbage entries. If the
#   dispatcher misclassifies "42abc" as an ID, lookups fail. Each path needs
#   explicit testing.
# Responsibility:
#   - Test lookup_by_name with and without auto-create
#   - Test lookup_by_id success and not-found
#   - Test resolve_name_or_id dispatch logic (int detection, name fallback)
#   - Test normalization is applied in name lookups
#   - Test RegistryLookupError is raised correctly
# Organization:
#   1. Imports and fixtures
#   2. Test class: TestLookupByName
#   3. Test class: TestLookupById
#   4. Test class: TestResolveNameOrId
# =============================================================================

from __future__ import annotations

import sqlite3

import pytest

from memory_cli.registries.registry_lookup_by_name_or_id import (
    RegistryLookupError,
    lookup_by_id,
    lookup_by_name,
    resolve_name_or_id,
)
from memory_cli.registries.tag_registry_crud_normalize_autocreate import (
    normalize_tag_name,
)


# -----------------------------------------------------------------------------
# Fixtures — in-memory SQLite DB with tags table pre-populated.
# -----------------------------------------------------------------------------


@pytest.fixture
def conn():
    """Create an in-memory SQLite DB with tags table and some seed data.

    Seed data:
    - id=1, name="project"
    - id=2, name="urgent"
    - id=3, name="meeting notes"
    """
    # --- Setup ---
    # 1. Create in-memory connection
    # 2. CREATE TABLE tags (id INTEGER PRIMARY KEY AUTOINCREMENT,
    #      name TEXT UNIQUE NOT NULL,
    #      created_at TEXT NOT NULL DEFAULT (datetime('now')))
    # 3. INSERT seed rows: "project", "urgent", "meeting notes"
    # 4. Yield connection
    # 5. Close in teardown
    c = sqlite3.connect(":memory:")
    c.execute("""
        CREATE TABLE tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            created_at INTEGER NOT NULL DEFAULT 0
        )
    """)
    c.execute("INSERT INTO tags (name, created_at) VALUES ('project', 1000)")
    c.execute("INSERT INTO tags (name, created_at) VALUES ('urgent', 1000)")
    c.execute("INSERT INTO tags (name, created_at) VALUES ('meeting notes', 1000)")
    yield c
    c.close()


# =============================================================================
# TestLookupByName — name-based resolution with normalization + auto-create
# =============================================================================
class TestLookupByName:
    """Tests for lookup_by_name function."""

    def test_lookup_existing_name(self, conn):
        """Looking up an existing name returns the correct row."""
        # 1. lookup_by_name(conn, "tags", "project", normalize_tag_name)
        # 2. Assert result["name"] == "project"
        # 3. Assert result["id"] == 1
        result = lookup_by_name(conn, "tags", "project", normalize_tag_name)
        assert result["name"] == "project"
        assert result["id"] == 1

    def test_lookup_name_with_normalization(self, conn):
        """Looking up "  URGENT  " finds "urgent" via normalization."""
        # 1. lookup_by_name(conn, "tags", "  URGENT  ", normalize_tag_name)
        # 2. Assert result["name"] == "urgent"
        result = lookup_by_name(conn, "tags", "  URGENT  ", normalize_tag_name)
        assert result["name"] == "urgent"

    def test_lookup_missing_name_with_autocreate(self, conn):
        """Looking up a non-existent name with autocreate=True creates it."""
        # 1. lookup_by_name(conn, "tags", "newtag", normalize_tag_name, autocreate=True)
        # 2. Assert result["name"] == "newtag"
        # 3. Assert result["id"] is an int > 0
        # 4. Verify it now exists in the table
        result = lookup_by_name(conn, "tags", "newtag", normalize_tag_name, autocreate=True)
        assert result["name"] == "newtag"
        assert isinstance(result["id"], int) and result["id"] > 0
        row = conn.execute("SELECT id FROM tags WHERE name = 'newtag'").fetchone()
        assert row is not None

    def test_lookup_missing_name_without_autocreate_raises(self, conn):
        """Looking up a non-existent name with autocreate=False raises error."""
        # 1. lookup_by_name(conn, "tags", "ghost", normalize_tag_name, autocreate=False)
        # 2. Expect RegistryLookupError
        with pytest.raises(RegistryLookupError):
            lookup_by_name(conn, "tags", "ghost", normalize_tag_name, autocreate=False)

    def test_lookup_autocreate_is_idempotent(self, conn):
        """Auto-creating an existing name returns the existing entry."""
        # 1. lookup_by_name(conn, "tags", "project", normalize_tag_name, autocreate=True)
        # 2. Assert result["id"] == 1 (pre-existing, not a new entry)
        result = lookup_by_name(conn, "tags", "project", normalize_tag_name, autocreate=True)
        assert result["id"] == 1


# =============================================================================
# TestLookupById — strict ID-based resolution
# =============================================================================
class TestLookupById:
    """Tests for lookup_by_id function."""

    def test_lookup_existing_id(self, conn):
        """Looking up an existing ID returns the correct row."""
        # 1. lookup_by_id(conn, "tags", 1)
        # 2. Assert result["name"] == "project"
        result = lookup_by_id(conn, "tags", 1)
        assert result["name"] == "project"

    def test_lookup_missing_id_raises(self, conn):
        """Looking up a non-existent ID raises RegistryLookupError."""
        # 1. lookup_by_id(conn, "tags", 9999) -> expect RegistryLookupError
        with pytest.raises(RegistryLookupError):
            lookup_by_id(conn, "tags", 9999)

    def test_lookup_id_never_autocreates(self, conn):
        """ID lookup for non-existent ID raises, never creates an entry."""
        # 1. lookup_by_id(conn, "tags", 100) -> expect RegistryLookupError
        # 2. Verify no new row was created (SELECT COUNT(*) = 3)
        with pytest.raises(RegistryLookupError):
            lookup_by_id(conn, "tags", 100)
        count = conn.execute("SELECT COUNT(*) FROM tags").fetchone()[0]
        assert count == 3


# =============================================================================
# TestResolveNameOrId — dispatcher: detect int vs string
# =============================================================================
class TestResolveNameOrId:
    """Tests for resolve_name_or_id function."""

    def test_resolve_integer_string_as_id(self, conn):
        """Passing "1" resolves via ID lookup (finds "project")."""
        # 1. resolve_name_or_id(conn, "tags", "1", normalize_tag_name)
        # 2. Assert result["name"] == "project"
        result = resolve_name_or_id(conn, "tags", "1", normalize_tag_name)
        assert result["name"] == "project"

    def test_resolve_name_string(self, conn):
        """Passing "urgent" resolves via name lookup."""
        # 1. resolve_name_or_id(conn, "tags", "urgent", normalize_tag_name)
        # 2. Assert result["name"] == "urgent"
        result = resolve_name_or_id(conn, "tags", "urgent", normalize_tag_name)
        assert result["name"] == "urgent"

    def test_resolve_mixed_string_as_name(self, conn):
        """Passing "42abc" is NOT an int, resolved as name."""
        # 1. resolve_name_or_id(conn, "tags", "42abc", normalize_tag_name, autocreate=False)
        # 2. Expect RegistryLookupError (no tag named "42abc")
        with pytest.raises(RegistryLookupError):
            resolve_name_or_id(conn, "tags", "42abc", normalize_tag_name, autocreate=False)

    def test_resolve_negative_id_string(self, conn):
        """Passing "-1" is parsed as int, looked up by ID (not found)."""
        # 1. resolve_name_or_id(conn, "tags", "-1", normalize_tag_name)
        # 2. Expect RegistryLookupError
        with pytest.raises(RegistryLookupError):
            resolve_name_or_id(conn, "tags", "-1", normalize_tag_name)

    def test_resolve_name_with_autocreate(self, conn):
        """Passing a new name with autocreate=True creates the entry."""
        # 1. resolve_name_or_id(conn, "tags", "brandnew", normalize_tag_name, autocreate=True)
        # 2. Assert result["name"] == "brandnew"
        # 3. Verify entry exists in table
        result = resolve_name_or_id(conn, "tags", "brandnew", normalize_tag_name, autocreate=True)
        assert result["name"] == "brandnew"
        row = conn.execute("SELECT id FROM tags WHERE name = 'brandnew'").fetchone()
        assert row is not None

    def test_resolve_id_ignores_autocreate(self, conn):
        """ID lookup never auto-creates, even if autocreate=True."""
        # 1. resolve_name_or_id(conn, "tags", "9999", normalize_tag_name, autocreate=True)
        # 2. Expect RegistryLookupError (ID 9999 doesn't exist, not auto-created)
        with pytest.raises(RegistryLookupError):
            resolve_name_or_id(conn, "tags", "9999", normalize_tag_name, autocreate=True)
