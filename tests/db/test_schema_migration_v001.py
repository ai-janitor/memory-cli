# =============================================================================
# test_schema_migration_v001.py — Tests for the v0->v1 baseline migration
# =============================================================================
# Purpose:     Verify that the v001 migration creates the complete schema
#              correctly: all 9 tables, all indexes, all triggers, the vec0
#              table, and meta entries. Also test rollback behavior, version
#              tracking, and idempotency concerns.
# Rationale:   The baseline migration is the most critical — it defines the
#              entire data model. Every table, column, constraint, index, and
#              trigger must be verified. Rollback must leave the DB clean.
# Responsibility:
#   - Test that all 9 tables are created with correct columns
#   - Test that all indexes exist
#   - Test that all 5 FTS triggers exist and work
#   - Test that neurons_vec (vec0) is created and usable
#   - Test that meta table is seeded correctly
#   - Test constraint enforcement (CHECK, FK, NOT NULL, UNIQUE)
#   - Test rollback on simulated failure mid-migration
#   - Test schema version is set to 1 after migration
# Organization:
#   Test classes grouped by verification area.
#   Helper fixture creates a migrated in-memory DB for most tests.
#   Separate tests for rollback use a deliberately broken migration.
# =============================================================================

from __future__ import annotations

import pytest
import sqlite3
import struct
import time
from unittest import mock
from memory_cli.db.connection_setup_wal_fk_busy import open_connection
from memory_cli.db.extension_loader_sqlite_vec import load_and_verify_extensions
from memory_cli.db.migrations.v001_baseline_all_tables_indexes_triggers import apply
from memory_cli.db.schema_version_reader import read_schema_version
from memory_cli.db.migration_runner_single_transaction import run_pending_migrations

# --- Module-level guard: all tests in this file require sqlite_vec ---
# The migration creates a vec0 virtual table, so sqlite_vec must be present.
# Tests will be skipped (not failed) when sqlite_vec is unavailable.
sqlite_vec = pytest.importorskip(
    "sqlite_vec",
    reason="sqlite_vec package required for migration tests (vec0 virtual table)",
)


# --- Fixtures ---

@pytest.fixture
def migrated_conn():
    """Create an in-memory DB with extensions loaded and v001 applied.

    # --- Setup ---
    # conn = open_connection(':memory:')
    # load_and_verify_extensions(conn)
    # conn.execute('BEGIN')
    # apply(conn)
    # conn.execute('COMMIT')
    # yield conn
    # conn.close()
    """
    # --- Setup ---
    conn = open_connection(":memory:")
    load_and_verify_extensions(conn)
    conn.execute("BEGIN")
    apply(conn)
    conn.execute("COMMIT")
    yield conn
    conn.close()


@pytest.fixture
def empty_conn():
    """Create an in-memory DB with extensions loaded but NO migration.

    # --- Setup ---
    # conn = open_connection(':memory:')
    # load_and_verify_extensions(conn)
    # yield conn
    # conn.close()
    """
    # --- Setup ---
    conn = open_connection(":memory:")
    load_and_verify_extensions(conn)
    yield conn
    conn.close()


# --- Helper: insert a neuron row ---
def _insert_neuron(conn, content="test content", project="test", status="active"):
    """Insert a minimal neuron and return its rowid."""
    now_ms = int(time.time() * 1000)
    conn.execute(
        "INSERT INTO neurons(content, created_at, updated_at, project, status) VALUES (?, ?, ?, ?, ?)",
        (content, now_ms, now_ms, project, status),
    )
    row = conn.execute("SELECT last_insert_rowid()").fetchone()
    return row[0]


