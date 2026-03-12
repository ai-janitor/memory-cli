# =============================================================================
# Module: test_neuron_get.py
# Purpose: Test single neuron lookup by ID — found, not found, archived
#   retrievable, and tag/attribute hydration.
# Rationale: neuron_get is the most used read path and the hydration logic
#   (joining tags and attrs) must be tested thoroughly since many other
#   modules depend on it for consistent output format.
# Responsibility:
#   - Test successful lookup returns fully hydrated record
#   - Test not-found returns None
#   - Test archived neurons are still retrievable
#   - Test tag hydration joins correctly and sorts alphabetically
#   - Test attribute hydration joins correctly
#   - Test neuron with no tags returns empty list
#   - Test neuron with no attrs returns empty dict
# Organization:
#   1. Imports and fixtures
#   2. Found/not-found tests
#   3. Tag hydration tests
#   4. Attribute hydration tests
#   5. Archived neuron tests
# =============================================================================

from __future__ import annotations

import time
import pytest

sqlite_vec = pytest.importorskip(
    "sqlite_vec",
    reason="sqlite_vec required for full schema (vec0 table)"
)


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------

@pytest.fixture
def migrated_conn():
    """In-memory SQLite with full migrated schema including neurons_vec."""
    from memory_cli.db.connection_setup_wal_fk_busy import open_connection
    from memory_cli.db.extension_loader_sqlite_vec import load_and_verify_extensions
    from memory_cli.db.migrations.v001_baseline_all_tables_indexes_triggers import apply

    conn = open_connection(":memory:")
    load_and_verify_extensions(conn)
    conn.execute("BEGIN")
    apply(conn)
    conn.execute("COMMIT")
    yield conn
    conn.close()