class TestTablesExist:
    """Verify all 9 tables are created by the migration."""

    def test_all_tables_present(self, migrated_conn) -> None:
        """All 9 expected tables should exist after migration.

        # --- Arrange ---
        # Use migrated_conn fixture

        # --- Act ---
        # Query sqlite_master for all table names (type='table' or type='virtual table')

        # --- Assert ---
        # Expected tables: neurons, edges, tags, neuron_tags, attr_keys,
        #   neuron_attrs, neurons_fts, neurons_vec, meta
        # All 9 should be present
        """
        # --- Act ---
        rows = migrated_conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'shadow') OR name IN "
            "('neurons', 'edges', 'tags', 'neuron_tags', 'attr_keys', 'neuron_attrs', "
            "'neurons_fts', 'neurons_vec', 'meta')"
        ).fetchall()
        table_names = {r[0] for r in rows}

        # Also check via a broader query that includes virtual tables
        all_rows = migrated_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        all_names = {r[0] for r in all_rows}

        # --- Assert ---
        expected_tables = {
            "neurons", "edges", "tags", "neuron_tags", "attr_keys",
            "neuron_attrs", "neurons_fts", "neurons_vec", "meta",
        }
        for table in expected_tables:
            assert table in all_names, f"Expected table '{table}' not found. Got: {all_names}"

    def test_neurons_table_columns(self, migrated_conn) -> None:
        """neurons table should have all 8 columns with correct types.

        # --- Arrange ---
        # Use migrated_conn fixture

        # --- Act ---
        # PRAGMA table_info(neurons)

        # --- Assert ---
        # Columns: id, content, created_at, updated_at, project, source,
        #   embedding_updated_at, status
        # Verify types: INTEGER, TEXT, INTEGER, INTEGER, TEXT, TEXT, INTEGER, TEXT
        """
        # --- Act ---
        rows = migrated_conn.execute("PRAGMA table_info(neurons)").fetchall()
        columns = {r[1]: r[2] for r in rows}  # name -> type

        # --- Assert ---
        expected = {
            "id": "INTEGER",
            "content": "TEXT",
            "created_at": "INTEGER",
            "updated_at": "INTEGER",
            "project": "TEXT",
            "source": "TEXT",
            "embedding_updated_at": "INTEGER",
            "status": "TEXT",
        }
        assert len(rows) == 8, f"Expected 8 columns, got {len(rows)}: {list(columns.keys())}"
        for col_name, col_type in expected.items():
            assert col_name in columns, f"Column '{col_name}' missing from neurons"
            assert columns[col_name] == col_type, (
                f"Column '{col_name}' has type '{columns[col_name]}', expected '{col_type}'"
            )

    def test_edges_table_columns(self, migrated_conn) -> None:
        """edges table should have all 6 columns with correct types.

        # --- Assert columns: id, source_id, target_id, reason, weight, created_at
        """
        # --- Act ---
        rows = migrated_conn.execute("PRAGMA table_info(edges)").fetchall()
        columns = {r[1]: r[2] for r in rows}

        # --- Assert ---
        expected_cols = {"id", "source_id", "target_id", "reason", "weight", "created_at"}
        assert len(rows) == 6, f"Expected 6 columns, got {len(rows)}: {list(columns.keys())}"
        for col in expected_cols:
            assert col in columns, f"Column '{col}' missing from edges"

    def test_tags_table_columns(self, migrated_conn) -> None:
        """tags table should have id, name, created_at columns.

        # --- Assert name is UNIQUE and NOT NULL
        """
        # --- Act ---
        rows = migrated_conn.execute("PRAGMA table_info(tags)").fetchall()
        columns = {r[1]: r[2] for r in rows}

        # --- Assert ---
        expected_cols = {"id", "name", "created_at"}
        assert len(rows) == 3, f"Expected 3 columns, got {len(rows)}: {list(columns.keys())}"
        for col in expected_cols:
            assert col in columns, f"Column '{col}' missing from tags"

        # --- Assert NOT NULL on name ---
        name_row = next(r for r in rows if r[1] == "name")
        assert name_row[3] == 1, "tags.name should be NOT NULL"  # notnull flag

    def test_neuron_tags_composite_pk(self, migrated_conn) -> None:
        """neuron_tags should have composite PK (neuron_id, tag_id).

        # --- Assert PK covers both columns
        """
        # --- Act ---
        rows = migrated_conn.execute("PRAGMA table_info(neuron_tags)").fetchall()
        pk_cols = {r[1] for r in rows if r[5] > 0}  # pk flag > 0 means part of PK

        # --- Assert ---
        assert "neuron_id" in pk_cols, "neuron_id should be part of PK"
        assert "tag_id" in pk_cols, "tag_id should be part of PK"

    def test_neuron_attrs_composite_pk(self, migrated_conn) -> None:
        """neuron_attrs should have composite PK (neuron_id, attr_key_id).

        # --- Assert PK covers both columns
        # --- Assert attr_key_id FK uses ON DELETE RESTRICT
        """
        # --- Act ---
        rows = migrated_conn.execute("PRAGMA table_info(neuron_attrs)").fetchall()
        pk_cols = {r[1] for r in rows if r[5] > 0}

        # --- Assert PK ---
        assert "neuron_id" in pk_cols, "neuron_id should be part of PK"
        assert "attr_key_id" in pk_cols, "attr_key_id should be part of PK"

        # --- Assert FK info for attr_key_id ---
        fk_rows = migrated_conn.execute("PRAGMA foreign_key_list(neuron_attrs)").fetchall()
        # Find FK for attr_key_id
        attr_key_fk = next(
            (r for r in fk_rows if r[3] == "attr_key_id"),  # 'from' column
            None,
        )
        assert attr_key_fk is not None, "neuron_attrs.attr_key_id should have a FK"
        # on_delete is index 6 in PRAGMA foreign_key_list result
        assert attr_key_fk[6].upper() == "RESTRICT", (
            f"attr_key_id FK should be ON DELETE RESTRICT, got '{attr_key_fk[6]}'"
        )

    def test_meta_table_structure(self, migrated_conn) -> None:
        """meta table should have key (PK) and value columns.

        # --- Assert key is TEXT PRIMARY KEY
        # --- Assert value is TEXT NOT NULL
        """
        # --- Act ---
        rows = migrated_conn.execute("PRAGMA table_info(meta)").fetchall()
        columns = {r[1]: r for r in rows}  # name -> full row

        # --- Assert ---
        assert "key" in columns, "meta table missing 'key' column"
        assert "value" in columns, "meta table missing 'value' column"

        # key is PK (pk flag = 1)
        key_row = columns["key"]
        assert key_row[5] == 1, "meta.key should be PRIMARY KEY"

        # value is NOT NULL (notnull flag = 1)
        value_row = columns["value"]
        assert value_row[3] == 1, "meta.value should be NOT NULL"


class TestIndexesExist:
    """Verify all indexes are created by the migration."""

    def test_all_indexes_present(self, migrated_conn) -> None:
        """All expected indexes should exist after migration.

        # --- Arrange ---
        # Use migrated_conn fixture

        # --- Act ---
        # Query sqlite_master WHERE type='index' for expected index names

        # --- Assert ---
        # Expected indexes:
        #   idx_neurons_project
        #   idx_neurons_created_at
        #   idx_neurons_status
        #   idx_neurons_embedding_updated_at
        #   idx_edges_source_id
        #   idx_edges_target_id
        #   idx_neuron_tags_tag_id
        #   idx_neuron_attrs_attr_key_id
        """
        # --- Act ---
        rows = migrated_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        ).fetchall()
        index_names = {r[0] for r in rows}

        # --- Assert ---
        expected_indexes = {
            "idx_neurons_project",
            "idx_neurons_created_at",
            "idx_neurons_status",
            "idx_neurons_embedding_updated_at",
            "idx_edges_source_id",
            "idx_edges_target_id",
            "idx_neuron_tags_tag_id",
            "idx_neuron_attrs_attr_key_id",
        }
        for idx in expected_indexes:
            assert idx in index_names, f"Expected index '{idx}' not found. Got: {index_names}"


class TestTriggersExist:
    """Verify all FTS triggers are created and functional."""

    def test_all_triggers_present(self, migrated_conn) -> None:
        """All 5 FTS maintenance triggers should exist.

        # --- Assert triggers:
        #   trg_neurons_fts_insert
        #   trg_neurons_fts_update
        #   trg_neurons_fts_delete
        #   trg_neuron_tags_fts_insert
        #   trg_neuron_tags_fts_delete
        """
        # --- Act ---
        rows = migrated_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger'"
        ).fetchall()
        trigger_names = {r[0] for r in rows}

        # --- Assert ---
        expected_triggers = {
            "trg_neurons_fts_insert",
            "trg_neurons_fts_update",
            "trg_neurons_fts_delete",
            "trg_neuron_tags_fts_insert",
            "trg_neuron_tags_fts_delete",
        }
        for trg in expected_triggers:
            assert trg in trigger_names, f"Expected trigger '{trg}' not found. Got: {trigger_names}"

    def test_neuron_insert_populates_fts(self, migrated_conn) -> None:
        """Inserting a neuron should create a corresponding FTS row.

        # --- Arrange ---
        # Use migrated_conn fixture

        # --- Act ---
        # INSERT a neuron with content 'quantum computing basics'

        # --- Assert ---
        # FTS search for 'quantum' should return the neuron
        """
        # --- Act ---
        neuron_id = _insert_neuron(migrated_conn, content="quantum computing basics")

        # --- Assert ---
        results = migrated_conn.execute(
            "SELECT rowid FROM neurons_fts WHERE neurons_fts MATCH 'quantum'"
        ).fetchall()
        rowids = {r[0] for r in results}
        assert neuron_id in rowids, f"Neuron {neuron_id} not found in FTS after insert"

    def test_neuron_update_updates_fts(self, migrated_conn) -> None:
        """Updating a neuron's content should update the FTS index.

        # --- Arrange ---
        # Insert a neuron with content 'old content'

        # --- Act ---
        # UPDATE the neuron's content to 'new content about physics'

        # --- Assert ---
        # FTS search for 'old' should return nothing
        # FTS search for 'physics' should return the neuron
        """
        # --- Arrange ---
        neuron_id = _insert_neuron(migrated_conn, content="old content")

        # Verify it's in FTS before update
        pre = migrated_conn.execute(
            "SELECT rowid FROM neurons_fts WHERE neurons_fts MATCH 'old'"
        ).fetchall()
        assert any(r[0] == neuron_id for r in pre), "Pre-condition failed: neuron not in FTS"

        # --- Act ---
        now_ms = int(time.time() * 1000)
        migrated_conn.execute(
            "UPDATE neurons SET content = ?, updated_at = ? WHERE id = ?",
            ("new content about physics", now_ms, neuron_id),
        )

        # --- Assert: old content gone ---
        old_results = migrated_conn.execute(
            "SELECT rowid FROM neurons_fts WHERE neurons_fts MATCH 'old'"
        ).fetchall()
        assert not any(r[0] == neuron_id for r in old_results), (
            "Old content should not appear in FTS after update"
        )

        # --- Assert: new content present ---
        new_results = migrated_conn.execute(
            "SELECT rowid FROM neurons_fts WHERE neurons_fts MATCH 'physics'"
        ).fetchall()
        assert any(r[0] == neuron_id for r in new_results), (
            "New content 'physics' should appear in FTS after update"
        )

    def test_neuron_delete_removes_fts(self, migrated_conn) -> None:
        """Deleting a neuron should remove it from the FTS index.

        # --- Arrange ---
        # Insert a neuron, verify it appears in FTS search

        # --- Act ---
        # DELETE the neuron

        # --- Assert ---
        # FTS search should return nothing
        """
        # --- Arrange ---
        neuron_id = _insert_neuron(migrated_conn, content="unique astrophysics content")

        # Verify it's in FTS
        pre = migrated_conn.execute(
            "SELECT rowid FROM neurons_fts WHERE neurons_fts MATCH 'astrophysics'"
        ).fetchall()
        assert any(r[0] == neuron_id for r in pre), "Pre-condition failed: neuron not in FTS"

        # --- Act ---
        migrated_conn.execute("DELETE FROM neurons WHERE id = ?", (neuron_id,))

        # --- Assert ---
        post = migrated_conn.execute(
            "SELECT rowid FROM neurons_fts WHERE neurons_fts MATCH 'astrophysics'"
        ).fetchall()
        assert not any(r[0] == neuron_id for r in post), (
            "Neuron should be removed from FTS after delete"
        )

    def test_tag_insert_updates_fts_tags_blob(self, migrated_conn) -> None:
        """Adding a tag to a neuron should update the FTS tags_blob.

        # --- Arrange ---
        # Insert a neuron and a tag

        # --- Act ---
        # INSERT into neuron_tags to link them

        # --- Assert ---
        # FTS search for the tag name should match the neuron
        """
        # --- Arrange ---
        neuron_id = _insert_neuron(migrated_conn, content="some neuron content")
        now_ms = int(time.time() * 1000)
        migrated_conn.execute(
            "INSERT INTO tags(name, created_at) VALUES('mytag', ?)", (now_ms,)
        )
        tag_row = migrated_conn.execute("SELECT last_insert_rowid()").fetchone()
        tag_id = tag_row[0]

        # --- Act ---
        migrated_conn.execute(
            "INSERT INTO neuron_tags(neuron_id, tag_id) VALUES(?, ?)",
            (neuron_id, tag_id),
        )

        # --- Assert ---
        results = migrated_conn.execute(
            "SELECT rowid FROM neurons_fts WHERE neurons_fts MATCH 'mytag'"
        ).fetchall()
        rowids = {r[0] for r in results}
        assert neuron_id in rowids, (
            f"Neuron {neuron_id} should match FTS for tag 'mytag' after linking"
        )

    def test_tag_delete_updates_fts_tags_blob(self, migrated_conn) -> None:
        """Removing a tag from a neuron should update the FTS tags_blob.

        # --- Arrange ---
        # Insert a neuron with a tag linked via neuron_tags

        # --- Act ---
        # DELETE from neuron_tags

        # --- Assert ---
        # FTS search for the tag name should no longer match the neuron
        """
        # --- Arrange ---
        neuron_id = _insert_neuron(migrated_conn, content="neuron with removable tag")
        now_ms = int(time.time() * 1000)
        migrated_conn.execute(
            "INSERT INTO tags(name, created_at) VALUES('removabletag', ?)", (now_ms,)
        )
        tag_row = migrated_conn.execute("SELECT last_insert_rowid()").fetchone()
        tag_id = tag_row[0]
        migrated_conn.execute(
            "INSERT INTO neuron_tags(neuron_id, tag_id) VALUES(?, ?)",
            (neuron_id, tag_id),
        )

        # Verify tag is in FTS before removal
        pre = migrated_conn.execute(
            "SELECT rowid FROM neurons_fts WHERE neurons_fts MATCH 'removabletag'"
        ).fetchall()
        assert any(r[0] == neuron_id for r in pre), "Pre-condition: tag should be in FTS"

        # --- Act ---
        migrated_conn.execute(
            "DELETE FROM neuron_tags WHERE neuron_id = ? AND tag_id = ?",
            (neuron_id, tag_id),
        )

        # --- Assert ---
        post = migrated_conn.execute(
            "SELECT rowid FROM neurons_fts WHERE neurons_fts MATCH 'removabletag'"
        ).fetchall()
        assert not any(r[0] == neuron_id for r in post), (
            "Neuron should NOT match FTS for tag 'removabletag' after unlinking"
        )