def _insert_neuron(conn, content="test content", project="test-project",
                   source=None, status="active", tags=None, attrs=None):
    """Helper: insert a neuron directly with SQL for test setup. Returns neuron_id."""
    from memory_cli.registries import tag_autocreate, attr_autocreate

    now_ms = int(time.time() * 1000)
    cursor = conn.execute(
        """INSERT INTO neurons (content, created_at, updated_at, project, source, status)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (content, now_ms, now_ms, project, source, status)
    )
    neuron_id = cursor.lastrowid

    for tag_name in (tags or []):
        tag_id = tag_autocreate(conn, tag_name)
        conn.execute(
            "INSERT OR IGNORE INTO neuron_tags (neuron_id, tag_id) VALUES (?, ?)",
            (neuron_id, tag_id)
        )

    for key, value in (attrs or {}).items():
        attr_key_id = attr_autocreate(conn, key)
        conn.execute(
            "INSERT INTO neuron_attrs (neuron_id, attr_key_id, value) VALUES (?, ?, ?)",
            (neuron_id, attr_key_id, value)
        )

    conn.commit()
    return neuron_id


# -----------------------------------------------------------------------------
# Found / not-found tests
# -----------------------------------------------------------------------------

class TestNeuronGetLookup:
    """Test basic lookup behavior."""

    def test_get_existing_neuron(self, migrated_conn):
        """Verify lookup of existing neuron returns complete record.

        Expected keys in returned dict:
        id, content, created_at, updated_at, project, source, status,
        embedding_updated_at, tags, attrs
        """
        from memory_cli.neuron.neuron_get_by_id import neuron_get

        neuron_id = _insert_neuron(migrated_conn, content="hello")
        result = neuron_get(migrated_conn, neuron_id)
        assert result is not None
        expected_keys = {"id", "content", "created_at", "updated_at", "project",
                         "source", "status", "embedding_updated_at", "tags", "attrs"}
        assert expected_keys.issubset(set(result.keys()))

    def test_get_nonexistent_id_returns_none(self, migrated_conn):
        """Verify lookup of non-existent ID returns None.

        Caller (CLI layer) should interpret None as exit 1.
        """
        from memory_cli.neuron.neuron_get_by_id import neuron_get

        result = neuron_get(migrated_conn, 99999)
        assert result is None

    def test_get_returns_correct_content(self, migrated_conn):
        """Verify returned content matches what was stored."""
        from memory_cli.neuron.neuron_get_by_id import neuron_get

        neuron_id = _insert_neuron(migrated_conn, content="exact content")
        result = neuron_get(migrated_conn, neuron_id)
        assert result["content"] == "exact content"

    def test_get_returns_correct_timestamps(self, migrated_conn):
        """Verify created_at and updated_at are correct integer ms values."""
        from memory_cli.neuron.neuron_get_by_id import neuron_get

        neuron_id = _insert_neuron(migrated_conn)
        result = neuron_get(migrated_conn, neuron_id)
        assert isinstance(result["created_at"], int)
        assert isinstance(result["updated_at"], int)
        assert result["created_at"] > 0
        assert result["created_at"] == result["updated_at"]

    def test_get_returns_correct_project(self, migrated_conn):
        """Verify project field matches what was stored."""
        from memory_cli.neuron.neuron_get_by_id import neuron_get

        neuron_id = _insert_neuron(migrated_conn, project="my-project")
        result = neuron_get(migrated_conn, neuron_id)
        assert result["project"] == "my-project"

    def test_get_returns_correct_source(self, migrated_conn):
        """Verify source field matches what was stored (including None)."""
        from memory_cli.neuron.neuron_get_by_id import neuron_get

        neuron_id_with = _insert_neuron(migrated_conn, source="chat:42")
        neuron_id_without = _insert_neuron(migrated_conn, source=None)

        result_with = neuron_get(migrated_conn, neuron_id_with)
        result_without = neuron_get(migrated_conn, neuron_id_without)

        assert result_with["source"] == "chat:42"
        assert result_without["source"] is None


# -----------------------------------------------------------------------------
# Tag hydration tests
# -----------------------------------------------------------------------------

class TestNeuronGetTagHydration:
    """Test that tags are correctly hydrated from junction table."""

    def test_tags_hydrated_as_list(self, migrated_conn):
        """Verify tags field is a list of tag name strings."""
        from memory_cli.neuron.neuron_get_by_id import neuron_get

        neuron_id = _insert_neuron(migrated_conn, tags=["python"])
        result = neuron_get(migrated_conn, neuron_id)
        assert isinstance(result["tags"], list)
        assert all(isinstance(t, str) for t in result["tags"])

    def test_tags_sorted_alphabetically(self, migrated_conn):
        """Verify tags are sorted by name for deterministic output."""
        from memory_cli.neuron.neuron_get_by_id import neuron_get

        neuron_id = _insert_neuron(migrated_conn, tags=["zebra", "apple", "mango"])
        result = neuron_get(migrated_conn, neuron_id)
        assert result["tags"] == sorted(result["tags"])

    def test_neuron_with_no_tags_returns_empty_list(self, migrated_conn):
        """Verify neuron with no tag associations returns tags=[]."""
        from memory_cli.neuron.neuron_get_by_id import neuron_get

        neuron_id = _insert_neuron(migrated_conn, tags=[])
        result = neuron_get(migrated_conn, neuron_id)
        assert result["tags"] == []

    def test_multiple_tags_all_present(self, migrated_conn):
        """Verify all associated tags appear in the list."""
        from memory_cli.neuron.neuron_get_by_id import neuron_get

        tags = ["python", "ai", "ml"]
        neuron_id = _insert_neuron(migrated_conn, tags=tags)
        result = neuron_get(migrated_conn, neuron_id)
        assert set(result["tags"]) == set(tags)


# -----------------------------------------------------------------------------
# Attribute hydration tests
# -----------------------------------------------------------------------------

class TestNeuronGetAttrHydration:
    """Test that attributes are correctly hydrated from junction table."""

    def test_attrs_hydrated_as_dict(self, migrated_conn):
        """Verify attrs field is a dict of key_name -> value."""
        from memory_cli.neuron.neuron_get_by_id import neuron_get

        neuron_id = _insert_neuron(migrated_conn, attrs={"priority": "high"})
        result = neuron_get(migrated_conn, neuron_id)
        assert isinstance(result["attrs"], dict)

    def test_neuron_with_no_attrs_returns_empty_dict(self, migrated_conn):
        """Verify neuron with no attribute pairs returns attrs={}."""
        from memory_cli.neuron.neuron_get_by_id import neuron_get

        neuron_id = _insert_neuron(migrated_conn, attrs={})
        result = neuron_get(migrated_conn, neuron_id)
        assert result["attrs"] == {}

    def test_multiple_attrs_all_present(self, migrated_conn):
        """Verify all associated attributes appear in the dict."""
        from memory_cli.neuron.neuron_get_by_id import neuron_get

        attrs = {"priority": "high", "author": "alice", "version": "2"}
        neuron_id = _insert_neuron(migrated_conn, attrs=attrs)
        result = neuron_get(migrated_conn, neuron_id)
        assert result["attrs"] == attrs


# -----------------------------------------------------------------------------
# Archived neuron tests
# -----------------------------------------------------------------------------

class TestNeuronGetArchived:
    """Test that archived neurons are still retrievable."""

    def test_archived_neuron_retrievable(self, migrated_conn):
        """Verify archived neuron can be fetched by ID.

        Archive a neuron, then fetch it. Should return the full record
        with status='archived'.
        """
        from memory_cli.neuron.neuron_get_by_id import neuron_get

        neuron_id = _insert_neuron(migrated_conn, status="archived")
        result = neuron_get(migrated_conn, neuron_id)
        assert result is not None

    def test_archived_neuron_has_correct_status(self, migrated_conn):
        """Verify returned status field is 'archived' for archived neurons."""
        from memory_cli.neuron.neuron_get_by_id import neuron_get

        neuron_id = _insert_neuron(migrated_conn, status="archived")
        result = neuron_get(migrated_conn, neuron_id)
        assert result["status"] == "archived"