class TestVec0Table:
    """Verify the neurons_vec vec0 virtual table."""

    def test_neurons_vec_created(self, migrated_conn) -> None:
        """neurons_vec should exist as a virtual table after migration.

        # --- Assert table exists in sqlite_master
        """
        # --- Act ---
        row = migrated_conn.execute(
            "SELECT name FROM sqlite_master WHERE name='neurons_vec'"
        ).fetchone()

        # --- Assert ---
        assert row is not None, "neurons_vec should exist in sqlite_master"

    def test_neurons_vec_insert_and_query(self, migrated_conn) -> None:
        """Should be able to insert and query vectors in neurons_vec.

        # --- Arrange ---
        # Use migrated_conn fixture

        # --- Act ---
        # INSERT a vector with neuron_id=1 and a 768-dim float array
        # Query for nearest neighbors

        # --- Assert ---
        # The inserted vector should be retrievable
        """
        # --- Arrange ---
        vec_data = [0.1] * 768
        vec_bytes = struct.pack(f"{768}f", *vec_data)

        # --- Act ---
        migrated_conn.execute(
            "INSERT INTO neurons_vec(neuron_id, embedding) VALUES(?, ?)",
            (1, vec_bytes),
        )
        result = migrated_conn.execute(
            "SELECT neuron_id, distance FROM neurons_vec WHERE embedding MATCH ? AND k = 1",
            (vec_bytes,),
        ).fetchone()

        # --- Assert ---
        assert result is not None, "Query should return at least one result"
        assert result[0] == 1, f"Expected neuron_id=1, got {result[0]}"

    def test_neurons_vec_no_fk_enforcement(self, migrated_conn) -> None:
        """vec0 does not enforce FKs — inserting with non-existent neuron_id
        should succeed (this is expected behavior, not a bug).

        # --- Assert ---
        # INSERT into neurons_vec with neuron_id=9999 should NOT raise
        # Callers must handle cleanup manually
        """
        # --- Arrange ---
        vec_data = [0.5] * 768
        vec_bytes = struct.pack(f"{768}f", *vec_data)

        # --- Act / Assert: should NOT raise even though neuron 9999 doesn't exist ---
        migrated_conn.execute(
            "INSERT INTO neurons_vec(neuron_id, embedding) VALUES(?, ?)",
            (9999, vec_bytes),
        )
        # Verify the row is there
        result = migrated_conn.execute(
            "SELECT neuron_id FROM neurons_vec WHERE embedding MATCH ? AND k = 1",
            (vec_bytes,),
        ).fetchone()
        assert result is not None
        assert result[0] == 9999


class TestMetaTableSeeding:
    """Verify meta table is seeded with correct initial values."""

    def test_schema_version_set(self, migrated_conn) -> None:
        """meta.schema_version should be '1' after v001 migration.

        # --- Assert ---
        # SELECT value FROM meta WHERE key = 'schema_version' => '1'
        """
        # --- Act ---
        row = migrated_conn.execute(
            "SELECT value FROM meta WHERE key = 'schema_version'"
        ).fetchone()

        # --- Assert ---
        assert row is not None, "meta.schema_version key should exist"
        assert row[0] == "1", f"Expected schema_version='1', got '{row[0]}'"

    def test_embedding_model_set(self, migrated_conn) -> None:
        """meta.embedding_model should be 'default' initially.

        # --- Assert ---
        # SELECT value FROM meta WHERE key = 'embedding_model' => 'default'
        """
        # --- Act ---
        row = migrated_conn.execute(
            "SELECT value FROM meta WHERE key = 'embedding_model'"
        ).fetchone()

        # --- Assert ---
        assert row is not None, "meta.embedding_model key should exist"
        assert row[0] == "default", f"Expected embedding_model='default', got '{row[0]}'"

    def test_embedding_dimensions_set(self, migrated_conn) -> None:
        """meta.embedding_dimensions should be '768' initially.

        # --- Assert ---
        # SELECT value FROM meta WHERE key = 'embedding_dimensions' => '768'
        """
        # --- Act ---
        row = migrated_conn.execute(
            "SELECT value FROM meta WHERE key = 'embedding_dimensions'"
        ).fetchone()

        # --- Assert ---
        assert row is not None, "meta.embedding_dimensions key should exist"
        assert row[0] == "768", f"Expected embedding_dimensions='768', got '{row[0]}'"

    def test_timestamps_set(self, migrated_conn) -> None:
        """created_at and last_migrated_at should be set to reasonable values.

        # --- Assert ---
        # Both values should be integers (ms since epoch)
        # Both should be within a few seconds of current time
        """
        # --- Act ---
        created_row = migrated_conn.execute(
            "SELECT value FROM meta WHERE key = 'created_at'"
        ).fetchone()
        migrated_row = migrated_conn.execute(
            "SELECT value FROM meta WHERE key = 'last_migrated_at'"
        ).fetchone()

        # --- Assert: both keys exist ---
        assert created_row is not None, "meta.created_at should exist"
        assert migrated_row is not None, "meta.last_migrated_at should exist"

        # --- Assert: parseable as integers ---
        created_ms = int(created_row[0])
        migrated_ms = int(migrated_row[0])

        # --- Assert: reasonable range (within 60 seconds of now) ---
        now_ms = int(time.time() * 1000)
        tolerance_ms = 60_000  # 60 seconds

        assert abs(now_ms - created_ms) < tolerance_ms, (
            f"meta.created_at ({created_ms}) is not within 60s of current time ({now_ms})"
        )
        assert abs(now_ms - migrated_ms) < tolerance_ms, (
            f"meta.last_migrated_at ({migrated_ms}) is not within 60s of current time ({now_ms})"
        )


class TestConstraints:
    """Verify CHECK, NOT NULL, UNIQUE, and FK constraints."""

    def test_neuron_content_not_empty(self, migrated_conn) -> None:
        """neurons.content CHECK(length > 0) should reject empty strings.

        # --- Act / Assert ---
        # INSERT neuron with content='' should raise IntegrityError
        """
        # --- Act / Assert ---
        now_ms = int(time.time() * 1000)
        with pytest.raises(sqlite3.IntegrityError):
            migrated_conn.execute(
                "INSERT INTO neurons(content, created_at, updated_at, project) VALUES('', ?, ?, 'test')",
                (now_ms, now_ms),
            )

    def test_neuron_project_not_empty(self, migrated_conn) -> None:
        """neurons.project CHECK(length > 0) should reject empty strings.

        # --- Act / Assert ---
        # INSERT neuron with project='' should raise IntegrityError
        """
        # --- Act / Assert ---
        now_ms = int(time.time() * 1000)
        with pytest.raises(sqlite3.IntegrityError):
            migrated_conn.execute(
                "INSERT INTO neurons(content, created_at, updated_at, project) VALUES('valid content', ?, ?, '')",
                (now_ms, now_ms),
            )

    def test_neuron_status_check(self, migrated_conn) -> None:
        """neurons.status must be 'active' or 'archived'.

        # --- Act / Assert ---
        # INSERT neuron with status='deleted' should raise IntegrityError
        """
        # --- Act / Assert ---
        now_ms = int(time.time() * 1000)
        with pytest.raises(sqlite3.IntegrityError):
            migrated_conn.execute(
                "INSERT INTO neurons(content, created_at, updated_at, project, status) "
                "VALUES('valid content', ?, ?, 'test', 'deleted')",
                (now_ms, now_ms),
            )

    def test_edge_weight_positive(self, migrated_conn) -> None:
        """edges.weight CHECK(> 0) should reject zero and negative values.

        # --- Act / Assert ---
        # INSERT edge with weight=0 should raise IntegrityError
        # INSERT edge with weight=-1 should raise IntegrityError
        """
        # --- Arrange: create two neurons ---
        now_ms = int(time.time() * 1000)
        src_id = _insert_neuron(migrated_conn, content="source neuron")
        tgt_id = _insert_neuron(migrated_conn, content="target neuron")

        # --- Assert: weight=0 rejected ---
        with pytest.raises(sqlite3.IntegrityError):
            migrated_conn.execute(
                "INSERT INTO edges(source_id, target_id, reason, weight, created_at) VALUES(?, ?, 'relates', 0, ?)",
                (src_id, tgt_id, now_ms),
            )

        # --- Assert: weight=-1 rejected ---
        with pytest.raises(sqlite3.IntegrityError):
            migrated_conn.execute(
                "INSERT INTO edges(source_id, target_id, reason, weight, created_at) VALUES(?, ?, 'relates', -1, ?)",
                (src_id, tgt_id, now_ms),
            )

    def test_edge_reason_not_empty(self, migrated_conn) -> None:
        """edges.reason CHECK(length > 0) should reject empty strings.

        # --- Act / Assert ---
        # INSERT edge with reason='' should raise IntegrityError
        """
        # --- Arrange ---
        now_ms = int(time.time() * 1000)
        src_id = _insert_neuron(migrated_conn, content="source neuron for reason test")
        tgt_id = _insert_neuron(migrated_conn, content="target neuron for reason test")

        # --- Act / Assert ---
        with pytest.raises(sqlite3.IntegrityError):
            migrated_conn.execute(
                "INSERT INTO edges(source_id, target_id, reason, weight, created_at) VALUES(?, ?, '', 1.0, ?)",
                (src_id, tgt_id, now_ms),
            )

    def test_tag_name_lowercase_check(self, migrated_conn) -> None:
        """tags.name CHECK(name = lower(name)) should reject uppercase.

        # --- Act / Assert ---
        # INSERT tag with name='Python' should raise IntegrityError
        # INSERT tag with name='python' should succeed
        """
        # --- Arrange ---
        now_ms = int(time.time() * 1000)

        # --- Assert: uppercase rejected ---
        with pytest.raises(sqlite3.IntegrityError):
            migrated_conn.execute(
                "INSERT INTO tags(name, created_at) VALUES('Python', ?)", (now_ms,)
            )

        # --- Assert: lowercase accepted ---
        migrated_conn.execute(
            "INSERT INTO tags(name, created_at) VALUES('python', ?)", (now_ms,)
        )
        row = migrated_conn.execute(
            "SELECT name FROM tags WHERE name='python'"
        ).fetchone()
        assert row is not None

    def test_tag_name_unique(self, migrated_conn) -> None:
        """tags.name UNIQUE should reject duplicate tag names.

        # --- Act / Assert ---
        # INSERT two tags with same name should raise IntegrityError
        """
        # --- Arrange ---
        now_ms = int(time.time() * 1000)
        migrated_conn.execute(
            "INSERT INTO tags(name, created_at) VALUES('uniquetag', ?)", (now_ms,)
        )

        # --- Act / Assert ---
        with pytest.raises(sqlite3.IntegrityError):
            migrated_conn.execute(
                "INSERT INTO tags(name, created_at) VALUES('uniquetag', ?)", (now_ms,)
            )

    def test_edge_cascade_delete(self, migrated_conn) -> None:
        """Deleting a neuron should CASCADE delete its edges.

        # --- Arrange ---
        # Insert two neurons and an edge between them

        # --- Act ---
        # DELETE the source neuron

        # --- Assert ---
        # Edge should be gone
        """
        # --- Arrange ---
        now_ms = int(time.time() * 1000)
        src_id = _insert_neuron(migrated_conn, content="cascade source neuron")
        tgt_id = _insert_neuron(migrated_conn, content="cascade target neuron")
        migrated_conn.execute(
            "INSERT INTO edges(source_id, target_id, reason, weight, created_at) VALUES(?, ?, 'test', 1.0, ?)",
            (src_id, tgt_id, now_ms),
        )
        edge_row = migrated_conn.execute("SELECT last_insert_rowid()").fetchone()
        edge_id = edge_row[0]

        # --- Act ---
        migrated_conn.execute("DELETE FROM neurons WHERE id = ?", (src_id,))

        # --- Assert ---
        result = migrated_conn.execute(
            "SELECT id FROM edges WHERE id = ?", (edge_id,)
        ).fetchone()
        assert result is None, "Edge should be CASCADE deleted when source neuron is deleted"

    def test_attr_key_restrict_delete(self, migrated_conn) -> None:
        """Deleting an attr_key referenced by neuron_attrs should RESTRICT.

        # --- Arrange ---
        # Insert a neuron, an attr_key, and a neuron_attr linking them

        # --- Act / Assert ---
        # DELETE the attr_key should raise IntegrityError
        """
        # --- Arrange ---
        now_ms = int(time.time() * 1000)
        neuron_id = _insert_neuron(migrated_conn, content="neuron with attr")
        migrated_conn.execute(
            "INSERT INTO attr_keys(name, created_at) VALUES('testkey', ?)", (now_ms,)
        )
        key_row = migrated_conn.execute("SELECT last_insert_rowid()").fetchone()
        attr_key_id = key_row[0]
        migrated_conn.execute(
            "INSERT INTO neuron_attrs(neuron_id, attr_key_id, value) VALUES(?, ?, 'testval')",
            (neuron_id, attr_key_id),
        )

        # --- Act / Assert ---
        with pytest.raises(sqlite3.IntegrityError):
            migrated_conn.execute("DELETE FROM attr_keys WHERE id = ?", (attr_key_id,))

    def test_self_referential_edge_allowed(self, migrated_conn) -> None:
        """An edge from a neuron to itself should be allowed.

        # --- Act ---
        # Insert a neuron, then an edge with source_id == target_id

        # --- Assert ---
        # No error raised, edge exists
        """
        # --- Act ---
        now_ms = int(time.time() * 1000)
        neuron_id = _insert_neuron(migrated_conn, content="self-referential neuron")
        migrated_conn.execute(
            "INSERT INTO edges(source_id, target_id, reason, weight, created_at) VALUES(?, ?, 'self-link', 1.0, ?)",
            (neuron_id, neuron_id, now_ms),
        )

        # --- Assert ---
        result = migrated_conn.execute(
            "SELECT id FROM edges WHERE source_id = ? AND target_id = ?",
            (neuron_id, neuron_id),
        ).fetchone()
        assert result is not None, "Self-referential edge should be allowed"

    def test_multiple_edges_between_same_neurons(self, migrated_conn) -> None:
        """Multiple edges between the same neuron pair should be allowed.

        # --- Act ---
        # Insert two edges with same source_id and target_id but different reasons

        # --- Assert ---
        # Both edges exist
        """
        # --- Arrange ---
        now_ms = int(time.time() * 1000)
        src_id = _insert_neuron(migrated_conn, content="multi-edge source")
        tgt_id = _insert_neuron(migrated_conn, content="multi-edge target")

        # --- Act ---
        migrated_conn.execute(
            "INSERT INTO edges(source_id, target_id, reason, weight, created_at) VALUES(?, ?, 'reason one', 1.0, ?)",
            (src_id, tgt_id, now_ms),
        )
        migrated_conn.execute(
            "INSERT INTO edges(source_id, target_id, reason, weight, created_at) VALUES(?, ?, 'reason two', 0.5, ?)",
            (src_id, tgt_id, now_ms),
        )

        # --- Assert ---
        results = migrated_conn.execute(
            "SELECT id FROM edges WHERE source_id = ? AND target_id = ?",
            (src_id, tgt_id),
        ).fetchall()
        assert len(results) == 2, f"Expected 2 edges, got {len(results)}"


class TestSchemaVersionTracking:
    """Verify schema version reader works with migrated DB."""

    def test_version_zero_before_migration(self, empty_conn) -> None:
        """Empty DB should report schema version 0.

        # --- Arrange ---
        # Use empty_conn fixture (no migration applied)

        # --- Act ---
        # version = read_schema_version(conn)

        # --- Assert ---
        # version should be 0
        """
        # --- Act ---
        version = read_schema_version(empty_conn)

        # --- Assert ---
        assert version == 0, f"Expected schema version 0, got {version}"

    def test_version_one_after_migration(self, migrated_conn) -> None:
        """After v001 migration, schema version should be 1.

        # --- Arrange ---
        # Use migrated_conn fixture

        # --- Act ---
        # version = read_schema_version(conn)

        # --- Assert ---
        # version should be 1
        """
        # --- Act ---
        version = read_schema_version(migrated_conn)

        # --- Assert ---
        assert version == 1, f"Expected schema version 1, got {version}"


class TestMigrationRunner:
    """Test the migration runner with v001."""

    def test_run_migration_v0_to_v1(self, empty_conn) -> None:
        """Migration runner should successfully migrate from v0 to v1.

        # --- Arrange ---
        # conn with extensions loaded, no migration yet

        # --- Act ---
        # success = run_pending_migrations(conn, current_version=0, target_version=1)

        # --- Assert ---
        # success should be True
        # All 9 tables should exist
        # Schema version should be 1
        """
        # --- Act ---
        success = run_pending_migrations(empty_conn, current_version=0, target_version=1)

        # --- Assert: runner returned True ---
        assert success is True, "run_pending_migrations should return True on success"

        # --- Assert: all 9 tables exist ---
        rows = empty_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = {r[0] for r in rows}
        expected_tables = {
            "neurons", "edges", "tags", "neuron_tags", "attr_keys",
            "neuron_attrs", "neurons_fts", "neurons_vec", "meta",
        }
        for table in expected_tables:
            assert table in table_names, f"Table '{table}' missing after migration"

        # --- Assert: schema version is 1 ---
        version = read_schema_version(empty_conn)
        assert version == 1, f"Expected schema version 1, got {version}"

    def test_rollback_on_failure(self, empty_conn) -> None:
        """If migration fails mid-way, all changes should be rolled back.

        # --- Arrange ---
        # Create a mock migration that fails after creating some tables
        # OR: corrupt the connection to cause a failure partway through

        # --- Act ---
        # Run migration, expect failure

        # --- Assert ---
        # success should be False
        # No tables from the migration should exist (rolled back)
        # Schema version should still be 0
        """
        import memory_cli.db.migration_runner_single_transaction as runner_module

        # --- Arrange: patch the registry to inject a failing migration ---
        # We patch _get_migration_steps to return a function that raises mid-apply
        def failing_apply(conn):
            # Create one table then blow up — simulates partial migration
            conn.execute("CREATE TABLE partial_migration_table (id INTEGER PRIMARY KEY)")
            raise RuntimeError("Simulated migration failure mid-way")

        with mock.patch.object(
            runner_module,
            "_get_migration_steps",
            return_value=[(1, failing_apply)],
        ):
            # --- Act ---
            success = run_pending_migrations(empty_conn, current_version=0, target_version=1)

        # --- Assert: runner returned False ---
        assert success is False, "run_pending_migrations should return False on failure"

        # --- Assert: partial table was rolled back ---
        row = empty_conn.execute(
            "SELECT name FROM sqlite_master WHERE name='partial_migration_table'"
        ).fetchone()
        assert row is None, (
            "Partial migration table should not exist after rollback"
        )

        # --- Assert: schema version still 0 ---
        version = read_schema_version(empty_conn)
        assert version == 0, f"Schema version should still be 0 after rollback, got {version}"

    def test_no_op_when_versions_match(self, migrated_conn) -> None:
        """Migration runner should be a no-op when current == target.

        # --- Arrange ---
        # Use migrated_conn (already at version 1)

        # --- Act ---
        # success = run_pending_migrations(conn, current_version=1, target_version=1)

        # --- Assert ---
        # success should be True (no-op success)
        # Schema should be unchanged
        """
        # --- Act ---
        success = run_pending_migrations(migrated_conn, current_version=1, target_version=1)

        # --- Assert ---
        assert success is True, "No-op migration should return True"

        # --- Assert: schema version unchanged ---
        version = read_schema_version(migrated_conn)
        assert version == 1, f"Schema version should still be 1 after no-op, got {version}"
